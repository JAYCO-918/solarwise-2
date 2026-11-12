"""External-data clients: parse what is documented, refuse what is not, never substitute data.

Every payload used here is an ARTIFICIAL fixture (see ``fixtures.py``).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest

from solarwise.core.models import Metric, TrackingType
from solarwise.core.provenance import Provenance
from solarwise.ingestion.validator import validate_table
from solarwise.integrations import nasa_power, pvgis
from solarwise.integrations.base import IntegrationError, IntegrationFailure, get_json
from tests.builders import PLANT
from tests.integrations.fixtures import nasa_power_payload, pvgis_payload

NOW = datetime(2026, 7, 1, tzinfo=UTC)
START, END = date(2026, 5, 1), date(2026, 5, 10)


def client_returning(payload: Any, status: int = 200, seen: list[httpx.Request] | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if isinstance(payload, bytes):
            return httpx.Response(status, content=payload)
        return httpx.Response(status, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def client_raising(error: Exception) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    return httpx.Client(transport=httpx.MockTransport(handler))


# --------------------------------------------------------------------------- failures are failures


@pytest.mark.safety
@pytest.mark.parametrize(
    ("client", "failure"),
    [
        (client_raising(httpx.ConnectError("no route to host")), IntegrationFailure.UNAVAILABLE),
        (client_raising(httpx.ReadTimeout("timed out")), IntegrationFailure.UNAVAILABLE),
        (client_returning({"message": "down"}, 503), IntegrationFailure.UNAVAILABLE),
        (client_returning({"messages": ["latitude out of range"]}, 422), IntegrationFailure.REJECTED),
        (client_returning(b"<html>gateway</html>"), IntegrationFailure.UNEXPECTED_RESPONSE),
        (client_returning([1, 2, 3]), IntegrationFailure.UNEXPECTED_RESPONSE),
    ],
)
def test_transport_failures_are_classified_and_raise(client: httpx.Client, failure: IntegrationFailure) -> None:
    with pytest.raises(IntegrationError) as raised:
        get_json(client, "TEST", "https://service.invalid/x", {})
    assert raised.value.failure is failure and raised.value.service == "TEST"


@pytest.mark.safety
def test_disabled_integrations_make_no_request() -> None:
    seen: list[httpx.Request] = []
    with pytest.raises(IntegrationError) as raised:
        get_json(client_returning({}, seen=seen), "TEST", "https://service.invalid/x", {}, enabled=False)
    assert raised.value.failure is IntegrationFailure.DISABLED and seen == []


def test_rejection_message_of_the_service_is_passed_on() -> None:
    with pytest.raises(IntegrationError, match="latitude out of range"):
        get_json(client_returning({"messages": ["latitude out of range"]}, 422), "TEST", "https://service.invalid/x", {})


# --------------------------------------------------------------------------- NASA POWER


def fetch_power(payload: Any, **kwargs: Any) -> nasa_power.PowerDaily:
    return nasa_power.fetch_daily(client_returning(payload), "https://power.invalid", latitude=33.5, longitude=6.8,
                                  start=START, end=END, now=NOW, **kwargs)


def test_power_request_follows_the_documented_interface() -> None:
    seen: list[httpx.Request] = []
    nasa_power.fetch_daily(client_returning(nasa_power_payload(), seen=seen), "https://power.invalid/", latitude=33.5,
                           longitude=6.8, start=START, end=END, now=NOW)
    request = seen[0]
    assert request.url.path == "/api/temporal/daily/point"
    params = dict(request.url.params)
    assert params["start"] == "20260501" and params["end"] == "20260510"
    assert params["latitude"] == "33.5000" and params["longitude"] == "6.8000"
    assert params["community"] == "RE" and params["format"] == "JSON" and params["time-standard"] == "LST"
    assert set(params["parameters"].split(",")) == {"ALLSKY_SFC_SW_DWN", "T2M", "WS2M", "RH2M", "PRECTOTCORR"}
    assert request.headers["user-agent"].startswith("SolarWise")


def test_power_values_are_read_in_canonical_units() -> None:
    data = fetch_power(nasa_power_payload())
    assert data.columns == ["ghi_kwh_m2", "ambient_temp_c", "wind_speed_ms", "relative_humidity_pct", "precipitation_mm"]
    assert len(data.days) == 10 and data.missing_values == 0
    assert data.days[date(2026, 5, 1)] == {
        "ghi_kwh_m2": 7.0, "ambient_temp_c": 24.0, "wind_speed_ms": 3.0, "relative_humidity_pct": 30.0, "precipitation_mm": 0.0,
    }
    assert data.api_version == "v0.0.0-artificial-fixture" and data.retrieved_at == NOW


def test_power_irradiation_in_megajoules_is_converted() -> None:
    data = fetch_power(nasa_power_payload(ghi_unit="MJ/m^2/day"))
    assert data.days[date(2026, 5, 1)]["ghi_kwh_m2"] == pytest.approx(7.0 / 3.6)


@pytest.mark.safety
def test_power_fill_values_become_missing_not_numbers() -> None:
    data = fetch_power(nasa_power_payload(fill_days=(2, 5)))
    assert data.days[date(2026, 5, 3)]["ghi_kwh_m2"] is None
    assert data.days[date(2026, 5, 6)]["ambient_temp_c"] is None
    assert data.missing_values == 10  # two days x five parameters
    assert all(v is None or v > -100 for values in data.days.values() for v in values.values())


@pytest.mark.safety
def test_power_unknown_unit_is_refused_rather_than_guessed() -> None:
    with pytest.raises(IntegrationError) as raised:
        fetch_power(nasa_power_payload(ghi_unit="W/m^2"))
    assert raised.value.failure is IntegrationFailure.UNEXPECTED_RESPONSE and "unrecognised unit" in raised.value.message


@pytest.mark.parametrize(
    "payload",
    [{}, {"properties": {}}, {"properties": {"parameter": {}}}, {"properties": {"parameter": {"SOMETHING_ELSE": {}}}},
     {"properties": {"parameter": {"T2M": [1, 2, 3]}}, "parameters": {"T2M": {"units": "C"}}},
     {"properties": {"parameter": {"T2M": {"2026-05-01": 20.0}}}, "parameters": {"T2M": {"units": "C"}}}],
)
def test_power_answers_of_another_shape_are_refused(payload: dict[str, Any]) -> None:
    with pytest.raises(IntegrationError) as raised:
        fetch_power(payload)
    assert raised.value.failure is IntegrationFailure.UNEXPECTED_RESPONSE


def test_power_request_limits() -> None:
    with pytest.raises(ValueError, match="precedes"):
        nasa_power.fetch_daily(client_returning({}), "https://power.invalid", latitude=0, longitude=0, start=END, end=START)
    with pytest.raises(ValueError, match="at most"):
        nasa_power.fetch_daily(client_returning({}), "https://power.invalid", latitude=0, longitude=0,
                               start=date(2024, 1, 1), end=date(2026, 1, 1))


@pytest.mark.safety
def test_power_data_enter_as_modelled_weather_and_pass_normal_validation() -> None:
    table, metadata = nasa_power.to_upload(fetch_power(nasa_power_payload(fill_days=(4,))), timezone="Africa/Algiers")
    assert {c.provenance for c in metadata.channels.values()} == {Provenance.MODELLED}
    assert Metric.SOILING_RATIO not in metadata.channels and Metric.ACTUAL_ENERGY not in metadata.channels
    assert "not site measurements" in metadata.description and "nothing about soiling" in metadata.description
    report, parsed = validate_table(table, metadata, plant=PLANT, now=NOW)
    assert report.accepted and parsed is not None
    assert parsed.interval_minutes == 1440 and len(parsed.observations) == 10
    assert parsed.observations[4].ghi_kwh_m2 is None  # the fill value stays missing
    assert parsed.observations[0].ghi_kwh_m2 == 7.0
    assert all(o.actual_energy_kwh is None and o.soiling_ratio is None for o in parsed.observations)
    assert parsed.channels[Metric.GHI].tag.provenance is Provenance.MODELLED
    assert "NASA" in parsed.channels[Metric.GHI].tag.source


# --------------------------------------------------------------------------- PVGIS


def test_pvgis_request_converts_the_azimuth_convention() -> None:
    south = PLANT.model_copy(update={"azimuth_deg": 180.0})
    params = pvgis.request_parameters(south, None)
    assert params["aspect"] == "0.0" and params["angle"] == "30.0" and params["loss"] == "14.00"
    assert params["peakpower"] == "1" and params["outputformat"] == "json"
    assert pvgis.request_parameters(PLANT.model_copy(update={"azimuth_deg": 270.0}), 10.0)["aspect"] == "90.0"   # west
    assert pvgis.request_parameters(PLANT.model_copy(update={"azimuth_deg": 90.0}), 10.0)["aspect"] == "-90.0"   # east
    assert pvgis.request_parameters(PLANT.model_copy(update={"azimuth_deg": 0.0}), 10.0)["aspect"] == "-180.0"   # north


@pytest.mark.safety
@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"azimuth_deg": None}, "tilt and azimuth"),
        ({"azimuth_deg": 180.0, "tilt_deg": None}, "tilt and azimuth"),
        ({"azimuth_deg": 180.0, "system_loss_fraction": None}, "system losses"),
        ({"azimuth_deg": 180.0, "tracking": TrackingType.SINGLE_AXIS}, "fixed-tilt"),
    ],
)
def test_pvgis_request_needs_declared_geometry_and_losses(change: dict[str, Any], fragment: str) -> None:
    """A missing engineering input is an error, not an occasion to assume a default."""
    with pytest.raises(ValueError, match=fragment):
        pvgis.request_parameters(PLANT.model_copy(update=change), None)


def test_pvgis_monthly_values_are_read_with_their_source() -> None:
    seen: list[httpx.Request] = []
    plant = PLANT.model_copy(update={"azimuth_deg": 180.0})
    typical = pvgis.fetch_typical_year(client_returning(pvgis_payload(), seen=seen), "https://pvgis.invalid", plant, now=NOW)
    assert seen[0].url.path == "/api/v5_3/PVcalc"
    assert [m.month for m in typical.months] == list(range(1, 13))
    assert typical.months[0].e_d_kwh_per_kwp == 3.7 and typical.months[0].h_i_d_kwh_m2 == 4.75
    assert typical.loss_pct == 14.0 and typical.tilt_deg == 30.0 and typical.aspect_deg == 0.0
    assert "PVGIS 5.3" in typical.source and "ARTIFICIAL-FIXTURE-DB" in typical.source and "2026-07-01" in typical.source


@pytest.mark.parametrize(
    "payload",
    [{}, {"outputs": {}}, {"outputs": {"monthly": {"fixed": []}}}, pvgis_payload(months=11),
     {"outputs": {"monthly": {"fixed": [{"month": m} for m in range(1, 13)]}}},
     {"outputs": {"monthly": {"fixed": [{"month": 1, "E_d": 4.0, "H(i)_d": 5.0}] * 12}}}],
)
def test_pvgis_answers_of_another_shape_are_refused(payload: dict[str, Any]) -> None:
    plant = PLANT.model_copy(update={"azimuth_deg": 180.0})
    with pytest.raises(IntegrationError) as raised:
        pvgis.fetch_typical_year(client_returning(payload), "https://pvgis.invalid", plant, now=NOW)
    assert raised.value.failure is IntegrationFailure.UNEXPECTED_RESPONSE
