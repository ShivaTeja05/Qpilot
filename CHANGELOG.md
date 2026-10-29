# Changelog

All notable changes to qPilot are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). qPilot is research software:
research use only, not for clinical decisions.

## [Unreleased]

## [0.2.0] — 2026-10-28

From the demo study to a lab's own files: qPilot now opens the files labs actually publish
(multiplex plates and Cq tables included), lets a person finish the design on the page without a
model, compares several groups, quantifies against standards (or only quantifies, with no groups
at all), reads melt curves, plans the repeat, and writes the numbers, figures and a Prism project
a paper needs. The rule is unchanged: the software never makes a choice that can
change a conclusion; a person does, with a reason, in the hash-chained record.

On the demo study every design hash, study id and the locked demo output are unchanged, except
where a feature adds to them on purpose: the Run Gate pack is now `research-default` 1.4.0 (one
G-MELT and one G-IPC "not applicable" line; 1.4.0's rule changes give the demo the same verdicts), MIQE 5.19 reads the melt rule's sentence, MIQE 5.14 is answered
from the standard curves, and the exports gain the Standard curves and Quantities tables and a
Methods paragraph on them.

### Added
- **The science review's offered options** (29 Oct 2026, [`docs/science-review-2026-10.md`](docs/science-review-2026-10.md)):
  the amplification rule **"LinRegPCR's call, its 'no amplification' respected"**
  (`linregpcr_call`; offered by the curves stage when a file has such wells, with how many; the
  demo has 11 and no call changes); **standards that look wrong** (the series' order broken, or
  a studentized residual beyond ±3.5) listed under their curve with the curve without them, and
  **Propose leaving these out** files one `curve.exclude_well` per well for a person to decide
  (`POST /api/studies/{id}/quantities/standards`); **Fisher's exact test** on the detection counts
  of a gene detected in one group only (orientation, never a call); the LOD's words say how many
  wells per level stand behind it (ten replicates around the limit recommended); NormFinder's
  warning names the genes whose negative variance it counted as zero.

#### Getting files in
- **Real lab files open** (`qpilot/io/`, `qpilot/io/connectors/`): RDML archives whatever their
  member is called, RDML 1.0 (StepOne Software) and 1.1–1.2 slips the vendored upgrader leaves,
  LinRegPCR-written RDML 1.3, LightCycler 96 files with the samples' and targets' real names
  (from their RDML description), and a person's own Excel **Cq table** (Sample, Gene, Condition,
  Gene Type, Cq): its Gene Type column proposes the reference genes, its condition column becomes
  the sample sheet, and its numbers are never shown before the design and curves are confirmed.
  Every refusal of an RDML file says its own reason in words; reports and exports name a person's
  own files, never qPilot's hashed copy.
- **A table of Cq values, analysed without curves** (`qpilot/qpcr/cq_only.py`,
  `GET /api/sessions/{sid}/cq-table`, [`docs/cq-tables.md`](docs/cq-tables.md)): a Cq table
  (Excel or CSV) or an RDML file without amplification curves goes through the same Studio
  stages, engine and Analysis Record. Each well's N0 is E^−Cq, with E from the assay's dilution
  series when the plate has one, else assumed 2.0 (then the log2 fold change is exactly −ΔΔCq);
  the Curves stage shows **Your Cq table** to confirm instead of curves; what needs a curve
  (LinRegPCR's fit, the Curve Judge, Import Trust, melt, two efficiency models) is said not to
  apply; confidence is capped at Low while an efficiency is assumed, Moderate when every assay's
  comes from its series.
- **Multiplex plates** (`qpilot/qpcr/multiplex.py`, [`docs/multiplex.md`](docs/multiplex.md)): every
  dye of a well gets its own baseline, efficiency, Cq and N0. Before, the vendored LinRegPCR gave
  the reaction volume to the first curve of a well only, so every other dye's N0 was 0 and a
  duplex lost its reference gene to "undetermined" (on the corpus: LightCycler 96 X/Y/IPC 0 → 12,
  12, 14 curves with an N0; QuantStudio 7 Pro IPC 0 → 95; CFX 4-plex 0 → 96 per dye; 7500 nCoV
  0 → 21). A gene's relative quantity uses the reference measured in the same well, and leaving a
  multiplex well out leaves out all its curves. Plate maps show the dyes per well, with a target
  picker. Singleplex plates (the demo) are analysed exactly as before.
- **Instrument exports on Open** (`qpilot/io/connectors/`, `qpilot/web/intake.py`): drop a Bio-Rad
  CFX export set, a QuantStudio / StepOne / 7500 export, a LightCycler 480 raw-data text or Cp
  table, an RDES or a tidy table; qPilot sorts the files by content, reads them once into
  deterministic RDML and opens that as a Studio session. The Design section shows what was read
  (plates, wells, sample types, vendor Cq, omitted wells) and whether the curves look raw,
  baseline-subtracted or normalised (`qpilot/io/rawness.py`).
- **The Import Trust card** (`capture.import_trust`, `qpilot/io/trust.py`,
  `GET|POST /api/studies/{id}/import-trust[/decide]`): a Studio session opened from an export whose
  curves were most likely baseline-subtracted before export (or whose processing qPilot could not
  tell) is analysed from the curves as imported with every gene's confidence capped at Moderate
  until a person decides on Results: re-export the raw curves, analyse them as they are (capped at
  Moderate), or use the instrument's Cq values only (quantity 2^-Cq, capped at Low). The choice
  is a `curve.import_trust` proposal a person accepts with a reason; an agent's request waits for
  a person. Curves normalised to a passive reference (Rn) get no card. `StudyDesign.import_trust`
  carries it, so a record re-runs to the same grades.
- **Which files qPilot reads** ([`docs/conformance.md`](docs/conformance.md)), generated by
  `python scripts/conformance.py` over the public corpus: every real set with curves or Cq values
  opens (newly the CFX RDML with a non-standard member name, the 17-plate soybean Cq-only RDML,
  StepOne's RDML 1.0, LinRegPCR's 6-plate RDML and the hmuY Cq workbook); an isothermal plate
  read and two RDML files dropped together are refused in words.
- Public instrument-export corpus for tests (`tests/fixtures/corpus/`, 18 real sets with
  manifests and SHA-256, 2 synthetic sets with known truth) and red-team reader tests
  (`tests/redteam/`).

#### Design
- **Finish the design on the page, with no model** (`qpilot/studio_design.py`,
  `qpilot/web/routers/design.py`, [`docs/design-editor.md`](docs/design-editor.md)): set target
  roles (reference gene, gene of interest, leave out), sample groups, sample types, standards
  (top quantity and dilution step) and biological units by selecting samples or wells, or by
  pasting two columns from Excel; choose the comparison; download a sample sheet pre-filled with
  the plate's names, or attach one to the session. Each change is the person's own proposal,
  checked by the engine and recorded with the person's reason (`made_by.kind = "person"`, only a
  person can make one). Sample sheets may carry a target-role column (Gene Type, Reference,
  Housekeeping, …). A whole 96-well plate records in about a second.
- **What the study is for: compare groups or quantify samples** (`StudyDesign.purpose`,
  `design.purpose`, `qpilot/qpcr/quantify_study.py`): a run that compares nothing (a viral load,
  wastewater, a construct's copy number, a library) chooses **Quantify samples** on the Design
  page. It needs standards with quantities, not a comparison or a reference gene, and reaches
  Results with each sample's quantity and what is reported for it (quantified, below the LOQ or
  LOD, not detected, extrapolated). Two Decision Cards (which wells count as detected; how precise
  a quantity must be to be reported) wait for a person only when another option changes what is
  reported for a sample. Controls, the report, the exports, the record and MCP `qpcr_quantities`
  follow; Gene, Audit, Trace, Claims, Prism and Plan next, which compare groups, say why they are
  locked. Absent by default: every existing design hash is unchanged.
- **Several comparisons proposed by Studio**: with three or more groups the rules propose each
  group against a control (when a group's name says control) or every pair, Holm-corrected; a
  donor, animal or passage column proposes pairings (`design.pair`) for paired tests. A person
  accepts, edits or rejects the plan like any proposal.
- `ProposalStore.decide_together`: one click of a person that proposes and decides several
  proposals in one locked write, all or nothing (about 80 s → 1.1 s for 189 items).

#### Comparisons & statistics
- **Several comparisons per study** (`qpilot/qpcr/contrast.py`, `GET /api/studies/{id}/comparisons`,
  `?comparison=` on the results routes): each group against a control, every pair, or a list a
  person chooses. Each gene's p-values are corrected with Holm's method across its comparisons,
  and q-values (Benjamini–Hochberg) are shown across genes. Pair by donor, animal or passage for a
  paired t-test. With three or more groups Welch's one-way ANOVA is shown per gene, for
  orientation only (never a call). Results has a comparison picker and every gene across every
  comparison; Methods, MCP, the CLI and the Analysis Record follow (`grid_comparisons.csv`).
  Method card [`methods/comparisons.md`](methods/comparisons.md).
- **Several comparisons in every section**: a Decision Card counts a changed call in every
  comparison, so a choice that changes a call only in a later comparison waits for a person (it
  names the comparison and shows each option's effect per comparison; the choice applies to the
  whole study); an opt-in choice enters the grid when it matters in any comparison. Trace and
  Where to look (`?comparison=`, MCP `qpcr_trace(comparison=…)`), a gene's page
  (`/genes/{gene}/units?comparison=`; the figure draws every group with a bracket per
  comparison) and History follow the comparison picked, with the corrected p the call uses; the
  Run Review names each comparison. The robustness audit audits the first comparison and says
  so; it refuses, in words, a paired or pooled-variance comparison or one whose correction
  changes a call. Studies with one comparison are unchanged.
- **Dunnett's and Tukey's corrections** (`qpilot/qpcr/multiplicity.py`): a person's choice beside
  Holm and none: Dunnett for each group against a control, Tukey(–Kramer) for every pair, each a
  single-step adjusted p from a t-test with the spread pooled over the plan's groups (equal
  spread on the log2 scale assumed; unpaired designs only).
- **Several comparisons on the Design page**: Design → Comparison → **Several comparisons**: each
  group against a control, every pair of groups, or your own list, and the correction.
- **The robustness audit runs on designs with technical replicates** (`sim/`, `qpilot/integration/`):
  each biological unit's wells are combined as qPilot combines them (the mean of their log2
  amounts), so the audit reproduces qPilot at its baseline; with three or more wells per value it
  also varies how replicates are combined (a ninth decision, `replicates`: the median well, or
  leaving out one well outside the expected spread).
- **Gene → Your samples from the engine** (`GET /api/studies/{id}/genes/{gene}/units`): each
  biological unit's value relative to the second group's mean, its replicate wells as small dots
  on its line, each group's mean with its 95 % CI, without needing an audit. Click a unit for its
  wells and curves.

#### Quantities & normalisation
- **Absolute quantification** (`qpilot/qpcr/absolute.py`, `qpilot/qpcr/absolute_study.py`,
  `GET /api/studies/{id}/quantities[/{target}]`, [`docs/quantities.md`](docs/quantities.md)):
  Results → **Quantities** shows standard curves (per plate, pooled across plates that carry the
  same series), the efficiency with its 95 % CI, the limit of detection (95 % of wells detected;
  logistic when a level is partly detected) and of quantification (back-calculated CV ≤ 35 %),
  and every unit's copies with a 95 % prediction interval and plain-word flags (extrapolated,
  below the LOD or LOQ). Per µL and per ng once a person records the reaction input
  (`POST /api/studies/{id}/quantities/reaction`, a `choice.reaction_input` proposal, kept out of
  the design hash). An ng → copies helper on the Design page (`GET /api/tools/copies`);
  `qpilot quantify FILE…` and `qpilot copies --ng --length`. Standard curves and Quantities tables
  in every export, a Methods paragraph, MIQE 5.13/5.14 answered from the curves. Method card
  [`methods/absolute_quantification.md`](methods/absolute_quantification.md). On a real
  QuantStudio 3 export: slope −3.327, efficiency 99.8 %.
- **NormFinder** (Andersen et al. 2004; `qpilot/qpcr/normfinder.py`,
  `GET /api/studies/{id}/references`): next to geNorm on the reference-gene panel, with a plain
  verdict on the best pair. Which reference genes are used stays a person's choice on the
  reference-gene card. Method card [`methods/normfinder.md`](methods/normfinder.md).
- **What to normalise each gene to, opt-in** (`qpilot/qpcr/axes/normaliser.py`): your reference
  genes, NormFinder's or geNorm's best pair, or the global mean (studies with at least 50 genes),
  tested as one more choice of qPilot's grid with its own Decision Card. On the demo NormFinder's
  pair changes 3 of 58 calls and the global mean 19.
- **How to correct differences between plates, opt-in** (`qpilot/qpcr/interrun.py`): an
  inter-run calibrator, or factor correction (Ruijter et al. 2015), with a card only when a
  correction changes a call. Method card
  [`methods/inter_run_calibration.md`](methods/inter_run_calibration.md). `qpilot run
  --normaliser all|LIST` and `--interrun all|LIST`; Results → "Also test other normalisers" and
  "Also test corrections between plates".
- **The efficiency models, opt-in** (`qpilot/qpcr/axes/`, with the axis registry, stage caches and
  grid cap): which efficiency turns each Cq into a quantity (LinRegPCR's mean per assay and
  plate, each well's own, one per assay over its plates, an assumed 2.0, the dilution series') as
  one more choice of the robustness grid, screened first, with its own Decision Card
  (`numbers.efficiency_model`). Asked for in Studio (Results → "Also test efficiency models": a
  `choice.axis` proposal the rule makes, D-AXIS checks and a person accepts) or with
  `qpilot run --efficiency all|LIST`. The request lives in the design (`StudyDesign.axes`; absent
  by default), so `qpilot verify` and `qpilot rerun` reproduce it. On the demo it changes 6 of 58
  calls (each well's own 5, an assumed 2.0 4, the dilution series 3). Method card
  [`methods/efficiency_model.md`](methods/efficiency_model.md).

#### Run Gate & melt
- **Melt curves** (`qpilot/qpcr/melt.py`, `GET /api/studies/{id}/melt`,
  `GET /api/sessions/{sid}/melt`): each well's −dF/dT, its peaks and Tm for SYBR Green / EvaGreen
  assays, judged in the Run Gate by **G-MELT** (added in pack `research-default` 1.2.0): one product within
  1 °C of the assay's Tm, extra peaks, and what melted in no-template controls; G-NTC-1 treats a
  primer-dimer in an NTC as a warning. A melt panel in Curves, the wells' melt curves on a G-MELT
  check in Controls, MIQE 5.19 from the melt, StepOne "Melt Region" section files read, and
  `qpilot melt FILE… [--json]` (reads only). On a CFX96 SYBR plate of the corpus (Hsieh et al.
  2016), 96 of 96 wells within 0.5 °C of CFX Manager's own Tm. Method card [`methods/melt_curve.md`](methods/melt_curve.md).
- **G-IPC, inhibition from the internal positive control** (pack `research-default` 1.3.0): a
  study well whose IPC (a target named IPC or IAC) comes up 3 or more cycles later than in the
  no-template wells, or where nothing amplified, is a warning with its consequence test; the
  3-cycle threshold is a lab-editable default. G-NTC-1 no longer judges an internal control (it
  is meant to amplify in the no-template wells). On the QuantStudio 7 Pro eDNA plate, sample
  M22's wells come up 3.5 to 4.2 cycles late.
- **Run Gate, the Controls section** (`qpilot/core/rules.py`, `qpilot/core/gate.py`,
  `qpilot/qpcr/gate_rules.py`, `packs/research-default.yaml`, `GET /api/studies/{id}/gate`): every
  plate's controls checked against a rule pack (G-TYPED, G-NTC-1, G-NAC, G-NRT, G-POS, G-STD,
  G-REP), and for each rule that warns or fails, whether leaving out the wells it points at would
  change a conclusion. Rules label; a person decides. Agreement with an independent oracle on the
  demo: `validation/scientist/`.
- **G-RT and G-INSTR in the Run Gate** (pack 1.1.0, `qpilot/qpcr/run_links.py`): reverse-
  transcription replicates per biological unit × target, and what the run file says per plate
  (run completed, pauses, lid openings, calibrations past expiry, holds off their setpoint), with
  sources, thresholds and the consequence test. On Controls a person links the run file the
  instrument wrote (an `.eds`, a QuantStudio export, CFX run information) to a plate
  (`POST /api/studies/{id}/gate/run-files`, `…/unlink`), kept for every analysis of the file. A
  session opened from a vendor export reads each plate's run file among the export's own files
  (`qpilot/qpcr/export_runs.py`) without a link.
- **Deciding a Run Gate card** (`POST /api/studies/{id}/gate/cards/{card_id}/decide`): in a Studio
  session a person chooses an option of a `gate.rule` card with a reason. Leaving wells out
  becomes one `curve.exclude_well` proposal per well, accepted by the person in one write to the
  session's hash-chained inbox; the study is analysed again; **Put the wells back** undoes it.
- **Choices carried to a new analysis** (`StudyStore.carry_decisions`): when a person's decision
  changes a confirmed design after the curves are confirmed (a Prism exclusion, a well left out
  or put back, a further choice switched on or off), what the person chose on the earlier
  analysis's Decision Cards is carried as new chain entries that name the earlier study and
  entry. A choice that matters more in the new analysis is asked again.
- Confidence caps (`qpilot/core/confidence.py`): `grade(..., cap=Cap(level, check_id, note))`, a
  ceiling with a named reason, reported among the checks.

#### Trace, repeat plan
- **Trace's Decide… applies the set-aside in a Studio session** (`Studio.decide_trace`): the wells
  leave the analysis and the study is analysed again, with the person's Decision Card choices
  carried; **Set aside from Trace** lists them, with **Put the wells back**. Outside Studio a
  Trace decision is recorded and the numbers stay as analysed.
- **What to repeat, and why** (`qpilot/qpcr/repeat.py`, `GET /api/studies/{id}/review/repeat`):
  the Run Review ranks each sample × gene worth re-running by what it does to the calls (the Run
  Gate's warnings and failures, wells a person left out, samples in no comparison, no
  amplification where the gene amplified elsewhere, Trace's places), lays out a downloadable
  repeat plate (every repeated sample with its reference genes, per assay the inter-run
  calibrator, no-RT and no-template controls) and shows the Run Gate per plate; Controls offers
  the plan; `qpilot report run-review --repeat [--repeat-csv FILE] [--all-items]`. Re-running is
  a person's call.
- **origin/main's 18 Oct work in the one page** (`INTEGRATION.md`): Shiva Teja's Trace engine with
  its planted-fault benchmark, the Spreadsheet Check, the Evidence Ledger, the Run Review with a
  person's sign-off, the instrument registry and logbook with lookback, the replicate budget
  planner, Ask's Trace questions and the Excel export, as page sections (**What this study cannot
  tell you**, **Where to look** with **Decide…**, **Sheet check**, **Instruments**).

#### Exports & Prism
- **Your numbers as numbers** (`qpilot/report/tables.py`, `qpilot/report/excel.py`,
  [`docs/exports.md`](docs/exports.md)): Report → Export writes an Excel workbook (results per
  gene with fold change, 95 % CI, p and n; each biological unit's ΔCq and relative quantity;
  every well's Cq, N0 and efficiency and why a well was left out; Trace's places; decisions;
  settings; Methods), the same tables as CSV, a figure per gene (each dot a biological unit, the
  mean with its 95 % CI; editable SVG, 300-dpi PNG, its data and caption) or a journal supplement
  (workbook, tables, MIQE checklist, figures, the RDML file with qPilot's Cq, N0 and left-out
  wells, and the Analysis Record). Every file follows the options chosen on the Decision Cards and
  adds the recommended analysis where it differs. Gene → **Figure** previews a gene's figure.
  `qpilot export xlsx|csv|figures|supplement`.
- **Send to Prism writes a Prism project** (`.pzfx`; `qpilot/prism/`,
  [`docs/prism.md`](docs/prism.md)) that opens in GraphPad Prism as it is: one table per gene, a
  table of all genes and an Info sheet with who decided what. No template to build, no script to
  run; steps for Windows and macOS on the page. To bring changes back, save the project in Prism
  and choose it under Round trip (`POST /api/sessions/{sid}/prism/roundtrip/upload`): exclusions,
  deletions and edits become questions with their consequences. A project a person accepted
  stays valid while no decision changes a number in its tables. `qpilot export prism` writes the
  project; `--scripts` adds the optional Prism scripts, `--scripts-only` writes the older bundle.

#### Agents/MCP
- **Seven new MCP tools** (33 in all: 28 `qpcr_*` and 5 `sim_*`): `qpcr_comparisons`, `qpcr_units`
  (paged), `qpcr_melt`, `qpcr_quantities`, `qpcr_repeat_plan` (items paged, the plate as CSV),
  `qpcr_export` (writes new files only; decides nothing) and `qpcr_request_set_aside` (a request
  that always waits for a person). `qpcr_prism_diff` reads a project saved in Prism (`project_path`). Trace shows an
  agent's request at its place: **Approve**, or **Turn down the request**; the Agents section
  groups the tools as Read, Open, Propose, Request a decision and **Write a file**. See
  [`docs/agents.md`](docs/agents.md).
- **The MCP tools' contract for agents** (`qpilot/agents/`): every refusal carries `error`, a
  stable `code` and a `fix` and is marked `isError`; `pending_human` says why it waits
  (`needs_human_decision`, `autonomy_forbids`) and is not an error. `qpcr_decide`, `qpcr_propose`,
  `qpcr_export` and `qpcr_request_set_aside` take an `idempotency_key`. Every tool has a title,
  honest annotations and an output schema each reply is checked against;
  `response_format="concise"` on the reading tools; `fact_ids` on the study's numbers; the study's
  files as read-only MCP resources.
- MCP `qpcr_gate` (read-only): the controls, the consequence tests and the `card_gate_*` cards;
  `qpcr_decide` on a gate card is always `pending_human`.
- `qpcr_inspect` and `qpcr_study` read instrument exports inside `QPILOT_DATA_ROOTS`, as the
  page's Open does; an export is analysed only with a design a person confirmed.
- Open Decision Card kinds (`qpilot/core/card_kinds.py`): a validated registry; a kind this build
  does not know is a human decision (fail closed).

#### Performance
- **The page is faster** (`qpilot/web/warm.py`, `frontend/src/api/live.ts`): each decision re-reads
  only the views it changed (a Studio action moves about 40–80 KB instead of 2–6 MB); unchanged
  views answer `304` (ETags) and JSON is gzipped. After start-up and after each new analysis,
  qPilot prepares Controls, the report, Trace, the audit and the Evidence Ledger in the
  background. Measured on the demo, first visit: Controls 11.3 s → 0.35 s, the report 4.2 s →
  0.49 s, Results 3.6 s → 0.67 s; rejecting a design proposal 2.7 s → 0.3 s; confirming the
  curves 13.3 s → 3.3 s. Proposing the design is about twice as fast, the Curve Judge reads the
  curves once, and the audit says how many analyses it has run.

#### Install & platforms
- **Install in one line** ([`docs/install.md`](docs/install.md)): `pipx install` or
  `uv tool install` (from GitHub until the first PyPI release), on Windows, macOS or Linux,
  Python 3.11–3.13, no Node and no compiler; Windows step by step in PowerShell; where your data
  lives; offline installs.
- **Releases** ([`docs/release.md`](docs/release.md), `.github/workflows/release.yml`): a tag builds
  the wheel and sdist, smoke-tests the installed wheel and makes a GitHub Release; PyPI Trusted
  Publishing is skipped until the repository variable `PYPI_PUBLISH` is `true`.
- **CI on Ubuntu, macOS and Windows** with a smoke test of the installed wheel
  (`scripts/smoke_installed.py`).
- **End-to-end tests on real lab files with no model** (`frontend/e2e/`): a LightCycler 96 plate,
  QuantStudio quantities, the K. phaffii study's several comparisons, Trace's set-aside and put
  back, and phone width. The test suite holds on a loaded machine (jobs followed, CPU-time
  budgets, a private test cache).
- `scripts/gate.sh` (the merge gate in one command) and `scripts/demo_regression.py` +
  `scripts/demo_fingerprint.json` (the locked demo numbers, checked end to end).

### Changed
- **A science review of this round** ([`docs/science-review-2026-10.md`](docs/science-review-2026-10.md)):
  every new method recomputed by an independent oracle on real lab files (`validation/excellence/`,
  `tests/science/`): Welch, paired t, Holm, BH and Welch's ANOVA to 1e-15, Dunnett and Tukey,
  NormFinder, inter-run calibration and factor correction against the papers, melt against CFX
  Manager's own −dF/dT, the audit's replicate rules. Its judgement calls (J0–J12) were then
  applied as the review recommends (29 Oct 2026; each J's "Applied" line in the review says what
  and where):
  - **Plan next / `qpilot plan` / `qpcr_plan` lead with the samples per group for qPilot's call**
    (p < 0.05 and at least 2-fold, `n_for_call`), with the samples a t test alone needs beside it,
    now exact (non-central t; the normal approximation was one sample short in 9 of 24 settings:
    2-fold at SD 0.5 needs 6, not 5). The Cq of one copy comes from a standard curve when there is
    one (`qpilot plan --curve-from FILE`, `qpcr_plan(study_id=…)`), else 35; the Poisson floor is
    said to be a lower bound below 3 copies.
  - **Run Gate pack `research-default` 1.4.0**: a no-template peak is a primer-dimer candidate only
    3 °C or more below the product (`dimer_min_below_c`, lab-editable; closer is another product);
    G-REP proposes no single well when the farthest wells tie (duplicates; 20.0/20.5/21.0); G-STD
    cites Taylor et al. 2010 for 90–110 % and R² 0.98. The demo's gate is unchanged.
  - **What to repeat**: "no amplification where one was expected" counts within the sample's own
    group (at least three others there); the 90 % is lab-editable (`?expected_share=`,
    `qpcr_repeat_plan(expected_share=)`).
  - **The global mean** uses only the genes measured in every compared unit (a gene missing in a
    unit is usually low there); 50 of them are needed. On the demo 45 of 64 are, so the opt-in
    global mean is no longer offered there.
  - **A unit of several samples** is the mean of its samples' means (a sample in three wells no
    longer weighs three times one in one); one sample per unit, and the demo, are unchanged. The
    audit combines them the same way, and its drop-outlier rule uses G-REP's tolerance (with the
    Poisson term from the plate's standard curve) and tie rule.
  - **Dunnett and Tukey** leave a group of capped values only out of the pooled variance; Welch's
    ANOVA says per gene when it left a group out.
- **Plan next starts at 2.5×**, above the 2-fold call line, and says why; plans are faster.
  `qpilot plan` and MCP `qpcr_plan` default to 2.5× too. `qpilot plan --cq/--expected-cq
  [--cq-one-copy]` sets the well noise from Poisson sampling at that Cq
  ([`methods/replicate_budget.md`](methods/replicate_budget.md)).
- **A gene never detected in one group** is reported "detected only in ⟨group⟩" with that group's
  ΔCq, never as a fold change made from capped values; no analysis compares a group made only of
  capped values.
- **A sample missing one gene** is dropped from that gene only, not from every gene.
- **Claim Auditor**: a claim about groups the study does not compare (MYCN amplification, stage,
  risk, another gene's status) is "Not supported: different groups" and says what the study
  compares; p-values stay with their own gene; a normalisation sentence applies only to the claims
  it is about.
- **Ask** finds genes by their HGNC alias (survivin → BIRC5).
- **Verify** names an altered or damaged file ("This record was altered or damaged after export:
  decisions.jsonl"), the entry where a chain breaks, or "not a qPilot record".
- **One wording everywhere**: one story for the two robustness counts (qPilot's choice grid and
  the audit's reasonable set, with "Why two counts?"), one name per group, plate and study,
  "Decided by you", plurals without "(s)", folded refuted Curve Judge calls and Decision Cards
  that fit a phone's width.
- Run Gate pack `research-default` 1.4.0 (1.2.0: G-MELT, and G-NTC-1 reads the melt of a
  no-template control; 1.3.0: G-IPC, and G-NTC-1 leaves internal controls alone; 1.4.0: the
  science review's G-MELT, G-REP and G-STD changes). The seven rules of 1.0.0 give the same
  verdicts on the demo.
- **Names are the lab's own**: groups, units, samples and genes keep any letters, digits, spaces
  and signs (`LPS + inhibitor`, `IL-6/ctrl`, `Day 3 (50 µM)`, `KO#2`, `α-syn`; at most 64
  characters) on the Design page and in every export; file names are derived safely (an ASCII
  slug and a short hash, `qpilot/core/names.py`). For Prism a group or unit cannot start with
  `=`, `+` or `@`.
- Accessibility: the comparison picker is a radio group; scrollable tables are reachable with the
  keyboard.
- A multiplex study analysed before this release no longer reproduces on re-analysis (its other
  dyes now have an N0): Trace and the exports say so until it is analysed again.
- `openpyxl` is a required dependency (Excel files work without extras); the sdist is an
  allow-list; the version is read from `qpilot/__init__.py`.

### Fixed
- A standard curve no longer includes wells LinRegPCR calls "no amplification" (they carried a
  quantity): on the QuantStudio 7 Pro eDNA curve three flat wells gave 154 % efficiency, R² 0.41;
  now 87.1 %, R² 0.9962 (science review J1).
- A quantity read from a weak standard curve gets the exact (Fieller) 95 % interval when the
  curve's g is above 0.05; the classical one was too narrow and off-centre there (eDNA curve, g
  0.21: [−0.56, 6.17] log10 instead of [−0.20, 5.80]). Every curve shows its g (science review J2).
- A study with three or more groups gets its report again; "The confirmed design" on the Design
  page shows the latest decisions.
- Trace's what-ifs on a paired or Holm-corrected study are the engine's own evaluation (they were
  an unpaired Welch update), so Trace's call is the engine's corrected call.
- The Claim Auditor checks a claim about another of the study's comparisons against that
  comparison, not the first; a phrase naming another grouping is no longer read as the study's
  group inside it (9 of 20 such sentences came back "Supported"; now 1 of 20).
- Excel-saved sample sheets were read without their text.
- The gene-symbol gate never reads a qPCR label as a gene (`REF` was proposed as ALYREF).
- The Evidence Ledger no longer shows LinRegPCR's "-1" (no mean efficiency) as a gene median.
- The robustness audit: a study with no data issue no longer fails, small panels get no noise
  outliers, a value without any well is left out (never treated as undetermined), and its lab
  panel counts wells, not samples, with technical replicates.
- A report on a one-gene, one-plate study reads right.
- Text is UTF-8 with LF line ends on every system, so a record verifies and keeps its id on
  Windows; UTF-8 output through a Windows pipe; the pseudonym key is read as binary.

### Security
- **A security review of this round** ([`docs/security-review-2026-10.md`](docs/security-review-2026-10.md),
  RT-EX-001 to 015, `THREAT_MODEL.md` rows 45–47), each finding shown by a failing test, then
  fixed: `qpilot quantify --csv` defuses formula-like names (every person-facing CSV now does); a
  figure of a name the exports refuse is a 409 in words, not a 500; `qpcr_export`'s copy never
  replaces a file that appeared while the export was written; an MCP path outside the data roots
  gets one refusal whether it exists or not; uploads are read off the event loop; the release's
  published files are built by a job that runs no npm, and checkouts keep no token. In the public
  sandbox (`QPILOT_HOSTED=1`) the Prism round trip reads only qPilot's export folder, a write is
  refused (507) before the disk fills (`QPILOT_MIN_FREE_MB`), and unpacked XML is capped
  (`QPILOT_MAX_UNPACKED_MB`).
- Setting the design and recording the reaction input require the decision-record head the page
  showed (`expected_head`), so a stale page cannot overwrite a newer decision (RT-EX-012);
  GitHub Actions are pinned by commit SHA (RT-EX-013).
- RT-UI-025: every refusal of an RDML file says its own reason, never a traceback.
- A hostile Prism project (a DOCTYPE, external links, an oversized file) is refused.
- The new MCP tools obey the blind rule (`results_hidden` until a person confirms the design and
  the curves), `qpcr_export` writes only new files named by qPilot (never over a file, never into
  the study store, never to a path outside `QPILOT_DATA_ROOTS`), and a set-aside request never
  sets anything aside; each was tried with hostile arguments (`tests/mcp/`). `THREAT_MODEL.md`
  row 44.
- RT-001: with `QPILOT_DATA_ROOTS` unset, `qpilot serve` no longer shares the filesystem root or
  the home folder as a data root when an MCP client starts it there.
- RT-003/004/005: package docstring vocabulary; name and id patterns end at `\Z`; an unsafe
  member in a record zip is refused, not a traceback.

## [0.1.0] — baseline `81484f7`

The state of `main` when the agent team started: 14 CLI commands, 16 MCP tools, qPilot Studio,
the Decision Simulator (`qsim`), the Prism bridge, the model layer and its harness, and the
hash-chained Analysis Record with `verify` and `rerun`.
