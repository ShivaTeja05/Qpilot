# Contributing to qPilot

Thank you for helping. qPilot is research software whose numbers people may rely on, so the rules below are about keeping every number traceable and every conclusion-changing choice with a person.

## The layers, and what each may import

| Layer | Where | Rule |
|---|---|---|
| I/O | `qpilot/io/` | Reads files safely (hardened XML parser, size caps, pinned downloads). No model calls. |
| qPCR plugin | `qpilot/qpcr/` | All the qPCR maths. Deterministic; no model calls, no network. |
| Core | `qpilot/core/` | Domain-agnostic: the robustness grid, Decision Cards and the escalation rule, the study store, the record, confidence, facts and the "no naked numbers" validator. Never imports `qpilot.qpcr` at import time and never a model. |
| Model layer | `qpilot/ai/`, `qpilot/harness/` | Optional. Explains and answers using `{{fact_id}}` tokens only; validated before anything is shown. |
| Front ends | `qpilot/app.py` (+ `app_state.py`, `explain/`), `qpilot/mcp_server.py`, `qpilot/cli/` | Wiring only. Views are pure, tested functions; every name and value shown is HTML-escaped. |

`tests/core/test_no_llm_in_engine.py` fails if importing any module of `qpilot.core` or `qpilot.qpcr` loads `qpilot.ai`, `anthropic` or `httpx`, or if `qpilot.core` loads `qpilot.qpcr` at import time. The data contract between layers is `qpilot/schemas.py`; change it only with both maintainers' agreement.

## Standing checks

Run these before every commit (the pre-commit hooks run the first two, plus a secrets scan):

```bash
ruff format . && ruff check .
```

```bash
pytest -q
```

CI runs lint, the unit tests (`pytest -m "not demo_data"`) and `pip-audit`. Tests marked `demo_data` need the cached demo study (`qpilot fetch-demo`) and run locally. Two rules for numbers:

- **Never type a number into prose, a template, the UI or a slide.** Numbers come from facts (`StudyResult.facts`) or generated files (`validation/validation.json`), rendered with their own format. Tests check that `README.md` and `docs/engine.md` quote the validation lines generated from `validation/validation.json`; the method cards still contain hand-copied demo numbers that no test checks yet.
- **If the engine disagrees with an expected number, report both.** Do not change a tolerance to make a test pass.

## Commits and branches

[Conventional Commits](https://www.conventionalcommits.org): `feat(qpcr): …`, `fix(app): …`, `test: …`, `docs: …`. One branch per change, rebased on `main`; `main` moves only by fast-forward after CI passes. Code owners are in `CODEOWNERS`.

## How to add…

**An input format (a connector).** A connector is a function `path -> rdml.Rdml`; see [`qpilot/io/README.md`](qpilot/io/README.md). `CONNECTORS` in `qpilot/io/rdml_io.py` lists them by suffix, but nothing dispatches on it yet: route `qpilot/qpcr/curves.py::analyse_study` through it, add the suffix to `RDML_SUFFIXES` in `qpilot/mcp_server.py` and to the app's upload `file_types`, and apply size caps and safe parsing inside the connector (the hardened `load()` covers RDML/XML only). Add a small fixture under `tests/fixtures/` (with its licence in `THIRD_PARTY_NOTICES.md`) and a test that it loads.

**A new domain (another assay).** Implement `qpilot.schemas.DecisionSpace` (`dimensions`, `primary`, `items`, `evaluate(cell)`, `conclude(result)`), as `qpilot/qpcr/space.py` does for qPCR; the core builds the robustness grid from it. For Decision Cards, also pass a list of `qpilot.core.decisions.CardSpec` to `build_cards`, as `qpilot/qpcr/study.py` does. Card kinds are currently the three qPCR kinds in `qpilot/schemas.py`, so a new domain needs a schema change, and `qpilot rerun` calls the qPCR `run_study`. Register your facts with `qpilot.core.facts.FactRegistry` so explanations can cite them.

**A model backend.** Add a class with `name`, `model` and `complete(system, messages, max_tokens, temperature) -> str` in `qpilot/ai/client.py`; add its provider to `Provider` and the `from_env` check in `qpilot/ai/config.py`, select it in `make_backend`, and add it to `PROVIDERS` in `qpilot/app.py` if the app should offer it. It must raise `ModelUnavailable` on any failure so the template answer is used, and its output still goes through the validator. Test it with `MockBackend`-style fakes; tests never call a real model or the network.

## Data and licences

Never commit the demo dataset or any `.rdml` outside `tests/fixtures/`. Do not import or copy GPL/EUPL code (for example `qslib`, `qpcR`) or NormFinder's original code. The vendored rdmlpython in `qpilot/vendor/` is never edited; a test checks its hashes.

## Reporting a vulnerability

See [`SECURITY.md`](SECURITY.md). Please do not open a public issue for it.
