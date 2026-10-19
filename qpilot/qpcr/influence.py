"""Closed-form influence on every group comparison: a unit set aside, shifted or brought back.

Trace (:mod:`qpilot.qpcr.trace`) asks, for every place it might point at, "what happens to each
conclusion if this value were different?". Each answer here is an exact update of the group
statistics of one comparison (Welch on the log2 scale, as :mod:`qpilot.qpcr.space` computes it),
so nothing is re-run from scratch and nothing is approximated:

* :meth:`Comparison.leave_one_out` sets one unit aside from one gene's comparison, for every
  unit and gene at once;
* :meth:`Comparison.shift` moves one unit's values on every gene by the same amount. That is
  what happens when one of the unit's reference wells is read as the unit's other references
  predict: the normaliser (the mean of ``k`` reference values) moves by the well's deviation
  divided by ``k``, and every relative value of the unit moves the other way;
* :meth:`Comparison.bring_back` adds one unit that is in no comparison today (for example
  because one reference well is empty) with the values it would have;
* :meth:`Comparison.evaluate` re-evaluates any other set of values and groups in full.

Group statistics are kept as ``(n, mean, sum of squared deviations)`` and updated with the
numerically stable one-point formulas (Welford), so "this unit set aside" equals the
comparison computed without it to rounding error; the tests check that against
:func:`qpilot.qpcr.contrast.welch`. The base comparison uses the same arithmetic as
:meth:`qpilot.qpcr.space.QpcrSpace.evaluate`, bit for bit.

The maths mirrors the simulator's ``qsim.influence`` (closed-form Welch from group sums). It is
written again here because the engine never imports the simulator. These are perturbations of
the observed data and are labelled as such; nothing is ever written back into a measured value.
Deterministic; no model call.
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
    t_crit: np.ndarray
    call: np.ndarray

    def half_width(self) -> np.ndarray:
        """Half the width of the 95 % confidence interval of the log2 fold change."""
        return self.t_crit * self.se


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
    return WelchArrays(diff=diff, se=se, p=p, t_crit=t_crit, call=calls(diff, p, rule))


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


def robust_z(values: np.ndarray, axis: int = 0) -> np.ndarray:
    """``(x - median) / (1.4826 * MAD)`` along ``axis``, ignoring NaN (NaN where MAD is 0)."""
    x = np.asarray(values, dtype=float)
    with warnings.catch_warnings(), np.errstate(invalid="ignore", divide="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)  # an all-NaN column has no median
        median = np.nanmedian(x, axis=axis, keepdims=True)
        mad = 1.4826 * np.nanmedian(np.abs(x - median), axis=axis, keepdims=True)
        z = (x - median) / mad
    return np.where(mad > 0, z, np.nan)
