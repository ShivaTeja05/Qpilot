"""The run file an instrument export already holds for each plate (Run Gate's G-INSTR).

A Studio session opened from a vendor export (:mod:`qpilot.web.intake`) is analysed from the RDML
qPilot built from it, and RDML has no field for the run state, pauses or calibrations. The export
often has them: a QuantStudio results export starts with the run's header rows (calibrations and
their expiry, the run's end) and flags wells; a CFX export set can include the run's "Run
Information" sheet. Each plate of the built RDML was read from known files of the export
(:func:`qpilot.io.connectors.common.plate_sources`), so G-INSTR reads the plate's own run file
from among them with :func:`~qpilot.qpcr.instrument_context.read_run_context`. Where several can
be read (a QuantStudio export repeats its header in every file), the one that lets the most be
checked is read.

The files are found by content in a folder (the page keeps every dropped file there as
``<sha256[:24]><suffix>``) and read only if their bytes are still the export's: a file that is
gone or changed is not read, and the plate reads its RDML. A file that is not a run file (an
amplification or Cq sheet) is simply not one. A run file a person links to a plate comes first
(:mod:`qpilot.qpcr.run_links`).

Serial numbers stay in the context (local only: :meth:`RunContext.model_view` leaves them out);
:attr:`ExportRun.name` is the file's name as the person's export called it, which may hold one,
so whoever shows it blanks the run's identity strings first. No model call and no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from qpilot.core.store import sha256_file
from qpilot.io.connectors import CaptureMeta
from qpilot.io.connectors.base import SourceInfo
from qpilot.io.connectors.common import plate_sources
from qpilot.qpcr.instrument_context import InstrumentFileError, RunContext, read_run_context

#: The suffixes of the run files an export can hold (QuantStudio results, CFX run information).
RUN_SUFFIXES = (".csv", ".tsv", ".txt")
SHA256 = re.compile(r"^[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class ExportRun:
    """One plate's run file in the export: its name, its sha256 and what it says."""

    plate: str
    name: str
    sha256: str
    context: RunContext


def kept_path(folder: str | Path, source: SourceInfo) -> Path | None:
    """The export's file kept by content in ``folder`` (``None`` when it is gone or changed)."""
    suffix = Path(source.name).suffix.lower()
    if not SHA256.match(source.sha256) or suffix not in RUN_SUFFIXES:
        return None
    path = Path(folder) / f"{source.sha256[:24]}{suffix}"
    try:
        return path if path.is_file() and sha256_file(path) == source.sha256 else None
    except OSError:
        return None


def export_runs(meta: CaptureMeta, folder: str | Path) -> dict[str, ExportRun]:
    """Plate -> the run file the export holds for it; a plate without one is left out."""
    sources = {s.name: s for s in meta.sources}
    out: dict[str, ExportRun] = {}
    for plate, names in plate_sources(meta).items():
        found: list[ExportRun] = []
        for name in names:
            source = sources[name]
            path = kept_path(folder, source)
            if path is None:
                continue
            try:
                context = read_run_context(path)
            except (InstrumentFileError, OSError, ValueError):
                continue  # not a run file: an amplification or a Cq sheet
            if context.source_kind != "rdml":
                found.append(ExportRun(plate, name, source.sha256, context))
        if found:  # the first of those that let the most be checked
            out[plate] = max(found, key=lambda r: (len(r.context.checked), len(r.context.facts)))
    return out


__all__ = ["RUN_SUFFIXES", "ExportRun", "export_runs", "kept_path"]
