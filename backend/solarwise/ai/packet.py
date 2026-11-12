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
