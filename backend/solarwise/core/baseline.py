"""Performance baseline (expected energy).

A baseline answers "what should the plant have produced?".  Several sources of
very different quality can provide it, behind one interface:

``OPERATOR_SUPPLIED`` / ``TELEMETRY_MODEL``
    An expected-energy channel delivered with the data.
``ENGINEERING_MODEL``
    SolarWise's weather-adjusted estimate from irradiation, temperature and the
    plant's design parameters.
``HISTORICAL_CLEAN_REFERENCE``
    The same model, with its system factor calibrated on a period during which
    the array is declared clean and fully available.
``PVGIS_TYPICAL_YEAR``
    Long-term monthly averages from PVGIS scaled to the installed capacity.
    Not adjusted to the weather actually experienced.

Whatever the source, the result states explicitly what the baseline accounts
for (:class:`~solarwise.core.models.BaselineDescriptor`), where it comes from
(provenance tag) and what limits its use.  A modelled reference is never
presented as the plant's measured clean-condition performance.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from solarwise.core.models import (
    BaselineDescriptor,
    BaselineMethod,
    ChannelMeta,
    IrradiancePlane,
    MeteringBoundary,
    Metric,
    PlantSpec,
)
from solarwise.core.provenance import UNKNOWN_TAG, Provenance, ProvenanceTag, derive, modelled
from solarwise.core.pv_model import degradation_factor, expected_energy_kwh
from solarwise.core.thermal import cell_temperature, poa_irradiation
from solarwise.core.timeline import DAILY_MINUTES, Slot


class BaselineStatus(StrEnum):
    OK = "OK"
    UNAVAILABLE = "UNAVAILABLE"


class PvgisMonth(BaseModel):
    """Monthly averages for 1 kWp as returned by the PVGIS ``PVcalc`` tool."""

    month: int = Field(ge=1, le=12)
    #: Average daily energy production [kWh/kWp/day] (``E_d``).
    e_d_kwh_per_kwp: float = Field(ge=0)
    #: Average daily in-plane irradiation [kWh/m2/day] (``H(i)_d``).
    h_i_d_kwh_m2: float = Field(ge=0)
    #: Average monthly production [kWh/kWp] (``E_m``).
    e_m_kwh_per_kwp: float | None = Field(default=None, ge=0)
    #: Year-to-year standard deviation of the monthly production [kWh/kWp] (``SD_m``).
    sd_m_kwh_per_kwp: float | None = Field(default=None, ge=0)


class BaselineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: BaselineMethod | Literal["AUTO"] = "AUTO"
    #: Period declared clean and fully available (``HISTORICAL_CLEAN_REFERENCE``).
    clean_reference_start: date | None = None
    clean_reference_end: date | None = None
    #: Relative standard uncertainty the user attributes to a SolarWise-built baseline [%].
    model_uncertainty_pct: float | None = Field(default=None, ge=0, le=50)
    #: Stored PVGIS monthly averages (``PVGIS_TYPICAL_YEAR``).
    pvgis_monthly: list[PvgisMonth] | None = None
    pvgis_source: str | None = None


class BaselineResult(BaseModel):
    status: BaselineStatus
    method: BaselineMethod
    descriptor: BaselineDescriptor
    meta: ChannelMeta
    #: Expected energy per slot [kWh]; ``None`` where it cannot be established.
    expected: list[float | None] = Field(default_factory=list, exclude=True)
    #: Reference irradiation per slot for baselines that are not irradiance adjusted.
    baseline_irradiation: list[float | None] | None = Field(default=None, exclude=True)
    baseline_irradiation_plane: IrradiancePlane | None = None
    parameters: dict[str, float | str | None] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class BaselineContext:
    slots: Sequence[Slot]
    interval_minutes: int
    plant: PlantSpec
    channels: dict[Metric, ChannelMeta]
    #: Descriptor declared with the dataset for a supplied expected-energy channel.
    declared: BaselineDescriptor | None
    request: BaselineRequest


class BaselineProvider(Protocol):
    """Interface every baseline source implements."""

    method: BaselineMethod

    def build(self, ctx: BaselineContext) -> BaselineResult: ...


# --------------------------------------------------------------------------- helpers


def descriptor_limitations(descriptor: BaselineDescriptor, tag: ProvenanceTag) -> list[str]:
    """Plain-language limits that follow from what the baseline does not cover."""
    out: list[str] = []
    if descriptor.method is BaselineMethod.UNKNOWN:
        out.append("The method behind the expected-energy baseline was not declared.")
    if tag.provenance is Provenance.UNKNOWN:
        out.append("The origin of the expected-energy baseline is unknown; the gap inherits that doubt.")
    if tag.provenance in (Provenance.MODELLED, Provenance.SYNTHETIC):
        out.append(
            "The baseline is a model output, not a measured clean-condition performance of this plant: "
            "part of any gap may be model error."
        )
    if descriptor.irradiance_adjusted is not True:
        state = "is not" if descriptor.irradiance_adjusted is False else "was not declared to be"
        out.append(
            f"The baseline {state} adjusted to the irradiance actually received: weather variability "
            "is part of the raw gap unless it can be normalised."
        )
    if descriptor.temperature_adjusted is not True:
        state = "is not" if descriptor.temperature_adjusted is False else "was not declared to be"
        out.append(
            f"The baseline {state} adjusted to actual temperature: thermal effects are part of the raw gap "
            "unless they can be quantified."
        )
    if descriptor.degradation_adjusted is None:
        out.append("Whether the baseline accounts for age-related degradation was not declared.")
    return out


def _unavailable(method: BaselineMethod, n: int, reasons: list[str]) -> BaselineResult:
    return BaselineResult(
        status=BaselineStatus.UNAVAILABLE,
        method=method,
        descriptor=BaselineDescriptor(method=method),
        meta=ChannelMeta(metric=Metric.EXPECTED_ENERGY, tag=UNKNOWN_TAG, unit="kWh"),
        expected=[None] * n,
        limitations=reasons,
    )


def _actual_boundary(channels: dict[Metric, ChannelMeta]) -> MeteringBoundary | None:
    meta = channels.get(Metric.ACTUAL_ENERGY)
    return meta.boundary if meta is not None else None


def _years_in_operation(plant: PlantSpec, day: date) -> float | None:
    if plant.commissioning_date is None:
        return None
    return max(0.0, (day - plant.commissioning_date).days / 365.25)


# --------------------------------------------------------------------------- providers


class SuppliedBaseline:
    """Expected energy delivered with the dataset."""

    def __init__(self, method: BaselineMethod = BaselineMethod.OPERATOR_SUPPLIED) -> None:
        self.method = method

    def build(self, ctx: BaselineContext) -> BaselineResult:
        n = len(ctx.slots)
        meta = ctx.channels.get(Metric.EXPECTED_ENERGY)
        expected = [s.obs.expected_energy_kwh if s.obs is not None else None for s in ctx.slots]
        if meta is None or all(v is None for v in expected):
            return _unavailable(self.method, n, ["The dataset contains no expected-energy channel."])
        descriptor = ctx.declared or BaselineDescriptor()
        if descriptor.method is BaselineMethod.UNKNOWN and self.method is not BaselineMethod.OPERATOR_SUPPLIED:
            descriptor = descriptor.model_copy(update={"method": self.method})
        irr_meta = ctx.channels.get(Metric.BASELINE_IRRADIATION)
        has_ref_irr = any(s.obs is not None and s.obs.baseline_irradiation_kwh_m2 is not None for s in ctx.slots)
        return BaselineResult(
            status=BaselineStatus.OK,
            method=descriptor.method,
            descriptor=descriptor,
            meta=meta,
            expected=expected,
            baseline_irradiation=(
                [s.obs.baseline_irradiation_kwh_m2 if s.obs is not None else None for s in ctx.slots]
                if has_ref_irr
                else None
            ),
            baseline_irradiation_plane=(irr_meta.plane if irr_meta is not None else None),
            limitations=descriptor_limitations(descriptor, meta.tag),
            notes=["Expected energy taken from the dataset as supplied."],
        )


class EngineeringModelBaseline:
    """Weather-adjusted engineering estimate built by SolarWise.

    ``E = P0 * H_poa / G_stc * (1 + gamma (T_cell - 25)) * (1 - L_sys) * degradation``

    With ``calibrate=True`` the system factor ``(1 - L_sys)`` is replaced by a
    reference performance ratio fitted on a declared clean period
    (``HISTORICAL_CLEAN_REFERENCE``).
    """

    def __init__(self, calibrate: bool = False) -> None:
        self.calibrate = calibrate
        self.method = (
            BaselineMethod.HISTORICAL_CLEAN_REFERENCE if calibrate else BaselineMethod.ENGINEERING_MODEL
        )

    def build(self, ctx: BaselineContext) -> BaselineResult:
        plant, n = ctx.plant, len(ctx.slots)
        missing: list[str] = []
        if plant.module_temp_coeff_per_c is None:
            missing.append("module power temperature coefficient")
        if not self.calibrate and plant.system_loss_fraction is None:
            missing.append("system loss fraction")
        if self.calibrate and (ctx.request.clean_reference_start is None or ctx.request.clean_reference_end is None):
            missing.append("clean reference period (start and end date)")
        if missing:
            return _unavailable(
                self.method, n, [f"Engineering baseline unavailable - missing: {', '.join(missing)}."]
            )
        gamma = plant.module_temp_coeff_per_c
        assert gamma is not None
        interval_h = ctx.interval_minutes / 60.0
        ac_limit = (
            plant.capacity_ac_kw * interval_h
            if plant.capacity_ac_kw is not None and ctx.interval_minutes != DAILY_MINUTES
            else None
        )
        use_degradation = plant.commissioning_date is not None and plant.annual_degradation_rate is not None

        # Per-slot "unit" energy: everything except the system factor.
        unit: list[float | None] = []
        input_tags: set[ProvenanceTag] = set()
        proxy_used = False
        for slot in ctx.slots:
            poa = poa_irradiation(slot, plant, ctx.interval_minutes, ctx.channels)
            if poa is None:
                unit.append(None)
                continue
            input_tags.add(poa.tag)
            proxy_used = proxy_used or poa.is_proxy
            if poa.value <= 0.0:
                unit.append(0.0)
                continue
            temp = cell_temperature(slot, plant, ctx.interval_minutes, ctx.channels, poa)
            if temp is None:
                unit.append(None)
                continue
            input_tags.add(temp.tag)
            proxy_used = proxy_used or temp.is_proxy
            degr = 1.0
            if use_degradation:
                years = _years_in_operation(plant, slot.day)
                assert years is not None and plant.annual_degradation_rate is not None
                degr = degradation_factor(years, plant.annual_degradation_rate)
            unit.append(expected_energy_kwh(plant.capacity_dc_kwp, poa.value, temp.value, gamma, 0.0, degr))

        if all(v is None for v in unit):
            return _unavailable(
                self.method,
                n,
                ["Engineering baseline unavailable - no interval has both in-plane irradiation and a "
                 "temperature (module, or ambient) from which to estimate cell temperature."],
            )

        parameters: dict[str, float | str | None] = {"temperature_coefficient_per_c": gamma}
        notes: list[str] = []
        tags = sorted(input_tags, key=lambda t: (t.provenance.value, t.source))

        if self.calibrate:
            start, end = ctx.request.clean_reference_start, ctx.request.clean_reference_end
            assert start is not None and end is not None
            num = den = 0.0
            days: set[date] = set()
            for slot, u in zip(ctx.slots, unit, strict=True):
                if not (start <= slot.day <= end) or u is None or u <= 0 or slot.obs is None:
                    continue
                actual = slot.obs.actual_energy_kwh
                if actual is None:
                    continue
                num += actual
                den += u
                days.add(slot.day)
            if den <= 0 or len(days) < 3:
                return _unavailable(
                    self.method,
                    n,
                    [f"Clean-reference calibration needs at least 3 days with irradiation, temperature and "
                     f"actual energy inside {start} .. {end}; found {len(days)}."],
                )
            factor = num / den
            parameters["reference_performance_ratio_stc"] = factor
            parameters["clean_reference_days"] = float(len(days))
            actual_meta = ctx.channels.get(Metric.ACTUAL_ENERGY)
            tags.append(actual_meta.tag if actual_meta is not None else UNKNOWN_TAG)
            notes.append(
                f"System factor calibrated on {len(days)} day(s) declared clean ({start} .. {end}): "
                f"temperature-corrected reference PR = {factor:.4f}. SolarWise cannot verify that the "
                "array was actually clean and fully available during that period."
            )
            if not 0.5 <= factor <= 1.0:
                notes.append(
                    f"The calibrated reference PR ({factor:.3f}) is outside the range usually seen for "
                    "utility-scale plants (0.5-1.0); check capacity, irradiance units and the chosen period."
                )
        else:
            assert plant.system_loss_fraction is not None
            factor = 1.0 - plant.system_loss_fraction
            parameters["system_loss_fraction"] = plant.system_loss_fraction
            notes.append(
                "System losses are a design parameter from the plant configuration; they must cover every "
                "loss of a clean, available array up to the point where actual energy is metered."
            )

        expected: list[float | None] = []
        for u in unit:
            if u is None:
                expected.append(None)
            else:
                value = u * factor
                expected.append(min(value, ac_limit) if ac_limit is not None else value)

        tag = derive(
            tags,
            source="SolarWise engineering model",
            method=(
                "P0 * H_poa * (1 + gamma (Tcell - 25)) * "
                + ("reference PR (clean-period calibration)" if self.calibrate else "(1 - system losses)")
            ),
            model_applied=True,
        )
        if proxy_used:
            notes.append(
                "Some inputs are proxies (daily means or irradiation transposed from the horizontal): "
                "the estimate is coarser than one built from interval-resolved in-plane measurements."
            )
        if not use_degradation:
            notes.append("No commissioning date / degradation rate configured: ageing is not modelled.")
        descriptor = BaselineDescriptor(
            method=self.method,
            irradiance_adjusted=True,
            temperature_adjusted=True,
            # A calibrated factor absorbs the ageing present during the reference period.
            degradation_adjusted=True if (use_degradation or self.calibrate) else None,
            description="Built by SolarWise from irradiation, temperature and plant parameters.",
        )
        meta = ChannelMeta(
            metric=Metric.EXPECTED_ENERGY,
            tag=tag,
            unit="kWh",
            uncertainty_pct=ctx.request.model_uncertainty_pct,
            boundary=_actual_boundary(ctx.channels),
        )
        limitations = descriptor_limitations(descriptor, tag)
        if ctx.request.model_uncertainty_pct is None:
            limitations.append(
                "No uncertainty was declared for the SolarWise-built baseline; the significance of the gap "
                "can only be judged against the materiality threshold."
            )
        return BaselineResult(
            status=BaselineStatus.OK,
            method=self.method,
            descriptor=descriptor,
            meta=meta,
            expected=expected,
            parameters=parameters,
            limitations=limitations,
            notes=notes,
        )


class PvgisTypicalYearBaseline:
    """Long-term monthly averages from PVGIS scaled to the installed capacity.

    Daily data only: PVGIS monthly averages carry no intraday profile.
    """

    method = BaselineMethod.PVGIS_TYPICAL_YEAR

    def build(self, ctx: BaselineContext) -> BaselineResult:
        n = len(ctx.slots)
        months = ctx.request.pvgis_monthly
        if not months:
            return _unavailable(self.method, n, ["No PVGIS monthly averages are stored for this plant."])
        if ctx.interval_minutes != DAILY_MINUTES:
            return _unavailable(
                self.method, n, ["The PVGIS typical-year baseline is only defined for daily data."]
            )
        by_month = {m.month: m for m in months}
        expected: list[float | None] = []
        reference_irr: list[float | None] = []
        rel_sd: list[float] = []
        for slot in ctx.slots:
            entry = by_month.get(slot.day.month)
            if entry is None:
                expected.append(None)
                reference_irr.append(None)
                continue
            expected.append(entry.e_d_kwh_per_kwp * ctx.plant.capacity_dc_kwp)
            reference_irr.append(entry.h_i_d_kwh_m2)
            if entry.sd_m_kwh_per_kwp is not None and entry.e_m_kwh_per_kwp:
                rel_sd.append(entry.sd_m_kwh_per_kwp / entry.e_m_kwh_per_kwp * 100.0)
        tag = modelled(
            ctx.request.pvgis_source or "PVGIS (European Commission, Joint Research Centre)",
            "PVcalc monthly average daily production per kWp x installed capacity",
        )
        descriptor = BaselineDescriptor(
            method=self.method,
            irradiance_adjusted=False,
            temperature_adjusted=False,
            degradation_adjusted=False,
            description="Long-term average conditions; not the weather of the analysed period.",
        )
        uncertainty = sum(rel_sd) / len(rel_sd) if rel_sd else None
        notes = ["Expected energy is a long-term monthly average, identical for every day of a month."]
        if uncertainty is not None:
            notes.append(
                f"Declared uncertainty ({uncertainty:.1f} %) is the PVGIS year-to-year standard deviation of "
                "monthly production; it does not include model bias."
            )
        return BaselineResult(
            status=BaselineStatus.OK,
            method=self.method,
            descriptor=descriptor,
            meta=ChannelMeta(
                metric=Metric.EXPECTED_ENERGY,
                tag=tag,
                unit="kWh",
                uncertainty_pct=uncertainty,
                boundary=_actual_boundary(ctx.channels),
            ),
            expected=expected,
            baseline_irradiation=reference_irr,
            baseline_irradiation_plane=IrradiancePlane.POA,
            limitations=descriptor_limitations(descriptor, tag),
            notes=notes,
        )


def provider_for(method: BaselineMethod) -> BaselineProvider:
    if method in (BaselineMethod.OPERATOR_SUPPLIED, BaselineMethod.TELEMETRY_MODEL, BaselineMethod.UNKNOWN):
        return SuppliedBaseline(method)
    if method is BaselineMethod.ENGINEERING_MODEL:
        return EngineeringModelBaseline(calibrate=False)
    if method is BaselineMethod.HISTORICAL_CLEAN_REFERENCE:
        return EngineeringModelBaseline(calibrate=True)
    if method is BaselineMethod.PVGIS_TYPICAL_YEAR:
        return PvgisTypicalYearBaseline()
    raise ValueError(f"no baseline provider for {method}")  # pragma: no cover - exhaustive above


def resolve_baseline(ctx: BaselineContext) -> BaselineResult:
    """Build the requested baseline; ``AUTO`` prefers a supplied channel, then the engineering model."""
    if ctx.request.method != "AUTO":
        return provider_for(ctx.request.method).build(ctx)
    supplied = SuppliedBaseline().build(ctx)
    if supplied.status is BaselineStatus.OK:
        return supplied
    engineered = EngineeringModelBaseline().build(ctx)
    if engineered.status is BaselineStatus.OK:
        engineered.notes.insert(0, "No expected-energy channel in the dataset: SolarWise built the baseline.")
        return engineered
    return _unavailable(
        BaselineMethod.UNKNOWN,
        len(ctx.slots),
        [*supplied.limitations, *engineered.limitations],
    )
