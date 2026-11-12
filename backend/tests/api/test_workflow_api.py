"""HTTP: plants, datasets, evidence, analyses and reports - the working path of the product."""

from __future__ import annotations

import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from tests import support

API = "/api/v1"


# --------------------------------------------------------------------------- plants


def test_plant_lifecycle(client: TestClient, engineer: dict[str, str]) -> None:
    created = client.post(f"{API}/plants", json=support.PLANT_PAYLOAD, headers=engineer)
    assert created.status_code == 201
    plant = created.json()
    assert plant["role"] == "OWNER" and plant["is_demonstration"] is False
    assert plant["pvgis"] == {"available": False, "source": None, "months": []}
    assert plant["latest_analysis"] is None and plant["dataset_count"] == 0

    updated = client.patch(f"{API}/plants/{plant['id']}", json={"spec": {"tilt_deg": 22.0}, "description": "edited"},
                           headers=engineer)
    assert updated.status_code == 200
    assert updated.json()["spec"]["tilt_deg"] == 22.0 and updated.json()["description"] == "edited"
    assert updated.json()["spec"]["capacity_dc_kwp"] == plant["spec"]["capacity_dc_kwp"]  # untouched fields are kept

    assert [p["id"] for p in client.get(f"{API}/plants", headers=engineer).json()] == [plant["id"]]
    assert client.delete(f"{API}/plants/{plant['id']}", headers=engineer).status_code == 204
    assert client.get(f"{API}/plants/{plant['id']}", headers=engineer).status_code == 404


@pytest.mark.parametrize(
    ("change", "field"),
    [({"latitude": 123.0}, "latitude"), ({"capacity_dc_kwp": 0}, "capacity_dc_kwp"), ({"name": ""}, "name"),
     ({"name": "   "}, "name"), ({"tilt_deg": 120}, "tilt_deg"), ({"module_temp_coeff_per_c": 0.004}, "module_temp_coeff_per_c")],
)
def test_physically_impossible_plant_descriptions_are_refused(
    client: TestClient, engineer: dict[str, str], change: dict[str, object], field: str
) -> None:
    payload = {"spec": {**support.PLANT_PAYLOAD["spec"], **change}}
    response = client.post(f"{API}/plants", json=payload, headers=engineer)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "INVALID" and any(field in d["field"] for d in error["details"])


def test_devices_can_be_registered_and_removed(client: TestClient, engineer: dict[str, str], plant_id: int) -> None:
    created = client.post(f"{API}/plants/{plant_id}/devices", json={"code": "INV-01", "capacity_kwp": 250.0}, headers=engineer)
    assert created.status_code == 201
    assert client.post(f"{API}/plants/{plant_id}/devices", json={"code": "INV-01", "capacity_kwp": 250.0},
                       headers=engineer).status_code == 409
    assert client.post(f"{API}/plants/{plant_id}/devices", json={"code": "INV-02", "capacity_kwp": -1},
                       headers=engineer).status_code == 422
    assert [d["code"] for d in client.get(f"{API}/plants/{plant_id}/devices", headers=engineer).json()] == ["INV-01"]
    assert client.delete(f"{API}/plants/{plant_id}/devices/{created.json()['id']}", headers=engineer).status_code == 204
    assert client.get(f"{API}/plants/{plant_id}/devices", headers=engineer).json() == []


def test_pvgis_months_can_be_entered_by_hand_with_their_source(client: TestClient, engineer: dict[str, str], plant_id: int) -> None:
    months = [{"month": m, "e_d_kwh_per_kwp": 4.0 + m / 10, "h_i_d_kwh_m2": 5.0 + m / 10} for m in range(1, 13)]
    stored = client.put(f"{API}/plants/{plant_id}/pvgis", json={"months": months, "source": "PVGIS web interface, test fixture"},
                        headers=engineer)
    assert stored.status_code == 200
    pvgis = stored.json()["pvgis"]
    assert pvgis["available"] and len(pvgis["months"]) == 12 and "entered manually" in pvgis["source"]
    assert client.put(f"{API}/plants/{plant_id}/pvgis", json={"months": months[:11], "source": "incomplete"},
                      headers=engineer).status_code == 422


# --------------------------------------------------------------------------- datasets: validate, then import


def test_validation_reports_without_storing_and_import_stores_once(client: TestClient, engineer: dict[str, str], plant_id: int) -> None:
    parts = support.upload_parts(support.daily_csv())
    check = client.post(f"{API}/plants/{plant_id}/datasets/validate", headers=engineer, **parts)
    assert check.status_code == 200
    body = check.json()
    assert body["accepted"] is True and body["stored"] is False and body["duplicate_of"] is None
    assert body["report"]["rows_plant"] == 30 and body["report"]["interval_minutes"] == 1440
    assert client.get(f"{API}/plants/{plant_id}/datasets", headers=engineer).json() == []

    stored = client.post(f"{API}/plants/{plant_id}/datasets", headers=engineer, **parts)
    assert stored.status_code == 201
    dataset = stored.json()["dataset"]
    assert stored.json()["stored"] is True and dataset["kind"] == "PRODUCTION" and dataset["is_synthetic"] is False
    assert dataset["content_sha256"] == body["content_sha256"]
    assert {c["metric"]: c["provenance"] for c in dataset["channels"]} == {
        "actual_energy": "MEASURED", "expected_energy": "MODELLED", "availability": "MEASURED", "soiling_ratio": "MEASURED",
    }

    again = client.post(f"{API}/plants/{plant_id}/datasets/validate", headers=engineer, **parts)
    assert again.json()["duplicate_of"] == dataset["id"]
    duplicate = client.post(f"{API}/plants/{plant_id}/datasets", headers=engineer, **parts)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DUPLICATE_DATASET"
    assert duplicate.json()["error"]["details"] == {"dataset_id": dataset["id"]}


def test_a_rejected_file_is_explained_and_not_stored(client: TestClient, engineer: dict[str, str], plant_id: int) -> None:
    bad = "timestamp,actual_energy_kwh,expected_energy_kwh\n2026-05-01,-5,100\nnot-a-date,5,100\n"
    check = client.post(f"{API}/plants/{plant_id}/datasets/validate", headers=engineer, **support.upload_parts(bad))
    assert check.status_code == 200 and check.json()["accepted"] is False
    assert check.json()["report"]["issues"], "the reasons must be listed"
    refused = client.post(f"{API}/plants/{plant_id}/datasets", headers=engineer, **support.upload_parts(bad))
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "VALIDATION_FAILED"
    assert client.get(f"{API}/plants/{plant_id}/datasets", headers=engineer).json() == []


@pytest.mark.parametrize(
    ("content", "filename", "code"),
    [
        (b"", "empty.csv", "UNREADABLE_FILE"),
        (b"\x00\x01\x02\x03 not text", "binary.csv", "UNREADABLE_FILE"),
        (b"{broken json", "data.json", "UNREADABLE_FILE"),
    ],
)
def test_unreadable_uploads_are_refused_cleanly(
    client: TestClient, engineer: dict[str, str], plant_id: int, content: bytes, filename: str, code: str
) -> None:
    response = client.post(f"{API}/plants/{plant_id}/datasets/validate", headers=engineer,
                           files={"file": (filename, content, "application/octet-stream")})
    assert response.status_code == 422 and response.json()["error"]["code"] == code


def test_metadata_that_is_not_understood_is_refused_rather_than_ignored(client: TestClient, engineer: dict[str, str], plant_id: int) -> None:
    meta = support.metadata()
    meta["channels"]["actual_energy"]["provenence"] = "MEASURED"  # misspelt on purpose
    response = client.post(f"{API}/plants/{plant_id}/datasets/validate", headers=engineer,
                           **support.upload_parts(support.daily_csv(), meta))
    assert response.status_code == 422 and response.json()["error"]["code"] == "INVALID_METADATA"


@pytest.mark.safety
@pytest.mark.safety
def test_the_shipped_metadata_template_cannot_be_imported_as_it_stands(client: TestClient, engineer: dict[str, str], plant_id: int) -> None:
    """The template declares channels MEASURED to show the format; unfilled, it would vouch for unknown data."""
    from pathlib import Path

    template = json.loads(
        (Path(__file__).resolve().parents[3] / "data" / "samples" / "daily_measured.template.metadata.json").read_text()
    )
    for path in ("datasets/validate", "datasets"):
        refused = client.post(f"/api/v1/plants/{plant_id}/{path}", headers=engineer,
                              **support.upload_parts(support.daily_csv(), template))
        assert refused.status_code == 422
        error = refused.json()["error"]
        assert error["code"] == "TEMPLATE_NOT_FILLED_IN" and "channels.actual_energy.source" in error["details"]["fields"]
    assert client.get(f"/api/v1/plants/{plant_id}/datasets", headers=engineer).json() == []


def test_missing_values_stay_missing_through_the_api(client: TestClient, engineer: dict[str, str], plant_id: int) -> None:
    stored = client.post(f"{API}/plants/{plant_id}/datasets", headers=engineer,
                         **support.upload_parts(support.daily_csv(days=10, blank_actual_days=(2, 7))))
    assert stored.status_code == 201
    series = client.get(f"{API}/datasets/{stored.json()['dataset']['id']}/series", headers=engineer).json()
    actual = series["columns"]["actual_energy_kwh"]
    assert [v is None for v in actual] == [i in (2, 7) for i in range(10)]
    assert 0 not in actual


def test_datasets_are_archived_not_deleted_and_their_analyses_remain(client: TestClient, engineer: dict[str, str],
                                                                      plant_id: int, dataset_id: int) -> None:
    analysis = client.post(f"{API}/datasets/{dataset_id}/analyses", json={"options": {}}, headers=engineer).json()
    assert client.delete(f"{API}/datasets/{dataset_id}", headers=engineer).status_code == 204
    assert client.get(f"{API}/plants/{plant_id}/datasets", headers=engineer).json() == []
    archived = client.get(f"{API}/plants/{plant_id}/datasets", params={"include_archived": True}, headers=engineer).json()
    assert [d["archived"] for d in archived] == [True]
    assert client.get(f"{API}/analyses/{analysis['id']}", headers=engineer).status_code == 200
    # There is no endpoint that edits a stored dataset.
    assert client.patch(f"{API}/datasets/{dataset_id}", json={"name": "x"}, headers=engineer).status_code in (404, 405)
    assert client.put(f"{API}/datasets/{dataset_id}", json={"name": "x"}, headers=engineer).status_code in (404, 405)


def test_dataset_detail_shows_declarations_and_validation_report(client: TestClient, engineer: dict[str, str], dataset_id: int) -> None:
    detail = client.get(f"{API}/datasets/{dataset_id}", headers=engineer).json()
    assert detail["declared_metadata"]["channels"]["actual_energy"]["source"] == "revenue meter (test fixture)"
    assert detail["validation_report"]["accepted"] is True
    assert detail["baseline"]["method"] == "TELEMETRY_MODEL"


# --------------------------------------------------------------------------- evidence


def _soiling_test(reference: str = "ST-1", **overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "reference": reference, "evidence_type": "SOILING_MEASUREMENT", "observed_start": "2026-05-29T09:00:00+01:00",
        "provenance": "MEASURED", "source": "handheld clean/dirty reference test (test fixture)", "value": 0.92,
        "unit": "fraction", "std_uncertainty": 0.005, "soiling_method": "SOILING_STATION",
    }
    record.update(overrides)
    return record


def test_evidence_can_be_recorded_listed_and_deleted(client: TestClient, engineer: dict[str, str], plant_id: int) -> None:
    created = client.post(f"{API}/plants/{plant_id}/evidence", json=_soiling_test(), headers=engineer)
    assert created.status_code == 201
    body = created.json()
    assert body["provenance_label"] == "MEASURED" and body["record"]["value"] == 0.92
    assert client.post(f"{API}/plants/{plant_id}/evidence", json=_soiling_test(), headers=engineer).status_code == 409
    assert len(client.get(f"{API}/plants/{plant_id}/evidence", headers=engineer).json()) == 1
    assert client.delete(f"{API}/plants/{plant_id}/evidence/{body['id']}", headers=engineer).status_code == 204
    assert client.get(f"{API}/plants/{plant_id}/evidence", headers=engineer).json() == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"observed_start": "2026-05-29T09:00:00"},  # no time zone
        {"value": 1.4},  # not a possible soiling ratio
        {"observed_end": "2026-05-01T00:00:00+01:00"},  # ends before it starts
        {"evidence_type": "GUESS"},
    ],
)
def test_implausible_evidence_is_refused(client: TestClient, engineer: dict[str, str], plant_id: int, overrides: dict[str, object]) -> None:
    response = client.post(f"{API}/plants/{plant_id}/evidence", json=_soiling_test(**overrides), headers=engineer)
    assert response.status_code == 422


def test_evidence_without_declared_origin_is_recorded_as_unknown(client: TestClient, engineer: dict[str, str], plant_id: int) -> None:
    record = _soiling_test()
    del record["provenance"], record["source"]
    created = client.post(f"{API}/plants/{plant_id}/evidence", json=record, headers=engineer)
    assert created.status_code == 201
    assert created.json()["record"]["tag"]["provenance"] == "UNKNOWN"


# --------------------------------------------------------------------------- analyses


@pytest.mark.safety
def test_measured_data_on_a_registered_plant_can_yield_an_operational_clean_now(client: TestClient, engineer: dict[str, str],
                                                                                 dataset_id: int) -> None:
    response = client.post(f"{API}/datasets/{dataset_id}/analyses", json={"options": support.PROFITABLE_OPTIONS}, headers=engineer)
    assert response.status_code == 201
    body = response.json()
    assert (body["decision"], body["rule"], body["reason_code"]) == ("CLEAN_NOW", "R3", "CLEANING_JUSTIFIED")
    assert body["context"] == "OPERATIONAL" and body["simulated"] is False and body["operational_authorization"] is True
    assert "SIMULATED" not in body["headline"]
    assert body["gap_pct"] == pytest.approx(8.0)
    result = body["result"]
    assert all(g["passed"] for g in result["recommendation"]["gates"])
    assert result["recoverable"]["recoverable"]["central"] == pytest.approx(0.08 * 0.9 * 50_000 * 30)
    assert body["dataset_sha256"] and body["engine_version"] == result["engine_version"]


@pytest.mark.safety
def test_a_production_gap_alone_never_yields_clean_now(client: TestClient, engineer: dict[str, str], plant_id: int) -> None:
    """Same 8 % gap and the same favourable economics, but no soiling measurement at all."""
    parts = support.upload_parts(
        support.daily_csv(with_soiling_channel=False), support.metadata(with_soiling_channel=False)
    )
    dataset = client.post(f"{API}/plants/{plant_id}/datasets", headers=engineer, **parts).json()["dataset"]
    body = client.post(f"{API}/datasets/{dataset['id']}/analyses", json={"options": support.PROFITABLE_OPTIONS},
                       headers=engineer).json()
    assert body["decision"] == "INVESTIGATE" and body["rule"] == "R4"
    assert body["operational_authorization"] is False
    assert body["gap_pct"] == pytest.approx(8.0)
    assert any("does not prove soiling" in reason for reason in body["result"]["recommendation"]["reasons"])


@pytest.mark.safety
@pytest.mark.parametrize("production", ["MODELLED", "UNKNOWN"])
def test_production_that_is_not_measured_cannot_support_a_decision(client: TestClient, engineer: dict[str, str],
                                                                     plant_id: int, production: str) -> None:
    parts = support.upload_parts(support.daily_csv(), support.metadata(production=production))
    dataset = client.post(f"{API}/plants/{plant_id}/datasets", headers=engineer, **parts).json()["dataset"]
    body = client.post(f"{API}/datasets/{dataset['id']}/analyses", json={"options": support.PROFITABLE_OPTIONS},
                       headers=engineer).json()
    assert (body["decision"], body["rule"]) == ("INVESTIGATE", "R0")
    assert body["operational_authorization"] is False


@pytest.mark.safety
def test_without_cost_inputs_no_price_is_assumed(client: TestClient, engineer: dict[str, str], dataset_id: int) -> None:
    body = client.post(f"{API}/datasets/{dataset_id}/analyses", json={"options": {}}, headers=engineer).json()
    assert (body["decision"], body["rule"]) == ("INVESTIGATE", "R5")
    economics = body["result"]["economics"]
    assert economics["status"] == "NO_RECOVERABLE_ENERGY" and economics["verdict"] == "UNDETERMINED"
    assert "value of energy per kWh" in economics["missing_inputs"] and "water cost" in economics["missing_inputs"]
    assert economics["energy_value_per_kwh"] is None and economics["cost"]["total"] is None
    assert all(s["net_benefit"] is None for s in economics["scenarios"])


@pytest.mark.safety
@pytest.mark.parametrize(
    "payload",
    [
        {"options": {}, "context": "OPERATIONAL"},
        {"options": {}, "simulated": False},
        {"options": {}, "allow_operational_authorization": True},
        {"options": {"context": "OPERATIONAL"}},
        {"options": {"economics": {"energy_value_per_kwh": 5, "energy_price": 5}}},
        {"options": {"cleaning": {"cleaning_efficiency": 0.9}}},
    ],
)
def test_the_request_cannot_set_the_context_and_unknown_fields_are_errors(client: TestClient, engineer: dict[str, str],
                                                                           dataset_id: int, payload: dict[str, object]) -> None:
    response = client.post(f"{API}/datasets/{dataset_id}/analyses", json=payload, headers=engineer)
    assert response.status_code == 422, response.text


def test_stored_analysis_is_returned_unchanged_and_listed(client: TestClient, engineer: dict[str, str], plant_id: int, dataset_id: int) -> None:
    created = client.post(f"{API}/datasets/{dataset_id}/analyses", json={"options": support.PROFITABLE_OPTIONS}, headers=engineer).json()
    fetched = client.get(f"{API}/analyses/{created['id']}", headers=engineer).json()
    assert fetched == created
    second = client.post(f"{API}/datasets/{dataset_id}/analyses", json={"options": {}}, headers=engineer).json()
    listed = client.get(f"{API}/plants/{plant_id}/analyses", headers=engineer).json()
    assert [a["id"] for a in listed] == [second["id"], created["id"]]
    assert "result" not in listed[0]
    datasets = client.get(f"{API}/plants/{plant_id}/datasets", headers=engineer).json()
    assert datasets[0]["latest_analysis"]["id"] == second["id"]
    assert client.get(f"{API}/plants/{plant_id}", headers=engineer).json()["latest_analysis"]["id"] == second["id"]
    assert client.get(f"{API}/plants/{plant_id}/analyses", params={"limit": 1, "offset": 1}, headers=engineer).json()[0]["id"] == created["id"]
    assert client.get(f"{API}/plants/{plant_id}/analyses", params={"limit": 0}, headers=engineer).status_code == 422


def test_plant_wide_evidence_enters_the_next_analysis(client: TestClient, engineer: dict[str, str], plant_id: int, dataset_id: int) -> None:
    before = client.post(f"{API}/datasets/{dataset_id}/analyses", json={"options": support.PROFITABLE_OPTIONS}, headers=engineer).json()
    assert before["decision"] == "CLEAN_NOW"
    fault = {
        "reference": "WO-17", "evidence_type": "INVERTER_FAULT", "observed_start": "2026-05-27T08:00:00+01:00",
        "provenance": "MEASURED", "source": "maintenance work order (test fixture)", "description": "inverter tripped",
        "resolved": False,
    }
    assert client.post(f"{API}/plants/{plant_id}/evidence", json=fault, headers=engineer).status_code == 201
    after = client.post(f"{API}/datasets/{dataset_id}/analyses", json={"options": support.PROFITABLE_OPTIONS}, headers=engineer).json()
    assert (after["decision"], after["rule"]) == ("INVESTIGATE", "R1")
    # The earlier analysis is history: it is not rewritten.
    assert client.get(f"{API}/analyses/{before['id']}", headers=engineer).json()["decision"] == "CLEAN_NOW"


def test_an_impossible_period_is_a_clear_error(client: TestClient, engineer: dict[str, str], dataset_id: int) -> None:
    response = client.post(f"{API}/datasets/{dataset_id}/analyses",
                           json={"options": {"period_start": "2030-01-01", "period_end": "2030-01-31"}}, headers=engineer)
    assert response.status_code == 422 and response.json()["error"]["code"] == "ANALYSIS_NOT_POSSIBLE"


def test_forecast_is_labelled_unvalidated_and_unusable_for_decisions(client: TestClient, engineer: dict[str, str], dataset_id: int) -> None:
    analysis = client.post(f"{API}/datasets/{dataset_id}/analyses", json={"options": {}}, headers=engineer).json()
    forecast = client.get(f"{API}/analyses/{analysis['id']}/forecast", params={"horizon_days": 7}, headers=engineer).json()["forecast"]
    assert forecast["validation_status"] == "UNVALIDATED" and forecast["usable_for_decision"] is False
    assert {m["method"] for m in forecast["methods"]} == {"PERSISTENCE", "MOVING_AVERAGE", "LINEAR_TREND"}
    for method in forecast["methods"]:
        assert method["validation_status"] == "UNVALIDATED" and len(method["points"]) == 7
        assert method["points"][0]["value"] == pytest.approx(92.0, abs=0.01)  # a flat 8 % loss stays flat
    assert client.get(f"{API}/analyses/{analysis['id']}/forecast", params={"horizon_days": 400}, headers=engineer).status_code == 422


def test_explanation_without_a_language_model_is_the_engines_own_text(client: TestClient, engineer: dict[str, str], dataset_id: int) -> None:
    analysis = client.post(f"{API}/datasets/{dataset_id}/analyses", json={"options": support.PROFITABLE_OPTIONS}, headers=engineer).json()
    explanation = client.post(f"{API}/analyses/{analysis['id']}/explanation", headers=engineer).json()
    assert explanation["generated_by"] == "DETERMINISTIC_ENGINE" and explanation["provider"] is None
    assert explanation["decision_statement"] == "Decision of the engine: Clean now."
    assert explanation["text"].strip() and "No language model" in explanation["notice"]


# --------------------------------------------------------------------------- reports


def _analysis(client: TestClient, headers: dict[str, str], dataset_id: int) -> dict[str, object]:
    response = client.post(f"{API}/datasets/{dataset_id}/analyses", json={"options": support.PROFITABLE_OPTIONS}, headers=headers)
    assert response.status_code == 201
    body: dict[str, object] = response.json()
    return body


def test_report_is_available_in_four_formats(client: TestClient, engineer: dict[str, str], dataset_id: int) -> None:
    analysis = _analysis(client, engineer, dataset_id)
    base = f"{API}/analyses/{analysis['id']}/report"

    html = client.get(f"{base}.html", headers=engineer)
    assert html.status_code == 200 and html.headers["content-type"].startswith("text/html")
    assert "<script" not in html.text.lower()
    assert "default-src 'none'" in html.headers["content-security-policy"]
    assert "Clean now" in html.text and "Test plant" in html.text

    pdf = client.get(f"{base}.pdf", headers=engineer)
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF-") and pdf.content.rstrip().endswith(b"%%EOF")

    as_csv = client.get(f"{base}.csv", headers=engineer)
    assert as_csv.status_code == 200 and as_csv.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(as_csv.text)))
    assert len(rows) > 30 and any("CLEAN_NOW" in cell for row in rows for cell in row)

    as_json = client.get(f"{base}.json", headers=engineer)
    document = json.loads(as_json.text)
    assert as_json.status_code == 200 and document["result"]["recommendation"]["decision"] == "CLEAN_NOW"

    for response, extension in ((html, "html"), (pdf, "pdf"), (as_csv, "csv"), (as_json, "json")):
        assert response.headers["content-disposition"] == f'attachment; filename="solarwise-analysis-{analysis["id"]}.{extension}"'
        assert response.headers["cache-control"] == "no-store"
    assert client.get(f"{base}.docx", headers=engineer).status_code == 422


def test_report_json_matches_the_stored_result(client: TestClient, engineer: dict[str, str], dataset_id: int) -> None:
    analysis = _analysis(client, engineer, dataset_id)
    document = client.get(f"{API}/analyses/{analysis['id']}/report.json", headers=engineer).json()
    assert document["result"] == analysis["result"]
    assert document["report"]["dataset_sha256"] == analysis["dataset_sha256"]


@pytest.mark.safety
def test_hostile_text_in_the_plant_name_is_inert_in_reports(client: TestClient, engineer: dict[str, str]) -> None:
    name = '<script>alert(1)</script><img src=x onerror=alert(2)>,=HYPERLINK("http://x"),"\n=1+1'
    spec = {**support.PLANT_PAYLOAD["spec"], "name": name}
    plant = client.post(f"{API}/plants", json={"spec": spec}, headers=engineer).json()
    dataset = client.post(f"{API}/plants/{plant['id']}/datasets", headers=engineer,
                          **support.upload_parts(support.daily_csv(), support.metadata(name="x,=cmd|'/c calc'!A1,@SUM(A1)"))).json()["dataset"]
    analysis = _analysis(client, engineer, dataset["id"])
    base = f"{API}/analyses/{analysis['id']}/report"

    html = client.get(f"{base}.html", headers=engineer).text
    assert "<script>alert(1)</script>" not in html and "<img src=x" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html

    rows = list(csv.reader(io.StringIO(client.get(f"{base}.csv", headers=engineer).text)))
    for row in rows:
        for cell in row:
            assert not cell.startswith(("=", "+", "@")), f"spreadsheet formula not neutralised: {cell!r}"
    preamble = [row for row in rows if row and row[0].startswith("#")]
    assert preamble and all(len(row) == 1 for row in preamble), "free text must stay inside one cell"

    assert client.get(f"{base}.pdf", headers=engineer).content.startswith(b"%PDF-")
