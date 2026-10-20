"""Suggest mode and the model scorecard, with no web framework in them.

Moved out of the old Gradio page (``qpilot app`` before the one page):

* :class:`SuggestOnlyStore`: the store as the model sees it in *Suggest* mode (it may ask, a
  person decides, on every card);
* :func:`load_profile_or_default` and :func:`run_scorecard`: the harness scorecard behind
  ``POST /api/model/test`` (items, run, saved by profile so the record carries them).

Undo lives with the results views (:func:`qpilot.web.results_views.undo_target`).
"""

from __future__ import annotations

from typing import Any

from qpilot.ai.client import ModelClient
from qpilot.ai.profile import Profile, load_profile
from qpilot.core.decisions import check_request, needs_human
from qpilot.core.store import StudyStore
from qpilot.schemas import Actor, DecisionOutcome

SUGGEST_ONLY_REASON = (
    "Suggest mode: the assistant may only ask. This choice changes no conclusion, but a person "
    "confirms it."
)
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
