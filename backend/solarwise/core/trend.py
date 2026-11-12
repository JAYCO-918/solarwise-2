"""Shape of the performance index over time.

The *shape* of a loss says something about its cause, but never proves it:

* a slow, steady decline during a dry spell is what soiling accumulation looks
  like - and also what vegetation growth or a drifting sensor look like;
* an abrupt, lasting drop is what an equipment fault looks like - and also what
  a dust storm looks like;
* a recovery right after rain or a cleaning is what the removal of soiling
  looks like.

This module only describes the shape.  The diagnostic engine weighs it together
with direct evidence, and always treats it as indirect.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date

from pydantic import BaseModel, Field

from solarwise.core.attribution import DailyAttribution
from solarwise.core.models import AnalysisThresholds
from solarwise.core.statistics import detect_largest_drop, finite_median, theil_sen

#: Fewest valid days for a trend estimate.
MIN_TREND_DAYS = 10


class ResetEvent(BaseModel):
    day: date
    kind: str  # RAIN | CLEANING
    #: Change of the median performance index from the 3 days before to the 3 days after [% points].
    recovery_pct: float | None = None
    detail: str | None = None


class StepFinding(BaseModel):
    day: date
    before_pct: float
    after_pct: float
    drop_pct: float
    noise_sigma_pct: float | None
    material: bool


class TrendAnalysis(BaseModel):
    evaluable: bool
    reason: str | None = None
    valid_days: int = 0
    precipitation_known: bool = False
    #: Day from which the current accumulation spell is counted.
    spell_start: date | None = None
    spell_started_by: str | None = None  # PERIOD_START | RAIN | CLEANING
    spell_days: int | None = None
    #: Theil-Sen slope of the performance index over the spell [% points per day].
    slope_pct_per_day: float | None = None
    slope_low_pct_per_day: float | None = None
    slope_high_pct_per_day: float | None = None
    confidence_level: float | None = None
    #: The whole confidence interval is below zero.
    declining: bool | None = None
    trend_points: int = 0
    step: StepFinding | None = None
    reset_events: list[ResetEvent] = Field(default_factory=list)
    method: str = (
        "Theil-Sen slope with Sen's confidence interval on the daily performance index "
        "(actual / pre-soiling expected), over the current dry spell."
    )


def analyse_trend(
    daily: Sequence[DailyAttribution],
    *,
    cleaning_days: Sequence[date],
    thresholds: AnalysisThresholds,
) -> TrendAnalysis:
    """Describe drift, level shifts and post-reset recoveries of the performance index."""
    if not daily:
        return TrendAnalysis(evaluable=False, reason="no daily data")

    days = [d.day for d in daily]
    index = [d.performance_index * 100.0 if d.performance_index is not None else math.nan for d in daily]
    valid = sum(1 for v in index if math.isfinite(v))
    precipitation_known = any(d.precipitation_mm is not None for d in daily)

    # ---- reset events (rain above the cleaning threshold, documented cleanings)
    period_start, period_end = days[0], days[-1]
    events: list[ResetEvent] = []
    for d in daily:
        if d.precipitation_mm is not None and d.precipitation_mm >= thresholds.rain_cleaning_threshold_mm:
            events.append(ResetEvent(day=d.day, kind="RAIN", detail=f"{d.precipitation_mm:.1f} mm"))
    for day in sorted(set(cleaning_days)):
        if period_start <= day <= period_end:
            events.append(ResetEvent(day=day, kind="CLEANING"))
    events.sort(key=lambda e: e.day)

    position = {day: i for i, day in enumerate(days)}
    measured_events: list[ResetEvent] = []
    for event in events:
        i = position.get(event.day)
        recovery: float | None = None
        if i is not None:
            before = finite_median(index[max(0, i - 3) : i])
            after = finite_median(index[i + 1 : i + 4])
            if before is not None and after is not None:
                recovery = after - before
        measured_events.append(event.model_copy(update={"recovery_pct": recovery}))

    if valid < MIN_TREND_DAYS:
        return TrendAnalysis(
            evaluable=False,
            reason=f"only {valid} day(s) with a performance index; at least {MIN_TREND_DAYS} are needed",
            valid_days=valid,
            precipitation_known=precipitation_known,
            reset_events=measured_events,
        )

    # ---- current accumulation spell
    if measured_events:
        last = measured_events[-1]
        spell_start_idx = min(position[last.day] + 1, len(days) - 1)
        started_by = last.kind
    else:
        spell_start_idx = 0
        started_by = "PERIOD_START"
    spell_start = days[spell_start_idx]
    spell_days = (period_end - spell_start).days + 1

    xs = [float(i) for i in range(spell_start_idx, len(days))]
    ys = index[spell_start_idx:]
    fit = theil_sen(xs, ys, confidence_level=0.95, min_points=MIN_TREND_DAYS)

    # ---- largest level shift over the whole period
    step: StepFinding | None = None
    shift = detect_largest_drop(index, window=5, min_valid=3)
    if shift is not None and shift.drop > 0:
        noise = shift.noise_sigma
        material = shift.drop >= thresholds.step_change_min_drop_pct and (noise is None or shift.drop >= 3.0 * noise)
        step = StepFinding(
            day=days[shift.index],
            before_pct=shift.before,
            after_pct=shift.after,
            drop_pct=shift.drop,
            noise_sigma_pct=noise,
            material=material,
        )

    return TrendAnalysis(
        evaluable=True,
        valid_days=valid,
        precipitation_known=precipitation_known,
        spell_start=spell_start,
        spell_started_by=started_by,
        spell_days=spell_days,
        slope_pct_per_day=fit.slope if fit else None,
        slope_low_pct_per_day=fit.slope_low if fit else None,
        slope_high_pct_per_day=fit.slope_high if fit else None,
        confidence_level=fit.confidence_level if fit else None,
        declining=fit.slope_is_negative if fit else None,
        trend_points=fit.n_points if fit else 0,
        step=step,
        reset_events=measured_events,
    )
