"""The published description of the rules must match what the engine does."""

from __future__ import annotations

import pytest

from solarwise.core import rules
from solarwise.core.decision import CLEAN_NOW_GATES, HEADLINES, Decision, ReasonCode
from solarwise.core.evidence import GateId
from solarwise.core.models import AnalysisThresholds
from solarwise.core.pipeline import run_analysis
from solarwise.core.provenance import EvaluationContext
from solarwise.demo.run import run_scenario
from solarwise.demo.scenarios import SCENARIO_KEYS, build_scenario
from tests.builders import soiled_case


def test_every_gate_is_documented_under_the_label_the_engine_uses() -> None:
    result = run_analysis(soiled_case())
    produced = {gate.id: gate.label for gate in result.recommendation.gates}
    assert produced == rules.GATE_LABELS
    assert [g.id for g in rules.GATES] == list(GateId) == list(CLEAN_NOW_GATES)


@pytest.mark.parametrize("key", SCENARIO_KEYS)
def test_every_rule_the_engine_applies_is_documented_with_its_outcome(key: str) -> None:
    recommendation = run_scenario(build_scenario(key), EvaluationContext.DEMONSTRATION).recommendation
    documented = {rule.id: rule for rule in rules.RULES}
    assert recommendation.rule in documented
    assert documented[recommendation.rule].outcome == recommendation.decision.value


def test_rule_list_is_complete_and_ordered() -> None:
    assert [r.id for r in rules.RULES] == ["R0", "R1", "R2", "R3", "R4", "R5", "R6", "INTERLOCK"]
    assert {r.outcome for r in rules.RULES} == {d.value for d in Decision}
    assert [r.id for r in rules.RULES if r.outcome == "CLEAN_NOW"] == ["R3"]


def test_every_threshold_is_explained() -> None:
    assert set(rules.THRESHOLD_DOCS) == set(AnalysisThresholds.model_fields)
    assert all(text.strip() for text in rules.THRESHOLD_DOCS.values())


def test_every_reason_code_has_a_headline() -> None:
    assert set(HEADLINES) == set(ReasonCode)
    assert "production gap alone does not prove soiling" in HEADLINES[ReasonCode.UNEXPLAINED_DEVIATION]
