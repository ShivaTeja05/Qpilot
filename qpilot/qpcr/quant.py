"""Relative quantities: each gene's starting amount divided by the control genes, on a log2 scale.

To compare a gene between samples, its starting quantity (``n0``) is divided by the mean of the
control ("reference") genes measured in the same sample; on the log2 scale that division is a
subtraction. This module builds a samples x genes matrix of ``log2(n0)`` and computes those
differences for any chosen set of control genes and either way of handling undetermined wells.

Only study samples (``sample_type == "unkn"``) are used. A unit that was not measured for some
gene (no well of that gene at all) is kept for the genes it has and left out of only the genes
it lacks: :func:`not_measured_cells` marks those values, and they are left out under every
option, never treated as undetermined (so never capped). A unit missing a *control* gene has
no normaliser, so it is left out of every gene; the study's facts say so. Otherwise a missing
value (NaN) means "the well never produced a usable signal" (undetermined), or that a person
excluded it. On a table where every unit has every gene (the demo) the matrix is what it
always was.

Technical replicates (several wells of one sample and gene) and biological units (several
samples of one animal or patient, from a study design) are averaged before anything else: per
sample and gene, the mean of ``log2(n0)`` over the wells that have a quantity (the geometric
mean of N0); per unit, the mean of its samples' means. With one sample per unit (the common
case, the demo) that is the mean over the unit's wells, exactly as before; with several, each
sample weighs the same whatever its number of wells (science review J10: two RNA preparations
of one animal are sub-replicates, and a preparation run in three wells must not count three
times one run in one). The unit is undetermined only when every replicate is. Technical
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
    """Return ``log2(n0)`` as a units x genes matrix over every study unit.

    Args:
        curves: The per-well table from :func:`qpilot.qpcr.curves.analyse_study`. An optional
            boolean column ``design_excluded`` marks wells a person excluded: they still show
            that the unit was measured, but their values are not used.
        units: Sample -> biological unit (samples not listed are their own unit). ``None``
            and one well per sample and gene keep the original one-row-per-sample matrix.

    Returns:
        A DataFrame indexed by unit (sorted) with one column per gene (sorted); NaN marks an
        undetermined, excluded or not measured value (:func:`left_out_cells` tells which of
        those are left out under every option).
    """
    unknown = curves[curves["sample_type"] == "unkn"]
    simple = units is None and not unknown.duplicated(["sample", "target"]).any()
    if simple and not _has_exclusions(unknown):
        measured = unknown.pivot(index="sample", columns="target", values="n0")
        matrix = np.log2(measured)
        return matrix.sort_index().sort_index(axis=1)
    return _aggregate(unknown, units)[0]


def not_measured_cells(
    curves: pd.DataFrame, units: Mapping[str, str] | None = None
) -> pd.DataFrame:
    """Units x genes, ``True`` where the unit has no study well of that gene at all.

    Same index and columns as :func:`log2_matrix`. Such a value is left out of that gene only,
    under every option; it is never undetermined (never capped).
    """
    unknown = curves[curves["sample_type"] == "unkn"]
    unit = unit_map(unknown["sample"], units).to_numpy()
    wells = pd.DataFrame({"unit": unit, "target": unknown["target"].to_numpy(), "one": 1})
    present = wells.groupby(["unit", "target"])["one"].sum().unstack("target")
    present = present.reindex(index=sorted(present.index), columns=sorted(present.columns))
    out = present.isna()
    out.index.name, out.columns.name = "sample", "target"
    return out


def left_out_cells(
    curves: pd.DataFrame, units: Mapping[str, str] | None = None
) -> pd.DataFrame | None:
    """Units x genes values left out under every option: excluded by a person or not measured.

    ``None`` when there are none (no exclusion column and every unit has every gene), so a
    complete table keeps the arithmetic it always had. Same index and columns as
    :func:`log2_matrix`.
    """
    missing = not_measured_cells(curves, units)
    unknown = curves[curves["sample_type"] == "unkn"]
    if EXCLUDED not in unknown.columns and not missing.to_numpy().any():
        return None
    if EXCLUDED not in unknown.columns:
        return missing
    excluded = excluded_cells(curves, units)
    return excluded | missing.reindex_like(excluded).fillna(True).astype(bool)


def not_measured(curves: pd.DataFrame, units: Mapping[str, str] | None = None) -> dict[str, list]:
    """Gene -> the units with no study well of it (sorted), for genes some unit lacks."""
    missing = not_measured_cells(curves, units)
    return {
        str(gene): sorted(str(u) for u in missing.index[missing[gene].to_numpy()])
        for gene in missing.columns
        if missing[gene].any()
    }


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
            "sample": rows["sample"].astype(str).to_numpy(),
            "target": rows["target"].to_numpy(),
            "log2": np.log2(rows["n0"].to_numpy(dtype=float)),
        }
    )


def unit_means(used: pd.DataFrame, column: str = "log2") -> pd.Series:
    """Per ``(unit, target)``: the mean over the unit's samples of each sample's mean ``column``.

    ``used`` has ``unit``, ``sample``, ``target`` and ``column``. A unit with one sample gets the
    plain mean of its wells (the same number, bit for bit, as one flat mean).
    """
    per_sample = used.groupby(["unit", "sample", "target"])[column].mean()
    return per_sample.groupby(level=["unit", "target"]).mean()


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
    all_excluded = wells.groupby(["unit", "target"])["excluded"].all().unstack("target")
    used = _usable(unknown, units)
    means = unit_means(used).unstack("target")
    index = present.index.sort_values()
    columns = present.columns.sort_values()
    values = means.reindex(index=index, columns=columns)
    excluded = all_excluded.reindex(index=index, columns=columns)
    excluded = excluded.astype("boolean").fillna(False).astype(bool)
    values.index.name, values.columns.name = "sample", "target"
    excluded.index.name, excluded.columns.name = "sample", "target"
    return values.astype(float), excluded


def samples_common(matrix: pd.DataFrame) -> list[str]:
    """The study units (the matrix's rows)."""
    return list(matrix.index)


def relative(
    matrix: pd.DataFrame,
    target: str,
    refs: Sequence[str],
    undetermined: Undetermined = "drop",
    left_out: pd.DataFrame | None = None,
) -> pd.Series:
    """Return ``log2(target) - mean(log2(refs))`` per sample.

    Samples missing any chosen control gene are skipped. An undetermined target well is skipped
    with ``"drop"``, or set to the lowest value detected for that gene with ``"cap"`` (the curve
    never rose, so the amount is treated as "at most the smallest one seen"). A value marked in
    ``left_out`` (:func:`left_out_cells`: excluded or not measured) is skipped under both.

    Args:
        matrix: From :func:`log2_matrix`.
        target: The gene to normalise.
        refs: The control genes to divide by (one or more).
        undetermined: ``"drop"`` or ``"cap"``.
        left_out: Units x genes, ``True`` for values left out under every option.

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
    if left_out is not None and target in left_out.columns:
        out = left_out[target].reindex(matrix.index).astype("boolean").fillna(False)
        keep = keep & ~out.astype(bool)
    result = values[keep] - reference[keep].mean(axis=1)
    result.name = target
    return result
