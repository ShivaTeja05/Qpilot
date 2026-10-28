"""The on-disk study store: one workspace per input file, shared by the app and the MCP server.

Domain-agnostic, and **the only code that writes a workspace**. The Gradio app and the MCP server
run in different processes, so the study lives on disk and every decision goes through this
module under a file lock, with an optimistic version check (``expected_head``)::

    $QPILOT_STUDIES_DIR/<input_sha256>/
        results.json  cards.json  facts.json  grid.csv   written atomically (temp -> rename)
        grid_comparisons.csv                             only for a study with several comparisons
        decisions.jsonl   hash-chained log, append-only, one DecisionEntry per line
        pending.jsonl     agent requests waiting for a human
        study_design.json the confirmed StudyDesign (designed studies only)
        trace_cards.json  cards opened on demand (Trace's set-aside cards), see open_card
        evidence.json  run_context.json  instrument_refs.json   artifact files (put_artifact)
        .lock
    $QPILOT_STUDIES_DIR/sessions/<input_sha256>/
        proposals.jsonl  quarantine.json  source.json  .keys/  .lock   (Studio, per input file)

A study analysed with a confirmed design (not the legacy default) lives in the workspace named
by the plugin's key, ``sha256(input_sha256 + design_hash)``, and its study id is the first 12
hex of that key; without a design the workspace is exactly ``<input_sha256>`` as before. A
Studio session holds the proposal inbox (``core/proposals.py``) and the quarantined free text
(``core/firewall.py``) of one input file, and nothing analytic, so it exists before any design
is confirmed.

The chain is tamper-evident, not tamper-proof: each entry stores the sha256 of the previous
entry (the first one stores the input file's sha256), so any later edit is detectable. An
entry is stored and hashed without its fields that are None, so entries written before the
review fields existed keep their bytes and their hashes.

Two kinds of card live here. The analysis builds the cards in ``cards.json`` (rewritten by
:meth:`StudyStore.put` whenever the study is analysed again). A card opened on demand, for one
place Trace points to, is kept in ``trace_cards.json`` (:meth:`StudyStore.open_card`), which a
re-analysis never deletes. Both are read, decided and replayed the same way, so the escalation
rule governs them alike. A run review (:meth:`StudyStore.append_review`) is a person's
sign-off in the same chain; no card replays it, so it never makes another write stale.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import os
import re
import tempfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from filelock import FileLock

from qpilot.core.decisions import (
    DecisionError,
    asked_again,
    carried_from,
    carried_reason,
    check_request,
    clean_reason,
    needs_human,
)
from qpilot.schemas import Actor, DecisionCard, DecisionEntry, DecisionOutcome, StudyResult
from qpilot.schemas_studio import Proposal, ProposalCheck, StudyDesign

if TYPE_CHECKING:
    from qpilot.core.firewall import Quarantine
    from qpilot.core.proposals import ProposalStore
    from qpilot.core.pseudonym import Pseudonymiser

_log = logging.getLogger(__name__)
STUDY_ID = re.compile(r"^[0-9a-f]{6,64}\Z")
INPUT_SHA = re.compile(r"^[0-9a-f]{64}\Z")
SESSIONS_DIR = "sessions"
DESIGN_FILE = "study_design.json"
NO_ENGINE_CHECK = "engine check not available in this build"
LOCK_TIMEOUT_S = 30
STALE_REASON = "card changed since you read it"
STALE_REVIEW = "the study changed since you read it: a decision was made in between"
PENDING_REASON = "This choice can change a conclusion, so a human must decide it."
SUGGEST_REASON = (
    "The scientist has not allowed agents to apply choices for this study (Suggest mode), "
    "so a person must confirm it."
)
AGENT_LEVELS = ("suggest", "decide_and_tell")
#: Files other features save in a workspace (written whole, read back as JSON). The Analysis
#: Record copies each one that is present.
ARTIFACT_FILES = ("evidence.json", "run_context.json", "instrument_refs.json", "trace_cards.json")
ON_DEMAND_FILE = "trace_cards.json"  # written only by open_card and the decision writes
#: Card kinds opened on demand rather than built by the analysis (no grid dimension).
ON_DEMAND_KINDS = ("trace_set_aside",)
REVIEW_KIND = "review"
REVIEW_CARD = "run_review"  # the card_id of every review entry; no card may take this id
REVIEW_OUTCOMES = ("accept", "repeat", "discuss")
MAX_REVIEWER = 100  # a person's name or initials, one line
MAX_CARD_ID = 128  # an on-demand card's id is a short printable label
HUMAN_ONLY_REVIEW = "only a person signs off a run review (actor must be 'human')"


# Later entries on the same card that make a write out of date: a new decision for any write,
# and also a new or settled request when a person turns requests down (they must have seen it).
STALE_IF = {
    "applied": ("applied", "auto"),
    "pending_human": ("applied", "auto"),
    "rejected": ("applied", "auto", "pending_human", "rejected"),
}
# Workspaces written before this card format (cards without flips_anywhere) are re-analysed when
# opened, so their choices escalate the way this qPilot escalates them.
CARDS_FORMAT = 2


def card_entries(entries: list[DecisionEntry]) -> list[DecisionEntry]:
    """The entries that decide (or ask about) a card: every entry but the run reviews."""
    return [e for e in entries if e.kind is None]


def changed_since(
    entries: list[DecisionEntry], root: str, expected_head: str, card_id: str, status: str
) -> bool:
    """Whether the study changed, in a way that matters to this write, since ``expected_head``.

    On the same card, see ``STALE_IF``. On other cards, only a decision by a person or the system
    counts: an agent's requests (or its decide-and-tell choices) elsewhere never make a write
    stale, so an agent cannot keep a person from deciding. A run review decides no card, so it
    never counts. A head that is not in the chain counts as changed.
    """
    heads = [root, *(e.hash for e in entries)]
    if expected_head not in heads:
        return True
    later = card_entries(entries[heads.index(expected_head) :])
    return any(
        e.status in STALE_IF[status]
        if e.card_id == card_id
        else e.actor != "agent" and e.status in ("applied", "auto")
        for e in later
    )


def pending_after(entries: list[DecisionEntry], legacy: bool = False) -> list[DecisionEntry]:
    """The agent requests still waiting after a log, replayed the way the store keeps them.

    An applied decision (by anyone) settles the card, so its waiting requests are cleared.
    ``legacy=True`` replays the rule of earlier qPilot builds (only a person's decision
    cleared requests, and one rejection cleared every request on its card); ``verify`` accepts
    either. Run reviews are skipped.
    """
    pending: list[DecisionEntry] = []
    for entry in card_entries(entries):
        if entry.status == "pending_human":
            pending.append(entry)
        elif entry.status == "applied" and (entry.actor == "human" or not legacy):
            pending = [p for p in pending if p.card_id != entry.card_id]
        elif entry.actor == "human" and entry.status == "rejected":
            pending = [
                p
                for p in pending
                if not (p.card_id == entry.card_id and (legacy or p.option == entry.option))
            ]
    return pending


class StudyNotFound(KeyError):
    """No workspace exists for the requested study id."""


class SheetChanged(ValueError):
    """A session's sample sheet is missing, or is no longer the file the session was opened with."""


class CardError(ValueError):
    """An on-demand card that cannot be opened: its kind, its state, or a clash with a card."""


class StaleReview(ValueError):
    """A run review whose ``expected_head`` is out of date: a decision changed the study since."""


def default_studies_dir() -> Path:
    """``$QPILOT_STUDIES_DIR`` or ``~/.cache/qpilot/studies``."""
    env = os.environ.get("QPILOT_STUDIES_DIR")
    return Path(env) if env else Path.home() / ".cache" / "qpilot" / "studies"


def sha256_file(path: str | Path) -> str:
    """Hex sha256 of a file's bytes."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(data: Any) -> str:
    """The one JSON form that gets hashed: sorted keys, no spaces, UTF-8 kept."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def entry_hash(entry: DecisionEntry) -> str:
    """sha256 of the entry's canonical JSON without its ``hash`` field and its None fields.

    Leaving out the fields that are None keeps the hash of every entry written before the
    review fields existed (none of the original fields can be None).
    """
    payload = canonical_json(entry.model_dump(mode="json", exclude={"hash"}, exclude_none=True))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def entry_line(entry: DecisionEntry) -> str:
    """The stored form of one entry: its canonical JSON without the fields that are None."""
    return canonical_json(entry.model_dump(mode="json", exclude_none=True))


def dump_json(data: Any) -> str:
    """Deterministic, human-readable JSON for workspace and record files."""
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def atomic_write(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` via a temp file in the same directory and an atomic rename."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_entries(path: Path) -> list[DecisionEntry]:
    """Parse a ``.jsonl`` file of decision entries (missing file = no entries)."""
    if not path.exists():
        return []
    return [DecisionEntry.model_validate_json(line) for line in _lines(path) if line.strip()]


def _lines(path: Path) -> list[str]:
    """The lines of a ``.jsonl`` file, split on newlines only.

    ``str.splitlines`` also breaks at U+2028, U+2029 and U+0085, which JSON leaves unescaped
    inside strings, so one such character in a reason would make the whole log unreadable.
    """
    return path.read_text(encoding="utf-8").split("\n")


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def study_key(input_sha256: str, design: StudyDesign | None) -> str:
    """The workspace name of a study: the input's sha256 without a design, else the plugin's key.

    With a design this asks ``qpilot.qpcr.designs.study_key`` (a documented lazy import, like
    :meth:`StudyStore.ensure_study`): the input's sha256 for the legacy default design,
    ``sha256(input_sha256 + design_hash)`` otherwise. The key names a folder, so anything but
    64 lower-case hex is refused.
    """
    if design is None:
        return input_sha256
    from qpilot.qpcr.designs import study_key as plugin_key  # documented lazy import

    key = plugin_key(input_sha256, design)
    if not isinstance(key, str) or not INPUT_SHA.match(key):
        raise ValueError("the design plugin returned an unusable workspace key")
    return key


def _no_engine_check(proposal: Proposal) -> ProposalCheck:
    return ProposalCheck(status="cannot_check", note=NO_ENGINE_CHECK)


def _session_input(store: StudyStore, session_id: str) -> tuple[Path | None, Path | None]:
    """A session's input file and sample sheet, as bound when it was opened.

    ``(None, None)`` when the input is unknown; :class:`SheetChanged` when the bound sheet is
    missing or changed, so the caller fails closed rather than reading the file without it.
    """
    path = None
    for find in (store.session_source, store.source):  # a session, else a legacy study
        try:
            path = find(session_id)
        except (StudyNotFound, OSError, ValueError, KeyError):
            path = None
        if path is not None:
            break
    if path is None:
        return None, None
    try:
        sheet = store.session_sheet(session_id)
    except StudyNotFound:  # a study whose input no Studio session opened has no sheet
        sheet = None
    return path, sheet


def _bind_check(
    check: Callable[..., ProposalCheck], store: StudyStore, session_id: str
) -> Callable[[Proposal], ProposalCheck]:
    def checker(proposal: Proposal) -> ProposalCheck:
        # A session has no analysed study yet, so the check is told where its input file and
        # its sample sheet are, and what a person has already confirmed (coverage and the
        # n-guard need the design; the hard bans need the sheet's explicit unit column).
        from qpilot.core.proposals import ProposalStore

        try:
            path, sheet = _session_input(store, session_id)
        except SheetChanged as err:
            return ProposalCheck(status="cannot_check", note=str(err))
        home, root = store.proposal_home(session_id)
        accepted = ProposalStore.at(home, root).accepted() if home.exists() else []
        extra = {"rdml_path": path, "accepted": accepted, "sheet_path": sheet}
        known = inspect.signature(check).parameters
        return check(proposal, store, session_id, **{k: v for k, v in extra.items() if k in known})

    return checker


def plugin_checks() -> tuple[Callable[..., str | None] | None, Callable[..., ProposalCheck] | None]:
    """The qPCR plugin's ``(hard_ban, check_proposal)``, or ``(None, None)`` without them.

    A documented lazy import of ``qpilot.qpcr.design_checks`` (like ``ensure_study``,
    :func:`study_key` and ``record.rerun``), so ``qpilot.core`` never depends on the plugin at
    import time. Only a build that lacks the module counts as "no checks"; any other import
    error is raised, so a broken plugin can never switch its hard bans off silently.
    """
    try:
        from qpilot.qpcr.design_checks import check_proposal, hard_ban  # documented lazy import
    except ModuleNotFoundError as err:
        if err.name in ("qpilot.qpcr", "qpilot.qpcr.design_checks"):
            return None, None
        raise
    return hard_ban, check_proposal


def _bind_input_resolver(store: StudyStore) -> None:
    """Let the plugin's hard bans find a session's input file and sample sheet, when needed.

    The bans must know which samples the file declares as controls and which units the sheet
    fixes; without that they refuse the proposals that could demote a control or merge a unit
    (they fail closed), as they do when the bound sheet is missing or has changed. The
    resolver is lazy, so listing an inbox never triggers a curve analysis. A documented lazy
    import, like :func:`plugin_checks`.
    """
    from qpilot.qpcr import design_checks  # documented lazy import

    set_input_resolver = getattr(design_checks, "set_input_resolver", None)
    if set_input_resolver is None:  # a plugin without the hook resolves inputs itself
        return

    def resolve(session_id: str) -> tuple[Path, Path | None] | None:
        try:
            path, sheet = _session_input(store, session_id)
        except SheetChanged:
            return None
        return None if path is None else (path, sheet)

    set_input_resolver(resolve)


DECISION_FIELDS = ("status", "decision", "reason", "decided_by", "decided_at")


def _settled_status(card: DecisionCard) -> str:
    if card.decision is None:
        return "open"
    return "auto_decided" if card.decided_by == "system" else "decided"


def _overlay_pending(cards: list[DecisionCard], entries: list[DecisionEntry]) -> list[DecisionCard]:
    """A card is ``pending_human`` exactly while a request on it is still waiting."""
    waiting = {p.card_id for p in pending_after(entries)}
    out = []
    for card in cards:
        status = "pending_human" if card.id in waiting else _settled_status(card)
        out.append(card if card.status == status else card.model_copy(update={"status": status}))
    return out


def replay_cards(
    cards: list[DecisionCard], entries: list[DecisionEntry], legacy: bool = False
) -> list[DecisionCard]:
    """The cards' decision state rebuilt from the log alone (the store and ``verify`` agree).

    Decision fields are blanked, every entry is replayed, and then each card with a request
    still waiting is ``pending_human``. ``legacy=True`` stops after the replay, the rule of
    earlier builds, where turning down one request could leave another waiting on an ``open``
    card.
    """
    blank = {f: None for f in DECISION_FIELDS} | {"status": "open"}
    states = {c.id: c.model_copy(update=blank) for c in cards}
    for entry in card_entries(entries):
        if entry.card_id in states:
            states[entry.card_id] = _apply_entry(states[entry.card_id], entry)
    replayed = [states[c.id] for c in cards]
    return replayed if legacy else _overlay_pending(replayed, entries)


def _card_text(card: DecisionCard) -> str:
    """A card without its decision state and autonomy, as text (equal for one card reopened).

    Text, not a dict comparison, so a NaN in the card compares equal to itself.
    """
    skip = {*DECISION_FIELDS, "autonomy", "effective_autonomy"}
    return canonical_json(card.model_dump(mode="json", exclude=skip))


def _check_on_demand(card: Any) -> DecisionCard:
    """An on-demand card as :meth:`StudyStore.open_card` accepts it, or :class:`CardError`."""
    if not isinstance(card, DecisionCard):
        raise CardError("open_card takes a DecisionCard")
    if card.kind not in ON_DEMAND_KINDS:
        raise CardError(f"a {card.kind} card is built by the analysis, never opened on demand")
    name = card.id
    if name == REVIEW_CARD or not name or name != name.strip() or not name.isprintable():
        raise CardError(f"{name!r} cannot be a card id")
    if len(name) > MAX_CARD_ID:
        raise CardError(f"a card id has at most {MAX_CARD_ID} characters")
    decided = any(getattr(card, f) is not None for f in DECISION_FIELDS if f != "status")
    if card.status != "open" or decided:
        raise CardError("a card is opened undecided (status open, no decision)")
    ids = [o.id for o in card.options]
    if not ids or len(set(ids)) != len(ids) or card.recommended not in ids:
        raise CardError("a card needs distinct options, one of them the recommended option")
    if not isinstance(card.impact.get("flips"), bool):
        # needs_human reads this; a card that does not say whether it flips must not open
        raise CardError("an on-demand card must say whether it can flip a conclusion (flips)")
    return card


def _apply_entry(card: DecisionCard, entry: DecisionEntry) -> DecisionCard:
    """The card state after one log entry (the store and ``verify`` both replay with this)."""
    if entry.status in ("applied", "auto"):
        return card.model_copy(
            update={
                "status": "auto_decided" if entry.status == "auto" else "decided",
                "decision": entry.option,
                "reason": entry.reason,
                "decided_by": entry.actor,
                "decided_at": entry.at,
            }
        )
    if entry.status == "pending_human":
        return card.model_copy(update={"status": "pending_human"})
    if entry.status == "rejected":
        if card.decision is None:
            return card.model_copy(update={"status": "open"})
        status = "auto_decided" if card.decided_by == "system" else "decided"
        return card.model_copy(update={"status": status})
    return card  # stale attempts change nothing


@dataclass
class CarryReport:
    """What :meth:`StudyStore.carry_decisions` did, card by card."""

    source: str
    target: str
    carried: list[str] = field(default_factory=list)  # card ids, one new entry each
    asked_again: dict[str, str] = field(default_factory=dict)  # card id -> why, in words
    gone: list[str] = field(default_factory=list)  # card or option not in the target

    def as_dict(self) -> dict[str, Any]:
        """Plain JSON (the session keeps the latest report per study)."""
        return asdict(self)


class StudyStore:
    """Reads and writes study workspaces; implements ``qpilot.schemas.StudyStoreAPI``."""

    def __init__(self, studies_dir: str | Path | None = None) -> None:
        self.root = Path(studies_dir) if studies_dir is not None else default_studies_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    # ---- locating workspaces ------------------------------------------------------------

    def workspace(self, study_id: str) -> Path:
        """The workspace directory of a study; ``StudyNotFound`` if there is none."""
        if not isinstance(study_id, str) or not STUDY_ID.match(study_id):
            raise StudyNotFound(f"not a study id: {study_id!r}")
        hits = [
            d
            for d in self.root.iterdir()
            if d.is_dir() and d.name.startswith(study_id) and (d / "results.json").exists()
        ]
        if len(hits) != 1:
            raise StudyNotFound(study_id)
        return hits[0]

    def list_studies(self) -> list[str]:
        """Study ids of every complete workspace."""
        out = []
        for d in sorted(self.root.iterdir()):
            if d.is_dir() and (d / "results.json").exists():
                out.append(json.loads((d / "results.json").read_text())["study_id"])
        return out

    @contextmanager
    def _locked(self, workspace: Path) -> Iterator[None]:
        with FileLock(str(workspace / ".lock"), timeout=LOCK_TIMEOUT_S):
            yield

    # ---- reading ---------------------------------------------------------------------

    def get(self, study_id: str) -> StudyResult:
        """Load a study's results."""
        path = self.workspace(study_id) / "results.json"
        return StudyResult.model_validate_json(path.read_text(encoding="utf-8"))

    def cards(self, study_id: str) -> list[DecisionCard]:
        """A study's Decision Cards: the analysis's in rank order, then on-demand cards by id."""
        workspace = self.workspace(study_id)
        return self._engine_cards(workspace) + self._on_demand_cards(workspace)

    @staticmethod
    def _engine_cards(workspace: Path) -> list[DecisionCard]:
        raw = json.loads((workspace / "cards.json").read_text(encoding="utf-8"))
        return sorted((DecisionCard.model_validate(c) for c in raw), key=lambda c: c.rank)

    @staticmethod
    def _on_demand_cards(workspace: Path) -> list[DecisionCard]:
        path = workspace / ON_DEMAND_FILE
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        return sorted((DecisionCard.model_validate(c) for c in raw), key=lambda c: c.id)

    def card(self, study_id: str, card_id: str) -> DecisionCard:
        """One card by id; ``KeyError`` if unknown."""
        for card in self.cards(study_id):
            if card.id == card_id:
                return card
        raise KeyError(f"unknown card {card_id!r}")

    def entries(self, study_id: str) -> list[DecisionEntry]:
        """Every entry of the decision log, oldest first."""
        return read_entries(self.workspace(study_id) / "decisions.jsonl")

    def chain_head(self, study_id: str) -> str:
        """Hash of the latest decision entry, or the input file's sha256 when there is none."""
        entries = self.entries(study_id)
        return entries[-1].hash if entries else self.get(study_id).input_sha256

    def pending(self, study_id: str) -> list[DecisionEntry]:
        """Agent requests that wait for a human, oldest first."""
        return read_entries(self.workspace(study_id) / "pending.jsonl")

    def reviews(self, study_id: str) -> list[DecisionEntry]:
        """The run reviews of a study (a person's sign-offs), oldest first."""
        return [e for e in self.entries(study_id) if e.kind == REVIEW_KIND]

    def get_artifact(self, study_id: str, name: str) -> Any | None:
        """One artifact file of a study, parsed, or None when it has not been saved.

        Raises:
            ValueError: ``name`` is not one of :data:`ARTIFACT_FILES`.
            StudyNotFound: No workspace has this study id.
        """
        if name not in ARTIFACT_FILES:
            raise ValueError(f"not an artifact file: {name!r}")
        path = self.workspace(study_id) / name
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def snapshot(self, study_id: str) -> tuple[str, list[DecisionCard], list[DecisionEntry]]:
        """Chain head, cards and pending requests read together under the workspace lock."""
        with self._locked(self.workspace(study_id)):
            return self.chain_head(study_id), self.cards(study_id), self.pending(study_id)

    def autonomy(self, study_id: str) -> str:
        """What agents may do in this study (``suggest`` by default).

        ``suggest``: agents may only ask. ``decide_and_tell``: agents may apply choices that
        cannot change a conclusion. The MCP server applies this setting.
        """
        path = self.workspace(study_id) / "autonomy.json"
        if not path.exists():
            return "suggest"
        level = json.loads(path.read_text(encoding="utf-8")).get("level")
        return level if level in AGENT_LEVELS else "suggest"

    def set_autonomy(self, study_id: str, level: str) -> None:
        """Set what agents may do in this study (the app's Autonomy toggle calls this)."""
        if level not in AGENT_LEVELS:
            raise ValueError(f"autonomy must be one of {', '.join(AGENT_LEVELS)}")
        workspace = self.workspace(study_id)
        with self._locked(workspace):
            atomic_write(workspace / "autonomy.json", dump_json({"level": level}))

    def attempts(self, study_id: str) -> list[dict[str, Any]]:
        """Refused (stale) attempts, kept outside the chain so they never move its head."""
        path = self.workspace(study_id) / "attempts.jsonl"
        if not path.exists():
            return []
        return [json.loads(x) for x in _lines(path) if x.strip()]

    # ---- writing (all under the workspace lock) ------------------------------------------

    def put(
        self,
        result: StudyResult,
        cards: list[DecisionCard],
        grid: Any = None,
        design: StudyDesign | None = None,
    ) -> None:
        """Write a study's results, cards, facts and (optionally) grid atomically.

        A new workspace's log starts with one ``system`` entry per auto-decided card. If the
        workspace already has a log (the same input analysed again), its decisions are replayed
        onto the new cards, so a re-run keeps what people decided. Run reviews count for
        neither, and the cards opened on demand (``trace_cards.json``) are kept as they are:
        they are not the analysis's output, so a re-analysis never deletes them.

        Without ``design`` the workspace is ``<input_sha256>``, exactly as before. With a
        confirmed design it is the plugin's :func:`study_key`, the result's study id must be
        the key's first 12 hex, and the design is saved as ``study_design.json`` (its canonical
        JSON), which ``record.rerun`` uses to rebuild the settings.
        """
        if not INPUT_SHA.match(result.input_sha256):
            raise ValueError("input_sha256 must be 64 lower-case hex")
        key = study_key(result.input_sha256, design)
        if design is not None and result.study_id != key[:12]:
            raise ValueError("a designed study's id must be the first 12 hex of its study key")
        workspace = self.root / key
        workspace.mkdir(parents=True, exist_ok=True)
        with self._locked(workspace):
            log = workspace / "decisions.jsonl"
            entries = read_entries(log)
            if not card_entries(entries):
                for card in sorted(cards, key=lambda c: c.rank):
                    if card.status == "auto_decided" and card.decision:
                        # _append adds the entry to ``entries`` itself (appending it here too
                        # made the next entry's seq skip one and broke the chain).
                        self._append(
                            log,
                            entries,
                            result.input_sha256,
                            card.id,
                            card.decision,
                            card.reason or "",
                            "system",
                            "auto",
                        )
            states = {c.id: c for c in cards}
            for entry in card_entries(entries):
                if entry.card_id in states:
                    states[entry.card_id] = _apply_entry(states[entry.card_id], entry)
            atomic_write(workspace / "results.json", dump_json(result.model_dump(mode="json")))
            self._write_cards(workspace, _overlay_pending(list(states.values()), entries))
            on_demand = self._on_demand_cards(workspace)
            if on_demand:  # kept, and rebuilt from the log like cards.json
                self._write_on_demand(workspace, replay_cards(on_demand, entries))
            self._write_pending(workspace, entries)
            facts = {fid: f.model_dump(mode="json") for fid, f in result.facts.items()}
            atomic_write(workspace / "facts.json", dump_json(facts))
            if grid is not None:
                atomic_write(workspace / "grid.csv", _grid_csv(grid))
                _put_comparison_grid(workspace, grid)
            if design is not None:
                atomic_write(workspace / DESIGN_FILE, design.canonical())
            atomic_write(workspace / "format.json", dump_json({"cards": CARDS_FORMAT}))

    def append_decision(
        self,
        study_id: str,
        card_id: str,
        option: str,
        reason: str,
        actor: Actor,
        expected_head: str | None,
    ) -> DecisionOutcome:
        """Apply a decision under the lock; ``stale`` if ``expected_head`` is out of date.

        A non-human actor on a card that can flip a conclusion is turned into a request for a
        human here as well, so no caller can write around the escalation rule.
        """
        card = self.card(study_id, card_id)
        reason = check_request(card, option, reason)
        if actor != "human" and needs_human(card):
            return self.request_human(study_id, card_id, option, reason, actor, expected_head)
        return self._write(study_id, card_id, option, reason, actor, "applied", expected_head)

    def request_human(
        self,
        study_id: str,
        card_id: str,
        option: str,
        reason: str,
        actor: Actor,
        expected_head: str | None,
    ) -> DecisionOutcome:
        """Log an agent's request on a flipping card and queue it for a human."""
        outcome = self._write(
            study_id, card_id, option, reason, actor, "pending_human", expected_head
        )
        if outcome.status == "pending_human":
            outcome = outcome.model_copy(update={"reason": PENDING_REASON})
        return outcome

    def reject_pending(
        self,
        study_id: str,
        card_id: str,
        reason: str,
        expected_head: str | None,
        option: str | None = None,
    ) -> DecisionOutcome:
        """A human declines pending agent requests on a card: one log entry per refused option.

        With ``option`` only requests for that option are refused; otherwise all of them.
        """
        waiting = [
            p
            for p in self.pending(study_id)
            if p.card_id == card_id and (option is None or p.option == option)
        ]
        if not waiting:
            which = f" for option {option!r}" if option else ""
            raise KeyError(f"no pending request on card {card_id!r}{which}")
        options = list(dict.fromkeys(p.option for p in waiting))  # distinct, oldest first
        return self._write(study_id, card_id, options, reason, "human", "rejected", expected_head)

    def carry_decisions(self, source: str, target: str) -> CarryReport:
        """Carry what a person decided in ``source`` to ``target``, another analysis of its file.

        For each card of ``source`` whose decision a person made, one new ``applied`` entry by
        ``human`` on the same card and option in ``target``, whose reason names the earlier
        study and the entry that made the decision, then the person's words
        (:func:`~qpilot.core.decisions.carried_reason`). The system's and agents' decisions,
        agents' requests and their turn-downs are never carried. A decision is asked again
        (not carried) when the choice matters more in ``target``
        (:func:`~qpilot.core.decisions.asked_again`) or an agent's request waits on the card;
        it is left alone when the card or option is gone, when ``target`` already shows the
        option decided by a person, or when the same entry was carried there before (so a later
        change in ``target`` stands). Writes under ``target``'s lock; ``ValueError`` when the
        two are not analyses of the same file.
        """
        with self._locked(self.workspace(source)):
            earlier = self.get(source)
            # Cards opened on demand (Trace's set-aside cards) are not analysis choices: a new
            # analysis does not have them, so they are never carried.
            before = self._engine_cards(self.workspace(source))
            made: dict[str, DecisionEntry] = {}
            for entry in card_entries(self.entries(source)):
                if entry.status in ("applied", "auto"):
                    made[entry.card_id] = entry
        workspace = self.workspace(target)
        report = CarryReport(source=earlier.study_id, target=target)
        with self._locked(workspace):
            root = self.get(target).input_sha256
            if root != earlier.input_sha256:
                raise ValueError("decisions are carried only between analyses of the same file")
            report.target = self.get(target).study_id
            log = workspace / "decisions.jsonl"
            entries = read_entries(log)
            cards = {c.id: c for c in replay_cards(self._engine_cards(workspace), entries)}
            waiting = {p.card_id for p in pending_after(entries)}
            done = {
                c.entry_hash
                for e in entries
                if e.actor == "human"
                and e.kind is None
                and (c := carried_from(e.reason)) is not None
            }
            for old in before:
                entry = made.get(old.id)
                if (
                    entry is None
                    or entry.actor != "human"
                    or old.decided_by != "human"
                    or entry.option != old.decision
                ):
                    continue  # nothing a person decided
                new = cards.get(old.id)
                if new is None or entry.option not in {o.id for o in new.options}:
                    report.gone.append(old.id)
                    continue
                if entry.hash in done or (new.decided_by, new.decision) == ("human", entry.option):
                    continue
                why = asked_again(old, new)
                if why is None and new.id in waiting:
                    why = "an agent's request waits on this card for a person"
                if why is not None:
                    report.asked_again[old.id] = why
                    continue
                words = carried_from(entry.reason)
                reason = carried_reason(
                    earlier.study_id, entry.hash, words.reason if words else entry.reason
                )
                self._append(log, entries, root, old.id, entry.option, reason, "human", "applied")
                report.carried.append(old.id)
            if report.carried:
                self._write_cards(workspace, replay_cards(self._engine_cards(workspace), entries))
                self._write_pending(workspace, entries)
        return report

    def open_card(self, study_id: str, card: DecisionCard) -> DecisionCard:
        """Add a card that no analysis builds (today Trace's ``trace_set_aside``) to a study.

        The card is kept in ``trace_cards.json`` (a list sorted by id; ``cards.json`` is never
        touched, and nothing is written to the log, so the chain head does not move). From
        then on it is read, decided, requested and replayed like the analysis's cards, so
        :func:`~qpilot.core.decisions.needs_human` governs it: an agent's request on a card
        that can flip a conclusion waits for a person at every autonomy level.

        Opening the same card again (equal apart from its decision state and autonomy) returns
        the stored card, with whatever has been decided on it. Its state is the log's: an id
        the log already decided keeps that decision.

        Args:
            study_id: The study.
            card: The card, ``status="open"`` with no decision, of a kind in
                :data:`ON_DEMAND_KINDS`, saying in ``impact["flips"]`` whether it can flip a
                conclusion.

        Returns:
            The card as stored.

        Raises:
            CardError: The card is of a kind the analysis builds, is not open, has no usable
                options, does not say whether it flips, takes an analysis card's id or the
                reserved review id, or differs from a card already open under its id.
            StudyNotFound: No workspace has this study id.
        """
        card = _check_on_demand(card)
        workspace = self.workspace(study_id)
        with self._locked(workspace):
            if card.id in {c.id for c in self._engine_cards(workspace)}:
                raise CardError(f"{card.id!r} is a card of the analysis; choose another id")
            opened = self._on_demand_cards(workspace)
            same = next((c for c in opened if c.id == card.id), None)
            if same is not None:
                if _card_text(same) != _card_text(card):
                    raise CardError(f"a different card is already open as {card.id!r}")
                return same
            entries = read_entries(workspace / "decisions.jsonl")
            card = replay_cards([card], entries)[0]
            self._write_on_demand(workspace, [*opened, card])
            return card

    def append_review(
        self,
        study_id: str,
        outcome: str,
        comment: str,
        reviewer: str,
        *,
        actor: str = "human",
        expected_head: str | None = None,
    ) -> DecisionEntry:
        """A person signs off the run: one ``review`` entry in the decision chain.

        The entry has ``card_id`` :data:`REVIEW_CARD`, ``option`` and ``outcome`` the outcome,
        ``reason`` the comment and ``status`` ``applied``. No card replays it and it clears no
        request, so it never makes another write stale (an agent's request or a person's
        decision read at the previous head still goes through). The reviewer's name is kept in
        the chain, so it stays in a shared record, as a proposal's subject does.

        Args:
            study_id: The study.
            outcome: ``accept``, ``repeat`` or ``discuss`` (:data:`REVIEW_OUTCOMES`).
            comment: Why; cleaned like a decision's reason (one line, at most 500 characters).
            reviewer: Who signs off (one line, at most :data:`MAX_REVIEWER` characters).
            actor: Must be ``human``: only a person reviews a run.
            expected_head: The chain head the reviewer read; a person's or the system's
                decision since then makes the review stale.

        Returns:
            The entry as written.

        Raises:
            DecisionError: ``actor`` is not ``human``, or the outcome, comment or reviewer is
                not usable.
            StaleReview: A decision changed the study since ``expected_head`` (the attempt is
                logged in ``attempts.jsonl``, outside the chain).
            StudyNotFound: No workspace has this study id.
        """
        # type() and not isinstance(): a str subclass could answer == "human" for anyone.
        if type(actor) is not str or actor != "human":
            raise DecisionError(HUMAN_ONLY_REVIEW)
        if type(outcome) is not str or outcome not in REVIEW_OUTCOMES:
            raise DecisionError(f"a review outcome is one of {', '.join(REVIEW_OUTCOMES)}")
        comment = clean_reason(comment, "comment")
        reviewer = clean_reason(reviewer, "reviewer", MAX_REVIEWER)
        workspace = self.workspace(study_id)
        log = workspace / "decisions.jsonl"
        with self._locked(workspace):
            entries = read_entries(log)
            root = self.get(study_id).input_sha256
            if expected_head is not None and changed_since(
                entries, root, expected_head, REVIEW_CARD, "applied"
            ):
                attempt = {
                    "at": _now(),
                    "status": "stale",
                    "attempted": REVIEW_KIND,
                    "card_id": REVIEW_CARD,
                    "option": outcome,
                    "options": [outcome],
                    "reason": comment,
                    "actor": actor,
                    "expected_head": expected_head,
                    "head": entries[-1].hash if entries else root,
                }
                with open(workspace / "attempts.jsonl", "a", encoding="utf-8") as fh:
                    fh.write(canonical_json(attempt) + "\n")
                raise StaleReview(STALE_REVIEW)
            return self._append(
                log,
                entries,
                root,
                REVIEW_CARD,
                outcome,
                comment,
                "human",
                "applied",
                kind=REVIEW_KIND,
                outcome=outcome,
                reviewer=reviewer,
            )

    def put_artifact(self, study_id: str, name: str, data: Mapping[str, Any] | list[Any]) -> Path:
        """Save one artifact file (a feature's derived result) in a study's workspace.

        Written whole, under the workspace lock, atomically, as deterministic JSON
        (:func:`dump_json`). The Analysis Record copies it. ``trace_cards.json`` is the one
        artifact this cannot write: cards are opened with :meth:`open_card`, so the escalation
        rule and the log decide their state.

        Args:
            study_id: The study.
            name: One of :data:`ARTIFACT_FILES` other than ``trace_cards.json``.
            data: A JSON object or list (NaN and infinity are refused: they are not JSON).

        Returns:
            The path written.

        Raises:
            ValueError: ``name`` is not an artifact file, is ``trace_cards.json``, or ``data``
                is not plain JSON.
            StudyNotFound: No workspace has this study id.
        """
        if name not in ARTIFACT_FILES:
            raise ValueError(f"not an artifact file: {name!r}")
        if name == ON_DEMAND_FILE:
            raise ValueError(f"{ON_DEMAND_FILE} is written by open_card only")
        if isinstance(data, Mapping):
            payload: dict[str, Any] | list[Any] = dict(data)
        elif isinstance(data, list):
            payload = data
        else:
            raise ValueError(f"{name} must hold a JSON object or list")
        try:
            json.dumps(payload, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as err:
            raise ValueError(f"{name} must be plain JSON: {err}") from err
        workspace = self.workspace(study_id)
        path = workspace / name
        with self._locked(workspace):
            atomic_write(path, dump_json(payload))
        return path

    def append_ai_call(self, study_id: str, entry: dict[str, Any]) -> None:
        """Append one model-call log line (no key, no raw payload unless opted in)."""
        workspace = self.workspace(study_id)
        line = canonical_json({**entry, "at": _now()}) + "\n"
        with self._locked(workspace):
            with open(workspace / "ai_calls.jsonl", "a", encoding="utf-8") as fh:
                fh.write(line)

    def put_scorecard(self, study_id: str, scorecards: dict[str, Any]) -> None:
        """Save the latest harness scorecards (by profile) so the record carries them."""
        workspace = self.workspace(study_id)
        with self._locked(workspace):
            atomic_write(workspace / "harness_scorecard.json", dump_json(scorecards))

    def scorecard(self, study_id: str) -> dict[str, Any]:
        """The saved harness scorecards, keyed by profile (empty if none)."""
        path = self.workspace(study_id) / "harness_scorecard.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def ai_calls(self, study_id: str) -> list[dict[str, Any]]:
        """Every model-call log line of a study."""
        path = self.workspace(study_id) / "ai_calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(x) for x in _lines(path) if x.strip()]

    # ---- internals -------------------------------------------------------------------

    def _write(
        self,
        study_id: str,
        card_id: str,
        option: str | list[str],
        reason: str,
        actor: Actor,
        status: str,
        expected_head: str | None,
    ) -> DecisionOutcome:
        """Append one entry (or one per option, all under one lock) after the version check."""
        workspace = self.workspace(study_id)
        log = workspace / "decisions.jsonl"
        options = option if isinstance(option, list) else [option]
        with self._locked(workspace):
            entries = read_entries(log)
            root = self.get(study_id).input_sha256
            head = entries[-1].hash if entries else root
            if expected_head is not None and changed_since(
                entries, root, expected_head, card_id, status
            ):
                # Logged outside the chain: a refused attempt must not move the head, or other
                # readers would be told the card changed when nothing did.
                attempt = {
                    "at": _now(),
                    "status": "stale",
                    "attempted": status,  # applied, pending_human or rejected
                    "card_id": card_id,
                    "option": options[0],
                    "options": options,
                    "reason": reason,
                    "actor": actor,
                    "expected_head": expected_head,
                    "head": head,
                }
                with open(workspace / "attempts.jsonl", "a", encoding="utf-8") as fh:
                    fh.write(canonical_json(attempt) + "\n")
                return DecisionOutcome(
                    status="stale",
                    chain_head=head,
                    card=self.card(study_id, card_id),
                    reason=STALE_REASON,
                )
            for each in options:
                entry = self._append(log, entries, root, card_id, each, reason, actor, status)
            # cards.json, trace_cards.json and pending.jsonl are derived from the log and rebuilt
            # in full on every write, so a write interrupted earlier can never leave them out of
            # step for good.
            cards = replay_cards(self._engine_cards(workspace), entries)
            self._write_cards(workspace, cards)
            on_demand = self._on_demand_cards(workspace)
            if on_demand:
                on_demand = replay_cards(on_demand, entries)
                self._write_on_demand(workspace, on_demand)
            self._write_pending(workspace, entries)
            card = next(c for c in [*cards, *on_demand] if c.id == card_id)
            return DecisionOutcome(status=status, chain_head=entry.hash, card=card)

    @staticmethod
    def _append(
        log: Path,
        entries: list[DecisionEntry],
        root: str,
        card_id: str,
        option: str,
        reason: str,
        actor: Actor,
        status: str,
        **review: Any,
    ) -> DecisionEntry:
        entry = DecisionEntry(
            seq=len(entries) + 1,
            prev_hash=entries[-1].hash if entries else root,
            card_id=card_id,
            option=option,
            reason=reason,
            actor=actor,
            status=status,
            at=_now(),
            **review,
        )
        entry = entry.model_copy(update={"hash": entry_hash(entry)})
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(entry_line(entry) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        entries.append(entry)
        return entry

    @staticmethod
    def _write_cards(workspace: Path, cards: list[DecisionCard]) -> None:
        ordered = sorted(cards, key=lambda c: c.rank)
        atomic_write(
            workspace / "cards.json", dump_json([c.model_dump(mode="json") for c in ordered])
        )

    @staticmethod
    def _write_on_demand(workspace: Path, cards: list[DecisionCard]) -> None:
        ordered = sorted(cards, key=lambda c: c.id)
        atomic_write(
            workspace / ON_DEMAND_FILE, dump_json([c.model_dump(mode="json") for c in ordered])
        )

    @staticmethod
    def _write_pending(workspace: Path, entries: list[DecisionEntry]) -> None:
        pending = pending_after(entries)
        text = "".join(entry_line(p) + "\n" for p in pending)
        path = workspace / "pending.jsonl"
        if path.exists() or text:
            atomic_write(path, text)

    # ---- running a study ---------------------------------------------------------------

    def ensure_study(self, rdml_path: str | Path, design: StudyDesign | None = None) -> str:
        """Return the study id for an input file, analysing it first if no workspace exists.

        With ``design`` (a confirmed :class:`~qpilot.schemas_studio.StudyDesign`) the study is
        analysed with ``StudySettings.from_design(design)`` in the design's own workspace (see
        :func:`study_key`); without it, exactly as before.

        This is one of the documented places where the core imports the qPCR plugin (the others
        are :func:`study_key`, :func:`plugin_checks` and ``record.rerun``); the imports are
        inside functions so that ``qpilot.core`` never depends on ``qpilot.qpcr`` at import time.
        """
        path = Path(rdml_path).resolve()
        digest = sha256_file(path)
        workspace = self.root / study_key(digest, design)
        fresh = False
        if (workspace / "results.json").exists() and not self._outdated(workspace):
            study_id = json.loads((workspace / "results.json").read_text())["study_id"]
        else:
            # New, or written by an older qPilot: (re-)analyse. put() replays the log onto the
            # new cards, so decisions people made are kept.
            from qpilot.qpcr.study import run_study  # documented lazy import

            if design is None:
                out = run_study(path)
            else:
                from qpilot.qpcr.study import StudySettings  # documented lazy import

                out = run_study(path, StudySettings.from_design(design))
            result, cards = out[0], out[1]
            grid = out[2] if len(out) > 2 else None
            self.put(result, cards, grid, design=design)
            study_id = result.study_id
            fresh = True
        self.set_source(study_id, path)
        if fresh:
            self._derive_artifacts(study_id, path)
        return study_id

    def _derive_artifacts(self, study_id: str, path: Path) -> None:
        """After a new analysis: keep ``evidence.json`` and ``run_context.json`` (best effort).

        The Evidence Ledger (``qpcr.evidence.evidence_store``) and one run context per RDML run
        (``qpcr.instrument_context.run_contexts_from_rdml``, in its ``model_view()`` shape: no
        serial, alias, local fact or file name ever enters the file). Neither touches the
        analysis outputs, and a failure only skips that file, with a logged note: the analysis
        stands.
        """
        try:
            from qpilot.qpcr.evidence import evidence_store  # documented lazy import

            ledger = evidence_store(self, study_id)
            self.put_artifact(study_id, "evidence.json", ledger.model_dump(mode="json"))
        except Exception as err:  # derived file only: the analysis must never fail here
            _log.warning("evidence.json not written for %s (%s)", study_id, type(err).__name__)
        try:
            from qpilot.qpcr.instrument_context import run_contexts_from_rdml  # lazy import

            contexts = run_contexts_from_rdml(path, source_file=path.name)
            runs = [ctx.model_view() for ctx in contexts]
            self.put_artifact(study_id, "run_context.json", {"runs": runs})
        except Exception as err:  # derived file only
            _log.warning("run_context.json not written for %s (%s)", study_id, type(err).__name__)

    @staticmethod
    def _outdated(workspace: Path) -> bool:
        """True for a workspace an older qPilot wrote, or one whose analysis was interrupted.

        ``put`` writes ``format.json`` last, so a workspace without it is either from a build
        before this card format or incomplete; both are analysed again.
        """
        try:
            fmt = json.loads((workspace / "format.json").read_text(encoding="utf-8"))
            return not fmt.get("cards", 0) >= CARDS_FORMAT
        except (OSError, ValueError, AttributeError):
            return True

    def set_source(self, study_id: str, rdml_path: str | Path) -> None:
        """Remember where the input file is, after checking it is the study's input."""
        workspace = self.workspace(study_id)
        path = Path(rdml_path).resolve()
        digest = sha256_file(path)
        if digest != self.get(study_id).input_sha256:
            raise ValueError("this file is not the input of this study (sha256 differs)")
        data = {"path": str(path), "sha256": digest}
        with self._locked(workspace):
            atomic_write(workspace / "source.json", dump_json(data))

    def source(self, study_id: str) -> Path | None:
        """The input file of a study, if it is known and still unchanged on disk."""
        meta = self.workspace(study_id) / "source.json"
        if not meta.exists():
            return None
        data = json.loads(meta.read_text(encoding="utf-8"))
        path = Path(data["path"])
        if not path.exists() or sha256_file(path) != data["sha256"]:
            return None
        return path

    def design(self, study_id: str) -> StudyDesign | None:
        """The confirmed design a study was analysed with, or None for the legacy default."""
        path = self.workspace(study_id) / DESIGN_FILE
        if not path.exists():
            return None
        return StudyDesign.model_validate_json(path.read_text(encoding="utf-8"))

    # ---- Studio sessions: proposals and quarantined text, per input file ----------------------

    def session(self, input_sha256: str) -> Path:
        """The Studio session folder of one input file, created if missing."""
        if not isinstance(input_sha256, str) or not INPUT_SHA.match(input_sha256):
            raise ValueError("a session is named by its input file's sha256 (64 hex)")
        folder = self.root / SESSIONS_DIR / input_sha256
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def open_session(
        self, rdml_path: str | Path, sheet_path: str | Path | None = None, *, rebind: bool = True
    ) -> str:
        """Open (or reopen) the session of an input file; return its id, ``input_sha256[:12]``.

        Records where the file and its sample sheet are (``source.json``: each path with its
        sha256; no ``sheet`` without one). The caller checks the paths first (the MCP server's
        path policy); nothing is analysed here.

        A person's open binds what they opened. ``rebind=False`` (an agent's open) never changes
        a session that was already opened: its input file and its sample sheet stay as they
        were bound, and a different sheet is refused with ``ValueError``.
        """
        path = Path(rdml_path).resolve()
        digest = sha256_file(path)
        sheet = None
        if sheet_path is not None:
            sheet_file = Path(sheet_path).resolve()
            sheet = {"path": str(sheet_file), "sha256": sha256_file(sheet_file)}
        folder = self.session(digest)
        record = folder / "source.json"
        with self._locked(folder):
            if record.exists() and not rebind:
                bound = json.loads(record.read_text(encoding="utf-8")).get("sheet") or {}
                if sheet is not None and bound.get("sha256") != sheet["sha256"]:
                    raise ValueError(
                        "this session was already opened with its own sample sheet (or none); "
                        "only a person can change it, in qPilot Studio"
                    )
                return digest[:12]
            data: dict[str, Any] = {"path": str(path), "sha256": digest}
            if sheet is not None:
                data["sheet"] = sheet
            atomic_write(record, dump_json(data))
        return digest[:12]

    def find_session(self, session_id: str) -> Path:
        """The session folder whose name starts with ``session_id``; ``StudyNotFound`` if none."""
        if not isinstance(session_id, str) or not STUDY_ID.match(session_id):
            raise StudyNotFound(f"not a session id: {session_id!r}")
        folder = self.root / SESSIONS_DIR
        hits = (
            [
                d
                for d in folder.iterdir()
                if d.is_dir() and INPUT_SHA.match(d.name) and d.name.startswith(session_id)
            ]
            if folder.is_dir()
            else []
        )
        if len(hits) != 1:
            raise StudyNotFound(session_id)
        return hits[0]

    def session_source(self, session_id: str) -> Path | None:
        """The input file of a session, if it is known and still unchanged on disk."""
        folder = self.find_session(session_id)
        meta = folder / "source.json"
        if not meta.exists():
            return None
        data = json.loads(meta.read_text(encoding="utf-8"))
        path = Path(data["path"])
        if data.get("sha256") != folder.name or not path.exists():
            return None
        return path if sha256_file(path) == folder.name else None

    def session_sheet(self, session_id: str) -> Path | None:
        """The sample sheet a session was opened with, or None when it was opened without one.

        Raises:
            SheetChanged: The bound sheet is missing or is no longer the file it was opened
                with (the session then fails closed until a person opens it again).
            StudyNotFound: No session has this id.
        """
        meta = self.find_session(session_id) / "source.json"
        if not meta.exists():
            return None
        sheet = json.loads(meta.read_text(encoding="utf-8")).get("sheet")
        if not sheet:
            return None
        path = Path(sheet["path"])
        if not path.exists() or sha256_file(path) != sheet["sha256"]:
            raise SheetChanged("the sample sheet is missing or has changed since it was opened")
        return path

    def proposal_home(self, study_id: str) -> tuple[Path, str]:
        """Where the proposals of a study or session live, and the input sha256 they chain from.

        Always the session of the input file: a session id (``input_sha256[:12]``) names it
        directly, and a study id (legacy or designed) names it through the study's input. An
        id that matches neither, or matches two different inputs, is ``StudyNotFound``. The
        folder is created on the first write, not here.
        """
        inputs = set()
        try:
            inputs.add(self.find_session(study_id).name)
        except StudyNotFound:
            pass
        try:
            inputs.add(self.get(study_id).input_sha256)
        except StudyNotFound:
            pass
        if len(inputs) != 1:
            raise StudyNotFound(study_id)
        digest = inputs.pop()
        if not INPUT_SHA.match(digest):
            raise StudyNotFound(study_id)
        return self.root / SESSIONS_DIR / digest, digest

    def proposals(self, study_id: str) -> ProposalStore:
        """The proposal inbox of a study or session, with the domain plugin's checks wired in.

        The plugin's ``hard_ban`` guards every proposal and every acceptance, and its
        ``check_proposal(proposal, store, session_id)`` replaces whatever check a caller
        supplies, where ``session_id`` is the input's legacy id (``input_sha256[:12]``) and may
        name a session with no analysed study yet. In a build without the plugin nothing is
        banned and every check is ``cannot_check``, so nothing can be accepted in bulk.
        """
        from qpilot.core.proposals import ProposalStore

        home, digest = self.proposal_home(study_id)
        guard, check = plugin_checks()
        checker = _no_engine_check if check is None else _bind_check(check, self, digest[:12])
        if guard is not None:
            _bind_input_resolver(self)
        return ProposalStore.at(home, digest, guard, checker=checker)

    def quarantine(self, study_id: str) -> Quarantine:
        """The quarantined free text of a study's or session's input (``core/firewall.py``)."""
        from qpilot.core.firewall import Quarantine

        return Quarantine(self.proposal_home(study_id)[0])

    def pseudonymiser(self, study_id: str) -> Pseudonymiser:
        """Keyed tokens for the names of a study's or session's input (``core/pseudonym.py``)."""
        from qpilot.core.pseudonym import Pseudonymiser

        return Pseudonymiser(self.proposal_home(study_id)[0])


COMPARISON_GRID_FILE = "grid_comparisons.csv"


def _put_comparison_grid(workspace: Path, grid: Any) -> None:
    """Write (or remove) ``grid_comparisons.csv``: every comparison's grid, when there are several.

    The qPCR plugin attaches it to the primary grid (``qpilot.qpcr.study.comparison_grid_of``);
    a study with one comparison has none, and a stale file from an earlier analysis is removed.
    """
    from qpilot.qpcr.study import comparison_grid_csv, comparison_grid_of  # documented lazy import

    path = workspace / COMPARISON_GRID_FILE
    frame = comparison_grid_of(grid)
    if frame is not None:
        atomic_write(path, comparison_grid_csv(frame))
    elif path.exists():
        path.unlink()


def _grid_csv(grid: Any) -> str:
    """CSV text for a grid DataFrame (tuples joined with ``|``) or an already-written string."""
    if isinstance(grid, str):
        return grid
    from qpilot.core.robustness import to_csv_frame

    return to_csv_frame(grid).to_csv(index=False, float_format="%.10g", lineterminator="\n")
