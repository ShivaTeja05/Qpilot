"""The proposal store's own gates: who may propose a confirm step, and agents' share of the inbox.

Domain-agnostic, so no plugin: the inbox is opened by folder and root, with no guard or check.
"""

import pytest

from qpilot.core import proposals as proposals_module
from qpilot.core.proposals import ProposalStore
from qpilot.schemas_studio import MadeBy
from tests.core.studio_helpers import SHA, proposal

RULE = MadeBy(kind="rule")


@pytest.fixture
def inbox(tmp_path) -> ProposalStore:
    return ProposalStore.at(tmp_path / "session", SHA)


def _confirm(made_by: MadeBy = RULE):
    return proposal(
        kind="stage.confirm", subject="design", payload={"stage": "design"}, made_by=made_by
    )


def test_only_the_system_proposes_a_confirm_step_as_the_rule(inbox):
    for made_by, actor in (
        (MadeBy(kind="agent"), "agent"),
        (RULE, "agent"),
        (MadeBy(kind="model"), "system"),
        (MadeBy(kind="agent"), "system"),
        (RULE, "human"),
    ):
        out = inbox.propose(_confirm(made_by), actor)
        assert out.status == "refused", (made_by, actor)
    assert "stage.confirm" in inbox.propose(_confirm(MadeBy(kind="model")), "system").reason
    assert not inbox.path.exists()  # nothing is written for a refusal
    assert inbox.propose(_confirm(), "system").status == "proposed"


def test_an_agents_proposal_is_always_recorded_as_an_agents(inbox):
    out = inbox.propose(proposal(made_by=RULE), "agent")
    assert out.status == "refused" and "made by an agent" in out.reason
    assert inbox.propose(proposal(made_by=MadeBy(kind="model")), "agent").status == "refused"
    assert inbox.propose(proposal(), "agent").status == "proposed"


def test_agents_fill_only_their_own_share_of_pending_proposals(inbox, monkeypatch):
    monkeypatch.setattr(proposals_module, "MAX_AGENT_PENDING", 2, raising=False)
    monkeypatch.setattr(proposals_module, "MAX_PENDING", 3)
    agents = [inbox.propose(proposal(subject=f"S{i}"), "agent").status for i in range(3)]
    assert agents == ["proposed", "proposed", "refused"]
    rules = [
        inbox.propose(proposal(subject=f"R{i}", made_by=RULE), "system").status for i in range(4)
    ]
    assert rules == ["proposed", "proposed", "proposed", "refused"]  # the system's own cap
    assert inbox.propose(_confirm(), "system").status == "proposed"  # never capped


def test_an_agents_flood_of_history_never_refuses_the_system(inbox, monkeypatch):
    first = inbox.propose(proposal(subject="S0"), "agent")
    monkeypatch.setattr(proposals_module, "MAX_CHAIN_BYTES", inbox.path.stat().st_size + 4_000)
    note = {"group": "LPS", "note": "x" * 1_500}
    statuses = [
        inbox.propose(proposal(subject="S1", payload=note), "agent").status for _ in range(6)
    ]
    assert statuses[-1] == "refused" and "proposed" in statuses
    assert inbox.propose(proposal(subject="R1", made_by=RULE), "system").status == "proposed"
    assert inbox.propose(_confirm(), "system").status == "proposed"
    assert inbox.reject(first.proposal.id, "human", "not this").status == "rejected"


def test_agents_have_a_much_smaller_share_of_the_history(inbox, monkeypatch):
    monkeypatch.setattr(proposals_module, "MAX_AGENT_BYTES", 3_000, raising=False)
    note = {"group": "LPS", "note": "x" * 1_500}
    statuses = [
        inbox.propose(proposal(subject=f"S{i}", payload=note), "agent").status for i in range(4)
    ]
    assert statuses[-1] == "refused"
    out = inbox.propose(proposal(subject="S9"), "agent")
    assert out.status == "refused" and "share" in out.reason
    assert inbox.propose(proposal(subject="R1", made_by=RULE), "system").status == "proposed"


def test_a_view_reads_head_proposals_and_acceptances_together(inbox):
    ids = [inbox.propose(proposal(subject=s), "agent").proposal.id for s in ("S1", "S2", "S3")]
    inbox.accept(ids[2], "human")
    inbox.accept(ids[0], "human")
    view = inbox.view()
    assert view.head == inbox.head()
    assert [p.id for p in view.proposals] == ids
    assert [p.id for p in view.accepted] == [ids[2], ids[0]]  # in the order a person decided
    assert [p.id for p in view.accepted] == [p.id for p in inbox.accepted()]
