"""GET /api/agents over a real store: the connect line, the tools, requests and agent activity.

The study is the demo's analysed result as the engine produced it (``tests/fixtures``); agents act
on it through the MCP tool code itself (:class:`qpilot.mcp_server.QpilotTools`), as in real use.
"""

from __future__ import annotations

import pytest

from qpilot.ai.explain import KIND_TITLE
from qpilot.core.store import StudyStore
from qpilot.mcp_server import TOOL_NAMES, QpilotTools, served_tool_names
from qpilot.web.routers.ops import CONNECT, TOOL_ACCESS

CAP_REASON = "Empty wells should count as very low expression, not be dropped."


@pytest.fixture
def study(web_store: StudyStore, fixture_result, fixture_cards) -> str:
    web_store.put(fixture_result, fixture_cards)
    return fixture_result.study_id


def test_every_tool_qpilot_serve_registers_says_what_it_can_change():
    for name in TOOL_NAMES:
        assert name in TOOL_ACCESS, f"{name}: add it to ops.TOOL_ACCESS"
    for name in served_tool_names():
        assert name in TOOL_ACCESS or name.startswith("sim_"), name
    assert {TOOL_ACCESS[n][0] for n in TOOL_NAMES} == {"read", "open", "propose", "request"}
    assert TOOL_ACCESS["qpcr_decide"][0] == "request"
    assert TOOL_ACCESS["qpcr_propose"][0] == "propose"


def test_an_empty_store_shows_how_to_connect_and_the_tools(client, web_store, monkeypatch):
    monkeypatch.setenv("QPILOT_STUDIES_DIR", str(web_store.root))
    body = client.get("/api/agents").json()
    assert body["connect"] == CONNECT and body["store_note"] is None
    assert [t["name"] for t in body["tools"]] == list(served_tool_names())
    assert body["simulator"] == (len(body["tools"]) > len(TOOL_NAMES))
    by_name = {t["name"]: t for t in body["tools"]}
    decide = by_name["qpcr_decide"]
    assert decide["access"] == "request" and decide["summary"].startswith("Ask to decide")
    assert "pending_human" in decide["description"]  # the agent's own description, as text
    assert all(t["access"] == "read" for t in body["tools"] if t["simulator"])
    assert body["pending"] == [] and body["activity"] == [] and body["activity_total"] == 0
    assert any("always waits for a person" in r for r in body["rules"])


def test_another_store_is_named_in_the_connect_command(client, web_store, monkeypatch):
    monkeypatch.delenv("QPILOT_STUDIES_DIR")
    body = client.get("/api/agents").json()
    assert body["connect"].startswith("claude mcp add qpilot -e QPILOT_STUDIES_DIR=")
    assert str(web_store.root) in body["connect"] and body["connect"].endswith("qpilot serve")
    assert body["store_note"]


def test_an_agents_request_waits_for_a_person_and_is_listed(client, web_store, study):
    tools = QpilotTools(web_store)
    out = tools.qpcr_decide(study, "card_refset", "hmbs_alone", "HMBS alone is enough.")
    assert out["status"] == "pending_human"
    out = tools.qpcr_decide(study, "card_undetermined", "cap", CAP_REASON)
    assert out["status"] == "pending_human"  # Suggest: even this choice waits for a person

    body = client.get("/api/agents").json()
    pending = body["pending"]
    assert [(p["card_id"], p["option"]) for p in pending] == [
        ("card_refset", "hmbs_alone"),
        ("card_undetermined", "cap"),
    ]
    first, second = pending
    assert first["card_title"] == KIND_TITLE["reference_set"]
    assert first["option_label"] == next(
        o.label for o in web_store.card(study, "card_refset").options if o.id == "hmbs_alone"
    )
    assert first["can_change_a_conclusion"] is True
    assert second["can_change_a_conclusion"] is False  # waits only because of Suggest mode
    assert second["reason"] == CAP_REASON and second["actor"] == "agent"
    assert {p["key"] for p in pending} == {study} and {p["kind"] for p in pending} == {"study"}
    assert all(p["expected_head"] == web_store.chain_head(study) for p in pending)

    activity = body["activity"]
    assert [a["kind"] for a in activity] == ["decision", "decision"]
    assert all(a["status"] == "pending_human" for a in activity)
    assert activity[0]["at"] >= activity[1]["at"]  # newest first
    assert "Asked a person to set" in activity[0]["summary"]


def test_a_person_turning_it_down_empties_the_queue_but_keeps_the_history(client, web_store, study):
    QpilotTools(web_store).qpcr_decide(study, "card_undetermined", "cap", CAP_REASON)
    head = client.get("/api/agents").json()["pending"][0]["expected_head"]
    web_store.reject_pending(study, "card_undetermined", "Keep dropping them.", head)
    body = client.get("/api/agents").json()
    assert body["pending"] == []
    assert [a["status"] for a in body["activity"]] == ["pending_human"]  # people are not listed


def test_a_stale_request_is_listed_as_not_applied(client, web_store, study):
    tools = QpilotTools(web_store)
    old = web_store.chain_head(study)  # what the agent read
    web_store.append_decision(
        study, "card_refset", "top3", "Three genes are steadier.", "human", old
    )
    out = tools.qpcr_decide(study, "card_refset", "hmbs_alone", "Use HMBS.", expected_head=old)
    assert out["status"] == "stale"
    body = client.get("/api/agents").json()
    stale = [a for a in body["activity"] if a["status"] == "stale"]
    assert len(stale) == 1 and stale[0]["option"] == "hmbs_alone"
    assert "card changed" in stale[0]["summary"]


def test_decide_and_tell_entries_show_what_the_agent_applied(client, web_store, study):
    web_store.set_autonomy(study, "decide_and_tell")
    out = QpilotTools(web_store).qpcr_decide(study, "card_undetermined", "cap", CAP_REASON)
    assert out["status"] == "applied"
    body = client.get("/api/agents").json()
    assert body["pending"] == []
    (entry,) = body["activity"]
    assert entry["status"] == "applied" and entry["summary"].startswith("Set “")


def test_an_agents_proposal_in_a_blind_session_is_listed_without_results(
    sclient, web_store, opened
):
    tools = QpilotTools(web_store)
    out = tools.qpcr_propose(opened, "design.group", "WT_1", {"group": "WT"})
    assert out["status"] == "proposed", out
    body = sclient.get("/api/agents").json()
    (entry,) = (a for a in body["activity"] if a["kind"] == "proposal")
    assert entry["key"] == opened and entry["workspace_kind"] == "session"
    assert entry["proposal_kind"] == "design.group" and entry["status"] == "proposed"
    assert entry["check"] in ("consistent", "contradicted", "cannot_check")
    assert "WT_1" in entry["summary"]


def test_agents_needs_the_launch_key(raw_client):
    assert raw_client.get("/api/agents").status_code == 401
