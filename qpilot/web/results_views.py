"""Results views for the page: the study, each gene, the flip matrix, the Decision Cards.

Built from the store (``results.json``, ``cards.json``, the decision chain and ``grid.csv``) and
the structured helpers of :mod:`qpilot.app_state`; never HTML. Numbers are returned raw (the
page formats them) and every sentence that cites a number says which fact it is
(:class:`~qpilot.web.contract.FactText`).

The grid holds every analysis the robustness check ran (one row per analysis and gene). The
planned analysis is the grid cell that reproduces the stored contrasts exactly; a card option is
the grid option that reproduces that option's stored consequences. Both are found by value, so a
view never assumes how the engine numbered its options.
"""

from __future__ import annotations

import json
import math
import re
import threading
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from qpilot.core.store import StudyNotFound, StudyStore
from qpilot.schemas import DecisionCard, DecisionEntry, Fact, StudyResult
from qpilot.web.contract import (
    AskedAgain,
    AtChoices,
    AuditBadge,
    AutonomyChange,
    AutonomyView,
    AxisOptionView,
    AxisView,
    CardOptionView,
    CardPlace,
    CardsView,
    CardView,
    CarriedFrom,
    ComparisonTab,
    DecisionEntryView,
    DecisionsView,
    FactRef,
    FactText,
    FlipOption,
    FlipRow,
    FlipsView,
    GeneGrid,
    GeneRow,
    GeneView,
    GenormView,
    GroupCount,
    NotCompared,
    NotComparedReason,
    OptionEffect,
    PendingRequest,
    ResultsSummary,
    ResultsView,
    RuleView,
    StaleAttempt,
    TextSegment,
    WithheldGene,
)

KIND_DIMENSION = {
    "reference_set": "refs",
    "group_cutoff": "cut",
    "undetermined": "undetermined",
    "amp_call": "amp_call",
    "numbers.efficiency_model": "efficiency",
}
DIMENSION_TITLE = {
    "refs": "Which control genes to normalise to",
    "cut": "Where to cut the comparison groups",
    "undetermined": "What to do with wells that never amplified",
    "amp_call": "Which curves count as amplified",
    "efficiency": "Which efficiency turns Cq into quantity",
}
UNDO_PREFIX = "Undo:"
TOLERANCE = 1e-9
MAX_GRIDS = 4
IDX = "__idx"
CONCLUSIONS = ("up", "down", "none")


# ---- facts in sentences ----------------------------------------------------------------------


NNBSP = "\u202f"  # the page writes percentages as "65 %" with a narrow no-break space


def shown(fact: Fact) -> str:
    """A fact as the page writes it: the engine's rendering, a percent sign set apart."""
    from qpilot.core.facts import render_fact

    text = render_fact(fact)
    if fact.fmt.endswith("%}") and text.endswith("%") and not text.endswith(" %"):
        text = text[:-1].rstrip() + NNBSP + "%"
    return text


def fact_ref(fact: Fact) -> FactRef:
    """A fact as the page cites it."""
    return FactRef(id=fact.id, text=shown(fact), value=fact.value, unit=fact.unit, path=fact.path)


def fact_text(tokens: str, facts: Mapping[str, Fact], source: str = "template") -> FactText:
    """Split ``{{fact}}`` tokens into plain text and cited numbers."""
    from qpilot.core.validator import TOKEN

    segments: list[TextSegment] = []
    cited: dict[str, FactRef] = {}
    last = 0
    for match in TOKEN.finditer(tokens):
        if match.start() > last:
            segments.append(TextSegment(text=tokens[last : match.start()]))
        fid = match.group(1)
        fact = facts.get(fid)
        if fact is None:  # validated texts never cite an unknown fact; shown as its id if so
            segments.append(TextSegment(text=fid))
        else:
            segments.append(TextSegment(text=shown(fact), fact=fid))
            cited.setdefault(fid, fact_ref(fact))
        last = match.end()
    if last < len(tokens):
        segments.append(TextSegment(text=tokens[last:]))
    plain = "".join(s.text for s in segments)
    return FactText(
        plain=plain,
        segments=segments,
        facts=list(cited.values()),
        source="model" if source == "model" else "template",
    )


OLD_WORDS = (
    (
        "holds in at least 80 % of the reasonable analyses.",
        "holds in at least 80 % of the {n} analyses qPilot checks.",
    ),
    (
        "holds in fewer than 80 % of the reasonable analyses.",
        "holds in fewer than 80 % of the {n} analyses qPilot checks.",
    ),
    (
        "No combination of the reasonable choices flips this conclusion.",
        "No combination of the choices qPilot checks flips this conclusion.",
    ),
)


#: A marker split's design variable in a stored note ("derived from the data (MYCN_high)").
_DERIVED_GROUPS = re.compile(r"(Groups are derived from the data \()([^()\s]+?)_high\)")


def reworded(text: str, n_cells: int | None) -> str:
    """A confidence reason stored before the wording named qPilot's grid, in today's words.

    A stored note that names the groups by the design's variable (``MYCN_high``) names them as
    every page does (``MYCN-high vs rest``); the engine's stored bytes are unchanged.
    """
    for old, new in OLD_WORDS:
        if old in text and (n_cells or "{n}" not in new):
            text = text.replace(old, new.format(n=n_cells))
    return _DERIVED_GROUPS.sub(lambda m: f"{m[1]}{m[2]}-high vs rest)", text)


def grade_now(grade: Any, n_cells: int | None) -> Any:
    """A stored Grade with its reasons and notes in today's words (numbers unchanged)."""
    if grade is None:
        return None
    return grade.model_copy(
        update={
            "reasons": [reworded(r, n_cells) for r in grade.reasons],
            "checks": [
                c.model_copy(update={"note": reworded(c.note, n_cells)}) for c in grade.checks
            ],
        }
    )


def plain_text(text: str) -> FactText:
    """A sentence with no cited number."""
    return FactText(plain=text, segments=[TextSegment(text=text)], facts=[])


# ---- the study's session and the blind rule --------------------------------------------------


def session_of_study(store: StudyStore, study_id: str) -> str | None:
    """The Studio session a study was analysed from (None for a study made outside one)."""
    sessions = store.root / "sessions"
    if not sessions.is_dir():
        return None
    for folder in sessions.iterdir():
        meta = folder / "studio.json"
        if len(folder.name) != 64 or not meta.is_file():
            continue
        try:
            studies = json.loads(meta.read_text(encoding="utf-8")).get("studies") or {}
        except (OSError, ValueError):
            continue
        if study_id in studies:
            return folder.name[:12]
    return None


# ---- a person's decisions carried from an earlier analysis of the same file -----------------


class CarryLinks:
    """Reads the carried entries of one study, each earlier study's chain read once."""

    def __init__(self, store: StudyStore, input_sha256: str) -> None:
        self.store = store
        self.input_sha256 = input_sha256
        self._chains: dict[str, dict[str, DecisionEntry]] = {}

    def _chain(self, study_id: str) -> dict[str, DecisionEntry]:
        if study_id not in self._chains:
            try:
                same = self.store.get(study_id).input_sha256 == self.input_sha256
                entries = self.store.entries(study_id) if same else []
            except (StudyNotFound, OSError, ValueError):
                entries = []
            self._chains[study_id] = {e.hash: e for e in entries}
        return self._chains[study_id]

    def of(self, entry: DecisionEntry | None) -> CarriedFrom | None:
        """Where a person's carried entry came from, its link checked (None for any other)."""
        from qpilot.core.decisions import carried_from

        if entry is None or entry.actor != "human" or entry.status != "applied":
            return None
        origin = carried_from(entry.reason)
        if origin is None:
            return None
        there = self._chain(origin.study_id).get(origin.entry_hash)
        made = (there.card_id, there.option, there.actor, there.status) if there else None
        found = made == (entry.card_id, entry.option, "human", "applied")
        return CarriedFrom(
            study_id=origin.study_id,
            entry_hash=origin.entry_hash,
            reason=origin.reason,
            found=found,
            decided_at=there.at if found and there is not None else None,
        )


def carry_report(store: StudyStore, study_id: str) -> dict[str, Any] | None:
    """The session's report of the latest carry of a person's decisions into this study."""
    sid = session_of_study(store, study_id)
    if sid is None:
        return None
    try:
        meta = json.loads((store.find_session(sid) / "studio.json").read_text(encoding="utf-8"))
    except (StudyNotFound, OSError, ValueError):
        return None
    report = (meta.get("carried") or {}).get(study_id)
    return report if isinstance(report, dict) else None


def asked_again_of(
    store: StudyStore, card: DecisionCard, report: dict[str, Any] | None
) -> AskedAgain | None:
    """A person's earlier decision on this card that was asked again, while no person decided it."""
    why = ((report or {}).get("asked_again") or {}).get(card.id)
    if not why or card.decided_by == "human":
        return None
    source = str(report.get("source") or "") if report else ""
    option = None
    label = None
    try:
        earlier = store.card(source, card.id)
        option = earlier.decision
        label = next((o.label for o in earlier.options if o.id == option), option)
    except (StudyNotFound, KeyError, OSError, ValueError):
        pass
    return AskedAgain(study_id=source, option=option, option_label=label, why=str(why))


# ---- the grid: every analysis, the planned one, and the cards' options ----------------------


@dataclass
class Grid:
    """A study's analysis grid, read once per change of ``grid.csv``."""

    frame: pd.DataFrame
    dimensions: list[str]
    options: dict[str, list[str]]  # dimension -> option value (as text) by index
    planned: dict[str, int] | None  # dimension -> the planned option's index
    by_item: dict[str, pd.DataFrame] = field(default_factory=dict)

    def item(self, gene: str) -> pd.DataFrame:
        """The grid rows of one gene."""
        if gene not in self.by_item:
            self.by_item[gene] = self.frame[self.frame["item"] == gene]
        return self.by_item[gene]

    def one_at_a_time(self, dimension: str) -> pd.DataFrame:
        """Rows where every other dimension is at its planned option."""
        assert self.planned is not None
        mask = pd.Series(True, index=self.frame.index)
        for dim, idx in self.planned.items():
            if dim != dimension:
                mask &= self.frame[dim + IDX] == idx
        return self.frame[mask]

    def cell(self, choice: Mapping[str, int]) -> pd.DataFrame:
        """Rows of one analysis (every dimension given)."""
        mask = pd.Series(True, index=self.frame.index)
        for dim, idx in choice.items():
            mask &= self.frame[dim + IDX] == idx
        return self.frame[mask].set_index("item")


_grid_lock = threading.Lock()
_grids: OrderedDict[tuple[str, int], Grid] = OrderedDict()


def load_grid(store: StudyStore, result: StudyResult) -> Grid | None:
    """The study's grid with its planned cell found by value (None when there is no grid)."""
    path = store.workspace(result.study_id) / "grid.csv"
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return None
    key = (str(path), mtime)
    with _grid_lock:
        cached = _grids.get(key)
        if cached is not None:
            return cached
    frame = pd.read_csv(path)
    dims = [c[: -len(IDX)] for c in frame.columns if c.endswith(IDX)]
    options: dict[str, list[str]] = {}
    for dim in dims:
        pairs = frame[[dim + IDX, dim]].drop_duplicates(dim + IDX).sort_values(dim + IDX)
        options[dim] = [str(v) for v in pairs[dim]]
    grid = Grid(frame=frame, dimensions=dims, options=options, planned=None)
    grid.planned = _planned(grid, result)
    with _grid_lock:
        _grids[key] = grid
        while len(_grids) > MAX_GRIDS:
            _grids.popitem(last=False)
    return grid


def _expected_values(result: StudyResult) -> dict[str, str]:
    """The planned option of each dimension as the engine defines it (as grid text)."""
    out = {"refs": "|".join(result.design.refs_primary), "undetermined": "drop"}
    if "f_group_a" not in result.facts:
        out["cut"] = str(result.design.cut)
    if "f_axis_efficiency" in result.facts:  # the efficiency models are tested
        from qpilot.qpcr.axes.efficiency import PRIMARY

        out["efficiency"] = PRIMARY
    amp = result.facts.get("f_amp_primary")
    if amp is not None:  # the fact holds the rule's label; the grid holds its id
        from qpilot.qpcr.amp_call import RULES

        value = str(amp.value)
        out["amp_call"] = next(
            (rid for rid, rule in RULES.items() if value in (rid, rule.label)), value
        )
    return out


def _planned(grid: Grid, result: StudyResult) -> dict[str, int] | None:
    """The grid cell whose numbers are the stored contrasts (None if none matches).

    Several cells can give the same numbers (a choice that changes nothing on this data); the
    one whose options are the engine's planned ones is taken then.
    """
    idx_cols = [d + IDX for d in grid.dimensions]
    candidates: set[tuple[int, ...]] | None = None
    for gene, contrast in result.contrasts.items():
        rows = grid.item(gene)
        hit = rows[(rows["log2fc"] - contrast.log2fc).abs() <= TOLERANCE]
        combos = {tuple(int(x) for x in r) for r in hit[idx_cols].to_numpy()}
        candidates = combos if candidates is None else candidates & combos
        if candidates is not None and len(candidates) <= 1:
            break
    if not candidates:
        return None
    expected = _expected_values(result)

    def agreement(combo: tuple[int, ...]) -> int:
        return sum(
            1
            for dim, idx in zip(grid.dimensions, combo, strict=True)
            if expected.get(dim) == grid.options[dim][idx]
        )

    ranked = sorted(candidates, key=lambda c: (-agreement(c), c))
    if len(ranked) > 1 and agreement(ranked[0]) == agreement(ranked[1]):
        return None  # cannot tell which analysis was planned
    return dict(zip(grid.dimensions, ranked[0], strict=True))


def card_options(grid: Grid, cards: Sequence[DecisionCard]) -> dict[str, dict[int, tuple]]:
    """Dimension -> grid option index -> (card id, option id, label) for every card option."""
    out: dict[str, dict[int, tuple]] = {}
    if grid.planned is None:
        return out
    for card in cards:
        dim = KIND_DIMENSION.get(card.kind)
        if dim not in grid.dimensions:
            continue
        rows = grid.one_at_a_time(dim)
        for option in card.options:
            matches: set[int] | None = None
            for gene, effect in option.per_gene.items():
                sub = rows[rows["item"] == gene]
                hit = set(sub.loc[(sub["log2fc"] - effect.log2fc).abs() <= TOLERANCE, dim + IDX])
                matches = hit if matches is None else matches & hit
            if matches and len(matches) > 1:  # options that change nothing here: by name
                named = {i for i in matches if grid.options[dim][int(i)] == option.id}
                if option.id == card.recommended:
                    named |= {i for i in matches if int(i) == grid.planned[dim]}
                matches = named
            if matches and len(matches) == 1:
                (idx,) = matches
                out.setdefault(dim, {})[int(idx)] = (card.id, option.id, option.label)
    return out


def current_cell(grid: Grid, cards: Sequence[DecisionCard], mapped: Mapping) -> dict[str, int]:
    """The grid cell in use now: each card's applied option, the planned one elsewhere."""
    assert grid.planned is not None
    choice = dict(grid.planned)
    for card in cards:
        dim = KIND_DIMENSION.get(card.kind)
        if dim is None or card.decision is None:
            continue
        for idx, (card_id, option_id, _) in mapped.get(dim, {}).items():
            if card_id == card.id and option_id == card.decision:
                choice[dim] = idx
    return choice


def at_choices(grid: Grid | None, cards: Sequence[DecisionCard]) -> pd.DataFrame | None:
    """Every gene's row at the options in use now, when they are not the planned ones."""
    if grid is None or grid.planned is None:
        return None
    choice = current_cell(grid, cards, card_options(grid, cards))
    return None if choice == grid.planned else grid.cell(choice)


def _number(value: Any) -> float | None:
    """A finite number from the grid, or None where the engine computed none."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _text(value: Any) -> str | None:
    """A conclusion from the grid, or None where there is none."""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    text = str(value)
    return text if text in CONCLUSIONS else None


def option_label(dimension: str, value: str) -> str:
    """Words for a grid option no card names."""
    if dimension == "efficiency":
        from qpilot.qpcr.axes import AxisError, get_axis

        try:
            return get_axis(dimension).option(value).label
        except AxisError:
            return value
    if dimension == "refs":
        return " + ".join(value.split("|"))
    if dimension == "cut":
        try:
            return f"top {float(value):.0%}".replace("%", " %")
        except ValueError:
            return value
    return value


# ---- results ---------------------------------------------------------------------------------


def _verdicts(store: StudyStore, study_id: str) -> tuple[dict[str, str], dict[str, str]]:
    """The audit's verdict per gene and the verdicts' labels (empty without an audit)."""
    from qpilot.web.views import audit_dir

    folder = audit_dir(store, study_id)
    if folder is None or not (folder / "explain.json").exists():
        return {}, {}
    try:
        explain = json.loads((folder / "explain.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}
    verdicts = {g: str(e.get("verdict")) for g, e in explain.items() if isinstance(e, dict)}
    try:
        from qsim.app import VERDICT_LABEL

        labels = {k: str(v) for k, v in VERDICT_LABEL.items()}
    except Exception:  # the simulator is not installed: the verdict's own words
        labels = {v: v for v in verdicts.values()}
    return verdicts, labels


def audit_badge(store: StudyStore, study_id: str) -> AuditBadge:
    """Whether an audit exists, its verdict counts and whether it is of the chain head of now."""
    from qpilot.web.views import audit_dir

    folder = audit_dir(store, study_id)
    if folder is None:
        return AuditBadge(status="none")
    try:
        manifest = json.loads((folder / "audit_manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return AuditBadge(status="none")
    head = manifest.get("chain_head")
    try:
        summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
        reasonable = ((summary.get("multiverse") or {}).get("defensible") or {}).get("cells")
    except (OSError, ValueError, AttributeError):
        reasonable = None
    scope = manifest.get("scope") or {}
    varied = list((scope.get("decisions") or {}).keys())
    if scope.get("reference_sets") and "refs" not in varied:
        varied.insert(varied.index("cut") if "cut" in varied else len(varied), "refs")
    analyses = manifest.get("analyses")
    return AuditBadge(
        status="ready",
        verdict_counts={str(k): int(v) for k, v in (manifest.get("verdict_counts") or {}).items()},
        chain_head=head,
        current=bool(head) and head == store.chain_head(study_id),
        analyses=analyses if isinstance(analyses, int) else None,
        reasonable=reasonable if isinstance(reasonable, int) else None,
        decisions=[str(d) for d in varied],
    )


_nc_lock = threading.Lock()
_not_compared: OrderedDict[tuple[str, int], NotCompared | None] = OrderedDict()


def not_compared(
    store: StudyStore, result: StudyResult, comparison: str | None = None
) -> NotCompared | None:
    """The study's samples in neither group, by reason, from the engine's model of the study.

    The model is rebuilt from the cached curve analysis (about a second on the demo) once per
    study and kept; None when the input file is not there to rebuild it. ``comparison`` is the
    comparison shown in a study with several: units of its other groups are named as such.
    """
    path = store.workspace(result.study_id) / "results.json"
    try:
        key = (str(path), path.stat().st_mtime_ns, comparison)
    except OSError:
        return None
    with _nc_lock:
        if key in _not_compared:
            return _not_compared[key]
    value = _rebuild_not_compared(store, result, comparison)
    with _nc_lock:
        _not_compared[key] = value
        while len(_not_compared) > MAX_GRIDS:
            _not_compared.popitem(last=False)
    return value


def _rebuild_not_compared(
    store: StudyStore, result: StudyResult, comparison: str | None = None
) -> NotCompared | None:
    from qpilot.qpcr.curves import analyse_study
    from qpilot.qpcr.designs import unit_groups
    from qpilot.qpcr.study import StudySettings, build_model

    source = store.source(result.study_id)
    if source is None:
        return None
    try:
        design = store.design(result.study_id)
        settings = StudySettings.from_design(design) if design is not None else StudySettings()
        curves = analyse_study(source, settings.experiment_id, settings.candidates, settings.curves)
        model = build_model(curves, settings)
    except Exception:  # a study that cannot be rebuilt here: the page says only the counts
        return None
    matrix = model.matrix
    grouped = model.high | model.rest
    elsewhere: dict[str, str] = {}  # unit -> its group, compared in another comparison
    specs = {spec.id: spec for spec in model.space.comparisons}
    if specs and settings.design is not None:
        spec = specs.get(comparison or "", model.space.comparisons[0])
        grouped = spec.group_a | spec.group_b
        compared = {g for s in specs.values() for g in s.labels}
        elsewhere = {u: g for u, g in unit_groups(settings.design).items() if g in compared}
    refs = [r for r in model.space.primary["refs"] if r in matrix.columns]
    marker = None if model.labels is not None else settings.marker
    by_reason: dict[str, list[str]] = {}
    for sample in matrix.index:
        if sample in grouped:
            continue
        row = matrix.loc[sample]
        missing = [r for r in refs if pd.isna(row[r])]
        if marker is not None and marker in row.index and pd.isna(row[marker]):
            reason = f"no value for the marker gene {marker}"
        elif missing:
            names = ", ".join(missing)
            reason = f"no value for the control gene{'s' * (len(missing) > 1)} {names}"
        elif str(sample) in elsewhere:
            reason = f"in group {elsewhere[str(sample)]}, compared in another comparison"
        elif model.labels is not None:
            reason = "in neither group of the confirmed design"
        else:
            reason = "not ranked by the marker (no reason recorded)"
        by_reason.setdefault(reason, []).append(str(sample))
    reasons = [
        NotComparedReason(reason=r, n=len(v), samples=sorted(v))
        for r, v in sorted(by_reason.items(), key=lambda kv: -len(kv[1]))
    ]
    return NotCompared(n=sum(r.n for r in reasons), reasons=reasons)


def withheld(result: StudyResult) -> list[WithheldGene]:
    """Genes the engine withheld (``f_withheld_*`` facts), with the reason in words."""
    out = []
    for fid, fact in result.facts.items():
        if fid.startswith("f_withheld_") and fact.path.startswith("withheld."):
            out.append(WithheldGene(gene=fact.path[len("withheld.") :], reason=str(fact.value)))
    return sorted(out, key=lambda w: w.gene)


def headline_genes(
    result: StudyResult, cards: Sequence[DecisionCard], store: StudyStore | None = None
) -> list[str]:
    """The design's headline genes, lead gene first (else the genes the cards show)."""
    from qpilot.qpcr.designs import HEADLINE_GENES

    order: tuple[str, ...] = ()
    if store is not None:
        try:
            design = store.design(result.study_id)
        except (StudyNotFound, OSError, ValueError):
            design = None
        if design is not None and design.headline:
            order = tuple(design.headline)
        elif design is None:
            order = HEADLINE_GENES  # a study analysed without a design: the demo's
    shown = list(cards[0].options[0].per_gene) if cards and cards[0].options else []
    if order:
        ranked = [g for g in order if g in result.contrasts and (not shown or g in shown)]
        if ranked:
            return ranked + [g for g in shown if g not in ranked and g in result.contrasts]
    return [g for g in shown if g in result.contrasts]


def groups(result: StudyResult) -> list[GroupCount]:
    """The compared group and the reference group, with their sizes."""
    facts = result.facts
    design = result.design
    if "f_group_a" in facts and "f_group_b" in facts:
        return [
            GroupCount(label=str(facts["f_group_a"].value), n=design.n_hi),
            GroupCount(label=str(facts["f_group_b"].value), n=design.n_lo),
        ]
    from qpilot.qpcr.design import marker_group_names

    a, b = marker_group_names(design.group_var)
    return [GroupCount(label=a, n=design.n_hi), GroupCount(label=b, n=design.n_lo)]


def _row(
    gene: str,
    result: StudyResult,
    headline: set[str],
    at: pd.DataFrame | None,
    verdicts: Mapping[str, str],
    labels: Mapping[str, str],
    extra: Mapping[str, tuple[float | None, float | None]] | None = None,
) -> GeneRow:
    contrast = result.contrasts[gene]
    p_adjusted, q = (extra or {}).get(gene, (None, None))
    robust = result.robustness.get(gene)
    grade = result.confidence.get(gene)
    yours = None
    if at is not None and gene in at.index:
        r = at.loc[gene]
        yours = AtChoices(
            fc=float(r["fc"]),
            log2fc=float(r["log2fc"]),
            p=_number(r["p"]),
            conclusion=str(r["conclusion"]),  # type: ignore[arg-type]
            differs=str(r["conclusion"]) != contrast.conclusion,
        )
    verdict = verdicts.get(gene)
    return GeneRow(
        gene=gene,
        headline=gene in headline,
        conclusion=contrast.conclusion,
        fc=contrast.fc,
        log2fc=contrast.log2fc,
        ci=(float(contrast.ci[0]), float(contrast.ci[1])),
        p=contrast.p,
        n_hi=contrast.n_hi,
        n_lo=contrast.n_lo,
        holds=robust.holds if robust else None,
        n_cells=robust.n_cells if robust else 0,
        level=grade.level if grade else None,
        reasons=[reworded(r, robust.n_cells if robust else None) for r in grade.reasons]
        if grade
        else [],
        min_flip_changes=grade.min_flip_changes if grade else None,
        flips_by=sorted(d for d, v in (robust.impact if robust else {}).items() if v.get("flips")),
        efficiency=result.efficiency.get(gene),
        at_your_choices=yours,
        verdict=verdict,
        verdict_label=labels.get(verdict) if verdict else None,
        p_adjusted=p_adjusted,
        q=q,
    )


AXIS_WORDS = {
    "off": "Not tested in qPilot's grid: every quantity uses LinRegPCR's mean efficiency of each "
    "assay on each plate. Testing the other efficiency models adds them as one more choice of the "
    "grid; the analysis in use stays the same until a person decides otherwise. The robustness "
    "audit varies the efficiency model on its own, so its verdicts already include it; qPilot's "
    "grid tests it only when you ask here.",
    "swept": "Tested as one more choice of the grid: changing only the efficiency model changes "
    "{{f_n_flipped_efficiency}} of {{f_n_genes}} calls. Its Decision Card says what each model "
    "changes; the analysis in use stays LinRegPCR's mean efficiency until a person decides.",
    "screened_out": "Tried alone first: no efficiency model changes a call, and the largest "
    "move of a log2 fold change is {{f_screen_efficiency_dlog2fc}}, under the screening "
    "threshold, so the grid keeps LinRegPCR's mean efficiency and raises no card.",
    "not_applicable": "None of the efficiency models asked for applies to this study, so the "
    "grid keeps LinRegPCR's mean efficiency.",
    "single_option": "Only LinRegPCR's mean efficiency was asked for, so nothing else is tested.",
}
EFFICIENCY_COMMAND = "qpilot run --efficiency all"


def axis_views(
    store: StudyStore,
    result: StudyResult,
    cards: Sequence[DecisionCard],
    session: str | None,
) -> list[AxisView]:
    """The further choices the grid can test on request (today: the efficiency models).

    Read from the study's facts and its stored design: which options were asked for, which
    apply, what each one alone changes, and the card it raised. Every number is a fact.
    """
    from qpilot.core.facts import slug
    from qpilot.qpcr.axes import get_axis

    axis = get_axis("efficiency")
    facts = result.facts
    try:
        design = store.design(result.study_id)
    except (OSError, ValueError):
        design = None
    asked = tuple((design.axes or {}).get(axis.name, ())) if design is not None else ()
    status_fact = facts.get(f"f_axis_{axis.name}")
    status = str(status_fact.value) if status_fact is not None else "off"
    if status not in AXIS_WORDS:
        status = "off"
    options = []
    for option in axis.catalogue:
        s = slug(option.id)
        why = facts.get(f"f_axis_{axis.name}_unavailable_{s}")
        flips = facts.get(f"f_n_flipped_eff_{s}") or facts.get(f"f_screen_{axis.name}_flips_{s}")
        primary = option.tier == "primary"
        tested = status != "off" and (primary or option.id in asked) and why is None
        options.append(
            AxisOptionView(
                id=option.id,
                label=option.label,
                tier=option.tier,
                primary=primary,
                tested=tested,
                flips=fact_ref(flips) if flips is not None and not primary else None,
                unavailable=str(why.value) if why is not None else None,
            )
        )
    try:
        text = fact_text(AXIS_WORDS[status], facts)
    except (KeyError, TypeError, ValueError):
        text = plain_text(AXIS_WORDS["off"])
    notes = []
    if "f_n_eff_excluded_per_well" in facts:
        notes.append(
            fact_text(
                "With each well's own efficiency, {{f_n_eff_excluded_per_well}} study wells "
                "whose own efficiency is outside LinRegPCR's valid range are left out.",
                facts,
            )
        )
    fallback = facts.get("f_eff_std_fallback")
    if fallback is not None and str(fallback.value) not in ("", "none"):
        notes.append(
            fact_text(
                "Amplicons without a dilution series keep LinRegPCR's mean efficiency under the "
                "dilution-series model: {{f_eff_std_fallback}}.",
                facts,
            )
        )
    card = next((c for c in cards if KIND_DIMENSION.get(c.kind) == axis.name), None)
    return [
        AxisView(
            name=axis.name,
            title=axis.title,
            status=status,  # type: ignore[arg-type]
            text=text,
            options=options,
            card_id=card.id if card is not None else None,
            notes=notes,
            can_propose=session is not None,
            command=None if session is not None else EFFICIENCY_COMMAND,
        )
    ]


def _shown(
    store: StudyStore, study_id: str, comparison: str | None
) -> tuple[StudyResult, StudyResult, Any, Any, Any]:
    """``(stored result, result as shown, outcome, primary grid, grid as shown)``.

    ``comparison`` picks one comparison of a study with several (``None``: the primary, as
    stored); see :mod:`qpilot.web.compare_views`.
    """
    from qpilot.web import compare_views as cv

    stored = store.get(study_id)
    outcome = cv.outcome_of(stored, comparison)
    grid = load_grid(store, stored)
    if outcome is None or outcome.primary:
        return stored, stored, outcome, grid, grid
    shown_grid = cv.comparison_grid(store, study_id, outcome.id, grid)
    return stored, cv.shown_result(stored, outcome), outcome, grid, shown_grid


def results_view(
    store: StudyStore, study_id: str, session: str | None = None, comparison: str | None = None
) -> ResultsView:
    """Everything the Results section shows (``comparison``: one of several; default primary)."""
    from qpilot.app_state import design_line
    from qpilot.explain.templates import TemplateError, render_template
    from qpilot.qpcr.contrast import ConclusionRule
    from qpilot.web import compare_views as cv

    stored, result, outcome, primary_grid, grid = _shown(store, study_id, comparison)
    head, cards, pending = store.snapshot(study_id)
    headline = headline_genes(result, cards, store)
    at = cv.at_choices_in(primary_grid, grid, cards)
    verdicts, labels = _verdicts(store, study_id)
    extra = cv.extra_columns(stored, outcome)
    rows = [_row(g, result, set(headline), at, verdicts, labels, extra) for g in result.contrasts]
    try:
        summary_text = fact_text(render_template("summary_v1", result.facts).tokens, result.facts)
    except (KeyError, TemplateError):
        summary_text = None
    if result is not stored:  # the summary sentence describes the first comparison
        summary_text = None
    rule = ConclusionRule(**result.conclusion_rule)
    genorm = result.genorm
    design = result.design
    counts = {c: sum(1 for r in rows if r.conclusion == c) for c in CONCLUSIONS}
    levels: dict[str, int] = {}
    for r in rows:
        if r.level:
            levels[r.level] = levels.get(r.level, 0) + 1
    return ResultsView(
        study_id=study_id,
        session=session,
        input_sha256=result.input_sha256,
        summary=ResultsSummary(
            n_plates=result.n_plates,
            n_reactions=result.n_reactions,
            n_samples=result.n_samples,
            n_genes=len(result.contrasts),
            mode="groups" if "f_group_a" in result.facts else "marker_split",
            group_var=design.group_var,
            groups=groups(result),
            cut=None if "f_group_a" in result.facts else design.cut,
            design_line=design_line(result),
            text=summary_text,
            not_compared=not_compared(store, stored, outcome.id if outcome is not None else None),
        ),
        rule=RuleView(
            alpha=rule.alpha,
            min_log2fc=rule.min_log2fc,
            min_fold=2**rule.min_log2fc,
            text=cv.rule_words(stored, rule),
        ),
        references=GenormView(
            used=list(design.refs_primary),
            candidates=list(genorm.M_initial),
            m=dict(genorm.M_initial),
            order=list(genorm.order),
            v=dict(genorm.V),
            recommended=list(genorm.recommended),
            cutoff_m=genorm.cutoff_M,
            cutoff_v=genorm.cutoff_V,
            stable=[g for g, m in genorm.M_initial.items() if m < genorm.cutoff_M],
        ),
        genes=rows,
        withheld=withheld(result) + _not_tested(outcome),
        headline=headline,
        counts=counts,
        levels=levels,
        choices={c.id: c.decision for c in cards if c.decision is not None},
        cards_waiting=sum(1 for c in cards if c.status in ("open", "pending_human")),
        pending_requests=len(pending),
        head=head,
        audit=audit_badge(store, study_id),
        axes=axis_views(store, result, cards, session),
        comparison=outcome.id if outcome is not None else _primary_id(stored),
        comparisons=[ComparisonTab(**tab) for tab in cv.tabs(stored)],
    )


def _primary_id(result: StudyResult) -> str | None:
    """The primary comparison's id in a study with several (None otherwise)."""
    return result.comparisons.comparisons[0].id if result.comparisons is not None else None


def _not_tested(outcome: Any) -> list[WithheldGene]:
    """Genes a (non-primary) comparison cannot test, as withheld genes of that comparison."""
    if outcome is None or outcome.primary:
        return []
    return [WithheldGene(gene=g, reason=r) for g, r in sorted(outcome.not_tested.items())]


# ---- the flip matrix -------------------------------------------------------------------------


def _flip_rows(
    result: StudyResult,
    grid: Grid | None,
    cards: Sequence[DecisionCard],
    genes: Sequence[str],
    primary: Grid | None = None,
) -> list[FlipRow]:
    """Decision rows for ``genes``; ``primary`` is the grid the cards' options are read from.

    The cards describe the primary comparison, so for another comparison's ``grid`` the cards'
    options and the options in use are found in the primary grid (the same analyses).
    """
    by_dim = {KIND_DIMENSION.get(c.kind): c for c in cards}
    source = grid if primary is None else primary
    mapped = card_options(source, cards) if source is not None else {}
    choice = current_cell(source, cards, mapped) if source is not None and source.planned else None
    dims: list[str] = []
    for gene in genes:
        for dim in result.robustness[gene].impact:
            if dim not in dims:
                dims.append(dim)
    rows: list[FlipRow] = []
    planned = [result.contrasts[g].conclusion for g in genes]
    for dim in dims:
        impacts = [result.robustness[g].impact.get(dim, {}) for g in genes]
        card = by_dim.get(dim)
        options: list[FlipOption] = []
        if grid is not None and grid.planned is not None and dim in grid.dimensions:
            sub = grid.one_at_a_time(dim)
            for idx, value in enumerate(grid.options[dim]):
                part = sub[sub[dim + IDX] == idx].set_index("item")
                conclusion = [_text(part.loc[g, "conclusion"]) if g in part.index else None
                              for g in genes]  # fmt: skip
                log2fc = [_number(part.loc[g, "log2fc"]) if g in part.index else None
                          for g in genes]  # fmt: skip

                card_option = mapped.get(dim, {}).get(idx)
                options.append(
                    FlipOption(
                        value=value,
                        label=card_option[2] if card_option else option_label(dim, value),
                        card_option=card_option[1] if card_option else None,
                        planned=idx == grid.planned[dim],
                        chosen=choice is not None and choice.get(dim) == idx,
                        conclusion=conclusion,  # type: ignore[arg-type]
                        log2fc=log2fc,
                        flips=[
                            c is not None and c != p
                            for c, p in zip(conclusion, planned, strict=True)
                        ],
                    )
                )
        flips = [bool(i.get("flips")) for i in impacts]
        rows.append(
            FlipRow(
                dimension=dim,
                title=DIMENSION_TITLE.get(dim, dim),
                card_id=card.id if card else None,
                status=card.status if card else None,
                flips=flips,
                max_delta_log2fc=[float(i.get("max_delta_log2fc", 0.0)) for i in impacts],
                n_flipped=sum(flips),
                options=options,
            )
        )
    return rows


def flips_view(store: StudyStore, study_id: str, comparison: str | None = None) -> FlipsView:
    """Decisions × genes: where a decision alone flips a gene's call, and by how much."""
    stored, result, outcome, primary_grid, grid = _shown(store, study_id, comparison)
    cards = store.cards(study_id)
    genes = [g for g in result.contrasts if g in result.robustness]
    return FlipsView(
        study_id=study_id,
        genes=genes,
        planned=[result.contrasts[g].conclusion for g in genes],
        rows=_flip_rows(result, grid, cards, genes, primary_grid),
        comparison=outcome.id if outcome is not None else _primary_id(stored),
    )


# ---- Decision Cards --------------------------------------------------------------------------


def undo_target(entries: Iterable[DecisionEntry], card_id: str) -> str | None:
    """The option Undo restores: one step back through the card's history, or ``None``.

    Replays the card's applied entries as a stack: an entry whose reason starts with ``Undo:``
    pops the step it undid; a repeated choice is not a new step (as the earlier page did).
    """
    stack: list[str] = []
    for entry in entries:
        if entry.card_id != card_id or entry.status not in ("applied", "auto"):
            continue
        if entry.reason.startswith(UNDO_PREFIX):
            if stack:
                stack.pop()
            continue
        if not stack or stack[-1] != entry.option:
            stack.append(entry.option)
    return stack[-2] if len(stack) >= 2 else None


def _last_decision(entries: Iterable[DecisionEntry], card_id: str) -> DecisionEntry | None:
    """The entry that made a card's decision in force (its last applied or automatic one)."""
    last = None
    for entry in entries:
        if entry.card_id == card_id and entry.status in ("applied", "auto"):
            last = entry
    return last


def card_carry(
    store: StudyStore,
    card: DecisionCard,
    entries: Sequence[DecisionEntry],
    links: CarryLinks,
    report: dict[str, Any] | None,
) -> tuple[CarriedFrom | None, AskedAgain | None]:
    """Whether a card's decision was carried from an earlier analysis, or asked again here."""
    carried = links.of(_last_decision(entries, card.id)) if card.decided_by == "human" else None
    return carried, asked_again_of(store, card, report)


def card_view(
    card: DecisionCard,
    result: StudyResult,
    entries: Sequence[DecisionEntry],
    pending: Sequence[DecisionEntry],
    carried: CarriedFrom | None = None,
    asked: AskedAgain | None = None,
) -> CardView:
    """One Decision Card in words, with every option's consequence per headline gene.

    A decision carried from an earlier analysis says so in the status line, with the person's
    own words as the reason; ``asked`` is a person's earlier decision asked again here.
    """
    from qpilot.ai.explain import KIND_TITLE
    from qpilot.app_state import FLIPPED_FACT, _status_line, decider_words
    from qpilot.core.validator import names_from_result
    from qpilot.explain.templates import TemplateError, render_template

    facts = result.facts
    labels = {o.id: o.label for o in card.options}
    waiting = [p for p in pending if p.card_id == card.id]
    status = _status_line(card, labels, waiting[-1].option if waiting else None)
    if carried is not None and card.status == "decided":
        chosen = labels.get(card.decision or "", card.decision or "")
        status = (
            f"Decided by {decider_words(card.decided_by)}: {chosen}, carried over from your "
            f"decision on the earlier analysis of these data. Reason: {carried.reason}"
        )
    try:
        rendered = render_template(
            card.rationale_template, facts, card=card, allowed_names=names_from_result(result)
        )
        explanation = fact_text(rendered.tokens, facts)
    except (KeyError, TemplateError):
        explanation = plain_text(KIND_TITLE.get(card.kind, card.kind))
    flipped = FLIPPED_FACT.get(card.kind)
    if flipped in facts and "f_n_genes" in facts and card.impact.get("flips"):
        tokens = "{{" + flipped + "}} of {{f_n_genes}} conclusions change with this choice"
        if card.kind == "reference_set" and "f_n_flipped_refset_min3" in facts:
            tokens += "; {{f_n_flipped_refset_min3}} even between sets of three or more genes"
        impact = fact_text(tokens, facts)
    elif card.impact.get("flips"):
        impact = plain_text("Can change a conclusion")
    else:
        impact = plain_text("Changes no conclusion")
    recommended = next((o for o in card.options if o.id == card.recommended), None)
    base = {g: r.conclusion for g, r in recommended.per_gene.items()} if recommended else {}
    not_recommended = set(card.evidence.get("not_recommended", ()) or ())
    requested = {p.option for p in waiting}
    options = [
        CardOptionView(
            id=o.id,
            label=o.label,
            recommended=o.id == card.recommended,
            chosen=o.id == card.decision,
            requested=o.id in requested,
            not_recommended=o.id in not_recommended,
            effects=[
                OptionEffect(
                    gene=g,
                    fc=r.fc,
                    log2fc=r.log2fc,
                    ci=(float(r.ci[0]), float(r.ci[1])),
                    p=r.p,
                    conclusion=r.conclusion,
                    changes_call=g in base and base[g] != r.conclusion,
                )
                for g, r in o.per_gene.items()
            ],
        )
        for o in card.options
    ]
    undo = undo_target(entries, card.id)
    return CardView(
        card=card,
        title=KIND_TITLE.get(card.kind, card.kind),
        status_line=status,
        impact=impact,
        explanation=explanation,
        needs_human=bool(card.impact.get("flips") or card.impact.get("flips_anywhere")),
        genes=list(card.options[0].per_gene) if card.options else [],
        options=options,
        pending=[
            PendingRequest(
                seq=p.seq,
                option=p.option,
                option_label=labels.get(p.option, p.option),
                reason=p.reason,
                actor=p.actor,
                at=p.at,
            )
            for p in waiting
        ],
        undo_option=undo,
        undo_label=labels.get(undo) if undo else None,
        carried=carried,
        asked_again=asked,
        place=card_place(card),
    )


#: What deciding a card opened from Trace does, said on the card.
TRACE_CARD_NOTE = (
    "Opened from Trace. Deciding it is a person's choice, kept in the decision chain with the "
    "reason; the study's numbers stay as analysed. To leave the wells out of the analysis, "
    "decide in Trace's Where to look in a Studio session (it analyses the study again); a "
    "study analysed outside Studio is opened in Studio first."
)


def card_place(card: DecisionCard) -> CardPlace | None:
    """The place a card opened from Trace is about (None for every other card)."""
    from qpilot.core.store import ON_DEMAND_KINDS

    if card.kind not in ON_DEMAND_KINDS:
        return None
    ev = card.evidence or {}
    checks = [c for c in ev.get("what_to_check") or () if isinstance(c, str)]
    return CardPlace(
        sample=str(ev.get("sample") or ""),
        plate=str(ev["plate"]) if ev.get("plate") else None,
        well=str(ev["well"]) if ev.get("well") else None,
        target=str(ev["target"]) if ev.get("target") else None,
        what_to_check=checks,
        note=TRACE_CARD_NOTE,
    )


def cards_view(store: StudyStore, study_id: str) -> CardsView:
    """Every card, most impact first, read together with the chain head."""
    from qpilot.app_state import cards_in_order, decision_counter, next_card

    result = store.get(study_id)
    head, cards, pending = store.snapshot(study_id)
    entries = store.entries(study_id)
    upcoming = next_card(cards)
    links, report = CarryLinks(store, result.input_sha256), carry_report(store, study_id)
    return CardsView(
        study_id=study_id,
        head=head,
        cards=[
            card_view(c, result, entries, pending, *card_carry(store, c, entries, links, report))
            for c in cards_in_order(cards)
        ],
        next_card=upcoming.id if upcoming else None,
        counter=decision_counter(cards),
        pending_requests=len(pending),
    )


def one_card(store: StudyStore, study_id: str, card_id: str) -> CardView:
    """One card's view (``KeyError`` if unknown)."""
    result = store.get(study_id)
    _, cards, pending = store.snapshot(study_id)
    card = next((c for c in cards if c.id == card_id), None)
    if card is None:
        raise KeyError(card_id)
    entries = store.entries(study_id)
    links, report = CarryLinks(store, result.input_sha256), carry_report(store, study_id)
    carry = card_carry(store, card, entries, links, report)
    return card_view(card, result, entries, pending, *carry)


# ---- the decision chain ----------------------------------------------------------------------


#: How a run review's sign-off reads in the chain (``StudyStore.append_review``).
REVIEW_TITLE = "Run Review sign-off"
REVIEW_WORDS = {"accept": "Accept", "repeat": "Repeat", "discuss": "Discuss"}


def decisions_view(store: StudyStore, study_id: str) -> DecisionsView:
    """The chain, entry by entry, with each card and option in words."""
    from qpilot.ai.explain import KIND_TITLE

    head, cards, pending = store.snapshot(study_id)
    by_id = {c.id: c for c in cards}
    links = CarryLinks(store, store.get(study_id).input_sha256)

    def view(entry: DecisionEntry) -> DecisionEntryView:
        if entry.kind == "review":  # a person's sign-off of the run: no card replays it
            return DecisionEntryView(
                entry=entry,
                card_title=REVIEW_TITLE,
                option_label=REVIEW_WORDS.get(entry.outcome or entry.option, entry.option),
                undo=False,
                carried=None,
            )
        card = by_id.get(entry.card_id)
        labels = {o.id: o.label for o in card.options} if card else {}
        return DecisionEntryView(
            entry=entry,
            card_title=KIND_TITLE.get(card.kind, card.kind) if card else entry.card_id,
            option_label=labels.get(entry.option, entry.option),
            undo=entry.reason.startswith(UNDO_PREFIX),
            carried=links.of(entry),
        )

    from qpilot.core.record import verify_chain

    entries = store.entries(study_id)
    root = store.get(study_id).input_sha256
    broken = verify_chain(entries, root)
    attempts = []
    for a in store.attempts(study_id):
        if a.get("status") != "stale":
            continue
        card = by_id.get(str(a.get("card_id")))
        labels = {o.id: o.label for o in card.options} if card else {}
        option = str(a.get("option") or "")
        attempts.append(
            StaleAttempt(
                at=str(a.get("at") or ""),
                attempted=str(a.get("attempted") or ""),
                card_id=str(a.get("card_id") or ""),
                card_title=KIND_TITLE.get(card.kind, card.kind) if card else str(a.get("card_id")),
                option=option,
                option_label=labels.get(option, option),
                reason=str(a.get("reason") or ""),
                actor=str(a.get("actor") or ""),
                expected_head=a.get("expected_head"),
                head=a.get("head"),
            )
        )
    return DecisionsView(
        study_id=study_id,
        head=head,
        root=root,
        chain_intact=broken is None,
        broken_at=broken,
        entries=[view(e) for e in entries],
        pending=[view(p) for p in pending],
        n_pending=len(pending),
        attempts=attempts,
    )


class GeneWithheld(LookupError):
    """A gene the engine withheld (the message says why)."""


# ---- one gene --------------------------------------------------------------------------------


def gene_view(
    store: StudyStore, study_id: str, gene: str, comparison: str | None = None
) -> GeneView:
    """Everything about one compared gene (``KeyError`` if it is not one)."""
    from qpilot.explain.templates import TemplateError, render_template
    from qpilot.web import compare_views as cv

    stored, result, outcome, primary_grid, grid = _shown(store, study_id, comparison)
    if gene not in result.contrasts:
        held = next((w for w in withheld(result) + _not_tested(outcome) if w.gene == gene), None)
        if held is not None:
            raise GeneWithheld(f"{gene} has no comparison: {held.reason}.")
        raise KeyError(gene)
    head, cards, pending = store.snapshot(study_id)
    entries = store.entries(study_id)
    headline = headline_genes(result, cards, store)
    at = cv.at_choices_in(primary_grid, grid, cards)
    verdicts, labels = _verdicts(store, study_id)
    row = _row(gene, result, set(headline), at, verdicts, labels, cv.extra_columns(stored, outcome))
    try:
        rendered = render_template("confidence_v1", result.facts, gene=gene)
        confidence_text = fact_text(rendered.tokens, result.facts)
    except (KeyError, TemplateError):
        confidence_text = None
    if result is not stored:  # the sentence's facts are the first comparison's
        confidence_text = None
    gene_grid = None
    if grid is not None and grid.planned is not None:
        rows = grid.item(gene)
        gene_grid = GeneGrid(
            dimensions=grid.dimensions,
            options=grid.options,
            planned=[grid.planned[d] for d in grid.dimensions],
            cells=rows[[d + IDX for d in grid.dimensions]].astype(int).to_numpy().tolist(),
            log2fc=[_number(x) for x in rows["log2fc"]],
            p=[_number(x) for x in rows["p"]],
            conclusion=[_text(x) for x in rows["conclusion"]],  # type: ignore[misc]
        )
    effects = (
        _flip_rows(result, grid, cards, [gene], primary_grid) if gene in result.robustness else []
    )
    links, report = CarryLinks(store, result.input_sha256), carry_report(store, study_id)
    # Every card the page lists for this gene (a row of "one choice at a time" or a card that
    # flips it) comes with its full view, so its status line says who decided it and why.
    listed = {r.card_id for r in effects if r.card_id}
    affecting = [
        card_view(c, result, entries, pending, *card_carry(store, c, entries, links, report))
        for c in cards
        if c.id in listed
        or result.robustness.get(gene)
        and result.robustness[gene].impact.get(KIND_DIMENSION.get(c.kind, ""), {}).get("flips")
        or any(gene in o.per_gene for o in c.options)
    ]
    order = list(result.contrasts)
    i = order.index(gene)
    verdict = verdicts.get(gene)
    return GeneView(
        study_id=study_id,
        gene=gene,
        row=row,
        contrast=result.contrasts[gene],
        robustness=result.robustness[gene],
        confidence=grade_now(result.confidence.get(gene), result.robustness[gene].n_cells),
        confidence_text=confidence_text,
        grid=gene_grid,
        effects=effects,
        cards=affecting,
        is_reference=gene in result.design.refs_primary,
        reference_m=result.genorm.M_initial.get(gene),
        prev_gene=order[i - 1] if i > 0 else None,
        next_gene=order[i + 1] if i + 1 < len(order) else None,
        audit_verdict=verdict,
        audit_verdict_label=labels.get(verdict) if verdict else None,
        comparison=outcome.id if outcome is not None else _primary_id(stored),
    )


def study_exists(store: StudyStore, study_id: str) -> bool:
    """True when the store holds this study."""
    try:
        store.workspace(study_id)
    except StudyNotFound:
        return False
    return Path(store.workspace(study_id) / "results.json").exists()


# ---- autonomy --------------------------------------------------------------------------------

AUTONOMY_STATUS = "autonomy"


def autonomy_changes(store: StudyStore, study_id: str) -> list[AutonomyChange]:
    """Each change of the study's autonomy (kept beside the chain, in ``attempts.jsonl``)."""
    return [
        AutonomyChange(
            at=str(a.get("at") or ""),
            level=str(a.get("level") or ""),
            previous=str(a.get("previous") or ""),
            actor=str(a.get("actor") or "human"),
        )
        for a in store.attempts(study_id)
        if a.get("status") == AUTONOMY_STATUS
    ]


def autonomy_view(store: StudyStore, study_id: str) -> AutonomyView:
    """The study's autonomy, the policy lines and how it was changed."""
    from qpilot.ai.profile import autonomy_policy

    level = store.autonomy(study_id)
    return AutonomyView(
        study_id=study_id,
        autonomy=level if level in ("suggest", "decide_and_tell") else "suggest",  # type: ignore[arg-type]
        policy=list(autonomy_policy()),
        changes=autonomy_changes(store, study_id),
    )


def set_autonomy(store: StudyStore, study_id: str, level: str) -> bool:
    """A person sets the study's autonomy; the change is written beside the chain.

    The decision chain has no entry for it (the store offers none), so the change is appended
    to ``attempts.jsonl`` with status ``autonomy`` — kept with the study and its record, never
    moving the chain's head. Returns False when the level was already that.
    """
    from qpilot.core.store import canonical_json

    previous = store.autonomy(study_id)
    if previous == level:
        return False
    store.set_autonomy(study_id, level)
    workspace = store.workspace(study_id)
    line = {
        "at": _now(),
        "status": AUTONOMY_STATUS,
        "level": level,
        "previous": previous,
        "actor": "human",
    }
    with store._locked(workspace):
        with open(workspace / "attempts.jsonl", "a", encoding="utf-8", newline="\n") as fh:
            fh.write(canonical_json(line) + "\n")
    return True


def _now() -> str:
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
