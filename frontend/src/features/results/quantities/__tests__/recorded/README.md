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
