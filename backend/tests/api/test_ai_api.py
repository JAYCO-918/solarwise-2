"""HTTP: the language-model layer as the product exposes it.

The model is a stand-in on a local socket that speaks the OpenAI chat-completions protocol
(:mod:`tests.ai.stub_provider`).  No real provider is contacted.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from solarwise.ai.analyst import NOTICE_AI, NOTICE_ENGINE, NOTICE_FALLBACK
from solarwise.api.app import create_app
from solarwise.db.models import AiInsight, Analysis, AuditLog
from tests import support
from tests.ai import stub_provider
from tests.ai.answers import faithful, scripted_model
from tests.ai.test_data_assist import GOOD, SITE_EXPORT
from tests.conftest import _accounts, login, make_settings

API = "/api/v1"
SECRET = "sk-test-SECRET-do-not-leak-0123456789"

pytestmark = pytest.mark.safety


@pytest.fixture(scope="module")
def stub() -> Iterator[stub_provider.StubProvider]:
    with stub_provider.serve() as server:
        yield server


@pytest.fixture(scope="module")
def ai_client(stub: stub_provider.StubProvider) -> Iterator[TestClient]:
    """A demonstration server with a language model configured: the stand-in."""
    application = create_app(make_settings(
        demo_mode=True, ai_provider="openai-compatible", ai_base_url=stub.base_url, ai_api_key=SECRET,
        ai_model="stub-model-1", ai_timeout_seconds=5.0, ai_max_retries=0,
    ))
    with TestClient(application) as test_client:
        _accounts(application)
        yield test_client


@pytest.fixture(autouse=True)
def _fresh_script(stub: stub_provider.StubProvider) -> None:
    stub.requests.clear()
    stub.delay = 0.0
    stub.answer(scripted_model)


@pytest.fixture
def admin_ai(ai_client: TestClient) -> dict[str, str]:
    return login(ai_client, support.ADMIN_EMAIL, support.ADMIN_PASSWORD)


def analysis_of(client: TestClient, headers: dict[str, str], scenario: str) -> int:
    plant = client.get(f"{API}/plants", headers=headers).json()[0]
    datasets = client.get(f"{API}/plants/{plant['id']}/datasets", headers=headers).json()
    dataset = next(d for d in datasets if d["scenario"] and d["scenario"]["key"] == scenario)
    return int(dataset["latest_analysis"]["id"])


def app_of(client: TestClient) -> FastAPI:
    application = client.app
    assert isinstance(application, FastAPI)
    return application


# --------------------------------------------------------------------------- status


def test_status_without_a_model(client: TestClient, engineer: dict[str, str]) -> None:
    status = client.get(f"{API}/ai/status", headers=engineer).json()
    assert status["enabled"] is False and status["provider"] is None and status["model"] is None
    assert status["endpoint_host"] is None and len(status["capabilities"]) == 5
    assert "never decides" in status["role"] and "deterministic engine" in status["fallback"]
    assert client.get(f"{API}/ai/status").status_code == 401
    assert client.get(f"{API}/meta").json()["ai"]["enabled"] is False


def test_status_with_a_model_names_it_and_never_the_key(ai_client: TestClient, admin_ai: dict[str, str]) -> None:
    response = ai_client.get(f"{API}/ai/status", headers=admin_ai)
    status = response.json()
    assert status["enabled"] is True and status["provider"] == "openai-compatible" and status["model"] == "stub-model-1"
    assert status["endpoint_host"] == "127.0.0.1"
    assert SECRET not in response.text and "api_key" not in response.text
    meta = ai_client.get(f"{API}/meta")
    assert meta.json()["ai"]["enabled"] is True and SECRET not in meta.text


# --------------------------------------------------------------------------- without a model


def test_without_a_model_the_analysis_is_explained_by_the_engine(
    client: TestClient, engineer: dict[str, str], dataset_id: int, app: FastAPI
) -> None:
    run = client.post(f"{API}/datasets/{dataset_id}/analyses", headers=engineer, json={"options": support.PROFITABLE_OPTIONS})
    analysis_id = run.json()["id"]
    read = client.get(f"{API}/analyses/{analysis_id}/insight", headers=engineer)
    assert read.status_code == 200
    body = read.json()
    assert body["stored"] is False and body["id"] is None and body["history"] == []
    insight = body["insight"]
    assert insight["generated_by"] == "DETERMINISTIC_ENGINE" and insight["notice"] == NOTICE_ENGINE
    assert insight["provider"] is None and insight["model"] is None and insight["fallback_reason"] is None
    assert insight["decision"]["value"] == run.json()["decision"] == "CLEAN_NOW"
    assert insight["decision"]["statement"] == "Decision of the engine: Clean now."
    assert len(insight["gates"]) == 10 and all(g["passed"] for g in insight["gates"])
    with app.state.session_factory() as session:
        assert session.query(AiInsight).count() == 0  # a read stores nothing

    made = client.post(f"{API}/analyses/{analysis_id}/insight", headers=engineer)
    assert made.status_code == 201
    stored = made.json()
    assert stored["stored"] is True and stored["insight"]["generated_by"] == "DETERMINISTIC_ENGINE"
    assert [h["generated_by"] for h in stored["history"]] == ["DETERMINISTIC_ENGINE"]
    assert stored["insight"]["executive_summary"] == insight["executive_summary"]
    assert client.get(f"{API}/analyses/{analysis_id}/insight", headers=engineer).json()["id"] == stored["id"]


def test_reports_and_the_rest_of_the_product_do_not_need_a_model(client: TestClient, engineer: dict[str, str], dataset_id: int) -> None:
    analysis_id = client.post(f"{API}/datasets/{dataset_id}/analyses", headers=engineer, json={}).json()["id"]
    for fmt, media in (("html", "text/html"), ("pdf", "application/pdf"), ("json", "application/json")):
        response = client.get(f"{API}/analyses/{analysis_id}/operational-report.{fmt}", headers=engineer)
        assert response.status_code == 200 and response.headers["content-type"].startswith(media)
        assert f'operational-report-{analysis_id}.{fmt}"' in response.headers["content-disposition"]
    html = client.get(f"{API}/analyses/{analysis_id}/operational-report.html", headers=engineer).text
    assert "No language model was used" in html and "1. Executive summary" in html and "8. Limitations and uncertainty" in html
    assert client.get(f"{API}/analyses/{analysis_id}/report.pdf", headers=engineer).status_code == 200
    explanation = client.post(f"{API}/analyses/{analysis_id}/explanation", headers=engineer).json()
    assert explanation["generated_by"] == "DETERMINISTIC_ENGINE"
    assert client.get(f"{API}/analyses/{analysis_id}/operational-report.csv", headers=engineer).status_code == 422


# --------------------------------------------------------------------------- with a model


def test_a_generated_insight_is_stored_with_what_wrote_it(
    ai_client: TestClient, admin_ai: dict[str, str], stub: stub_provider.StubProvider
) -> None:
    analysis_id = analysis_of(ai_client, admin_ai, "S05_shading")
    before = ai_client.get(f"{API}/analyses/{analysis_id}", headers=admin_ai).json()
    stub.answer(stub_provider.chat(faithful()))
    made = ai_client.post(f"{API}/analyses/{analysis_id}/insight", headers=admin_ai)
    assert made.status_code == 201, made.text
    body = made.json()
    insight = body["insight"]
    assert insight["generated_by"] == "AI" and insight["provider"] == "openai-compatible" and insight["model"] == "stub-model-1"
    assert insight["notice"] == NOTICE_AI and insight["prompt_version"] == "analyst-1" and insight["generated_at"]
    assert len(insight["packet_sha256"]) == 64 and insight["duration_ms"] is not None
    assert all(c["passed"] for c in insight["checks"]) and len(insight["checks"]) >= 9
    assert insight["decision"]["value"] == before["decision"] == "INVESTIGATE"
    assert insight["executive_summary"].startswith("In this synthetic demonstration scenario")
    assert body["history"][0]["model"] == "stub-model-1" and body["history"][0]["fell_back"] is False
    # What went to the provider: the findings of the engine, with the key in the header and nowhere else.
    request = stub.requests[-1]
    assert request["path"] == "/v1/chat/completions" and request["headers"]["authorization"] == f"Bearer {SECRET}"
    assert request["body"]["model"] == "stub-model-1" and SECRET not in json.dumps(request["body"])
    # The analysis itself is exactly what it was.
    assert ai_client.get(f"{API}/analyses/{analysis_id}", headers=admin_ai).json() == before
    with app_of(ai_client).state.session_factory() as session:
        row = session.get(AiInsight, body["id"])
        assert row is not None and row.generated_by == "AI" and row.model == "stub-model-1" and row.provider == "openai-compatible"
        assert row.packet_sha256 == insight["packet_sha256"] and row.fallback_reason is None
        assert SECRET not in json.dumps(row.content) and SECRET not in json.dumps(row.checks)
        audit = session.query(AuditLog).filter(AuditLog.action == "AI_INSIGHT_GENERATED").order_by(AuditLog.id.desc()).first()
        assert audit is not None and audit.detail is not None
        assert audit.detail["generated_by"] == "AI" and audit.detail["model"] == "stub-model-1" and audit.detail["fell_back"] is False
        assert SECRET not in json.dumps(audit.detail)


def test_the_decision_shown_is_the_engines_whatever_the_model_says(
    ai_client: TestClient, admin_ai: dict[str, str], stub: stub_provider.StubProvider
) -> None:
    analysis_id = analysis_of(ai_client, admin_ai, "S05_shading")
    stored = ai_client.get(f"{API}/analyses/{analysis_id}", headers=admin_ai).json()
    stub.answer(stub_provider.chat(faithful(
        decision={"value": "CLEAN_NOW"}, gates=[{"id": "SOILING_EVIDENCE_CREDIBLE", "passed": True}],
        decision_rationale="The gap is large, so the recommendation is to clean now and the crew can start.",
    )))
    insight = ai_client.post(f"{API}/analyses/{analysis_id}/insight", headers=admin_ai).json()["insight"]
    assert insight["generated_by"] == "DETERMINISTIC_ENGINE" and insight["notice"] == NOTICE_FALLBACK
    assert "consistent_with_decision" in insight["fallback_reason"]
    assert insight["decision"]["value"] == "INVESTIGATE" and insight["decision"]["operational_authorization"] is False
    engine_gates = {g["id"]: g["passed"] for g in stored["result"]["recommendation"]["gates"]}
    assert {g["id"]: g["passed"] for g in insight["gates"]} == engine_gates
    after = ai_client.get(f"{API}/analyses/{analysis_id}", headers=admin_ai).json()
    assert (after["decision"], after["rule"], after["operational_authorization"]) == ("INVESTIGATE", "R4", False)
    assert after["result"] == stored["result"]


@pytest.mark.parametrize("scenario", [
    "S01_normal_operation", "S02_confirmed_soiling", "S03_temperature_effect", "S04_inverter_fault", "S05_shading",
    "S06_curtailment", "S07_missing_data", "S08_conflicting_evidence", "S09_synthetic_demonstration",
    "S10_unprofitable_cleaning",
])
def test_every_demonstration_analysis_can_be_interpreted_by_a_model(
    ai_client: TestClient, admin_ai: dict[str, str], scenario: str
) -> None:
    analysis_id = analysis_of(ai_client, admin_ai, scenario)
    analysis = ai_client.get(f"{API}/analyses/{analysis_id}", headers=admin_ai).json()
    insight = ai_client.post(f"{API}/analyses/{analysis_id}/insight", headers=admin_ai).json()["insight"]
    assert insight["generated_by"] == "AI", insight["fallback_reason"]
    assert insight["decision"]["value"] == analysis["decision"] and insight["decision"]["rule"] == analysis["rule"]
    assert insight["decision"]["simulated"] is True and insight["decision"]["operational_authorization"] is False
    assert insight["decision"]["statement"].startswith("SIMULATED DECISION")


@pytest.mark.parametrize(("scripted", "fragment"), [
    ((500, {}, {"error": "boom"}), "HTTP 500"),
    ((429, {"Retry-After": "0"}, {"error": "quota"}), "rate limit"),
    ((401, {}, {"error": "bad key"}), "refused the credentials"),
    ((200, {}, "<html>gateway</html>"), "did not answer with JSON"),
    ((200, {}, {"choices": [{"message": {"content": "no json here"}}]}), "no JSON object"),
])
def test_when_the_provider_fails_the_product_goes_on_with_the_engines_text(
    ai_client: TestClient, admin_ai: dict[str, str], stub: stub_provider.StubProvider, scripted: Any, fragment: str
) -> None:
    analysis_id = analysis_of(ai_client, admin_ai, "S04_inverter_fault")
    stub.answer(scripted)
    made = ai_client.post(f"{API}/analyses/{analysis_id}/insight", headers=admin_ai)
    assert made.status_code == 201
    insight = made.json()["insight"]
    assert insight["generated_by"] == "DETERMINISTIC_ENGINE" and insight["notice"] == NOTICE_FALLBACK
    assert fragment in insight["fallback_reason"] and SECRET not in made.text
    assert "boom" not in made.text and "bad key" not in made.text and "gateway" not in made.text
    assert insight["provider"] == "openai-compatible" and insight["model"] == "stub-model-1"  # what was asked
    assert made.json()["history"][0]["fell_back"] is True
    assert insight["executive_summary"] and insight["next_steps"] and insight["decision"]["value"] == "INVESTIGATE"
    # Nothing else is affected.
    assert ai_client.get(f"{API}/analyses/{analysis_id}/report.pdf", headers=admin_ai).status_code == 200


def test_a_provider_that_does_not_answer_in_time_does_not_hang_the_page(stub: stub_provider.StubProvider) -> None:
    application = create_app(make_settings(
        demo_mode=True, ai_provider="openai-compatible", ai_base_url=stub.base_url, ai_api_key=SECRET, ai_model="slow",
        ai_timeout_seconds=0.3, ai_max_retries=0,
    ))
    with TestClient(application) as slow:
        _accounts(application)
        headers = login(slow, support.ADMIN_EMAIL, support.ADMIN_PASSWORD)
        analysis_id = analysis_of(slow, headers, "S01_normal_operation")
        stub.delay = 1.5
        insight = slow.post(f"{API}/analyses/{analysis_id}/insight", headers=headers).json()["insight"]
    assert insight["generated_by"] == "DETERMINISTIC_ENGINE" and "time limit" in insight["fallback_reason"]
    assert insight["duration_ms"] < 1400


def test_the_key_appears_in_no_answer_no_log_and_no_stored_row(
    ai_client: TestClient, admin_ai: dict[str, str], stub: stub_provider.StubProvider, caplog: pytest.LogCaptureFixture
) -> None:
    analysis_id = analysis_of(ai_client, admin_ai, "S03_temperature_effect")
    texts: list[str] = []
    with caplog.at_level(logging.DEBUG):
        stub.answer(scripted_model, (401, {}, {"error": f"invalid key {SECRET}"}), (500, {}, f"echo {SECRET}"))
        for _ in range(3):
            texts.append(ai_client.post(f"{API}/analyses/{analysis_id}/insight", headers=admin_ai).text)
        texts.append(ai_client.post(f"{API}/analyses/{analysis_id}/explanation", headers=admin_ai).text)
        for path in ("insight", "operational-report.html", "operational-report.json"):
            texts.append(ai_client.get(f"{API}/analyses/{analysis_id}/{path}", headers=admin_ai).text)
        texts.append(ai_client.get(f"{API}/ai/status", headers=admin_ai).text)
        texts.append(ai_client.get(f"{API}/meta").text)
        texts.append(ai_client.get("/api/openapi.json").text)
    assert all(SECRET not in text for text in texts)
    assert SECRET not in caplog.text
    with app_of(ai_client).state.session_factory() as session:
        for row in session.query(AiInsight):
            assert SECRET not in json.dumps([row.content, row.checks, row.fallback_reason])
        for entry in session.query(AuditLog):
            assert SECRET not in json.dumps(entry.detail)


def test_an_insight_never_changes_the_analysis_it_reads(ai_client: TestClient, admin_ai: dict[str, str]) -> None:
    analysis_id = analysis_of(ai_client, admin_ai, "S02_confirmed_soiling")
    with app_of(ai_client).state.session_factory() as session:
        row = session.get(Analysis, analysis_id)
        assert row is not None
        before = (row.decision, row.rule, row.simulated, row.operational_authorization, json.dumps(row.result, sort_keys=True))
    for _ in range(2):
        assert ai_client.post(f"{API}/analyses/{analysis_id}/insight", headers=admin_ai).status_code == 201
    with app_of(ai_client).state.session_factory() as session:
        row = session.get(Analysis, analysis_id)
        assert row is not None
        after = (row.decision, row.rule, row.simulated, row.operational_authorization, json.dumps(row.result, sort_keys=True))
    assert after == before and before[:4] == ("CLEAN_NOW", "R3", True, False)


def test_only_the_latest_insights_of_an_analysis_are_kept(ai_client: TestClient, admin_ai: dict[str, str]) -> None:
    analysis_id = analysis_of(ai_client, admin_ai, "S06_curtailment")
    for _ in range(12):
        assert ai_client.post(f"{API}/analyses/{analysis_id}/insight", headers=admin_ai).status_code == 201
    history = ai_client.get(f"{API}/analyses/{analysis_id}/insight", headers=admin_ai).json()["history"]
    assert len(history) == 10 and history == sorted(history, key=lambda h: (h["created_at"], h["id"]), reverse=True)


# --------------------------------------------------------------------------- the operational report


def test_the_operational_report_says_who_wrote_what_and_calls_no_model(
    ai_client: TestClient, admin_ai: dict[str, str], stub: stub_provider.StubProvider
) -> None:
    analysis_id = analysis_of(ai_client, admin_ai, "S05_shading")
    stub.answer(stub_provider.chat(faithful()))
    assert ai_client.post(f"{API}/analyses/{analysis_id}/insight", headers=admin_ai).json()["insight"]["generated_by"] == "AI"
    calls = len(stub.requests)
    html = ai_client.get(f"{API}/analyses/{analysis_id}/operational-report.html", headers=admin_ai)
    assert html.status_code == 200 and "default-src 'none'" in html.headers["content-security-policy"]
    assert 'filename="solarwise-SIMULATED-operational-report-' in html.headers["content-disposition"]
    text = html.text
    for section in ("1. Executive summary", "2. Plant performance overview", "3. Main detected anomalies",
                    "4. Evidence-based diagnostic analysis", "5. Data-quality assessment", "6. Economic implications",
                    "7. Recommended actions", "8. Limitations and uncertainty", "Annex - the engine&#39;s figures"):
        assert section in text, section
    assert "SIMULATED DECISION" in text and "language model stub-model-1" in text
    assert "The decision, the gates, the support given to each cause" in text
    assert "In this synthetic demonstration scenario the plant produced less than its baseline" in text  # the narrative
    assert "Engine: " in text and "Interpretation (language model stub-model-1): " in text
    assert "<script" not in text.lower()
    pdf = ai_client.get(f"{API}/analyses/{analysis_id}/operational-report.pdf", headers=admin_ai)
    assert pdf.content.startswith(b"%PDF") and len(pdf.content) > 20_000
    document = ai_client.get(f"{API}/analyses/{analysis_id}/operational-report.json", headers=admin_ai).json()
    assert document["report"]["format"] == "solarwise-operational-report" and document["report"]["simulated"] is True
    assert document["report"]["narrative"]["written_by"] == "AI" and document["report"]["narrative"]["model"] == "stub-model-1"
    assert document["insight"]["decision"]["value"] == "INVESTIGATE"
    assert len(stub.requests) == calls  # an export reads the stored insight: no model is called
    with app_of(ai_client).state.session_factory() as session:
        exported = session.query(AuditLog).filter(AuditLog.action == "OPERATIONAL_REPORT_EXPORTED").count()
        assert exported >= 3


# --------------------------------------------------------------------------- who may ask


def test_a_read_only_account_reads_insights_and_cannot_generate_them(ai_client: TestClient, admin_ai: dict[str, str]) -> None:
    analysis_id = analysis_of(ai_client, admin_ai, "S08_conflicting_evidence")
    viewer = login(ai_client, support.VIEWER_EMAIL, support.VIEWER_PASSWORD)
    plant = ai_client.get(f"{API}/plants", headers=admin_ai).json()[0]
    granted = ai_client.put(f"{API}/plants/{plant['id']}/permissions", headers=admin_ai,
                            json={"email": support.VIEWER_EMAIL, "role": "VIEWER"})
    assert granted.status_code == 200, granted.text
    assert ai_client.get(f"{API}/analyses/{analysis_id}/insight", headers=viewer).status_code == 200
    assert ai_client.post(f"{API}/analyses/{analysis_id}/insight", headers=viewer).status_code == 403
    assert ai_client.get(f"{API}/analyses/{analysis_id}/operational-report.pdf", headers=viewer).status_code == 200
    assert ai_client.get(f"{API}/analyses/{analysis_id}/insight").status_code == 401
    assert ai_client.post(f"{API}/analyses/999999/insight", headers=admin_ai).status_code == 404


def test_demonstration_visitors_cannot_spend_the_model_budget_without_bound(stub: stub_provider.StubProvider) -> None:
    application = create_app(make_settings(
        demo_mode=True, ai_provider="openai-compatible", ai_base_url=stub.base_url, ai_api_key=SECRET, ai_model="m",
        ai_max_retries=0,
    ))
    with TestClient(application) as demo:
        visitor = {"Authorization": f"Bearer {demo.post(f'{API}/auth/demo-login').json()['access_token']}"}
        analysis_id = analysis_of(demo, visitor, "S01_normal_operation")
        origins = [demo.post(f"{API}/analyses/{analysis_id}/insight", headers=visitor).json()["insight"]["generated_by"]
                   for _ in range(23)]
    assert origins[:20] == ["AI"] * 20 and origins[20:] == ["DETERMINISTIC_ENGINE"] * 3
    assert len(stub.requests) == 20


# --------------------------------------------------------------------------- the review of a file


def test_a_file_can_be_reviewed_by_the_model_and_nothing_is_applied(
    ai_client: TestClient, admin_ai: dict[str, str], stub: stub_provider.StubProvider
) -> None:
    plant_id = ai_client.post(f"{API}/plants", json=support.PLANT_PAYLOAD, headers=admin_ai).json()["id"]
    stub.answer(stub_provider.chat(json.dumps(GOOD)))
    files = {"file": ("site.csv", SITE_EXPORT.encode(), "text/csv")}
    review = ai_client.post(f"{API}/plants/{plant_id}/datasets/ai-review", headers=admin_ai, files=files)
    assert review.status_code == 200, review.text
    body = review.json()
    assert body["generated_by"] == "AI" and body["model"] == "stub-model-1" and body["prompt_version"] == "data-review-1"
    assert [s["column"] for s in body["suggestions"]] == ["Prod", "Ref", "G_incl", "T1", "T2", "Rem"]
    assert body["suggestions"][0]["current"] == {"role": "UNUSED", "metric": None, "unit": None}
    # The model saw a summary, not the file ...
    sent = json.loads(stub.requests[-1]["body"]["messages"][1]["content"])
    assert len(sent["columns"]) == 8 and "2026-05-12" not in json.dumps(sent)
    # ... and the server changed nothing: the deterministic reading of the same file is what it was.
    preview = ai_client.post(f"{API}/plants/{plant_id}/datasets/preview", headers=admin_ai, files=files).json()
    assert list(preview["preview"]["proposal"]["channels"]) == ["relative_humidity"]
    assert ai_client.get(f"{API}/plants/{plant_id}/datasets", headers=admin_ai).json() == []
    with app_of(ai_client).state.session_factory() as session:
        audit = session.query(AuditLog).filter(AuditLog.action == "AI_DATA_REVIEW").order_by(AuditLog.id.desc()).first()
        assert audit is not None and audit.detail is not None and audit.detail["suggestions"] == 6


def test_accepted_suggestions_still_go_through_the_validator(
    ai_client: TestClient, admin_ai: dict[str, str], stub: stub_provider.StubProvider
) -> None:
    """A suggestion with a wrong unit, accepted by the uploader, is caught where everything is caught: at validation."""
    plant_id = ai_client.post(f"{API}/plants", json=support.PLANT_PAYLOAD, headers=admin_ai).json()["id"]
    wrong = {"suggestions": [{"column": "Prod", "role": "QUANTITY", "metric": "actual_energy", "unit": "gwh",
                              "reason": "Prod reads as the production of the plant."}]}
    stub.answer(stub_provider.chat(json.dumps(wrong)))
    files = {"file": ("site.csv", SITE_EXPORT.encode(), "text/csv")}
    suggestion = ai_client.post(f"{API}/plants/{plant_id}/datasets/ai-review", headers=admin_ai, files=files).json()["suggestions"][0]
    assert suggestion["unit"] == "gwh"  # a unit of energy: the suggestion itself is well-formed
    declaration = {"name": "site", "timestamp_column": "Date",
                   "channels": {suggestion["metric"]: {"column": suggestion["column"], "unit": suggestion["unit"]}}}
    check = ai_client.post(f"{API}/plants/{plant_id}/datasets/validate", headers=admin_ai, files=files,
                           data={"metadata": json.dumps(declaration)}).json()
    assert check["accepted"] is False
    assert "ENERGY_EXCEEDS_CAPACITY" in {i["code"] for i in check["report"]["issues"] if i["severity"] == "BLOCKING"}


def test_without_a_model_a_review_says_so_and_is_empty(client: TestClient, engineer: dict[str, str], plant_id: int) -> None:
    files = {"file": ("site.csv", SITE_EXPORT.encode(), "text/csv")}
    body = client.post(f"{API}/plants/{plant_id}/datasets/ai-review", headers=engineer, files=files).json()
    assert body["generated_by"] == "DETERMINISTIC_ENGINE" and body["provider"] is None and body["suggestions"] == []
    assert "No language model is configured" in body["notice"]
    assert client.post(f"{API}/plants/{plant_id}/datasets/ai-review", files=files).status_code == 401
