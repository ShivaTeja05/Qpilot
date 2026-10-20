"""A session that goes blind again keeps its records and bundles hidden (redteam RT-UI-023).

The mini file is walked over HTTP to results, a record of its study is exported, then an agent
proposes moving one sample to the other group and a person accepts it: the design changed, so
the session is blind again and its earlier study (with fold changes and p-values) must not be
exported, listed or downloaded.
"""

from __future__ import annotations

from qpilot.mcp_server import QpilotTools
from tests.web.conftest import wait_job
from tests.web.test_studio_flow import accept_all, confirm, design_ready, head, propose


def test_a_blind_again_sessions_records_are_not_served(sclient, web_store, opened):
    sid = opened
    design_ready(sclient, web_store, sid)
    confirm(sclient, sid, "design")
    propose(sclient, sid, "curves")
    accept_all(sclient, sid, "curves")
    study_id = wait_job(sclient, confirm(sclient, sid, "curves")["job"])["result"]["study_id"]
    exported = wait_job(
        sclient, sclient.post(f"/api/studies/{study_id}/record", json={}).json()["job"]
    )
    assert exported["status"] == "done", exported
    url = exported["result"]["download"]["url"]
    assert sclient.get(url).status_code == 200
    assert sclient.get(f"/api/studies/{study_id}/records").status_code == 200

    QpilotTools(web_store).qpcr_propose(sid, "design.group", "WT_1", {"group": "KO"})
    listed = sclient.get(f"/api/sessions/{sid}/proposals", params={"stage": "design"}).json()
    change = next(
        p for p in listed["proposals"] if p["status"] == "proposed" and p["kind"] == "design.group"
    )
    r = sclient.post(
        f"/api/sessions/{sid}/proposals/{change['id']}/accept",
        json={"reason": "the lab book says KO", "expected_head": head(sclient, sid)},
    )
    assert r.status_code == 200 and not r.json()["results_visible"], r.text

    for response in (
        sclient.post(f"/api/studies/{study_id}/record", json={}),
        sclient.get(f"/api/studies/{study_id}/records"),
        sclient.get(url),
        sclient.get(f"/api/sessions/{sid}/prism/bundles"),
    ):
        assert response.status_code == 403, response.text[:200]
        assert response.json()["error"]["code"] == "blind"
