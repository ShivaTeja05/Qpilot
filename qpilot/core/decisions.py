"""Decision Cards and the escalation rule: which choices a human must make, and who may decide.

Domain-agnostic. The plugin describes each card with a :class:`CardSpec` (which grid dimension it
is about, its options, the recommended option, and the plugin's own evidence, template key and
fact ids). The core fills in the consequences of each option from the decision space, measures
the card's impact from the robustness summary, ranks the cards, and enforces one rule **in code**:

    A choice that can flip any conclusion is a human decision, at every autonomy level and for
    every actor. An agent (or the system) asking to make it gets ``pending_human``.

A card whose dimension flips no conclusion is decided automatically (recommended option, actor
``system``) and logged; a human can reopen it. A card's ``kind`` must be registered in
``core/card_kinds.py``; a kind registered ``always_human`` (and a kind this build does not know)
makes its cards human-only even when nothing flips. The kind can make the rule stricter, never
looser.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, NamedTuple

from pydantic import BaseModel, field_validator

from qpilot.core.card_kinds import CardKindError, card_kind, requires_human
from qpilot.schemas import (
    Actor,
    Autonomy,
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
# A person's decision carried to another analysis of the same file (StudyStore.carry_decisions)
# says where it came from inside the hashed entry: the earlier study and the entry's hash.
CARRIED_PREFIX = "Carried from analysis"
_CARRIED = re.compile(
    r"Carried from analysis ([0-9a-f]{12}) \(entry ([0-9a-f]{64})\): (.*)\Z", re.S
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
    kind: str  # a registered kind (core/card_kinds.py)
    dimension: str
    options: list[OptionSpec]
    recommended: str
    rationale_template: str
    evidence: dict[str, Any] = {}
    facts: list[str] = []

    @field_validator("kind")
    @classmethod
    def _registered(cls, value: str) -> str:
        try:
            return card_kind(value).name
        except CardKindError as exc:
            raise ValueError(str(exc)) from None


def effective_level(
    user_level: Autonomy, impact: dict[str, Any], always_human: bool = False
) -> Autonomy:
    """The autonomy that actually applies to a card: a flipping card is always ``suggest``.

    So is every card of a kind that is always a human decision (``always_human``).
    """
    if (impact.get("flips") or always_human) and user_level in ("decide_and_tell", "automatic"):
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
    """Order cards by calls flipped, then by the largest fold-change shift; renumber ranks 1..n.

    With several views (a study's comparisons) the calls flipped are counted over all of them.
    """
    ordered = sorted(
        cards,
        key=lambda c: (
            -int(c.impact.get("n_calls_flipped", c.impact["n_genes_flipped"])),
            -c.impact["max_delta_log2fc"],
            c.id,
        ),
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


class View(NamedTuple):
    """Another reading of the same items under the same choices (e.g. a study's other comparison).

    ``summary`` and ``grid`` are its robustness summary and grid (same cells as the primary
    grid); ``space`` evaluates it, for each option's consequence.
    """

    summary: dict[str, GeneRobustness]
    grid: Any
    space: DecisionSpace


def _view_impact(view_id: str, summary: dict[str, GeneRobustness], anywhere: list[str], dim: str):  # noqa: ANN202
    from qpilot.core.robustness import flipped_by

    found = card_impact(summary, dim)
    return {
        "id": view_id,
        "flips": found["flips"],
        "n_genes_flipped": found["n_genes_flipped"],
        "genes": flipped_by(summary, dim),
        "flips_anywhere": bool(anywhere),
        "n_genes_flipped_anywhere": len(anywhere),
        "max_delta_log2fc": found["max_delta_log2fc"],
    }


def _with_views(
    impact: dict[str, Any],
    spec: CardSpec,
    space: DecisionSpace,
    grid_summary: dict[str, GeneRobustness],
    anywhere: list[str],
    views: Mapping[str, View],
    primary_view: str,
    headline_items: list[str],
) -> dict[str, Any]:
    """A card's impact over every view: a flip in any of them is a flip.

    ``impact["n_genes_flipped"]`` stays the primary view's; ``impact["views"]`` lists each
    view's own counts (the primary first) and ``n_calls_flipped`` sums them. Each other view's
    entry has ``per_option``: option id -> item -> the result (``ContrastResult`` as JSON) for
    the headline items and every item whose call the choice changes there.
    """
    from qpilot.core.robustness import flipped_anywhere

    dim = spec.dimension
    entries = [_view_impact(primary_view, grid_summary, anywhere, dim)]
    for view_id, view in views.items():
        entries.append(_view_impact(view_id, view.summary, flipped_anywhere(view.grid, dim), dim))
    impact = {
        **impact,
        "flips": any(e["flips"] for e in entries),
        "flips_anywhere": any(e["flips_anywhere"] for e in entries),
        "n_calls_flipped": sum(e["n_genes_flipped"] for e in entries),
        "n_calls_flipped_anywhere": sum(e["n_genes_flipped_anywhere"] for e in entries),
        "max_delta_log2fc": max(e["max_delta_log2fc"] for e in entries),
        "views": entries,
    }
    by_option = {o.id: o for o in spec.options}
    shown = {  # the headline items, and every item whose call this choice changes in the view
        e["id"]: list(dict.fromkeys([*headline_items, *e["genes"]])) for e in entries[1:]
    }
    for option in spec.options:
        cell = {**space.primary, dim: by_option[option.id].value}
        for entry, (view_id, view) in zip(entries[1:], views.items(), strict=True):
            results = view.space.evaluate(cell)
            entry.setdefault("per_option", {})[option.id] = {
                i: results[i].model_dump(mode="json") for i in shown[view_id] if i in results
            }
    return impact


def build_cards(
    space: DecisionSpace,
    grid_summary: dict[str, GeneRobustness],
    option_sets: list[CardSpec],
    headline_items: list[str],
    autonomy: Autonomy = "suggest",
    grid: Any = None,
    views: Mapping[str, View] | None = None,
    primary_view: str = "primary",
) -> list[DecisionCard]:
    """Build one Decision Card per spec, with each option's consequence, impact and rank.

    ``impact["flips"]`` (and the auto-decision) looks at the other choices at their
    recommended settings; ``impact["flips_anywhere"]`` looks at every combination in the grid,
    so a choice that can change a conclusion at some setting always needs a person when an
    agent asks. ``grid`` is computed from ``space`` when not given.

    ``views`` (other readings of the same items under the same choices, e.g. a study's other
    comparisons, by id) count too: a choice that flips a conclusion in any of them is a
    person's, and each option's consequence is given per view (``impact["views"][k]
    ["per_option"]``: the headline items and every item whose call the choice changes there).
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
        options = _options(space, spec, headline_items)
        if views:
            impact = _with_views(
                impact, spec, space, grid_summary, anywhere, views, primary_view, headline_items
            )
        human_kind = requires_human(spec.kind)
        card = DecisionCard(
            id=spec.card_id,
            kind=spec.kind,
            rank=0,
            impact=impact,
            evidence=spec.evidence,
            options=options,
            recommended=spec.recommended,
            rationale_template=spec.rationale_template,
            facts=spec.facts,
            autonomy=autonomy,
            effective_autonomy=effective_level(autonomy, impact, human_kind),
        )
        if not impact["flips"] and not human_kind:
            card = card.model_copy(
                update={
                    "status": "auto_decided",
                    "decision": spec.recommended,
                    "reason": AUTO_REASON_ELSEWHERE if impact["flips_anywhere"] else AUTO_REASON,
                    "decided_by": "system",
                }
            )
        cards.append(card)
    return rank_cards(cards)


def needs_human(card: DecisionCard) -> bool:
    """True when the card can flip a conclusion at any setting (or is in teaching mode).

    Also true for every card whose kind is always a human decision, and for a card whose kind
    this build does not register (fail closed).
    """
    impact = card.impact
    return (
        bool(impact.get("flips"))
        or bool(impact.get("flips_anywhere"))
        or card.effective_autonomy == "teach"
        or requires_human(card.kind)
    )


def stakes(card: DecisionCard) -> int:
    """How much a card's choice matters, from 0 to 2.

    0: it changes no conclusion at any setting. 1: it is a person's when an agent asks (it can
    change one at other settings, or the study is in teaching mode). 2: it changes one at the
    analysis's own settings, or its kind is always a person's decision.
    """
    if card.impact.get("flips") or requires_human(card.kind):
        return 2
    return 1 if needs_human(card) else 0


def _calls_changed(card: DecisionCard) -> set[str]:
    """The headline items whose conclusion differs between the card's options.

    In a card with several views (comparisons) an item of another view is ``"<view>:<item>"``.
    """
    calls: dict[str, set[str]] = {}
    for option in card.options:
        for item, result in option.per_gene.items():
            calls.setdefault(item, set()).add(result.conclusion)
    for view in card.impact.get("views") or ():
        for results in (view.get("per_option") or {}).values():
            for item, result in results.items():
                calls.setdefault(f"{view['id']}:{item}", set()).add(str(result["conclusion"]))
    return {item for item, seen in calls.items() if len(seen) > 1}


def asked_again(before: DecisionCard, after: DecisionCard) -> str | None:
    """Why a person's decision on ``before`` is not carried to ``after``, or None to carry it.

    A decision is carried to another analysis only when the choice matters no more there than
    where the person made it: never onto a card that changes a conclusion (or more of them, or
    another one) while it changed none (or fewer) before, so a choice made when nothing hung on
    it is never applied, unseen, where something does.
    """
    if stakes(after) > stakes(before):
        if stakes(after) == 2:
            return "in this analysis the choice can change a conclusion"
        return "in this analysis the choice can change a conclusion at other settings"
    for key in (
        "n_genes_flipped",
        "n_genes_flipped_anywhere",
        "n_calls_flipped",
        "n_calls_flipped_anywhere",
    ):
        if int(after.impact.get(key) or 0) > int(before.impact.get(key) or 0):
            return "in this analysis the choice changes more conclusions"
    if not _calls_changed(after) <= _calls_changed(before):
        return "in this analysis the choice changes another conclusion"
    return None


class Carried(NamedTuple):
    """Where a carried decision came from, read back from its reason."""

    study_id: str
    entry_hash: str
    reason: str  # the person's own words


def carried_reason(study_id: str, entry_hash: str, reason: str) -> str:
    """The reason of a carried entry: the earlier study, its entry's hash, the person's words."""
    return f"{CARRIED_PREFIX} {study_id} (entry {entry_hash}): {reason}"


def carried_from(reason: str) -> Carried | None:
    """The origin a carried entry's reason names (None for any other reason)."""
    found = _CARRIED.match(reason or "")
    return Carried(*found.groups()) if found else None


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
    if cleaned.startswith(CARRIED_PREFIX):  # only qPilot writes that, when it carries one
        raise DecisionError(f"a {what} cannot start with {CARRIED_PREFIX!r}")
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
