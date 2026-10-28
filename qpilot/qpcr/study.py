"""Run one qPCR study end to end: an RDML file in; results, Decision Cards and the grid out.

This is the one place where the qPCR plugin meets the domain-agnostic core:

1. curves (LinRegPCR on every plate) -> log2 quantities -> geNorm -> the decision space
   (:class:`qpilot.qpcr.space.QpcrSpace`);
2. ``core.robustness`` evaluates every cell of the space (186 analyses on the demo) and
   summarises each gene: primary conclusion, how often it holds, which choices flip it;
3. ``core.decisions`` turns the analysis choices into ranked Decision Cards and applies the
   escalation rule (a choice that can flip a conclusion is a human decision); the reference-set
   card then gains the flip count by normaliser-set size and the control-gene group-effect check
   (:func:`qpilot.qpcr.refgenes.group_effect`);
4. ``qpcr.confidence_checks`` and ``core.confidence`` grade every gene (capped for an instrument
   export whose curves were processed before export, :mod:`qpilot.io.trust`);
5. every number that prose may cite is registered as a fact (``core.facts``) under the id
   convention ``f_<metric>_<slug>_<context>``, e.g. ``f_fc_odc1_hmbs``.

A study runs from :class:`StudySettings`; :meth:`StudySettings.from_design` turns a confirmed
:class:`~qpilot.schemas_studio.StudyDesign` into settings. ``StudySettings()`` is the demo
analysis, and so is the demo preset (:func:`qpilot.qpcr.designs.vermeulen_design`). Any other
design may take its groups from a sample sheet (no ``cut`` dimension), average technical
replicates per biological unit, exclude or re-type wells, offer several amplification-call
rules (the ``amp_call`` dimension, screened before it enters the grid) and adds the Studio facts:
the usual route to Prism (:mod:`qpilot.qpcr.routes`) and the amp_call screening result.

A design with several comparisons, or a paired one (:class:`~qpilot.schemas_studio.
ComparisonPlan`), evaluates every comparison in every cell of the grid; the result's
``contrasts``, cards and grades stay the primary comparison's (with Holm's correction their calls
use the corrected p), and ``StudyResult.comparisons`` adds each comparison's results, corrected
p-values, q-values, robustness and grades. Each comparison's own grid travels with the primary
grid (:func:`comparison_grid_of`) and is written as ``grid_comparisons.csv``.

A biological unit with no well of some gene is left out of that gene only (``f_not_measured_*``
facts say which); before, it was left out of every gene.

Deterministic: the same file and settings give byte-identical output, which ``qpilot rerun``
relies on. No model is called and nothing touches the network.
"""

from __future__ import annotations

import hashlib
import logging
import re
import statistics
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from qpilot.core import robustness
from qpilot.core.confidence import Cap, grade
from qpilot.core.decisions import CardSpec, OptionSpec, View, build_cards, card_impact
from qpilot.core.facts import FactRegistry, slug
from qpilot.core.store import atomic_write, dump_json
from qpilot.io.trust import cap_for, not_measured
from qpilot.qpcr import interrun as irc
from qpilot.qpcr.amp_call import (
    DEFAULT_AMP_CALLS,
    METHOD_CARD_PATH,
    RECOMMENDED,
    RULES,
    AmpScreen,
    apply_rule,
    screen_amp_call,
)
from qpilot.qpcr.axes import efficiency as eff_axis
from qpilot.qpcr.axes import get_axis
from qpilot.qpcr.axes import normaliser as norm_axis
from qpilot.qpcr.confidence_checks import START_LEVEL, checks_for, mde_fold, upgrade_rule
from qpilot.qpcr.contrast import (
    CORRECTION_WORDS,
    DEFAULT_RULE,
    TEST_WORDS,
    ConclusionRule,
    bh,
    welch_anova,
)
from qpilot.qpcr.curves import (
    DEMO_EXPERIMENT,
    INSTRUMENT_CQ,
    REFERENCE_TARGETS,
    CurveSettings,
    analyse_study,
)
from qpilot.qpcr.design import (
    DEMO_GROUP_VAR,
    DEMO_MARKER,
    GroupSpec,
    design_summary,
    groups_by_cut,
)
from qpilot.qpcr.designs import (
    HEADLINE_GENES,
    DesignError,
    check_design,
    design_curves,
    design_units,
    is_legacy_design,
    pairs_for,
    study_key,
    unit_groups,
)
from qpilot.qpcr.multiplicity import CORRECTIONS_POOLED
from qpilot.qpcr.quant import EXCLUDED, Undetermined, left_out_cells, log2_matrix
from qpilot.qpcr.quant import not_measured as units_not_measured
from qpilot.qpcr.refgenes import RefGroupEffect, genorm, group_effect
from qpilot.qpcr.routes import ROUTES, RouteResult, compare_routes
from qpilot.qpcr.space import (
    DEFAULT_CUTS,
    DEFAULT_UNDETERMINED,
    ComparisonSpec,
    MatrixStage,
    QpcrSpace,
    comparison_grid,
    group_stats,
)
from qpilot.schemas import (
    Autonomy,
    ComparisonOutcome,
    ComparisonsResult,
    DecisionCard,
    DesignSummary,
    Fact,
    GeneRobustness,
    GenormResult,
    Grade,
    Omnibus,
    StudyResult,
)
from qpilot.schemas_studio import StudyDesign

log = logging.getLogger(__name__)

HOLDS_LOW = 0.80  # "holds in fewer than 80 %" is counted in f_n_hold_lt_80
FC_FMT = "{:.2g}"
COUNT_FMT = "{:,}"  # 24576 -> 24,576
TIMES = "×"
_NUMBER_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}
NOT_RECOMMENDED_NOTE = (
    "MIQE recommends normalising to more than one validated reference gene; a single gene is "
    "what a ΔΔCt spreadsheet does"
)
GENORM_NOTE = (
    "geNorm M ranks stability across all samples; it cannot show whether a control gene differs "
    "between the groups. The pairwise ratios below check that."
)
GROUPS_NOTE = "groups from the confirmed design"
AMP_CALL_TITLE = "Which curves count as amplified"
_REFSET_EXTRA_FACTS = (
    "f_n_flipped_refset_min3",
    "f_n_flipped_refset_single_only",
    "f_ref_pair_top",
    "f_ref_ratio_top",
    "f_ref_ratio_top_p",
    "f_n_ref_pairs_flagged",
    "f_n_ref_pairs",
    "f_ref_flag_fold",
)


class NGuardError(ValueError):
    """A comparison group has fewer than two biological units, so no p-value can be given."""


#: Where a study's per-comparison grid travels with the primary grid (``DataFrame.attrs``).
COMPARISON_GRID_ATTR = "qpilot_comparison_grid"
COMPARISON_GRID_FILE = "grid_comparisons.csv"


def comparison_grid_of(grid: pd.DataFrame | None) -> pd.DataFrame | None:
    """Every comparison's grid of a study with several comparisons (``None`` otherwise).

    :func:`study_from_curves` attaches it to the primary grid it returns, so every caller that
    stores a grid can store this one too (``grid_comparisons.csv``) without a new return value.
    """
    if grid is None or not isinstance(grid, pd.DataFrame):
        return None
    return grid.attrs.get(COMPARISON_GRID_ATTR)


def comparison_grid_csv(frame: pd.DataFrame) -> str:
    """CSV text of a comparison grid, written exactly as ``grid.csv`` is."""
    return robustness.to_csv_frame(frame).to_csv(
        index=False, float_format="%.10g", lineterminator="\n"
    )


@dataclass(frozen=True)
class StudySettings:
    """Every choice that shapes a study's output; the defaults reproduce the demo analysis.

    ``design`` is the confirmed design for anything but the legacy demo analysis (``None``
    then); ``amp_calls`` are the options of the amplification-call dimension, primary first
    (one option: no dimension); ``studio_facts`` adds the Studio facts (the routes to Prism and
    the amp_call screening), which the legacy output does not carry. ``efficiency`` are the
    options of the efficiency-model axis, primary first (opt-in; one option: no axis, see
    :mod:`qpilot.qpcr.axes.efficiency`); ``max_cells`` caps the grid with seeded sampling
    (:func:`qpilot.core.robustness.run_grid`; ``None``: the full product). ``normaliser``
    (:mod:`qpilot.qpcr.axes.normaliser`) and ``interrun`` (:mod:`qpilot.qpcr.interrun`) are
    the options of the normaliser and the between-plate correction axes, opt-in the same way.
    """

    experiment_id: str | None = DEMO_EXPERIMENT
    candidates: tuple[str, ...] = REFERENCE_TARGETS
    marker: str = DEMO_MARKER
    group_var: str = DEMO_GROUP_VAR
    cut: float = 0.15
    cuts: tuple[float, ...] = DEFAULT_CUTS
    undetermined: tuple[Undetermined, ...] = DEFAULT_UNDETERMINED
    headline: tuple[str, ...] = HEADLINE_GENES
    rule: ConclusionRule = DEFAULT_RULE
    curves: CurveSettings = field(default_factory=CurveSettings)
    autonomy: Autonomy = "suggest"
    amp_calls: tuple[str, ...] = DEFAULT_AMP_CALLS
    design: StudyDesign | None = None
    studio_facts: bool = False
    efficiency: tuple[str, ...] = (eff_axis.PRIMARY,)
    max_cells: int | None = None
    normaliser: tuple[str, ...] = (norm_axis.PRIMARY,)
    interrun: tuple[str, ...] = (irc.PRIMARY,)

    @property
    def marker_label(self) -> str:
        """The marker gene's name without its assay suffix: ``MYCN(4)`` -> ``MYCN``."""
        return re.sub(r"\(.*\)$", "", self.marker).strip() or self.marker

    @property
    def groups_mode(self) -> bool:
        """True when the groups come from the design (no marker gene, no ``cut`` dimension)."""
        return self.design is not None and self.design.mode == "groups"

    @classmethod
    def from_design(cls, design: StudyDesign) -> StudySettings:
        """Settings that run a confirmed design.

        The demo preset (:func:`qpilot.qpcr.designs.vermeulen_design`) gives exactly
        ``StudySettings()``, so its output is the legacy output byte for byte. Any other design
        is carried in ``design`` and switches the Studio facts on; its ``axes`` give the options
        of the opt-in axes a person asked to test (``efficiency``, ``normaliser``,
        ``interrun``). Control-gene candidates are
        ``reference_candidates``, or (when that is empty) the targets whose role is ``ref``,
        sorted by name.

        Raises:
            DesignError: The design breaks a rule :func:`qpilot.qpcr.designs.check_design`
                checks.
        """
        check_design(design)
        legacy = is_legacy_design(design)
        candidates = tuple(design.reference_candidates) or tuple(
            sorted(t for t, target in design.targets.items() if target.role == "ref")
        )
        values: dict = {
            "experiment_id": design.experiment_id,
            "candidates": candidates,
            "headline": tuple(design.headline),
            "amp_calls": tuple(design.amp_calls),
            "design": None if legacy else design,
            "studio_facts": not legacy,
            "efficiency": tuple((design.axes or {}).get("efficiency", (eff_axis.PRIMARY,))),
            "normaliser": tuple((design.axes or {}).get("normaliser", (norm_axis.PRIMARY,))),
            "interrun": tuple((design.axes or {}).get("interrun", (irc.PRIMARY,))),
        }
        trust = design.import_trust
        if trust is not None and trust.analysis == "cq_only":  # the Import Trust card's Cq only
            values["curves"] = CurveSettings(quantities=INSTRUMENT_CQ)
        if design.mode == "marker_split" and design.marker_split is not None:
            split = design.marker_split
            values.update(
                marker=split.marker, group_var=split.group_var, cut=split.cut, cuts=split.cuts
            )
        return cls(**values)


def run_study(
    rdml_path: str | Path,
    settings: StudySettings | None = None,
    *,
    cache_dir: str | Path | None = None,
) -> tuple[StudyResult, list[DecisionCard], pd.DataFrame]:
    """Analyse one RDML file.

    Args:
        rdml_path: The instrument export (RDML 1.0–1.4, plain or zipped).
        settings: Analysis choices; defaults reproduce the demo analysis.
        cache_dir: Curve-cache directory (default ``$QPILOT_CACHE_DIR`` or ``~/.cache/qpilot``).

    Returns:
        ``(result, cards, grid)``: the study result with confidence grades and facts, the ranked
        Decision Cards, and the robustness grid (one row per analysis x gene).
    """
    settings = settings or StudySettings()
    path = Path(rdml_path)
    curves = analyse_study(
        path, settings.experiment_id, settings.candidates, settings.curves, cache_dir=cache_dir
    )
    return study_from_curves(curves, _sha256(path), settings)


@dataclass(frozen=True)
class _Inputs:
    """The per-well table as the design says, and the matrices the space is built from."""

    table: pd.DataFrame  # design applied, before any amplification rule
    primary_table: pd.DataFrame  # ... under the primary amplification rule
    units: dict[str, str] | None
    matrix: pd.DataFrame
    alternatives: dict[str, pd.DataFrame]
    excluded: pd.DataFrame | None  # values left out under every option (excluded / not measured)
    not_amplified: dict[str, int]  # study wells without a value, per amplification rule
    not_measured: dict[str, list[str]] = field(default_factory=dict)  # gene -> units without it


def _inputs(
    curves: pd.DataFrame, settings: StudySettings, extra_excluded: Collection[str] = ()
) -> _Inputs:
    design = settings.design
    legacy = design is None and settings.amp_calls == DEFAULT_AMP_CALLS
    if legacy and not extra_excluded:  # the legacy path (the demo: every unit has every gene)
        matrix = log2_matrix(curves)
        missing = units_not_measured(curves)
        left_out = left_out_cells(curves) if missing else None
        return _Inputs(curves, curves, None, matrix, {}, left_out, {}, missing)
    table = design_curves(curves, design) if design is not None else curves
    if extra_excluded:
        table = _with_excluded(table, extra_excluded)
    units = (design_units(design) or None) if design is not None else None
    calls = dict(design.well_calls) if design is not None else {}
    tables = {rule_id: apply_rule(table, rule_id, calls) for rule_id in settings.amp_calls}
    primary, *others = settings.amp_calls
    return _Inputs(
        table=table,
        primary_table=tables[primary],
        units=units,
        matrix=log2_matrix(tables[primary], units),
        alternatives={rule_id: log2_matrix(tables[rule_id], units) for rule_id in others},
        excluded=left_out_cells(table, units),
        not_amplified={rule_id: _counts(t)["n_undetermined"] for rule_id, t in tables.items()},
        not_measured=units_not_measured(table, units),
    )


def _with_excluded(table: pd.DataFrame, keys: Collection[str]) -> pd.DataFrame:
    """A copy of ``table`` with the wells ``run_id/well`` in ``keys`` also marked excluded."""
    out = table.copy()
    hit = (out["run_id"] + "/" + out["well"]).isin(set(keys)).to_numpy()
    already = out[EXCLUDED].astype(bool).to_numpy() if EXCLUDED in out.columns else False
    out[EXCLUDED] = hit | already
    return out


def _counts(table: pd.DataFrame) -> dict[str, int]:
    """Undetermined and total study wells (wells a person excluded are not counted)."""
    unknown = table[table["sample_type"] == "unkn"]
    if EXCLUDED in unknown.columns:
        unknown = unknown[~unknown[EXCLUDED].astype(bool)]
    return {"n_undetermined": int(unknown["n0"].isna().sum()), "n_unknown_wells": len(unknown)}


def _stability(matrix: pd.DataFrame, candidates: tuple[str, ...]) -> GenormResult:
    """Control-gene stability: geNorm for three or more candidates; no ranking with fewer.

    With two candidates M is the SD of their log2 ratio (the same for both); with one it is
    undefined. Either way every candidate is used and no V is reported.
    """
    if len(candidates) >= 3:
        return genorm(matrix, candidates)
    m: dict[str, float] = {}
    if len(candidates) == 2:
        a, b = candidates
        sd = float((matrix[a] - matrix[b]).dropna().std(ddof=1))
        m = {a: sd, b: sd}
    return GenormResult(M_initial=m, order=list(candidates), V={}, recommended=candidates)


def _design_groups(
    design: StudyDesign, table: pd.DataFrame, matrix: pd.DataFrame
) -> tuple[tuple[frozenset[str], frozenset[str]], tuple[str, str]]:
    """The compared units of a groups design's primary comparison (see :func:`_units_of`)."""
    comparison = design.comparison
    names = (comparison.group_a, comparison.group_b)
    return _units_of(design, table, matrix, names), names


def _units_of(
    design: StudyDesign, table: pd.DataFrame, matrix: pd.DataFrame, names: Sequence[str]
) -> tuple[frozenset[str], ...]:
    """The units of each named group that are study units of the matrix, in ``names`` order.

    ``table`` is the per-well table as the design says (:func:`design_curves`). A sample of the
    groups with no study well there (the file types it otherwise, and no accepted decision
    re-typed it) is not a study sample, so it is left out of n; the log names it and its type.
    """
    by_unit = unit_groups(design)
    compared = {s for s, d in design.samples.items() if d.group in names}
    absent = sorted(compared - set(table["sample"]))
    if absent:
        raise DesignError(f"samples of the comparison groups not in the data: {absent[:5]}")
    studied = set(table.loc[table["sample_type"] == "unkn", "sample"])
    typed = table[table["sample"].isin(compared - studied)].groupby("sample")["sample_type"]
    left_out = [f"{s} ({', '.join(sorted(set(types)))})" for s, types in typed]
    if left_out:
        log.warning(
            "samples of the comparison groups that are not study samples are left out: %s",
            "; ".join(left_out),
        )
    present = set(matrix.index)
    return tuple(
        frozenset(u for u, g in by_unit.items() if g == name and u in present) for name in names
    )


def _design_comparisons(
    design: StudyDesign, table: pd.DataFrame, matrix: pd.DataFrame
) -> tuple[ComparisonSpec, ...]:
    """Every comparison of a design with a :class:`ComparisonPlan`, primary first.

    Each group needs two biological units; a paired plan needs every compared unit to have its
    pair key and each pair one unit in each group of a comparison (:func:`pairs_for`).

    Raises:
        NGuardError: A group has fewer than two units, or a comparison fewer than two pairs.
        DesignError: A paired comparison whose units do not pair up.
    """
    plan = design.comparisons
    assert plan is not None
    names = plan.groups()
    units = dict(zip(names, _units_of(design, table, matrix, names), strict=True))
    specs = []
    for comparison in plan.comparisons:
        a, b = comparison.group_a, comparison.group_b
        _n_guard((units[a], units[b]), (a, b))
        pairs = keys = None
        if plan.pair_by is not None:
            pairs, keys = pairs_for(design, units[a], units[b], (a, b), plan.pair_by)
            if len(pairs) < 2:
                raise NGuardError(
                    f"the p-value of {comparison.title()} is withheld: it has "
                    f"{len(pairs)} complete pair(s) of {plan.pair_by}; a paired test needs two"
                )
        specs.append(
            ComparisonSpec(
                id=comparison.key(),
                labels=(a, b),
                group_a=units[a],
                group_b=units[b],
                pairs=pairs,
                pair_keys=keys or (),
            )
        )
    return tuple(specs)


def comparison_units(model: StudyModel) -> dict[str, tuple[frozenset, frozenset, tuple | None]]:
    """Per comparison id: ``(units of A, units of B, pairs or None)``, the primary first.

    One entry (the primary, ``"primary"`` for a study without a plan) when the study has one
    comparison. Pairs are ``(unit in A, unit in B)`` in pair-key order, for per-unit tables.
    """
    if model.space.comparisons:
        return {s.id: (s.group_a, s.group_b, s.pairs) for s in model.space.comparisons}
    design = model.settings.design
    key = design.comparison.key() if design is not None and design.comparison else "primary"
    return {key: (model.high, model.rest, None)}


def _n_guard(groups: tuple[frozenset[str], frozenset[str]], labels: tuple[str, str]) -> None:
    """Refuse a comparison with fewer than two biological units in a group (never wells)."""
    pairs = zip(labels, groups, strict=True)
    short = [f"{label} has {len(units)}" for label, units in pairs if len(units) < 2]
    if short:
        raise NGuardError(
            "the p-value is withheld because a group has fewer than two biological units "
            f"({'; '.join(short)}); every group needs at least two"
        )


@dataclass(frozen=True, eq=False)
class StudyModel:
    """The decision space of a study and what it was built from (no grid, no cards yet).

    :func:`study_from_curves` builds its outputs from this, and the Prism bridge rebuilds a
    stored study's per-unit values from the same object, so both always use one arithmetic.
    ``labels`` are the two groups' names (``None`` for the demo's expression-defined split);
    ``high`` and ``rest`` are the primary comparison's units (``group_a``, ``group_b``).
    """

    settings: StudySettings
    inputs: _Inputs
    matrix: pd.DataFrame
    stability: GenormResult
    space: QpcrSpace
    labels: tuple[str, str] | None
    screen: AmpScreen | None
    high: frozenset[str]
    rest: frozenset[str]
    screens: dict[str, robustness.AxisScreen] = field(default_factory=dict)
    axis_notes: dict[str, dict] = field(default_factory=dict)  # per opt-in axis, for facts
    tables: CellTables | None = None

    def cell_table(self, cell: Mapping[str, Any]) -> pd.DataFrame:
        """The per-well table a cell's matrix is built from (see :class:`CellTables`)."""
        if self.tables is None:
            return self.inputs.primary_table
        return self.tables.table(cell)

    def cell_stage(self, cell: Mapping[str, Any]) -> MatrixStage:
        """Units x genes ``log2 N0`` of a cell, with the values every well of which is left out."""
        if self.tables is None:
            return MatrixStage(self.matrix, self.inputs.excluded)
        return self.tables.stage(cell)


@dataclass(frozen=True, eq=False)
class CellTables:
    """The per-well table under any combination of matrix-stage options.

    One arithmetic for the decision space's matrices, Trace and the Prism export: the design's
    per-well table, the efficiency model's quantities (LinRegPCR's own for the primary, passed
    through untouched), then the amplification rule. A cell that leaves out an option uses its
    primary; the primaries give exactly the table the primary matrix was built from.
    """

    inputs: _Inputs
    amp_primary: str
    legacy: bool  # the legacy demo path: no amplification rule is applied
    calls: Mapping[str, bool]
    curves: Mapping[tuple[str, str], eff_axis.StdCurve]

    def table(self, cell: Mapping[str, Any]) -> pd.DataFrame:
        """The per-well table under the cell's rule, efficiency model and plate correction.

        The correction between plates (:mod:`qpilot.qpcr.interrun`) comes last, on the wells
        the rule counts as amplified.
        """
        amp = str(cell.get("amp_call", self.amp_primary))
        efficiency = str(cell.get("efficiency", eff_axis.PRIMARY))
        between = str(cell.get("interrun", irc.PRIMARY))
        if efficiency == eff_axis.PRIMARY and amp == self.amp_primary:
            table = self.inputs.primary_table
        else:
            table = eff_axis.universe(self.inputs.table, efficiency, self.curves).table
            table = table if self.legacy else apply_rule(table, amp, self.calls)
        return table if between == irc.PRIMARY else irc.correct(table, between).table

    def stage(self, cell: Mapping[str, Any]) -> MatrixStage:
        """Units x genes ``log2 N0`` of the cell's table, and the values left out entirely."""
        table = self.table(cell)
        units = self.inputs.units
        return MatrixStage(log2_matrix(table, units), left_out_cells(table, units))


def build_model(
    curves: pd.DataFrame,
    settings: StudySettings | None = None,
    *,
    extra_excluded: Collection[str] = (),
) -> StudyModel:
    """The study's decision space from the per-well table and the settings.

    ``extra_excluded`` are well keys (``run_id/well``) to leave out as a person's exclusion
    would, on top of the design's; Run Gate's consequence test uses it to ask "what if these
    wells were excluded?". Empty (the default) changes nothing.

    Raises:
        NGuardError: A comparison group has fewer than two biological units.
        DesignError: The design does not fit the data (unknown wells or samples).
    """
    settings = settings or StudySettings()
    if not settings.candidates:
        raise DesignError("no control genes: set reference_candidates or mark targets as ref")
    inputs = _inputs(curves, settings, extra_excluded)
    matrix = inputs.matrix
    unmeasured = [gene for gene in settings.candidates if gene not in matrix.columns]
    if unmeasured:  # e.g. the target of a LightCycler 96's "no target" wells, accepted as ref
        raise DesignError(
            f"the reference gene {', '.join(repr(g) for g in unmeasured)} has no value in any "
            "study sample (no study well measures it), so it cannot normalise them: keep as "
            "reference genes only targets measured in the study samples"
        )
    stability = _stability(matrix, settings.candidates)
    groups = labels = None
    specs: tuple[ComparisonSpec, ...] = ()
    if settings.groups_mode:
        groups, labels = _design_groups(settings.design, inputs.table, matrix)
        _n_guard(groups, labels)
        if settings.design.comparisons is not None:
            specs = _design_comparisons(settings.design, inputs.table, matrix)
    spec = None
    if groups is None:
        spec = GroupSpec(settings.marker, settings.cut, settings.candidates, settings.group_var)
    options = dict(
        candidates=settings.candidates,
        cuts=settings.cuts,
        undetermined=settings.undetermined,
        rule=settings.rule,
        groups=groups,
        amp_call=settings.amp_calls[0],
        excluded=inputs.excluded,
        group_labels=labels,
    )
    if specs:
        plan = settings.design.comparisons
        options.update(comparisons=specs, correction=plan.correction, control=plan.control)
    efficiency, eff_notes, tables = _efficiency_axis(inputs, settings)
    between, irc_notes = _interrun_axis(inputs, settings, tables)
    if between:
        efficiency = {
            "matrix_axes": {**efficiency.get("matrix_axes", {}), **between["matrix_axes"]},
            "matrix_source": tables.stage,
            "unavailable": {**efficiency.get("unavailable", {}), **between["unavailable"]},
        }
    normalisers, norm_notes = _normaliser_axis(
        matrix, stability, settings, inputs, groups, specs, spec
    )
    if normalisers:
        unavailable = {**efficiency.get("unavailable", {}), **normalisers.pop("unavailable")}
        efficiency = {**efficiency, "unavailable": unavailable}
    space = QpcrSpace(
        matrix,
        stability,
        spec,
        amp_alternatives=inputs.alternatives,
        **options,
        **efficiency,
        **normalisers,
    )
    screen = None
    if inputs.alternatives:
        dims = space.dimensions["amp_call"]
        screen = screen_amp_call(space.evaluate, space.primary, dims, space.items)
        if not screen.admitted:  # the choice changes nothing that matters: no axis in the grid
            space.hold("amp_call", "screened_out", SCREENED_REASON)
    screens = {}
    for name in ("efficiency", "normaliser"):
        if name in space.dimensions:
            screens[name] = robustness.screen_axis(space, name)
            if not screens[name].admitted:
                space.hold(name, "screened_out", SCREENED_REASON)
    if "interrun" in space.dimensions:  # a card only when a correction flips a call
        screen = robustness.screen_axis(space, "interrun")
        screens["interrun"] = replace(screen, admitted=any(screen.flipped.values()))
        if not screens["interrun"].admitted:
            space.hold("interrun", "screened_out", INTERRUN_SCREENED_REASON)
    high, rest = space.groups(settings.cut)
    if groups is None:
        _n_guard((high, rest), (settings.group_var, "rest"))
    notes = {"efficiency": eff_notes} if eff_notes else {}
    if norm_notes:
        notes["normaliser"] = norm_notes
    if irc_notes:
        notes["interrun"] = irc_notes
    return StudyModel(
        settings,
        inputs,
        matrix,
        stability,
        space,
        labels,
        screen,
        high,
        rest,
        screens,
        notes,
        tables,
    )


SCREENED_REASON = (
    "no option, changed alone, flips a conclusion or moves a log2 fold change by more than 0.5"
)
INTERRUN_SCREENED_REASON = "no correction between plates, changed alone, flips a conclusion"


def _interrun_axis(
    inputs: _Inputs, settings: StudySettings, tables: CellTables
) -> tuple[dict, dict]:
    """``QpcrSpace`` keywords and notes for the correction between plates (opt-in).

    Nothing when only ``none`` is offered. An option that cannot change anything here (every
    gene on one plate, no calibrator on each plate of a split gene, no measurement two plates
    share) is not offered and is reported, asked for or not. The corrected matrices come from
    the study's :class:`CellTables` (the correction follows the rule and the efficiency model).
    """
    offered = tuple(settings.interrun)
    if offered == (irc.PRIMARY,):
        return {}, {}
    if not offered or offered[0] != irc.PRIMARY:
        raise DesignError(f"the inter-run options must start with {irc.PRIMARY!r}")
    for option in offered:
        if option not in irc.OPTIONS:
            raise DesignError(f"unknown inter-run option {option!r}")
    table = inputs.primary_table
    every = irc.unavailable(table)
    missing = {k: v for k, v in every.items() if k in offered}
    kept = [o for o in offered if o not in missing]
    notes: dict = {"unavailable": missing, **irc.summary(table)}
    if "calibrator" in kept:
        notes["calibrator_uncorrected"] = list(irc.calibrate(table).uncorrected)
    if "factor" in kept:
        factors, unlinked = irc.plate_factors(table)
        notes["plate_factors"] = {run: round(value, 6) for run, value in factors.items()}
        notes["factor_uncorrected"] = list(unlinked)
    keywords = {
        "matrix_axes": {"interrun": kept},
        "matrix_source": tables.stage,
        "unavailable": {"interrun": every},
    }
    return keywords, notes


def _normaliser_groups(
    settings: StudySettings,
    matrix: pd.DataFrame,
    groups: tuple[frozenset[str], frozenset[str]] | None,
    spec: GroupSpec | None,
    refs: tuple[str, ...],
) -> tuple[dict[str, str | None], frozenset[str], frozenset[str]]:
    """Unit -> group for NormFinder, and the primary comparison's two groups.

    A design's groups are every group of the design (several comparisons share them); the
    demo's expression-defined split is the primary cut-off's high group and the rest.
    """
    if groups is None:
        assert spec is not None
        primary = GroupSpec(spec.marker, spec.cut, refs, spec.group_var)
        high, rest = groups_by_cut(matrix, primary, [spec.cut])[spec.cut]
        label = {**{u: "high" for u in high}, **{u: "rest" for u in rest}}
        return {u: label.get(u) for u in matrix.index}, high, rest
    by_unit = unit_groups(settings.design) if settings.design is not None else {}
    return {u: by_unit.get(u) for u in matrix.index}, groups[0], groups[1]


def _normaliser_axis(
    matrix: pd.DataFrame,
    stability: GenormResult,
    settings: StudySettings,
    inputs: _Inputs,
    groups: tuple[frozenset[str], frozenset[str]] | None,
    specs: tuple[ComparisonSpec, ...],
    spec: GroupSpec | None,
) -> tuple[dict, dict]:
    """``QpcrSpace`` keywords and notes for the normaliser axis (opt-in).

    Nothing when only ``planned`` is offered. The best pairs (NormFinder with the study's
    groups, geNorm) and the global mean's genes come from the primary matrix and stay fixed
    across the grid; each cell reads their values from its own matrix.
    """
    offered = tuple(settings.normaliser)
    if offered == (norm_axis.PRIMARY,):
        return {}, {}
    if not offered or offered[0] != norm_axis.PRIMARY:
        raise DesignError(f"the normaliser options must start with {norm_axis.PRIMARY!r}")
    for option in offered:
        if option not in norm_axis.OPTIONS:
            raise DesignError(f"unknown normaliser option {option!r}")
    candidates = settings.candidates
    refs = tuple(g for g in candidates if g in set(stability.recommended))
    labels, high, rest = _normaliser_groups(settings, matrix, groups, spec, refs)
    plan = norm_axis.plan(matrix, candidates, stability, refs, labels, offered, high, rest)
    missing = {k: v for k, v in plan.unavailable.items() if k in offered}
    notes: dict = {"unavailable": missing, **plan.evidence}

    def source(option: str, block: pd.DataFrame) -> np.ndarray:
        return norm_axis.normaliser_values(option, refs, block, plan)

    keywords = {
        "normaliser": list(plan.options),
        "normaliser_source": source,
        "unavailable": {"normaliser": plan.unavailable},
    }
    return keywords, notes


def _efficiency_axis(inputs: _Inputs, settings: StudySettings) -> tuple[dict, dict, CellTables]:
    """``QpcrSpace`` keywords and notes for the efficiency axis, and the study's cell tables.

    No keywords and no notes when only the primary is offered. Options that do not apply to
    the study (no dilution series, every amplicon on one run, an efficiency the imported curves'
    processing rules out: :func:`qpilot.io.trust.not_measured`) are not offered and are
    reported with the reason, asked for or not. The matrix of any other option is rebuilt
    from Cq and the per-run threshold, under the same amplification rule and design
    (:class:`CellTables`).
    """
    offered = tuple(settings.efficiency)
    legacy = settings.design is None and settings.amp_calls == DEFAULT_AMP_CALLS
    calls = dict(settings.design.well_calls) if settings.design is not None else {}
    if offered == (eff_axis.PRIMARY,):
        return {}, {}, CellTables(inputs, settings.amp_calls[0], legacy, calls, {})
    if not offered or offered[0] != eff_axis.PRIMARY:
        raise DesignError(f"the efficiency options must start with {eff_axis.PRIMARY!r}")
    for option in offered:
        if option not in eff_axis.OPTIONS:
            raise DesignError(f"unknown efficiency option {option!r}")
    quantities = None
    if settings.design is not None:
        quantities = {s: d.quantity for s, d in settings.design.samples.items() if d.quantity}
    curves = eff_axis.standard_curves(inputs.table, quantities)
    every = eff_axis.unavailable(inputs.table, curves)  # asked for or not: said in the facts
    trust = settings.design.import_trust if settings.design is not None else None
    every.update(not_measured(trust))
    missing = {k: v for k, v in every.items() if k in offered}
    kept = [o for o in offered if o not in missing]
    tables = CellTables(inputs, settings.amp_calls[0], legacy, calls, curves)
    notes: dict = {"unavailable": missing}
    if "per_well" in kept:
        notes["n_excluded_per_well"] = eff_axis.universe(inputs.table, "per_well").n_excluded
    if "standard_curve" in kept:
        fallback = eff_axis.universe(inputs.table, "standard_curve", curves).fallback
        notes["std_curve_fallback"] = list(fallback)
    keywords = {
        "matrix_axes": {"efficiency": kept},
        "matrix_source": tables.stage,
        "unavailable": {"efficiency": every},
    }
    return keywords, notes, tables


def study_from_curves(
    curves: pd.DataFrame, input_sha256: str, settings: StudySettings | None = None
) -> tuple[StudyResult, list[DecisionCard], pd.DataFrame]:
    """Everything after curve analysis, on the per-well table (see :func:`run_study`).

    Raises:
        NGuardError: A comparison group has fewer than two biological units.
        DesignError: The design does not fit the data (unknown wells or samples).
    """
    settings = settings or StudySettings()
    model = build_model(curves, settings)
    inputs, matrix, stability, space = model.inputs, model.matrix, model.stability, model.space
    labels, screen, high, rest = model.labels, model.screen, model.high, model.rest
    grid = robustness.run_grid(space, max_cells=settings.max_cells)
    summary = robustness.summary(grid, space)
    fragility = robustness.fragility(grid, space)
    counts = _counts(inputs.primary_table)
    base = StudyResult(
        study_id=study_key(input_sha256, settings.design)[:12],
        input_sha256=input_sha256,
        n_plates=int(curves["run_id"].nunique()),
        n_reactions=len(curves),
        n_samples=len(matrix),
        design=_summary_of_design(high, rest, space, labels),
        genorm=stability,
        contrasts=space.evaluate(space.primary),
        robustness=summary,
        efficiency=_efficiency(curves),
        conclusion_rule=settings.rule.as_dict(),
    )
    cap = cap_for(settings.design.import_trust if settings.design is not None else None)
    confidence = {gene: _grade(gene, base, fragility, cap) for gene in space.items}
    outcomes = None
    if space.comparisons:
        every = comparison_grid(space, grid)
        grid.attrs[COMPARISON_GRID_ATTR] = every
        primary = (base.contrasts, summary, confidence)
        outcomes = _comparison_outcomes(space, every, base, primary, settings, cap)
    headline = [gene for gene in settings.headline if gene in space.items]
    views = _card_views(space, outcomes, grid)
    others = [view.summary for view in views.values()]
    specs = _card_specs(space, stability, summary, settings, headline, counts, others)
    if "amp_call" in space.dimensions:
        specs.append(_amp_call_spec(space, grid, summary, headline, inputs.not_amplified))
    if "efficiency" in space.dimensions:
        specs.append(_efficiency_spec(space, grid, summary, headline, model.axis_notes))
    if "normaliser" in space.dimensions:
        specs.append(_normaliser_spec(space, grid, summary, headline, model.axis_notes))
    if "interrun" in space.dimensions:
        specs.append(_interrun_spec(space, grid, summary, headline, model.axis_notes))
    cards = build_cards(
        space,
        summary,
        specs,
        headline,
        settings.autonomy,
        grid=grid,
        views=views,
        primary_view=space.comparisons[0].id if space.comparisons else "primary",
    )
    ref_flips = refset_flip_counts(grid, space, summary)
    ref_effect = group_effect(matrix, settings.candidates, high, rest)
    cards = [_refset_extras(card, ref_flips, ref_effect) for card in cards]
    routes = None
    if settings.studio_facts:
        primary = {gene: summary[gene].conclusion for gene in space.items}
        calls = settings.design.well_calls if settings.design is not None else None
        routes = compare_routes(
            inputs.table,
            inputs.units,
            list(matrix.index),
            high,
            rest,
            space.primary["refs"],
            primary,
            settings.rule,
            calls,
            amp_call=settings.amp_calls[0],
        )
    extras = _Extras(
        withheld=space.withheld,
        detected_only=detected_only_dcq(model),
        screen=screen if settings.studio_facts else None,
        routes=routes,
        groups=labels,
        axis_notes=model.axis_notes,
        axes=space.axes,
        screens=model.screens,
        not_measured=_not_measured_words(inputs.not_measured, settings.candidates),
        comparisons=outcomes,
        dimensions=tuple(space.dimensions),
    )
    facts = _facts(base, confidence, cards, space, settings, headline, counts, extras)
    update: dict[str, Any] = {"confidence": confidence, "facts": facts.as_dict()}
    if outcomes is not None:
        update["comparisons"] = outcomes
    result = base.model_copy(update=update)
    return result, cards, grid


def _card_views(
    space: QpcrSpace, outcomes: ComparisonsResult | None, grid: pd.DataFrame
) -> dict[str, View]:
    """The study's other comparisons as views of the cards (none without several).

    A card's choice applies to the whole study, so it is a person's whenever it changes a call
    in any comparison, not only in the first.
    """
    if outcomes is None or len(outcomes.comparisons) < 2:
        return {}
    every = grid.attrs[COMPARISON_GRID_ATTR]
    return {
        o.id: View(
            summary=dict(o.robustness),
            grid=every[every["comparison"] == o.id],
            space=space.comparison_view(o.id),
        )
        for o in outcomes.comparisons[1:]
    }


def _comparison_outcomes(
    space: QpcrSpace,
    every: pd.DataFrame,
    base: StudyResult,
    primary: tuple[dict, dict, dict],
    settings: StudySettings,
    cap: Cap | None,
) -> ComparisonsResult:
    """Each comparison's results, corrected p-values, q-values, robustness and grades.

    The primary's are the study's own (``primary``: contrasts, robustness, grades). A gene a
    comparison cannot test in the primary cell (fewer than two values or pairs) is listed in
    ``not_tested`` only.
    """
    plan = settings.design.comparisons  # type: ignore[union-attr]
    arrays = space.evaluate_all_arrays(space.primary)
    out = []
    for i, spec in enumerate(space.comparisons):
        a = arrays[spec.id]
        view = space.comparison_view(spec.id)
        p_call = a.p if a.p_call is None else a.p_call
        tested = [g for j, g in enumerate(space.items) if np.isfinite(a.p[j])]
        index = {g: j for j, g in enumerate(space.items)}
        if i == 0:
            contrasts, summary, confidence = primary
        else:
            rows = every[every["comparison"] == spec.id]
            summary = robustness.summary(rows, view)
            fragility = robustness.fragility(rows, view)
            contrasts = a.results()
            graded = base.model_copy(update={"contrasts": contrasts, "robustness": summary})
            confidence = {g: _grade(g, graded, fragility, cap) for g in tested}
        q = bh(np.array([a.p[index[g]] for g in tested], dtype=float))
        reason = (
            "fewer than two complete pairs (a value in both groups)"
            if spec.paired
            else f"fewer than two biological units with a value in {spec.labels[0]} or "
            f"{spec.labels[1]}"
        )
        out.append(
            ComparisonOutcome(
                id=spec.id,
                group_a=spec.labels[0],
                group_b=spec.labels[1],
                label=_comparison_label(settings.design, spec.id),
                primary=i == 0,
                n_a=len(spec.group_a) if not spec.paired else len(spec.pairs or ()),
                n_b=len(spec.group_b) if not spec.paired else len(spec.pairs or ()),
                n_pairs=len(spec.pairs) if spec.paired else None,
                contrasts={g: contrasts[g] for g in tested},
                p_adjusted={g: float(p_call[index[g]]) for g in tested},
                q_value={g: float(v) for g, v in zip(tested, q, strict=True)},
                robustness={g: summary[g] for g in tested},
                confidence={g: confidence[g] for g in tested if g in confidence},
                not_tested={g: reason for g in space.items if g not in set(tested)},
            )
        )
    groups, omnibus = _omnibus(space, plan.pair_by is None)
    return ComparisonsResult(
        test=test_of(plan.pair_by, space.correction),
        correction=space.correction,  # type: ignore[arg-type]
        pattern=plan.pattern,
        control=plan.control,
        pair_by=plan.pair_by,
        comparisons=out,
        omnibus_groups=groups,
        omnibus=omnibus,
    )


def test_of(pair_by: str | None, correction: str) -> str:
    """The test each comparison uses: paired, pooled-variance (Dunnett, Tukey) or Welch's."""
    if pair_by is not None:
        return "paired_t"
    return "pooled_t" if correction in CORRECTIONS_POOLED else "welch"


def _omnibus(space: QpcrSpace, unpaired: bool) -> tuple[list[str], dict[str, Omnibus]]:
    """Welch's ANOVA per gene across the compared groups, at the planned analysis.

    Only for an unpaired plan comparing three or more groups (a paired design would need a
    repeated-measures model, which qPilot does not claim). Genes without a result (fewer than
    two groups with two values) are left out.
    """
    units: dict[str, frozenset[str]] = {}
    for spec in space.comparisons:
        units.setdefault(spec.labels[0], spec.group_a)
        units.setdefault(spec.labels[1], spec.group_b)
    if not unpaired or len(units) < 3:
        return [], {}
    values, ref_values = space.cell_arrays(space.primary)
    relative = values - ref_values.mean(axis=1)[:, None]
    valid = ~np.isnan(ref_values).any(axis=1)[:, None] & ~np.isnan(relative)
    masks = [space.units.isin(members) for members in units.values()]
    f, df1, df2, p = welch_anova([group_stats(relative, valid & m[:, None]) for m in masks])
    found = {
        gene: Omnibus(f=float(f[i]), df1=float(df1[i]), df2=float(df2[i]), p=float(p[i]))
        for i, gene in enumerate(space.items)
        if np.isfinite(p[i])
    }
    return list(units), found


def _comparison_label(design: StudyDesign | None, comparison_id: str) -> str:
    """The comparison's words: its label, else ``"<group a> vs <group b>"``."""
    for comparison in design.comparison_list() if design is not None else ():
        if comparison.key() == comparison_id:
            return comparison.title()
    return comparison_id


def detected_only_dcq(model: StudyModel) -> dict[str, dict[str, Any]]:
    """Each "detected only in" gene: the group, the counts and that group's ΔCq.

    ΔCq is the engine's Cq of the gene minus the mean Cq of the primary control genes, per
    biological unit of the group it was detected in (mean Cq of the unit's wells that count as
    amplified under the primary rule, as the spreadsheet route builds it,
    :func:`qpilot.qpcr.routes.cq_matrix`), then the mean and SD over those units. No fold change
    is computed: the other group has no measured amount.
    """
    from qpilot.qpcr.routes import cq_matrix

    space = model.space
    if not space.detected_only:
        return {}
    settings, inputs = model.settings, model.inputs
    calls = settings.design.well_calls if settings.design is not None else None
    cq = cq_matrix(inputs.table, inputs.units, calls, amp_call=settings.amp_calls[0])
    refs = [r for r in space.primary["refs"] if r in cq.columns]
    labels = model.labels or (settings.group_var, "rest")
    groups = dict(zip(labels, (model.high, model.rest), strict=True))
    out: dict[str, dict[str, Any]] = {}
    for gene, only in sorted(space.detected_only.items()):
        entry: dict[str, Any] = {
            "group": only.group,
            "absent": only.absent,
            "n_detected": only.n_detected,
            "n_group": only.n_group,
            "n_absent": only.n_absent,
            "dcq": None,
            "dcq_sd": None,
        }
        members = groups.get(only.group) if only.group is not None else None
        if members and gene in cq.columns and refs:
            rows = cq.loc[cq.index.isin(members)]
            delta = (rows[gene] - rows[refs].mean(axis=1, skipna=False)).dropna()
            if len(delta):
                entry["dcq"] = float(delta.mean())
            if len(delta) >= 2:
                entry["dcq_sd"] = float(delta.std(ddof=1))
        out[gene] = entry
    return out


def _not_measured_words(
    missing: Mapping[str, list[str]], candidates: Sequence[str]
) -> dict[str, str]:
    """Gene -> the units it was not measured in, in words (a control gene says what follows)."""
    out = {}
    for gene, units in missing.items():
        listed = ", ".join(units[:10]) + (f" and {len(units) - 10} more" if len(units) > 10 else "")
        if gene in candidates:
            out[gene] = f"{listed} (a control gene: without it the unit has no normaliser)"
        else:
            out[gene] = listed
    return out


def write_outputs(
    result: StudyResult, cards: list[DecisionCard], grid: pd.DataFrame, out_dir: str | Path
) -> dict[str, Path]:
    """Write ``results.json``, ``cards.json``, ``facts.json`` and ``grid.csv`` atomically.

    A study with several comparisons also gets ``grid_comparisons.csv``.
    """
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    texts = {
        "results.json": dump_json(result.model_dump(mode="json")),
        "cards.json": dump_json([card.model_dump(mode="json") for card in cards]),
        "facts.json": dump_json(
            {fid: f.model_dump(mode="json") for fid, f in result.facts.items()}
        ),
        "grid.csv": robustness.to_csv_frame(grid).to_csv(
            index=False, float_format="%.10g", lineterminator="\n"
        ),
    }
    every = comparison_grid_of(grid)
    if every is not None:  # a study with several comparisons
        texts[COMPARISON_GRID_FILE] = comparison_grid_csv(every)
    paths = {}
    for name, text in texts.items():
        paths[name] = directory / name
        atomic_write(paths[name], text)
    return paths


# ---------- pieces ----------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _efficiency(curves: pd.DataFrame) -> dict[str, float]:
    """Each gene's mean PCR efficiency (median over its plates)."""
    per_gene = curves.dropna(subset=["eff_target"]).groupby("target")["eff_target"].median()
    return {str(gene): float(value) for gene, value in per_gene.sort_index().items()}


def _summary_of_design(
    high: frozenset[str],
    rest: frozenset[str],
    space: QpcrSpace,
    labels: tuple[str, str] | None,
) -> DesignSummary:
    """The design record: expression-defined groups, or the confirmed design's two groups.

    With groups from a design there is no cut-off; ``cut`` is 0 there and is not an option.
    """
    if space.design is not None:
        return design_summary(high, rest, space.design)
    return DesignSummary(
        group_var=f"{labels[0]} vs {labels[1]}",
        cut=0.0,
        n_hi=len(high),
        n_lo=len(rest),
        note=GROUPS_NOTE,
        refs_primary=tuple(space.primary["refs"]),
    )


def _grade(
    gene: str, result: StudyResult, fragility: dict[str, int], cap: Cap | None = None
) -> Grade:
    checks = checks_for(gene, result, fragility)
    holds = result.robustness[gene].holds
    return grade(
        START_LEVEL,
        checks,
        upgrade_rule(result.contrasts[gene], holds),
        min_flip_changes=int(fragility[gene]),
        cap=cap,
    )


def _pct(cut: float) -> int:
    return round(cut * 100)


def _refs_label(refs: tuple[str, ...], candidates: tuple[str, ...]) -> str:
    if len(refs) == 1:
        return f"{refs[0]} (the only control gene)"
    if refs == candidates:
        return f"Recommended set (all {_NUMBER_WORDS.get(len(refs), str(len(refs)))})"
    return f"Recommended set ({', '.join(refs)})"


def _ref_options(
    space: QpcrSpace, stability: GenormResult, candidates: tuple[str, ...]
) -> list[tuple[OptionSpec, str]]:
    """(option, fact context) for the reference-set card, recommended first.

    Single-gene options keep their ids (``<gene>_alone``); the card's evidence lists them under
    ``not_recommended`` with the MIQE note instead of changing their labels.
    """
    recommended = tuple(space.primary["refs"])
    label = _refs_label(recommended, candidates)
    options = [(OptionSpec(id="recommended", label=label, value=recommended), "recommended")]
    top2 = tuple(gene for gene in candidates if gene in stability.order[:2])
    top3 = tuple(gene for gene in candidates if gene in stability.order[:3])
    if top3 not in (recommended, top2):
        label = f"Top three by stability ({', '.join(stability.order[:3])})"
        options.append((OptionSpec(id="top3", label=label, value=top3), "top3"))
    if top2 != recommended:
        label = f"Top two by stability ({', '.join(stability.order[:2])})"
        options.append((OptionSpec(id="top2", label=label, value=top2), "top2"))
    for gene in candidates:
        if (gene,) != recommended:
            option = OptionSpec(id=f"{slug(gene)}_alone", label=f"{gene} alone", value=(gene,))
            options.append((option, slug(gene)))
    return options


def _only_varying(grid: pd.DataFrame, space: QpcrSpace, dimension: str) -> pd.DataFrame:
    """Grid rows where every dimension except ``dimension`` is at its primary option."""
    rows = grid
    for name in space.dimensions:
        if name != dimension:
            idx = space.dimensions[name].index(space.primary[name])
            rows = rows[rows[f"{name}{robustness.IDX_SUFFIX}"] == idx]
    return rows


def refset_flip_counts(
    grid: pd.DataFrame, space: QpcrSpace, summary: dict[str, GeneRobustness]
) -> dict[str, int]:
    """How many genes the control-gene choice flips, by the size of the sets compared.

    Uses the grid rows where every other choice is at its primary option, so only the
    control-gene set varies. A gene counts when some subset gives a conclusion different from
    its primary one:

    * ``n_flipped_refs_all``: over every subset (equals the card's ``n_genes_flipped``);
    * ``n_flipped_refs_min3``: over subsets of three or more control genes only, i.e. between
      sets a careful analyst could defend;
    * ``n_flipped_refs_single_only``: flips over all subsets but not over subsets of two or more,
      i.e. only a single control gene (what a ΔΔCt spreadsheet does) changes it.
    """
    rows = _only_varying(grid, space, "refs")
    primary = rows["item"].map({gene: s.conclusion for gene, s in summary.items()})
    changed = rows["conclusion"] != primary
    size = rows["refs"].map(len)

    def flipped(min_size: int) -> set[str]:
        return set(rows.loc[changed & (size >= min_size), "item"])

    flipped_all = flipped(1)
    return {
        "n_flipped_refs_all": len(flipped_all),
        "n_flipped_refs_min3": len(flipped(3)),
        "n_flipped_refs_single_only": len(flipped_all - flipped(2)),
    }


def amp_flip_counts(
    grid: pd.DataFrame, space: QpcrSpace, summary: dict[str, GeneRobustness]
) -> dict[str, int]:
    """Per amplification rule, how many genes change their conclusion when only it changes."""
    rows = _only_varying(grid, space, "amp_call")
    primary = rows["item"].map({gene: s.conclusion for gene, s in summary.items()})
    changed = rows[rows["conclusion"] != primary]
    return {
        rule_id: int(changed.loc[changed["amp_call"] == rule_id, "item"].nunique())
        for rule_id in space.dimensions["amp_call"]
    }


def _refset_extras(
    card: DecisionCard, flips: dict[str, int], effect: RefGroupEffect
) -> DecisionCard:
    """Add the flip count by set size, the group-effect check and the MIQE note to card 1."""
    if card.id != "card_refset":
        return card
    extra = [f for f in _REFSET_EXTRA_FACTS if effect.top is not None or "_top" not in f]
    impact = {
        **card.impact,
        "n_genes_flipped_min3": flips["n_flipped_refs_min3"],
        "n_genes_flipped_single_only": flips["n_flipped_refs_single_only"],
    }
    evidence = {
        **card.evidence,
        "ref_group_effect": effect.as_dict(),
        "genorm_validated": False,
        "genorm_note": GENORM_NOTE,
        "not_recommended": [o.id for o in card.options if o.id.endswith("_alone")],
        "not_recommended_note": NOT_RECOMMENDED_NOTE,
    }
    facts = list(dict.fromkeys([*card.facts, *extra]))
    return card.model_copy(update={"impact": impact, "evidence": evidence, "facts": facts})


def _option_facts(headline: Sequence[str], contexts: list[str]) -> list[str]:
    return [f"f_fc_{slug(gene)}_{ctx}" for ctx in contexts for gene in headline]


def _card_specs(
    space: QpcrSpace,
    stability: GenormResult,
    summary: dict[str, GeneRobustness],
    settings: StudySettings,
    headline: Sequence[str],
    counts: dict[str, int],
    others: Sequence[dict[str, GeneRobustness]] = (),
) -> list[CardSpec]:
    """The cards the qPCR plugin asks the core to build (the core adds impact and rank).

    The cut-off card exists only when the groups are defined from the data. ``others`` are
    the robustness summaries of the study's other comparisons (a flip there counts too).
    """

    def option_facts(contexts: list[str]) -> list[str]:
        return _option_facts(headline, contexts)

    ref_options = _ref_options(space, stability, settings.candidates)
    lead = [slug(headline[0])] if headline else []
    refset_facts = ["f_order_1", "f_m_1", "f_worst_ref"]
    contexts = ("recommended", "worst")
    if len(settings.candidates) == 1:  # one candidate: no M and no "worst gene alone" option
        refset_facts.remove("f_m_1")
        contexts = ("recommended",)
    refset_facts += [f"f_fc_{s}_{ctx}" for s in lead for ctx in contexts]
    refset_facts += ["f_n_flipped_refset", "f_n_genes"]
    refset_facts += option_facts([ctx for _, ctx in ref_options])

    cut_ids = [f"cut_{_pct(cut)}" for cut in settings.cuts]
    undetermined_flips = any(
        card_impact(s, "undetermined")["flips"] for s in (summary, *others) if s
    )
    specs = [
        CardSpec(
            card_id="card_refset",
            kind="reference_set",
            dimension="refs",
            options=[option for option, _ in ref_options],
            recommended="recommended",
            rationale_template="refset_v1",
            evidence={
                "genorm_M": stability.M_initial,
                "genorm_order": stability.order,
                "genorm_V": stability.V,
                "cutoff_M": stability.cutoff_M,
                "cutoff_V": stability.cutoff_V,
            },
            facts=list(dict.fromkeys(refset_facts)),
        ),
    ]
    if "cut" in space.dimensions:
        specs.append(
            CardSpec(
                card_id="card_cutoff",
                kind="group_cutoff",
                dimension="cut",
                options=[
                    OptionSpec(
                        id=cid,
                        label=f"Top {_pct(cut)} % by {settings.marker_label} expression",
                        value=cut,
                    )
                    for cid, cut in zip(cut_ids, settings.cuts, strict=True)
                ],
                recommended=f"cut_{_pct(settings.cut)}",
                rationale_template="cutoff_v1",
                evidence={
                    "cuts": list(settings.cuts),
                    "n_hi_by_cut": {
                        cid: len(space.groups(cut)[0])
                        for cid, cut in zip(cut_ids, settings.cuts, strict=True)
                    },
                },
                facts=["f_n_flipped_cutoff", "f_n_genes", *option_facts(cut_ids)],
            )
        )
    specs.append(
        CardSpec(
            card_id="card_undetermined",
            kind="undetermined",
            dimension="undetermined",
            options=[
                OptionSpec(id="drop", label="Drop empty wells", value="drop"),
                OptionSpec(id="cap", label="Count empty wells as very low (cap)", value="cap"),
            ],
            recommended="drop",
            rationale_template="undetermined_v1" if undetermined_flips else "undetermined_auto_v1",
            evidence=dict(counts),
            facts=[
                "f_n_flipped_undetermined",
                "f_n_undetermined",
                "f_n_unknown_wells",
                "f_pct_undetermined",
                *option_facts(["drop", "cap"]),
            ],
        )
    )
    return specs


def flip_counts(
    grid: pd.DataFrame, space: QpcrSpace, summary: dict[str, GeneRobustness], dimension: str
) -> dict[str, int]:
    """Per option of ``dimension``: genes whose conclusion changes when only it changes."""
    rows = _only_varying(grid, space, dimension)
    primary = rows["item"].map({gene: s.conclusion for gene, s in summary.items()})
    changed = rows[rows["conclusion"] != primary]
    return {
        str(value): int(changed.loc[changed[dimension] == value, "item"].nunique())
        for value in space.dimensions[dimension]
    }


EFFICIENCY_WORDING = (
    "The answer depends on which efficiency turns each Cq into a quantity, e.g. each well's own "
    "efficiency or the assay's mean efficiency; none of them is the correct one by default."
)


def _efficiency_spec(
    space: QpcrSpace,
    grid: pd.DataFrame,
    summary: dict[str, GeneRobustness],
    headline: Sequence[str],
    notes: Mapping[str, dict],
) -> CardSpec:
    """The "Which efficiency turns Cq into quantity" card (only when the axis is in the grid)."""
    axis = space.axes["efficiency"]
    options = list(space.dimensions["efficiency"])
    by_value = {o.value: o for o in axis.options}
    eff_notes = dict(notes.get("efficiency", {}))
    slugs = [slug(str(o)) for o in options]
    return CardSpec(
        card_id="card_efficiency",
        kind="numbers.efficiency_model",
        dimension="efficiency",
        options=[OptionSpec(id=str(o), label=by_value[o].label, value=o) for o in options],
        recommended=str(space.primary["efficiency"]),
        rationale_template="efficiency_v1",
        evidence={
            "title": axis.title,
            "wording": EFFICIENCY_WORDING,
            "n_flipped_by_option": flip_counts(grid, space, summary, "efficiency"),
            "unavailable": dict(axis.unavailable),
            **{k: v for k, v in eff_notes.items() if k != "unavailable"},
            "method_card": eff_axis.METHOD_CARD_PATH,
        },
        facts=[
            "f_n_flipped_efficiency",
            "f_n_genes",
            *[f"f_eff_label_{s}" for s in slugs],
            *[f"f_n_flipped_eff_{s}" for s in slugs],
            *_option_facts(headline, [str(o) for o in options]),
        ],
    )


NORMALISER_WORDING = (
    "The answer depends on what each gene is divided by: the reference genes chosen for this "
    "study, the pair NormFinder or geNorm ranks steadiest, or the mean of every gene measured. "
    "The reference genes in use stay a person's choice."
)
INTERRUN_WORDING = (
    "The answer depends on whether differences between plates are corrected, and how: with "
    "the calibrator sample measured on every plate, or with the measurements plates share."
)


def _axis_card(
    space: QpcrSpace,
    grid: pd.DataFrame,
    summary: dict[str, GeneRobustness],
    headline: Sequence[str],
    notes: Mapping[str, dict],
    name: str,
    prefix: str,
    wording: str,
    method_card: str,
) -> CardSpec:
    """The card of an opt-in axis whose options are the axis's own ids (one per option)."""
    axis = space.axes[name]
    options = list(space.dimensions[name])
    by_value = {o.value: o for o in axis.options}
    own = dict(notes.get(name, {}))
    slugs = [slug(str(o)) for o in options]
    return CardSpec(
        card_id=f"card_{name}",
        kind=get_axis(name).card_kind,
        dimension=name,
        options=[OptionSpec(id=str(o), label=by_value[o].label, value=o) for o in options],
        recommended=str(space.primary[name]),
        rationale_template=f"{name}_v1",
        evidence={
            "title": axis.title,
            "wording": wording,
            "n_flipped_by_option": flip_counts(grid, space, summary, name),
            "unavailable": dict(axis.unavailable),
            **{k: v for k, v in own.items() if k != "unavailable"},
            "method_card": method_card,
        },
        facts=[
            f"f_n_flipped_{name}",
            "f_n_genes",
            *[f"f_{prefix}_label_{s}" for s in slugs],
            *[f"f_n_flipped_{prefix}_{s}" for s in slugs],
            *_option_facts(headline, [str(o) for o in options]),
        ],
    )


def _normaliser_spec(
    space: QpcrSpace,
    grid: pd.DataFrame,
    summary: dict[str, GeneRobustness],
    headline: Sequence[str],
    notes: Mapping[str, dict],
) -> CardSpec:
    """The "What to normalise each gene to" card (only when the axis is in the grid)."""
    card = _axis_card(
        space,
        grid,
        summary,
        headline,
        notes,
        "normaliser",
        "norm",
        NORMALISER_WORDING,
        norm_axis.METHOD_CARD_PATH,
    )
    own = notes.get("normaliser", {})
    pairs = own.get("refs") or {}
    options = [
        o.model_copy(update={"label": f"{o.label} ({', '.join(pairs[o.id])})"})
        if o.id in pairs
        else o
        for o in card.options
    ]
    card = card.model_copy(update={"options": options})
    extra = [
        *(["f_nf_best_pair", "f_nf_pair_stability"] if own.get("normfinder") else []),
        *(["f_genorm_best_pair"] if own.get("genorm_pair") else []),
        *(["f_nf_agreement"] if own.get("agreement") else []),
        *(["f_gm_n_genes", "f_gm_min_genes"] if own.get("global_mean") else []),
    ]
    return card.model_copy(update={"facts": list(dict.fromkeys([*card.facts, *extra]))})


def _interrun_spec(
    space: QpcrSpace,
    grid: pd.DataFrame,
    summary: dict[str, GeneRobustness],
    headline: Sequence[str],
    notes: Mapping[str, dict],
) -> CardSpec:
    """The "How to correct differences between plates" card (only when one flips a call)."""
    return _axis_card(
        space,
        grid,
        summary,
        headline,
        notes,
        "interrun",
        "irc",
        INTERRUN_WORDING,
        irc.METHOD_CARD_PATH,
    )


def _amp_call_spec(
    space: QpcrSpace,
    grid: pd.DataFrame,
    summary: dict[str, GeneRobustness],
    headline: Sequence[str],
    not_amplified: Mapping[str, int],
) -> CardSpec:
    """The "Which curves count as amplified" card (only when the dimension is in the grid).

    The recommended option is the primary rule (``linregpcr`` unless a person chose another).
    """
    options = list(space.dimensions["amp_call"])
    flips = amp_flip_counts(grid, space, summary)
    slugs = [slug(rule_id) for rule_id in options]
    return CardSpec(
        card_id="card_amp_call",
        kind="amp_call",
        dimension="amp_call",
        options=[OptionSpec(id=r, label=RULES[r].label, value=r) for r in options],
        recommended=space.primary["amp_call"],
        rationale_template="ampcall_v1",
        evidence={
            "title": AMP_CALL_TITLE,
            "rules": {r: RULES[r].model_dump(mode="json", exclude_none=True) for r in options},
            "recommended_rule": RECOMMENDED,
            "n_flipped_by_rule": flips,
            "n_not_amplified_by_rule": {r: int(not_amplified[r]) for r in options},
            "method_card": METHOD_CARD_PATH,
        },
        facts=[
            "f_n_flipped_amp_call",
            "f_n_genes",
            "f_amp_primary",
            *[f"f_amp_label_{s}" for s in slugs],
            *[f"f_n_flipped_amp_{s}" for s in slugs],
            *[f"f_n_undetermined_amp_{s}" for s in slugs],
            *_option_facts(headline, options),
        ],
    )


@dataclass(frozen=True)
class _Extras:
    """Facts beyond the legacy set: withheld genes, the Studio facts, the design's groups."""

    withheld: Mapping[str, str]
    detected_only: Mapping[str, Mapping[str, Any]]
    screen: AmpScreen | None
    routes: Mapping[str, RouteResult] | None
    groups: tuple[str, str] | None
    axis_notes: Mapping[str, dict] = field(default_factory=dict)
    axes: Mapping[str, object] = field(default_factory=dict)
    screens: Mapping[str, robustness.AxisScreen] = field(default_factory=dict)
    not_measured: Mapping[str, str] = field(default_factory=dict)
    comparisons: ComparisonsResult | None = None
    dimensions: tuple[str, ...] = ()


#: A grid dimension's name in the flip-count fact ids (``f_n_flipped_refset``, ...).
FLIP_SUFFIX = {"refs": "refset", "cut": "cutoff"}


def _facts(
    result: StudyResult,
    confidence: dict[str, Grade],
    cards: list[DecisionCard],
    space: QpcrSpace,
    settings: StudySettings,
    headline: Sequence[str],
    counts: dict[str, int],
    extras: _Extras,
) -> FactRegistry:
    """Every number that prose may cite, under the id convention in the module docstring."""
    registry = FactRegistry()

    def add(fid: str, value: float | int | str, fmt: str = "{}", unit: str = "", path: str = ""):
        if fid in registry:  # the same number reached by two routes, e.g. a card's primary option
            if registry.get(fid).value != value:
                raise ValueError(f"fact {fid} has two different values")
            return
        registry.add(Fact(id=fid, value=value, fmt=fmt, unit=unit, path=path))

    items = space.items
    flipped = {dim: robustness.flipped_by(result.robustness, dim) for dim in space.dimensions}
    study = {
        "f_n_plates": result.n_plates,
        "f_n_reactions": result.n_reactions,
        "f_n_samples": result.n_samples,
        "f_n_hi": result.design.n_hi,
        "f_n_lo": result.design.n_lo,
        "f_n_cells": robustness.n_cells(space),
        "f_n_genes": len(items),
        "f_n_flipped_refset": len(flipped["refs"]),
        **({"f_n_flipped_cutoff": len(flipped["cut"])} if "cut" in flipped else {}),
        "f_n_flipped_undetermined": len(flipped["undetermined"]),
        **({"f_n_flipped_amp_call": len(flipped["amp_call"])} if "amp_call" in flipped else {}),
        **(
            {"f_n_flipped_efficiency": len(flipped["efficiency"])}
            if "efficiency" in flipped
            else {}
        ),
        **{
            f"f_n_flipped_{name}": len(flipped[name])
            for name in ("normaliser", "interrun")
            if name in flipped
        },
        "f_n_hold_lt_80": sum(result.robustness[gene].holds < HOLDS_LOW for gene in items),
        **{f"f_{key}": value for key, value in counts.items()},
    }
    large_counts = {"f_n_reactions", "f_n_unknown_wells"}
    for fid, value in study.items():
        add(fid, int(value), COUNT_FMT if fid in large_counts else "{}", path="study")
    share = counts["n_undetermined"] / counts["n_unknown_wells"] if counts["n_unknown_wells"] else 0
    add("f_pct_undetermined", 100 * share, "{:.1f}", "%", "study")
    if result.efficiency:
        median = statistics.median(result.efficiency.values())
        add("f_eff_median", float(median), "{:.2f}", "", "efficiency")
    for gene, value in result.efficiency.items():
        add(f"f_eff_{slug(gene)}", value, "{:.2f}", "", f"efficiency.{gene}")

    stability = result.genorm
    for i, ref in enumerate(stability.order, start=1):
        add(f"f_order_{i}", ref, path=f"genorm.order[{i - 1}]")
        if ref in stability.M_initial:
            m = float(stability.M_initial[ref])
            add(f"f_m_{i}", m, "{:.2f}", "", f"genorm.M_initial.{ref}")
    for ref, value in stability.M_initial.items():
        add(f"f_m_{slug(ref)}", float(value), "{:.2f}", "", f"genorm.M_initial.{ref}")
    for key, value in stability.V.items():  # "V2/3" -> f_v_2_3
        add(f"f_v_{slug(key[1:])}", float(value), "{:.2f}", "", f"genorm.V.{key}")
    add("f_worst_ref", stability.order[-1], path="genorm.order[-1]")
    if stability.V:
        add("f_genorm_v_min", float(min(stability.V.values())), "{:.2f}", "", "genorm.V")

    for gene in items:
        s, contrast, graded = slug(gene), result.contrasts[gene], confidence[gene]
        add(f"f_fc_{s}_recommended", contrast.fc, FC_FMT, TIMES, f"contrasts.{gene}.fc")
        add(f"f_ci_lo_{s}_recommended", contrast.ci[0], FC_FMT, TIMES, f"contrasts.{gene}.ci[0]")
        add(f"f_ci_hi_{s}_recommended", contrast.ci[1], FC_FMT, TIMES, f"contrasts.{gene}.ci[1]")
        add(f"f_p_{s}_recommended", contrast.p, "{:.2g}", "", f"contrasts.{gene}.p")
        add(f"f_holds_{s}", result.robustness[gene].holds, "{:.0%}", "", f"robustness.{gene}.holds")
        add(f"f_level_{s}", graded.level, path=f"confidence.{gene}.level")
        flips = int(graded.min_flip_changes or 0)
        add(f"f_min_flip_{s}", flips, path=f"confidence.{gene}.min_flip_changes")
        add(f"f_mde_fold_{s}", mde_fold(contrast), FC_FMT, TIMES, f"confidence.{gene}.mde")

    for card in cards:
        for option in card.options:
            context = option.id.removesuffix("_alone")
            for gene, contrast in option.per_gene.items():
                path = f"cards.{card.id}.{option.id}.{gene}.fc"
                add(f"f_fc_{slug(gene)}_{context}", contrast.fc, FC_FMT, TIMES, path)
        for option_id, n_hi in card.evidence.get("n_hi_by_cut", {}).items():
            add(f"f_n_hi_{option_id}", int(n_hi), path=f"cards.{card.id}.evidence.n_hi_by_cut")
        if card.id == "card_refset" and "ref_group_effect" in card.evidence:
            _refset_facts(add, card)
        if card.id == "card_amp_call":
            _amp_call_facts(add, card)
        if card.id == "card_efficiency":
            _efficiency_card_facts(add, card)
        if card.id in ("card_normaliser", "card_interrun"):
            _axis_card_facts(add, card, "norm" if card.id == "card_normaliser" else "irc")
    worst = slug(stability.order[-1])
    for gene in headline:
        source = f"f_fc_{slug(gene)}_{worst}"
        if source in registry:
            path = f"cards.card_refset.{worst}_alone.{gene}.fc"
            add(f"f_fc_{slug(gene)}_worst", registry.get(source).value, FC_FMT, TIMES, path)
    _extra_facts(add, extras, settings)
    _axis_facts(add, extras)
    _comparison_facts(add, extras)
    return registry


def _comparison_facts(add: Callable[..., None], extras: _Extras) -> None:
    """Facts for units not measured for a gene and for a study's several comparisons.

    None exist in a study where every unit has every gene and the design has one comparison
    (every existing study). Comparison facts are numbered ``f_cmp<i>_*`` in the plan's order
    (1 = the primary), so a gene or group name can never collide with another fact.
    """
    if extras.not_measured:
        add("f_n_not_measured", len(extras.not_measured), path="not_measured")
        for gene, words in extras.not_measured.items():
            add(f"f_not_measured_{slug(gene)}", words, path=f"not_measured.{gene}")
    found = extras.comparisons
    if found is None:
        return
    add("f_n_comparisons", len(found.comparisons), path="comparisons.comparisons")
    for gene, result in found.omnibus.items():
        add(f"f_anova_p_{slug(gene)}", result.p, "{:.2g}", "", f"comparisons.omnibus.{gene}.p")
    add("f_cmp_test", TEST_WORDS[found.test], path="comparisons.test")
    add("f_cmp_correction", CORRECTION_WORDS[found.correction], path="comparisons.correction")
    if found.pair_by is not None:
        add("f_cmp_pair_by", found.pair_by, path="comparisons.pair_by")
    for i, outcome in enumerate(found.comparisons, start=1):
        root = f"comparisons.{outcome.id}"
        add(f"f_cmp{i}_label", outcome.label, path=f"{root}.label")
        add(f"f_cmp{i}_n_a", outcome.n_a, path=f"{root}.n_a")
        add(f"f_cmp{i}_n_b", outcome.n_b, path=f"{root}.n_b")
        calls = [c.conclusion for c in outcome.contrasts.values()]
        add(f"f_cmp{i}_n_up", calls.count("up"), path=f"{root}.contrasts")
        add(f"f_cmp{i}_n_down", calls.count("down"), path=f"{root}.contrasts")
        add(f"f_cmp{i}_n_tested", len(outcome.contrasts), path=f"{root}.contrasts")
        for dim in extras.dimensions:
            flipped = robustness.flipped_by(outcome.robustness, dim)
            fid = f"f_cmp{i}_n_flipped_{FLIP_SUFFIX.get(dim, slug(dim))}"
            add(fid, len(flipped), path=f"{root}.robustness")
        for gene, contrast in outcome.contrasts.items():
            s, path = slug(gene), f"{root}.contrasts.{gene}"
            add(f"f_cmp{i}_fc_{s}", contrast.fc, FC_FMT, TIMES, f"{path}.fc")
            add(f"f_cmp{i}_p_{s}", contrast.p, "{:.2g}", "", f"{path}.p")
            padj = outcome.p_adjusted[gene]
            add(f"f_cmp{i}_padj_{s}", padj, "{:.2g}", "", f"{root}.p_adjusted.{gene}")
            add(f"f_cmp{i}_q_{s}", outcome.q_value[gene], "{:.2g}", "", f"{root}.q_value.{gene}")
            holds = outcome.robustness[gene].holds
            add(f"f_cmp{i}_holds_{s}", holds, "{:.0%}", "", f"{root}.robustness.{gene}.holds")


def _refset_facts(add: Callable[..., None], card: DecisionCard) -> None:
    """Facts for the reference-set card's flip count by set size and its group-effect check.

    Values are read from the card itself, so a fact always equals what ``cards.json`` shows.
    """
    root = f"cards.{card.id}"
    for key, fid in (
        ("n_genes_flipped_min3", "f_n_flipped_refset_min3"),
        ("n_genes_flipped_single_only", "f_n_flipped_refset_single_only"),
    ):
        add(fid, int(card.impact[key]), path=f"{root}.impact.{key}")
    effect = card.evidence["ref_group_effect"]
    base = f"{root}.evidence.ref_group_effect"
    pairs = effect["pairs"]
    for pair in pairs:  # f_ref_ratio_hmbs_ubc_2 (+ _p): the shift of HMBS:UBC(2), high vs rest
        a, b = pair["genes"]
        fid, path = f"f_ref_ratio_{slug(a)}_{slug(b)}", f"{base}.pairs.{pair['label']}"
        add(fid, float(pair["fold"]), FC_FMT, TIMES, f"{path}.fold")
        add(f"{fid}_p", float(pair["p"]), "{:.2g}", "", f"{path}.p")
    if pairs:
        top, path = pairs[0], f"{base}.pairs.{pairs[0]['label']}"
        add("f_ref_pair_top", str(top["label"]), path=f"{path}.label")
        add("f_ref_ratio_top", float(top["fold"]), FC_FMT, TIMES, f"{path}.fold")
        add("f_ref_ratio_top_p", float(top["p"]), "{:.2g}", "", f"{path}.p")
    add("f_n_ref_pairs", len(pairs), path=f"{base}.pairs")
    add("f_n_ref_pairs_flagged", len(effect["flagged"]), path=f"{base}.flagged")
    add("f_ref_flag_fold", float(effect["flag_fold"]), FC_FMT, TIMES, f"{base}.flag_fold")


def _amp_call_facts(add: Callable[..., None], card: DecisionCard) -> None:
    """Facts for the amplification-call card, read from the card itself."""
    root = f"cards.{card.id}.evidence"
    evidence = card.evidence
    add("f_amp_primary", RULES[card.recommended].label, path=f"{root}.rules.{card.recommended}")
    for option in card.options:
        s = slug(option.id)
        add(f"f_amp_label_{s}", option.label, path=f"{root}.rules.{option.id}.label")
        flips = int(evidence["n_flipped_by_rule"][option.id])
        add(f"f_n_flipped_amp_{s}", flips, path=f"{root}.n_flipped_by_rule.{option.id}")
        wells = int(evidence["n_not_amplified_by_rule"][option.id])
        path = f"{root}.n_not_amplified_by_rule.{option.id}"
        add(f"f_n_undetermined_amp_{s}", wells, COUNT_FMT, path=path)


def _efficiency_card_facts(add: Callable[..., None], card: DecisionCard) -> None:
    """Facts for the efficiency-model card, read from the card itself."""
    root = f"cards.{card.id}"
    for option in card.options:
        s = slug(option.id)
        label = option.label  # inside a sentence: "each well's own …", "LinRegPCR's …"
        if label.split(" ", 1)[0][1:].islower():
            label = label[:1].lower() + label[1:]
        add(f"f_eff_label_{s}", label, path=f"{root}.{option.id}.label")
        flips = int(card.evidence["n_flipped_by_option"][option.id])
        add(f"f_n_flipped_eff_{s}", flips, path=f"{root}.evidence.n_flipped_by_option.{option.id}")


def _axis_card_facts(add: Callable[..., None], card: DecisionCard, prefix: str) -> None:
    """Facts for the normaliser or inter-run card, read from the card itself."""
    root = f"cards.{card.id}"
    for option in card.options:
        s = slug(option.id)
        label = option.label  # inside a sentence; a name such as "NormFinder's" keeps its case
        if label.split(" ", 1)[0][1:].islower():
            label = label[:1].lower() + label[1:]
        add(f"f_{prefix}_label_{s}", label, path=f"{root}.{option.id}.label")
        flips = int(card.evidence["n_flipped_by_option"][option.id])
        path = f"{root}.evidence.n_flipped_by_option.{option.id}"
        add(f"f_n_flipped_{prefix}_{s}", flips, path=path)


def _normaliser_facts(add: Callable[..., None], notes: Mapping[str, Any]) -> None:
    """NormFinder's and geNorm's best pairs and the global mean's gene count (when offered)."""
    base = "axes.normaliser"
    found = notes.get("normfinder")
    if found:
        add("f_nf_best", str(found["best"]), path=f"{base}.normfinder.best")
        add("f_nf_best_pair", " and ".join(found["best_pair"]), path=f"{base}.normfinder.best_pair")
        add(
            "f_nf_pair_stability",
            float(found["pair_stability"]),
            "{:.3f}",
            path=f"{base}.normfinder.pair_stability",
        )
        for gene, value in found["stability"].items():
            add(f"f_nf_{slug(gene)}", float(value), "{:.3f}", path=f"{base}.normfinder.stability")
    if notes.get("genorm_pair"):
        add("f_genorm_best_pair", " and ".join(notes["genorm_pair"]), path=f"{base}.genorm_pair")
    if notes.get("agreement"):
        add("f_nf_agreement", str(notes["agreement"]), path=f"{base}.agreement")
    gm = notes.get("global_mean") or {}
    if gm:
        add("f_gm_n_genes", int(gm["n_genes"]), path=f"{base}.global_mean.n_genes")
        add("f_gm_min_genes", int(gm["min_genes"]), path=f"{base}.global_mean.min_genes")
        shift = gm.get("group_shift")
        if shift:
            path = f"{base}.global_mean.group_shift"
            add("f_gm_shift_fold", float(shift["fold"]), FC_FMT, TIMES, f"{path}.fold")
            add("f_gm_shift_p", float(shift["p"]), "{:.2g}", "", f"{path}.p")


def _interrun_facts(add: Callable[..., None], notes: Mapping[str, Any]) -> None:
    """How many genes are split over plates and what can correct them (when offered)."""
    base = "axes.interrun"
    add("f_irc_n_runs", int(notes["n_runs"]), path=f"{base}.n_runs")
    add("f_irc_n_split", int(notes["n_split_targets"]), path=f"{base}.n_split_targets")
    n_cal = len(notes.get("calibrators") or {})
    add("f_irc_n_calibrated", n_cal, path=f"{base}.calibrators")
    add("f_irc_n_pairs", int(notes["n_plate_pairs_sharing"]), path=f"{base}.n_plate_pairs_sharing")


def _axis_facts(add: Callable[..., None], extras: _Extras) -> None:
    """Facts for the opt-in axes a study offered: status, screening, what did not apply.

    None exist in the legacy output (no opt-in axis is offered there).
    """
    for name, notes in extras.axis_notes.items():
        axis = extras.axes[name]
        base = f"axes.{name}"
        add(f"f_axis_{name}", axis.status, path=f"{base}.status")
        for option_id, reason in axis.unavailable:
            add(f"f_axis_{name}_unavailable_{slug(option_id)}", reason, path=f"{base}.unavailable")
        if "n_excluded_per_well" in notes:
            n = int(notes["n_excluded_per_well"])
            add("f_n_eff_excluded_per_well", n, COUNT_FMT, path=f"{base}.n_excluded_per_well")
        if "std_curve_fallback" in notes:
            genes = ", ".join(notes["std_curve_fallback"]) or "none"
            add("f_eff_std_fallback", genes, path=f"{base}.std_curve_fallback")
        if name == "normaliser":
            _normaliser_facts(add, notes)
        if name == "interrun":
            _interrun_facts(add, notes)
        screen = extras.screens.get(name)
        if screen is not None:
            add(
                f"f_screen_{name}",
                "admitted" if screen.admitted else "not admitted",
                path=f"screen.{name}.admitted",
            )
            delta = screen.max_delta_log2fc
            add(f"f_screen_{name}_dlog2fc", delta, "{:.2f}", path=f"screen.{name}.max_delta_log2fc")
            for option, items in screen.flipped.items():
                add(
                    f"f_screen_{name}_flips_{slug(option)}",
                    len(items),
                    path=f"screen.{name}.flipped.{option}",
                )


def _extra_facts(add: Callable[..., None], extras: _Extras, settings: StudySettings) -> None:
    """Withheld genes, the design's group names and the Studio facts (routes, screening).

    None of these exist in the legacy demo output: a withheld gene cannot occur there, and the
    Studio facts are added only when the settings ask for them.
    """
    if extras.withheld or settings.studio_facts:
        add("f_n_withheld", len(extras.withheld), path="withheld")
        for gene, reason in extras.withheld.items():
            add(f"f_withheld_{slug(gene)}", reason, path=f"withheld.{gene}")
    for gene, only in extras.detected_only.items():
        s, path = slug(gene), f"detected_only.{gene}"
        add(f"f_detected_only_{s}", only["group"] or "neither group", path=f"{path}.group")
        add(f"f_absent_only_{s}", only["absent"], path=f"{path}.absent")
        add(f"f_n_detected_only_{s}", only["n_detected"], COUNT_FMT, path=f"{path}.n_detected")
        add(f"f_n_units_only_{s}", only["n_group"], COUNT_FMT, path=f"{path}.n_group")
        add(f"f_n_absent_only_{s}", only["n_absent"], COUNT_FMT, path=f"{path}.n_absent")
        if only.get("dcq") is not None:
            add(f"f_dcq_only_{s}", only["dcq"], "{:.2f}", path=f"{path}.dcq")
        if only.get("dcq_sd") is not None:
            add(f"f_dcq_sd_only_{s}", only["dcq_sd"], "{:.2f}", path=f"{path}.dcq_sd")
    if extras.groups is not None:
        add("f_group_a", extras.groups[0], path="design.comparison.group_a")
        add("f_group_b", extras.groups[1], path="design.comparison.group_b")
    if extras.routes is not None:
        for route in ROUTES:
            found = extras.routes[route]
            add(f"f_n_differ_route_{route}", found.n_differ, path=f"routes.{route}.differ")
            genes = ", ".join(found.differ) or "none"
            add(f"f_genes_differ_route_{route}", genes, path=f"routes.{route}.differ")
    if extras.screen is not None:
        screen = extras.screen
        verdict = "admitted" if screen.admitted else "not admitted"
        add("f_screen_amp_call", verdict, path="screen.amp_call.admitted")
        add("f_screen_amp_min_log2fc", screen.min_log2fc, "{:g}", path="screen.amp_call.min_log2fc")
        for rule in screen.rules:
            s, path = slug(rule.rule_id), f"screen.amp_call.{rule.rule_id}"
            add(f"f_screen_amp_flips_{s}", rule.n_flipped, path=f"{path}.flipped")
            delta = rule.max_delta_log2fc
            add(f"f_screen_amp_dlog2fc_{s}", delta, "{:.2f}", path=f"{path}.max_delta_log2fc")
