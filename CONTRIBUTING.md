# Contributing to qPilot

Thank you for helping. qPilot is research software whose numbers people may rely on, so the rules below are about keeping every number traceable and every conclusion-changing choice with a person.

## The layers, and what each may import

| Layer | Where | Rule |
|---|---|---|
| I/O | `qpilot/io/` | Reads files safely (hardened XML parser, size caps, pinned downloads). No model calls. |
| qPCR plugin | `qpilot/qpcr/` | All the qPCR maths. Deterministic; no model calls, no network. |
| Core | `qpilot/core/` | Domain-agnostic: the robustness grid, Decision Cards and the escalation rule, the study store, the record, confidence, facts and the "no naked numbers" validator. Never imports `qpilot.qpcr` at import time and never a model. |
| Model layer | `qpilot/ai/`, `qpilot/harness/` | Optional. Explains and answers using `{{fact_id}}` tokens only; validated before anything is shown. |
| Front ends | `qpilot/web/` (the one server: the API, live events, the guard), `frontend/` (the one page), `qpilot/mcp_server.py`, `qpilot/cli/` | Wiring only: no analysis here, only calls to the layers above. The API returns JSON, never HTML; the page shows every string as text (React escapes it, and the build fails on `dangerouslySetInnerHTML` or `innerHTML`). Views in `qpilot/web/` are pure, tested functions. |

`tests/core/test_no_llm_in_engine.py` fails if importing any module of `qpilot.core` or `qpilot.qpcr` loads `qpilot.ai`, `anthropic` or `httpx`, or if `qpilot.core` loads `qpilot.qpcr` at import time. The data contract between layers is `qpilot/schemas.py`; change it only with both maintainers' agreement.

## Standing checks

Run these before every commit (the pre-commit hooks run the first two, plus a secrets scan):

```bash
ruff format . && ruff check .
```

```bash
pytest -q
```

If you touched `frontend/`, also run the page's four checks (next section). CI runs lint, the unit tests (`pytest -m "not demo_data"`), `pip-audit`, and the page's checks and build. Tests marked `demo_data` need the cached demo study (`qpilot fetch-demo`) and run locally. Two rules for numbers:

- **Never type a number into prose, a template, the UI or a slide.** Numbers come from facts (`StudyResult.facts`) or generated files (`validation/validation.json`), rendered with their own format. Tests check that `README.md` and `docs/engine.md` quote the validation lines generated from `validation/validation.json`; the method cards still contain hand-copied demo numbers that no test checks yet.
- **If the engine disagrees with an expected number, report both.** Do not change a tolerance to make a test pass.

## Working on the page (`frontend/`)

The page is React, TypeScript, Vite and Tailwind CSS in `frontend/`; `npm run build` writes it into `qpilot/web/static/`, which the server (`qpilot app`) serves, so using qPilot never needs Node. You need Node 22 or newer only to change the page. Where things are: `src/ui/` the components every section shares, `src/charts/` the science charts, `src/lib/` number formats and the plain words, `src/api/` the typed client, `src/features/<section>/` one folder per section of the page. The page's rules (what it shows, never mocked data, design system) are in [`docs/app.md`](docs/app.md); read its principles first.

```bash
(cd frontend && npm ci)                                  # once, and after the lockfile changes
scripts/serve-dev.sh                                     # terminal 1: qpilot app on :7860 with the development key
cd frontend && QPILOT_APP_TOKEN=qpilot-dev npm run dev   # terminal 2: the page on http://127.0.0.1:5173
```

`scripts/serve-dev.sh` runs `.venv/bin/qpilot` (create the virtual environment in the repository root, as in the README), fixes the launch key to `qpilot-dev` and keeps its studies apart in `~/.cache/qpilot/dev-studies`. `npm run dev` forwards `/api` to it and adds the same key to each forwarded request, so the development page needs no cookie. Never use a fixed key on a shared computer (see [`THREAT_MODEL.md`](THREAT_MODEL.md), row 24). `QPILOT_API` (default `http://127.0.0.1:7860`), `QPILOT_APP_TOKEN` and `VITE_PORT` (default 5173) override the defaults. Sections load real data from your own study store: fetch the demo (`qpilot fetch-demo`, or **Download** on the page) and open it, rather than typing numbers into a component.

Before every commit that touches `frontend/` or the API's contract (all four must pass):

```bash
npm run typecheck && npm run lint && npm test && npm run build
```

* **The API's types are generated.** Response models live in `qpilot/web/contract*.py`. After you change one, run `npm run gen:api` (it writes `frontend/src/api/schema.d.ts` from the server's OpenAPI schema, without starting a server) and commit both files together; `npm run check:api` fails when they differ, and CI runs it. Keep contract changes additive.
* **A new API route** is a module in `qpilot/web/routers/` that defines `router` (routers are discovered, there is no list to edit). Writes record the actor `human` (the server sets it; a request cannot choose), results of a Studio session stay blind until the design and the curves are confirmed (the server refuses, the page does not merely hide), and every route has a test in `tests/web/`. Slow work is a job (`202`, followed on the event stream), not a long request.
* **Tests use real data, never made-up numbers.** Component tests may use JSON recorded from your store's own API, kept in `frontend/src/test/recorded/` with the command that produced it (`frontend/src/test/recorded/record.py`). Do not write numbers, gene names or sample names into a component or a fixture to make a screen look finished.
* **What is committed:** `frontend/package.json` and `package-lock.json`, `frontend/src/`, and the built page in `qpilot/web/static/` (CI runs `npm run build` and fails if `git diff` then shows a difference, so the committed page is always what the source produces). `node_modules` is not committed. When `package-lock.json` changes, regenerate the npm part of [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) (the generator is in that file); a GPL-family licence in the page's production packages is a blocker.
* **Lint rules that protect the principles:** no `dangerouslySetInnerHTML`, no `innerHTML`, no external URL in the page's code (it makes no outbound request; the CSP would refuse it anyway).

## Commits and branches

[Conventional Commits](https://www.conventionalcommits.org): `feat(qpcr): …`, `fix(app): …`, `test: …`, `docs: …`. One branch per change, rebased on `main`; `main` moves only by fast-forward after CI passes. Code owners are in `CODEOWNERS`.

## How to add…

**An input format (a connector).** A connector is a function `path -> rdml.Rdml`; see [`qpilot/io/README.md`](qpilot/io/README.md). `CONNECTORS` in `qpilot/io/rdml_io.py` lists them by suffix, but nothing dispatches on it yet: route `qpilot/qpcr/curves.py::analyse_study` through it, add the suffix to `RDML_SUFFIXES` in `qpilot/mcp_server.py` and to `INPUT_SUFFIXES` in `qpilot/web/views.py` (what the page accepts as an upload), and apply size caps and safe parsing inside the connector (the hardened `load()` covers RDML/XML only). Add a small fixture under `tests/fixtures/` (with its licence in `THIRD_PARTY_NOTICES.md`) and a test that it loads.

**A new domain (another assay).** Implement `qpilot.schemas.DecisionSpace` (`dimensions`, `primary`, `items`, `evaluate(cell)`, `conclude(result)`), as `qpilot/qpcr/space.py` does for qPCR; the core builds the robustness grid from it. For Decision Cards, also pass a list of `qpilot.core.decisions.CardSpec` to `build_cards`, as `qpilot/qpcr/study.py` does. Card kinds are currently the three qPCR kinds in `qpilot/schemas.py`, so a new domain needs a schema change, and `qpilot rerun` calls the qPCR `run_study`. Register your facts with `qpilot.core.facts.FactRegistry` so explanations can cite them.

**A model backend.** Add a class with `name`, `model` and `complete(system, messages, max_tokens, temperature) -> str` in `qpilot/ai/client.py`; add its provider to `Provider` and the `from_env` check in `qpilot/ai/config.py`, and select it in `make_backend`. The provider, endpoint and key come from the environment (`QPILOT_MODEL_PROVIDER` and the variables in `qpilot/ai/config.py`); the page has no setting for them, by design (see [`THREAT_MODEL.md`](THREAT_MODEL.md), row 14). It must raise `ModelUnavailable` on any failure so the template answer is used, and its output still goes through the validator. Test it with `MockBackend`-style fakes; tests never call a real model or the network.

## Data and licences

Never commit the demo dataset or any `.rdml` outside `tests/fixtures/`. Do not import or copy GPL/EUPL code (for example `qslib`, `qpcR`) or NormFinder's original code. The vendored rdmlpython in `qpilot/vendor/` is never edited; a test checks its hashes.

## Reporting a vulnerability

See [`SECURITY.md`](SECURITY.md). Please do not open a public issue for it.
