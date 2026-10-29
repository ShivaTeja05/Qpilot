"""The default bundle end to end on the toy study: a Prism project that needs no template, its
README, and the round trip from the project as Prism saves it (exclusions, deletions and edits
become proposals; a value excluded in the table of all genes is the gene's own cell).

``study_inputs`` is replaced by the toy (the engine's own numbers on six units with three
technical replicates), so this runs without the demo dataset.
"""

from __future__ import annotations

import importlib
import shutil
from pathlib import Path

import pytest
from lxml import etree

from qpilot.prism import diff_report, export_study, pzfx, verify_provenance
from qpilot.prism.roundtrip import (
    CHANGED_PROJECT_NOTE,
    DELETED_NOTE,
    EXCLUDED_PROJECT_NOTE,
    RoundTripError,
    is_project_path,
)
from qpilot.prism.script import host_platform
from tests.prism.conftest import TOY_STUDY, accepted_exclusion, toy_inputs

NS = {"p": pzfx.NAMESPACE}


def _engine_export():
    """The engine's export module as imported (``sys.modules``), whose inputs the toy replaces."""
    return importlib.import_module("qpilot.qpcr.export")


class _Store:
    """The only store call the export makes besides the (replaced) inputs: the decisions."""

    def entries(self, study_id):
        return []


@pytest.fixture
def toy_export(tmp_path, monkeypatch):
    inputs = toy_inputs()
    monkeypatch.setattr(_engine_export(), "demo_inputs", lambda *a, **k: inputs)
    result = export_study(_Store(), TOY_STUDY, tmp_path / "bundle", platform="macos")
    return result, inputs


def _root(path: Path):
    return etree.fromstring(path.read_bytes())


def _save(root, path: Path, binary: bool = True) -> None:
    """Write the tree back as Prism would: with its binary analyses block appended."""
    if binary:
        block = etree.SubElement(root, f"{{{pzfx.NAMESPACE}}}Template")
        block.text = "QUJDREVG" * 50
    path.write_bytes(b'<?xml version="1.0" encoding="UTF-8"?>\n' + etree.tostring(root))


def _table(root, prefix: str):
    return next(
        t for t in root.findall("p:Table", NS) if t.find("p:Title", NS).text.startswith(prefix)
    )


def _cell(table, unit: str, group: str):
    units = [d.text for d in table.findall("p:RowTitlesColumn/p:Subcolumn/p:d", NS)]
    column = next(c for c in table.findall("p:YColumn", NS) if c.find("p:Title", NS).text == group)
    return column.findall("p:Subcolumn/p:d", NS)[units.index(unit)]


def test_the_default_bundle_is_a_project_that_needs_no_template(toy_export):
    result, _ = toy_export
    names = {p.name for p in result.out_dir.iterdir()}
    assert {
        f"qpilot_{TOY_STUDY}.pzfx",
        f"qpilot_{TOY_STUDY}_replicates.pzfx",
        "T.csv",
        "T2.csv",
        "T_replicates.csv",
        "T2_replicates.csv",
        "README.txt",
        "qpilot_provenance.json",
        "qpilot_bundle.json",
    } == names
    assert not any(n.endswith(".pzc") or n.endswith(".pzt") for n in names)
    assert result.project.name == f"qpilot_{TOY_STUDY}.pzfx" and not result.scripts
    assert result.send_back is None and result.launch.argv[:2] == ("open", "-a")
    assert verify_provenance(result.out_dir) == []
    bundle = result.bundle
    assert bundle.mode == "xml" and bundle.info["template_status"] == "not needed"
    project = pzfx.read_project(result.project.read_bytes())
    kinds = [t.kind for t in project.tables]
    assert kinds == ["column", "column", "grouped"]
    assert {t.title for t in bundle.tables if t.layout == "column"} == {
        t.title for t in project.tables if t.kind == "column"
    }
    nested = pzfx.read_project(result.replicates_project.read_bytes())
    assert [t.kind for t in nested.tables] == ["nested", "nested"]
    # the project file is not a checked file (Prism saves it), its sha256 as written is kept
    assert result.project.name not in bundle.files
    assert bundle.info["project_sha256"] and bundle.info["replicates_project_sha256"]


def test_the_readme_gives_plain_steps_for_both_systems_and_no_repo_path(toy_export):
    result, _ = toy_export
    readme = " ".join((result.out_dir / "README.txt").read_text().split())  # unwrapped
    assert readme.index("Open it (macOS)") < readme.index("Open it (Windows)")  # this one first
    assert f"Double-click qpilot_{TOY_STUDY}.pzfx" in readme
    assert "Extract All" in readme and "Analyze" in readme and "New Graph" in readme
    assert "Welch's correction" in readme and "Mean with" in readme
    assert "File > Save" in readme and ".pzfx" in readme
    for gone in ("qpilot/prism/templates", "osascript", "NOT here yet", "run.pzc"):
        assert gone not in readme, gone
    assert "cannot write Prism's analyses or graphs" in readme  # honest about what it is
    assert "Not affiliated with or endorsed by GraphPad Software" in readme


def test_scripts_are_an_optional_extra(tmp_path, monkeypatch):
    inputs = toy_inputs()
    monkeypatch.setattr(_engine_export(), "demo_inputs", lambda *a, **k: inputs)
    result = export_study(
        _Store(), TOY_STUDY, tmp_path / "b", platform=host_platform(), scripts=True
    )
    names = {p.name for p in result.out_dir.iterdir()}
    assert {"run.pzc", "send_back.pzc", f"qpilot_{TOY_STUDY}.pzfx"} <= names
    run = (result.out_dir / "run.pzc").read_text()
    assert 'Import "T.csv"' in run and "T_replicates" not in run  # the template's layout only
    assert result.send_back is not None and result.scripts
    assert "Optional: the Prism scripts" in (result.out_dir / "README.txt").read_text()
    assert verify_provenance(result.out_dir) == []


def test_the_older_scripts_only_bundle_is_unchanged(tmp_path, monkeypatch):
    inputs = toy_inputs()
    monkeypatch.setattr(_engine_export(), "demo_inputs", lambda *a, **k: inputs)
    result = export_study(
        _Store(), TOY_STUDY, tmp_path / "b", platform=host_platform(), project=False
    )
    names = {p.name for p in result.out_dir.iterdir()}
    assert {"run.pzc", "send_back.pzc", "T.csv", "T2.csv", "sent_back"} <= names
    assert not any(n.endswith(".pzfx") for n in names)
    assert result.project is None and result.bundle.mode == "script"
    assert "qpilot/prism/templates" not in " ".join(result.notes)


def test_an_unsaved_project_brings_back_nothing_and_says_so(toy_export):
    result, _ = toy_export
    report = diff_report(_Store(), TOY_STUDY, result.out_dir, result.out_dir, proposals=False)
    assert report["source"] == "project" and report["items"] == []
    assert any("exactly as qPilot wrote it" in n for n in report["notes"])


def test_exclusions_deletions_and_edits_in_the_saved_project_become_questions(toy_export):
    result, inputs = toy_export
    root = _root(result.project)
    t = _table(root, "T log2")
    excluded = _cell(t, "a1", "A")
    excluded.set("Excluded", "1")
    _cell(t, "b2", "B").text = None  # deleted
    _cell(_table(root, "T2 log2"), "b3", "B").text = "9,5"  # changed, comma decimal
    _save(root, result.project)
    assert is_project_path(result.project) and is_project_path(result.out_dir)
    report = diff_report(_Store(), TOY_STUDY, result.out_dir, result.project)
    assert report["source"] == "project"
    items = {(i["kind"], i["table"], i["row"], i["column"]): i for i in report["items"]}
    assert set(items) == {
        ("excluded", "T", "a1", "A"),
        ("missing", "T", "b2", "B"),
        ("changed", "T2", "b3", "B"),
    }
    assert items[("excluded", "T", "a1", "A")]["note"] == EXCLUDED_PROJECT_NOTE
    assert items[("missing", "T", "b2", "B")]["note"] == DELETED_NOTE
    assert items[("changed", "T2", "b3", "B")]["note"] == CHANGED_PROJECT_NOTE
    assert items[("changed", "T2", "b3", "B")]["returned"] == 9.5
    assert float(excluded.text) == items[("excluded", "T", "a1", "A")]["exported"]
    proposals = {p["subject"]: p for p in report["proposals"]}
    exclusion = proposals["T/a1"]
    assert exclusion["kind"] == "prism.exclusion_reason" and exclusion["status"] == "proposed"
    assert exclusion["payload"]["question"] == "You excluded sample a1 for T in Prism. Reason?"
    assert exclusion["evidence"][0]["ref"] == "project:T!a1|A"
    assert exclusion["consequence"]["n_genes"] == 2
    deletion = proposals["T/b2"]
    assert deletion["payload"]["question"].startswith("You deleted sample b2 for T in Prism.")
    assert deletion["level"] == "High"
    assert not any("cannot tell" in r for r in deletion["reasons"])
    assert proposals["T2/b3"]["kind"] == "prism.value_edit"
    assert report["combined_consequence"]["n_genes"] == 2


def test_an_exclusion_in_the_table_of_all_genes_is_the_genes_own_cell(toy_export):
    result, _ = toy_export
    root = _root(result.project)
    grouped = _table(root, "All genes")
    genes = [d.text for d in grouped.findall("p:RowTitlesColumn/p:Subcolumn/p:d", NS)]
    titles = grouped.findall("p:SubColumnTitles/p:Subcolumn", NS)
    k = [s.findall("p:d", NS)[1].text for s in titles].index("b3")  # data set B, unit b3
    group_b = grouped.findall("p:YColumn", NS)[1]
    group_b.findall("p:Subcolumn", NS)[k].findall("p:d", NS)[genes.index("T2")].set("Excluded", "1")
    _cell(_table(root, "T log2"), "a1", "A").set("Excluded", "1")
    a1 = grouped.findall("p:YColumn", NS)[0].findall("p:Subcolumn", NS)[0]
    a1.findall("p:d", NS)[genes.index("T")].set("Excluded", "1")  # the same value twice
    _save(root, result.project)
    report = diff_report(_Store(), TOY_STUDY, result.out_dir, result.out_dir, proposals=False)
    found = sorted((i["kind"], i["table"], i["row"], i["column"]) for i in report["items"])
    assert found == [("excluded", "T", "a1", "A"), ("excluded", "T2", "b3", "B")]
    grouped_note = next(i["note"] for i in report["items"] if i["table"] == "T2")
    assert grouped_note.startswith(EXCLUDED_PROJECT_NOTE) and "all genes" in grouped_note


def test_a_replicate_excluded_in_the_nested_table_names_its_well(toy_export):
    result, _ = toy_export
    root = _root(result.replicates_project)
    table = _table(root, "T log2 RQ by replicate")
    first = table.findall("p:YColumn", NS)[0].findall("p:Subcolumn", NS)[1]  # unit a2
    first.findall("p:d", NS)[2].set("Excluded", "1")  # its third replicate
    _save(root, result.replicates_project)
    report = diff_report(_Store(), TOY_STUDY, result.out_dir, result.out_dir)
    (item,) = report["items"]
    assert (item["kind"], item["table"], item["row"], item["column"]) == (
        "excluded",
        "T_replicates",
        "rep 3",
        "A/a2",
    )
    (proposal,) = report["proposals"]
    assert proposal["subject"] == "T/a2/rep 3" and proposal["payload"]["well"].startswith("plate1/")


def test_only_the_main_project_given_leaves_the_nested_tables_alone(toy_export, tmp_path):
    result, _ = toy_export
    root = _root(result.project)
    _cell(_table(root, "T log2"), "a3", "A").set("Excluded", "1")
    saved = tmp_path / "home" / "my analysis.pzfx"
    saved.parent.mkdir()
    _save(root, saved)
    report = diff_report(_Store(), TOY_STUDY, result.out_dir, saved, proposals=False)
    assert [(i["kind"], i["row"]) for i in report["items"]] == [("excluded", "a3")]
    assert any("replicates project was not given" in n for n in report["notes"])


def test_an_already_accepted_exclusion_is_not_asked_again(toy_export):
    result, _ = toy_export
    root = _root(result.project)
    _cell(_table(root, "T log2"), "a1", "A").set("Excluded", "1")
    _save(root, result.project)
    report = diff_report(
        _Store(),
        TOY_STUDY,
        result.out_dir,
        result.out_dir,
        accepted=[accepted_exclusion("T", "a1")],
    )
    assert report["items"] and report["proposals"] == []


def test_renamed_tables_and_foreign_files_are_reported_not_guessed(toy_export, tmp_path):
    result, _ = toy_export
    root = _root(result.project)
    _table(root, "T log2").find("p:Title", NS).text = "T (mine)"
    _save(root, result.project)
    report = diff_report(_Store(), TOY_STUDY, result.out_dir, result.project, proposals=False)
    (item,) = (i for i in report["items"] if i["table"] == "T")
    assert item["kind"] == "unreadable" and "renamed or deleted" in item["note"]
    assert any("did not write" in n for n in report["notes"])
    other = tmp_path / "other.pzfx"
    other.write_bytes(b"<GraphPadPrismFile PrismXMLVersion='5.00'/>")
    with pytest.raises(RoundTripError, match="none of the tables"):
        diff_report(_Store(), TOY_STUDY, result.out_dir, other, proposals=False)
    linked = tmp_path / "linked"
    linked.mkdir()
    (linked / "x.pzfx").symlink_to(other)
    with pytest.raises(RoundTripError, match="a link, not read"):
        diff_report(_Store(), TOY_STUDY, result.out_dir, linked / "x.pzfx", proposals=False)
    (linked / "notes.txt").write_text("not a project")
    with pytest.raises(RoundTripError, match="no Prism project"):  # a link is never followed
        diff_report(_Store(), TOY_STUDY, result.out_dir, linked, proposals=False)


def test_the_csv_route_still_works_from_a_project_bundle(toy_export):
    result, _ = toy_export
    back = result.out_dir / "sent_back"
    back.mkdir()
    for table in result.bundle.tables:
        shutil.copy(result.out_dir / table.csv, back / table.csv)
    lines = (back / "T.csv").read_text().splitlines()
    lines[1] = lines[1].split(",")[0] + ",,"
    (back / "T.csv").write_text("\n".join(lines) + "\n")
    report = diff_report(_Store(), TOY_STUDY, result.out_dir, back, proposals=False)
    assert report["source"] == "sent_back"
    assert [(i["kind"], i["table"]) for i in report["items"]] == [("missing", "T")]
