"""Explain one Decision Card in words: the chosen model if it passes the validator, else a template.

The model sees the card without any numbers (ids, kinds, option labels, whether it can flip a
conclusion) and a facts table of the numbers it may cite as ``{{fact_id}}`` tokens. Its text is
validated, and it must cite the counts the card is about (:func:`required_facts`: how many
genes change their conclusion with the choice; on the amplification-call card, under each rule
other than the one in use). On failure it gets one retry with the reason, then the template is
used and ``fallback`` is True. The result always carries the token text, so the app can render
each number with its fact id.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping

from pydantic import BaseModel

from qpilot.ai import payload_log
from qpilot.ai.client import ModelClient, ModelUnavailable
from qpilot.ai.profile import Profile
from qpilot.ai.prompts import SYSTEM_EXPLAIN
from qpilot.core.card_kinds import TITLES
from qpilot.core.facts import render_fact, slug
from qpilot.core.validator import TOKEN, render_tokens, validate
from qpilot.schemas import DecisionCard, Fact

#: Card kind -> title: a live view of the registry in ``core/card_kinds.py`` (kinds a plugin
#: registers later appear here too; the original four keep their titles).
KIND_TITLE = TITLES
#: The fact that counts the genes a card's choice flips, by card kind.
FLIP_FACT = {
    "reference_set": "f_n_flipped_refset",
    "group_cutoff": "f_n_flipped_cutoff",
    "undetermined": "f_n_flipped_undetermined",
}


class ExplainResult(BaseModel):
    """An explanation: token text, the same text with numbers rendered, and how it was made."""

    tokens: str
    plain: str
    validated: bool
    fallback: bool
    provider: str
    error: str | None = None


def card_view(card: DecisionCard) -> dict:
    """The card as the model sees it: structure and labels, no numbers."""
    return {
        "card_id": card.id,
        "kind": card.kind,
        "title": KIND_TITLE.get(card.kind, card.kind),
        "can_flip_a_conclusion": bool(card.impact.get("flips")),
        # A choice that changes nothing at the recommended settings can still flip conclusions
        # at other reasonable settings; then a person decides it, and the model must say so.
        "can_flip_a_conclusion_at_other_settings": bool(card.impact.get("flips_anywhere")),
        "status": card.status,
        "recommended": card.recommended,
        "options": [{"id": o.id, "label": o.label} for o in card.options],
        "fact_ids": card.facts,
    }


def card_names(card: DecisionCard) -> set[str]:
    """Labels and ids that may appear verbatim (they can contain digits, e.g. SDHA(1))."""
    names = {card.id}
    for option in card.options:
        names |= {option.id, option.label, *option.per_gene}
    for value in card.evidence.values():  # e.g. the reference genes in geNorm evidence
        if isinstance(value, dict):
            names |= {k for k in value if isinstance(k, str)}
        elif isinstance(value, list | tuple):
            names |= {v for v in value if isinstance(v, str)}
    return names


def fact_table(facts: Mapping[str, Fact], ids: Iterable[str]) -> dict[str, dict[str, str]]:
    """What the model may cite: each fact's value for reading, and the token to write."""
    return {
        f: {"value_for_reading_only": render_fact(facts[f]), "write_exactly": "{{" + f + "}}"}
        for f in ids
        if f in facts
    }


def required_facts(card: DecisionCard, facts: Mapping[str, Fact]) -> list[str]:
    """The count facts a model's explanation of ``card`` must cite, or the template is used.

    These are the numbers the card is about: how many genes change their conclusion with the
    choice (``f_n_flipped_refset`` and the like). On the amplification-call card it is that
    count under each rule other than the one in use (every ``f_n_flipped_amp_<rule>``; the rule
    in use is the analysis itself, so its own count is zero by construction). Only facts on the
    card and in ``facts`` are required.
    """
    if card.kind == "amp_call":
        wanted = [f"f_n_flipped_amp_{slug(o.id)}" for o in card.options if o.id != card.recommended]
    else:
        wanted = [FLIP_FACT[card.kind]] if card.kind in FLIP_FACT else []
    return [fid for fid in wanted if fid in card.facts and fid in facts]


def _uncited(text: str, required: Iterable[str]) -> list[str]:
    cited = set(TOKEN.findall(text))
    return [fid for fid in required if fid not in cited]


def template_explanation(card: DecisionCard, facts: Mapping[str, Fact]) -> str:
    """The deterministic explanation, in ``{{fact_id}}`` tokens.

    Uses Dev 1's ``qpilot.explain.templates`` when it is present; otherwise a generic sentence.
    """
    try:
        from qpilot.explain.templates import render_template  # Dev 1's templates

        rendered = render_template(card.rationale_template, facts)
        text = getattr(rendered, "tokens", None) or getattr(rendered, "plain", None)
        if isinstance(text, str) and text:
            return text
    except (ImportError, KeyError, AttributeError, ValueError):
        pass
    labels = {o.id: o.label for o in card.options}
    parts = [f"{KIND_TITLE.get(card.kind, card.kind)}."]
    flipped = next((f for f in card.facts if f.startswith("f_n_flipped") and f in facts), None)
    if flipped and card.impact.get("flips"):
        parts.append(f"{{{{{flipped}}}}} genes change their conclusion with this choice alone.")
    parts.append(f"Recommended: {labels.get(card.recommended, card.recommended)}.")
    if card.status == "auto_decided":
        parts.append("No option changes any conclusion, so it was decided automatically.")
    elif card.impact.get("flips"):
        parts.append("This choice can change a conclusion, so a person decides it.")
    return " ".join(parts)


def explain_card(
    card: DecisionCard,
    facts: Mapping[str, Fact],
    profile: Profile | None = None,
    client: ModelClient | None = None,
    allowed_names: Iterable[str] = (),
    fewshots: list[dict[str, str]] | None = None,
) -> ExplainResult:
    """Explain ``card`` with the chosen model, falling back to the template."""
    profile = profile or Profile()
    client = client or ModelClient.from_env()
    names = set(allowed_names) | card_names(card)
    template = template_explanation(card, facts)
    if not client.available:
        return ExplainResult(
            tokens=template,
            plain=render_tokens(template, facts),
            validated=validate(template, facts, names).ok,
            fallback=True,
            provider=client.provider,
        )
    table = fact_table(facts, card.facts)
    required = required_facts(card, facts)
    user = json.dumps(
        {
            "card": card_view(card),
            "facts": table,
            "must_cite": [table[fid]["write_exactly"] for fid in required],
            "lab_profile": profile.model_dump(),
            "examples_from_this_lab": fewshots or [],
        },
        ensure_ascii=False,
    )
    messages = [{"role": "user", "content": user}]
    error = None
    for _attempt in range(2):
        try:
            text = client.complete(SYSTEM_EXPLAIN, messages).strip()
        except ModelUnavailable as err:
            error = str(err)
            break
        check = validate(text, facts, names)
        missing = _uncited(text, required)
        if check.ok and not missing:
            return ExplainResult(
                tokens=text,
                plain=render_tokens(text, facts),
                validated=True,
                fallback=False,
                provider=client.provider,
            )
        if check.ok:
            tokens = ", ".join("{{" + fid + "}}" for fid in missing)
            error = f"the explanation does not cite {tokens}, the counts this card is about"
            retry = f"Rejected: {error}. Rewrite it citing them, following the token rule."
        else:
            error = check.error()
            retry = f"Rejected: {error}. Rewrite following the token rule."
        messages = [
            *messages,
            {"role": "assistant", "content": text},
            {"role": "user", "content": retry},
        ]
    return ExplainResult(
        tokens=template,
        plain=render_tokens(template, facts),
        validated=validate(template, facts, names).ok,
        fallback=True,
        provider=client.provider,
        error=error,
    )


def log_line(result: ExplainResult, client: ModelClient) -> dict:
    """The ``ai_calls.jsonl`` line for an explanation."""
    return payload_log.log_entry(
        "explain_card",
        client.provider,
        client.model,
        client.last_meta,
        result.tokens,
        result.validated and not result.fallback,
        result.fallback,
    )
