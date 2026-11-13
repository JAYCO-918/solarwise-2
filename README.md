# SolarWise DZ

Decision support for photovoltaic plants in the Algerian south. It compares what a plant produced with what it
should have produced, separates the causes the data can establish from those they cannot, and says whether a
cleaning is justified - and on what evidence.

> **Status: a working demonstrator.** Every dataset shipped with it is synthetic. The reference case is El Foulia
> (300 MWp nominal, Guemar, El Oued): its name, location and nominal capacity are public information; every
> technical parameter used here is an illustrative assumption, and no measurement from that plant - or from any
> plant - is in this repository. See [docs/limitations.md](docs/limitations.md).

## What it answers

When production is below expectation, dust is one possible cause among several: heat, an inverter fault, shading,
curtailment by the grid operator, or simply bad data produce the same drop. SolarWise DZ asks three questions, in
this order:

1. **How much is missing?** Expected energy against actual energy, with the uncertainty of both.
2. **Why?** Each factor is quantified only where the data needed to calculate it exist. What cannot be explained
   stays visible as "unexplained".
3. **Does cleaning pay?** Recoverable energy and cost, from a low to a high estimate.

It ends with one of three decisions, with its reasons:

| Decision | Meaning |
|---|---|
| `CLEAN_NOW` | Every one of the ten gates is passed: measured under-performance, explained by measured soiling, nothing else open, and a cleaning that pays even in the conservative case. |
| `INVESTIGATE` | Something is unknown, open or contradictory. Find out first. |
| `MONITOR` | Nothing to act on now. The analysis is repeated later. |

## Rules the software never breaks

- A production gap is an observation, never proof of soiling.
- Every value carries a declared origin: `MEASURED`, `MODELLED`, `SYNTHETIC` or `UNKNOWN`.
- The decision comes from a deterministic rule engine with ten explicit gates, not from a statistical or language
  model. A language model, when one is configured, interprets and explains what the engine found; it never
  decides, never supplies a figure, and its text is checked against the engine's result before it is shown.
- A missing value stays missing: it is never replaced by zero and never interpolated.
- Demonstration data are synthetic: every decision on them is marked *simulated* and authorises nothing.

## Quick start

You need Python 3.11 or later and Node.js 22.

### Linux and macOS

```sh
make install     # creates .venv, installs the backend and the packages of the interface
make build       # builds the interface into frontend/dist
make run         # http://localhost:8000, with the demonstration
```

No API key and no account with an outside service is needed. `make install` and `make build` download packages;
after them the application runs without the internet. What you create is kept in `var/solarwise.db`.

A language model is optional. Without one, every page that could show a model's text shows the engine's own and
says so. With one - any service that speaks the OpenAI chat-completions protocol, or Anthropic - the *AI analysis*
tab, the operational report and the assistant of the upload page use it:

```sh
SOLARWISE_AI_PROVIDER=openai-compatible SOLARWISE_AI_MODEL=... SOLARWISE_AI_API_KEY=... make run
```

The key stays on the server. This path was tested against a stand-in that speaks the protocol, not against a real
provider: see [docs/ai.md](docs/ai.md).

The same without `make`:

```sh
python3 -m venv .venv
.venv/bin/pip install -e "backend[dev]"
(cd frontend && npm ci && npm run build)
SOLARWISE_DEMO_MODE=true .venv/bin/solarwise serve
```

### Windows (PowerShell)

```powershell
py -3 -m venv .venv
.venv\Scripts\pip install -e "backend[dev]"
cd frontend; npm ci; npm run build; cd ..
$env:SOLARWISE_DEMO_MODE = "true"
.venv\Scripts\solarwise serve
```

These Windows commands are the direct equivalent of the ones above, but the project was developed and tested on
Linux only.

### Docker

```sh
cp .env.example .env        # then set SOLARWISE_SECRET_KEY and POSTGRES_PASSWORD in it
docker compose up --build   # the application and PostgreSQL -> http://localhost:8000
```

Details, the single-container variant and every setting: [docs/deployment.md](docs/deployment.md).

## First steps in the application

1. Open http://localhost:8000 and choose **Open the demonstration**. No account is needed.
2. Open the plant *El Foulia reference case (synthetic data)*. It has ten datasets, one per scenario, each already
   analysed. The same production drop of about 9 % leads to different decisions depending on the evidence:
   [docs/demo-scenarios.md](docs/demo-scenarios.md).
3. Open an analysis. The tabs follow the reasoning: Decision, AI analysis, Performance, Attribution, Diagnosis,
   Economics, Provenance and quality, Explanation. Reports are available as PDF, HTML, CSV and JSON.
4. **AI analysis** reads the findings back: a summary, each possible explanation with the support the engine gave
   it, what is uncertain or missing, what to do next - and an *operational report* in PDF, HTML or JSON. Each
   section carries a tag: **Engine** for a result of the engine, **AI interpretation** for text written by a
   language model. Without a model the page says that the deterministic fallback is active, and everything is
   tagged Engine.
5. **Rules and data** shows the decision rules, the data format with templates to download, the economic
   references and a cleaning-cost calculator.

A demonstration visitor sees the shared plant, runs analyses that only they see, and may register demonstration
plants of their own; the session is deleted after 24 hours.

## Your own data

On the sign-in page choose **Create an account**: a name, an e-mail address and a password of at least 12
characters. The account is signed in at once. It can register plants and work on them, and nobody else sees them
unless you share them. It does not see the demonstration plant, which needs no account.

An account created this way is never an administrator. Create the administrator - who manages the accounts on
the **Accounts** page - on the command line (the password is asked on the terminal):

```sh
.venv/bin/solarwise create-user you@example.org --role ADMIN
```

`SOLARWISE_ALLOW_REGISTRATION=false` removes sign-up, so that only an administrator creates accounts.

Two separate things are asked of you:

* **The plant, once**: **Register a plant** - name, location, capacity, mounting, module parameters. No
  measurement is typed in.
* **Its operational data, as files**: on the plant's page, **Upload operational data**. Choose a CSV or JSON
  export with one row per day or per interval: date, energy produced, and whatever else you have - expected
  production, irradiance, temperatures, humidity, wind, rain, soiling ratio or loss, cleaning marks, alarms.
  1. The first rows are shown as they are, and the columns are **recognised from their headers** (`Energy (kWh)`,
     `Énergie produite (MWh)`, `Irradiance (W/m2)`, `Tmod_C` ...), with their units.
  2. You correct what was not recognised, and declare where each column comes from - that is never guessed.
  3. **Check the file** lists what would be imported, the events found, and every rejected cell with what to do
     about it; the rejected rows and the report can be downloaded.
  4. **Import and run the analysis** stores the file - byte for byte - and runs the pipeline on it.

Templates and examples in CSV and JSON are on the upload page and in [data/samples](data/samples). The guide is
[docs/data-upload.md](docs/data-upload.md); the reference of the format is [docs/data-format.md](docs/data-format.md).

What you declare decides what the data can support: a file declared `MEASURED` can lead to an operational
recommendation; a synthetic, modelled or undeclared one cannot. The platform records who imported a file and
keeps the declaration with every result; it cannot verify the declaration itself.

To follow the whole path without data of your own:

* **An operator's export.** Register a plant of 1,000 kWp, then upload
  `data/samples/solarwise-operational-data.example.csv`. Every column is recognised; the check lists one cleaning,
  an inverter alarm and a grid outage. Imported as proposed, with nothing declared, the analysis answers
  *Investigate*: data of unknown origin cannot support a decision. The values of that file are invented.
* **A demonstration scenario, with its declaration file.** In **Upload operational data** choose
  `data/demo/S02_confirmed_soiling.csv`, select **Use a declaration file (JSON)** and choose
  `data/demo/S02_confirmed_soiling.metadata.json`; then **Check the file**, **Import the dataset** and **Run the
  analysis**. In the demonstration these numbers give *Clean now*, marked simulated. On your plant they give
  *Investigate*, with 4 gates of 10 passed: the file is declared synthetic, and synthetic data cannot support a
  cleaning decision.

The browser checks `frontend/e2e/upload_flow.cjs` and `frontend/e2e/first_use.cjs` walk these two paths.

## Command line

The engine also runs without the web application or a database:

```sh
.venv/bin/solarwise scenarios                 # the ten demonstration scenarios and their decisions
.venv/bin/solarwise scenario S02              # one of them, as text (also --format html|pdf|csv|json)
.venv/bin/solarwise analyze data.csv --plant plant.json --metadata data.metadata.json --format html -o report.html
.venv/bin/solarwise --help
```

## Repository

| Path | Content |
|---|---|
| `backend/` | Python package `solarwise`: analysis engines, ingestion, API (FastAPI), reports, command line; its tests |
| `frontend/` | Web interface (React, TypeScript, Vite); its tests; `e2e/` browser checks |
| `data/demo/` | The ten demonstration scenarios as files in the upload format (generated; all synthetic) |
| `data/samples/` | Templates and small invented examples for your own data, in CSV and JSON |
| `docs/` | Documentation (below) |
| `presentation/` | The 5-minute pitch: slides (PowerPoint, PDF, HTML) and speaker script |
| `Dockerfile`, `docker-compose.yml`, `.env.example` | Packaging |
| `Makefile` | Common tasks: `make help` |
| `FINAL_REPORT.md` | What was built, what was verified and how, what remains |

## Documentation

| Document | Question it answers |
|---|---|
| [docs/architecture.md](docs/architecture.md) | How is the software organised? |
| [docs/decision-rules.md](docs/decision-rules.md) | Exactly when does it say clean, investigate or monitor? |
| [docs/SCIENTIFIC_METHODOLOGY.md](docs/SCIENTIFIC_METHODOLOGY.md) | Which formulas and references are behind each figure? |
| [docs/data-provenance.md](docs/data-provenance.md) | How is the origin of every value tracked, and what may each kind of data support? |
| [docs/data-upload.md](docs/data-upload.md) | How do I upload the data of my plant, step by step? |
| [docs/data-format.md](docs/data-format.md) | What must a file look like? |
| [docs/ai.md](docs/ai.md) | What does the language model do, what can it not do, how is it configured, and what was tested? |
| [docs/demo-scenarios.md](docs/demo-scenarios.md) | What do the ten scenarios show? |
| [docs/api.md](docs/api.md) | How do other programs use it? |
| [docs/security.md](docs/security.md) | How are accounts, sessions and uploads protected? |
| [docs/deployment.md](docs/deployment.md) | How is it installed and configured? |
| [docs/limitations.md](docs/limitations.md) | What does it not do, and what has not been verified? |

## Checks

```sh
make check       # ruff, eslint, mypy, tsc, backend tests, interface tests, build of the interface
make e2e         # browser checks against a throw-away server (needs a Chromium: see frontend/e2e/README.md)
```

| Check | Result on the last run |
|---|---|
| Backend tests (`pytest`) | 1,135 passed on SQLite, and 1,135 passed on PostgreSQL 16 |
| Interface tests (`vitest`) | 122 passed |
| Browser checks | 12 runs, 291 expectations, all passed; the 7 checks that write data also passed on PostgreSQL 16 |
| Static checks | `ruff`, `mypy`, `tsc`, `eslint`: clean |

What could not be verified in the environment the project was built in - Docker itself, a real plant's data,
Windows, the external weather services, **a real language-model provider** - is listed in
[docs/limitations.md](docs/limitations.md).

## Licence

No licence has been chosen yet: the package metadata marks the code as proprietary. Third-party material embedded
in the slides is listed in [presentation/README.md](presentation/README.md).
