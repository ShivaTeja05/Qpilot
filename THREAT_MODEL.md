# qPilot threat model (one page)

qPilot is local research software. It reads a qPCR export (RDML), analyses it deterministically, shows the scientist the choices that can change a conclusion, records their decisions, and offers the same functions to AI agents over MCP (stdio). It is **not** for clinical or diagnostic use and is **not** a multi-user service.

## Assets
| Asset | Why it matters |
|---|---|
| Raw curves and sample/target names in the input file | May be unpublished or patient-derived |
| The decision log (`decisions.jsonl`) and the Analysis Record | The evidence of who chose what and why |
| The numbers (`results.json`, `facts.json`) | What a paper or a reviewer relies on |
| An API key for a frontier model (if used) | Spending and account access |
| The user's filesystem | An agent must not be able to read arbitrary files through qPilot |

## Trust boundaries
```
RDML file (untrusted) ─▶ io (hardened loader) ─▶ engine (qpcr + core, no network, no model)
                                                      │
                                                      ▼
                                        core/store.py: the only writer to a workspace
                                       ┌──────────────┼───────────────────────────┐
                                       ▼              ▼                           ▼
                         Gradio app on 127.0.0.1   MCP server (stdio)       ai/ → model endpoint
                         (the scientist)           (any agent; untrusted)    (only if chosen)
```
**Untrusted inputs:** RDML content (including names inside it), every MCP tool argument, every model output, a record zip received from someone else.

## Threats and controls
| # | Threat | Control | Backed by |
|---|---|---|---|
| 1 | XXE / external entities in RDML | lxml parser with entity resolution and network access off, on every load (Dev 1, `io/rdml_io.py`) | `tests/engine/test_rdml_io.py` (XXE fixture) |
| 2 | Zip bomb or huge input | Size cap and compression-ratio cap on load; record zips capped at 1 GB and 10,000 members | `tests/engine/test_rdml_io.py`, `tests/core/test_record.py` |
| 3 | Path traversal through the agent's `rdml_path` | `resolve(strict=True)` then `is_relative_to(QPILOT_DATA_ROOTS)`; `.rdml`/`.xml` only; no string-prefix checks | `tests/core/test_mcp_server.py` (sibling prefix, symlink out, `..`, missing, non-RDML) |
| 4 | Path traversal through a study id or a record zip | Study ids must be hex; zip members with absolute paths, `..`, backslashes or symlinks are refused | `tests/core/test_store.py`, `tests/core/test_record.py` |
| 5 | An agent makes a conclusion-changing decision | Rule in code (`core/decisions.py`, repeated inside the store): a non-human on a card that can flip a conclusion **at any setting of the other choices** (`impact.flips_anywhere`) gets `pending_human`; over MCP, agents only ask until the scientist sets the study to *decide and tell* (`StudyStore.set_autonomy`, default `suggest`); over MCP the actor is always `agent` and `actor="human"` is refused; people decide only in the app (127.0.0.1); the command line has no decide command. **Limit:** an agent that can run commands as the user (import the library, or drive the local app) can act as the user. The gate binds MCP-only agents and the in-app model. | `tests/core/test_decisions.py`, `tests/core/test_mcp_server.py`, `tests/core/test_brief_p1.py` |
| 6 | Lost or forked decisions when the app and an agent write at once; an agent that keeps writing to block a person | File lock around every append; `expected_head` version check returns `stale` and is logged outside the chain. A write is stale only when its own card changed or a person (or the system) decided elsewhere; an agent's requests on other cards never block a person | `tests/core/test_store_concurrent.py` (two processes), `tests/core/test_brief_p1.py` |
| 7 | A model invents numbers, or reports a refused change as done | Model sees only facts (no raw curves, no sample names); every data number must be a `{{fact_id}}` token (digits anywhere, and spelled-out amounts such as "seven-fold"); method constants pass only in their method wording ("95 % confidence interval", "p < 0.05", "at least 2-fold"), so a bare "2x" or "95%" is rejected; one retry, then the template. A refused or stale change is always reported in qPilot's own fixed words. Change requests in the tested wordings, direct and indirect ("make HMBS the reference gene", "from now on normalise to HMBS"), are routed to the gate, and an answer that claims a change in a recognised wording is replaced. **Limit:** recognising wording is best effort; the guarantee is the gate itself: no choice that can change a conclusion is applied without a person, whatever the model writes | `tests/ai/test_ai.py`, `tests/ai/test_harness.py`, `tests/ai/test_safety_regressions.py` |
| 8 | Prompt injection or XSS through names in the RDML or reasons | Reasons capped at 500 characters; few-shot examples only from human decisions; names validated at load and HTML-escaped in the app (Dev 1) | `tests/core/test_decisions.py`, `tests/ai/test_ai.py`; app, end to end (reasons, labels from the RDML and model text are escaped): `tests/app/test_app.py` (`test_a_hostile_label_from_an_rdml_file_is_shown_as_text`, `test_model_text_with_markup_is_escaped`) |
| 9 | Data leaves the machine | Provider `none` by default; the headless path runs with sockets disabled; model calls log hashes and sizes, never the key, raw payload only with `QPILOT_LOG_PAYLOAD=1`; app binds `127.0.0.1` with telemetry forced off (Dev 1) | `tests/core/test_offline.py`, `tests/ai/test_ai.py`; app: `tests/app/test_app.py` (`test_launch_options_are_local_only`, `test_telemetry_is_forced_off_even_when_the_environment_turns_it_on`, `test_main_launches_with_every_hardening_option`) |
| 10 | Tampered record | `CHECKSUMS.sha256` over every file, a hash chain over decisions, and a replay of the chain that `cards.json`, `choices.json` and `pending.jsonl` must match (both required when anything is waiting); every chain line must be the exact canonical form of the entry it hashes; `record.json` must name the chain's last entry and the study; `input.rdml`, when present or declared, must be the study's input; `qpilot verify` names the changed file, the first broken link, or the disagreeing card. The store rebuilds `cards.json` and `pending.jsonl` from the log on every write, so an interrupted write never turns into a false tamper report. **Tamper-evident, not tamper-proof:** nothing is signed, so someone who rewrites the whole chain and all checksums consistently can still pass `verify`. Resealing the checksums alone also lets someone change files outside the chain (`results.json`, `facts.json`, `grid.csv`, card impacts) or delete a card nobody decided. `qpilot rerun` regenerates and compares all of these, but only for records exported with their input. Signatures are roadmap. | `tests/core/test_record.py`, `tests/core/test_record_hardening.py` |
| 11 | Unsafe deserialisation | JSON and `yaml.safe_load` only; no pickle anywhere | code review |
| 12 | Supply chain and secrets | Pinned lower bounds (`lxml>=6.1.3`, `mcp>=1.23.0`), Dependabot, `pip-audit` in CI, gitleaks pre-commit | `.github/workflows/ci.yml`, `.pre-commit-config.yaml` |
| 13 | A web page in the browser uses DNS rebinding to drive the local app | The app accepts only `127.0.0.1` / `localhost` as Host and refuses to serve files from the study store (Dev 1) | `tests/app/test_app.py` (`test_foreign_hosts_and_store_files_are_refused`) |
| 14 | The API key reaches an endpoint typed into the page | The key is sent only with the provider and endpoint it was configured for in the environment (Dev 1) | `tests/app/test_app.py` (`test_the_api_key_only_goes_where_it_was_configured`) |
| 15 | An agent or model sends planner arguments that exhaust memory or crash the server (a fold change near 1, an infinite or huge SD) | Inputs must be finite and plausible (fold change within 1/1000 to 1000, SD of log2 at most 10, 2 or more per group); the simulation draws group means and variances, so its memory does not grow with the sample size; errors come back as JSON | `tests/core/test_plan.py`, `tests/ai/test_safety_regressions.py` |

## Out of scope
A compromised host or Python environment; a malicious lab profile written by the user themself; proving who authored a record (signatures are roadmap); multi-user hosting, accounts and roles; 21 CFR Part 11; clinical or diagnostic use.
