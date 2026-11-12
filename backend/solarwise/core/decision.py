"""Decision engine: CLEAN_NOW / MONITOR / INVESTIGATE.

The rules are evaluated in a fixed order; the first one that applies decides.

``R0  INVESTIGATE``  production data are not reliable measured data, or the
                     baseline is of unknown origin.
``R1  INVESTIGATE``  a technical issue is unresolved in the assessment window.
``R2  INVESTIGATE``  the evidence contains a critical contradiction.
``R3  CLEAN_NOW``    every gate is passed (see :data:`CLEAN_NOW_GATES`).
``R4  INVESTIGATE``  a significant deviation is left unexplained.
``R5  INVESTIGATE``  soiling is credibly measured and matches the deviation,
                     but the recoverable-energy or economic inputs are
                     incomplete or not decision-grade.
``R6  MONITOR``      none of the above: no significant deviation, a deviation
                     explained by a cause cleaning cannot remove, weak evidence,
                     or a cleaning that does not pay.

Safety properties (enforced twice: by the rule order and by a final interlock
that re-checks every gate independently of the path taken):

* a production gap alone never leads to ``CLEAN_NOW`` - credible *measured*
  soiling evidence is a mandatory gate;
* modelled, synthetic or unknown-origin data in the role of production or of
  soiling evidence never lead to an operational ``CLEAN_NOW``;
* in a demonstration context a ``CLEAN_NOW`` is a *simulated* decision and never
  carries an operational authorisation;
* the engine is the only component that can output a decision - the optional AI
  layer receives the result read-only.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from solarwise.core.diagnostics import DiagnosticCategory, DiagnosticReport, DiagnosticStatus, SupportLevel
from solarwise.core.economics import EconomicsResult, EconomicStatus, ScenarioName, Verdict
from solarwise.core.evidence import DecisiveEvidence, EvidenceAssessment, Gate, GateId
from solarwise.core.models import AnalysisThresholds
from solarwise.core.provenance import EvaluationContext, Provenance
from solarwise.core.recoverable import RecoverableEnergy, RecoverableStatus


class Decision(StrEnum):
    CLEAN_NOW = "CLEAN_NOW"
    MONITOR = "MONITOR"
    INVESTIGATE = "INVESTIGATE"


class ReasonCode(StrEnum):
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NON_MEASURED_PRODUCTION = "NON_MEASURED_PRODUCTION"
    TECHNICAL_ISSUE = "TECHNICAL_ISSUE"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    CLEANING_JUSTIFIED = "CLEANING_JUSTIFIED"
    UNEXPLAINED_DEVIATION = "UNEXPLAINED_DEVIATION"
    ECONOMIC_INPUTS_INCOMPLETE = "ECONOMIC_INPUTS_INCOMPLETE"
    NO_SIGNIFICANT_DEVIATION = "NO_SIGNIFICANT_DEVIATION"
    CLEANING_NOT_PROFITABLE = "CLEANING_NOT_PROFITABLE"
    CLEANING_MARGINAL = "CLEANING_MARGINAL"
    DEVIATION_EXPLAINED_NOT_SOILING = "DEVIATION_EXPLAINED_NOT_SOILING"
    EVIDENCE_WEAK = "EVIDENCE_WEAK"
    SAFETY_INTERLOCK = "SAFETY_INTERLOCK"


#: One short sentence per outcome.  The detailed reasons follow separately.
HEADLINES: dict[ReasonCode, str] = {
    ReasonCode.CLEANING_JUSTIFIED: "measured soiling explains the loss and cleaning pays even in the conservative case",
    ReasonCode.UNEXPLAINED_DEVIATION: "a significant loss is not explained, and a production gap alone does not prove soiling",
    ReasonCode.NON_MEASURED_PRODUCTION: "the production data are not measured data and cannot support a cleaning decision",
    ReasonCode.INSUFFICIENT_DATA: "the data are not sufficient to support a decision",
    ReasonCode.TECHNICAL_ISSUE: "a technical issue is open and has to be resolved first",
    ReasonCode.CONFLICTING_EVIDENCE: "the evidence contradicts itself",
    ReasonCode.NO_SIGNIFICANT_DEVIATION: "production is in line with the baseline",
    ReasonCode.ECONOMIC_INPUTS_INCOMPLETE: "soiling is measured, but it cannot yet be shown that cleaning pays",
    ReasonCode.CLEANING_NOT_PROFITABLE: "soiling is measured, but cleaning now would cost more than it recovers",
    ReasonCode.CLEANING_MARGINAL: "soiling is measured, but cleaning now is not robustly profitable",
    ReasonCode.DEVIATION_EXPLAINED_NOT_SOILING: "the loss is explained by a cause that cleaning does not address",
    ReasonCode.EVIDENCE_WEAK: "the evidence does not point to a loss that cleaning would recover",
    ReasonCode.SAFETY_INTERLOCK: "a cleaning decision was withheld by the safety interlock",
}

#: Every one of these gates must be passed for CLEAN_NOW.
CLEAN_NOW_GATES: tuple[GateId, ...] = (
    GateId.PRODUCTION_MEASURED,
    GateId.BASELINE_DOCUMENTED,
    GateId.DEVIATION_SIGNIFICANT,
    GateId.SOILING_EVIDENCE_CREDIBLE,
    GateId.SOILING_CONSISTENT_WITH_GAP,
    GateId.NO_UNRESOLVED_TECHNICAL_ISSUE,
    GateId.NO_CRITICAL_CONTRADICTION,
    GateId.RECOVERABLE_ENERGY_ESTIMATED,
    GateId.ECONOMICS_DECISION_GRADE,
    GateId.ECONOMICS_PROFITABLE,
)


class Recommendation(BaseModel):
    decision: Decision
    #: Identifier of the rule that decided (R0 .. R6, or INTERLOCK).
    rule: str
    reason_code: ReasonCode
    headline: str
    context: EvaluationContext
    #: The decision was produced in a demonstration context (reference plant or scenario).
    simulated: bool
    #: True only for a CLEAN_NOW on a real plant, in the operational context, with no synthetic evidence.
    operational_authorization: bool
    authorization_note: str
    reasons: list[str]
    next_actions: list[str]
    #: What would have to change for the decision to change.
    would_change_decision: list[str]
    gates: list[Gate]
    failed_gates: list[GateId]
    decisive_evidence: list[DecisiveEvidence]
    safety_interlock_triggered: bool = False
    #: Suggested number of days before the analysis is repeated.
    review_after_days: int | None = None
    rule_trace: list[str] = Field(default_factory=list)


def _interlock_violations(
    assessment: EvidenceAssessment,
    recoverable: RecoverableEnergy,
    economics: EconomicsResult,
) -> list[str]:
    """Independent re-check of everything a CLEAN_NOW requires."""
    problems = [f"gate {g.value} not passed" for g in CLEAN_NOW_GATES if not assessment.passed(g)]
    for item in assessment.decisive_evidence:
        if item.label == "Expected energy (baseline)":
            if item.effective_class in (Provenance.UNKNOWN, Provenance.SYNTHETIC):
                problems.append(f"baseline counts as {item.effective_class.value}")
        elif item.effective_class is not Provenance.MEASURED:
            problems.append(f"{item.label.lower()} counts as {item.effective_class.value}, not MEASURED")
    if not any(d.label == "Soiling measurement" for d in assessment.decisive_evidence):
        problems.append("no soiling measurement among the decisive evidence")
    if recoverable.status is not RecoverableStatus.ESTIMATED or not recoverable.usable_for_decision:
        problems.append("recoverable energy is not an estimate based on measured soiling")
    conservative = economics.scenario(ScenarioName.CONSERVATIVE)
    if economics.status is not EconomicStatus.COMPLETE or not economics.decision_grade:
        problems.append("economics incomplete or not decision-grade")
    if conservative.net_benefit is None or conservative.net_benefit <= 0:
        problems.append("conservative net benefit is not positive")
    return problems


def decide(
    *,
    assessment: EvidenceAssessment,
    diagnostics: DiagnosticReport,
    recoverable: RecoverableEnergy,
    economics: EconomicsResult,
    context: EvaluationContext,
    plant_is_demonstration: bool,
    thresholds: AnalysisThresholds,
    allow_operational_authorization: bool = True,
) -> Recommendation:
    """Apply the decision rules.  Deterministic: same inputs, same output."""
    trace: list[str] = []
    reasons: list[str] = []
    actions: list[str] = []
    change: list[str] = []
    ok = assessment.passed
    ev = diagnostics.soiling_evidence
    review: int | None = thresholds.assessment_window_days

    def gate_detail(gate_id: GateId) -> str:
        return assessment.gate(gate_id).detail

    leading = [h for h in diagnostics.hypotheses if h.category in diagnostics.leading]

    # ---------------------------------------------------------------- R0
    if not ok(GateId.PRODUCTION_MEASURED) or not ok(GateId.BASELINE_DOCUMENTED):
        decision, rule = Decision.INVESTIGATE, "R0"
        non_measured = any(
            d.label == "Actual energy" and d.effective_class is not Provenance.MEASURED
            for d in assessment.decisive_evidence
        )
        code = ReasonCode.NON_MEASURED_PRODUCTION if non_measured else ReasonCode.INSUFFICIENT_DATA
        if not ok(GateId.PRODUCTION_MEASURED):
            reasons.append(gate_detail(GateId.PRODUCTION_MEASURED))
        if not ok(GateId.BASELINE_DOCUMENTED):
            reasons.append(gate_detail(GateId.BASELINE_DOCUMENTED))
        if non_measured:
            reasons.append(
                "Only measured production can support a cleaning decision. Synthetic, modelled or "
                "unknown-origin production data are shown for information and cannot trigger CLEAN_NOW."
            )
            actions.append("Connect or import measured production data (revenue meter or inverter telemetry) with declared provenance.")
        else:
            actions.append("Restore complete production telemetry for the assessment window and document the baseline.")
        change.append("Reliable measured production data with sufficient completeness, and a baseline of documented origin.")
        trace.append("R0 applies: production not reliable measured data or baseline not documented")
    # ---------------------------------------------------------------- R1
    elif not ok(GateId.NO_UNRESOLVED_TECHNICAL_ISSUE):
        decision, rule, code = Decision.INVESTIGATE, "R1", ReasonCode.TECHNICAL_ISSUE
        reasons.extend(diagnostics.technical_issues)
        reasons.append(
            "While a technical issue is open, its losses cannot be separated reliably from soiling, and "
            "cleaning would not recover them."
        )
        for h in diagnostics.hypotheses:
            if h.category in (DiagnosticCategory.INVERTER, DiagnosticCategory.CURTAILMENT_DOWNTIME) and h.active_in_window:
                actions.extend(h.recommended_investigation)
        if not actions:
            actions.append("Resolve the open technical issue, then repeat the analysis.")
        change.append("The technical issue is resolved (or documented as closed) and the analysis is repeated on data after the fix.")
        trace.extend(["R0 passed", "R1 applies: unresolved technical issue in the assessment window"])
    # ---------------------------------------------------------------- R2
    elif not ok(GateId.NO_CRITICAL_CONTRADICTION):
        decision, rule, code = Decision.INVESTIGATE, "R2", ReasonCode.CONFLICTING_EVIDENCE
        for conflict in diagnostics.conflicts:
            if conflict.severity == "CRITICAL":
                reasons.append(conflict.description)
                actions.append(conflict.resolution)
        change.append("The contradicting sources are reconciled (sensor verified, measurement repeated, or baseline reviewed).")
        trace.extend(["R0 passed", "R1 passed", "R2 applies: critical contradiction"])
    # ---------------------------------------------------------------- R3
    elif all(ok(g) for g in CLEAN_NOW_GATES):
        decision, rule, code = Decision.CLEAN_NOW, "R3", ReasonCode.CLEANING_JUSTIFIED
        conservative = economics.scenario(ScenarioName.CONSERVATIVE)
        base = economics.scenario(ScenarioName.BASE)
        if conservative.net_benefit is not None and base.net_benefit is not None:
            economics_text = (
                f"Net benefit: {conservative.net_benefit:,.0f} {economics.currency} in the conservative case, "
                f"{base.net_benefit:,.0f} {economics.currency} in the base case"
                + (f" (ROI {base.roi_pct:,.0f} %)." if base.roi_pct is not None else ".")
            )
        else:  # pragma: no cover - excluded by the ECONOMICS_PROFITABLE gate
            economics_text = gate_detail(GateId.ECONOMICS_PROFITABLE)
        reasons.extend(
            [
                gate_detail(GateId.DEVIATION_SIGNIFICANT),
                gate_detail(GateId.SOILING_EVIDENCE_CREDIBLE),
                gate_detail(GateId.SOILING_CONSISTENT_WITH_GAP),
                "No technical issue is open and the evidence is free of critical contradictions.",
                gate_detail(GateId.RECOVERABLE_ENERGY_ESTIMATED),
                economics_text,
            ]
        )
        actions.extend(
            [
                "Schedule the cleaning; record its date, method, water use and cost.",
                "Measure the soiling ratio again after cleaning to verify the recovery and to refine the "
                "cleaning-effectiveness assumption.",
            ]
        )
        change.append("Any gate failing: a technical issue appearing, the soiling measurement becoming outdated, or costs rising above the break-even.")
        review = None
        trace.extend(["R0 passed", "R1 passed", "R2 passed", "R3 applies: all gates passed"])
    # ---------------------------------------------------------------- R4
    elif (
        ok(GateId.DEVIATION_SIGNIFICANT)
        and diagnostics.unexplained_residual_material
        and not (ok(GateId.SOILING_EVIDENCE_CREDIBLE) and ok(GateId.SOILING_CONSISTENT_WITH_GAP))
    ):
        decision, rule, code = Decision.INVESTIGATE, "R4", ReasonCode.UNEXPLAINED_DEVIATION
        reasons.append(gate_detail(GateId.DEVIATION_SIGNIFICANT))
        reasons.append(
            f"{diagnostics.unexplained_residual_pct:.1f} % of expected energy in the assessment window is not "
            "explained by any credibly quantified factor."
            if diagnostics.unexplained_residual_pct is not None
            else "A material residual is not explained by any credibly quantified factor."
        )
        if not ev.available:
            reasons.append(
                "There is no soiling measurement. A production gap does not prove soiling: cleaning on this "
                "basis could spend water and money without recovering the loss."
            )
        elif not ev.credible:
            reasons.append(
                "The soiling information available does not qualify as credible measured evidence. "
                + gate_detail(GateId.SOILING_EVIDENCE_CREDIBLE)
            )
        if leading:
            reasons.append(
                "Plausible explanations to follow up: "
                + "; ".join(f"{h.title.lower()} ({h.support.value.lower()} support)" for h in leading)
                + "."
            )
        for h in leading:
            actions.extend(h.recommended_investigation)
        soiling_h = next(h for h in diagnostics.hypotheses if h.category is DiagnosticCategory.SOILING)
        if soiling_h.support in (SupportLevel.MODERATE, SupportLevel.WEAK) and soiling_h not in leading:
            actions.extend(soiling_h.recommended_investigation)
        unclassified = next(h for h in diagnostics.hypotheses if h.category is DiagnosticCategory.UNCLASSIFIED)
        actions.extend(unclassified.recommended_investigation)
        change.append("A direct soiling measurement that accounts for the deviation (would open the way to CLEAN_NOW, economics permitting).")
        change.append("Identification and repair of another cause, after which the deviation disappears.")
        trace.extend(["R0 passed", "R1 passed", "R2 passed", "R3 not met", "R4 applies: significant unexplained deviation"])
    # ---------------------------------------------------------------- R5
    elif (
        ok(GateId.DEVIATION_SIGNIFICANT)
        and ok(GateId.SOILING_EVIDENCE_CREDIBLE)
        and ok(GateId.SOILING_CONSISTENT_WITH_GAP)
        and not (ok(GateId.RECOVERABLE_ENERGY_ESTIMATED) and ok(GateId.ECONOMICS_DECISION_GRADE))
    ):
        decision, rule, code = Decision.INVESTIGATE, "R5", ReasonCode.ECONOMIC_INPUTS_INCOMPLETE
        reasons.append("Soiling is credibly measured and matches the deviation, but it cannot yet be shown that cleaning pays.")
        if not ok(GateId.RECOVERABLE_ENERGY_ESTIMATED):
            reasons.append(gate_detail(GateId.RECOVERABLE_ENERGY_ESTIMATED))
        if not ok(GateId.ECONOMICS_DECISION_GRADE):
            reasons.append(gate_detail(GateId.ECONOMICS_DECISION_GRADE))
        actions.append("Supply the missing cleaning assumptions and cost inputs, then re-evaluate.")
        change.append("Complete, decision-grade economic inputs showing a positive net benefit in the conservative case.")
        trace.extend(["R0 passed", "R1 passed", "R2 passed", "R3 not met", "R4 not met", "R5 applies: economics incomplete"])
    # ---------------------------------------------------------------- R6
    else:
        decision, rule = Decision.MONITOR, "R6"
        trace.extend(["R0 passed", "R1 passed", "R2 passed", "R3 not met", "R4 not met", "R5 not met", "R6 applies"])
        soiling_confirmed = (
            ok(GateId.DEVIATION_SIGNIFICANT)
            and ok(GateId.SOILING_EVIDENCE_CREDIBLE)
            and ok(GateId.SOILING_CONSISTENT_WITH_GAP)
        )
        if soiling_confirmed and economics.status is EconomicStatus.COMPLETE:
            base = economics.scenario(ScenarioName.BASE)
            conservative = economics.scenario(ScenarioName.CONSERVATIVE)
            if economics.verdict is Verdict.MARGINAL:
                code = ReasonCode.CLEANING_MARGINAL
                reasons.append(
                    f"Soiling is measured ({ev.loss_pct:.1f} %), but cleaning now is not robustly profitable: "
                    f"net benefit {base.net_benefit:,.0f} {economics.currency} in the base case, "
                    f"{conservative.net_benefit:,.0f} {economics.currency} in the conservative case."
                )
            else:
                code = ReasonCode.CLEANING_NOT_PROFITABLE
                reasons.append(
                    f"Soiling is measured ({ev.loss_pct:.1f} %), but cleaning now would cost more than it "
                    f"recovers: net benefit {base.net_benefit:,.0f} {economics.currency} in the base case."
                )
            if economics.break_even_energy_kwh is not None:
                text = f"Break-even: the cleaning must recover {economics.break_even_energy_kwh / 1000:,.1f} MWh"
                if economics.break_even_soiling_loss_pct is not None:
                    text += f", i.e. a soiling loss of about {economics.break_even_soiling_loss_pct:.1f} % over the benefit horizon"
                reasons.append(text + ".")
            actions.append("Keep tracking the soiling ratio; re-evaluate when the loss approaches the break-even level or before a long dry period.")
            change.append("Soiling loss rising above the break-even level, lower cleaning cost, or a longer benefit horizon.")
        elif not ok(GateId.DEVIATION_SIGNIFICANT):
            code = ReasonCode.NO_SIGNIFICANT_DEVIATION
            reasons.append(gate_detail(GateId.DEVIATION_SIGNIFICANT))
            reasons.append("Production is in line with the baseline in the assessment window; there is no loss to act upon.")
            if diagnostics.deviation_period:
                reasons.append("A deviation earlier in the period is no longer present in the assessment window.")
            if ev.available and ev.credible:
                reasons.append(
                    f"A soiling loss of {ev.loss_pct:.1f} % is measured but does not yet show as a significant "
                    "production deviation."
                )
            actions.append("Continue routine monitoring.")
            change.append("A significant deviation appearing together with credible measured soiling evidence and favourable economics.")
        elif diagnostics.status in (DiagnosticStatus.SINGLE_EXPLANATION, DiagnosticStatus.MULTIPLE_PLAUSIBLE) and leading:
            code = ReasonCode.DEVIATION_EXPLAINED_NOT_SOILING
            reasons.append(gate_detail(GateId.DEVIATION_SIGNIFICANT))
            reasons.append(
                "The deviation is accounted for by: "
                + "; ".join(f"{h.title.lower()} - {h.summary}" for h in leading)
            )
            reasons.append("No material loss is left unexplained, and cleaning would not recover a loss of this kind.")
            actions.append("Continue monitoring; no cleaning is indicated by this deviation.")
            for h in leading:
                actions.extend(h.recommended_investigation[:1])
            change.append("A soiling measurement showing a material loss, or a residual appearing once the identified cause ends.")
        else:
            code = ReasonCode.EVIDENCE_WEAK
            reasons.append(gate_detail(GateId.DEVIATION_SIGNIFICANT))
            reasons.append("The evidence available does not point to a loss that cleaning would recover.")
            actions.append("Continue monitoring and add a direct soiling measurement if the deviation persists.")
            change.append("Credible measured soiling evidence consistent with the deviation.")

    # ---------------------------------------------------------------- safety interlock
    interlock = False
    if decision is Decision.CLEAN_NOW:
        violations = _interlock_violations(assessment, recoverable, economics)
        if violations:
            interlock = True
            decision, rule, code = Decision.INVESTIGATE, "INTERLOCK", ReasonCode.SAFETY_INTERLOCK
            reasons = [
                "Safety interlock: the conditions for CLEAN_NOW were not all confirmed on independent re-check ("
                + "; ".join(violations)
                + "). The decision was withheld."
            ]
            actions = ["Review the evidence listed under the failed gates."]
            change = ["Every CLEAN_NOW gate confirmed."]
            review = thresholds.assessment_window_days
            trace.append("INTERLOCK: CLEAN_NOW withheld")

    # ---------------------------------------------------------------- context and authorisation
    simulated = context is EvaluationContext.DEMONSTRATION or plant_is_demonstration
    authorised = (
        decision is Decision.CLEAN_NOW
        and context is EvaluationContext.OPERATIONAL
        and not plant_is_demonstration
        and not assessment.synthetic_evidence_present
        and allow_operational_authorization
    )
    if authorised:
        note = (
            "Operational recommendation based on measured evidence. The cleaning must still be approved and "
            "scheduled by the responsible operator."
        )
    elif decision is Decision.CLEAN_NOW and simulated:
        note = (
            "SIMULATED DECISION. It rests on a demonstration scenario"
            + (" with synthetic evidence" if assessment.synthetic_evidence_present else "")
            + " and is not an operational instruction. No cleaning may be ordered on this basis."
        )
    elif decision is Decision.CLEAN_NOW:
        note = "Advisory evaluation of supplied figures; it does not authorise a cleaning."
    elif simulated:
        note = "Simulated evaluation of a demonstration scenario; not an operational instruction."
    else:
        note = "No cleaning is authorised by this evaluation."

    labels = {
        Decision.CLEAN_NOW: "Clean now",
        Decision.MONITOR: "Monitor",
        Decision.INVESTIGATE: "Investigate",
    }
    headline = f"{labels[decision]}: {HEADLINES[code]}."
    if simulated:
        headline = f"SIMULATED DECISION - {headline} Not an operational instruction."

    failed = [g.id for g in assessment.gates if g.id in CLEAN_NOW_GATES and g.passed is not True]
    return Recommendation(
        decision=decision,
        rule=rule,
        reason_code=code,
        headline=headline,
        context=context,
        simulated=simulated,
        operational_authorization=authorised,
        authorization_note=note,
        reasons=reasons,
        next_actions=list(dict.fromkeys(actions)),
        would_change_decision=change,
        gates=assessment.gates,
        failed_gates=failed,
        decisive_evidence=assessment.decisive_evidence,
        safety_interlock_triggered=interlock,
        review_after_days=review,
        rule_trace=trace,
    )
