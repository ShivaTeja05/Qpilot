"""Write plates as a deterministic RDML 1.4 document: the one format the engine reads.

Every connector ends here. The same plates always give the same bytes:

* no ``dateMade``/``dateUpdated`` (the schema makes them optional), elements in schema order,
  numbers written with Python's shortest round-trip ``repr``;
* samples, targets and dyes in order of first appearance (plates in the order given, reactions
  sorted by well and target);
* the RDML archive is a zip with one member, ``rdml_data.xml``, *stored* (not deflated) with a
  fixed timestamp, so the bytes do not depend on the zlib build.

One RDML experiment (:data:`EXPERIMENT_ID`) holds one run per plate. Reaction ids number the
wells row by row from 1, as LinRegPCR reads them (``pcrFormat`` gives the plate width). A well
without a sample name gets the sample id ``<run>_<well>`` (each such well is its own sample, so
no two unnamed wells are merged). A sample's RDML type is its wells' type; when its wells
disagree for one target the most common type wins (ties: ``ntc``, ``nrt``, ``std``, ``pos``,
then the rest) and a ``TYPE_CONFLICT`` warning says so.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from lxml import etree

from qpilot.io.connectors.base import CaptureError, PlateData, Reaction

EXPERIMENT_ID = "qpilot_import"
RDML_NS = "http://www.rdml.org"
RDML_MEMBER = "rdml_data.xml"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

#: Standard plate formats, smallest first: (rows, columns).
PLATE_FORMATS: tuple[tuple[int, int], ...] = ((6, 8), (8, 12), (16, 24), (32, 48))
MAX_WELLS = 1536
MAX_CYCLES = 200
MAX_MELT_POINTS = 2000
MAX_PLATES = 64
MAX_ID_CHARS = 64

_TYPE_PRIORITY = ("ntc", "nrt", "std", "pos", "nac", "ntp", "opt", "unkn")
_XML_ILLEGAL = re.compile("[^\x09\x0a\x0d\x20-퟿-�\U00010000-\U0010ffff]")
_WELL = re.compile(r"^([A-Za-z]{1,2})0*([1-9][0-9]{0,2})$")


def clean_id(text: str, fallback: str) -> str:
    """An RDML id from file text: XML-illegal characters removed, trimmed, at most 64 chars.

    The engine still turns anything that is not a plain identifier into its safe name; this only
    makes the text storable in XML.
    """
    cleaned = _XML_ILLEGAL.sub("", str(text)).strip()[:MAX_ID_CHARS].strip()
    return cleaned or fallback


def parse_well(label: str) -> tuple[int, int] | None:
    """``(row, column)`` of a well label (``A1``, ``a01``, ``AB12``), or ``None``."""
    match = _WELL.match(label.strip())
    if match is None:
        return None
    letters, digits = match.group(1).upper(), int(match.group(2))
    row = 0
    for char in letters:
        row = row * 26 + (ord(char) - ord("A") + 1)
    return row, digits


def well_name(row: int, column: int) -> str:
    """The well label for 1-based ``row`` and ``column`` (``A1``; row 27 is ``AA``)."""
    letters = ""
    value = row
    while value:
        value, rest = divmod(value - 1, 26)
        letters = chr(ord("A") + rest) + letters
    return f"{letters}{column}"


def plate_format(plate: PlateData) -> tuple[int, int]:
    """The plate's (rows, columns): as the reader said, else the smallest standard plate.

    Raises:
        CaptureError: A well lies outside every standard plate, or outside the stated format.
    """
    max_row = max((r.row for r in plate.reactions), default=1)
    max_col = max((r.column for r in plate.reactions), default=1)
    if plate.rows and plate.columns:
        if max_row > plate.rows or max_col > plate.columns:
            raise CaptureError(
                f"plate {plate.run_id}: a well lies outside its "
                f"{plate.rows} x {plate.columns} format"
            )
        return plate.rows, plate.columns
    for rows, columns in PLATE_FORMATS:
        if max_row <= rows and max_col <= columns:
            return rows, columns
    raise CaptureError(f"plate {plate.run_id}: wells outside a 1536-well plate")


def _num(value: float) -> str:
    number = float(value)
    if number.is_integer() and abs(number) < 1e15:
        return str(int(number))
    return repr(number)


@dataclass
class BuildNotes:
    """What the builder had to decide, for :class:`~qpilot.io.connectors.base.CaptureMeta`."""

    type_conflicts: int = 0
    quantity_conflicts: int = 0
    unnamed_wells: int = 0
    dye_conflicts: int = 0
    role_conflicts: int = 0
    sample_ids: dict[tuple[str, str], str] = field(default_factory=dict)  # (run, well) -> id


def _sub(
    parent: etree._Element, tag: str, text: str | None = None, **attrib: str
) -> etree._Element:
    element = etree.SubElement(parent, f"{{{RDML_NS}}}{tag}", attrib)
    if text is not None:
        element.text = text
    return element


def _majority(types: Counter[str]) -> str:
    best = max(types.values())
    for candidate in _TYPE_PRIORITY:
        if types.get(candidate, 0) == best:
            return candidate
    return "unkn"


def _sample_id(plate_id: str, reaction: Reaction, notes: BuildNotes) -> str:
    name = clean_id(reaction.sample, "")
    if not name:
        notes.unnamed_wells += 1
        return f"{plate_id[: MAX_ID_CHARS - 8]}_{reaction.well}"
    return name


def _check_limits(plates: Sequence[PlateData]) -> None:
    if not plates:
        raise CaptureError("no plate with any well was found in the input")
    if len(plates) > MAX_PLATES:
        raise CaptureError(f"more than {MAX_PLATES} plates in one import")
    for plate in plates:
        wells = {(r.row, r.column) for r in plate.reactions}
        if len(wells) > MAX_WELLS:
            raise CaptureError(f"plate {plate.run_id}: more than {MAX_WELLS} wells")
        for reaction in plate.reactions:
            if reaction.amp is not None and len(reaction.amp.x) > MAX_CYCLES:
                raise CaptureError(f"plate {plate.run_id}: more than {MAX_CYCLES} cycles")
            if reaction.melt is not None and len(reaction.melt.x) > MAX_MELT_POINTS:
                raise CaptureError(
                    f"plate {plate.run_id}: more than {MAX_MELT_POINTS} melt-curve points"
                )


def unique_run_ids(plates: Iterable[PlateData]) -> None:
    """Make run ids storable and unique in place (``plate``, ``plate_2``, ...)."""
    seen: set[str] = set()
    for index, plate in enumerate(plates, start=1):
        base = clean_id(plate.run_id, f"plate{index}")
        candidate, n = base, 1
        while candidate.lower() in seen:
            n += 1
            candidate = f"{base[: MAX_ID_CHARS - 4]}_{n}"
        seen.add(candidate.lower())
        plate.run_id = candidate


def build_xml(
    plates: Sequence[PlateData], *, experiment_id: str = EXPERIMENT_ID, description: str = ""
) -> tuple[bytes, BuildNotes]:
    """The RDML 1.4 XML for ``plates`` (deterministic bytes) and what the builder decided.

    Raises:
        CaptureError: No plates, too many plates / wells / cycles, or a well outside its plate.
    """
    _check_limits(plates)
    unique_run_ids(plates)
    notes = BuildNotes()
    root = etree.Element(f"{{{RDML_NS}}}rdml", nsmap={None: RDML_NS}, version="1.4")

    # Collect samples, targets and dyes in order of first appearance.
    ordered: list[tuple[PlateData, list[Reaction]]] = []
    sample_types: dict[str, dict[str, Counter[str]]] = {}
    sample_quantities: dict[str, dict[str, float]] = {}
    target_dyes: dict[str, str] = {}
    target_types: dict[str, set[str]] = {}
    dyes: list[str] = []
    for plate in plates:
        reactions = sorted(plate.reactions, key=lambda r: (r.row, r.column, clean_id(r.target, "")))
        ordered.append((plate, reactions))
        for reaction in reactions:
            sample = _sample_id(plate.run_id, reaction, notes)
            notes.sample_ids[(plate.run_id, reaction.well)] = sample
            target = clean_id(reaction.target, clean_id(reaction.dye, "target"))
            dye = clean_id(reaction.dye, target)
            if dye not in dyes:
                dyes.append(dye)
            previous = target_dyes.setdefault(target, dye)
            if previous != dye:
                notes.dye_conflicts += 1
            if reaction.target_type in ("ref", "toi"):
                target_types.setdefault(target, set()).add(reaction.target_type)
            sample_types.setdefault(sample, {}).setdefault(target, Counter())[
                reaction.sample_type
            ] += 1
            if reaction.quantity is not None:
                known = sample_quantities.setdefault(sample, {})
                if target in known and known[target] != reaction.quantity:
                    notes.quantity_conflicts += 1
                known.setdefault(target, reaction.quantity)

    for dye in dyes:
        _sub(root, "dye", id=dye)
    for sample, by_target in sample_types.items():
        element = _sub(root, "sample", id=sample)
        per_target = {}
        for target, counts in by_target.items():
            if len(counts) > 1:
                notes.type_conflicts += 1
            per_target[target] = _majority(counts)
        overall = _majority(Counter(per_target.values()))
        _sub(element, "type", overall)
        for target, chosen in per_target.items():
            if chosen != overall:
                _sub(element, "type", chosen, targetId=target)
        quantities = sample_quantities.get(sample, {})
        values = set(quantities.values())
        if len(values) == 1 and len(quantities) == len(by_target):
            quantity = _sub(element, "quantity")
            _sub(quantity, "value", _num(next(iter(values))))
            _sub(quantity, "unit", "other")
        else:
            for target, value in quantities.items():
                quantity = _sub(element, "quantity", targetId=target)
                _sub(quantity, "value", _num(value))
                _sub(quantity, "unit", "other")
    for target, dye in target_dyes.items():
        element = _sub(root, "target", id=target)
        declared = target_types.get(target, set())
        if len(declared) > 1:
            notes.role_conflicts += 1
        _sub(element, "type", "ref" if declared == {"ref"} else "toi")  # the file's own word
        _sub(element, "dyeId", id=dye)

    experiment = _sub(root, "experiment", id=experiment_id)
    for plate, reactions in ordered:
        rows, columns = plate_format(plate)
        run = _sub(experiment, "run", id=plate.run_id)
        if description:
            _sub(run, "description", description)
        fmt = _sub(run, "pcrFormat")
        _sub(fmt, "rows", str(rows))
        _sub(fmt, "columns", str(columns))
        _sub(fmt, "rowLabel", "ABC")
        _sub(fmt, "columnLabel", "123")
        by_well: dict[int, list[Reaction]] = {}
        for reaction in reactions:
            react_id = (reaction.row - 1) * columns + reaction.column
            by_well.setdefault(react_id, []).append(reaction)
        for react_id in sorted(by_well):
            group = by_well[react_id]
            react = _sub(run, "react", id=str(react_id))
            _sub(react, "sample", id=notes.sample_ids[(plate.run_id, group[0].well)])
            seen_targets: set[str] = set()
            for reaction in group:
                target = clean_id(reaction.target, clean_id(reaction.dye, "target"))
                if target in seen_targets:
                    raise CaptureError(
                        f"plate {plate.run_id} well {reaction.well}: one target appears twice"
                    )
                seen_targets.add(target)
                _data(react, target, reaction)
    xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
    return xml, notes


def _data(react: etree._Element, target: str, reaction: Reaction) -> None:
    data = _sub(react, "data")
    _sub(data, "tar", id=target)
    if reaction.cq is not None:
        _sub(data, "cq", _num(reaction.cq))
    if reaction.amp is not None:
        for cycle, fluor in zip(reaction.amp.x, reaction.amp.y, strict=True):
            point = _sub(data, "adp")
            _sub(point, "cyc", _num(cycle))
            _sub(point, "fluor", _num(fluor))
    if reaction.melt is not None:
        for temperature, fluor in zip(reaction.melt.x, reaction.melt.y, strict=True):
            point = _sub(data, "mdp")
            _sub(point, "tmp", _num(temperature))
            _sub(point, "fluor", _num(fluor))


def rdml_archive(xml: bytes) -> bytes:
    """``xml`` as RDML archive bytes: one stored member, fixed timestamp (deterministic)."""
    buffer = io.BytesIO()
    info = zipfile.ZipInfo(RDML_MEMBER, date_time=ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = 0o644 << 16
    info.create_system = 3
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(info, xml)
    return buffer.getvalue()


def load_xml(xml: bytes):  # -> rdml.Rdml
    """The vendored rdmlpython document for ``xml`` (parsed with the hardened parser)."""
    from qpilot.io.rdml_io import hardened_parser
    from qpilot.vendor.rdmlpython import rdml

    etree.set_default_parser(hardened_parser())
    doc = rdml.Rdml()
    try:
        doc.loadXMLString(xml.decode("utf-8"))
    except rdml.RdmlError as err:
        raise CaptureError(f"the RDML qPilot built could not be read back ({err})") from err
    return doc


__all__ = [
    "EXPERIMENT_ID",
    "MAX_CYCLES",
    "MAX_PLATES",
    "MAX_WELLS",
    "PLATE_FORMATS",
    "BuildNotes",
    "build_xml",
    "clean_id",
    "load_xml",
    "parse_well",
    "plate_format",
    "unique_run_ids",
    "well_name",
    "rdml_archive",
]
