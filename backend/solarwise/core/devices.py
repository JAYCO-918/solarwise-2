"""Device-to-fleet comparison.

Inverters of one plant see the same weather, so their specific yields
(kWh per kWp) should agree closely.  A device that persistently yields less
than the fleet median points at an equipment problem on *that* device - a
signature that plant-wide soiling does not produce.

The comparison is a ratio of observations, not a model.  It cannot see a
problem that affects every device equally.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from solarwise.core.models import AnalysisThresholds, DeviceObservation, DeviceSpec
from solarwise.core.provenance import UNKNOWN_TAG, ProvenanceTag
from solarwise.core.timeline import local_day

#: Fewest devices with data on a day for a fleet median to be meaningful.
MIN_DEVICES = 4
#: Below this share of the fleet median a device is considered not producing.
OFFLINE_RATIO = 0.02


class DeviceFinding(BaseModel):
    device_code: str
    capacity_kwp: float
    status: str  # NORMAL | UNDERPERFORMING | OFFLINE
    median_ratio_period: float | None
    median_ratio_window: float | None
    days_flagged: int
    days_offline: int
    first_flagged: date | None
    last_flagged: date | None
    lost_energy_kwh: float
    active_in_window: bool


class DeviceAnalysis(BaseModel):
    evaluable: bool
    reason: str | None = None
    n_devices: int = 0
    n_days: int = 0
    findings: list[DeviceFinding] = Field(default_factory=list)
    flagged_devices: int = 0
    active_in_window: int = 0
    lost_energy_kwh: float = 0.0
    #: Share of fleet energy lost by flagged devices, per day.
    loss_fraction_by_day: dict[date, float] = Field(default_factory=dict)
    tag: ProvenanceTag = UNKNOWN_TAG
    notes: list[str] = Field(default_factory=list)


def analyse_devices(
    observations: Mapping[str, Sequence[DeviceObservation]],
    devices: Mapping[str, DeviceSpec],
    *,
    timezone: ZoneInfo,
    period_start: date,
    period_end: date,
    thresholds: AnalysisThresholds,
    tag: ProvenanceTag | None,
) -> DeviceAnalysis:
    """Compare each device's daily specific yield with the fleet median."""
    known = {code: spec for code, spec in devices.items() if spec.capacity_kwp > 0 and code in observations}
    if len(known) < MIN_DEVICES:
        return DeviceAnalysis(
            evaluable=False,
            reason=(
                f"device-level energy is available for {len(known)} device(s); at least {MIN_DEVICES} "
                "are needed for a fleet comparison"
            ),
            n_devices=len(known),
        )

    # device -> day -> (energy sum, number of readings)
    daily: dict[str, dict[date, tuple[float, int]]] = {}
    for code in known:
        per_day: dict[date, tuple[float, int]] = {}
        for obs in observations[code]:
            if obs.actual_energy_kwh is None:
                continue
            day = local_day(obs.start_utc, timezone)
            if not (period_start <= day <= period_end):
                continue
            energy, count = per_day.get(day, (0.0, 0))
            per_day[day] = (energy + obs.actual_energy_kwh, count + 1)
        daily[code] = per_day

    window_start = max(period_start, period_end - timedelta(days=thresholds.assessment_window_days - 1))
    ratios: dict[str, dict[date, float]] = {code: {} for code in known}
    lost: dict[str, float] = dict.fromkeys(known, 0.0)
    flagged_days: dict[str, list[date]] = {code: [] for code in known}
    offline_days: dict[str, int] = dict.fromkeys(known, 0)
    loss_fraction: dict[date, float] = {}
    evaluated_days = 0

    day = period_start
    while day <= period_end:
        counts = [daily[code][day][1] for code in known if day in daily[code]]
        if counts:
            full = max(counts)
            # Only devices with a complete set of readings for the day are comparable.
            valid = {
                code: daily[code][day][0] / known[code].capacity_kwp
                for code in known
                if day in daily[code] and daily[code][day][1] == full
            }
            if len(valid) >= MIN_DEVICES:
                fleet = float(median(valid.values()))
                if fleet > 0:
                    evaluated_days += 1
                    fleet_energy = 0.0
                    day_loss = 0.0
                    for code, specific in valid.items():
                        ratio = specific / fleet
                        ratios[code][day] = ratio
                        fleet_energy += fleet * known[code].capacity_kwp
                        if ratio < thresholds.device_underperformance_ratio:
                            energy_lost = (fleet - specific) * known[code].capacity_kwp
                            lost[code] += energy_lost
                            day_loss += energy_lost
                            flagged_days[code].append(day)
                            if ratio < OFFLINE_RATIO:
                                offline_days[code] += 1
                    if fleet_energy > 0:
                        loss_fraction[day] = day_loss / fleet_energy
        day += timedelta(days=1)

    if evaluated_days == 0:
        return DeviceAnalysis(
            evaluable=False,
            reason="no day has complete energy readings for enough devices",
            n_devices=len(known),
        )

    last_evaluated = max(d for per_code in ratios.values() for d in per_code)
    findings: list[DeviceFinding] = []
    for code, spec in sorted(known.items()):
        per_day_ratio = ratios[code]
        flags = flagged_days[code]
        window_flags = [d for d in flags if d >= window_start]
        # Persistent: flagged on at least two days, or still flagged on the latest day.
        persistent = len(flags) >= 2 or (bool(flags) and flags[-1] == last_evaluated)
        if not persistent:
            status = "NORMAL"
        elif offline_days[code] * 2 >= len(flags):
            status = "OFFLINE"
        else:
            status = "UNDERPERFORMING"
        window_ratios = [r for d, r in per_day_ratio.items() if d >= window_start]
        findings.append(
            DeviceFinding(
                device_code=code,
                capacity_kwp=spec.capacity_kwp,
                status=status,
                median_ratio_period=float(median(per_day_ratio.values())) if per_day_ratio else None,
                median_ratio_window=float(median(window_ratios)) if window_ratios else None,
                days_flagged=len(flags),
                days_offline=offline_days[code],
                first_flagged=flags[0] if flags else None,
                last_flagged=flags[-1] if flags else None,
                lost_energy_kwh=lost[code],
                active_in_window=persistent and (len(window_flags) >= 2 or (bool(flags) and flags[-1] == last_evaluated)),
            )
        )

    flagged = [f for f in findings if f.status != "NORMAL"]
    notes = [
        "A device is flagged when its specific yield falls below "
        f"{thresholds.device_underperformance_ratio * 100:.0f} % of the fleet median on at least two days "
        "(or on the latest day).",
        "The comparison cannot detect a problem that affects all devices equally, and uneven soiling "
        "between blocks can also lower individual devices.",
    ]
    return DeviceAnalysis(
        evaluable=True,
        n_devices=len(known),
        n_days=evaluated_days,
        findings=findings,
        flagged_devices=len(flagged),
        active_in_window=sum(1 for f in flagged if f.active_in_window),
        lost_energy_kwh=sum(lost.values()),
        loss_fraction_by_day=loss_fraction,
        tag=tag or UNKNOWN_TAG,
        notes=notes,
    )
