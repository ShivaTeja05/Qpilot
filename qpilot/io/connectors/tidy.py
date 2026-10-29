"""Two vendor-neutral formats: RDES (wide) and qPilot's tidy table (long), for any instrument.

**RDES** (Real-time PCR Data Essential Spreadsheet, the MIQE 2.0 companion to RDML): one row
per well and target with ``Well``, ``Sample``, ``Sample Type``, ``Target``, ``Target Type``,
``Dye`` and ``Cq`` (or ``Tm``), then one column per cycle (or temperature). The same reader
takes any *wide* table whose header has a well column and at least five numeric column names.

**Tidy table**: one row per well, target and cycle with columns found by name: ``well``,
``cycle`` and a signal (``fluorescence``/``RFU``/``Rn``/``Delta Rn``), optionally ``target``,
``sample``, ``sample type`` (or ``task``/``content``), ``dye``, ``plate``, ``Cq`` and
``quantity``. Without a ``cycle`` column but with ``Cq`` it is a **Cq table** (no curves):
the door to Cq-only mode. A Cq table without a well column gets positions in row order
(``A1``, ``A2`` ...), and the import says so.

A **person's own Cq table** (typed in Excel, one row per well: ``Sample Name``, ``Gene Name``,
``Condition``, ``Gene Type``, ``Cq``) is read too: the header synonyms are in
:data:`~qpilot.io.connectors.common.COLUMNS` (``Ct``, ``Cp``, ``Detector`` ...), a Cq written as
text is a number, ``Undetermined``/``N/A``/``No Ct`` is no Cq, and a mean (``Cq Mean``) is never
read as a well's Cq. A gene type / role column (``Reference``, ``Housekeeping`` -> ``ref``;
``Target`` -> ``toi``) becomes each target's declared type, so Design proposes the reference
genes the table names. A condition, group or animal column makes the table its own sample sheet
too (``qpilot.web.intake``); a table naming those but no target is only a sample sheet. When the
sheets of a workbook repeat one sample and target (two experiments), only the first is read.
"""

from __future__ import annotations

from qpilot.io.connectors.base import (
    CaptureError,
    Curve,
    PlateData,
    Probe,
    Reaction,
    Sniff,
    Source,
)
from qpilot.io.connectors.builder import well_name
from qpilot.io.connectors.common import (
    COLUMNS,
    LongAssembler,
    plate_stem,
    roles_not_types,
    target_role,
    well_position,
)
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

_RDES_HEAD = ("well", "sample", "sampletype", "target", "targettype", "dye")
_SIGNALS = ("fluorescence", "rn", "drn")  # preference order: the least processed first
_KIND = {"fluorescence": "fluorescence", "rn": "Rn", "drn": "dRn"}


def _probe_rows(probe: Probe) -> list[list[str]]:
    """The probe's first table-like rows (text split by the sniffed delimiter, or sheet 1)."""
    if probe.kind == "xlsx":
        return next(iter(probe.sheets.values()), [])
    if probe.kind != "text":
        return []
    import csv

    from qpilot.io.connectors.tables import sniff_delimiter

    lines = probe.head[:200]
    delimiter = sniff_delimiter(lines)
    return [next(csv.reader([line], delimiter=delimiter), []) for line in lines]


#: Sample-sheet fields (``qpilot.io.sheets.HEADER_SYNONYMS``) a Cq table never has.
_DESIGN_FIELDS = frozenset({"group", "bio_unit", "bio_rep"})


def _design_columns(row: list[str]) -> bool:
    """Whether a header row names a sample sheet's design column (group, animal, bio rep)."""
    from qpilot.io.sheets import header_field

    return any(header_field(cell) in _DESIGN_FIELDS for cell in row if cell)


def _numeric_header(cell: str) -> bool:
    return number(cell) is not None


# ---------------------------------------------------------------------------------------------
# RDES / wide
# ---------------------------------------------------------------------------------------------


class RdesConnector:
    """RDES amplification / melting tables, and any wide well-by-cycle table."""

    id = "rdes"
    version = "1"
    label = "RDES or wide well-by-cycle table"
    suffixes = (".tsv", ".txt", ".csv", ".xlsx")

    def sniff(self, probe: Probe) -> Sniff | None:
        """RDES by its seven fixed columns; a wide table by a well column + numeric headers."""
        for row in _probe_rows(probe)[:30]:
            squashed = [squash(c) for c in row]
            if tuple(squashed[:6]) == _RDES_HEAD and len(squashed) > 6:
                melt = squashed[6] == "tm"
                return Sniff(95, "rdes.melt" if melt else "rdes.amp", "melt" if melt else "plate")
            found = match_columns(row, COLUMNS)
            numeric = sum(1 for c in row if _numeric_header(c))
            if "well" in found and numeric >= 5 and "cycle" not in found:
                return Sniff(45, "wide.amp")
        return None

    def read(self, sources: list[Source]) -> list[PlateData]:
        """One plate per amplification file; melt files join the plate of the same stem."""
        plates: dict[str, PlateData] = {}
        for source in sources:
            for grid in read_grids(source.path):
                plate = _read_wide(grid, source)
                if plate is None:
                    continue
                key = plate.run_id.lower()
                if key in plates:
                    _merge(plates[key], plate)
                else:
                    plates[key] = plate
        return list(plates.values())


def _read_wide(grid: Grid, source: Source) -> PlateData | None:
    header = find_header(grid.rows, COLUMNS, ("well",))
    if header is None:
        return None
    head = grid.rows[header]
    columns = match_columns(head, COLUMNS)
    xs = [(i, number(c)) for i, c in enumerate(head) if i not in columns.values()]
    points = [(i, x) for i, x in xs if x is not None]
    if len(points) < 2:
        return None
    melt = any(squash(c) == "tm" for c in head[:8]) or source.sniff.dialect == "rdes.melt"
    table = table_at(grid.rows, header, COLUMNS)
    run_id = plate_stem(source.path.stem)
    plate = PlateData(run_id=run_id, value_kind="fluorescence")
    plate.sources.append((source.path.name, "melt" if melt else "amplification"))
    for row in table.rows:
        position = well_position(table.get(row, "well"))
        if position is None:
            continue
        values = [(x, number(row[i], decimal_comma=grid.decimal_comma)) for i, x in points
                  if i < len(row)]  # fmt: skip
        curve_points = [(x, y) for x, y in values if y is not None]
        target = table.get(row, "target") or table.get(row, "dye")
        vendor_type = table.get(row, "type")
        mapped, known = map_vendor_type(vendor_type)
        curve = Curve(tuple(x for x, _ in curve_points), tuple(y for _, y in curve_points))
        cq = None if melt else number(table.get(row, "cq"), decimal_comma=grid.decimal_comma)
        plate.reactions.append(
            Reaction(
                well=well_name(*position),
                row=position[0],
                column=position[1],
                sample=table.get(row, "sample"),
                target=target,
                dye=table.get(row, "dye"),
                sample_type=mapped,
                vendor_type=vendor_type,
                type_mapped=known,
                cq=cq if cq is not None and cq > 0 else None,
                amp=None if melt or not curve_points else curve,
                melt=curve if melt and curve_points else None,
            )
        )
    return plate


def _merge(into: PlateData, other: PlateData) -> None:
    """Join a melt plate to its amplification plate (or the other way) by well and target."""
    index = {(r.row, r.column, r.target): r for r in into.reactions}
    for reaction in other.reactions:
        existing = index.get((reaction.row, reaction.column, reaction.target))
        if existing is None:
            into.reactions.append(reaction)
            continue
        if reaction.melt is not None and existing.melt is None:
            existing.melt = reaction.melt
        elif reaction.amp is not None and existing.amp is None:
            existing.amp = reaction.amp
            existing.cq = existing.cq if existing.cq is not None else reaction.cq
        else:
            raise CaptureError(
                f"plate {into.run_id} well {reaction.well}: the same curve is given in two files"
            )
    into.sources.extend(other.sources)


# ---------------------------------------------------------------------------------------------
# Tidy long tables and Cq tables
# ---------------------------------------------------------------------------------------------


class TidyConnector:
    """A long table (well, cycle, fluorescence ...) or a Cq table (sample, target, Cq ...)."""

    id = "tidy"
    version = "1"
    label = "Tidy table (long amplification data or a Cq table)"
    suffixes = (".csv", ".tsv", ".txt", ".xlsx")

    def sniff(self, probe: Probe) -> Sniff | None:
        """A header naming a well, a cycle and a signal; or a target / sample and a Cq.

        A table that also names a group, an animal or a biological replicate is a Cq table
        only when it names a sample, a target and a Cq per row (a person's own Cq table, which
        is then its own sample sheet too); without a target it is a qPilot sample sheet
        (``qpilot.io.sheets``) and is not claimed.
        """
        for row in _probe_rows(probe)[:30]:
            found = match_columns(row, COLUMNS)
            if "well" in found and "cycle" in found and any(s in found for s in _SIGNALS):
                return Sniff(50, "tidy.long")
            if "cq" in found and ("target" in found or "sample" in found) and "cycle" not in found:
                if _design_columns(row):
                    if "target" in found and "sample" in found:
                        return Sniff(30, "tidy.cq.design", "cq")
                    return None
                return Sniff(30, "tidy.cq", "cq")
        return None

    def read(self, sources: list[Source]) -> list[PlateData]:
        """Every plate in every file (a ``plate`` column splits one file into plates).

        When a later sheet of a workbook repeats a sample and target of an earlier one, it is
        another experiment of the same samples' names: it is left out, and a note says so.
        """
        plates: list[PlateData] = []
        for source in sources:
            seen: set[tuple[str, str]] = set()
            left_out = 0
            for grid in read_grids(source.path):
                found = _read_long(grid, source)
                pairs = {(r.sample, r.target) for p in found for r in p.reactions if r.sample}
                if seen & pairs:
                    left_out += 1
                    continue
                seen |= pairs
                plates.extend(found)
            if left_out and plates:
                plates[0].notes.append(
                    f"{left_out} more sheet{'s repeat' if left_out > 1 else ' repeats'} the "
                    "same sample and gene names (another experiment): qPilot read the first Cq "
                    "table of the workbook only. Save each experiment as its own file to open it."
                )
        return plates


def _read_long(grid: Grid, source: Source) -> list[PlateData]:
    header = find_header(grid.rows, COLUMNS, ("cycle",))
    cq_only = header is None
    if cq_only:
        header = find_header(grid.rows, COLUMNS, ("cq",))
        if header is None:
            return []
    table = table_at(grid.rows, header, COLUMNS, stop_at_blank=False)
    signal = next((s for s in _SIGNALS if table.has(s)), None)
    if not cq_only and signal is None:
        raise CaptureError(f"{source.path.name}: a cycle column but no fluorescence column")
    stem = plate_stem(source.path.stem) + (f" {grid.name}" if grid.name else "")
    assemblers: dict[str, LongAssembler] = {}
    positions_assigned = 0
    dc = grid.decimal_comma
    # a "Type"/"Role" column of Reference / Target words is the targets' role, not sample types
    type_is_role = table.has("type") and roles_not_types(table.get(r, "type") for r in table.rows)
    for row in table.rows:
        plate_name = table.get(row, "plate") or stem
        assembler = assemblers.setdefault(plate_name, LongAssembler(plate_name))
        position = well_position(table.get(row, "well"), table.get(row, "well_index"))
        if position is None:
            if table.has("well") or table.has("well_index"):
                continue  # a footer or a blank well
            n = len(assembler.parts)
            position = (n // 12 + 1, n % 12 + 1)
            positions_assigned += 1
        target = table.get(row, "target") or table.get(row, "dye") or "target"
        reaction = assembler.reaction(
            *position,
            target,
            sample=table.get(row, "sample"),
            dye=table.get(row, "dye"),
            vendor_type="" if type_is_role else table.get(row, "type"),
        )
        role = target_role(table.get(row, "type" if type_is_role else "target_type"))
        if role and not reaction.target_type:
            reaction.target_type = role
        cq = number(table.get(row, "cq"), decimal_comma=dc)
        if cq is not None and cq > 0 and reaction.cq is None:
            reaction.cq = cq
        quantity = number(table.get(row, "quantity"), decimal_comma=dc)
        if quantity is not None and reaction.quantity is None:
            reaction.quantity = quantity
        if table.get(row, "omit").lower() in ("true", "yes", "1", "x"):
            reaction.omitted = True
        if not cq_only:
            x = number(table.get(row, "cycle"), decimal_comma=dc)
            y = number(table.get(row, signal or ""), decimal_comma=dc)
            if x is not None and y is not None:
                assembler.point(*position, target, x, y)
    kind = "unknown" if cq_only else _KIND[signal or "fluorescence"]
    plates = []
    for assembler in assemblers.values():
        plate = assembler.plate(value_kind=kind)
        plate.sources.append((source.path.name, "cq" if cq_only else "amplification"))
        if positions_assigned:
            plate.notes.append(
                "The table has no well column; qPilot numbered its rows as wells A1, A2 ... "
                "in the order they appear."
            )
        plates.append(plate)
    return plates


RDES = RdesConnector()
TIDY = TidyConnector()

__all__ = ["RDES", "TIDY", "RdesConnector", "TidyConnector"]
