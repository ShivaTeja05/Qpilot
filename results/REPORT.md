# qPilot Decision Simulator: results on the public neuroblastoma benchmark

Input SHA-256 `bc1d233e3866ad4d…`, grid hash `696d92f679fcee53`, seed 2026. qsim 0.1.0, qPilot 0.1.0, Python 3.11.14, NumPy 2.4.6, SciPy 1.17.1.

Study: 366 tumours, 58 genes compared (MYCN-high vs rest), 64 plates. Baseline calls: {'down': 29, 'none': 18, 'up': 11}.

## Decision space

7 decisions with levels [3, 3, 3, 31, 3, 3, 3]: 22,599 analyses, **all evaluated** (exhaustive). Full sweep: 13.33 s on one core.

| | all options | defensible options only |
|---|---|---|
| analyses | 22,599 | 8,424 |
| genes whose call flips somewhere | 54 | 46 |
| fragility (fewest choices to flip): count of genes | {'0': 4, '1': 32, '2': 15, '3': 5, '4': 1, '5': 1} | {'0': 12, '1': 27, '2': 13, '3': 4, '4': 2} |
| genes that flip only through two or more choices together | 22 | 19 |
| called genes holding in ≥ 95 % of analyses | 18 of 40 | 20 of 40 |
| called genes holding in < 80 % | 8 | 9 |

Fragility 0 means no analysis in the space changes the call.

### Which decisions matter

| decision | genes flipped by this choice alone | flip rate (all / defensible) | share of fold-change variance (all / defensible) |
|---|---|---|---|
| efficiency | 6 | 0.074 / 0.051 | 0.041 / 0.028 |
| flagged | 4 | 0.100 / 0.107 | 0.089 / 0.104 |
| nondetect | 0 | 0.013 / 0.010 | 0.019 / 0.022 |
| refs | 31 | 0.592 / 0.421 | 0.347 / 0.274 |
| cut | 17 | 0.277 / 0.293 | 0.456 / 0.520 |
| test | 0 | 0.009 / 0.007 | 0.000 / 0.000 |
| multiplicity | 0 | 0.015 / 0.013 | 0.000 / 0.000 |

Largest pairwise interactions (share of variance): {'flaggedxrefs': 0.0152, 'refsxcut': 0.0099, 'flaggedxcut': 0.0062, 'flaggedxnondetect': 0.004, 'efficiencyxcut': 0.0033}.

**Pre-registration advisor.** Locking ['refs', 'cut'] protects every headline call. Locking ['efficiency', 'flagged', 'refs', 'cut'] protects every called gene; the remaining choices cannot flip any call.

### Headline genes

| gene | call | fold | holds (all) | holds (defensible) | fewest choices to flip (defensible) | minimal flip sets (defensible) |
|---|---|---|---|---|---|---|
| ODC1 | up | 3.59 | 0.996 | 1.000 | – | none |
| BIRC5 | up | 4.011 | 1.000 | 1.000 | – | none |
| NTRK1 | down | 0.066 | 0.998 | 0.998 | 4 | flagged + refs + cut + multiplicity |
| NM23A | up | 2.188 | 0.691 | 0.682 | 1 | cut; refs |

## What the calls lean on (baseline analysis)

* 4 genes flip when one tumour is removed; 26 different tumours can do it.
* 148 of 1745 single reference-well removals flip at least one gene; the worst flips 3.
* 7 of 40 called genes sit within one SE of the 2-fold line; 15 can be overturned by removing at most 5 tumours (greedy, an upper bound).

## Joint inference across analyses

Permutation max-T over 936 defensible Welch analyses per gene (999 permutations, seed 2026): 57 genes are associated with the MYCN-high group (BH q < 0.05). 24 genes are significant, same direction, in at least 95 % of analyses with family-wise control; of the called genes, 23. Significance is robust; the 2-fold threshold and the group definition are what make calls fragile.

## Troubleshooting

Observations: {'well_outlier': 92, 'sample_outlier': 12, 'ntc': 11, 'spatial': 4, 'reference_group_effect': 3, 'efficiency': 2}. Issues in the queue: 128 ({'no_demonstrated_effect': 116, 'changes_conclusion': 11, 'biases': 1}).

Identifiability: every sample sits in the same well on every plate: a position effect shared by all plates cannot be told apart from the sample, and largely cancels in reference normalisation; only plate-specific patterns are detectable; group membership is clustered on the plate; spatial artefacts could mimic group differences.

| rank | issue | impact | headline changed | calls changed | max move (SE) |
|---|---|---|---|---|---|
| 1 | Choice of refs changes 31 call(s) on its own | changes_conclusion | NM23A | 31 | 3.47 |
| 2 | Choice of cut changes 17 call(s) on its own | changes_conclusion | NM23A | 17 | 3.07 |
| 3 | Choice of efficiency changes 6 call(s) on its own | changes_conclusion | – | 6 | 2.547 |
| 4 | Choice of flagged changes 4 call(s) on its own | changes_conclusion | – | 4 | 3.704 |
| 5 | Reference pair HMBS/UBC(2) differs between groups | changes_conclusion | – | 3 | 0.868 |
| 6 | Reference pair HMBS/HPRT1 differs between groups | changes_conclusion | – | 3 | 0.868 |
| 7 | Outlying well H20 on PRKACB_bis | changes_conclusion | – | 1 | 0.495 |
| 8 | Outlying well K22 on HMBS | changes_conclusion | – | 1 | 0.459 |
| 9 | Outlying well F23 on HPRT1 | changes_conclusion | – | 1 | 0.414 |
| 10 | Reference pair SDHA(1)/UBC(2) differs between groups | changes_conclusion | – | 1 | 0.326 |

## Can cheaper search find the same flips?

| strategy | runs | share of space | genes with a flip found | pairwise coverage |
|---|---|---|---|---|
| rings <= 1 | 43 | 0.190% | 32 / 54 | 0.394 |
| rings <= 2 | 463 | 2.049% | 47 / 54 | 1.000 |
| covering array t=2 | 98 | 0.434% | 47 / 54 | 1.000 |
| covering array t=3 | 452 | 2.000% | 49 / 54 | 1.000 |
| Morris, 20 trajectories | 160 | 0.708% | 48 / 54 | 0.583 |
| random, 500 cells | 496 | 2.195% | 51 / 54 | 0.997 |

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

Timings (s): {'load_s': 0.12, 'full_grid_s': 13.33, 'influence_s': 1.97, 'joint_test_s': 1.41, 'troubleshoot_s': 0.9, 'explorer_check_s': 4.58, 'benchmark_s': 195.04}.
