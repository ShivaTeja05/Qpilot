"""Trace: from a result, a sample or a well back to the wells to look at.

A scientist looks at one result (a gene's call), one sample or one well and asks *which input
made it this way, and does it matter?* Trace assumes the arithmetic is right and walks back
through the numbers the result was built from::

    conclusion -> group set -> sample value -> target well -> plate controls
                                            -> normaliser -> reference well -> plate controls

Every node is a number the engine already computes. Each child gets two scores: its
**influence** (how much the parent moves if the child read as expected; closed form: leave one
sample out of its group, or replace one reference value) and its **unusualness** (the
fingerprint checks below, each a robust z against the same study, so thresholds follow the
panel's own noise). The walk is depth-first in order of influence and prunes a subtree when its
influence is below a small share of the result's confidence-interval half-width **and** no
check fails below it **and** it does not change the call; each subtree's failed checks are
known before the walk (bottom-up), so pruning never hides a failure.

Fingerprints (``CHECKS``; thresholds in :data:`TRACE_THRESHOLDS`):

* ``S1`` one reference well disagrees with the sample's other reference wells. Expected value
  of reference r for a sample: the mean of its other references plus r's usual offset (the
  median over the compared samples, which have every reference). The sample's single reference
  with the largest robust ``|z|`` is flagged when it exceeds the threshold. Needs three or more
  references; works without technical replicates.
* ``S2`` every gene of the sample is late together: per sample, the median over its wells of
  Cq minus the plate's median Cq, robust z (late side only).
* ``S4`` the sample's efficiency shifts across assays: the same with the per-well efficiency;
  shown only when the robust z **and** an absolute floor are both exceeded.
* ``S5`` LinRegPCR noted a curve-quality issue on a well that carries a value. ``Ncopy < 10``
  and ``Ncopy > 100 Mio`` are information about the amount, not about the curve, and never fail.
* ``S6`` a study well with Cq at or after the lowest NTC Cq of its plate minus the window
  (MIQE's 5-cycle rule). Reported per plate: "nothing found" is claimed only for plates whose
  NTCs did not amplify.
* ``S7`` a sample in no comparison: which wells left it out, and what bringing it back would do
  (the empty reference read from the sample's other references; the group by the fixed marker
  threshold).

``S3`` (references shifted, targets not) is cut. ``S8`` (shared annotations) needs a sample
sheet and ``S9`` (technical replicates) a replicate design: they are reported as what the data
cannot show, or as not applicable.

**Groups are held fixed in every scenario** (the primary cut's masks): leave-one-out, a
reference read from the others, a sample set aside or brought back never re-derives the
groups. Each place gets options (keep / read from the other references / set aside) and the
consequence of each (:mod:`qpilot.core.consequence`): it changes the call > it moves the fold
change by more than its CI half-width > it changes nothing. Places are ranked by that class,
then by the size of the change, then by ``|z|``, then by sample id. A child that is influential
but shows nothing unusual goes in a separate list: that is the "nothing to look at" answer.

Answers: ``place_to_look`` (a place changes the call or moves the number beyond its CI),
``choice_to_look_at`` (no such place, but changing one analysis choice alone flips the gene),
``nothing_to_look_at``, or ``absent`` (the sample is in no comparison).

Every number a result shows is a fact (``f_trace_<root>_<rank>_<field>`` and
``f_trace_<root>_<field>``); sample ids, plates and wells are string facts because they carry
digits. Trace facts live in :class:`TraceResult`, never in the study's own facts. Trace only
reads: every change is a decision a person makes on a ``trace_set_aside`` card.

Deterministic: no model call and no network. The JSON form is byte-stable (sorted keys, floats
rounded to ten places, NaN as null).
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, PrivateAttr

from qpilot.core.consequence import (
    CLASSES,
    NOTHING,
    Baseline,
    Consequence,
    classify,
    classify_roots,
    sort_key,
)
from qpilot.core.facts import FactRegistry, slug
from qpilot.core.store import dump_json
from qpilot.qpcr.design import marker_group_names
from qpilot.qpcr.quant import EXCLUDED, unit_map
from qpilot.qpcr.space import ContrastArrays, QpcrSpace, group_stats, welch_arrays
from qpilot.schemas import CardOption, DecisionCard, Fact

if TYPE_CHECKING:
    from qpilot.core.store import StudyStore
    from qpilot.qpcr.study import StudyModel

METHOD_CARD_PATH = "methods/trace.md"
TRACE_THRESHOLDS: dict[str, float] = {
    "z": 3.5,  # robust z (median and 1.4826 x MAD over the study) for S1, S2 and S4
    "ntc_window_cycles": 5.0,  # S6: a study well within 5 cycles of its plate's lowest NTC Cq
    "eff_shift_floor": 0.05,  # S4: the median efficiency shift must also exceed this
    "late_cycles": 2.0,  # descriptive only: a well this many cycles after its plate's median
    "eps_ci_share": 0.1,  # walk: below this share of the result's CI half-width, prune
    "influential_top": 3,  # length of the "influential, nothing unusual" list
    "boundary_tol": 1e-9,  # closed-form results this close to the call rule are recomputed
}
MAD_SCALE = 1.4826  # robust z = (x - median) / (1.4826 x MAD)
CARD_KIND = "trace_set_aside"
CARD_TEMPLATE = "trace_set_aside_v1"
Answer = Literal["place_to_look", "choice_to_look_at", "nothing_to_look_at", "absent"]
Role = Literal["reference_well", "target_well", "sample", "control_well"]

CHECKS: dict[str, dict[str, str]] = {
    "S1": {
        "looks_like": "one reference well disagrees with the sample's other reference wells",
        "consistent_with": "that well: pipetting, evaporation, the seal or a failed reaction",
        "what_to_check": "re-run that well and look at its curve",
    },
    "S2": {
        "looks_like": "every gene of the sample comes up late together, references included",
        "consistent_with": "RNA or cDNA input, or extraction yield",
        "what_to_check": "the RNA concentration and RT input of that tube",
    },
    "S4": {
        "looks_like": "the sample's amplification efficiency shifts across assays",
        "consistent_with": "inhibitor carry-over from extraction",
        "what_to_check": "a SPUD assay or a dilution of that sample",
    },
    "S5": {
        "looks_like": "LinRegPCR noted a curve-quality issue on the well",
        "consistent_with": "that curve",
        "what_to_check": "look at the curve",
    },
    "S6": {
        "looks_like": "the well comes up close to its plate's no-template control",
        "consistent_with": "contamination on that plate and target",
        "what_to_check": "the NTC well, and its melt curve if the assay is SYBR",
    },
    "S7": {
        "looks_like": "the sample is in no comparison",
        "consistent_with": "an empty reference or marker well",
        "what_to_check": "the empty well",
    },
}
CANNOT_SHOW: dict[str, str] = {
    "S8": "flagged samples sharing an extraction batch, RT batch, operator or date (no sample "
    "sheet with annotations)",
    "single_target_well": "a single target well that is off: without replicates it cannot be "
    "told apart from biology",
    "group_wide_fault": "a fault shared by every sample of one group looks like biology",
    "sample_swap": "the wrong sample in the tube",
    "rna_integrity": "RNA integrity",
    "rt_replicates": "RT replicates",
    "no_rt_controls": "no-RT controls",
}
POSITION_CONFOUNDED = "position_confounded"  # every sample at the same well on every plate

_NOTE_CODES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"PCR efficiency outlier"), "efficiency_outlier"),
    (re.compile(r"indiv PCR eff is \S+ < \S+"), "low_well_efficiency"),
    (re.compile(r"baseline error"), "baseline_error"),
    (re.compile(r"no plateau"), "no_plateau"),
    (re.compile(r"only \d+ values in log phase"), "few_log_phase_points"),
    (re.compile(r"no amplification"), "no_amplification"),
    (re.compile(r"no TD0 found"), "no_td0"),
    (re.compile(r"Ncopy < 10"), "ncopy_below_10"),
    (re.compile(r"Ncopy > 100 Mio"), "ncopy_above_100m"),
)
NOTE_INFORMATION = frozenset({"ncopy_below_10", "ncopy_above_100m"})  # never an S5 failure
_STD_LABEL = re.compile(r"^STD_(\d+(?:\.\d+)?)$")  # dilution standards carry copies in the name
_WELL_KEY = re.compile(r"^(?P<run>[^/:]+)[/:](?P<well>[^/:]+)$")
_REQUIRED = ("run_id", "well", "sample", "sample_type", "target", "cq", "n0", "eff_indiv", "note")

METHOD_CARD: dict[str, Any] = {
    "id": "trace",
    "version": "1",
    "title": "Trace: from a result back to the wells to look at",
    "source": (
        "qPilot's own method. Robust z (median, 1.4826 x MAD); leave-one-out Welch in closed "
        "form; the normalisation factor as a quality signal (Vermeulen et al., Nucleic Acids "
        "Res 2011); LinRegPCR's well notes (Ruijter et al. 2009); MIQE 2.0's NTC window"
    ),
    "implementation": "qpilot/qpcr/trace.py",
    "inputs": [
        "per-well table: run_id, well, sample, sample_type, target, cq, n0, eff_indiv, note",
        "StudyModel (qpilot.qpcr.study.build_model): matrix, decision space, fixed groups",
    ],
    "outputs": [
        "TraceResult: ranked places to look, influential samples with nothing unusual, checks "
        "that found nothing, absent samples, the walked graph, facts",
        "DecisionCard of kind trace_set_aside for one place (keep / read from the other "
        "references / set aside)",
    ],
    "acceptance_tests": [
        "tests/engine/test_trace.py::test_demo_camta2_ranking",
        "tests/engine/test_trace.py::test_demo_absent_sample_1846",
        "tests/engine/test_trace.py::test_demo_well_k22",
        "tests/engine/test_trace.py::test_demo_study_counts",
        "tests/engine/test_trace.py::test_demo_json_is_byte_deterministic_across_processes",
        "tests/engine/test_trace.py::test_planted_reference_well_ranks_first_in_its_sample",
        "tests/engine/test_trace.py::test_planted_low_input_fires_s2_not_s1",
    ],
    "thresholds": TRACE_THRESHOLDS,
    "licence": "Apache-2.0",
    "card": METHOD_CARD_PATH,
}


class TraceError(ValueError):
    """The trace cannot be computed: an unknown gene, sample or well, or a bad argument."""


# =============================================================================================
# Result models (JSON-stable)
# =============================================================================================


class TraceNode(BaseModel):
    """One node of the walked lineage graph (only nodes the walk visited are kept).

    ``influence_log2`` is how much the root result moves if this node read as expected;
    ``influence_ci_share`` is the same as a share of the root's CI half-width (the largest
    over genes for a sample or well root). ``checks`` failed at this node; ``worst_below`` are
    the checks that fail anywhere in its subtree (computed before the walk). ``n_pruned``
    counts children the walk did not descend into.
    """

    id: str
    kind: str
    parent: str | None = None
    children: list[str] = Field(default_factory=list)
    address: dict[str, str | None] = Field(default_factory=dict)
    influence_log2: float | None = None
    influence_ci_share: float | None = None
    consequence: str | None = None
    checks: list[str] = Field(default_factory=list)
    worst_below: list[str] = Field(default_factory=list)
    z: float | None = None
    n_pruned: int = 0


class PlaceToLook(BaseModel):
    """A physical place (a well, or the sample's tube) where something is unusual.

    ``consequence`` is the class of its most consequential option (for the root gene in a
    gene trace; for any gene otherwise) and ``via`` that option; ``options`` hold every
    option's class, changed calls and changes. ``fold_off`` is ``2**|pull_log2|``, the factor
    by which every value of the sample reads off because of this reference well, and
    ``values_read`` says in which direction.
    """

    rank: int
    sample: str
    plate: str | None = None
    well: str | None = None
    target: str | None = None
    role: Role
    checks: list[str]
    z: float | None = None
    pull_log2: float | None = None
    fold_off: float | None = None
    values_read: Literal["high", "low"] | None = None
    feeds: int = 0
    cq: float | None = None
    plate_context: dict[str, Any] = {}
    detail: dict[str, Any] = {}
    consequence: str
    effect_log2: float
    via: str
    options: dict[str, dict[str, Any]]


class TraceResult(BaseModel):
    """One trace: the answer, the ranked places, what was checked, the graph and the facts."""

    root: dict[str, str]
    answer: Answer
    places: list[PlaceToLook]
    influential_nothing_unusual: list[dict[str, Any]]
    checked_nothing_found: list[str]
    cannot_show: list[str]
    not_applicable: list[str]
    absent: list[dict[str, Any]]
    summary: dict[str, Any]
    nodes: list[TraceNode]
    facts: dict[str, Fact]
    _ctx: Any = PrivateAttr(default=None)

    def to_json(self) -> str:
        """Byte-stable JSON (sorted keys, two-space indent, trailing newline)."""
        return dump_json(self.model_dump(mode="json"))

    def card(self, rank: int) -> DecisionCard:
        """The ``trace_set_aside`` Decision Card for the place at ``rank`` (1-based).

        Options: ``keep`` (recommended), ``read_from_other_refs`` (reference wells),
        ``set_aside_value`` (target wells: only that value) and ``set_aside`` (the sample,
        from every comparison); ``per_gene`` holds every gene's result under each option, with
        the groups fixed. The card's id and content depend on the place only, not on the
        result the trace started from, so opening it from two traces gives the same card.

        Raises:
            TraceError: No such rank, or the result was loaded from JSON (trace again).
        """
        if self._ctx is None:
            raise TraceError("this trace result has no context (loaded from JSON); trace again")
        if isinstance(rank, bool) or not isinstance(rank, int):
            raise TraceError("rank must be a whole number")
        if not 1 <= rank <= len(self.places):
            raise TraceError(f"no place at rank {rank}; this trace has {len(self.places)}")
        return _card(self._ctx, self.places[rank - 1])


# =============================================================================================
# The context: everything that does not depend on the root, computed once per study
# =============================================================================================


@dataclass(eq=False)
class TraceContext:
    """Study-level arrays every trace reads; built once by :func:`build_context`.

    Rows of every array are :attr:`units` (the matrix rows), columns :attr:`items` (the
    compared genes) or :attr:`refs` (the primary control genes).
    """

    space: QpcrSpace
    units: tuple[str, ...]
    unit_row: dict[str, int]
    sample_unit: dict[str, str]
    items: tuple[str, ...]
    item_col: dict[str, int]
    refs: tuple[str, ...]
    marker: str | None
    labels: tuple[str, str]
    in_hi: np.ndarray
    in_lo: np.ndarray
    values: np.ndarray
    ref_values: np.ndarray
    used: np.ndarray
    valid: np.ndarray
    base: ContrastArrays
    baseline: dict[str, Baseline]
    loo_log2fc: np.ndarray
    loo_call: np.ndarray
    shift_log2fc: np.ndarray
    shift_call: np.ndarray
    s1_dev: np.ndarray
    s1_expected: np.ndarray
    s1_z: np.ndarray
    s1_offset: np.ndarray
    s1_flag: dict[int, int]
    tube: pd.DataFrame
    wells: pd.DataFrame
    cells: dict[tuple[str, str], tuple[str, int]]
    cell_checks: dict[tuple[str, str], tuple[str, ...]]
    plates: dict[tuple[str, str], dict[str, Any]]
    absent: list[dict[str, Any]]
    restorable: dict[str, dict[str, Any]]
    replicates: bool
    confounded: bool
    row_tube: list[tuple[str, ...]] = field(default_factory=list)
    row_ref_side: list[tuple[str, ...]] = field(default_factory=list)
    row_below: list[tuple[str, ...]] = field(default_factory=list)
    target_checks: dict[int, dict[int, tuple[str, ...]]] = field(default_factory=dict)
    target_plates: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    plate_cq: dict[tuple[str, str], np.ndarray] = field(default_factory=dict)
    well_pos: dict[str, int] = field(default_factory=dict)
    well_columns: dict[str, np.ndarray] = field(default_factory=dict)
    tube_rows: dict[str, dict[str, Any]] = field(default_factory=dict)
    late_positions: dict[str, tuple[str, ...]] = field(default_factory=dict)
    robustness: Mapping[str, Any] | None = None
    #: The analysis traced: a cell of the decision space (the primary one unless given).
    cell: dict[str, Any] = field(default_factory=dict)
    #: Units x items: the values the cell's non-detect rule filled in (``None``: none).
    capped: np.ndarray | None = None
    timings: dict[str, float] = field(default_factory=dict)
    _cache: dict[Any, Any] = field(default_factory=dict)

    @property
    def planned(self) -> bool:
        """True when the traced analysis is the study's planned (primary) one."""
        return not self.cell or self.cell == self.space.primary

    @property
    def s1_applicable(self) -> bool:
        """S1 needs three or more references to say which one disagrees."""
        return len(self.refs) >= 3

    def unit_target_checks(self, unit: str) -> tuple[str, ...]:
        """Checks that fail on any of a unit's target wells."""
        found: set[str] = set()
        for gene in self.items:
            found.update(self.cell_checks.get((unit, gene), ()))
        return tuple(sorted(found))

    def unit_plates(self, unit: str) -> list[tuple[str, str]]:
        """``(run, target)`` of every well of a unit."""
        w = self.wells[self.wells["unit"] == unit]
        return sorted(set(zip(w["run_id"], w["target"], strict=True)))


def build_context(
    curves: pd.DataFrame,
    model: StudyModel,
    *,
    robustness: Mapping[str, Any] | None = None,
    cell: Mapping[str, Any] | None = None,
    comparison: str | None = None,
) -> TraceContext:
    """Compute everything a trace needs for one study (about a sixth of a second on the demo).

    Args:
        curves: The per-well table the model was built from (:func:`analyse_study`). The
            wells are read from ``model.inputs.primary_table`` when the model carries it (the
            same table with the design and the primary amplification rule applied; identical to
            ``curves`` on the legacy path).
        model: :func:`qpilot.qpcr.study.build_model` of that table.
        robustness: The study's stored robustness summary (``StudyResult.robustness``), used
            for the "choice to look at" answer; computed from the space when not given.
        cell: The analysis to trace, a cell of ``model.space`` (the one page traces the
            analysis in use: each Decision Card's applied option). The primary cell when not
            given. Groups stay the cell's cut-off's, held fixed in every scenario.
        comparison: A study with several comparisons: the one traced (its id; the first when
            not given). The space is focused on it (:meth:`QpcrSpace.focus`): its groups are
            the traced ones, every comparison is still evaluated and corrected together, and a
            sample set aside is set aside in every comparison. With a correction the
            leave-one-out and reference what-if calls are computed exactly, not in closed form.

    Raises:
        TraceError: The table lacks a column Trace needs, or the comparison is not the
            study's.
    """
    t0 = time.perf_counter()
    try:
        space: QpcrSpace = model.space.focus(comparison)
    except KeyError as err:
        raise TraceError(f"this study has no comparison {comparison!r}") from err
    cell = dict(space.primary if cell is None else cell)
    planned = cell == space.primary
    if not planned:  # a best pair is traced as the control genes it is
        from qpilot.qpcr.axes.normaliser import NotTraceable, as_refs_cell

        try:
            cell = as_refs_cell(cell, getattr(model, "axis_notes", {}).get("normaliser"))
        except NotTraceable as err:
            raise TraceError(f"Trace cannot follow this analysis: {err}") from None
    inputs = getattr(model, "inputs", None)
    table = getattr(inputs, "primary_table", None)
    table = curves if table is None else table
    if not planned and _matrix_cell(cell, space):
        from qpilot.trace.context import _cell_table  # the cell's rule and efficiency model

        table = _cell_table(model, cell)
    missing = [c for c in _REQUIRED if c not in table.columns]
    if missing:
        raise TraceError(f"the per-well table lacks the columns Trace needs: {missing}")
    units = tuple(str(u) for u in space.units)
    unit_row = {u: i for i, u in enumerate(units)}
    items = tuple(space.items)
    refs = tuple(cell["refs"])
    marker = space.design.marker if space.design is not None else None
    if space.design is not None:
        labels = marker_group_names(space.design.group_var)
    elif space.comparisons:
        labels = space.comparisons[0].labels
    else:
        labels = tuple(model.labels) if model.labels else ("group A", "group B")
    in_hi, in_lo = space.group_masks(cell)
    values, ref_values = space.cell_arrays(cell)
    # values the cell's non-detect rule filled in: a group none of whose values was detected
    # is not compared (as the space does), so every evaluation here is given them
    capped = space.cell_capped(cell)
    if capped is not None and not capped.any():
        capped = None
    base = space.evaluate_arrays(values, ref_values, in_hi, in_lo, capped=capped)
    half = base.half_ci
    baseline = {
        g: Baseline(float(base.log2fc[j]), str(base.conclusion[j]), float(half[j]))
        for j, g in enumerate(items)
    }
    refs_ok = ~np.isnan(ref_values).any(axis=1)
    used = (in_hi | in_lo) & refs_ok
    rel = values - ref_values.mean(axis=1)[:, None]
    valid = used[:, None] & ~np.isnan(rel)
    loo_log2fc, loo_call = _loo(
        rel,
        valid,
        in_hi,
        in_lo,
        space,
        base.conclusion,
        arrays=(values, ref_values),
        capped=capped,
    )
    t1 = time.perf_counter()

    dev, expected, z, offset = _s1(ref_values, used)
    s1_flag: dict[int, int] = {}
    if len(refs) >= 3:
        absz = np.abs(z)
        for i in np.flatnonzero(used & ~np.isnan(absz).all(axis=1)):
            r = int(np.nanargmax(absz[i]))
            if absz[i, r] > TRACE_THRESHOLDS["z"]:
                s1_flag[int(i)] = r
    shift_log2fc, shift_call = _shift(rel, valid, in_hi, in_lo, dev / max(len(refs), 1), space)
    if not _closed_form(space) or capped is not None:
        _corrected(
            space, values, ref_values, in_hi, in_lo, used, expected, loo_log2fc, loo_call, capped
        )
        _corrected_shift(
            space, values, ref_values, in_hi, in_lo, expected, shift_log2fc, shift_call, capped
        )
    t2 = time.perf_counter()

    units_map = getattr(inputs, "units", None)
    wells = _wells(table, units_map)
    unknown = wells[(wells["sample_type"] == "unkn") & ~wells["person_excluded"]]
    ordered = unknown.sort_values(["unit", "target", "run_id", "well"], kind="mergesort")
    n_wells = ordered.groupby(["unit", "target"], sort=False)["well"].transform("size")
    first = ordered.assign(n_wells=n_wells).drop_duplicates(["unit", "target"])
    cells = {
        (u, t): (k, int(n))
        for u, t, k, n in zip(
            first["unit"].to_numpy(),
            first["target"].to_numpy(),
            first.index.to_numpy(),
            first["n_wells"].to_numpy(),
            strict=True,
        )
    }
    flagged = unknown[unknown["s5"] | unknown["s6"]]
    cell_checks: dict[tuple[str, str], tuple[str, ...]] = {}
    for u, t, s5, s6 in zip(
        flagged["unit"].to_numpy(),
        flagged["target"].to_numpy(),
        flagged["s5"].to_numpy(),
        flagged["s6"].to_numpy(),
        strict=True,
    ):
        found = set(cell_checks.get((u, t), ())) | ({"S5"} if s5 else set())
        cell_checks[(u, t)] = tuple(sorted(found | ({"S6"} if s6 else set())))
    tube = _tube(unknown)
    plates = _plates(wells)
    pairs = zip(wells["sample"].to_numpy(), wells["unit"].to_numpy(), strict=True)
    sample_unit = {str(s): str(u) for s, u in pairs if s != u}
    replicates = bool((first["n_wells"] > 1).any())
    labels_per_unit = unknown.groupby("unit")["well"].nunique()
    confounded = bool(len(labels_per_unit)) and bool((labels_per_unit == 1).all())
    ctx = TraceContext(
        space=space,
        units=units,
        unit_row=unit_row,
        sample_unit=sample_unit,
        items=items,
        item_col={g: j for j, g in enumerate(items)},
        refs=refs,
        marker=marker,
        labels=(str(labels[0]), str(labels[1])),
        in_hi=in_hi,
        in_lo=in_lo,
        values=values,
        ref_values=ref_values,
        used=used,
        valid=valid,
        base=base,
        baseline=baseline,
        loo_log2fc=loo_log2fc,
        loo_call=loo_call,
        shift_log2fc=shift_log2fc,
        shift_call=shift_call,
        s1_dev=dev,
        s1_expected=expected,
        s1_z=z,
        s1_offset=offset,
        s1_flag=s1_flag,
        tube=tube,
        wells=wells,
        cells=cells,
        cell_checks=cell_checks,
        plates=plates,
        absent=[],
        restorable={},
        replicates=replicates,
        confounded=confounded,
        robustness=robustness,
        cell=cell,
        capped=capped,
    )
    matrix = getattr(model, "matrix", None)
    if not planned and _matrix_cell(cell, space):
        from qpilot.trace.context import _cell_matrix

        matrix = _cell_matrix(model, cell)
    _index_checks(ctx, unknown)
    ctx.absent, ctx.restorable = _absent(ctx, unknown, matrix)
    t3 = time.perf_counter()
    ctx.timings = {
        "contrasts_loo_s": t1 - t0,
        "s1_shift_s": t2 - t1,
        "wells_s": t3 - t2,
        "context_s": t3 - t0,
    }
    return ctx


def _index_checks(ctx: TraceContext, unknown: pd.DataFrame) -> None:
    """Fast row access, per-row failed checks (tube, references), per-item target checks."""
    ctx.well_pos = {k: n for n, k in enumerate(ctx.wells.index)}
    ctx.well_columns = {c: ctx.wells[c].to_numpy() for c in ctx.wells.columns}
    ctx.tube_rows = {
        str(u): dict(zip(ctx.tube.columns, values, strict=True))
        for u, values in zip(ctx.tube.index, ctx.tube.to_numpy(), strict=True)
    }
    tube_flags = {
        u: tuple(c for c, on in (("S2", s2), ("S4", s4)) if bool(on))
        for u, s2, s4 in zip(ctx.tube.index, ctx.tube["s2"], ctx.tube["s4"], strict=True)
    }
    ctx.row_tube = [tube_flags.get(u, ()) for u in ctx.units]
    ctx.row_ref_side = [
        tuple(sorted({c for r in range(len(ctx.refs)) for c in _ref_checks(ctx, i, r)}))
        for i in range(len(ctx.units))
    ]
    ctx.row_below = [
        tuple(sorted(set(t) | set(r))) for t, r in zip(ctx.row_tube, ctx.row_ref_side, strict=True)
    ]
    for (unit, target), checks in ctx.cell_checks.items():
        j, i = ctx.item_col.get(target), ctx.unit_row.get(unit)
        if j is not None and i is not None:
            ctx.target_checks.setdefault(j, {})[i] = checks
    for run, target in ctx.plates:
        ctx.target_plates.setdefault(target, []).append((run, target))
    late = unknown[unknown["dcq"] > TRACE_THRESHOLDS["late_cycles"]]
    ctx.late_positions = {
        str(label): tuple(sorted(set(runs)))
        for label, runs in late.groupby("well", sort=True)["run_id"]
    }
    with_cq = unknown[unknown["cq"].notna()]
    for (run, target), cq in with_cq.groupby(["run_id", "target"], sort=True)["cq"]:
        ctx.plate_cq[(str(run), str(target))] = cq.to_numpy(dtype=float)


# ---------------------------------------------------------------------------------------------
# Closed-form what-ifs (influence) and exact ones (consequence)
# ---------------------------------------------------------------------------------------------


def _matrix_cell(cell: Mapping[str, Any], space: QpcrSpace) -> bool:
    """True when the cell's per-well table differs from the primary one.

    Its amplification rule, efficiency model or correction between plates.
    """
    return any(
        dim in cell and cell[dim] != space.primary.get(dim)
        for dim in ("amp_call", "efficiency", "interrun")
    )


def _closed_form(space: QpcrSpace) -> bool:
    """Whether a unit's what-if is the one-comparison Welch update the closed forms compute.

    Not for a paired comparison (it tests within-pair differences, and a unit set aside takes
    its pair with it), nor with a correction over several comparisons (the call uses the
    corrected p, which moves when a unit leaves its group in any of them): those are evaluated
    exactly, unit by unit (:func:`_corrected`, :func:`_corrected_shift`).
    """
    specs = space.comparisons
    if not specs:
        return True
    return not (specs[0].paired or (space.correction != "none" and len(specs) > 1))


def _loo(
    rel: np.ndarray,
    valid: np.ndarray,
    in_hi: np.ndarray,
    in_lo: np.ndarray,
    space: QpcrSpace,
    base_calls: np.ndarray,
    *,
    arrays: tuple[np.ndarray, np.ndarray] | None = None,
    capped: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Leave-one-out log2fc and call for every (unit, item), from centred group sums.

    Dropping x from a group of n with mean m and squared deviations D: mean m - e/(n-1),
    deviations D - e^2 n/(n-1), with e = x - m. Units not used for an item get NaN and the
    baseline call. Results within ``boundary_tol`` of the call rule are recomputed exactly; a
    paired or corrected study is then evaluated exactly throughout (:func:`_closed_form`).
    """
    mask_hi, mask_lo = valid & in_hi[:, None], valid & in_lo[:, None]
    hi = group_stats(rel, mask_hi)
    lo = group_stats(rel, mask_lo)
    log2fc = np.full(rel.shape, np.nan)
    p = np.full(rel.shape, np.nan)
    items = tuple(space.items)
    call = np.broadcast_to(base_calls, rel.shape).astype(object)
    for mask, own, other, own_first in ((mask_hi, hi, lo, True), (mask_lo, lo, hi, False)):
        n, mean, var = own
        n1 = n - 1.0
        with np.errstate(divide="ignore", invalid="ignore"):
            e = rel - mean
            mean1 = mean - e / n1
            var1 = (var * n1 - e**2 * n / n1) / (n1 - 1.0)
        dropped = (np.broadcast_to(n1, rel.shape), mean1, var1)
        pair = (dropped, other) if own_first else (other, dropped)
        w = welch_arrays(items, *pair, space.rule, with_ci=False)
        log2fc = np.where(mask, w.log2fc, log2fc)
        p = np.where(mask, w.p, p)
        call = np.where(mask, w.conclusion, call)
    _recheck(rel, valid, in_hi, in_lo, space, log2fc, p, call, arrays, capped)
    return log2fc, call


def _corrected(
    space: QpcrSpace,
    values: np.ndarray,
    ref_values: np.ndarray,
    in_hi: np.ndarray,
    in_lo: np.ndarray,
    used: np.ndarray,
    expected: np.ndarray,
    loo_log2fc: np.ndarray,
    loo_call: np.ndarray,
    capped: np.ndarray | None = None,
) -> None:
    """Each unit set aside, exactly: with a correction a call depends on every comparison.

    The closed form above is one Welch test; with several comparisons and a correction the
    traced call uses the corrected p, which moves when a unit leaves its group in any of them,
    and a paired comparison tests within-pair differences (the unit's pair leaves with it).
    Each traced unit is set aside in every comparison and the space evaluates it (in place).
    """
    del expected
    for i in np.flatnonzero(used):
        hi, lo = in_hi.copy(), in_lo.copy()
        hi[i] = lo[i] = False
        exact = space.evaluate_arrays(values, ref_values, hi, lo, capped=capped)
        loo_log2fc[i] = np.where(np.isnan(loo_log2fc[i]), np.nan, exact.log2fc)
        loo_call[i] = np.where(np.isnan(loo_log2fc[i]), loo_call[i], exact.conclusion)


def _corrected_shift(
    space: QpcrSpace,
    values: np.ndarray,
    ref_values: np.ndarray,
    in_hi: np.ndarray,
    in_lo: np.ndarray,
    expected: np.ndarray,
    shift_log2fc: np.ndarray,
    shift_call: np.ndarray,
    capped: np.ndarray | None = None,
) -> None:
    """One reference value read as expected, exactly (see :func:`_corrected`), in place."""
    rows, cols = np.nonzero(np.isfinite(shift_log2fc).any(axis=2))
    for i, r in zip(rows.tolist(), cols.tolist(), strict=True):
        if not np.isfinite(expected[i, r]):
            continue
        refs = ref_values.copy()
        refs[i, r] = expected[i, r]
        exact = space.evaluate_arrays(values, refs, in_hi, in_lo, capped=capped)
        keep = np.isfinite(shift_log2fc[i, r])
        shift_log2fc[i, r] = np.where(keep, exact.log2fc, np.nan)
        shift_call[i, r] = np.where(keep, exact.conclusion, shift_call[i, r])


def _near_rule(log2fc: np.ndarray, p: np.ndarray, space: QpcrSpace) -> np.ndarray:
    tol = TRACE_THRESHOLDS["boundary_tol"]
    rule = space.rule
    with np.errstate(invalid="ignore"):
        near_fc = np.abs(np.abs(log2fc) - rule.min_log2fc) <= tol
        near_p = np.abs(p - rule.alpha) <= tol * rule.alpha
    return near_fc | near_p


def _recheck(rel, valid, in_hi, in_lo, space, log2fc, p, call, arrays=None, capped=None) -> None:
    """Recompute exactly the leave-one-out rows that sit on the call rule's lines."""
    rows = np.flatnonzero((_near_rule(log2fc, p, space) & valid).any(axis=1))
    if not len(rows):
        return
    values, refs = space.cell_arrays() if arrays is None else arrays
    for i in rows:
        hi, lo = in_hi.copy(), in_lo.copy()
        hi[i] = lo[i] = False
        exact = space.evaluate_arrays(values, refs, hi, lo, capped=capped)
        keep = valid[i]
        log2fc[i] = np.where(keep, exact.log2fc, log2fc[i])
        p[i] = np.where(keep, exact.p, p[i])
        call[i] = np.where(keep, exact.conclusion, call[i])


def _shift(
    rel: np.ndarray,
    valid: np.ndarray,
    in_hi: np.ndarray,
    in_lo: np.ndarray,
    pull: np.ndarray,
    space: QpcrSpace,
) -> tuple[np.ndarray, np.ndarray]:
    """log2fc and call of every item when one reference value of one unit reads as expected.

    Replacing reference r of unit u by its expected value moves every relative value of u by
    ``pull[u, r]`` (deviation / k). Changing x by d in a group of n with mean m and squared
    deviations D: mean m + d/n, deviations D + 2d(x - m) + d^2 (1 - 1/n). Shape units x refs x
    items; NaN where the unit is not in the S1 population or has no value. A paired or
    corrected study is then evaluated exactly (:func:`_closed_form`).
    """
    n_units, n_items = rel.shape
    out = np.full((n_units, pull.shape[1], n_items), np.nan)
    call = np.full(out.shape, "none", dtype=object)
    if not pull.shape[1]:
        return out, call
    d = pull[:, :, None]
    x = rel[:, None, :]
    items = tuple(space.items)
    hi = group_stats(rel, valid & in_hi[:, None])
    lo = group_stats(rel, valid & in_lo[:, None])
    for group, own, other, own_first in ((in_hi, hi, lo, True), (in_lo, lo, hi, False)):
        n, mean, var = own
        with np.errstate(divide="ignore", invalid="ignore"):
            mean1 = mean + d / n
            var1 = (var * (n - 1.0) + 2 * d * (x - mean) + d**2 * (1 - 1 / n)) / (n - 1.0)
        moved = (np.broadcast_to(n, out.shape), mean1, var1)
        pair = (moved, other) if own_first else (other, moved)
        w = welch_arrays(items, *pair, space.rule, with_ci=False)
        mask = (valid & group[:, None])[:, None, :] & ~np.isnan(d)
        out = np.where(mask, w.log2fc, out)
        call = np.where(mask, w.conclusion, call)
    return out, call


def _exact(ctx: TraceContext, key: tuple) -> ContrastArrays:
    """Exact evaluation of one option with the groups fixed, cached.

    Keys: ``("drop", row)``, ``("ref", row, r)``, ``("value", row, col)``, ``("restore", row)``.
    """
    if key in ctx._cache:
        return ctx._cache[key]
    values, refs = ctx.values, ctx.ref_values
    hi, lo = ctx.in_hi, ctx.in_lo
    kind, row = key[0], key[1]
    if kind == "drop":
        hi, lo = hi.copy(), lo.copy()
        hi[row] = lo[row] = False
    elif kind == "ref":
        refs = refs.copy()
        refs[row, key[2]] = ctx.s1_expected[row, key[2]]
    elif kind == "value":
        values = values.copy()
        values[row, key[2]] = np.nan
    elif kind == "restore":
        info = ctx.restorable[ctx.units[row]]
        refs = refs.copy()
        refs[row, info["ref_col"]] = info["fill"]
        hi, lo = hi.copy(), lo.copy()
        (hi if info["group"] == "high" else lo)[row] = True
    else:
        raise ValueError(f"unknown option {kind!r}")
    out = ctx.space.evaluate_arrays(values, refs, hi, lo, capped=ctx.capped)
    ctx._cache[key] = out
    return out


def _option(ctx: TraceContext, arrays: ContrastArrays) -> dict[str, tuple[float, str]]:
    pairs = zip(arrays.log2fc.tolist(), arrays.conclusion.tolist(), strict=True)
    return dict(zip(ctx.items, pairs, strict=True))


def _consequence(ctx: TraceContext, key: tuple, root: str | None) -> Consequence:
    """The consequence of one exact option, for ``root`` (or any gene), cached per option."""
    ck = ("cons", key)
    if ck not in ctx._cache:
        ctx._cache[ck] = classify_roots(ctx.baseline, _option(ctx, _exact(ctx, key)))
    return ctx._cache[ck][root]


def _row(ctx: TraceContext, key: str) -> dict[str, Any]:
    """One well as a plain dict (cached; a pandas row lookup is far slower)."""
    rows = ctx._cache.setdefault("rows", {})
    if key not in rows:
        pos = ctx.well_pos[key]
        rows[key] = {col: values[pos] for col, values in ctx.well_columns.items()}
    return rows[key]


# ---------------------------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------------------------


def robust_z(x: np.ndarray) -> np.ndarray:
    """``(x - median) / (1.4826 x MAD)`` over the finite values; all NaN when MAD is 0."""
    x = np.asarray(x, dtype=float)
    ok = ~np.isnan(x)
    out = np.full(x.shape, np.nan)
    if not ok.any():
        return out
    med = float(np.median(x[ok]))
    mad = float(np.median(np.abs(x[ok] - med)))
    if mad == 0:
        return out
    out[ok] = (x[ok] - med) / (MAD_SCALE * mad)
    return out


def _s1(ref_values: np.ndarray, used: np.ndarray) -> tuple[np.ndarray, ...]:
    """S1 arrays over units x refs: deviation, expected value, robust z; and the offsets.

    Population: the compared units (every reference present). Expected value of reference r:
    mean of the unit's other references + r's offset (the median over the population of
    ``L[r] - mean(other refs)``). NaN outside the population; z only with three references.
    """
    n_units, k = ref_values.shape
    dev = np.full((n_units, k), np.nan)
    expected = np.full((n_units, k), np.nan)
    z = np.full((n_units, k), np.nan)
    offset = np.full(k, np.nan)
    if k < 2 or not used.any():
        return dev, expected, z, offset
    block = ref_values[used]
    others = (block.sum(axis=1, keepdims=True) - block) / (k - 1)
    raw = block - others
    offset = np.median(raw, axis=0)
    expected[used] = others + offset
    dev[used] = raw - offset
    if k >= 3:
        z[used] = np.column_stack([robust_z(dev[used, r]) for r in range(k)])
    return dev, expected, z, offset


def _note_codes(note: str) -> tuple[str, ...]:
    codes = []
    for token in (t.strip() for t in str(note).split(";")):
        if not token:
            continue
        code = next((c for pattern, c in _NOTE_CODES if pattern.fullmatch(token)), "other_note")
        codes.append(code)
    return tuple(sorted(set(codes)))


def _wells(table: pd.DataFrame, units: Mapping[str, str] | None) -> pd.DataFrame:
    """Every well with its unit, note codes, plate-relative shifts and the S5 / S6 flags.

    A plate is one target on one run (the demo has one target per run). ``dcq`` / ``deff``
    are a study well's Cq / efficiency minus its plate's median over study wells.
    """
    cols = ["run_id", "well", "sample", "sample_type", "target", "cq", "n0", "eff_indiv", "note"]
    w = table[cols].copy()
    for c in ("run_id", "well", "sample", "sample_type", "target", "note"):
        w[c] = w[c].astype(str)
    for c in ("cq", "n0", "eff_indiv"):
        w[c] = w[c].astype(float)
    if EXCLUDED in table.columns:
        w["person_excluded"] = table[EXCLUDED].astype(bool).to_numpy()
    else:
        w["person_excluded"] = False
    if "eff_target" in table.columns:
        w["eff_target"] = table["eff_target"].astype(float)
    else:
        w["eff_target"] = np.nan
    w["unit"] = unit_map(w["sample"].tolist(), units).to_numpy().astype(str)
    w.index = pd.Index((w["run_id"] + "/" + w["well"]).to_numpy(), name="key")
    codes = {note: _note_codes(note) for note in w["note"].unique()}
    w["note_codes"] = w["note"].map(codes)
    study = (w["sample_type"] == "unkn") & ~w["person_excluded"]
    s = w[study]
    plate = [s["run_id"], s["target"]]
    w["dcq"] = np.nan
    w["deff"] = np.nan
    w.loc[study, "dcq"] = s["cq"] - s.groupby(plate)["cq"].transform("median")
    w.loc[study, "deff"] = s["eff_indiv"] - s.groupby(plate)["eff_indiv"].transform("median")
    failing = w["note_codes"].map(lambda c: bool(set(c) - NOTE_INFORMATION))
    w["s5"] = study & w["n0"].notna() & failing
    ntc = w[(w["sample_type"] == "ntc") & ~w["person_excluded"] & w["cq"].notna()]
    lowest = ntc.sort_values(["run_id", "target", "cq", "well"]).drop_duplicates(
        ["run_id", "target"]
    )
    by_plate = {
        (r, t): (c, x)
        for r, t, c, x in zip(
            lowest["run_id"], lowest["target"], lowest["cq"], lowest["well"], strict=True
        )
    }
    pairs = list(zip(w["run_id"].to_numpy(), w["target"].to_numpy(), strict=True))
    w["ntc_cq"] = [by_plate.get(p, (np.nan, ""))[0] for p in pairs]
    w["ntc_well"] = [by_plate.get(p, (np.nan, ""))[1] for p in pairs]
    w["ntc_gap"] = w["ntc_cq"] - w["cq"]
    w["s6"] = study & w["cq"].notna() & (w["ntc_gap"] <= TRACE_THRESHOLDS["ntc_window_cycles"])
    return w


def _tube(unknown: pd.DataFrame) -> pd.DataFrame:
    """Per unit: median Cq shift (S2) and efficiency shift (S4) against the plates, robust z."""
    per = (
        unknown.assign(empty=unknown["n0"].isna())
        .groupby("unit")
        .agg(
            dcq=("dcq", "median"),
            deff=("deff", "median"),
            n_wells=("n0", "size"),
            n_empty=("empty", "sum"),
        )
    )
    per["z_late"] = robust_z(per["dcq"].to_numpy())
    per["z_eff"] = robust_z(per["deff"].to_numpy())
    z = TRACE_THRESHOLDS["z"]
    with np.errstate(invalid="ignore"):
        per["s2"] = per["z_late"] > z
        per["s4"] = (per["z_eff"].abs() > z) & (
            per["deff"].abs() > TRACE_THRESHOLDS["eff_shift_floor"]
        )
    return per.sort_index()


def _plates(wells: pd.DataFrame) -> dict[tuple[str, str], dict[str, Any]]:
    """Per (run, target): study-well median Cq, lowest standard, NTCs, plate efficiency."""
    keys = ["run_id", "target"]
    study = wells[(wells["sample_type"] == "unkn") & ~wells["person_excluded"]]
    by = study.groupby(keys, sort=True)
    agg = pd.DataFrame(
        {
            "n_study_wells": by.size(),
            "n_study_wells_with_cq": by["cq"].count(),
            "study_median_cq": by["cq"].median(),
            "n_study_wells_in_ntc_window": by["s6"].sum(),
        }
    )
    efficiency = wells.groupby(keys, sort=True)["eff_target"].first()
    ntc = wells[(wells["sample_type"] == "ntc") & ~wells["person_excluded"]]
    n_ntc = ntc.groupby(keys)["well"].size()
    amplified = ntc[ntc["cq"].notna()].sort_values([*keys, "cq", "well"])
    n_amp = amplified.groupby(keys)["well"].size()
    lowest = amplified.drop_duplicates(keys).set_index(keys)
    std = wells[(wells["sample_type"] == "std") & wells["sample"].str.fullmatch(_STD_LABEL)]
    std = std.assign(copies=std["sample"].str.extract(_STD_LABEL, expand=False).astype(float))
    std = std[std["copies"] == std.groupby(keys)["copies"].transform("min")]
    standards = std.groupby(keys).agg(
        copies=("copies", "first"), cq=("cq", "mean"), n=("cq", "count")
    )
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for key in sorted(set(efficiency.index)):
        run, target = str(key[0]), str(key[1])
        row = agg.loc[key] if key in agg.index else None
        info: dict[str, Any] = {
            "plate": run,
            "target": target,
            "n_study_wells": int(row["n_study_wells"]) if row is not None else 0,
            "n_study_wells_with_cq": int(row["n_study_wells_with_cq"]) if row is not None else 0,
            "study_median_cq": _num(row["study_median_cq"]) if row is not None else None,
            "plate_efficiency": _num(efficiency.get(key)),
            "n_ntc": int(n_ntc.get(key, 0)),
            "n_ntc_amplified": int(n_amp.get(key, 0)),
            "lowest_ntc_cq": _num(lowest.loc[key, "cq"]) if key in lowest.index else None,
            "lowest_ntc_well": str(lowest.loc[key, "well"]) if key in lowest.index else None,
            "n_study_wells_in_ntc_window": int(row["n_study_wells_in_ntc_window"])
            if row is not None
            else 0,
        }
        if key in standards.index:
            info["lowest_standard_copies"] = float(standards.loc[key, "copies"])
            info["lowest_standard_cq"] = _num(standards.loc[key, "cq"])
            info["lowest_standard_n_wells"] = int(standards.loc[key, "n"])
        out[(run, target)] = info
    return out


def _absent(
    ctx: TraceContext, unknown: pd.DataFrame, matrix: pd.DataFrame | None
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """S7: the units in no comparison, the wells that explain it, and the restorable ones."""
    marker_mode = ctx.marker is not None
    grouped = ctx.in_hi | ctx.in_lo
    candidates = [
        i for i in range(len(ctx.units)) if not ctx.used[i] and (marker_mode or grouped[i])
    ]
    marker_vals = None
    threshold = None
    if marker_mode and matrix is not None and ctx.marker in matrix.columns:
        marker_vals = matrix[ctx.marker].reindex(list(ctx.units)).to_numpy(dtype=float)
        rel_marker = marker_vals - ctx.ref_values.mean(axis=1)
        compared = np.sort(rel_marker[ctx.used], kind="mergesort")
        if len(compared):
            cut = (ctx.cell or ctx.space.primary)["cut"]
            threshold = float(compared[int((1 - cut) * len(compared))])
    out: list[dict[str, Any]] = []
    restorable: dict[str, dict[str, Any]] = {}
    k = len(ctx.refs)
    for i in candidates:
        unit = ctx.units[i]
        empty_refs = [r for r, ref in enumerate(ctx.refs) if np.isnan(ctx.ref_values[i, r])]
        empty_marker = bool(marker_vals is not None and np.isnan(marker_vals[i]))
        reasons = [_reason(ctx, unit, ctx.refs[r], "empty_reference_well") for r in empty_refs]
        if empty_marker:
            reasons.append(_reason(ctx, unit, ctx.marker, "empty_marker_well"))
        entry: dict[str, Any] = {"sample": unit, "scope": "study", "reasons": reasons}
        if len(empty_refs) == 1 and not empty_marker and k >= 2:
            r = empty_refs[0]
            others = [x for x in range(k) if x != r]
            fill = float(ctx.ref_values[i, others].mean() + ctx.s1_offset[r])
            if marker_mode:
                if threshold is None or marker_vals is None:
                    fill_group = None
                else:
                    filled = ctx.ref_values[i].copy()
                    filled[r] = fill
                    fill_group = "high" if marker_vals[i] - filled.mean() >= threshold else "rest"
            else:
                fill_group = "high" if ctx.in_hi[i] else "rest"
            if fill_group is not None and np.isfinite(fill):
                restorable[unit] = {"ref_col": r, "fill": fill, "group": fill_group}
                entry["restore"] = {
                    "reference": ctx.refs[r],
                    "fill_log2": fill,
                    "group": ctx.labels[0] if fill_group == "high" else ctx.labels[1],
                }
        out.append(entry)
    in_matrix = set(ctx.units)
    targets = sorted(set(unknown["target"]))
    for unit, w in unknown[~unknown["unit"].isin(in_matrix)].groupby("unit", sort=True):
        lacking = sorted(set(targets) - set(w["target"]))
        reasons = [
            {"reason": "not_measured_for_every_gene", "target": t, "plate": None, "well": None}
            for t in lacking
        ]
        out.append({"sample": str(unit), "scope": "study", "reasons": reasons})
    out.sort(key=lambda e: e["sample"])
    return out, restorable


def _reason(ctx: TraceContext, unit: str, target: str, reason: str) -> dict[str, Any]:
    key, n = ctx.cells.get((unit, target), (None, 0))
    entry: dict[str, Any] = {"reason": reason, "target": target, "plate": None, "well": None}
    if key is None:  # no well carries it: say so when a person left its wells out
        w = ctx.wells
        out = w[(w["unit"] == unit) & (w["target"] == target) & w["person_excluded"]]
        if len(out):
            first = out.sort_values(["run_id", "well"], kind="mergesort").iloc[0]
            entry.update(plate=str(first["run_id"]), well=str(first["well"]), left_out=True)
    if key is not None:
        row = _row(ctx, key)
        entry.update(
            plate=str(row["run_id"]),
            well=str(row["well"]),
            note_codes=list(row["note_codes"]),
            cq=_num(row["cq"]),
            n_wells=n,
        )
    return entry


# =============================================================================================
# The walk
# =============================================================================================


class _Graph:
    """Visited nodes in depth-first pre-order; a plate shared by several wells is listed once."""

    def __init__(self) -> None:
        self.nodes: dict[str, TraceNode] = {}
        self.order: list[str] = []
        self.pruned = 0

    def add(self, node: TraceNode) -> TraceNode:
        if node.parent is not None and node.parent in self.nodes:
            self.nodes[node.parent].children.append(node.id)
        if node.id in self.nodes:
            return self.nodes[node.id]
        self.nodes[node.id] = node
        self.order.append(node.id)
        return node

    def prune(self, parent: str, n: int) -> None:
        if n:
            self.nodes[parent].n_pruned += int(n)
            self.pruned += int(n)

    def listed(self) -> list[TraceNode]:
        return [self.nodes[i] for i in self.order]


@dataclass
class _Place:
    """A place the walk found, before its options are evaluated and it is ranked."""

    row: int
    role: str
    key: str | None
    target: str | None
    checks: tuple[str, ...]
    ref_col: int | None = None
    item_col: int | None = None
    options: dict[str, Consequence] = field(default_factory=dict)
    best: str = "keep"


def _shares(ctx: TraceContext, delta: np.ndarray, cols: np.ndarray) -> np.ndarray:
    """``|delta| / half_ci`` per entry (0 where there is no CI or no finite delta)."""
    half = ctx.base.half_ci[cols]
    with np.errstate(divide="ignore", invalid="ignore"):
        share = np.abs(delta) / half
    return np.where(np.isfinite(share), share, 0.0)


def _absmax(a: np.ndarray, axis: int | None = None) -> np.ndarray | float:
    filled = np.where(np.isfinite(a), np.abs(a), 0.0)
    if filled.size == 0:
        return 0.0 if axis is None else np.zeros(a.shape[0])
    return filled.max() if axis is None else filled.max(axis=axis)


def _kept(share: np.ndarray, changes: np.ndarray, below: np.ndarray) -> np.ndarray:
    """The pruning rule: keep a child that moves the result, changes a call or hides a check."""
    return (share >= TRACE_THRESHOLDS["eps_ci_share"]) | changes | below


def _well_node(ctx: TraceContext, key: str, kind: str, parent: str | None, **extra) -> TraceNode:
    row = _row(ctx, key)
    return TraceNode(
        id=f"well:{key}",
        kind=kind,
        parent=parent,
        address={
            "sample": str(row["sample"]),
            "plate": str(row["run_id"]),
            "well": str(row["well"]),
            "target": str(row["target"]),
        },
        **extra,
    )


def _plate_node(ctx: TraceContext, key: str, parent: str) -> TraceNode:
    row = _row(ctx, key)
    run, target = str(row["run_id"]), str(row["target"])
    return TraceNode(
        id=f"plate:{run}:{target}",
        kind="plate_controls",
        parent=parent,
        address={"plate": run, "target": target},
    )


def _ref_checks(ctx: TraceContext, i: int, r: int) -> tuple[str, ...]:
    """Checks that fail on reference well r of unit row i (S1 only on the flagged one)."""
    found = set(ctx.cell_checks.get((ctx.units[i], ctx.refs[r]), ()))
    if ctx.s1_flag.get(i) == r:
        found.add("S1")
    return tuple(sorted(found))


def _well_checks(ctx: TraceContext, key: str, i: int | None, r: int | None) -> tuple[str, ...]:
    """Checks that fail on one well (its own S5 / S6 flags, and S1 if it is the flagged ref)."""
    row = _row(ctx, key)
    found = {c for c, on in (("S5", row["s5"]), ("S6", row["s6"])) if bool(on)}
    if i is not None and r is not None and ctx.s1_flag.get(i) == r:
        found.add("S1")
    return tuple(sorted(found))


def _walk_normaliser(
    ctx: TraceContext, graph: _Graph, places: list[_Place], i: int, parent: str, cols: np.ndarray
) -> None:
    """The normaliser of unit row ``i`` and its reference wells, scored on items ``cols``."""
    unit = ctx.units[i]
    delta = ctx.shift_log2fc[i][:, cols] - ctx.base.log2fc[cols]  # refs x cols
    calls = (ctx.shift_call[i][:, cols] != ctx.base.conclusion[cols]) & np.isfinite(delta)
    share = _shares(ctx, delta, cols).max(axis=1, initial=0.0)
    size = _absmax(delta, axis=1)
    changes = calls.any(axis=1)
    checks = [_ref_checks(ctx, i, r) for r in range(len(ctx.refs))]
    below = ctx.row_ref_side[i]
    if (
        share.max(initial=0.0) < TRACE_THRESHOLDS["eps_ci_share"]
        and not changes.any()
        and not below
    ):
        graph.prune(parent, 1)
        return
    node_id = f"normaliser:{unit}"
    graph.add(
        TraceNode(
            id=node_id,
            kind="normaliser",
            parent=parent,
            address={"sample": unit},
            influence_log2=_num(size.max(initial=0.0)),
            influence_ci_share=_num(share.max(initial=0.0)),
            consequence="changes_call" if changes.any() else None,
            worst_below=list(below),
        )
    )
    keep = _kept(share, changes, np.array([bool(c) for c in checks]))
    graph.prune(node_id, int((~keep).sum()))
    for r in sorted(np.flatnonzero(keep), key=lambda r: (-size[r], r)):
        key = ctx.cells.get((unit, ctx.refs[r]), (None, 0))[0]
        if key is None:
            continue
        node = graph.add(
            _well_node(
                ctx,
                key,
                "reference_well",
                node_id,
                influence_log2=_num(size[r]),
                influence_ci_share=_num(share[r]),
                consequence="changes_call" if changes[r] else None,
                checks=list(checks[r]),
                worst_below=list(checks[r]),
                z=_num(ctx.s1_z[i, r]),
            )
        )
        if checks[r]:
            graph.add(_plate_node(ctx, key, node.id))
            places.append(_Place(i, "reference_well", key, ctx.refs[r], checks[r], ref_col=r))


def _walk_gene(ctx: TraceContext, j: int) -> tuple[_Graph, list[_Place], list[dict[str, Any]]]:
    """Conclusion -> group set (absent samples) and sample values -> wells -> plates."""
    gene = ctx.items[j]
    b = ctx.baseline[gene]
    graph = _Graph()
    places: list[_Place] = []
    root_id = f"conclusion:{gene}"
    graph.add(TraceNode(id=root_id, kind="conclusion", address={"target": gene}))
    absent = _absent_for_gene(ctx, j)
    group_id = f"groups:{gene}"
    s7 = ["S7"] if absent else []
    graph.add(TraceNode(id=group_id, kind="group_set", parent=root_id, worst_below=s7))
    for entry in absent:
        aid = f"absent:{entry['sample']}"
        graph.add(
            TraceNode(
                id=aid,
                kind="absent_sample",
                parent=group_id,
                address={"sample": entry["sample"]},
                checks=["S7"],
                worst_below=["S7"],
            )
        )
        for reason in entry["reasons"]:
            if reason.get("plate"):
                key = f"{reason['plate']}/{reason['well']}"
                graph.add(_well_node(ctx, key, "empty_well", aid, checks=["S7"]))
    rows = np.flatnonzero(ctx.valid[:, j])
    cols = np.array([j])
    delta = ctx.loo_log2fc[rows, j] - b.log2fc
    changed = ctx.loo_call[rows, j] != b.call
    share = _shares(ctx, delta[:, None], cols)[:, 0]
    target = ctx.target_checks.get(j, {})
    below = np.array([bool(ctx.row_below[i]) or i in target for i in rows], dtype=bool)
    keep = _kept(share, changed, below)
    graph.prune(root_id, int((~keep).sum()))
    order = sorted(np.flatnonzero(keep), key=lambda n: (-abs(delta[n]), ctx.units[rows[n]]))
    influential: list[dict[str, Any]] = []
    for n in order:
        i = int(rows[n])
        unit = ctx.units[i]
        tube = ctx.row_tube[i]
        target_checks = target.get(i, ())
        vid = f"value:{unit}:{gene}"
        graph.add(
            TraceNode(
                id=vid,
                kind="sample_value",
                parent=root_id,
                address={"sample": unit, "target": gene},
                influence_log2=_num(abs(delta[n])),
                influence_ci_share=_num(share[n]),
                consequence="changes_call" if changed[n] else None,
                checks=list(tube),
                worst_below=sorted(set(ctx.row_below[i]) | set(target_checks)),
                z=_num(_tube_z(ctx, unit)),
            )
        )
        if tube:
            places.append(_Place(i, "sample", None, None, tube))
        key = ctx.cells.get((unit, gene), (None, 0))[0]
        if key is not None:
            graph.add(
                _well_node(
                    ctx,
                    key,
                    "target_well",
                    vid,
                    influence_log2=_num(abs(delta[n])),
                    influence_ci_share=_num(share[n]),
                    consequence="changes_call" if changed[n] else None,
                    checks=list(target_checks),
                    worst_below=list(target_checks),
                )
            )
            if target_checks:
                graph.add(_plate_node(ctx, key, f"well:{key}"))
                places.append(_Place(i, "target_well", key, gene, target_checks, item_col=j))
        _walk_normaliser(ctx, graph, places, i, vid, cols)
        unusual = ctx.row_below[i] or target_checks
        if not unusual and len(influential) < TRACE_THRESHOLDS["influential_top"]:
            cons = classify(ctx.baseline, _loo_option(ctx, i), gene)
            influential.append(
                {
                    "sample": unit,
                    "delta_log2": delta[n],
                    "fold": 2 ** abs(delta[n]),
                    "consequence": cons.cls,
                    "changed_calls": list(cons.changed_calls),
                    "group": _group_of(ctx, i),
                }
            )
    graph.nodes[root_id].worst_below = sorted({c for p in places for c in p.checks} | set(s7))
    return graph, places, influential


def _loo_option(ctx: TraceContext, i: int) -> dict[str, tuple[float, str]]:
    """Every item with unit row ``i`` left out (closed form; baseline where it is not used)."""
    log2fc = np.where(ctx.valid[i], ctx.loo_log2fc[i], ctx.base.log2fc)
    pairs = zip(log2fc.tolist(), ctx.loo_call[i].tolist(), strict=True)
    return dict(zip(ctx.items, pairs, strict=True))


def _group_of(ctx: TraceContext, i: int) -> str:
    return ctx.labels[0] if ctx.in_hi[i] else ctx.labels[1]


def _tube_z(ctx: TraceContext, unit: str) -> float | None:
    """The z of a tube place: S4's when only S4 fails, else S2's (late side)."""
    row = ctx.tube_rows.get(unit)
    if row is None:
        return None
    z = row["z_eff"] if bool(row["s4"]) and not bool(row["s2"]) else row["z_late"]
    return float(z) if np.isfinite(z) else None


def _absent_for_gene(ctx: TraceContext, j: int) -> list[dict[str, Any]]:
    """The study's absent samples, then compared samples with no value for this gene."""
    gene = ctx.items[j]
    out = [dict(e) for e in ctx.absent]
    for i in np.flatnonzero(ctx.used & ~ctx.valid[:, j]):
        unit = ctx.units[i]
        reason = _reason(ctx, unit, gene, "empty_target_well")
        out.append({"sample": unit, "scope": "gene", "reasons": [reason]})
    return out


# =============================================================================================
# Options, ranking and the three entries
# =============================================================================================

_OPTION_KEYS = {
    "read_from_other_refs": lambda p: ("ref", p.row, p.ref_col),
    "set_aside_value": lambda p: ("value", p.row, p.item_col),
    "set_aside": lambda p: ("drop", p.row),
}


def _place_options(ctx: TraceContext, place: _Place, root: str | None) -> None:
    """Every option of a place, exact with fixed groups; ``best`` is the most consequential."""
    names = ["keep"]
    if place.role == "reference_well" and place.ref_col is not None:
        names.append("read_from_other_refs")
    if place.role == "target_well" and place.item_col is not None:
        names.append("set_aside_value")
    names.append("set_aside")
    place.options = {
        name: NOTHING if name == "keep" else _consequence(ctx, _OPTION_KEYS[name](place), root)
        for name in names
    }
    others = sorted(
        (n for n in names if n != "keep"), key=lambda n: (sort_key(place.options[n]), n)
    )
    place.best = others[0]


def _option_view(ctx: TraceContext, place: _Place, name: str, root: str | None) -> dict:
    view = _cons_view(place.options[name])
    if root is not None:
        j = ctx.item_col[root]
        if name == "keep":
            view.update(new_log2fc=ctx.baseline[root].log2fc, new_call=ctx.baseline[root].call)
        else:
            arrays = _exact(ctx, _OPTION_KEYS[name](place))
            view.update(new_log2fc=arrays.log2fc[j], new_call=str(arrays.conclusion[j]))
    return _clean(view)


def _cons_view(cons: Consequence) -> dict[str, Any]:
    view = cons.as_dict()
    view["class"] = view.pop("cls")
    return view


def _rank(ctx: TraceContext, places: list[_Place], root: str | None) -> list[PlaceToLook]:
    """Evaluate every place's options and rank: class, |effect|, |z|, sample id, well."""
    for place in places:
        _place_options(ctx, place, root)

    def key(p: _Place) -> tuple:
        z = _place_z(ctx, p)
        return (*sort_key(p.options[p.best]), -abs(z or 0.0), ctx.units[p.row], p.key or "")

    return [
        _place_model(ctx, place, rank, root)
        for rank, place in enumerate(sorted(places, key=key), start=1)
    ]


def _place_z(ctx: TraceContext, place: _Place) -> float | None:
    if place.role == "reference_well" and place.ref_col is not None:
        z = ctx.s1_z[place.row, place.ref_col]
        return float(z) if np.isfinite(z) else None
    if place.role == "sample":
        return _tube_z(ctx, ctx.units[place.row])
    return None


def _place_model(ctx: TraceContext, place: _Place, rank: int, root: str | None) -> PlaceToLook:
    i, unit = place.row, ctx.units[place.row]
    cons = place.options[place.best]
    detail: dict[str, Any] = {}
    plate_context: dict[str, Any] = {}
    fields: dict[str, Any] = {"feeds": int(ctx.valid[i].sum())}
    if place.key is not None:
        row = _row(ctx, place.key)
        fields.update(plate=str(row["run_id"]), well=str(row["well"]), cq=_num(row["cq"]))
        plate_context = _plate_context(ctx, place.key)
        if "S5" in place.checks:
            detail["S5"] = {"note_codes": list(row["note_codes"])}
        if "S6" in place.checks:
            detail["S6"] = {
                "ntc_cq": row["ntc_cq"],
                "ntc_well": str(row["ntc_well"]),
                "gap_cycles": row["ntc_gap"],
            }
    if place.role == "reference_well" and place.ref_col is not None:
        r = place.ref_col
        pull = float(ctx.s1_dev[i, r] / len(ctx.refs))
        if np.isfinite(pull):
            fields.update(
                pull_log2=_num(pull),
                fold_off=_num(2 ** abs(pull)),
                values_read="high" if pull < 0 else "low",
            )
        detail["S1"] = {
            "observed_log2": ctx.ref_values[i, r],
            "expected_log2": ctx.s1_expected[i, r],
            "dev_log2": ctx.s1_dev[i, r],
            "z": ctx.s1_z[i, r],
            "flagged": ctx.s1_flag.get(i) == r,
            "n_other_refs": len(ctx.refs) - 1,
            "other_refs_max_abs_z": _others_z(ctx, i, r),
        }
    elif place.role == "target_well":
        fields["feeds"] = 1
    elif place.role == "sample":
        row = ctx.tube_rows[unit]
        detail["S2"] = {
            "median_cq_shift_cycles": row["dcq"],
            "z": row["z_late"],
            "n_empty_wells": int(row["n_empty"]),
            "n_wells": int(row["n_wells"]),
        }
        detail["S4"] = {"median_efficiency_shift": row["deff"], "z": row["z_eff"]}
    return PlaceToLook(
        rank=rank,
        sample=unit,
        target=place.target,
        role=place.role,  # type: ignore[arg-type]
        checks=list(place.checks),
        z=_num(_place_z(ctx, place)),
        plate_context=_clean(plate_context),
        detail=_clean(detail),
        consequence=cons.cls,
        effect_log2=_num(cons.effect) or 0.0,
        via=place.best,
        options={name: _option_view(ctx, place, name, root) for name in place.options},
        **fields,
    )


def _others_z(ctx: TraceContext, i: int, r: int) -> float | None:
    """Largest robust ``|z|`` among unit i's other references, judged without reference r.

    The S1 check run on the other references alone (each against the mean of the remaining
    ones plus its usual offset to them), so a far-off reference r does not drag their
    expected values; needs three other references.
    """
    keep = [x for x in range(len(ctx.refs)) if x != r]
    if len(keep) < 3:
        return None
    ck = ("others_z", r)
    if ck not in ctx._cache:
        block = ctx.ref_values[ctx.used][:, keep]
        others = (block.sum(axis=1, keepdims=True) - block) / (len(keep) - 1)
        raw = block - others
        dev = raw - np.median(raw, axis=0)
        z = np.full((len(ctx.units), len(keep)), np.nan)
        z[ctx.used] = np.column_stack([robust_z(dev[:, c]) for c in range(len(keep))])
        ctx._cache[ck] = z
    z = np.abs(ctx._cache[ck][i])
    return float(z[np.isfinite(z)].max()) if np.isfinite(z).any() else None


def _plate_context(ctx: TraceContext, key: str) -> dict[str, Any]:
    """The plate's controls and where this well sits on it (latest Cq = rank 1); cached."""
    ck = ("plate_context", key)
    if ck not in ctx._cache:
        ctx._cache[ck] = _plate_context_of(ctx, key)
    return dict(ctx._cache[ck])


def _plate_context_of(ctx: TraceContext, key: str) -> dict[str, Any]:
    row = _row(ctx, key)
    info = dict(ctx.plates.get((str(row["run_id"]), str(row["target"])), {}))
    cq = float(row["cq"])
    if np.isfinite(cq):
        study = ctx.plate_cq.get((str(row["run_id"]), str(row["target"])))
        if study is not None:
            info["cq_rank_latest"] = int((study > cq).sum()) + 1
    info["same_position_late_on"] = _same_position(ctx, str(row["well"]))
    return info


def _same_position(ctx: TraceContext, label: str) -> list[str]:
    """Plates where the study well at this position is late (context only; never blamed)."""
    return list(ctx.late_positions.get(label, ()))


def _choice_flips(ctx: TraceContext) -> dict[str, list[str]]:
    """Per gene, the analysis choices that flip it when changed alone (the robustness rule)."""
    if "choice" in ctx._cache:
        return ctx._cache["choice"]
    out: dict[str, set[str]] = {g: set() for g in ctx.items}
    if ctx.robustness is not None and ctx.planned:  # stored impacts are the planned analysis's
        for g in ctx.items:
            impact = getattr(ctx.robustness.get(g), "impact", None) or {}
            out[g] = {d for d, v in impact.items() if v.get("flips")}
    else:
        space = ctx.space
        cell = ctx.cell or space.primary
        for dim, options in space.dimensions.items():
            for value in options:
                if value == cell.get(dim, space.primary[dim]):
                    continue
                results = space.evaluate({**cell, dim: value})
                for g in ctx.items:
                    if results[g].conclusion != ctx.baseline[g].call:
                        out[g].add(dim)
    ctx._cache["choice"] = {g: sorted(v) for g, v in out.items()}
    return ctx._cache["choice"]


def _answer(places: list[PlaceToLook], choice: list[str] | None) -> Answer:
    if any(p.consequence != "changes_nothing" for p in places):
        return "place_to_look"
    if choice:
        return "choice_to_look_at"
    return "nothing_to_look_at"


def _check_top(top: int) -> int:
    if isinstance(top, bool) or not isinstance(top, int) or top < 1:
        raise TraceError("top must be a whole number of at least 1")
    return top


def _limits(ctx: TraceContext) -> tuple[list[str], list[str]]:
    """``(cannot_show, not_applicable)`` for this study."""
    cannot = list(CANNOT_SHOW)
    not_applicable = []
    (cannot if ctx.replicates else not_applicable).append("S9")
    if ctx.confounded:
        cannot.append(POSITION_CONFOUNDED)
    if not ctx.s1_applicable:
        not_applicable.append("S1")
    return sorted(cannot), sorted(not_applicable)


def _ran(ctx: TraceContext) -> list[str]:
    return ["S2", "S4", "S5", "S7"] + (["S1"] if ctx.s1_applicable else [])


def _ntc_status(ctx: TraceContext, plates: Iterable[tuple[str, str]]) -> dict[str, dict]:
    """Per run: NTC wells, how many amplified, the lowest NTC Cq (over the given targets)."""
    out: dict[str, dict] = {}
    for run, target in sorted(set(plates)):
        info = ctx.plates.get((run, target))
        if info is None:
            continue
        entry = out.setdefault(
            run, {"n_ntc": 0, "n_ntc_amplified": 0, "lowest_ntc_cq": None, "targets": []}
        )
        entry["n_ntc"] += info["n_ntc"]
        entry["n_ntc_amplified"] += info["n_ntc_amplified"]
        entry["targets"].append(target)
        low = info["lowest_ntc_cq"]
        if low is not None and (entry["lowest_ntc_cq"] is None or low < entry["lowest_ntc_cq"]):
            entry["lowest_ntc_cq"] = low
            entry["lowest_ntc_well"] = info["lowest_ntc_well"]
    return out


def _nothing_found(ran: Iterable[str], found: Iterable[str], ntc: Mapping[str, dict]) -> list[str]:
    """Checks that ran and found nothing; ``S6:<plate>`` only where every NTC stayed clean."""
    found = set(found)
    out = {c for c in ran if c not in found}
    out |= {f"S6:{run}" for run, e in ntc.items() if e["n_ntc"] > 0 and not e["n_ntc_amplified"]}
    return sorted(out)


def _corrected_p(ctx: TraceContext, j: int) -> dict[str, Any]:
    """Several comparisons with a correction: the corrected p the call uses, and its name.

    Nothing for a study with one comparison (or without a correction), so its summary and words
    are what they were.
    """
    from qpilot.qpcr.contrast import CORRECTION_NAMES

    space = ctx.space
    name = CORRECTION_NAMES.get(space.correction)
    if not space.comparisons or name is None or ctx.base.p_call is None:
        return {}
    return {"p_adjusted": float(ctx.base.p_call[j]), "correction": name}


def _by_class(places: Sequence[PlaceToLook]) -> dict[str, int]:
    return {c: sum(p.consequence == c for p in places) for c in CLASSES}


def trace_gene(ctx: TraceContext, gene: str, *, top: int = 3) -> TraceResult:
    """Trace one gene's result back to the places to look at (Trace Precedents).

    Args:
        ctx: From :func:`build_context`.
        gene: A compared gene (``ctx.items``).
        top: How many ranked places to return; the summary counts all of them.

    Returns:
        The :class:`TraceResult`; ``summary`` carries the baseline numbers, the number of
        samples whose single removal flips the call (``n_loo_flips``) and the largest
        single-sample effect.

    Raises:
        TraceError: Unknown, withheld or control gene; a bad ``top``.
    """
    top = _check_top(top)
    if not isinstance(gene, str) or gene not in ctx.item_col:
        if gene in ctx.space.withheld:
            raise TraceError(f"{gene} has no comparison: {ctx.space.withheld[gene]}")
        if gene in ctx.refs or (ctx.marker is not None and gene == ctx.marker):
            raise TraceError(f"{gene} is a control gene or the marker; trace a sample or a well")
        raise TraceError(f"unknown gene {gene!r}")
    j = ctx.item_col[gene]
    b = ctx.baseline[gene]
    graph, found, influential = _walk_gene(ctx, j)
    ranked = _rank(ctx, found, gene)
    rows = np.flatnonzero(ctx.valid[:, j])
    delta = ctx.loo_log2fc[rows, j] - b.log2fc
    flips = sorted(ctx.units[i] for i in rows[ctx.loo_call[rows, j] != b.call])
    n_max = int(np.argmax(np.abs(delta))) if len(delta) else None
    absent = _absent_for_gene(ctx, j)
    for entry in absent:
        if entry["sample"] in ctx.restorable:
            cons = _consequence(ctx, ("restore", ctx.unit_row[entry["sample"]]), gene)
            entry["restore"] = {**entry.get("restore", {}), **_cons_view(cons)}
    choice = _choice_flips(ctx)[gene]
    plates = [p for t in (gene, *ctx.refs) for p in ctx.target_plates.get(t, ())]
    ntc = _ntc_status(ctx, plates)
    found_checks = {c for p in ranked for c in p.checks} | ({"S7"} if absent else set())
    cannot, not_applicable = _limits(ctx)
    rule = ctx.space.rule
    more = ranked[top:]
    summary = {
        "gene": gene,
        "log2fc": b.log2fc,
        "fc": 2**b.log2fc,
        "fold": 2 ** abs(b.log2fc),
        "direction": "lower" if b.log2fc < 0 else "higher",
        "p": ctx.base.p[j],
        **_corrected_p(ctx, j),
        "call": b.call,
        "half_ci_log2": b.half_ci,
        "ci": [2 ** (b.log2fc - b.half_ci), 2 ** (b.log2fc + b.half_ci)],
        "n_hi": ctx.base.n_hi[j],
        "n_lo": ctx.base.n_lo[j],
        "group_labels": list(ctx.labels),
        "rule": {
            "alpha": rule.alpha,
            "min_log2fc": rule.min_log2fc,
            "min_fold": 2**rule.min_log2fc,
        },
        "distance_to_line_log2": abs(b.log2fc) - rule.min_log2fc,
        "n_loo_flips": len(flips),
        "loo_flip_samples": flips,
        "max_single_effect_log2": delta[n_max] if n_max is not None else None,
        "max_single_effect_sample": ctx.units[rows[n_max]] if n_max is not None else None,
        "max_single_effect_fold": 2 ** abs(delta[n_max]) if n_max is not None else None,
        "n_places": len(ranked),
        "n_places_by_class": _by_class(ranked),
        "n_shown": min(top, len(ranked)),
        "n_more": len(more),
        "n_more_by_class": _by_class(more),
        "n_absent_study": len(ctx.absent),
        "n_absent_gene": sum(e["scope"] == "gene" for e in absent),
        "n_restorable": len(ctx.restorable),
        "restore_all": _restore_all(ctx, gene),
        "choice_flips": choice,
        "eps_log2": TRACE_THRESHOLDS["eps_ci_share"] * b.half_ci,
        "n_nodes_visited": len(graph.order),
        "n_nodes_pruned": graph.pruned,
        "ntc_by_plate": ntc,
        "n_genes": len(ctx.items),
    }
    return _result(
        ctx,
        {"kind": "gene", "id": gene},
        _answer(ranked, choice),
        ranked[:top],
        influential,
        _nothing_found(_ran(ctx), found_checks, ntc),
        (cannot, not_applicable),
        absent,
        summary,
        graph,
    )


def _restore_all(ctx: TraceContext, root: str | None) -> dict[str, Any] | None:
    """Every restorable absent sample brought back at once (fixed groups, fixed threshold)."""
    if not ctx.restorable:
        return None
    ck = ("restore_all",)
    if ck not in ctx._cache:
        refs = ctx.ref_values.copy()
        hi, lo = ctx.in_hi.copy(), ctx.in_lo.copy()
        for unit, info in sorted(ctx.restorable.items()):
            i = ctx.unit_row[unit]
            refs[i, info["ref_col"]] = info["fill"]
            (hi if info["group"] == "high" else lo)[i] = True
        ctx._cache[ck] = ctx.space.evaluate_arrays(ctx.values, refs, hi, lo, capped=ctx.capped)
    cons = classify(ctx.baseline, _option(ctx, ctx._cache[ck]), root)
    n_high = sum(info["group"] == "high" for info in ctx.restorable.values())
    return {**_cons_view(cons), "n_samples": len(ctx.restorable), "n_to_first_group": n_high}


def _resolve_unit(ctx: TraceContext, sample: str) -> str:
    if not isinstance(sample, str) or not sample:
        raise TraceError("give a sample name")
    if sample in ctx.unit_row or any(e["sample"] == sample for e in ctx.absent):
        return sample
    if sample in ctx.sample_unit:
        return ctx.sample_unit[sample]
    raise TraceError(f"unknown sample {sample!r}")


def _absent_entry(ctx: TraceContext, unit: str) -> dict[str, Any] | None:
    entry = next((e for e in ctx.absent if e["sample"] == unit), None)
    if entry is None and (unit not in ctx.unit_row or not ctx.used[ctx.unit_row[unit]]):
        reason = {"reason": "not_in_a_compared_group", "target": None, "plate": None, "well": None}
        entry = {"sample": unit, "scope": "study", "reasons": [reason]}
    return entry


def trace_sample(ctx: TraceContext, sample: str, *, top: int = 3) -> TraceResult:
    """Trace one sample: what is unusual about it, and what it does to the conclusions.

    Consequences here are study-wide (any gene). A sample in no comparison gets the answer
    ``absent`` with the wells that left it out and what bringing it back would change.

    Raises:
        TraceError: Unknown sample; a bad ``top``.
    """
    top = _check_top(top)
    unit = _resolve_unit(ctx, sample)
    root = {"kind": "sample", "id": sample}
    entry = _absent_entry(ctx, unit)
    if entry is not None:
        return _absent_result(ctx, root, entry)
    i = ctx.unit_row[unit]
    graph = _Graph()
    places: list[_Place] = []
    root_id = f"sample:{unit}"
    tube = ctx.row_tube[i]
    graph.add(
        TraceNode(
            id=root_id,
            kind="sample",
            address={"sample": unit},
            checks=list(tube),
            worst_below=sorted(set(ctx.row_below[i]) | set(ctx.unit_target_checks(unit))),
            z=_num(_tube_z(ctx, unit)),
        )
    )
    if tube:
        places.append(_Place(i, "sample", None, None, tube))
    cols = np.flatnonzero(ctx.valid[i])
    _walk_normaliser(ctx, graph, places, i, root_id, cols)
    delta = ctx.loo_log2fc[i, cols] - ctx.base.log2fc[cols]
    changed = ctx.loo_call[i, cols] != ctx.base.conclusion[cols]
    share = _shares(ctx, delta, cols)
    checks = [ctx.cell_checks.get((unit, ctx.items[j]), ()) for j in cols]
    keep = _kept(share, changed, np.array([bool(c) for c in checks], dtype=bool))
    graph.prune(root_id, int((~keep).sum()))
    clean_sample = not ctx.row_below[i]
    influential: list[dict[str, Any]] = []
    for n in sorted(np.flatnonzero(keep), key=lambda n: (-abs(delta[n]), ctx.items[cols[n]])):
        j = int(cols[n])
        gene = ctx.items[j]
        vid = f"value:{unit}:{gene}"
        graph.add(
            TraceNode(
                id=vid,
                kind="sample_value",
                parent=root_id,
                address={"sample": unit, "target": gene},
                influence_log2=_num(abs(delta[n])),
                influence_ci_share=_num(share[n]),
                consequence="changes_call" if changed[n] else None,
                worst_below=list(checks[n]),
            )
        )
        key = ctx.cells.get((unit, gene), (None, 0))[0]
        if key is not None and checks[n]:
            graph.add(_well_node(ctx, key, "target_well", vid, checks=list(checks[n])))
            graph.add(_plate_node(ctx, key, f"well:{key}"))
            places.append(_Place(i, "target_well", key, gene, checks[n], item_col=j))
        elif clean_sample and len(influential) < TRACE_THRESHOLDS["influential_top"]:
            influential.append(
                {
                    "gene": gene,
                    "delta_log2": delta[n],
                    "fold": 2 ** abs(delta[n]),
                    "consequence": "changes_call" if changed[n] else "changes_nothing",
                }
            )
    ranked = _rank(ctx, places, None)
    flagged = ctx.s1_flag.get(i)
    read = _consequence(ctx, ("ref", i, flagged), None) if flagged is not None else None
    tube_row = ctx.tube_rows.get(unit)
    ntc = _ntc_status(ctx, ctx.unit_plates(unit))
    cannot, not_applicable = _limits(ctx)
    n_max = int(np.argmax(np.abs(delta))) if len(delta) else None
    summary = {
        "sample": unit,
        "in_comparison": True,
        "group": _group_of(ctx, i),
        "n_values": len(cols),
        "set_aside": _cons_view(_consequence(ctx, ("drop", i), None)),
        "read_from_other_refs": _cons_view(read) if read is not None else None,
        "references": [_reference_view(ctx, i, r) for r in range(len(ctx.refs))],
        "late": {
            "median_cq_shift_cycles": tube_row["dcq"] if tube_row is not None else None,
            "z": tube_row["z_late"] if tube_row is not None else None,
        },
        "efficiency": {
            "median_efficiency_shift": tube_row["deff"] if tube_row is not None else None,
            "z": tube_row["z_eff"] if tube_row is not None else None,
        },
        "max_loo_effect_log2": delta[n_max] if n_max is not None else None,
        "max_loo_gene": ctx.items[cols[n_max]] if n_max is not None else None,
        "n_places": len(ranked),
        "n_places_by_class": _by_class(ranked),
        "n_shown": min(top, len(ranked)),
        "n_more": max(len(ranked) - top, 0),
        "n_absent_study": len(ctx.absent),
        "n_nodes_visited": len(graph.order),
        "n_nodes_pruned": graph.pruned,
        "ntc_by_plate": ntc,
        "n_genes": len(ctx.items),
    }
    found_checks = {c for p in ranked for c in p.checks}
    return _result(
        ctx,
        root,
        _answer(ranked, None),
        ranked[:top],
        influential,
        _nothing_found(_ran(ctx), found_checks, ntc),
        (cannot, not_applicable),
        [],
        summary,
        graph,
    )


def _reference_view(ctx: TraceContext, i: int, r: int) -> dict[str, Any]:
    key = ctx.cells.get((ctx.units[i], ctx.refs[r]), (None, 0))[0]
    row = _row(ctx, key) if key is not None else None
    return {
        "reference": ctx.refs[r],
        "plate": str(row["run_id"]) if row is not None else None,
        "well": str(row["well"]) if row is not None else None,
        "cq": row["cq"] if row is not None else None,
        "dev_log2": ctx.s1_dev[i, r],
        "z": ctx.s1_z[i, r],
        "pull_log2": ctx.s1_dev[i, r] / len(ctx.refs),
        "flagged": ctx.s1_flag.get(i) == r,
    }


def _absent_result(ctx: TraceContext, root: dict[str, str], entry: dict[str, Any]) -> TraceResult:
    """The answer ``absent``: the wells that left the sample out, and bringing it back."""
    unit = entry["sample"]
    entry = dict(entry)
    graph = _Graph()
    aid = f"absent:{unit}"
    graph.add(TraceNode(id=aid, kind="absent_sample", address={"sample": unit}, checks=["S7"]))
    for reason in entry["reasons"]:
        if reason.get("plate"):
            key = f"{reason['plate']}/{reason['well']}"
            graph.add(_well_node(ctx, key, "empty_well", aid, checks=["S7"]))
    restore = None
    if unit in ctx.restorable:
        cons = _consequence(ctx, ("restore", ctx.unit_row[unit]), None)
        restore = {**entry.get("restore", {}), **_cons_view(cons)}
        entry["restore"] = restore
    summary = {
        "sample": unit,
        "in_comparison": False,
        "n_reasons": len(entry["reasons"]),
        "restore": restore,
        "n_absent_study": len(ctx.absent),
        "n_genes": len(ctx.items),
        "n_nodes_visited": len(graph.order),
        "n_nodes_pruned": 0,
    }
    return _result(ctx, root, "absent", [], [], [], _limits(ctx), [entry], summary, graph)


def parse_well(well_key: str) -> tuple[str, str]:
    """``"RUN/WELL"`` or ``"RUN:WELL"`` -> ``(run_id, well)``.

    Raises:
        TraceError: Not of that form.
    """
    if not isinstance(well_key, str):
        raise TraceError("give a well as PLATE:WELL or PLATE/WELL")
    match = _WELL_KEY.fullmatch(well_key.strip())
    if match is None:
        raise TraceError(f"not a well address (PLATE:WELL or PLATE/WELL): {well_key!r}")
    return match.group("run"), match.group("well")


def trace_well(ctx: TraceContext, well_key: str, *, top: int = 3) -> TraceResult:
    """Trace one well forward (Trace Dependents): what it feeds and what it changes.

    Accepts ``"RUN:WELL"`` or ``"RUN/WELL"``. A reference well feeds every value of its
    sample; a target well feeds one value; an NTC well is traced to the compared wells of its
    plate within the window of its own Cq; a well of a sample in no comparison gets
    ``absent``; standards, the marker and excluded wells feed no compared value. The well
    itself is the place (rank 1) when it feeds a value; consequences are study-wide. For a
    target well ``summary["limit"]`` says why its value cannot be told apart from biology
    (``single_target_well``, or ``S9`` when its replicate wells exist but are not compared).

    Raises:
        TraceError: Unknown well; a bad ``top``.
    """
    top = _check_top(top)
    run, label = parse_well(well_key)
    key = f"{run}/{label}"
    if key not in ctx.wells.index:
        raise TraceError(f"no well {label} on plate {run}")
    row = _row(ctx, key)
    unit, target, kind = str(row["unit"]), str(row["target"]), str(row["sample_type"])
    root = {"kind": "well", "id": key}
    about: dict[str, Any] = {
        "well_key": key,
        "plate": run,
        "well": label,
        "sample": str(row["sample"]),
        "target": target,
        "sample_type": kind,
        "cq": row["cq"],
        "note_codes": list(row["note_codes"]),
        "person_excluded": bool(row["person_excluded"]),
        "plate_context": _plate_context(ctx, key),
        "n_genes": len(ctx.items),
    }
    if kind == "ntc":
        return _trace_ntc(ctx, key, about, top)
    i = ctx.unit_row.get(unit)
    feeds_nothing = kind != "unkn" or bool(row["person_excluded"])
    if not feeds_nothing and _absent_entry(ctx, unit) is not None:
        out = _absent_result(ctx, root, _absent_entry(ctx, unit))
        out.summary = _clean({**out.summary, **about, "role": "absent_sample", "feeds": 0})
        return _finish(ctx, out)
    if feeds_nothing or i is None or not (target in ctx.refs or target in ctx.item_col):
        role = (
            "excluded"
            if bool(row["person_excluded"])
            else (
                "marker"
                if target == ctx.marker
                else ("control" if kind != "unkn" else "not_compared")
            )
        )
        graph = _Graph()
        graph.add(_well_node(ctx, key, "control_well", None))
        summary = {**about, "role": role, "feeds": 0}
        return _result(
            ctx, root, "nothing_to_look_at", [], [], [], _limits(ctx), [], summary, graph
        )
    graph = _Graph()
    limit: str | None = None
    if target in ctx.refs:
        r = ctx.refs.index(target)
        checks = _well_checks(ctx, key, i, r)
        if abs(np.nan_to_num(ctx.s1_z[i, r])) > TRACE_THRESHOLDS["z"]:  # this well's own z
            checks = tuple(sorted(set(checks) | {"S1"}))
        cols = np.flatnonzero(ctx.valid[i])
        delta = ctx.shift_log2fc[i, r, cols] - ctx.base.log2fc[cols]
        calls = (ctx.shift_call[i, r, cols] != ctx.base.conclusion[cols]) & np.isfinite(delta)
        share = _shares(ctx, delta, cols)
        node = graph.add(
            _well_node(
                ctx,
                key,
                "reference_well",
                None,
                influence_log2=_num(_absmax(delta)),
                influence_ci_share=_num(share.max(initial=0.0)),
                checks=list(checks),
                worst_below=list(checks),
                z=_num(ctx.s1_z[i, r]),
            )
        )
        keep = _kept(share, calls, np.zeros(len(cols), dtype=bool))
        graph.prune(node.id, int((~keep).sum()))
        for n in sorted(np.flatnonzero(keep), key=lambda n: (-abs(delta[n]), n)):
            gene = ctx.items[cols[n]]
            graph.add(
                TraceNode(
                    id=f"value:{unit}:{gene}",
                    kind="sample_value",
                    parent=node.id,
                    address={"sample": unit, "target": gene},
                    influence_log2=_num(abs(delta[n])),
                    influence_ci_share=_num(share[n]),
                    consequence="changes_call" if calls[n] else None,
                )
            )
        place = _Place(i, "reference_well", key, target, checks, ref_col=r)
        ran = ["S5", "S6"] + (["S1"] if ctx.s1_applicable else [])
    else:
        j = ctx.item_col[target]
        checks = _well_checks(ctx, key, None, None)
        node = graph.add(_well_node(ctx, key, "target_well", None, checks=list(checks)))
        place = _Place(i, "target_well", key, target, checks, item_col=j)
        ran = ["S5", "S6"]
        limit = _target_limit(ctx, unit, target)
    graph.add(_plate_node(ctx, key, node.id))
    ranked = _rank(ctx, [place], None)
    best = ranked[0]
    ntc = _ntc_status(ctx, [(run, target)])
    summary = {
        **about,
        "role": place.role,
        "feeds": best.feeds,
        "consequence": best.consequence,
        "via": best.via,
        "n_nodes_visited": len(graph.order),
        "n_nodes_pruned": graph.pruned,
        "ntc_by_plate": ntc,
    }
    if limit is not None:
        summary["limit"] = limit
    answer: Answer = (
        "nothing_to_look_at" if best.consequence == "changes_nothing" else "place_to_look"
    )
    return _result(
        ctx,
        root,
        answer,
        ranked[:top],
        [],
        _nothing_found(ran, checks, ntc),
        _limits(ctx),
        [],
        summary,
        graph,
    )


def _target_limit(ctx: TraceContext, unit: str, target: str) -> str:
    """Why a target well's value cannot be told apart from biology (the well trace says so).

    ``single_target_well``: the sample has this one well for the gene, so nothing in the data
    can show whether it is off (Trace cannot tell from biology without replicates).
    ``S9``: the sample has replicate wells, but the replicate check is not built.
    """
    n_wells = ctx.cells.get((unit, target), (None, 0))[1]
    return "single_target_well" if n_wells <= 1 else "S9"


def _trace_ntc(ctx: TraceContext, key: str, about: dict[str, Any], top: int) -> TraceResult:
    """An NTC well: the compared wells of its plate within the window of its own Cq."""
    run, target = about["plate"], about["target"]
    root = {"kind": "well", "id": key}
    graph = _Graph()
    node = graph.add(_well_node(ctx, key, "control_well", None))
    cq = float(about["cq"]) if about["cq"] is not None else math.nan
    places: list[_Place] = []
    n_in_window = 0
    if np.isfinite(cq):
        w = ctx.wells
        study = (w["run_id"] == run) & (w["target"] == target) & (w["sample_type"] == "unkn")
        near = w[
            study & ~w["person_excluded"] & (w["cq"] >= cq - TRACE_THRESHOLDS["ntc_window_cycles"])
        ]
        n_in_window = len(near)
        for k in sorted(near.index):
            i = ctx.unit_row.get(str(near.loc[k, "unit"]))
            if i is None or not ctx.used[i]:
                continue
            if target in ctx.refs:
                r = ctx.refs.index(target)
                checks = tuple(sorted(set(_well_checks(ctx, k, i, r)) | {"S6"}))
                places.append(_Place(i, "reference_well", k, target, checks, ref_col=r))
            elif target in ctx.item_col and ctx.valid[i, ctx.item_col[target]]:
                checks = tuple(sorted(set(_well_checks(ctx, k, None, None)) | {"S6"}))
                places.append(
                    _Place(i, "target_well", k, target, checks, item_col=ctx.item_col[target])
                )
            else:
                continue
            graph.add(_well_node(ctx, k, places[-1].role, node.id, checks=list(checks)))
    node.worst_below = ["S6"] if places else []
    ranked = _rank(ctx, places, None)
    ntc = _ntc_status(ctx, [(run, target)])
    summary = {
        **about,
        "role": "ntc",
        "feeds": 0,
        "n_study_wells_in_window": n_in_window,
        "n_compared_wells_in_window": len(ranked),
        "n_places": len(ranked),
        "n_places_by_class": _by_class(ranked),
        "n_more": max(len(ranked) - top, 0),
        "ntc_by_plate": ntc,
        "n_nodes_visited": len(graph.order),
        "n_nodes_pruned": 0,
    }
    found = {"S6"} if ranked else set()
    return _result(
        ctx,
        root,
        _answer(ranked, None),
        ranked[:top],
        [],
        _nothing_found(["S6"] if np.isfinite(cq) else [], found, ntc),
        _limits(ctx),
        [],
        summary,
        graph,
    )


# =============================================================================================
# Result assembly, facts, JSON
# =============================================================================================


def _root_slug(root: Mapping[str, str]) -> str:
    if root["kind"] == "gene":
        return slug(root["id"])
    return f"{root['kind']}_{slug(root['id'])}"


def _result(
    ctx: TraceContext,
    root: dict[str, str],
    answer: Answer,
    places: list[PlaceToLook],
    influential: list[dict[str, Any]],
    nothing_found: list[str],
    limits: tuple[list[str], list[str]],
    absent: list[dict[str, Any]],
    summary: dict[str, Any],
    graph: _Graph,
) -> TraceResult:
    cannot, not_applicable = limits
    out = TraceResult(
        root=dict(root),
        answer=answer,
        places=places,
        influential_nothing_unusual=_clean(influential),
        checked_nothing_found=sorted(nothing_found),
        cannot_show=sorted(cannot),
        not_applicable=sorted(not_applicable),
        absent=_clean(absent),
        summary=_clean(summary),
        nodes=[_clean_node(n) for n in graph.listed()],
        facts={},
    )
    return _finish(ctx, out)


def _finish(ctx: TraceContext, out: TraceResult) -> TraceResult:
    out.facts = _facts(out)
    out._ctx = ctx
    return out


def _clean_node(node: TraceNode) -> TraceNode:
    node.influence_log2 = _num(node.influence_log2)
    node.influence_ci_share = _num(node.influence_ci_share)
    node.z = _num(node.z)
    return node


def _num(value: Any) -> float | None:
    """A float rounded to ten places, or ``None`` for NaN, infinity or ``None``."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return round(f, 10)


def _clean(obj: Any) -> Any:
    """JSON-stable plain data: numpy scalars to Python, floats rounded, NaN to ``None``."""
    if isinstance(obj, Mapping):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple | set | frozenset):
        items = sorted(obj) if isinstance(obj, set | frozenset) else obj
        return [_clean(v) for v in items]
    if isinstance(obj, bool | np.bool_):
        return bool(obj)
    if isinstance(obj, int | np.integer):
        return int(obj)
    if isinstance(obj, float | np.floating):
        return _num(obj)
    if isinstance(obj, np.str_):
        return str(obj)
    return obj


FOLD_FMT = "{:.3g}"
TIMES = "×"
COUNT_FMT = "{:,}"
P_FMT = "{:.2g}"
LOG2_FMT = "{:.3f}"
SIGNED_FMT = "{:+.3f}"
CQ_FMT = "{:.1f}"
Z_FMT = "{:.1f}"


class _FactBook:
    """Registers the facts of one trace under ``f_trace_<root>_...``; skips empty values."""

    def __init__(self, root_slug: str, path: str) -> None:
        self.reg = FactRegistry()
        self.prefix = f"f_trace_{root_slug}"
        self.path = path

    def add(self, name: str, value: Any, fmt: str = "{}", unit: str = "", path: str = "") -> None:
        if value is None or isinstance(value, bool):
            return
        if isinstance(value, str):
            if not value:
                return
        else:
            value = _num(value) if isinstance(value, float) else value
            if value is None:
                return
        self.reg.add(
            Fact(
                id=f"{self.prefix}_{name}",
                value=value,
                fmt=fmt,
                unit=unit,
                path=f"{self.path}.{path or name}",
            )
        )


def _facts(result: TraceResult) -> dict[str, Fact]:
    """Every number (and every address with digits) the result shows, as a fact."""
    root = result.root
    book = _FactBook(_root_slug(root), f"trace.{root['kind']}.{root['id']}")
    s = result.summary
    book.add("root_kind", root["kind"], path="root.kind")
    book.add("answer", result.answer, path="answer")
    book.add("nothing_found", " ".join(result.checked_nothing_found), path="checked_nothing_found")
    clean = [c.split(":", 1)[1] for c in result.checked_nothing_found if c.startswith("S6:")]
    book.add("clean_ntc_plates", ", ".join(clean), path="checked_nothing_found")
    book.add("n_clean_ntc_plates", len(clean), COUNT_FMT, path="checked_nothing_found")
    for name, fmt, unit in (
        ("log2fc", SIGNED_FMT, ""),
        ("fc", FOLD_FMT, TIMES),
        ("fold", FOLD_FMT, ""),
        ("p", P_FMT, ""),
        ("p_adjusted", P_FMT, ""),
        ("half_ci_log2", LOG2_FMT, ""),
        ("distance_to_line_log2", LOG2_FMT, ""),
        ("max_single_effect_log2", SIGNED_FMT, ""),
        ("max_single_effect_fold", FOLD_FMT, TIMES),
        ("max_loo_effect_log2", SIGNED_FMT, ""),
        ("cq", CQ_FMT, ""),
    ):
        value = s.get(name)
        if isinstance(value, int | float) and not isinstance(value, bool):
            book.add(name, float(value), fmt, unit, path=f"summary.{name}")
    if isinstance(s.get("distance_to_line_log2"), float):
        distance = abs(s["distance_to_line_log2"])
        book.add("distance_abs_log2", distance, LOG2_FMT, path="summary.distance_to_line_log2")
        book.add("distance_fold", 2**distance, FOLD_FMT, TIMES, path="summary")
    if isinstance(s.get("correction"), str):
        book.add("correction", s["correction"], path="summary.correction")
    for name in (
        "n_loo_flips",
        "n_places",
        "n_shown",
        "n_more",
        "n_absent_study",
        "n_absent_gene",
        "n_restorable",
        "n_hi",
        "n_lo",
        "n_genes",
        "n_values",
        "feeds",
        "n_reasons",
        "n_study_wells_in_window",
        "n_compared_wells_in_window",
    ):
        if isinstance(s.get(name), int) and not isinstance(s.get(name), bool):
            book.add(name, s[name], COUNT_FMT, path=f"summary.{name}")
    for name in ("call", "direction", "max_single_effect_sample", "max_loo_gene", "group"):
        if isinstance(s.get(name), str):
            book.add(name, s[name], path=f"summary.{name}")
    for name in ("sample", "plate", "well", "target", "role", "sample_type", "well_key", "limit"):
        if isinstance(s.get(name), str):
            book.add(name, s[name], path=f"summary.{name}")
    book.add("choice_flips", " ".join(s.get("choice_flips") or []), path="summary.choice_flips")
    labels = s.get("group_labels") or []
    if len(labels) == 2:
        book.add("group_hi", labels[0], path="summary.group_labels[0]")
        book.add("group_lo", labels[1], path="summary.group_labels[1]")
    rule = s.get("rule") or {}
    if rule:
        book.add("rule_fold", float(rule["min_fold"]), "{:g}", path="summary.rule.min_fold")
        book.add("rule_alpha", float(rule["alpha"]), "{:g}", path="summary.rule.alpha")
    for cls, n in (s.get("n_places_by_class") or {}).items():
        book.add(f"n_places_{cls}", n, COUNT_FMT, path=f"summary.n_places_by_class.{cls}")
    for cls, n in (s.get("n_more_by_class") or {}).items():
        book.add(f"n_more_{cls}", n, COUNT_FMT, path=f"summary.n_more_by_class.{cls}")
    for key in ("set_aside", "read_from_other_refs", "restore", "restore_all"):
        view = s.get(key)
        if isinstance(view, Mapping):
            book.add(f"{key}_class", view.get("class"), path=f"summary.{key}.class")
            book.add(f"{key}_n_changed", view.get("n_changed"), COUNT_FMT, path=f"summary.{key}")
            book.add(f"{key}_changed_calls", ", ".join(view.get("changed_calls") or []), path=key)
            book.add(f"{key}_group", view.get("group"), path=f"summary.{key}.group")
            book.add(f"{key}_n_samples", view.get("n_samples"), COUNT_FMT, path=key)
    for n, p in enumerate(result.places, start=1):
        _place_facts(book, p, n, root)
    for n, item in enumerate(result.influential_nothing_unusual, start=1):
        base = f"infl_{n}"
        book.add(f"{base}_sample", item.get("sample"), path=f"influential[{n - 1}].sample")
        book.add(f"{base}_gene", item.get("gene"), path=f"influential[{n - 1}].gene")
        book.add(f"{base}_delta_log2", item.get("delta_log2"), SIGNED_FMT, path=f"infl.{n}")
        book.add(f"{base}_fold", item.get("fold"), FOLD_FMT, TIMES, path=f"infl.{n}")
        book.add(f"{base}_consequence", item.get("consequence"), path=f"infl.{n}")
    absent = result.absent if root["kind"] != "gene" else []  # a gene panel shows the count
    for n, entry in enumerate(absent, start=1):
        base = f"absent_{n}"
        book.add(f"{base}_sample", entry["sample"], path=f"absent[{n - 1}].sample")
        book.add(f"{base}_scope", entry.get("scope"), path=f"absent[{n - 1}].scope")
        for m, reason in enumerate(entry.get("reasons", []), start=1):
            rb = f"{base}_{m}"
            book.add(f"{rb}_reason", reason.get("reason"), path=f"absent.{n}.{m}")
            book.add(f"{rb}_target", reason.get("target"), path=f"absent.{n}.{m}")
            book.add(f"{rb}_plate", reason.get("plate"), path=f"absent.{n}.{m}")
            book.add(f"{rb}_well", reason.get("well"), path=f"absent.{n}.{m}")
            codes = [c for c in reason.get("note_codes") or [] if c == "no_amplification"]
            book.add(f"{rb}_note", " ".join(codes), path=f"absent.{n}.{m}.note_codes")
            if reason.get("left_out"):  # a person left the well out of the analysis
                book.add(f"{rb}_left_out", "left out", path=f"absent.{n}.{m}.left_out")
        restore = entry.get("restore") or {}
        book.add(f"{base}_restore_class", restore.get("class"), path=f"absent.{n}.restore")
        book.add(f"{base}_restore_group", restore.get("group"), path=f"absent.{n}.restore")
    return book.reg.as_dict()


def _place_facts(book: _FactBook, p: PlaceToLook, n: int, root: Mapping[str, str]) -> None:
    at = f"places[{n - 1}]"
    book.add(f"{n}_rank", p.rank, COUNT_FMT, path=f"{at}.rank")
    book.add(f"{n}_sample", p.sample, path=f"{at}.sample")
    book.add(f"{n}_plate", p.plate, path=f"{at}.plate")
    book.add(f"{n}_well", p.well, path=f"{at}.well")
    book.add(f"{n}_target", p.target, path=f"{at}.target")
    book.add(f"{n}_role", p.role, path=f"{at}.role")
    book.add(f"{n}_checks", " ".join(p.checks), path=f"{at}.checks")
    book.add(f"{n}_cq", p.cq, CQ_FMT, path=f"{at}.cq")
    book.add(f"{n}_z", p.z, Z_FMT, path=f"{at}.z")
    book.add(f"{n}_abs_z", abs(p.z) if p.z is not None else None, Z_FMT, path=f"{at}.z")
    book.add(f"{n}_pull_log2", p.pull_log2, "{:+.2f}", path=f"{at}.pull_log2")
    book.add(f"{n}_fold_off", p.fold_off, FOLD_FMT, TIMES, path=f"{at}.fold_off")
    book.add(f"{n}_values_read", p.values_read, path=f"{at}.values_read")
    book.add(f"{n}_feeds", p.feeds, COUNT_FMT, path=f"{at}.feeds")
    book.add(f"{n}_consequence", p.consequence, path=f"{at}.consequence")
    book.add(f"{n}_effect_log2", p.effect_log2, LOG2_FMT, path=f"{at}.effect_log2")
    book.add(f"{n}_effect_fold", 2**p.effect_log2, FOLD_FMT, TIMES, path=f"{at}.effect_log2")
    book.add(f"{n}_via", p.via, path=f"{at}.via")
    best = p.options.get(p.via, {})
    book.add(f"{n}_n_changed", best.get("n_changed"), COUNT_FMT, path=f"{at}.options")
    book.add(f"{n}_changed_calls", ", ".join(best.get("changed_calls") or []), path=at)
    book.add(f"{n}_new_call", best.get("new_call"), path=f"{at}.options.{p.via}.new_call")
    book.add(f"{n}_new_log2fc", best.get("new_log2fc"), SIGNED_FMT, path=f"{at}.options")
    for option, view in sorted(p.options.items()):
        if option == "keep":
            continue
        book.add(f"{n}_{option}_class", view.get("class"), path=f"{at}.options.{option}")
        book.add(f"{n}_{option}_new_call", view.get("new_call"), path=f"{at}.options.{option}")
        book.add(f"{n}_{option}_changed_calls", ", ".join(view.get("changed_calls") or []), path=at)
    ctx = p.plate_context
    book.add(f"{n}_std_copies", ctx.get("lowest_standard_copies"), "{:g}", path=f"{at}.plate")
    book.add(f"{n}_std_cq", ctx.get("lowest_standard_cq"), CQ_FMT, path=f"{at}.plate")
    book.add(f"{n}_plate_median_cq", ctx.get("study_median_cq"), CQ_FMT, path=f"{at}.plate")
    book.add(f"{n}_cq_rank", ctx.get("cq_rank_latest"), COUNT_FMT, path=f"{at}.plate")
    book.add(f"{n}_n_plate_cq", ctx.get("n_study_wells_with_cq"), COUNT_FMT, path=f"{at}.plate")
    book.add(f"{n}_plate_ntc_amplified", ctx.get("n_ntc_amplified"), COUNT_FMT, path=at)
    s1 = p.detail.get("S1") or {}
    book.add(f"{n}_n_other_refs", s1.get("n_other_refs"), COUNT_FMT, path=f"{at}.detail.S1")
    book.add(f"{n}_other_refs_max_z", s1.get("other_refs_max_abs_z"), Z_FMT, path=at)
    book.add(f"{n}_dev_log2", s1.get("dev_log2"), "{:+.2f}", path=f"{at}.detail.S1")
    s2 = p.detail.get("S2") or {}
    book.add(f"{n}_cq_shift", s2.get("median_cq_shift_cycles"), CQ_FMT, path=f"{at}.detail")
    book.add(f"{n}_n_empty_wells", s2.get("n_empty_wells"), COUNT_FMT, path=f"{at}.detail")
    s4 = p.detail.get("S4") or {}
    book.add(f"{n}_eff_shift", s4.get("median_efficiency_shift"), "{:+.3f}", path=at)
    s6 = p.detail.get("S6") or {}
    book.add(f"{n}_ntc_cq", s6.get("ntc_cq"), CQ_FMT, path=f"{at}.detail.S6")
    book.add(f"{n}_ntc_well", s6.get("ntc_well"), path=f"{at}.detail.S6")
    book.add(f"{n}_ntc_gap", s6.get("gap_cycles"), CQ_FMT, path=f"{at}.detail.S6")


# =============================================================================================
# The card, the exclusion effect, the store entry
# =============================================================================================


def _card_id(place: PlaceToLook) -> str:
    where = f"{place.plate} {place.well}" if place.well else "tube"
    return f"card_trace_{slug(f'{place.sample} {where}')}"


def _card(ctx: TraceContext, place: PlaceToLook) -> DecisionCard:
    unit = place.sample
    i = ctx.unit_row[unit]
    keys: list[tuple[str, str, tuple | None]] = [("keep", "Keep (no change)", None)]
    if place.role == "reference_well" and place.target in ctx.refs:
        r = ctx.refs.index(place.target)
        keys.append(
            (
                "read_from_other_refs",
                "Read this well from the sample's other reference wells",
                ("ref", i, r),
            )
        )
    if place.role == "target_well" and place.target in ctx.item_col:
        keys.append(
            (
                "set_aside_value",
                "Set this well's value aside",
                ("value", i, ctx.item_col[place.target]),
            )
        )
    keys.append(("set_aside", "Set the sample aside (every comparison)", ("drop", i)))
    keep = ctx.space.evaluate(ctx.cell or ctx.space.primary)
    options = []
    changed: set[str] = set()
    max_delta = 0.0
    by_option: dict[str, dict[str, Any]] = {}
    for oid, label, key in keys:
        per_gene = keep if key is None else _exact(ctx, key).results()
        options.append(CardOption(id=oid, label=label, per_gene=per_gene))
        if key is None:
            continue
        cons = classify(ctx.baseline, _option(ctx, _exact(ctx, key)), None)
        changed.update(cons.changed_calls)
        max_delta = max(max_delta, cons.max_abs_delta)
        by_option[oid] = _cons_view(cons)
    impact = {
        "flips": bool(changed),
        "n_genes_flipped": len(changed),
        "max_delta_log2fc": _num(max_delta) or 0.0,
        "flips_anywhere": bool(changed),
        "n_genes_flipped_anywhere": len(changed),
        "flipped_genes": sorted(changed),
        "by_option": _clean(by_option),
    }
    evidence = _clean(
        {
            "sample": unit,
            "plate": place.plate,
            "well": place.well,
            "target": place.target,
            "role": place.role,
            "checks": _intrinsic_checks(ctx, place),
            "z": place.z,
            "pull_log2": place.pull_log2,
            "fold_off": place.fold_off,
            "values_read": place.values_read,
            "feeds": place.feeds,
            "cq": place.cq,
            "what_to_check": [CHECKS[c]["what_to_check"] for c in _intrinsic_checks(ctx, place)],
            "groups": "held fixed",
        }
    )
    data = {
        "id": _card_id(place),
        "kind": CARD_KIND,
        "rank": 0,
        "impact": impact,
        "evidence": evidence,
        "options": options,
        "recommended": "keep",
        "rationale_template": CARD_TEMPLATE,
        "facts": [],
        "autonomy": "suggest",
        "effective_autonomy": "suggest",
        "status": "open",
    }
    return DecisionCard(**data)  # CARD_KIND is registered in core/card_kinds.py


# ---- a person's decision applied: the wells an option leaves out of the analysis ------------

#: The options of a place that leave wells out of the analysis (a Studio session applies them as
#: ``curve.exclude_well``). ``read_from_other_refs`` is a what-if only: the analysis never reads
#: one well from other wells, it keeps a well or leaves it out.
SET_ASIDE_OPTIONS: tuple[str, ...] = ("set_aside_value", "set_aside")
#: The options a person can apply from Trace: keep (put back) and the set-asides.
APPLIED_OPTIONS: tuple[str, ...] = ("keep", *SET_ASIDE_OPTIONS)


def _study_wells_of(ctx: TraceContext, unit: str, target: str | None = None) -> list[str]:
    """Every study well (``RUN/WELL``) of a unit, or of one unit x target, left out or not."""
    w = ctx.wells
    mask = (w["sample_type"] == "unkn") & (w["unit"] == unit)
    if target is not None:
        mask &= w["target"] == target
    return sorted(str(k) for k in w.index[mask.to_numpy()])


def option_wells(ctx: TraceContext, place: PlaceToLook, option: str) -> tuple[str, ...] | None:
    """The wells (``RUN/WELL`` keys) an option at a place leaves out of the analysis.

    ``keep`` leaves none out; ``set_aside_value`` (a target well) leaves out every well behind
    that value (the well and its technical replicates, on every plate); ``set_aside`` leaves out
    every study well of the sample (every gene, every plate), so it is in no comparison. Wells
    already left out are listed too (the caller compares with the design). ``None`` for an
    option that is not a set-aside (``read_from_other_refs``) or that the place does not have.

    Leaving out every well of a reference gene of a sample takes the sample out of every
    comparison (its normaliser needs every reference); that is ``set_aside``.
    """
    if option == "keep":
        return ()
    if option not in SET_ASIDE_OPTIONS or option not in place.options:
        return None
    if option == "set_aside_value":
        if place.target is None:
            return None
        return tuple(_study_wells_of(ctx, place.sample, place.target))
    return tuple(_study_wells_of(ctx, place.sample))


def place_wells(ctx: TraceContext, place: PlaceToLook) -> tuple[str, ...]:
    """The wells the place itself is: its well and replicates (a tube place: every well)."""
    if place.role == "sample" or place.target is None:
        return tuple(_study_wells_of(ctx, place.sample))
    return tuple(_study_wells_of(ctx, place.sample, place.target))


def restore_effect(ctx: TraceContext, unit: str) -> dict[str, Any] | None:
    """What bringing back a sample in no comparison would do, or ``None`` when it cannot be.

    Its one empty reference well is read from the sample's other references, groups fixed. The
    consequence view: ``class``, ``changed_calls``, ``max_abs_delta``.
    """
    if unit not in ctx.restorable:
        return None
    return _cons_view(_consequence(ctx, ("restore", ctx.unit_row[unit]), None))


def cell_effect(ctx: TraceContext, unit: str, target: str) -> dict[str, Any] | None:
    """What leaving one sample x gene value out does to the calls (exact, groups fixed).

    A target gene's value left out; a reference gene's value left out takes the sample out of
    every comparison (its normaliser needs every reference). A sample in no comparison changes
    nothing. ``None`` for a gene the comparison does not use that way (the marker, say). The
    consequence view: ``class``, ``changed_calls``, ``max_abs_delta``.
    """
    i = ctx.unit_row.get(unit)
    if i is None or not ctx.used[i]:
        return _cons_view(NOTHING)
    if target in ctx.item_col:
        key: tuple = ("value", i, ctx.item_col[target])
    elif target in ctx.refs:
        key = ("drop", i)
    else:
        return None
    return _cons_view(_consequence(ctx, key, None))


def place_universe(ctx: TraceContext, place: PlaceToLook) -> tuple[str, ...]:
    """Every well any set-aside option of the place leaves out (what "keep" can put back)."""
    found: set[str] = set()
    for option in SET_ASIDE_OPTIONS:
        found.update(option_wells(ctx, place, option) or ())
    return tuple(sorted(found))


def _intrinsic_checks(ctx: TraceContext, place: PlaceToLook) -> list[str]:
    """Checks of the place itself (its well, and the sample's tube checks for a tube place)."""
    unit = place.sample
    found: set[str] = set()
    if place.role == "sample":
        found.update(ctx.row_tube[ctx.unit_row[unit]])
    if place.role == "reference_well" and place.target in ctx.refs:
        found.update(_ref_checks(ctx, ctx.unit_row[unit], ctx.refs.index(place.target)))
    if place.role == "target_well" and place.target is not None:
        found.update(ctx.cell_checks.get((unit, place.target), ()))
    return sorted(found)


def baseline(ctx: TraceContext) -> dict[str, Baseline]:
    """Every compared gene's baseline (log2fc, call, CI half-width), for ``classify``."""
    return dict(ctx.baseline)


def exclusion_effect(
    ctx: TraceContext,
    *,
    drop_samples: Iterable[str] = (),
    impute: Iterable[str] = (),
) -> dict[str, tuple[float, str]]:
    """Every gene's ``(log2fc, call)`` with samples set aside and wells read another way.

    Groups are held fixed. ``drop_samples`` are sample (or unit) names taken out of every
    comparison. ``impute`` are well keys (``RUN/WELL`` or ``RUN:WELL``): a reference well is
    read from its sample's remaining references (each reference's usual offset to those,
    measured over the compared samples); a target well has nothing to be read from, so its
    value is left out; a sample whose every reference is imputed is set aside. Wells that feed
    no value (controls, standards, samples in no comparison, the marker, excluded wells)
    change nothing. Pass the result to :func:`qpilot.core.consequence.classify` with
    :func:`baseline` for "changes k of N conclusions".

    Raises:
        TraceError: A sample or well the study does not have.
    """
    hi, lo = ctx.in_hi.copy(), ctx.in_lo.copy()
    values, refs = ctx.values.copy(), ctx.ref_values.copy()
    for name in drop_samples:
        unit = _resolve_unit(ctx, str(name))
        i = ctx.unit_row.get(unit)
        if i is not None:
            hi[i] = lo[i] = False
    by_unit: dict[int, set[int]] = {}
    for well_key in impute:
        run, label = parse_well(str(well_key))
        key = f"{run}/{label}"
        if key not in ctx.wells.index:
            raise TraceError(f"no well {label} on plate {run}")
        row = _row(ctx, key)
        if row["sample_type"] != "unkn" or bool(row["person_excluded"]):
            continue
        i = ctx.unit_row.get(str(row["unit"]))
        if i is None or not ctx.used[i]:
            continue
        target = str(row["target"])
        if target in ctx.refs:
            by_unit.setdefault(i, set()).add(ctx.refs.index(target))
        elif target in ctx.item_col:
            values[i, ctx.item_col[target]] = np.nan
    for i, cols in sorted(by_unit.items()):
        keep = [r for r in range(len(ctx.refs)) if r not in cols]
        if not keep:
            hi[i] = lo[i] = False
            continue
        if len(cols) == 1:  # the S1 expected value, exactly as the card's option reads it
            (r,) = cols
            refs[i, r] = ctx.s1_expected[i, r]
            continue
        for r in sorted(cols):
            refs[i, r] = ctx.ref_values[i, keep].mean() + _subset_offset(ctx, r, tuple(keep))
    out = ctx.space.evaluate_arrays(values, refs, hi, lo, capped=ctx.capped)
    return _option(ctx, out)


def _subset_offset(ctx: TraceContext, r: int, keep: tuple[int, ...]) -> float:
    """Median over the compared samples of ``L[r] - mean(L[keep])``."""
    ck = ("offset", r, keep)
    if ck not in ctx._cache:
        block = ctx.ref_values[ctx.used]
        ctx._cache[ck] = float(np.median(block[:, r] - block[:, list(keep)].mean(axis=1)))
    return ctx._cache[ck]


def trace_store(
    store: StudyStore,
    study_id: str,
    *,
    gene: str | None = None,
    sample: str | None = None,
    well: str | None = None,
    top: int = 3,
    comparison: str | None = None,
) -> TraceResult:
    """Trace a stored study, read-only: exactly one of ``gene``, ``sample`` or ``well``.

    ``comparison``: a study with several comparisons, the one traced (its id; the first).

    The settings come from the study's confirmed design (the demo settings without one), the
    per-well table from the curve cache (nothing is written when it is absent) and the model
    from :func:`qpilot.qpcr.study.build_model`; the re-analysis must reproduce the stored
    results. The workspace is never written.

    Raises:
        TraceError: Not exactly one root, the input file unknown or changed, a re-analysis
            that does not reproduce the stored results, or an unknown gene, sample or well.
        qpilot.core.store.StudyNotFound: Unknown study.
    """
    given = [(k, v) for k, v in (("gene", gene), ("sample", sample), ("well", well)) if v]
    if len(given) != 1 or not isinstance(given[0][1], str):
        raise TraceError("give exactly one of gene, sample or well (PLATE:WELL)")
    _check_top(top)
    ctx = _store_context(store, study_id, comparison=comparison)
    kind, value = given[0]
    if kind == "gene":
        return trace_gene(ctx, value, top=top)
    if kind == "sample":
        return trace_sample(ctx, value, top=top)
    return trace_well(ctx, value, top=top)


def _store_context(
    store: StudyStore,
    study_id: str,
    choice: Mapping[str, str] | None = None,
    comparison: str | None = None,
) -> TraceContext:
    """Trace's context for a stored study: the planned analysis, or the one ``choice`` names.

    ``choice``: the options in use as the robustness grid writes them
    (:func:`qpilot.trace.context.cell_of`).
    """
    from qpilot.core.store import sha256_file
    from qpilot.io.datasets import default_cache_dir
    from qpilot.qpcr.curves import analyse_study, cache_path
    from qpilot.qpcr.study import StudySettings, build_model

    result = store.get(study_id)
    path = store.source(study_id)
    if path is None:
        raise TraceError("the study's input file is not known or has changed")
    if sha256_file(path) != result.input_sha256:
        raise TraceError("this file is not the input of this study (sha256 differs)")
    design = store.design(study_id)
    settings = StudySettings.from_design(design) if design is not None else StudySettings()
    cached = cache_path(
        result.input_sha256,
        settings.experiment_id,
        settings.candidates,
        settings.curves,
        default_cache_dir(),
    ).exists()
    curves = analyse_study(
        path, settings.experiment_id, settings.candidates, settings.curves, use_cache=cached
    )
    model = build_model(curves, settings)
    primary = model.space.evaluate(model.space.primary)
    stored = result.contrasts
    if set(primary) != set(stored) or any(
        (primary[g].fc, primary[g].p) != (stored[g].fc, stored[g].p) for g in primary
    ):
        raise TraceError("a re-analysis does not reproduce the stored results; nothing traced")
    robust = result.robustness
    found = result.comparisons
    if comparison:
        if found is None or comparison not in {o.id for o in found.comparisons}:
            raise TraceError(f"this study has no comparison {comparison!r}")
        robust = next(o.robustness for o in found.comparisons if o.id == comparison)
    if choice:
        from qpilot.trace.context import cell_of

        cell = cell_of(model, choice)
        return build_context(curves, model, robustness=robust, cell=cell, comparison=comparison)
    return build_context(curves, model, robustness=robust, comparison=comparison)


def trace_all_genes(ctx: TraceContext, *, top: int = 3) -> dict[str, TraceResult]:
    """:func:`trace_gene` for every compared gene (for the planted-fault benchmark)."""
    return {gene: trace_gene(ctx, gene, top=top) for gene in ctx.items}


__all__: Sequence[str] = (
    "CANNOT_SHOW",
    "CHECKS",
    "METHOD_CARD",
    "TRACE_THRESHOLDS",
    "PlaceToLook",
    "TraceContext",
    "TraceError",
    "TraceNode",
    "TraceResult",
    "baseline",
    "build_context",
    "exclusion_effect",
    "parse_well",
    "robust_z",
    "trace_all_genes",
    "trace_gene",
    "trace_sample",
    "trace_store",
    "trace_well",
)
