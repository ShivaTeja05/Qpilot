"""POST /api/studies/{id}/ask: qPilot's Ask over the API, with no model (templates answer).

The study is the demo's analysed result as the engine produced it (``tests/fixtures``). Every
number an answer shows must be one of the facts it cites, with the engine's value.
"""

from __future__ import annotations

import pytest

from qpilot.ai.explain import KIND_TITLE
from qpilot.core.store import StudyStore
from qpilot.core.validator import render_tokens
from tests.web.conftest import wait_job

CAP = "Please switch to: Count empty wells as very low (cap)"
HMBS = "Apply HMBS alone as the control gene"


@pytest.fixture
def study(web_store: StudyStore, fixture_result, fixture_cards) -> str:
    web_store.put(fixture_result, fixture_cards)
    return fixture_result.study_id


@pytest.fixture
def no_model(web_ctx, monkeypatch):
    """No model is configured: templates answer (Studio builds its client on first use)."""
    monkeypatch.setenv("QPILOT_MODEL_PROVIDER", "none")
    assert web_ctx.studio.client.provider == "none"
    return web_ctx


def ask(client, key, question, **extra):
    r = client.post(f"/api/studies/{key}/ask", json={"question": question, **extra})
    assert r.status_code == 202, r.text
    job = r.json()["job"]
    assert job["kind"] == "ask" and job["typical_s"]
    done = wait_job(client, job)
    assert done["status"] == "done", done
    return done["result"]


def test_a_count_question_cites_the_engines_numbers(client, no_model, study, fixture_result):
    answer = ask(client, study, "How many samples and plates are in this study?")
    assert answer["engine"] == "study" and answer["tool"] == "qpcr_study"
    assert answer["written_by"] == "template" and answer["routed_by"] == "keywords"
    assert answer["validated"] is True and answer["model"] is None
    facts = {f["id"]: f for f in answer["facts"]}
    assert facts["f_ans_n_samples"]["value"] == str(fixture_result.n_samples)
    assert facts["f_ans_n_plates"]["value"] == str(fixture_result.n_plates)
    assert facts["f_ans_n_samples"]["meaning"] == "samples"
    for fact in answer["facts"]:
        assert fact["value"] in answer["answer"]
    assert "{{" not in answer["answer"]
    assert "template" in answer["writer_words"] and answer["note"]  # why no model answered


def test_a_gene_question_is_answered_from_the_robustness_grid(client, no_model, study, web_store):
    answer = ask(client, study, "Is ODC1 robust?")
    assert answer["tool"] == "qpcr_robustness" and answer["args"] == {"gene": "ODC1"}
    contrast = web_store.get(study).contrasts["ODC1"]
    facts = {f["id"]: f for f in answer["facts"]}
    from qpilot.schemas import Fact

    expected = Fact(id="x", value=contrast.fc, fmt="{:.2g}", unit="×")
    assert facts["f_ans_fc"]["value"] == render_tokens("{{x}}", {"x": expected})
    assert facts["f_ans_fc"]["meaning"].startswith("fold change")
    assert {"f_ans_holds", "f_ans_n_cells", "f_ans_level"} <= set(facts)
    assert answer["status"] is None and answer["head_after"] == answer["head_before"]


@pytest.mark.parametrize("autonomy", ["suggest", "decide_and_tell"])
def test_a_change_is_never_written_it_names_the_card(client, no_model, study, web_store, autonomy):
    # docs/app.md §1.1: every write from the page is a person's, so Ask never decides or asks
    web_store.set_autonomy(study, autonomy)
    before = (web_store.chain_head(study), web_store.cards(study), web_store.pending(study))
    for question, card_id in ((CAP, "card_undetermined"), (HMBS, "card_refset")):
        answer = ask(client, study, question)
        assert answer["tool"] == "qpcr_decide" and answer["status"] is None
        assert answer["card_id"] == card_id and answer["focus"] == f"card:{card_id}"
        title = KIND_TITLE[web_store.card(study, card_id).kind]
        assert answer["answer"].startswith("Ask never changes a choice.")
        assert f"“{title}”" in answer["answer"] and "Nothing was written" in answer["note"]
        assert answer["head_after"] == answer["head_before"] and answer["facts"] == []
        assert answer["autonomy"] == autonomy
    assert (web_store.chain_head(study), web_store.cards(study), web_store.pending(study)) == before
    assert client.get("/api/agents").json()["activity"] == []  # no agent entry either


def test_questions_are_checked(client, no_model, study):
    assert client.post(f"/api/studies/{study}/ask", json={"question": ""}).status_code == 422
    r = client.post(f"/api/studies/{study}/ask", json={"question": "x" * 501})
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_request"
    r = client.post(f"/api/studies/{study}/ask", json={"question": "   "})
    assert r.status_code == 422
    for key in ("0" * 12, "../etc", "ABCDEF123456"):
        r = client.post(f"/api/studies/{key}/ask", json={"question": "How many samples?"})
        assert r.status_code == 404, key


def test_the_audit_cannot_be_forced_without_an_audit(client, no_model, study):
    r = client.post(
        f"/api/studies/{study}/ask", json={"question": "Is ODC1 solid?", "source": "audit"}
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_audit"
    assert "Run it in Audit" in r.json()["error"]["message"]
    answer = ask(client, study, "Is ODC1 solid?")  # auto: no audit, so the study answers
    assert answer["engine"] == "study" and answer["tool"] == "qpcr_robustness"


def test_a_what_if_question_without_an_audit_says_to_run_it(client, no_model, study, web_store):
    head = web_store.chain_head(study)
    for question in (
        "What if I normalise to HMBS alone?",
        "What should I look at first?",
        "What is the verdict for ODC1?",
        "How many analyses did the audit run?",
    ):
        answer = ask(client, study, question)
        assert answer["engine"] == "none" and answer["tool"] == "none", question
        assert "Run it in Audit" in answer["answer"] and answer["facts"] == []
        assert answer["head_after"] == head
    assert web_store.pending(study) == []  # a what-if is never a request


def test_a_blind_session_cannot_be_asked(sclient, opened):
    r = sclient.post(f"/api/studies/{opened}/ask", json={"question": "Is anything up?"})
    assert r.status_code == 403
    error = r.json()["error"]
    assert error["code"] == "blind" and "confirmed" in error["message"]
    assert error["details"]["session"] == opened


def test_the_same_question_while_it_runs_is_one_job(client, no_model, web_ctx, study):
    import threading

    from qpilot.web.routers import ops

    release = threading.Event()
    real = ops._ask_study

    def slow(*args):
        release.wait(30)
        return real(*args)

    ops._ask_study = slow
    try:
        one = client.post(f"/api/studies/{study}/ask", json={"question": "How many samples?"})
        two = client.post(f"/api/studies/{study}/ask", json={"question": "how many  samples?"})
        assert one.json()["job"]["id"] == two.json()["job"]["id"]
    finally:
        release.set()
        ops._ask_study = real
    assert wait_job(client, one.json()["job"])["status"] == "done"


def test_two_questions_are_two_jobs(client, no_model, study):
    one = client.post(f"/api/studies/{study}/ask", json={"question": "How many samples?"})
    two = client.post(f"/api/studies/{study}/ask", json={"question": "How many plates?"})
    assert one.json()["job"]["id"] != two.json()["job"]["id"]
    for r in (one, two):
        assert wait_job(client, r.json()["job"])["status"] == "done"


def test_answers_carry_no_html(client, no_model, study):
    answer = ask(client, study, "<img src=x onerror=alert(1)> how many samples?")
    assert "<img" in answer["question"]  # text stays text; the page renders it as text
    assert "<" not in answer["answer"]
