"""Two processes decide the same card at the same moment: exactly one wins."""

import multiprocessing as mp

from qpilot.core.store import StudyStore, entry_hash


def _decide(root, study_id, option, head, barrier, results):
    store = StudyStore(root)
    barrier.wait()
    out = store.append_decision(study_id, "card_refset", option, f"pick {option}", "human", head)
    results.put(out.status)


def test_two_processes_one_applied_one_stale(store, study):
    head = store.chain_head(study)
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(2)
    results = ctx.Queue()
    procs = [
        ctx.Process(target=_decide, args=(str(store.root), study, opt, head, barrier, results))
        for opt in ("recommended", "hmbs_alone")
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0
    statuses = sorted(results.get(timeout=5) for _ in procs)
    assert statuses == ["applied", "stale"]

    entries = store.entries(study)
    assert [e.seq for e in entries] == list(range(1, len(entries) + 1))
    for prev, entry in zip(entries, entries[1:], strict=False):
        assert entry.prev_hash == prev.hash
        assert entry.hash == entry_hash(entry)
    assert [e.status for e in entries[1:]] == ["applied"]  # the loser is not in the chain
    assert [a["status"] for a in store.attempts(study)] == ["stale"]
