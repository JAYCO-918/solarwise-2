"""Plain description of the decision rules and gates.

This module documents :mod:`solarwise.core.decision`; it does not decide
anything.  The test suite checks that it stays in step with the engine (every
gate the engine produces is described here under the same label, and every rule
the engine can apply is listed).
"""

from __future__ import annotations

from pydantic import BaseModel

from solarwise.core.evidence import GateId


class GateDoc(BaseModel):
    id: GateId
    label: str
    requirement: str


class RuleDoc(BaseModel):
    id: str
    outcome: str
    applies_when: str
    rationale: str


GATES: tuple[GateDoc, ...] = (
    GateDoc(
        id=GateId.PRODUCTION_MEASURED, label="Reliable measured production data",
        requirement="The production channel is of the measured class, its metering is declared reliable enough, and "
                    "the assessment window is sufficiently complete. Synthetic, modelled or unknown-origin production "
                    "never passes outside a demonstration.",
    ),
    GateDoc(
        id=GateId.BASELINE_DOCUMENTED, label="Baseline of documented origin",
        requirement="The expected energy comes from a baseline whose method and source are declared.",
    ),
    GateDoc(
        id=GateId.DEVIATION_SIGNIFICANT, label="Significant under-performance now",
        requirement="In the assessment window the gap exceeds both the materiality threshold and the combined "
                    "expanded uncertainty of baseline and metering.",
    ),
    GateDoc(
        id=GateId.SOILING_EVIDENCE_CREDIBLE, label="Credible measured soiling evidence",
        requirement="A direct soiling measurement (soiling station, clean/dirty reference pair, or equivalent) of the "
                    "measured class, recent enough, showing a loss above the credibility floor and above its own "
                    "uncertainty. A production gap is not soiling evidence.",
    ),
    GateDoc(
        id=GateId.SOILING_CONSISTENT_WITH_GAP, label="Soiling measurement consistent with the production gap",
        requirement="The measured soiling loss and the gap left after the other quantified factors agree within the "
                    "tolerance.",
    ),
    GateDoc(
        id=GateId.NO_UNRESOLVED_TECHNICAL_ISSUE, label="No unresolved technical issue",
        requirement="No open outage, under-performing device, availability alert or unresolved fault record in the "
                    "assessment window.",
    ),
    GateDoc(
        id=GateId.NO_CRITICAL_CONTRADICTION, label="No critical contradiction in the evidence",
        requirement="No pair of sources contradict each other in a way that changes the conclusion (for example an "
                    "inspection finding clean modules while a sensor reports heavy soiling).",
    ),
    GateDoc(
        id=GateId.RECOVERABLE_ENERGY_ESTIMATED, label="Recoverable energy estimated from measured soiling",
        requirement="Cleaning effectiveness and benefit horizon were supplied, and the estimate rests on the credible "
                    "soiling measurement.",
    ),
    GateDoc(
        id=GateId.ECONOMICS_DECISION_GRADE, label="Economic inputs complete and decision-grade",
        requirement="Every cost item and the value of energy were supplied, and the value of energy is a selling "
                    "price, an avoided purchase cost or an internal valuation - not a consumer-tariff stand-in.",
    ),
    GateDoc(
        id=GateId.ECONOMICS_PROFITABLE, label="Cleaning profitable in the conservative case",
        requirement="The net benefit is positive with the low recoverable-energy estimate and the high cost estimate.",
    ),
)

GATE_LABELS: dict[GateId, str] = {g.id: g.label for g in GATES}

RULES: tuple[RuleDoc, ...] = (
    RuleDoc(
        id="R0", outcome="INVESTIGATE",
        applies_when="Production data are not reliable measured data, or the baseline is not documented.",
        rationale="Without trustworthy production and a known reference there is no gap to reason about.",
    ),
    RuleDoc(
        id="R1", outcome="INVESTIGATE",
        applies_when="A technical issue is open in the assessment window.",
        rationale="Its losses cannot be separated from soiling, and cleaning would not recover them.",
    ),
    RuleDoc(
        id="R2", outcome="INVESTIGATE",
        applies_when="The evidence contains a critical contradiction.",
        rationale="A decision resting on one of two contradicting sources would be arbitrary.",
    ),
    RuleDoc(
        id="R3", outcome="CLEAN_NOW",
        applies_when="Every one of the ten gates is passed.",
        rationale="Measured under-performance, explained by measured soiling, with nothing else open, and a "
                  "cleaning that pays even in the conservative case.",
    ),
    RuleDoc(
        id="R4", outcome="INVESTIGATE",
        applies_when="The deviation is significant, a material part of it is unexplained, and soiling is not "
                     "credibly measured and consistent with it.",
        rationale="A production gap alone does not prove soiling.",
    ),
    RuleDoc(
        id="R5", outcome="INVESTIGATE",
        applies_when="Soiling is credibly measured and matches the deviation, but the recoverable energy or the "
                     "economic inputs are not decision-grade.",
        rationale="It cannot yet be shown that cleaning pays.",
    ),
    RuleDoc(
        id="R6", outcome="MONITOR",
        applies_when="None of the above: no significant deviation, a deviation explained by something cleaning does "
                     "not change, or a cleaning that would not pay.",
        rationale="Nothing to act on now; the analysis is repeated after the review interval.",
    ),
    RuleDoc(
        id="INTERLOCK", outcome="INVESTIGATE",
        applies_when="A CLEAN_NOW result is re-checked independently against the gates and the provenance of its "
                     "decisive evidence, and the check fails.",
        rationale="Defence in depth: a programming error in the rules must not be able to issue a cleaning order.",
    ),
)

#: What each engineering threshold means.  Defaults live in :class:`solarwise.core.models.AnalysisThresholds`.
THRESHOLD_DOCS: dict[str, str] = {
    "gap_materiality_pct": "A relative gap below this is treated as normal variation [%].",
    "gap_severe_pct": "A relative gap above this is called severe [%].",
    "coverage_factor": "Coverage factor k applied to standard uncertainties (2 corresponds to about 95 %).",
    "min_data_completeness": "Minimum share of daylight intervals with both expected and actual data.",
    "assessment_window_days": "Length of the most recent window describing the current state of the plant [days].",
    "soiling_credibility_floor_pct": "A measured soiling loss below this is not treated as credible evidence [%].",
    "soiling_measurement_max_age_days": "Maximum age of a spot soiling measurement relative to the period end [days].",
    "consistency_tolerance_pct": "Allowed disagreement between the measured soiling loss and the gap it should "
                                 "explain [% points].",
    "rain_cleaning_threshold_mm": "Daily rainfall assumed to clean the array [mm] (Kimber et al. 2006 use about 6 mm).",
    "min_dry_days_for_trend": "Minimum dry spell before a downward trend is read as possible soiling [days].",
    "availability_alert_fraction": "Availability below this in the assessment window counts as an open equipment issue.",
    "device_underperformance_ratio": "A device yielding less than this share of the fleet median is under-performing.",
    "outage_actual_fraction": "Actual energy below this share of expected energy, in daylight, marks an outage interval.",
    "shading_edge_excess_pct": "Excess loss near sunrise or sunset over midday that suggests shading [% points].",
    "step_change_min_drop_pct": "A level shift of the performance index larger than this is an abrupt change [% points].",
    "factor_materiality_pct": "A quantified effect smaller than this share of expected energy is immaterial [%].",
}
