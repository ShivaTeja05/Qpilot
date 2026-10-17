"""Held-out evaluation, the accuracy gate, and the numpy-evaluator check -> ``metrics.json``.

Usage (training environment)::

    python training/curve_judge/evaluate.py --data DATA_DIR --model qpilot/models/curve_judge

1. Rebuilds the dataset and the fixed 80/20 split (``features.py``), loads ``model.json`` with
   XGBoost, and scores the 33,043 held-out curves at the paper's threshold (``p > 0.5``):
   accuracy, sensitivity, specificity, PPV, NPV, confusion matrix, n; also by data source and
   dye, and the paper's 0.1-0.9 "flag" band.
2. **Gate: held-out accuracy >= 0.99** (the paper reports 0.996). Below it, the script exits 1
   and the model must not ship.
3. Loads the same file with qPilot's numpy evaluator (``qpilot.qpcr.curve_judge``, after its
   SHA-256 check) and compares it with ``xgboost.Booster.predict`` on every held-out curve and on
   all 165,214 curves; the evaluator must agree to within 1e-6 in probability.
4. Stores a small sample of held-out curves (inputs before normalisation, XGBoost's margin and
   probability) that ``tests/engine/test_curve_judge.py`` replays without XGBoost.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import sklearn
import xgboost as xgb
from sklearn.metrics import confusion_matrix

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))
import features  # noqa: E402
import fetch  # noqa: E402
import train  # noqa: E402

from qpilot.qpcr import curve_judge  # noqa: E402

GATE_ACCURACY = 0.99
TOLERANCE = 1e-6
THRESHOLD = 0.5
FLAG_BAND = (0.1, 0.9)
SAMPLE_SEED = 7
PAPER = {
    "source": "Brintz et al. 2025, Gates Open Res 9:1, Results and Table 2 (internal validation)",
    "n": 33043,
    "accuracy": 0.996,
    "sensitivity": 0.997,
    "specificity": 0.993,
    "ppv": 0.998,
    "npv": 0.991,
    "confusion_matrix": {"tn": 25166, "fp": 72, "fn": 53, "tp": 7752},
    "note": "From the paper's own Table 2, sensitivity = 7752/7805 = 0.993 and specificity = "
    "25166/25238 = 0.997; the text's 0.997 / 0.993 appear swapped. Accuracy 0.996 agrees.",
}


def scores(y: np.ndarray, p: np.ndarray) -> dict[str, object]:
    """Accuracy, sensitivity, specificity, PPV, NPV and the confusion matrix at p > 0.5."""
    pred = (p > THRESHOLD).astype(int)
    tn, fp, fn, tp = (int(v) for v in confusion_matrix(y, pred, labels=[0, 1]).ravel())
    assert tn + fp + fn + tp == len(y)
    assert tp == int(((pred == 1) & (y == 1)).sum()) and tn == int(((pred == 0) & (y == 0)).sum())
    n = len(y)
    lo, hi = FLAG_BAND
    flagged = (p > lo) & (p < hi)
    wrong = pred != y
    return {
        "n": n,
        "accuracy": (tp + tn) / n,
        "sensitivity": tp / (tp + fn) if tp + fn else None,
        "specificity": tn / (tn + fp) if tn + fp else None,
        "ppv": tp / (tp + fp) if tp + fp else None,
        "npv": tn / (tn + fn) if tn + fn else None,
        "confusion_matrix": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
        "misclassified": int(wrong.sum()),
        "flagged_0.1_0.9": {
            "misclassified_flagged": int((flagged & wrong).sum()),
            "correct_flagged": int((flagged & ~wrong).sum()),
        },
    }


def _round(obj: object) -> object:
    if isinstance(obj, float):
        return round(obj, 6)
    if isinstance(obj, dict):
        return {k: _round(v) for k, v in obj.items()}
    return obj


def evaluator_sample(
    data: features.Dataset, test_idx: np.ndarray, p: np.ndarray, booster: xgb.Booster
) -> list[dict[str, object]]:
    """A fixed sample of held-out curves for the package test, plus curves with gaps (NaN)."""
    rng = np.random.default_rng(SAMPLE_SEED)
    y = data.y[test_idx]
    pred = p > THRESHOLD
    groups = {
        "true_positive": np.flatnonzero(pred & (y == 1)),
        "true_negative": np.flatnonzero(~pred & (y == 0)),
        "misclassified": np.flatnonzero(pred != (y == 1)),
        "borderline": np.flatnonzero((p > 0.1) & (p < 0.9)),
    }
    chosen: list[tuple[str, int]] = []
    for name, members in groups.items():
        take = rng.choice(members, size=min(8, len(members)), replace=False)
        chosen += [(name, int(test_idx[i])) for i in sorted(take)]
    rows = [(name, data.rn[i].copy()) for name, i in chosen]
    # Missing cycles exercise the default directions (cycles are 1-based in the names).
    gaps = {
        "missing_cycles_1_5": slice(0, 5),
        "missing_cycles_31_40": slice(30, 40),
        "missing_odd_cycles": slice(0, 40, 2),
        "missing_cycle_40": slice(39, 40),
    }
    for (name, cycles), (_, i) in zip(gaps.items(), chosen[:4], strict=True):
        curve = data.rn[i].copy()
        curve[cycles] = np.nan
        rows.append((name, curve))
    rn = np.vstack([curve for _, curve in rows])
    dmat = xgb.DMatrix(features.normalise(rn), feature_names=features.CYC_COLUMNS)
    margin = booster.predict(dmat, output_margin=True)
    prob = booster.predict(dmat)
    return [
        {
            "kind": name,
            "fluorescence": [None if np.isnan(v) else float(v) for v in curve],
            "xgboost_margin": float(m),
            "xgboost_p": float(q),
        }
        for (name, curve), m, q in zip(rows, margin, prob, strict=True)
    ]


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point; exits 1 if the gate or the evaluator check fails."""
    parser = argparse.ArgumentParser(description="Evaluate the Curve Judge; write metrics.json.")
    parser.add_argument("--data", type=Path, required=True, help="directory fetch.py filled")
    parser.add_argument("--model", type=Path, required=True, help="directory with model.json")
    args = parser.parse_args(argv)

    data = features.build_dataset(args.data)
    train_idx, test_idx = features.split_indices(len(data.y))
    booster = xgb.Booster()
    booster.load_model(str(args.model / "model.json"))
    model_sha = hashlib.sha256((args.model / "model.json").read_bytes()).hexdigest()

    dtest = xgb.DMatrix(data.x[test_idx], feature_names=features.CYC_COLUMNS)
    p_test = booster.predict(dtest)
    m_test = booster.predict(dtest, output_margin=True)
    y_test = data.y[test_idx]
    held_out = scores(y_test, p_test)
    by_source = {
        s: scores(y_test[data.source[test_idx] == s], p_test[data.source[test_idx] == s])
        for s in ("maled", "niger")
    }
    by_dye = {
        d: scores(y_test[data.dye[test_idx] == d], p_test[data.dye[test_idx] == d])
        for d in ("FAM", "VIC")
    }
    passed = held_out["accuracy"] >= GATE_ACCURACY

    # The numpy evaluator, loaded through its own SHA-256 check (against model.sha256).
    ensemble = curve_judge.load_model(
        args.model / "model.json", args.model / "model.sha256", expected_sha256=model_sha
    )
    np_p_test = ensemble.predict_proba(data.x[test_idx])
    np_m_test = ensemble.margin(data.x[test_idx])
    dall = xgb.DMatrix(data.x, feature_names=features.CYC_COLUMNS)
    p_all = booster.predict(dall)
    np_p_all = ensemble.predict_proba(data.x)
    sample = evaluator_sample(data, test_idx, p_test, booster)
    sample_np = ensemble.predict_proba(
        curve_judge.normalise(
            np.array([[np.nan if v is None else v for v in s["fluorescence"]] for s in sample])
        )
    )
    sample_diff = max(
        abs(float(a) - s["xgboost_p"]) for a, s in zip(sample_np, sample, strict=True)
    )
    comparison = {
        "tolerance": TOLERANCE,
        "held_out": {
            "n": int(len(test_idx)),
            "max_abs_diff_p": float(np.max(np.abs(np_p_test.astype(np.float64) - p_test))),
            "max_abs_diff_margin": float(np.max(np.abs(np_m_test.astype(np.float64) - m_test))),
            "calls_differ": int(((np_p_test > THRESHOLD) != (p_test > THRESHOLD)).sum()),
        },
        "all_curves": {
            "n": int(len(data.y)),
            "max_abs_diff_p": float(np.max(np.abs(np_p_all.astype(np.float64) - p_all))),
            "calls_differ": int(((np_p_all > THRESHOLD) != (p_all > THRESHOLD)).sum()),
        },
        "stored_sample": {"n": len(sample), "max_abs_diff_p": sample_diff},
    }
    worst = max(
        comparison["held_out"]["max_abs_diff_p"],
        comparison["all_curves"]["max_abs_diff_p"],
        sample_diff,
    )
    comparison["passed"] = bool(worst <= TOLERANCE)

    metrics = {
        "model": "Curve Judge amplification classifier (XGBoost, binary:logistic)",
        "model_sha256": model_sha,
        "date": dt.date.today().isoformat(),
        "environment": {
            "python": sys.version.split()[0],
            "xgboost": xgb.__version__,
            "numpy": np.__version__,
            "scikit-learn": sklearn.__version__,
        },
        "data": {
            "repository": f"https://github.com/{fetch.REPO}",
            "commit": fetch.COMMIT,
            "zenodo": "https://doi.org/10.5281/zenodo.13798821",
            "files_sha256": {name: pin[0] for name, pin in fetch.PINS.items()},
            "n_curves": int(len(data.y)),
            "n_maled": int((data.source == "maled").sum()),
            "n_niger": int((data.source == "niger").sum()),
            "n_amplified": int(data.y.sum()),
        },
        "preprocessing": "Fnorm = Fstand - (Fmin - 1) per curve over Cyc1..Cyc40 (R:33-37)",
        "split": {
            "method": "uniform random permutation by reaction, first floor(0.8 n) train "
            "(the paper's 80/20; its index file main_idx_vNiger.rds is unpublished)",
            "seed": features.SPLIT_SEED,
            "n_train": int(len(train_idx)),
            "n_test": int(len(test_idx)),
            "test_index_sha256": features.index_sha256(test_idx),
        },
        "training": {"params": train.PARAMS, "num_boost_round": train.NUM_BOOST_ROUND},
        "threshold": THRESHOLD,
        "held_out": _round(held_out),
        "held_out_by_source": _round(by_source),
        "held_out_by_dye": _round(by_dye),
        "paper_held_out": PAPER,
        "gate": {
            "metric": "held-out accuracy",
            "threshold": GATE_ACCURACY,
            "value": round(held_out["accuracy"], 6),
            "passed": bool(passed),
        },
        "evaluator_vs_xgboost": comparison,
        "evaluator_sample": sample,
    }
    out = args.model / "metrics.json"
    out.write_text(json.dumps(metrics, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: metrics[k] for k in ("held_out", "gate")}, indent=1))
    print(json.dumps(comparison, indent=1))
    if not passed:
        print(f"GATE FAILED: accuracy {held_out['accuracy']:.4f} < {GATE_ACCURACY}")
        return 1
    if not comparison["passed"]:
        print(f"EVALUATOR CHECK FAILED: max |p diff| {worst:.3g} > {TOLERANCE}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
