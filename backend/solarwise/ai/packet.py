"""The evidence packet: the only material a language model is given."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

from solarwise.core.pipeline import AnalysisResult

_NUMBER = re.compile(r"(?<![A-Za-z_])\d[\d,]*(?:\.\d+)?")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_USER_TEXT = 300


def clean_text(value: str, limit: int = MAX_USER_TEXT) -> str:
    """User-supplied text is data: control characters removed, length bounded."""
    return _CONTROL.sub(" ", value).strip()[:limit]


def numbers_in(text: str) -> list[float]:
    values: list[float] = []
    for match in _NUMBER.findall(text):
        try:
            values.append(float(match.replace(",", "")))
        except ValueError:  # pragma: no cover - the pattern only matches numbers
            continue
    return values


class EvidencePacket(BaseModel):
    """Engine output restated as plain data, plus every number that may be quoted."""

    decision: str
    decision_label: str
    simulated: bool
    operational_authorization: bool
    content: dict[str, Any]
    allowed_numbers: list[float]


_LABELS = {"CLEAN_NOW": "Clean now", "INVESTIGATE": "Investigate", "MONITOR": "Monitor"}


def _collect(value: Any, numbers: set[float]) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, int | float):
        number = float(value)
        numbers.add(number)
        if abs(number) >= 1000:  # energy in kWh may be quoted in MWh or GWh
            numbers.add(number / 1_000.0)
            numbers.add(number / 1_000_000.0)
        return
    if isinstance(value, str):
        numbers.update(numbers_in(value))
        return
    if isinstance(value, dict):
        for item in value.values():
            _collect(item, numbers)
        return
    if isinstance(value, list | tuple):
        for item in value:
            _collect(item, numbers)


def build_packet(result: AnalysisResult) -> EvidencePacket:
    rec = result.recommendation
    eco = result.economics
    recov = result.recoverable
    content: dict[str, Any] = {
        "plant": clean_text(result.plant.name),
        "period": {
            "start": result.period_start.isoformat(), "end": result.period_end.isoformat(),
            "days": (result.period_end - result.period_start).days + 1,
        },
        "assessment_window": {
            "start": result.gap.window.start.isoformat(), "end": result.gap.window.end.isoformat(),
            "days": (result.gap.window.end - result.gap.window.start).days + 1,
        },
        "decision": {
            "value": rec.decision.value,
            "label": _LABELS[rec.decision.value],
            "rule": rec.rule,
            "simulated": rec.simulated,
            "reasons": list(rec.reasons),
            "next_actions": list(rec.next_actions),
            "would_change_decision": list(rec.would_change_decision),
        },
        "gap": {
            "period_pct": result.gap.result.relative_gap_pct,
            "window_pct": result.gap.window.result.relative_gap_pct,
            "expected_kwh": result.gap.result.expected_kwh,
            "actual_kwh": result.gap.result.actual_kwh,
            "significance": result.gap.window.significance.note,
        },
        "gates": [{"gate": g.label, "passed": g.passed, "basis": g.detail} for g in rec.gates],
        "diagnosis": {
            "status": result.diagnostics.status.value,
            "headline": result.diagnostics.headline,
            "unexplained_residual_pct": result.diagnostics.unexplained_residual_pct,
            "hypotheses": [
                {"name": h.title, "support": h.support.value, "summary": h.summary} for h in result.diagnostics.hypotheses
            ],
            "conflicts": [c.description for c in result.diagnostics.conflicts],
        },
        "recoverable_energy": {
            "status": recov.status.value,
            "soiling_loss_pct": recov.soiling_loss_pct,
            "low_kwh": recov.recoverable.low,
            "base_kwh": recov.recoverable.central,
            "high_kwh": recov.recoverable.high,
            "horizon_days": recov.horizon_days,
            "reasons": list(recov.reasons),
        },
        "economics": {
            "status": eco.status.value,
            "verdict": eco.verdict.value,
            "currency": eco.currency,
            "decision_grade": eco.decision_grade,
            "total_cost": eco.cost.total,
            "break_even_energy_kwh": eco.break_even_energy_kwh,
            "scenarios": [
                {"name": s.name.value, "net_benefit": s.net_benefit, "roi_pct": s.roi_pct} for s in eco.scenarios
            ],
            "missing_inputs": list(eco.missing_inputs),
        },
        "data": {
            "adequacy": result.evidence.quality.value,
            "quality": result.quality.status.value,
            "provenance": [f"{p.label}: {p.provenance}" for p in result.provenance],
            "provenance_statement": result.explanation.provenance_statement,
        },
        "engine_summary": result.explanation.summary,
        "disclaimers": list(result.disclaimers),
    }
    numbers: set[float] = set()
    _collect(content, numbers)
    return EvidencePacket(
        decision=rec.decision.value,
        decision_label=_LABELS[rec.decision.value],
        simulated=rec.simulated,
        operational_authorization=rec.operational_authorization,
        content=content,
        allowed_numbers=sorted(numbers),
    )


# --------------------------------------------------------------------------- the analyst's packet

#: Diagnostic categories shown to the reader, and the engine finding each one restates.
CAUSE_ORDER = ("SOILING", "THERMAL", "IRRADIANCE", "EQUIPMENT", "SHADING", "CURTAILMENT_OR_OUTAGE", "DATA_QUALITY", "UNEXPLAINED")
_CAUSE_OF_HYPOTHESIS = {
    "SOILING": "SOILING", "TEMPERATURE": "THERMAL", "INVERTER": "EQUIPMENT", "SHADING": "SHADING",
    "CURTAILMENT_DOWNTIME": "CURTAILMENT_OR_OUTAGE", "INSUFFICIENT_DATA": "DATA_QUALITY", "UNCLASSIFIED": "UNEXPLAINED",
}
_CAUSE_TITLES = {
    "SOILING": "Soiling", "THERMAL": "Thermal effects", "IRRADIANCE": "Irradiance", "EQUIPMENT": "Equipment or inverter",
    "SHADING": "Shading", "CURTAILMENT_OR_OUTAGE": "Curtailment or outage", "DATA_QUALITY": "Data quality",
    "UNEXPLAINED": "Unexplained remainder",
}
MAX_ITEMS = 8


class CauseFacts(BaseModel):
    """What the engine established about one possible explanation.  Copied, never generated."""

    category: str
    title: str
    #: The engine's rating: a support level, or - for irradiance - the status of the attribution factor.
    engine_support: str
    engine_summary: str
    evidence_for: list[str] = []
    evidence_against: list[str] = []
    context: list[str] = []
    missing_evidence: list[str] = []
    estimated_loss_kwh: float | None = None
    share_of_gap_pct: float | None = None
    #: The condition is present in the assessment window.
    active_now: bool = False


class Candidate(BaseModel):
    """A step or a missing input the engine itself named.  A language model may choose among these, not add to them."""

    id: str
    text: str


class AnalystPacket(BaseModel):
    """Everything the analyst layer is given, and everything it is allowed to quote."""

    decision: str
    decision_label: str
    simulated: bool
    operational_authorization: bool
    #: Credible *measured* soiling evidence exists (the engine's gate).  Without it soiling may not be asserted.
    soiling_confirmed: bool
    #: The engine produced a recoverable-energy estimate.  Without it none may be stated.
    recoverable_estimated: bool
    #: Some decisive data are synthetic: they may never be called measurements.
    synthetic: bool
    content: dict[str, Any]
    allowed_numbers: list[float]
    causes: list[CauseFacts]
    #: What the engine itself reports as an anomaly, in its own sentences.  A narrative may word them differently; it
    #: may not pass them over.
    anomalies: list[str]
    next_steps: list[Candidate]
    missing_information: list[Candidate]
    what_would_change: list[str]


def _unique(items: list[str], limit: int = 40) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = " ".join(item.split())
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out[:limit]


def engine_anomalies(result: AnalysisResult, causes: list[CauseFacts]) -> list[str]:
    """The anomalies the engine found, each in a sentence of its own: open technical issues, an abrupt drop of the
    performance index, critical contradictions in the evidence, a material unexplained remainder, and every cause it
    rates as supported and present in the assessment window."""
    diag = result.diagnostics
    anomalies: list[str] = list(diag.technical_issues)
    step = result.trend.step
    if step is not None and step.material:
        anomalies.append(
            f"The performance index dropped abruptly by {step.drop_pct:.1f} % points around {step.day.isoformat()}."
        )
    anomalies += [c.description for c in diag.conflicts if c.severity == "CRITICAL"]
    if diag.unexplained_residual_material and diag.unexplained_residual_pct is not None:
        anomalies.append(
            f"{diag.unexplained_residual_pct:.1f} % of the expected energy in the assessment window is not explained "
            "by any quantified factor."
        )
    anomalies += [
        f"{cause.title}: {cause.engine_summary}" for cause in causes
        if cause.active_now and cause.category not in ("UNEXPLAINED", "DATA_QUALITY")
        and cause.engine_support in ("STRONG", "MODERATE")
    ]
    return _unique(anomalies, limit=10)


def cause_facts(result: AnalysisResult) -> list[CauseFacts]:
    causes: dict[str, CauseFacts] = {}
    for h in result.diagnostics.hypotheses:
        category = _CAUSE_OF_HYPOTHESIS[h.category.value]

        def statements(direction: str, hypothesis: Any = h) -> list[str]:
            return [
                f"{e.statement} [{e.tag.label}; counts as {e.effective_class.value}]"
                for e in hypothesis.evidence if e.direction.value == direction
            ][:MAX_ITEMS]

        causes[category] = CauseFacts(
            category=category, title=_CAUSE_TITLES[category], engine_support=h.support.value,
            engine_summary=h.summary + (f" {h.uncertainty_note}" if h.uncertainty_note else ""),
            evidence_for=statements("SUPPORTS"), evidence_against=statements("CONTRADICTS"), context=statements("CONTEXT"),
            missing_evidence=list(h.missing_evidence[:MAX_ITEMS]),
            estimated_loss_kwh=h.estimated_loss.value if h.estimated_loss is not None else None,
            share_of_gap_pct=h.estimated_loss_share_of_gap_pct, active_now=h.active_in_window,
        )
    for factor in result.attribution.period.contributions:
        if factor.factor.value == "IRRADIANCE":
            causes["IRRADIANCE"] = CauseFacts(
                category="IRRADIANCE", title=_CAUSE_TITLES["IRRADIANCE"], engine_support=factor.status.value,
                engine_summary=factor.explanation, missing_evidence=list(factor.missing_inputs[:MAX_ITEMS]),
                estimated_loss_kwh=factor.energy.value, share_of_gap_pct=None,
            )
    return [causes[key] for key in CAUSE_ORDER if key in causes]


def build_analyst_packet(result: AnalysisResult) -> AnalystPacket:
    """The engine's findings as plain data for the analyst layer, with the list of every number it may quote."""
    base = build_packet(result)
    rec = result.recommendation
    eco = result.economics
    recov = result.recoverable
    diag = result.diagnostics
    soiling = diag.soiling_evidence
    gap = result.gap
    causes = cause_facts(result)

    steps = _unique([
        *rec.next_actions,
        *(step for h in diag.hypotheses if h.support.value in ("STRONG", "MODERATE") or h.active_in_window
          for step in h.recommended_investigation),
    ])
    missing = _unique([
        *(m for h in diag.hypotheses for m in h.missing_evidence if not m.startswith("[")),
        *(f"Economic input: {m}" for m in eco.missing_inputs),
        *(m for f in result.attribution.period.contributions for m in f.missing_inputs),
    ])
    next_steps = [Candidate(id=f"N{i}", text=text) for i, text in enumerate(steps, start=1)]
    missing_information = [Candidate(id=f"M{i}", text=text) for i, text in enumerate(missing, start=1)]

    anomalies = engine_anomalies(result, causes)

    synthetic = result.evidence.synthetic_evidence_present or any("SYNTHETIC" in p.provenance for p in result.provenance)
    gates = [{"id": g.id.value, "gate": g.label, "passed": g.passed, "basis": g.detail} for g in rec.gates]
    quality_issues = [*result.quality.issues, *result.quality.import_issues]
    content: dict[str, Any] = {
        **base.content,
        "plant_capacity_dc_kwp": result.plant.capacity_dc_kwp,
        "interval": "daily" if result.interval_minutes == 1440 else f"{result.interval_minutes} minutes",
        "evaluation": {
            "context": result.context.value, "simulated": rec.simulated, "synthetic_data": synthetic,
            "operational_authorization": rec.operational_authorization, "authorization_note": rec.authorization_note,
        },
        "decision": {**base.content["decision"], "headline": rec.headline, "reason_code": rec.reason_code.value},
        "gates": gates,
        "gates_summary": {
            "total": len(gates), "passed": sum(1 for g in rec.gates if g.passed),
            "not_passed": sum(1 for g in rec.gates if g.passed is False),
            "not_evaluable": sum(1 for g in rec.gates if g.passed is None),
        },
        "performance": {
            "expected_kwh": gap.result.expected_kwh, "actual_kwh": gap.result.actual_kwh, "gap_kwh": gap.result.gap_kwh,
            "gap_pct": gap.result.relative_gap_pct, "window_gap_pct": gap.window.result.relative_gap_pct,
            "window_significant": gap.window.significance.significant, "significance": gap.window.significance.note,
            "data_completeness_pct": None if gap.coverage.fraction is None else round(gap.coverage.fraction * 100.0, 1),
            "days_total": gap.coverage.days_total, "days_complete": gap.coverage.days_complete,
            "expected_provenance": gap.expected.tag.label, "actual_provenance": gap.actual.tag.label,
            "limitations": list(gap.limitations),
        },
        "attribution": [
            {"factor": f.factor.value, "status": f.status.value, "energy_kwh": f.energy.value,
             "share_of_expected_pct": f.share_of_expected_pct, "basis": f.explanation}
            for f in result.attribution.period.contributions
        ],
        "unexplained_residual": {
            "period_kwh": result.attribution.period.residual_kwh, "period_pct": result.attribution.period.residual_pct,
            "window_pct": diag.unexplained_residual_pct, "material": diag.unexplained_residual_material,
        },
        "trend": (
            {
                "dry_spell_days": result.trend.spell_days, "slope_pct_per_day": result.trend.slope_pct_per_day,
                "declining": result.trend.declining,
                "abrupt_drop": None if result.trend.step is None else {
                    "day": result.trend.step.day.isoformat(), "drop_pct_points": result.trend.step.drop_pct,
                    "material": result.trend.step.material,
                },
                "resets": [{"day": e.day.isoformat(), "kind": e.kind} for e in result.trend.reset_events[:MAX_ITEMS]],
            }
            if result.trend.evaluable else {"evaluable": False, "reason": result.trend.reason}
        ),
        "causes": [c.model_dump(mode="json") for c in causes],
        "conflicts": [{"severity": c.severity, "description": c.description, "resolution": c.resolution} for c in diag.conflicts],
        "technical_issues": list(diag.technical_issues),
        "anomalies": anomalies,
        "soiling_measurement": {
            "available": soiling.available, "method": soiling.method.value if soiling.method is not None else None,
            "counts_as": soiling.effective_class.value if soiling.effective_class is not None else None,
            "credible": soiling.credible, "loss_pct": soiling.loss_pct, "age_days": soiling.age_days,
            "consistent_with_gap": soiling.consistent_with_gap, "notes": list(soiling.notes[:MAX_ITEMS]),
        },
        "recoverable_energy": {**base.content["recoverable_energy"], "usable_for_decision": recov.usable_for_decision},
        "economics": {**base.content["economics"], "warnings": list(eco.warnings[:MAX_ITEMS])},
        "data": {
            **base.content["data"],
            "quality_summary": result.quality.summary,
            "issues": [
                {"code": i.code, "severity": i.severity.value, "message": i.message, "count": i.count}
                for i in quality_issues[:12]
            ],
            "channels": [
                {"channel": p.label, "declared": p.provenance, "counts_as": p.effective_class, "source": clean_text(p.source)}
                for p in result.provenance
            ],
        },
        "thresholds": result.thresholds.model_dump(mode="json"),
        "candidates": {
            "next_steps": [c.model_dump() for c in next_steps],
            "missing_information": [c.model_dump() for c in missing_information],
            "what_would_change": list(rec.would_change_decision),
        },
    }
    numbers: set[float] = set()
    _collect(content, numbers)
    return AnalystPacket(
        decision=base.decision, decision_label=base.decision_label, simulated=base.simulated,
        operational_authorization=base.operational_authorization,
        soiling_confirmed=bool(soiling.credible and soiling.measured_class),
        recoverable_estimated=recov.status.value == "ESTIMATED",
        synthetic=synthetic, content=content, allowed_numbers=sorted(numbers), causes=causes, anomalies=anomalies,
        next_steps=next_steps, missing_information=missing_information,
        what_would_change=list(rec.would_change_decision),
    )
