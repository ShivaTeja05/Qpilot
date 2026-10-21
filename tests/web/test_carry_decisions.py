"""A person's Decision Card choices follow the session to a re-analysed study (the mini file).

Leaving a well out after the curves are confirmed (or putting it back) makes another analysis of
the file. What a person chose on the earlier analysis's Decision Cards is carried to it: one new
chain entry per card, by ``human``, whose reason names the earlier study and the entry that made
the choice. Results, the Record's chain and History say so; the choices stage is not carried (a
person confirms the new analysis's choices, one click when every card is decided).
"""

from __future__ import annotations

import pytest

from qpilot.core.decisions import CARRIED_PREFIX, carried_from
from qpilot.core.record import verify, verify_chain, write_record
from qpilot.mcp_server import QpilotTools
from qpilot.studio_service import EXCLUDE_KIND
from tests.web.test_gate_decide import analysed

WELL = "GAPDH_plate/A3"
CAP_REASON = "the lab caps never-amplified wells at 40 cycles"
WELL_REASON = "a bubble in the well"


def decide_card(c, study: str, card: str, option: str, reason: str):
    head = c.get(f"/api/studies/{study}/cards").json()["head"]
    return c.post(
        f"/api/studies/{study}/cards/{card}/decide",
        json={"option": option, "reason": reason, "expected_head": head},
    )


def set_well(walked, excluded: bool, reason: str) -> str:
    """Leave the well out of (or put it back into) the analysis from the Curves inbox."""
    c, sid = walked["client"], walked["sid"]
    out = QpilotTools(walked["store"]).qpcr_propose(sid, EXCLUDE_KIND, WELL, {"excluded": excluded})
    assert out["status"] == "proposed", out
    r = c.post(
        f"/api/sessions/{sid}/proposals/{out['proposal']['id']}/accept",
        json={"reason": reason, "expected_head": out["head"]},
    )
    assert r.status_code == 200, r.text
    return analysed(c, sid, r.json())


@pytest.fixture
def capped(walked):
    """The walked mini study with a person's choice on the undetermined-wells card."""
    c, study = walked["client"], walked["study"]
    r = decide_card(c, study, "card_undetermined", "cap", CAP_REASON)
    assert r.status_code == 200, r.text
    return walked


def test_the_choice_is_carried_to_the_new_analysis(capped):
    c, store, study = capped["client"], capped["store"], capped["study"]
    made = store.entries(study)[-1]
    assert (made.card_id, made.option, made.actor) == ("card_undetermined", "cap", "human")

    new = set_well(capped, True, WELL_REASON)
    assert new != study and WELL in store.design(new).excluded_wells

    # the chain: the new analysis's own automatic entries, then the person's choice carried
    entries = store.entries(new)
    assert verify_chain(entries, store.get(new).input_sha256) is None
    carried = entries[-1]
    assert (carried.card_id, carried.option, carried.actor, carried.status) == (
        "card_undetermined",
        "cap",
        "human",
        "applied",
    )
    assert carried.reason == f"{CARRIED_PREFIX} {study} (entry {made.hash}): {CAP_REASON}"
    assert [e.actor for e in entries[:-1]] == ["system"] * (len(entries) - 1)

    # Results: the card is the person's, carried, with their words
    cards = {v["card"]["id"]: v for v in c.get(f"/api/studies/{new}/cards").json()["cards"]}
    card = cards["card_undetermined"]
    assert card["card"]["status"] == "decided" and card["card"]["decision"] == "cap"
    assert card["carried"] == {
        "study_id": study,
        "entry_hash": made.hash,
        "reason": CAP_REASON,
        "found": True,
        "decided_at": made.at,
    }
    assert card["status_line"] == (
        "Decided by human: Count empty wells as very low (cap), carried from the earlier "
        f"analysis {study}. Reason: {CAP_REASON}"
    )
    assert card["asked_again"] is None and cards["card_refset"]["carried"] is None

    # the Record's chain: the entry says where it came from
    chain = c.get(f"/api/studies/{new}/decisions").json()
    assert chain["chain_intact"]
    (view,) = (e for e in chain["entries"] if e["carried"])
    assert view["entry"]["hash"] == carried.hash and view["carried"]["found"]

    # the record of the new analysis verifies
    info = write_record(store, new, capped["base"] / "record-new")
    assert verify(info.record_dir).ok


def test_history_shows_the_carried_step_and_what_was_carried(capped):
    c, store, study = capped["client"], capped["store"], capped["study"]
    made = store.entries(study)[-1]
    new = set_well(capped, True, WELL_REASON)
    body = c.get(f"/api/studies/{new}/history").json()
    (step,) = (s for s in body["steps"] if s["carried"])
    assert step["actor"] == "human" and step["option"] == "cap"
    assert step["reason"] == CAP_REASON  # the person's words, quoted as theirs
    assert step["carried"]["study_id"] == study and step["carried"]["entry_hash"] == made.hash
    assert step["carried"]["found"] and step["link_ok"]
    assert step["effect"].startswith("Carried from the earlier analysis. ")
    assert body["carry"]["from_study"] == study
    assert [x["card_id"] for x in body["carry"]["carried"]] == ["card_undetermined"]
    assert body["carry"]["carried"][0]["option"] == "cap"
    assert body["carry"]["asked_again"] == [] and body["carry"]["gone"] == []
    # the earlier analysis's own History has no carry note and no carried step
    before = c.get(f"/api/studies/{study}/history").json()
    assert before["carry"] is None and not any(s["carried"] for s in before["steps"])


def test_putting_the_well_back_keeps_the_choice_without_a_new_entry(capped):
    store, study = capped["store"], capped["study"]
    new = set_well(capped, True, WELL_REASON)
    n = len(store.entries(study))
    assert set_well(capped, False, "the bubble was on the seal, not in the well") == study
    assert len(store.entries(study)) == n  # the same option, already a person's
    assert store.card(study, "card_undetermined").decision == "cap"
    # a change made in the new analysis goes back with the well
    set_well(capped, True, WELL_REASON)
    c = capped["client"]
    r = decide_card(c, new, "card_undetermined", "drop", "dropping is the lab's new rule")
    assert r.status_code == 200, r.text
    assert set_well(capped, False, "the bubble was on the seal, not in the well") == study
    last = store.entries(study)[-1]
    assert last.option == "drop" and carried_from(last.reason).study_id == new
    assert carried_from(last.reason).reason == "dropping is the lab's new rule"


def test_the_choices_stage_is_confirmed_again_in_one_click(capped):
    studio, sid = capped["studio"], capped["sid"]
    confirm = studio.propose_confirm(sid, "choices")
    studio.accept(sid, confirm.proposal.id, "human", "checked")
    assert {s.stage: s.confirmed for s in studio.stages(sid)}["choices"]

    set_well(capped, True, WELL_REASON)
    stages = {s.stage: s for s in studio.stages(sid)}
    assert stages["design"].confirmed and stages["curves"].confirmed
    assert not stages["choices"].confirmed  # a person confirms the new analysis's choices
    again = studio.propose_confirm(sid, "choices")  # nothing left open: every card decided
    assert again.proposal.payload["decisions"]["card_undetermined"] == "cap"
    studio.accept(sid, again.proposal.id, "human", "checked again")
    assert {s.stage: s.confirmed for s in studio.stages(sid)}["choices"]


def test_a_carry_that_fails_never_blocks_the_analysis(capped, monkeypatch):
    store, study = capped["store"], capped["study"]

    def broken(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(store, "carry_decisions", broken)
    new = set_well(capped, True, WELL_REASON)
    assert new != study
    assert store.card(new, "card_undetermined").decided_by == "system"
    assert capped["studio"].carried(capped["sid"], new) is None


def test_a_reason_cannot_pretend_to_be_carried(capped):
    c, study = capped["client"], capped["study"]
    r = decide_card(c, study, "card_undetermined", "drop", f"{CARRIED_PREFIX} by hand")
    assert r.status_code == 422, r.text


def test_a_design_changed_in_a_blind_stage_starts_its_cards_afresh(capped):
    studio, sid, store, study = capped["studio"], capped["sid"], capped["store"], capped["study"]
    out = QpilotTools(store).qpcr_propose(sid, "curve.call_rule", "amp_call", {"rule": "cq_le_40"})
    assert out["status"] == "proposed", out
    studio.accept(sid, out["proposal"]["id"], "human", "the lab calls a curve by its Cq")
    assert not studio.results_visible(sid)  # the curves stage is open again: blind
    confirm = studio.propose_confirm(sid, "curves")
    studio.accept(sid, confirm.proposal.id, "human", "checked")
    new = studio.study(sid)
    assert new != study
    assert {e.actor for e in store.entries(new)} <= {"system"}
    assert studio.carried(sid, new) is None
    assert capped["client"].get(f"/api/studies/{new}/history").json()["carry"] is None
