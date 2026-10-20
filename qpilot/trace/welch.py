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

    def half_width(self) -> np.ndarray:
        """Half the width of the 95 % confidence interval of the log2 fold change."""
        return self.t_crit * self.se

    def row(self, i: int) -> WelchArrays:
        """One row of a (perturbations x genes) result."""
        return WelchArrays(*(np.asarray(v)[i] for v in self.__dict__.values()))


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
    """

    def __init__(
        self,
        relative: np.ndarray,
        valid: np.ndarray,
        in_a: np.ndarray,
        in_b: np.ndarray,
        rule: ConclusionRule = DEFAULT_RULE,
    ) -> None:
        relative = np.asarray(relative, dtype=float)
        valid = np.asarray(valid, dtype=bool) & ~np.isnan(relative)
        if np.any(np.asarray(in_a, dtype=bool) & np.asarray(in_b, dtype=bool)):
            raise ValueError("a unit cannot be in both groups")
        self.rule = rule
        self.x = np.where(valid, relative, 0.0)
        self.a = valid & np.asarray(in_a, dtype=bool)[:, None]
        self.b = valid & np.asarray(in_b, dtype=bool)[:, None]
        self.stats_a = group_stats(relative, self.a)
        self.stats_b = group_stats(relative, self.b)
        self.base = welch(self.stats_a, self.stats_b, rule)

    @property
    def used(self) -> np.ndarray:
        """Units x genes: the value enters the comparison (in either group)."""
        return self.a | self.b

    def leave_one_out(self) -> Effect:
        """Each unit set aside from each gene's comparison, one at a time."""
        a = _remove(_tile(self.stats_a, self.x.shape), self.x, self.a)
        b = _remove(_tile(self.stats_b, self.x.shape), self.x, self.b)
        return Effect(after=welch(a, b, self.rule), base=self.base, touched=self.used)

    def without(self, rows: list[int] | tuple[int, ...], j: int) -> WelchArrays:
        """Gene ``j`` with the units ``rows`` set aside together (exact, sequential updates)."""
        a = GroupStats(*(np.asarray(v[j], dtype=float) for v in self.stats_a.__dict__.values()))
        b = GroupStats(*(np.asarray(v[j], dtype=float) for v in self.stats_b.__dict__.values()))
        for i in rows:
            a = _remove(a, self.x[i, j], np.asarray(self.a[i, j]))
            b = _remove(b, self.x[i, j], np.asarray(self.b[i, j]))
        return welch(a, b, self.rule)

    def pairs(self, j: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Every pair of the units used for gene ``j`` set aside together (calls only).

        Returns:
            ``(rows, diff, call)``: the used unit rows (``n``) and ``(n, n)`` arrays whose cell
            ``[u, v]`` is gene ``j`` without units ``rows[u]`` and ``rows[v]`` (the diagonal
            removes one unit only; only ``u < v`` are pairs). Calls are exact
            (:func:`fast_calls`).
        """
        rows = np.flatnonzero(self.used[:, j])
        x = self.x[rows, j]
        in_a = self.a[rows, j]
        in_b = self.b[rows, j]
        sa = _repeat(self.stats_a, j, len(rows))
        sb = _repeat(self.stats_b, j, len(rows))
        one_a, one_b = _remove(sa, x, in_a), _remove(sb, x, in_b)
        shape = (len(rows), len(rows))
        col = np.broadcast_to(x[None, :], shape)
        two_a = _remove(_column(one_a, shape), col, np.broadcast_to(in_a[None, :], shape))
        two_b = _remove(_column(one_b, shape), col, np.broadcast_to(in_b[None, :], shape))
        diagonal = np.eye(len(rows), dtype=bool)  # the same unit twice is one removal
        two_a = _keep_where(two_a, _column(one_a, shape), diagonal)
        two_b = _keep_where(two_b, _column(one_b, shape), diagonal)
        diff, _, _, call = fast_calls(two_a, two_b, self.rule)
        return rows, diff, call

    def shift(self, delta: np.ndarray) -> Effect:
        """Each unit ``i`` alone moved by ``delta[i]`` on every gene it is used for."""
        d = np.broadcast_to(np.nan_to_num(np.asarray(delta, dtype=float))[:, None], self.x.shape)
        touched = self.used & (d != 0)
        a = _shift(_tile(self.stats_a, self.x.shape), self.x, d, self.a & touched)
        b = _shift(_tile(self.stats_b, self.x.shape), self.x, d, self.b & touched)
        return Effect(after=welch(a, b, self.rule), base=self.base, touched=touched)

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
        a = _add(_tile(self.stats_a, y.shape), filled, join_a)
        b = _add(_tile(self.stats_b, y.shape), filled, join_b)
        return Effect(after=welch(a, b, self.rule), base=self.base, touched=join_a | join_b)

    def evaluate(
        self, relative: np.ndarray, valid: np.ndarray, in_a: np.ndarray, in_b: np.ndarray
    ) -> WelchArrays:
        """Any other values and groups (several units changed at once), in full."""
        return Comparison(relative, valid, in_a, in_b, self.rule).base

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
        a = GroupStats(*(np.asarray(v[j], dtype=float) for v in self.stats_a.__dict__.values()))
        b = GroupStats(*(np.asarray(v[j], dtype=float) for v in self.stats_b.__dict__.values()))
        left = self.used[:, j].copy()
        chosen: list[int] = []
        steps = min(limit, int(left.sum()) - 4)
        for _ in range(max(steps, 0)):
            rows = np.flatnonzero(left)
            x = self.x[rows, j]
            in_a, in_b = self.a[rows, j], self.b[rows, j]
            ta = _remove(GroupStats(*(np.full(len(rows), v) for v in (a.n, a.mean, a.ss))), x, in_a)
            tb = _remove(GroupStats(*(np.full(len(rows), v) for v in (b.n, b.mean, b.ss))), x, in_b)
            after = welch(ta, tb, self.rule)
            m = margin(after, np.full(len(rows), base_call), self.rule)
            pick = int(np.argmin(np.where(after.call != base_call, -np.inf, m)))
            i = int(rows[pick])
            chosen.append(i)
            left[i] = False
            a = _remove(a, self.x[i, j], np.asarray(self.a[i, j]))
            b = _remove(b, self.x[i, j], np.asarray(self.b[i, j]))
            if after.call[pick] != base_call:
                return FlipSet(tuple(chosen), False, len(chosen), self.without(tuple(chosen), j))
        return FlipSet((), False, len(chosen), None)


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
