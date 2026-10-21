"""Replay a study's decision chain step by step on its own robustness grid.

Step 0 is the study as analysed (the chain's root, the input file's sha256); step *k* is the
state after the *k*-th entry of ``decisions.jsonl``. At every step:

* the Decision Cards are rebuilt from the log alone (:func:`qpilot.core.store.replay_cards`, the
  same replay the store and ``qpilot verify`` use);
* the analysis in force is the grid cell those cards name — each card's applied option, the
  planned option elsewhere — found by value exactly as the Results views find it
  (:func:`qpilot.web.results_views.current_cell`), so replaying to the head gives the numbers
  the Results section shows;
* every gene's call, fold change and p-value are that cell's row of ``grid.csv`` (the planned
  analysis is the stored contrasts themselves), and its *holds* is the share of the grid's
  analyses that give the same call.

Nothing is estimated: a step whose analysis the grid does not hold is reported as not
replayable, with the reason.
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from qpilot.core.record import verify_chain
from qpilot.core.store import StudyNotFound, StudyStore, replay_cards
from qpilot.schemas import DecisionCard, DecisionEntry, StudyResult
from qpilot.web import results_views as rv
from qpilot.web.contract_history import (
    AuditMark,
    CarryCard,
    CarryNote,
    ChoiceChange,
    ChoiceInForce,
    GeneChange,
    HistoryAnalysis,
    HistoryChoice,
    HistoryDiff,
    HistoryGene,
    HistoryStep,
    HistoryView,
    StepConclusions,
)

CONCLUSIONS = ("up", "down", "none")
MOVED = 1e-9  # a fold change "moved" when its log2 changed by more than this
TOP = 12  # fold and holds movers listed in a diff
MAX_CACHED = 4
NOT_REPLAYABLE = (
    "This study's grid of analyses does not hold its planned analysis, so only the analysis as "
    "planned can be shown, not what each decision changed."
)
NO_GRID = (
    "This study has no grid of analyses (grid.csv), so only the analysis as planned can be "
    "shown, not what each decision changed."
)


class HistoryError(ValueError):
    """A step that is not in the chain, or an analysis the grid cannot give (message says)."""


# ---- reading the chain once ------------------------------------------------------------------


@dataclass
class Analysis:
    """One distinct analysis some step had in force."""

    index: int
    planned: bool
    choice: dict[str, int] | None  # dimension -> grid option index (None without a grid)
    genes: dict[str, HistoryGene]


@dataclass
class Chain:
    """A study's chain read once, with every step's cards and analysis."""

    store: StudyStore
    study_id: str
    result: StudyResult
    cards: list[DecisionCard]  # rank order; decision fields as on disk now
    entries: list[DecisionEntry]
    root: str
    broken: int | None
    grid: rv.Grid | None
    mapped: dict[str, dict[int, tuple]]
    step_cards: list[list[DecisionCard]]  # step k -> cards after the first k entries
    step_analysis: list[int | None]  # step k -> index into analyses
    analyses: list[Analysis]
    note: str | None

    @property
    def head(self) -> str:
        """The chain head: the latest entry's hash, or the root."""
        return self.entries[-1].hash if self.entries else self.root

    @property
    def replayable(self) -> bool:
        """The grid holds the planned analysis, so every step's analysis can be read from it."""
        return self.grid is not None and self.grid.planned is not None

    def analysis_at(self, seq: int) -> Analysis | None:
        """The analysis in force at a step (``HistoryError`` for a step not in the chain)."""
        if not isinstance(seq, int) or not 0 <= seq <= len(self.entries):
            raise HistoryError(
                f"There is no step {seq} in this chain; it has steps 0 to {len(self.entries)}."
            )
        index = self.step_analysis[seq]
        return None if index is None else self.analyses[index]


def _num(value: Any) -> float | None:
    """A finite float, or None where the engine computed none."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _call(value: Any) -> str | None:
    text = None if value is None else str(value)
    return text if text in CONCLUSIONS else None


_shares_lock = threading.Lock()
_shares: OrderedDict[int, tuple[rv.Grid, dict[tuple[str, str], float]]] = OrderedDict()


def call_shares(grid: rv.Grid) -> dict[tuple[str, str], float]:
    """(gene, call) -> share of the grid's analyses of that gene giving that call.

    The same definition as :func:`qpilot.core.robustness.holds_fraction` (every cell of the
    gene counts in the denominator).
    """
    with _shares_lock:
        hit = _shares.get(id(grid))
        if hit is not None and hit[0] is grid:
            return hit[1]
    frame = grid.frame
    sizes = frame.groupby("item").size()
    counts = frame.groupby(["item", "conclusion"]).size()
    out = {
        (str(item), str(call)): float(n) / float(sizes[item]) for (item, call), n in counts.items()
    }
    with _shares_lock:
        _shares[id(grid)] = (grid, out)
        while len(_shares) > MAX_CACHED:
            _shares.popitem(last=False)
    return out


def _planned_genes(result: StudyResult) -> dict[str, HistoryGene]:
    """The analysis as planned: the stored contrasts and robustness, exactly."""
    out = {}
    for gene, c in result.contrasts.items():
        robust = result.robustness.get(gene)
        out[gene] = HistoryGene(
            gene=gene,
            log2fc=_num(c.log2fc),
            fc=_num(c.fc),
            p=_num(c.p),
            conclusion=c.conclusion,
            holds=robust.holds if robust is not None else None,
        )
    return out


def _cell_genes(
    result: StudyResult, grid: rv.Grid, choice: Mapping[str, int]
) -> dict[str, HistoryGene]:
    """Every gene's row of one grid cell (None values where the cell has no row)."""
    cell = grid.cell(choice)
    shares = call_shares(grid)
    out = {}
    for gene in result.contrasts:
        if gene not in cell.index:
            out[gene] = HistoryGene(
                gene=gene, log2fc=None, fc=None, p=None, conclusion=None, holds=None
            )
            continue
        row = cell.loc[gene]
        call = _call(row["conclusion"])
        out[gene] = HistoryGene(
            gene=gene,
            log2fc=_num(row["log2fc"]),
            fc=_num(row["fc"]),
            p=_num(row["p"]),
            conclusion=call,  # type: ignore[arg-type]
            holds=shares.get((gene, call)) if call is not None else None,
        )
    return out


def _at_recommended(cards: Sequence[DecisionCard]) -> bool:
    return all(c.decision is None or c.decision == c.recommended for c in cards)


def load_chain(store: StudyStore, study_id: str) -> Chain:
    """Read a study's chain, cards, results and grid, and replay every step."""
    result = store.get(study_id)
    cards = store.cards(study_id)
    entries = store.entries(study_id)
    root = result.input_sha256
    broken = verify_chain(entries, root)
    grid = rv.load_grid(store, result)
    replayable = grid is not None and grid.planned is not None
    mapped = rv.card_options(grid, cards) if replayable else {}
    note = None if replayable else (NO_GRID if grid is None else NOT_REPLAYABLE)

    analyses: list[Analysis] = []
    by_key: dict[tuple, int] = {}
    step_cards: list[list[DecisionCard]] = []
    step_analysis: list[int | None] = []
    for k in range(len(entries) + 1):
        state = replay_cards(cards, entries[:k])
        step_cards.append(state)
        if replayable:
            assert grid is not None and grid.planned is not None
            choice = rv.current_cell(grid, state, mapped)
            key: tuple = tuple(choice[d] for d in grid.dimensions)
            planned = choice == grid.planned
        elif _at_recommended(state):
            choice, key, planned = None, ("planned",), True
        else:
            step_analysis.append(None)
            continue
        if key not in by_key:
            genes = _planned_genes(result) if planned else _cell_genes(result, grid, choice)  # type: ignore[arg-type]
            by_key[key] = len(analyses)
            analyses.append(Analysis(len(analyses), planned, choice, genes))
        step_analysis.append(by_key[key])
    return Chain(
        store=store,
        study_id=study_id,
        result=result,
        cards=cards,
        entries=entries,
        root=root,
        broken=broken,
        grid=grid,
        mapped=mapped,
        step_cards=step_cards,
        step_analysis=step_analysis,
        analyses=analyses,
        note=note,
    )


# ---- views -----------------------------------------------------------------------------------


def _card_title(card: DecisionCard) -> str:
    from qpilot.ai.explain import KIND_TITLE

    return KIND_TITLE.get(card.kind, card.kind)


def choices_in_force(cards: Sequence[DecisionCard]) -> list[ChoiceInForce]:
    """Each card's option in force (its decision, else the planned option), in rank order."""
    out = []
    for card in cards:
        option = card.decision or card.recommended
        labels = {o.id: o.label for o in card.options}
        out.append(
            ChoiceInForce(
                card_id=card.id,
                title=_card_title(card),
                dimension=rv.KIND_DIMENSION.get(card.kind),
                option=option,
                option_label=labels.get(option, option),
                planned=option == card.recommended,
                decided=card.decision is not None,
                decided_by=card.decided_by,
                status=card.status,
            )
        )
    return out


def _analysis_view(chain: Chain, analysis: Analysis, genes: Sequence[str]) -> HistoryAnalysis:
    choices = []
    grid = chain.grid
    if grid is not None and grid.planned is not None and analysis.choice is not None:
        for dim in grid.dimensions:
            idx = analysis.choice[dim]
            value = grid.options[dim][idx]
            named = chain.mapped.get(dim, {}).get(idx)
            choices.append(
                HistoryChoice(
                    dimension=dim,
                    title=rv.DIMENSION_TITLE.get(dim, dim),
                    value=value,
                    label=named[2] if named else rv.option_label(dim, value),
                    planned=idx == grid.planned[dim],
                )
            )
    return HistoryAnalysis(
        index=analysis.index,
        planned=analysis.planned,
        choices=choices,
        genes=[analysis.genes[g] for g in genes],
        counts=counts_of(analysis.genes.values()),
    )


def counts_of(genes: Any) -> dict[str, int]:
    """Genes called up / down / none."""
    out = dict.fromkeys(CONCLUSIONS, 0)
    for g in genes:
        if g.conclusion in out:
            out[g.conclusion] += 1
    return out


def _changed(before: Analysis | None, after: Analysis | None) -> tuple[list[str], int]:
    """Genes whose call changed, and how many fold changes moved, between two analyses."""
    if before is None or after is None or before.index == after.index:
        return [], 0
    changed, moved = [], 0
    for gene, b in after.genes.items():
        a = before.genes.get(gene)
        if a is None:
            continue
        if a.conclusion != b.conclusion:
            changed.append(gene)
        if a.log2fc is not None and b.log2fc is not None and abs(b.log2fc - a.log2fc) > MOVED:
            moved += 1
    return changed, moved


def _names(genes: Sequence[str], limit: int = 4) -> str:
    shown = ", ".join(genes[:limit])
    more = len(genes) - limit
    return f"{shown} and {more} more" if more > 0 else shown


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _effect(entry: DecisionEntry | None, changed: list[str], moved: int, same: bool) -> str:
    """What one step changed, in plain words."""
    if entry is None:
        return "The study as analysed: every choice as planned, nothing decided yet."
    if entry.status == "pending_human":
        return "An agent asked for this choice; it waits for a person, so nothing changed."
    if entry.status == "rejected":
        return "A person turned down an agent's request; nothing changed."
    if entry.status == "stale":
        return "A write refused as out of date; nothing changed."
    from qpilot.core.decisions import carried_from

    prefix = "Undo. " if entry.reason.startswith(rv.UNDO_PREFIX) else ""
    if entry.actor == "human" and carried_from(entry.reason) is not None:
        prefix = "Carried from the earlier analysis. "
    if same:
        return prefix + "The analysis in force stayed the same: no number changed."
    if changed:
        calls = _plural(len(changed), "call")
        return f"{prefix}Changed {calls}: {_names(changed)}; {_plural(moved, 'fold change')} moved."
    return f"{prefix}No call changed; {_plural(moved, 'fold change')} moved."


def _created_at(store: StudyStore, study_id: str, entries: Sequence[DecisionEntry]) -> str | None:
    """When the analysis was made: its first chain entry, else its results file's time."""
    if entries:
        return entries[0].at
    try:
        mtime = (store.workspace(study_id) / "results.json").stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _audit_mark(chain: Chain) -> AuditMark | None:
    badge = rv.audit_badge(chain.store, chain.study_id)
    if badge.status != "ready" or not badge.chain_head:
        return None
    hashes = [chain.root, *(e.hash for e in chain.entries)]
    step = hashes.index(badge.chain_head) if badge.chain_head in hashes else None
    return AuditMark(chain_head=badge.chain_head, step=step, current=badge.current)


def carry_note(store: StudyStore, study_id: str, cards: Sequence[DecisionCard]) -> CarryNote | None:
    """What a person had decided in the session's analysis before this one, and what became of it.

    Read from the session's report of the carry (:meth:`StudyStore.carry_decisions`); the
    carried entries themselves are steps of this chain.
    """
    report = rv.carry_report(store, study_id)
    if not report or not report.get("source"):
        return None
    source = str(report["source"])
    here = {c.id: c for c in cards}
    try:
        there = {c.id: c for c in store.cards(source)}
    except (StudyNotFound, OSError, ValueError):
        there = {}

    def card(card_id: str, why: str | None = None) -> CarryCard:
        before = there.get(card_id)
        option = before.decision if before is not None else None
        labels = {o.id: o.label for o in before.options} if before is not None else {}
        shown = here.get(card_id) or before
        return CarryCard(
            card_id=card_id,
            card_title=_card_title(shown) if shown is not None else card_id,
            option=option,
            option_label=labels.get(option or "", option),
            why=why,
        )

    asked = report.get("asked_again") or {}
    return CarryNote(
        from_study=source,
        carried=[card(c) for c in report.get("carried") or []],
        asked_again=[card(c, str(why)) for c, why in asked.items()],
        gone=[card(c) for c in report.get("gone") or []],
    )


def history_view(store: StudyStore, study_id: str, session: str | None = None) -> HistoryView:
    """Every step of a study's decision chain with the analysis in force and its calls."""
    from qpilot.history.studio import studio_context

    chain = load_chain(store, study_id)
    result = chain.result
    genes = list(result.contrasts)
    audit = _audit_mark(chain)
    links = rv.CarryLinks(store, result.input_sha256)
    steps: list[HistoryStep] = []
    for k, cards in enumerate(chain.step_cards):
        entry = chain.entries[k - 1] if k else None
        analysis = chain.analysis_at(k)
        previous = chain.analysis_at(k - 1) if k else None
        changed, moved = _changed(previous, analysis)
        same = analysis is not None and previous is not None and analysis.index == previous.index
        conclusions = None
        if analysis is not None:
            counts = counts_of(analysis.genes.values())
            conclusions = StepConclusions(
                **counts, n_changed=len(changed), changed=changed, n_moved=moved
            )
        link_ok = chain.broken is None or k == 0 or k < chain.broken
        step = HistoryStep(
            seq=k,
            kind="decision" if entry else "start",
            hash=entry.hash if entry else chain.root,
            prev_hash=entry.prev_hash if entry else None,
            link_ok=link_ok,
            chain_intact=link_ok,
            analysis=analysis.index if analysis is not None else None,
            choices=choices_in_force(cards),
            conclusions=conclusions,
            effect=_effect(entry, changed, moved, same)
            if analysis is not None or entry is None
            else "This step's analysis is not in the study's grid.",
            audited=audit is not None and audit.step == k,
        )
        if entry is not None:
            card = next((c for c in chain.cards if c.id == entry.card_id), None)
            labels = {o.id: o.label for o in card.options} if card else {}
            carried = links.of(entry)
            step = step.model_copy(
                update={
                    "at": entry.at,
                    "actor": entry.actor,
                    "card_id": entry.card_id,
                    "card_title": _card_title(card) if card else entry.card_id,
                    "option": entry.option,
                    "option_label": labels.get(entry.option, entry.option),
                    "reason": carried.reason if carried is not None else entry.reason,
                    "status": entry.status,
                    "undo": entry.reason.startswith(rv.UNDO_PREFIX),
                    "carried": carried,
                }
            )
        steps.append(step)

    created = _created_at(store, study_id, chain.entries)
    session_id, milestones, intact, related = studio_context(
        store, study_id, result.input_sha256, created, chain.entries, session
    )
    robust = next(iter(result.robustness.values()), None)
    rule = result.conclusion_rule
    return HistoryView(
        study_id=study_id,
        session=session_id,
        input_sha256=result.input_sha256,
        head=chain.head,
        root=chain.root,
        chain_intact=chain.broken is None,
        broken_at=chain.broken,
        created_at=created,
        replayable=chain.replayable,
        note=chain.note,
        n_cells=robust.n_cells if robust is not None else None,
        min_log2fc=float(rule.get("min_log2fc", 1.0)),
        alpha=float(rule.get("alpha", 0.05)),
        groups=[g.label for g in rv.groups(result)],
        genes=genes,
        headline=rv.headline_genes(result, chain.cards, store),
        analyses=[_analysis_view(chain, a, genes) for a in chain.analyses],
        steps=steps,
        studio=milestones,
        studio_intact=intact,
        related=related,
        carry=carry_note(store, study_id, chain.cards),
        audit=audit,
    )


# ---- diff ------------------------------------------------------------------------------------


def gene_changes(
    genes: Sequence[str],
    before: Mapping[str, HistoryGene],
    after: Mapping[str, HistoryGene],
    headline: Sequence[str] = (),
    verdicts: Mapping[str, str] | None = None,
    labels: Mapping[str, str] | None = None,
    causes: Mapping[str, str] | None = None,
) -> tuple[list[GeneChange], list[GeneChange], list[GeneChange], int]:
    """Calls changed, the largest fold moves, the largest holds moves, and how many folds moved."""
    verdicts = verdicts or {}
    labels = labels or {}
    rows = []
    for gene in genes:
        a, b = before.get(gene), after.get(gene)
        if a is None or b is None:
            continue
        delta = b.log2fc - a.log2fc if a.log2fc is not None and b.log2fc is not None else None
        verdict = verdicts.get(gene)
        rows.append(
            GeneChange(
                gene=gene,
                headline=gene in headline,
                from_conclusion=a.conclusion,
                to_conclusion=b.conclusion,
                from_log2fc=a.log2fc,
                to_log2fc=b.log2fc,
                from_p=a.p,
                to_p=b.p,
                from_holds=a.holds,
                to_holds=b.holds,
                delta_log2fc=delta,
                call_changed=a.conclusion != b.conclusion,
                verdict=verdict,
                verdict_label=labels.get(verdict) if verdict else None,
                cause=causes.get(gene) if causes is not None else None,  # type: ignore[arg-type]
            )
        )
    calls = [r for r in rows if r.call_changed]
    moved = [r for r in rows if r.delta_log2fc is not None and abs(r.delta_log2fc) > MOVED]
    folds = sorted(moved, key=lambda r: (-abs(r.delta_log2fc or 0.0), r.gene))[:TOP]

    def holds_delta(r: GeneChange) -> float:
        if r.from_holds is None or r.to_holds is None:
            return 0.0
        return abs(r.to_holds - r.from_holds)

    holds = sorted(
        (r for r in rows if holds_delta(r) > 1e-12), key=lambda r: (-holds_delta(r), r.gene)
    )[:TOP]
    return calls, folds, holds, len(moved)


def choice_changes(
    before: Sequence[ChoiceInForce], after: Sequence[ChoiceInForce]
) -> list[ChoiceChange]:
    """Cards whose option in force differs between two points."""
    then = {c.card_id: c for c in before}
    out = []
    for now in after:
        was = then.get(now.card_id)
        if was is not None and was.option != now.option:
            out.append(
                ChoiceChange(
                    card_id=now.card_id,
                    title=now.title,
                    from_option=was.option,
                    from_label=was.option_label,
                    to_option=now.option,
                    to_label=now.option_label,
                )
            )
    return out


def change_sentence(calls: Sequence[GeneChange], n_moved: int) -> str:
    """The change between two analyses in one sentence."""
    if not calls and not n_moved:
        return "No conclusion and no number changed."
    folds = _plural(n_moved, "fold change")
    if not calls:
        return f"No call changed; {folds} moved."
    names = _names([c.gene for c in calls])
    return f"{_plural(len(calls), 'call')} changed ({names}); {folds} moved."


def diff_steps(store: StudyStore, study_id: str, from_seq: int, to_seq: int) -> HistoryDiff:
    """What changed between two steps of a study's chain (``HistoryError`` when it cannot say)."""
    chain = load_chain(store, study_id)
    before = chain.analysis_at(from_seq)
    after = chain.analysis_at(to_seq)
    if before is None or after is None:
        raise HistoryError(chain.note or NOT_REPLAYABLE)
    result = chain.result
    genes = list(result.contrasts)
    verdicts, labels = rv._verdicts(store, study_id)
    headline = rv.headline_genes(result, chain.cards, store)
    calls, folds, holds, n_moved = gene_changes(
        genes, before.genes, after.genes, headline, verdicts, labels
    )
    audit = _audit_mark(chain)
    audit_note = None
    if audit is not None and verdicts:
        where = f"step {audit.step}" if audit.step is not None else "a head not in this chain"
        audit_note = f"The audit's verdicts shown are of {where} (chain {audit.chain_head[:8]})."
    same = before.index == after.index
    return HistoryDiff(
        study_id=study_id,
        from_seq=from_seq,
        to_seq=to_seq,
        same_analysis=same,
        choices=choice_changes(
            choices_in_force(chain.step_cards[from_seq]),
            choices_in_force(chain.step_cards[to_seq]),
        ),
        from_counts=counts_of(before.genes.values()),
        to_counts=counts_of(after.genes.values()),
        calls_changed=calls,
        fold_moves=folds,
        holds_moves=holds,
        n_moved=n_moved,
        summary=(
            "The same analysis was in force at both points: no number changed."
            if same
            else change_sentence(calls, n_moved)
        ),
        audit_note=audit_note,
    )
