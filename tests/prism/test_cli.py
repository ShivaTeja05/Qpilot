"""The Prism commands end to end, the agent preview (writes nothing) and import hygiene."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from qpilot.cli import build_parser, main

REPO = Path(__file__).resolve().parents[2]


def test_both_commands_are_registered_next_to_the_others():
    parser = build_parser()
    commands = set(parser._subparsers._group_actions[0].choices)
    assert {"export", "prism", "run", "verify", "serve"} <= commands


def test_the_bridge_never_imports_a_model_client():
    code = (
        "import sys, qpilot.prism, qpilot.prism.roundtrip, qpilot.qpcr.export, "
        "qpilot.cli.prism_cmds\n"
        "ai = ('qpilot.ai', 'anthropic', 'httpx')\n"
        "bad = sorted(m for m in sys.modules if m.startswith(ai))\n"
        "assert not bad, bad\nprint('ok')"
    )
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, env=env
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"


def _files(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    }


@pytest.fixture
def studies_env(demo_study, monkeypatch):
    store, study_id = demo_study
    monkeypatch.setenv("QPILOT_STUDIES_DIR", str(store.root))
    return store, study_id


@pytest.mark.demo_data
def test_export_prism_writes_the_bundle_and_verify_passes(studies_env, tmp_path, capsys):
    _, study_id = studies_env
    out = tmp_path / "bundle"
    code = main(
        ["export", "prism", "--study", study_id, "--genes", "ODC1,NTRK1", "--out", str(out)]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert "two_groups_log2" in printed and "Run in Prism" in printed
    names = {p.name for p in out.iterdir()}
    assert {
        "ODC1.csv",
        "NTRK1.csv",
        "run.pzc",
        "send_back.pzc",
        "qpilot_provenance.json",
        "qpilot_bundle.json",
        "README.txt",
        "sent_back",
    } <= names
    readme = (out / "README.txt").read_text()
    assert "Not affiliated with or endorsed by GraphPad Software" in readme
    assert "two_groups_log2.pzt is NOT here yet" in readme
    assert main(["prism", "verify", "--bundle", str(out)]) == 0


@pytest.mark.demo_data
def test_export_refuses_a_non_empty_folder_and_a_bad_gene(studies_env, tmp_path, capsys):
    _, study_id = studies_env
    full = tmp_path / "full"
    full.mkdir()
    (full / "keep.txt").write_text("mine")
    assert main(["export", "prism", "--study", study_id, "--out", str(full)]) == 2
    assert (full / "keep.txt").read_text() == "mine"
    empty = tmp_path / "empty"
    code = main(["export", "prism", "--study", study_id, "--genes", "HMBS", "--out", str(empty)])
    assert code == 2
    assert not empty.exists()
    assert "not analysed genes" in capsys.readouterr().err
    code = main(["export", "prism", "--study", study_id, "--graphs", "svg", "--out", str(empty)])
    assert code == 2 and not empty.exists()
    code = main(
        [
            "export",
            "prism",
            "--study",
            study_id,
            "--template",
            "many_genes_log2",
            "--out",
            str(empty),
        ]
    )
    assert code == 2 and not empty.exists()
    assert "contract change" in capsys.readouterr().err


@pytest.mark.demo_data
def test_prism_diff_prints_items_and_proposals(studies_env, tmp_path, capsys):
    _, study_id = studies_env
    out = tmp_path / "bundle"
    assert main(["export", "prism", "--study", study_id, "--genes", "ODC1", "--out", str(out)]) == 0
    lines = (out / "ODC1.csv").read_text().splitlines()
    edited = []
    for line in lines:
        title = line.split(",")[0]
        if title == "1496":
            line = "1496,,"
        elif title == "1784":
            line = "1784,9.5,"
        edited.append(line)
    (out / "sent_back" / "ODC1.csv").write_text("\n".join(edited) + "\n")
    capsys.readouterr()
    code = main(
        [
            "prism",
            "diff",
            "--study",
            study_id,
            "--bundle",
            str(out),
            "--sent-back",
            str(out / "sent_back"),
        ]
    )
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert [(i["kind"], i["row"]) for i in report["items"]] == [
        ("missing", "1496"),
        ("changed", "1784"),
    ]
    kinds = [p["kind"] for p in report["proposals"]]
    assert kinds == ["prism.exclusion_reason", "prism.value_edit"]
    assert all(p["status"] == "proposed" for p in report["proposals"])
    assert report["proposals"][0]["consequence"]["n_conclusions_changed"] == 0


@pytest.mark.demo_data
def test_prism_diff_refuses_a_tampered_bundle(studies_env, tmp_path, capsys):
    _, study_id = studies_env
    out = tmp_path / "bundle"
    assert main(["export", "prism", "--study", study_id, "--genes", "ODC1", "--out", str(out)]) == 0
    (out / "run.pzc").write_text('SetPath "/elsewhere"\n')
    code = main(
        [
            "prism",
            "diff",
            "--study",
            study_id,
            "--bundle",
            str(out),
            "--sent-back",
            str(out / "sent_back"),
        ]
    )
    assert code == 2
    assert "does not verify" in capsys.readouterr().err
    assert main(["prism", "verify", "--bundle", str(out)]) == 1


@pytest.mark.demo_data
def test_preview_writes_nothing(studies_env, tmp_path, monkeypatch):
    from qpilot.io.datasets import default_cache_dir
    from qpilot.prism import preview

    store, study_id = studies_env
    monkeypatch.chdir(tmp_path)
    watched = [store.root, tmp_path, default_cache_dir()]
    before = [_files(root) for root in watched]
    result = preview(store, study_id, ["ODC1", "NTRK1"])
    assert [_files(root) for root in watched] == before
    assert result["writes_nothing"] is True
    bundle = result["bundle"]
    assert [t["gene"] for t in bundle["tables"]] == ["ODC1", "NTRK1"]
    assert bundle["bundle_sha256"] == ""
    assert result["tables"]["ODC1"]["head"][0] == "Sample,MYCN-high,rest"
    assert "run.pzc" in result["would_write"]
    json.dumps(result)  # JSON-ready for the MCP tool
