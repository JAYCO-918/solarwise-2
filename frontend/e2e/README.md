# Browser checks

Scripts that drive a real browser against a real server and exit with a non-zero status when something a visitor
would notice is wrong. They complement the unit tests of the interface (`npm test` in `frontend/`): those run in a
simulated browser with canned answers; these use the built interface, the API and a database.

`run.sh` starts a throw-away server for each check (its own SQLite database and key in a temporary folder,
demonstration mode on, bound to 127.0.0.1) and stops it afterwards. Nothing is left behind.

| Check | What it establishes |
|---|---|
| `sign_in.cjs` | The demonstration is offered first; a wrong password is explained; the demonstration opens; a session the server refuses says what the server answered. With `PROXY=strip` or `PROXY=replace` a proxy removes or replaces the `Authorization` header: the session still works and the server tells the operator. |
| `sign_up.cjs` | The sign-in page offers to create an account; a form that cannot be accepted is answered before anything is sent; the account is created and its session opens at once; it is an engineer account, not an administrator; it registers a plant; after a sign-out its password opens the next session, on its list of plants; an address that is taken is refused next to the field; no password reaches the server log. With `PROXY=strip` the new session survives a proxy that removes the `Authorization` header. |
| `first_use.cjs` | A first visit from beginning to end: the demonstration answers "Clean now" for scenario 02; the visitor signs out and creates an account, which starts on its own empty list of plants and not on the page that was left; the account registers a plant, adds the file of scenario 02 with its declaration file, and runs the analysis, which answers "Investigate" with 4 gates of 10 because the file is declared synthetic; the PDF report downloads. |
| `tour_demo.cjs` | Every page and tab as a demonstration visitor, on a desktop and on a 390 px screen: no sideways scrolling, no raw value (`null`, `NaN`, `undefined`) in the text, charts drawn, the PDF report downloads, an incomplete calculator input is refused. |
| `tour_admin.cjs` (`ADMIN=1`) | A signed-in account registers a plant, declares and imports a file through the form, runs an analysis, meets the duplicate check, creates an account, signs out. |
| `upload_flow.cjs` (`ADMIN=1`) | An operator's own export from the first look to the analysis: the plant form asks for no measurement; the plant's page leads to "Upload operational data"; templates download; the first rows are shown as they are; the columns are recognised from their headers, corrected by hand, and no provenance is pre-selected; the check lists events, rejections and what to do about them; the rejected rows download; the import runs the analysis; the "AI analysis" tab says the deterministic fallback is active and marks every section as the engine's; the operational report downloads; the uploaded file comes back with its exact size; the same file is noticed when chosen again. |
| `upload_flow.cjs` (`ADMIN=1 AI=stub`) | The same with a language model configured - a **stand-in** (see below): the assistant's suggestion is shown, checked and applied only when accepted; the generated narrative is marked as the AI's while decision, gates and steps stay marked as the engine's; an answer that states soiling as a fact and names its own decision is discarded whole; an unavailable provider leaves the engine's text; the key of the model appears in no answer the browser receives. |
| `framing.cjs` | Another origin cannot embed the application by default; it can when `SOLARWISE_FRAME_ANCESTORS` names it. |

### The stand-in model

`AI=stub` starts `stub_model.py` next to the server and configures the server to use it. It listens on a local port and
speaks the OpenAI `/chat/completions` protocol, so the application is exercised exactly as with a real provider:
configuration, request, answer, checks, storage, display. **It is not a language model.** Its answers are scripted: it
restates what the request contains in the structure the request asks for, and on demand it misbehaves (`rogue`),
fails (`fail`) or is slow (`slow`). These checks show that the path works and that the page says who wrote what. They
say nothing about how a real model writes: no real provider is contacted by any check or test of this repository.

## Running them

```sh
# once
(cd frontend && npm ci && npm run build)        # the interface that the server will serve
(cd frontend/e2e && npm install)                # puppeteer-core; it does not download a browser

# a browser: any Chromium or Chrome
export CHROMIUM_PATH=/usr/bin/chromium

frontend/e2e/all.sh                             # the twelve runs, one after the other
frontend/e2e/run.sh sign_in.cjs                 # or one check
PROXY=strip frontend/e2e/run.sh sign_in.cjs
PROXY=strip frontend/e2e/run.sh sign_up.cjs
ADMIN=1 frontend/e2e/run.sh tour_admin.cjs
ADMIN=1 frontend/e2e/run.sh upload_flow.cjs
ADMIN=1 AI=stub frontend/e2e/run.sh upload_flow.cjs
FRAME=allowed frontend/e2e/run.sh framing.cjs allowed
```

`run.sh` needs the backend installed in `.venv` at the root of the repository (or `PYTHON=/path/to/python`), and
`curl`. Other settings: `DIST` (built interface, default `frontend/dist`), `CHROMIUM_ARGS` (extra arguments for the
browser; a container without user namespaces may need `--single-process --no-zygote`), `E2E_SHOTS` (where the
screenshots go, default `frontend/e2e/shots`, which is not committed), `E2E_PORT`, `E2E_PROXY_PORT`,
`E2E_PARENT_PORT`, `E2E_MODEL_PORT`, `E2E_IDLE_TIMEOUT` (how long a check waits for the network to fall silent
before going on anyway, in milliseconds), and `E2E_DATABASE_URL` to run a check on another database than the
throw-away SQLite file (an empty PostgreSQL database, for example; it is not emptied afterwards).

`run.sh` runs any script given to it, so it also serves to script the application for other purposes:
`presentation/src/capture.cjs` takes the screenshots of the slides that way.

## Reading a failure

Each expectation prints `ok` or `FAIL` with what was observed. When a check fails, `run.sh` prints the end of the
server log, and a screenshot of the moment is in `shots/failed.png`.
