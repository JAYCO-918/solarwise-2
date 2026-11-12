"""Regular time grid for an analysis period.

The gap engine never looks only at the rows that happen to exist.  It lays out
the full grid of intervals the period *should* contain and matches
observations onto it, so that missing records are counted as missing instead
of vanishing from the statistics.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from solarwise.core.models import Observation
from solarwise.core.solar_geometry import hour_angle_rad, sun_elevation_deg

DAILY_MINUTES = 1440
SUPPORTED_INTERVALS: tuple[int, ...] = (15, 30, 60, DAILY_MINUTES)


class TimelineError(ValueError):
    pass


def get_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise TimelineError(f"unknown time zone '{name}'") from exc


def local_midnight_utc(day: date, zone: ZoneInfo) -> datetime:
    """UTC instant at which the local calendar day ``day`` begins."""
    return datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC)


def local_day(moment_utc: datetime, zone: ZoneInfo) -> date:
    if moment_utc.tzinfo is None:
        raise TimelineError("naive datetime: every stored timestamp must be UTC-aware")
    return moment_utc.astimezone(zone).date()


@dataclass(slots=True)
class Slot:
    """One interval of the regular grid, with the observation found for it (if any)."""

    start_utc: datetime
    day: date
    #: Sun above the horizon at the interval midpoint (always true for daily data).
    daylight: bool
    #: Solar hour angle at the midpoint [rad]; ``None`` for daily data.
    hour_angle: float | None
    obs: Observation | None


def observation_span(observations: Iterable[Observation], zone: ZoneInfo) -> tuple[date, date] | None:
    """First and last local day covered by ``observations``."""
    first: date | None = None
    last: date | None = None
    for obs in observations:
        day = local_day(obs.start_utc, zone)
        if first is None or day < first:
            first = day
        if last is None or day > last:
            last = day
    if first is None or last is None:
        return None
    return first, last


def build_slots(
    observations: Sequence[Observation],
    interval_minutes: int,
    timezone: str,
    latitude: float,
    longitude: float,
    period_start: date,
    period_end: date,
) -> list[Slot]:
    """Lay out the regular grid for ``[period_start, period_end]`` (local days, inclusive).

    Observations whose start does not coincide with a grid point are ignored
    here; ingestion rejects misaligned timestamps, so this only happens for
    rows outside the requested period.
    """
    if interval_minutes not in SUPPORTED_INTERVALS:
        raise TimelineError(
            f"unsupported interval of {interval_minutes} min; supported: {SUPPORTED_INTERVALS}"
        )
    if period_end < period_start:
        raise TimelineError("period end precedes period start")
    zone = get_zone(timezone)
    slots: list[Slot] = []

    if interval_minutes == DAILY_MINUTES:
        by_day: dict[date, Observation] = {}
        for obs in observations:
            by_day.setdefault(local_day(obs.start_utc, zone), obs)
        day = period_start
        while day <= period_end:
            slots.append(
                Slot(
                    start_utc=local_midnight_utc(day, zone),
                    day=day,
                    daylight=True,
                    hour_angle=None,
                    obs=by_day.get(day),
                )
            )
            day += timedelta(days=1)
        return slots

    by_start: dict[datetime, Observation] = {obs.start_utc.astimezone(UTC): obs for obs in observations}
    step = timedelta(minutes=interval_minutes)
    half = step / 2
    cursor = local_midnight_utc(period_start, zone)
    end = local_midnight_utc(period_end + timedelta(days=1), zone)
    while cursor < end:
        midpoint = cursor + half
        slots.append(
            Slot(
                start_utc=cursor,
                day=local_day(cursor, zone),
                daylight=sun_elevation_deg(midpoint, latitude, longitude) > 0.0,
                hour_angle=hour_angle_rad(midpoint, longitude),
                obs=by_start.get(cursor),
            )
        )
        cursor += step
    return slots
