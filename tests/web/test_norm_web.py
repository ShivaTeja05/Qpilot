"""The reference panel's route and the new further choices, over HTTP on the walked mini session.

The mini file has one reference gene and one gene per plate: NormFinder cannot rank one
candidate, no other normaliser applies and no correction between plates can change anything. The
page and the MCP tools say so in words instead of proposing a choice that cannot be what it says.
"""

from __future__ import annotations

from qpilot.mcp_server import QpilotTools


def test_references_say_why_normfinder_cannot_rank_one_candidate(walked):
    c, study = walked["client"], walked["study"]
    r = c.get(f"/api/studies/{study}/references")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["study_id"] == study and body["candidates"] == ["GAPDH"]
    assert body["verdict"] == "not_available"
    assert "at least 3 candidate control genes" in body["words"]
    assert body["normfinder_pair"] is None and body["rows"][0]["normfinder"] is None
    assert body["rows"][0]["used"] is True
    assert "your choice" in body["choice_note"]
    assert any("Andersen" in s for s in body["sources"])


def test_references_of_an_unknown_study_is_not_found(walked):
    r = walked["client"].get("/api/studies/0123456789ab/references")
    assert r.status_code == 404


def test_results_list_every_further_choice(walked):
    c, study = walked["client"], walked["study"]
    axes = c.get(f"/api/studies/{study}/results").json()["axes"]
    assert [a["name"] for a in axes] == ["efficiency", "normaliser", "interrun"]
    norm = axes[1]
    assert norm["status"] == "off" and norm["can_propose"]
    assert norm["title"] == "What to normalise each gene to"
    assert [o["id"] for o in norm["options"]] == [
        "planned",
        "normfinder_pair",
        "genorm_pair",
        "global_mean",
    ]
    assert "reference genes chosen" in norm["text"]["plain"]


def test_the_rule_does_not_propose_a_normaliser_that_cannot_apply(walked):
    c, sid = walked["client"], walked["sid"]
    r = c.post(f"/api/sessions/{sid}/propose/axis", json={"axis": "normaliser", "on": True})
    assert r.status_code == 409, r.text
    message = r.json()["error"]["message"]
    assert "No other option of this choice applies" in message
    assert "global_mean: only 2 genes are measured" in message
    assert "at least 3" in message  # NormFinder's pair: one reference gene


def test_the_rule_does_not_propose_a_plate_correction_that_cannot_change_anything(walked):
    c, sid = walked["client"], walked["sid"]
    r = c.post(f"/api/sessions/{sid}/propose/axis", json={"axis": "interrun", "on": True})
    assert r.status_code == 409, r.text
    assert "cancels in every fold change" in r.json()["error"]["message"]
    bad = c.post(f"/api/sessions/{sid}/propose/axis", json={"axis": "plates", "on": True})
    assert bad.status_code == 422  # not one of the further choices


def test_an_agent_may_propose_the_new_axes_and_d_axis_refutes_them(walked):
    tools = QpilotTools(walked["store"])
    sid = walked["sid"]
    for subject, options, why in (
        ("normaliser", ["planned", "global_mean"], "too few genes"),
        ("interrun", ["none", "factor"], "cancels in every fold change"),
    ):
        out = tools.qpcr_propose(sid, "choice.axis", subject, {"options": options})
        assert out["status"] == "proposed", out
        check = out["proposal"]["check"]
        assert check["status"] == "contradicted" and check["rule_ids"] == ["D-AXIS"]
        assert why in check["note"]
    refused = tools.qpcr_propose(sid, "choice.axis", "normaliser", {"options": ["global_mean"]})
    assert refused["status"] == "proposed"
    assert refused["proposal"]["check"]["status"] == "contradicted"  # not the axis's own order
