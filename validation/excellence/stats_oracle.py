"""Group comparisons from first principles: Welch, paired t, Holm, BH, Welch ANOVA, Dunnett, Tukey.

Written from the papers and textbooks, element by element (loops, not qPilot's vectorised
arrays), so a shared mistake is unlikely:

* Welch BL (1947) Biometrika 34:28-35: ``t = (mean_a - mean_b) / sqrt(s_a^2/n_a + s_b^2/n_b)``
  with the Welch-Satterthwaite degrees of freedom.
* The paired t-test: the one-sample t-test of the within-pair differences, ``df = n - 1``.
* Holm S (1979) Scand J Stat 6:65-70: step-down, ``max_{j<=i} min(1, (m - j + 1) p_(j))``.
* Benjamini Y, Hochberg Y (1995) J R Stat Soc B 57:289-300: step-up,
  ``min_{j>=i} min(1, m p_(j) / j)``.
* Welch BL (1951) Biometrika 38:330-336, the one-way ANOVA without equal variances.
* Dunnett CW (1955) J Am Stat Assoc 50:1096-1121: many-to-one, single step, two-sided. The
  probability that every ``|T_j|`` stays below ``c`` is integrated here by adaptive quadrature
  (``scipy.integrate.quad``) over the shared normal term and the pooled SD, a different numerical
  route from qPilot's fixed Gauss rules.
* Tukey JW (1953) / Kramer CY (1956): all pairs, ``P(Q_{k,df} >= |t| sqrt 2)`` with ``Q`` the
  studentized range (``scipy.stats.studentized_range``).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

import numpy as np
from scipy import integrate, special, stats


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _var(values: Sequence[float]) -> float:
    m = _mean(values)
    return sum((v - m) ** 2 for v in values) / (len(values) - 1)


def welch(a: Sequence[float], b: Sequence[float]) -> dict[str, float]:
    """Welch's t-test of ``mean(a) - mean(b)``: diff, se, t, df, p and the 95 % CI half-width."""
    va, vb = _var(a) / len(a), _var(b) / len(b)
    se = math.sqrt(va + vb)
    diff = _mean(a) - _mean(b)
    df = (va + vb) ** 2 / (va**2 / (len(a) - 1) + vb**2 / (len(b) - 1))
    t = diff / se
    return {
        "diff": diff,
        "se": se,
        "t": t,
        "df": df,
        "p": 2 * stats.t.sf(abs(t), df),
        "half_ci": stats.t.ppf(0.975, df) * se,
    }


def paired(differences: Sequence[float]) -> dict[str, float]:
    """The paired t-test from the within-pair differences."""
    n = len(differences)
    diff = _mean(differences)
    se = math.sqrt(_var(differences) / n)
    t = diff / se
    return {"diff": diff, "se": se, "t": t, "df": n - 1.0, "p": 2 * stats.t.sf(abs(t), n - 1)}


def holm(p: Sequence[float]) -> list[float]:
    """Holm's adjusted p-values of one family (NaN entries are not part of it and stay NaN)."""
    idx = [i for i, v in enumerate(p) if math.isfinite(v)]
    order = sorted(idx, key=lambda i: (p[i], i))
    m = len(order)
    out = [math.nan] * len(p)
    running = 0.0
    for rank, i in enumerate(order, start=1):
        running = max(running, min(1.0, (m - rank + 1) * p[i]))
        out[i] = running
    return out


def bh(p: Sequence[float]) -> list[float]:
    """Benjamini-Hochberg q-values of one family (NaN entries are left out and stay NaN)."""
    idx = [i for i, v in enumerate(p) if math.isfinite(v)]
    order = sorted(idx, key=lambda i: (p[i], i))
    m = len(order)
    out = [math.nan] * len(p)
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, min(1.0, m * p[i] / rank))
        out[i] = running
    return out


def welch_anova(groups: Sequence[Sequence[float]]) -> dict[str, float]:
    """Welch's one-way ANOVA (Welch 1951) over groups with at least two values each."""
    used = [g for g in groups if len(g) >= 2]
    k = len(used)
    w = [len(g) / _var(g) for g in used]
    total = sum(w)
    centre = sum(wi * _mean(g) for wi, g in zip(w, used, strict=True)) / total
    between = sum(wi * (_mean(g) - centre) ** 2 for wi, g in zip(w, used, strict=True)) / (k - 1)
    lam = sum((1 - wi / total) ** 2 / (len(g) - 1) for wi, g in zip(w, used, strict=True))
    f = between / (1 + 2 * (k - 2) / (k**2 - 1) * lam)
    df2 = (k**2 - 1) / (3 * lam)
    return {"f": f, "df1": k - 1.0, "df2": df2, "p": stats.f.sf(f, k - 1, df2), "k": k}


def pooled_variance(groups: Mapping[str, Sequence[float]]) -> tuple[float, float]:
    """One variance pooled over every group with a value, and its ``df = N - G``."""
    ss = sum(sum((v - _mean(g)) ** 2 for v in g) for g in groups.values() if len(g) >= 1)
    df = sum(len(g) - 1 for g in groups.values() if len(g) >= 1)
    return ss / df, float(df)


def pooled_t(a: Sequence[float], b: Sequence[float], var: float, df: float) -> dict[str, float]:
    """A t-test of ``mean(a) - mean(b)`` with a variance pooled over every group of the plan."""
    se = math.sqrt(var * (1 / len(a) + 1 / len(b)))
    diff = _mean(a) - _mean(b)
    t = diff / se
    return {"diff": diff, "se": se, "t": t, "df": df, "p": 2 * stats.t.sf(abs(t), df)}


def _s_density(s: float, df: float) -> float:
    """Density of ``S = sqrt(chi2_df / df)``."""
    return 2 * df * s * stats.chi2.pdf(df * s * s, df)


def dunnett_adjusted(
    t: Sequence[float], n_treated: Sequence[int], n_control: int, df: float
) -> list[float]:
    """Dunnett's single-step two-sided adjusted p of each comparison with the control.

    ``P(max_j |T_j| >= |t_i|)`` with ``corr(T_i, T_j) = lambda_i lambda_j``,
    ``lambda_j = sqrt(n_j / (n_j + n_0))`` (Dunnett 1955), by nested adaptive quadrature.
    """
    lam = [math.sqrt(n / (n + n_control)) for n in n_treated]
    root = [math.sqrt(1 - x * x) for x in lam]

    def inside(c: float) -> float:
        def over_z(z: float, s: float) -> float:
            prod = 1.0
            for lj, rj in zip(lam, root, strict=True):
                prod *= special.ndtr((c * s - lj * z) / rj) - special.ndtr((-c * s - lj * z) / rj)
            return prod * math.exp(-z * z / 2) / math.sqrt(2 * math.pi)

        def over_s(s: float) -> float:
            value, _ = integrate.quad(over_z, -9, 9, args=(s,), epsabs=1e-12, epsrel=1e-10)
            return value * _s_density(s, df)

        top = math.sqrt(stats.chi2.isf(1e-14, df) / df)
        value, _ = integrate.quad(over_s, 0, top, epsabs=1e-12, epsrel=1e-10, limit=200)
        return value

    return [min(1.0, max(0.0, 1.0 - inside(abs(ti)))) for ti in t]


def tukey_adjusted(t: float, k: int, df: float) -> float:
    """Tukey-Kramer adjusted p of one pair: ``P(Q_{k,df} >= |t| sqrt 2)``."""
    return float(stats.studentized_range.sf(abs(t) * math.sqrt(2.0), k, df))


def scipy_dunnett(
    treated: Sequence[Sequence[float]], control: Sequence[float]
) -> tuple[np.ndarray, np.ndarray]:
    """``scipy.stats.dunnett`` (quasi-Monte Carlo, seeded): statistics and adjusted p."""
    res = stats.dunnett(
        *[np.asarray(x, dtype=float) for x in treated],
        control=np.asarray(control, dtype=float),
        random_state=np.random.default_rng(20261028),
    )
    return np.asarray(res.statistic), np.asarray(res.pvalue)
