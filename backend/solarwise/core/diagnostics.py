"""Deterministic diagnostics engine.

Seven hypotheses are evaluated side by side.  None of them is "the answer" by
construction: each receives an ordinal *support level* derived from explicit
rules, together with the evidence for and against it, what is missing, and what
to investigate.  Several hypotheses may remain plausible at once, and evidence
may conflict - both situations are reported as such instead of being resolved
by fiat.

Why ordinal levels and not percentages
--------------------------------------
A numeric "confidence" would need a probability model of plant failures that
does not exist here.  Numeric uncertainty is therefore attached only to
*quantities* whose uncertainty follows from declared measurement uncertainty
(for example a soiling loss of 8.9 +/- 2 x 0.5 %).  Hypotheses get levels:

``STRONG``         direct evidence of the measured class, consistent with the data
``MODERATE``       indirect evidence (pattern, document) or direct but incomplete
``WEAK``           compatible with the data, not specifically evidenced
``NOT_SUPPORTED``  the evidence that exists argues against it
``NOT_EVALUABLE``  the evidence needed to judge it is missing
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from solarwise.core.attribution import AttributionScope, Factor, FactorContribution, FactorStatus, LossAttribution
from solarwise.core.baseline import BaselineResult
from solarwise.core.devices import DeviceAnalysis
from solarwise.core.gap import GapDirection, GapSeries, GapStatus
from solarwise.core.intraday import IntradayAnalysis
from solarwise.core.models import (
    DIRECT_SOILING_METHODS,
    AnalysisThresholds,
    ChannelMeta,
    EvidenceRecord,
    EvidenceType,
    InspectionFinding,
    Metric,
    SoilingMethod,
)
from solarwise.core.provenance import (
    UNKNOWN_TAG,
    EvaluationContext,
    Provenance,
    ProvenanceTag,
    Traced,
    derive,
)
from solarwise.core.timeline import local_day
from solarwise.core.trend import TrendAnalysis


class DiagnosticCategory(StrEnum):
    SOILING = "SOILING"
    TEMPERATURE = "TEMPERATURE"
    INVERTER = "INVERTER"
    SHADING = "SHADING"
    CURTAILMENT_DOWNTIME = "CURTAILMENT_DOWNTIME"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    UNCLASSIFIED = "UNCLASSIFIED"


class SupportLevel(StrEnum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    NOT_EVALUABLE = "NOT_EVALUABLE"


class EvidenceDirection(StrEnum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    CONTEXT = "CONTEXT"


class EvidenceItem(BaseModel):
    code: str
    statement: str
    direction: EvidenceDirection
    #: DIRECT_MEASUREMENT | CALCULATED | LOGGED | PATTERN | DOCUMENT | CONTEXT
    kind: str
    tag: ProvenanceTag
    #: Evidence class used for gating in the current evaluation context.
    effective_class: Provenance
    value: float | None = None
    unit: str | None = None


class Hypothesis(BaseModel):
    category: DiagnosticCategory
    title: str
    support: SupportLevel
    summary: str
    #: Identifiers of the rules that determined the support level.
    rules: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    #: Energy attributed to this cause over the analysed period, where calculable.
    estimated_loss: Traced | None = None
    estimated_loss_share_of_gap_pct: float | None = None
    uncertainty_note: str | None = None
    competing_explanations: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    recommended_investigation: list[str] = Field(default_factory=list)
    #: The condition is present in the assessment window (i.e. now).
    active_in_window: bool = False


class Conflict(BaseModel):
    code: str
    severity: str  # CRITICAL | MINOR
    description: str
    involved: list[DiagnosticCategory]
    resolution: str


class DiagnosticStatus(StrEnum):
    NO_SIGNIFICANT_DEVIATION = "NO_SIGNIFICANT_DEVIATION"
    SINGLE_EXPLANATION = "SINGLE_EXPLANATION"
    MULTIPLE_PLAUSIBLE = "MULTIPLE_PLAUSIBLE"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    UNCLASSIFIED = "UNCLASSIFIED"


class SoilingEvidence(BaseModel):
    """The soiling information available *now*, distilled for the decision chain."""

    available: bool = False
    source: str | None = None  # TIME_SERIES | EVIDENCE_RECORD
    reference: str | None = None
    method: SoilingMethod | None = None
    tag: ProvenanceTag | None = None
    effective_class: Provenance | None = None
    soiling_ratio: float | None = None
    loss_pct: float | None = None
    #: Declared standard uncertainty of the loss [% points]; ``None`` if not declared.
    std_uncertainty_pct: float | None = None
    observed_on: date | None = None
    age_days: int | None = None
    readings_in_window: int = 0
    #: A numeric soiling ratio exists.
    quantified: bool = False
    #: Obtained by a direct comparison method and of the measured class.
    measured_class: bool = False
    recent: bool = False
    #: The loss exceeds the credibility floor and k times its uncertainty.
    above_floor: bool = False
    #: quantified, measured class, recent and above the floor.
    credible: bool = False
    #: Pre-soiling gap the measurement should explain [%].
    gap_to_explain_pct: float | None = None
    #: gap_to_explain - measured loss [% points].
    gap_minus_soiling_pct: float | None = None
    tolerance_pct: float | None = None
    consistent_with_gap: bool | None = None
    notes: list[str] = Field(default_factory=list)


class DiagnosticReport(BaseModel):
    status: DiagnosticStatus
    headline: str
    hypotheses: list[Hypothesis]
    leading: list[DiagnosticCategory]
    conflicts: list[Conflict]
    soiling_evidence: SoilingEvidence
    #: An equipment / outage / sensor problem is present in the assessment window.
    unresolved_technical_issue: bool
    technical_issues: list[str]
    #: Unexplained residual in the assessment window [% of pre-soiling expected].
    unexplained_residual_pct: float | None
    unexplained_residual_material: bool | None
    #: Deviation is significant in the assessment window / over the period.
    deviation_now: bool
    deviation_period: bool


@dataclass(frozen=True)
class DiagnosticInputs:
    gap: GapSeries
    attribution: LossAttribution
    trend: TrendAnalysis
    devices: DeviceAnalysis
    intraday: IntradayAnalysis
    baseline: BaselineResult
    channels: Mapping[Metric, ChannelMeta]
    records: Sequence[EvidenceRecord]
    context: EvaluationContext
    thresholds: AnalysisThresholds
    timezone: ZoneInfo


# --------------------------------------------------------------------------- helpers

_SUPPORT_RANK = {
    SupportLevel.STRONG: 4,
    SupportLevel.MODERATE: 3,
    SupportLevel.WEAK: 2,
    SupportLevel.NOT_SUPPORTED: 1,
    SupportLevel.NOT_EVALUABLE: 0,
}

_ONGOING_TYPES = frozenset(
    {EvidenceType.INVERTER_FAULT, EvidenceType.SENSOR_FAULT, EvidenceType.SHADING_OBSERVATION}
)


def _contribution(scope: AttributionScope, factor: Factor) -> FactorContribution | None:
    for c in scope.contributions:
        if c.factor is factor:
            return c
    return None


def _quantified(c: FactorContribution | None) -> bool:
    return c is not None and c.status in (FactorStatus.QUANTIFIED, FactorStatus.PARTIALLY_QUANTIFIED)


def _share(c: FactorContribution | None) -> float:
    if c is None or c.share_of_expected_pct is None:
        return 0.0
    return c.share_of_expected_pct


def _tag(inp: DiagnosticInputs, metric: Metric) -> ProvenanceTag:
    meta = inp.channels.get(metric)
    return meta.tag if meta is not None else UNKNOWN_TAG


def _item(
    inp: DiagnosticInputs,
    code: str,
    statement: str,
    direction: EvidenceDirection,
    kind: str,
    tag: ProvenanceTag,
    value: float | None = None,
    unit: str | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        code=code,
        statement=statement,
        direction=direction,
        kind=kind,
        tag=tag,
        effective_class=tag.effective_class(inp.context),
        value=value,
        unit=unit,
    )


def _record_days(rec: EvidenceRecord, zone: ZoneInfo, period_end: date) -> tuple[date, date]:
    """Local days spanned by a record; open faults are taken to last until the period end."""
    start = local_day(rec.observed_start, zone)
    if rec.observed_end is not None:
        return start, local_day(rec.observed_end, zone)
    if rec.resolved is False or (rec.resolved is None and rec.evidence_type in _ONGOING_TYPES):
        return start, max(start, period_end)
    return start, start


def _records(
    inp: DiagnosticInputs, types: set[EvidenceType], start: date, end: date
) -> list[EvidenceRecord]:
    out = []
    for rec in inp.records:
        if rec.evidence_type not in types:
            continue
        first, last = _record_days(rec, inp.timezone, inp.gap.period_end)
        if first <= end and last >= start:
            out.append(rec)
    return out


def _fmt_pct(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value:.{digits}f} %"


def _fmt_mwh(kwh: float | None) -> str:
    return "n/a" if kwh is None else f"{kwh / 1000.0:,.1f} MWh"


def _share_of_gap(loss_kwh: float | None, gap_kwh: float | None) -> float | None:
    if loss_kwh is None or gap_kwh is None or gap_kwh <= 0:
        return None
    return loss_kwh / gap_kwh * 100.0


# --------------------------------------------------------------------------- soiling evidence


def distill_soiling_evidence(inp: DiagnosticInputs) -> tuple[SoilingEvidence, list[Conflict]]:
    """Find the soiling information that describes the plant *now* and test it against the gap."""
    th = inp.thresholds
    window = inp.attribution.window
    period_end = inp.gap.period_end
    conflicts: list[Conflict] = []
    k = th.coverage_factor

    # --- continuous soiling-ratio channel
    ts: SoilingEvidence | None = None
    meta = inp.channels.get(Metric.SOILING_RATIO)
    days_with_sr = [d for d in inp.attribution.daily if d.soiling_ratio is not None]
    if meta is not None and days_with_sr:
        last = days_with_sr[-1]
        in_window = [d for d in days_with_sr if d.day >= window.start]
        if window.measured_soiling_loss_pct is not None:
            loss = window.measured_soiling_loss_pct
            gap_to_explain = window.pre_soiling_gap_on_soiling_slots_pct
        else:
            assert last.soiling_ratio is not None
            loss = (1.0 - min(last.soiling_ratio, 1.0)) * 100.0
            gap_to_explain = None
        ts = SoilingEvidence(
            available=True,
            source="TIME_SERIES",
            reference="soiling_ratio channel",
            method=meta.soiling_method or SoilingMethod.UNSPECIFIED,
            tag=meta.tag,
            effective_class=meta.tag.effective_class(inp.context),
            soiling_ratio=1.0 - loss / 100.0,
            loss_pct=loss,
            std_uncertainty_pct=(meta.uncertainty_abs * 100.0 if meta.uncertainty_abs is not None else None),
            observed_on=last.day,
            age_days=(period_end - last.day).days,
            readings_in_window=len(in_window),
            quantified=True,
            gap_to_explain_pct=gap_to_explain,
        )

    # --- latest documented spot measurement
    spot: SoilingEvidence | None = None
    candidates = [
        r
        for r in inp.records
        if r.evidence_type is EvidenceType.SOILING_MEASUREMENT
        and r.value is not None
        and local_day(r.observed_start, inp.timezone) <= period_end
    ]
    if candidates:
        rec = max(candidates, key=lambda r: r.observed_start)
        assert rec.value is not None
        day = local_day(rec.observed_start, inp.timezone)
        spot = SoilingEvidence(
            available=True,
            source="EVIDENCE_RECORD",
            reference=rec.reference,
            method=rec.soiling_method or SoilingMethod.UNSPECIFIED,
            tag=rec.tag,
            effective_class=rec.tag.effective_class(inp.context),
            soiling_ratio=min(rec.value, 1.0),
            loss_pct=(1.0 - min(rec.value, 1.0)) * 100.0,
            std_uncertainty_pct=(rec.std_uncertainty * 100.0 if rec.std_uncertainty is not None else None),
            observed_on=day,
            age_days=(period_end - day).days,
            readings_in_window=1 if day >= window.start else 0,
            quantified=True,
            gap_to_explain_pct=window.pre_soiling_gap_pct,
        )

    if ts is None and spot is None:
        return SoilingEvidence(notes=["No quantified soiling ratio is available."]), conflicts

    # Prefer the continuous channel when it has readings in the window, else the most recent source.
    if ts is not None and spot is not None:
        assert ts.age_days is not None and spot.age_days is not None
        primary = ts if (ts.readings_in_window > 0 or ts.age_days <= spot.age_days) else spot
        other = spot if primary is ts else ts
        assert primary.loss_pct is not None and other.loss_pct is not None
        both_recent = (
            ts.age_days <= th.soiling_measurement_max_age_days
            and spot.age_days <= th.soiling_measurement_max_age_days
        )
        if both_recent and abs(primary.loss_pct - other.loss_pct) > th.consistency_tolerance_pct:
            conflicts.append(
                Conflict(
                    code="C-SOILING-SOURCES-DISAGREE",
                    severity="CRITICAL",
                    description=(
                        f"Two recent soiling measurements disagree: the soiling-ratio channel indicates "
                        f"{ts.loss_pct:.1f} % loss, the documented measurement {spot.reference} indicates "
                        f"{spot.loss_pct:.1f} %."
                    ),
                    involved=[DiagnosticCategory.SOILING],
                    resolution="Check the soiling sensor (cleanliness of its reference device, location) and "
                    "repeat the spot measurement on representative strings.",
                )
            )
    else:
        primary = ts if ts is not None else spot  # type: ignore[assignment]
    assert primary is not None and primary.loss_pct is not None and primary.age_days is not None

    notes: list[str] = []
    method_direct = primary.method in DIRECT_SOILING_METHODS
    measured_class = method_direct and primary.effective_class is Provenance.MEASURED
    if not method_direct:
        notes.append(
            f"Soiling figure obtained by '{(primary.method or SoilingMethod.UNSPECIFIED).value}': not a direct "
            "comparison of soiled and clean reference devices."
        )
    if primary.effective_class is not Provenance.MEASURED:
        assert primary.tag is not None
        notes.append(
            f"Soiling figure has provenance {primary.tag.label}; in the {inp.context.value} context it counts "
            f"as {primary.effective_class.value if primary.effective_class else 'UNKNOWN'}, not as measured evidence."
        )
    recent = primary.age_days <= th.soiling_measurement_max_age_days
    if not recent:
        notes.append(
            f"Latest soiling reading is {primary.age_days} day(s) old (limit {th.soiling_measurement_max_age_days})."
        )
    u = primary.std_uncertainty_pct
    above_floor = primary.loss_pct >= th.soiling_credibility_floor_pct and (u is None or primary.loss_pct > k * u)
    if u is None:
        notes.append("No measurement uncertainty was declared for the soiling figure.")
    if not above_floor:
        notes.append(
            f"Measured soiling loss {primary.loss_pct:.1f} % does not exceed the credibility floor "
            f"({th.soiling_credibility_floor_pct:g} %"
            + (f", and {k:g} x uncertainty = {k * u:.1f} %" if u is not None else "")
            + "): it is not distinguishable from a clean array."
        )

    gap_to_explain = primary.gap_to_explain_pct
    diff: float | None = None
    tolerance: float | None = None
    consistent: bool | None = None
    if gap_to_explain is not None:
        tolerance = th.consistency_tolerance_pct
        u_gap = inp.gap.window.significance.combined_std_uncertainty_pct
        if u_gap is not None and u is not None:
            tolerance = max(tolerance, k * math.sqrt(u_gap**2 + u**2))
        diff = gap_to_explain - primary.loss_pct
        consistent = abs(diff) <= tolerance

    evidence = primary.model_copy(
        update={
            "measured_class": measured_class,
            "recent": recent,
            "above_floor": above_floor,
            "credible": bool(measured_class and recent and above_floor),
            "gap_minus_soiling_pct": diff,
            "tolerance_pct": tolerance,
            "consistent_with_gap": consistent,
            "notes": notes,
        }
    )

    # A reading that shows a (near-)clean array next to a large gap is not a contradiction:
    # it simply rules soiling out.  A conflict exists only when a *material* soiling figure
    # fails to match the deviation it is supposed to explain.
    if evidence.credible and consistent is False:
        assert diff is not None and tolerance is not None and gap_to_explain is not None
        if diff > 0:
            conflicts.append(
                Conflict(
                    code="C-SOILING-DOES-NOT-EXPLAIN-GAP",
                    severity="CRITICAL" if diff >= th.gap_materiality_pct else "MINOR",
                    description=(
                        f"Measured soiling loss ({primary.loss_pct:.1f} %) explains only part of the current "
                        f"deviation ({gap_to_explain:.1f} % after the quantified non-soiling factors): "
                        f"{diff:.1f} % points remain unexplained (tolerance {tolerance:.1f})."
                    ),
                    involved=[DiagnosticCategory.SOILING, DiagnosticCategory.UNCLASSIFIED],
                    resolution="Look for a second cause (equipment, shading, curtailment, sensors) before "
                    "attributing the deviation to soiling; verify that the soiling sensor is representative.",
                )
            )
        else:
            conflicts.append(
                Conflict(
                    code="C-SOILING-EXCEEDS-GAP",
                    severity="CRITICAL",
                    description=(
                        f"Measured soiling loss ({primary.loss_pct:.1f} %) is larger than the deviation seen in "
                        f"production ({gap_to_explain:.1f} %) by {-diff:.1f} % points (tolerance {tolerance:.1f}). "
                        "Either the soiling sensor is not representative of the array or the baseline is biased low."
                    ),
                    involved=[DiagnosticCategory.SOILING, DiagnosticCategory.INSUFFICIENT_DATA],
                    resolution="Verify the soiling sensor against a clean-reference test on representative "
                    "strings and review the baseline before acting on the soiling figure.",
                )
            )
    return evidence, conflicts


# --------------------------------------------------------------------------- hypotheses


def _soiling(inp: DiagnosticInputs, ev: SoilingEvidence, pre_gap_material: bool) -> Hypothesis:
    th = inp.thresholds
    trend = inp.trend
    period = inp.attribution.period
    rules: list[str] = []
    items: list[EvidenceItem] = []
    missing: list[str] = []
    investigate: list[str] = []

    # direct measurement
    if ev.available and ev.tag is not None and ev.loss_pct is not None:
        if ev.credible:
            direction = EvidenceDirection.SUPPORTS
        elif ev.measured_class and ev.recent:
            direction = EvidenceDirection.CONTRADICTS
        else:
            direction = EvidenceDirection.CONTEXT
        uncertainty = (
            f" (+/- {th.coverage_factor * ev.std_uncertainty_pct:.1f} % points at k = {th.coverage_factor:g})"
            if ev.std_uncertainty_pct is not None
            else ""
        )
        items.append(
            _item(
                inp,
                "SOIL-RATIO",
                f"Soiling ratio {ev.soiling_ratio:.3f} -> soiling loss {ev.loss_pct:.1f} %{uncertainty} "
                f"({(ev.method or SoilingMethod.UNSPECIFIED).value.replace('_', ' ').lower()}, "
                f"last reading {ev.observed_on}, {ev.readings_in_window} reading day(s) in the assessment window).",
                direction,
                "DIRECT_MEASUREMENT" if ev.method in DIRECT_SOILING_METHODS else "CALCULATED",
                ev.tag,
                ev.loss_pct,
                "%",
            )
        )
        if ev.consistent_with_gap is not None and ev.gap_to_explain_pct is not None:
            items.append(
                _item(
                    inp,
                    "SOIL-GAP-CONSISTENCY",
                    f"Deviation left for soiling to explain: {ev.gap_to_explain_pct:.1f} %; measured soiling "
                    f"loss {ev.loss_pct:.1f} %; difference {ev.gap_minus_soiling_pct:+.1f} % points "
                    f"(tolerance {ev.tolerance_pct:.1f}).",
                    EvidenceDirection.SUPPORTS if ev.consistent_with_gap else EvidenceDirection.CONTRADICTS,
                    "CALCULATED",
                    derive([ev.tag, inp.gap.gap.tag], source="SolarWise diagnostics",
                           method="pre-soiling gap vs measured soiling loss"),
                    ev.gap_minus_soiling_pct,
                    "% points",
                )
            )
    else:
        missing.append("A quantified soiling ratio (soiling station, clean reference module or string comparison).")

    # trend shape (indirect)
    pi_tag = derive([inp.gap.expected.tag, inp.gap.actual.tag], source="SolarWise trend analysis",
                    method="Theil-Sen on daily performance index", model_applied=True)
    gradual = False
    if trend.evaluable and trend.slope_pct_per_day is not None:
        long_spell = (trend.spell_days or 0) >= th.min_dry_days_for_trend
        gradual = bool(trend.declining) and long_spell
        items.append(
            _item(
                inp,
                "SOIL-TREND",
                f"Performance index drifts by {trend.slope_pct_per_day:+.3f} % points/day "
                f"(95 % interval {trend.slope_low_pct_per_day:+.3f} .. {trend.slope_high_pct_per_day:+.3f}) over "
                f"{trend.spell_days} day(s) since {trend.spell_start} "
                f"({(trend.spell_started_by or '').replace('_', ' ').lower()}).",
                EvidenceDirection.SUPPORTS if gradual else EvidenceDirection.CONTEXT,
                "PATTERN",
                pi_tag,
                trend.slope_pct_per_day,
                "% points/day",
            )
        )
        if not trend.precipitation_known:
            missing.append("Precipitation record, to establish how long the array has gone without natural cleaning.")
    for event in trend.reset_events:
        if event.recovery_pct is not None and event.recovery_pct >= 1.0:
            items.append(
                _item(
                    inp,
                    "SOIL-RECOVERY",
                    f"Performance index rose by {event.recovery_pct:.1f} % points after "
                    f"{event.kind.lower()} on {event.day}.",
                    EvidenceDirection.SUPPORTS,
                    "PATTERN",
                    pi_tag,
                    event.recovery_pct,
                    "% points",
                )
            )
    if trend.step is not None and trend.step.material:
        items.append(
            _item(
                inp,
                "SOIL-STEP",
                f"Abrupt drop of {trend.step.drop_pct:.1f} % points around {trend.step.day}: not typical of "
                "gradual accumulation (a dust storm is the exception).",
                EvidenceDirection.CONTRADICTS,
                "PATTERN",
                pi_tag,
                trend.step.drop_pct,
                "% points",
            )
        )

    # documented inspections
    inspections = _records(inp, {EvidenceType.VISUAL_INSPECTION}, period.start, period.end)
    heavy = [r for r in inspections if r.finding is InspectionFinding.SOILING_HEAVY]
    light = [r for r in inspections if r.finding is InspectionFinding.SOILING_LIGHT]
    clean = [r for r in inspections if r.finding is InspectionFinding.CLEAN]
    for rec in heavy + light:
        items.append(
            _item(inp, "SOIL-INSPECTION",
                  f"Inspection {rec.reference} ({local_day(rec.observed_start, inp.timezone)}): "
                  f"{(rec.finding.value if rec.finding else '').replace('_', ' ').lower()} - qualitative, not quantified.",
                  EvidenceDirection.SUPPORTS, "DOCUMENT", rec.tag)
        )
    for rec in clean:
        items.append(
            _item(inp, "SOIL-INSPECTION",
                  f"Inspection {rec.reference} ({local_day(rec.observed_start, inp.timezone)}): modules reported clean.",
                  EvidenceDirection.CONTRADICTS, "DOCUMENT", rec.tag)
        )
    documented_heavy = any(r.tag.effective_class(inp.context) is Provenance.MEASURED for r in heavy)

    # ---- support level
    if ev.credible and ev.consistent_with_gap is not False:
        support = SupportLevel.STRONG
        rules.append("S1: credible measured soiling ratio, consistent with the deviation it should explain")
        summary = (
            f"A direct soiling measurement shows a loss of {ev.loss_pct:.1f} %, in line with the deviation "
            "observed in production."
        )
    elif ev.credible:
        support = SupportLevel.MODERATE
        rules.append("S2: credible measured soiling ratio that does not match the observed deviation")
        summary = (
            f"Soiling is measured ({ev.loss_pct:.1f} %) but does not account for the observed deviation; "
            "it is at most part of the explanation."
        )
    elif ev.available and ev.measured_class and ev.recent and not ev.above_floor:
        support = SupportLevel.NOT_SUPPORTED
        rules.append("S3: recent measured soiling ratio indicates a near-clean array")
        summary = (
            f"The soiling measurement indicates a near-clean array ({ev.loss_pct:.1f} % loss): soiling does "
            "not explain a material deviation."
        )
    elif ev.available and ev.quantified and ev.loss_pct is not None:
        if ev.loss_pct >= th.soiling_credibility_floor_pct:
            support = SupportLevel.WEAK
            rules.append("S4: soiling figure available but not of the measured class, not direct, or outdated")
            summary = (
                f"A soiling figure of {ev.loss_pct:.1f} % exists but cannot be treated as credible measured "
                "evidence (see notes); it is indicative only."
            )
        else:
            support = SupportLevel.NOT_SUPPORTED
            rules.append("S5: indicative soiling figure below the credibility floor")
            summary = f"The available (indicative) soiling figure is small ({ev.loss_pct:.1f} %)."
        investigate.append("Obtain a direct, current soiling measurement with a declared uncertainty.")
    elif documented_heavy or (gradual and pre_gap_material):
        support = SupportLevel.MODERATE
        rules.append(
            "S6: no quantified measurement; "
            + ("documented inspection reports heavy soiling" if documented_heavy
               else "gradual decline over a long dry spell with a material deviation")
        )
        summary = (
            "Soiling is plausible on indirect grounds only. A production gap, even a steadily growing one, "
            "does not prove soiling."
        )
    elif pre_gap_material:
        support = SupportLevel.WEAK
        rules.append("S7: material deviation, no soiling measurement and no specific indirect indication")
        summary = "Soiling is compatible with the deviation but nothing specifically points to it."
    else:
        support = SupportLevel.NOT_EVALUABLE
        rules.append("S8: no soiling measurement and no material deviation to explain")
        summary = (
            "Soiling cannot be assessed without a soiling measurement; production data show no material "
            "deviation that would call for one."
        )

    if support in (SupportLevel.MODERATE, SupportLevel.WEAK) and not ev.credible:
        investigate.extend(
            [
                "Quantify soiling directly: compare a freshly cleaned reference string or module with adjacent "
                "uncleaned ones under the same irradiance.",
                "Inspect modules across the site (centre and edges) and document the deposit.",
            ]
        )
    if ev.available and ev.std_uncertainty_pct is None:
        missing.append("Declared uncertainty of the soiling measurement.")
    if ev.available and ev.readings_in_window <= 1 and ev.source == "EVIDENCE_RECORD":
        missing.append("More than one measurement location, to show the figure is representative of the array.")

    soil = _contribution(period, Factor.SOILING)
    loss = soil.energy if _quantified(soil) and soil is not None else None
    uncertainty_note = None
    if ev.available and ev.loss_pct is not None:
        if ev.std_uncertainty_pct is not None:
            uncertainty_note = (
                f"Current soiling loss {ev.loss_pct:.1f} % with declared standard uncertainty "
                f"{ev.std_uncertainty_pct:.1f} % points -> {ev.loss_pct - th.coverage_factor * ev.std_uncertainty_pct:.1f} .. "
                f"{ev.loss_pct + th.coverage_factor * ev.std_uncertainty_pct:.1f} % at k = {th.coverage_factor:g}. "
                "Representativeness of the sensor location is not included."
            )
        else:
            uncertainty_note = "No uncertainty can be stated: the measurement uncertainty was not declared."

    return Hypothesis(
        category=DiagnosticCategory.SOILING,
        title="Soiling of the module surface",
        support=support,
        summary=summary,
        rules=rules,
        evidence=items,
        estimated_loss=loss,
        estimated_loss_share_of_gap_pct=_share_of_gap(loss.value if loss else None, period.gap_kwh),
        uncertainty_note=uncertainty_note,
        competing_explanations=[
            "Equipment under-performance developing gradually (tracker drift, string failures accumulating).",
            "Drift or soiling of the irradiance sensor that feeds the baseline.",
            "A dust-storm deposition event, which appears as an abrupt rather than gradual loss.",
        ],
        missing_evidence=missing,
        recommended_investigation=investigate,
        active_in_window=bool(ev.credible),
    )


def _temperature(inp: DiagnosticInputs) -> Hypothesis:
    th = inp.thresholds
    period = inp.attribution.period
    window = inp.attribution.window
    c = _contribution(period, Factor.TEMPERATURE)
    cw = _contribution(window, Factor.TEMPERATURE)
    descriptor = inp.baseline.descriptor
    items: list[EvidenceItem] = []
    rules: list[str] = []
    missing: list[str] = []
    investigate: list[str] = []
    loss: Traced | None = None
    support: SupportLevel
    mean_temp = [d.cell_temp_c for d in inp.attribution.daily if d.cell_temp_c is not None]
    temp_text = f"{sum(mean_temp) / len(mean_temp):.1f} degC" if mean_temp else "n/a"

    if c is not None and c.status is FactorStatus.ACCOUNTED_IN_BASELINE:
        support = SupportLevel.NOT_SUPPORTED
        rules.append("T1: the baseline is adjusted to actual temperature")
        summary = (
            "The baseline already reflects the temperatures actually experienced, so heat cannot explain a "
            "gap against it - unless the temperature input itself is wrong."
        )
        items.append(
            _item(inp, "TEMP-BASELINE", "Baseline declared temperature-adjusted "
                  f"(energy-weighted cell temperature over the period: {temp_text}).",
                  EvidenceDirection.CONTRADICTS, "CONTEXT", inp.baseline.meta.tag)
        )
    elif _quantified(c) and c is not None:
        loss = c.energy
        share_expected = _share(c)
        share_gap = _share_of_gap(loss.value, period.gap_kwh)
        measured = loss.tag.effective_class(inp.context) is Provenance.MEASURED or (
            c.basis == "CALCULATED" and _tag(inp, Metric.MODULE_TEMP).effective_class(inp.context) is Provenance.MEASURED
        )
        items.append(
            _item(inp, "TEMP-LOSS",
                  f"Thermal loss relative to the baseline reference temperature "
                  f"({descriptor.reference_cell_temp_c:g} degC): {_fmt_mwh(loss.value)} "
                  f"= {share_expected:.1f} % of expected energy; energy-weighted cell temperature {temp_text}.",
                  EvidenceDirection.SUPPORTS if share_expected >= th.factor_materiality_pct else EvidenceDirection.CONTRADICTS,
                  "CALCULATED" if c.basis == "CALCULATED" else "PROXY", loss.tag, share_expected, "%")
        )
        if share_expected < th.factor_materiality_pct:
            support = SupportLevel.NOT_SUPPORTED
            rules.append("T2: calculated thermal deviation is immaterial")
            summary = f"Temperature accounts for only {share_expected:.1f} % of expected energy: not a material cause."
        elif share_gap is not None and share_gap >= 50.0:
            support = SupportLevel.STRONG if measured else SupportLevel.MODERATE
            rules.append(
                "T3: calculated thermal deviation explains most of the gap "
                + ("(measured module temperature)" if measured else "(cell temperature modelled, not measured)")
            )
            summary = (
                f"Operating temperature above the baseline's reference explains {share_gap:.0f} % of the "
                "observed gap. This is an expected physical effect, not a fault."
            )
        else:
            support = SupportLevel.MODERATE if measured else SupportLevel.WEAK
            rules.append("T4: calculated thermal deviation is material but explains less than half of the gap")
            summary = (
                f"Temperature explains part of the gap ({_fmt_pct(share_gap, 0)} of it); another cause must "
                "account for the rest."
            )
        if not measured:
            missing.append("Measured module temperature (the thermal loss rests on a temperature model).")
        if c.status is FactorStatus.PARTIALLY_QUANTIFIED:
            missing.append(f"Temperature data for the whole period (covered: {(c.coverage or 0) * 100:.0f} % of energy).")
    else:
        support = SupportLevel.NOT_EVALUABLE
        rules.append("T5: thermal deviation cannot be calculated")
        summary = (
            "The baseline is not adjusted to actual temperature and the inputs needed to calculate the "
            "thermal effect are missing."
        )
        missing.extend(c.missing_inputs if c is not None else ["temperature data"])
        investigate.append(
            "Provide module (or ambient) temperature and the cell temperature assumed by the baseline, or "
            "use a temperature-adjusted baseline."
        )

    sensor_faults = _records(inp, {EvidenceType.SENSOR_FAULT}, period.start, period.end)
    if sensor_faults:
        items.append(
            _item(inp, "TEMP-SENSOR",
                  f"{len(sensor_faults)} sensor fault record(s) in the period - verify that temperature and "
                  "irradiance inputs were not affected.",
                  EvidenceDirection.CONTEXT, "DOCUMENT", sensor_faults[0].tag)
        )

    return Hypothesis(
        category=DiagnosticCategory.TEMPERATURE,
        title="Operating temperature above the baseline's reference",
        support=support,
        summary=summary,
        rules=rules,
        evidence=items,
        estimated_loss=loss,
        estimated_loss_share_of_gap_pct=_share_of_gap(loss.value if loss else None, period.gap_kwh),
        uncertainty_note=(
            "The thermal loss scales with the module temperature coefficient taken from the plant "
            "configuration; its uncertainty was not declared and is not propagated."
            if loss is not None
            else None
        ),
        competing_explanations=[
            "A wrong or outdated temperature coefficient in the plant configuration.",
            "Module temperature sensor detached from the module or reading ambient air.",
        ],
        missing_evidence=missing,
        recommended_investigation=investigate,
        active_in_window=_quantified(cw) and _share(cw) >= th.factor_materiality_pct,
    )


def _inverter(inp: DiagnosticInputs, pre_gap_material: bool) -> Hypothesis:
    th = inp.thresholds
    period = inp.attribution.period
    window = inp.attribution.window
    devices = inp.devices
    trend = inp.trend
    c = _contribution(period, Factor.EQUIPMENT_AVAILABILITY)
    items: list[EvidenceItem] = []
    rules: list[str] = []
    missing: list[str] = []
    investigate: list[str] = []
    direct_measured = False
    direct_other = False
    active = False

    has_availability = Metric.AVAILABILITY in inp.channels and period.mean_availability is not None
    availability_issue = False
    if has_availability:
        tag = _tag(inp, Metric.AVAILABILITY)
        assert period.mean_availability is not None
        share = _share(c)
        availability_issue = share >= 0.5
        window_low = window.mean_availability is not None and window.mean_availability < th.availability_alert_fraction
        items.append(
            _item(inp, "INV-AVAILABILITY",
                  f"Logged availability: {period.mean_availability * 100:.1f} % over the period"
                  + (f", {window.mean_availability * 100:.1f} % in the assessment window" if window.mean_availability is not None else "")
                  + f"; energy not produced: {_fmt_mwh(c.energy.value if c else None)} ({share:.1f} % of expected).",
                  EvidenceDirection.SUPPORTS if (availability_issue or window_low) else EvidenceDirection.CONTRADICTS,
                  "LOGGED", tag, period.mean_availability * 100.0, "%")
        )
        if availability_issue or window_low:
            if tag.effective_class(inp.context) is Provenance.MEASURED:
                direct_measured = True
            else:
                direct_other = True
        active = active or window_low
    else:
        missing.append("Availability log (capacity-weighted share of inverters in operation).")

    if devices.evaluable:
        flagged = [f for f in devices.findings if f.status != "NORMAL"]
        if flagged:
            names = ", ".join(f.device_code for f in flagged[:6]) + (" ..." if len(flagged) > 6 else "")
            items.append(
                _item(inp, "INV-DEVICES",
                      f"{len(flagged)} of {devices.n_devices} device(s) yield persistently below the fleet median "
                      f"({names}); {devices.active_in_window} still affected in the assessment window; "
                      f"energy lost versus fleet median: {_fmt_mwh(devices.lost_energy_kwh)}.",
                      EvidenceDirection.SUPPORTS, "CALCULATED", devices.tag, float(len(flagged)), "devices")
            )
            if devices.tag.effective_class(inp.context) is Provenance.MEASURED:
                direct_measured = True
            else:
                direct_other = True
            active = active or devices.active_in_window > 0
        else:
            items.append(
                _item(inp, "INV-DEVICES",
                      f"All {devices.n_devices} devices yield within "
                      f"{(1 - th.device_underperformance_ratio) * 100:.0f} % of the fleet median on "
                      f"{devices.n_days} day(s): no device stands out.",
                      EvidenceDirection.CONTRADICTS, "CALCULATED", devices.tag)
            )
    else:
        missing.append("Device-level (inverter) energy, to compare each device with the fleet.")

    faults = _records(inp, {EvidenceType.INVERTER_FAULT}, period.start, period.end)
    open_faults = [
        r for r in _records(inp, {EvidenceType.INVERTER_FAULT}, window.start, window.end) if r.resolved is not True
    ]
    for rec in faults:
        items.append(
            _item(inp, "INV-FAULT-LOG",
                  f"Fault record {rec.reference}"
                  + (f" on {rec.device_code}" if rec.device_code else "")
                  + f" from {local_day(rec.observed_start, inp.timezone)}"
                  + (" (closed)" if rec.resolved is True else " (not closed)")
                  + (f": {rec.description}" if rec.description else "."),
                  EvidenceDirection.SUPPORTS, "DOCUMENT", rec.tag)
        )
        if rec.tag.effective_class(inp.context) is Provenance.MEASURED:
            direct_measured = True
        else:
            direct_other = True
    active = active or bool(open_faults)

    step_material = trend.step is not None and trend.step.material
    if step_material and trend.step is not None:
        pi_tag = derive([inp.gap.expected.tag, inp.gap.actual.tag], source="SolarWise trend analysis",
                        method="largest level shift of the daily performance index", model_applied=True)
        items.append(
            _item(inp, "INV-STEP",
                  f"Performance index dropped abruptly by {trend.step.drop_pct:.1f} % points around "
                  f"{trend.step.day} ({trend.step.before_pct:.1f} % -> {trend.step.after_pct:.1f} %).",
                  EvidenceDirection.SUPPORTS, "PATTERN", pi_tag, trend.step.drop_pct, "% points")
        )

    has_direct_data = has_availability or devices.evaluable or bool(faults)
    if direct_measured:
        support = SupportLevel.STRONG
        rules.append("I1: equipment unavailability shown by logged availability, device comparison or fault records of the measured class")
        summary = "Equipment data show part of the plant not producing as the rest of the fleet does."
    elif direct_other:
        support = SupportLevel.MODERATE
        rules.append("I2: equipment unavailability indicated by data that are not of the measured class")
        summary = "Equipment data indicate a problem, but their provenance does not allow them to count as measured evidence."
    elif step_material:
        support = SupportLevel.MODERATE
        rules.append("I3: abrupt, lasting drop of the performance index without equipment data confirming it")
        summary = "An abrupt drop is consistent with an equipment fault; no equipment data confirm or exclude it."
        # The drop only matters now if it happened in the window or the deviation persists into it.
        active = active or (trend.step is not None and trend.step.day >= window.start) or pre_gap_material
    elif has_direct_data:
        support = SupportLevel.NOT_SUPPORTED
        rules.append("I4: equipment data available and showing no anomaly; no abrupt change")
        summary = "Available equipment data show no anomaly."
    else:
        support = SupportLevel.NOT_EVALUABLE
        rules.append("I5: no availability log, no device-level energy, no fault records")
        summary = "No equipment data are available; an equipment fault can be neither shown nor excluded."

    if support in (SupportLevel.STRONG, SupportLevel.MODERATE):
        investigate.extend(
            [
                "Review inverter alarm and event logs for the affected devices and dates.",
                "Check DC side of the affected blocks (string currents, fuses, combiner boxes) and trackers if fitted.",
                "Restore the equipment before judging any remaining deviation: losses on a unit that is "
                "not producing cannot be recovered by cleaning.",
            ]
        )
    loss = c.energy if _quantified(c) and c is not None and _share(c) > 0 else None
    return Hypothesis(
        category=DiagnosticCategory.INVERTER,
        title="Inverter or other equipment fault",
        support=support,
        summary=summary,
        rules=rules,
        evidence=items,
        estimated_loss=loss,
        estimated_loss_share_of_gap_pct=_share_of_gap(loss.value if loss else None, period.gap_kwh),
        uncertainty_note=None,
        competing_explanations=[
            "Planned maintenance or a grid-side constraint affecting only part of the plant.",
            "Uneven soiling or shading of the blocks connected to the affected devices.",
            "A metering or communication fault on the affected devices (energy produced but not recorded).",
        ],
        missing_evidence=missing,
        recommended_investigation=investigate,
        active_in_window=active and support in (SupportLevel.STRONG, SupportLevel.MODERATE),
    )


def _shading(inp: DiagnosticInputs) -> Hypothesis:
    period = inp.attribution.period
    intraday = inp.intraday
    items: list[EvidenceItem] = []
    rules: list[str] = []
    missing: list[str] = []
    investigate: list[str] = []
    pattern_tag = derive([inp.gap.expected.tag, inp.gap.actual.tag], source="SolarWise intraday analysis",
                         method="loss fraction by part of day (morning / midday / evening)", model_applied=True)

    records = _records(inp, {EvidenceType.SHADING_OBSERVATION, EvidenceType.VISUAL_INSPECTION}, period.start, period.end)
    records = [
        r for r in records
        if r.evidence_type is EvidenceType.SHADING_OBSERVATION or r.finding is InspectionFinding.SHADING
    ]
    documented = any(r.tag.effective_class(inp.context) is Provenance.MEASURED for r in records)
    for rec in records:
        items.append(
            _item(inp, "SHADE-OBSERVATION",
                  f"Record {rec.reference} ({local_day(rec.observed_start, inp.timezone)}): shading observed"
                  + (f" - {rec.description}" if rec.description else "."),
                  EvidenceDirection.SUPPORTS, "DOCUMENT", rec.tag)
        )

    loss: Traced | None = None
    if intraday.evaluable:
        items.append(
            _item(inp, "SHADE-PROFILE",
                  f"Loss by part of day: morning {_fmt_pct(intraday.loss_morning_pct)}, midday "
                  f"{_fmt_pct(intraday.loss_midday_pct)}, evening {_fmt_pct(intraday.loss_evening_pct)}"
                  + (f"; {intraday.edge_side.lower()} exceeds midday by {intraday.edge_excess_pct:.1f} % points on "
                     f"{intraday.days_with_edge_excess} of {intraday.days_evaluated} day(s)."
                     if intraday.edge_side and intraday.edge_excess_pct is not None else "."),
                  EvidenceDirection.SUPPORTS if intraday.shading_signature else EvidenceDirection.CONTRADICTS,
                  "PATTERN", pattern_tag, intraday.edge_excess_pct, "% points")
        )
        if intraday.shading_signature and intraday.shading_excess_loss_kwh is not None:
            loss = Traced(
                value=intraday.shading_excess_loss_kwh, unit="kWh", tag=pattern_tag, basis="PROXY",
                note="Excess loss in the affected part of the day over the midday loss fraction.",
            )
    else:
        missing.append("Sub-daily (hourly or finer) production data: shading shows in the shape of the day, not in daily totals.")

    if intraday.shading_signature and documented:
        support = SupportLevel.STRONG
        rules.append("H1: persistent one-sided loss near sunrise/sunset and a documented shading observation")
        summary = "A persistent loss confined to one end of the day is corroborated by a documented observation of shading."
    elif intraday.shading_signature:
        support = SupportLevel.MODERATE
        rules.append("H2: persistent loss near sunrise/sunset, not confirmed on site")
        side = (intraday.edge_side or "").lower()
        summary = (
            f"Losses are concentrated in the {side} while midday is unaffected, day after day. This pattern is "
            "typical of shading but is a proxy until confirmed on site."
        )
    elif records:
        support = SupportLevel.MODERATE
        rules.append("H3: documented shading observation, not corroborated by an intraday pattern")
        summary = "Shading was documented on site; production data cannot confirm its effect."
    elif intraday.evaluable:
        support = SupportLevel.NOT_SUPPORTED
        rules.append("H4: intraday profile shows no loss concentrated near sunrise or sunset")
        summary = "The shape of the day shows no loss confined to low-sun hours."
    else:
        support = SupportLevel.NOT_EVALUABLE
        rules.append("H5: daily data only and no site observation")
        summary = "Shading cannot be assessed from daily totals and no site observation is recorded."

    if support in (SupportLevel.STRONG, SupportLevel.MODERATE):
        investigate.extend(
            [
                "Inspect the site at the affected time of day for new obstructions, vegetation, sand accumulation "
                "or structures, and for row-to-row shading.",
                "On tracking systems, check backtracking and tracker position at low sun.",
            ]
        )
    if not records:
        missing.append("A documented site observation at the affected time of day.")

    return Hypothesis(
        category=DiagnosticCategory.SHADING,
        title="Shading of part of the array",
        support=support,
        summary=summary,
        rules=rules,
        evidence=items,
        estimated_loss=loss,
        estimated_loss_share_of_gap_pct=_share_of_gap(loss.value if loss else None, period.gap_kwh),
        uncertainty_note=(
            "The shading loss is a pattern-based proxy; no uncertainty can be stated for it." if loss else None
        ),
        competing_explanations=[
            "Tracker stalled or mis-positioned at low sun.",
            "Baseline error at low sun elevation (angle-of-incidence and spectral effects).",
            "Heavier angular losses of a soiled array at high incidence angles (would affect both ends of the day).",
        ],
        missing_evidence=missing,
        recommended_investigation=investigate,
        active_in_window=intraday.shading_signature,
    )


def _curtailment(inp: DiagnosticInputs) -> tuple[Hypothesis, bool]:
    """Returns the hypothesis and whether an *unexplained* outage is present in the window."""
    th = inp.thresholds
    period = inp.attribution.period
    window = inp.attribution.window
    intraday = inp.intraday
    curt = _contribution(period, Factor.CURTAILMENT)
    down = _contribution(period, Factor.DOWNTIME)
    curt_w = _contribution(window, Factor.CURTAILMENT)
    down_w = _contribution(window, Factor.DOWNTIME)
    items: list[EvidenceItem] = []
    rules: list[str] = []
    missing: list[str] = []
    investigate: list[str] = []
    measured = False
    other = False

    has_log = _quantified(curt)
    curtailed = (curt.energy.value or 0.0) if has_log and curt is not None else 0.0
    logged_material = has_log and _share(curt) >= 0.2
    if has_log and curt is not None:
        tag = _tag(inp, Metric.CURTAILED_ENERGY)
        items.append(
            _item(inp, "CURT-LOG",
                  f"Energy logged as curtailed: {_fmt_mwh(curtailed)} ({_share(curt):.1f} % of expected).",
                  EvidenceDirection.SUPPORTS if logged_material else EvidenceDirection.CONTRADICTS,
                  "LOGGED", tag, curtailed, "kWh")
        )
        if logged_material:
            if tag.effective_class(inp.context) is Provenance.MEASURED:
                measured = True
            else:
                other = True
    else:
        missing.append("Curtailment log (curtailed energy or active-power set-points from the grid operator).")

    downtime = (down.energy.value or 0.0) if down is not None else 0.0
    downtime_material = _share(down) >= 0.2 and period.outage_slots > 0
    if period.outage_slots > 0 and down is not None:
        items.append(
            _item(inp, "DOWN-OUTAGE",
                  f"{period.outage_slots} daylight interval(s) with (near-)zero production while energy was "
                  f"expected: {_fmt_mwh(downtime)} ({_share(down):.1f} % of expected).",
                  EvidenceDirection.SUPPORTS, "CALCULATED", down.energy.tag, downtime, "kWh")
        )
        if downtime_material:
            # The outage itself is seen in the production channel; the baseline only sizes it.
            if _tag(inp, Metric.ACTUAL_ENERGY).effective_class(inp.context) is Provenance.MEASURED:
                measured = True
            else:
                other = True

    records = _records(inp, {EvidenceType.CURTAILMENT_EVENT, EvidenceType.GRID_OUTAGE}, period.start, period.end)
    for rec in records:
        items.append(
            _item(inp, "CURT-RECORD",
                  f"{rec.evidence_type.value.replace('_', ' ').title()} record {rec.reference} "
                  f"({local_day(rec.observed_start, inp.timezone)})" + (f": {rec.description}" if rec.description else "."),
                  EvidenceDirection.SUPPORTS, "DOCUMENT", rec.tag)
        )
        if rec.tag.effective_class(inp.context) is Provenance.MEASURED:
            measured = True
        else:
            other = True

    plateau_tag = derive([inp.gap.expected.tag, inp.gap.actual.tag], source="SolarWise intraday analysis",
                         method="flat output below the day's typical actual/expected ratio", model_applied=True)
    if intraday.evaluable:
        if intraday.plateau_signature:
            level = (
                f" at about {intraday.plateau_level_of_ac * 100:.0f} % of AC capacity"
                if intraday.plateau_level_of_ac is not None else ""
            )
            items.append(
                _item(inp, "CURT-PLATEAU",
                      f"Output held flat{level} on {intraday.plateau_days} day(s) while expected output kept "
                      f"rising above it; energy below the day's own trend: {_fmt_mwh(intraday.plateau_excess_loss_kwh)}.",
                      EvidenceDirection.SUPPORTS, "PATTERN", plateau_tag,
                      float(intraday.plateau_days), "days")
            )
        else:
            items.append(
                _item(inp, "CURT-PLATEAU", "No flat-topped output profile was found in the intraday data.",
                      EvidenceDirection.CONTRADICTS, "PATTERN", plateau_tag)
            )
    elif not has_log:
        missing.append("Sub-daily production data, in which curtailment appears as a flat-topped profile.")

    if measured:
        support = SupportLevel.STRONG
        rules.append("C1: curtailment logged, outage visible in measured production, or documented grid event")
        summary = "Part of the gap is production that was withheld or interrupted, as shown by logs or by the production record itself."
    elif other:
        support = SupportLevel.MODERATE
        rules.append("C2: curtailment or outage indicated by data that are not of the measured class")
        summary = "Curtailment or an outage is indicated, by data whose provenance does not count as measured evidence."
    elif intraday.plateau_signature:
        support = SupportLevel.MODERATE
        rules.append("C3: flat-topped output profile without a curtailment log")
        summary = "A flat-topped output profile suggests an active-power limit; no log confirms it."
    elif has_log or intraday.evaluable:
        support = SupportLevel.NOT_SUPPORTED
        rules.append("C4: curtailment log or intraday profile available and showing nothing; no outage")
        summary = "No curtailment is logged or visible, and no outage interval was found."
    else:
        support = SupportLevel.NOT_EVALUABLE
        rules.append("C5: no curtailment log and no sub-daily data (no outage found in production)")
        summary = "No outage interval was found; curtailment cannot be assessed without a log or sub-daily data."

    # An outage in the assessment window that no record explains is an open technical question.
    window_records = _records(inp, {EvidenceType.CURTAILMENT_EVENT, EvidenceType.GRID_OUTAGE}, window.start, window.end)
    unexplained_outage = (
        window.outage_slots > 0 and _share(down_w) >= th.factor_materiality_pct and not window_records
    )
    if unexplained_outage:
        investigate.append(
            "Establish why the plant produced nothing during the outage interval(s) in the assessment window "
            "(grid event, protection trip, maintenance, or a telemetry fault)."
        )
    if support is SupportLevel.MODERATE and intraday.plateau_signature and not has_log:
        investigate.append("Obtain the grid operator's dispatch instructions or plant-controller set-points for the affected days.")

    loss: Traced | None = None
    total = curtailed + downtime
    if total > 0:
        tags = []
        if curtailed > 0 and curt is not None:
            tags.append(curt.energy.tag)
        if downtime > 0 and down is not None:
            tags.append(down.energy.tag)
        loss = Traced(value=total, unit="kWh",
                      tag=derive(tags, source="SolarWise attribution", method="logged curtailment + calculated downtime"),
                      basis="LOGGED+CALCULATED")
    elif intraday.plateau_signature and intraday.plateau_excess_loss_kwh:
        loss = Traced(value=intraday.plateau_excess_loss_kwh, unit="kWh", tag=plateau_tag, basis="PROXY",
                      note="Energy below the day's own actual/expected trend during plateau intervals.")

    active = (_quantified(curt_w) and _share(curt_w) >= 0.2) or window.outage_slots > 0
    hypothesis = Hypothesis(
        category=DiagnosticCategory.CURTAILMENT_DOWNTIME,
        title="Curtailment or downtime",
        support=support,
        summary=summary,
        rules=rules,
        evidence=items,
        estimated_loss=loss,
        estimated_loss_share_of_gap_pct=_share_of_gap(loss.value if loss else None, period.gap_kwh),
        uncertainty_note=(
            "Logged curtailed energy is itself an estimate made by the plant controller; its uncertainty "
            "was not declared." if curtailed > 0 else None
        ),
        competing_explanations=[
            "Inverter clipping at the AC rating (a design property, not curtailment).",
            "A telemetry gap recorded as zero production.",
        ],
        missing_evidence=missing,
        recommended_investigation=investigate,
        active_in_window=bool(active) and support in (SupportLevel.STRONG, SupportLevel.MODERATE),
    )
    return hypothesis, unexplained_outage


def production_is_reliable(inp: DiagnosticInputs) -> tuple[bool, list[str]]:
    """Reliable measured production: measured class, complete enough, gap computable."""
    th = inp.thresholds
    reasons: list[str] = []
    actual_class = inp.gap.actual.tag.effective_class(inp.context)
    if inp.gap.result.status is not GapStatus.OK:
        reasons.append(inp.gap.result.message or "The performance gap could not be computed.")
    if actual_class is not Provenance.MEASURED:
        reasons.append(
            f"Actual energy has provenance {inp.gap.actual.tag.label}; in the {inp.context.value} context it "
            f"counts as {actual_class.value}, not as measured production."
        )
    cov = inp.gap.coverage.fraction
    if cov is None or cov < th.min_data_completeness:
        reasons.append(
            f"Data completeness over the period is {_fmt_pct(cov * 100 if cov is not None else None)} "
            f"(minimum {th.min_data_completeness * 100:.0f} %)."
        )
    wcov = inp.gap.window.coverage.fraction
    if wcov is None or wcov < th.min_data_completeness:
        reasons.append(
            f"Data completeness in the assessment window is {_fmt_pct(wcov * 100 if wcov is not None else None)} "
            f"(minimum {th.min_data_completeness * 100:.0f} %)."
        )
    return (not reasons), reasons


def _insufficient(inp: DiagnosticInputs, others: Sequence[Hypothesis], material: bool) -> tuple[Hypothesis, bool]:
    reliable, reasons = production_is_reliable(inp)
    items: list[EvidenceItem] = []
    missing: list[str] = list(reasons)
    baseline_tag = inp.baseline.meta.tag
    baseline_unknown = baseline_tag.effective_class(inp.context) is Provenance.UNKNOWN
    if baseline_unknown:
        missing.append("The origin of the expected-energy baseline is unknown.")
    cov = inp.gap.coverage
    items.append(
        _item(inp, "DATA-COVERAGE",
              f"{cov.matched_daylight_slots} of {cov.daylight_slots} daylight interval(s) have both expected and "
              f"actual data ({_fmt_pct(cov.fraction * 100 if cov.fraction is not None else None)}); "
              f"{cov.missing_actual_slots} lack actual energy, {cov.missing_expected_slots} lack expected energy.",
              EvidenceDirection.SUPPORTS if not reliable else EvidenceDirection.CONTRADICTS,
              "CALCULATED", inp.gap.gap.tag, cov.fraction * 100 if cov.fraction is not None else None, "%")
    )
    not_evaluable = [h for h in others if h.support is SupportLevel.NOT_EVALUABLE]
    for h in not_evaluable:
        missing.extend(f"[{h.category.value}] {m}" for m in h.missing_evidence)
    unquantified = [
        c for c in inp.attribution.period.contributions if c.status is FactorStatus.NOT_QUANTIFIED
    ]
    if unquantified:
        items.append(
            _item(inp, "DATA-FACTORS",
                  "Factors that could not be quantified and therefore remain inside the residual: "
                  + ", ".join(c.factor.value.replace("_", " ").lower() for c in unquantified) + ".",
                  EvidenceDirection.SUPPORTS, "CONTEXT", UNKNOWN_TAG)
        )

    critical = (not reliable) or baseline_unknown
    if critical:
        support = SupportLevel.STRONG
        rule = "D1: production data are not reliable measured data, or the baseline is of unknown origin"
        summary = "The data do not support any conclusion about the cause - or even the existence - of a deviation."
    elif material and len(not_evaluable) >= 2:
        support = SupportLevel.MODERATE
        rule = "D2: material deviation while two or more hypotheses cannot be evaluated"
        summary = "A deviation exists but several possible causes cannot be evaluated with the data at hand."
    elif not_evaluable or unquantified:
        support = SupportLevel.WEAK
        rule = "D3: some hypotheses or factors cannot be evaluated"
        summary = "The core data are adequate; some hypotheses cannot be evaluated."
    else:
        support = SupportLevel.NOT_SUPPORTED
        rule = "D4: every hypothesis could be evaluated"
        summary = "The data are sufficient to evaluate every hypothesis."

    deduped = list(dict.fromkeys(missing))
    hypothesis = Hypothesis(
        category=DiagnosticCategory.INSUFFICIENT_DATA,
        title="Insufficient data",
        support=support,
        summary=summary,
        rules=[rule],
        evidence=items,
        competing_explanations=[],
        missing_evidence=deduped,
        recommended_investigation=(
            ["Restore complete, measured production telemetry and a documented baseline before drawing conclusions."]
            if critical
            else (["Add the missing inputs listed to narrow down the cause."] if deduped else [])
        ),
        active_in_window=critical,
    )
    return hypothesis, critical


def _unclassified(inp: DiagnosticInputs, ev: SoilingEvidence) -> tuple[Hypothesis, float | None, bool | None]:
    th = inp.thresholds
    window = inp.attribution.window
    period = inp.attribution.period
    chain_residual = window.residual_pct
    residual = chain_residual
    period_residual_kwh = period.residual_kwh
    tag = derive([inp.gap.expected.tag, inp.gap.actual.tag], source="SolarWise attribution",
                 method="expected - quantified factors - actual", model_applied=True)

    # A loss that only a soiling figure of inadequate kind accounts for (not a direct measurement,
    # not of the measured class, or outdated) is not an explained loss.  The attribution table
    # still shows what the figure would imply; here it is counted as unexplained.
    uncredited: float | None = None
    soiling_in_chain = _contribution(window, Factor.SOILING)
    if (
        chain_residual is not None
        and window.pre_soiling_gap_pct is not None
        and ev.available
        and not (ev.measured_class and ev.recent)
        and _quantified(soiling_in_chain)
    ):
        uncredited = max(0.0, window.pre_soiling_gap_pct - chain_residual)
        residual = chain_residual + uncredited
        period_soiling = _contribution(period, Factor.SOILING)
        if period_residual_kwh is not None and _quantified(period_soiling):
            assert period_soiling is not None
            period_residual_kwh += max(0.0, period_soiling.energy.value or 0.0)

    material: bool | None = None if residual is None else residual >= th.gap_materiality_pct
    items = [
        _item(inp, "RESIDUAL",
              f"Unexplained residual: {_fmt_pct(chain_residual)} of pre-soiling expected energy in the assessment "
              f"window; {_fmt_mwh(period.residual_kwh)} ({_fmt_pct(period.residual_pct)}) over the period.",
              EvidenceDirection.SUPPORTS if material else EvidenceDirection.CONTRADICTS,
              "CALCULATED", tag, chain_residual, "%")
    ]
    if uncredited:
        items.append(
            _item(inp, "RESIDUAL-UNCREDITED-SOILING",
                  f"A further {uncredited:.1f} % is matched only by a soiling figure that does not qualify as "
                  "measured evidence (" + " ".join(ev.notes) + ") It is counted as unexplained: "
                  f"{_fmt_pct(residual)} in total.",
                  EvidenceDirection.SUPPORTS, "CALCULATED", tag, uncredited, "%")
        )
    if residual is None:
        support = SupportLevel.NOT_EVALUABLE
        rule = "U3: residual cannot be computed"
        summary = "No residual can be computed."
    elif material:
        support = SupportLevel.STRONG if residual >= th.gap_severe_pct else SupportLevel.MODERATE
        rule = "U1: a material residual remains after every quantified factor"
        summary = (
            f"{residual:.1f} % of expected energy is lost to causes that the available evidence does not "
            "identify. It must not be assigned to soiling by default."
        )
    else:
        support = SupportLevel.NOT_SUPPORTED
        rule = "U2: no material residual"
        summary = "Quantified factors account for the deviation within the materiality threshold."
    loss = None
    if period_residual_kwh is not None and period_residual_kwh > 0 and material:
        loss = Traced(value=period_residual_kwh, unit="kWh", tag=tag, basis="CALCULATED")
    hypothesis = Hypothesis(
        category=DiagnosticCategory.UNCLASSIFIED,
        title="Unclassified loss",
        support=support,
        summary=summary,
        rules=[rule],
        evidence=items,
        estimated_loss=loss,
        estimated_loss_share_of_gap_pct=_share_of_gap(loss.value if loss else None, period.gap_kwh),
        competing_explanations=[
            "Any factor listed as not quantified (see the attribution table).",
            "Baseline model error or a biased irradiance sensor.",
            "Module degradation or defects (PID, hot spots, cracked cells) not visible in plant-level data.",
        ],
        missing_evidence=[],
        recommended_investigation=(
            [
                "Supply the inputs for the factors listed as not quantified.",
                "Verify the irradiance sensor (cleanliness, alignment, calibration date) that feeds the baseline.",
                "Consider IV-curve tracing or thermography on a sample of strings.",
            ]
            if material
            else []
        ),
        active_in_window=bool(material),
    )
    return hypothesis, residual, material


# --------------------------------------------------------------------------- entry point


def evaluate_hypotheses(inp: DiagnosticInputs) -> DiagnosticReport:
    """Evaluate all hypotheses and summarise without forcing a single diagnosis."""
    th = inp.thresholds
    window = inp.attribution.window

    soiling_evidence, conflicts = distill_soiling_evidence(inp)
    pre_gap = window.pre_soiling_gap_pct
    pre_gap_material = pre_gap is not None and pre_gap >= th.gap_materiality_pct

    soiling = _soiling(inp, soiling_evidence, pre_gap_material)
    temperature = _temperature(inp)
    inverter = _inverter(inp, pre_gap_material)
    shading = _shading(inp)
    curtailment, unexplained_outage = _curtailment(inp)
    physical = [soiling, temperature, inverter, shading, curtailment]

    sig_now = inp.gap.window.significance
    sig_period = inp.gap.significance
    deviation_now = bool(sig_now.significant) and sig_now.direction is GapDirection.UNDERPERFORMANCE
    deviation_period = bool(sig_period.significant) and sig_period.direction is GapDirection.UNDERPERFORMANCE

    insufficient, data_critical = _insufficient(inp, physical, deviation_now or deviation_period)
    unclassified, residual, residual_material = _unclassified(inp, soiling_evidence)

    # ---- inspection vs sensor
    recent_inspections = _records(inp, {EvidenceType.VISUAL_INSPECTION}, window.start, window.end)
    if soiling_evidence.available and soiling_evidence.measured_class and soiling_evidence.recent:
        heavy = [r for r in recent_inspections if r.finding is InspectionFinding.SOILING_HEAVY]
        clean = [r for r in recent_inspections if r.finding is InspectionFinding.CLEAN]
        if heavy and not soiling_evidence.above_floor:
            conflicts.append(
                Conflict(
                    code="C-INSPECTION-VS-SENSOR",
                    severity="CRITICAL",
                    description=(
                        f"Inspection {heavy[0].reference} reports heavy soiling while the soiling measurement "
                        f"indicates only {soiling_evidence.loss_pct:.1f} % loss."
                    ),
                    involved=[DiagnosticCategory.SOILING],
                    resolution="Check the soiling sensor: a soiled 'clean' reference device or an "
                    "unrepresentative location makes it under-read. Run a clean-reference test on the array.",
                )
            )
        if clean and soiling_evidence.credible:
            conflicts.append(
                Conflict(
                    code="C-INSPECTION-VS-SENSOR",
                    severity="CRITICAL",
                    description=(
                        f"Inspection {clean[0].reference} reports clean modules while the soiling measurement "
                        f"indicates {soiling_evidence.loss_pct:.1f} % loss."
                    ),
                    involved=[DiagnosticCategory.SOILING],
                    resolution="Verify the soiling sensor and repeat the inspection across the site.",
                )
            )

    if soiling_evidence.credible and inp.trend.step is not None and inp.trend.step.material:
        conflicts.append(
            Conflict(
                code="C-STEP-DURING-SOILING",
                severity="MINOR",
                description=(
                    f"Soiling is measured, yet the performance index also dropped abruptly by "
                    f"{inp.trend.step.drop_pct:.1f} % points around {inp.trend.step.day}."
                ),
                involved=[DiagnosticCategory.SOILING, DiagnosticCategory.INVERTER],
                resolution="Check for an equipment event or a dust storm on that date.",
            )
        )

    # ---- technical issues present now
    technical: list[str] = []
    if inverter.active_in_window:
        technical.append("Equipment under-performance or unavailability is present in the assessment window.")
    if unexplained_outage:
        technical.append("An outage in the assessment window is not explained by any recorded grid or curtailment event.")
    open_sensor_faults = [
        r for r in _records(inp, {EvidenceType.SENSOR_FAULT}, window.start, window.end) if r.resolved is not True
    ]
    for rec in open_sensor_faults:
        technical.append(f"Open sensor fault {rec.reference}: {rec.description or 'no description'}")

    # ---- summary status
    hypotheses = [soiling, temperature, inverter, shading, curtailment, insufficient, unclassified]
    supported = [h for h in physical if h.support in (SupportLevel.STRONG, SupportLevel.MODERATE)]
    supported.sort(
        key=lambda h: (_SUPPORT_RANK[h.support], (h.estimated_loss.value or 0.0) if h.estimated_loss else 0.0),
        reverse=True,
    )
    critical_conflicts = [c for c in conflicts if c.severity == "CRITICAL"]

    if data_critical:
        status = DiagnosticStatus.INSUFFICIENT_DATA
        headline = "The data are not sufficient to establish whether, or why, the plant deviates from its baseline."
    elif critical_conflicts:
        status = DiagnosticStatus.CONFLICTING_EVIDENCE
        headline = "Evidence conflicts: " + critical_conflicts[0].description
    elif not deviation_now and not deviation_period:
        status = DiagnosticStatus.NO_SIGNIFICANT_DEVIATION
        headline = "Production is in line with the baseline within the significance threshold."
    elif len(supported) == 1 and not residual_material:
        status = DiagnosticStatus.SINGLE_EXPLANATION
        headline = f"{supported[0].title} accounts for the deviation: {supported[0].summary}"
    elif supported:
        status = DiagnosticStatus.MULTIPLE_PLAUSIBLE
        names = ", ".join(h.title.lower() for h in supported)
        headline = (
            f"Several explanations remain plausible ({names})"
            + (" and a material residual is unexplained." if residual_material else ".")
        )
    else:
        status = DiagnosticStatus.UNCLASSIFIED
        headline = "A significant deviation exists but the available evidence does not identify its cause."

    return DiagnosticReport(
        status=status,
        headline=headline,
        hypotheses=hypotheses,
        leading=[h.category for h in supported],
        conflicts=conflicts,
        soiling_evidence=soiling_evidence,
        unresolved_technical_issue=bool(technical),
        technical_issues=technical,
        unexplained_residual_pct=residual,
        unexplained_residual_material=residual_material,
        deviation_now=deviation_now,
        deviation_period=deviation_period,
    )


__all__ = [
    "Conflict",
    "DiagnosticCategory",
    "DiagnosticInputs",
    "DiagnosticReport",
    "DiagnosticStatus",
    "EvidenceDirection",
    "EvidenceItem",
    "Hypothesis",
    "SoilingEvidence",
    "SupportLevel",
    "distill_soiling_evidence",
    "evaluate_hypotheses",
    "production_is_reliable",
]
