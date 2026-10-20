"""The Studio walk over HTTP on a small synthetic file: blind design and curves, then results.

Mirrors ``qpilot studio demo --check`` (``qpilot/cli/studio_cmds.py:_walk``) on the mini file:
the rules propose, an agent (through the MCP tools, as in real use) proposes the groups, a person
decides every proposal through the page's routes, and results appear only once both blind
stages are confirmed.
"""

from __future__ import annotations

import re

import pytest

from qpilot.ai import payload_log
from qpilot.mcp_server import QpilotTools
from tests.web.conftest import wait_job

GROUPS = {"WT_1": "WT", "WT_2": "WT", "KO_1": "KO", "KO_2": "KO"}
TAG = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")


def strings(value):
    """Every string in a JSON value (keys included)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


def no_html(body) -> None:
    bad = [s for s in strings(body) if TAG.search(s)]
    assert not bad, bad[:3]


def head(client, sid):
    return client.get(f"/api/sessions/{sid}/proposals").json()["head"]


def pending(client, sid, stage):
    body = client.get(f"/api/sessions/{sid}/proposals", params={"stage": stage}).json()
    return [p for p in body["proposals"] if p["status"] == "proposed"]


def propose(client, sid, what):
    r = client.post(f"/api/sessions/{sid}/propose/{what}")
    assert r.status_code == 202, r.text
    job = wait_job(client, r.json()["job"])
    assert job["status"] == "done", job
    return job["result"]


def agent_groups(store, sid):
    tools = QpilotTools(store)
    for sample, group in GROUPS.items():
        tools.qpcr_propose(sid, "design.group", sample, {"group": group})


def accept_all(client, sid, stage):
    """Bulk-accept what is consistent, then accept the rest one by one (with a reason)."""
    shown = client.get(f"/api/sessions/{sid}/bulk/accept", params={"stage": stage}).json()
    if shown["ids"]:
        r = client.post(
            f"/api/sessions/{sid}/bulk/accept",
            json={"stage": stage, "ids": shown["ids"], "expected_head": shown["head"]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["done"] == len(shown["ids"])
    for p in pending(client, sid, stage):
        if p["kind"] == "stage.confirm":
            continue
        r = client.post(
            f"/api/sessions/{sid}/proposals/{p['id']}/accept",
            json={"reason": "checked against the lab book", "expected_head": head(client, sid)},
        )
        assert r.status_code == 200, r.text


def confirm(client, sid, stage):
    shown = client.post(f"/api/sessions/{sid}/confirm/{stage}")
    assert shown.status_code == 200, shown.text
    view = shown.json()
    assert view["ready"] and view["proposal"]["kind"] == "stage.confirm"
    assert {p["id"] for p in view["covers"]} == set(view["proposal"]["payload"]["covers"])
    r = client.post(
        f"/api/sessions/{sid}/confirm/{stage}/accept",
        json={"proposal_id": view["proposal"]["id"], "expected_head": view["head"]},
    )
    assert r.status_code == 200, r.text
    return r.json()


def design_ready(client, store, sid):
    report = propose(client, sid, "design")
    assert report["proposed"] and report["fallback"] is True
    agent_groups(store, sid)
    accept_all(client, sid, "design")
    one = client.post(f"/api/sessions/{sid}/propose/comparison").json()
    assert one["outcome"]["status"] == "proposed", one
    r = client.post(
        f"/api/sessions/{sid}/proposals/{one['outcome']['proposal']['id']}/accept",
        json={"reason": "WT is the reference", "expected_head": head(client, sid)},
    )
    assert r.status_code == 200, r.text


def test_the_whole_walk_over_http(sclient, web_store, opened):
    sid = opened
    frame = sclient.get(f"/api/sessions/{sid}").json()
    assert frame["next_step"]["section"] == "design" and not frame["results_visible"]

    # blind: the plate has no curve numbers and no groups before the design is confirmed
    plate = sclient.get(f"/api/sessions/{sid}/plate").json()
    assert not plate["curves_shown"] and all(w["cq"] is None for w in plate["wells"])
    assert all(w["group"] is None for w in plate["wells"])

    design_ready(sclient, web_store, sid)
    decided = confirm(sclient, sid, "design")
    assert "design stage is confirmed" in decided["message"]
    assert not decided["results_visible"] and decided["job"] is None

    plate = sclient.get(f"/api/sessions/{sid}/plate").json()
    assert plate["curves_shown"] and any(w["cq"] is not None for w in plate["wells"])
    assert all(w["group"] is None for w in plate["wells"]), "no group next to a number while blind"

    curves = propose(sclient, sid, "curves")
    assert curves["stage"] == "curves" and curves["message"]
    accept_all(sclient, sid, "curves")
    decided = confirm(sclient, sid, "curves")
    assert decided["results_visible"]
    assert decided["job"] and decided["job"]["kind"] == "analyse"
    job = wait_job(sclient, decided["job"])
    assert job["status"] == "done", job
    study_id = job["result"]["study_id"]

    frame = sclient.get(f"/api/sessions/{sid}").json()
    assert frame["results_visible"] and frame["study_id"] == study_id
    assert frame["next_step"]["section"] in ("results", "audit", "record")
    plate = sclient.get(f"/api/sessions/{sid}/plate").json()
    groups = {w["sample"]: w["group"] for w in plate["wells"] if w["group"]}
    assert groups == {s: g for s, g in GROUPS.items() if s in groups} and groups

    # every decision was written by a person
    entries = web_store.proposals(sid).entries()
    assert {e.actor for e in entries if e.action != "propose"} == {"human"}


def test_blind_until_confirmed(sclient, web_store, opened):
    sid = opened
    for stage in ("prism", "roundtrip"):
        r = sclient.get(f"/api/sessions/{sid}/proposals", params={"stage": stage})
        assert r.status_code == 403 and r.json()["error"]["code"] == "blind"
    r = sclient.get(f"/api/sessions/{sid}/bulk/accept", params={"stage": "prism"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "blind"
    r = sclient.get(f"/api/sessions/{sid}/confirm/choices")
    assert r.status_code == 403 and r.json()["error"]["code"] == "blind"
    r = sclient.post(f"/api/sessions/{sid}/propose/curves")
    assert r.status_code == 409 and r.json()["error"]["code"] == "studio"
    # the model's last payload is withheld unless the Design Interpreter sent it
    payload_log.record_payload({"system": "explain this card", "user": "ODC1 3.6x up"})
    try:
        seen = sclient.get(f"/api/sessions/{sid}/model-seen").json()
        assert seen["state"] == "hidden" and seen["payload_text"] is None
    finally:
        payload_log.clear()
    assert sclient.get(f"/api/sessions/{sid}/model-seen").json()["state"] == "none"


def test_decisions_refuse_stale_and_settled(sclient, web_store, opened):
    sid = opened
    propose(sclient, sid, "design")
    first, second = pending(sclient, sid, "design")[:2]
    old = head(sclient, sid)
    r = sclient.post(
        f"/api/sessions/{sid}/proposals/{first['id']}/accept",
        json={"reason": "ok", "expected_head": old, "actor": "agent"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["outcome"]["proposal"]["decided_by"] == "human"
    # the same proposal again: settled, refused
    r = sclient.post(
        f"/api/sessions/{sid}/proposals/{first['id']}/accept",
        json={"expected_head": head(sclient, sid)},
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "refused"
    # a proposal the chain changed since the page read it (an agent superseded it)
    QpilotTools(web_store).qpcr_propose(sid, second["kind"], second["subject"], {"role": "std"})
    r = sclient.post(
        f"/api/sessions/{sid}/proposals/{second['id']}/accept", json={"expected_head": old}
    )
    assert r.status_code in (403, 409)
    if r.status_code == 409:
        assert r.json()["error"]["code"] == "stale"
        assert r.json()["error"]["details"]["head"] == head(sclient, sid)


def test_reject_needs_a_reason_and_edit_must_change_something(sclient, opened):
    sid = opened
    propose(sclient, sid, "design")
    p = pending(sclient, sid, "design")[0]
    r = sclient.post(
        f"/api/sessions/{sid}/proposals/{p['id']}/reject",
        json={"reason": "  ", "expected_head": head(sclient, sid)},
    )
    assert r.status_code == 422 and "reason" in r.json()["error"]["message"]
    r = sclient.post(
        f"/api/sessions/{sid}/proposals/{p['id']}/edit",
        json={"edits": dict(p["payload"]), "reason": "same", "expected_head": head(sclient, sid)},
    )
    assert r.status_code == 422 and "Nothing was changed" in r.json()["error"]["message"]
    r = sclient.post(
        f"/api/sessions/{sid}/proposals/{p['id']}/reject",
        json={"reason": "not this one", "expected_head": head(sclient, sid)},
    )
    assert r.status_code == 200 and r.json()["outcome"]["status"] == "rejected"
    r = sclient.post(
        f"/api/sessions/{sid}/proposals/{p['id']}/reject",
        json={"reason": "x" * 2001, "expected_head": head(sclient, sid)},
    )
    assert r.status_code == 422


def test_an_agent_proposal_can_be_edited_and_accepted(sclient, web_store, opened):
    sid = opened
    propose(sclient, sid, "design")
    agent_groups(web_store, sid)
    group = next(p for p in pending(sclient, sid, "design") if p["kind"] == "design.group")
    view = sclient.get(f"/api/sessions/{sid}/proposals/{group['id']}").json()
    assert view["proposal"]["made_by"]["kind"] == "agent" and view["blind"]
    r = sclient.post(
        f"/api/sessions/{sid}/proposals/{group['id']}/edit",
        json={
            "edits": {"group": "control"},
            "reason": "the lab calls it control",
            "expected_head": head(sclient, sid),
        },  # fmt: skip
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"]["status"] == "edited" and "control" in body["message"]


def test_bulk_lists_are_exactly_what_is_acted_on(sclient, opened):
    sid = opened
    propose(sclient, sid, "design")
    shown = sclient.get(f"/api/sessions/{sid}/bulk/accept", params={"stage": "design"}).json()
    assert shown["ids"] and all(p["check"]["status"] == "consistent" for p in shown["proposals"])
    assert set(shown["descriptions"]) == set(shown["ids"])
    # a list that is not the one shown is refused as a whole
    r = sclient.post(
        f"/api/sessions/{sid}/bulk/accept",
        json={
            "stage": "design",
            "ids": [*shown["ids"], "p_0000000000000000"],
            "expected_head": shown["head"],
        },  # fmt: skip
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale"
    assert r.json()["error"]["details"]["ids"] == shown["ids"]
    r = sclient.post(
        f"/api/sessions/{sid}/bulk/accept",
        json={"stage": "design", "ids": [], "expected_head": shown["head"]},
    )
    assert r.status_code == 422
    r = sclient.post(
        f"/api/sessions/{sid}/bulk/accept",
        json={"stage": "design", "ids": shown["ids"], "expected_head": shown["head"]},
    )
    assert r.status_code == 200 and r.json()["done"] == len(shown["ids"])
    rejecting = sclient.get(f"/api/sessions/{sid}/bulk/reject", params={"stage": "design"})
    assert rejecting.status_code == 200 and rejecting.json()["action"] == "reject"
    r = sclient.post(
        f"/api/sessions/{sid}/bulk/reject",
        json={
            "stage": "design",
            "ids": rejecting.json()["ids"] or ["p_0000000000000000"],
            "expected_head": head(sclient, sid),
        },  # fmt: skip
    )
    assert r.status_code in (409, 422)


def test_confirm_refuses_while_the_stage_is_open(sclient, opened):
    sid = opened
    propose(sclient, sid, "design")
    r = sclient.post(f"/api/sessions/{sid}/confirm/design")
    assert r.status_code == 409 and r.json()["error"]["message"].startswith("Not ready to confirm")
    view = sclient.get(f"/api/sessions/{sid}/confirm/design").json()
    assert not view["ready"] and view["proposal"] is None


def test_reading_routes_and_their_ids(sclient, opened, mini_rdml):
    sid = opened
    propose(sclient, sid, "design")
    q = sclient.get(f"/api/sessions/{sid}/quarantine").json()
    injection = [e for e in q["entries"] if "ignore previous instructions" in e["value"]]
    assert injection and "instruction_like" in injection[0]["flags"]
    one = sclient.get(f"/api/sessions/{sid}/quarantine", params={"ids": injection[0]["text_id"]})
    assert [e["text_id"] for e in one.json()["entries"]] == [injection[0]["text_id"]]
    p = pending(sclient, sid, "design")[0]
    view = sclient.get(f"/api/sessions/{sid}/proposals/{p['id']}").json()
    assert view["description"] and isinstance(view["alternatives"], list)
    texts = [e for e in view["evidence"] if e["kind"] == "text"]
    assert all(e["text"] is not None and e["origin"] for e in texts)
    plate = sclient.get(f"/api/sessions/{sid}/plate").json()
    assert plate["n_rows"] * plate["n_cols"] >= len(plate["wells"]) > 0
    well = plate["wells"][0]
    curve = sclient.get(f"/api/sessions/{sid}/curve", params={"well": well["key"]}).json()
    assert curve["cycle"] and len(curve["cycle"]) == len(curve["fluorescence"])
    assert not curve["numbers_shown"] and curve["cq"] is None
    calls = sclient.get(f"/api/sessions/{sid}/curve-calls", params={"gene": well["target"]})
    assert calls.status_code == 200 and calls.json()["wells"]
    for path, params, code in (
        ("/api/sessions/ZZZ/plate", None, 404),
        (f"/api/sessions/{'0' * 12}/plate", None, 404),
        (f"/api/sessions/{sid}/plate", {"run": "no such plate"}, 404),
        (f"/api/sessions/{sid}/curve", {"well": "../../etc/passwd"}, 422),
        (f"/api/sessions/{sid}/curve", {"well": f"{plate['run']['run_id']}/Z99"}, 404),
        (f"/api/sessions/{sid}/proposals/../x", None, 404),
        (f"/api/sessions/{sid}/proposals/p_zz", None, 404),
        (f"/api/sessions/{sid}/proposals/p_0000000000000000", None, 404),
        (f"/api/sessions/{sid}/curve-calls", {"gene": "NOPE"}, 409),
        (f"/api/sessions/{sid}/bulk/accept", {"stage": "nowhere"}, 422),
    ):
        r = sclient.get(path, params=params)
        assert r.status_code == code, (path, r.status_code, r.text)
        assert "error" in r.json()
    for body in (q, view, plate, curve, calls.json()):
        no_html(body)


def test_matters_answers_only_yes_or_no(sclient, web_store, opened):
    sid = opened
    design_ready(sclient, web_store, sid)
    some = sclient.get(f"/api/sessions/{sid}/proposals", params={"stage": "design"}).json()
    target = next(p for p in some["proposals"] if p["alternatives"])
    r = sclient.post(f"/api/sessions/{sid}/proposals/{target['id']}/matters")
    assert r.status_code == 202
    job = wait_job(sclient, r.json()["job"])
    assert job["status"] == "done", job
    answer = job["result"]
    assert set(answer) == {"proposal_id", "matters", "head", "message"}
    assert answer["matters"] in (True, False, None)


@pytest.mark.parametrize("stage", ["design", "curves"])
def test_proposing_writes_as_the_system_and_says_so(sclient, opened, stage):
    sid = opened
    if stage == "curves":
        r = sclient.post(f"/api/sessions/{sid}/propose/curves")
        assert r.status_code == 409
        return
    report = propose(sclient, sid, "design")
    assert report["message"].startswith(f"{len(report['proposed'])} design proposal")
    listed = sclient.get(f"/api/sessions/{sid}/proposals", params={"stage": "design"}).json()
    assert {p["made_by"]["kind"] for p in listed["proposals"]} == {"rule"}
    assert set(listed["descriptions"]) == {p["id"] for p in listed["proposals"]}


def test_a_confirm_step_is_only_accepted_as_shown(sclient, web_store, opened):
    sid = opened
    design_ready(sclient, web_store, sid)
    view = sclient.post(f"/api/sessions/{sid}/confirm/design").json()
    pid = view["proposal"]["id"]
    for action, body in (
        ("edit", {"edits": {"covers": []}, "reason": "x"}),
        ("accept", {"reason": "x"}),
    ):
        r = sclient.post(
            f"/api/sessions/{sid}/proposals/{pid}/{action}",
            json={**body, "expected_head": view["head"]},
        )
        assert r.status_code == 403 and r.json()["error"]["code"] == "refused", action
    stages = {s["stage"]: s for s in sclient.get(f"/api/sessions/{sid}").json()["stages"]}
    assert not stages["design"]["confirmed"]
    # withdrawing it (a reject with a reason) is allowed
    r = sclient.post(
        f"/api/sessions/{sid}/proposals/{pid}/reject",
        json={"reason": "not yet", "expected_head": view["head"]},
    )
    assert r.status_code == 200 and "stays open" in r.json()["message"]


def test_asking_twice_whether_it_matters_runs_once(sclient, web_store, opened, monkeypatch):
    import threading

    sid = opened
    design_ready(sclient, web_store, sid)
    some = sclient.get(f"/api/sessions/{sid}/proposals", params={"stage": "design"}).json()
    target = next(p for p in some["proposals"] if p["alternatives"])
    gate = threading.Event()
    studio = sclient.app.state.ctx.studio
    real = studio.matters
    monkeypatch.setattr(studio, "matters", lambda s, p: (gate.wait(10), real(s, p))[1])
    try:
        url = f"/api/sessions/{sid}/proposals/{target['id']}/matters"
        first, second = sclient.post(url).json()["job"], sclient.post(url).json()["job"]
    finally:
        gate.set()
    assert first["id"] == second["id"]
    assert wait_job(sclient, first)["status"] == "done"


def test_a_cold_file_answers_warming_then_fills_in(sclient, opened):
    from qpilot.qpcr import inspect as qinspect

    sid = opened
    ctx = sclient.app.state.ctx
    qinspect.clear_cache()  # as after a restart: the file's facts are not in memory
    ctx.facts_wait = 0.0
    frame = sclient.get(f"/api/sessions/{sid}").json()
    assert frame["warming"] and frame["stages"] == [] and frame["facts"] is None
    assert any(j["kind"] == "warm" for j in frame["active_jobs"])
    r = sclient.get(f"/api/sessions/{sid}/plate")
    if r.status_code == 503:
        assert r.json()["error"]["code"] == "warming" and r.json()["error"]["details"]["job"]
        wait_job(sclient, r.json()["error"]["details"]["job"])
    listed = sclient.get("/api/workspaces").json()["workspaces"]
    assert [w["key"] for w in listed] == [sid]
    ctx.facts_wait = None
    frame = sclient.get(f"/api/sessions/{sid}").json()
    assert not frame["warming"] and frame["stages"] and frame["facts"]


def test_an_edit_is_checked_before_it_is_accepted(sclient, web_store, opened):
    sid = opened
    propose(sclient, sid, "design")
    p = next(x for x in pending(sclient, sid, "design") if x["kind"] == "design.well_role")
    other = "unkn" if p["payload"].get("role") != "unkn" else "ntc"
    r = sclient.post(
        f"/api/sessions/{sid}/proposals/{p['id']}/check", json={"edits": {"role": other}}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] in ("consistent", "contradicted", "cannot_check")
    r = sclient.post(f"/api/sessions/{sid}/proposals/{p['id']}/check", json={"edits": {"x": 1}})
    assert r.status_code == 422
    assert pending(sclient, sid, "design")[0]["status"] == "proposed", "a check writes nothing"
