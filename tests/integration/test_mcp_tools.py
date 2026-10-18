"""The simulator's MCP tools: read-only, checked audits only, errors as data (demo data)."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import anyio
import pytest

from qpilot.integration.mcp_tools import SIM_TOOL_NAMES, SimulatorTools, create_server
from qpilot.mcp_server import TOOL_NAMES

pytestmark = pytest.mark.demo_data


def _digest(folder: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(folder.rglob("*")):
        if p.is_file() and p.name != ".lock":
            h.update(p.relative_to(folder).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()


@pytest.fixture(scope="module")
def tools(workflow):
    return SimulatorTools(workflow["store"], audits=workflow["report"].paths)


def test_the_server_lists_qpilots_tools_and_the_simulators(workflow):
    server = create_server(workflow["store"], audits=workflow["report"].paths)
    names = {t.name for t in anyio.run(server.list_tools)}
    assert set(TOOL_NAMES) | set(SIM_TOOL_NAMES) == names


def test_an_agent_reads_the_audit(workflow, tools):
    study = workflow["report"].study_id
    view = tools.sim_audit(study)
    assert "error" not in view, view
    assert view["analyses"] == 90_396 and view["reproduces_qpilot"]["ok"]
    gene = tools.sim_gene(study, "odc1")
    assert gene["gene"] == "ODC1" and gene["call"] == "up" and gene["verdict"]
    decisions = tools.sim_decisions(study)
    assert set(decisions["baseline"]) == {
        "efficiency",
        "flagged",
        "late_cq",
        "nondetect",
        "refs",
        "cut",
        "test",
        "multiplicity",
    }


def test_whatif_answers_without_storing_anything(workflow, tools):
    store, study = workflow["store"], workflow["report"].study_id
    before = _digest(store.workspace(study))
    answer = tools.sim_whatif(study, {"refs": "HMBS"})
    assert "error" not in answer, answer
    assert "NM23A" in answer["calls_that_change"]  # NM23A loses its call with HMBS alone
    some = tools.sim_whatif(study, {"late_cq": "cq35"}, genes=["ntrk1"])
    assert [g["gene"] for g in some["genes"]] == ["NTRK1"]
    assert _digest(store.workspace(study)) == before


def test_bad_requests_come_back_as_errors(workflow, tools):
    study = workflow["report"].study_id
    assert "error" in tools.sim_whatif(study, {"refs": "no such genes"})
    assert "error" in tools.sim_whatif(study, {"colour": "blue"})
    assert "error" in tools.sim_whatif(study, {"refs": 3})  # type: ignore[dict-item]
    assert "error" in tools.sim_whatif(study, {}, genes=["x"] * 101)
    assert "error" in tools.sim_gene(study, "NOT_A_GENE")
    assert "error" in tools.sim_audit("ffffffffffff")
    assert "error" in tools.sim_audit("../../etc")


def test_a_changed_audit_is_not_served(workflow, tmp_path):
    report = workflow["report"]
    copy = tmp_path / "audit"
    shutil.copytree(report.paths["simulator_audit"], copy)
    explain = copy / "explain.json"
    explain.write_text(explain.read_text().replace('"up"', '"down"', 1))
    tampered = SimulatorTools(workflow["store"], audits={report.study_id: str(copy)})
    answer = tampered.sim_audit(report.study_id)
    assert "error" in answer and "does not verify" in answer["error"]
