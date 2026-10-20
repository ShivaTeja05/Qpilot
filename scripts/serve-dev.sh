#!/bin/bash
# Development: serve the one page on 127.0.0.1:${PORT:-7860} with a fixed launch key, so a
# browser pane or `npm run dev` can be pointed at http://127.0.0.1:7860/?token=$QPILOT_APP_TOKEN.
# Uses its own study folder unless QPILOT_STUDIES_DIR is set. Never use a fixed key otherwise.
set -euo pipefail
cd "$(dirname "$0")/.."
export QPILOT_APP_TOKEN="${QPILOT_APP_TOKEN:-qpilot-dev}"
export QPILOT_MODEL_PROVIDER="${QPILOT_MODEL_PROVIDER:-none}"
export QPILOT_STUDIES_DIR="${QPILOT_STUDIES_DIR:-$HOME/.cache/qpilot/dev-studies}"
exec .venv/bin/qpilot app --no-open --port "${PORT:-7860}"
