# Integrating origin/main (18 Oct) into the one page

Branch `ui/integrate-main` = `ui/one-page` (7c87f26: the one FastAPI + React page that replaced the
Gradio app, Gradio Studio and qsim's page) + `origin/main` (7765f40: Shiva Teja's 32 commits of
18 Oct, partly built on the Gradio app). Nothing of origin/main is dropped; the one page stays the
only UI. This file says what was combined, ported or left out, and why.

## 1. Where both sides built the same thing

| Area | ui/one-page | origin/main | Kept |
|---|---|---|---|
| **Trace** | `qpilot/trace/` (the Trace section): every sample's exact influence on a call, the fewest samples that change it, control-gene shares, the study overview, a plate, a what-if without samples; traces **the analysis in use** (each card's applied option) and refuses if its numbers differ from the grid | `qpilot/qpcr/trace.py`: from a gene, a **sample or a well** to the places to look; fingerprint checks S1–S7 with robust z; options (keep / read from the other references / set aside) ranked by consequence class; `trace_set_aside` Decision Cards; a planted-fault benchmark (T3); CLI `qpilot trace`, MCP `qpcr_trace`, Ask, the Excel sheet; traced the **planned** analysis only | **Both, each for what it does best.** The Trace section keeps `qpilot/trace`; origin/main's engine is the section's **Where to look** panel and Decide…, and stays the engine of the CLI, MCP, Ask and Excel. It gained `build_context(cell=)` so the page traces the analysis in use, and the route refuses unless its fold changes equal the Trace section's at that analysis. On the demo both agree (tumour 2016, HMBS_20080318/K22: values read 5.55× too high; CAMTA2 changes) |
| **Planner** (`qpcr/plan.py`) | `min_log2fc`, pooled SD, σ interval, `n_for_call`, `simulate_calls(n_other=)`; plate layouts | the replicate budget (biological, RT and technical replicates; cheapest design) | **Combined** in one `plan()`: both sets of arguments (keyword-only); the simulation uses the effective SD at the rule's threshold |
| **Report** (`qpilot/report/`) | Methods, MIQE 2.0, a reviewer's report, a passport | the Run Review (`run_review.py`) and the Excel export (`excel.py`) | **Both** in one package: the Run Review is a panel of the Report section with a person's sign-off; the workbook is a fourth export format |
| **MCP surface** | `agents/surface.py`: titles, annotations and output schemas from one table (`SPECS`); typed refusals (error, code, fix); idempotency keys | `TOOL_META` + `HINTS` annotations; nine new tools answering `{"error": …}` | **`SPECS` is the one table** (nine entries and output schemas added); `TOOL_META` is a read-only view of it; the nine tools answer typed refusals. 21 `qpcr_*` + 5 `sim_*` tools |
| **Card kinds** | an open registry (`core/card_kinds.py`, G3) | a closed `Literal` with `trace_set_aside` added | **The registry**, with `trace_set_aside` registered (owner `trace`); a trace card validates like any other |
| **Raw-ness of the curves** | `io/rawness.py`: Open's check of an instrument export (raw / Rn / baseline-subtracted / scaled / Cq only / unknown) | the Evidence Ledger's raw-ness item: "not judged, the detector is not built" | **Combined**: the ledger reads the import's verdict when the study came from an export (raw/Rn → present, baseline-subtracted/Cq only → absent, scaled/unknown → unknown); otherwise it says the file did not go through the check |
| **Decision store** (`core/store.py`) | carried decisions (`carry_decisions`), the `_append` double-entry fix | on-demand cards (`trace_cards.json`), run reviews in the chain, artifact files | **Both.** Carrying skips on-demand cards and review entries and writes `cards.json` from the analysis's cards only; `clean_reason` refuses the "Carried from analysis" prefix for every reason, comment and reviewer name |
| **Ask** (`ai/ask.py`) | study topics (overview, calls, references, cards), "not understood" | Trace questions ("why is X no call?", "where should I look?", a well) | **Both**: Trace questions route first, then the study topics |
| **`qpcr/space.py`** | stage caches for the efficiency axis | a public what-if API over its internals | **Both**: the what-if API reads the stage caches, so it works on any matrix axis |

One difference stays visible: **Ask, MCP's `qpcr_trace`, `qpilot trace` and the Excel sheet**
trace the stored results (every choice at its recommended option), as on origin/main; the Trace
section and its Where to look trace **the analysis in use**. They differ only once a person has
decided a card away from its recommended option.

Not combined (different questions, kept apart): origin/main's G-RT and G-INSTR gate lines
(`qpcr/gate_rt.py`, `gate_instr.py`) feed the Evidence Ledger and the run-file reading; the Run
Gate rule pack (`core/rules.py`, `qpcr/gate_rules.py`: G-TYPED, NTC, NAC, NRT, POS, STD, REP) is
the Controls section. `core/consequence.py` (Trace's consequence classes) and `core/gate.py`
(the Run Gate's consequence test over the grid) answer different questions.

## 2. The Gradio features, now on the page

| origin/main (Gradio app) | On the page | API | Tests (`tests/web/`) |
|---|---|---|---|
| Evidence Ledger panel | Results: "What this study cannot tell you" | `GET /api/studies/{id}/evidence` | `test_evidence_review.py` |
| Run Review accordion + sign-off | Report: Run Review with the sign-off form | `GET …/review`, `POST …/review/sign-off` | `test_evidence_review.py` |
| Trace accordion + Decide… | Trace: Where to look (gene, sample or well) + Decide…; the card on Results says its place | `GET …/where-to-look`, `POST …/where-to-look/open` | `test_where_to_look.py` |
| Excel export (CLI) | Report: export "Excel workbook" | `POST …/report/export {format: xlsx}` | `test_excel_route.py` |
| Spreadsheet Check (CLI, MCP) | Sheet check (lab section) | `POST /api/sheets`, `POST /api/sheets/{id}/check` | `test_sheets.py` |
| Instrument logbook (CLI, MCP) | Instruments (lab section) | `/api/instruments…`, `POST …/lookback` | `test_instruments.py` |
| Templates (`explain/templates.py`) | every sentence above is a registered template's validated token text | — | engine tests as on origin/main |

Every new write is `actor="human"` (set by the server); every new `GET` writes nothing and every
study route is blind until the design and curves are confirmed (the parity and red-team sweeps
enumerate the routes, so they cover these too).

## 3. Left out, and why

* **The Gradio app, qsim's HTTP page and their UI tests** (`qpilot/app.py`, `sim/src/qsim/app_page.html`,
  `tests/app/test_app.py`): the one page replaced them on ui/one-page. Their features are ported
  above; the safety assertions of `tests/app/test_app.py` and `test_app_state.py` are carried into
  `tests/web/` (§2) and `tests/app/test_app_state.py` (view-models the page still uses).
* **qsim's results-screen redesign** (5620ca3, 47b66e1): the page's Audit, Gene and Report
  sections already cover its views (its one engine change, the overview naming the planned
  reference genes, is kept: the API serves it and the Audit header says it) (overview and verdicts, genes with prev/next, the what-if lab,
  a methods paragraph and exports); its decision record kept in the browser is replaced by the
  real decision chain.
* **`demo/demo.mp4`** (a recording of the Gradio app): kept in the repository, no longer linked
  from the README.
* **Inferred instrument events across successive run files** (`infer_events(previous, current)`):
  needs the previous run's summary, which holds serial numbers; the page links a run file and logs
  what the file itself states (an aborted run, a pause). Calibrations and part changes are logged
  by a person.
* **Lookback `--log`** (recording a lookback in the logbook) and **position history**
  (`qpilot instrument position`): on the command line only.
* **The replicate budget on Plan next**: in `plan()`, the CLI and MCP; Plan next shows the
  study-noise planner as before.
* **A Trace card's set-aside applied to the analysis**: as on origin/main, deciding a
  `trace_set_aside` card records the decision; the numbers stay as analysed (leaving a well out
  is Curves' or Controls' job).

## 4. ui/one-page merged again (b3cfdf8)

After the first pass (198fe22), ui/one-page gained the Import Trust card (ui/import-trust 0615720:
a confidence cap and Cq only for baseline-subtracted or unknown export curves,
`GET/POST /api/studies/{id}/import-trust`, the Results card, `pending_human` over MCP) and the
refusal-table fixes of e9aed03. Merged as 2fa4a08: `docs/app.md` keeps both the Evidence Ledger /
Trace cards and Import Trust in Results; `schema.d.ts` regenerated; the page rebuilt from the
merged source. Shiva's nine MCP tools and Import Trust's sentences all keep their refusal codes.
Import Trust and the Evidence Ledger's raw-ness item read the same import check (`io/rawness`):
the card decides what to do about it, the ledger says what it means.

## 5. ui/one-page merged a third time (0f7c415)

Hosted mode for a public sandbox (`QPILOT_HOSTED=1`: extra hosts, allowed origins, framing, no
launch key; `SystemView.hosted`, the HostedBanner), the Hugging Face Space files
(`deploy/hf-space/`, `scripts/build_hf_space.py`) and HEAD on the page route. Merged as 3de7dcd:
only the built page conflicted (rebuilt); `schema.d.ts` regenerated. This branch's routes
(evidence, review, where-to-look, sheets, instruments) go through the same Guard, so hosted mode
covers them as it covers every route.

## 6. Gates on this branch (21 Oct 2026, after 3de7dcd)

ruff check + format clean (whole repository) · `pytest -m "not demo_data"` 3562 passed, 3 skipped,
6 xfailed (the capture weak spots, strict) · `pytest -m demo_data` 420 passed · `sim/tests` 55
passed · `qpilot studio demo --check` 28/28 · `scripts/demo_regression.py` PASS (17/17 locked;
results.json additive) · frontend typecheck, lint, prettier, `check:api` clean, vitest 381 passed,
build committed · e2e (Playwright + axe, fresh copy of the seeded demo store) 212 passed,
2 skipped, 0 failed, including `e2e/integrate.spec.ts` and the two lab sections at every width
and theme. Nothing is pushed.
