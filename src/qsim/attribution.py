"""Which decisions matter, alone and together, computed exactly from a full-factorial grid.

The grid is reshaped into a tensor with one axis per decision, so every quantity below is an
exact group-by over all contexts. No sampling, no surrogate model:

* ``holds``: share of cells whose call equals the baseline call (uniform weight per cell, an
  assumption stated in the ledger);
* ``flip_rate``: for each decision, the share of contexts (settings of every other decision) in
  which changing that decision alone changes the call;
* ``fragility``: fewest decisions changed from the baseline that flip the call;
* ``minimal_flip_sets``: sets of decisions whose joint change flips the call while no proper
  subset does (the "if we choose X and Y" answer);
* ``main_effect_share``: share of the log2 fold change variance explained by each decision
  alone, plus the pairwise interaction shares;
* ``lock_advisor``: the smallest set of decisions to fix in advance so that no remaining choice
  can flip any of the given genes (a minimal hitting set over flip sets).
"""

from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

from qsim.engine import Grid
from qsim.explore import distance


class Factorial:
    """A full-factorial grid (or a sub-factorial of allowed options) as tensors."""

    def __init__(self, grid: Grid, allowed: dict[str, list[int]] | None = None) -> None:
        space = grid.space
        levels = space.levels
        if len(grid.index) != int(np.prod(levels)):
            raise ValueError("attribution needs the full grid")
        expected = np.array(list(itertools.product(*[range(n) for n in levels])))
        if not np.array_equal(grid.index, expected):
            raise ValueError("grid rows are not in product order")
        self.grid, self.space = grid, space
        self.names = space.names
        self.allowed = [
            (allowed or {}).get(name, list(range(n)))
            for name, n in zip(self.names, levels, strict=True)
        ]
        sel = np.ix_(*self.allowed, np.arange(len(grid.items)))

        def tensor(a: np.ndarray) -> np.ndarray:
            return a.reshape(*levels, len(grid.items))[sel]

        self.call = tensor(grid.call)
        self.log2fc = tensor(grid.log2fc)
        base = space.baseline_index()
        self.base_pos = tuple(opts.index(b) for opts, b in zip(self.allowed, base, strict=True))
        self.base_call = self.call[self.base_pos]
        self.base_log2fc = self.log2fc[self.base_pos]
        idx = np.array(list(itertools.product(*[range(len(a)) for a in self.allowed])))
        self.dist = distance(idx, self.base_pos).reshape(self.call.shape[:-1])
        self.flipped = self.call != self.base_call

    @property
    def n_cells(self) -> int:
        return int(np.prod(self.call.shape[:-1]))

    def holds(self) -> np.ndarray:
        axes = tuple(range(len(self.names)))
        return 1.0 - self.flipped.mean(axis=axes)

    def flip_rate(self) -> pd.DataFrame:
        out = {}
        for d, name in enumerate(self.names):
            varies = self.call.max(axis=d) != self.call.min(axis=d)
            out[name] = varies.mean(axis=tuple(range(len(self.names) - 1)))
        return pd.DataFrame(out, index=self.grid.items)

    def single_flips(self) -> pd.DataFrame:
        """Genes flipped by changing only one decision from the baseline (ring 1)."""
        out = {}
        for d, name in enumerate(self.names):
            line = [slice(None) if k == d else p for k, p in enumerate(self.base_pos)]
            out[name] = (self.call[tuple(line)] != self.base_call).any(axis=0)
        return pd.DataFrame(out, index=self.grid.items)

    def fragility(self) -> np.ndarray:
        """Fewest changed decisions that flip each gene's call; 0 when nothing flips it."""
        dist = np.broadcast_to(self.dist[..., None], self.flipped.shape)
        masked = np.where(self.flipped, dist, 99)
        best = masked.reshape(-1, masked.shape[-1]).min(axis=0)
        return np.where(best == 99, 0, best)

    def minimal_flip_sets(self, gene: str) -> list[tuple[str, ...]]:
        g = self.grid.items.index(gene)
        flips = np.argwhere(self.flipped[..., g])
        masks = set()
        for cell in flips:
            masks.add(
                frozenset(
                    d for d, (v, b) in enumerate(zip(cell, self.base_pos, strict=True)) if v != b
                )
            )
        minimal = [m for m in masks if not any(o < m for o in masks)]
        return sorted(
            (tuple(self.names[d] for d in sorted(m)) for m in minimal), key=lambda t: (len(t), t)
        )

    def main_effect_share(self) -> pd.DataFrame:
        y = self.log2fc
        axes = tuple(range(len(self.names)))
        total = y.var(axis=axes)
        out = {}
        for d, name in enumerate(self.names):
            others = tuple(a for a in axes if a != d)
            out[name] = y.mean(axis=others).var(axis=0) / total
        return pd.DataFrame(out, index=self.grid.items)

    def interaction_share(self) -> pd.DataFrame:
        y = self.log2fc
        axes = tuple(range(len(self.names)))
        total = y.var(axis=axes)
        mu = y.mean(axis=axes)
        rows = {}
        for d1, d2 in itertools.combinations(range(len(self.names)), 2):
            rest = tuple(a for a in axes if a not in (d1, d2))
            m12 = y.mean(axis=rest)
            m1 = y.mean(axis=tuple(a for a in axes if a != d1))
            m2 = y.mean(axis=tuple(a for a in axes if a != d2))
            inter = m12 - m1[:, None, :] - m2[None, :, :] + mu
            rows[f"{self.names[d1]}x{self.names[d2]}"] = (inter**2).mean(axis=(0, 1)) / total
        return pd.DataFrame(rows, index=self.grid.items)

    def lock_advisor(self, genes: list[str]) -> list[str] | None:
        """Smallest set of decisions to fix at baseline so none of ``genes`` can flip."""
        cols = [self.grid.items.index(g) for g in genes]
        flipped = self.flipped[..., cols].any(axis=-1)
        k = len(self.names)
        for size in range(k + 1):
            for locked in itertools.combinations(range(k), size):
                sel = tuple(self.base_pos[d] if d in locked else slice(None) for d in range(k))
                if not flipped[sel].any():
                    return [self.names[d] for d in locked]
        return None

    def gene_table(self) -> pd.DataFrame:
        from qsim.engine import CALL_NAMES

        frag = self.fragility()
        single = self.single_flips()
        table = pd.DataFrame(
            {
                "baseline_call": [CALL_NAMES[int(c)] for c in self.base_call],
                "baseline_fold": 2**self.base_log2fc,
                "holds": self.holds(),
                "fragility": frag,
                "flipped_by_one": single.apply(lambda r: ",".join(r.index[r]), axis=1),
            },
            index=self.grid.items,
        )
        table["interaction_only"] = (table["fragility"] >= 2) & (table["flipped_by_one"] == "")
        return table
