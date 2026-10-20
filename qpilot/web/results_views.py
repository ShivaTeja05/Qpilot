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
import threading
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from qpilot.core.store import StudyNotFound, StudyStore
from qpilot.schemas import DecisionCard, DecisionEntry, Fact, StudyResult
from qpilot.web.contract import (
    AtChoices,
    AuditBadge,
    CardOptionView,
    CardsView,
    CardView,
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
    OptionEffect,
    PendingRequest,
    ResultsSummary,
    ResultsView,
    RuleView,
    TextSegment,
)

KIND_DIMENSION = {
    "reference_set": "refs",
    "group_cutoff": "cut",
    "undetermined": "undetermined",
    "amp_call": "amp_call",
}
DIMENSION_TITLE = {
    "refs": "Which control genes to normalise to",
    "cut": "Where to cut the comparison groups",
    "undetermined": "What to do with wells that never amplified",
    "amp_call": "Which curves count as amplified",
}
UNDO_PREFIX = "Undo:"
TOLERANCE = 1e-9
MAX_GRIDS = 4
IDX = "__idx"
CONCLUSIONS = ("up", "down", "none")


# ---- facts in sentences ----------------------------------------------------------------------


def fact_ref(fact: Fact) -> FactRef:
    """A fact as the page cites it."""
    from qpilot.core.facts import render_fact

    return FactRef(
        id=fact.id, text=render_fact(fact), value=fact.value, unit=fact.unit, path=fact.path
    )


def fact_text(tokens: str, facts: Mapping[str, Fact], source: str = "template") -> FactText:
    """Split ``{{fact}}`` tokens into plain text and cited numbers."""
    from qpilot.core.facts import render_fact
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
            segments.append(TextSegment(text=render_fact(fact), fact=fid))
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
    amp = result.facts.get("f_amp_primary")
    if amp is not None:
        out["amp_call"] = str(amp.value)
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


def chosen(grid: Grid, cards: Sequence[DecisionCard], mapped: Mapping) -> dict[str, int] | None:
    """The grid cell of the options applied on the cards now (None when it is the planned)."""
    if grid.planned is None:
        return None
    choice = dict(grid.planned)
    for card in cards:
        dim = KIND_DIMENSION.get(card.kind)
        if dim is None or card.decision is None:
            continue
        for idx, (card_id, option_id, _) in mapped.get(dim, {}).items():
            if card_id == card.id and option_id == card.decision:
                choice[dim] = idx
    return None if choice == grid.planned else choice


def option_label(dimension: str, value: str) -> str:
    """Words for a grid option no card names."""
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
    return AuditBadge(
        status="ready",
        verdict_counts={str(k): int(v) for k, v in (manifest.get("verdict_counts") or {}).items()},
        chain_head=head,
        current=bool(head) and head == store.chain_head(study_id),
    )


def headline_genes(result: StudyResult, cards: Sequence[DecisionCard]) -> list[str]:
    """The genes the cards show consequences for (the design's headline genes)."""
    for card in cards:
        if card.options:
            return [g for g in card.options[0].per_gene if g in result.contrasts]
    from qpilot.qpcr.designs import HEADLINE_GENES

    return [g for g in HEADLINE_GENES if g in result.contrasts]


def groups(result: StudyResult) -> list[GroupCount]:
    """The compared group and the reference group, with their sizes."""
    facts = result.facts
    design = result.design
    if "f_group_a" in facts and "f_group_b" in facts:
        return [
            GroupCount(label=str(facts["f_group_a"].value), n=design.n_hi),
            GroupCount(label=str(facts["f_group_b"].value), n=design.n_lo),
        ]
    marker = design.group_var.removesuffix("_high") or design.group_var
    return [
        GroupCount(label=f"{marker}-high", n=design.n_hi),
        GroupCount(label="rest", n=design.n_lo),
    ]


def _row(
    gene: str,
    result: StudyResult,
    headline: set[str],
    at: pd.DataFrame | None,
    verdicts: Mapping[str, str],
    labels: Mapping[str, str],
) -> GeneRow:
    contrast = result.contrasts[gene]
    robust = result.robustness.get(gene)
    grade = result.confidence.get(gene)
    yours = None
    if at is not None and gene in at.index:
        r = at.loc[gene]
        yours = AtChoices(
            fc=float(r["fc"]),
            log2fc=float(r["log2fc"]),
            p=float(r["p"]),
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
        reasons=list(grade.reasons) if grade else [],
        min_flip_changes=grade.min_flip_changes if grade else None,
        flips_by=sorted(d for d, v in (robust.impact if robust else {}).items() if v.get("flips")),
        efficiency=result.efficiency.get(gene),
        at_your_choices=yours,
        verdict=verdict,
        verdict_label=labels.get(verdict) if verdict else None,
    )


def results_view(store: StudyStore, study_id: str, session: str | None = None) -> ResultsView:
    """Everything the Results section shows."""
    from qpilot.app_state import design_line
    from qpilot.explain.templates import TemplateError, render_template
    from qpilot.qpcr.contrast import ConclusionRule

    result = store.get(study_id)
    head, cards, pending = store.snapshot(study_id)
    headline = headline_genes(result, cards)
    grid = load_grid(store, result)
    at = None
    if grid is not None:
        choice = chosen(grid, cards, card_options(grid, cards))
        if choice is not None:
            at = grid.cell(choice)
    verdicts, labels = _verdicts(store, study_id)
    rows = [_row(g, result, set(headline), at, verdicts, labels) for g in result.contrasts]
    try:
        summary_text = fact_text(render_template("summary_v1", result.facts).tokens, result.facts)
    except (KeyError, TemplateError):
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
        ),
        rule=RuleView(
            alpha=rule.alpha,
            min_log2fc=rule.min_log2fc,
            min_fold=2**rule.min_log2fc,
            text=rule.describe(),
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
        headline=headline,
        counts=counts,
        levels=levels,
        choices={c.id: c.decision for c in cards if c.decision is not None},
        cards_waiting=sum(1 for c in cards if c.status in ("open", "pending_human")),
        pending_requests=len(pending),
        head=head,
        audit=audit_badge(store, study_id),
    )


# ---- the flip matrix -------------------------------------------------------------------------


def _flip_rows(
    result: StudyResult,
    grid: Grid | None,
    cards: Sequence[DecisionCard],
    genes: Sequence[str],
) -> list[FlipRow]:
    by_dim = {KIND_DIMENSION.get(c.kind): c for c in cards}
    mapped = card_options(grid, cards) if grid is not None else {}
    choice = chosen(grid, cards, mapped) if grid is not None else None
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
                conclusion = [str(part.loc[g, "conclusion"]) if g in part.index else "none"
                              for g in genes]  # fmt: skip
                log2fc = [float(part.loc[g, "log2fc"]) if g in part.index else float("nan")
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
                        log2fc=[x if math.isfinite(x) else 0.0 for x in log2fc],
                        flips=[c != p for c, p in zip(conclusion, planned, strict=True)],
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


def flips_view(store: StudyStore, study_id: str) -> FlipsView:
    """Decisions × genes: where a decision alone flips a gene's call, and by how much."""
    result = store.get(study_id)
    cards = store.cards(study_id)
    genes = [g for g in result.contrasts if g in result.robustness]
    grid = load_grid(store, result)
    return FlipsView(
        study_id=study_id,
        genes=genes,
        planned=[result.contrasts[g].conclusion for g in genes],
        rows=_flip_rows(result, grid, cards, genes),
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


def card_view(
    card: DecisionCard,
    result: StudyResult,
    entries: Sequence[DecisionEntry],
    pending: Sequence[DecisionEntry],
) -> CardView:
    """One Decision Card in words, with every option's consequence per headline gene."""
    from qpilot.ai.explain import KIND_TITLE
    from qpilot.app_state import FLIPPED_FACT, _status_line
    from qpilot.core.validator import names_from_result
    from qpilot.explain.templates import TemplateError, render_template

    facts = result.facts
    labels = {o.id: o.label for o in card.options}
    waiting = [p for p in pending if p.card_id == card.id]
    status = _status_line(card, labels, waiting[-1].option if waiting else None)
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
    )


def cards_view(store: StudyStore, study_id: str) -> CardsView:
    """Every card, most impact first, read together with the chain head."""
    from qpilot.app_state import cards_in_order, decision_counter, next_card

    result = store.get(study_id)
    head, cards, pending = store.snapshot(study_id)
    entries = store.entries(study_id)
    upcoming = next_card(cards)
    return CardsView(
        study_id=study_id,
        head=head,
        cards=[card_view(c, result, entries, pending) for c in cards_in_order(cards)],
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
    return card_view(card, result, store.entries(study_id), pending)


# ---- the decision chain ----------------------------------------------------------------------


def decisions_view(store: StudyStore, study_id: str) -> DecisionsView:
    """The chain, entry by entry, with each card and option in words."""
    from qpilot.ai.explain import KIND_TITLE

    head, cards, pending = store.snapshot(study_id)
    by_id = {c.id: c for c in cards}

    def view(entry: DecisionEntry) -> DecisionEntryView:
        card = by_id.get(entry.card_id)
        labels = {o.id: o.label for o in card.options} if card else {}
        return DecisionEntryView(
            entry=entry,
            card_title=KIND_TITLE.get(card.kind, card.kind) if card else entry.card_id,
            option_label=labels.get(entry.option, entry.option),
            undo=entry.reason.startswith(UNDO_PREFIX),
        )

    return DecisionsView(
        study_id=study_id,
        head=head,
        entries=[view(e) for e in store.entries(study_id)],
        pending=[view(p) for p in pending],
    )


# ---- one gene --------------------------------------------------------------------------------


def gene_view(store: StudyStore, study_id: str, gene: str) -> GeneView:
    """Everything about one compared gene (``KeyError`` if it is not one)."""
    from qpilot.explain.templates import TemplateError, render_template

    result = store.get(study_id)
    if gene not in result.contrasts:
        raise KeyError(gene)
    head, cards, pending = store.snapshot(study_id)
    entries = store.entries(study_id)
    headline = headline_genes(result, cards)
    grid = load_grid(store, result)
    at = None
    if grid is not None:
        choice = chosen(grid, cards, card_options(grid, cards))
        if choice is not None:
            at = grid.cell(choice)
    verdicts, labels = _verdicts(store, study_id)
    row = _row(gene, result, set(headline), at, verdicts, labels)
    try:
        rendered = render_template("confidence_v1", result.facts, gene=gene)
        confidence_text = fact_text(rendered.tokens, result.facts)
    except (KeyError, TemplateError):
        confidence_text = None
    gene_grid = None
    if grid is not None and grid.planned is not None:
        rows = grid.item(gene)
        gene_grid = GeneGrid(
            dimensions=grid.dimensions,
            options=grid.options,
            planned=[grid.planned[d] for d in grid.dimensions],
            cells=rows[[d + IDX for d in grid.dimensions]].astype(int).to_numpy().tolist(),
            log2fc=[float(x) for x in rows["log2fc"]],
            p=[float(x) if np.isfinite(x) else 1.0 for x in rows["p"]],
            conclusion=[str(x) for x in rows["conclusion"]],  # type: ignore[misc]
        )
    effects = _flip_rows(result, grid, cards, [gene]) if gene in result.robustness else []
    affecting = [
        card_view(c, result, entries, pending)
        for c in cards
        if result.robustness.get(gene)
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
        confidence=result.confidence.get(gene),
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
    )


def study_exists(store: StudyStore, study_id: str) -> bool:
    """True when the store holds this study."""
    try:
        store.workspace(study_id)
    except StudyNotFound:
        return False
    return Path(store.workspace(study_id) / "results.json").exists()
