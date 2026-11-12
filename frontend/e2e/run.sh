#!/usr/bin/env bash
# Start a throw-away server (its own database, its own key) on 127.0.0.1, run one browser check against it, stop it.
#
# usage: [ADMIN=1] [PROXY=strip|replace] [FRAME=allowed] ./run.sh <script.cjs> [arguments]
#
#   ADMIN=1          create an administrator account; its credentials are passed to the script
#   PROXY=strip      put a proxy that removes the Authorization header between the browser and the server
#   PROXY=replace    the same, but the proxy replaces the header by a credential of its own
#   FRAME=allowed    let the page that framing.cjs serves embed the application
#
#   E2E_DATABASE_URL an empty database to use instead of a throw-away SQLite file, for example
#                    postgresql+psycopg://user:password@localhost/solarwise_e2e (it is not emptied afterwards)
#   PYTHON           interpreter with the backend installed (default: <repository>/.venv/bin/python)
#   DIST             built interface to serve (default: <repository>/frontend/dist)
#   CHROMIUM_PATH    browser executable; CHROMIUM_ARGS: extra arguments for it
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
DIST="${DIST:-$ROOT/frontend/dist}"
PORT="${E2E_PORT:-18011}"
PROXY_PORT="${E2E_PROXY_PORT:-18013}"
export E2E_PARENT_PORT="${E2E_PARENT_PORT:-18014}"

[ $# -ge 1 ] || { echo "usage: [ADMIN=1] [PROXY=strip|replace] [FRAME=allowed] $0 <script.cjs> [arguments]" >&2; exit 2; }
[ -x "$PYTHON" ] || { echo "no interpreter at $PYTHON: install the backend (see README.md) or set PYTHON" >&2; exit 2; }
[ -f "$DIST/index.html" ] || { echo "no built interface in $DIST: run 'npm run build' in frontend/ or set DIST" >&2; exit 2; }
[ -d "$HERE/node_modules/puppeteer-core" ] || { echo "run 'npm install' in $HERE first" >&2; exit 2; }

WORK="$(mktemp -d)"
PIDS=()
cleanup() {
  for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null; done
  wait 2>/dev/null
  rm -rf "$WORK"
}
trap cleanup EXIT

random() { "$PYTHON" -c "import secrets; print(secrets.token_urlsafe($1))"; }
export E2E_ADMIN_EMAIL=admin@example.org
E2E_ADMIN_PASSWORD="$(random 18)"
export E2E_ADMIN_PASSWORD
export SERVER_LOG="$WORK/server.log"

(
  cd "$ROOT/backend" || exit 2
  export SOLARWISE_DEMO_MODE=true DATABASE_URL="${E2E_DATABASE_URL:-sqlite:///$WORK/solarwise.db}" SOLARWISE_FRONTEND_DIST="$DIST"
  SOLARWISE_SECRET_KEY="$(random 48)"
  export SOLARWISE_SECRET_KEY
  if [ "${ADMIN:-0}" = 1 ]; then
    export SOLARWISE_BOOTSTRAP_ADMIN_EMAIL="$E2E_ADMIN_EMAIL" SOLARWISE_BOOTSTRAP_ADMIN_PASSWORD="$E2E_ADMIN_PASSWORD"
  fi
  if [ "${FRAME:-}" = allowed ]; then export SOLARWISE_FRAME_ANCESTORS="http://127.0.0.1:$E2E_PARENT_PORT"; fi
  exec "$PYTHON" -m uvicorn --factory solarwise.api.app:get_app --host 127.0.0.1 --port "$PORT" > "$SERVER_LOG" 2>&1
) &
PIDS+=($!)

wait_for() { # port
  for _ in $(seq 1 120); do
    curl -s -o /dev/null -m 1 "http://127.0.0.1:$1/api/v1/health" && return 0
    sleep 0.25
  done
  return 1
}
wait_for "$PORT" || { echo "the server did not start:" >&2; cat "$SERVER_LOG" >&2; exit 2; }
export BASE_URL="http://127.0.0.1:$PORT"

if [ -n "${PROXY:-}" ]; then
  "$PYTHON" "$HERE/header_proxy.py" "$PROXY_PORT" "$PORT" "$PROXY" &
  PIDS+=($!)
  wait_for "$PROXY_PORT" || { echo "the proxy did not start" >&2; exit 2; }
  export BASE_URL="http://127.0.0.1:$PROXY_PORT"
fi

cd "$HERE" && node "$@"
STATUS=$?
if [ $STATUS -ne 0 ]; then
  echo "--- end of the server log" >&2
  tail -n 25 "$SERVER_LOG" >&2
fi
exit $STATUS
