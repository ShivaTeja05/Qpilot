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

Not claimed: no mixed model, no plate effect (the demo has one gene per plate), no prediction
interval, no multiple-testing correction. The arithmetic follows the validation oracle.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Sequence
from dataclasses import asdict, dataclass

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
