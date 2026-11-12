"""PV performance formulas."""

from __future__ import annotations

import math

import pytest

from solarwise.core.pv_model import (
    cell_temperature_faiman,
    cell_temperature_noct,
    degradation_factor,
    energy_weighted_irradiance_from_daily,
    expected_energy_kwh,
    performance_ratio,
    temperature_corrected_pr,
    temperature_factor,
)

pytestmark = pytest.mark.scientific


def test_noct_model_reproduces_its_definition() -> None:
    # By definition a module is at NOCT with 800 W/m2 and 20 degC ambient.
    assert cell_temperature_noct(20.0, 800.0, noct_c=45.0) == pytest.approx(45.0)
    assert cell_temperature_noct(30.0, 0.0) == pytest.approx(30.0)
    assert cell_temperature_noct(35.0, 1000.0, noct_c=45.0) == pytest.approx(35.0 + 25.0 / 800.0 * 1000.0)


def test_faiman_model() -> None:
    assert cell_temperature_faiman(25.0, 1000.0, 0.0) == pytest.approx(25.0 + 1000.0 / 25.0)
    assert cell_temperature_faiman(25.0, 1000.0, 5.0) == pytest.approx(25.0 + 1000.0 / (25.0 + 6.84 * 5.0))
    # Wind cools the module.
    assert cell_temperature_faiman(25.0, 1000.0, 5.0) < cell_temperature_faiman(25.0, 1000.0, 1.0)


def test_thermal_models_reject_impossible_inputs() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        cell_temperature_noct(25.0, -5.0)
    with pytest.raises(ValueError, match="non-negative"):
        cell_temperature_faiman(25.0, 500.0, -1.0)
    with pytest.raises(ValueError, match="non-finite"):
        cell_temperature_noct(math.nan, 500.0)


def test_temperature_factor() -> None:
    assert temperature_factor(25.0, -0.0035) == pytest.approx(1.0)
    assert temperature_factor(65.0, -0.0035) == pytest.approx(0.86)
    assert temperature_factor(5.0, -0.0035) == pytest.approx(1.07)
    assert temperature_factor(1000.0, -0.0035) == 0.0  # never negative


def test_expected_energy_formula() -> None:
    # 10 MWp x 6 kWh/m2 x (1 - 0.0035 x 20) x (1 - 0.14)
    energy = expected_energy_kwh(10_000.0, 6.0, 45.0, -0.0035, 0.14)
    assert energy == pytest.approx(10_000.0 * 6.0 * 0.93 * 0.86)


def test_expected_energy_respects_the_ac_limit_and_degradation() -> None:
    assert expected_energy_kwh(10_000.0, 1.0, 25.0, -0.0035, 0.0, ac_limit_kwh=8_500.0) == pytest.approx(8_500.0)
    assert expected_energy_kwh(10_000.0, 1.0, 25.0, -0.0035, 0.0, degradation=0.95) == pytest.approx(9_500.0)


def test_expected_energy_rejects_impossible_inputs() -> None:
    with pytest.raises(ValueError):
        expected_energy_kwh(-1.0, 6.0, 45.0, -0.0035, 0.14)
    with pytest.raises(ValueError):
        expected_energy_kwh(10_000.0, -6.0, 45.0, -0.0035, 0.14)
    with pytest.raises(ValueError):
        expected_energy_kwh(10_000.0, 6.0, 45.0, -0.0035, 1.2)


def test_performance_ratio() -> None:
    # IEC 61724-1: PR = final yield / reference yield.
    assert performance_ratio(48_000.0, 10_000.0, 6.0) == pytest.approx(0.8)
    assert performance_ratio(None, 10_000.0, 6.0) is None
    assert performance_ratio(48_000.0, 10_000.0, 0.0) is None
    assert performance_ratio(48_000.0, 0.0, 6.0) is None


def test_temperature_corrected_pr_removes_the_thermal_loss() -> None:
    gamma = -0.0035
    poa = [6.0, 6.5, 5.5]
    temps = [45.0, 55.0, 35.0]
    energies = [10_000.0 * h * 0.86 * (1.0 + gamma * (t - 25.0)) for h, t in zip(poa, temps, strict=True)]
    assert temperature_corrected_pr(energies, poa, temps, 10_000.0, gamma) == pytest.approx(0.86)


def test_degradation_factor() -> None:
    assert degradation_factor(0.0, 0.005) == pytest.approx(1.0)
    assert degradation_factor(10.0, 0.005) == pytest.approx(0.995**10)
    # Before commissioning there is nothing to degrade.
    assert degradation_factor(-1.0, 0.005) == pytest.approx(1.0)
    with pytest.raises(ValueError, match="rate"):
        degradation_factor(5.0, 1.5)


def test_energy_weighted_irradiance_of_a_half_sine_day() -> None:
    # H = 6 kWh/m2 over 12 h -> (pi^2 / 8) x 500 W/m2
    assert energy_weighted_irradiance_from_daily(6.0, 12.0) == pytest.approx(math.pi**2 / 8.0 * 500.0)
    assert energy_weighted_irradiance_from_daily(6.0, 0.0) == 0.0
