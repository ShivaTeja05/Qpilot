# qPilot Decision Simulator: results on the public neuroblastoma benchmark

Input SHA-256 `bc1d233e3866ad4d…`, grid hash `6585fdf65c032a64`, seed 2026. qsim 0.1.0, qPilot 0.1.0, Python 3.11.14, NumPy 2.4.6, SciPy 1.17.1.

Study: 366 tumours, 58 genes compared (MYCN-high vs rest), 64 plates. Baseline calls: {'down': 29, 'none': 18, 'up': 11}.

## Decision space

7 decisions with levels [4, 3, 3, 31, 3, 3, 3]: 30,132 analyses, **all evaluated** (exhaustive). Full sweep: 18.27 s on one core.

| | all options | defensible options only |
|---|---|---|
| analyses | 30,132 | 8,424 |
| genes whose call flips somewhere | 54 | 45 |
| fragility (fewest choices to flip): count of genes | {'0': 4, '1': 32, '2': 15, '3': 5, '4': 1, '5': 1} | {'0': 13, '1': 27, '2': 13, '3': 3, '4': 2} |
| genes that flip only through two or more choices together | 22 | 18 |
| called genes holding in ≥ 95 % of analyses | 18 of 40 | 21 of 40 |
| called genes holding in < 80 % | 10 | 10 |

Fragility 0 means no analysis in the space changes the call.

### Which decisions matter

| decision | genes flipped by this choice alone | flip rate (all / defensible) | share of fold-change variance (all / defensible) |
|---|---|---|---|
| efficiency | 6 | 0.074 / 0.027 | 0.034 / 0.015 |
| flagged | 4 | 0.100 / 0.106 | 0.090 / 0.106 |
| nondetect | 0 | 0.013 / 0.010 | 0.019 / 0.021 |
| refs | 31 | 0.587 / 0.405 | 0.348 / 0.270 |
| cut | 17 | 0.277 / 0.295 | 0.461 / 0.544 |
| test | 0 | 0.008 / 0.005 | 0.000 / 0.000 |
| multiplicity | 0 | 0.014 / 0.009 | 0.000 / 0.000 |

Largest pairwise interactions (share of variance): {'flaggedxrefs': 0.0155, 'refsxcut': 0.0098, 'flaggedxcut': 0.0063, 'flaggedxnondetect': 0.0041, 'efficiencyxcut': 0.0028}.

**Pre-registration advisor.** Locking ['refs', 'cut'] protects every headline call. Locking ['efficiency', 'flagged', 'refs', 'cut'] protects every called gene; the remaining choices cannot flip any call.

### Headline genes

| gene | call | fold | holds (all) | holds (defensible) | fewest choices to flip (defensible) | minimal flip sets (defensible) |
|---|---|---|---|---|---|---|
| ODC1 | up | 3.59 | 0.996 | 1.000 | – | none |
| BIRC5 | up | 4.011 | 1.000 | 1.000 | – | none |
| NTRK1 | down | 0.066 | 0.998 | 0.999 | 4 | flagged + refs + cut + multiplicity |
| NM23A | up | 2.188 | 0.698 | 0.690 | 1 | cut; refs |

## Verdicts in plain words

Rules: solid = same call in >= 95 % of defensible analyses, no 5 or fewer samples overturn it, significant in >= 95 %; fragile = < 80 %, or <= 2 samples overturn it, or within 0.1 log2 of the fold line; check data first = a data finding changes it.

check data first: 2 · fragile: 9 · depends on your choices: 12 · solid: 17 · no call: 18

## What the calls lean on (baseline analysis)

* 4 genes flip when one tumour is removed; 26 different tumours can do it.
* 148 of 1745 single reference-well removals flip at least one gene; the worst flips 3.
* 7 of 40 called genes sit within one SE of the 2-fold line; 15 can be overturned by removing at most 5 tumours (greedy, an upper bound).

## Joint inference across analyses

Permutation max-T over 936 defensible Welch analyses per gene (999 permutations, seed 2026): 58 genes are associated with the MYCN-high group (BH q < 0.05). 28 genes are significant, same direction, in at least 95 % of analyses with family-wise control; of the called genes, 27. Significance is robust; the 2-fold threshold and the group definition are what make calls fragile.

## Troubleshooting

Observations: {'well_outlier': 92, 'sample_outlier': 12, 'ntc': 11, 'spatial': 4, 'reference_group_effect': 3, 'efficiency': 2}. Issues in the queue: 128 ({'no_demonstrated_effect': 116, 'changes_conclusion': 11, 'biases': 1}).

Identifiability: every sample sits in the same well on every plate: a position effect shared by all plates cannot be told apart from the sample, and largely cancels in reference normalisation; only plate-specific patterns are detectable; group membership is clustered on the plate; spatial artefacts could mimic group differences.

| rank | issue | impact | headline changed | calls changed | max move (SE) |
|---|---|---|---|---|---|
| 1 | The reference genes: changing only this changes 31 call(s) | changes_conclusion | NM23A | 31 | 3.47 |
| 2 | The group cut-off: changing only this changes 17 call(s) | changes_conclusion | NM23A | 17 | 3.07 |
| 3 | The efficiency model: changing only this changes 6 call(s) | changes_conclusion | – | 6 | 2.547 |
| 4 | How flagged wells are handled: changing only this changes 4 call(s) | changes_conclusion | – | 4 | 3.704 |
| 5 | Reference pair HMBS/UBC(2) differs between groups | changes_conclusion | – | 3 | 0.868 |
| 6 | Reference pair HMBS/HPRT1 differs between groups | changes_conclusion | – | 3 | 0.868 |
| 7 | Outlying well H20 on PRKACB_bis | changes_conclusion | – | 1 | 0.495 |
| 8 | Outlying well K22 on HMBS | changes_conclusion | – | 1 | 0.459 |
| 9 | Outlying well F23 on HPRT1 | changes_conclusion | – | 1 | 0.414 |
| 10 | Reference pair SDHA(1)/UBC(2) differs between groups | changes_conclusion | – | 1 | 0.326 |

## Can cheaper search find the same flips?

| strategy | runs | share of space | genes with a flip found | pairwise coverage |
|---|---|---|---|---|
| rings <= 1 | 44 | 0.146% | 32 / 54 | 0.378 |
| rings <= 2 | 504 | 1.673% | 47 / 54 | 1.000 |
| covering array t=2 | 124 | 0.412% | 50 / 54 | 1.000 |
| covering array t=3 | 479 | 1.590% | 49 / 54 | 1.000 |
| Morris, 20 trajectories | 159 | 0.528% | 48 / 54 | 0.570 |
| random, 500 cells | 498 | 1.653% | 50 / 54 | 0.995 |

## Fault-injection benchmark

Of 46 planted faults that changed at least one call, 39 were detected. Of 174 that changed nothing, 96 were detected. Mean other new findings per trial: 1.01 (these include knock-on effects of the fault, so they are an upper bound on false alarms).

| fault | size (cycles) | trials | detected | new findings elsewhere (mean) | trials where a call changed | detected when a call changed |
|---|---|---|---|---|---|---|
| well_outlier | 3.0 | 20 | 5% | 0.10 | 0% | – |
| well_outlier | 5.0 | 20 | 45% | 0.45 | 0% | – |
| well_outlier | 8.0 | 20 | 90% | 0.85 | 5% | 100% |
| row_offset | 1.0 | 20 | 40% | 1.40 | 5% | 0% |
| row_offset | 2.0 | 20 | 85% | 1.90 | 5% | 100% |
| edge_ring | 0.7 | 20 | 50% | 1.80 | 0% | – |
| edge_ring | 1.5 | 20 | 90% | 2.55 | 15% | 100% |
| sample_swap | 0.0 | 20 | 0% | 0.50 | 0% | – |
| ntc_contamination | 2.0 | 20 | 100% | 0.00 | 0% | – |
| reference_shift | 0.3 | 20 | 85% | 0.30 | 100% | 85% |
| reference_shift | 0.6 | 20 | 85% | 1.25 | 100% | 85% |

Timings (s): {'load_s': 0.12, 'full_grid_s': 18.27, 'influence_s': 1.94, 'joint_test_s': 1.27, 'troubleshoot_s': 0.83, 'explorer_check_s': 4.53, 'benchmark_s': 176.26}.
