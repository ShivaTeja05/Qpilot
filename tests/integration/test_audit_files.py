"""Checks that need no demo data: audit files, the missing simulator, the empty-folder rule."""

from __future__ import annotations

import builtins
import json

import pytest

from qpilot.core.store import StudyStore
from qpilot.integration import simulator as sim


def _fake_audit(folder, study_id="abcdefabcdef", sha="a" * 64):
    folder.mkdir(parents=True)
    lock = {"input_sha256": sha, "baseline": {}, "sha256": "f" * 64}
    (folder / "lock.json").write_text(json.dumps(lock))
    (folder / "genes.csv").write_text("gene,verdict\nODC1,solid\n")
    manifest = {
        "study_id": study_id,
        "input_sha256": sha,
        "lock_sha256": "f" * 64,
        "reproduces_qpilot": {"ok": True},
    }
    (folder / sim.MANIFEST).write_text(json.dumps(manifest))
    sim._write_checksums(folder)
    return folder


def test_a_complete_audit_verifies_and_each_change_is_named(tmp_path):
    folder = _fake_audit(tmp_path / "audit")
    assert sim.verify_audit(folder).ok
    (folder / "genes.csv").write_text("gene,verdict\nODC1,fragile\n")
    assert sim.verify_audit(folder).problems == ["changed: genes.csv"]


def test_a_missing_or_unlisted_file_fails(tmp_path):
    folder = _fake_audit(tmp_path / "audit")
    (folder / "genes.csv").unlink()
    assert "missing: genes.csv" in sim.verify_audit(folder).problems
    other = _fake_audit(tmp_path / "other")
    (other / "planted.json").write_text("{}")
    assert "not in checksums: planted.json" in sim.verify_audit(other).problems


def test_a_lock_for_another_file_fails(tmp_path):
    folder = _fake_audit(tmp_path / "audit")
    (folder / "lock.json").write_text(json.dumps({"input_sha256": "b" * 64, "sha256": "f" * 64}))
    sim._write_checksums(folder)
    assert "lock.json is for another input file" in sim.verify_audit(folder).problems


def test_no_checksums_no_audit(tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    assert not sim.verify_audit(folder).ok


def test_without_the_simulator_the_audit_says_so(monkeypatch, tmp_path):
    real = builtins.__import__

    def no_qsim(name, *args, **kwargs):
        if name == "qsim" or name.startswith("qsim."):
            raise ImportError("no qsim")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_qsim)
    assert not sim.available()
    with pytest.raises(sim.SimulatorUnavailable):
        sim.audit(StudyStore(tmp_path / "studies"), "abcdefabcdef", tmp_path / "audit")


def test_the_workflow_never_writes_into_a_folder_in_use(tmp_path):
    from qpilot.integration.workflow import run_workflow

    used = tmp_path / "used"
    used.mkdir()
    (used / "notes.txt").write_text("keep me")
    with pytest.raises(FileExistsError):
        run_workflow(tmp_path / "x.rdml", used, StudyStore(tmp_path / "studies"))
    assert (used / "notes.txt").read_text() == "keep me"


def test_the_command_line_lists_its_commands(capsys):
    from qpilot.integration.__main__ import main

    assert main([]) == 0
    printed = capsys.readouterr().out
    for command in ("demo", "audit", "verify", "serve", "status"):
        assert command in printed
