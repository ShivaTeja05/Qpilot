"""Instrument exports over MCP: ``qpcr_inspect`` and ``qpcr_study`` read them like the page's Open.

An export (one file, or the folder of one export set) inside ``QPILOT_DATA_ROOTS`` is converted
once into RDML in the study store (``imports/capture/``, through
``qpilot.io.connectors.materialise``); the path policy is unchanged: the path and every file of a
folder must resolve inside a data root.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from qpilot.web import intake, views

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"
CFX = CORPUS / "synthetic" / "cfx-manager-raw-vs-baseline-subtracted"
LC480 = CORPUS / "roche" / "mendeley-diras2-lc480-raw-and-cp" / "CP1.txt"


def cfx_set(folder: Path, stem: str = "qpilot-synthetic-baselined") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for path in sorted(CFX.glob(f"{stem} *")):
        shutil.copy(path, folder / path.name)
    return folder


def test_an_export_set_opens_a_session_and_is_recorded_like_the_pages_open(tools, data_root):
    folder = cfx_set(data_root / "run-1")
    out = tools.qpcr_inspect(str(folder))
    assert "error" not in out, out
    session = out["session_id"]
    imported = out["imported"]
    assert (imported["connector"], imported["n_files"], imported["n_plates"]) == ("cfx", 2, 1)
    assert imported["rawness"] == "baseline_subtracted" and imported["linregpcr_ok"] is False
    assert "Re-export" in imported["rawness_meaning"]
    assert "CURVES_NOT_RAW" in {w["code"] for w in imported["warnings"]}
    # the RDML lives in the study store where the page keeps imports, named after the export
    source = tools.studio.source(session)
    assert source.parent == intake.imports_dir(tools.store) / "capture"
    assert views.display_name(source) == "qpilot-synthetic-baselined (2 files)"
    # the session carries the import, so the page shows it and the Run Gate reads its raw-ness
    meta, unused = intake.load(tools.store, session)
    assert meta.rawness["study_verdict"] == "baseline_subtracted" and unused == []
    assert [s.name for s in meta.sources] == sorted(p.name for p in folder.iterdir())
    # no file text reaches the agent outside the quoted block
    assert "qpilot-synthetic" not in json.dumps(imported)
    again = tools.qpcr_inspect(str(folder), response_format="concise")
    assert again["session_id"] == session and again["imported"] == imported


def test_one_exported_file_opens_too(tools, data_root):
    target = data_root / LC480.name
    shutil.copy(LC480, target)
    out = tools.qpcr_inspect(str(target))
    assert out["imported"]["connector"] == "lightcycler480"
    assert out["imported"]["rawness"] == "raw"


def test_a_person_s_import_record_is_kept_as_it_is(tools, data_root):
    folder = cfx_set(data_root / "run-1")
    session = tools.qpcr_inspect(str(folder))["session_id"]
    record = tools.store.find_session(session) / intake.CAPTURE_FILE
    data = json.loads(record.read_text(encoding="utf-8"))
    data["unused"] = ["notes.docx"]  # what a person's Open set aside
    record.write_text(json.dumps(data), encoding="utf-8")
    tools.qpcr_inspect(str(folder))
    assert json.loads(record.read_text(encoding="utf-8"))["unused"] == ["notes.docx"]


def test_an_export_is_analysed_only_with_the_design_a_person_confirms(tools, data_root):
    folder = cfx_set(data_root / "run-1")
    out = tools.qpcr_study(str(folder))
    assert (out["code"], out["field"]) == ("results_hidden", "design")
    assert "qpcr_inspect" in out["error"]
    session = tools.qpcr_inspect(str(folder))["session_id"]
    hidden = tools.qpcr_study(str(folder), design={"session": session})
    assert hidden["code"] == "results_hidden"
    other = cfx_set(data_root / "run-2", stem="qpilot-synthetic-raw")
    wrong = tools.qpcr_study(str(other), design={"session": session})
    assert wrong["code"] == "invalid_argument" and "another input file" in wrong["error"]
    assert tools.store.list_studies() == []


# ---- the path policy is unchanged ---------------------------------------------------------------


def test_an_export_outside_the_roots_is_refused_and_nothing_is_converted(
    tools, data_root, tmp_path
):
    outside = cfx_set(tmp_path / "elsewhere")
    for path in (outside, next(outside.iterdir())):
        out = tools.qpcr_inspect(str(path))
        assert (out["code"], out["field"]) == ("path_not_allowed", "rdml_path")
    assert not (tools.store.root / intake.IMPORTS_DIR).exists()


def test_a_link_in_an_export_folder_to_a_file_outside_the_roots_is_refused(
    tools, data_root, tmp_path
):
    outside = cfx_set(tmp_path / "elsewhere")
    folder = data_root / "run-1"
    folder.mkdir()
    for path in outside.iterdir():
        (folder / path.name).symlink_to(path)
    out = tools.qpcr_inspect(str(folder))
    assert out["code"] == "path_not_allowed" and out["error"] == "path outside QPILOT_DATA_ROOTS"
    assert tools.qpcr_study(str(folder))["code"] == "path_not_allowed"
    assert not (tools.store.root / intake.IMPORTS_DIR).exists()


@pytest.mark.parametrize(
    "content",
    ["just some notes\n", "patient,diagnosis\nAlice Smith,positive\n"],
    ids=["text", "a sheet"],
)
def test_a_file_that_is_no_export_is_refused_by_content(tools, data_root, content):
    path = data_root / "notes.csv"
    path.write_text(content, encoding="utf-8")
    out = tools.qpcr_inspect(str(path))
    assert (out["code"], out["field"]) == ("unsupported_input", "rdml_path")
    assert out["error"].startswith("not an RDML file or an instrument export qPilot reads")
    assert "Alice" not in out["error"]


def test_an_empty_folder_is_refused(tools, data_root):
    (data_root / "empty").mkdir()
    out = tools.qpcr_inspect(str(data_root / "empty"))
    assert out["code"] == "unsupported_input"


def test_over_mcp_an_export_session_matches_the_schema(served, data_root):
    folder = cfx_set(data_root / "run-1")
    reply = served("qpcr_inspect", {"rdml_path": str(folder), "response_format": "concise"})
    assert reply.is_error is False
    assert reply.structured_content["imported"]["connector"] == "cfx"
