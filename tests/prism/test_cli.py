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
def test_export_prism_writes_the_project_and_verify_passes(studies_env, tmp_path, capsys):
    _, study_id = studies_env
    out = tmp_path / "bundle"
    code = main(
        ["export", "prism", "--study", study_id, "--genes", "ODC1,NTRK1", "--out", str(out)]
    )
    assert code == 0
    printed = capsys.readouterr().out
    assert f"Open in Prism: double-click qpilot_{study_id}.pzfx" in printed
    assert "Run in Prism" not in printed and "osascript" not in printed
    names = {p.name for p in out.iterdir()}
    assert {
        f"qpilot_{study_id}.pzfx",
        "ODC1.csv",
        "NTRK1.csv",
        "qpilot_provenance.json",
        "qpilot_bundle.json",
        "README.txt",
    } == names
    readme = (out / "README.txt").read_text()
    assert "Not affiliated with or endorsed by GraphPad Software" in readme
    assert "NOT here yet" not in readme and "qpilot/prism/templates" not in readme
    assert main(["prism", "verify", "--bundle", str(out)]) == 0


@pytest.mark.demo_data
def test_export_prism_scripts_are_an_extra(studies_env, tmp_path, capsys):
    _, study_id = studies_env
    out = tmp_path / "bundle"
    args = ["export", "prism", "--study", study_id, "--genes", "ODC1", "--out", str(out)]
    assert main([*args, "--scripts"]) == 0
    names = {p.name for p in out.iterdir()}
    assert {"run.pzc", "send_back.pzc", "sent_back", f"qpilot_{study_id}.pzfx"} <= names
    old = tmp_path / "old"
    assert (
        main(
            [
                "export",
                "prism",
                "--study",
                study_id,
                "--genes",
                "ODC1",
                "--out",
                str(old),
                "--scripts-only",
            ]
        )
        == 0
    )
    assert "Run in Prism" in capsys.readouterr().out
    assert not any(p.suffix == ".pzfx" for p in old.iterdir())


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
    code = main(["export", "prism", "--study", study_id, "--graphs", "pdf", "--out", str(empty)])
    assert code == 2 and not empty.exists()
    assert "only apply to the Prism scripts" in capsys.readouterr().err
    code = main(
        [
            "export",
            "prism",
            "--study",
            study_id,
            "--scripts",
            "--graphs",
            "svg",
            "--out",
            str(empty),
        ]
    )
    assert code == 2 and not empty.exists()
    code = main(
        [
            "export",
            "prism",
            "--study",
            study_id,
            "--template",
            "many_genes_log2",
            "--scripts",
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
    (out / "sent_back").mkdir()
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
    (out / "ODC1.csv").write_text("Sample,MYCN-high,rest\n1496,1.0,\n")
    code = main(
        [
            "prism",
            "diff",
            "--study",
            study_id,
            "--bundle",
            str(out),
            "--returned",
            str(out),
        ]
    )
    assert code == 2
    assert "does not verify" in capsys.readouterr().err
    assert main(["prism", "verify", "--bundle", str(out)]) == 1


def _private_cache(root: Path, input_sha256: str) -> Path:
    """The demo's own files of the shared cache, linked into a cache of this test's own.

    Every other run on the machine writes to the shared cache (the curve tables of the files it
    reads), so watching it sees their writes. Here only this test can write: any file it adds,
    replaces or changes in the cache shows (a link reports its target's size and time).
    """
    import shutil

    from qpilot.io.datasets import VERMEULEN_FILENAME, default_cache_dir

    root.mkdir()
    for path in default_cache_dir().iterdir():
        mine = path.name == VERMEULEN_FILENAME or path.name.startswith(f"{input_sha256}.")
        if not (mine and path.is_file()):
            continue
        try:
            os.link(path, root / path.name)
        except OSError:  # another volume: a copy keeps the same bytes
            shutil.copy2(path, root / path.name)
    return root


@pytest.mark.demo_data
def test_preview_writes_nothing(studies_env, tmp_path, monkeypatch):
    from qpilot.io.datasets import default_cache_dir
    from qpilot.prism import preview

    store, study_id = studies_env
    cache = _private_cache(tmp_path / "cache", store.get(study_id).input_sha256)
    monkeypatch.setenv("QPILOT_CACHE_DIR", str(cache))
    assert default_cache_dir() == cache and any(cache.iterdir())
    monkeypatch.chdir(tmp_path)
    watched = [store.root, tmp_path, cache]
    before = [_files(root) for root in watched]
    result = preview(store, study_id, ["ODC1", "NTRK1"])
    assert [_files(root) for root in watched] == before
    assert result["writes_nothing"] is True
    bundle = result["bundle"]
    assert [t["gene"] for t in bundle["tables"]] == ["ODC1", "NTRK1"]
    assert bundle["bundle_sha256"] == ""
    assert result["tables"]["ODC1"]["head"][0] == "Sample,MYCN-high,rest"
    assert f"qpilot_{study_id}.pzfx" in result["would_write"]
    assert result["project"]["needs_template"] is False
    assert [t["kind"] for t in result["project"]["tables"]] == ["column", "column", "grouped"]
    json.dumps(result)  # JSON-ready for the MCP tool
