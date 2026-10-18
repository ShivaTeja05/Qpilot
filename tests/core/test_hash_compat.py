"""Decision logs written by the c3fbb16 code still hash, verify and extend byte for byte.

Adding ``kind``, ``outcome`` and ``reviewer`` to :class:`~qpilot.schemas.DecisionEntry` would
change every old entry's hash if the None fields were hashed (gap G6). The store now hashes and
stores entries without their None fields, so an old line is exactly the canonical form of the
entry it parses to and its hash recomputes unchanged.

The pins below were produced by running the c3fbb16 tree itself (``git archive c3fbb16``) on
the fixture study with a fixed clock: a ``system`` auto entry, a person's decision with
non-ASCII text, two agent requests and a person's rejection of one of them.
"""

import hashlib
import json
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel

import qpilot.core.store as store_module
from qpilot.core.record import verify, verify_chain, write_record
from qpilot.core.store import canonical_json, entry_hash, entry_line
from qpilot.schemas import DecisionEntry

ROOT = "bc1d233e3866ad4d32736a9feea832ea6261a9c75d82a78e465d31bad554e151"
OLD_HASHES = [
    "bddc33d25e2901f2dacc3d5b7ca86e3dd30e10c3a93f76d4540d542c7b05d6df",
    "1d6db7b70841162d8dd0783fea152d228b3fac18c6d889b3623e6e58c2781086",
    "15726cd568b3f6052d9918f91050306363cc8fe5dfdaea31fccc76f49696e18c",
    "8b99c3944819a9a6a251a77506830d5417cd3409905b90912be9a92b1968038f",
    "c6d1b37553156c607ad07488382bea35861fa1bebe9076f6e49a141a8e8e7536",
]
OLD_FILES = {  # sha256 of the workspace files c3fbb16 wrote for that sequence
    "decisions.jsonl": "32df1b60174dd48780c853f5bba9e77d3ea1b27c00d2a9538eb39d7411fdbb2a",
    "pending.jsonl": "bab084dd62c77505048ced804c0ceb0edac9de5cbbb66ddceb270c332847f0eb",
    "cards.json": "425e388eeda55e387ee5c9394d0754367d715b93ac8069bb1dded414d8b24bd7",
}
AUTO = "Decided automatically: no option on this card changes any conclusion."
# (card_id, option, reason, actor, status), in the order c3fbb16 wrote them
STEPS = [
    ("card_undetermined", "drop", AUTO, "system", "auto"),
    ("card_refset", "top2", "two most stable; ΔCq naïve check", "human", "applied"),
    ("card_cutoff", "cut_10", "the agent asks for a 10 % cut", "agent", "pending_human"),
    ("card_cutoff", "cut_20", "and asks for 20 %", "agent", "pending_human"),
    ("card_cutoff", "cut_10", "not now", "human", "rejected"),
]


class OldDecisionEntry(BaseModel):
    """``DecisionEntry`` exactly as c3fbb16 defined it (``qpilot/schemas.py:140-151``)."""

    seq: int
    prev_hash: str
    card_id: str
    option: str
    reason: str
    actor: Literal["human", "agent", "system"]
    status: Literal["applied", "stale", "pending_human", "rejected", "auto"]
    at: str
    hash: str = ""


def old_entry_hash(entry: OldDecisionEntry) -> str:
    """c3fbb16 ``store.entry_hash``: every field but ``hash``, no ``exclude_none``."""
    payload = canonical_json(entry.model_dump(mode="json", exclude={"hash"}))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def old_line(entry: OldDecisionEntry) -> str:
    """c3fbb16 ``StudyStore._append``: the stored line is the full canonical dump."""
    return canonical_json(entry.model_dump(mode="json"))


def at(i: int) -> str:
    return f"2026-10-18T09:00:{i:02d}Z"


def old_log() -> list[str]:
    """The decision log of :data:`STEPS`, built the way c3fbb16 built it."""
    lines, prev = [], ROOT
    for i, (card_id, option, reason, actor, status) in enumerate(STEPS):
        entry = OldDecisionEntry(
            seq=i + 1,
            prev_hash=prev,
            card_id=card_id,
            option=option,
            reason=reason,
            actor=actor,
            status=status,
            at=at(i),
        )
        entry = entry.model_copy(update={"hash": old_entry_hash(entry)})
        lines.append(old_line(entry))
        prev = entry.hash
    return lines


def test_the_old_formula_reproduces_the_c3fbb16_hashes():
    hashes = [json.loads(line)["hash"] for line in old_log()]
    assert hashes == OLD_HASHES
    text = "".join(line + "\n" for line in old_log())
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == OLD_FILES["decisions.jsonl"]


def test_new_code_hashes_old_entries_identically():
    entries = [DecisionEntry.model_validate_json(line) for line in old_log()]
    assert [entry_hash(e) for e in entries] == [e.hash for e in entries] == OLD_HASHES
    assert [entry_line(e) for e in entries] == old_log()  # byte-identical stored lines
    assert all(e.kind is None and e.outcome is None and e.reviewer is None for e in entries)
    assert verify_chain(entries, ROOT) is None


def test_without_exclude_none_the_new_fields_would_change_every_hash():
    entry = DecisionEntry.model_validate_json(old_log()[0])
    naive = canonical_json(entry.model_dump(mode="json", exclude={"hash"}))
    assert hashlib.sha256(naive.encode("utf-8")).hexdigest() != OLD_HASHES[0]


def _run_steps(store, study_id):
    """The c3fbb16 sequence through today's store (the auto entry comes from put)."""
    for card_id, option, reason, actor, status in STEPS[1:]:
        if status == "applied":
            store.append_decision(study_id, card_id, option, reason, actor, None)
        elif status == "pending_human":
            store.request_human(study_id, card_id, option, reason, actor, None)
        else:
            store.reject_pending(study_id, card_id, reason, None, option=option)


def test_new_code_writes_the_c3fbb16_bytes(monkeypatch, store, fixture_result, fixture_cards):
    clock = iter(at(i) for i in range(len(STEPS)))
    monkeypatch.setattr(store_module, "_now", lambda: next(clock))
    store.put(fixture_result, fixture_cards)
    _run_steps(store, fixture_result.study_id)
    ws = store.workspace(fixture_result.study_id)
    for name, digest in OLD_FILES.items():
        assert hashlib.sha256((ws / name).read_bytes()).hexdigest() == digest, name
    assert store.chain_head(fixture_result.study_id) == OLD_HASHES[-1]


def test_an_old_log_in_a_record_verifies_and_extends(store, study, tmp_path):
    ws = store.workspace(study)
    (ws / "decisions.jsonl").write_text("".join(line + "\n" for line in old_log()))
    store.put(store.get(study), store.cards(study))  # rebuild cards.json and pending.jsonl
    assert store.chain_head(study) == OLD_HASHES[-1]
    assert [p.option for p in store.pending(study)] == ["cut_20"]
    assert (ws / "decisions.jsonl").read_text().splitlines() == old_log()  # not rewritten
    report = verify(write_record(store, study, tmp_path / "old").record_dir)
    assert report.ok, report.summary()
    assert report.n_entries == len(OLD_HASHES)
    review = store.append_review(study, "accept", "checked", "AR", expected_head=OLD_HASHES[-1])
    assert review.prev_hash == OLD_HASHES[-1]
    out = store.append_decision(study, "card_cutoff", "cut_20", "agreed", "human", review.hash)
    assert out.status == "applied"
    lines = (ws / "decisions.jsonl").read_text().splitlines()
    assert lines[: len(OLD_HASHES)] == old_log()
    report = verify(write_record(store, study, tmp_path / "extended").record_dir)
    assert report.ok, report.summary()
    assert report.n_entries == len(OLD_HASHES) + 2


@pytest.mark.parametrize("field", ["kind", "outcome", "reviewer"])
def test_an_old_line_with_a_null_new_field_is_not_its_canonical_form(field, tmp_path):
    """A null field added to an old line is an altered line, not the same entry."""
    from qpilot.core.record import _first_altered_line

    data = json.loads(old_log()[0])
    data[field] = None
    log = tmp_path / "decisions.jsonl"
    log.write_text(canonical_json(data) + "\n")
    entries = [DecisionEntry.model_validate_json(canonical_json(data))]
    assert entry_hash(entries[0]) == OLD_HASHES[0]  # the hash ignores None fields
    assert _first_altered_line(Path(log), entries) == 1  # but the stored bytes are checked
