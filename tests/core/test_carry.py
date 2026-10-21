"""Carrying a person's card decisions to another analysis of the same file.

``StudyStore.carry_decisions(source, target)``: one new ``applied`` entry by ``human`` per card a
person decided in ``source``, whose reason names the earlier study and entry; never the system's
or an agent's decisions; asked again (not carried) where the choice matters more in ``target``.
The two analyses here are the fixture study under two confirmed designs (the plugin faked).
"""

import pytest

from qpilot.core.decisions import (
    CARRIED_PREFIX,
    DecisionError,
    apply_decision,
    asked_again,
    carried_from,
    carried_reason,
    stakes,
)
from qpilot.core.record import verify_chain
from qpilot.core.store import study_key
from qpilot.schemas import DecisionCard
from tests.core.studio_helpers import fake_designs, groups_design

CUTOFF_REASON = "the lab cuts at 15 for this cohort"


@pytest.fixture
def designs(monkeypatch):
    return fake_designs(monkeypatch)


def analysed(store, result, cards, note):
    """The fixture study analysed with a design of its own (its own workspace and id)."""
    design = groups_design(note)
    study = study_key(result.input_sha256, design)[:12]
    store.put(result.model_copy(update={"study_id": study}), cards, design=design)
    return study


def flat(card: DecisionCard) -> DecisionCard:
    """The card as an analysis where no option changes any conclusion would build it."""
    impact = {**card.impact, "flips": False, "n_genes_flipped": 0}
    for key in ("flips_anywhere", "n_genes_flipped_anywhere"):
        impact[key] = False if key == "flips_anywhere" else 0
    first = card.options[0].per_gene
    options = [o.model_copy(update={"per_gene": first}) for o in card.options]
    return card.model_copy(
        update={
            "impact": impact,
            "options": options,
            "status": "auto_decided",
            "decision": card.recommended,
            "reason": "Decided automatically: no option on this card changes any conclusion.",
            "decided_by": "system",
        }
    )


@pytest.fixture
def two(store, fixture_result, fixture_cards, designs):
    """Two analyses of one file with the same three cards; a person decides the cut-off."""
    source = analysed(store, fixture_result, fixture_cards, "before")
    target = analysed(store, fixture_result, fixture_cards, "after")
    head = store.chain_head(source)
    out = apply_decision(store, source, "card_cutoff", "cut_20", CUTOFF_REASON, "human", head)
    assert out.status == "applied"
    return source, target


def test_a_persons_decision_is_carried_as_a_new_entry_that_names_its_origin(store, two):
    source, target = two
    made = store.entries(source)[-1]
    report = store.carry_decisions(source, target)
    assert report.carried == ["card_cutoff"] and report.asked_again == {} and report.gone == []
    assert (report.source, report.target) == (source, target)
    entry = store.entries(target)[-1]
    assert (entry.card_id, entry.option, entry.actor, entry.status) == (
        "card_cutoff",
        "cut_20",
        "human",
        "applied",
    )
    assert entry.reason == f"{CARRIED_PREFIX} {source} (entry {made.hash}): {CUTOFF_REASON}"
    assert carried_from(entry.reason) == (source, made.hash, CUTOFF_REASON)
    card = store.card(target, "card_cutoff")
    assert (card.status, card.decision, card.decided_by) == ("decided", "cut_20", "human")
    # the chain still verifies, and the source is untouched
    assert verify_chain(store.entries(target), store.get(target).input_sha256) is None
    assert [e.card_id for e in store.entries(source)][-1] == "card_cutoff"
    assert store.card(source, "card_cutoff").decision == "cut_20"


def test_carrying_twice_writes_nothing_and_a_later_change_stands(store, two):
    source, target = two
    store.carry_decisions(source, target)
    n = len(store.entries(target))
    assert store.carry_decisions(source, target).carried == []
    assert len(store.entries(target)) == n
    # the person changes their mind in the new analysis; carrying again keeps that
    head = store.chain_head(target)
    apply_decision(store, target, "card_cutoff", "cut_10", "rethought", "human", head)
    assert store.carry_decisions(source, target).carried == []
    assert store.card(target, "card_cutoff").decision == "cut_10"


def test_back_to_the_earlier_analysis_carries_only_what_changed(store, two):
    source, target = two
    store.carry_decisions(source, target)
    # nothing new: going back finds the same option decided by a person
    assert store.carry_decisions(target, source).carried == []
    head = store.chain_head(target)
    apply_decision(store, target, "card_cutoff", "cut_10", "rethought", "human", head)
    report = store.carry_decisions(target, source)
    assert report.carried == ["card_cutoff"]
    entry = store.entries(source)[-1]
    assert entry.option == "cut_10" and carried_from(entry.reason).reason == "rethought"
    # a carried entry is carried with the person's own words, never a nested prefix
    assert store.carry_decisions(source, target).carried == []
    assert entry.reason.count(CARRIED_PREFIX) == 1


def test_the_systems_and_agents_decisions_are_never_carried(store, two):
    source, target = two
    head = store.chain_head(source)
    # an agent's request on a card that needs a person, and its turn-down
    out = apply_decision(store, source, "card_refset", "top3", "agent asks", "agent", head)
    assert out.status == "pending_human"
    store.reject_pending(source, "card_refset", "not now", store.chain_head(source))
    report = store.carry_decisions(source, target)
    assert report.carried == ["card_cutoff"]
    carried = [e for e in store.entries(target) if e.actor == "human"]
    assert [e.card_id for e in carried] == ["card_cutoff"]
    assert {e.actor for e in store.entries(target)} == {"system", "human"}
    assert store.pending(target) == []


def test_an_agents_applied_choice_is_not_carried(store, fixture_result, fixture_cards, designs):
    cards = [flat(c) if c.id == "card_undetermined" else c for c in fixture_cards]
    source = analysed(store, fixture_result, cards, "before")
    target = analysed(store, fixture_result, cards, "after")
    head = store.chain_head(source)
    out = apply_decision(store, source, "card_undetermined", "cap", "agent caps", "agent", head)
    assert out.status == "applied"  # the card changes nothing, so an agent may apply it
    assert store.carry_decisions(source, target).carried == []
    assert store.card(target, "card_undetermined").decided_by == "system"


def test_a_choice_that_matters_more_now_is_asked_again(
    store, fixture_result, fixture_cards, designs
):
    # the person overrode an automatic card; in the new analysis that card changes a conclusion
    before = [flat(c) if c.id == "card_cutoff" else c for c in fixture_cards]
    source = analysed(store, fixture_result, before, "before")
    target = analysed(store, fixture_result, fixture_cards, "after")
    assert store.card(source, "card_cutoff").status == "auto_decided"
    assert store.card(target, "card_cutoff").status == "open"
    head = store.chain_head(source)
    apply_decision(store, source, "card_cutoff", "cut_20", CUTOFF_REASON, "human", head)
    report = store.carry_decisions(source, target)
    assert report.carried == []
    assert report.asked_again == {
        "card_cutoff": "in this analysis the choice can change a conclusion"
    }
    assert store.card(target, "card_cutoff").status == "open"
    assert all(e.actor == "system" for e in store.entries(target))


def test_a_choice_that_matters_less_now_is_carried(store, fixture_result, fixture_cards, designs):
    after = [flat(c) if c.id == "card_cutoff" else c for c in fixture_cards]
    source = analysed(store, fixture_result, fixture_cards, "before")
    target = analysed(store, fixture_result, after, "after")
    head = store.chain_head(source)
    apply_decision(store, source, "card_cutoff", "cut_20", CUTOFF_REASON, "human", head)
    assert store.carry_decisions(source, target).carried == ["card_cutoff"]
    card = store.card(target, "card_cutoff")
    assert (card.status, card.decision, card.decided_by) == ("decided", "cut_20", "human")


def test_a_card_or_option_the_new_analysis_lacks_is_gone(
    store, fixture_result, fixture_cards, designs
):
    source = analysed(store, fixture_result, fixture_cards, "before")
    cutoff = next(c for c in fixture_cards if c.id == "card_cutoff")
    fewer = cutoff.model_copy(update={"options": cutoff.options[:2]})  # no cut_20
    after = [fewer if c.id == "card_cutoff" else c for c in fixture_cards if c.id != "card_refset"]
    target = analysed(store, fixture_result, after, "after")
    for card, option in (("card_cutoff", "cut_20"), ("card_refset", "top3")):
        head = store.chain_head(source)
        apply_decision(store, source, card, option, "the person's choice", "human", head)
    report = store.carry_decisions(source, target)
    assert report.carried == [] and sorted(report.gone) == ["card_cutoff", "card_refset"]


def test_a_card_with_an_agents_request_waiting_is_asked_again(store, two):
    source, target = two
    head = store.chain_head(target)
    out = apply_decision(store, target, "card_cutoff", "cut_10", "agent asks", "agent", head)
    assert out.status == "pending_human"
    report = store.carry_decisions(source, target)
    assert report.carried == [] and "agent's request waits" in report.asked_again["card_cutoff"]
    assert [p.option for p in store.pending(target)] == ["cut_10"]  # still for a person


def test_only_analyses_of_the_same_file_share_decisions(store, two, fixture_result, fixture_cards):
    source, _ = two
    other = fixture_result.model_copy(update={"input_sha256": "b" * 64, "study_id": "b" * 12})
    store.put(other, fixture_cards)
    with pytest.raises(ValueError, match="same file"):
        store.carry_decisions(source, "b" * 12)


def test_nobody_can_write_a_carried_reason_by_hand(store, two):
    source, target = two
    head = store.chain_head(target)
    forged = carried_reason(source, "0" * 64, "trust me")
    with pytest.raises(DecisionError, match="cannot start with"):
        apply_decision(store, target, "card_cutoff", "cut_20", forged, "human", head)


def test_stakes_and_asked_again(fixture_cards):
    refset, cutoff, undetermined = (
        next(c for c in fixture_cards if c.id == i)
        for i in ("card_refset", "card_cutoff", "card_undetermined")
    )
    assert stakes(refset) == 2 and stakes(flat(cutoff)) == 0
    elsewhere = flat(cutoff).model_copy(
        update={"impact": {**flat(cutoff).impact, "flips_anywhere": True}}
    )
    assert stakes(elsewhere) == 1
    assert asked_again(flat(cutoff), elsewhere) == (
        "in this analysis the choice can change a conclusion at other settings"
    )
    assert asked_again(elsewhere, flat(cutoff)) is None
    assert asked_again(cutoff, cutoff) is None
    more = cutoff.model_copy(update={"impact": {**cutoff.impact, "n_genes_flipped": 40}})
    assert asked_again(cutoff, more) == "in this analysis the choice changes more conclusions"
    assert carried_from("Undo: back") is None and carried_from(undetermined.reason or "") is None


def test_two_carries_at_once_write_one_entry(store, two):
    from concurrent.futures import ThreadPoolExecutor

    source, target = two
    before = len(store.entries(target))
    with ThreadPoolExecutor(max_workers=4) as pool:
        reports = list(pool.map(lambda _: store.carry_decisions(source, target), range(4)))
    assert sorted(len(r.carried) for r in reports) == [0, 0, 0, 1]
    assert len(store.entries(target)) == before + 1
    assert verify_chain(store.entries(target), store.get(target).input_sha256) is None
