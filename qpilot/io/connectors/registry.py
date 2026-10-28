"""Find the connector for an input by its content, read it, and materialise it as RDML.

Detection reads at most the first 256 KB of a text file (or the first rows of each sheet of a
workbook) and asks every connector how sure it is; the suffix only breaks ties. Several files
form one study (one plate each, or one CFX export set per plate); a folder means its files.

:func:`materialise` is what engine callers use: an RDML input is returned as it is (path and
sha256 unchanged), any other input is written once as a deterministic RDML archive in the
cache, keyed by the connector's id and version and the name and sha256 of every source file,
next to its ``.capture.json`` (:class:`~qpilot.io.connectors.base.CaptureMeta`).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from qpilot.io.connectors import builder
from qpilot.io.connectors.base import (
    CaptureError,
    CaptureMeta,
    Connector,
    ConnectorInfo,
    Detection,
    HeaderItem,
    Layers,
    PlateData,
    PlateMeta,
    Probe,
    Source,
    SourceInfo,
    TextBox,
    VendorType,
)
from qpilot.io.connectors.sample_types import known_token
from qpilot.io.connectors.tables import (
    PROBE_ROWS,
    check_size,
    file_kind,
    head_lines,
    read_workbook,
)

MAX_FILES = 256
CAPTURE_DIR = "capture"


def _registered() -> list[Connector]:
    from qpilot.io.connectors import cfx, lightcycler, quantstudio, rdml_file, tidy

    return [
        rdml_file.CONNECTOR,
        cfx.CONNECTOR,
        quantstudio.CONNECTOR,
        lightcycler.CONNECTOR,
        tidy.RDES,
        tidy.TIDY,
    ]


def connectors() -> list[Connector]:
    """Every registered connector, in detection order."""
    return _registered()


def get_connector(connector_id: str) -> Connector:
    """The connector with this id.

    Raises:
        CaptureError: No such connector.
    """
    for connector in _registered():
        if connector.id == connector_id:
            return connector
    known = ", ".join(c.id for c in _registered())
    raise CaptureError(f"no connector {connector_id!r} (known: {known})")


@dataclass
class Capture:
    """One read input: the RDML document, what was recorded, and the plates as read.

    Attributes:
        doc: The vendored ``rdml.Rdml`` document.
        meta: What was captured (JSON-ready).
        plates: The plates as the connector read them (for the raw-ness detector).
        xml: The RDML XML qPilot built (``None`` for an RDML input, which is used as it is).
        sources: The input files, in reading order.
    """

    doc: object
    meta: CaptureMeta
    plates: list[PlateData]
    xml: bytes | None
    sources: tuple[Path, ...] = field(default_factory=tuple)


@dataclass
class Materialised:
    """An input ready for the engine: an RDML path and what was captured."""

    rdml_path: Path
    meta: CaptureMeta
    sources: tuple[Path, ...]


# ---------------------------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------------------------


def probe(path: Path) -> Probe:
    """The first look at a file (see :class:`~qpilot.io.connectors.base.Probe`)."""
    check_size(path)
    kind = file_kind(path)
    found = Probe(path=path, suffix=path.suffix.lower(), kind=kind)
    if kind == "text":
        found.head = head_lines(path)
    elif kind == "xlsx":
        try:
            grids = read_workbook(path, max_rows=PROBE_ROWS)
        except CaptureError:
            return found
        found.sheets = {grid.name: grid.rows for grid in grids}
    return found


def _sniff(found: Probe, only: str | None) -> list[tuple[Connector, Detection]]:
    out = []
    for connector in _registered():
        if only is not None and connector.id != only:
            continue
        result = connector.sniff(found)
        if result is None or result.score <= 0:
            continue
        score = result.score + (1 if found.suffix in connector.suffixes else 0)
        out.append((connector, Detection(connector.id, score, result.dialect, result.role)))
    out.sort(key=lambda item: -item[1].score)
    return out


def detect(path: str | Path) -> list[Detection]:
    """Every connector that recognises the file, most confident first (``[]`` = none)."""
    return [d for _, d in _sniff(probe(Path(path)), None)]


def is_capturable(path: str | Path) -> bool:
    """Whether some connector reads this file (cheap: the probe only; never raises)."""
    try:
        return bool(detect(path))
    except (CaptureError, OSError):
        return False


def expand(paths: str | Path | Sequence[str | Path]) -> list[Path]:
    """The input files: each path, a folder's files (sorted, not recursive), no duplicates.

    Raises:
        CaptureError: A missing path, no files, or more than :data:`MAX_FILES` files.
    """
    items = [paths] if isinstance(paths, str | Path) else list(paths)
    files: list[Path] = []
    for item in items:
        path = Path(item)
        if path.is_dir():
            files.extend(
                sorted(
                    p for p in path.iterdir() if p.is_file() and not p.name.startswith((".", "~$"))
                )
            )
        elif path.is_file():
            files.append(path)
        else:
            raise CaptureError(f"not a file or folder: {path.name}")
    unique = list(dict.fromkeys(p.resolve() for p in files))
    if not unique:
        raise CaptureError("no input files")
    if len(unique) > MAX_FILES:
        raise CaptureError(f"more than {MAX_FILES} input files")
    return unique


DESIGN_TABLE = "tidy.cq.design"


def _looked(path: Path, only: str | None) -> tuple[Probe, list[tuple[Connector, Detection]]]:
    found = probe(path)
    return found, _sniff(found, only)


def _choose(files: list[Path], only: str | None) -> tuple[Connector, list[Source]]:
    """One connector for every file (a mix of vendors is refused)."""
    chosen: Connector | None = None
    sources: list[Source] = []
    skipped: list[str] = []
    looked = [(path, *_looked(path, only)) for path in files]
    # a person's Cq table naming conditions, beside the export it was typed from, is that
    # export's sample sheet (``qpilot.web.intake``), not a second kind of export
    curves = any(m and m[0][1].dialect != DESIGN_TABLE for _, _, m in looked)
    for path, found, matches in looked:
        if not matches or (curves and matches[0][1].dialect == DESIGN_TABLE):
            skipped.append(path.name)
            continue
        connector, detection = matches[0]
        if chosen is None:
            chosen = connector
        elif connector.id != chosen.id:
            same = [m for m in matches if m[0].id == chosen.id]
            if not same:
                raise CaptureError(
                    f"{path.name} looks like a {connector.label}, but the other files are a "
                    f"{chosen.label}; import one kind of export at a time"
                )
            connector, detection = same[0]
        sniff = connector.sniff(found)
        assert sniff is not None
        sources.append(Source(path=path, probe=found, sniff=sniff))
    if chosen is None:
        names = ", ".join(skipped[:3])
        raise CaptureError(
            f"qPilot does not recognise {names} as an instrument export it reads "
            "(RDML; CFX, QuantStudio or LightCycler 480 exports; RDES; a tidy CSV with well, "
            "cycle and fluorescence columns; or a Cq table)"
        )
    if skipped and len(files) == 1:
        raise CaptureError(f"{skipped[0]}: not a recognised export")
    return chosen, sources


# ---------------------------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------------------------


def sha256_file(path: Path) -> str:
    """sha256 of a file's bytes, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def capture(paths: str | Path | Sequence[str | Path], *, connector: str | None = None) -> Capture:
    """Read one or more input files into an RDML document and a :class:`CaptureMeta`.

    Args:
        paths: A file, a folder, or several files (several plates of one study).
        connector: Force a connector id (``"cfx"``, ``"tidy"`` ...) instead of detection.

    Raises:
        CaptureError: Unrecognised, mixed, unsafe or inconsistent input.
    """
    files = expand(paths)
    chosen, sources = _choose(files, connector)
    plates = chosen.read(sources)
    plates = [p for p in plates if p.reactions]
    if chosen.id == "rdml":
        doc = chosen.load(sources[0].path)  # type: ignore[attr-defined]
        xml, notes = None, builder.BuildNotes()
        experiments = [e["id"] for e in doc.experiments()]
        experiment_id = experiments[0] if len(experiments) == 1 else ""
    else:
        xml, notes = builder.build_xml(plates, description=f"qPilot import: {chosen.label}")
        doc = builder.load_xml(xml)
        experiment_id = builder.EXPERIMENT_ID
    meta = describe(chosen, sources, plates, notes, experiment_id)
    from qpilot.io import rawness

    meta.rawness = rawness.assess(plates).to_json()
    for code, message in rawness.warnings_for(meta.rawness):
        meta.warn(code, message)
    return Capture(doc=doc, meta=meta, plates=plates, xml=xml, sources=tuple(files))


def describe(
    connector: Connector,
    sources: list[Source],
    plates: list[PlateData],
    notes: builder.BuildNotes,
    experiment_id: str,
) -> CaptureMeta:
    """The :class:`CaptureMeta` of a read input (every free text quarantined)."""
    box = TextBox()
    meta = CaptureMeta(
        connector=ConnectorInfo(id=connector.id, version=connector.version, label=connector.label),
        dialect="+".join(sorted({s.sniff.dialect for s in sources})),
        sources=[
            SourceInfo(
                name=s.path.name,
                sha256=sha256_file(s.path),
                bytes=s.path.stat().st_size,
                role=s.sniff.role,
            )
            for s in sources
        ],
        experiment_id=experiment_id,
        layers=Layers(),
    )
    origin = f"capture:{connector.id}"
    kinds = Counter()
    unmapped = 0
    for plate in plates:
        meta.plates.append(_plate_meta(plate, box, origin))
        kinds[plate.value_kind] += 1
        for key, value in plate.header:
            text_id = box.add(f"{origin}:header:{key}", value)
            if text_id:
                item = HeaderItem(key=key, text_id=text_id)
                if item not in meta.header:
                    meta.header.append(item)
        box.add(f"{origin}:run", plate.run_id)
        box.add(f"{origin}:software", plate.software)
        for note in plate.notes:
            meta.warn("READER_NOTE", note)
        unmapped += sum(v.n_wells for v in meta.plates[-1].vendor_types if v.unmapped)
    layers = meta.layers
    every = [r for p in plates for r in p.reactions]
    layers.amplification = any(r.amp is not None for r in every)
    layers.melt = any(r.melt is not None for r in every)
    layers.cq = any(r.cq is not None for r in every)
    layers.sample_types = any(r.vendor_type or r.sample_type != "unkn" for r in every)
    layers.targets = any(r.target for r in every)
    layers.quantities = any(r.quantity is not None for r in every)
    meta.value_kind = kinds.most_common(1)[0][0] if kinds else "unknown"
    if unmapped:
        meta.warn(
            "UNMAPPED_SAMPLE_TYPE",
            f"{unmapped} wells have a sample type qPilot does not know; they are treated as "
            "unknowns until you type your controls.",
        )
    if not layers.sample_types:
        meta.warn(
            "NO_SAMPLE_TYPES",
            "The file declares no sample types; every well is treated as an unknown until "
            "you type your controls (NTC, no-RT, standards).",
        )
    if notes.type_conflicts:
        meta.warn(
            "TYPE_CONFLICT",
            f"{notes.type_conflicts} sample-target pairs have wells of different sample types; "
            "the most common type is used.",
        )
    if notes.quantity_conflicts:
        meta.warn(
            "QUANTITY_CONFLICT",
            f"{notes.quantity_conflicts} standards have different quantities in different "
            "wells; the first is used.",
        )
    if notes.unnamed_wells:
        meta.warn(
            "UNNAMED_WELLS",
            f"{notes.unnamed_wells} reactions have no sample name; each such well is its own "
            "sample, named after its plate and well.",
        )
    if notes.dye_conflicts:
        meta.warn(
            "DYE_CONFLICT",
            "A target is read with more than one dye; the first dye is recorded for it.",
        )
    if notes.role_conflicts:
        meta.warn(
            "ROLE_CONFLICT",
            f"{notes.role_conflicts} targets are called a reference gene in some rows and a "
            "target in others; qPilot records them as targets. Set their roles in Design.",
        )
    declared = sum(1 for r in every if r.target_type == "ref")
    if declared:
        refs = sorted({builder.clean_id(r.target, "") for r in every if r.target_type == "ref"})
        meta.warn(
            "DECLARED_REFERENCES",
            f"The table names {len(refs)} reference gene{'s' if len(refs) != 1 else ''} in its "
            "gene type column; Design proposes "
            + ("them" if len(refs) != 1 else "it")
            + " as reference genes for you to confirm.",
        )
    omitted = sum(len(p.vendor_omitted) for p in meta.plates)
    if omitted:
        meta.warn(
            "VENDOR_OMITTED",
            f"The vendor software marked {omitted} wells omitted. qPilot analyses every well; "
            "exclude them in Studio if you agree.",
        )
    meta.quarantine = box.all()
    return meta


def _plate_meta(plate: PlateData, box: TextBox, origin: str) -> PlateMeta:
    reactions = plate.reactions
    rows, columns = builder.plate_format(plate) if reactions else (plate.rows, plate.columns)
    wells = sorted({(r.row, r.column) for r in reactions})
    targets: list[str] = []
    dyes: list[str] = []
    for reaction in sorted(reactions, key=lambda r: (r.row, r.column)):
        box.add(f"{origin}:sample", reaction.sample)
        box.add(f"{origin}:target", reaction.target)
        target = builder.clean_id(reaction.target, builder.clean_id(reaction.dye, "target"))
        if target not in targets:
            targets.append(target)
        dye = builder.clean_id(reaction.dye, "")
        if dye and dye not in dyes:
            dyes.append(dye)
    per_well_type: dict[tuple[int, int], str] = {}
    vendor: dict[tuple[str, str, bool], set[tuple[int, int]]] = {}
    for reaction in reactions:
        per_well_type.setdefault((reaction.row, reaction.column), reaction.sample_type)
        if reaction.vendor_type:
            token = known_token(reaction.vendor_type) or box.add(
                f"{origin}:sample_type", reaction.vendor_type
            )
            key = (token or "", reaction.sample_type, not reaction.type_mapped)
            vendor.setdefault(key, set()).add((reaction.row, reaction.column))
    cycles = max((len(r.amp.x) for r in reactions if r.amp is not None), default=0)
    omitted = sorted({(r.row, r.column) for r in reactions if r.omitted})
    return PlateMeta(
        run_id=plate.run_id,
        rows=rows,
        columns=columns,
        n_wells=len(wells),
        n_reactions=len(reactions),
        n_cycles=cycles,
        targets=targets,
        dyes=dyes,
        sample_types=dict(sorted(Counter(per_well_type.values()).items())),
        vendor_types=[
            VendorType(vendor=token, mapped=mapped, n_wells=len(where), unmapped=flag)
            for (token, mapped, flag), where in sorted(vendor.items())
        ],
        n_with_vendor_cq=sum(1 for r in reactions if r.cq is not None),
        n_with_amplification=sum(1 for r in reactions if r.amp is not None),
        n_with_melt=sum(1 for r in reactions if r.melt is not None),
        vendor_omitted=[builder.well_name(r, c) for r, c in omitted],
        value_kind=plate.value_kind,
        sources=list(dict.fromkeys(name for name, _ in plate.sources)),
    )


# ---------------------------------------------------------------------------------------------
# Materialising
# ---------------------------------------------------------------------------------------------


def _atomic_write(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = data.encode("utf-8") if isinstance(data, str) else data
    handle = tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False)
    try:
        with handle:
            handle.write(payload)
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


def _cache_root(cache_dir: str | Path | None) -> Path:
    from qpilot.io.datasets import default_cache_dir

    return (Path(cache_dir) if cache_dir is not None else default_cache_dir()) / CAPTURE_DIR


def materialise(
    paths: str | Path | Sequence[str | Path],
    *,
    cache_dir: str | Path | None = None,
    connector: str | None = None,
) -> Materialised:
    """An RDML file the engine can read for this input, plus what was captured.

    An RDML input is returned as it is. Anything else is converted once and cached under
    ``<cache>/capture/`` (a second call with the same files, by name and bytes, reads the
    cache; names count because plate names and CFX fluorophores are read from them).

    Raises:
        CaptureError: The input cannot be read (see :func:`capture`).
    """
    files = expand(paths)
    chosen, _ = _choose(files, connector)
    digest = hashlib.sha256(f"{chosen.id}\x00{chosen.version}".encode())
    for path in files:
        # the name counts too: plate names and CFX fluorophores are read from file names
        digest.update(b"\x00" + path.name.encode("utf-8", "surrogateescape"))
        digest.update(b"\x00" + sha256_file(path).encode())
    key = digest.hexdigest()[:20]
    root = _cache_root(cache_dir)
    meta_path = root / f"{key}.capture.json"
    rdml_path = files[0] if chosen.id == "rdml" else root / f"{key}.rdml"
    if meta_path.exists() and rdml_path.exists():
        try:
            meta = CaptureMeta.model_validate(json.loads(meta_path.read_text(encoding="utf-8")))
            return Materialised(rdml_path=rdml_path, meta=meta, sources=tuple(files))
        except (ValueError, OSError):
            pass  # a damaged cache entry is rebuilt
    result = capture(files, connector=chosen.id)
    if result.xml is not None:
        _atomic_write(rdml_path, builder.rdml_archive(result.xml))
    _atomic_write(meta_path, result.meta.to_json())
    return Materialised(rdml_path=rdml_path, meta=result.meta, sources=tuple(files))


def write_rdml(result: Capture, out: str | Path) -> Path:
    """Write a capture's RDML to ``out`` (an RDML input is copied byte for byte)."""
    target = Path(out)
    if result.xml is None:
        _atomic_write(target, result.sources[0].read_bytes())
    else:
        _atomic_write(target, builder.rdml_archive(result.xml))
    return target


__all__ = [
    "Capture",
    "Materialised",
    "capture",
    "connectors",
    "describe",
    "detect",
    "expand",
    "get_connector",
    "is_capturable",
    "materialise",
    "probe",
    "sha256_file",
    "write_rdml",
]
