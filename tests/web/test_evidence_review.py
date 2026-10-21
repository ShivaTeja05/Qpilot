"""The Evidence Ledger and the Run Review on the page (ported from the Gradio app's panels).

What the Gradio tests held (tests/app on origin/main, 18 Oct) holds here over the API: the
ledger's every number is a fact; an unknown status shows as unknown; a sign-off is one ``review``
entry, always a person's, with an outcome, a comment and a name; a decision since the review
was read makes the sign-off stale (and is shown again); a sign-off never makes a decision
stale; the record still verifies; and every GET writes nothing.
"""

from __future__ import annotations

import re

import pytest

from qpilot.core.store import StudyStore
from qpilot.schemas import Fact
from qpilot.web.routers import evidence as evidence_router

EVIL = '<img src=x onerror="alert(1)">'


@pytest.fixture(autouse=True)
def _fresh():
    evidence_router.clear()
    yield
    evidence_router.clear()


def _toy_ledger(study_id):
    from qpilot.qpcr.evidence import evidence_for
    from tests.engine.evidence_toys import toy_design, toy_model, toy_table

    table, design = toy_table(), toy_design()
    ledger = evidence_for(table, toy_model(table, design), design)
    return ledger.model_copy(update={"study_id": study_id})


def _state(store: StudyStore, study_id: str) -> dict[str, bytes]:
    folder = store.workspace(study_id)
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir()) if p.is_file()}


def _numbers_are_facts(text: dict) -> None:
    """Every digit of a FactText sits in a cited fact (names from the study aside)."""
    for segment in text["segments"]:
        if segment["fact"] is None:
            assert not re.search(r"\d", segment["text"]), segment


# ---- the Evidence Ledger --------------------------------------------------------------------


def test_the_ledger_kept_at_analysis_is_shown_and_every_number_is_a_fact(walked):
    c, store, study = walked["client"], walked["store"], walked["study"]
    store.put_artifact(study, "evidence.json", _toy_ledger(study).model_dump(mode="json"))
    before = _state(store, study)
    body = c.get(f"/api/studies/{study}/evidence").json()
    assert body["available"] is True and body["source"] == "kept"
    assert [i["id"] for i in body["items"]] == [i.id for i in _toy_ledger(study).items]
    statuses = {i["status"] for i in body["items"]}
    assert {"present", "absent"} <= statuses
    for item in body["items"]:
        _numbers_are_facts(item["line"])
        assert item["cannot_tell"] is (item["status"] in ("absent", "unknown"))
    _numbers_are_facts(body["summary"])
    assert any(f["id"] == "f_ev_n_present" for f in body["summary"]["facts"])
    assert sum(body["counts"].values()) == len(body["items"])
    assert "never change a conclusion" in body["rule"]
    assert _state(store, study) == before  # a GET writes nothing


def test_an_unknown_status_or_a_naked_number_is_never_shown(walked):
    c, store, study = walked["client"], walked["store"], walked["study"]
    ledger = _toy_ledger(study)
    items = list(ledger.items)
    items[1] = items[1].model_copy(
        update={"consequence": items[1].consequence.model_copy(update={"text": "42 wells"})}
    )
    facts = {**ledger.facts, "f_ev_n_present": Fact(id="f_ev_n_present", value=EVIL)}
    bad = ledger.model_copy(update={"items": items, "facts": facts})
    store.put_artifact(study, "evidence.json", bad.model_dump(mode="json"))
    body = c.get(f"/api/studies/{study}/evidence").json()
    text = str(body)
    assert "42 wells" not in text
    for item in body["items"]:
        _numbers_are_facts(item["line"])
    # a markup value stays a string value of a fact: the page renders it as text
    assert any(f["value"] == EVIL for f in body["summary"]["facts"])


def test_without_its_input_file_the_ledger_says_why_and_nothing_is_written(walked, monkeypatch):
    c, store, study = walked["client"], walked["store"], walked["study"]
    monkeypatch.setattr(store, "source", lambda _sid: None)  # moved or changed since
    (store.workspace(study) / "evidence.json").unlink(missing_ok=True)
    before = _state(store, study)
    body = c.get(f"/api/studies/{study}/evidence").json()
    assert body["available"] is False and body["source"] == "none"
    assert body["note"].startswith("The Evidence Ledger is not available for this study.")
    assert body["items"] == []
    assert _state(store, study) == before


# ---- the Run Review -------------------------------------------------------------------------


def test_the_review_shows_the_ledger_headline_and_no_sign_off_yet(walked):
    c, store, study = walked["client"], walked["store"], walked["study"]
    body = c.get(f"/api/studies/{study}/review").json()
    assert body["head"] == store.chain_head(study)
    assert body["sign_offs"] == [] and body["can_sign_off"] is True
    assert [o["id"] for o in body["outcomes"]] == ["accept", "repeat", "discuss"]
    assert "a person signs off" in body["purpose"]
    _numbers_are_facts(body["title"])
    for gene in body["headline"]:
        _numbers_are_facts(gene["line"])
    assert {n["id"] for n in body["not_built"]} >= {"gate", "next_run"}
    assert {n["section"] for n in body["not_built"] if n["section"]} == {"gate", "planner"}


def test_a_sign_off_writes_one_review_entry_always_as_a_person(walked, tmp_path):
    from qpilot.core.record import verify, write_record

    c, store, study = walked["client"], walked["store"], walked["study"]
    head = c.get(f"/api/studies/{study}/review").json()["head"]
    before = len(store.entries(study))
    r = c.post(
        f"/api/studies/{study}/review/sign-off",
        json={
            "outcome": "accept",
            "comment": "Looked at the controls.",
            "reviewer": EVIL,
            "expected_head": head,
            "actor": "agent",  # not a field: the server records a person whatever is sent
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["message"].startswith("Signed off (accept).")
    (entry,) = store.reviews(study)
    assert (entry.kind, entry.outcome, entry.actor, entry.reviewer) == (
        "review",
        "accept",
        "human",
        EVIL,
    )
    assert len(store.entries(study)) == before + 1 and store.chain_head(study) == entry.hash
    assert body["head"] == entry.hash and body["review"]["head"] == entry.hash
    shown = body["sign_off"]
    assert shown["reviewer"] == EVIL and shown["comment"] == "Looked at the controls."
    _numbers_are_facts(shown["line"])
    info = write_record(store, study, tmp_path / "rec")
    assert verify(info.record_dir).ok


@pytest.mark.parametrize(
    ("change", "status"),
    [
        ({"comment": "   "}, 422),
        ({"reviewer": "  "}, 422),
        ({"outcome": "approve"}, 422),
        ({"comment": "x" * 2001}, 422),
        ({"expected_head": ""}, 422),
    ],
)
def test_a_sign_off_needs_an_outcome_a_comment_and_a_name(walked, change, status):
    c, store, study = walked["client"], walked["store"], walked["study"]
    body = {
        "outcome": "repeat",
        "comment": "Plate 2 again.",
        "reviewer": "A. Person",
        "expected_head": store.chain_head(study),
        **change,
    }
    assert c.post(f"/api/studies/{study}/review/sign-off", json=body).status_code == status
    assert store.reviews(study) == []


def test_a_decision_since_the_review_was_read_makes_the_sign_off_stale(walked):
    from qpilot.core.decisions import apply_decision

    c, store, study = walked["client"], walked["store"], walked["study"]
    read = c.get(f"/api/studies/{study}/review").json()["head"]
    card = next(x for x in store.cards(study) if len(x.options) > 1)
    other = next(o.id for o in card.options if o.id != card.decision)
    apply_decision(store, study, card.id, other, "other tab", "human", store.chain_head(study))
    body = {"outcome": "discuss", "comment": "Talk.", "reviewer": "B", "expected_head": read}
    r = c.post(f"/api/studies/{study}/review/sign-off", json=body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale"
    assert r.json()["error"]["details"]["head"] == store.chain_head(study)
    assert store.reviews(study) == []
    body["expected_head"] = c.get(f"/api/studies/{study}/review").json()["head"]
    assert c.post(f"/api/studies/{study}/review/sign-off", json=body).status_code == 200


def test_a_sign_off_never_makes_a_decision_stale(walked):
    c, store, study = walked["client"], walked["store"], walked["study"]
    head = store.chain_head(study)
    body = {"outcome": "accept", "comment": "Fine.", "reviewer": "C", "expected_head": head}
    assert c.post(f"/api/studies/{study}/review/sign-off", json=body).status_code == 200
    card = next(x for x in store.cards(study) if len(x.options) > 1)
    other = next(o.id for o in card.options if o.id != card.decision)
    r = c.post(
        f"/api/studies/{study}/cards/{card.id}/decide",
        json={"option": other, "reason": "read before the sign-off", "expected_head": head},
    )
    assert r.status_code == 200, r.text
    assert r.json()["outcome"]["status"] == "applied"


def test_only_the_sign_off_route_writes_a_review():
    from pathlib import Path

    web = Path(__file__).resolve().parents[2] / "qpilot" / "web"
    found = [p for p in web.rglob("*.py") if ".append_review(" in p.read_text()]
    assert [p.name for p in found] == ["evidence.py"]
    assert 'actor="human"' in (web / "routers" / "evidence.py").read_text()


def test_an_imports_rawness_verdict_reaches_the_ledger(walked, monkeypatch):
    """Open's raw-ness check of an instrument export (qpilot.io.rawness) fills the ledger's item."""
    c, study = walked["client"], walked["study"]
    verdict = {
        "study_verdict": "baseline_subtracted",
        "plate_verdicts": {"p1": "baseline_subtracted"},
    }
    monkeypatch.setattr(evidence_router, "import_rawness", lambda _ctx, _sid: verdict)
    body = c.get(f"/api/studies/{study}/evidence").json()
    item = next(i for i in body["items"] if i["id"] == "rawness")
    assert item["status"] == "absent" and item["value"] == "baseline_subtracted"
    assert item["line"]["plain"].startswith("Raw-ness of the curves: absent.")
    assert "Re-export the raw fluorescence" in item["line"]["plain"]
    _numbers_are_facts(item["line"])


def test_a_sign_off_reads_as_a_sign_off_in_the_record_and_history(walked):
    c, store, study = walked["client"], walked["store"], walked["study"]
    body = {"outcome": "discuss", "comment": "Plate two.", "reviewer": "D", "expected_head": ""}
    body["expected_head"] = store.chain_head(study)
    assert c.post(f"/api/studies/{study}/review/sign-off", json=body).status_code == 200
    last = c.get(f"/api/studies/{study}/decisions").json()["entries"][-1]
    assert (last["card_title"], last["option_label"]) == ("Run Review sign-off", "Discuss")
    step = c.get(f"/api/studies/{study}/history").json()["steps"][-1]
    assert (step["card_title"], step["option_label"]) == ("Run Review sign-off", "Discuss")
    assert "signed off the run review" in step["effect"]
