# Architecture

## Overview

One process serves everything on one origin:

```
 browser
    │  HTTP(S)
    ▼
 uvicorn ── FastAPI application (backend/solarwise/api)
    ├── /               the web interface: the files of frontend/dist
    ├── /api/v1/...     the API
    └── /api/docs       interactive description of the API (/api/openapi.json)
          │
          ├── services        permissions, storage, audit trail, running the engine on stored data
          ├── ingestion       reading uploads, validating them against their declarations
          ├── core            the analysis pipeline - pure functions
          ├── reports         PDF, HTML, CSV, JSON
          ├── integrations    PVGIS and NASA POWER, only when a user asks
          └── ai              optional rephrasing of the explanation, behind guardrails
          │
          ▼
   SQLite file or PostgreSQL (SQLAlchemy, Alembic migrations)
```

The interface only uses relative URLs, so there is no cross-origin configuration to get right: in production the
backend serves the built interface; in development Vite serves it on port 5173 and proxies `/api` to the backend.

## The analysis pipeline (`solarwise.core`)

```
input -> validation -> baseline -> gap -> attribution -> diagnostic hypotheses
      -> recoverable energy -> economics -> evidence assessment -> decision -> explanation
```

Every stage is a plain function in its own module and is tested on its own. `core/pipeline.py` only wires them
together and records what each stage concluded. The pipeline is pure: no database, no network, and no dependence
on the clock other than the timestamp written on the result. The same input always gives the same result, which
is what makes the stored analyses, the demonstration and the tests reproducible.

| Module | Role |
|---|---|
| `provenance` | The origin tag carried by every value, and the two rules on combining tags |
| `units` | One canonical unit per dimension; explicit conversion at the boundary; unknown units are refused |
| `timeline` | The regular grid of intervals a period should contain, so that missing records are counted |
| `data_quality` | Series-level checks: completeness, impossible values, stuck sensors, production at night |
| `solar_geometry`, `thermal`, `pv_model` | Closed-form engineering relations (daylight, transposition, cell temperature, expected energy) |
| `baseline` | "What should the plant have produced?" from five possible sources, each with its stated limits |
| `gap` | Expected minus actual on matched intervals, coverage, significance against uncertainty |
| `attribution` | The loss chain: each factor quantified only where its inputs exist; the rest is the residual |
| `trend`, `devices`, `intraday`, `statistics` | Signatures: drift, level shifts, a device against the fleet, the shape of the day |
| `diagnostics` | Seven hypotheses side by side, each with an ordinal support level and its evidence |
| `recoverable` | Energy a cleaning would bring back, from measured soiling and declared assumptions |
| `economics` | Cost and benefit in three cases (conservative, base, optimistic) |
| `evidence` | The ten gates, each with the evidence it rests on; the adequacy grade of the data |
| `decision` | The rules R0 to R6 and the final safety interlock |
| `rules` | The plain description of gates, rules and thresholds served to users (kept in step by tests) |
| `explanation` | The text of the result, assembled from computed values only |
| `forecast` | Reference projections of the performance index; never used in a decision |

The method is described in [SCIENTIFIC_METHODOLOGY.md](SCIENTIFIC_METHODOLOGY.md), the rules in
[decision-rules.md](decision-rules.md).

## Around the pipeline

**Ingestion** (`solarwise.ingestion`). `parser` handles the shape of a file (encoding, separator, JSON envelope,
size limits); `validator` handles its meaning (timestamps, units, ranges, duplicates) against the uploader's
declarations (`schema`). A value that cannot be trusted is rejected and stored as missing, with a count and
examples in the validation report; a problem that makes the whole file unusable blocks the import.

**Services** (`solarwise.services`). The only layer that touches both the database and the engine.

- *Datasets are immutable.* A stored dataset is never edited; its content hash (SHA-256) detects a second import
  of the same file; "deleting" archives it.
- *Analyses are kept exactly as issued.* The complete result is stored with the engine version and the options
  used. Reading an analysis later returns that record; nothing is recomputed silently.
- *The evaluation context is decided on the server.* A demonstration plant, or anything evaluated from a
  demonstration session, is a demonstration; a client cannot ask for an operational evaluation of it.
- *Access* is checked per plant (`OWNER`, `EDITOR`, `VIEWER`), on top of the account role (`ADMIN`, `ENGINEER`,
  `VIEWER`). An unknown plant and an inaccessible one give the same answer.
- State-changing actions are written to an audit trail.

**API** (`solarwise.api`). Thin routes over the services; request and response schemas in `schemas.py`; one error
format. From the outside in, a request passes: `HEAD` handling, security headers (so that every answer, refusals
included, carries them), host check, body-size limit, CORS. See [api.md](api.md) and [security.md](security.md).

**Reports** (`solarwise.reports`). `document.py` turns a result into a format-independent document in which every
figure is already text; `render.py` writes it as PDF (ReportLab), HTML (Jinja2, auto-escaped), CSV or JSON.

**Integrations** (`solarwise.integrations`). PVGIS provides long-term monthly averages for a typical-year
baseline; NASA POWER provides daily weather context. Both are labelled `MODELLED`, are never required, and are
called only on request.

**Language model** (`solarwise.ai`). Off by default. When configured it receives an evidence packet - the
engine's result, read-only - and may rephrase the explanation. Its answer is shown only if mechanical checks pass
(figures taken from the engine only, no contradiction with the decision, no over-claiming, plain text);
otherwise the engine's own text is shown.

**Demonstration** (`solarwise.demo`). A seeded generator builds ten synthetic scenarios for the reference case;
`services/demo.py` loads them at start-up when demonstration mode is on.

## Database

Eleven tables, created by the Alembic migration `0001_initial_schema`:

| Table | Content |
|---|---|
| `users` | Accounts: Argon2id password hash, role, lock-out state, demonstration flag |
| `plants`, `devices`, `plant_permissions` | Plants with their specification, their inverter blocks, who may access them |
| `datasets` | One row per imported file: declarations, validation report, content hash, period |
| `production_observations`, `weather_observations` | The validated time series, in canonical units, UTC |
| `evidence_records` | Soiling measurements, inspections, fault and curtailment logs, cleaning events |
| `analyses` | Each analysis as issued: decision, rule, context, options, complete result |
| `economic_reference_values` | Documented references and demonstration values; never applied automatically |
| `audit_log` | Who did what, when, from where |

Timestamps are stored in UTC and are timezone-aware on every backend; a naive timestamp is refused. The schema
is created or upgraded when the server starts; a database that contains tables but no migration history is
refused rather than guessed at. The same test suite passes on SQLite and on PostgreSQL 16.

## Web interface (`frontend/`)

React 19 and TypeScript, built with Vite, styled with Tailwind CSS, charts drawn with ECharts.

| Path | Content |
|---|---|
| `src/api/` | Typed client. `schema.d.ts` is generated from `openapi.json`, itself written by `solarwise openapi` |
| `src/auth/` | Session state; the access token is sent in two headers (see [security.md](security.md)) |
| `src/pages/` | Sign-in, sign-up, plants, plant, dataset, upload, analysis, rules and data, accounts |
| `src/components/` | Decision panel, charts, forms, badges for provenance and decisions |
| `src/lib/` | Formatting, time zones, assumption handling, plant specification, metadata |
| `src/test/` | Test support and fixtures: real answers of the API, generated by `backend/tests/frontend_fixtures.py` |
| `e2e/` | Browser checks that drive a real browser against a real server |

The interface never computes a result: it displays what the API returns, including the provenance of each
figure and the "simulated" marking.

## Files that are generated

| File | Written by | Kept current by |
|---|---|---|
| `frontend/openapi.json`, `frontend/src/api/schema.d.ts` | `make openapi` | a backend test compares the file with the live description |
| `frontend/src/test/fixtures/*.json` | `make fixtures` | a backend test fails when they are stale |
| `data/demo/*` | `make demo-data` | a backend test compares them with the generator's output |
| `presentation/SolarWise-DZ-pitch.*`, `SPEAKER-SCRIPT.md` | `make presentation` | built from `presentation/src/` |

They are committed so that the repository works as cloned; they are never edited by hand.

## Design decisions

- **Rules, not a learned model, decide.** A cleaning order on a 300 MWp plant must be explainable line by line,
  and there is no labelled history of cleaning decisions to learn from. The rules are few, ordered and published.
- **Ordinal support levels, not percentages.** A numeric "confidence" in a diagnosis would need a probability
  model of plant failures that does not exist. Numeric uncertainty is attached only to quantities whose
  uncertainty follows from declared measurement uncertainty.
- **Provenance is part of every value,** not a property of a file checked once at import. A derived value is
  never better than its weakest input, and nothing turns a synthetic value into a measured one.
- **One origin, one process.** Fewer moving parts to deploy and to secure.
