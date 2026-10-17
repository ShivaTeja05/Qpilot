"""The qPCR decision space: every reasonable way to analyse the same plates.

This is the qPCR plugin's implementation of :class:`qpilot.schemas.DecisionSpace`, the object the
domain-agnostic core sweeps to build the robustness grid and the Decision Cards. It knows three
analysis choices a scientist has to make:

* ``refs`` — which control genes to divide by: every non-empty subset of the candidates
  (31 subsets of 5);
* ``cut`` — where to draw the MYCN-high line: top 10, 15 or 20 % by MYCN expression;
* ``undetermined`` — what to do with wells that never amplified: ``drop`` or ``cap``.

3 x 31 x 2 = 186 cells. :meth:`QpcrSpace.evaluate` returns every gene's comparison for one cell.
The comparison groups are computed once per cut-off **from the primary control genes** and never
from the cell's own control genes, so changing the control gene changes only the normaliser.

Evaluation is vectorised over genes (numpy), so a full 186-cell sweep over 58 genes takes a few
seconds; results equal :func:`qpilot.qpcr.contrast.welch_contrast` cell by cell.
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from qpilot.qpcr.contrast import DEFAULT_RULE, ConclusionRule, conclude
from qpilot.qpcr.curves import REFERENCE_TARGETS
from qpilot.qpcr.design import GroupSpec, groups_by_cut
from qpilot.qpcr.quant import Undetermined
from qpilot.schemas import Conclusion, ContrastResult, GenormResult

DEFAULT_CUTS: tuple[float, ...] = (0.10, 0.15, 0.20)
DEFAULT_UNDETERMINED: tuple[Undetermined, ...] = ("drop", "cap")


def ref_subsets(candidates: Sequence[str]) -> list[tuple[str, ...]]:
    """Every non-empty subset of the candidates, smallest first, in candidate order."""
    return [
        subset
        for size in range(1, len(candidates) + 1)
        for subset in combinations(candidates, size)
    ]


class QpcrSpace:
    """All reasonable analyses of one qPCR study (implements ``schemas.DecisionSpace``).

    Args:
        matrix: Samples x genes ``log2(n0)`` from :func:`qpilot.qpcr.quant.log2_matrix`.
        genorm: geNorm result for ``candidates``; its recommended set is the primary choice.
        design: Marker gene and primary cut-off; ``design.refs_primary`` is replaced by the
            geNorm-recommended set so groups always come from the primary control genes.
        candidates: Candidate control genes (default: the five demo reference genes).
        cuts: Cut-off options for the high group.
        undetermined: Options for wells that never amplified.
        rule: The conclusion rule.
    """

    def __init__(
        self,
        matrix: pd.DataFrame,
        genorm: GenormResult,
        design: GroupSpec | None = None,
        *,
        candidates: Sequence[str] = REFERENCE_TARGETS,
        cuts: Sequence[float] = DEFAULT_CUTS,
        undetermined: Sequence[Undetermined] = DEFAULT_UNDETERMINED,
        rule: ConclusionRule = DEFAULT_RULE,
    ) -> None:
        design = design or GroupSpec()
        candidates = tuple(candidates)
        missing = [gene for gene in (*candidates, design.marker) if gene not in matrix.columns]
        if missing:
            raise ValueError(f"genes not in the matrix: {missing}")
        primary_refs = tuple(gene for gene in candidates if gene in set(genorm.recommended))
        if design.cut not in cuts:
            raise ValueError(f"primary cut {design.cut} is not one of the options {list(cuts)}")
        self.rule = rule
        self.design = GroupSpec(design.marker, design.cut, primary_refs, design.group_var)
        self.dimensions: dict[str, list[Any]] = {
            "refs": ref_subsets(candidates),
            "cut": list(cuts),
            "undetermined": list(undetermined),
        }
        self.primary: dict[str, Any] = {
            "refs": primary_refs,
            "cut": design.cut,
            "undetermined": "drop",
        }
        excluded = {*candidates, design.marker}
        self.items: list[str] = [gene for gene in matrix.columns if gene not in excluded]
        self._groups = groups_by_cut(matrix, self.design, cuts)
        self._samples = matrix.index
        self._values = matrix[self.items].to_numpy(dtype=float)
        self._lowest = np.nanmin(self._values, axis=0)  # per gene, for the "cap" option
        self._refs = matrix[list(candidates)]
        self._ref_mean: dict[tuple[str, ...], tuple[np.ndarray, np.ndarray]] = {}
        self._masks = {
            cut: (self._samples.isin(high), self._samples.isin(rest))
            for cut, (high, rest) in self._groups.items()
        }

    def groups(self, cut: float) -> tuple[frozenset[str], frozenset[str]]:
        """The (high, rest) sample sets for a cut-off, fixed from the primary control genes."""
        return self._groups[cut]

    def _reference(self, refs: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray]:
        if refs not in self._ref_mean:
            block = self._refs[list(refs)]
            self._ref_mean[refs] = (
                block.mean(axis=1).to_numpy(dtype=float),
                block.notna().all(axis=1).to_numpy(),
            )
        return self._ref_mean[refs]

    def evaluate(self, cell: dict[str, Any]) -> dict[str, ContrastResult]:
        """Every gene's MYCN-high vs rest comparison under one combination of choices."""
        refs = tuple(cell["refs"])
        ref_mean, refs_ok = self._reference(refs)
        values = self._values
        if cell["undetermined"] == "cap":
            values = np.where(np.isnan(values), self._lowest, values)
        elif cell["undetermined"] != "drop":
            raise ValueError(f"unknown undetermined option {cell['undetermined']!r}")
        relative = values - ref_mean[:, None]
        valid = refs_ok[:, None] & ~np.isnan(relative)
        in_high, in_rest = self._masks[cell["cut"]]
        stats_hi = _group_stats(relative, valid & in_high[:, None])
        stats_lo = _group_stats(relative, valid & in_rest[:, None])
        return _welch_results(self.items, stats_hi, stats_lo, self.rule)

    def conclude(self, result: ContrastResult) -> Conclusion:
        """Up / down / none for a result under this space's conclusion rule."""
        return conclude(result.log2fc, result.p, self.rule)


def _group_stats(values: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, ...]:
    """Per-column count, mean and sample variance of ``values`` where ``mask`` is true."""
    n = mask.sum(axis=0)
    filled = np.where(mask, values, 0.0)
    mean = filled.sum(axis=0) / n
    deviations = np.where(mask, values - mean, 0.0)
    var = (deviations**2).sum(axis=0) / (n - 1)
    return n, mean, var


def _welch_results(
    genes: Sequence[str],
    high: tuple[np.ndarray, ...],
    rest: tuple[np.ndarray, ...],
    rule: ConclusionRule,
) -> dict[str, ContrastResult]:
    n_a, mean_a, var_a = high
    n_b, mean_b, var_b = rest
    if (n_a < 2).any() or (n_b < 2).any():
        short = [gene for gene, a, b in zip(genes, n_a, n_b, strict=True) if a < 2 or b < 2]
        raise ValueError(f"fewer than two samples in a group for {short[:5]}")
    sa, sb = var_a / n_a, var_b / n_b
    se = np.sqrt(sa + sb)
    diff = mean_a - mean_b
    t = diff / se
    df = (sa + sb) ** 2 / (sa**2 / (n_a - 1) + sb**2 / (n_b - 1))
    p = 2 * stats.t.sf(np.abs(t), df)
    t_crit = stats.t.ppf(0.975, df)
    out = {}
    for i, gene in enumerate(genes):
        d, half = float(diff[i]), float(t_crit[i] * se[i])
        out[gene] = ContrastResult(
            target=gene,
            log2fc=d,
            fc=2**d,
            ci=(2 ** (d - half), 2 ** (d + half)),
            p=float(p[i]),
            t=float(t[i]),
            n_hi=int(n_a[i]),
            n_lo=int(n_b[i]),
            conclusion=conclude(d, float(p[i]), rule),
        )
    return out
