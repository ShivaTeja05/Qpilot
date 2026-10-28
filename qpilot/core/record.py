"""The Analysis Record: one folder (or zip) that lets anyone check and re-run an analysis.

Domain-agnostic apart from :func:`rerun`, which imports the qPCR plugin lazily (documented, the
same pattern as ``StudyStore.ensure_study``). A record contains::

    input.rdml          the input file, byte for byte (when it is known)
    results.json  cards.json  facts.json  grid.csv  decisions.jsonl  pending.jsonl
    design.json         how the groups were defined
    study_design.json   the confirmed StudyDesign (designed studies only; rerun uses it)
    proposals.jsonl     what the AI proposed and what a person did, hash-chained (Studio)
    quarantine.json     the free text the proposals cite (pseudonyms in a shared record)
    trace_cards.json    the cards opened on demand (Trace's set-aside cards), when there are any
    evidence.json  run_context.json  instrument_refs.json   other features' artifact files
    choices.json        the primary analysis choices, the conclusion rule, each card's decision
    versions.json       python, platform, qpilot version and git commit, vendored method commit
    record.json         record id, chain heads, timestamps (not part of the determinism check)
    CHECKSUMS.sha256    sha256 of every other file; record_id = sha256 of this file

``proposals.jsonl`` and ``quarantine.json`` come from the input's Studio session
(``sessions/<input_sha256>/``), the one place Studio writes them; a copy in the study's own
workspace is used only when the session has none. The pseudonym key (``.keys/``) is never
copied.

The artifact files (``store.ARTIFACT_FILES``) are copied when present. In a shared record their
names (the string values under :data:`SHARE_NAME_KEYS`, and the keys of the mappings under
:data:`SHARE_NAME_MAPS`) are replaced by the same keyed pseudonyms the quarantine uses.

The record is **tamper-evident, not tamper-proof**: ``verify`` detects any changed file and the
first broken link in the decision and proposal chains, but it cannot prove who made a record.
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
import shutil
import zipfile
import zlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel

from qpilot import __version__
from qpilot.core.firewall import (
    QUARANTINE_FILE,
    Quarantine,
    QuarantineError,
    quarantine_json,
    read_quarantine,
)
from qpilot.core.proposals import (
    PROPOSALS_FILE,
    chain_lines,
    first_altered_line,
    replay,
    verify_proposal_chain,
)
from qpilot.core.pseudonym import TOKEN, Pseudonymiser
from qpilot.core.store import (
    ARTIFACT_FILES,
    DECISION_FIELDS,
    DESIGN_FILE,
    ON_DEMAND_FILE,
    ON_DEMAND_KINDS,
    REVIEW_CARD,
    REVIEW_KIND,
    SESSIONS_DIR,
    StudyStore,
    _lines,
    atomic_write,
    card_entries,
    dump_json,
    entry_hash,
    entry_line,
    pending_after,
    read_entries,
    replay_cards,
    sha256_file,
    study_key,
)
from qpilot.schemas import DecisionCard, DecisionEntry, StudyResult
from qpilot.schemas_studio import ProposalEntry, StudyDesign

CHECKSUMS = "CHECKSUMS.sha256"
#: ``DesignSummary.note`` of a study whose groups come from a confirmed design.
GROUPS_NOTE = "groups from the confirmed design"
WORKSPACE_FILES = (
    "results.json",
    "cards.json",
    "facts.json",
    "grid.csv",
    "decisions.jsonl",
    "pending.jsonl",
    "ai_calls.jsonl",
    "harness_scorecard.json",
    "attempts.jsonl",
    "autonomy.json",
    DESIGN_FILE,
    *ARTIFACT_FILES,
)
SESSION_FILES = (PROPOSALS_FILE, QUARANTINE_FILE)  # from the session; never .keys/
MAX_UNZIPPED_BYTES = 1 << 30
MAX_MEMBERS = 10_000
# Files an operating system adds to a folder by itself; verify neither lists nor counts them.
OS_METADATA = re.compile(r"(^|/)(\.DS_Store|Thumbs\.db|desktop\.ini|\._[^/]*)$|(^|/)__MACOSX/")
#: In a shared record, the string values under these keys (at any depth of an artifact file,
#: also inside lists) name a sample, a well, a plate (run) or an instrument, and become
#: pseudonyms. Features that write artifact files keep their names under these keys.
SHARE_NAME_KEYS = frozenset(
    {
        "sample",
        "samples",
        "well",
        "wells",
        "well_key",
        "well_keys",
        "plate",
        "plates",
        "run_id",
        "run_ids",
        "serial",
        "block_serial",
        "cover_serial",
        "optical_head_serial",
        "aliases",
        "source_file",
        "operator",
    }
)
#: ... and the keys of a mapping under one of these keys are such names (a well -> flags map).
SHARE_NAME_MAPS = frozenset({"well_flags"})
NAMES_IN_SHARED = "holds names in a shared record"
_DATA_FILES = tuple(n for n in ARTIFACT_FILES if n != ON_DEMAND_FILE)  # not about decisions


def _record_files(record_dir: Path) -> set[str]:
    return {
        p.relative_to(record_dir).as_posix()
        for p in record_dir.rglob("*")
        if p.is_file()
        and p.name != CHECKSUMS
        and not OS_METADATA.search(p.relative_to(record_dir).as_posix())
    }


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
    has_proposals: bool = False
    proposal_chain_broken_at: int | None = None
    n_proposal_entries: int = 0

    def summary(self) -> str:
        """One human-readable line per problem, or ``OK``."""
        if self.ok:
            text = f"OK; decision chain: {self.n_entries} entries, intact"
            if self.has_proposals:
                text += f"; proposal chain: {self.n_proposal_entries} entries, intact"
            return text
        lines = [f"changed: {name}" for name in self.changed]
        lines += [f"missing: {name}" for name in self.missing]
        lines += [f"not in checksums: {name}" for name in self.unlisted]
        if self.chain_broken_at is not None:
            lines.append(f"decision chain broken at entry {self.chain_broken_at}")
        if self.proposal_chain_broken_at is not None:
            lines.append(f"proposal chain broken at entry {self.proposal_chain_broken_at}")
        for item in self.inconsistent:
            if item.startswith((PROPOSALS_FILE, "record.json proposals_head")):
                lines.append(f"does not match the proposal chain: {item}")
            elif item.startswith((QUARANTINE_FILE, DESIGN_FILE, *_DATA_FILES)) or item.endswith(
                NAMES_IN_SHARED
            ):
                lines.append(f"inconsistent: {item}")
            else:
                lines.append(f"does not match the decision chain: {item}")
        return "\n".join(lines)


def _map_names(data: Any, rename: Callable[[str], str]) -> Any:
    """Parsed JSON with every name (see :data:`SHARE_NAME_KEYS`) passed through ``rename``.

    Everything that is not a name is kept, so the file still reads the same way.
    """

    def names(value: Any) -> Any:
        if isinstance(value, str):
            return rename(value)
        if isinstance(value, list):
            return [names(v) for v in value]
        return walk(value)

    def walk(value: Any) -> Any:
        if isinstance(value, list):
            return [walk(v) for v in value]
        if not isinstance(value, dict):
            return value
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key in SHARE_NAME_KEYS:
                out[key] = names(item)
            elif key in SHARE_NAME_MAPS and isinstance(item, dict):
                mapped: dict[str, Any] = {}
                for name, sub in item.items():
                    new = rename(name)
                    if new in mapped:
                        raise RecordError("two names share one pseudonym; rename one of them")
                    mapped[new] = walk(sub)
                out[key] = mapped
            else:
                out[key] = walk(item)
        return out

    return walk(data)


def pseudonymise_names(data: Any, pseudonym: Callable[[str], str]) -> Any:
    """An artifact file's parsed JSON with its names replaced by their pseudonyms.

    A name is a string under one of :data:`SHARE_NAME_KEYS`, or a key of a mapping under one
    of :data:`SHARE_NAME_MAPS`; a name that already is a pseudonym is kept.

    Args:
        data: The parsed file.
        pseudonym: The workspace's keyed pseudonym function
            (``StudyStore.pseudonymiser(study_id).pseudonymise``).

    Returns:
        A new object; ``data`` is not changed.

    Raises:
        RecordError: Two names would share one pseudonym inside one mapping.
    """
    return _map_names(data, lambda name: name if TOKEN.match(name) else pseudonym(name))


def unpseudonymised_names(data: Any) -> list[str]:
    """The names in an artifact file's parsed JSON that are not pseudonyms (none when shared)."""
    found: list[str] = []

    def note(name: str) -> str:
        if not TOKEN.match(name):
            found.append(name)
        return name

    _map_names(data, note)
    return found


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
        ref = head.read_text(encoding="utf-8").strip()
        if ref.startswith("ref: "):
            ref_path = _REPO / ".git" / ref[5:]
            if ref_path.exists():
                return ref_path.read_text(encoding="utf-8").strip()
            packed = _REPO / ".git" / "packed-refs"
            for line in packed.read_text(encoding="utf-8").splitlines() if packed.exists() else []:
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
        # A study whose groups come from a confirmed design has no cut-off (its cut is 0.0).
        "group_cut": None if result.design.note == GROUPS_NOTE else result.design.cut,
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


def _copy_session(
    store: StudyStore,
    folders: tuple[Path, Path],
    record_dir: Path,
    result: StudyResult,
    share: bool,
) -> str | None:
    """Copy the proposal chain and the quarantine into a record; return the chain's head.

    Each file comes from the first folder that has it (the session, then the study's
    workspace). A shared record gets each quarantined text's pseudonym instead of the text.
    Returns None when there is no proposal chain to copy.
    """
    for name in SESSION_FILES:
        folder = next((f for f in folders if (f / name).exists()), None)
        if folder is None:
            continue
        try:
            if name == QUARANTINE_FILE and share:
                entries = Pseudonymiser(folder).pseudonymise_entries(Quarantine(folder).all())
                atomic_write(record_dir / name, quarantine_json(entries, pseudonymised=True))
            else:
                with store._locked(folder):
                    shutil.copyfile(folder / name, record_dir / name)
        except (QuarantineError, ValueError) as err:
            raise RecordError(f"{name} cannot be exported: {err}") from err
    if not (record_dir / PROPOSALS_FILE).exists():
        return None
    lines = chain_lines(record_dir / PROPOSALS_FILE)
    try:
        return ProposalEntry.model_validate_json(lines[-1]).hash if lines else result.input_sha256
    except ValueError as err:
        raise RecordError(f"{PROPOSALS_FILE} is damaged; not exporting it") from err


def write_record(
    store: StudyStore,
    study_id: str,
    out_dir: str | Path,
    rdml_path: str | Path | None = None,
    include_input: bool = True,
    share: bool = False,
) -> RecordInfo:
    """Copy a study's workspace into ``out_dir`` and add design, choices, versions, checksums.

    With ``include_input=False`` the raw input file (which holds sample names and curves) is
    left out: the record can still be verified but not re-run.

    ``share=True`` marks a record for sharing: ``quarantine.json`` carries each text's
    pseudonym (same ``text_id``) instead of the text, the artifact files carry pseudonyms for
    their names (:func:`pseudonymise_names`, the same keyed tokens), and the raw input is
    always left out. This is pseudonymisation, not anonymisation: proposal subjects and
    payloads (sample ids), card ids, run reviewers' names and every reason stay as they are
    because they are inside a hash chain, and a ``text_id`` is an unkeyed hash of the original
    text, so anyone who can guess a name can confirm it.
    """
    workspace = store.workspace(study_id)
    result = store.get(study_id)
    record_dir = Path(out_dir)
    record_dir.mkdir(parents=True, exist_ok=True)
    if any(record_dir.iterdir()):
        raise RecordError(f"record directory is not empty: {record_dir}")
    artifacts: dict[str, str] = {}
    with store._locked(workspace):  # copy a consistent workspace: no write in between
        for name in WORKSPACE_FILES:
            src = workspace / name
            if not src.exists():
                continue
            if share and name in ARTIFACT_FILES:
                artifacts[name] = src.read_text(encoding="utf-8")  # pseudonymised below
            else:
                shutil.copyfile(src, record_dir / name)
        head = store.chain_head(study_id)
        choices = _choices(result, store, study_id)
    if artifacts:  # outside the workspace lock: the key lives in the session folder
        pseudonym = store.pseudonymiser(study_id).pseudonymise
        for name, text in sorted(artifacts.items()):
            try:
                data = pseudonymise_names(json.loads(text), pseudonym)
            except (ValueError, RecursionError) as err:
                raise RecordError(f"{name} cannot be exported: {err}") from err
            atomic_write(record_dir / name, dump_json(data))
    session = store.root / SESSIONS_DIR / result.input_sha256
    proposals_head = _copy_session(store, (session, workspace), record_dir, result, share)
    if share:
        include_input = False
    source = Path(rdml_path) if rdml_path is not None else store.source(study_id)
    included = False
    if source is not None and include_input:
        if sha256_file(source) != result.input_sha256:
            raise RecordError("the input file does not match the study (sha256 differs)")
        shutil.copyfile(source, record_dir / "input.rdml")
        included = True
    atomic_write(record_dir / "design.json", dump_json(result.design.model_dump(mode="json")))
    atomic_write(record_dir / "choices.json", dump_json(choices))
    atomic_write(record_dir / "versions.json", dump_json(versions()))
    meta = {
        "study_id": study_id,
        "input_sha256": result.input_sha256,
        "chain_head": head,
        "input_included": included,
        "written_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "Tamper-evident, not tamper-proof. Research use only.",
    }
    if proposals_head is not None:
        meta["proposals_head"] = proposals_head
    if share:
        meta["shared"] = True
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
    """Check every file against ``CHECKSUMS.sha256`` and walk the decision and proposal chains.

    The proposal chain (when the record has one) is checked on its own, so a changed line is
    caught even after the checksums are rewritten: every link and hash, every line's exact
    canonical bytes, a replay in which only a person decides, and ``record.json``'s
    ``proposals_head``. ``quarantine.json`` and ``study_design.json`` must be well formed, and
    so must the artifact files (with only pseudonyms for names in a shared record).
    """
    record_dir = Path(record_dir)
    if not (record_dir / CHECKSUMS).exists():
        return VerifyReport(ok=False, missing=[CHECKSUMS])
    try:
        listed = _read_checksums(record_dir)
    except (RecordError, OSError, UnicodeDecodeError):
        return VerifyReport(ok=False, inconsistent=[f"{CHECKSUMS} unreadable"])
    present = _record_files(record_dir)
    missing = sorted(n for n in listed if n not in present)
    unlisted = sorted(n for n in present if n not in listed)
    changed = sorted(
        n for n, d in listed.items() if n in present and sha256_file(record_dir / n) != d
    )
    broken = None
    n_entries = 0
    try:
        root = StudyResult.model_validate_json(
            (record_dir / "results.json").read_text(encoding="utf-8")
        )
        entries = read_entries(record_dir / "decisions.jsonl")
        n_entries = len(entries)
        broken = verify_chain(entries, root.input_sha256)
        if broken is None:
            broken = _first_altered_line(record_dir / "decisions.jsonl", entries)
    except (OSError, ValueError, RecursionError):
        broken = 1
        entries = []
        root = None
    inconsistent = _consistency(record_dir, entries) if broken is None else []
    if root is not None and broken is None:
        inconsistent += _metadata(record_dir, root, entries)
    proposals = _proposal_chain(record_dir, root)
    inconsistent += proposals.problems + _studio_files(record_dir, root)
    inconsistent += _artifact_files(record_dir)
    ok = (
        not (missing or unlisted or changed or inconsistent)
        and broken is None
        and proposals.broken is None
    )
    return VerifyReport(
        ok=ok,
        changed=changed,
        missing=missing,
        unlisted=unlisted,
        chain_broken_at=broken,
        inconsistent=inconsistent,
        n_entries=n_entries,
        has_proposals=proposals.present,
        proposal_chain_broken_at=proposals.broken,
        n_proposal_entries=proposals.n_entries,
    )


class _ProposalCheck(BaseModel):
    present: bool = False
    n_entries: int = 0
    broken: int | None = None
    problems: list[str] = []


def _proposal_chain(record_dir: Path, root: StudyResult | None) -> _ProposalCheck:
    """Walk ``proposals.jsonl`` (root = the input's sha256) and check record.json names its head.

    ``record.json`` naming a proposal chain that is not there is reported too, so deleting the
    whole file is caught after a reseal.
    """
    path = record_dir / PROPOSALS_FILE
    try:
        meta = json.loads((record_dir / "record.json").read_text(encoding="utf-8"))
        named = meta.get("proposals_head") if isinstance(meta, dict) else None
    except (OSError, ValueError, RecursionError):
        named = None  # _metadata reports an unreadable record.json
    if not path.exists():
        missing = [f"{PROPOSALS_FILE} missing although record.json names a proposal chain"]
        return _ProposalCheck(problems=missing if named is not None else [])
    try:
        lines = chain_lines(path)
    except (OSError, UnicodeDecodeError):
        return _ProposalCheck(present=True, broken=1)
    if root is None:
        return _ProposalCheck(present=True, n_entries=len(lines), broken=1)
    entries = []
    for position, line in enumerate(lines, start=1):
        try:
            entries.append(ProposalEntry.model_validate_json(line))
        except (ValueError, RecursionError):
            return _ProposalCheck(present=True, n_entries=len(lines), broken=position)
    broken = verify_proposal_chain(entries, root.input_sha256)
    if broken is None:
        broken = first_altered_line(lines, entries)
    if broken is not None:
        return _ProposalCheck(present=True, n_entries=len(entries), broken=broken)
    problems = [f"{PROPOSALS_FILE} {p}" for p in replay(entries, root.input_sha256[:12]).problems]
    head = entries[-1].hash if entries else root.input_sha256
    if named != head:
        problems.append("record.json proposals_head is not the last entry of the proposal chain")
    return _ProposalCheck(present=True, n_entries=len(entries), problems=problems)


def _studio_files(record_dir: Path, root: StudyResult | None) -> list[str]:
    """What is wrong with ``quarantine.json`` and ``study_design.json`` (each optional)."""
    problems = []
    quarantine = record_dir / QUARANTINE_FILE
    if quarantine.exists():
        try:
            entries, pseudonymised = read_quarantine(quarantine)
            meta = json.loads((record_dir / "record.json").read_text(encoding="utf-8"))
            shared = bool(meta.get("shared")) if isinstance(meta, dict) else False
        except (QuarantineError, OSError, ValueError, RecursionError):
            problems.append(f"{QUARANTINE_FILE} unreadable, or a text_id does not match its text")
        else:
            if pseudonymised and not all(TOKEN.match(e.value) for e in entries):
                problems.append(f"{QUARANTINE_FILE} says pseudonymised but holds other text")
            if shared and not pseudonymised:
                problems.append(f"{QUARANTINE_FILE} holds original text in a shared record")
    design_path = record_dir / DESIGN_FILE
    if design_path.exists():
        try:
            text = design_path.read_text(encoding="utf-8")
            design = StudyDesign.model_validate_json(text)
        except (OSError, ValueError, RecursionError):
            return [*problems, f"{DESIGN_FILE} unreadable"]
        if text != design.canonical():
            problems.append(f"{DESIGN_FILE} is not the canonical form of its design")
        if root is not None:
            try:
                key = study_key(root.input_sha256, design)
            except ImportError:
                key = None  # a build without the qPCR plugin cannot recompute the study key
            except (ValueError, TypeError):
                key = ""
            if key is not None and root.study_id != key[:12]:
                problems.append(f"{DESIGN_FILE} is not the design this study was analysed with")
    return problems


def _artifact_files(record_dir: Path) -> list[str]:
    """What is wrong with the artifact files (each optional): not JSON, or names when shared.

    ``trace_cards.json`` is read as cards by :func:`_consistency`, which reports it unreadable.
    """
    try:
        meta = json.loads((record_dir / "record.json").read_text(encoding="utf-8"))
        shared = bool(meta.get("shared")) if isinstance(meta, dict) else False
    except (OSError, ValueError, RecursionError):
        shared = False  # _metadata reports an unreadable record.json
    problems = []
    for name in ARTIFACT_FILES:
        path = record_dir / name
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            left = unpseudonymised_names(data) if shared else []
        except (OSError, ValueError, RecursionError):
            if name != ON_DEMAND_FILE:
                problems.append(f"{name} unreadable")
            continue
        if left:
            problems.append(f"{name} {NAMES_IN_SHARED}")
    return problems


def _first_altered_line(log: Path, entries: list[DecisionEntry]) -> int | None:
    """The first chain line whose bytes are not the canonical form of the entry it parses to.

    The hash covers the parsed entry, so without this an extra field or a duplicate key could
    be added to a line (and the checksums resealed) without breaking the chain.
    """
    lines = [line for line in _lines(log) if line.strip()]
    for position, (line, entry) in enumerate(zip(lines, entries, strict=False), start=1):
        if line != entry_line(entry):
            return position
    return None


def _metadata(record_dir: Path, root: StudyResult, entries: list[DecisionEntry]) -> list[str]:
    """record.json and input.rdml must agree with the chain and results.json."""
    problems = []
    try:
        meta = json.loads((record_dir / "record.json").read_text(encoding="utf-8"))
        head = entries[-1].hash if entries else root.input_sha256
        if meta.get("chain_head") != head:
            problems.append("record.json chain_head is not the last entry of the chain")
        if meta.get("input_sha256") != root.input_sha256 or meta.get("study_id") != root.study_id:
            problems.append("record.json does not name the study in results.json")
        included = meta.get("input_included")
    except (OSError, ValueError, AttributeError, RecursionError):
        return ["record.json unreadable"]
    source = record_dir / "input.rdml"
    if source.exists():
        if sha256_file(source) != root.input_sha256:
            problems.append("input.rdml is not the study's input (sha256 differs)")
    elif included:
        problems.append("input.rdml missing although record.json says it is included")
    return problems


def _consistency(record_dir: Path, entries: list[DecisionEntry]) -> list[str]:
    """What in cards.json, choices.json and pending.jsonl the decision chain does not support.

    Each card's state (the analysis's in cards.json and the on-demand ones in trace_cards.json)
    is rebuilt by replaying the chain with the store's own logic and compared field by field;
    the card sets must match and every card the chain decides must exist. Run reviews decide
    no card; each must be a person's sign-off. Unreadable files are reported, never raised.
    """
    problems: list[str] = []
    try:
        cards = json.loads((record_dir / "cards.json").read_text(encoding="utf-8"))
        by_id = {c["id"]: c for c in cards}
        parsed = [DecisionCard.model_validate(c) for c in cards]
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        return ["cards.json unreadable"]
    origin = dict.fromkeys(by_id, "cards.json")
    on_demand = record_dir / ON_DEMAND_FILE
    if on_demand.exists():
        try:
            extra = json.loads(on_demand.read_text(encoding="utf-8"))
            extra_parsed = [DecisionCard.model_validate(c) for c in extra]
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            return [f"{ON_DEMAND_FILE} unreadable"]
        ids = [c.id for c in extra_parsed]
        if len(set(ids)) != len(ids):
            problems.append(f"{ON_DEMAND_FILE} lists a card twice")
        for card, raw in zip(extra_parsed, extra, strict=True):
            if card.kind not in ON_DEMAND_KINDS:
                problems.append(f"{ON_DEMAND_FILE} {card.id} is not an on-demand card")
            if card.id in origin:
                if origin[card.id] == "cards.json":
                    problems.append(f"{ON_DEMAND_FILE} {card.id} is also in cards.json")
                continue
            origin[card.id] = ON_DEMAND_FILE
            by_id[card.id] = raw
            parsed.append(card)
    replays = (replay_cards(parsed, entries), replay_cards(parsed, entries, legacy=True))
    expected: dict[str, dict] = {}
    for card_id, card in by_id.items():
        recorded = {f: card.get(f) for f in DECISION_FIELDS}
        states = [
            {f: getattr(c, f) for f in DECISION_FIELDS}
            for r in replays
            for c in r
            if c.id == card_id
        ]
        expected[card_id] = recorded if recorded in states else states[0]
        if recorded not in states:
            problems.append(f"{origin[card_id]} {card_id}")
    where = f"cards.json or {ON_DEMAND_FILE}" if on_demand.exists() else "cards.json"
    decided = {e.card_id for e in card_entries(entries)}
    problems += [f"{where} has no card {cid}" for cid in sorted(decided - set(by_id))]
    problems += [
        f"decisions.jsonl entry {e.seq} is a review no person signed"
        for e in entries
        if e.kind == REVIEW_KIND
        and not (
            e.actor == "human"
            and e.status == "applied"
            and e.card_id == REVIEW_CARD
            and e.outcome is not None
            and e.option == e.outcome
            and e.reviewer
        )
    ]
    choices_path = record_dir / "choices.json"
    if not choices_path.exists():
        problems.append("choices.json missing")
    else:
        try:
            choices = json.loads(choices_path.read_text(encoding="utf-8"))["cards"]
            items = sorted(choices.items())
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
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
    accepted = (
        [e.seq for e in pending_after(entries)],
        [e.seq for e in pending_after(entries, legacy=True)],
    )
    pending_path = record_dir / "pending.jsonl"
    if pending_path.exists():
        try:
            recorded_pending = [e.seq for e in read_entries(pending_path)]
        except (OSError, ValueError, RecursionError):
            return [*problems, "pending.jsonl unreadable"]
    else:
        recorded_pending = []
    if recorded_pending not in accepted:
        problems.append("pending.jsonl" if pending_path.exists() else "pending.jsonl missing")
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
            if not member.is_dir() and (not name.parts or dest == target):
                raise RecordError(f"unsafe path in record zip: {member.filename!r}")
        for member in members:
            if member.is_dir():
                continue
            dest = target / PurePosixPath(member.filename)
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
            except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError) as err:
                raise RecordError(f"damaged record zip ({member.filename}): {err}") from err
            except OSError as err:  # a file and a folder of one name, a '.' member, ...
                raise RecordError(f"unsafe path in record zip: {member.filename!r}") from err
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
    not_in_record: list[str] = []
    build_note: str = ""


STRUCTURE_SKIP = (*DECISION_FIELDS, "autonomy", "effective_autonomy")


def _card_structure(cards: list[dict]) -> str:
    """Cards without who-decided-what: what a re-run must reproduce."""
    stripped = [{k: v for k, v in c.items() if k not in STRUCTURE_SKIP} for c in cards]
    return dump_json(sorted(stripped, key=lambda c: c.get("id", "")))


def rerun_compare(record_dir: str | Path, out_dir: str | Path | None = None) -> RerunReport:
    """Re-run from ``input.rdml`` and compare results, facts, grid and card structure.

    Lazily imports ``qpilot.qpcr.study`` (documented exception to the core/plugin rule).
    ``results.json`` and ``facts.json`` must match byte for byte, ``grid.csv`` too when the
    record has one, and the cards must match apart from decisions.
    """
    record_dir = Path(record_dir)
    results_path = rerun(record_dir, out_dir)
    out = results_path.parent
    from qpilot.core.store import _grid_csv

    regenerated = _run_engine(record_dir, record_dir / "input.rdml")
    result, cards = regenerated[0], regenerated[1]
    grid = regenerated[2] if len(regenerated) > 2 else None
    facts = {fid: f.model_dump(mode="json") for fid, f in result.facts.items()}
    atomic_write(out / "facts.json", dump_json(facts))
    if grid is not None:
        atomic_write(out / "grid.csv", _grid_csv(grid))
    atomic_write(out / "cards.json", dump_json([c.model_dump(mode="json") for c in cards]))
    compared, differs = [], []
    absent = [n for n in ("facts.json", "grid.csv") if not (record_dir / n).exists()]
    for name in ("results.json", "facts.json", "grid.csv"):
        if (record_dir / name).exists() and (out / name).exists():
            compared.append(name)
            if (record_dir / name).read_bytes() != (out / name).read_bytes():
                differs.append(name)
    compared.append("cards.json (structure)")
    try:
        mine = _card_structure(json.loads((record_dir / "cards.json").read_text(encoding="utf-8")))
    except (OSError, ValueError, AttributeError, TypeError, RecursionError):
        mine = ""
    if mine != _card_structure([c.model_dump(mode="json") for c in cards]):
        differs.append("cards.json (structure)")
    note = ""
    try:
        made_with = json.loads((record_dir / "versions.json").read_text(encoding="utf-8")).get(
            "qpilot_git"
        )
        if made_with and made_with != versions()["qpilot_git"]:
            now = versions()["qpilot_git"]
            note = f"record made with qpilot {made_with[:12]}, re-run with {now[:12]}"
    except (OSError, ValueError, AttributeError, RecursionError):
        pass
    return RerunReport(
        out_dir=str(out),
        same=not differs,
        compared=compared,
        differs=differs,
        not_in_record=absent,
        build_note=note,
    )


def _run_engine(record_dir: Path, source: Path) -> tuple:
    """``run_study`` on the record's input, with the record's confirmed design when it has one.

    Lazily imports ``qpilot.qpcr.study`` (documented exception to the core/plugin rule). A
    record with ``study_design.json`` is re-run with ``StudySettings.from_design(design)``;
    one without it with the default settings, as before.
    """
    from qpilot.qpcr.study import run_study  # documented lazy import

    design_path = record_dir / DESIGN_FILE
    if not design_path.exists():
        return run_study(source)
    from qpilot.qpcr.study import StudySettings  # documented lazy import

    try:
        design = StudyDesign.model_validate_json(design_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as err:
        raise RecordError(f"{DESIGN_FILE} is unreadable, so the record cannot be re-run") from err
    return run_study(source, StudySettings.from_design(design))


def rerun(record_dir: str | Path, out_dir: str | Path | None = None) -> Path:
    """Re-run the analysis from the record's input; return the regenerated ``results.json``.

    Lazily imports ``qpilot.qpcr.study`` (documented exception to the core/plugin rule), and
    rebuilds the settings from ``study_design.json`` when the record has one.
    :func:`rerun_compare` also checks facts, grid and cards.
    """
    record_dir = Path(record_dir)
    source = record_dir / "input.rdml"
    if not source.exists():
        raise RecordError("this record does not include its input file, so it cannot be re-run")
    expected = StudyResult.model_validate_json(
        (record_dir / "results.json").read_text(encoding="utf-8")
    )
    if sha256_file(source) != expected.input_sha256:
        raise RecordError("input.rdml does not match results.json (sha256 differs)")
    out = Path(out_dir) if out_dir else record_dir.parent / f"{record_dir.name}-rerun"
    if out.resolve() == record_dir.resolve() or record_dir.resolve() in out.resolve().parents:
        raise RecordError("--out is inside the record; re-run into another folder")
    result = _run_engine(record_dir, source)[0]
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
