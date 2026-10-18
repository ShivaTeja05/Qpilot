"""Read a sample sheet (``.xlsx`` or ``.csv``) safely: every cell is untrusted text.

A sample sheet says which sample is in which group, which animal it came from and which wells
are controls. It comes from a person, a LIMS export or a collaborator, so it is treated like
any other input file:

* size caps run before anything is parsed (:data:`MAX_FILE_BYTES`; a workbook's zip members
  may not inflate past :data:`MAX_XML_BYTES` in total or more than :data:`MAX_ZIP_RATIO` times);
  after parsing, at most :data:`MAX_SHEETS` sheets and :data:`MAX_ROWS` x :data:`MAX_COLUMNS`
  cells with values;
* workbooks are opened by openpyxl in read-only, data-only mode: formulas are never evaluated
  (a formula cell gives the value Excel cached when it last saved the file, or nothing);
* merged cells are expanded, so every cell a merged range covers carries the range's value; a
  sheet lists at most :data:`MAX_MERGED_RANGES` merged ranges, a range listed twice counts once,
  and all the ranges of a workbook together cover at most :data:`MAX_CELLS` cells (Excel never
  writes overlapping ranges, so a file whose ranges overlap cannot multiply the work);
* every non-empty cell becomes a :class:`~qpilot.schemas_studio.QuarantineEntry` with origin
  ``sheet:<file name>!<Sheet>!<A1>`` and a :class:`~qpilot.schemas_studio.SheetCell` that cites
  it by ``text_id``. Nothing here interprets the text beyond finding a header row;
* cells Excel stored as dates are reported, never silently converted back: openpyxl returns a
  ``datetime`` for them, which is how gene names such as ``MARCH1`` or ``SEPT2`` look after
  Excel turned them into ``1-Mar`` and ``2-Sep``.

:func:`sheet_table` finds the header row (tolerant of case, separators and common
abbreviations) and returns the rows as dictionaries of strings for the deterministic design
rules (``qpilot.qpcr.design_rules``).
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from qpilot.schemas_studio import QuarantineEntry, SheetCell, text_id_for

MAX_FILE_BYTES = 5 * 1024 * 1024  # the sheet file itself
MAX_XML_BYTES = 200 * 1024 * 1024  # all members of an .xlsx, uncompressed
MAX_ZIP_RATIO = 100
MAX_SHEETS = 50
MAX_ROWS = 20_000
MAX_COLUMNS = 200
MAX_CELLS = 1_000_000  # non-empty cells after merged ranges are expanded
MAX_MERGED_RANGES = 10_000  # merged ranges on one sheet
HEADER_SCAN_ROWS = 30
SUFFIXES = (".xlsx", ".xlsm", ".csv", ".tsv", ".txt")

DATE_FLAG = "date_like"


class SheetError(Exception):
    """The sheet is not a readable, safe spreadsheet within the size caps."""


@dataclass
class SheetRead:
    """Everything read from one sheet file.

    Attributes:
        file_name: The file's name (no directories).
        sha256: sha256 of the file's bytes.
        cells: One :class:`SheetCell` per non-empty cell, sheet by sheet, row by row.
        quarantine: One entry per non-empty cell (same order as ``cells``) plus one per sheet
            title; the caller stores them.
        values: Cell reference (``Sheet1!B2``) -> the value as openpyxl or the CSV reader gave
            it (``str``, ``int``, ``float``, ``bool`` or ``datetime``). For deterministic code
            only; never shown to a model except through the quarantine.
        date_cells: References of cells stored as dates (possible date-mangled names).
        sheets: Sheet titles in workbook order (a CSV file has one, its file stem).
        notes: Plain-English remarks (date cells found, merged ranges cut at the caps).
    """

    file_name: str
    sha256: str
    cells: list[SheetCell] = field(default_factory=list)
    quarantine: list[QuarantineEntry] = field(default_factory=list)
    values: dict[str, Any] = field(default_factory=dict)
    date_cells: list[str] = field(default_factory=list)
    sheets: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def text(self, ref: str) -> str:
        """The cell's value as text (``""`` for an empty cell); see :func:`cell_text`."""
        return cell_text(self.values.get(ref))


@dataclass
class SheetTable:
    """The table found on one sheet.

    Attributes:
        sheet: Sheet title.
        header_row: 1-based row of the header.
        columns: Canonical field (``sample``, ``group``, ``bio_unit``, ``bio_rep``, ``type``,
            ``target``, ``quantity``, ``concentration``, ``dilution``, ``replicate``, ``well``)
            -> 1-based column number. Only the first column recognised for a field is used.
            ``quantity`` is a standard's known quantity; ``concentration`` (also an input
            amount) and ``dilution`` describe any sample.
        headers: Column number -> header text (unrecognised headers included).
        rows: One dictionary per data row: canonical field -> value text, plus
            ``"col<N>"`` -> value text for every other non-empty column.
        refs: Same shape as ``rows``: field -> cell reference (``Sheet1!B5``).
        row_numbers: 1-based sheet row of each entry in ``rows``.
        date_cells: Cells in the table body stored as dates, or written the way Excel shows a
            date it made from a name (``1-Mar``, ``Sep-02``).
        skipped_rows: Rows after the header without a sample value (units rows, blank rows,
            footers).
    """

    sheet: str
    header_row: int
    columns: dict[str, int]
    headers: dict[int, str]
    rows: list[dict[str, str]]
    refs: list[dict[str, str]]
    row_numbers: list[int]
    date_cells: list[str] = field(default_factory=list)
    skipped_rows: list[int] = field(default_factory=list)


# ---------------------------------------------------------------------------------------------
# Header vocabulary (compared after lowercasing and removing everything but letters and digits)
# ---------------------------------------------------------------------------------------------

#: canonical field -> accepted header spellings (already squashed).
HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "sample": (
        "sample",
        "samples",
        "samplename",
        "sampleid",
        "samplelabel",
        "samplecode",
        "sampleno",
        "samplenumber",
        "specimen",
        "specimenid",
        "name",
        "smp",
    ),
    "group": (
        "group",
        "grp",
        "groups",
        "groupname",
        "condition",
        "cond",
        "treatment",
        "treat",
        "trt",
        "genotype",
        "cohort",
        "arm",
        "class",
        "biologicalgroup",
        "biologicalgroupname",
        "biogroup",
        "biogroupname",
        "phenotype",
    ),
    "bio_unit": (
        "animal",
        "animalid",
        "animalno",
        "mouse",
        "mouseid",
        "mouseno",
        "rat",
        "ratid",
        "patient",
        "patientid",
        "donor",
        "donorid",
        "subject",
        "subjectid",
        "individual",
        "individualid",
        "biologicalunit",
        "biounit",
        "organism",
        "plant",
        "plantid",
        "culture",
        "cultureid",
    ),
    "bio_rep": (
        "biologicalreplicate",
        "biologicalrep",
        "biorep",
        "biorepl",
        "bioreplicate",
        "biolrep",
    ),
    "type": (
        "type",
        "task",
        "sampletype",
        "welltype",
        "content",
        "role",
        "wellrole",
        "sampletargettype",
        "relquantcombinedsampletargettype",
        "combinedsampletargettype",
    ),
    "target": (
        "target",
        "targetname",
        "gene",
        "genename",
        "genesymbol",
        "assay",
        "assayname",
        "primer",
        "primers",
        "detector",
        "detectorname",
    ),
    # A standard's known quantity. "Given Conc" is LightCycler's column for standards alone.
    "quantity": (
        "quantity",
        "qty",
        "copies",
        "copynumber",
        "startingquantity",
        "sq",
        "givenconc",
    ),
    # Columns that describe every sample (an RNA concentration, the input of a reaction, the
    # dilution of every cDNA); they give a standard's quantity only for a marked standard. An
    # amount of a named material ("RNA quantity", "Input quantity") is such an input too.
    "concentration": (
        "concentration",
        "conc",
        "inputamount",
        "inputquantity",
        "rnaquantity",
        "cdnaquantity",
        "dnaquantity",
        "templatequantity",
        "rnaamount",
        "cdnaamount",
        "dnaamount",
        "templateamount",
    ),
    "dilution": (
        "dilution",
        "dilutionfactor",
    ),
    "replicate": (
        "replicate",
        "rep",
        "techrep",
        "technicalreplicate",
        "technicalrep",
        "replicateno",
    ),
    "well": ("well", "wellposition", "pos", "position", "wellid", "generalpos"),
}
_HEADER_KEY: dict[str, str] = {
    spelling: name for name, spellings in HEADER_SYNONYMS.items() for spelling in spellings
}

_EXCEL_DATE_TEXT = re.compile(
    r"^\s*(?:\d{1,2}[-\s/](?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*[-\s/]\d{1,4})\s*$",
    re.IGNORECASE,
)


def squash(text: str) -> str:
    """Lowercase ``text`` and keep only letters and digits (``"Sample ID*"`` -> ``"sampleid"``)."""
    return re.sub(r"[^0-9a-z]", "", text.casefold())


def header_field(text: str) -> str | None:
    """The canonical field a header names, or ``None`` (case, separator and abbreviation tolerant).

    ``"Sample ID"``, ``"sample_name"`` and ``"*Sample Name"`` give ``"sample"``; ``"grp"`` gives
    ``"group"``; ``"Bio rep"`` gives ``"bio_rep"``; ``"Mouse"`` gives ``"bio_unit"``.
    """
    key = squash(text)
    if not key:
        return None
    if key in _HEADER_KEY:
        return _HEADER_KEY[key]
    # "Sample name (as on tube)", "Group 1" or "Treatment group": a known word of five or more
    # letters at the start or the end (short words such as "name" or "type" only match whole
    # headers, so "Cell type" stays unrecognised). A header that starts with one field and
    # ends with another ("Sample quantity") is ambiguous and left unrecognised.
    found = {
        name
        for spelling, name in _HEADER_KEY.items()
        if len(spelling) >= 5 and (key.startswith(spelling) or key.endswith(spelling))
    }
    return found.pop() if len(found) == 1 else None


def cell_text(value: Any) -> str:
    """One canonical text form of a cell value, used for quarantine and for table rows.

    Strings are kept as written; integers and integral floats print without a decimal point;
    other floats use ``repr``; dates print as ISO dates (with the time only when it is not
    midnight); booleans as ``TRUE``/``FALSE``.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return repr(value)
    if isinstance(value, dt.datetime):
        return value.date().isoformat() if value.time() == dt.time(0) else value.isoformat()
    if isinstance(value, dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return str(value)
    return str(value)


def looks_like_excel_date(value: Any) -> bool:
    """Whether a cell value is a date, or text written the way Excel displays one (``1-Mar``)."""
    if isinstance(value, dt.date | dt.datetime):
        return True
    return isinstance(value, str) and bool(_EXCEL_DATE_TEXT.match(value))


# ---------------------------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------------------------


def column_letter(column: int) -> str:
    """1 -> ``A``, 27 -> ``AA``."""
    letters = ""
    while column > 0:
        column, rest = divmod(column - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def cell_ref(sheet: str, row: int, column: int) -> str:
    """``Sheet1!B2`` for row 2, column 2 of ``Sheet1``."""
    return f"{sheet}!{column_letter(column)}{row}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check_zip(path: Path) -> None:
    """Refuse a workbook whose members would inflate past the caps (a decompression bomb)."""
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
    except zipfile.BadZipFile as err:
        raise SheetError(f"{path.name}: not a valid .xlsx file") from err
    total = sum(info.file_size for info in infos)
    packed = sum(info.compress_size for info in infos)
    if total > MAX_XML_BYTES:
        raise SheetError(f"{path.name}: workbook too large ({total} bytes uncompressed)")
    if packed and total / packed > MAX_ZIP_RATIO:
        raise SheetError(f"{path.name}: workbook too large (compression ratio above 100:1)")


def _checked(path: str | Path) -> Path:
    """The sheet file, once it passes the checks that run before any byte is read."""
    file = Path(path)
    if not file.is_file():
        raise SheetError(f"not a file: {file.name}")
    if file.suffix.lower() not in SUFFIXES:
        raise SheetError(f"{file.name}: unsupported sheet type (use .xlsx or .csv)")
    size = file.stat().st_size
    if size > MAX_FILE_BYTES:
        raise SheetError(f"{file.name}: sheet too large ({size} bytes; the cap is 5 MB)")
    return file


def sheet_sha256(path: str | Path) -> str:
    """The sha256 :func:`read_sheet` would report for ``path``, without parsing anything.

    The same checks run first (a missing file, an unsupported type or a file over the size cap
    raises :class:`SheetError`), so a cache keyed by this hash never reads a sheet twice.
    """
    return _sha256(_checked(path))


def read_sheet(path: str | Path) -> SheetRead:
    """Read every sheet of an ``.xlsx`` workbook or a ``.csv``/``.tsv`` file, safely.

    Args:
        path: The sample sheet.

    Returns:
        The cells, their quarantine entries and the raw values (see :class:`SheetRead`).

    Raises:
        SheetError: Missing file, unsupported type, a size cap exceeded, or unreadable content.
    """
    file = _checked(path)
    suffix = file.suffix.lower()
    out = SheetRead(file_name=file.name, sha256=_sha256(file))
    if suffix in (".xlsx", ".xlsm"):
        grids = _xlsx_grids(file, out)
    else:
        grids = _csv_grids(file)
    n_cells = 0
    for title, grid in grids:
        out.sheets.append(title)
        out.quarantine.append(
            QuarantineEntry(
                text_id=text_id_for(f"sheet:{file.name}:sheet_title", title),
                origin=f"sheet:{file.name}:sheet_title",
                value=title,
            )
        )
        for (row, column), value in sorted(grid.items()):
            text = cell_text(value)
            if text.strip() == "":
                continue
            n_cells += 1
            if n_cells > MAX_CELLS:
                raise SheetError(f"{file.name}: more than {MAX_CELLS} filled cells")
            ref = cell_ref(title, row, column)
            origin = f"sheet:{file.name}!{ref}"
            text_id = text_id_for(origin, text)
            is_date = isinstance(value, dt.date | dt.datetime)
            flags = [DATE_FLAG] if is_date else []
            out.cells.append(SheetCell(cell=ref, text_id=text_id, row=row, column=column))
            out.quarantine.append(
                QuarantineEntry(text_id=text_id, origin=origin, value=text, flags=flags)
            )
            out.values[ref] = value
            if is_date:
                out.date_cells.append(ref)
    if out.date_cells:
        out.notes.append(
            "Some cells are stored as dates; if they were gene names, Excel converted them."
        )
    return out


def _xlsx_grids(file: Path, out: SheetRead) -> list[tuple[str, dict[tuple[int, int], Any]]]:
    """Every sheet of a workbook as ``{(row, column): value}`` with merged ranges expanded."""
    _check_zip(file)
    try:
        import openpyxl
    except ImportError as err:  # pragma: no cover - the studio extra installs it
        raise SheetError("reading .xlsx needs openpyxl (pip install 'qpilot[studio]')") from err
    try:
        book = openpyxl.load_workbook(file, read_only=True, data_only=True, keep_links=False)
    except Exception as err:  # openpyxl raises many types for malformed workbooks
        raise SheetError(f"{file.name}: not a readable workbook ({type(err).__name__})") from err
    try:
        if len(book.sheetnames) > MAX_SHEETS:
            raise SheetError(f"{file.name}: more than {MAX_SHEETS} sheets")
        grids = []
        budget = MAX_CELLS  # cells all merged ranges of the workbook may cover together
        for sheet in book.worksheets:
            grid, merged = _stream_sheet(book, sheet, file.name)
            budget -= _expand_merged(grid, merged, out, sheet.title, budget)
            grids.append((sheet.title, grid))
        return grids
    except SheetError:
        raise
    except Exception as err:
        raise SheetError(f"{file.name}: not a readable workbook ({type(err).__name__})") from err
    finally:
        book.close()


def _stream_sheet(
    book: Any, sheet: Any, file_name: str
) -> tuple[dict[tuple[int, int], Any], list[tuple[int, int, int, int]]]:
    """Stream one read-only sheet: its values and its merged ranges, in one pass.

    openpyxl's read-only worksheet does not expose merged ranges, so this drives the same
    worksheet parser openpyxl uses internally (with its hardened XML settings) and collects
    the ``mergeCells`` element it records after the cell data.
    """
    from openpyxl.worksheet._reader import WorkSheetParser

    grid: dict[tuple[int, int], Any] = {}
    with sheet._get_source() as source:
        parser = WorkSheetParser(
            source,
            book.shared_strings,
            data_only=True,
            epoch=book.epoch,
            date_formats=book._date_formats,
            timedelta_formats=book._timedelta_formats,
        )
        for row_index, cells in parser.parse():
            for cell in cells:
                value = cell.get("value")
                if value is None or (isinstance(value, str) and value.strip() == ""):
                    continue
                column = cell["column"]
                if row_index > MAX_ROWS or column > MAX_COLUMNS:
                    raise SheetError(
                        f"{file_name}: a value lies outside {MAX_ROWS} rows x {MAX_COLUMNS} columns"
                    )
                grid[(row_index, column)] = value
        merged = []
        if parser.merged_cells is not None:
            if len(parser.merged_cells.mergeCell) > MAX_MERGED_RANGES:
                raise SheetError(f"{file_name}: more than {MAX_MERGED_RANGES} merged ranges")
            for item in parser.merged_cells.mergeCell:
                merged.append(_range_bounds(item.ref))
    return grid, list(dict.fromkeys(merged))  # a range listed twice is expanded once


def _range_bounds(ref: str) -> tuple[int, int, int, int]:
    """``"B2:D4"`` -> (min_row, min_col, max_row, max_col)."""
    from openpyxl.utils.cell import range_boundaries

    min_col, min_row, max_col, max_row = range_boundaries(ref)
    return min_row, min_col, max_row, max_col


def _expand_merged(
    grid: dict[tuple[int, int], Any],
    merged: list[tuple[int, int, int, int]],
    out: SheetRead,
    title: str,
    budget: int,
) -> int:
    """Copy each merged range's top-left value into every cell the range covers (within caps).

    The ranges expanded may cover at most ``budget`` cells together, overlaps counted each
    time; returns how many they covered.

    Raises:
        SheetError: The ranges cover more than ``budget`` cells.
    """
    clipped = False
    covered = 0
    for min_row, min_col, max_row, max_col in merged:
        value = grid.get((min_row, min_col))
        if value is None:
            continue
        if max_row > MAX_ROWS or max_col > MAX_COLUMNS:
            clipped = True
            max_row, max_col = min(max_row, MAX_ROWS), min(max_col, MAX_COLUMNS)
        covered += (max_row - min_row + 1) * (max_col - min_col + 1)
        if covered > budget:
            raise SheetError(f"{out.file_name}: the merged ranges cover too many cells")
        for row in range(min_row, max_row + 1):
            for column in range(min_col, max_col + 1):
                grid.setdefault((row, column), value)
    if clipped:
        out.notes.append(f"A merged range on sheet {title!r} was cut at the size caps.")
    return covered


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _csv_grids(file: Path) -> list[tuple[str, dict[tuple[int, int], Any]]]:
    """A delimited text file as one sheet named after the file stem."""
    text = _decode(file.read_bytes())
    if "\x00" in text:
        raise SheetError(f"{file.name}: not a text file")
    sample = text[:65536]
    if file.suffix.lower() == ".tsv":
        delimiter = "\t"
    else:
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
        except csv.Error:
            delimiter = ","
    grid: dict[tuple[int, int], Any] = {}
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        for row_index, row in enumerate(_limited(reader, file.name), start=1):
            for column, value in enumerate(row, start=1):
                if value.strip() == "":
                    continue
                if column > MAX_COLUMNS:
                    raise SheetError(f"{file.name}: more than {MAX_COLUMNS} columns")
                grid[(row_index, column)] = value
    except csv.Error as err:
        raise SheetError(f"{file.name}: not a readable delimited file ({err})") from err
    return [(file.stem[:31] or "Sheet1", grid)]


def _limited(reader: Iterator[list[str]], file_name: str) -> Iterator[list[str]]:
    for index, row in enumerate(reader, start=1):
        if index > MAX_ROWS:
            if any(value.strip() for value in row):
                raise SheetError(f"{file_name}: more than {MAX_ROWS} rows")
            continue
        yield row


# ---------------------------------------------------------------------------------------------
# The table on a sheet
# ---------------------------------------------------------------------------------------------


def sheet_table(source: str | Path | SheetRead, sheet: str | None = None) -> SheetTable | None:
    """Find the header row of a sheet and return its rows as dictionaries of strings.

    The header is the row (among the first 30) that names the most known fields, and it must
    name a sample column. Rows after it without a sample value are skipped (units rows, blank
    rows, footers) and listed in ``skipped_rows``. Values are stripped of surrounding spaces.

    Args:
        source: A sheet file, or what :func:`read_sheet` returned for it.
        sheet: Sheet title; default the first sheet that has a recognisable table.

    Returns:
        The table, or ``None`` when no sheet has a header row with a sample column.
    """
    read = source if isinstance(source, SheetRead) else read_sheet(source)
    titles = [sheet] if sheet is not None else read.sheets
    for title in titles:
        table = _table_on(read, title)
        if table is not None:
            return table
    return None


def _table_on(read: SheetRead, title: str) -> SheetTable | None:
    by_row: dict[int, dict[int, Any]] = {}
    for cell in read.cells:
        if cell.cell.rsplit("!", 1)[0] != title:
            continue
        by_row.setdefault(cell.row, {})[cell.column] = read.values[cell.cell]
    if not by_row:
        return None
    best: tuple[int, int, dict[str, int], dict[int, str]] | None = None
    for row in sorted(by_row)[:HEADER_SCAN_ROWS]:
        columns: dict[str, int] = {}
        headers: dict[int, str] = {}
        for column, value in sorted(by_row[row].items()):
            text = cell_text(value).strip()
            headers[column] = text
            name = header_field(text) if isinstance(value, str) else None
            if name is not None and name not in columns:
                columns[name] = column
        if "sample" not in columns:
            continue
        score = len(columns)
        if best is None or score > best[1]:
            best = (row, score, columns, headers)
    if best is None:
        return None
    header_row, _, columns, headers = best
    table = SheetTable(
        sheet=title,
        header_row=header_row,
        columns=columns,
        headers=headers,
        rows=[],
        refs=[],
        row_numbers=[],
    )
    field_of = {column: name for name, column in columns.items()}
    for row in sorted(r for r in by_row if r > header_row):
        values = by_row[row]
        sample_value = values.get(columns["sample"])
        if sample_value is None or cell_text(sample_value).strip() == "":
            table.skipped_rows.append(row)
            continue
        entry: dict[str, str] = {}
        refs: dict[str, str] = {}
        for column, value in sorted(values.items()):
            key = field_of.get(column, f"col{column}")
            entry[key] = cell_text(value).strip()
            refs[key] = cell_ref(title, row, column)
            if looks_like_excel_date(value):
                table.date_cells.append(refs[key])
        table.rows.append(entry)
        table.refs.append(refs)
        table.row_numbers.append(row)
    return table


__all__ = [
    "HEADER_SYNONYMS",
    "MAX_COLUMNS",
    "MAX_FILE_BYTES",
    "MAX_ROWS",
    "MAX_SHEETS",
    "SheetError",
    "SheetRead",
    "SheetTable",
    "cell_ref",
    "cell_text",
    "header_field",
    "looks_like_excel_date",
    "read_sheet",
    "sheet_sha256",
    "sheet_table",
    "squash",
]
