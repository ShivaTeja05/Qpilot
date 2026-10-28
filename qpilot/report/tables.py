"""A study's numbers as tidy tables: the one source of every export (xlsx, CSV, figures, zip).

:func:`study_tables` reads one study from the store, read only, and returns its numbers as plain
tables of engine values (never text renderings of them):

* **Results**: one row per comparison and gene: the call, the fold change with its 95 % CI as
  two numbers, log2 fold change, p (Welch's t test), q when the engine gives one, n per group
  (biological units), how often the call holds in qPilot's choice grid and the confidence level;
* **Per unit**: one row per comparison, gene and biological unit: the wells used, mean Cq of the
  gene and of the reference genes, ΔCq, log2 relative quantity (log2 RQ, the value the test
  uses) and RQ;
* **Per well**: one row per well: plate, well, sample, unit, group, role, target, Cq, N0 (the
  curve fit's and the one in use), the well's and the assay's efficiency, whether it counts as
  amplified under the call rule in use, and whether a person left it out (and why);
* **Decisions** (who, what, why, when), **Settings** (every analysis choice in use, the test,
  the rule), **Methods** and the **MIQE 2.0** checklist from the report, and **About**.

**Which analysis.** The tables follow the options the person chose on the Decision Cards (the
analysis the decision chain describes; a card still open counts at its recommended option),
labelled "As decided". When that is not the recommended analysis, the recommended one comes too
(:attr:`StudyTables.recommended`), labelled, so a reader can see both. The as-decided numbers
are the engine's own: :class:`qpilot.qpcr.export.Reanalysis` evaluates the study's decision
space at the chosen cell, the arithmetic the Results page's "at your choices" reads from the
grid; at the recommended options they are the stored results, unchanged.

**Comparisons.** Every per-gene table iterates over :attr:`AnalysisTables.comparisons`
(:func:`comparisons`, the one adapter): today one, the study's two groups; several when the
design compares several pairs.

Without the study's input file (unknown or changed) the per-unit and per-well tables cannot be
rebuilt: they are empty with a note saying why, and the results come from the store (and, for
decided options, from the choice grid). Deterministic: no model call, no network, nothing
written.
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import cached_property
from typing import Any, Literal

import numpy as np
import pandas as pd

from qpilot.core.store import ON_DEMAND_KINDS, StudyNotFound, StudyStore
from qpilot.schemas import ContrastResult, DecisionCard, StudyResult

Basis = Literal["as_decided", "recommended"]
AS_DECIDED: Basis = "as_decided"
RECOMMENDED: Basis = "recommended"
BASES: tuple[Basis, ...] = (AS_DECIDED, RECOMMENDED)
BASIS_LABEL: dict[str, str] = {
    AS_DECIDED: "As decided",
    RECOMMENDED: "Recommended analysis",
}
BASIS_WORDS: dict[str, str] = {
    AS_DECIDED: "As decided: the options chosen on the Decision Cards (a card still open counts "
    "at its recommended option)",
    RECOMMENDED: "Recommended analysis: every Decision Card at its recommended option",
}
CALL_WORDS = {"up": "up", "down": "down", "none": "no call"}
NOT_COMPARED = "not compared"
TEST_WORDS = (
    "Welch's t test (two-sided) on per-unit log2 relative quantities; 95 % confidence "
    "intervals from the same test"
)
REPLICATE_WORDS = (
    "Technical replicates averaged within each biological unit (mean log2 N0); n is biological "
    "units, never wells"
)
NORMALISATION_WORDS = "log2 N0 of the gene minus the mean log2 N0 of the reference genes"
RESEARCH_USE = "For research use only. Not for clinical or diagnostic use."
MAX_CACHED = 4

Kind = Literal[
    "text", "int", "float", "fold", "log2", "p", "share", "cq", "n0", "eff", "bool", "rq"
]


# ---------------------------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Column:
    """One column: its tidy name (CSV header), its header in words (Excel), and its kind."""

    key: str
    header: str
    kind: Kind = "text"


@dataclass(frozen=True)
class Table:
    """One tidy table: a name (file stem), a title (sheet), columns and rows of plain values.

    Values are ``str``, ``int``, ``float`` (finite), ``bool`` or ``None`` (no value).
    """

    name: str
    title: str
    columns: tuple[Column, ...]
    rows: tuple[tuple[Any, ...], ...] = ()
    note: str = ""

    def keys(self) -> list[str]:
        """The tidy column names."""
        return [c.key for c in self.columns]

    def records(self) -> list[dict[str, Any]]:
        """The rows as dicts by tidy column name."""
        keys = self.keys()
        return [dict(zip(keys, row, strict=True)) for row in self.rows]

    def frame(self) -> pd.DataFrame:
        """The table as a DataFrame (tidy names)."""
        return pd.DataFrame(list(self.rows), columns=self.keys())


def _num(value: Any) -> float | None:
    """A finite float, or None (NaN, infinity and missing values are no number)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value: Any) -> int | None:
    number = _num(value)
    return None if number is None else int(round(number))


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    text = str(value)
    return text or None


# ---------------------------------------------------------------------------------------------
# Comparisons (the one adapter: several pairs of groups when the design names several)
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Comparison:
    """One comparison of two groups and every gene's result in it (engine values)."""

    name: str
    group_a: str
    group_b: str
    contrasts: Mapping[str, ContrastResult]
    withheld: Mapping[str, str] = field(default_factory=dict)
    q: Mapping[str, float] | None = None
    correction: str | None = None

    @property
    def genes(self) -> list[str]:
        """The compared genes, then the withheld ones, each in the engine's order."""
        return [*self.contrasts, *(g for g in self.withheld if g not in self.contrasts)]


def comparisons(
    group_order: Sequence[str],
    contrasts: Mapping[str, ContrastResult],
    withheld: Mapping[str, str] | None = None,
    extra: Iterable[Comparison] = (),
) -> tuple[Comparison, ...]:
    """The comparisons the tables iterate over: the study's two groups, then any ``extra``.

    The one place that knows how a study's comparisons are named; a design with several pairs
    of groups passes them as ``extra`` (each with its own contrasts and, when the engine
    corrects across them, its q-values).
    """
    a, b = (str(group_order[0]), str(group_order[1])) if len(group_order) >= 2 else ("A", "B")
    first = Comparison(
        name=f"{a} vs {b}", group_a=a, group_b=b, contrasts=contrasts, withheld=withheld or {}
    )
    return (first, *extra)


# ---------------------------------------------------------------------------------------------
# One analysis (as decided, or recommended)
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Choice:
    """One analysis choice the tables are computed at, in words."""

    card_id: str
    title: str
    dimension: str
    option: str
    option_label: str
    recommended: str
    recommended_label: str
    who: str
    status: str

    @property
    def is_recommended(self) -> bool:
        """The option in use is the card's recommended one."""
        return self.option == self.recommended


@dataclass(frozen=True)
class AnalysisTables:
    """The per-gene, per-unit and per-well tables of one analysis of a study."""

    basis: Basis
    comparisons: tuple[Comparison, ...]
    choices: tuple[Choice, ...]
    results: Table
    per_unit: Table
    per_well: Table
    refs: tuple[str, ...]
    efficiency: str
    amp_call: str
    undetermined: str
    rebuilt: bool = True
    note: str = ""

    @property
    def label(self) -> str:
        """``As decided`` or ``Recommended analysis``."""
        return BASIS_LABEL[self.basis]

    @property
    def words(self) -> str:
        """What the analysis is, in a sentence."""
        return BASIS_WORDS[self.basis]

    def comparison(self, name: str | None = None) -> Comparison:
        """One comparison by name (the first by default).

        Raises:
            KeyError: No comparison of that name.
        """
        if name is None:
            return self.comparisons[0]
        for c in self.comparisons:
            if c.name == name:
                return c
        raise KeyError(name)

    def unit_values(self, gene: str, comparison: str | None = None) -> dict[str, list]:
        """``{group: [(unit, log2 RQ), ...]}`` of one gene, each unit with a value, by unit."""
        comp = self.comparison(comparison)
        keys = self.per_unit.keys()
        at = {k: keys.index(k) for k in ("comparison", "gene", "group", "biological_unit")}
        value = keys.index("log2_rq")
        out: dict[str, list] = {comp.group_a: [], comp.group_b: []}
        for row in self.per_unit.rows:
            if row[at["comparison"]] != comp.name or row[at["gene"]] != gene:
                continue
            if row[value] is None:
                continue
            out.setdefault(row[at["group"]], []).append((row[at["biological_unit"]], row[value]))
        return {g: sorted(v, key=lambda pair: str(pair[0])) for g, v in out.items()}


@dataclass(frozen=True)
class StudyTables:
    """Every table of one study: the analysis as decided, the recommended one when it differs."""

    study_id: str
    input_sha256: str
    chain_head: str
    design_hash: str
    source_name: str | None
    decided: AnalysisTables
    recommended: AnalysisTables | None
    decisions: Table
    settings: Table
    headline: tuple[str, ...]
    n_open: int
    versions: dict[str, str]
    notes: tuple[str, ...] = ()
    load_report: Callable[[], tuple[Any, str]] = field(
        default=lambda: (None, ""), compare=False, repr=False
    )

    @cached_property
    def _report(self) -> tuple[Any, str]:
        """The study's report (built on first use: only the Methods and MIQE tables need it)."""
        return self.load_report()

    @property
    def methods(self) -> Table:
        """The report's Methods paragraphs and references."""
        return _methods(self._report[0])

    @property
    def miqe(self) -> Table:
        """The report's MIQE 2.0 checklist."""
        return _miqe(self._report[0])

    @property
    def bases(self) -> tuple[Basis, ...]:
        """The analyses these tables hold: as decided first."""
        return (AS_DECIDED, RECOMMENDED) if self.recommended is not None else (AS_DECIDED,)

    def analysis(self, basis: str = AS_DECIDED) -> AnalysisTables:
        """One analysis; ``recommended`` is the decided one when they are the same.

        Raises:
            ValueError: Unknown basis.
        """
        if basis == AS_DECIDED:
            return self.decided
        if basis == RECOMMENDED:
            return self.recommended or self.decided
        raise ValueError(f"basis must be one of {BASES}, not {basis!r}")

    def about(self, record_id: str | None = None) -> Table:
        """What the export is: the study, the analysis, the hashes that bind it, how to check it."""
        decided = self.decided
        rows: list[tuple[str, str]] = [
            ("study_id", self.study_id),
            ("analysis", decided.words),
        ]
        if self.recommended is not None:
            rows.append(
                (
                    "also_included",
                    "The recommended analysis (every card at its recommended option), in the "
                    "tables marked 'recommended'",
                )
            )
        elif self.n_open:
            rows.append(("open_cards", f"{self.n_open} Decision Cards are still open"))
        else:
            rows.append(("recommended_analysis", "The same: every choice in use is recommended"))
        rows += [
            ("comparisons", "; ".join(c.name for c in decided.comparisons)),
            ("input_file", self.source_name or "unknown"),
            ("input_sha256", self.input_sha256),
            ("design_sha256", self.design_hash or "none (the demo settings)"),
            ("decision_chain_head", self.chain_head),
        ]
        if record_id:
            rows.append(("analysis_record_id", record_id))
        rows += [
            (
                "verify",
                "The decision chain head is the hash the Analysis Record carries: export the "
                "record (Record section, or `qpilot export supplement`) and run "
                "`qpilot verify <record.zip>`",
            ),
            *((f"version_{k}", v) for k, v in sorted(self.versions.items()) if v != "unknown"),
            *(("note", n) for n in (*self.notes, self._report[1]) if n),
            ("research_use", RESEARCH_USE),
        ]
        return Table(
            name="about",
            title="About",
            columns=(Column("key", "What"), Column("value", "Value")),
            rows=tuple(rows),
        )


# ---- columns ---------------------------------------------------------------------------------

RESULT_COLUMNS: tuple[Column, ...] = (
    Column("comparison", "Comparison"),
    Column("group_a", "Group A"),
    Column("group_b", "Group B (reference)"),
    Column("gene", "Gene"),
    Column("headline", "Headline gene", "bool"),
    Column("call", "Call (rule: see Settings)"),
    Column("fold_change", "Fold change (×, A / B)", "fold"),
    Column("ci95_low", "95 % CI low (×)", "fold"),
    Column("ci95_high", "95 % CI high (×)", "fold"),
    Column("log2_fold_change", "log2 fold change", "log2"),
    Column("p", "p (Welch's t test)", "p"),
    Column("n_a", "n A (biological units)", "int"),
    Column("n_b", "n B (biological units)", "int"),
    Column("same_call_share", "Same call in qPilot's choice grid (share)", "share"),
    Column("grid_analyses", "Analyses in qPilot's choice grid", "int"),
    Column("confidence", "Confidence level"),
    Column("assay_efficiency", "Assay efficiency (amplification per cycle)", "eff"),
    Column("note", "Note"),
)
Q_COLUMN = Column("q", "q (corrected for many genes)", "p")
PER_UNIT_COLUMNS: tuple[Column, ...] = (
    Column("comparison", "Comparison"),
    Column("gene", "Gene"),
    Column("group", "Group"),
    Column("biological_unit", "Biological unit"),
    Column("wells", "Wells used (technical replicates)", "int"),
    Column("cq_gene", "Mean Cq of the gene (cycles)", "cq"),
    Column("cq_reference", "Mean Cq of the reference genes (cycles)", "cq"),
    Column("delta_cq", "ΔCq (cycles, gene − reference genes)", "cq"),
    Column("log2_rq", "log2 relative quantity (log2 RQ; the value tested)", "log2"),
    Column("rq", "Relative quantity (RQ, linear)", "rq"),
    Column("note", "Note"),
)
PER_WELL_COLUMNS: tuple[Column, ...] = (
    Column("plate", "Plate (run)"),
    Column("well", "Well"),
    Column("sample", "Sample"),
    Column("biological_unit", "Biological unit"),
    Column("group", "Group"),
    Column("role", "Role (unkn, ntc, nrt, std, ...)"),
    Column("target", "Target"),
    Column("reference_gene", "Reference gene", "bool"),
    Column("cq", "Cq (cycles, TD0)", "cq"),
    Column("n0", "N0 (curve fit, fluorescence units)", "n0"),
    Column("n0_in_use", "N0 in use (call rule and efficiency model applied)", "n0"),
    Column("efficiency_well", "Well efficiency (its own fit)", "eff"),
    Column("efficiency_assay", "Assay efficiency on this plate (mean of its wells)", "eff"),
    Column("amplified", "Counts as amplified (call rule in use)", "bool"),
    Column("left_out", "Left out by a person", "bool"),
    Column("left_out_reason", "Why it was left out"),
    Column("file_flag", "Flag in the file or from the curve fit"),
)
DECISION_COLUMNS: tuple[Column, ...] = (
    Column("seq", "Entry", "int"),
    Column("kind", "Kind"),
    Column("what", "What was decided"),
    Column("option", "Option chosen"),
    Column("recommended", "Recommended option"),
    Column("who", "Who"),
    Column("why", "Why (their reason)"),
    Column("when", "When (UTC)"),
    Column("status", "Status"),
    Column("hash", "Entry hash"),
)
SETTING_COLUMNS: tuple[Column, ...] = (
    Column("setting", "Setting"),
    Column("value", "In use"),
    Column("recommended", "Recommended"),
    Column("who", "Chosen by"),
)
METHOD_COLUMNS: tuple[Column, ...] = (
    Column("section", "Section"),
    Column("text", "Text"),
)
MIQE_COLUMNS: tuple[Column, ...] = (
    Column("id", "MIQE 2.0 item"),
    Column("section", "Section"),
    Column("item", "Item"),
    Column("status", "Status"),
    Column("only_a_person", "Only a person can answer", "bool"),
    Column("evidence", "Evidence from the study"),
)


# ---------------------------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------------------------

_lock = threading.Lock()
_cache: OrderedDict[tuple, StudyTables] = OrderedDict()


def study_tables(
    store: StudyStore, study_id: str, session: str | None = None, *, report: Any = None
) -> StudyTables:
    """Every table of one study (cached until the study's files change).

    Args:
        store: The study store (read only).
        study_id: The study.
        session: The Studio session the study belongs to (for the report's Methods and MIQE).
        report: A :class:`qpilot.report.model.ReportView` already built (default: built here;
            without one the Methods and MIQE tables say why they are empty).

    Raises:
        StudyNotFound: Unknown study.
    """
    from qpilot.report.inputs import fingerprint

    key = (str(store.root), session, *fingerprint(store, study_id))
    with _lock:
        cached = _cache.get(key)
        if cached is not None:
            _cache.move_to_end(key)
            return cached
    tables = build_tables(store, study_id, session, report=report)
    with _lock:
        _cache[key] = tables
        while len(_cache) > MAX_CACHED:
            _cache.popitem(last=False)
    return tables


def build_tables(
    store: StudyStore, study_id: str, session: str | None = None, *, report: Any = None
) -> StudyTables:
    """:func:`study_tables` afresh (no cache)."""
    from qpilot.qpcr.designs import vermeulen_design
    from qpilot.qpcr.export import ExportError, study_inputs

    result = store.get(study_id)
    head = store.chain_head(study_id)
    cards = [c for c in store.cards(study_id) if c.kind not in ON_DEMAND_KINDS]
    design = store.design(study_id)
    notes: list[str] = []
    reasons = _exclusion_reasons(store, study_id)
    try:
        decided_inputs = study_inputs(store, study_id, read_only=True)
    except (ExportError, OSError, ValueError) as err:
        decided_inputs = None
        notes.append(
            f"The per-unit and per-well tables are empty: {str(err).rstrip('.')}. The results "
            "come from the stored analysis."
        )
    if decided_inputs is not None:
        decided = _analysis(AS_DECIDED, decided_inputs, result, cards, reasons)
        recommended = None
        if not decided_inputs.at_primary:
            rec_inputs = study_inputs(_AtRecommended(store), study_id, read_only=True)
            recommended = _analysis(RECOMMENDED, rec_inputs, result, cards, reasons)
        design_hash = decided_inputs.design_hash
    else:
        decided, recommended = _stored_analyses(store, result, cards)
        design_hash = (design or vermeulen_design()).design_hash() if design else ""
    source = store.source(study_id)
    return StudyTables(
        study_id=study_id,
        input_sha256=result.input_sha256,
        chain_head=head,
        design_hash=design_hash,
        source_name=source.name if source is not None else None,
        decided=decided,
        recommended=recommended,
        decisions=_decisions(store, study_id, cards),
        settings=_settings(decided, recommended, result),
        headline=tuple(_headline(store, result, cards)),
        n_open=sum(1 for c in cards if c.status in ("open", "pending_human")),
        versions=_versions(),
        notes=tuple(notes),
        load_report=lambda: _report_view(store, study_id, session, report),
    )


class _AtRecommended:
    """A read-only view of the store whose cards are all at their recommended option."""

    def __init__(self, store: StudyStore) -> None:
        self._store = store

    def cards(self, study_id: str) -> list[DecisionCard]:
        return [
            c.model_copy(update={"decision": None, "decided_by": None})
            for c in self._store.cards(study_id)
        ]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)


def _analysis(
    basis: Basis,
    inputs: Any,
    result: StudyResult,
    cards: Sequence[DecisionCard],
    reasons: Mapping[str, str],
) -> AnalysisTables:
    """One analysis from the Prism bridge's inputs (:func:`qpilot.qpcr.export.study_inputs`)."""
    from qpilot.qpcr.export import Reanalysis

    if inputs.at_primary:
        contrasts: Mapping[str, ContrastResult] = result.contrasts
        withheld = _stored_withheld(result)
    else:
        contrasts, withheld = Reanalysis(inputs).results()
    comps = comparisons(inputs.group_order, contrasts, withheld)
    choices = _choices(inputs.choices, cards)
    words = _choice_words(inputs, choices)
    table = inputs.table("column")
    return AnalysisTables(
        basis=basis,
        comparisons=comps,
        choices=choices,
        results=_results_table(basis, comps, result, inputs.headline),
        per_unit=_per_unit_table(basis, comps, table, inputs),
        per_well=_per_well_table(basis, inputs, reasons),
        refs=tuple(inputs.refs),
        **words,
    )


def _stored_analyses(
    store: StudyStore, result: StudyResult, cards: Sequence[DecisionCard]
) -> tuple[AnalysisTables, AnalysisTables | None]:
    """Without the input file: the stored results, and the grid's row at the decided options."""
    from qpilot.web.results_views import at_choices, load_grid

    headline = _headline(store, result, cards)
    group_order = _stored_groups(result)
    rec_comps = comparisons(group_order, result.contrasts, _stored_withheld(result))
    choices = _choices((), cards)
    why = "the study's input file is not known here, so per-unit and per-well values are missing"
    empty_unit = Table("per_unit", "Per unit", PER_UNIT_COLUMNS, note=why)
    empty_well = Table("per_well", "Per well", PER_WELL_COLUMNS, note=why)
    words = {
        "efficiency": "LinRegPCR's mean efficiency of each assay on each plate",
        "amp_call": "see the Methods",
        "undetermined": "see the Methods",
    }
    recommended = AnalysisTables(
        basis=RECOMMENDED,
        comparisons=rec_comps,
        choices=choices,
        results=_results_table(RECOMMENDED, rec_comps, result, headline),
        per_unit=empty_unit,
        per_well=empty_well,
        refs=tuple(result.design.refs_primary),
        rebuilt=False,
        note=why,
        **words,
    )
    at = at_choices(load_grid(store, result), cards)
    if at is None:  # nothing decided differs: as decided is the recommended analysis
        decided = replace(
            recommended,
            basis=AS_DECIDED,
            results=_results_table(AS_DECIDED, rec_comps, result, headline),
        )
        return decided, None
    contrasts = {
        gene: ContrastResult(
            target=gene,
            log2fc=float(row["log2fc"]),
            fc=float(row["fc"]),
            ci=(math.nan, math.nan),
            p=float(row["p"]) if _num(row["p"]) is not None else math.nan,
            t=math.nan,
            n_hi=0,
            n_lo=0,
            conclusion=str(row["conclusion"]),  # type: ignore[arg-type]
        )
        for gene, row in at.iterrows()
    }
    comps = comparisons(group_order, contrasts)
    decided = AnalysisTables(
        basis=AS_DECIDED,
        comparisons=comps,
        choices=choices,
        results=_results_table(AS_DECIDED, comps, result, headline, grid_only=True),
        per_unit=empty_unit,
        per_well=empty_well,
        refs=tuple(result.design.refs_primary),
        rebuilt=False,
        note=why + "; confidence intervals and n need it too",
        **words,
    )
    return decided, recommended


def _stored_groups(result: StudyResult) -> tuple[str, str]:
    from qpilot.app_state import GROUPS_NOTE

    if result.design.note == GROUPS_NOTE:
        a = result.facts.get("f_group_a")
        b = result.facts.get("f_group_b")
        if a is not None and b is not None:
            return str(a.value), str(b.value)
    marker = result.design.group_var.removesuffix("_high") or result.design.group_var
    return f"{marker}-high", "rest"


def _stored_withheld(result: StudyResult) -> dict[str, str]:
    from qpilot.web.results_views import withheld

    return {w.gene: w.reason for w in withheld(result)}


def _headline(store: StudyStore, result: StudyResult, cards: Sequence[DecisionCard]) -> list[str]:
    from qpilot.web.results_views import headline_genes

    try:
        return list(headline_genes(result, cards, store))
    except Exception:  # the headline is a label; a study without one still exports
        return []


# ---- choices ---------------------------------------------------------------------------------

WHO = {"human": "a person", "agent": "an agent", "system": "the system"}


def _who(card: DecisionCard | None) -> str:
    if card is None or card.decision is None:
        return "not decided yet (recommended option)"
    who = WHO.get(card.decided_by or "", card.decided_by or "the system")
    return (
        f"{who} (decided automatically: it changes no conclusion)"
        if (card.status == "auto_decided")
        else who
    )


def _choices(raw: Sequence[Any], cards: Sequence[DecisionCard]) -> tuple[Choice, ...]:
    """Each card's option in use, in words (from the bridge's choices, else from the cards)."""
    from qpilot.ai.explain import KIND_TITLE

    by_id = {c.id: c for c in cards}
    out = []
    picked = {c.card_id: c for c in raw}
    for card in sorted(cards, key=lambda c: c.rank):
        choice = picked.get(card.id)
        option = choice.option if choice is not None else (card.decision or card.recommended)
        labels = {o.id: o.label for o in card.options}
        out.append(
            Choice(
                card_id=card.id,
                title=KIND_TITLE.get(card.kind, card.kind.replace("_", " ")),
                dimension=choice.dimension if choice is not None else card.kind,
                option=option,
                option_label=labels.get(option, option),
                recommended=card.recommended,
                recommended_label=labels.get(card.recommended, card.recommended),
                who=_who(by_id.get(card.id))
                if option == card.decision or card.decision is None
                else "recommended (the option chosen on the card differs)",
                status=card.status,
            )
        )
    return tuple(out)


def _choice_words(inputs: Any, choices: Sequence[Choice]) -> dict[str, str]:
    """The efficiency model, amplification rule and undetermined rule in use, in words."""
    from qpilot.qpcr.amp_call import RULES
    from qpilot.web.results_views import option_label

    value = {c.dimension: c.value for c in inputs.choices}
    design = inputs.design
    amp = value.get("amp_call", design.amp_calls[0] if design is not None else "linregpcr")
    rule = RULES.get(str(amp))
    efficiency = value.get("efficiency")
    if efficiency is None:
        axes = (design.axes or {}) if design is not None else {}
        efficiency = (axes.get("efficiency") or ("linregpcr",))[0]
    eff_words = option_label("efficiency", str(efficiency))
    if eff_words == "linregpcr":
        eff_words = "LinRegPCR's mean efficiency of each assay on each plate"
    undetermined = str(inputs.undetermined)
    by_dim = {c.dimension: c for c in choices}
    und = by_dim.get("undetermined")
    und_words = und.option_label if und is not None and und.option == undetermined else undetermined
    return {
        "efficiency": eff_words,
        "amp_call": rule.label if rule is not None else str(amp),
        "undetermined": und_words,
    }


# ---- results ---------------------------------------------------------------------------------


def _results_table(
    basis: Basis,
    comps: Sequence[Comparison],
    result: StudyResult,
    headline: Iterable[str],
    *,
    grid_only: bool = False,
) -> Table:
    lead = set(headline)
    with_q = any(c.q for c in comps)
    columns = list(RESULT_COLUMNS)
    if with_q:
        columns.insert(columns.index(next(c for c in columns if c.key == "p")) + 1, Q_COLUMN)
    rows = []
    for comp in comps:
        for gene in comp.genes:
            con = comp.contrasts.get(gene)
            rob = result.robustness.get(gene)
            grade = result.confidence.get(gene)
            stored = result.contrasts.get(gene)
            same = None
            if rob is not None and con is not None and stored is not None:
                if con.conclusion == stored.conclusion:  # the grid's share is of the planned call
                    same = _num(rob.holds)
            note = None
            if con is None:
                note = f"withheld: {comp.withheld.get(gene, 'too few values in a group')}"
            elif grid_only:
                note = "from qPilot's choice grid (no input file: no CI or n here)"
            row: dict[str, Any] = {
                "comparison": comp.name,
                "group_a": comp.group_a,
                "group_b": comp.group_b,
                "gene": gene,
                "headline": gene in lead,
                "call": CALL_WORDS.get(con.conclusion, con.conclusion) if con else NOT_COMPARED,
                "fold_change": _num(con.fc) if con else None,
                "ci95_low": _num(con.ci[0]) if con else None,
                "ci95_high": _num(con.ci[1]) if con else None,
                "log2_fold_change": _num(con.log2fc) if con else None,
                "p": _num(con.p) if con else None,
                "q": _num((comp.q or {}).get(gene)) if with_q else None,
                "n_a": (con.n_hi or None) if con else None,
                "n_b": (con.n_lo or None) if con else None,
                "same_call_share": same,
                "grid_analyses": (rob.n_cells or None) if rob is not None else None,
                "confidence": grade.level if grade else None,
                "assay_efficiency": _num(result.efficiency.get(gene)),
                "note": note,
            }
            rows.append(tuple(row[c.key] for c in columns))
    title = "Results" if basis == AS_DECIDED else "Results (recommended)"
    name = "results" if basis == AS_DECIDED else "results_recommended"
    return Table(name, title, tuple(columns), tuple(rows))


# ---- per unit --------------------------------------------------------------------------------


def _unit_wells(inputs: Any) -> pd.DataFrame:
    """The wells each unit's value comes from: study samples with a quantity, not left out."""
    from qpilot.qpcr.quant import EXCLUDED

    data = inputs.data
    keep = data["sample_type"] == "unkn"
    keep &= data["sample"].isin(list(inputs.groups))
    keep &= data["n0"].notna()
    if EXCLUDED in data.columns:
        keep &= ~data[EXCLUDED].fillna(False).astype(bool)
    wells = data.loc[keep, ["sample", "target", "cq"]].copy()
    units = inputs.units or {}
    wells["unit"] = wells["sample"].map(lambda s: units.get(s, s))
    wells["cq"] = pd.to_numeric(wells["cq"], errors="coerce")
    wells.loc[~np.isfinite(wells["cq"].astype(float)) | (wells["cq"] <= 0), "cq"] = np.nan
    return wells


def _per_unit_table(
    basis: Basis, comps: Sequence[Comparison], table: pd.DataFrame, inputs: Any
) -> Table:
    wells = _unit_wells(inputs)
    grouped = wells.groupby(["unit", "target"])["cq"]
    counts = {(str(u), str(t)): int(n) for (u, t), n in grouped.size().items()}
    cq = {(str(u), str(t)): float(v) for (u, t), v in grouped.mean().items()}
    refs = list(inputs.refs)
    ref_cq: dict[str, float] = {}
    for unit in {u for u, _ in cq}:
        values = [cq.get((unit, r), math.nan) for r in refs]
        if values and all(math.isfinite(v) for v in values):
            ref_cq[unit] = float(np.mean(values))
    rows = []
    for comp in comps:
        sub = table[table["gene"].isin(set(comp.genes))]
        columns = (sub[k].to_numpy() for k in ("gene", "group", "biological_unit", "log2_rq"))
        for gene, group, unit, value in zip(*columns, strict=True):
            gene, unit = str(gene), str(unit)
            log2 = _num(value)
            n = counts.get((unit, gene), 0)
            gene_cq = _num(cq.get((unit, gene)))
            ref = ref_cq.get(unit)
            delta = gene_cq - ref if gene_cq is not None and ref is not None else None
            note = None
            if log2 is not None and n == 0:
                note = "no quantity in any well: counted at the gene's lowest value (cap)"
            elif log2 is None:
                note = "no value (undetermined or left out)"
            rows.append(
                (
                    comp.name,
                    gene,
                    str(group),
                    unit,
                    n,
                    gene_cq,
                    _num(ref),
                    _num(delta),
                    log2,
                    _num(2.0**log2) if log2 is not None else None,
                    note,
                )
            )
    title = "Per unit" if basis == AS_DECIDED else "Per unit (recommended)"
    name = "per_unit" if basis == AS_DECIDED else "per_unit_recommended"
    return Table(name, title, PER_UNIT_COLUMNS, tuple(rows))


# ---- per well --------------------------------------------------------------------------------

_WELL_FIELDS = (
    "run_id",
    "well",
    "sample",
    "sample_type",
    "target",
    "target_raw",
    "cq",
    "n0",
    "eff_indiv",
    "eff_target",
    "excluded",
    "note",
)


def _per_well_table(basis: Basis, inputs: Any, reasons: Mapping[str, str]) -> Table:
    from qpilot.qpcr.quant import EXCLUDED

    data = inputs.data
    raw = inputs.curves
    key = ["run_id", "well", "target_raw"]
    raw_n0: dict[tuple, Any] = {}
    if raw is not None and set(key) <= set(raw.columns):
        raw_n0 = dict(zip(map(tuple, raw[key].to_numpy()), raw["n0"].to_numpy(), strict=True))
    units = inputs.units or {}
    refs = set(inputs.refs)
    groups = inputs.groups
    n = len(data)
    excluded = (
        data[EXCLUDED].fillna(False).astype(bool).to_numpy()
        if EXCLUDED in data.columns
        else np.zeros(n, dtype=bool)
    )
    left_out_design = set(inputs.design.excluded_wells) if inputs.design is not None else set()
    fields = [
        data[f].to_numpy() if f in data.columns else np.full(n, None, dtype=object)
        for f in _WELL_FIELDS
    ]
    rows = []
    for out, (
        plate,
        well,
        sample,
        role,
        target,
        target_raw,
        cq,
        n0,
        eff_w,
        eff_a,
        excl,
        note,
    ) in zip(excluded, zip(*fields, strict=True), strict=True):
        plate, well, sample = str(plate), str(well), str(sample)
        wkey = f"{plate}/{well}"
        left = bool(out) or wkey in left_out_design
        unit = units.get(sample, sample) if role == "unkn" else None
        n0_use = _num(n0)
        n0_fit = _num(raw_n0.get((plate, well, target_raw), n0))
        flag = " ".join(t for t in (_text(excl), _text(note)) if t) or None
        rows.append(
            (
                plate,
                well,
                sample,
                unit,
                groups.get(sample) if unit is not None else None,
                _text(role),
                _text(target),
                str(target) in refs,
                _positive(cq),
                n0_fit,
                None if left else n0_use,
                _num(eff_w),
                _num(eff_a),
                n0_use is not None,
                left,
                _reason(reasons, wkey, target, unit, sample) if left else None,
                flag,
            )
        )
    title = "Per well" if basis == AS_DECIDED else "Per well (recommended)"
    name = "per_well" if basis == AS_DECIDED else "per_well_recommended"
    return Table(name, title, PER_WELL_COLUMNS, tuple(rows))


def _reason(reasons: Mapping[str, str], key: str, target: Any, unit: Any, sample: str) -> str:
    """Why a well is left out: its own proposal, else its unit's (from Prism), else the design."""
    for k in (key, f"unit:{target}/{unit}", f"unit:{target}/{sample}"):
        if k in reasons:
            return reasons[k]
    return "left out in the confirmed design"


def _positive(value: Any) -> float | None:
    """A Cq: positive and finite (vendors write 0 or -1 for none)."""
    number = _num(value)
    return number if number is not None and number > 0 else None


def _exclusion_reasons(store: StudyStore, study_id: str) -> dict[str, str]:
    """Well key -> why a person left it out (the accepted proposal's reason, in their words)."""
    try:
        accepted = store.proposals(study_id).accepted()
    except Exception:  # no session, or a chain that does not verify: no reasons to quote
        return {}
    out: dict[str, str] = {}
    for p in accepted:
        payload = p.effective_payload()
        reason = (p.reason or "").strip() or "no reason given"
        who = "a person" if p.decided_by == "human" else "accepted"
        if p.kind == "curve.exclude_well" and payload.get("excluded") is True:
            out[p.subject] = f"{reason} ({who}, {p.decided_at or 'time not recorded'})"
        elif p.kind == "prism.exclusion_reason" and payload.get("action") == "exclude":
            well = payload.get("well")
            text = f"{reason} (left out from Prism, {p.decided_at or 'time not recorded'})"
            if well:
                out[str(well)] = text
            else:
                out[f"unit:{payload.get('gene')}/{payload.get('sample')}"] = text
    return out


# ---- decisions, settings, methods, MIQE -----------------------------------------------------


def _report_view(
    store: StudyStore, study_id: str, session: str | None, view: Any
) -> tuple[Any, str]:
    if view is not None:
        return view, ""
    from qpilot.report.build import report
    from qpilot.report.text import ProseError

    try:
        return report(store, study_id, session), ""
    except (ProseError, StudyNotFound, OSError, ValueError) as err:
        return None, f"The Methods and MIQE tables are empty: the report could not be built ({err})"


def _decisions(store: StudyStore, study_id: str, cards: Sequence[DecisionCard]) -> Table:
    from qpilot.ai.explain import KIND_TITLE
    from qpilot.web.results_views import REVIEW_TITLE, REVIEW_WORDS

    by_id = {c.id: c for c in cards}
    rows: list[tuple] = []
    for e in store.entries(study_id):
        card = by_id.get(e.card_id)
        review = e.kind == "review"
        labels = {o.id: o.label for o in card.options} if card is not None else {}
        title = (
            REVIEW_TITLE
            if review
            else KIND_TITLE.get(card.kind, card.kind)
            if card is not None
            else e.card_id
        )
        rows.append(
            (
                e.seq,
                "Sign-off" if review else "Decision Card",
                title,
                REVIEW_WORDS.get(e.option, e.option) if review else labels.get(e.option, e.option),
                labels.get(card.recommended, card.recommended) if card is not None else None,
                (e.reviewer or WHO.get(e.actor, e.actor)) if review else WHO.get(e.actor, e.actor),
                e.reason or None,
                e.at,
                e.status,
                e.hash,
            )
        )
    for p in _accepted(store, study_id):
        rows.append(
            (
                None,
                "Proposal accepted",
                _PROPOSAL_WORDS.get(p.kind, p.kind)
                + ("" if p.kind in ("curve.call_rule", "choice.axis") else f": {p.subject}"),
                _payload_words(p),
                None,
                WHO.get(p.decided_by or "", "a person"),
                p.reason or None,
                p.decided_at,
                p.status,
                p.id,
            )
        )
    for card in cards:
        if card.status in ("open", "pending_human"):
            labels = {o.id: o.label for o in card.options}
            rows.append(
                (
                    None,
                    "Open card",
                    KIND_TITLE.get(card.kind, card.kind),
                    None,
                    labels.get(card.recommended, card.recommended),
                    None,
                    None,
                    None,
                    "open" if card.status == "open" else "waiting for a person",
                    None,
                )
            )
    return Table("decisions", "Decisions", DECISION_COLUMNS, tuple(rows))


_PROPOSAL_WORDS = {
    "curve.exclude_well": "Leave a well out",
    "curve.well_call": "Call a well amplified or not",
    "curve.call_rule": "Amplification call rule",
    "prism.exclusion_reason": "Leave a value out (from Prism)",
    "prism.value_edit": "A value changed in Prism",
    "choice.axis": "Test more analysis choices",
}


def _accepted(store: StudyStore, study_id: str) -> list[Any]:
    """Accepted proposals that change the analysis after the design (well exclusions, axes...)."""
    try:
        accepted = store.proposals(study_id).accepted()
    except Exception:
        return []
    return [p for p in accepted if p.kind in _PROPOSAL_WORDS]


def _payload_words(p: Any) -> str | None:
    payload = p.effective_payload()
    if p.kind == "curve.exclude_well":
        return "left out" if payload.get("excluded") else "put back"
    if p.kind == "curve.well_call":
        return "amplified" if payload.get("amplified") else "not amplified"
    if p.kind == "prism.exclusion_reason":
        return "left out" if payload.get("action") == "exclude" else "put back"
    if p.kind == "choice.axis":
        return ", ".join(str(o) for o in payload.get("options") or ()) or None
    if p.kind == "curve.call_rule":
        from qpilot.qpcr.amp_call import RULES

        rule = RULES.get(str(payload.get("rule")))
        return rule.label if rule is not None else _text(payload.get("rule"))
    return None


def _settings(
    decided: AnalysisTables, recommended: AnalysisTables | None, result: StudyResult
) -> Table:
    rule = result.conclusion_rule
    alpha = float(rule.get("alpha", 0.05))
    fold = 2 ** float(rule.get("min_log2fc", 1.0))
    rec = recommended or decided
    rows: list[tuple] = [
        ("Analysis", decided.words, rec.words if recommended else "the same", None),
        ("Comparisons", "; ".join(c.name for c in decided.comparisons), None, None),
        (
            "Reference genes (normalisation)",
            ", ".join(decided.refs),
            ", ".join(rec.refs) if recommended else None,
            None,
        ),
        ("Normalisation", NORMALISATION_WORDS, None, None),
        ("Efficiency model", decided.efficiency, rec.efficiency if recommended else None, None),
        ("Amplification call", decided.amp_call, rec.amp_call if recommended else None, None),
        (
            "Wells with no quantity",
            decided.undetermined,
            rec.undetermined if recommended else None,
            None,
        ),
        ("Technical replicates", REPLICATE_WORDS, None, None),
        ("Test", TEST_WORDS, None, None),
        (
            "Conclusion rule",
            f"up or down only if p < {alpha:g} and the change is at least {fold:g}-fold; "
            "otherwise no call",
            None,
            None,
        ),
        (
            "Multiple testing",
            "No correction across genes (p is per gene)"
            if not any(c.correction for c in decided.comparisons)
            else "; ".join(
                f"{c.name}: {c.correction}" for c in decided.comparisons if c.correction
            ),
            None,
            None,
        ),
    ]
    for choice in decided.choices:
        rows.append(
            (
                f"Decision Card: {choice.title}",
                choice.option_label,
                choice.recommended_label,
                choice.who,
            )  # fmt: skip
        )
    return Table("settings", "Settings", SETTING_COLUMNS, tuple(rows))


def _methods(view: Any) -> Table:
    if view is None:
        return Table("methods", "Methods", METHOD_COLUMNS, note="the report could not be built")
    rows = tuple((p.title, p.text.plain) for p in view.methods.paragraphs)
    refs = tuple(
        (f"Reference [{i}]", getattr(c, "text", None) or str(c))
        for i, c in enumerate(view.methods.citations, start=1)
    )
    return Table("methods", "Methods", METHOD_COLUMNS, rows + refs)


def _miqe(view: Any) -> Table:
    if view is None:
        return Table("miqe", "MIQE 2.0", MIQE_COLUMNS, note="the report could not be built")
    words = {
        "met": "the data show it",
        "not_met": "not met",
        "not_applicable": "not applicable",
        "cannot_tell": "cannot tell from the data",
    }
    rows = tuple(
        (
            i.id,
            i.section,
            i.label,
            words.get(i.status, i.status),
            bool(i.attest),
            i.evidence.plain if i.evidence is not None else None,
        )
        for i in view.miqe.items
    )
    return Table("miqe", "MIQE 2.0", MIQE_COLUMNS, rows)


def _versions() -> dict[str, str]:
    from qpilot.core.record import versions

    return versions()


def all_tables(tables: StudyTables, record_id: str | None = None) -> list[Table]:
    """Every table in the order the exports write them (as decided first, About last)."""
    out = [tables.decided.results, tables.decided.per_unit, tables.decided.per_well]
    if tables.recommended is not None:
        out += [tables.recommended.results, tables.recommended.per_unit]
    out += [tables.decisions, tables.settings, tables.methods, tables.miqe]
    out.append(tables.about(record_id))
    return out


__all__: Sequence[str] = (
    "AS_DECIDED",
    "BASES",
    "BASIS_LABEL",
    "BASIS_WORDS",
    "RECOMMENDED",
    "AnalysisTables",
    "Basis",
    "Choice",
    "Column",
    "Comparison",
    "StudyTables",
    "Table",
    "all_tables",
    "build_tables",
    "comparisons",
    "study_tables",
)
