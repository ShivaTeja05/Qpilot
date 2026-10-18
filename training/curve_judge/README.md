# Curve Judge: training (outside the package)

This folder rebuilds the model behind qPilot's learned amplification call from the published
data. Nothing here is imported by qPilot or shipped in the wheel. The package ships only the
result, in `qpilot/models/curve_judge/`: `model.json`, `model.sha256`, `metrics.json`,
`transfer.json` and `METHOD_CARD.md`. It evaluates the trees with numpy in
`qpilot/qpcr/curve_judge.py`, so XGBoost is a training dependency only.

| File | What it does |
|---|---|
| `fetch.py` | Downloads the authors' CSVs at a pinned commit and checks SHA-256, size and git blob id. `--check-licence` re-reads both licence statements. |
| `features.py` | The authors' preprocessing, line by line from their R script (`R:<line>` citations). Also defines the 80/20 split. |
| `train.py` | XGBoost with the paper's hyperparameters and a fixed seed. Writes `model.json` and `model.sha256`. |
| `evaluate.py` | Held-out metrics, the **accuracy ≥ 0.99 gate**, and the numpy-evaluator vs `xgboost.Booster.predict` check. Writes `metrics.json`. |
| `transfer.py` | The **pre-registered** transfer test on the demo instrument. Writes `transfer.json`. It was committed on its own, before any prediction on demo data. |
| `requirements.txt` | Exact versions of the training environment. |

## Reproduce

Use a separate venv outside the repository. Keep the data outside the repository too: it is
never committed.

```sh
python3.11 -m venv /tmp/cj-venv && /tmp/cj-venv/bin/pip install -r training/curve_judge/requirements.txt
/tmp/cj-venv/bin/python -I training/curve_judge/fetch.py --check-licence --out /tmp/cj-data
/tmp/cj-venv/bin/python -I training/curve_judge/train.py --data /tmp/cj-data --out qpilot/models/curve_judge
/tmp/cj-venv/bin/python -I training/curve_judge/evaluate.py --data /tmp/cj-data --model qpilot/models/curve_judge
# then, in qPilot's own environment (no XGBoost), with the demo cached by `qpilot fetch-demo`:
python training/curve_judge/transfer.py --preregistered-in <commit that added transfer.py>
```

Training is deterministic: two runs give the same `model.json` byte for byte (SHA-256
`39ea518cb716c82534e4371ce43ad74ee2adc7be809324bdb8847c79a9e586f9`, 169,376 bytes, 17 trees).
If you retrain and the hash changes, update `MODEL_SHA256` in `qpilot/qpcr/curve_judge.py` and
re-run `evaluate.py` and `transfer.py`. A new hash means the old `transfer.json` no longer
validates anything, so `validated(rdml_path)` turns False until the transfer test passes again.

## Data source

- **Paper.** Brintz BJ, Operario DJ, Brown DG, Wu S, Wang L, Houpt ER, Leung DT, Liu J,
  Platts-Mills JA. *Automated post-run analysis of arrayed quantitative PCR amplification
  curves using machine learning.* Gates Open Research 9:1 (2025),
  doi:[10.12688/gatesopenres.16313.1](https://doi.org/10.12688/gatesopenres.16313.1).
- **Data and code.** <https://github.com/bbrintz/qPCR-amp-call>, tag `v1.0.0` = commit
  `191675bd644a4b8e087d371d65b42ced58230afc`, archived on Zenodo as
  doi:[10.5281/zenodo.13798821](https://doi.org/10.5281/zenodo.13798821). The later `main`
  commit `f07ced3` changes only `README.md`; the data files are byte-identical.

| File (raw.githubusercontent.com/bbrintz/qPCR-amp-call/191675b…/) | Bytes | SHA-256 |
|---|---:|---|
| `raw_training.csv` (MAL-ED curves, long by cycle) | 30,921,212 | `beba58ebd9c8dc4e8f2d8cc762ce7ce440d60cff329eba0aaecd37c3642b738c` |
| `qpcr_training_data.csv` (MAL-ED expert labels) | 39,852,277 | `d7e55d5d91b6569606c4c5ab8bce84387f498dcb3e70b876b8a67c1cbd4d6cda` |
| `niger_final.csv` (Niger curves and labels) | 77,948,217 | `fb89a8b178c3b4ef24e94145ee4368e6acf615474053169447701ca60483a7e6` |
| `qPCR-amp-call_xgboost.R` (the authors' script) | 12,872 | `367d4561711dfb3f6ca3c53e91842589e9eb561e8ed1fe65797bb7c88d9d70e3` |
| `LICENSE` | 7,048 | `a2010f343487d3f7618affe54f789f5487602331c0a8d03f49e9a7c547cf0499` |

## Licence (checked 17 Oct 2026; the stricter one is followed)

| Where | What it says (quoted) |
|---|---|
| GitHub `LICENSE` file, line 3 | `CC0 1.0 Universal` (GitHub's licence API: `"spdx_id": "CC0-1.0"`) |
| Paper, *Data availability* | Creative Commons Zero "No rights reserved" data waiver (CC0 1.0 Public domain dedication) |
| Zenodo record 13798821 (API `metadata.license`) | `{"id": "cc-by-4.0"}` |
| Paper itself | Creative Commons Attribution Licence |

The two data statements differ: CC0 on GitHub and in the paper, CC BY 4.0 on Zenodo. **qPilot
follows the stricter one, CC BY 4.0.** That means attribution, a link to the licence, and a
statement of what changed. The attribution travels with the model in `METHOD_CARD.md` and in
`methods/curve_judge.md`. The change is that the data was used to fit a new model with the
published hyperparameters. The data is not redistributed: it is not in the repository, the
sdist or the wheel.

## What the scripts reproduce, and where they had to choose

- **Preprocessing.** Exactly as published, `Fnorm = Fstand − (Fmin − 1)` over 40 cycles. The
  published CSVs are already ROX-standardised. The R script never divides them by ROX
  (`R:14-30`), though it does divide the raw external exports (`R:241-242`), and the values are
  O(1). The MAL-ED reshape and join follow `R:18-25`. Counts match the paper: 56,539 MAL-ED +
  108,675 Niger = 165,214 curves, 39,093 of them amplified. The dye split comes out 115,961 FAM
  / 49,253 VIC against the paper's 115,965 / 49,249. That is 4 curves, and dye is not a model
  input.
- **Split.** The paper uses 80/20 (132,171 / 33,043). The script loads its indices from
  `main_idx_vNiger.rds` (`R:40`), but that file is not published. So `features.split_indices`
  draws a uniform random permutation with seed `20250120` and uses the first 132,171 to train:
  the same sizes, split by reaction as in the paper. Fingerprint of the test indices: in
  `metrics.json` (`split.test_index_sha256`). As in the paper, held-out curves can come from the
  same cards and runs as training curves. That is one reason held-out accuracy says nothing
  about another instrument.
- **Model.** The amplification model only, with the hyperparameters in Table 1 of the paper
  (`R:127-142`) and 17 rounds (`R:188-189`). The Ct-regression model is not trained, because
  qPilot's Cq comes from LinRegPCR. There is no re-tuning. The paper says 5-fold CV and the
  script says `nfold = 10`; we tune nothing, so this does not matter here.
- **R-xgboost defaults made explicit.** `base_score = 0.5`, the default of R xgboost 1.7 (CRAN
  in 2024). Newer XGBoost would estimate it from the labels. `tree_method = "exact"`, which is
  what `auto` picked in xgboost 1.x for under 4M rows. `seed = 20250120`, `nthread = 1`.
- **File format.** `model.json` is `Booster.save_model` output plus one trailing newline, so
  the repository's end-of-file hook never changes the pinned bytes.

## Results (from `metrics.json`)

Held-out set, n = 33,043, call = `p > 0.5`:

| | qPilot refit | Paper (Table 2) |
|---|---:|---:|
| Accuracy | **0.9968** | 0.996 |
| Sensitivity | 0.9932 (7,755 / 7,808) | 0.993 (7,752 / 7,805)\* |
| Specificity | 0.9979 (25,181 / 25,235) | 0.997 (25,166 / 25,238)\* |
| Confusion (TN, FP, FN, TP) | 25,181, 54, 53, 7,755 | 25,166, 72, 53, 7,752 |

\* Computed from the paper's own Table 2. The paper's text gives sensitivity 0.997 and
specificity 0.993, which look swapped.

**Gate: held-out accuracy ≥ 0.99. Passed (0.9968).**

**Evaluator check.** qPilot's numpy evaluator and `xgboost.Booster.predict` (3.2.0) differ by
**0.0** (max absolute difference in probability and in margin) on all 33,043 held-out curves
and on all 165,214 curves, and no call differs. The allowed tolerance was 1e-6. The package
test replays 36 stored curves, including misclassified and borderline curves and curves with
missing cycles, without XGBoost.

## Transfer test

See `transfer.py` for the gate, pre-registered in commit `94f2b48` before any demo prediction,
and `qpilot/models/curve_judge/transfer.json` for the result. Held-out accuracy on TaqMan Array
Cards is not evidence for SYBR Green on a LightCycler 480. Only the transfer test decides
whether the learned option is offered.

Result, 17 Oct 2026, model `39ea518c…`: **pass**.

- (a) 960 / 960 standards called amplified.
- (b) 16,043 / 16,153 = 99.32 % agreement with LinRegPCR at Cq < 30.
- (c) 192 NTCs tabulated: 17 called amplified, against LinRegPCR's 23.

Post-hoc, all 110 disagreements in (b) are very early `ALUsq(Eurogentec)` curves (Cq 9.5-13.5)
that the model calls not amplified. See `methods/curve_judge.md`.
