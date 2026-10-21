"""Roche LightCycler 480 text export ("Export ▸ Text", raw fluorescence per acquisition).

The export is one tab-separated table, optionally after an ``Experiment: … Selected Filter: …``
line: one row per well and acquisition with columns found by name (``SamplePos``/``Pos``,
``SampleName``/``Name``, ``Prog``/``Program``, ``Seg``/``Segment``, ``Cycle``, ``Temp``) and
one column per channel named by its filter pair (``465-510``, ``483-533`` …). Every program is
split by its role: the program whose cycle number runs highest is the amplification, a
program with one cycle per well and many acquisitions is a melt. When the first line names a
selected filter, only that channel is read; otherwise each channel column becomes a target
named after the channel. The text export carries no Cp and no sample types.
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
_CHANNEL = re.compile(r"^\s*(\d{3})\s*-\s*(\d{3})")
_SELECTED = re.compile(r"Selected Filter:.*?\((\d{3})\s*-\s*(\d{3})\)", re.IGNORECASE)


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
        """A position + cycle header with filter-pair channel columns (``465-510``)."""
        if probe.kind != "text":
            return None
        for line in probe.head[:10]:
            cells = line.split("\t")
            found = match_columns(cells, LC_COLUMNS)
            if "well" in found and "cycle" in found and _channels(cells):
                return Sniff(90, "lightcycler480.text")
        return None

    def read(self, sources: list[Source]) -> list[PlateData]:
        """One plate per file."""
        return [_read(source) for source in sources]


def _read(source: Source) -> PlateData:
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
    assembler = LongAssembler(plate_stem(source.path.stem))
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
    plate = assembler.plate(value_kind="fluorescence")
    plate.sources.append((source.path.name, "plate"))
    plate.notes.append(
        "LightCycler 480 text exports carry no sample types and no Cp; targets are named "
        "after the detection channel."
    )
    return plate


CONNECTOR = LightCyclerConnector()

__all__ = ["CONNECTOR", "LightCyclerConnector"]
