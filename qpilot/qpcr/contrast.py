"""Welch t-test: is a gene higher in one group than the other, by how much, how sure?

For one gene and one set of analysis choices, this compares the relative quantities
(:func:`qpilot.qpcr.quant.relative`) of the high group with the rest using Welch's t-test on the
log2 scale (no equal-variance assumption) and reports:

* the fold change ``fc = 2**log2fc`` (3.6 means "3.6 times higher"; 0.07 means "about 14 times
  lower") with a 95 % confidence interval on the same scale;
* the p-value; and
* a plain conclusion under a rule that is printed wherever the result is shown:
  **up** if p < 0.05 and the change is at least two-fold, **down** if p < 0.05 and at least
  two-fold lower, otherwise **none** ("no call").

A study with several comparisons (:class:`~qpilot.schemas_studio.ComparisonPlan`) uses the same
test for each, and corrects for doing several: :func:`holm` adjusts one gene's p-values across
its comparisons (Holm's step-down method; a call then needs the *corrected* p below the
threshold), and :func:`bh` gives each comparison's Benjamini-Hochberg q-values across genes (the
expected share of false findings among the genes called at that q; shown, never used for a
call). A paired design (``pair_by``) compares the groups within each pair instead:
:func:`paired_t` is the one-sample t-test of the within-pair differences of log2 relative
quantity (ΔΔCq within the pair), with n = the number of complete pairs.

Not claimed: no mixed model, no plate effect (the demo has one gene per plate), no prediction
interval, no simultaneous confidence intervals (each interval is for its comparison alone).
The arithmetic follows the validation oracle.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Sequence
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy import stats

from qpilot.qpcr.quant import Undetermined, relative
from qpilot.schemas import Conclusion, ContrastResult


@dataclass(frozen=True)
class ConclusionRule:
    """When a fold change counts as a finding. Shown to the user, never hidden."""

    alpha: float = 0.05
    min_log2fc: float = 1.0  # one doubling = two-fold

    def as_dict(self) -> dict[str, float]:
        """For ``StudyResult.conclusion_rule``."""
        return asdict(self)

    def describe(self) -> str:
        """The rule in words, for cards, README and methods text."""
        return (
            f"up or down only if p < {self.alpha:g} and the change is at least "
            f"{2**self.min_log2fc:g}-fold; otherwise no call"
        )


DEFAULT_RULE = ConclusionRule()


@dataclass(frozen=True)
class Welch:
    """Welch t-test on two samples: difference of means, its SE, t, p and the 97.5 % t quantile."""

    diff: float
    se: float
    t: float
    p: float
    t_crit: float
    df: float


def welch(a: Sequence[float], b: Sequence[float]) -> Welch:
    """Welch's unequal-variance t-test of ``mean(a) - mean(b)``; each side needs two values."""
    if len(a) < 2 or len(b) < 2:
        raise ValueError("each group needs at least two values")
    a_series, b_series = pd.Series(a, dtype=float), pd.Series(b, dtype=float)
    var_a, var_b = a_series.var(ddof=1) / len(a), b_series.var(ddof=1) / len(b)
    se = math.sqrt(var_a + var_b)
    diff = float(a_series.mean() - b_series.mean())
    t = diff / se
    df = (var_a + var_b) ** 2 / (var_a**2 / (len(a) - 1) + var_b**2 / (len(b) - 1))
    return Welch(
        diff=diff,
        se=se,
        t=t,
        p=float(2 * stats.t.sf(abs(t), df)),
        t_crit=float(stats.t.ppf(0.975, df)),
        df=df,
    )


def paired_t(differences: Sequence[float]) -> Welch:
    """Paired t-test: the one-sample t-test of within-pair differences against zero.

    ``diff`` is the mean difference, ``se`` its standard error (SD / sqrt(n)), ``df = n - 1``;
    the same fields as :func:`welch` so a paired comparison is reported the same way. It needs
    at least two pairs.
    """
    values = pd.Series(differences, dtype=float)
    if len(values) < 2:
        raise ValueError("a paired test needs at least two pairs")
    n = len(values)
    diff = float(values.mean())
    se = float(values.std(ddof=1)) / math.sqrt(n)
    t = diff / se
    df = n - 1
    return Welch(
        diff=diff,
        se=se,
        t=t,
        p=float(2 * stats.t.sf(abs(t), df)),
        t_crit=float(stats.t.ppf(0.975, df)),
        df=float(df),
    )


def holm(p: np.ndarray | Sequence[float], axis: int = 0) -> np.ndarray:
    """Holm's step-down adjusted p-values along ``axis`` (one family per slice).

    A NaN p-value (no test) is not part of its family and stays NaN; ``m`` is the number of
    finite p-values in the family. The adjusted value of the i-th smallest of m is
    ``max_{j <= i} min(1, (m - j + 1) * p_(j))``, as in ``statsmodels``' ``holm``.
    """
    values = np.asarray(p, dtype=float)
    moved = np.moveaxis(values, axis, 0)
    finite = np.isfinite(moved)
    m = finite.sum(axis=0)
    order = np.argsort(np.where(finite, moved, np.inf), axis=0, kind="stable")
    ranked = np.take_along_axis(moved, order, axis=0)
    rank = np.arange(moved.shape[0]).reshape((-1,) + (1,) * (moved.ndim - 1))
    with np.errstate(invalid="ignore"):
        scaled = np.minimum(1.0, (m - rank) * ranked)
    scaled = np.where(np.isfinite(ranked), scaled, -np.inf)
    stepped = np.maximum.accumulate(scaled, axis=0)
    stepped = np.where(np.isfinite(ranked), stepped, np.nan)
    out = np.empty_like(moved)
    np.put_along_axis(out, order, stepped, axis=0)
    return np.moveaxis(out, 0, axis)


def bh(p: np.ndarray | Sequence[float]) -> np.ndarray:
    """Benjamini-Hochberg q-values of one family (1-D); NaN stays NaN and is not counted.

    The q-value of the i-th smallest of m finite p-values is
    ``min_{j >= i} min(1, m * p_(j) / j)``, as in ``statsmodels``' ``fdr_bh``.
    """
    values = np.asarray(p, dtype=float)
    out = np.full(values.shape, np.nan)
    finite = np.flatnonzero(np.isfinite(values))
    if not len(finite):
        return out
    order = finite[np.argsort(values[finite], kind="stable")]
    m = len(order)
    scaled = values[order] * m / np.arange(1, m + 1)
    out[order] = np.minimum(1.0, np.minimum.accumulate(scaled[::-1])[::-1])
    return out


def welch_anova(groups: Sequence[tuple[np.ndarray, ...]]) -> tuple[np.ndarray, ...]:
    """Welch's one-way ANOVA (unequal variances) from per-group ``(n, mean, var)`` arrays.

    Vectorised over the arrays' common shape (genes). Returns ``(F, df1, df2, p)``; NaN where
    fewer than two groups have two values, or a group's variance is zero. Equal to
    ``scipy.stats.f_oneway(..., equal_var=False)`` (Welch 1951).
    """
    n = np.array([g[0] for g in groups], dtype=float)
    mean = np.array([g[1] for g in groups], dtype=float)
    var = np.array([g[2] for g in groups], dtype=float)
    used = n >= 2
    k = used.sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        w = np.where(used, n / var, 0.0)
        total = w.sum(axis=0)
        centre = np.where(used, w * mean, 0.0).sum(axis=0) / total
        between = np.where(used, w * (mean - centre) ** 2, 0.0).sum(axis=0) / (k - 1)
        spread = np.where(used, (1 - w / total) ** 2 / (n - 1), 0.0).sum(axis=0)
        f = between / (1 + 2 * (k - 2) / (k**2 - 1) * spread)
        df2 = (k**2 - 1) / (3 * spread)
        df1 = k - 1.0
        p = stats.f.sf(f, df1, df2)
    bad = (k < 2) | ~np.isfinite(f) | ~np.isfinite(df2)
    nan = np.full(np.shape(f), np.nan)
    return (
        np.where(bad, nan, f),
        np.where(bad, nan, df1),
        np.where(bad, nan, df2),
        np.where(bad, nan, p),
    )


CORRECTION_WORDS = {
    "holm": "Holm's correction across each gene's comparisons",
    "dunnett": "Dunnett's correction for comparing each group with the control",
    "tukey": "Tukey's correction for comparing every pair of groups (Tukey-Kramer)",
    "none": "no correction for several comparisons",
}
TEST_WORDS = {
    "welch": "Welch's t-test on log2 relative quantities (no equal-variance assumption)",
    "paired_t": "a paired t-test on the within-pair differences of log2 relative quantity",
    "pooled_t": "a t-test on log2 relative quantities with one variance pooled over every "
    "compared group (equal variances assumed)",
}
#: Corrections whose call uses a corrected p-value (every one but "none").
CORRECTED = ("holm", "dunnett", "tukey")
#: A correction's short name, as a label next to the corrected p ("corrected p (Holm)").
CORRECTION_NAMES = {"holm": "Holm", "dunnett": "Dunnett", "tukey": "Tukey"}


def describe_rule(rule: ConclusionRule, correction: str = "none") -> str:
    """The calling rule in words; with a correction the call needs the corrected p."""
    if correction in CORRECTED:
        return (
            f"up or down only if the corrected p < {rule.alpha:g} and the change is at least "
            f"{2**rule.min_log2fc:g}-fold; otherwise no call"
        )
    return rule.describe()


def conclude(log2fc: float, p: float, rule: ConclusionRule = DEFAULT_RULE) -> Conclusion:
    """Map a log2 fold change and p-value to up / down / none under ``rule``."""
    if p < rule.alpha and log2fc >= rule.min_log2fc:
        return "up"
    if p < rule.alpha and log2fc <= -rule.min_log2fc:
        return "down"
    return "none"


def welch_contrast(
    matrix: pd.DataFrame,
    target: str,
    refs: Sequence[str],
    undetermined: Undetermined,
    high: Collection[str],
    rest: Collection[str],
    rule: ConclusionRule = DEFAULT_RULE,
) -> ContrastResult:
    """Compare ``target`` between the high group and the rest under one set of choices.

    Args:
        matrix: Samples x genes ``log2(n0)`` from :func:`qpilot.qpcr.quant.log2_matrix`.
        target: The gene to compare.
        refs: The control genes to normalise by.
        undetermined: ``"drop"`` or ``"cap"`` for wells that never amplified.
        high: Sample names in the high group (fixed from the primary control genes).
        rest: Sample names in the comparison group.
        rule: The conclusion rule.

    Returns:
        A :class:`ContrastResult` with fold change, 95 % CI, p, t, group sizes and conclusion.
    """
    rel = relative(matrix, target, refs, undetermined)
    a = rel[rel.index.isin(high)]
    b = rel[rel.index.isin(rest)]
    w = welch(a.to_numpy(), b.to_numpy())
    return ContrastResult(
        target=target,
        log2fc=w.diff,
        fc=2**w.diff,
        ci=(2 ** (w.diff - w.t_crit * w.se), 2 ** (w.diff + w.t_crit * w.se)),
        p=w.p,
        t=w.t,
        n_hi=len(a),
        n_lo=len(b),
        conclusion=conclude(w.diff, w.p, rule),
    )


def standard_error(result: ContrastResult) -> float:
    """Recover the standard error of log2fc from a result (used for MDE and precision checks)."""
    return abs(result.log2fc / result.t) if result.t else float("nan")
