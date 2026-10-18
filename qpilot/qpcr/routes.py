"""The usual route from the instrument to Prism, recomputed by the engine for comparison.

Most published qPCR results go through ΔΔCq in a spreadsheet and a t test in GraphPad Prism.
This module recomputes that route on the same plates, the same groups (fixed from the engine's
primary analysis) and the same primary control genes, and counts the genes whose conclusion
differs from the engine's. Three variants, each a common way to do it:

* ``ddcq`` — ΔΔCq with the efficiency assumed to be 2.0 on the engine's Cq, Welch's t test on
  the log2 scale (``-ΔCq``). Only the assumed efficiency differs from the engine's primary
  cell, which uses the same wells;
* ``linear_welch`` — then 2^-ΔΔCq per sample (calibrator: the mean ΔCq of the comparison group,
  the "rest"), Welch's t test on that linear scale, fold change = ratio of the group means;
* ``linear_student`` — the same with Student's equal-variance t test (Prism's older default).

ΔCq = Cq(gene) - mean(Cq of the control genes) per sample; samples missing a control gene's Cq
are skipped, as are wells without a Cq (the spreadsheet route has no quantity to drop or cap).
Technical replicates are averaged per biological unit (mean Cq), as the engine averages
log2 N0. Wells a person excluded or called not amplified are left out, and so are the wells
the engine's primary amplification rule does not count (a Cq cut-off a person chose as the
primary rule applies to the routes as to the engine; no route applies a cut-off of its own).
Conclusions use the engine's call rule (p < 0.05 and at least two-fold). A gene with fewer
than two values in a group gets "none".

The routes are reported as facts, never used for a conclusion. Deterministic; no model call.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from qpilot.qpcr.amp_call import amplified, well_keys
from qpilot.qpcr.contrast import DEFAULT_RULE, ConclusionRule, conclude, welch
from qpilot.qpcr.quant import EXCLUDED, unit_map
from qpilot.schemas import Conclusion

ROUTES: tuple[str, ...] = ("ddcq", "linear_welch", "linear_student")
ROUTE_LABELS: dict[str, str] = {
    "ddcq": "ΔΔCq (efficiency assumed 2.0), Welch's t test on log2",
    "linear_welch": "2^-ΔΔCq per sample, Welch's t test on the linear scale",
    "linear_student": "2^-ΔΔCq per sample, Student's t test on the linear scale",
}


@dataclass(frozen=True)
class RouteResult:
    """One route's conclusion per gene and the genes where it differs from the engine."""

    route: str
    conclusions: dict[str, Conclusion]
    differ: tuple[str, ...]

    @property
    def n_differ(self) -> int:
        """How many genes this route concludes differently from the engine."""
        return len(self.differ)


def cq_matrix(
    curves: pd.DataFrame,
    units: Mapping[str, str] | None = None,
    well_calls: Mapping[str, bool] | None = None,
    amp_call: str | None = None,
) -> pd.DataFrame:
    """Mean Cq per biological unit and gene over the study wells that have a Cq.

    Wells excluded by a person (``design_excluded``) or called not amplified by a person
    (``well_calls[...] = False``) are left out; with ``amp_call`` (the engine's primary rule),
    so are the wells that rule does not count as amplified.
    """
    unknown = curves[curves["sample_type"] == "unkn"]
    keep = unknown["cq"].notna()
    if EXCLUDED in unknown.columns:
        keep &= ~unknown[EXCLUDED].astype(bool)
    if well_calls:
        keep &= ~well_keys(unknown).map(well_calls).eq(False)
    if amp_call is not None:
        keep &= amplified(curves, amp_call, well_calls).loc[unknown.index]
    rows = unknown[keep]
    table = pd.DataFrame(
        {
            "unit": unit_map(rows["sample"], units).to_numpy(),
            "target": rows["target"].to_numpy(),
            "cq": rows["cq"].to_numpy(dtype=float),
        }
    )
    return table.groupby(["unit", "target"])["cq"].mean().unstack("target")


def _student_p(a: np.ndarray, b: np.ndarray) -> float:
    """Two-sided p of Student's equal-variance t test."""
    return float(stats.ttest_ind(a, b, equal_var=True).pvalue)


def gene_routes(
    delta_cq: pd.Series,
    high: Collection[str],
    rest: Collection[str],
    rule: ConclusionRule = DEFAULT_RULE,
) -> dict[str, Conclusion]:
    """The three routes' conclusions for one gene from its ΔCq per unit."""
    a = delta_cq[delta_cq.index.isin(high)].to_numpy(dtype=float)
    b = delta_cq[delta_cq.index.isin(rest)].to_numpy(dtype=float)
    if len(a) < 2 or len(b) < 2:
        return dict.fromkeys(ROUTES, "none")
    log2 = welch(-a, -b)
    calibrator = b.mean()
    rq_a, rq_b = 2.0 ** -(a - calibrator), 2.0 ** -(b - calibrator)
    log2_fold = math.log2(rq_a.mean() / rq_b.mean())
    return {
        "ddcq": conclude(log2.diff, log2.p, rule),
        "linear_welch": conclude(log2_fold, welch(rq_a, rq_b).p, rule),
        "linear_student": conclude(log2_fold, _student_p(rq_a, rq_b), rule),
    }


def compare_routes(
    curves: pd.DataFrame,
    units: Mapping[str, str] | None,
    samples: Sequence[str],
    high: Collection[str],
    rest: Collection[str],
    refs: Sequence[str],
    engine: Mapping[str, Conclusion],
    rule: ConclusionRule = DEFAULT_RULE,
    well_calls: Mapping[str, bool] | None = None,
    amp_call: str | None = None,
) -> dict[str, RouteResult]:
    """Every route's conclusions and the genes where each differs from the engine.

    Args:
        curves: The per-well table as the design says (:func:`qpilot.qpcr.designs.design_curves`).
        units: Sample -> biological unit (as for the engine's matrix).
        samples: The units of the engine's matrix (the routes use the same ones).
        high: Units of the first group (fixed from the engine's primary analysis).
        rest: Units of the comparison group.
        refs: The engine's primary control genes.
        engine: Each compared gene's conclusion in the engine's primary cell.
        rule: The call rule.
        well_calls: A person's per-well resolutions (``False`` leaves the well out).
        amp_call: The engine's primary amplification rule; the routes leave out the wells it
            does not count, so they use the primary cell's wells.
    """
    cq = cq_matrix(curves, units, well_calls, amp_call).reindex(index=list(samples))
    reference = cq.reindex(columns=list(refs))
    refs_ok = reference.notna().all(axis=1)
    ref_mean = reference.mean(axis=1)
    by_route: dict[str, dict[str, Conclusion]] = {route: {} for route in ROUTES}
    for gene in engine:
        values = cq[gene] if gene in cq.columns else pd.Series(np.nan, index=cq.index)
        delta = (values - ref_mean)[refs_ok & values.notna()]
        for route, conclusion in gene_routes(delta, high, rest, rule).items():
            by_route[route][gene] = conclusion
    return {
        route: RouteResult(
            route=route,
            conclusions=conclusions,
            differ=tuple(g for g in engine if conclusions[g] != engine[g]),
        )
        for route, conclusions in by_route.items()
    }
