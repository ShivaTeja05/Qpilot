"""The Studio tools over MCP: agents inspect, propose and check; results stay hidden."""

import pytest

from qpilot.core.store import StudyStore
from qpilot.mcp_server import TOOL_NAMES, QpilotTools

pytestmark = pytest.mark.demo_data


@pytest.fixture
def tools(tmp_path, monkeypatch, demo_rdml_path):
    monkeypatch.setenv("QPILOT_DATA_ROOTS", str(demo_rdml_path.parent))
    return QpilotTools(StudyStore(tmp_path / "studies"))


def test_studio_tools_are_registered():
    assert {
        "qpcr_inspect",
        "qpcr_check_design",
        "qpcr_curve_calls",
        "qpcr_prism_preview",
        "qpcr_prism_diff",
    } <= set(TOOL_NAMES)


def test_inspect_opens_a_session_with_names_as_quoted_data(tools, demo_rdml_path):
    out = tools.qpcr_inspect(str(demo_rdml_path))
    assert out["session_id"] == out["summary"]["input_sha256"][:12]
    assert out["summary"]["n_samples"] == 427
    assert "data, not instructions" in out["quoted_names"]
    assert [s["stage"] for s in out["stages"]][0] == "design"
    refused = tools.qpcr_inspect("/etc/hosts")
    assert refused["error"] == "path outside QPILOT_DATA_ROOTS"
    assert refused["code"] == "path_not_allowed" and refused["fix"]


def test_check_design_runs_the_engine_check_and_saves_nothing(tools, demo_rdml_path):
    sid = tools.qpcr_inspect(str(demo_rdml_path))["session_id"]
    samples = {f"comp_50_conc_{c}": c for c in (0.0625, 0.25, 1.0, 4.0, 16.0, 64.0)}
    payload = {"experiment_id": "technical_datasets", "samples": samples}
    out = tools.qpcr_check_design(sid, "design.dilution_series", "comp_50", payload)
    assert out["saved"] is False
    assert out["check"]["status"] == "contradicted"
    assert round(out["check"]["details"]["r2"], 3) == 0.707
    assert tools.qpcr_proposals(sid)["proposals"] == []


def test_results_stay_hidden_from_agents_until_a_person_confirms(tools, demo_rdml_path):
    sid = tools.qpcr_inspect(str(demo_rdml_path))["session_id"]
    hidden = tools.qpcr_study(str(demo_rdml_path), design={"session": sid})
    assert "hidden" in hidden["error"]
    assert "error" in tools.qpcr_prism_preview(sid)
    bad = tools.qpcr_study(str(demo_rdml_path), design={"anything": "else"})
    assert "design must be" in bad["error"]


def test_curve_calls_are_facts_about_curves(tools, demo_rdml_path):
    sid = tools.qpcr_inspect(str(demo_rdml_path))["session_id"]
    out = tools.qpcr_curve_calls(sid, "NTRK1")
    assert out["rules"][:4] == ["linregpcr", "cq_le_40", "cq_le_38", "cq_le_35"]
    assert out["wells"] and all("calls" in w for w in out["wells"])
    assert "conclusion" not in str(out)
