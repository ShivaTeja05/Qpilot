"""Trace routes over a study walked through Studio (the synthetic mini file, 2 vs 2 samples).

The first trace loads the study's model in a job (409 ``loading`` with the job), then the
routes answer; a person's decision changes the analysis traced (the call Results shows); names
that are not results say why; and the routes are blind like every result until the session's
design and curves are confirmed again.
"""

from __future__ import annotations

import pytest

from qpilot.mcp_server import QpilotTools
from qpilot.web.routers import trace as trace_router
from tests.web.conftest import get_settled, wait_job
from tests.web.test_studio_flow import no_html

GENE = "1-Mar"


@pytest.fixture(autouse=True)
def fresh_trace_cache():
    trace_router.clear()
    yield
    trace_router.clear()


def ready(c, url: str):
    """GET ``url``, following every ``trace.load`` job an answer names until it answers."""
    jobs: list[dict] = []
    r = get_settled(c, url, jobs=jobs)
    # a load that failed is answered by the route's own refusal (not_traceable…), returned
    for job in (j for j in jobs if j["status"] == "done"):
        assert job["result"]["n_genes"] >= 1 and job["result_type"] == "TraceLoaded"
    return r


def test_a_cold_trace_answers_loading_with_the_job(walked, monkeypatch):
    c, study = walked["client"], walked["study"]
    monkeypatch.setattr(trace_router, "WAIT_S", 0.0)
    r = c.get(f"/api/studies/{study}/trace/{GENE}")
    assert r.status_code == 409, r.text
    error = r.json()["error"]
    assert error["code"] == "loading" and error["details"]["job"]["kind"] == "trace.load"
    assert "wells" in error["message"]
    job = wait_job(c, error["details"]["job"])
    assert job["status"] == "done" and job["result"]["study_id"] == study
    assert c.get(f"/api/studies/{study}/trace/{GENE}").status_code == 200


def test_one_gene_traced_down_to_its_wells(walked):
    c, study, store = walked["client"], walked["study"], walked["store"]
    r = ready(c, f"/api/studies/{study}/trace/{GENE}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["study_id"] == study and body["session"] == walked["sid"]
    assert body["head"] == store.chain_head(study)
    trace = body["trace"]
    results = c.get(f"/api/studies/{study}/results").json()
    row = next(g for g in results["genes"] if g["gene"] == GENE)
    assert trace["call"]["conclusion"] == row["conclusion"]
    assert trace["call"]["log2fc"] == pytest.approx(row["log2fc"], abs=1e-9)
    assert trace["n_used"] == len(trace["samples"]) == row["n_hi"] + row["n_lo"]
    assert {s["group"] for s in trace["samples"]} == set(trace["labels"])
    assert [r["gene"] for r in trace["references"]] == results["references"]["used"]
    for sample in trace["samples"]:  # 2 vs 2: setting any one aside leaves no p-value
        assert sample["call_without"] == "none" and sample["p_without"] is None
        assert sample["wells"] and {w["gene"] for w in sample["wells"]} >= {GENE}
        assert all(w["key"] == f"{w['plate']}/{w['well']}" for w in sample["wells"])
    assert trace["look_first"]["kind"] in ("place", "influential", "none")
    texts = body["texts"]
    assert {"summary", "flip", "look_first"} <= set(texts)
    for text in texts.values():
        assert "".join(s["text"] for s in text["segments"]) == text["plain"]
        assert all(f["id"].startswith("f_trace_") for f in text["facts"])
    assert "control genes" in " ".join(trace["checked"])  # one control gene: S1 cannot run
    no_html(body)


def test_the_study_overview(walked):
    c, study = walked["client"], walked["study"]
    r = ready(c, f"/api/studies/{study}/trace")
    assert r.status_code == 200, r.text
    body = r.json()
    trace = body["trace"]
    assert [g["gene"] for g in trace["genes"]] == [GENE] and trace["genes"][0]["rank"] == 1
    assert trace["n_genes"] == 1 and trace["n_compared"] <= trace["n_units"]
    assert body["texts"]["summary"]["plain"].startswith("Of 1 compared genes")
    no_html(body)


def test_what_if_a_sample_is_set_aside(walked):
    c, study = walked["client"], walked["study"]
    trace = ready(c, f"/api/studies/{study}/trace/{GENE}").json()["trace"]
    unit = trace["samples"][0]["unit"]
    url = f"/api/studies/{study}/trace/{GENE}/without"
    r = c.post(url, json={"samples": [unit]})
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert (
        result["units"] == [unit] and result["before"]["conclusion"] == trace["call"]["conclusion"]
    )
    assert result["after"]["n_a"] + result["after"]["n_b"] == trace["n_used"] - 1
    assert result["after"]["log2fc"] == pytest.approx(trace["samples"][0]["log2fc_without"])
    for body, words in (({}, "Name each sample"), ({"samples": ["nobody"]}, "no sample")):
        r = c.post(url, json=body)
        assert r.status_code == 422 and words in r.json()["error"]["message"], r.text
    r = c.post(f"/api/studies/{study}/trace/GAPDH/without", json={"samples": [unit]})
    assert r.status_code == 404


def test_names_that_are_not_results(walked):
    c, study = walked["client"], walked["study"]
    ready(c, f"/api/studies/{study}/trace")
    r = c.get(f"/api/studies/{study}/trace/GAPDH")
    assert r.status_code == 404 and "control gene" in r.json()["error"]["message"]
    assert c.get(f"/api/studies/{study}/trace/NOPE").status_code == 404
    assert c.get(f"/api/studies/{study}/trace/{'x' * 200}").status_code == 404
    assert c.get("/api/studies/0123456789ab/trace").status_code == 404
    assert c.get("/api/studies/not-a-key/trace/x").status_code == 404


def test_a_persons_decision_changes_what_is_traced(walked):
    c, study = walked["client"], walked["study"]
    before = ready(c, f"/api/studies/{study}/trace/{GENE}").json()
    assert before["trace"]["cell"]["planned"] and before["trace"]["cell"]["undetermined"] == "drop"
    cards = c.get(f"/api/studies/{study}/cards").json()
    r = c.post(
        f"/api/studies/{study}/cards/card_undetermined/decide",
        json={
            "option": "cap",
            "reason": "our lab caps empty wells",
            "expected_head": cards["head"],
        },
    )
    assert r.status_code == 200, r.text
    after = ready(c, f"/api/studies/{study}/trace/{GENE}").json()
    assert after["head"] != before["head"]
    row = next(
        g for g in c.get(f"/api/studies/{study}/results").json()["genes"] if g["gene"] == GENE
    )
    shown = row["at_your_choices"]  # the choice moved the grid cell: it is traced there
    assert shown is not None
    cell = after["trace"]["cell"]
    assert not cell["planned"] and cell["undetermined"] == "cap"
    assert after["trace"]["call"]["log2fc"] == pytest.approx(shown["log2fc"], abs=1e-8)
    assert after["trace"]["call"]["conclusion"] == shown["conclusion"]


def test_trace_is_blind_until_the_session_is_confirmed_again(walked):
    c, study, sid, store, studio = (
        walked["client"], walked["study"], walked["sid"], walked["store"], walked["studio"]
    )  # fmt: skip
    assert ready(c, f"/api/studies/{study}/trace/{GENE}").status_code == 200
    QpilotTools(store).qpcr_propose(sid, "design.group", "WT_1", {"group": "KO"})
    change = next(p for p in studio.inbox(sid, "design", "proposed") if p.kind == "design.group")
    studio.accept(sid, change.id, "human", "the lab book says KO")
    assert not studio.results_visible(sid)
    for method, url, body in (
        ("GET", f"/api/studies/{study}/trace", None),
        ("GET", f"/api/studies/{study}/trace/{GENE}", None),
        ("POST", f"/api/studies/{study}/trace/{GENE}/without", {"samples": ["WT_1"]}),
        ("POST", f"/api/studies/{study}/trace/{GENE}/without", {}),
        ("GET", f"/api/studies/{study}/trace/plate", None),
    ):
        r = c.request(method, url, json=body)
        assert r.status_code == 403 and r.json()["error"]["code"] == "blind", (url, r.text)
        assert "log2fc" not in r.text and "samples" not in r.json()["error"]["details"]


def test_a_plate_as_trace_reads_it(walked):
    c, study = walked["client"], walked["study"]
    trace = ready(c, f"/api/studies/{study}/trace/{GENE}").json()["trace"]
    well = trace["samples"][0]["wells"][0]
    r = c.get(f"/api/studies/{study}/trace/plate", params={"run": well["plate"]})
    assert r.status_code == 200, r.text
    plate = r.json()["plate"]
    assert plate["run"] == well["plate"] and well["gene"] in plate["genes"]
    listed = {w["key"]: w for w in plate["wells"]}
    assert listed[well["key"]] == well
    assert {w["sample_type"] for w in plate["wells"]} >= {"unkn"}
    r = c.get(f"/api/studies/{study}/trace/plate", params={"run": "no such plate"})
    assert r.status_code == 404
    assert c.get(f"/api/studies/{study}/trace/plate").status_code == 422
