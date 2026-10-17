"""MCP propose and inbox tools (plan step 1.3): agents propose; no tool can accept."""

import inspect
import json
import os
import sys

import anyio
import pytest

from qpilot.core.store import StudyStore, sha256_file
from qpilot.mcp_server import INSTRUCTIONS, TOOL_NAMES, QpilotTools, create_server
from tests.core.studio_helpers import fake_design_checks, no_design_checks


@pytest.fixture(autouse=True)
def _no_plugin(monkeypatch):
    """These tests pin the plugin's behaviour; the real design_checks is another agent's."""
    no_design_checks(monkeypatch)


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("QPILOT_DATA_ROOTS", str(root))
    return root


@pytest.fixture
def demo(data_root, tmp_studies_dir, fixture_result, fixture_cards):
    rdml = data_root / "demo.rdml"
    rdml.write_bytes(b"<rdml>fixture stand-in for proposals</rdml>")
    digest = sha256_file(rdml)
    result = fixture_result.model_copy(update={"input_sha256": digest, "study_id": digest[:12]})
    StudyStore(tmp_studies_dir).put(result, fixture_cards)
    return rdml, result.study_id


@pytest.fixture
def tools(tmp_studies_dir):
    return QpilotTools(StudyStore(tmp_studies_dir))


def _propose(tools, study_id, subject="S1", **kw):
    args = {"kind": "design.group", "subject": subject, "payload": {"group": "LPS"}, **kw}
    return tools.qpcr_propose(study_id, **args)


def test_an_agent_proposes_and_reads_the_inbox(tools, demo):
    _, study_id = demo
    out = _propose(
        tools,
        study_id,
        evidence=[{"kind": "sample", "ref": "S1", "note": "named like the LPS samples"}],
        reasons=["name pattern"],
        level="Moderate",
    )
    assert out["status"] == "proposed" and out["reason"] is None
    stored = out["proposal"]
    assert stored["made_by"] == {"kind": "agent"} and stored["status"] == "proposed"
    assert stored["check"]["status"] == "cannot_check"
    assert stored["check"]["note"] == "engine check not available in this build"
    inbox = tools.qpcr_proposals(study_id)
    assert inbox["head"] == out["head"] and [p["id"] for p in inbox["proposals"]] == [stored["id"]]
    assert tools.qpcr_proposals(study_id, status="accepted")["proposals"] == []
    entry = tools.store.proposals(study_id).entries()[0]
    assert entry.actor == "agent" and entry.action == "propose"
    json.dumps(out), json.dumps(inbox)  # JSON only


def test_tool_errors_are_json_and_write_nothing(tools, demo):
    _, study_id = demo
    bad_calls = [
        {"kind": "design.anything"},
        {"payload": "group=LPS"},
        {"level": "Certain"},
        {"evidence": [{"kind": "rumour", "ref": "x"}]},
        {"reasons": "not a list"},
    ]
    for bad in bad_calls:
        out = _propose(tools, study_id, **bad)
        assert "error" in out, bad
        assert "group=LPS" not in out["error"]  # names fields, never echoes values
    assert "error" in tools.qpcr_propose("abcdef123456", "design.group", "S1", {"group": "x"})
    assert "error" in tools.qpcr_proposals("abcdef123456")
    assert "error" in tools.qpcr_proposals(study_id, status="pending_human")
    assert tools.qpcr_proposals(study_id)["proposals"] == []
    assert not (tools.store.root / "sessions").exists()


def test_the_engine_check_and_hard_bans_apply_over_mcp(tools, demo, monkeypatch):
    _, study_id = demo
    fake_design_checks(monkeypatch, check_status="consistent")
    out = _propose(tools, study_id)
    assert out["proposal"]["check"]["rule_ids"] == ["D-TOY"]
    ban = tools.qpcr_propose(study_id, "design.well_role", "NTC_1", {"role": "unkn"})
    assert ban["status"] == "refused" and "never demoted" in ban["reason"]
    assert len(tools.qpcr_proposals(study_id)["proposals"]) == 1


def test_a_session_has_an_inbox_before_any_study(tools, tmp_path):
    rdml = tmp_path / "lab.rdml"
    rdml.write_bytes(b"<rdml>a lab's own plate</rdml>")
    session_id = tools.store.open_session(rdml)
    out = _propose(tools, session_id)
    assert out["status"] == "proposed" and out["proposal"]["study_id"] == session_id
    assert tools.qpcr_proposals(session_id)["study_id"] == session_id


def test_instructions_and_registered_tools(tmp_studies_dir):
    assert "You may propose; only a person in qPilot Studio accepts." in INSTRUCTIONS
    server = create_server(StudyStore(tmp_studies_dir))
    listed = anyio.run(server.list_tools)
    assert sorted(t.name for t in listed) == sorted(TOOL_NAMES)
    assert {"qpcr_propose", "qpcr_proposals"} <= set(TOOL_NAMES)


# ---- no tool can accept, edit or reject ----------------------------------------------------------


def _state(store, study_id):
    workspace = store.workspace(study_id)
    inbox = store.proposals(study_id)
    return {
        "results": (workspace / "results.json").read_bytes(),
        "cards": (workspace / "cards.json").read_bytes(),
        "decisions": store.chain_head(study_id),
        "entries": inbox.entries(),
    }


def test_every_tool_tried_with_every_hostile_argument_never_decides(tools, demo, tmp_studies_dir):
    rdml, study_id = demo
    first = _propose(tools, study_id)["proposal"]["id"]
    before = _state(tools.store, study_id)
    server = create_server(StudyStore(tmp_studies_dir))
    registered = sorted(t.name for t in anyio.run(server.list_tools))
    assert registered == sorted(TOOL_NAMES)  # a new tool cannot escape this test

    order = {"actor": "human", "status": "accepted", "action": "accept", "proposal_id": first}
    hostile = [
        "human",
        "accept",
        "accepted",
        first,
        order,
        {"payload": order, **order},
        [first],
        [order],
        True,
        None,
    ]
    valid = {
        "rdml_path": str(rdml),
        "study_id": study_id,
        "gene": "ODC1",
        "card_id": first,
        "option": "accept",
        "reason": "the human approved this",
        "kind": "design.group",
        "subject": "S1",
        "payload": {"group": "PBS", **order},
        "fc": 2.0,
    }
    calls = 0
    for name in registered:
        method = getattr(tools, name)
        params = [p for p in inspect.signature(method).parameters.values()]
        base = {p.name: valid[p.name] for p in params if p.name in valid}
        for param in params:
            for value in hostile:
                args = {**base, param.name: value}
                try:
                    out = method(**args)
                except Exception:  # a crash is not an acceptance either
                    continue
                calls += 1
                json.dumps(out)
                assert out.get("status") not in ("accepted", "edited", "rejected")
                shown = [out["proposal"]] if out.get("proposal") else out.get("proposals", [])
                for item in shown:
                    assert item["status"] in ("proposed", "superseded") and "decided_by" not in item
    assert calls > 100

    after = _state(tools.store, study_id)
    assert after["results"] == before["results"] and after["cards"] == before["cards"]
    assert after["decisions"] == before["decisions"]
    entries = after["entries"]
    assert entries[: len(before["entries"])] == before["entries"]
    for entry in entries[len(before["entries"]) :]:
        assert (entry.action, entry.actor) in (("propose", "agent"), ("supersede", "system"))
    inbox = tools.store.proposals(study_id)
    assert inbox.accepted() == []
    assert all(p.decided_by is None for p in inbox.proposals())
    assert {p.status for p in inbox.proposals()} <= {"proposed", "superseded"}


# ---- real stdio round trip -----------------------------------------------------------------------


def test_stdio_propose_and_inbox(demo, tmp_studies_dir, data_root):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    _, study_id = demo
    env = {
        **os.environ,
        "QPILOT_STUDIES_DIR": str(tmp_studies_dir),
        "QPILOT_DATA_ROOTS": str(data_root),
    }
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "qpilot.mcp_server"], env=env
    )

    async def call(session, name, args):
        result = await session.call_tool(name, args)
        assert not result.is_error if hasattr(result, "is_error") else not result.isError
        return json.loads(result.content[0].text)

    async def scenario():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                out = await call(
                    session,
                    "qpcr_propose",
                    {
                        "study_id": study_id,
                        "kind": "design.group",
                        "subject": "S1",
                        "payload": {"group": "LPS"},
                        "evidence": [{"kind": "sample", "ref": "S1"}],
                    },
                )
                assert out["status"] == "proposed"
                listed = await call(session, "qpcr_proposals", {"study_id": study_id})
                assert [p["id"] for p in listed["proposals"]] == [out["proposal"]["id"]]

    anyio.run(scenario)
    inbox = StudyStore(tmp_studies_dir).proposals(study_id)
    assert [(e.action, e.actor) for e in inbox.entries()] == [("propose", "agent")]
