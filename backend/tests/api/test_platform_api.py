"""HTTP: error shape, security headers, size limits, static files, reference material, advisory endpoints."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from solarwise.api.app import create_app
from solarwise.core.rules import GATES, RULES
from tests import support
from tests.conftest import make_settings

API = "/api/v1"


# --------------------------------------------------------------------------- errors


def test_every_error_has_the_same_shape(client: TestClient, engineer: dict[str, str]) -> None:
    responses = [
        client.get(f"{API}/plants"),  # 401
        client.get(f"{API}/plants/999", headers=engineer),  # 404 from a service
        client.get(f"{API}/does-not-exist", headers=engineer),  # 404 unknown endpoint
        client.post(f"{API}/plants", json={"spec": {}}, headers=engineer),  # 422 validation
        client.post(f"{API}/plants", content=b"{not json", headers={**engineer, "Content-Type": "application/json"}),
        client.delete(f"{API}/auth/me", headers=engineer),  # 405
        client.put(f"{API}/plants/1/datasets", headers=engineer),  # 405
    ]
    assert [r.status_code for r in responses] == [401, 404, 404, 422, 422, 405, 405]
    # HEAD is offered wherever GET is.
    assert responses[-2].headers["allow"] == "GET, HEAD" and responses[-1].headers["allow"] == "GET, HEAD, POST"
    for response in responses:
        body = response.json()
        assert set(body) == {"error"} and set(body["error"]) == {"code", "message", "details"}
        assert isinstance(body["error"]["code"], str) and isinstance(body["error"]["message"], str)


def test_unknown_api_paths_are_json_404_not_the_web_page(client: TestClient) -> None:
    response = client.get("/api/v2/anything")
    assert response.status_code == 404 and response.headers["content-type"].startswith("application/json")


def test_internal_errors_do_not_leak_details(monkeypatch: pytest.MonkeyPatch) -> None:
    from solarwise.api.routes import reference

    def explode() -> str:
        raise RuntimeError("secret internal detail: /etc/passwd")

    monkeypatch.setattr(reference.reference_service, "statement", explode)
    app = create_app(make_settings())
    with TestClient(app, raise_server_exceptions=False) as client:
        with app.state.session_factory() as session:
            from solarwise.db.models import Role
            from solarwise.services import users as user_service

            user_service.create_user(session, email=support.ENGINEER_EMAIL, password=support.ENGINEER_PASSWORD, role=Role.ENGINEER)
            session.commit()
        token = client.post(f"{API}/auth/login", json={"email": support.ENGINEER_EMAIL, "password": support.ENGINEER_PASSWORD}).json()["access_token"]
        response = client.get(f"{API}/reference/economic", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 500
    assert response.json() == {"error": {"code": "INTERNAL_ERROR", "message": "an unexpected error occurred", "details": None}}
    assert "secret" not in response.text and "Traceback" not in response.text
    assert response.headers["x-content-type-options"] == "nosniff"


def test_a_failed_request_leaves_nothing_behind(client: TestClient, engineer: dict[str, str], plant_id: int) -> None:
    """A request that fails is rolled back as a whole."""
    bad = "timestamp,actual_energy_kwh\nnot-a-date,5\n"
    assert client.post(f"{API}/plants/{plant_id}/datasets", headers=engineer, **support.upload_parts(bad)).status_code == 422
    assert client.get(f"{API}/plants/{plant_id}/datasets", params={"include_archived": True}, headers=engineer).json() == []


# --------------------------------------------------------------------------- headers


@pytest.mark.safety
def test_security_headers_are_on_every_response(client: TestClient, engineer: dict[str, str]) -> None:
    for response in (client.get("/"), client.get(f"{API}/health"), client.get(f"{API}/plants"),
                     client.get(f"{API}/plants", headers=engineer), client.get("/api/nope")):
        headers = response.headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["referrer-policy"] == "no-referrer"
        assert headers["x-frame-options"] == "SAMEORIGIN"
        csp = headers["content-security-policy"]
        assert "default-src 'self'" in csp and "script-src 'self'" in csp and "object-src 'none'" in csp
        assert "frame-ancestors 'self'" in csp and "unsafe-eval" not in csp
        assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    assert client.get(f"{API}/plants", headers=engineer).headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in client.get("/").headers


@pytest.mark.parametrize(
    ("ancestors", "legacy"),
    [("'none'", "DENY"), ("'self'", "SAMEORIGIN"), ("https://portal.example", None), ("*", None)],
)
def test_frame_ancestors_is_configurable(ancestors: str, legacy: str | None) -> None:
    with TestClient(create_app(make_settings(frame_ancestors=ancestors))) as client:
        headers = client.get(f"{API}/health").headers
    assert f"frame-ancestors {ancestors}" in headers["content-security-policy"]
    assert headers.get("x-frame-options") == legacy


def test_production_adds_hsts() -> None:
    with TestClient(create_app(make_settings(environment="production"))) as client:
        assert "max-age=31536000" in client.get(f"{API}/health").headers["strict-transport-security"]


def test_cors_is_off_unless_origins_are_configured(client: TestClient) -> None:
    response = client.get(f"{API}/health", headers={"Origin": "https://elsewhere.example"})
    assert "access-control-allow-origin" not in response.headers
    with TestClient(create_app(make_settings(cors_origins=["https://portal.example"]))) as configured:
        allowed = configured.get(f"{API}/health", headers={"Origin": "https://portal.example"})
        refused = configured.get(f"{API}/health", headers={"Origin": "https://elsewhere.example"})
        preflight = configured.options(f"{API}/plants", headers={
            "Origin": "https://portal.example", "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,x-solarwise-token",
        })
    assert allowed.headers["access-control-allow-origin"] == "https://portal.example"
    assert "access-control-allow-credentials" not in allowed.headers
    assert "access-control-allow-origin" not in refused.headers
    # Both ways of sending the access token are open to an allowed origin.
    assert preflight.status_code == 200
    assert {h.strip().lower() for h in preflight.headers["access-control-allow-headers"].split(",")} >= {
        "authorization", "content-type", "x-solarwise-token"}


def test_host_header_is_checked_when_hosts_are_configured() -> None:
    with TestClient(create_app(make_settings(allowed_hosts=["solar.example"]))) as client:
        assert client.get(f"{API}/health", headers={"Host": "solar.example"}).status_code == 200
        refused = client.get(f"{API}/health", headers={"Host": "evil.example"})
        assert refused.status_code == 400 and refused.headers["x-content-type-options"] == "nosniff"


def test_api_documentation_is_served_with_a_policy_that_lets_it_load(client: TestClient) -> None:
    docs = client.get("/api/docs")
    assert docs.status_code == 200 and "cdn.jsdelivr.net" in docs.headers["content-security-policy"]
    schema = client.get("/api/openapi.json").json()
    assert schema["info"]["title"] == "SolarWise DZ API"
    assert f"{API}/datasets/{{dataset_id}}/analyses" in schema["paths"]
    assert "A production gap is an observation" in schema["info"]["description"]


# --------------------------------------------------------------------------- size limits


@pytest.mark.safety
def test_oversized_bodies_are_refused_before_being_read() -> None:
    with TestClient(create_app(make_settings(max_upload_mb=1))) as client:
        declared = client.post(f"{API}/auth/login", content=b"x", headers={"Content-Length": str(5 * 1024 * 1024)})
        assert declared.status_code == 413 and declared.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
        assert declared.headers["x-content-type-options"] == "nosniff"

        def chunks() -> object:
            for _ in range(40):
                yield b"x" * 100_000  # 4 MB, sent without a declared length

        streamed = client.post(f"{API}/auth/login", content=chunks(), headers={"Content-Type": "application/json"})
        assert streamed.status_code == 413 and streamed.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_upload_above_the_file_limit_is_refused(app: FastAPI) -> None:
    limited = create_app(make_settings(max_upload_mb=1))
    with TestClient(limited) as client:
        from solarwise.db.models import Role
        from solarwise.services import users as user_service

        with limited.state.session_factory() as session:
            user_service.create_user(session, email=support.ENGINEER_EMAIL, password=support.ENGINEER_PASSWORD, role=Role.ENGINEER)
            session.commit()
        token = client.post(f"{API}/auth/login", json={"email": support.ENGINEER_EMAIL, "password": support.ENGINEER_PASSWORD}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        plant = client.post(f"{API}/plants", json=support.PLANT_PAYLOAD, headers=headers).json()
        big = "timestamp,actual_energy_kwh\n" + "2026-05-01,1\n" * 110_000  # about 1.4 MB
        response = client.post(f"{API}/plants/{plant['id']}/datasets/validate", headers=headers,
                               files={"file": ("big.csv", big.encode(), "text/csv")})
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


# --------------------------------------------------------------------------- web interface files


def _dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>SolarWise</title><div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log('app')")
    (dist / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    (tmp_path / "secret.txt").write_text("outside the build directory")
    return dist


def test_without_a_build_the_root_explains_what_to_do(client: TestClient) -> None:
    with TestClient(create_app(make_settings(frontend_dist=Path("/nonexistent/dist")))) as bare:
        response = bare.get("/")
    assert response.status_code == 200 and "has not been built" in response.text


def test_single_page_application_is_served_with_client_side_routes(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(frontend_dist=_dist(tmp_path)))) as client:
        root = client.get("/")
        assert root.status_code == 200 and "<div id=root>" in root.text
        assert root.headers["cache-control"] == "no-cache"
        assert client.get("/plants/3/analyses/7").text == root.text  # a route of the web application
        assert client.get("/assets/app.js").text == "console.log('app')"
        assert client.get("/favicon.svg").headers["content-type"].startswith("image/svg")
        assert client.get("/assets/missing.js").status_code == 404
        assert client.get(f"{API}/nope").status_code == 404  # the API never falls back to the page


def test_head_is_answered_wherever_get_is(tmp_path: Path) -> None:
    """Availability checks and proxies probe with HEAD: the application must not look unavailable to them."""
    with TestClient(create_app(make_settings(frontend_dist=_dist(tmp_path)))) as client:
        for path in ("/", "/plants/3/analyses/7", "/assets/app.js", "/favicon.svg", f"{API}/health", f"{API}/meta"):
            got, head = client.get(path), client.head(path)
            assert head.status_code == got.status_code == 200, path
            assert head.content == b"" and got.content != b"", path
            for name in ("content-type", "content-length", "content-security-policy", "x-content-type-options"):
                assert head.headers[name] == got.headers[name], (path, name)
        assert client.head("/").headers["cache-control"] == "no-cache"


def test_head_is_refused_exactly_where_get_is(client: TestClient, engineer: dict[str, str]) -> None:
    assert client.head(f"{API}/plants").status_code == 401  # no session: the same answer as GET, without the body
    assert client.head(f"{API}/plants").content == b""
    assert client.head(f"{API}/plants", headers=engineer).status_code == 200
    assert client.head(f"{API}/nope").status_code == 404
    assert client.head(f"{API}/auth/login").status_code == 405  # POST only: HEAD is not offered there
    assert client.head(f"{API}/auth/login").headers["allow"] == "POST"


def test_a_wrong_method_is_told_that_head_is_available_with_get(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(frontend_dist=_dist(tmp_path)))) as client:
        refused = client.post(f"{API}/health")
        assert refused.status_code == 405 and refused.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
        assert {m.strip() for m in refused.headers["allow"].split(",")} == {"GET", "HEAD"}
        page = client.post("/plants")
        assert page.status_code == 405
        assert {m.strip() for m in page.headers["allow"].split(",")} == {"GET", "HEAD"}


@pytest.mark.safety
@pytest.mark.parametrize(
    "path", ["/../secret.txt", "/..%2Fsecret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt", "//etc/passwd",
             "/..%5csecret.txt"],
)
def test_files_outside_the_build_directory_are_never_served(tmp_path: Path, path: str) -> None:
    with TestClient(create_app(make_settings(frontend_dist=_dist(tmp_path)))) as client:
        response = client.get(path)
    assert "outside the build directory" not in response.text
    assert "root:" not in response.text


# --------------------------------------------------------------------------- reference material


def test_decision_rules_are_published(client: TestClient, engineer: dict[str, str]) -> None:
    body = client.get(f"{API}/reference/decision-rules", headers=engineer).json()
    assert [g["id"] for g in body["gates"]] == [g.id.value for g in GATES] and len(body["gates"]) == 10
    assert [r["id"] for r in body["rules"]] == [r.id for r in RULES]
    assert {r["outcome"] for r in body["rules"] if r["id"] == "R3"} == {"CLEAN_NOW"}
    assert all(t["description"] for t in body["thresholds"])
    assert next(t for t in body["thresholds"] if t["name"] == "gap_materiality_pct")["default"] == 3.0


def test_data_dictionary_lists_columns_units_and_the_missing_value_rule(client: TestClient, engineer: dict[str, str]) -> None:
    body = client.get(f"{API}/reference/schema", headers=engineer).json()
    columns = {m["column"]: m for m in body["metrics"]}
    assert columns["actual_energy_kwh"]["unit"] == "kWh" and columns["soiling_ratio"]["unit"] == "fraction"
    assert "mwh" in body["units"]["energy"]["accepted"] and body["units"]["energy"]["canonical"] == "kWh"
    assert [p["value"] for p in body["provenance"]] == ["MEASURED", "MODELLED", "SYNTHETIC", "UNKNOWN"]
    assert "never read as zero" in body["missing_values"]
    assert body["metadata_schema"]["title"] == "DatasetMetadata"


@pytest.mark.safety
def test_economic_references_carry_no_unverified_official_figure(client: TestClient, engineer: dict[str, str]) -> None:
    body = client.get(f"{API}/reference/economic", headers=engineer).json()
    assert body["statement"]
    official = [e for e in body["entries"] if e["classification"] == "OFFICIAL_REFERENCE"]
    assert official and all(e["amount"] is None and e["verification_status"] == "PENDING_VERIFICATION" for e in official)
    assert all(e["source_reference"] for e in official)
    with_amount = [e for e in body["entries"] if e["amount"] is not None]
    assert with_amount and {e["classification"] for e in with_amount} == {"DEMONSTRATION_VALUE"}


# --------------------------------------------------------------------------- advisory calculations


def _economics_request(**overrides: object) -> dict[str, object]:
    request: dict[str, object] = {
        "recoverable_low_kwh": 80_000, "recoverable_base_kwh": 100_000, "recoverable_high_kwh": 120_000,
        "inputs": support.PROFITABLE_OPTIONS["economics"], "horizon_days": 30,
    }
    request.update(overrides)
    return request


def test_economics_arithmetic_is_exact_and_marked_advisory(client: TestClient, engineer: dict[str, str]) -> None:
    body = client.post(f"{API}/economics/calculate", json=_economics_request(), headers=engineer).json()
    assert body["advisory"] is True and "not a cleaning recommendation" in body["notice"]
    result = body["result"]
    assert result["status"] == "COMPLETE" and result["cost"]["total"] == 100_000
    scenarios = {s["name"]: s for s in result["scenarios"]}
    assert scenarios["BASE"]["net_benefit"] == pytest.approx(100_000 * 5 - 100_000)
    assert scenarios["CONSERVATIVE"]["net_benefit"] == pytest.approx(80_000 * 5 - 120_000)
    assert scenarios["OPTIMISTIC"]["net_benefit"] == pytest.approx(120_000 * 5 - 80_000)
    assert result["break_even_energy_kwh"] == pytest.approx(20_000)
    assert result["verdict"] == "PROFITABLE"


@pytest.mark.safety
def test_economics_with_missing_inputs_assumes_nothing(client: TestClient, engineer: dict[str, str]) -> None:
    inputs = {k: v for k, v in support.PROFITABLE_OPTIONS["economics"].items() if k not in ("water_cost", "energy_value_per_kwh")}
    result = client.post(f"{API}/economics/calculate", json=_economics_request(inputs=inputs), headers=engineer).json()["result"]
    assert result["status"] == "INCOMPLETE_INPUTS" and result["verdict"] == "UNDETERMINED"
    assert "water cost" in result["missing_inputs"] and "value of energy per kWh" in result["missing_inputs"]
    assert result["cost"]["total"] is None and all(s["net_benefit"] is None for s in result["scenarios"])


def test_economics_refuses_inconsistent_or_unknown_input(client: TestClient, engineer: dict[str, str]) -> None:
    disorder = client.post(f"{API}/economics/calculate", json=_economics_request(recoverable_low_kwh=500_000), headers=engineer)
    assert disorder.status_code == 422
    negative = client.post(f"{API}/economics/calculate", json=_economics_request(recoverable_base_kwh=-1), headers=engineer)
    assert negative.status_code == 422
    unknown = client.post(f"{API}/economics/calculate", json={**_economics_request(), "discount": 0.5}, headers=engineer)
    assert unknown.status_code == 422


def _case(**overrides: object) -> dict[str, object]:
    import csv
    import io

    records = list(csv.DictReader(io.StringIO(support.daily_csv())))
    case: dict[str, object] = {
        "plant": support.PLANT_PAYLOAD["spec"], "metadata": support.metadata(), "records": records,
        "options": support.PROFITABLE_OPTIONS,
    }
    case.update(overrides)
    return case


@pytest.mark.safety
def test_stateless_evaluation_never_authorises_and_stores_nothing(client: TestClient, engineer: dict[str, str]) -> None:
    response = client.post(f"{API}/recommendations/evaluate", json=_case(), headers=engineer)
    assert response.status_code == 200
    body = response.json()
    assert body["advisory"] is True and "no operational authorisation" in body["notice"]
    recommendation = body["result"]["recommendation"]
    assert recommendation["decision"] == "CLEAN_NOW"
    assert recommendation["operational_authorization"] is False
    assert "does not authorise" in recommendation["authorization_note"]
    assert client.get(f"{API}/plants", headers=engineer).json() == []


def test_stateless_evaluation_reports_invalid_records_instead_of_analysing_them(client: TestClient, engineer: dict[str, str]) -> None:
    records = [{"timestamp": "not-a-date", "actual_energy_kwh": 1, "expected_energy_kwh": 2}]
    body = client.post(f"{API}/recommendations/evaluate", json=_case(records=records), headers=engineer).json()
    assert body["result"] is None and body["validation"]["accepted"] is False


def test_stateless_evaluation_bounds_its_input(client: TestClient, engineer: dict[str, str]) -> None:
    assert client.post(f"{API}/recommendations/evaluate", json=_case(records=[]), headers=engineer).status_code == 422
    too_many = [{"timestamp": "2026-05-01", "actual_energy_kwh": 1}] * 20_001
    assert client.post(f"{API}/recommendations/evaluate", json=_case(records=too_many), headers=engineer).status_code == 422
