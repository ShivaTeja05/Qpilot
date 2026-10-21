"""The simulator's MCP tools: read-only, checked audits only, errors as data (demo data)."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import anyio
import pytest

from qpilot.integration import mcp_tools
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


# ---- sim_findings: the audit's saved findings, read-only -----------------------------------------


def test_an_agent_pages_through_the_saved_findings(workflow, tools):
    store, study = workflow["store"], workflow["report"].study_id
    before = _digest(store.workspace(study))
    audit = Path(workflow["report"].paths["simulator_audit"])
    audit_before = _digest(audit)
    issues = tools.sim_findings(study, "issues", limit=200)
    assert "error" not in issues, issues
    assert issues["file"] == "issues.json" and issues["total"] == len(issues["rows"]) > 0
    assert {"issue_id", "kind", "impact", "remedy"} <= set(issues["rows"][0])
    first = tools.sim_findings(study, "issues", limit=2)
    second = tools.sim_findings(study, "issues", offset=first["next_offset"], limit=2)
    assert [r["issue_id"] for r in first["rows"] + second["rows"]] == [
        r["issue_id"] for r in issues["rows"][:4]
    ]
    for table, column in (("one_sample_flips", "gene"), ("reference_wells", "reference")):
        page = tools.sim_findings(study, table)
        assert "error" not in page, page
        assert page["rows"] and column in page["rows"][0]
        assert len(page["file_sha256"]) == 64
    flips = tools.sim_findings(study, "one_sample_flips", limit=200)
    gene = flips["rows"][0]["gene"]
    only = tools.sim_findings(study, "one_sample_flips", gene=gene.lower(), limit=200)
    assert only["total"] >= 1 and {r["gene"] for r in only["rows"]} == {gene}
    named = tools.sim_findings(study, "issues", gene=gene, limit=200)
    assert named["total"] >= 1
    assert _digest(store.workspace(study)) == before and _digest(audit) == audit_before


def test_findings_refuse_bad_requests(workflow, tools):
    study = workflow["report"].study_id
    for bad in (
        {"table": "../lock"},
        {"table": "grid.parquet"},
        {"table": ["issues"]},
        {"limit": 0},
        {"limit": 201},
        {"limit": True},
        {"offset": -1},
        {"offset": "1"},
        {"gene": "x" * 201},
        {"gene": {"actor": "human"}},
    ):
        assert "error" in tools.sim_findings(study, **bad), bad
    assert "error" in tools.sim_findings("ffffffffffff")
    assert "error" in tools.sim_findings("../../etc")
    past = tools.sim_findings(study, "issues", offset=1_000_000)
    assert past["rows"] == [] and past["next_offset"] is None


def test_findings_come_only_from_a_verified_plain_capped_file(workflow, tmp_path, monkeypatch):
    report = workflow["report"]
    copy = tmp_path / "audit"
    shutil.copytree(report.paths["simulator_audit"], copy)
    served = SimulatorTools(workflow["store"], audits={report.study_id: str(copy)})
    assert "error" not in served.sim_findings(report.study_id, "reference_wells")
    monkeypatch.setattr(mcp_tools, "MAX_FINDINGS_BYTES", 100)
    capped = served.sim_findings(report.study_id, "issues")
    assert "error" in capped and "larger than" in capped["error"]
    monkeypatch.undo()
    flips = copy / "one_sample_flips.csv"
    flips.write_text(flips.read_text().replace("True", "False", 1))
    tampered = served.sim_findings(report.study_id, "one_sample_flips")
    assert "error" in tampered and "does not verify" in tampered["error"]

    linked = tmp_path / "linked"
    shutil.copytree(report.paths["simulator_audit"], linked)
    outside = tmp_path / "outside.csv"
    shutil.copy(linked / "reference_wells_top50.csv", outside)
    (linked / "reference_wells_top50.csv").unlink()
    (linked / "reference_wells_top50.csv").symlink_to(outside)  # same bytes, so it verifies
    via_link = SimulatorTools(workflow["store"], audits={report.study_id: str(linked)})
    answer = via_link.sim_findings(report.study_id, "reference_wells")
    assert "error" in answer and "not a plain file" in answer["error"]


# ---- every reply matches its declared output schema (qpilot.agents.outputs) ---------------------


def test_the_simulator_and_prism_replies_match_their_output_schemas(workflow, monkeypatch):
    """Over MCP: a reply that did not match its schema would come back as engine_refused."""
    from qpilot.agents.surface import SPECS

    report, store = workflow["report"], workflow["store"]
    study = report.study_id
    bundle = Path(report.paths["prism_bundle"])
    monkeypatch.setenv("QPILOT_DATA_ROOTS", str(workflow["root"]))
    server = create_server(store, audits=report.paths)

    def ok(name, args):
        reply = anyio.run(server.call_tool, name, args)
        assert reply.is_error is False, (name, reply.structured_content)
        return SPECS[name].output.model_validate(reply.structured_content)

    for fmt in ("detailed", "concise"):
        ok("sim_audit", {"study_id": study, "response_format": fmt})
        ok("sim_whatif", {"study_id": study, "changes": {"refs": "HMBS"}, "response_format": fmt})
    ok("sim_gene", {"study_id": study, "gene": "ODC1"})
    ok("sim_decisions", {"study_id": study})
    ok("sim_findings", {"study_id": study, "table": "issues", "limit": 5})
    ok("qpcr_prism_preview", {"study_id": study})
    diff = ok(
        "qpcr_prism_diff",
        {"study_id": study, "bundle_dir": str(bundle), "sent_back_dir": str(bundle / "sent_back")},
    )
    assert diff.saved is False
    refused = anyio.run(server.call_tool, "sim_gene", {"study_id": study, "gene": "NOT_A_GENE"})
    assert refused.is_error and refused.structured_content["code"] == "unknown_item"
