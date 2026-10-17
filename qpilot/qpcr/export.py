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
  value).

Technical replicates are never rows of the column layout, so Prism never counts them as n.

:func:`demo_inputs` rebuilds, read-only, everything the bridge needs for a study that is
already in the store: the per-well table from the curve cache, the groups exactly as
:meth:`qpilot.qpcr.space.QpcrSpace.groups` gives them, and every card's decided option mapped
back to its dimension value with the same option specs ``qpcr/study.py`` builds the cards from.

Integration point for any confirmed design (``qpcr/designs.py``, ``StudyDesign``): the bridge
takes only plain mappings (``groups``: sample -> group, ``units``: sample -> biological unit,
``group_order``, ``refs``, ``undetermined``), so ``designs.py`` can build an
:class:`ExportInputs` from a ``StudyDesign`` without any change here; ``demo_inputs`` is the
``vermeulen_expression_defined`` preset of that.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
import pandas as pd

from qpilot.qpcr.contrast import DEFAULT_RULE, ConclusionRule, conclude, welch
from qpilot.qpcr.quant import EXCLUDED, Undetermined, excluded_cells, log2_matrix, relative
from qpilot.schemas import ContrastResult, DecisionCard, StudyResult

if TYPE_CHECKING:
    from qpilot.core.store import StudyStore

TABLE_COLUMNS: tuple[str, ...] = (
    "gene",
    "group",
    "biological_unit",
    "sample",
    "well_rep",
    "log2_rq",
)
Layout = Literal["column", "nested"]
UNIT_ROW = 0  # ``well_rep`` of a column-layout row: the unit's value, not one well
SAFE_LABEL = re.compile(r"^[\w()\-. ]{1,64}$")  # the rule of ``curves.safe_name``
DEMO_DESIGN_ID = "vermeulen_expression_defined"
_CURVE_COLUMNS = {"sample", "sample_type", "target", "n0"}


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
    biological units (``None``: every sample is its own unit).
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
    extra: dict[str, Any] = field(default_factory=dict)

    def table(self, layout: Layout = "column", genes: Sequence[str] | None = None) -> pd.DataFrame:
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

    Returns:
        A DataFrame with :data:`TABLE_COLUMNS`, sorted by gene (in the order given), group (in
        ``group_order``), unit, sample and replicate. ``well_rep`` is 0 for a unit's value
        (column layout) and 1, 2, ... for its wells (nested layout).

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

    wells, matrix, excluded = _wells(matrix_or_curves, units)
    known = sorted(set(wells["target"]))
    missing_refs = [r for r in refs if r not in known]
    if missing_refs:
        raise ExportError(f"reference genes not in the data: {missing_refs}")
    chosen = list(genes) if genes is not None else [g for g in known if g not in refs]
    unknown_genes = [g for g in chosen if g not in known]
    if unknown_genes:
        raise ExportError(f"genes not in the data: {unknown_genes}")

    in_data = set(wells["sample"])
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
    replicated = wells.duplicated(["sample", "target"]).any() or not one_to_one
    if not replicated and excluded is None:
        rows = _single_well_rows(matrix, chosen, refs, undetermined, unit_of, groups, layout)
    else:
        rows = _replicate_rows(
            wells, matrix, excluded, chosen, refs, undetermined, groups, samples_per_unit, layout
        )
    table = pd.DataFrame(rows, columns=list(TABLE_COLUMNS))
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

    The long table has ``sample, target, key, log2`` for the wells that carry a value (a
    quantity, not excluded); the matrix is :func:`qpilot.qpcr.quant.log2_matrix` with these
    ``units``, so only units measured for every gene are kept, exactly as in the engine.
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
        keys = (
            unknown["run_id"].astype(str) + "/" + unknown["well"].astype(str)
            if {"run_id", "well"} <= set(unknown.columns)
            else pd.Series(range(len(unknown)), index=unknown.index).astype(str)
        )
        wells = pd.DataFrame(
            {
                "sample": unknown["sample"].astype(str).to_numpy(),
                "target": unknown["target"].astype(str).to_numpy(),
                "key": keys.to_numpy(),
                "log2": np.log2(unknown["n0"].to_numpy(dtype=float)),
            }
        )
        return wells, matrix, excluded
    matrix = data.copy()
    matrix.index = matrix.index.astype(str)
    stacked = matrix.stack(future_stack=True).rename("log2").reset_index()
    stacked.columns = ["sample", "target", "log2"]
    stacked["key"] = stacked["sample"]
    return stacked[["sample", "target", "key", "log2"]].dropna(subset=["log2"]), matrix, None


def _single_well_rows(
    matrix: pd.DataFrame,
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
    for gene in genes:
        values = relative(matrix, gene, refs, undetermined)
        for sample, value in values.items():
            if sample in unit_of:
                rows.append((gene, groups[sample], unit_of[sample], str(sample), rep, float(value)))
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
                rows.append((gene, group, str(unit), sample, UNIT_ROW, float(value)))
            continue
        normaliser = matrix.loc[values.index, list(refs)].mean(axis=1)
        target = wells[(wells["target"] == gene) & wells["unit"].isin(values.index)]
        target = target.sort_values(["unit", "sample", "key"], kind="mergesort")
        measured = set(target["unit"])
        for unit, block in target.groupby("unit", sort=True):
            group = groups[samples_per_unit[unit][0]]
            for rep, (sample, value) in enumerate(
                zip(block["sample"], block["log2"], strict=True), start=1
            ):
                rows.append(
                    (gene, group, str(unit), str(sample), rep, float(value - normaliser[unit]))
                )
        for unit in sorted(set(values.index) - measured):  # every replicate undetermined (cap)
            group = groups[samples_per_unit[unit][0]]
            sample = "+".join(samples_per_unit[unit])
            rows.append((gene, group, str(unit), sample, 1, float(values[unit])))
    return rows


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


def exclusion_consequence(
    inputs: ExportInputs,
    gene: str,
    unit: str,
    well_rep: int = UNIT_ROW,
    *,
    layout: Layout = "column",
) -> dict[str, Any]:
    """What leaving one value out of one gene's comparison does, computed by the engine.

    Every gene of the study is compared again (Welch on log2 per unit, at the exported
    choices) with ``unit`` (or one of its replicates) left out of ``gene`` only, and the
    conclusions are compared with the same comparison without the exclusion.

    Returns:
        Numbers only (no prose): fold change, p and conclusion before and after for ``gene``,
        and how many of all genes' conclusions change.
    """
    table = inputs.table(layout, list(inputs.genes) or None)
    if gene not in set(table["gene"]):
        raise ExportError(f"gene {gene!r} is not in the exported comparison")
    before = unit_contrasts(table, inputs.group_order, inputs.rule)
    after = unit_contrasts(
        table, inputs.group_order, inputs.rule, exclude=[(gene, unit, int(well_rep))]
    )
    changed = sorted(g for g in before if before[g].conclusion != after[g].conclusion)
    b, a = before[gene], after[gene]
    return {
        "gene": gene,
        "biological_unit": unit,
        "well_rep": int(well_rep),
        "fc_before": b.fc,
        "fc_after": a.fc,
        "log2fc_before": b.log2fc,
        "log2fc_after": a.log2fc,
        "p_before": b.p,
        "p_after": a.p,
        "n_units_before": [b.n_hi, b.n_lo],
        "n_units_after": [a.n_hi, a.n_lo],
        "conclusion_before": b.conclusion,
        "conclusion_after": a.conclusion,
        "n_conclusions_changed": len(changed),
        "n_genes": len(before),
        "changed_genes": changed,
        "rule": inputs.rule.as_dict(),
    }


# ---------------------------------------------------------------------------------------------
# An existing study, rebuilt read-only (the demo design)
# ---------------------------------------------------------------------------------------------


def demo_inputs(
    store: StudyStore,
    study_id: str,
    *,
    rdml_path: str | Path | None = None,
    read_only: bool = False,
) -> ExportInputs:
    """Rebuild, read-only, what the Prism bridge needs for a study in the store.

    The study's workspace is never written. The per-well table comes from the curve cache
    (computed and cached when absent). With ``read_only=True`` nothing at all is written: the
    curve cache is not filled and the workspace lock file is not touched (the chain head and the
    cards are read twice instead, until they agree). Groups are the study's fixed split for the
    chosen cut-off, exactly as
    :meth:`QpcrSpace.groups` gives them; each choice is its card's decided option (the
    recommended option while the card is open), mapped back to its dimension value with the
    option specs ``qpcr/study.py`` builds the cards from.

    Raises:
        ExportError: The input file is unknown or changed, or a re-analysis with the demo
            settings does not reproduce the stored results (the study used other settings).
    """
    from qpilot.core.store import sha256_file
    from qpilot.io.datasets import default_cache_dir
    from qpilot.qpcr.curves import analyse_study, cache_path
    from qpilot.qpcr.design import GROUP_NOTE, GroupSpec
    from qpilot.qpcr.refgenes import genorm
    from qpilot.qpcr.space import QpcrSpace
    from qpilot.qpcr.study import StudySettings, _card_specs
    from qpilot.schemas_studio import MarkerSplit, StudyDesign

    result = store.get(study_id)
    head, cards = _head_and_cards(store, study_id, read_only)
    path = Path(rdml_path) if rdml_path is not None else store.source(study_id)
    if path is None:
        raise ExportError(
            "the study's input file is not known or has changed; give the RDML file explicitly"
        )
    if sha256_file(path) != result.input_sha256:
        raise ExportError("this file is not the input of this study (sha256 differs)")
    settings = StudySettings()
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
    matrix = log2_matrix(curves)
    stability = genorm(matrix, settings.candidates)
    space = QpcrSpace(
        matrix,
        stability,
        GroupSpec(settings.marker, settings.cut, settings.candidates, settings.group_var),
        candidates=settings.candidates,
        cuts=settings.cuts,
        undetermined=settings.undetermined,
        rule=settings.rule,
    )
    primary = space.evaluate(space.primary)
    stored = result.contrasts
    if set(primary) != set(stored) or any(
        (primary[g].fc, primary[g].p) != (stored[g].fc, stored[g].p) for g in primary
    ):
        raise ExportError(
            "a re-analysis with the demo settings does not reproduce this study's stored "
            "results, so the study used other settings; the Prism export cannot rebuild it yet"
        )
    headline = [gene for gene in settings.headline if gene in space.items]
    unknown = curves[curves["sample_type"] == "unkn"]
    counts = {"n_undetermined": int(unknown["n0"].isna().sum()), "n_unknown_wells": len(unknown)}
    specs = {
        spec.card_id: spec
        for spec in _card_specs(space, stability, result.robustness, settings, headline, counts)
    }
    choices = tuple(_choice(card, specs) for card in sorted(cards, key=lambda c: c.rank))
    value = {c.dimension: c.value for c in choices}
    cut = float(value.get("cut", space.primary["cut"]))
    high, rest = space.groups(cut)
    high_label = f"{settings.marker_label}-high"
    groups = {**{s: high_label for s in sorted(high)}, **{s: "rest" for s in sorted(rest)}}
    design = StudyDesign(
        design_id=DEMO_DESIGN_ID,
        experiment_id=settings.experiment_id,
        mode="marker_split",
        marker_split=MarkerSplit(
            marker=settings.marker,
            cut=settings.cut,
            cuts=tuple(settings.cuts),
            group_var=settings.group_var,
        ),
        reference_candidates=tuple(settings.candidates),
        headline=tuple(settings.headline),
    )
    return ExportInputs(
        study_id=study_id,
        input_sha256=result.input_sha256,
        data=curves,
        refs=tuple(value.get("refs", space.primary["refs"])),
        undetermined=value.get("undetermined", space.primary["undetermined"]),
        groups=groups,
        group_order=(high_label, "rest"),
        units=None,
        genes=tuple(space.items),
        headline=tuple(headline),
        rule=settings.rule,
        choices=choices,
        design_hash=design.design_hash(),
        design_note=GROUP_NOTE,
        chain_head=head,
        result=result,
        at_primary=all(c.option == c.recommended for c in choices),
    )


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
    "Choice",
    "ExportError",
    "ExportInputs",
    "check_label",
    "demo_inputs",
    "exclusion_consequence",
    "sample_table",
    "unit_contrasts",
]
