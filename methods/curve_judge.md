# Method card: Curve Judge (learned amplification call)

**What it answers.** For each well: did this curve amplify? The answer comes from the shape of
the raw amplification curve, using a classifier trained on expert calls. It is **one option on
the `amp_call` axis** ("Which curves count as amplified"). It is **never the default**: the
default stays `linregpcr`. It is offered only when `qpilot.qpcr.curve_judge.validated()` is
True, which requires the pre-registered transfer test on the instrument to have passed.
Otherwise it ships disabled, labelled *not validated for this instrument*.

**Status on the demo instrument (LightCycler 480, SYBR Green I): the pre-registered transfer
test passed on 17 Oct 2026, so the learned option may be offered (never as the default).** It
passed with little margin, and it has a systematic blind spot for very early curves: see
*Transfer result*.

## Paper, data, licence

- **Paper.** Brintz BJ, Operario DJ, Brown DG, Wu S, Wang L, Houpt ER, Leung DT, Liu J,
  Platts-Mills JA. *Automated post-run analysis of arrayed quantitative PCR amplification
  curves using machine learning.* Gates Open Research 9:1 (2025),
  doi:10.12688/gatesopenres.16313.1.
- **Data.** 165,214 qPCR curves with expert amplification calls from the University of
  Virginia: 56,539 from the MAL-ED cohort and 108,675 from a diarrhoea-aetiology study in Niger.
  All were run on TaqMan Array Cards (hydrolysis probes, FAM or VIC, with the ROX passive
  reference) for 40 cycles, on stool nucleic acid. Source:
  github.com/bbrintz/qPCR-amp-call, tag v1.0.0 (commit `191675b`), archived as
  doi:10.5281/zenodo.13798821. The files are pinned by SHA-256 in
  `training/curve_judge/fetch.py`.
- **Licence.** The GitHub `LICENSE` file reads `CC0 1.0 Universal` (SPDX `CC0-1.0`), and the
  paper's data statement says CC0 1.0. The Zenodo record says `cc-by-4.0`. qPilot follows the
  stricter one, **CC BY 4.0**. Attribution: the data are by Brintz et al. (above), licensed
  under CC BY 4.0 (creativecommons.org/licenses/by/4.0). qPilot changed them by fitting its
  own model with the authors' published hyperparameters. The data themselves are not
  redistributed.

## Model

| | |
|---|---|
| Algorithm | XGBoost gradient-boosted trees (`gbtree`, `binary:logistic`), 17 trees |
| Hyperparameters | the paper's Table 1 "Amplification model": eta 0.5, max_depth 13, min_child_weight 1, subsample 0.7, gamma 0.1, colsample_bytree 0.7; 17 rounds (`R:188-189`); base_score 0.5, tree_method exact (R-xgboost 1.7 defaults, made explicit), seed 20250120 |
| File | `qpilot/models/curve_judge/model.json` (XGBoost JSON, 169,376 bytes), SHA-256 `39ea518cb716c82534e4371ce43ad74ee2adc7be809324bdb8847c79a9e586f9` |
| Integrity | Checked against `model.sha256` **and** the pin compiled into `curve_judge.py` before parsing; refused otherwise. Never unpickled, never `eval`-ed, no network |
| Inference | numpy tree walk in `qpilot/qpcr/curve_judge.py` (float32, `x < threshold` goes left, NaN follows the learned default direction, `p = logistic(logit(0.5) + Σ leaves)`); XGBoost is not a qPilot dependency |
| Training code | `training/curve_judge/` (outside the package) |

## Inputs and outputs

- **Input.** 40 numbers per well, `Cyc1..Cyc40`. On the training instrument these were
  `Fstand = reporter / ROX` per cycle, then the paper's `Fnorm = Fstand − (Fmin − 1)`, so each
  curve's minimum is 1.
- **On an instrument without ROX** (`features_from_rdml`): raw fluorescence per well and cycle
  is read from the RDML only through `qpilot.io.rdml_io.load` and the vendored rdmlpython
  (`Run.getreactjson`, the same `adp` points LinRegPCR uses). Cycles 1-40 are kept by cycle
  number; later cycles are dropped and missing ones are NaN. Then `Fstand = F / min(F)` per
  curve (the per-curve substitution for ROX), then the paper's `Fnorm`. A curve whose minimum
  is not positive cannot be called (`callable = False`, call = not amplified).
- **Output.** `learned_p` (probability of amplification) and the call `p > 0.5`, per well,
  keyed `run_id/well`.

## Training split and held-out metrics

The paper's 80/20 split by reaction (132,171 / 33,043) has the same sizes here, but uses a
seeded random permutation, because the authors' index file is unpublished. Held-out (n =
33,043): **accuracy 0.9968**, sensitivity 0.9932, specificity 0.9979, PPV 0.9931, NPV 0.9979;
confusion TN 25,181, FP 54, FN 53, TP 7,755. The paper reports accuracy 0.996, and its Table 2
gives 0.993 / 0.997 for sensitivity / specificity. **Gate (accuracy ≥ 0.99): passed.** The
numpy evaluator reproduces `xgboost.Booster.predict` exactly (max |Δp| = 0.0 on all 165,214
curves). Details: `qpilot/models/curve_judge/metrics.json`.

## Transfer result (demo: Vermeulen 2009, LightCycler 480, SYBR Green I, `biomarker_set`)

The gate, the threshold and both substitutions (per-curve `F / min(F)` instead of ROX; LC480
cycles 1-40 → `Cyc1..Cyc40`, cycles 41-50 dropped) were committed in
`training/curve_judge/transfer.py` (commit `94f2b48`) before any prediction on demo data. The
result is in `qpilot/models/curve_judge/transfer.json`, for model `39ea518c…`.

| Criterion (all must hold) | Result | |
|---|---|---|
| (a) ≥ 99 % of the 960 standard wells (STD_15 … STD_150000) called amplified | 960 / 960 (100 %); every level 192 / 192 | **pass** |
| (b) ≥ 99 % agreement with LinRegPCR's amplification call, unknown wells with Cq < 30 | 16,043 / 16,153 (**99.32 %**). The 110 disagreements are all learned *no* where LinRegPCR says *yes*; 1 well both *no* | **pass** |
| (c) NTC calls tabulated (no threshold) | 192 NTC wells: 17 called amplified by the Curve Judge, 23 by LinRegPCR. All 17 are among LinRegPCR's 23; the other 6 have LinRegPCR Cq 44-47, beyond the model's 40 cycles | **pass** (tabulated) |

**Verdict: pass. The learned option is enabled as one non-default option on `amp_call`.**

Read beyond the verdict:

- **Post-hoc, descriptive (not part of the gate).** All 110 disagreements in (b) are wells of
  one target, `ALUsq(Eurogentec)`, a reference gene in the demo's primary analysis. Their
  LinRegPCR Cq is 9.5-13.5, and every one gets the same probability, 0.400. Curves that rise
  this early are rare in training: 231 of the 39,093 amplified training curves (0.6 %) have
  an expert Ct below 14. Treat very early curves (Cq ≲ 14) as outside what the model knows.
- **False positives.** By design the gate cannot see over-calling. Evidence: the 17 NTC calls
  above, all shared with LinRegPCR, several with LinRegPCR Cq above 40, where the model sees
  only the start of the rise. On all 23,424 unknown wells: 22,933 both *yes*, 332 both *no*,
  157 learned *no* / LinRegPCR *yes*, 2 learned *yes* / LinRegPCR *no*.
- The margin on (b) is 0.32 percentage points. Retraining, or any change to the substitution,
  needs a new pre-registered run.

## Known limits

- **Chemistry.** Trained only on hydrolysis-probe (TaqMan) curves. SYBR Green curves have a
  different baseline, amplitude and plateau, and they have primer-dimer and non-specific
  signal in late cycles and in NTCs, which never appear in training.
- **Instrument and reference dye.** Trained on ROX-standardised QuantStudio TAC data. The
  per-curve `F / min(F)` stand-in keeps the shape but not the scale: SYBR curves rise far more,
  relative to baseline, than any training curve.
- **Very early curves.** On the demo, every `ALUsq(Eurogentec)` well with Cq 9.5-13.5 that
  LinRegPCR calls amplified, 110 in all, is called *not* amplified (p = 0.400). These are
  outside the training range.
- **Cycle count.** Exactly 40 inputs. Amplification after cycle 40 is invisible. Runs with
  fewer than 40 cycles leave inputs missing, handled by the trees' default directions, which
  were never trained on missing data.
- **Curve types not in training.** Melt curves, digital PCR, multi-dye wells (refused), and
  background-subtracted exports with zero or negative values (not callable). Also any sample
  matrix other than stool nucleic acid.
- **Held-out ≠ new instrument.** The held-out curves share cards and runs with the training
  curves (the split is by reaction, as in the paper).
- **Gate blind spot.** The transfer gate tests calls on wells expected to amplify. It cannot
  detect a model that over-calls. The NTC table and the descriptive 2×2 on all unknown wells in
  `transfer.json` are the evidence on false positives.
- Research use only.

## The rule

The learned call is one option on the `amp_call` axis, shown beside `linregpcr` and the Cq
cut-offs, and **never the default**. It reaches the axis only through
`register_learned(LEARNED_RULE, predict)`, and only when `validated()` is True. Re-labels by a
person are proposals (`curve.well_call`). The model never decides on its own.
