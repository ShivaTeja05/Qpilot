# End-to-end tests (Playwright + axe)

The whole page, in a real browser, against a real `qpilot app` over a real study store. The tests
start nothing: you start the server, they open the link it printed.

## Run

```bash
source "…/agent-bus/ui-env.sh" e2e        # venv, store, ports, launch key
frontend/e2e/reset-store.sh               # fresh copy of the seeded demo store (server stopped)
(cd frontend && npm run build)            # the page the server serves; do not commit qpilot/web/static
qpilot app --no-open --port $APP_PORT &   # the server under test
cd frontend && npx playwright install chromium   # once per machine (browsers are not committed)
nice -n 10 npm run e2e                    # all specs; or: npx playwright test e2e/screens.spec.ts
```

Commit only `frontend/e2e/**` and `playwright.config.ts` (`git add frontend/e2e …`); never
`git checkout -- qpilot/web/static` while a run is going: it swaps the page under the test for the
last committed build. Restore it only before merging `ui/one-page`, then build again.

- `E2E_URL` — the link qPilot printed (default `http://127.0.0.1:$APP_PORT/?token=qpilot-dev`).
- `E2E_READONLY=1` — skip the tests that write (decide + undo, export).
- `E2E_WORKERS` — parallel browsers (default 1: one server, one store, a shared machine). Run the
  suite under `nice -n 10`.

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

## Sections that have not landed

`support/sections.ts` has one flag per feature (`LANDED`) with its owner. A test of a feature
that has not been merged into `ui/one-page` yet is `test.fixme` with the owner's name; the
screens spec also marks a section `fixme` while it still shows the development placeholder.
Flip the flag when the coordinator announces the merge.

| Spec                     | Covers                                                                                                                                   | Owners               |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- | -------------------- |
| `screens.spec.ts`        | every section × 1440/1024/768/390 × light/dark: renders, heading, axe, no side scroll, no bug text, screenshot                           | all                  |
| `shell.spec.ts`          | printed link, other-launch 403, CSP, needs-key screen, rail and bottom bar reach every section, next step, top bar, unknown study, theme | shell                |
| `home.spec.ts`           | Open (Recent = /api/workspaces, system strip, mouse and keyboard), Settings (model, never-does, autonomy, theme)                         | home                 |
| `studio.spec.ts`         | Design and Curves inboxes = /proposals, a decided card read-only, plate map and well, Curves plate, blind                                | design, curves       |
| `results.spec.ts`        | all genes, Call counts, map summary + table, Decision Cards = /cards, j/k/Enter, decide + Undo vs /decisions, gene row → Gene            | insight, gene        |
| `audit.spec.ts`          | verdict strip = /audit/overview, every tab, gene → Gene; Gene header = /results numbers, panels, prev/next                               | audit, gene          |
| `prism.spec.ts`          | routes into Prism = /prism/routes, gene links                                                                                            | prism                |
| `record.spec.ts`         | timeline = /decisions, Intact, Export → download → Verify, a changed copy fails; Agents = /api/agents                                    | record               |
| `keyboard.spec.ts`       | ⌘K, `?`, g then a letter, ⌘J Ask + an answered example, focus rings                                                                      | shell, ask           |
| `planner.spec.ts`        | Plan next = /planner: groups, rule, every gene, explorer defaults, plates                                                                | planner              |
| `history-report.spec.ts` | History = /history (timeline, Studio log, Intact); Report = /report (summary, findings, methods, MIQE), passport download                | history, report      |
| `claims.spec.ts`         | a pasted paragraph's verdicts and counts = POST /claims; Try an example                                                                  | claims               |
| `trace.spec.ts`          | overview = /trace, a gene's trace = /trace/{gene}, the link from Gene                                                                    | trace                |
| `gate.spec.ts`           | Controls = /gate: headline, plates, Decision Cards from the controls, a check opens to its reason, axe                                   | gate                 |
| `walk.spec.ts`           | `E2E_WALK=1` only: fresh demo → design → curves → results equal the seeded walk's (moves the demo aside; reset after)                    | design, curves, home |
