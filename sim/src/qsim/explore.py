"""Choose which cells of the decision space to run, and say honestly what was covered.

Strategies (all deterministic for a given seed):

* ``full``: every combination, when the space is cheap enough.
* ``rings``: every cell within r changed decisions of the baseline. This is an anchored
  decomposition around the prespecified analysis (Owen), i.e. local robustness.
* ``covering_array``: a greedy strength-t covering array (every t-tuple of options appears at
  least once), seeded with the baseline (Kuhn, Kacker & Lei, NIST SP 800-142).
* ``morris``: one-at-a-time trajectories from random starts (Morris 1991). On a flip indicator
  the mean absolute elementary effect is the probability that changing that decision flips the
  call (Campolongo et al. 2007).
* ``random_cells``: a uniform random stratum, the only basis for share-of-space estimates.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np

from qsim.decisions import Space


def full(space: Space) -> np.ndarray:
    return np.array(list(itertools.product(*[range(n) for n in space.levels])), dtype=np.int16)


def distance(cells: np.ndarray, baseline: tuple[int, ...]) -> np.ndarray:
    """Number of decisions in which each cell differs from the baseline."""
    return (np.asarray(cells) != np.array(baseline)).sum(axis=1)


def rings(space: Space, max_ring: int) -> np.ndarray:
    base = space.baseline_index()
    out = []
    for r in range(max_ring + 1):
        for dims in itertools.combinations(range(len(base)), r):
            choices = [[i for i in range(space.levels[d]) if i != base[d]] for d in dims]
            for values in itertools.product(*choices):
                cell = list(base)
                for d, v in zip(dims, values, strict=True):
                    cell[d] = v
                out.append(cell)
    return np.array(out, dtype=np.int16)


def ring_sizes(space: Space) -> list[int]:
    from math import prod

    alt = [n - 1 for n in space.levels]
    return [sum(prod(c) for c in itertools.combinations(alt, r)) for r in range(len(alt) + 1)]


def _tuples(levels: list[int], t: int) -> set[tuple]:
    out = set()
    for cols in itertools.combinations(range(len(levels)), t):
        for vals in itertools.product(*(range(levels[c]) for c in cols)):
            out.add((cols, vals))
    return out


def covering_array(space: Space, strength: int, seed: int = 0, candidates: int = 20) -> np.ndarray:
    """Greedy covering array; the first row is the baseline. An upper bound, not optimal."""
    rng = np.random.default_rng(seed)
    levels = space.levels
    k = len(levels)
    combos = list(itertools.combinations(range(k), strength))
    uncovered = _tuples(levels, strength)
    rows: list[list[int]] = []

    def covered_by(row: list[int]) -> set[tuple]:
        return {(c, tuple(row[x] for x in c)) for c in combos}

    def take(row: list[int]) -> None:
        rows.append(row)
        uncovered.difference_update(covered_by(row))

    take(list(space.baseline_index()))
    while uncovered:
        target_cols, target_vals = min(uncovered)
        best, best_gain = None, -1
        for _ in range(candidates):
            row = [int(rng.integers(n)) for n in levels]
            for c, v in zip(target_cols, target_vals, strict=True):
                row[c] = v
            for col in rng.permutation(k):
                if col in target_cols:
                    continue
                gains = []
                for value in range(levels[col]):
                    row[col] = value
                    gains.append(len(covered_by(row) & uncovered))
                row[col] = int(np.argmax(gains))
            gain = len(covered_by(row) & uncovered)
            if gain > best_gain:
                best, best_gain = row[:], gain
        take(best)
    return np.array(rows, dtype=np.int16)


def coverage(space: Space, cells: np.ndarray, strength: int) -> float:
    """Share of all strength-t option tuples that appear in at least one of ``cells``."""
    allt = _tuples(space.levels, strength)
    seen = set()
    for row in np.asarray(cells):
        for cols in itertools.combinations(range(len(row)), strength):
            seen.add((cols, tuple(int(row[c]) for c in cols)))
    return len(seen & allt) / len(allt)


def morris(space: Space, trajectories: int, seed: int = 0) -> list[np.ndarray]:
    """One-at-a-time trajectories: a random start, then each decision changed once."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(trajectories):
        cell = [int(rng.integers(n)) for n in space.levels]
        path = [cell[:]]
        for d in rng.permutation(len(cell)):
            choices = [i for i in range(space.levels[d]) if i != cell[d]]
            cell[d] = int(rng.choice(choices))
            path.append(cell[:])
        out.append(np.array(path, dtype=np.int16))
    return out


def random_cells(space: Space, n: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.stack([rng.integers(0, k, size=n) for k in space.levels], axis=1).astype(np.int16)


@dataclass
class Ledger:
    """What was explored; printed with every result, never optional."""

    strategy: str
    total_cells: int
    evaluated: int
    per_ring: dict[int, tuple[int, int]] = field(default_factory=dict)
    t_way: dict[int, float] = field(default_factory=dict)
    seeds: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def exhaustive(self) -> bool:
        return self.evaluated == self.total_cells

    def as_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "total_cells": self.total_cells,
            "evaluated": self.evaluated,
            "share_evaluated": self.evaluated / self.total_cells,
            "exploration": "exhaustive" if self.exhaustive else "partial",
            "per_ring": {
                str(k): {"evaluated": v[0], "total": v[1]} for k, v in self.per_ring.items()
            },
            "t_way_coverage": {str(k): v for k, v in self.t_way.items()},
            "seeds": self.seeds,
            "notes": self.notes,
        }


def ledger(
    space: Space, cells: np.ndarray, strategy: str, seeds: dict[str, int] | None = None
) -> Ledger:
    cells = np.unique(np.asarray(cells), axis=0)
    sizes = ring_sizes(space)
    dist = distance(cells, space.baseline_index())
    per_ring = {r: (int((dist == r).sum()), sizes[r]) for r in range(len(sizes))}
    total = int(np.prod(space.levels))
    out = Ledger(strategy, total, len(cells), per_ring, seeds=seeds or {})
    if len(cells) < total:
        out.t_way = {t: coverage(space, cells, t) for t in (1, 2)}
    else:
        out.t_way = {1: 1.0, 2: 1.0, 3: 1.0}
    return out
