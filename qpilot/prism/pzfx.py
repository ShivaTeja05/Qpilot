"""Prism's own project file, written and read by qPilot: the plain-XML data part of ``.pzfx``.

A ``.pzfx`` file is GraphPad Prism's XML project format. GraphPad documents its first part, the
data tables and Info sheets, as plain XML that other programs may read and write ("All you have
to do is replace the data portion of a .PZFX file, and resave it", FAQ 913 [V]); everything after
it (analyses, graphs, layouts) is a compressed binary block that only Prism reads. qPilot writes
and reads **only the plain XML part**. It never writes, decodes or parses the binary part: a file
qPilot writes has none, and when Prism saves one back the binary block (``<Template>``) is
skipped unread.

What a qPilot project holds (built by :func:`column_table`, :func:`nested_table`,
:func:`grouped_table` and written by :func:`write_project`):

* an **Info sheet** with qPilot's provenance: the study, the decision record's head, the design
  hash, the analysis settings and who decided each choice (constants and notes);
* a **Column table** per gene (``TableType="OneWay"``): one data set per group, one row per
  biological unit (row titles), the unit's log2 relative quantity in its group's column. A
  technical replicate is never a row;
* a **Grouped table** of every exported gene (``TableType="TwoWay"``, ``YFormat="replicates"``):
  genes as rows, groups as data sets, the biological units as side-by-side subcolumns with their
  names as subcolumn titles, for Prism's "Multiple t tests - one per row";
* when units have technical replicates, a **Nested table** per gene (one subcolumn per unit, its
  replicates as rows), written to its own project file by the caller (see ``docs/prism.md``:
  the Nested table's attributes are inferred, not documented [R], so it never risks the main
  project).

The structure follows GraphPad's published Prism 5 XML schema (KB 1638: element and attribute
names, ``TableType`` values ``OneWay``/``TwoWay``, ``d`` with ``Excluded="1"``) and real files
saved by Prism 6.0f, 7.0d, 8.0 and 10.2.2 (``SubColumnTitles OwnSet="1"``, ``ExtTableType``, the
default namespace, ``<d/>`` for an empty cell, a comma decimal separator in some locales). The
open-source readers and writers ``pzfx`` (R, MIT, Yue Jiang), ``pzfx_parser`` (Python, MIT) and
``prismWriter`` (Python, MIT) were read to learn the structure; no code was copied
(``THIRD_PARTY_NOTICES.md``).

**Reading is for untrusted files** (:func:`read_project`): at most :data:`MAX_PROJECT_BYTES`,
parsed with lxml with entities, DTDs and the network off (a ``<!DOCTYPE`` is refused before
parsing), at most :data:`MAX_TABLES` tables and :data:`MAX_CELLS` cells; cell text is never
evaluated (the round trip reads a cell as a number only in plain decimal notation).

Works with GraphPad Prism. Not affiliated with or endorsed by GraphPad Software or Dotmatics.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from lxml import etree

NAMESPACE = "http://graphpad.com/prism/Prism.htm"
XML_VERSION = "5.00"  # PrismXMLVersion of every file Prism 5 to 10 writes [V]
EV_FORMAT = "AsteriskAfterNumber"  # how Prism marks an excluded value in its own exports [V]
MAX_SUBCOLUMNS = 512  # per data set, Prism 9 and later (KB 845) [V]; Prism 6 to 8: 256
MAX_DATA_SETS = 1023  # data set columns per table (".pzfx" tables have fewer than 1024) [V]
MAX_PROJECT_BYTES = 64 * 1024 * 1024  # a saved project carries Prism's binary analyses too
MAX_TABLES = 2000
MAX_CELLS = 2_000_000
DECIMALS = "4"  # display only: Prism keeps the full value
ROW_TITLE_WIDTH = "125"
SUBCOLUMN_WIDTH = 81
PROGRAM = "qPilot"
INFO_TITLE = "qPilot provenance"

TableKind = Literal["column", "nested", "grouped"]
ROW_HEADER: dict[TableKind, str] = {"column": "Sample", "nested": "Replicate", "grouped": "Gene"}
_COMMA_DECIMAL = re.compile(r"[+-]?[0-9]+,[0-9]+(?:[eE][+-]?[0-9]+)?")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class PzfxError(ValueError):
    """A project cannot be written as asked, or a file is not a readable Prism XML project."""


@dataclass(frozen=True)
class PzCell:
    """One data cell: its text exactly as written (``""`` when empty) and Prism's exclusion."""

    text: str = ""
    excluded: bool = False


@dataclass(frozen=True)
class DataSet:
    """One data set (a ``YColumn``): its title and its subcolumns, each a list of row cells."""

    title: str
    subcolumns: tuple[tuple[PzCell, ...], ...]
    subcolumn_titles: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectTable:
    """One data table of a project, as qPilot writes it or as Prism saved it.

    ``name`` is qPilot's own name for the table (the bundle's table name, ``all_genes`` for the
    grouped table); it is not stored in the file, which knows tables by ``title`` only.
    """

    name: str
    kind: TableKind
    title: str
    row_titles: tuple[str, ...]
    data_sets: tuple[DataSet, ...]
    table_type: str = ""  # as read from a file (TableType / ExtTableType)

    @property
    def n_rows(self) -> int:
        """The number of rows (the longest of the row titles and every subcolumn)."""
        lengths = [len(self.row_titles)]
        lengths += [len(sub) for ds in self.data_sets for sub in ds.subcolumns]
        return max(lengths)

    def column_names(self) -> list[str]:
        """Each subcolumn's name as qPilot's CSVs write it: ``group`` or ``group/subtitle``."""
        names = []
        for ds in self.data_sets:
            if self.kind == "column":
                names.append(ds.title)
                continue
            titles = list(ds.subcolumn_titles) + [""] * len(ds.subcolumns)
            names += [f"{ds.title}/{titles[k]}" for k in range(len(ds.subcolumns))]
        return names

    def grid(self) -> list[list[PzCell]]:
        """The table as rows of cells, header first: the shape of qPilot's CSV for the table."""
        header = [PzCell(ROW_HEADER[self.kind]), *(PzCell(n) for n in self.column_names())]
        flat = [sub for ds in self.data_sets for sub in ds.subcolumns]
        rows = []
        for r in range(self.n_rows):
            title = self.row_titles[r] if r < len(self.row_titles) else ""
            cells = [sub[r] if r < len(sub) else PzCell() for sub in flat]
            rows.append([PzCell(title), *cells])
        return [header, *rows]


@dataclass(frozen=True)
class ProjectInfo:
    """The Info sheet: a title, notes (one line each) and constants (name, value)."""

    title: str = INFO_TITLE
    notes: tuple[str, ...] = ()
    constants: tuple[tuple[str, str], ...] = ()


@dataclass
class ReadProject:
    """What :func:`read_project` found in a file: its tables and Info sheets, in file order."""

    tables: list[ProjectTable] = field(default_factory=list)
    infos: list[ProjectInfo] = field(default_factory=list)
    created_by: str = ""
    problems: list[str] = field(default_factory=list)

    def by_title(self) -> dict[str, ProjectTable]:
        """Tables by title (the first of two with one title; the second is a problem)."""
        out: dict[str, ProjectTable] = {}
        for table in self.tables:
            out.setdefault(table.title, table)
        return out


# ---------------------------------------------------------------------------------------------
# Building tables from qPilot's own grids (the CSV rows: header first, all text)
# ---------------------------------------------------------------------------------------------


def _cells(values: Sequence[str]) -> tuple[PzCell, ...]:
    return tuple(PzCell(text=v) for v in values)


def column_table(name: str, title: str, grid: Sequence[Sequence[str]]) -> ProjectTable:
    """A Column table from a column-layout grid (``Sample, <group>, ...``; one row per unit)."""
    header, rows = list(grid[0]), [list(r) for r in grid[1:]]
    data_sets = tuple(
        DataSet(title=group, subcolumns=(_cells([row[c] for row in rows]),))
        for c, group in enumerate(header[1:], start=1)
    )
    return ProjectTable(
        name=name,
        kind="column",
        title=title,
        row_titles=tuple(row[0] for row in rows),
        data_sets=data_sets,
    )


def nested_table(
    name: str, title: str, grid: Sequence[Sequence[str]], pad_prefix: str = "empty_"
) -> ProjectTable:
    """A Nested table from a nested-layout grid (``Replicate, <group>/<unit>, ...``).

    Every data set has the same number of subcolumns (the grid pads groups with
    ``<group>/<pad_prefix>k``); a padding subcolumn gets an empty title.
    """
    header, rows = list(grid[0]), [list(r) for r in grid[1:]]
    order: list[str] = []
    subs: dict[str, list[tuple[str, tuple[PzCell, ...]]]] = {}
    for c, column in enumerate(header[1:], start=1):
        group, _, unit = column.partition("/")
        if group not in subs:
            order.append(group)
            subs[group] = []
        subtitle = "" if unit.startswith(pad_prefix) else unit
        subs[group].append((subtitle, _cells([row[c] for row in rows])))
    data_sets = tuple(
        DataSet(
            title=group,
            subcolumns=tuple(cells for _, cells in subs[group]),
            subcolumn_titles=tuple(t for t, _ in subs[group]),
        )
        for group in order
    )
    return ProjectTable(
        name=name,
        kind="nested",
        title=title,
        row_titles=tuple(row[0] for row in rows),
        data_sets=data_sets,
    )


def grouped_units(columns: Sequence[ProjectTable], groups: Sequence[str]) -> dict[str, list[str]]:
    """Per group, the units (row titles) in order of first appearance across the column tables.

    The grouped table's subcolumns follow this order, and the round trip rebuilds it from the
    exported column tables alone, so it needs nothing else to name a grouped table's cell.
    """
    out: dict[str, list[str]] = {g: [] for g in groups}
    for table in columns:
        for ds in table.data_sets:
            if ds.title not in out:
                continue
            seen = out[ds.title]
            for title, cell in zip(table.row_titles, ds.subcolumns[0], strict=False):
                if cell.text and title not in seen:
                    seen.append(title)
    return out


def grouped_table(
    name: str,
    title: str,
    columns: Sequence[ProjectTable],
    groups: Sequence[str],
    genes: Sequence[str],
) -> ProjectTable:
    """A Grouped table: a row per gene, groups as data sets, units as titled subcolumns.

    ``genes`` names the gene of each column table (one row each, in that order).

    Raises:
        PzfxError: A group has more biological units than Prism allows subcolumns.
    """
    units = grouped_units(columns, groups)
    widest = max((len(u) for u in units.values()), default=0)
    if widest > MAX_SUBCOLUMNS:
        raise PzfxError(
            f"a group has {widest} biological units; a Prism grouped table holds at most "
            f"{MAX_SUBCOLUMNS} subcolumns"
        )
    values: dict[tuple[str, str, str], str] = {}
    for table in columns:
        for ds in table.data_sets:
            for unit, cell in zip(table.row_titles, ds.subcolumns[0], strict=False):
                if cell.text:
                    values[(table.name, ds.title, unit)] = cell.text
    data_sets = []
    for group in groups:
        subcolumns = []
        for k in range(widest):
            unit = units[group][k] if k < len(units[group]) else None
            subcolumns.append(
                tuple(
                    PzCell(values.get((table.name, group, unit), "") if unit else "")
                    for table in columns
                )
            )
        titles = tuple(units[group][k] if k < len(units[group]) else "" for k in range(widest))
        data_sets.append(
            DataSet(title=group, subcolumns=tuple(subcolumns), subcolumn_titles=titles)
        )
    if len(genes) != len(columns):
        raise PzfxError("one gene per column table")
    return ProjectTable(
        name=name, kind="grouped", title=title, row_titles=tuple(genes), data_sets=tuple(data_sets)
    )


# ---------------------------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------------------------


def _q(tag: str) -> str:
    return f"{{{NAMESPACE}}}{tag}"


def _text(text: str, what: str) -> str:
    if _CONTROL.search(text):
        raise PzfxError(f"{what} contains a control character")
    return text


def _sub(parent: etree._Element, tag: str, text: str | None = None, **attrs: str) -> etree._Element:
    element = etree.SubElement(parent, _q(tag), {k: v for k, v in attrs.items()})
    if text is not None:
        element.text = _text(text, tag)
    return element


def _check(table: ProjectTable) -> None:
    if not table.data_sets:
        raise PzfxError(f"table {table.title!r} has no data set")
    if len(table.data_sets) > MAX_DATA_SETS:
        raise PzfxError(f"table {table.title!r}: more than {MAX_DATA_SETS} data sets")
    widths = {len(ds.subcolumns) for ds in table.data_sets}
    if table.kind == "column" and widths != {1}:
        raise PzfxError(f"column table {table.title!r} must have one subcolumn per data set")
    if table.kind != "column" and len(widths) != 1:
        raise PzfxError(f"table {table.title!r}: every data set needs the same subcolumns")
    if max(widths) > MAX_SUBCOLUMNS:
        raise PzfxError(f"table {table.title!r}: more than {MAX_SUBCOLUMNS} subcolumns")


def _table_attrs(table: ProjectTable, table_id: str) -> dict[str, str]:
    if table.kind == "column":
        return {
            "ID": table_id,
            "XFormat": "none",
            "TableType": "OneWay",
            "EVFormat": EV_FORMAT,
        }
    replicates = str(len(table.data_sets[0].subcolumns))
    attrs = {
        "ID": table_id,
        "XFormat": "none",
        "YFormat": "replicates",
        "Replicates": replicates,
        "TableType": "TwoWay" if table.kind == "grouped" else "OneWay",
        "EVFormat": EV_FORMAT,
    }
    if table.kind == "nested":
        attrs["ExtTableType"] = "Nested"  # [R] by analogy with MultipleVariables (Prism 10)
    return attrs


def _write_table(root: etree._Element, table: ProjectTable, table_id: str) -> None:
    _check(table)
    element = _sub(root, "Table", **_table_attrs(table, table_id))
    _sub(element, "Title", table.title)
    rows = _sub(element, "RowTitlesColumn", Width=ROW_TITLE_WIDTH)
    sub = _sub(rows, "Subcolumn")
    for title in table.row_titles:
        _cell(sub, PzCell(title))
    if table.kind != "column":
        titles = _sub(element, "SubColumnTitles", OwnSet="1")
        for k in range(len(table.data_sets[0].subcolumns)):
            column = _sub(titles, "Subcolumn")
            for ds in table.data_sets:
                own = ds.subcolumn_titles[k] if k < len(ds.subcolumn_titles) else ""
                _cell(column, PzCell(own))
    for ds in table.data_sets:
        y = _sub(
            element,
            "YColumn",
            Width=str(SUBCOLUMN_WIDTH * len(ds.subcolumns)),
            Decimals=DECIMALS,
            Subcolumns=str(len(ds.subcolumns)),
        )
        _sub(y, "Title", ds.title)
        for cells in ds.subcolumns:
            column = _sub(y, "Subcolumn")
            for cell in cells:
                _cell(column, cell)


def _cell(parent: etree._Element, cell: PzCell) -> None:
    attrs = {"Excluded": "1"} if cell.excluded else {}
    element = _sub(parent, "d", **attrs)
    if cell.text:
        element.text = _text(cell.text, "a cell")


def _write_info(root: etree._Element, info: ProjectInfo, info_id: str) -> None:
    element = _sub(root, "Info", ID=info_id)
    _sub(element, "Title", info.title)
    notes = _sub(element, "Notes")
    if info.notes:
        font = _sub(notes, "Font", Color="#000000", Face="Helvetica")
        last: etree._Element | None = None
        for line in info.notes:
            text = _text(line, "an Info note")
            if last is None:
                font.text = text
            else:
                last.tail = text
            last = _sub(font, "BR")
    for name, value in info.constants:
        constant = _sub(element, "Constant")
        _sub(constant, "Name", name)
        _sub(constant, "Value", value)


def write_project(tables: Sequence[ProjectTable], info: ProjectInfo, *, version: str = "") -> bytes:
    """The bytes of a ``.pzfx`` project: the Info sheet, then the tables, in the given order.

    Deterministic (no timestamps, no user name), UTF-8 with an XML declaration. Prism adds its
    analyses and graphs (the binary part) when a person saves the project in Prism.

    Raises:
        PzfxError: No table, two tables with one title, a malformed table or a control
            character in any text.
    """
    if not tables:
        raise PzfxError("a project needs at least one table")
    titles = [t.title for t in tables]
    if len(set(titles)) != len(titles):
        raise PzfxError("two tables of one project have the same title")
    root = etree.Element(_q("GraphPadPrismFile"), nsmap={None: NAMESPACE})
    root.set("PrismXMLVersion", XML_VERSION)
    created = _sub(root, "Created")
    _sub(created, "OriginalVersion", CreatedByProgram=PROGRAM, CreatedByVersion=version or "0")
    infos = _sub(root, "InfoSequence")
    _sub(infos, "Ref", ID="Info0", Selected="1")
    _write_info(root, info, "Info0")
    sequence = _sub(root, "TableSequence", Selected="1")
    for i in range(len(tables)):
        attrs = {"ID": f"Table{i}"} | ({"Selected": "1"} if i == 0 else {})
        _sub(sequence, "Ref", **attrs)
    for i, table in enumerate(tables):
        _write_table(root, table, f"Table{i}")
    # Prism's own files open with this declaration, in double quotes
    declaration = b'<?xml version="1.0" encoding="UTF-8"?>\n'
    return declaration + etree.tostring(root, encoding="UTF-8", pretty_print=True)


# ---------------------------------------------------------------------------------------------
# Reading (untrusted)
# ---------------------------------------------------------------------------------------------


def _parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
        remove_comments=True,
        remove_pis=True,
    )


def _local(element: etree._Element) -> str:
    tag = element.tag
    return etree.QName(tag).localname if isinstance(tag, str) else ""


def _children(element: etree._Element, name: str) -> list[etree._Element]:
    return [child for child in element if _local(child) == name]


def _first(element: etree._Element, name: str) -> etree._Element | None:
    found = _children(element, name)
    return found[0] if found else None


def _plain(element: etree._Element | None) -> str:
    """An element's text with every nested formatting element (``TextAlign``, ``Font``) dropped."""
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


class _Budget:
    def __init__(self) -> None:
        self.cells = MAX_CELLS

    def take(self, n: int) -> None:
        self.cells -= n
        if self.cells < 0:
            raise PzfxError(f"more than {MAX_CELLS} cells in the project; not read")


def _read_cells(subcolumn: etree._Element | None, budget: _Budget) -> tuple[PzCell, ...]:
    if subcolumn is None:
        return ()
    cells = _children(subcolumn, "d")
    budget.take(len(cells))
    return tuple(
        PzCell(text=_plain(d), excluded=d.get("Excluded", "0").strip() in ("1", "true"))
        for d in cells
    )


def _read_table(element: etree._Element, budget: _Budget) -> ProjectTable:
    table_type = element.get("TableType", "")
    ext = element.get("ExtTableType", "")
    replicates = element.get("YFormat", "") == "replicates" and element.get("Replicates", "1")
    if ext.lower() == "nested":
        kind: TableKind = "nested"
    elif table_type == "TwoWay" or (replicates and replicates != "1"):
        kind = "grouped"
    else:
        kind = "column"
    rows = _first(element, "RowTitlesColumn")
    row_titles = tuple(
        c.text for c in _read_cells(_first(rows, "Subcolumn") if rows is not None else None, budget)
    )
    own: list[list[str]] = []
    titles = _first(element, "SubColumnTitles")
    if titles is not None:
        own = [[c.text for c in _read_cells(sub, budget)] for sub in _children(titles, "Subcolumn")]
    data_sets = []
    for i, column in enumerate(_children(element, "YColumn")):
        subcolumns = tuple(_read_cells(sub, budget) for sub in _children(column, "Subcolumn"))
        sub_titles = tuple(
            (own[k][i] if i < len(own[k]) else "") if k < len(own) else ""
            for k in range(len(subcolumns))
        )
        data_sets.append(
            DataSet(
                title=_plain(_first(column, "Title")),
                subcolumns=subcolumns,
                subcolumn_titles=sub_titles if kind != "column" else (),
            )
        )
    return ProjectTable(
        name="",
        kind=kind,
        title=_plain(_first(element, "Title")),
        row_titles=row_titles,
        data_sets=tuple(data_sets),
        table_type=f"{table_type}/{ext}" if ext else table_type,
    )


def _note_lines(notes: etree._Element) -> tuple[str, ...]:
    """The Notes text as lines: a ``<BR/>`` ends a line; formatting elements are dropped."""
    lines: list[str] = []
    current: list[str] = []

    def walk(node: etree._Element) -> None:
        current.append(node.text or "")
        for child in node:
            if _local(child) == "BR":
                lines.append("".join(current))
                current.clear()
            else:
                walk(child)
            current.append(child.tail or "")

    walk(notes)
    lines.append("".join(current))
    return tuple(line.strip() for line in lines if line.strip())


def _read_info(element: etree._Element) -> ProjectInfo:
    notes = _first(element, "Notes")
    constants = tuple(
        (_plain(_first(c, "Name")), _plain(_first(c, "Value")))
        for c in _children(element, "Constant")
    )
    return ProjectInfo(
        title=_plain(_first(element, "Title")),
        notes=_note_lines(notes) if notes is not None else (),
        constants=constants,
    )


def read_project(data: bytes) -> ReadProject:
    """The data tables and Info sheets of a ``.pzfx`` file (its binary part is never read).

    Raises:
        PzfxError: Too large, a document type declaration, not well-formed XML, not a Prism
            XML project, or more than :data:`MAX_TABLES` tables or :data:`MAX_CELLS` cells.
    """
    if len(data) > MAX_PROJECT_BYTES:
        raise PzfxError(f"larger than {MAX_PROJECT_BYTES // (1024 * 1024)} MB; not read")
    head = data[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in data.lower():
        raise PzfxError("the file declares a document type or entities; not read")
    try:
        root = etree.fromstring(data, parser=_parser())
    except etree.XMLSyntaxError as err:
        raise PzfxError(f"not a well-formed XML file ({err})") from err
    if _local(root) != "GraphPadPrismFile":
        raise PzfxError("not a Prism XML project (.pzfx)")
    out = ReadProject()
    created = _first(root, "Created")
    if created is not None:
        versions = _children(created, "MostRecentVersion") or _children(created, "OriginalVersion")
        if versions:
            v = versions[-1]
            out.created_by = (
                f"{v.get('CreatedByProgram', '')} {v.get('CreatedByVersion', '')}".strip()
            )
    budget = _Budget()
    for element in root:
        name = _local(element)
        if name in ("Table", "HugeTable"):
            if len(out.tables) >= MAX_TABLES:
                raise PzfxError(f"more than {MAX_TABLES} tables; not read")
            out.tables.append(_read_table(element, budget))
        elif name == "Info":
            out.infos.append(_read_info(element))
        # Template (Prism's binary analyses and graphs) and everything else: skipped unread
    seen: set[str] = set()
    for table in out.tables:
        if table.title in seen:
            out.problems.append(f"two tables are titled {table.title!r}")
        seen.add(table.title)
    return out


def number_text(text: str) -> str:
    """A cell's text with a comma decimal separator read as a point (Prism writes ``3,5``)."""
    stripped = text.strip()
    if _COMMA_DECIMAL.fullmatch(stripped):
        return stripped.replace(",", ".")
    return stripped


def by_name(tables: Sequence[ProjectTable], names: Mapping[str, str]) -> dict[str, ProjectTable]:
    """``tables`` keyed by qPilot's name for each, matched by exact title (title -> name)."""
    out = {}
    for table in tables:
        name = names.get(table.title)
        if name is not None and name not in out:
            out[name] = table
    return out


__all__ = [
    "MAX_PROJECT_BYTES",
    "MAX_SUBCOLUMNS",
    "NAMESPACE",
    "DataSet",
    "ProjectInfo",
    "ProjectTable",
    "PzCell",
    "PzfxError",
    "ReadProject",
    "by_name",
    "column_table",
    "grouped_table",
    "grouped_units",
    "nested_table",
    "number_text",
    "read_project",
    "write_project",
]
