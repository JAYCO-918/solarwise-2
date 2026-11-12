# solarwise

The Python package of SolarWise DZ: the analysis engines, the ingestion of files, the HTTP API, the reports and the
`solarwise` command. The project is described in the [README at the root of the repository](../README.md) and in
[`docs/`](../docs).

## Install and run

```sh
python3 -m venv ../.venv
../.venv/bin/pip install -e ".[dev]"          # add ",postgres" for the PostgreSQL driver
SOLARWISE_DEMO_MODE=true ../.venv/bin/solarwise serve
```

The server answers on http://127.0.0.1:8000: the API under `/api/v1`, its interactive documentation under
`/api/docs`, and the web interface when `frontend/dist` has been built (`npm ci && npm run build` in
`frontend/`). The database schema is created or upgraded at start-up. Settings are environment variables with the
prefix `SOLARWISE_` (see [`.env.example`](../.env.example)).

## Layout

| Package | Role |
|---|---|
| `solarwise.core` | The analysis pipeline. Pure functions: no database, no network. |
| `solarwise.ingestion` | Reading uploads and validating them against what the uploader declared. |
| `solarwise.demo` | Generator of the ten synthetic demonstration scenarios. |
| `solarwise.services` | Permissions, storage, audit trail, running the engine on stored data. |
| `solarwise.api` | FastAPI application, middleware, routes, schemas. |
| `solarwise.db`, `solarwise.migrations` | SQLAlchemy models and Alembic migrations (SQLite or PostgreSQL). |
| `solarwise.reports` | PDF, HTML, CSV and JSON reports. |
| `solarwise.integrations` | Optional clients for PVGIS and NASA POWER. |
| `solarwise.ai` | Optional rephrasing of the engine's explanation by a language model, behind guardrails. |
| `solarwise.cli` | The `solarwise` command. |

More in [docs/architecture.md](../docs/architecture.md).

## Tests

```sh
../.venv/bin/pytest                   # everything
../.venv/bin/pytest -m safety         # the decision-safety invariants only
../.venv/bin/pytest -m scientific     # formulas against independent reference values
../.venv/bin/ruff check . && ../.venv/bin/mypy
```

By default every test gets its own in-memory SQLite database. To run the suite on PostgreSQL, install the
`postgres` extra and name a server on which the account may create databases; each test then gets a database of
its own, dropped at the end:

```sh
SOLARWISE_TEST_DATABASE_URL=postgresql+psycopg://user:password@localhost/postgres ../.venv/bin/pytest
```

Three kinds of generated files are checked by the tests and must be regenerated after the change that affects
them (from the root of the repository): `make openapi` after an API change, `make fixtures` after an engine or API
change, `make demo-data` after a change of the scenario generator.
