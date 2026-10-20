"""The demo's Studio walk over HTTP: ``qpilot studio demo --check`` through the page's routes.

The same scripted person and the same numbers as ``qpilot/cli/studio_cmds.py:_walk`` (rules
only, no model), as far as the choices stage; Prism and the round trip are the Prism routes'.
"""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from qpilot.cli.studio_cmds import EXPECTED, REASONS
from qpilot.web.context import make_context
from qpilot.web.server import create_app
from tests.web.conftest import BASE, TOKEN, wait_job

pytestmark = pytest.mark.demo_data


@pytest.fixture
def demo_client(web_store):
    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.studio_service import Studio

    studio = Studio(web_store, client=ModelClient(backend=NoneBackend()))
    ctx = make_context(web_store, studio, token=TOKEN, watch=False)
    with TestClient(create_app(ctx), base_url=BASE) as c:
        c.headers["x-qpilot-token"] = TOKEN
        c.headers["origin"] = BASE
        yield c
    ctx.close()


def _job(c, response):
    assert response.status_code == 202, response.text
    job = wait_job(c, response.json()["job"], timeout=1200)
    assert job["status"] == "done", job
    return job["result"]


def _pending(c, sid, stage):
    body = c.get(f"/api/sessions/{sid}/proposals", params={"stage": stage}).json()
    return [p for p in body["proposals"] if p["status"] == "proposed"], body["head"]


def _head(c, sid):
    return c.get(f"/api/sessions/{sid}/proposals").json()["head"]


def _confirm(c, sid, stage):
    view = c.post(f"/api/sessions/{sid}/confirm/{stage}").json()
    assert view["ready"], view
    r = c.post(
        f"/api/sessions/{sid}/confirm/{stage}/accept",
        json={"proposal_id": view["proposal"]["id"], "expected_head": view["head"]},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_the_demo_walk_over_http(demo_client):  # noqa: PLR0915
    c, e = demo_client, EXPECTED
    sid = _job(c, c.post("/api/workspaces/demo"))["key"]
    frame = c.get(f"/api/sessions/{sid}").json()
    assert frame["is_demo"] and frame["facts"]["n_samples"] == e["samples"]

    # ---- 1. design (blind) ----
    report = _job(c, c.post(f"/api/sessions/{sid}/propose/design"))
    assert len(report["proposed"]) == e["design_proposals"]
    pending, head = _pending(c, sid, "design")
    preset = next(p for p in pending if p["kind"] == "design.preset")
    assert preset["check"]["status"] == "cannot_check"
    comp50 = next(
        p for p in pending if p["kind"] == "design.dilution_series" and p["subject"] == "comp_50"
    )
    assert comp50["check"]["status"] == "contradicted"
    assert round(comp50["check"]["details"]["r2"], 3) == e["comp_50_r2"]
    roles = [
        p for p in pending
        if p["kind"] == "design.well_role" and p["check"]["status"] == "contradicted"
    ]  # fmt: skip
    assert len(roles) == e["well_roles_contradicted"]
    assert c.get(f"/api/sessions/{sid}/plate").json()["curves_shown"] is False
    r = c.post(
        f"/api/sessions/{sid}/proposals/{preset['id']}/accept",
        json={"reason": REASONS["preset"], "expected_head": head},
    )
    assert r.status_code == 200, r.text
    shown = c.get(f"/api/sessions/{sid}/bulk/accept", params={"stage": "design"}).json()
    assert len(shown["ids"]) == e["consistent_listed"]
    assert all(p["check"]["status"] == "consistent" for p in shown["proposals"])
    r = c.post(
        f"/api/sessions/{sid}/bulk/accept",
        json={"stage": "design", "ids": shown["ids"], "reason": REASONS["consistent"],
              "expected_head": shown["head"]},
    )  # fmt: skip
    assert r.status_code == 200 and r.json()["done"] == e["consistent_listed"]
    left, _ = _pending(c, sid, "design")
    assert len(left) == e["contradicted_left"]
    assert all(p["check"]["status"] == "contradicted" for p in left)
    # the rules made these, so "Reject contradicted AI calls" does not list them
    ai = c.get(f"/api/sessions/{sid}/bulk/reject", params={"stage": "design"}).json()
    assert ai["ids"] == []
    for p in left:
        r = c.post(
            f"/api/sessions/{sid}/proposals/{p['id']}/reject",
            json={"reason": REASONS["design_rejects"], "expected_head": _head(c, sid)},
        )
        assert r.status_code == 200, r.text
    assert c.get(f"/api/studies/{sid}/results").status_code == 404  # a session id is no study
    _confirm(c, sid, "design")

    # ---- 2. curves (blind) ----
    report = _job(c, c.post(f"/api/sessions/{sid}/propose/curves"))
    assert report["disagreements"] == e["curve_judge_disagreements"]
    pending, _ = _pending(c, sid, "curves")
    calls = [p for p in pending if p["kind"] == "curve.well_call"]
    assert len(calls) == e["curve_judge_well_calls"]
    assert {p["evidence"][0]["note"] for p in calls} == {f"target {e['curve_judge_target']}"}
    assert all(p["consequence"] == {"matters": True} for p in calls)
    run = calls[0]["subject"].rpartition("/")[0]
    plate = c.get(f"/api/sessions/{sid}/plate", params={"run": run}).json()
    assert plate["curves_shown"] and not plate["results_visible"]
    assert {w["key"] for w in plate["wells"] if w["proposal_id"]} <= {p["subject"] for p in calls}
    assert all(w["group"] is None for w in plate["wells"])
    curve = c.get(f"/api/sessions/{sid}/curve", params={"well": calls[0]["subject"]}).json()
    assert curve["numbers_shown"] and len(curve["cycle"]) >= 40
    listed = c.get(f"/api/sessions/{sid}/bulk/reject", params={"stage": "curves"}).json()
    assert sorted(listed["ids"]) == sorted(p["id"] for p in calls)
    r = c.post(
        f"/api/sessions/{sid}/bulk/reject",
        json={"stage": "curves", "ids": listed["ids"], "reason": REASONS["well_calls"],
              "expected_head": listed["head"]},
    )  # fmt: skip
    assert r.status_code == 200 and r.json()["done"] == len(calls)
    rule = next(p for p in _pending(c, sid, "curves")[0] if p["kind"] == "curve.call_rule")
    r = c.post(
        f"/api/sessions/{sid}/proposals/{rule['id']}/accept",
        json={"reason": REASONS["rule"], "expected_head": _head(c, sid)},
    )
    assert r.status_code == 200
    decided = _confirm(c, sid, "curves")
    assert decided["results_visible"] and decided["job"]
    study = wait_job(c, decided["job"], timeout=1800)["result"]["study_id"]

    # ---- 3. choices (results visible from here) ----
    results = c.get(f"/api/studies/{study}/results").json()
    odc1 = next(g for g in results["genes"] if g["gene"] == "ODC1")
    assert math.isclose(odc1["fc"], e["odc1_fc"], abs_tol=5e-4) and odc1["conclusion"] == "up"
    assert odc1["n_cells"] == e["grid_cells"] and len(results["genes"]) == e["genes"]
    assert results["session"] == sid
    cards = c.get(f"/api/studies/{study}/cards").json()
    for view in cards["cards"]:
        card = view["card"]
        if card["status"] == "auto_decided":
            continue
        head = c.get(f"/api/studies/{study}/cards").json()["head"]
        r = c.post(
            f"/api/studies/{study}/cards/{card['id']}/decide",
            json={"option": card["recommended"], "reason": REASONS["cards"], "expected_head": head},
        )
        assert r.status_code == 200, r.text
    _confirm(c, sid, "choices")
    stages = {s["stage"]: s for s in c.get(f"/api/sessions/{sid}").json()["stages"]}
    assert all(stages[s]["confirmed"] for s in ("design", "curves", "choices"))
