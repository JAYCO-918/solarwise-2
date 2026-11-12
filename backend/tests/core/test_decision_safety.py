"""Safety properties of the decision engine.

Each test builds a small case by hand, changes exactly one thing relative to a
case in which a cleaning *is* justified, and checks that the decision reacts as
required.  The reference case - measured production, a documented baseline, a
credible soiling measurement that matches the gap, no technical issue, complete
economics that pay - is the only path to ``CLEAN_NOW``.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest

from solarwise.core.decision import CLEAN_NOW_GATES, Decision, ReasonCode, decide
from solarwise.core.diagnostics import DiagnosticStatus
from solarwise.core.economics import EnergyValueBasis
from solarwise.core.evidence import GateId
from solarwise.core.models import (
    AnalysisThresholds,
    BaselineDescriptor,
    EvidenceRecord,
    EvidenceType,
    InspectionFinding,
    SoilingMethod,
)
from solarwise.core.pipeline import AnalysisResult, run_analysis
from solarwise.core.provenance import UNKNOWN_TAG, EvaluationContext, Provenance, measured, modelled, synthetic
from tests.builders import PLANT, START, ZONE, economic_inputs, make_case, soiled_case

pytestmark = pytest.mark.safety

DEMO = EvaluationContext.DEMONSTRATION


def at(day_index: int, hour: int = 10) -> datetime:
    return datetime.combine(START + timedelta(days=day_index), time(hour=hour), tzinfo=ZONE)


def failed(result: AnalysisResult) -> set[GateId]:
    return set(result.recommendation.failed_gates)


# --------------------------------------------------------------------------- the reference case


def test_reference_case_is_clean_now_with_operational_authorisation() -> None:
    result = run_analysis(soiled_case(0.08))
    rec = result.recommendation
    assert rec.decision is Decision.CLEAN_NOW
    assert rec.rule == "R3"
    assert rec.reason_code is ReasonCode.CLEANING_JUSTIFIED
    assert rec.failed_gates == []
    assert all(g.passed is True for g in rec.gates)
    assert rec.operational_authorization is True
    assert rec.simulated is False
    assert not rec.safety_interlock_triggered
    assert result.diagnostics.status is DiagnosticStatus.SINGLE_EXPLANATION


def test_all_ten_gates_are_required() -> None:
    assert len(CLEAN_NOW_GATES) == 10
    assert set(CLEAN_NOW_GATES) == set(GateId)


# --------------------------------------------------------------------------- a gap alone


def test_production_gap_alone_never_triggers_clean_now() -> None:
    """The central requirement: under-performance is not evidence of soiling."""
    result = run_analysis(make_case(true_soiling_ratio=0.88))  # 12 % gap, no soiling measurement
    rec = result.recommendation
    assert result.gap.window.significance.significant is True
    assert rec.decision is Decision.INVESTIGATE
    assert rec.rule == "R4"
    assert rec.reason_code is ReasonCode.UNEXPLAINED_DEVIATION
    assert GateId.SOILING_EVIDENCE_CREDIBLE in failed(result)
    assert not rec.operational_authorization
    assert any("does not prove soiling" in text for text in rec.reasons)


def test_gap_with_favourable_economics_but_no_soiling_evidence_is_not_clean_now() -> None:
    cheap = economic_inputs(water_cost=1.0, labour_cost=1.0, equipment_cost=1.0, operational_cost=1.0)
    result = run_analysis(make_case(true_soiling_ratio=0.80, economics=cheap))
    assert result.recommendation.decision is Decision.INVESTIGATE
    # Without a soiling measurement no recoverable energy is stated at all.
    assert result.recoverable.recoverable.central is None
    assert result.economics.scenarios[1].net_benefit is None


def test_a_steadily_growing_gap_is_still_only_a_suspicion() -> None:
    result = run_analysis(make_case(days=60, true_soiling_ratio=lambda i: 1.0 - 0.002 * (i + 1)))
    assert result.recommendation.decision is Decision.INVESTIGATE
    assert not result.diagnostics.soiling_evidence.available
    assert result.recoverable.recoverable.central is None


@pytest.mark.parametrize("gap", [0.03, 0.05, 0.10, 0.20, 0.40, 0.70])
def test_no_gap_size_substitutes_for_soiling_evidence(gap: float) -> None:
    result = run_analysis(make_case(true_soiling_ratio=1.0 - gap))
    assert result.recommendation.decision is not Decision.CLEAN_NOW


# --------------------------------------------------------------------------- provenance of production


@pytest.mark.parametrize(
    "tag",
    [
        modelled("simulated production"),
        synthetic("generator"),
        synthetic("generator", emulates=Provenance.MEASURED),
        UNKNOWN_TAG,
    ],
    ids=["modelled", "synthetic", "synthetic-emulating-measured", "unknown"],
)
def test_non_measured_production_never_triggers_operational_clean_now(tag) -> None:  # type: ignore[no-untyped-def]
    result = run_analysis(soiled_case(0.08, actual_tag=tag))
    rec = result.recommendation
    assert rec.decision is Decision.INVESTIGATE
    assert rec.rule == "R0"
    assert rec.reason_code is ReasonCode.NON_MEASURED_PRODUCTION
    assert GateId.PRODUCTION_MEASURED in failed(result)
    assert not rec.operational_authorization


@pytest.mark.parametrize(
    "tag",
    [modelled("soiling model"), synthetic("generator"), synthetic("generator", emulates=Provenance.MEASURED), UNKNOWN_TAG],
    ids=["modelled", "synthetic", "synthetic-emulating-measured", "unknown"],
)
def test_non_measured_soiling_evidence_never_triggers_operational_clean_now(tag) -> None:  # type: ignore[no-untyped-def]
    result = run_analysis(soiled_case(0.08, soiling_tag=tag))
    rec = result.recommendation
    # The loss is real but nothing credible explains it: neither clean nor merely watch.
    assert rec.decision is Decision.INVESTIGATE
    assert rec.rule == "R4"
    assert result.diagnostics.unexplained_residual_pct == pytest.approx(8.0, abs=0.01)
    assert GateId.SOILING_EVIDENCE_CREDIBLE in failed(result)
    assert not result.recoverable.usable_for_decision
    assert not rec.operational_authorization


def test_baseline_of_unknown_origin_blocks_the_decision() -> None:
    result = run_analysis(soiled_case(0.08, expected_tag=UNKNOWN_TAG))
    assert result.recommendation.decision is Decision.INVESTIGATE
    assert result.recommendation.rule == "R0"
    assert GateId.BASELINE_DOCUMENTED in failed(result)


def test_synthetic_baseline_blocks_an_operational_decision() -> None:
    tag = synthetic("generator", emulates=Provenance.MODELLED)
    result = run_analysis(soiled_case(0.08, expected_tag=tag))
    assert result.recommendation.decision is Decision.INVESTIGATE
    assert GateId.BASELINE_DOCUMENTED in failed(result)


# --------------------------------------------------------------------------- demonstration context


def demo_tags() -> dict[str, object]:
    return {
        "actual_tag": synthetic("generator", emulates=Provenance.MEASURED),
        "expected_tag": synthetic("generator", emulates=Provenance.MODELLED),
        "soiling_tag": synthetic("generator", emulates=Provenance.MEASURED),
    }


def test_demonstration_clean_now_is_simulated_and_never_authorised() -> None:
    demo_plant = PLANT.model_copy(update={"is_demonstration": True})
    result = run_analysis(soiled_case(0.08, context=DEMO, plant=demo_plant, **demo_tags()))
    rec = result.recommendation
    assert rec.decision is Decision.CLEAN_NOW
    assert rec.simulated is True
    assert rec.operational_authorization is False
    assert rec.headline.startswith("SIMULATED DECISION")
    assert "Not an operational instruction" in rec.headline
    assert "SIMULATED DECISION" in rec.authorization_note
    assert result.evidence.synthetic_evidence_present


def test_the_same_synthetic_data_in_the_operational_context_is_refused() -> None:
    result = run_analysis(soiled_case(0.08, context=EvaluationContext.OPERATIONAL, **demo_tags()))
    rec = result.recommendation
    assert rec.decision is Decision.INVESTIGATE
    assert rec.rule == "R0"
    assert not rec.operational_authorization


def test_plain_synthetic_data_is_refused_even_in_a_demonstration() -> None:
    result = run_analysis(
        soiled_case(0.08, context=DEMO, actual_tag=synthetic("generator"), soiling_tag=synthetic("generator"))
    )
    assert result.recommendation.decision is Decision.INVESTIGATE
    assert result.recommendation.rule == "R0"


def test_a_demonstration_plant_is_never_authorised_even_with_measured_data() -> None:
    demo_plant = PLANT.model_copy(update={"is_demonstration": True})
    result = run_analysis(soiled_case(0.08, plant=demo_plant))
    rec = result.recommendation
    assert rec.decision is Decision.CLEAN_NOW
    assert rec.simulated is True
    assert rec.operational_authorization is False


def test_measured_data_evaluated_in_a_demonstration_context_is_not_authorised() -> None:
    result = run_analysis(soiled_case(0.08, context=DEMO))
    assert result.recommendation.decision is Decision.CLEAN_NOW
    assert result.recommendation.operational_authorization is False
    assert result.recommendation.simulated is True


def test_advisory_evaluation_is_never_authorised() -> None:
    case = soiled_case(0.08)
    case.allow_operational_authorization = False
    rec = run_analysis(case).recommendation
    assert rec.decision is Decision.CLEAN_NOW
    assert rec.operational_authorization is False
    assert "does not authorise" in rec.authorization_note


# --------------------------------------------------------------------------- soiling evidence quality


def test_soiling_reading_of_a_clean_array_rules_soiling_out() -> None:
    result = run_analysis(make_case(true_soiling_ratio=0.90, reported_soiling_ratio=0.995))
    rec = result.recommendation
    assert rec.decision is Decision.INVESTIGATE
    assert rec.rule == "R4"
    assert not result.diagnostics.soiling_evidence.credible
    assert result.diagnostics.unexplained_residual_material


def test_soiling_that_explains_only_part_of_the_gap_is_not_enough() -> None:
    # 4 % measured soiling, 16 % gap: most of the loss has another cause.
    result = run_analysis(make_case(true_soiling_ratio=0.84, reported_soiling_ratio=0.96))
    rec = result.recommendation
    assert rec.decision is Decision.INVESTIGATE
    assert GateId.SOILING_CONSISTENT_WITH_GAP in failed(result)
    assert result.diagnostics.soiling_evidence.consistent_with_gap is False


def test_soiling_measurement_larger_than_the_gap_is_a_contradiction() -> None:
    # The sensor claims 15 % loss while production is only 2 % short.
    result = run_analysis(make_case(true_soiling_ratio=0.98, reported_soiling_ratio=0.85))
    assert result.recommendation.decision is not Decision.CLEAN_NOW


def test_outdated_spot_measurement_is_not_credible() -> None:
    record = EvidenceRecord(
        reference="SR-OLD", evidence_type=EvidenceType.SOILING_MEASUREMENT, observed_start=at(5),
        tag=measured("string comparison test"), value=0.92, unit="fraction", std_uncertainty=0.005,
        soiling_method=SoilingMethod.STRING_COMPARISON,
    )
    result = run_analysis(make_case(true_soiling_ratio=0.92, records=[record]))  # 24 days before the period end
    evidence = result.diagnostics.soiling_evidence
    assert evidence.available and not evidence.recent and not evidence.credible
    assert result.recommendation.decision is Decision.INVESTIGATE


def test_recent_spot_measurement_is_accepted() -> None:
    record = EvidenceRecord(
        reference="SR-NEW", evidence_type=EvidenceType.SOILING_MEASUREMENT, observed_start=at(28),
        tag=measured("string comparison test"), value=0.92, unit="fraction", std_uncertainty=0.005,
        soiling_method=SoilingMethod.STRING_COMPARISON,
    )
    result = run_analysis(make_case(true_soiling_ratio=0.92, records=[record]))
    assert result.diagnostics.soiling_evidence.credible
    assert result.recommendation.decision is Decision.CLEAN_NOW


def test_visual_estimate_is_not_a_measurement() -> None:
    record = EvidenceRecord(
        reference="EYE-1", evidence_type=EvidenceType.SOILING_MEASUREMENT, observed_start=at(28),
        tag=measured("technician estimate"), value=0.92, unit="fraction",
        soiling_method=SoilingMethod.VISUAL_ESTIMATE,
    )
    result = run_analysis(make_case(true_soiling_ratio=0.92, records=[record]))
    assert not result.diagnostics.soiling_evidence.credible
    assert result.recommendation.decision is Decision.INVESTIGATE


def test_soiling_channel_without_a_declared_method_is_not_credible() -> None:
    result = run_analysis(soiled_case(0.08, soiling_method=None))
    assert not result.diagnostics.soiling_evidence.credible
    assert result.recommendation.decision is Decision.INVESTIGATE
    assert result.recommendation.rule == "R4"
    assert any("not a direct comparison" in text for text in result.recommendation.reasons)


def test_inspection_alone_does_not_quantify_soiling() -> None:
    record = EvidenceRecord(
        reference="INSP-1", evidence_type=EvidenceType.VISUAL_INSPECTION, observed_start=at(28),
        tag=measured("inspection report"), finding=InspectionFinding.SOILING_HEAVY,
    )
    result = run_analysis(make_case(true_soiling_ratio=0.90, records=[record]))
    assert result.recommendation.decision is Decision.INVESTIGATE
    assert result.recoverable.recoverable.central is None


def test_weather_data_never_stand_in_for_soiling_evidence() -> None:
    """Dry, dusty, windy weather is context; it measures nothing on the modules."""
    case = make_case(days=45, true_soiling_ratio=lambda i: 1.0 - 0.002 * (i + 1))
    for obs in case.observations:
        obs.precipitation_mm = 0.0
        obs.wind_speed_ms = 9.0
        obs.relative_humidity_pct = 12.0
        obs.ambient_temp_c = 38.0
    result = run_analysis(case)
    assert not result.diagnostics.soiling_evidence.available
    assert result.recommendation.decision is Decision.INVESTIGATE
    assert any("do not measure dust" in text for text in result.disclaimers)


# --------------------------------------------------------------------------- technical issues and conflicts


def test_unresolved_inverter_fault_blocks_cleaning() -> None:
    record = EvidenceRecord(
        reference="FAULT-1", evidence_type=EvidenceType.INVERTER_FAULT, observed_start=at(26),
        tag=measured("alarm log"), description="Inverter 3 tripped", resolved=False,
    )
    result = run_analysis(soiled_case(0.08, records=[record]))
    rec = result.recommendation
    assert rec.decision is Decision.INVESTIGATE
    assert rec.rule == "R1"
    assert rec.reason_code is ReasonCode.TECHNICAL_ISSUE
    assert GateId.NO_UNRESOLVED_TECHNICAL_ISSUE in failed(result)


def test_resolved_fault_outside_the_window_does_not_block() -> None:
    record = EvidenceRecord(
        reference="FAULT-2", evidence_type=EvidenceType.INVERTER_FAULT, observed_start=at(3), observed_end=at(4),
        tag=measured("alarm log"), resolved=True,
    )
    result = run_analysis(soiled_case(0.08, records=[record]))
    assert result.recommendation.decision is Decision.CLEAN_NOW


def test_low_availability_in_the_window_blocks_cleaning() -> None:
    result = run_analysis(soiled_case(0.08, availability=lambda i: 0.90 if i >= 25 else 1.0))
    rec = result.recommendation
    assert rec.decision is Decision.INVESTIGATE
    assert rec.rule == "R1"


def test_open_sensor_fault_blocks_cleaning() -> None:
    record = EvidenceRecord(
        reference="SENS-1", evidence_type=EvidenceType.SENSOR_FAULT, observed_start=at(27),
        tag=measured("maintenance log"), description="Pyranometer misaligned", resolved=False,
    )
    result = run_analysis(soiled_case(0.08, records=[record]))
    assert result.recommendation.decision is Decision.INVESTIGATE
    assert result.recommendation.rule == "R1"


def test_inspection_contradicting_the_sensor_is_a_critical_conflict() -> None:
    record = EvidenceRecord(
        reference="INSP-2", evidence_type=EvidenceType.VISUAL_INSPECTION, observed_start=at(28),
        tag=measured("inspection report"), finding=InspectionFinding.CLEAN,
    )
    result = run_analysis(soiled_case(0.08, records=[record]))
    rec = result.recommendation
    assert rec.decision is Decision.INVESTIGATE
    assert rec.rule == "R2"
    assert rec.reason_code is ReasonCode.CONFLICTING_EVIDENCE
    assert result.diagnostics.status is DiagnosticStatus.CONFLICTING_EVIDENCE
    assert GateId.NO_CRITICAL_CONTRADICTION in failed(result)


def test_two_soiling_sources_that_disagree_are_a_conflict() -> None:
    record = EvidenceRecord(
        reference="SR-X", evidence_type=EvidenceType.SOILING_MEASUREMENT, observed_start=at(28),
        tag=measured("string comparison test"), value=0.99, unit="fraction", std_uncertainty=0.005,
        soiling_method=SoilingMethod.STRING_COMPARISON,
    )
    result = run_analysis(soiled_case(0.08, records=[record]))
    assert result.recommendation.decision is Decision.INVESTIGATE
    assert any(c.code == "C-SOILING-SOURCES-DISAGREE" for c in result.diagnostics.conflicts)


# --------------------------------------------------------------------------- data sufficiency


def test_incomplete_recent_data_blocks_the_decision() -> None:
    result = run_analysis(soiled_case(0.08, missing_actual_days=[25, 26, 27]))
    rec = result.recommendation
    assert rec.decision is Decision.INVESTIGATE
    assert rec.rule == "R0"
    assert rec.reason_code is ReasonCode.INSUFFICIENT_DATA
    assert result.diagnostics.status is DiagnosticStatus.INSUFFICIENT_DATA


def test_no_significant_deviation_means_monitor() -> None:
    result = run_analysis(soiled_case(0.01))
    rec = result.recommendation
    assert rec.decision is Decision.MONITOR
    assert rec.reason_code is ReasonCode.NO_SIGNIFICANT_DEVIATION
    assert result.diagnostics.status is DiagnosticStatus.NO_SIGNIFICANT_DEVIATION


def test_gap_inside_the_uncertainty_band_does_not_trigger_cleaning() -> None:
    # 3.5 % soiling is material, but with a 2 % baseline uncertainty k x u = 4.1 %.
    result = run_analysis(soiled_case(0.035))
    assert result.gap.window.significance.distinguishable is False
    assert result.recommendation.decision is Decision.MONITOR


# --------------------------------------------------------------------------- economics


def test_missing_cost_blocks_cleaning() -> None:
    result = run_analysis(soiled_case(0.08, economics=economic_inputs(labour_cost=None)))
    rec = result.recommendation
    assert rec.decision is Decision.INVESTIGATE
    assert rec.rule == "R5"
    assert rec.reason_code is ReasonCode.ECONOMIC_INPUTS_INCOMPLETE
    assert GateId.ECONOMICS_DECISION_GRADE in failed(result)


def test_missing_economics_blocks_cleaning() -> None:
    result = run_analysis(soiled_case(0.08, economics=None))
    assert result.recommendation.decision is Decision.INVESTIGATE
    assert result.recommendation.rule == "R5"


def test_missing_cleaning_assumptions_block_cleaning() -> None:
    result = run_analysis(soiled_case(0.08, cleaning=None))
    assert result.recommendation.decision is Decision.INVESTIGATE
    assert result.recommendation.rule == "R5"
    assert GateId.RECOVERABLE_ENERGY_ESTIMATED in failed(result)


def test_consumer_tariff_proxy_cannot_justify_cleaning() -> None:
    proxy = economic_inputs(energy_value_basis=EnergyValueBasis.CONSUMER_TARIFF_PROXY)
    result = run_analysis(soiled_case(0.08, economics=proxy))
    rec = result.recommendation
    assert rec.decision is Decision.INVESTIGATE
    assert rec.rule == "R5"


def test_unprofitable_cleaning_means_monitor() -> None:
    expensive = economic_inputs(labour_cost=5_000_000.0)
    result = run_analysis(soiled_case(0.08, economics=expensive))
    rec = result.recommendation
    assert rec.decision is Decision.MONITOR
    assert rec.reason_code is ReasonCode.CLEANING_NOT_PROFITABLE
    assert GateId.ECONOMICS_PROFITABLE in failed(result)


def test_marginal_cleaning_means_monitor() -> None:
    """Profitable in the base case only: not robust enough to act on."""
    # base recoverable 0.08 x 0.9 x 50 000 x 30 = 108 000 kWh -> 540 000 DZD
    marginal = economic_inputs(labour_cost=390_000.0, cost_uncertainty_pct=30.0)
    result = run_analysis(soiled_case(0.08, economics=marginal))
    rec = result.recommendation
    assert result.economics.verdict.value == "MARGINAL"
    assert rec.decision is Decision.MONITOR
    assert rec.reason_code is ReasonCode.CLEANING_MARGINAL


# --------------------------------------------------------------------------- the interlock


def test_interlock_withholds_clean_now_if_a_gate_was_bypassed() -> None:
    """Even if the rule path were wrong, the final check must stop an unjustified CLEAN_NOW."""
    result = run_analysis(soiled_case(0.08))
    assessment = result.evidence.model_copy(deep=True)
    # Corrupt the decisive evidence behind the gates' back: production is no longer measured.
    for item in assessment.decisive_evidence:
        if item.label == "Actual energy":
            item.effective_class = Provenance.SYNTHETIC
    rec = decide(
        assessment=assessment, diagnostics=result.diagnostics, recoverable=result.recoverable,
        economics=result.economics, context=EvaluationContext.OPERATIONAL, plant_is_demonstration=False,
        thresholds=AnalysisThresholds(),
    )
    assert rec.decision is Decision.INVESTIGATE
    assert rec.rule == "INTERLOCK"
    assert rec.safety_interlock_triggered
    assert not rec.operational_authorization


def test_interlock_checks_the_economics_independently() -> None:
    result = run_analysis(soiled_case(0.08))
    economics = result.economics.model_copy(deep=True)
    economics.scenarios[0].net_benefit = -1.0  # conservative case no longer positive
    rec = decide(
        assessment=result.evidence, diagnostics=result.diagnostics, recoverable=result.recoverable,
        economics=economics, context=EvaluationContext.OPERATIONAL, plant_is_demonstration=False,
        thresholds=AnalysisThresholds(),
    )
    assert rec.decision is Decision.INVESTIGATE
    assert rec.safety_interlock_triggered


# --------------------------------------------------------------------------- baseline declarations


def test_undeclared_baseline_properties_are_reported_not_assumed() -> None:
    result = run_analysis(soiled_case(0.08, baseline=BaselineDescriptor()))
    assert any("not declared" in text.lower() for text in result.baseline.limitations)


def test_the_engine_is_deterministic() -> None:
    first = run_analysis(soiled_case(0.08), now=at(0)).model_dump(mode="json")
    second = run_analysis(soiled_case(0.08), now=at(0)).model_dump(mode="json")
    assert first == second
