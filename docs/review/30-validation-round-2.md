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
