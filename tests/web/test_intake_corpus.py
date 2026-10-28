"""Real lab files open on the page, with the names their people gave them.

Every set of the public corpus (``tests/fixtures/corpus``) that holds real curves or Cq values
is dropped on ``POST /api/workspaces`` as a person would drop it (the whole folder, and each
RDML or workbook alone), opened as a Studio session, and the rules propose its design. A
person's own Excel Cq table opens as Cq values with its own sample sheet (its sample, condition
and gene-type columns, never its numbers); a report names an imported export by its files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qpilot.io import inputs
from tests.web.conftest import wait_job

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"
NOT_DATA = {"MANIFEST.yaml", "truth.csv", ".gitattributes", "README.md"}
HMUY = CORPUS / "rdml" / "lightcycler96-lc96p-hmuy"
TABLE = HMUY / "hmuy_cq_values.xlsx"
LC96P = HMUY / "hmuy_hm_vs_dip_r123.lc96p"
SYNTH_CFX = CORPUS / "synthetic" / "cfx-manager-raw-vs-baseline-subtracted"
SAMPLES = "Sample,Group\nS1,A\nS2,A\nS3,A\nS4,A\nS5,B\nS6,B\nS7,B\nS8,B\n"


def data_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_file() and p.name not in NOT_DATA)


def drop(client, paths: list[Path], sheet: tuple[str, bytes] | None = None):
    parts = [("files", (p.name, p.read_bytes(), "application/octet-stream")) for p in paths]
    if sheet is not None:
        parts.append(("sheet", (sheet[0], sheet[1], "text/csv")))
    return client.post("/api/workspaces", files=parts)


def opened(client, paths: list[Path], sheet=None) -> tuple[str, dict]:
    r = drop(client, paths, sheet)
    assert r.status_code == 202, r.text
    job = wait_job(client, r.json()["job"])
    assert job["status"] == "done", job
    return job["result"]["key"], job


def design(client, sid: str) -> list[dict]:
    r = client.post(f"/api/sessions/{sid}/propose/design")
    assert r.status_code == 202, r.text
    assert wait_job(client, r.json()["job"])["status"] == "done"
    r = client.get(f"/api/sessions/{sid}/proposals", params={"stage": "design"})
    return r.json()["proposals"]


# ---- every corpus set that holds curves or Cq values opens -----------------------------------

#: slug -> (plates, wells) as the page reports them when the whole folder is dropped.
OPENS = {
    "biorad/covmatic-cfx-maestro-4.0-simulated-4plex": (1, 96),
    "biorad/hsieh2016-cfx-manager-3.1-sybr": (3, 209),
    "biorad/urtecho-cfx-tsv-baseline-subtracted": (1, 95),
    "rdml/cfx-manager-3.0-rdml-1.1-nonstandard-member": (2, 60),
    "rdml/cfx-manager-3.0-rdml-1.2-rpa": (1, 90),
    "rdml/lightcycler96-lc96p-hmuy": (1, 96),
    "rdml/lightcycler96-rdml-1.1": (1, 96),
    "rdml/linregpcr-rdml-1.3-lc480-kphaffii": (6, 432),
    "rdml/rdml-1.2-cq-only-soybean": (17, 1428),
    "rdml/stepone-2.3-rdml-1.0": (1, 24),
    "roche/mendeley-diras2-lc480-raw-and-cp": (1, 384),
    "roche/sanger-lc480-cp-table": (1, 384),
    "synthetic/cfx-manager-raw-vs-baseline-subtracted": (2, 160),
    "synthetic/quantstudio-design-analysis-rn-drn": (1, 80),
    "thermofisher/allotropy-quantstudio-rtpcr-txt": (6, 216),
    "thermofisher/opentrons-7500-design-analysis-csv": (1, 51),
    "thermofisher/securebio-qs3-design-analysis-2.7": (2, 186),
    "thermofisher/zamanian-stepone-plus-sybr-sections": (1, 57),
}
#: Sets the page refuses as a whole, in words (each file of them alone is tried below).
REFUSED = {
    "roche/nomads-lc480-raw-isothermal-not-pcr": "not a PCR run",
    "rdml/quantstudio7pro-rdml-1.2-edna": "one RDML file at a time",
}


def test_every_corpus_set_is_listed():
    sets = {str(p.parent.relative_to(CORPUS)) for p in CORPUS.rglob("MANIFEST.yaml")}
    assert sets == set(OPENS) | set(REFUSED)


@pytest.mark.parametrize("slug", sorted(OPENS))
def test_each_corpus_set_opens_and_its_design_is_proposed(sclient, slug):
    sid, _ = opened(sclient, data_files(CORPUS / slug))
    facts = sclient.get(f"/api/sessions/{sid}").json()["facts"]
    assert (facts["n_plates"], facts["n_wells"]) == OPENS[slug]
    assert facts["n_targets"] >= 1 and facts["n_samples"] >= 1
    design(sclient, sid)  # the rules run on every file (some files give them nothing to say)


@pytest.mark.parametrize("slug", sorted(REFUSED))
def test_a_set_that_cannot_open_as_a_whole_says_why(sclient, slug):
    r = drop(sclient, data_files(CORPUS / slug))
    if r.status_code == 202:
        job = wait_job(sclient, r.json()["job"])
        assert job["status"] == "failed"
        message = job["error"]["message"]
    else:
        message = r.json()["error"]["message"]
    assert REFUSED[slug] in message


@pytest.mark.parametrize(
    "path",
    sorted(p for p in (CORPUS / "rdml").rglob("*") if p.suffix in (".rdml", ".lc96p", ".xlsx")),
    ids=lambda p: p.name,
)
def test_each_rdml_file_and_workbook_opens_alone(sclient, path):
    sid, _ = opened(sclient, [path])
    assert sclient.get(f"/api/sessions/{sid}").json()["facts"]["n_wells"] > 0


# ---- LightCycler 96: names from the file, the depositors' table as its sheet --------------


def test_the_lc96_folder_opens_with_real_names_and_the_tables_sample_columns(sclient):
    sid, job = opened(sclient, [LC96P, TABLE])
    assert job["result"]["unused"] == []
    view = sclient.get(f"/api/sessions/{sid}").json()
    assert view["facts"]["sheet_name"] == "hmuy_cq_values (sample columns).csv"
    summary = view["summary"]
    assert {s["sample"] for s in summary["samples"]} >= {"Hm_1", "Hm_3", "DIP_1", "DIP_3"}
    assert {t["target"] for t in summary["targets"]} == {
        "HmuYPe",
        "16S rRNA",
        "no target (SYBR Green I)",
    }
    groups = {p["subject"]: p["payload"]["group"] for p in design(sclient, sid)
              if p["kind"] == "design.group"}  # fmt: skip
    assert groups == {"Hm_1": "Hm", "Hm_2": "Hm", "Hm_3": "Hm",
                      "DIP_1": "DIP", "DIP_2": "DIP", "DIP_3": "DIP"}  # fmt: skip
    quarantine = sclient.get(f"/api/sessions/{sid}/quarantine").text
    assert "23.4" not in quarantine and "Cq Mean" not in quarantine  # no number beside a group


def test_a_persons_cq_table_alone_opens_with_groups_and_its_reference_gene(sclient):
    sid, _ = opened(sclient, [TABLE])
    view = sclient.get(f"/api/sessions/{sid}").json()
    capture = view["capture"]
    assert capture["connector"] == "tidy" and capture["rawness"]["verdict"] == "cq_only"
    assert {"DECLARED_REFERENCES", "CQ_ONLY"} <= {w["code"] for w in capture["warnings"]}
    targets = {t["target"]: t["declared_type"] for t in view["summary"]["targets"]}
    assert targets == {"hmuYPe": "toi", "16S rRNA": "ref"}
    notes = view["summary"]["notes"]
    assert any("Cq values only" in n for n in notes)
    assert not any("LinRegPCR could not analyse" in n for n in notes)  # nothing failed
    assert view["facts"]["sheet_name"] == "hmuy_cq_values (sample columns).csv"
    proposals = design(sclient, sid)
    roles = {p["subject"]: p["payload"] for p in proposals if p["kind"] == "design.target_role"}
    assert roles.get("16S rRNA") == {"role": "ref"}
    assert {p["payload"]["group"] for p in proposals if p["kind"] == "design.group"} == {
        "Hm",
        "DIP",
    }


# ---- the person's own file names, wherever a source is named ----------------------------------


def test_an_imported_export_is_named_by_its_files_not_by_qpilots_copy(sclient, studio_ctx):
    files = sorted(SYNTH_CFX.glob("qpilot-synthetic-raw *"))
    sid, _ = opened(sclient, files, sheet=("samples.csv", SAMPLES.encode()))
    studio = studio_ctx.studio
    source = studio.source(sid)
    assert len(source.stem) == 20  # qPilot's content-named copy ...
    assert inputs.is_converted(source)
    named = inputs.input_files(source)
    assert [f.name for f in named] == [p.name for p in files]  # ... its files, by their names
    assert all(len(f.sha256) == 64 for f in named)
    from qpilot.mcp_server import QpilotTools

    studio.propose_design(sid)
    QpilotTools(studio.store).qpcr_propose(sid, "design.target_role", "REF", {"role": "ref"})
    for p in studio.inbox(sid, "design", "proposed"):
        studio.accept(sid, p.id, "human", "checked")
    comparison = studio.propose_comparison(sid)
    studio.accept(sid, comparison.proposal.id, "human", "A is the reference")
    for stage in ("design", "curves"):
        if stage == "curves":
            studio.propose_curves(sid)
            for p in studio.inbox(sid, "curves", "proposed"):
                studio.accept(sid, p.id, "human", "checked")
        confirm = studio.propose_confirm(sid, stage)
        studio.accept(sid, confirm.proposal.id, "human")
    study = studio.study(sid)
    report = sclient.get(f"/api/studies/{study}/report").json()
    label = inputs.input_label(source)
    assert report["header"]["source_name"] == label
    assert label.startswith("qpilot-synthetic-raw -  Quantification")
    assert source.name not in str(report)  # never the hashed copy's name
    assert report["header"]["input_sha256"] == studio.store.get(study).input_sha256
    methods = " ".join(
        part if isinstance(part, str) else str(part.get("text", ""))
        for paragraph in report["methods"]["paragraphs"]
        for part in (paragraph["text"].get("parts") or [])
    )
    assert "instrument export" in str(report["methods"]) or "instrument export" in methods


def test_a_cq_table_given_as_the_sheet_of_an_rdml_file_is_read_as_its_sample_columns(sclient):
    lc96 = CORPUS / "rdml" / "lightcycler96-lc96p-hmuy" / "hmuy_hm_vs_dip_r123.lc96p"
    files = {
        "rdml": ("hmuy r123.rdml", lc96.read_bytes(), "application/octet-stream"),
        "sheet": (TABLE.name, TABLE.read_bytes(), "application/octet-stream"),
    }
    r = sclient.post("/api/workspaces", files=files)
    assert r.status_code == 202, r.text
    job = wait_job(sclient, r.json()["job"])
    assert job["status"] == "done", job
    view = sclient.get(f"/api/sessions/{job['result']['key']}").json()
    assert view["facts"]["sheet_name"] == "hmuy_cq_values (sample columns).csv"
    assert "23.4" not in sclient.get(f"/api/sessions/{job['result']['key']}/quarantine").text
