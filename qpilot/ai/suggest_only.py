"""What a page needs around the model and the decision log, with no web framework in it.

Moved out of the old Gradio app (:mod:`qpilot.app`, which re-exports these names) so the one
page's API (:mod:`qpilot.web`) uses the same rules without importing Gradio:

* :class:`SuggestOnlyStore`: the store as the model sees it in *Suggest* mode (it may ask, a
  person decides, on every card);
* :func:`undo_target`: the option Undo restores on a card (Undo is a new chain entry whose
  reason starts with :data:`UNDO_PREFIX`; only the Undo action may write that prefix);
* :func:`snapshot`: the chain head, the cards and the pending requests read together, so a view
  never pairs a new head with an old card;
* :func:`load_profile_or_default` and :func:`run_scorecard`: the harness scorecard the old
  page's *Check this model* computed (items, run, saved by profile so the record carries them).
"""

from __future__ import annotations

from typing import Any

from qpilot.ai.client import ModelClient
from qpilot.ai.profile import Profile, load_profile
from qpilot.core.decisions import check_request, needs_human
from qpilot.core.store import StudyStore
from qpilot.schemas import Actor, DecisionCard, DecisionEntry, DecisionOutcome

SUGGEST_ONLY_REASON = (
    "Suggest mode: the assistant may only ask. This choice changes no conclusion, but a person "
    "confirms it."
)
UNDO_PREFIX = "Undo:"
#: Scorecards are saved under these names (the provider ``openai_compatible`` is ``local``).
SCORECARD_KEYS = {"none": "none", "anthropic": "anthropic", "openai_compatible": "local"}
HARNESS_ITEMS_PER_TYPE = 3


class SuggestOnlyStore(StudyStore):
    """The store as the model sees it in *Suggest* mode: it may ask, never apply.

    Every decision by an actor other than a person becomes a request for a person, on any card.
    (The core already does this for choices that can change a conclusion.)
    """

    def append_decision(
        self,
        study_id: str,
        card_id: str,
        option: str,
        reason: str,
        actor: Actor,
        expected_head: str | None,
    ) -> DecisionOutcome:
        """Turn an agent's decision into a request; a person's decision passes through."""
        if actor == "human":
            return super().append_decision(study_id, card_id, option, reason, actor, expected_head)
        card = self.card(study_id, card_id)
        cleaned = check_request(card, option, reason)
        outcome = self.request_human(study_id, card_id, option, cleaned, actor, expected_head)
        if outcome.status == "pending_human" and not needs_human(card):
            outcome = outcome.model_copy(update={"reason": SUGGEST_ONLY_REASON})
        return outcome


def acting_store(store: StudyStore, autonomy: str) -> StudyStore:
    """The store the model acts through: ``store`` in *Decide and tell me*, else Suggest-only."""
    return store if autonomy == "decide_and_tell" else SuggestOnlyStore(store.root)


def undo_target(entries: list[DecisionEntry], card_id: str) -> str | None:
    """The option Undo restores: one step back through the card's history, or ``None``.

    Replays the card's applied entries as a stack: an entry whose reason starts with ``Undo:``
    pops the step it undid, a repeated choice is not a new step.

    Args:
        entries: The study's decision log, oldest first (``StudyStore.entries``).
        card_id: The card to undo on.

    Returns:
        The option id to restore, or ``None`` when there is nothing to undo.
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


def snapshot(
    store: StudyStore, study_id: str
) -> tuple[str | None, list[DecisionCard], list[DecisionEntry]]:
    """Head, cards and pending requests read together under the workspace lock.

    The store writes the log line before it replaces ``cards.json``; reading both under its lock
    means a view never pairs a new head with an old card. (A ``snapshot`` method in the core
    would replace this use of the store's lock.)
    """
    with store._locked(store.workspace(study_id)):
        return store.chain_head(study_id), store.cards(study_id), store.pending(study_id)


def load_profile_or_default() -> Profile:
    """The user's model profile, or the default one when it cannot be read."""
    try:
        return load_profile()
    except Exception:  # a broken profile must not stop the page; the default is used instead
        return Profile()


def run_scorecard(
    store: StudyStore,
    study_id: str,
    client: ModelClient,
    profile: Profile | None = None,
    n_per_type: int = HARNESS_ITEMS_PER_TYPE,
) -> tuple[str, dict[str, Any], int]:
    """Score ``client`` on questions about the study and save it with the earlier scorecards.

    Args:
        store: The study store.
        study_id: The analysed study the questions are about.
        client: The model to score (a ``NoneBackend`` client scores the templates).
        profile: The model profile; read from disk (or the default) when omitted.
        n_per_type: Questions per item type.

    Returns:
        The key it was saved under (``none`` / ``anthropic`` / ``local``), every saved
        scorecard by key (``Report.model_dump()`` each), and the number of questions asked.
    """
    from qpilot.harness.make_evalset import build_items
    from qpilot.harness.run import run as run_harness

    result, cards = store.get(study_id), store.cards(study_id)
    items = build_items(result, cards, n_per_type=n_per_type)
    key = SCORECARD_KEYS.get(client.provider, client.provider)
    report = run_harness(
        items, client, store, study_id, profile=profile or load_profile_or_default(),
        profile_name=key,
    )  # fmt: skip
    saved = store.scorecard(study_id)
    saved[report.profile] = report.model_dump()
    store.put_scorecard(study_id, saved)
    return key, saved, len(items)
