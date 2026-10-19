"""The readers on main against the red team's adversarial files (tests/redteam/adversarial).

Contract for every reader: refuse with its own typed error, or read with every string kept as
data; never hang, never resolve an entity or include, never raise anything else. Findings:

* RT-005: ``core.record.unzip_record`` lets ``OSError`` escape on a member named ``.`` or a
  file member that is also a folder (``qpilot verify`` prints a traceback instead of
  ``qpilot verify: unsafe ...``); containment itself held on every case.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from qpilot.core.record import RecordError, unzip_record
from qpilot.io.rdml_io import RdmlLoadError, load
from qpilot.io.sheets import SheetError, read_sheet, sheet_table
from tests.redteam.adversarial import FORMULA_CELLS, csv_cases, xlsx_cases, xml_cases, zip_cases

SECRET_TEXT = "redteam-secret-7f3a"
SLOW_S = 20.0


@pytest.fixture
def secret(tmp_path: Path) -> Path:
    path = tmp_path / "secret.txt"
    path.write_text(SECRET_TEXT, encoding="utf-8")
    return path


def _xml_text(doc) -> str:
    from lxml import etree

    return etree.tostring(doc._rdmlData).decode("utf-8", "replace")


@pytest.mark.parametrize("case", sorted(xml_cases()))
def test_the_rdml_loader_refuses_or_reads_hostile_xml_safely(
    case: str, tmp_path: Path, secret: Path
) -> None:
    path = xml_cases(secret)[case](tmp_path / "in")
    start = time.monotonic()
    try:
        doc = load(path)
    except RdmlLoadError:
        doc = None
    assert time.monotonic() - start < SLOW_S
    if doc is not None:
        text = _xml_text(doc)
        assert SECRET_TEXT not in text  # no external entity, no XInclude
        assert "lollollol" not in text  # no entity expansion


@pytest.mark.parametrize("case", sorted(csv_cases()))
def test_the_sheet_reader_refuses_or_reads_hostile_csv_safely(case: str, tmp_path: Path) -> None:
    path = csv_cases()[case](tmp_path / "in")
    start = time.monotonic()
    try:
        read = read_sheet(path)
    except SheetError:
        return
    finally:
        assert time.monotonic() - start < SLOW_S
    assert len(read.cells) + len(read.sheets) == len(read.quarantine)
    for value in read.values.values():
        assert isinstance(value, str)  # a CSV cell is text: nothing evaluated or converted


def test_formula_cells_stay_text_and_are_quarantined(tmp_path: Path) -> None:
    read = read_sheet(csv_cases()["printable_names.csv"](tmp_path))
    quoted = {entry.value for entry in read.quarantine}
    for cell in FORMULA_CELLS:
        assert cell in quoted


def test_a_utf8_bom_does_not_hide_the_first_header(tmp_path: Path) -> None:
    table = sheet_table(read_sheet(csv_cases()["bom_utf8.csv"](tmp_path)))
    assert table is not None and "sample" in table.columns


@pytest.mark.parametrize("case", sorted(xlsx_cases()))
def test_the_sheet_reader_refuses_or_reads_hostile_xlsx_safely(
    case: str, tmp_path: Path, secret: Path
) -> None:
    path = xlsx_cases(secret)[case](tmp_path / "in")
    start = time.monotonic()
    try:
        read = read_sheet(path)
    except SheetError:
        return
    finally:
        assert time.monotonic() - start < SLOW_S
    joined = " ".join(str(v) for v in read.values.values())
    assert SECRET_TEXT not in joined
    assert "lollollol" not in joined
    assert not (tmp_path / "escaped.xml").exists()
    if case == "formulas.xlsx":  # data_only: the cached value or nothing, never the formula run
        assert "example.invalid" not in joined


ESCAPES = ("escaped.txt", "qpilot_redteam_absolute.txt")


@pytest.mark.parametrize(
    "case",
    [
        c
        if c not in {"dot_member.zip", "file_then_dir.zip"}
        else pytest.param(c, marks=pytest.mark.xfail(strict=True, reason="RT-005"))
        for c in sorted(zip_cases())
    ],
)
def test_unzip_record_refuses_escaping_or_broken_zips_with_record_error(
    case: str, tmp_path: Path
) -> None:
    path = zip_cases()[case](tmp_path / "in")
    target = tmp_path / "out" / "record"
    try:
        unzip_record(path, target)
    except RecordError:
        pass
    for name in ESCAPES:
        assert not (tmp_path / "out" / name).exists()
        assert not (tmp_path / name).exists()
    assert not Path("/tmp/qpilot_redteam_absolute.txt").exists()
    results = target / "results.json"
    assert not results.is_symlink()
