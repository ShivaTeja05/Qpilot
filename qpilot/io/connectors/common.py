"""Pieces connectors share: column vocabulary, plate names and files, long-table assembly.

A *long* table has one row per well, target and cycle (or per well and target for a Cq table):
QuantStudio's ``[Amplification Data]``, the LightCycler text export and qPilot's generic tidy
CSV all have this shape. :class:`LongAssembler` collects such rows into reactions, checking
that a well's cycles are not given twice with different values.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from qpilot.io.connectors.base import CaptureError, CaptureMeta, Curve, PlateData, Reaction
from qpilot.io.connectors.builder import clean_id, parse_well, well_name
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
               "detector name", "primer", "amplicon", "target id", "gene symbol", "target gene",
               "primer pair", "primer set", "probe", "assay id"),
    "sample": ("sample", "sample name", "sample id", "name", "sample label", "biological sample",
               "specimen", "specimen id", "sample code"),
    "target_type": ("gene type", "target type", "target role", "gene role", "assay type",
                    "assay role", "gene category", "reference gene", "housekeeping",
                    "is reference", "reference or target"),
    "type": ("sample type", "type", "task", "content", "role", "well type", "well role"),
    "dye": ("dye", "reporter", "fluor", "fluorophore", "channel", "reporter dye", "filter"),
    "plate": ("plate", "plate id", "plate name", "run", "run id", "run name", "plate number"),
    "cq": ("cq", "ct", "cp", "cq value", "ct value", "cp value", "crt", "cq (Δrn)", "c q",
           "threshold cycle", "quantification cycle", "crossing point", "ct (drn)", "cq (rfu)"),
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


#: A target-role cell (a gene type / role column) -> ``ref`` or ``toi``; other words say nothing.
TARGET_ROLES: dict[str, str] = {
    **dict.fromkeys(
        ("reference", "ref", "reference gene", "refgene", "housekeeping", "housekeeping gene",
         "hk", "hkg", "endogenous control", "endogenous", "normaliser", "normalizer",
         "normalization", "normalisation", "control gene", "internal control", "yes", "y",
         "true", "x", "1"),
        "ref",
    ),
    **dict.fromkeys(
        ("target", "target gene", "gene of interest", "goi", "toi", "target of interest",
         "test", "test gene", "no", "n", "false", "0"),
        "toi",
    ),
}  # fmt: skip
_ROLE_KEYS = {re.sub(r"[^0-9a-z]+", "", key): role for key, role in TARGET_ROLES.items()}
#: Words a sample-type column holds that are target roles only (a "Type" column of a Cq table).
_ROLE_ONLY = {"reference", "referencegene", "housekeeping", "housekeepinggene", "target",
              "targetgene", "geneofinterest", "goi", "toi", "endogenouscontrol", "normaliser",
              "normalizer"}  # fmt: skip


def target_role(text: str) -> str:
    """``ref``, ``toi`` or ``""`` for a cell of a gene type / role column."""
    return _ROLE_KEYS.get(re.sub(r"[^0-9a-z]+", "", text.strip().lower()), "")


def roles_not_types(values: Iterable[str]) -> bool:
    """Whether a "Type"/"Role" column holds target roles (Reference/Target), not sample types."""
    words = {re.sub(r"[^0-9a-z]+", "", v.strip().lower()) for v in values if v.strip()}
    return bool(words) and words <= _ROLE_ONLY


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


def plate_sources(meta: CaptureMeta) -> dict[str, list[str]]:
    """Each plate's input files: run id -> the names of the files it was read from.

    A capture names them per plate (:attr:`PlateMeta.sources`). One recorded before it did is
    read as the connectors group files: one plate was read from every file; with several, a
    file belongs to the plate its stem names (:func:`plate_stem`), and one naming none is left out.
    """
    names = [s.name for s in meta.sources]
    if any(p.sources for p in meta.plates):
        return {p.run_id: [n for n in p.sources if n in names] for p in meta.plates}
    if len(meta.plates) == 1:
        return {meta.plates[0].run_id: names}
    out: dict[str, list[str]] = {p.run_id: [] for p in meta.plates}
    plates = {run_id.lower(): run_id for run_id in out}
    for name in names:
        run_id = plates.get(clean_id(plate_stem(Path(name).stem), "").lower())
        if run_id is not None:
            out[run_id].append(name)
    return out


def well_position(label: str, index: str = "", columns: int = 12) -> tuple[int, int] | None:
    """(row, column) of a well from its label (``A1``), else from its index (a label or a number).

    Raises:
        CaptureError: An index below 1.
    """
    if label:
        found = parse_well(label)
        if found is not None:
            return found
    if index:
        found = parse_well(index)  # StepOne writes "A1" in its "Well" column
        if found is not None:
            return found
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


__all__ = [
    "COLUMNS",
    "TARGET_ROLES",
    "LongAssembler",
    "header_pairs",
    "plate_sources",
    "plate_stem",
    "roles_not_types",
    "target_role",
    "well_position",
]
