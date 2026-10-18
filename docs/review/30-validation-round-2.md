# Validation round 2: dPCR truth, four machines, a no-difference plate, propagated intervals

18 Oct 2026. This round implements ruling items 8.2–8.4 and plan steps V1, V2 and V4 (`00-judge-ruling.md`). Reproduce it with `.venv/bin/qsim validate` (about 1 min). The outputs are:

- `results/validation_dpcr.json`, with the per-case tables `validation_dpcr.csv` and `validation_dpcr_baseline.csv`;
- `results/validation_nodiff.json`.

The code is in `src/qsim/truth.py`, `known_answers.py` and `nodiff.py`, and the data sources are in `data/*/README.md`.

## Verdict

| Test | Pass rule (from the ruling) | Result | Verdict |
|---|---|---|---|
| V1 bias | LinRegPCR assay-mean efficiency: median \|error\| ≤ 0.15 log2 on ≥ 2 machines | Passes on 2 of 4 machines: LC480 AMC (dPCR truth, 0.122) and StepOne (nominal truth, 0.087, 4 cases). Fails on LC480 DKFZ (dPCR, 0.218) and QuantStudio 6 Flex (nominal, 0.205, 4 cases). | **Pass by the letter, weak in substance.** With dPCR truth, only 1 of 2 machines passes. |
| V1 warning | Spread–error Spearman ≥ 0.3 within each input level | 0.51, 0.68, 0.33, 0.57 (20→7, 7→2, 2→0.7, 20→0.7 ng) | **Pass.** But among assays that pass the dilution QC, the values are 0.29, 0.55, 0.02 and 0.38, so 2 of 4 levels fail. |
| V2 coverage | Baseline 95 % interval with truth uncertainty contains the truth ≥ 90 % | 83.2 % (Welch interval: 65.5 %), over 197 cases | **Fail.** 88.1 % on assays passing the dilution QC; 80.9 % on round 1's 188 nominal cases (was 73.4 %). |
| V4 no difference | ≤ 1 % of analysis cells call; no call passes the robust filter; median \|log2\| ≤ 0.15 | All cells: 1.33 % (3 vs 3) and 1.01 % (6 vs 6). Defensible cells: 0 %. Robust calls: 0. Median \|log2\|: 0.066 and 0.055. | **Fail on all cells, pass on defensible cells.** Every call comes from per-well efficiency, which is already common practice. |

## What the truth is

The truth for each pair of tubes is the dPCR (QX200) log2 ratio, averaged over the dPCR assays that measured both tubes. A quality rule based only on the dPCR table sets aside two pairs:

- **0.2 ng.** F_109 and K_219 disagree 2.5-fold on this tube (0.40 against 1.80 log2 for 0.7→0.2 ng; nominal is 1.81).
- **10^5 standard.** Both probe wells are above the QX200's linear range: about 160,000 copies per 20 µl, with 99.9 % of droplets positive. Only EvaGreen L_412 remains.

These pairs are reported separately and kept out of the pass rules. The qPCR baseline gives 1.73 log2 for 0.7→0.2 ng (41 cases), which agrees with K_219 and the nominal value.

The truth's uncertainty is the dPCR Poisson interval plus a well-to-well SD of 0.048 log2, estimated from F_109 against K_219 on the same tubes. On the measured steps, nominal ratios sat within 0.024 log2 of dPCR (RMS, after dPCR's own error). That figure is the error bar for the instrument comparison, which only has nominal truth because its dilution series predates the dPCR.

The truth applies to four sets of cases:

- **DKFZ plate (LC480, same tubes as the dPCR).** 4 assays, with genomic, EMBL and amplicon pairs.
- **AMC plate (LC480).** The same genomic series, measured 8 months before the dPCR: 38 assay×mix runs.
- **QuantStudio 6 Flex and StepOne.** Pipetted from the same reaction tubes.
- **A February 2024 LC480 plate.** One assay each on these last three.

## V1: every choice against dPCR, by input level

Each cell gives the median error and the median \|error\| in log2, pooling all replicate and flag choices.

| Efficiency | 20→7 | 7→2 | 2→0.7 | 20→0.7 | EMBL 20 vs 20 | 1e4→1e3 | 1e3→1e2 | 1e4→1e2 | All |
|---|---|---|---|---|---|---|---|---|---|
| Assay mean (baseline) | −0.05 / 0.09 | −0.10 / 0.12 | +0.06 / 0.12 | −0.04 / 0.21 | +0.42 / 0.42 | −0.33 / 0.33 | −0.21 / 0.21 | −0.52 / 0.52 | −0.05 / 0.13 |
| Standard curve | −0.03 / 0.08 | −0.03 / 0.07 | +0.10 / 0.11 | +0.03 / 0.14 | +0.43 / 0.43 | −0.18 / 0.18 | −0.21 / 0.21 | −0.05 / 0.13 | +0.02 / 0.10 |
| Assume 100 % | +0.06 / 0.12 | +0.03 / 0.08 | +0.18 / 0.22 | +0.29 / 0.39 | +0.41 / 0.41 | 0.00 / 0.17 | +0.21 / 0.21 | +0.22 / 0.23 | +0.12 / 0.17 |
| Each well's own | −0.13 / 1.27 | −0.27 / 0.91 | +0.20 / 1.18 | −0.34 / 1.08 | +0.43 / 1.05 | −0.41 / 0.53 | −0.75 / 0.75 | −0.75 / 0.75 | −0.22 / 1.04 |

The genomic columns hold 42 runs each; the EMBL and amplicon columns hold 4 assays each.

- **Ranking.** dPCR truth separates the options that nominal truth could not: standard curve, then assay mean, then assume 100 %, then each well's own.
- **No tier change.** The standard curve beat the baseline on the AMC plate (0.088 against 0.122) but not on the DKFZ plate (0.245 against 0.218). Tiers are unchanged; this goes to the outside reviewer (item 8.5).
- **EMBL DNA.** dPCR puts the second DNA stock 0.53 log2 below the 20 ng tube. The qPCR assays put it 0.00 to 0.27 below, so all four errors are 0.26–0.53 log2. qPCR and dPCR disagree on that DNA, and no analysis choice fixes it.

## V1 warning: does spread flag a wrong answer?

Within each dPCR-resolved genomic level, the Spearman correlation of spread against baseline \|error\| is 0.33–0.68, so the pre-registered test passes. The cases are 38 AMC runs plus 4 DKFZ assays per level.

Five AMC runs fail qsim's existing standard-curve plausibility rule (efficiency outside 1.6–2.2): M_398, O_417 and T_770 with Roche, and C_040 with SensiFast and with LC Green. Those assays barely respond to dilution and drive both spread and error. Without them, the correlations are 0.29, 0.55, 0.02 and 0.38.

**Claim to make:** "wide spread flags broken assays". **Claim to drop:** "spread predicts error in a working assay".

The truth lies inside the range of defensible analyses in 40.2 % of cases, the same as in round 1.

## V2: the propagated interval

The interval adds three terms to the replicate (Welch) variance:

- the delta-method efficiency term ΔCq²·SE(log2 E)²;
- a per-run efficiency SD;
- a per-level premix SD.

The run effect is estimated without any truth: it comes from how estimates of the same tube pair scatter across assays, mixes and machines. Each group is scored with components estimated on the other groups.

| Group scored | Per-level SD, log2 | Per-cycle efficiency SD, log2 | Coverage with truth SE | Median half-width (Welch → new) |
|---|---|---|---|---|
| AMC (152 cases) | 0.066 | 0.000 | 81.6 % | 0.169 → 0.227 |
| DKFZ (32) | 0.078 | 0.047 | 87.5 % | 0.329 → 0.473 |
| Instrument comparison (13) | 0.075 | 0.041 | 92.3 % | 0.128 → 0.249 |
| **All (197)** | | | **83.2 %** | 0.186 → 0.251 |

**Why it still fails.** At 20→0.7 ng (ΔCq ≈ 5) the AMC baseline is biased by −0.11 log2. The assay-mean efficiency there runs about 1.6 % per cycle low, and a bias cannot be covered by a variance term: coverage at that level is 71 %. On the other three genomic levels it is 86–88 %. The EMBL comparison covers 1 of 4.

**What I changed after seeing results.** My first estimator was the plain variance. On the AMC plate it was dominated by the five broken assays: the per-level SD came out at 0.40 log2, and intervals were ±2.2-fold or wider. Between groups, its per-cycle efficiency SD swings from 0.01 to 0.17. I switched to a robust (MAD) scale after that run. All four versions are in the JSON:

| Estimator | Coverage | Half-width |
|---|---|---|
| Robust, out of sample | 83.2 % | 0.25 |
| Robust, in sample | 88.3 % | 0.32 |
| Plain, out of sample | 84.3 % | 0.27 |
| Plain, in sample | 93.4 % | 0.59 |

Plain in-sample is the only version that passes. It uses its own truth group and gives ±1.5-fold intervals, so I do not count it.

**Other decisions recorded:**
- The dPCR saturation rule was added after the 10^5 ratios disagreed, looking only at the dPCR table.
- The 0.5 ng/µl wells of the instrument comparison come from a separate one-mix tube and were left out, decided from the pipetting scheme before scoring.
- No option tier was changed.

## V4: ds_380, one template on one plate

The data are 380 wells of 150,000 copies on a CFX384, converted to RDML so that qPilot's LinRegPCR analyses them. 14 wells are flagged as efficiency outliers. There were 1,000 random splits each at 3 vs 3 and 6 vs 6, with 18 and 27 analysis cells.

- **Defensible analyses.** The defensible cells (4 and 6: the assay-mean baseline, with or without flagged wells, and the defensible tests) made no call in any split. Their significance-only rate was 2.3 % and 4.5 %, at or below α. The robust filter had nothing to pass.
- **Per-well efficiency.** Per-well efficiency produced every call: 4.0 % and 3.0 % of its cells, with a median \|log2 FC\| of 0.69 and 0.46. This independently supports its common-practice tier.
- **Plate position.** Splitting by plate half gave the same picture. Position effects are measurable but tiny: column-median SD 0.05 cycles, left–right difference 0.005 cycles.

**Limits of this test:**
- At 150,000 copies the Cq SD is 0.19 cycles, so a 2-fold call needs about 5 SD and the null is easy.
- It cannot test low-copy behaviour; ds_94_4 at 15 copies would.
- It cannot test normalisation, because there are no reference genes.
- The standard curve, late-Cq and non-detect choices cannot act on this plate.

## What this changes

- **Wording.** Say "within 0.15 log2 of dPCR on the AMC LightCycler 480", not "validated on four instruments". The DKFZ LightCycler and the QuantStudio miss the bar, and the QuantStudio and StepOne have only one assay each.
- **Intervals.** Report propagated intervals and their measured coverage (about 83 %), never a nominal 95 %. The next step is to correct the efficiency bias: for example, calibrate the assay-mean efficiency against a dPCR-measured dilution, and test it on held-out plates.
- **Spread warning.** Keep "spread is a warning" only as a broken-assay flag.

## Addendum: calibrating the assay-mean efficiency

18 Oct 2026. This tries the next step named above: correct the efficiency bias with a calibration fitted on dPCR-measured dilutions, scored only on held-out plate groups.

**Result: coverage rises from 83.2 % to 87.8 % and still fails the 90 % bar.** The gain comes from a wider interval, not from removing the bias, and the fitted offset does not transfer between plates.

Reproduce it with `qsim validate`. The numbers are under `efficiency_calibration` in `results/validation_dpcr.json`, and per-case `*_calibrated` columns are appended to `validation_dpcr_baseline.csv`. Every round-2 number above is unchanged, and so are the option tiers.

### Method, fixed before any calibrated number was computed

- **Model.** One per-cycle offset δ on the LinRegPCR assay mean: log2 E_cal = log2 E + δ. This moves each baseline estimate by −ΔCq·δ.
- **One δ per series.** Each dPCR-measured dilution series (one run, assay and template, either genomic DNA or the amplicon standard) gives its own δ: the least-squares slope through the origin of error on ΔCq.
- **Held out.** The offset for a plate group is the median δ over the *other* groups' dPCR series (leave-one-group-out over amc / dkfz / volume). Its SE (the median's, from the MAD) joins the efficiency term. The run effect is the round-2 one.
- **Pass rule.** The round-2 rule, unchanged.

The fitted offsets, in log2 per cycle:

| Group | Offset | SE | Fitted on | Efficiency change |
|---|---|---|---|---|
| AMC | +0.0285 | 0.027 | 8 DKFZ series | +2.0 % per cycle |
| DKFZ | +0.0135 | 0.013 | 38 AMC series | +0.9 % per cycle |
| Instrument comparison | +0.0138 | 0.012 | 46 AMC and DKFZ series | +1.0 % per cycle |

### Results against round 2

| Measure | Uncalibrated (round 2) | Calibrated |
|---|---|---|
| Coverage, all 197 cases | 83.2 % | **87.8 %** |
| AMC (152) / DKFZ (32) / instrument comparison (13) | 81.6 / 87.5 / 92.3 % | 87.5 / 87.5 / 92.3 % |
| Assays passing the dilution QC (177) | 88.1 % | 92.1 % |
| AMC 20→0.7 ng (38) | 65.8 % | 81.6 % |
| Round 1's 188 nominal cases | 80.9 % | 85.1 % |
| Median half-width, log2 | 0.251 | 0.293 |

Median \|error\| of the baseline, by machine (log2):

| Machine | Cases | Uncalibrated | Calibrated |
|---|---|---|---|
| LightCycler 480 AMC (AMC plate + Feb 2024 plate) | 157 | 0.121 | 0.130 |
| LightCycler 480 DKFZ | 32 | 0.218 | 0.191 |
| QuantStudio 6 Flex | 4 | 0.205 | 0.233 |
| StepOne | 4 | 0.087 | 0.113 |

The same two machines are within 0.15 before and after.

### Why it fails

1. **The gain is variance, not bias.** With the same offsets but their SE left out, coverage is 83.2 %, exactly the uncalibrated figure. The AMC offset comes from 8 DKFZ series that fall into two clusters (genomic −0.011, amplicon +0.074 per cycle). So its SE is large and widens AMC intervals at wide steps. Median \|error\| gets worse on 3 of 4 machines.
2. **The offset is not a LinRegPCR property that transfers.** Fitted on each plate's own truth (descriptive only, not used for scoring), the median offset per series is:

   | Series | Offset (log2 per cycle) | Series count | MAD |
   |---|---|---|---|
   | AMC genomic | +0.014 | 38 | 0.065 |
   | DKFZ genomic | −0.011 | 4 | |
   | DKFZ amplicon | +0.074 | 4 | |
   | Feb 2024 LC480 | +0.008 | 1 | |
   | QuantStudio | −0.076 | 1 | |
   | StepOne | −0.038 | 1 | |

   The sign flips between the two LightCyclers on the same tubes, and between templates within the same run.
3. **The AMC wide-step bias is mostly not an efficiency error.** An efficiency error biases each step in proportion to its ΔCq.
   - The 7→2 and 2→0.7 ng steps have similar ΔCq (1.9 and 1.6 cycles), so their errors should differ by about 0.007 log2.
   - In the median AMC run, the 2→0.7 step reads 0.099 log2 higher than the 7→2 step (31 of 38 runs, sign test p = 0.0001). All 4 DKFZ assays point the same way (median +0.46).
   - So qPCR and dPCR disagree on the 2 ng tube on both LightCyclers. That is a per-tube discrepancy, like the EMBL one.
   - It may be on the truth side. Relative to nominal, dPCR puts the 2 ng tube 0.06 log2 low, about 1.5 truth SE (see `31-research-closing-the-coverage-gap.md`).
   - A per-cycle correction that fixes AMC 20→0.7 (bias −0.113 → +0.028) spoils 2→0.7 (+0.013 → +0.059).

### Variants (all in the JSON; none counts for the pass)

| Variant | AMC offset | Coverage |
|---|---|---|
| Primary, pre-registered | +0.0285 (8 series) | 87.8 % |
| Truth-disjoint: no training pair uses a tube the scored group is scored on | +0.0741 (4 amplicon series). DKFZ has no series left and stays uncalibrated. | 80.2 % |
| Nominal-truth plates also used in training | +0.0080 (11) | 87.3 % |
| Genomic DNA only | −0.0112 (4) | 82.2 % |
| In sample: one offset from every group, own truth included | +0.0138 (46) | 86.3 % |
| Diagnostic: primary offsets with their SE left out | +0.0285 | 83.2 % |

- **The primary leaks truth.** AMC and DKFZ are scored against the same dPCR ratios (same tubes), so the DKFZ genomic series that calibrate AMC carry the error of AMC's own truth, and the reverse. The truth-disjoint variant removes that leak. It is the cleanest test, and it does worst: the only dPCR series left for AMC are the amplicon standard's, and they overcorrect (AMC bias +0.09, median \|error\| 0.155).
- **Even the in-sample fit stays at 86.3 %.** It sees every plate's own truth, so no single per-cycle offset closes the gap.

**Decided after seeing results:**
- The diagnostic variant (SE left out) and the step-pattern sign test in point 3 were added after the primary result, to explain it.
- The per-series table in point 2 uses each plate's own truth and is descriptive only.
- Nothing in the primary method was changed.

### Should the calibrated efficiency become an option?

This decision goes to the outside reviewer (item 8.5), and tiers are unchanged.

- **For.** It removes most of the AMC wide-step bias. A lab that runs its own dPCR-measured standard on the same instrument and template could fit δ for itself, and these data cannot test that design.
- **Against.**
  - The offset changes sign across plates and templates.
  - Median \|error\| worsens on 3 of 4 machines.
  - The whole coverage gain is the offset's own SE.
  - The cleanest held-out version lowers coverage.

My recommendation is to keep it as a validation variant and not add it as an analysis option.

### What this changes

- **Coverage to quote.** Keep quoting the uncalibrated coverage, about 83 %.
- **How to describe the gap.** It is qPCR–dPCR disagreement on single tubes (2 ng, EMBL) plus run-to-run efficiency scatter, not a LinRegPCR efficiency bias.
- **Possible next step.** A per-tube discrepancy term on the truth side, estimated only from the other plate that shares the tubes. Being estimated from the other plate means its qPCR, not its truth. It would need its own pre-registration.
