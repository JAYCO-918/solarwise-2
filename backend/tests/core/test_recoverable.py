"""Recoverable energy: only from measured soiling, with explicit assumptions and a stated range."""

from __future__ import annotations

import pytest

from solarwise.core.pipeline import run_analysis
from solarwise.core.provenance import modelled
from solarwise.core.recoverable import CleaningAssumptions, RecoverableStatus
from tests.builders import DAILY_EXPECTED_KWH, make_case, soiled_case


def test_formula_loss_x_effectiveness_x_daily_energy_x_horizon() -> None:
    rec = run_analysis(soiled_case(0.08)).recoverable
    assert rec.status is RecoverableStatus.ESTIMATED
    assert rec.soiling_loss_pct == pytest.approx(8.0)
    assert rec.projected_daily_clean_energy is not None
    assert rec.projected_daily_clean_energy.value == pytest.approx(DAILY_EXPECTED_KWH)
    # 8 % x 0.9 x 50 000 kWh/day x 30 days
    assert rec.recoverable.central == pytest.approx(0.08 * 0.9 * DAILY_EXPECTED_KWH * 30.0)
    assert rec.recoverable_per_day.central == pytest.approx(0.08 * 0.9 * DAILY_EXPECTED_KWH)
    assert rec.horizon_days == 30.0
    assert rec.usable_for_decision


def test_range_combines_the_extremes_of_every_input() -> None:
    rec = run_analysis(soiled_case(0.08)).recoverable
    # soiling 8 +/- 2 x 0.5 % points; effectiveness 0.8 .. 1.0; horizon 24 .. 36 days
    assert rec.soiling_loss_low_pct == pytest.approx(7.0)
    assert rec.soiling_loss_high_pct == pytest.approx(9.0)
    assert rec.recoverable.low == pytest.approx(0.07 * 0.8 * DAILY_EXPECTED_KWH * 24.0)
    assert rec.recoverable.high == pytest.approx(0.09 * 1.0 * DAILY_EXPECTED_KWH * 36.0)
    assert rec.recoverable.low < rec.recoverable.central < rec.recoverable.high
    assert "not a statistical confidence interval" in rec.uncertainty_statement


def test_residual_soiling_after_cleaning_is_reported() -> None:
    rec = run_analysis(soiled_case(0.08)).recoverable
    assert rec.residual_soiling_after_cleaning_pct == pytest.approx(8.0 * (1.0 - 0.9))


@pytest.mark.safety
def test_no_number_without_a_soiling_measurement() -> None:
    rec = run_analysis(make_case(true_soiling_ratio=0.90)).recoverable
    assert rec.status is RecoverableStatus.INSUFFICIENT_EVIDENCE
    assert rec.recoverable.low is None and rec.recoverable.central is None and rec.recoverable.high is None
    assert rec.soiling_related_loss.value is None
    assert rec.observed_gap.value == pytest.approx(0.10 * DAILY_EXPECTED_KWH * 7)
    assert not rec.usable_for_decision
    assert "gap alone" in rec.reasons[0]


@pytest.mark.safety
def test_the_gap_is_reported_separately_from_the_soiling_loss() -> None:
    """Gap 14 %, of which the soiling station accounts for 6 %: three distinct figures."""
    result = run_analysis(make_case(true_soiling_ratio=0.94, reported_soiling_ratio=0.94, extra_loss_fraction=0.0851))
    rec = result.recoverable
    window_expected = DAILY_EXPECTED_KWH * 7
    assert rec.observed_gap.value == pytest.approx(window_expected * (1 - 0.94 * (1 - 0.0851)), rel=1e-6)
    assert rec.soiling_related_loss.value == pytest.approx(window_expected * 0.06, rel=1e-6)
    assert rec.unexplained_loss.value == pytest.approx(window_expected * 0.94 * 0.0851, rel=1e-6)
    # The three add up: nothing is silently reassigned to soiling.
    assert rec.observed_gap.value == pytest.approx(rec.soiling_related_loss.value + rec.unexplained_loss.value)


@pytest.mark.safety
def test_no_default_assumptions() -> None:
    rec = run_analysis(soiled_case(0.08, cleaning=None)).recoverable
    assert rec.status is RecoverableStatus.MISSING_ASSUMPTIONS
    assert rec.recoverable.central is None
    assert "cleaning effectiveness" in rec.reasons[0] and "benefit horizon" in rec.reasons[0]


def test_partial_assumptions_are_reported_as_missing() -> None:
    only_effectiveness = CleaningAssumptions(cleaning_effectiveness=0.9)
    rec = run_analysis(soiled_case(0.08, cleaning=only_effectiveness)).recoverable
    assert rec.status is RecoverableStatus.MISSING_ASSUMPTIONS
    assert "benefit horizon" in rec.reasons[0] and "cleaning effectiveness" not in rec.reasons[0]


def test_near_clean_array_has_nothing_to_recover() -> None:
    rec = run_analysis(make_case(true_soiling_ratio=0.90, reported_soiling_ratio=0.995)).recoverable
    assert rec.status is RecoverableStatus.NO_RECOVERABLE_LOSS
    assert rec.recoverable.central is None


@pytest.mark.safety
def test_modelled_soiling_figure_gives_no_recoverable_energy() -> None:
    rec = run_analysis(soiled_case(0.08, soiling_tag=modelled("soiling model"))).recoverable
    assert rec.status is RecoverableStatus.INSUFFICIENT_EVIDENCE
    assert rec.recoverable.central is None
    assert not rec.usable_for_decision


def test_user_supplied_daily_energy_is_used_and_labelled() -> None:
    assumptions = CleaningAssumptions(
        cleaning_effectiveness=0.9, benefit_horizon_days=10.0, projected_daily_clean_energy_kwh=40_000.0
    )
    rec = run_analysis(soiled_case(0.08, cleaning=assumptions)).recoverable
    assert rec.recoverable.central == pytest.approx(0.08 * 0.9 * 40_000.0 * 10.0)
    daily = next(a for a in rec.assumptions if "daily" in a.name.lower())
    assert daily.classification == "USER_ASSUMPTION"


def test_without_ranges_the_warnings_say_so() -> None:
    assumptions = CleaningAssumptions(cleaning_effectiveness=0.9, benefit_horizon_days=30.0)
    rec = run_analysis(soiled_case(0.08, cleaning=assumptions, soiling_uncertainty_abs=None)).recoverable
    assert rec.status is RecoverableStatus.ESTIMATED
    assert rec.recoverable.low == pytest.approx(rec.recoverable.central)
    assert any("no declared uncertainty" in w for w in rec.warnings)
    assert any("No range was supplied" in w for w in rec.warnings)


def test_conservative_case_never_credits_more_than_production_shows() -> None:
    # Station reads 9 % (7.6 % at the lower bound with u = 0.7), production is 7 % short.
    result = run_analysis(
        make_case(true_soiling_ratio=0.93, reported_soiling_ratio=0.91, soiling_uncertainty_abs=0.007)
    )
    rec = result.recoverable
    assert rec.status is RecoverableStatus.ESTIMATED
    assert rec.recoverable.low == pytest.approx(0.07 * 0.8 * DAILY_EXPECTED_KWH * 24.0, rel=1e-6)
    assert any("Conservative case limited" in w for w in rec.warnings)


def test_every_assumption_is_listed() -> None:
    rec = run_analysis(soiled_case(0.08)).recoverable
    names = " | ".join(a.name.lower() for a in rec.assumptions)
    assert "effectiveness" in names and "horizon" in names and "daily" in names
    assert all(a.classification for a in rec.assumptions)


def test_invalid_assumptions_are_rejected() -> None:
    with pytest.raises(ValueError):
        CleaningAssumptions(cleaning_effectiveness=1.5)
    with pytest.raises(ValueError):
        CleaningAssumptions(benefit_horizon_days=-3.0)
    with pytest.raises(ValueError):
        CleaningAssumptions(cleaning_effectiveness=0.9, cleaning_effectiveness_low=0.95)
