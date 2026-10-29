# Recorded from the real API (no hand-written numbers)

Recorded 28 Oct 2026 from `qpilot app` (branch `ex/quant`) with `record_quantities.py`, which
walks a real QuantStudio 3 export (corpus `thermofisher/securebio-qs3-design-analysis-2.7`,
airplane wastewater, SARS-CoV-2 and PMMoV) through the page's own routes, as a person would on
the Design page with no model: PMMoV the reference gene, the standards `Std 1` … `Std 5` a
ten-fold series from 100,000 copies (the person's input: the export does not carry quantities),
the DNI and DSI samples the groups, DNI vs DSI the comparison; both blind stages confirmed.

```bash
qpilot app --no-open --port 7949 &
python frontend/src/features/results/quantities/__tests__/recorded/record_quantities.py 7949
```

- `quantities.json` — `GET /api/studies/{id}/quantities` (both assays' curves, LOD, LOQ).
- `quantities-cov2.json` — `GET /api/studies/{id}/quantities/Cov2` (the curve's points, levels
  and prediction band; every sample's copies with its interval and flags).
- `copies.json` — `GET /api/tools/copies?ng=1&length=3000&step=10&levels=4`.

## A quantification run (purpose: quantify samples)

Recorded with `record_quantify.py` (in-process, a fresh study store, no model): the same
QuantStudio 3 export, but the person's purpose is _quantify samples_ (no groups, no reference
gene) and the standards are a ten-fold series from 100,000 copies; both blind stages confirmed.

```bash
python frontend/src/features/results/quantities/__tests__/recorded/record_quantify.py
```

- `quantify-quantities.json`, `quantify-cov2.json` — the Quantities view (with each unit's class).
- `quantify-cards.json` — the quantity cards (which wells count as detected waits for a person:
  Cq ≤ 35 reports 9 of 54 sample results differently).
- `quantify-frame.json` — the session's frame (`purpose: quantify`).
- `../../../design/recorded/editor-quantify.json` — the Design editor after the person's choice.
