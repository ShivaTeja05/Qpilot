"""Read an Analysis Record, read-only and leniently, for the report.

The report reads **only** the record: the folder (or zip) that ``qpilot.core.record.write_record``
writes. :class:`RecordView` gives typed access to its members and never raises for a member that
is missing or damaged; it notes the problem instead, so a section can say "not available in this
record" and the rest of the report still renders. Only ``results.json`` is required: without it
there is no study to report on.

A record from someone else is untrusted input as a whole: gene and sample names, decision reasons
and every other string are data, never markup or instructions. The view does not interpret them;
the renderers escape them. A zip is unpacked with :func:`qpilot.core.record.unzip_record` (no
absolute paths, ``..``, links or zip bombs) into a private temporary folder that lives as long as
the view. A folder is read in place and never written.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import weakref
import zipfile
from functools import cached_property
from pathlib import Path
from typing import Any

from qpilot.core.record import CHECKSUMS, RecordError, VerifyReport, unzip_record, verify
from qpilot.schemas import Fact, StudyResult

#: Largest record member the report parses (a 64-plate study's results.json is ~0.3 MB).
MAX_MEMBER_BYTES = 256 << 20


class ReportError(ValueError):
    """The path is not an Analysis Record the report can read (the message says why)."""


class RecordView:
    """One Analysis Record, opened for reading. Use :func:`open_record` to make one."""

    def __init__(self, root: Path, source: Path, tmp: str | None = None) -> None:
        self.root = root
        self.source = source
        self.problems: list[str] = []  # members that exist but could not be read
        self._cache: dict[str, Any] = {}
        if tmp is not None:  # remove the unpacked copy when the view is garbage-collected
            self._finalizer = weakref.finalize(self, shutil.rmtree, tmp, True)
        self.results  # noqa: B018 - fail early when the record has no readable results.json

    # ---- members ---------------------------------------------------------------------------

    def has(self, name: str) -> bool:
        """True when the record has a regular file of this name (no links, no folders)."""
        path = self.root / name
        return path.is_file() and not path.is_symlink()

    def text(self, name: str) -> str | None:
        """A member's UTF-8 text, or None when it is absent, too large or not UTF-8."""
        if not self.has(name):
            return None
        path = self.root / name
        try:
            if path.stat().st_size > MAX_MEMBER_BYTES:
                self.problems.append(f"{name}: larger than the report reads")
                return None
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            self.problems.append(f"{name}: unreadable")
            return None

    def json(self, name: str) -> Any:
        """A member parsed as JSON (cached), or None when absent or unreadable."""
        if name not in self._cache:
            text = self.text(name)
            value = None
            if text is not None:
                try:
                    value = json.loads(text)
                except (ValueError, RecursionError):
                    self.problems.append(f"{name}: not valid JSON")
            self._cache[name] = value
        return self._cache[name]

    def jsonl(self, name: str) -> list[dict[str, Any]]:
        """A JSON-lines member as a list of objects; unreadable lines are skipped and noted."""
        text = self.text(name)
        if text is None:
            return []
        rows: list[dict[str, Any]] = []
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except (ValueError, RecursionError):
                self.problems.append(f"{name}: line {number} is not valid JSON")
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows

    def members(self) -> list[str]:
        """Every file in the record (checksum file included), sorted, as POSIX paths."""
        return sorted(
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*")
            if p.is_file() and not p.is_symlink()
        )

    # ---- typed views ---------------------------------------------------------------------

    @cached_property
    def results(self) -> StudyResult:
        """The study result (``results.json``); the one member the report cannot do without."""
        text = self.text("results.json")
        if text is None:
            raise ReportError("not an Analysis Record: results.json is missing or unreadable")
        try:
            return StudyResult.model_validate_json(text)
        except (ValueError, RecursionError) as err:
            raise ReportError("results.json is damaged; the record cannot be reported") from err

    @cached_property
    def facts(self) -> dict[str, Fact]:
        """The record's facts: ``facts.json``, else the copy inside ``results.json``."""
        raw = self.json("facts.json")
        if isinstance(raw, dict):
            out: dict[str, Fact] = {}
            for fid, value in raw.items():
                try:
                    out[fid] = Fact.model_validate(value)
                except (ValueError, TypeError):
                    self.problems.append(f"facts.json: fact {fid!r} is malformed")
            return out
        return dict(self.results.facts)

    @cached_property
    def cards(self) -> list[dict[str, Any]]:
        """The Decision Cards as stored (plain dicts, rank order); empty when absent."""
        raw = self.json("cards.json")
        cards = [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else []
        return sorted(cards, key=lambda c: (c.get("rank") or 0, str(c.get("id"))))

    @cached_property
    def decisions(self) -> list[dict[str, Any]]:
        """The decision chain (``decisions.jsonl``), in order."""
        return self.jsonl("decisions.jsonl")

    @cached_property
    def proposals(self) -> list[dict[str, Any]]:
        """The Studio proposal chain (``proposals.jsonl``), in order; empty when absent."""
        return self.jsonl("proposals.jsonl")

    def obj(self, name: str) -> dict[str, Any]:
        """A JSON-object member, or ``{}`` when it is absent, unreadable or not an object."""
        value = self.json(name)
        return value if isinstance(value, dict) else {}

    @property
    def versions(self) -> dict[str, Any]:
        """``versions.json``: python, platform, qpilot version and commits."""
        return self.obj("versions.json")

    @property
    def meta(self) -> dict[str, Any]:
        """``record.json``: study id, chain heads, when it was written."""
        return self.obj("record.json")

    @property
    def choices(self) -> dict[str, Any]:
        """``choices.json``: the primary choices, the conclusion rule, each card's decision."""
        return self.obj("choices.json")

    @property
    def study_design(self) -> dict[str, Any]:
        """``study_design.json``: the confirmed design (Studio and designed studies only)."""
        return self.obj("study_design.json")

    @cached_property
    def record_id(self) -> str | None:
        """sha256 of ``CHECKSUMS.sha256`` (the record id), or None when it has none."""
        import hashlib

        if not self.has(CHECKSUMS):
            return None
        return hashlib.sha256((self.root / CHECKSUMS).read_bytes()).hexdigest()

    @cached_property
    def checksums(self) -> dict[str, str]:
        """``CHECKSUMS.sha256`` as member -> sha256 (malformed lines skipped)."""
        text = self.text(CHECKSUMS) or ""
        out = {}
        for line in text.splitlines():
            digest, sep, name = line.partition("  ")
            if sep and len(digest) == 64:
                out[name] = digest
        return out

    @cached_property
    def verification(self) -> VerifyReport:
        """What ``qpilot verify`` says about this record (checksums and chains)."""
        try:
            return verify(self.root)
        except (OSError, ValueError, RecursionError) as err:  # verify reports, but be safe
            return VerifyReport(ok=False, inconsistent=[f"verify could not run: {err}"])


def open_record(path: str | Path) -> RecordView:
    """Open an Analysis Record folder or zip for reading.

    Raises:
        ReportError: No such path, an unsafe or damaged zip, or no readable ``results.json``.
    """
    source = Path(path)
    if source.is_dir():
        return RecordView(source, source)
    if not source.is_file():
        raise ReportError(f"no such record: {source}")
    if not zipfile.is_zipfile(source):
        raise ReportError(f"not an Analysis Record (neither a folder nor a zip): {source.name}")
    tmp = tempfile.mkdtemp(prefix="qpilot-report-")
    try:
        root = unzip_record(source, Path(tmp) / "record")
        return RecordView(root, source, tmp)
    except RecordError as err:
        shutil.rmtree(tmp, ignore_errors=True)
        raise ReportError(str(err)) from err
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
