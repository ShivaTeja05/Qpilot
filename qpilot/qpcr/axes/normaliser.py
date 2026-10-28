"""The normaliser axis: what each gene is divided by before the groups are compared.

The legacy ``refs`` axis varies which subset of the chosen reference genes is averaged. This
opt-in axis asks a different question a reviewer asks: would the conclusions change with
another normalisation *strategy*? Its options (ids are stable):

* ``planned`` (primary): the reference genes as chosen for this study (the ``refs`` axis and
  its card, unchanged);
* ``normfinder_pair``: NormFinder's best pair of the candidates (:mod:`qpilot.qpcr.normfinder`,
  with the study's groups);
* ``genorm_pair``: geNorm's best pair (its last two genes, :mod:`qpilot.qpcr.refgenes`);
* ``global_mean``: the mean of every gene measured in the unit (Mestdagh et al., Genome Biol
  2009; 10:R64), with each gene weighted equally (D'haene et al., Methods Mol Biol 2012;
  822:261-272): each gene's ``log2 N0`` is first centred on its own mean over the units, then
  a unit's normaliser is the mean of its genes that have a value. When every gene has a value in
  every unit this is the plain mean (up to a constant that cancels in every fold change).

An option that would repeat another (a best pair that is the set in use, geNorm's pair equal to
NormFinder's) or that the study cannot support is not offered and the reason is reported.
Mestdagh et al. say the global mean "is only valid if a large number of" genes are profiled (they
profiled 366 to 448) and give no number; qPilot offers it from :data:`GLOBAL_MEAN_MIN_GENES`
genes (its own default, not a published threshold) and says so in plain words below that.

Choosing an option never changes which reference genes a study uses: the analysis in use stays
``planned`` until a person decides the card this axis raises. Deterministic.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from qpilot.qpcr.axes import get_axis
from qpilot.qpcr.contrast import welch
from qpilot.qpcr.normfinder import NormFinderError, NormFinderResult, agreement, normfinder
from qpilot.schemas import GenormResult

AXIS = "normaliser"
PRIMARY = "planned"
OPTIONS: tuple[str, ...] = tuple(o.id for o in get_axis(AXIS).catalogue)
GLOBAL_MEAN = "global_mean"
PAIRS = ("normfinder_pair", "genorm_pair")
#: qPilot's own default: the global mean is offered from this many genes with values.
GLOBAL_MEAN_MIN_GENES = 50
GLOBAL_MEAN_SOURCE = (
    "Mestdagh et al., Genome Biol 2009; 10:R64 (global mean normalisation); D'haene et al., "
    "Methods Mol Biol 2012; 822:261-272 (each gene weighted equally)"
)
GLOBAL_MEAN_THRESHOLD_NOTE = (
    f"qPilot offers the global mean from {GLOBAL_MEAN_MIN_GENES} genes. This is qPilot's own "
    "default, not a published number: Mestdagh et al. (2009) say the global mean is only valid "
    "when a large number of genes is profiled (they profiled 366 to 448) and give no minimum."
)
GLOBAL_MEAN_PANEL_NOTE = (
    "The global mean assumes the genes measured were not chosen for this comparison: a panel of "
    "genes picked because they differ between the groups moves its own mean, and every fold "
    "change with it."
)
METHOD_CARD_PATH = "methods/normfinder.md"


def global_mean_genes(matrix: pd.DataFrame) -> tuple[str, ...]:
    """Genes that can enter the global mean: two or more units with a value (matrix order)."""
    counts = matrix.notna().sum(axis=0)
    return tuple(str(g) for g in matrix.columns if counts[g] >= 2)


def global_mean(matrix: pd.DataFrame, genes: Sequence[str]) -> pd.Series:
    """Per unit, the mean of its genes' centred ``log2 N0`` (each gene weighted equally).

    A unit with no value of any of ``genes`` gets NaN (no normaliser, like a unit missing a
    reference gene).
    """
    block = matrix[list(genes)].astype(float)
    centred = block - block.mean(axis=0)
    return centred.mean(axis=1, skipna=True).where(block.notna().any(axis=1))


@dataclass(frozen=True)
class NormaliserPlan:
    """The normaliser axis on one study: what each option divides by, and what does not apply.

    ``refs`` maps each pair option to its genes (candidate order); ``global_genes`` lists the
    genes of the global mean; ``unavailable`` gives every option that does not apply (asked for
    or not) with the reason; ``options`` are the offered options that apply, primary first.
    """

    options: tuple[str, ...]
    refs: dict[str, tuple[str, ...]]
    global_genes: tuple[str, ...]
    unavailable: dict[str, str]
    normfinder: NormFinderResult | None
    genorm_pair: tuple[str, str] | None
    words: str
    evidence: dict[str, Any] = field(default_factory=dict)


def _ordered(genes: Collection[str], candidates: Sequence[str]) -> tuple[str, ...]:
    return tuple(g for g in candidates if g in set(genes))


def _words(genes: Sequence[str]) -> str:
    return " and ".join(genes) if len(genes) <= 2 else ", ".join(genes)


def plan(
    matrix: pd.DataFrame,
    candidates: Sequence[str],
    stability: GenormResult,
    primary_refs: Sequence[str],
    groups: Mapping[str, str | None] | None,
    offered: Sequence[str] = OPTIONS,
    high: Collection[str] = (),
    rest: Collection[str] = (),
) -> NormaliserPlan:
    """What the normaliser axis offers on this study, and why an option is left out.

    Args:
        matrix: Units x genes ``log2 N0`` under the primary options.
        candidates: The study's candidate reference genes.
        stability: The study's geNorm result for ``candidates``.
        primary_refs: The reference genes the analysis in use divides by.
        groups: Unit -> group, for NormFinder's intergroup variation.
        offered: The options asked for, primary first.
        high: The primary comparison's first group (for the global mean's group check).
        rest: Its second group.
    """
    candidates = tuple(candidates)
    primary = set(primary_refs)
    unavailable: dict[str, str] = {}
    refs: dict[str, tuple[str, ...]] = {}
    found: NormFinderResult | None = None
    try:
        found = normfinder(matrix, candidates, groups)
    except NormFinderError as err:
        unavailable["normfinder_pair"] = str(err)
    g_pair: tuple[str, str] | None = None
    if len(candidates) >= 3 and len(stability.order) >= 2:
        g_pair = (stability.order[0], stability.order[1])
    else:
        unavailable["genorm_pair"] = (
            f"geNorm needs at least three candidate reference genes to rank them, not "
            f"{len(candidates)}"
        )
    if found is not None:
        pair = _ordered(found.best_pair, candidates)
        if set(pair) == primary:
            unavailable["normfinder_pair"] = (
                f"NormFinder's best pair ({_words(pair)}) is the set the analysis already uses"
            )
        else:
            refs["normfinder_pair"] = pair
    if g_pair is not None:
        pair = _ordered(g_pair, candidates)
        if set(pair) == primary:
            unavailable["genorm_pair"] = (
                f"geNorm's best pair ({_words(pair)}) is the set the analysis already uses"
            )
        elif found is not None and set(pair) == set(found.best_pair):
            unavailable["genorm_pair"] = (
                f"geNorm's best pair ({_words(pair)}) is NormFinder's best pair too"
            )
        else:
            refs["genorm_pair"] = pair
    genes = global_mean_genes(matrix)
    if len(genes) < GLOBAL_MEAN_MIN_GENES:
        unavailable[GLOBAL_MEAN] = (
            f"only {len(genes)} genes are measured; the global mean needs a large set of genes "
            f"(qPilot asks for at least {GLOBAL_MEAN_MIN_GENES})"
        )
    words = agreement(stability.order, found).words if found and g_pair else ""
    evidence: dict[str, Any] = {
        "normfinder": found.as_dict() if found is not None else None,
        "genorm_pair": list(g_pair) if g_pair else None,
        "agreement": words,
        "refs": {k: list(v) for k, v in refs.items()},
        "planned": list(_ordered(primary, candidates)),
        "global_mean": {
            "n_genes": len(genes),
            "min_genes": GLOBAL_MEAN_MIN_GENES,
            "threshold_note": GLOBAL_MEAN_THRESHOLD_NOTE,
            "panel_note": GLOBAL_MEAN_PANEL_NOTE,
            "source": GLOBAL_MEAN_SOURCE,
            "min_genes_per_unit": int(matrix[list(genes)].notna().sum(axis=1).min())
            if genes
            else 0,
            "group_shift": _global_shift(matrix, genes, primary_refs, high, rest),
        },
    }
    kept = tuple(o for o in offered if o == PRIMARY or o not in unavailable)
    return NormaliserPlan(
        options=kept,
        refs=refs,
        global_genes=genes,
        unavailable=unavailable,
        normfinder=found,
        genorm_pair=g_pair,
        words=words,
        evidence=evidence,
    )


def _global_shift(
    matrix: pd.DataFrame,
    genes: Sequence[str],
    refs: Sequence[str],
    high: Collection[str],
    rest: Collection[str],
) -> dict[str, float] | None:
    """Does the global mean move between the groups, relative to the reference genes in use?

    The log2 shift (first group minus second) of ``global mean - mean(reference genes)``, with
    Welch's p; ``None`` without two units with a value on each side.
    """
    if not genes or not refs or not high or not rest:
        return None
    ratio = (global_mean(matrix, genes) - matrix[list(refs)].mean(axis=1)).dropna()
    a = ratio[ratio.index.isin(set(high))].to_numpy(dtype=float)
    b = ratio[ratio.index.isin(set(rest))].to_numpy(dtype=float)
    if len(a) < 2 or len(b) < 2:
        return None
    w = welch(a, b)
    return {"log2_shift": float(w.diff), "fold": float(2**w.diff), "p": float(w.p)}


def normaliser_values(
    option: str,
    planned_refs: Sequence[str],
    block: pd.DataFrame,
    plan_: NormaliserPlan,
) -> np.ndarray:
    """Units x columns whose row mean is the option's normaliser, from a cell's matrix ``block``.

    ``block`` holds every gene of the cell's matrix (candidates and items). The planned option
    and the pairs return their genes' columns; the global mean returns one column.
    """
    if option == PRIMARY:
        return block[list(planned_refs)].to_numpy(dtype=float)
    if option in plan_.refs:
        return block[list(plan_.refs[option])].to_numpy(dtype=float)
    if option == GLOBAL_MEAN:
        return global_mean(block, plan_.global_genes).to_numpy(dtype=float)[:, None]
    raise ValueError(f"the normaliser option {option!r} does not apply to this study")


class NotTraceable(ValueError):
    """A cell normalised to the global mean: no reference wells to trace."""


def as_refs_cell(cell: Mapping[str, Any], notes: Mapping[str, Any] | None) -> dict[str, Any]:
    """The cell with a best-pair normaliser written as its control genes (the same numbers).

    A best pair is one of the ``refs`` options, so ``{"refs": pair}`` with the planned
    normaliser evaluates to exactly what the normaliser option does; tools that follow the
    reference wells (Trace) use that. The planned option returns the cell as it is.

    Raises:
        NotTraceable: The cell divides by the global mean.
    """
    out = dict(cell)
    option = out.pop(AXIS, PRIMARY)
    if option == PRIMARY:
        return dict(cell)
    pairs = (notes or {}).get("refs") or {}
    if option in pairs:
        out["refs"] = tuple(pairs[option])
        return out
    raise NotTraceable(
        "this analysis divides each gene by the global mean of every gene, not by reference "
        "genes, so there are no reference wells to follow"
    )


__all__ = [
    "NotTraceable",
    "as_refs_cell",
    "AXIS",
    "GLOBAL_MEAN",
    "GLOBAL_MEAN_MIN_GENES",
    "GLOBAL_MEAN_SOURCE",
    "OPTIONS",
    "PRIMARY",
    "NormaliserPlan",
    "global_mean",
    "global_mean_genes",
    "normaliser_values",
    "plan",
]
