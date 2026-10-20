"""Red team: blind stages, actor spoofing and stale-head races on the Studio routes.

The hard case for "blind until confirmed" is a session that *was* confirmed and analysed, and
then went blind again because a person accepted a design change: its earlier study (with fold
changes, p-values, Decision Cards) is still in the store. Every route must then answer as for a
blind session. One such session is walked once for this module (the mini file; ~15 s).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from qpilot.mcp_server import QpilotTools
from tests.web.conftest import BASE, TOKEN, wait_job

# Keys whose value is a result (a number about a group difference) in any API answer.
RESULT_KEYS = {
    "fold",
    "fold_change",
    "log2_fold",
    "log2fc",
    "log2_fc",
    "ratio",
    "p",
    "p_value",
    "pvalue",
    "q_value",
    "ci",
    "ci_low",
    "ci_high",
    "conclusion",
    "conclusions",
    "contrast",
    "contrasts",
    "direction",
    "holds",
    "robustness",
    "verdict",
    "effect",
    "expression",
}


def _leaks(value: Any, where: str = "$") -> list[str]:
    """Paths in a JSON value where a result shows (a result key with a value)."""
    out: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            if str(k).lower() in RESULT_KEYS and v not in (None, [], {}, ""):
                out.append(f"{where}.{k}")
            out.extend(_leaks(v, f"{where}.{k}"))
        group = value.get("group")
        numbers = [k for k, v in value.items() if isinstance(v, int | float) and k != "group"]
        if group and numbers and not isinstance(group, dict):
            out.append(f"{where}: group {group!r} next to {numbers[:3]}")
    elif isinstance(value, list):
        for i, v in enumerate(value[:400]):
            out.extend(_leaks(v, f"{where}[{i}]"))
    return out


# ---- one session walked to results, then re-opened (module scope) ----------------------------


@contextmanager
def walked(base: Path, reblind: bool) -> Iterator[dict[str, Any]]:
    """The mini file walked over HTTP to results (and, with ``reblind``, re-opened after).

    Re-opening: an agent proposes moving one sample to the other group and a person accepts
    it, so the design changes and the session is blind again.
    """
    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.core.store import StudyStore
    from qpilot.qpcr import design_checks
    from qpilot.qpcr import inspect as qinspect
    from qpilot.studio_service import Studio
    from qpilot.web.context import make_context
    from qpilot.web.server import create_app
    from tests.fixtures.studio.studio_mini import write_studio_mini
    from tests.web.test_studio_flow import accept_all, confirm, design_ready, head, propose

    with pytest.MonkeyPatch.context() as mp:
        (base / "data").mkdir()
        (base / "studies").mkdir()
        mp.setenv("QPILOT_DATA_ROOTS", str(base / "data"))
        mp.setenv("QPILOT_STUDIES_DIR", str(base / "studies"))
        qinspect.clear_cache()
        rdml = write_studio_mini(base / "data" / "mini.rdml")
        store = StudyStore(base / "studies")
        studio = Studio(store, client=ModelClient(backend=NoneBackend()))
        ctx = make_context(store, studio, token=TOKEN, watch=False)
        events: list[dict[str, Any]] = []
        real_publish = ctx.bus.publish
        ctx.bus.publish = lambda e: (events.append(e), real_publish(e))[1]  # type: ignore[method-assign]
        app = create_app(ctx)
        try:
            with TestClient(app, base_url=BASE) as c:
                c.headers["x-qpilot-token"] = TOKEN
                c.headers["origin"] = BASE
                r = c.post("/api/workspaces", files={"rdml": ("mini.rdml", rdml.read_bytes())})
                sid = wait_job(c, r.json()["job"])["result"]["key"]
                design_ready(c, store, sid)
                confirm(c, sid, "design")
                propose(c, sid, "curves")
                accept_all(c, sid, "curves")
                job = wait_job(c, confirm(c, sid, "curves")["job"])
                study_id = job["result"]["study_id"]
                assert c.get(f"/api/sessions/{sid}").json()["results_visible"]
                if reblind:
                    QpilotTools(store).qpcr_propose(sid, "design.group", "WT_1", {"group": "KO"})
                    listed = c.get(f"/api/sessions/{sid}/proposals", params={"stage": "design"})
                    change = next(
                        p
                        for p in listed.json()["proposals"]
                        if p["status"] == "proposed" and p["kind"] == "design.group"
                    )
                    r = c.post(
                        f"/api/sessions/{sid}/proposals/{change['id']}/accept",
                        json={"reason": "the lab book says KO", "expected_head": head(c, sid)},
                    )
                    assert r.status_code == 200, r.text
                    assert not r.json()["results_visible"]
                yield {
                    "client": c,
                    "app": app,
                    "ctx": ctx,
                    "store": store,
                    "sid": sid,
                    "study_id": study_id,
                    "analyse_job": job["id"],
                    "events": events,
                }
        finally:
            ctx.close()
            design_checks._DECLARED.clear()
            design_checks.set_input_resolver(None)
            qinspect.clear_cache()


@pytest.fixture(scope="module")
def reblinded(tmp_path_factory) -> Iterator[dict[str, Any]]:
    """A session confirmed and analysed, then blind again after a person's design change."""
    with walked(tmp_path_factory.mktemp("reblind"), reblind=True) as walk:
        yield walk


def test_the_reblinded_frame_hides_the_old_study(reblinded):
    c, sid = reblinded["client"], reblinded["sid"]
    frame = c.get(f"/api/sessions/{sid}").json()
    assert not frame["results_visible"] and frame["study_id"] is None
    assert frame["decisions_head"] is None
    listed = c.get("/api/workspaces").json()["workspaces"]
    assert [w["key"] for w in listed] == [sid], "the session's study is listed on its own"


@pytest.mark.xfail(
    strict=True,
    reason="RT-UI-009 GET /api/studies/{id} (and every route under it) serves a session's study "
    "while that session is blind again (design changed after confirm): the study routes never "
    "ask the session's gate; the id is in the analyse job's result and the study.changed events",
)
def test_a_blind_sessions_study_is_not_served_by_id(reblinded):
    c, study_id = reblinded["client"], reblinded["study_id"]
    r = c.get(f"/api/studies/{study_id}")
    assert r.status_code == 403 and r.json()["error"]["code"] == "blind", r.text[:300]


def _fill(path: str, reblinded: dict[str, Any], c: TestClient) -> str | None:
    """A concrete URL for a route path of a session or study (None when it cannot be filled)."""
    sid, study = reblinded["sid"], reblinded["study_id"]
    proposals = c.get(f"/api/sessions/{sid}/proposals").json()["proposals"]
    values = {
        "sid": sid,
        "key": sid,
        "study_id": study,
        "id": study,
        "pid": proposals[0]["id"] if proposals else "p_0000000000000000",
        "gene": "1-Mar",
        "stage": "design",
        "action": "accept",
        "job_id": reblinded["analyse_job"],
    }
    out = path
    for name, value in values.items():
        out = out.replace("{" + name + "}", value)
    return None if "{" in out else out


QUERY = {"well": None, "gene": "1-Mar", "stage": "design"}


def _get_routes(app) -> list[str]:
    return sorted(
        r.path
        for r in app.routes
        if "GET" in getattr(r, "methods", set())
        and r.path.startswith(("/api/sessions/{", "/api/studies/{"))
    )


def test_no_route_of_a_blind_session_answers_with_a_result(reblinded):
    c, app, sid = reblinded["client"], reblinded["app"], reblinded["sid"]
    plate = c.get(f"/api/sessions/{sid}/plate").json()
    params = {**QUERY, "well": plate["wells"][0]["key"]}
    problems: dict[str, list[str]] = {}
    for route in _get_routes(app):
        if route.startswith("/api/studies/"):
            continue  # RT-UI-009 (above) covers the study routes
        url = _fill(route, reblinded, c)
        if url is None:
            continue
        r = c.get(url, params={k: v for k, v in params.items() if "{" + k + "}" not in route})
        if r.status_code != 200 or not r.headers["content-type"].startswith("application/json"):
            continue
        found = _leaks(r.json())
        if found:
            problems[url] = found[:5]
    assert not problems, problems


def _study_routes(app, method: str) -> list[str]:
    return sorted(
        r.path
        for r in app.routes
        if method in getattr(r, "methods", set())
        and r.path.startswith("/api/studies/{")
        and r.path != "/api/studies/{study_id}"
    )


BODIES = {
    "decide": {"option": "x", "reason": "r"},
    "undo": {"reason": "r"},
    "reject-request": {"reason": "r"},
    "ask": {"question": "Which genes changed?"},
}


def test_every_study_route_of_a_blind_session_is_blind(reblinded):
    """Every study route (results, gene, cards, audit, files, ask …) answers 403 blind."""
    c, app = reblinded["client"], reblinded["app"]
    open_routes: dict[str, int] = {}
    for method in ("GET", "POST", "PUT"):
        for route in _study_routes(app, method):
            url = _fill(route.replace("{card_id}", "reference_set"), reblinded, c)
            if url is None:
                url = route.replace("{study_id}", reblinded["study_id"])
                url = url.replace("{gene}", "1-Mar").replace("{g}", "1-Mar")
                if "{" in url:
                    continue
            body = BODIES.get(url.rsplit("/", 1)[-1], {})
            r = c.request(method, url, json=body, params={"gene": "1-Mar"})
            if r.status_code not in (403, 422) or (
                r.status_code == 403 and r.json()["error"]["code"] != "blind"
            ):
                open_routes[f"{method} {route}"] = r.status_code
    assert not open_routes, open_routes


def test_the_plate_of_a_blind_session_pairs_no_group_with_a_number(reblinded):
    c, sid = reblinded["client"], reblinded["sid"]
    plate = c.get(f"/api/sessions/{sid}/plate").json()
    assert not plate["results_visible"]
    assert all(w["group"] is None for w in plate["wells"])


def test_result_stages_stay_blind(reblinded):
    c, sid = reblinded["client"], reblinded["sid"]
    for stage in ("prism", "roundtrip"):
        r = c.get(f"/api/sessions/{sid}/proposals", params={"stage": stage})
        assert r.status_code == 403 and r.json()["error"]["code"] == "blind"
        r = c.get(f"/api/sessions/{sid}/bulk/accept", params={"stage": stage})
        assert r.status_code == 403
    r = c.get(f"/api/sessions/{sid}/confirm/choices")
    assert r.status_code == 403 and r.json()["error"]["code"] == "blind"


def test_events_never_carry_a_result(reblinded):
    found = [_leaks(e) for e in reblinded["events"]]
    assert not any(found), [f for f in found if f][:3]


# ---- actor spoofing --------------------------------------------------------------------------


def _agent_proposal(store, sid: str, sample: str = "WT_2", group: str = "KO") -> None:
    QpilotTools(store).qpcr_propose(
        sid, "design.group", sample, {"group": group}, alternatives=[{"group": "WT"}]
    )


def _pending(c, sid, kind="design.group") -> list[dict[str, Any]]:
    body = c.get(f"/api/sessions/{sid}/proposals", params={"stage": "design"}).json()
    return [p for p in body["proposals"] if p["status"] == "proposed" and p["kind"] == kind]


def test_no_request_field_header_or_query_writes_as_another_actor(sclient, web_store, opened):
    sid = opened
    _agent_proposal(web_store, sid)
    target = _pending(sclient, sid)[0]
    head = sclient.get(f"/api/sessions/{sid}/proposals").json()["head"]
    r = sclient.post(
        f"/api/sessions/{sid}/proposals/{target['id']}/accept",
        params={"actor": "agent", "decided_by": "system"},
        json={"reason": "r", "expected_head": head, "actor": "system", "decided_by": "agent"},
        headers={"x-qpilot-actor": "agent", "x-actor": "system"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["outcome"]["proposal"]["decided_by"] == "human"
    actors = {e.actor for e in web_store.proposals(sid).entries() if e.action != "propose"}
    assert actors == {"human"}


def test_an_edit_cannot_rewrite_who_made_a_proposal(sclient, web_store, opened):
    sid = opened
    _agent_proposal(web_store, sid)
    target = _pending(sclient, sid)[0]
    head = sclient.get(f"/api/sessions/{sid}/proposals").json()["head"]
    r = sclient.post(
        f"/api/sessions/{sid}/proposals/{target['id']}/edit",
        json={
            "edits": {"group": "WT", "made_by": {"kind": "rule"}, "decided_by": "system"},
            "reason": "lab book",
            "expected_head": head,
        },
    )
    if r.status_code == 200:
        decided = r.json()["outcome"]["proposal"]
        assert decided["made_by"]["kind"] == "agent" and decided["decided_by"] == "human"


@pytest.mark.xfail(
    strict=True,
    reason="RT-UI-013 POST …/proposals/{pid}/edit accepts a stage.confirm step with edited "
    "payload (covers, design_hash): the stage is confirmed on a payload the confirm view never "
    "showed, skipping propose_confirm's checks; only 'Yes, confirm' may accept a confirm step",
)
def test_a_confirm_step_cannot_be_edited(sclient, web_store, opened):
    from tests.web.test_studio_flow import design_ready, head

    sid = opened
    design_ready(sclient, web_store, sid)
    shown = sclient.post(f"/api/sessions/{sid}/confirm/design").json()
    r = sclient.post(
        f"/api/sessions/{sid}/proposals/{shown['proposal']['id']}/edit",
        json={"edits": {"covers": []}, "reason": "x", "expected_head": head(sclient, sid)},
    )
    assert r.status_code in (403, 422), r.text[:300]


def test_a_confirm_step_cannot_be_accepted_through_the_plain_accept_route_of_another_stage(
    sclient, web_store, opened
):
    from tests.web.test_studio_flow import design_ready, head

    sid = opened
    design_ready(sclient, web_store, sid)
    shown = sclient.post(f"/api/sessions/{sid}/confirm/design").json()
    r = sclient.post(
        f"/api/sessions/{sid}/confirm/curves/accept",
        json={"proposal_id": shown["proposal"]["id"], "expected_head": head(sclient, sid)},
    )
    assert r.status_code == 422


# ---- stale heads and two writers -------------------------------------------------------------


def test_two_writers_on_one_head_one_wins(sclient, web_store, opened):
    sid = opened
    _agent_proposal(web_store, sid, "WT_2", "KO")
    _agent_proposal(web_store, sid, "KO_2", "WT")
    first, second = _pending(sclient, sid)[:2]
    head = sclient.get(f"/api/sessions/{sid}/proposals").json()["head"]
    codes: list[int] = []
    barrier = threading.Barrier(2)

    def write(pid: str) -> None:
        barrier.wait()
        r = sclient.post(
            f"/api/sessions/{sid}/proposals/{pid}/accept",
            json={"reason": "r", "expected_head": head},
        )
        codes.append(r.status_code)

    threads = [threading.Thread(target=write, args=(p["id"],)) for p in (first, second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert sorted(codes) == [200, 409], codes


def test_a_write_on_an_old_head_is_stale_and_names_the_new_head(sclient, web_store, opened):
    sid = opened
    _agent_proposal(web_store, sid, "WT_2", "KO")
    _agent_proposal(web_store, sid, "KO_2", "WT")
    first, second = _pending(sclient, sid)[:2]
    old = sclient.get(f"/api/sessions/{sid}/proposals").json()["head"]
    ok = sclient.post(  # another tab decides meanwhile
        f"/api/sessions/{sid}/proposals/{first['id']}/accept",
        json={"reason": "r", "expected_head": old},
    )
    assert ok.status_code == 200
    r = sclient.post(
        f"/api/sessions/{sid}/proposals/{second['id']}/accept",
        json={"reason": "r", "expected_head": old},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale"
    assert r.json()["error"]["details"]["head"] == ok.json()["head"]


def test_an_agents_proposal_elsewhere_never_makes_a_person_stale(sclient, web_store, opened):
    sid = opened
    _agent_proposal(web_store, sid, "WT_2", "KO")
    old = sclient.get(f"/api/sessions/{sid}/proposals").json()["head"]
    target = _pending(sclient, sid)[0]
    _agent_proposal(web_store, sid, "KO_2", "WT")  # an agent cannot block a person
    r = sclient.post(
        f"/api/sessions/{sid}/proposals/{target['id']}/accept",
        json={"reason": "r", "expected_head": old},
    )
    assert r.status_code == 200, r.text[:200]


@pytest.mark.xfail(
    strict=True,
    reason="RT-UI-014 expected_head is optional on accept/edit/reject/confirm/bulk: a write "
    "without it skips the stale check, so a page bug (or any client) decides on a view the "
    "chain has moved past; docs/app.md §6 says writes carry it",
)
def test_a_decision_without_the_head_it_was_made_on_is_refused(sclient, web_store, opened):
    sid = opened
    _agent_proposal(web_store, sid, "WT_2", "KO")
    _agent_proposal(web_store, sid, "KO_2", "WT")
    target = _pending(sclient, sid)[0]
    r = sclient.post(f"/api/sessions/{sid}/proposals/{target['id']}/accept", json={"reason": "r"})
    assert r.status_code == 422, r.text[:200]


@pytest.mark.parametrize("head", ["", "x" * 64, "../" * 20, "0" * 64])
def test_nonsense_heads_are_stale_not_errors(sclient, web_store, opened, head):
    sid = opened
    _agent_proposal(web_store, sid)
    target = _pending(sclient, sid)[0]
    r = sclient.post(
        f"/api/sessions/{sid}/proposals/{target['id']}/accept",
        json={"reason": "r", "expected_head": head},
    )
    assert r.status_code in (409, 422)


# ---- flooding --------------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="RT-UI-015 'Does this matter?' is submitted with dedupe=False: every click queues two "
    "more full analyses (~6 s each on the demo) on the 3-worker pool, so a burst of clicks "
    "starves the analysis, the audit and every other job",
)
def test_does_this_matter_twice_is_one_job(sclient, web_store, opened):
    sid = opened
    _agent_proposal(web_store, sid)
    target = _pending(sclient, sid)[0]
    ids = {
        sclient.post(f"/api/sessions/{sid}/proposals/{target['id']}/matters").json()["job"]["id"]
        for _ in range(5)
    }
    assert len(ids) == 1, f"5 clicks queued {len(ids)} jobs"


@pytest.mark.parametrize(
    "path,params",
    [
        ("plate", {"run": "../../../../etc/passwd"}),
        ("plate", {"run": "x" * 128}),
        ("curve", {"well": "../../etc/passwd"}),
        ("curve", {"well": "a/../../b/A1"}),
        ("curve", {"well": "plate/A1", "target": "../../x"}),
        ("curve-calls", {"gene": "../../../etc/passwd"}),
        ("curve-calls", {"gene": "<img src=x onerror=alert(1)>"}),
        ("quarantine", {"ids": "../../x," * 50}),
        ("model-seen", {"proposal": "../../../x"}),
        ("proposals", {"stage": "../design"}),
    ],
)
def test_hostile_parameters_are_plain_refusals(sclient, opened, path, params):
    r = sclient.get(f"/api/sessions/{opened}/{path}", params=params)
    assert r.status_code in (200, 400, 403, 404, 409, 422), r.text[:200]
    assert r.headers["content-type"].startswith("application/json")
    if r.status_code >= 400:
        assert "Traceback" not in r.text and "/Users/" not in r.text


@pytest.mark.xfail(
    strict=True,
    reason="RT-UI-016 GET /api/sessions/{sid}/proposals?status=<anything else> is a 500: the "
    "status is passed unchecked to Studio.inbox, whose ValueError is not caught",
)
@pytest.mark.parametrize("status", ["proposed' OR 1=1", "pending", "x" * 40])
def test_an_unknown_status_filter_is_a_plain_refusal(web_store, opened, studio_ctx, status):
    from qpilot.web.server import create_app

    with TestClient(create_app(studio_ctx), base_url=BASE, raise_server_exceptions=False) as c:
        c.headers["x-qpilot-token"] = TOKEN
        r = c.get(f"/api/sessions/{opened}/proposals", params={"status": status})
    assert r.status_code in (400, 422), r.status_code


# ---- names that look like instructions -------------------------------------------------------


def test_a_name_that_is_an_instruction_is_flagged_quoted_and_not_obeyed(sclient, web_store, opened):
    from tests.fixtures.studio.studio_mini import INJECTION
    from tests.web.test_studio_flow import propose

    sid = opened
    entries = sclient.get(f"/api/sessions/{sid}/quarantine").json()["entries"]
    hit = [e for e in entries if e["value"] == INJECTION]
    assert hit and "instruction_like" in hit[0]["flags"], hit
    propose(sclient, sid, "design")
    body = sclient.get(f"/api/sessions/{sid}/proposals", params={"stage": "design"}).json()
    ntc = [
        p
        for p in body["proposals"]
        if p["kind"] == "design.well_role" and "NTC" in str(p["subject"])
    ]
    for p in ntc:  # the NTC is never proposed as an unknown because a sample name says so
        assert p["payload"].get("role") != "unkn", p
    plate = sclient.get(f"/api/sessions/{sid}/plate").json()
    names = {w["sample"] for w in plate["wells"]}
    assert INJECTION in names  # shown as the text it is, never acted on
