"""What the Prism bridge needs from the engine: log2 relative quantities per biological unit.

:func:`sample_table` turns the per-well table (or the samples x genes ``log2(n0)`` matrix) into
one row per biological unit and gene (the *column* layout) or one row per technical replicate
(the *nested* layout), with the engine's own arithmetic: ``log2(target) - mean(log2(refs))``,
which is :func:`qpilot.qpcr.quant.relative`. When every unit has one well per gene (the demo),
the values *are* ``relative()``'s output, bit for bit.

With technical replicates (several wells of one sample and gene, or several samples in one
biological unit):

* the unit-level matrix is the engine's own, :func:`qpilot.qpcr.quant.log2_matrix` with the
  design's units: per unit and gene the mean ``log2(n0)`` of the wells that have a quantity
  (undetermined only when every replicate is), then the undetermined rule at unit level, as in
  the engine (an excluded value is left out and never capped);
* the column layout holds one value per unit: ``relative()`` on that matrix, so it equals the
  engine's value bit for bit;
* the nested layout holds one value per well that has a quantity: the well's ``log2(n0)``
  minus the unit's reference mean, so the replicates of a unit average to its column-layout
  value (a unit whose wells are all undetermined, under ``cap``, has one row: its capped
  value). A unit's replicates are numbered 1, 2, ... by sample, then well key
  (``"<run_id>/<well>"``); ``sample_table(..., wells=True)`` adds the well behind each row
  (:data:`WELL_COLUMN`), and :func:`replicate_wells` maps a replicate number back to its well.

Technical replicates are never rows of the column layout, so Prism never counts them as n.

:func:`demo_inputs` rebuilds, read-only, everything the bridge needs for a study that is
already in the store: the per-well table from the curve cache, the groups exactly as
:meth:`qpilot.qpcr.space.QpcrSpace.groups` gives them, and every card's decided option mapped
back to its dimension value with the same option specs ``qpcr/study.py`` builds the cards from.

:class:`Reanalysis` answers the round trip's question "what does leaving this value out do?"
by running the engine again on the study's design with the exclusion applied, the way accepting
it applies it, so the numbers a person approves are the numbers the engine then reports. A
replicate of the nested layout is excluded by its exact well, the one behind that row of the
exported table, so the engine leaves out the well the person cleared whatever the
amplification rule of the export and whatever was excluded since.

Integration point for any confirmed design (``qpcr/designs.py``, ``StudyDesign``): the bridge
takes only plain mappings (``groups``: sample -> group, ``units``: sample -> biological unit,
``group_order``, ``refs``, ``undetermined``), so ``designs.py`` can build an
:class:`ExportInputs` from a ``StudyDesign`` without any change here; ``demo_inputs`` is the
``vermeulen_expression_defined`` preset of that.
"""

from __future__ import annotations

import math
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
import pandas as pd

from qpilot.core.store import ON_DEMAND_KINDS
from qpilot.qpcr.contrast import DEFAULT_RULE, ConclusionRule, conclude, welch
from qpilot.qpcr.quant import EXCLUDED, Undetermined, excluded_cells, log2_matrix, relative
from qpilot.schemas import ContrastResult, DecisionCard, StudyResult

if TYPE_CHECKING:
    from qpilot.core.store import StudyStore
    from qpilot.qpcr.study import StudyModel
    from qpilot.schemas_studio import Proposal, StudyDesign

TABLE_COLUMNS: tuple[str, ...] = (
    "gene",
    "group",
    "biological_unit",
    "sample",
    "well_rep",
    "log2_rq",
)
WELL_COLUMN = "well"  # with ``wells=True``: the well key behind a row ("" for a unit's value)
Layout = Literal["column", "nested"]
UNIT_ROW = 0  # ``well_rep`` of a column-layout row: the unit's value, not one well
SAFE_LABEL = re.compile(r"^[\w()\-. ]{1,64}\Z")  # the rule of ``curves.safe_name``
DEMO_DESIGN_ID = "vermeulen_expression_defined"
EXCLUSION_KIND = "prism.exclusion_reason"
WITHHELD = "withheld"  # an excluded gene's conclusion when the engine then withholds the gene
_CURVE_COLUMNS = {"sample", "sample_type", "target", "n0"}

#: ``(gene, biological unit, well_rep)`` or ``(gene, unit, well_rep, well)``: well_rep 0 is the
#: whole unit; a replicate (well_rep > 0) is its exact ``well`` (found by :class:`Reanalysis`
#: from the exported numbering when it is not given).
Exclusion = tuple[str, str, int] | tuple[str, str, int, str | None]
Results = tuple[dict[str, ContrastResult], dict[str, str]]  # compared genes, withheld genes
Replicates = dict[tuple[str, str, int], tuple[str, float]]  # (gene, unit, rep) -> (well, value)


class ExportError(ValueError):
    """The study cannot be turned into tables for Prism (the message says why)."""


@dataclass(frozen=True)
class Choice:
    """One analysis choice the exported values were computed at, and who made it."""

    card_id: str
    dimension: str
    option: str
    recommended: str
    value: Any
    actor: str | None  # "human", "agent", "system", or None when nobody decided yet
    status: str  # the card's status: decided, auto_decided, open, pending_human

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form (tuples become lists)."""
        value = list(self.value) if isinstance(self.value, tuple) else self.value
        return {
            "card_id": self.card_id,
            "dimension": self.dimension,
            "option": self.option,
            "recommended": self.recommended,
            "value": value,
            "actor": self.actor,
            "status": self.status,
        }


@dataclass(frozen=True, eq=False)
class ExportInputs:
    """Everything the Prism bridge needs from one study, as plain values and mappings.

    ``data`` is the per-well table (or a samples x genes ``log2(n0)`` matrix); ``groups`` maps
    each sample in the comparison to its group label; ``group_order`` is the contrast's order
    (``log2fc = mean(group_order[0]) - mean(group_order[1])``); ``units`` maps samples to
    biological units (``None``: every sample is its own unit). ``design`` (the confirmed
    design the study was analysed with) and ``curves`` (the curve analysis's per-well table,
    before the design is applied) let :class:`Reanalysis` run the engine again; without them
    no consequence is computed.
    """

    study_id: str
    input_sha256: str
    data: pd.DataFrame
    refs: tuple[str, ...]
    undetermined: Undetermined
    groups: Mapping[str, str]
    group_order: tuple[str, ...]
    units: Mapping[str, str] | None = None
    genes: tuple[str, ...] = ()
    headline: tuple[str, ...] = ()
    rule: ConclusionRule = DEFAULT_RULE
    choices: tuple[Choice, ...] = ()
    design_hash: str = ""
    design_note: str = ""
    chain_head: str = ""
    result: StudyResult | None = None
    at_primary: bool = True
    design: StudyDesign | None = None
    curves: pd.DataFrame | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def table(
        self, layout: Layout = "column", genes: Sequence[str] | None = None, *, wells: bool = False
    ) -> pd.DataFrame:
        """:func:`sample_table` for these inputs."""
        return sample_table(
            self.data,
            refs=self.refs,
            undetermined=self.undetermined,
            groups=self.groups,
            units=self.units,
            group_order=self.group_order,
            layout=layout,
            genes=list(genes) if genes is not None else (list(self.genes) or None),
            wells=wells,
        )

    def all_units(self) -> list[str]:
        """Every biological unit in the comparison, sorted."""
        units = self.units or {}
        return sorted({units.get(sample, sample) for sample in self.groups})


# ---------------------------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------------------------


def sample_table(
    matrix_or_curves: pd.DataFrame,
    *,
    refs: Sequence[str],
    undetermined: Undetermined,
    groups: Mapping[str, str],
    units: Mapping[str, str] | None = None,
    group_order: Sequence[str],
    layout: Layout = "column",
    genes: Sequence[str] | None = None,
    wells: bool = False,
) -> pd.DataFrame:
    """Log2 relative quantities per biological unit (column layout) or per replicate (nested).

    Args:
        matrix_or_curves: The per-well table from :func:`qpilot.qpcr.curves.analyse_study`, or
            a samples x genes ``log2(n0)`` matrix from :func:`qpilot.qpcr.quant.log2_matrix`.
        refs: The reference genes to normalise by.
        undetermined: ``"drop"`` or ``"cap"`` (see the module docstring for replicates).
        groups: Sample -> group label; samples not listed are not in the comparison.
        units: Sample -> biological unit; samples not listed are their own unit.
        group_order: The groups in the design's order; every label in ``groups`` must be here.
        layout: ``"column"``: one row per unit and gene; ``"nested"``: one row per well.
        genes: Genes to include (default: every gene that is not a reference gene).
        wells: Also return :data:`WELL_COLUMN`, the well key (``"<run_id>/<well>"``) behind
            each nested-layout row; ``""`` for a row that is a unit's value (every column-layout
            row, a unit whose replicates are all undetermined) and for a table without wells.

    Returns:
        A DataFrame with :data:`TABLE_COLUMNS` (and :data:`WELL_COLUMN` when asked), sorted by
        gene (in the order given), group (in ``group_order``), unit, sample and replicate.
        ``well_rep`` is 0 for a unit's value (column layout) and 1, 2, ... for its wells
        (nested layout), numbered by sample, then well key.

    Raises:
        ExportError: Unknown genes or groups, unsafe labels, a unit in two groups.
    """
    refs = tuple(refs)
    order = tuple(group_order)
    if not refs:
        raise ExportError("at least one reference gene is required")
    if undetermined not in ("drop", "cap"):
        raise ExportError(f"undetermined must be 'drop' or 'cap', not {undetermined!r}")
    if layout not in ("column", "nested"):
        raise ExportError(f"layout must be 'column' or 'nested', not {layout!r}")
    if not order or len(set(order)) != len(order):
        raise ExportError("group_order must list each group once")
    for label in order:
        check_label(label, "group")
    stray = sorted(set(groups.values()) - set(order))
    if stray:
        raise ExportError(f"groups not in group_order: {stray}")

    well_rows, matrix, excluded = _wells(matrix_or_curves, units)
    known = sorted(set(well_rows["target"]))
    missing_refs = [r for r in refs if r not in known]
    if missing_refs:
        raise ExportError(f"reference genes not in the data: {missing_refs}")
    chosen = list(genes) if genes is not None else [g for g in known if g not in refs]
    unknown_genes = [g for g in chosen if g not in known]
    if unknown_genes:
        raise ExportError(f"genes not in the data: {unknown_genes}")

    in_data = set(well_rows["sample"])
    unit_of = {s: (units or {}).get(s, s) for s in groups if s in in_data}
    group_of_unit: dict[str, str] = {}
    for sample, unit in unit_of.items():
        check_label(unit, "biological unit")
        group = groups[sample]
        if group_of_unit.setdefault(unit, group) != group:
            raise ExportError(f"biological unit {unit!r} has samples in two groups")
    samples_per_unit: dict[str, list[str]] = {}
    for sample, unit in sorted(unit_of.items()):
        samples_per_unit.setdefault(unit, []).append(sample)

    one_to_one = all(len(s) == 1 for s in samples_per_unit.values())
    replicated = well_rows.duplicated(["sample", "target"]).any() or not one_to_one
    if not replicated and excluded is None:
        rows = _single_well_rows(
            matrix, well_rows, chosen, refs, undetermined, unit_of, groups, layout
        )
    else:
        rows = _replicate_rows(
            well_rows,
            matrix,
            excluded,
            chosen,
            refs,
            undetermined,
            groups,
            samples_per_unit,
            layout,
        )
    columns = [*TABLE_COLUMNS, WELL_COLUMN]
    table = pd.DataFrame(rows, columns=columns)
    if not wells:
        table = table.drop(columns=[WELL_COLUMN])
    if table.empty:
        return table
    gene_rank = {gene: i for i, gene in enumerate(chosen)}
    group_rank = {group: i for i, group in enumerate(order)}
    table["_g"] = table["gene"].map(gene_rank)
    table["_o"] = table["group"].map(group_rank)
    table = table.sort_values(
        ["_g", "_o", "biological_unit", "sample", "well_rep"], kind="mergesort"
    )
    table = table.drop(columns=["_g", "_o"]).reset_index(drop=True)
    table["well_rep"] = table["well_rep"].astype(int)
    return table


def check_label(label: str, kind: str) -> str:
    """Return ``label`` if it is a plain name (letters, digits, ``_ - . ( )``, spaces, <= 64)."""
    if not isinstance(label, str) or not SAFE_LABEL.match(label) or label != label.strip():
        raise ExportError(f"unsafe {kind} name {label!r}: use letters, digits, _ - . ( ) spaces")
    return label


def _wells(
    data: pd.DataFrame, units: Mapping[str, str] | None
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame | None]:
    """(long well table, the engine's units x genes matrix, excluded cells or None).

    The long table has ``sample, target, key, well, log2`` for the wells that carry a value (a
    quantity, not excluded); ``key`` orders a unit's replicates and ``well`` is the well key
    (``"<run_id>/<well>"``, ``""`` when the table has no wells). The matrix is
    :func:`qpilot.qpcr.quant.log2_matrix` with these ``units``, so only units measured for
    every gene are kept, exactly as in the engine.
    """
    if _CURVE_COLUMNS <= set(data.columns):
        unknown = data[data["sample_type"] == "unkn"]
        replicated = unknown.duplicated(["sample", "target"]).any() or bool(units)
        excluded_any = EXCLUDED in unknown.columns and bool(unknown[EXCLUDED].any())
        engine_units = units if replicated or excluded_any else None
        matrix = log2_matrix(data, engine_units)
        excluded = excluded_cells(data, engine_units) if replicated or excluded_any else None
        used = unknown["n0"].notna()
        if EXCLUDED in unknown.columns:
            used &= ~unknown[EXCLUDED].astype(bool)
        unknown = unknown[used]
        if {"run_id", "well"} <= set(unknown.columns):
            keys = unknown["run_id"].astype(str) + "/" + unknown["well"].astype(str)
            names = keys
        else:
            keys = pd.Series(range(len(unknown)), index=unknown.index).astype(str)
            names = pd.Series("", index=unknown.index)
        wells = pd.DataFrame(
            {
                "sample": unknown["sample"].astype(str).to_numpy(),
                "target": unknown["target"].astype(str).to_numpy(),
                "key": keys.to_numpy(),
                "well": names.to_numpy(),
                "log2": np.log2(unknown["n0"].to_numpy(dtype=float)),
            }
        )
        return wells, matrix, excluded
    matrix = data.copy()
    matrix.index = matrix.index.astype(str)
    stacked = matrix.stack(future_stack=True).rename("log2").reset_index()
    stacked.columns = ["sample", "target", "log2"]
    stacked["key"] = stacked["sample"]
    stacked["well"] = ""
    columns = ["sample", "target", "key", "well", "log2"]
    return stacked[columns].dropna(subset=["log2"]), matrix, None


def _single_well_rows(
    matrix: pd.DataFrame,
    wells: pd.DataFrame,
    genes: Sequence[str],
    refs: tuple[str, ...],
    undetermined: Undetermined,
    unit_of: Mapping[str, str],
    groups: Mapping[str, str],
    layout: Layout,
) -> list[tuple]:
    """One well per sample and gene: the values are ``relative()``'s output itself."""
    rows = []
    rep = UNIT_ROW if layout == "column" else 1
    well_of: dict[tuple[str, str], str] = {}
    if layout == "nested":
        cells = zip(wells["sample"], wells["target"], wells["well"], strict=True)
        well_of = {(sample, target): well for sample, target, well in cells}
    for gene in genes:
        values = relative(matrix, gene, refs, undetermined)
        for sample, value in values.items():
            if sample in unit_of:
                well = well_of.get((str(sample), gene), "")  # "" for a capped value
                row = (gene, groups[sample], unit_of[sample], str(sample), rep, float(value), well)
                rows.append(row)
    return rows


def _replicate_rows(
    wells: pd.DataFrame,
    matrix: pd.DataFrame,
    excluded: pd.DataFrame | None,
    genes: Sequence[str],
    refs: tuple[str, ...],
    undetermined: Undetermined,
    groups: Mapping[str, str],
    samples_per_unit: Mapping[str, list[str]],
    layout: Layout,
) -> list[tuple]:
    """Technical replicates or exclusions: the engine's unit-level matrix, then ``relative()``."""
    sample_unit = {s: unit for unit, samples in samples_per_unit.items() for s in samples}
    wells = wells[wells["sample"].isin(list(sample_unit))].copy()
    wells["unit"] = wells["sample"].map(sample_unit)
    in_design = [unit for unit in matrix.index if unit in samples_per_unit]
    rows = []
    for gene in genes:
        values = relative(matrix, gene, refs, undetermined)
        if excluded is not None:  # a person's exclusion is left out, never capped
            values = values[~excluded[gene].reindex(values.index).fillna(False).astype(bool)]
        values = values[values.index.isin(in_design)]
        if layout == "column":
            for unit, value in values.items():
                group = groups[samples_per_unit[unit][0]]
                sample = "+".join(samples_per_unit[unit])
                rows.append((gene, group, str(unit), sample, UNIT_ROW, float(value), ""))
            continue
        normaliser = matrix.loc[values.index, list(refs)].mean(axis=1)
        target = wells[(wells["target"] == gene) & wells["unit"].isin(values.index)]
        target = target.sort_values(["unit", "sample", "key"], kind="mergesort")
        measured = set(target["unit"])
        for unit, block in target.groupby("unit", sort=True):
            group = groups[samples_per_unit[unit][0]]
            replicates = zip(block["sample"], block["log2"], block["well"], strict=True)
            for rep, (sample, value, well) in enumerate(replicates, start=1):
                relative_value = float(value - normaliser[unit])
                rows.append((gene, group, str(unit), str(sample), rep, relative_value, str(well)))
        for unit in sorted(set(values.index) - measured):  # every replicate undetermined (cap)
            group = groups[samples_per_unit[unit][0]]
            sample = "+".join(samples_per_unit[unit])
            rows.append((gene, group, str(unit), sample, 1, float(values[unit]), ""))
    return rows


def replicate_wells(inputs: ExportInputs, genes: Sequence[str] | None = None) -> Replicates:
    """The well behind every replicate of the nested layout, as the export numbers them.

    Returns:
        ``(gene, biological unit, well_rep) -> (well key, exported log2 value)`` for every
        nested-layout row of ``genes`` (default: the inputs' genes). The well is ``""`` for a
        row that is the unit's value (every replicate undetermined, capped).
    """
    table = inputs.table("nested", genes, wells=True)
    rows = zip(
        table["gene"],
        table["biological_unit"],
        table["well_rep"],
        table[WELL_COLUMN],
        table["log2_rq"],
        strict=True,
    )
    return {(str(g), str(u), int(r)): (str(w), float(v)) for g, u, r, w, v in rows}


# ---------------------------------------------------------------------------------------------
# Contrasts on the table (the round trip's consequence test)
# ---------------------------------------------------------------------------------------------


def unit_contrasts(
    table: pd.DataFrame,
    group_order: Sequence[str],
    rule: ConclusionRule = DEFAULT_RULE,
    *,
    exclude: Collection[tuple[str, str, int]] = (),
) -> dict[str, ContrastResult]:
    """Welch's t test on log2, one value per biological unit, for every gene in ``table``.

    A unit's value is the mean of its rows (its one value in the column layout, its replicates'
    mean in the nested layout). ``exclude`` lists ``(gene, unit, well_rep)`` to leave out;
    ``well_rep`` 0 leaves the whole unit out for that gene. The result equals
    :func:`qpilot.qpcr.contrast.welch_contrast` on the same values.

    Raises:
        ExportError: Not exactly two groups.
    """
    if len(group_order) != 2:
        raise ExportError("the Welch contrast needs exactly two groups")
    first, second = group_order
    dropped = {(g, u, int(r)) for g, u, r in exclude}
    out = {}
    for gene, block in table.groupby("gene", sort=False):
        if dropped:
            keep = [
                (gene, u, 0) not in dropped and (gene, u, int(r)) not in dropped
                for u, r in zip(block["biological_unit"], block["well_rep"], strict=True)
            ]
            block = block[keep]
        means = block.groupby("biological_unit", sort=True)["log2_rq"].mean()
        group = block.groupby("biological_unit", sort=True)["group"].first()
        a = means[group == first].to_numpy(dtype=float)
        b = means[group == second].to_numpy(dtype=float)
        w = welch(a, b)
        out[str(gene)] = ContrastResult(
            target=str(gene),
            log2fc=w.diff,
            fc=2**w.diff,
            ci=(2 ** (w.diff - w.t_crit * w.se), 2 ** (w.diff + w.t_crit * w.se)),
            p=w.p,
            t=w.t,
            n_hi=len(a),
            n_lo=len(b),
            conclusion=conclude(w.diff, w.p, rule),
        )
    return out


def resolve_replicate(
    replicates: Mapping[tuple[str, str, int], tuple[str, float]],
    gene: str,
    unit: str,
    well_rep: int,
) -> tuple[int, str | None]:
    """``(well_rep, well)`` an exclusion of one exported row is applied with.

    ``replicates`` is :func:`replicate_wells` of the inputs the table was exported from. A
    replicate (``well_rep`` > 0) becomes its exact well; a row that is the unit's value (its
    replicates all undetermined, capped) becomes the whole unit, ``(0, None)``, as does
    ``well_rep`` 0.

    Raises:
        ExportError: The exported table has no such replicate.
    """
    if not well_rep:
        return UNIT_ROW, None
    found = replicates.get((gene, unit, int(well_rep)))
    if found is None:
        raise ExportError(f"{gene}: unit {unit!r} has no replicate {well_rep} in the export")
    well = found[0]
    return (int(well_rep), well) if well else (UNIT_ROW, None)


class Reanalysis:
    """The study analysed again by the engine with exclusions accepted, at the exported choices.

    Each exclusion is applied to the study's design by the function that applies a person's
    acceptance of a ``prism.exclusion_reason`` proposal
    (:func:`qpilot.qpcr.designs.design_from_proposals`, on an in-memory copy: nothing is stored
    and nothing is decided), and the study is rebuilt from the per-well table with
    :func:`qpilot.qpcr.study.build_model`. Everything accepting recomputes is therefore
    recomputed here too: the cap floor (each gene's lowest remaining value), the withheld genes,
    the units each group keeps. ``accepted`` are the ``prism.exclusion_reason`` proposals a
    person already accepted (whether or not the study's design holds them yet); they are part
    of every comparison, "before" included. Results are kept per set of exclusions, so asking
    twice costs one analysis.

    A replicate of the nested layout (``well_rep`` > 0) is excluded by its exact well: the one
    given, else the one behind that row of the nested table these inputs export
    (:func:`resolve_replicate`), never a well counted again on the design as it stands.

    Raises:
        ExportError: The inputs carry no design or per-well table (:func:`study_inputs` gives
            both), or an accepted exclusion cannot be applied to the design.
    """

    def __init__(self, inputs: ExportInputs, accepted: Sequence[Proposal] = ()) -> None:
        from qpilot.qpcr.designs import APPLIED

        if inputs.design is None or inputs.curves is None:
            raise ExportError(
                "the consequence needs the study's design and per-well table; rebuild the "
                "inputs with study_inputs"
            )
        self.inputs = inputs
        self.accepted = [p for p in accepted if p.kind == EXCLUSION_KIND and p.status in APPLIED]
        self._base = self._applied(inputs.design, self.accepted)
        self._results: dict[frozenset[tuple[str, str, int, str]], Results] = {}
        self._replicates: Replicates | None = None

    def _applied(self, design: StudyDesign, proposals: Sequence[Proposal]) -> StudyDesign:
        from qpilot.qpcr.designs import DesignError, design_from_proposals

        if not proposals:
            return design
        try:
            return design_from_proposals(design, proposals, self.inputs.curves)
        except DesignError as err:
            raise ExportError(f"the exclusion cannot be applied: {err}") from err

    def resolve(
        self, gene: str, unit: str, well_rep: int, well: str | None = None
    ) -> tuple[int, str | None]:
        """``(well_rep, well)`` the exclusion is applied with (see :func:`resolve_replicate`)."""
        if well:
            return int(well_rep), str(well)
        if not well_rep:
            return UNIT_ROW, None
        if self._replicates is None:
            self._replicates = replicate_wells(self.inputs)
        return resolve_replicate(self._replicates, gene, unit, well_rep)

    def _key(self, exclusion: Exclusion) -> tuple[str, str, int, str]:
        gene, unit, well_rep, *rest = exclusion
        rep, well = self.resolve(str(gene), str(unit), int(well_rep), rest[0] if rest else None)
        return str(gene), str(unit), rep, well or ""

    def results(self, exclusions: Collection[Exclusion] = ()) -> Results:
        """Every compared gene's result at the exported choices, and the withheld genes."""
        from qpilot.qpcr.study import NGuardError, StudySettings, build_model

        key = frozenset(self._key(e) for e in exclusions)
        if key not in self._results:
            what_if = [_as_accepted(self.inputs.study_id, *e) for e in sorted(key)]
            design = self._applied(self._base, what_if)
            try:
                model = build_model(self.inputs.curves, StudySettings.from_design(design))
            except NGuardError as err:
                raise ExportError(f"the engine cannot compare the groups: {err}") from err
            space = model.space
            self._results[key] = (space.evaluate(_cell(self.inputs, model)), dict(space.withheld))
        return self._results[key]

    def consequence(
        self, gene: str, unit: str, well_rep: int = UNIT_ROW, well: str | None = None
    ) -> dict[str, Any]:
        """What leaving one value out does: see :func:`exclusion_consequence`."""
        before, _ = self.results()
        if gene not in before:
            raise ExportError(f"gene {gene!r} is not in the exported comparison")
        _, _, rep, named = self._key((gene, unit, well_rep, well))
        after = self.results([(gene, unit, rep, named)])
        return {
            "gene": gene,
            "biological_unit": unit,
            "well_rep": rep,
            **({"well": named} if named else {}),
            **_change(gene, before, after),
            **self._summary(before, after),
        }

    def combined(self, exclusions: Sequence[Exclusion]) -> dict[str, Any]:
        """What leaving every one of ``exclusions`` out together does (numbers only).

        Returns:
            The exclusions, each excluded gene's numbers before and after (as in
            :func:`exclusion_consequence`), and how many of all genes' conclusions change.
        """
        before, _ = self.results()
        excluded = [self._key(e) for e in exclusions]
        unknown = sorted({g for g, *_ in excluded} - set(before))
        if unknown:
            raise ExportError(f"genes not in the exported comparison: {unknown}")
        after = self.results(excluded)
        return {
            "exclusions": [
                {"gene": g, "biological_unit": u, "well_rep": r, **({"well": w} if w else {})}
                for g, u, r, w in excluded
            ],
            "genes": {g: _change(g, before, after) for g in dict.fromkeys(g for g, *_ in excluded)},
            **self._summary(before, after),
        }

    def _summary(self, before: dict[str, ContrastResult], after: Results) -> dict[str, Any]:
        compared, _ = after
        genes = sorted(set(before) | set(compared))
        changed = [g for g in genes if _conclusion(before, g) != _conclusion(compared, g)]
        return {
            "n_conclusions_changed": len(changed),
            "n_genes": len(before),
            "changed_genes": changed,
            "rule": self.inputs.rule.as_dict(),
            "basis": {
                "study_id": self.inputs.study_id,
                "chain_head": self.inputs.chain_head,
                "accepted": [p.id for p in self.accepted],
            },
        }


def exclusion_consequence(
    inputs: ExportInputs,
    gene: str,
    unit: str,
    well_rep: int = UNIT_ROW,
    *,
    well: str | None = None,
    accepted: Sequence[Proposal] = (),
) -> dict[str, Any]:
    """What leaving one value out of one gene's comparison does, computed by the engine.

    The study is analysed again with ``unit`` excluded for ``gene`` exactly as accepting the
    exclusion would do it (:class:`Reanalysis`), and every gene's conclusion at the exported
    choices is compared with the analysis without it. ``well_rep`` > 0 leaves out one
    replicate of the nested layout: ``well`` when given, else the well behind that row of the
    nested table these inputs export. Exclusions a person already accepted (``accepted``) are
    in both. A gene the engine then withholds (fewer than two units with a value in a group)
    has no numbers after: its conclusion is ``"withheld"`` and ``withheld_after`` gives the
    engine's reason.

    Returns:
        Numbers only (no prose): fold change, p, units per group and conclusion before and after
        for ``gene`` (``None`` where the engine gives no number), how many of all genes'
        conclusions change, the well left out (``well``, for a replicate), and the basis
        (study, chain head, accepted exclusions) it was computed at.

    Raises:
        ExportError: See :class:`Reanalysis`; also a gene that is not compared, or a replicate
            the exported table does not have.
    """
    return Reanalysis(inputs, accepted).consequence(gene, unit, well_rep, well)


def exclusion_subject(gene: str, unit: str, well_rep: int = UNIT_ROW) -> str:
    """A ``prism.exclusion_reason`` (or ``prism.value_edit``) subject: one per value.

    ``gene/unit`` for a unit's value, ``gene/unit/rep n`` for one replicate, so two replicates
    of one unit are two subjects and never supersede each other in the inbox.
    """
    return f"{gene}/{unit}/rep {well_rep}" if well_rep else f"{gene}/{unit}"


def _as_accepted(study_id: str, gene: str, unit: str, well_rep: int, well: str) -> Proposal:
    """An exclusion as the proposal a person would accept (in memory only, never stored)."""
    from qpilot.schemas_studio import MadeBy, Proposal

    payload: dict[str, Any] = {
        "gene": gene,
        "sample": unit,
        "action": "exclude",
        "well_rep": well_rep,
    }
    if well:
        payload["well"] = well
    return Proposal(
        study_id=study_id,
        kind=EXCLUSION_KIND,
        subject=exclusion_subject(gene, unit, well_rep),
        payload=payload,
        made_by=MadeBy(kind="rule"),
        status="accepted",
    )


def _cell(inputs: ExportInputs, model: StudyModel) -> dict[str, Any]:
    """The decision-space cell the export was computed at, in a re-analysed space.

    Raises:
        ExportError: The exported amplification rule or efficiency model is no longer an
            option of the space.
    """
    space = model.space
    chosen = {choice.dimension: choice.value for choice in inputs.choices}
    cell: dict[str, Any] = {"refs": tuple(inputs.refs), "undetermined": inputs.undetermined}
    if "cut" in space.dimensions:
        cell["cut"] = chosen.get("cut", space.primary["cut"])
    primary = model.settings.amp_calls[0]
    rule = chosen.get("amp_call", primary)
    if rule in space.dimensions.get("amp_call", ()):
        cell["amp_call"] = rule
    elif rule != primary:
        raise ExportError(f"the amplification rule {rule!r} is no longer an option of the study")
    primary = model.settings.efficiency[0]
    efficiency = chosen.get("efficiency", primary)
    if efficiency in space.dimensions.get("efficiency", ()):
        cell["efficiency"] = efficiency
    elif efficiency != primary:
        raise ExportError(
            f"the efficiency model {efficiency!r} is no longer an option of the study"
        )
    return cell


def _conclusion(compared: Mapping[str, ContrastResult], gene: str) -> str:
    """A gene's conclusion, or ``"withheld"`` when the engine does not compare it."""
    return compared[gene].conclusion if gene in compared else WITHHELD


def _number(value: float) -> float | None:
    """A finite float, or ``None`` (no number) for NaN and infinity."""
    return float(value) if math.isfinite(value) else None


def _change(gene: str, before: Mapping[str, ContrastResult], after: Results) -> dict[str, Any]:
    """One gene's numbers before and after an exclusion (``None`` where there is none)."""
    compared, withheld = after
    b, a = before[gene], compared.get(gene)
    return {
        "fc_before": _number(b.fc),
        "fc_after": _number(a.fc) if a else None,
        "log2fc_before": _number(b.log2fc),
        "log2fc_after": _number(a.log2fc) if a else None,
        "p_before": _number(b.p),
        "p_after": _number(a.p) if a else None,
        "n_units_before": [b.n_hi, b.n_lo],
        "n_units_after": [a.n_hi, a.n_lo] if a else None,
        "conclusion_before": b.conclusion,
        "conclusion_after": a.conclusion if a else WITHHELD,
        "withheld_after": withheld.get(gene),
    }


# ---------------------------------------------------------------------------------------------
# An existing study, rebuilt read-only (the demo design)
# ---------------------------------------------------------------------------------------------


def study_inputs(
    store: StudyStore,
    study_id: str,
    *,
    rdml_path: str | Path | None = None,
    read_only: bool = False,
) -> ExportInputs:
    """Rebuild, read-only, what the Prism bridge needs for a study in the store.

    The study's workspace is never written. The settings come from the study's confirmed
    design (``study_design.json``; the demo settings when there is none), the per-well table
    from the curve cache (computed and cached when absent; with ``read_only=True`` nothing at
    all is written: the curve cache is not filled and the workspace lock file is not touched),
    and the decision space from :func:`qpilot.qpcr.study.build_model`, the same object the
    study was analysed with. Each choice is its card's decided option (the recommended option
    while the card is open), mapped back to its dimension value with the option specs
    ``qpcr/study.py`` builds the cards from (cards opened on demand, such as Trace's set-aside
    cards, are not analysis choices and are left out); the per-well table is the design's under the
    chosen amplification rule, and the groups are the study's fixed comparison. The design
    (the demo preset when there is none) and the curve analysis's own per-well table come along,
    so :class:`Reanalysis` can run the engine again.

    Raises:
        ExportError: The input file is unknown or changed, or the re-analysis does not
            reproduce the stored results.
    """
    from qpilot.core.store import sha256_file
    from qpilot.io.datasets import default_cache_dir
    from qpilot.qpcr.amp_call import apply_rule
    from qpilot.qpcr.curves import analyse_study, cache_path
    from qpilot.qpcr.designs import vermeulen_design
    from qpilot.qpcr.study import StudySettings, _card_specs, _counts, build_model

    result = store.get(study_id)
    head, cards = _head_and_cards(store, study_id, read_only)
    path = Path(rdml_path) if rdml_path is not None else store.source(study_id)
    if path is None:
        raise ExportError(
            "the study's input file is not known or has changed; give the RDML file explicitly"
        )
    if sha256_file(path) != result.input_sha256:
        raise ExportError("this file is not the input of this study (sha256 differs)")
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
        path,
        settings.experiment_id,
        settings.candidates,
        settings.curves,
        use_cache=cached or not read_only,
    )
    model = build_model(curves, settings)
    space = model.space
    primary = space.evaluate(space.primary)
    stored = result.contrasts
    if set(primary) != set(stored) or any(
        (primary[g].fc, primary[g].p) != (stored[g].fc, stored[g].p) for g in primary
    ):
        raise ExportError(
            "a re-analysis with the study's own settings does not reproduce its stored "
            "results; the Prism export refuses rather than export other numbers"
        )
    headline = [gene for gene in settings.headline if gene in space.items]
    counts = _counts(model.inputs.primary_table)
    specs: dict[str, Any] = {
        spec.card_id: spec
        for spec in _card_specs(
            space, model.stability, result.robustness, settings, headline, counts
        )
    }
    if "amp_call" in space.dimensions:  # the card's options are the rule ids themselves
        specs["card_amp_call"] = _RuleOptions(space.dimensions["amp_call"])
    if "efficiency" in space.dimensions:  # ... and the efficiency models' ids
        specs["card_efficiency"] = _RuleOptions(space.dimensions["efficiency"], "efficiency")
    analysis_cards = [c for c in cards if c.kind not in ON_DEMAND_KINDS]
    choices = tuple(_choice(card, specs) for card in sorted(analysis_cards, key=lambda c: c.rank))
    value = {c.dimension: c.value for c in choices}
    rule_id = value.get("amp_call", settings.amp_calls[0])
    efficiency = value.get("efficiency", settings.efficiency[0])
    if efficiency != settings.efficiency[0]:  # rebuilt quantities, then the rule
        data = model.cell_table({"amp_call": rule_id, "efficiency": efficiency})
    elif rule_id == settings.amp_calls[0]:
        data = model.inputs.primary_table
    else:
        calls = dict(design.well_calls) if design is not None else {}
        data = apply_rule(model.inputs.table, rule_id, calls)
    units = model.inputs.units
    unit_of = lambda sample: (units or {}).get(sample, sample)  # noqa: E731
    samples = sorted(set(data.loc[data["sample_type"] == "unkn", "sample"]))
    if model.labels is not None:  # groups from the confirmed design
        order = tuple(model.labels)
        high, rest = model.high, model.rest
    else:
        cut = float(value.get("cut", space.primary["cut"]))
        high, rest = space.groups(cut)
        order = (f"{settings.marker_label}-high", "rest")
    groups = {
        **{s: order[0] for s in samples if unit_of(s) in high},
        **{s: order[1] for s in samples if unit_of(s) in rest},
    }
    return ExportInputs(
        study_id=study_id,
        input_sha256=result.input_sha256,
        data=data,
        refs=tuple(value.get("refs", space.primary["refs"])),
        undetermined=value.get("undetermined", space.primary["undetermined"]),
        groups=groups,
        group_order=order,
        units=units,
        genes=tuple(space.items),
        headline=tuple(headline),
        rule=settings.rule,
        choices=choices,
        design_hash=(design or vermeulen_design()).design_hash(),
        design_note=result.design.note,
        chain_head=head,
        result=result,
        at_primary=all(c.option == c.recommended for c in choices),
        design=design or vermeulen_design(),
        curves=curves,
    )


#: The name every caller used before designs existed; the demo is one confirmed design.
demo_inputs = study_inputs


@dataclass(frozen=True)
class _RuleOptions:
    """Stands in for a card spec whose options are the dimension's values themselves.

    The amplification rules (``amp_call``) and the efficiency models (``efficiency``).
    """

    rules: Sequence[str]
    dimension: str = "amp_call"

    @property
    def options(self) -> list[Any]:
        from qpilot.core.decisions import OptionSpec

        return [OptionSpec(id=rule, label=rule, value=rule) for rule in self.rules]


def _head_and_cards(
    store: StudyStore, study_id: str, read_only: bool
) -> tuple[str, list[DecisionCard]]:
    """The chain head and the cards, read consistently (under the lock unless read-only)."""
    if not read_only:
        head, cards, _ = store.snapshot(study_id)
        return head, cards
    for _ in range(5):
        head = store.chain_head(study_id)
        cards = store.cards(study_id)
        if store.chain_head(study_id) == head:
            return head, cards
    raise ExportError("the study kept changing while it was read; try again")


def _choice(card: DecisionCard, specs: Mapping[str, Any]) -> Choice:
    """A card's decided (else recommended) option, mapped to its dimension value."""
    spec = specs.get(card.id)
    if spec is None:
        raise ExportError(f"card {card.id!r} is not one this export knows how to apply")
    option = card.decision or card.recommended
    values = {o.id: o.value for o in spec.options}
    if option not in values:
        raise ExportError(f"card {card.id!r}: option {option!r} is not one of its options")
    value = values[option]
    return Choice(
        card_id=card.id,
        dimension=spec.dimension,
        option=option,
        recommended=card.recommended,
        value=tuple(value) if isinstance(value, list | tuple) else value,
        actor=card.decided_by if card.decision else None,
        status=card.status,
    )


__all__ = [
    "TABLE_COLUMNS",
    "WITHHELD",
    "Choice",
    "Exclusion",
    "ExportError",
    "ExportInputs",
    "Reanalysis",
    "WELL_COLUMN",
    "check_label",
    "demo_inputs",
    "exclusion_consequence",
    "exclusion_subject",
    "replicate_wells",
    "resolve_replicate",
    "sample_table",
    "study_inputs",
    "unit_contrasts",
]
