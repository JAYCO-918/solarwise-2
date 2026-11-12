"""PVGIS ``PVcalc``: long-term monthly averages for the typical-year baseline.

Service: European Commission, Joint Research Centre - Photovoltaic Geographical
Information System, non-interactive service ``/api/<version>/PVcalc``.

The result is a **modelled long-term average** (satellite irradiance database
and a generic performance model).  It is not the weather of any particular
period: a baseline built from it is declared "not adjusted to actual irradiance
or temperature", and SolarWise treats it accordingly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from solarwise.core.baseline import PvgisMonth
from solarwise.core.models import PlantSpec, TrackingType
from solarwise.integrations.base import IntegrationError, IntegrationFailure, get_json

SERVICE = "PVGIS"
DEFAULT_API_VERSION = "v5_3"


@dataclass
class PvgisTypicalYear:
    months: list[PvgisMonth]
    source: str
    loss_pct: float
    tilt_deg: float
    aspect_deg: float
    radiation_database: str | None
    retrieved_at: datetime


def request_parameters(plant: PlantSpec, loss_pct: float | None) -> dict[str, Any]:
    """PVcalc parameters for 1 kWp.  Missing engineering inputs are an error, not a default."""
    if plant.tracking is not TrackingType.FIXED:
        raise ValueError("the PVGIS typical-year import handles fixed-tilt plants only")
    if plant.tilt_deg is None or plant.azimuth_deg is None:
        raise ValueError("declare the tilt and azimuth of the array before requesting a PVGIS baseline")
    if loss_pct is None:
        if plant.system_loss_fraction is None:
            raise ValueError("declare the system losses of the plant (or pass them with the request)")
        loss_pct = plant.system_loss_fraction * 100.0
    if not 0.0 <= loss_pct < 60.0:
        raise ValueError("system losses must lie between 0 and 60 %")
    # PVGIS: aspect 0 = south, 90 = west, -90 = east.  SolarWise: azimuth clockwise from north.
    aspect = plant.azimuth_deg - 180.0
    if aspect > 180.0:
        aspect -= 360.0
    return {
        "lat": f"{plant.latitude:.4f}",
        "lon": f"{plant.longitude:.4f}",
        "peakpower": "1",
        "loss": f"{loss_pct:.2f}",
        "angle": f"{plant.tilt_deg:.1f}",
        "aspect": f"{aspect:.1f}",
        "mountingplace": "free",
        "pvtechchoice": "crystSi",
        "outputformat": "json",
    }


def parse_response(payload: dict[str, Any], *, retrieved_at: datetime, version: str) -> PvgisTypicalYear:
    def unexpected(message: str) -> IntegrationError:
        return IntegrationError(SERVICE, IntegrationFailure.UNEXPECTED_RESPONSE, message)

    outputs = payload.get("outputs")
    monthly = outputs.get("monthly") if isinstance(outputs, dict) else None
    rows = monthly.get("fixed") if isinstance(monthly, dict) else None
    if not isinstance(rows, list) or len(rows) != 12:
        raise unexpected("the answer does not contain twelve monthly values under 'outputs.monthly.fixed'")
    months: list[PvgisMonth] = []
    for row in rows:
        if not isinstance(row, dict):
            raise unexpected("a monthly entry is not an object")
        try:
            months.append(
                PvgisMonth(
                    month=int(row["month"]),
                    e_d_kwh_per_kwp=float(row["E_d"]),
                    h_i_d_kwh_m2=float(row["H(i)_d"]),
                    e_m_kwh_per_kwp=float(row["E_m"]) if row.get("E_m") is not None else None,
                    sd_m_kwh_per_kwp=float(row["SD_m"]) if row.get("SD_m") is not None else None,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise unexpected(f"a monthly entry lacks a documented field ({exc})") from exc
    if sorted(m.month for m in months) != list(range(1, 13)):
        raise unexpected("the monthly values do not cover the twelve months")
    inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
    assert isinstance(inputs, dict)
    meteo = inputs.get("meteo_data") if isinstance(inputs.get("meteo_data"), dict) else {}
    mounting = inputs.get("mounting_system") if isinstance(inputs.get("mounting_system"), dict) else {}
    fixed = mounting.get("fixed") if isinstance(mounting, dict) and isinstance(mounting.get("fixed"), dict) else {}
    pv = inputs.get("pv_module") if isinstance(inputs.get("pv_module"), dict) else {}
    assert isinstance(meteo, dict) and isinstance(fixed, dict) and isinstance(pv, dict)

    def nested(container: dict[str, Any], key: str) -> float | None:
        item = container.get(key)
        value = item.get("value") if isinstance(item, dict) else None
        return float(value) if isinstance(value, int | float) else None

    database = meteo.get("radiation_db")
    tilt, aspect = nested(fixed, "slope"), nested(fixed, "azimuth")
    loss = pv.get("system_loss")
    return PvgisTypicalYear(
        months=sorted(months, key=lambda m: m.month),
        source=(
            f"PVGIS {version.lstrip('v').replace('_', '.')} PVcalc (European Commission, Joint Research Centre)"
            + (f", radiation database {database}" if database else "")
            + f"; retrieved {retrieved_at.date().isoformat()}"
        ),
        loss_pct=float(loss) if isinstance(loss, int | float) else float("nan"),
        tilt_deg=tilt if tilt is not None else float("nan"),
        aspect_deg=aspect if aspect is not None else float("nan"),
        radiation_database=str(database) if database else None,
        retrieved_at=retrieved_at,
    )


def fetch_typical_year(
    client: httpx.Client, base_url: str, plant: PlantSpec, *, loss_pct: float | None = None,
    version: str = DEFAULT_API_VERSION, enabled: bool = True, now: datetime | None = None,
) -> PvgisTypicalYear:
    params = request_parameters(plant, loss_pct)
    payload = get_json(client, SERVICE, f"{base_url.rstrip('/')}/api/{version}/PVcalc", params, enabled=enabled)
    return parse_response(payload, retrieved_at=now or datetime.now(UTC), version=version)
