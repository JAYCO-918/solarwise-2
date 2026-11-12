"""Synthetic demonstration datasets.

Everything produced here is **artificial**.  The generator builds plausible
weather and production series for a utility-scale plant in a Saharan climate
and injects one known effect per scenario, so that the behaviour of the
engines can be shown and tested against a known ground truth.

What is real and what is not
----------------------------
* The *reference case* - El Foulia, Guemar, El Oued, nominal 300 MWp - is public
  information about an existing plant and is used only as a setting.
* Every technical parameter (tilt, temperature coefficient, system losses, AC
  rating, block layout) is an illustrative assumption.
* Every time series is computed by this module from a seeded pseudo-random
  generator.  None of it was measured at El Foulia or anywhere else, and none
  of it describes how that plant actually operates.

Reproducibility: the same ``seed`` always yields exactly the same dataset.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from solarwise.core.models import DeviceSpec, PlantSpec, TrackingType
from solarwise.core.pv_model import (
    cell_temperature_faiman,
    energy_weighted_irradiance_from_daily,
    temperature_factor,
)
from solarwise.core.solar_geometry import (
    cos_incidence_equator_facing,
    day_of_year,
    daylight_hours,
    declination_rad,
    extraterrestrial_daily_horizontal_kwh_m2,
    hour_angle_rad,
    sun_elevation_deg,
    sunset_hour_angle_rad,
    transpose_daily_isotropic,
)

GENERATOR_NAME = "solarwise.demo.generator"
GENERATOR_VERSION = "1.0.0"
DEFAULT_SEED = 20260607

SYNTHETIC_STATEMENT = (
    "SYNTHETIC DEMONSTRATION DATASET. Every value was computed by the SolarWise DZ scenario generator from a "
    "seeded pseudo-random sequence. It contains no measurement from the El Foulia plant or from any other "
    "plant and does not describe the actual operation of any plant. The plant name, location and nominal "
    "capacity are public reference information; all technical parameters are illustrative assumptions."
)

_ILLUSTRATIVE = "Illustrative assumption for the demonstration - not the actual design of the plant."

#: The reference setting used by every scenario.
REFERENCE_PLANT = PlantSpec(
    name="El Foulia reference case (synthetic data)",
    capacity_dc_kwp=300_000.0,
    capacity_ac_kw=250_000.0,
    latitude=33.49,
    longitude=6.80,
    timezone="Africa/Algiers",
    tracking=TrackingType.FIXED,
    tilt_deg=30.0,
    azimuth_deg=180.0,
    module_temp_coeff_per_c=-0.0035,
    noct_c=45.0,
    system_loss_fraction=0.14,
    is_demonstration=True,
    parameter_notes={
        "capacity_dc_kwp": "Nominal capacity of the public reference case (300 MWp).",
        "latitude": "Approximate location of Guemar, El Oued (not a surveyed site coordinate).",
        "longitude": "Approximate location of Guemar, El Oued (not a surveyed site coordinate).",
        "capacity_ac_kw": _ILLUSTRATIVE,
        "tracking": _ILLUSTRATIVE,
        "tilt_deg": _ILLUSTRATIVE,
        "azimuth_deg": _ILLUSTRATIVE,
        "module_temp_coeff_per_c": _ILLUSTRATIVE,
        "noct_c": _ILLUSTRATIVE,
        "system_loss_fraction": _ILLUSTRATIVE,
    },
)

#: Hypothetical layout: 20 blocks of 15 MWp.  Not the plant's real topology.
REFERENCE_DEVICES: tuple[DeviceSpec, ...] = tuple(
    DeviceSpec(code=f"BLK-{i:02d}", capacity_kwp=15_000.0, kind="INVERTER_BLOCK") for i in range(1, 21)
)


@dataclass
class DayWeather:
    day: date
    ghi_kwh_m2: float
    poa_kwh_m2: float
    ambient_temp_c: float
    wind_speed_ms: float
    module_temp_c: float
    precipitation_mm: float = 0.0


@dataclass
class Effects:
    """Effects injected into the clean production of a scenario."""

    #: day index -> soiling ratio of the array (true state).
    soiling_ratio: dict[int, float] = field(default_factory=dict)
    #: day index -> value reported by the soiling sensor (defaults to the true state + noise).
    reported_soiling_ratio: dict[int, float] | None = None
    #: day index -> capacity-weighted availability.
    availability: dict[int, float] = field(default_factory=dict)
    #: day index -> set of device codes that are out of service.
    devices_down: dict[int, frozenset[str]] = field(default_factory=dict)
    #: day indices on which production telemetry is missing.
    missing_actual_days: frozenset[int] = frozenset()
    #: day indices for which no row exists at all.
    absent_days: frozenset[int] = frozenset()
    #: Fraction of production lost during the first third of the day (hourly scenarios).
    morning_shading_loss: float = 0.0
    #: day index -> active-power cap as a fraction of AC capacity, 10:00-15:59 local (hourly scenarios).
    curtailment_cap: dict[int, float] = field(default_factory=dict)
    #: The baseline delivered with the data ignores temperature (rated at 25 degC).
    baseline_ignores_temperature: bool = False


def _rng(seed: int, key: str) -> random.Random:
    """Independent, reproducible stream per (seed, scenario)."""
    return random.Random(f"{seed}:{key}")


def generate_weather(start: date, days: int, plant: PlantSpec, rng: random.Random) -> list[DayWeather]:
    """Plausible daily weather for a dry Saharan site (artificial)."""
    assert plant.tilt_deg is not None
    out: list[DayWeather] = []
    for index in range(days):
        day = start + timedelta(days=index)
        doy = day_of_year(day)
        ra = extraterrestrial_daily_horizontal_kwh_m2(plant.latitude, doy)
        clearness = rng.uniform(0.42, 0.55) if rng.random() < 0.06 else min(0.76, max(0.5, rng.gauss(0.69, 0.025)))
        ghi = clearness * ra
        transposed = transpose_daily_isotropic(ghi, plant.latitude, plant.tilt_deg, doy)
        assert transposed is not None
        poa = transposed.poa_kwh_m2
        ambient = 24.0 + 12.0 * math.cos(2.0 * math.pi * (doy - 205) / 365.0) + rng.gauss(0.0, 1.5)
        wind = min(9.0, max(0.5, rng.gauss(3.2, 0.9)))
        irradiance = energy_weighted_irradiance_from_daily(poa, daylight_hours(plant.latitude, doy))
        module = cell_temperature_faiman(ambient, irradiance, wind) + rng.gauss(0.0, 0.6)
        out.append(DayWeather(day, ghi, poa, ambient, wind, module))
    return out


def clean_energy_kwh(plant: PlantSpec, poa_kwh_m2: float, module_temp_c: float) -> float:
    """Energy of the clean, fully available reference plant (the generator's ground truth)."""
    assert plant.module_temp_coeff_per_c is not None and plant.system_loss_fraction is not None
    return (
        plant.capacity_dc_kwp
        * poa_kwh_m2
        * temperature_factor(module_temp_c, plant.module_temp_coeff_per_c)
        * (1.0 - plant.system_loss_fraction)
    )


def _iso_local(moment: datetime) -> str:
    return moment.isoformat(timespec="minutes")


def generate_daily_rows(
    weather: list[DayWeather],
    plant: PlantSpec,
    effects: Effects,
    rng: random.Random,
    *,
    devices: tuple[DeviceSpec, ...] = (),
    include_soiling_channel: bool = True,
    include_availability: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Daily plant-level rows and (optionally) device-level rows."""
    zone = ZoneInfo(plant.timezone)
    rows: list[dict[str, Any]] = []
    device_rows: list[dict[str, Any]] = []
    total_capacity = sum(d.capacity_kwp for d in devices)
    for index, w in enumerate(weather):
        if index in effects.absent_days:
            continue
        stamp = _iso_local(datetime.combine(w.day, time.min, tzinfo=zone))
        clean = clean_energy_kwh(plant, w.poa_kwh_m2, w.module_temp_c)
        if effects.baseline_ignores_temperature:
            assert plant.system_loss_fraction is not None
            expected = plant.capacity_dc_kwp * w.poa_kwh_m2 * (1.0 - plant.system_loss_fraction)
        else:
            expected = clean
        expected *= 1.0 + rng.gauss(0.0, 0.004)
        soiling = effects.soiling_ratio.get(index, 1.0)
        availability = effects.availability.get(index, 1.0)
        down = effects.devices_down.get(index, frozenset())

        if devices:
            produced = 0.0
            for device in devices:
                share = device.capacity_kwp / total_capacity
                energy = 0.0 if device.code in down else clean * share * soiling * (1.0 + rng.gauss(0.0, 0.004))
                produced += energy
                device_rows.append(
                    {"timestamp": stamp, "device_code": device.code, "actual_energy_kwh": round(energy, 1)}
                )
            actual = produced
            if down:
                availability = 1.0 - sum(d.capacity_kwp for d in devices if d.code in down) / total_capacity
        else:
            actual = clean * soiling * availability * (1.0 + rng.gauss(0.0, 0.003))

        row: dict[str, Any] = {
            "timestamp": stamp,
            "actual_energy_kwh": None if index in effects.missing_actual_days else round(actual, 1),
            "expected_energy_kwh": round(expected, 1),
            "poa_irradiation_kwh_m2": round(w.poa_kwh_m2, 4),
            "ghi_kwh_m2": round(w.ghi_kwh_m2, 4),
            "ambient_temp_c": round(w.ambient_temp_c, 2),
            "module_temp_c": round(w.module_temp_c, 2),
            "wind_speed_ms": round(w.wind_speed_ms, 2),
            "precipitation_mm": round(w.precipitation_mm, 2),
        }
        if include_availability:
            row["availability_fraction"] = round(availability, 4)
        if include_soiling_channel:
            if effects.reported_soiling_ratio is not None:
                reported = effects.reported_soiling_ratio.get(index, 1.0)
            else:
                reported = soiling
            row["soiling_ratio"] = round(min(1.05, max(0.0, reported + rng.gauss(0.0, 0.002))), 4)
        rows.append(row)
    return rows, device_rows


def generate_hourly_rows(
    weather: list[DayWeather],
    plant: PlantSpec,
    effects: Effects,
    rng: random.Random,
    *,
    include_soiling_channel: bool = True,
    include_curtailment_log: bool = False,
) -> list[dict[str, Any]]:
    """Hourly plant-level rows.  Daily irradiation is distributed with the clear-day incidence profile."""
    assert plant.tilt_deg is not None and plant.capacity_ac_kw is not None
    zone = ZoneInfo(plant.timezone)
    ac_limit = plant.capacity_ac_kw  # kWh per hour
    rows: list[dict[str, Any]] = []
    for index, w in enumerate(weather):
        doy = day_of_year(w.day)
        declination = declination_rad(doy)
        sunset = sunset_hour_angle_rad(plant.latitude, doy)
        hours: list[tuple[datetime, float, float]] = []  # start (local), hour angle at midpoint, weight
        for hour in range(24):
            start = datetime.combine(w.day, time(hour=hour), tzinfo=zone)
            midpoint = (start + timedelta(minutes=30)).astimezone(UTC)
            omega = hour_angle_rad(midpoint, plant.longitude)
            up = sun_elevation_deg(midpoint, plant.latitude, plant.longitude) > 0.0
            weight = max(0.0, cos_incidence_equator_facing(plant.latitude, plant.tilt_deg, declination, omega)) if up else 0.0
            hours.append((start, omega, weight))
        total_weight = sum(weight for _, _, weight in hours) or 1.0
        soiling = effects.soiling_ratio.get(index, 1.0)
        cap = effects.curtailment_cap.get(index)
        for start, omega, weight in hours:
            poa = w.poa_kwh_m2 * weight / total_weight
            ambient = w.ambient_temp_c + 4.5 * math.cos(2.0 * math.pi * (start.hour + 0.5 - 15.0) / 24.0) - 1.5
            module = (
                cell_temperature_faiman(ambient, poa * 1000.0, w.wind_speed_ms) + rng.gauss(0.0, 0.5)
                if poa > 0 else ambient
            )
            clean = min(ac_limit, clean_energy_kwh(plant, poa, module))
            expected = clean * (1.0 + rng.gauss(0.0, 0.004)) if clean > 0 else 0.0
            actual = clean * soiling * (1.0 + rng.gauss(0.0, 0.003)) if clean > 0 else 0.0
            if effects.morning_shading_loss and weight > 0 and omega < -sunset / 3.0:
                actual *= 1.0 - effects.morning_shading_loss
            curtailed = 0.0
            if cap is not None and 10 <= start.hour <= 15:
                # The plant controller holds the set-point with a small regulation error.
                ceiling = cap * ac_limit * (1.0 + rng.gauss(0.0, 0.0015))
                if actual > ceiling:
                    curtailed = actual - ceiling
                    actual = ceiling
            row: dict[str, Any] = {
                "timestamp": _iso_local(start),
                "actual_energy_kwh": round(actual, 1),
                "expected_energy_kwh": round(expected, 1),
                "poa_irradiation_kwh_m2": round(poa, 5),
                "ambient_temp_c": round(ambient, 2),
                "module_temp_c": round(module, 2),
                "wind_speed_ms": round(w.wind_speed_ms, 2),
            }
            if include_curtailment_log:
                # The plant controller's own estimate of the withheld energy (with its own error).
                row["curtailed_energy_kwh"] = round(curtailed * (1.0 + rng.gauss(0.0, 0.01)), 1) if curtailed > 0 else 0.0
            if include_soiling_channel and weight > 0:
                row["soiling_ratio"] = round(min(1.05, max(0.0, soiling + rng.gauss(0.0, 0.002))), 4)
            rows.append(row)
    return rows


def stream(seed: int, key: str) -> random.Random:
    """Public accessor for the per-scenario random stream."""
    return _rng(seed, key)
