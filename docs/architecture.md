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
          ├── ingestion       reading uploads, proposing what their columns are, validating them
          ├── core            the analysis pipeline - pure functions; the only place a decision is taken
          ├── reports         PDF, HTML, CSV, JSON
          ├── integrations    PVGIS and NASA POWER, only when a user asks
          └── ai              optional: a language model interprets and explains the result; checked, never deciding
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
size limits). `detect` takes a first look before anything is declared: it proposes what each column is and in
which unit from its header, with fixed vocabularies, and reports what looks odd in the values - a proposal the
uploader corrects, which never includes a provenance and never changes a value. `validator` handles the meaning of
the file (timestamps, units, ranges, duplicates) against the uploader's declarations (`schema`), converts mean
irradiance to irradiation with the length of the interval and a soiling loss to a soiling ratio, and turns the
cleaning marks and alarm texts of declared event columns into evidence records. A value that cannot be trusted is
rejected and stored as missing, with a count and examples in the validation report and a line in the list of
rejected rows; a problem that makes the whole file unusable blocks the import. `templates` serves the files an
operator downloads to see the format. See [data-upload.md](data-upload.md).

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

**Language model** (`solarwise.ai`). An interpretation layer above the pipeline, off by default. It reads the
stored result of an analysis as an *evidence packet* - plain data, no time series - and writes: a diagnostic
analysis and the narrative of an operational report (`analyst.py`, `report.py`), a rewording of the engine's
explanation (`explain.py`), and suggestions for the mapping of an uploaded file (`data_assist.py`). Three things
keep it in its place: the decision, the gates, the rating of each cause, the evidence, the steps and the figures of
an insight are copied from the engine by the server and have no field in the model's answer; everything the model
writes passes mechanical checks before it is shown (`guardrails.py`); and when there is no model, or its answer
cannot be used, the engine's own text fills the same structure and the page says so. Providers are reached over
plain HTTPS through one small interface (`providers.py`): the OpenAI chat-completions protocol, which most services
and self-hosted servers implement, and Anthropic's. See [ai.md](ai.md).

**Demonstration** (`solarwise.demo`). A seeded generator builds ten synthetic scenarios for the reference case;
`services/demo.py` loads them at start-up when demonstration mode is on.

## Database

Thirteen tables: eleven created by the Alembic migration `0001_initial_schema`, and `dataset_files` and
`ai_insights` added by `0002_original_files_and_ai_insights`. A database of the first release is upgraded in place
at start-up.

| Table | Content |
|---|---|
| `users` | Accounts: Argon2id password hash, role, lock-out state, demonstration flag |
| `plants`, `devices`, `plant_permissions` | Plants with their specification, their inverter blocks, who may access them |
| `datasets` | One row per imported file: declarations, validation report, content hash, period |
| `dataset_files` | The uploaded file itself, compressed and returned byte for byte, with its SHA-256; the rows rejected at import |
| `production_observations`, `weather_observations` | The validated time series, in canonical units, UTC |
| `evidence_records` | Soiling measurements, inspections, fault and curtailment logs, cleaning events |
| `analyses` | Each analysis as issued: decision, rule, context, options, complete result |
| `ai_insights` | Each interpretation generated for an analysis: written by a model or by the engine, provider, model, time, prompt version, fingerprint of the evidence, result of every check, content |
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
