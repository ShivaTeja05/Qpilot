# Security review, October 2026 (excellence round)

An adversarial review of everything added to qPilot between `2b7ee46` and `5171854` (162 commits:
the design editor, exports and the supplement, melt, units, references, quantities, Where to look
decisions, the agents' new MCP tools, the `.pzfx` Prism round trip, the answer cache and background
preparation, the public sandbox, CI and the release workflow). It was done on branch `ex/redteam`
on 28 Oct 2026. Each finding was first shown by a failing test, then fixed, and the test now
passes and keeps it fixed. The controls themselves are in [`THREAT_MODEL.md`](../THREAT_MODEL.md)
(rows 2, 3, 12, 29, 37, 44 updated; rows 45 to 47 new); this page is the review's table.

Severity is for qPilot's two settings: a person's own computer (`qpilot app` on 127.0.0.1 with a
launch key; MCP agents bound by the data roots) and the public sandbox (`QPILOT_HOSTED=1`: no key,
shared by every visitor, no private data). "Hosted" marks findings that matter only there.

## Findings

| Id | Severity | Where | Finding | Status | Test |
|---|---|---|---|---|---|
| RT-EX-001 | none | `qpcr/repeat.py`, `qpcr/layout.py` | Checked: the repeat plate CSV writes sample, group and target names without an apostrophe, but its layout rule refuses every name that starts with `-` (and the engine's name rule leaves no `=`, `+`, `@`), so no formula can reach it. A minus-first sample ("-RT") is listed and not laid out, said in words | holds | `tests/web/test_redteam_exports.py::test_the_repeat_plate_never_writes_a_live_cell` |
| RT-EX-002 | low | `cli/quant_cmds.py` | `qpilot quantify --csv` wrote unit, assay, sample and curve names as they were: a minus-first name (`-KO(2)`, which the name rule keeps) opened as a formula | fixed `0348d37` | `tests/web/test_redteam_exports.py::test_the_cli_quantities_csv_is_defused` |
| RT-EX-003 | low | `web/routers/report.py` | A group name the exports refuse (any character outside `_ - . ( )`, letters, digits, spaces) made `GET …/report/figure` and `…/figure/info` a 500, and the error quoted the name; now 409 `no_figure` in qPilot's words (since `2b93656` the exports refuse only a name with a tab, a line break or an invisible character) | fixed `0348d37` | `…::test_a_group_the_exports_cannot_name_is_said_in_words_not_a_500` |
| RT-EX-004 | medium, hosted | `web/routers/files.py` (round trip), `web/folders.py` | The Prism round trip read a folder (or `.pzfx`) anywhere in the server's home folder: on the Space, the app's own code. Hosted, only qPilot's export folder; visitors upload the saved project | fixed `2fade61` | `tests/web/test_redteam_hosted.py::test_a_hosted_round_trip_never_reads_the_servers_home_folder` |
| RT-EX-005 | low | `web/folders.py` | The folder rule looked a path up on disk before checking the roots, so "There is no folder /x" against "must be inside your home folder" told whether any path on the server exists | fixed `2fade61` | `…::test_a_path_outside_the_roots_gets_one_answer_whether_it_exists_or_not` |
| RT-EX-006 | medium, hosted | `io/rdml_io.py`, `io/connectors/tables.py`, `deploy/hf-space/app.py` | A 10 MB zipped RDML may hold 1 GiB of XML (ratio 100:1), and loading takes about 20 times the XML in memory (measured: the demo's 60 MB of XML, 1.35 GB peak): one upload could take the sandbox down. `QPILOT_MAX_UNPACKED_MB` lowers the cap (RDML zipped or plain, workbooks); the Space sets 128 MB | fixed `2fade61` | `…::test_a_hosted_server_refuses_xml_over_its_cap_before_parsing`, `…_a_workbook_over_its_cap`, `…::test_the_space_sets_the_hosted_caps` |
| RT-EX-007 | medium, hosted | `web/security.py` (`Guard`, `Hosting`) | Uploads, exports and records are kept until restart, with nothing between a visitor and a full disk (the store's writes then fail for everyone). A hosted server now answers every write 507 `sandbox_full` in words while the store's disk has less than `QPILOT_MIN_FREE_MB` (1024) free; reads go on; a local server never checks | fixed `2fade61` (no per-visitor quota: RT-EX-015) | `…::test_hosted_writes_wait_for_disk_space`, `…::test_an_upload_to_a_full_sandbox_is_refused_before_it_is_read`, `…::test_a_local_server_never_checks_the_disk` |
| RT-EX-008 | low | `agents/capabilities.py` (`qpcr_export`), `report/excel.py` | `out_dir` was checked for the file's name, then the export was written (up to a minute), then copied with `os.replace`, which overwrites: a file a person saved there meanwhile, or a link, was replaced. The copy is now linked into place (`write_new`: fails when the name exists; an exclusive create without hard links) | fixed `717ff1f` | `tests/mcp/test_redteam_export_copy.py` |
| RT-EX-009 | medium | `.github/workflows/release.yml` | The release's build job ran `npm ci` (every dependency's install script) and then `python -m build` in the same workspace: a compromised npm package could change `qpilot/` before the wheel that PyPI publishes was built. The page check is now its own job; the build job runs no npm; release checkouts set `persist-credentials: false` | fixed `228c7c7` | `tests/redteam/test_workflows.py` |
| RT-EX-010 | low (medium hosted) | `web/routers/{design,workspaces,instruments,gate}.py` | The async upload routes read the kept file on the event loop: a sample sheet (up to 200 MB of workbook XML), a Cq table's sample columns, an export set's content sort, a run file (up to 200 MB). Every other request and the event stream stopped meanwhile. Each read now runs in a worker thread | fixed `2a1842e` | `tests/web/test_redteam_loop.py` |
| RT-EX-011 | low | `mcp_server.py` (`_resolve`) | "file not found" for a missing path and "path outside QPILOT_DATA_ROOTS" for an existing one: an MCP-only agent could map the disk. "not found" is now said only inside a root | fixed `fadd191` | `tests/redteam/test_mcp_paths.py::test_a_path_outside_the_roots_gets_one_answer_whether_it_exists_or_not` |
| RT-EX-012 | low | `web/contract_absolute.py`, `web/contract_design.py`, `features/results/quantities/api.ts` | `POST …/quantities/reaction` and `POST …/design/set` skip the stale check when `expected_head` is missing (RT-UI-014's rule for page writes), and the page sends none for the reaction input: two tabs, the later one wins unseen (per-µL and per-ng quantities only, no conclusion) | fixed `3f2b641`: `expected_head` is required on both (422 without it, 409 `stale` in words); the quantities view carries `inbox_head` and the page sends it | `tests/web/test_absolute_routes.py::test_the_reaction_input_needs_the_head_the_page_showed`, `tests/web/test_design_editor.py::test_design_set_needs_the_head_the_page_showed` |
| RT-EX-013 | low | `.github/workflows/*.yml` | Actions are pinned by tag (`actions/checkout@v7`, `pypa/gh-action-pypi-publish@release/v1`), not by commit; a moved tag of a compromised action runs in the publishing job, which holds the OIDC token. Mitigated by the `pypi` environment (required reviewer, `v*` tags only: `docs/release.md`) | fixed `cbe6e8b`: every `uses:` is `owner/repo@<commit SHA> # vX.Y.Z` (the commit each tag pointed at; Dependabot's github-actions updates move both) | `tests/redteam/test_workflows.py::test_every_action_is_pinned_by_commit_with_its_release` |
| RT-EX-014 | info | `core/store.py` (`grid.csv`), `web/intake.py` (a Cq table's sample columns), `prism/tables.py`, the audit's CSVs (`qsim`) | These CSVs carry names as they are, because qPilot, the Simulator's tools (the audit's files are hashed in `AUDIT.sha256`) or Prism read them back by name; defusing would change the names. Only minus-first, argument-poor formulas can reach them (the engine's name rule) | accepted | THREAT_MODEL row 46 |
| RT-EX-015 | low, hosted | `web/ratelimit.py`, `web/jobs.py`, `web/server.py`, `deploy/hf-space/app.py` | No rate limit per visitor: one visitor could keep the job workers busy (a supplement is about 50 s on the demo), flood the sandbox with uploads or take its event streams, until it restarts. A shared, reset-on-restart demo by design | fixed `e353be7`: a hosted server limits each visitor with token buckets (reads 240 a minute, writes 20 a minute, uploads 6 in 10 minutes), 3 slow jobs at once (8 in all; refused before the route runs and again when the job is made) and 6 event streams, plus sandbox-wide buckets as a backstop; answered `429 rate_limited` with `Retry-After` in words. A visitor is the socket peer unless the peer is in `QPILOT_TRUSTED_PROXIES`, then the `X-Forwarded-For` entry `QPILOT_PROXY_HOPS` names (the Space: Vercel's overwritten header, leftmost). A forwarded address from any other peer is ignored. Local mode, the page, its assets and `/api/system` are never limited. **Residual:** a visitor who bypasses the Vercel front door and spoofs the header gets a new allowance per address; the sandbox-wide buckets, the job cap, the upload and unpacked-size caps and the disk floor still bound them (`docs/sandbox.md`) | `tests/web/test_ratelimit.py` |

Not a security finding, reported to the owners and fixed (`2b93656`): an export refused a study
whose group name had a character outside letters, digits, spaces and `_ - . ( )`, so a group a lab
names "LPS + inhibitor" got no workbook, CSV, figures or supplement at all. A name may now hold any
letters, digits, spaces and signs (`qpilot/core/names.py`; refused only when empty, longer than 64
characters, with an edge space, a tab, a line break or an invisible character); it is escaped or
defused where it is written, and file names are derived separately (the name itself when it is a
plain ASCII file name, else an ASCII slug and a short hash). `tests/web/test_unicode_names.py`.

## Checked and holding

* **XML.** Every parse of file text uses a parser with entity resolution, DTD loading and network
  access off and `huge_tree` off: `io/rdml_io.hardened_parser` (RDML, the schema, `rdml_out`,
  run files), `prism/pzfx._parser` (which also refuses any `<!DOCTYPE`/`<!ENTITY` before parsing),
  and the `iterparse` readers (`report/rdml_meta.py`, `qpcr/instrument_context.py`). Tried on each:
  an external general entity, an external parameter entity, an external DTD, XInclude and a
  billion-laughs expansion: nothing is read and the expansion is refused by libxml2. openpyxl
  reads workbooks through defusedxml.
* **Archives.** The RDML member chosen "whatever its name" is read into memory and never written
  out, so `..`, absolute names, links and nested zips name no path; its declared size and ratio
  are checked before a byte is inflated, and the read stops at the declared size. `.lc96p` files
  take the same path. A partitions member (digital PCR) is never read by qPilot's code paths.
* **Exports.** No workbook cell is ever a formula (text is a string cell); every person-facing CSV
  defuses `= + - @`, tab and carriage return; SVG figures escape every text and carry no element
  or handler a name brought in; figure files are served with the page's CSP and a
  `filename` made of `[\w().-]`; the HTML reports escape every name. Walked end to end with a
  minus-first sample, target and group (`tests/web/test_redteam_exports.py`).
* **New routes.** Every `/api` route needs the launch key (the guard runs before any route), every
  write is same-origin, JSON bodies are capped at 1 MB and uploads at 200 MB (25 MB hosted);
  the blind sweeps (`tests/web/test_redteam_blind.py`) enumerate the OpenAPI schema and cover
  every new study and session route (melt, units, references, quantities, Where to look,
  exports, Prism project and upload, design editor) with valid bodies; no route answered a
  result for a re-blinded session. The design editor's template is an attachment with
  `nosniff`, its names defused.
* **MCP.** `qpcr_export` writes only into the study's export folder and, when asked, a copy under
  a name qPilot chooses inside the data roots, never inside the store, never over a file (now
  race-free); `qpcr_request_set_aside` files the agent's own proposals and decides nothing; the
  new read tools answer `results_hidden` until a person confirmed design and curves
  (`tests/mcp/test_capabilities.py`).
* **Cache.** An ETag is the hash of the bytes the route just produced, so an old tag is no way
  past a blind gate, no oracle without the key, and not honoured by another view; `Prefer:
  respond-async` softens only `loading` and `warming` (`tests/web/test_redteam_cache.py`). The
  in-process `Memo` is not used by any view. Background preparation reads through the guard,
  writes nothing and never queues a person's job.
* **CI.** No `pull_request_target`, no event text spliced into a script, read-only by default,
  `contents: write` only for the GitHub Release job, `id-token: write` only for the publishers
  behind an environment, PyPI only from a `v*` tag, switched off by `PYPI_PUBLISH` = `false`
  (`tests/redteam/test_workflows.py`).

## For the public sandbox

The Space (`deploy/hf-space/app.py`) now sets `QPILOT_MAX_UNPACKED_MB=128` and
`QPILOT_MIN_FREE_MB=1024` beside the 25 MB upload cap. If the Vercel proxy forwards writes,
`QPILOT_ALLOWED_ORIGINS` must name its origin (the guard refuses other sites' writes, hosted or
not). It also sets the limit per visitor that closes RT-EX-015 (reads, writes, uploads, running
jobs, live streams; Vercel's `X-Forwarded-For` is believed from the platform's proxy) and starts
uvicorn with `proxy_headers=False`; `docs/sandbox.md` says what each setting does and where the
limit stops.
