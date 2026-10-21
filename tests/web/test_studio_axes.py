"""Also test efficiency models, over HTTP on the walked mini session (no download, no model).

The rule proposes the choice in the choices stage (``POST …/propose/axis``), the engine checks
it (D-AXIS), a person accepts it through the page's routes; the confirmed design gains the axis,
the study is analysed again with it, and Results says what the grid did with it. The blind
stages stay confirmed, switching it off again gives back the earlier study with its decisions,
and the Analysis Record verifies and re-runs with it.
"""

from __future__ import annotations

import pytest

from qpilot.core.proposals import ProposalError
from qpilot.core.record import rerun_compare, verify, write_record
from tests.web.conftest import wait_job

MINI_OPTIONS = ["linregpcr", "per_well", "assumed_2", "standard_curve"]  # one plate per assay


def _head(c, sid):
    return c.get(f"/api/sessions/{sid}/proposals").json()["head"]


def _stages(c, sid):
    return {s["stage"]: s for s in c.get(f"/api/sessions/{sid}").json()["stages"]}


def _propose(c, sid, on=True):
    r = c.post(f"/api/sessions/{sid}/propose/axis", json={"axis": "efficiency", "on": on})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"]["status"] == "proposed", body
    return body


def _accept(c, sid, pid, reason="checked"):
    r = c.post(
        f"/api/sessions/{sid}/proposals/{pid}/accept",
        json={"reason": reason, "expected_head": _head(c, sid)},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    if body.get("job"):
        assert wait_job(c, body["job"])["status"] == "done"
    return body


def _study(c, sid):
    frame = c.get(f"/api/sessions/{sid}").json()
    assert frame["results_visible"], frame["next_step"]
    return frame["study_id"]


def test_the_rule_proposes_the_models_that_apply_and_the_engine_checks_them(walked):
    c, sid, studio = walked["client"], walked["sid"], walked["studio"]
    body = _propose(c, sid)
    proposal = body["outcome"]["proposal"]
    assert proposal["kind"] == "choice.axis" and proposal["subject"] == "efficiency"
    assert proposal["payload"] == {"options": MINI_OPTIONS}
    assert proposal["made_by"]["kind"] == "rule" and proposal["status"] == "proposed"
    assert proposal["check"]["status"] == "consistent"
    assert proposal["check"]["rule_ids"] == ["D-AXIS"]
    assert any("not offered" in r and "one run" in r for r in proposal["reasons"])
    assert proposal["alternatives"] == [{"options": ["linregpcr"]}]
    listed = c.get(f"/api/sessions/{sid}/proposals", params={"stage": "choices"}).json()
    assert [p["id"] for p in listed["proposals"]] == [proposal["id"]]
    assert listed["descriptions"][proposal["id"]].startswith("Also test which efficiency")
    stages = _stages(c, sid)
    assert stages["choices"]["pending"] == 1
    assert stages["design"]["confirmed"] and stages["curves"]["confirmed"]
    frame = c.get(f"/api/sessions/{sid}").json()
    assert frame["next_step"]["title"] == "Decide which further choices to test"
    # nothing changed: the same study, the axis not tested
    assert frame["study_id"] == walked["study"]
    assert studio.store.design(walked["study"]).axes is None


def test_accepting_analyses_again_with_the_axis_and_results_say_what_it_did(walked):
    c, sid, store = walked["client"], walked["sid"], walked["store"]
    before = c.get(f"/api/studies/{walked['study']}/results").json()["axes"]
    assert [a["status"] for a in before] == ["off"] and before[0]["can_propose"]
    assert before[0]["command"] is None
    proposal = _propose(c, sid)["outcome"]["proposal"]
    decided = _accept(c, sid, proposal["id"], "test them before deciding the cards")
    assert decided["outcome"]["status"] == "accepted"
    assert decided["outcome"]["proposal"]["decided_by"] == "human"
    study = _study(c, sid)
    assert study != walked["study"]
    assert store.design(study).axes == {"efficiency": tuple(MINI_OPTIONS)}
    stages = _stages(c, sid)
    assert stages["design"]["confirmed"] and stages["curves"]["confirmed"]  # never re-opened
    assert not stages["choices"]["confirmed"] and stages["choices"]["pending"] == 0
    view = c.get(f"/api/studies/{study}/results").json()
    (axis,) = view["axes"]
    result = store.get(study)
    assert axis["status"] == result.facts["f_axis_efficiency"].value == "screened_out"
    assert axis["card_id"] is None  # screened out: no card, the grid is as before
    assert {o["id"]: o["tested"] for o in axis["options"]} == {
        "linregpcr": True,
        "per_well": True,
        "amplicon_mean": False,
        "assumed_2": True,
        "standard_curve": True,
    }
    by_id = {o["id"]: o for o in axis["options"]}
    assert "one run" in by_id["amplicon_mean"]["unavailable"]
    assert by_id["per_well"]["flips"]["id"] == "f_screen_efficiency_flips_per_well"
    assert by_id["per_well"]["flips"]["value"] == 0
    cited = {f["id"] for f in axis["text"]["facts"]}
    assert cited == {"f_screen_efficiency_dlog2fc"}
    assert all(f["id"] in result.facts for n in axis["notes"] for f in n["facts"])
    assert {c["card"]["kind"] for c in c.get(f"/api/studies/{study}/cards").json()["cards"]} == {
        k["card"]["kind"] for k in c.get(f"/api/studies/{walked['study']}/cards").json()["cards"]
    }


def test_testing_twice_or_nothing_is_refused_in_words(walked):
    c, sid = walked["client"], walked["sid"]
    r = c.post(f"/api/sessions/{sid}/propose/axis", json={"on": False})
    assert r.status_code == 409 and "not tested" in r.json()["error"]["message"]
    _accept(c, sid, _propose(c, sid)["outcome"]["proposal"]["id"])
    r = c.post(f"/api/sessions/{sid}/propose/axis", json={"axis": "efficiency"})
    assert r.status_code == 409 and "already tested" in r.json()["error"]["message"]
    r = c.post(f"/api/sessions/{sid}/propose/axis", json={"axis": "refs"})
    assert r.status_code == 422


def test_switching_off_gives_back_the_study_with_its_decisions(walked):
    c, sid = walked["client"], walked["sid"]
    first = walked["study"]
    cards = c.get(f"/api/studies/{first}/cards").json()
    card = next(k for k in cards["cards"] if any(not o["recommended"] for o in k["options"]))
    option = next(o["id"] for o in card["options"] if not o["recommended"])
    r = c.post(
        f"/api/studies/{first}/cards/{card['card']['id']}/decide",
        json={"option": option, "reason": "prespecified", "expected_head": cards["head"]},
    )
    assert r.status_code == 200, r.text
    _accept(c, sid, _propose(c, sid)["outcome"]["proposal"]["id"])
    tested = _study(c, sid)
    assert tested != first
    assert c.get(f"/api/studies/{tested}/results").json()["choices"].get(card["card"]["id"]) in (
        None,
        card["card"]["recommended"],
    )
    off = _propose(c, sid, on=False)["outcome"]["proposal"]
    assert off["payload"] == {"options": ["linregpcr"]}
    _accept(c, sid, off["id"], "back to the planned grid")
    assert _study(c, sid) == first
    assert c.get(f"/api/studies/{first}/results").json()["choices"][card["card"]["id"]] == option
    assert c.get(f"/api/studies/{first}/results").json()["axes"][0]["status"] == "off"


def test_the_record_holds_the_choice_and_reruns_it(walked, tmp_path):
    c, sid, store = walked["client"], walked["sid"], walked["store"]
    proposal = _propose(c, sid)["outcome"]["proposal"]
    _accept(c, sid, proposal["id"], "test the efficiency models")
    study = _study(c, sid)
    info = write_record(store, study, tmp_path / "record")
    record = tmp_path / "record"
    report = verify(record)
    assert report.ok, report
    assert report.has_proposals and report.proposal_chain_broken_at is None
    lines = (record / "proposals.jsonl").read_text().splitlines()
    assert any(proposal["id"] in line and '"accept"' in line for line in lines)
    assert '"axes":{"efficiency":' in (record / "study_design.json").read_text()
    again = rerun_compare(record, tmp_path / "rerun")
    assert again.same, again
    assert info.input_included


def test_an_agent_can_propose_it_but_only_a_person_accepts_it(walked):
    from qpilot.mcp_server import QpilotTools

    c, sid, store = walked["client"], walked["sid"], walked["store"]
    tools = QpilotTools(store)
    out = tools.qpcr_propose(
        sid, "choice.axis", "efficiency", {"options": ["linregpcr", "assumed_2"]}
    )
    assert out.get("status") == "proposed", out
    pid = out["proposal"]["id"]
    with pytest.raises(ProposalError, match="only a person"):
        store.proposals(sid).accept(pid, "agent", "I decide")
    pending = c.get(f"/api/sessions/{sid}/proposals", params={"stage": "choices"}).json()
    agent = [p for p in pending["proposals"] if p["made_by"]["kind"] == "agent"]
    assert agent and agent[0]["check"]["status"] == "consistent"
    assert _stages(c, sid)["choices"]["pending"] == 1


def test_before_the_blind_stages_are_confirmed_it_is_blind(sclient, opened):
    r = sclient.post(f"/api/sessions/{opened}/propose/axis", json={"on": True})
    assert r.status_code == 403 and r.json()["error"]["code"] == "blind"
    r = sclient.get(f"/api/sessions/{opened}/proposals", params={"stage": "choices"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "blind"
