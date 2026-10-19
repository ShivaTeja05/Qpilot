"""The shapes every connector shares: what a reader finds in a file, and what qPilot records.

A connector reads one vendor export (or a set of files that together describe plates) into
:class:`PlateData` objects, one per plate, in a vendor-neutral form: wells, the sample and
target in each, the vendor's sample type, the vendor's Cq and the fluorescence per cycle (and
per temperature for melts). :mod:`qpilot.io.connectors.builder` turns those plates into an RDML
document, so the engine never sees a vendor format.

What was found, where it came from and what was odd about it goes into :class:`CaptureMeta`
(JSON, schema ``qpilot.capture/1``). Every piece of free text from a file (sample and target
names, header values, comments, task names qPilot does not know) is in its ``quarantine`` and
cited elsewhere only by ``text_id``; warning messages are qPilot's own words, never file text.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from qpilot.schemas_studio import QuarantineEntry, text_id_for

#: What kind of signal a reader put into the amplification curves.
ValueKind = Literal["RFU", "Rn", "dRn", "fluorescence", "unknown"]

#: RDML sample types (``sampleTypeType`` in the RDML 1.4 schema).
RDML_SAMPLE_TYPES = ("unkn", "ntc", "nac", "std", "ntp", "nrt", "pos", "opt")

CAPTURE_SCHEMA = "qpilot.capture/1"


class CaptureError(ValueError):
    """The input cannot be read safely or unambiguously; the message is plain English.

    Messages never quote file content (only file names the person chose and qPilot's words).
    """


# ---------------------------------------------------------------------------------------------
# What a reader finds
# ---------------------------------------------------------------------------------------------


@dataclass
class Curve:
    """One fluorescence trace: x (cycle or temperature) and y (fluorescence), same length."""

    x: tuple[float, ...]
    y: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.x) != len(self.y):
            raise CaptureError("a curve has a different number of x and y values")


@dataclass
class Reaction:
    """One target measured in one well (a multiplex well has one reaction per target).

    Attributes:
        well: The well label as qPilot names it (``A1``; ``AA1`` from row 27).
        row: 1-based row.
        column: 1-based column.
        sample: The sample name exactly as in the file (``""`` when the file has none).
        target: The target name exactly as in the file (or the dye when the file names none).
        dye: The dye / fluorophore / channel (``""`` when unknown).
        sample_type: RDML sample type mapped from the vendor's task (``unkn`` by default).
        vendor_type: The vendor's task / content text (``""`` when none).
        type_mapped: Whether ``vendor_type`` was recognised (``False`` = treated as ``unkn``).
        cq: The vendor's Cq (``None`` when none or undetermined).
        quantity: A standard's known quantity (``None`` when none).
        omitted: The vendor software marked the well omitted (recorded, never applied).
        amp: Fluorescence per cycle, or ``None``.
        melt: Fluorescence per temperature, or ``None``.
    """

    well: str
    row: int
    column: int
    sample: str = ""
    target: str = ""
    dye: str = ""
    sample_type: str = "unkn"
    vendor_type: str = ""
    type_mapped: bool = True
    cq: float | None = None
    quantity: float | None = None
    omitted: bool = False
    amp: Curve | None = None
    melt: Curve | None = None


@dataclass
class PlateData:
    """One plate (an RDML run) as a reader found it.

    Attributes:
        run_id: The plate's name (cleaned file stem, at most 64 characters).
        reactions: Every reaction, in any order (the builder sorts them).
        rows: Plate rows (``0`` = infer from the wells).
        columns: Plate columns (``0`` = infer from the wells).
        value_kind: Which signal went into the amplification curves.
        header: ``(canonical key, value)`` pairs from the file's header block; values are file
            text (quarantined by the registry).
        sources: ``(file name, role)`` of each file that contributed.
        software: The vendor software named in the file, as file text (``""`` when none).
        notes: qPilot's own remarks about this plate (never file text).
    """

    run_id: str
    reactions: list[Reaction] = field(default_factory=list)
    rows: int = 0
    columns: int = 0
    value_kind: ValueKind = "unknown"
    header: list[tuple[str, str]] = field(default_factory=list)
    sources: list[tuple[str, str]] = field(default_factory=list)
    software: str = ""
    notes: list[str] = field(default_factory=list)


def finite(value: float | None) -> float | None:
    """``value`` if it is a finite number, else ``None``."""
    if value is None or not math.isfinite(value):
        return None
    return float(value)


# ---------------------------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------------------------


@dataclass
class Probe:
    """The first look at a file, made once by the registry and shown to every connector.

    Attributes:
        path: The file.
        suffix: Lower-case suffix (``.csv``).
        kind: ``text``, ``xlsx``, ``zip`` (a zip that is not a workbook), ``xls`` or ``binary``.
        head: The first lines of a text file (decoded, at most 256 KB), else ``[]``.
        sheets: For a workbook: sheet title -> its first rows as text cells.
    """

    path: Path
    suffix: str
    kind: str
    head: list[str] = field(default_factory=list)
    sheets: dict[str, list[list[str]]] = field(default_factory=dict)


@dataclass(frozen=True)
class Sniff:
    """A connector's answer to a probe: how sure it is (1-100) and which dialect it sees."""

    score: int
    dialect: str
    role: str = "plate"  # amplification | cq | melt | setup | plate (everything in one file)


@dataclass(frozen=True)
class Detection:
    """One connector that recognised a file."""

    connector_id: str
    score: int
    dialect: str
    role: str


@dataclass
class Source:
    """A file a connector reads, with what the probe found."""

    path: Path
    probe: Probe
    sniff: Sniff


class Connector(Protocol):
    """A reader for one family of files (see ``qpilot/io/connectors/__init__.py``)."""

    id: str
    version: str
    label: str
    suffixes: tuple[str, ...]

    def sniff(self, probe: Probe) -> Sniff | None:
        """Whether this connector reads the file, from its content (not only its suffix)."""
        ...

    def read(self, sources: list[Source]) -> list[PlateData]:
        """Read the files (one plate's set, or several plates) into plates."""
        ...


# ---------------------------------------------------------------------------------------------
# What qPilot records (CaptureMeta, JSON)
# ---------------------------------------------------------------------------------------------


class ConnectorInfo(BaseModel):
    """Which connector read the input."""

    id: str
    version: str
    label: str


class SourceInfo(BaseModel):
    """One input file: its name (as the person chose it), hash, size and role."""

    name: str
    sha256: str
    bytes: int
    role: str


class Layers(BaseModel):
    """Which kinds of data the input carries."""

    amplification: bool = False
    melt: bool = False
    cq: bool = False
    sample_types: bool = False
    targets: bool = False
    quantities: bool = False


class VendorType(BaseModel):
    """How one vendor task / content name was mapped (``vendor`` is a known token or a text_id)."""

    vendor: str
    mapped: str
    n_wells: int
    unmapped: bool = False


class PlateMeta(BaseModel):
    """What was captured for one plate."""

    run_id: str
    rows: int
    columns: int
    n_wells: int
    n_reactions: int
    n_cycles: int
    targets: list[str]
    dyes: list[str]
    sample_types: dict[str, int]
    vendor_types: list[VendorType] = []
    n_with_vendor_cq: int = 0
    n_with_amplification: int = 0
    n_with_melt: int = 0
    vendor_omitted: list[str] = []
    value_kind: str = "unknown"


class HeaderItem(BaseModel):
    """One header line of a vendor file: qPilot's key for it and the value's text_id."""

    key: str
    text_id: str


class CaptureWarning(BaseModel):
    """Something odd about the input, in qPilot's words (never file text)."""

    code: str
    message: str


class CaptureMeta(BaseModel):
    """Everything qPilot records about an import (``<rdml>.capture.json``)."""

    schema_: str = Field(default=CAPTURE_SCHEMA, alias="schema")
    connector: ConnectorInfo
    dialect: str
    sources: list[SourceInfo]
    experiment_id: str
    layers: Layers
    value_kind: str = "unknown"
    plates: list[PlateMeta] = []
    header: list[HeaderItem] = []
    quarantine: list[QuarantineEntry] = []
    warnings: list[CaptureWarning] = []
    rawness: dict | None = None

    model_config = {"populate_by_name": True}

    def to_json(self) -> str:
        """Deterministic JSON (sorted keys, no timestamps)."""
        import json

        return json.dumps(
            self.model_dump(mode="json", by_alias=True), sort_keys=True, indent=2,
            ensure_ascii=False,
        ) + "\n"  # fmt: skip

    def warn(self, code: str, message: str) -> None:
        """Add a warning once."""
        item = CaptureWarning(code=code, message=message)
        if item not in self.warnings:
            self.warnings.append(item)


class TextBox:
    """Collects quarantined text while a capture is built (deduplicated by ``text_id``)."""

    def __init__(self) -> None:
        self.entries: dict[str, QuarantineEntry] = {}

    def add(self, origin: str, value: str | None) -> str | None:
        """Quarantine ``value`` (if any) and return its ``text_id``."""
        if value is None or str(value) == "":
            return None
        text = str(value)
        text_id = text_id_for(origin, text)
        if text_id not in self.entries:
            from qpilot.core.firewall import flags_for

            self.entries[text_id] = QuarantineEntry(
                text_id=text_id, origin=origin, value=text, flags=flags_for(text)
            )
        return text_id

    def all(self) -> list[QuarantineEntry]:
        """Every entry, sorted by ``text_id`` (deterministic)."""
        return [self.entries[key] for key in sorted(self.entries)]


__all__ = [
    "CAPTURE_SCHEMA",
    "RDML_SAMPLE_TYPES",
    "CaptureError",
    "CaptureMeta",
    "CaptureWarning",
    "Connector",
    "ConnectorInfo",
    "Curve",
    "Detection",
    "HeaderItem",
    "Layers",
    "PlateData",
    "PlateMeta",
    "Probe",
    "Reaction",
    "Sniff",
    "Source",
    "SourceInfo",
    "TextBox",
    "ValueKind",
    "VendorType",
    "finite",
]
