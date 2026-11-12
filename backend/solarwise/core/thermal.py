"""Cell-temperature and in-plane irradiation estimates for a single interval.

Each helper returns the value together with an explicit *basis* string and a
provenance tag, so that a measured module temperature is never confused with a
temperature inferred from ambient conditions, nor a pyranometer reading with a
transposed satellite value.
"""

from __future__ import annotations

from dataclasses import dataclass

from solarwise.core.models import ChannelMeta, Metric, PlantSpec, TrackingType
from solarwise.core.provenance import UNKNOWN_TAG, ProvenanceTag, derive
from solarwise.core.pv_model import (
    cell_temperature_faiman,
    cell_temperature_noct,
    energy_weighted_irradiance_from_daily,
)
from solarwise.core.solar_geometry import day_of_year, daylight_hours, transpose_daily_isotropic
from solarwise.core.timeline import DAILY_MINUTES, Slot

#: NOCT used when the plant configuration does not provide one.
DEFAULT_NOCT_C = 45.0

BASIS_MEASURED_MODULE = "MEASURED_MODULE_TEMPERATURE"
BASIS_FAIMAN = "MODELLED_FROM_AMBIENT_FAIMAN"
BASIS_NOCT = "MODELLED_FROM_AMBIENT_NOCT"
BASIS_POA_MEASURED = "IN_PLANE_CHANNEL"
BASIS_POA_TRANSPOSED = "TRANSPOSED_FROM_GHI_ISOTROPIC"


@dataclass(frozen=True, slots=True)
class Estimate:
    value: float
    basis: str
    tag: ProvenanceTag
    #: True when the estimate rests on a simplifying proxy rather than on
    #: interval-resolved inputs (for example daily means).
    is_proxy: bool = False


def _tag(channels: dict[Metric, ChannelMeta], metric: Metric) -> ProvenanceTag:
    meta = channels.get(metric)
    return meta.tag if meta is not None else UNKNOWN_TAG


def poa_irradiation(
    slot: Slot, plant: PlantSpec, interval_minutes: int, channels: dict[Metric, ChannelMeta]
) -> Estimate | None:
    """In-plane irradiation for the slot [kWh/m2].

    Uses the in-plane channel when present.  For *daily* data of a *fixed*
    array with a known tilt, global horizontal irradiation is transposed with
    the isotropic-sky model; the result is then a modelled quantity.
    """
    obs = slot.obs
    if obs is None:
        return None
    if obs.poa_irradiation_kwh_m2 is not None:
        return Estimate(obs.poa_irradiation_kwh_m2, BASIS_POA_MEASURED, _tag(channels, Metric.POA_IRRADIATION))
    if (
        obs.ghi_kwh_m2 is not None
        and interval_minutes == DAILY_MINUTES
        and plant.tracking is TrackingType.FIXED
        and plant.tilt_deg is not None
    ):
        try:
            transposed = transpose_daily_isotropic(
                obs.ghi_kwh_m2, plant.latitude, plant.tilt_deg, day_of_year(slot.day)
            )
        except ValueError:
            return None
        if transposed is None:
            return None
        tag = derive(
            [_tag(channels, Metric.GHI)],
            source="SolarWise transposition",
            method="daily GHI -> POA, Erbs diffuse fraction + Liu-Jordan isotropic sky",
            model_applied=True,
        )
        return Estimate(transposed.poa_kwh_m2, BASIS_POA_TRANSPOSED, tag, is_proxy=True)
    return None


def cell_temperature(
    slot: Slot,
    plant: PlantSpec,
    interval_minutes: int,
    channels: dict[Metric, ChannelMeta],
    poa: Estimate | None,
) -> Estimate | None:
    """Cell temperature for the slot [degC].

    Order of preference:

    1. the module-temperature channel (used as is);
    2. the Faiman model from ambient temperature, irradiance and wind speed;
    3. the NOCT model from ambient temperature and irradiance.

    With daily data the irradiance driving (2) and (3) is the energy-weighted
    mean of an assumed half-sine day, which makes the result a proxy.
    """
    obs = slot.obs
    if obs is None:
        return None
    if obs.module_temp_c is not None:
        return Estimate(obs.module_temp_c, BASIS_MEASURED_MODULE, _tag(channels, Metric.MODULE_TEMP))
    if obs.ambient_temp_c is None or poa is None:
        return None

    daily = interval_minutes == DAILY_MINUTES
    if daily:
        irradiance = energy_weighted_irradiance_from_daily(
            poa.value, daylight_hours(plant.latitude, day_of_year(slot.day))
        )
    else:
        irradiance = poa.value * 1000.0 / (interval_minutes / 60.0)

    inputs = [_tag(channels, Metric.AMBIENT_TEMP), poa.tag]
    if obs.wind_speed_ms is not None:
        value = cell_temperature_faiman(obs.ambient_temp_c, irradiance, obs.wind_speed_ms)
        basis = BASIS_FAIMAN
        inputs.append(_tag(channels, Metric.WIND_SPEED))
        method = "Faiman (2008): T = Ta + G / (25.0 + 6.84 v)"
    else:
        noct = plant.noct_c if plant.noct_c is not None else DEFAULT_NOCT_C
        value = cell_temperature_noct(obs.ambient_temp_c, irradiance, noct)
        basis = BASIS_NOCT
        method = f"NOCT model: T = Ta + (NOCT - 20) / 800 * G, NOCT = {noct:g} degC"
    tag = derive(inputs, source="SolarWise thermal model", method=method, model_applied=True)
    return Estimate(value, basis, tag, is_proxy=daily or poa.is_proxy)
