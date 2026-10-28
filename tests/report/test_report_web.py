"""The exports over HTTP: the job formats, one gene's figure (info and files), the blind rule."""

from __future__ import annotations

import io
import zipfile

import pytest

from tests.web.conftest import wait_job

GENE = "1-Mar"


def _export(client, study, fmt, **body):
    r = client.post(f"/api/studies/{study}/report/export", json={"format": fmt, **body})
    assert r.status_code == 202, r.text
    job = wait_job(client, r.json()["job"])
    assert job["status"] == "done", job
    assert job["result_type"] == "ReportExported"
    return job["result"]


@pytest.mark.parametrize("fmt", ["csv", "figures"])
def test_csv_and_figures_are_report_exports(walked, fmt):
    c, store, study = walked["client"], walked["store"], walked["study"]
    out = _export(c, study, fmt, expected_head=store.chain_head(study))
    assert out["format"] == fmt and out["download"]["name"].endswith(".zip")
    assert out["head_moved"] is False and out["bases"] == ["as_decided"]
    data = c.get(out["download"]["url"])
    assert data.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(data.content)).namelist()
    assert ("results.csv" in names) if fmt == "csv" else (f"{GENE}.svg" in names)
    if fmt == "figures":
        assert out["genes"] == [GENE]
    listed = c.get(f"/api/studies/{study}/report/exports").json()["exports"]
    assert listed[0]["format"] == fmt


def test_the_supplement_is_bound_to_its_record(walked):
    c, store, study = walked["client"], walked["store"], walked["study"]
    store.append_decision(study, "card_undetermined", "cap", "very low, not missing", "human", None)
    out = _export(c, study, "supplement")
    assert out["record"]["record_id"] and out["record"]["verify"].startswith("qpilot verify ")
    assert out["bases"] == ["as_decided", "recommended"]
    assert any("recommended analysis too" in w for w in out["warnings"])
    z = zipfile.ZipFile(io.BytesIO(c.get(out["download"]["url"]).content))
    assert "tables/results_recommended.csv" in z.namelist()
    assert c.get(out["record"]["download"]["url"]).status_code == 200


def test_one_gene_s_figure_info_and_files(walked):
    c, study = walked["client"], walked["study"]
    info = c.get(f"/api/studies/{study}/report/figure/info", params={"gene": GENE})
    assert info.status_code == 200, info.text
    view = info.json()
    assert view["gene"] == GENE and view["comparison"] == "KO vs WT"
    assert [g["n"] for g in view["groups"]] == [2, 2] and view["basis"] == "as_decided"
    assert view["call"] == "none" and "Welch's t test" in view["caption"]
    svg = c.get(view["files"]["svg"])
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml")
    assert svg.text.count('<circle class="unit"') == 4
    png = c.get(view["files"]["png"] + "&download=true")
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert png.headers["content-disposition"] == 'attachment; filename="1-Mar.png"'
    data = c.get(view["files"]["csv"])
    assert data.text.splitlines()[0].startswith("analysis,comparison,gene,group")
    assert c.get(f"/api/studies/{study}/report/figure", params={"gene": "NOPE"}).status_code == 404
    bad = c.get(f"/api/studies/{study}/report/figure", params={"gene": GENE, "format": "pdf"})
    assert bad.status_code == 422
    other = c.get(
        f"/api/studies/{study}/report/figure/info", params={"gene": GENE, "basis": "recommended"}
    )
    assert other.status_code == 200 and other.json()["bases"] == ["as_decided"]


def test_figures_and_exports_go_blind_when_the_design_reopens(walked):
    from qpilot.mcp_server import QpilotTools

    c, store, sid, study = walked["client"], walked["store"], walked["sid"], walked["study"]
    done = _export(c, study, "csv")
    QpilotTools(store).qpcr_propose(sid, "design.group", "WT_1", {"group": "KO"})
    listed = c.get(f"/api/sessions/{sid}/proposals", params={"stage": "design"}).json()
    change = next(
        p for p in listed["proposals"] if p["status"] == "proposed" and p["kind"] == "design.group"
    )
    r = c.post(
        f"/api/sessions/{sid}/proposals/{change['id']}/accept",
        json={"reason": "the lab book says KO", "expected_head": listed["head"]},
    )
    assert r.status_code == 200 and not r.json()["results_visible"], r.text
    for response in (
        c.get(f"/api/studies/{study}/report/figure/info", params={"gene": GENE}),
        c.get(f"/api/studies/{study}/report/figure", params={"gene": GENE, "format": "png"}),
        c.post(f"/api/studies/{study}/report/export", json={"format": "figures"}),
        c.post(f"/api/studies/{study}/report/export", json={"format": "supplement"}),
        c.get(done["download"]["url"]),
    ):
        assert response.status_code == 403, response.text[:200]
        assert response.json()["error"]["code"] == "blind"


def test_cli_exports(walked, monkeypatch, tmp_path, capsys):
    from qpilot.cli import main

    store, study = walked["store"], walked["study"]
    monkeypatch.setenv("QPILOT_STUDIES_DIR", str(store.root))
    out = tmp_path / "tables.zip"
    assert main(["export", "--format", "csv", "--study", study, "--out", str(out)]) == 0
    assert "results.csv" in zipfile.ZipFile(out).namelist()
    figs = tmp_path / "figures.zip"
    args = ["export", "figures", "--study", study, "--genes", f"{GENE},NOPE", "--out", str(figs)]
    assert main(args) == 0
    printed = capsys.readouterr().out
    assert f"figures of {GENE}" in printed and "Not drawn: NOPE" in printed
    supp = tmp_path / "supplement.zip"
    assert main(["export", "supplement", "--study", study, "--out", str(supp)]) == 0
    assert "Analysis Record" in capsys.readouterr().out
    refused = [
        ["export", "csv", "--genes", GENE],
        ["export", "csv", "--basis", "recommended"],
        ["export", "xlsx", "--format", "csv"],
        ["export", "figures", "--share"],
    ]
    for extra in refused:
        assert main([*extra, "--study", study, "--out", str(tmp_path / "x.zip")]) == 2
    assert main(["export", "csv", "--study", study, "--out", str(out)]) == 2  # never overwritten
    assert not (tmp_path / "x.zip").exists()
