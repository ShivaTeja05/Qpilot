"""The qPCR decision space: every reasonable way to analyse the same plates.

This is the qPCR plugin's implementation of :class:`qpilot.schemas.DecisionSpace`, the object the
domain-agnostic core sweeps to build the robustness grid and the Decision Cards. It knows these
analysis choices a scientist has to make:

* ``refs`` — which control genes to divide by: every non-empty subset of the candidates
  (31 subsets of 5);
* ``cut`` — where to draw the MYCN-high line: top 10, 15 or 20 % by MYCN expression (only when
  the groups are defined from the data; groups from a confirmed design have no cut);
* ``undetermined`` — what to do with wells that never amplified: ``drop`` or ``cap``;
* ``amp_call`` — which curves count as amplified (:mod:`qpilot.qpcr.amp_call`); present only when
  more than one rule is offered.

3 x 31 x 2 = 186 cells on the demo. :meth:`QpcrSpace.evaluate` returns every gene's comparison
for one cell. The comparison groups are computed once per cut-off **from the primary control
genes and the primary amplification rule** and never from the cell's own choices, so changing a
choice changes only that choice.

A gene with fewer than two values in a group in the primary cell has no p-value: it is withheld
(left out of the items, see :attr:`QpcrSpace.withheld`). In any other cell such a gene gets the
conclusion "none" with p = NaN instead of stopping the sweep.

Evaluation is vectorised over genes (numpy), so a full 186-cell sweep over 58 genes takes a few
seconds; results equal :func:`qpilot.qpcr.contrast.welch_contrast` cell by cell.
"""

from __future__ import annotations

import warnings
from collections.abc import Collection, Mapping, Sequence
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
DEFAULT_AMP_CALL = "linregpcr"


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
        matrix: Units x genes ``log2(n0)`` from :func:`qpilot.qpcr.quant.log2_matrix`, under the
            primary amplification rule.
        genorm: geNorm result for ``candidates``; its recommended set is the primary choice.
        design: Marker gene and primary cut-off; ``design.refs_primary`` is replaced by the
            geNorm-recommended set so groups always come from the primary control genes. Not
            used when ``groups`` is given.
        candidates: Candidate control genes (default: the five demo reference genes).
        cuts: Cut-off options for the high group.
        undetermined: Options for wells that never amplified.
        rule: The conclusion rule.
        groups: Fixed ``(group_a, group_b)`` units from a confirmed design. When given there is
            no ``cut`` dimension and no marker gene.
        amp_call: The amplification rule ``matrix`` was built with (the primary option).
        amp_alternatives: Other amplification rules -> their matrix on the same units and genes.
            With at least one, the space gains the ``amp_call`` dimension.
        excluded: Units x genes, ``True`` where a person excluded every well; such a value is
            left out under every option (never capped).
        group_labels: Names of the two groups, for the withheld-gene reasons.
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
        groups: tuple[Collection[str], Collection[str]] | None = None,
        amp_call: str = DEFAULT_AMP_CALL,
        amp_alternatives: Mapping[str, pd.DataFrame] | None = None,
        excluded: pd.DataFrame | None = None,
        group_labels: tuple[str, str] | None = None,
    ) -> None:
        marker_mode = groups is None
        design = design or GroupSpec()
        candidates = tuple(candidates)
        needed = (*candidates, design.marker) if marker_mode else candidates
        missing = [gene for gene in needed if gene not in matrix.columns]
        if missing:
            raise ValueError(f"genes not in the matrix: {missing}")
        primary_refs = tuple(gene for gene in candidates if gene in set(genorm.recommended))
        if marker_mode and design.cut not in cuts:
            raise ValueError(f"primary cut {design.cut} is not one of the options {list(cuts)}")
        alternatives = dict(amp_alternatives or {})
        if amp_call in alternatives:
            raise ValueError(f"amp_call option {amp_call!r} is listed twice")
        self.rule = rule
        self.design: GroupSpec | None = (
            GroupSpec(design.marker, design.cut, primary_refs, design.group_var)
            if marker_mode
            else None
        )
        self.dimensions: dict[str, list[Any]] = {"refs": ref_subsets(candidates)}
        self.primary: dict[str, Any] = {"refs": primary_refs}
        if marker_mode:
            self.dimensions["cut"] = list(cuts)
            self.primary["cut"] = design.cut
        self.dimensions["undetermined"] = list(undetermined)
        self.primary["undetermined"] = "drop"
        if alternatives:
            self.dimensions["amp_call"] = [amp_call, *alternatives]
            self.primary["amp_call"] = amp_call
        self._amp_primary = amp_call
        excluded_genes = {*candidates, design.marker} if marker_mode else set(candidates)
        genes = [gene for gene in matrix.columns if gene not in excluded_genes]
        self._samples = matrix.index
        if marker_mode:
            self._groups = groups_by_cut(matrix, self.design, cuts)
            labels = group_labels or (design.group_var, "rest")
        else:
            group_a, group_b = groups
            self._groups = {None: (frozenset(group_a), frozenset(group_b))}
            labels = group_labels or ("group A", "group B")
        self._masks = {
            cut: (self._samples.isin(high), self._samples.isin(rest))
            for cut, (high, rest) in self._groups.items()
        }
        matrices = {amp_call: matrix}
        for rule_id, other in alternatives.items():  # same units and genes: a rule never drops one
            matrices[rule_id] = other.reindex(index=matrix.index, columns=matrix.columns)
        self.withheld = self._withheld(matrix, genes, primary_refs, labels)
        self.items: list[str] = [gene for gene in genes if gene not in self.withheld]
        self._excluded: np.ndarray | None = None
        if excluded is not None:
            mask = excluded.reindex(index=matrix.index, columns=self.items)
            self._excluded = mask.astype("boolean").fillna(False).to_numpy(dtype=bool)
        self._by_rule = {rid: self._rule_arrays(m, candidates) for rid, m in matrices.items()}
        self._values, self._lowest, self._refs = self._by_rule[amp_call]
        self._ref_mean: dict[tuple[tuple[str, ...], str], tuple[np.ndarray, np.ndarray]] = {}

    def _rule_arrays(
        self, matrix: pd.DataFrame, candidates: tuple[str, ...]
    ) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
        """Values of the items, their lowest detected value ("cap") and the control genes."""
        values = matrix[self.items].to_numpy(dtype=float)
        with warnings.catch_warnings():  # a gene that is undetermined everywhere has no lowest
            warnings.simplefilter("ignore", RuntimeWarning)
            lowest = np.nanmin(values, axis=0)  # per gene, for the "cap" option
        return values, lowest, matrix[list(candidates)]

    def _withheld(
        self,
        matrix: pd.DataFrame,
        genes: list[str],
        refs: tuple[str, ...],
        labels: tuple[str, str],
    ) -> dict[str, str]:
        """Genes with fewer than two values in a group in the primary cell, with the reason."""
        values = matrix[genes].to_numpy(dtype=float)
        block = matrix[list(refs)]
        relative = values - block.mean(axis=1).to_numpy(dtype=float)[:, None]
        valid = block.notna().all(axis=1).to_numpy()[:, None] & ~np.isnan(relative)
        in_high, in_rest = self._masks[self.primary.get("cut")]
        n_a = (valid & in_high[:, None]).sum(axis=0)
        n_b = (valid & in_rest[:, None]).sum(axis=0)
        out = {}
        for gene, a, b in zip(genes, n_a, n_b, strict=True):
            short = [label for label, n in zip(labels, (a, b), strict=True) if n < 2]
            if short:
                where = " and ".join(short)
                out[gene] = f"fewer than two biological units with a value in {where}"
        return out

    def groups(self, cut: float | None = None) -> tuple[frozenset[str], frozenset[str]]:
        """The (high, rest) units for a cut-off, fixed from the primary choices.

        With groups from a confirmed design there is one pair, ``(group_a, group_b)``, and
        ``cut`` is ignored.
        """
        if self.design is None:
            return self._groups[None]
        return self._groups[cut]

    def _reference(self, refs: tuple[str, ...], amp_call: str) -> tuple[np.ndarray, np.ndarray]:
        key = (refs, amp_call)
        if key not in self._ref_mean:
            block = self._by_rule[amp_call][2][list(refs)]
            self._ref_mean[key] = (
                block.mean(axis=1).to_numpy(dtype=float),
                block.notna().all(axis=1).to_numpy(),
            )
        return self._ref_mean[key]

    def evaluate(self, cell: dict[str, Any]) -> dict[str, ContrastResult]:
        """Every gene's group comparison (high vs rest, or group A vs B) under one cell."""
        refs = tuple(cell["refs"])
        amp_call = cell.get("amp_call", self._amp_primary)
        if amp_call not in self._by_rule:
            raise ValueError(f"unknown amp_call option {amp_call!r}")
        ref_mean, refs_ok = self._reference(refs, amp_call)
        values, lowest, _ = self._by_rule[amp_call]
        if cell["undetermined"] == "cap":
            if self._excluded is None:
                values = np.where(np.isnan(values), lowest, values)
            else:  # an excluded value stays out; only undetermined wells are capped
                values = np.where(np.isnan(values) & ~self._excluded, lowest, values)
        elif cell["undetermined"] != "drop":
            raise ValueError(f"unknown undetermined option {cell['undetermined']!r}")
        relative = values - ref_mean[:, None]
        valid = refs_ok[:, None] & ~np.isnan(relative)
        in_high, in_rest = self._masks[cell["cut"] if self.design is not None else None]
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
    with np.errstate(divide="ignore", invalid="ignore"):  # n < 2 is handled by the caller
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
    with np.errstate(divide="ignore", invalid="ignore"):  # genes with n < 2 are reported below
        sa, sb = var_a / n_a, var_b / n_b
        se = np.sqrt(sa + sb)
        diff = mean_a - mean_b
        t = diff / se
        df = (sa + sb) ** 2 / (sa**2 / (n_a - 1) + sb**2 / (n_b - 1))
        p = 2 * stats.t.sf(np.abs(t), df)
        t_crit = stats.t.ppf(0.975, df)
    out = {}
    nan = float("nan")
    for i, gene in enumerate(genes):
        d = float(diff[i])
        if n_a[i] < 2 or n_b[i] < 2:  # no p-value without two values on each side
            out[gene] = ContrastResult(
                target=gene,
                log2fc=d,
                fc=2**d,
                ci=(nan, nan),
                p=nan,
                t=nan,
                n_hi=int(n_a[i]),
                n_lo=int(n_b[i]),
                conclusion="none",
            )
            continue
        half = float(t_crit[i] * se[i])
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
