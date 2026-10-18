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
proposal whose consequence the engine computes (that gene's comparison again without the value:
fold change, p and conclusion before and after, and how many of all genes' conclusions change),
and a changed value into a ``prism.value_edit`` proposal ("this value no longer matches the
record", action ``restore`` by default). They are made by a rule, never accepted here: only a
person accepts a proposal.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from qpilot.prism.tables import REPLICATE_COLUMN, row_titles
from qpilot.qpcr.export import ExportError, ExportInputs, exclusion_consequence
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
CHANGED_NOTE = "This value no longer matches the record."


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
) -> list[Proposal]:
    """Turn diff items into proposals for the inbox (never accepted here).

    A missing, excluded or removed value becomes ``prism.exclusion_reason`` with the engine's
    consequence; a changed value becomes ``prism.value_edit`` (restore by default). Other
    items (added or removed columns, added rows, unreadable files) stay diff items only.

    Args:
        items: From :func:`diff`.
        study_id: The study the bundle was exported from.
        inputs: The study's inputs at the exported choices (:func:`qpcr.export.demo_inputs`).
        bundle: The exported bundle (layout per table, whether row titles were pseudonymised).
        pseudonym: The pseudonym function used at export, when it was shared.
    """
    layouts = {t.name: t.layout for t in bundle.tables} if bundle is not None else {}
    shared = bundle is not None and bundle.info.get("row_titles") == "pseudonymised"
    units_by_title = {title: unit for unit, title in row_titles(inputs, shared, pseudonym).items()}
    proposals = []
    for item in items:
        layout = layouts.get(item.table, "column")
        if item.kind in EXCLUSION_KINDS and not (item.kind == "removed_row" and layout != "column"):
            proposals.append(_exclusion(item, study_id, inputs, layout, units_by_title))
        elif item.kind == "changed":
            proposals.append(_value_edit(item, study_id, layout, units_by_title))
    return proposals


def _evidence(item: PrismDiffItem, unit: str | None) -> list[Evidence]:
    cell = f"sent_back/{item.table}.csv!{item.row or ''}|{item.column or ''}"
    out = [Evidence(kind="cell", ref=cell, note="the cell in the table Prism sent back")]
    if unit is not None:
        out.append(Evidence(kind="sample", ref=unit, note="the biological unit"))
    out.append(Evidence(kind="rule", ref=f"prism.diff.{item.kind}", note=item.note[:200]))
    return out


def _exclusion(
    item: PrismDiffItem,
    study_id: str,
    inputs: ExportInputs,
    layout: str,
    units_by_title: Mapping[str, str],
) -> Proposal:
    unit, rep = _locate(item, layout, units_by_title)
    sample = unit or "an unknown sample"
    if item.kind == "excluded":
        question = f"You excluded sample {sample} for {item.gene} in Prism. Reason?"
    else:
        question = (
            f"Sample {sample} for {item.gene} is empty in the table Prism sent back. If you "
            "excluded it in Prism: reason? If you deleted it, say so."
        )
    consequence: dict[str, Any] | None = None
    details: dict[str, Any] = {}
    note = "Whether an exclusion is justified is the scientist's call; the engine shows its effect."
    if unit is not None:
        try:
            consequence = exclusion_consequence(inputs, item.gene, unit, rep, layout=layout)
            details = {
                "conclusion_before": consequence["conclusion_before"],
                "conclusion_after": consequence["conclusion_after"],
                "n_conclusions_changed": consequence["n_conclusions_changed"],
                "n_genes": consequence["n_genes"],
            }
        except (ExportError, ValueError) as err:
            note = f"The consequence could not be computed: {err}"
    payload: dict[str, Any] = {
        "gene": item.gene,
        "sample": unit,
        "action": "exclude",
        "question": question,
        "well_rep": rep,
    }
    reasons = ["Found by comparing the table Prism sent back with the exported table."]
    if item.kind != "excluded":
        reasons.append("An empty cell may be an exclusion or a deletion; Mode S cannot tell yet.")
    return Proposal(
        id=_proposal_id(study_id, item),
        study_id=study_id,
        kind="prism.exclusion_reason",
        subject=f"{item.gene}/{unit or item.row or ''}",
        payload=payload,
        evidence=_evidence(item, unit),
        check=ProposalCheck(
            status="cannot_check",
            rule_ids=["prism.exclusion_consequence"],
            details=details,
            note=note,
        ),
        consequence=consequence,
        level="High" if item.kind == "excluded" else "Moderate",
        reasons=reasons,
        made_by=MadeBy(kind="rule"),
    )


def _value_edit(
    item: PrismDiffItem, study_id: str, layout: str, units_by_title: Mapping[str, str]
) -> Proposal:
    unit, rep = _locate(item, layout, units_by_title)
    return Proposal(
        id=_proposal_id(study_id, item),
        study_id=study_id,
        kind="prism.value_edit",
        subject=f"{item.gene}/{unit or item.row or ''}",
        payload={
            "gene": item.gene,
            "sample": unit,
            "action": "restore",
            "question": (
                f"{CHANGED_NOTE} Restore qPilot's value for {item.gene}, or record it as a "
                "manual edit?"
            ),
            "well_rep": rep,
        },
        evidence=_evidence(item, unit),
        check=ProposalCheck(
            status="contradicted",
            rule_ids=["prism.value_matches_record"],
            details={"exported": item.exported, "returned": item.returned},
            note="The value differs from the one qPilot computed from the raw curves.",
        ),
        consequence={"exported": item.exported, "returned": item.returned},
        level="High",
        reasons=["Found by comparing the table Prism sent back with the exported table."],
        made_by=MadeBy(kind="rule"),
    )


__all__ = [
    "MAX_CELLS",
    "MAX_FILES",
    "MAX_FILE_BYTES",
    "REPLICATE_COLUMN",
    "Cell",
    "RoundTripError",
    "SentBackTable",
    "diff",
    "diff_to_proposals",
    "exported_tables",
    "parse_number",
    "parse_table",
    "read_sent_back",
    "same_as_shown",
]
