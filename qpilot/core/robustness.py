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
- **rests on**: the dimensions whose change alone, from the primary cell, flips an item's
  conclusion (:func:`fragility_by_axis`), i.e. which choice the answer depends on.

Keeping big grids affordable (W3 §4.2): :func:`screen_axis` varies one dimension alone from the
primary cell so a plugin can leave out an optional axis that changes nothing that matters, and
``run_grid(space, max_cells=N)`` evaluates, when the full product is larger than ``N``, the
primary cell, every one-at-a-time cell (so ``impact`` stays exact) and a seeded uniform sample
of the other cells. :func:`grid_plan` says which of the two happened. Without ``max_cells`` the
grid is the full product, exactly as before.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
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


def _sampled_combos(
    space: DecisionSpace, names: list[str], sizes: list[int], max_cells: int, seed: int
) -> list[tuple[int, ...]]:
    """Primary + one-at-a-time cells + a seeded uniform sample of the rest, in product order."""
    primary = _primary_index(space)
    base = tuple(primary[n] for n in names)
    must = {base}
    for d, size in enumerate(sizes):
        for i in range(size):
            must.add(base[:d] + (i,) + base[d + 1 :])
    total = math.prod(sizes)
    flat_must = {int(np.ravel_multi_index(c, sizes)) for c in must}
    room = max(0, max_cells - len(flat_must))
    rest = np.setdiff1d(np.arange(total, dtype=np.int64), np.fromiter(flat_must, np.int64))
    rng = np.random.default_rng(seed)
    picked = rng.choice(rest, size=min(room, len(rest)), replace=False) if room else rest[:0]
    flat = np.sort(np.concatenate([np.fromiter(flat_must, np.int64), picked]))
    return [tuple(int(i) for i in c) for c in zip(*np.unravel_index(flat, sizes), strict=True)]


def grid_plan(space: DecisionSpace, max_cells: int | None = None, seed: int = 0) -> dict[str, Any]:
    """What :func:`run_grid` evaluates: the full product, or a seeded sample of it."""
    total = n_cells(space)
    sampled = max_cells is not None and total > max_cells
    if sampled:
        sizes = [len(options) for options in space.dimensions.values()]
        evaluated = len(_sampled_combos(space, list(space.dimensions), sizes, max_cells, seed))
    else:
        evaluated = total
    return {
        "dimensions": list(space.dimensions),
        "full_product": total,
        "n_cells": evaluated,
        "sampled": sampled,
        "max_cells": max_cells,
        "seed": seed if sampled else None,
    }


def run_grid(space: DecisionSpace, *, max_cells: int | None = None, seed: int = 0) -> pd.DataFrame:
    """Evaluate every cell (or a capped sample of them) and return one row per cell x item.

    Columns: one per dimension (the option value), one ``<dimension>__idx`` per dimension (the
    option's position, used for comparisons because option values may be tuples), then ``item``,
    ``log2fc``, ``fc``, ``p`` and ``conclusion`` (from ``space.conclude``).

    With ``max_cells`` and a product larger than it, only the primary cell, every
    one-at-a-time cell and a sample (``numpy`` generator seeded with ``seed``) of the other
    cells are evaluated, still in product order; see :func:`grid_plan`.
    """
    names = list(space.dimensions)
    rows: list[dict[str, Any]] = []
    sizes = [len(space.dimensions[n]) for n in names]
    if max_cells is not None and math.prod(sizes) > max_cells:
        index_combos: Any = _sampled_combos(space, names, sizes, max_cells, seed)
    else:
        index_combos = itertools.product(*(range(size) for size in sizes))
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


def flipped_anywhere(grid: pd.DataFrame, dimension: str) -> list[str]:
    """Items whose conclusion changes with ``dimension`` at *some* setting of the others.

    Two grid cells that differ only in ``dimension`` and give different conclusions are enough;
    unlike :func:`impact_per_dimension`, the other choices need not be at their primary values.
    """
    others = [f"{n}{IDX_SUFFIX}" for n in _dimension_names(grid) if n != dimension]
    counts = grid.groupby(["item", *others])["conclusion"].nunique()
    return sorted(set(counts[counts > 1].index.get_level_values("item")))


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


@dataclass(frozen=True)
class AxisScreen:
    """One dimension varied alone from the primary cell: does any option matter?"""

    name: str
    flipped: dict[str, tuple[str, ...]]  # option (as grid.csv writes it) -> items that flip
    max_delta_log2fc: float  # over options and items, finite values only
    min_log2fc: float
    admitted: bool  # some option flips an item or moves a log2 fold change > min_log2fc

    def as_dict(self) -> dict[str, Any]:
        """JSON form (stable key order)."""
        return {
            "name": self.name,
            "admitted": self.admitted,
            "min_log2fc": self.min_log2fc,
            "max_delta_log2fc": self.max_delta_log2fc,
            "flipped": {k: list(v) for k, v in self.flipped.items()},
        }


def _text(value: Any) -> str:
    return "|".join(map(str, value)) if isinstance(value, tuple) else str(value)


def screen_axis(
    space: DecisionSpace,
    name: str,
    options: Sequence[Any] | None = None,
    min_log2fc: float = 0.5,
) -> AxisScreen:
    """Vary ``name`` alone from the primary cell and decide whether it belongs in the grid.

    Admitted when some option flips an item's conclusion or moves a log2 fold change by more
    than ``min_log2fc`` (W3 §4.2; 0.5 log2 is the prototypes' reporting threshold). An axis
    that moves nothing alone can still interact with others; the plugin records it as
    screened out, never as absent.
    """
    options = list(space.dimensions[name] if options is None else options)
    base = space.evaluate(dict(space.primary))
    flipped: dict[str, tuple[str, ...]] = {}
    largest = 0.0
    for option in options:
        if option == space.primary.get(name):
            continue
        results = space.evaluate({**space.primary, name: option})
        flips = tuple(
            item
            for item in space.items
            if space.conclude(results[item]) != space.conclude(base[item])
        )
        flipped[_text(option)] = flips
        shifts = [abs(results[i].log2fc - base[i].log2fc) for i in space.items]
        finite = [s for s in shifts if math.isfinite(s)]
        largest = max(largest, max(finite, default=0.0))
    admitted = any(flipped.values()) or largest > min_log2fc
    return AxisScreen(name, flipped, float(largest), float(min_log2fc), bool(admitted))


def fragility_by_axis(grid: pd.DataFrame, space: DecisionSpace) -> dict[str, dict[str, Any]]:
    """Per item: which choices its conclusion rests on (JSON-serialisable, stable order).

    ``rests_on`` lists the dimensions whose change alone, from the primary cell, flips the
    conclusion; ``by_axis`` gives for every dimension ``flips`` (alone), ``flips_anywhere``
    (at some setting of the others), ``max_delta_log2fc`` (alone) and ``flipping_options``
    (alone; option values as ``grid.csv`` writes them, in option order).
    """
    primary_idx = _primary_index(space)
    names = list(space.dimensions)
    prim_rows = grid[_primary_mask(grid, primary_idx)].set_index("item")
    anywhere = {name: set(flipped_anywhere(grid, name)) for name in names}
    alone: dict[str, pd.DataFrame] = {}
    for name in names:
        rows = grid[_primary_mask(grid, primary_idx, skip=name)]
        base = prim_rows.loc[rows["item"]]
        alone[name] = rows.assign(
            changed=rows["conclusion"].to_numpy() != base["conclusion"].to_numpy(),
            delta=(rows["log2fc"].to_numpy() - base["log2fc"].to_numpy()),
        )
    out: dict[str, dict[str, Any]] = {}
    for item in space.items:
        conclusion = str(prim_rows.loc[item, "conclusion"])
        by_axis: dict[str, dict[str, Any]] = {}
        for name in names:
            rows = alone[name][alone[name]["item"] == item]
            changed = rows[rows["changed"]].sort_values(f"{name}{IDX_SUFFIX}")
            deltas = rows["delta"].abs()
            by_axis[name] = {
                "flips": bool(len(changed)),
                "flips_anywhere": item in anywhere[name],
                "max_delta_log2fc": float(deltas.max()) if len(deltas) else 0.0,
                "flipping_options": [_text(v) for v in changed[name]],
            }
        out[item] = {
            "conclusion": conclusion,
            "holds": holds_fraction(grid, item, conclusion),
            "min_flip_changes": min_flip_changes(grid, space, item),
            "rests_on": [name for name in names if by_axis[name]["flips"]],
            "by_axis": by_axis,
        }
    return out
