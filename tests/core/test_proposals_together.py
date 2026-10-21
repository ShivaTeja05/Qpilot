"""One click of a person that proposes and decides several proposals: all of it, or nothing.

``ProposalStore.decide_together`` is how a choice on a Run Gate card becomes curve exclusions:
the rule's proposals are made for the click and decided by the person in the same locked write,
and an agent's request waiting on the same wells is answered by that click too.
"""

import pytest

from qpilot.core.proposals import ProposalError, ProposalStore, verify_proposal_chain
from qpilot.schemas_studio import MadeBy
from tests.core.studio_helpers import SHA, proposal, toy_guard


@pytest.fixture
def inbox(tmp_path) -> ProposalStore:
    return ProposalStore.at(tmp_path / "session", SHA, toy_guard)


def well(subject: str, excluded: bool = True, maker: str = "rule"):
    return proposal(
        kind="curve.exclude_well",
        subject=subject,
        payload={"excluded": excluded},
        made_by=MadeBy(kind=maker),  # type: ignore[arg-type]
    )


def _bytes(inbox: ProposalStore) -> bytes | None:
    return inbox.path.read_bytes() if inbox.path.exists() else None


def test_new_proposals_and_a_waiting_one_are_settled_in_one_write(inbox):
    asked = inbox.propose(well("run1/A3", maker="agent"), "agent").proposal
    other = inbox.propose(well("run1/B1", excluded=False, maker="agent"), "agent").proposal
    head = inbox.head()
    out = inbox.decide_together(
        [(well("run1/A1"), "accept"), (well("run1/A2"), "reject")],
        [(asked.id, "accept"), (other.id, "reject")],
        "human",
        "  the NTC amplified on this plate ",
        expected_head=head,
    )
    assert [o.status for o in out] == ["accepted", "rejected", "accepted", "rejected"]
    assert len({o.head for o in out}) == 1 and out[-1].head == inbox.head()
    for o in out:
        assert (
            o.proposal.decided_by == "human"
            and o.proposal.reason == "the NTC amplified on this plate"
        )
    entries = inbox.entries()
    assert verify_proposal_chain(entries, inbox.root) is None
    click = entries[-6:]  # two proposals made (rule) and decided, then the two waiting ones
    assert [e.action for e in click] == [
        "propose",
        "propose",
        "accept",
        "reject",
        "accept",
        "reject",
    ]
    assert {e.actor for e in click if e.action == "propose"} == {"system"}
    assert {e.actor for e in click if e.action != "propose"} == {"human"}
    assert len({e.at for e in click}) == 1  # one click, one moment
    assert [p.subject for p in inbox.accepted()] == ["run1/A1", "run1/A3"]


def test_only_a_person_decides_and_a_reason_is_required(inbox):
    for actor in ("agent", "system"):
        with pytest.raises(ProposalError):
            inbox.decide_together([(well("run1/A1"), "accept")], [], actor, "why")
    with pytest.raises(ProposalError):
        inbox.decide_together([(well("run1/A1"), "accept")], [], "human", "   ")
    with pytest.raises(ProposalError):
        inbox.decide_together([(well("run1/A1"), "edit")], [], "human", "why")
    with pytest.raises(ProposalError):
        inbox.decide_together([], [], "human", "why")
    assert _bytes(inbox) is None


def test_nothing_is_written_when_one_item_is_refused(inbox):
    done = inbox.propose(well("run1/A3", maker="agent"), "agent").proposal
    inbox.reject(done.id, "human", "not this one")
    before = _bytes(inbox)
    out = inbox.decide_together(
        [(well("run1/A1"), "accept")], [(done.id, "accept")], "human", "the NTC amplified"
    )
    assert {o.status for o in out} == {"refused"} and "already rejected" in out[0].reason
    out = inbox.decide_together(
        [(well("run1/A1"), "accept")], [("p_0000000000000000", "accept")], "human", "why"
    )
    assert {o.status for o in out} == {"refused"}
    with pytest.raises(ProposalError):
        inbox.decide_together([], [(done.id, "accept"), (done.id, "accept")], "human", "why")
    # an agent's proposal is always an agent's: the click cannot make one in a rule's name
    out = inbox.decide_together([(well("run1/A1"), "accept")], [], "human", "why", proposer="agent")
    assert {o.status for o in out} == {"refused"}
    assert _bytes(inbox) == before


def test_a_person_deciding_since_the_view_makes_the_click_stale(inbox):
    first = inbox.propose(well("run1/A3", maker="agent"), "agent").proposal
    seen = inbox.head()
    inbox.propose(well("run1/A4", maker="agent"), "agent")  # an agent elsewhere: not stale
    out = inbox.decide_together(
        [(well("run1/A1"), "accept")], [], "human", "why", expected_head=seen
    )
    assert out[0].status == "accepted"
    seen = inbox.head()
    inbox.reject(first.id, "human", "turned down in another tab")
    before = _bytes(inbox)
    out = inbox.decide_together(
        [(well("run1/A2"), "accept")], [], "human", "why", expected_head=seen
    )
    assert {o.status for o in out} == {"stale"}
    assert _bytes(inbox) == before


def test_a_new_proposal_supersedes_a_pending_one_in_its_slot(inbox):
    old = inbox.propose(well("run1/A1", excluded=False), "system").proposal
    out = inbox.decide_together([(well("run1/A1"), "accept")], [], "human", "the NTC amplified")
    assert out[0].status == "accepted"
    state = {p.id: p for p in inbox.proposals()}
    assert state[old.id].status == "superseded"
    assert state[old.id].superseded_by == out[0].proposal.id
