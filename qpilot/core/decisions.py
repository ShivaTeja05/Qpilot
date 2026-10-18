"""Decision Cards and the escalation rule: which choices a human must make, and who may decide.

Domain-agnostic. The plugin describes each card with a :class:`CardSpec` (which grid dimension it
is about, its options, the recommended option, and the plugin's own evidence, template key and
fact ids). The core fills in the consequences of each option from the decision space, measures
the card's impact from the robustness summary, ranks the cards, and enforces one rule **in code**:

    A choice that can flip any conclusion is a human decision, at every autonomy level and for
    every actor. An agent (or the system) asking to make it gets ``pending_human``.

A card whose dimension flips no conclusion is decided automatically (recommended option, actor
``system``) and logged; a human can reopen it.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from qpilot.schemas import (
    Actor,
    Autonomy,
    CardKind,
    CardOption,
    DecisionCard,
    DecisionOutcome,
    DecisionSpace,
    GeneRobustness,
)

if TYPE_CHECKING:
    from qpilot.core.store import StudyStore

MAX_REASON = 500
AUTO_REASON = "Decided automatically: no option on this card changes any conclusion."
AUTO_REASON_ELSEWHERE = (
    "Decided automatically: at the recommended settings no option on this card changes any "
    "conclusion. At other settings it can, so an agent must ask a person to change it."
)


class DecisionError(ValueError):
    """A decision request that is malformed (unknown card or option, bad reason)."""


class OptionSpec(BaseModel):
    """One option of a card: its id, its label and the dimension value it stands for."""

    id: str
    label: str
    value: Any


class CardSpec(BaseModel):
    """What a plugin tells the core about one card; the core adds consequences and impact."""

    card_id: str
    kind: CardKind
    dimension: str
    options: list[OptionSpec]
    recommended: str
    rationale_template: str
    evidence: dict[str, Any] = {}
    facts: list[str] = []


def effective_level(user_level: Autonomy, impact: dict[str, Any]) -> Autonomy:
    """The autonomy that actually applies to a card: a flipping card is always ``suggest``."""
    if impact.get("flips") and user_level in ("decide_and_tell", "automatic"):
        return "suggest"
    return user_level


def card_impact(grid_summary: dict[str, GeneRobustness], dimension: str) -> dict[str, Any]:
    """How much changing ``dimension`` alone can move the items' conclusions."""
    flipped = [s for s in grid_summary.values() if s.impact[dimension]["flips"]]
    deltas = [float(s.impact[dimension]["max_delta_log2fc"]) for s in grid_summary.values()]
    return {
        "flips": bool(flipped),
        "n_genes_flipped": len(flipped),
        "max_delta_log2fc": max(deltas, default=0.0),
    }


def rank_cards(cards: list[DecisionCard]) -> list[DecisionCard]:
    """Order cards by genes flipped, then by the largest fold-change shift; renumber ranks 1..n."""
    ordered = sorted(
        cards,
        key=lambda c: (-c.impact["n_genes_flipped"], -c.impact["max_delta_log2fc"], c.id),
    )
    return [c.model_copy(update={"rank": i}) for i, c in enumerate(ordered, start=1)]


def _options(space: DecisionSpace, spec: CardSpec, headline_items: list[str]) -> list[CardOption]:
    if spec.dimension not in space.dimensions:
        raise DecisionError(f"card {spec.card_id}: unknown dimension {spec.dimension!r}")
    out = []
    for option in spec.options:
        if option.value not in space.dimensions[spec.dimension]:
            raise DecisionError(f"card {spec.card_id}: option {option.id!r} is not in the grid")
        results = space.evaluate({**space.primary, spec.dimension: option.value})
        out.append(
            CardOption(
                id=option.id,
                label=option.label,
                per_gene={item: results[item] for item in headline_items},
            )
        )
    return out


def build_cards(
    space: DecisionSpace,
    grid_summary: dict[str, GeneRobustness],
    option_sets: list[CardSpec],
    headline_items: list[str],
    autonomy: Autonomy = "suggest",
    grid: Any = None,
) -> list[DecisionCard]:
    """Build one Decision Card per spec, with each option's consequence, impact and rank.

    ``impact["flips"]`` (and the auto-decision) looks at the other choices at their
    recommended settings; ``impact["flips_anywhere"]`` looks at every combination in the grid,
    so a choice that can change a conclusion at some setting always needs a person when an
    agent asks. ``grid`` is computed from ``space`` when not given.
    """
    from qpilot.core.robustness import flipped_anywhere, run_grid

    grid = run_grid(space) if grid is None else grid
    cards = []
    for spec in option_sets:
        if spec.recommended not in {o.id for o in spec.options}:
            raise DecisionError(f"card {spec.card_id}: recommended option is not an option")
        impact = card_impact(grid_summary, spec.dimension)
        anywhere = flipped_anywhere(grid, spec.dimension)
        impact["flips_anywhere"] = bool(anywhere)
        impact["n_genes_flipped_anywhere"] = len(anywhere)
        card = DecisionCard(
            id=spec.card_id,
            kind=spec.kind,
            rank=0,
            impact=impact,
            evidence=spec.evidence,
            options=_options(space, spec, headline_items),
            recommended=spec.recommended,
            rationale_template=spec.rationale_template,
            facts=spec.facts,
            autonomy=autonomy,
            effective_autonomy=effective_level(autonomy, impact),
        )
        if not impact["flips"]:
            card = card.model_copy(
                update={
                    "status": "auto_decided",
                    "decision": spec.recommended,
                    "reason": AUTO_REASON_ELSEWHERE if anywhere else AUTO_REASON,
                    "decided_by": "system",
                }
            )
        cards.append(card)
    return rank_cards(cards)


def needs_human(card: DecisionCard) -> bool:
    """True when the card can flip a conclusion at any setting (or is in teaching mode)."""
    impact = card.impact
    return (
        bool(impact.get("flips"))
        or bool(impact.get("flips_anywhere"))
        or card.effective_autonomy == "teach"
    )


def clean_reason(reason: str | None, what: str = "reason", limit: int = MAX_REASON) -> str:
    """A reason (or comment) as the log keeps it: one line, stripped, not empty, within ``limit``.

    Args:
        reason: The text a person or an agent gave.
        what: What the text is called in the error message.
        limit: The most characters kept text may have.

    Returns:
        The cleaned text.

    Raises:
        DecisionError: The text is not a string, is empty once cleaned, or is too long.
    """
    if reason is not None and not isinstance(reason, str):
        raise DecisionError(f"a {what} must be text")
    # Unicode line and paragraph separators read as line breaks in some viewers; keep one line.
    cleaned = re.sub("[\u2028\u2029\u0085]+", " ", reason or "").strip()
    if not cleaned:
        raise DecisionError(f"a {what} is required")
    if len(cleaned) > limit:
        raise DecisionError(f"{what} longer than {limit} characters")
    return cleaned


def check_request(card: DecisionCard, option: str, reason: str) -> str:
    """Validate a decision request; return the cleaned reason or raise :class:`DecisionError`."""
    if option not in {o.id for o in card.options}:
        raise DecisionError(f"unknown option {option!r} for card {card.id}")
    return clean_reason(reason)


def apply_decision(
    store: StudyStore,
    study_id: str,
    card_id: str,
    option: str,
    reason: str,
    actor: Actor,
    expected_head: str | None = None,
) -> DecisionOutcome:
    """Decide a card, or refuse: ``pending_human`` for a non-human on a flipping card.

    The rule is evaluated here, from the card's impact on disk, never from what the caller says.
    The store applies the version check (``stale`` when ``expected_head`` is out of date).
    """
    card = store.card(study_id, card_id)
    cleaned = check_request(card, option, reason)
    if actor != "human" and needs_human(card):
        return store.request_human(study_id, card_id, option, cleaned, actor, expected_head)
    # the store also turns an agent's choice into a request while the study is in Suggest mode
    return store.append_decision(study_id, card_id, option, cleaned, actor, expected_head)


def reject_request(
    store: StudyStore,
    study_id: str,
    card_id: str,
    reason: str,
    expected_head: str | None = None,
    option: str | None = None,
) -> DecisionOutcome:
    """A human turns down agents' pending requests on a card (one option, or all), with a reason."""
    card = store.card(study_id, card_id)
    cleaned = check_request(card, option or card.recommended, reason)
    return store.reject_pending(study_id, card_id, cleaned, expected_head, option)
