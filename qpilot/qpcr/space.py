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

Several comparisons (a confirmed :class:`~qpilot.schemas_studio.ComparisonPlan`): the space is
given :class:`ComparisonSpec` s, the primary first, and every cell evaluates all of them from the
same relative quantities (the curve fitting and the matrices are shared; a comparison costs a few
array operations). With Holm's correction each gene's p-values are adjusted across its
comparisons inside every cell, and the call uses the adjusted p; :meth:`QpcrSpace.evaluate`
returns the primary comparison, :meth:`QpcrSpace.evaluate_all` every one, and
:class:`ComparisonView` presents one comparison as a decision space of its own (same dimensions,
same cells), so the core's robustness summary works per comparison unchanged. A paired
comparison tests the within-pair differences (:func:`paired_arrays`). Without comparisons (the
default) nothing of this runs and every number is what it was.

What-if evaluation with the groups held fixed (used by :mod:`qpilot.qpcr.trace`): the arrays a
cell is computed from are public through :meth:`QpcrSpace.cell_arrays` and
:meth:`QpcrSpace.group_masks` (copies), and :meth:`QpcrSpace.evaluate_arrays` /
:meth:`QpcrSpace.evaluate_with` run the same arithmetic as :meth:`QpcrSpace.evaluate` on changed
arrays: a reference value read differently, a value left out, a unit set aside. With no change
they return exactly what :meth:`QpcrSpace.evaluate` returns.
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
from qpilot.qpcr.contrast import DEFAULT_RULE, ConclusionRule, conclude, holm
from qpilot.qpcr.curves import REFERENCE_TARGETS
from qpilot.qpcr.design import GroupSpec, groups_by_cut
from qpilot.qpcr.multiplicity import (
    CORRECTIONS_POOLED,
    dunnett_adjusted,
    pooled,
    tukey_adjusted,
)
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


@dataclass(frozen=True)
class ComparisonSpec:
    """One comparison of a study: the units of group A against those of group B.

    ``pairs`` (a paired design) lists ``(unit in A, unit in B)`` per pair, in the order of
    ``pair_keys`` (the donor, animal or passage names); ``None`` for an unpaired comparison.
    """

    id: str
    labels: tuple[str, str]
    group_a: frozenset[str]
    group_b: frozenset[str]
    pairs: tuple[tuple[str, str], ...] | None = None
    pair_keys: tuple[str, ...] = ()

    @property
    def paired(self) -> bool:
        """True for a paired comparison."""
        return self.pairs is not None


MAX_KEPT_CELLS = 20_000  # cells kept by a space with a pooled correction (a few kB each)


def _cell_key(cell: Mapping[str, Any]) -> tuple[Any, ...]:
    """A hashable key of a cell (lists become tuples)."""
    return tuple(
        sorted((k, tuple(v) if isinstance(v, list | tuple) else v) for k, v in cell.items())
    )


@dataclass(frozen=True, eq=False)
class _Masks:
    """A comparison over the space's units: group masks, or the pair positions when paired."""

    in_a: np.ndarray
    in_b: np.ndarray
    idx_a: np.ndarray | None = None
    idx_b: np.ndarray | None = None


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
        comparisons: Several comparisons (or one paired comparison) from a confirmed design,
            the primary first; they replace ``groups`` (whose pair is the primary's). Each cell
            evaluates all of them.
        correction: ``"holm"`` (each gene's p-values adjusted across its comparisons; the
            call uses the adjusted p), ``"dunnett"`` (each group against ``control``) or
            ``"tukey"`` (every pair of groups): both pool the variance over every compared
            group (:mod:`qpilot.qpcr.multiplicity`); or ``"none"``. Only read with
            ``comparisons``.
        control: The control group's label, for ``"dunnett"``.
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
        comparisons: Sequence[ComparisonSpec] | None = None,
        correction: str = "holm",
        control: str | None = None,
    ) -> None:
        specs = tuple(comparisons or ())
        if specs:
            if correction not in ("holm", "none", *CORRECTIONS_POOLED):
                raise ValueError(
                    f"correction must be 'holm', 'dunnett', 'tukey' or 'none', not {correction!r}"
                )
            ids = [spec.id for spec in specs]
            if len(set(ids)) != len(ids):
                raise ValueError(f"comparison ids repeat: {ids}")
            groups = (specs[0].group_a, specs[0].group_b)
            group_labels = specs[0].labels
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
        self.comparisons: tuple[ComparisonSpec, ...] = specs
        self.correction = correction if specs else "none"
        self._cmp: list[_Masks] = [self._spec_masks(spec) for spec in specs]
        self._family = _Family.of(specs, self.correction, control) if specs else None
        self._cells: dict[tuple[Any, ...], list[ContrastArrays]] = {}
        if specs and specs[0].paired:  # the primary's masks are its paired units
            self._masks = {None: (self._cmp[0].in_a, self._cmp[0].in_b)}
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
        if self.comparisons and self.comparisons[0].paired:
            masks = self._cmp[0]
            pairs = (valid[masks.idx_a] & valid[masks.idx_b]).sum(axis=0)
            return {
                gene: "fewer than two complete pairs (a value in both groups)"
                for gene, n in zip(genes, pairs, strict=True)
                if n < 2
            }
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

    def _spec_masks(self, spec: ComparisonSpec) -> _Masks:
        """A comparison's masks over the units (and pair positions when paired)."""
        if spec.pairs is None:
            return _Masks(self._samples.isin(spec.group_a), self._samples.isin(spec.group_b))
        where = {unit: i for i, unit in enumerate(self._samples)}
        kept = [(a, b) for a, b in spec.pairs if a in where and b in where]
        idx_a = np.array([where[a] for a, _ in kept], dtype=int)
        idx_b = np.array([where[b] for _, b in kept], dtype=int)
        in_a = np.zeros(len(self._samples), dtype=bool)
        in_b = np.zeros(len(self._samples), dtype=bool)
        in_a[idx_a], in_b[idx_b] = True, True
        return _Masks(in_a, in_b, idx_a, idx_b)

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
        if self.comparisons:
            return self._cell_compare(cell, relative, valid)[0].results()
        in_high, in_rest = self._masks[cell["cut"] if self.design is not None else None]
        stats_hi = _group_stats(relative, valid & in_high[:, None])
        stats_lo = _group_stats(relative, valid & in_rest[:, None])
        return _welch_results(self.items, stats_hi, stats_lo, self.rule)

    def conclude(self, result: ContrastResult) -> Conclusion:
        """Up / down / none for a result under this space's conclusion rule.

        With several comparisons the call is the one the result carries: it was made from the
        corrected p-value, which a single result cannot recompute.
        """
        if self.comparisons:
            return result.conclusion
        return conclude(result.log2fc, result.p, self.rule)

    # ---- several comparisons ------------------------------------------------------------

    def evaluate_all_arrays(
        self, cell: Mapping[str, Any], *, with_ci: bool = True
    ) -> dict[str, ContrastArrays]:
        """Every comparison under one cell, as arrays over :attr:`items` (calls corrected)."""
        if not self.comparisons:
            raise ValueError("this study has one comparison; use evaluate")
        arrays = self._cells.get(_cell_key(cell))
        if arrays is None:
            values, ref_values = self._cell_inputs(cell)
            ref_mean = ref_values.mean(axis=1)
            refs_ok = ~np.isnan(ref_values).any(axis=1)
            relative = values - ref_mean[:, None]
            valid = refs_ok[:, None] & ~np.isnan(relative)
            arrays = self._cell_compare(cell, relative, valid, with_ci=with_ci)
        return {spec.id: a for spec, a in zip(self.comparisons, arrays, strict=True)}

    def _cell_compare(
        self,
        cell: Mapping[str, Any],
        relative: np.ndarray,
        valid: np.ndarray,
        *,
        with_ci: bool = True,
    ) -> list[ContrastArrays]:
        """A cell's comparisons, kept (with intervals) so the grid's second pass is free.

        A pooled correction (Dunnett, Tukey) integrates a distribution per gene and cell; the
        grid and the per-comparison grid read every cell twice, so each cell is kept once.
        """
        key = _cell_key(cell)
        found = self._cells.get(key)
        if found is not None:
            return found
        out = self._compare(relative, valid, self._cmp, with_ci=with_ci or self._pooled)
        if self._pooled and len(self._cells) < MAX_KEPT_CELLS:
            self._cells[key] = out
        return out

    @property
    def _pooled(self) -> bool:
        return self.correction in CORRECTIONS_POOLED

    def evaluate_all(self, cell: Mapping[str, Any]) -> dict[str, dict[str, ContrastResult]]:
        """Every comparison's results under one cell, by comparison id, the primary first."""
        return {cid: a.results() for cid, a in self.evaluate_all_arrays(cell).items()}

    def comparison_view(self, comparison_id: str) -> ComparisonView:
        """One comparison as a decision space of its own (same dimensions and cells)."""
        if comparison_id not in {spec.id for spec in self.comparisons}:
            raise KeyError(f"no comparison {comparison_id!r}")
        return ComparisonView(self, comparison_id)

    def _cell_inputs(self, cell: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray]:
        """``(values, ref_values)`` of a cell from the stage caches (no copies)."""
        amp_call = cell.get("amp_call", self._amp_primary)
        if amp_call not in self._offered["amp_call"]:
            raise ValueError(f"unknown amp_call option {amp_call!r}")
        key = self._matrix_key(cell)
        values = self._nondetect_values(key, cell["undetermined"])
        refs = self._matrix_arrays(key)[2][list(cell["refs"])].to_numpy(dtype=float)
        return values, refs

    def _compare(
        self,
        relative: np.ndarray,
        valid: np.ndarray,
        masks: Sequence[_Masks],
        *,
        with_ci: bool = True,
    ) -> list[ContrastArrays]:
        """Each comparison's test on the same relative quantities, then the correction."""
        if self._family is not None and self._family.pooled:
            return self._family.compare(self.items, relative, valid, masks, self.rule, with_ci)
        out = []
        for spec, m in zip(self.comparisons, masks, strict=True):
            if spec.pairs is None:
                stats_a = _group_stats(relative, valid & m.in_a[:, None])
                stats_b = _group_stats(relative, valid & m.in_b[:, None])
                out.append(welch_arrays(self.items, stats_a, stats_b, self.rule, with_ci=with_ci))
            else:
                differences = relative[m.idx_a] - relative[m.idx_b]
                complete = valid[m.idx_a] & valid[m.idx_b]
                stats = _group_stats(differences, complete)
                out.append(paired_arrays(self.items, stats, self.rule, with_ci=with_ci))
        if self.correction == "holm" and len(out) > 1:
            adjusted = holm(np.vstack([a.p for a in out]), axis=0)
            out = [_with_call_p(a, adjusted[i]) for i, a in enumerate(out)]
        return out

    # ---- what-if evaluation with fixed groups (public, read-only) ----------------------------

    @property
    def units(self) -> pd.Index:
        """The matrix rows (biological units), in the order every array below uses."""
        return self._samples

    def group_masks(self, cell: Mapping[str, Any] | None = None) -> tuple[np.ndarray, np.ndarray]:
        """Copies of the fixed ``(high, rest)`` boolean masks over :attr:`units` for a cell.

        The groups depend only on the cell's cut-off (none in groups mode); the primary cell's
        groups when ``cell`` is ``None``.
        """
        cell = self.primary if cell is None else cell
        in_high, in_rest = self._masks[cell["cut"] if self.design is not None else None]
        return in_high.copy(), in_rest.copy()

    def cell_arrays(self, cell: Mapping[str, Any] | None = None) -> tuple[np.ndarray, np.ndarray]:
        """Copies of the arrays one cell is computed from: ``(values, ref_values)``.

        ``values`` is units x :attr:`items` ``log2(n0)`` under the cell's amplification rule,
        with the cell's undetermined rule applied (``cap`` fills undetermined values with each
        gene's lowest value); ``ref_values`` is units x the cell's control genes, in the cell's
        order. The primary cell when ``cell`` is ``None``.

        Raises:
            ValueError: Unknown amplification or undetermined option.
        """
        cell = self.primary if cell is None else cell
        amp_call = cell.get("amp_call", self._amp_primary)
        if amp_call not in self._offered["amp_call"]:
            raise ValueError(f"unknown amp_call option {amp_call!r}")
        key = self._matrix_key(cell)  # the stage caches :meth:`evaluate` reads (any matrix axis)
        values = self._nondetect_values(key, cell["undetermined"])
        ref_values = self._matrix_arrays(key)[2][list(cell["refs"])].to_numpy(dtype=float)
        return np.array(values, dtype=float), ref_values

    def evaluate_arrays(
        self,
        values: np.ndarray,
        ref_values: np.ndarray,
        in_high: np.ndarray,
        in_rest: np.ndarray,
    ) -> ContrastArrays:
        """Every item's comparison from explicit arrays, with :meth:`evaluate`'s arithmetic.

        The normaliser is the row mean of ``ref_values``; a unit with any control value missing
        has no relative value. Nothing is re-derived: the masks are used as given.

        Args:
            values: Units x :attr:`items` ``log2(n0)`` (NaN = no value).
            ref_values: Units x control genes ``log2(n0)``.
            in_high: Boolean mask over :attr:`units`, the high group (group A).
            in_rest: Boolean mask over :attr:`units`, the comparison group (group B).

        Returns:
            The arrays; :meth:`ContrastArrays.results` gives the :class:`ContrastResult` dict.
        """
        ref_mean = ref_values.mean(axis=1)
        refs_ok = ~np.isnan(ref_values).any(axis=1)
        relative = values - ref_mean[:, None]
        valid = refs_ok[:, None] & ~np.isnan(relative)
        if self.comparisons:
            return self._compare(relative, valid, self._masks_with(in_high, in_rest))[0]
        stats_hi = _group_stats(relative, valid & in_high[:, None])
        stats_lo = _group_stats(relative, valid & in_rest[:, None])
        return welch_arrays(self.items, stats_hi, stats_lo, self.rule)

    def _masks_with(self, in_high: np.ndarray, in_rest: np.ndarray) -> list[_Masks]:
        """Every comparison's masks with the primary's replaced by ``in_high`` / ``in_rest``.

        A unit the given masks leave out of the primary's groups is set aside in every
        comparison (and its pairs dropped), so the correction sees the same units throughout.
        """
        own = self._cmp[0]
        aside = (own.in_a & ~in_high) | (own.in_b & ~in_rest)
        out = []
        for i, m in enumerate(self._cmp):
            if m.idx_a is not None:
                keep = ~(aside[m.idx_a] | aside[m.idx_b])
                idx_a, idx_b = m.idx_a[keep], m.idx_b[keep]
                out.append(_Masks(m.in_a & ~aside, m.in_b & ~aside, idx_a, idx_b))
            elif i == 0:
                out.append(_Masks(np.asarray(in_high), np.asarray(in_rest)))
            else:
                out.append(_Masks(m.in_a & ~aside, m.in_b & ~aside))
        return out

    def evaluate_with(
        self,
        cell: Mapping[str, Any] | None = None,
        *,
        values: np.ndarray | None = None,
        ref_values: np.ndarray | None = None,
        in_high: np.ndarray | None = None,
        in_rest: np.ndarray | None = None,
    ) -> dict[str, ContrastResult]:
        """:meth:`evaluate` for a cell with some of its arrays replaced (fixed groups).

        Each argument left ``None`` is the cell's own (:meth:`cell_arrays`,
        :meth:`group_masks`), so ``evaluate_with(cell)`` equals ``evaluate(cell)``.
        """
        cell = self.primary if cell is None else cell
        own_values, own_refs = self.cell_arrays(cell)
        own_high, own_rest = self.group_masks(cell)
        out = self.evaluate_arrays(
            own_values if values is None else values,
            own_refs if ref_values is None else ref_values,
            own_high if in_high is None else in_high,
            own_rest if in_rest is None else in_rest,
        )
        return out.results()


@dataclass(frozen=True, eq=False)
class ContrastArrays:
    """Every item's group comparison under one analysis, as arrays over the items.

    Same arithmetic as :meth:`QpcrSpace.evaluate`; ``conclusion`` holds ``"up"``, ``"down"`` or
    ``"none"``, and an item with fewer than two values in a group has p = NaN and ``"none"``.
    """

    items: tuple[str, ...]
    log2fc: np.ndarray
    se: np.ndarray
    t: np.ndarray
    p: np.ndarray
    t_crit: np.ndarray
    n_hi: np.ndarray
    n_lo: np.ndarray
    conclusion: np.ndarray
    rule: ConclusionRule
    p_call: np.ndarray | None = None  # the p-value the call uses (corrected); None: ``p``

    @property
    def half_ci(self) -> np.ndarray:
        """Half-width of the 95 % confidence interval on the log2 scale (NaN without a test)."""
        ok = (self.n_hi >= 2) & (self.n_lo >= 2)
        with np.errstate(invalid="ignore"):
            return np.where(ok, self.t_crit * self.se, np.nan)

    def results(self) -> dict[str, ContrastResult]:
        """One :class:`ContrastResult` per item, exactly as :meth:`QpcrSpace.evaluate` builds it."""
        return _results(
            self.items,
            (self.log2fc, self.se, self.t, self.p, self.t_crit),
            self.n_hi,
            self.n_lo,
            self.rule,
            self.p_call,
        )


@dataclass(frozen=True, eq=False)
class _Family:
    """A study's comparisons as pairs of groups, for a correction that pools their variance.

    ``groups`` are the plan's groups in order of first mention, ``pairs`` each comparison's
    ``(group a, group b)`` positions in it and ``control`` the control's position (Dunnett).
    """

    correction: str
    groups: tuple[str, ...]
    pairs: tuple[tuple[int, int], ...]
    control: int | None

    @property
    def pooled(self) -> bool:
        """True for Dunnett's and Tukey's corrections (one pooled variance per gene)."""
        return self.correction in CORRECTIONS_POOLED

    @classmethod
    def of(cls, specs: Sequence[ComparisonSpec], correction: str, control: str | None) -> _Family:
        groups = tuple(dict.fromkeys(label for spec in specs for label in spec.labels))
        pairs = tuple((groups.index(s.labels[0]), groups.index(s.labels[1])) for s in specs)
        family = cls(correction, groups, pairs, None)
        if not family.pooled:
            return family
        if any(spec.paired for spec in specs):
            raise ValueError(f"{correction} pools unpaired groups; a paired plan uses holm or none")
        if correction == "dunnett":
            if control not in groups or any(groups[b] != control for _, b in pairs):
                raise ValueError("dunnett compares each group with the control (vs_control)")
            return cls(correction, groups, pairs, groups.index(control))
        every = {frozenset((i, j)) for i in range(len(groups)) for j in range(i + 1, len(groups))}
        if {frozenset(p) for p in pairs} != every:
            raise ValueError("tukey compares every pair of the groups (all_pairs)")
        return family

    def compare(
        self,
        items: Sequence[str],
        relative: np.ndarray,
        valid: np.ndarray,
        masks: Sequence[_Masks],
        rule: ConclusionRule,
        with_ci: bool,
    ) -> list[ContrastArrays]:
        """Each comparison's pooled-variance t-test, then Dunnett's or Tukey's adjusted p."""
        found: dict[int, np.ndarray] = {}
        for (a, b), m in zip(self.pairs, masks, strict=True):
            found.setdefault(a, m.in_a)  # a unit set aside is out of every comparison's masks
            found.setdefault(b, m.in_b)
        stats_by_group = [
            _group_stats(relative, valid & found[g][:, None]) for g in range(len(self.groups))
        ]
        var, df = pooled(stats_by_group)
        arrays = [
            pooled_arrays(items, stats_by_group[a], stats_by_group[b], var, df, rule, with_ci)
            for a, b in self.pairs
        ]
        t = np.vstack([a.t for a in arrays])
        if self.correction == "dunnett":
            n_treated = np.vstack([stats_by_group[a][0] for a, _ in self.pairs])
            n_control = stats_by_group[self.control][0]  # type: ignore[index]
            adjusted = dunnett_adjusted(t, n_treated, n_control, df)
        else:
            k = sum((s[0] >= 2).astype(float) for s in stats_by_group)
            adjusted = tukey_adjusted(t, k, df)
        return [_with_call_p(a, adjusted[i]) for i, a in enumerate(arrays)]


def pooled_arrays(
    items: Sequence[str],
    group_a: tuple[np.ndarray, ...],
    group_b: tuple[np.ndarray, ...],
    var: np.ndarray,
    df: np.ndarray,
    rule: ConclusionRule,
    with_ci: bool = True,
) -> ContrastArrays:
    """A t-test of group A against group B with the variance pooled over every group.

    ``var`` and ``df`` are the pooled variance and its degrees of freedom per item
    (:func:`qpilot.qpcr.multiplicity.pooled`). Fewer than two values in either group gives
    p = NaN, t = NaN and the call "none", as :func:`welch_arrays` does.
    """
    n_a, mean_a, _ = group_a
    n_b, mean_b, _ = group_b
    with np.errstate(divide="ignore", invalid="ignore"):
        se = np.sqrt(var * (1 / n_a + 1 / n_b))
        diff = mean_a - mean_b
        t = diff / se
        p = 2 * stats.t.sf(np.abs(t), df)
        t_crit = stats.t.ppf(0.975, df) if with_ci else np.full(np.shape(df), np.nan)
    tested = (n_a >= 2) & (n_b >= 2) & (df > 0) & np.isfinite(t)
    p = np.where(tested, p, np.nan)
    t = np.where(tested, t, np.nan)
    with np.errstate(invalid="ignore"):
        significant = p < rule.alpha
    call = np.where(
        significant & (diff >= rule.min_log2fc),
        "up",
        np.where(significant & (diff <= -rule.min_log2fc), "down", "none"),
    )
    return ContrastArrays(tuple(items), diff, se, t, p, t_crit, n_a, n_b, call, rule)


class ComparisonView:
    """One comparison of a :class:`QpcrSpace` with several, as a decision space of its own.

    It has the space's dimensions, primary cell and items, and evaluates to that comparison's
    results (calls already corrected), so ``core.robustness`` summarises it unchanged.
    """

    def __init__(self, space: QpcrSpace, comparison_id: str) -> None:
        self.space = space
        self.id = comparison_id

    @property
    def dimensions(self) -> dict[str, list[Any]]:
        """The space's dimensions."""
        return self.space.dimensions

    @property
    def primary(self) -> dict[str, Any]:
        """The space's primary cell."""
        return self.space.primary

    @property
    def items(self) -> list[str]:
        """The space's genes."""
        return self.space.items

    def evaluate(self, cell: dict[str, Any]) -> dict[str, ContrastResult]:
        """This comparison's results under one cell."""
        return self.space.evaluate_all_arrays(cell)[self.id].results()

    def conclude(self, result: ContrastResult) -> Conclusion:
        """The call the result carries (made from the corrected p-value)."""
        return result.conclusion


def _with_call_p(arrays: ContrastArrays, p_call: np.ndarray) -> ContrastArrays:
    """The arrays with their calls made from ``p_call`` (a corrected p-value)."""
    rule = arrays.rule
    with np.errstate(invalid="ignore"):
        significant = p_call < rule.alpha
    call = np.where(
        significant & (arrays.log2fc >= rule.min_log2fc),
        "up",
        np.where(significant & (arrays.log2fc <= -rule.min_log2fc), "down", "none"),
    )
    return replace(arrays, conclusion=call, p_call=p_call)


def paired_arrays(
    items: Sequence[str],
    differences: tuple[np.ndarray, ...],
    rule: ConclusionRule,
    *,
    with_ci: bool = True,
) -> ContrastArrays:
    """The paired t-test per item from the ``(n, mean, var)`` of within-pair differences.

    ``n_hi`` and ``n_lo`` are both the number of complete pairs; fewer than two give p = NaN
    and the call "none", as :func:`welch_arrays` does for a group with fewer than two values.
    """
    n, mean, var = differences
    with np.errstate(divide="ignore", invalid="ignore"):
        se = np.sqrt(var / n)
        t = mean / se
        df = n - 1.0
        p = 2 * stats.t.sf(np.abs(t), df)
        t_crit = stats.t.ppf(0.975, df) if with_ci else np.full(np.shape(df), np.nan)
    tested = n >= 2
    p = np.where(tested, p, np.nan)
    with np.errstate(invalid="ignore"):
        significant = p < rule.alpha
    call = np.where(
        significant & (mean >= rule.min_log2fc),
        "up",
        np.where(significant & (mean <= -rule.min_log2fc), "down", "none"),
    )
    return ContrastArrays(tuple(items), mean, se, t, p, t_crit, n, n, call, rule)


def comparison_grid(space: QpcrSpace, grid: pd.DataFrame) -> pd.DataFrame:
    """Every comparison's rows for the cells of ``grid`` (the primary's ``run_grid`` output).

    The same cells in the same order, one block per comparison (primary first): the grid's
    dimension, index and ``item`` columns, then ``log2fc``, ``fc``, ``p`` (uncorrected),
    ``p_adjusted`` (the p the call used) and ``conclusion``, with a leading ``comparison``
    column. The primary's block repeats ``grid``'s numbers.
    """
    idx_cols = [c for c in grid.columns if c.endswith(_IDX)]
    names = [c[: -len(_IDX)] for c in idx_cols]
    n_items = len(space.items)
    starts = range(0, len(grid), n_items) if n_items else range(0)
    collected: dict[str, list[tuple[np.ndarray, ...]]] = {s.id: [] for s in space.comparisons}
    for start in starts:
        combo = grid.iloc[start][idx_cols].to_numpy(dtype=int)
        cell = {n: space.dimensions[n][i] for n, i in zip(names, combo, strict=True)}
        for cid, a in space.evaluate_all_arrays(cell, with_ci=False).items():
            p_call = a.p if a.p_call is None else a.p_call
            collected[cid].append((a.log2fc, a.p, p_call, a.conclusion))
    base = grid[[*names, *idx_cols, "item"]].reset_index(drop=True)
    blocks = []
    for cid, parts in collected.items():
        block = base.copy()
        block.insert(0, "comparison", cid)
        if parts:
            log2fc, p, p_call, call = (np.concatenate(x) for x in zip(*parts, strict=True))
        else:
            log2fc = p = p_call = np.array([], dtype=float)
            call = np.array([], dtype=object)
        block["log2fc"] = log2fc
        block["fc"] = 2.0**log2fc
        block["p"] = p
        block["p_adjusted"] = p_call
        block["conclusion"] = call
        blocks.append(block)
    if not blocks:
        return base.iloc[0:0]
    return pd.concat(blocks, ignore_index=True)


_IDX = "__idx"


def welch_arrays(
    items: Sequence[str],
    high: tuple[np.ndarray, ...],
    rest: tuple[np.ndarray, ...],
    rule: ConclusionRule,
    *,
    with_ci: bool = True,
) -> ContrastArrays:
    """Welch's test per item from per-group ``(n, mean, var)`` arrays (any common shape).

    The arrays may be per item (one analysis) or, broadcast, several analyses at once (rows =
    analyses, columns = items); ``items`` names the last axis. ``with_ci=False`` skips the
    t quantile (``t_crit`` is NaN): faster when only the fold change and the call are needed.
    """
    n_a, n_b = high[0], rest[0]
    diff, se, t, p, t_crit = _welch_core(high, rest, with_ci=with_ci)
    tested = (n_a >= 2) & (n_b >= 2)
    p = np.where(tested, p, np.nan)
    with np.errstate(invalid="ignore"):
        significant = p < rule.alpha
    call = np.where(
        significant & (diff >= rule.min_log2fc),
        "up",
        np.where(significant & (diff <= -rule.min_log2fc), "down", "none"),
    )
    return ContrastArrays(tuple(items), diff, se, t, p, t_crit, n_a, n_b, call, rule)


def group_stats(values: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, ...]:
    """Per-column count, mean and sample variance of ``values`` where ``mask`` is true."""
    return _group_stats(values, mask)


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


def _welch_core(
    high: tuple[np.ndarray, ...], rest: tuple[np.ndarray, ...], *, with_ci: bool = True
) -> tuple[np.ndarray, ...]:
    """``(diff, se, t, p, t_crit)`` of Welch's test from per-group ``(n, mean, var)``."""
    n_a, mean_a, var_a = high
    n_b, mean_b, var_b = rest
    with np.errstate(divide="ignore", invalid="ignore"):  # genes with n < 2 are reported later
        sa, sb = var_a / n_a, var_b / n_b
        se = np.sqrt(sa + sb)
        diff = mean_a - mean_b
        t = diff / se
        df = (sa + sb) ** 2 / (sa**2 / (n_a - 1) + sb**2 / (n_b - 1))
        p = 2 * stats.t.sf(np.abs(t), df)
        t_crit = stats.t.ppf(0.975, df) if with_ci else np.full(np.shape(df), np.nan)
    return diff, se, t, p, t_crit


def _welch_results(
    genes: Sequence[str],
    high: tuple[np.ndarray, ...],
    rest: tuple[np.ndarray, ...],
    rule: ConclusionRule,
) -> dict[str, ContrastResult]:
    return _results(genes, _welch_core(high, rest), high[0], rest[0], rule)


def _results(
    genes: Sequence[str],
    welch: tuple[np.ndarray, ...],
    n_a: np.ndarray,
    n_b: np.ndarray,
    rule: ConclusionRule,
    p_call: np.ndarray | None = None,
) -> dict[str, ContrastResult]:
    diff, se, t, p, t_crit = welch
    call_p = p if p_call is None else p_call
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
            conclusion=conclude(d, float(call_p[i]), rule),
        )
    return out
