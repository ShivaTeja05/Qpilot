"""The whole qPCR workflow on the demo: every stage, every person's action, every binding."""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest

from qpilot.integration import simulator as sim
from qpilot.integration.workflow import HUMAN, STAGES

pytestmark = pytest.mark.demo_data


def test_every_stage_runs_and_every_check_passes(workflow):
    report = workflow["report"]
    assert report.ok, [(c.stage, c.label, c.got, c.want) for c in report.failed]
    assert {s.stage for s in report.steps} == set(STAGES)
    assert len(report.checks) >= 30
    folder = Path(report.out_dir)
    assert (folder / "workflow.json").exists() and (folder / "WORKFLOW.md").exists()
    saved = json.loads((folder / "workflow.json").read_text())
    assert saved["ok"] and saved["n_failed"] == 0


def test_only_the_person_decides_and_always_with_a_reason(workflow):
    steps = workflow["report"].steps
    people = [s for s in steps if s.actor == HUMAN]
    assert people and all(s.reason for s in people)
    words = ("accepted", "rejected", "decided", "confirmed", "sent", "gave the reason")
    for step in steps:
        if step.actor != HUMAN and step.stage != "agents":
            assert not step.action.startswith(words), step
    actors = Counter(s.actor for s in steps)
    assert set(actors) <= {"human", "system", "agent"}


def test_the_simulator_runs_only_after_the_blind_stages(workflow):
    steps = workflow["report"].steps
    confirmed_curves = next(
        i for i, s in enumerate(steps) if s.action == "confirmed the curves stage"
    )
    audited = next(i for i, s in enumerate(steps) if s.stage == "simulator")
    assert audited > confirmed_curves


def test_the_audit_reproduces_qpilot_and_covers_every_analysis(workflow):
    values = workflow["report"].stages["simulator"]
    assert values["status"] == "audited"
    assert values["analyses"] == 90_396
    manifest = json.loads((Path(values["audit_dir"]) / sim.MANIFEST).read_text(encoding="utf-8"))
    repro = manifest["reproduces_qpilot"]
    assert repro["ok"] and repro["genes"] == 58
    assert repro["max_abs_diff_log2fc"] <= 1e-9 and repro["max_abs_diff_p"] <= 1e-9
    assert manifest["study_id"] == workflow["report"].study_id
    assert manifest["your_choices"]["changes_from_prespecified"] == {}


def test_the_audit_of_the_studio_study_equals_the_simulator_on_its_own(workflow):
    """Studio's confirmed design gives the simulator the same verdicts as the bare RDML file."""
    import qsim

    committed = Path(qsim.__file__).resolve().parents[2] / "results" / "genes.csv"
    if not committed.exists():
        pytest.skip("the simulator's committed results are not in this checkout")
    ours = pd.read_csv(
        Path(workflow["report"].stages["simulator"]["audit_dir"]) / "genes.csv"
    ).set_index("gene")
    theirs = pd.read_csv(committed).set_index("gene")
    assert dict(ours["verdict"]) == dict(theirs["verdict"])
    for column in ("defensible_holds", "all_holds", "fold_margin_log2"):
        assert (ours[column] - theirs[column]).abs().max() < 1e-9, column


def test_the_audit_is_bound_to_the_prism_bundle(workflow):
    binding = workflow["report"].stages["prism"]["audit_binding"]
    assert binding["ok"]
    assert binding["compared"] and all(binding["compared"].values())


def test_the_prism_exclusion_reaches_the_reaudit(workflow):
    report = workflow["report"]
    values = report.stages["roundtrip"]
    assert values["items"] == [["missing", "ODC1", "1496"]]
    assert values["reaudit_status"] == "audited"
    assert values["reaudit_scope"]["wells_excluded_by_a_person"] == 1
    assert report.final_study_id != report.study_id
    again = json.loads(
        (Path(report.paths["simulator_audit_after_roundtrip"]) / sim.MANIFEST).read_text()
    )
    assert again["reproduces_qpilot"]["ok"]  # the exclusion is left out, never filled in
    assert again["study_id"] == report.final_study_id


def test_the_record_carries_the_audit_and_refuses_the_old_one(workflow):
    report = workflow["report"]
    record = Path(report.paths["record"])
    after = Path(report.paths["simulator_audit_after_roundtrip"])
    assert sim.verify_audit(after, record).ok
    old = sim.verify_audit(report.paths["simulator_audit"], record)
    assert not old.ok
    assert any("another study" in p for p in old.problems)


def test_a_changed_audit_file_is_caught(workflow, tmp_path):
    source = Path(workflow["report"].paths["simulator_audit"])
    copy = tmp_path / "audit"
    shutil.copytree(source, copy)
    assert sim.verify_audit(copy).ok
    genes = copy / "genes.csv"
    genes.write_text(genes.read_text().replace("fragile", "solid", 1))
    check = sim.verify_audit(copy)
    assert not check.ok and "changed: genes.csv" in check.problems
    (copy / "extra.txt").write_text("planted")
    assert "not in checksums: extra.txt" in sim.verify_audit(copy).problems


def test_agents_get_the_simulator_tools_and_cannot_decide(workflow):
    values = workflow["report"].stages["agents"]
    for name in ("sim_audit", "sim_gene", "sim_whatif", "sim_decisions", "qpcr_decide"):
        assert name in values["tools"]
    assert values["agent_request"] == "pending_human"
    assert values["chain_head_before"] != values["chain_head_after"]  # only the request line
