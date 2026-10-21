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

One hash-routed page. Global routes: `#/` (Open), `#/settings`. A workspace is either a Studio
**session** (`#/s/<session id>/<section>/…`, the session id is `input_sha256[:12]`) or a
**study** analysed outside one (`#/r/<study id>/<section>/…`; e.g. by `qpilot run` or an agent's
`qpcr_study`), whose results show straight away.

| Section | Route | Shown when | Data (API → service) |
|---|---|---|---|
| Open | `#/` | always | `GET /api/system`, `GET /api/workspaces`, `POST /api/workspaces` (upload: `rdml` + `sheet`, or `files` = instrument exports sorted by content → `qpilot.web.intake` + `io.connectors.materialise`), `POST /api/workspaces/demo`, `POST /api/demo/fetch` |
| Design (blind) | `…/design` | session | `GET /api/sessions/{sid}` (incl. `capture`: what an export was read as), `…/proposals?stage=design`, `…/plate`, propose/accept/edit/reject/bulk/confirm → `Studio.*` |
| Curves (blind) | `…/curves` | session, design confirmed | `…/proposals?stage=curves`, `…/plate` (calls, Cq, efficiency, R²), `…/curve?well=`, `…/curve-calls?gene=` → `Studio.propose_curves/curve/curve_calls` |
| Results | `…/results` | results visible | `GET /api/studies/{id}/results` (summary, rule, genes with robustness + confidence, the opt-in `axes`), `/flips`, `/cards`, decide/undo/turn down/explain → store + `core.decisions` + `ai.explain`; `…/proposals?stage=choices`, `POST /api/sessions/{sid}/propose/axis` → `Studio.propose_axis`; `GET /api/studies/{id}/import-trust`, `POST …/import-trust/decide` (session only) → `io.trust` + `Studio.decide_import_trust` (+ the `analyse` job for Cq only) |
| Controls | `…/gate` | results visible | `GET /api/studies/{id}/gate` (first run a `gate.run` job: 409 `loading` + the job) → `qpcr.gate_rules.run_gate` (rule pack `packs/research-default.yaml`) + `core.gate` (consequence test); `POST /api/studies/{id}/gate/cards/{card_id}/decide` (session only) → `Studio.decide_gate` (curve exclusions) + the `analyse` job |
| Gene | `…/gene/<GENE>` | results visible | `GET /api/studies/{id}/genes/{gene}` (qPilot contrast, robustness, confidence, cards affecting it) + audit gene views when an audit exists |
| Audit | `…/audit` | results visible | `GET|POST /api/studies/{id}/audit` (status / run), `/audit/overview|study|how|gene/{g}|analyses/{g}|effects/{g}|lab/{g}`, `POST /audit/whatif|samples` → `integration.simulator` + qsim `Screen`/`LabViews` |
| Prism | `…/prism` | session, results visible | `/prism/preview|routes|bundles`, `POST /prism/draft|send|roundtrip` → `Studio.preview_prism/propose_prism/send_to_prism/launch_prism/round_trip` |
| Record | `…/record` | always (empty until analysed) | `GET /decisions` (chain), `POST /record` (export → download), `POST /api/records/verify` → `core.record` |
| Agents | `…/agents` | always | `GET /api/agents` (MCP command, tools, pending requests, recent agent entries) |
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
  back), the session moves to another analysis of the file (`Studio._study`), whose design
  differs only in the wells left out. What a person decided on the earlier analysis's cards is
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
  and **Propose to stop testing them** goes back to the earlier analysis with its decisions. A
  study analysed outside Studio shows `qpilot run --efficiency all` instead. Method card:
  `methods/efficiency_model.md`.

### Controls (`features/gate`) — Run Gate
What the controls on each plate say, and whether any of it changes a call. The shipped rule pack
(`research-default`: G-TYPED, G-NTC-1, G-NAC, G-NRT, G-POS, G-STD, G-REP; thresholds and sources
in `packs/research-default.yaml`, science in `agent-bus/contracts/scientist-spec-gate.md`) is
evaluated on the study's wells; every rule that warns or fails and points at wells gets the
consequence test: the whole analysis grid is re-run without those wells and compared at the
analysis in use (each card's applied option, the planned one elsewhere).
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
| **gate** | `qpilot/core/{rules,gate,card_kinds}.py`, `qpilot/qpcr/gate_rules.py`, `packs/`, `qpilot/web/routers/gate.py`, `qpilot/web/contract_gate.py`, `tests/gate/**`, `tests/web/test_gate*.py`, `frontend/src/features/gate/**` |
| **coordinator** | `docs/app.md`, `frontend/src/shell/sections.ts`, `frontend/src/api/{client,live,jobs}.ts`, `qpilot/web/routers/__init__.py`, `qpilot/web/static/` (built on merge), CI, merges |

Reusable UI primitives live in `src/ui/` (barrel `src/ui/index.ts`), charts in `src/charts/`
(barrel `src/charts/index.ts`), formatting in `src/lib/format.ts`. Use them; ask their owner on the
bus for what is missing (or build a local component in your feature folder and offer it up).
