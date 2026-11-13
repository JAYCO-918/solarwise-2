"""HTTP: an operator's own file, from the first look to the analysis.

preview -> correct the mapping -> validate -> (download what was rejected) -> import -> analyse.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from solarwise.api.app import create_app
from solarwise.db.base import build_engine
from solarwise.db.migrate import alembic_config, current_revision, init_schema
from solarwise.db.models import AuditLog, Dataset, DatasetFile, EvidenceRow
from solarwise.ingestion import templates
from solarwise.ingestion.schema import DatasetMetadata
from tests import support
from tests.conftest import _accounts, login, make_settings

API = "/api/v1"


def file_part(content: str | bytes, filename: str = "export.csv", media_type: str = "text/csv") -> dict[str, Any]:
    data = content.encode() if isinstance(content, str) else content
    return {"files": {"file": (filename, data, media_type)}}


def with_declaration(content: str | bytes, declaration: dict[str, Any], filename: str = "export.csv") -> dict[str, Any]:
    return {**file_part(content, filename), "data": {"metadata": json.dumps(declaration)}}


def preview_of(client: TestClient, headers: dict[str, str], plant_id: int, content: str | bytes,
               filename: str = "export.csv") -> dict[str, Any]:
    response = client.post(f"{API}/plants/{plant_id}/datasets/preview", headers=headers, **file_part(content, filename))
    assert response.status_code == 200, response.text
    return dict(response.json())


def import_file(client: TestClient, headers: dict[str, str], plant_id: int, content: str,
                declaration: dict[str, Any] | None = None, filename: str = "export.csv") -> dict[str, Any]:
    declaration = declaration or support.declaration_from(preview_of(client, headers, plant_id, content, filename))
    response = client.post(f"{API}/plants/{plant_id}/datasets", headers=headers,
                           **with_declaration(content, declaration, filename))
    assert response.status_code == 201, response.text
    return dict(response.json())


# --------------------------------------------------------------------------- the whole path


def test_an_operators_export_goes_from_preview_to_analysis(client: TestClient, engineer: dict[str, str], plant_id: int) -> None:
    content = support.operator_csv(alarms={10: "Inverter fault INV-02", 11: "Inverter fault INV-02"}, cleaned=(3,))

    # 1. A first look: nothing is declared, nothing is stored.
    preview = preview_of(client, engineer, plant_id, content)
    assert preview["file_name"] == "export.csv" and preview["size_bytes"] == len(content.encode())
    assert preview["file_sha256"] == hashlib.sha256(content.encode()).hexdigest() and preview["same_file_as"] == []
    proposal = preview["preview"]["proposal"]
    assert proposal["timestamp_column"] == "Date" and proposal["interval_minutes"] == 1440
    assert proposal["channels"]["soiling_ratio"] == {"column": "Soiling loss (%)", "unit": "percent", "reported_as": "LOSS"}
    assert proposal["channels"]["poa_irradiation"]["unit"] == "w/m2"
    assert len(preview["preview"]["sample_rows"]) == 12 and preview["preview"]["rows_total"] == 30
    assert client.get(f"{API}/plants/{plant_id}/datasets", headers=engineer).json() == []

    # 2. The uploader confirms the mapping and declares where the columns come from; the server validates.
    declaration = support.declaration_from(preview, name="May 2026, operator export")
    checked = client.post(f"{API}/plants/{plant_id}/datasets/validate", headers=engineer, **with_declaration(content, declaration))
    assert checked.status_code == 200, checked.text
    check = checked.json()
    assert check["accepted"] is True and check["stored"] is False and check["duplicate_of"] is None
    report = check["report"]
    assert report["rows_plant"] == 30 and report["values_rejected"] == 0 and report["interval_minutes"] == 1440
    by_metric = {c["metric"]: c for c in report["channels"]}
    assert by_metric["actual_energy"]["source_column"] == "Energy (kWh)" and by_metric["actual_energy"]["provenance"] == "MEASURED"
    assert by_metric["poa_irradiation"]["unit_in"] == "w/m2" and by_metric["poa_irradiation"]["unit"] == "kWh/m2"
    assert by_metric["soiling_ratio"]["minimum"] == pytest.approx(0.92)
    assert [e["evidence_type"] for e in report["events"]] == ["CLEANING_EVENT", "INVERTER_FAULT"]
    assert client.get(f"{API}/plants/{plant_id}/datasets", headers=engineer).json() == []

    # 3. Import: the values, the declarations, the file itself and its events.
    stored = client.post(f"{API}/plants/{plant_id}/datasets", headers=engineer, **with_declaration(content, declaration))
    assert stored.status_code == 201, stored.text
    body = stored.json()
    assert body["stored"] is True and body["events_stored"] == 2
    dataset_id = body["dataset"]["id"]
    detail = client.get(f"{API}/datasets/{dataset_id}", headers=engineer).json()
    assert detail["name"] == "May 2026, operator export" and detail["rows_plant"] == 30 and detail["is_synthetic"] is False
    assert detail["original_file"] == {
        "file_name": "export.csv", "content_type": "text/csv", "size_bytes": len(content.encode()),
        "sha256": hashlib.sha256(content.encode()).hexdigest(), "rejections": 0,
    }
    channels = {c["metric"]: c for c in detail["channels"]}
    assert channels["actual_energy"]["provenance"] == "MEASURED" and channels["expected_energy"]["provenance"] == "MODELLED"
    assert channels["poa_irradiation"]["original_unit"] == "w/m2"
    assert detail["declared_metadata"]["channels"]["soiling_ratio"]["reported_as"] == "LOSS"
    assert [(e["record"]["evidence_type"], e["provenance_label"]) for e in detail["events"]] == [
        ("CLEANING_EVENT", "MEASURED"), ("INVERTER_FAULT", "MEASURED"),
    ]

    # 4. The analysis runs on what was uploaded, with the events of the file as evidence.
    run = client.post(f"{API}/datasets/{dataset_id}/analyses", headers=engineer, json={"options": support.PROFITABLE_OPTIONS})
    assert run.status_code == 201, run.text
    result = run.json()["result"]
    assert result["gap"]["result"]["expected_kwh"] == pytest.approx(30 * 50_000.0)
    assert result["gap"]["result"]["actual_kwh"] == pytest.approx(30 * 46_000.0)
    assert result["recommendation"]["decision"] == "CLEAN_NOW" and result["recommendation"]["simulated"] is False
    assert result["recommendation"]["operational_authorization"] is True
    labels = {p["label"]: p["provenance"] for p in result["provenance"]}
    assert labels["Actual energy"] == "MEASURED" and labels["In-plane irradiation"] == "MEASURED"
    fault_log = [e for h in result["diagnostics"]["hypotheses"] for e in h["evidence"] if e["code"] == "INV-FAULT-LOG"]
    assert fault_log and "F-EVT-002" in fault_log[0]["statement"]


def test_the_same_data_as_json_records(client: TestClient, engineer: dict[str, str], plant_id: int) -> None:
    rows = list(csv.DictReader(io.StringIO(support.operator_csv(days=10, alarms={9: "Grid outage"}))))
    records = [
        {key: (None if value == "" else (value if key in ("Date", "Alarms", "Cleaning") else float(value)))
         for key, value in row.items()}
        for row in rows
    ]
    content = json.dumps({"records": records})
    preview = preview_of(client, engineer, plant_id, content, "export.json")
    assert preview["preview"]["file_format"] == "JSON" and preview["preview"]["embedded_metadata"] is False
    assert preview["preview"]["proposal"]["channels"]["actual_energy"]["column"] == "Energy (kWh)"
    body = import_file(client, engineer, plant_id, content, filename="export.json")
    assert body["dataset"]["file_format"] == "JSON" and body["dataset"]["rows_plant"] == 10 and body["events_stored"] == 1
    original = client.get(f"{API}/datasets/{body['dataset']['id']}/file", headers=engineer)
    assert original.content == content.encode()
    assert 'filename="export.json"' in original.headers["content-disposition"]


def test_a_french_export_with_semicolons_and_decimal_commas(client: TestClient, engineer: dict[str, str], plant_id: int) -> None:
    lines = ["Date;Énergie produite (MWh);Production attendue (MWh);Température module (°C)"]
    lines += [f"{day:02d}/05/2026;46,0;50,0;44,5" for day in range(1, 11)]
    content = "\n".join(lines) + "\n"
    preview = preview_of(client, engineer, plant_id, content)
    proposal = preview["preview"]["proposal"]
    assert preview["preview"]["decimal_comma"] is True and proposal["timestamp_column"] == "Date"
    assert proposal["channels"]["actual_energy"] == {"column": "Énergie produite (MWh)", "unit": "mwh", "reported_as": "RATIO"}
    assert proposal["channels"]["expected_energy"]["unit"] == "mwh"
    assert proposal["channels"]["module_temp"]["column"] == "Température module (°C)"
    body = import_file(client, engineer, plant_id, content)
    series = client.get(f"{API}/datasets/{body['dataset']['id']}/series", headers=engineer).json()
    assert series["columns"]["actual_energy_kwh"] == [46_000.0] * 10 and series["columns"]["module_temp_c"] == [44.5] * 10
    assert series["start_utc"][0] == "2026-04-30T23:00:00+00:00"  # 1 May, local midnight in Africa/Algiers


# --------------------------------------------------------------------------- what is kept


def test_the_uploaded_file_is_kept_byte_for_byte(client: TestClient, engineer: dict[str, str], plant_id: int, app: Any) -> None:
    content = ("\ufeff" + support.operator_csv(days=5)).replace("\n", "\r\n")  # a BOM and Windows line ends, as exported
    body = import_file(client, engineer, plant_id, content, filename="Mai 2026 (export).csv")
    dataset_id = body["dataset"]["id"]
    response = client.get(f"{API}/datasets/{dataset_id}/file", headers=engineer)
    assert response.status_code == 200 and response.content == content.encode()
    assert response.headers["content-type"] == "application/octet-stream"  # never rendered by a browser
    assert response.headers["content-disposition"] == 'attachment; filename="Mai_2026_export_.csv"'
    assert response.headers["cache-control"] == "no-store"
    with app.state.session_factory() as session:
        stored = session.get(DatasetFile, dataset_id)
        assert stored is not None and stored.encoding == "zlib" and stored.content != content.encode()
        assert stored.sha256 == hashlib.sha256(content.encode()).hexdigest() == body["file_sha256"]
        exported = list(session.query(AuditLog).filter(AuditLog.action == "ORIGINAL_FILE_EXPORTED"))
        assert len(exported) == 1 and exported[0].entity_id == dataset_id


def test_provenance_is_what_the_uploader_declared_and_nothing_more(client: TestClient, engineer: dict[str, str], plant_id: int) -> None:
    """Imported exactly as proposed, nothing declared: every channel and every event is UNKNOWN, and nothing can be cleaned."""
    content = support.operator_csv(alarms={5: "Tracker fault"})
    preview = preview_of(client, engineer, plant_id, content)
    body = import_file(client, engineer, plant_id, content, support.declaration_from(preview, measured=False))
    dataset_id = body["dataset"]["id"]
    detail = client.get(f"{API}/datasets/{dataset_id}", headers=engineer).json()
    assert {c["provenance"] for c in detail["channels"]} == {"UNKNOWN"}
    assert [e["provenance_label"] for e in detail["events"]] == ["UNKNOWN"]
    codes = {i["code"] for i in detail["validation_report"]["issues"]}
    assert {"PROVENANCE_NOT_DECLARED", "BASELINE_NOT_DESCRIBED", "SOILING_METHOD_NOT_DECLARED"} <= codes
    run = client.post(f"{API}/datasets/{dataset_id}/analyses", headers=engineer, json={"options": support.PROFITABLE_OPTIONS})
    recommendation = run.json()["result"]["recommendation"]
    assert recommendation["decision"] == "INVESTIGATE" and recommendation["rule"] == "R0"
    assert recommendation["operational_authorization"] is False


@pytest.mark.safety
def test_a_synthetic_upload_never_authorises_a_cleaning(client: TestClient, engineer: dict[str, str], plant_id: int) -> None:
    """A real plant, a real account, a file declared synthetic that passes every other gate: never CLEAN_NOW."""
    content = support.operator_csv(alarms={2: "Inverter trip"}, cleaned=(1,))
    preview = preview_of(client, engineer, plant_id, content)
    declaration = support.declaration_from(preview)
    for channel in declaration["channels"].values():
        channel.update({"provenance": "SYNTHETIC", "emulates": "MODELLED" if channel["column"].startswith("Expected") else "MEASURED",
                        "source": "generator (test fixture)"})
    declaration["events"].update({"provenance": "SYNTHETIC", "emulates": "MEASURED", "source": "generator (test fixture)"})
    declaration["synthetic"] = {"generator": "test fixture", "generator_version": "1", "statement": "Artificial values."}
    body = import_file(client, engineer, plant_id, content, declaration)
    assert body["dataset"]["is_synthetic"] is True
    detail = client.get(f"{API}/datasets/{body['dataset']['id']}", headers=engineer).json()
    assert {c["provenance"] for c in detail["channels"]} == {"SYNTHETIC"}
    assert {e["provenance_label"] for e in detail["events"]} == {"SYNTHETIC (emulates MEASURED)"}
    run = client.post(f"{API}/datasets/{body['dataset']['id']}/analyses", headers=engineer, json={"options": support.PROFITABLE_OPTIONS})
    recommendation = run.json()["result"]["recommendation"]
    assert recommendation["decision"] != "CLEAN_NOW" and recommendation["operational_authorization"] is False
    assert run.json()["context"] == "OPERATIONAL"
    insight = client.get(f"{API}/analyses/{run.json()['id']}/insight", headers=engineer).json()["insight"]
    assert insight["decision"]["value"] == recommendation["decision"]
    assert insight["decision"]["operational_authorization"] is False


def test_events_of_a_file_are_evidence_of_its_dataset_only(client: TestClient, engineer: dict[str, str], plant_id: int, app: Any) -> None:
    first = import_file(client, engineer, plant_id, support.operator_csv(alarms={29: "Inverter fault INV-02"}))
    second = import_file(client, engineer, plant_id, support.operator_csv(start=date(2026, 7, 1)))
    with app.state.session_factory() as session:
        rows = session.query(EvidenceRow).all()
        assert [(r.dataset_id, r.reference, r.evidence_type) for r in rows] == [(first["dataset"]["id"], "F-EVT-001", "INVERTER_FAULT")]
    listed = client.get(f"{API}/plants/{plant_id}/evidence", headers=engineer).json()
    assert [e["dataset_id"] for e in listed] == [first["dataset"]["id"]]
    # It belongs to its dataset: it cannot be removed on its own.
    refused = client.delete(f"{API}/plants/{plant_id}/evidence/{listed[0]['id']}", headers=engineer)
    assert refused.status_code == 409 and "belongs to that dataset" in refused.json()["error"]["message"]
    # The open alarm stops a cleaning for the dataset it came with, and does not leak into the other one.
    with_fault = client.post(f"{API}/datasets/{first['dataset']['id']}/analyses", headers=engineer, json={"options": support.PROFITABLE_OPTIONS})
    without = client.post(f"{API}/datasets/{second['dataset']['id']}/analyses", headers=engineer, json={"options": support.PROFITABLE_OPTIONS})
    assert with_fault.json()["result"]["recommendation"]["rule"] == "R1"
    assert without.json()["result"]["recommendation"]["decision"] == "CLEAN_NOW"


def test_in_a_demonstration_session_nothing_uploaded_counts_as_a_real_observation(demo_client: TestClient, visitor: dict[str, str]) -> None:
    created = demo_client.post(f"{API}/plants", json=support.PLANT_PAYLOAD, headers=visitor)
    assert created.status_code == 201, created.text
    plant_id = created.json()["id"]
    body = import_file(demo_client, visitor, plant_id, support.operator_csv(alarms={29: "Inverter trip"}))
    detail = demo_client.get(f"{API}/datasets/{body['dataset']['id']}", headers=visitor).json()
    assert [e["provenance_label"] for e in detail["events"]] == ["SYNTHETIC (emulates MEASURED)"]
    run = demo_client.post(f"{API}/datasets/{body['dataset']['id']}/analyses", headers=visitor, json={"options": support.PROFITABLE_OPTIONS})
    assert run.json()["simulated"] is True and run.json()["operational_authorization"] is False


# --------------------------------------------------------------------------- rejected rows and validation results


BAD_CELLS = {(1, "Energy (kWh)"): "abc", (2, "Energy (kWh)"): "-5", (4, "Date"): "someday", (6, "Soiling loss (%)"): "=1+1"}


def test_rejected_rows_come_back_as_they_were_sent_with_the_reason(client: TestClient, engineer: dict[str, str], plant_id: int) -> None:
    content = support.operator_csv(days=8, cells=BAD_CELLS)
    declaration = support.declaration_from(preview_of(client, engineer, plant_id, content))
    response = client.post(f"{API}/plants/{plant_id}/datasets/rejected-rows", headers=engineer, **with_declaration(content, declaration))
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == 'attachment; filename="rejected-rows-export.csv"'
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0] == ["solarwise_row", *support.OPERATOR_HEADER, "solarwise_problems"]
    by_row = {int(r[0]): r for r in rows[1:]}
    assert sorted(by_row) == [3, 4, 6, 8]
    original = list(csv.reader(io.StringIO(content)))
    assert by_row[3][1:-1] == original[2] and by_row[4][1:-1] == original[3]  # the uploader's own cells, untouched
    assert "Energy (kWh): not a number; stored as missing, not as zero [NON_NUMERIC]" in by_row[3][-1]
    assert "negative value" in by_row[4][-1] and "[NEGATIVE_VALUE]" in by_row[4][-1]
    assert "the whole row was rejected" in by_row[6][-1] and "[INVALID_TIMESTAMP]" in by_row[6][-1]
    # A cell a spreadsheet would run as a formula is neutralised; everything else is as sent.
    assert by_row[8][support.OPERATOR_HEADER.index("Soiling loss (%)") + 1] == "'=1+1"
    assert client.get(f"{API}/plants/{plant_id}/datasets", headers=engineer).json() == []  # nothing was stored


def test_what_was_rejected_at_import_stays_downloadable(client: TestClient, engineer: dict[str, str], plant_id: int) -> None:
    content = support.operator_csv(days=8, cells=BAD_CELLS)
    declaration = support.declaration_from(preview_of(client, engineer, plant_id, content))
    before = client.post(f"{API}/plants/{plant_id}/datasets/rejected-rows", headers=engineer, **with_declaration(content, declaration))
    body = import_file(client, engineer, plant_id, content, declaration)
    dataset_id = body["dataset"]["id"]
    assert body["report"]["rejections_total"] == 4 and body["report"]["rows_rejected"] == 1
    assert client.get(f"{API}/datasets/{dataset_id}", headers=engineer).json()["original_file"]["rejections"] == 4
    after = client.get(f"{API}/datasets/{dataset_id}/rejected-rows.csv", headers=engineer)
    assert after.status_code == 200 and after.text == before.text
    assert after.headers["content-disposition"] == f'attachment; filename="rejected-rows-dataset-{dataset_id}.csv"'
    # The rejected cells are missing in what was stored - not zero.
    series = client.get(f"{API}/datasets/{dataset_id}/series", headers=engineer).json()
    assert series["columns"]["actual_energy_kwh"][:3] == [46_000.0, None, None]
    assert len(series["start_utc"]) == 7  # the row without a usable date was not imported

    clean = import_file(client, engineer, plant_id, support.operator_csv(start=date(2026, 8, 1)))
    nothing = client.get(f"{API}/datasets/{clean['dataset']['id']}/rejected-rows.csv", headers=engineer)
    assert nothing.status_code == 200 and nothing.text == "solarwise_row,solarwise_problems\n"


def test_the_validation_report_can_be_downloaded(client: TestClient, engineer: dict[str, str], plant_id: int) -> None:
    content = support.operator_csv(days=8, cells=BAD_CELLS)
    body = import_file(client, engineer, plant_id, content)
    dataset_id = body["dataset"]["id"]
    response = client.get(f"{API}/datasets/{dataset_id}/validation-report.json", headers=engineer)
    assert response.status_code == 200 and response.headers["content-type"] == "application/json"
    assert f'filename="validation-report-dataset-{dataset_id}.json"' in response.headers["content-disposition"]
    document = response.json()
    assert document["report"] == {"format": "solarwise-validation", "format_version": 1}
    assert document["dataset"]["file_sha256"] == hashlib.sha256(content.encode()).hexdigest()
    assert document["dataset"]["imported_by"] == "Engineer" and document["dataset"]["content_sha256"] == body["content_sha256"]
    assert document["validation_report"]["values_rejected"] == 3
    assert document["declared_metadata"]["channels"]["actual_energy"]["column"] == "Energy (kWh)"
    hints = {i["code"]: i["hint"] for i in document["validation_report"]["issues"]}
    assert hints["NON_NUMERIC"] and hints["INVALID_TIMESTAMP"]


def test_a_dataset_that_did_not_come_from_an_upload_has_no_file(demo_client: TestClient, visitor: dict[str, str]) -> None:
    plant = demo_client.get(f"{API}/plants", headers=visitor).json()[0]
    dataset = demo_client.get(f"{API}/plants/{plant['id']}/datasets", headers=visitor).json()[0]
    detail = demo_client.get(f"{API}/datasets/{dataset['id']}", headers=visitor).json()
    assert detail["original_file"] is None
    for path in ("file", "rejected-rows.csv"):
        missing = demo_client.get(f"{API}/datasets/{dataset['id']}/{path}", headers=visitor)
        assert missing.status_code == 404 and missing.json()["error"]["code"] == "NO_ORIGINAL_FILE"
    assert demo_client.get(f"{API}/datasets/{dataset['id']}/validation-report.json", headers=visitor).status_code == 200


# --------------------------------------------------------------------------- duplicates


def test_the_same_file_with_the_same_declaration_is_refused(client: TestClient, engineer: dict[str, str], plant_id: int) -> None:
    content = support.operator_csv()
    declaration = support.declaration_from(preview_of(client, engineer, plant_id, content))
    first = import_file(client, engineer, plant_id, content, declaration)
    again = client.post(f"{API}/plants/{plant_id}/datasets/validate", headers=engineer, **with_declaration(content, declaration))
    assert again.json()["duplicate_of"] == first["dataset"]["id"] and again.json()["same_file_as"] == []
    refused = client.post(f"{API}/plants/{plant_id}/datasets", headers=engineer, **with_declaration(content, declaration))
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "DUPLICATE_DATASET"
    assert refused.json()["error"]["details"] == {"dataset_id": first["dataset"]["id"]}
    assert len(client.get(f"{API}/plants/{plant_id}/datasets", headers=engineer).json()) == 1


def test_the_same_file_under_another_declaration_is_allowed_and_pointed_out(client: TestClient, engineer: dict[str, str], plant_id: int) -> None:
    content = support.operator_csv()
    preview = preview_of(client, engineer, plant_id, content)
    first = import_file(client, engineer, plant_id, content, support.declaration_from(preview, measured=False))
    # Seen again at the first look ...
    assert preview_of(client, engineer, plant_id, content)["same_file_as"] == [first["dataset"]["id"]]
    # ... and at validation: a warning, not a refusal - a corrected declaration is a legitimate new dataset.
    corrected = support.declaration_from(preview, name="Corrected declaration")
    check = client.post(f"{API}/plants/{plant_id}/datasets/validate", headers=engineer, **with_declaration(content, corrected)).json()
    assert check["duplicate_of"] is None and check["same_file_as"] == [first["dataset"]["id"]]
    assert [o["dataset_id"] for o in check["overlapping"]] == [first["dataset"]["id"]]
    second = import_file(client, engineer, plant_id, content, corrected)
    assert second["dataset"]["id"] != first["dataset"]["id"] and second["file_sha256"] == first["file_sha256"]
    assert second["content_sha256"] != first["content_sha256"]


def test_another_file_for_the_same_days_is_pointed_out(client: TestClient, engineer: dict[str, str], plant_id: int) -> None:
    first = import_file(client, engineer, plant_id, support.operator_csv(days=30))
    later = support.operator_csv(days=10, start=date(2026, 5, 25), soiling_loss=0.05)
    check = client.post(
        f"{API}/plants/{plant_id}/datasets/validate", headers=engineer,
        **with_declaration(later, support.declaration_from(preview_of(client, engineer, plant_id, later))),
    ).json()
    assert check["accepted"] is True and check["duplicate_of"] is None and check["same_file_as"] == []
    assert check["overlapping"] == [{"dataset_id": first["dataset"]["id"], "name": "Operator export",
                                     "period_start": "2026-05-01", "period_end": "2026-05-30"}]
    apart = support.operator_csv(days=10, start=date(2026, 6, 1))
    check = client.post(
        f"{API}/plants/{plant_id}/datasets/validate", headers=engineer,
        **with_declaration(apart, support.declaration_from(preview_of(client, engineer, plant_id, apart))),
    ).json()
    assert check["overlapping"] == []
    # An archived dataset no longer counts.
    assert client.delete(f"{API}/datasets/{first['dataset']['id']}", headers=engineer).status_code == 204
    check = client.post(
        f"{API}/plants/{plant_id}/datasets/validate", headers=engineer,
        **with_declaration(later, support.declaration_from(preview_of(client, engineer, plant_id, later))),
    ).json()
    assert check["overlapping"] == []


def test_a_declaration_without_the_new_fields_keeps_the_fingerprint_it_always_had(
    client: TestClient, engineer: dict[str, str], plant_id: int
) -> None:
    content = support.daily_csv()
    declared = support.metadata()
    check = client.post(f"{API}/plants/{plant_id}/datasets/validate", headers=engineer,
                        **support.upload_parts(content, declared)).json()
    # How the fingerprint was computed before events and soiling losses could be declared.
    legacy = DatasetMetadata.model_validate(declared).model_dump(mode="json")
    del legacy["events"]
    for channel in legacy["channels"].values():
        del channel["reported_as"]
    digest = hashlib.sha256()
    digest.update(content.encode())
    digest.update(b"\x00")
    digest.update(json.dumps(legacy, sort_keys=True).encode())
    assert check["content_sha256"] == digest.hexdigest()


# --------------------------------------------------------------------------- access and limits


def test_a_first_look_stores_nothing_and_writing_needs_write_access(
    client: TestClient, admin: dict[str, str], engineer: dict[str, str], plant_id: int, app: Any
) -> None:
    content = support.operator_csv()
    preview_of(client, engineer, plant_id, content)
    with app.state.session_factory() as session:
        assert session.query(Dataset).count() == 0 and session.query(DatasetFile).count() == 0
    stranger = login(client, support.VIEWER_EMAIL, support.VIEWER_PASSWORD)
    assert client.post(f"{API}/plants/{plant_id}/datasets/preview", headers=stranger, **file_part(content)).status_code == 404
    granted = client.put(f"{API}/plants/{plant_id}/permissions", headers=engineer,
                         json={"email": support.VIEWER_EMAIL, "role": "VIEWER"})
    assert granted.status_code == 200, granted.text
    preview = preview_of(client, stranger, plant_id, content)  # a reader may look ...
    refused = client.post(f"{API}/plants/{plant_id}/datasets", headers=stranger,
                          **with_declaration(content, support.declaration_from(preview)))
    assert refused.status_code == 403  # ... and may not import
    assert client.post(f"{API}/plants/{plant_id}/datasets/preview", **file_part(content)).status_code == 401


@pytest.mark.parametrize(("content", "filename", "fragment"), [
    (b"", "empty.csv", "empty"), (b"\x00\x01\x02\x03binary", "data.csv", "binary"),
    (b"timestamp,energy\n", "header.csv", "no data rows"), (b"just one column\nvalue\n", "one.csv", "no delimiter"),
    (b'{"records": "nope"}', "bad.json", "non-empty list of records"), (b"a,b\n1,2\n", "sheet.xlsx", "unsupported file type"),
])
def test_a_file_that_cannot_be_read_is_refused_in_plain_words(
    client: TestClient, engineer: dict[str, str], plant_id: int, content: bytes, filename: str, fragment: str
) -> None:
    response = client.post(f"{API}/plants/{plant_id}/datasets/preview", headers=engineer, **file_part(content, filename))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "UNREADABLE_FILE" and fragment in response.json()["error"]["message"]


def test_the_upload_limit_applies_to_a_first_look_too(tmp_path: Path) -> None:
    application = create_app(make_settings(max_upload_mb=1))
    with TestClient(application) as small:
        _accounts(application)
        headers = login(small, support.ENGINEER_EMAIL, support.ENGINEER_PASSWORD)
        plant = small.post(f"{API}/plants", json=support.PLANT_PAYLOAD, headers=headers).json()["id"]
        too_big = "timestamp,actual_energy_kwh\n" + "2026-05-01,1\n" * 120_000
        response = small.post(f"{API}/plants/{plant}/datasets/preview", headers=headers, **file_part(too_big))
        assert response.status_code == 413


# --------------------------------------------------------------------------- templates and reference


def test_templates_and_examples_can_be_downloaded(client: TestClient, engineer: dict[str, str]) -> None:
    schema = client.get(f"{API}/reference/schema", headers=engineer).json()
    listed = schema["templates"]
    assert [t["name"] for t in listed] == [t.name for t in templates.TEMPLATES] and len(listed) == 4
    assert [t["example"] for t in listed] == [False, True, False, True]
    for template in templates.TEMPLATES:
        response = client.get(f"{API}/reference/templates/{template.name}", headers=engineer)
        assert response.status_code == 200 and response.content == templates.read(template)
        assert response.headers["content-disposition"] == f'attachment; filename="{template.name}"'
        assert response.headers["content-type"].split(";")[0] == template.media_type.split(";")[0]
    assert client.get(f"{API}/reference/templates/../../etc/passwd", headers=engineer).status_code == 404
    assert client.get(f"{API}/reference/templates/unknown.csv", headers=engineer).status_code == 404
    assert client.get(f"{API}/reference/templates/{templates.TEMPLATES[0].name}").status_code == 401


def test_the_example_file_goes_through_the_whole_path(client: TestClient, engineer: dict[str, str]) -> None:
    small = {**support.PLANT_PAYLOAD["spec"], "name": "Example plant", "capacity_dc_kwp": 1000.0, "capacity_ac_kw": 900.0}
    plant_id = client.post(f"{API}/plants", json={"spec": small}, headers=engineer).json()["id"]
    name = "solarwise-operational-data.example.csv"
    content = client.get(f"{API}/reference/templates/{name}", headers=engineer).text
    preview = preview_of(client, engineer, plant_id, content, name)
    assert not [n for n in preview["preview"]["notes"] if n["severity"] == "WARNING"]
    body = import_file(client, engineer, plant_id, content, support.declaration_from(preview, measured=False), name)
    assert body["dataset"]["rows_plant"] == 14 and body["events_stored"] == 3
    run = client.post(f"{API}/datasets/{body['dataset']['id']}/analyses", headers=engineer, json={})
    assert run.status_code == 201 and run.json()["decision"] == "INVESTIGATE"  # nothing declared: nothing to act on


def test_the_data_dictionary_describes_units_and_events(client: TestClient, engineer: dict[str, str]) -> None:
    schema = client.get(f"{API}/reference/schema", headers=engineer).json()
    by_metric = {m["metric"]: m for m in schema["metrics"]}
    assert by_metric["poa_irradiation"]["accepted_units"][0] == "kWh/m2" and "w/m2" in by_metric["poa_irradiation"]["accepted_units"]
    assert "w/m2" not in by_metric["actual_energy"]["accepted_units"] and "mwh" in by_metric["actual_energy"]["accepted_units"]
    events = schema["events"]
    assert {v["evidence_type"] for v in events["vocabulary"]} >= {"INVERTER_FAULT", "GRID_OUTAGE", "CLEANING_EVENT"}
    assert "yes" in events["cleaning_marks"] and "ok" in events["no_event_cells"] and events["max_events_per_file"] == 500
    properties = schema["metadata_schema"]["properties"]
    assert "events" in properties and "reported_as" in schema["metadata_schema"]["$defs"]["ChannelDeclaration"]["properties"]


# --------------------------------------------------------------------------- an existing database


def test_a_database_of_the_first_release_is_upgraded_in_place(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'first-release.db'}"
    engine = build_engine(url)
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0001")
    assert current_revision(engine) == "0001"
    assert not {"dataset_files", "ai_insights"} & set(inspect(engine).get_table_names())
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO users (email, full_name, role, is_active, is_demo, failed_logins, created_at) "
            "VALUES ('kept@example.org', 'Kept', 'ENGINEER', 1, 0, 0, '2026-11-11 00:00:00')"
        ))
    assert init_schema(engine) == "migrated 0001 -> 0002"
    assert {"dataset_files", "ai_insights"} <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.execute(text("SELECT email FROM users")).scalars().all() == ["kept@example.org"]
    engine.dispose()


# --------------------------------------------------------------------------- very many rejections


def test_a_file_with_more_rejections_than_are_listed_says_how_many_are_not(
    client: TestClient, engineer: dict[str, str], plant_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    from solarwise.ingestion import validator

    monkeypatch.setattr(validator, "MAX_REJECTIONS", 5)
    lines = ["timestamp,actual_energy_kwh"] + [f"2026-05-{day:02d},{'bad' if day <= 12 else '46000'}" for day in range(1, 31)]
    content = "\n".join(lines) + "\n"
    declaration = {"name": "many rejections", "channels": {"actual_energy": {}}}
    response = client.post(f"{API}/plants/{plant_id}/datasets/rejected-rows", headers=engineer, **with_declaration(content, declaration))
    rows = list(csv.reader(io.StringIO(response.text)))
    assert [r[0] for r in rows[1:]] == ["2", "3", "4", "5", "6", ""]
    assert rows[-1][-1].startswith("7 further rejected cells or rows are not listed: the list stops at 5.")
    check = client.post(f"{API}/plants/{plant_id}/datasets/validate", headers=engineer, **with_declaration(content, declaration)).json()
    assert check["report"]["rejections_total"] == 12 and check["report"]["values_rejected"] == 12  # counted in full


def test_showing_a_dataset_does_not_read_the_file_it_came_from(client: TestClient, engineer: dict[str, str], plant_id: int, app: Any) -> None:
    from sqlalchemy import inspect as sa_inspect

    body = import_file(client, engineer, plant_id, support.operator_csv())
    with app.state.session_factory() as session:
        stored = session.get(DatasetFile, body["dataset"]["id"])
        assert stored is not None and stored.size_bytes > 0
        assert {"content", "rejected_rows"} <= sa_inspect(stored).unloaded  # megabytes stay in the database until asked for
        assert len(stored.content) > 0 and "content" not in sa_inspect(stored).unloaded
