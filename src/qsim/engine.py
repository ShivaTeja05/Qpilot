"""Run analyses: one cell of the decision space in, every gene's result out.

Cells are executed in stage order (matrix -> normaliser -> groups -> test -> correction), and
each stage's output is kept only while the next cell shares the same prefix. Cells are sorted
lexicographically first, so a whole sweep is a depth-first walk of the prefix tree: each
matrix, normaliser and test is computed once per distinct prefix.

Conventions, matching qPilot so that the baseline cell reproduces qPilot's results exactly:

* the non-detect rule applies to target genes; a sample missing a reference gene in the chosen
  set is left out of that gene's comparison;
* groups are fixed per cut-off from the baseline matrix and the primary reference genes, so a
  different choice never moves a sample between groups;
* the fold change and its CI come from the difference of group means on the log2 scale. The
  ``test`` decision changes only the p-value, except Student's test, which also uses the pooled
  standard error.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from qpilot.qpcr.contrast import DEFAULT_RULE, ConclusionRule
from scipy import stats

from qsim.data import Study
from qsim.decisions import Space

UP, NONE, DOWN = 1, 0, -1
CALL_NAMES = {UP: "up", NONE: "none", DOWN: "down"}


@dataclass
class Grid:
    """Results of many cells: arrays of shape (cells, genes)."""

    space: Space
    items: list[str]
    index: np.ndarray
    log2fc: np.ndarray
    se: np.ndarray
    lo: np.ndarray
    hi: np.ndarray
    p: np.ndarray
    p_adj: np.ndarray
    call: np.ndarray
    rule: ConclusionRule

    def row_of(self, cell: tuple[int, ...]) -> int:
        hits = np.where((self.index == np.array(cell)).all(axis=1))[0]
        if hits.size != 1:
            raise KeyError(f"cell {cell} is not in this grid")
        return int(hits[0])

    def baseline_row(self) -> int:
        return self.row_of(self.space.baseline_index())

    def margins(self) -> tuple[np.ndarray, np.ndarray]:
        """Distance to the decision boundary: log2 beyond the fold line, decades beyond alpha."""
        fold = np.abs(self.log2fc) - self.rule.min_log2fc
        with np.errstate(divide="ignore"):
            sig = np.log10(self.rule.alpha) - np.log10(np.maximum(self.p_adj, 1e-300))
        return fold, sig

    def to_frame(self) -> pd.DataFrame:
        """One row per cell x gene (for Parquet)."""
        cells, genes = self.call.shape
        frame = pd.DataFrame(
            {name: np.repeat(self.index[:, j], genes) for j, name in enumerate(self.space.names)}
        )
        frame["gene"] = np.tile(np.array(self.items, dtype=object), cells)
        for name in ("log2fc", "se", "lo", "hi", "p", "p_adj", "call"):
            frame[name] = getattr(self, name).ravel()
        return frame


class Engine:
    """Evaluates cells of a :class:`Space` on one :class:`Study`."""

    def __init__(self, study: Study, space: Space, rule: ConclusionRule = DEFAULT_RULE) -> None:
        self.study, self.space, self.rule = study, space, rule
        self.items = list(study.items)
        self._item_cols = study.item_columns()
        self._ref_cols = {
            o.id: np.array([study.genes.index(g) for g in o.value])
            for o in space.decision("refs").options
        }
        self._masks = {o.value: study.group_masks(o.value) for o in space.decision("cut").options}
        # one fluorescence threshold per plate: the Cq = 40 substitute needs it for wells with no Cq
        runs = pd.Series(study.run.ravel())
        nq = pd.Series(study.log2_nq.ravel())
        self._plate_nq = nq.groupby(runs).transform("median").to_numpy().reshape(study.run.shape)
        self._undetermined = np.isnan(study.cq)
        self._last: dict[str, tuple[object, object]] = {}

    # ---- stage 1: the samples x genes log2 quantity matrix -------------------------------
    def matrix(self, efficiency: str, flagged: str, nondetect: str, drop: np.ndarray | None = None):
        s = self.study
        if efficiency == "assay":
            values = s.log2_n0.copy()
            eff = s.eff_assay
        elif efficiency == "well":
            with np.errstate(divide="ignore", invalid="ignore"):
                values = s.log2_nq - s.cq * np.log2(s.eff_well)
            eff = s.eff_assay
        elif efficiency == "std":
            # plates without a usable standard curve keep the LinRegPCR assay mean
            eff = np.where(np.isnan(s.eff_std), s.eff_assay, s.eff_std)
            values = s.log2_nq - s.cq * np.log2(eff)
        elif efficiency == "fixed2":
            values = s.log2_nq - s.cq
            eff = np.full_like(s.eff_assay, 2.0)
        else:
            raise ValueError(f"unknown efficiency model {efficiency!r}")
        missing = np.zeros(values.shape, dtype=bool)
        if flagged in ("eff", "eff_low"):
            missing |= s.flag_eff
        if flagged == "eff_low":
            missing |= s.flag_low
        if drop is not None:
            missing |= drop
        undetermined = self._undetermined & ~missing
        values[missing] = np.nan
        items = self._item_cols
        target = values[:, items]
        und = undetermined[:, items]
        if nondetect == "cap":
            lowest = np.nanmin(np.where(und, np.nan, target), axis=0)
            target = np.where(und, lowest[None, :], target)
        elif nondetect == "cq40":
            sub = self._plate_nq[:, items] - 40.0 * np.log2(eff[:, items])
            target = np.where(und, sub, target)
        elif nondetect != "drop":
            raise ValueError(f"unknown non-detect rule {nondetect!r}")
        return values, target

    # ---- stage 2: normalise by the mean of a reference-gene subset ----------------------
    def relative(self, matrix, refs_id: str):
        values, target = matrix
        mean = values[:, self._ref_cols[refs_id]].mean(axis=1)  # NaN when any chosen ref is missing
        rel = target - mean[:, None]
        return rel, ~np.isnan(rel)

    # ---- stage 3+4: groups and the two-group test ---------------------------------------
    def compare(self, relative, cut: float, test: str):
        rel, valid = relative
        hi_mask, lo_mask = self._masks[cut]
        a = valid & hi_mask[:, None]
        b = valid & lo_mask[:, None]
        na, nb = a.sum(0), b.sum(0)
        x = np.where(valid, rel, 0.0)
        ma = (x * a).sum(0) / na
        mb = (x * b).sum(0) / nb
        va = (((x - ma) ** 2) * a).sum(0) / (na - 1)
        vb = (((x - mb) ** 2) * b).sum(0) / (nb - 1)
        diff = ma - mb
        if test == "student":
            pooled = ((na - 1) * va + (nb - 1) * vb) / (na + nb - 2)
            se = np.sqrt(pooled * (1 / na + 1 / nb))
            df = na + nb - 2.0
        else:
            sa, sb = va / na, vb / nb
            se = np.sqrt(sa + sb)
            df = (sa + sb) ** 2 / (sa**2 / (na - 1) + sb**2 / (nb - 1))
        t = diff / se
        half = stats.t.ppf(0.975, df) * se
        if test == "mwu":
            p = mann_whitney(rel, a, b)
        else:
            p = 2 * stats.t.sf(np.abs(t), df)
        bad = (na < 2) | (nb < 2)
        p = np.where(bad, np.nan, p)
        return diff, se, diff - half, diff + half, p, t

    def conclude(self, diff: np.ndarray, p: np.ndarray, multiplicity: str):
        p_adj = adjust(p, multiplicity)
        sig = p_adj < self.rule.alpha
        call = np.where(sig & (diff >= self.rule.min_log2fc), UP, NONE)
        call = np.where(sig & (diff <= -self.rule.min_log2fc), DOWN, call)
        return p_adj, call.astype(np.int8)

    # ---- sweeps ----------------------------------------------------------------------
    def _stage(self, level: str, key: tuple, build):
        cached = self._last.get(level)
        if cached is not None and cached[0] == key:
            return cached[1]
        value = build()
        self._last[level] = (key, value)
        return value

    def values_of(self, cell: tuple[int, ...]) -> dict[str, object]:
        return {d.id: d.options[i].value for d, i in zip(self.space.decisions, cell, strict=True)}

    def ids_of(self, cell: tuple[int, ...]) -> dict[str, str]:
        return self.space.to_assignment(cell)

    def evaluate(self, cell: tuple[int, ...], drop: np.ndarray | None = None):
        """One cell; ``drop`` removes extra wells (a data perturbation, never cached)."""
        v, ids = self.values_of(cell), self.ids_of(cell)
        if drop is None:
            matrix = self._stage(
                "matrix",
                tuple(cell[:3]),
                lambda: self.matrix(v["efficiency"], v["flagged"], v["nondetect"]),
            )
            rel = self._stage("rel", tuple(cell[:4]), lambda: self.relative(matrix, ids["refs"]))
            out = self._stage(
                "cmp", tuple(cell[:6]), lambda: self.compare(rel, v["cut"], v["test"])
            )
        else:
            matrix = self.matrix(v["efficiency"], v["flagged"], v["nondetect"], drop)
            rel = self.relative(matrix, ids["refs"])
            out = self.compare(rel, v["cut"], v["test"])
        diff, se, lo, hi, p, _ = out
        p_adj, call = self.conclude(diff, p, v["multiplicity"])
        return {"log2fc": diff, "se": se, "lo": lo, "hi": hi, "p": p, "p_adj": p_adj, "call": call}

    def run(self, cells: np.ndarray) -> Grid:
        cells = np.asarray(cells, dtype=np.int16)
        n, g = len(cells), len(self.items)
        arrays = {k: np.empty((n, g)) for k in ("log2fc", "se", "lo", "hi", "p", "p_adj")}
        call = np.empty((n, g), dtype=np.int8)
        order = np.lexsort(cells.T[::-1])
        for row in order:
            res = self.evaluate(tuple(int(x) for x in cells[row]))
            for k in arrays:
                arrays[k][row] = res[k]
            call[row] = res["call"]
        return Grid(self.space, self.items, cells, call=call, rule=self.rule, **arrays)


def adjust(p: np.ndarray, method: str) -> np.ndarray:
    """Benjamini-Hochberg or Holm adjustment across genes (NaN p-values are left out)."""
    if method == "none":
        return p
    out = np.full_like(p, np.nan)
    ok = ~np.isnan(p)
    q = p[ok]
    m = q.size
    order = np.argsort(q, kind="mergesort")
    ranked = q[order]
    if method == "bh":
        adj = ranked * m / np.arange(1, m + 1)
        adj = np.minimum.accumulate(adj[::-1])[::-1]
    elif method == "holm":
        adj = ranked * (m - np.arange(m))
        adj = np.maximum.accumulate(adj)
    else:
        raise ValueError(f"unknown correction {method!r}")
    back = np.empty(m)
    back[order] = np.minimum(adj, 1.0)
    out[ok] = back
    return out


def mann_whitney(rel: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Two-sided Mann-Whitney U p-values per column (normal approximation, tie and continuity
    corrected, as ``scipy.stats.mannwhitneyu(method="asymptotic")``)."""
    p = np.full(rel.shape[1], np.nan)
    for j in range(rel.shape[1]):
        xa, xb = rel[a[:, j], j], rel[b[:, j], j]
        n1, n2 = xa.size, xb.size
        if n1 < 2 or n2 < 2:
            continue
        both = np.concatenate([xa, xb])
        ranks = stats.rankdata(both)
        u1 = ranks[:n1].sum() - n1 * (n1 + 1) / 2
        _, counts = np.unique(both, return_counts=True)
        n = n1 + n2
        tie = (counts**3 - counts).sum() / (n * (n - 1))
        sigma = np.sqrt(n1 * n2 / 12 * ((n + 1) - tie))
        mu = n1 * n2 / 2
        z = (abs(u1 - mu) - 0.5) / sigma
        p[j] = min(1.0, 2 * stats.norm.sf(z))
    return p
