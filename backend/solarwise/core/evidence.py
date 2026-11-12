"""Evidence assessment.

Turns the outputs of the earlier stages into an explicit list of *gates* - the
conditions a cleaning recommendation depends on - each with the evidence it
rests on and that evidence's provenance.  The decision engine reads the gates;
it does not re-derive them.

It also grades how adequate the data are for diagnosis (``HIGH`` .. ``INSUFFICIENT``).
The grade is a transparent checklist count, not a probability.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from solarwise.core.baseline import BaselineResult
from solarwise.core.diagnostics import DiagnosticInputs as _DiagnosticInputs
from solarwise.core.diagnostics import DiagnosticReport, production_is_reliable
from solarwise.core.economics import EconomicsResult, EconomicStatus, ScenarioName, Verdict
from solarwise.core.models import Metric
from solarwise.core.provenance import EvaluationContext, Provenance, ProvenanceTag
from solarwise.core.recoverable import RecoverableEnergy, RecoverableStatus
from solarwise.core.timeline import DAILY_MINUTES


class GateId(StrEnum):
    PRODUCTION_MEASURED = "PRODUCTION_MEASURED"
    BASELINE_DOCUMENTED = "BASELINE_DOCUMENTED"
    DEVIATION_SIGNIFICANT = "DEVIATION_SIGNIFICANT"
    SOILING_EVIDENCE_CREDIBLE = "SOILING_EVIDENCE_CREDIBLE"
    SOILING_CONSISTENT_WITH_GAP = "SOILING_CONSISTENT_WITH_GAP"
    NO_UNRESOLVED_TECHNICAL_ISSUE = "NO_UNRESOLVED_TECHNICAL_ISSUE"
    NO_CRITICAL_CONTRADICTION = "NO_CRITICAL_CONTRADICTION"
    RECOVERABLE_ENERGY_ESTIMATED = "RECOVERABLE_ENERGY_ESTIMATED"
    ECONOMICS_DECISION_GRADE = "ECONOMICS_DECISION_GRADE"
    ECONOMICS_PROFITABLE = "ECONOMICS_PROFITABLE"


class Gate(BaseModel):
    id: GateId
    label: str
    #: ``True`` passed, ``False`` failed, ``None`` could not be evaluated (counts as not passed).
    passed: bool | None
    detail: str


class DecisiveEvidence(BaseModel):
    """A piece of evidence a CLEAN_NOW decision would rest on."""

    label: str
    tag: ProvenanceTag
    effective_class: Provenance


class EvidenceQuality(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INSUFFICIENT = "INSUFFICIENT"


class QualityCheck(BaseModel):
    label: str
    met: bool
    detail: str


class EvidenceAssessment(BaseModel):
    gates: list[Gate]
    decisive_evidence: list[DecisiveEvidence]
    #: At least one decisive piece of evidence is synthetic (whatever it emulates).
    synthetic_evidence_present: bool
    quality: EvidenceQuality
    quality_checks: list[QualityCheck]
    quality_note: str = (
        "The grade counts which kinds of evidence are available. It describes how well a cause can be "
        "investigated with the data at hand; it is not a probability that a diagnosis is right."
    )
    reasons_production_unreliable: list[str] = Field(default_factory=list)

    def gate(self, gate_id: GateId) -> Gate:
        return next(g for g in self.gates if g.id is gate_id)

    def passed(self, gate_id: GateId) -> bool:
        return self.gate(gate_id).passed is True


def assess_evidence(
    inp: _DiagnosticInputs,
    baseline: BaselineResult,
    diagnostics: DiagnosticReport,
    recoverable: RecoverableEnergy,
    economics: EconomicsResult,
    *,
    interval_minutes: int,
) -> EvidenceAssessment:
    ctx: EvaluationContext = inp.context
    th = inp.thresholds
    gates: list[Gate] = []

    # --- production
    reliable, reasons = production_is_reliable(inp)
    actual_tag = inp.gap.actual.tag
    gates.append(
        Gate(
            id=GateId.PRODUCTION_MEASURED,
            label="Reliable measured production data",
            passed=reliable,
            detail=(
                f"Actual energy: {actual_tag.label} ({actual_tag.source}); completeness "
                f"{(inp.gap.coverage.fraction or 0) * 100:.0f} % over the period, "
                f"{(inp.gap.window.coverage.fraction or 0) * 100:.0f} % in the assessment window."
                if reliable
                else " ".join(reasons)
            ),
        )
    )

    # --- baseline
    baseline_class = baseline.meta.tag.effective_class(ctx)
    baseline_ok = baseline_class is not Provenance.UNKNOWN and (
        baseline_class is not Provenance.SYNTHETIC
    )
    gates.append(
        Gate(
            id=GateId.BASELINE_DOCUMENTED,
            label="Baseline of documented origin",
            passed=baseline_ok,
            detail=(
                f"Baseline: {baseline.method.value}, {baseline.meta.tag.label} ({baseline.meta.tag.source})."
                if baseline_ok
                else f"Baseline provenance {baseline.meta.tag.label} counts as {baseline_class.value} in the "
                f"{ctx.value} context: it cannot anchor a decision."
            ),
        )
    )

    # --- deviation
    sig = inp.gap.window.significance
    rel = inp.gap.window.result.relative_gap_pct
    gates.append(
        Gate(
            id=GateId.DEVIATION_SIGNIFICANT,
            label="Significant under-performance now",
            passed=diagnostics.deviation_now if sig.significant is not None else None,
            detail=(
                f"Gap in the assessment window: {rel:.1f} % ({sig.note})."
                if rel is not None
                else "The gap in the assessment window could not be computed."
            ),
        )
    )

    # --- soiling evidence
    ev = diagnostics.soiling_evidence
    if not ev.available:
        soiling_detail = "No quantified soiling measurement is available."
    else:
        soiling_detail = (
            f"Soiling loss {ev.loss_pct:.1f} % from {ev.reference} "
            f"[{ev.tag.label if ev.tag else 'UNKNOWN'}], last reading {ev.observed_on} "
            f"({ev.age_days} day(s) before the period end)."
        )
        if ev.notes:
            soiling_detail += " " + " ".join(ev.notes)
    gates.append(
        Gate(id=GateId.SOILING_EVIDENCE_CREDIBLE, label="Credible measured soiling evidence",
             passed=ev.credible, detail=soiling_detail)
    )
    if ev.consistent_with_gap is None:
        consistency_detail = "Consistency between the soiling measurement and the production gap could not be tested."
    else:
        consistency_detail = (
            f"Deviation left for soiling to explain {ev.gap_to_explain_pct:.1f} % vs measured soiling loss "
            f"{ev.loss_pct:.1f} %: difference {ev.gap_minus_soiling_pct:+.1f} % points "
            f"(tolerance {ev.tolerance_pct:.1f})."
        )
    gates.append(
        Gate(id=GateId.SOILING_CONSISTENT_WITH_GAP, label="Soiling measurement consistent with the production gap",
             passed=ev.consistent_with_gap if ev.available else None, detail=consistency_detail)
    )

    # --- technical issues / contradictions
    gates.append(
        Gate(
            id=GateId.NO_UNRESOLVED_TECHNICAL_ISSUE,
            label="No unresolved technical issue",
            passed=not diagnostics.unresolved_technical_issue,
            detail=" ".join(diagnostics.technical_issues) or "No equipment, outage or sensor issue is open in the assessment window.",
        )
    )
    critical = [c for c in diagnostics.conflicts if c.severity == "CRITICAL"]
    gates.append(
        Gate(
            id=GateId.NO_CRITICAL_CONTRADICTION,
            label="No critical contradiction in the evidence",
            passed=not critical,
            detail=" ".join(c.description for c in critical) or "No critical contradiction was found.",
        )
    )

    # --- recoverable energy
    recoverable_ok = (
        recoverable.status is RecoverableStatus.ESTIMATED
        and recoverable.usable_for_decision
        and (recoverable.recoverable.low or 0.0) > 0.0
    )
    gates.append(
        Gate(
            id=GateId.RECOVERABLE_ENERGY_ESTIMATED,
            label="Recoverable energy estimated from measured soiling",
            passed=recoverable_ok,
            detail=(
                f"Recoverable over {recoverable.horizon_days:g} days: "
                f"{(recoverable.recoverable.low or 0) / 1000:,.1f} .. {(recoverable.recoverable.high or 0) / 1000:,.1f} MWh "
                f"(central {(recoverable.recoverable.central or 0) / 1000:,.1f} MWh)."
                if recoverable.status is RecoverableStatus.ESTIMATED and recoverable.horizon_days is not None
                else f"Not estimated ({recoverable.status.value.replace('_', ' ').lower()}): " + " ".join(recoverable.reasons)
            ),
        )
    )

    # --- economics
    gates.append(
        Gate(
            id=GateId.ECONOMICS_DECISION_GRADE,
            label="Economic inputs complete and decision-grade",
            passed=economics.decision_grade,
            detail=(
                "All cost items and a decision-grade energy value were supplied."
                if economics.decision_grade
                else (
                    "Missing: " + "; ".join(economics.missing_inputs) + "."
                    if economics.missing_inputs
                    else (
                        "The energy value is a consumer-tariff proxy, which is not decision-grade."
                        if economics.status is EconomicStatus.COMPLETE
                        else f"{economics.status.value}."
                    )
                )
            ),
        )
    )
    conservative = economics.scenario(ScenarioName.CONSERVATIVE)
    profitable = economics.status is EconomicStatus.COMPLETE and economics.verdict is Verdict.PROFITABLE
    gates.append(
        Gate(
            id=GateId.ECONOMICS_PROFITABLE,
            label="Cleaning profitable in the conservative case",
            passed=profitable if economics.status is EconomicStatus.COMPLETE else None,
            detail=(
                f"Conservative net benefit {conservative.net_benefit:,.0f} {economics.currency} "
                f"({economics.verdict.value})."
                if conservative.net_benefit is not None
                else "Net benefit cannot be stated."
            ),
        )
    )

    # --- decisive evidence and its provenance
    decisive = [
        DecisiveEvidence(label="Actual energy", tag=actual_tag, effective_class=actual_tag.effective_class(ctx)),
        DecisiveEvidence(label="Expected energy (baseline)", tag=baseline.meta.tag, effective_class=baseline_class),
    ]
    if ev.available and ev.tag is not None:
        decisive.append(
            DecisiveEvidence(label="Soiling measurement", tag=ev.tag, effective_class=ev.tag.effective_class(ctx))
        )
    synthetic_present = any(d.tag.is_synthetic for d in decisive)

    # --- data adequacy grade
    exp_u = baseline.meta.uncertainty_pct is not None
    act_meta = inp.channels.get(Metric.ACTUAL_ENERGY)
    act_u = act_meta is not None and act_meta.uncertainty_pct is not None
    checks = [
        QualityCheck(
            label="Uncertainty declared for baseline and metering",
            met=exp_u and act_u,
            detail="Allows the gap to be tested against measurement uncertainty, not only against a threshold.",
        ),
        QualityCheck(
            label="Direct soiling measurement of the measured class",
            met=bool(ev.available and ev.measured_class),
            detail="Without it soiling can only be suspected, never quantified.",
        ),
        QualityCheck(
            label="Equipment data (availability log or device-level energy)",
            met=(Metric.AVAILABILITY in inp.channels) or inp.devices.evaluable,
            detail="Separates equipment losses from losses on the DC side.",
        ),
        QualityCheck(
            label="Sub-daily time resolution",
            met=interval_minutes != DAILY_MINUTES,
            detail="Needed to see shading and curtailment in the shape of the day.",
        ),
        QualityCheck(
            label="No critical contradiction",
            met=not critical,
            detail="Contradicting sources lower the trust in every one of them.",
        ),
    ]
    met = sum(1 for c in checks if c.met)
    if not reliable or not baseline_ok:
        quality = EvidenceQuality.INSUFFICIENT
    elif met >= 4 and not critical:
        quality = EvidenceQuality.HIGH
    elif met >= 2:
        quality = EvidenceQuality.MEDIUM
    else:
        quality = EvidenceQuality.LOW
    _ = th  # thresholds are part of the inputs for traceability; gates above use stage outputs

    return EvidenceAssessment(
        gates=gates,
        decisive_evidence=decisive,
        synthetic_evidence_present=synthetic_present,
        quality=quality,
        quality_checks=checks,
        reasons_production_unreliable=reasons,
    )
