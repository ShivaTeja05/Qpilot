# Recorded API answers for the Design tests

From the design agent's store: a Studio session of `sim/data/untergasser/large_DNA_dilutions.rdml`
(Untergasser et al., CC BY 4.0) opened through `POST /api/workspaces` and proposed in the page
(see `src/ui/proposal/recorded/README.md`). Nothing is hand-written. Re-record with the design
agent's server running (`qpilot app --port 7881`; the key is in `$QPILOT_APP_TOKEN`):

```bash
curl -s -H "x-qpilot-token: $QPILOT_APP_TOKEN" http://127.0.0.1:7881/api/sessions/2529de8272eb/plate > untergasser-plate.json
curl -s -H "x-qpilot-token: $QPILOT_APP_TOKEN" http://127.0.0.1:7881/api/sessions/2529de8272eb > untergasser-session.json  # "summary" dropped
```

## Imports (`import-*.json`)

The `capture` of a session frame (`GET /api/sessions/{sid}` → `capture`) for two exports of the
public corpus (`tests/fixtures/corpus`), opened through `POST /api/workspaces` with `files` on a
throwaway store (FastAPI TestClient over the real app, no model):

- `import-cfx-hsieh-gapdh.json`: every `2016-09-04 gapdh*` file of
  `biorad/hsieh2016-cfx-manager-3.1-sybr` (CFX Manager 3.1, baseline-subtracted, melt, two
  sheets qPilot does not read);
- `import-lc480-cp-table.json`: `roche/sanger-lc480-cp-table/qPCR.txt` (a LightCycler 480 Cp
  table: Cq only, standards, five omitted wells).

## The Design editor (`editor-*.json`, `plan-*.json`)

`python frontend/src/features/design/recorded/record_editor.py` (from the repository root; no
download, no model): the synthetic CFX Manager export of the corpus
(`synthetic/cfx-manager-raw-vs-baseline-subtracted`, raw RFU) opened through
`POST /api/workspaces` with `files` and a two-column group sheet, the rules' proposals made, then

- `editor-cfx-synthetic.json`: `GET /api/sessions/{sid}/design/editor`;
- `plan-cfx-synthetic.json`: `POST /api/sessions/{sid}/design/check` for a draft (REF a reference
  gene; S1 in group A, which the sheet proposed; S5 in group Z, the sheet said B; the NTC in a
  group, which the hard ban refuses).
