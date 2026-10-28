"""The proposal inbox: the AI proposes, the engine checks, and only a person decides.

Domain-agnostic. A :class:`~qpilot.schemas_studio.Proposal` has no effect on any number, record
entry or Prism file until a person accepts it; the engine reads only :meth:`ProposalStore.accepted`.
Proposals live in the Studio session of their input file, so an inbox exists before any design
is confirmed or any analysis has run::

    $QPILOT_STUDIES_DIR/sessions/<input_sha256>/
        proposals.jsonl   hash-chained, append-only, one ProposalEntry per line
        quarantine.json   the free text proposals cite (core/firewall.py)
        source.json       where the input file (and its sample sheet) is
        .lock

There is one chain per input file. Its root is the input's sha256 (the root of the decision
chain too), and every proposal in it carries ``study_id = input_sha256[:12]``, the input's
legacy study id, whatever design is later confirmed. Each line's ``hash`` is the sha256 of the
canonical JSON of the entry without ``hash`` and without fields that are None, so optional
fields added later never change old hashes. The full proposal is stored once, on its
``propose`` line; every state (pending, accepted, edited, rejected, superseded) is rebuilt by
replaying the chain, so there is no derived file that could drift from it.

Rules enforced here, in code:

- **Only a person decides.** :meth:`~ProposalStore.accept`, :meth:`~ProposalStore.edit_and_accept`,
  :meth:`~ProposalStore.reject` and :meth:`~ProposalStore.bulk_accept` raise
  :class:`ProposalError` unless ``actor == "human"``, before the lock is taken or any file is
  read. Replay ignores, and ``verify`` reports, any decision whose actor is not ``human``.
- **Hard bans hold at every step.** The domain plugin's guard (``hard_ban``) runs inside the
  lock on every proposal and again on everything a person accepts (with any edits merged in).
- **Bulk acceptance is narrow.** It takes only the listed ids, and only those still pending
  with an engine check of ``consistent``.
- **Only the system proposes a confirm step.** A ``stage.confirm`` is refused unless the system
  proposes it as the rule's; an agent's proposal is always recorded as made by an agent.
- **Agents cannot fill the inbox.** Agent-made proposals have their own, much smaller caps
  (pending proposals and bytes of history), so a flood from an agent never refuses a rule's,
  the model's or the system's proposal; a confirm step is never capped, like a decision.
- **Version check.** With ``expected_head``, a decision is ``stale`` when its own proposal
  changed or a person decided anything since that head (an agent's new proposals elsewhere
  never make a person's decision stale, so an agent cannot block a person by proposing).
- **Nothing is written for a refusal.** A refused or stale action writes nothing anywhere; the
  outcome says why, and the chain records only what happened.
- **A damaged inbox stops.** A chain that does not verify (or holds an entry replay rejects) is
  neither read nor extended; qPilot never repairs it silently.

The guard and the checker are called with data, never with the store: the guard runs while the
lock is held and must not open this inbox again.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from filelock import FileLock
from pydantic import ValidationError

from qpilot.core.decisions import MAX_REASON
from qpilot.core.store import INPUT_SHA, LOCK_TIMEOUT_S, _lines, _now, canonical_json
from qpilot.schemas import Actor
from qpilot.schemas_studio import (
    Proposal,
    ProposalCheck,
    ProposalEntry,
    ProposalOutcome,
    ProposalStatus,
)

if TYPE_CHECKING:
    from qpilot.core.store import StudyStore

Guard = Callable[[Proposal, list[Proposal]], "str | None"]
Checker = Callable[[Proposal], ProposalCheck]

PROPOSALS_FILE = "proposals.jsonl"
MAX_PAYLOAD_BYTES = 64 * 1024
MAX_PROPOSAL_BYTES = 256 * 1024
MAX_EVIDENCE = 200
MAX_LIST = 50  # alternatives, reasons, check rule ids
MAX_STRING = 2_000
MAX_PENDING = 2_000
MAX_CHAIN_BYTES = 64 * 1024 * 1024  # new proposals stop here; decisions never do
MAX_AGENT_PENDING = 200  # agents' own share: an agent flood never refuses anyone else
MAX_AGENT_BYTES = 4 * 1024 * 1024
SYSTEM_ONLY_KINDS = ("stage.confirm",)  # the confirm step of a person's click
HUMAN_ONLY = "only a person in qPilot Studio can accept, edit or reject a proposal"
STALE_REASON = "the inbox changed since you read it"
CONTRADICTED_REASON = "a reason is required to accept a proposal the engine's check contradicts"
ACTORS = ("human", "agent", "system")
STATUSES: tuple[str, ...] = ProposalStatus.__args__  # type: ignore[attr-defined]
DECISION_FIELDS = ("decided_by", "decided_at", "reason", "edits", "superseded_by")


def _slot(proposal: Proposal) -> tuple[str, str, str]:
    """What a newer proposal replaces: same kind, same subject, same kind of maker."""
    return proposal.kind, proposal.subject, proposal.made_by.kind


_SEPARATORS = re.compile("[  \u0085]+")


class ProposalError(ValueError):
    """An action on the inbox that is not allowed, malformed, or meets a damaged chain."""


# ---- hashing and verification -----------------------------------------------------------------


def proposal_entry_hash(entry: ProposalEntry) -> str:
    """sha256 of the entry's canonical JSON without ``hash`` and without None fields."""
    data = entry.model_dump(mode="json", exclude={"hash"}, exclude_none=True)
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def canonical_line(entry: ProposalEntry) -> str:
    """The exact line an entry is stored as (no trailing newline)."""
    return canonical_json(entry.model_dump(mode="json", exclude_none=True))


def verify_proposal_chain(entries: list[ProposalEntry], root: str) -> int | None:
    """Return the ``seq`` of the first entry whose link or hash is wrong, or None if intact."""
    prev = root
    for position, entry in enumerate(entries, start=1):
        if (
            entry.seq != position
            or entry.prev_hash != prev
            or entry.hash != proposal_entry_hash(entry)
        ):
            return position
        prev = entry.hash
    return None


def first_altered_line(lines: list[str], entries: list[ProposalEntry]) -> int | None:
    """The first line whose bytes are not the canonical form of the entry it parses to.

    The hash covers the parsed entry, so without this an extra field, a duplicate key or a
    missing default could be written into a line without breaking the chain.
    """
    for position, (line, entry) in enumerate(zip(lines, entries, strict=False), start=1):
        if line != canonical_line(entry):
            return position
    return None


def chain_lines(path: Path) -> list[str]:
    """The non-blank lines of a ``proposals.jsonl`` (split on newlines only)."""
    if not path.exists():
        return []
    return [line for line in _lines(path) if line.strip()]


# Chains verified in this process, by (root, study id, digest of the exact text) — see _load.
_VERIFIED: OrderedDict[tuple[str, str, bytes], tuple[tuple[ProposalEntry, ...], Replay]] = (
    OrderedDict()
)
_VERIFIED_LOCK = threading.Lock()
VERIFIED_KEPT = 64


def _verified(key: tuple[str, str, bytes]) -> tuple[list[ProposalEntry], Replay] | None:
    with _VERIFIED_LOCK:
        found = _VERIFIED.get(key)
        if found is None:
            return None
        _VERIFIED.move_to_end(key)
    entries, state = found
    return list(entries), _copy_replay(state)


def _keep_verified(
    key: tuple[str, str, bytes], entries: list[ProposalEntry], state: Replay
) -> None:
    with _VERIFIED_LOCK:
        _VERIFIED[key] = (tuple(entries), _copy_replay(state))
        while len(_VERIFIED) > VERIFIED_KEPT:
            _VERIFIED.popitem(last=False)


def _copy_replay(state: Replay) -> Replay:
    """A replay whose maps and lists are its own (writes apply their entry to the copy)."""
    return Replay(
        proposals=dict(state.proposals),
        proposed_at=dict(state.proposed_at),
        decided=list(state.decided),
        problems=list(state.problems),
        agent_bytes=state.agent_bytes,
    )


# ---- replay ------------------------------------------------------------------------------------


@dataclass
class Replay:
    """The inbox rebuilt from a chain: every proposal, in the order it was proposed."""

    proposals: dict[str, Proposal] = field(default_factory=dict)
    proposed_at: dict[str, int] = field(default_factory=dict)  # proposal id -> seq
    decided: list[str] = field(default_factory=list)  # accepted or edited, in chain order
    problems: list[str] = field(default_factory=list)
    agent_bytes: int = 0  # propose and supersede lines of agent-made proposals (set on load)


@dataclass(frozen=True)
class InboxView:
    """The inbox at one moment: its head, every proposal, and what a person accepted."""

    head: str
    proposals: list[Proposal]
    accepted: list[Proposal]  # in the order a person decided them, as :meth:`accepted` gives


def _step(state: Replay, entry: ProposalEntry, study_id: str | None) -> str | None:
    """Apply one entry to ``state``; return why it is invalid (state unchanged) or None."""
    pid = entry.proposal_id
    if entry.action == "propose":
        proposal = entry.proposal
        if proposal is None:
            return "a propose line without its proposal"
        if proposal.id != pid or pid in state.proposals:
            return "a proposal id that is not new"
        if proposal.status != "proposed" or any(
            getattr(proposal, f) is not None for f in DECISION_FIELDS
        ):
            return "a proposal that arrives already decided"
        if entry.reason or entry.edits is not None or entry.superseded_by is not None:
            return "a propose line with fields its action does not use"
        if study_id is not None and proposal.study_id != study_id:
            return "a proposal for another study"
        if proposal.made_by.kind == "person" and entry.actor != "human":
            return f"a proposal made by a person but proposed by {entry.actor}"
        state.proposals[pid] = proposal
        state.proposed_at[pid] = entry.seq
        return None
    if entry.proposal is not None:
        return "a full proposal on a line that does not propose it"
    current = state.proposals.get(pid)
    if current is None:
        return f"a {entry.action} of an unknown proposal"
    if current.status != "proposed":
        return f"a {entry.action} of a proposal that is already {current.status}"
    if entry.action == "supersede":
        newer = state.proposals.get(entry.superseded_by or "")
        if entry.actor != "system":
            return f"a supersede by {entry.actor}; only the system supersedes"
        if (
            newer is None
            or state.proposed_at[newer.id] <= state.proposed_at[pid]
            or _slot(newer) != _slot(current)
        ):
            return "a supersede without a newer proposal for the same subject from the same maker"
        if entry.reason or entry.edits is not None:
            return "a supersede line with fields its action does not use"
        state.proposals[pid] = current.model_copy(
            update={"status": "superseded", "superseded_by": newer.id}
        )
        return None
    if entry.actor != "human":
        return f"a decision ({entry.action}) by {entry.actor}; only a person decides"
    if entry.superseded_by is not None:
        return "a decision line with fields its action does not use"
    update: dict[str, Any] = {
        "decided_by": "human",
        "decided_at": entry.at,
        "reason": entry.reason or None,
    }
    if entry.action == "reject":
        if not entry.reason:
            return "a rejection without a reason"
        if entry.edits is not None:
            return "a rejection with edits"
        update["status"] = "rejected"
    else:
        if current.check.status == "contradicted" and not entry.reason:
            return "acceptance of a contradicted proposal without a reason"
        if entry.action == "accept":
            if entry.edits is not None:
                return "an acceptance with edits (that is an edit)"
            update["status"] = "accepted"
        else:
            if not entry.edits or not set(entry.edits) <= set(current.payload):
                return "edits that are not fields of the proposal"
            update.update(status="edited", edits=entry.edits)
        state.decided.append(pid)
    state.proposals[pid] = current.model_copy(update=update)
    return None


def replay(entries: Iterable[ProposalEntry], study_id: str | None = None) -> Replay:
    """Rebuild the inbox from its chain; invalid entries change nothing and are listed.

    ``study_id`` (the input's legacy id) is checked on every proposal when given.
    """
    state = Replay()
    for entry in entries:
        problem = _step(state, entry, study_id)
        if problem:
            state.problems.append(f"entry {entry.seq}: {problem}")
    return state


def changed_since(
    entries: list[ProposalEntry], root: str, expected_head: str, proposal_id: str
) -> bool:
    """Whether a decision on ``proposal_id`` made at ``expected_head`` is now out of date.

    It is when any later entry touches the same proposal, or when a person decided anything
    since; an agent's new proposals (and the supersedes they cause) elsewhere never count. A
    head that is not in the chain counts as changed.
    """
    heads = [root, *(e.hash for e in entries)]
    if expected_head not in heads:
        return True
    later = entries[heads.index(expected_head) :]
    return any(
        e.proposal_id == proposal_id
        or (e.actor == "human" and e.action in ("accept", "edit", "reject"))
        for e in later
    )


def proposal_id(proposal: Proposal, created_at: str, seq: int) -> str:
    """``p_`` + 16 hex of sha256 over kind, subject, payload, made_by, created_at and seq."""
    data = {
        "kind": proposal.kind,
        "subject": proposal.subject,
        "payload": proposal.payload,
        "made_by": proposal.made_by.model_dump(mode="json", exclude_none=True),
        "created_at": created_at,
        "seq": seq,
    }
    return "p_" + hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()[:16]


# ---- request cleaning ----------------------------------------------------------------------------


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _plain_json(value: Any, what: str) -> Any:
    """``value`` round-tripped through strict JSON; refuses NaN, infinity and non-JSON types."""
    try:
        text = json.dumps(value, allow_nan=False, ensure_ascii=False)
        text.encode("utf-8")
    except (TypeError, ValueError, RecursionError) as err:
        raise ProposalError(f"{what} must be plain JSON (no NaN, infinity or other types)") from err
    return json.loads(text)


def _check_strings(value: Any, what: str) -> None:
    if any(len(s) > MAX_STRING for s in _strings(value)):
        raise ProposalError(f"{what} holds text longer than {MAX_STRING:,} characters")


def clean_reason(reason: str | None, required: bool = False) -> str:
    """A decision's reason on one line, at most ``MAX_REASON`` characters (refused, not cut)."""
    if reason is None:
        reason = ""
    if not isinstance(reason, str):
        raise ProposalError("a reason must be text")
    cleaned = _SEPARATORS.sub(" ", reason).strip()
    if required and not cleaned:
        raise ProposalError("a reason is required")
    if len(cleaned) > MAX_REASON:
        raise ProposalError(f"reason longer than {MAX_REASON} characters")
    _plain_json(cleaned, "a reason")
    return cleaned


def clean_edits(edits: dict[str, Any]) -> dict[str, Any]:
    """A person's edits as plain JSON within the size caps (keys are checked under the lock)."""
    if not isinstance(edits, dict) or not edits:
        raise ProposalError("edits must be a non-empty object of payload fields")
    cleaned = _plain_json(edits, "edits")
    if len(canonical_json(cleaned).encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ProposalError(f"edits larger than {MAX_PAYLOAD_BYTES // 1024} KB")
    _check_strings(cleaned, "edits")
    return cleaned


def _require_human(actor: Any) -> None:
    # type() and not isinstance(): a str subclass could answer == "human" for anyone.
    if type(actor) is not str or actor != "human":
        raise ProposalError(HUMAN_ONLY)


def _check_maker(proposal: Proposal, actor: str) -> None:
    """Who may propose what: an agent's proposal is an agent's, a person's only a person's.

    Only the system proposes a confirm step, as the rule.
    """
    if actor == "agent" and proposal.made_by.kind != "agent":
        raise ProposalError("an agent's proposal is always recorded as made by an agent")
    if proposal.made_by.kind == "person" and actor != "human":
        raise ProposalError("only a person makes a proposal recorded as made by a person")
    if proposal.kind in SYSTEM_ONLY_KINDS and (
        actor != "system" or proposal.made_by.kind != "rule"
    ):
        raise ProposalError(
            f"only qPilot itself proposes a {proposal.kind}; a person confirms a stage in "
            "qPilot Studio"
        )


class _Copies:
    """Deep copies of the inbox's proposals for the guard, each made once per proposal state.

    One decision that settles many proposals (:meth:`ProposalStore.decide_together`) asks the
    guard once per item; copying the whole inbox for every question made a person's act of a
    few hundred items quadratic. A proposal is copied again only when the inbox holds a new
    object for it (its status changed). The original is kept beside its copy, so its identity
    can never be reused by another object while the copy is served.
    """

    def __init__(self) -> None:
        self._made: dict[str, tuple[Proposal, Proposal]] = {}

    def of(self, proposals: Iterable[Proposal]) -> list[Proposal]:
        out = []
        for p in proposals:
            hit = self._made.get(p.id)
            if hit is None or hit[0] is not p:
                hit = (p, p.model_copy(deep=True))
                self._made[p.id] = hit
            out.append(hit[1])
        return out


def _ask(
    guard: Guard | None,
    candidate: Proposal,
    current: list[Proposal],
    copies: _Copies | None = None,
) -> str | None:
    """The guard's refusal, on copies: a guard can read the inbox but never change it."""
    if guard is None:
        return None
    others = copies.of(current) if copies else [p.model_copy(deep=True) for p in current]
    refusal = guard(candidate.model_copy(deep=True), others)
    return str(refusal)[:500] if refusal else None


def _short(err: ValidationError) -> str:
    parts = []
    for item in err.errors()[:3]:
        where = ".".join(str(x) for x in item.get("loc", ())) or "proposal"
        parts.append(f"{where}: {item.get('msg', 'invalid')}")
    return "invalid proposal (" + "; ".join(parts) + ")"


# ---- the store -----------------------------------------------------------------------------------


class ProposalStore:
    """The inbox of one input file: append-only, hash-chained, decided only by a person.

    ``ProposalStore(store, study_id, guard)`` opens the inbox of a study or Studio session
    through the study store (``StudyStore.proposals`` does the same and also wires the domain
    plugin's guard and engine check). :meth:`at` opens one by folder and root.

    ``guard(proposal, current)`` is the plugin's hard-ban check: ``current`` is every proposal
    in the inbox with its present status; it returns a refusal reason or None. ``checker``,
    when given, replaces whatever ``check`` the caller put on a proposal with the engine's own.
    """

    def __init__(
        self,
        store: StudyStore,
        study_id: str,
        guard: Guard | None = None,
        *,
        checker: Checker | None = None,
    ) -> None:
        workspace, root = store.proposal_home(study_id)
        self._setup(workspace, root, guard, checker)

    @classmethod
    def at(
        cls,
        workspace: str | Path,
        root: str,
        guard: Guard | None = None,
        *,
        checker: Checker | None = None,
    ) -> ProposalStore:
        """The inbox kept in ``workspace``, chained from ``root`` (the input's sha256)."""
        inbox = cls.__new__(cls)
        inbox._setup(Path(workspace), root, guard, checker)
        return inbox

    def _setup(
        self, workspace: Path, root: str, guard: Guard | None, checker: Checker | None
    ) -> None:
        if not isinstance(root, str) or not INPUT_SHA.match(root):
            raise ValueError("the root of a proposal chain is an input file's sha256")
        self.workspace = workspace
        self.root = root
        self.study_id = root[:12]
        self.path = workspace / PROPOSALS_FILE
        self._guard = guard
        self._checker = checker

    # ---- reading --------------------------------------------------------------------------

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.workspace.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.workspace / ".lock"), timeout=LOCK_TIMEOUT_S):
            yield

    def _load(self) -> tuple[list[ProposalEntry], Replay]:
        """The chain and its replay; :class:`ProposalError` when it does not verify.

        A chain whose exact text was verified before (same root, same bytes) is not parsed and
        verified again: its entries and replay are reused (a fresh copy of the replay's lists and
        maps each time; proposals themselves are only ever replaced, never changed in place).
        """
        text = self.path.read_text(encoding="utf-8") if self.path.exists() else ""
        key = (self.root, self.study_id, hashlib.blake2b(text.encode("utf-8")).digest())
        known = _verified(key)
        if known is not None:
            return known
        entries, state = self._verify([line for line in text.split("\n") if line.strip()])
        _keep_verified(key, entries, state)
        return entries, state

    def _verify(self, lines: list[str]) -> tuple[list[ProposalEntry], Replay]:
        try:
            entries = [ProposalEntry.model_validate_json(line) for line in lines]
        except (ValueError, RecursionError) as err:
            raise ProposalError(f"{PROPOSALS_FILE} is damaged; qPilot will not use it") from err
        broken = verify_proposal_chain(entries, self.root)
        if broken is None:
            broken = first_altered_line(lines, entries)
        if broken is not None:
            raise ProposalError(f"{PROPOSALS_FILE} does not verify at entry {broken}")
        state = replay(entries, self.study_id)
        if state.problems:
            raise ProposalError(f"{PROPOSALS_FILE}: {state.problems[0]}")
        state.agent_bytes = sum(
            len(line.encode("utf-8")) + 1
            for line, entry in zip(lines, entries, strict=True)
            if entry.action in ("propose", "supersede")
            and state.proposals[entry.proposal_id].made_by.kind == "agent"
        )
        return entries, state

    def _read(self) -> tuple[list[ProposalEntry], Replay]:
        if not self.path.exists():
            return [], Replay()
        with self._locked():
            return self._load()

    def head(self) -> str:
        """Hash of the latest entry, or the input's sha256 when the inbox is empty."""
        entries, _ = self._read()
        return entries[-1].hash if entries else self.root

    def entries(self) -> list[ProposalEntry]:
        """Every entry of the chain, oldest first."""
        return self._read()[0]

    def snapshot(self) -> tuple[str, list[Proposal]]:
        """Head and every proposal, read together (pass the head back as ``expected_head``)."""
        entries, state = self._read()
        return (entries[-1].hash if entries else self.root), list(state.proposals.values())

    def view(self) -> InboxView:
        """Head, every proposal and what a person accepted, all from one read of the chain.

        Use it when one answer needs several of them (a stage's status and the design it
        confirms), so a decision made in between can never mix two moments.
        """
        entries, state = self._read()
        return InboxView(
            head=entries[-1].hash if entries else self.root,
            proposals=list(state.proposals.values()),
            accepted=[state.proposals[pid] for pid in state.decided],
        )

    def proposals(
        self, status: str | None = None, kind_prefix: str | None = None
    ) -> list[Proposal]:
        """Proposals in the order they were made, optionally by status and kind prefix."""
        if status is not None and status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        return [
            p
            for p in self._read()[1].proposals.values()
            if (status is None or p.status == status)
            and (kind_prefix is None or p.kind.startswith(kind_prefix))
        ]

    def get(self, proposal_id: str) -> Proposal:
        """One proposal by id; ``KeyError`` if unknown."""
        found = self._read()[1].proposals.get(proposal_id)
        if found is None:
            raise KeyError(f"unknown proposal {proposal_id!r}")
        return found

    def accepted(self, kind_prefix: str | None = None) -> list[Proposal]:
        """What a person accepted (as is or edited), in the order they decided it.

        This is the only view the engine may read. A later acceptance for the same kind and
        subject overrides an earlier one; pending, rejected and superseded proposals are never
        in it.
        """
        state = self._read()[1]
        return [
            state.proposals[pid]
            for pid in state.decided
            if kind_prefix is None or state.proposals[pid].kind.startswith(kind_prefix)
        ]

    # ---- proposing (any actor) --------------------------------------------------------------

    def propose(self, proposal: Proposal, actor: Actor) -> ProposalOutcome:
        """Add a proposal to the inbox as ``proposed``, or refuse it without writing anything.

        The status and every decision field are reset, the id and ``created_at`` are assigned
        here, and the engine's check replaces the caller's when a checker is set. Sizes are
        capped (refused, never cut): payload 64 KB, 200 evidence items, 50 alternatives or
        reasons, 2,000 characters per string, 256 KB in all, 2,000 pending proposals, and no new
        proposal once the chain holds 64 MB. Agent-made proposals count against their own
        share instead (200 pending, 4 MB of history), and a ``stage.confirm`` (the system's
        proposal for a person's confirm click) is never capped, like a person's decisions: a
        flood of proposals from an agent cannot stop a person deciding or confirming. An older
        pending proposal for the same kind and subject from the same kind of maker (rule, model
        or agent) is superseded in the same write; one from another maker stays pending beside
        it, so an agent can never push a rule's or the model's proposal out of the inbox.
        """
        if type(actor) is not str or actor not in ACTORS:
            raise ProposalError(f"actor must be one of {', '.join(ACTORS)}")
        try:
            clean = self._clean(proposal)
            _check_maker(clean, actor)
            if self._checker is not None:
                clean = clean.model_copy(update={"check": self._engine_check(clean)})
        except ProposalError as err:
            return ProposalOutcome(status="refused", head=self.head(), reason=str(err))
        with self._locked():
            entries, state = self._load()
            head = entries[-1].hash if entries else self.root
            current = list(state.proposals.values())
            pending = [p for p in current if p.status == "proposed"]
            reason = self._full(clean, pending, state)
            if reason:
                return ProposalOutcome(status="refused", head=head, reason=reason)
            refusal = _ask(self._guard, clean, current)
            if refusal:
                return ProposalOutcome(status="refused", head=head, reason=refusal)
            at = _now()
            pid = proposal_id(clean, at, len(entries) + 1)
            if pid in state.proposals:
                return ProposalOutcome(status="refused", head=head, reason="proposal id collision")
            stored = clean.model_copy(update={"id": pid, "created_at": at})
            new = [self._entry(entries, state, "propose", pid, actor, at, proposal=stored)]
            older = [p for p in pending if _slot(p) == _slot(stored)]
            for old in older:
                supersede = {"superseded_by": pid}
                new.append(
                    self._entry(
                        entries + new, state, "supersede", old.id, "system", at, **supersede
                    )
                )
            self._write(new)
            stored = state.proposals[pid]
        return ProposalOutcome(status="proposed", head=new[-1].hash, proposal=stored)

    def _full(self, proposal: Proposal, pending: list[Proposal], state: Replay) -> str | None:
        """Why the inbox takes no more proposals from this proposal's maker, or None.

        Agents fill only their own share, and nothing an agent wrote counts against anyone
        else's: the system's caps count the pending proposals and the history agents did not
        make. A confirm step is never refused for size.
        """
        if proposal.kind in SYSTEM_ONLY_KINDS:
            return None
        size = self.path.stat().st_size if self.path.exists() else 0
        by_agents = sum(1 for p in pending if p.made_by.kind == "agent")
        many = f"the inbox already holds {MAX_PENDING:,} pending proposals"
        full = f"the inbox is full ({MAX_CHAIN_BYTES // (1024 * 1024)} MB of history)"
        if proposal.made_by.kind != "agent":
            if len(pending) - by_agents >= MAX_PENDING:
                return many
            return full if size - state.agent_bytes >= MAX_CHAIN_BYTES else None
        if by_agents >= MAX_AGENT_PENDING:
            return f"agents already have {MAX_AGENT_PENDING:,} proposals waiting for a decision"
        if len(pending) >= MAX_PENDING:
            return many
        if state.agent_bytes >= MAX_AGENT_BYTES:
            share = MAX_AGENT_BYTES // (1024 * 1024)
            return f"agents have used their share of this inbox ({share} MB of history)"
        return full if size >= MAX_CHAIN_BYTES else None

    def _clean(self, proposal: Proposal) -> Proposal:
        """The proposal re-validated as plain JSON, undecided, and within the caps."""
        if not isinstance(proposal, Proposal):
            raise ProposalError("not a Proposal")
        raw = proposal.model_dump()
        raw.update({f: None for f in DECISION_FIELDS}, status="proposed", id="", created_at="")
        data = _plain_json(raw, "a proposal")
        if len(canonical_json(data).encode("utf-8")) > MAX_PROPOSAL_BYTES:
            raise ProposalError(f"a proposal larger than {MAX_PROPOSAL_BYTES // 1024} KB")
        try:
            clean = Proposal.model_validate(data)
        except ValidationError as err:
            raise ProposalError(_short(err)) from err
        if clean.study_id != self.study_id:
            raise ProposalError(f"this inbox takes proposals for study {self.study_id} only")
        if not clean.subject.strip():
            raise ProposalError("a proposal needs a subject")
        if len(canonical_json(clean.payload).encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise ProposalError(f"payload larger than {MAX_PAYLOAD_BYTES // 1024} KB")
        if len(clean.evidence) > MAX_EVIDENCE:
            raise ProposalError(f"more than {MAX_EVIDENCE} evidence items")
        if max(len(clean.alternatives), len(clean.reasons), len(clean.check.rule_ids)) > MAX_LIST:
            raise ProposalError(f"more than {MAX_LIST} alternatives, reasons or rule ids")
        _check_strings(clean.model_dump(mode="json"), "the proposal")
        return clean

    def _engine_check(self, proposal: Proposal) -> ProposalCheck:
        check = self._checker(proposal.model_copy(deep=True))  # type: ignore[misc]
        if not isinstance(check, ProposalCheck):
            raise ProposalError("the engine check did not return a ProposalCheck")
        data = _plain_json(check.model_dump(), "the engine's check")
        _check_strings(data, "the engine's check")
        return ProposalCheck.model_validate(data)

    # ---- deciding (a person only) -------------------------------------------------------------

    def accept(
        self, proposal_id: str, actor: Actor, reason: str = "", expected_head: str | None = None
    ) -> ProposalOutcome:
        """A person accepts a proposal as it is (a reason is required if the check contradicts)."""
        _require_human(actor)
        return self._decide(proposal_id, "accept", clean_reason(reason), None, expected_head)

    def edit_and_accept(
        self,
        proposal_id: str,
        actor: Actor,
        edits: dict[str, Any],
        reason: str,
        expected_head: str | None = None,
    ) -> ProposalOutcome:
        """A person changes some payload fields and accepts; edits may not add new fields."""
        _require_human(actor)
        cleaned = clean_edits(edits)
        return self._decide(proposal_id, "edit", clean_reason(reason), cleaned, expected_head)

    def reject(
        self, proposal_id: str, actor: Actor, reason: str, expected_head: str | None = None
    ) -> ProposalOutcome:
        """A person turns a proposal down, with a reason."""
        _require_human(actor)
        cleaned = clean_reason(reason, required=True)
        return self._decide(proposal_id, "reject", cleaned, None, expected_head)

    def bulk_accept(
        self,
        ids: Iterable[str],
        actor: Actor,
        reason: str = "",
        expected_head: str | None = None,
    ) -> list[ProposalOutcome]:
        """A person accepts exactly the listed proposals that are pending and ``consistent``.

        Anything else on the list (contradicted, cannot be checked, settled, unknown, listed
        twice, or refused by the guard) comes back ``refused`` with a reason, and a proposal
        changed since ``expected_head`` comes back ``stale``. One chain entry per accepted
        proposal, all in one locked write; outcomes are in the order of ``ids``.
        """
        _require_human(actor)
        cleaned = clean_reason(reason)
        ids = list(ids)
        if len(ids) > MAX_PENDING or not all(isinstance(i, str) for i in ids):
            raise ProposalError(f"bulk acceptance takes up to {MAX_PENDING:,} proposal ids")
        results: list[tuple[str, Proposal | None, str | None]] = []
        with self._locked():
            entries, state = self._load()
            before = list(entries)
            new: list[ProposalEntry] = []
            seen: set[str] = set()
            for pid in ids:
                current = state.proposals.get(pid)
                if current is None or pid in seen:
                    why = "unknown proposal" if current is None else "listed twice"
                    results.append(("refused", current, why))
                    continue
                seen.add(pid)
                if expected_head is not None and changed_since(
                    before, self.root, expected_head, pid
                ):
                    results.append(("stale", current, STALE_REASON))
                    continue
                if current.status != "proposed":
                    results.append(("refused", current, f"already {current.status}"))
                    continue
                if current.check.status != "consistent":
                    why = f"the engine's check is {current.check.status}; decide it on its own"
                    results.append(("refused", current, why))
                    continue
                refusal = self._guarded(current, None, state)
                if refusal:
                    results.append(("refused", current, refusal))
                    continue
                at = _now()
                new.append(
                    self._entry(entries + new, state, "accept", pid, "human", at, reason=cleaned)
                )
                results.append(("accepted", state.proposals[pid], None))
            if new:
                self._write(new)
            head = (entries + new)[-1].hash if entries or new else self.root
        return [
            ProposalOutcome(status=status, head=head, proposal=p, reason=why)  # type: ignore[arg-type]
            for status, p, why in results
        ]

    def decide_together(
        self,
        new: Iterable[tuple[Proposal, str]],
        pending: Iterable[tuple[str, str]],
        actor: Actor,
        reason: str,
        *,
        proposer: Actor = "system",
        expected_head: str | None = None,
    ) -> list[ProposalOutcome]:
        """One click of a person that settles several proposals at once: all of it, or nothing.

        ``new`` are proposals made for this click by ``proposer`` (qPilot's rule, say), each
        with the person's answer (``"accept"`` or ``"reject"``); ``pending`` are proposal ids
        already waiting in the inbox (an agent's request) with the person's answer to each.
        Each new proposal is cleaned, checked and capped as :meth:`propose` does (an older
        pending proposal in its slot is superseded), and each answer is held to the rules of
        :meth:`accept` and :meth:`reject`: only a person, the guard on what is accepted, a
        settled proposal refused. The reason is required (one click decides many).

        Everything is written in one locked write, in order (each new proposal's ``propose``
        line followed by the person's answer, then the answers to the pending ones). When any
        item is refused, or a person decided anything since ``expected_head`` (or a listed
        pending proposal changed since), nothing is written and every outcome is ``refused``
        (or ``stale``) with the reason.
        """
        _require_human(actor)
        if type(proposer) is not str or proposer not in ACTORS:
            raise ProposalError(f"actor must be one of {', '.join(ACTORS)}")
        cleaned = clean_reason(reason, required=True)
        new, pending = list(new), list(pending)
        if not new and not pending:
            raise ProposalError("nothing to decide")
        if len(new) + len(pending) > MAX_PENDING:
            raise ProposalError(f"one decision settles up to {MAX_PENDING:,} proposals")
        if any(action not in ("accept", "reject") for _, action in [*new, *pending]):
            raise ProposalError("each proposal is accepted or rejected")
        if len({pid for pid, _ in pending}) != len(pending):
            raise ProposalError("a proposal is listed twice")
        count = len(new) + len(pending)

        def every(status: str, why: str, head: str) -> list[ProposalOutcome]:
            return [ProposalOutcome(status=status, head=head, reason=why) for _ in range(count)]  # type: ignore[arg-type]

        made: list[tuple[Proposal, str]] = []
        try:
            for proposal, action in new:
                clean = self._clean(proposal)
                _check_maker(clean, proposer)
                if self._checker is not None:
                    clean = clean.model_copy(update={"check": self._engine_check(clean)})
                made.append((clean, action))
        except ProposalError as err:
            return every("refused", str(err), self.head())
        with self._locked():
            entries, state = self._load()
            head = entries[-1].hash if entries else self.root
            if expected_head is not None and any(
                changed_since(entries, self.root, expected_head, pid)
                for pid in [*(pid for pid, _ in pending), ""]
            ):
                return every("stale", STALE_REASON, head)
            written: list[ProposalEntry] = []
            done: list[tuple[str, str]] = []
            copies = _Copies()  # the guard's copies of the inbox, made once per proposal state
            at = _now()  # one click, one moment
            for clean, action in made:
                current = list(state.proposals.values())
                waiting = [p for p in current if p.status == "proposed"]
                refusal = self._full(clean, waiting, state) or _ask(
                    self._guard, clean, current, copies
                )
                if refusal:
                    return every("refused", refusal, head)
                pid = proposal_id(clean, at, len(entries) + len(written) + 1)
                if pid in state.proposals:
                    return every("refused", "proposal id collision", head)
                stored = clean.model_copy(update={"id": pid, "created_at": at})
                written.append(
                    self._entry(
                        entries + written, state, "propose", pid, proposer, at, proposal=stored
                    )
                )
                for old in [p for p in waiting if _slot(p) == _slot(stored)]:
                    written.append(
                        self._entry(
                            entries + written, state, "supersede", old.id, "system", at,
                            superseded_by=pid,
                        )
                    )  # fmt: skip
                done.append((pid, action))
            for pid, action in pending:
                current = state.proposals.get(pid)
                if current is None:
                    return every("refused", f"unknown proposal {pid!r}", head)
                if current.status != "proposed":
                    return every("refused", f"this proposal is already {current.status}", head)
                done.append((pid, action))
            for pid, action in done:
                if action == "accept":
                    refusal = self._guarded(state.proposals[pid], None, state, copies)
                    if refusal:
                        return every("refused", refusal, head)
                written.append(
                    self._entry(entries + written, state, action, pid, "human", at, reason=cleaned)
                )
            self._write(written)
            head = written[-1].hash
            return [
                ProposalOutcome(
                    status=state.proposals[pid].status, head=head, proposal=state.proposals[pid]
                )
                for pid, _ in done
            ]

    def _decide(
        self,
        proposal_id: str,
        action: str,
        reason: str,
        edits: dict[str, Any] | None,
        expected_head: str | None,
    ) -> ProposalOutcome:
        with self._locked():
            entries, state = self._load()
            head = entries[-1].hash if entries else self.root
            current = state.proposals.get(proposal_id)
            if current is None:
                raise KeyError(f"unknown proposal {proposal_id!r}")
            if expected_head is not None and changed_since(
                entries, self.root, expected_head, proposal_id
            ):
                return ProposalOutcome(
                    status="stale", head=head, proposal=current, reason=STALE_REASON
                )
            if current.status != "proposed":
                return ProposalOutcome(
                    status="refused",
                    head=head,
                    proposal=current,
                    reason=f"this proposal is already {current.status}",
                )
            if action != "reject" and current.check.status == "contradicted" and not reason:
                raise ProposalError(CONTRADICTED_REASON)
            if edits is not None and not set(edits) <= set(current.payload):
                extra = sorted(set(edits) - set(current.payload))
                raise ProposalError(f"edits may change payload fields only, not add {extra}")
            if action != "reject":
                refusal = self._guarded(current, edits, state)
                if refusal:
                    return ProposalOutcome(
                        status="refused", head=head, proposal=current, reason=refusal
                    )
            entry = self._entry(
                entries, state, action, proposal_id, "human", _now(), reason=reason, edits=edits
            )
            self._write([entry])
            updated = state.proposals[proposal_id]
        return ProposalOutcome(status=updated.status, head=entry.hash, proposal=updated)

    # ---- internals ----------------------------------------------------------------------------

    def _guarded(
        self,
        proposal: Proposal,
        edits: dict[str, Any] | None,
        state: Replay,
        copies: _Copies | None = None,
    ) -> str | None:
        """The guard's refusal of what would take effect (edits merged in), or None."""
        effective = proposal
        if edits:
            effective = proposal.model_copy(update={"payload": {**proposal.payload, **edits}})
        others = [p for p in state.proposals.values() if p.id != proposal.id]
        return _ask(self._guard, effective, others, copies)

    def _entry(
        self,
        entries: list[ProposalEntry],
        state: Replay,
        action: str,
        pid: str,
        actor: str,
        at: str,
        **fields: Any,
    ) -> ProposalEntry:
        """Build the next entry, apply it to ``state`` exactly as replay will, and return it."""
        entry = ProposalEntry(
            seq=len(entries) + 1,
            prev_hash=entries[-1].hash if entries else self.root,
            action=action,  # type: ignore[arg-type]
            proposal_id=pid,
            actor=actor,  # type: ignore[arg-type]
            at=at,
            **{k: v for k, v in fields.items() if v is not None},
        )
        entry = entry.model_copy(update={"hash": proposal_entry_hash(entry)})
        # What is written must read back as the same entry, or the chain would not verify.
        again = ProposalEntry.model_validate_json(canonical_line(entry))
        if (
            canonical_line(again) != canonical_line(entry)
            or proposal_entry_hash(again) != entry.hash
        ):
            raise ProposalError("this entry would not read back as written")
        problem = _step(state, again, self.study_id)
        if problem:
            raise ProposalError(f"refusing to write {problem}")
        return again

    def _write(self, entries: list[ProposalEntry]) -> None:
        text = "".join(canonical_line(e) + "\n" for e in entries)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())


__all__ = [
    "PROPOSALS_FILE",
    "SYSTEM_ONLY_KINDS",
    "InboxView",
    "ProposalError",
    "ProposalStore",
    "Replay",
    "canonical_line",
    "chain_lines",
    "changed_since",
    "clean_reason",
    "first_altered_line",
    "proposal_entry_hash",
    "proposal_id",
    "replay",
    "verify_proposal_chain",
]
