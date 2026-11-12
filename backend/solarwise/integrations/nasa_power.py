"""NASA POWER daily point data (weather context).

Service: NASA Langley Research Center, Prediction Of Worldwide Energy Resources
(POWER), Daily API - ``/api/temporal/daily/point``.

What the data are, and are not:

* Irradiance is derived from satellite observations (CERES products), the
  meteorology from the MERRA-2 reanalysis.  Values are averages over a grid cell
  of roughly half a degree to one degree.  They are **modelled** data: SolarWise
  labels them MODELLED and never lets them count as a measurement.
* They describe the weather.  They contain no information about dust on the
  modules and are never used as soiling evidence.
* Daily values follow local solar time (``time-standard=LST``) and are assigned
  to the plant's local calendar day; the two can differ by up to about an hour
  at the day boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from solarwise.core.models import IrradiancePlane, Metric
from solarwise.core.provenance import Provenance
from solarwise.ingestion.parser import RawTable
from solarwise.ingestion.schema import ChannelDeclaration, DatasetMetadata
from solarwise.integrations.base import IntegrationError, IntegrationFailure, get_json

SERVICE = "NASA POWER"
ENDPOINT = "/api/temporal/daily/point"
MAX_DAYS = 366

#: POWER parameter -> (canonical column, metric, accepted units -> factor to the canonical unit).
PARAMETERS: dict[str, tuple[str, Metric, dict[str, float]]] = {
    "ALLSKY_SFC_SW_DWN": ("ghi_kwh_m2", Metric.GHI, {"kw-hr/m^2/day": 1.0, "kwh/m^2/day": 1.0, "mj/m^2/day": 1.0 / 3.6}),
    "T2M": ("ambient_temp_c", Metric.AMBIENT_TEMP, {"c": 1.0}),
    "WS2M": ("wind_speed_ms", Metric.WIND_SPEED, {"m/s": 1.0}),
    "RH2M": ("relative_humidity_pct", Metric.RELATIVE_HUMIDITY, {"%": 1.0}),
    "PRECTOTCORR": ("precipitation_mm", Metric.PRECIPITATION, {"mm/day": 1.0}),
}

_NOTES = {
    Metric.GHI: "All-sky surface shortwave downward irradiance; satellite-derived grid-cell average, not a site pyranometer.",
    Metric.AMBIENT_TEMP: "Air temperature at 2 m, mean over 24 hours (not the daylight mean); reanalysis grid-cell value.",
    Metric.WIND_SPEED: "Wind speed at 2 m, daily mean; reanalysis grid-cell value.",
    Metric.RELATIVE_HUMIDITY: "Relative humidity at 2 m, daily mean; reanalysis grid-cell value.",
    Metric.PRECIPITATION: "Bias-corrected total precipitation; reanalysis grid-cell value (local showers may be missed).",
}


@dataclass
class PowerDaily:
    latitude: float
    longitude: float
    start: date
    end: date
    #: day -> canonical column -> value (``None`` = the service's fill value, i.e. no data).
    days: dict[date, dict[str, float | None]]
    columns: list[str]
    source: str
    api_version: str | None
    retrieved_at: datetime
    messages: list[str] = field(default_factory=list)

    @property
    def missing_values(self) -> int:
        return sum(1 for values in self.days.values() for c in self.columns if values.get(c) is None)


def parse_response(payload: dict[str, Any], *, latitude: float, longitude: float, start: date, end: date,
                   retrieved_at: datetime) -> PowerDaily:
    """Interpret a POWER daily answer.  Anything not matching the documented structure is refused."""
    def unexpected(message: str) -> IntegrationError:
        return IntegrationError(SERVICE, IntegrationFailure.UNEXPECTED_RESPONSE, message)

    properties = payload.get("properties")
    series = properties.get("parameter") if isinstance(properties, dict) else None
    if not isinstance(series, dict) or not series:
        raise unexpected("the answer contains no 'properties.parameter' object")
    header = payload.get("header") if isinstance(payload.get("header"), dict) else {}
    assert isinstance(header, dict)
    fill = header.get("fill_value", -999.0)
    if not isinstance(fill, int | float):
        raise unexpected("'header.fill_value' is not a number")
    described = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
    assert isinstance(described, dict)

    days: dict[date, dict[str, float | None]] = {}
    columns: list[str] = []
    for name, (column, _metric, units) in PARAMETERS.items():
        values = series.get(name)
        if values is None:
            continue
        if not isinstance(values, dict):
            raise unexpected(f"parameter {name} is not an object of daily values")
        info = described.get(name)
        unit = str(info.get("units", "")).strip().lower() if isinstance(info, dict) else ""
        if unit not in units:
            # A unit that is not recognised is not guessed: the whole parameter is refused.
            raise unexpected(f"parameter {name} is reported in an unrecognised unit {unit!r}")
        factor = units[unit]
        columns.append(column)
        for key, raw in values.items():
            try:
                day = datetime.strptime(str(key), "%Y%m%d").date()
            except ValueError as exc:
                raise unexpected(f"parameter {name}: '{key}' is not a YYYYMMDD date") from exc
            if day < start or day > end:
                continue
            if raw is None or not isinstance(raw, int | float) or isinstance(raw, bool):
                value: float | None = None
            elif raw == fill or raw <= -990:
                value = None
            else:
                value = float(raw) * factor
            days.setdefault(day, {})[column] = value
    if not columns:
        raise unexpected("none of the requested parameters is present in the answer")
    api = header.get("api")
    messages = payload.get("messages")
    return PowerDaily(
        latitude=latitude, longitude=longitude, start=start, end=end,
        days=dict(sorted(days.items())), columns=columns,
        source=str(header.get("title") or "NASA POWER daily data"),
        api_version=str(api.get("version")) if isinstance(api, dict) and api.get("version") else None,
        retrieved_at=retrieved_at,
        messages=[str(m) for m in messages] if isinstance(messages, list) else [],
    )


def fetch_daily(
    client: httpx.Client, base_url: str, *, latitude: float, longitude: float, start: date, end: date,
    enabled: bool = True, now: datetime | None = None,
) -> PowerDaily:
    if end < start:
        raise ValueError("the end date precedes the start date")
    if (end - start).days + 1 > MAX_DAYS:
        raise ValueError(f"at most {MAX_DAYS} days per request")
    params = {
        "parameters": ",".join(PARAMETERS),
        "community": "RE",
        "longitude": f"{longitude:.4f}",
        "latitude": f"{latitude:.4f}",
        "start": start.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
        "format": "JSON",
        "time-standard": "LST",
    }
    payload = get_json(client, SERVICE, base_url.rstrip("/") + ENDPOINT, params, enabled=enabled)
    return parse_response(
        payload, latitude=latitude, longitude=longitude, start=start, end=end, retrieved_at=now or datetime.now(UTC)
    )


def to_upload(data: PowerDaily, *, timezone: str) -> tuple[RawTable, DatasetMetadata]:
    """Express the series as an upload, so that it passes through the same validation as any file."""
    columns = ["timestamp", *data.columns]
    rows: list[dict[str, Any]] = []
    day = data.start
    while day <= data.end:
        values = data.days.get(day)
        if values is not None:
            rows.append({"timestamp": day.isoformat(), **{c: values.get(c) for c in data.columns}})
        day += timedelta(days=1)
    source = (
        f"{data.source} (NASA Langley Research Center POWER project), grid cell containing "
        f"{data.latitude:.3f}, {data.longitude:.3f}; retrieved {data.retrieved_at.date().isoformat()}"
    )
    channels: dict[Metric, ChannelDeclaration] = {}
    for _name, (column, metric, _units) in PARAMETERS.items():
        if column not in data.columns:
            continue
        channels[metric] = ChannelDeclaration(
            provenance=Provenance.MODELLED,
            source=source,
            method="satellite-derived irradiance (CERES) and MERRA-2 reanalysis meteorology",
            plane=IrradiancePlane.GHI if metric is Metric.GHI else None,
            notes=_NOTES[metric],
        )
    metadata = DatasetMetadata(
        name=f"NASA POWER weather {data.start.isoformat()} to {data.end.isoformat()}",
        description=(
            "Modelled weather context from NASA POWER. Grid-cell averages, not site measurements; they say "
            "nothing about soiling. Daily values follow local solar time."
        ),
        timezone=timezone,
        interval_minutes=1440,
        channels=channels,
    )
    return RawTable(columns=columns, rows=rows, file_format="JSON"), metadata
