"""Suggest mode, Undo and the scorecard helpers, out of the Gradio app (qpilot/ai/suggest_only.py).

Ported from the old page's tests (``tests/app/test_app.py``) so they outlive it: the rules are
the same, only their home changed.
"""

import subprocess
import sys

import pytest

from qpilot.ai.suggest_only import (
    SUGGEST_ONLY_REASON,
    UNDO_PREFIX,
    SuggestOnlyStore,
    acting_store,
    snapshot,
    undo_target,
)
from qpilot.core.store import StudyStore
from qpilot.schemas import DecisionEntry


def test_the_helpers_load_without_gradio():
    code = (
        "import sys, qpilot.ai.suggest_only, qpilot.web.server; "
        "sys.exit(1 if 'gradio' in sys.modules else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def test_the_old_import_path_still_works():
    pytest.importorskip("gradio")
    from qpilot import app

    assert app.SuggestOnlyStore is SuggestOnlyStore and app.undo_target is undo_target


@pytest.fixture
def analysed_study(tmp_studies_dir, fixture_result, fixture_cards):
    store = StudyStore(tmp_studies_dir)
    store.put(fixture_result, fixture_cards)
    return store, fixture_result.study_id


def _entry(seq, option, reason="", status="applied", card_id="card_x"):
    return DecisionEntry(
        seq=seq, card_id=card_id, option=option, reason=reason, actor="human",
        status=status, at="2026-10-20T00:00:00Z", prev_hash="0" * 64,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("history", "expected"),
    [
        ([], None),
        ([("a", "")], None),
        ([("a", ""), ("b", "")], "a"),
        ([("a", ""), ("a", "same again")], None),
        ([("a", ""), ("b", ""), ("a", f"{UNDO_PREFIX} wrong one")], None),
        ([("a", ""), ("b", ""), ("c", "")], "b"),
        ([("a", ""), ("b", ""), ("c", ""), ("b", f"{UNDO_PREFIX} back")], "a"),
    ],
)
def test_undo_steps_back_through_the_cards_own_history(history, expected):
    entries = [_entry(i, option, reason) for i, (option, reason) in enumerate(history, 1)]
    entries.append(_entry(99, "z", card_id="card_other"))  # other cards never count
    entries.append(_entry(100, "y", status="rejected"))  # nor do requests turned down
    assert undo_target(entries, "card_x") == expected


def test_acting_store_is_suggest_only_unless_decide_and_tell(tmp_studies_dir):
    store = StudyStore(tmp_studies_dir)
    assert acting_store(store, "decide_and_tell") is store
    assert isinstance(acting_store(store, "suggest"), SuggestOnlyStore)
    assert isinstance(acting_store(store, "anything else"), SuggestOnlyStore)


def test_suggest_mode_turns_an_agents_choice_into_a_request(analysed_study):
    store, study_id = analysed_study
    head, cards, _ = snapshot(store, study_id)
    card = next(c for c in cards if c.id == "card_undetermined")
    other = next(o.id for o in card.options if o.id != card.decision)
    suggest = SuggestOnlyStore(store.root)
    outcome = suggest.append_decision(study_id, card.id, other, "the model asks", "agent", head)
    assert outcome.status == "pending_human" and outcome.reason == SUGGEST_ONLY_REASON
    assert store.card(study_id, card.id).decision == card.decision  # nothing applied
    assert [p.card_id for p in store.pending(study_id)] == [card.id]


def test_a_persons_choice_passes_through_suggest_mode(analysed_study):
    store, study_id = analysed_study
    head, cards, _ = snapshot(store, study_id)
    card = next(c for c in cards if c.id == "card_undetermined")
    other = next(o.id for o in card.options if o.id != card.decision)
    outcome = SuggestOnlyStore(store.root).append_decision(
        study_id, card.id, other, "a person decides", "human", head
    )
    assert outcome.status == "applied" and store.card(study_id, card.id).decision == other
