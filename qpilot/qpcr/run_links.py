"""Run files a person linked to the plates of a study's input file (Run Gate's G-INSTR).

A study's own file is RDML, which names the instrument and the run date at most. The run file
the instrument wrote (a QuantStudio or StepOne ``.eds``, a QuantStudio results export, CFX run
information) says whether the run completed, when it was paused and which calibrations were past
their expiry. A person links one to a plate in the Controls section; G-INSTR then reads it in
the plate's place (:func:`qpilot.qpcr.gate_rules.with_linked`).

Links are kept per **input file** (``<store>/run_links/<input sha256>.json``), not per analysis:
every analysis of the same file reads the same links (a Studio session moves to a new analysis
when a person leaves wells out, and the run file still describes the same plate). The file a
link names is kept by content in the page's kept-inputs folder and checked by its sha256 when it
is read: a link whose file is gone or changed is said, never read. Each link says that a person
made it (``by: human``, set by the server) and when. Serial numbers never enter a link: the name
kept is the file's name with the run's identity strings blanked out.

Deterministic JSON, written atomically. No model call and no network.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from qpilot.core.store import atomic_write, dump_json, sha256_file
from qpilot.qpcr.instrument_context import InstrumentFileError, RunContext, read_run_context

LINKS_DIR = "run_links"
SCHEMA = "qpilot.run_links/1"
MAX_LINKS = 2000
SHA256 = re.compile(r"^[0-9a-f]{64}\Z")
KEPT_NAME = re.compile(r"^[0-9a-f]{24}\.[a-z]{2,5}\Z")
Problem = Literal["missing", "changed", "unreadable"]

_lock = threading.Lock()


class RunLinkError(ValueError):
    """A link that cannot be made or read (a bad input id, plate or kept file name)."""


class RunLink(BaseModel):
    """One plate's linked run file."""

    plate: str = Field(min_length=1, max_length=200)
    file: str = Field(description="The kept file's name in the kept-inputs folder.")
    sha256: str
    name: str = Field(max_length=200, description="The file's name, serials blanked out.")
    kind: str = Field(max_length=40, description="What the file is (RunContext.source_kind).")
    by: Literal["human"] = "human"
    at: str = Field(max_length=40, description="When the person linked it (ISO 8601, UTC).")


def links_path(root: str | Path, input_sha256: str) -> Path:
    """Where the links of one input file are kept."""
    if not SHA256.match(input_sha256 or ""):
        raise RunLinkError("not an input file's sha256")
    return Path(root) / LINKS_DIR / f"{input_sha256}.json"


def load(root: str | Path, input_sha256: str) -> dict[str, RunLink]:
    """The links of one input file, plate -> link (``{}`` when none, or the file is unreadable)."""
    path = links_path(root, input_sha256)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, Mapping) or data.get("schema") != SCHEMA:
        return {}
    out: dict[str, RunLink] = {}
    for entry in data.get("links") or []:
        try:
            link = RunLink.model_validate(entry)
        except ValidationError:
            continue
        if KEPT_NAME.match(link.file) and SHA256.match(link.sha256):
            out[link.plate] = link
    return out


def version(root: str | Path, input_sha256: str) -> str:
    """A short digest of the links file (``""`` when there is none), for caches."""
    try:
        raw = links_path(root, input_sha256).read_bytes()
    except (OSError, RunLinkError):
        return ""
    return hashlib.sha256(raw).hexdigest()[:16]


def _write(root: str | Path, input_sha256: str, links: Mapping[str, RunLink]) -> None:
    path = links_path(root, input_sha256)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema": SCHEMA,
        "input_sha256": input_sha256,
        "links": [links[p].model_dump(mode="json") for p in sorted(links)],
    }
    atomic_write(path, dump_json(data))


def link(root: str | Path, input_sha256: str, entry: RunLink) -> dict[str, RunLink]:
    """Link ``entry``'s run file to its plate (replacing that plate's earlier link)."""
    if not KEPT_NAME.match(entry.file) or not SHA256.match(entry.sha256):
        raise RunLinkError("a link names a kept run file by its content")
    with _lock:
        links = load(root, input_sha256)
        if entry.plate not in links and len(links) >= MAX_LINKS:
            raise RunLinkError(f"at most {MAX_LINKS} plates of one file can be linked")
        links[entry.plate] = entry
        _write(root, input_sha256, links)
        return links


def unlink(root: str | Path, input_sha256: str, plate: str) -> RunLink | None:
    """Remove a plate's link; the link removed, or ``None`` when the plate had none."""
    with _lock:
        links = load(root, input_sha256)
        gone = links.pop(plate, None)
        if gone is not None:
            _write(root, input_sha256, links)
        return gone


def read_linked(
    links: Mapping[str, RunLink], folder: str | Path
) -> tuple[dict[str, RunContext], dict[str, Problem]]:
    """What each linked file says (plate -> context), and the plates whose file cannot be read.

    A file that is gone is ``missing``; one whose bytes no longer match the link's sha256 is
    ``changed``; one the reader refuses is ``unreadable``. None of them is read in its place.
    """
    contexts: dict[str, RunContext] = {}
    problems: dict[str, Problem] = {}
    for plate, entry in links.items():
        path = Path(folder) / entry.file
        if not path.is_file():
            problems[plate] = "missing"
            continue
        try:
            if sha256_file(path) != entry.sha256:
                problems[plate] = "changed"
                continue
            contexts[plate] = read_run_context(path)
        except (InstrumentFileError, OSError, ValueError):
            problems[plate] = "unreadable"
    return contexts, problems
