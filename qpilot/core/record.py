"""The Analysis Record: one folder (or zip) that lets anyone check and re-run an analysis.

Domain-agnostic apart from :func:`rerun`, which imports the qPCR plugin lazily (documented, the
same pattern as ``StudyStore.ensure_study``). A record contains::

    input.rdml          the input file, byte for byte (when it is known)
    results.json  cards.json  facts.json  grid.csv  decisions.jsonl  pending.jsonl
    design.json         how the groups were defined
    choices.json        the primary analysis choices, the conclusion rule, each card's decision
    versions.json       python, platform, qpilot version and git commit, vendored method commit
    record.json         record id, chain head, timestamps (not part of the determinism check)
    CHECKSUMS.sha256    sha256 of every other file; record_id = sha256 of this file

The record is **tamper-evident, not tamper-proof**: ``verify`` detects any changed file and the
first broken link in the decision chain, but it cannot prove who made a record.
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from pydantic import BaseModel

from qpilot import __version__
from qpilot.core.store import (
    StudyStore,
    _apply_entry,
    atomic_write,
    dump_json,
    entry_hash,
    pending_after,
    read_entries,
    sha256_file,
)
from qpilot.schemas import DecisionCard, DecisionEntry, StudyResult

DECISION_FIELDS = ("status", "decision", "reason", "decided_by", "decided_at")

CHECKSUMS = "CHECKSUMS.sha256"
WORKSPACE_FILES = (
    "results.json",
    "cards.json",
    "facts.json",
    "grid.csv",
    "decisions.jsonl",
    "pending.jsonl",
    "ai_calls.jsonl",
    "harness_scorecard.json",
)
MAX_UNZIPPED_BYTES = 1 << 30
MAX_MEMBERS = 10_000
_REPO = Path(__file__).resolve().parents[2]


class RecordError(ValueError):
    """A record that cannot be written, unpacked or re-run safely."""


class RecordInfo(BaseModel):
    """What :func:`write_record` produced."""

    record_dir: str
    record_id: str
    chain_head: str
    n_files: int
    input_included: bool


class VerifyReport(BaseModel):
    """Outcome of :func:`verify`; ``ok`` only when nothing failed."""

    ok: bool
    changed: list[str] = []
    missing: list[str] = []
    unlisted: list[str] = []
    chain_broken_at: int | None = None
    inconsistent: list[str] = []
    n_entries: int = 0

    def summary(self) -> str:
        """One human-readable line per problem, or ``OK``."""
        if self.ok:
            return f"OK; decision chain: {self.n_entries} entries, intact"
        lines = [f"changed: {name}" for name in self.changed]
        lines += [f"missing: {name}" for name in self.missing]
        lines += [f"not in checksums: {name}" for name in self.unlisted]
        if self.chain_broken_at is not None:
            lines.append(f"decision chain broken at entry {self.chain_broken_at}")
        lines += [f"does not match the decision chain: {item}" for item in self.inconsistent]
        return "\n".join(lines)


def _vendored_commit() -> str:
    note = _REPO / "qpilot" / "vendor" / "rdmlpython" / "README_VENDOR.md"
    if note.exists():
        found = re.search(r"\b([0-9a-f]{40})\b", note.read_text(encoding="utf-8"))
        if found:
            return found.group(1)
    return "unknown"


def _git_commit() -> str:
    head = _REPO / ".git" / "HEAD"
    try:
        ref = head.read_text().strip()
        if ref.startswith("ref: "):
            ref_path = _REPO / ".git" / ref[5:]
            if ref_path.exists():
                return ref_path.read_text().strip()
            packed = _REPO / ".git" / "packed-refs"
            for line in packed.read_text().splitlines() if packed.exists() else []:
                if line.endswith(ref[5:]):
                    return line.split()[0]
            return "unknown"
        return ref
    except OSError:
        return "unknown"


def versions() -> dict[str, str]:
    """Software versions that produced a record (no timestamps, so the file is stable)."""
    return {
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.machine()}",
        "qpilot": __version__,
        "qpilot_git": _git_commit(),
        "rdmlpython_vendored": _vendored_commit(),
    }


def _choices(result: StudyResult, store: StudyStore, study_id: str) -> dict:
    cards = store.cards(study_id)
    return {
        "conclusion_rule": result.conclusion_rule,
        "primary_refs": list(result.design.refs_primary),
        "group_cut": result.design.cut,
        "cards": {
            c.id: {
                "recommended": c.recommended,
                "decision": c.decision,
                "decided_by": c.decided_by,
                "status": c.status,
            }
            for c in cards
        },
    }


def _write_checksums(record_dir: Path) -> str:
    names = sorted(
        p.relative_to(record_dir).as_posix()
        for p in record_dir.rglob("*")
        if p.is_file() and p.name != CHECKSUMS
    )
    text = "".join(f"{sha256_file(record_dir / n)}  {n}\n" for n in names)
    atomic_write(record_dir / CHECKSUMS, text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_record(
    store: StudyStore,
    study_id: str,
    out_dir: str | Path,
    rdml_path: str | Path | None = None,
    include_input: bool = True,
) -> RecordInfo:
    """Copy a study's workspace into ``out_dir`` and add design, choices, versions, checksums.

    With ``include_input=False`` the raw input file (which holds sample names and curves) is
    left out: the record can still be verified but not re-run.
    """
    workspace = store.workspace(study_id)
    result = store.get(study_id)
    record_dir = Path(out_dir)
    record_dir.mkdir(parents=True, exist_ok=True)
    if any(record_dir.iterdir()):
        raise RecordError(f"record directory is not empty: {record_dir}")
    for name in WORKSPACE_FILES:
        src = workspace / name
        if src.exists():
            shutil.copyfile(src, record_dir / name)
    source = Path(rdml_path) if rdml_path is not None else store.source(study_id)
    included = False
    if source is not None and include_input:
        if sha256_file(source) != result.input_sha256:
            raise RecordError("the input file does not match the study (sha256 differs)")
        shutil.copyfile(source, record_dir / "input.rdml")
        included = True
    atomic_write(record_dir / "design.json", dump_json(result.design.model_dump(mode="json")))
    atomic_write(record_dir / "choices.json", dump_json(_choices(result, store, study_id)))
    atomic_write(record_dir / "versions.json", dump_json(versions()))
    head = store.chain_head(study_id)
    meta = {
        "study_id": study_id,
        "input_sha256": result.input_sha256,
        "chain_head": head,
        "input_included": included,
        "written_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "Tamper-evident, not tamper-proof. Research use only.",
    }
    atomic_write(record_dir / "record.json", dump_json(meta))
    record_id = _write_checksums(record_dir)
    n_files = sum(1 for p in record_dir.rglob("*") if p.is_file())
    return RecordInfo(
        record_dir=str(record_dir),
        record_id=record_id,
        chain_head=head,
        n_files=n_files,
        input_included=included,
    )


def verify_chain(entries: list[DecisionEntry], root: str) -> int | None:
    """Return the ``seq`` of the first entry whose link or hash is wrong, or None if intact."""
    prev = root
    for position, entry in enumerate(entries, start=1):
        if entry.seq != position or entry.prev_hash != prev or entry.hash != entry_hash(entry):
            return position
        prev = entry.hash
    return None


def _read_checksums(record_dir: Path) -> dict[str, str]:
    """Parse CHECKSUMS.sha256; ``RecordError`` on a malformed line."""
    listed = {}
    for line in (record_dir / CHECKSUMS).read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, sep, name = line.partition("  ")
            if not sep or len(digest) != 64:
                raise RecordError(f"malformed line in {CHECKSUMS}")
            listed[name] = digest
    return listed


def verify(record_dir: str | Path) -> VerifyReport:
    """Check every file against ``CHECKSUMS.sha256`` and walk the decision chain."""
    record_dir = Path(record_dir)
    if not (record_dir / CHECKSUMS).exists():
        return VerifyReport(ok=False, missing=[CHECKSUMS])
    try:
        listed = _read_checksums(record_dir)
    except (RecordError, OSError, UnicodeDecodeError):
        return VerifyReport(ok=False, inconsistent=[f"{CHECKSUMS} unreadable"])
    present = {
        p.relative_to(record_dir).as_posix()
        for p in record_dir.rglob("*")
        if p.is_file() and p.name != CHECKSUMS
    }
    missing = sorted(n for n in listed if n not in present)
    unlisted = sorted(n for n in present if n not in listed)
    changed = sorted(
        n for n, d in listed.items() if n in present and sha256_file(record_dir / n) != d
    )
    broken = None
    n_entries = 0
    try:
        root = StudyResult.model_validate_json((record_dir / "results.json").read_text())
        entries = read_entries(record_dir / "decisions.jsonl")
        n_entries = len(entries)
        broken = verify_chain(entries, root.input_sha256)
    except (OSError, ValueError):
        broken = 1
        entries = []
    inconsistent = _consistency(record_dir, entries) if broken is None else []
    ok = not (missing or unlisted or changed or inconsistent) and broken is None
    return VerifyReport(
        ok=ok,
        changed=changed,
        missing=missing,
        unlisted=unlisted,
        chain_broken_at=broken,
        inconsistent=inconsistent,
        n_entries=n_entries,
    )


def _consistency(record_dir: Path, entries: list[DecisionEntry]) -> list[str]:
    """What in cards.json, choices.json and pending.jsonl the decision chain does not support.

    Each card's state is rebuilt by replaying the chain with the store's own logic and compared
    field by field; the card sets must match and every card the chain mentions must exist.
    Unreadable files are reported, never raised.
    """
    problems: list[str] = []
    try:
        cards = json.loads((record_dir / "cards.json").read_text())
        by_id = {c["id"]: c for c in cards}
    except (OSError, ValueError, TypeError, KeyError):
        return ["cards.json unreadable"]
    expected: dict[str, dict] = {}
    for card_id, card in by_id.items():
        blank = {f: None for f in DECISION_FIELDS} | {"status": "open"}
        try:
            state = DecisionCard.model_validate({**card, **blank})
        except (ValueError, TypeError):
            return [*problems, "cards.json unreadable"]
        for entry in entries:
            if entry.card_id == card_id:
                state = _apply_entry(state, entry)
        expected[card_id] = {f: getattr(state, f) for f in DECISION_FIELDS}
        if {f: card.get(f) for f in DECISION_FIELDS} != expected[card_id]:
            problems.append(f"cards.json {card_id}")
    problems += [
        f"cards.json has no card {cid}" for cid in sorted({e.card_id for e in entries} - set(by_id))
    ]
    choices_path = record_dir / "choices.json"
    if choices_path.exists():
        try:
            choices = json.loads(choices_path.read_text())["cards"]
            items = sorted(choices.items())
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return [*problems, "choices.json unreadable"]
        if set(choices) != set(by_id):
            problems.append("choices.json lists different cards from cards.json")
        for card_id, choice in items:
            want = expected.get(card_id)
            fields = ("status", "decision", "decided_by")
            if want is None or not isinstance(choice, dict):
                continue
            if {f: choice.get(f) for f in fields} != {f: want[f] for f in fields}:
                problems.append(f"choices.json {card_id}")
    pending_path = record_dir / "pending.jsonl"
    if pending_path.exists():
        try:
            recorded = [e.seq for e in read_entries(pending_path)]
        except (OSError, ValueError):
            return [*problems, "pending.jsonl unreadable"]
        accepted = (
            [e.seq for e in pending_after(entries)],
            [e.seq for e in pending_after(entries, legacy=True)],
        )
        if recorded not in accepted:
            problems.append("pending.jsonl")
    return problems


def zip_record(record_dir: str | Path, zip_path: str | Path | None = None) -> Path:
    """Zip a record folder with members in a fixed order."""
    record_dir = Path(record_dir)
    target = Path(zip_path) if zip_path else record_dir.with_suffix(".zip")
    files = sorted(p for p in record_dir.rglob("*") if p.is_file())
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(record_dir).as_posix(), (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes())
    return target


def unzip_record(zip_path: str | Path, target_dir: str | Path) -> Path:
    """Unpack a record zip defensively: no absolute paths, ``..``, links, or zip bombs."""
    target = Path(target_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    try:
        archive = zipfile.ZipFile(zip_path)
    except FileNotFoundError as err:
        raise RecordError(f"no such record zip: {zip_path}") from err
    except zipfile.BadZipFile as err:
        raise RecordError(f"not a zip file: {zip_path}") from err
    with archive as zf:
        members = zf.infolist()
        if len(members) > MAX_MEMBERS:
            raise RecordError("too many files in the record zip")
        if sum(m.file_size for m in members) > MAX_UNZIPPED_BYTES:
            raise RecordError("record zip would unpack to more than 1 GB")
        for member in members:
            name = PurePosixPath(member.filename)
            is_link = (member.external_attr >> 16) & 0o170000 == 0o120000
            if name.is_absolute() or ".." in name.parts or "\\" in member.filename or is_link:
                raise RecordError(f"unsafe path in record zip: {member.filename!r}")
            dest = (target / name).resolve()
            if not dest.is_relative_to(target):
                raise RecordError(f"unsafe path in record zip: {member.filename!r}")
        for member in members:
            if member.is_dir():
                continue
            dest = target / PurePosixPath(member.filename)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
    children = [c for c in target.iterdir() if c.name != "__MACOSX"]
    if not (target / CHECKSUMS).exists() and len(children) == 1 and children[0].is_dir():
        return children[0]  # a zip made of the record folder itself (zip -r rec.zip rec)
    return target


class RerunReport(BaseModel):
    """What a re-run regenerated and which of the record's files it reproduced."""

    out_dir: str
    same: bool
    compared: list[str]
    differs: list[str]
    build_note: str = ""


STRUCTURE_SKIP = (*DECISION_FIELDS, "autonomy", "effective_autonomy")


def _card_structure(cards: list[dict]) -> str:
    """Cards without who-decided-what: what a re-run must reproduce."""
    stripped = [{k: v for k, v in c.items() if k not in STRUCTURE_SKIP} for c in cards]
    return dump_json(sorted(stripped, key=lambda c: c.get("id", "")))


def rerun_compare(record_dir: str | Path, out_dir: str | Path | None = None) -> RerunReport:
    """Re-run from ``input.rdml`` and compare results, facts, grid and card structure.

    Lazily imports ``qpilot.qpcr.study.run_study`` (documented exception to the core/plugin
    rule). ``results.json`` and ``facts.json`` must match byte for byte, ``grid.csv`` too when
    the record has one, and the cards must match apart from decisions.
    """
    record_dir = Path(record_dir)
    results_path = rerun(record_dir, out_dir)
    out = results_path.parent
    from qpilot.core.store import _grid_csv
    from qpilot.qpcr.study import run_study  # documented lazy import

    regenerated = run_study(record_dir / "input.rdml")
    result, cards = regenerated[0], regenerated[1]
    grid = regenerated[2] if len(regenerated) > 2 else None
    facts = {fid: f.model_dump(mode="json") for fid, f in result.facts.items()}
    atomic_write(out / "facts.json", dump_json(facts))
    if grid is not None:
        atomic_write(out / "grid.csv", _grid_csv(grid))
    atomic_write(out / "cards.json", dump_json([c.model_dump(mode="json") for c in cards]))
    compared, differs = [], []
    for name in ("results.json", "facts.json", "grid.csv"):
        if (record_dir / name).exists() and (out / name).exists():
            compared.append(name)
            if (record_dir / name).read_bytes() != (out / name).read_bytes():
                differs.append(name)
    compared.append("cards.json (structure)")
    try:
        mine = _card_structure(json.loads((record_dir / "cards.json").read_text()))
    except (OSError, ValueError, AttributeError):
        mine = ""
    if mine != _card_structure([c.model_dump(mode="json") for c in cards]):
        differs.append("cards.json (structure)")
    note = ""
    try:
        made_with = json.loads((record_dir / "versions.json").read_text()).get("qpilot_git")
        if made_with and made_with != versions()["qpilot_git"]:
            now = versions()["qpilot_git"]
            note = f"record made with qpilot {made_with[:12]}, re-run with {now[:12]}"
    except (OSError, ValueError):
        pass
    return RerunReport(
        out_dir=str(out), same=not differs, compared=compared, differs=differs, build_note=note
    )


def rerun(record_dir: str | Path, out_dir: str | Path | None = None) -> Path:
    """Re-run the analysis from the record's input; return the regenerated ``results.json``.

    Lazily imports ``qpilot.qpcr.study.run_study`` (documented exception to the core/plugin
    rule). :func:`rerun_compare` also checks facts, grid and cards.
    """
    record_dir = Path(record_dir)
    source = record_dir / "input.rdml"
    if not source.exists():
        raise RecordError("this record does not include its input file, so it cannot be re-run")
    expected = StudyResult.model_validate_json((record_dir / "results.json").read_text())
    if sha256_file(source) != expected.input_sha256:
        raise RecordError("input.rdml does not match results.json (sha256 differs)")
    from qpilot.qpcr.study import run_study  # documented lazy import

    result = run_study(source)[0]
    out = Path(out_dir) if out_dir else record_dir.parent / f"{record_dir.name}-rerun"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "results.json"
    atomic_write(path, dump_json(result.model_dump(mode="json")))
    return path


def rerun_matches(record_dir: str | Path, out_dir: str | Path | None = None) -> bool:
    """True when a re-run reproduces results, facts, grid and card structure."""
    return rerun_compare(record_dir, out_dir).same


def summary_json(info: RecordInfo) -> str:
    """Compact JSON for CLI output."""
    return json.dumps(info.model_dump(), sort_keys=True)


__all__ = [
    "RecordError",
    "RecordInfo",
    "VerifyReport",
    "rerun",
    "rerun_matches",
    "summary_json",
    "unzip_record",
    "verify",
    "verify_chain",
    "versions",
    "write_record",
    "zip_record",
]
