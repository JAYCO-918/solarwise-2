"""Solar geometry and daily irradiation on tilted planes.

These are deterministic astronomical relations.  They are used for

* plausibility checks on irradiance data (global horizontal irradiation can not
  exceed the extraterrestrial value),
* identifying daylight intervals, so that missing night-time records are not
  counted as missing production,
* intraday signature analysis (losses concentrated near sunrise or sunset),
* a first-order transposition of daily horizontal irradiation to a fixed,
  equator-facing plane when no in-plane measurement exists.

References
----------
* Allen, Pereira, Raes, Smith (1998). *Crop evapotranspiration*, FAO Irrigation
  and Drainage Paper 56, eqs. 21-34 (extraterrestrial radiation, declination,
  sunset hour angle, daylight hours, seasonal correction for solar time).
* Liu & Jordan (1962/1963) isotropic-sky model for tilted surfaces, as given in
  Duffie & Beckman, *Solar Engineering of Thermal Processes*.
* Erbs, Klein, Duffie (1982). Estimation of the diffuse radiation fraction for
  hourly, daily and monthly-average global radiation. *Solar Energy* 28(4).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

#: Solar constant used by FAO-56 [MJ m-2 min-1] (equivalent to 1366.7 W/m2).
SOLAR_CONSTANT_MJ_M2_MIN = 0.0820
_MJ_PER_KWH = 3.6


def _check_latitude(latitude_deg: float) -> None:
    if not -90.0 <= latitude_deg <= 90.0:
        raise ValueError(f"latitude {latitude_deg} outside [-90, 90]")


def day_of_year(d: date) -> int:
    return d.timetuple().tm_yday


def inverse_relative_distance(doy: int) -> float:
    """Inverse relative Earth-Sun distance, FAO-56 eq. 23."""
    return 1.0 + 0.033 * math.cos(2.0 * math.pi * doy / 365.0)


def declination_rad(doy: int) -> float:
    """Solar declination [rad], FAO-56 eq. 24."""
    return 0.409 * math.sin(2.0 * math.pi * doy / 365.0 - 1.39)


def sunset_hour_angle_rad(latitude_deg: float, doy: int) -> float:
    """Sunset hour angle [rad], FAO-56 eq. 25.  Clamped for polar day/night."""
    _check_latitude(latitude_deg)
    phi = math.radians(latitude_deg)
    x = -math.tan(phi) * math.tan(declination_rad(doy))
    return math.acos(max(-1.0, min(1.0, x)))


def daylight_hours(latitude_deg: float, doy: int) -> float:
    """Astronomical day length [h], FAO-56 eq. 34."""
    return 24.0 / math.pi * sunset_hour_angle_rad(latitude_deg, doy)


def extraterrestrial_daily_horizontal_kwh_m2(latitude_deg: float, doy: int) -> float:
    """Daily extraterrestrial irradiation on a horizontal plane [kWh/m2], FAO-56 eq. 21."""
    phi = math.radians(latitude_deg)
    delta = declination_rad(doy)
    ws = sunset_hour_angle_rad(latitude_deg, doy)
    ra_mj = (
        (24.0 * 60.0 / math.pi)
        * SOLAR_CONSTANT_MJ_M2_MIN
        * inverse_relative_distance(doy)
        * (ws * math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.sin(ws))
    )
    return max(ra_mj, 0.0) / _MJ_PER_KWH


def equation_of_time_hours(doy: int) -> float:
    """Seasonal correction for solar time [h], FAO-56 eq. 32-33."""
    b = 2.0 * math.pi * (doy - 81) / 364.0
    return 0.1645 * math.sin(2.0 * b) - 0.1255 * math.cos(b) - 0.025 * math.sin(b)


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("a timezone-aware datetime is required")
    return moment.astimezone(UTC)


def solar_time_hours(moment: datetime, longitude_east_deg: float) -> float:
    """Apparent solar time [h, 0-24) at ``longitude_east_deg`` for an aware datetime."""
    utc = _as_utc(moment)
    hours = utc.hour + utc.minute / 60.0 + utc.second / 3600.0
    local_solar_date = (utc + timedelta(hours=longitude_east_deg / 15.0)).date()
    eot = equation_of_time_hours(day_of_year(local_solar_date))
    return (hours + longitude_east_deg / 15.0 + eot) % 24.0


def hour_angle_rad(moment: datetime, longitude_east_deg: float) -> float:
    """Solar hour angle [rad]: negative before solar noon, positive after."""
    return math.pi / 12.0 * (solar_time_hours(moment, longitude_east_deg) - 12.0)


def sun_elevation_deg(moment: datetime, latitude_deg: float, longitude_east_deg: float) -> float:
    """Solar elevation above the horizon [deg] (no refraction correction)."""
    _check_latitude(latitude_deg)
    utc = _as_utc(moment)
    local_solar_date = (utc + timedelta(hours=longitude_east_deg / 15.0)).date()
    delta = declination_rad(day_of_year(local_solar_date))
    phi = math.radians(latitude_deg)
    omega = hour_angle_rad(utc, longitude_east_deg)
    sin_alpha = math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.cos(omega)
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_alpha))))


def is_daylight(
    moment: datetime, latitude_deg: float, longitude_east_deg: float, min_elevation_deg: float = 0.0
) -> bool:
    return sun_elevation_deg(moment, latitude_deg, longitude_east_deg) > min_elevation_deg


def _plane_latitude_rad(latitude_deg: float, tilt_deg: float) -> float:
    """Equivalent latitude of a plane tilted towards the equator."""
    phi = math.radians(latitude_deg)
    beta = math.radians(tilt_deg)
    return phi - beta if latitude_deg >= 0.0 else phi + beta


def cos_incidence_equator_facing(
    latitude_deg: float, tilt_deg: float, declination: float, hour_angle: float
) -> float:
    """Cosine of the beam incidence angle on a fixed plane tilted towards the equator."""
    phi_p = _plane_latitude_rad(latitude_deg, tilt_deg)
    return math.sin(declination) * math.sin(phi_p) + math.cos(declination) * math.cos(phi_p) * math.cos(
        hour_angle
    )


def rb_daily_equator_facing(latitude_deg: float, tilt_deg: float, doy: int) -> float | None:
    """Daily beam tilt factor R_b for a fixed plane tilted towards the equator.

    Ratio of daily extraterrestrial irradiation on the tilted plane to that on
    the horizontal (Liu & Jordan).  Returns ``None`` during polar night.
    """
    _check_latitude(latitude_deg)
    if not 0.0 <= tilt_deg <= 90.0:
        raise ValueError(f"tilt {tilt_deg} outside [0, 90]")
    phi = math.radians(latitude_deg)
    phi_p = _plane_latitude_rad(latitude_deg, tilt_deg)
    delta = declination_rad(doy)
    ws = sunset_hour_angle_rad(latitude_deg, doy)
    ws_plane = math.acos(max(-1.0, min(1.0, -math.tan(phi_p) * math.tan(delta))))
    ws_t = min(ws, ws_plane)
    num = math.cos(phi_p) * math.cos(delta) * math.sin(ws_t) + ws_t * math.sin(phi_p) * math.sin(delta)
    den = math.cos(phi) * math.cos(delta) * math.sin(ws) + ws * math.sin(phi) * math.sin(delta)
    if den <= 1e-9:
        return None
    return max(num, 0.0) / den


def erbs_daily_diffuse_fraction(clearness_index: float, sunset_hour_angle_deg: float) -> float:
    """Daily diffuse fraction H_d/H from the daily clearness index (Erbs et al., 1982)."""
    if not math.isfinite(clearness_index) or clearness_index < 0.0:
        raise ValueError("clearness index must be a finite, non-negative number")
    kt = clearness_index
    if sunset_hour_angle_deg <= 81.4:
        if kt < 0.715:
            return 1.0 - 0.2727 * kt + 2.4495 * kt**2 - 11.9514 * kt**3 + 9.3879 * kt**4
        return 0.143
    if kt < 0.722:
        return 1.0 + 0.2832 * kt - 2.5557 * kt**2 + 0.8448 * kt**3
    return 0.175


@dataclass(frozen=True)
class DailyTransposition:
    """Result of transposing daily horizontal irradiation to a tilted plane."""

    poa_kwh_m2: float
    beam_kwh_m2: float
    sky_diffuse_kwh_m2: float
    ground_reflected_kwh_m2: float
    clearness_index: float
    diffuse_fraction: float
    rb: float


def transpose_daily_isotropic(
    ghi_kwh_m2: float,
    latitude_deg: float,
    tilt_deg: float,
    doy: int,
    albedo: float = 0.2,
) -> DailyTransposition | None:
    """Daily global horizontal -> plane-of-array irradiation (isotropic sky).

    Valid for a *fixed* plane tilted towards the equator.  It is a model, so the
    result must be tagged ``MODELLED``; it is not suitable for tracking systems.
    Returns ``None`` when the computation is undefined (polar night) and raises
    ``ValueError`` for physically impossible inputs.
    """
    if not math.isfinite(ghi_kwh_m2) or ghi_kwh_m2 < 0.0:
        raise ValueError("global horizontal irradiation must be finite and non-negative")
    if not 0.0 <= albedo <= 1.0:
        raise ValueError("albedo must be within [0, 1]")
    h0 = extraterrestrial_daily_horizontal_kwh_m2(latitude_deg, doy)
    rb = rb_daily_equator_facing(latitude_deg, tilt_deg, doy)
    if h0 <= 1e-9 or rb is None:
        return None
    kt = ghi_kwh_m2 / h0
    if kt > 1.0:
        raise ValueError(
            f"global horizontal irradiation {ghi_kwh_m2:.3f} kWh/m2 exceeds the "
            f"extraterrestrial value {h0:.3f} kWh/m2"
        )
    ws_deg = math.degrees(sunset_hour_angle_rad(latitude_deg, doy))
    fd = min(1.0, max(0.0, erbs_daily_diffuse_fraction(kt, ws_deg)))
    beta = math.radians(tilt_deg)
    diffuse_h = fd * ghi_kwh_m2
    beam_h = ghi_kwh_m2 - diffuse_h
    beam_t = beam_h * rb
    sky_t = diffuse_h * (1.0 + math.cos(beta)) / 2.0
    ground_t = ghi_kwh_m2 * albedo * (1.0 - math.cos(beta)) / 2.0
    return DailyTransposition(
        poa_kwh_m2=beam_t + sky_t + ground_t,
        beam_kwh_m2=beam_t,
        sky_diffuse_kwh_m2=sky_t,
        ground_reflected_kwh_m2=ground_t,
        clearness_index=kt,
        diffuse_fraction=fd,
        rb=rb,
    )
