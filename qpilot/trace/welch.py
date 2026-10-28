"""Closed-form Welch updates: one or two units set aside, a unit shifted, a unit brought back.

Trace asks, for every sample it might point at, "what happens to each conclusion if this value
were different, or not there?". Each answer here is an exact update of the group statistics of
one comparison (Welch on the log2 scale, as :meth:`qpilot.qpcr.space.QpcrSpace.evaluate`
computes it), so nothing is re-run from scratch and nothing is approximated:

* :meth:`Comparison.leave_one_out` sets one unit aside from one gene's comparison, for every
  unit and gene at once;
* :meth:`Comparison.pairs` sets every pair of units aside from one gene's comparison (the
  exhaustive check behind "two samples change this call");
* :meth:`Comparison.shift` moves one unit's values on every gene by the same amount (one of its
  reference wells read differently moves the normaliser, so every relative value moves);
* :meth:`Comparison.bring_back` adds a unit that is in no comparison today;
* :meth:`Comparison.evaluate` re-evaluates any other set of values and groups in full.

Group statistics are kept as ``(n, mean, sum of squared deviations)`` and updated with the
numerically stable one-point formulas (Welford), so "this unit set aside" equals the comparison
computed without it to rounding error; the tests check that against a brute-force re-run.

A study with several comparisons (:class:`Family`): the statistics are kept per *group*, every
comparison of the study is computed from them after each change (a unit set aside leaves its
group, so every comparison of that group moves), and the call of the traced comparison uses the
corrected p-value (Holm across the gene's comparisons, or Dunnett's or Tukey's single-step p of
a pooled-variance test), exactly as the engine calls it. ``WelchArrays.p`` stays the p before
correction and ``p_adj`` is the corrected one.

Ported from the WIP branch ``agents/trace`` (``qpilot/qpcr/influence.py``, 19 Oct 2026), with the
pair search, the margin to the call's line and the greedy flip search added. The maths mirrors
the simulator's ``qsim.influence``; it is written again because the engine never imports the
simulator. Deterministic; no model call.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
from scipy import stats

from qpilot.qpcr.contrast import DEFAULT_RULE, ConclusionRule

UP, NONE, DOWN = 1, 0, -1
CALL_NAMES = {UP: "up", NONE: "none", DOWN: "down"}


@dataclass(frozen=True)
class GroupStats:
    """Per-gene count, mean and sum of squared deviations of one group (arrays broadcast)."""

    n: np.ndarray
    mean: np.ndarray
    ss: np.ndarray


@dataclass(frozen=True)
class WelchArrays:
    """Welch's test for many genes (or many perturbations x genes) at once.

    ``call`` holds :data:`UP`, :data:`NONE` or :data:`DOWN`; a gene with fewer than two values
    in a group has ``p`` NaN and the call ``NONE``, as in the decision space.
    """

    diff: np.ndarray
    se: np.ndarray
    p: np.ndarray
    df: np.ndarray
    t_crit: np.ndarray
    call: np.ndarray
    p_adj: np.ndarray | None = None  # the corrected p the call used (None: no correction)

    def half_width(self) -> np.ndarray:
        """Half the width of the 95 % confidence interval of the log2 fold change."""
        return self.t_crit * self.se

    @property
    def p_call(self) -> np.ndarray:
        """The p-value the call used: the corrected one when there is a correction."""
        return self.p if self.p_adj is None else self.p_adj

    def row(self, i: int) -> WelchArrays:
        """One row of a (perturbations x genes) result."""
        return WelchArrays(
            *(None if v is None else np.asarray(v)[i] for v in self.__dict__.values())
        )


def group_stats(values: np.ndarray, mask: np.ndarray) -> GroupStats:
    """Column-wise statistics of ``values`` where ``mask`` is true (two-pass, as the space)."""
    n = mask.sum(axis=0)
    filled = np.where(mask, values, 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):  # n < 2 is reported as p = NaN
        mean = filled.sum(axis=0) / n
        deviations = np.where(mask, values - mean, 0.0)
        ss = (deviations**2).sum(axis=0)
    return GroupStats(n=n.astype(float), mean=mean, ss=ss)


def calls(diff: np.ndarray, p: np.ndarray, rule: ConclusionRule = DEFAULT_RULE) -> np.ndarray:
    """Up / none / down codes under ``rule`` (NaN p is never significant)."""
    with np.errstate(invalid="ignore"):
        significant = p < rule.alpha
        up = significant & (diff >= rule.min_log2fc)
        down = significant & (diff <= -rule.min_log2fc)
    return np.where(up, UP, np.where(down, DOWN, NONE)).astype(int)


def welch(a: GroupStats, b: GroupStats, rule: ConclusionRule = DEFAULT_RULE) -> WelchArrays:
    """Welch's test of ``mean(a) - mean(b)``, element-wise over broadcast arrays."""
    with np.errstate(divide="ignore", invalid="ignore"):
        var_a, var_b = a.ss / (a.n - 1), b.ss / (b.n - 1)
        sa, sb = var_a / a.n, var_b / b.n
        se = np.sqrt(sa + sb)
        diff = a.mean - b.mean
        t = diff / se
        df = (sa + sb) ** 2 / (sa**2 / (a.n - 1) + sb**2 / (b.n - 1))
        short = (a.n < 2) | (b.n < 2)
        p = np.where(short, np.nan, 2 * stats.t.sf(np.abs(t), df))
        t_crit = np.where(short, np.nan, stats.t.ppf(0.975, df))
    return WelchArrays(diff=diff, se=se, p=p, df=df, t_crit=t_crit, call=calls(diff, p, rule))


def fast_calls(
    a: GroupStats, b: GroupStats, rule: ConclusionRule = DEFAULT_RULE
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """``(diff, se, df, call)`` of Welch's test without a p-value per element, calls exact.

    ``p < alpha`` is ``|t| > t_crit(df)``, and the critical t falls as df rises; over many
    perturbations of one gene df hardly moves, so ``|t|`` above the critical t of the smallest
    df is significant and below that of the largest df is not. Only the elements in between
    get their exact p (as :func:`welch`), so every call equals :func:`welch`'s.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        var_a, var_b = a.ss / (a.n - 1), b.ss / (b.n - 1)
        sa, sb = var_a / a.n, var_b / b.n
        se = np.sqrt(sa + sb)
        diff = a.mean - b.mean
        t = np.abs(diff / se)
        df = (sa + sb) ** 2 / (sa**2 / (a.n - 1) + sb**2 / (b.n - 1))
        short = (a.n < 2) | (b.n < 2) | ~np.isfinite(t) | ~np.isfinite(df)
    significant = np.zeros(np.shape(diff), dtype=bool)
    ok = ~short
    if ok.any():
        q = 1 - rule.alpha / 2
        t_high = float(stats.t.ppf(q, float(np.min(df[ok]))))  # the strictest threshold
        t_low = float(stats.t.ppf(q, float(np.max(df[ok]))))
        significant = ok & (t > t_high)
        unsure = ok & (t >= t_low) & (t <= t_high)
        if unsure.any():
            p = 2 * stats.t.sf(t[unsure], df[unsure])
            significant[unsure] = p < rule.alpha
    up = significant & (diff >= rule.min_log2fc)
    down = significant & (diff <= -rule.min_log2fc)
    return diff, se, df, np.where(up, UP, np.where(down, DOWN, NONE)).astype(int)


def margin(after: WelchArrays, base_call: np.ndarray, rule: ConclusionRule) -> np.ndarray:
    """How far each result is from changing ``base_call``, in standard errors (≤ 0: changed).

    A call up (or down) holds while the fold change is past the rule's line and significant:
    the margin is the smaller of (distance past the line) / SE and t minus the critical t. A
    "none" call changes (towards the side of its fold change) once both hold, so its margin
    is the larger of the two shortfalls. Used to rank which sample to set aside next, never
    to decide a call: every call comes from :func:`calls`.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        t_rule = stats.t.ppf(1 - rule.alpha / 2, after.df)
        side = np.where(base_call == NONE, np.where(after.diff < 0, -1.0, 1.0), base_call)
        towards = side * after.diff
        past_line = (towards - rule.min_log2fc) / after.se
        past_t = towards / after.se - t_rule
        held = np.minimum(past_line, past_t)
        short = np.maximum(-past_line, -past_t)
        out = np.where(base_call == NONE, short, held)
    return np.where(np.isfinite(out), out, np.inf)


def _tile(s: GroupStats, shape: tuple[int, ...]) -> GroupStats:
    """The same per-gene statistics repeated for every row of a (rows, genes) perturbation."""
    return GroupStats(*(np.broadcast_to(v, shape) for v in (s.n, s.mean, s.ss)))


def _remove(s: GroupStats, x: np.ndarray, member: np.ndarray) -> GroupStats:
    """Statistics after taking ``x`` out where ``member``; unchanged elsewhere."""
    with np.errstate(divide="ignore", invalid="ignore"):
        n = s.n - 1
        mean = s.mean - (x - s.mean) / n
        ss = np.maximum(s.ss - (x - s.mean) * (x - mean), 0.0)
    keep = ~member
    return GroupStats(
        n=np.where(keep, s.n, n),
        mean=np.where(keep, s.mean, mean),
        ss=np.where(keep, s.ss, ss),
    )


def _shift(s: GroupStats, x: np.ndarray, delta: np.ndarray, member: np.ndarray) -> GroupStats:
    """Statistics after ``x`` becomes ``x + delta`` where ``member``; unchanged elsewhere."""
    with np.errstate(divide="ignore", invalid="ignore"):
        mean = s.mean + delta / s.n
        ss = s.ss + 2 * delta * (x - s.mean) + delta**2 * (s.n - 1) / s.n
        ss = np.maximum(ss, 0.0)
    keep = ~member
    return GroupStats(
        n=np.broadcast_to(s.n, mean.shape),
        mean=np.where(keep, s.mean, mean),
        ss=np.where(keep, s.ss, ss),
    )


def _add(s: GroupStats, y: np.ndarray, joining: np.ndarray) -> GroupStats:
    """Statistics after ``y`` joins where ``joining``; unchanged elsewhere."""
    with np.errstate(divide="ignore", invalid="ignore"):
        n = s.n + 1
        mean = s.mean + (y - s.mean) / n
        ss = s.ss + (y - s.mean) * (y - mean)
    keep = ~joining
    return GroupStats(
        n=np.where(keep, s.n, n),
        mean=np.where(keep, s.mean, mean),
        ss=np.where(keep, s.ss, ss),
    )


@dataclass(frozen=True)
class Effect:
    """A perturbation's result for every (unit, gene): the new comparison and what changed."""

    after: WelchArrays
    base: WelchArrays
    touched: np.ndarray  # (unit, gene): the perturbation reaches this gene's comparison

    @property
    def d_log2fc(self) -> np.ndarray:
        """Change in the log2 fold change (0 where the gene's comparison is not touched)."""
        return np.where(self.touched, self.after.diff - self.base.diff, 0.0)

    @property
    def changed(self) -> np.ndarray:
        """True where the conclusion differs from the base conclusion."""
        return self.touched & (self.after.call != self.base.call)


@dataclass(frozen=True)
class FlipSet:
    """The smallest set of units found whose removal changes one gene's call.

    ``exact`` is True when no smaller set exists (sizes 1 and 2 are checked exhaustively);
    ``units`` is empty when no set of up to ``searched`` units changed it.
    """

    units: tuple[int, ...]
    exact: bool
    searched: int
    after: WelchArrays | None


class Comparison:
    """One comparison of every gene between two groups of units, ready for exact updates.

    Args:
        relative: Units x genes relative values (log2 target minus log2 normaliser).
        valid: Units x genes, True where the value enters the gene's comparison.
        in_a: Per unit, True for the first group (the high group, or group A).
        in_b: Per unit, True for the second group (the rest, or group B).
        rule: The conclusion rule.
        family: The study's comparisons when it has several (:class:`Family`); ``in_a`` and
            ``in_b`` must then be the traced comparison's groups. Every update moves the
            statistics of the unit's group, every comparison is recomputed and the traced
            call uses the corrected p-value. ``None``: one comparison, Welch's test.
    """

    def __init__(
        self,
        relative: np.ndarray,
        valid: np.ndarray,
        in_a: np.ndarray,
        in_b: np.ndarray,
        rule: ConclusionRule = DEFAULT_RULE,
        family: Family | None = None,
    ) -> None:
        relative = np.asarray(relative, dtype=float)
        valid = np.asarray(valid, dtype=bool) & ~np.isnan(relative)
        in_a, in_b = np.asarray(in_a, dtype=bool), np.asarray(in_b, dtype=bool)
        if np.any(in_a & in_b):
            raise ValueError("a unit cannot be in both groups")
        self.rule = rule
        self.family = family
        if family is None:
            masks = [in_a, in_b]
            self._ia, self._ib = 0, 1
        else:
            fa, fb = family.masks()
            if not (np.array_equal(fa, in_a) and np.array_equal(fb, in_b)):
                raise ValueError("the traced groups are not the family's traced comparison")
            masks = list(family.groups)
            self._ia, self._ib = family.pairs[family.chosen]
        self.x = np.where(valid, relative, 0.0)
        self.members = [valid & m[:, None] for m in masks]
        self.a, self.b = self.members[self._ia], self.members[self._ib]
        self.stats = [group_stats(relative, m) for m in self.members]
        self.stats_a, self.stats_b = self.stats[self._ia], self.stats[self._ib]
        self.base = self._test(self.stats, exact=True)

    def _test(self, stats_by_group: list[GroupStats], *, exact: bool = False) -> WelchArrays:
        """The traced comparison from every group's statistics (corrected with a family)."""
        if self.family is None:
            return welch(stats_by_group[self._ia], stats_by_group[self._ib], self.rule)
        return self.family.test(stats_by_group, self.rule, exact=exact)

    @property
    def used(self) -> np.ndarray:
        """Units x genes: the value enters the comparison (in either group)."""
        return self.a | self.b

    def leave_one_out(self) -> Effect:
        """Each unit set aside from each gene's comparison, one at a time."""
        shape = self.x.shape
        stats = [
            _remove(_tile(s, shape), self.x, m)
            for s, m in zip(self.stats, self.members, strict=True)
        ]
        return Effect(after=self._test(stats), base=self.base, touched=self.used)

    def without(self, rows: list[int] | tuple[int, ...], j: int) -> WelchArrays:
        """Gene ``j`` with the units ``rows`` set aside together (exact, sequential updates)."""
        stats = [_column_of(s, j) for s in self.stats]
        for i in rows:
            stats = [
                _remove(s, self.x[i, j], np.asarray(m[i, j]))
                for s, m in zip(stats, self.members, strict=True)
            ]
        return self._test(stats, exact=True)

    def pairs(self, j: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Every pair of the units used for gene ``j`` set aside together (calls only).

        Returns:
            ``(rows, diff, call)``: the used unit rows (``n``) and ``(n, n)`` arrays whose cell
            ``[u, v]`` is gene ``j`` without units ``rows[u]`` and ``rows[v]`` (the diagonal
            removes one unit only; only ``u < v`` are pairs). Calls are exact
            (:func:`fast_calls`, or every comparison and the correction with a family).
        """
        rows = np.flatnonzero(self.used[:, j])
        x = self.x[rows, j]
        shape = (len(rows), len(rows))
        col = np.broadcast_to(x[None, :], shape)
        diagonal = np.eye(len(rows), dtype=bool)  # the same unit twice is one removal
        two = []
        for s, m in zip(self.stats, self.members, strict=True):
            inside = m[rows, j]
            one = _remove(_repeat(s, j, len(rows)), x, inside)
            both = _remove(_column(one, shape), col, np.broadcast_to(inside[None, :], shape))
            two.append(_keep_where(both, _column(one, shape), diagonal))
        if self.family is None:
            diff, _, _, call = fast_calls(two[self._ia], two[self._ib], self.rule)
            return rows, diff, call
        after = self._test(two)
        return rows, after.diff, after.call

    def shift(self, delta: np.ndarray) -> Effect:
        """Each unit ``i`` alone moved by ``delta[i]`` on every gene it is used for."""
        d = np.broadcast_to(np.nan_to_num(np.asarray(delta, dtype=float))[:, None], self.x.shape)
        touched = self.used & (d != 0)
        everywhere = (np.any(self.members, axis=0) if self.family else self.used) & (d != 0)
        stats = [
            _shift(_tile(s, self.x.shape), self.x, d, m & everywhere)
            for s, m in zip(self.stats, self.members, strict=True)
        ]
        return Effect(after=self._test(stats), base=self.base, touched=touched)

    def bring_back(self, values: np.ndarray, to_a: np.ndarray, to_b: np.ndarray) -> Effect:
        """Each row ``j`` of ``values`` (a unit not used today) joining alone, in its group.

        Args:
            values: Rows x genes relative values the unit would have (NaN: still left out).
            to_a: Per row, True when the unit would join the first group.
            to_b: Per row, True when it would join the second group.
        """
        y = np.asarray(values, dtype=float)
        ok = ~np.isnan(y)
        join_a = ok & np.asarray(to_a, dtype=bool)[:, None]
        join_b = ok & np.asarray(to_b, dtype=bool)[:, None]
        filled = np.where(ok, y, 0.0)
        stats = []
        for g, s in enumerate(self.stats):
            tiled = _tile(s, y.shape)
            joining = join_a if g == self._ia else join_b if g == self._ib else None
            stats.append(tiled if joining is None else _add(tiled, filled, joining))
        return Effect(after=self._test(stats), base=self.base, touched=join_a | join_b)

    def evaluate(
        self, relative: np.ndarray, valid: np.ndarray, in_a: np.ndarray, in_b: np.ndarray
    ) -> WelchArrays:
        """Any other values and groups (several units changed at once), in full."""
        family = self.family
        if family is not None:
            fa, fb = family.masks()
            if not (np.array_equal(fa, in_a) and np.array_equal(fb, in_b)):
                family = None  # regrouped (a marker split): no family there
        return Comparison(relative, valid, in_a, in_b, self.rule, family).base

    def smallest_flip(self, j: int, loo: Effect, limit: int = 20) -> FlipSet:
        """The fewest units whose removal together changes gene ``j``'s call.

        One unit (every unit, from ``loo``) and two units (every pair) are checked
        exhaustively, so a set of one or two is the smallest there is. Beyond that the search
        is greedy: it sets aside, one at a time, the unit that moves the result furthest
        towards its line (:func:`margin`), up to ``limit`` units; the set it finds is then
        no smaller than three and no larger than its size.
        """
        base_call = self.base.call[j]
        used = self.used[:, j]
        single = np.flatnonzero(used & loo.changed[:, j])
        if single.size:
            m = margin(loo.after, self.base.call, self.rule)[single, j]
            i = int(single[np.argmin(m)])
            return FlipSet((i,), True, 1, self.without((i,), j))
        if used.sum() < 3:
            return FlipSet((), True, int(used.sum()), None)
        rows, _, call = self.pairs(j)
        flips = np.triu(call != base_call, k=1)
        if flips.any():
            u, v = np.nonzero(flips)
            after = [
                self.without((int(rows[a]), int(rows[b])), j) for a, b in zip(u, v, strict=True)
            ]
            m = [float(margin(w, np.asarray(base_call), self.rule)) for w in after]
            best = int(np.argmin(m))  # the pair that changes it most decisively
            chosen = (int(rows[u[best]]), int(rows[v[best]]))
            return FlipSet(chosen, True, 2, after[best])
        return self._greedy(j, limit)

    def _greedy(self, j: int, limit: int) -> FlipSet:
        base_call = np.asarray(self.base.call[j])
        stats = [_column_of(s, j) for s in self.stats]
        left = self.used[:, j].copy()
        chosen: list[int] = []
        steps = min(limit, int(left.sum()) - 4)
        for _ in range(max(steps, 0)):
            rows = np.flatnonzero(left)
            x = self.x[rows, j]
            trial = [
                _remove(
                    GroupStats(*(np.full(len(rows), v) for v in (s.n, s.mean, s.ss))), x, m[rows, j]
                )
                for s, m in zip(stats, self.members, strict=True)
            ]
            after = self._test(trial)
            m = margin(after, np.full(len(rows), base_call), self.rule)
            pick = int(np.argmin(np.where(after.call != base_call, -np.inf, m)))
            i = int(rows[pick])
            chosen.append(i)
            left[i] = False
            stats = [
                _remove(s, self.x[i, j], np.asarray(mm[i, j]))
                for s, mm in zip(stats, self.members, strict=True)
            ]
            if after.call[pick] != base_call:
                return FlipSet(tuple(chosen), False, len(chosen), self.without(tuple(chosen), j))
        return FlipSet((), False, len(chosen), None)


def _column_of(s: GroupStats, j: int) -> GroupStats:
    """Gene ``j``'s statistics of one group (0-d arrays)."""
    return GroupStats(*(np.asarray(v[j], dtype=float) for v in (s.n, s.mean, s.ss)))


def _repeat(s: GroupStats, j: int, n: int) -> GroupStats:
    """Gene ``j``'s statistics repeated ``n`` times (one copy per unit to remove)."""
    return GroupStats(*(np.full(n, np.asarray(v)[j], dtype=float) for v in (s.n, s.mean, s.ss)))


def _column(s: GroupStats, shape: tuple[int, int]) -> GroupStats:
    """Per-row statistics (one per first removed unit) repeated along the second axis."""
    return GroupStats(
        *(np.broadcast_to(np.asarray(v)[:, None], shape) for v in (s.n, s.mean, s.ss))
    )


def _keep_where(s: GroupStats, other: GroupStats, where: np.ndarray) -> GroupStats:
    return GroupStats(
        n=np.where(where, other.n, s.n),
        mean=np.where(where, other.mean, s.mean),
        ss=np.where(where, other.ss, s.ss),
    )


def robust_z(values: np.ndarray, axis: int = 0) -> np.ndarray:
    """``(x - median) / (1.4826 * MAD)`` along ``axis``, ignoring NaN (NaN where MAD is 0)."""
    x = np.asarray(values, dtype=float)
    with warnings.catch_warnings(), np.errstate(invalid="ignore", divide="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)  # an all-NaN column has no median
        median = np.nanmedian(x, axis=axis, keepdims=True)
        mad = 1.4826 * np.nanmedian(np.abs(x - median), axis=axis, keepdims=True)
        z = (x - median) / mad
    return np.where(mad > 0, z, np.nan)


# ---- several comparisons -------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class Family:
    """A study's comparisons as pairs of groups over the units, and how they are corrected.

    ``groups`` is groups x units (a unit is in at most one group), ``pairs`` each comparison's
    ``(group a, group b)``, ``chosen`` the traced comparison's position in ``pairs``,
    ``correction`` ``holm``, ``dunnett``, ``tukey`` or ``none`` and ``control`` the control
    group's position (Dunnett). ``correction`` ``none`` with Welch tests is the uncorrected study.
    """

    groups: np.ndarray
    pairs: tuple[tuple[int, int], ...]
    chosen: int
    correction: str = "none"
    control: int | None = None

    @property
    def pooled(self) -> bool:
        """Dunnett and Tukey pool one variance per gene over every group."""
        return self.correction in ("dunnett", "tukey")

    def masks(self) -> tuple[np.ndarray, np.ndarray]:
        """The traced comparison's ``(in_a, in_b)`` unit masks."""
        a, b = self.pairs[self.chosen]
        return self.groups[a], self.groups[b]

    def test(
        self, stats_by_group: list[GroupStats], rule: ConclusionRule, *, exact: bool = True
    ) -> WelchArrays:
        """Every comparison from the groups' statistics; the traced one, with its corrected call.

        Works on any common shape of the statistics (genes, or perturbations x genes). With
        ``exact=False`` (many perturbations at once) Dunnett's and Tukey's integrals are
        computed only where the call depends on them: where the change is past the rule's line
        and ``p <= alpha < m p`` (the corrected p lies between the uncorrected one and
        Bonferroni's ``m p``); elsewhere ``p_adj`` holds the bound that decides the call, and
        the calls are exact everywhere.
        """
        if self.pooled:
            tests = self._pooled(stats_by_group, rule)
        else:
            tests = [welch(stats_by_group[a], stats_by_group[b], rule) for a, b in self.pairs]
        mine = tests[self.chosen]
        if self.correction == "none" or len(tests) < 2 and not self.pooled:
            return mine
        p_adj = self._adjusted(tests, stats_by_group, None if exact else rule)
        call = calls(mine.diff, p_adj, rule)
        return WelchArrays(mine.diff, mine.se, mine.p, mine.df, mine.t_crit, call, p_adj)

    def _pooled(self, stats_by_group: list[GroupStats], rule: ConclusionRule) -> list[WelchArrays]:
        shape = np.broadcast_shapes(*(np.shape(s.mean) for s in stats_by_group))
        ss = np.zeros(shape)
        dof = np.zeros(shape)
        for s in stats_by_group:
            n = np.broadcast_to(s.n, shape)
            ok = n >= 2
            ss = ss + np.where(ok, np.broadcast_to(s.ss, shape), 0.0)
            dof = dof + np.where(ok, n - 1.0, 0.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            var = np.where(dof > 0, ss / dof, np.nan)
        out = []
        for a, b in self.pairs:
            sa, sb = stats_by_group[a], stats_by_group[b]
            with np.errstate(divide="ignore", invalid="ignore"):
                se = np.sqrt(var * (1 / sa.n + 1 / sb.n))
                diff = sa.mean - sb.mean
                t = diff / se
                short = (sa.n < 2) | (sb.n < 2) | ~(dof > 0) | ~np.isfinite(t)
                p = np.where(short, np.nan, 2 * stats.t.sf(np.abs(t), dof))
                t_crit = np.where(short, np.nan, stats.t.ppf(0.975, dof))
            diff = np.broadcast_to(diff, shape)
            out.append(
                WelchArrays(diff, np.broadcast_to(se, shape), p, dof, t_crit, calls(diff, p, rule))
            )
        return out

    def _adjusted(
        self,
        tests: list[WelchArrays],
        stats_by_group: list[GroupStats],
        calls_only: ConclusionRule | None = None,
    ) -> np.ndarray:
        """The traced comparison's corrected p (any shape; NaN where it is not tested)."""
        from qpilot.qpcr.contrast import holm
        from qpilot.qpcr.multiplicity import dunnett_adjusted, tukey_adjusted

        shape = np.shape(tests[self.chosen].p)
        p = np.stack([np.broadcast_to(t.p, shape) for t in tests])
        if self.correction == "holm":
            return holm(p, axis=0)[self.chosen]
        flat = p.reshape(len(tests), -1)
        with np.errstate(divide="ignore", invalid="ignore"):
            t = np.stack([np.broadcast_to(x.diff / x.se, shape) for x in tests])
        t = np.where(np.isfinite(flat), t.reshape(len(tests), -1), np.nan)
        df = np.broadcast_to(tests[self.chosen].df, shape).reshape(-1)
        n = [np.broadcast_to(s.n, shape).reshape(-1) for s in stats_by_group]
        mine = flat[self.chosen]
        need = np.isfinite(mine)
        out = np.full(mine.shape, np.nan)
        if calls_only is not None:  # decide the call from the bounds where they suffice
            m = np.isfinite(flat).sum(axis=0)
            upper = np.minimum(1.0, m * mine)
            diff = np.broadcast_to(tests[self.chosen].diff, shape).reshape(-1)
            with np.errstate(invalid="ignore"):
                past = np.abs(diff) >= calls_only.min_log2fc
                sure_yes = past & (upper < calls_only.alpha)
                sure_no = ~past | (mine >= calls_only.alpha)
            out = np.where(need & sure_yes, upper, np.where(need & sure_no, mine, np.nan))
            need = need & ~sure_yes & ~sure_no
        cols = np.flatnonzero(need)
        if len(cols):
            if self.correction == "dunnett":
                n_treated = np.stack([n[a][cols] for a, _ in self.pairs])
                n0 = n[self.control][cols]  # type: ignore[index]
                exact = dunnett_adjusted(t[:, cols], n_treated, n0, df[cols])
            else:
                k = sum((x[cols] >= 2).astype(float) for x in n)
                exact = tukey_adjusted(t[:, cols], k, df[cols])
            out[cols] = exact[self.chosen]
        return out.reshape(shape)
