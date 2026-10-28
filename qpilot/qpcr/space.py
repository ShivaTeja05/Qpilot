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
  more than one rule is offered;
* ``normaliser`` (opt-in) — what each gene is divided by: the control genes of the ``refs`` cell
  (``planned``), NormFinder's or geNorm's best pair, or the global mean
  (:mod:`qpilot.qpcr.axes.normaliser`). Its other options do not depend on ``refs``, so a cell
  with another normaliser and a non-primary ``refs`` would repeat an analysis: such cells are
  :meth:`QpcrSpace.redundant` and the grid leaves them out.

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


@dataclass(frozen=True)
class DetectedOnly:
    """A gene measured in both groups but detected in only one of them (or in neither).

    ``group`` is the group it was detected in (``None``: neither); ``absent`` the group none
    of whose measured units it was detected in. Counts are biological units: ``n_detected``
    of ``n_group`` in ``group``, none of ``n_absent`` in ``absent``.
    """

    group: str | None
    absent: str
    n_detected: int
    n_group: int
    n_absent: int

    def words(self) -> str:
        """The withheld reason in plain words (no fold change is given)."""
        if self.group is None:
            return (
                f"not detected in any of the {self.n_absent} biological units of {self.absent}: "
                "there is no fold change to give"
            )
        return (
            f"detected only in {self.group} ({self.n_detected} of {self.n_group} biological "
            f"units); not detected in any of the {self.n_absent} units of {self.absent}: there "
            "is no fold change to give (a ratio to nothing), only that it is present in one "
            "group"
        )


def _detected_only(
    labels: tuple[str, str], detected: tuple[int, int], measured: tuple[int, int]
) -> DetectedOnly | None:
    """The :class:`DetectedOnly` of a withheld gene, or ``None`` when that is not why."""
    (label_a, label_b), (n_a, n_b), (m_a, m_b) = labels, detected, measured
    if m_a == 0 or m_b == 0:  # a group without a measured unit: not a detection question
        return None
    if n_a == 0 and n_b == 0:
        return DetectedOnly(None, f"{label_a} or {label_b}", 0, 0, m_a + m_b)
    if n_a == 0:
        return DetectedOnly(label_b, label_a, n_b, m_b, m_a)
    if n_b == 0:
        return DetectedOnly(label_a, label_b, n_a, m_a, m_b)
    return None


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
            call uses the adjusted p) or ``"none"``. Only read with ``comparisons``.
        normaliser: The options of the normaliser axis, ``"planned"`` first (one option or
            none: no axis).
        normaliser_source: ``(option, cell matrix) -> units x columns`` whose row mean is that
            option's normaliser (every option but ``"planned"``); required with a second
            normaliser option.
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
        normaliser: Sequence[str] | None = None,
        normaliser_source: Callable[[str, pd.DataFrame], np.ndarray] | None = None,
    ) -> None:
        specs = tuple(comparisons or ())
        if specs:
            if correction not in ("holm", "none"):
                raise ValueError(f"correction must be 'holm' or 'none', not {correction!r}")
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
        norm_options = list(normaliser or ())
        if norm_options and (
            norm_options[0] != _DEFAULT_PRIMARY["normaliser"]
            or len(set(norm_options)) != len(norm_options)
        ):
            raise AxisError("the normaliser options must be distinct and start with 'planned'")
        if len(norm_options) > 1 and normaliser_source is None:
            raise AxisError("the normaliser axis offers several options but no normaliser_source")
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
        offered_axes = {**extra, **({"normaliser": norm_options} if norm_options else {})}
        for name in ordered(list(offered_axes)):
            if len(offered_axes[name]) > 1:
                self.dimensions[name] = offered_axes[name]
                self.primary[name] = offered_axes[name][0]
        self._amp_primary = amp_call
        # every matrix-stage axis has a primary, swept or not: it keys the stage caches
        self._matrix_primary: dict[str, Any] = {"amp_call": amp_call}
        self._matrix_primary.update({name: options[0] for name, options in extra.items()})
        self._matrix_names = [n for n in DIMENSION_ORDER if n in self._matrix_primary]
        self._matrix_source = matrix_source
        self._offered = {"amp_call": [amp_call, *alternatives], **extra}
        if norm_options:
            self._offered["normaliser"] = norm_options
        self._normaliser_source = normaliser_source
        self._norm_cache: dict[tuple[str, tuple[Any, ...]], np.ndarray] = {}
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
        if specs and specs[0].paired:  # the primary's masks are its paired units
            self._masks = {None: (self._cmp[0].in_a, self._cmp[0].in_b)}
        left_out = None
        if excluded is not None:
            left_out = excluded.reindex(index=matrix.index, columns=genes)
            left_out = left_out.astype("boolean").fillna(False).to_numpy(dtype=bool)
        self.detected_only: dict[str, DetectedOnly] = {}
        self.withheld = self._withheld(matrix, genes, primary_refs, labels, left_out)
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
        self._capped: dict[tuple[tuple[Any, ...], str], np.ndarray] = {}
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
        """Values of the items, their lowest detected value ("cap") and the whole matrix.

        The matrix (every gene, the control genes among them) is what a normaliser is read
        from: the chosen control genes' columns, or every gene for the global mean.
        """
        values = matrix[self.items].to_numpy(dtype=float)
        with warnings.catch_warnings():  # a gene that is undetermined everywhere has no lowest
            warnings.simplefilter("ignore", RuntimeWarning)
            lowest = np.nanmin(values, axis=0)  # per gene, for the "cap" option
        return values, lowest, matrix

    def _nondetect_values(self, key: tuple[Any, ...], rule: str) -> np.ndarray:
        """Stage 2: the items' values after the non-detect rule."""
        cached = self._nondetect.get((key, rule))
        if cached is not None:
            return cached
        values, lowest, _ = self._matrix_arrays(key)
        excluded = self._excl_by_key.get(key, self._excluded)
        if rule == "cap":
            capped = np.isnan(values) if excluded is None else np.isnan(values) & ~excluded
            values = np.where(capped, lowest, values)  # an excluded value stays out
            self._capped[(key, rule)] = capped & ~np.isnan(values)
        elif rule != "drop":
            raise AxisError(f"unknown undetermined option {rule!r}")
        self._nondetect[(key, rule)] = values
        return values

    def _capped_mask(self, cell: Mapping[str, Any]) -> np.ndarray | None:
        """Units x items: the values the cell's non-detect rule filled in (``None``: none).

        A group none of whose values was detected (every one of them capped) has no measured
        amount to compare: the comparison is not tested there, as under ``drop``, instead of a
        fold change made of the cap (see :attr:`detected_only`).
        """
        key = self._matrix_key(cell)
        self._nondetect_values(key, cell["undetermined"])
        return self._capped.get((key, cell["undetermined"]))

    def _withheld(
        self,
        matrix: pd.DataFrame,
        genes: list[str],
        refs: tuple[str, ...],
        labels: tuple[str, str],
        left_out: np.ndarray | None = None,
    ) -> dict[str, str]:
        """Genes with fewer than two values in a group in the primary cell, with the reason.

        A gene measured in both groups but not detected in any unit of one of them (every
        such value undetermined; none excluded or not measured) is "detected only in" the
        other group, or "not detected in either group": :attr:`detected_only` keeps who, and
        the reason says it in words. There is no fold change to give for it.
        """
        values = matrix[genes].to_numpy(dtype=float)
        block = matrix[list(refs)]
        relative = values - block.mean(axis=1).to_numpy(dtype=float)[:, None]
        refs_ok = block.notna().all(axis=1).to_numpy()[:, None]
        valid = refs_ok & ~np.isnan(relative)
        measured = refs_ok & np.ones_like(valid)
        if left_out is not None:
            measured = measured & ~left_out
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
        m_a = (measured & in_high[:, None]).sum(axis=0)
        m_b = (measured & in_rest[:, None]).sum(axis=0)
        out = {}
        for i, (gene, a, b) in enumerate(zip(genes, n_a, n_b, strict=True)):
            short = [label for label, n in zip(labels, (a, b), strict=True) if n < 2]
            if not short:
                continue
            only = _detected_only(labels, (int(a), int(b)), (int(m_a[i]), int(m_b[i])))
            if only is None:
                where = " and ".join(short)
                out[gene] = f"fewer than two biological units with a value in {where}"
                continue
            self.detected_only[gene] = only
            out[gene] = only.words()
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

    def _normaliser_of(self, cell: Mapping[str, Any]) -> str:
        """The cell's normaliser option (``planned`` when the axis is not in the cell)."""
        option = cell.get("normaliser", _DEFAULT_PRIMARY["normaliser"])
        if option not in self._offered.get("normaliser", [_DEFAULT_PRIMARY["normaliser"]]):
            raise AxisError(f"unknown normaliser option {option!r}")
        return option

    def _ref_block(self, cell: Mapping[str, Any], key: tuple[Any, ...]) -> np.ndarray:
        """Units x columns whose row mean is the cell's normaliser (no copy for a cache hit)."""
        option = self._normaliser_of(cell)
        if option == _DEFAULT_PRIMARY["normaliser"]:
            return self._matrix_arrays(key)[2][list(cell["refs"])].to_numpy(dtype=float)
        cached = self._norm_cache.get((option, key))
        if cached is None:
            assert self._normaliser_source is not None  # checked in __init__
            block = self._normaliser_source(option, self._matrix_arrays(key)[2])
            cached = np.asarray(block, dtype=float).reshape(len(self._samples), -1)
            self._norm_cache[(option, key)] = cached
        return cached

    def _reference_of(
        self, cell: Mapping[str, Any], key: tuple[Any, ...]
    ) -> tuple[np.ndarray, np.ndarray]:
        """Stage 3 for a cell: its normaliser per unit, and where the unit has one."""
        if self._normaliser_of(cell) == _DEFAULT_PRIMARY["normaliser"]:
            return self._reference(tuple(cell["refs"]), key)
        block = self._ref_block(cell, key)
        return block.mean(axis=1), ~np.isnan(block).any(axis=1)

    def redundant(self, cell: Mapping[str, Any]) -> bool:
        """True for a cell that repeats another analysis, which the grid leaves out.

        A normaliser other than ``planned`` does not read the ``refs`` choice, so only its cell
        with the primary ``refs`` is evaluated.
        """
        if self._normaliser_of(cell) == _DEFAULT_PRIMARY["normaliser"]:
            return False
        return tuple(cell["refs"]) != tuple(self.primary["refs"])

    def normaliser_label(self, cell: Mapping[str, Any]) -> str:
        """What the cell divides by, in words (the control genes, or the global mean)."""
        option = self._normaliser_of(cell)
        if option == _DEFAULT_PRIMARY["normaliser"]:
            return ", ".join(cell["refs"])
        return next(o.label for o in self.axes["normaliser"].options if o.id == option)

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
        ref_mean, refs_ok = self._reference_of({**cell, "refs": refs}, key)
        relative = values - ref_mean[:, None]
        valid = refs_ok[:, None] & ~np.isnan(relative)
        capped = self._capped.get((key, cell["undetermined"]))
        if self.comparisons:
            return self._compare(relative, valid, self._cmp, capped=capped)[0].results()
        in_high, in_rest = self._masks[cell["cut"] if self.design is not None else None]
        stats_hi = _group_stats(relative, valid & in_high[:, None])
        stats_lo = _group_stats(relative, valid & in_rest[:, None])
        untested = _none_detected(valid, capped, in_high, in_rest)
        return _welch_results(self.items, stats_hi, stats_lo, self.rule, untested)

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
        values, ref_values = self._cell_inputs(cell)
        ref_mean = ref_values.mean(axis=1)
        refs_ok = ~np.isnan(ref_values).any(axis=1)
        relative = values - ref_mean[:, None]
        valid = refs_ok[:, None] & ~np.isnan(relative)
        capped = self._capped_mask(cell)
        arrays = self._compare(relative, valid, self._cmp, with_ci=with_ci, capped=capped)
        return {spec.id: a for spec, a in zip(self.comparisons, arrays, strict=True)}

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
        return values, self._ref_block(cell, key)

    def _compare(
        self,
        relative: np.ndarray,
        valid: np.ndarray,
        masks: Sequence[_Masks],
        *,
        with_ci: bool = True,
        capped: np.ndarray | None = None,
    ) -> list[ContrastArrays]:
        """Each comparison's test on the same relative quantities, then the correction.

        ``capped`` (units x items) marks the values a non-detect rule filled in: a comparison
        with a group none of whose values was detected is not tested for that item.
        """
        out = []
        for spec, m in zip(self.comparisons, masks, strict=True):
            if spec.pairs is None:
                stats_a = _group_stats(relative, valid & m.in_a[:, None])
                stats_b = _group_stats(relative, valid & m.in_b[:, None])
                untested = _none_detected(valid, capped, m.in_a, m.in_b)
                out.append(
                    welch_arrays(
                        self.items, stats_a, stats_b, self.rule, with_ci=with_ci, untested=untested
                    )
                )
            else:
                differences = relative[m.idx_a] - relative[m.idx_b]
                complete = valid[m.idx_a] & valid[m.idx_b]
                stats = _group_stats(differences, complete)
                untested = None
                if capped is not None:
                    seen_a = (complete & ~capped[m.idx_a]).sum(axis=0)
                    seen_b = (complete & ~capped[m.idx_b]).sum(axis=0)
                    untested = (seen_a == 0) | (seen_b == 0)
                out.append(
                    paired_arrays(self.items, stats, self.rule, with_ci=with_ci, untested=untested)
                )
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
        order (another normaliser: the columns whose row mean it is, one column for the global
        mean). The primary cell when ``cell`` is ``None``.

        Raises:
            ValueError: Unknown amplification or undetermined option.
        """
        cell = self.primary if cell is None else cell
        amp_call = cell.get("amp_call", self._amp_primary)
        if amp_call not in self._offered["amp_call"]:
            raise ValueError(f"unknown amp_call option {amp_call!r}")
        key = self._matrix_key(cell)  # the stage caches :meth:`evaluate` reads (any matrix axis)
        values = self._nondetect_values(key, cell["undetermined"])
        ref_values = np.array(self._ref_block(cell, key), dtype=float)
        return np.array(values, dtype=float), ref_values

    def evaluate_arrays(
        self,
        values: np.ndarray,
        ref_values: np.ndarray,
        in_high: np.ndarray,
        in_rest: np.ndarray,
        capped: np.ndarray | None = None,
    ) -> ContrastArrays:
        """Every item's comparison from explicit arrays, with :meth:`evaluate`'s arithmetic.

        The normaliser is the row mean of ``ref_values``; a unit with any control value missing
        has no relative value. Nothing is re-derived: the masks are used as given.

        Args:
            values: Units x :attr:`items` ``log2(n0)`` (NaN = no value).
            ref_values: Units x control genes ``log2(n0)``.
            in_high: Boolean mask over :attr:`units`, the high group (group A).
            in_rest: Boolean mask over :attr:`units`, the comparison group (group B).
            capped: Units x :attr:`items`, the values a non-detect rule filled in
                (:meth:`cell_capped`); ``None``: none were.

        Returns:
            The arrays; :meth:`ContrastArrays.results` gives the :class:`ContrastResult` dict.
        """
        ref_mean = ref_values.mean(axis=1)
        refs_ok = ~np.isnan(ref_values).any(axis=1)
        relative = values - ref_mean[:, None]
        valid = refs_ok[:, None] & ~np.isnan(relative)
        if self.comparisons:
            masks = self._masks_with(in_high, in_rest)
            return self._compare(relative, valid, masks, capped=capped)[0]
        stats_hi = _group_stats(relative, valid & in_high[:, None])
        stats_lo = _group_stats(relative, valid & in_rest[:, None])
        untested = _none_detected(valid, capped, in_high, in_rest)
        return welch_arrays(self.items, stats_hi, stats_lo, self.rule, untested=untested)

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
            self.cell_capped(cell),
        )
        return out.results()

    def cell_capped(self, cell: Mapping[str, Any] | None = None) -> np.ndarray | None:
        """A copy of the values the cell's non-detect rule filled in (``None``: none were)."""
        mask = self._capped_mask(self.primary if cell is None else cell)
        return None if mask is None else mask.copy()


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
    untested: np.ndarray | None = None  # a group with no detected value (only capped ones)

    @property
    def half_ci(self) -> np.ndarray:
        """Half-width of the 95 % confidence interval on the log2 scale (NaN without a test)."""
        ok = (self.n_hi >= 2) & (self.n_lo >= 2)
        if self.untested is not None:
            ok = ok & ~self.untested
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
            self.untested,
        )


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

    def redundant(self, cell: Mapping[str, Any]) -> bool:
        """The space's own answer (see :meth:`QpcrSpace.redundant`)."""
        return self.space.redundant(cell)


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
    untested: np.ndarray | None = None,
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
    if untested is not None:
        tested = tested & ~untested
    p = np.where(tested, p, np.nan)
    with np.errstate(invalid="ignore"):
        significant = p < rule.alpha
    call = np.where(
        significant & (mean >= rule.min_log2fc),
        "up",
        np.where(significant & (mean <= -rule.min_log2fc), "down", "none"),
    )
    return ContrastArrays(
        tuple(items), mean, se, t, p, t_crit, n, n, call, rule, untested=_any(untested)
    )


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
    untested: np.ndarray | None = None,
) -> ContrastArrays:
    """Welch's test per item from per-group ``(n, mean, var)`` arrays (any common shape).

    The arrays may be per item (one analysis) or, broadcast, several analyses at once (rows =
    analyses, columns = items); ``items`` names the last axis. ``with_ci=False`` skips the
    t quantile (``t_crit`` is NaN): faster when only the fold change and the call are needed.
    ``untested`` marks items with a group none of whose values was detected (p = NaN, "none").
    """
    n_a, n_b = high[0], rest[0]
    diff, se, t, p, t_crit = _welch_core(high, rest, with_ci=with_ci)
    tested = (n_a >= 2) & (n_b >= 2)
    if untested is not None:
        tested = tested & ~untested
    p = np.where(tested, p, np.nan)
    with np.errstate(invalid="ignore"):
        significant = p < rule.alpha
    call = np.where(
        significant & (diff >= rule.min_log2fc),
        "up",
        np.where(significant & (diff <= -rule.min_log2fc), "down", "none"),
    )
    return ContrastArrays(
        tuple(items), diff, se, t, p, t_crit, n_a, n_b, call, rule, untested=_any(untested)
    )


def _any(mask: np.ndarray | None) -> np.ndarray | None:
    """``mask`` when it marks anything, else ``None`` (the arrays stay as they always were)."""
    return mask if mask is not None and bool(np.any(mask)) else None


def _none_detected(
    valid: np.ndarray, capped: np.ndarray | None, in_a: np.ndarray, in_b: np.ndarray
) -> np.ndarray | None:
    """Items where group A or group B has values but none detected (all filled in by a cap)."""
    if capped is None:
        return None
    seen = valid & ~capped
    return _any(~(seen & in_a[:, None]).any(axis=0) | ~(seen & in_b[:, None]).any(axis=0))


def group_stats(values: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, ...]:
    """Per-column count, mean and sample variance of ``values`` where ``mask`` is true."""
    return _group_stats(values, mask)


_DEFAULT_PRIMARY: dict[str, Any] = {
    "amp_call": DEFAULT_AMP_CALL,
    "efficiency": "linregpcr",
    "normaliser": "planned",
    "interrun": "none",
}


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
    untested: np.ndarray | None = None,
) -> dict[str, ContrastResult]:
    return _results(genes, _welch_core(high, rest), high[0], rest[0], rule, untested=untested)


def _results(
    genes: Sequence[str],
    welch: tuple[np.ndarray, ...],
    n_a: np.ndarray,
    n_b: np.ndarray,
    rule: ConclusionRule,
    p_call: np.ndarray | None = None,
    untested: np.ndarray | None = None,
) -> dict[str, ContrastResult]:
    diff, se, t, p, t_crit = welch
    call_p = p if p_call is None else p_call
    out = {}
    nan = float("nan")
    for i, gene in enumerate(genes):
        d = float(diff[i])
        # no p-value without two values on each side, nor for a group with none detected
        if n_a[i] < 2 or n_b[i] < 2 or (untested is not None and untested[i]):
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
