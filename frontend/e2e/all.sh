#!/usr/bin/env bash
# Every browser check, one after the other, each against a fresh server. Exit code 0 only if all of them pass.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FAILED=()
RUNS=0
check() { # label, then the command line of run.sh (environment assignments first)
  local label="$1"; shift
  RUNS=$((RUNS + 1))
  echo
  echo "=== $label"
  if env "$@"; then :; else FAILED+=("$label"); fi
}
check "sign-in, direct connection"                      "$HERE/run.sh" sign_in.cjs
check "sign-in, proxy removing Authorization"           PROXY=strip "$HERE/run.sh" sign_in.cjs
check "sign-in, proxy replacing Authorization"          PROXY=replace "$HERE/run.sh" sign_in.cjs
check "sign-up, direct connection"                      "$HERE/run.sh" sign_up.cjs
check "sign-up, proxy removing Authorization"           PROXY=strip "$HERE/run.sh" sign_up.cjs
check "first visit, from the demonstration to a report" "$HERE/run.sh" first_use.cjs
check "demonstration tour"                              "$HERE/run.sh" tour_demo.cjs
check "work of a signed-in account"                     ADMIN=1 "$HERE/run.sh" tour_admin.cjs
check "framing refused by default"                      "$HERE/run.sh" framing.cjs refused
check "framing by an allowed origin"                    FRAME=allowed "$HERE/run.sh" framing.cjs allowed
echo
if [ ${#FAILED[@]} -eq 0 ]; then
  echo "browser checks: $RUNS of $RUNS passed"
else
  echo "browser checks: ${#FAILED[@]} of $RUNS FAILED: ${FAILED[*]}"
  exit 1
fi
