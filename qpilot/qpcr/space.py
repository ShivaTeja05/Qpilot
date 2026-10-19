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
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from qpilot.qpcr.axes import (
    DIMENSION_ORDER,
    AxisDef,
    AxisError,
    AxisOption,
    AxisState,
    AxisStatus,
    get_axis,
    option_text,
    ordered,
)
from qpilot.qpcr.axes import state as axes_state
from qpilot.qpcr.contrast import DEFAULT_RULE, ConclusionRule, conclude
from qpilot.qpcr.curves import REFERENCE_TARGETS
from qpilot.qpcr.design import GroupSpec, groups_by_cut
from qpilot.qpcr.quant import Undetermined
from qpilot.schemas import Conclusion, ContrastResult, GenormResult

DEFAULT_CUTS: tuple[float, ...] = (0.10, 0.15, 0.20)
DEFAULT_UNDETERMINED: tuple[Undetermined, ...] = ("drop", "cap")
DEFAULT_AMP_CALL = "linregpcr"
#: Non-detect rules the space can apply today (see :mod:`qpilot.qpcr.axes`).
NONDETECT_RULES: tuple[str, ...] = ("drop", "cap")


@dataclass(frozen=True)
class MatrixStage:
    """What a matrix source returns for one combination of matrix-stage options.

    ``excluded`` (units x genes, ``True`` where every well of the unit was excluded, e.g. by
    the ``per_well`` efficiency's validity range) keeps such values out under every non-detect
    rule, as a person's exclusion does.
    """

    values: pd.DataFrame
    excluded: pd.DataFrame | None = None


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
            primary option of every matrix-stage axis (amplification rule, efficiency model).
        genorm: geNorm result for ``candidates``; its recommended set is the primary choice.
        design: Marker gene and primary cut-off; ``design.refs_primary`` is replaced by the
            geNorm-recommended set so groups always come from the primary control genes. Not
            used when ``groups`` is given.
        candidates: Candidate control genes (default: the five demo reference genes).
        cuts: Cut-off options for the high group.
        undetermined: Options for wells that never amplified (``drop`` and ``cap`` in the
            legacy grid; see :mod:`qpilot.qpcr.axes`).
        rule: The conclusion rule.
        groups: Fixed ``(group_a, group_b)`` units from a confirmed design. When given there is
            no ``cut`` dimension and no marker gene.
        amp_call: The amplification rule ``matrix`` was built with (the primary option).
        amp_alternatives: Other amplification rules -> their matrix on the same units and genes.
            With at least one, the space gains the ``amp_call`` dimension.
        excluded: Units x genes, ``True`` where a person excluded every well; such a value is
            left out under every option (never capped).
        group_labels: Names of the two groups, for the withheld-gene reasons.
        matrix_axes: Further matrix-stage axes -> their options, primary first, e.g.
            ``{"efficiency": ("linregpcr", "per_well")}``. An axis with one option is held.
        matrix_source: Builds the matrix for any combination of matrix-stage options
            (``{"amp_call": ..., "efficiency": ...}``) that is not the primary matrix or an
            ``amp_alternatives`` entry. Required when ``matrix_axes`` offers a second option.
        option_labels: Axis -> option value -> label, for :attr:`axes` (plain words).
        unavailable: Axis -> option id -> why that option does not apply to this study; such
            options are not offered and are reported in :attr:`axes`.
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
        matrix_axes: Mapping[str, Sequence[Any]] | None = None,
        matrix_source: Callable[[Mapping[str, Any]], pd.DataFrame | MatrixStage] | None = None,
        option_labels: Mapping[str, Mapping[Any, str]] | None = None,
        unavailable: Mapping[str, Mapping[str, str]] | None = None,
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
        undetermined = list(undetermined)
        unknown = [u for u in undetermined if u not in NONDETECT_RULES]
        if unknown or "drop" not in undetermined:
            raise AxisError(
                f"undetermined options must include 'drop' and be among {list(NONDETECT_RULES)}, "
                f"not {undetermined}"
            )
        extra = {name: list(options) for name, options in (matrix_axes or {}).items()}
        for name, options in extra.items():
            if get_axis(name).stage != "matrix" or name == "amp_call":
                raise AxisError(f"{name!r} is not a further matrix-stage axis")
            if not options or len(set(map(repr, options))) != len(options):
                raise AxisError(f"axis {name!r} needs distinct options, primary first")
            if len(options) > 1 and matrix_source is None:
                raise AxisError(f"axis {name!r} offers several options but no matrix_source")
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
        self.dimensions["undetermined"] = undetermined
        self.primary["undetermined"] = "drop"
        if alternatives:
            self.dimensions["amp_call"] = [amp_call, *alternatives]
            self.primary["amp_call"] = amp_call
        for name in ordered(list(extra)):
            if len(extra[name]) > 1:
                self.dimensions[name] = extra[name]
                self.primary[name] = extra[name][0]
        self._amp_primary = amp_call
        # every matrix-stage axis has a primary, swept or not: it keys the stage caches
        self._matrix_primary: dict[str, Any] = {"amp_call": amp_call}
        self._matrix_primary.update({name: options[0] for name, options in extra.items()})
        self._matrix_names = [n for n in DIMENSION_ORDER if n in self._matrix_primary]
        self._matrix_source = matrix_source
        self._offered = {"amp_call": [amp_call, *alternatives], **extra}
        excluded_genes = {*candidates, design.marker} if marker_mode else set(candidates)
        genes = [gene for gene in matrix.columns if gene not in excluded_genes]
        self._samples = matrix.index
        self._columns = matrix.columns
        self._candidates = candidates
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
        self.withheld = self._withheld(matrix, genes, primary_refs, labels)
        self.items: list[str] = [gene for gene in genes if gene not in self.withheld]
        self._excluded: np.ndarray | None = None
        if excluded is not None:
            mask = excluded.reindex(index=matrix.index, columns=self.items)
            self._excluded = mask.astype("boolean").fillna(False).to_numpy(dtype=bool)
        # stage caches: matrix arrays per matrix key, non-detect arrays per (key, rule),
        # control-gene means per (refs, key)
        primary_key = self._matrix_key({})
        self._given = {primary_key: matrix}
        for rule_id, other in alternatives.items():  # same units and genes: a rule never drops one
            key = self._matrix_key({"amp_call": rule_id})
            self._given[key] = other.reindex(index=matrix.index, columns=matrix.columns)
        self._by_key: dict[tuple[Any, ...], tuple[np.ndarray, np.ndarray, pd.DataFrame]] = {}
        self._nondetect: dict[tuple[tuple[Any, ...], str], np.ndarray] = {}
        self._excl_by_key: dict[tuple[Any, ...], np.ndarray] = {}
        self._ref_mean: dict[
            tuple[tuple[str, ...], tuple[Any, ...]], tuple[np.ndarray, np.ndarray]
        ] = {}
        self._unavailable = {k: dict(v) for k, v in (unavailable or {}).items()}
        self.axes: dict[str, AxisState] = self._axis_states(option_labels or {}, candidates)

    # ---- the axes as this study offers them --------------------------------------------

    def _axis_states(
        self, labels: Mapping[str, Mapping[Any, str]], candidates: tuple[str, ...]
    ) -> dict[str, AxisState]:
        """Every registered axis, with its options and whether this grid sweeps it."""
        out: dict[str, AxisState] = {}
        for name in DIMENSION_ORDER:
            axis = get_axis(name)
            if name == "refs":
                values: list[Any] = self.dimensions["refs"]
                primary = self.primary["refs"]
            elif name == "cut":
                if self.design is None:
                    reason = "groups come from the confirmed design, so there is no cut-off"
                    option = AxisOption("none", None, "Groups from the design", "primary")
                    out[name] = axes_state(name, [option], "none", "not_applicable", reason)
                    continue
                values, primary = self.dimensions["cut"], self.primary["cut"]
            elif name == "undetermined":
                values, primary = self.dimensions["undetermined"], "drop"
            else:
                values = self._offered.get(name) or [_DEFAULT_PRIMARY.get(name)]
                primary = values[0]
            options = [
                _option(axis, value, labels.get(name, {}), value == primary, candidates)
                for value in values
            ]
            primary_id = next(o.id for o, v in zip(options, values, strict=True) if v == primary)
            missing = tuple(self._unavailable.get(name, {}).items())
            if name in self.dimensions:
                status, reason = "swept", ""
            elif missing:
                status, reason = "not_applicable", "; ".join(f"{k}: {v}" for k, v in missing)
            else:
                status, reason = "single_option", "only one option offered"
            out[name] = axes_state(name, options, primary_id, status, reason, None, missing)
        return out

    def hold(self, name: str, status: AxisStatus, reason: str) -> None:
        """Take an opt-in axis out of the grid, held at its primary option, and say why.

        Used after screening (:func:`qpilot.core.robustness.screen_axis`): the stage caches
        are kept, so the cells already evaluated are not recomputed. Legacy axes cannot be
        held.
        """
        if self.axes[name].legacy:
            raise AxisError(f"axis {name!r} is in the legacy grid and cannot be held")
        if name in self.dimensions:
            del self.dimensions[name]
            del self.primary[name]
        self.axes[name] = replace(self.axes[name], status=status, reason=reason)

    # ---- stages ----------------------------------------------------------------------

    def _matrix_key(self, cell: Mapping[str, Any]) -> tuple[Any, ...]:
        return tuple(cell.get(name, self._matrix_primary[name]) for name in self._matrix_names)

    def _matrix_arrays(self, key: tuple[Any, ...]) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
        """Stage 1: values of the items, their lowest detected value and the control genes."""
        if key not in self._by_key:
            matrix = self._given.get(key)
            if matrix is None:
                for name, value in zip(self._matrix_names, key, strict=True):
                    if value not in self._offered.get(name, ()):
                        raise AxisError(f"unknown {name} option {value!r}")
                if self._matrix_source is None:
                    raise AxisError(f"no matrix for the options {key!r}")
                built = self._matrix_source(dict(zip(self._matrix_names, key, strict=True)))
                if not isinstance(built, MatrixStage):
                    built = MatrixStage(built)
                matrix = built.values.reindex(index=self._samples, columns=self._columns)
                if built.excluded is not None:
                    mask = built.excluded.reindex(index=self._samples, columns=self.items)
                    mask = mask.astype("boolean").fillna(False).to_numpy(dtype=bool)
                    base = self._excluded
                    self._excl_by_key[key] = mask if base is None else (mask | base)
            self._by_key[key] = self._rule_arrays(matrix, self._candidates)
        return self._by_key[key]

    def _rule_arrays(
        self, matrix: pd.DataFrame, candidates: tuple[str, ...]
    ) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
        """Values of the items, their lowest detected value ("cap") and the control genes."""
        values = matrix[self.items].to_numpy(dtype=float)
        with warnings.catch_warnings():  # a gene that is undetermined everywhere has no lowest
            warnings.simplefilter("ignore", RuntimeWarning)
            lowest = np.nanmin(values, axis=0)  # per gene, for the "cap" option
        return values, lowest, matrix[list(candidates)]

    def _nondetect_values(self, key: tuple[Any, ...], rule: str) -> np.ndarray:
        """Stage 2: the items' values after the non-detect rule."""
        cached = self._nondetect.get((key, rule))
        if cached is not None:
            return cached
        values, lowest, _ = self._matrix_arrays(key)
        excluded = self._excl_by_key.get(key, self._excluded)
        if rule == "cap":
            if excluded is None:
                values = np.where(np.isnan(values), lowest, values)
            else:  # an excluded value stays out; only undetermined wells are capped
                values = np.where(np.isnan(values) & ~excluded, lowest, values)
        elif rule != "drop":
            raise AxisError(f"unknown undetermined option {rule!r}")
        self._nondetect[(key, rule)] = values
        return values

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

    def _reference(
        self, refs: tuple[str, ...], key: tuple[Any, ...]
    ) -> tuple[np.ndarray, np.ndarray]:
        """Stage 3: the mean of the chosen control genes per unit, and where all are present."""
        cache_key = (refs, key)
        if cache_key not in self._ref_mean:
            block = self._matrix_arrays(key)[2][list(refs)]
            self._ref_mean[cache_key] = (
                block.mean(axis=1).to_numpy(dtype=float),
                block.notna().all(axis=1).to_numpy(),
            )
        return self._ref_mean[cache_key]

    def evaluate(self, cell: dict[str, Any]) -> dict[str, ContrastResult]:
        """Every gene's group comparison (high vs rest, or group A vs B) under one cell.

        A cell may leave out an opt-in axis (``amp_call``, ``efficiency``): its primary option
        is used.
        """
        refs = tuple(cell["refs"])
        amp_call = cell.get("amp_call", self._amp_primary)
        if amp_call not in self._offered["amp_call"]:
            raise ValueError(f"unknown amp_call option {amp_call!r}")
        key = self._matrix_key(cell)
        values = self._nondetect_values(key, cell["undetermined"])
        ref_mean, refs_ok = self._reference(refs, key)
        relative = values - ref_mean[:, None]
        valid = refs_ok[:, None] & ~np.isnan(relative)
        in_high, in_rest = self._masks[cell["cut"] if self.design is not None else None]
        stats_hi = _group_stats(relative, valid & in_high[:, None])
        stats_lo = _group_stats(relative, valid & in_rest[:, None])
        return _welch_results(self.items, stats_hi, stats_lo, self.rule)

    def conclude(self, result: ContrastResult) -> Conclusion:
        """Up / down / none for a result under this space's conclusion rule."""
        return conclude(result.log2fc, result.p, self.rule)


_DEFAULT_PRIMARY: dict[str, Any] = {"amp_call": DEFAULT_AMP_CALL, "efficiency": "linregpcr"}


def _option(
    axis: AxisDef,
    value: Any,
    labels: Mapping[Any, str],
    is_primary: bool,
    candidates: tuple[str, ...],
) -> AxisOption:
    """The :class:`AxisOption` for one value of an axis (catalogue entry when there is one)."""
    tier = "primary" if is_primary else "defensible"
    if axis.name == "refs":
        option_id = option_text(value)
        label = labels.get(value) or ", ".join(value)
        if len(value) == 1 and len(candidates) > 1:
            tier = "primary" if is_primary else "common_practice"
        return AxisOption(option_id, value, label, tier)
    if axis.name == "cut":
        return AxisOption(
            f"cut_{round(value * 100)}", value, labels.get(value) or f"Top {value:g}", tier
        )
    for option in axis.catalogue:
        if option.value == value:
            label = labels.get(value) or option.label
            return AxisOption(option.id, value, label, "primary" if is_primary else option.tier)
    return AxisOption(str(value), value, labels.get(value) or str(value), tier)


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
