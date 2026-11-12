"""Intraday signatures (sub-daily data only).

Two loss mechanisms leave a mark on the *shape of the day* that daily totals
cannot show:

Shading
    Losses concentrated near sunrise or sunset while midday is unaffected,
    repeating day after day.  A one-sided pattern points at a fixed obstruction.

Curtailment
    Output held flat at a level below what the plant could deliver while the
    expected output keeps rising above it (a plateau).

Both are pattern-based *proxies*.  They make a hypothesis plausible; they do not
identify the cause.  Near-horizon intervals are also where baselines are least
accurate, which is why a persistent, sizeable excess is required.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date

from pydantic import BaseModel, Field

from solarwise.core.attribution import LossAttribution
from solarwise.core.models import AnalysisThresholds, PlantSpec
from solarwise.core.solar_geometry import day_of_year, sunset_hour_angle_rad
from solarwise.core.timeline import DAILY_MINUTES, Slot

#: Output within this share of the daily maximum counts as "on the plateau".
PLATEAU_BAND = 0.97
#: On a plateau the actual/expected ratio must be lower than the day's typical ratio by this factor.
PLATEAU_HEADROOM = 1.05
#: Shortest plateau considered [minutes].
PLATEAU_MIN_MINUTES = 120
#: A plateau at or above this share of AC capacity is inverter clipping, not curtailment.
CLIPPING_LEVEL = 0.97
#: Fewest evaluated days for a shading pattern to be called persistent.
MIN_DAYS = 5


class HourProfile(BaseModel):
    solar_hour: int
    expected_kwh: float
    actual_kwh: float
    loss_pct: float | None


class IntradayAnalysis(BaseModel):
    evaluable: bool
    reason: str | None = None
    days_evaluated: int = 0
    # --- shading signature
    loss_morning_pct: float | None = None
    loss_midday_pct: float | None = None
    loss_evening_pct: float | None = None
    edge_side: str | None = None  # MORNING | EVENING
    edge_excess_pct: float | None = None
    asymmetry_pct: float | None = None
    days_with_edge_excess: int = 0
    shading_signature: bool = False
    #: Loss in the affected part of the day beyond what the midday loss fraction explains.
    shading_excess_loss_kwh: float | None = None
    # --- curtailment signature
    plateau_days: int = 0
    plateau_day_list: list[date] = Field(default_factory=list)
    plateau_level_of_ac: float | None = None
    plateau_excess_loss_kwh: float | None = None
    plateau_signature: bool = False
    clipping_days: int = 0
    profile: list[HourProfile] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def _loss_pct(expected: float, actual: float) -> float | None:
    if expected <= 0:
        return None
    return (expected - actual) / expected * 100.0


def analyse_intraday(
    slots: Sequence[Slot],
    attribution: LossAttribution,
    *,
    interval_minutes: int,
    plant: PlantSpec,
    thresholds: AnalysisThresholds,
) -> IntradayAnalysis:
    """Look for shading and curtailment signatures in sub-daily data."""
    if interval_minutes == DAILY_MINUTES:
        return IntradayAnalysis(
            evaluable=False,
            reason="daily data carry no intraday profile; shading and curtailment signatures cannot be assessed",
        )
    pre_soiling = attribution.slot_pre_soiling
    pre_curtailment = attribution.slot_pre_curtailment
    outage = attribution.slot_outage
    if not (len(slots) == len(pre_soiling) == len(pre_curtailment) == len(outage)):
        raise ValueError("attribution is not aligned with the slot grid")

    interval_h = interval_minutes / 60.0
    ac_per_slot = plant.capacity_ac_kw * interval_h if plant.capacity_ac_kw is not None else None

    parts = ("MORNING", "MIDDAY", "EVENING")
    total_exp = dict.fromkeys(parts, 0.0)
    total_act = dict.fromkeys(parts, 0.0)
    day_exp: dict[date, dict[str, float]] = {}
    day_act: dict[date, dict[str, float]] = {}
    hours: dict[int, list[float]] = {}
    # per day: list of (expected before curtailment, actual) for daylight matched slots, in time order
    day_series: dict[date, list[tuple[float, float]]] = {}

    for slot, e_soil, e_curt, is_out in zip(slots, pre_soiling, pre_curtailment, outage, strict=True):
        if e_soil is None or e_curt is None or slot.obs is None or not slot.daylight or slot.hour_angle is None:
            continue
        actual = slot.obs.actual_energy_kwh
        if actual is None:
            continue
        day_series.setdefault(slot.day, []).append((e_curt, actual))
        if is_out:
            continue
        ws = sunset_hour_angle_rad(plant.latitude, day_of_year(slot.day))
        if ws <= 0:
            continue
        u = slot.hour_angle / ws
        part = "MORNING" if u < -1.0 / 3.0 else "EVENING" if u > 1.0 / 3.0 else "MIDDAY"
        total_exp[part] += e_soil
        total_act[part] += actual
        de = day_exp.setdefault(slot.day, dict.fromkeys(parts, 0.0))
        da = day_act.setdefault(slot.day, dict.fromkeys(parts, 0.0))
        de[part] += e_soil
        da[part] += actual
        solar_hour = math.floor(12.0 + slot.hour_angle * 12.0 / math.pi)
        bucket = hours.setdefault(solar_hour, [0.0, 0.0])
        bucket[0] += e_soil
        bucket[1] += actual

    days_evaluated = len(day_exp)
    if days_evaluated == 0 or sum(total_exp.values()) <= 0:
        return IntradayAnalysis(evaluable=False, reason="no matched daylight intervals to analyse")

    result = IntradayAnalysis(evaluable=True, days_evaluated=days_evaluated)
    result.profile = [
        HourProfile(solar_hour=h, expected_kwh=v[0], actual_kwh=v[1], loss_pct=_loss_pct(v[0], v[1]))
        for h, v in sorted(hours.items())
    ]

    # ------------------------------------------------------------------ shading
    loss = {p: _loss_pct(total_exp[p], total_act[p]) for p in parts}
    result.loss_morning_pct = loss["MORNING"]
    result.loss_midday_pct = loss["MIDDAY"]
    result.loss_evening_pct = loss["EVENING"]
    midday = loss["MIDDAY"]
    grand_total = sum(total_exp.values())
    if midday is not None:
        candidates = [
            (p, loss[p] - midday)  # type: ignore[operator]
            for p in ("MORNING", "EVENING")
            if loss[p] is not None and total_exp[p] >= 0.03 * grand_total
        ]
        if candidates:
            side, excess = max(candidates, key=lambda c: c[1])
            result.edge_side = side
            result.edge_excess_pct = excess
            if loss["MORNING"] is not None and loss["EVENING"] is not None:
                result.asymmetry_pct = abs(loss["MORNING"] - loss["EVENING"])
            persistent_days = 0
            for day, de in day_exp.items():
                da = day_act[day]
                edge_loss = _loss_pct(de[side], da[side])
                mid_loss = _loss_pct(de["MIDDAY"], da["MIDDAY"])
                if (
                    edge_loss is not None
                    and mid_loss is not None
                    and edge_loss - mid_loss >= thresholds.shading_edge_excess_pct / 2.0
                ):
                    persistent_days += 1
            result.days_with_edge_excess = persistent_days
            result.shading_signature = (
                excess >= thresholds.shading_edge_excess_pct
                and days_evaluated >= MIN_DAYS
                and persistent_days >= 0.6 * days_evaluated
            )
            if result.shading_signature:
                result.shading_excess_loss_kwh = max(
                    0.0, (total_exp[side] - total_act[side]) - midday / 100.0 * total_exp[side]
                )

    # ------------------------------------------------------------------ curtailment plateau
    # A soiled or derated plant also produces less than expected around noon, but its
    # actual/expected ratio is the same all day.  A plateau is therefore only accepted
    # where the ratio falls clearly below the day's own typical (upper-quartile) ratio.
    min_run = max(2, math.ceil(PLATEAU_MIN_MINUTES / interval_minutes))
    plateau_days: list[date] = []
    levels: list[float] = []
    excess_loss = 0.0
    clipping_days = 0
    for day, series in sorted(day_series.items()):
        peak = max(actual for _, actual in series)
        peak_expected = max(e_curt for e_curt, _ in series)
        if peak <= 0 or peak_expected <= 0:
            continue
        ratios = sorted(actual / e_curt for e_curt, actual in series if e_curt >= 0.10 * peak_expected)
        if len(ratios) < 4:
            continue
        typical = ratios[min(len(ratios) - 1, round(0.75 * (len(ratios) - 1)))]
        best_run: list[tuple[float, float]] = []
        run: list[tuple[float, float]] = []
        for e_curt, actual in series:
            on_plateau = (
                e_curt >= 0.10 * peak_expected
                and actual >= PLATEAU_BAND * peak
                and actual / e_curt <= typical / PLATEAU_HEADROOM
            )
            if on_plateau:
                run.append((e_curt, actual))
            else:
                if len(run) > len(best_run):
                    best_run = run
                run = []
        if len(run) > len(best_run):
            best_run = run
        if len(best_run) < min_run:
            continue
        level = peak / ac_per_slot if ac_per_slot else None
        if level is not None and level >= CLIPPING_LEVEL:
            clipping_days += 1
            continue
        plateau_days.append(day)
        if level is not None:
            levels.append(level)
        excess_loss += sum(max(0.0, typical * e_curt - actual) for e_curt, actual in best_run)

    result.plateau_days = len(plateau_days)
    result.plateau_day_list = plateau_days
    result.plateau_signature = bool(plateau_days)
    result.clipping_days = clipping_days
    if plateau_days:
        result.plateau_excess_loss_kwh = excess_loss
        if levels:
            levels.sort()
            result.plateau_level_of_ac = levels[len(levels) // 2]
    if clipping_days:
        result.notes.append(
            f"On {clipping_days} day(s) output was flat at the AC rating: this is inverter clipping, a design "
            "property the baseline should already include, not curtailment."
        )
    result.notes.append(
        "Intraday signatures are pattern-based proxies. Baselines are least accurate near sunrise and "
        "sunset, so only persistent, sizeable excess losses are reported."
    )
    return result
