"""Excel export: the results table with a Trace column and the "Where to look" sheet.

Synthetic tests run in CI on the fixture study (no input file, so Trace does not run) and on
the Trace toy study (a context built from its per-well table); the ``demo_data`` test checks
the CAMTA2 row names well K22.
"""

import hashlib
import zipfile

import pytest

from qpilot.app_state import RESULT_COLUMNS, results_table
from qpilot.cli import main
from qpilot.core.store import StudyStore
from qpilot.report.excel import (
    ABOUT_SHEET,
    NOT_TRACED,
    RESULTS_SHEET,
    WHERE_COLUMNS,
    WHERE_SHEET,
    ExcelError,
    export_excel,
    where_rows,
)

openpyxl = pytest.importorskip("openpyxl")


def _sheets(path):
    book = openpyxl.load_workbook(path)
    return {name: list(book[name].iter_rows(values_only=True)) for name in book.sheetnames}


def _expected_results(result, trace_cells):
    table = results_table(result)
    rows = [tuple(v or None for v in row) for row in table.itertuples(index=False)]
    return [(*RESULT_COLUMNS, "Trace"), *((*r, c) for r, c in zip(rows, trace_cells, strict=True))]


@pytest.fixture
def store(tmp_studies_dir, fixture_result, fixture_cards):
    store = StudyStore(tmp_studies_dir)
    store.put(fixture_result, fixture_cards)
    return store


def test_without_the_input_file_the_results_are_written_and_trace_says_why(store, tmp_path):
    sid = store.list_studies()[0]
    ws = store.workspace(sid)
    before = {p.name: p.read_bytes() for p in ws.iterdir() if p.is_file()}
    info = export_excel(store, sid, tmp_path / "study.xlsx")
    assert (info.n_results, info.n_places, info.traced) == (58, 0, False)
    assert "input file is not known" in info.note
    sheets = _sheets(info.path)
    assert list(sheets) == [RESULTS_SHEET, WHERE_SHEET, ABOUT_SHEET]
    result = store.get(sid)
    assert sheets[RESULTS_SHEET] == _expected_results(result, [NOT_TRACED] * 58)
    assert sheets[WHERE_SHEET] == [WHERE_COLUMNS]
    about = dict(sheets[ABOUT_SHEET])
    assert about["study_id"] == sid and about["input_sha256"] == result.input_sha256
    assert about["trace"].startswith("Trace did not run: the study's input file")
    after = {p.name: p.read_bytes() for p in ws.iterdir() if p.is_file()}
    assert after == before  # nothing written to the workspace


def test_two_writes_are_byte_identical(store, tmp_path):
    sid = store.list_studies()[0]
    a = export_excel(store, sid, tmp_path / "a.xlsx").path.read_bytes()
    b = export_excel(store, sid, tmp_path / "b.xlsx").path.read_bytes()
    assert hashlib.sha256(a).hexdigest() == hashlib.sha256(b).hexdigest()
    with zipfile.ZipFile(tmp_path / "a.xlsx") as z:
        names = [i.filename for i in z.infolist()]
        assert names == sorted(names) and names[0] == "[Content_Types].xml"
        assert {i.date_time for i in z.infolist()} == {(1980, 1, 1, 0, 0, 0)}
        core = z.read("docProps/core.xml")
        assert b"2000-01-01T00:00:00Z" in core


def test_refusals(store, tmp_path):
    sid = store.list_studies()[0]
    with pytest.raises(ExcelError, match=r"\.xlsx"):
        export_excel(store, sid, tmp_path / "study.csv")
    (tmp_path / "taken.xlsx").write_bytes(b"x")
    with pytest.raises(ExcelError, match="already exists"):
        export_excel(store, sid, tmp_path / "taken.xlsx")
    with pytest.raises(ExcelError, match="does not exist"):
        export_excel(store, sid, tmp_path / "nowhere" / "study.xlsx")
    for top in (0, 51, True, "3"):
        with pytest.raises(ExcelError, match="top"):
            export_excel(store, sid, tmp_path / f"top{top}.xlsx", top=top)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["studies", "taken.xlsx"]


@pytest.fixture(scope="module")
def toy(tmp_path_factory):
    from tests.app.trace_toys import toy_store

    hostile = '=HYPERLINK("http://x.example")'
    return toy_store(tmp_path_factory.mktemp("toy") / "studies", sample_name=hostile)


def test_trace_rows_round_trip_with_the_top_place_in_the_results(toy, tmp_path):
    from qpilot.app_state import trace_cell
    from qpilot.qpcr import trace as T

    store, sid, ctx, result = toy
    info = export_excel(store, sid, tmp_path / "toy.xlsx", context=ctx)
    traces = {g: T.trace_gene(ctx, g, top=3) for g in result.contrasts}
    sheets = _sheets(info.path)
    assert sheets[RESULTS_SHEET] == _expected_results(
        result, [trace_cell(traces[g]) for g in results_table(result)["Gene"]]
    )
    down = dict((r[0], r[-1]) for r in sheets[RESULTS_SHEET][1:])["DOWN"]
    assert down.startswith("R1_20260101/") and down.endswith(": changes the call")
    assert sheets[WHERE_SHEET] == [WHERE_COLUMNS, *where_rows(traces)]
    first = dict(zip(WHERE_COLUMNS, sheets[WHERE_SHEET][1], strict=True))
    assert first["result"] == "DOWN" and first["rank"] == 1 and first["changes_call"] is True
    assert first["consequence"] == "changes the call" and first["checks"] == "S1"
    assert first["sample"] == '=HYPERLINK("http://x.example")'  # kept as text
    assert info.n_places == len(sheets[WHERE_SHEET]) - 1 and info.traced
    with zipfile.ZipFile(info.path) as z:
        xml = b"".join(z.read(n) for n in z.namelist() if n.startswith("xl/worksheets/"))
        assert b"<f>" not in xml  # no cell is a formula
    again = export_excel(store, sid, tmp_path / "again.xlsx", context=ctx)
    assert again.path.read_bytes() == info.path.read_bytes()


def test_cli_export_excel(store, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("QPILOT_STUDIES_DIR", str(store.root))
    out = tmp_path / "cli.xlsx"
    assert main(["export", "excel", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "58 results and 0 places to look" in printed and "Trace did not run" in printed
    assert _sheets(out)[RESULTS_SHEET][0][-1] == "Trace"
    assert main(["export", "excel", "--out", str(out)]) == 2  # never overwritten
    assert "already exists" in capsys.readouterr().err
    for extra in (["--share"], ["--genes", "ODC1"], ["--template", "two_groups_log2"],
                  ["--graphs", "png"]):  # fmt: skip
        assert main(["export", "excel", "--out", str(tmp_path / "x.xlsx"), *extra]) == 2
        assert "only apply to export prism" in capsys.readouterr().err
    assert not (tmp_path / "x.xlsx").exists()
    assert main(["export", "excel", "--study", "nope", "--out", str(tmp_path / "y.xlsx")]) == 2


@pytest.mark.demo_data
def test_demo_camta2_row_names_k22(demo_rdml_path, tmp_studies_dir, tmp_path):
    store = StudyStore(tmp_studies_dir)
    sid = store.ensure_study(demo_rdml_path)
    info = export_excel(store, sid, tmp_path / "demo.xlsx")
    assert info.traced and info.n_results == 58
    sheets = _sheets(info.path)
    trace = {row[0]: row[-1] for row in sheets[RESULTS_SHEET][1:]}
    assert trace["CAMTA2"] == "HMBS_20080318/K22 (2016): changes the call"
    camta2 = [dict(zip(WHERE_COLUMNS, r, strict=True)) for r in sheets[WHERE_SHEET][1:]
              if r[0] == "CAMTA2"]  # fmt: skip
    assert [(r["sample"], r["plate"], r["well"]) for r in camta2] == [
        ("2016", "HMBS_20080318", "K22"),
        ("1924", "HPRT1_20080303", "F23"),
        ("1772", "UBC(2)_20080220", "O13"),
    ]
    assert all(r["changes_call"] is True and r["checks"] == "S1" for r in camta2)
    assert camta2[0]["fold_off"] == pytest.approx(5.552, abs=1e-3)
    again = export_excel(store, sid, tmp_path / "again.xlsx")
    assert again.path.read_bytes() == info.path.read_bytes()
