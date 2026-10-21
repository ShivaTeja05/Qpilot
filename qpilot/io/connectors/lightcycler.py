"""Roche LightCycler 480 text exports: raw fluorescence per acquisition, and the Cp table.

The export is one tab-separated table, optionally after an ``Experiment: … Selected Filter: …``
line: one row per well and acquisition with columns found by name (``SamplePos``/``Pos``,
``SampleName``/``Name``, ``Prog``/``Program``, ``Seg``/``Segment``, ``Cycle``, ``Temp``) and
one column per channel named by its filter pair (``465-510``, ``483-533`` …). Every program is
split by its role: the program whose cycle number runs highest is the amplification, a
program with one cycle per well and many acquisitions is a melt. When the first line names a
selected filter, only that channel is read; otherwise each channel column becomes a target
named after the channel. The text export carries no Cp and no sample types.

The **Abs Quant Cp table** (``Include``, ``Color``, ``Pos``, ``Name``, ``Cp``,
``Concentration``, ``Standard``, ``Status``) gives the LightCycler software's Cp per well and
the standards: a ``Standard`` value above zero is a standard of that known concentration.
``Concentration`` is the software's own estimate from its standard curve (an output, not a
known quantity) and is not read; ``Include`` = false is recorded as the vendor's omission (never
applied). A Cp table and a raw-data file of the same plate (``CP1 Ct.txt`` and ``CP1.txt``) are
joined by well into one plate; a Cp table alone is a Cq-only plate.

A raw-data file whose every reading was taken below 45 °C is refused: that is an isothermal
plate read (a growth or binding assay in the LightCycler's layout), not a PCR.
"""

from __future__ import annotations

import re
from collections import defaultdict

from qpilot.io.connectors.base import CaptureError, PlateData, Probe, Sniff, Source
from qpilot.io.connectors.common import LongAssembler, plate_stem, well_position
from qpilot.io.connectors.tables import find_header, match_columns, number, read_grids, table_at

LC_COLUMNS: dict[str, tuple[str, ...]] = {
    "well": ("samplepos", "sample pos", "pos", "position", "well"),
    "sample": ("samplename", "sample name", "name"),
    "program": ("prog", "program", "program no", "programno", "prog no"),
    "segment": ("seg", "segment", "segment no", "segmentno"),
    "cycle": ("cycle", "cycle no", "cycleno", "cycles"),
    "time": ("time", "acq time"),
    "temperature": ("temp", "temperature", "acq temp"),
}
LC_CP_COLUMNS: dict[str, tuple[str, ...]] = {
    "include": ("include",),
    "well": ("pos", "position", "samplepos"),
    "sample": ("name", "sample name", "samplename"),
    "cq": ("cp", "ct", "cq"),
    "standard": ("standard",),
    "concentration": ("concentration",),
    "status": ("status",),
}
_CHANNEL = re.compile(r"^\s*(\d{3})\s*-\s*(\d{3})")
_SELECTED = re.compile(r"Selected Filter:.*?\((\d{3})\s*-\s*(\d{3})\)", re.IGNORECASE)
#: Below this temperature (°C) no reading of a PCR is taken (annealing is ~50-65 °C).
MIN_PCR_READ_C = 45.0
_FALSE = {"false", "no", "0"}


def _channels(headers: list[str]) -> list[tuple[int, str]]:
    out = []
    for index, header in enumerate(headers):
        match = _CHANNEL.match(header)
        if match:
            out.append((index, f"{match.group(1)}-{match.group(2)}"))
    return out


class LightCyclerConnector:
    """LightCycler 480 text exports (raw fluorescence; no Cp, no sample types)."""

    id = "lightcycler480"
    version = "1"
    label = "Roche LightCycler 480 text export"
    suffixes = (".txt",)

    def sniff(self, probe: Probe) -> Sniff | None:
        """A raw-data header (position, cycle, channel columns) or the Cp table's header.

        Raw data: ``SamplePos`` + ``Cycle#`` + channels such as ``465-510``; the Cp table:
        ``Include`` / ``Pos`` / ``Cp`` / ``Standard``.
        """
        if probe.kind != "text":
            return None
        for line in probe.head[:10]:
            cells = line.split("\t")
            found = match_columns(cells, LC_COLUMNS)
            if "well" in found and "cycle" in found and _channels(cells):
                return Sniff(90, "lightcycler480.text")
            found = match_columns(cells, LC_CP_COLUMNS)
            if {"well", "cq"} <= set(found) and {"include", "standard"} & set(found):
                return Sniff(85, "lightcycler480.cp", "cq")
        return None

    def read(self, sources: list[Source]) -> list[PlateData]:
        """One plate per file stem: a raw-data file, a Cp table, or both joined by well."""
        groups: dict[str, list[Source]] = {}
        for source in sources:
            groups.setdefault(plate_stem(source.path.stem).lower(), []).append(source)
        return [_read_group(members) for members in groups.values()]


def _read_group(members: list[Source]) -> PlateData:
    raw = [s for s in members if s.sniff.dialect == "lightcycler480.text"]
    tables = [s for s in members if s.sniff.dialect == "lightcycler480.cp"]
    if len(raw) > 1 or len(tables) > 1:
        names = ", ".join(s.path.name for s in members)
        raise CaptureError(f"{names}: two LightCycler files of one kind for one plate")
    first = (raw or tables)[0]
    assembler = LongAssembler(plate_stem(first.path.stem))
    plate_sources: list[tuple[str, str]] = []
    channels: list[str] = []
    if raw:
        channels = _read_raw(raw[0], assembler)
        plate_sources.append((raw[0].path.name, "plate"))
    if tables:
        _read_cp(tables[0], assembler, channels)
        plate_sources.append((tables[0].path.name, "cq"))
    plate = assembler.plate(value_kind="fluorescence" if raw else "unknown")
    plate.sources = plate_sources
    if raw and not tables:
        plate.notes.append(
            "LightCycler 480 text exports carry no sample types and no Cp; targets are named "
            "after the detection channel."
        )
    else:
        plate.notes.append(
            "The LightCycler 480 Cp table names standards only (by their concentration); "
            "targets are named after the detection channel. Type your other controls in Studio."
        )
    return plate


def _read_cp(source: Source, assembler: LongAssembler, channels: list[str]) -> None:
    """Add the Cp table's names, Cp, standards and omissions to the plate's reactions."""
    grid = read_grids(source.path)[0]
    selected = None
    for row in grid.rows[:3]:
        match = _SELECTED.search(" ".join(row))
        if match:
            selected = f"{match.group(1)}-{match.group(2)}"
    header = find_header(grid.rows, LC_CP_COLUMNS, ("well", "cq"), scan=10)
    if header is None:
        raise CaptureError(f"{source.path.name}: no Pos / Cp header")
    table = table_at(grid.rows, header, LC_CP_COLUMNS, stop_at_blank=False)
    if selected and (selected in channels or not channels):
        target = selected
    elif len(channels) == 1:
        target = channels[0]
    else:
        target = selected or "target"
    dc = grid.decimal_comma
    seen: set[tuple[int, int]] = set()
    for row in table.rows:
        position = well_position(table.get(row, "well"))
        if position is None:
            continue
        if position in seen:
            raise CaptureError(f"{source.path.name}: well {table.get(row, 'well')} is listed twice")
        seen.add(position)
        standard = number(table.get(row, "standard"), decimal_comma=dc)
        reaction = assembler.reaction(
            *position,
            target,
            sample=table.get(row, "sample"),
            dye=target if _CHANNEL.match(target) else "",
            vendor_type="Standard" if standard is not None and standard > 0 else "",
        )
        if standard is not None and standard > 0:
            reaction.quantity = standard
        cq = number(table.get(row, "cq"), decimal_comma=dc)
        if cq is not None and cq > 0:
            reaction.cq = cq
        if table.get(row, "include").strip().lower() in _FALSE:
            reaction.omitted = True


def _read_raw(source: Source, assembler: LongAssembler) -> list[str]:
    """Add a raw-data file's curves to the plate; the channels read, in order."""
    grid = read_grids(source.path)[0]
    selected = None
    for row in grid.rows[:3]:
        match = _SELECTED.search(" ".join(row))
        if match:
            selected = f"{match.group(1)}-{match.group(2)}"
    header = find_header(grid.rows, LC_COLUMNS, ("well", "cycle"), scan=10)
    if header is None:
        raise CaptureError(f"{source.path.name}: no position / cycle header")
    table = table_at(grid.rows, header, LC_COLUMNS, stop_at_blank=False)
    channels = _channels(table.headers)
    if selected is not None:
        channels = [c for c in channels if c[1] == selected] or channels
    if not channels:
        raise CaptureError(f"{source.path.name}: no channel column (such as 465-510)")
    dc = grid.decimal_comma
    by_program: dict[str, list[list[str]]] = defaultdict(list)
    for row in table.rows:
        by_program[table.get(row, "program") or "1"].append(row)

    def max_cycle(rows: list[list[str]]) -> float:
        return max((number(table.get(r, "cycle"), decimal_comma=dc) or 0 for r in rows), default=0)

    amp_program = max(by_program, key=lambda p: max_cycle(by_program[p]))
    if max_cycle(by_program[amp_program]) < 5:
        raise CaptureError(f"{source.path.name}: no amplification program found")
    temperatures = [
        t
        for r in by_program[amp_program]
        if (t := number(table.get(r, "temperature"), decimal_comma=dc)) is not None
    ]
    if temperatures and max(temperatures) < MIN_PCR_READ_C:
        raise CaptureError(
            f"{source.path.name}: every reading was taken at about "
            f"{sorted(temperatures)[len(temperatures) // 2]:.0f} °C, with no heating step, so "
            "this is not a PCR run (it looks like an isothermal plate read); qPilot reads "
            "qPCR runs only"
        )
    for program, rows in by_program.items():
        if program == amp_program:
            melt = False
        else:
            per_well: dict[str, int] = defaultdict(int)
            for row in rows:
                per_well[table.get(row, "well")] += 1
            if not per_well or min(per_well.values()) < 10 or max_cycle(rows) > 1:
                continue
            melt = True
        for row in rows:
            position = well_position(table.get(row, "well"))
            if position is None:
                continue
            x = number(table.get(row, "temperature" if melt else "cycle"), decimal_comma=dc)
            for index, channel in channels:
                assembler.reaction(*position, channel, sample=table.get(row, "sample"), dye=channel)
                y = number(row[index], decimal_comma=dc) if index < len(row) else None
                if x is not None and y is not None:
                    if melt and x in assembler.parts[(*position, channel)].melt:
                        continue  # repeated temperature reading in a melt: keep the first
                    assembler.point(*position, channel, x, y, melt=melt)
    return [channel for _, channel in channels]


CONNECTOR = LightCyclerConnector()

__all__ = ["CONNECTOR", "LightCyclerConnector"]
