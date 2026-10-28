"""The round trip: what a scientist changed in Prism since the export (steps 6.1 and 6.2).

After editing in Prism, the scientist runs ``send_back.pzc``, which exports every data table to
``sent_back/<table>.csv`` with Prism's own ``ExportTable`` (Mode S). This module reads those
files, compares them with the exported bundle and turns what changed into proposals.

**Everything sent back is untrusted input.** :func:`read_sent_back` reads at most
:data:`MAX_FILES` files of at most :data:`MAX_FILE_BYTES` each and :data:`MAX_CELLS` cells in
all; links, folders and non-CSV files are reported, never followed or read. A cell is a number
only if it is plain decimal or exponent notation and finite; nothing is ever evaluated. Any
other cell text is quarantined under ``text_id_for(f"prism:{file}!{cell}", text)`` and never
interpreted; titles are only compared for equality with the names qPilot wrote.

:func:`diff` reports, per table:

* ``changed`` only when the returned number differs from the exported value rounded to the
  returned text's own number of decimals (Prism may print fewer digits than qPilot wrote);
* ``missing`` when a value qPilot wrote comes back empty. Mode S cannot tell an exclusion from a
  deletion until step 0.1 shows how ``ExportTable`` writes excluded values [R], so the note
  says so and the proposal asks the scientist;
* ``excluded`` only when the returned text carries an explicit exclusion marker. Which marker
  Prism writes (if any) is [R]; the hook (``exclusion_suffix``) is off by default;
* added and removed rows and columns, and ``unreadable`` files or cells.

:func:`diff_to_proposals` turns a missing or excluded value into a ``prism.exclusion_reason``
proposal whose consequence the engine computes (the study analysed again with the value excluded
as accepting would exclude it, on top of the exclusions already accepted: fold change, p and
conclusion before and after, and how many of all genes' conclusions change; with several
exclusions, also what all of them do together), and a changed value into a ``prism.value_edit``
proposal ("this value no longer matches the record", action ``restore`` by default). They are
made by a rule, never accepted here: only a person accepts a proposal.

**From the Prism project itself** (the default bundle): :func:`read_returned` reads the
``.pzfx`` file(s) the scientist saved in Prism (a file, or a folder holding them) with
:func:`qpilot.prism.pzfx.read_project`, finds each exported table by its exact title, and turns
it into the same strict cells as a sent-back CSV, with Prism's own exclusion mark
(``Excluded="1"``). There an empty cell is a deletion and a marked one an exclusion, so the
question names which. A value excluded in the Grouped table of all genes is the same value as
in that gene's Column table and is reported once, as that table's cell.

A value of the nested layout is one technical replicate. Its proposal names the replicate in
its subject (``gene/unit/rep n``, so two replicates of one unit never supersede each other) and
question, and carries the exact well behind that row of the exported table (``"well":
"<run_id>/<well>"``, also cited as evidence), found when the proposal is made. Accepting it
excludes that well, never a well counted again later on another design.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from qpilot.prism import pzfx
from qpilot.prism.tables import REPLICATE_COLUMN, ROW_TITLE_COLUMN, row_titles
from qpilot.qpcr.export import (
    ExportError,
    ExportInputs,
    Reanalysis,
    exclusion_subject,
    replicate_wells,
    resolve_replicate,
)
from qpilot.schemas_studio import (
    Evidence,
    MadeBy,
    PrismBundle,
    PrismDiffItem,
    Proposal,
    ProposalCheck,
    QuarantineEntry,
    text_id_for,
)

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_FILES = 200
MAX_CELLS = 100_000
SAFE_FILE = re.compile(r"[A-Za-z0-9_().\- ]{1,80}")
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")  # ASCII only
MISSING_NOTE = (
    "Empty in the table Prism sent back. qPilot cannot yet tell an exclusion from a deletion "
    "(how ExportTable writes excluded values is checked in plan step 0.1), so please say which, "
    "and why."
)
EXCLUDED_NOTE = "Excluded in Prism (marked in the table Prism sent back)."
DELETED_NOTE = "Deleted in Prism: the cell is empty in the saved project."
EXCLUDED_PROJECT_NOTE = "Excluded in Prism (marked as excluded in the saved project)."
SOURCE_SENT_BACK = "sent_back"
SOURCE_PROJECT = "project"
MAX_PROJECT_FILES = 20
CHANGED_PROJECT_NOTE = "This value no longer matches the record (changed in the saved project)."
IN_GROUPED = " In the table of all genes."
_PROJECT_NOTES = {  # a sent-back note -> the same finding in a saved project
    "missing": DELETED_NOTE,
    "excluded": EXCLUDED_PROJECT_NOTE,
    "changed": CHANGED_PROJECT_NOTE,
}
CHANGED_NOTE = "This value no longer matches the record."
NOT_THE_EXPORT = (
    "the study's wells no longer give the exported table, so the well behind this replicate is "
    "not known; export again"
)


class RoundTripError(ValueError):
    """The sent-back folder or the bundle cannot be read safely (the message says why)."""


@dataclass(frozen=True)
class Cell:
    """One cell sent back from Prism: a finite number, empty, or quarantined text."""

    ref: str  # spreadsheet-style reference inside its file, e.g. "C7"
    text: str
    value: float | None = None
    excluded: bool = False
    text_id: str | None = None  # set when the text is not a number (quarantined)

    @property
    def empty(self) -> bool:
        """True when the cell holds nothing."""
        return not self.text.strip()


@dataclass
class SentBackTable:
    """One CSV file sent back from Prism, parsed strictly (or the reason it was not)."""

    name: str
    file: str
    header: list[Cell] = field(default_factory=list)
    rows: list[list[Cell]] = field(default_factory=list)
    quarantine: list[QuarantineEntry] = field(default_factory=list)
    problem: str | None = None

    def titles(self) -> list[str]:
        """Row titles (first column), stripped."""
        return [row[0].text.strip() if row else "" for row in self.rows]

    def columns(self) -> list[str]:
        """Column titles after the row-title column, stripped."""
        return [cell.text.strip() for cell in self.header[1:]]


def cell_ref(row: int, column: int) -> str:
    """``(0, 0)`` -> ``A1``; rows and columns count from 0, the header is row 1."""
    letters, n = "", column + 1
    while n:
        n, rest = divmod(n - 1, 26)
        letters = chr(65 + rest) + letters
    return f"{letters}{row + 1}"


def parse_number(text: str) -> float | None:
    """A finite float for plain decimal or exponent notation; ``None`` for anything else."""
    stripped = text.strip()
    if not NUMBER.fullmatch(stripped):
        return None
    value = float(stripped)
    return value if math.isfinite(value) else None


class _Budget:
    def __init__(self, cells: int) -> None:
        self.left = cells


def parse_table(
    text: str,
    file: str,
    *,
    exclusion_suffix: str | None = None,
    budget: _Budget | None = None,
) -> SentBackTable:
    """Parse one CSV text strictly (header row, first column = row titles)."""
    name = Path(file).stem
    table = SentBackTable(name=name, file=file)
    budget = budget or _Budget(MAX_CELLS)
    if "\x00" in text:
        table.problem = "contains NUL characters"
        return table
    try:
        raw = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error as err:
        table.problem = f"not a readable CSV ({err})"
        return table
    raw = [row for row in raw if any(cell.strip() for cell in row)]
    if not raw:
        table.problem = "empty"
        return table
    width = len(raw[0])
    if sum(len(row) for row in raw) > budget.left:
        table.problem = f"more than {MAX_CELLS} cells sent back in all"
        return table
    budget.left -= sum(len(row) for row in raw)
    for r, row in enumerate(raw):
        if len(row) > width and any(cell.strip() for cell in row[width:]):
            table.problem = f"row {r + 1} has more cells than the header"
            return table
        row = (row + [""] * width)[:width]
        cells = []
        for c, text_cell in enumerate(row):
            ref = cell_ref(r, c)
            cells.append(_cell(text_cell, ref, file, r == 0 or c == 0, exclusion_suffix, table))
        if r == 0:
            table.header = cells
        else:
            table.rows.append(cells)
    return table


def _cell(
    text: str,
    ref: str,
    file: str,
    is_title: bool,
    exclusion_suffix: str | None,
    table: SentBackTable,
) -> Cell:
    if not text.strip():
        return Cell(ref=ref, text="")
    if not is_title:
        value = parse_number(text)
        if value is not None:
            return Cell(ref=ref, text=text.strip(), value=value)
        if exclusion_suffix and text.strip().endswith(exclusion_suffix):
            value = parse_number(text.strip()[: -len(exclusion_suffix)])
            if value is not None:
                return Cell(ref=ref, text=text.strip(), value=value, excluded=True)
    origin = f"prism:{file}!{ref}"
    text_id = text_id_for(origin, text)
    table.quarantine.append(QuarantineEntry(text_id=text_id, origin=origin, value=text))
    return Cell(ref=ref, text=text, text_id=text_id)


def read_sent_back(
    directory: str | Path, *, exclusion_suffix: str | None = None
) -> dict[str, SentBackTable]:
    """Read every file Prism sent back, strictly and size-capped.

    Args:
        directory: The ``sent_back/`` folder.
        exclusion_suffix: The marker Prism appends to an excluded value, once step 0.1 has
            confirmed one (off by default: an excluded value then reads as missing).

    Returns:
        Tables by file stem; a file that could not be read is a table with ``problem`` set.

    Raises:
        RoundTripError: The folder is missing, is a link, or holds more than 200 entries.
    """
    folder = Path(directory)
    if folder.is_symlink() or not folder.is_dir():
        raise RoundTripError(f"not a folder: {folder}")
    entries = sorted(os.scandir(folder), key=lambda e: e.name)
    entries = [e for e in entries if not e.name.startswith(".")]
    if len(entries) > MAX_FILES:
        raise RoundTripError(f"more than {MAX_FILES} files sent back; refusing to read them")
    budget = _Budget(MAX_CELLS)
    out: dict[str, SentBackTable] = {}
    for entry in entries:
        path = Path(entry.path)
        key = path.stem if path.suffix.lower() == ".csv" else entry.name
        table = SentBackTable(name=key, file=entry.name)
        if key in out:
            table.name = entry.name
            table.problem = "a second file for the same table"
            out[entry.name] = table
            continue
        out[key] = table
        if entry.is_symlink():
            table.problem = "a link, not read"
        elif not entry.is_file(follow_symlinks=False):
            table.problem = "not a regular file, not read"
        elif path.suffix.lower() != ".csv":
            table.problem = "not a .csv file, not read"
        elif entry.stat(follow_symlinks=False).st_size > MAX_FILE_BYTES:
            table.problem = f"larger than {MAX_FILE_BYTES // (1024 * 1024)} MB, not read"
        else:
            out[key] = _read_file(path, entry.name, exclusion_suffix, budget)
    return out


def _read_file(
    path: Path, file: str, exclusion_suffix: str | None, budget: _Budget
) -> SentBackTable:
    with open(path, "rb") as fh:
        data = fh.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        return SentBackTable(name=path.stem, file=file, problem="grew past the size limit")
    try:
        text = data.decode("utf-8-sig")  # a byte-order mark is allowed; the encoding is [R]
    except UnicodeDecodeError:
        return SentBackTable(name=path.stem, file=file, problem="not UTF-8 text")
    return parse_table(text, file, exclusion_suffix=exclusion_suffix, budget=budget)


# ---------------------------------------------------------------------------------------------
# Reading the project Prism saved (.pzfx)
# ---------------------------------------------------------------------------------------------


@dataclass
class Returned:
    """What came back from Prism, ready for :func:`diff`: tables by the bundle's table names.

    ``grouped`` holds the differences found in the Grouped table of all genes, already as the
    gene's Column-table cells; ``files`` the project files read (newest wins for a table found
    in two); ``source`` says where it came from (a saved project, or ``send_back.pzc``'s CSVs).
    """

    tables: dict[str, SentBackTable] = field(default_factory=dict)
    grouped: pzfx.ProjectTable | None = None
    files: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    source: str = SOURCE_SENT_BACK
    skipped: set[str] = field(default_factory=set)  # tables of project files not given


def is_project_path(path: str | Path) -> bool:
    """True for a ``.pzfx`` file, or a folder that holds one (the project route)."""
    target = Path(path)
    if target.is_file():
        return target.suffix.lower() == ".pzfx"
    if target.is_dir() and not target.is_symlink():
        return any(
            e.name.lower().endswith(".pzfx") and not e.name.startswith(".")
            for e in os.scandir(target)
        )
    return False


def _project_files(path: Path) -> list[Path]:
    if path.is_symlink():
        raise RoundTripError(f"a link, not read: {path.name}")
    if path.is_file():
        if path.suffix.lower() != ".pzfx":
            raise RoundTripError("choose the project Prism saved (a .pzfx file)")
        return [path]
    if not path.is_dir():
        raise RoundTripError(f"not a file or folder: {path}")
    found = sorted(
        Path(e.path)
        for e in os.scandir(path)
        if e.name.lower().endswith(".pzfx")
        and not e.name.startswith(".")
        and e.is_file(follow_symlinks=False)
    )
    if len(found) > MAX_PROJECT_FILES:
        raise RoundTripError(f"more than {MAX_PROJECT_FILES} .pzfx files here; choose the file")
    return found


def read_returned(
    path: str | Path,
    bundle: PrismBundle,
    bundle_dir: str | Path,
) -> Returned:
    """Read the project file(s) Prism saved and match their tables to the exported ones.

    Raises:
        RoundTripError: Nothing readable was given, or no exported table is in it.
    """
    from qpilot.prism.project import (
        GROUPED_NAME,
        INFO_GROUPED_TITLE,
        INFO_PROJECT,
        INFO_PROJECT_SHA,
        INFO_REPLICATES,
        INFO_REPLICATES_SHA,
    )

    files = _project_files(Path(path))
    if not files:
        raise RoundTripError("no Prism project (.pzfx) here; choose the file Prism saved")
    names = {t.title: t.name for t in bundle.tables}
    grouped_title = bundle.info.get(INFO_GROUPED_TITLE)
    if grouped_title:
        names[grouped_title] = GROUPED_NAME
    written = {
        bundle.info.get(INFO_PROJECT_SHA): bundle.info.get(INFO_PROJECT),
        bundle.info.get(INFO_REPLICATES_SHA): bundle.info.get(INFO_REPLICATES),
    }
    out = Returned(source=SOURCE_PROJECT)
    found: dict[str, tuple[float, str, pzfx.ProjectTable]] = {}
    other = 0
    for file in files:
        if file.stat().st_size > pzfx.MAX_PROJECT_BYTES:
            out.notes.append(f"{_file_label(file.name)}: too large, not read")
            continue
        with open(file, "rb") as fh:
            data = fh.read(pzfx.MAX_PROJECT_BYTES + 1)
        digest = hashlib.sha256(data).hexdigest()
        if written.get(digest):
            out.notes.append(
                f"{_file_label(file.name)} is the project exactly as qPilot wrote it: nothing "
                "was saved in Prism since (save the project in Prism first)"
            )
        try:
            project = pzfx.read_project(data)
        except pzfx.PzfxError as err:
            out.notes.append(f"{_file_label(file.name)}: {err}")
            continue
        out.files.append(_file_label(file.name))
        out.notes += [f"{_file_label(file.name)}: {p}" for p in project.problems]
        mtime = file.stat().st_mtime
        for table in project.tables:
            name = names.get(table.title)
            if name is None:
                other += 1
                continue
            if name not in found or mtime > found[name][0]:
                found[name] = (mtime, file.name, table)
    if not found:
        raise RoundTripError(
            "none of the tables qPilot wrote is in this project (were they renamed?); choose "
            "the project qPilot wrote, saved in Prism"
        )
    if other:
        out.notes.append(
            f"{other} table{'s' * (other != 1)} qPilot did not write (added or renamed in "
            "Prism) were left alone"
        )
    exported = exported_tables(bundle, bundle_dir)
    read_names = {name for name in found}
    replicates = [t.name for t in bundle.tables if t.layout == "nested"]
    if replicates and not read_names & set(replicates):
        out.skipped |= set(replicates)
        out.notes.append(
            "the replicates project was not given, so its Nested tables were not compared"
        )
    if not read_names & {t.name for t in bundle.tables if t.layout == "column"}:
        out.skipped |= {t.name for t in bundle.tables if t.layout == "column"}
    budget = _Budget(MAX_CELLS)
    for table in bundle.tables:
        if table.name in out.skipped:
            continue
        if table.name not in found:
            out.tables[table.name] = SentBackTable(
                name=table.name,
                file=table.name,
                problem="not in the saved project (renamed or deleted in Prism?)",
            )
            continue
        _, file, returned = found[table.name]
        out.tables[table.name] = _project_cells(
            returned, exported[table.name], f"{file}!{table.name}", budget
        )
    if GROUPED_NAME in found:
        out.grouped = found[GROUPED_NAME][2]
    return out


def _project_cells(
    returned: pzfx.ProjectTable, mine: SentBackTable, file: str, budget: _Budget
) -> SentBackTable:
    """A saved project's table as the strict cells of a sent-back CSV, named like the export.

    A Nested table's subcolumns are named by position within their data set (the export's
    ``group/unit`` names), since Prism may drop or rename subcolumn titles.
    """
    grid = returned.grid()
    header = [cell.text for cell in grid[0]]
    if returned.kind == "nested":
        by_group: dict[str, list[str]] = {}
        for column in mine.columns():
            group = column.split("/", 1)[0]
            by_group.setdefault(group, []).append(column)
        header = [REPLICATE_COLUMN]
        for ds in returned.data_sets:
            known = by_group.get(ds.title, [])
            for k in range(len(ds.subcolumns)):
                header.append(known[k] if k < len(known) else f"{ds.title}/added_{k + 1}")
    elif returned.kind == "column":
        header = [ROW_TITLE_COLUMN, *header[1:]]
    table = SentBackTable(name=mine.name, file=file)
    rows = [[PzRaw(text=h) for h in header], *[[PzRaw.of(c) for c in row] for row in grid[1:]]]
    n = sum(len(r) for r in rows)
    if n > budget.left:
        table.problem = f"more than {MAX_CELLS} cells sent back in all"
        return table
    budget.left -= n
    width = len(header)
    for r, row in enumerate(rows):
        row = (row + [PzRaw()] * width)[:width]
        cells = []
        for c, raw in enumerate(row):
            cell = _cell(raw.text, cell_ref(r, c), file, r == 0 or c == 0, None, table)
            if raw.excluded and cell.value is not None:
                cell = replace(cell, excluded=True)
            elif raw.excluded and cell.empty:
                cell = replace(cell, excluded=True)
            cells.append(cell)
        if r == 0:
            table.header = cells
        else:
            table.rows.append(cells)
    while table.rows and all(cell.empty for cell in table.rows[-1]):
        table.rows.pop()  # Prism may keep empty rows at the end of a table
    return table


@dataclass(frozen=True)
class PzRaw:
    """A saved project's cell before it is checked: its text, and Prism's exclusion mark.

    A comma decimal separator (``3,5``, written by Prism in some locales) reads as a point.
    """

    text: str = ""
    excluded: bool = False

    @classmethod
    def of(cls, cell: pzfx.PzCell) -> PzRaw:
        """The raw form of a project cell."""
        return cls(text=pzfx.number_text(cell.text), excluded=cell.excluded)


def grouped_items(
    returned: Returned, bundle: PrismBundle, bundle_dir: str | Path
) -> list[PrismDiffItem]:
    """Values excluded, deleted or changed in the Grouped table, as their Column-table cells.

    Row ``r`` is a gene, data set a group, subcolumn ``k`` a unit (its subcolumn title when it
    names one, else the export's order). Rows or data sets qPilot did not write are left alone.
    """
    from qpilot.prism.project import project_tables

    grouped = returned.grouped
    if grouped is None:
        return []
    exported = exported_tables(bundle, bundle_dir)
    primary = [t for t in bundle.tables if t.layout == "column" and "__" not in t.name]
    by_gene = {t.gene: t for t in primary}
    texts = {t.csv: (Path(bundle_dir) / t.csv).read_text(encoding="utf-8") for t in primary}
    sub = bundle.model_copy(update={"tables": primary})
    mine = next((t for t in project_tables(sub, texts)[0] if t.kind == "grouped"), None)
    if mine is None:
        return []
    order = {ds.title: list(ds.subcolumn_titles) for ds in mine.data_sets}
    items = []
    for r, gene in enumerate(grouped.row_titles):
        table = by_gene.get(gene)
        if table is None:
            continue
        columns = exported[table.name].columns()
        rows = dict(zip(exported[table.name].titles(), exported[table.name].rows, strict=True))
        for ds in grouped.data_sets:
            if ds.title not in order or ds.title not in columns:
                continue
            c = columns.index(ds.title) + 1
            for k, cells in enumerate(ds.subcolumns):
                known = order[ds.title]
                title = ds.subcolumn_titles[k] if k < len(ds.subcolumn_titles) else ""
                unit = title if title in rows else (known[k] if k < len(known) else "")
                if unit not in rows or r >= len(cells):
                    continue
                raw = PzRaw.of(cells[r])
                ref = f"{GROUPED_FILE}!{cell_ref(r + 1, k + 1)}"
                placeholder = SentBackTable(name=table.name, file=GROUPED_FILE)
                theirs = _cell(raw.text, ref, GROUPED_FILE, False, None, placeholder)
                if raw.excluded:
                    theirs = replace(theirs, excluded=True)
                found = _compare(rows[unit][c], theirs)
                if found is None or found[0] == "unreadable":
                    continue
                kind, note = found
                items.append(
                    PrismDiffItem(
                        kind=kind,
                        table=table.name,
                        gene=table.gene,
                        row=unit,
                        column=ds.title,
                        exported=rows[unit][c].value,
                        returned=theirs.value,
                        note=_PROJECT_NOTES.get(kind, note) + IN_GROUPED,
                    )
                )
    return items


GROUPED_FILE = "all_genes"


def diff_returned(
    bundle: PrismBundle, returned: Returned, *, bundle_dir: str | Path
) -> list[PrismDiffItem]:
    """:func:`diff` for a saved project: Column and Nested tables, then the Grouped table.

    An empty cell is a deletion and a marked one an exclusion (the notes say which); a value
    found changed in two tables is reported once (its own table's cell first).
    """
    kept = bundle.model_copy(
        update={"tables": [t for t in bundle.tables if t.name not in returned.skipped]}
    )
    items = diff(kept, returned.tables, bundle_dir=bundle_dir)
    seen = {(i.kind, i.table, i.row, i.column) for i in items}
    for item in grouped_items(returned, bundle, bundle_dir):
        key = (item.kind, item.table, item.row, item.column)
        if key not in seen:
            seen.add(key)
            items.append(item)
    out = []
    for item in items:
        note = item.note or ""
        if item.kind in _PROJECT_NOTES and not _from_project(item):
            base = {"missing": MISSING_NOTE, "excluded": EXCLUDED_NOTE, "changed": CHANGED_NOTE}
            rest = note[len(base[item.kind]) :] if note.startswith(base[item.kind]) else ""
            item = item.model_copy(update={"note": _PROJECT_NOTES[item.kind] + rest})
        out.append(item)
    return out


# ---------------------------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------------------------


def same_as_shown(exported: float, shown: str) -> bool:
    """True when ``shown`` is ``exported`` rounded to the shown text's own decimals.

    Text that reads back to the exported float bit for bit is the same value, whatever its
    number of digits (a 17-digit round-trip format prints more digits than ``repr``). Otherwise
    the bound is half a unit in the last shown place, inclusive, around the float's exact binary
    value or its shortest ``repr`` (a writer may round either), so either rounding rule
    (half-even or half-away-from-zero) counts as unchanged.
    """
    try:
        shown_value = Decimal(shown.strip())
    except InvalidOperation:
        return False
    exponent = shown_value.as_tuple().exponent
    if not isinstance(exponent, int):
        return False
    exported = float(exported)
    if float(shown_value) == exported:
        return True
    tolerance = Decimal(5).scaleb(exponent - 1)
    return any(
        abs(value - shown_value) <= tolerance
        for value in (Decimal(exported), Decimal(repr(exported)))
    )


def exported_tables(bundle: PrismBundle, bundle_dir: str | Path) -> dict[str, SentBackTable]:
    """The exported CSVs, checked against the bundle's checksums and parsed the same way.

    Raises:
        RoundTripError: A CSV is missing or changed since export.
    """
    out = {}
    for table in bundle.tables:
        path = Path(bundle_dir) / table.csv
        try:
            data = path.read_bytes()
        except OSError as err:
            raise RoundTripError(f"exported table missing: {table.csv}") from err
        if hashlib.sha256(data).hexdigest() != table.csv_sha256:
            raise RoundTripError(f"exported table changed since export: {table.csv}")
        parsed = parse_table(data.decode("utf-8"), table.csv)
        if parsed.problem:
            raise RoundTripError(f"exported table unreadable: {table.csv} ({parsed.problem})")
        out[table.name] = parsed
    return out


def diff(
    bundle: PrismBundle,
    sent_back: Mapping[str, SentBackTable],
    *,
    bundle_dir: str | Path,
) -> list[PrismDiffItem]:
    """Every difference between the exported bundle and the tables Prism sent back.

    Args:
        bundle: The exported bundle (``qpilot_bundle.json``).
        sent_back: From :func:`read_sent_back`.
        bundle_dir: The bundle folder, for qPilot's own CSVs (checked against the bundle).

    Returns:
        Items in a fixed order: per table (bundle order) columns, rows, then cells.
    """
    exported = exported_tables(bundle, bundle_dir)
    by_name = {table.name: table for table in bundle.tables}
    items: list[PrismDiffItem] = []
    for name, returned in sorted(sent_back.items()):
        if name not in by_name:
            note = returned.problem or "not a table qPilot exported"
            label = _file_label(returned.file)
            items.append(PrismDiffItem(kind="unreadable", table=label, gene="", note=note))
    for table in bundle.tables:
        returned = sent_back.get(table.name)
        if returned is None:
            items.append(
                PrismDiffItem(
                    kind="unreadable",
                    table=table.name,
                    gene=table.gene,
                    note="not sent back (run send_back.pzc in Prism)",
                )
            )
        elif returned.problem:
            items.append(
                PrismDiffItem(
                    kind="unreadable", table=table.name, gene=table.gene, note=returned.problem
                )
            )
        else:
            items += _diff_table(table.name, table.gene, exported[table.name], returned)
    return items


def _file_label(file: str) -> str:
    """A file name as it may be shown: itself when plain, else its quarantine ``text_id``."""
    if SAFE_FILE.fullmatch(file):
        return file
    return text_id_for("prism:sent_back", file)


def _diff_table(
    name: str, gene: str, mine: SentBackTable, theirs: SentBackTable
) -> list[PrismDiffItem]:
    def item(kind: str, **kw: Any) -> PrismDiffItem:
        return PrismDiffItem(kind=kind, table=name, gene=gene, **kw)

    columns, titles = theirs.columns(), theirs.titles()
    if len(set(columns)) != len(columns):
        return [item("unreadable", note="two columns have the same title")]
    if len(set(titles)) != len(titles):
        return [item("unreadable", note="two rows have the same title")]
    items = []
    my_columns, my_titles = mine.columns(), mine.titles()
    for column in my_columns:
        if column not in columns:
            items.append(item("removed_column", column=column))
    for cell, column in zip(theirs.header[1:], columns, strict=True):
        if column not in my_columns:
            label = cell.text_id or ""
            items.append(item("added_column", column=label, note="title quarantined"))
    for title in my_titles:
        if title not in titles:
            items.append(item("removed_row", row=title))
    for row, title in zip(theirs.rows, titles, strict=True):
        if title not in my_titles:
            items.append(item("added_row", row=row[0].text_id or "", note="title quarantined"))
    their_rows = dict(zip(titles, theirs.rows, strict=True))
    their_index = {column: i + 1 for i, column in enumerate(columns)}
    for my_row, title in zip(mine.rows, my_titles, strict=True):
        if title not in their_rows:
            continue
        for c, column in enumerate(my_columns, start=1):
            if column not in their_index:
                continue
            exported, returned = my_row[c], their_rows[title][their_index[column]]
            found = _compare(exported, returned)
            if found is not None:
                kind, note = found
                items.append(
                    item(
                        kind,
                        row=title,
                        column=column,
                        exported=exported.value,
                        returned=returned.value,
                        note=note,
                    )
                )
    return items


def _compare(exported: Cell, returned: Cell) -> tuple[str, str] | None:
    if returned.text_id is not None:
        return "unreadable", f"not a number; text quarantined as {returned.text_id}"
    if exported.value is None:
        if returned.empty:
            return None
        return "changed", "a value where qPilot wrote none"
    if returned.empty:
        return "missing", MISSING_NOTE
    if returned.excluded:
        return "excluded", EXCLUDED_NOTE
    if returned.value is not None and same_as_shown(exported.value, returned.text):
        return None
    return "changed", CHANGED_NOTE


# ---------------------------------------------------------------------------------------------
# Proposals
# ---------------------------------------------------------------------------------------------

EXCLUSION_KINDS = ("missing", "excluded", "removed_row")


def _proposal_id(study_id: str, item: PrismDiffItem) -> str:
    key = "|".join([study_id, item.kind, item.table, item.row or "", item.column or ""])
    return "prism-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _locate(
    item: PrismDiffItem, layout: str, units_by_title: Mapping[str, str]
) -> tuple[str | None, int]:
    """(biological unit, well_rep) of a diff item; well_rep 0 is the whole unit."""
    if layout == "nested":
        if not item.column or "/" not in item.column:
            return None, 0
        title = item.column.split("/", 1)[1]
        match = re.fullmatch(r"rep (\d+)", item.row or "")
        rep = int(match.group(1)) if match else 0
        return units_by_title.get(title), rep
    return units_by_title.get(item.row or ""), 0


def diff_to_proposals(
    items: Sequence[PrismDiffItem],
    study_id: str,
    inputs: ExportInputs,
    *,
    bundle: PrismBundle | None = None,
    pseudonym: Callable[[str], str] | None = None,
    accepted: Sequence[Proposal] = (),
    declined: Sequence[Proposal] = (),
) -> list[Proposal]:
    """Turn diff items into proposals for the inbox (never accepted here).

    A missing, excluded or removed value becomes ``prism.exclusion_reason`` with the engine's
    consequence; a changed value becomes ``prism.value_edit`` (restore by default). Other
    items (added or removed columns, added rows, unreadable files) stay diff items only.

    Every consequence is computed together with the exclusions a person already accepted
    (those in the study's design and ``accepted``); a value they already exclude is not asked
    about again. With several exclusions, each one's consequence also carries what all of them
    together do (``with_all_pending``): one at a time, each may change nothing while together
    they change a conclusion. A replicate of the nested layout is named by its exact well, the
    one behind its row in the exported table (rebuilt from ``inputs``, which must be the
    inputs the bundle was exported from: the values are compared with the exported ones).

    Args:
        items: From :func:`diff`.
        study_id: The study the bundle was exported from.
        inputs: The study's inputs at the exported choices (:func:`qpcr.export.demo_inputs`).
        bundle: The exported bundle (layout per table, whether row titles were pseudonymised).
        pseudonym: The pseudonym function used at export, when it was shared.
        accepted: ``prism.exclusion_reason`` proposals a person accepted since the export.
        declined: ``prism.exclusion_reason`` questions a person rejected (or accepted as a
            restore): their values are neither asked about again nor counted as pending.
    """
    return round_trip_proposals(
        items,
        study_id,
        inputs,
        bundle=bundle,
        pseudonym=pseudonym,
        accepted=accepted,
        declined=declined,
    )[0]


def round_trip_proposals(
    items: Sequence[PrismDiffItem],
    study_id: str,
    inputs: ExportInputs,
    *,
    bundle: PrismBundle | None = None,
    pseudonym: Callable[[str], str] | None = None,
    accepted: Sequence[Proposal] = (),
    declined: Sequence[Proposal] = (),
) -> tuple[list[Proposal], dict[str, Any] | None]:
    """:func:`diff_to_proposals`, and the combined consequence of every exclusion it proposes.

    Returns:
        ``(proposals, combined)``: ``combined`` is
        :meth:`qpilot.qpcr.export.Reanalysis.combined` for all the proposed exclusions together
        (``None`` when there is none, or when it cannot be computed).
    """
    layouts = {t.name: t.layout for t in bundle.tables} if bundle is not None else {}
    shared = bundle is not None and bundle.info.get("row_titles") == "pseudonymised"
    units_by_title = {title: unit for unit, title in row_titles(inputs, shared, pseudonym).items()}
    settled = _settled(accepted)
    kept = _declined(declined, accepted)  # values a person chose to keep: never pending
    replicates, unmatched = _replicates(items, layouts, inputs)
    located: list[_Located] = []
    for item in items:
        layout = layouts.get(item.table, "column")
        unit, rep = _locate(item, layout, units_by_title)
        here = _Located(item, unit, rep)
        if unit is not None and rep and item.exported is not None:
            here = _replicate(here, replicates, unmatched)
        asks = item.kind in EXCLUSION_KINDS and not (
            item.kind == "removed_row" and layout != "column"
        )
        decided = _is_settled(settled, here) or _is_settled(kept, here)
        if item.kind == "changed" or (asks and not decided):
            located.append(here)  # a value a person decided on is not asked about again
    pending = [
        (here.item.gene, here.unit, here.rep, here.well)
        for here in located
        if here.item.kind != "changed" and here.unit is not None and not here.problem
    ]
    reanalysis: Reanalysis | None = None
    combined: dict[str, Any] | None = None
    problem = ""
    if pending:
        try:
            reanalysis = Reanalysis(inputs, accepted)
            combined = reanalysis.combined(pending)
        except (ExportError, ValueError) as err:
            problem = str(err)
    proposals = []
    for here in located:
        item, unit = here.item, here.unit
        if item.kind == "changed":
            proposals.append(_value_edit(here, study_id))
            continue
        consequence, note = None, here.problem
        if unit is not None and not note and reanalysis is None:
            note = problem
        elif unit is not None and not note and reanalysis is not None:
            try:
                consequence = reanalysis.consequence(item.gene, unit, here.rep, here.well)
            except (ExportError, ValueError) as err:
                note = str(err)
        if consequence is not None and combined is not None and len(pending) > 1:
            consequence["with_all_pending"] = {
                "n_exclusions": len(pending),
                **combined["genes"][item.gene],
                "n_conclusions_changed": combined["n_conclusions_changed"],
                "changed_genes": combined["changed_genes"],
            }
        proposals.append(_exclusion(here, study_id, consequence, note))
    return proposals, combined


@dataclass(frozen=True)
class _Located:
    """One diff item, the value it is about, and why that value cannot be named (if so)."""

    item: PrismDiffItem
    unit: str | None  # the biological unit, or None when the item names none
    rep: int  # 0: the unit's value; n: replicate n of the nested layout
    well: str | None = None  # the exact well behind replicate ``rep``, from the exported table
    problem: str = ""


def _replicates(
    items: Sequence[PrismDiffItem], layouts: Mapping[str, str], inputs: ExportInputs
) -> tuple[dict[tuple[str, str, int], tuple[str, float]], str]:
    """The exported numbering of every nested table's replicates, or why it cannot be rebuilt."""
    genes = sorted({item.gene for item in items if layouts.get(item.table) == "nested"})
    if not genes:
        return {}, ""
    try:
        return replicate_wells(inputs, genes), ""
    except ExportError as err:
        return {}, f"{NOT_THE_EXPORT} ({err})"


def _replicate(
    here: _Located, replicates: Mapping[tuple[str, str, int], tuple[str, float]], unmatched: str
) -> _Located:
    """``here`` with the exact well behind its replicate, checked against the exported value.

    A row that is the unit's value (every replicate undetermined, capped) is the whole unit.
    """
    item, unit = here.item, str(here.unit)
    if unmatched:
        return replace(here, problem=unmatched)
    found = replicates.get((item.gene, unit, here.rep))
    if found is None or found[1] != item.exported:
        return replace(here, problem=NOT_THE_EXPORT)
    rep, well = resolve_replicate(replicates, item.gene, unit, here.rep)
    return replace(here, rep=rep, well=well)


def _settled(accepted: Sequence[Proposal]) -> set[tuple[str, str, str]]:
    """The values an accepted exclusion leaves out (a later accepted restore undoes it).

    Each is ``(gene, unit, value)``: value ``""`` is the unit's (every replicate), else the
    exact well of one replicate (``"rep n"`` for an exclusion that names no well).
    """
    from qpilot.qpcr.designs import APPLIED

    out: set[tuple[str, str, str]] = set()
    for proposal in accepted:
        if proposal.kind != "prism.exclusion_reason" or proposal.status not in APPLIED:
            continue
        payload = proposal.effective_payload()
        rep = int(payload.get("well_rep") or 0)
        value = str(payload.get("well") or (f"rep {rep}" if rep else ""))
        key = (str(payload.get("gene")), str(payload.get("sample")), value)
        if payload.get("action") == "exclude":
            out.add(key)
        else:
            out.discard(key)
    return out


def _declined(
    declined: Sequence[Proposal], accepted: Sequence[Proposal]
) -> set[tuple[str, str, str]]:
    """The values a person chose to keep: a rejected exclusion question, or an accepted restore.

    Keys as in :func:`_settled`. A later accepted exclusion of the same value wins (it is in
    ``settled``, which is checked first).
    """
    from qpilot.qpcr.designs import APPLIED

    out: set[tuple[str, str, str]] = set()
    restores = [
        p
        for p in accepted
        if p.status in APPLIED and p.effective_payload().get("action") == "restore"
    ]
    for proposal in [*declined, *restores]:
        if proposal.kind != "prism.exclusion_reason":
            continue
        payload = proposal.effective_payload()
        rep = int(payload.get("well_rep") or 0)
        value = str(payload.get("well") or (f"rep {rep}" if rep else ""))
        out.add((str(payload.get("gene")), str(payload.get("sample")), value))
    return out


def _is_settled(settled: set[tuple[str, str, str]], here: _Located) -> bool:
    """True when an accepted exclusion already leaves out the value ``here`` is about."""
    gene, unit = here.item.gene, str(here.unit)
    values = {""}  # the unit's value covers every replicate
    if here.rep:
        values |= {f"rep {here.rep}", here.well or ""}
    return any((gene, unit, value) in settled for value in values)


def _what(here: _Located, capital: bool = True) -> str:
    """``Sample X for G``, or ``Replicate n of sample X for G`` for a replicate."""
    sample = f"sample {here.unit}" if here.unit is not None else "an unknown sample"
    what = f"replicate {here.rep} of {sample}" if here.rep else sample
    return f"{what[0].upper() if capital else what[0]}{what[1:]} for {here.item.gene}"


def _subject(here: _Located) -> str:
    item = here.item
    if here.unit is None:
        return f"{item.gene}/{item.row or ''}"
    return exclusion_subject(item.gene, here.unit, here.rep)


def _payload(here: _Located, action: str, question: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "gene": here.item.gene,
        "sample": here.unit,
        "action": action,
        "question": question,
        "well_rep": here.rep,
    }
    if here.well:
        payload["well"] = here.well
    return payload


def _evidence(here: _Located) -> list[Evidence]:
    item, unit = here.item, here.unit
    if _from_project(item):
        cell = f"project:{item.table}!{item.row or ''}|{item.column or ''}"
        out = [Evidence(kind="cell", ref=cell, note="the cell in the project Prism saved")]
    else:
        cell = f"sent_back/{item.table}.csv!{item.row or ''}|{item.column or ''}"
        out = [Evidence(kind="cell", ref=cell, note="the cell in the table Prism sent back")]
    if unit is not None:
        out.append(Evidence(kind="sample", ref=unit, note="the biological unit"))
    if here.well:
        note = "the well behind this replicate in the exported table"
        out.append(Evidence(kind="well", ref=here.well, note=note))
    out.append(Evidence(kind="rule", ref=f"prism.diff.{item.kind}", note=item.note[:200]))
    return out


def _exclusion(
    here: _Located, study_id: str, consequence: dict[str, Any] | None, problem: str
) -> Proposal:
    item = here.item
    deleted = item.kind != "excluded" and _from_project(item)
    if item.kind == "excluded":
        question = f"You excluded {_what(here, capital=False)} in Prism. Reason?"
    elif deleted:
        question = (
            f"You deleted {_what(here, capital=False)} in Prism. Reason? Accepting leaves the "
            "value out of the analysis; rejecting keeps qPilot's value."
        )
    else:
        question = (
            f"{_what(here)} is empty in the table Prism sent back. If you excluded it in Prism: "
            "reason? If you deleted it, say so."
        )
    details: dict[str, Any] = {}
    note = "Whether an exclusion is justified is the scientist's call; the engine shows its effect."
    if consequence is not None:
        details = {
            "conclusion_before": consequence["conclusion_before"],
            "conclusion_after": consequence["conclusion_after"],
            "n_conclusions_changed": consequence["n_conclusions_changed"],
            "n_genes": consequence["n_genes"],
        }
    elif problem:
        note = f"The consequence could not be computed: {problem}"
    if _from_project(item):
        reasons = ["Found by comparing the project Prism saved with the exported table."]
    else:
        reasons = ["Found by comparing the table Prism sent back with the exported table."]
    if item.kind != "excluded" and not deleted:
        reasons.append("An empty cell may be an exclusion or a deletion; Mode S cannot tell yet.")
    return Proposal(
        id=_proposal_id(study_id, item),
        study_id=study_id,
        kind="prism.exclusion_reason",
        subject=_subject(here),
        payload=_payload(here, "exclude", question),
        evidence=_evidence(here),
        check=ProposalCheck(
            status="cannot_check",
            rule_ids=["prism.exclusion_consequence"],
            details=details,
            note=note,
        ),
        consequence=consequence,
        level="High" if item.kind == "excluded" or deleted else "Moderate",
        reasons=reasons,
        made_by=MadeBy(kind="rule"),
    )


def _value_edit(here: _Located, study_id: str) -> Proposal:
    item = here.item
    value = f"of {_what(here, capital=False)}" if here.rep else f"for {item.gene}"
    question = f"{CHANGED_NOTE} Restore qPilot's value {value}, or record it as a manual edit?"
    return Proposal(
        id=_proposal_id(study_id, item),
        study_id=study_id,
        kind="prism.value_edit",
        subject=_subject(here),
        payload=_payload(here, "restore", question),
        evidence=_evidence(here),
        check=ProposalCheck(
            status="contradicted",
            rule_ids=["prism.value_matches_record"],
            details={"exported": item.exported, "returned": item.returned},
            note="The value differs from the one qPilot computed from the raw curves.",
        ),
        consequence={"exported": item.exported, "returned": item.returned},
        level="High",
        reasons=[
            "Found by comparing the project Prism saved with the exported table."
            if _from_project(item)
            else "Found by comparing the table Prism sent back with the exported table."
        ],
        made_by=MadeBy(kind="rule"),
    )


def _from_project(item: PrismDiffItem) -> bool:
    """True for a difference read from a saved project (its note says so), not from a CSV."""
    note = item.note or ""
    return note.startswith((DELETED_NOTE, EXCLUDED_PROJECT_NOTE, CHANGED_PROJECT_NOTE))


__all__ = [
    "DELETED_NOTE",
    "EXCLUDED_PROJECT_NOTE",
    "MAX_CELLS",
    "MAX_FILES",
    "MAX_FILE_BYTES",
    "REPLICATE_COLUMN",
    "Cell",
    "Returned",
    "RoundTripError",
    "SentBackTable",
    "diff",
    "diff_returned",
    "diff_to_proposals",
    "exported_tables",
    "is_project_path",
    "parse_number",
    "parse_table",
    "read_returned",
    "read_sent_back",
    "round_trip_proposals",
    "same_as_shown",
]
