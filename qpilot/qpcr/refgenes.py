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

geNorm looks at all samples together, so it cannot tell whether a control gene differs **between
the groups being compared**; a control gene that does would normalise part of the real signal
away (or invent one). :func:`group_effect` checks that directly: the ratio of every pair of
candidates is compared between the high group and the rest (Welch), and a pair whose ratio moves
by at least ``flag_log2`` is flagged. Ratios cancel the input amount, so they are the fair test;
each gene's raw level is reported too but includes the amount of cDNA put in.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import Any

import pandas as pd

from qpilot.qpcr.contrast import welch
from qpilot.schemas import GenormResult

CUTOFF_M = 1.5
CUTOFF_V = 0.15
GROUP_FLAG_LOG2 = 0.5  # a ratio that moves by at least 2**0.5 (1.4-fold) between groups


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


@dataclass(frozen=True)
class RefShift:
    """One control gene (or the ratio of two) compared between the high group and the rest.

    ``diff`` is mean(high) - mean(rest) on the log2 scale; for a pair ``(a, b)`` it is the shift
    of ``log2(a / b)``, so +0.81 means the ratio a:b is 2**0.81 = 1.76 times higher in the high
    group. ``p`` is Welch's two-sided p-value; ``n_hi`` and ``n_lo`` count the samples used.
    """

    genes: tuple[str, ...]
    diff: float
    p: float
    n_hi: int
    n_lo: int

    @property
    def label(self) -> str:
        """``HMBS:UBC(2)`` for a pair, the gene name for a single gene."""
        return ":".join(self.genes)

    @property
    def fold(self) -> float:
        """The shift as a fold change, ``2**diff``."""
        return float(2**self.diff)

    def as_dict(self) -> dict[str, Any]:
        """Plain JSON-serialisable values."""
        return {
            "genes": list(self.genes),
            "label": self.label,
            "diff": float(self.diff),
            "fold": self.fold,
            "p": float(self.p),
            "n_hi": int(self.n_hi),
            "n_lo": int(self.n_lo),
        }


@dataclass(frozen=True)
class RefGroupEffect:
    """Do the candidate control genes differ between the groups being compared?

    ``raw``: each candidate's own log2 level, high minus rest, in candidate order (includes the
    amount of cDNA put in, so it is context, not a verdict). ``pairs``: every pair's log2 ratio,
    high minus rest, largest shift first. ``flagged``: the pairs whose ratio moves by at least
    ``flag_log2``. No multiple-testing correction is applied.
    """

    raw: tuple[RefShift, ...]
    pairs: tuple[RefShift, ...]
    flagged: tuple[RefShift, ...]
    flag_log2: float
    note: str

    @property
    def top(self) -> RefShift | None:
        """The pair whose ratio moves most between the groups (``None`` without pairs)."""
        return self.pairs[0] if self.pairs else None

    def as_dict(self) -> dict[str, Any]:
        """Plain JSON-serialisable values (for a Decision Card's evidence)."""
        return {
            "raw": {shift.label: shift.as_dict() for shift in self.raw},
            "pairs": [shift.as_dict() for shift in self.pairs],
            "flagged": [shift.label for shift in self.flagged],
            "flag_log2": float(self.flag_log2),
            "flag_fold": float(2**self.flag_log2),
            "note": self.note,
        }


def _shift(
    genes: tuple[str, ...], values: pd.Series, high: Collection[str], rest: Collection[str]
) -> RefShift | None:
    """Welch comparison of ``values`` between the groups; ``None`` if a side has < 2 values."""
    values = values.dropna()
    a = values[values.index.isin(high)]
    b = values[values.index.isin(rest)]
    if len(a) < 2 or len(b) < 2:
        return None
    w = welch(a.to_numpy(), b.to_numpy())
    return RefShift(genes=genes, diff=float(w.diff), p=float(w.p), n_hi=len(a), n_lo=len(b))


def group_effect(
    matrix: pd.DataFrame,
    candidates: Sequence[str],
    high: Collection[str],
    rest: Collection[str],
    flag_log2: float = GROUP_FLAG_LOG2,
) -> RefGroupEffect:
    """Check whether the candidate control genes shift between the groups being compared.

    geNorm's M ranks stability over all samples and cannot see a gene that differs between the
    groups; normalising to such a gene moves every target by the same amount. For each pair
    ``(a, b)`` in candidate order, ``matrix[a] - matrix[b]`` (the log2 ratio, which cancels the
    input amount) is compared between ``high`` and ``rest`` with Welch's t-test; samples missing
    either gene are dropped. Pairs whose ratio moves by at least ``flag_log2`` are flagged.

    Args:
        matrix: Samples x genes ``log2(n0)`` from :func:`qpilot.qpcr.quant.log2_matrix`.
        candidates: The candidate control genes.
        high: Sample names in the high group.
        rest: Sample names in the comparison group.
        flag_log2: Flag threshold on ``|diff|`` (log2); 0.5 = 1.4-fold.

    Returns:
        A :class:`RefGroupEffect`. A comparison with fewer than two samples on a side is left
        out (and not counted in the note).
    """
    candidates = tuple(candidates)
    raw = [_shift((gene,), matrix[gene], high, rest) for gene in candidates]
    pairs = [
        _shift((a, b), matrix[a] - matrix[b], high, rest) for a, b in combinations(candidates, 2)
    ]
    tested = sorted((s for s in pairs if s is not None), key=lambda s: -abs(s.diff))
    return RefGroupEffect(
        raw=tuple(s for s in raw if s is not None),
        pairs=tuple(tested),
        flagged=tuple(s for s in tested if abs(s.diff) >= flag_log2),
        flag_log2=float(flag_log2),
        note=f"{len(tested)} pairs, no multiple-testing correction",
    )
