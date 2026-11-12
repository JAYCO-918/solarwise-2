"""Format-independent content of a report: every figure already turned into text."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from solarwise.core.attribution import FactorStatus
from solarwise.core.decision import Decision
from solarwise.core.pipeline import AnalysisResult

_DECISION_LABEL = {
    Decision.CLEAN_NOW: "Clean now",
    Decision.INVESTIGATE: "Investigate",
    Decision.MONITOR: "Monitor",
}
_FACTOR_LABEL = {
    "SOILING_ALLOWANCE": "Soiling allowance inside the baseline",
    "IRRADIANCE": "Irradiance",
    "TEMPERATURE": "Temperature",
    "DEGRADATION": "Degradation",
    "DOWNTIME": "Outage (no production)",
    "EQUIPMENT_AVAILABILITY": "Equipment availability",
    "CURTAILMENT": "Curtailment",
    "SOILING": "Soiling (measured)",
}
_STATUS_LABEL = {
    FactorStatus.QUANTIFIED: "Quantified",
    FactorStatus.PARTIALLY_QUANTIFIED: "Partially quantified",
    FactorStatus.ACCOUNTED_IN_BASELINE: "Already in the baseline",
    FactorStatus.NOT_QUANTIFIED: "Not quantified",
    FactorStatus.NOT_APPLICABLE: "Not applicable",
}


def fmt_number(value: float | None, digits: int = 0, unit: str = "") -> str:
    if value is None:
        return "not available"
    text = f"{value:,.{digits}f}"
    return f"{text} {unit}".strip()


def fmt_energy(kwh: float | None) -> str:
    """Energy with a unit suited to its size."""
    if kwh is None:
        return "not available"
    if abs(kwh) >= 1_000_000:
        return f"{kwh / 1_000_000:,.2f} GWh"
    if abs(kwh) >= 1_000:
        return f"{kwh / 1_000:,.1f} MWh"
    return f"{kwh:,.0f} kWh"


def fmt_pct(value: float | None, digits: int = 1) -> str:
    return "not available" if value is None else f"{value:.{digits}f} %"


def fmt_money(value: float | None, currency: str) -> str:
    return "not available" if value is None else f"{value:,.0f} {currency}"


@dataclass
class ReportMeta:
    analysis_id: int | None
    dataset_name: str | None
    dataset_sha256: str | None
    created_at: datetime
    created_by: str | None = None


@dataclass
class Table:
    title: str
    columns: list[str]
    rows: list[list[str]]
    note: str | None = None
    #: Relative column widths for the PDF.
    widths: list[float] | None = None


@dataclass
class TextBlock:
    title: str
    paragraphs: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)


@dataclass
class ReportDocument:
    title: str
    subtitle: str
    simulated: bool
    banner: str
    decision: str
    decision_label: str
    headline: str
    authorization_note: str
    facts: list[tuple[str, str]]
    key_figures: list[tuple[str, str]]
    blocks: list[TextBlock]
    tables: list[Table]
    hypotheses: list[TextBlock]
    explanation: list[TextBlock]
    disclaimers: list[str]
    footer: str


def build_document(result: AnalysisResult, meta: ReportMeta) -> ReportDocument:
    rec = result.recommendation
    eco = result.economics
    recov = result.recoverable
    currency = eco.currency
    simulated = rec.simulated
    banner = (
        "SIMULATED DECISION - demonstration only. This document is not an operational instruction."
        if simulated
        else (
            "Operational recommendation issued by the deterministic engine on measured evidence."
            if rec.operational_authorization
            else "Advisory result. It does not authorise field work."
        )
    )

    facts = [
        ("Plant", result.plant.name),
        ("Installed capacity", f"{result.plant.capacity_dc_kwp:,.0f} kWp DC"),
        ("Dataset", meta.dataset_name or result.dataset_name or "not named"),
        ("Period analysed", f"{result.period_start.isoformat()} to {result.period_end.isoformat()} ({result.timezone})"),
        ("Assessment window", f"{result.gap.window.start.isoformat()} to {result.gap.window.end.isoformat()}"),
        ("Data interval", "daily" if result.interval_minutes == 1440 else f"{result.interval_minutes} minutes"),
        ("Evaluation context", result.context.value),
        ("Engine version", result.engine_version),
        ("Analysis", f"#{meta.analysis_id}" if meta.analysis_id is not None else "not stored"),
        ("Issued", meta.created_at.strftime("%Y-%m-%d %H:%M UTC")),
    ]
    if meta.created_by:
        facts.append(("Requested by", meta.created_by))
    if meta.dataset_sha256:
        facts.append(("Dataset fingerprint (SHA-256)", meta.dataset_sha256))

    gap = result.gap
    key_figures = [
        ("Expected energy (baseline)", f"{fmt_energy(gap.result.expected_kwh)}  [{gap.expected.tag.label}]"),
        ("Actual energy", f"{fmt_energy(gap.result.actual_kwh)}  [{gap.actual.tag.label}]"),
        ("Gap over the period", f"{fmt_energy(gap.result.gap_kwh)} ({fmt_pct(gap.result.relative_gap_pct)})"),
        ("Gap in the assessment window", fmt_pct(gap.window.result.relative_gap_pct)),
        ("Significance", gap.window.significance.note),
        ("Data completeness", fmt_pct((gap.coverage.fraction or 0.0) * 100.0 if gap.coverage.fraction is not None else None)),
        ("Data adequacy", f"{result.evidence.quality.value} - {result.evidence.quality_note}"),
        ("Diagnostic status", result.diagnostics.status.value.replace("_", " ").title()),
    ]

    blocks = [
        TextBlock("Why", bullets=list(rec.reasons)),
        TextBlock("Recommended next steps", bullets=list(rec.next_actions)),
        TextBlock("What would change this decision", bullets=list(rec.would_change_decision)),
    ]
    if result.diagnostics.conflicts:
        blocks.append(
            TextBlock(
                "Contradictions in the evidence",
                bullets=[f"[{c.severity}] {c.description} Resolution: {c.resolution}" for c in result.diagnostics.conflicts],
            )
        )
    if result.diagnostics.technical_issues:
        blocks.append(TextBlock("Open technical issues", bullets=list(result.diagnostics.technical_issues)))

    tables: list[Table] = []
    tables.append(
        Table(
            "Decision gates",
            ["Gate", "Result", "Basis"],
            [[g.label, "passed" if g.passed else ("not evaluable" if g.passed is None else "NOT passed"), g.detail]
             for g in rec.gates],
            note="CLEAN NOW requires every gate to pass. A production gap alone passes none of the soiling gates.",
            widths=[0.24, 0.12, 0.64],
        )
    )
    period = result.attribution.period
    rows = []
    for c in period.contributions:
        rows.append([
            _FACTOR_LABEL.get(c.factor.value, c.factor.value.replace("_", " ").title()),
            _STATUS_LABEL.get(c.status, c.status.value),
            fmt_energy(c.energy.value) if c.energy.value is not None else "-",
            fmt_pct(c.share_of_expected_pct) if c.share_of_expected_pct is not None else "-",
            c.explanation,
        ])
    rows.append(["Unexplained residual", "Remainder", fmt_energy(period.residual_kwh), fmt_pct(period.residual_pct),
                 "Expected energy less every quantified factor less actual energy. Never assigned to soiling by default."])
    tables.append(
        Table("Loss attribution over the period", ["Factor", "Status", "Energy", "Share of expected", "Basis"], rows,
              note="Factors that cannot be quantified from the available inputs stay inside the residual.",
              widths=[0.19, 0.13, 0.11, 0.11, 0.46])
    )

    if recov.recoverable.central is not None or recov.soiling_loss_pct is not None:
        tables.append(
            Table(
                "Recoverable energy",
                ["Quantity", "Value"],
                [
                    ["Status", recov.status.value.replace("_", " ").title()],
                    ["Observed gap in the assessment window", f"{fmt_energy(recov.observed_gap.value)} ({fmt_pct(recov.observed_gap_pct)})"],
                    ["Soiling-related loss in the window", fmt_energy(recov.soiling_related_loss.value)],
                    ["Unexplained loss in the window", fmt_energy(recov.unexplained_loss.value)],
                    ["Measured soiling loss", f"{fmt_pct(recov.soiling_loss_pct)} (range {fmt_pct(recov.soiling_loss_low_pct)} to {fmt_pct(recov.soiling_loss_high_pct)})"],
                    ["Recoverable energy - conservative", fmt_energy(recov.recoverable.low)],
                    ["Recoverable energy - base", fmt_energy(recov.recoverable.central)],
                    ["Recoverable energy - optimistic", fmt_energy(recov.recoverable.high)],
                    ["Benefit horizon", fmt_number(recov.horizon_days, 0, "days")],
                ],
                note=recov.uncertainty_statement or None,
                widths=[0.45, 0.55],
            )
        )
    else:
        blocks.append(TextBlock("Recoverable energy", paragraphs=[
            f"{recov.status.value.replace('_', ' ').title()}. " + " ".join(recov.reasons)
        ]))

    if eco.scenarios and any(s.gross_benefit is not None for s in eco.scenarios):
        tables.append(
            Table(
                f"Economics of one cleaning ({currency})",
                ["Scenario", "Recoverable energy", "Gross benefit", "Cost", "Net benefit", "ROI"],
                [[s.name.value.title(), fmt_energy(s.recoverable_energy_kwh), fmt_money(s.gross_benefit, currency),
                  fmt_money(s.total_cost, currency), fmt_money(s.net_benefit, currency),
                  fmt_pct(s.roi_pct, 0) if s.roi_pct is not None else "-"] for s in eco.scenarios],
                note=(
                    f"Verdict: {eco.verdict.value.title()}. Status: {eco.status.value.replace('_', ' ').title()}. "
                    f"Break-even energy: {fmt_energy(eco.break_even_energy_kwh)}. "
                    + ("Decision grade: yes." if eco.decision_grade else "Decision grade: no - a cleaning decision cannot rest on these economics.")
                ),
                widths=[0.14, 0.18, 0.18, 0.16, 0.2, 0.14],
            )
        )
    else:
        blocks.append(TextBlock("Economics", paragraphs=[
            f"{eco.status.value.replace('_', ' ').title()}. "
            + ("Missing inputs: " + "; ".join(eco.missing_inputs) + "." if eco.missing_inputs else "No net benefit can be stated.")
        ]))
    assumptions = [*recov.assumptions, *eco.assumptions]
    if assumptions:
        tables.append(
            Table(
                "Assumptions used",
                ["Assumption", "Value", "Classification", "Source"],
                [[a.name, fmt_number(a.value, 2 if a.value is not None and abs(a.value) < 100 else 0, a.unit),
                  a.classification.replace("_", " ").title(), a.source] for a in assumptions],
                note="Assumptions are inputs supplied with the request. None of them is a measurement.",
                widths=[0.27, 0.17, 0.18, 0.38],
            )
        )
    if eco.warnings or recov.warnings:
        blocks.append(TextBlock("Warnings on the estimate", bullets=[*recov.warnings, *eco.warnings]))

    tables.append(
        Table(
            "Provenance of the data",
            ["Channel", "Declared provenance", "Counts as", "Source"],
            [[p.label, p.provenance, p.effective_class, p.source or "not declared"] for p in result.provenance],
            note="'Counts as' is the evidence class in this evaluation context. Synthetic data never count as "
                 "measured evidence outside a demonstration.",
            widths=[0.22, 0.22, 0.14, 0.42],
        )
    )
    quality = result.quality
    issues = [*quality.issues, *quality.import_issues]
    tables.append(
        Table(
            "Data quality",
            ["Code", "Severity", "Finding"],
            [[i.code, i.severity.value, i.message] for i in issues] or [["-", "-", "No issue found on the analysed period."]],
            note=f"Overall: {quality.status.value}. {quality.summary} " + " ".join(quality.notes),
            widths=[0.24, 0.1, 0.66],
        )
    )
    tables.append(
        Table(
            "Pipeline stages",
            ["Stage", "State", "Outcome"],
            [[s.title, s.state.value, s.message] for s in result.stages],
            widths=[0.2, 0.1, 0.7],
        )
    )

    hypotheses = []
    for h in result.diagnostics.hypotheses:
        bullets = [
            f"{'Supports' if e.direction.value == 'SUPPORTS' else ('Contradicts' if e.direction.value == 'CONTRADICTS' else 'Context')}: "
            f"{e.statement} [{e.tag.label}; counts as {e.effective_class.value}]"
            for e in h.evidence
        ]
        bullets += [f"Missing evidence: {m}" for m in h.missing_evidence]
        paragraphs = [h.summary, "Rule applied: " + "; ".join(h.rules)]
        if h.estimated_loss is not None and h.estimated_loss.value is not None:
            paragraphs.append(f"Estimated loss over the period: {fmt_energy(h.estimated_loss.value)}.")
        if h.uncertainty_note:
            paragraphs.append(h.uncertainty_note)
        hypotheses.append(
            TextBlock(f"{h.title} - support: {h.support.value.replace('_', ' ').lower()}", paragraphs, bullets)
        )

    explanation = [TextBlock(s.title, list(s.paragraphs), list(s.bullets)) for s in result.explanation.sections]
    explanation.append(TextBlock("Provenance statement", [result.explanation.provenance_statement]))

    return ReportDocument(
        title="SolarWise DZ - performance and cleaning assessment",
        subtitle=result.plant.name,
        simulated=simulated,
        banner=banner,
        decision=rec.decision.value,
        decision_label=_DECISION_LABEL[rec.decision],
        headline=rec.headline,
        authorization_note=rec.authorization_note,
        facts=facts,
        key_figures=key_figures,
        blocks=[b for b in blocks if b.paragraphs or b.bullets],
        tables=tables,
        hypotheses=hypotheses,
        explanation=explanation,
        disclaimers=list(result.disclaimers),
        footer=(
            f"Produced by the SolarWise DZ deterministic engine {result.engine_version} (rule {rec.rule}). "
            "The recommendation is decision support for qualified staff; it does not replace an on-site assessment."
        ),
    )
