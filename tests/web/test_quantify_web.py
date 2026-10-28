"""A quantification run (no groups compared) taken to Results through the page's routes.

Two real labs' exports (:mod:`tests.web.quantify_walk`): the StepOne RDML file, where the rules
propose the purpose and a person accepts it, and the QuantStudio 3 wastewater export, where a
person sets the purpose and the standards' series on the Design page. No model. Then Results
(Quantities, the quantity cards), Controls, the report, the record and the MCP tool.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from qpilot.core.store import StudyStore
from qpilot.mcp_server import QpilotTools
from qpilot.web.context import make_context
from qpilot.web.server import create_app
from tests.web import quantify_walk as qw
from tests.web.conftest import BASE, TOKEN, wait_job


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> Iterator[dict]:
    base = tmp_path_factory.mktemp("quantify")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("QPILOT_MODEL_PROVIDER", "none")
        mp.setenv("QPILOT_STUDIES_DIR", str(base / "studies"))
        store = StudyStore(base / "studies")
        ctx = make_context(store, token=TOKEN, watch=False)
        with TestClient(create_app(ctx), base_url=BASE) as client:
            client.headers["x-qpilot-token"] = TOKEN
            yield {"client": client, "store": store, "ctx": ctx, "base": base}
        ctx.close()


@pytest.fixture(scope="module")
def stepone(world) -> dict:
    client = world["client"]
    sid = qw.open_stepone(client)
    listed = client.get(f"/api/sessions/{sid}/proposals", params={"stage": "design"}).json()
    purpose = [p for p in listed["proposals"] if p["kind"] == "design.purpose"]
    editor = client.get(f"/api/sessions/{sid}/design/editor").json()
    return {"sid": sid, "purpose": purpose, "editor": editor}


@pytest.fixture(scope="module")
def stepone_study(world, stepone) -> dict:
    return qw.walk_stepone(world["client"], stepone["sid"])


@pytest.fixture(scope="module")
def qs3(world) -> dict:
    client = world["client"]
    sid = qw.open_qs3(client)
    before = client.get(f"/api/sessions/{sid}/design/editor").json()
    qw._set(client, sid, qw.qs3_items(client, sid), "standards from the lab notebook")
    after = client.get(f"/api/sessions/{sid}/design/editor").json()
    out = qw.finish(client, sid)
    return {**out, "before": before, "after": after}


def test_the_rules_propose_quantify_for_the_stepone_file(stepone):
    (purpose,) = stepone["purpose"]
    assert purpose["payload"] == {"purpose": "quantify"} and purpose["made_by"]["kind"] == "rule"
    assert purpose["check"]["status"] == "cannot_check"  # never in "Accept all consistent"
    assert purpose["check"]["rule_ids"] == ["D-PURPOSE"]
    editor = stepone["editor"]
    assert editor["purpose"] == "compare" and editor["n_standards"] == 5
    assert editor["n_standards_with_quantity"] == 5
    assert [o["value"] for o in editor["purposes"]] == ["compare", "quantify"]
    assert "fold" not in str(editor).lower()  # blind words


def test_stepone_reaches_results_as_a_quantification(world, stepone_study):
    c, sid, study = world["client"], stepone_study["sid"], stepone_study["study"]
    ws = c.get(f"/api/sessions/{sid}").json()
    assert ws["purpose"] == "quantify" and ws["results_visible"]
    view = c.get(f"/api/studies/{study}/quantities").json()
    assert view["purpose"] == "quantify" and view["available"]
    assert view["analysis"][0].startswith("Wells count as detected by LinRegPCR")
    (assay,) = view["assays"]
    assert assay["target"] == "RNase P" and assay["by_class"] == {"quantified": 2}
    detail = c.get(f"/api/studies/{study}/quantities/RNase P").json()
    assert {u["reported"] for u in detail["units"]} == {"quantified"}
    assert all(u["group"] is None for u in detail["units"])  # no groups: no group column
    assert not view["groups_shown"]
    cards = c.get(f"/api/studies/{study}/cards").json()["cards"]
    assert {v["card"]["kind"] for v in cards} == {"quantity.amp_call", "quantity.loq_cv"}
    assert all(v["card"]["status"] == "auto_decided" for v in cards)
    results = c.get(f"/api/studies/{study}/results")
    assert results.status_code == 200 and results.json()["genes"] == []


def test_the_qs3_editor_needs_standards_not_a_comparison(qs3):
    before, after = qs3["before"], qs3["after"]
    assert {n["code"] for n in before["needs"]} >= {"reference", "groups"}
    assert after["purpose"] == "quantify"
    assert not {"reference", "groups", "comparison", "gene"} & {n["code"] for n in after["needs"]}
    assert after["n_standards"] == 5 and after["n_standards_with_quantity"] == 5


def test_the_qs3_card_waits_for_a_person_and_lists_what_changes(world, qs3):
    c, study = world["client"], qs3["study"]
    cards = {v["card"]["kind"]: v for v in c.get(f"/api/studies/{study}/cards").json()["cards"]}
    amp = cards["quantity.amp_call"]
    assert amp["card"]["status"] == "open" and amp["needs_human"]
    assert amp["impact"]["plain"] == "9 of 54 sample results change with this choice"
    options = {o["id"]: o for o in amp["options"]}
    late = options["cq_le_35"]
    assert late["n_quantities_changed"] == 9 and late["not_recommended"]
    moved = {(q["class_from"], q["class_to"]) for q in late["quantities"]}
    assert ("quantified", "below_lod") in moved  # the 10-copy standard drops off the curve
    for q in late["quantities"]:  # another class, or a number more than 2-fold away
        same = q["class_from"] == q["class_to"]
        assert not same or max(q["quantity_from"], q["quantity_to"]) > 2 * min(
            q["quantity_from"], q["quantity_to"]
        )
    assert sum(q["class_from"] == "quantified" for q in late["quantities"]) >= 6
    assert options["linregpcr"]["n_quantities_changed"] == 0
    assert cards["quantity.loq_cv"]["card"]["status"] == "auto_decided"
    # an agent cannot make it: the escalation rule reads the card's impact
    tools = QpilotTools(world["store"])
    asked = tools.qpcr_decide(study, amp["card"]["id"], "cq_le_35", "the lab's usual cut-off")
    assert asked.get("status") == "pending_human" or asked.get("code") == "needs_human_decision"


def test_a_persons_choice_is_the_analysis_in_use(world, qs3):
    c, study, sid = world["client"], qs3["study"], qs3["sid"]
    head = c.get(f"/api/studies/{study}/cards").json()["head"]
    card = "card_quantity_amp_call"
    r = c.post(
        f"/api/studies/{study}/cards/{card}/decide",
        json={"option": "cq_le_35", "reason": "the lab reports Cq > 35 as not detected",
              "expected_head": head},
    )  # fmt: skip
    assert r.status_code == 200, r.text
    view = c.get(f"/api/studies/{study}/quantities").json()
    assert "Cq ≤ 35" in view["analysis"][0] and "A person chose" in view["analysis"][-1]
    cov2 = next(a for a in view["assays"] if a["target"] == "Cov2")
    assert cov2["by_class"].get("below_lod", 0) >= 6
    head = c.get(f"/api/studies/{study}/cards").json()["head"]
    back = c.post(
        f"/api/studies/{study}/cards/{card}/decide",
        json={"option": "linregpcr", "reason": "a 10-copy standard comes up after cycle 35",
              "expected_head": head},
    )  # fmt: skip
    assert back.status_code == 200, back.text
    view = c.get(f"/api/studies/{study}/quantities").json()
    assert "LinRegPCR" in view["analysis"][0]
    ws = c.get(f"/api/sessions/{sid}").json()
    assert ws["next_step"]["section"] == "results"  # confirm the choices next


def test_controls_ask_whether_a_quantity_changes(world, qs3):
    c, study = world["client"], qs3["study"]
    r = c.get(f"/api/studies/{study}/gate")
    if r.status_code == 409:
        wait_job(c, r.json()["error"]["details"]["job"])
        r = c.get(f"/api/studies/{study}/gate")
    assert r.status_code == 200, r.text
    gate = r.json()
    by_rule = {(e["rule_id"], e["target"], e["verdict"]) for e in gate["evaluations"]}
    assert ("G-STD", "PMMoV", "fail") in by_rule  # efficiency 124 % with the person's series
    std = next(e for e in gate["evaluations"] if e["rule_id"] == "G-STD")
    assert "every quantity of this assay" in std["reason"]["plain"]
    (consequence,) = gate["consequences"]
    words = " ".join(o["text"]["plain"] for o in consequence["options"])
    assert "what is reported for 1 sample result" in words and "call" not in words
    assert gate["cards"] and gate["cards"][0]["card"]["impact"]["flips"]


def test_the_report_speaks_of_quantities(world, qs3):
    c, study = world["client"], qs3["study"]
    report = c.get(f"/api/studies/{study}/report").json()
    assert report["header"]["title"].startswith("A quantification")
    summary = report["summary"]["plain"]
    assert "no groups are compared" in summary and "quantified" in summary
    ids = [p["id"] for p in report["methods"]["paragraphs"]]
    assert "quantities" in ids and "quantity_choices" in ids and "comparison" not in ids
    assert {x["id"] for x in report["limitations"]} >= {"standards", "limits", "matrix"}


def test_the_mcp_tool_reads_the_quantities(world, qs3):
    tools = QpilotTools(world["store"])
    out = tools.qpcr_quantities(qs3["study"])
    assert out["purpose"] == "quantify" and {a["target"] for a in out["assays"]} == {
        "Cov2",
        "PMMoV",
    }
    one = tools.qpcr_quantities(qs3["study"], target="cov2", response_format="concise")
    assert one["target"] == "Cov2" and len(one["units"]) == 27
    assert "wells" not in one["units"][0] and one["units"][0]["reported"]
    bad = tools.qpcr_quantities(qs3["study"], target="ACTB")
    assert bad["code"] == "invalid_argument"


def test_compare_only_sections_answer_plainly(world, qs3):
    c, study = world["client"], qs3["study"]
    evidence = c.get(f"/api/studies/{study}/evidence").json()
    assert not evidence["available"] and "quantifies samples" in evidence["note"]
    r = c.post(f"/api/sessions/{qs3['sid']}/propose/axis", json={"axis": "efficiency"})
    assert r.status_code in (409, 422) and "quantifies samples" in r.text
    for url in (f"/api/studies/{study}/trace", f"/api/studies/{study}/audit"):
        r = c.get(url)
        assert r.status_code == 409 and r.json()["error"]["code"] == "quantify", (url, r.text)
        assert "compares no groups" in r.json()["error"]["message"]
