"""Relative quantities: each gene's starting amount divided by the control genes, on a log2 scale.

To compare a gene between samples, its starting quantity (``n0``) is divided by the mean of the
control ("reference") genes measured in the same sample; on the log2 scale that division is a
subtraction. This module builds a samples x genes matrix of ``log2(n0)`` and computes those
differences for any chosen set of control genes and either way of handling undetermined wells.

Only study samples (``sample_type == "unkn"``) are used, and only samples measured for *every*
gene are kept, as in the validation oracle. After that restriction a missing value (NaN) always
means "the well never produced a usable signal" (undetermined), or that a person excluded it.

Technical replicates (several wells of one sample and gene) and biological units (several
samples of one animal or patient, from a study design) are averaged before anything else: per
unit and gene, the mean of ``log2(n0)`` over the wells that have a quantity, which is the
geometric mean of N0. The unit is undetermined only when every replicate is. Technical
replicates are never counted as n; their spread is kept by :func:`replicate_sd`. A table with
one well per sample and gene, and no units, gives exactly the matrix it always did.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

import numpy as np
import pandas as pd

Undetermined = Literal["drop", "cap"]
EXCLUDED = "design_excluded"  # optional boolean column: a person excluded the well


class QuantError(Exception):
    """The per-well table cannot be turned into a samples x genes matrix."""


def log2_matrix(curves: pd.DataFrame, units: Mapping[str, str] | None = None) -> pd.DataFrame:
    """Return ``log2(n0)`` as a units x genes matrix over units measured for every gene.

    Args:
        curves: The per-well table from :func:`qpilot.qpcr.curves.analyse_study`. An optional
            boolean column ``design_excluded`` marks wells a person excluded: they still show
            that the unit was measured, but their values are not used.
        units: Sample -> biological unit (samples not listed are their own unit). ``None``
            and one well per sample and gene keep the original one-row-per-sample matrix.

    Returns:
        A DataFrame indexed by unit (sorted) with one column per gene (sorted); NaN marks an
        undetermined (or excluded) value.
    """
    unknown = curves[curves["sample_type"] == "unkn"]
    simple = units is None and not unknown.duplicated(["sample", "target"]).any()
    if simple and not _has_exclusions(unknown):
        measured = unknown.pivot(index="sample", columns="target", values="n0")
        present = unknown.assign(one=1).pivot(index="sample", columns="target", values="one")
        complete = present.notna().all(axis=1)
        matrix = np.log2(measured.loc[complete])
        return matrix.sort_index().sort_index(axis=1)
    return _aggregate(unknown, units)[0]


def excluded_cells(curves: pd.DataFrame, units: Mapping[str, str] | None = None) -> pd.DataFrame:
    """Units x genes, ``True`` where every well of that unit and gene was excluded by a person.

    Such a value is left out under every option; it is never treated as undetermined (and so is
    never capped). Same index and columns as :func:`log2_matrix`.
    """
    unknown = curves[curves["sample_type"] == "unkn"]
    return _aggregate(unknown, units)[1]


def replicate_sd(curves: pd.DataFrame, units: Mapping[str, str] | None = None) -> pd.DataFrame:
    """SD (n - 1) of ``log2(n0)`` over the technical replicates of each unit and gene.

    Over the wells that have a quantity (and were not excluded); NaN where fewer than two do.
    Same index and columns as :func:`log2_matrix`. Kept for the replicate-tolerance check; it
    never enters a test statistic.
    """
    unknown = curves[curves["sample_type"] == "unkn"]
    matrix = _aggregate(unknown, units)[0]
    used = _usable(unknown, units)
    sd = used.groupby(["unit", "target"])["log2"].std(ddof=1).unstack("target")
    return sd.reindex(index=matrix.index, columns=matrix.columns)


def unit_map(samples: Sequence[str], units: Mapping[str, str] | None) -> pd.Series:
    """Sample -> biological unit for these sample names (by default a sample is its own unit)."""
    names = pd.Series(list(samples), index=list(samples), dtype=object)
    if not units:
        return names
    return names.map(lambda s: units.get(s, s))


def _has_exclusions(table: pd.DataFrame) -> bool:
    return EXCLUDED in table.columns and bool(table[EXCLUDED].any())


def _usable(unknown: pd.DataFrame, units: Mapping[str, str] | None) -> pd.DataFrame:
    """Rows that carry a value: a quantity, not excluded; with their unit and log2(n0)."""
    keep = unknown["n0"].notna()
    if EXCLUDED in unknown.columns:
        keep &= ~unknown[EXCLUDED].astype(bool)
    rows = unknown.loc[keep, ["sample", "target", "n0"]]
    return pd.DataFrame(
        {
            "unit": unit_map(rows["sample"], units).to_numpy(),
            "target": rows["target"].to_numpy(),
            "log2": np.log2(rows["n0"].to_numpy(dtype=float)),
        }
    )


def _aggregate(
    unknown: pd.DataFrame, units: Mapping[str, str] | None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(values, excluded): per unit and gene, the mean log2(n0) and the all-excluded flag."""
    unit = unit_map(unknown["sample"], units).to_numpy()
    wells = pd.DataFrame({"unit": unit, "target": unknown["target"].to_numpy()})
    if EXCLUDED in unknown.columns:
        wells["excluded"] = unknown[EXCLUDED].astype(bool).to_numpy()
    else:
        wells["excluded"] = False
    present = wells.groupby(["unit", "target"]).size().unstack("target")
    complete = present.notna().all(axis=1)
    all_excluded = wells.groupby(["unit", "target"])["excluded"].all().unstack("target")
    used = _usable(unknown, units)
    means = used.groupby(["unit", "target"])["log2"].mean().unstack("target")
    index = present.index[complete].sort_values()
    columns = present.columns.sort_values()
    values = means.reindex(index=index, columns=columns)
    excluded = all_excluded.reindex(index=index, columns=columns)
    excluded = excluded.astype("boolean").fillna(False).astype(bool)
    values.index.name, values.columns.name = "sample", "target"
    excluded.index.name, excluded.columns.name = "sample", "target"
    return values.astype(float), excluded


def samples_common(matrix: pd.DataFrame) -> list[str]:
    """Samples measured for every gene (the matrix's rows)."""
    return list(matrix.index)


def relative(
    matrix: pd.DataFrame,
    target: str,
    refs: Sequence[str],
    undetermined: Undetermined = "drop",
) -> pd.Series:
    """Return ``log2(target) - mean(log2(refs))`` per sample.

    Samples missing any chosen control gene are skipped. An undetermined target well is skipped
    with ``"drop"``, or set to the lowest value detected for that gene with ``"cap"`` (the curve
    never rose, so the amount is treated as "at most the smallest one seen").

    Args:
        matrix: From :func:`log2_matrix`.
        target: The gene to normalise.
        refs: The control genes to divide by (one or more).
        undetermined: ``"drop"`` or ``"cap"``.

    Returns:
        A Series indexed by sample.
    """
    if not refs:
        raise ValueError("at least one control gene is required")
    reference = matrix[list(refs)]
    refs_ok = reference.notna().all(axis=1)
    values = matrix[target]
    if undetermined == "drop":
        keep = refs_ok & values.notna()
    elif undetermined == "cap":
        values = values.fillna(values.min())
        keep = refs_ok
    else:
        raise ValueError(f"undetermined must be 'drop' or 'cap', not {undetermined!r}")
    result = values[keep] - reference[keep].mean(axis=1)
    result.name = target
    return result
