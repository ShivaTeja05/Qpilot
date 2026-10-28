# Recorded from the real API (no hand-written numbers)

Recorded 21 Oct 2026 from `qpilot app` (branch `ui/numbers`) on a fresh copy of the seeded demo
store (`frontend/e2e/reset-store.sh`: the real Studio walk of the demo), with
`record_axes.py`, which walks "Also test efficiency models" through the page's own routes:

```bash
frontend/e2e/reset-store.sh "$QPILOT_STUDIES_DIR"
qpilot app --no-open --port 7896 &
python frontend/src/features/results/__tests__/recorded/record_axes.py \
  http://127.0.0.1:7896 bc1d233e3866 frontend/src/features/results/__tests__/recorded
```

- `axes-off.json` — `ResultsView.axes` of the session's study before anything was asked
  (`GET /api/studies/{id}/results`).
- `proposals-choices-pending.json` — the choices stage's inbox after
  `POST /api/sessions/{sid}/propose/axis` (the rule's proposal, checked by D-AXIS).
- `axes-swept.json` — `ResultsView.axes` of the study analysed again after a person accepted it
  (the efficiency models are one more dimension of the grid; the card `card_efficiency`).
- `proposals-choices-decided.json` — the choices stage's inbox after the acceptance.

## The Evidence Ledger and a card opened from Trace

Recorded 21 Oct 2026 from `qpilot app` on port 7896 over a copy of the seeded demo store, after
one **Decide…** on Trace's Where to look (`frontend/src/features/trace/__tests__/recorded/record_where.py --open`):

```bash
python frontend/src/features/results/__tests__/recorded/record_ledger.py --port 7896 --study e300000d4f9a
```

- `evidence.json` — `GET /api/studies/{id}/evidence` (the Evidence Ledger).
- `cards-trace.json` — `GET /api/studies/{id}/cards` with the `trace_set_aside` card the
  Decide… opened (`place` set); the stored cards' `card.options[].per_gene` are left out (`{}`).

## The normalisers and the reference panel (ex/norm)

Recorded 28 Oct 2026 from `qpilot app` (branch `ex/norm`) on a fresh copy of the seeded demo store
(`agent-bus/scratch/ui-seed/studies`, the real Studio walk of the demo), with `record_norm.py`,
which walks "Also test other normalisers" through the page's own routes:

```bash
python frontend/src/features/results/__tests__/recorded/record_norm.py \
  http://127.0.0.1:7958 bc1d233e3866 frontend/src/features/results/__tests__/recorded
```

- `references.json` — `GET /api/studies/{id}/references` (geNorm and NormFinder side by side).
- `normaliser-off.json` — `ResultsView.axes` before anything was asked.
- `proposals-normaliser-pending.json` — the choices inbox after
  `POST /api/sessions/{sid}/propose/axis {"axis": "normaliser"}` (checked by D-AXIS).
- `normaliser-swept.json` — `ResultsView.axes` after a person accepted it (`card_normaliser`).
- `card-normaliser.json` — that card as `GET /api/studies/{id}/cards` lists it
  (`card.options[].per_gene` left out).
