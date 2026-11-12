"""Deterministic explanation of a recommendation.

Every sentence is assembled from values computed by the engines; nothing is
generated freely.  The optional AI layer may rephrase this explanation for a
given audience, but the decision, the figures and the provenance statements
always come from here.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from solarwise.core.attribution import FactorStatus, LossAttribution
from solarwise.core.baseline import BaselineResult
from solarwise.core.decision import Decision, Recommendation
from solarwise.core.diagnostics import DiagnosticCategory, DiagnosticReport, SupportLevel
from solarwise.core.economics import EconomicsResult, EconomicStatus, ScenarioName
from solarwise.core.evidence import EvidenceAssessment
from solarwise.core.gap import GapSeries, GapStatus
from solarwise.core.provenance import EvaluationContext
from solarwise.core.recoverable import RecoverableEnergy, RecoverableStatus


class ExplanationSection(BaseModel):
    key: str
    title: str
    paragraphs: list[str] = Field(default_factory=list)
    bullets: list[str] = Field(default_factory=list)


class Explanation(BaseModel):
    title: str
    summary: str
    sections: list[ExplanationSection]
    provenance_statement: str
    generated_by: str = "DETERMINISTIC_ENGINE"


def _mwh(kwh: float | None) -> str:
    return "n/a" if kwh is None else f"{kwh / 1000.0:,.1f} MWh"


def _pct(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value:.{digits}f} %"


def _money(value: float | None, currency: str) -> str:
    return "n/a" if value is None else f"{value:,.0f} {currency}"


_SUPPORT_TEXT = {
    SupportLevel.STRONG: "strong support",
    SupportLevel.MODERATE: "moderate support",
    SupportLevel.WEAK: "weak support",
    SupportLevel.NOT_SUPPORTED: "not supported",
    SupportLevel.NOT_EVALUABLE: "cannot be evaluated",
}

_DECISION_TEXT = {
    Decision.CLEAN_NOW: "CLEAN NOW",
    Decision.MONITOR: "MONITOR",
    Decision.INVESTIGATE: "INVESTIGATE",
}


def build_explanation(
    *,
    plant_name: str,
    gap: GapSeries,
    baseline: BaselineResult,
    attribution: LossAttribution,
    diagnostics: DiagnosticReport,
    assessment: EvidenceAssessment,
    recoverable: RecoverableEnergy,
    economics: EconomicsResult,
    recommendation: Recommendation,
) -> Explanation:
    """Assemble the plain-language explanation of ``recommendation``."""
    sections: list[ExplanationSection] = []
    window = gap.window

    # ---------------------------------------------------------------- what the data show
    data = ExplanationSection(key="observation", title="What the data show")
    if gap.result.status is GapStatus.OK:
        data.paragraphs.append(
            f"Between {gap.period_start} and {gap.period_end} the plant delivered {_mwh(gap.result.actual_kwh)} "
            f"against an expected {_mwh(gap.result.expected_kwh)}: a gap of {_mwh(gap.result.gap_kwh)} "
            f"({_pct(gap.result.relative_gap_pct)}). The comparison covers "
            f"{_pct((gap.coverage.fraction or 0) * 100, 0)} of daylight intervals; intervals without both values "
            "are left out, not filled."
        )
        if window.result.status is GapStatus.OK:
            data.paragraphs.append(
                f"In the assessment window ({window.start} to {window.end}), which describes the present state "
                f"of the plant, the gap is {_pct(window.result.relative_gap_pct)}. {window.significance.note[:1].upper()}"
                f"{window.significance.note[1:]}."
            )
    else:
        data.paragraphs.append(gap.result.message or "The performance gap could not be computed.")
    data.paragraphs.append(
        f"Actual energy is {gap.actual.tag.label} ({gap.actual.tag.source}). Expected energy is "
        f"{gap.expected.tag.label} ({baseline.method.value.replace('_', ' ').lower()}; {gap.expected.tag.source})."
    )
    data.bullets.extend(gap.limitations)
    sections.append(data)

    # ---------------------------------------------------------------- what explains it
    causes = ExplanationSection(key="diagnosis", title="What may explain it")
    causes.paragraphs.append(diagnostics.headline)
    for h in diagnostics.hypotheses:
        if h.category is DiagnosticCategory.INSUFFICIENT_DATA:
            continue
        line = f"{h.title}: {_SUPPORT_TEXT[h.support]}. {h.summary}"
        if h.estimated_loss is not None and h.estimated_loss.value is not None:
            line += f" Estimated loss {_mwh(h.estimated_loss.value)} [{h.estimated_loss.tag.label}]."
        causes.bullets.append(line)
    unquantified = [
        c.factor.value.replace("_", " ").lower()
        for c in attribution.period.contributions
        if c.status is FactorStatus.NOT_QUANTIFIED
    ]
    if unquantified:
        causes.paragraphs.append(
            "Not quantified for lack of inputs (any effect stays inside the unexplained residual): "
            + ", ".join(unquantified) + "."
        )
    for conflict in diagnostics.conflicts:
        causes.bullets.append(f"Conflict ({conflict.severity.lower()}): {conflict.description}")
    sections.append(causes)

    # ---------------------------------------------------------------- recoverable energy and economics
    money = ExplanationSection(key="economics", title="Recoverable energy and economics")
    if recoverable.status is RecoverableStatus.ESTIMATED:
        soiling_tag = diagnostics.soiling_evidence.tag
        money.paragraphs.append(
            f"Soiling loss from the soiling measurement [{soiling_tag.label if soiling_tag else 'UNKNOWN'}]: "
            f"{_pct(recoverable.soiling_loss_pct)} "
            f"({_pct(recoverable.soiling_loss_low_pct)} to {_pct(recoverable.soiling_loss_high_pct)}). "
            f"Over a benefit horizon of {recoverable.horizon_days:g} days a cleaning is projected to recover "
            f"{_mwh(recoverable.recoverable.central)} (range {_mwh(recoverable.recoverable.low)} to "
            f"{_mwh(recoverable.recoverable.high)})."
        )
        money.paragraphs.append(recoverable.uncertainty_statement)
    else:
        money.paragraphs.append(
            f"Recoverable energy: {recoverable.status.value.replace('_', ' ').lower()}. "
            + " ".join(recoverable.reasons)
        )
    if economics.status is EconomicStatus.COMPLETE:
        base = economics.scenario(ScenarioName.BASE)
        conservative = economics.scenario(ScenarioName.CONSERVATIVE)
        optimistic = economics.scenario(ScenarioName.OPTIMISTIC)
        money.paragraphs.append(
            f"Cost of the cleaning: {_money(economics.cost.total, economics.currency)}. Net benefit: "
            f"{_money(conservative.net_benefit, economics.currency)} (conservative), "
            f"{_money(base.net_benefit, economics.currency)} (base), "
            f"{_money(optimistic.net_benefit, economics.currency)} (optimistic). "
            f"Break-even at {_mwh(economics.break_even_energy_kwh)} recovered."
        )
    elif economics.missing_inputs:
        money.paragraphs.append("Economic inputs not supplied: " + "; ".join(economics.missing_inputs) + ".")
    money.bullets.extend(economics.warnings)
    money.bullets.extend(recoverable.warnings)
    sections.append(money)

    # ---------------------------------------------------------------- decision
    decision = ExplanationSection(
        key="decision",
        title=f"Decision: {_DECISION_TEXT[recommendation.decision]} (rule {recommendation.rule})",
    )
    decision.paragraphs.extend(recommendation.reasons)
    decision.bullets.extend(
        f"{'PASS' if g.passed is True else 'FAIL' if g.passed is False else 'NOT EVALUABLE'} - {g.label}: {g.detail}"
        for g in recommendation.gates
    )
    decision.paragraphs.append(recommendation.authorization_note)
    sections.append(decision)

    # ---------------------------------------------------------------- unknowns
    unknown = ExplanationSection(key="unknowns", title="What is not known")
    insufficient = next(h for h in diagnostics.hypotheses if h.category is DiagnosticCategory.INSUFFICIENT_DATA)
    unknown.bullets.extend(insufficient.missing_evidence)
    for h in diagnostics.hypotheses:
        if h.category in (DiagnosticCategory.INSUFFICIENT_DATA, DiagnosticCategory.UNCLASSIFIED):
            continue
        if h.support is not SupportLevel.NOT_EVALUABLE:
            unknown.bullets.extend(f"[{h.category.value}] {m}" for m in h.missing_evidence)
    unknown.bullets = list(dict.fromkeys(unknown.bullets))
    unknown.bullets.extend(baseline.limitations)
    if not unknown.bullets:
        unknown.paragraphs.append("No missing evidence was identified for this analysis.")
    sections.append(unknown)

    # ---------------------------------------------------------------- next steps
    steps = ExplanationSection(key="next_steps", title="Next steps")
    steps.bullets.extend(recommendation.next_actions)
    if recommendation.review_after_days is not None:
        steps.paragraphs.append(f"Repeat the analysis in about {recommendation.review_after_days} days, or sooner if new evidence is recorded.")
    change = ExplanationSection(key="would_change", title="What would change this decision")
    change.bullets.extend(recommendation.would_change_decision)
    sections.extend([steps, change])

    # ---------------------------------------------------------------- provenance
    classes = "; ".join(
        f"{d.label}: {d.tag.label}"
        + (f" (counts as {d.effective_class.value} here)" if d.tag.is_synthetic else "")
        for d in assessment.decisive_evidence
    )
    provenance = f"Evidence used - {classes}."
    if recommendation.context is EvaluationContext.DEMONSTRATION:
        provenance += (
            " This is a demonstration evaluation: synthetic values stand in for the evidence class they emulate "
            "so that the decision logic can be shown. They are not measurements of any real plant, and the "
            "result is not an operational instruction."
        )
    elif assessment.synthetic_evidence_present:
        provenance += " Synthetic values were present; in the operational context they never count as measured evidence."

    summary = (
        f"{plant_name}: {_DECISION_TEXT[recommendation.decision]}. "
        + (recommendation.reasons[0] if recommendation.reasons else "")
    )
    if recommendation.simulated:
        summary = "SIMULATED - " + summary
    return Explanation(
        title=f"{_DECISION_TEXT[recommendation.decision]} - {plant_name}",
        summary=summary,
        sections=sections,
        provenance_statement=provenance,
    )
