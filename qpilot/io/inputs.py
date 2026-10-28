"""The files a person opened, by the names they gave them, for anything that prints a source.

qPilot keeps what it opens by content: an uploaded RDML file as ``studio-inputs/<sha256[:24]>``
and an instrument export as the RDML it was converted to, ``imports/capture/<key>.rdml``. Those
names are for qPilot; a report, an audit or an Evidence Ledger must name the person's own
files. :func:`input_files` finds them from the kept path alone:

* a converted export: every file it was read from, with its name, sha256 and size, from the
  capture's own record beside it (``<key>.capture.json``, :class:`CaptureMeta`);
* a kept upload: the name it had on the person's computer (remembered beside the kept copy);
* any other file (the demo, a path given to the CLI): its own name.

The study's identity stays the sha256 of the RDML the engine read; these names are only shown.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

MAX_NAME = 200
#: How many file names one line shows before "and N more files".
SHOWN = 3


@dataclass(frozen=True)
class InputFile:
    """One file the person opened.

    Attributes:
        name: Its name as the person knows it.
        sha256: Its content hash (``""`` when not known).
        bytes: Its size (``None`` when not known).
        role: What it held (``amplification``, ``cq``, ``melt`` ... for an export's file;
            ``rdml`` for an RDML file).
    """

    name: str
    sha256: str = ""
    bytes: int | None = None
    role: str = "rdml"


def _name_file(kept: Path) -> Path | None:
    """Where a kept file's original name is written (the same places ``web.views`` uses)."""
    if kept.parent.name == "studio-inputs":
        return kept.parent.parent / "studio-input-names" / kept.name
    if kept.parent.name == "capture" and kept.parent.parent.name == "imports":
        return kept.parent / f"{kept.name}.name"
    return None


def known_name(path: str | Path) -> str:
    """A kept file's name as the person knows it (its own name when none was remembered)."""
    file = Path(path)
    target = _name_file(file)
    if target is not None:
        try:
            name = target.read_text(encoding="utf-8").strip()[:MAX_NAME]
        except OSError:
            name = ""
        if name:
            return name
    return file.name


def capture_record(path: str | Path) -> dict | None:
    """The capture record of an RDML file qPilot built from an export (``None`` otherwise)."""
    file = Path(path)
    if file.parent.name != "capture" or file.suffix != ".rdml":
        return None
    record = file.with_name(f"{file.stem}.capture.json")
    try:
        meta = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta, dict) and isinstance(meta.get("sources"), list) else None


def input_files(path: str | Path | None, *, hashes: bool = True) -> list[InputFile]:
    """The files behind a kept input, by the person's names (``[]`` without a path).

    ``hashes=False`` leaves out an RDML file's own sha256 (an export's files keep theirs).
    """
    if path is None:
        return []
    file = Path(path)
    meta = capture_record(file)
    if meta is not None:
        out = []
        for source in meta["sources"]:
            if not isinstance(source, dict) or not source.get("name"):
                continue
            size = source.get("bytes")
            out.append(
                InputFile(
                    name=str(source["name"])[:MAX_NAME],
                    sha256=str(source.get("sha256") or ""),
                    bytes=int(size) if isinstance(size, int) else None,
                    role=str(source.get("role") or "plate"),
                )
            )
        if out:
            return out
    sha = _sha256(file) if hashes else ""
    return [InputFile(name=known_name(file), sha256=sha, bytes=_size(file))]


def is_converted(path: str | Path | None) -> bool:
    """Whether the input is an RDML file qPilot built from an instrument export."""
    return path is not None and capture_record(path) is not None


def input_label(path: str | Path | None) -> str | None:
    """The input's files in one line: ``run1.csv, run1 Cq.csv`` or ``a.csv and 4 more files``."""
    names = [f.name for f in input_files(path, hashes=False)]
    if not names:
        return None
    if len(names) <= SHOWN:
        return ", ".join(names)
    return f"{', '.join(names[: SHOWN - 1])} and {len(names) - SHOWN + 1} more files"


def _sha256(path: Path) -> str:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


def _size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


__all__ = [
    "InputFile",
    "capture_record",
    "input_files",
    "input_label",
    "is_converted",
    "known_name",
]
