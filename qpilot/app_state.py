"""View-models for the one-page app: pure functions from engine output to rows and escaped HTML.

Nothing here imports Gradio, so every view can be tested without a browser. Two rules hold for
everything these functions return:

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
from qpilot.ai.profile import autonomy_policy
from qpilot.core.facts import render_fact, slug
from qpilot.explain.templates import TemplateError, render_template, to_html
from qpilot.qpcr.contrast import ConclusionRule
from qpilot.schemas import DecisionCard, Fact, Grade, StudyResult

Facts = Mapping[str, Fact]

CONCLUSION_WORDS = {"up": "up", "down": "down", "none": "no call"}
FLIPPED_FACT = {
    "reference_set": "f_n_flipped_refset",
    "group_cutoff": "f_n_flipped_cutoff",
    "undetermined": "f_n_flipped_undetermined",
}
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


def _fact_html(facts: Facts, fid: str, fallback: str = "") -> str:
    """A fact's rendered value wrapped in a span naming the fact (escaped)."""
    if fid not in facts:
        return esc(fallback)
    return to_html("{{" + fid + "}}", facts)


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
    marker = design.group_var.removesuffix("_high") or design.group_var
    return (
        f"Groups by {marker} expression, top {design.cut:.0%}: {marker}-high {design.n_hi} vs "
        f"rest {design.n_lo}. Expression-defined, not a clinical call."
    ).replace("%", " %")


# ---------- robustness meter ----------


@dataclass(frozen=True)
class MeterRow:
    """One gene in the robustness meter."""

    gene: str
    conclusion: str
    fold_change: str
    holds: float
    holds_text: str
    level: str


def meter_rows(result: StudyResult, genes: Iterable[str] | None = None) -> list[MeterRow]:
    """Rows for ``genes`` (default: every compared gene), in the order given."""
    facts = result.facts
    rows = []
    for gene in genes if genes is not None else result.robustness:
        if gene not in result.robustness:
            continue
        s, robust = slug(gene), result.robustness[gene]
        grade = result.confidence.get(gene)
        rows.append(
            MeterRow(
                gene=gene,
                conclusion=conclusion_word(robust.conclusion),
                fold_change=_fact_text(facts, f"f_fc_{s}_recommended", f"{robust.fc:.2g}×"),
                holds=robust.holds,
                holds_text=_fact_text(facts, f"f_holds_{s}", f"{robust.holds:.0%}"),
                level=grade.level if grade else "",
            )
        )
    return rows


def meter_html(result: StudyResult, genes: Iterable[str] | None = None) -> str:
    """HTML bars: how often each conclusion holds across the reasonable analyses."""
    caption = render_template("meter_v1", result.facts).html
    of_cells = f" of {_fact_html(result.facts, 'f_n_cells')}" if "f_n_cells" in result.facts else ""
    bars = []
    for row in meter_rows(result, genes):
        width = max(0.0, min(1.0, row.holds)) * 100
        tone = "solid" if row.holds >= 0.8 else "fragile"
        holds = _fact_html(result.facts, f"f_holds_{slug(row.gene)}", row.holds_text)
        bars.append(
            f'<div class="qp-meter-row {tone}"><span class="qp-gene">{esc(row.gene)}</span>'
            f'<span class="qp-call">{esc(row.fold_change)} {esc(row.conclusion)}</span>'
            f'<span class="qp-bar"><span class="qp-fill" style="width:{width:.1f}%"></span></span>'
            f'<span class="qp-holds">holds in {holds}{of_cells}</span></div>'
        )
    return f'<div class="qp-meter"><p>{caption}</p>{"".join(bars)}</div>'


# ---------- confidence ----------


def confidence_badge(grade: Grade, gene: str | None = None, facts: Facts | None = None) -> str:
    """A level badge with its reasons (and the confidence sentence when facts are given)."""
    level = esc(grade.level)
    css = slug(grade.level)
    parts = [f'<span class="qp-badge level-{css}">{level}</span>']
    if gene and facts is not None:
        try:
            parts.append(f" {render_template('confidence_v1', facts, gene=gene).html}")
        except TemplateError:
            pass
    if grade.reasons:
        items = "".join(f"<li>{esc(reason)}</li>" for reason in grade.reasons)
        parts.append(f'<ul class="qp-reasons">{items}</ul>')
    return f'<div class="qp-confidence">{"".join(parts)}</div>'


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
        return f"Decided by {card.decided_by or 'someone'}: {chosen}.{reason}"
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
    genes = tuple(card.options[0].per_gene) if card.options else ()
    rows = []
    for option in card.options:
        context = option.id.removesuffix("_alone")
        cells = tuple(
            (
                esc(gene),
                esc(_fact_text(facts, f"f_fc_{slug(gene)}_{context}", f"{result.fc:.2g}×")),
                esc(conclusion_word(result.conclusion)),
            )
            for gene, result in option.per_gene.items()
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
        needs_human=bool(card.impact.get("flips")),
        status_line=esc(_status_line(card, labels, pending_option)),
        impact_html=impact,
        explanation_html=explanation_html,
        explanation_plain=explanation_plain,
        genes=tuple(esc(g) for g in genes),
        options=tuple(rows),
        html="",
    )
    return _with_html(view)


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
        f'<p class="qp-explain">{view.explanation_html}</p>'
        f'<table class="qp-options"><thead><tr><th>Option</th>{head}</tr></thead>'
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )
    return CardView(**{**view.__dict__, "html": markup})


def cards_in_order(cards: Sequence[DecisionCard]) -> list[DecisionCard]:
    """Cards by rank (most impact first)."""
    return sorted(cards, key=lambda c: c.rank)


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


# ---------- results table, policy and footer ----------

RESULT_COLUMNS = ("Gene", "Fold change", "95 % CI", "p", "Conclusion", "Holds", "Confidence")


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


def policy_lines() -> list[str]:
    """The three-line autonomy policy (escaped), as fixed in code."""
    return [esc(line) for line in autonomy_policy()]


def footer_lines(version: str, vendored_commit: str) -> list[str]:
    """Footer: research use only, what qPilot never does, version and vendored commit."""
    return [esc(line) for line in FOOTER] + [
        esc(f"qPilot {version} · LinRegPCR (rdmlpython) @ {vendored_commit[:7]}")
    ]
