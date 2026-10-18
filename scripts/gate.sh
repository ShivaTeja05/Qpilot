#!/usr/bin/env bash
# The merge gate for qPilot: lint, format, the full test suite and the demo regression.
#
#   scripts/gate.sh            # the gate (what the release captain runs on every merge)
#   scripts/gate.sh --heavy    # + Studio demo check, the integration demo and the MCP tool list
#   scripts/gate.sh --fast     # lint + format + demo regression only (no pytest), while developing
#
# Run from anywhere; it works on the checkout it lives in. Prints one summary line at the end:
#   GATE: PASS | ruff ok | format ok | pytest 2101 passed, 3 skipped (412s) | demo PASS (...)
# Exit code 0 only when everything is green. Logs go to $GATE_LOG_DIR (default: a temp dir).
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 2
MODE="${1:-}"
LOG="${GATE_LOG_DIR:-$(mktemp -d -t qpilot-gate)}"
mkdir -p "$LOG"
export MPLBACKEND=Agg GRADIO_ANALYTICS_ENABLED=False
export QPILOT_MODEL_PROVIDER="${QPILOT_MODEL_PROVIDER:-none}"
status=0
parts=()

if ruff check . >"$LOG/ruff.txt" 2>&1; then parts+=("ruff ok"); else parts+=("ruff FAIL"); status=1; fi
if ruff format --check . >"$LOG/format.txt" 2>&1; then
  parts+=("format ok")
else
  parts+=("format FAIL ($(grep -c '^Would reformat' "$LOG/format.txt") files)"); status=1
fi

if [[ "$MODE" != "--fast" ]]; then
  start=$(date +%s)
  pytest -q -p no:cacheprovider >"$LOG/pytest.txt" 2>&1
  rc=$?
  secs=$(( $(date +%s) - start ))
  line="$(grep -E '^(=+ )?[0-9]+ (passed|failed)|^=+ .*(passed|failed|error)' "$LOG/pytest.txt" | tail -1 | sed -E 's/=//g; s/^ +| +$//g')"
  if [[ $rc -eq 0 ]]; then parts+=("pytest ${line} (${secs}s)"); else parts+=("pytest FAIL: ${line} (${secs}s)"); status=1; fi
fi

python scripts/demo_regression.py --fresh-curves >"$LOG/demo.txt" 2>&1
rc=$?
demo="$(grep '^DEMO REGRESSION' "$LOG/demo.txt" | tail -1 | sed 's/^DEMO REGRESSION: //')"
if [[ $rc -eq 0 ]]; then parts+=("demo ${demo}"); elif [[ $rc -eq 2 ]]; then parts+=("demo ${demo}"); else parts+=("demo FAIL: ${demo:-crashed}"); status=1; fi

if [[ "$MODE" == "--heavy" ]]; then
  scratch="$(mktemp -d -t qpilot-gate-heavy)"
  if qpilot studio demo --check >"$LOG/studio_demo.txt" 2>&1; then parts+=("studio-demo ok"); else parts+=("studio-demo FAIL"); status=1; fi
  if python -m qpilot.integration demo --out "$scratch/integration-demo" >"$LOG/integration_demo.txt" 2>&1; then
    parts+=("integration-demo ok")
  else
    parts+=("integration-demo FAIL"); status=1
  fi
  if qpilot serve --list-tools >"$LOG/tools.txt" 2>&1; then
    parts+=("mcp $(grep -m1 '^# ' "$LOG/tools.txt" | sed -E 's/^# //; s/;.*//')")
  else
    parts+=("mcp list-tools FAIL"); status=1
  fi
fi

verdict=PASS
[[ $status -ne 0 ]] && verdict=FAIL
summary="GATE: ${verdict}"
for p in "${parts[@]}"; do summary+=" | $p"; done
if [[ $status -ne 0 ]]; then
  # Show what failed, briefly, above the summary.
  grep -E 'FAILED|ERROR|Error' "$LOG/pytest.txt" 2>/dev/null | head -30
  grep -E '^ +(FAIL|changed)' "$LOG/demo.txt" 2>/dev/null | head -30
  head -30 "$LOG/ruff.txt" 2>/dev/null | grep -v '^All checks passed' || true
  grep '^Would reformat' "$LOG/format.txt" 2>/dev/null | head -10
fi
echo "logs: $LOG"
echo "$summary"
exit $status
