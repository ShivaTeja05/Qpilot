"""Train the Curve Judge: the paper's amplification classifier, refitted with a fixed seed.

Usage (training environment)::

    python training/curve_judge/train.py --data DATA_DIR --out qpilot/models/curve_judge

Writes ``model.json`` (XGBoost's own JSON format: no pickle, loadable without XGBoost by
``qpilot.qpcr.curve_judge``) and ``model.sha256`` (``sha256sum`` format). Then run
``evaluate.py``, which applies the held-out gate and writes ``metrics.json``.

Model, exactly as published (no re-tuning):

* inputs: the 40 normalised fluorescence values ``Cyc1..Cyc40`` only (paper, Modeling
  development; ``R:188``);
* hyperparameters: the paper's Table 1, "Amplification model" column, which the script sets at
  ``R:127-142``: ``eta 0.5, max_depth 13, min_child_weight 1, subsample 0.7, gamma 0.1,
  colsample_bytree 0.7``, ``booster gbtree``, ``objective binary:logistic``;
* rounds: ``nrounds = 17`` (``R:188-189``, the model the paper evaluated on the 20 % test set);
* decision: ``p > 0.5`` is amplified (paper, Modeling development; ``R:212``).

Settings the R script left at R-xgboost defaults, pinned here so the fit is reproducible:

* ``base_score = 0.5``: the default of R xgboost 1.7 (CRAN in 2024). XGBoost >= 2.0 would
  otherwise estimate it from the labels;
* ``tree_method = "exact"``: what ``tree_method = "auto"`` chose in xgboost 1.x for fewer than
  4M training rows (132,171 here);
* ``seed = 20250120`` for row and column subsampling, and ``nthread = 1``.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np
import xgboost as xgb

sys.path.insert(0, str(Path(__file__).resolve().parent))
import features  # noqa: E402

SEED = 20250120
NUM_BOOST_ROUND = 17
PARAMS: dict[str, object] = {
    "booster": "gbtree",
    "objective": "binary:logistic",
    "eval_metric": "error",
    "eta": 0.5,
    "max_depth": 13,
    "min_child_weight": 1,
    "subsample": 0.7,
    "gamma": 0.1,
    "colsample_bytree": 0.7,
    "base_score": 0.5,
    "tree_method": "exact",
    "seed": SEED,
    "nthread": 1,
}


def train(x_train: np.ndarray, y_train: np.ndarray) -> xgb.Booster:
    """Fit the classifier on the normalised training curves."""
    dtrain = xgb.DMatrix(x_train, label=y_train, feature_names=features.CYC_COLUMNS)
    return xgb.train(PARAMS, dtrain, num_boost_round=NUM_BOOST_ROUND)


def write_model(booster: xgb.Booster, out_dir: Path) -> str:
    """Save ``model.json`` and ``model.sha256``; return the digest."""
    out_dir.mkdir(parents=True, exist_ok=True)
    model = out_dir / "model.json"
    booster.save_model(str(model))
    payload = model.read_bytes()
    if not payload.endswith(b"\n"):  # the repo's end-of-file hook would otherwise add it
        payload += b"\n"
        model.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (out_dir / "model.sha256").write_text(f"{digest}  model.json\n", encoding="ascii")
    return digest


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Train the Curve Judge classifier.")
    parser.add_argument("--data", type=Path, required=True, help="directory fetch.py filled")
    parser.add_argument("--out", type=Path, required=True, help="model directory")
    args = parser.parse_args(argv)

    data = features.build_dataset(args.data)
    train_idx, test_idx = features.split_indices(len(data.y))
    print(f"curves {len(data.y)}: train {len(train_idx)}, held out {len(test_idx)}")
    booster = train(data.x[train_idx], data.y[train_idx])
    digest = write_model(booster, args.out)
    size = (args.out / "model.json").stat().st_size
    print(f"model.json {size} bytes, sha256 {digest}, xgboost {xgb.__version__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
