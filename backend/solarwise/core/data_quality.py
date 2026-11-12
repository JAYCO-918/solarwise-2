"""Series-level data quality assessment.

Row-level validation (types, units, ranges, duplicates, time zones) happens at
ingestion.  This module looks at the series as a whole, on the analysis grid:
completeness and gaps per channel, values that are physically impossible for
*this* plant, stuck sensors, production at night, statistical outliers.

Nothing is repaired here.  Suspect values are reported, not altered, and missing
values stay missing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field

from solarwise.core.models import METRIC_SPECS, PLANT_LEVEL_METRICS, ChannelMeta, Metric, PlantSpec
from solarwise.core.solar_geometry import (
    day_of_year,
    daylight_hours,
    extraterrestrial_daily_horizontal_kwh_m2,
)
from solarwise.core.statistics import modified_z_scores
from solarwise.core.timeline import DAILY_MINUTES, Slot

#: Margin allowed above nameplate before energy is called inconsistent with capacity.
CAPACITY_MARGIN = 1.05
#: Peak in-plane irradiance regarded as physically plausible [kW/m2].
MAX_PLAUSIBLE_IRRADIANCE_KW_M2 = 1.5
#: Modified z-score beyond which a daily performance index is listed as an outlier.
OUTLIER_Z = 3.5
#: A soiling ratio up to this value is ordinary measurement scatter around a clean array.
SOILING_RATIO_TOLERANCE = 1.02

#: Channels judged over daylight intervals only.
_DAYLIGHT_METRICS = frozenset(
    {
        Metric.ACTUAL_ENERGY,
        Metric.EXPECTED_ENERGY,
        Metric.BASELINE_IRRADIATION,
        Metric.AVAILABILITY,
        Metric.CURTAILED_ENERGY,
        Metric.SOILING_RATIO,
        Metric.POA_IRRADIATION,
        Metric.GHI,
        Metric.MODULE_TEMP,
    }
)
#: Channels for which a flat line suggests a stuck sensor.
_FLATLINE_METRICS = (Metric.ACTUAL_ENERGY, Metric.POA_IRRADIATION, Metric.GHI, Metric.MODULE_TEMP, Metric.AMBIENT_TEMP)


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class QualityIssue(BaseModel):
    code: str
    severity: Severity
    metric: str | None = None
    message: str
    count: int = 1
    first_day: date | None = None
    last_day: date | None = None


class ChannelQuality(BaseModel):
    metric: Metric
    column: str
    unit: str
    provenance: str
    source: str
    #: Intervals in which the channel is expected (daylight, or all).
    expected_slots: int
    observed_slots: int
    completeness: float | None
    longest_gap_slots: int
    minimum: float | None
    maximum: float | None
    mean: float | None


class QualityStatus(StrEnum):
    GOOD = "GOOD"
    DEGRADED = "DEGRADED"
    INSUFFICIENT = "INSUFFICIENT"


class DataQualityReport(BaseModel):
    status: QualityStatus
    summary: str
    slots_total: int
    daylight_slots: int
    days_total: int
    channels: list[ChannelQuality]
    issues: list[QualityIssue]
    #: Issues recorded when the dataset was imported (rows rejected, values set to missing ...).
    import_issues: list[QualityIssue] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def _span(days: Sequence[date]) -> tuple[date | None, date | None]:
    return (min(days), max(days)) if days else (None, None)


def assess_data_quality(
    slots: Sequence[Slot],
    *,
    interval_minutes: int,
    plant: PlantSpec,
    channels: Mapping[Metric, ChannelMeta],
    min_completeness: float,
    import_issues: Sequence[QualityIssue] = (),
) -> DataQualityReport:
    """Assess completeness and plausibility of every channel on the analysis grid."""
    daily = interval_minutes == DAILY_MINUTES
    interval_h = interval_minutes / 60.0
    issues: list[QualityIssue] = []
    channel_reports: list[ChannelQuality] = []
    daylight_total = sum(1 for s in slots if s.daylight)
    days = sorted({s.day for s in slots})

    def add(code: str, severity: Severity, metric: Metric | None, message: str, where: Sequence[date]) -> None:
        first, last = _span(where)
        issues.append(
            QualityIssue(code=code, severity=severity, metric=metric.value if metric else None,
                         message=message, count=max(1, len(where)), first_day=first, last_day=last)
        )

    # ------------------------------------------------------------------ per channel
    for metric in PLANT_LEVEL_METRICS:
        spec = METRIC_SPECS[metric]
        meta = channels.get(metric)
        values: list[float] = []
        expected_slots = observed = longest = run = 0
        flat_run = 0
        flat_days: list[date] = []
        previous: float | None = None
        flat_limit = 3 if daily else max(4, round(120 / interval_minutes))
        for slot in slots:
            relevant = slot.daylight or metric not in _DAYLIGHT_METRICS
            value = getattr(slot.obs, spec.column) if slot.obs is not None else None
            if value is not None:
                values.append(value)
            if not relevant:
                previous, flat_run = None, 0
                continue
            expected_slots += 1
            if value is None:
                run += 1
                longest = max(longest, run)
                previous, flat_run = None, 0
                continue
            observed += 1
            run = 0
            if metric in _FLATLINE_METRICS:
                if previous is not None and value == previous and value != 0.0:
                    flat_run += 1
                    if flat_run + 1 == flat_limit:
                        flat_days.append(slot.day)
                else:
                    flat_run = 0
                previous = value
        if meta is None and observed == 0:
            continue
        completeness = observed / expected_slots if expected_slots else None
        channel_reports.append(
            ChannelQuality(
                metric=metric,
                column=spec.column,
                unit=spec.unit,
                provenance=meta.tag.label if meta else "UNKNOWN",
                source=meta.tag.source if meta else "origin not declared",
                expected_slots=expected_slots,
                observed_slots=observed,
                completeness=completeness,
                longest_gap_slots=longest,
                minimum=min(values) if values else None,
                maximum=max(values) if values else None,
                mean=sum(values) / len(values) if values else None,
            )
        )
        if metric in (Metric.ACTUAL_ENERGY, Metric.EXPECTED_ENERGY) and completeness is not None:
            if completeness < min_completeness:
                add("LOW_COMPLETENESS", Severity.ERROR, metric,
                    f"{spec.column}: {completeness * 100:.1f} % of daylight intervals have a value "
                    f"(minimum {min_completeness * 100:.0f} %). Missing values are not filled.", [])
            elif completeness < 1.0:
                add("MISSING_VALUES", Severity.INFO, metric,
                    f"{spec.column}: {expected_slots - observed} daylight interval(s) without a value; "
                    "they are left out of the comparison, not filled.", [])
        elif completeness is not None and 0 < completeness < 0.5:
            add("SPARSE_CHANNEL", Severity.INFO, metric,
                f"{spec.column}: present for {completeness * 100:.0f} % of the intervals in which it applies.", [])
        if flat_days:
            cause = (
                "a stuck meter, back-filled data, or output held at a fixed limit (curtailment, inverter clipping)"
                if metric is Metric.ACTUAL_ENERGY
                else "possible stuck sensor or back-filled data"
            )
            add("FLATLINE", Severity.WARNING, metric,
                f"{spec.column}: identical non-zero value repeated {flat_limit}+ times in a row on "
                f"{len(flat_days)} occasion(s) - {cause}.", flat_days)

    if Metric.ACTUAL_ENERGY not in {c.metric for c in channel_reports}:
        add("NO_ACTUAL_ENERGY", Severity.ERROR, Metric.ACTUAL_ENERGY,
            "No actual energy values in the analysed period.", [])

    # ------------------------------------------------------------------ plant-specific plausibility
    capacity = plant.capacity_ac_kw if plant.capacity_ac_kw is not None else plant.capacity_dc_kwp
    capacity_name = "AC capacity" if plant.capacity_ac_kw is not None else "DC capacity"
    over_capacity: list[date] = []
    night_production: list[date] = []
    irradiance_high: list[date] = []
    ghi_above_extraterrestrial: list[date] = []
    module_below_ambient: list[date] = []
    soiling_above_one: list[date] = []
    zero_with_sun: list[date] = []
    for slot in slots:
        obs = slot.obs
        if obs is None:
            continue
        doy = day_of_year(slot.day)
        hours = daylight_hours(plant.latitude, doy) if daily else interval_h
        if obs.actual_energy_kwh is not None:
            if obs.actual_energy_kwh > capacity * hours * CAPACITY_MARGIN:
                over_capacity.append(slot.day)
            if not daily and not slot.daylight and obs.actual_energy_kwh > 0.01 * capacity * interval_h:
                night_production.append(slot.day)
        if obs.poa_irradiation_kwh_m2 is not None:
            limit = MAX_PLAUSIBLE_IRRADIANCE_KW_M2 * hours
            if obs.poa_irradiation_kwh_m2 > limit:
                irradiance_high.append(slot.day)
            if (
                slot.daylight
                and obs.actual_energy_kwh == 0.0
                and obs.poa_irradiation_kwh_m2 > 0.2 * hours * (0.3 if daily else 1.0)
            ):
                zero_with_sun.append(slot.day)
        if daily and obs.ghi_kwh_m2 is not None and obs.ghi_kwh_m2 > extraterrestrial_daily_horizontal_kwh_m2(plant.latitude, doy):
            ghi_above_extraterrestrial.append(slot.day)
        if (
            slot.daylight
            and obs.module_temp_c is not None
            and obs.ambient_temp_c is not None
            and obs.module_temp_c < obs.ambient_temp_c - 5.0
        ):
            module_below_ambient.append(slot.day)
        if obs.soiling_ratio is not None and obs.soiling_ratio > SOILING_RATIO_TOLERANCE:
            soiling_above_one.append(slot.day)

    if over_capacity:
        add("ENERGY_EXCEEDS_CAPACITY", Severity.ERROR, Metric.ACTUAL_ENERGY,
            f"Actual energy exceeds what the configured {capacity_name} ({capacity:,.0f} kW) can deliver in the "
            f"interval on {len(over_capacity)} occasion(s): the capacity, the unit or the interval is inconsistent.",
            over_capacity)
    if night_production:
        add("PRODUCTION_AT_NIGHT", Severity.WARNING, Metric.ACTUAL_ENERGY,
            f"Energy recorded while the sun is below the horizon on {len(night_production)} interval(s): "
            "check the time zone and timestamp convention of the dataset.", night_production)
    if irradiance_high:
        add("IRRADIANCE_IMPLAUSIBLE", Severity.WARNING, Metric.POA_IRRADIATION,
            f"In-plane irradiation above {MAX_PLAUSIBLE_IRRADIANCE_KW_M2:g} kW/m2 average on "
            f"{len(irradiance_high)} interval(s): check the unit and the sensor.", irradiance_high)
    if ghi_above_extraterrestrial:
        add("GHI_ABOVE_EXTRATERRESTRIAL", Severity.ERROR, Metric.GHI,
            f"Daily global horizontal irradiation exceeds the extraterrestrial value on "
            f"{len(ghi_above_extraterrestrial)} day(s), which is physically impossible: check unit, "
            "location and sensor.", ghi_above_extraterrestrial)
    if module_below_ambient:
        add("MODULE_TEMP_BELOW_AMBIENT", Severity.WARNING, Metric.MODULE_TEMP,
            f"Module temperature more than 5 degC below ambient in daylight on {len(module_below_ambient)} "
            "interval(s): one of the two sensors is suspect.", module_below_ambient)
    if soiling_above_one:
        add("SOILING_RATIO_ABOVE_ONE", Severity.WARNING, Metric.SOILING_RATIO,
            f"Soiling ratio above {SOILING_RATIO_TOLERANCE:g} on {len(soiling_above_one)} interval(s): the 'clean' "
            "reference device may be dirtier than the soiled one. Such values are treated as 'no soiling loss'.",
            soiling_above_one)
    if zero_with_sun:
        add("ZERO_PRODUCTION_WITH_IRRADIANCE", Severity.INFO, Metric.ACTUAL_ENERGY,
            f"Zero production while irradiance was recorded on {len(zero_with_sun)} interval(s): an outage, "
            "or a telemetry gap stored as zero.", zero_with_sun)

    # ------------------------------------------------------------------ outliers of the daily performance index
    per_day: dict[date, list[float]] = {}
    for slot in slots:
        obs = slot.obs
        if obs is None or obs.actual_energy_kwh is None or obs.expected_energy_kwh is None:
            continue
        acc = per_day.setdefault(slot.day, [0.0, 0.0])
        acc[0] += obs.actual_energy_kwh
        acc[1] += obs.expected_energy_kwh
    pi_days = [d for d in sorted(per_day) if per_day[d][1] > 0]
    if len(pi_days) >= 8:
        scores = modified_z_scores([per_day[d][0] / per_day[d][1] for d in pi_days])
        outliers = [d for d, z in zip(pi_days, scores, strict=True) if z is not None and abs(z) > OUTLIER_Z]
        if outliers:
            add("PERFORMANCE_INDEX_OUTLIER", Severity.INFO, None,
                f"{len(outliers)} day(s) have a performance index far from the period median "
                f"(modified z-score beyond {OUTLIER_Z:g}). They are kept; nothing is removed automatically.",
                outliers)

    # ------------------------------------------------------------------ provenance
    undeclared = [m.value for m in PLANT_LEVEL_METRICS if m in channels and channels[m].tag.provenance.value == "UNKNOWN"]
    if undeclared:
        add("PROVENANCE_NOT_DECLARED", Severity.WARNING, None,
            "Provenance not declared for: " + ", ".join(undeclared) + ". These channels are treated as UNKNOWN "
            "and cannot serve as measured evidence.", [])

    errors = [i for i in issues if i.severity is Severity.ERROR]
    warnings = [i for i in issues if i.severity is Severity.WARNING]
    if errors:
        status = QualityStatus.INSUFFICIENT
        summary = f"{len(errors)} blocking issue(s): " + "; ".join(i.code for i in errors) + "."
    elif warnings:
        status = QualityStatus.DEGRADED
        summary = f"Usable with {len(warnings)} warning(s): " + "; ".join(i.code for i in warnings) + "."
    else:
        status = QualityStatus.GOOD
        summary = "No blocking issue or warning on the analysed period."

    return DataQualityReport(
        status=status,
        summary=summary,
        slots_total=len(slots),
        daylight_slots=daylight_total,
        days_total=len(days),
        channels=channel_reports,
        issues=issues,
        import_issues=list(import_issues),
        notes=[
            "Missing values are never replaced by zero or interpolated.",
            "Suspect values are reported and left unchanged.",
        ],
    )
