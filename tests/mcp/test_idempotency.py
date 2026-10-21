"""Idempotency keys: a retried ``qpcr_decide`` or ``qpcr_propose`` is answered, never logged twice.

The first answer that recorded something is kept for a day under the key; the same key with the
same arguments gets it back (``idempotent_replay``), the same key with other arguments is refused
(``idempotency_key_reused``), and a refusal is not kept, so the corrected request may reuse it.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from qpilot.agents import idempotency
from qpilot.agents.idempotency import LEDGER_DIR, TTL_S, IdempotencyLedger
from qpilot.agents.outputs import DecideOut, ProposeOut

KEY = "retry-of-request-1"


def recorded(store, study_id):
    """Everything a decide call can write: the chain head, the log and the person's queue."""
    return (
        store.chain_head(study_id),
        len(store.entries(study_id)),
        [(p.card_id, p.option, p.actor) for p in store.pending(study_id)],
    )


def ask(tools, study_id, key=KEY, option="hmbs_alone", **kw):
    return tools.qpcr_decide(
        study_id, "card_refset", option, "HMBS is the most stable", idempotency_key=key, **kw
    )


def test_without_a_key_a_retry_is_logged_again(tools, demo):
    """Why the key exists: the same request sent twice asks the person twice."""
    _, study_id = demo
    ask(tools, study_id, key=None)
    ask(tools, study_id, key=None)
    assert len(tools.store.pending(study_id)) == 2


def test_a_retry_with_the_key_gets_the_first_answer_and_logs_nothing(tools, demo):
    _, study_id = demo
    first = ask(tools, study_id)
    assert first["status"] == "pending_human" and "idempotent_replay" not in first
    after_first = recorded(tools.store, study_id)
    again = ask(tools, study_id)
    assert again == {**first, "idempotent_replay": True}
    assert recorded(tools.store, study_id) == after_first
    DecideOut.model_validate(again)


def test_the_same_key_for_another_request_is_refused_and_logs_nothing(tools, demo):
    _, study_id = demo
    ask(tools, study_id)
    before = recorded(tools.store, study_id)
    other = ask(tools, study_id, option="top3")
    assert other["code"] == "idempotency_key_reused" and other["field"] == "idempotency_key"
    assert "error" in other and recorded(tools.store, study_id) == before
    proposed = tools.qpcr_propose(
        study_id, "design.group", "S1", {"group": "LPS"}, idempotency_key=KEY
    )
    assert proposed["code"] == "idempotency_key_reused"  # a key is not shared across tools
    assert tools.qpcr_proposals(study_id)["proposals"] == []


def test_a_refusal_is_not_kept_so_the_corrected_request_may_reuse_the_key(tools, demo):
    _, study_id = demo
    wrong = ask(tools, study_id, option="no_such_option")
    assert wrong["code"] == "unknown_item"
    right = ask(tools, study_id)
    assert right["status"] == "pending_human" and "idempotent_replay" not in right


def test_a_stale_answer_is_not_kept_so_the_retry_with_the_new_head_runs(tools, demo):
    _, study_id = demo
    tools.store.set_autonomy(study_id, "decide_and_tell")

    def cap(head):
        return tools.qpcr_decide(
            study_id, "card_undetermined", "cap", "try cap", expected_head=head,
            idempotency_key=KEY,
        )  # fmt: skip

    stale = cap("0" * 64)
    assert (stale["status"], stale["code"]) == ("stale", "stale_head")
    applied = cap(stale["chain_head"])
    assert applied["status"] == "applied" and "idempotent_replay" not in applied
    replay = cap(stale["chain_head"])
    assert replay["idempotent_replay"] is True and replay["status"] == "applied"
    agent_entries = [e for e in tools.store.entries(study_id) if e.actor == "agent"]
    assert len(agent_entries) == 1


@pytest.mark.parametrize("key", ["", " ", "has space", "x" * 129, "-starts-with-dash", "ü-key", 7])
def test_a_key_that_is_not_a_plain_token_is_refused(tools, demo, key):
    _, study_id = demo
    before = recorded(tools.store, study_id)
    out = ask(tools, study_id, key=key)
    assert out["code"] == "invalid_argument" and out["field"] == "idempotency_key"
    assert recorded(tools.store, study_id) == before


def test_an_expired_answer_is_not_replayed(tools, demo, monkeypatch):
    _, study_id = demo
    ask(tools, study_id)
    now = idempotency._now()
    monkeypatch.setattr(idempotency, "_now", lambda: now + TTL_S + 1)
    again = ask(tools, study_id)
    assert "idempotent_replay" not in again
    assert len(tools.store.pending(study_id)) == 2


def test_a_retried_proposal_adds_nothing_to_the_inbox(tools, demo):
    _, study_id = demo

    def propose():
        return tools.qpcr_propose(
            study_id, "design.group", "S1", {"group": "LPS"}, idempotency_key=KEY
        )

    first = propose()
    assert first["status"] == "proposed"
    inbox = tools.qpcr_proposals(study_id)
    again = propose()
    assert again == {**first, "idempotent_replay": True}
    assert tools.qpcr_proposals(study_id) == inbox
    ProposeOut.model_validate(again)


def test_concurrent_retries_record_one_request(tools, demo):
    _, study_id = demo
    start = threading.Barrier(4)

    def send(_):
        start.wait()
        return ask(tools, study_id)

    with ThreadPoolExecutor(4) as pool:
        answers = list(pool.map(send, range(4)))
    assert sum("idempotent_replay" not in a for a in answers) == 1
    assert len(tools.store.pending(study_id)) == 1


def test_the_ledger_lives_beside_the_workspaces_never_inside(tools, demo):
    _, study_id = demo
    ask(tools, study_id)
    folder = tools.store.root / LEDGER_DIR
    files = [p for p in folder.rglob("*.json")]
    assert len(files) == 1 and KEY not in files[0].read_text(encoding="utf-8")  # stored hashed
    workspace = tools.store.workspace(study_id)
    assert not any(KEY in p.read_text(errors="ignore") for p in workspace.rglob("*") if p.is_file())
    assert tools.store.list_studies() == [study_id]  # the ledger is not a study
    assert IdempotencyLedger(tools.store.root).folder == folder


def test_a_replay_over_mcp_matches_the_output_schema(served, demo):
    _, study_id = demo
    args = {
        "study_id": study_id,
        "card_id": "card_refset",
        "option": "top3",
        "reason": "x",
        "idempotency_key": KEY,
    }
    first, again = served("qpcr_decide", args), served("qpcr_decide", args)
    assert first.is_error is False and again.is_error is False
    assert again.structured_content == {**first.structured_content, "idempotent_replay": True}
    reused = served("qpcr_decide", {**args, "option": "hmbs_alone"})
    assert reused.is_error is True
    assert reused.structured_content["code"] == "idempotency_key_reused"
