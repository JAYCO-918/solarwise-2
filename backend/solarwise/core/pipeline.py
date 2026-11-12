"""The analysis pipeline.

    input -> validation -> baseline -> gap -> attribution -> diagnostic hypotheses
          -> recoverable energy -> economics -> evidence assessment -> decision
          -> explanation

Every stage is a plain function in its own module and can be called and tested
on its own; this module only wires them together and records what each stage
concluded.  The pipeline is pure: no database, no network, no clock dependence
other than the timestamp written on the result.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from solarwise.core.attribution import LossAttribution, attribute_losses
from solarwise.core.baseline import (
    BaselineContext,
    BaselineRequest,
    BaselineResult,
    BaselineStatus,
    resolve_baseline,
)
from solarwise.core.data_quality import DataQualityReport, QualityIssue, QualityStatus, assess_data_quality
from solarwise.core.decision import Recommendation, decide
from solarwise.core.devices import DeviceAnalysis, analyse_devices
from solarwise.core.diagnostics import DiagnosticInputs, DiagnosticReport, evaluate_hypotheses
from solarwise.core.economics import EconomicInputs, EconomicsResult, evaluate_cleaning_economics
from solarwise.core.evidence import EvidenceAssessment, assess_evidence
from solarwise.core.explanation import Explanation, build_explanation
from solarwise.core.gap import GapSeries, GapStatus, compute_gap_series
from solarwise.core.intraday import IntradayAnalysis, analyse_intraday
from solarwise.core.models import (
    AnalysisThresholds,
    BaselineDescriptor,
    ChannelMeta,
    DeviceObservation,
    DeviceSpec,
    EvidenceRecord,
    EvidenceType,
    Metric,
    Observation,
    PlantSpec,
)
from solarwise.core.provenance import UNKNOWN_TAG, EvaluationContext, ProvenanceTag
from solarwise.core.recoverable import CleaningAssumptions, RecoverableEnergy, estimate_recoverable_energy
from solarwise.core.timeline import build_slots, get_zone, local_day, observation_span
from solarwise.core.trend import TrendAnalysis, analyse_trend

ENGINE_VERSION = "1.0.0"

#: Longest period analysed in one run [days].
MAX_PERIOD_DAYS = 366


class AnalysisError(ValueError):
    """The request cannot be analysed at all (as opposed to: analysed with caveats)."""


class AnalysisOptions(BaseModel):
    """Options of one analysis run."""

    model_config = ConfigDict(extra="forbid")

    period_start: date | None = None
    period_end: date | None = None
    baseline: BaselineRequest = Field(default_factory=BaselineRequest)
    thresholds: AnalysisThresholds = Field(default_factory=AnalysisThresholds)
    cleaning: CleaningAssumptions | None = None
    economics: EconomicInputs | None = None


@dataclass
class AnalysisInput:
    plant: PlantSpec
    observations: Sequence[Observation]
    interval_minutes: int
    channels: Mapping[Metric, ChannelMeta]
    context: EvaluationContext
    options: AnalysisOptions = field(default_factory=AnalysisOptions)
    declared_baseline: BaselineDescriptor | None = None
    device_observations: Mapping[str, Sequence[DeviceObservation]] = field(default_factory=dict)
    devices: Mapping[str, DeviceSpec] = field(default_factory=dict)
    device_tag: ProvenanceTag | None = None
    records: Sequence[EvidenceRecord] = ()
    import_issues: Sequence[QualityIssue] = ()
    dataset_name: str | None = None
    #: Free-text statement shown with every output derived from the dataset.
    dataset_disclaimer: str | None = None
    #: When false, even a real plant only receives an advisory result.
    allow_operational_authorization: bool = True


class StageState(StrEnum):
    OK = "OK"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"


class StageStatus(BaseModel):
    key: str
    title: str
    state: StageState
    message: str


class ChannelProvenance(BaseModel):
    metric: Metric
    label: str
    provenance: str
    effective_class: str
    source: str
    method: str | None = None
    unit: str
    uncertainty_pct: float | None = None
    uncertainty_abs: float | None = None


class AnalysisResult(BaseModel):
    engine_version: str = ENGINE_VERSION
    generated_at: datetime
    context: EvaluationContext
    plant: PlantSpec
    dataset_name: str | None
    period_start: date
    period_end: date
    interval_minutes: int
    timezone: str
    thresholds: AnalysisThresholds
    stages: list[StageStatus]
    provenance: list[ChannelProvenance]
    quality: DataQualityReport
    baseline: BaselineResult
    gap: GapSeries
    attribution: LossAttribution
    trend: TrendAnalysis
    devices: DeviceAnalysis
    intraday: IntradayAnalysis
    diagnostics: DiagnosticReport
    recoverable: RecoverableEnergy
    economics: EconomicsResult
    evidence: EvidenceAssessment
    recommendation: Recommendation
    explanation: Explanation
    cleaning_assumptions: CleaningAssumptions | None
    economic_inputs: EconomicInputs | None
    disclaimers: list[str]


_LABELS = {
    Metric.ACTUAL_ENERGY: "Actual energy",
    Metric.EXPECTED_ENERGY: "Expected energy (baseline)",
    Metric.BASELINE_IRRADIATION: "Baseline reference irradiation",
    Metric.AVAILABILITY: "Availability",
    Metric.CURTAILED_ENERGY: "Curtailed energy",
    Metric.SOILING_RATIO: "Soiling ratio",
    Metric.POA_IRRADIATION: "In-plane irradiation",
    Metric.GHI: "Global horizontal irradiation",
    Metric.AMBIENT_TEMP: "Ambient temperature",
    Metric.MODULE_TEMP: "Module temperature",
    Metric.WIND_SPEED: "Wind speed",
    Metric.RELATIVE_HUMIDITY: "Relative humidity",
    Metric.PRECIPITATION: "Precipitation",
    Metric.DEVICE_ENERGY: "Device energy",
}


def resolve_period(inp: AnalysisInput) -> tuple[date, date]:
    """Analysis period in local days: the requested one, else the span of the data."""
    zone = get_zone(inp.plant.timezone)
    span = observation_span(inp.observations, zone)
    if span is None:
        raise AnalysisError("the dataset contains no observations")
    start = inp.options.period_start or span[0]
    end = inp.options.period_end or span[1]
    if end < start:
        raise AnalysisError("the analysis period ends before it starts")
    if (end - start).days + 1 > MAX_PERIOD_DAYS:
        raise AnalysisError(f"the analysis period exceeds {MAX_PERIOD_DAYS} days; analyse a shorter period")
    if end < span[0] or start > span[1]:
        raise AnalysisError(
            f"the requested period ({start} .. {end}) does not overlap the data ({span[0]} .. {span[1]})"
        )
    return start, end


def run_analysis(inp: AnalysisInput, *, now: datetime | None = None) -> AnalysisResult:
    """Run every stage of the pipeline and return the complete, self-describing result."""
    options = inp.options
    th = options.thresholds
    plant = inp.plant
    zone = get_zone(plant.timezone)
    period_start, period_end = resolve_period(inp)
    stages: list[StageStatus] = []

    slots = build_slots(
        inp.observations, inp.interval_minutes, plant.timezone, plant.latitude, plant.longitude,
        period_start, period_end,
    )
    channels = dict(inp.channels)

    # 1 ------------------------------------------------------------ validation / data quality
    quality = assess_data_quality(
        slots,
        interval_minutes=inp.interval_minutes,
        plant=plant,
        channels=channels,
        min_completeness=th.min_data_completeness,
        import_issues=inp.import_issues,
    )
    stages.append(
        StageStatus(
            key="validation", title="Data validation",
            state={QualityStatus.GOOD: StageState.OK, QualityStatus.DEGRADED: StageState.WARNING,
                   QualityStatus.INSUFFICIENT: StageState.BLOCKED}[quality.status],
            message=quality.summary,
        )
    )

    # 2 ------------------------------------------------------------ baseline
    baseline = resolve_baseline(
        BaselineContext(
            slots=slots, interval_minutes=inp.interval_minutes, plant=plant, channels=channels,
            declared=inp.declared_baseline, request=options.baseline,
        )
    )
    stages.append(
        StageStatus(
            key="baseline", title="Baseline",
            state=StageState.OK if baseline.status is BaselineStatus.OK else StageState.BLOCKED,
            message=(
                f"{baseline.method.value.replace('_', ' ').title()} baseline, {baseline.meta.tag.label}."
                if baseline.status is BaselineStatus.OK
                else " ".join(baseline.limitations)
            ),
        )
    )
    channels[Metric.EXPECTED_ENERGY] = baseline.meta

    # 3 ------------------------------------------------------------ performance gap
    actual_meta = channels.get(Metric.ACTUAL_ENERGY) or ChannelMeta(
        metric=Metric.ACTUAL_ENERGY, tag=UNKNOWN_TAG, unit="kWh"
    )
    gap = compute_gap_series(
        slots, baseline.expected, interval_minutes=inp.interval_minutes,
        expected_meta=baseline.meta, actual_meta=actual_meta, thresholds=th,
    )
    stages.append(
        StageStatus(
            key="gap", title="Performance gap",
            state=StageState.OK if gap.result.status is GapStatus.OK else StageState.BLOCKED,
            message=(
                f"Gap {gap.result.relative_gap_pct:.1f} % over the period, "
                f"{gap.window.result.relative_gap_pct:.1f} % in the assessment window."
                if gap.result.relative_gap_pct is not None and gap.window.result.relative_gap_pct is not None
                else gap.result.message or gap.window.result.message or "The gap could not be computed."
            ),
        )
    )

    # 4 ------------------------------------------------------------ factor attribution and patterns
    device_analysis = analyse_devices(
        inp.device_observations, inp.devices, timezone=zone, period_start=period_start,
        period_end=period_end, thresholds=th, tag=inp.device_tag,
    )
    attribution = attribute_losses(
        slots, baseline, interval_minutes=inp.interval_minutes, plant=plant, channels=channels, thresholds=th,
        device_loss_fraction_by_day=device_analysis.loss_fraction_by_day if device_analysis.evaluable else None,
        device_tag=device_analysis.tag if device_analysis.evaluable else None,
    )
    cleaning_days = [
        local_day(r.observed_start, zone) for r in inp.records if r.evidence_type is EvidenceType.CLEANING_EVENT
    ]
    trend = analyse_trend(attribution.daily, cleaning_days=cleaning_days, thresholds=th)
    intraday = analyse_intraday(slots, attribution, interval_minutes=inp.interval_minutes, plant=plant, thresholds=th)
    not_quantified = [c.factor.value for c in attribution.period.contributions if c.status.value == "NOT_QUANTIFIED"]
    stages.append(
        StageStatus(
            key="attribution", title="Factor attribution",
            state=StageState.WARNING if not_quantified else StageState.OK,
            message=(
                "Not quantified (remain in the residual): " + ", ".join(n.replace("_", " ").lower() for n in not_quantified) + "."
                if not_quantified else "Every factor of the chain was quantified or is covered by the baseline."
            ),
        )
    )

    # 5 ------------------------------------------------------------ diagnostic hypotheses
    diag_inputs = DiagnosticInputs(
        gap=gap, attribution=attribution, trend=trend, devices=device_analysis, intraday=intraday,
        baseline=baseline, channels=channels, records=inp.records, context=inp.context, thresholds=th,
        timezone=zone,
    )
    diagnostics = evaluate_hypotheses(diag_inputs)
    stages.append(
        StageStatus(
            key="diagnostics", title="Diagnostic hypotheses",
            state=StageState.OK if diagnostics.status.value in ("NO_SIGNIFICANT_DEVIATION", "SINGLE_EXPLANATION")
            else StageState.WARNING,
            message=diagnostics.headline,
        )
    )

    # 6 ------------------------------------------------------------ recoverable energy
    recoverable = estimate_recoverable_energy(
        gap=gap, attribution=attribution, soiling=diagnostics.soiling_evidence,
        assumptions=options.cleaning, thresholds=th,
    )
    stages.append(
        StageStatus(
            key="recoverable", title="Recoverable energy",
            state=StageState.OK if recoverable.status.value == "ESTIMATED" else StageState.WARNING,
            message=(
                f"{(recoverable.recoverable.central or 0) / 1000:,.1f} MWh over {recoverable.horizon_days:g} days (central)."
                if recoverable.status.value == "ESTIMATED" and recoverable.horizon_days is not None
                else recoverable.status.value.replace("_", " ").capitalize() + "."
            ),
        )
    )

    # 7 ------------------------------------------------------------ economics
    economics = evaluate_cleaning_economics(
        recoverable, options.economics,
        cleaning_effectiveness=options.cleaning.cleaning_effectiveness if options.cleaning else None,
    )
    stages.append(
        StageStatus(
            key="economics", title="Cleaning economics",
            state=StageState.OK if economics.status.value == "COMPLETE" else StageState.WARNING,
            message=(
                f"{economics.verdict.value.capitalize()}: base net benefit "
                f"{economics.scenarios[1].net_benefit:,.0f} {economics.currency}."
                if economics.status.value == "COMPLETE" and economics.scenarios[1].net_benefit is not None
                else economics.status.value.replace("_", " ").capitalize() + "."
            ),
        )
    )

    # 8 ------------------------------------------------------------ evidence assessment
    evidence = assess_evidence(
        diag_inputs, baseline, diagnostics, recoverable, economics, interval_minutes=inp.interval_minutes
    )
    stages.append(
        StageStatus(
            key="evidence", title="Evidence assessment",
            state=StageState.OK if evidence.quality.value in ("HIGH", "MEDIUM") else StageState.WARNING,
            message=f"Data adequacy {evidence.quality.value}; "
            f"{sum(1 for g in evidence.gates if g.passed is True)} of {len(evidence.gates)} gates passed.",
        )
    )

    # 9 ------------------------------------------------------------ decision
    recommendation = decide(
        assessment=evidence, diagnostics=diagnostics, recoverable=recoverable, economics=economics,
        context=inp.context, plant_is_demonstration=plant.is_demonstration, thresholds=th,
        allow_operational_authorization=inp.allow_operational_authorization,
    )
    stages.append(
        StageStatus(
            key="decision", title="Decision", state=StageState.OK,
            message=f"{recommendation.decision.value} (rule {recommendation.rule}).",
        )
    )

    # 10 ----------------------------------------------------------- explanation
    explanation = build_explanation(
        plant_name=plant.name, gap=gap, baseline=baseline, attribution=attribution, diagnostics=diagnostics,
        assessment=evidence, recoverable=recoverable, economics=economics, recommendation=recommendation,
    )
    stages.append(StageStatus(key="explanation", title="Explanation", state=StageState.OK,
                              message="Assembled deterministically from the engine outputs."))

    provenance = [
        ChannelProvenance(
            metric=metric,
            label=_LABELS[metric],
            provenance=meta.tag.label,
            effective_class=meta.tag.effective_class(inp.context).value,
            source=meta.tag.source,
            method=meta.tag.method,
            unit=meta.unit,
            uncertainty_pct=meta.uncertainty_pct,
            uncertainty_abs=meta.uncertainty_abs,
        )
        for metric, meta in channels.items()
    ]
    if device_analysis.evaluable:
        provenance.append(
            ChannelProvenance(
                metric=Metric.DEVICE_ENERGY, label=_LABELS[Metric.DEVICE_ENERGY],
                provenance=device_analysis.tag.label,
                effective_class=device_analysis.tag.effective_class(inp.context).value,
                source=device_analysis.tag.source, method=device_analysis.tag.method, unit="kWh",
            )
        )

    disclaimers: list[str] = []
    if inp.dataset_disclaimer:
        disclaimers.append(inp.dataset_disclaimer)
    if inp.context is EvaluationContext.DEMONSTRATION:
        disclaimers.append(
            "Demonstration evaluation. Decisions are simulated and are not operational instructions."
        )
    if any(p.provenance.startswith("SYNTHETIC") for p in provenance):
        disclaimers.append(
            "This analysis uses synthetic data. Synthetic values are not measurements and do not describe "
            "the operation of any real plant."
        )
    disclaimers.append(
        "Weather data are context for the analysis. They do not measure dust accumulation on the modules."
    )

    return AnalysisResult(
        generated_at=now or datetime.now(UTC),
        context=inp.context,
        plant=plant,
        dataset_name=inp.dataset_name,
        period_start=period_start,
        period_end=period_end,
        interval_minutes=inp.interval_minutes,
        timezone=plant.timezone,
        thresholds=th,
        stages=stages,
        provenance=provenance,
        quality=quality,
        baseline=baseline,
        gap=gap,
        attribution=attribution,
        trend=trend,
        devices=device_analysis,
        intraday=intraday,
        diagnostics=diagnostics,
        recoverable=recoverable,
        economics=economics,
        evidence=evidence,
        recommendation=recommendation,
        explanation=explanation,
        cleaning_assumptions=options.cleaning,
        economic_inputs=options.economics,
        disclaimers=disclaimers,
    )
