"""The zipped exports: CSV tables equal the engine's values, the figures, the journal supplement
(the record verifies, the RDML carries qPilot's results and the person's exclusion)."""

from __future__ import annotations

import csv
import io
import zipfile

import pytest

from qpilot.core.record import unzip_record, verify
from qpilot.report.bundle import (
    BundleError,
    csv_zip,
    figures_zip,
    write_supplement,
)
from qpilot.report.figures import csv_value
from qpilot.report.rdml_out import EXCL_PREFIX, wells_from_table, write_back
from qpilot.report.tables import build_tables
from tests.report.conftest import LEFT_OUT, REASON


def _csv(archive: zipfile.ZipFile, name: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(archive.read(name).decode("utf-8"))))


def test_csv_tables_carry_the_exact_engine_values(walked):
    store, study = walked["store"], walked["study"]
    tables = build_tables(store, study)
    data = csv_zip(tables)
    assert data == csv_zip(tables)  # deterministic
    z = zipfile.ZipFile(io.BytesIO(data))
    assert sorted(z.namelist()) == sorted(
        [
            "README.txt",
            "results.csv",
            "per_unit.csv",
            "per_well.csv",
            "standard_curves.csv",  # the mini plates carry a ten-fold series (STD_100...)
            "quantities.csv",
            "decisions.csv",
            "settings.csv",
            "methods.csv",
            "miqe.csv",
            "about.csv",
        ]  # fmt: skip
    )
    assert {i.date_time for i in z.infolist()} == {(1980, 1, 1, 0, 0, 0)}
    con = store.get(study).contrasts
    for row in _csv(z, "results.csv"):
        c = con[row["gene"]]
        assert float(row["fold_change"]) == c.fc and float(row["p"]) == c.p  # exact
        assert float(row["ci95_low"]) == c.ci[0] and int(row["n_a"]) == c.n_hi
        assert row["headline"] in ("TRUE", "FALSE")
    units = _csv(z, "per_unit.csv")
    assert len(units) == 4 * len(con) and {u["wells"] for u in units} == {"3"}
    expected = {(u["gene"], u["biological_unit"]): u["log2_rq"] for u in
                tables.decided.per_unit.records()}  # fmt: skip
    assert {(u["gene"], u["biological_unit"]): float(u["log2_rq"]) for u in units} == expected
    assert len(_csv(z, "per_well.csv")) == 60
    about = {r["key"]: r["value"] for r in _csv(z, "about.csv")}
    assert about["decision_chain_head"] == store.chain_head(study)


def test_text_that_looks_like_a_formula_gets_an_apostrophe():
    assert csv_value("=HYPERLINK(1)") == "'=HYPERLINK(1)" and csv_value("@x") == "'@x"
    assert csv_value("1-Mar") == "1-Mar" and csv_value(-1.5) == "-1.5"
    assert csv_value(None) == "" and csv_value(True) == "TRUE" and csv_value(0.1) == "0.1"
    assert csv_value(float("nan")) == ""


def test_figures_zip(walked):
    tables = build_tables(walked["store"], walked["study"])
    data, figures = figures_zip(tables)
    names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
    assert figures.genes == ("1-Mar",)
    assert {
        "1-Mar.svg",
        "1-Mar.png",
        "1-Mar_source.csv",
        "1-Mar_caption.txt",
        "README.txt",
    } == names
    _, two = figures_zip(tables, ["1-Mar", "NOPE"])
    assert two.skipped and two.skipped[0][0] == "NOPE"
    with pytest.raises(BundleError, match="no figure"):
        figures_zip(tables, ["NOPE"])


def test_rdml_write_back_puts_results_and_the_exclusion_in_schema_order(excluded):
    store, study = excluded["store"], excluded["study"]
    tables = build_tables(store, study)
    wb = write_back(store.source(study), wells_from_table(tables.decided.per_well.records()))
    assert wb.n_wells == 60 and wb.n_excluded == 1 and wb.quantities
    xml = zipfile.ZipFile(io.BytesIO(wb.data)).read("rdml_data.xml").decode()
    assert f"<excl>{EXCL_PREFIX}{REASON}" in xml
    # cq, N0, ampEffMet, ampEff come right after <tar>, in the schema's order
    i = xml.index(f"<excl>{EXCL_PREFIX}")
    data = xml[xml.rindex("<data>", 0, i) : i]
    order = [t for t in ("<tar ", "<cq>", "<N0>", "<ampEffMet>", "<ampEff>") if t in data]
    assert order == ["<tar ", "<cq>", "<N0>", "<ampEffMet>", "<ampEff>"]
    assert [data.index(t) for t in order] == sorted(data.index(t) for t in order)
    assert write_back(store.source(study), wells_from_table(
        tables.decided.per_well.records())).data == wb.data  # fmt: skip


def test_the_supplement_has_everything_and_its_record_verifies(excluded, tmp_path):
    store, study = excluded["store"], excluded["study"]
    out = tmp_path / "supplement.zip"
    info = write_supplement(store, study, out)
    assert info.rdml_written_back and info.genes == ("1-Mar",) and info.input_included
    z = zipfile.ZipFile(out)
    names = set(z.namelist())
    for name in (
        "README.txt",
        f"qpilot-results-{study}.xlsx",
        "tables/results.csv",
        "tables/per_unit.csv",
        "tables/per_well.csv",
        "tables/miqe.csv",
        "tables/methods.csv",
        "tables/per_gene/1-Mar.csv",
        "figures/1-Mar.svg",
        "figures/1-Mar.png",
        "data/mini-qpilot.rdml",
        f"record/qpilot-record-{study}.zip",
    ):
        assert name in names, name
    readme = z.read("README.txt").decode()
    assert info.record_id in readme and "qpilot verify" in readme and "compliance" in readme
    about = {r["key"]: r["value"] for r in _csv(z, "tables/about.csv")}
    assert about["analysis_record_id"] == info.record_id
    miqe = _csv(z, "tables/miqe.csv")
    assert miqe and {"id", "status", "evidence"} <= set(miqe[0])
    left = [w for w in _csv(z, "tables/per_well.csv") if w["left_out"] == "TRUE"]
    assert [f"{w['plate']}/{w['well']}" for w in left] == [LEFT_OUT]
    record = tmp_path / "record.zip"
    record.write_bytes(z.read(f"record/qpilot-record-{study}.zip"))
    report = verify(unzip_record(record, tmp_path / "unzipped"))
    assert report.ok, report
    with pytest.raises(BundleError, match="already exists"):
        write_supplement(store, study, out)
