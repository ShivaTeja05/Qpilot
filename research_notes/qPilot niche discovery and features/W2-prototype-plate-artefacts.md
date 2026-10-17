# W2 — Prototype: are plate-level and run-level artefacts detectable in the 64-plate Vermeulen study?

Prototype note, 17 October 2026. Timeboxed (~40 min of scripting). Goal: turn three proposed qPilot features — (a) Plate Residual Map (note 06, D2), (b) Well Signal Integrity signatures (06, D6), (c) between-plate offsets + control/NTC trending ("instrument passport", 06, D3/D4; lot-drift ledger, 01, D3) — from ideas into measured evidence on real raw data.

Data: Vermeulen/Ruijter 2013 raw RDML (`~/.cache/qpilot/data_vermeulen_raw.rdml`, CC BY 4.0), LightCycler 480, SYBR Green, 45 cycles. Per-well Cq (TD0), N0 (Ncopy) and efficiency come from qPilot's own cached LinRegPCR table (`qpilot/qpcr/curves.py`; cache `~/.cache/qpilot/*.curves.csv`, 24,576 rows); raw per-cycle fluorescence was read from the RDML XML directly (the vendored `Run` class has no react accessor). All scripts and outputs live in `/private/tmp/claude-501/-Users-gangadhara-Documents-Wheel-Hack/512c949e-9168-4b0a-8341-49ef6b39392c/scratchpad/proto_plate_qc/` (referred to below as `proto_plate_qc/`); each is re-runnable with `cd qpilot && .venv/bin/python proto_plate_qc/<script>`. Nothing in the qPilot repo was changed (`git status --porcelain` is empty at the end; see section 8).

Every number below is from the named script. Nothing is estimated unless marked.

---

## 1. What is on the plates (script `s01_plate_structure.py`)

| fact | value |
|---|---|
| experiments in the file | `biomarker_set` (64 runs), `technical_datasets` (3 runs) |
| total reacts with raw curves | 25,491 (45–50 cycles each) |
| plate format | 64/64 plates are 16 × 24 (384-well); all 384 wells filled |
| targets per plate | exactly 1 (64 plates = 64 genes; plate = gene) |
| unknowns per plate | 366 tumour cDNAs, each **once** per plate; same 366 on every plate |
| standards per plate | 15 wells: STD_15 / 150 / 1,500 / 15,000 / 150,000 copies in triplicate, at fixed wells N14–N24 and P2–P18 (even columns) |
| NTCs per plate | 3 wells: P20, P22, P24 |
| layout identity | 64/64 plates have the **identical well → sample map** |
| inter-run calibrator flag (`interRunCalibrator`) | never set (value `None` on all 372 samples) |
| edge wells (rows A/P, cols 1/24) | 76 per plate: 63 unknowns, 10 standards, 3 NTCs; interior: 303 unknowns, 5 standards |
| run dates | plate ids carry a date token: 15 distinct dates, 2008-02-20 … 2008-03-18 (2–8 plates per date); no `runDate`/`instrument` fields in the RDML |
| technical plates | `380_replicates_set` (one sample in 380 wells + 4 NTC, 384 format); `94_replicates_4_dilutions_set` (4 levels × 94 replicates + 8 NTC); `competimer_set` (147 wells) |

Consequences for the three features:
- **Between-plate offsets (Ruijter 2015 factor model) cannot be estimated from the study design**: no two plates share a target, so the ratio matrix of shared (target × condition) is empty (0 of 2,016 plate pairs share a target; `s04`). There are no inter-run calibrators. The only cross-plate material is the per-gene standard series (different amplicon per plate), which calibrates each plate to known copies but cannot separate "plate/run" from "gene".
- **Position and sample are perfectly confounded** on the biomarker plates: tumour *s* sits in the same well on all 64 plates. A two-way (sample + plate) model therefore absorbs any position effect that is constant across plates into the sample effect; only plate-specific spatial structure is visible. The pure instrument/position effect is measurable only on the technical plates (380 replicates of one sample; 94 × 4 dilutions).
- **NTC/control trending** is possible: 3 NTCs + 15 standards per plate × 64 plates in date order.

---

## 2. Spatial effects (script `s02_spatial.py`)

### 2.1 Biomarker plates: two-way residuals (unknown wells only)

Model per outcome y ∈ {Cq, log2 N0}: y[s,k] = μ + a_s + b_k + r[s,k], s = sample (366), k = plate (64), fitted by alternating means (NaN-aware). 23,101 values, 323 missing (no Cq).

| outcome | total SD | sample-effect SD | plate-effect SD | residual SD |
|---|---|---|---|---|
| Cq | 4.355 | 1.617 | 3.606 | **1.947** |
| log2 N0 | 3.894 | 1.484 | 3.193 | 1.778 |

The residual SD (≈1.9 Cq) is not noise: it is the sample × gene interaction (each tumour expresses each gene differently), so any spatial test on these residuals has low power. Per-plate statistics on the Cq residual map (rook adjacency on the 16 × 24 grid; Moran's I with a 999-permutation p-value; edge = outer ring):

| per-plate statistic (n = 64 plates) | min | 25% | median | 75% | max |
|---|---|---|---|---|---|
| residual SD (Cq) | 0.855 | 1.225 | 1.656 | 2.033 | 5.158 |
| range of row means | 0.53 | 1.32 | 1.66 | 2.38 | 4.33 |
| range of column means | 0.88 | 1.21 | 1.64 | 2.38 | 5.74 |
| edge − interior (median residual) | −1.59 | −0.25 | +0.04 | +0.31 | +0.99 |
| Moran's I | −0.087 | −0.034 | −0.004 | +0.022 | +0.090 |

- Plates with Moran p < 0.05: **3/64** (Cq), 2/64 (log2 N0) — what the null expects (~3.2). p < 0.01: 0. Strongest: HIVEP2 (I = 0.090, p = 0.010), CPSG3 (0.083, p = 0.041), SCG2 (0.070, p = 0.038).
- Plates with edge-vs-interior Mann-Whitney p < 0.01: 9/64; median |edge − interior| = 0.29 Cq. Largest: CPSG3 −1.59 (p = 0.39, residual SD 4.4, a near-failed plate), BIRC5 −1.13 (p < 0.001), CDH5 +0.99 (p = 0.017), PRAME −0.98. Because the same 63 tumours are the edge wells on every plate, an edge difference on one gene's plate is indistinguishable from "those 63 tumours express that gene differently".
- Mean |row-mean residual| over plates is 0.26–0.52 Cq for rows A–O and **0.80 for row P** (row P holds only 9 unknowns plus the standards/NTCs, so its mean is noisier; not evidence of an edge effect). Columns: 0.27–0.53.
- Maps: `proto_plate_qc/s02_residual_maps_cq.png` (6 strongest + 2 median plates). Visible by eye: some plates show row-wise bands (e.g. DDC row D, CPSG3 rows J–M); whether these are pipetting rows or sample-order biology cannot be told from this design.

Verdict for this design: **no detectable plate-specific spatial structure** above the permutation null in 61/64 plates; the test is weak because biology dominates the residual.

### 2.2 Technical plate `380_replicates_set` (pure position effect; LinRegPCR run here via `qpilot.qpcr.curves.analyse_run`)

One sample in 380 wells (NTCs excluded), Cq mean 19.103, **SD 0.192**, range 16.69–19.61; LinRegPCR excluded 0 wells.

| outcome | SD | row-mean range | col-mean range | edge − interior | Mann-Whitney p | Moran's I (E[I] = −0.0026) | perm. p |
|---|---|---|---|---|---|---|---|
| Cq | 0.192 | 0.240 | 0.324 | **+0.062** | 8.6e−05 | 0.053 | 0.061 |
| log2 N0 | 0.171 | 0.213 | 0.288 | −0.055 | 8.7e−05 | 0.053 | 0.056 |
| eff_indiv | 0.099 | 0.106 | 0.067 | −0.019 | 0.13 | **0.088** | **0.004** |

Row means of Cq (A…P): 19.21, 19.13, 19.11, 19.11, 19.12, 19.12, 19.05, 19.08, 19.04, 18.97, 19.13, 19.08, 19.11, 19.08, 19.16, 19.17 — row A is +0.1 and the middle rows G–J are −0.05 to −0.13 relative to the plate; columns 5–6 (+0.1) and 14 (−0.2) stand out. Maps: `proto_plate_qc/s02_380_cq_map.png`, `proto_plate_qc/s02_380_eff_map.png`.

Reading: on this CFX384-class plate the position effect is **real but tiny**: edge wells are 0.06 Cq later (statistically clear with 380 replicates, biologically irrelevant); row/column ranges 0.24–0.32 Cq; efficiency shows weak but significant spatial clustering (Moran p = 0.004). This matches Rogers-Broadway 2015's SD ≈ 0.3 on a modern block (note 06, KQ2).

### 2.3 Technical plate `94_replicates_4_dilutions_set`

Levels alternate by row (A, C, E… = STDA150/STDA15000; B, D, F… = STDA15/STDA1500). Within-level Cq SD: 0.067 (15,000 copies), 0.121 (150), 0.379 (1,500), 0.411 (15). Within-level residuals: SD 0.290, row-mean range 0.287, column-mean range 0.436, edge − interior +0.006 (p = 0.91), Moran's I −0.025 (p = 0.77). No spatial structure; variation is Poisson-dominated at low copies.

### 2.4 Per-well efficiency by position over the 64 biomarker plates

Within-plate z-score of `eff_indiv`, averaged per well over 64 plates: SD across wells 0.303; Moran's I 0.052 (p = 0.043); edge − interior +0.05 (p = 0.06); row F −0.28, row N −0.18, column 24 −0.33, column 6 −0.12. Confounded with sample identity (an inhibitor-containing cDNA sits in the same well on all plates), so this is a "which tumours amplify poorly" map, not a position map. PNG: `proto_plate_qc/s02_eff_by_position.png`.

---

## 3. Well Signal Integrity signatures on raw fluorescence (script `s03_signal_integrity.py`)

Inputs: 24,576 raw curves (biomarker plates, cycles 1–45), joined to LinRegPCR Cq/efficiency. Definitions (σ = plate median of 1.4826 × MAD of ground-phase first differences; A_ref = plate median plateau amplitude of wells with a Cq; ground phase = cycles 3…G, G = clip(⌊Cq⌋ − 4, 8, 40), or 3…40 without Cq):

| signature | rule | rationale |
|---|---|---|
| STEP | persistent jump in ground phase: \|mean of next 3 − mean of previous 3\| > 6σ and > 2 % of A_ref, not a single-cycle spike | vendor "sudden changes"/bubble (06 [1][56]) |
| SPIKE | \|F_i − (F_{i−1}+F_{i+1})/2\| > 8σ **and** > 2 % of A_ref, curve returns (\|F_{i+1} − F_{i−1}\| < half the deviation), outside the exponential phase | vendor "spikes, dips" [1]. The 2 %-of-amplitude clause was added after a σ-only rule flagged 1,249 wells (5.1 %) with plateau ripples of 0.1 units ≈ 0.47 % of amplitude at cycles 37–44: plateau noise is larger than ground-phase noise, so σ alone is the wrong yardstick |
| DRIFT | ground-phase slope × ground-phase length, as fraction of A_ref, outside ±3 % | Rotor-Gene "slope correct" [20]; a trend of this size is of the order of the lowest fluorescence LinRegPCR uses in its window of linearity, so it biases baseline and efficiency |
| LATE | last-5-cycle slope × 5 / own amplitude < −5 % (hook/decline, PCRedux `hookreg` idea [45]) or > +5 % (still rising); only wells with ⌊Cq⌋ + 8 ≤ 40 | evaporation/no-plateau |
| PLATEAU | amplitude / A_ref < 0.4 or > 2.0, wells with a Cq | abnormal plateau height |

Measured noise: plate-median σ = 0.0120 raw units (median over plates); A_ref median 23.1 units → ground-phase noise ≈ 0.05 % of amplitude; smallest non-zero fluorescence step 1e−4 (the LC480 export is 4-decimal). Feature percentiles (p1/p5/p50/p95/p99): drift −0.002/+0.001/+0.004/+0.007/+0.009; late −0.022/−0.007/+0.001/+0.107/+0.742; amp_ratio 0.001/0.865/0.999/1.082/1.131.

Counts (24,576 wells):

| signature | wells | % | unkn / std / ntc | plates with ≥ 1 | max per plate |
|---|---|---|---|---|---|
| STEP | 0 | 0.00 | 0/0/0 | 0 | 0 |
| SPIKE | 0 | 0.00 | 0/0/0 | 0 | 0 |
| DRIFT | 4 | 0.02 | 4/0/0 | 4 | 1 |
| LATE | 58 | 0.24 | 46/9/3 | 9 | 30 (QPCT) |
| PLATEAU | 75 | 0.31 | 68/0/7 | 25 | 14 (PTPRH) |
| any | 136 | 0.55 | 117/9/10 | 31 | 30 |

Edge share among flagged wells: DRIFT 50 % (n = 4), LATE 36 %, PLATEAU 36 % vs 19.8 % of all wells — a mild edge enrichment (small n).

Do flagged wells differ in LinRegPCR output? (unknown wells; medians, flagged vs not)

| signature | n | \|Cq residual\| | \|eff z\| | eff_indiv | LinRegPCR note present |
|---|---|---|---|---|---|
| DRIFT | 4 | 1.44 vs 0.91 | **1.66 vs 0.17** | 1.845 vs 1.895 | 50 % vs 5 % |
| LATE | 46 | 1.24 vs 0.91 | 0.19 vs 0.17 | 1.891 vs 1.895 | 2 % vs 5 % |
| PLATEAU | 68 | **10.03 vs 0.91** | 0.22 vs 0.17 | 1.881 vs 1.895 | **98.5 % vs 4.9 %** |

Standards (triplicates on the same plate): |Cq − triplicate median| median 0.213 for the 9 flagged standard wells vs 0.047 for the 951 unflagged; > 0.5 Cq in 33 % vs 4.5 %.

Reading:
- The LC480 raw export is extremely clean (no step, no spike in 24,576 wells at any defensible threshold). Bubble/spike signatures found **nothing to detect here**; the dataset gives no positive controls for them.
- PLATEAU almost exactly reproduces LinRegPCR's own exclusions (low-amplitude, late or failed wells: notes "Ncopy < 10", "no plateau", "PCR efficiency outlier"); it adds nothing qPilot does not already have.
- LATE is mostly a **plate-level** property: 30 of 58 flags are on the QPCT plate (late-Cq gene, curves still rising at cycle 45), plus ALUsq standards. That is a "no plateau reached" plate warning, not a well artefact.
- DRIFT (4 wells) is the only signature that catches wells LinRegPCR keeps but whose efficiency is off (|eff z| 1.66 vs 0.17) — e.g. AKR1C1 A11 (drift −3.4 %, eff 1.94), CDKN3 A8 (+3.2 %, eff 1.75). Too few to conclude; worth keeping as the one reporter-only signature with a visible effect.
- Examples (5 per signature; blank panels where fewer exist): `proto_plate_qc/s03_signature_examples.png`. Per-well features: `proto_plate_qc/s03_well_features.csv`; per-plate counts: `s03_counts_per_plate.csv`.

---

## 4. Between-plate offsets (script `s04_between_plate.py`)

- Ruijter 2015 factor model: **unidentifiable** here (0 of 2,016 plate pairs share a target; no inter-run calibrators). Not estimated; nothing invented.
- What the standards allow — per-plate calibration of log10 N0 against log10 known copies (15 wells/plate, 64 plates):

| statistic | min | 25% | median | 75% | max | SD |
|---|---|---|---|---|---|---|
| slope (Ruijter 2013 "bias") | 0.370 | 0.952 | 0.962 | 0.977 | 1.010 | 0.080 |
| R² | 0.694 | 0.997 | 0.998 | 0.999 | 1.000 | 0.038 |
| mean log10(N0 / copies) ("bias as ratio") | −0.509 | −0.097 | +0.003 | +0.105 | +1.329 | **0.295** |
| Cq at 15,000 copies (triplicate mean) | 23.48 | 24.29 | 24.66 | 25.04 | 26.09 | **0.570** |
| LinRegPCR plate efficiency | 1.726 | 1.881 | 1.903 | 1.913 | 1.936 | 0.037 |

  SD of the calibration offset across plates = 0.295 log10 = 1.97-fold (range 68.8-fold, driven by CLSTN1 +1.33 and PLAT −0.51). This spread is gene (amplicon, standard preparation) + plate + day, inseparable.
- Invariance check: qPilot's group contrast (MYCN-high = top 15 % by MYCN(4) relative to the five reference genes; drop policy; n = 53 vs 294) is a within-plate difference of log quantities, so a multiplicative per-plate factor cancels. Verified: applying the standard-derived per-plate factor to every N0 changes each of the 64 genes' log2 fold change by at most **3.6e−15** (ODC1 1.844, NTRK1 −3.911, BIRC5 2.004, PLAT −1.765 before and after). In a one-gene-per-plate design, plate correction cannot change any group conclusion; it would matter only for absolute-copy claims or designs where a gene spans plates.

---

## 5. NTC / control trending in run order (script `s05_trending.py`)

Run order: plate-id date token, ties by file order (64 plates, 15 dates). Outputs `proto_plate_qc/s05_plate_timeseries.csv`, `s05_levey_jennings.png`, `s05_ntc_chart.png`.

NTCs: 23 of 192 NTC wells have a LinRegPCR Cq (53 plates 0/3, 3 plates 1/3, 4 plates 2/3, 4 plates 3/3). NTC Cq when present: min 23.94 (ALUsq — an Alu-repeat assay, where NTC signal is expected), median 39.46, max 47.16. NTC Cq minus the same plate's STD_15 Cq: median +4.0 cycles, min −2.63 (ALUsq), max +11.9. Apart from ALUsq, every NTC amplifies > 1 cycle later than the 15-copy standard; no plate would fail an "NTC within 3 cycles of the lowest standard" rule except ALUsq.

Levey-Jennings (limits = mean ± 2 SD / 3 SD from the **first 20 plates** in run order, Westgard's minimum; applied to all 64):

| metric | first-20 mean ± SD | all-64 SD | 1-2s | 1-3s | 2-2s | 4-1s | 10x | 1-3s plates |
|---|---|---|---|---|---|---|---|---|
| Cq STD_15000 | 24.60 ± 0.60 | 0.57 | 3 | 0 | 0 | 0 | 0 | — |
| Cq STD_15 | 34.64 ± 2.03 | 1.30 | 1 | 1 | 0 | 0 | 0 | ALUsq |
| plate efficiency | 1.884 ± 0.046 | 0.037 | 2 | 2 | 0 | 0 | 3 | CLSTN1, NTRK1 |
| standard-curve slope | 0.924 ± 0.137 | 0.080 | 1 | 1 | 0 | 0 | 25 | ALUsq |
| plateau amplitude A_ref | 22.9 ± 2.8 | 1.74 | 1 | 1 | 0 | 0 | 0 | ALUsq |
| median baseline fluorescence | 0.679 ± 0.094 | 0.148 | 5 | 1 | 0 | 0 | 5 | CD44 |
| ground-phase noise σ | 0.013 ± 0.003 | 0.002 | 1 | 1 | 0 | 0 | 2 | SNAPC1 |

Reading: the charts flag exactly the plates a scientist would want to see — ALUsq (slope 0.37, R² 0.69, plateau half height, NTC at 23.9: a repeat-element assay behaving unlike the rest), CLSTN1 and NTRK1 (efficiency 1.73), CD44 (baseline 1.6 vs 0.68). Efficiency by date drifts from 1.86 (02-27) to 1.91 (02-28/03-03) to 1.83 (03-18), but with one gene per plate a "date" effect cannot be separated from "which genes were run that day". The 10x rule on the standard-curve slope (25 hits) fires because the first-20 mean (0.924) is pulled down by ALUsq — a known Westgard failure mode when limits are set from a reference period containing an outlier; the shipped version must use robust limits (median/MAD) or exclude 1-3s points from the limit set.

---

## 6. Verdict per feature

| feature | evidence on this dataset | what the data cannot tell | what a lab's own multi-run data would add |
|---|---|---|---|
| (a) Plate Residual Map | **Not found on the biomarker plates** (3/64 plates with Moran p < 0.05 = null rate; residual dominated by sample × gene biology). **Found but tiny on the technical plate**: edge +0.06 Cq (p = 9e−5), row/col ranges 0.24–0.32 Cq, efficiency Moran I = 0.088 (p = 0.004). | Any position effect that is identical on every plate (same layout everywhere); whether row bands seen on some plates are pipetting or biology. | Plates with technical replicates in different positions, or randomised layouts across plates, make the two-way residual a true position residual; ageing/older blocks (SD ≈ 1.9 Cq class) are where the map would pay off. The method is validated (it recovers the 380-plate structure) but its *value* on modern blocks is unproven. |
| (b) Well Signal Integrity | STEP 0, SPIKE 0, DRIFT 4, LATE 58 (30 on one plate), PLATEAU 75 (≈ LinRegPCR's own exclusions). Flagged standards deviate 4.5× more from their triplicate (0.21 vs 0.05 Cq). | Whether bubble/step/spike detectors work: the LC480 export contains none; no ground truth. Passive-reference channels are absent from RDML. | Vendor multi-channel exports (QuantStudio multicomponent, CFX per-fluorophore RFU) and a few labelled bad plates; synthetic injection into these clean curves for an acceptance test. |
| (c) Between-plate offsets | **Data cannot tell**: no shared targets, no IRCs; per-plate standard calibration spread SD 0.295 log10 (1.97-fold) is gene-confounded. Group contrasts are provably invariant to plate factors in this design (max change 3.6e−15). | Run/instrument factors. | Any design with a gene on ≥ 2 plates or an IRC per plate; the Ruijter 2015 code path is then a 1–2 week job with a worked example from the paper. |
| (c') NTC/control trending | **Works as a prototype**: L-J/Westgard on 7 per-plate metrics flags ALUsq, CLSTN1, NTRK1, CD44, SNAPC1 — all explainable; NTC rate 23/192 wells, ALUsq the only NTC earlier than the 15-copy standard. | Instrument drift vs gene identity (one gene per plate, 4 weeks, one instrument). | Repeated controls of the same material over months and instrument ids: that is the passport. Also lot fields (01, D3). |

---

## 7. What to ship, with the paper for each, and effort (estimates)

1. **Plate residual engine (core of a, reused by c')** — two-way or median-polish residuals per plate on log N0/Cq within replicate groups (Brideau 2003 B-score family; Tukey median polish), global Moran's I with layout-respecting permutation null (Lachmann 2016, Bioinformatics 32:1959), border-vs-interior Mann-Whitney (Lab Manager edge-effect practice), local Moran (Anselin 1995 LISA) for clusters. All numpy/scipy; `s02_spatial.py` is 170 lines and runs 64 plates in ~5 s. Must refuse to attribute when sample and position are confounded (detectable from the layout: same well→sample map on all plates, or one gene per plate). **Effort: 1 week** engine + facts; +1 week UI/cards. Acceptance test: 380-replicate plate (edge +0.06, Moran eff p < 0.01) and synthetic gradients injected into it.
2. **Signal signatures (b), reporter-only subset** — DRIFT (ground-phase slope, Rotor-Gene slope-correct rationale; Qiagen manual) and LATE/no-plateau (PCRedux `hookreg`/`sd_plateau` definitions, Rödiger/Burdukiewicz/Spiess, JOSS 2022 — reimplement, MIT definitions) as plate-level warnings; drop PLATEAU (duplicates LinRegPCR notes); keep STEP/SPIKE dormant until multi-channel vendor capture exists, with thresholds expressed as % of amplitude, never σ alone. **Effort: 3–4 days** for the reporter-only subset; bubble/passive-reference work blocked on vendor import (roadmap).
3. **Between-plate factor (c)** — Ruijter et al. 2015, Biomol Detect Quantif 5:10–14 (Eqs 3–5 ratio matrix, nested geometric-mean substitution, run factor), plus a design check that reports "ratio matrix empty / plate confounded with gene" (as here) and a bootstrap CI over shared conditions. **Effort: 1–2 weeks**, no validation possible on this dataset; use the paper's 6-plate example and the `ruijter` CC BY data with synthetic factors.
4. **Control trending / passport (c')** — Levey-Jennings with Westgard multirules (Westgard, Barry, Hunt & Groth 1981, Clin Chem 27:493), limits from ≥ 20 runs with robust (median/MAD) option, per metric: NTC amplification (p-chart), lowest-standard/IRC Cq, LinRegPCR plate efficiency, standard-curve slope, plateau amplitude, median baseline, ground-phase σ; change-point by CUSUM (Page 1954). `s05_trending.py` is 70 lines. **Effort: 1 week** engine + chart; the hard part is control-material identity and instrument id across records (lab profile naming rules), not the statistics.

Order suggested by the evidence: 4 (works now, cheap) → 1 (works, needs the right designs to be valuable) → 2 reporter-only subset (small) → 3 (cannot be validated on the demo data; wait for a dataset with overlap).

---

## 8. Reproducibility and integrity

- Scripts: `proto_plate_qc/common.py` (RDML react/adp reader + cache; two-way fit), `s01_plate_structure.py`, `s02_spatial.py`, `s03_signal_integrity.py`, `s04_between_plate.py`, `s05_trending.py`. Run from the qpilot directory with `.venv/bin/python` (the package is imported for `rdml_io.load` and `curves.analyse_run`).
- Outputs: `s01_plate_table.csv`, `s02_plate_spatial_{cq,log2n0}.csv`, `s02_380_linregpcr.csv`, `s02_94x4_linregpcr.csv`, `s03_well_features.csv`, `s03_counts_per_plate.csv`, `s04_standard_calibration.csv`, `s05_plate_timeseries.csv`; PNGs `s02_residual_maps_cq.png`, `s02_380_cq_map.png`, `s02_380_eff_map.png`, `s02_eff_by_position.png`, `s03_signature_examples.png`, `s05_levey_jennings.png`, `s05_ntc_chart.png`.
- Failures and fixes during the run, for honesty: the first SPIKE rule (σ-only) over-flagged 1,249 wells and was corrected (section 3); the first 380-plate efficiency Moran's I (0.267) included the 4 NTC wells by mistake and is 0.088 after excluding them; one plate id (`…_bis`) broke date parsing and was fixed with a regex; the invariance check first showed 9.5e−3 because samples missing a reference gene were averaged over fewer refs — exact (3.6e−15) under qPilot's "drop" policy.
- `git -C qpilot status --porcelain` at the end: empty (no files changed, added or committed in the repo). An untracked `demo/demo.mp4` was listed at the start of the session and had disappeared by the end; neither state was caused by this work.
