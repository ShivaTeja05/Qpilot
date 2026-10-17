# W2 — Run Gate and Lab Memory: one specification

Date: 17 October 2026. Audience: the two qPilot developers. Status: synthesis of six independent research notes (01, 02, 06, 09, 14, 15) that each arrived at the same two ideas from different corners of the niche, deepened with the primary sources they cite. Every threshold below carries its source number; every number that is an estimate is labelled as one. Product horizon: 6–18 months; nothing here is hackathon scope.

**One-paragraph summary.** Six researchers, looking at expression labs, assay designers, instrument physics, gene-therapy bioanalysts, journal reviewers and clinical QC labs, each concluded that research qPCR has controls on the plate but no *rules* for them, no *memory* of how an assay, an instrument or a reagent lot behaved last month, and no way to decide whether a failed control actually matters for the conclusion. Clinical labs solved this decades ago with typed controls, run-validity rules, Levey-Jennings charts and lot bridging [5][6][7], and sell it in closed middleware [58]; research tools have none of it. qPilot already computes, for every well of every plate, the per-well efficiency, Cq, N0 and melt data from raw curves and stores them in a re-runnable record. **Run Gate** evaluates named, sourced, lab-editable acceptance rules against each plate's typed wells and turns failures into Decision Cards whose recommendation ("repeat / rescue / ignore") is decided by whether the conclusion changes and what a repeat costs. **Lab Memory** turns the lab's own archive of records into *passports* for each assay, instrument and reagent lot, with control-chart trending, lot-change bridging and drift alerts. They are one system: the Gate's thresholds are learned from Memory, and Memory's alerts are delivered as Gate cards.

---

## 0. Terms used throughout (defined once)

- **RDML** — Real-time PCR Data Markup Language, the XML interchange format qPilot reads and writes; version 1.3 is the recommendation, 1.4 a candidate [47]. A file holds `experiment → run → react (well) → data (per target)` with per-cycle fluorescence (`adp`) and melt points (`mdp`).
- **Sample type** — the RDML `sample/type` enumeration: `unkn` (unknown), `ntc` (no-template control), `nac` (no-amplification control), `std` (standard of known quantity), `ntp` (no target present), `nrt` (minus reverse transcriptase), `pos` (positive control), `opt` (optical calibrator) [47]. Note: `ref` is **not** a sample type; it is a *target* type (`ref` = reference gene, `toi` = target of interest) [47]. Two sample booleans matter too: `interRunCalibrator` (a sample run on every plate to detect between-run differences) and `calibratorSample` (the sample results are rescaled to) [47].
- **Cq** — quantification cycle, the cycle at which fluorescence crosses a threshold; depends on baseline and threshold choices [3]. **N0** — starting quantity in fluorescence units, computed by LinRegPCR as N0 = Nq / E^Cq where Nq is a common threshold and E the per-target mean efficiency [45]. **E** — amplification efficiency per cycle, 2.0 = 100 %.
- **LinRegPCR** — the per-well baseline and efficiency method qPilot runs through the MIT-licensed `rdmlpython` [46][45]. It writes back `N0`, `ampEff`, `ampEffSE`, `excl` (exclusion reasons) and `note` per well [47].
- **Control material** — a physical thing run repeatedly: a positive-control plasmid or gBlock, an inter-run calibrator (IRC) cDNA pool, a standard dilution series, an NTC.
- **Lot** — a manufacturer's batch of a reagent (primers, probe, master mix, RT enzyme, standard, control material). RDML has no lot field anywhere [47]; see A.5.
- **Levey-Jennings chart** — a time plot of a control's value with lines at the mean ± 1, 2, 3 standard deviations (SD), limits set from the lab's own first ≥ 20 measurements over ≥ 10 days [6]. **Westgard rules** — named tests on such a chart (e.g. 1_3s = one point beyond ± 3 SD) [5].
- **Robustness grid** — qPilot's existing engine that re-runs a study under every reasonable combination of analysis choices and reports how many agree with the answer (brief). **Decision Card** — qPilot's existing unit of a human judgment call: evidence, options, per-gene consequences, recommendation, logged reason (brief). **Analysis Record** — RDML + results + hash-chained decision log (brief).
- **Gate** — a set of rules evaluated per plate and per target that yields a status. **Passport** — a versioned summary of everything the lab's records say about one assay, instrument, lot or control material.
- **BLOD / BLOQ** — below limit of detection / quantification [8]. **TOST** — two one-sided tests, the standard equivalence test ("is the difference inside ± margin?").

---

## A. The unified data model

### A.1 Objects and keys

Everything is derived from two inputs qPilot already has: the RDML files of a study and the Analysis Records qPilot wrote for them. Lab Memory adds one side-car (A.5) that the lab types once per run or per lot.

| Object | Key | Built from | Notes |
|---|---|---|---|
| `Run` | `run_hash` = SHA-256 of the canonicalised RDML run element (sorted attributes, per-cycle floats rounded to 6 significant digits) | RDML `run` | Also stores `instrument` (free text), `dataCollectionSoftware`, `runDate`, `pcrFormat`, `cqDetectionMethod`, `backgroundDeterminationMethod` [47] and the `record_root_hash` of the Analysis Record it belongs to. |
| `Well` | (`run_hash`, `react.id`, `target_id`) | RDML `react/data` | Row/column from `pcrFormat`; sample id, sample type, `quantity` (value, unit) for `std`, `interRunCalibrator`, `calibratorSample` [47]. |
| `WellFacts` | same as Well + `engine_version` | LinRegPCR + MCA outputs | `cq`, `N0`, `ampEff`, `ampEffSE`, `excl`, `note`, `bgFluor`, `bgFluorSlp`, `quantFluor`, plateau height, window-of-linearity cycles, `meltTemp`, peak width, extra-peak fraction [45][47]; plus Gate-specific derived facts (A.6). |
| `Assay` | `assay_id` (A.2) | RDML `target` | Sequences, `commercialAssay`, dye, expected `amplificationEfficiency`, `amplificationEfficiencySE`, `meltingTemperature`, `detectionLimit` [47]. |
| `Instrument` | `instrument_id` (A.2) | RDML `run/instrument` + lab profile | Make, model, serial (typed once), block format, calibration events. |
| `LotRecord` | `lot_id` = `<kind>:<manufacturer>:<order>:<lot>` | side-car | kind ∈ {primer, probe, assay_mix, master_mix, rt_enzyme, standard, control_material, extraction_kit}; dates received/opened/expiry; linked `assay_id` where applicable. |
| `ControlMaterial` | `control_id` | side-car or inferred | What physical material a `pos` / IRC / `std` sample is; a `pos` sample name is not enough on its own (see F.1). |
| `Series` | (`metric`, `assay_id`, `control_id`, `instrument_id`) | WellFacts over time | The unit of trending; one point per run (A.4). |
| `Event` | `event_id` | side-car, vendor reports, engine | lot_change, calibration, lamp/LED replacement, service, software_version_change, operator_change, rule_pack_change. Drawn on charts; used by change-point tests. |
| `RulePack`, `Rule`, `RuleEval` | `pack_hash`, `rule_id` | YAML (B.0) | Every evaluation stores the pack hash, rule id, inputs, numbers, verdict. |
| `Card`, `Decision` | existing qPilot objects | Gate and Memory | Cards carry `rule_ids`, `consequence` (C.2), `cost` (C.3), options, recommendation; decisions carry actor, option, reason, hash. |
| `Passport` | (`kind`, `key`, `version`) | all of the above | kind ∈ {assay, instrument, lot, control_material}; a versioned JSON document (A.3–A.5) regenerated deterministically from the store; `passport_hash` is written into every Analysis Record that used it. |

### A.2 Identity, because nothing in a vendor export is a stable key

- **Assay identity.** `assay_id = "seq:" + SHA-256(upper(fwd) + "|" + upper(rev) + "|" + upper(probe1 or "") + "|" + upper(probe2 or ""))` when RDML `target/sequences` is present [47]. Else `"com:" + company + ":" + orderNumber` from `commercialAssay` (TaqMan assay IDs are stable and come with a context sequence, so the context-sequence hash can be used when the vendor withholds primer sequences [1]). Else `"name:" + target.id`, which triggers a one-time **reconciliation card** ("targets `GAPDH`, `Gapdh_2`, `GAPDH-new` appear in 14 runs; same assay?"), whose answer is stored as an alias table. Most vendor exports carry no sequences (note 02 finding), so the alias table and the lot side-car are where identity actually lives; the registry prompt asks for sequences once per new name.
- **Instrument identity.** RDML `run/instrument` is free text and inconsistent across exporters [47]. The lab profile maps observed strings to `instrument_id`; the first unmapped string raises a card ("`QuantStudio 5 (278880123)` — which instrument is this?"). Serial numbers never leave the machine.
- **Control-material identity.** A sample typed `pos` or flagged `interRunCalibrator` is matched to a `control_id` by (sample name, assay, lab alias table). First occurrence → prompt. Without this mapping a Series cannot be formed; the chart shows "unmapped control" rather than guessing.
- **Lot identity.** Only from the side-car (A.5). Date ranges per lot allow back-filling runs that were not tagged at the time, with the fact flagged `lot_source = inferred_from_dates`.

### A.3 Assay passport (per `assay_id`, optionally split per instrument and per chemistry)

Computed deterministically from every run containing the assay. All statistics carry n, the engine version and the date range.

| Field group | Fields | Method and source |
|---|---|---|
| Identity | sequences or context-sequence hash, species/accession (registry), amplicon length, dye, commercial order number | RDML target [47]; MIQE 2.0 section 1 items [1] |
| Efficiency, per run | per-target mean LinRegPCR E with SD and n of valid wells; LinRegPCR excludes no-amplification wells, then wells flagged no-plateau, baseline error, or efficiency outlier (skewness + Grubbs) before the mean [45] | LinRegPCR [45][46]; MIQE 2.0 endorses the mean of individual-curve efficiencies for standardised experiments [1] |
| Efficiency, learned interval | median and robust SD (MAD × 1.4826) of per-run mean E over the first ≥ 10 runs; thereafter the control-chart limits (B.2). Stored separately per instrument because E is instrument-dependent but stable on one platform [42][44] | Svec 2015 [42]; Rogers-Broadway 2015 [44] |
| Efficiency, standard-curve events | whenever a run holds ≥ 3 `std` levels for the assay: slope, intercept, E_std = 10^(−1/slope) − 1, R², CI from replicate resampling, number of levels and replicates per level; stored **separately** from LinRegPCR E with `amplificationEfficiencyMethod` label, because the two are different quantities with different biases (standard-curve E runs high with pipetting error; per-curve E runs low with inhibitors) [1][43] | MIQE 2.0 [1]; Hastings 2021 [43] |
| Calibrators and controls | per run: Cq and N0 of every `pos`, IRC and `calibratorSample` well for this assay, with `control_id` | RDML booleans [47] |
| Melt fingerprint | per instrument and chemistry: median Tm, IQR, peak width, shoulder/extra-peak frequency, median normalised −dF/dT curve; LinRegPCR MCA classifies a peak within 1.0 °C of the expected Tm as product (user-adjustable), minimum peak height 0.05 of summed peak heights, minimum width 5 °C [45] | rdmlpython MCA [45][46] |
| NTC behaviour | fraction of `ntc` wells amplifying (engine call, not vendor "Undetermined"), their Cq distribution and Tm (dimer Tm is usually below product Tm), the Cq gap to the lowest `unkn` per run | MIQE 2.0 five-cycle rule [1]; Thermo NTC spec Ct > 38 [23]; PrimePCR redesigns any assay with NTC Cq < 35 [24] |
| LOD / LOQ | from standard-curve events with ≥ 3 replicates per level: discrete LOD = lowest level with ≥ 95 % detection; LOQ = lowest level with CV of back-calculated copies < 35 %; curve-fitted variants and effective LOD for n replicates, 1 − (1 − p)^n [21]; Poisson floor 3 copies [3]; Ma-style LOD = lowest level positive in all replicates across runs [8] | Klymus 2020 [21]; Forootan 2017 [21b]; Ruiz-Villalba 2021 [3]; Ma 2021 [8] |
| Single-copy anchor | if a `std` series in copies exists: the Cq that corresponds to 1 and 10 copies at the passport E (used by the Poisson replicate tolerance, B.1 G-REP) | derived; Ruiz-Villalba: 10 copies ≈ Cq 35 at E 1.9 [3] |
| Lot timeline | which `lot_id`s (primer, probe, master mix) were in use per run; per-lot summaries of E, Tm, control Cq; bridge verdicts (B.3) | side-car |
| Flags history | counts of LinRegPCR `excl`/`note` reasons per run (no amplification, no plateau, baseline error, efficiency outlier) [45] | rdmlpython |

The passport is also **written back** into the RDML `target` of every record qPilot produces: `amplificationEfficiency`, `amplificationEfficiencySE`, `amplificationEfficiencyMethod`, `meltingTemperature`, `detectionLimit` — all existing RDML fields [47] — so the assay's expected behaviour travels inside the standard.

### A.4 Instrument passport (per `instrument_id`)

| Field group | Fields | Source |
|---|---|---|
| Identity and events | make, model, block format, serial (local only); calibration dates (background, ROI/uniformity, dye, RNase P verification), lamp/LED replacement, service visits — typed or imported from the vendor's maintenance report; Thermo cadence: ROI/background/uniformity/dye "semi-annually", background "monthly", RNase P "as needed" and after lamp replacement; QuantStudio 3/5: ROI/uniformity every two years recommended [27][28] | lab profile; vendor guides |
| Per-run control Cq | one Series per (assay, control_id): Cq and N0 of `pos`/IRC wells | A.3 |
| Per-run NTC | amplification rate, Cq, Tm of `ntc` wells across all assays (a p-chart, B.2) | A.3 |
| Per-run baseline | distribution of LinRegPCR `bgFluor` (baseline level) and `bgFluorSlp` (baseline slope) across wells; plateau heights; fraction of wells with baseline error | rdmlpython [45][47] |
| Per-run efficiency | per-assay mean E on this instrument (the instrument-specific learned interval) | [42][44] |
| Uniformity | from any run with ≥ 24 technical replicates of one sample (verification plates, `ds_380`-like layouts): replicate SD of Cq, edge index (median residual of outer rows/columns vs interior), Moran's I of within-replicate-group residuals (note 06 Plate Residual Map, when built) | Thermo RNase P criterion [(Cq_A − 3σ_A) > (Cq_B + 3σ_B)] with 5,000 vs 10,000-copy groups, which the vendor software evaluates after auto-omitting wells [27]; Bio-Rad "2-fold discrimination with 99.7 % confidence" [30] |
| Verification-plate re-analysis | per plate: vendor criterion recomputed with and without omitted wells, position map, slope/intercept, replicate SD; trended over years | note 06 D5; [27][30] |
| Between-instrument offsets | log(F)/log(E) Cq-equivalent plate/instrument factors from studies run across instruments (B.4) | Ruijter 2015 [38] |

### A.5 Lot passport and the side-car schema (RDML has no lot fields)

Confirmed against the RDML 1.4 candidate schema: no element name contains "lot", "batch", "barcode" or "reagent"; the only serial is the file publisher's `serialNumber` [47]. The only generic hooks are `sample/annotation{property,value}`, `documentation`, `experimenter`, free-text `description`, and the `cdnaSynthesisMethod{enzyme, primingMethod, dnaseTreatment}` block [47]. Therefore:

**Side-car file (authoritative, local).** `labmemory/run_meta/<run_hash>.yaml`, written by a 10-field prompt at import (defaults carried forward from the previous run on the same instrument) or by CSV/ELN import:

```yaml
schema: qpilot.run_meta/1
run_hash: "sha256:…"
instrument_id: "qs5-main"           # lab alias, mapped from RDML run/instrument
operator: "AB"                      # optional
plate_barcode: "P-2026-0417"        # optional
lots:
  master_mix:   {manufacturer: "Thermo", order: "4444557", lot: "2611045"}
  rt_enzyme:    {manufacturer: "Bio-Rad", order: "1708891", lot: "64515012"}
  rt_batch_id:  "RT-2026-10-02"     # the lab's own cDNA batch
  per_assay:                        # keyed by assay_id or alias
    "seq:3f9a…": {primer_lot: "IDT-1234567", probe_lot: null, assay_mix_lot: null}
    "com:Thermo:Hs00174131_m1": {assay_mix_lot: "P2401123"}
  standard:     {control_id: "IL6-gBlock-v2", lot: "G-2026-03", nominal_copies_per_ul: 1.0e6}
  control_material:
    - {sample_name: "POS_pool_A", control_id: "cDNA-pool-A", lot: "2026-02-14"}
notes: ""
```

and `labmemory/lots.jsonl` (one `LotRecord` per line: kind, manufacturer, order, lot, received, opened, expiry, storage, linked assay_id, `bridge_status`, `retired`). Every record stores the SHA-256 of the side-car it used, so the record stays re-runnable even if the side-car is later edited.

**Where the fields come from, in order of preference:** (1) the side-car; (2) RDML `sample/annotation` pairs written by qPilot itself using namespaced property names (`qpilot:lot.master_mix`, `qpilot:lot.primer`, `qpilot:control_id`, `qpilot:spike_copies`, `qpilot:instrument_id`) — this is legal RDML today and survives round-trips through RDML-aware tools [47]; (3) vendor export headers (QuantStudio exports carry instrument serial and block type; CFX exports carry the instrument name) via the vendor-capture roadmap; (4) date-range inference from `lots.jsonl`, flagged as inferred.

**RDML extension path.** Propose to the RDML consortium (GitHub `rdml-schema`, MIT [47]) a `reagent` element for v1.5, on the model of the existing `commercialAssay`:

```xml
<reagent id="mm-2611045">
  <type>masterMix</type>         <!-- masterMix | primer | probe | assayMix | rtEnzyme | standard | controlMaterial | extractionKit -->
  <manufacturer>…</manufacturer> <orderNumber>…</orderNumber> <lot>…</lot>
  <receivedDate>…</receivedDate> <expiryDate>…</expiryDate>
</reagent>
<!-- referenced by run/reagentRef, target/reagentRef and sample/reagentRef -->
```

plus `run/instrumentSerial` and `run/plateBarcode`. Until accepted, qPilot writes the same facts as `annotation` pairs and keeps the side-car authoritative. MIQE 2.0 asks for lot numbers of RT reagents and kits and for verification "when changing batches" [1], so the extension has a reporting rationale, not only a qPilot one.

**Lot passport fields:** lot identity and dates; assays and runs that used it; for each Series the segment statistics under this lot (mean, SD, n) vs the previous lot; change-point and bridge verdicts (B.3); `retired` flag and reason.

### A.6 How it is built from a folder of RDML files plus Analysis Records

```
qpilot memory build [--workspace DIR] [--since DATE] [--rebuild]
```

1. **Discover.** Walk the workspace for `*.rdml` and Analysis Records (records are preferred: they already hold LinRegPCR outputs, the decision log, the rule-pack hash and the side-car hash). Dedupe by `run_hash`; a vendor re-export of the same run with different processing produces a different hash and a provenance note (the note 06 "is this curve raw?" guard runs here: baseline-subtracted exports are marked and excluded from efficiency series).
2. **Analyse what is not yet analysed.** Runs without WellFacts for the current engine version go through `rdmlpython` LinRegPCR (`pcrEfficiencyExl=0.05`, `excludeNoPlateau=True`, `excludeEfficiency="outlier"`, `excludeInstableBaseline=True`, as the consortium's own Vermeulen test script does [46]) and MCA.
3. **Type and map.** Read sample types, `quantity`, `interRunCalibrator`, `calibratorSample`, target types [47]. Apply alias tables; queue reconciliation cards for unmapped assays, instruments and control materials. Untyped plates are marked "no gate possible" (B.1 G-TYPED).
4. **Derive Gate facts per well and per target** (B.1 needs them): engine amplification call; Cq gap NTC→lowest unknown; NRT→RT gap; melt class; replicate range and Poisson tolerance; KOD z-score; adjacency to high-copy wells; standard-curve statistics.
5. **Form Series** (A.1) and recompute passports whose inputs changed. Passports are pure functions of the store: `rebuild` must reproduce byte-identical JSON (acceptance test).
6. **Evaluate trending rules** (B.2) on each updated Series; emit Events and Cards.
7. **Write** passports (JSON, versioned) and a `memory_manifest.json` (hashes of every input and output) into the workspace; link `passport_hash` into subsequent Analysis Records.

Incremental runs touch only changed Series. A 2,000-plate archive is ~2,000 × 384 wells × ~45 cycles ≈ 35 M floats, which fits in a few hundred MB of parquet and runs LinRegPCR in minutes to an hour on a laptop (estimate; the web-LinRegPCR paper reports per-run timing, not archive timing [45]).

### A.7 What is stored locally and never leaves the machine

- `labmemory/labmemory.sqlite` — tables `runs`, `wells`, `well_facts`, `assays`, `assay_aliases`, `instruments`, `control_materials`, `lots`, `run_lots`, `events`, `series`, `series_points`, `rule_packs`, `rule_evals`, `cards`, `decisions`, `passports`, `manifest`. SQLite is chosen for single-file, zero-server, transactional, agent-queryable (read-only connection for MCP) storage; the existing on-disk workspace locks (brief) cover concurrent human + agent writes.
- `labmemory/curves/<run_hash>.parquet` — per-cycle fluorescence and melt arrays (columns: react_id, target_id, cycle/temperature, fluor), so charts and re-analysis never re-parse XML.
- `labmemory/passports/<kind>/<key>/<version>.json`, `labmemory/run_meta/*.yaml`, `labmemory/lots.jsonl`, `labmemory/rule_packs/*.yaml`, `labmemory/memory_manifest.json`.
- Nothing is transmitted. The only outbound path is an explicit `qpilot memory export --anonymised` (assay hash, chemistry, instrument family, n, E distribution, Tm, NTC behaviour; no serials, no operators, no sample names) for the opt-in commons already on the roadmap. Serial numbers, operators and barcodes are excluded from every export by schema, not by convention.
- Everything is domain-agnostic at the core: the store knows "control material", "series", "rule", "passport"; the qPCR plugin supplies the metrics. A plate reader plugin would reuse the tables unchanged.

---

## B. The rule pack

### B.0 Rule-pack format

A rule pack is a YAML file, versioned, hashed into every record that used it. Rules are declarative so that an auditor (or the agent) can read them without reading Python. Thresholds ship as *examples with sources* and are lab-editable; editing creates a new pack version and a `rule_pack_change` Event.

```yaml
pack: research-default
version: 0.3
label: "Research use; lab-defined rules. Not clinical validity rules."
rules:
  - id: G-NTC-1
    name: "NTC amplification within k cycles of the lowest unknown"
    keys_on: {sample_type: ntc, scope: [plate, target]}
    needs: [engine_call, cq, melt_class, lowest_unknown_cq]
    params: {k_cycles: 5, melt_tolerance_c: 1.0}
    statement: "An unknown is considered positive only if its Cq precedes the NTC's by ≥ k cycles; NTC product with Tm within ±1 °C of the assay's product Tm is a contamination candidate, lower Tm is a dimer candidate."
    sources: [1, 23, 24, 36, 45]
    severity: {contamination_candidate: fail, dimer_candidate: warn}
    consequence_scope: "all unkn wells of this target on this plate whose Cq is within k cycles of the NTC Cq"
    default_action: card
```

Fields: `keys_on` (sample types and scope), `needs` (evidence facts; a rule with missing evidence returns `not_applicable`, never `pass`), `params` with defaults, `statement`, `sources`, `severity`, `consequence_scope` (which wells/targets/samples a failure taints — this drives C.2), `default_action` ∈ {log, card, invalidate_plate}. `invalidate_plate` is used only in packs that copy a regulatory SOP (B.5) and is always a Human-only decision in qPilot (D.4).

Packs shipped: `research-default` (expression work), `core-facility` (UC Davis-style [31]), `cgt-biodistribution` (Ma 2021 / FDA LTFU [8][9]), `edna-lod` (Klymus [21]), `rare-target` (EuroMRD-style [17][18][19]). Every pack file begins with the research-use banner.

### B.1 Gate rules (evaluated per plate, per target, at import and on demand)

Legend: *keys on* = RDML sample type(s); *needs* = evidence facts; *threshold* = shipped default with source; *failure means* = what is affected in conclusion terms.

**G-TYPED — are there typed controls at all?**
Keys on: presence of any `ntc`, `nrt`, `pos`, `std`, `interRunCalibrator` on the plate. Needs: sample types. Threshold: none. Failure means: no gate is possible; the plate is marked "ungated" loudly in the record and on the study page, and the "type your controls" prompt is shown once per plate layout and remembered. Rationale: NTC values are "often hidden" and NRT controls essentially unused in audited papers [52]; a silent gate would hide exactly that.

**G-PROV — are the curves raw?**
Keys on: all wells. Needs: per-cycle data. Threshold: ground-phase offset and subtraction-footprint tests (note 06 D1). Failure means: no per-well efficiency rule (G-EFF, G-REP's KOD, G-STD's E comparison) may run; the Gate reports those rules `not_applicable (processed input)`; a card offers "re-export raw" instructions per vendor.

**G-NTC-1 — NTC amplification relative to unknowns.**
Keys on: `ntc` (and `ntp`). Needs: engine amplification call per well (not the vendor's "Undetermined"), Cq, melt Tm class, lowest `unkn` Cq for the target on the plate. Thresholds: MIQE 2.0 — "an unknown sample should be considered positive only if its Cq precedes that of the negative control by at least 5 cycles" [1]; Thermo TaqMan spec "NTC background: Ct > 38.0" [23]; PrimePCR redesigns an assay whose NTC Cq < 35 [24]; CDC-style IFU: any NTC growth curve invalidates the run [32]; Ma: in sample analysis ≥ 2/3 of NTC wells BLOD, in validation all [8]. Melt class: product peak within ±1.0 °C of expected Tm (LinRegPCR MCA default) = contamination candidate; lower-Tm peak = primer-dimer [45]; the 5–10 °C lower dimer heuristic is practitioner lore [36]. Failure means: every `unkn` well of that target on that plate whose Cq is within k cycles of the NTC is **tainted** (its positive call and its quantity are not interpretable); wells more than k cycles earlier are unaffected; a contamination candidate additionally raises the plate-level question of the source (aerosol of the same amplicon affects later plates too — the p-chart in B.2 is the cross-run check).

**G-NAC — no-amplification control amplifies.**
Keys on: `nac`. Needs: engine call. Threshold: any amplification = fail [32] (by analogy; `nac` is rare in research). Failure means: signal in that channel is not amplification-dependent (probe degradation, dye artefact); all wells of the target on the plate are tainted.

**G-NRT — genomic DNA contribution.**
Keys on: `nrt` paired with the same sample's `unkn` well for the same target. Needs: both Cqs, E. Threshold: ΔCq(NRT − RT) ≥ 5 cycles by the same MIQE 2.0 logic [1] (the estimated gDNA fraction is E^(−ΔCq): at E 1.9 and ΔCq 5, ≈ 4 %); PrimePCR's own gDNA control uses "Cq < 35 = gDNA contamination" but only for that assay [25]; MIQE 2.0 says no-RT is "desirable, but no longer essential" once a sample is shown DNA-free [1]. Failure means: for intron-spanning assays, minor; for assays with intron-less pseudogenes or single-exon targets, the sample's quantity for that target carries a gDNA component up to the estimated fraction; the card shows the fraction and whether subtracting it changes the group comparison.

**G-POS — positive control window.**
Keys on: `pos`, and `interRunCalibrator` samples. Needs: Cq (and N0), `control_id`, passport Series for (assay, control_id, instrument). Threshold: absolute window from the lab (IFU-style: TaqPath positive control ≤ 37 [33]; PrimePCR "positive PCR control Cq ≥ 30 = poor PCR performance" [25]) **or**, preferred, the learned Levey-Jennings limits (1_3s on this run, B.2). Failure means (UC Davis rule, copied for cores): "If any positive control failures occur, all samples associated with the control should be considered invalid" [31] — in qPilot terms, every `unkn` well of that assay on that plate is tainted and the plate's quantities cannot be compared to other plates until a rescue (B.4 run factor) or repeat; `pos` must be mapped to a `control_id` or the rule is `not_applicable`.

**G-IPC — internal/extraction control and spike recovery (sample-level).**
Keys on: `unkn` wells carrying `qpilot:spike_copies` or a sample annotated as internal control. Needs: observed vs nominal copies (needs a `std` curve on the plate) or IPC Cq vs its window. Thresholds: Ma — spiked third well must recover ≥ 55 % of nominal, else re-analyse at 1/4 or 1/10 input [8]; FDA shedding guidance asks for a spiked parallel sample when diluting [12]; ICH S12 asks for spike-and-recovery per matrix [11]; IFU analogues: TaqPath MS2 ≤ 32 [33], CDC RP < 40 [32]. Failure means: **that sample** (all its targets on the plate) is flagged inhibited; its negatives are not interpretable as negatives (a false "BLOD"); other samples unaffected.

**G-STD — standard curve acceptance.**
Keys on: `std` wells with `quantity` [47]. Needs: ≥ 3 levels, per-level replicates, Cq, LinRegPCR E of the same wells. Thresholds (pack-dependent):
- `research-default`: E 90–110 % (Ma; Thermo spec 90–110 % across 5 logs [8][23]); Bio-Rad's guide uses 90–105 % and R² > 0.980 [26]; UC Davis: "No single efficiency … has been set as a limit … although 90 % or greater is an accepted norm" [31]; MIQE 2.0: ≥ 3 replicates per dilution step over 4–5 orders of magnitude with a confidence interval on E, and E > 100 % is a pipetting signature [1]; ICH Q2(R2) asks for ≥ 5 concentrations for linearity [77]; Svec: with single wells the 95 % CI of E can be ± 8.3 %, across 16 plates ± 42.5 %; triplicates give ± 2.3 % [42].
- `cgt-biodistribution` (Ma Table 4): R² ≥ 0.980; E 90–110 %; ≥ 8 non-zero levels in duplicate (sample runs) / ≥ 7 (validation); duplicate Ct %CV ≤ 2.0 %; back-calculated quantity within ± 25 % of nominal (± 45 % between LLOQ and the lowest QC) for ≥ 75 % of levels and a minimum of six/seven; if LLOQ or ULOQ fails, the next level becomes the plate-specific limit if the curve still passes; QC sets per plate: ≥ 50 % per level and ≥ 67 % overall with Qty %CV ≤ 25 % and %RE ± 25 % (± 45 % at the lowest) [8].
- `rare-target` (EuroMRD 2007): ≥ 3 points, ≥ 2 logs, slope −3.1 to −3.9, correlation ≥ 0.98; quantitative range requires replicate ΔCt ≤ 1.5, all Ct ≥ 3.0 below the lowest background Ct, and 2.6–4.0 cycles per 10-fold step (0.5–1.5 per 2-fold) [17].
- `edna-lod` (Klymus): standards in ≥ 3 (ideally 8–24) replicates per level; LOD = lowest level with ≥ 95 % detection; LOQ = lowest level with CV < 35 % of back-calculated copies; outlier flag at Cq < 90 % or > 110 % of the level's median, flagged not removed; effective LOD for n field replicates 1 − (1 − p)^n [21].
Also computed on every standard-curve plate: the gap between E_std and the mean per-well E of the same wells; MIQE 2.0 explains that pipetting error pushes E_std above 100 % while inhibitors raise E_std but lower per-curve E [1]. Failure means: in absolute quantification, every `unkn` quantity on the plate is uninterpretable (pack action `invalidate_plate` in `cgt-biodistribution`, with Ma's "repeat the run; second consecutive failure → escalate" [8] rendered as an escalation card); in relative quantification, the curve is only an efficiency estimate and the failure demotes the assay's efficiency source in the robustness grid.

**G-EFF — per-target efficiency and Tm against the passport.**
Keys on: all wells of the target (LinRegPCR mean over valid wells). Needs: G-PROV pass; passport learned interval (A.3) on this instrument; n ≥ 10 runs or the rule reports `provisional`. Thresholds: per-run mean E outside the passport's 1_3s limits (B.2) → fail; Tm of product peaks outside expected ± 1.0 °C [45] → warn; instrument offsets of Tm (e.g. 83.1 vs 84.6 °C across two cyclers, note 02 example) are expected and absorbed by the per-instrument fingerprint. Before 10 runs, the textbook band (90–110 %) is used and labelled as such. Failure means: the target's quantities on the plate rest on an efficiency unlike the assay's history (inhibition, wrong lot, wrong mix); affects every sample of that target; the card offers "use passport E / use plate E / exclude target on this plate" as robustness options.

**G-REP — technical replicate disagreement, Poisson-aware.**
Keys on: `unkn`, `pos`, `std` groups of ≥ 2 technical replicates. Needs: N0 (efficiency-corrected), Cq, estimated copies N, per-well E. Method:
1. Expected replicate tolerance on Cq from two error sources: pipetting (Ruiz-Villalba: a 15 % pipetting error at E 1.9 gives a Cq range of 0.5 cycles at all inputs) and Poisson sampling (variance = mean; "already below 100 target copies per reaction, the Cq variation due to Poisson sampling becomes larger than the pipetting error"; at 10 copies SD 3.3, CV 33 %) [3]. qPilot's tolerance for the replicate *range*:
   tol_Cq(N) = 2.1 / ln(E) × √(0.15² + 1/N),
   calibrated so that tol → 0.5 cycles at high copy number (matching the common 0.5-cycle rule) and ≈ 2 cycles near 3 copies (matching "for samples with Cq values up to 35 … a variation between technical replicates up to two cycles should be considered acceptable" [3]). N comes from the passport's single-copy anchor or a standard curve; without either, the fallback is the published Cq-tiered table (0.5 cycles at Cq 25–31 rising to 1.9 at Cq 35) [35], labelled as a fallback.
2. Kinetic outlier evidence: each well's LinRegPCR efficiency compared with the target's distribution (Bar 2003 KOD: efficiency of the test sample vs the mean of a training set, P = 0.05, detects outliers of 1.3–1.9-fold in quantity [40]; Tichopad's amplification-compatibility test is the same idea with a z-score on fitted parameters [41]); LinRegPCR's own `excl`/`note` reasons (no plateau, baseline error, efficiency outlier by skewness + Grubbs) [45].
3. Classical fallbacks offered, never default: fixed 0.5 / 1.0 / 1.5 Ct rules [36][37], Promega's SD > 0.5 [34], Grubbs.
Failure means: only the affected sample × target. The consequence test (C.2) is run under keep / drop well / drop sample; the Gate never drops silently. Vendor-flag folklore ("dropping replicates in more than 5–10 % of wells is a sign of a systematic workflow problem" [36]) is reported as a plate-level fact when the fraction exceeds 10 %.

**G-MELT — product identity per well (SYBR/EvaGreen only).**
Keys on: `unkn`, `pos`, `std`. Needs: MCA peaks, passport fingerprint. Thresholds: product peak within ± 1.0 °C of the expected/fingerprint Tm; extra peak above 0.05 of summed heights; width > fingerprint IQR × 2 (lab-set) [45]; MIQE 2.0 and Bio-Rad both warn that a single peak does not prove specificity and that melt analysis cannot see small off-target fractions [1][24]. Failure means: the well's N0 includes non-target product; affects that sample × target; "mixture" class offers exclusion with consequence shown; probe assays skip this rule (`not_applicable`).

**G-GEO — plate geometry.**
Keys on: `ntc`, `nrt`, lowest-copy `unkn`. Needs: row/column, Cq of neighbours. Thresholds: an NTC or low well that amplified and is rook-adjacent to a well in the top decile of copies on the plate is flagged "carry-over candidate" (clinical middleware detects cross-contamination "based on proximity, trends, and positivity rates" [58]); when the vendor file carries a pipetting order, negatives not pipetted last are noted (Burd's placement advice [7]). Failure means: strengthens or weakens a G-NTC-1 contamination hypothesis; never taints on its own.

**G-CLAIM — minimum reportable fold change (study-level, reported with the gate).**
Keys on: all `unkn` of a comparison. Needs: group mean Cq, replicate SD. Thresholds: Bustin 2025 — "Cq < 25: two-fold differences can be reliably detected"; "Cq 25–30: ≥ three-fold differences are advisable"; "Cq > 30: ≥ four-fold differences should be required unless high measurement precision is demonstrated"; detecting 1.5-fold at SD 0.5 Cq needs six technical replicates at 80 % power; a nominal 3× comparison above Cq 30 had a 95 % CI of 0.71–14.74 [4]. Used by C.2 to define what a "resolved" conclusion is; a failure is a Study-Confidence reason, not a plate action.

### B.2 Trending rules (Lab Memory → Levey-Jennings / Westgard adapted for research qPCR)

**Series.** One per (metric, assay_id, control_id, instrument_id). Metrics: `pos`/IRC Cq; `pos`/IRC N0 (efficiency-corrected; detects changes that Cq alone cannot separate from efficiency change); per-target mean E; product Tm; baseline level and slope; and, per instrument across assays, the NTC amplification rate per plate.

**Baseline policy (copied from clinical practice, labelled "provisional" until met).** Mean and SD from "a minimum of 20 measurements over at least 10 days" [6]; limits at mean ± 2 SD and ± 3 SD [6]. Before 20 points: status `provisional`, limits drawn from the available points with widened (× 1.5, lab-set) bands and no rejection rules, only 1_3s warnings. After 20: lock the baseline; recompute on request or after a declared lot/instrument event (B.3). Check approximate normality (Shapiro–Wilk, warn if p < 0.01), because the charting method assumes it and a published PCR-lab application notes it fails otherwise [57].

**Rules (names and definitions verbatim from Westgard [5]; application per run and across runs as stated there).**

| Rule | Definition | Use in qPilot | Needs per run |
|---|---|---|---|
| 1_2s | one measurement beyond ± 2 SD | warning only; "computer applications don't need to use the 1_2s warning rule" [5]; shown, never a card | 1 control well |
| 1_3s | one measurement beyond ± 3 SD | rejection (G-POS fail on this plate) | 1 |
| 2_2s | 2 consecutive beyond the same + 2 SD or − 2 SD | rejection; across runs (consecutive plates) and within run (two control wells) | 1 (across) / 2 (within) |
| R_4s | one beyond + 2 SD and another beyond − 2 SD in the same run; "should only be interpreted within-run, not between-run" [5] | rejection within run only | ≥ 2 control wells |
| 4_1s | 4 consecutive beyond the same ± 1 SD | rejection; "often must be applied across runs" [5] | 1 |
| 10x / 8x / 12x | 10 (8, 12 for N = 4 variants) consecutive on one side of the mean | rejection; across runs and across control materials [5] | 1 |
| 2of3_2s, 3_1s, 6x, 9x | N = 3 variants [5] | available when a plate carries three control wells | 3 |

Why multirules and not ± 2 SD alone: "at ± 2 SD limits about 5 % of good runs are falsely rejected" (note 15, citing Burd [7]) — unacceptable for a research tool. Westgard also states users "should be able to select the individual rejection rules on a test-by-test basis" [5]; the pack exposes each rule as on/off.

**Research-specific additions (deterministic, textbook SPC, no single qPCR source):** a p-chart (binomial limits) on the NTC amplification rate per plate per instrument; an EWMA (λ = 0.2, L = 3) on per-target mean E and Tm as a slow-drift detector shown next to the Shewhart chart; a two-sample change-point check at every Event boundary (Mann–Whitney on the k runs before vs after, k = 5 default) that annotates the chart with "shift of −0.8 Cq at lot change 3 Mar (p = 0.004)".

**What fires a card.** A rule hit on a Series alone writes an Event and a chart annotation. A **card** is created only when the hit concerns a plate that contributes to an open study *and* the robustness engine shows the plate's exclusion or correction changes a conclusion (C.2) — otherwise it is an "FYI" line on the instrument/assay passport page. This is the escalation discipline that keeps approval fatigue down.

### B.3 Lot rules: change-point and bridging (EP26-style, research-adapted)

Evidence that lots matter: Thermo's own specification is "difference between Ct's < 0.6 Ct when different lots of an assay are run with the same sample" (another FAQ on the same page says 0.5) [23]; four master mixes on the same cDNA gave 10- to 30-fold spread in derived quantities [53]; extraction-kit lots shifted Ct significantly [61]; MIQE 2.0 requires verification "when changing batches" [1]; UC Davis: "Reagents from different lot numbers should not be interchanged without prior functional validation" and "each new lot of enzyme should be compared with old lots using known controls" [31]; a 360-lot-change clinical study found QC material and patient samples disagreed in ~7.8 % of events, so real samples are preferred for bridging [54]. CLSI EP26 (paid) defines the two-stage acceptance design [14]; this spec copies the shape, not the text.

**L-CP (automatic).** When `lots.jsonl` records a new lot for a Series' assay or master mix, run the change-point check (B.2) and compute the segment difference with a bootstrap CI. Output: Event + passport line; card only via C.2.

**L-BRIDGE (declared, human-approved).**
- Stage 1 (once per assay, in the pack): the acceptable difference δ, default 0.6 Cq on a matched sample (Thermo [23]) or 25 % in copies (Ma's QC band [8]); the design: ≥ 3 samples spanning the passport's Cq range × ≥ 3 replicates per lot + NTC per lot, both lots on one plate (`qpilot plan` proposes the layout).
- Stage 2 (after the plate): paired ΔCq (new − old) per sample, mean and 90 % CI; TOST against ± δ; also per-well E of each lot inside the passport interval and NTC class unchanged. Verdicts: `pass` (CI inside ± δ); `pass_with_offset` (CI excludes 0 but inside ± δ — store the offset on the lot passport so charts do not alarm, and expose "apply lot offset" as a robustness axis); `fail` (CI outside ± δ — lot marked `retired: recommended`, card); `undetermined` (CI straddles the margin — n too small; card suggests the replicate count that would resolve it from the observed SD).
- Everything is recorded: layout, lot ids, rule, numbers, verdict, actor.

### B.4 Run-factor rescue (the thing "rescue" usually means)

Between-plate variation is multiplicative and can be large ("the 6-times difference between runs 2 and 5" in a routine 6-plate experiment) and calibrator-only correction propagates calibrator error to the whole plate [38]. Ruijter 2015: Y_nj = F_n × (Y_mean + C_j + error); the ratio of two run factors is estimated as the geometric mean of ratios over all overlapping conditions (Eq. 2); missing pairs are filled by nested geometric-mean substitution (Eq. 3) with the warning that "when more than 2 rounds of substitution are required, the design of the experiment is clearly incomplete"; F_n is the geometric mean of the completed matrix column (Eq. 4); N0_corrected = N0 / F_n (Eq. 5) [38]. When `interRunCalibrator` samples are flagged, Hellemans' qBase IRC correction (geometric mean of IRC NRQs, delta-method error; one IRC adds ~70 % uncertainty, three ~40 %) is the alternative [39]. Both are reimplemented from the open-access papers under Apache-2.0 (Factor-qPCR's licence is unstated [71]). In the Gate, a G-POS failure or a 2_2s/4_1s hit on plates 5–8 is *rescued* if a run factor exists for those plates and the conclusion holds after correction (C.2); the factor magnitude is itself a QC fact ("plate 4 is 2.1× plate 3").

### B.5 Packs that copy a regulatory SOP (research use only)

`cgt-biodistribution` implements Ma Table 4 verbatim as examples [8] plus FDA LTFU's "demonstrated limit of quantitation of < 50 copies/µg genomic DNA … with 95 % confidence", triplicates per tissue with one spiked replicate, and individual-animal reporting with the below-LOQ policy stated [9]; FDA's draft potency guidance adds "An assay run should be invalidated if suitability criteria are not met" and control-chart trending of control samples [10]. `rare-target` implements EuroMRD 2007 ranges [17] and the 2024 "MRD low positive, < QR" criterion (three replicates with Ct ≥ 1.0 below the lowest background Ct and at least one ≥ 3.0 below) [18][19], with the fixed banner "research use; not for patient reporting". `edna-lod` implements Klymus [21] with the USGS calculator as the regression reference [22].

---

## C. The triage logic: repeat / rescue / ignore

### C.1 Definitions

- **Ignore** — keep the data as is, log the rule hit, the evidence and the reason "no conclusion changes". Nothing is hidden: the hit stays in the record and the methods text.
- **Rescue** — keep the plate but change the analysis in a recorded, re-runnable way: drop a well or a sample; apply a run factor or lot offset; use the passport's E instead of the plate's; treat the NTC level as background; reclassify a melt mixture; use the plate-specific LLOQ. Rescue is only offered when the robustness engine shows the conclusion is the same with and without the rescue *or* when the rescue is the method the sources prescribe (run factor; plate-specific limit per Ma [8]).
- **Repeat** — re-run a targeted set of wells (affected sample × target plus their NTC, IRC/positive control and, for absolute quantification, the standards), or the whole plate when a pack's rule says the plate is invalid [8][31][32].

### C.2 The consequence test

A **conclusion** is the existing engine's per-gene, per-comparison call: direction, whether the interval excludes 1, and whether the effect clears the Cq-tier threshold (G-CLAIM [4]); plus the per-gene Study Confidence level. The consequence of a Gate hit is computed by running the robustness grid restricted to the hit's `consequence_scope` under its options:

- G-NTC-1: keep / exclude tainted wells / subtract NTC-level background from all wells of the target.
- G-REP: keep / drop well / drop sample.
- G-POS, trending hits: keep / exclude plate(s) / apply run factor (B.4) / apply lot offset (B.3).
- G-EFF: plate E / passport E / exclude target on plate.
- G-STD (absolute): full curve / drop failed end level(s) / plate-specific LLOQ / pooled curve across plates; BLOQ as 0 / LOQ/2 / censored.
- G-IPC: keep / mark sample inhibited (its negatives become "not interpretable") / exclude sample.

Result ∈ {`none` (every call identical across options and the grid's agreement fraction changes by < 1 cell), `magnitude` (same calls, log2 effect moves by more than the tier's resolution or Study Confidence drops one level), `flip` (any call changes direction, crosses 1, or crosses its tier threshold), `unknown` (the study is incomplete: later plates not yet run, or n too small to test)}. `unknown` is stated as such and the card is re-evaluated automatically when plates arrive (the note 01 honesty point).

### C.3 The cost model

A `price_profile.yaml` per lab (defaults shipped, every number editable and labelled as a default):

```yaml
reagent_per_well: {sybr_96: 0.89, sybr_384: 0.44, probe_96: 1.80}   # USD; one cost model gives $85.78/96-well plate ($0.89/rxn) and $167.86/384 ($0.44/rxn) [62]; TaqMan roughly double (estimate, note 01)
plate_plastic: {p96: 5.55, p384: 8.12}                                 # [62]
labour_rate: 27                                                        # USD/h, mid-point of $18–36/h technician adverts [62]
labour_fixed_h: 1.0                                                    # set-up, QC, re-analysis for any repeat (estimate)
labour_per_well_h: 0.02                                                # pipetting/time per well (estimate)
instrument_run: {internal: 30, external: 45}                           # core run charge per plate, UC Davis [62]; Brown $56/$100 [62]
sample_volume_ul_per_well: 2.0
```

Cost(repeat set W) = plate_plastic + |W| × reagent_per_well + labour_rate × (labour_fixed_h + |W| × labour_per_well_h) + instrument_run (if a core) and, separately, **sample depletion**: µL of each sample required vs the remaining volume in the optional sample ledger (note 01 P13); a sample that cannot cover the repeat makes "repeat" infeasible for it and the card says so. A full 96-well repeat lands at roughly $150–300 and 3–5 person-hours before sample cost (estimate, note 01 §1.6); a targeted 12-well repeat at roughly $20–40 and ~1.3 h. The lab sets `repeat_budget_threshold` (default $100) above which a repeat recommendation is downgraded to "human decides" even when the consequence is a flip.

### C.4 The decision table

| Consequence | Repeat feasible (sample available, cost ≤ threshold) | Recommendation | Who may apply (D.4) |
|---|---|---|---|
| none | any | **ignore** (log; keep all data) | Automatic log; the choice "ignore" is recorded by the agent at "Decide-and-tell-me", by the human at "Suggest" |
| magnitude | any | **rescue** with the option that keeps the calls and moves the effect least; state the magnitude shift in the Study Confidence reasons | Agent may apply |
| flip | yes | **repeat** targeted wells (list, layout, cost); until then the conclusion is "unresolved" | Human only |
| flip | no (sample exhausted or over budget) | **rescue** if a prescribed rescue restores agreement across ≥ 90 % of grid cells (lab-set); else report "unresolved at this depth" with the replicate count that would resolve it [4] | Human only |
| unknown | — | defer; re-triage on new data; show provisional direction | Automatic |
| plate invalid by pack rule (G-STD in `cgt`, contamination-class NTC with tainted wells across the target, G-NAC) | — | **repeat plate**, with Ma's escalation on a second consecutive failure [8] | Human only |

### C.5 Worked examples

**Example 1 — NTC at 36.4 (ignore).** SYBR, IL6, plate 3. NTC Cq 36.4, engine call positive, melt peak Tm 74.0 °C vs passport product Tm 84.2 ± 0.3 °C → class `dimer_candidate`. Lowest IL6 unknown on the plate Cq 27.1; gap 9.3 cycles > k = 5 [1]. consequence_scope = unknowns with Cq ≥ 31.4: none. Consequence `none`. Card is not raised; the record logs `G-NTC-1: warn (dimer), 0 wells tainted, ignored (no conclusion changes)`; the methods paragraph gains "NTC amplification at Cq 36.4 (primer-dimer by melt) ≥ 9 cycles after the lowest sample". Cost not computed. Passport: NTC-dimer frequency for IL6 ticks up; if it exceeds the p-chart limit across plates, the assay passport suggests redesign (PrimePCR's < 35 criterion [24] is shown as context).

**Example 2 — replicate 0.9 Ct off at Cq 33 (ignore after consequence test).** Triplicate 33.0 / 33.1 / 33.9 for gene TNF, sample S7. Passport anchor: 10 copies ≈ Cq 35.0 at E 1.9 [3], so N ≈ 10 × 1.9^(35.0 − 33.2) ≈ 32 copies. tol_Cq = 2.1/ln 1.9 × √(0.0225 + 1/32) = 3.27 × 0.232 = 0.76 cycles; observed range 0.9 → G-REP flag, marginal. KOD: well 3's efficiency z = 0.8 (not an outlier) [40]; no LinRegPCR `excl` [45]. Consequence under keep / drop well / drop sample: group B mean log2 ratio moves 0.11; all calls identical → `none`. Repeat cost (3 wells + NTC, 96-well SYBR): 5.55 + 4 × 0.89 + 27 × (1.0 + 0.08) ≈ $38 and 1.1 h — not justified. Recommendation **ignore**; logged with the Poisson tolerance shown so the student learns why the 0.5-cycle rule did not apply [3].

**Example 3 — positive control drifting on instrument B (rescue).** Series (GAPDH, cDNA-pool-A, qs5-B), baseline locked at 20 points (mean 22.40, SD 0.21). Plates 5–8 (after master-mix lot B on 3 Oct): 22.85, 22.90, 22.95, 23.10 → 2_2s on plates 5–6 and 4_1s across 5–8 [5]; change-point at the lot Event: +0.55 Cq (p = 0.003). G-POS fails on plates 5–8 for GAPDH (1_3s on plate 8). Scope: every sample on plates 5–8. Consequence: excluding plates 5–8 flips gene X ("2.4×, CI excludes 1" → "unresolved"); applying run factors (overlap exists: 6 samples shared across plates 4–8) gives F = 1.42 (Cq-equivalent 0.55) and the conclusion holds in 11/12 grid cells → `magnitude` under rescue, `flip` under exclusion. Recommendation **rescue** by run factor, agent may apply at "Decide-and-tell-me"; card also offers "bridge lot B against lot A" (L-BRIDGE, 20 wells ≈ $45, 1.4 h) as the confirmatory follow-up, and "repeat plates 5–8" (~$600–1,200, 12–20 h) as the expensive alternative. Human sees all three with numbers; the chosen option and reason are hashed into the record.

**Example 4 — standard curve fails in the `cgt-biodistribution` pack (repeat plate).** 384-well vector-genome plate, 8-level curve in duplicate: slope −3.68 (E 87 %), R² 0.991, the 25-copy level fails one duplicate (Ct %CV 2.6 %). Pack rule G-STD: E outside 90–110 % → curve fails [8]. Consequence: every unknown quantity on the plate is uninterpretable (absolute quantification) → pack action `invalidate_plate`. Options: repeat plate (reagents 8.12 + 384 × 1.80 ≈ $700, ~5 h plus instrument time; tissue DNA remaining per the ledger: sufficient for 41/42 samples); or, if this is the LLOQ level only, Ma's plate-specific-LLOQ rescue [8] — not applicable here because E failed, so the card says so. Recommendation **repeat plate**, Human only; if the repeat fails again the card becomes an escalation record ("second consecutive failure — Ma: notify the Study Director" [8]); also a G-EFF cross-check: the per-well mean E of the standards is 1.86 vs E_std 1.87, consistent, so inhibition is unlikely and the pipetting/standard-dilution hypothesis is shown (MIQE 2.0 mechanism [1]; Klymus's weekly-fresh-dilution advice [21]).

---

## D. Decision Cards and the record

### D.1 What the scientist sees

A Gate card has the existing card anatomy plus four Gate-specific blocks:
1. **Rule and evidence** — rule id and plain statement with its source; the numbers (Cq, Tm, gap, tolerance, z-score, chart with the point and its limits); the wells and samples in `consequence_scope` on a small plate map.
2. **Consequence** — the per-gene table of calls under each option, colour-coded identical / magnitude / flip, with the grid-agreement fraction.
3. **Cost** — for each repeat option: wells, layout, reagent, hours, instrument charge, sample depletion per sample; for rescues: "no bench cost; analysis change recorded".
4. **Recommendation and reason** — one line, bound to fact ids ("no naked numbers").
Passport pages (assay / instrument / lot) show the Series charts, Events, provisional status, and the list of FYI hits that did not become cards. A plate's Gate summary is a single line per target: `IL6: G-NTC-1 warn (dimer, ignored) · G-REP 1 well (ignored) · G-EFF pass (E 1.89, passport 1.90 ± 0.03)`. For cores, this line per target *is* the client QC page (note 14 D5).

### D.2 What is logged (record fields)

Into the Analysis Record (hash-chained): `rule_pack {name, version, hash}`; `passport_refs [{kind, key, version, hash}]`; `side_car_hash`; per plate per rule: `rule_eval {rule_id, verdict, numbers, scope_well_ids, not_applicable_reason}`; per card: `consequence {class, per_gene_calls_by_option, grid_agreement}`, `cost {per option}`, `recommendation`, `decision {actor ∈ human|agent|system, option, reason, timestamp, prev_hash}`; Events (lot change, instrument, pack edits) with their source (typed / inferred / imported). The record is sufficient to re-run the Gate byte-for-byte: same RDML, same pack hash, same passport versions → same verdicts (acceptance test). Vocabulary note: these are "time-stamped, operator-attributed entries that do not obscure previous entries" in Part 11's words [72] — described as features, never claimed as compliance (note 15 D5).

### D.3 What an agent can call (MCP, consistent with `qpcr_study` / `qpcr_robustness` / `qpcr_decide` / `qpcr_plan`)

| Tool | Input | Output | Autonomy |
|---|---|---|---|
| `qpcr_run_gate` | `{study_id, plate_id?, rule_pack?: name\|hash}` | `{plates: [{plate_id, status: gated\|ungated, evaluations: [...], cards: [card_id]}]}` | read |
| `qpcr_triage` | `{study_id, scope?: {plate_id, target_id, sample_id}}` | `[{card_id, rule_ids, consequence, cost_by_option, recommendation}]` | read |
| `qpcr_repeat_plan` | `{card_id, option_id}` | `{wells: [{row, col, sample_id, target_id, role}], layout_file, cost, sample_check: [{sample_id, needed_ul, remaining_ul, ok}]}` | read; writing the layout to vendor software is the roadmap's layout-push item |
| `qpcr_passport` | `{kind: assay\|instrument\|lot\|control_material, key, version?}` | passport JSON with fact ids | read |
| `qpcr_passport_history` | `{kind, key, metric, since?}` | `{points: [{run_hash, date, value, limits, rule_hits}], events: [...]}` | read |
| `qpcr_control_trend` | `{assay_id, control_id, instrument_id, metric}` | `{status: provisional\|in_control\|warning\|rejection, rule_hits: [...], baseline: {n, mean, sd, locked_at}}` | read |
| `qpcr_lot_register` | `{run_hash, lots: {...}}` or `{lot: LotRecord}` | `{ok, inferred_runs_updated}` | **Agent may apply** (data entry, reversible, logged) |
| `qpcr_lot_bridge` | `{assay_id, old_lot, new_lot, plate_id?}` | without plate: proposed layout and δ; with plate: `{verdict, delta_cq, ci, tost, n}` | propose: agent; accept verdict: human |
| `qpcr_instrument_status` | `{instrument_id}` | `{series_status: [...], last_calibration: {...}, open_alerts: [...]}` — for an agent deciding where to run a plate | read |
| `qpcr_rulepack` | `{action: list\|get\|validate\|diff, pack?}` | pack text, validation errors, diff between versions | read; `apply_edit` is human only |
| `qpcr_decide` (existing) | `{card_id, option_id, reason, actor}` | `{decision_hash}` | per D.4 |

All tools return engine fact ids with every number; the model harness (brief) gains Gate questions ("why was plate 3 ungated?", "which wells are tainted by the IL6 NTC?") with engine-known answers.

### D.4 Automatic / Agent may apply / Human only

| Automatic (system, always logged) | Agent may apply (at "Decide-and-tell-me"; always reversible, always logged) | Human only (escalation rule: conclusion-flipping and irreversible) |
|---|---|---|
| Compute all Gate facts; evaluate every rule; mark plates ungated; build passports, Series, charts; detect change-points; compute consequence and cost; re-triage when new plates arrive; write FYI lines; write RDML `target` expected values | Record "ignore" where consequence = none; apply rescues where consequence ≠ flip (drop well/sample, run factor, lot offset, passport E, plate-specific LLOQ); register lots and control-material mappings; propose bridge layouts and repeat plans; lock a provisional baseline once ≥ 20 points exist; propose alias merges | Any option whose consequence is `flip`; declaring a plate invalid in a study; accepting a bridge `fail`/`pass_with_offset`; retiring a lot; editing any rule threshold or pack; excluding plates; closing an escalation; merging assay aliases when sequences differ; unlocking/recomputing a baseline; any export off the machine |

At "Teach me" everything above the Automatic row becomes a card; at "Suggest" the agent recommends and the human clicks.

---

## E. Validation plan

### E.1 Public datasets and what each can validate

| Dataset | Licence | Contents | Validates |
|---|---|---|---|
| Vermeulen 2009 neuroblastoma set as used by the RDML consortium (`data_vermeulen_raw.rdml`, driven by `run_analyze_vermeulen_rdml.py` in `rdmlpython/test`) [46]; Ruijter 2013 built its 11-method benchmark on it [78] | consortium test data; reuse terms for redistribution unverified (notes 07/14 could not confirm) | multi-run study, raw curves, LinRegPCR reference outputs | A.6 ingest at scale; LinRegPCR flag counts per run (G-REP evidence); run-factor estimation across runs (B.4) and whether correction changes any gene call (C.2); behaviour of the Gate on plates with few or no typed controls (G-TYPED) |
| `ruijter` R data package: `ds_94_4` (MYCN, SYBR, four 10-fold dilutions incl. NTC, 384 wells, well ids), `ds_380` (one sample in 380 wells), `ds_competimer` (efficiency modulated by competimer primers, no well ids) [49] | CC BY 4.0 | raw fluorescence by cycle | `ds_94_4`: G-STD (slope, R², per-level replicate CV, E_std vs per-well E), G-NTC-1 engine call vs NTC wells, Klymus discrete LOD/LOQ on a 4-level series (limited), Svec's CI-vs-replicates claim [42]; `ds_380`: null distribution of G-REP (false-flag rate must be ≤ 5 % at tol), KOD false-positive rate, G-GEO/edge index on a plate with no biology, instrument uniformity metrics; `ds_competimer`: G-EFF and KOD sensitivity to known efficiency changes |
| Brintz 2025, 165,214 TaqMan Array Card curves with expert calls [50] | CC0 on GitHub (Zenodo metadata says CC BY 4.0 — confirm before redistribution) | ROX-normalised 40-cycle curves, labels; column schema and presence of NTC/control labels unverified | engine amplification call agreement for G-NTC-1 / G-NAC / positivity (expected > 99 % within-source per the paper); a stress test for A.6 throughput |
| Klymus 2020 USGS data release (36 assays × 7 labs, 20–96 replicates per standard level; Cq tables) [21][22] | public domain (USGS) | Cq/SQ tables, calculator outputs | regression tests for the `edna-lod` pack (discrete and modelled LOD/LOQ must match `qPCR_LOD_Calc` outputs); cross-lab divergence of the same assay = what a passport commons would show |
| Nettle 2019 telomere Cq replicates and code (Zenodo 1994386) [73] | CC BY 4.0 | T and S Cq replicates across plates with QC DNAs | G-REP across plates; plate effects and QC-DNA Series as a multi-plate control-chart test |
| Lane 2020 EPA Draft Method C workbook (21 labs, 91 standard curves) [74] | open access article; data in supplement | standard-curve parameters across labs and weeks | composite/pooled curve acceptance (G-STD pooled option) and between-run slope/intercept trending |
| Zenodo 18833966 (Ostrea edulis eDNA assay, 2026) [75] | per record | LOD/LOQ standard data + environmental Cq | `edna-lod` pack end-to-end on one assay |
| qpcR / PCRedux collections: `lievens1–3` (inhibition series), `RAS002/RAS003.rdml` with human decisions, `htPCR` 95 × 96 grid [51] | GPL (tests only; never vendored) | raw curves, some RDML, labels | G-IPC-like inhibition signatures via KOD; call agreement; scale |
| Clinical control-chart literature: Peng 2022 (466 HPV batches, limits from the first 20, 1_2s/1_3s/2_2s, 8 out-of-control) [57] | open access | batch-level numbers in the paper | sanity check of the Westgard implementation against a published PCR-lab application (if the batch series is recoverable from the paper's figures/supplement; otherwise synthetic) |
| Synthetic injections into `ds_380` / `ds_94_4` / Vermeulen: lot shifts (+0.3…+1.5 Cq), slow E drift, NTC contamination at product Tm, carry-over next to high wells, baseline-subtracted exports | derived | ground truth by construction | power and false-alarm curves for every rule (published as the acceptance test) |

Not available publicly (gaps the notes confirmed): longitudinal research-lab archives with typed controls, lot ids and instrument ids; raw biodistribution/VCN plates; raw wastewater plates (the NWSS public dataset is concentrations only and archived [76]). Wastewater and eDNA programmes are the most promising partners because they run the same assay weekly for months.

### E.2 Acceptance tests (what "done" means per component)

- Determinism: `memory build --rebuild` reproduces identical passport JSON and identical `rule_evals` for the same inputs, pack hash and engine version.
- G-REP on `ds_380`: flag rate ≤ 5 % at the Poisson tolerance; KOD false positives ≤ 5 % at P = 0.05 [40].
- G-STD on `ds_94_4`: slope, R², E agree with an independent least-squares implementation to 1e-6; E_std vs per-well E gap reported.
- G-NTC-1: engine call agrees with Brintz expert calls ≥ 99 % on the internal split [50]; melt class on `test_mca_*` RDML files reproduces rdmlpython's stored results [46].
- Westgard engine: unit tests for every rule on hand-built series (including the "within-run only" restriction of R_4s and the across-run 4_1s/10x) [5]; provisional status before 20 points [6].
- Run factors: reproduce Ruijter's worked example including the substituted F6/F5 ratio [38].
- `edna-lod`: match `qPCR_LOD_Calc` on the USGS release for discrete LOD/LOQ and modelled values within the paper's reported ranges [21][22].
- `cgt-biodistribution`: synthetic plates built to pass/fail each Table 4 criterion individually [8].
- Record round-trip: a record re-run with the same pack hash yields the same verdicts; changing one threshold yields a new pack hash and a diff.

### E.3 What a lab's own data adds

Only a lab archive supplies: real lot boundaries with dates; control materials run for months; instrument identities and calibration events; operator changes; the base rate of each rule hit (how often G-NTC-1 is a dimer vs contamination); whether the Poisson tolerance matches their pipetting; how often "repeat" was chosen and whether the repeat changed anything (the number nobody has, note 01 Q4). Ask two or three partner labs (one core, one expression lab, one wastewater or eDNA programme) for de-identified RDML archives plus a lot logbook photo; everything stays on their machine — they run `qpilot memory build` and share passports and rule-hit counts, not data.

### E.4 Build plans for two developers

**Two weeks (10 working days) — Gate v0 + Memory v0.**
Dev A (engine): days 1–2 ingest, `run_hash`, SQLite schema, parquet curves, Series extraction from existing records; days 3–5 rule-pack loader and validator, G-TYPED, G-NTC-1, G-NRT, G-POS (absolute window), G-STD (research defaults), G-REP (Poisson tolerance + LinRegPCR flags), G-MELT, with facts and `not_applicable` logic; days 6–8 consequence test on top of the robustness API, cost model, decision table, three card templates; days 9–10 acceptance tests on `ds_94_4`, `ds_380`, Vermeulen; synthetic NTC/replicate injections.
Dev B (memory, UI, MCP): days 1–3 assay and instrument passports, alias tables, reconciliation and control-mapping cards; days 4–6 Levey-Jennings with provisional baseline, Westgard 1_3s/2_2s/4_1s/10x (R_4s when ≥ 2 wells), chart in the Gradio page, Event markers; days 7–8 side-car prompt (10 fields, carry-forward), `lots.jsonl`, RDML annotation write-back, `qpcr_run_gate`, `qpcr_triage`, `qpcr_passport`, `qpcr_control_trend`, `qpcr_lot_register`; days 9–10 record fields, docs, demo workspace with 30 synthetic runs and an injected lot shift, harness questions.
Deliverable: a plate gets a Gate line per target; failures become cards with consequence and cost; an assay and an instrument have passports; a control Series shows a chart with rules; lots are typed once per run.

**Six weeks — Gate v1 + Memory v1.**
Weeks 3–4: L-CP and L-BRIDGE (TOST), run-factor rescue wired into C.2 (B.4), KOD, G-IPC and spike handling, `cgt-biodistribution` and `rare-target` packs with their escalation cards, `edna-lod` pack with Klymus curve-fitting and the USGS regression test, p-chart and EWMA, change-point annotations, `qpcr_lot_bridge`, `qpcr_repeat_plan` with the sample ledger.
Weeks 5–6: `core-facility` profile (client QC page per plate from the Gate lines; UC Davis logbook line: instrument, lots, operator [31]); verification-plate import and re-analysis for Thermo RNase P and Bio-Rad qualification layouts [27][30]; G-GEO; passport write-back into RDML `target` and the consortium extension proposal (A.5) as a GitHub issue with the XSD fragment; anonymised passport export; validation report (E.2 results published in the repo); documentation of every default with its source; two partner-lab pilots.
Hardest parts, honestly: identity (assay/instrument/control mapping without sequences or serials), getting lots typed (one prompt, defaults carried forward, nothing mandatory), and keeping "unknown consequence" honest while a study is incomplete.

---

## F. Risks and honest limits

### F.1 What cannot be inferred from RDML alone

- **Lots, serials, operators, barcodes, pipetting order, reagent volumes, time of set-up** — none exist in RDML 1.3/1.4 [47]; they come only from the side-car or vendor headers. Lot attribution by date range is inference and is labelled so.
- **What a `pos` sample physically is** — RDML types it but does not identify the material; a Series needs the lab's mapping. IRC and `calibratorSample` booleans exist but exporters rarely set them [47]; `qpilot plan` should set them at design time.
- **Sample types at all** — many vendor exports arrive untyped or with vendor task names (QuantStudio "NTC/STANDARD/UNKNOWN", CFX "NTC/Std/Unkn"); the vendor-capture roadmap must map them; until then G-TYPED says "ungated".
- **Whether curves are raw** — vendors baseline-subtract and ROX-normalise by default (note 06); G-PROV detects footprints but cannot recover raw data.
- **Multi-channel evidence** (passive reference, bubbles) — RDML carries only the reporter per target [47].
- **Copies** — Poisson tolerances need an estimate of copies; without a standard curve or a passport anchor the fallback is a Cq-tier table [35], which is cruder and said so.
- **The source of contamination** (reagent, aerosol, carry-over) — the Gate can classify by melt and geometry, never diagnose.
- **Biology vs drift** — a control material can itself degrade; charts show the hypothesis "control degraded" next to "instrument/lot drift" (note 15 D2 risk).
- **Small labs** — 20 points per Series may take months; provisional status is shown, never silently tightened.

### F.2 Avoiding any implication of clinical QC

- Status words are `gated / ungated`, `pass / warn / fail (rule id)`, `in_control / warning / rejection (Westgard rule)`; never "valid run", "diagnostic", "patient", "clinically acceptable", "validated", "Part 11 compliant", "IVD" (note 15 Q5 word list; FDA's RUO guidance treats "performance claims, instructions for clinical interpretation" and solicitation of clinical labs as evidence against RUO status [59]; 21 CFR 809.10 wording [59]).
- Every pack file, passport page and report carries: "Research use only; rules are lab-defined examples with sources; not clinical validity rules; the software is not validated as a GLP computerised system and makes no 21 CFR Part 11 claim."
- Packs that mirror regulatory SOPs (`cgt-biodistribution`, `rare-target`) are named by document, never by claim, and their `invalidate_plate` actions are always Human-only.
- Audit vocabulary (time-stamped, non-obscuring, attributed entries [72]) is described as what the record *does*, with an explicit "no compliance claim" sentence (note 15 D5).

### F.3 Where the sources conflict (and what qPilot does)

| Topic | Sources disagree | qPilot's position |
|---|---|---|
| NTC rule | MIQE 2.0: ≥ 5 cycles before the negative control [1]; Thermo: NTC Ct > 38 clean [23]; CDC IFU: any NTC growth invalidates the run [32]; Ma: ≥ 2/3 NTC wells BLOD in sample analysis [8]; PrimePCR: NTC Cq < 35 → redesign [24]; forum: "no impact if product < 30" [37] | Default the MIQE gap rule with melt class; the absolute rules are selectable per pack; the consequence test decides what to do |
| Efficiency window | 90–110 % (Ma, Thermo) [8][23]; 90–105 % (Bio-Rad guide) [26]; "≥ 90 % accepted norm" (UC Davis) [31]; per-curve E is systematically lower than standard-curve E (Hastings 1.92 vs 2.10–2.12) [43]; E is instrument-dependent [42][44] | Learn the assay's own interval per instrument and per method; textbook band only while provisional; never mix E_std and E_LinReg in one chart |
| Replicate tolerance | 0.2–0.5 Ct [37]; < 1.5 Ct (lab protocol); SD > 0.5 (Promega) [34]; Cq-tiered table [35]; "up to two cycles to Cq 35" (Ruiz-Villalba) [3] | Poisson-aware tolerance with copies; the fixed rules offered as named alternatives |
| R² | ≥ 0.980 (Ma; Bio-Rad) [8][26]; ≥ 0.98 correlation (EuroMRD) [17]; > 0.99 (VCN/AAV method papers, note 09); > 0.97 (Thermo spec) [23] | Pack-specific; always reported with the number of levels and replicates, since R² alone is weak with few points |
| LOD definition | ≥ 95 % detection (Klymus; MIQE/Ruiz-Villalba) [21][3]; positive in all replicates across five runs with Ct ≤ 40 (Ma) [8]; EuroMRD "sensitivity" = lowest dilution with ≥ 1 positive replicate ≥ 1.0 Ct below background [17]; Poisson floor 3 copies in all [3][8] | Store each definition under its name; never report "LOD" without the method label |
| Control-chart limits | ± 2 SD alone rejects ~5 % of good runs [7]; Westgard multirules [5] | Multirules; 1_2s shown as a warning only |
| Westgard N | rules designed for 2–4 control measurements per run [5]; research plates usually hold one positive control | Within-run rules need ≥ 2 wells; otherwise only across-run rules; the plate-design assistant proposes two control wells |
| Lot tolerance | Thermo says < 0.6 Ct in one FAQ and 0.5 Ct in another on the same page [23]; MIQE 2.0 gives no number [1]; clinical practice: lab-defined (EP26) [14][54] | δ is lab-set; 0.6 Ct shipped as the example with the citation and the discrepancy noted |
| Cq cut-off | fixed 35/40 cycles (common) vs efficiency-dependent (MIQE 2.0: the LLOQ Cq is 35 at 90 % efficiency but 42 at 70 %, note 14; Ruiz-Villalba: "the decision which Cq cutoff value … should be based on the PCR efficiency") [1][3] | No fixed cut-off in `research-default`; the passport's E and anchor define it; packs copying an SOP may fix 40 |
| Who decides invalidity | clinical/GLP: software against pre-declared rules, technologist reviews [7][8]; research: nobody | Rules evaluate automatically; invalidity is always a human decision in qPilot; the record keeps both |

### F.4 Other risks

- **Adoption of lot entry** is the weakest link (notes 01, 02, 15 all rate it medium); mitigations: one prompt, carry-forward, inference from dates, barcode/photo capture later.
- **Alert fatigue** if thresholds are textbook: learned intervals plus the consequence filter are the mitigation; measure the card rate per plate in the pilots and target < 1 card per plate on average (goal, not a source).
- **Over-correction** by run factors when plates coincide with biological groups (Ruijter's caveat [38]): the design check refuses to correct confounded designs and says so.
- **False reassurance** on systematic contamination: a single-plate "ignore" is correct only if the cross-run p-chart is also quiet; both are shown.
- **Licences**: all methods above are reimplemented from open-access papers; qpcR/PCRedux/qcc (GPL) are used for tests only; Factor-qPCR code is not reused [71].
- **Scope creep toward GLP**: regulated users will ask for e-signatures and validation packages; the answer is the fixed header and the note 15 D5 posture.

---

## Sources

1. Bustin SA, Ruijter JM, van den Hoff MJB, et al. MIQE 2.0: Revision of the MIQE Guidelines. Clin Chem 2025;71(6):634–651. https://academic.oup.com/clinchem/article/71/6/634/8119148 ; PDF https://www.multid.se/publications/MIQE-ver2.pdf (quotations as read by notes 01, 02, 14, 15)
2. Bustin SA. MIQE 2.0 and the Urgent Need to Rethink qPCR Standards. Int J Mol Sci 2025. https://pmc.ncbi.nlm.nih.gov/articles/PMC12154065/
3. Ruiz-Villalba A, Ruijter JM, van den Hoff MJB. Use and Misuse of Cq in qPCR Data Analysis and Reporting. Life 2021;11:496. https://pmc.ncbi.nlm.nih.gov/articles/PMC8229287/
4. Bustin SA, Kirvell S, Nolan T, Mueller R, Shipley GL. When Two-Fold Is Not Enough: Quantifying Uncertainty in Low-Copy qPCR. Int J Mol Sci 2025;26:7796. https://pmc.ncbi.nlm.nih.gov/articles/PMC12387016/
5. Westgard QC. "Westgard Rules" and multirules. https://www.westgard.com/mltirule.htm
6. Westgard QC. QC — The Levey-Jennings Control Chart (lesson 12). https://www.westgard.com/lesson12.htm
7. Burd EM. Validation of laboratory-developed molecular assays for infectious diseases. Clin Microbiol Rev 2010. https://pmc.ncbi.nlm.nih.gov/articles/PMC2901657/ (control-set and ±2 SD statements as read by note 15; the fetched first half confirms the probit/60-point LoD design and 20-day precision)
8. Ma H, Bell KN, Loker RN. qPCR and qRT-PCR analysis: regulatory points to consider when conducting biodistribution and vector shedding studies. Mol Ther Methods Clin Dev 2021;20:152–168. https://pmc.ncbi.nlm.nih.gov/articles/PMC7786041/
9. FDA. Long Term Follow-Up After Administration of Human Gene Therapy Products (Jan 2020). https://www.fda.gov/media/113768/download
10. FDA draft guidance. Potency Assurance for Cellular and Gene Therapy Products (Dec 2023). https://www.fda.gov/media/175132/download
11. ICH S12. Nonclinical Biodistribution Considerations for Gene Therapy Products (2023). https://database.ich.org/sites/default/files/ICH_S12_Step4_Guideline_2023_0314.pdf
12. FDA. Design and Analysis of Shedding Studies for Virus or Bacteria-Based Gene Therapy and Oncolytic Products (2015). https://www.fda.gov/media/89036/download
13. EMA. Guideline on the quality, non-clinical and clinical aspects of gene therapy medicinal products (EMA/CAT/80183/2014). https://www.ema.europa.eu/en/documents/scientific-guideline/guideline-quality-non-clinical-and-clinical-aspects-gene-therapy-medicinal-products_en.pdf
14. CLSI EP26-Ed2. User Evaluation of Acceptability of a Reagent Lot Change (2022; paid). https://clsi.org/standards/products/method-evaluation/documents/ep26/
15. CLSI EP17-A2. Evaluation of Detection Capability (paid). https://clsi.org/shop/standards/ep17/ (CLSI EP05 page not retrievable in any note)
16. ISO 20395:2019 (paid; under revision). https://www.iso.org/standard/67893.html
17. van der Velden VHJ, et al. EuroMRD guidelines for RQ-PCR MRD data interpretation. Leukemia 2007;21:604–611. https://euromrd-public.s3.nl-ams.scw.cloud/Guidelines_for_RQ-PCR_MRD_data_interpretation-Leukemia2007_%2021_604-611.pdf (numbers as read by note 09)
18. van der Velden VHJ, et al. Quality assurance and updated EuroMRD guidelines. Leukemia 2024;38:1315–1322. https://europepmc.org/article/PMC/PMC11147754
19. Kotrova M, et al. The gray area of RQ-PCR-based MRD: subdividing "positive, below quantitative range". Leukemia 2024;38:1617–1620. https://europepmc.org/article/PMC/PMC11216996
20. Cross NCP, et al. Laboratory recommendations for scoring deep molecular responses in CML. Leukemia 2015;29:999–1003. https://europepmc.org/article/PMC/PMC4430701
21. Klymus KE, Merkes CM, Allison MJ, et al. Reporting the limits of detection and quantification for environmental DNA assays. Environmental DNA 2020;2:271–282. https://dspace.library.uvic.ca/bitstreams/26e02ceb-fd07-486b-b7c1-283f0eb1ea8b/download ; USGS data release https://data.usgs.gov/datacatalog/data/USGS:5d36fbfce4b01d82ce8a6cbf (numbers as read by note 08)
21b. Forootan A, et al. Methods to determine limit of detection and limit of quantification in qPCR. Biomol Detect Quantif 2017. https://pmc.ncbi.nlm.nih.gov/articles/PMC5496743/
22. Merkes CM. qPCR_LOD_Calc (USGS, public domain). https://github.com/cmerkes/qPCR_LOD_Calc
23. Thermo Fisher. TaqMan MicroRNA Assay FAQs (lot-to-lot < 0.6 Ct / 0.5 Ct; efficiency 90–110 % across 5 logs; NTC Ct > 38; R² > 0.97). https://www.thermofisher.com/order/catalog/product/4440888/faqs
24. Hellemans J, Vandesompele J, et al. PrimePCR Assays: Meeting the MIQE Guidelines by Full Wet-Lab Validation. Bio-Rad Bulletin 6262. https://www.bio-rad.com/sites/default/files/webroot/web/pdf/lsr/literature/Bulletin_6262.pdf
25. Bio-Rad. PrimePCR Assays, Panels, and Controls Instruction Manual (control-assay rules). https://www.bio-rad.com/webroot/web/pdf/lsr/global/english/primePCR/LIT10026370.pdf
26. Bio-Rad. Real-Time PCR Applications Guide, Bulletin 5279. https://www.bio-rad.com/webroot/web/pdf/lsr/literature/Bulletin_5279.pdf
27. Thermo Fisher. QuantStudio 3 and 5 Installation, Use and Maintenance Guide (RNase P verification criterion and calibration cadence). https://www.ffclrp.usp.br/divulgacao/emu/real_time/manuais/QuantStudio3_5_InstallUseMaint_UG.pdf
28. Thermo Fisher. QuantStudio 6 and 7 Flex Maintenance and Administration Guide, Pub. 4489821. https://documents.thermofisher.com/TFS-Assets/LSG/manuals/4489821.pdf
29. Thermo Fisher. Real-Time PCR Instrument Calibration and Verification Kits (prices). https://www.thermofisher.com/us/en/home/life-science/pcr/real-time-pcr/reagents-kits/other/calibration-verification.html
30. Bio-Rad. Bulletin 6323, CFX Qualification Plate. https://www.bio-rad.com/sites/default/files/webroot/web/pdf/lsr/literature/Bulletin%206323.pdf
31. UC Davis Real-Time PCR Research and Diagnostic Core Facility. QA/QC Guidance (April 2016). https://pcrlab.vetmed.ucdavis.edu/sites/g/files/dgvnsk6571/files/inline-files/CoreFacility_QA-QCGuidance_2016.pdf
32. CDC. 2019-nCoV Real-Time RT-PCR Diagnostic Panel IFU (run-validity table). https://www.fda.gov/media/134922/download
33. Thermo Fisher. TaqPath COVID-19 Combo Kit IFU (control Ct cut-offs). https://www.fda.gov/media/136112/download
34. Promega. Real-Time qPCR: Guidelines for a Comparison of Reagent Performance (AN299). https://www.promega.com/-/media/files/resources/application-notes/pcr/an299-real-time-qpcr-guidelines-for-a-comparison-of-reagent-performance.pdf
35. Table of maximal acceptable Cq replicate variance by mean Cq (PMC7780752, Table II). https://pmc.ncbi.nlm.nih.gov/articles/PMC7780752/table/tII-br-0-0-01400
36. VoilaPCR (vendor blog). NTC Amplification in qPCR https://voilapcr.com/blog/ntc-amplification-in-qpcr-what-it-means-and-when-to-worry ; Replicate Variability in qPCR https://voilapcr.com/blog/replicate-variability-in-qpcr-how-much-is-too-much
37. ResearchGate threads: NTC amplification https://www.researchgate.net/post/NTC_amplification_contamination_in_my_real_time_qpcr_runs_Anyone_offer_insights_to_know_if_the_results_are_negligible_or_not ; triplicates https://www.researchgate.net/post/Triplicate-for-samples-in-qPCR-analysis ; SD threshold https://www.researchgate.net/post/Is-there-a-statistical-test-or-a-specific-standard-deviation-threshold-that-must-be-met-in-order-to-remove-a-technical-replicate-from-my-qPCR-data ; NTC late amplification https://www.researchgate.net/post/Amplification-in-the-NTC-towards-the-end-of-qPCR
38. Ruijter JM, et al. Removal of between-run variation in a multi-plate qPCR experiment. Biomol Detect Quantif 2015;5:10–14. https://pmc.ncbi.nlm.nih.gov/articles/PMC4822202/
39. Hellemans J, et al. qBase relative quantification framework. Genome Biol 2007;8:R19. https://europepmc.org/article/PMC/PMC1852402
40. Bar T, Ståhlberg A, Muszta A, Kubista M. Kinetic Outlier Detection (KOD) in real-time PCR. Nucleic Acids Res 2003;31:e105. https://doi.org/10.1093/nar/gng106
41. Tichopad A, et al. Quality control for quantitative PCR based on amplification compatibility test. Methods 2010;50:308–312. https://www.gene-quantification.de/Tichopad-et-al-The-ongoing-evolution-of-qPCR-Methods-2010.pdf
42. Svec D, Tichopad A, Novosadova V, Pfaffl MW, Kubista M. How good is a PCR efficiency estimate. Biomol Detect Quantif 2015. https://www.gene-quantification.de/svec-et-al-pcr-efficiency-bdq-2015.pdf
43. Hastings WJ, Eisenberg DTA, Shalev I. Impact of Amplification Efficiency Approaches on Telomere Length Measurement via qPCR. Front Genet 2021;12:728603. https://pmc.ncbi.nlm.nih.gov/articles/PMC8484782/
44. Rogers-Broadway KR, Karteris E. Amplification efficiency and thermal stability of qPCR instrumentation. Exp Ther Med 2015;10:1261–1264. https://pmc.ncbi.nlm.nih.gov/articles/PMC4578049/
45. Untergasser A, et al. Web-based LinRegPCR. BMC Bioinformatics 2021;22:398. Full text https://www.ebi.ac.uk/europepmc/webservices/rest/PMC8386043/fullTextXML
46. RDML-consortium/rdmlpython (MIT), incl. `test/run_analyze_vermeulen_rdml.py` and `test_mca_*` RDML files. https://github.com/RDML-consortium/rdmlpython ; https://raw.githubusercontent.com/RDML-consortium/rdmlpython/master/test/run_analyze_vermeulen_rdml.py
47. RDML schema: v1.4 candidate XSD https://raw.githubusercontent.com/RDML-consortium/rdml-schema/master/RDML_v1_4_CR.xsd ; v1.3 page https://rdml.org/rdml_v_1_3.html ; schema repo (MIT) https://github.com/RDML-consortium/rdml-schema
48. RDES specification. https://rdml.org/rdes.html
49. `ruijter` R data package (Ramiro Magno; Ruijter 2013 technical datasets; CC BY 4.0). https://rmagno.eu/ruijter/ ; https://github.com/ramiromagno/ruijter
50. Brintz BJ, et al. Automated post-run analysis of arrayed qPCR amplification curves using machine learning. Gates Open Res 2025;9:1. https://pmc.ncbi.nlm.nih.gov/articles/PMC11756513/ ; data/code https://github.com/bbrintz/qPCR-amp-call ; https://zenodo.org/doi/10.5281/zenodo.13798820
51. qpcR (CRAN, GPL ≥ 2) https://cran.r-project.org/web/packages/qpcR/refman/qpcR.html ; PCRedux (MIT) https://cran.r-project.org/web/packages/PCRedux/refman/PCRedux.html
52. Drude N, et al. Reporting quality of qPCR methods in scientific publications. Res Integr Peer Rev 2026. https://pmc.ncbi.nlm.nih.gov/articles/PMC12961777/
53. Bustin S, Nolan T. Talking the talk, but not walking the walk. Eur J Clin Invest 2017;47:756–774. https://www.gene-quantification.de/bustin-nolan-miqe-2017.pdf
54. Lot-to-lot verification in clinical chemistry (360 lot changes; QC vs patient-sample disagreement ~7.8 %). CCLM 2022. https://doi.org/10.1515/cclm-2022-1126 ; CLN Bench Matters 2014 https://myadlm.org/cln/articles/2014/july/bench-matters
55. IDT. Storing oligos: 7 things you should know. https://www.idtdna.com/page/support-and-education/decoded-plus/storing-oligos-7-things-you-should-know/
56. Effects of storage conditions on the stability of qPCR reagents (eDNA). BMC Res Notes 2024. https://pmc.ncbi.nlm.nih.gov/articles/PMC11264737/
57. Peng P, et al. A unique Levey-Jennings control chart used for internal quality control in HPV detection. Virol J 2022;19:125. https://pmc.ncbi.nlm.nih.gov/articles/PMC9331565/
58. UgenTec FastFinder QC (Levey-Jennings, preset Westgard rules, cross-contamination by proximity). https://www.ugentec.com/fastfinder/qc ; https://www.ugentec.com/fastfinder
59. FDA. Distribution of IVD Products Labeled for Research Use Only or Investigational Use Only (2013). https://www.fda.gov/media/87374/download ; 21 CFR 809.10 https://www.law.cornell.edu/cfr/text/21/809.10 ; EU IVDR Art. 1(3)(a) https://eur-lex.europa.eu/eli/reg/2017/746/oj
60. Saunders GC, et al. Interlaboratory study on thermal cycler performance. Clin Chem 2001. https://europepmc.org/article/MED/11148176 ; Kim YH, et al. Performance evaluation of thermal cyclers. BioTechniques 2008. https://europepmc.org/article/MED/18476814
61. Statistical assessment of DNA extraction reagent lot variability in real-time qPCR. Lett Appl Microbiol 2010. https://europepmc.org/article/MED/20070509
62. Cost figures: Unicorn Lifescience, PCR Equipment Cost Breakdown https://unicornlifescience.com/pcr-equipment-cost-breakdown-labs-actually/ ; Lab Manager qPCR buyer survey https://labmanager.com/surveys/are-you-in-the-market-for-qpcr-18095 ; UC Davis research services https://pcrlab.vetmed.ucdavis.edu/research/research-services ; Brown Genomics Facility FY26 rates https://biomedcorefacilities.brown.edu/genomics-facility ; ZipRecruiter qPCR technician listings https://www.ziprecruiter.com/Jobs/Qpcr
63. Stadhouders R, et al. The effect of primer-template mismatches on the 5' nuclease assay. J Mol Diagn 2010;12:109–117. https://pmc.ncbi.nlm.nih.gov/articles/PMC2797725/ ; Lefever S, et al. SNPs and other mismatches reduce performance of qPCR assays. Clin Chem 2013;59:1470–80. https://europepmc.org/article/MED/24014836
64. 2023 White Paper on Recent Issues in Bioanalysis (WRIB; qPCR/dPCR, gene therapy). Bioanalysis 2024. https://pmc.ncbi.nlm.nih.gov/articles/PMC11849449/
65. Open lab notebook with full reruns triggered by replicate gaps (heareresearch, 2015). https://eagle.fish.washington.edu/trilobite/notebooks/jake/heareresearch.blogspot.com/search%3Fupdated-max=2015-08-14T18:58:00-07:00&max-results=7&reverse-
66. CDC NWSS reporting guidance (archived) https://archive.cdc.gov/www_cdc_gov/nwss/reporting.html ; Pecson BM, et al. Reproducibility and sensitivity of 36 methods to quantify SARS-CoV-2 in raw wastewater. Environ Sci Water Res Technol 2021;7:504. https://pubs.rsc.org/en/content/articlehtml/2021/ew/d0ew00946f
67. tidyqpcr plate-plan format (Apache-2.0). https://docs.ropensci.org/tidyqpcr/articles/platesetup_vignette.html
68. Vogels CBF, et al. Analytical sensitivity and efficiency comparisons of SARS-CoV-2 RT-qPCR primer-probe sets. Nat Microbiol 2020. https://www.nature.com/articles/s41564-020-0761-6
69. Thermo Fisher. Gene Expression Support — Troubleshooting. https://www.thermofisher.com/us/en/home/technical-resources/technical-reference-library/real-time-digital-PCR-applications-support-center/gene-expression-support/gene-expression-support-troubleshooting.html
70. Lachmann A, Giorgi FM, Alvarez MJ, Califano A. Detection and removal of spatial bias in multiwell assays. Bioinformatics 2016;32:1959–1965. https://academic.oup.com/bioinformatics/article/32/13/1959/1742942
71. medischebiologie.nl downloads (Factor-qPCR, LinRegPCR, "qPCR data with Methods paper"; no licence stated). https://medischebiologie.nl/files/
72. 21 CFR 11.10 (audit-trail wording). https://www.law.cornell.edu/cfr/text/21/11.10
73. Nettle D. Code and data archive for "Consequences of measurement error in qPCR telomere data" (Zenodo 1994386, CC BY 4.0). https://zenodo.org/record/1994386
74. Lane MJ, et al. Simplified analysis of measurement data from a rapid E. coli qPCR method (EPA Draft Method C). Water 2020;12:775. https://www.mdpi.com/2073-4441/12/3/775
75. Zenodo record 18833966 (Ostrea edulis COI eDNA assay data, 2026). https://zenodo.org/records/18833966
76. CDC data.cdc.gov. NWSS Public SARS-CoV-2 Concentration in Wastewater Data (archived 2025). https://data.cdc.gov/Public-Health-Surveillance/NWSS-Public-SARS-CoV-2-Concentration-in-Wastewater-/g653-rqe2
77. ICH Q2(R2). Validation of Analytical Procedures (2023). https://database.ich.org/sites/default/files/ICH_Q2%28R2%29_Guideline_2023_1130.pdf
78. Ruijter JM, et al. Evaluation of qPCR curve analysis methods for reliable biomarker discovery. Methods 2013;59:32–46. https://doi.org/10.1016/j.ymeth.2012.08.011
