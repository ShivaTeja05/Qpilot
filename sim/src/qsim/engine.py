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
  standard error;
* technical replicates (a study with :attr:`qsim.data.Study.replicates`): every matrix-stage
  choice acts on each well, then a sample's wells are combined (``replicates``: the mean
  ``log2 N0`` of the wells that have a value, qPilot's rule; or their median; or the mean after
  leaving out a well outside the expected replicate spread, :func:`replicate_outliers`). A
  value is undetermined only when every well that is not left out is, and left out (never
  filled in) when every well is. Replicates are never counted as n: the groups compare samples.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from qpilot.qpcr.contrast import DEFAULT_RULE, ConclusionRule
from scipy import stats

from qsim.data import Study
from qsim.decisions import Space

UP, NONE, DOWN = 1, 0, -1
CALL_NAMES = {UP: "up", NONE: "none", DOWN: "down"}
COMBINE = ("mean", "median", "outlier")  # how a sample's replicate wells become one value
# G-REP's defaults (packs/research-default.yaml; methods/design_checks.md, D-REP): pipetting CV,
# the two-cycle floor up to Cq 35, and the Cq above which replicate spread is not judged.
PIPETTING_CV = 0.15
COPIES_UNKNOWN_MAX_CQ = 30.0
LOW_COPY_TOLERANCE = 2.0
STOCHASTIC_MIN_CQ = 35.0


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
        wells = study.replicates
        if wells is None:
            runs = pd.Series(study.run.ravel())
            nq = pd.Series(study.log2_nq.ravel())
            self._plate_nq = (
                nq.groupby(runs).transform("median").to_numpy().reshape(study.run.shape)
            )
            # a cell without any well (a unit not measured for a gene) is left out, never
            # undetermined: no non-detect rule fills it in
            self._undetermined = np.isnan(study.cq) & (study.well != "")
        else:
            runs = pd.Series(np.where(wells.present, wells.run, "").ravel())
            nq = pd.Series(np.where(wells.present, wells.log2_nq, np.nan).ravel())
            self._plate_nq = (
                nq.groupby(runs).transform("median").to_numpy().reshape(wells.run.shape)
            )
            self._undetermined = wells.present & np.isnan(wells.cq)
        self._last: dict[str, tuple[object, object]] = {}
        names = space.names
        stages = [d.stage for d in space.decisions]
        self._m = next(i for i, s in enumerate(stages) if s != "matrix")
        if stages[self._m :].count("matrix") or names[self._m] != "refs":
            raise ValueError("matrix-stage decisions must come first, then refs, cut, test")
        self._cmp = names.index("test") + 1

    # ---- stage 1: the samples x genes log2 quantity matrix -------------------------------
    def matrix_of(self, v: dict, drop: np.ndarray | None = None):
        """:meth:`matrix` at a cell's option values (:meth:`values_of`)."""
        return self.matrix(
            v["efficiency"],
            v["flagged"],
            v["nondetect"],
            drop,
            v.get("late_cq"),
            v.get("replicates"),
        )

    def matrix(
        self,
        efficiency: str,
        flagged: str,
        nondetect: str,
        drop: np.ndarray | None = None,
        late: float | None = None,
        combine: str | None = None,
    ):
        """``(values, target)``: samples x genes log2 quantities, and the compared genes' after
        the non-detect rule. ``drop`` marks values (samples x genes) or, with replicates, single
        wells (samples x genes x wells) to leave out; ``combine`` is how replicates are combined
        (:data:`COMBINE`; ignored without replicates)."""
        if self.study.replicates is not None:
            return self._replicate_matrix(
                efficiency, flagged, nondetect, drop, late, combine or "mean"
            )
        s = self.study
        values, eff = _quantities(s, efficiency)
        missing = np.zeros(values.shape, dtype=bool)
        if flagged in ("eff", "eff_low"):
            missing |= s.flag_eff
        if flagged == "eff_low":
            missing |= s.flag_low
        if drop is not None:
            missing |= drop
        undetermined = self._undetermined.copy()
        if late is not None:
            undetermined |= ~np.isnan(s.cq) & (s.cq > late)
        undetermined &= ~missing
        values[undetermined] = np.nan
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

    def _replicate_matrix(self, efficiency, flagged, nondetect, drop, late, combine):
        """:meth:`matrix` with technical replicates: each choice per well, then per sample."""
        w = self.study.replicates
        values, eff = _quantities(w, efficiency)
        missing = np.zeros(values.shape, dtype=bool)
        if flagged in ("eff", "eff_low"):
            missing |= w.flag_eff
        if flagged == "eff_low":
            missing |= w.flag_low
        if drop is not None:
            missing |= drop if drop.ndim == 3 else drop[:, :, None]
        missing &= w.present
        undetermined = self._undetermined.copy()
        if late is not None:
            with np.errstate(invalid="ignore"):
                undetermined |= w.present & ~np.isnan(w.cq) & (w.cq > late)
        undetermined &= w.present & ~missing
        usable = w.present & ~missing & ~undetermined & ~np.isnan(values)
        if combine == "outlier":
            usable &= ~replicate_outliers(w.cq, w.eff_assay, usable, w.std_slope, w.std_intercept)
        elif combine not in COMBINE:
            raise ValueError(f"unknown replicate rule {combine!r}")
        # undetermined only when no well has a value and one never amplified; a sample whose
        # every well is left out (flagged, excluded, dropped) has no value and is never filled in
        unit_und = undetermined.any(axis=2) & ~usable.any(axis=2)
        how = "median" if combine == "median" else "mean"
        combined = _combine(values, usable, how, w.sub)
        items = self._item_cols
        target = combined[:, items]
        und = unit_und[:, items]
        if nondetect == "cap":
            lowest = np.nanmin(np.where(und, np.nan, target), axis=0)
            target = np.where(und, lowest[None, :], target)
        elif nondetect == "cq40":
            # the spreadsheet shortcut: every undetermined well becomes Cq 40, then the mean
            with np.errstate(divide="ignore", invalid="ignore"):
                sub = self._plate_nq - 40.0 * np.log2(eff)
            filled = np.where(undetermined, sub, values)
            target = _combine(filled, usable | undetermined, "mean", w.sub)[:, items]
        elif nondetect != "drop":
            raise ValueError(f"unknown non-detect rule {nondetect!r}")
        return combined, target

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
            matrix = self._stage("matrix", tuple(cell[: self._m]), lambda: self.matrix_of(v))
            rel = self._stage(
                "rel", tuple(cell[: self._m + 1]), lambda: self.relative(matrix, ids["refs"])
            )
            out = self._stage(
                "cmp", tuple(cell[: self._cmp]), lambda: self.compare(rel, v["cut"], v["test"])
            )
        else:
            matrix = self.matrix_of(v, drop)
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


def _quantities(s, efficiency: str) -> tuple[np.ndarray, np.ndarray]:
    """(log2 N0 under an efficiency model, the efficiency) for a study's or its wells' arrays."""
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
    return values, eff


def _combine(
    values: np.ndarray, use: np.ndarray, how: str, sub: np.ndarray | None = None
) -> np.ndarray:
    """Per sample and gene, the mean (or median) of the wells in ``use``; NaN where none is.

    With ``sub`` (each well's sample within its unit) the mean of a unit with several samples
    is the mean of its samples' means, as qPilot's (science review J10); a unit with one sample
    keeps the plain mean of its wells.
    """
    if how == "median":
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN slices: no value
            return np.nanmedian(np.where(use, values, np.nan), axis=2)
    n = use.sum(axis=2)
    total = np.where(use, values, 0.0).sum(axis=2)
    with np.errstate(divide="ignore", invalid="ignore"):
        flat = np.where(n > 0, total / n, np.nan)
    if sub is None:
        return flat
    same = (sub[:, :, :, None] == sub[:, :, None, :]) & use[:, :, None, :]
    n_same = same.sum(axis=3)  # per well: the used wells of its own sample
    with np.errstate(divide="ignore", invalid="ignore"):
        share = np.where(use, 1.0 / n_same, 0.0)
        n_samples = share.sum(axis=2)  # each sample counts once
        weight = np.where(use, share / n_samples[:, :, None], 0.0)
        two_level = np.where(use, values * weight, 0.0).sum(axis=2)
    return np.where(n_samples > 1 + 1e-9, two_level, flat)


def range_tolerance(
    n: np.ndarray, mean_cq: np.ndarray, eff: np.ndarray, copies: np.ndarray | None = None
) -> np.ndarray:
    """G-REP's expected Cq range of ``n`` replicate wells (``qpilot.qpcr.gate_rules``).

    The 95th percentile of the range of ``n`` normal values whose SD combines pipetting (CV
    0.15) and, where the plate's standard curve gives the wells' ``copies``, Poisson sampling:
    ``q95(n) * sqrt(0.15^2 + 1/N) / ln(E)`` (science review J10: the audit had the pipetting
    term only, so at low copy numbers it could leave out a well G-REP accepts). Without copies,
    from Cq 30 to 35 at least two cycles, because low copy numbers are possible.
    """
    from qpilot.qpcr.gate_rules import range_quantile

    q = np.zeros(n.shape)
    for m in np.unique(n[n >= 2]):
        q[n == m] = range_quantile(int(m))
    e = np.where(np.isfinite(eff) & (eff > 1.0), eff, 2.0)
    if copies is None:
        known = np.zeros(n.shape, dtype=bool)
        inv_n = np.zeros(n.shape)
    else:
        c = np.asarray(copies, dtype=float)
        known = np.isfinite(c) & (c > 0)
        with np.errstate(divide="ignore", invalid="ignore"):
            inv_n = np.where(known, 1.0 / np.where(known, c, 1.0), 0.0)
    tol = q * np.sqrt(PIPETTING_CV**2 + inv_n) / np.log(e)
    with np.errstate(invalid="ignore"):
        low_copy = ~known & (mean_cq > COPIES_UNKNOWN_MAX_CQ) & (mean_cq <= STOCHASTIC_MIN_CQ)
    return np.where(low_copy, np.maximum(tol, LOW_COPY_TOLERANCE), tol)


#: Two Cq deviations this close (cycles) are a tie, as G-REP's (``gate_rules.TIE_CYCLES``).
TIE_CYCLES = 1e-6


def replicate_outliers(
    cq: np.ndarray,
    eff: np.ndarray,
    use: np.ndarray,
    slope: np.ndarray | None = None,
    intercept: np.ndarray | None = None,
) -> np.ndarray:
    """Wells to leave out: per sample and gene with three or more wells in ``use`` whose Cq range
    is above :func:`range_tolerance`, the well farthest from their median Cq (G-REP's
    ``drop_outlier_well``). With two wells neither can be called the outlier, nor with a tie
    for the farthest (G-REP 1.4.0), and above Cq 35 without a standard curve the spread is
    sampling, so nothing is left out there. ``slope`` and ``intercept`` (per well, the plate's
    standard curve) give the copies of G-REP's Poisson term."""
    n = use.sum(axis=2)
    c = np.where(use, cq, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        median = np.nanmedian(c, axis=2)
        spread = np.nanmax(c, axis=2) - np.nanmin(c, axis=2)
        mean_cq = np.nanmean(c, axis=2)
        e = np.nanmedian(np.where(use, eff, np.nan), axis=2)
        copies = None
        if slope is not None and intercept is not None:
            m = np.nanmedian(np.where(use, slope, np.nan), axis=2)
            b = np.nanmedian(np.where(use, intercept, np.nan), axis=2)
            with np.errstate(invalid="ignore", divide="ignore", over="ignore"):
                copies = np.where(np.isfinite(m) & (m < 0), 10 ** ((mean_cq - b) / m), np.nan)
    known = np.zeros(n.shape, dtype=bool) if copies is None else np.isfinite(copies) & (copies > 0)
    dev = np.where(use, np.abs(c - median[:, :, None]), -math.inf)
    top = dev.max(axis=2)
    single = (dev >= top[:, :, None] - TIE_CYCLES).sum(axis=2) == 1
    with np.errstate(invalid="ignore"):
        judged = (n >= 3) & (known | (mean_cq <= STOCHASTIC_MIN_CQ)) & single
        outside = judged & (spread > range_tolerance(n, mean_cq, e, copies))
    far = np.argmax(dev, axis=2)
    out = np.zeros(use.shape, dtype=bool)
    np.put_along_axis(out, far[:, :, None], outside[:, :, None], axis=2)
    return out & use


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
