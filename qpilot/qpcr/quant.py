"""Relative quantities: each gene's starting amount divided by the control genes, on a log2 scale.

To compare a gene between samples, its starting quantity (``n0``) is divided by the mean of the
control ("reference") genes measured in the same sample; on the log2 scale that division is a
subtraction. This module builds a samples x genes matrix of ``log2(n0)`` and computes those
differences for any chosen set of control genes and either way of handling undetermined wells.

Only study samples (``sample_type == "unkn"``) are used, and only samples measured for *every*
gene are kept, as in the validation oracle. After that restriction a missing value (NaN) always
means "the well never produced a usable signal" (undetermined).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

import numpy as np
import pandas as pd

Undetermined = Literal["drop", "cap"]


class QuantError(Exception):
    """The per-well table cannot be turned into a samples x genes matrix."""


def log2_matrix(curves: pd.DataFrame) -> pd.DataFrame:
    """Return ``log2(n0)`` as a samples x genes matrix over samples measured for every gene.

    Args:
        curves: The per-well table from :func:`qpilot.qpcr.curves.analyse_study`.

    Returns:
        A DataFrame indexed by sample (sorted) with one column per gene (sorted); NaN marks an
        undetermined well.

    Raises:
        QuantError: A sample was measured more than once for the same gene (technical
            replicates are not supported yet).
    """
    unknown = curves[curves["sample_type"] == "unkn"]
    duplicated = unknown.duplicated(["sample", "target"])
    if duplicated.any():
        first = unknown[duplicated].iloc[0]
        raise QuantError(
            f"sample {first['sample']!r} has more than one well for {first['target']!r}; "
            "technical replicates are not supported yet"
        )
    measured = unknown.pivot(index="sample", columns="target", values="n0")
    present = unknown.assign(one=1).pivot(index="sample", columns="target", values="one")
    complete = present.notna().all(axis=1)
    matrix = np.log2(measured.loc[complete])
    return matrix.sort_index().sort_index(axis=1)


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
