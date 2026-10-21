"""MCP tools: direct calls, path policy, and a real stdio round trip in a subprocess."""

import json
import os
import sys

import anyio
import pytest

from qpilot.core.decisions import apply_decision
from qpilot.core.store import StudyStore, sha256_file
from qpilot.mcp_server import (
    SIM_OFF_NOTICE,
    TOOL_NAMES,
    QpilotTools,
    check_path,
    create_server,
    served_tool_names,
)


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("QPILOT_DATA_ROOTS", str(root))
    return root


@pytest.fixture
def demo(data_root, tmp_studies_dir, fixture_result, fixture_cards):
    """A fake RDML file inside the data root whose workspace already holds the fixture study."""
    rdml = data_root / "demo.rdml"
    rdml.write_bytes(b"<rdml>fixture stand-in</rdml>")
    digest = sha256_file(rdml)
    result = fixture_result.model_copy(update={"input_sha256": digest, "study_id": digest[:12]})
    StudyStore(tmp_studies_dir).put(result, fixture_cards)
    return rdml, result.study_id


@pytest.fixture
def tools(tmp_studies_dir):
    return QpilotTools(StudyStore(tmp_studies_dir))


def test_study_tool(tools, demo):
    rdml, study_id = demo
    out = tools.qpcr_study(str(rdml))
    assert out["study_id"] == study_id
    assert out["record_root_hash"] == sha256_file(rdml)
    assert out["n_plates"] == 64 and out["n_reactions"] == 24576
    assert out["contrasts"]["ODC1"]["holds"] == 1.0
    assert [c["card_id"] for c in out["open_cards"]] == ["card_refset", "card_cutoff"]
    assert out["open_cards"][0]["needs_human"] is True
    assert [c["card_id"] for c in out["decided_cards"]] == ["card_undetermined"]
    assert "f_n_flipped_refset" in out["facts"]
    json.dumps(out)  # JSON only


def test_robustness_tool(tools, demo):
    _, study_id = demo
    out = tools.qpcr_robustness(study_id, "odc1")
    assert out["gene"] == "ODC1" and out["holds_fraction"] == 1.0 and out["n_cells"] == 186
    assert out["confidence"]["level"] == "Moderate"
    assert out["cards_that_can_flip_it"] == []
    nm23a = tools.qpcr_robustness(study_id, "NM23A")
    assert nm23a["cards_that_can_flip_it"] == ["card_refset", "card_cutoff"]
    assert tools.qpcr_robustness(study_id, "GAPDH")["error"] == "gene not in this study"
    assert "unknown study_id" in tools.qpcr_robustness("abcdef123456", "ODC1")["error"]


def test_decide_tool(tools, demo):
    _, study_id = demo
    out = tools.qpcr_decide(study_id, "card_refset", "hmbs_alone", "try HMBS alone")
    assert out["status"] == "pending_human"
    assert out["card"]["decision"] is None
    stale = tools.qpcr_decide(study_id, "card_undetermined", "cap", "try cap", "agent", "0" * 64)
    assert stale["status"] == "stale"
    # Suggest (the default): even a choice that changes nothing waits for a person
    asked = tools.qpcr_decide(
        study_id, "card_undetermined", "cap", "try cap", "agent", stale["chain_head"]
    )
    assert asked["status"] == "pending_human" and "Suggest mode" in asked["reason"]
    tools.store.set_autonomy(study_id, "decide_and_tell")
    applied = tools.qpcr_decide(study_id, "card_undetermined", "cap", "try cap")
    assert applied["status"] == "applied" and applied["card"]["decided_by"] == "agent"


def test_mcp_caller_cannot_claim_to_be_human(tools, demo):
    _, study_id = demo
    out = tools.qpcr_decide(study_id, "card_refset", "hmbs_alone", "trust me", actor="human")
    assert "error" in out
    assert tools.store.card(study_id, "card_refset").status == "open"


def test_decide_errors(tools, demo):
    _, study_id = demo
    assert "unknown option" in tools.qpcr_decide(study_id, "card_refset", "zz", "x")["error"]
    assert "reason" in tools.qpcr_decide(study_id, "card_refset", "top2", "")["error"]
    assert "unknown card" in tools.qpcr_decide(study_id, "card_zz", "top2", "x")["error"]


def test_plan_tool(tools):
    out = tools.qpcr_plan(fc=2, sd_log2=1.95, n_per_group=3)
    assert out["n_needed"] == 61 and out["mde_fold"] == pytest.approx(22.0, rel=0.03)
    assert "error" in tools.qpcr_plan(fc=1)


# ---- path policy -------------------------------------------------------------------------


def test_path_inside_root_allowed(demo):
    rdml, _ = demo
    assert check_path(str(rdml)) == rdml.resolve()


def test_sibling_prefix_refused(tmp_path, data_root):
    evil = tmp_path / "data-evil"
    evil.mkdir()
    (evil / "x.rdml").write_text("x")
    with pytest.raises(PermissionError, match="outside"):
        check_path(str(evil / "x.rdml"))


def test_symlink_out_refused(tmp_path, data_root):
    outside = tmp_path / "secret.rdml"
    outside.write_text("secret")
    link = data_root / "link.rdml"
    link.symlink_to(outside)
    with pytest.raises(PermissionError, match="outside"):
        check_path(str(link))


def test_dotdot_and_missing_refused(data_root):
    with pytest.raises(PermissionError):
        check_path(str(data_root / ".." / "data" / ".." / "nope.rdml"))
    with pytest.raises(PermissionError, match="not found"):
        check_path(str(data_root / "missing.rdml"))


def test_non_rdml_refused(data_root):
    other = data_root / "notes.txt"
    other.write_text("x")
    with pytest.raises(PermissionError, match="rdml"):
        check_path(str(other))
    with pytest.raises(PermissionError):
        check_path(str(data_root))


def test_study_tool_reports_policy_error(tools, tmp_path, data_root):
    (tmp_path / "x.rdml").write_text("x")
    out = tools.qpcr_study(str(tmp_path / "x.rdml"))
    assert out["error"] == "path outside QPILOT_DATA_ROOTS"
    assert (out["code"], out["field"]) == ("path_not_allowed", "rdml_path")


def test_server_registers_every_served_tool(tmp_studies_dir):
    server = create_server(StudyStore(tmp_studies_dir))
    tools = anyio.run(server.list_tools)
    assert sorted(t.name for t in tools) == sorted(served_tool_names())
    assert set(TOOL_NAMES) <= {t.name for t in tools}


def test_the_simulator_tools_follow_the_simulator(tmp_studies_dir, monkeypatch):
    """Without qsim the server lists the eleven qpcr_* tools and nothing breaks; with it, sim_*."""
    from qpilot.integration import simulator as sim
    from qpilot.integration.mcp_tools import SIM_TOOL_NAMES

    monkeypatch.setattr(sim, "available", lambda: False)
    assert served_tool_names() == TOOL_NAMES
    off = anyio.run(create_server(StudyStore(tmp_studies_dir)).list_tools)
    assert sorted(t.name for t in off) == sorted(TOOL_NAMES)
    monkeypatch.setattr(sim, "available", lambda: True)
    assert served_tool_names() == TOOL_NAMES + SIM_TOOL_NAMES
    on = anyio.run(create_server(StudyStore(tmp_studies_dir)).list_tools)
    assert sorted(t.name for t in on) == sorted(TOOL_NAMES + SIM_TOOL_NAMES)
    assert served_tool_names(simulator=False) == TOOL_NAMES
    assert "sim_*" in SIM_OFF_NOTICE and "--list-tools" in SIM_OFF_NOTICE


def test_serve_list_tools_prints_what_is_served(capsys, monkeypatch):
    from qpilot.cli import main
    from qpilot.integration import simulator as sim

    monkeypatch.setattr(sim, "available", lambda: False)
    assert main(["serve", "--list-tools"]) == 0
    out = capsys.readouterr()
    assert out.out.split() == list(TOOL_NAMES)
    assert "11 tools" in out.err and "not installed" in out.err


# ---- real stdio round trip ---------------------------------------------------------------


def test_stdio_round_trip(demo, tmp_studies_dir, data_root):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    rdml, study_id = demo
    env = {
        **os.environ,
        "QPILOT_STUDIES_DIR": str(tmp_studies_dir),
        "QPILOT_DATA_ROOTS": str(data_root),
    }
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "qpilot.mcp_server"], env=env
    )

    async def call(session, name, args, refused=False):
        result = await session.call_tool(name, args)
        failed = result.is_error if hasattr(result, "is_error") else result.isError
        assert failed is refused
        return json.loads(result.content[0].text)

    async def scenario():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                assert sorted(t.name for t in listed.tools) == sorted(served_tool_names())
                study = await call(session, "qpcr_study", {"rdml_path": str(rdml)})
                assert study["study_id"] == study_id
                robust = await call(
                    session, "qpcr_robustness", {"study_id": study_id, "gene": "ODC1"}
                )
                assert robust["holds_fraction"] == 1.0
                decide = await call(
                    session,
                    "qpcr_decide",
                    {
                        "study_id": study_id,
                        "card_id": "card_refset",
                        "option": "hmbs_alone",
                        "reason": "try",
                    },
                )
                assert decide["status"] == "pending_human"
                # A person decides elsewhere in the meantime, so the agent's head is out of date.
                apply_decision(
                    StudyStore(tmp_studies_dir), study_id, "card_cutoff", "cut_20", "pi", "human"
                )
                stale = await call(
                    session,
                    "qpcr_decide",
                    {
                        "study_id": study_id,
                        "card_id": "card_undetermined",
                        "option": "cap",
                        "reason": "try",
                        "expected_head": study["chain_head"],
                    },
                    refused=True,  # nothing was decided: a refusal with a code and a fix
                )
                assert (stale["status"], stale["code"]) == ("stale", "stale_head")
                assert stale["error"] == stale["reason"] and stale["applied"] is False

    anyio.run(scenario)
    # The agent's request is visible to the app's process through the shared store.
    pending = StudyStore(tmp_studies_dir).pending(study_id)
    assert [(p.card_id, p.actor) for p in pending] == [("card_refset", "agent")]


@pytest.mark.parametrize("card_id", [" card_refset", "CARD_REFSET"])
def test_an_unknown_card_is_named_exactly(tmp_studies_dir, fixture_result, fixture_cards, card_id):
    store = StudyStore(tmp_studies_dir)
    store.put(fixture_result, fixture_cards)
    out = QpilotTools(store).qpcr_decide(fixture_result.study_id, card_id, "x", "y")
    assert out["error"] == f"unknown card {card_id!r}"


def test_stdio_without_the_simulator_lists_the_qpcr_tools_and_says_why(tmp_studies_dir, tmp_path):
    """`import qsim` fails in the served process: eleven tools, no crash, a note on stderr."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {**os.environ, "QPILOT_STUDIES_DIR": str(tmp_studies_dir)}
    blocked = "import sys; sys.modules['qsim'] = None; from qpilot.mcp_server import main; main()"
    params = StdioServerParameters(command=sys.executable, args=["-c", blocked], env=env)
    errlog = tmp_path / "stderr.txt"

    async def scenario():
        with errlog.open("w") as err:
            async with stdio_client(params, errlog=err) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    return sorted(t.name for t in listed.tools)

    assert anyio.run(scenario) == sorted(TOOL_NAMES)
    assert SIM_OFF_NOTICE in errlog.read_text()
