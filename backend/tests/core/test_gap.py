"""Performance gap: the formula, its edge cases, significance and coverage."""

from __future__ import annotations

import math
from datetime import timedelta

import pytest

from solarwise.core.gap import (
    GapDirection,
    GapStatus,
    assess_significance,
    compute_gap,
    compute_gap_with_units,
)
from solarwise.core.models import AnalysisThresholds
from solarwise.core.pipeline import run_analysis
from tests.builders import DAILY_EXPECTED_KWH, START, make_case

THRESHOLDS = AnalysisThresholds()


# --------------------------------------------------------------------------- formula


def test_gap_formula() -> None:
    result = compute_gap(1000.0, 920.0)
    assert result.status is GapStatus.OK
    assert result.gap_kwh == pytest.approx(80.0)
    assert result.relative_gap_pct == pytest.approx(8.0)


def test_overperformance_gives_a_negative_gap() -> None:
    result = compute_gap(1000.0, 1050.0)
    assert result.gap_kwh == pytest.approx(-50.0)
    assert result.relative_gap_pct == pytest.approx(-5.0)


def test_zero_expected_energy_has_no_relative_gap() -> None:
    result = compute_gap(0.0, 12.0)
    assert result.status is GapStatus.ZERO_EXPECTED
    assert result.gap_kwh == pytest.approx(-12.0)
    assert result.relative_gap_pct is None  # no division by zero, no infinity


def test_zero_expected_and_zero_actual() -> None:
    result = compute_gap(0.0, 0.0)
    assert result.status is GapStatus.ZERO_EXPECTED
    assert result.gap_kwh == 0.0
    assert result.relative_gap_pct is None


@pytest.mark.parametrize(("expected", "actual"), [(None, 10.0), (10.0, None), (None, None)])
def test_missing_operand_is_not_treated_as_zero(expected: float | None, actual: float | None) -> None:
    result = compute_gap(expected, actual)
    assert result.status is GapStatus.MISSING_INPUT
    assert result.gap_kwh is None
    assert result.relative_gap_pct is None
    assert "missing is not zero" in (result.message or "")


@pytest.mark.parametrize(("expected", "actual"), [(-1.0, 10.0), (10.0, -1.0)])
def test_negative_energy_is_invalid(expected: float, actual: float) -> None:
    result = compute_gap(expected, actual)
    assert result.status is GapStatus.INVALID_INPUT
    assert result.gap_kwh is None


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_energy_is_invalid(bad: float) -> None:
    assert compute_gap(bad, 10.0).status is GapStatus.INVALID_INPUT
    assert compute_gap(10.0, bad).status is GapStatus.INVALID_INPUT


def test_units_are_converted_before_comparing() -> None:
    result = compute_gap_with_units(1.0, "MWh", 920.0, "kWh")
    assert result.status is GapStatus.OK
    assert result.gap_kwh == pytest.approx(80.0)
    assert result.relative_gap_pct == pytest.approx(8.0)


def test_unknown_or_wrong_units_are_refused() -> None:
    assert compute_gap_with_units(1.0, "MWh", 920.0, "bananas").status is GapStatus.INVALID_UNIT
    # kW is a power, not an energy: refusing is the only safe answer.
    assert compute_gap_with_units(1.0, "MWh", 920.0, "kW").status is GapStatus.INVALID_UNIT


# --------------------------------------------------------------------------- significance


def test_small_gap_is_within_tolerance() -> None:
    sig = assess_significance(compute_gap(1000.0, 985.0), 2.0, 0.5, THRESHOLDS)
    assert sig.direction is GapDirection.WITHIN_TOLERANCE
    assert sig.material is False
    assert sig.significant is False


def test_combined_uncertainty_formula() -> None:
    sig = assess_significance(compute_gap(1000.0, 900.0), 2.0, 0.5, THRESHOLDS)
    assert sig.combined_std_uncertainty_pct == pytest.approx(math.sqrt(2.0**2 + (0.5 * 0.9) ** 2))
    assert sig.threshold_pct == pytest.approx(2.0 * sig.combined_std_uncertainty_pct)
    assert sig.distinguishable is True
    assert sig.direction is GapDirection.UNDERPERFORMANCE


def test_material_gap_inside_the_uncertainty_band_is_not_significant() -> None:
    # 5 % gap, but the baseline alone is uncertain by 4 % (one sigma): k x u = 8 %.
    sig = assess_significance(compute_gap(1000.0, 950.0), 4.0, 0.5, THRESHOLDS)
    assert sig.material is True
    assert sig.distinguishable is False
    assert sig.significant is False
    assert sig.direction is GapDirection.WITHIN_TOLERANCE


def test_without_declared_uncertainty_only_materiality_is_used() -> None:
    sig = assess_significance(compute_gap(1000.0, 950.0), None, 0.5, THRESHOLDS)
    assert sig.basis == "MATERIALITY_ONLY"
    assert sig.distinguishable is None
    assert sig.significant is True
    assert "baseline uncertainty not declared" in sig.note


def test_overperformance_is_reported_as_such() -> None:
    sig = assess_significance(compute_gap(1000.0, 1100.0), 2.0, 0.5, THRESHOLDS)
    assert sig.direction is GapDirection.OVERPERFORMANCE


def test_significance_of_an_undefined_gap_is_undetermined() -> None:
    sig = assess_significance(compute_gap(0.0, 5.0), 2.0, 0.5, THRESHOLDS)
    assert sig.direction is GapDirection.UNDETERMINED
    assert sig.significant is None


# --------------------------------------------------------------------------- series


def test_series_totals() -> None:
    result = run_analysis(make_case(days=30, true_soiling_ratio=0.92))
    assert result.gap.result.expected_kwh == pytest.approx(30 * DAILY_EXPECTED_KWH)
    assert result.gap.result.actual_kwh == pytest.approx(30 * DAILY_EXPECTED_KWH * 0.92)
    assert result.gap.result.relative_gap_pct == pytest.approx(8.0)
    assert result.gap.coverage.fraction == pytest.approx(1.0)
    assert len(result.gap.daily) == 30


def test_missing_production_is_excluded_not_counted_as_zero() -> None:
    """A day without telemetry must not look like a day without production."""
    result = run_analysis(make_case(days=30, true_soiling_ratio=0.92, missing_actual_days=[10]))
    gap = result.gap
    # The day is left out on both sides: the relative gap is unchanged.
    assert gap.result.expected_kwh == pytest.approx(29 * DAILY_EXPECTED_KWH)
    assert gap.result.actual_kwh == pytest.approx(29 * DAILY_EXPECTED_KWH * 0.92)
    assert gap.result.relative_gap_pct == pytest.approx(8.0)
    assert gap.coverage.fraction == pytest.approx(29 / 30)
    assert gap.coverage.missing_actual_slots == 1
    day = gap.daily[10]
    assert day.status == "MISSING"
    assert day.actual_kwh is None and day.gap_kwh is None and day.relative_gap_pct is None


def test_days_without_any_row_are_counted_as_missing() -> None:
    result = run_analysis(make_case(days=30, absent_days=[4, 5]))
    assert len(result.gap.daily) == 30
    assert result.gap.coverage.fraction == pytest.approx(28 / 30)
    assert [d.status for d in result.gap.daily[4:6]] == ["MISSING", "MISSING"]


def test_assessment_window_describes_the_most_recent_days() -> None:
    # Clean for 23 days, then 10 % down for the last 7.
    case = make_case(days=30, extra_loss_fraction=lambda i: 0.10 if i >= 23 else 0.0)
    gap = run_analysis(case).gap
    assert gap.window.start == START + timedelta(days=23)
    assert gap.window.end == START + timedelta(days=29)
    assert gap.window.result.relative_gap_pct == pytest.approx(10.0)
    assert gap.result.relative_gap_pct == pytest.approx(10.0 * 7 / 30)


def test_low_coverage_is_reported_as_a_limitation() -> None:
    result = run_analysis(make_case(days=30, missing_actual_days=range(0, 6)))
    assert result.gap.coverage.fraction == pytest.approx(0.8)
    assert any("Missing intervals were excluded" in text for text in result.gap.limitations)


def test_gap_provenance_follows_the_weaker_input() -> None:
    result = run_analysis(make_case())
    assert result.gap.actual.tag.label == "MEASURED"
    assert result.gap.expected.tag.label == "MODELLED"
    assert result.gap.gap.tag.label == "MODELLED"
