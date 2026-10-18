"""Explanations whose numbers are never typed: every number is a ``{{fact_id}}`` token.

Each template turns the study's facts (``StudyResult.facts``) into one short paragraph. The text
is built from the facts that exist, so the same template works for any study, and it is checked
with ``qpilot.core.validator.validate`` before it is returned: every token must name a known fact
and no digit may appear outside a token or an allowed name (a gene such as ``ODC1``).

:func:`render_template` returns the same paragraph three ways:

* ``tokens``: the token text (what the model layer validates and stores);
* ``plain``: numbers rendered with each fact's format (CLI, logs);
* ``html``: every number wrapped in ``<span class="fact" data-fact="f_...">``, so the app can show
  which fact a number came from; all other text is HTML-escaped.

Templates: ``refset_v1``, ``cutoff_v1``, ``undetermined_auto_v1``, ``undetermined_v1``,
``ampcall_v1`` (card explanations, keyed by ``DecisionCard.rationale_template``), ``summary_v1``,
``meter_v1`` and ``confidence_v1`` (needs ``gene=``). Feature templates, written in their own
modules and registered here: ``evidence_v1``, ``grt_v1`` and ``runreview_v1``
(:mod:`qpilot.explain.evidence_text`), ``instrument_gate_v1``
(:mod:`qpilot.explain.instrument_text`), ``lookback_v1`` and ``position_v1``
(:mod:`qpilot.explain.lookback_text`). Each renders a digit-free sentence when its facts are
absent; the last three need their structured result for anything more.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from qpilot.core.facts import render_fact, slug
from qpilot.core.validator import TOKEN, render_tokens, validate
from qpilot.qpcr.refgenes import CUTOFF_M
from qpilot.schemas import DecisionCard, Fact

Facts = Mapping[str, Fact]


@dataclass(frozen=True)
class RenderedText:
    """One rendered template: token text, plain text and HTML, plus the fact ids it cites."""

    key: str
    tokens: str
    plain: str
    html: str
    fact_ids: tuple[str, ...]


class TemplateError(ValueError):
    """A template cannot be rendered from these facts (missing fact or a naked number)."""


# ---------- helpers ----------


def _t(fid: str) -> str:
    return "{{" + fid + "}}"


def _need(facts: Facts, *ids: str) -> None:
    missing = [fid for fid in ids if fid not in facts]
    if missing:
        raise TemplateError(f"missing facts: {', '.join(missing)}")


def _value(facts: Facts, fid: str) -> float | int | str:
    _need(facts, fid)
    return facts[fid].value


def _gene_name(facts: Facts, gene_slug: str) -> str:
    """Display name of a gene, from the path of its primary fold-change fact."""
    fact = facts.get(f"f_fc_{gene_slug}_recommended")
    if fact and fact.path.startswith("contrasts.") and fact.path.endswith(".fc"):
        return fact.path[len("contrasts.") : -len(".fc")]
    return gene_slug.upper()


def _genes_with(facts: Facts, suffix: str, card: DecisionCard | None) -> list[str]:
    """Slugs of genes that have ``f_fc_<gene>_<suffix>``: the card's order, else sorted."""
    if card is not None and card.options:
        ordered = [slug(gene) for gene in card.options[0].per_gene]
    else:
        pattern = re.compile(rf"^f_fc_([a-z0-9_]+)_{re.escape(suffix)}$")
        ordered = sorted(m.group(1) for fid in facts if (m := pattern.match(fid)))
    return [g for g in ordered if f"f_fc_{g}_{suffix}" in facts]


def _flips_sentence(facts: Facts, flipped_id: str) -> str:
    """How many genes this choice flips, and therefore who decides it."""
    if int(_value(facts, flipped_id)) > 0:
        return (
            f"{_t(flipped_id)} genes out of {_t('f_n_genes')} change their conclusion with this "
            "choice alone, so a person makes it."
        )
    return (
        "No gene changes its conclusion with this choice, so it was decided automatically and "
        "logged; you can reopen it."
    )


def _cut_ids(facts: Facts) -> list[str]:
    """``cut_10``, ``cut_15``, ... in numeric order, from the ``f_n_hi_cut_*`` facts."""
    cuts = [fid[len("f_n_hi_") :] for fid in facts if fid.startswith("f_n_hi_cut_")]
    return sorted(cuts, key=lambda c: int(c.split("_")[1]))


def _list(items: list[str], joiner: str = "or") -> str:
    if len(items) <= 2:
        return f" {joiner} ".join(items)
    return ", ".join(items[:-1]) + f" {joiner} " + items[-1]


# ---------- the templates (each returns token text) ----------


def _refset(facts: Facts, card: DecisionCard | None, gene: str | None) -> str:
    _need(facts, "f_order_1", "f_worst_ref", "f_n_flipped_refset", "f_n_genes")
    stable = [fid for fid in facts if re.fullmatch(r"f_m_\d+", fid)]
    any_stable = any(float(facts[fid].value) < CUTOFF_M for fid in stable)
    pair = f"{_t('f_order_1')} and {_t('f_order_2')}" if "f_order_2" in facts else _t("f_order_1")
    text = (
        f"geNorm's stepwise ranking keeps {pair} as the most stable and drops "
        f"{_t('f_worst_ref')} first. "
    )
    if not any_stable:
        text += (
            "None of the candidates reaches geNorm's usual stability cut-off, so which control "
            "genes to use is a judgement call. "
        )
    genes = _genes_with(facts, "worst", card)
    if genes:
        pairs = [
            f"{_gene_name(facts, g)} {_t(f'f_fc_{g}_recommended')} vs {_t(f'f_fc_{g}_worst')}"
            for g in genes
        ]
        text += (
            f"With the recommended set versus {_t('f_worst_ref')} alone: {_list(pairs, 'and')}. "
        )
    text += _flips_sentence(facts, "f_n_flipped_refset")
    if "f_n_flipped_refset_min3" in facts:
        text += (
            f" Even between sets of three or more control genes, "
            f"{_t('f_n_flipped_refset_min3')} of {_t('f_n_genes')} change."
        )
    if {"f_ref_pair_top", "f_ref_ratio_top", "f_ref_ratio_top_p"} <= set(facts):
        text += (
            f" The control genes are not neutral here: the ratio {_t('f_ref_pair_top')} itself "
            f"differs {_t('f_ref_ratio_top')} between the groups (p = {_t('f_ref_ratio_top_p')})"
        )
        if {"f_n_ref_pairs_flagged", "f_n_ref_pairs", "f_ref_flag_fold"} <= set(facts):
            text += (
                f", and {_t('f_n_ref_pairs_flagged')} of {_t('f_n_ref_pairs')} pairs differ by at "
                f"least {_t('f_ref_flag_fold')}"
            )
        text += "."
    return text


def _cutoff(facts: Facts, card: DecisionCard | None, gene: str | None) -> str:
    _need(facts, "f_n_flipped_cutoff", "f_n_genes")
    cuts = _cut_ids(facts)
    text = (
        "The high group is the top fraction of samples by the marker gene's expression; where "
        "to draw that line is a convention, not a measurement. "
    )
    if cuts:
        sizes = _list([_t(f"f_n_hi_{c}") for c in cuts])
        text += f"Depending on the line, the high group has {sizes} samples. "
    for g in _genes_with(facts, cuts[len(cuts) // 2] if cuts else "cut_15", card):
        values = [_t(f"f_fc_{g}_{c}") for c in cuts if f"f_fc_{g}_{c}" in facts]
        text += f"{_gene_name(facts, g)} is {_list(values)} respectively. "
    return text + _flips_sentence(facts, "f_n_flipped_cutoff")


def _undetermined(facts: Facts, card: DecisionCard | None, gene: str | None) -> str:
    _need(facts, "f_n_undetermined", "f_n_unknown_wells", "f_pct_undetermined")
    _need(facts, "f_n_flipped_undetermined", "f_n_genes")
    text = (
        f"{_t('f_n_undetermined')} of {_t('f_n_unknown_wells')} sample wells "
        f"({_t('f_pct_undetermined')}) never amplified. They can be dropped or counted as very "
        "low. "
    )
    pairs = [
        f"{_gene_name(facts, g)} {_t(f'f_fc_{g}_drop')} vs {_t(f'f_fc_{g}_cap')}"
        for g in _genes_with(facts, "drop", card)
        if f"f_fc_{g}_cap" in facts
    ]
    if pairs:
        text += f"Dropped versus counted: {_list(pairs, 'and')}. "
    return text + _flips_sentence(facts, "f_n_flipped_undetermined")


def _amp_rules(facts: Facts) -> tuple[str | None, list[str]]:
    """(primary rule slug, other rule slugs sorted) from the ``f_amp_label_*`` facts."""
    prefix = "f_amp_label_"
    labels = {fid[len(prefix) :]: facts[fid].value for fid in facts if fid.startswith(prefix)}
    primary = facts["f_amp_primary"].value if "f_amp_primary" in facts else None
    first = next((s for s, v in sorted(labels.items()) if v == primary), None)
    return first, sorted(s for s in labels if s != first)


def _ampcall(facts: Facts, card: DecisionCard | None, gene: str | None) -> str:
    text = (
        "Which wells count as amplified is a choice. LinRegPCR's own call counts a well when it "
        "finds a starting quantity; a Cq cut-off calls every well with a later Cq not detected, "
        "for every gene including the control genes. "
    )
    primary, others = _amp_rules(facts)
    if "f_n_flipped_amp_call" not in facts or primary is None or not others:
        return text + "This analysis uses LinRegPCR's own call only."
    _need(facts, "f_n_genes")
    text += f"This analysis uses {_t('f_amp_primary')}"
    if f"f_n_undetermined_amp_{primary}" in facts:
        text += f", under which {_t(f'f_n_undetermined_amp_{primary}')} study wells have no value"
    parts = []
    for s in others:
        _need(facts, f"f_n_flipped_amp_{s}")
        part = (
            f"with {_t(f'f_amp_label_{s}')}, {_t(f'f_n_flipped_amp_{s}')} of {_t('f_n_genes')} "
            "genes change their conclusion"
        )
        if f"f_n_undetermined_amp_{s}" in facts:
            part += f" ({_t(f'f_n_undetermined_amp_{s}')} study wells without a value)"
        parts.append(part)
    text += ". Changing only this choice: " + "; ".join(parts) + ". "
    return text + _flips_sentence(facts, "f_n_flipped_amp_call")


def _summary(facts: Facts, card: DecisionCard | None, gene: str | None) -> str:
    _need(facts, "f_n_plates", "f_n_reactions", "f_n_samples", "f_n_hi", "f_n_lo")
    counts = (
        f"{_t('f_n_plates')} plates · {_t('f_n_samples')} samples · {_t('f_n_reactions')} "
        "reactions. "
    )
    if "f_group_a" in facts and "f_group_b" in facts:  # groups from a confirmed design
        return counts + (
            f"{_t('f_group_a')}: {_t('f_n_hi')} biological units; "
            f"{_t('f_group_b')}: {_t('f_n_lo')}."
        )
    return counts + f"High group {_t('f_n_hi')} samples, rest {_t('f_n_lo')}."


def _meter(facts: Facts, card: DecisionCard | None, gene: str | None) -> str:
    _need(facts, "f_n_cells", "f_n_genes", "f_n_hold_lt_80")
    return (
        f"Every conclusion was recomputed under {_t('f_n_cells')} reasonable analyses. "
        f"{_t('f_n_hold_lt_80')} of {_t('f_n_genes')} genes keep their conclusion in fewer than "
        "four out of five of them."
    )


def _confidence(facts: Facts, card: DecisionCard | None, gene: str | None) -> str:
    if not gene:
        raise TemplateError("confidence_v1 needs gene=")
    g = slug(gene)
    _need(facts, f"f_level_{g}", f"f_holds_{g}", f"f_min_flip_{g}", "f_n_cells")
    text = (
        f"{gene}: {_t(f'f_level_{g}')} confidence. The conclusion holds in {_t(f'f_holds_{g}')} "
        f"of {_t('f_n_cells')} analyses; "
    )
    flips = int(_value(facts, f"f_min_flip_{g}"))
    if flips == 0:
        text += "no combination of the reasonable choices flips it."
    elif flips == 1:
        text += "changing a single choice can flip it."
    else:
        text += f"changing {_t(f'f_min_flip_{g}')} choices at once can flip it."
    if f"f_mde_fold_{g}" in facts:
        text += f" The smallest change this design detects reliably is {_t(f'f_mde_fold_{g}')}."
    return text


# ---------- feature templates (registered here, written in their own modules) ----------
# Imported inside each wrapper: those modules import this one (RenderedText, to_html), and the
# structured renderers (a ledger, Gate lines, a lookback) stay where their feature lives.

NO_INSTRUMENT_FILE = "No instrument run file has been read for this study."


def _evidence(facts: Facts, card: DecisionCard | None, gene: str | None) -> str:
    from qpilot.explain.evidence_text import evidence_text

    return evidence_text(facts, card, gene)


def _gate_rt(facts: Facts, card: DecisionCard | None, gene: str | None) -> str:
    from qpilot.explain.evidence_text import gate_rt_text

    return gate_rt_text(facts, card, gene)


def _runreview(facts: Facts, card: DecisionCard | None, gene: str | None) -> str:
    from qpilot.explain.evidence_text import runreview_text

    return runreview_text(facts, card, gene)


def _structured_only(key: str, renderer: str) -> TemplateError:
    return TemplateError(f"{key} renders from the structured result; use {renderer}")


def _instrument_gate(facts: Facts, card: DecisionCard | None, gene: str | None) -> str:
    """``instrument_gate_v1``: a digit-free sentence without G-INSTR facts.

    The wording of each line depends on its code, which lives on the Gate line, not in the
    facts: with G-INSTR facts present, render the lines with
    ``qpilot.explain.instrument_text.render_gate``.
    """
    if any(fid.startswith("f_instr_") for fid in facts):
        raise _structured_only("instrument_gate_v1", "explain.instrument_text.render_gate(lines)")
    return NO_INSTRUMENT_FILE


def _lookback(facts: Facts, card: DecisionCard | None, gene: str | None) -> str:
    """``lookback_v1``: a digit-free sentence without lookback facts (else use the result)."""
    from qpilot.explain.lookback_text import NO_LOOKBACK

    if "f_lookback_instrument" in facts:
        raise _structured_only("lookback_v1", "explain.lookback_text.lookback_tokens(result)")
    return NO_LOOKBACK


def _position(facts: Facts, card: DecisionCard | None, gene: str | None) -> str:
    """``position_v1``: a digit-free sentence without position facts (else use the report)."""
    from qpilot.explain.lookback_text import NO_POSITIONS

    if "f_position_base_rate" in facts:
        raise _structured_only("position_v1", "explain.lookback_text.position_tokens(report)")
    return NO_POSITIONS


Template = Callable[[Facts, "DecisionCard | None", "str | None"], str]

TEMPLATES: dict[str, Template] = {
    "refset_v1": _refset,
    "cutoff_v1": _cutoff,
    "undetermined_auto_v1": _undetermined,
    "undetermined_v1": _undetermined,
    "ampcall_v1": _ampcall,
    "summary_v1": _summary,
    "meter_v1": _meter,
    "confidence_v1": _confidence,
    "evidence_v1": _evidence,
    "grt_v1": _gate_rt,
    "runreview_v1": _runreview,
    "instrument_gate_v1": _instrument_gate,
    "lookback_v1": _lookback,
    "position_v1": _position,
}


# ---------- rendering ----------


def to_html(tokens: str, facts: Facts) -> str:
    """Escape the text and wrap each rendered number in a span naming its fact."""
    out, last = [], 0
    for match in TOKEN.finditer(tokens):
        out.append(html.escape(tokens[last : match.start()]))
        fid = match.group(1)
        value = html.escape(render_fact(facts[fid]))
        out.append(f'<span class="fact" data-fact="{fid}" title="{fid}">{value}</span>')
        last = match.end()
    out.append(html.escape(tokens[last:]))
    return "".join(out)


def render_template(
    key: str,
    facts: Facts,
    *,
    card: DecisionCard | None = None,
    gene: str | None = None,
    allowed_names: Iterable[str] = (),
) -> RenderedText:
    """Render one template from a study's facts.

    Args:
        key: Template key, e.g. a card's ``rationale_template``.
        facts: The study's facts (``StudyResult.facts``).
        card: The card being explained (gives the genes' order); optional.
        gene: The gene, for ``confidence_v1``.
        allowed_names: Extra names that may appear verbatim (gene names with digits).

    Raises:
        KeyError: Unknown template key.
        TemplateError: A needed fact is missing or the text fails the validator.
    """
    if key not in TEMPLATES:
        raise KeyError(f"unknown template {key!r}; known: {', '.join(sorted(TEMPLATES))}")
    tokens = TEMPLATES[key](facts, card, gene)
    names = set(allowed_names) | {_gene_name(facts, g) for g in _all_gene_slugs(facts)}
    if gene:
        names.add(gene)
    check = validate(tokens, facts, names)
    if not check.ok:
        raise TemplateError(f"{key}: {check.error()}")
    cited = tuple(dict.fromkeys(TOKEN.findall(tokens)))
    return RenderedText(
        key=key,
        tokens=tokens,
        plain=render_tokens(tokens, facts),
        html=to_html(tokens, facts),
        fact_ids=cited,
    )


def _all_gene_slugs(facts: Facts) -> list[str]:
    return [fid[len("f_fc_") : -len("_recommended")] for fid in facts if
            fid.startswith("f_fc_") and fid.endswith("_recommended")]  # fmt: skip
