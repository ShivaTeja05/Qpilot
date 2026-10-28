# Recorded from the real API (no hand-written numbers)

Recorded 20 Oct 2026 from `qpilot app` on the curves agent's seeded store (the Studio walk of the
demo study: Vermeulen, 64 plates; design and curves confirmed), session `bc1d233e3866`:

```bash
source "/Users/gangadhara/Documents/Wheel Hack/agent-bus/ui-env.sh" curves
qpilot app --no-open --port $APP_PORT &
H=(-H "x-qpilot-token: qpilot-dev" -H "origin: $QPILOT_API")
curl -s "${H[@]}" "$QPILOT_API/api/sessions/bc1d233e3866/plate?run=CDH5_20080305" \
  | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin), separators=(',', ':')))" \
  > plate-CDH5_20080305.json
```

CDH5_20080305 is a 384-well plate with 5 wells where the Curve Judge disagrees with LinRegPCR
and 15 wells LinRegPCR calls not amplified.

## plate-lc96-bACTXY.json (multiplex)

Recorded 28 Oct 2026 by the multiplex agent from the real API (`GET /api/sessions/{sid}/plate`,
the FastAPI app under `TestClient`, no model) after the Studio walk of
`tests/web/test_multiplex_walk.py::test_a_lightcycler96_4plex_with_an_ipc_from_design_to_the_run_gate`
on `tests/fixtures/corpus/rdml/lightcycler96-rdml-1.1/lc96_bACTXY.rdml` (LightCycler 96, four dyes
per well: FAM bACT, Hex X, Texas Red Y, Cy5 IPC; design and curves confirmed). The wells of the
four empty channels (`no target (…)`, 320 entries) are left out of the file to keep it small;
every other entry is as the API sent it.
