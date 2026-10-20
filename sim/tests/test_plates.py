"""Opening a lab's own RDML file: the design check and the quick run."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from qsim.app import Screen
from qsim.cli import main
from qsim.data import demo_rdml, sha256
from qsim.plates import MAX_BYTES, PlateProblem, check, prepare, save_upload

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
UNTERGASSER = sorted((ROOT / "data" / "untergasser").glob("*.rdml"))
JARGON = re.compile(r"fragility|multiverse|\bSE\b|\brings?\b", re.I)
NS = "http://www.rdml.org"
PANEL = {
    "ALUsq(Eurogentec)", "HMBS", "HPRT1", "SDHA(1)", "UBC(2)", "MYCN(4)",
    "ODC1", "BIRC5", "NTRK1", "NM23A", "CD44", "CDH5", "AHCY", "CAMTA2", "DPYSL3", "PLAT",
}  # fmt: skip


def _tag(name: str) -> str:
    return f"{{{NS}}}{name}"


def smaller_study(out: Path) -> Path:
    """Another study cut from the benchmark RDML: 16 of its 64 plates, two thirds of the tumours.

    The zip carries a fixed date, so the bytes (and qPilot's curve cache) are the same every run.
    """
    ET.register_namespace("", NS)
    root = ET.fromstring(zipfile.ZipFile(demo_rdml()).read("rdml_data.xml"))
    unknown = sorted(
        s.get("id") for s in root.findall(_tag("sample")) if s.findtext(_tag("type")) == "unkn"
    )
    dropped = set(unknown[2::3])
    for exp in root.findall(_tag("experiment")):
        if exp.get("id") != "biomarker_set":
            root.remove(exp)
            continue
        for run in exp.findall(_tag("run")):
            if run.get("id").rsplit("_", 1)[0] not in PANEL:
                exp.remove(run)
                continue
            for react in run.findall(_tag("react")):
                if react.find(_tag("sample")).get("id") in dropped:
                    run.remove(react)
    for sample in root.findall(_tag("sample")):
        if sample.get("id") in dropped:
            root.remove(sample)
    info = zipfile.ZipInfo("rdml_data.xml", date_time=(2026, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr(info, ET.tostring(root, xml_declaration=True, encoding="utf-8"))
    return out


@pytest.fixture(scope="module")
def plate(tmp_path_factory):
    return smaller_study(tmp_path_factory.mktemp("rdml") / "smaller_study.rdml")


@pytest.fixture(scope="module")
def run(plate, tmp_path_factory):
    """A results folder with no run of its own, and the quick run of the smaller study in it."""
    root = tmp_path_factory.mktemp("results")
    steps: list[str] = []
    folder = prepare(plate, root, progress=steps.append)
    return root, folder, steps


def quiet(_: str) -> None:
    pass


def test_untergasser_files_get_a_plain_reason():
    assert UNTERGASSER
    for path in UNTERGASSER:
        with pytest.raises(PlateProblem) as err:
            check(path, progress=quiet)
        problem = err.value
        assert problem.design and "two-group design" in problem.message
        assert "biomarker_set" in problem.message
        # eva_green_b.rdml (added with the validation data) has a single experiment
        assert (
            "Its experiments are" in problem.message or "Its only experiment is" in problem.message
        )
        assert "MYCN(4)" in problem.full()  # the terminal also states the design
        assert not JARGON.findall(problem.full())


def test_files_that_are_not_rdml(tmp_path):
    with pytest.raises(PlateProblem, match="not an RDML file"):
        save_upload(b"plain text with an .rdml name", tmp_path)
    with pytest.raises(PlateProblem, match="larger than"):
        save_upload(b"PK\x03\x04" + bytes(MAX_BYTES), tmp_path)
    saved = save_upload(b"<?xml version='1.0'?><rdml/>", tmp_path)
    assert saved.parent.parent == tmp_path / "plates" and saved.name == "input.rdml"
    with pytest.raises(PlateProblem):
        check(saved, progress=quiet)


def test_the_benchmark_reuses_its_full_run():
    assert prepare(demo_rdml(), RESULTS, progress=quiet) == RESULTS


def test_quick_run_of_another_study(run, plate, monkeypatch):
    root, folder, steps = run
    assert folder.parent == root / "plates" and folder.name == sha256(plate)[:12]
    assert steps[0] == "Reading every curve with LinRegPCR" and steps[-1].startswith("Running all")
    summary = json.loads((folder / "summary.json").read_text())
    assert summary["source"]["name"] == "smaller_study.rdml"
    assert summary["benchmark_pooled"] is None and summary["designs"] is None
    assert not (folder / "validation_untergasser.json").exists()

    def no_rerun(*args, **kwargs):
        raise AssertionError("the run should have been reused")

    monkeypatch.setattr("qsim.report.run_all", no_rerun)
    assert prepare(plate, root, progress=quiet) == folder


def test_screen_on_another_study(run, plate):
    _, folder, _ = run
    screen = Screen(folder)  # the RDML is found from summary.json
    assert screen.engine.study.input_sha256 == sha256(plate)
    ov = screen.overview()
    assert ov["source"] == {"name": "smaller_study.rdml", "benchmark": False}
    assert ov["study"]["plates"] == len(PANEL)
    assert ov["study"]["genes"] == len(screen.explain) == len(PANEL) - 6
    text = json.dumps(ov)
    for gene, e in screen.explain.items():
        an = screen.gene_analyses(gene)
        assert an["n"] == e["analyses_defensible"]
        assert an["n_same"] / an["n"] == pytest.approx(e["holds_defensible"])
        assert screen.gene_samples(gene)["fold_log2"] == pytest.approx(e["log2fc"])
        views = [screen.gene_card(gene), screen.gene_effects(gene), screen.lab_parameters(gene)]
        text += json.dumps(views, ensure_ascii=False) + screen.evidence_html(gene)
    how = screen.how_view()
    assert "known" not in how and "faults" not in how and how["small"] == []
    assert how["not_run"] == [
        "planted faults",
        "small experiments drawn from the data",
        "known answers",
    ]
    text += json.dumps([screen.study_view(), how], ensure_ascii=False)
    assert not JARGON.findall(text)


def test_screen_refuses_a_run_from_another_file(plate):
    with pytest.raises(ValueError, match="different file"):
        Screen(RESULTS, rdml=str(plate))


def test_cli_says_why_a_file_cannot_be_opened(tmp_path, capsys):
    assert main(["app", "--rdml", str(UNTERGASSER[0]), "--results", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert f"qsim cannot open {UNTERGASSER[0].name}." in err
    assert "two-group design" in err and "MYCN(4)" in err
    assert not (tmp_path / "plates").exists() or not any((tmp_path / "plates").iterdir())
