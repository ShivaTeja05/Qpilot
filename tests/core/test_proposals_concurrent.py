"""Several processes use one inbox at once: the chain stays valid and only one tab wins."""

import multiprocessing as mp

from qpilot.core.proposals import (
    ProposalStore,
    canonical_line,
    chain_lines,
    first_altered_line,
    verify_proposal_chain,
)
from tests.core.studio_helpers import SHA, proposal


def _propose_many(folder, worker, barrier, results):
    inbox = ProposalStore.at(folder, SHA)
    barrier.wait()
    statuses = [inbox.propose(proposal(subject=f"W{worker}_{i}"), "agent").status for i in range(5)]
    results.put(statuses)


def _accept(folder, pid, head, barrier, results):
    inbox = ProposalStore.at(folder, SHA)
    barrier.wait()
    results.put(inbox.accept(pid, "human", f"tab for {pid}", head).status)


def _run(target, args_list):
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(len(args_list))
    results = ctx.Queue()
    procs = [ctx.Process(target=target, args=(*a, barrier, results)) for a in args_list]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0
    return [results.get(timeout=5) for _ in procs]


def test_concurrent_proposers_keep_one_valid_chain(tmp_path):
    folder = str(tmp_path / "session")
    out = _run(_propose_many, [(folder, w) for w in range(4)])
    assert all(statuses == ["proposed"] * 5 for statuses in out)
    inbox = ProposalStore.at(folder, SHA)
    entries = inbox.entries()
    lines = chain_lines(inbox.path)
    assert len(entries) == 20 and [e.seq for e in entries] == list(range(1, 21))
    assert verify_proposal_chain(entries, SHA) is None
    assert first_altered_line(lines, entries) is None
    assert lines == [canonical_line(e) for e in entries]
    assert len({p.id for p in inbox.proposals("proposed")}) == 20


def test_two_tabs_in_two_processes_one_accepted_one_stale(tmp_path):
    folder = tmp_path / "session"
    inbox = ProposalStore.at(folder, SHA)
    first = inbox.propose(proposal(subject="S1"), "agent").proposal.id
    second = inbox.propose(proposal(subject="S2"), "agent").proposal.id
    head = inbox.head()
    out = _run(_accept, [(str(folder), first, head), (str(folder), second, head)])
    assert sorted(out) == ["accepted", "stale"]
    entries = inbox.entries()
    assert [e.action for e in entries] == ["propose", "propose", "accept"]  # the loser wrote none
    assert verify_proposal_chain(entries, SHA) is None
