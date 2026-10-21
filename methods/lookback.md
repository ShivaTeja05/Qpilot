# Method card: the Instrument Logbook (registry, incidents, lookback, position history)

**What it answers.** Three questions a scientist asks about an instrument, from the run files and a short logbook, without a 20-run baseline:

- *Have we seen this before, and what fixed it?* (incident memory)
- *Which of my results used the bad period, and does it change them?* (lookback)
- *Is it the machine or me?* (position history: does an odd well follow the instrument, or move with the samples?)

**References.** None of this is a published statistical method. The binomial test with a Bonferroni correction is textbook; the "examine the effect" wording echoes ISO/IEC 17025 clause 6.4.9, but qPilot makes **no** ISO 17025, CLIA or 21 CFR Part 11 claim. Research use only.

**Implementation.**

| Part | Module | Public API |
|---|---|---|
| Registry, logbook, inferred events, incidents, matcher | `qpilot/core/instruments.py` (domain-agnostic; never imports `qpilot.qpcr`) | `Registry` (`register`, `update`, `resolve`, `ask`, `remember`, `remember_alias`, `remember_serial`, `logbook`, `export`), `Logbook` (`append`, `append_many`, `events`, `incidents`, `head`, `verify`), `infer_events`, `log_typed`, `log_incident`, `confirm_incident`, `reject_incident`, `log_fix`, `match_incidents`, `event_view`, `proposed_window` |
| Lookback | `qpilot/qpcr/lookback.py` | `lookback`, `lookback_study`, `write_lookback`, `run_name_date`, `dated_runs`, `LookbackResult` |
| Position history | `qpilot/qpcr/position_history.py` | `position_history`, `runs_from_curves`, `runs_needed`, `adjusted_p`, `PositionReport` |
| Prose from facts | `qpilot/explain/lookback_text.py` | `lookback_text`, `position_text` (and the `*_tokens` forms); not registered as templates |

## Registry and logbook

| Item | Definition |
|---|---|
| Where | `$QPILOT_STUDIES_DIR/instruments/instruments.yaml` and `instruments/logbook/<instrument_id>.jsonl`. The folder name is not hex, so the study store never takes it for a study workspace |
| Registry file | Strict YAML: no aliases, no repeated keys, unknown fields refused, at most 1 MiB. Each entry: `display_name`, `make_model`, `location`, `shared`, `aliases`, `serials`. A serial or alias names one instrument only. Serial numbers must be quoted (an unquoted `0123` would be read as a number) |
| Linking a run | `resolve(summary)`: by the file's serial when it has one (an unknown serial is a new instrument, whatever its model string); otherwise by an alias, an identity string seen in an earlier file. No match gives `None`, and the app asks "Which instrument is this?" once (`ask`); `remember` stores the answer by serial, or by the file's identity strings |
| Events | `kind` in calibration, component_change, firmware_change, software_change, run_event, service, move, incident, fix, note, lookback; `source` in file, inferred, typed; `actor` in human, agent, system; `at` (when it happened, if known), `recorded_at`, `run_hash`, `wells`, `signature`, `payload` |
| Inferred from two successive files (`infer_events`) | a calibration's `performed_on` changed → `calibration` (dated by the new calibration date); a block, cover or optical-head serial changed → `component_change` (the payload names the component, never the serial); firmware or software changed → `firmware_change` / `software_change`. A value missing from either file infers nothing |
| From the current file alone | a run state other than complete, a pause, a lid or drawer opening, an abort or a power event → `run_event` with its cycle (`source` = file) |
| Chain | Each line's `hash` is the sha256 of the canonical JSON of the event without `hash` and without None fields (the proposal chain's rule); the first event links to the sha256 of the instrument id. `verify()` lists problems (link, hash, altered bytes, another instrument's entry, an incident rule broken) and never raises; reads and appends refuse a chain that does not verify. Size caps: 16 MiB per logbook, 64 KiB per event, 2,000 characters per typed note. Appends hold a file lock |

## Incidents and "seen before"

| Item | Definition |
|---|---|
| Logging | `log_incident(logbook, actor=..., wells=..., signature=..., run_hash=..., note=...)`. A person's incident is confirmed at once; an agent's (or the system's) is `proposed` |
| Confirming | `confirm_incident` and `reject_incident` take `actor="human"` only (checked by type, before any read); `log_fix` too. Replay checks the same rule, so an entry written around these functions is refused on append and reported by `verify` |
| Signature | `metric` (`plateau`, `cq_residual`, ...), `direction` (low, high), `error_code` (a vendor flag such as `PRFDROP`), `numbers`. No free text |
| Matcher (`match_incidents`) | Confirmed incidents only. A match is the same instrument and either an overlapping well with the same metric and direction, or the same error code (case-folded). Deterministic, no model. Most recent first; each record says "seen before" and whether a fix is on record |
| Typed text | An incident note or a fix is stored exactly as typed, for the person's own screen. `match_incidents` and `event_view` return only its length unless `include_text=True`; nothing in qPilot passes it to a model, and callers that hand events to an agent use the defaults |
| Proposed window | `proposed_window(logbook, incident)`: from the latest calibration or service entry before the incident to its first fix. A proposal for a person to edit |

## Lookback

| Step | Definition |
|---|---|
| Input | `runs`: run id → instrument id (the same run id in two studies is the same run); the instrument; a window `start`..`end` (whole days, inclusive; a date-time counts by its UTC date); optionally the studies to check and explicit run dates |
| Run dates | In this order: dates the caller gives; the UTC start date of a stored run context (`run_context.json` in the workspace); the date in the run name (`_20YYMMDD`). Each run reports its `date_source`. A mapped run with no date is listed as undated and is in no window |
| Before | The study's primary analysis on all its runs, with its robustness grid (the stored contrasts are checked against it: `baseline_matches_stored`) |
| After | The runs in the window removed from the per-well table, then `build_model`, `run_grid` and `summary` again; each gene's conclusion is its primary cell |
| k of N | N = conclusions before; k = genes concluded both times whose call (up, down, none) differs. Decided cards are not applied: the comparison is between primary analyses (`basis`) |
| A gene measured only in the window | **No longer concluded**: listed separately, not counted in k |
| A control-gene candidate measured only in the window | Analysed again with the other candidates (the engine needs every candidate in the matrix). This also derives the marker groups again; the result reports both group sizes and whether membership changed. The grid has fewer reference subsets, so its cells are not comparable one to one; k compares primary cells only |
| The grouping marker measured only in the window | "cannot evaluate: the grouping marker was measured in the window". Also refused: no control-gene candidate left, every run in the window, an unknown study, an input file that is missing or changed, and an engine refusal (with its message) |
| Writes | None. The curve cache is read when present and never filled. `write_lookback(logbook, result, actor)` appends one `lookback` event (window, the result's sha256, k, N and genes per study) |

**On the demo study** (all 64 plates mapped to one synthetic instrument; dates from the run names, 20 Feb – 18 Mar 2008; about half a second per study, two grids):

| Window | Plates in it | Result |
|---|---|---|
| 11 Mar 2008 | 8 target plates | changes 0 of 58 conclusions; 8 genes no longer concluded |
| 25–27 Feb 2008 | 13 target plates | changes 0 of 58; 13 no longer concluded |
| 28 Feb 2008 | ALUsq(Eurogentec) + 5 target plates | changes 0 of 58; 5 no longer concluded; 4 candidates |
| 3 Mar 2008 | HPRT1 + 2 target plates | changes 3 of 58 (CDKN3, IGSF4, NM23A); 2 no longer concluded |
| 20 Feb 2008 | SDHA(1), UBC(2) | changes 4 of 58 (CLSTN1, DPYSL3, EPN2, PLAGL1); groups 53/294 → 53/296 |
| 18 Mar 2008 | HMBS, NTRK1 | changes 5 of 58 (DPYSL3, PAICS, PDE4DIP, PLAGL1, SLC25A5); NTRK1 no longer concluded; groups 53/294 → 54/305; grid 186 → 90 cells |
| 22 Feb 2008 | MYCN(4), MRPL3, NHLH2 | cannot evaluate: the grouping marker was measured in the window |

On the demo a window of target plates alone can never change another gene's call: each plate holds one gene, and the groups depend only on the control genes and the marker. Only windows holding a control-gene plate (or the marker plate) can.

## Position history (on demand)

| Step | Definition |
|---|---|
| Residual | A well's Cq minus the median Cq of its replicate group (same sample, target and run). Groups with fewer than two wells with a Cq are skipped. Off: \|residual\| > 0.5 cycles |
| Base rate | The lab's own share of off wells over every residual given (all instruments pooled): its pipetting and replicate noise is the null |
| Test | Per instrument and position: x off of n residuals across runs; one-sided binomial P(X ≥ x \| n, base rate), Bonferroni over the positions tested on that instrument |
| Flag | Adjusted p < 0.05 **and** the off runs span at least two people or two plate layouts. A layout is which sample sat in which well (given, or fingerprinted from the run; the target is ignored) |
| Runs needed | The smallest k with positions × base rate^k < 0.05: the fewest runs in which a position off every time could beat chance. A position with fewer runs cannot be flagged |
| Answer | `follows_instrument` (a position is flagged); `not_enough_runs` (no position has the runs needed, or a position beats chance only with one layout and at most one person on record); `moves_with_samples` (positions had the runs needed and none beats chance) |
| Privacy | Operators are counted, never reported |

**Measured.** The plan's six-run StepOnePlus series (Zenodo 18006983) is not on disk, so its acceptance runs on a synthetic series built to the plan's measured numbers: 294 residuals, 85 off (28.9 %), 66 positions, each measured in four or five of the six runs. Nothing is flagged and the answer is "not enough runs yet (need ≈ 6)": 66 × 0.289⁶ = 0.038 < 0.05, while 66 × 0.289⁵ = 0.133; a position off in 3 of 3 runs has adjusted p = 1.0, as the plan reports. A planted −1.5-cycle offset at B3 and B4 across 8 runs (two people, a new layout every run) is flagged at exactly those two positions; an offset that moves at random is not flagged. On the demo the only replicates are the standards (960 residuals, base rate 4.8 %, 15 positions): the 15-copy standard's wells P14, P16 and P18 beat chance, but the same standard sits there on all 64 plates and no operator is recorded, so the answer is "not enough runs yet", not "follows the instrument". Low-copy scatter is a property of the sample, and the layout rule is what keeps it from being blamed on the instrument.

## What is not claimed

- An expired calibration is a fact plus its consequence, never an automatic exclusion, and nothing here says whether an expired optical calibration moves Cq at all (unknown; see the plan's §9).
- A lookback compares the primary analyses before and after; it does not re-apply decided cards, and the reduced grid of a window holding a control-gene plate is a different grid.
- Position history uses Cq residuals only; plateau and passive-reference levels are not yet used. Its normal answer is "nothing follows the instrument", which says where not to look, not what happened.
- Serial numbers and aliases never leave the machine: `Registry.export` and `Instrument.public` drop them and no event stores one. Pseudonymising them in an Analysis Record export is the record's job, not done here.
- Words: "the file says", "seen before", "follows the instrument", "changes k of N conclusions"; status words only.

**Validation.** `tests/core/test_instruments.py` (strict registry loading, alias memory, the block-swap acceptance, chain verification and tamper detection, concurrent appends, human-only confirmation, the B3/B4 "seen before" acceptance); `tests/engine/test_lookback.py` (synthetic cases for each gotcha; the demo windows against an independent recomputation, byte-determinism, nothing written); `tests/engine/test_position_history.py` (planted, moving and single-layout offsets, the six-run arithmetic, the demo standards).

**Licence.** Apache-2.0 (qPilot's own code).
