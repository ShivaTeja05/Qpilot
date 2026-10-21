"""Read delimited text and workbooks safely into rows of strings, and find tables by header name.

Every connector reads its file through this module, so the input caps live in one place:

* the file must be at most :data:`MAX_FILE_BYTES`; text is decoded as UTF-8 (with or without a
  byte-order mark), UTF-16 when it starts with a UTF-16 byte-order mark, else Windows-1252; a
  NUL character in decoded text refuses the file;
* at most :data:`MAX_ROWS` rows, :data:`MAX_COLUMNS` columns and :data:`MAX_CELLS` non-empty
  cells per file, and at most :data:`MAX_CELL_CHARS` characters in one cell;
* workbooks (``.xlsx``/``.xlsm``) are opened by openpyxl in read-only, data-only mode, so a
  formula is never evaluated (a formula cell gives the value Excel cached, or nothing); their
  zip members may not inflate past :data:`MAX_UNZIPPED_BYTES` in total or more than
  :data:`MAX_ZIP_RATIO` times; at most :data:`MAX_SHEETS` sheets;
* legacy ``.xls`` workbooks are refused with a re-export hint (no reader is shipped for them).

Tables are found by **header names, never by column positions**: :func:`find_header` looks for
the row whose cells name the most of a connector's expected columns, after
:func:`squash` (lower case, letters and digits only), so ``Well Position``, ``well_position``
and ``WELL POSITION`` are one name. Numbers are parsed by :func:`number`, which accepts a
decimal comma when the file's delimiter is not a comma.
"""

from __future__ import annotations

import csv
import io
import math
import re
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from qpilot.io.connectors.base import CaptureError

MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_HEAD_BYTES = 256 * 1024
MAX_ROWS = 2_000_000
MAX_COLUMNS = 2_000
MAX_CELLS = 20_000_000
MAX_CELL_CHARS = 10_000
MAX_SHEETS = 64
MAX_UNZIPPED_BYTES = 1 << 30
MAX_ZIP_RATIO = 100
PROBE_ROWS = 60

TEXT_SUFFIXES = (".csv", ".txt", ".tsv", ".tab", ".dat", ".asc", "")
WORKBOOK_SUFFIXES = (".xlsx", ".xlsm")

_UNDETERMINED = {"undetermined", "nan", "n/a", "na", "none", "", "-", "--", "no ct", "noct",
                 "no cq", "nocq", "inf", "infinity", "-inf", "null", "nd", "n.d."}  # fmt: skip
_NUMBER = re.compile(r"^[+-]?(\d+([.,]\d*)?|[.,]\d+)([eE][+-]?\d+)?$")


@dataclass
class Grid:
    """One table-shaped thing from a file: a text file, or one sheet of a workbook.

    Attributes:
        name: The sheet title (a text file: ``""``).
        rows: Every row as a list of stripped strings (trailing empty cells removed).
        delimiter: The text delimiter (``""`` for a workbook sheet).
        decimal_comma: Whether ``1,25`` means 1.25 here: the delimiter is not a comma and
            more number-like cells use a decimal comma than a decimal point.
    """

    name: str
    rows: list[list[str]]
    delimiter: str = ""
    decimal_comma: bool = False


def squash(text: str) -> str:
    """A header name for comparison: lower case, letters and digits only (``wellposition``).

    Greek and Cyrillic letters some vendors use (``Cт`` with a Cyrillic te, ``ΔRn``) are folded
    to ``ct`` and ``deltarn`` first.
    """
    folded = text.replace("т", "t").replace("Т", "T")  # Cyrillic te in "Cт"
    folded = folded.replace("Δ", "delta").replace("δ", "delta")  # Greek delta
    return re.sub(r"[^0-9a-z]+", "", folded.lower())


def number(text: str, *, decimal_comma: bool = False) -> float | None:
    """Parse a cell as a finite number, or ``None`` (``Undetermined``, ``NaN``, empty, text).

    Args:
        text: The cell text.
        decimal_comma: Accept ``1,25`` as 1.25 (files whose delimiter is not a comma).
    """
    value = text.strip().replace("−", "-")  # a Unicode minus sign
    if value.lower() in _UNDETERMINED:
        return None
    if not _NUMBER.match(value):
        return None
    if "," in value:
        if not decimal_comma or "." in value:
            return None
        value = value.replace(",", ".")
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


# ---------------------------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------------------------


def check_size(path: Path) -> int:
    """The file's size in bytes, once it passes the size cap.

    Raises:
        CaptureError: Not a file, or larger than :data:`MAX_FILE_BYTES`.
    """
    if not path.is_file():
        raise CaptureError(f"not a file: {path.name}")
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise CaptureError(f"{path.name}: file too large ({size} bytes; the cap is 200 MB)")
    if size == 0:
        raise CaptureError(f"{path.name}: the file is empty")
    return size


def decode(raw: bytes, name: str) -> str:
    """Decode a text export (UTF-8 with or without BOM, UTF-16 with BOM, else Windows-1252).

    Raises:
        CaptureError: The decoded text holds a NUL character (a binary file).
    """
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            text = raw.decode("utf-16")
        except UnicodeDecodeError as err:
            raise CaptureError(f"{name}: not a readable UTF-16 text file") from err
    else:
        for encoding in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
    if "\x00" in text:
        raise CaptureError(f"{name}: not a text file")
    return text


def file_kind(path: Path) -> str:
    """``xlsx``, ``xls``, ``zip``, ``text`` or ``binary``, from the first bytes (not the suffix)."""
    with path.open("rb") as handle:
        start = handle.read(8)
    # a zip; CFX Manager 3.0 writes RDML archives that start with the spanning marker PK 07 08
    if start.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08PK\x03\x04")):
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile:
            return "binary"
        return "xlsx" if "xl/workbook.xml" in names else "zip"
    if start.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "xls"
    if start.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "text"
    with path.open("rb") as handle:
        sample = handle.read(4096)
    if b"\x00" in sample:
        return "binary"
    return "text"


def sniff_delimiter(lines: Sequence[str]) -> str:
    """The delimiter of a text table: tab, semicolon or comma, by which splits lines most evenly.

    The header block of a vendor export (``* key = value`` lines, ``[Section]`` lines) is skipped.
    """
    body = [
        line
        for line in lines
        if line.strip() and not line.lstrip().startswith(("*", "#", "[")) and len(line) < 100_000
    ][:200]
    best, best_score = ",", -1.0
    for delimiter in ("\t", ";", ","):
        counts = [len(next(csv.reader([line], delimiter=delimiter))) for line in body]
        wide = [c for c in counts if c > 1]
        if not wide:
            continue
        # most lines split, into the most columns
        score = len(wide) * 1000 + max(wide)
        if score > best_score:
            best, best_score = delimiter, score
    return best


def read_text(path: Path) -> Grid:
    """A delimited text file as one :class:`Grid` (rows of stripped strings).

    Raises:
        CaptureError: Too large, binary, or over a row / column / cell cap.
    """
    check_size(path)
    text = decode(path.read_bytes(), path.name)
    lines = text.splitlines()
    delimiter = sniff_delimiter(lines[:400])
    rows = _rows(_csv_rows(text, delimiter, path.name), path.name)
    return Grid(
        name="", rows=rows, delimiter=delimiter, decimal_comma=_decimal_comma(rows, delimiter)
    )


_COMMA_DECIMAL = re.compile(r"^[+-]?\d+,\d+$")
_POINT_DECIMAL = re.compile(r"^[+-]?\d+\.\d+$")


def _decimal_comma(rows: Sequence[Sequence[str]], delimiter: str) -> bool:
    """Whether numbers in these rows use a decimal comma (judged on up to 5,000 cells)."""
    if delimiter == ",":
        return False
    comma = point = seen = 0
    for row in rows:
        for cell in row:
            if _COMMA_DECIMAL.match(cell):
                comma += 1
            elif _POINT_DECIMAL.match(cell):
                point += 1
            seen += 1
        if seen > 5_000:
            break
    return comma > point


def _csv_rows(text: str, delimiter: str, name: str) -> Iterable[list[str]]:
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        yield from reader
    except csv.Error as err:
        raise CaptureError(f"{name}: not a readable delimited file ({err})") from err


def _rows(rows: Iterable[Sequence[object]], name: str) -> list[list[str]]:
    """Strip cells, drop trailing empties, enforce the caps."""
    out: list[list[str]] = []
    cells = 0
    for index, row in enumerate(rows, start=1):
        values = [_cell_text(value) for value in row]
        while values and values[-1] == "":
            values.pop()
        if index > MAX_ROWS:
            if values:
                raise CaptureError(f"{name}: more than {MAX_ROWS} rows")
            continue
        if len(values) > MAX_COLUMNS:
            raise CaptureError(f"{name}: more than {MAX_COLUMNS} columns")
        for value in values:
            if len(value) > MAX_CELL_CHARS:
                raise CaptureError(f"{name}: a cell longer than {MAX_CELL_CHARS} characters")
            if value:
                cells += 1
        if cells > MAX_CELLS:
            raise CaptureError(f"{name}: more than {MAX_CELLS} filled cells")
        out.append(values)
    return out


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value) if math.isfinite(value) else ""
    if isinstance(value, int):
        return str(value)
    return str(value).strip()


def check_workbook(path: Path) -> None:
    """Refuse a workbook whose zip members would inflate past the caps (a decompression bomb)."""
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
    except zipfile.BadZipFile as err:
        raise CaptureError(f"{path.name}: not a valid .xlsx file") from err
    total = sum(info.file_size for info in infos)
    packed = sum(info.compress_size for info in infos)
    if total > MAX_UNZIPPED_BYTES:
        raise CaptureError(f"{path.name}: workbook too large ({total} bytes uncompressed)")
    if packed and total / packed > MAX_ZIP_RATIO:
        raise CaptureError(f"{path.name}: workbook too large (compression ratio above 100:1)")


def read_workbook(path: Path, *, max_rows: int | None = None) -> list[Grid]:
    """Every sheet of an ``.xlsx`` workbook as a :class:`Grid` (formulas never evaluated).

    Args:
        path: The workbook.
        max_rows: Read only this many rows per sheet (the probe), else every row within the caps.

    Raises:
        CaptureError: Too large, not a workbook, or over a cap.
    """
    check_size(path)
    check_workbook(path)
    try:
        import openpyxl
    except ImportError as err:  # pragma: no cover - the xlsx/studio extra installs it
        raise CaptureError("reading .xlsx needs openpyxl (pip install 'qpilot[xlsx]')") from err
    try:
        book = openpyxl.load_workbook(path, read_only=True, data_only=True, keep_links=False)
    except Exception as err:  # openpyxl raises many types for malformed workbooks
        raise CaptureError(f"{path.name}: not a readable workbook ({type(err).__name__})") from err
    try:
        if len(book.sheetnames) > MAX_SHEETS:
            raise CaptureError(f"{path.name}: more than {MAX_SHEETS} sheets")
        grids = []
        for sheet in book.worksheets:
            rows = sheet.iter_rows(values_only=True, max_row=max_rows)
            grids.append(
                Grid(name=str(sheet.title), rows=_rows(_capped(rows, path.name), path.name))
            )
        return grids
    except CaptureError:
        raise
    except Exception as err:
        raise CaptureError(f"{path.name}: not a readable workbook ({type(err).__name__})") from err
    finally:
        book.close()


def _capped(rows: Iterable[Sequence[object]], name: str) -> Iterable[Sequence[object]]:
    for row in rows:
        if len(row) > MAX_COLUMNS and any(v not in (None, "") for v in row[MAX_COLUMNS:]):
            raise CaptureError(f"{name}: more than {MAX_COLUMNS} columns")
        yield row[:MAX_COLUMNS]


def read_grids(path: Path) -> list[Grid]:
    """A text file or a workbook as grids (one per sheet).

    Raises:
        CaptureError: An ``.xls`` workbook, a binary file, or anything over a cap.
    """
    kind = file_kind(path)
    if kind == "xlsx":
        return read_workbook(path)
    if kind == "xls":
        raise CaptureError(
            f"{path.name}: legacy .xls workbooks are not read; export the data as .txt, .csv or "
            ".xlsx from the instrument software"
        )
    if kind != "text":
        raise CaptureError(f"{path.name}: not a text export or an .xlsx workbook")
    return [read_text(path)]


def head_lines(path: Path) -> list[str]:
    """The first lines of a text file (at most :data:`MAX_HEAD_BYTES`), for sniffing."""
    with path.open("rb") as handle:
        raw = handle.read(MAX_HEAD_BYTES)
    try:
        text = decode(raw, path.name)
    except CaptureError:
        return []
    except UnicodeDecodeError:  # a UTF-16 head cut inside a character
        text = decode(raw[: len(raw) - len(raw) % 2], path.name)
    lines = text.splitlines()
    if len(raw) == MAX_HEAD_BYTES and lines:
        lines = lines[:-1]  # the last line may be cut
    return lines


# ---------------------------------------------------------------------------------------------
# Tables by header name
# ---------------------------------------------------------------------------------------------


@dataclass
class Table:
    """The rows under a header row, keyed by canonical column name.

    Attributes:
        columns: Canonical name -> 0-based column index (first matching column wins).
        headers: Every header cell as written (by 0-based index).
        rows: The data rows (lists of strings) after the header, up to the first blank row
            or section marker when ``stop_at_blank`` was asked.
        header_row: 0-based index of the header row in the grid.
    """

    columns: dict[str, int]
    headers: list[str]
    rows: list[list[str]]
    header_row: int

    def get(self, row: list[str], name: str) -> str:
        """The cell of canonical column ``name`` in ``row`` (``""`` when absent)."""
        index = self.columns.get(name)
        if index is None or index >= len(row):
            return ""
        return row[index]

    def has(self, name: str) -> bool:
        """Whether the table has canonical column ``name``."""
        return name in self.columns


def match_columns(
    headers: Sequence[str], vocabulary: Mapping[str, Sequence[str]]
) -> dict[str, int]:
    """Canonical name -> column index, for every header cell that names a vocabulary entry.

    ``vocabulary`` maps a canonical name to accepted spellings (compared after :func:`squash`).
    The first column that matches a name wins; a column matches at most one name.
    """
    lookup: dict[str, str] = {}
    for canonical, spellings in vocabulary.items():
        for spelling in spellings:
            lookup.setdefault(squash(spelling), canonical)
    found: dict[str, int] = {}
    for index, header in enumerate(headers):
        canonical = lookup.get(squash(header))
        if canonical is not None and canonical not in found:
            found[canonical] = index
    return found


def find_header(
    rows: Sequence[Sequence[str]],
    vocabulary: Mapping[str, Sequence[str]],
    required: Iterable[str],
    *,
    start: int = 0,
    scan: int = 200,
) -> int | None:
    """0-based index of the first row (from ``start``) naming every ``required`` column.

    Among the rows that name all required columns, the first is chosen; ``None`` if none does
    within ``scan`` rows.
    """
    needed = set(required)
    for index in range(start, min(len(rows), start + scan)):
        found = match_columns(rows[index], vocabulary)
        if needed <= set(found):
            return index
    return None


def table_at(
    rows: Sequence[Sequence[str]],
    header_row: int,
    vocabulary: Mapping[str, Sequence[str]],
    *,
    stop_at_blank: bool = True,
) -> Table:
    """The table whose header is at ``header_row``; data runs to a blank row or ``[Section]``."""
    headers = list(rows[header_row])
    body: list[list[str]] = []
    for row in rows[header_row + 1 :]:
        blank = not any(cell for cell in row)
        if blank and stop_at_blank:
            break
        if row and row[0].startswith("[") and row[0].rstrip().endswith("]"):
            break
        if not blank:
            body.append(list(row))
    return Table(
        columns=match_columns(headers, vocabulary),
        headers=headers,
        rows=body,
        header_row=header_row,
    )


__all__ = [
    "MAX_CELLS",
    "MAX_COLUMNS",
    "MAX_FILE_BYTES",
    "MAX_ROWS",
    "Grid",
    "Table",
    "check_size",
    "decode",
    "file_kind",
    "find_header",
    "head_lines",
    "match_columns",
    "number",
    "read_grids",
    "read_text",
    "read_workbook",
    "sniff_delimiter",
    "squash",
    "table_at",
]
