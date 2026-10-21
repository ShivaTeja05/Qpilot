"""Open what an instrument wrote: sort the dropped files, read the export, keep what was read.

``POST /api/workspaces`` with ``files`` (one file or a whole export set) comes here. Each file
was already kept by content (``studio-inputs/<sha256[:24]><suffix>``, its own name remembered
beside it); :func:`sort_dropped` decides by **content** (``qpilot.io.connectors.detect``, never
the suffix alone) what each file is:

* an RDML file: opened as it is, exactly as the ``rdml`` field does;
* a file a vendor connector reads (CFX, QuantStudio, LightCycler 480, RDES, a tidy table): part
  of the export; all of them must be one kind of export;
* any other ``.csv``/``.tsv``/``.xlsx``/``.xlsm`` with a sample column
  (:func:`qpilot.io.sheets.sheet_table`) that is not a sheet of the export itself: the optional
  sample sheet;
* anything else: not used, and named back to the person.

:func:`read_export` copies the export's files under the person's own names into the study
store (``imports/sources/<key>/``: connectors read plate names and CFX fluorophores from file
names), materialises them once as deterministic RDML (``imports/capture/<key>.rdml``), and the
session opens that file. What was read (:class:`~qpilot.io.connectors.CaptureMeta`) is kept in
the session folder as ``capture.json``, so it survives a restart; :func:`summary` turns it into
the page's blind-safe :class:`~qpilot.web.contract_capture.CaptureSummary`.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from qpilot.core.store import StudyNotFound, StudyStore, atomic_write, dump_json
from qpilot.io.connectors import CaptureError, CaptureMeta, Detection, Materialised, detect
from qpilot.io.connectors import materialise as materialise_export
from qpilot.io.connectors.common import plate_stem
from qpilot.web.contract_capture import (
    CaptureNote,
    CapturePlate,
    CaptureRawness,
    CaptureSource,
    CaptureSummary,
)

IMPORTS_DIR = "imports"
SOURCES_DIR = "sources"
CAPTURE_FILE = "capture.json"
CAPTURE_SCHEMA = "qpilot.web.capture/1"
MAX_FILES = 64
MAX_NAME_BYTES = 200
#: What the ``files`` field keeps (the content decides what each file is).
EXPORT_SUFFIXES = (".rdml", ".rdm", ".xml", ".lc96p", ".csv", ".tsv", ".txt", ".xlsx", ".xlsm")
SHEET_SUFFIXES = (".csv", ".tsv", ".xlsx", ".xlsm")
#: Instrument project files qPilot cannot read, and how to export from them.
PROJECT_FILES = {
    ".pcrd": "a CFX Manager project: export it with Export > Export All Data Sheets (CSV)",
    ".zpcr": "a CFX Maestro project: export it with Export > Export All Data Sheets (CSV)",
    ".eds": "a QuantStudio experiment: export Results and Amplification Data (.txt or .csv)",
    ".sds": "an SDS experiment: export Results and Amplification Data (.txt or .csv)",
    ".ixo": "a LightCycler 480 experiment: export the raw data with Export > Text",
    ".xls": "a legacy Excel workbook: save it as .xlsx or .csv",
}


class Refused(Exception):
    """The dropped files cannot be opened together; ``message`` says why in plain words."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Dropped:
    """One dropped file: its kept copy, the name the person gave it, what detection says."""

    path: Path
    name: str
    detections: list[Detection] = field(default_factory=list)

    @property
    def connector(self) -> str | None:
        """The connector most sure it reads this file (``None``: no connector does)."""
        return self.detections[0].connector_id if self.detections else None


@dataclass
class Sorted:
    """The dropped files, sorted by what they are."""

    rdml: list[Dropped] = field(default_factory=list)
    exports: list[Dropped] = field(default_factory=list)
    sheets: list[Dropped] = field(default_factory=list)
    unused: list[Dropped] = field(default_factory=list)
    label: str = ""


def suffix_problem(name: str) -> str | None:
    """Why a file of this name is not taken (by its suffix), or ``None`` when it is."""
    suffix = Path(name).suffix.lower()
    if suffix in EXPORT_SUFFIXES:
        return None
    shown = name or "This file"
    if suffix in PROJECT_FILES:
        return f"{shown} is {PROJECT_FILES[suffix]}, then open the exported files."
    return (
        f"{shown}: qPilot opens RDML files and instrument exports "
        "(.rdml, .xml, .csv, .tsv, .txt, .xlsx)."
    )


def safe_name(name: str, fallback: str) -> str:
    """A file name to stage a dropped file under: its base name, printable, at most 200 bytes.

    Never a path: no separators, never ``.``/``..``, never hidden (a leading dot or ``~``).
    """
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in base if ch.isprintable() and ch not in "/\x00").strip()
    if base in ("", ".", ".."):
        base = fallback
    if base.startswith((".", "~")):
        base = "_" + base
    suffix = Path(base).suffix[:16]
    stem = base[: len(base) - len(suffix)] if suffix else base
    while len((stem + suffix).encode("utf-8")) > MAX_NAME_BYTES and stem:
        stem = stem[:-1]
    return (stem.strip() or "file") + suffix


def classify(path: Path, name: str) -> Dropped:
    """What detection says about one kept file (its message names the person's file).

    Raises:
        Refused: The file cannot even be looked at (empty, over the cap, unreadable).
    """
    try:
        found = detect(path)
    except CaptureError as err:
        raise Refused("bad_file", str(err).replace(path.name, name)) from err
    return Dropped(path=path, name=name, detections=found)


def _is_sheet(item: Dropped) -> bool:
    from qpilot.io.sheets import SheetError, sheet_table

    if Path(item.name).suffix.lower() not in SHEET_SUFFIXES:
        return False
    try:
        return sheet_table(item.path) is not None
    except (SheetError, OSError, ValueError):
        return False


def _design_sheet(item: Dropped) -> bool:
    from qpilot.io.sheets import SheetError, sheet_table

    try:
        table = sheet_table(item.path)
    except (SheetError, OSError, ValueError):
        return False
    return table is not None and bool({"group", "bio_unit", "bio_rep"} & set(table.columns))


def _labels() -> dict[str, str]:
    from qpilot.io.connectors import connectors

    return {c.id: c.label for c in connectors()}


def sort_dropped(items: list[Dropped]) -> Sorted:
    """Sort dropped files into the RDML file, the export, the sample sheet and the unused.

    Raises:
        Refused: Nothing qPilot reads; an RDML file with an export; two RDML files; two kinds
            of export; two sample sheets; or a sample sheet alone.
    """
    out = Sorted()
    unclaimed: list[Dropped] = []
    for item in items:
        if item.connector == "rdml":
            out.rdml.append(item)
        elif item.connector is not None:
            out.exports.append(item)
        else:
            unclaimed.append(item)
    labels = _labels()
    if out.rdml and out.exports:
        raise Refused(
            "mixed_files",
            f"{out.rdml[0].name} is an RDML file and {out.exports[0].name} is an instrument "
            "export; open one of them at a time.",
        )
    if len(out.rdml) > 1:
        names = ", ".join(i.name for i in out.rdml[:3])
        raise Refused(
            "mixed_files",
            f"Open one RDML file at a time ({names}); one RDML file can hold many plates.",
        )
    if out.exports:
        chosen = out.exports[0].connector
        for item in out.exports[1:]:
            if item.connector != chosen and chosen not in {d.connector_id for d in item.detections}:
                raise Refused(
                    "mixed_files",
                    f"{item.name} looks like a {labels.get(item.connector or '', 'other')}, but "
                    f"{out.exports[0].name} is a {labels.get(chosen or '', 'other')}; open one "
                    "kind of export at a time.",
                )
        out.label = labels.get(chosen or "", "")
    stems = {plate_stem(Path(i.name).stem).lower() for i in out.exports}
    for item in unclaimed:
        part_of_export = plate_stem(Path(item.name).stem).lower() in stems
        if not part_of_export and _is_sheet(item):
            out.sheets.append(item)
        else:
            out.unused.append(item)
    if len(out.sheets) > 1:
        design = [i for i in out.sheets if _design_sheet(i)]
        if len(design) == 1:
            out.unused.extend(i for i in out.sheets if i is not design[0])
            out.sheets = design
        else:
            names = ", ".join(i.name for i in out.sheets[:3])
            raise Refused("mixed_files", f"Add one sample sheet at a time ({names}).")
    if not out.rdml and not out.exports:
        if out.sheets:
            raise Refused(
                "bad_file",
                f"{out.sheets[0].name} looks like a sample sheet. Add the instrument's export or "
                "RDML file with it.",
            )
        names = ", ".join(i.name for i in out.unused[:3])
        raise Refused(
            "bad_file",
            f"qPilot does not recognise {names} as an instrument export it reads: RDML; CFX, "
            "QuantStudio or LightCycler 480 exports; RDES; a tidy table with well, cycle and "
            "fluorescence columns; or a Cq table.",
        )
    return out


def rdml_input(item: Dropped) -> Path:
    """The RDML file to open: the kept copy, under an ``.rdml``/``.xml`` name (``.lc96p`` …)."""
    if item.path.suffix.lower() in (".rdml", ".xml"):
        return item.path
    zipped = item.detections[0].dialect.startswith("rdml.zip")
    target = item.path.with_suffix(".rdml" if zipped else ".xml")
    if not target.exists():
        shutil.copyfile(item.path, target)
    from qpilot.web import views

    views.remember_name(target, item.name)
    return target


def imports_dir(store: StudyStore) -> Path:
    """Where imports live in the study store: staged sources and the RDML built from them."""
    return store.root / IMPORTS_DIR


def stage(store: StudyStore, exports: list[Dropped]) -> list[Path]:
    """The export's files under the person's names, in a folder keyed by names and contents.

    Raises:
        Refused: Two different files with one name.
    """
    named: dict[str, Dropped] = {}
    for index, item in enumerate(exports, start=1):
        name = safe_name(item.name, f"file{index}{item.path.suffix}")
        other = named.get(name)
        if other is not None and other.path != item.path:
            raise Refused(
                "bad_file", f"Two different files are named {name}; rename one and try again."
            )
        named[name] = item
    digest = hashlib.sha256()
    for name in sorted(named):
        digest.update(f"{name}\x00{named[name].path.name}\x00".encode())
    folder = imports_dir(store) / SOURCES_DIR / digest.hexdigest()[:20]
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in sorted(named):
        target = folder / name
        if not target.exists():
            try:
                os.link(named[name].path, target)
            except OSError:
                shutil.copyfile(named[name].path, target)
        paths.append(target)
    return paths


def title(meta: CaptureMeta) -> str:
    """How the import is named on the page: its file, or its plate and how many files."""
    names = [s.name for s in meta.sources]
    if len(names) == 1:
        return names[0]
    if len(meta.plates) == 1:
        return f"{meta.plates[0].run_id} ({len(names)} files)"
    return f"{names[0]} and {len(names) - 1} more files"


def read_export(store: StudyStore, exports: list[Dropped]) -> Materialised:
    """Stage the export, build its RDML once (cached in the study store), remember its title.

    Raises:
        Refused: Two different files with one name.
        CaptureError: The export cannot be read (the message names the person's files).
    """
    from qpilot.web import views

    paths = stage(store, exports)
    result = materialise_export(paths, cache_dir=imports_dir(store))
    views.remember_name(result.rdml_path, title(result.meta))
    return result


def save(store: StudyStore, sid: str, meta: CaptureMeta, unused: list[str]) -> None:
    """Keep what was read with the session (``capture.json``), so it survives a restart."""
    record = {
        "schema": CAPTURE_SCHEMA,
        "meta": json.loads(meta.to_json()),
        "unused": list(unused),
    }
    atomic_write(store.find_session(sid) / CAPTURE_FILE, dump_json(record))


def load(store: StudyStore, sid: str) -> tuple[CaptureMeta, list[str]] | None:
    """The session's import record, or ``None`` (an RDML file, or a damaged record)."""
    try:
        path = store.find_session(sid) / CAPTURE_FILE
        if not path.is_file():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
        meta = CaptureMeta.model_validate(record["meta"])
        unused = [str(n) for n in record.get("unused", [])]
    except (StudyNotFound, OSError, ValueError, KeyError, TypeError):
        return None
    return meta, unused


#: Raw-ness verdict -> (title, what it means for the analysis).
RAWNESS_WORDS: dict[str, tuple[str, str]] = {
    "raw": (
        "Raw fluorescence",
        "The curves are as the instrument read them, so LinRegPCR estimates each well's "
        "baseline and efficiency itself.",
    ),
    "normalized": (
        "Normalised to a passive reference (Rn)",
        "The curves are divided by the passive reference dye; the ground phase is kept, so "
        "LinRegPCR can still estimate each well's baseline and efficiency.",
    ),
    "baseline_subtracted": (
        "Baseline already subtracted",
        "The instrument software subtracted a baseline before export. That weakens LinRegPCR's "
        "per-well efficiency, because it cannot see each well's own baseline. Re-export the raw "
        "fluorescence to restore it: in CFX Manager or Maestro choose 'No Baseline Subtraction' "
        "before exporting; from QuantStudio export Rn, not Delta Rn.",
    ),
    "scaled": (
        "Rescaled from 0 to 1",
        "The curves were rescaled before export; qPilot cannot see whether a baseline was "
        "subtracted first, so per-well efficiencies may be weaker. Re-export the raw "
        "fluorescence if you can.",
    ),
    "cq_only": (
        "Cq values only",
        "There are no curves to check: only the instrument's Cq values. Efficiency is assumed, "
        "not measured, so confidence is capped at Low.",
    ),
    "unknown": (
        "Not clear",
        "qPilot could not tell whether the curves were processed before export (the signal is "
        "small, the run short, or the wells disagree); treat per-well efficiencies with caution.",
    ),
}

VALUE_WORDS = {
    "RFU": "RFU, as the instrument software exported them",
    "Rn": "Rn: reporter divided by the passive reference dye",
    "dRn": "Delta Rn: Rn minus a baseline the software fitted",
    "fluorescence": "Fluorescence, as exported",
    "unknown": "No curves: Cq values only",
}


def summary(store: StudyStore, sid: str) -> CaptureSummary | None:
    """The page's view of the session's import (``None`` when it was opened from RDML)."""
    loaded = load(store, sid)
    if loaded is None:
        return None
    meta, unused = loaded
    rawness: dict[str, Any] = meta.rawness or {}
    verdict = str(rawness.get("study_verdict") or "unknown")
    words = RAWNESS_WORDS.get(verdict, RAWNESS_WORDS["unknown"])
    plate_verdicts = rawness.get("plate_verdicts") or {}
    return CaptureSummary(
        connector=meta.connector.id,
        label=meta.connector.label,
        dialect=meta.dialect,
        sources=[CaptureSource(name=s.name, role=s.role, bytes=s.bytes) for s in meta.sources],
        unused=unused,
        value_kind=meta.value_kind,
        value_words=VALUE_WORDS.get(meta.value_kind, meta.value_kind),
        layers=meta.layers.model_dump(),
        plates=[
            CapturePlate(
                run_id=p.run_id,
                rows=p.rows,
                columns=p.columns,
                n_wells=p.n_wells,
                n_reactions=p.n_reactions,
                n_cycles=p.n_cycles,
                targets=p.targets,
                dyes=p.dyes,
                sample_types=p.sample_types,
                n_unmapped_types=sum(v.n_wells for v in p.vendor_types if v.unmapped),
                n_with_vendor_cq=p.n_with_vendor_cq,
                vendor_omitted=p.vendor_omitted,
                value_kind=p.value_kind,
                verdict=str(plate_verdicts.get(p.run_id, "unknown")),
            )
            for p in meta.plates
        ],
        rawness=CaptureRawness(
            verdict=verdict,
            title=words[0],
            meaning=words[1],
            linregpcr_ok=bool(rawness.get("linregpcr_ok")),
        ),
        warnings=[CaptureNote(code=w.code, message=w.message) for w in meta.warnings],
        n_quarantined=len(meta.quarantine),
    )


__all__ = [
    "CAPTURE_FILE",
    "EXPORT_SUFFIXES",
    "MAX_FILES",
    "Dropped",
    "Refused",
    "Sorted",
    "classify",
    "load",
    "rdml_input",
    "read_export",
    "safe_name",
    "save",
    "sort_dropped",
    "stage",
    "suffix_problem",
    "summary",
    "title",
]
