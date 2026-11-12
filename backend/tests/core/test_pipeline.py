"""The pipeline as a whole: stages, baselines, attribution, data quality."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from solarwise.core.attribution import Factor, FactorStatus
from solarwise.core.baseline import BaselineRequest
from solarwise.core.data_quality import QualityStatus
from solarwise.core.decision import Decision
from solarwise.core.models import BaselineDescriptor, BaselineMethod, ChannelMeta, Metric
from solarwise.core.pipeline import AnalysisError, AnalysisOptions, run_analysis
from solarwise.core.provenance import measured
from tests.builders import DAILY_EXPECTED_KWH, PLANT, START, make_case, soiled_case

STAGES = [
    "validation", "baseline", "gap", "attribution", "diagnostics",
    "recoverable", "economics", "evidence", "decision", "explanation",
]


def contribution(result, factor: Factor, scope: str = "period"):  # type: ignore[no-untyped-def]
    contributions = getattr(result.attribution, scope).contributions
    return next(c for c in contributions if c.factor is factor)


def test_every_stage_reports() -> None:
    result = run_analysis(soiled_case(0.08))
    assert [s.key for s in result.stages] == STAGES


def test_result_is_self_describing() -> None:
    result = run_analysis(soiled_case(0.08))
    assert result.engine_version
    assert result.thresholds.gap_materiality_pct == 3.0
    assert {p.metric for p in result.provenance} >= {Metric.ACTUAL_ENERGY, Metric.EXPECTED_ENERGY}
    assert result.cleaning_assumptions is not None and result.economic_inputs is not None
    payload = result.model_dump(mode="json")
    assert payload["recommendation"]["decision"] == "CLEAN_NOW"


def test_empty_dataset_is_an_error() -> None:
    case = make_case()
    case.observations = []
    with pytest.raises(AnalysisError, match="no observations"):
        run_analysis(case)


def test_period_must_overlap_the_data() -> None:
    case = make_case()
    case.options = AnalysisOptions(period_start=date(2030, 1, 1), period_end=date(2030, 1, 31))
    with pytest.raises(AnalysisError, match="does not overlap"):
        run_analysis(case)


def test_period_end_before_start_is_an_error() -> None:
    case = make_case()
    case.options = AnalysisOptions(period_start=START + timedelta(days=10), period_end=START)
    with pytest.raises(AnalysisError, match="ends before"):
        run_analysis(case)


def test_period_longer_than_a_year_is_refused() -> None:
    case = make_case()
    case.options = AnalysisOptions(period_start=date(2024, 1, 1), period_end=date(2026, 6, 1))
    with pytest.raises(AnalysisError, match="exceeds"):
        run_analysis(case)


def test_a_sub_period_can_be_analysed() -> None:
    case = make_case(days=30, true_soiling_ratio=0.92)
    case.options = AnalysisOptions(period_start=START + timedelta(days=10), period_end=START + timedelta(days=19))
    result = run_analysis(case)
    assert len(result.gap.daily) == 10
    assert result.gap.result.expected_kwh == pytest.approx(10 * DAILY_EXPECTED_KWH)


# --------------------------------------------------------------------------- attribution


def test_factors_and_residual_add_up_to_the_gap() -> None:
    case = make_case(
        true_soiling_ratio=0.94, reported_soiling_ratio=0.94, availability=0.97, extra_loss_fraction=0.02,
        economics=None, cleaning=None,
    )
    result = run_analysis(case)
    scope = result.attribution.period
    quantified = sum(c.energy.value or 0.0 for c in scope.contributions if c.energy.value is not None)
    assert scope.gap_kwh == pytest.approx(quantified + (scope.residual_kwh or 0.0), rel=1e-9)
    assert contribution(result, Factor.EQUIPMENT_AVAILABILITY).energy.value == pytest.approx(
        30 * DAILY_EXPECTED_KWH * 0.03
    )
    assert contribution(result, Factor.SOILING).energy.value == pytest.approx(30 * DAILY_EXPECTED_KWH * 0.97 * 0.06)
    assert scope.residual_kwh == pytest.approx(30 * DAILY_EXPECTED_KWH * 0.97 * 0.94 * 0.02)


def test_unquantifiable_factors_stay_in_the_residual() -> None:
    result = run_analysis(make_case(true_soiling_ratio=0.92, log_availability=False))
    for factor in (Factor.EQUIPMENT_AVAILABILITY, Factor.CURTAILMENT, Factor.SOILING):
        item = contribution(result, factor)
        assert item.status is FactorStatus.NOT_QUANTIFIED
        assert item.energy.value is None
        assert item.missing_inputs
    assert result.attribution.period.residual_kwh == pytest.approx(30 * DAILY_EXPECTED_KWH * 0.08)


def test_temperature_loss_against_a_baseline_rated_at_25_degc() -> None:
    """Baseline ignores heat; module at 55 degC -> thermal loss 0.35 %/K x 30 K = 10.5 %."""
    descriptor = BaselineDescriptor(
        method=BaselineMethod.OPERATOR_SUPPLIED, irradiance_adjusted=True, temperature_adjusted=False,
        reference_cell_temp_c=25.0, degradation_adjusted=True, soiling_allowance_fraction=0.0,
    )
    case = make_case(extra_loss_fraction=0.105, baseline=descriptor, economics=None, cleaning=None)
    for obs in case.observations:
        obs.module_temp_c = 55.0
    case.channels = {
        **case.channels,
        Metric.MODULE_TEMP: ChannelMeta(metric=Metric.MODULE_TEMP, tag=measured("module sensors"), unit="degC"),
    }
    result = run_analysis(case)
    item = contribution(result, Factor.TEMPERATURE)
    assert item.status is FactorStatus.QUANTIFIED
    assert item.share_of_expected_pct == pytest.approx(10.5)
    assert result.attribution.period.residual_pct == pytest.approx(0.0, abs=1e-6)
    assert result.recommendation.decision is Decision.MONITOR
    assert "TEMPERATURE" in [c.value for c in result.diagnostics.leading]


def test_temperature_cannot_be_quantified_without_a_temperature_input() -> None:
    descriptor = BaselineDescriptor(
        method=BaselineMethod.OPERATOR_SUPPLIED, irradiance_adjusted=True, temperature_adjusted=False,
        reference_cell_temp_c=25.0, degradation_adjusted=True, soiling_allowance_fraction=0.0,
    )
    result = run_analysis(make_case(extra_loss_fraction=0.105, baseline=descriptor))
    assert contribution(result, Factor.TEMPERATURE).status is FactorStatus.NOT_QUANTIFIED
    assert result.recommendation.decision is Decision.INVESTIGATE


def test_soiling_allowance_inside_the_baseline_is_removed_first() -> None:
    """A baseline that already assumes 2 % soiling hides 2 points of a soiling loss."""
    descriptor = BaselineDescriptor(
        method=BaselineMethod.OPERATOR_SUPPLIED, irradiance_adjusted=True, temperature_adjusted=True,
        degradation_adjusted=True, soiling_allowance_fraction=0.02,
    )
    case = make_case(reported_soiling_ratio=0.92, baseline=descriptor, expected_kwh=DAILY_EXPECTED_KWH)
    # actual = clean energy x 0.92, where clean energy = expected / (1 - 0.02)
    for obs in case.observations:
        obs.actual_energy_kwh = DAILY_EXPECTED_KWH / 0.98 * 0.92
    result = run_analysis(case)
    assert result.diagnostics.soiling_evidence.consistent_with_gap is True
    assert result.attribution.window.pre_soiling_gap_pct == pytest.approx(8.0, abs=1e-6)
    assert result.attribution.window.residual_pct == pytest.approx(0.0, abs=1e-6)


# --------------------------------------------------------------------------- baselines


def test_engineering_model_baseline_when_no_expected_energy_is_supplied() -> None:
    case = make_case(economics=None, cleaning=None, baseline=None)
    for obs in case.observations:
        obs.expected_energy_kwh = None
        obs.poa_irradiation_kwh_m2 = 6.0
        obs.module_temp_c = 45.0
        obs.actual_energy_kwh = 45_000.0
    channels = dict(case.channels)
    del channels[Metric.EXPECTED_ENERGY]
    channels[Metric.POA_IRRADIATION] = ChannelMeta(
        metric=Metric.POA_IRRADIATION, tag=measured("pyranometer"), unit="kWh/m2"
    )
    channels[Metric.MODULE_TEMP] = ChannelMeta(metric=Metric.MODULE_TEMP, tag=measured("module sensors"), unit="degC")
    case.channels = channels
    result = run_analysis(case)
    assert result.baseline.method is BaselineMethod.ENGINEERING_MODEL
    # 10 MWp x 6 kWh/m2 x (1 - 0.0035 x 20) x (1 - 0.14)
    expected = PLANT.capacity_dc_kwp * 6.0 * 0.93 * 0.86
    assert result.gap.result.expected_kwh == pytest.approx(30 * expected)
    assert result.baseline.meta.tag.label == "MODELLED"  # a model applied to measurements is a model
    assert result.gap.result.relative_gap_pct == pytest.approx((expected - 45_000.0) / expected * 100.0)


def test_no_baseline_at_all_blocks_the_analysis_gracefully() -> None:
    case = make_case(baseline=None)
    for obs in case.observations:
        obs.expected_energy_kwh = None
    channels = dict(case.channels)
    del channels[Metric.EXPECTED_ENERGY]
    case.channels = channels
    result = run_analysis(case)
    assert result.gap.result.expected_kwh is None
    assert result.recommendation.decision is Decision.INVESTIGATE
    assert result.recommendation.rule == "R0"
    assert next(s for s in result.stages if s.key == "baseline").state.value == "BLOCKED"


def test_requesting_an_unavailable_baseline_method_does_not_fall_back_silently() -> None:
    case = make_case()
    case.options = AnalysisOptions(baseline=BaselineRequest(method=BaselineMethod.PVGIS_TYPICAL_YEAR))
    result = run_analysis(case)
    assert result.baseline.method is BaselineMethod.PVGIS_TYPICAL_YEAR
    assert result.gap.result.expected_kwh is None
    assert result.recommendation.decision is Decision.INVESTIGATE


# --------------------------------------------------------------------------- data quality


def test_energy_beyond_capacity_is_a_blocking_quality_issue() -> None:
    case = make_case()
    case.observations[3].actual_energy_kwh = 5_000_000.0  # 10 MWp cannot deliver 5 GWh in a day
    result = run_analysis(case)
    assert result.quality.status is QualityStatus.INSUFFICIENT
    assert any(i.code == "ENERGY_EXCEEDS_CAPACITY" for i in result.quality.issues)


def test_clean_data_has_good_quality() -> None:
    case = soiled_case(0.08)
    for index, obs in enumerate(case.observations):  # day-to-day variation, as real weather produces
        factor = 1.0 + 0.01 * (index % 5)
        assert obs.actual_energy_kwh is not None and obs.expected_energy_kwh is not None
        obs.actual_energy_kwh *= factor
        obs.expected_energy_kwh *= factor
    result = run_analysis(case)
    assert result.quality.status is QualityStatus.GOOD
    assert {c.metric for c in result.quality.channels} >= {Metric.ACTUAL_ENERGY, Metric.SOILING_RATIO}


def test_identical_values_day_after_day_are_flagged_as_a_flat_line() -> None:
    result = run_analysis(soiled_case(0.08))  # the hand-built case repeats exactly the same energy
    assert result.quality.status is QualityStatus.DEGRADED
    flat = next(i for i in result.quality.issues if i.code == "FLATLINE")
    assert flat.metric == "actual_energy"


def test_undeclared_provenance_is_flagged() -> None:
    from solarwise.core.provenance import UNKNOWN_TAG

    result = run_analysis(soiled_case(0.08, actual_tag=UNKNOWN_TAG))
    assert any(i.code == "PROVENANCE_NOT_DECLARED" for i in result.quality.issues)


def test_explanation_covers_every_part_of_the_reasoning() -> None:
    result = run_analysis(soiled_case(0.08))
    keys = [s.key for s in result.explanation.sections]
    assert keys == ["observation", "diagnosis", "economics", "decision", "unknowns", "next_steps", "would_change"]
    assert result.explanation.generated_by == "DETERMINISTIC_ENGINE"
    assert "MEASURED" in result.explanation.provenance_statement
