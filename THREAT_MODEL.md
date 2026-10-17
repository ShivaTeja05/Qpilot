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
| 5 | An agent makes a conclusion-changing decision | Rule in code (`core/decisions.py`, repeated inside the store): a non-human on a flipping card gets `pending_human`; over MCP the actor is always `agent` and `actor="human"` is refused | `tests/core/test_decisions.py`, `tests/core/test_mcp_server.py` |
| 6 | Lost or forked decisions when the app and an agent write at once | File lock around every append; `expected_head` version check returns `stale` and is logged | `tests/core/test_store_concurrent.py` (two processes) |
| 7 | A model invents numbers, or reports a refused change as done | Model sees only facts (no raw curves, no sample names); every number must be a `{{fact_id}}` token; one retry, then the template; an answer that does not report `pending_human` is replaced | `tests/ai/test_ai.py`, `tests/ai/test_harness.py` |
| 8 | Prompt injection or XSS through names in the RDML or reasons | Reasons capped at 500 characters; few-shot examples only from human decisions; names validated at load and HTML-escaped in the app (Dev 1) | `tests/core/test_decisions.py`, `tests/ai/test_ai.py`; app: `tests/app/` |
| 9 | Data leaves the machine | Provider `none` by default; the headless path runs with sockets disabled; model calls log hashes and sizes, never the key, raw payload only with `QPILOT_LOG_PAYLOAD=1`; app binds `127.0.0.1` with telemetry off (Dev 1) | `tests/core/test_offline.py`, `tests/ai/test_ai.py` |
| 10 | Tampered record | `CHECKSUMS.sha256` over every file and a hash chain over decisions; `qpilot verify` names the changed file and the first broken link. **Tamper-evident, not tamper-proof.** | `tests/core/test_record.py` |
| 11 | Unsafe deserialisation | JSON and `yaml.safe_load` only; no pickle anywhere | code review |
| 12 | Supply chain and secrets | Pinned lower bounds (`lxml>=6.1.3`, `mcp>=1.23.0`), Dependabot, `pip-audit` in CI, gitleaks pre-commit | `.github/workflows/ci.yml`, `.pre-commit-config.yaml` |

## Out of scope
A compromised host or Python environment; a malicious lab profile written by the user themself; proving who authored a record (signatures are roadmap); multi-user hosting, accounts and roles; 21 CFR Part 11; clinical or diagnostic use.
