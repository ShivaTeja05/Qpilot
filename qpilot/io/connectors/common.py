"""Pieces several connectors share: column vocabulary, plate names, and long-table assembly.

A *long* table has one row per well, target and cycle (or per well and target for a Cq table):
QuantStudio's ``[Amplification Data]``, the LightCycler text export and qPilot's generic tidy
CSV all have this shape. :class:`LongAssembler` collects such rows into reactions, checking
that a well's cycles are not given twice with different values.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from qpilot.io.connectors.base import CaptureError, Curve, PlateData, Reaction
from qpilot.io.connectors.builder import parse_well, well_name
from qpilot.io.connectors.sample_types import map_vendor_type

#: Canonical column -> accepted spellings (compared after ``tables.squash``).
COLUMNS: dict[str, tuple[str, ...]] = {
    "well": ("well", "well position", "wellposition", "well id", "pos", "position", "samplepos",
             "sample pos", "well name", "wells"),
    "well_index": ("well number", "well no", "well index", "well #"),
    "cycle": ("cycle", "cycles", "cycle number", "cycle no", "cycle #", "cyc"),
    "fluorescence": ("fluorescence", "fluorescence value", "raw fluorescence", "rfu", "raw rfu",
                     "signal", "intensity", "raw", "value", "fluorescence (rfu)"),
    "rn": ("rn", "normalized reporter", "normalised reporter"),
    "drn": ("delta rn", "deltarn", "drn", "Δrn", "dRn", "delta rn (Δrn)"),
    "target": ("target", "target name", "gene", "gene name", "assay", "assay name", "detector",
               "detector name", "primer", "amplicon", "target id"),
    "sample": ("sample", "sample name", "sample id", "name", "sample label", "biological sample"),
    "type": ("sample type", "type", "task", "content", "role", "well type", "well role"),
    "dye": ("dye", "reporter", "fluor", "fluorophore", "channel", "reporter dye", "filter"),
    "plate": ("plate", "plate id", "plate name", "run", "run id", "run name", "plate number"),
    "cq": ("cq", "ct", "cp", "cq value", "ct value", "cp value", "crt", "cq (Δrn)", "c q"),
    "quantity": ("quantity", "starting quantity", "starting quantity (sq)", "sq", "copies",
                 "copy number", "concentration", "conc", "std quantity", "given conc"),
    "temperature": ("temperature", "temp", "tm", "melt temperature", "temperature (°c)"),
    "omit": ("omit", "omitted", "excluded", "exclude"),
}  # fmt: skip

_STEM_TRAILERS = re.compile(
    r"(?i)[\s_-]*(-\s*)?(quantification\s+amplification\s+results|amplification\s+results|"
    r"quantification\s+cq\s+results|quantification\s+summary|quantification\s+results|"
    r"melt\s+curve\s+(rfu|derivative|peak|plate\s+view)\s+results|amplification\s+data|"
    r"run\s+information|end\s+point\s+results|standard\s+curve\s+results|"
    r"quantification\s+plate\s+view\s+results|allelic\s+discrimination\s+results|"
    r"gene\s+expression\s+results(\s+-\s+\w+(\s+\w+)?)?|results|"
    r"sample\s+setup|melt\s+curve\s+raw\s+data|multicomponent\s+data|raw\s+data|amp|melt|"
    r"amplification|melting|data|export|cq|ct)(_[A-Za-z0-9 ()-]{1,24})?(_\d+)?$"
)


def plate_stem(file_stem: str) -> str:
    """A plate's name from a file stem: the vendor's export suffix removed.

    ``run1 -  Quantification Amplification Results_SYBR`` -> ``run1``;
    ``2019-05-02 plate3_data`` -> ``2019-05-02 plate3``.
    """
    stem = file_stem.strip()
    for _ in range(3):
        trimmed = _STEM_TRAILERS.sub("", stem).strip(" -_")
        if trimmed == stem or not trimmed:
            break
        stem = trimmed
    return stem or file_stem


def well_position(label: str, index: str = "", columns: int = 12) -> tuple[int, int] | None:
    """(row, column) of a well from its label (``A1``), else from a 1-based index on a plate.

    Raises:
        CaptureError: An index below 1.
    """
    if label:
        found = parse_well(label)
        if found is not None:
            return found
    if index:
        try:
            position = int(float(index))
        except ValueError:
            return None
        if position < 1:
            raise CaptureError("a well number below 1")
        return (position - 1) // columns + 1, (position - 1) % columns + 1
    return None


@dataclass
class _Partial:
    reaction: Reaction
    amp: dict[float, float] = field(default_factory=dict)
    melt: dict[float, float] = field(default_factory=dict)


class LongAssembler:
    """Collects long-table rows (one per well, target and cycle) into reactions."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.parts: dict[tuple[int, int, str], _Partial] = {}
        self.duplicates = 0

    def reaction(
        self,
        row: int,
        column: int,
        target: str,
        *,
        sample: str = "",
        dye: str = "",
        vendor_type: str = "",
    ) -> Reaction:
        """The reaction for this well and target (created on first sight)."""
        key = (row, column, target)
        part = self.parts.get(key)
        if part is None:
            mapped, known = map_vendor_type(vendor_type)
            part = _Partial(
                Reaction(
                    well=well_name(row, column),
                    row=row,
                    column=column,
                    sample=sample,
                    target=target,
                    dye=dye,
                    sample_type=mapped,
                    vendor_type=vendor_type,
                    type_mapped=known,
                )
            )
            self.parts[key] = part
        else:
            r = part.reaction
            if sample and not r.sample:
                r.sample = sample
            if dye and not r.dye:
                r.dye = dye
            if vendor_type and not r.vendor_type:
                r.sample_type, r.type_mapped = map_vendor_type(vendor_type)
                r.vendor_type = vendor_type
        return part.reaction

    def point(self, row: int, column: int, target: str, x: float, y: float, *, melt: bool = False):
        """Add one (cycle or temperature, fluorescence) point to a reaction."""
        part = self.parts[(row, column, target)]
        points = part.melt if melt else part.amp
        if x in points and points[x] != y:
            self.duplicates += 1
            raise CaptureError(
                f"plate {self.run_id} well {well_name(row, column)}: cycle or temperature "
                f"{x:g} is given twice with different values"
            )
        points[x] = y

    def plate(self, **kwargs) -> PlateData:
        """The collected reactions as a plate (``kwargs`` go to :class:`PlateData`)."""
        plate = PlateData(run_id=self.run_id, **kwargs)
        for part in self.parts.values():
            if part.amp:
                xs = sorted(part.amp)
                part.reaction.amp = Curve(tuple(xs), tuple(part.amp[x] for x in xs))
            if part.melt:
                xs = sorted(part.melt)
                part.reaction.melt = Curve(tuple(xs), tuple(part.melt[x] for x in xs))
            plate.reactions.append(part.reaction)
        return plate


def header_pairs(lines: Iterable[str]) -> list[tuple[str, str]]:
    """``(key, value)`` pairs from ``* Key = Value`` or ``Key<TAB>Value`` header lines."""
    pairs = []
    for line in lines:
        text = line.strip().lstrip("*").strip()
        if "=" in text:
            key, _, value = text.partition("=")
        elif "\t" in text:
            key, _, value = text.partition("\t")
        elif ":" in text:
            key, _, value = text.partition(":")
        else:
            continue
        key, value = key.strip(), value.strip().strip("\t").strip()
        if key and len(key) <= 80:
            pairs.append((key, value))
    return pairs


__all__ = ["COLUMNS", "LongAssembler", "header_pairs", "plate_stem", "well_position"]
