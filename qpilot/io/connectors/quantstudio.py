"""Thermo Fisher / Applied Biosystems exports: QuantStudio, ViiA 7, StepOne, 7500 (TXT, CSV, XLSX).

QuantStudio Real-Time PCR Software, Design & Analysis (D&A) and the older SDS software export
the same sections, either all in one text file (``[Sample Setup]``, ``[Amplification Data]``,
``[Results]`` ... each followed by its table), one file per section, or one workbook sheet per
section. Each file or sheet starts with a header block of ``* Key = Value`` lines (instrument
type and serial number, block type, passive reference, calibration dates and whether they have
expired, the analysis settings); D&A writes ``Key<TAB>Value`` lines instead. All of it is
read by header name:

* **Amplification Data** (``Well``, ``Well Position``, ``Cycle``/``Cycle Number``,
  ``Target Name``/``Target``, ``Rn``, ``Delta Rn``/``dRn``): the curves. qPilot takes **Rn**
  (reporter divided by the passive reference, not baseline-subtracted), and ``Delta Rn`` only
  when Rn is absent (then the curves are baseline-subtracted and the raw-ness detector says so).
* **Multicomponent Data** (``Cycle`` then one column per dye): used for the curves only when
  there is no Amplification Data (the reporter dye of each target, not normalised).
* **Results** / **Sample Setup** (``Sample Name``, ``Target Name``, ``Task``, ``Reporter``,
  ``CT``/``Cт``/``Cq``, ``Quantity``, ``Omit``): names, sample types, the vendor's Cq.
* **Melt Curve Raw Data** (``Temperature``, ``Fluorescence``): melt curves.

Wells are named by ``Well Position`` (``A1``) or, without it, by the ``Well`` number on the
plate the ``Block Type`` line describes. Several files of one plate (one per section) are
grouped by their file stem with the section name removed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from qpilot.io.connectors.base import CaptureError, PlateData, Probe, Sniff, Source
from qpilot.io.connectors.common import LongAssembler, header_pairs, plate_stem, well_position
from qpilot.io.connectors.headers import canonical_header
from qpilot.io.connectors.tables import (
    Grid,
    find_header,
    match_columns,
    number,
    read_grids,
    squash,
    table_at,
)

QS_COLUMNS: dict[str, tuple[str, ...]] = {
    "well": ("well position", "wellposition", "well pos"),
    "well_index": ("well", "well number"),
    "cycle": ("cycle", "cycle number", "cycle #"),
    "rn": ("rn",),
    "drn": ("delta rn", "deltarn", "drn", "Δrn"),
    "target": ("target name", "target", "detector name", "detector", "assay name"),
    "sample": ("sample name", "sample"),
    "type": ("task",),
    "dye": ("reporter", "reporter dye"),
    "cq": ("ct", "cq", "crt", "cт"),
    "quantity": ("quantity",),
    "omit": ("omit",),
    "temperature": ("temperature",),
    "fluorescence": ("fluorescence",),
    "reading": ("reading",),
    "derivative": ("derivative",),
    "amp_status": ("amp status",),
}
_NOT_DYES = {squash(s) for spellings in QS_COLUMNS.values() for s in spellings} | {
    "well",
    "wellposition",
    "omit",
}
_SECTION_NAMES = {
    "sample setup": "setup",
    "amplification data": "amplification",
    "results": "results",
    "multicomponent data": "multicomponent",
    "multicomponent": "multicomponent",
    "raw data": "raw",
    "melt curve raw data": "melt",
    "melt region normalization data": "ignored",
    "melt curve result": "ignored",
    "replicate group result": "ignored",
    "technical analysis result": "ignored",
    "reagent information": "ignored",
}
_HEADER_HINTS = {
    "instrumenttype",
    "blocktype",
    "experimentname",
    "instrumentserialnumber",
    "passivereference",
    "experimenttype",
    "softwarenameandversion",
    "quantificationcyclemethod",
}
_BLOCKS = (("1536", (32, 48)), ("384", (16, 24)), ("96", (8, 12)), ("48", (6, 8)))
_NO_PASSIVE = {"", "null", "none", "na", "nopassivereference"}


@dataclass
class _Section:
    kind: str
    rows: list[list[str]]
    decimal_comma: bool = False


@dataclass
class _Parsed:
    header: list[tuple[str, str]] = field(default_factory=list)
    sections: list[_Section] = field(default_factory=list)


def _section_kind(name: str) -> str:
    return _SECTION_NAMES.get(" ".join(name.lower().split()), "ignored")


def _kind_from_columns(row: list[str]) -> str | None:
    found = match_columns(row, QS_COLUMNS)
    if not ("well" in found or "well_index" in found):
        return None
    if "cycle" in found and ("rn" in found or "drn" in found):
        return "amplification"
    if "temperature" in found and "fluorescence" in found:
        return "melt"
    if "cq" in found and ("target" in found or "type" in found):
        return "results"
    if "cycle" in found:
        return "multicomponent"
    if "sample" in found and ("target" in found or "type" in found):
        return "setup"
    return None


def _stepone_section(kind: str, found: dict[str, int]) -> bool:
    """A section exported on its own by StepOne / 7500 software (a ``Well`` column, no position).

    Only Thermo Fisher's own column sets count: ``Rn`` with ``Delta Rn`` (amplification), or a
    ``Task`` with ``Target Name`` (results, sample setup), so a generic tidy table stays tidy.
    """
    if "well_index" not in found or "well" in found:
        return False
    if kind == "amplification":
        return "rn" in found and "drn" in found
    if kind == "results":
        return "type" in found and "target" in found
    if kind == "setup":
        return "type" in found and "target" in found and "sample" in found
    return False


_SECTION_STEMS = {squash(name) for name in _SECTION_NAMES} | {"amplification", "setup"}


def _group_key(stem: str) -> str:
    """The plate a file belongs to: its stem without the section name.

    Files named only after their section (``amplification_data.txt``, ``results.txt``,
    ``sample_setup.txt``: a StepOne export saved section by section) form one plate.
    """
    if squash(stem) in _SECTION_STEMS:
        return ""
    return plate_stem(stem).lower()


def _split(grid: Grid) -> _Parsed:
    """Header pairs and sections of one text file or sheet."""
    parsed = _Parsed()
    current: _Section | None = None
    default_kind = _section_kind(grid.name) if grid.name else ""
    for row in grid.rows:
        first = row[0].strip() if row else ""
        if first.startswith("*") and current is None:
            parsed.header.extend(header_pairs(["\t".join(row)]))
            continue
        if first.startswith("#") and current is None:  # Design & Analysis: "# Key: Value"
            key, colon, value = (grid.delimiter or ",").join(row).lstrip("#").partition(":")
            if colon and key.strip() and len(key.strip()) <= 80:
                parsed.header.append((key.strip(), value.strip()))
            continue
        if first.startswith("[") and first.endswith("]"):
            current = _Section(_section_kind(first[1:-1]), [], grid.decimal_comma)
            parsed.sections.append(current)
            continue
        if current is None:
            kind = _kind_from_columns(row) or (default_kind if default_kind != "ignored" else "")
            if not kind:
                if row and len(row) <= 3 and squash(first) in _HEADER_HINTS | {"filename"}:
                    parsed.header.extend(header_pairs(["\t".join(row)]))
                continue
            current = _Section(kind, [], grid.decimal_comma)
            parsed.sections.append(current)
        current.rows.append(row)
    return parsed


class QuantStudioConnector:
    """QuantStudio / ViiA 7 / StepOne / 7500 exports (QS RT-PCR software, D&A, SDS)."""

    id = "quantstudio"
    version = "1"
    label = "Thermo Fisher QuantStudio / Applied Biosystems export"
    suffixes = (".txt", ".csv", ".xlsx")

    def sniff(self, probe: Probe) -> Sniff | None:
        """The ``*`` header block, ``[Section]`` markers, section sheets, or QS column names."""
        if probe.kind == "xlsx":
            kinds = {_section_kind(name) for name in probe.sheets}
            if kinds & {"amplification", "results", "setup", "multicomponent"}:
                return Sniff(95, "quantstudio.xlsx")
            rows = [r for rows in probe.sheets.values() for r in rows[:60]]
        elif probe.kind == "text":
            import csv

            from qpilot.io.connectors.tables import sniff_delimiter

            delimiter = sniff_delimiter(probe.head[:300])
            lines = probe.head[:300]
            starred = {
                squash(line.lstrip("*").split("=")[0])
                for line in lines
                if line.lstrip().startswith("*")
            }
            sections = {
                _section_kind(line.strip()[1:-1])
                for line in lines
                if line.strip().startswith("[") and line.strip().endswith("]")
            }
            if len(starred & _HEADER_HINTS) >= 2 or sections - {"ignored"}:
                return Sniff(95, "quantstudio.txt")
            rows = [next(csv.reader([line], delimiter=delimiter), []) for line in lines]
        else:
            return None
        for row in rows[:60]:
            kind = _kind_from_columns(row)
            if kind is None:
                continue
            found = match_columns(row, QS_COLUMNS)
            if "well" in found and kind in ("amplification", "results", "setup", "melt"):
                return Sniff(85, f"quantstudio.{kind}")
            if _stepone_section(kind, found):
                return Sniff(80, f"quantstudio.{kind}")
        return None

    def read(self, sources: list[Source]) -> list[PlateData]:
        """One plate per file, or per group of section files sharing a stem."""
        groups: dict[str, list[Source]] = {}
        for source in sources:
            groups.setdefault(_group_key(source.path.stem), []).append(source)
        return [_read_plate(members, named=key != "") for key, members in groups.items()]


def _block(header: list[tuple[str, str]]) -> tuple[int, int]:
    for key, value in header:
        if canonical_header(key) == "block_type":
            for token, shape in _BLOCKS:
                if token in value:
                    return shape
    return (0, 0)


def _read_plate(members: list[Source], *, named: bool = True) -> PlateData:
    run_id = plate_stem(members[0].path.stem) if named else "plate"
    parsed = _Parsed()
    for source in members:
        for grid in read_grids(source.path):
            part = _split(grid)
            parsed.header.extend(p for p in part.header if p not in parsed.header)
            parsed.sections.extend(part.sections)
    rows, columns = _block(parsed.header)
    assembler = LongAssembler(run_id)
    by_kind: dict[str, list[_Section]] = {}
    for section in parsed.sections:
        by_kind.setdefault(section.kind, []).append(section)
    if not ({"amplification", "results", "setup", "multicomponent"} & set(by_kind)):
        raise CaptureError(f"{members[0].path.name}: no QuantStudio data section found")
    width = columns or 12
    info: dict[tuple[int, int], list[dict[str, str]]] = {}
    for kind in ("setup", "results"):
        for section in by_kind.get(kind, []):
            _well_info(section, width, info)
    value_kind = "unknown"
    for section in by_kind.get("amplification", []):
        value_kind = _amplification(section, width, assembler, info)
    if value_kind == "unknown" and by_kind.get("multicomponent"):
        for section in by_kind["multicomponent"]:
            if _multicomponent(section, width, assembler, info):
                value_kind = "fluorescence"
    for section in by_kind.get("melt", []):
        _melt(section, width, assembler, info)
    for (row, column), entries in info.items():  # wells with a Cq but no curve
        for entry in entries:
            if not (entry.get("sample") or entry.get("target") or entry.get("cq")):
                continue  # an empty well listed in the setup or results
            target = entry.get("target") or entry.get("dye") or "target"
            _apply(assembler.reaction(row, column, target), entry)
    plate = assembler.plate(rows=rows, columns=columns, value_kind=value_kind)
    plate.header = list(parsed.header)
    plate.header = [(canonical_header(k), v) for k, v in parsed.header]
    plate.software = next((v for k, v in plate.header if k == "software"), "")
    plate.sources = [(s.path.name, s.sniff.role) for s in members]
    if value_kind == "dRn":
        plate.notes.append(
            "The export has Delta Rn but no Rn column: the curves are baseline-subtracted. "
            "Re-export with Rn (Amplification Data) for per-well efficiency."
        )
    passive = next((v for k, v in plate.header if k == "passive_reference"), None)
    if value_kind == "Rn" and passive is not None and squash(passive) in _NO_PASSIVE:
        plate.value_kind = "fluorescence"
        plate.notes.append(
            "The export names no passive reference, so its Rn column is not a ratio to a "
            "reference dye; qPilot judges from the curves themselves whether they were processed."
        )
    return plate


def _table(section: _Section):
    header = find_header(section.rows, QS_COLUMNS, (), scan=5)
    for index, row in enumerate(section.rows[:5]):
        found = match_columns(row, QS_COLUMNS)
        if "well" in found or "well_index" in found:
            header = index
            break
    if header is None:
        return None
    return table_at(section.rows, header, QS_COLUMNS)


def _position(table, row: list[str], width: int) -> tuple[int, int] | None:
    return well_position(table.get(row, "well"), table.get(row, "well_index"), width)


def _well_info(section: _Section, width: int, info: dict) -> None:
    table = _table(section)
    if table is None:
        return
    for row in table.rows:
        position = _position(table, row, width)
        if position is None:
            continue
        entry = {
            key: table.get(row, key)
            for key in ("sample", "target", "type", "dye", "cq", "quantity", "omit")
            if table.has(key)
        }
        entry["dc"] = "1" if section.decimal_comma else ""
        entries = info.setdefault(position, [])
        for existing in entries:
            if existing.get("target", "") == entry.get("target", ""):
                for key, value in entry.items():
                    if value and not existing.get(key):
                        existing[key] = value
                break
        else:
            entries.append(entry)


def _apply(reaction, entry: dict[str, str]) -> None:
    from qpilot.io.connectors.sample_types import map_vendor_type

    dc = bool(entry.get("dc"))
    if entry.get("sample") and not reaction.sample:
        reaction.sample = entry["sample"]
    if entry.get("dye") and not reaction.dye:
        reaction.dye = entry["dye"]
    if entry.get("type") and not reaction.vendor_type:
        reaction.vendor_type = entry["type"]
        reaction.sample_type, reaction.type_mapped = map_vendor_type(entry["type"])
    cq = number(entry.get("cq", ""), decimal_comma=dc)
    if cq is not None and cq > 0 and reaction.cq is None:
        reaction.cq = cq
    quantity = number(entry.get("quantity", ""), decimal_comma=dc)
    if quantity is not None and reaction.quantity is None and reaction.sample_type == "std":
        reaction.quantity = quantity
    if entry.get("omit", "").strip().lower() in ("true", "yes", "1"):
        reaction.omitted = True


def _target_for(info: dict, position: tuple[int, int], target: str, dye: str = "") -> str:
    """The well's target: as given, else the only target the setup lists for the well."""
    if target:
        return target
    entries = info.get(position, [])
    if dye:
        for entry in entries:
            if squash(entry.get("dye", "")) == squash(dye):
                return entry.get("target") or dye
    if len(entries) == 1:
        return entries[0].get("target") or entries[0].get("dye") or "target"
    return dye or "target"


def _used(info: dict, position: tuple[int, int]) -> bool:
    """Whether the setup or results name a sample or a target for this well."""
    return any(e.get("sample") or e.get("target") for e in info.get(position, []))


def _consume(info: dict, position: tuple[int, int], target: str) -> dict[str, str] | None:
    """Take the setup entry for this well and target out of ``info`` (``None`` if absent)."""
    entries = info.get(position, [])
    for index, entry in enumerate(entries):
        if entry.get("target", "") in (target, "") or len(entries) == 1:
            found = entries.pop(index)
            if not entries:
                info.pop(position, None)
            return found
    return None


def _amplification(section: _Section, width: int, assembler: LongAssembler, info: dict) -> str:
    table = _table(section)
    if table is None:
        return "unknown"
    column = "rn" if table.has("rn") else ("drn" if table.has("drn") else None)
    if column is None:
        return "unknown"
    if column == "rn" and not any(number(table.get(r, "rn")) is not None for r in table.rows[:50]):
        column = "drn" if table.has("drn") else column
    dc = section.decimal_comma
    taken: set[tuple[int, int, str]] = set()
    for row in table.rows:
        position = _position(table, row, width)
        if position is None:
            continue
        if table.has("target") and not table.get(row, "target") and not _used(info, position):
            continue  # an empty well: no target here and no sample or target in the setup
        target = _target_for(info, position, table.get(row, "target"))
        reaction = assembler.reaction(*position, target)
        if (*position, target) not in taken:
            taken.add((*position, target))
            entry = _consume(info, position, target)
            if entry is not None:
                _apply(reaction, entry)
        x = number(table.get(row, "cycle"), decimal_comma=dc)
        y = number(table.get(row, column), decimal_comma=dc)
        if x is not None and y is not None:
            assembler.point(*position, target, x, y)
    return "Rn" if column == "rn" else "dRn"


def _multicomponent(section: _Section, width: int, assembler: LongAssembler, info: dict) -> bool:
    table = _table(section)
    if table is None or not table.has("cycle"):
        return False
    dyes = [(i, h) for i, h in enumerate(table.headers) if squash(h) and squash(h) not in _NOT_DYES]
    reporters = {squash(e.get("dye", "")) for entries in info.values() for e in entries}
    used = [(i, h) for i, h in dyes if squash(h) in reporters] or [
        (i, h) for i, h in dyes if squash(h) not in ("rox", "mustanggreen", "passive")
    ]
    if not used:
        return False
    dc = section.decimal_comma
    taken: set[tuple[int, int, str]] = set()
    for row in table.rows:
        position = _position(table, row, width)
        if position is None:
            continue
        x = number(table.get(row, "cycle"), decimal_comma=dc)
        for index, dye in used:
            y = number(row[index], decimal_comma=dc) if index < len(row) else None
            target = _target_for(info, position, "", dye)
            reaction = assembler.reaction(*position, target, dye=dye)
            if (*position, target) not in taken:
                taken.add((*position, target))
                entry = _consume(info, position, target)
                if entry is not None:
                    _apply(reaction, entry)
            if x is not None and y is not None:
                assembler.point(*position, target, x, y)
    return True


def _melt(section: _Section, width: int, assembler: LongAssembler, info: dict) -> None:
    table = _table(section)
    if table is None:
        return
    dc = section.decimal_comma
    for row in table.rows:
        position = _position(table, row, width)
        if position is None:
            continue
        target = table.get(row, "target")
        if not target:
            known = [k for k in assembler.parts if k[:2] == position]
            target = known[0][2] if len(known) == 1 else _target_for(info, position, "")
        assembler.reaction(*position, target)
        x = number(table.get(row, "temperature"), decimal_comma=dc)
        y = number(table.get(row, "fluorescence"), decimal_comma=dc)
        if x is not None and y is not None:
            assembler.point(*position, target, x, y, melt=True)


CONNECTOR = QuantStudioConnector()

__all__ = ["CONNECTOR", "QS_COLUMNS", "QuantStudioConnector"]
