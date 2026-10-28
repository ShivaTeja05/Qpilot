# End-to-end tests (Playwright + axe)

The whole page, in a real browser, against a real `qpilot app` over a real study store. The tests
start nothing: you start the server, they open the link it printed.

## Run

```bash
source "…/agent-bus/ex-env.sh" e2e        # venv, store, ports, launch key, QPILOT_MODEL_PROVIDER=none
frontend/e2e/reset-store.sh               # fresh copy of the seeded demo store (server stopped)
(cd frontend && npm run build)            # the page the server serves; do not commit qpilot/web/static
qpilot app --no-open --port $APP_PORT &   # the server under test (no model: the specs check it)
cd frontend && npx playwright install chromium   # once per machine (browsers are not committed)
nice -n 10 npm run e2e                    # all specs; or: npx playwright test e2e/own-data.spec.ts
```

Commit only `frontend/e2e/**` and `playwright.config.ts` (`git add frontend/e2e …`); never
`git checkout -- qpilot/web/static` while a run is going: it swaps the page under the test for the
last committed build. Restore it only before committing or merging, then build again.

- `E2E_URL` — the link qPilot printed (default `http://127.0.0.1:$APP_PORT/?token=qpilot-dev`).
- `E2E_READONLY=1` — skip the tests that write (decide + undo, exports, the walks of real files).
- `E2E_WORKERS` — parallel browsers (default 1: one server, one store, a shared machine). Run the
  suite under `nice -n 10`.
- A click that cannot happen fails after a minute (`actionTimeout`) with the page's state in
  `test-results/<test>/error-context.md`.

The specs that open a lab's own files (`own-data`, `quantities`, `comparisons`) add sessions to
the store and walk them once: on a store that already walked a file, the walk is skipped (re-copy
the seed) and the tests after it read the walked session from the server. `trace-decide` sets a
sample of the demo aside and puts it back (the demo's study is the same at the end).

The report is `frontend/playwright-report/` (`npx playwright show-report`); traces of failures
are in `frontend/test-results/`. Screenshots of every section at 1440 / 1024 / 768 / 390 px in
light and dark go to `frontend/e2e/screenshots/<section>/<width>-<theme>.png` (gitignored).
Every state's axe findings are saved to `frontend/e2e/screenshots/axe/<state>.json` (cleared at
the start of a run); `node e2e/axe-summary.mjs [--all]` groups them by rule and element, with the
states each was seen in, ready to post to the owners.

## What every test checks

- **Real data only.** What the page must show (workspace titles, proposal subjects and counts,
  genes, cards, chain entries) is read from the API of the server under test (`support/data.ts`).
  No test carries its own numbers, genes or names.
- **axe** (`app.axe(state)`, WCAG 2.2 A + AA): serious and critical violations fail the test;
  all findings are attached to the report as `axe-<state>.json`.
- **Nothing leaves the machine.** Any request to another origin fails the test.
- **No console errors**, no uncaught exceptions; no `NaN` / `undefined` / stack traces on screen.
- **No sideways page scroll** at any width.

## Specs

Every feature has landed (`support/sections.ts` lists the sections and their owners); a section
that shows the development placeholder fails. `support/studio.ts` walks a Studio session as a
person does (Open, decide what waits in a stage, confirm it) and reads what a job prepares;
`support/files.py` (the venv's `python3 -I`) reads the files the page downloads (a workbook with
openpyxl, a zip, a Prism project).

| Spec                     | Covers                                                                                                                                                                                                                                                                                                                                                                                                  | Owners                                           |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ |
| `screens.spec.ts`        | every section × 1440/1024/768/390 × light/dark: renders, heading, axe, no side scroll, no bug text, screenshot                                                                                                                                                                                                                                                                                          | all                                              |
| `shell.spec.ts`          | printed link, other-launch 403, CSP, needs-key screen, rail and bottom bar reach every section, next step, top bar, unknown study, theme                                                                                                                                                                                                                                                                | shell                                            |
| `home.spec.ts`           | Open (Recent = /api/workspaces, system strip, mouse and keyboard), Settings (model, never-does, autonomy, theme)                                                                                                                                                                                                                                                                                        | home                                             |
| `studio.spec.ts`         | Design and Curves inboxes = /proposals, a decided card read-only, plate map and well, Curves plate, blind                                                                                                                                                                                                                                                                                               | design, curves                                   |
| `results.spec.ts`        | all genes, Call counts, map summary + table, Decision Cards = /cards, j/k/Enter, decide + Undo vs /decisions, gene row → Gene                                                                                                                                                                                                                                                                           | insight, gene                                    |
| `audit.spec.ts`          | verdict strip = /audit/overview, every tab, gene → Gene; Gene header = /results numbers, panels, prev/next                                                                                                                                                                                                                                                                                              | audit, gene                                      |
| `prism.spec.ts`          | routes into Prism = /prism/routes, gene links                                                                                                                                                                                                                                                                                                                                                           | prism                                            |
| `record.spec.ts`         | timeline = /decisions, Intact, Export → download → Verify, a changed copy fails; Agents = /api/agents                                                                                                                                                                                                                                                                                                   | record                                           |
| `keyboard.spec.ts`       | ⌘K, `?`, g then a letter, ⌘J Ask + an answered example, focus rings                                                                                                                                                                                                                                                                                                                                     | shell, ask                                       |
| `planner.spec.ts`        | Plan next = /planner: groups, rule, every gene, explorer defaults, plates                                                                                                                                                                                                                                                                                                                               | planner                                          |
| `history-report.spec.ts` | History = /history (timeline, Studio log, Intact); Report = /report (summary, findings, methods, MIQE), passport download                                                                                                                                                                                                                                                                               | history, report                                  |
| `claims.spec.ts`         | a pasted paragraph's verdicts and counts = POST /claims; Try an example                                                                                                                                                                                                                                                                                                                                 | claims                                           |
| `trace.spec.ts`          | overview = /trace, a gene's trace = /trace/{gene}, the link from Gene                                                                                                                                                                                                                                                                                                                                   | trace                                            |
| `gate.spec.ts`           | Controls = /gate: headline, plates, Decision Cards from the controls, a check opens to its reason, axe                                                                                                                                                                                                                                                                                                  | gate                                             |
| `walk.spec.ts`           | `E2E_WALK=1` only: fresh demo → design → curves → results equal the seeded walk's (moves the demo aside; reset after)                                                                                                                                                                                                                                                                                   | design, curves, home                             |
| `own-data.spec.ts`       | a LightCycler 96 .lc96p (corpus), no model: Open → "Set the design on this page" (roles, groups, comparison) → Curves → Results; the melt panel and G-MELT lines = /melt, /gate; every export downloads, the workbook's numbers are number cells (openpyxl); Gene figure SVG/PNG; Send to Prism writes the .pzfx, an edited one uploaded raises questions; one decision reads each view once and no 409 | design, curves, melt, exports, gene, prism, perf |
| `quantities.spec.ts`     | the QuantStudio 3 wastewater export (corpus): standards from the ng → copies helper (= /tools/copies), groups, comparison; Results → Quantities: copies with 95 % prediction intervals = /quantities                                                                                                                                                                                                    | quant, design                                    |
| `comparisons.spec.ts`    | the K. phaffii LinRegPCR RDML (corpus): Several comparisons, each vs a control, Dunnett; Results picker, side-by-side table with q = /comparisons; Trace and the gene's page follow the pick                                                                                                                                                                                                            | compare, compare2                                |
| `trace-decide.spec.ts`   | demo: Decide… on a place that changes a call → set aside → the call changes; Put the wells back → the first study again; Run Review's repeat plan and its plate CSV                                                                                                                                                                                                                                     | followup, trace                                  |
| `phone.spec.ts`          | every analysed session at 375 px (touch): Results' genes, every Decision Card, a card open, no side scroll, axe                                                                                                                                                                                                                                                                                         | insight, polish                                  |
