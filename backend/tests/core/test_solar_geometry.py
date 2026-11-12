"""Solar geometry against published worked examples (FAO Irrigation and Drainage Paper 56)."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime

import pytest

from solarwise.core.solar_geometry import (
    day_of_year,
    daylight_hours,
    declination_rad,
    erbs_daily_diffuse_fraction,
    extraterrestrial_daily_horizontal_kwh_m2,
    hour_angle_rad,
    inverse_relative_distance,
    rb_daily_equator_facing,
    sun_elevation_deg,
    sunset_hour_angle_rad,
    transpose_daily_isotropic,
)

pytestmark = pytest.mark.scientific


def test_fao56_example_8_extraterrestrial_radiation() -> None:
    """FAO-56 Example 8: 20 degS on 3 September (J = 246) -> Ra = 32.2 MJ m-2 day-1."""
    doy = day_of_year(date(2025, 9, 3))
    assert doy == 246
    assert inverse_relative_distance(doy) == pytest.approx(0.985, abs=5e-4)
    assert declination_rad(doy) == pytest.approx(0.120, abs=5e-4)
    assert sunset_hour_angle_rad(-20.0, doy) == pytest.approx(1.527, abs=5e-4)
    ra_mj = extraterrestrial_daily_horizontal_kwh_m2(-20.0, doy) * 3.6
    assert ra_mj == pytest.approx(32.2, abs=0.05)


def test_fao56_example_9_daylight_hours() -> None:
    """FAO-56 Example 9: same place and day -> N = 11.7 h."""
    assert daylight_hours(-20.0, 246) == pytest.approx(11.7, abs=0.05)


def test_equinox_day_length_is_twelve_hours_everywhere() -> None:
    doy = day_of_year(date(2026, 3, 21))
    for latitude in (-45.0, 0.0, 33.5, 60.0):
        assert daylight_hours(latitude, doy) == pytest.approx(12.0, abs=0.15)


def test_polar_night_and_midnight_sun() -> None:
    assert daylight_hours(80.0, 355) == 0.0
    assert daylight_hours(80.0, 172) == 24.0
    assert extraterrestrial_daily_horizontal_kwh_m2(80.0, 355) == 0.0


def test_latitude_out_of_range_is_rejected() -> None:
    with pytest.raises(ValueError, match="latitude"):
        extraterrestrial_daily_horizontal_kwh_m2(95.0, 100)


def test_sun_is_highest_near_local_solar_noon() -> None:
    # 6.8 degE: solar noon falls around 11:33 UTC (before the equation of time).
    noon = datetime(2026, 6, 21, 11, 33, tzinfo=UTC)
    elevation = sun_elevation_deg(noon, 33.5, 6.8)
    assert elevation == pytest.approx(90.0 - 33.5 + 23.44, abs=0.6)
    assert abs(hour_angle_rad(noon, 6.8)) < math.radians(1.5)
    assert sun_elevation_deg(datetime(2026, 6, 21, 0, 0, tzinfo=UTC), 33.5, 6.8) < 0.0


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="aware"):
        sun_elevation_deg(datetime(2026, 6, 21, 12, 0), 33.5, 6.8)


def test_tilt_factor_is_one_for_horizontal_plane() -> None:
    assert rb_daily_equator_facing(33.5, 0.0, 100) == pytest.approx(1.0)


def test_tilt_towards_equator_gains_in_winter_and_loses_in_summer() -> None:
    winter = rb_daily_equator_facing(33.5, 30.0, 355)
    summer = rb_daily_equator_facing(33.5, 30.0, 172)
    assert winter is not None and summer is not None
    assert winter > 1.5
    assert summer < 1.0


def test_erbs_diffuse_fraction_limits() -> None:
    assert erbs_daily_diffuse_fraction(0.0, 90.0) == pytest.approx(1.0)
    assert erbs_daily_diffuse_fraction(0.75, 90.0) == pytest.approx(0.175)
    assert erbs_daily_diffuse_fraction(0.75, 70.0) == pytest.approx(0.143)
    assert 0.2 < erbs_daily_diffuse_fraction(0.6, 90.0) < 0.5


def test_transposition_components_add_up() -> None:
    result = transpose_daily_isotropic(6.5, 33.5, 30.0, 120)
    assert result is not None
    assert result.poa_kwh_m2 == pytest.approx(
        result.beam_kwh_m2 + result.sky_diffuse_kwh_m2 + result.ground_reflected_kwh_m2
    )
    assert 0.0 < result.clearness_index < 1.0


def test_transposition_of_horizontal_plane_returns_the_input() -> None:
    result = transpose_daily_isotropic(6.5, 33.5, 0.0, 120)
    assert result is not None
    assert result.poa_kwh_m2 == pytest.approx(6.5)


def test_transposition_rejects_irradiation_above_extraterrestrial() -> None:
    with pytest.raises(ValueError, match="exceeds the extraterrestrial"):
        transpose_daily_isotropic(20.0, 33.5, 30.0, 355)


def test_transposition_rejects_negative_irradiation() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        transpose_daily_isotropic(-1.0, 33.5, 30.0, 120)
