# Tests on new public data: plan fixed before scoring

18 Oct 2026, about 03:30. The user asked for new data to test the simulator on. All files were downloaded from the sources the repo already uses:

- **RDML-consortium.** `rdmlpython/experiments`, at commit `e9f936b1d986df3938eb43c85f9cd9c0348a68ed`, MIT licence.
- **r-universe.** The `ruijter` R package's data endpoint, CC BY 4.0.

Sizes were checked against the GitHub API, and every RDML file was confirmed to hold only `rdml_data.xml`. Provenance and SHA-256 are in `data/*/README.md`.

**Already known when this plan was written** (without the truth):
- **Which plates hold the genomic dilution series.** The README upstream says one series, made in AMC in December 2024, was used for every later experiment.
- **`sybr_conc.rdml` is excluded.** 576 of its 672 wells are wells of the AMC plates already scored (same run and well, and 481 have identical Cq).
- **ds_94_4's labels run the right way.** More copies amplify earlier: the half-maximum cycle is 26, 29, 32 and 35 at 15,000, 1,500, 150 and 15 copies.

**Applies to every test:**
- No number is fitted on the new data; every interval component comes from the existing results.
- Every result is reported in `results/validation_external.json`, failures included.
- No option tier changes.

## X1. Held-out dPCR plates (primary)

**Plates.** Same genomic tubes as the dPCR truth:

| File | Experiment / run | Instrument (from the file) | Date | Chemistry |
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
