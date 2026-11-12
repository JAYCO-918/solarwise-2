"""The ten demonstration scenarios are the regression fixtures of the decision logic."""

from __future__ import annotations

import pytest

from solarwise.core.decision import Decision
from solarwise.core.diagnostics import DiagnosticCategory, SupportLevel
from solarwise.core.pipeline import AnalysisResult
from solarwise.core.provenance import EvaluationContext
from solarwise.demo.generator import DEFAULT_SEED, REFERENCE_PLANT, SYNTHETIC_STATEMENT
from solarwise.demo.run import parse_scenario, run_scenario
from solarwise.demo.scenarios import SCENARIO_KEYS, Scenario, build_all, build_scenario

SCENARIOS = {s.key: s for s in build_all()}
RESULTS: dict[str, AnalysisResult] = {key: run_scenario(s) for key, s in SCENARIOS.items()}


def support(result: AnalysisResult, category: DiagnosticCategory) -> SupportLevel:
    return next(h.support for h in result.diagnostics.hypotheses if h.category is category)


def test_there_are_ten_scenarios() -> None:
    assert len(SCENARIO_KEYS) == 10
    assert [s.number for s in SCENARIOS.values()] == list(range(1, 11))


@pytest.mark.parametrize("key", SCENARIO_KEYS)
def test_scenario_outcome(key: str) -> None:
    scenario, result = SCENARIOS[key], RESULTS[key]
    assert result.recommendation.decision.value == scenario.expected_decision
    assert result.recommendation.rule == scenario.expected_rule
    assert result.diagnostics.status.value == scenario.expected_diagnostic_status


@pytest.mark.safety
@pytest.mark.parametrize("key", SCENARIO_KEYS)
def test_no_scenario_ever_carries_an_operational_authorisation(key: str) -> None:
    rec = RESULTS[key].recommendation
    assert rec.simulated is True
    assert rec.operational_authorization is False
    assert rec.headline.startswith("SIMULATED DECISION")


@pytest.mark.safety
@pytest.mark.parametrize("key", SCENARIO_KEYS)
def test_synthetic_scenarios_are_refused_in_the_operational_context(key: str) -> None:
    """Outside a demonstration, synthetic data must never produce a cleaning decision."""
    result = run_scenario(SCENARIOS[key], EvaluationContext.OPERATIONAL)
    assert result.recommendation.decision is Decision.INVESTIGATE
    assert result.recommendation.rule == "R0"
    assert not result.recommendation.operational_authorization


@pytest.mark.safety
@pytest.mark.parametrize("key", SCENARIO_KEYS)
def test_every_scenario_is_labelled_synthetic(key: str) -> None:
    scenario, result = SCENARIOS[key], RESULTS[key]
    assert scenario.metadata.is_synthetic
    assert scenario.metadata.synthetic is not None
    assert scenario.metadata.synthetic.seed == DEFAULT_SEED
    assert scenario.metadata.disclaimer == SYNTHETIC_STATEMENT
    assert all(p.provenance.startswith("SYNTHETIC") for p in result.provenance)
    assert SYNTHETIC_STATEMENT in result.disclaimers
    assert any("synthetic data" in d for d in result.disclaimers)
    assert all(r.tag.is_synthetic for r in scenario.evidence)


def test_only_confirmed_soiling_leads_to_clean_now() -> None:
    clean_now = [key for key, r in RESULTS.items() if r.recommendation.decision is Decision.CLEAN_NOW]
    assert clean_now == ["S02_confirmed_soiling"]


def test_scenarios_are_reproducible() -> None:
    first = build_scenario("S05_shading", seed=7)
    second = build_scenario("S05_shading", seed=7)
    assert first.rows == second.rows
    other = build_scenario("S05_shading", seed=8)
    assert first.rows != other.rows


@pytest.mark.parametrize("seed", [1, 42, 20250101])
def test_outcomes_do_not_depend_on_the_random_seed(seed: int) -> None:
    for key in SCENARIO_KEYS:
        scenario = build_scenario(key, seed)
        result = run_scenario(scenario)
        assert result.recommendation.decision.value == scenario.expected_decision, (key, seed)
        assert result.recommendation.rule == scenario.expected_rule, (key, seed)


@pytest.mark.parametrize("key", SCENARIO_KEYS)
def test_scenarios_pass_the_same_validation_as_uploads(key: str) -> None:
    report, parsed = parse_scenario(SCENARIOS[key])
    assert report.accepted
    assert report.is_synthetic
    assert not [i for i in report.issues if i.severity.value in ("BLOCKING", "ERROR")]
    assert parsed.interval_minutes == SCENARIOS[key].interval_minutes


def test_reference_plant_is_marked_as_a_demonstration() -> None:
    assert REFERENCE_PLANT.is_demonstration
    assert REFERENCE_PLANT.capacity_dc_kwp == 300_000.0
    assert "synthetic" in REFERENCE_PLANT.name.lower()
    # Every assumed engineering parameter says that it is an assumption.
    for name in ("tilt_deg", "module_temp_coeff_per_c", "system_loss_fraction", "capacity_ac_kw"):
        assert "assumption" in REFERENCE_PLANT.parameter_notes[name].lower()


# --------------------------------------------------------------------------- per-scenario detail


def test_s01_normal_operation() -> None:
    result = RESULTS["S01_normal_operation"]
    assert abs(result.gap.window.result.relative_gap_pct or 0) < 3.0
    assert not result.diagnostics.deviation_now


def test_s02_confirmed_soiling() -> None:
    result = RESULTS["S02_confirmed_soiling"]
    assert support(result, DiagnosticCategory.SOILING) is SupportLevel.STRONG
    assert result.diagnostics.soiling_evidence.credible
    assert result.diagnostics.soiling_evidence.consistent_with_gap
    # Injected: 0.15 %/day -> about 8.6 % averaged over the last seven days.
    assert result.diagnostics.soiling_evidence.loss_pct == pytest.approx(8.55, abs=0.3)
    assert result.trend.slope_pct_per_day == pytest.approx(-0.15, abs=0.02)
    assert result.economics.verdict.value == "PROFITABLE"
    assert all(g.passed for g in result.recommendation.gates)


def test_s03_temperature_effect() -> None:
    result = RESULTS["S03_temperature_effect"]
    assert support(result, DiagnosticCategory.TEMPERATURE) is SupportLevel.STRONG
    assert support(result, DiagnosticCategory.SOILING) is SupportLevel.NOT_SUPPORTED
    assert result.diagnostics.deviation_now
    assert not result.diagnostics.unexplained_residual_material
    assert result.recommendation.reason_code.value == "DEVIATION_EXPLAINED_NOT_SOILING"


def test_s04_inverter_fault() -> None:
    result = RESULTS["S04_inverter_fault"]
    assert support(result, DiagnosticCategory.INVERTER) is SupportLevel.STRONG
    assert result.diagnostics.unresolved_technical_issue
    offline = {f.device_code for f in result.devices.findings if f.status == "OFFLINE"}
    assert offline == {"BLK-07", "BLK-13"}
    assert result.gap.window.result.relative_gap_pct == pytest.approx(10.0, abs=1.0)


def test_s05_shading() -> None:
    result = RESULTS["S05_shading"]
    assert support(result, DiagnosticCategory.SHADING) is SupportLevel.MODERATE  # a proxy until confirmed on site
    assert result.intraday.shading_signature
    assert result.intraday.edge_side == "MORNING"
    assert result.diagnostics.unexplained_residual_material
    assert any("Inspect the site" in a for a in result.recommendation.next_actions)


def test_s06_curtailment() -> None:
    result = RESULTS["S06_curtailment"]
    assert support(result, DiagnosticCategory.CURTAILMENT_DOWNTIME) is SupportLevel.STRONG
    assert not result.diagnostics.unexplained_residual_material
    assert result.recommendation.reason_code.value == "DEVIATION_EXPLAINED_NOT_SOILING"


def test_s07_missing_data() -> None:
    result = RESULTS["S07_missing_data"]
    assert (result.gap.window.coverage.fraction or 0) < 0.9
    assert result.quality.status.value == "INSUFFICIENT"
    assert result.evidence.quality.value == "INSUFFICIENT"
    # Missing days stay missing: 13 of 60 days have no usable production value.
    assert sum(1 for d in result.gap.daily if d.status == "MISSING") == 13
    assert result.recoverable.recoverable.central is None


def test_s08_conflicting_evidence() -> None:
    result = RESULTS["S08_conflicting_evidence"]
    codes = {c.code for c in result.diagnostics.conflicts if c.severity == "CRITICAL"}
    assert "C-INSPECTION-VS-SENSOR" in codes
    assert result.recoverable.recoverable.central is None


def test_s09_is_numerically_identical_to_s02_but_refused() -> None:
    s02, s09 = SCENARIOS["S02_confirmed_soiling"], SCENARIOS["S09_synthetic_demonstration"]
    assert s02.rows == s09.rows
    r02, r09 = RESULTS["S02_confirmed_soiling"], RESULTS["S09_synthetic_demonstration"]
    assert r02.gap.result.relative_gap_pct == pytest.approx(r09.gap.result.relative_gap_pct)
    assert r02.recommendation.decision is Decision.CLEAN_NOW
    assert r09.recommendation.decision is Decision.INVESTIGATE
    assert r09.recommendation.reason_code.value == "NON_MEASURED_PRODUCTION"
    assert r09.recoverable.recoverable.central is None


def test_s10_unprofitable_cleaning() -> None:
    result = RESULTS["S10_unprofitable_cleaning"]
    assert result.diagnostics.soiling_evidence.credible
    assert result.economics.verdict.value == "UNPROFITABLE"
    assert result.recommendation.reason_code.value == "CLEANING_NOT_PROFITABLE"
    base = result.economics.scenarios[1]
    assert base.net_benefit is not None and base.net_benefit < 0


def test_scenario_type_is_exported() -> None:
    assert isinstance(SCENARIOS["S01_normal_operation"], Scenario)
