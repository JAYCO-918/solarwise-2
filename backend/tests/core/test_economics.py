"""Cleaning economics: formulas, scenarios, incomplete inputs."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from solarwise.core.economics import (
    EconomicInputs,
    EconomicStatus,
    EnergyValueBasis,
    ScenarioName,
    Verdict,
    build_costs,
    evaluate_economics,
)
from solarwise.core.recoverable import EnergyRange
from tests.builders import economic_inputs

ENERGY = EnergyRange(low=20_000.0, central=30_000.0, high=45_000.0)


def test_formulas_of_the_base_scenario() -> None:
    result = evaluate_economics(ENERGY, economic_inputs(cost_uncertainty_pct=0.0))
    base = result.scenario(ScenarioName.BASE)
    assert result.cost.total == pytest.approx(100_000.0)
    assert base.gross_benefit == pytest.approx(30_000.0 * 5.0)
    assert base.net_benefit == pytest.approx(150_000.0 - 100_000.0)
    assert base.roi_pct == pytest.approx(50.0)
    assert result.break_even_energy_kwh == pytest.approx(100_000.0 / 5.0)


def test_scenarios_combine_energy_and_cost_extremes() -> None:
    result = evaluate_economics(ENERGY, economic_inputs())
    conservative = result.scenario(ScenarioName.CONSERVATIVE)
    optimistic = result.scenario(ScenarioName.OPTIMISTIC)
    assert conservative.recoverable_energy_kwh == 20_000.0
    assert conservative.total_cost == pytest.approx(120_000.0)
    assert conservative.net_benefit == pytest.approx(20_000.0 * 5.0 - 120_000.0)
    assert optimistic.total_cost == pytest.approx(80_000.0)
    assert optimistic.net_benefit == pytest.approx(45_000.0 * 5.0 - 80_000.0)


def test_verdicts() -> None:
    profitable = evaluate_economics(EnergyRange(low=40_000.0, central=50_000.0, high=60_000.0), economic_inputs())
    assert profitable.verdict is Verdict.PROFITABLE
    marginal = evaluate_economics(ENERGY, economic_inputs())
    assert marginal.verdict is Verdict.MARGINAL  # base +50 000, conservative -20 000
    unprofitable = evaluate_economics(EnergyRange(low=5_000.0, central=10_000.0, high=15_000.0), economic_inputs())
    assert unprofitable.verdict is Verdict.UNPROFITABLE
    assert unprofitable.scenario(ScenarioName.BASE).net_benefit == pytest.approx(-50_000.0)


def test_costs_computed_from_quantities() -> None:
    inputs = EconomicInputs(
        energy_value_per_kwh=5.0, energy_value_basis=EnergyValueBasis.SELLING_PRICE,
        water_volume_m3=100.0, water_price_per_m3=80.0,
        labour_hours=200.0, labour_rate_per_hour=400.0,
        equipment_cost=0.0, operational_cost=0.0, downtime_energy_kwh=1_000.0,
    )
    costs = build_costs(inputs)
    by_name = {item.name: item for item in costs.items}
    assert by_name["water"].amount == pytest.approx(8_000.0)
    assert by_name["labour"].amount == pytest.approx(80_000.0)
    assert by_name["downtime"].amount == pytest.approx(5_000.0)  # energy not produced x energy value
    assert by_name["water"].basis == "COMPUTED"
    assert costs.total == pytest.approx(93_000.0)
    assert costs.missing == []


@pytest.mark.safety
def test_a_missing_cost_is_not_counted_as_zero() -> None:
    result = evaluate_economics(ENERGY, economic_inputs(labour_cost=None))
    assert result.status is EconomicStatus.INCOMPLETE_INPUTS
    assert result.verdict is Verdict.UNDETERMINED
    assert result.cost.total is None
    assert result.cost.missing == ["labour"]
    assert result.cost.partial_total == pytest.approx(40_000.0)
    base = result.scenario(ScenarioName.BASE)
    assert base.gross_benefit == pytest.approx(150_000.0)
    assert base.net_benefit is None and base.roi_pct is None and base.profitable is None
    assert not result.decision_grade
    assert "labour cost" in result.missing_inputs


def test_an_explicit_zero_cost_is_accepted() -> None:
    result = evaluate_economics(ENERGY, economic_inputs(water_cost=0.0))
    assert result.status is EconomicStatus.COMPLETE
    assert result.cost.total == pytest.approx(90_000.0)


def test_no_inputs_at_all() -> None:
    result = evaluate_economics(ENERGY, None)
    assert result.status is EconomicStatus.INCOMPLETE_INPUTS
    assert result.energy_value_per_kwh is None
    assert len(result.missing_inputs) == 7  # value, basis and five cost items
    assert all(s.net_benefit is None for s in result.scenarios)


def test_missing_energy_value_basis_is_incomplete() -> None:
    result = evaluate_economics(ENERGY, economic_inputs(energy_value_basis=None))
    assert result.status is EconomicStatus.INCOMPLETE_INPUTS
    assert not result.decision_grade


@pytest.mark.safety
def test_consumer_tariff_proxy_is_not_decision_grade() -> None:
    result = evaluate_economics(ENERGY, economic_inputs(energy_value_basis=EnergyValueBasis.CONSUMER_TARIFF_PROXY))
    assert result.status is EconomicStatus.COMPLETE  # the arithmetic is shown ...
    assert not result.decision_grade                 # ... but no decision may rest on it
    assert any("consumer tariff" in w for w in result.warnings)


def test_no_recoverable_energy() -> None:
    result = evaluate_economics(EnergyRange(), economic_inputs())
    assert result.status is EconomicStatus.NO_RECOVERABLE_ENERGY
    assert result.verdict is Verdict.UNDETERMINED
    assert result.break_even_energy_kwh == pytest.approx(20_000.0)  # still informative
    assert result.scenario(ScenarioName.BASE).net_benefit is None
    assert not result.decision_grade


def test_zero_total_cost_has_no_roi() -> None:
    free = economic_inputs(water_cost=0.0, labour_cost=0.0, equipment_cost=0.0, operational_cost=0.0)
    result = evaluate_economics(ENERGY, free)
    assert result.cost.total == 0.0
    assert result.scenario(ScenarioName.BASE).roi_pct is None
    assert result.verdict is Verdict.PROFITABLE


def test_zero_energy_value() -> None:
    result = evaluate_economics(ENERGY, economic_inputs(energy_value_per_kwh=0.0))
    assert result.break_even_energy_kwh is None  # no division by zero
    assert result.verdict is Verdict.UNPROFITABLE


def test_break_even_soiling_loss_and_payback() -> None:
    result = evaluate_economics(
        ENERGY, economic_inputs(), horizon_days=30.0, recoverable_per_day_central=1_000.0,
        projected_daily_clean_energy_kwh=50_000.0, cleaning_effectiveness=0.9,
    )
    # 20 000 kWh to recover / (0.9 x 50 000 kWh/day x 30 days)
    assert result.break_even_soiling_loss_pct == pytest.approx(20_000.0 / (0.9 * 50_000.0 * 30.0) * 100.0)
    assert result.payback_days == pytest.approx(100_000.0 / (1_000.0 * 5.0))


def test_negative_amounts_are_rejected() -> None:
    with pytest.raises(ValidationError):
        EconomicInputs(water_cost=-1.0)
    with pytest.raises(ValidationError):
        EconomicInputs(energy_value_per_kwh=-0.5)


def test_currency_is_normalised_and_checked() -> None:
    assert EconomicInputs(currency="dzd").currency == "DZD"
    with pytest.raises(ValidationError):
        EconomicInputs(currency="D1D")


def test_every_assumption_is_listed_with_its_classification() -> None:
    result = evaluate_economics(ENERGY, economic_inputs())
    names = [a.name for a in result.assumptions]
    assert names[0] == "Energy value"
    assert {"Water cost", "Labour cost", "Equipment cost", "Operational cost", "Downtime cost"} <= set(names)
    assert all(a.classification == "USER_ASSUMPTION" for a in result.assumptions)
    assert "[SELLING_PRICE]" in result.assumptions[0].source
