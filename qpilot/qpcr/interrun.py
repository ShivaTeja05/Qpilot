"""Correction between plates: when a gene's wells are spread over several runs.

A run (plate) adds its own offset to every quantity measured on it: a slightly different
threshold, efficiency or pipetting of the master mix. When all samples of a gene are on one
plate (sample maximisation, Hellemans et al., Genome Biol 2007) the offset is the same for every
sample of that gene and cancels in every fold change, so no correction can change a result.
When a gene's samples are split over plates the offset adds to the comparison, and there are
two published ways to remove it, both offered by :mod:`qpilot.qpcr.axes` as the ``interrun``
axis (never applied by default):

* ``calibrator`` — **inter-run calibration** (Hellemans et al. 2007; qbase, CFX Maestro): the
  same calibrator sample (an IRC, e.g. the planner's ``IRC`` with RDML type ``pos``) is measured
  for the gene on every plate. Per gene and plate the calibration factor is the calibrators'
  mean ``log2 N0`` there minus their mean over the gene's plates (several calibrators: the mean
  over them, i.e. the geometric mean of their factors), and it is subtracted from every well of
  that gene on that plate. Only non-study samples (any RDML type but ``unkn`` and the negative
  controls) that have a quantity for the gene on **every** one of its plates count; a gene
  without one is left as it is and listed.
* ``factor`` — **factor correction** (Ruijter et al., Biomol Detect Quantif 2015; 5:10-14,
  "Removal of between-run variation in a multi-plate qPCR experiment"): one factor per plate,
  from every measurement two plates share (the same target in the same sample, any sample type
  but the negative controls, every pair of their replicate wells). For each pair of plates the
  mean log ratio is the ratio of their factors (Eq. 2); a pair without a shared measurement is
  estimated through the other plates (Eq. 3, two passes); each plate's factor is the mean of its
  column (Eq. 4) and every quantity on the plate is divided by it (Eq. 5). A plate that shares
  nothing with any other is left as it is and listed.

This is a reimplementation in numpy on the log2 scale, following the same steps as the RDML
consortium's ``interRunCorr`` (``qpilot/vendor/rdmlpython``, MIT; it works on an RDML 1.4 file
and only after LinRegPCR has written ``Ncopy``), so it runs on qPilot's per-well table for any
import. Where ``interRunCorr`` would divide by a missing ratio while filling a gap it is skipped
here. Deterministic: plates in ``run_id`` order, targets and samples sorted.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd

from qpilot.qpcr.quant import EXCLUDED

AXIS = "interrun"
PRIMARY = "none"
OPTIONS: tuple[str, ...] = ("none", "calibrator", "factor")
NEGATIVE_TYPES = frozenset({"ntc", "nac", "ntp", "nrt", "opt"})  # never a calibrator or overlap
STUDY_TYPE = "unkn"
GAP_PASSES = 2  # Ruijter et al. 2015: more than two rounds means the design is incomplete
METHOD_CARD_PATH = "methods/inter_run_calibration.md"
SOURCES = {
    "calibrator": "Hellemans et al., Genome Biol 2007; 8:R19 (inter-run calibration)",
    "factor": "Ruijter et al., Biomol Detect Quantif 2015; 5:10-14 (factor correction)",
}

METHOD_CARD: dict[str, Any] = {
    "id": "inter_run_calibration",
    "version": "1",
    "title": "How to correct differences between plates",
    "source": "; ".join(SOURCES.values()),
    "implementation": "qpilot/qpcr/interrun.py",
    "inputs": ["per-well table: run_id, sample, sample_type, target, n0"],
    "outputs": ["the per-well table with n0 corrected between plates"],
    "acceptance_tests": [
        "tests/numbers/test_interrun.py::test_calibrator_removes_a_known_plate_offset",
        "tests/numbers/test_interrun.py::test_factor_recovers_known_plate_factors",
        "tests/numbers/test_interrun.py::test_factor_fills_a_gap_through_a_third_plate",
    ],
    "licence": "Apache-2.0",
    "card": METHOD_CARD_PATH,
}


@dataclass(frozen=True)
class Correction:
    """What one option did to a per-well table.

    ``table`` is the corrected table (``n0`` divided by the factors); ``factors`` the log2
    factor subtracted, per ``(run, target)`` for the calibrator and per ``(run, "*")`` for the
    factor correction (all targets of the plate); ``uncorrected`` the targets (calibrator) or
    plates (factor) that could not be corrected; ``calibrators`` the samples used per target.
    """

    option: str
    table: pd.DataFrame
    factors: dict[tuple[str, str], float] = field(default_factory=dict)
    uncorrected: tuple[str, ...] = ()
    calibrators: dict[str, tuple[str, ...]] = field(default_factory=dict)


def _usable(table: pd.DataFrame) -> pd.Series:
    """Wells with a positive quantity, not a negative control and not excluded by a person."""
    ok = table["n0"].gt(0) & ~table["sample_type"].isin(NEGATIVE_TYPES)
    if EXCLUDED in table.columns:
        ok &= ~table[EXCLUDED].fillna(False).astype(bool)
    return ok


def split_targets(table: pd.DataFrame) -> dict[str, tuple[str, ...]]:
    """Target -> the runs its study wells are on, for targets on two or more runs (sorted)."""
    study = table[table["sample_type"] == STUDY_TYPE]
    runs = study.groupby(study["target"].astype(str))["run_id"].unique()
    return {
        str(target): tuple(sorted(map(str, values)))
        for target, values in sorted(runs.items())
        if len(values) >= 2
    }


def calibrators(table: pd.DataFrame) -> dict[str, tuple[str, ...]]:
    """Target -> the calibrator samples measured for it on every one of its study runs.

    Only split targets (:func:`split_targets`); a calibrator is a non-study sample (RDML type
    other than ``unkn`` and the negative controls) with a quantity on each of those runs.
    """
    usable = table[_usable(table) & (table["sample_type"] != STUDY_TYPE)]
    out = {}
    for target, runs in split_targets(table).items():
        wells = usable[usable["target"].astype(str) == target]
        on = wells.groupby(wells["sample"].astype(str))["run_id"].apply(lambda r: set(map(str, r)))
        found = tuple(sorted(s for s, have in on.items() if set(runs) <= have))
        out[target] = found
    return out


def _log2(table: pd.DataFrame) -> pd.Series:
    return np.log2(table["n0"].where(table["n0"] > 0))


def calibrate(table: pd.DataFrame) -> Correction:
    """Inter-run calibration per gene and plate (see the module docstring)."""
    split = split_targets(table)
    found = calibrators(table)
    usable = table[_usable(table)]
    factors: dict[tuple[str, str], float] = {}
    uncorrected = []
    for target, runs in split.items():
        samples = found.get(target, ())
        if not samples:
            uncorrected.append(target)
            continue
        wells = usable[
            (usable["target"].astype(str) == target)
            & usable["sample"].astype(str).isin(samples)
            & usable["run_id"].astype(str).isin(runs)
        ]
        per = (
            _log2(wells)
            .groupby([wells["sample"].astype(str), wells["run_id"].astype(str)])
            .mean()
            .unstack("run_id")
            .reindex(columns=list(runs))
        )
        deviation = per.sub(per.mean(axis=1), axis=0).mean(axis=0)  # mean over calibrators
        for run in runs:
            factors[(run, target)] = float(deviation[run])
    out = table.copy()
    if factors:
        keys = list(zip(out["run_id"].astype(str), out["target"].astype(str), strict=True))
        shift = np.array([factors.get(k, 0.0) for k in keys], dtype=float)
        out["n0"] = out["n0"] / np.exp2(shift)
    return Correction(
        "calibrator",
        out,
        factors,
        tuple(uncorrected),
        {t: s for t, s in found.items() if s},
    )


def ratio_matrix(table: pd.DataFrame) -> tuple[list[str], np.ndarray]:
    """Runs and the log2 between-run matrix ``L[r, c] = log2 f_c - log2 f_r`` (NaN: no overlap).

    Each entry is the mean, over every measurement the two runs share (same target and sample)
    and every pair of their replicate wells, of ``log2(value on c / value on r)``. The diagonal
    is 0 for a run that shares something with another run.
    """
    usable = table[_usable(table)]
    runs = sorted(map(str, table["run_id"].unique()))
    where = {run: i for i, run in enumerate(runs)}
    values: dict[tuple[str, str], dict[str, list[float]]] = {}
    logs = _log2(usable).to_numpy()
    keys = zip(
        usable["target"].astype(str),
        usable["sample"].astype(str),
        usable["run_id"].astype(str),
        strict=True,
    )
    for (target, sample, run), value in zip(keys, logs, strict=True):
        values.setdefault((target, sample), {}).setdefault(run, []).append(float(value))
    sums = np.zeros((len(runs), len(runs)))
    counts = np.zeros((len(runs), len(runs)))
    for _, by_run in sorted(values.items()):
        if len(by_run) < 2:
            continue
        for a, b in combinations(sorted(by_run), 2):
            va, vb = np.asarray(by_run[a]), np.asarray(by_run[b])
            diffs = (vb[None, :] - va[:, None]).ravel()  # log2(b / a) for every replicate pair
            i, j = where[a], where[b]
            sums[i, j] += diffs.sum()
            sums[j, i] -= diffs.sum()
            counts[i, j] += diffs.size
            counts[j, i] += diffs.size
    with np.errstate(invalid="ignore", divide="ignore"):
        matrix = np.where(counts > 0, sums / counts, np.nan)
    linked = (counts > 0).any(axis=1)
    matrix[np.diag_indices(len(runs))] = np.where(linked, 0.0, np.nan)
    return runs, matrix


def _fill(matrix: np.ndarray, row: int, col: int) -> None:
    """Eq. 3: estimate a missing ``L[row, col]`` through the other columns (in place)."""
    n = len(matrix)
    estimates = []
    for other in range(n):
        if other == col or np.isnan(matrix[row, other]):
            continue
        diffs = [
            matrix[i, other] - matrix[i, col]
            for i in range(n)
            if i != row and not np.isnan(matrix[i, other]) and not np.isnan(matrix[i, col])
        ]
        if diffs:
            estimates.append(matrix[row, other] - float(np.mean(diffs)))
    if estimates:
        value = float(np.mean(estimates))
        matrix[row, col] = value
        matrix[col, row] = -value


def plate_factors(table: pd.DataFrame) -> tuple[dict[str, float], tuple[str, ...]]:
    """Each run's log2 correction factor (Eqs. 2-4) and the runs that cannot be corrected."""
    runs, matrix = ratio_matrix(table)
    n = len(runs)
    if n < 2:
        return {}, ()
    for _ in range(GAP_PASSES):
        for row in range(n):
            for col in range(n):
                if row != col and np.isnan(matrix[row, col]):
                    _fill(matrix, row, col)
    factors, uncorrected = {}, []
    for c, run in enumerate(runs):
        column = matrix[:, c]
        known = column[~np.isnan(column)]
        if len(known) < 2:  # only the diagonal (or nothing): no link to another plate
            uncorrected.append(run)
            continue
        factors[run] = float(known.mean())
    return factors, tuple(uncorrected)


def factor_correct(table: pd.DataFrame) -> Correction:
    """Factor correction: every quantity on a plate divided by that plate's factor."""
    factors, uncorrected = plate_factors(table)
    out = table.copy()
    if factors:
        shift = out["run_id"].astype(str).map(factors).fillna(0.0).to_numpy(dtype=float)
        out["n0"] = out["n0"] / np.exp2(shift)
    return Correction(
        "factor",
        out,
        {(run, "*"): value for run, value in factors.items()},
        uncorrected,
    )


def correct(table: pd.DataFrame, option: str) -> Correction:
    """The per-well table under ``option`` (``none`` returns ``table`` itself)."""
    if option == "none":
        return Correction("none", table)
    if option == "calibrator":
        return calibrate(table)
    if option == "factor":
        return factor_correct(table)
    raise ValueError(f"unknown inter-run option {option!r} (known: {', '.join(OPTIONS)})")


def unavailable(table: pd.DataFrame) -> dict[str, str]:
    """Options that cannot change anything in this study -> why, in plain words."""
    split = split_targets(table)
    if not split:
        why = (
            "every gene's samples are on one plate, so a plate's offset is the same for every "
            "sample of a gene and cancels in every fold change"
        )
        return {"calibrator": why, "factor": why}
    out = {}
    if not any(calibrators(table).values()):
        out["calibrator"] = (
            "no gene split over plates has the same calibrator sample on each of its plates"
        )
    _, matrix = ratio_matrix(table)
    off_diagonal = ~np.eye(len(matrix), dtype=bool)
    if not np.isfinite(matrix[off_diagonal]).any():
        out["factor"] = (
            "no two plates share a measurement (the same gene in the same sample), so their "
            "factors cannot be compared"
        )
    return out


def summary(table: pd.DataFrame) -> dict[str, Any]:
    """Plain numbers for a proposal's evidence and a card: what is split, what can correct it."""
    split = split_targets(table)
    found = calibrators(table)
    runs, matrix = ratio_matrix(table)
    off = ~np.eye(len(matrix), dtype=bool)
    return {
        "n_runs": len(runs),
        "split_targets": {t: list(r) for t, r in split.items()},
        "n_split_targets": len(split),
        "calibrators": {t: list(s) for t, s in found.items() if s},
        "n_plate_pairs_sharing": int(np.isfinite(matrix[off]).sum() // 2),
    }


def apply_factors(table: pd.DataFrame, factors: Mapping[str, float]) -> pd.DataFrame:
    """``table`` with every quantity on a run divided by ``2**factors[run]`` (for what-ifs)."""
    out = table.copy()
    shift = out["run_id"].astype(str).map(dict(factors)).fillna(0.0).to_numpy(dtype=float)
    out["n0"] = out["n0"] / np.exp2(shift)
    return out


__all__ = [
    "AXIS",
    "OPTIONS",
    "PRIMARY",
    "Correction",
    "apply_factors",
    "calibrate",
    "calibrators",
    "correct",
    "factor_correct",
    "plate_factors",
    "ratio_matrix",
    "split_targets",
    "summary",
    "unavailable",
]
