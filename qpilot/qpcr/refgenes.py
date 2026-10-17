"""Control-gene stability (geNorm): is the yardstick actually straight?

A control gene is only useful if its expression is the same in every sample. geNorm
(Vandesompele et al. 2002) scores each candidate by how much its ratio to the other candidates
varies across samples: the stability value **M** is the mean standard deviation of the pairwise
log2 ratios, and lower is steadier. The least stable gene is removed and M recomputed until two
remain, which gives a ranking. **V(n/n+1)** is the standard deviation of the change in the
normalisation factor when the (n+1)-th gene is added; geNorm recommends the smallest n with
V < 0.15 and treats M < 1.5 as "stable enough".

On the demo tumour panel no candidate is below M 1.5 and no V is below 0.15, so the
recommendation is to use all five; that is exactly why the choice of control gene matters there.
The arithmetic follows the validation oracle (``planning/verification/verify.py``) step by step.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from qpilot.schemas import GenormResult

CUTOFF_M = 1.5
CUTOFF_V = 0.15


def _pairwise_m(matrix: pd.DataFrame, genes: Sequence[str]) -> dict[str, float]:
    """M per gene: mean over the other genes of the SD of the log2 ratio (pairwise complete)."""
    m = {}
    for gene in genes:
        sds = [
            (matrix[gene] - matrix[other]).dropna().std(ddof=1) for other in genes if other != gene
        ]
        m[gene] = float(sum(sds) / len(sds))
    return m


def genorm(matrix: pd.DataFrame, candidates: Sequence[str]) -> GenormResult:
    """Rank candidate control genes by stability and recommend how many to use.

    Args:
        matrix: Samples x genes ``log2(n0)`` from :func:`qpilot.qpcr.quant.log2_matrix`.
        candidates: The candidate control genes (at least three).

    Returns:
        A :class:`GenormResult` with the initial M of every candidate, the ranking (most stable
        first), V(n/n+1) for each step and the recommended set (in ranking order).
    """
    if len(candidates) < 3:
        raise ValueError("geNorm needs at least three candidate control genes")
    remaining = list(candidates)
    removed: list[str] = []
    m_initial: dict[str, float] = {}
    while len(remaining) > 1:
        m = _pairwise_m(matrix, remaining)
        if not m_initial:
            m_initial = m
        if len(remaining) == 2:
            break
        worst = max(m, key=m.get)
        removed.append(worst)
        remaining.remove(worst)
    order = remaining + removed[::-1]
    v: dict[str, float] = {}
    for n in range(2, len(order)):
        smaller, larger = order[:n], order[: n + 1]
        complete = matrix[larger].notna().all(axis=1)
        change = matrix.loc[complete, smaller].mean(axis=1) - matrix.loc[complete, larger].mean(
            axis=1
        )
        v[f"V{n}/{n + 1}"] = float(change.std(ddof=1))
    n_recommended = next(
        (n for n in range(2, len(order)) if v[f"V{n}/{n + 1}"] < CUTOFF_V), len(order)
    )
    return GenormResult(
        M_initial=m_initial,
        order=order,
        V=v,
        recommended=tuple(order[:n_recommended]),
        cutoff_M=CUTOFF_M,
        cutoff_V=CUTOFF_V,
    )


def robust_m(matrix: pd.DataFrame, candidates: Sequence[str]) -> dict[str, float]:
    """A robust variant of M using the scaled median absolute deviation instead of the SD.

    Reported next to M so a reader can see whether a few extreme samples drive instability.
    """
    out = {}
    for gene in candidates:
        mads = []
        for other in candidates:
            if other == gene:
                continue
            ratio = (matrix[gene] - matrix[other]).dropna()
            mads.append(float((ratio - ratio.median()).abs().median() * 1.4826))
        out[gene] = sum(mads) / len(mads)
    return out
