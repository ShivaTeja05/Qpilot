"""Brintz et al. (2025) preprocessing, reproduced line by line from the authors' own R script.

Sources (both pinned in ``fetch.py``):

* the paper, Brintz BJ et al., *Automated post-run analysis of arrayed quantitative PCR
  amplification curves using machine learning*, Gates Open Research 9:1 (2025),
  doi:10.12688/gatesopenres.16313.1, Methods > Data;
* ``qPCR-amp-call_xgboost.R`` at commit ``191675b`` (tag v1.0.0), cited below as ``R:<line>``.

What the paper says (Methods > Data, paraphrased): each cycle's raw FAM or VIC value is
divided by that cycle's ROX reference-dye value (``Fstand``), then
``Fnorm = Fstand - (Fmin - 1)``, where ``Fmin`` is the curve's minimum ``Fstand`` over all 40
cycles.

What the code does with the published CSVs:

* The training CSVs already hold ROX-standardised values (Rn). The script never divides them
  by ROX (``R:14-30``), but it does divide the *external* instrument exports, which still carry
  a ROX column, by ROX (``R:241-242``: ``mutate(value=value/ROX)``). The published values are
  O(1) (median ~2.5), as Rn is, not O(10^4) as raw QuantStudio fluorescence is.
* MAL-ED (``R:14-25``): ``raw_training.csv`` is long by cycle and wide by well position; it is
  reshaped to one row per (card, dye, position) with 40 cycle columns, joined to the expert
  labels in ``qpcr_training_data.csv`` on (position, card, dye), and rows without a label are
  dropped. 56,539 curves.
* Niger (``R:28-30``): ``niger_final.csv`` already has ``Cyc1..Cyc40``, ``truth`` and ``Ct``;
  rows without ``truth`` are dropped. 108,675 curves.
* Both are stacked, MAL-ED first (``R:29``), and normalised per curve (``R:33-37``):
  ``min_value = min(Cyc - 1, na.rm = TRUE)`` and ``Cyc = Cyc - min_value``, i.e.
  ``Fnorm = Fstand - (Fmin - 1)``, so every curve's minimum becomes exactly 1.

The train/test split (``R:40``) loads ``main_idx_vNiger.rds``, which the authors did not
publish, so :func:`split_indices` draws an 80/20 split of the same sizes as the paper
(132,171 / 33,043) with a fixed seed. See ``README.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

N_CYCLES = 40
CYC_COLUMNS = [f"Cyc{i}" for i in range(1, N_CYCLES + 1)]
SPLIT_SEED = 20250120  # the paper's publication date
TRAIN_FRACTION = 0.8

#: Counts stated in the paper (Methods > Data); build_dataset checks them.
PAPER_N_MALED = 56_539
PAPER_N_NIGER = 108_675
PAPER_N_TOTAL = 165_214
PAPER_N_TRAIN = 132_171
PAPER_N_TEST = 33_043


@dataclass(frozen=True)
class Dataset:
    """The combined, normalised training data in the R script's row order."""

    x: np.ndarray  # (n, 40) float64, normalised (Fnorm)
    rn: np.ndarray  # (n, 40) float64, before normalisation (Fstand, the published Rn)
    y: np.ndarray  # (n,) int 0/1, the experts' call
    ct: np.ndarray  # (n,) float64, experts' Ct; "Undetermined" -> 40 (R:22)
    source: np.ndarray  # (n,) "maled" | "niger"
    dye: np.ndarray  # (n,) "FAM" | "VIC"


def normalise(rn: np.ndarray) -> np.ndarray:
    """``Fnorm = Fstand - (Fmin - 1)`` per curve (row), ignoring missing cycles (``R:33-37``).

    ``min(c_across(starts_with("Cyc")) - 1, na.rm = TRUE)`` is the row minimum minus one;
    every cycle then has it subtracted. NaN cycles stay NaN (XGBoost treats them as missing).
    """
    rn = np.asarray(rn, dtype=np.float64)
    min_value = np.nanmin(rn, axis=1, keepdims=True) - 1.0
    return rn - min_value


def load_maled(data_dir: Path) -> pd.DataFrame:
    """MAL-ED curves as ``R:14-25`` builds them: one row per labelled (card, dye, position)."""
    raw = pd.read_csv(data_dir / "raw_training.csv")  # R:15
    labels = pd.read_csv(  # R:14
        data_dir / "qpcr_training_data.csv",
        usecols=["card", "position", "dye", "truth", "ct"],
        dtype={"position": str, "dye": str, "ct": str},
    )
    id_cols = ["cycle", "card", "dye"]
    positions = [c for c in raw.columns if c not in id_cols]
    # R:18 gather(): positions stacked in column order, each over all rows in file order.
    long = raw.melt(id_vars=id_cols, value_vars=positions, var_name="position", value_name="v")
    # R:18 pivot_wider(): one row per (card, dye, position) in order of first appearance.
    keys = long[["card", "dye", "position"]].drop_duplicates()
    wide = long.pivot(index=["card", "dye", "position"], columns="cycle", values="v")
    wide = wide.reindex(pd.MultiIndex.from_frame(keys))
    if list(wide.columns) != list(range(1, N_CYCLES + 1)):
        raise ValueError(f"raw_training.csv: expected cycles 1..40, got {list(wide.columns)}")
    wide.columns = CYC_COLUMNS  # R:25
    wide = wide.reset_index()
    if labels.duplicated(["card", "position", "dye"]).any():
        raise ValueError("qpcr_training_data.csv: duplicate (card, position, dye) labels")
    # R:19 left_join by (position, card, dye); R:20 filter(!is.na(truth)).
    joined = wide.merge(labels, on=["position", "card", "dye"], how="left", sort=False)
    joined = joined[joined["truth"].notna()].reset_index(drop=True)
    # R:22 ct: "Undetermined" -> 40.
    joined["ct"] = pd.to_numeric(joined["ct"].replace("Undetermined", "40"), errors="raise")
    joined["source"] = "maled"
    joined["dye"] = joined["dye"].str.upper()
    return joined[[*CYC_COLUMNS, "truth", "ct", "source", "dye"]]


def load_niger(data_dir: Path) -> pd.DataFrame:
    """Niger curves as ``R:28-30`` reads them (``ct=Ct``; rows without ``truth`` dropped)."""
    niger = pd.read_csv(data_dir / "niger_final.csv")
    niger = niger.rename(columns={"Ct": "ct", "Reporter": "dye"})
    niger = niger[niger["truth"].notna()].reset_index(drop=True)  # R:30
    niger["ct"] = pd.to_numeric(niger["ct"], errors="coerce")
    niger["source"] = "niger"
    niger["dye"] = niger["dye"].astype(str).str.upper()
    return niger[[*CYC_COLUMNS, "truth", "ct", "source", "dye"]]


def build_dataset(data_dir: str | Path) -> Dataset:
    """MAL-ED then Niger (``R:29``), normalised (``R:33-37``); checks the paper's counts."""
    data_dir = Path(data_dir)
    maled = load_maled(data_dir)
    niger = load_niger(data_dir)
    if len(maled) != PAPER_N_MALED or len(niger) != PAPER_N_NIGER:
        raise ValueError(
            f"curve counts {len(maled)} (MAL-ED) / {len(niger)} (Niger) differ from the paper's "
            f"{PAPER_N_MALED} / {PAPER_N_NIGER}"
        )
    both = pd.concat([maled, niger], ignore_index=True)
    rn = both[CYC_COLUMNS].to_numpy(dtype=np.float64)
    if np.isnan(rn).all(axis=1).any():
        raise ValueError("a curve has no fluorescence value at all")
    y = both["truth"].to_numpy()
    if not np.isin(y, (0.0, 1.0)).all():
        raise ValueError("truth must be 0 or 1")
    return Dataset(
        x=normalise(rn),
        rn=rn,
        y=y.astype(np.int64),
        ct=both["ct"].to_numpy(dtype=np.float64),
        source=both["source"].to_numpy(dtype=str),
        dye=both["dye"].to_numpy(dtype=str),
    )


def split_indices(n: int, seed: int = SPLIT_SEED) -> tuple[np.ndarray, np.ndarray]:
    """80/20 split by reaction, as the paper describes; the paper's own indices are unpublished.

    A uniform random permutation with a fixed seed; the first ``floor(0.8 n)`` rows train.
    For n = 165,214 this gives the paper's 132,171 / 33,043. Both index arrays are sorted.
    """
    order = np.random.default_rng(seed).permutation(n)
    n_train = int(np.floor(TRAIN_FRACTION * n))
    return np.sort(order[:n_train]), np.sort(order[n_train:])


def index_sha256(index: np.ndarray) -> str:
    """Fingerprint of a split (sorted int64 indices), recorded in ``metrics.json``."""
    import hashlib

    return hashlib.sha256(np.ascontiguousarray(index, dtype="<i8").tobytes()).hexdigest()
