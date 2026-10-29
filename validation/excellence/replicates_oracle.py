"""How a unit's technical replicate wells become one value: mean, median, or one outlier left out.

The three rules the robustness audit compares (``qsim``'s ``replicates`` decision), written
again from their definitions:

* ``mean``: the mean ``log2 N0`` of the unit's wells with a positive quantity (qPilot's rule);
* ``median``: their median;
* ``drop_outlier``: with three or more such wells whose mean Cq is at most 35, if their Cq range
  is above the 95th percentile of the range of ``n`` normal values with SD
  ``0.15 / ln(E)`` cycles (pipetting CV 15 %, G-REP's "copies unknown" tolerance; at least
  2 cycles when the mean Cq is above 30), the well farthest from the median Cq is left out,
  then the mean (Ruiz-Villalba et al., Life 2021; qPilot's G-REP).

A unit is one value per gene however many wells it has: the comparison's n counts units.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict

import pandas as pd
from scipy import stats

PIPETTING_CV = 0.15
LOW_COPY_CQ = 30.0
STOCHASTIC_CQ = 35.0
LOW_COPY_FLOOR = 2.0


def range_q95(n: int) -> float:
    """Upper 5 % point of the range of ``n`` standard normals (studentized range, df = inf)."""
    return float(stats.studentized_range.ppf(0.95, n, math.inf))


def combine(wells: pd.DataFrame, rule: str, eff_column: str = "eff_target") -> pd.DataFrame:
    """Units x genes ``log2 N0`` under ``rule`` from a per-well table (``sample`` = unit)."""
    by: dict[tuple[str, str], list[tuple[float, float, float]]] = defaultdict(list)
    for row in wells.itertuples(index=False):
        n0 = float(row.n0)
        if not (math.isfinite(n0) and n0 > 0):
            continue
        by[(row.sample, row.target)].append(
            (math.log2(n0), float(row.cq), float(getattr(row, eff_column)))
        )
    out = {}
    for key, items in by.items():
        logs = [v for v, _, _ in items]
        if rule == "mean":
            out[key] = sum(logs) / len(logs)
        elif rule == "median":
            out[key] = statistics.median(logs)
        elif rule == "drop_outlier":
            cqs = [c for _, c, _ in items]
            n = len(cqs)
            mean_cq = sum(cqs) / n
            keep = list(range(n))
            if n >= 3 and mean_cq <= STOCHASTIC_CQ:
                e = statistics.median(x for _, _, x in items)
                e = e if math.isfinite(e) and e > 1 else 2.0
                tol = range_q95(n) * PIPETTING_CV / math.log(e)
                if mean_cq > LOW_COPY_CQ:
                    tol = max(tol, LOW_COPY_FLOOR)
                if max(cqs) - min(cqs) > tol:
                    med = statistics.median(cqs)
                    far = max(range(n), key=lambda i: (abs(cqs[i] - med), -i))
                    keep.remove(far)
            out[key] = sum(logs[i] for i in keep) / len(keep)
        else:
            raise ValueError(rule)
    return pd.Series(out).unstack().sort_index().sort_index(axis=1)
