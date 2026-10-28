"""View-models over engine output: the study summary, the design sentence and the Decision Cards.

Pure functions, used by the one page's results views (:mod:`qpilot.web.results_views`), the
Studio views and the model layer. Two rules hold for everything these functions return:

* every name, label, reason and fact value is HTML-escaped before it reaches markup;
* every number comes from the engine (a fact, rendered with its own format, or a count of cards),
  never from a hand-typed string.
"""

from __future__ import annotations

import html
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import pandas as pd

from qpilot.ai.explain import KIND_TITLE
from qpilot.core.decisions import needs_human
from qpilot.core.facts import render_fact, slug
from qpilot.core.store import ON_DEMAND_KINDS
from qpilot.explain.templates import TemplateError, render_template, to_html
from qpilot.qpcr.contrast import ConclusionRule
from qpilot.schemas import DecisionCard, Fact, StudyResult

Facts = Mapping[str, Fact]

CONCLUSION_WORDS = {"up": "up", "down": "down", "none": "no call"}
FLIPPED_FACT = {
    "reference_set": "f_n_flipped_refset",
    "group_cutoff": "f_n_flipped_cutoff",
    "undetermined": "f_n_flipped_undetermined",
    "amp_call": "f_n_flipped_amp_call",
    "numbers.efficiency_model": "f_n_flipped_efficiency",
}
#: ``DesignSummary.note`` of a study whose groups come from a confirmed design (sample sheet or
#: accepted proposals), as written by ``qpilot.qpcr.study``; such a study has no cut-off.
GROUPS_NOTE = "groups from the confirmed design"
FOOTER = (
    "For research use only. Not for clinical or diagnostic use.",
    "qPilot never makes a choice that can change a conclusion; those always wait for a person.",
)


def esc(value: object) -> str:
    """HTML-escape any value's text (quotes included)."""
    return html.escape(str(value), quote=True)


def conclusion_word(conclusion: str) -> str:
    """``up`` / ``down`` / ``no call``."""
    return CONCLUSION_WORDS.get(conclusion, conclusion)


def _fact_text(facts: Facts, fid: str, fallback: str = "") -> str:
    """A fact's rendered value (plain text), or ``fallback`` when the fact is missing."""
    return render_fact(facts[fid]) if fid in facts else fallback


# ---------- study summary ----------


@dataclass(frozen=True)
class SummaryView:
    """The left-hand study summary: one paragraph plus the conclusion rule."""

    html: str
    plain: str
    rule: str


def study_summary(result: StudyResult) -> SummaryView:
    """Counts, groups and the rule every conclusion is drawn with."""
    rendered = render_template("summary_v1", result.facts)
    rule = ConclusionRule(**result.conclusion_rule).describe()
    design = design_line(result)
    body = (
        f'<p class="qp-summary">{rendered.html}</p><p class="qp-design">{esc(design)}</p>'
        f'<p class="qp-rule">Rule: {esc(rule)}</p>'
    )
    return SummaryView(html=body, plain=f"{rendered.plain} {design}", rule=rule)


def design_line(result: StudyResult) -> str:
    """How the groups were made, from the engine's design record."""
    design = result.design
    if design.note == GROUPS_NOTE:
        return (
            f"Groups from the confirmed design ({design.group_var}): {design.n_hi} vs "
            f"{design.n_lo} biological units; technical replicates averaged within each unit."
        )
    marker = design.group_var.removesuffix("_high") or design.group_var
    return (
        f"Groups by {marker} expression, top {design.cut:.0%}: {marker}-high {design.n_hi} vs "
        f"rest {design.n_lo}. Expression-defined, not a clinical call."
    ).replace("%", " %")


# ---------- Decision Cards ----------


@dataclass(frozen=True)
class OptionRow:
    """One option of a card, with its consequence for each headline gene (escaped text)."""

    id: str
    label: str
    recommended: bool
    chosen: bool
    cells: tuple[tuple[str, str, str], ...]  # (gene, fold change, conclusion word)
    not_recommended: bool = False  # e.g. a single control gene (MIQE)


@dataclass(frozen=True)
class CardView:
    """Everything the centre panel shows for one Decision Card."""

    id: str
    kind: str
    title: str
    rank: int
    status: str
    needs_human: bool
    status_line: str
    impact_html: str
    explanation_html: str
    explanation_plain: str
    genes: tuple[str, ...]
    options: tuple[OptionRow, ...]
    html: str
    where_html: str = ""  # a Trace card: the place it is about and what to check


DECIDER_WORDS = {"human": "you", "agent": "an agent", "system": "qPilot"}


def decider_words(actor: str | None) -> str:
    """Who decided a card, as the page says it to the person using it ("Decided by you")."""
    return DECIDER_WORDS.get(actor or "", actor or "someone")


def _status_line(
    card: DecisionCard, labels: Mapping[str, str], pending_option: str | None = None
) -> str:
    chosen = labels.get(card.decision or "", card.decision or "")
    if card.status == "auto_decided":
        reason = card.reason or ""
        return (
            reason
            if reason.startswith("Decided automatically")
            else f"Decided automatically. {reason}".strip()
        )
    if card.status == "decided":
        reason = f" Reason: {card.reason}" if card.reason else ""
        return f"Decided by {decider_words(card.decided_by)}: {chosen}.{reason}"
    if card.status == "pending_human":
        # The request lives in the store's pending list; card.decision is the earlier choice.
        asked = labels.get(pending_option or "", pending_option or "another option")
        return f"Waiting for a person: an agent asked to choose {asked}."
    if card.impact.get("flips"):
        return "Your decision: this choice can change a conclusion."
    return "Open."


def card_view(
    card: DecisionCard,
    facts: Facts,
    *,
    allowed_names: Iterable[str] = (),
    pending_option: str | None = None,
) -> CardView:
    """The view of one card: title, status, impact, explanation and the options table.

    ``pending_option`` is the option an agent asked for (from ``StudyStore.pending``); it is
    named while the card waits for a person, because ``card.decision`` keeps the earlier choice.
    """
    labels = {o.id: o.label for o in card.options}
    genes = _card_genes(card)
    on_demand = card.kind in ON_DEMAND_KINDS
    rows = []
    for option in card.options:
        context = option.id.removesuffix("_alone")
        if on_demand and option.id == card.recommended:  # keep: the study as analysed
            context = "recommended"
        cells = tuple(
            (
                esc(gene),
                esc(_fact_text(facts, f"f_fc_{slug(gene)}_{context}", f"{result.fc:.2g}×")),
                esc(conclusion_word(result.conclusion)),
            )
            for gene, result in option.per_gene.items()
            if gene in genes
        )
        rows.append(
            OptionRow(
                id=esc(option.id),
                label=esc(option.label),
                recommended=option.id == card.recommended,
                chosen=option.id == card.decision,
                cells=cells,
                not_recommended=option.id in set(card.evidence.get("not_recommended", ())),
            )
        )
    try:
        explanation = render_template(
            card.rationale_template, facts, card=card, allowed_names=allowed_names
        )
        explanation_html, explanation_plain = explanation.html, explanation.plain
    except (KeyError, TemplateError):
        explanation_plain = KIND_TITLE.get(card.kind, card.kind)
        explanation_html = esc(explanation_plain)
    flipped = FLIPPED_FACT.get(card.kind)
    if flipped in facts and "f_n_genes" in facts and card.impact.get("flips"):
        tokens = "{{" + flipped + "}} of {{f_n_genes}} conclusions change with this choice"
        if card.kind == "reference_set" and "f_n_flipped_refset_min3" in facts:
            tokens += "; {{f_n_flipped_refset_min3}} even between sets of three or more genes"
        impact = to_html(tokens, facts)
    elif card.impact.get("flips") and on_demand and card.impact.get("flipped_genes"):
        changed = ", ".join(esc(g) for g in card.impact["flipped_genes"])
        impact = f"Can change a conclusion: the call of {changed}"
    elif card.impact.get("flips"):
        impact = "Can change a conclusion"
    else:
        impact = "Changes no conclusion"
    view = CardView(
        id=esc(card.id),
        kind=card.kind,
        title=esc(KIND_TITLE.get(card.kind, card.kind)),
        rank=card.rank,
        status=card.status,
        needs_human=needs_human(card),
        status_line=esc(_status_line(card, labels, pending_option)),
        impact_html=impact,
        explanation_html=explanation_html,
        explanation_plain=explanation_plain,
        genes=tuple(esc(g) for g in genes),
        options=tuple(rows),
        html="",
        where_html=_where_html(card) if on_demand else "",
    )
    return _with_html(view)


#: Columns a Trace card shows when no option changes a call (its options cover every gene).
TRACE_CARD_GENES = 4


def _card_genes(card: DecisionCard) -> tuple[str, ...]:
    """The genes a card's table shows: every gene, or a Trace card's changed calls."""
    genes = tuple(card.options[0].per_gene) if card.options else ()
    if card.kind not in ON_DEMAND_KINDS:
        return genes
    flipped = [g for g in card.impact.get("flipped_genes") or () if g in genes]
    return tuple(flipped) or genes[:TRACE_CARD_GENES]


def _where_html(card: DecisionCard) -> str:
    """A Trace card's place (sample, plate, well) and what to check, all escaped."""
    ev = card.evidence
    parts = [f"sample {esc(ev['sample'])}"] if ev.get("sample") else []
    if ev.get("plate") and ev.get("well"):
        parts.append(f"plate {esc(ev['plate'])}, well {esc(ev['well'])}")
    text = f'<p class="qp-rule">Place: {" · ".join(parts)}.</p>' if parts else ""
    checks = [c for c in ev.get("what_to_check") or () if isinstance(c, str)]
    if checks:
        items = "".join(f"<li>{esc(c)}</li>" for c in checks)
        text += f'<p class="qp-rule">What to check:</p><ul class="qp-ev-lines">{items}</ul>'
    text += f'<p class="qp-rule">{esc(TRACE_CARD_NOTE)}</p>'
    return text


TRACE_CARD_NOTE = (
    "Opened from Trace. The groups stay as they are; deciding this card is logged, and the "
    "study's numbers stay as analysed."
)


def _with_html(view: CardView) -> CardView:
    head = "".join(f"<th>{gene}</th>" for gene in view.genes)
    body = []
    for row in view.options:
        css = " ".join(c for c in ("recommended" if row.recommended else "",
                                   "chosen" if row.chosen else "") if c)  # fmt: skip
        tags = ' <span class="qp-tag">recommended</span>' if row.recommended else ""
        tags += ' <span class="qp-tag chosen">chosen</span>' if row.chosen else ""
        tags += (
            ' <span class="qp-tag miqe">not recommended (MIQE)</span>'
            if row.not_recommended
            else ""
        )
        cells = "".join(
            f'<td>{fc} <span class="qp-c qp-c-{slug(word)}">{word}</span></td>'
            for _, fc, word in row.cells
        )
        body.append(f'<tr class="{css}"><td>{row.label}{tags}</td>{cells}</tr>')
    markup = (
        f'<div class="qp-card" data-card="{view.id}">'
        f"<h3>{view.rank}. {view.title}</h3>"
        f'<p class="qp-impact">{view.impact_html}</p>'
        f'<p class="qp-status">{view.status_line}</p>'
        f'<p class="qp-explain">{view.explanation_html}</p>{view.where_html}'
        f'<table class="qp-options"><thead><tr><th>Option</th>{head}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )
    return CardView(**{**view.__dict__, "html": markup})


def cards_in_order(cards: Sequence[DecisionCard]) -> list[DecisionCard]:
    """Cards by rank (most impact first); cards opened from Trace come after the analysis's."""
    return sorted(cards, key=lambda c: (c.kind in ON_DEMAND_KINDS, c.rank))


def card_label(card: DecisionCard) -> str:
    """The card picker's label: rank and kind, or the place a Trace card is about; and status."""
    status = card.status.replace("_", " ")
    if card.kind in ON_DEMAND_KINDS:
        ev = card.evidence
        where = f"{ev.get('plate')}/{ev.get('well')}" if ev.get("well") else "tube"
        return f"Trace: sample {ev.get('sample')} · {where} ({status})"
    return f"{card.rank}. {card.kind.replace('_', ' ')} ({status})"


def next_card(cards: Sequence[DecisionCard]) -> DecisionCard | None:
    """The highest-ranked card still waiting for a decision, if any."""
    waiting = [c for c in cards_in_order(cards) if c.status in ("open", "pending_human")]
    return waiting[0] if waiting else None


def decision_counter(cards: Sequence[DecisionCard]) -> str:
    """E.g. ``2 decisions could change a conclusion · 1 made automatically``."""
    human = sum(1 for c in cards if c.impact.get("flips"))
    auto = sum(1 for c in cards if c.status == "auto_decided")
    noun = "decision" if human == 1 else "decisions"
    return f"{human} {noun} could change a conclusion · {auto} made automatically"


# ---------- the results table and Trace's one-line cell (the Excel export reads these) ----------

RESULT_COLUMNS = ("Gene", "Fold change", "95 % CI", "p", "Conclusion", "Holds", "Confidence")
TRACE_NOTHING = "nothing unusual"


def results_table(result: StudyResult) -> pd.DataFrame:
    """One row per compared gene, numbers rendered from facts (plain text for a data grid)."""
    facts = result.facts
    rows = []
    for gene, contrast in result.contrasts.items():
        s = slug(gene)
        lo = _fact_text(facts, f"f_ci_lo_{s}_recommended", f"{contrast.ci[0]:.2g}×")
        hi = _fact_text(facts, f"f_ci_hi_{s}_recommended", f"{contrast.ci[1]:.2g}×")
        grade = result.confidence.get(gene)
        robust = result.robustness.get(gene)
        rows.append(
            (
                gene,
                _fact_text(facts, f"f_fc_{s}_recommended", f"{contrast.fc:.2g}×"),
                f"{lo} – {hi}",
                _fact_text(facts, f"f_p_{s}_recommended", f"{contrast.p:.2g}"),
                conclusion_word(contrast.conclusion),
                _fact_text(facts, f"f_holds_{s}", f"{robust.holds:.0%}" if robust else ""),
                grade.level if grade else "",
            )
        )
    return pd.DataFrame(rows, columns=list(RESULT_COLUMNS))


def place_address(place) -> str:
    """``HMBS_20080318/K22 (2016)`` for a well, ``2016 (tube)`` for a sample's tube."""
    if place.well:
        return f"{place.plate}/{place.well} ({place.sample})"
    return f"{place.sample} (tube)"


def trace_cell(result) -> str:
    """One line for a result's top place: ``HMBS_20080318/K22 (2016): changes the call``.

    ``nothing unusual`` when the trace found no place to look.
    """
    from qpilot.explain.trace_text import CONSEQUENCE_WORDS

    if not result.places:
        return TRACE_NOTHING
    top = result.places[0]
    return f"{place_address(top)}: {CONSEQUENCE_WORDS.get(top.consequence, top.consequence)}"
