"""Dunnett's and Tukey's corrections for several comparisons of one gene (pooled variance).

A study that compares each group with one control (``vs_control``) may correct with
**Dunnett's test**; one that compares every pair of groups (``all_pairs``) with **Tukey's test**
(Tukey-Kramer for unequal group sizes). Both use one variance per gene, pooled over every group
the study compares (an equal-variance assumption on the log2 scale), so each comparison is a
t-test with that pooled standard deviation and ``df = N - G`` (units minus groups with a value).
Holm's correction (:func:`qpilot.qpcr.contrast.holm`) keeps each comparison's own Welch test.

The adjusted p-values are single-step:

* Dunnett (1955): ``p_i = P(max_j |T_j| >= |t_i|)`` where ``T`` is multivariate t with ``df``
  degrees of freedom and correlations ``rho_ij = lambda_i lambda_j``,
  ``lambda_j = sqrt(n_j / (n_j + n_0))`` (``n_0`` the control's size). With that product
  structure the probability is a two-dimensional integral (Dunnett 1955, eq. 3), computed here
  with fixed Gauss quadrature: Gauss-Hermite over the shared normal term and Gauss-Legendre
  (``df < 20``) or a centred Gauss-Hermite rule (``df >= 20``) over ``s = S / sigma``.
  Deterministic (no Monte Carlo), so every run gives the same digits; checked against
  ``scipy.stats.dunnett`` (which integrates by quasi-Monte Carlo, to about 1e-4) and against a
  high-order rule of the same integral (agreement better than 1e-6 for every
  ``lambda <= 0.95``, i.e. a group up to nine times the control's size).
* Tukey-Kramer (Tukey 1953; Kramer 1956): ``p_ij = P(Q_{k,df} >= |t_ij| sqrt(2))`` with
  ``Q`` the studentized range of the ``k`` groups, by the same quadrature; equal to
  ``scipy.stats.studentized_range.sf`` (and so to ``scipy.stats.tukey_hsd``) to about 1e-9.

Everything is vectorised over genes (columns) and comparisons (rows); a NaN statistic (a
comparison the gene cannot test) is not part of its gene's family and stays NaN.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from numpy.polynomial.hermite_e import hermegauss
from numpy.polynomial.legendre import leggauss
from scipy import special, stats

Z_NODES = 64  # the shared standard-normal term (Gauss-Hermite, probabilists')
S_NODES_SMALL_DF = 48  # Gauss-Legendre on [0, s_max] for df < SMALL_DF
S_NODES_LARGE_DF = 32  # centred Gauss-Hermite for df >= SMALL_DF
SMALL_DF = 20
TAIL = 1e-16  # s_max: the chi distribution's upper quantile left out (Legendre rule)
CHUNK = 2_000_000  # quadrature points per block, to bound memory


@lru_cache(maxsize=4)
def _z_rule(n: int = Z_NODES) -> tuple[np.ndarray, np.ndarray]:
    """Nodes and weights of E[g(Z)], Z standard normal."""
    z, w = hermegauss(n)
    return z, w / np.sqrt(2 * np.pi)


@lru_cache(maxsize=512)
def s_rule(df: float) -> tuple[np.ndarray, np.ndarray]:
    """Nodes and weights of E[g(S)], ``S = sqrt(chi2_df / df)`` (the pooled SD over sigma)."""
    if not np.isfinite(df) or df <= 0:
        raise ValueError(f"degrees of freedom must be positive, not {df!r}")
    if df < SMALL_DF:  # wide distribution: Legendre on [0, s_max] with the density explicit
        top = float(np.sqrt(stats.chi2.isf(TAIL, df) / df))
        u, w = leggauss(S_NODES_SMALL_DF)
        s = (u + 1) / 2 * top
        weights = w / 2 * top * 2 * df * s * stats.chi2.pdf(df * s**2, df)
        return s, weights
    # concentrated near 1: Gauss-Hermite centred at 1 with the asymptotic SD, density ratio
    x, w = hermegauss(S_NODES_LARGE_DF)
    w = w / np.sqrt(2 * np.pi)
    sd = np.sqrt(1 / (2 * df))
    s = 1.0 + sd * x
    keep = s > 0
    s = np.where(keep, s, 0.0)
    density = np.where(keep, 2 * df * s * stats.chi2.pdf(df * s**2, df), 0.0)
    normal = np.exp(-(x**2) / 2) / np.sqrt(2 * np.pi)
    return s, w * density * sd / normal


def _by_df(df: np.ndarray, cols: np.ndarray, per_col: int) -> list[tuple[float, np.ndarray]]:
    """Columns grouped by their degrees of freedom, in blocks of at most :data:`CHUNK` points."""
    out = []
    values = df[cols]
    for value in np.unique(values):
        same = cols[values == value]
        step = max(1, CHUNK // max(per_col, 1))
        out.extend((float(value), same[i : i + step]) for i in range(0, len(same), step))
    return out


def dunnett_adjusted(
    t: np.ndarray, n_treated: np.ndarray, n_control: np.ndarray, df: np.ndarray
) -> np.ndarray:
    """Dunnett's single-step adjusted p-values (two-sided), comparison by comparison.

    Args:
        t: Comparisons x genes pooled-variance t statistics (treatment minus control); NaN
            where the comparison is not tested for that gene.
        n_treated: Comparisons x genes, each treatment group's number of values.
        n_control: Per gene, the control group's number of values.
        df: Per gene, the pooled degrees of freedom.

    Returns:
        Comparisons x genes adjusted p-values (NaN where ``t`` is NaN).
    """
    t = np.atleast_2d(np.asarray(t, dtype=float))
    k = t.shape[0]
    n_treated = np.broadcast_to(np.asarray(n_treated, dtype=float), t.shape)
    n_control = np.broadcast_to(np.asarray(n_control, dtype=float), t.shape[1:])
    df = np.broadcast_to(np.asarray(df, dtype=float), t.shape[1:])
    out = np.full(t.shape, np.nan)
    z, wz = _z_rule()
    with np.errstate(divide="ignore", invalid="ignore"):
        lam = np.sqrt(n_treated / (n_treated + n_control[None, :]))
    tested = np.isfinite(t) & np.isfinite(lam) & (lam > 0) & (lam < 1)
    cols = np.flatnonzero(tested.any(axis=0) & np.isfinite(df) & (df > 0))
    for value, block in _by_df(df, cols, k * k * len(z) * S_NODES_SMALL_DF):
        s, ws = s_rule(value)
        member = tested[:, block].T  # (c, j)
        lj = np.where(member, lam[:, block].T, 0.0)
        root = np.sqrt(1 - lj**2)
        c = np.where(member, np.abs(t[:, block].T), 0.0)  # (c, i)
        # (c, i, s, z, j): P(|Z_j| < c_i s | Z_0 = z); a j outside the family counts as 1
        cs = c[:, :, None, None, None] * s[None, None, :, None, None]
        lz = (lj[:, None, :] * z[None, :, None])[:, None, None, :, :]
        rt = root[:, None, None, None, :]
        with np.errstate(invalid="ignore"):
            inside = special.ndtr((lz + cs) / rt) - special.ndtr((lz - cs) / rt)
        inside = np.where(member[:, None, None, None, :], inside, 1.0)
        prob = np.prod(inside, axis=4) @ wz @ ws  # (c, i)
        p = np.clip(1.0 - prob, 0.0, 1.0)
        out[:, block] = np.where(member, p, np.nan).T
    return out


def tukey_adjusted(t: np.ndarray, k: np.ndarray, df: np.ndarray) -> np.ndarray:
    """Tukey-Kramer adjusted p-values from pooled-variance t statistics of pairs of groups.

    Args:
        t: Pairs x genes pooled-variance t statistics (NaN where not tested).
        k: Per gene, the number of groups compared (the studentized range's ``k``).
        df: Per gene, the pooled degrees of freedom.

    Returns:
        Pairs x genes ``P(Q_{k,df} >= |t| sqrt(2))`` (NaN where ``t`` is NaN).
    """
    t = np.atleast_2d(np.asarray(t, dtype=float))
    k = np.broadcast_to(np.asarray(k, dtype=float), t.shape[1:])
    df = np.broadcast_to(np.asarray(df, dtype=float), t.shape[1:])
    out = np.full(t.shape, np.nan)
    z, wz = _z_rule()
    tested = np.isfinite(t)
    cols = np.flatnonzero(tested.any(axis=0) & np.isfinite(df) & (df > 0) & (k >= 2))
    for value, block in _by_df(df, cols, t.shape[0] * len(z) * S_NODES_SMALL_DF):
        s, ws = s_rule(value)
        q = np.where(tested[:, block], np.abs(t[:, block]), 0.0).T * np.sqrt(2.0)  # (c, i)
        groups = k[block][:, None, None, None]
        # (c, i, s, z): k * [Phi(z) - Phi(z - q s)]^(k-1), averaged over z and s
        span = special.ndtr(z[None, None, None, :]) - special.ndtr(
            z[None, None, None, :] - q[:, :, None, None] * s[None, None, :, None]
        )
        inner = groups * np.clip(span, 0.0, 1.0) ** (groups - 1)
        prob = inner @ wz @ ws
        p = np.clip(1.0 - prob, 0.0, 1.0)
        out[:, block] = np.where(tested[:, block].T, p, np.nan).T
    return out


def pooled(
    stats_by_group: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray]:
    """The pooled variance and its degrees of freedom per gene, from each group's (n, mean, var).

    Groups with one value add nothing (no spread); a group with none is left out. ``df`` is
    the sum of ``n - 1`` over the groups; the variance is NaN where ``df`` is zero.
    """
    total_ss = 0.0
    total_df = 0.0
    for n, _, var in stats_by_group:
        n = np.asarray(n, dtype=float)
        dof = np.maximum(n - 1.0, 0.0)
        ss = np.where(dof > 0, np.nan_to_num(np.asarray(var, dtype=float)) * dof, 0.0)
        total_ss = total_ss + ss
        total_df = total_df + dof
    total_ss = np.asarray(total_ss, dtype=float)
    total_df = np.asarray(total_df, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        var = np.where(total_df > 0, total_ss / total_df, np.nan)
    return var, total_df


CORRECTIONS_POOLED = ("dunnett", "tukey")
