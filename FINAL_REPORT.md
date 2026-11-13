# SolarWise DZ - final report

State of the project in November 2026: what was built, how it was verified, and what remains. Each section
points to the document that holds the detail.

**In one paragraph.** SolarWise DZ is a working web application that compares what a photovoltaic plant produced
with what it should have produced, separates the causes the data can establish from those they cannot, and says
whether a cleaning is justified - and on what evidence. Operational data arrive as files: an operator's own CSV or
JSON export is read, its columns are recognised from their headers, and it is checked before anything is stored. A
language model, when one is configured, interprets and explains the engine's findings; it never decides. It is
complete as a demonstrator: engine, API, web interface, ten demonstration scenarios, reports, documentation,
packaging and a pitch. It has been tested on synthetic data only. No measurement from El Foulia or from any other
plant has been used; the Docker packaging has not been run; and the language-model layer has been run against a
stand-in that speaks the protocol, never against a real provider.

| | |
|---|---|
| Backend | Python package `solarwise` 0.1.0 (analysis engine 1.0.0, unchanged): 91 source files, about 20,200 lines |
| Interface | React and TypeScript: about 8,700 lines, tests and generated API types not counted |
| API | 54 operations on 44 paths |
| Database | 13 tables; SQLite or PostgreSQL |
| Demonstration | 10 synthetic scenarios on one reference case |
| Automated tests | 1,135 on the backend, 122 on the interface, 12 browser runs with 291 expectations: all passing |
| Documentation | 12 documents in `docs/`, 2 READMEs, this report |
| Pitch | 15 slides (PowerPoint, PDF, HTML) and a speaker script |

## 1. Purpose and principles

Production below expectation has several possible causes - dust, heat, an equipment fault, shading, curtailment
by the grid operator, bad data - and they look alike on the meter. Cleaning for the wrong reason spends water,
labour and money and recovers nothing; waiting when dust is the cause loses energy every day.

The application answers three questions in order: how much is missing, why, and whether cleaning pays. It ends
with one decision - `CLEAN_NOW`, `INVESTIGATE` or `MONITOR` - and its reasons.

Five principles are enforced in code and held by tests:

1. A production gap is an observation, never proof of soiling.
2. Every value carries a declared origin: `MEASURED`, `MODELLED`, `SYNTHETIC` or `UNKNOWN`.
3. The decision comes from a deterministic rule engine with ten explicit gates, not from a statistical or
   language model.
4. A missing value stays missing: never replaced by zero, never interpolated.
5. Demonstration data are synthetic; every decision on them is marked *simulated* and authorises nothing.

The reference case is named after El Foulia (300 MWp nominal, Guemar, El Oued). The name, the location and the
nominal capacity are public information. Every technical parameter is an illustrative assumption.

## 2. What was built

| Part | Content | Where |
|---|---|---|
| Analysis engine | 24 modules: units, time grid, data quality, baseline, gap, attribution, signatures, diagnosis, recoverable energy, economics, evidence gates, decision, explanation, projections | `backend/solarwise/core` |
| Ingestion | CSV and JSON parsing; a first look that proposes what each column is from its header; validation against declarations; irradiance and soiling-loss conversions; cleaning marks and alarms as evidence; rejected rows; templates | `backend/solarwise/ingestion` |
| Storage and services | Plants, devices, datasets with the uploaded file kept byte for byte, evidence, analyses, insights, accounts, permissions, audit trail; two migrations | `backend/solarwise/db`, `services`, `migrations` |
| API | REST API with one error format and security middleware | `backend/solarwise/api` |
| Reports | PDF, HTML, CSV, JSON | `backend/solarwise/reports` |
| External data | Clients for PVGIS and NASA POWER, on request only | `backend/solarwise/integrations` |
| Language-model layer | Diagnostic analysis, explanation of the decision, operational report, review of an uploaded file, rewording of the explanation - behind a structure check and mechanical guardrails, with the engine's own text as fallback; off by default | `backend/solarwise/ai` |
| Demonstration | Seeded scenario generator, ten scenarios | `backend/solarwise/demo`, `data/demo` |
| Command line | 11 commands: `serve`, `migrate`, `create-user`, `seed-demo`, `check-config`, `openapi`, `scenarios`, `scenario`, `export-demo`, `analyze`, `validate` | `backend/solarwise/cli.py` |
| Web interface | Sign-in, sign-up, plants, plant, dataset, upload of operational data (preview, mapping, check, import), analysis (eight tabs, one of them the AI analysis), rules and data, accounts | `frontend/src` |
| Templates | Templates and small invented examples for real data, in CSV and JSON | `data/samples` |
| Packaging | `Dockerfile`, `docker-compose.yml`, `.env.example`, `Makefile` | repository root |
| Pitch | Slides in three formats, speaker script, a small server | `presentation/` |

## 3. Architecture

One process serves the API and the built interface on one origin; the database is a SQLite file or PostgreSQL.
The analysis pipeline is a chain of pure functions - no database, no network - so the same input always gives
the same result. Around it: ingestion, a service layer that is the only one to touch both the database and the
engine, thin API routes, and report rendering. Datasets are immutable, and an analysis is stored exactly as it
was issued, with the engine version, the options and the content hash of its dataset.

Detail: [docs/architecture.md](docs/architecture.md).

## 4. Analysis method

    input -> validation -> baseline -> gap -> attribution -> diagnostic hypotheses
          -> recoverable energy -> economics -> evidence assessment -> decision -> explanation

- **Baseline**: five possible sources behind one interface, from an operator-supplied expected energy to an
  engineering model in the structure of PVWatts, each with its stated limits.
- **Gap**: on intervals where both values exist; reported for the period and for the last seven days; tested
  against a materiality threshold and against the combined uncertainty of baseline and metering.
- **Attribution**: a loss chain in which a factor is quantified only where its inputs exist. Soiling enters only
  through a soiling measurement; what is not explained stays visible as the unexplained residual.
- **Diagnosis**: seven hypotheses side by side, each with an ordinal support level and its evidence. No
  percentages of confidence.
- **Recoverable energy and economics**: from the measured soiling loss and declared assumptions, in a
  conservative, a base and an optimistic case. No price is built in.

The relations are closed-form, with published references (IEC 61724-1, PVWatts, Faiman, FAO-56, Erbs, Theil-Sen).
Detail: [docs/SCIENTIFIC_METHODOLOGY.md](docs/SCIENTIFIC_METHODOLOGY.md).

## 5. Decision rules and safety

Ten gates - data, loss, soiling evidence, absence of other causes, economics - and seven rules applied in a
fixed order; the first that applies decides. `CLEAN_NOW` requires all ten gates. A final interlock re-checks
every `CLEAN_NOW` independently of the path that led to it.

A decision and an authorisation are separate: an operational authorisation exists only for `CLEAN_NOW`, in an
operational context, on a plant that is not a demonstration plant, without synthetic evidence, on stored and
attributable data. The context is decided by the server.

Of the 1,135 backend tests, 496 carry the `safety` marker: they hold the invariants that must not be relaxed, for
example that a production gap alone never yields `CLEAN_NOW`, that an event read from a file can only make the
engine more cautious, and that nothing a language model returns can change a decision.

The engine itself was not changed by the work on file ingestion and on the language-model layer: its version is
still 1.0.0, the ten demonstration scenarios give the same decisions, and the files of `data/demo` are byte for
byte what they were.

Detail: [docs/decision-rules.md](docs/decision-rules.md).

## 6. Data provenance

Every quantity carries a tag. Two rules are enforced in one place: nothing turns a synthetic value into a
measured one, and a derived value is never better than its weakest input. Only measured production and measured
soiling can support an operational cleaning decision. A declaration of `MEASURED` is a statement by the person
who imports the file: the platform records it and who made it, and cannot verify it.

Reading a file never assigns a provenance: the columns of an upload are recognised from their headers, and every
one of them stays `UNKNOWN` until the uploader declares where it comes from. The same holds for a suggestion of
the language model that the uploader accepts. The uploaded file is kept byte for byte with its SHA-256, next to
the declaration, the validation report and the rows that were rejected.

Detail: [docs/data-provenance.md](docs/data-provenance.md), [docs/data-format.md](docs/data-format.md),
[docs/data-upload.md](docs/data-upload.md).

## 7. Demonstration scenarios

Ten synthetic scenarios with a known cause each. Gap over the last seven days, and the engine's answer:

| # | Scenario | Gap | Decision | Rule |
|---|---|---|---|---|
| 1 | Normal operation | 0.5 % | `MONITOR` | R6 |
| 2 | Confirmed soiling | 8.6 % | `CLEAN_NOW` | R3 |
| 3 | Temperature effect | 8.9 % | `MONITOR` | R6 |
| 4 | Inverter fault | 10.6 % | `INVESTIGATE` | R1 |
| 5 | Morning shading | 9.2 % | `INVESTIGATE` | R4 |
| 6 | Grid curtailment | 10.1 % | `MONITOR` | R6 |
| 7 | Missing data | 6.5 % | `INVESTIGATE` | R0 |
| 8 | Conflicting evidence | 8.6 % | `INVESTIGATE` | R2 |
| 9 | Synthetic data with no evidence role | 8.6 % | `INVESTIGATE` | R0 |
| 10 | Unprofitable cleaning | 5.8 % | `MONITOR` | R6 |

Six scenarios show a drop between 8.6 and 10.1 %; one ends in a cleaning order. Scenarios 2 and 10 have the same
cleaning cost and opposite answers, because the benefit lasts 30 days in one and 3 in the other. Every decision
is simulated. The generator is seeded: the files and the decisions are reproducible, and tests check it.

Detail: [docs/demo-scenarios.md](docs/demo-scenarios.md).

## 8. API

54 operations on 44 paths under `/api/v1`: accounts and sign-up, plants, devices, permissions, datasets (first
look, review, check, rejected rows, import, the file as uploaded), evidence, analyses, insights, reports,
advisory calculations, external data, reference and templates. One error format with stable codes. The description
(`frontend/openapi.json`) is generated; the types of the interface are generated from it, and a test fails when
the committed description differs from the running server.

Detail: [docs/api.md](docs/api.md).

## 9. Web interface

Sign-in, sign-up or entry into the demonstration; the list of plants; a plant with its datasets, evidence, analyses and
access rights; an analysis in eight tabs (Decision, AI analysis, Performance, Attribution, Diagnosis, Economics,
Provenance and quality, Explanation); export of reports; a reference page with the rules, the data format and its
templates, the economic references and a cleaning-cost calculator; account management for administrators.

**Two separate workflows.** The plant form describes the plant and asks for no measurement. Operational data are
uploaded from the plant's page, **Upload operational data**: the page says what a file may hold and offers
templates; the first rows are shown as they are; each column is pre-selected from its header, with its unit, and
flagged when the header is ambiguous; the uploader corrects the mapping and declares the provenance; the check
lists rows, quantities, events and every finding with what to do about it; rejected rows and the report download;
**Import and run the analysis** stores the file and runs the pipeline.

**The AI analysis tab** shows the engine's decision in a box of its own, then the reading of the findings section
by section. Every section carries a tag - *Engine* or *AI interpretation* - so that an engineering result is never
mistaken for an interpretation; gates, steps and what would change the decision are always tagged Engine. The page
says when no model is configured ("the deterministic fallback is active") and when a model's answer was not used,
and why.

The interface computes nothing: it displays what the API returns, with the origin of each figure and the
*simulated* marking. It is in English only.

## 10. Security

Argon2id password hashing; signed session tokens of limited life; account roles and plant roles checked on the
server for every request; sign-in throttling and account lock-out; sign-up that can never produce an
administrator, is rate-limited, and can be switched off (`SOLARWISE_ALLOW_REGISTRATION=false`); an isolated demonstration (throw-away
accounts, limits, everything marked as demonstration); security headers on every response; uploads parsed as
data only, with size limits, and given back only as attachments; an audit trail; no secret with a usable default
in production. The key of a language-model provider stays on the server: it is sent to the provider only, and
tests look for it in every answer, stored row and log line.

Not implemented: verification of the e-mail address at sign-up (the application sends no mail), password change
and reset, multi-factor authentication. TLS is left to a reverse proxy.
No independent security review has been made.

Detail: [docs/security.md](docs/security.md).

## 11. Tests and verification

Last complete run: November 2026, on Debian 12 with Python 3.11.2, Node.js 22.22.3 and PostgreSQL 16.2.

| Check | Command | Result |
|---|---|---|
| Backend tests, SQLite | `make test` (`pytest`) | 1,135 passed |
| Backend tests, PostgreSQL 16 | `pytest` with `SOLARWISE_TEST_DATABASE_URL` | 1,135 passed |
| Interface tests | `npm test` (`vitest`) | 122 passed, 13 files |
| Lint | `ruff check`, `eslint` | clean |
| Static typing | `mypy` (91 files), `tsc` | clean |
| Build of the interface | `npm run build` | succeeds |
| Browser checks | `make e2e` | 12 runs of 12 passed, 291 expectations |
| Browser checks that write data, on PostgreSQL 16 | `E2E_DATABASE_URL=...` | 7 runs passed, 244 expectations |
| Slides | build and comparison of the PowerPoint file with the PDF | 377 lines of text of 377 in place |

The first six are one command: `make check`.

How the backend tests are distributed: engine 227, ingestion 213, API 208, language-model layer 196, demonstration 68, services 61, command line 44, reports 35, external data 33, database 12, configuration, security primitives and generated fixtures 38.

**The language-model layer was verified against a stand-in, not against a real provider.** No provider could be
reached and no key was available where the project was built. The stand-in is a small server on a local port that
speaks the OpenAI chat-completions protocol and gives scripted answers: the tests and the browser check go through
a real HTTP connection - request format, key in the header, time-out, retry on a rate limit, refused key,
malformed replies - and through the whole application. What this establishes: the protocol, the handling of
failures, the checks on a model's text, the storage, the display, and that the key leaks nowhere. What it does
not: how well a real model writes, how often its answers pass the checks, its cost, its delay.

What the browser checks cover: sign-in directly and through proxies that remove or replace the `Authorization`
header; sign-up, directly and through such a proxy (the account is created, signed in at once, registers a
plant, signs in again; an address that is taken is refused); a first visit from beginning to end (the
demonstration answers "Clean now" for scenario 02; the visitor signs out, creates an account, registers a plant,
imports the file of scenario 02 with its declaration file and gets "Investigate", because the file is declared
synthetic; the PDF report downloads); a tour of the demonstration (every page, every scenario, the reports); the
work of a signed-in account (register a plant, import a file, run an analysis, manage accounts); an operator's
own export from the first look to the analysis, without a language model and with the stand-in (columns
recognised from the headers, a correction by hand, a suggestion of the assistant applied only when accepted,
events and rejected rows in the check, the import running the analysis, the AI analysis tab marking who wrote
what, an answer of the model that overreaches discarded whole, a provider that is down, the uploaded file given
back with its exact size, the key of the model in no answer); and the framing policy.

A fresh copy of the pushed branch was also cloned from GitHub, installed with `make install`, built with
`make build` and started with `make run`; the first visit above was walked in a browser against it.

Beyond the test suites, the package was installed the way the container image installs it and run in
production mode from another directory, on a SQLite file and on PostgreSQL: start-up, migration, demonstration
content, first administrator, sign-in, a new analysis, the four report formats, the health-check command.

## 12. Packaging and deployment

- `make install`, `make build`, `make run` start the application from a checkout.
- `Dockerfile`: the interface is built with Node 22, the backend installed on `python:3.11-slim`, run as an
  unprivileged user, with a health check and a data volume.
- `docker-compose.yml`: the application and PostgreSQL 16.
- `.env.example` lists every setting; `solarwise check-config` shows the effective configuration.

**Docker itself was not available where the project was built: `docker build` and `docker compose up` have never
been run.** The files are written from installation steps that were verified without Docker; their first real
run may need a correction.

Detail: [docs/deployment.md](docs/deployment.md).

## 13. Limitations and next steps

The complete list is in [docs/limitations.md](docs/limitations.md). The ones that matter most:

| Limitation | Consequence |
|---|---|
| No real plant data have been analysed | The results show that the logic behaves as designed, not that the method works on a plant |
| The thresholds are engineering judgement | They must be calibrated with an operator's engineers |
| Without a direct soiling measurement there is no cleaning recommendation | By design; a plant without soiling instrumentation gets `INVESTIGATE` or `MONITOR` |
| Recoverable energy and economics rest on the user's assumptions | Effectiveness of a cleaning and duration of its benefit are inputs, not forecasts |
| Economic references carry no amounts | The Algerian regulatory texts are listed by title; their figures were not verified (`PENDING_VERIFICATION`) |
| Files only | No live connection to a SCADA system, no scheduled import, no alerting. A date and a time in two columns, counter readings and Excel files are not read |
| The language model was never run against a real provider | The path is verified with a stand-in; the quality, cost and delay of a real model are unknown. Its text is kept in bounds by pattern checks, in English, which do not verify that every sentence is true |
| Events are read with a fixed vocabulary | An alarm text it does not know is kept as "other" and does not enter the diagnosis |
| English only | No French or Arabic interface |
| Not verified | Docker; Windows and macOS; a live call to PVGIS or NASA POWER; a real language-model provider; the PowerPoint file in PowerPoint itself |
| No licence chosen | The package metadata marks the code as proprietary |

Next steps, in order:

1. Build and run the container image on a machine with Docker; correct what the first run shows.
2. Configure a real language-model provider and try the ten scenarios with it: how often its answers pass the
   checks, what they add, what they cost. Adjust the prompt before trusting the layer with an operator.
3. A pilot on the measured data of one plant, with its operator - starting with the upload of its own exports.
4. Calibrate the thresholds and the declared uncertainties on that plant.
5. Verify the economic reference amounts against the official texts.
6. Connect soiling stations and weather feeds; try the PVGIS and NASA POWER clients against the live services.
7. An interface in Arabic and in French.
8. An independent review of the method and of the security.
9. Choose a licence.
