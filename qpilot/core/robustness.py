"""The robustness grid: rerun an analysis under every combination of reasonable choices.

Domain-agnostic. It works on any object that satisfies ``qpilot.schemas.DecisionSpace``
(``dimensions``, ``primary``, ``items``, ``evaluate(cell)``, ``conclude(result)``) and never
imports a domain plugin. For qPCR the dimensions are the reference-gene subset, the group
cut-off and the empty-well rule (31 x 3 x 2 = 186 cells); the items are genes.

Definitions (they match the oracle, ``planning/verification/verify.py``):

- **holds**: share of all cells whose conclusion equals the primary cell's conclusion.
- **impact of a dimension**: vary that dimension only, others held at the primary option;
  ``flips`` is whether any of those cells changes the conclusion and ``max_delta_log2fc`` the
  largest absolute change in log2 fold change.
- **min_flip_changes**: the fewest dimensions that must change, from the primary cell, to reach
  a cell with a different conclusion (0 when no cell changes it).
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from typing import Any

import pandas as pd

from qpilot.schemas import DecisionSpace, GeneRobustness

IDX_SUFFIX = "__idx"
RESULT_COLUMNS = ["item", "log2fc", "fc", "p", "conclusion"]


def cells(space: DecisionSpace) -> Iterator[dict[str, Any]]:
    """Yield every combination of options, one value per dimension, in a fixed order."""
    names = list(space.dimensions)
    for combo in itertools.product(*(space.dimensions[n] for n in names)):
        yield dict(zip(names, combo, strict=True))


def n_cells(space: DecisionSpace) -> int:
    """Number of cells in the grid (product of the number of options per dimension)."""
    total = 1
    for options in space.dimensions.values():
        total *= len(options)
    return total


def _primary_index(space: DecisionSpace) -> dict[str, int]:
    out = {}
    for name, options in space.dimensions.items():
        if space.primary[name] not in options:
            raise ValueError(f"primary option for {name!r} is not one of its options")
        out[name] = options.index(space.primary[name])
    return out


def run_grid(space: DecisionSpace) -> pd.DataFrame:
    """Evaluate every cell and return one row per cell x item.

    Columns: one per dimension (the option value), one ``<dimension>__idx`` per dimension (the
    option's position, used for comparisons because option values may be tuples), then ``item``,
    ``log2fc``, ``fc``, ``p`` and ``conclusion`` (from ``space.conclude``).
    """
    names = list(space.dimensions)
    rows: list[dict[str, Any]] = []
    index_combos = itertools.product(*(range(len(space.dimensions[n])) for n in names))
    for idx_combo in index_combos:
        cell = {n: space.dimensions[n][i] for n, i in zip(names, idx_combo, strict=True)}
        results = space.evaluate(cell)
        for item in space.items:
            res = results[item]
            row: dict[str, Any] = dict(cell)
            row.update({f"{n}{IDX_SUFFIX}": i for n, i in zip(names, idx_combo, strict=True)})
            row.update(
                item=item,
                log2fc=res.log2fc,
                fc=res.fc,
                p=res.p,
                conclusion=space.conclude(res),
            )
            rows.append(row)
    columns = names + [f"{n}{IDX_SUFFIX}" for n in names] + RESULT_COLUMNS
    return pd.DataFrame(rows, columns=columns)


def _dimension_names(grid: pd.DataFrame) -> list[str]:
    return [c[: -len(IDX_SUFFIX)] for c in grid.columns if c.endswith(IDX_SUFFIX)]


def _item_rows(grid: pd.DataFrame, item: str) -> pd.DataFrame:
    rows = grid[grid["item"] == item]
    if rows.empty:
        raise KeyError(f"item not in grid: {item!r}")
    return rows


def _primary_mask(rows: pd.DataFrame, primary_idx: dict[str, int], skip: str | None = None):
    mask = pd.Series(True, index=rows.index)
    for name, idx in primary_idx.items():
        if name != skip:
            mask &= rows[f"{name}{IDX_SUFFIX}"] == idx
    return mask


def primary_row(grid: pd.DataFrame, space: DecisionSpace, item: str) -> pd.Series:
    """The grid row for ``item`` under the primary choices."""
    rows = _item_rows(grid, item)
    hit = rows[_primary_mask(rows, _primary_index(space))]
    if len(hit) != 1:
        raise ValueError(f"expected one primary row for {item!r}, found {len(hit)}")
    return hit.iloc[0]


def holds_fraction(grid: pd.DataFrame, item: str, primary_conclusion: str) -> float:
    """Share of cells in which ``item`` reaches ``primary_conclusion``."""
    rows = _item_rows(grid, item)
    return float((rows["conclusion"] == primary_conclusion).mean())


def impact_per_dimension(
    grid: pd.DataFrame, space: DecisionSpace, item: str
) -> dict[str, dict[str, Any]]:
    """For each dimension, vary it alone and report ``flips`` and ``max_delta_log2fc``."""
    rows = _item_rows(grid, item)
    primary_idx = _primary_index(space)
    prim = primary_row(grid, space, item)
    out: dict[str, dict[str, Any]] = {}
    for name in space.dimensions:
        sub = rows[_primary_mask(rows, primary_idx, skip=name)]
        out[name] = {
            "flips": bool((sub["conclusion"] != prim["conclusion"]).any()),
            "max_delta_log2fc": float((sub["log2fc"] - prim["log2fc"]).abs().max()),
        }
    return out


def min_flip_changes(grid: pd.DataFrame, space: DecisionSpace, item: str) -> int:
    """Fewest dimensions changed from the primary cell that flip the conclusion; 0 if none do."""
    rows = _item_rows(grid, item)
    primary_idx = _primary_index(space)
    prim = primary_row(grid, space, item)
    flipped = rows[rows["conclusion"] != prim["conclusion"]]
    if flipped.empty:
        return 0
    distance = sum(
        (flipped[f"{name}{IDX_SUFFIX}"] != idx).astype(int) for name, idx in primary_idx.items()
    )
    return int(distance.min())


def flipped_by(summaries: dict[str, GeneRobustness], dimension: str) -> list[str]:
    """Items whose conclusion changes when only ``dimension`` changes."""
    return sorted(i for i, s in summaries.items() if s.impact[dimension]["flips"])


def summary(grid: pd.DataFrame, space: DecisionSpace) -> dict[str, GeneRobustness]:
    """One ``GeneRobustness`` per item: primary conclusion and fold change, holds, impact."""
    total = n_cells(space)
    out: dict[str, GeneRobustness] = {}
    for item in space.items:
        prim = primary_row(grid, space, item)
        out[item] = GeneRobustness(
            target=item,
            conclusion=prim["conclusion"],
            fc=float(prim["fc"]),
            holds=holds_fraction(grid, item, prim["conclusion"]),
            n_cells=total,
            impact=impact_per_dimension(grid, space, item),
        )
    return out


def to_csv_frame(grid: pd.DataFrame) -> pd.DataFrame:
    """A copy of the grid that serialises deterministically (tuples become ``a|b|c``)."""
    out = grid.copy()
    for name in _dimension_names(grid):
        out[name] = out[name].map(lambda v: "|".join(map(str, v)) if isinstance(v, tuple) else v)
    return out


def fragility(grid: pd.DataFrame, space: DecisionSpace) -> dict[str, int]:
    """``min_flip_changes`` for every item (input for the confidence checks)."""
    return {item: min_flip_changes(grid, space, item) for item in space.items}
