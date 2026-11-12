"""Performance gap engine.

    gap_kwh              = expected_energy_kwh - actual_energy_kwh
    relative_gap_percent = gap_kwh / expected_energy_kwh * 100

The gap is only ever computed over intervals for which **both** an expected
and an actual value exist (pairwise matching).  A missing measurement is never
replaced by zero: it removes the interval from the comparison and lowers the
reported coverage.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date, timedelta
from enum import StrEnum

from pydantic import BaseModel

from solarwise.core.models import AnalysisThresholds, ChannelMeta, MeteringBoundary
from solarwise.core.provenance import Traced, derive
from solarwise.core.timeline import Slot
from solarwise.core.units import UnitError, to_canonical


class GapStatus(StrEnum):
    OK = "OK"
    #: Expected energy is zero: the absolute gap exists, the relative gap does not.
    ZERO_EXPECTED = "ZERO_EXPECTED"
    MISSING_INPUT = "MISSING_INPUT"
    #: Negative or non-finite energy.
    INVALID_INPUT = "INVALID_INPUT"
    INVALID_UNIT = "INVALID_UNIT"


class GapResult(BaseModel):
    status: GapStatus
    expected_kwh: float | None = None
    actual_kwh: float | None = None
    gap_kwh: float | None = None
    relative_gap_pct: float | None = None
    message: str | None = None


def compute_gap(expected_kwh: float | None, actual_kwh: float | None) -> GapResult:
    """Energy gap between an expected and an actual value, both in kWh."""
    if expected_kwh is None or actual_kwh is None:
        missing = "expected" if expected_kwh is None else "actual"
        if expected_kwh is None and actual_kwh is None:
            missing = "expected and actual"
        return GapResult(
            status=GapStatus.MISSING_INPUT,
            expected_kwh=expected_kwh,
            actual_kwh=actual_kwh,
            message=f"{missing} energy is missing; the gap is undefined (missing is not zero)",
        )
    if not (math.isfinite(expected_kwh) and math.isfinite(actual_kwh)):
        return GapResult(status=GapStatus.INVALID_INPUT, message="non-finite energy value")
    if expected_kwh < 0 or actual_kwh < 0:
        return GapResult(
            status=GapStatus.INVALID_INPUT,
            expected_kwh=expected_kwh,
            actual_kwh=actual_kwh,
            message="energy values must be non-negative",
        )
    gap = expected_kwh - actual_kwh
    if expected_kwh == 0:
        return GapResult(
            status=GapStatus.ZERO_EXPECTED,
            expected_kwh=0.0,
            actual_kwh=actual_kwh,
            gap_kwh=gap,
            relative_gap_pct=None,
            message="expected energy is zero; the relative gap is undefined",
        )
    return GapResult(
        status=GapStatus.OK,
        expected_kwh=expected_kwh,
        actual_kwh=actual_kwh,
        gap_kwh=gap,
        relative_gap_pct=gap / expected_kwh * 100.0,
    )


def compute_gap_with_units(
    expected: float | None, expected_unit: str, actual: float | None, actual_unit: str
) -> GapResult:
    """As :func:`compute_gap`, converting both operands to kWh first."""
    try:
        exp_kwh = None if expected is None else to_canonical(expected, expected_unit, expected_dimension="energy")
        act_kwh = None if actual is None else to_canonical(actual, actual_unit, expected_dimension="energy")
    except UnitError as exc:
        return GapResult(status=GapStatus.INVALID_UNIT, message=str(exc))
    return compute_gap(exp_kwh, act_kwh)


# --------------------------------------------------------------------------- series


class GapDirection(StrEnum):
    UNDERPERFORMANCE = "UNDERPERFORMANCE"
    OVERPERFORMANCE = "OVERPERFORMANCE"
    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"
    UNDETERMINED = "UNDETERMINED"


class Significance(BaseModel):
    """Is the gap large enough to act upon?

    ``material``         |gap| reaches the engineering materiality threshold.
    ``distinguishable``  |gap| exceeds k times the combined standard
                         uncertainty of baseline and metering.  ``None`` when
                         those uncertainties were not declared.
    ``significant``      material and not contradicted by the uncertainty test.
    """

    direction: GapDirection
    material: bool | None
    distinguishable: bool | None
    significant: bool | None
    threshold_pct: float | None
    combined_std_uncertainty_pct: float | None
    basis: str
    note: str


class CoverageStats(BaseModel):
    daylight_slots: int
    matched_daylight_slots: int
    fraction: float | None
    days_total: int
    days_with_data: int
    days_complete: int
    missing_actual_slots: int
    missing_expected_slots: int


class DailyGap(BaseModel):
    day: date
    expected_kwh: float | None
    actual_kwh: float | None
    gap_kwh: float | None
    relative_gap_pct: float | None
    performance_index: float | None
    coverage: float
    status: str  # OK | PARTIAL | MISSING | ZERO_EXPECTED


class GapWindow(BaseModel):
    start: date
    end: date
    result: GapResult
    coverage: CoverageStats
    significance: Significance


class GapSeries(BaseModel):
    period_start: date
    period_end: date
    interval_minutes: int
    result: GapResult
    expected: Traced
    actual: Traced
    gap: Traced
    coverage: CoverageStats
    significance: Significance
    window: GapWindow
    daily: list[DailyGap]
    limitations: list[str]


def assess_significance(
    result: GapResult,
    expected_uncertainty_pct: float | None,
    actual_uncertainty_pct: float | None,
    thresholds: AnalysisThresholds,
) -> Significance:
    """Compare a gap with the materiality threshold and the declared uncertainties.

    With standard uncertainties ``u_E`` and ``u_A`` (relative, one sigma) of the
    expected and actual energy, and assuming independence,

        u(gap) / E = sqrt(u_E^2 + (u_A * A / E)^2)

    The gap is *distinguishable* from zero when ``|gap| / E > k * u(gap) / E``.
    """
    if result.status is not GapStatus.OK or result.relative_gap_pct is None:
        return Significance(
            direction=GapDirection.UNDETERMINED,
            material=None,
            distinguishable=None,
            significant=None,
            threshold_pct=None,
            combined_std_uncertainty_pct=None,
            basis="NOT_COMPUTABLE",
            note=result.message or "the relative gap could not be computed",
        )
    rel = result.relative_gap_pct
    material = abs(rel) >= thresholds.gap_materiality_pct

    combined: float | None = None
    if expected_uncertainty_pct is not None and actual_uncertainty_pct is not None:
        assert result.expected_kwh and result.actual_kwh is not None  # status OK
        ratio = result.actual_kwh / result.expected_kwh
        combined = math.sqrt(expected_uncertainty_pct**2 + (actual_uncertainty_pct * ratio) ** 2)

    if combined is None:
        distinguishable: bool | None = None
        threshold = thresholds.gap_materiality_pct
        basis = "MATERIALITY_ONLY"
        missing = [
            name
            for name, value in (("baseline", expected_uncertainty_pct), ("metering", actual_uncertainty_pct))
            if value is None
        ]
        note = (
            f"{' and '.join(missing)} uncertainty not declared: the gap is judged against the "
            f"{thresholds.gap_materiality_pct:g} % materiality threshold only"
        )
    else:
        limit = thresholds.coverage_factor * combined
        distinguishable = abs(rel) > limit
        threshold = max(thresholds.gap_materiality_pct, limit)
        basis = "UNCERTAINTY_AND_MATERIALITY"
        note = (
            f"combined standard uncertainty {combined:.2f} % (k = {thresholds.coverage_factor:g} "
            f"-> {limit:.2f} %); materiality threshold {thresholds.gap_materiality_pct:g} %"
        )

    significant = material and distinguishable is not False
    if not significant:
        direction = GapDirection.WITHIN_TOLERANCE
    elif rel > 0:
        direction = GapDirection.UNDERPERFORMANCE
    else:
        direction = GapDirection.OVERPERFORMANCE
    return Significance(
        direction=direction,
        material=material,
        distinguishable=distinguishable,
        significant=significant,
        threshold_pct=threshold,
        combined_std_uncertainty_pct=combined,
        basis=basis,
        note=note,
    )


class _Accumulator:
    __slots__ = (
        "actual", "daylight", "expected", "matched_any", "matched_daylight",
        "missing_actual", "missing_expected",
    )

    def __init__(self) -> None:
        self.expected = 0.0
        self.actual = 0.0
        self.matched_any = 0
        self.daylight = 0
        self.matched_daylight = 0
        self.missing_actual = 0
        self.missing_expected = 0

    def add(self, slot: Slot, expected: float | None) -> None:
        actual = slot.obs.actual_energy_kwh if slot.obs is not None else None
        matched = expected is not None and actual is not None
        if slot.daylight:
            self.daylight += 1
            if matched:
                self.matched_daylight += 1
            if actual is None:
                self.missing_actual += 1
            if expected is None:
                self.missing_expected += 1
        if matched:
            assert expected is not None and actual is not None
            self.expected += expected
            self.actual += actual
            self.matched_any += 1

    def result(self) -> GapResult:
        if self.matched_any == 0:
            return GapResult(
                status=GapStatus.MISSING_INPUT,
                message="no interval has both an expected and an actual value",
            )
        return compute_gap(self.expected, self.actual)

    @property
    def coverage(self) -> float | None:
        if self.daylight == 0:
            return None
        return self.matched_daylight / self.daylight


def _coverage_stats(total: _Accumulator, per_day: dict[date, _Accumulator]) -> CoverageStats:
    return CoverageStats(
        daylight_slots=total.daylight,
        matched_daylight_slots=total.matched_daylight,
        fraction=total.coverage,
        days_total=len(per_day),
        days_with_data=sum(1 for a in per_day.values() if a.matched_daylight > 0),
        days_complete=sum(1 for a in per_day.values() if a.daylight > 0 and a.matched_daylight == a.daylight),
        missing_actual_slots=total.missing_actual,
        missing_expected_slots=total.missing_expected,
    )


def compute_gap_series(
    slots: Sequence[Slot],
    expected: Sequence[float | None],
    *,
    interval_minutes: int,
    expected_meta: ChannelMeta,
    actual_meta: ChannelMeta,
    thresholds: AnalysisThresholds,
) -> GapSeries:
    """Gap over a regular grid of slots, with daily breakdown and coverage."""
    if len(slots) != len(expected):
        raise ValueError("expected series is not aligned with the slot grid")
    if not slots:
        raise ValueError("empty analysis period")

    period_start, period_end = slots[0].day, slots[-1].day
    window_start = max(period_start, period_end - timedelta(days=thresholds.assessment_window_days - 1))

    total = _Accumulator()
    window = _Accumulator()
    per_day: dict[date, _Accumulator] = {}
    for slot, exp in zip(slots, expected, strict=True):
        acc = per_day.setdefault(slot.day, _Accumulator())
        acc.add(slot, exp)
        total.add(slot, exp)
        if slot.day >= window_start:
            window.add(slot, exp)

    daily: list[DailyGap] = []
    for day in sorted(per_day):
        acc = per_day[day]
        day_coverage = acc.coverage or 0.0
        if acc.matched_any == 0:
            daily.append(
                DailyGap(day=day, expected_kwh=None, actual_kwh=None, gap_kwh=None,
                         relative_gap_pct=None, performance_index=None, coverage=0.0, status="MISSING")
            )
            continue
        res = compute_gap(acc.expected, acc.actual)
        if res.status is GapStatus.ZERO_EXPECTED:
            status = "ZERO_EXPECTED"
        elif acc.daylight > 0 and acc.matched_daylight < acc.daylight:
            status = "PARTIAL"
        else:
            status = "OK"
        daily.append(
            DailyGap(
                day=day,
                expected_kwh=res.expected_kwh,
                actual_kwh=res.actual_kwh,
                gap_kwh=res.gap_kwh,
                relative_gap_pct=res.relative_gap_pct,
                performance_index=(
                    res.actual_kwh / res.expected_kwh
                    if res.expected_kwh and res.actual_kwh is not None
                    else None
                ),
                coverage=day_coverage,
                status=status,
            )
        )

    result = total.result()
    window_result = window.result()
    window_days = {d: a for d, a in per_day.items() if d >= window_start}

    gap_tag = derive(
        [expected_meta.tag, actual_meta.tag],
        source="SolarWise gap engine",
        method="expected - actual, summed over intervals where both exist",
    )

    limitations: list[str] = []
    exp_boundary = expected_meta.boundary or MeteringBoundary.UNKNOWN
    act_boundary = actual_meta.boundary or MeteringBoundary.UNKNOWN
    if MeteringBoundary.UNKNOWN in (exp_boundary, act_boundary):
        undeclared = [
            name
            for name, b in (("expected", exp_boundary), ("actual", act_boundary))
            if b is MeteringBoundary.UNKNOWN
        ]
        limitations.append(
            f"Metering boundary not declared for {' and '.join(undeclared)} energy: it cannot be "
            "confirmed that both refer to the same point of the plant."
        )
    elif exp_boundary is not act_boundary:
        limitations.append(
            f"Expected energy refers to {exp_boundary.value} while actual energy refers to "
            f"{act_boundary.value}: losses between these two points are included in the gap."
        )
    coverage_stats = _coverage_stats(total, per_day)
    if coverage_stats.fraction is not None and coverage_stats.fraction < thresholds.min_data_completeness:
        limitations.append(
            f"Only {coverage_stats.fraction * 100:.1f} % of daylight intervals have both expected and actual "
            f"data (minimum for a reliable gap: {thresholds.min_data_completeness * 100:.0f} %). "
            "Missing intervals were excluded, not treated as zero production."
        )

    return GapSeries(
        period_start=period_start,
        period_end=period_end,
        interval_minutes=interval_minutes,
        result=result,
        expected=Traced(value=result.expected_kwh, unit="kWh", tag=expected_meta.tag, basis="BASELINE"),
        actual=Traced(value=result.actual_kwh, unit="kWh", tag=actual_meta.tag, basis="OBSERVATION"),
        gap=Traced(value=result.gap_kwh, unit="kWh", tag=gap_tag, basis="CALCULATED"),
        coverage=coverage_stats,
        significance=assess_significance(
            result, expected_meta.uncertainty_pct, actual_meta.uncertainty_pct, thresholds
        ),
        window=GapWindow(
            start=window_start,
            end=period_end,
            result=window_result,
            coverage=_coverage_stats(window, window_days),
            significance=assess_significance(
                window_result, expected_meta.uncertainty_pct, actual_meta.uncertainty_pct, thresholds
            ),
        ),
        daily=daily,
        limitations=limitations,
    )
