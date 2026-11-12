"""Answers of the API used as fixtures by the tests of the web interface (``frontend/src/test/fixtures``).

They are real answers of a demonstration-mode server, so that the interface is tested against what the server
actually sends.  After a change of the engine or of the API, run from ``backend/``::

    python -m tests.frontend_fixtures

``tests/test_frontend_fixtures.py`` fails while the stored files are out of date.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from solarwise.api.app import create_app
from tests.conftest import make_settings

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "frontend" / "src" / "test" / "fixtures"

#: Daily series are cut to their last days: the interface needs their shape, not their length.
MAX_SERIES = 14
#: Set when the answer was produced; replaced so that the files do not change with every run.
RUN_TIME_KEYS = {"created_at", "generated_at", "imported_at", "issued_at", "updated_at"}
FIXED_TIME = "2026-07-01T08:00:00Z"

#: fixture name -> name of the demonstration dataset whose analysis it is
ANALYSES = {
    "analysis_clean_now": "Confirmed soiling",
    "analysis_missing_data": "Missing data",
    "analysis_unprofitable": "Unprofitable cleaning",
}


def _normalise(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (FIXED_TIME if k in RUN_TIME_KEYS and isinstance(v, str) else _normalise(v)) for k, v in value.items()}
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
        for name, wanted in ANALYSES.items():
            dataset = next(d for d in datasets if wanted.lower() in d["name"].lower())
            summary = next(a for a in analyses if a["dataset_id"] == dataset["id"])
            fixtures[name] = get(f"/analyses/{summary['id']}")
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
