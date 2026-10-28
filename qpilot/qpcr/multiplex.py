"""Multiplex wells: several dyes, one target each, measured in the same reaction.

A multiplex well holds one curve per dye (a TaqMan duplex: the gene of interest in FAM, the
reference gene in VIC/HEX; a 4-plex with an internal positive control in Cy5). The per-well
table (:func:`qpilot.qpcr.curves.analyse_study`) has one row per curve, so such a well has one
row per target under one ``run_id/well`` key. LinRegPCR analyses each dye of a multiplex plate
on its own (:func:`qpilot.qpcr.curves.channels`): every curve gets its own baseline, efficiency,
Cq, N0 and amplification call, as on a plate of that dye alone.

This module says which wells are multiplex, which target is an **internal positive control**
(IPC: a control template spiked at the same amount into every reaction, so its Cq should be the
same in every well; a much later IPC in a sample's well suggests something in the sample slowed
the reaction, an inhibitor), and where pairing a gene with the reference of the *same* well would
give another number than qPilot's relative quantity.

**Relative quantities in multiplex wells.** qPilot averages each gene's log2 N0 over a unit's
wells and subtracts the control genes' mean over the unit's wells (:mod:`qpilot.qpcr.quant`).
When the gene and its reference are measured in the same wells and every one of those wells has
both values, that is exactly the mean of the per-well differences (same-well pairing, which
cancels the pipetting error in the template amount, because both dyes read the same aliquot).
The two differ only where one dye of a well has no value while the other has one;
:func:`pairing_gaps` counts those places, and a person who wants them paired leaves the whole
well out (the Run Gate's options do: in a multiplex well every curve is left out together).
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence

import pandas as pd

WELL = ("run_id", "well")

#: Words that name an internal positive (amplification) control. Matched on the target name split
#: into words, case ignored: ``IPC``, ``IAC``, ``Exo IPC``, ``IPC2``, ``internal positive
#: control``, ``internal amplification control``.
_CONTROL_WORD = re.compile(r"^(ipc|iac|exoipc)\d*$")
_CONTROL_PHRASE = re.compile(r"\binternal (positive|amplification) control\b")


def is_internal_control_name(name: str) -> bool:
    """True when a target's name says it is an internal positive control (IPC, IAC)."""
    text = str(name).lower()
    words = [w for w in re.split(r"[^a-z0-9]+", text) if w]
    if any(_CONTROL_WORD.match(w) for w in words):
        return True
    if "".join(words[:2]) == "exoipc":
        return True
    return bool(_CONTROL_PHRASE.search(" ".join(words)))


def well_keys(table: pd.DataFrame) -> pd.Series:
    """``run_id/well`` for every row."""
    return table["run_id"].astype(str) + "/" + table["well"].astype(str)


def shared_wells(table: pd.DataFrame) -> pd.Series:
    """For every row: does its well hold another target's curve too (a multiplex well)?"""
    if table.empty:
        return pd.Series(False, index=table.index, dtype=bool)
    counts = table.groupby(list(WELL))["target"].transform("nunique")
    return (counts > 1).astype(bool)


def is_multiplex(table: pd.DataFrame) -> bool:
    """True when at least one well holds more than one target's curve."""
    return bool(shared_wells(table).any())


def multiplex_keys(table: pd.DataFrame) -> frozenset[str]:
    """The ``run_id/well`` keys of the multiplex wells."""
    return frozenset(well_keys(table[shared_wells(table)]))


def internal_controls(table: pd.DataFrame) -> list[str]:
    """Targets that are internal positive controls: so named, and measured in multiplex wells.

    The name alone is not enough: an IPC shares its wells with the targets it checks. In table
    order.
    """
    shared = shared_wells(table)
    out: list[str] = []
    for target in dict.fromkeys(table["target"].astype(str)):
        rows = table["target"].astype(str) == target
        if is_internal_control_name(target) and bool(shared[rows].any()):
            out.append(target)
    return out


def partners(table: pd.DataFrame, target: str) -> pd.DataFrame:
    """The other targets' curves in the wells where ``target`` is measured."""
    mine = set(well_keys(table[table["target"] == target]))
    keys = well_keys(table)
    return table[keys.isin(mine) & (table["target"] != target)]


def dyes_by_well(table: pd.DataFrame) -> dict[str, list[str]]:
    """``run_id/well`` -> its targets in table order, for the multiplex wells only."""
    rows = table[shared_wells(table)]
    out: dict[str, list[str]] = {}
    for key, target in zip(well_keys(rows), rows["target"].astype(str), strict=True):
        out.setdefault(key, []).append(target)
    return out


def pairing_gaps(
    curves: pd.DataFrame,
    refs: Sequence[str],
    units: Mapping[str, str] | None = None,
    excluded: Collection[str] = (),
) -> pd.DataFrame:
    """Where pairing a gene with the reference of the same well would differ from qPilot's value.

    qPilot's value for a unit is the gene's mean log2 N0 over its wells with a value minus the
    reference's mean over its wells with a value; pairing takes the mean of the differences over
    the wells where both have one. The two are the same number unless the two sets of wells
    differ while each has at least one well. One row per study unit, gene and control gene
    where they do (``unit``, ``target``, ``ref``, ``n_wells``: the wells the two share,
    ``n_unpaired``: those where only one of the two has a value). Empty: qPilot's relative
    quantity is the mean of the same-well differences exactly. A value is a quantity that was
    not left out.

    Args:
        curves: The per-well table (study wells are read: ``sample_type == "unkn"``).
        refs: The control genes.
        units: Sample -> biological unit (samples not listed are their own unit).
        excluded: Well keys a person left out.
    """
    columns = ["unit", "target", "ref", "n_wells", "n_unpaired"]
    study = curves[curves["sample_type"] == "unkn"]
    if study.empty or not refs:
        return pd.DataFrame(columns=columns)
    keys = well_keys(study)
    valued = study["n0"].notna() & ~keys.isin(set(excluded))
    if "design_excluded" in study.columns:
        valued &= ~study["design_excluded"].astype(bool)
    frame = pd.DataFrame(
        {
            "key": keys.to_numpy(),
            "unit": study["sample"].map(lambda s: (units or {}).get(s, s)).to_numpy(),
            "target": study["target"].astype(str).to_numpy(),
            "valued": valued.to_numpy(),
        }
    )
    has = frame.pivot_table(index="key", columns="target", values="valued", aggfunc="max")
    unit_of = frame.drop_duplicates("key").set_index("key")["unit"]
    rows: list[dict[str, object]] = []
    for ref in refs:
        if ref not in has.columns:
            continue
        for target in has.columns:
            if target == ref or target in refs:
                continue
            both = has[[target, ref]].dropna()
            if both.empty:
                continue
            pair = both.astype(bool)
            for unit, block in pair.groupby(unit_of.reindex(both.index)):
                odd = block[target] != block[ref]
                if odd.any() and block[target].any() and block[ref].any():
                    rows.append(
                        {
                            "unit": str(unit),
                            "target": str(target),
                            "ref": str(ref),
                            "n_wells": int(len(block)),
                            "n_unpaired": int(odd.sum()),
                        }
                    )
    return pd.DataFrame(rows, columns=columns)


__all__ = [
    "dyes_by_well",
    "internal_controls",
    "is_internal_control_name",
    "is_multiplex",
    "multiplex_keys",
    "pairing_gaps",
    "partners",
    "shared_wells",
]
