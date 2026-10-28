"""The workbook holds numbers as numbers: typed cells, number formats, units, frozen headers."""

from __future__ import annotations

import io
import zipfile

import pytest

from qpilot.report.excel import NUMBER_FORMATS, excel_bytes
from qpilot.report.tables import build_tables

openpyxl = pytest.importorskip("openpyxl")


def _book(store, study, **kw):
    data, info = excel_bytes(store, study, trace=False, **kw)
    return openpyxl.load_workbook(io.BytesIO(data)), info, data


def _header(sheet):
    return [c.value for c in next(sheet.iter_rows(min_row=1, max_row=1))]


def test_numbers_are_number_cells_with_formats_and_units(walked):
    store, study = walked["store"], walked["study"]
    book, info, _ = _book(store, study)
    assert info.sheets == tuple(book.sheetnames)
    assert book.sheetnames == [
        "Results",
        "Per unit",
        "Per well",
        "Where to look",
        "Decisions",
        "Settings",
        "Methods",
        "About",
    ]
    results = book["Results"]
    header = _header(results)
    for words in ("Fold change (×, A / B)", "95 % CI low (×)", "95 % CI high (×)",
                  "p (Welch's t test)", "n A (biological units)"):  # fmt: skip
        assert words in header
    con = store.get(study).contrasts
    row = next(r for r in results.iter_rows(min_row=2) if r[header.index("Gene")].value == "1-Mar")
    cell = {h: c for h, c in zip(header, row, strict=True)}
    assert cell["Gene"].data_type == "s" and cell["Gene"].value == "1-Mar"  # never a date
    for key, fmt in (
        ("Fold change (×, A / B)", "fold"),
        ("95 % CI low (×)", "fold"),
        ("95 % CI high (×)", "fold"),
        ("p (Welch's t test)", "p"),
        ("n A (biological units)", "int"),
    ):
        assert cell[key].data_type == "n", key
        assert cell[key].number_format == NUMBER_FORMATS[fmt]
    assert cell["Fold change (×, A / B)"].value == pytest.approx(con["1-Mar"].fc, rel=1e-15)
    assert cell["95 % CI low (×)"].value == pytest.approx(con["1-Mar"].ci[0], rel=1e-15)
    assert cell["Headline gene"].data_type == "b"
    assert results.freeze_panes == "E2" and results.auto_filter.ref.startswith("A1:")
    assert results.column_dimensions["A"].width > 0
    per_unit = book["Per unit"]
    assert "ΔCq (cycles, gene − reference genes)" in _header(per_unit)
    assert "log2 relative quantity (log2 RQ; the value tested)" in _header(per_unit)
    assert per_unit.max_row - 1 == 4 * len(con)  # one row per biological unit and gene
    per_well = book["Per well"]
    assert per_well.max_row - 1 == 60 and per_well.freeze_panes == "C2"
    cq = _header(per_well).index("Cq (cycles, TD0)")
    assert all(r[cq].data_type == "n" for r in per_well.iter_rows(min_row=2) if r[cq].value)
    about = dict(book["About"].iter_rows(min_row=2, values_only=True))
    assert about["analysis"].startswith("As decided")
    assert about["decision_chain_head"] == store.chain_head(study)
    assert about["input_sha256"] == store.get(study).input_sha256


def test_two_analyses_when_a_choice_is_not_the_recommended_one(walked):
    store, study = walked["store"], walked["study"]
    store.append_decision(study, "card_undetermined", "cap", "very low, not missing", "human", None)
    book, info, _ = _book(store, study, record_id="r" * 64)
    assert info.bases == ("as_decided", "recommended")
    assert (
        "Results (recommended)" in book.sheetnames and "Per unit (recommended)" in book.sheetnames
    )
    settings = list(book["Settings"].iter_rows(min_row=2, values_only=True))
    row = next(r for r in settings if r[0].endswith("wells that never amplified"))
    assert row[3] == "a person" and row[1] != row[2]
    about = dict(book["About"].iter_rows(min_row=2, values_only=True))
    assert about["analysis_record_id"] == "r" * 64


def test_deterministic_and_no_cell_is_a_formula(walked):
    store, study = walked["store"], walked["study"]
    tables = build_tables(store, study)
    _, _, a = _book(store, study, tables=tables)
    _, _, b = _book(store, study, tables=tables)
    assert a == b
    with zipfile.ZipFile(io.BytesIO(a)) as z:
        xml = b"".join(z.read(n) for n in z.namelist() if n.startswith("xl/worksheets/"))
    assert b"<f>" not in xml
