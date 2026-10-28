"""Standard curves, inverse prediction, LOD and LOQ recomputed with statsmodels and scipy.

* The curve: ordinary least squares of Cq on ``log10`` quantity (``statsmodels.api.OLS``) over the
  detected standard wells; efficiency ``10^(-1/slope) - 1`` and its 95 % interval from the
  slope's t interval (a monotone transform of the slope's ends).
* Inverse prediction of an unknown's mean Cq of ``k`` wells: the classical interval (Miller &
  Miller, Statistics and Chemometrics for Analytical Chemistry, eq. 5.9) and, as a check of that
  approximation, the exact interval obtained by inverting the prediction band (Fieller; Draper &
  Smith, Applied Regression Analysis, 3rd ed., section 3.2): every ``x`` whose band holds ``y0``.
* LOD: the lowest level detected in at least 95 % of its wells with every higher level too, and
  a logistic regression of detection on ``log10`` quantity (``statsmodels`` ``Logit``); its
  95 % point is ``(logit(0.95) - a) / b`` (Forootan et al., Biomol Detect Quantif 2017; 12:1-6).
* LOQ: the lowest level at or above the LOD whose back-calculated quantities have a log-normal
  CV ``sqrt(exp(SD_ln^2) - 1)`` of at most 35 % (Forootan et al. 2017, eq. 4), every higher level
  too.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import statsmodels.api as sm
from scipy import stats


def fit(x: Sequence[float], y: Sequence[float]) -> dict[str, float]:
    """OLS of ``y`` (Cq) on ``x`` (log10 quantity) with statsmodels."""
    xs, ys = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    model = sm.OLS(ys, sm.add_constant(xs)).fit()
    b, m = (float(v) for v in model.params)
    lo, hi = (float(v) for v in model.conf_int(0.05)[1])
    eff_ends = sorted(10 ** (-1 / s) - 1 for s in (lo, hi)) if hi < 0 else [math.nan, math.nan]
    return {
        "n": len(xs),
        "slope": m,
        "intercept": b,
        "r2": float(model.rsquared),
        "s_yx": math.sqrt(float(model.scale)),
        "efficiency": 10 ** (-1 / m) - 1,
        "efficiency_low": eff_ends[0],
        "efficiency_high": eff_ends[1],
        "x_mean": float(xs.mean()),
        "y_mean": float(ys.mean()),
        "sxx": float(((xs - xs.mean()) ** 2).sum()),
    }


def inverse_classical(f: dict[str, float], y0: float, k: int) -> tuple[float, float, float]:
    """``(x0, low, high)`` of the classical (symmetric) 95 % inverse prediction interval."""
    m = f["slope"]
    x0 = (y0 - f["intercept"]) / m
    inner = 1 / k + 1 / f["n"] + (y0 - f["y_mean"]) ** 2 / (m * m * f["sxx"])
    s = f["s_yx"] / abs(m) * math.sqrt(inner)
    t = stats.t.ppf(0.975, f["n"] - 2)
    return x0, x0 - t * s, x0 + t * s


def inverse_exact(f: dict[str, float], y0: float, k: int) -> tuple[float, float]:
    """The exact interval: every ``x`` whose 95 % band for a mean of ``k`` wells holds ``y0``.

    Solves ``(y0 - b - m x)^2 = t^2 s^2 (1/k + 1/n + (x - xbar)^2 / Sxx)`` for ``x``; ``NaN``
    when the slope is not significant enough for a bounded interval (``g >= 1``).
    """
    m, b, n = f["slope"], f["intercept"], f["n"]
    t = stats.t.ppf(0.975, n - 2)
    s2, sxx, xbar = f["s_yx"] ** 2, f["sxx"], f["x_mean"]
    c = t * t * s2
    # (m^2 - c/Sxx) x^2 - 2 (m (y0 - b) - c xbar / Sxx) x + (y0 - b)^2 - c (1/k + 1/n + xbar^2/Sxx)
    qa = m * m - c / sxx
    qb = -2 * (m * (y0 - b) - c * xbar / sxx)
    qc = (y0 - b) ** 2 - c * (1 / k + 1 / n + xbar * xbar / sxx)
    disc = qb * qb - 4 * qa * qc
    if qa <= 0 or disc < 0:
        return math.nan, math.nan
    r1 = (-qb - math.sqrt(disc)) / (2 * qa)
    r2 = (-qb + math.sqrt(disc)) / (2 * qa)
    return min(r1, r2), max(r1, r2)


def lognormal_cv(log10_values: Sequence[float]) -> float:
    """Forootan et al. 2017: ``sqrt(exp(SD_ln^2) - 1)`` of back-calculated quantities."""
    sd_ln = float(np.std(np.asarray(log10_values, dtype=float), ddof=1)) * math.log(10)
    return math.sqrt(math.exp(sd_ln**2) - 1)


def lod_empirical(levels: dict[float, tuple[int, int]], rate: float = 0.95) -> float | None:
    """Lowest level (quantity -> (wells, detected)) at >= rate, every higher level too."""
    passed = None
    for q in sorted(levels, reverse=True):
        n, d = levels[q]
        if n and d / n >= rate:
            passed = q
        else:
            break
    return passed


def lod_logistic(x: Sequence[float], detected: Sequence[bool], rate: float = 0.95) -> float | None:
    """The quantity detected with ``rate`` probability by a logistic fit on log10 quantity."""
    y = np.asarray(detected, dtype=float)
    model = sm.Logit(y, sm.add_constant(np.asarray(x, dtype=float))).fit(disp=0, method="newton")
    a, b = (float(v) for v in model.params)
    if not b > 0:
        return None
    return 10 ** ((math.log(rate / (1 - rate)) - a) / b)
