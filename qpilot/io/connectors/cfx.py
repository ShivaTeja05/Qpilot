"""Bio-Rad CFX Manager / CFX Maestro exports ("Export All Data Sheets", CSV or XLSX).

One CFX run exports several sheets; qPilot reads four of them, found by their headers:

* **Quantification Amplification Results** (one file per fluorophore, ``…_SYBR.csv``, or one
  workbook with a sheet per fluorophore): a ``Cycle`` column, then one column per well
  (``A1`` ... ``H12``), values in RFU. CFX applies the baseline mode in force when the data
  were exported ("Baseline Subtracted Curve Fit" by default), so these curves are raw only if
  the analyst chose "No Baseline Subtraction" first; the raw-ness detector checks.
* **Quantification Cq Results** / **Quantification Summary**: ``Well``, ``Fluor``,
  ``Target``, ``Content`` (``Unkn-01``, ``Std-02``, ``NTC``, ``NRT``, ``Pos Ctrl``…),
  ``Sample``, ``Cq``, ``Starting Quantity (SQ)``: names, sample types, the vendor's Cq.
* **Melt Curve RFU Results** (per fluorophore): ``Temperature`` then one column per well.
  The derivative sheet is not read (qPilot recomputes derivatives).
* **Run Information**: key/value rows (file name, run dates, base and optical-head serial
  numbers, software version), kept as quarantined header text.

Files of one run are grouped by their file stem with the sheet name removed
(``run1 -  Quantification Cq Results.csv`` and ``run1 -  Quantification Amplification
Results_SYBR.csv`` are plate ``run1``). Wells are joined by well and fluorophore.
"""

from __future__ import annotations

import re

from qpilot.io.connectors.base import (
    CaptureError,
    Curve,
    PlateData,
    Probe,
    Reaction,
    Sniff,
    Source,
)
from qpilot.io.connectors.builder import parse_well, well_name
from qpilot.io.connectors.common import COLUMNS, header_pairs, plate_stem
from qpilot.io.connectors.headers import canonical_header
from qpilot.io.connectors.sample_types import map_vendor_type
from qpilot.io.connectors.tables import (
    Grid,
    find_header,
    match_columns,
    number,
    read_grids,
    squash,
    table_at,
)

_CQ_REQUIRED = ("well", "fluor", "content")
_CQ_COLUMNS = {
    **COLUMNS,
    "fluor": ("fluor", "fluorophore", "dye"),
    "content": ("content",),
    "sq": ("starting quantity (sq)", "starting quantity", "sq"),
    "dye": (),
    "type": (),
    "quantity": (),
}
_RUN_INFO_KEYS = {
    "filename",
    "runstarted",
    "runended",
    "baseserialnumber",
    "opticalheadserialnumber",
    "createdbyuser",
    "protocolfilename",
    "platesetupfilename",
    "cfxmanagerversion",
    "cfxmaestroversion",
    "samplevol",
    "lidtemp",
}
_DATA_ROLES = ("amplification", "cq", "melt")
_FLUOR_SUFFIX = re.compile(r"_([A-Za-z0-9][A-Za-z0-9 ()/+-]{0,23})$")


def _well_columns(row: list[str], axis: str) -> int:
    """How many well labels follow the ``axis`` cell (``Cycle`` or ``Temperature``) in ``row``."""
    squashed = [squash(c) for c in row]
    if axis not in squashed:
        return 0
    start = squashed.index(axis) + 1
    return sum(1 for c in row[start:] if parse_well(c) is not None)


def _sheets(probe: Probe) -> list[list[list[str]]]:
    if probe.kind == "xlsx":
        return list(probe.sheets.values())
    if probe.kind != "text":
        return []
    import csv

    from qpilot.io.connectors.tables import sniff_delimiter

    delimiter = sniff_delimiter(probe.head[:100])
    return [[next(csv.reader([line], delimiter=delimiter), []) for line in probe.head[:100]]]


class CfxConnector:
    """CFX Manager / CFX Maestro spreadsheet exports (CSV, TXT or XLSX)."""

    id = "cfx"
    version = "1"
    label = "Bio-Rad CFX Manager / Maestro export"
    suffixes = (".csv", ".txt", ".xlsx")

    def sniff(self, probe: Probe) -> Sniff | None:
        """Curve sheets by ``Cycle``/``Temperature`` + well columns; other sheets by name."""
        name = probe.path.name.lower()
        for rows in _sheets(probe):
            for row in rows[:20]:
                if _well_columns(row, "cycle") >= 1:
                    return Sniff(90, "cfx.amplification", "amplification")
                if _well_columns(row, "temperature") >= 1:
                    if "derivative" in name:
                        return Sniff(85, "cfx.melt_derivative", "ignored")
                    return Sniff(90, "cfx.melt", "melt")
                found = match_columns(row, _CQ_COLUMNS)
                if all(c in found for c in _CQ_REQUIRED) and "cq" in found:
                    return Sniff(90, "cfx.cq", "cq")
            keys = {squash(row[0]) for row in rows[:40] if row}
            if len(keys & _RUN_INFO_KEYS) >= 3:
                return Sniff(80, "cfx.run_information", "setup")
        return None

    def read(self, sources: list[Source]) -> list[PlateData]:
        """One plate per run stem, joining amplification, Cq, melt and run-information files."""
        groups: dict[str, list[Source]] = {}
        for source in sources:
            groups.setdefault(plate_stem(source.path.stem).lower(), []).append(source)
        data = {k: m for k, m in groups.items() if any(s.sniff.role in _DATA_ROLES for s in m)}
        for key, members in groups.items():  # a lone Run Information sheet joins the only run
            if key not in data and len(data) == 1:
                next(iter(data.values())).extend(members)
        return [_read_run(members) for members in data.values()]


def _fluor_from_name(stem: str) -> str:
    match = _FLUOR_SUFFIX.search(stem)
    if match is None:
        return ""
    fluor = match.group(1).strip()
    return "" if squash(fluor) in ("results", "data", "0", "1") else fluor


def _read_run(members: list[Source]) -> PlateData:
    run_id = plate_stem(members[0].path.stem)
    plate = PlateData(run_id=run_id, value_kind="RFU")
    amp: dict[tuple[str, str], Curve] = {}  # (well, fluor) -> curve
    melt: dict[tuple[str, str], Curve] = {}
    setup: dict[tuple[str, str], dict[str, str]] = {}  # (well, fluor) -> Cq-results row
    for source in members:
        role = source.sniff.role
        plate.sources.append((source.path.name, role))
        if role == "ignored":
            continue
        for grid in read_grids(source.path):
            fluor = grid.name if grid.name and squash(grid.name) not in ("0", "sheet1") else ""
            fluor = fluor or _fluor_from_name(source.path.stem)
            if role == "amplification":
                amp.update(_wide_curves(grid, "cycle", fluor, source.path.name))
            elif role == "melt":
                melt.update(_wide_curves(grid, "temperature", fluor, source.path.name))
            elif role == "cq":
                setup.update(_cq_rows(grid, source.path.name))
            elif role == "setup":
                for key, value in header_pairs("\t".join(row) for row in grid.rows):
                    canonical = canonical_header(key)
                    plate.header.append((canonical, value))
                    if canonical == "software":
                        plate.software = value
    if not amp and not setup and not melt:
        raise CaptureError(f"{members[0].path.name}: no CFX amplification or Cq data found")
    _join(plate, amp, melt, setup)
    if amp and not setup:
        plate.notes.append(
            "Only the amplification sheet was given: targets are named after the fluorophore "
            "and no sample names or types are known. Add the Quantification Cq Results sheet."
        )
    return plate


def _wide_curves(grid: Grid, axis: str, fluor: str, name: str) -> dict[tuple[str, str], Curve]:
    header = None
    for index, row in enumerate(grid.rows[:40]):
        if _well_columns(row, axis) >= 1:
            header = index
            break
    if header is None:
        raise CaptureError(f"{name}: no {axis} column followed by well columns")
    head = grid.rows[header]
    x_index = [squash(c) for c in head].index(axis)
    wells = [(i, parse_well(c)) for i, c in enumerate(head) if i > x_index]
    wells = [(i, w) for i, w in wells if w is not None]
    xs: list[float] = []
    ys: dict[int, list[float | None]] = {i: [] for i, _ in wells}
    for row in grid.rows[header + 1 :]:
        if x_index >= len(row):
            continue
        x = number(row[x_index], decimal_comma=grid.decimal_comma)
        if x is None:
            continue
        xs.append(x)
        for i, _ in wells:
            ys[i].append(number(row[i], decimal_comma=grid.decimal_comma) if i < len(row) else None)
    if len(set(xs)) != len(xs):
        raise CaptureError(f"{name}: a {axis} value appears twice")
    curves = {}
    for i, (r, c) in wells:
        points = [(x, y) for x, y in zip(xs, ys[i], strict=True) if y is not None]
        if points:
            points.sort()
            curves[(well_name(r, c), squash(fluor))] = Curve(
                tuple(p[0] for p in points), tuple(p[1] for p in points)
            )
    return curves


def _cq_rows(grid: Grid, name: str) -> dict[tuple[str, str], dict[str, str]]:
    header = find_header(grid.rows, _CQ_COLUMNS, _CQ_REQUIRED)
    if header is None:
        raise CaptureError(f"{name}: no Well / Fluor / Content header")
    table = table_at(grid.rows, header, _CQ_COLUMNS, stop_at_blank=False)
    out: dict[tuple[str, str], dict[str, str]] = {}
    for row in table.rows:
        position = parse_well(table.get(row, "well"))
        if position is None:
            continue
        key = (well_name(*position), squash(table.get(row, "fluor")))
        record = {
            name_: table.get(row, name_)
            for name_ in ("fluor", "target", "content", "sample", "cq", "sq")
        }
        record["decimal_comma"] = "1" if grid.decimal_comma else ""
        if key in out and out[key] != record:
            raise CaptureError(f"{name}: well {key[0]} is listed twice for one fluorophore")
        out[key] = record
    return out


def _join(
    plate: PlateData,
    amp: dict[tuple[str, str], Curve],
    melt: dict[tuple[str, str], Curve],
    setup: dict[tuple[str, str], dict[str, str]],
) -> None:
    setup_fluors = {k[1] for k in setup}
    if len(setup_fluors) == 1:
        # curves whose file names no fluorophore belong to the Cq sheet's only one
        only = next(iter(setup_fluors))
        amp = {(w, f or only): c for (w, f), c in amp.items()}
        melt = {(w, f or only): c for (w, f), c in melt.items()}
    keys = sorted(set(amp) | set(setup) | set(melt))
    fluor_names = {k[1]: "" for k in keys}
    for record in setup.values():
        fluor_names[squash(record["fluor"])] = record["fluor"]
    for well, fluor_key in keys:
        record = setup.get((well, fluor_key))
        position = parse_well(well)
        assert position is not None
        dc = bool(record and record.get("decimal_comma"))
        content = record["content"] if record else ""
        mapped, known = map_vendor_type(content)
        fluor = (record["fluor"] if record else "") or fluor_names.get(fluor_key) or fluor_key
        target = (record["target"] if record else "") or fluor or "target"
        cq = number(record["cq"], decimal_comma=dc) if record else None
        quantity = number(record["sq"], decimal_comma=dc) if record else None
        sample = record["sample"] if record else ""
        if not sample and not target and not content:
            continue
        plate.reactions.append(
            Reaction(
                well=well,
                row=position[0],
                column=position[1],
                sample=sample,
                target=target,
                dye=fluor,
                sample_type=mapped,
                vendor_type=content,
                type_mapped=known,
                cq=cq if cq is not None and cq > 0 else None,
                quantity=quantity if mapped == "std" else None,
                amp=amp.get((well, fluor_key)),
                melt=melt.get((well, fluor_key)),
            )
        )


CONNECTOR = CfxConnector()

__all__ = ["CONNECTOR", "CfxConnector"]
