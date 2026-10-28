# qPilot — the one page

`qpilot app` serves one page on `127.0.0.1` (first free port from 7860): Studio, the results,
the robustness audit, Prism and the Analysis Record, for one study at a time, on one server.
It replaces the three earlier pages (`qpilot app` Gradio, `qpilot studio` Gradio, `qsim app`).
Research use only.

This file is the build spec for the page: what each section shows, where its numbers come from,
the design system, the API conventions and who builds what. Keep it true as the page changes.

---

## 1. Principles (non-negotiable)

1. **AI proposes. The engine checks. You decide.** Every write from the page is `actor="human"`
   (the server sets it; the page cannot choose). Agents act only through `qpilot serve` (MCP),
   and a choice that can change a conclusion always waits for a person.
2. **Blind until confirmed.** In a Studio session nothing that reveals a group difference (group
   labels next to numbers, fold changes, p-values, consequences) is shown or sent until the
   design and the curves are both confirmed. The **server** enforces it (403 `blind`); the page
   never relies on hiding.
3. **No naked numbers, no mock data.** Every number on the page comes from the engine, the store
   or the audit for the open study, through the API. There are no sample numbers, placeholder
   genes, lorem ipsum or "example" charts in the shipped page. Empty states say what to do.
4. **Text is text.** Every string from a file, a sheet, a model or an agent is rendered as text
   (React escaping). No `dangerouslySetInnerHTML`, no `innerHTML` (lint error).
5. **Nothing leaves the machine.** The page loads nothing from the internet (fonts and code are
   bundled; CSP `default-src 'self'`). Only the demo download and a configured remote model
   reach out, each on an explicit action and said so on the page.
6. **Ordinal levels, never percentages of confidence.** Confidence is High / Moderate / Low /
   Very low with named reasons. "Holds in 64 % of reasonable analyses" is a robustness fraction,
   not a confidence.
7. **Plain words.** Scientists, not developers, read this page. Say what a thing means and what
   to do next; never show an exception, a stack trace or a raw id where a sentence fits.

## 2. Information architecture

One hash-routed page. Global routes: `#/` (Open), `#/sheetcheck`, `#/instruments`, `#/settings`.
A workspace is either a Studio
**session** (`#/s/<session id>/<section>/…`, the session id is `input_sha256[:12]`) or a
**study** analysed outside one (`#/r/<study id>/<section>/…`; e.g. by `qpilot run` or an agent's
`qpcr_study`), whose results show straight away.

| Section | Route | Shown when | Data (API → service) |
|---|---|---|---|
| Open | `#/` | always | `GET /api/system`, `GET /api/workspaces`, `POST /api/workspaces` (upload: `rdml` + `sheet`, or `files` = instrument exports sorted by content → `qpilot.web.intake` + `io.connectors.materialise`), `POST /api/workspaces/demo`, `POST /api/demo/fetch` |
| Design (blind) | `…/design` | session | `GET /api/sessions/{sid}` (incl. `capture`: what an export was read as), `…/proposals?stage=design`, `…/plate`, propose/accept/edit/reject/bulk/confirm → `Studio.*` |
| Curves (blind) | `…/curves` | session, design confirmed | `…/proposals?stage=curves`, `…/plate` (calls, Cq, efficiency, R²), `…/curve?well=`, `…/curve-calls?gene=` → `Studio.propose_curves/curve/curve_calls` |
| Results | `…/results` | results visible | `GET /api/studies/{id}/results` (summary, rule, genes with robustness + confidence, the opt-in `axes`), `/flips`, `/cards` (incl. cards opened from Trace, with their `place`), decide/undo/turn down/explain → store + `core.decisions` + `ai.explain`; `GET /api/studies/{id}/evidence` (the Evidence Ledger) → `qpcr.evidence`; `…/proposals?stage=choices`, `POST /api/sessions/{sid}/propose/axis` → `Studio.propose_axis`; `GET /api/studies/{id}/import-trust`, `POST …/import-trust/decide` (session only) → `io.trust` + `Studio.decide_import_trust` (+ the `analyse` job for Cq only) |
| Controls | `…/gate` | results visible | `GET /api/studies/{id}/gate` (first run a `gate.run` job: 409 `loading` + the job) → `qpcr.gate_rules.run_gate` (rule pack `packs/research-default.yaml`) + `core.gate` (consequence test); `POST /api/studies/{id}/gate/cards/{card_id}/decide` (session only) → `Studio.decide_gate` (curve exclusions) + the `analyse` job; `POST /api/studies/{id}/gate/run-files` (multipart `plate` + `run`), `POST …/gate/run-files/unlink` → `qpcr.run_links` (G-INSTR's run file for a plate; else the export's own, `qpcr.export_runs`) |
| Gene | `…/gene/<GENE>` | results visible | `GET /api/studies/{id}/genes/{gene}` (qPilot contrast, robustness, confidence, cards affecting it) + audit gene views when an audit exists |
| Audit | `…/audit` | results visible | `GET|POST /api/studies/{id}/audit` (status / run), `/audit/overview|study|how|gene/{g}|analyses/{g}|effects/{g}|lab/{g}`, `POST /audit/whatif|samples` → `integration.simulator` + qsim `Screen`/`LabViews` |
| Trace | `…/trace`, `…/trace/<GENE>` | results visible | `GET /api/studies/{id}/trace`, `…/trace/{gene}`, `…/trace/plate?run=`, `POST …/trace/{gene}/without` (first load a `trace.load` job: 409 `loading` + the job) → `qpilot.trace`; **Where to look**: `GET …/where-to-look?gene=|sample=|well=`, in a Studio session `POST …/where-to-look/decide` and `…/put-back`, `GET …/where-to-look/set-aside` (Decide… applied: `Studio.decide_trace`, Run Gate's path), outside Studio `POST …/where-to-look/open` → `qpcr.trace` at the analysis in use + `StudyStore.open_card` |
| Claims | `…/claims` | results visible | `POST /api/studies/{id}/claims` → `qpilot.claims` |
| Report | `…/report` | results visible | `GET /api/studies/{id}/report`, `POST …/report/export` (`md`, `html`, `passport`, `xlsx`: a `report.export` job), `GET …/report/exports` → `qpilot.report` (+ `report.excel`); **Run Review**: `GET …/review`, `GET …/review/repeat` (+ `.csv`), `POST …/review/sign-off` → `report.run_review`, `qpcr.repeat` + `StudyStore.append_review` |
| History | `…/history` | results visible | `GET /api/studies/{id}/history`, `/history/diff`, `/history/compare` → `qpilot.history` |
| Plan next | `…/planner` | results visible | `GET|POST /api/studies/{id}/planner`, `POST …/planner/layout`, `GET …/planner/layout.csv` → `qpcr.plan` + `qpcr.layout` |
| Prism | `…/prism` | session, results visible | `/prism/preview|routes|bundles`, `POST /prism/draft|send|roundtrip` → `Studio.preview_prism/propose_prism/send_to_prism/launch_prism/round_trip` |
| Record | `…/record` | always (empty until analysed) | `GET /decisions` (chain), `POST /record` (export → download), `POST /api/records/verify` → `core.record` |
| Agents | `…/agents` | always | `GET /api/agents` (MCP command, tools, pending requests, recent agent entries) |
| Sheet check | `#/sheetcheck` | always | `POST /api/sheets` (keep a `.xlsx`/`.csv`), `POST /api/sheets/{id}/check` (`study_id?`, a person's `columns`, `confirm`) → `qpcr.sheetcheck` |
| Instruments | `#/instruments`, `#/instruments/<id>` | always | `GET|POST /api/instruments`, `GET /api/instruments/{id}`, `POST …/events`, `POST …/incidents`, `POST …/incidents/{seq}/confirm|reject|fix`, `POST /api/instruments/runs` (+ `…/runs/{id}/link`), `POST /api/studies/{id}/lookback` (a `lookback.run` job) → `core.instruments` + `qpcr.instrument_context` + `qpcr.lookback` |
| Settings | `#/settings` | always | `GET/PUT /api/settings`, `GET /api/model`, `POST /api/model/test` (harness scorecard) |

Ask (a drawer, every workspace section): `POST /api/studies/{id}/ask` → `ai.ask.ask`, and for an
audited study the audit's `Asker` — the answer shows which tool answered, who wrote the words
(template or model), and the facts it cites.

## 3. The shell

* **Rail (left, 248 px; icons only below 1024 px; bottom bar on phones).** The workflow in order
  (Design → Curves → Results → Controls → Audit → Prism → Record), each with its live state: a check when
  confirmed, a count of proposals waiting, a lock with the reason when not reachable yet
  ("Confirm the design first"). Below: Agents (with the pending-request count), Settings. The
  workspace switcher sits at the top (recent workspaces, ⌘O opens a file).
* **Top bar.** Study title and short input SHA (copy on click); the chain-head pill (`chain 3f2a…`,
  opens Record's timeline); the model chip (`no model` / `local qwen2.5:7b` / `REMOTE — names
  pseudonymised`, with a dot: answering / checking / not answering + reason on hover); the
  autonomy switch (Suggest · Decide and tell me); the agent bell (live count, popover list);
  ⌘K; the theme toggle; the live dot (event stream connected / reconnecting).
* **Next-step banner** under the top bar on workspace sections: `WorkspaceView.next_step`
  (title, detail, a button that goes to the section and focuses the named action).
* **Ask drawer** (right, 420 px, ⌘J).
* **Toasts** (sonner) for every write: what happened, with Undo where the chain allows it.
* **Job cards**: a slow action shows an inline card with the step, the elapsed time against the
  typical time ("usually ~50 s"), and a progress bar when the job reports a fraction. Jobs
  survive navigation; the bell's popover lists running ones.
* **Errors**: `ApiError.message` verbatim in a calm panel; `needsKey` (401) shows one screen:
  "Open the link qPilot printed in your terminal"; `stale` (409) re-reads the view and says
  "Something was decided since you loaded this (another tab or an agent). Here is the current
  state."

## 4. Sections in detail

### Open (`features/home`)
Hero: one sentence of what qPilot does, then three actions: **Drop a file** (an RDML file, or
what the instrument exported: one file or a whole export set, up to 64 files, from Bio-Rad CFX
(amplification per dye + Cq results + run information), QuantStudio / StepOne / 7500,
LightCycler 480, RDES or a tidy table; optional sample sheet; optional one sentence about the
experiment, ≤ 500 characters), **Open the demo
study** (Vermeulen 2009 / Ruijter 2013, 64 plates, 366 tumours; if not cached: "Download 7 MB
from the RDML consortium's repository (SHA-256 pinned)" first), **Recent** (workspace cards: title,
file, plates · samples · genes, stage chips, decisions, pending requests, audit badge, updated
"2 h ago"; demo badge). System strip: version, method commit, `outbound` line, simulator
installed, model chip. "Start a fresh demo" lives in Settings (moves earlier work aside).

The intake lists each dropped file with a first guess from its name ("CFX amplification curves
(SYBR)", "QuantStudio amplification data", "RDML file") and names back what it cannot take (an
`.eds`/`.pcrd`/`.ixo` project file says how to export it). One RDML file (with at most one sheet)
goes in `rdml` + `sheet` as before; anything else goes in `files`, and the **server** decides by
content (`detect()`, never the suffix alone): an RDML file opens as it is; files a vendor
connector reads are the export (one kind at a time); a remaining `.csv`/`.xlsx` with a sample
column that is not a sheet of the export itself is the sample sheet; anything else is named back
as not used. A refusal is a sentence (400 while sorting, a failed open job for a reader's
refusal). An export is staged under the person's own names in the study store
(`imports/sources/`), written once as deterministic RDML (`imports/capture/<key>.rdml`, cached),
and the session opens that file; what was read is kept as `capture.json` in the session folder.

### Design (`features/design`) — blind
Left: the inbox (the six-part proposal card, contradicted first). Right (sticky): the **plate
map** for the selected plate (wells coloured by declared sample type: unknown / standard / NTC
/ NRT / …; target per plate; quarantined names shown as their quoted text on hover, flagged
`instruction_like` text marked and never obeyed), the file facts, and for a session opened from
an instrument export the **Imported from …** card (`WorkspaceView.capture`): the source files by
their names, per plate wells / cycles / targets / dyes / declared sample types, the instrument's
Cq count and omitted wells (recorded, never applied), the signal, the raw-ness verdict with what
it means (baseline-subtracted or rescaled curves weaken LinRegPCR's per-well efficiency, with how
to re-export; Cq only: no curves to check), files not used and each warning. When the verdict calls
for the Import Trust card (`CaptureRawness.import_trust`: baseline-subtracted, or qPilot could not
tell) one line says that every gene is capped at Moderate until a person decides, on Results once
the blind is lifted. Blind-safe: counts and names only, no sample name, no Cq value, no group.
* Proposal card: (1) the proposal in words + the alternatives considered; (2) **Why**: each
  evidence item as a fold-out (text quote with its origin, a sheet cell, a well → opens its
  curve); (3) **Engine check**: consistent / contradicted / cannot check, with the rule ids and
  numbers; (4) **Consequence**: hidden, or "this matters for at least one conclusion", or the
  answer to **Does this matter?** (a job); (5) **Level** + reasons; (6) **Accept**, **Edit**
  (fields of the payload; re-checked), **Reject** (reason required). Footer: made by (rule /
  model name + prompt hash / agent).
* Bulk: **Accept all consistent…** shows the exact list first, then accepts exactly that list.
  **Reject contradicted AI calls…** same, with one reason. **Confirm this stage…** shows what it
  covers; **Yes, confirm** confirms.
* Empty: "Ask for proposals on the design" → **Propose the design** (job; the one sentence from
  Open is used).

### Curves (`features/curves`) — blind
**Check the curves** (job, ~15 s on the demo) → Curve Judge disagreements as proposal cards
(well call proposals), the call-rule proposal, then confirm. The **plate heatmap**: per well the
amplification call (shape + colour), Cq, efficiency or R² (switch), disagreements outlined; a
gene filter. Click a well → **curve viewer** (uPlot): raw fluorescence by cycle, linear/log
switch, the Cq marker and baseline when known; neighbouring wells of the same sample overlaid.
No group labels here. A well left out of (or put back into) the analysis is a `curve.exclude_well`
proposal (subject `run/well`, payload `{"excluded": true|false}`), accepted only with a reason
and never in "Accept all consistent"; the Controls section makes them from a gate card. Accepted
after the curves are confirmed, it keeps them confirmed (the confirmation does not cover the
wells left out) and makes a new analysis, like an accepted Prism exclusion. A person's option on
the Import Trust card (Results) is a `curve.import_trust` proposal (subject `import`, payload
`{"option": …}`, engine check D-TRUST), also accepted only with a reason and never in "Accept all
consistent"; it is outside both blind confirmations (they never re-open for it).

### Results (`features/results`)
* Summary strip: plates, reactions, samples, groups (n each), the conclusion rule ("up or down
  only if p < 0.05 and at least 2-fold"), reference genes and their geNorm M/V.
* **Robustness map** (hero chart): every gene a point — x: fold change (log2 axis, labelled in
  ×), y: share of reasonable analyses with the same call (0–100 %), colour + shape by
  conclusion/level; the 2× lines; hover card; click → Gene. "View as table".
* **All genes table** (virtualised; sort, filter by conclusion / level / "flips"): gene, call,
  fold [CI], p, holds, confidence level, reasons.
* **Flip matrix**: decisions (rows) × genes (columns), a cell marked where that decision alone
  flips that gene's call (from the robustness impact / grid).
* **Decision Cards** (right column, ranked by impact): question, evidence, each option with what
  it changes for the headline genes, the recommended option, reason (required), **Decide**;
  decided cards collapse with who decided and why, **Undo** (a new chain entry). Agent requests
  waiting for a person show first, with **Approve** / **Turn down**.
* **Choices carried to a new analysis.** When a person's decision changes a session's confirmed
  design after the curves are confirmed (an accepted Prism exclusion, a well left out or put
  back, the efficiency models switched on or off), the session moves to another analysis of the
  file (`Studio._study`), whose design differs only in the wells left out or the further
  choices tested. What a person decided on the earlier analysis's cards is
  carried to it (`StudyStore.carry_decisions`): one new
  chain entry per card, `actor` human, `applied`, reason `Carried from analysis <study> (entry
  <hash>): <the person's words>`, so the hashed entry names where it came from; the card shows
  **Carried** and its status line says from where. Never carried: the system's automatic
  decisions (the new analysis makes its own), agents' choices and requests, a card or option the
  new analysis lacks, a decision already carried there once (a later change stands), a card with
  an agent's request waiting, and a choice that **matters more** in the new analysis (it can
  change a conclusion, or more or other ones, where it could not before): that card says what
  the person chose and why it is asked again. The **choices stage is not carried**: its
  confirmation is a person's statement about one analysis's cards, so a person confirms again
  (one click when every card is decided). A design changed in a blind stage and confirmed again
  is another question: its cards start afresh. A reason typed as `Carried from analysis…` is
  refused. **Explain with the model**
  (only when a model answers; numbers in the explanation are facts, cited).
* **What this study cannot tell you** (the Evidence Ledger, `qpcr/evidence.py`, origin/main's
  Gradio panel): eleven items (NTC, no-RT, reference genes, efficiency, raw-ness, RNA integrity,
  RT replicates, biological units, inter-run calibrator, lots, instrument), each present /
  absent / unknown / not applicable (glyph + word), what that means (every number a fact),
  absent and unknown first. Absent items never change a conclusion or a grade. The ledger is the
  one kept at analysis (`evidence.json`), else rebuilt read-only; for a study opened from an
  instrument export the raw-ness item reads Open's own check (`io/rawness`).
* **Cards opened from Trace** (`trace_set_aside`, a person's Decide… in Trace's Where to look)
  are listed with the other cards, say the place they are about (sample · plate · well) and what
  to check, and are decided the same way: a choice that can change a conclusion is a person's,
  at every autonomy level. Deciding one is kept in the chain; the study's numbers stay as
  analysed (leaving a well out of the analysis is Curves' or Controls' job).
* **Import Trust** (first in the Decision Cards column, a Studio session opened from an instrument
  export whose curves were most likely baseline-subtracted before export, or whose processing
  qPilot could not tell; `capture.import_trust`, always a person's decision; policy and words in
  `qpilot/io/trust.py`, science in `agent-bus/contracts/scientist-spec-capture.md` §4–5). Until a
  person decides, the curves as imported are analysed with every gene's confidence capped at
  **Moderate** ("vendor-baselined curves": a failed `import_trust` check, and a reason where it
  holds the level down; the caps are qPilot policy and say so). Options, each with its cap:
  **Re-export the raw curves** (recommended; the vendor's recipe, e.g. CFX "No Baseline
  Subtraction"; this analysis stays as it is), **Analyse the curves as they are** (Moderate),
  **Use the instrument's Cq values only** (the curves are not used: the instrument's Cq, quantity
  2^-Cq with every cycle assumed to double, no per-well efficiency; capped at **Low**, "efficiency
  assumed"; not offered without instrument Cq values). A reason is required; the choice is one
  `curve.import_trust` proposal accepted by the person in the session's hash-chained inbox, and
  only Cq only (or leaving it) analyses the study again (its Decision Cards start at the
  recommended options, said before deciding). An agent's `qpcr_decide` on `card_import_trust`
  over MCP is `pending_human` and waits on the card with **Approve** / **Turn down** (turning down
  rejects the request in the inbox). Shown on Results, not on Design: it can be decided only once
  the blind is lifted, and the cap it sets is what every gene's level and reasons here say.
  The efficiency models a person asks the grid to test never include each well's own efficiency
  for such curves, and under Cq only neither the per-amplicon mean nor the assumed 2 (said as not
  applicable, with why: `io.trust.not_measured`). Curves normalised to a passive reference (Rn)
  keep their ground phase and get no card; nor does an RDML file or a study analysed outside
  Studio. Refusals: `blind` (403), `studio` (409: outside
  Studio, no card, an option already chosen, Cq only without instrument Cq), `stale` (409).
* `j`/`k` move between cards, `Enter` focuses the reason, `⌘Enter` decides.
* **Also test efficiency models** (under the cards; `ResultsView.axes`, opt-in): what qPilot does
  with the efficiency model now (not tested / tested in the grid / tried, changes nothing / does
  not apply), each model with what it alone changes (facts) or why it does not apply here, and a
  link to its Decision Card (`numbers.efficiency_model`) once it is in the grid. In a session,
  **Propose testing the efficiency models** (`POST /api/sessions/{sid}/propose/axis`) adds a
  `choice.axis` proposal to the choices stage (the rule proposes, D-AXIS checks, a person accepts,
  edits the models with one switch each, or rejects); accepting analyses the study again with it,
  and **Propose to stop testing them** goes back to the earlier analysis; either way a person's
  choices on the other cards are carried (above). A
  study analysed outside Studio shows `qpilot run --efficiency all` instead. Method card:
  `methods/efficiency_model.md`.

### Controls (`features/gate`) — Run Gate
What the controls on each plate say, and whether any of it changes a call. The shipped rule pack
(`research-default` 1.1.0: G-TYPED, G-NTC-1, G-NAC, G-NRT, G-POS, G-STD, G-REP, G-RT, G-INSTR;
thresholds and sources in `packs/research-default.yaml`, science in
`agent-bus/contracts/scientist-spec-gate.md`) is evaluated on the study's wells; every rule that
warns or fails and points at wells gets the consequence test: the whole analysis grid is re-run
without those wells and compared at the analysis in use (each card's applied option, the planned
one elsewhere).
* **G-RT and G-INSTR** are origin/main's gate lines (`qpcr/gate_rt.py`, `qpcr/gate_instr.py`) as
  rules of the pack, with their thresholds as parameters (`limit_cycles` 1, Bustin et al. 2015
  as quoted in the research notes and still to be checked against the paper; `hold_limit_c`
  0.5 °C, a lab default) and the pack's severity. **G-RT** gives a verdict per biological unit ×
  target where the design marks reverse-transcription replicates (`rt_replicate`; one "not
  applicable" for the study when none are marked, as on the demo), counting every study well
  (including wells a person left out, so its option then says "already left out"; the Evidence
  Ledger's G-RT line counts the wells in use); a range at or above the limit warns and the
  consequence test leaves the unit's wells out for that target (or, with three or more RT
  replicates, the one farthest from the others). **G-INSTR** gives a verdict per plate from the
  plate's run file: whether the run completed, pauses and lid or drawer openings (with the
  cycles), calibrations past the vendor's expiry, holds off their setpoint. Each is a warning to
  weigh (G-INSTR's information lines, such as an expired calibration, are warnings here, so the
  consequence test prices them), and the test leaves the run's study wells out. The study's own
  file is RDML (`run_context.json`, else the input file), which names the instrument and the run
  date at most, so on the demo every plate is "not applicable" with what to do.
* **Which run file each plate reads**: a run file a person linked to the plate, else (a Studio
  session opened from an instrument export) the plate's run file among the export's own files,
  else the study's own file. Each plate of the RDML built from an export names the files it was
  read from (`CaptureMeta.plates[].sources`; read from the file names, as the connectors group
  them, for an import recorded before); `qpcr/export_runs.py` reads those kept in the
  kept-inputs folder by content, only while their sha256 is the one captured, and gives the
  plate the one that lets the most be checked: a QuantStudio results export's header rows
  (calibrations and their expiry, the run's end, per-well flags) or CFX Run Information
  exported with the data. Its check says it read "this plate's run file in the instrument
  export" (`source: export` in the view, with the file's name, serials blanked), never "linked
  by a person"; an export opened by an agent (its files are not kept by the page) reads the
  RDML. Amplification and Cq sheets are not run files and are passed over.
* **Run files**: a person links the run file the instrument wrote (an `.eds`, a QuantStudio
  results export, CFX run information; never an RDML) to a plate, by dropping it on the card or
  from a G-INSTR check's **Link a run file for this plate**; it is read instead of the export's
  own file or the RDML, and **Unlink** reads that again. The file is kept by content and
  read with the hardened reader; the link (`qpcr/run_links.py`, `<store>/run_links/<input
  sha256>.json`: plate, file, sha256, its name with serials blanked, kind, `by: human`, when) is
  kept per **input file**, so every analysis of the file reads it, including the new one a
  person's decision makes. A linked file that is gone or changed is said, never read. The card
  lists each linked file with its plate's verdict, **Show the check** and **Unlink**, and says
  in one sentence which run file each plate reads (linked, the export's, the study's own); the
  plate list marks the plates linked or read from the export. Linking changes no number: the
  gate is read again. Serial numbers never come back from the server.
* Header with the pack (name, version, hash); **In one line**: the headline (every number a fact),
  the verdict counts (Fail / Warn / Pass / Not applicable: status words only, no claim about the
  run as a whole) and what to do (Curves in a session, Trace for a study analysed outside Studio).
* **Plates**: one button per plate, gated or ungated (no wells typed as controls, dashed), its
  worst verdict as glyph + colour; pressing one filters the rule checks to it.
* **Rule checks**: warn and fail first (filters: verdict, rule, plate); each row opens to the
  reason in words, the wells it points at and **What leaving the wells out changes** (class,
  triage in words, each option's sentence: "Leaving these 2 wells out changes no call").
* **What leaving the wells out would change**: one line per tested finding; "Show the check" opens
  its row.
* **Decision Cards from the controls**: the `gate.rule` cards (only when leaving the wells out can
  change a conclusion: open when it changes a call at the analysis in use, decided automatically
  to keep when it changes one only at other settings; either way an agent must ask a person), in
  the Decision Card language. A gate card has no grid dimension, so it is not decided in the
  study's decision chain. **In a Studio session a person decides it here**: options, a reason
  (required), **Decide**. Leaving wells out becomes one `curve.exclude_well` proposal per well
  (proposed by Run Gate's rule, accepted by the person with the reason, all in one write to the
  session's hash-chained inbox, the same exclusions the Curves inbox lists), and the study is
  analysed again (the `analyse` job; the gate then reads the new analysis, where the option says
  "already left out" and the wells are listed with who decided, why and when, and **Put the
  wells back**). **Keep every well** puts back what a person left out through the card, or, when
  nothing has to change, records the keep (the rule's exclusions, rejected with the reason). What
  a person chose on the Decision Cards is carried to the new analysis (as after a Prism round
  trip; see Results), and the page says so before deciding. An agent's request (`qpcr_decide` on a
  `card_gate_*` card over MCP: always `pending_human`, filed as the agent's exclusions) waits on
  its card with **Approve** / **Turn down**. Refusals: `blind` (403) like every result, `stale`
  (409) when the analysis, the chain or the inbox changed since the view, `studio` (409) for a
  check whose wells change no conclusion, and for **a study analysed outside Studio**, which has
  no inbox: its cards are read-only, and the page says plainly that wells are left out by opening
  its file in Studio (Trace follows its calls down to their wells).
* **The rules and where their thresholds come from**: each rule's statement and its sources.
* A rule check that points at more than 24 wells (a whole run) shows the first ones and folds
  the rest.

### Trace (`features/trace`)
Follow any number down to the samples, wells and plates that drive it (`qpilot.trace`: flip sets,
control-gene shares, plates, a what-if without samples), at the analysis in use. **Where to
look** (origin/main's Trace engine, `qpcr/trace.py`, built here for the analysis in use and
cross-checked against the section's own numbers): trace a gene, a sample or a well
(`PLATE:WELL`); the places to look ranked by what each option there does (changes a call > moves
a fold change beyond its CI > changes nothing), the fingerprint checks each fails (S1–S7) in
words, what was checked and found nothing, what the data cannot show. **Decide…** on a place
whose option changes a call, in a Studio session (its current analysis), opens the place's
options and a reason box: a set-aside (the value: the well and its replicates; the sample: every
well) becomes one `curve.exclude_well` per well, made by Trace and accepted by the person with
the reason in one write to the session's inbox (`Studio.decide_trace`, Run Gate's path); the
study is analysed again (Trace waits for it) and the person's Decision Card choices are carried
to the new analysis. "Keep" puts back what was set aside at the place, or records the keep.
Reading a well from the sample's other reference wells stays a what-if (shown, not chosen).
**Set aside from Trace** lists what a person set aside that is out of the analysis now, each
with **Put the wells back** (a reason; only the wells set aside there come back). For a study
analysed outside Studio, Decide… opens the place as a Decision Card on Results
(`StudyStore.open_card`: no chain entry; recorded, the numbers stay as analysed) and the panel
says to open the file in Studio to leave the wells out. Method card: `methods/trace.md`.

### Report (`features/report`)
Methods, MIQE 2.0, a reviewer's report, the study passport, and **exports** (Markdown, printable
HTML, passport, and the **Excel workbook**: the results with a "Where to look" sheet, at the
recommended choices like the Analysis Record). **Run Review** (origin/main's Gradio accordion,
`report/run_review.py`): the headline genes, the Evidence Ledger, **what to repeat and why**
(`qpcr/repeat.py`, at the analysis in use: the Run Gate's warnings and failures, the wells a
person left out with their reason, samples in no comparison, wells with no amplification where
the gene amplified in at least 90% of the other compared samples, replicate wells that did not
amplify, Trace's places to look; per sample × gene, every reason in words and its own
consequence, ranked: changes a call > beyond the CI > no value > not known > changes nothing),
the **repeat plate** (every repeated sample with all its reference genes; per assay the inter-run
calibrator, the no-RT and no-template controls, a positive control where the run had one; the
planner's CSV; items that change no call only when asked), the **Run Gate lines per plate**
(with a link to Controls, which also offers the plan), every sign-off recorded, what is not
built yet (what to change next run, pointing at Plan next), and a person's
**sign-off**: accept / repeat / discuss, a comment and a name, one `review` entry in the decision
chain (actor `human`, set by the server; no card replays it, so it never makes a decision stale;
a decision made since the review was read makes the sign-off stale: 409, shown again). qPilot
never passes or fails a run.

### Gene (`features/gene`) — the merge
Header: gene, call (arrow + word), fold [95 % CI], p, n per group, confidence level + reasons,
verdict (when audited). Then, top to bottom: **What holds** (holds fraction, the analyses strip
— every reasonable analysis as a dot on the fold axis, coloured by call), **One choice at a
time** (dot plot per decision option), **Your samples** (beeswarm by group; click a sample →
its well, its curve), **What changes it / What it leans on / What to do** (audit), **Decision
Cards that affect this gene**, **Assay and wells** (efficiency, Cq range, undetermined), the
reference-gene stability bars, and the Prism figure for this gene when available. Prev/next gene
with `[`/`]`.

### Audit (`features/audit`)
Not run: what it is ("re-runs your confirmed study under every combination of eight analysis
decisions — 90,396 analyses on the demo, about 50 s — and gives each gene a verdict"), **Run the
audit** (job with stages). Refused / not applicable: the reason in words (e.g. technical
replicates). Done: tabs **Study** (verdict strip with counts, map, calls changed by one choice,
share of spread, reference stability, fix-these-first, issue queue), **What-if lab** (one select
per decision grouped by tier, dumbbell of every gene planned → chosen, changed genes first),
**How it works** (stages, verdict rules, known-answer tests, limits), and **Verify** (the audit's
checksums and its binding to the record). Gene rows open the Gene section.

### Prism (`features/prism`)
Routes table (how often the usual Excel→Prism routes change a conclusion on this study),
preview tables and per-gene figure (group means with CI), **Draft the Prism project** (a model
proposal, accepted like any other), **Send to Prism** (job: bundle zip download link, whether
Prism was launched), **Round trip** (pick the bundle; give the folder Prism saved into; job;
the changes come back as proposals with their consequences).

### Record (`features/record`)
The decision chain as a timeline (seq, card, option, actor icon human/agent/system, reason,
time, hash → prev hash, status applied/pending/rejected/stale; a carried entry is marked
**Carried**, with the earlier analysis's entry it names and whether it is found there). **Export the Analysis Record**
(job → download; record id, chain head, files). **Verify a record** (drop a zip → checksums,
chain, audit binding). Copyable `qpilot verify` / `qpilot rerun` commands.

### Agents (`features/agents`)
How to connect (`claude mcp add qpilot -- qpilot serve`, copy button), the tools (read / ask /
propose; none can decide a conclusion-changing choice), live list of requests waiting for a
person (same Approve / Turn down as Results) and recent agent entries from the chain and the
proposal inbox.

### Sheet check (`features/sheetcheck`) — global
origin/main's Spreadsheet Check (`qpcr/sheetcheck.py`): drop a lab's own ΔΔCq sheet (`.xlsx` /
`.csv`; kept by content, never edited) and qPilot recomputes it from its own Cq values: how many
fold changes reproduce, the first column and row that differ, the known slip that reproduces it
(an inverted sign, the exponent applied twice, statistics on fold changes …), and, compared with
a study (blind rule applies), the genes whose arithmetic reproduces but whose fold change
differs from qPilot's (a difference of method). The column mapping is a guess and says so until
a person confirms it (and may set any column first). Sample and group labels never come back
from the server. Method card: `methods/sheetcheck.md`.

### Instruments (`features/instruments`) — global
origin/main's instrument registry and hash-chained logbook (`core/instruments.py`): the
instruments, the age of their latest calibrations, open incidents, and whether each logbook's
chain verifies. **Waiting for you**: incidents an agent proposed (`qpcr_incident_log`), which only
a person confirms or turns down here; **Note what fixed it**; **Log an event** (calibration, part
change, service, move, note) and **an incident you saw** (confirmed, since a person logs it); the
logbook in chain order. **Read a run file** (`.eds`, QuantStudio/CFX exports, RDML): what it says
about the instrument (model, firmware, run state, calibration ages, pauses; serial numbers named,
never shown) with its G-INSTR lines, and which registered instrument it is, or "Which instrument
is this?" once (the answer is remembered locally; what the file states is logged). **Lookback**:
which of a study's conclusions used an instrument between two dates, and what leaving those runs
out changes (a job; writes nothing). Every write is `actor="human"`. Methods:
`methods/instrument_context.md`, `methods/lookback.md`.

### Settings (`features/settings`)
Model: provider (none / local OpenAI-compatible / Anthropic, from the environment), status and
reason, **Check connection**, **Test this model** (harness scorecard job: correct, invented
numbers, safety, fallbacks, latency). Autonomy (Suggest / Decide and tell me) with the policy
lines. Theme. Fresh demo. The never-does lines and the version.

## 5. Design system

* **Feel:** a calm instrument. Dense where scientists scan (tables, plates), generous where they
  decide (cards). Neutral surfaces, one teal accent, colour reserved for meaning.
* **Tokens** (`src/styles.css`): `bg`, `surface`, `surface-2`, `sunken`, `line`,
  `line-strong`, `fg`, `muted`, `faint`, `accent(-strong/-soft/-fg)`, `danger|warn|ok|info(-soft)`,
  conclusions `up|down|none`, verdicts `v-solid|v-caveats|v-depends|v-fragile|v-check|v-nocall`,
  levels `l-high|l-moderate|l-low|l-verylow`. Use the Tailwind utilities they generate
  (`bg-surface`, `text-muted`, `border-line`, `text-v-fragile`, …), never raw hex.
* **Type:** Inter Variable (UI), JetBrains Mono Variable (numbers in tables, hashes, ids,
  commands); `tabular` class on every column of numbers. Scale: 12 / 13 / 14 (body) / 16 / 20 /
  24 / 32.
* **Shape:** radius 8 (controls) / 12 (cards); 1 px `line` borders; shadows only for floating
  layers (popover, dialog, toast).
* **Meaning never by colour alone:** conclusions have arrows (▲ up, ▼ down, — no call),
  verdicts have a glyph + word, levels have a bar count (4/3/2/1) + word.
* **Numbers:** folds as `3.59×` (2 significant decimals ≥ 1, `0.57×` below), CIs `[2.42–5.33]`,
  p `0.003` / `< 0.001`, percentages of analyses `64 %`, counts with thin spaces `24 576`.
* **Motion:** 120–200 ms ease-out for state changes; layout animation for cards leaving the
  inbox; nothing moves under `prefers-reduced-motion`.
* **Accessibility:** WCAG AA contrast in both themes; every control reachable by keyboard with a
  visible focus ring; charts have `role="img"`, an `aria-label` summary and "View as table".
* **Responsive:** ≥ 1280 two/three columns; 1024–1280 two; 768–1024 one column, rail icons;
  < 768 read-friendly single column, rail as bottom bar, plate maps scroll horizontally.

### Keyboard

| Keys | Action |
|---|---|
| ⌘K / Ctrl K | Command palette: go to section, gene, card; actions (Propose, Run audit, Export) |
| ⌘J | Ask drawer |
| ⌘O | Open a file |
| g then d / c / r / a / p / e | Design / Curves / Results / Audit / Prism / Record |
| j / k | Next / previous card (inbox, Decision Cards) |
| a / e / x | Accept / Edit / Reject the focused proposal |
| [ / ] | Previous / next gene |
| ? | Shortcut sheet |

## 6. API conventions

* All JSON under `/api`; types generated from `qpilot/web/contract.py` (`npm run gen:api`).
* Errors: `{"error": {"code", "message", "details"}}`; codes used by the page: `no_token` (401),
  `not_found` (404), `blind` (403), `stale` (409, `details.head` is the current head),
  `studio` (409, a Studio refusal in words), `refused` (403, not allowed for this actor),
  `bad_request` (422), `too_large` (413), `cross_origin` (403).
* Writes carry `expected_head` (the head the view showed); the answer carries the new head.
* Slow work answers `202 {"job": JobView}`; follow with `useJob(id)`; the result is on the job.
* Query keys: `["system"]`, `["workspaces"]`, `["job", id]`, `["w", key, …]` — every query about
  a workspace starts with `["w", key]` so live events can invalidate it (see `src/api/live.ts`).

## 7. Who builds what

Twenty-five agents, each owning paths nobody else edits (the coordinator merges into `ui/one-page`).
API modules each define their own response models in `qpilot/web/contract_<area>.py`;
`contract.py` is the shared core (owner: **api**). Routers are discovered (one module per area).

| Agent | Owns |
|---|---|
| **api** | `qpilot/web/{contract,views,context,server,security,jobs,events}.py`, `routers/{system,workspaces,studio,results}.py`, `tests/web/test_{guard,workspaces,studio,results}*.py` |
| **api-audit** | `routers/audit.py`, `contract_audit.py`, `sim/src/qsim/app.py` + `app_lab.py` (adding `Screen.from_prepared`), `tests/web/test_audit*.py` |
| **api-files** | `routers/files.py` (Prism, record export, downloads, record verify), `contract_files.py`, `qpilot/web/folders.py`, `tests/web/test_{prism,record}*.py` |
| **api-ops** | `routers/ops.py` (agents, ask, model test, fresh demo), `contract_ops.py`, `qpilot/cli/*`, `sim/src/qsim/cli.py`, `tests/web/test_{agents,ask,cli}*.py` |
| **legacy** | the old pages until they are removed: `qpilot/{app,studio,app_state,studio_state}.py`, `sim/src/qsim/app_page.html`, `tests/app/**`, `tests/studio/test_studio_{app,demo_ui}.py`, `sim/tests/test_app.py`; new `qpilot/ai/suggest_only.py`; `tests/web/test_parity*.py`; the `gradio` dependency |
| **redteam** | `tests/web/test_redteam*.py` (adversarial tests; findings go to owners) |
| **science** | `tests/web/test_numbers*.py` (every number the API serves equals the engine's / CLI's) |
| **shell** | `frontend/src/{lib,shell}/**` (not `sections.ts`), `frontend/src/ui/**` except `ui/proposal/` |
| **insight** | `frontend/src/charts/**` except `plate/` and `curves/`, `frontend/src/test/recorded/**`, `features/results/**` |
| **home** | `features/home/**`, `features/settings/**` |
| **design** | `features/design/**`, `frontend/src/ui/proposal/**` (ProposalCard, reused by Curves and Prism) |
| **curves** | `features/curves/**`, `frontend/src/charts/{plate,curves}/**` |
| **record** | `features/record/**`, `features/agents/**` |
| **gene** | `features/gene/**` |
| **audit** | `features/audit/**` |
| **prism** | `features/prism/**` |
| **ask** | `features/ask/**` (the Ask drawer's content; keep `AskDrawer` props) |
| **e2e** | `frontend/e2e/**`, `frontend/playwright.config.ts` (Playwright + axe on the real seeded store) |
| **docs** | `README.md`, `docs/{studio,integration,agents}.md`, `THREAT_MODEL.md`, `THIRD_PARTY_NOTICES.md`, `CONTRIBUTING.md`, `demo/README.md`, `docs/user-guide.md` |
| **trace** | `qpilot/web/routers/trace.py`, `qpilot/web/contract_trace.py`, `qpilot/trace/**` (may port from branch `agents/trace`: `qpilot/qpcr/trace.py`, `schemas_trace.py`, influence), `tests/web/test_trace*.py`, `frontend/src/features/trace/**` |
| **claims** | `qpilot/web/routers/claims.py`, `qpilot/web/contract_claims.py`, `qpilot/claims/**`, `tests/web/test_claims*.py`, `frontend/src/features/claims/**` |
| **report** | `qpilot/web/routers/report.py`, `qpilot/web/contract_report.py`, `qpilot/report/**` (may port from branch `agents/report`), `tests/web/test_report*.py`, `frontend/src/features/report/**` |
| **history** | `qpilot/web/routers/history.py`, `qpilot/web/contract_history.py`, `qpilot/history/**`, `tests/web/test_history*.py`, `frontend/src/features/history/**` |
| **planner** | `qpilot/web/routers/planner.py`, `qpilot/web/contract_planner.py`, `qpilot/qpcr/layout.py` (new), additive changes to `qpilot/qpcr/plan.py`, `tests/web/test_planner*.py`, `frontend/src/features/planner/**` |
| **ux-review** | nothing in the repo: reviews merged builds in a browser and files issues to owners |
| **gate** | `qpilot/core/{rules,gate,card_kinds}.py`, `qpilot/qpcr/{gate_rules,run_links}.py`, `packs/`, `qpilot/web/routers/gate.py`, `qpilot/web/contract_gate.py`, `tests/gate/**`, `tests/web/test_gate*.py`, `frontend/src/features/gate/**` |
| **coordinator** | `docs/app.md`, `frontend/src/shell/sections.ts`, `frontend/src/api/{client,live,jobs}.ts`, `qpilot/web/routers/__init__.py`, `qpilot/web/static/` (built on merge), CI, merges |

Reusable UI primitives live in `src/ui/` (barrel `src/ui/index.ts`), charts in `src/charts/`
(barrel `src/charts/index.ts`), formatting in `src/lib/format.ts`. Use them; ask their owner on the
bus for what is missing (or build a local component in your feature folder and offer it up).
