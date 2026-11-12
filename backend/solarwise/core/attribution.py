"""Performance-factor attribution (loss chain).

Starting from the baseline, each matched interval is walked through a chain of
factors.  A factor is only applied when the inputs needed to *calculate* it
exist; otherwise it is reported as ``NOT_QUANTIFIED`` and whatever effect it may
have stays - visibly - inside the unexplained residual.

    baseline expected energy
      / (1 - declared soiling allowance)        -> clean reference
      x irradiance ratio  H_actual / H_baseline (baselines not irradiance adjusted)
      x temperature ratio (1+g(T-25)) / (1+g(Tref-25))  (baselines not temperature adjusted)
      x degradation factor                      (baselines that ignore ageing)
      = weather-adjusted expected energy of a clean, available plant
      - downtime          (intervals with no production while energy was expected)
      - equipment         (logged availability, or device-to-fleet comparison)
      - curtailment       (energy logged as curtailed)
      = pre-soiling expected energy
      - soiling           (measured soiling ratio)
      - actual energy
      = unexplained residual

Soiling is never inferred from the gap: the soiling step exists only where a
soiling ratio was observed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from enum import StrEnum
from statistics import median

from pydantic import BaseModel, Field

from solarwise.core.baseline import BaselineResult
from solarwise.core.models import (
    AnalysisThresholds,
    ChannelMeta,
    IrradiancePlane,
    Metric,
    PlantSpec,
)
from solarwise.core.provenance import UNKNOWN_TAG, ProvenanceTag, Traced, derive
from solarwise.core.pv_model import degradation_factor, temperature_factor
from solarwise.core.thermal import BASIS_MEASURED_MODULE, cell_temperature, poa_irradiation
from solarwise.core.timeline import DAILY_MINUTES, Slot


class Factor(StrEnum):
    BASELINE_SOILING_ALLOWANCE = "BASELINE_SOILING_ALLOWANCE"
    IRRADIANCE = "IRRADIANCE"
    TEMPERATURE = "TEMPERATURE"
    DEGRADATION = "DEGRADATION"
    DOWNTIME = "DOWNTIME"
    EQUIPMENT_AVAILABILITY = "EQUIPMENT_AVAILABILITY"
    CURTAILMENT = "CURTAILMENT"
    SOILING = "SOILING"


class FactorStatus(StrEnum):
    QUANTIFIED = "QUANTIFIED"
    PARTIALLY_QUANTIFIED = "PARTIALLY_QUANTIFIED"
    #: The baseline already reflects this effect; it is not part of the gap.
    ACCOUNTED_IN_BASELINE = "ACCOUNTED_IN_BASELINE"
    #: Inputs are missing.  Any effect remains inside the residual.
    NOT_QUANTIFIED = "NOT_QUANTIFIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class FactorContribution(BaseModel):
    factor: Factor
    status: FactorStatus
    #: Energy attributed to the factor over the scope; positive = loss.
    energy: Traced
    share_of_expected_pct: float | None
    #: Share of matched expected energy for which the factor could be evaluated.
    coverage: float | None
    #: CALCULATED | LOGGED | DIRECT_MEASUREMENT | PROXY | ASSUMPTION | N/A
    basis: str
    explanation: str
    missing_inputs: list[str] = Field(default_factory=list)


class AttributionScope(BaseModel):
    """Sums of the chain over a set of days."""

    start: date
    end: date
    matched_slots: int
    expected_kwh: float | None
    actual_kwh: float | None
    gap_kwh: float | None
    weather_adjusted_expected_kwh: float | None
    pre_soiling_expected_kwh: float | None
    #: Gap that remains once every quantified non-soiling factor is removed.
    pre_soiling_gap_kwh: float | None
    pre_soiling_gap_pct: float | None
    #: Energy-weighted measured soiling loss, over intervals with a soiling ratio.
    measured_soiling_loss_pct: float | None
    #: Pre-soiling gap restricted to the intervals that have a soiling ratio.
    pre_soiling_gap_on_soiling_slots_pct: float | None
    soiling_coverage: float | None
    residual_kwh: float | None
    #: Unexplained residual relative to pre-soiling expected energy.
    residual_pct: float | None
    outage_slots: int
    mean_availability: float | None
    contributions: list[FactorContribution]


class DailyAttribution(BaseModel):
    day: date
    expected_kwh: float | None
    weather_adjusted_expected_kwh: float | None
    pre_soiling_expected_kwh: float | None
    actual_kwh: float | None
    irradiance_kwh: float | None
    temperature_kwh: float | None
    degradation_kwh: float | None
    downtime_kwh: float | None
    equipment_kwh: float | None
    curtailment_kwh: float | None
    soiling_kwh: float | None
    residual_kwh: float | None
    #: actual / pre-soiling expected, outage intervals excluded.
    performance_index: float | None
    soiling_ratio: float | None
    cell_temp_c: float | None
    availability: float | None
    poa_irradiation_kwh_m2: float | None
    precipitation_mm: float | None
    outage: bool


class LossAttribution(BaseModel):
    period: AttributionScope
    window: AttributionScope
    daily: list[DailyAttribution]
    #: How cell temperature was obtained, in number of intervals per basis.
    cell_temperature_basis: dict[str, int]
    curtailment_capped_slots: int
    notes: list[str]
    #: Per-slot chain values, kept in memory for the intraday analysis.
    slot_pre_curtailment: list[float | None] = Field(default_factory=list, exclude=True)
    slot_pre_soiling: list[float | None] = Field(default_factory=list, exclude=True)
    slot_outage: list[bool] = Field(default_factory=list, exclude=True)


# --------------------------------------------------------------------------- internals

_CHAIN: tuple[Factor, ...] = (
    Factor.BASELINE_SOILING_ALLOWANCE,
    Factor.IRRADIANCE,
    Factor.TEMPERATURE,
    Factor.DEGRADATION,
    Factor.DOWNTIME,
    Factor.EQUIPMENT_AVAILABILITY,
    Factor.CURTAILMENT,
    Factor.SOILING,
)


class _Sums:
    """Accumulates the chain over a scope."""

    def __init__(self) -> None:
        self.matched = 0
        self.expected = 0.0
        self.actual = 0.0
        self.weather = 0.0
        self.pre_soiling = 0.0
        self.residual = 0.0
        self.outage_slots = 0
        self.loss = dict.fromkeys(_CHAIN, 0.0)
        #: baseline energy of the slots on which each factor could be evaluated
        self.covered = dict.fromkeys(_CHAIN, 0.0)
        self.soiling_slots_pre = 0.0
        self.soiling_slots_actual = 0.0
        self.avail_weighted = 0.0
        self.avail_weight = 0.0
        self.temp_weighted = 0.0
        self.temp_weight = 0.0
        self.non_outage_pre = 0.0
        self.non_outage_actual = 0.0


def _tag(channels: Mapping[Metric, ChannelMeta], metric: Metric) -> ProvenanceTag:
    meta = channels.get(metric)
    return meta.tag if meta is not None else UNKNOWN_TAG


def daily_soiling_ratio(slots: Sequence[Slot]) -> dict[date, float]:
    """Representative soiling ratio per local day: the median of that day's readings.

    No value is carried over to days without a reading.
    """
    readings: dict[date, list[float]] = {}
    for slot in slots:
        if slot.obs is not None and slot.obs.soiling_ratio is not None:
            readings.setdefault(slot.day, []).append(slot.obs.soiling_ratio)
    return {day: float(median(values)) for day, values in readings.items()}


def _status(covered: float, total: float) -> FactorStatus:
    if total <= 0 or covered <= 0:
        return FactorStatus.NOT_QUANTIFIED
    if covered / total >= 0.95:
        return FactorStatus.QUANTIFIED
    return FactorStatus.PARTIALLY_QUANTIFIED


def attribute_losses(
    slots: Sequence[Slot],
    baseline: BaselineResult,
    *,
    interval_minutes: int,
    plant: PlantSpec,
    channels: Mapping[Metric, ChannelMeta],
    thresholds: AnalysisThresholds,
    device_loss_fraction_by_day: Mapping[date, float] | None = None,
    device_tag: ProvenanceTag | None = None,
) -> LossAttribution:
    """Walk every matched interval through the factor chain."""
    expected = baseline.expected
    if len(slots) != len(expected):
        raise ValueError("baseline is not aligned with the slot grid")
    if not slots:
        raise ValueError("empty analysis period")

    descriptor = baseline.descriptor
    gamma = plant.module_temp_coeff_per_c
    period_start, period_end = slots[0].day, slots[-1].day
    window_start = max(period_start, period_end - timedelta(days=thresholds.assessment_window_days - 1))
    sr_by_day = daily_soiling_ratio(slots)
    channel_map = dict(channels)

    allowance = descriptor.soiling_allowance_fraction or 0.0
    ref_irr = baseline.baseline_irradiation
    ref_plane = baseline.baseline_irradiation_plane
    use_degradation_step = (
        descriptor.degradation_adjusted is False
        and plant.commissioning_date is not None
        and plant.annual_degradation_rate is not None
    )
    # Smallest expected energy for an interval to count as "energy was expected" when
    # looking for outages; avoids flagging dawn/dusk intervals.
    finite_expected = [e for e in expected if e is not None and e > 0]
    outage_floor = 0.05 * max(finite_expected) if finite_expected else 0.0

    period, window = _Sums(), _Sums()
    by_day: dict[date, _Sums] = {}
    day_extra: dict[date, dict[str, float]] = {}
    temp_basis_counts: dict[str, int] = {}
    capped = 0
    slot_pre_curt: list[float | None] = []
    slot_pre_soil: list[float | None] = []
    slot_outage: list[bool] = []

    for idx, slot in enumerate(slots):
        obs = slot.obs
        extra = day_extra.setdefault(slot.day, {})
        by_day.setdefault(slot.day, _Sums())
        if obs is not None:
            if obs.precipitation_mm is not None:
                extra["precipitation"] = extra.get("precipitation", 0.0) + obs.precipitation_mm
            if obs.poa_irradiation_kwh_m2 is not None:
                extra["poa"] = extra.get("poa", 0.0) + obs.poa_irradiation_kwh_m2

        e0 = expected[idx]
        actual = obs.actual_energy_kwh if obs is not None else None
        if obs is None or e0 is None or actual is None:
            slot_pre_curt.append(None)
            slot_pre_soil.append(None)
            slot_outage.append(False)
            continue

        scopes = [period, by_day[slot.day]]
        if slot.day >= window_start:
            scopes.append(window)

        loss = dict.fromkeys(_CHAIN, 0.0)
        covered = dict.fromkeys(_CHAIN, False)

        # 0. soiling allowance already inside the baseline -------------------------
        energy = e0 / (1.0 - allowance) if allowance > 0 else e0
        loss[Factor.BASELINE_SOILING_ALLOWANCE] = e0 - energy
        covered[Factor.BASELINE_SOILING_ALLOWANCE] = True

        # 1. irradiance ----------------------------------------------------------------
        if descriptor.irradiance_adjusted is True:
            covered[Factor.IRRADIANCE] = True
        else:
            h_ref = ref_irr[idx] if ref_irr is not None else None
            if ref_plane is IrradiancePlane.GHI:
                h_act = obs.ghi_kwh_m2
            else:
                h_act = obs.poa_irradiation_kwh_m2
            if h_ref is not None and h_ref > 0 and h_act is not None and ref_plane is not None:
                adjusted = energy * (h_act / h_ref)
                loss[Factor.IRRADIANCE] = energy - adjusted
                energy = adjusted
                covered[Factor.IRRADIANCE] = True

        # 2. temperature ---------------------------------------------------------------
        poa = poa_irradiation(slot, plant, interval_minutes, channel_map)
        temp = cell_temperature(slot, plant, interval_minutes, channel_map, poa)
        if temp is not None and e0 > 0:
            temp_basis_counts[temp.basis] = temp_basis_counts.get(temp.basis, 0) + 1
            for s in scopes:
                s.temp_weighted += temp.value * e0
                s.temp_weight += e0
        if descriptor.temperature_adjusted is True:
            covered[Factor.TEMPERATURE] = True
        elif temp is not None and gamma is not None and descriptor.reference_cell_temp_c is not None:
            reference = temperature_factor(descriptor.reference_cell_temp_c, gamma)
            if reference > 0:
                adjusted = energy * temperature_factor(temp.value, gamma) / reference
                loss[Factor.TEMPERATURE] = energy - adjusted
                energy = adjusted
                covered[Factor.TEMPERATURE] = True

        # 3. degradation ---------------------------------------------------------------
        if descriptor.degradation_adjusted is True:
            covered[Factor.DEGRADATION] = True
        elif use_degradation_step:
            assert plant.commissioning_date is not None and plant.annual_degradation_rate is not None
            years = max(0.0, (slot.day - plant.commissioning_date).days / 365.25)
            adjusted = energy * degradation_factor(years, plant.annual_degradation_rate)
            loss[Factor.DEGRADATION] = energy - adjusted
            energy = adjusted
            covered[Factor.DEGRADATION] = True

        weather_adjusted = energy

        # 4. downtime ------------------------------------------------------------------
        covered[Factor.DOWNTIME] = True
        is_outage = (
            slot.daylight
            and weather_adjusted > outage_floor
            and actual <= thresholds.outage_actual_fraction * weather_adjusted
        )
        if is_outage:
            loss[Factor.DOWNTIME] = weather_adjusted - actual
            energy = actual
            pre_curtailment = actual
            # Later factors cannot act on an interval that produced nothing.
            covered[Factor.EQUIPMENT_AVAILABILITY] = True
            covered[Factor.CURTAILMENT] = True
            covered[Factor.SOILING] = True
        else:
            # 5. equipment availability ------------------------------------------------
            availability = obs.availability_fraction
            if availability is not None:
                loss[Factor.EQUIPMENT_AVAILABILITY] = energy * (1.0 - availability)
                energy -= loss[Factor.EQUIPMENT_AVAILABILITY]
                covered[Factor.EQUIPMENT_AVAILABILITY] = True
                for s in scopes:
                    s.avail_weighted += availability * e0
                    s.avail_weight += e0
            elif device_loss_fraction_by_day is not None and slot.day in device_loss_fraction_by_day:
                loss[Factor.EQUIPMENT_AVAILABILITY] = energy * device_loss_fraction_by_day[slot.day]
                energy -= loss[Factor.EQUIPMENT_AVAILABILITY]
                covered[Factor.EQUIPMENT_AVAILABILITY] = True
            pre_curtailment = energy

            # 6. curtailment -----------------------------------------------------------
            if obs.curtailed_energy_kwh is not None:
                curtailed = obs.curtailed_energy_kwh
                if curtailed > energy:
                    curtailed = energy
                    capped += 1
                loss[Factor.CURTAILMENT] = curtailed
                energy -= curtailed
                covered[Factor.CURTAILMENT] = True

        pre_soiling = energy

        # 7. soiling (measured only) ---------------------------------------------------
        if not is_outage:
            sr = sr_by_day.get(slot.day)
            if sr is not None:
                loss[Factor.SOILING] = pre_soiling * (1.0 - min(sr, 1.0))
                energy -= loss[Factor.SOILING]
                covered[Factor.SOILING] = True
                for s in scopes:
                    s.soiling_slots_pre += pre_soiling
                    s.soiling_slots_actual += actual

        residual = energy - actual

        for s in scopes:
            s.matched += 1
            s.expected += e0
            s.actual += actual
            s.weather += weather_adjusted
            s.pre_soiling += pre_soiling
            s.residual += residual
            if is_outage:
                s.outage_slots += 1
            else:
                s.non_outage_pre += pre_soiling
                s.non_outage_actual += actual
            for factor in _CHAIN:
                s.loss[factor] += loss[factor]
                if covered[factor]:
                    s.covered[factor] += e0

        slot_pre_curt.append(pre_curtailment)
        slot_pre_soil.append(pre_soiling)
        slot_outage.append(is_outage)

    # --------------------------------------------------------------------- reporting
    exp_tag = baseline.meta.tag
    act_tag = _tag(channel_map, Metric.ACTUAL_ENERGY)
    temp_inputs = [exp_tag]
    measured_temp_only = set(temp_basis_counts) == {BASIS_MEASURED_MODULE}
    if Metric.MODULE_TEMP in channel_map and BASIS_MEASURED_MODULE in temp_basis_counts:
        temp_inputs.append(_tag(channel_map, Metric.MODULE_TEMP))
    if not measured_temp_only and temp_basis_counts:
        temp_inputs.append(_tag(channel_map, Metric.AMBIENT_TEMP))

    def build_scope(s: _Sums, start: date, end: date) -> AttributionScope:
        total = s.expected
        contributions: list[FactorContribution] = []

        def add(
            factor: Factor,
            status: FactorStatus,
            tag: ProvenanceTag,
            basis: str,
            explanation: str,
            missing: list[str] | None = None,
        ) -> None:
            quantified = status in (FactorStatus.QUANTIFIED, FactorStatus.PARTIALLY_QUANTIFIED)
            value = s.loss[factor] if quantified and s.matched else None
            contributions.append(
                FactorContribution(
                    factor=factor,
                    status=status,
                    energy=Traced(value=value, unit="kWh", tag=tag, basis=basis),
                    share_of_expected_pct=(value / total * 100.0 if value is not None and total > 0 else None),
                    coverage=(s.covered[factor] / total if total > 0 else None),
                    basis=basis,
                    explanation=explanation,
                    missing_inputs=missing or [],
                )
            )

        # baseline soiling allowance
        if allowance > 0:
            add(
                Factor.BASELINE_SOILING_ALLOWANCE,
                FactorStatus.QUANTIFIED,
                derive([exp_tag], source="SolarWise attribution", method="baseline / (1 - declared soiling allowance)"),
                "ASSUMPTION",
                f"The baseline already assumes a soiling loss of {allowance * 100:.1f} %; it is removed so "
                "that later steps refer to a clean array (negative value = energy added back).",
            )

        # irradiance
        if descriptor.irradiance_adjusted is True:
            add(Factor.IRRADIANCE, FactorStatus.ACCOUNTED_IN_BASELINE, exp_tag, "N/A",
                "The baseline already reflects the irradiance actually received.")
        else:
            status = _status(s.covered[Factor.IRRADIANCE], total)
            if status is FactorStatus.NOT_QUANTIFIED:
                add(Factor.IRRADIANCE, status, UNKNOWN_TAG, "N/A",
                    "The baseline is not adjusted to actual irradiance and the deviation cannot be "
                    "calculated; any irradiance effect remains inside the unexplained residual.",
                    ["irradiation assumed by the baseline", "actual irradiation in the same plane"])
            else:
                irr_metric = Metric.GHI if ref_plane is IrradiancePlane.GHI else Metric.POA_IRRADIATION
                add(Factor.IRRADIANCE, status,
                    derive([exp_tag, _tag(channel_map, irr_metric), _tag(channel_map, Metric.BASELINE_IRRADIATION)]
                           if Metric.BASELINE_IRRADIATION in channel_map else [exp_tag, _tag(channel_map, irr_metric)],
                           source="SolarWise attribution",
                           method="expected x (1 - H_actual / H_baseline)", model_applied=True),
                    "CALCULATED",
                    "Difference between the irradiation actually received and the irradiation assumed by "
                    "the baseline (first-order: energy proportional to irradiation).")

        # temperature
        if descriptor.temperature_adjusted is True:
            add(Factor.TEMPERATURE, FactorStatus.ACCOUNTED_IN_BASELINE, exp_tag, "N/A",
                "The baseline already reflects the temperatures actually experienced.")
        else:
            status = _status(s.covered[Factor.TEMPERATURE], total)
            if status is FactorStatus.NOT_QUANTIFIED:
                missing = []
                if gamma is None:
                    missing.append("module power temperature coefficient")
                if descriptor.reference_cell_temp_c is None:
                    missing.append("cell temperature assumed by the baseline")
                if not temp_basis_counts:
                    missing.append("module temperature, or ambient temperature with in-plane irradiation")
                add(Factor.TEMPERATURE, status, UNKNOWN_TAG, "N/A",
                    "The baseline is not adjusted to actual temperature and the thermal deviation cannot "
                    "be calculated; any thermal effect remains inside the unexplained residual.", missing)
            else:
                proxy = interval_minutes == DAILY_MINUTES and not measured_temp_only
                add(Factor.TEMPERATURE, status,
                    derive(temp_inputs, source="SolarWise attribution",
                           method="expected x (1 - (1+g(Tcell-25)) / (1+g(Tref-25)))", model_applied=True),
                    "PROXY" if proxy else "CALCULATED",
                    "Thermal loss relative to the cell temperature assumed by the baseline "
                    f"({descriptor.reference_cell_temp_c:g} degC), from "
                    + ("measured module temperature." if measured_temp_only
                       else "cell temperature modelled from ambient conditions."))

        # degradation
        if descriptor.degradation_adjusted is True:
            add(Factor.DEGRADATION, FactorStatus.ACCOUNTED_IN_BASELINE, exp_tag, "N/A",
                "The baseline already includes age-related degradation.")
        elif use_degradation_step:
            assert plant.annual_degradation_rate is not None
            add(Factor.DEGRADATION, _status(s.covered[Factor.DEGRADATION], total),
                derive([exp_tag], source="SolarWise attribution",
                       method="expected x (1 - (1 - rate)^years)", model_applied=True),
                "ASSUMPTION",
                f"Ageing at an assumed constant {plant.annual_degradation_rate * 100:.2f} %/year since "
                "commissioning. The rate is a configuration assumption, not a measurement.")
        else:
            missing = []
            if descriptor.degradation_adjusted is None:
                missing.append("declaration of whether the baseline includes degradation")
            if plant.commissioning_date is None:
                missing.append("commissioning date")
            if plant.annual_degradation_rate is None:
                missing.append("annual degradation rate")
            add(Factor.DEGRADATION, FactorStatus.NOT_QUANTIFIED, UNKNOWN_TAG, "N/A",
                "Age-related degradation could not be evaluated; any effect remains inside the residual.",
                missing)

        # downtime
        add(Factor.DOWNTIME, FactorStatus.QUANTIFIED,
            derive([exp_tag, act_tag], source="SolarWise attribution",
                   method="expected energy of daylight intervals with (near-)zero production"),
            "CALCULATED",
            f"{s.outage_slots} interval(s) produced less than "
            f"{thresholds.outage_actual_fraction * 100:g} % of the energy expected in daylight. This shows "
            "that the plant did not produce, not why (grid outage, trip, maintenance or a data fault).")

        # equipment availability
        status = _status(s.covered[Factor.EQUIPMENT_AVAILABILITY], total)
        if s.avail_weight > 0:
            add(Factor.EQUIPMENT_AVAILABILITY, status,
                derive([exp_tag, _tag(channel_map, Metric.AVAILABILITY)], source="SolarWise attribution",
                       method="expected x (1 - availability)"),
                "CALCULATED",
                "Energy not produced because part of the plant was unavailable, from the logged "
                "capacity-weighted availability.")
        elif device_loss_fraction_by_day is not None and status is not FactorStatus.NOT_QUANTIFIED:
            add(Factor.EQUIPMENT_AVAILABILITY, status,
                derive([exp_tag, device_tag or UNKNOWN_TAG], source="SolarWise attribution",
                       method="expected x share lost by devices yielding below the fleet median"),
                "CALCULATED",
                "No availability log: equipment losses estimated by comparing each device's specific yield "
                "with the fleet median.")
        else:
            add(Factor.EQUIPMENT_AVAILABILITY, FactorStatus.NOT_QUANTIFIED, UNKNOWN_TAG, "N/A",
                "Neither an availability log nor device-level energy is available; equipment losses, if "
                "any, remain inside the unexplained residual.",
                ["availability log", "device-level (inverter) energy"])

        # curtailment
        curtailment_status = _status(s.covered[Factor.CURTAILMENT], total)
        if Metric.CURTAILED_ENERGY in channel_map and curtailment_status is not FactorStatus.NOT_QUANTIFIED:
            add(Factor.CURTAILMENT, curtailment_status,
                derive([_tag(channel_map, Metric.CURTAILED_ENERGY)], source="SolarWise attribution",
                       method="sum of logged curtailed energy"),
                "LOGGED",
                "Energy logged as curtailed. The figure is taken from the log as supplied.")
        else:
            add(Factor.CURTAILMENT, FactorStatus.NOT_QUANTIFIED, UNKNOWN_TAG, "N/A",
                "No curtailment log; curtailed energy, if any, remains inside the unexplained residual.",
                ["curtailment log (energy or set-points)"])

        # soiling
        if Metric.SOILING_RATIO in channel_map and s.soiling_slots_pre > 0:
            add(Factor.SOILING, _status(s.covered[Factor.SOILING], total),
                derive([exp_tag, _tag(channel_map, Metric.SOILING_RATIO)], source="SolarWise attribution",
                       method="pre-soiling expected x (1 - soiling ratio)"),
                "DIRECT_MEASUREMENT",
                "Loss corresponding to the observed soiling ratio, on days with a reading. It is not "
                "inferred from the production gap.")
        else:
            add(Factor.SOILING, FactorStatus.NOT_QUANTIFIED, UNKNOWN_TAG, "N/A",
                "No soiling ratio was observed. Soiling is not inferred from the production gap; any "
                "soiling loss remains inside the unexplained residual.",
                ["soiling ratio (soiling station, clean reference module or string comparison)"])

        matched = s.matched > 0
        pre = s.pre_soiling if matched else None
        pre_gap = (s.pre_soiling - s.actual) if matched else None
        return AttributionScope(
            start=start,
            end=end,
            matched_slots=s.matched,
            expected_kwh=s.expected if matched else None,
            actual_kwh=s.actual if matched else None,
            gap_kwh=(s.expected - s.actual) if matched else None,
            weather_adjusted_expected_kwh=s.weather if matched else None,
            pre_soiling_expected_kwh=pre,
            pre_soiling_gap_kwh=pre_gap,
            pre_soiling_gap_pct=(
                (s.non_outage_pre - s.non_outage_actual) / s.non_outage_pre * 100.0
                if s.non_outage_pre > 0
                else None
            ),
            measured_soiling_loss_pct=(
                s.loss[Factor.SOILING] / s.soiling_slots_pre * 100.0 if s.soiling_slots_pre > 0 else None
            ),
            pre_soiling_gap_on_soiling_slots_pct=(
                (s.soiling_slots_pre - s.soiling_slots_actual) / s.soiling_slots_pre * 100.0
                if s.soiling_slots_pre > 0
                else None
            ),
            soiling_coverage=(s.soiling_slots_pre / s.non_outage_pre if s.non_outage_pre > 0 else None),
            residual_kwh=s.residual if matched else None,
            residual_pct=(s.residual / s.non_outage_pre * 100.0 if s.non_outage_pre > 0 else None),
            outage_slots=s.outage_slots,
            mean_availability=(s.avail_weighted / s.avail_weight if s.avail_weight > 0 else None),
            contributions=contributions,
        )

    daily: list[DailyAttribution] = []
    for day in sorted(by_day):
        s = by_day[day]
        extra = day_extra.get(day, {})
        has = s.matched > 0

        def quantified(factor: Factor, s: _Sums = s, has: bool = has) -> float | None:
            return s.loss[factor] if has and s.covered[factor] > 0 else None

        daily.append(
            DailyAttribution(
                day=day,
                expected_kwh=s.expected if has else None,
                weather_adjusted_expected_kwh=s.weather if has else None,
                pre_soiling_expected_kwh=s.pre_soiling if has else None,
                actual_kwh=s.actual if has else None,
                irradiance_kwh=quantified(Factor.IRRADIANCE),
                temperature_kwh=quantified(Factor.TEMPERATURE),
                degradation_kwh=quantified(Factor.DEGRADATION),
                downtime_kwh=quantified(Factor.DOWNTIME),
                equipment_kwh=quantified(Factor.EQUIPMENT_AVAILABILITY),
                curtailment_kwh=quantified(Factor.CURTAILMENT),
                soiling_kwh=(s.loss[Factor.SOILING] if s.soiling_slots_pre > 0 else None),
                residual_kwh=s.residual if has else None,
                performance_index=(s.non_outage_actual / s.non_outage_pre if s.non_outage_pre > 0 else None),
                soiling_ratio=sr_by_day.get(day),
                cell_temp_c=(s.temp_weighted / s.temp_weight if s.temp_weight > 0 else None),
                availability=(s.avail_weighted / s.avail_weight if s.avail_weight > 0 else None),
                poa_irradiation_kwh_m2=extra.get("poa"),
                precipitation_mm=extra.get("precipitation"),
                outage=has and s.outage_slots > 0 and s.non_outage_pre <= 0,
            )
        )

    notes: list[str] = []
    if capped:
        notes.append(
            f"On {capped} interval(s) the logged curtailed energy exceeded the energy available after the "
            "preceding steps and was limited to it; the curtailment log and the baseline disagree there."
        )
    if temp_basis_counts and not measured_temp_only:
        notes.append(
            "Cell temperature was partly or wholly modelled from ambient conditions; it is not a measured "
            "module temperature."
        )

    return LossAttribution(
        period=build_scope(period, period_start, period_end),
        window=build_scope(window, window_start, period_end),
        daily=daily,
        cell_temperature_basis=temp_basis_counts,
        curtailment_capped_slots=capped,
        notes=notes,
        slot_pre_curtailment=slot_pre_curt,
        slot_pre_soiling=slot_pre_soil,
        slot_outage=slot_outage,
    )
