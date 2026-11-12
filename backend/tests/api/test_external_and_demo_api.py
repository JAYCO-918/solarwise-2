"""HTTP: external data (with ARTIFICIAL fixtures, no network) and the public demonstration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from solarwise import security
from solarwise.demo.scenarios import SCENARIO_KEYS
from tests import support
from tests.integrations.fixtures import nasa_power_payload, pvgis_payload

API = "/api/v1"


def mock_http(app: FastAPI, handler: Callable[[httpx.Request], httpx.Response]) -> list[httpx.Request]:
    """Replace the server's outbound HTTP client; returns the list of requests it will record."""
    seen: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    app.state.http_client = httpx.Client(transport=httpx.MockTransport(recording))
    return seen


def unreachable(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("network is unreachable")


# --------------------------------------------------------------------------- NASA POWER


@pytest.mark.safety
def test_when_the_service_is_unreachable_no_data_are_made_up(client: TestClient, app: FastAPI, engineer: dict[str, str], plant_id: int) -> None:
    mock_http(app, unreachable)
    response = client.post(f"{API}/plants/{plant_id}/weather/nasa-power",
                           json={"start": "2026-05-01", "end": "2026-05-10", "store": True}, headers=engineer)
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "EXTERNAL_UNAVAILABLE"
    assert error["details"] == {"service": "NASA POWER", "failure": "UNAVAILABLE", "data_returned": False}
    assert client.get(f"{API}/plants/{plant_id}/datasets", headers=engineer).json() == []


def test_disabled_external_data_is_reported_without_any_request(engineer_on: Any = None) -> None:
    from solarwise.api.app import create_app
    from solarwise.db.models import Role
    from solarwise.services import users as user_service
    from tests.conftest import login, make_settings

    app = create_app(make_settings(external_data_enabled=False))
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            user_service.create_user(session, email=support.ENGINEER_EMAIL, password=support.ENGINEER_PASSWORD, role=Role.ENGINEER)
            session.commit()
        headers = login(client, support.ENGINEER_EMAIL, support.ENGINEER_PASSWORD)
        plant = client.post(f"{API}/plants", json=support.PLANT_PAYLOAD, headers=headers).json()
        seen = mock_http(app, lambda request: httpx.Response(200, json=nasa_power_payload()))
        response = client.post(f"{API}/plants/{plant['id']}/weather/nasa-power",
                               json={"start": "2026-05-01", "end": "2026-05-10"}, headers=headers)
        assert response.status_code == 503 and response.json()["error"]["code"] == "EXTERNAL_DISABLED"
        assert seen == []
        assert client.get(f"{API}/meta").json()["external_data_enabled"] is False


def test_nasa_power_preview_then_import_as_modelled_weather(client: TestClient, app: FastAPI, engineer: dict[str, str], plant_id: int) -> None:
    seen = mock_http(app, lambda request: httpx.Response(200, json=nasa_power_payload(fill_days=(3,))))
    request = {"start": "2026-05-01", "end": "2026-05-10"}

    preview = client.post(f"{API}/plants/{plant_id}/weather/nasa-power", json=request, headers=engineer)
    assert preview.status_code == 200
    body = preview.json()
    assert body["accepted"] and body["stored"] is False and body["dataset"] is None
    assert body["report"]["rows_plant"] == 10
    assert client.get(f"{API}/plants/{plant_id}/datasets", headers=engineer).json() == []
    assert dict(seen[0].url.params)["latitude"] == "33.5000"  # the plant's coordinates, not the client's

    stored = client.post(f"{API}/plants/{plant_id}/weather/nasa-power", json={**request, "store": True}, headers=engineer)
    assert stored.status_code == 200
    dataset = stored.json()["dataset"]
    assert dataset["kind"] == "WEATHER" and dataset["is_synthetic"] is False
    assert {c["provenance"] for c in dataset["channels"]} == {"MODELLED"}
    assert all("NASA" in c["source"] for c in dataset["channels"])
    series = client.get(f"{API}/datasets/{dataset['id']}/series", headers=engineer).json()
    assert series["columns"]["ghi_kwh_m2"][3] is None and series["columns"]["ghi_kwh_m2"][0] == 7.0
    assert "actual_energy_kwh" not in series["columns"] and "soiling_ratio" not in series["columns"]

    again = client.post(f"{API}/plants/{plant_id}/weather/nasa-power", json={**request, "store": True}, headers=engineer)
    assert again.status_code == 409 and again.json()["error"]["code"] == "DUPLICATE_DATASET"
    # A weather dataset cannot be analysed on its own.
    alone = client.post(f"{API}/datasets/{dataset['id']}/analyses", json={"options": {}}, headers=engineer)
    assert alone.status_code == 422 and alone.json()["error"]["code"] == "NOT_A_PRODUCTION_DATASET"


@pytest.mark.safety
def test_modelled_weather_never_turns_into_soiling_evidence(client: TestClient, app: FastAPI, engineer: dict[str, str], plant_id: int) -> None:
    """Same gap, favourable economics, weather context added - still no soiling measurement, still no CLEAN_NOW."""
    mock_http(app, lambda request: httpx.Response(200, json=nasa_power_payload(days=30)))
    weather = client.post(f"{API}/plants/{plant_id}/weather/nasa-power",
                          json={"start": "2026-05-01", "end": "2026-05-30", "store": True}, headers=engineer).json()["dataset"]
    parts = support.upload_parts(support.daily_csv(with_soiling_channel=False), support.metadata(with_soiling_channel=False))
    production = client.post(f"{API}/plants/{plant_id}/datasets", headers=engineer, **parts).json()["dataset"]
    body = client.post(f"{API}/datasets/{production['id']}/analyses", headers=engineer,
                       json={"options": support.PROFITABLE_OPTIONS, "weather_dataset_id": weather["id"]}).json()
    assert body["decision"] == "INVESTIGATE" and body["operational_authorization"] is False
    provenance = {p["metric"]: p["provenance"] for p in body["result"]["provenance"]}
    assert provenance["ghi"].startswith("MODELLED") and provenance["actual_energy"].startswith("MEASURED")
    gate = next(g for g in body["result"]["recommendation"]["gates"] if g["id"] == "SOILING_EVIDENCE_CREDIBLE")
    assert gate["passed"] is not True


def test_weather_dataset_of_another_plant_cannot_be_combined(client: TestClient, app: FastAPI, engineer: dict[str, str], plant_id: int, dataset_id: int) -> None:
    other = client.post(f"{API}/plants", json=support.PLANT_PAYLOAD, headers=engineer).json()
    mock_http(app, lambda request: httpx.Response(200, json=nasa_power_payload()))
    weather = client.post(f"{API}/plants/{other['id']}/weather/nasa-power",
                          json={"start": "2026-05-01", "end": "2026-05-10", "store": True}, headers=engineer).json()["dataset"]
    response = client.post(f"{API}/datasets/{dataset_id}/analyses", headers=engineer,
                           json={"options": {}, "weather_dataset_id": weather["id"]})
    assert response.status_code == 404


def test_an_unexpected_answer_is_reported_as_such(client: TestClient, app: FastAPI, engineer: dict[str, str], plant_id: int) -> None:
    mock_http(app, lambda request: httpx.Response(200, json={"something": "else"}))
    response = client.post(f"{API}/plants/{plant_id}/weather/nasa-power",
                           json={"start": "2026-05-01", "end": "2026-05-10"}, headers=engineer)
    assert response.status_code == 502 and response.json()["error"]["code"] == "EXTERNAL_UNEXPECTED_RESPONSE"


def test_invalid_period_is_refused_before_any_request(client: TestClient, app: FastAPI, engineer: dict[str, str], plant_id: int) -> None:
    seen = mock_http(app, lambda request: httpx.Response(200, json=nasa_power_payload()))
    response = client.post(f"{API}/plants/{plant_id}/weather/nasa-power",
                           json={"start": "2026-05-10", "end": "2026-05-01"}, headers=engineer)
    assert response.status_code == 422 and seen == []


# --------------------------------------------------------------------------- PVGIS


def test_pvgis_typical_year_is_stored_on_the_plant_with_its_source(client: TestClient, app: FastAPI, engineer: dict[str, str], plant_id: int) -> None:
    assert client.patch(f"{API}/plants/{plant_id}", json={"spec": {"azimuth_deg": 180.0}}, headers=engineer).status_code == 200
    seen = mock_http(app, lambda request: httpx.Response(200, json=pvgis_payload()))
    response = client.post(f"{API}/plants/{plant_id}/pvgis/fetch", json={}, headers=engineer)
    assert response.status_code == 200
    pvgis = response.json()["pvgis"]
    assert pvgis["available"] and len(pvgis["months"]) == 12 and pvgis["source"].startswith("PVGIS 5.3 PVcalc")
    assert dict(seen[0].url.params)["aspect"] == "0.0"


def test_pvgis_needs_the_array_geometry_and_never_assumes_it(client: TestClient, app: FastAPI, engineer: dict[str, str], plant_id: int) -> None:
    seen = mock_http(app, lambda request: httpx.Response(200, json=pvgis_payload()))
    response = client.post(f"{API}/plants/{plant_id}/pvgis/fetch", json={}, headers=engineer)  # no azimuth declared
    assert response.status_code == 422 and response.json()["error"]["code"] == "PLANT_DESCRIPTION_INCOMPLETE"
    assert seen == []


@pytest.mark.safety
def test_pvgis_failure_leaves_the_plant_without_a_typical_year(client: TestClient, app: FastAPI, engineer: dict[str, str], plant_id: int) -> None:
    client.patch(f"{API}/plants/{plant_id}", json={"spec": {"azimuth_deg": 180.0}}, headers=engineer)
    mock_http(app, unreachable)
    response = client.post(f"{API}/plants/{plant_id}/pvgis/fetch", json={}, headers=engineer)
    assert response.status_code == 503 and response.json()["error"]["details"]["data_returned"] is False
    assert client.get(f"{API}/plants/{plant_id}", headers=engineer).json()["pvgis"]["available"] is False


# --------------------------------------------------------------------------- the public demonstration


def test_the_demonstration_shows_ten_synthetic_scenarios_with_their_outcomes(demo_client: TestClient, visitor: dict[str, str]) -> None:
    meta = demo_client.get(f"{API}/meta").json()
    assert meta["demo_mode"] is True and "synthetic" in meta["demo_statement"].lower()
    plant = demo_client.get(f"{API}/plants", headers=visitor).json()[0]
    assert plant["is_demonstration"] and "synthetic" in plant["name"].lower()
    datasets = demo_client.get(f"{API}/plants/{plant['id']}/datasets", headers=visitor).json()
    assert [d["scenario"]["key"] for d in datasets] == list(SCENARIO_KEYS)
    for dataset in datasets:
        assert dataset["is_synthetic"] and dataset["disclaimer"]
        assert all(c["provenance"] == "SYNTHETIC" for c in dataset["channels"])
        latest = dataset["latest_analysis"]
        assert latest["simulated"] is True and latest["operational_authorization"] is False
        assert latest["decision"] == dataset["scenario"]["expected_decision"]
        assert latest["headline"].startswith("SIMULATED DECISION")
    assert sum(d["latest_analysis"]["decision"] == "CLEAN_NOW" for d in datasets) == 1


@pytest.mark.safety
def test_a_simulated_clean_now_is_marked_in_every_export(demo_client: TestClient, visitor: dict[str, str]) -> None:
    plant = demo_client.get(f"{API}/plants", headers=visitor).json()[0]
    datasets = demo_client.get(f"{API}/plants/{plant['id']}/datasets", headers=visitor).json()
    analysis_id = next(d for d in datasets if d["scenario"]["key"] == "S02_confirmed_soiling")["latest_analysis"]["id"]
    detail = demo_client.get(f"{API}/analyses/{analysis_id}", headers=visitor).json()
    assert detail["decision"] == "CLEAN_NOW" and detail["simulated"] and not detail["operational_authorization"]
    assert "No cleaning may be ordered" in detail["result"]["recommendation"]["authorization_note"]

    base = f"{API}/analyses/{analysis_id}/report"
    html = demo_client.get(f"{base}.html", headers=visitor)
    assert "SIMULATED DECISION" in html.text
    assert 'filename="solarwise-SIMULATED-analysis-' in html.headers["content-disposition"]
    assert "SIMULATED DECISION" in demo_client.get(f"{base}.csv", headers=visitor).text
    document = demo_client.get(f"{base}.json", headers=visitor).json()
    assert document["report"]["simulated"] is True and "SIMULATED DECISION" in document["report"]["marking"]
    pdf = demo_client.get(f"{base}.pdf", headers=visitor)
    assert pdf.content.startswith(b"%PDF-") and "SIMULATED" in pdf.headers["content-disposition"]

    explanation = demo_client.post(f"{API}/analyses/{analysis_id}/explanation", headers=visitor).json()
    assert explanation["decision_statement"].startswith("SIMULATED DECISION")


def test_visitors_may_rerun_scenarios_with_their_own_assumptions_privately(demo_client: TestClient) -> None:
    def session() -> dict[str, str]:
        token = demo_client.post(f"{API}/auth/demo-login").json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    first, second = session(), session()
    plant = demo_client.get(f"{API}/plants", headers=first).json()[0]
    datasets = demo_client.get(f"{API}/plants/{plant['id']}/datasets", headers=first).json()
    soiling = next(d for d in datasets if d["scenario"]["key"] == "S02_confirmed_soiling")
    # Without the scenario's economic assumptions the same data no longer justify a cleaning.
    rerun = demo_client.post(f"{API}/datasets/{soiling['id']}/analyses", json={"options": {}}, headers=first)
    assert rerun.status_code == 201
    mine = rerun.json()
    assert (mine["decision"], mine["rule"], mine["simulated"]) == ("INVESTIGATE", "R5", True)

    seen_by_first = demo_client.get(f"{API}/plants/{plant['id']}/analyses", params={"limit": 200}, headers=first).json()
    seen_by_second = demo_client.get(f"{API}/plants/{plant['id']}/analyses", params={"limit": 200}, headers=second).json()
    assert mine["id"] in {a["id"] for a in seen_by_first}
    assert mine["id"] not in {a["id"] for a in seen_by_second}
    assert demo_client.get(f"{API}/analyses/{mine['id']}", headers=second).status_code == 404
    assert demo_client.get(f"{API}/analyses/{mine['id']}/report.pdf", headers=second).status_code == 404
    # The other visitor still sees the scenario as shipped.
    for_second = demo_client.get(f"{API}/plants/{plant['id']}/datasets", headers=second).json()
    assert next(d for d in for_second if d["id"] == soiling["id"])["latest_analysis"]["decision"] == "CLEAN_NOW"


@pytest.mark.safety
def test_visitors_cannot_change_what_every_visitor_sees(demo_client: TestClient, visitor: dict[str, str]) -> None:
    plant = demo_client.get(f"{API}/plants", headers=visitor).json()[0]
    dataset = demo_client.get(f"{API}/plants/{plant['id']}/datasets", headers=visitor).json()[0]
    evidence = {"reference": "X", "evidence_type": "INVERTER_FAULT", "observed_start": "2026-06-20T00:00:00+01:00"}
    attempts = [
        demo_client.patch(f"{API}/plants/{plant['id']}", json={"spec": {"name": "defaced"}}, headers=visitor),
        demo_client.delete(f"{API}/plants/{plant['id']}", headers=visitor),
        demo_client.post(f"{API}/plants/{plant['id']}/evidence", json=evidence, headers=visitor),
        demo_client.post(f"{API}/plants/{plant['id']}/devices", json={"code": "X", "capacity_kwp": 1}, headers=visitor),
        demo_client.post(f"{API}/plants/{plant['id']}/datasets", headers=visitor, **support.upload_parts(support.daily_csv())),
        demo_client.delete(f"{API}/datasets/{dataset['id']}", headers=visitor),
        demo_client.put(f"{API}/plants/{plant['id']}/pvgis", json={"months": [], "source": "x"}, headers=visitor),
        demo_client.post(f"{API}/plants/{plant['id']}/weather/nasa-power", json={"start": "2026-05-01", "end": "2026-05-02"}, headers=visitor),
    ]
    assert all(r.status_code in (403, 422) for r in attempts), [r.status_code for r in attempts]
    assert [r.status_code for r in attempts].count(403) >= 7
    assert demo_client.get(f"{API}/plants/{plant['id']}", headers=visitor).json()["name"] == plant["name"]


@pytest.mark.safety
def test_a_visitors_own_plant_and_measured_looking_upload_remain_a_simulation(demo_client: TestClient, visitor: dict[str, str]) -> None:
    payload = {"spec": {**support.PLANT_PAYLOAD["spec"], "is_demonstration": False}}
    plant = demo_client.post(f"{API}/plants", json=payload, headers=visitor).json()
    assert plant["is_demonstration"] is True and plant["role"] == "OWNER"
    stored = demo_client.post(f"{API}/plants/{plant['id']}/datasets", headers=visitor, **support.upload_parts(support.daily_csv()))
    assert stored.status_code == 201
    body = demo_client.post(f"{API}/datasets/{stored.json()['dataset']['id']}/analyses",
                            json={"options": support.PROFITABLE_OPTIONS}, headers=visitor).json()
    assert body["decision"] == "CLEAN_NOW"
    assert body["simulated"] is True and body["operational_authorization"] is False and body["context"] == "DEMONSTRATION"
    assert body["headline"].startswith("SIMULATED DECISION")
    lifted = demo_client.patch(f"{API}/plants/{plant['id']}", json={"spec": {"is_demonstration": False}}, headers=visitor).json()
    assert lifted["is_demonstration"] is True
    # Other visitors do not see this plant.
    other = {"Authorization": f"Bearer {demo_client.post(f'{API}/auth/demo-login').json()['access_token']}"}
    assert plant["id"] not in {p["id"] for p in demo_client.get(f"{API}/plants", headers=other).json()}
    assert demo_client.get(f"{API}/plants/{plant['id']}", headers=other).status_code == 404


@pytest.mark.safety
def test_evidence_entered_in_a_demonstration_is_recorded_as_synthetic(demo_client: TestClient, visitor: dict[str, str]) -> None:
    plant = demo_client.post(f"{API}/plants", json=support.PLANT_PAYLOAD, headers=visitor).json()
    record = {
        "reference": "ST-1", "evidence_type": "SOILING_MEASUREMENT", "observed_start": "2026-05-29T09:00:00+01:00",
        "provenance": "MEASURED", "source": "typed in by a visitor", "value": 0.9, "soiling_method": "SOILING_STATION",
    }
    created = demo_client.post(f"{API}/plants/{plant['id']}/evidence", json=record, headers=visitor)
    assert created.status_code == 201
    tag = created.json()["record"]["tag"]
    assert tag["provenance"] == "SYNTHETIC" and tag["emulates"] == "MEASURED"
    assert created.json()["provenance_label"].startswith("SYNTHETIC")


def test_demonstration_uploads_are_size_limited(demo_client: TestClient, visitor: dict[str, str]) -> None:
    assert demo_client.get(f"{API}/meta").json()["demo_limits"]["max_upload_mb"] == 5
    plant = demo_client.post(f"{API}/plants", json=support.PLANT_PAYLOAD, headers=visitor).json()
    big = "timestamp,actual_energy_kwh\n" + "2026-05-01,1\n" * 420_000  # about 5.5 MB
    response = demo_client.post(f"{API}/plants/{plant['id']}/datasets/validate", headers=visitor,
                                files={"file": ("big.csv", big.encode(), "text/csv")})
    assert response.status_code == 413


def test_demonstration_visitors_cannot_flood_external_services(demo_client: TestClient, demo_app: FastAPI, visitor: dict[str, str]) -> None:
    plant = demo_client.post(f"{API}/plants", json=support.PLANT_PAYLOAD, headers=visitor).json()
    seen = mock_http(demo_app, lambda request: httpx.Response(200, json=nasa_power_payload()))
    demo_app.state.external_limiter = security.AttemptLimiter(2, 600)
    try:
        request = {"start": "2026-05-01", "end": "2026-05-10"}
        codes = [demo_client.post(f"{API}/plants/{plant['id']}/weather/nasa-power", json=request, headers=visitor).status_code
                 for _ in range(3)]
    finally:
        demo_app.state.external_limiter = security.AttemptLimiter(20, 600)
    assert codes == [200, 200, 429] and len(seen) == 2
