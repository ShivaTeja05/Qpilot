"""Where to look and Decide… on the page (ported from the Gradio app's Trace accordion).

What the Gradio tests held holds over the API: tracing writes nothing; a place whose option
changes a call offers Decide…; Decide… opens one ``trace_set_aside`` card (writing no chain
entry), the same card again when asked twice; the card is decided on Results by a person with
a reason; an agent's request on it waits for a person; names from the file come back as text.
The engine at the analysis in use is checked against the Trace section in the demo tests.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from qpilot.core.decisions import apply_decision
from qpilot.web.context import make_context
from qpilot.web.routers import where as where_router
from qpilot.web.server import create_app
from tests.web.conftest import BASE, TOKEN

EVIL = '<img src=x onerror="alert(1)">'


@pytest.fixture
def toy(tmp_studies_dir, monkeypatch):
    """The Trace engine's toy study in a store, served; the context is the toy's own."""
    from tests.app.trace_toys import toy_store

    store, study_id, built, _ = toy_store(tmp_studies_dir, sample_name=EVIL)
    calls = []

    def fake_context(ctx, sid):
        calls.append(sid)
        return built

    monkeypatch.setattr(where_router, "_context", fake_context)
    ctx = make_context(store, token=TOKEN, watch=False)
    with TestClient(create_app(ctx), base_url=BASE) as c:
        c.headers["x-qpilot-token"] = TOKEN
        c.headers["origin"] = BASE
        yield {"client": c, "store": store, "study": study_id, "calls": calls}
    ctx.close()


def _files(store, study_id):
    folder = store.workspace(study_id)
    return {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}


def test_tracing_a_gene_writes_nothing_and_offers_decide_for_a_place_that_changes_a_call(toy):
    c, store, study = toy["client"], toy["store"], toy["study"]
    before = _files(store, study)
    r = c.get(f"/api/studies/{study}/where-to-look", params={"gene": "DOWN"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["root"] == {"kind": "gene", "id": "DOWN"} and body["answer"] == "place_to_look"
    (place,) = (p for p in body["places"] if p["can_decide"])
    assert place["rank"] == 1 and place["consequence"] == "changes_call"
    assert place["sample"] == EVIL  # a name from the file is a string; the page shows text
    assert place["card_id"].startswith("card_trace_") and place["card_status"] is None
    assert [ch["code"] for ch in place["checks"]] == ["S1"]
    assert any("DOWN" in o["changed_calls"] for o in place["options"])
    assert any(line["plain"].startswith("Where to look first") for line in body["text"])
    for line in body["text"]:  # every number in the panel is a cited fact
        for segment in line["segments"]:
            if segment["fact"] is None:
                assert not any(ch.isdigit() for ch in segment["text"].replace(EVIL, "")), segment
    assert _files(store, study) == before


@pytest.mark.parametrize(
    "params",
    [{}, {"gene": "DOWN", "sample": "s01"}, {"gene": "  "}, {"gene": "NOT_A_GENE"}],
)
def test_one_root_and_a_known_name(toy, params):
    c, study = toy["client"], toy["study"]
    r = c.get(f"/api/studies/{study}/where-to-look", params=params)
    assert r.status_code in (404, 422), r.text
    assert r.json()["error"]["message"]


def test_decide_opens_one_card_a_person_decides_on_results(toy):
    c, store, study = toy["client"], toy["store"], toy["study"]
    view = c.get(f"/api/studies/{study}/where-to-look", params={"gene": "DOWN"}).json()
    head = view["head"]
    body = {"kind": "gene", "id": "DOWN", "rank": 1, "expected_head": head}
    stale = c.post(
        f"/api/studies/{study}/where-to-look/open", json={**body, "expected_head": "0" * 64}
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale"
    r = c.post(f"/api/studies/{study}/where-to-look/open", json=body)
    assert r.status_code == 200, r.text
    opened = r.json()
    card_id = opened["card_id"]
    assert opened["opened"] is True and card_id == view["places"][0]["card_id"]
    assert store.chain_head(study) == head  # opening writes nothing to the decision chain
    again = c.post(f"/api/studies/{study}/where-to-look/open", json=body).json()
    assert again["opened"] is False and again["card_id"] == card_id
    assert [x.id for x in store.cards(study)].count(card_id) == 1
    cards = c.get(f"/api/studies/{study}/cards").json()["cards"]
    shown = next(x for x in cards if x["card"]["id"] == card_id)
    assert shown["title"] == "What to do with one unusual well" and shown["needs_human"]
    assert shown["place"]["sample"] == EVIL and shown["place"]["what_to_check"]
    assert "numbers stay as analysed" in shown["place"]["note"]
    traced = c.get(f"/api/studies/{study}/where-to-look", params={"gene": "DOWN"}).json()
    assert traced["places"][0]["card_status"] == "open"
    no_reason = c.post(
        f"/api/studies/{study}/cards/{card_id}/decide",
        json={"option": "set_aside", "reason": " ", "expected_head": head},
    )
    assert no_reason.status_code == 422
    r = c.post(
        f"/api/studies/{study}/cards/{card_id}/decide",
        json={
            "option": "set_aside",
            "reason": "The tube was mislabelled at extraction.",
            "expected_head": head,
        },
    )
    assert r.status_code == 200, r.text
    entry = store.entries(study)[-1]
    assert (entry.card_id, entry.option, entry.actor, entry.status) == (
        card_id,
        "set_aside",
        "human",
        "applied",
    )
    assert store.card(study, card_id).status == "decided"


def test_an_agent_cannot_decide_a_trace_card_that_changes_a_call(toy):
    c, store, study = toy["client"], toy["store"], toy["study"]
    head = c.get(f"/api/studies/{study}/where-to-look", params={"gene": "DOWN"}).json()["head"]
    body = {"kind": "gene", "id": "DOWN", "rank": 1, "expected_head": head}
    card_id = c.post(f"/api/studies/{study}/where-to-look/open", json=body).json()["card_id"]
    out = apply_decision(store, study, card_id, "set_aside", "agent says so", "agent", head)
    assert out.status == "pending_human"
    shown = next(
        x
        for x in c.get(f"/api/studies/{study}/cards").json()["cards"]
        if x["card"]["id"] == card_id
    )
    assert shown["pending"] and shown["pending"][0]["actor"] == "agent"
    r = c.post(
        f"/api/studies/{study}/cards/{card_id}/reject-request",
        json={
            "reason": "Not without looking at the curve.",
            "expected_head": store.chain_head(study),
        },
    )
    assert r.status_code == 200, r.text
    assert store.card(study, card_id).status == "open"


def test_a_place_that_changes_no_call_has_no_decide(toy):
    c, study = toy["client"], toy["study"]
    view = c.get(f"/api/studies/{study}/where-to-look", params={"gene": "FLAT"}).json()
    assert not any(p["can_decide"] for p in view["places"])
    for p in view["places"]:
        r = c.post(
            f"/api/studies/{study}/where-to-look/open",
            json={"kind": "gene", "id": "FLAT", "rank": p["rank"], "expected_head": view["head"]},
        )
        assert r.status_code == 422


def test_a_sample_and_a_well_are_traced_too(toy):
    c, study = toy["client"], toy["study"]
    sample = c.get(f"/api/studies/{study}/where-to-look", params={"sample": EVIL}).json()
    assert sample["root"]["kind"] == "sample"
    well = sample["places"][0]
    key = f"{well['plate']}:{well['well']}"
    traced = c.get(f"/api/studies/{study}/where-to-look", params={"well": key})
    assert traced.status_code == 200, traced.text
    assert traced.json()["root"]["kind"] == "well"
    bad = c.get(f"/api/studies/{study}/where-to-look", params={"well": "R1_20260101:XX99"})
    assert bad.status_code == 404
