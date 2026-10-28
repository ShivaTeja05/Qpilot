"""A chain verified once is not verified again for the same bytes, and only for the same bytes.

Every read of the inbox (each view the page re-reads) used to parse and verify the whole chain;
the result is now kept by the digest of the chain's exact text (perf, excellence round). These
tests pin that a kept result is never trusted for other bytes, and that writes never touch it.
"""

import os

import pytest

import qpilot.core.proposals as proposals_module
from qpilot.core.proposals import ProposalError, ProposalStore
from tests.core.studio_helpers import SHA, proposal, toy_guard


@pytest.fixture
def inbox(tmp_path) -> ProposalStore:
    proposals_module._VERIFIED.clear()
    return ProposalStore.at(tmp_path / "session", SHA, toy_guard)


def _three(inbox):
    return [
        inbox.propose(proposal(subject=s, payload={"group": g}), "agent").proposal.id
        for s, g in (("S1", "LPS"), ("S2", "PBS"), ("S3", "LPS"))
    ]


def test_the_same_bytes_are_verified_once(inbox, monkeypatch):
    _three(inbox)
    calls = []
    real = proposals_module.verify_proposal_chain
    monkeypatch.setattr(
        proposals_module, "verify_proposal_chain", lambda *a: calls.append(1) or real(*a)
    )
    first = inbox.proposals()
    for _ in range(5):
        assert inbox.proposals() == first
        inbox.head()
    assert len(calls) == 1


def test_a_tampered_chain_is_refused_even_after_it_was_verified(inbox):
    pid = _three(inbox)[0]
    inbox.proposals()  # verified and kept
    st = inbox.path.stat()
    text = inbox.path.read_text()
    forged = text.replace('"LPS"', '"PBS"', 1)
    assert len(forged) == len(text)
    inbox.path.write_text(forged)
    os.utime(inbox.path, ns=(st.st_atime_ns, st.st_mtime_ns))  # same size, same time
    with pytest.raises(ProposalError, match="does not verify at entry 1"):
        inbox.proposals()
    with pytest.raises(ProposalError):
        inbox.accept(pid, "human")
    inbox.path.write_text(text)  # put back: the kept result is good again
    assert len(inbox.proposals()) == 3


def test_a_write_never_changes_what_was_kept(inbox):
    first, second, _ = _three(inbox)
    before = {p.id: p.status for p in inbox.proposals()}
    assert inbox.accept(first, "human", "matches the sheet").status == "accepted"
    after = {p.id: p.status for p in inbox.proposals()}
    assert after[first] == "accepted" and before[first] == "proposed"
    # The replay of the earlier bytes (kept) still says what those bytes say.
    kept = [state for _, state in proposals_module._VERIFIED.values() if len(state.proposals) == 3]
    undecided = [state for state in kept if not state.decided]
    assert undecided and all(s.proposals[first].status == "proposed" for s in undecided)
    assert inbox.reject(second, "human", "not in this study").status == "rejected"
    assert {p.id: p.status for p in inbox.proposals()}[second] == "rejected"


def test_returned_views_are_the_callers_own(inbox):
    _three(inbox)
    entries = inbox.entries()
    entries.clear()
    assert len(inbox.entries()) == 3
    head, props = inbox.snapshot()
    props.clear()
    assert len(inbox.snapshot()[1]) == 3
