"""Run reviews: a person's sign-off in the decision chain that no card replays.

A review entry is human-only, its comment is cleaned like a decision's reason, it never makes
another write stale, the replay rules (pending requests, card states, ``put``) skip it, and an
Analysis Record that holds one verifies.
"""

import json
from pathlib import Path

import pytest

from qpilot.core.decisions import DecisionError, apply_decision
from qpilot.core.record import _write_checksums, verify, write_record
from qpilot.core.store import (
    MAX_REVIEWER,
    REVIEW_CARD,
    StaleReview,
    changed_since,
    entry_hash,
    entry_line,
    pending_after,
    replay_cards,
)
from qpilot.schemas import DecisionEntry
from tests.core.ondemand_helpers import sha, trace_card


def _reseal(rec: Path) -> None:
    (rec / "CHECKSUMS.sha256").unlink()
    _write_checksums(rec)


def test_a_person_signs_off_the_run(store, study):
    head = store.chain_head(study)
    entry = store.append_review(
        study, "accept", "curves look clean all plates checked", "A. Reviewer"
    )
    assert (entry.kind, entry.card_id, entry.option, entry.outcome) == (
        "review",
        REVIEW_CARD,
        "accept",
        "accept",
    )
    assert entry.reason == "curves look clean all plates checked"
    assert (entry.reviewer, entry.actor, entry.status) == ("A. Reviewer", "human", "applied")
    assert entry.prev_hash == head and entry.hash == entry_hash(entry)
    assert store.chain_head(study) == entry.hash
    assert store.reviews(study) == [entry] and store.entries(study)[-1] == entry
    line = (store.workspace(study) / "decisions.jsonl").read_text().splitlines()[-1]
    assert line == entry_line(entry)
    assert {"kind", "outcome", "reviewer"} <= set(json.loads(line))


@pytest.mark.parametrize("outcome", ["accept", "repeat", "discuss"])
def test_every_outcome_is_recorded(store, study, outcome):
    entry = store.append_review(study, outcome, "why", "AR", expected_head=store.chain_head(study))
    assert entry.outcome == outcome and store.reviews(study)[-1].option == outcome


class _LooksHuman(str):
    def __eq__(self, other):
        return True

    __hash__ = str.__hash__


@pytest.mark.parametrize("actor", ["agent", "system", "Human", "human ", None, 1, _LooksHuman("x")])
def test_only_a_person_reviews(store, study, actor):
    head = store.chain_head(study)
    with pytest.raises(DecisionError, match="only a person"):
        store.append_review(study, "accept", "fine", "AR", actor=actor)
    assert store.chain_head(study) == head and store.reviews(study) == []


@pytest.mark.parametrize(
    ("outcome", "comment", "reviewer", "match"),
    [
        ("approve", "fine", "AR", "outcome is one of"),
        ("Accept", "fine", "AR", "outcome is one of"),
        (None, "fine", "AR", "outcome is one of"),
        ("accept", "", "AR", "a comment is required"),
        ("accept", "   ", "AR", "a comment is required"),
        ("accept", "x" * 501, "AR", "longer than 500"),
        ("accept", 5, "AR", "must be text"),
        ("accept", "fine", "", "a reviewer is required"),
        ("accept", "fine", "r" * (MAX_REVIEWER + 1), f"longer than {MAX_REVIEWER}"),
        ("accept", "fine", ["AR"], "must be text"),
    ],
)
def test_review_fields_are_checked(store, study, outcome, comment, reviewer, match):
    with pytest.raises(DecisionError, match=match):
        store.append_review(study, outcome, comment, reviewer)
    assert store.reviews(study) == []


def test_a_review_never_makes_another_write_stale(store, study, fixture_result):
    store.open_card(study, trace_card(fixture_result))
    writes = [
        lambda head: store.request_human(study, "card_cutoff", "cut_10", "ask", "agent", head),
        lambda head: store.append_decision(study, "card_refset", "top2", "stable", "human", head),
        lambda head: apply_decision(
            store, study, "card_trace_camta2_1", "keep", "fine", "human", head
        ),
        lambda head: store.reject_pending(study, "card_cutoff", "no", head, option="cut_10"),
    ]
    for write in writes:
        head = store.chain_head(study)  # what the app or an agent read
        store.append_review(study, "discuss", "ask about the plate", "AR", expected_head=head)
        store.append_review(study, "accept", "a second reviewer", "BR")
        assert write(head).status != "stale"
    assert store.attempts(study) == []
    assert [e.status for e in store.entries(study) if e.kind is None][1:] == [
        "pending_human",
        "applied",
        "applied",
        "rejected",
    ]


def test_changed_since_skips_reviews(store, study):
    head = store.chain_head(study)
    store.append_review(study, "accept", "ok", "AR")
    entries = store.entries(study)
    root = store.get(study).input_sha256
    for card_id in ("card_refset", REVIEW_CARD):
        for status in ("applied", "pending_human", "rejected"):
            assert not changed_since(entries, root, head, card_id, status)
    assert not changed_since(entries, root, entries[-1].hash, "card_refset", "applied")
    assert changed_since(entries, root, "f" * 64, "card_refset", "applied")


def test_a_review_goes_stale_when_a_person_decided_in_between(store, study):
    head = store.chain_head(study)
    store.request_human(study, "card_cutoff", "cut_10", "agent asks", "agent", None)
    store.append_review(study, "accept", "first reviewer", "AR", expected_head=head)
    store.append_review(study, "repeat", "second reviewer", "BR", expected_head=head)
    store.append_decision(study, "card_refset", "top2", "stable", "human", None)
    moved = store.chain_head(study)
    with pytest.raises(StaleReview, match="changed since you read it"):
        store.append_review(study, "accept", "late", "CR", expected_head=head)
    assert store.chain_head(study) == moved
    attempt = store.attempts(study)[-1]
    assert (attempt["attempted"], attempt["card_id"], attempt["option"]) == (
        "review",
        REVIEW_CARD,
        "accept",
    )
    with pytest.raises(StaleReview):
        store.append_review(study, "accept", "unknown head", "CR", expected_head="0" * 64)
    assert [r.reviewer for r in store.reviews(study)] == ["AR", "BR"]


def test_reviews_are_not_card_decisions(store, study):
    store.request_human(study, "card_cutoff", "cut_10", "agent asks", "agent", None)
    ws = store.workspace(study)
    cards_before, pending_before = sha(ws / "cards.json"), sha(ws / "pending.jsonl")
    store.append_review(study, "accept", "ok", "AR")
    assert sha(ws / "cards.json") == cards_before and sha(ws / "pending.jsonl") == pending_before
    entries = store.entries(study)
    without = [e for e in entries if e.kind is None]
    assert pending_after(entries) == pending_after(without)
    assert replay_cards(store.cards(study), entries) == replay_cards(store.cards(study), without)
    assert store.card(study, "card_cutoff").status == "pending_human"


def test_put_skips_reviews(store, fixture_result, fixture_cards):
    open_cards = [c.model_copy(update={"status": "open", "decision": None}) for c in fixture_cards]
    open_cards = [c.model_copy(update={"reason": None, "decided_by": None}) for c in open_cards]
    store.put(fixture_result, open_cards)
    sid = fixture_result.study_id
    assert store.entries(sid) == []
    review = store.append_review(sid, "accept", "ok", "AR")
    store.put(fixture_result, fixture_cards)  # the analysis now decides one card itself
    entries = store.entries(sid)
    assert [(e.kind, e.card_id, e.status) for e in entries] == [
        ("review", REVIEW_CARD, "applied"),
        (None, "card_undetermined", "auto"),
    ]
    assert entries[1].prev_hash == review.hash
    assert store.card(sid, "card_undetermined").status == "auto_decided"
    store.put(fixture_result, fixture_cards)
    assert len(store.entries(sid)) == 2  # no second system entry


def test_a_record_with_reviews_verifies(store, study, tmp_path):
    store.append_decision(study, "card_refset", "top2", "stable", "human", None)
    store.append_review(study, "accept", "signed off", "AR")
    rec = Path(write_record(store, study, tmp_path / "rec").record_dir)
    report = verify(rec)
    assert report.ok, report.summary()
    assert report.n_entries == 3
    choices = json.loads((rec / "choices.json").read_text())["cards"]
    assert REVIEW_CARD not in choices
    assert json.loads((rec / "record.json").read_text())["chain_head"] == store.chain_head(study)


def _rechain(entries: list[DecisionEntry], root: str) -> list[DecisionEntry]:
    """What a forger does: rewrite every link and hash so the chain itself checks out."""
    out = []
    prev = root
    for entry in entries:
        entry = entry.model_copy(update={"prev_hash": prev, "hash": ""})
        entry = entry.model_copy(update={"hash": entry_hash(entry)})
        out.append(entry)
        prev = entry.hash
    return out


@pytest.mark.parametrize(
    "forgery",
    [
        {"actor": "agent"},
        {"status": "pending_human"},
        {"card_id": "card_refset"},
        {"option": "repeat"},
        {"reviewer": ""},
        {"outcome": None},
    ],
)
def test_a_forged_review_is_reported_even_with_valid_hashes(store, study, tmp_path, forgery):
    store.append_review(study, "accept", "signed off", "AR")
    rec = Path(write_record(store, study, tmp_path / "rec").record_dir)
    log = rec / "decisions.jsonl"
    entries = [DecisionEntry.model_validate_json(x) for x in log.read_text().splitlines()]
    entries[-1] = entries[-1].model_copy(update=forgery)
    entries = _rechain(entries, store.get(study).input_sha256)
    log.write_text("".join(entry_line(e) + "\n" for e in entries))
    meta = json.loads((rec / "record.json").read_text())
    meta["chain_head"] = entries[-1].hash
    (rec / "record.json").write_text(json.dumps(meta, sort_keys=True, indent=2) + "\n")
    _reseal(rec)
    report = verify(rec)
    assert not report.ok and report.chain_broken_at is None
    assert f"decisions.jsonl entry {entries[-1].seq} is a review no person signed" in (
        report.inconsistent
    )


def test_an_extra_field_on_a_review_line_is_caught(store, study, tmp_path):
    store.append_review(study, "accept", "signed off", "AR")
    rec = Path(write_record(store, study, tmp_path / "rec").record_dir)
    log = rec / "decisions.jsonl"
    lines = log.read_text().splitlines()
    data = json.loads(lines[-1])
    data["reviewer"] = "AR"
    data["kind"] = "review"
    lines[-1] = json.dumps(data)  # same content, not the canonical bytes
    log.write_text("\n".join(lines) + "\n")
    _reseal(rec)
    assert verify(rec).chain_broken_at == len(lines)
