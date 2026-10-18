# Tests on new public data: plan fixed before scoring

18 Oct 2026; this plan was committed as d0cfd27 at 02:52 BST, before any scoring code existed. The user asked for new data to test the simulator on. All files were downloaded from the sources the repo already uses:

- **RDML-consortium.** `rdmlpython/experiments`, at commit `e9f936b1d986df3938eb43c85f9cd9c0348a68ed`, MIT licence.
- **r-universe.** The `ruijter` R package's data endpoint, CC BY 4.0.

Sizes were checked against the GitHub API, and every RDML file was confirmed to hold only `rdml_data.xml`. Provenance and SHA-256 are in `data/*/README.md`.

**Already known when this plan was written** (without the truth):
- **Which plates hold the genomic dilution series.** The README upstream says one series, made in AMC in December 2024, was used for every later experiment.
- **`sybr_conc.rdml` is excluded.** Its DNA-dilution runs (P3, P6) hold 672 wells. 576 of them are the same reactions as the AMC plates already scored: same run and well, identical raw curves, and identical Cq wherever one exists (481 wells; the other 95 have no Cq in either file). The other 96 are extra-SYBR wells at one level only, which give no dilution pair. The file also holds 407 further wells in another experiment.
- **ds_94_4's labels run the right way.** More copies amplify earlier: the half-maximum cycle is 26, 29, 32 and 35 at 15,000, 1,500, 150 and 15 copies.

**Applies to every test:**
- No number is fitted on the new data; every interval component comes from the existing results.
- Every result is reported in `results/validation_external.json`, failures included.
- No option tier changes.

## X1. Held-out dPCR plates (primary)

**Plates.** Same genomic tubes as the dPCR truth:

| File | Experiment / run | Instrument | Date | Chemistry |
|---|---|---|---|---|
| `eva_green_b.rdml` | Eva Green B / Run 1 | QuantStudio | 17.09.2025 | EvaGreen in IDT probe mix |
| `quantification_methods.rdml` | Quantification Methods / Run 1 | QuantStudio | 22.10.2025 | probe, EvaGreen and SYBR reporters |
| `probes.rdml` | Probes - AMC / P4 - Probe Mixes - DNA Dilution | LightCycler 480 AMC | 10.12.2024 | Roche and IDT probe mixes |

**Cases.**
- **Which.** Every (run, target) with two or more wells at both levels of a round-2 genomic pair that dPCR resolved (20→7, 7→2, 2→0.7, 20→0.7 ng), scored with the round-2 dPCR truth.
- **Left out.** Targets named "No Primer". Unresolved pairs (0.2 ng) are reported separately.
- **EMBL pair.** The EMBL 20 vs 20 ng pair from `unused_qpcr_dpcr_comparison.rdml` is reported separately. Its "genomic DNA 20ng - EMBL" may not be the tube dPCR measured.

**Estimate.** The round-2 baseline: assay-mean efficiency, mean of log quantities, keep flagged wells. It goes through `qsim.validate.run` exactly as before.

**Intervals.** All components are fixed from the existing results:

| Interval | Variance |
|---|---|
| Round 2 | Welch + ΔCq²(SE(log2 E)² + 0.0408²) + 2·0.0768². This is the robust run effect from all three existing groups. |
| **P1 (primary)** | Round 2 + 0.1479², the plate×pair term pooled from both existing series. |
| P1 variant | Round 2 + 0.1693², the term the AMC and DKFZ plates were scored with. |
| P5 | Round 2 + (1/c_hi + 1/c_lo)/ln²2, with c = ng × 303 copies per reaction. |

**Bar.** ≥ 90 % of cases inside the interval widened by the truth SE.

**Reported.** Coverage per plate and per truth, the cluster-bootstrap 90 % CI over truths, and median half-width. Also the median |error| per plate for every efficiency option.

## X2. Baseline-shift invariance

- **File.** `technical/shifted_baseline.rdml`, run "Shifted Baseline". Each target "T X" holds the same wells as target "T", with a constant added to every fluorescence value.
- **Bar.** For each well and its shifted copy:
  - |Δ log2 N0| ≤ 0.01;
  - |Δ individual efficiency| ≤ 0.001;
  - the round-2 baseline estimate of every genomic pair changes by ≤ 0.01 log2.

## X3. Missing cycles

- **File.** `technical/matrix_gaps.rdml`, with cycles deleted on purpose as listed in its README.
- **Reported, descriptive only.** Whether the analysis runs, and which wells get a Cq and an N0. For wells with only end cycles missing, report how far their efficiency and Cq are from the plate's intact wells of the same sample.

## X4. Ruijter ds_94_4: low copy, CFX384, a second lab

Data: 94 replicates at each of 15, 150, 1,500 and 15,000 copies of a MYCN oligo, plus 8 controls. The CSV is converted to RDML in the same way as ds_380.

**X4a. Known answer.**
- **Pairs.** 15000→1500, 1500→150, 150→15, 15000→15.
- **Truth.** log2(10^k) for k ten-fold steps, with SE 0.0238·√k (the round-2 nominal error bar per step).
- **Draws.** 500 per pair (seed 2026), each taking 3 random wells per level.
- **Estimate.** The round-2 baseline, with the plate's LinRegPCR assay-mean efficiency and SE.
- **Intervals.** Round 2, P1 and P5 as in X1, with c = the stated copies.
- **Coverage.** Coverage is the share of draws covered, per pair. The overall figure gives the 4 pairs equal weight.
- **Bar.** Primary P1 ≥ 90 % overall.
- **Also reported.** The full-plate (all-well) error per pair, and the replicate SD per level against the Poisson expectation.

**X4b. No difference at low copy.**
- **Draws.** Within the 15-copy and the 150-copy level, random 3 vs 3 and 6 vs 6 splits, 1,000 draws each (seed 2026).
- **Cells.** The same cells and rule as V4 on ds_380 (`qsim.nodiff`).
- **Bar.** ≤ 1 % of cells call, no call passes the robust filter, and the baseline median |log2| ≤ 0.15.
- **Expected.** At 15 copies, Poisson noise alone may push the median |log2| over 0.15. That is a property of the data, and the result is reported either way.

## X5. Ruijter competimer: a real efficiency fault (LightCycler 480)

Data: AluSx with competitor at 0, 5, 10, 20, 30, 40 and 50 %, gDNA at 64, 16, 4, 1, 0.25 and 0.0625 ng/µl, in triplicate, plus controls. The CSV has no well IDs, so wells are numbered in file order.

**X5a. Dilution within each competitor level.**
- **Pairs.** Adjacent 4-fold pairs (truth 2 log2) and 64→0.0625 (truth 10 log2).
- **Options.** Assay mean (LinRegPCR, one mean over the plate's wells), each well's own, assume 100 %, and a standard curve leave-pair-out within the same competitor series.
- **Reported.** Median error and median |error| per competitor level and option.

**X5b. The fault case.**
- **Comparison.** Competitor p % against 0 % at the same concentration. The truth is 0 log2: same DNA, only the efficiency differs.
- **Reported.** The error per option and per p.

**X5c. Detectors, frozen as they are now.**
- **The detectors.**
  1. LinRegPCR's efficiency-outlier note on a well: `qsim.data.EFFICIENCY_NOTES`.
  2. qsim's existing efficiency threshold (1.8, from `detect_efficiency`), applied to the mean individual efficiency of each triplicate. This is the existing threshold applied to a new unit.
- **Detection.** The share of competitor > 0 % wells or triplicates flagged, by level.
- **False alarm.** The same share at 0 %.
- **Bar.** From the ruling: false alarm ≤ 2 %. Detection is reported.

## Results (run after the plan was committed as d0cfd27)

Reproduce with `qsim external` (about 45 s). Output: `results/validation_external.json`.

### X1. Held-out dPCR plates: pass

| Interval (components fixed in advance) | Coverage, 120 cases | 90 % CI over truths | Median half-width, log2 |
|---|---|---|---|
| Round 2 | 97.5 % | 96.3–100 % | 0.292 |
| **P1 (primary)** | **100 %** | 100–100 % | 0.411 |
| P1 with the AMC/DKFZ term | 100 % | 100–100 % | 0.441 |
| P5, Poisson | 98.3 % | 97.5–100 % | 0.357 |

**Cases by plate:**
- QuantStudio Eva Green B: 40 cases (10 assays × 4 pairs).
- QuantStudio Quantification Methods: 40 cases (20 assay×reporter rows × 2 pairs). Round-2 coverage there is 92.5 %, and P5's is 95 %.
- LightCycler 480 AMC probe mixes: 40 cases (10 assay×mix rows × 4 pairs).

**Median |error| of each efficiency option, log2:**

| Plate | Assay mean | Standard curve | Assume 100 % | Per well |
|---|---|---|---|---|
| LC480 probes | 0.129 | 0.111 | 0.138 | 0.929 |
| QuantStudio Eva Green B | 0.096 | 0.128 | 0.257 | 0.414 |
| QuantStudio Quantification Methods | 0.195 | n/a (3 levels, leave-pair-out leaves one) | 0.226 | 0.722 |

**The EMBL pair, reported separately.** On the QuantStudio, the "20ng - EMBL" sample reads 0.29 log2 above the dPCR ratio (10 cases). That is the same direction as the round-2 EMBL disagreement. P1 covers all 10 (half-width 0.36).

**What this shows:**
- **The intervals carry over to new plates.** Coverage holds on plates no component was estimated on, including a new instrument (QuantStudio) and new chemistries (EvaGreen, probes).
  - The two QuantStudio plates were measured 3 weeks and 2 months after the dPCR.
  - The LC480 probe plate was measured on 10.12.2024, the same day and machine as the AMC round-2 runs, about 8.5 months before the dPCR.
- **But only 4 distinct truths stand behind the 120 cases,** so the confidence interval over truths is degenerate.
- **Even the round-2 interval passes here.**
  - The comparison with AMC needs the same components. The 97.5 % uses the fixed in-sample run effect (0.0768, 0.0408). Scored with those, the AMC round-2 plate reaches 88.8 %, still under the bar; its 81.6 % used leave-one-group-out components.
  - The LC480 probe plate, from the same day and machine as AMC, is covered 40 of 40. So a time gap between plate and truth does **not** explain the AMC shortfall. (An earlier draft said it did; corrected after review.)

### X2. Baseline-shift invariance: pass

Across 72 well pairs:
- max |Δ log2 N0| = 0.00008;
- max |Δ individual efficiency| = 0.00002;
- no Cq changes;
- the 24 pair estimates differ by at most 0.00002 log2.

Adding a constant to a curve changes nothing.

### X3. Missing cycles (descriptive)

**The analysis runs, and 19 of 22 damaged wells get a Cq.**
- **The three without one** are N9 (cycles 5–9 and 31–35 missing), O3 (only cycle 20 present) and O7 (no data). All three are noted "no amplification; no TD0 found", so none of them fails silently.
- **The pre-registered distances.** These are measured against intact wells of the same sample *and plate row*. Each sample spans two rows about 3.5 cycles apart, so the row-matched reference was adopted after review.
  - **Wells missing only start or end cycles** (K3–K11, L2–L11, O1) are within 0.4 cycles of their row.
  - **Wells missing cycles inside the curve** move more: M3 by +1.39, N3 (cycles 17–20) by +1.72 and N11 by +1.02 cycles.
  - **N5 and N7** have no intact reference in their row.
- **One upstream error.** The upstream README lists O1 as missing cycles 1–8, but the file holds cycle 8.

### X4. Ruijter ds_94_4

**X4a. Known answer: fail.**

| Interval | Coverage (equal weight over 4 pairs) | 15000→1500 | 1500→150 | 150→15 | 15000→15 |
|---|---|---|---|---|---|
| Round 2 | 70.7 % | 60.2 % | 90.8 % | 81.0 % | 50.8 % |
| **P1 (primary)** | **84.8 %** | 93.2 % | 99.0 % | 89.2 % | 57.8 % |
| P5, Poisson | 86.9 % | 64.6 % | 97.4 % | 100 % | 85.4 % |

- **Full-plate estimates** (94 wells per level) read short of 10-fold at every step: errors −0.386, −0.258 and −0.272 log2 per decade, and −0.916 over 15000→15. The assay-mean efficiency is 1.853. A 10-fold step at the observed ΔCq would need E ≈ 1.98.
- **This data cannot say which is wrong.** Either LinRegPCR's efficiency is 6–7 % low on this plate, or the real steps are about 8-fold. Ruijter & van den Hoff 2025 report 8–9.9-fold real steps for the Vermeulen standards from the same lab.
- **The miss is a bias, as on AMC.** Pairs with small systematic error are covered; the 3-decade pair is not.
- **Replicate scatter matches Poisson** at 15 copies (SD 0.365 against 0.373 log2) and at 150 copies (0.107 against 0.118). At 1,500 copies it is 0.337 (robust 0.106) because of 8 flagged wells and one outlier.
- **The stored quantities are 1/8 of the labels** inside the RDML-consortium copy of this set (dataset search). The Poisson match says the labelled copies per reaction are right.

**X4b. No difference at low copy: fail on all cells, pass on defensible cells.**

| Level | Split | All cells calling | Defensible cells calling | Robust calls | Baseline median \|log2\| | Per-well cells calling |
|---|---|---|---|---|---|---|
| 15 copies | 3 vs 3 | 1.07 % | 0 % | 0 | 0.205 | 3.1 % |
| 15 copies | 6 vs 6 | 1.61 % | 0 % | 0 | 0.131 | 4.8 % |
| 150 copies | 3 vs 3 | 1.48 % | 0 % | 0 | 0.057 | 4.5 % |
| 150 copies | 6 vs 6 | 1.49 % | 0 % | 0 | 0.042 | 4.5 % |

This is the same picture as ds_380:
- **Defensible analyses never call,** and nothing passes the robust filter.
- **Almost every call comes from per-well efficiency,** which is common practice. The exception is about 0.1 % of assume-100 % cells at 15 copies, 3 vs 3.
- **At 15 copies (3 vs 3), the baseline median |log2| of 0.205 exceeds 0.15.** Poisson noise alone predicts about 0.2.

### X5. Competimer: a real efficiency fault

All 147 wells are one target, so LinRegPCR's plate-mean efficiency (1.668) mixes clean and inhibited wells.

**The pre-registered numbers:**

| Comparison | Assay mean | Standard curve | Assume 100 % | Per well |
|---|---|---|---|---|
| Fault, same DNA, 10 % vs 0 % | −1.04 | −1.26 | −1.41 | −1.09 |
| Fault, 30 % vs 0 % | −3.65 | −4.43 | −4.95 | +0.23 |
| Fault, 50 % vs 0 % | −10.56 | −12.84 | −14.30 | +1.78 |
| Dilution within 0 % (median bias) | −0.33 | +0.03 | +0.26 | +1.47 |

**Detectors:**
- **LinRegPCR's efficiency-outlier note.** It flags 17 % of wells at 0 %, rising to 11, 44, 72, 83, 83 and 78 % from 5 to 50 %.
- **The 1.8 threshold on each triplicate.** It flags 83 % at 0 % and 100 % from 10 % up.
- **False alarm at 0 %: fail.** It is 17 % and 83 %, against a 2 % bar.

**Why the false alarms happen.** The 64 and 16 ng/µl curves rise before cycle 7. LinRegPCR marks them "no amplification" or "only 3 values in log phase" with efficiency 1.00. The clean wells of this AluSx assay sit near 1.70–1.85, so a 1.8 threshold cannot separate them from inhibited wells.

**Post hoc, not counted: without failed curve analyses.**
- **Bias.** The fault bias still grows with competitor: assay mean −0.60 (5 %), −1.22 (10 %), −2.64 (20 %), −4.45 (30 %) log2. Per-well efficiency stays at −0.19 to −1.20.
- **Detection.** LinRegPCR's note flags 9, 62, 93 and 100 % from 5 to 30 %.
- **False alarm.** It is still 25 %.

**What this shows (for the outside reviewer):**
- **Under strong inhibition, the defensible options are the most biased.**
  - **At 30–50 % competitor,** the assay mean and the standard curve are badly biased (median |error| 3.65–10.56 log2). Per-well efficiency, currently common practice, is much less biased (0.97–2.85).
  - **At 5–10 %,** per-well is as biased or worse: at 10 %, bias −1.09 against −1.04, and median |error| 1.54 against 1.04.
  - **On the clean 0 % dilution,** per-well is far worse (median |error| 3.63 against 0.33).
- **The current tiers assume clean, comparable wells.** The simulator's "per-well vs assay mean" spread is exactly the signal that flags this.
- **The detectors are not frozen-ready.** Their false alarms on this assay exceed the 2 % bar.

## What to claim from X1–X5

**Can claim:**
- The propagated interval (P1) covered dPCR truth on 120 cases from 3 new plates, including a second instrument, with no refitting. The caveat is that only 4 truths stand behind them.
- Baseline-shift invariance holds exactly.
- Defensible analyses made no false call at 15, 150 or 150,000 copies.

**Must say:**
- **Low copy.** The known-answer test at low copy fails (85 % with P1) because of a systematic −0.3 log2 per decade against the nominal dilution. The data cannot tell whether that is efficiency error or dilution error.
- **Detectors.** The efficiency detectors flag real inhibition but also flag clean wells of a low-efficiency assay (false alarm 17–83 %).
- **Inhibited samples.** Only under strong inhibition (≥ 30 % competitor) confined to some samples does per-well efficiency beat the baseline. Under mild inhibition, or none, it is as bad or worse.

## Corrections after an adversarial review (18 Oct 2026)

A review workflow ran three reviewers (code, claims and data), plus a skeptic for each of the seven most severe findings. All seven were confirmed. **No pass or fail changed, and no scored number changed.** Corrected:

1. **Timing.** The time-gap explanation of the AMC shortfall is withdrawn (X1 above).
2. **Per-well efficiency.** The claim is now limited to strong inhibition (X5).
3. **sybr_conc counts.** The duplicate counts are restated.
4. **X3 distances.** These now use a same-row reference.
5. **O1 gap.** The O1 gap is corrected.
6. **Instrument column.** It no longer says "from the file". probes.rdml names no instrument, and both QuantStudio files store "QuantStudio Dx" with a placeholder date, so instruments and those dates come from the upstream README.
7. **Assume-100 % calls.** The 0.1 % of assume-100 % calls is now mentioned.
8. **Efficiency SE.** 4 X1 cases (Eva Green B FSTL_1_L_412) have no efficiency SE. That happens because LinRegPCR writes an assay-level note on every well of an assay below 1.7, and `_assay_mean_se` then counts no unflagged wells. Their efficiency term is filled with 0, as it is for 8 AMC rows in round 2. The true SE is about 0.003, so coverage is unaffected. `results/validation_external.json` now counts these cases.
