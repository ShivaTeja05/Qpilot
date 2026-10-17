# W2 — Red-team review of the qPilot discovery exercise

Date: 17 October 2026. Written for the two qPilot developers. Role: hostile but fair reviewer. I read `00-brief-for-researchers.md`, the Discoveries section of every note 01–17 (plus their pain inventories and open-questions lists), and all six W2 deliverables in full. I did two web checks on claims I distrusted: the Bustin 2025 claim-floor paper (PMC12387016) and the Clarida changelog (clarida.bio/changelog). Everything else is judged on what the notes themselves say and on the two prototypes' numbers.

Short version, so you do not have to read 800 lines before Monday:

- **109 discoveries** were proposed, not ~90. After clustering, **about 14 distinct product ideas** survive; the rest are duplicates, re-skins of the same engine for another domain, or plans rather than features.
- **The two prototypes are the most valuable documents in the folder** and they contradict the rankings in the notes they tested. Note 06 ranked the Plate Residual Map second; the prototype found nothing on 61/64 Vermeulen plates and a 0.06-Cq edge effect on the technical plate. Note 07 ranked the plate-aware mixed model first; the prototype shows it reproduces Welch and the plate term is not even estimable on the demo. What the prototypes *did* find is that the claim floor relabels 23 of 40 calls, the efficiency-model axis flips 4–5 of 58 calls, the non-detect rule moves 4 of 19 estimates by up to 3.3 log2, and Levey-Jennings trending on seven per-plate metrics flags exactly the five odd plates a scientist would want to see. Build what the data showed, not what the notes ranked.
- **The claim floor is one group's proposal, not a field standard.** I verified it: Bustin, Kirvell, Nolan, Mueller, Shipley, *Int J Mol Sci* 2025;26:7796. The authors call the 2×/3×/4× tiers "recommendations … grounded in the data reported in this study", say they are "context-specific and ideally should be determined empirically for each assay system", and the paper's own bootstrap description is internally inconsistent (10,000 iterations in §2.8, 1,000 in §4.8). It is not in MIQE 2.0. Ship it as a named, overridable rule pack and never as a refusal.
- **Clarida is closer than note 12 says.** Its 7 Sep 2026 release "reads your instrument files directly", "shows the raw amplification and melt curves" and "reuses or makes Cq calls with a choice of three methods". Note 12's "raw curves shown but not re-analysed" is no longer safe. The durable differences are: local, unlimited, open method with published per-well efficiency, robustness across choices, hash-chained record, agent-callable. Those are the five things to be known for; nothing in the 109 changes that.
- **The champion user is the academic multi-plate expression lab without a biostatistician** (note 12, the practitioner-voice note, the expert reviewer's question). The domain bake-off's "build eDNA first" is a ranking *among domain plugins*; it never scored the expression core against them, and eDNA's whole literature (540 title/abstract papers) is smaller than one year of gene-expression qPCR. Treat eDNA as a validation showcase with public-domain regression data, not as the first customer.
- **Lab memory has a cold-start problem the spec acknowledges but the notes mostly ignore.** Control-chart limits need ≥20 runs; passports need ≥10; most labs' historical data is in `.pcrd`/`.eds` files that need vendor capture before any retrospective build. Split the spec: the within-study Run Gate ships first (works on plate 1), the cross-run Memory is a month-3+ retention feature.
- **Do not rebuild the MCP surface.** MCP Tasks moved twice in eight months; the client matrix shows no host support for Tasks. Do the cheap parts (annotations, typed refusals, idempotency keys, concise mode) in days and keep the blocking path.

---

## 1. Master list of proposed discoveries, clustered

Counting: 01 (7), 02 (6), 03 (6), 04 (6), 05 (6), 06 (6), 07 (8), 08 (6), 09 (8), 10 (7), 11 (7), 12 (5), 13 (6), 14 (6), 15 (6), 16 (7), 17 (6) = **109**. Plus the ten "pains no wave-1 note evidenced" in `W2-practitioner-voice.md` §6, which are not discoveries but reshape several. IDs below are `note-Dn`. Verdict codes: **KEEP**, **RESHAPE**, **MERGE→**, **DEFER**, **KILL**.

### Cluster A — Signal provenance and vendor capture (getting raw data in, and proving it is raw)

| ID | Title (short) | Verdict | Duplicates / notes |
|---|---|---|---|
| 05-D1 | Raw-reachability contract: capture recipes + Import Trust Card + raw-ness detector | **KEEP** | Same detector as 06-D1; same recipes as 12-D2 |
| 06-D1 | "Is this curve raw?" signal-provenance guard | **MERGE→ 05-D1** | Identical idea; 06 has the better test design (ground-phase offset, subtraction footprint, `ruijter` CC BY data) |
| 12-D2 | Thermo CLI batch-capture kit + public per-vendor RDML conformance table | **KEEP** | The CLI part is the single cheapest high-value capture item; the conformance table duplicates 05-D2 |
| 05-D2 | RDML dialect normaliser and conformance report; ship RDML 1.4/Ncopy path | **MERGE→ 12-D2** | Keep `qpilot rdml inspect`; the 1.4 writer is a nice-to-have |
| 05-D5 | Zero-click capture daemon; map of where GUI automation is truly needed | **RESHAPE** | Watched folder is 16-D2's feature; the valuable output is the *map* (which vendors need GhostDriver at all: Bio-Rad retrospective `.pcrd`, Q-Rex, Mic). Ship the map as docs, the daemon as part of 16-D2, no GUI automation in the first year |
| 01-D2 | Cq provenance diff (vendor Cq vs LinRegPCR vs Cy0 vs fixed threshold) | **MERGE→ 07-D4** | Same thing as the curve-analysis multiverse |
| 07-D4 | Curve-analysis multiverse (baseline, Cq method, threshold universes) | **DEFER** | Real axis (Ruijter 2009 ratio 0.7–9.5 under 2 % baseline error) but 2–3 weeks, and Clarida now offers three Cq methods itself; do the cheap "vendor Cq vs LinRegPCR Cq per well" diff (days) as a Trust Card fact, defer Cy0/SDM/sigmoid reimplementations |
| 10-D7 | dPCR vendor capture (QIAcuity API, per-partition importers) | **DEFER with the dPCR plugin** | Enabling work only |
| 05-D6 | Open qPCR (Chai) live-analysis and classroom mode | **KILL** | Niche 16-well hardware; no user asked for it; a week spent on a demo nobody runs |
| 05-D3 | Allotrope ASM export with calculated-data provenance | **KILL (for now)** | CC BY-NC / CC BY-ND schema licence is unresolved (05 Q, 03 Q10, bake-off [74]); integrators read Cq columns anyway (05 [42-CFX]); no user in the practitioner sample mentioned ASM. Revisit only if a Benchling-connected core asks |

**Cluster verdict.** This is the foundation and the loudest practitioner complaint ("the bigger issue isn't analysis itself, it's data alignment", practitioner item 82; the "skip 27 header rows" workaround, item 86; note 12 §1.5: the recurring technical complaint across trackers is getting data in). The raw-ness detector costs 3–5 days (06-D1 §5) and protects the entire engine from the silent CFX "baseline subtracted by default" failure (06 [12]). The Thermo CLI wrapper is 3–5 days and replaces the roadmap's GUI-automation idea for the biggest vendor. OpenReadout (MIT/Apache, v0.3.0, 13 Oct 2026, 1 star; 05 [48]) now exists and reads `.eds/.ixo/.rex/.lc96p`: pin it as an optional reader rather than writing readers yourselves, and contribute fixtures upstream. Is this in Clarida's path? Yes, Clarida imports instrument files since September 2026, but it cannot publish a conformance table or a raw-ness test as a public good, and it is cloud-only. Effort for the KEEP set: ~3 weeks.

### Cluster B — Run gate and triage (controls on the plate, rules for them, repeat/rescue/ignore)

| ID | Title (short) | Verdict | Duplicates / notes |
|---|---|---|---|
| 15-D1 | Run Gate: named, sourced run-acceptance rules keyed to RDML sample types | **KEEP** | The W2 spec §B is the merged version of this, 01-D1, 04-D4, 02-D4 |
| 01-D1 | Run triage "repeat, rescue or ignore" by consequence and cost | **MERGE→ 15-D1** | The consequence test (spec §C.2) is the genuinely new part; the cost model (§C.3) is a day of work and can wait |
| 04-D4 | Negative-control ledger: dimer vs contamination, trending across runs | **MERGE→ 15-D1 (within-study) + cluster C (cross-run)** | The melt-class rule is G-NTC-1; the cross-run p-chart is Memory |
| 02-D4 | Melt-identity fingerprint and NTC-artefact model per assay | **MERGE→ 15-D1 G-MELT** | rdmlpython MCA already gives peaks; the "fingerprint" needs Memory |
| 11-D7 | Melt-informed quantification corrections (`corrF`) | **MERGE→ G-MELT** | Wiring only; a week; verify how LinRegPCR consumes `corrF` first (11 §5 admits it did not) |
| 04-D3 | gDNA contribution from no-RT wells, ValidPrime-style correction and grades | **KEEP (G-NRT + a correction option)** | Arithmetic; a week; the practitioner sample has a live case (item 29, No-RT at 29 vs 22). Watch the ValidPrime patent note (04 Q4) before the *subtraction* option; the grade is safe |
| 04-D2 | Inhibition gate from curve kinetics (KOD/SOD/ACT) plus spike-ins | **RESHAPE** | KOD is cheap (2–3 days) and is G-REP's kinetic-outlier evidence; SOD/ACT need a labelled inhibited-curve set that does not exist (04 §5). Ship KOD + the spike ΔCq rule; defer SOD/ACT until you have built the tannic-acid titration set 04 proposes |
| 06-D6 | Well Signal Integrity signatures (bubble/step, spike, drift, late, passive-ref) | **DEFER (reporter-only subset KEEP as plate warnings)** | Prototype: STEP 0, SPIKE 0 in 24,576 wells; PLATEAU duplicates LinRegPCR's own exclusions; LATE is a plate-level "no plateau" warning; DRIFT caught 4 wells. Ship DRIFT + LATE as 3–4 days of plate warnings; nothing else until multi-channel vendor capture and labelled bad plates exist |
| 09-D2 | Gene/cell-therapy run-acceptance rule packs (Ma Table 4, FDA LTFU) | **DEFER** | Same rule engine as 15-D1 with a different YAML; no public data (bake-off 3.2 Data = 1); users have LIMS and will ask for Part 11. Build the generic pack loader; write this pack only when a vector core partners |
| 09-D7 | Research "rare-target" rule pack (EuroMRD) | **DEFER** | Same reasoning; clinical adjacency risk |
| 15-D4 | Research-use assay qualification report (ISO 20395 / Ma / ICH Q2(R2)) | **DEFER** | 3–5 weeks; the LOD/LLOQ/linearity pieces come for free from the standard-series substrate (cluster E); the full wizard is a CGT-market feature with no public data |

**Cluster verdict.** This is the second-strongest cluster on evidence and the strongest on practitioner frequency: threshold/Cq cut-off (14 items), NTC/no-RT/contamination (9), replicate outliers (8) are 30 % of the practitioner sample, and "two defensible choices and I cannot tell which changes my answer" is the sample's recurring shape (practitioner §2). Six notes arrived at the Gate independently (spec preamble). Is it a "should" or will a scientist adopt it? Items 1–9 (cut-off folklore challenged, "is there a reference?"), 23–31 (NTC), 15–22 (replicates) are people actively asking for exactly this. Is it in Clarida's path? Clarida has "sample/assay QC" since June 2026 and "plate checks" since July; the changelog does not mention run acceptance, typed-control rules, melt classification or consequence testing. Does it violate constraints? Only if the vocabulary drifts clinical; spec §F.2 handles it. Effort: the spec's two-week Gate v0 is honest *if* the consequence test reuses the existing `QpcrSpace` (0.07 s for 186×58, memory note) and if you drop the cost model, G-GEO, G-IPC and all packs except `research-default` from v0.

One reshaping the spec needs: **G-TYPED will fire on almost every imported plate** because vendor exports arrive untyped (spec §F.1). The first user experience of the Gate must therefore be the "type your controls" prompt, remembered per layout, not a wall of `not_applicable`. Design that screen before the rules.

### Cluster C — Lab memory: passports, control trending, lot bridging, drift

| ID | Title (short) | Verdict | Duplicates / notes |
|---|---|---|---|
| 02-D1 | Assay Passport per primer pair from every RDML run | **KEEP, reshaped as a month-3 feature** | Spec §A.3 is the merged version of this, 06-D3, 15-D2, 01-D3 |
| 06-D3 | Instrument Passport (L-J/Westgard on controls, NTC rate, E, baseline) | **MERGE→ 02-D1 / spec §A.4** | Prototype `s05` shows the trending works on 64 plates of one study |
| 15-D2 | Control-trend engine (L-J + Westgard + lot/instrument event markers) | **MERGE→ spec §B.2** | Identical to 06-D3 and 01-D3 |
| 01-D3 | Lot and batch drift ledger (L-J on IRC and NTC; lot fields in record) | **MERGE→ spec §A.5/B.3** | The 10-field side-car is the right minimal capture |
| 02-D3 | Lot-change gate: deterministic bridging study | **MERGE→ spec §B.3 L-BRIDGE** | 15-D3 is the same with TOST |
| 15-D3 | Lot and run bridging (EP26-style) + run-factor model | **MERGE→ spec §B.3/B.4** | Same |
| 06-D5 | Verification-plate re-analysis (RNase P / CFX qualification plate) | **DEFER** | Narrow persona (cores running $1.2k plates twice a year); a week on top of a plate model that the prototype says adds little on modern blocks |
| 11-D2 | Cross-run melt alignment, "melt passports" | **DEFER with HRM** | Only valuable for HRM typing labs |
| 10-D3 | dPCR study-level uncertainty and lot-specific LoB/LoD | **DEFER with dPCR** | |
| 02-D5 | Lab assay registry with sequence-hash identity, MIQE §1 autofill, paper resolver | **RESHAPE** | The identity layer (spec §A.2) is needed; the "which pair did that paper use" resolver and ELN push are not. Keep the alias table and the one-time sequence prompt; kill the rest for a year |
| 02-D6 | Opt-in cross-lab passport commons | **DEFER (year 2)** | Needs passports first and critical mass; the note itself rates it low-medium |
| 15-D6 | Ring mode (QCMD-style scoring across users/sites) | **KILL** | "The hard part is organising materials and participants, which is a community task, not software" (15 §5). No EQA exists for research targets, and you are not the body to run one |
| 13-D2 (part) | Generated "lab skill" SKILL.md from decision-log statistics | **DEFER** | Cute; needs a decision log with dozens of studies in it |

**Cluster verdict.** The pain is real and the evidence for lot and instrument effects is strong (four master mixes → 10–30-fold spread, 01 [11]; Thermo's own <0.6 Ct lot spec; 6× between-run factors, Ruijter 2015). But three notes (01, 02, 15) independently rate "labs will type lot numbers" as medium at best, and the spec names identity (assay/instrument/control mapping without sequences or serials) as the hardest part. The prototype's trending worked because one study had 64 plates in date order; a 3-vs-3 lab produces 20 plates a year. **This is a retention feature, not an acquisition feature.** The cold-start resolution: (1) the Gate ships with textbook thresholds labelled provisional; (2) trending starts *within a study* (the prototype's `s05` is 70 lines) and only becomes "memory" when the workspace crosses ≥10 runs for a Series; (3) retrospective `memory build` over a lab's old RDML folder is promised in the spec but most labs have no old RDML — they have `.eds`/`.pcrd`, so retrospective memory depends on cluster A. Do not sell lab memory in the first six months; sell the Gate and let memory accrue.

One correction to the spec: the prototype found that first-20-plate L-J limits are poisoned by a single outlier (ALUsq pulled the slope mean down and fired 10x on 25 plates). The spec §B.2 still says "mean and SD from the first 20 measurements". Make robust limits (median/MAD) the default, not an option.

### Cluster D — Plate map, design-time checks, multi-plate assembly and correction

| ID | Title (short) | Verdict | Duplicates / notes |
|---|---|---|---|
| 03-D1 | One plate-map object (RDML + sidecar) compiling to robot, instrument, analysis, with round-trip verify | **RESHAPE** | Keep the *verify* half (design vs as-run diff from the vendor export): a week, deterministic, catches the undetectable mis-load. Defer the *writers* to QuantStudio TXT and CFX only; LC480/Tecan/Hamilton/Opentrons writers are vendor-fragile byte formats you cannot test without hardware |
| 05-D4 | Plate-layout round trip through vendor setup files + "what actually ran" check | **MERGE→ 03-D1** | Same feature from the format side |
| 03-D6 | Three-way as-designed / as-pipetted / as-run reconciliation | **MERGE→ 03-D1 verify** | Without a robot log the chain starts at the instrument export anyway |
| 03-D2 | Design-time "can this study be analysed?" check (overlap graph, IRC count, controls, randomisation) | **KEEP (checks), DEFER (randomiser)** | The analysability facts (Ruijter substitution rounds, IRC sameness, NTC/NRT per plate) are combinatorics on `qpilot plan` output: ~1 week. qPCR-specific evidence for randomisation benefit is thin (03 §7 admits it); the PlateLayout reimplementation can wait |
| 01-D4 | Multi-plate assembly with layout-as-loaded verification and overlap-based correction | **MERGE→ 03-D1 verify + 03-D3** | |
| 03-D3 | Inter-plate correction as a robustness axis (Ruijter factor vs Hellemans IRC vs none) | **KEEP** | 1–2 weeks; published equations; but the prototype could not validate it (one gene per plate) and the group contrast is provably invariant to plate factors in that design. Validate on the paper's worked 6-plate example and `ruijter` CC BY data with synthetic factors |
| 06-D4 | Between-run factor correction (Ruijter 2015) in the robustness grid | **MERGE→ 03-D3** | Same algorithm, four times |
| 04-D6 | QC-ready plate design rules in `qpilot plan` + MIQE §2/3/5 map | **MERGE→ 03-D2 + cluster F** | |
| 06-D2 | Plate Residual Map with spatial statistics | **RESHAPE to a diagnostic, not a product** | Prototype: 3/64 plates at Moran p<0.05 (= null rate); technical plate edge effect +0.06 Cq. Keep the 170-line engine as an "instrument uniformity" fact computed when a plate has ≥24 technical replicates (verification plates, `ds_380`-like); never raise a card from it on ordinary plates; never mention "edge effects" in the pitch |
| 03-D4 | Opentrons / PyLabRobot closed loop | **KILL (year 1)** | Audience is cores and automation labs (03 §7 admits "small share of qPilot's academic users own robots"); untestable without hardware; liability |
| 13-D6 | Closed-loop "next experiment" JSON for PyLabRobot/Opentrons/LINQ | **RESHAPE** | The useful part is `qpcr_repeat_plan` → a well list a human pipettes (spec §D.3), which the Gate already produces. Drop the robot executors and the A-Lab gating language |
| 13-D5 | Cards delivered over Slack/Teams/ELN; Benchling Results Tables write-back | **RESHAPE** | Webhook digest is 16-D2 (keep); Benchling Results Tables are beta (14 Oct 2026) with no test tenant: kill |
| 03-D5 | ELN/LIMS push: `.eln` RO-Crate for eLabFTW/RSpace; Benchling plate-keyed results | **RESHAPE** | `.eln` RO-Crate export is 3 days and generalises the stretch item; keep. eLabFTW API push is a week against a free docker: fine, later. Benchling: kill until a tenant exists |

**Cluster verdict.** The verify step is the one piece with a clean story ("pipetted against the wrong layout" is undetectable today, 01 [67]) and it needs only the vendor export you are already parsing. The writers are where effort goes to die: five vendor formats, two robot formats, all undocumented in the details that matter (03 §5 Q1–Q5). The practitioner note found **no clean "wrong layout" complaint** in 103 items and says not to downgrade P12 on that basis (r/labrats was unreachable); I half agree: keep verify because it is cheap, not because the pain is proven frequent.

### Cluster E — Study-level statistics, claim floor, efficiency, non-detects, Cq-only mode

| ID | Title (short) | Verdict | Duplicates / notes |
|---|---|---|---|
| 07-D3 | Claim floor: Cq-tier minimum credible fold change + replicate-level bootstrap | **KEEP, reshaped** | 01-D5 is the same. Prototype: relabels 23/40 calls. See the provenance discussion in §2.6 below: ship as `bustin2025-tiers` rule pack, overridable, as a label on every grid cell, and honour the paper's own "unless high measurement precision is demonstrated" clause |
| 01-D5 | Claim guard | **MERGE→ 07-D3** | |
| 07-D1 | Efficiency-model sweep + delta-method propagation | **KEEP (sweep), KEEP-but-do-not-promise (propagation)** | Prototype: the sweep flips 4–5/58 calls and moves NTRK1 ×0.39; propagation changes nothing at n=366 wells (SE(E)≈0.0013) and only matters at n≤12. Half a day for the formula, 2–3 days for the axis |
| 07-D2 | Study-level plate-aware censored mixed model with prediction intervals | **RESHAPE: ship the PIs and the censored axis; DEFER the mixed model** | Prototype: per-target LMM = Welch (0 changes); joint LMM shifts via the normaliser, not the model, and gives one SE to every gene; plate term unidentifiable. PIs are one line of code and are what MIQE 2.0 asks for. Do not spend 3–4 weeks on the LMM until you have a multi-gene-per-plate dataset |
| 12-D4 | Censored non-detect card (drop / censor / impute / substitute) as a grid axis | **KEEP** | Prototype: moves 4/19 estimates by up to 3.3 log2 (NHLH2 15×→150×); practitioner item 103 (20 % missing, contradictory folk advice, 9 upvotes). 3–4 days with the singular-Hessian guard |
| 07-D5 | Replicate-structure guard, "what is your n?", variance components | **KEEP (guard), DEFER (components)** | The "are A1–A3 one cDNA or three animals?" card and the refusal of p-values at n<2 biological units cost days and address the 46 % pseudoreplication finding (07 [35]); variance components need the LMM |
| 07-D7 | Reference-gene decisions on efficiency-corrected inputs; NormFinder from the model; "algorithms disagree" card; co-regulation screen | **KEEP (co-regulation screen + disagreement card), roadmap already has NormFinder** | A week. The expert reviewer's "control:control ratios are the guide" is already implemented as the reverse-normalisation guard; the co-regulation screen (Sundaram's Gapdh/Tbp pairs) is the missing half |
| 12-D5 | Cq-only mode with an explicit "efficiency assumption" card | **KEEP** | Contested below (§2.7). Every open tool and both AI products are Cq-only; practitioners mostly have Cq exports; Clarida's free tier is Cq-only. One week. Cap Study Confidence at "Low" with the reason named |
| 12-D1 | Open qbase+ successor: import qbase+ archives, run the qBase model | **DEFER until two donor workspaces exist** | Format undocumented; population finite and shrinking; Clarida already offers read-only import. The qBase method card (Hellemans 2007 IRC + error propagation) is worth having independently and is 03-D3's IRC branch |
| 07-D6 | Methods paper: specification-curve framework for qPCR | **KEEP as a deliverable, after six months** | 6–10 weeks of writing; the only durable credibility move; needs D1/D3/D4 to exist and the Ruijter/Vandesompele schools as reviewers |
| 09-D5 | Objective CNV calls with propagated error | **DEFER** | Niche, flat, ddPCR-dominated; the qBase error model is reused from 03-D3 |

**Cluster verdict.** This is where the prototype earned its keep: three of the five cheapest items in the whole exercise (claim floor 2–3 days, efficiency axis 2–3 days, PIs half a day, non-detect axis 3–4 days) all changed something on real data. None is in Clarida's changelog (no prediction intervals, no non-detect policy, no efficiency-model sweep, no claim floor). An agent ecosystem cares: these are exactly the facts that stop a model from stating "1.6-fold up, p<0.05" as if it were resolved. Effort for the KEEP set: ~2 weeks.

### Cluster F — Reporting, reviewer-proofing, MIQE, deposition, audit posture

| ID | Title (short) | Verdict | Duplicates / notes |
|---|---|---|---|
| 14-D1 | MIQE 2.0 Auto-Report: 53 items, 28 from the record, three journal renderings | **KEEP (one rendering)** | 01-D6, 07-D8, 04-D6 and 08-D6 are the same idea for different item subsets. The machine-checkable / human / never split is the real content; one rendering (MIQE 2.0 Table 1 + JSON) is enough; the 2009 and Clin Chem docx renderings can wait for a journal to ask |
| 01-D6 | Machine-checkable MIQE 2.0 (class A/B/C map) | **MERGE→ 14-D1** | |
| 07-D8 | Machine-derived MIQE §5 data-analysis statement | **MERGE→ 14-D1** | |
| 10-D5 | dMIQE2020 auto-filled | **DEFER with dPCR** | |
| 08-D6 | FAIR export, Thalinger checklist, GBIF Darwin Core, transfer card | **DEFER with eDNA** | |
| 14-D2 | Reviewer's Report: eight deterministic checks with field base rates | **KEEP** | 1–2 weeks; this is the roadmap's "reviewer-critic agent" made deterministic, and it answers the expert reviewer's "where is your space" in one page. Practitioner item 32 (PolyIC dataset about to be dropped after a reviewer asked about GAPDH, 2 Oct 2026) is the use case |
| 14-D3 | Fact-bound SuperPlot figures with n-honest captions and source data | **KEEP** | A week; matplotlib; the figure is a view of the record. 85.6 % of papers use bar graphs that hide distributions (14 [57]); "redrawn for the third reviewer" is every paper |
| 14-D4 | One-click deposition: GEO workbook, RO-Crate to Zenodo/BioStudies/Dryad, DMS paragraph | **RESHAPE** | Zenodo deposit of the record + RO-Crate is 3–5 days and overlaps the `.eln` export; GEO's RT-PCR route needs ≥20–50 genes and curator expectations you cannot test; DMS paragraph is a template. Do Zenodo + RO-Crate; skip GEO |
| 15-D5 | Honest audit posture: Part 11 vocabulary mapped to the record without the claim | **KEEP** | Days; wording only; it is what cores and CGT labs will ask |
| 14-D6 | Teaching mode with seeded-error datasets graded by the robustness engine | **DEFER** | Instructor adoption is slow and unpaid (14 §7 admits "no willingness-to-pay evidence"); the classroom worksheet already exists; licences of the perturbed datasets need checking |

**Cluster verdict.** MIQE auto-fill is the one item the brief explicitly says is "not a discovery on its own"; 14-D1's item-by-item split clears that bar. The Reviewer's Report is the better product: it is short, it is bound to facts, and it is the artefact a PI will actually forward. Clarida sells a "MIQE score" and methods text; AnnealIQ has a MIQE checklist; this is table stakes for a paid tool, so you need it, but it is not what you will be *known for*.

### Cluster G — Core facilities

| ID | Title (short) | Verdict | Duplicates / notes |
|---|---|---|---|
| 01-D7 | Core-facility hand-off bundle: client "what happened to your run" page | **MERGE→ 14-D5** | |
| 14-D5 | Core-facility client report and "why did this run fail" | **KEEP, as the Gate line per target rendered as a page** | Spec §D.1 already says the Gate summary line *is* the client QC page; so this is a template on top of cluster B, not a feature |
| 16-D4 | Core-facility qualification kit (`qpilot qualify`, traceability stamps, SOP template) | **RESHAPE** | `qpilot qualify` (run the public benchmark on this PC, write an IQ/OQ-style page) is a week and doubles as your CI acceptance test: keep. SOP template and 2-hour training module: write when a core pilots |

**Cluster verdict.** Three notes (01, 14, 16) want the core as a customer; all three say the evidence is inferred from SOPs and price lists, not from core complaints (01 Q7, 14 §5, 16 Q1). The "72 % of cores cannot identify the raw data behind figures" number is load-bearing and its source is disputed (16 cites [42]; 12 §5 Q11 says it could not be located). Verify it before it goes in a pitch.

### Cluster H — Agent contract, benchmark, security, distribution, sustainability

| ID | Title (short) | Verdict | Duplicates / notes |
|---|---|---|---|
| 13-D1 | Agent Contract v2: handles, Tasks, MRTR elicitation, annotations, idempotency, typed refusals, trace context | **RESHAPE: do the cheap half, defer the protocol half** | Annotations (`readOnlyHint` etc.), `outputSchema`, typed refusal codes, idempotency keys on `qpcr_decide`, `response_format: concise`, `resource_link` for curves: 1–2 weeks, no spec risk. Tasks + MRTR: 13 §7 admits "Tasks moved twice in 8 months" and "the client matrix shows no Tasks column at all". Keep the blocking path; revisit when a host you care about supports Tasks |
| 13-D2 | Ship the `qpcr-analysis` Agent Skill; PyPI + MCP registry; Claude plugin; ChatGPT import | **KEEP** | 3–5 days; the SKILL.md rule "never compute Cq or ΔΔCq yourself; call the engine" is the single most important sentence for agent users. The "lab skill" generator: defer (cluster C) |
| 13-D3 | qPCR-AgentBench: public benchmark judged by the engine | **RESHAPE** | Keep it internal (the existing ~50-question harness + F2 no-naked-numbers + F3 refusal + F4 injection) as CI; 2–3 weeks for a public v0 with a private split and CC BY-SA data constraints is not the best use of two developers in year one. Publish it with the methods paper |
| 13-D4 | Untrusted-content firewall for instrument exports; hash-pinned manifests | **KEEP** | ~1 week; quarantining free-text fields (sample names, descriptions) as quoted data is the right design and cheap; F4 becomes a CI test |
| 16-D1 | Zero-admin distribution matrix; "first result in 15 minutes on a locked-down PC" | **KEEP** | Practitioner items 71–79: Mac/M1 install failure, "install it in a Windows VM", Windows-7-only vendor software, shared instrument PC. Portable Windows zip + `uv tool install` + `qpilot doctor`: ~2 weeks. Check packager licences (PyInstaller's GPL-with-exception bootloader vs your no-GPL rule) |
| 16-D2 | Watched-folder analyser with Slack/Teams/e-mail digest bound to record hash | **KEEP (later)** | A week; merges 05-D5 and 13-D5's chat half; only after the Gate exists so the digest has something to say |
| 16-D3 | Trust Pack (SBOM, attestations, egress test, data-flow, pseudonymisation, SMP, DOI) | **KEEP, mostly docs** | Much of it already exists (brief: SBOM, threat model, offline test); the pseudonymisation of sample names before anything leaves the machine is the one new feature (3–5 days) and matters for human-sample labs (EDPB para. 22) |
| 16-D5 | Two-machine offline workflow: `study.qpilot` pack/verify over USB and e-mail | **KEEP** | 1–2 weeks; the record format already defines the content; the browser-only verifier is a nice demo |
| 12-D3 | Maintained permissive engine-as-library with tidy schema and an R bridge | **KEEP** | Days for the tidy export; a week for `qpilotr`; the R user base is small but real and underserved (`pcr` archived Nov 2025, tidyqpcr stalled, EasyqpcR gone) and it is the group most likely to cite you. Upstream a release workflow PR to rdmlpython (PyPI three years behind GitHub) |
| 16-D6 | Community, teaching and publication plan | **KEEP as a plan** | GitHub Discussions as the one venue; JOSS at month 6; it is not a feature |
| 16-D7 | Funding and sustainability roadmap | **KEEP as a plan** | SMP and CITATION.cff now; EOSS when a cycle opens |

**Cluster verdict.** Distribution is under-rated by every note except 16 and the practitioner voice, and it is the precondition for the champion user ("I have tonnes of data … I just want to do it at my PC rather than sitting in the lab all day", item 75). Note 12's gap matrix row "Free-and-unlimited with a modern UI: empty" is the commercial position, and it is only real if a student can install the thing without IT.

### Cluster I — Pre-analytics (RNA quality, RT step)

| ID | Title (short) | Verdict | Duplicates / notes |
|---|---|---|---|
| 04-D1 | Per-sample fitness dossier from TapeStation/Bioanalyzer/NanoDrop/Qubit exports joined to the curves | **DEFER** | Good instinct, but 4–6 weeks (five parser families + mapping UI + regression), no public corpus pairing QC exports with RDML plates (04 Q3), and the key is free-text sample names. The integrity regression (Cq vs RIN by group) is the valuable 10 %: offer it as a CSV column (`rin`) on the sample sheet first, parsers later |
| 04-D5 | RT step as a first-class covariate: form, variance decomposition, confounding check, RT-replicate planning | **RESHAPE** | The confounding crosstab (group × rt_batch × extraction_batch × plate) is a day of work on sample-sheet columns and catches a wrong-conclusion failure mode; keep that. Nested variance decomposition needs RT replicates nobody runs; defer |

### Cluster J — Assay design and in-silico checks

| ID | Title (short) | Verdict | Duplicates / notes |
|---|---|---|---|
| 02-D2 | In-silico pre-flight of existing assays against pinned genome packs (isoforms, SNPs, pseudogenes, dimers) | **DEFER (year 2)** | 3–5 weeks for human/mouse/rat, packs of hundreds of MB per species, laptop-speed genome-wide mismatch search, and a 3′-mismatch scoring table you would have to publish and defend. Real pain (>80 % of human primers overlap a variant) but it is a second product. The one cheap piece: predicted amplicon Tm vs observed passport Tm, when passports exist |
| 17-D4 | Isoform-aware assay coverage check against the lab's own transcript quant | **DEFER with 02-D2** | Same engine, narrower; 1–2 weeks; needs Ensembl FASTA/GTF the user downloads |
| 11-D3 | Permissive in-silico melt prediction (partition function) + heterozygote composites | **KILL** | 3–5 weeks to reimplement uMelt's model; absolute Tm is off without instrument calibration (11 [28]); serves HRM, which is deferred |

### Cluster K — Multi-omics hand-offs and HT-qPCR

| ID | Title (short) | Verdict | Duplicates / notes |
|---|---|---|---|
| 17-D1 | RefSeek: reference-gene candidates from the lab's own RNA-seq, feeding geNorm | **KEEP (small)** | 1–2 weeks, numpy only, closed-form rules, SEQC acceptance test. Evidence is strong (87 % single reference, 72 % GAPDH/ACTB/18S alone; data-derived candidates beat classics in every study read). It is the upstream half of the reverse-normalisation guard. Keep the atlas lookups off by default (local-first) |
| 17-D2 | Concordance Report: RNA-seq vs qPCR agreement with pre-declared definitions and robustness | **KEEP (small)** | 1–2 weeks; Bland–Altman on log2FC, pre-registered definitions locked in the record, verdict across the grid. The top-scoring practitioner item (70 upvotes) is this argument; item 91 names the publication-bias mechanism ("brute force qPCR setup until it does agree") that a hash-chained record counters |
| 17-D3 | Validation Study Planner from a DEG table (symbol gate, stratified panel, power, hand-off bundle) | **RESHAPE** | The symbol gate (date/float patterns, HGNC previous symbols) is 2–3 days and fixes the best-quantified pain in the folder (19.5–30.9 % of articles with Excel gene lists corrupted); keep it as an import check everywhere a gene list enters. The stratified panel and bundle: defer |
| 17-D5 | HT-qPCR panel plugin (Biomark / OpenArray / TaqMan Array Card) | **DEFER** | Cq-mode only (no raw curves), vendor column names unverified (17 Q3–4), needs a core's files; a 12-D5 Cq-mode importer variant once Cq mode exists |
| 09-D8 | Biomark/single-cell import with Fano LoD | **KILL** | "Shrinking community"; low-medium confidence by its own author |
| 17-D6 | nCounter RCC import + RUV normalisation robustness | **KILL** | Not qPCR; RCC spec not obtained; platform changed hands |

### Cluster L — New-domain plugins (the bake-off candidates)

| ID | Title (short) | Bake-off score | Verdict | Notes |
|---|---|---|---|---|
| 08-D1 | eDNA assay LOD/LOQ passport (Klymus 2020 curve fits, model-choice grid) | 93 | **RESHAPE into a generic "standard-series substrate" for every user** | See §2.1. The maths (detection per standard, log-dose models, LOD at 95 %, effective LOD for n, LOQ from CV) is the same thing an expression lab needs to derive its own Cq cut-off and LLOQ instead of "35 / 38 / 40" (practitioner items 1–9). Build it once, generically; the USGS public-domain data is the regression test; eDNA labs get it for free |
| 08-D2 | eDNA detection-call and control-negation engine (QAPP rule pack, occupancy export) | (in 93) | **DEFER until an eDNA lab partners** | Rule-pack machinery is cluster B; the QAPP-specific negation logic and GBIF export are 3–4 weeks for a segment with "agencies adopt third-party software slowly" (08 §7) |
| 08-D3 | Composite (master) standard curves + absolute quant with EPA/ENGL acceptance | 78 | **DEFER** | Shared base for 09-D2, 08-D4, 08-D5; 3–5 weeks; the per-run weighted regression and the standard-vs-sample efficiency check fall out of the substrate; pooled curves and three method cards wait for a wastewater/beach lab |
| 08-D4 | NWSS/PHES-ODM wastewater run packet | 64 | **KILL** | Past-peak funding, dPCR-dominated, NWSS dataset archived, PHES-ODM in maintenance mode, dictionaries drift. The bake-off's own words |
| 08-D5 | GMO % module (ENGL / ISO 21570) | 64 | **KILL** | Accredited labs will not swap a regulator-accepted spreadsheet; 6 title/abstract papers a year |
| 09-D1 | Telomere Study Mode | 87 | **DEFER to the first domain pack, conditional on a TRN lab partner** | Best domain candidate: CC BY/CC0 data, an NIH-sponsored consortium that asks for exactly this computation (ICC, protocol-as-fixed-effect), no competitor. But Cq-level public data only, MMqPCR two-acquisition mapping in RDML is unsolved, and the community is flat (114 papers/year). 3–4 weeks after the core is stable |
| 09-D4 | miRNA panel normalisation robustness + hemolysis cards | 76 | **DEFER** | Cheap (1–2 weeks on geNorm) but no public dataset (Faraldi "on request"), the 384-well TLDA import is itself a roadmap item, and Clarida could add it in a month |
| 10-D1 | dPCR partition-level "classify it every reasonable way" | 80 | **DEFER (year 2)** | 4–7 weeks; six classifiers from GPL/Artistic R tools reimplemented; rdmlpython dPCR support unverified (bake-off §7); vendor exports drift per version. The biggest community but the wrong year |
| 10-D2 | dPCR constants ledger (partition volume provenance) | — | **DEFER with 10-D1** | 2–3 days once 10-D1 exists; a lovely "no naked numbers" story |
| 10-D4 | Multiplex cluster assignment with orphan cards | — | **KILL** | "Hard problem; vendors are improving"; medium confidence from its own author |
| 10-D6 | dPCR application packs (CNV, VCN, wastewater, GMO) | — | **DEFER with 10-D1** | |
| 11-D1 | Open HRM genotyping engine | 59 | **KILL (year 1)** | Declining literature (244→159 papers/yr), Utah patents (US 8,296,074 expiry date is a Google assumption; US 8,068,992 reinstated to 2029), the Li 2014 "70.3 % / commercial worse" claim unverified, no raw-curve dataset with sequencing truth |
| 11-D4 | MS-HRM methylation quantification | — | **KILL** | Smaller than HRM |
| 11-D5 / 09-D3 | Allelic-discrimination / full-curve genotyping caller | 59 | **KILL (year 1)** | No public two-dye raw dataset; free vendor callers users accept; Clarida shipped genotyping on 12 Oct 2026, so it is now in the incumbent's path |
| 11-D6 | Open HRM benchmark + "never-seen genotype" card | — | **KILL with HRM** | |
| 09-D6 | ChIP-qPCR %input module | — | **DEFER (days when someone asks)** | Correct, tiny, low impact |

**Cluster verdict.** The bake-off is a careful document and I accept its ranking *among domain plugins*. I reject its framing that a domain plugin should be built in weeks 1–3. See §2.1.

### Cluster M — Teaching and demo

Covered: 14-D6 DEFER, 05-D6 KILL, 16-D6 plan. The existing classroom worksheet is enough for year one.

---

## 2. Contradictions and tensions between notes, with resolutions

### 2.1 Champion user: note 12's academic multi-plate expression lab vs the bake-off's "build eDNA first"

The evidence for the expression lab as champion is the broadest in the folder: note 12 §1.9 gap matrix (per-well efficiency + multi-plate statistics + record: "nobody ships it"), the practitioner note (reference genes, Excel/ΔΔCq, cut-offs and efficiency are 51 % of 103 items; eDNA appears zero times), the expert reviewer (who assumed an expression lab), and the brief's own "Already built" list, which is an expression-lab engine. The bake-off never scored this baseline; its rubric weights "champion with a mandate" and "public data with licence" in ways that structurally favour agency-driven niches. eDNA's entire qPCR literature is 540 title/abstract papers (bake-off A1); gene-expression RT-qPCR is tens of thousands a year.

Resolution: the eDNA candidate's *maths* (standard-series detection table, log-dose LOD fits, effective LOD for n replicates, LOQ from CV, outlier-standard cards) is not domain-specific. An expression lab needs exactly this to answer "where do I draw the Cq line and why" (practitioner items 1–9: two separate people asked for the reference behind the "mid-30s" folklore and got none). Build it as the **standard-series substrate** in the qPCR core, regression-test it against the USGS public-domain release, and let eDNA labs be the first *external* validators rather than the first customers. What would settle it the other way: a signed pilot with an eDNA consultancy or agency lab before month 3. Without that, eDNA-first is building for a persona you have never spoken to.

### 2.2 Plate-map object: note 03 (RDML as the plate-map object) vs note 05 (vendor setup files are the only way in)

Not actually a contradiction. 03-D1 proposes RDML as qPilot's *internal* object and writes vendor files from it; 05-D4 proposes writing the same vendor files from `qpilot plan`. Both agree the instrument cannot read RDML (the project memory confirms: "vendor desktop cannot import RDML (no write-back) but plate layouts can be pushed in"). The real tension is effort: seven writers across two notes, none testable without the vendor software installed, and the LC480 import format, the CFX `.plrn` row positions and the Opentrons HTTP routes all unverified (03 §5). Resolution: one object (RDML + sidecar), *verify* first (reads the vendor export you already parse), writers only for QuantStudio TXT (documented) and CFX spreadsheet import (practitioner item 80 names it as annoying), and only when a user has an instrument to test against.

### 2.3 The expert reviewer's "where do you see your space?"

The reviewer (project memory, 17 Oct ~16:15) said: multi-gene normalisers are standard, reference genes should be tested for design effects, control:control ratios are the guide, big-panel groups already have robust workflows, bench scientists have Excel. The notes answer this three ways, and they are consistent: (a) note 12's matrix — the position "how many defensible analyses agree with the conclusion" is empty everywhere, and "open, local, maintained, raw-curve" is effectively only R scripts; (b) the practitioner note — "the recurring shape of the complaint is not 'I can't compute ΔΔCq' but 'there are two defensible choices and I cannot tell which one changes my answer'" (§2), and nobody in 103 items mentions Clarida, qbase+, GenEx or LinRegPCR by name — the competition is Excel, the vendor's own software, Prism and R; (c) the retro-analysis in memory — 17 of 58 genes flip between defensible ≥3-gene normaliser sets on Vermeulen; geNorm V 0.33–0.56 means no normaliser on that panel is validated.

The answer to the reviewer is therefore: the space is *between* the big-panel group with a biostatistician and the bench scientist with Excel — the multi-plate study where the analysis choices are defensible either way and nobody can tell which one the conclusion rests on; and the deliverable is not a better ΔΔCq but a record that says how fragile the answer is and why. The reviewer's "control:control ratios" point is already the reverse-normalisation guard; make it the headline, not a card. What would strengthen the answer: five labs' real multi-plate studies run through the robustness grid with the flip counts published. That is the methods paper (07-D6) and it should be the first external validation you do.

### 2.4 Lab memory needs an archive a new user does not have

Three notes (01-D3, 02-D1, 15-D2) and the spec describe passports and control charts as if the longitudinal store exists. The spec is honest in §F.1 ("20 points per Series may take months") and §E.3 ("only a lab archive supplies …"). The prototype worked because Vermeulen is 64 plates in date order; a typical lab has 20–50 plates a year per assay. Most historical data is not RDML (14 §2 P4: <10 RDML depositors in ten years; vendor RDML is unreliable per 05 P2), so the retrospective `memory build` depends on cluster A. Resolution: split the spec into Gate (within-study, day one) and Memory (cross-study, accrues); show "provisional" everywhere; make the first memory-like feature the within-study trend the prototype already demonstrated. Treat lab memory as the reason a lab stays, not the reason it tries you.

### 2.5 "Agent contract v2" rebuild vs shipping features

13-D1 wants handles, Tasks, MRTR elicitation, annotations, idempotency, typed refusals, trace context; its own §7 says Tasks moved twice in eight months and no host tabulates Tasks support. Meanwhile every other cluster needs the engine to grow. Resolution: the parts that are pure JSON (tool annotations, `outputSchema`, typed refusal codes, idempotency key on `qpcr_decide`, concise/detailed response format, `resource_link` for curves) are 1–2 weeks and have no spec risk; do them. Tasks and MRTR: wait for a host you care about to support them, and keep the blocking path that works in MCP Inspector today. What would resolve it: Claude or ChatGPT shipping Tasks support in their client matrix.

### 2.6 The claim floor: whose rule is it, and is it accepted?

Verified today (PMC12387016). The 2×/3×/4× tiers are in §3.7 of Bustin, Kirvell, Nolan, Mueller and Shipley, *Int J Mol Sci* 2025;26:7796, introduced as "recommendations … grounded in the data reported in this study", from 12–16 technical replicates at four concentrations on five assays (GAPDH-A, ACTA2-A, CDKN1A, IGF-1, *C. auris* rRNA) on Bio-Rad and BMS Mic instruments. The authors write: "we emphasise that they are context-specific and ideally should be determined empirically for each assay system", and the Limitations section repeats it. The paper's bootstrap is described as 10,000 iterations in §2.8 and 1,000 in §4.8; the efficiency lists differ between Methods and Results. The "six technical replicates for 1.5-fold at SD 0.5" is a power calculation, not a bootstrap result. It is **not** in MIQE 2.0; MIQE 2.0 asks for uncertainty and prediction intervals, not fold-change tiers. So: a serious proposal from the MIQE lead author's group, four months old, not a field consensus.

Notes 01-D5 and 07-D3 say this correctly ("tiers are a proposal from one group … expose them as a named, versioned rule pack"). The W2 spec's G-CLAIM and the study-model prototype's "23 of 40 calls relabelled" treat the tiers as a default rule, and the prototype takes the floor from the *less precise group's* mean Cq, which pushes 26 of 58 genes into the 4× tier. On a study with 53 vs 294 biological samples and bootstrap CIs that never include 1, relabelling 58 % of calls as "below credible floor" is not credible: the tiers were derived from *technical-replicate* uncertainty and the paper itself attaches "unless high measurement precision is demonstrated" to the Cq>30 tier. Resolution: (1) name the pack `bustin2025-tiers` and cite it; (2) apply the floor only when the study's own CI does not already demonstrate the precision (i.e. the label is "below floor *and* precision not demonstrated"); (3) when the lab has standards or technical replicates, derive the lab's own floor from its replicate SD, which is what the paper asks for; (4) never refuse a number, only label it. Re-run `s5_claimfloor.py` with rule (2) and report the new count; I expect it to fall from 23 to well under 10.

### 2.7 Cq-only mode vs "raw curves are the product"

12-D5 argues every competitor is Cq-only and so are most users' exports; the brief defines qPilot by raw curves; the bake-off's generalisation table says LinRegPCR is what makes qPilot different. Both are right. Resolution: Cq-only mode is the door, not the house. Ship it in a week with Study Confidence capped at "Low: efficiency assumed", the efficiency-assumption card, and a one-line nudge ("ask your core for the RDML / use the capture recipe"). Clarida's free tier is Cq-only and metered; an unlimited local Cq-only mode with the robustness grid is already better than the free tier, and it funnels toward raw curves.

### 2.8 Other tensions worth naming

- **Note 06 ranked the Plate Residual Map #2 and Well Signal Integrity #6; the prototype found nothing actionable for either on the demo data.** Note 06's own risk line anticipated it ("the 7900HT-class instruments are ageing out; modern blocks are tighter"). The map is now a diagnostic for technical-replicate plates only.
- **Note 07 ranked the mixed model #1 and the claim floor #3; the prototype inverted that.** The note's D2 risk line ("over-complex for 1-plate, 3-vs-3 studies") was right for a different reason: it is unidentifiable on the demo and reproduces Welch where it is identifiable.
- **Note 12 §1.2 says Clarida shows raw curves but "as far as I can document" does not re-analyse them.** The changelog (fetched today) says Clarida "reuses or makes Cq calls with a choice of three methods" and "calculate efficiency" (April 2026). Whether that is per-well LinRegPCR-style efficiency is still unknown; do not claim Clarida cannot re-quantify.
- **Note 13 proposes a public qPCR-AgentBench; the brief already has a ~50-question harness.** Same thing; keep it internal until there is a paper to attach it to.
- **Note 16-D1 recommends packagers whose licences it did not verify and warns PyInstaller's bootloader is GPL-with-exception.** Resolve before the first Windows build.
- **Note 02-D2 wants offline genome packs of "a few hundred MB per species"; note 16 wants a 15-minute install on a locked-down PC.** They cannot both be in the default download.
- **Note 05 and note 03 both want to vendor or validate against Allotrope ASM; both flag the CC BY-NC/BY-ND licence.** Nobody resolved it; treat ASM as out until Allotrope answers in writing.
- **Audit numbers drift between notes**: "432 papers" (01, 15), "439 papers" (14), "2024 papers 1 % efficiency" (07, 15, from Bustin & Wittwer 2026 whose text note 12 says it did not obtain, and whose "non-significant decline P=0.12" the project memory records). A vendor page's "13 % → 1 %" is explicitly unverified (01 Q5, 02 Q3). Pick one audit (Drude 2026, CC BY, with data on OSF — 14 [5]) and quote only it.

---

## 3. The strongest version of the thesis: what qPilot should be known for in 12 months

Ordered for a two-developer team. Effort figures are the notes' own estimates, cross-checked against the prototypes where they exist.

### 3.1 "It tells you how fragile your answer is" — the robustness grid with honest numbers on every cell

This exists; what is missing is the four cheap layers the prototype proved matter. Claim floor as a named, overridable rule pack applied with the paper's own "unless precision is demonstrated" clause (2–3 days; prototype `s5`: 23/40 calls relabelled under the naive rule, expect far fewer under the honest one). Efficiency-model axis {per-assay mean, per-well, assumed 2.0, dilution series} (2–3 days; prototype `s4`: flips 4–5 of 58 calls, NTRK1 ×0.39 at Cq 32–38). Non-detect axis {drop, substitute floor, censored MLE} with the >30 %-censored sensitivity card (3–4 days; prototype `s3`: NHLH2 15×→150×, 4 of 19 estimates move >0.5 log2). Prediction intervals per group as one sentence next to every contrast (half a day; "ODC1 is 3.6× higher on average (CI 2.4–5.3×) but a single new tumour's level falls in a 290-fold range" — MIQE 2.0 asks for this and nobody emits it). Delta-method efficiency propagation, shipped but not promised (half a day; zero effect at n=366 wells, matters at n≤12 per Bilgrau). The "what is your n?" card and refusal of p-values with <2 biological units per group (days; 46 % pseudoreplication). The reverse-normalisation guard plus a co-regulation screen as the headline, with the memory's numbers (17 of 58 flip between defensible ≥3-gene sets; HMBS:UBC ratio shifts 1.76×). **Weeks 1–3.** Nothing in Clarida's changelog touches any of it.

### 3.2 "It gets your data in and proves it is raw" — the capture layer as a public good

Raw-ness detector with the Import Trust Card (3–5 days; test on `ruijter` ds_94_4 with synthetic baseline subtraction). Thermo D&A CLI wrapper for batch EDS→TXT+RDML (3–5 days; documented, scriptable, Windows and Mac). `qpilot rdml inspect` dialect label and fix plan (1 week). OpenReadout pinned as an optional reader for `.eds/.ixo/.rex/.lc96p`, `.pcrd` refused with the recipe shown. Cq-only mode as the door (1 week). A public per-vendor conformance table in the repo with CC0 donated fixtures. Design-vs-as-run layout verify from the vendor export (1 week). The symbol gate for any gene list that enters (2–3 days; 19.5–30.9 % of Excel gene lists corrupted). **Weeks 3–7.** Evidence: note 12 §1.5 ("the loudest recurring technical complaint … is getting data in and efficiency"), practitioner items 82–86, rdmlpython issue #3, tidyqpcr #134 and pcr #29 open for years. Clarida reads instrument files now; it cannot own a conformance table or a raw-ness test.

### 3.3 "It knows what the controls on your plate mean, and whether a failure matters" — Run Gate v0

Typed-control prompt remembered per layout; G-NTC-1 with melt class, G-NRT with gDNA fraction and grade, G-POS with an absolute window, G-STD research defaults plus the E_std-vs-per-well-E gap, G-REP with the Poisson-aware tolerance and KOD evidence, G-MELT from rdmlpython MCA, G-PROV from 3.2; consequence test on the existing grid; three card templates; within-study trending of the seven per-plate metrics with robust (median/MAD) limits (prototype `s05`, 70 lines). Drop from v0: cost model, G-GEO, G-IPC, every pack except `research-default`, L-BRIDGE. **Weeks 7–11**, matching the spec's two-week Gate v0 for Dev A with Dev B on 3.2/3.4. Evidence: 30 % of practitioner items; six notes converging; prototype trending flagged ALUsq, CLSTN1, NTRK1, CD44, SNAPC1 and all were explainable. Lab Memory proper (passports, lot side-car, Westgard across runs, bridging) is **months 4–6** and only after two pilot labs supply archives.

### 3.4 "It installs in 15 minutes without IT and answers the reviewer in one page" — distribution and the Reviewer's Report

Portable Windows zip, `uv tool install qpilot`, `qpilot doctor`, signed per-user installer via SignPath, CI acceptance test on a clean Windows VM as a standard user (2 weeks). Tidy export schema + `qpilotr` shell-out bridge (1 week). The Reviewer's Report: eight deterministic checks with base rates (1–2 weeks). Fact-bound SuperPlot figure with n-honest caption and source CSV (1 week). MIQE 2.0 Table 1 auto-fill with the machine/human/never split, one rendering (1–2 weeks). `study.qpilot` pack/verify (1–2 weeks). Pseudonymised sample names before anything leaves the machine (3–5 days). `.eln` RO-Crate export and Zenodo deposit (1 week). **Weeks 11–20.** Evidence: practitioner items 71–80 (Mac/M1, Windows VM, Windows-7 vendor software, shared instrument PC); 14 [57] bar graphs; item 32 (PolyIC dataset about to be dropped after a reviewer question); note 12's "Free-and-unlimited with a modern UI: empty".

### 3.5 "An agent can call it and cannot make numbers up" — the agent surface, done cheaply

SKILL.md with the rule "never compute Cq or ΔΔCq yourself; call the engine"; PyPI + official registry marker; Claude plugin (3–5 days). Tool annotations, `outputSchema`, typed refusal codes, idempotency keys, concise mode, `resource_link` curves (1–2 weeks). Free-text quarantine and manifest pinning (1 week); F3 refusal and F4 injection cases added to the existing harness as CI. **Weeks 20–24, or interleaved.** Evidence: 13 P1 (BixBench 17 %, "hallucinated numerical results"), the practitioner wish "an assistant providing coaching and warnings exactly when they are needed" (item 99). Tasks/MRTR and the public AgentBench wait.

**After month 6:** the methods paper (07-D6) with five partner labs' real multi-plate studies; the first domain pack (telomere, if a TRN lab partners; otherwise the generic standard-series substrate validated on the USGS eDNA release); Lab Memory v1; inter-plate correction as a grid axis once a multi-gene-per-plate dataset exists to validate on.

Total for 3.1–3.5: roughly 24 developer-weeks of feature work across two people in six months, leaving room for maintenance, pilots and the JOSS/community items in 16-D6. That is honest only if nothing in §4 creeps in.

---

## 4. Things everybody wants us to build that we should not (in year one)

1. **A plate-aware mixed model as the default engine (07-D2).** Prototype: reproduces Welch, plate term unidentifiable, joint model gives every gene the same SE. 3–4 weeks for no change on the only dataset you have. Ship PIs and the censored axis; revisit with a multi-gene-per-plate dataset.
2. **Plate spatial statistics and bubble/spike detectors as user-facing features (06-D2, 06-D6).** Prototype: null-rate Moran hits, 0.06-Cq edge effect, zero steps or spikes in 24,576 wells. Keep the 170-line engine as an instrument-uniformity diagnostic on technical plates.
3. **Any domain plugin before the expression core is stable (08-D2/D3/D4/D5, 09-D1/D2/D4/D7, 10-*, 11-*).** The bake-off's top candidate becomes a generic substrate (§2.1); telomere is the first real pack, conditional on a partner; wastewater and GMO are killed by the bake-off's own evidence; HRM and allelic discrimination have patents, declining literature, no data and now a Clarida genotyping module.
4. **Robot integration and closed-loop "next experiment" JSON (03-D4, 13-D6).** Untestable without hardware, tiny academic audience, liability. Keep `qpcr_repeat_plan` as a well list a human pipettes.
5. **Seven vendor/robot plate-map writers (03-D1, 05-D4).** Verify, yes; QuantStudio TXT and CFX import, maybe; the rest no.
6. **MCP Tasks + MRTR rebuild and a public AgentBench (13-D1 protocol half, 13-D3).** Spec churn and no host support; the harness is already the benchmark.
7. **In-silico assay pre-flight with offline genome packs (02-D2, 17-D4) and melt prediction (11-D3).** A second product; hundreds of MB; weeks; conflicts with the 15-minute install.
8. **Allotrope ASM export (05-D3) and Benchling Results Tables (13-D5, 03-D5).** Licence unresolved; beta API with no tenant.
9. **Pre-analytic QC-file parsers (04-D1).** Five parser families and a name-matching UI before anyone has asked; accept a `rin` column on the sample sheet instead.
10. **Ring mode, passport commons, teaching mode, Chai live mode (15-D6, 02-D6, 14-D6, 05-D6).** Community-organising tasks or demos, not features; no adoption evidence.
11. **GUI automation ("GhostDriver") for any vendor.** The Thermo CLI exists; for Bio-Rad retrospective `.pcrd` the honest answer is "export once by hand with this recipe".
12. **Anything that uses the word "validated", "compliant" or "IVD".** 15-D5's posture is the whole answer.

---

## 5. The ten most load-bearing, least verified facts

| # | Fact as used in the notes | Where it carries weight | Status | What would verify it |
|---|---|---|---|---|
| 1 | "72 % of core facilities cannot identify the raw data behind published figures" | 16-D4, 14-D5, the core-facility pitch, project memory | Note 16 cites [42] (an eLife survey); note 12 §5 Q11 says the source could not be located in the project files or online | Find the primary survey (eLife core-facility reproducibility paper), quote the exact question and denominator, or drop the number |
| 2 | The 2×/3×/4× claim-floor tiers are an accepted standard | Spec G-CLAIM, prototype "23/40 relabelled", 3.1 above | **Verified today as one group's proposal** (Bustin et al. 2025 IJMS), explicitly context-specific, with internal inconsistencies; not in MIQE 2.0 | Already done; now re-run `s5` with the "precision demonstrated" clause and report the honest count |
| 3 | Clarida displays raw curves but does not re-analyse them | Note 12 §1.2/§1.9, every "Clarida cannot" line | **Weakened today**: changelog says "makes Cq calls with a choice of three methods" and "calculate efficiency" | Sign up for the free tier, import a Vermeulen plate, compare its Cq and efficiency to LinRegPCR per well; record which three methods |
| 4 | Efficiency is reported in 1 % of 2024 papers; reporting "collapsed" 13 % → 1 % | 07, 14, 15 pain tables; pitch lines | The 1 % is attributed to Bustin & Wittwer 2026 whose text note 12 did not obtain and whose decline is P=0.12 (memory); 13 % → 1 % is a vendor page (01 Q5, 02 Q3) | Read Bustin & Wittwer 2026 (doi 10.1093/clinchem/hvaf176) and Drude 2026 (CC BY, OSF data); quote one, with its year and denominator |
| 5 | Research plates are repeated often enough that triage saves money | 01-D1, spec §C.3 cost model | No audit or survey of research repeat rates exists (01 Q1); the $150–300 and 3–5 h figures are estimates | Ask the two pilot labs to log, for one month, how many plates or wells were repeated and why; qPilot's own decision log can collect it thereafter |
| 6 | Primer/reagent lot changes drift efficiency in research assays | 02-D1/D3, 01-D3, 15-D3, spec §B.3 | No peer-reviewed quantification for research primers (02 Q1); evidence is Thermo's <0.6 Ct spec (with two different numbers on one page), one master-mix comparison, and MIQE's mandate | A partner lab's archive with lot dates; or a 20-well bridge on two lots of three assays run once in your own hands |
| 7 | Labs will type lot numbers and control-material identities | Entire cluster C | Rated medium or weaker by 01, 02, 15 and the spec ("the weakest link") | Pilot: measure what fraction of imported runs get the 10-field side-car filled within a week of the prompt |
| 8 | Multi-plate studies commonly lack calibrators and layouts are commonly mis-typed | 03-D1/D2, 01-D4 | Forum-level only (03 Q8); the practitioner sample had zero clean "wrong layout" items (r/labrats unreachable) | Re-run the Arctic Shift query against r/labrats when reachable; ask pilot labs for their last ten plate maps and whether any plate was ever re-run for a layout error |
| 9 | Position/edge effects matter on current instruments | 06-D2, 06-D5, 03-D2 edge rule | Prototype: +0.06 Cq edge effect on a modern-class plate; no controlled peer-reviewed study (06 Q7) | A 384-well plate of one sample on each instrument a pilot lab owns (the `ds_380` design); if the edge index is <0.2 Cq everywhere, retire the feature |
| 10 | rdmlpython already has a dPCR data model and importers | 10-D1 effort estimate (4–7 weeks assumes it) | Bake-off §7: neither README nor PyPI mentions dPCR | Read `rdml.py` for `partitions`/`endPtTable` handling before any dPCR estimate |

Two more that did not make the ten but will bite: the Thermo D&A CLI's continued existence in v2.x (05 Q, 12-D2 depends on it; the guide is rev D.0, March 2021) — check on an installed copy; and the Utah HRM patent expiry dates, which Google states are assumptions — irrelevant if HRM stays killed.

---

## 6. Notes on method and what I did not do

I did not re-fetch any source other than the two named above. I took the prototype numbers at face value because the scripts are re-runnable and the notes record their own failures (the σ-only SPIKE rule that flagged 1,249 wells; the NTC wells included in the Moran's I). I did not read sections 1 of the notes in full; where a verdict rests on a frequency claim I took it from the pain inventories and open-questions lists, which are honest about what is estimated. The counts of "109 discoveries" and "about 14 distinct ideas" are mine; re-count if you disagree with a merge.

If you only act on one page of this, act on §3.1 and §2.6: the four cheap statistical layers the prototype proved, with the claim floor labelled as what it is.
