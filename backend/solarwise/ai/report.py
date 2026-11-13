"""The operational report: the insight of an analysis as a document.

Eight sections, in the order an operator reads them.  Each section says who
wrote it: the narrative (a language model, or the engine's own sentences) or the
engine.  The decision box, the gates and the annex tables are always the
engine's.  The document is rendered by the same HTML and PDF renderers as the
analysis report.
"""

from __future__ import annotations

import json

from solarwise.ai.analyst import Insight, InsightCause, InsightItem
from solarwise.core.pipeline import AnalysisResult
from solarwise.reports.document import ReportDocument, ReportMeta, TextBlock, build_document, fmt_energy, fmt_pct

#: Tables of the analysis report that go into the annex of the operational report.
_ANNEX_TABLES = (
    "Decision gates", "Loss attribution over the period", "Recoverable energy", "Assumptions used",
    "Provenance of the data", "Data quality",
)
_SUPPORT = {
    "STRONG": "strong support", "MODERATE": "moderate support", "WEAK": "weak support", "NOT_SUPPORTED": "not supported",
    "NOT_EVALUABLE": "cannot be evaluated", "QUANTIFIED": "quantified", "PARTIALLY_QUANTIFIED": "partially quantified",
    "ACCOUNTED_IN_BASELINE": "already in the baseline", "NOT_QUANTIFIED": "not quantified", "NOT_APPLICABLE": "not applicable",
}
ENGINE = "engine"


def narrative_source(insight: Insight) -> str:
    """Who wrote the narrative, in a few words."""
    if insight.generated_by == "AI":
        return f"language model {insight.model or insight.provider or ''}".strip()
    return "engine text, no language model"


def _cause_block(cause: InsightCause, narrative: str) -> TextBlock:
    paragraphs = [f"Engine: {cause.engine_summary}"]
    if cause.interpretation:
        paragraphs.append(f"Interpretation ({narrative}): {cause.interpretation}")
    if cause.estimated_loss_kwh is not None and cause.estimated_loss_kwh > 0:
        share = f", {fmt_pct(cause.share_of_gap_pct)} of the gap" if cause.share_of_gap_pct is not None else ""
        paragraphs.append(f"Engine estimate of the loss over the period: {fmt_energy(cause.estimated_loss_kwh)}{share}.")
    bullets = [f"Supports: {e}" for e in cause.evidence_for]
    bullets += [f"Contradicts: {e}" for e in cause.evidence_against]
    bullets += [f"Context: {e}" for e in cause.context]
    bullets += [f"Missing evidence: {m}" for m in cause.missing_evidence]
    support = _SUPPORT.get(cause.engine_support, cause.engine_support.replace("_", " ").lower())
    present = " - present in the assessment window" if cause.active_now else ""
    return TextBlock(f"{cause.title} - {support}{present}", paragraphs, bullets)


def _items(items: list[InsightItem]) -> list[str]:
    return [f"{item.text} Why: {item.why}" if item.why else item.text for item in items]


def build_operational_report(result: AnalysisResult, insight: Insight, meta: ReportMeta) -> ReportDocument:
    """The operational report of one analysis, from its insight."""
    base = build_document(result, meta)
    narrative = narrative_source(insight)
    by_ai = insight.generated_by == "AI"
    passed = [g for g in insight.gates if g.passed]
    failed = [g for g in insight.gates if g.passed is False]
    unknown = [g for g in insight.gates if g.passed is None]

    if by_ai:
        notice = (
            f"How this report was written. The narrative sections were written by a language model "
            f"({insight.provider}, model {insight.model}) on {insight.generated_at:%Y-%m-%d %H:%M} UTC from the findings "
            f"of the deterministic engine, and passed {sum(1 for c in insight.checks if c.passed)} checks against "
            "those findings before being shown. The decision, the gates, the support given to each cause, the evidence, "
            "the steps and every figure are the engine's: the model could not change them."
        )
    else:
        notice = (
            "How this report was written. No language model was used: every section was assembled by the "
            "deterministic engine from its own findings."
            + (f" A language model was asked, but its answer could not be used: {insight.fallback_reason}"
               if insight.fallback_reason else "")
        )

    gate_block = TextBlock(
        "Gates behind the decision",
        [f"{len(passed)} of {len(insight.gates)} gates are passed. Clean now requires every gate."],
        [f"Passed: {g.label}. {g.basis}" for g in passed]
        + [f"NOT passed: {g.label}. {g.basis}" for g in failed]
        + [f"Not evaluable: {g.label}. {g.basis}" for g in unknown],
        label=ENGINE,
    )
    blocks = [
        TextBlock("1. Executive summary", [insight.decision.statement, insight.executive_summary], label=narrative),
        TextBlock("2. Plant performance overview", [insight.performance_overview], label=narrative),
        TextBlock(
            "3. Main detected anomalies",
            [] if insight.anomalies else ["The findings contain no anomaly."], list(insight.anomalies), label=narrative,
        ),
        TextBlock(
            "4. Evidence-based diagnostic analysis",
            ["Each possible explanation carries the support the engine gave it, from the evidence listed. No "
             "probability is stated: the data do not support one. A production gap alone is never taken as soiling."],
            label=f"support and evidence: {ENGINE}; interpretation: {narrative}" if by_ai else ENGINE,
            children=[_cause_block(cause, narrative) for cause in insight.causes],
        ),
        TextBlock(
            "5. Data-quality assessment",
            [f"Engine status: {insight.data_quality_status.lower()}.", insight.data_quality_assessment], label=narrative,
        ),
        TextBlock(
            "6. Economic implications",
            [
                f"Engine status: {insight.economics_status.replace('_', ' ').lower()}; "
                + ("the inputs are decision grade." if insight.economics_decision_grade
                   else "the inputs are not decision grade: no cleaning decision can rest on them."),
                insight.economic_implications,
            ],
            label=narrative,
        ),
        TextBlock(
            "7. Recommended actions",
            [insight.decision_rationale],
            label=f"steps: {ENGINE}; reasons: {narrative}" if by_ai else ENGINE,
            children=[
                gate_block,
                TextBlock("Next steps, in order", [] if insight.next_steps else ["The engine proposes no step."],
                          _items(insight.next_steps)),
                TextBlock("What would change the decision", [], list(insight.what_would_change), label=ENGINE),
                TextBlock("Information that is missing",
                          [] if insight.missing_information else ["The engine lists no missing input."],
                          _items(insight.missing_information)),
            ],
        ),
        TextBlock(
            "8. Limitations and uncertainty", [], [*insight.uncertainty, *insight.limitations], label=narrative,
        ),
    ]
    facts = [
        *base.facts,
        ("Narrative written by", narrative if not by_ai else f"{narrative} ({insight.provider}), checked against the engine's findings"),
        ("Narrative written on", f"{insight.generated_at:%Y-%m-%d %H:%M} UTC"),
        ("Evidence packet (SHA-256)", insight.packet_sha256),
    ]
    return ReportDocument(
        title="SolarWise DZ - operational report",
        subtitle=base.subtitle,
        simulated=base.simulated,
        banner=base.banner,
        decision=base.decision,
        decision_label=base.decision_label,
        headline=base.headline,
        authorization_note=base.authorization_note,
        facts=facts,
        key_figures=base.key_figures,
        blocks=blocks,
        tables=[t for t in base.tables if t.title in _ANNEX_TABLES or t.title.startswith("Economics of one cleaning")],
        hypotheses=[],
        explanation=[],
        disclaimers=base.disclaimers,
        footer=(
            f"Decision, gates, figures and annex tables: SolarWise DZ deterministic engine {result.engine_version} "
            f"(rule {result.recommendation.rule}). Narrative: {narrative}. The report is decision support for qualified "
            "staff; it does not replace an on-site assessment."
        ),
        notice=notice,
        tables_title="Annex - the engine's figures",
    )


def render_operational_json(result: AnalysisResult, insight: Insight, meta: ReportMeta) -> str:
    rec = result.recommendation
    envelope = {
        "report": {
            "format": "solarwise-operational-report",
            "format_version": 1,
            "analysis_id": meta.analysis_id,
            "dataset_name": meta.dataset_name or result.dataset_name,
            "dataset_sha256": meta.dataset_sha256,
            "analysis_issued_at": meta.created_at.isoformat(),
            "simulated": rec.simulated,
            "operational_authorization": rec.operational_authorization,
            "marking": "SIMULATED DECISION - not an operational instruction" if rec.simulated else None,
            "narrative": {
                "written_by": insight.generated_by, "provider": insight.provider, "model": insight.model,
                "written_at": insight.generated_at.isoformat(), "prompt_version": insight.prompt_version,
                "evidence_packet_sha256": insight.packet_sha256,
            },
            "disclaimers": result.disclaimers,
        },
        "insight": insight.model_dump(mode="json"),
    }
    return json.dumps(envelope, indent=2, ensure_ascii=False, allow_nan=False)
