"""The old results page's decision rules, checked on the one server (tests/web/PARITY.md §1).

Ported from ``tests/app/test_app.py``: a write that carries an old head changes nothing and says
so (decide, undo, turn down), the page's own question never makes its next decision stale, text
a person types comes back as data, and a study's routes read without writing and, once its
session is blind again, show and do nothing. The sweeps enumerate the server's routes, so the
audit, Prism and record routes are checked as they land.
"""

from __future__ import annotations

import pytest

from qpilot.mcp_server import QpilotTools
from tests.web.conftest import wait_job
from tests.web.test_ask import CAP
from tests.web.test_parity_studio import HOSTILE, call_all, decision_files, reveals

CARD = "card_undetermined"


def study_values(client, study: str) -> dict[str, list]:
    """Plausible values for each parameter of a study's routes, read from the study itself."""
    results = client.get(f"/api/studies/{study}/results")
    genes = [g["gene"] for g in results.json().get("genes", [])] if results.is_success else []
    cards = client.get(f"/api/studies/{study}/cards")
    ids = [c["card"]["id"] for c in cards.json().get("cards", [])] if cards.is_success else []
    return {
        "study_id": [study],
        "gene": genes[:2] or ["ODC1"],
        "card_id": ids[:2] or [CARD],
        "name": ["summary.json"],
        "stage": ["design", "curves"],
    }


def head(walked) -> str:
    return walked["store"].chain_head(walked["study"])


def post(client, study: str, card: str, action: str, **body):
    return client.post(f"/api/studies/{study}/cards/{card}/{action}", json=body)


# ---- stale heads (P6) ------------------------------------------------------------------------


def test_undo_and_turn_down_with_an_old_head_write_nothing(walked):
    """A person's decision in another tab makes this tab's undo stale; a request that arrived
    after this tab looked makes its turn-down stale. An agent's request never blocks a person."""
    c, study, store = walked["client"], walked["study"], walked["store"]
    agent = QpilotTools(store)
    r = post(c, study, CARD, "decide", option="cap", reason="we cap", expected_head=head(walked))
    assert r.status_code == 200, r.text
    seen = r.json()["head"]

    # an agent's request since this tab looked does not keep a person from acting
    agent.qpcr_decide(study, CARD, "drop", "the agent prefers drop")
    assert store.pending(study) and head(walked) != seen
    r = post(c, study, CARD, "reject-request", reason="we cap", expected_head=head(walked))
    assert r.status_code == 200 and r.json()["outcome"]["status"] == "rejected"

    # another tab: a person decides; this tab's Undo (on its old head) is stale, writes nothing
    other = head(walked)
    r = post(c, study, CARD, "decide", option="drop", reason="tab two", expected_head=other)
    assert r.status_code == 200, r.text
    moved = head(walked)
    r = post(c, study, CARD, "undo", reason="a slip", expected_head=other)
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale"
    assert r.json()["error"]["details"]["head"] == moved
    assert head(walked) == moved and store.card(study, CARD).decision == "drop"

    # a new request after this tab looked: turning down what it has not seen is stale
    agent.qpcr_decide(study, CARD, "cap", "the agent asks again")
    looked = head(walked)
    agent.qpcr_decide(study, CARD, "cap", "and once more, with a new reason")
    assert head(walked) != looked, "the store logged the second request"
    r = post(c, study, CARD, "reject-request", reason="no", expected_head=looked)
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale"
    r = post(c, study, CARD, "reject-request", reason="we drop them", expected_head=head(walked))
    assert r.status_code == 200 and not store.pending(study)


# ---- the page's Ask never writes; a person decides next (P10, P26, RT-UI-017) -----------------


@pytest.mark.xfail(
    strict=True,
    reason="RT-UI-017 (api-ops): the page's Ask must never write (coordinator #0233); today it "
    "files a request in Suggest mode and applies in Decide and tell me",
)
@pytest.mark.parametrize("autonomy", ["suggest", "decide_and_tell"])
def test_ask_never_writes_and_leads_to_the_card(walked, autonomy):
    c, study, store = walked["client"], walked["study"], walked["store"]
    assert c.put("/api/settings", json={"autonomy": autonomy}).status_code == 200
    before = c.get(f"/api/studies/{study}/cards").json()["head"]
    files = decision_files(store)
    r = c.post(f"/api/studies/{study}/ask", json={"question": CAP})
    assert r.status_code == 202, r.text
    answer = wait_job(c, r.json()["job"])["result"]
    assert decision_files(store) == files and store.chain_head(study) == before, "Ask wrote"
    assert not store.pending(study) and store.card(study, CARD).decision == "drop"
    assert answer["focus"] == f"card:{CARD}", "the answer leads the person to the card"

    # the person decides on the card, with the head the page already had: not stale
    r = post(c, study, CARD, "decide", option="cap", reason="yes, cap them", expected_head=before)
    assert r.status_code == 200 and r.json()["outcome"]["status"] == "applied"
    assert store.entries(study)[-1].actor == "human"


# ---- text a person types comes back as data (P12) --------------------------------------------


def test_a_reason_with_markup_comes_back_as_data(walked):
    c, study, store = walked["client"], walked["study"], walked["store"]
    reason = f"caps {HOSTILE} & <b>bold</b>"
    r = post(c, study, CARD, "decide", option="cap", reason=reason, expected_head=head(walked))
    assert r.status_code == 200, r.text
    assert store.entries(study)[-1].reason == reason, "stored exactly as typed"
    chain = c.get(f"/api/studies/{study}/decisions")
    assert chain.headers["content-type"].startswith("application/json")
    assert chain.headers["x-content-type-options"] == "nosniff"
    assert chain.json()["entries"][-1]["entry"]["reason"] == reason, "served exactly as typed"


# ---- reading writes nothing; blind again means nothing (P2, P3) ------------------------------


def test_every_study_get_route_writes_nothing(walked):
    c, study, store = walked["client"], walked["study"], walked["store"]
    values = study_values(c, study)
    before = decision_files(store)
    assert any(name.endswith("decisions.jsonl") for name in before)
    calls = list(call_all(c, "/api/studies/{study_id}", values))
    assert len(calls) >= 8
    assert all(r.status_code < 500 for _, r in calls), [u for u, r in calls if r.status_code >= 500]
    assert decision_files(store) == before, "a GET wrote a decision"
    assert any(reveals(r.json()) for _, r in calls if r.status_code == 200), "results are shown"


def test_a_study_blind_again_shows_and_does_nothing(walked):
    c, study, store, studio, sid = (
        walked["client"], walked["study"], walked["store"], walked["studio"], walked["sid"],
    )  # fmt: skip
    values = study_values(c, study)  # read while the results are visible
    QpilotTools(store).qpcr_propose(sid, "design.group", "WT_2", {"group": "KO"})
    (change,) = (p for p in studio.inbox(sid, "design", "proposed") if p.subject == "WT_2")
    studio.accept(sid, change.id, "human", "checked: WT_2 is a knock-out")
    assert not studio.results_visible(sid)
    before = decision_files(store)

    shown = []
    for url, r in call_all(c, "/api/studies/{study_id}", values):
        if r.status_code == 200 and reveals(r.json()):
            shown.append(url)
        if r.status_code == 403:
            assert r.json()["error"]["code"] == "blind", url
    assert not shown, f"results served while blind: {shown}"

    body = {
        "option": "cap", "reason": "x", "expected_head": head(walked), "question": "Is ODC1 up?",
        "changes": {}, "gene": values["gene"][0],
    }  # fmt: skip
    for url, r in call_all(c, "/api/studies/{study_id}", values, method="post", body=body):
        assert not r.is_success, f"{url} answered {r.status_code} while blind"
    assert decision_files(store) == before, "nothing is written while blind"


# ---- every model call is logged with the study (A15a) ----------------------------------------


def test_each_explanation_is_logged_with_the_study(walked):
    from fastapi.testclient import TestClient

    from qpilot.ai.client import MockBackend, ModelClient
    from qpilot.studio_service import Studio
    from qpilot.web.context import make_context
    from qpilot.web.server import create_app
    from tests.web.conftest import BASE, TOKEN

    store, study = walked["store"], walked["study"]
    model = ModelClient(MockBackend(lambda _system, _messages: "Empty wells are handled here."))
    ctx = make_context(store, Studio(store, client=model), token=TOKEN, watch=False)
    before = len(store.ai_calls(study))
    try:
        with TestClient(create_app(ctx), base_url=BASE) as c:
            c.headers.update({"x-qpilot-token": TOKEN, "origin": BASE})
            r = c.post(f"/api/studies/{study}/cards/{CARD}/explain")
            assert r.status_code == 202, r.text
            job = wait_job(c, r.json()["job"])
    finally:
        ctx.close()
    assert job["status"] == "done", job
    explained = job["result"]
    assert explained["card_id"] == CARD and (explained["fallback"] or explained["validated"])
    calls = store.ai_calls(study)
    assert len(calls) == before + 1, "the record carries every model call"
