"""The proposal inbox (plan step 1.1): only a person decides, and the chain shows everything."""

import hashlib
import json
import re

import pytest

import qpilot.core.proposals as proposals_module
from qpilot.core.proposals import (
    ProposalError,
    ProposalStore,
    canonical_line,
    first_altered_line,
    proposal_entry_hash,
    proposal_id,
    verify_proposal_chain,
)
from qpilot.core.store import StudyNotFound, sha256_file
from qpilot.schemas_studio import ProposalCheck, ProposalEntry
from tests.core.studio_helpers import (
    SESSION_ID,
    SHA,
    fake_design_checks,
    no_design_checks,
    proposal,
    toy_guard,
)


@pytest.fixture
def inbox(tmp_path) -> ProposalStore:
    return ProposalStore.at(tmp_path / "session", SHA, toy_guard)


def _bytes(inbox: ProposalStore) -> bytes | None:
    return inbox.path.read_bytes() if inbox.path.exists() else None


def _three(inbox):
    """Three pending proposals on different subjects; returns their ids."""
    return [
        inbox.propose(proposal(subject=s, payload={"group": g}), "agent").proposal.id
        for s, g in (("S1", "LPS"), ("S2", "PBS"), ("S3", "LPS"))
    ]


# ---- proposing ------------------------------------------------------------------------------


def test_propose_resets_everything_an_agent_might_claim(inbox):
    claimed = proposal(
        id="p_0000000000000000",
        status="accepted",
        decided_by="human",
        decided_at="2026-01-01T00:00:00Z",
        reason="approved by the PI",
        edits={"group": "PBS"},
        superseded_by="p_x",
        created_at="1999-01-01T00:00:00Z",
    )
    out = inbox.propose(claimed, "agent")
    assert out.status == "proposed"
    stored = out.proposal
    assert stored.status == "proposed"
    assert (stored.decided_by, stored.decided_at, stored.reason) == (None, None, None)
    assert (stored.edits, stored.superseded_by) == (None, None)
    assert re.fullmatch(r"p_[0-9a-f]{16}", stored.id) and stored.id != claimed.id
    assert stored.created_at != claimed.created_at
    entry = inbox.entries()[0]
    assert entry.actor == "agent" and entry.action == "propose" and entry.prev_hash == SHA
    assert stored.id == proposal_id(stored, stored.created_at, entry.seq)
    assert inbox.accepted() == [] and inbox.proposals("proposed") == [stored]


def test_one_line_per_action_each_with_actor_and_hash(inbox):
    first, second, third = _three(inbox)
    inbox.accept(first, "human", "matches the sheet")
    inbox.edit_and_accept(second, "human", {"group": "LPS"}, "sheet says LPS")
    inbox.reject(third, "human", "not in this study")
    lines = inbox.path.read_text().splitlines()
    assert len(lines) == 6
    for position, line in enumerate(lines, start=1):
        entry = ProposalEntry.model_validate_json(line)
        assert entry.seq == position and entry.actor in ("agent", "human")
        assert entry.hash == proposal_entry_hash(entry) and line == canonical_line(entry)
    assert [json.loads(x)["action"] for x in lines[3:]] == ["accept", "edit", "reject"]


def test_hash_ignores_fields_that_are_none(inbox):
    inbox.propose(proposal(), "agent")
    entry = inbox.entries()[0]
    data = entry.model_dump(mode="json", exclude={"hash"})
    assert data["edits"] is None and data["superseded_by"] is None
    without_none = {k: v for k, v in data.items() if v is not None}
    without_none["proposal"] = {k: v for k, v in data["proposal"].items() if v is not None}
    made_by = without_none["proposal"]["made_by"]
    without_none["proposal"]["made_by"] = {k: v for k, v in made_by.items() if v is not None}
    canonical = json.dumps(without_none, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert entry.hash == hashlib.sha256(canonical.encode()).hexdigest()

    class Later(ProposalEntry):  # a later build adds an optional field
        signed_by: str | None = None

    assert proposal_entry_hash(Later.model_validate(entry.model_dump())) == entry.hash


@pytest.mark.parametrize(
    "bad",
    [
        {"payload": {"group": "x" * 70_000}},
        {"payload": {"group": "x" * 2_001}},
        {"payload": {"x" * 2_001: 1}},
        {"payload": {"n": float("nan")}},
        {"payload": {"n": float("inf")}},
        {"payload": {"s": {1, 2}}},
        {"evidence": [proposal().evidence[0]] * 201},
        {"reasons": ["r"] * 51},
        {"subject": "   "},
        {"study_id": "ffffffffffff"},
    ],
)
def test_oversized_or_malformed_proposals_are_refused_not_cut(inbox, bad):
    out = inbox.propose(proposal(**bad), "agent")
    assert out.status == "refused" and out.reason and out.head == SHA
    assert not inbox.path.exists()


def test_a_kind_outside_the_contract_is_refused(inbox):
    forged = proposal().model_construct(**{**proposal().__dict__, "kind": "design.anything"})
    out = inbox.propose(forged, "agent")
    assert out.status == "refused" and "kind" in out.reason
    assert not inbox.path.exists()


def test_unknown_actor_is_an_error(inbox):
    with pytest.raises(ProposalError):
        inbox.propose(proposal(), "admin")


def test_a_newer_proposal_supersedes_the_pending_one_in_the_same_write(inbox):
    old = inbox.propose(proposal(payload={"group": "LPS"}), "agent").proposal
    new = inbox.propose(proposal(payload={"group": "PBS"}), "agent")
    entries = inbox.entries()
    assert [e.action for e in entries] == ["propose", "propose", "supersede"]
    assert entries[2].actor == "system" and entries[2].superseded_by == new.proposal.id
    assert new.head == entries[2].hash
    assert inbox.get(old.id).status == "superseded"
    refused = inbox.accept(old.id, "human", "too late")
    assert refused.status == "refused" and "superseded" in refused.reason
    # an accepted proposal is settled: a later one on the same subject does not supersede it
    inbox.accept(new.proposal.id, "human")
    inbox.propose(proposal(payload={"group": "LPS"}), "agent")
    assert inbox.get(new.proposal.id).status == "accepted"


# ---- only a person decides -------------------------------------------------------------------


class _Sneaky(str):
    def __eq__(self, other):
        return True

    def __ne__(self, other):
        return False

    __hash__ = str.__hash__


@pytest.mark.parametrize("actor", ["agent", "system", "Human", "human ", None, _Sneaky("agent")])
@pytest.mark.parametrize("action", ["accept", "edit", "reject", "bulk"])
def test_only_a_person_decides_and_the_file_stays_byte_identical(inbox, monkeypatch, actor, action):
    first = _three(inbox)[0]
    before = _bytes(inbox)

    def no_touch(*args, **kwargs):
        raise AssertionError("the lock or the file was touched before the actor was checked")

    monkeypatch.setattr(proposals_module, "FileLock", no_touch)
    monkeypatch.setattr(ProposalStore, "_load", no_touch)
    with pytest.raises(ProposalError, match="only a person"):
        if action == "accept":
            inbox.accept(first, actor, "agent says so")
        elif action == "edit":
            inbox.edit_and_accept(first, actor, {"group": "PBS"}, "agent says so")
        elif action == "reject":
            inbox.reject(first, actor, "agent says so")
        else:
            inbox.bulk_accept([first], actor, "agent says so")
    assert _bytes(inbox) == before


def test_a_person_accepts_edits_and_rejects(inbox):
    first, second, third = _three(inbox)
    out = inbox.accept(first, "human")
    assert out.status == "accepted" and out.proposal.decided_by == "human"
    out = inbox.edit_and_accept(second, "human", {"group": "LPS"}, "sheet says LPS")
    assert out.status == "edited" and out.proposal.effective_payload() == {"group": "LPS"}
    out = inbox.reject(third, "human", "not in this study")
    assert out.status == "rejected" and out.proposal.reason == "not in this study"
    assert [p.id for p in inbox.accepted()] == [first, second]
    assert inbox.accepted("curve.") == []
    assert {p.id: p.status for p in inbox.proposals()} == {
        first: "accepted",
        second: "edited",
        third: "rejected",
    }


def test_pending_proposals_never_appear_in_accepted(inbox):
    first, second, _ = _three(inbox)
    inbox.accept(second, "human")
    inbox.propose(
        proposal(kind="curve.call_rule", subject="amp_call", payload={"rule": "x"}), "agent"
    )
    assert [p.id for p in inbox.accepted()] == [second]
    assert all(p.status in ("accepted", "edited") for p in inbox.accepted())
    assert first in {p.id for p in inbox.proposals("proposed")}


def test_accepted_is_in_the_order_people_decided(inbox):
    first, second, _ = _three(inbox)
    inbox.accept(second, "human")
    inbox.accept(first, "human")
    assert [p.id for p in inbox.accepted()] == [second, first]


def test_reasons_are_required_cleaned_and_capped(inbox):
    first, second, _ = _three(inbox)
    before = _bytes(inbox)
    with pytest.raises(ProposalError, match="reason is required"):
        inbox.reject(first, "human", "   ")
    with pytest.raises(ProposalError, match="longer than 500"):
        inbox.reject(first, "human", "x" * 501)
    assert _bytes(inbox) == before
    out = inbox.reject(first, "human", "wrong group\u0085here")
    assert out.proposal.reason == "wrong group here"


def test_a_contradicted_proposal_needs_a_reason_to_be_accepted(inbox):
    pid = inbox.propose(proposal(check="contradicted"), "agent").proposal.id
    before = _bytes(inbox)
    with pytest.raises(ProposalError, match="contradicts"):
        inbox.accept(pid, "human")
    with pytest.raises(ProposalError, match="contradicts"):
        inbox.edit_and_accept(pid, "human", {"group": "PBS"}, "")
    assert _bytes(inbox) == before
    assert inbox.accept(pid, "human", "the dilution series is known to be bad").status == "accepted"


def test_edits_may_change_fields_but_never_add_them(inbox):
    pid = _three(inbox)[0]
    before = _bytes(inbox)
    with pytest.raises(ProposalError, match="not add"):
        inbox.edit_and_accept(pid, "human", {"group": "PBS", "role": "ntc"}, "x")
    for bad in ({}, {"group": float("nan")}, {"group": "x" * 70_000}, "group=PBS"):
        with pytest.raises(ProposalError):
            inbox.edit_and_accept(pid, "human", bad, "x")
    assert _bytes(inbox) == before


def test_a_settled_proposal_is_refused_without_a_write(inbox):
    pid = _three(inbox)[0]
    inbox.accept(pid, "human")
    before = _bytes(inbox)
    for out in (
        inbox.accept(pid, "human"),
        inbox.reject(pid, "human", "changed my mind"),
        inbox.edit_and_accept(pid, "human", {"group": "PBS"}, "x"),
    ):
        assert out.status == "refused" and "already accepted" in out.reason
    assert _bytes(inbox) == before
    with pytest.raises(KeyError, match="unknown proposal"):
        inbox.accept("p_nope", "human")


# ---- version check ---------------------------------------------------------------------------


def test_two_tabs_accepting_with_the_same_head_the_second_is_stale(inbox):
    first, second, _ = _three(inbox)
    head = inbox.head()
    assert inbox.accept(first, "human", "tab A", head).status == "accepted"
    before = _bytes(inbox)
    stale = inbox.accept(second, "human", "tab B", head)
    assert stale.status == "stale" and stale.head == inbox.head()
    same = inbox.accept(first, "human", "tab B too", head)
    assert same.status == "stale"
    assert _bytes(inbox) == before  # a stale attempt writes nothing anywhere
    assert not [p for p in inbox.workspace.iterdir() if "attempt" in p.name]


def test_an_agent_proposing_elsewhere_never_makes_a_person_stale(inbox):
    first = _three(inbox)[0]
    head = inbox.head()
    for i in range(5):  # an agent floods the inbox, including a supersede of another subject
        inbox.propose(proposal(subject=f"X{i}"), "agent")
    inbox.propose(proposal(subject="S2", payload={"group": "LPS"}), "agent")
    assert inbox.accept(first, "human", "still mine", head).status == "accepted"


def test_a_change_to_the_same_proposal_or_an_unknown_head_is_stale(inbox):
    pid = inbox.propose(proposal(), "agent").proposal.id
    head = inbox.head()
    inbox.propose(proposal(payload={"group": "PBS"}), "agent")  # supersedes pid
    assert inbox.accept(pid, "human", "x", head).status == "stale"
    newest = inbox.proposals("proposed")[0].id
    assert inbox.reject(newest, "human", "x", "0" * 64).status == "stale"


# ---- bulk acceptance ---------------------------------------------------------------------------


def test_bulk_accepts_only_the_listed_consistent_pending_ones(inbox):
    good = inbox.propose(proposal(subject="S1"), "agent").proposal.id
    also = inbox.propose(proposal(subject="S2"), "agent").proposal.id
    bad = inbox.propose(proposal(subject="S3", check="contradicted"), "agent").proposal.id
    unsure = inbox.propose(proposal(subject="S4", check="cannot_check"), "agent").proposal.id
    unlisted = inbox.propose(proposal(subject="S5"), "agent").proposal.id
    n_before = len(inbox.entries())
    outs = inbox.bulk_accept([good, bad, unsure, "p_nope", good, also], "human", "batch")
    assert [o.status for o in outs] == [
        "accepted",
        "refused",
        "refused",
        "refused",
        "refused",
        "accepted",
    ]
    assert "contradicted" in outs[1].reason and "cannot_check" in outs[2].reason
    assert outs[3].reason == "unknown proposal" and outs[4].reason == "listed twice"
    entries = inbox.entries()
    assert len(entries) == n_before + 2 and {e.proposal_id for e in entries[-2:]} == {good, also}
    assert all(e.action == "accept" and e.actor == "human" for e in entries[-2:])
    assert inbox.get(unlisted).status == "proposed"
    assert {p.id for p in inbox.accepted()} == {good, also}


def test_bulk_with_a_stale_head_accepts_nothing_that_changed(inbox):
    first, second, third = _three(inbox)
    head = inbox.head()
    inbox.accept(first, "human", "tab A")
    outs = inbox.bulk_accept([second, third], "human", "tab B", expected_head=head)
    assert [o.status for o in outs] == ["stale", "stale"]


# ---- the domain guard (hard bans) ------------------------------------------------------------


def test_demoting_a_control_is_refused_at_propose_with_no_write(inbox):
    demote = proposal(kind="design.well_role", subject="NTC_1", payload={"role": "unkn"})
    out = inbox.propose(demote, "agent")
    assert out.status == "refused" and "never demoted" in out.reason
    assert not inbox.path.exists()
    kept = inbox.propose(
        proposal(kind="design.well_role", subject="NRT_2", payload={"role": "nrt"}), "agent"
    )
    before = _bytes(inbox)
    out = inbox.edit_and_accept(kept.proposal.id, "human", {"role": "unkn"}, "person edits")
    assert out.status == "refused" and "never demoted" in out.reason
    assert _bytes(inbox) == before


def test_the_guard_sees_every_current_proposal(tmp_path):
    seen = []

    def guard(candidate, current):
        seen.append(sorted(p.status for p in current))
        return None

    inbox = ProposalStore.at(tmp_path / "s", SHA, guard)
    first = inbox.propose(proposal(subject="S1"), "agent").proposal.id
    inbox.accept(first, "human")
    inbox.propose(proposal(subject="S2"), "agent")
    assert seen == [[], [], ["accepted"]]


def test_a_guard_or_checker_that_meddles_changes_nothing_stored(tmp_path):
    def meddling_guard(candidate, current):
        candidate.payload["group"] = "PBS"
        for p in current:
            p.status = "accepted"
        return None

    def meddling_checker(candidate):
        candidate.payload["group"] = "PBS"
        return ProposalCheck(status="consistent")

    inbox = ProposalStore.at(tmp_path / "s", SHA, meddling_guard, checker=meddling_checker)
    first = inbox.propose(proposal(subject="S1"), "agent").proposal
    second = inbox.propose(proposal(subject="S2"), "agent").proposal
    inbox.accept(first.id, "human")
    assert first.payload == second.payload == {"group": "LPS"}
    assert [p.id for p in inbox.accepted()] == [first.id]
    assert inbox.get(second.id).status == "proposed"


def test_a_checker_replaces_the_callers_check(tmp_path):
    def engine(candidate):
        return ProposalCheck(status="contradicted", rule_ids=["D-NTC"], note="engine")

    inbox = ProposalStore.at(tmp_path / "s", SHA, checker=engine)
    pid = inbox.propose(proposal(check="consistent"), "agent").proposal.id
    assert inbox.get(pid).check.status == "contradicted"
    assert inbox.bulk_accept([pid], "human")[0].status == "refused"


def test_a_checker_returning_nan_is_refused_not_stored(tmp_path):
    def engine(candidate):
        return ProposalCheck(status="consistent", details={"r2": float("nan")})

    inbox = ProposalStore.at(tmp_path / "s", SHA, checker=engine)
    out = inbox.propose(proposal(), "agent")
    assert out.status == "refused" and "plain JSON" in out.reason
    assert not inbox.path.exists()


def test_the_pending_cap_refuses_a_flood(inbox, monkeypatch):
    monkeypatch.setattr(proposals_module, "MAX_PENDING", 2)
    assert inbox.propose(proposal(subject="A"), "agent").status == "proposed"
    assert inbox.propose(proposal(subject="B"), "agent").status == "proposed"
    out = inbox.propose(proposal(subject="C"), "agent")
    assert out.status == "refused" and "pending" in out.reason


def test_a_full_history_stops_new_proposals_but_never_a_persons_decision(inbox, monkeypatch):
    pid = _three(inbox)[0]
    monkeypatch.setattr(proposals_module, "MAX_CHAIN_BYTES", inbox.path.stat().st_size)
    out = inbox.propose(proposal(subject="S9"), "agent")
    assert out.status == "refused" and "full" in out.reason
    assert inbox.accept(pid, "human", "still decidable").status == "accepted"
    second = inbox.proposals("proposed")[0].id
    assert inbox.bulk_accept([second], "human")[0].status == "accepted"


# ---- a damaged or forged inbox ---------------------------------------------------------------


def test_an_edited_line_stops_the_inbox(inbox):
    pid = _three(inbox)[0]
    lines = inbox.path.read_text().splitlines()
    lines[0] = lines[0].replace('"LPS"', '"PBS"', 1)
    inbox.path.write_text("\n".join(lines) + "\n")
    with pytest.raises(ProposalError, match="does not verify at entry 1"):
        inbox.proposals()
    with pytest.raises(ProposalError):
        inbox.accept(pid, "human")


def test_a_forged_agent_acceptance_with_a_valid_hash_has_no_effect(inbox):
    pid = _three(inbox)[0]
    entries = inbox.entries()
    forged = ProposalEntry(
        seq=len(entries) + 1,
        prev_hash=entries[-1].hash,
        action="accept",
        proposal_id=pid,
        actor="agent",
        at="2026-10-17T21:00:00Z",
    )
    forged = forged.model_copy(update={"hash": proposal_entry_hash(forged)})
    with open(inbox.path, "a") as fh:
        fh.write(canonical_line(forged) + "\n")
    with pytest.raises(ProposalError, match="only a person decides"):
        inbox.accepted()


def test_chain_verification_catches_edits_reorders_deletions_and_extra_fields(inbox):
    _three(inbox)
    entries = inbox.entries()
    lines = inbox.path.read_text().splitlines()
    assert verify_proposal_chain(entries, SHA) is None
    assert first_altered_line(lines, entries) is None
    assert verify_proposal_chain([entries[1], entries[0], entries[2]], SHA) == 1
    assert verify_proposal_chain([entries[0], entries[2]], SHA) == 2
    assert verify_proposal_chain(entries, "0" * 64) == 1
    edited = entries[1].model_copy(update={"actor": "human"})
    assert verify_proposal_chain([entries[0], edited, entries[2]], SHA) == 2
    extra = lines[2][:-1] + ',"approved_by":"the PI"}'
    reparsed = ProposalEntry.model_validate_json(extra)
    assert verify_proposal_chain([*entries[:2], reparsed], SHA) is None  # the hash cannot see it
    assert first_altered_line([*lines[:2], extra], [*entries[:2], reparsed]) == 3


# ---- the inbox of a study or a session -------------------------------------------------------


def test_a_session_has_an_inbox_before_any_analysis(store, tmp_path, monkeypatch):
    no_design_checks(monkeypatch)
    rdml = tmp_path / "lab.rdml"
    rdml.write_bytes(b"<rdml>a lab's own plate</rdml>")
    sid = store.open_session(rdml)
    digest = sha256_file(rdml)
    assert sid == digest[:12] and store.find_session(sid).name == digest
    assert store.session_source(sid) == rdml.resolve()
    inbox = store.proposals(sid)
    assert inbox.study_id == sid and inbox.root == digest
    out = inbox.propose(proposal(study_id=sid), "agent")
    assert out.status == "proposed" and out.proposal.check.status == "cannot_check"
    assert (store.root / "sessions" / digest / "proposals.jsonl").exists()
    assert store.list_studies() == []


def test_a_studys_inbox_is_its_inputs_session(store, study, fixture_result, monkeypatch):
    no_design_checks(monkeypatch)
    inbox = store.proposals(study)
    assert inbox.workspace == store.root / "sessions" / fixture_result.input_sha256
    assert inbox.study_id == fixture_result.input_sha256[:12]
    assert ProposalStore(store, study).workspace == inbox.workspace
    assert not inbox.workspace.exists()  # created on the first write, not on a read
    assert inbox.proposals() == []
    inbox.propose(proposal(study_id=inbox.study_id), "agent")
    assert store.find_session(study) == inbox.workspace


@pytest.mark.parametrize("bad", ["../etc", "", "ZZZ", None, 123, "abcdef123456"])
def test_unknown_or_hostile_ids_have_no_inbox(store, bad):
    with pytest.raises(StudyNotFound):
        store.proposals(bad)
    with pytest.raises(ValueError):
        store.session("../" + "a" * 61)


def test_the_plugin_check_and_guard_are_wired_by_the_store(store, study, monkeypatch):
    calls = []
    fake_design_checks(monkeypatch, check_status="contradicted", calls=calls)
    inbox = store.proposals(study)
    out = inbox.propose(proposal(study_id=inbox.study_id, check="consistent"), "agent")
    assert out.proposal.check.status == "contradicted" and out.proposal.check.rule_ids == ["D-TOY"]
    assert calls == [("design.group", "S1", inbox.study_id)]
    demote = proposal(
        study_id=inbox.study_id, kind="design.well_role", subject="NTC_1", payload={"role": "unkn"}
    )
    assert inbox.propose(demote, "agent").status == "refused"


def test_a_broken_plugin_never_switches_its_bans_off(store, study, monkeypatch):
    import sys
    import types

    broken = types.ModuleType("qpilot.qpcr.design_checks")  # no hard_ban, no check_proposal
    monkeypatch.setitem(sys.modules, "qpilot.qpcr.design_checks", broken)
    with pytest.raises(ImportError):
        store.proposals(study)


def test_without_the_plugin_nothing_is_banned_and_nothing_is_consistent(store, study, monkeypatch):
    no_design_checks(monkeypatch)
    inbox = store.proposals(study)
    pid = inbox.propose(proposal(study_id=inbox.study_id), "agent").proposal.id
    check = inbox.get(pid).check
    assert (
        check.status == "cannot_check" and check.note == "engine check not available in this build"
    )
    assert inbox.bulk_accept([pid], "human")[0].status == "refused"
    assert SESSION_ID != inbox.study_id  # the fixture study is its own input
