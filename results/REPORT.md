# qPilot Decision Simulator: results on the public neuroblastoma benchmark

Input SHA-256 `bc1d233e3866ad4d…`, grid hash `d2a608136a83e59d`, seed 2026. qsim 0.1.0, qPilot 0.1.0, Python 3.11.14, NumPy 2.4.6, SciPy 1.17.1.

Study: 366 tumours, 58 genes compared (MYCN-high vs rest), 64 plates. Baseline calls: {'down': 29, 'none': 18, 'up': 11}.

## Decision space

8 decisions with levels [4, 3, 3, 3, 31, 3, 3, 3]: 90,396 analyses, **all evaluated** (exhaustive). Full sweep: 52.1 s on one core.

| | all options | defensible options only |
|---|---|---|
| analyses | 90,396 | 144 |
| genes whose call flips somewhere | 55 | 14 |
| fragility (fewest choices to flip): count of genes | {'0': 3, '1': 34, '2': 15, '3': 5, '5': 1} | {'0': 44, '1': 12, '2': 2} |
| genes that flip only through two or more choices together | 21 | 2 |
| called genes holding in ≥ 95 % of analyses | 16 of 40 | 31 of 40 |
| called genes holding in < 80 % | 10 | 4 |

Fragility 0 means no analysis in the space changes the call.

### Which decisions matter

| decision | genes flipped by this choice alone | flip rate (all / defensible) | share of fold-change variance (all / defensible) |
|---|---|---|---|
| efficiency | 6 | 0.078 / 0.027 | 0.029 / 0.097 |
| flagged | 4 | 0.075 / 0.000 | 0.040 / 0.002 |
| late_cq | 11 | 0.100 / 0.140 | 0.027 / 0.476 |
| nondetect | 0 | 0.067 / 0.042 | 0.050 / 0.083 |
| refs | 31 | 0.600 / 0.036 | 0.334 / 0.130 |
| cut | 17 | 0.284 / 0.000 | 0.416 / 0.000 |
| test | 0 | 0.010 / 0.000 | 0.000 / 0.000 |
| multiplicity | 0 | 0.018 / 0.000 | 0.000 / 0.000 |

Largest pairwise interactions (share of variance): {'late_cqxnondetect': 0.0334, 'late_cqxrefs': 0.0113, 'refsxcut': 0.0095, 'flaggedxlate_cq': 0.0069, 'flaggedxrefs': 0.0068}.

**Pre-registration advisor.** Locking ['late_cq', 'refs', 'cut'] protects every headline call. Locking ['efficiency', 'flagged', 'late_cq', 'refs', 'cut'] protects every called gene; the remaining choices cannot flip any call.

### Headline genes

| gene | call | fold | holds (all) | holds (defensible) | fewest choices to flip (defensible) | minimal flip sets (defensible) |
|---|---|---|---|---|---|---|
| ODC1 | up | 3.59 | 0.998 | 1.000 | – | none |
| BIRC5 | up | 4.011 | 1.000 | 1.000 | – | none |
| NTRK1 | down | 0.066 | 0.862 | 0.833 | 1 | late_cq |
| NM23A | up | 2.188 | 0.722 | 1.000 | – | none |

**Locked before the sweep:** baseline, tiers and rule, SHA-256 `5f5983a21a42e33a…` (results/lock.json).

**Question choices, reported separately** (they change the claim, not the analysis): calls changed by each alone {'cut': 17, 'multiplicity': 0}.

## Verdicts in plain words

Rules: solid = same call in >= 95 % of defensible analyses, no 5 or fewer samples overturn it, significant in >= 95 %; fragile = < 80 %, or <= 2 samples overturn it, or within 0.1 log2 of the fold line; check data first = a data finding changes it.

check data first: 2 · fragile: 5 · depends on your choices: 3 · holds with caveats: 7 · solid: 23 · no call: 18

## What the calls lean on (baseline analysis)

* 4 genes flip when one tumour is removed; 26 different tumours can do it.
* 148 of 1745 single reference-well removals flip at least one gene; the worst flips 3.
* 7 of 40 called genes sit within one SE of the 2-fold line; 15 can be overturned by removing at most 5 tumours (greedy, an upper bound).

## Joint inference across analyses

Permutation max-T over 48 defensible Welch analyses per gene (999 permutations, seed 2026): 56 genes are associated with the MYCN-high group (BH q < 0.05). 50 genes are significant, same direction, in at least 95 % of analyses with family-wise control; of the called genes, 35. Significance is robust; the 2-fold threshold and the group definition are what make calls fragile.

## Troubleshooting

Observations: {'well_outlier': 92, 'sample_outlier': 12, 'ntc': 11, 'spatial': 4, 'reference_group_effect': 3, 'efficiency': 2}. Issues in the queue: 129 ({'no_demonstrated_effect': 116, 'changes_conclusion': 12, 'biases': 1}).

Identifiability: every sample sits in the same well on every plate: a position effect shared by all plates cannot be told apart from the sample, and largely cancels in reference normalisation; only plate-specific patterns are detectable; group membership is clustered on the plate; spatial artefacts could mimic group differences.

| rank | issue | impact | headline changed | calls changed | max move (SE) |
|---|---|---|---|---|---|
| 1 | The reference genes: changing only this changes 31 call(s) | changes_conclusion | NM23A | 31 | 3.47 |
| 2 | The group cut-off: changing only this changes 17 call(s) | changes_conclusion | NM23A | 17 | 3.07 |
| 3 | The late-Cq cut-off: changing only this changes 11 call(s) | changes_conclusion | NTRK1 | 11 | 6.658 |
| 4 | The efficiency model: changing only this changes 6 call(s) | changes_conclusion | – | 6 | 2.547 |
| 5 | How flagged wells are handled: changing only this changes 4 call(s) | changes_conclusion | – | 4 | 3.704 |
| 6 | Reference pair HMBS/UBC(2) differs between groups | changes_conclusion | – | 3 | 0.868 |
| 7 | Reference pair HMBS/HPRT1 differs between groups | changes_conclusion | – | 3 | 0.868 |
| 8 | Outlying well H20 on PRKACB_bis | changes_conclusion | – | 1 | 0.495 |
| 9 | Outlying well K22 on HMBS | changes_conclusion | – | 1 | 0.459 |
| 10 | Outlying well F23 on HPRT1 | changes_conclusion | – | 1 | 0.414 |

## Can cheaper search find the same flips?

| strategy | runs | share of space | genes with a flip found | pairwise coverage |
|---|---|---|---|---|
| rings <= 1 | 46 | 0.051% | 34 / 55 | 0.386 |
| rings <= 2 | 592 | 0.655% | 49 / 55 | 1.000 |
| covering array t=2 | 124 | 0.137% | 49 / 55 | 1.000 |
| covering array t=3 | 504 | 0.558% | 52 / 55 | 1.000 |
| Morris, 20 trajectories | 179 | 0.198% | 49 / 55 | 0.611 |
| random, 500 cells | 500 | 0.553% | 51 / 55 | 0.997 |

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

## Typical bench experiments drawn from the real data

100 random draws per size; defensible analyses = 144 (question choices fixed); robust = same call in >= 95 %.

| n per group | false calls, single analysis (no true difference) | false calls after robust filter | real difference: calls passing filter | disagree with full study: robust / not robust |
|---|---|---|---|---|
| 3 | 2.45% | 0.00% | 0.0 | None / 0.286 |
| 6 | 2.81% | 0.24% | 0.162 | 0.247 / 0.216 |

The filter removes analysis-induced false calls; it does not fix small-sample noise (robust and non-robust real calls disagree with the full study about equally).

Timings (s): {'load_s': 0.15, 'full_grid_s': 52.1, 'influence_s': 1.93, 'joint_test_s': 0.54, 'troubleshoot_s': 0.8, 'explorer_check_s': 6.4, 'benchmark_s': 174.45, 'designs_s': 79.34}.
