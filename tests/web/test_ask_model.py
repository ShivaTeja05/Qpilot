"""The model's routes: the harness scorecard (POST /api/model/test), what the model saw, and the
fresh demo (POST /api/demo/fresh). No model is configured: the scorecard scores the templates.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from qpilot.ai import payload_log
from qpilot.ai.prompts import SYSTEM_INTERPRET
from qpilot.core.store import StudyStore
from tests.web.conftest import wait_job


@pytest.fixture
def study(web_store: StudyStore, fixture_result, fixture_cards) -> str:
    web_store.put(fixture_result, fixture_cards)
    return fixture_result.study_id


@pytest.fixture
def no_model(web_ctx, monkeypatch):
    monkeypatch.setenv("QPILOT_MODEL_PROVIDER", "none")
    assert web_ctx.studio.client.provider == "none"
    return web_ctx


@pytest.fixture(autouse=True)
def forget_payload():
    payload_log.clear()  # process-wide: other tests may have filled it
    yield
    payload_log.clear()


# ---- the model test --------------------------------------------------------------------------


def test_the_model_test_scores_templates_and_saves_the_scorecard(
    client, no_model, study, web_store
):
    r = client.post("/api/model/test", json={})
    assert r.status_code == 202, r.text
    job = r.json()["job"]
    assert job["kind"] == "model.test" and job["key"] == study and job["typical_s"]
    done = wait_job(client, job)
    assert done["status"] == "done", done
    result = done["result"]
    assert result["study_id"] == study and result["n_questions"] == 9
    row = result["current"]
    assert row["profile"] == "none" and row["provider"] == "none"
    assert row["n_items"] == 9 and 0 <= row["correct"] <= 9
    assert row["safety_held"] == row["safety_items"]  # the human-only rule held
    assert row["fallbacks"] is None and row["correct_by_model"] is None  # no model
    assert row["numbers_shown"] == 0
    saved = web_store.scorecard(study)
    assert saved["none"]["n_items"] == 9 and saved["none"]["correct"] == row["correct"]
    assert [r["profile"] for r in result["saved"]] == ["none"]
    assert "9 questions" in result["note"]


def test_the_model_test_on_a_named_study(client, no_model, study):
    r = client.post("/api/model/test", json={"study": study})
    assert r.status_code == 202
    assert wait_job(client, r.json()["job"])["status"] == "done"


def test_the_model_test_needs_an_analysed_study(client, no_model):
    r = client.post("/api/model/test", json={})
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_study"
    r = client.post("/api/model/test", json={"study": "0" * 12})
    assert r.status_code == 404


def test_the_model_test_refuses_a_blind_session(sclient, opened):
    r = sclient.post("/api/model/test", json={"study": opened})
    assert r.status_code == 403 and r.json()["error"]["code"] == "blind"
    r = sclient.post("/api/model/test", json={})  # the only session is blind: nothing to test on
    assert r.status_code == 409


def test_saved_scorecards_are_read_without_running_a_test(client, no_model, study):
    before = client.get("/api/model/scorecards").json()
    assert before["study_id"] == study and before["current"] is None and before["saved"] == []
    assert "not been tested" in before["note"] and before["n_questions"] == 0
    done = wait_job(client, client.post("/api/model/test", json={}).json()["job"])
    after = client.get(f"/api/model/scorecards?study={study}").json()
    assert after["current"] == done["result"]["current"]
    assert [r["profile"] for r in after["saved"]] == ["none"] and after["n_questions"] == 9
    assert "last test of this model" in after["note"]


def test_scorecards_need_a_visible_study(client, no_model, sclient, opened):
    assert client.get("/api/model/scorecards").json()["error"]["code"] == "no_study"
    r = sclient.get(f"/api/model/scorecards?study={opened}")
    assert r.status_code == 403 and r.json()["error"]["code"] == "blind"


# ---- what the model saw ----------------------------------------------------------------------

RESULTS_PAYLOAD = {"provider": "none", "system": "You explain", "messages": [{"content": "3.6"}]}


def test_nothing_was_sent_yet(client):
    seen = client.get("/api/model/seen").json()
    assert seen["state"] == "none" and seen["payload_text"] is None


def test_the_last_payload_is_shown_when_nothing_is_blind(client, study):
    payload_log.record_payload(RESULTS_PAYLOAD)
    seen = client.get("/api/model/seen").json()
    assert seen["state"] == "shown" and "You explain" in seen["payload_text"]
    assert seen["sha256"] and seen["interpreter"] is False
    assert client.get(f"/api/model/seen?study={study}").json()["state"] == "shown"


def test_a_payload_that_may_hold_results_is_hidden_while_a_session_is_blind(sclient, opened):
    payload_log.record_payload(RESULTS_PAYLOAD)
    for url in ("/api/model/seen", f"/api/model/seen?study={opened}"):
        seen = sclient.get(url).json()
        assert seen["state"] == "hidden" and seen["payload_text"] is None, url
    payload_log.record_payload({"provider": "none", "system": SYSTEM_INTERPRET, "messages": []})
    seen = sclient.get(f"/api/model/seen?study={opened}").json()
    assert seen["state"] == "shown" and seen["interpreter"] is True  # holds no result


def test_seen_checks_the_id(client):
    assert client.get("/api/model/seen?study=0123456789ab").status_code == 404
    assert client.get("/api/model/seen?study=../etc").status_code in (404, 422)


# ---- the fresh demo --------------------------------------------------------------------------


def test_a_fresh_demo_moves_the_demo_aside_and_keeps_it(client, web_store, study):
    workspace = web_store.workspace(study)
    files = sorted(p.name for p in workspace.iterdir())
    r = client.post("/api/demo/fresh")
    assert r.status_code == 200, r.text
    body = r.json()
    assert web_store.list_studies() == []
    (moved,) = body["moved"]
    kept = Path(moved)
    assert kept.is_dir() and sorted(p.name for p in kept.iterdir()) == files  # never deleted
    assert kept.parent == Path(body["archive"])
    assert kept.parent.parent == web_store.root.parent / "studies-archive"
    assert "never deleted" in body["message"]
    again = client.post("/api/demo/fresh").json()
    assert again["moved"] == [] and "no earlier demo work" in again["message"]


def test_a_fresh_demo_waits_for_running_demo_work(client, web_ctx, study):
    release = threading.Event()
    web_ctx.jobs.submit("audit", lambda progress: release.wait(30), title="busy", key=study)
    try:
        r = client.post("/api/demo/fresh")
        assert r.status_code == 409 and r.json()["error"]["code"] == "busy"
        assert web_ctx.store.list_studies() == [study]
    finally:
        release.set()


def test_other_studies_are_not_moved(client, web_store, study, fixture_result, fixture_cards):
    # the same results filed under another input file: not the demo, so it stays
    other = fixture_result.model_copy(update={"study_id": "f" * 12, "input_sha256": "f" * 64})
    web_store.put(other, fixture_cards)
    client.post("/api/demo/fresh")
    assert web_store.list_studies() == ["f" * 12]
