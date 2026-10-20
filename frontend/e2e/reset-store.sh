#!/usr/bin/env bash
# Replace the e2e study store with a fresh copy of the shared seed (a real Studio walk of the
# demo study), and drop the exports/ folder beside it, so writing tests (decide + undo, exports)
# start from the same state every run.
#
#   e2e/reset-store.sh [STORE]     STORE defaults to $QPILOT_STUDIES_DIR
#
# Run it with the server stopped (the server caches what it read); then start `qpilot app`.
set -euo pipefail

seed="${E2E_SEED:-${QP_ROOT:?source agent-bus/ui-env.sh first, or set E2E_SEED}/agent-bus/scratch/ui-seed/studies}"
store="${1:-${QPILOT_STUDIES_DIR:?set QPILOT_STUDIES_DIR or pass the store path}}"
port="${APP_PORT:-7860}"

[[ -d "$seed" ]] || { echo "no seed at $seed (set E2E_SEED)" >&2; exit 1; }
abs="$(cd "$store" 2>/dev/null && pwd || echo "$store")"
case "$abs" in
  "$seed" | "$seed"/*) echo "refusing: $store is the seed itself" >&2; exit 1;;
  */agent-bus/scratch/*) ;;
  *) [[ "${E2E_FORCE:-}" == 1 ]] || { echo "refusing: $store is not a scratch store (E2E_FORCE=1 to insist)" >&2; exit 1; };;
esac
if curl -s -o /dev/null --max-time 1 "http://127.0.0.1:$port/"; then
  echo "a server is answering on :$port; stop it first (it caches the store)" >&2
  exit 1
fi

mkdir -p "$store"
# Keep the store folder (the server may be pointed at it), replace what is in it.
find "$store" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
cp -R "$seed"/. "$store"/
# Records and Prism bundles are written to exports/ beside the store (kept across launches):
# a fresh run starts without the previous run's exports.
exports="$(dirname "$abs")/exports"
[[ -d "$exports" ]] && rm -rf "$exports"
echo "e2e store reset from the seed: $store"
