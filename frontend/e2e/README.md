# Browser checks

Scripts that drive a real browser against a real server and exit with a non-zero status when something a visitor
would notice is wrong. They complement the unit tests of the interface (`npm test` in `frontend/`): those run in a
simulated browser with canned answers; these use the built interface, the API and a database.

`run.sh` starts a throw-away server for each check (its own SQLite database and key in a temporary folder,
demonstration mode on, bound to 127.0.0.1) and stops it afterwards. Nothing is left behind.

| Check | What it establishes |
|---|---|
| `sign_in.cjs` | The demonstration is offered first; a wrong password is explained; the demonstration opens; a session the server refuses says what the server answered. With `PROXY=strip` or `PROXY=replace` a proxy removes or replaces the `Authorization` header: the session still works and the server tells the operator. |
| `sign_up.cjs` | The sign-in page offers to create an account; a form that cannot be accepted is answered before anything is sent; the account is created and its session opens at once; it is an engineer account, not an administrator; it registers a plant; its password opens the next session; an address that is taken is refused next to the field; no password reaches the server log. With `PROXY=strip` the new session survives a proxy that removes the `Authorization` header. |
| `tour_demo.cjs` | Every page and tab as a demonstration visitor, on a desktop and on a 390 px screen: no sideways scrolling, no raw value (`null`, `NaN`, `undefined`) in the text, charts drawn, the PDF report downloads, an incomplete calculator input is refused. |
| `tour_admin.cjs` (`ADMIN=1`) | A signed-in account registers a plant, declares and imports a file through the form, runs an analysis, meets the duplicate check, creates an account, signs out. |
| `framing.cjs` | Another origin cannot embed the application by default; it can when `SOLARWISE_FRAME_ANCESTORS` names it. |

## Running them

```sh
# once
(cd frontend && npm ci && npm run build)        # the interface that the server will serve
(cd frontend/e2e && npm install)                # puppeteer-core; it does not download a browser

# a browser: any Chromium or Chrome
export CHROMIUM_PATH=/usr/bin/chromium

frontend/e2e/all.sh                             # the nine runs, one after the other
frontend/e2e/run.sh sign_in.cjs                 # or one check
PROXY=strip frontend/e2e/run.sh sign_in.cjs
PROXY=strip frontend/e2e/run.sh sign_up.cjs
ADMIN=1 frontend/e2e/run.sh tour_admin.cjs
FRAME=allowed frontend/e2e/run.sh framing.cjs allowed
```

`run.sh` needs the backend installed in `.venv` at the root of the repository (or `PYTHON=/path/to/python`), and
`curl`. Other settings: `DIST` (built interface, default `frontend/dist`), `CHROMIUM_ARGS` (extra arguments for the
browser; a container without user namespaces may need `--single-process --no-zygote`), `E2E_SHOTS` (where the
screenshots go, default `frontend/e2e/shots`, which is not committed), `E2E_PORT`, `E2E_PROXY_PORT`,
`E2E_PARENT_PORT`, and `E2E_DATABASE_URL` to run a check on another database than the throw-away SQLite file (an
empty PostgreSQL database, for example; it is not emptied afterwards).

`run.sh` runs any script given to it, so it also serves to script the application for other purposes:
`presentation/src/capture.cjs` takes the screenshots of the slides that way.

## Reading a failure

Each expectation prints `ok` or `FAIL` with what was observed. When a check fails, `run.sh` prints the end of the
server log, and a screenshot of the moment is in `shots/failed.png`.
