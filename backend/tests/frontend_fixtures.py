"""Answers of the API used as fixtures by the tests of the web interface (``frontend/src/test/fixtures``).

They are real answers of a demonstration-mode server, so that the interface is tested against what the server
actually sends.  After a change of the engine or of the API, run from ``backend/``::

    python -m tests.frontend_fixtures

``tests/test_frontend_fixtures.py`` fails while the stored files are out of date.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from solarwise.api.app import create_app
from tests import support
from tests.ai import stub_provider
from tests.ai.answers import scripted_model
from tests.conftest import make_settings

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "frontend" / "src" / "test" / "fixtures"

#: Daily series are cut to their last days: the interface needs their shape, not their length.
MAX_SERIES = 14
#: Set when the answer was produced; replaced so that the files do not change with every run.
RUN_TIME_KEYS = {"created_at", "generated_at", "imported_at", "issued_at", "updated_at"}
FIXED_TIME = "2026-07-01T08:00:00Z"
#: How long the stand-in model took: replaced for the same reason.
FIXED_DURATION_MS = 850

#: What a stand-in model answers when asked to review the columns of :func:`operator_file`.
DATA_REVIEW = {
    "suggestions": [
        {"column": "T2", "role": "QUANTITY", "metric": "ambient_temp", "unit": "degC",
         "reason": "T2 stays below the module temperature on every row, as an air temperature does."},
        {"column": "Irradiance (W/m2)", "role": "QUANTITY", "metric": "ghi", "unit": "w/m2",
         "reason": "The header does not name the plane; a horizontal pyranometer is a common default."},
        {"column": "Operator", "role": "QUANTITY", "metric": "actual_energy", "unit": "kWh",
         "reason": "Operator could hold the production."},
    ],
    "observations": [
        {"column": "Energy (kWh)", "text": "Energy (kWh) holds one cell that is not a number, 'abc'."},
        {"column": None, "text": "About 12.5 % of the rows look interpolated."},
    ],
    "missing_context": ["Whether the irradiance sensor is in the plane of the modules should be confirmed."],
}


def operator_file() -> str:
    """An operator's export with a column the reader cannot place, a few bad cells, a cleaning and three alarms."""
    text = support.operator_csv(
        days=14, cleaned=(4,), alarms={9: "Inverter fault INV-02", 10: "Inverter fault INV-02", 13: "Err 0x21"},
        cells={(2, "Energy (kWh)"): "abc", (6, "Energy (kWh)"): "", (11, "Soiling loss (%)"): "250"},
    )
    rows = list(csv.reader(io.StringIO(text)))
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    for index, row in enumerate(rows):
        writer.writerow([*row[:5], "T2" if index == 0 else "27.4", *row[5:], "Operator" if index == 0 else "A. B."])
    return out.getvalue()

#: fixture name -> name of the demonstration dataset whose analysis it is
ANALYSES = {
    "analysis_clean_now": "Confirmed soiling",
    "analysis_missing_data": "Missing data",
    "analysis_unprofitable": "Unprofitable cleaning",
}


def _normalise(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: (FIXED_TIME if k in RUN_TIME_KEYS and isinstance(v, str)
                else FIXED_DURATION_MS if k == "duration_ms" and isinstance(v, int) else _normalise(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_normalise(item) for item in value[-MAX_SERIES:]]
    return value


def build() -> dict[str, Any]:
    """The fixtures, by file name (without extension)."""
    fixtures: dict[str, Any] = {}
    with TestClient(create_app(make_settings(demo_mode=True, database_url="sqlite://"))) as client:
        token = client.post("/api/v1/auth/demo-login").json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        def get(path: str) -> Any:
            response = client.get(f"/api/v1{path}", headers=headers)
            assert response.status_code == 200, (path, response.text)
            return response.json()

        fixtures["meta"] = get("/meta")
        plant = get("/plants")[0]
        fixtures["plant"] = get(f"/plants/{plant['id']}")
        schema = get("/reference/schema")
        schema.pop("metadata_schema", None)  # the JSON Schema of a declaration: large, and not read by the interface
        fixtures["reference_schema"] = schema
        fixtures["decision_rules"] = get("/reference/decision-rules")
        datasets = get(f"/plants/{plant['id']}/datasets")
        analyses = get(f"/plants/{plant['id']}/analyses")
        ids: dict[str, int] = {}
        for name, wanted in ANALYSES.items():
            dataset = next(d for d in datasets if wanted.lower() in d["name"].lower())
            summary = next(a for a in analyses if a["dataset_id"] == dataset["id"])
            ids[name] = summary["id"]
            fixtures[name] = get(f"/analyses/{summary['id']}")
        # Without a language model: the engine's own reading of an analysis.
        fixtures["insight_engine"] = get(f"/analyses/{ids['analysis_missing_data']}/insight")
        fixtures["ai_status_off"] = get("/ai/status")

        # An operator's own export, on a plant of the visitor: first look, then validation.
        own = client.post("/api/v1/plants", json=support.PLANT_PAYLOAD, headers=headers).json()
        files = {"file": ("may-2026-export.csv", operator_file().encode(), "text/csv")}
        preview = client.post(f"/api/v1/plants/{own['id']}/datasets/preview", headers=headers, files=files).json()
        fixtures["upload_preview"] = preview
        declaration = support.declaration_from(preview, name="May 2026, operator export")
        fixtures["upload_check"] = client.post(
            f"/api/v1/plants/{own['id']}/datasets/validate", headers=headers, files=files,
            data={"metadata": json.dumps(declaration)},
        ).json()

    # With a language model: a stand-in on a local socket that speaks the chat-completions protocol.
    with stub_provider.serve() as stub:
        settings = make_settings(
            demo_mode=True, database_url="sqlite://", ai_provider="openai-compatible", ai_base_url=stub.base_url,
            ai_api_key="fixture-key", ai_model="example-model", ai_max_retries=0,
        )
        with TestClient(create_app(settings)) as client:
            token = client.post("/api/v1/auth/demo-login").json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}
            fixtures["ai_status_on"] = client.get("/api/v1/ai/status", headers=headers).json()
            stub.answer(scripted_model)
            made = client.post(f"/api/v1/analyses/{ids['analysis_clean_now']}/insight", headers=headers)
            assert made.status_code == 201 and made.json()["insight"]["generated_by"] == "AI", made.text
            fixtures["insight_ai"] = made.json()
            own = client.post("/api/v1/plants", json=support.PLANT_PAYLOAD, headers=headers).json()
            files = {"file": ("may-2026-export.csv", operator_file().encode(), "text/csv")}
            stub.answer(stub_provider.chat(json.dumps(DATA_REVIEW)))
            review = client.post(f"/api/v1/plants/{own['id']}/datasets/ai-review", headers=headers, files=files)
            assert review.status_code == 200 and review.json()["generated_by"] == "AI", review.text
            fixtures["data_review"] = review.json()
    return {name: _normalise(payload) for name, payload in fixtures.items()}


def render(payload: Any) -> str:
    return json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=True) + "\n"


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in build().items():
        path = FIXTURE_DIR / f"{name}.json"
        path.write_text(render(payload), encoding="utf-8")
        print(f"written: {path.relative_to(FIXTURE_DIR.parents[3])} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
