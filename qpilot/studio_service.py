"""qPilot Studio's operations: the one place the dashboard, the CLI and the MCP tools go through.

Studio sits between the instrument and GraphPad Prism. The AI does the preparation work (it
proposes the study design, calls every curve and drafts the Prism project); the deterministic
engine checks every proposal and computes every number; the scientist decides. Each stage is a
set of proposals in the session's hash-chained inbox (``core/proposals.py``) and ends with a
``stage.confirm`` proposal that only a person can accept:

==========  ==============================================================================
stage       what the scientist confirms
==========  ==============================================================================
design      well roles, groups, biological units, reference genes (blind: no conclusion)
curves      which curves count as amplified, and each disagreement that matters (blind)
choices     the Decision Cards (reference set, cut-off, empty wells, amplification call), and
            which further choices the grid tests (the efficiency models, opt-in)
prism       the Prism project: tables, test, graph, caption (then Send to Prism)
roundtrip   what changed in Prism, each exclusion with a reason and its consequence
==========  ==============================================================================

**Blind stages.** No conclusion, fold change, card or Prism preview is returned before the
design and curve stages are confirmed: the design is a fact about the experiment and is decided
on evidence, never on the answer it gives. Internally the engine may run (to say that an
ambiguity "matters for at least one conclusion"), but only that boolean leaves this module.

**Who acts.** Rules and the in-app model propose as ``system``; MCP agents propose as ``agent``
through the MCP server; only ``human`` accepts, edits or rejects (refused in code by the
proposal store, whoever calls this module). Writing a Prism bundle or launching Prism also needs
``actor == "human"``.

**Round-trip consequences hold or are refused.** Each exclusion's consequence is computed on top
of the exclusions a person accepted since the export (its ``basis``) and says what all the
exclusions found together do. Accepting one recomputes the others at once; a question whose
basis no longer matches is shown as out of date and cannot be accepted.
"""

from __future__ import annotations

import copy
import inspect
import json
import logging
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from filelock import FileLock

from qpilot.core.proposals import InboxView
from qpilot.core.store import (
    ON_DEMAND_KINDS,
    SheetChanged,
    StudyNotFound,
    StudyStore,
    atomic_write,
    canonical_json,
    dump_json,
)
from qpilot.io import trust
from qpilot.schemas import Actor, DecisionCard
from qpilot.schemas_studio import (
    TEXT_ID,
    DesignField,
    Evidence,
    ImportTrust,
    InspectSummary,
    MadeBy,
    MarkerSplit,
    Proposal,
    ProposalCheck,
    ProposalOutcome,
    QuarantineEntry,
    StudyDesign,
)

log = logging.getLogger(__name__)

STAGES: tuple[str, ...] = ("design", "curves", "choices", "prism", "roundtrip")
BLIND_STAGES: tuple[str, ...] = ("design", "curves")
STAGE_KINDS = {
    "design": "design.",
    "curves": "curve.",
    "choices": "choice.",  # the Decision Cards, and which further choices the grid tests
    "prism": "prism.project",
    "roundtrip": ("prism.exclusion_reason", "prism.value_edit"),
}
STUDIO_FILE = "studio.json"
AI_CALLS_FILE = "ai_calls.jsonl"
CURVE_JUDGE_FILE = "curve_judge_calls.json"
MAX_WELL_PROPOSALS = 400
PRISM_WAIT_S = 120.0
PING_TTL_S = 60.0  # how long a model's answer (or silence) to a one-token request is trusted
PING_TIMEOUT_S = 10.0  # the one-token request gives up after this (it runs in the background)
PING_WAIT_S = 2.0  # the longest a caller (a page render) waits for an answer not known yet
BLANK_DESIGN_ID = "studio_blank"
CURVE_JUDGE_UNREADABLE = "unable to read this file"
#: The curves round's note on what the inbox lists (the page's sentence says it once, with counts).
CURVE_JUDGE_LISTED = (
    "Curve Judge disagreements that could change a conclusion are listed one well each; "
    "the others change no conclusion and are not listed"
)
EXCLUSION_KIND = "prism.exclusion_reason"
EXCLUDE_KIND = "curve.exclude_well"  # a well left out of (or put back into) the analysis
TRUST_KIND = "curve.import_trust"  # a person's option on the Import Trust card (qpilot/io/trust.py)
PURPOSE_KIND = "design.purpose"  # what the study is for (compare groups / quantify samples)
#: Kinds a person accepts only with a reason (a well left out and an Import Trust choice are
#: never in "Accept all consistent": each is accepted on its own, or by a card's one click).
REASON_KINDS = (EXCLUSION_KIND, EXCLUDE_KIND, TRUST_KIND)
GATE_KEEP = "keep"  # a Run Gate card's option "keep every well (the analysis as it stands)"
GATE_MAKER = "qpilot-run-gate"
TRUST_STALE = (
    "the analysis changed since the Import Trust card was read; read it again (it is shown at "
    "the new analysis)"
)
GATE_STALE = (
    "the analysis changed since the controls were checked; read them again (they are checked "
    "at the new analysis)"
)
TRACE_STALE = (
    "the analysis changed since the place was traced; trace it again (it is shown at the new "
    "analysis)"
)
STALE_EXCLUSIONS = (
    "its consequence was computed before the exclusions accepted since then; read what Prism "
    "sent back again (Round trip) for numbers that hold"
)
STALE_CHOICES = (
    "its consequence was computed at analysis choices that have changed since; export again "
    "and send the tables back from the new project"
)
NOT_CHECKED = (
    "not checked yet: “Check connection” sends one short request to {provider}; qPilot never "
    "contacts a remote model just to show its status"
)
STALE_EXPORT = "its consequence belongs to a bundle that was not sent to Prism from this session"


class StudioError(ValueError):
    """A Studio action that cannot be taken now (wrong stage, missing input, not a person)."""


@dataclass(frozen=True)
class StageStatus:
    """Where one stage stands: reachable, confirmed, what is pending, what blocks it."""

    stage: str
    open: bool
    confirmed: bool
    pending: int
    blockers: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready."""
        return {
            "stage": self.stage,
            "open": self.open,
            "confirmed": self.confirmed,
            "pending": self.pending,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class Assembly:
    """The design assembled from a session's accepted proposals, or why there is none yet."""

    design: StudyDesign | None
    blockers: list[str]
    design_hash: str = ""
    curves_hash: str = ""


@dataclass(frozen=True)
class GateChoice:
    """One option of a Run Gate card as the gate measured it (built by the server, never sent).

    ``wells`` are what the option leaves out (none for ``keep``); ``universe`` every well any
    option of the card leaves out. ``matters``: the option (for ``keep``, any option) changes a
    call at the analysis in use. ``study_id`` is the analysis the gate measured.
    """

    study_id: str
    card_id: str
    rule_id: str
    verdict: str
    where: str
    option: str
    label: str
    wells: tuple[str, ...]
    universe: tuple[str, ...]
    matters: bool
    pack: str

    @property
    def verdict_words(self) -> str:
        """The verdict as a verb ("fails", "warns")."""
        return {"fail": "fails", "warn": "warns"}.get(self.verdict, self.verdict)


@dataclass(frozen=True)
class GateDecision:
    """What a choice on a Run Gate card did: wells left out or put back, a keep recorded, or not.

    ``status``: ``left_out`` / ``put_back`` / ``kept`` (a person's choice, written), or
    ``pending_human`` (an agent's request, filed), ``stale`` or ``refused`` (nothing written).
    ``not_put_back`` are wells left out another way (a Prism round trip) that "keep" leaves as
    they are.
    """

    status: str
    head: str
    left_out: list[str] = field(default_factory=list)
    put_back: list[str] = field(default_factory=list)
    not_put_back: list[str] = field(default_factory=list)
    proposals: list[Proposal] = field(default_factory=list)
    reason: str | None = None


@dataclass(frozen=True)
class TrustDecision:
    """What a choice on the Import Trust card did.

    ``status``: ``decided`` (a person's choice, written; ``changed`` when the analysis is not the
    one it was, so the study is analysed again), ``pending_human`` (an agent's request, filed),
    ``stale`` or ``refused`` (nothing written).
    """

    status: str
    head: str
    option: str | None = None
    changed: bool = False
    proposals: list[Proposal] = field(default_factory=list)
    reason: str | None = None


@dataclass(frozen=True)
class _GatePlan:
    """How the inbox gets a gate choice: wells that change, and the proposals that do it."""

    changes: list[tuple[str, bool]]  # well -> left out, for every well whose state changes
    new: list[tuple[str, bool]]  # the changes no waiting proposal already asks for
    settle: list[tuple[str, str]]  # waiting proposals (id, accept | reject)
    elsewhere: list[str]  # left out another way (a Prism round trip): "keep" leaves them


# ---- Trace: a person sets wells aside from Where to look (the decide_trace block) -------------

TRACE_MAKER = "qpilot-trace"  # the rule that proposes the exclusions of a Trace decision
TRACE_MODEL = "trace-v1"


@dataclass(frozen=True)
class TraceChoice:
    """One option at one place Trace pointed at (built by the server from the trace, never sent).

    The shape :func:`_gate_plan` reads (``card_id``, ``option``, ``wells``, ``universe``):
    ``wells`` are what the option leaves out (none for ``keep``), ``universe`` every well any
    set-aside of the place leaves out (what "keep" can put back), ``place_wells`` the place's
    own wells (recorded when a keep changes nothing). ``matters``: the option (for ``keep``,
    any option) changes a call at the analysis in use. ``study_id`` is the analysis traced.
    """

    study_id: str
    card_id: str
    option: str
    label: str
    where: str
    sample: str
    well: str | None
    checks: tuple[str, ...]
    wells: tuple[str, ...]
    universe: tuple[str, ...]
    place_wells: tuple[str, ...]
    matters: bool


@dataclass
class TraceSetAside:
    """Wells a person set aside from one Trace place that are out of the analysis now."""

    card_id: str
    option: str
    sample: str
    well: str | None
    reason: str
    decided_at: str
    matters: bool
    wells: list[str]


@dataclass
class _Ping:
    """What one model configuration last said to a one-token request, and the request out."""

    at: float | None = None  # time.monotonic() of the last answer (or failure); None: none yet
    answers: bool | None = None
    reason: str | None = None
    thread: threading.Thread | None = None


def _require_human(actor: str, what: str) -> None:
    if type(actor) is not str or actor != "human":
        raise StudioError(f"only a person can {what}")


def _evidence(cites: Sequence[str]) -> list[Evidence]:
    out = []
    for cite in cites:
        kind = "text" if TEXT_ID.match(cite) else "cell" if "!" in cite else "sample"
        out.append(Evidence(kind=kind, ref=cite))
    return out


class Studio:
    """Studio's operations over one study store (the dashboard and MCP share it on disk).

    Args:
        store: The study store (default: ``QPILOT_STUDIES_DIR``).
        client: The model client for the Design Interpreter and the Prism draft. ``None``
            means Studio's default (a local model when one answers, else the rules alone).
    """

    def __init__(self, store: StudyStore | None = None, client: Any = None) -> None:
        self.store = store or StudyStore()
        self._client = client
        self._not_configured: str | None = None  # why the configured model could not be built
        self._pings: dict[tuple[str, str | None, str | None], _Ping] = {}  # per model config
        self._ping_lock = threading.Lock()

    # ---- the model ------------------------------------------------------------------------

    @property
    def client(self) -> Any:
        """The model client (Studio's local default, created on first use)."""
        if self._client is None:
            from qpilot.ai.client import ModelClient, ModelUnavailable, NoneBackend, make_backend

            try:
                from qpilot.ai.config import studio_config
            except ImportError:  # an AI layer without the Studio default: environment only
                self._client = ModelClient.from_env()
            else:
                backend: Any
                try:
                    backend = make_backend(studio_config())
                except (ModelUnavailable, ValueError) as err:  # misconfigured: say why
                    self._not_configured = str(err)[:300]
                    backend = NoneBackend()  # and use the rules alone
                self._client = ModelClient(backend=backend)
        return self._client

    def model_status(self, check: bool = False) -> dict[str, Any]:
        """Which model Studio uses, whether it answers, and whether anything leaves this machine.

        ``available`` is True only when a model is configured and answered a one-token request.
        That request is asked at most once a minute per model configuration, in the background:
        only the call that asks it first waits, for at most :data:`PING_WAIT_S` seconds; every
        other call returns the last known answer at once (``answers`` None and ``checking`` True
        while there is none), so a page render never stalls on an endpoint that does not answer.
        A real call's outcome counts too. When the model is not available, ``reason`` says why
        (not configured or misconfigured, the endpoint refused or timed out, an HTTP error such
        as a model that is not pulled), so a down local model is never shown as working, nor as
        "no model". A remote model is asked only with ``check`` (the person's "Check
        connection"); otherwise its last known answer is returned and nothing leaves the machine.
        """
        local = self._local()
        answers, reason = self._answers(ask=local or check)
        configured = bool(self.client.available)
        return {
            "provider": self.client.provider,
            "model": self.client.model,
            "available": configured and answers is True,
            "configured": configured,
            "answers": answers,
            "checking": configured and answers is None and (local or check),
            "misconfigured": self._not_configured is not None,
            "reason": reason,
            "local": local,
            "sample_names": "sent as quoted data"
            if local
            else "replaced by pseudonyms before anything leaves this machine",
        }

    def _endpoint(self) -> str | None:
        backend = self.client.backend
        endpoint = getattr(backend, "url", None) or getattr(
            getattr(backend, "config", None), "endpoint", None
        )
        return str(endpoint) if endpoint else None

    def _local(self) -> bool:
        """True when nothing the model is sent can leave this machine."""
        from qpilot.core.pseudonym import endpoint_is_local

        provider = self.client.provider
        return provider in ("none", "mock") or endpoint_is_local(provider, self._endpoint())

    def _model_key(self) -> tuple[str, str | None, str | None]:
        """The model configuration a ping answer belongs to: provider, model, endpoint."""
        return str(self.client.provider), self.client.model, self._endpoint()

    def _answers(self, ask: bool = True) -> tuple[bool | None, str | None]:
        """Whether the model answers a one-token request, and why not (None: not known yet).

        The request runs on a background thread, at most once per :data:`PING_TTL_S` for each
        model configuration. The last known answer is returned at once; only the call that
        starts the very first request waits for it, at most :data:`PING_WAIT_S` seconds.
        """
        client = self.client
        if not client.available:
            return False, self._not_configured or "no model is configured"
        if client.provider == "mock":  # canned replies: nothing to reach, and none to spend
            return True, None
        key = self._model_key()
        waiting: threading.Thread | None = None
        if not ask:  # a remote model is never contacted just to show its status
            with self._ping_lock:
                known = self._pings.get(key)
                if known is not None and known.at is not None:
                    return known.answers, known.reason
            return None, NOT_CHECKED.format(provider=client.provider)
        with self._ping_lock:
            ping = self._pings.setdefault(key, _Ping())
            due = ping.at is None or time.monotonic() - ping.at > PING_TTL_S
            if due and (ping.thread is None or not ping.thread.is_alive()):
                ping.thread = threading.Thread(
                    target=self._ping,
                    args=(key, client.backend),
                    name="qpilot-model-ping",
                    daemon=True,
                )
                ping.thread.start()
                if ping.at is None:  # nothing known yet: the call that asks waits a little
                    waiting = ping.thread
        if waiting is not None:
            waiting.join(PING_WAIT_S)
        with self._ping_lock:
            return ping.answers, ping.reason

    def _ping(self, key: tuple[str, str | None, str | None], backend: Any) -> None:
        """Send the one-token request (on its own thread) and remember the answer."""
        probe = copy.copy(backend)
        if hasattr(probe, "timeout"):
            probe.timeout = min(float(probe.timeout), PING_TIMEOUT_S)
        try:
            probe.complete("Reply with OK.", [{"role": "user", "content": "OK?"}], 1, 0.0)
        except Exception as err:  # any failure means "not answering"; keep why
            answer: tuple[bool, str | None] = (False, _why_not(err))
        else:
            answer = (True, None)
        with self._ping_lock:
            ping = self._pings.setdefault(key, _Ping())
            ping.at, (ping.answers, ping.reason) = time.monotonic(), answer

    def _heard(self, down: bool, why: str | None) -> str | None:
        """Remember what a real call showed about the model; return the most precise reason.

        A failure the last ping already explained more precisely (with its HTTP status, say)
        keeps the ping's words, on the status line and in the propose report alike.
        """
        with self._ping_lock:
            ping = self._pings.setdefault(self._model_key(), _Ping())
            known = ping.reason if ping.answers is False else None
            if down and why and known and known != why and known.startswith(why):
                why = known
            ping.at, ping.answers, ping.reason = time.monotonic(), not down, why if down else None
        return why

    # ---- the session ------------------------------------------------------------------------

    def open(
        self,
        rdml_path: str | Path,
        sheet_path: str | Path | None = None,
        *,
        actor: Actor = "human",
    ) -> str:
        """Open the Studio session of an input file (and optional sample sheet); return its id.

        The file is inspected once (every name quarantined); nothing is analysed and nothing is
        proposed yet. A person's open binds the file and the sheet they opened (none means
        none). Anyone else (an agent's ``qpcr_inspect``) reopens an existing session exactly as
        a person bound it: its input file and sheet never change, and a different sheet is
        refused, so an agent can never put its own cells behind the rules' proposals.
        """
        from qpilot.qpcr.design_checks import register_declared
        from qpilot.qpcr.inspect import file_facts

        file_facts(rdml_path, sheet_path)  # an unreadable file or sheet is refused before binding
        try:
            session_id = self.store.open_session(rdml_path, sheet_path, rebind=actor == "human")
        except ValueError as err:
            raise StudioError(str(err)) from err
        facts = self.facts(session_id)  # the bound input and sheet, which may predate this call
        entries = [(e.value, e.origin) for e in facts.quarantine]
        self.store.quarantine(session_id).add_many(entries)
        register_declared(session_id, facts)  # the hard bans see the sheet's units from now on
        return session_id

    def _folder(self, session_id: str) -> Path:
        return self.store.find_session(session_id)

    def _meta(self, session_id: str) -> dict[str, Any]:
        path = self._folder(session_id) / STUDIO_FILE
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _update_meta(self, session_id: str, update: dict[str, Any]) -> None:
        self._edit_meta(session_id, lambda meta: meta.update(update))

    def _edit_meta(self, session_id: str, change: Callable[[dict[str, Any]], Any]) -> None:
        """Read, change and write the session's ``studio.json`` under its lock."""
        folder = self._folder(session_id)
        with FileLock(str(folder / ".lock"), timeout=30):
            meta = self._meta(session_id)
            change(meta)
            atomic_write(folder / STUDIO_FILE, dump_json(meta))

    def source(self, session_id: str) -> Path:
        """The session's input file; ``StudioError`` when it is missing or has changed."""
        path = self.store.session_source(session_id)
        if path is None:
            raise StudioError("the input file is missing or has changed since it was opened")
        return path

    def sheet(self, session_id: str) -> Path | None:
        """The session's sample sheet, when it has one and it is unchanged."""
        try:
            return self.store.session_sheet(session_id)
        except SheetChanged as err:
            raise StudioError(str(err)) from err

    def facts(self, session_id: str) -> Any:
        """The file's facts (summary, quarantine, wells), cached in the process."""
        from qpilot.qpcr.inspect import file_facts

        return file_facts(self.source(session_id), self.sheet(session_id))

    def summary(self, session_id: str) -> InspectSummary:
        """What the file declares, before any design (names are ids and ``text_id``s)."""
        return self.facts(session_id).summary

    def quarantined(self, session_id: str) -> list[QuarantineEntry]:
        """Every quarantined text of the session (sample names, sheet cells, the sentence)."""
        return self.store.quarantine(session_id).all()

    def inbox(
        self, session_id: str, stage: str | None = None, status: str | None = None
    ) -> list[Proposal]:
        """The session's proposals (every stage, or one), in chain order."""
        proposals = self.store.proposals(session_id).proposals(status=status)
        if stage is None:
            return proposals
        return [p for p in proposals if _in_stage(p, stage)]

    def head(self, session_id: str) -> str:
        """The proposal chain's head (for ``expected_head`` version checks)."""
        return self.store.proposals(session_id).head()

    def _log_calls(self, session_id: str, purpose: str, metas: Sequence[dict[str, Any]]) -> None:
        folder = self._folder(session_id)
        lines = "".join(
            canonical_json({**meta, "purpose": purpose, "at": _now()}) + "\n" for meta in metas
        )
        if lines:
            with FileLock(str(folder / ".lock"), timeout=30):
                with open(folder / AI_CALLS_FILE, "a", encoding="utf-8", newline="\n") as fh:
                    fh.write(lines)

    # ---- stage 1: the design ----------------------------------------------------------------

    def propose_design(self, session_id: str, sentence: str = "") -> dict[str, Any]:
        """The Design Interpreter: rules always, the model when one answers; all as proposals.

        ``sentence`` (the scientist's one line about the experiment) is quarantined like any
        file text and reaches the model only as quoted data. The report's ``fallback`` is True
        only when no model field was used at all; ``model_fields`` counts the fields the model
        made, and ``model_error`` says why the model was not used, or not for every part
        (also written with the calls in ``ai_calls.jsonl``): a misconfigured model says what is
        wrong with its configuration. Whatever happens in the Design Interpreter, the rules'
        proposals are stored.
        """
        from qpilot.qpcr.design_rules import propose_from_names, purpose_field

        facts = self.facts(session_id)
        quarantine = self.store.quarantine(session_id)
        if sentence.strip():
            quarantine.add(sentence.strip(), "studio:sentence")
        entries = quarantine.all()
        rule_fields = propose_from_names(facts.summary, entries, facts=facts)
        presets = _preset_fields(facts.summary)
        purpose = None if presets else purpose_field(rule_fields, facts)
        rule_fields = [*presets, *rule_fields, *([purpose] if purpose else [])]
        notes: list[str] = []
        makers: list[MadeBy] = [MadeBy(kind="rule")] * len(rule_fields)
        fields: list[DesignField] = list(rule_fields)
        rejected: list[dict[str, Any]] = []
        why: str | None = None  # why the model was not used, or not for every part
        used = 0  # fields the model made
        if self._not_configured is not None:  # the client is the rules alone: say why
            why = f"the configured model cannot be used: {self._not_configured}"
        try:
            from qpilot.ai.interpret import interpret
        except ImportError:
            notes.append("the Design Interpreter is not installed; rules only")
        else:
            more: list[str] = []
            try:
                fields, makers, rejected, why, more = self._interpret(
                    session_id, interpret, entries, sentence, rule_fields, why
                )
            except Exception as err:  # a bug in the interpreter never loses the rules' proposals
                fields, rejected = list(rule_fields), []
                makers = [MadeBy(kind="rule")] * len(rule_fields)
                why = f"the Design Interpreter failed ({type(err).__name__}); rules only"
            used = sum(1 for m in makers if m.kind == "model")
            if why and not used:
                notes.append(f"reason: {why}")
            elif why:
                notes.append(f"the model answered for part of the file only: {why}")
            notes += more
        fields, makers, repeats = _not_decided(
            fields, makers, self.store.proposals(session_id).accepted("design.")
        )
        if repeats:
            notes.append(
                f"{repeats} proposal{'s' * (repeats != 1)} not made again: a person already "
                "decided the same"
            )
        outcomes = [
            self._propose(session_id, f, maker) for f, maker in zip(fields, makers, strict=True)
        ]
        report = _report(outcomes, notes=notes, rejected=rejected, fallback=used == 0)
        report["model_fields"] = used
        report["model_error"] = why
        return report

    def _interpret(
        self,
        session_id: str,
        interpret: Any,
        entries: list[QuarantineEntry],
        sentence: str,
        rule_fields: list[DesignField],
        why: str | None,
    ) -> tuple[list[DesignField], list[MadeBy], list[dict[str, Any]], str | None, list[str]]:
        """Run the Design Interpreter: (fields, makers, rejected, why not the model, notes)."""
        facts = self.facts(session_id)
        quarantine = self.store.quarantine(session_id)
        pseudonymiser = None
        if not self._local():
            pseudonymiser = self.store.pseudonymiser(session_id)
        result = interpret(
            facts.summary,
            entries,
            sentence,
            self.client,
            rule_fields=rule_fields,
            pseudonymiser=pseudonymiser,
        )
        extra = [(e.value, e.origin) for e in getattr(result, "quarantine", [])]
        if extra:
            quarantine.add_many(extra)
        fields, makers = _fields_and_makers(result, rule_fields)
        if len(fields) != len(makers) or not all(isinstance(m, MadeBy) for m in makers):
            raise TypeError("the interpreter's fields and makers do not pair up")
        rejected = [dict(r) for r in getattr(result, "rejected", [])]
        if getattr(result, "fallback", True):  # the rules alone for some or all of the file
            why = why or _model_reason(getattr(result, "error", None))
        used = sum(1 for m in makers if m.kind == "model")
        metas = [dict(m) for m in getattr(result, "meta", [])]
        if metas and self.client.available:  # a real call says more about the model than a ping
            down = not used and why is not None and why.startswith(_CALL_FAILURES)
            why = self._heard(down, why)
        if metas and why:
            metas[-1]["error"] = why  # the cause stays on disk with the calls
        self._log_calls(session_id, "studio.interpret", metas)
        return fields, makers, rejected, why, [str(n) for n in getattr(result, "notes", [])]

    def _propose(self, session_id: str, f: DesignField, maker: MadeBy) -> ProposalOutcome:
        proposal = Proposal(
            study_id=session_id,
            kind=f.kind,
            subject=f.subject,
            payload=f.value,
            evidence=_evidence(f.cites),
            alternatives=f.alternatives,
            level=f.level,
            reasons=f.reasons,
            made_by=maker,
        )
        return self.store.proposals(session_id).propose(proposal, "system")

    def assemble(self, session_id: str, accepted: Sequence[Proposal] | None = None) -> Assembly:
        """The design the session's accepted proposals describe, or what still blocks it.

        Starts from the demo preset when a person accepted it, else from a blank design that
        must gain a comparison; Studio's default amplification rules are the options of the
        ``amp_call`` axis. Only accepted proposals are read: ``accepted`` (in the order a
        person decided them, from one :meth:`ProposalStore.view`), else the inbox's now.

        The further choices a person asked the grid to test (``choice.axis``) come last, after
        the curves and the round-trip exclusions; like the exclusions they are not part of the
        curves hash, so testing them never re-opens a blind stage. They change the design, and
        so the study: switching one off again gives back the study as it was.
        A session opened from an instrument export whose curves call for the Import Trust card
        (``qpilot/io/trust.py``) gets ``import_trust``: the import's verdict and the analysis
        of the option a person last accepted on the card (the curves as imported before any).
        It is set after both hashes are taken, so neither blind confirmation covers it: the
        card is decided once the results are visible, and choosing it never re-opens them.
        """
        from qpilot.qpcr.amp_call import STUDIO_AMP_CALLS
        from qpilot.qpcr.designs import QUANTIFY, DesignError, design_from_proposals, purpose_of
        from qpilot.qpcr.quantify_study import standards_needed

        if accepted is None:
            accepted = self.store.proposals(session_id).accepted()
        blockers: list[str] = []
        design_part = [p for p in accepted if p.kind.startswith("design.")]
        quantify = purpose_of(design_part) == QUANTIFY
        compares = any(p.kind in ("design.preset", "design.comparison") for p in design_part)
        if not quantify and not compares:
            blockers.append("no comparison yet: accept the groups to compare (or the demo preset)")
        base = StudyDesign(
            design_id=BLANK_DESIGN_ID,
            mode="marker_split",
            marker_split=MarkerSplit(marker=""),
            amp_calls=STUDIO_AMP_CALLS,
        )
        try:
            curves = self._curves_table(session_id)
            design = design_from_proposals(base, design_part, curves)
            design = design.model_copy(update={"amp_calls": STUDIO_AMP_CALLS})
            if design.mode == "groups":
                design = _with_lab_defaults(design, self.summary(session_id))
            if quantify:  # quantify samples: standards with quantities instead
                needed = standards_needed(design, self.facts(session_id))
                if needed:
                    blockers.append(needed)
            elif not design.reference_candidates:
                blockers.append("no reference genes yet: accept at least one target as a reference")
            design_hash = design.design_hash()
            curve_part = [p for p in accepted if p.kind.startswith("curve.")]
            full = design_from_proposals(design, curve_part, curves)
            prism_part = [p for p in accepted if p.kind == "prism.exclusion_reason"]
            full = design_from_proposals(full, prism_part, curves)
            choice_part = [p for p in accepted if p.kind.startswith("choice.")]
            full = design_from_proposals(full, choice_part, curves)
        except DesignError as err:
            return Assembly(None, [*blockers, str(err)])
        if blockers:
            return Assembly(None, blockers, design_hash)
        unhashed = {"excluded_wells": (), "axes": None, "reaction_input": None}
        curves_hash = full.model_copy(update=unhashed).design_hash()
        verdict = self.import_verdict(session_id)
        if verdict is not None:
            option = trust_option(accepted) or trust.IN_USE
            analysis = trust.analysis_for(option)
            chosen = ImportTrust(verdict=verdict, analysis=analysis)  # type: ignore[arg-type]
            full = full.model_copy(update={"import_trust": chosen})
        return Assembly(full, [], design_hash, curves_hash)

    def import_verdict(self, session_id: str) -> str | None:
        """The raw-ness verdict of the session's import when it calls for the Import Trust card."""
        try:
            return trust.session_verdict(self._folder(session_id))
        except StudyNotFound:
            return None

    def _curves_table(self, session_id: str) -> Any:
        """Every well of every experiment (for mapping gene/sample exclusions to wells)."""
        return self.facts(session_id).wells

    # ---- stage confirmation -------------------------------------------------------------------

    def stages(self, session_id: str) -> list[StageStatus]:
        """Every stage's status, in the fixed order; a stage opens when the one before closes."""
        view = self.store.proposals(session_id).view()
        return self._stages(session_id, view, self.assemble(session_id, view.accepted))

    def _stages(self, session_id: str, view: InboxView, assembly: Assembly) -> list[StageStatus]:
        """:meth:`stages` from one read of the inbox and the design assembled from it."""
        pending = [p for p in view.proposals if p.status == "proposed"]
        out: list[StageStatus] = []
        previous = True
        for stage in STAGES:
            confirmed = previous and _confirmed(view.accepted, stage, assembly, self, session_id)
            waiting = sum(1 for p in pending if _in_stage(p, stage))
            blockers = list(assembly.blockers) if stage == "design" else []
            if stage == "roundtrip" and not self._meta(session_id).get("exports"):
                blockers.append("nothing has been sent to Prism yet")
            out.append(StageStatus(stage, previous, confirmed, waiting, blockers))
            previous = confirmed
        return out

    def expected_study(self, session_id: str, assembly: Assembly | None = None) -> str | None:
        """The study id the confirmed design implies (whether or not it was analysed yet)."""
        from qpilot.qpcr.designs import study_key

        assembly = assembly or self.assemble(session_id)
        if assembly.design is None:
            return None
        return study_key(self._folder(session_id).name, assembly.design)[:12]

    def confirmed_assembly(self, session_id: str, through: str = "curves") -> Assembly | None:
        """The design a person confirmed, or None while a blind stage up to ``through`` is open.

        The confirmations and the design come from one read of the inbox, and callers analyse
        exactly the assembly returned: a person's decision that lands in between can never put
        an unconfirmed design behind a check that passed.
        """
        return self._confirmed_view(session_id, through)[0]

    def _confirmed_view(
        self, session_id: str, through: str = "curves"
    ) -> tuple[Assembly | None, InboxView]:
        """:meth:`confirmed_assembly` and the one read of the inbox it was assembled from."""
        if through not in BLIND_STAGES:
            raise ValueError(f"through must be one of {', '.join(BLIND_STAGES)}")
        view = self.store.proposals(session_id).view()
        assembly = self.assemble(session_id, view.accepted)
        for stage in BLIND_STAGES[: BLIND_STAGES.index(through) + 1]:
            if not _confirmed(view.accepted, stage, assembly, self, session_id):
                return None, view
        return assembly, view

    def results_visible(self, session_id: str) -> bool:
        """True once the blind stages (design, curves) are both confirmed by a person."""
        return self.confirmed_assembly(session_id) is not None

    def propose_confirm(self, session_id: str, stage: str) -> ProposalOutcome:
        """The system proposes closing a stage; a person accepts it (the confirm click).

        Refused while the stage has pending proposals or (design) the design cannot run. The
        payload names the design hash it confirms and every accepted proposal it covers; for
        the choices stage also the study, its decision chain's head and the option applied on
        each Decision Card, which is what the confirm describes.
        """
        if stage not in ("design", "curves", "choices"):
            raise StudioError(f"no confirm step for stage {stage!r}")
        view = self.store.proposals(session_id).view()
        assembly = self.assemble(session_id, view.accepted)
        status = {s.stage: s for s in self._stages(session_id, view, assembly)}[stage]
        if not status.open:
            raise StudioError(f"the {stage} stage is not open yet")
        if status.pending:
            raise StudioError(f"the {stage} stage still has proposals waiting for a decision")
        if assembly.design is None:
            raise StudioError("the design cannot be confirmed yet: " + "; ".join(assembly.blockers))
        covers = [p.id for p in view.accepted if _in_stage(p, stage)]
        payload: dict[str, Any] = {
            "stage": stage,
            "design_hash": assembly.design_hash if stage == "design" else assembly.curves_hash,
            "covers": covers,
        }
        if stage == "choices":
            study_id = self.study(session_id)
            head, cards, _ = self.store.snapshot(study_id)
            undecided = [  # an on-demand card (a Trace set-aside) is not an analysis choice
                c.id
                for c in cards
                if c.status in ("open", "pending_human") and c.kind not in ON_DEMAND_KINDS
            ]
            if undecided:
                raise StudioError(
                    "decide every analysis choice first (still open: " + ", ".join(undecided) + ")"
                )
            payload["study_id"] = study_id
            payload["chain_head"] = head
            payload["decisions"] = _decisions(cards)
        proposal = Proposal(
            study_id=session_id,
            kind="stage.confirm",
            subject=stage,
            payload=payload,
            level="Moderate",
            reasons=[f"every {stage} proposal is settled; a person confirms the stage"],
            made_by=MadeBy(kind="rule"),
        )
        return self.store.proposals(session_id).propose(proposal, "system")

    # ---- deciding (only a person; the proposal store refuses anyone else) --------------------

    def accept(
        self,
        session_id: str,
        proposal_id: str,
        actor: Actor,
        reason: str = "",
        expected_head: str | None = None,
    ) -> ProposalOutcome:
        """A person accepts one proposal (a reason is needed when the check contradicts it).

        A round-trip exclusion whose consequence no longer holds (:meth:`stale_consequence`) is
        refused: its numbers were computed before other exclusions were accepted. Accepting an
        exclusion makes the others' consequences out of date, so the round trip they came from
        is read again at once (:meth:`refresh_round_trips`).
        """
        inbox = self.store.proposals(session_id)
        if actor == "human":
            refused = self._refuse_stale(session_id, inbox.get(proposal_id), inbox)
            if refused is not None:
                return refused
        outcome = inbox.accept(proposal_id, actor, reason, expected_head)
        self._after_decision(session_id, outcome)
        return outcome

    def edit(
        self,
        session_id: str,
        proposal_id: str,
        actor: Actor,
        edits: dict[str, Any],
        reason: str,
        expected_head: str | None = None,
    ) -> ProposalOutcome:
        """A person edits and accepts; the edited payload is checked again first.

        The stored check describes the proposal as made; the edit gets its own engine check,
        and a contradicted edit needs a reason like a contradicted proposal. A round-trip
        exclusion is refused and refreshed as in :meth:`accept`.
        """
        _require_human(actor, "edit a proposal")
        inbox = self.store.proposals(session_id)
        original = inbox.get(proposal_id)
        refused = self._refuse_stale(session_id, original, inbox)
        if refused is not None:
            return refused
        recheck = self.check(session_id, original.model_copy(update={"edits": edits}))
        if recheck.status == "contradicted" and not reason.strip():
            return ProposalOutcome(
                status="refused",
                head=inbox.head(),
                proposal=original,
                reason="the engine check contradicts this edit; give a reason to accept it anyway",
            )
        outcome = inbox.edit_and_accept(proposal_id, actor, edits, reason, expected_head)
        self._after_decision(session_id, outcome)
        return outcome

    def _refuse_stale(
        self, session_id: str, proposal: Proposal, inbox: Any
    ) -> ProposalOutcome | None:
        """A refusal for a pending exclusion whose consequence no longer holds, else None."""
        if proposal.kind != EXCLUSION_KIND or proposal.status != "proposed":
            return None  # anything else is the proposal store's to answer
        payload = proposal.effective_payload()
        if (
            payload.get("action") == "exclude"
            and payload.get("well_rep")
            and not payload.get("well")
        ):
            return ProposalOutcome(
                status="refused",
                head=inbox.head(),
                proposal=proposal,
                reason="not accepted: this replicate's exact well could not be matched to the "
                "exported table, so excluding it could hit another well; reject it, or export "
                "again and send the tables back from the new project",
            )
        why = self.stale_consequence(session_id, proposal)
        if why is None:
            return None
        return ProposalOutcome(
            status="refused", head=inbox.head(), proposal=proposal, reason=f"not accepted: {why}"
        )

    def _after_decision(self, session_id: str, outcome: ProposalOutcome) -> None:
        """After a person accepted an exclusion, recompute the round-trip questions it outdates."""
        decided = outcome.proposal
        if decided is None or decided.kind != EXCLUSION_KIND:
            return
        if outcome.status not in ("accepted", "edited"):
            return
        try:
            self.refresh_round_trips(session_id)
        except Exception:  # the decision is recorded; out-of-date questions stay refused
            log.warning("round-trip questions not recomputed after an exclusion", exc_info=True)

    def reject(
        self,
        session_id: str,
        proposal_id: str,
        actor: Actor,
        reason: str,
        expected_head: str | None = None,
    ) -> ProposalOutcome:
        """A person rejects one proposal, with a reason."""
        return self.store.proposals(session_id).reject(proposal_id, actor, reason, expected_head)

    def consistent_ids(self, session_id: str, stage: str) -> list[str]:
        """What "Accept all consistent" would cover: pending, ``consistent``, in this stage."""
        return [
            p.id
            for p in self.inbox(session_id, stage, status="proposed")
            if p.check.status == "consistent"
            and p.kind not in ("stage.confirm", EXCLUDE_KIND, TRUST_KIND, PURPOSE_KIND)
        ]

    def accept_all_consistent(
        self,
        session_id: str,
        stage: str,
        actor: Actor,
        ids: Sequence[str],
        reason: str = "",
        expected_head: str | None = None,
    ) -> list[ProposalOutcome]:
        """Accept exactly the listed ids (one chain entry each); never a contradicted one.

        ``ids`` must be the list the person was shown (:meth:`consistent_ids`); anything else
        on it is refused by the proposal store.
        """
        _require_human(actor, "accept proposals")
        inbox = self.store.proposals(session_id)
        return inbox.bulk_accept(list(ids), actor, reason, expected_head)

    def reject_many(
        self, session_id: str, ids: Sequence[str], actor: Actor, reason: str
    ) -> list[ProposalOutcome]:
        """A person rejects each listed proposal with the same reason (one chain entry each)."""
        _require_human(actor, "reject proposals")
        inbox = self.store.proposals(session_id)
        return [inbox.reject(pid, actor, reason) for pid in ids]

    def propose_comparison(self, session_id: str) -> ProposalOutcome | None:
        """Once a person accepted exactly two groups, the rule proposes comparing them.

        The reference group (``group_b``) is a control-like name (control, vehicle, PBS, WT,
        untreated, baseline, sham, mock) when exactly one group has one; otherwise the order is
        alphabetical, with the other direction as the alternative and the level Low.
        """
        accepted = self.store.proposals(session_id).accepted("design.")
        if any(p.kind in ("design.comparison", "design.preset") for p in accepted):
            return None
        latest: dict[str, Any] = {}  # a later decision on a sample wins (None: no group)
        for p in accepted:
            if p.kind == "design.group":
                latest[p.subject] = p.effective_payload().get("group")
        groups = sorted({str(g) for g in latest.values() if g is not None})
        if len(groups) > 2:
            return self._propose_plan(session_id, groups, accepted)
        if len(groups) != 2:
            return None
        controls = [g for g in groups if _CONTROL_GROUP.search(g)]
        if len(controls) == 1:
            reference = controls[0]
            level, why = "Moderate", "the reference group has a control-like name"
        else:
            reference = groups[1]
            level, why = "Low", "no group name says which is the reference; please check"
        other = next(g for g in groups if g != reference)
        cites = [e.ref for p in accepted if p.kind == "design.group" for e in p.evidence if e.ref][
            :20
        ]
        proposal = Proposal(
            study_id=session_id,
            kind="design.comparison",
            subject="comparison",
            payload={"group_a": other, "group_b": reference},
            evidence=_evidence(cites),
            alternatives=[{"group_a": reference, "group_b": other}],
            level=level,
            reasons=[f"exactly two groups were accepted; {why}"],
            made_by=MadeBy(kind="rule"),
        )
        return self.store.proposals(session_id).propose(proposal, "system")

    def _propose_plan(
        self, session_id: str, groups: Sequence[str], accepted: Sequence[Proposal]
    ) -> ProposalOutcome | None:
        """Three or more groups: the rule proposes several comparisons, a person decides.

        With exactly one control-like group name (control, vehicle, untreated, WT, mock, 0 h,
        day 0...) every other group is compared with it ("each group vs <control>", Moderate);
        otherwise every pair of groups (up to five groups; Low, with "each vs the first group"
        as the alternative). Holm's correction across each gene's comparisons is proposed either
        way. When a person accepted pairings (``design.pair``) for the grouped samples, the
        comparisons are paired by them. A person may edit the list, the control, the correction
        or the pairing before accepting.
        """
        controls = [g for g in groups if _CONTROL_GROUP.search(g) or _TIME_ZERO.search(g)]
        cites = [e.ref for p in accepted if p.kind == "design.group" for e in p.evidence if e.ref][
            :20
        ]
        pairing = _accepted_pairing(accepted)
        if len(controls) == 1:
            control = controls[0]
            payload = _vs_control(groups, control)
            alternative = _all_pairs(groups)
            level, why = "Moderate", f"one group has a control-like name ({control})"
        elif len(groups) <= MAX_ALL_PAIRS_GROUPS:
            payload = _all_pairs(groups)
            alternative = _vs_control(groups, groups[0])
            level = "Low"
            why = "no single group name says which is the control, so every pair is compared"
        else:
            return None  # too many groups to guess: a person writes the list
        reasons = [f"{len(groups)} groups were accepted; {why}"]
        reasons.append("Holm's correction across each gene's comparisons is proposed")
        if pairing:
            payload["pair_by"] = alternative["pair_by"] = pairing
            reasons.append(f"accepted pairings ({pairing}): each comparison is a paired test")
        proposal = Proposal(
            study_id=session_id,
            kind="design.comparison",
            subject="comparison",
            payload=payload,
            evidence=_evidence(cites),
            alternatives=[alternative],
            level=level,
            reasons=reasons,
            made_by=MadeBy(kind="rule"),
        )
        return self.store.proposals(session_id).propose(proposal, "system")

    def check(self, session_id: str, proposal: Proposal) -> ProposalCheck:
        """The engine's refute-only check of a proposal (stores nothing)."""
        from qpilot.qpcr.design_checks import check_proposal

        accepted = self.store.proposals(session_id).accepted()
        return check_proposal(
            proposal,
            self.store,
            session_id,
            rdml_path=self.source(session_id),
            accepted=accepted,
            sheet_path=self.sheet(session_id),
        )

    def matters(self, session_id: str, proposal: Proposal) -> bool | None:
        """Blind consequence: does this proposal or its first alternative change a conclusion?

        Only the boolean leaves this module (no gene, direction or number); ``None`` when it
        cannot be computed yet (the rest of the design is not runnable).

        Each reading is assembled exactly as accepting it would assemble the design: from the
        base, with what a person accepted plus this one reading in place of any accepted
        proposal of the same kind and subject (one assembly path, never a reading stacked on an
        already assembled design, which could not undo what that design already wrote).
        """
        if not proposal.alternatives or not proposal.kind.startswith("design."):
            return None
        accepted = self.store.proposals(session_id).accepted()
        if self.assemble(session_id, accepted).design is None:
            return None
        others = [
            p
            for p in accepted
            if p.id != proposal.id and (p.kind, p.subject) != (proposal.kind, proposal.subject)
        ]
        readings = []
        for payload in (proposal.payload, proposal.alternatives[0]):
            reading = proposal.model_copy(
                update={"payload": payload, "edits": None, "status": "accepted"}
            )
            design = self.assemble(session_id, [*others, reading]).design
            if design is None:
                return None
            readings.append(design)
        conclusions = [self._primary_conclusions(session_id, d) for d in readings]
        if None in conclusions:
            return None
        return _differ(conclusions[0], conclusions[1])

    def _primary_conclusions(self, session_id: str, design: StudyDesign) -> dict[str, Any] | None:
        """Each gene's conclusion at the primary choices (internal only: blind stages).

        For a study that quantifies samples, each sample result's reported class and quantity
        (:class:`qpilot.qpcr.quantify_study.Reported`); compare two with :func:`_differ`.
        """
        from qpilot.qpcr.curves import CurveAnalysisError, analyse_study
        from qpilot.qpcr.designs import DesignError, is_quantify
        from qpilot.qpcr.study import StudySettings, build_model

        single = design.model_copy(update={"amp_calls": design.amp_calls[:1], "axes": None})
        settings = StudySettings.from_design(single)
        try:
            curves = analyse_study(
                self.source(session_id),
                settings.experiment_id,
                settings.candidates,
                settings.curves,
            )
            if is_quantify(design):
                from qpilot.qpcr import quantify_study as qs

                inputs = qs.inputs_for(self.source(session_id), curves, single)
                return dict(qs.reported(inputs.at(single.amp_calls[0], qs.LOQ_OPTIONS[0])))
            model = build_model(curves, settings)
        except (DesignError, CurveAnalysisError, ValueError):
            return None
        if model.space.comparisons:  # several comparisons: every one's calls count
            every = model.space.evaluate_all(model.space.primary)
            return {
                f"{cid}/{gene}": r.conclusion
                for cid, found in every.items()
                for gene, r in found.items()
            }
        results = model.space.evaluate(model.space.primary)
        return {gene: r.conclusion for gene, r in results.items()}

    # ---- stage 2: the curves ------------------------------------------------------------------

    def propose_curves(self, session_id: str) -> dict[str, Any]:
        """The Curve Judge's calls, where they disagree with LinRegPCR and that matters.

        Proposes the call rule (LinRegPCR, the engine default) and, per target where resolving
        the disagreements could change a conclusion, one ``curve.well_call`` per disagreeing
        well, each with the curve's evidence. Only "matters" (a boolean) is said; no gene, no
        direction, no number. Needs the design stage confirmed.
        """
        from qpilot.qpcr.amp_call import amplified
        from qpilot.qpcr.curves import analyse_study
        from qpilot.qpcr.designs import design_curves
        from qpilot.qpcr.study import StudySettings

        assembly = self.confirmed_assembly(session_id, through="design")
        if assembly is None:
            raise StudioError("confirm the design first: the curves stage follows it")
        design = assembly.design
        assert design is not None  # a confirmed design always assembles
        settings = StudySettings.from_design(design)
        path = self.source(session_id)
        curves = analyse_study(path, settings.experiment_id, settings.candidates, settings.curves)
        table = design_curves(curves, design)
        study = table[table["sample_type"] == "unkn"]
        keys = study["run_id"].astype(str) + "/" + study["well"].astype(str)
        linreg = amplified(study, "linregpcr", design.well_calls)
        notes: list[str] = []
        outcomes = [self._propose_rule(session_id)]
        disagree: list[str] = []
        learned, judge = self._judge_calls(session_id, path, settings.experiment_id)
        if learned is not None:  # an unscored well has no call, so it never disagrees
            disagree = [
                k
                for k, ours in zip(keys, linreg, strict=True)
                if k in learned and learned[k] != bool(ours) and k not in design.well_calls
            ]
            unscored = sum(1 for k in keys if k not in learned)
            if unscored:
                wells = "study well" if unscored == 1 else "study wells"
                notes.append(
                    f"the Curve Judge cannot score {unscored} {wells} (a curve whose "
                    "minimum over cycles 1-40 is not a positive number); LinRegPCR alone there"
                )
        else:
            notes.append("the Curve Judge is " + judge + "; LinRegPCR alone")
            learned = {}
        by_target: dict[str, list[str]] = {}
        target_of = dict(zip(keys, study["target"], strict=True))
        for key in disagree:
            by_target.setdefault(target_of[key], []).append(key)
        baseline = self._primary_conclusions(session_id, design)
        mattering = 0
        for target, wells in sorted(by_target.items()):
            calls = {**design.well_calls, **{k: learned[k] for k in wells}}
            changed = self._primary_conclusions(
                session_id, design.model_copy(update={"well_calls": calls})
            )
            matters = baseline is not None and changed is not None and _differ(changed, baseline)
            if not matters:
                continue
            mattering += 1
            for key in wells[: max(0, MAX_WELL_PROPOSALS - len(outcomes))]:
                outcomes.append(self._propose_well_call(session_id, key, learned[key], target))
        notes.append(CURVE_JUDGE_LISTED)
        report = _report(outcomes, notes=notes)
        report["disagreements"] = len(disagree)
        report["targets_that_matter"] = mattering
        return report

    def _propose_rule(self, session_id: str) -> ProposalOutcome:
        proposal = Proposal(
            study_id=session_id,
            kind="curve.call_rule",
            subject="amp_call",
            payload={"rule": "linregpcr"},
            evidence=[Evidence(kind="rule", ref="linregpcr", note="the engine's default call")],
            alternatives=[{"rule": "cq_le_40"}, {"rule": "cq_le_38"}, {"rule": "cq_le_35"}],
            level="High",
            reasons=[
                "LinRegPCR calls a well amplified when it finds an exponential phase and a "
                "quantity; the Cq cut-offs are kept as choices whose consequences are shown later"
            ],
            made_by=MadeBy(kind="rule"),
        )
        return self.store.proposals(session_id).propose(proposal, "system")

    def _propose_well_call(
        self, session_id: str, key: str, amplified: bool, target: str
    ) -> ProposalOutcome:
        from qpilot.qpcr import curve_judge

        proposal = Proposal(
            study_id=session_id,
            kind="curve.well_call",
            subject=key,
            payload={"amplified": amplified},
            evidence=[
                Evidence(kind="well", ref=key, note=f"target {target}"),
                Evidence(kind="curve", ref=key, note="the amplification curve"),
            ],
            alternatives=[{"amplified": not amplified}],
            consequence={"matters": True},
            level="Low",
            reasons=["the Curve Judge reads this curve's shape differently from LinRegPCR"],
            made_by=MadeBy(
                kind="model",
                provider="qpilot-curve-judge",
                model=curve_judge.MODEL_SHA256[:12],
            ),
        )
        return self.store.proposals(session_id).propose(proposal, "system")

    def _judge_calls(
        self, session_id: str, path: Path, experiment_id: str | None
    ) -> tuple[dict[str, bool] | None, str]:
        """The Curve Judge's calls and its status, or ``(None, why not)`` when it does not call.

        It calls only a file it is validated for (the instrument and chemistry its transfer
        test passed on). A file it cannot read (a well with two curves, say) leaves LinRegPCR
        and the Cq cut-offs alone instead of failing every target's calls.
        """
        from qpilot.qpcr import curve_judge

        status = _judge_status(self._folder(session_id).name, path)
        if status != "validated":
            return None, status
        try:
            return self._learned_calls(session_id, path, experiment_id), status
        except curve_judge.CurveJudgeError:
            return None, CURVE_JUDGE_UNREADABLE

    def _learned_calls(
        self, session_id: str, path: Path, experiment_id: str | None
    ) -> dict[str, bool]:
        """The Curve Judge's call per ``run_id/well``, cached in the session by model.

        Only the wells it scored are in it: a curve it cannot score has no call (None from
        ``predict_calls``), never "not amplified", so it is never shown or proposed as one. The
        cache key names that rule, so a cache written before it (which held False for those
        wells) is never read.
        """
        from qpilot.qpcr import curve_judge

        cache = self._folder(session_id) / CURVE_JUDGE_FILE
        key = f"{curve_judge.MODEL_SHA256}:{experiment_id}:scored-only"
        if cache.exists():
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("key") == key and isinstance(data.get("calls"), dict):
                return {str(k): v for k, v in data["calls"].items() if isinstance(v, bool)}
        calls = curve_judge.predict_calls(path, experiment_id)
        out = {str(k): bool(v) for k, v in calls.items() if v is not None and v == v}
        atomic_write(cache, dump_json({"key": key, "calls": out}))
        return out

    def curve_calls(self, session_id: str, gene: str) -> dict[str, Any]:
        """Each well of one target called under every rule (and the Curve Judge when validated).

        Facts about the curves, never a conclusion, so they are available in the blind curve
        stage. Uses the assembled design's experiment and well roles when there is one.
        """
        from qpilot.qpcr.amp_call import STUDIO_AMP_CALLS, disagreements, well_calls
        from qpilot.qpcr.curves import analyse_study
        from qpilot.qpcr.designs import design_curves
        from qpilot.qpcr.study import StudySettings

        design = self.assemble(session_id).design
        path = self.source(session_id)
        if design is not None:
            settings = StudySettings.from_design(design)
            curves = analyse_study(path, settings.experiment_id, settings.candidates)
            table = design_curves(curves, design)
            overrides = design.well_calls
        else:
            table = self.facts(session_id).wells
            overrides = {}
        rows = table[table["target"] == gene]
        if rows.empty:
            raise StudioError("no well of this target in the analysed experiment")
        calls = well_calls(rows, STUDIO_AMP_CALLS, overrides)
        experiment = design.experiment_id if design is not None else None
        learned, judge = self._judge_calls(session_id, path, experiment)
        if learned is not None:
            calls = [
                c.model_copy(update={"calls": {**c.calls, "learned": learned[k]}})
                if (k := f"{c.run_id}/{c.well}") in learned
                else c
                for c in calls
            ]
        return {
            "gene": gene,
            "rules": [*STUDIO_AMP_CALLS, *(["learned"] if learned is not None else [])],
            "curve_judge": judge,
            "wells": [c.model_dump(mode="json") for c in calls],
            "disagreements": [f"{c.run_id}/{c.well}" for c in disagreements(calls)],
        }

    def curve(self, session_id: str, well_key: str) -> dict[str, list[float]]:
        """One well's curve by cycle, as the Curve Judge reads it, for the card's plot.

        The values are the well's fluorescence divided by its own minimum (the Curve Judge's
        normalisation, since this instrument has no ROX reference), cycles 1 to 40. The file is
        read once per input and experiment in this process.
        """
        design = self.assemble(session_id).design
        experiment = design.experiment_id if design is not None else None
        features = _curve_features(self.source(session_id), experiment)
        run_id, _, well = well_key.rpartition("/")
        if (run_id, well) not in features.index:
            raise StudioError("no curve for this well in the analysed experiment")
        row = features.loc[(run_id, well)]
        cycles = [c for c in features.columns if str(c).startswith("Cyc")]
        values = [float(row[c]) for c in cycles]
        return {"cycle": list(range(1, len(values) + 1)), "fluorescence": values}

    # ---- stage 3: the analysis and its Decision Cards -----------------------------------------

    def study(self, session_id: str) -> str:
        """The analysed study of the confirmed design (analysed on first use); blind-gated.

        The design analysed is exactly the one the gate checked (:meth:`confirmed_assembly`).
        """
        return self._study(session_id)[0]

    def _study(self, session_id: str) -> tuple[str, list[Proposal]]:
        """:meth:`study` and what a person had accepted in the read its design came from."""
        assembly, view = self._confirmed_view(session_id)
        if assembly is None:
            raise StudioError("confirm the design and the curves first: results stay hidden")
        design = assembly.design
        assert design is not None  # a confirmed design always assembles
        study_id = self.store.ensure_study(self.source(session_id), design=design)
        meta = self._meta(session_id)
        if study_id not in meta.get("studies", {}) or meta.get("current_study") != study_id:
            self._edit_meta(session_id, lambda m: self._switch(m, study_id, design))
        return study_id, list(view.accepted)

    def _switch(self, meta: dict[str, Any], study_id: str, design: StudyDesign) -> None:
        """Make ``study_id`` the session's analysis (in ``meta``, under the session's lock).

        When it replaces another analysis whose design differs only in the wells left out (a
        person left a well out after the curves were confirmed, from Prism, Controls or the
        Curves inbox, or put one back) or in the further choices the grid tests (a person
        switched the efficiency models on or off), what a person decided on the earlier one's
        Decision
        Cards is carried to it first (:meth:`StudyStore.carry_decisions`), so the switch is seen
        only once they are; the report is kept under ``carried``. A design changed in a blind
        stage and confirmed again is another question, so its cards start afresh. The choices
        stage is never carried: its confirmation describes the cards of one analysis, so a person
        confirms the new one. A carry that fails is logged and never keeps the analysis from
        being used.
        """
        studies = dict(meta.get("studies", {}))
        studies.setdefault(study_id, design.design_hash())
        previous = meta.get("current_study")
        if previous and previous != study_id:
            try:
                same = _carries(self.store.design(previous), design)
                report = self.store.carry_decisions(previous, study_id) if same else None
            except (StudyNotFound, OSError, ValueError):
                log.warning(
                    "decisions not carried from %s to %s", previous, study_id, exc_info=True
                )
            else:
                if report is not None:
                    meta["carried"] = {**meta.get("carried", {}), study_id: report.as_dict()}
        meta.update({"studies": studies, "current_study": study_id})

    def carried(self, session_id: str, study_id: str) -> dict[str, Any] | None:
        """The report of the latest carry of a person's decisions into ``study_id`` (or None)."""
        report = self._meta(session_id).get("carried", {}).get(study_id)
        return report if isinstance(report, dict) else None

    def decide(
        self,
        session_id: str,
        card_id: str,
        option: str,
        reason: str,
        actor: Actor,
        expected_head: str | None = None,
    ) -> Any:
        """Decide a Decision Card of the session's study (the core's escalation rule applies)."""
        from qpilot.core.decisions import apply_decision

        return apply_decision(
            self.store, self.study(session_id), card_id, option, reason, actor, expected_head
        )

    def reject_request(
        self,
        session_id: str,
        card_id: str,
        reason: str,
        actor: Actor,
        expected_head: str | None = None,
        option: str | None = None,
    ) -> Any:
        """A person turns down an agent's pending request on a Decision Card, with a reason."""
        from qpilot.core.decisions import reject_request

        _require_human(actor, "turn down an agent's request")
        return reject_request(
            self.store, self.study(session_id), card_id, reason, expected_head, option
        )

    def axis_offer(self, session_id: str, axis: str = "efficiency") -> dict[str, Any]:
        """What testing an opt-in axis would add to the confirmed design (nothing is written).

        ``options``: every option of the axis that applies to this study, primary first;
        ``unavailable``: option id -> why it does not apply here; ``tested``: the options the
        design tests now (the primary alone when it does not); ``evidence``: the per-well
        numbers the proposal cites. Results only: needs the blind stages confirmed.
        """
        from qpilot.qpcr.axes import efficiency as eff_axis
        from qpilot.qpcr.curves import analyse_study
        from qpilot.qpcr.designs import DESIGN_AXES, axis_primary, design_curves
        from qpilot.qpcr.study import StudySettings

        if axis not in DESIGN_AXES:
            raise StudioError(f"there is no further choice called {axis!r} to test")
        assembly = self.confirmed_assembly(session_id)
        if assembly is None:
            raise StudioError(
                "confirm the design and the curves first: which further choices to test "
                "follows them"
            )
        design = assembly.design
        assert design is not None  # a confirmed design always assembles
        tested = tuple((design.axes or {}).get(axis, (axis_primary(axis),)))
        settings = StudySettings.from_design(design)
        curves = analyse_study(
            self.source(session_id), settings.experiment_id, settings.candidates, settings.curves
        )
        if axis != "efficiency":  # the normaliser and the correction between plates
            from qpilot import studio_axes

            return {"axis": axis, "tested": tested, **studio_axes.offer(axis, settings, curves)}
        table = design_curves(curves, design)
        quantities = {s: d.quantity for s, d in design.samples.items() if d.quantity}
        std = eff_axis.standard_curves(table, quantities)
        unavailable = eff_axis.unavailable(table, std)
        study = table[(table["sample_type"] == "unkn") & table["n0"].notna()]
        own = study["eff_indiv"].astype(float)
        low, high = eff_axis.E_VALID
        valid = own[own.notna() & (own > low) & (own < high)]
        if valid.empty:
            unavailable["per_well"] = "no study well has its own efficiency inside (1.0, 2.3)"
        options = tuple(o for o in eff_axis.OPTIONS if o not in unavailable)
        assay = study["eff_target"].astype(float).dropna()
        evidence = {
            "study_wells": len(study),
            "own_in_range": len(valid),
            "own_outside_range": len(study) - len(valid),
            "own_min": float(valid.min()) if len(valid) else None,
            "own_median": float(valid.median()) if len(valid) else None,
            "own_max": float(valid.max()) if len(valid) else None,
            "assay_min": float(assay.min()) if len(assay) else None,
            "assay_max": float(assay.max()) if len(assay) else None,
            "dilution_series": len(std),
        }
        return {
            "axis": axis,
            "options": options,
            "unavailable": unavailable,
            "tested": tested,
            "evidence": evidence,
        }

    def propose_axis(
        self, session_id: str, axis: str = "efficiency", on: bool = True
    ) -> ProposalOutcome:
        """The rule proposes testing a further choice (or no longer testing it); a person decides.

        On: every option of the axis that applies to the confirmed design, primary first (for
        the efficiency models: LinRegPCR's mean efficiency, each well's own, one per amplicon,
        an assumed 2.0, the dilution series'; for the normaliser: the reference genes chosen,
        NormFinder's and geNorm's best pairs, the global mean; for the correction between
        plates: none, the inter-run calibrator, the factor correction); off: the primary alone.
        Nothing changes until a person accepts it; then the design names the axis and the
        study is analysed again with it as one more dimension of the grid, whose Decision Card
        says what each option would change. The analysis in use stays the primary until a
        person decides that card.
        """
        from qpilot.qpcr.axes import get_axis

        offer = self.axis_offer(session_id, axis)
        primary, options = offer["options"][0], offer["options"]
        wanted = options if on else (primary,)
        if on and len(options) < 2:
            why = "; ".join(f"{k}: {v}" for k, v in sorted(offer["unavailable"].items()))
            raise StudioError(f"no other option of this choice applies to this study ({why})")
        if tuple(wanted) == tuple(offer["tested"]):
            state = "already tested" if on else "not tested"
            raise StudioError(f"this choice is {state} in the current analysis")
        catalogue = {o.id: o for o in get_axis(axis).catalogue}
        numbers = offer["evidence"]
        if axis != "efficiency":  # the normaliser and the correction between plates
            from qpilot import studio_axes

            labels = {o: c.label for o, c in catalogue.items()}
            proposal = Proposal(
                study_id=session_id,
                kind="choice.axis",
                subject=axis,
                payload={"options": list(wanted)},
                evidence=studio_axes.evidence(axis, numbers),
                alternatives=[{"options": [primary]} if on else {"options": list(options)}],
                level="Moderate",
                reasons=studio_axes.reasons(axis, on, offer["unavailable"], labels),
                made_by=MadeBy(kind="rule"),
            )
            return self.store.proposals(session_id).propose(proposal, "system")
        evidence = [
            Evidence(
                kind="rule",
                ref=axis,
                note="method card methods/efficiency_model.md: which efficiency turns Cq into "
                "quantity",
            )
        ]
        if numbers["own_median"] is not None:
            evidence.append(
                Evidence(
                    kind="pattern",
                    ref="each well's own efficiency",
                    note=f"{numbers['own_in_range']} study wells: median "
                    f"{numbers['own_median']:.3f}, {numbers['own_min']:.3f} to "
                    f"{numbers['own_max']:.3f}; {numbers['own_outside_range']} outside "
                    "LinRegPCR's valid range (1.0, 2.3)",
                )
            )
        if numbers["assay_min"] is not None:
            evidence.append(
                Evidence(
                    kind="pattern",
                    ref="each assay's mean efficiency",
                    note=f"LinRegPCR's mean efficiency per assay and plate: "
                    f"{numbers['assay_min']:.3f} to {numbers['assay_max']:.3f}",
                )
            )
        if on:
            reasons = [
                "qPilot turns each Cq into a quantity with LinRegPCR's mean efficiency of each "
                "assay on each plate; testing the other efficiency models shows which "
                "conclusions depend on that choice. The analysis in use stays the same until "
                "a person decides otherwise on the card it raises; what a person decided on the "
                "other cards is carried to it, unless that choice matters more there.",
                *(
                    f"not offered: {catalogue[o].label.lower()} ({why})"
                    for o, why in sorted(offer["unavailable"].items())
                ),
            ]
            alternatives = [{"options": [primary]}]
        else:
            reasons = [
                "stop testing the efficiency models: the analysis goes back to the grid "
                "without that choice; what a person decided on the other cards is carried back"
            ]
            alternatives = [{"options": list(options)}]
        proposal = Proposal(
            study_id=session_id,
            kind="choice.axis",
            subject=axis,
            payload={"options": list(wanted)},
            evidence=evidence,
            alternatives=alternatives,
            level="Moderate",
            reasons=reasons,
            made_by=MadeBy(kind="rule"),
        )
        return self.store.proposals(session_id).propose(proposal, "system")

    # ---- Run Gate: what a person (or an agent) chooses on a control check ----------------------

    def decide_gate(
        self,
        session_id: str,
        choice: GateChoice,
        actor: Actor,
        reason: str,
        expected_head: str | None = None,
    ) -> GateDecision:
        """A person chooses an option of a Run Gate card: the wells become curve exclusions.

        The card's options are states of the wells it points at. Leaving wells out makes one
        ``curve.exclude_well`` per well (proposed by Run Gate's rule, accepted by the person
        with the reason) and puts back the card's other wells a person left out; keeping every
        well puts back the wells a person left out, or, when nothing has to change, records the
        keep (the rule's exclusions, rejected with the reason). An agent's request waiting on
        these wells is answered by the same click: accepted when it asks for what the person
        chose, rejected otherwise. Everything is one write to the inbox (all or nothing), and
        a changed design means the study is analysed again (:meth:`study`).

        Only a person; refused while the results are hidden, and ``stale`` when the session's
        analysis is no longer the one the gate measured (``choice.study_id``) or a person
        decided anything in the inbox since ``expected_head``.
        """
        from qpilot.core.proposals import clean_reason

        _require_human(actor, "decide what a control check means for the analysis")
        reason = clean_reason(reason, required=True)
        assembly, view = self._gate_view(session_id, choice)
        if isinstance(assembly, GateDecision):
            return assembly
        plan = _gate_plan(assembly, view, choice)
        new = [(self._gate_proposal(session_id, choice, w, x, None), "accept") for w, x in plan.new]
        settle = list(plan.settle)
        if not new and not settle:
            if choice.option != GATE_KEEP:
                raise StudioError("these wells are already left out of the analysis")
            excluded = set(assembly.design.excluded_wells)  # type: ignore[union-attr]
            keep = [w for w in choice.universe if w not in excluded]
            if not keep:
                raise StudioError("nothing to decide: none of these wells is in the analysis")
            new = [(self._gate_proposal(session_id, choice, w, True, None), "reject") for w in keep]
        # the plan was made from ``view``: nothing a person decides after it may slip under it
        since = expected_head if expected_head is not None else view.head
        outcomes = self.store.proposals(session_id).decide_together(
            new, settle, actor, reason, proposer="system", expected_head=since
        )
        first = outcomes[0]
        if first.status in ("stale", "refused"):
            return GateDecision(status=first.status, head=first.head, reason=first.reason)
        decided = [o.proposal for o in outcomes if o.proposal is not None]
        out = [p.subject for p in decided if p.status != "rejected" and leaves_out(p)]
        back = [p.subject for p in decided if p.status != "rejected" and not leaves_out(p)]
        status = "left_out" if out else "put_back" if back else "kept"
        return GateDecision(
            status=status,
            head=outcomes[-1].head,
            left_out=sorted(set(out)),
            put_back=sorted(set(back)),
            not_put_back=list(plan.elsewhere),
            proposals=decided,
        )

    def request_gate(
        self, session_id: str, choice: GateChoice, reason: str, agent: str | None = None
    ) -> GateDecision:
        """An agent asks for an option of a Run Gate card: proposals that wait for a person.

        One agent-made ``curve.exclude_well`` per well whose state the option would change;
        nothing is applied (only a person accepts, :meth:`decide_gate` or the Curves inbox), so
        the answer is ``pending_human`` whatever the card is. When nothing would change, nothing
        is filed and the answer says so.
        """
        from qpilot.core.proposals import clean_reason

        reason = clean_reason(reason, required=True)
        assembly, view = self._gate_view(session_id, choice)
        if isinstance(assembly, GateDecision):
            return assembly
        plan = _gate_plan(assembly, view, choice)
        inbox = self.store.proposals(session_id)
        filed: list[Proposal] = []
        head = view.head
        for well, excluded in plan.changes:
            proposal = self._gate_proposal(session_id, choice, well, excluded, (reason, agent))
            outcome = inbox.propose(proposal, "agent")
            if outcome.status == "refused":
                return GateDecision(status="refused", head=outcome.head, reason=outcome.reason)
            head = outcome.head
            if outcome.proposal is not None:
                filed.append(outcome.proposal)
        return GateDecision(
            status="pending_human",
            head=head,
            proposals=filed,
            reason=(
                "Only a person decides what a control check means for the analysis: the "
                "request waits in qPilot (Controls, or the Curves inbox)."
                if filed
                else "Nothing to ask: the wells are already as this option leaves them."
            ),
        )

    def _gate_view(
        self, session_id: str, choice: GateChoice
    ) -> tuple[Assembly | GateDecision, InboxView]:
        """The confirmed design and inbox the gate's choice applies to, or why not (stale)."""
        assembly, view = self._confirmed_view(session_id)
        if assembly is None or assembly.design is None:
            raise StudioError("confirm the design and the curves first: results stay hidden")
        if self.expected_study(session_id, assembly) != choice.study_id:
            return GateDecision(status="stale", head=view.head, reason=GATE_STALE), view
        return assembly, view

    def _gate_proposal(
        self,
        session_id: str,
        choice: GateChoice,
        well: str,
        excluded: bool,
        agent: tuple[str, str | None] | None,
    ) -> Proposal:
        """One well of a Run Gate choice as a ``curve.exclude_well`` proposal.

        Run Gate's rule makes it (``made_by`` rule ``qpilot-run-gate``, the pack as the model),
        or an agent when ``agent`` gives its reason (and name). The consequence says only
        whether the option changes a call at the analysis in use and which card and option it
        came from: never a gene, a direction or a number, so the proposal stays blind-safe
        should the design change and the session be blind again.
        """
        if agent is None:
            made_by = MadeBy(kind="rule", provider=GATE_MAKER, model=choice.pack)
            reasons = [f"{choice.rule_id} {choice.verdict_words} ({choice.where}): {choice.label}"]
        else:
            made_by = MadeBy(kind="agent", agent=agent[1])
            reasons = [agent[0]]
        words = "leave it out" if excluded else "put it back"
        return Proposal(
            study_id=session_id,
            kind=EXCLUDE_KIND,
            subject=well,
            payload={"excluded": excluded},
            evidence=[
                Evidence(kind="rule", ref=choice.rule_id, note=f"Run Gate, {choice.where}"),
                Evidence(kind="well", ref=well, note=f"a well the check points at: {words}"),
            ],
            alternatives=[{"excluded": not excluded}],
            consequence={
                "matters": choice.matters,
                "gate": {
                    "card_id": choice.card_id,
                    "option": choice.option,
                    "study_id": choice.study_id,
                },
            },
            level="Moderate",
            reasons=reasons,
            made_by=made_by,
        )

    def gate_record(self, session_id: str) -> dict[str, list[Proposal]]:
        """Every ``curve.exclude_well`` proposal tied to a Run Gate card, by card, oldest first."""
        out: dict[str, list[Proposal]] = {}
        for proposal in self.store.proposals(session_id).proposals(kind_prefix=EXCLUDE_KIND):
            card = gate_card_of(proposal)
            if card is not None:
                out.setdefault(card, []).append(proposal)
        return out

    # ---- Trace: a person sets wells aside from Where to look ---------------------------------

    def decide_trace(
        self,
        session_id: str,
        choice: TraceChoice,
        actor: Actor,
        reason: str,
        expected_head: str | None = None,
    ) -> GateDecision:
        """A person chooses an option at a place Trace pointed at: the wells become exclusions.

        Run Gate's path (:meth:`decide_gate`), with Trace as the proposer: a set-aside makes one
        ``curve.exclude_well`` per well it leaves out (made by Trace, accepted by the person with
        the reason) and puts back the place's other wells a person left out; "keep" puts back
        the wells a person left out at this place, or, when nothing has to change, records the
        keep (the place's own wells, Trace's exclusions rejected with the reason). One write to
        the inbox (all or nothing); a changed design is analysed again (:meth:`study`), and the
        person's Decision Card choices are carried to it (:meth:`_switch`).

        Only a person; refused while the results are hidden, and ``stale`` when the session's
        analysis is no longer the one traced (``choice.study_id``) or a person decided anything
        in the inbox since ``expected_head``.
        """
        from qpilot.core.proposals import clean_reason

        _require_human(actor, "decide what Trace's place to look means for the analysis")
        reason = clean_reason(reason, required=True)
        assembly, view = self._gate_view(session_id, choice)  # type: ignore[arg-type]
        if isinstance(assembly, GateDecision):
            return assembly
        # What the option can put back: only the wells a person left out from this place (a
        # well of the sample left out in Curves or from Controls stays as it is).
        mine = {
            w
            for w, p in _latest_exclusions(view).items()
            if trace_card_of(p) == choice.card_id and leaves_out(p)
        }
        # an agent's request waiting at this place is answered by any click here (approved when
        # it asks for what the person chose, turned down otherwise), whichever wells it names
        asked = {
            p.subject
            for p in view.proposals
            if p.kind == EXCLUDE_KIND
            and p.status == "proposed"
            and p.made_by.kind == "agent"
            and trace_card_of(p) == choice.card_id
        }
        choice = replace(choice, universe=tuple(sorted(set(choice.wells) | mine | asked)))
        # Run Gate's plan: a waiting request from no card (or from Trace) on these wells is
        # settled by the same click; one tied to a Run Gate card is left for that card.
        plan = _gate_plan(assembly, view, choice)  # type: ignore[arg-type]
        new = [(self._trace_proposal(session_id, choice, w, x), "accept") for w, x in plan.new]
        settle = list(plan.settle)
        if not new and not settle:
            if choice.option != GATE_KEEP:
                raise StudioError("these wells are already left out of the analysis")
            excluded = set(assembly.design.excluded_wells)  # type: ignore[union-attr]
            keep = [w for w in choice.place_wells if w not in excluded]
            if not keep:
                raise StudioError("nothing to decide: none of these wells is in the analysis")
            new = [(self._trace_proposal(session_id, choice, w, True), "reject") for w in keep]
        since = expected_head if expected_head is not None else view.head
        outcomes = self.store.proposals(session_id).decide_together(
            new, settle, actor, reason, proposer="system", expected_head=since
        )
        first = outcomes[0]
        if first.status in ("stale", "refused"):
            return GateDecision(status=first.status, head=first.head, reason=first.reason)
        decided = [o.proposal for o in outcomes if o.proposal is not None]
        out = [p.subject for p in decided if p.status != "rejected" and leaves_out(p)]
        back = [p.subject for p in decided if p.status != "rejected" and not leaves_out(p)]
        status = "left_out" if out else "put_back" if back else "kept"
        return GateDecision(
            status=status,
            head=outcomes[-1].head,
            left_out=sorted(set(out)),
            put_back=sorted(set(back)),
            not_put_back=list(plan.elsewhere),
            proposals=decided,
        )

    def request_trace(
        self, session_id: str, choice: TraceChoice, reason: str, agent: str | None = None
    ) -> GateDecision:
        """An agent asks to set wells aside at a place Trace pointed at: proposals that wait.

        Run Gate's :meth:`request_gate` for a Trace place: one agent-made ``curve.exclude_well``
        per well whose state the option would change (the place's wells, and the wells a person
        set aside from this same place that the option would put back), with the agent's
        ``reason``. Nothing is applied (only a person accepts, :meth:`decide_trace` or the
        Curves inbox), so the answer is ``pending_human`` whatever the place is; a person's
        Decide… at the place answers a waiting request by the same click (accepted when it
        asks for what the person chose, turned down otherwise). When nothing would change,
        nothing is filed and the answer says so.
        """
        from qpilot.core.proposals import clean_reason

        reason = clean_reason(reason, required=True)
        assembly, view = self._gate_view(session_id, choice)  # type: ignore[arg-type]
        if isinstance(assembly, GateDecision):
            return replace(assembly, reason=TRACE_STALE)
        mine = {
            w
            for w, p in _latest_exclusions(view).items()
            if trace_card_of(p) == choice.card_id and leaves_out(p)
        }
        choice = replace(choice, universe=tuple(sorted(set(choice.wells) | mine)))
        plan = _gate_plan(assembly, view, choice)  # type: ignore[arg-type]
        inbox = self.store.proposals(session_id)
        filed: list[Proposal] = []
        head = view.head
        for well, excluded in plan.changes:
            proposal = self._trace_proposal(session_id, choice, well, excluded, (reason, agent))
            outcome = inbox.propose(proposal, "agent")
            if outcome.status == "refused":
                return GateDecision(status="refused", head=outcome.head, reason=outcome.reason)
            head = outcome.head
            if outcome.proposal is not None:
                filed.append(outcome.proposal)
        return GateDecision(
            status="pending_human",
            head=head,
            proposals=filed,
            reason=(
                "Only a person decides whether to set wells aside: the request waits in qPilot "
                "(Trace, at this place, or the Curves inbox)."
                if filed
                else "Nothing to ask: the wells are already as this option leaves them."
            ),
        )

    def trace_requests(self, session_id: str) -> dict[str, list[Proposal]]:
        """Agents' requests waiting at Trace places, by the place's card id, oldest first."""
        out: dict[str, list[Proposal]] = {}
        for card, proposals in self.trace_record(session_id).items():
            waiting = [p for p in proposals if p.status == "proposed" and p.made_by.kind == "agent"]
            if waiting:
                out[card] = waiting
        return out

    def _trace_proposal(
        self,
        session_id: str,
        choice: TraceChoice,
        well: str,
        excluded: bool,
        agent: tuple[str, str | None] | None = None,
    ) -> Proposal:
        """One well of a Trace choice as a ``curve.exclude_well`` proposal.

        Made by Trace's rule, or by an agent when ``agent`` gives its reason (and name).
        Blind-safe like Run Gate's: the consequence says only whether the option changes a
        call at the analysis in use and which place and option it came from (the sample and
        its well, never a gene, a direction or a number).
        """
        words = "leave it out" if excluded else "put it back"
        checks = f" ({', '.join(choice.checks)})" if choice.checks else ""
        if agent is None:
            made_by = MadeBy(kind="rule", provider=TRACE_MAKER, model=TRACE_MODEL)
            reasons = [f"Trace{checks}, {choice.where}: {choice.label}"]
        else:
            made_by = MadeBy(kind="agent", agent=agent[1])
            reasons = [agent[0]]
        return Proposal(
            study_id=session_id,
            kind=EXCLUDE_KIND,
            subject=well,
            payload={"excluded": excluded},
            evidence=[
                Evidence(kind="rule", ref=TRACE_MAKER, note=f"Trace: {choice.where}"),
                Evidence(kind="well", ref=well, note=f"a well of the place in Trace: {words}"),
            ],
            alternatives=[{"excluded": not excluded}],
            consequence={
                "matters": choice.matters,
                "trace": {
                    "card_id": choice.card_id,
                    "option": choice.option,
                    "study_id": choice.study_id,
                    "sample": choice.sample,
                    "well": choice.well,
                },
            },
            level="Moderate",
            reasons=reasons,
            made_by=made_by,
        )

    def trace_record(self, session_id: str) -> dict[str, list[Proposal]]:
        """Every ``curve.exclude_well`` proposal tied to a place Trace pointed at, by card."""
        out: dict[str, list[Proposal]] = {}
        for proposal in self.store.proposals(session_id).proposals(kind_prefix=EXCLUDE_KIND):
            card = trace_card_of(proposal)
            if card is not None:
                out.setdefault(card, []).append(proposal)
        return out

    def trace_left_out(self, session_id: str) -> dict[str, TraceSetAside]:
        """The wells a person set aside from Trace that are out of the analysis now, by card.

        A well counts for the card whose acceptance is the person's latest decision on it (a
        well put back in Curves, or left out again from another place, belongs there now) and
        only while the confirmed design leaves it out.
        """
        assembly, view = self._confirmed_view(session_id)
        if assembly is None or assembly.design is None:
            return {}
        excluded = set(assembly.design.excluded_wells)
        out: dict[str, TraceSetAside] = {}
        for well, p in _latest_exclusions(view).items():
            card = trace_card_of(p)
            if card is None or not leaves_out(p) or well not in excluded:
                continue
            info = (p.consequence or {}).get("trace") or {}
            found = out.get(card)
            if found is None:
                found = out[card] = TraceSetAside(
                    card_id=card,
                    option=str(info.get("option") or ""),
                    sample=str(info.get("sample") or ""),
                    well=info.get("well") if isinstance(info.get("well"), str) else None,
                    reason=p.reason or "",
                    decided_at=p.decided_at or "",
                    matters=bool((p.consequence or {}).get("matters")),
                    wells=[],
                )
            found.wells.append(well)
            if (p.decided_at or "") >= found.decided_at:
                found.reason, found.decided_at = p.reason or "", p.decided_at or ""
                found.option = str(info.get("option") or found.option)
        for entry in out.values():
            entry.wells.sort()
        return out

    # ---- the Import Trust card: what curves processed before export mean --------------------

    def decide_import_trust(
        self,
        session_id: str,
        option: str,
        actor: Actor,
        reason: str,
        expected_head: str | None = None,
        study_id: str | None = None,
    ) -> TrustDecision:
        """A person chooses an option of the Import Trust card, with a reason.

        The choice is one ``curve.import_trust`` proposal (made by the card's rule, accepted by
        the person with the reason) or the agent's request asking for it (approved); every other
        waiting request on the card is turned down by the same click, all in one write to the
        inbox. ``cq_only`` changes the analysis (the study is analysed again); the other options
        keep it. Only a person; refused while the results are hidden, when the import calls for
        no card, for an option already chosen, and for Cq only without instrument Cq values;
        ``stale`` when the analysis is not ``study_id`` any more or a person decided anything
        in the inbox since ``expected_head``.
        """
        from qpilot.core.proposals import clean_reason

        _require_human(actor, "decide how far imported curves can be trusted")
        reason = clean_reason(reason, required=True)
        assembly, view = self._trust_view(session_id, option, study_id)
        if isinstance(assembly, TrustDecision):
            return assembly
        assert assembly.design is not None and assembly.design.import_trust is not None
        if trust_option(view.accepted) == option:
            raise StudioError("this is already the decision on the Import Trust card")
        waiting = trust_requests(view)
        match = next((p for p in waiting if trust_choice(p) == option), None)
        settle = [(p.id, "accept" if p is match else "reject") for p in waiting]
        new = (
            []
            if match is not None
            else [(self._trust_proposal(session_id, option, None), "accept")]
        )
        since = expected_head if expected_head is not None else view.head
        outcomes = self.store.proposals(session_id).decide_together(
            new, settle, actor, reason, proposer="system", expected_head=since
        )
        first = outcomes[0]
        if first.status in ("stale", "refused"):
            return TrustDecision(status=first.status, head=first.head, reason=first.reason)
        before = assembly.design.import_trust.analysis
        return TrustDecision(
            status="decided",
            head=outcomes[-1].head,
            option=option,
            changed=trust.analysis_for(option) != before,
            proposals=[o.proposal for o in outcomes if o.proposal is not None],
        )

    def request_import_trust(
        self,
        session_id: str,
        option: str,
        reason: str,
        agent: str | None = None,
        study_id: str | None = None,
    ) -> TrustDecision:
        """An agent asks for an option of the Import Trust card: a proposal that waits.

        Nothing is applied (only a person accepts, :meth:`decide_import_trust` or the Curves
        inbox), so the answer is ``pending_human``; asking for what is already decided files
        nothing and says so.
        """
        from qpilot.core.proposals import clean_reason

        reason = clean_reason(reason, required=True)
        assembly, view = self._trust_view(session_id, option, study_id)
        if isinstance(assembly, TrustDecision):
            return assembly
        if trust_option(view.accepted) == option:
            return TrustDecision(
                status="pending_human",
                head=view.head,
                option=option,
                reason="Nothing to ask: a person already chose this option on the card.",
            )
        proposal = self._trust_proposal(session_id, option, (reason, agent))
        outcome = self.store.proposals(session_id).propose(proposal, "agent")
        if outcome.status == "refused":
            return TrustDecision(status="refused", head=outcome.head, reason=outcome.reason)
        return TrustDecision(
            status="pending_human",
            head=outcome.head,
            option=option,
            proposals=[outcome.proposal] if outcome.proposal is not None else [],
            reason=(
                "Only a person decides how far imported curves can be trusted: the request "
                "waits in qPilot (Results, or the Curves inbox)."
            ),
        )

    def instrument_cq_count(self, session_id: str, experiment_id: str | None) -> int:
        """How many wells of the session's file have a Cq from the instrument (RDML ``<cq>``)."""
        from qpilot.io.rdml_io import load
        from qpilot.qpcr.curves import instrument_cq

        return len(instrument_cq(load(self.source(session_id)), experiment_id))

    def _trust_view(
        self, session_id: str, option: str, study_id: str | None
    ) -> tuple[Assembly | TrustDecision, InboxView]:
        """The confirmed design an Import Trust choice applies to, or why not."""
        trust.analysis_for(option)  # ValueError: not an option of the card
        assembly, view = self._confirmed_view(session_id)
        if assembly is None or assembly.design is None:
            raise StudioError("confirm the design and the curves first: results stay hidden")
        if assembly.design.import_trust is None:
            raise StudioError(
                "this study's curves call for no Import Trust card: they are raw, normalised to "
                "a passive reference, or were not opened from an instrument export"
            )
        if study_id is not None and self.expected_study(session_id, assembly) != study_id:
            return TrustDecision(status="stale", head=view.head, reason=TRUST_STALE), view
        experiment = assembly.design.experiment_id
        if option == "cq_only" and self.instrument_cq_count(session_id, experiment) < 1:
            raise StudioError(
                "the export has no Cq values from the instrument, so it cannot be analysed "
                "without its curves"
            )
        return assembly, view

    def _trust_proposal(
        self, session_id: str, option: str, agent: tuple[str, str | None] | None
    ) -> Proposal:
        """An option of the Import Trust card as a ``curve.import_trust`` proposal.

        The card's rule makes it (``made_by`` rule ``qpilot-import-trust``), or an agent when
        ``agent`` gives its reason (and name). Its consequence names only the analysis the
        option leads to and its cap level: never a gene, a direction or a number.
        """
        verdict = self.import_verdict(session_id)
        if agent is None:
            made_by = MadeBy(kind="rule", provider=trust.MAKER)
            reasons = [f"the import's raw-ness verdict is {verdict}: {trust.LABELS[option]}"]
        else:
            made_by = MadeBy(kind="agent", agent=agent[1])
            reasons = [agent[0]]
        cap = trust.caps(verdict or "unknown")[option]
        return Proposal(
            study_id=session_id,
            kind=TRUST_KIND,
            subject=trust.SUBJECT,
            payload={"option": option},
            evidence=[
                Evidence(kind="rule", ref=trust.RULE_ID, note=f"raw-ness verdict {verdict}"),
                Evidence(kind="file", ref="capture.json", note="what the export was read as"),
            ],
            alternatives=[{"option": o} for o in trust.OPTIONS if o != option],
            consequence={
                "import_trust": {
                    "option": option,
                    "analysis": trust.analysis_for(option),
                    "cap": cap.level,
                }
            },
            level="Moderate",
            reasons=reasons,
            made_by=made_by,
        )

    # ---- stage 4: the Prism project -----------------------------------------------------------

    def propose_prism(
        self, session_id: str, genes: Sequence[str] | None = None, template_id: str = ""
    ) -> ProposalOutcome:
        """The AI drafts the Prism project (tables, test, graph, caption in fact tokens)."""
        from qpilot.prism import DEFAULT_TEMPLATE

        status = {s.stage: s for s in self.stages(session_id)}
        if not status["choices"].confirmed:
            raise StudioError("confirm the analysis choices first: the Prism draft follows them")
        study_id = self.study(session_id)
        result = self.store.get(study_id)
        cards = self.store.cards(study_id)
        template = template_id or DEFAULT_TEMPLATE
        chosen = list(genes) if genes else [g for g in result.contrasts if g in _headline(result)]
        maker = MadeBy(kind="rule")
        try:
            from qpilot.ai.prism_draft import draft_prism_project
        except ImportError:
            payload = {"template_id": template, "genes": chosen}
            reasons = ["template draft (the AI draft is not installed)"]
        else:
            draft = draft_prism_project(result, cards, chosen or None, template, client=self.client)
            payload = _as_payload(draft)
            reasons = list(getattr(draft, "reasons", [])) or ["the Prism draft"]
            if getattr(draft, "made_by_model", False):
                maker = MadeBy(kind="model", provider=self.client.provider, model=self.client.model)
            self._log_calls(session_id, "studio.prism_draft", getattr(draft, "meta", []))
        payload["study_id"] = study_id
        digest = self._prism_digest(study_id, payload.get("genes") or None)
        if digest:  # a later analysis with the same tables keeps this draft (still current)
            payload["tables_sha256"] = digest
        proposal = Proposal(
            study_id=session_id,
            kind="prism.project",
            subject="prism",
            payload=payload,
            evidence=[Evidence(kind="fact", ref=f) for f in _caption_facts(payload)],
            level="Moderate",
            reasons=reasons,
            made_by=maker,
        )
        return self.store.proposals(session_id).propose(proposal, "system")

    def preview_prism(self, session_id: str, rows: int = 5) -> dict[str, Any]:
        """What Send to Prism would write (nothing is written); blind-gated like every result.

        ``rows`` is how many rows of each table to show (the graph wants them all).
        """
        from qpilot.prism import preview

        study_id = self.study(session_id)
        found, _, _ = self.prism_project_cached(session_id, study_id)
        project = found.effective_payload() if found is not None else None
        genes = project.get("genes") if project else None
        template = (project or {}).get("template_id") or "two_groups_log2"
        out = preview(self.store, study_id, genes or None, template, rows=rows)
        digest = (out.get("bundle") or {}).get("info", {}).get("tables_sha256")
        head = (out.get("bundle") or {}).get("chain_head")
        if digest and head:  # the preview computed it anyway: the status needs not
            with _DIGESTS_LOCK:
                _DIGESTS[(str(self.store.root), study_id, head, tuple(genes or ()))] = digest
        return out

    def _accepted_project(self, session_id: str, study_id: str) -> dict[str, Any] | None:
        found, _ = self.prism_project(session_id, study_id)
        return found.effective_payload() if found is not None else None

    def prism_project_cached(
        self, session_id: str, study_id: str
    ) -> tuple[Proposal | None, bool, bool]:
        """:meth:`prism_project` without computing a digest: ``(found, carried, pending)``.

        ``pending`` is True when an earlier analysis's project might still be current but a
        digest it needs is not computed yet (call :meth:`prism_project` in the background).
        """
        return self._prism_project(session_id, study_id, compute=False)

    def prism_project(self, session_id: str, study_id: str) -> tuple[Proposal | None, bool]:
        """The accepted Prism project that holds for ``study_id``, and whether it is carried.

        A project accepted for this analysis holds. So does the latest one accepted for an
        earlier analysis whose exported tables hold exactly the same numbers (the digest of
        the tables, ``tables_sha256``, is equal): a decision that changed no number in the
        tables does not make a person draft the project again. It is then "still current"
        (the second value is True). A draft from before digests were kept is compared by the
        tables its own analysis exports now.
        """
        found, carried, _ = self._prism_project(session_id, study_id, compute=True)
        return found, carried

    def _prism_project(
        self, session_id: str, study_id: str, *, compute: bool
    ) -> tuple[Proposal | None, bool, bool]:
        accepted = self.store.proposals(session_id).accepted("prism.project")
        for proposal in reversed(accepted):
            if proposal.effective_payload().get("study_id") == study_id:
                return proposal, False, False
        if not accepted:
            return None, False, False
        latest = accepted[-1]
        payload = latest.effective_payload()
        genes = payload.get("genes") or None
        digest = payload.get("tables_sha256") or self._prism_digest(
            str(payload.get("study_id") or ""), genes, compute=compute
        )
        current = self._prism_digest(study_id, genes, compute=compute) if digest else None
        if digest is _MISSING or current is _MISSING:
            return None, False, True
        if digest and current == digest:
            return latest, True, False
        return None, False, False

    def _prism_digest(
        self, study_id: str, genes: Sequence[str] | None, *, compute: bool = True
    ) -> Any:
        """The digest of the tables a Prism project of ``study_id`` holds (cached per head).

        ``None`` when it cannot be computed; with ``compute=False``, :data:`_MISSING` when it is
        not in the cache yet.
        """
        from qpilot.prism import project_digest
        from qpilot.qpcr.export import ExportError

        if not study_id:
            return None
        try:
            key = _digest_key(self.store, study_id, genes)
        except (StudyNotFound, OSError, ValueError):
            return None
        with _DIGESTS_LOCK:
            if key in _DIGESTS:
                return _DIGESTS[key]
        if not compute:
            return _MISSING
        try:
            digest = project_digest(self.store, study_id, genes)
        except (ExportError, StudyNotFound, OSError, ValueError, KeyError) as err:
            log.info("no Prism tables digest for %s: %s", study_id, err)
            return None
        with _DIGESTS_LOCK:
            if len(_DIGESTS) > 256:
                _DIGESTS.clear()
            _DIGESTS[key] = digest
        return digest

    def exports(self, session_id: str) -> list[dict[str, Any]]:
        """Every bundle sent to Prism from this session: study, folder, bundle sha256, time."""
        return list(self._meta(session_id).get("exports", []))

    def send_to_prism(
        self, session_id: str, out_dir: str | Path, actor: Actor, *, share: bool = False
    ) -> Any:
        """Write the bundle (CSVs, scripts, provenance) for the accepted Prism project.

        Only a person's click writes: ``actor`` must be ``human``, the choices stage must be
        confirmed and a ``prism.project`` for this study accepted. The export is remembered with
        the round-trip exclusions its analysis already holds, so a later round trip computes
        each consequence on top of exactly the ones accepted since.
        """
        from qpilot.prism import export_study

        _require_human(actor, "send a study to Prism")
        status = {s.stage: s for s in self.stages(session_id)}
        if not status["choices"].confirmed:
            raise StudioError("confirm the analysis choices first")
        study_id, accepted = self._study(session_id)
        project = self._accepted_project(session_id, study_id)
        if project is None:
            raise StudioError("accept the Prism project for this analysis first")
        pseudonym = self.store.pseudonymiser(session_id).pseudonymise if share else None
        result = export_study(
            self.store,
            study_id,
            out_dir,
            genes=project.get("genes") or None,
            template_id=project.get("template_id") or "two_groups_log2",
            share=share,
            pseudonym=pseudonym,
        )
        entry = {
            "study_id": study_id,
            "bundle_dir": str(Path(out_dir).resolve()),
            "bundle_sha256": result.bundle.bundle_sha256,
            "at": _now(),
            "exclusions": [p.id for p in accepted if p.kind == EXCLUSION_KIND],
        }
        if getattr(result, "project", None) is not None:
            entry["project"] = result.project.name
        self._edit_meta(session_id, lambda meta: meta.setdefault("exports", []).append(entry))
        return result

    def launch_prism(self, result: Any, actor: Actor, wait_s: float = PRISM_WAIT_S) -> dict:
        """Open the bundle's project in the scientist's Prism (or run a scripts-only bundle).

        A bundle with a Prism project (the default) is opened in Prism and not waited for: Prism
        shows it. A scripts-only bundle runs ``run.pzc`` and waits for its done file. Never
        runs without a person's click (``actor == "human"``) and never when Prism is not
        installed: then the bundle stays where it is, to open on the Prism machine.
        """
        from qpilot.prism.script import DONE_FILE

        _require_human(actor, "launch Prism")
        project = getattr(result, "project", None)
        if project is not None:
            return _open_project(Path(project), Path(result.out_dir))
        command = result.launch
        argv: list[str] | str = list(command.argv)
        if argv:  # macOS: osascript with a fixed argument list
            installed = _mac_prism_installed()
        else:  # Windows: Prism wants its documented command line verbatim (no shell)
            exe = command.command_line.split('"')[1] if command.command_line.startswith('"') else ""
            installed = bool(exe) and Path(exe).exists()
            argv = command.command_line
        if not installed:
            return {
                "launched": False,
                "note": "Prism is not installed on this computer; run run.pzc in Prism on the "
                "machine that has it (the bundle folder holds everything)",
                "bundle_dir": str(result.out_dir),
            }
        done = Path(result.out_dir) / DONE_FILE
        done.unlink(missing_ok=True)
        subprocess.run(argv, check=False, timeout=60)  # noqa: S603 (no shell; fixed command)
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline and not done.exists():
            time.sleep(1.0)
        return {"launched": True, "done": done.exists(), "bundle_dir": str(result.out_dir)}

    # ---- stage 5: the round trip --------------------------------------------------------------

    def round_trip(
        self, session_id: str, bundle_dir: str | Path, sent_back_dir: str | Path
    ) -> dict[str, Any]:
        """What changed in Prism since export; each change becomes a proposal with consequence.

        An exclusion asks "Reason?" and says whether it changes any conclusion; a changed value
        is a warning ("no longer matches the record") offering restore. Nothing is accepted.

        Each exclusion's consequence is computed on top of the exclusions a person accepted
        since this export (the ones accepted before it are in the exported analysis already),
        and records that ``basis``; with several exclusions, each also says what all of them do
        together (``with_all_pending``), and the report's ``combined_consequence`` is the same
        for the whole round trip. The sent-back folder is remembered with the export, so that
        accepting one exclusion can recompute the others (:meth:`refresh_round_trips`).
        """
        export = self._export(session_id, bundle_dir)
        sent_back = str(Path(sent_back_dir).resolve())
        report = self._diff(session_id, export, sent_back)
        inbox = self.store.proposals(session_id)
        outcomes = [inbox.propose(p, "system") for p in _round_trip_proposals(report, session_id)]

        def remember(meta: dict[str, Any]) -> None:
            for entry in meta.get("exports", []):
                if entry.get("bundle_dir") == export["bundle_dir"]:
                    entry["sent_back_dir"] = sent_back

        self._edit_meta(session_id, remember)
        report["inbox"] = _report(outcomes)
        return report

    def _export(self, session_id: str, bundle_dir: str | Path) -> dict[str, Any]:
        """The latest export of this session into ``bundle_dir``; ``StudioError`` if none."""
        folder = Path(bundle_dir).resolve()
        match = [e for e in self.exports(session_id) if Path(e["bundle_dir"]) == folder]
        if not match:
            raise StudioError("this bundle was not sent to Prism from this session")
        return match[-1]

    def _diff(self, session_id: str, export: dict[str, Any], sent_back_dir: str) -> dict[str, Any]:
        """``diff_report`` for one export, on top of the exclusions accepted since it."""
        from qpilot.prism import diff_report

        inbox = self.store.proposals(session_id)
        accepted = inbox.accepted(EXCLUSION_KIND)
        declined = [  # questions about this export's values a person turned down
            p
            for p in inbox.proposals(status="rejected", kind_prefix=EXCLUSION_KIND)
            if _basis_study(p) in ("", export["study_id"])
        ]
        return diff_report(
            self.store,
            export["study_id"],
            export["bundle_dir"],
            sent_back_dir,
            pseudonym=self.store.pseudonymiser(session_id).pseudonymise,
            accepted=_since_export(accepted, export),
            declined=declined,
        )

    def stale_consequence(self, session_id: str, proposal: Proposal) -> str | None:
        """Why a round-trip exclusion's consequence no longer holds, or None while it holds.

        A consequence holds while the exclusions a person accepted since its export are exactly
        the ones it was computed on top of (its ``basis``), and the exported analysis's decision
        chain is where it was. Its numbers are then what accepting it gives; otherwise the card
        says it is out of date and :meth:`accept` refuses it.
        """
        consequence = proposal.consequence
        if proposal.kind != EXCLUSION_KIND or not isinstance(consequence, dict):
            return None
        if "fc_before" not in consequence:  # no numbers, nothing to go out of date
            return None
        accepted = self.store.proposals(session_id).accepted(EXCLUSION_KIND)
        basis = consequence.get("basis")
        if not isinstance(basis, dict):  # made before consequences named their basis
            made = proposal.created_at or ""
            later = [p for p in accepted if (p.decided_at or "") >= made]
            return STALE_EXCLUSIONS if later else None
        export = self._latest_export(session_id, str(basis.get("study_id")))
        if export is None:
            return STALE_EXPORT
        then = basis.get("accepted")
        since = {p.id for p in _since_export(accepted, export)}
        if not isinstance(then, list) or {str(i) for i in then} != since:
            return STALE_EXCLUSIONS
        try:
            head = self.store.chain_head(export["study_id"])
        except StudyNotFound:
            return STALE_EXPORT
        return None if basis.get("chain_head") == head else STALE_CHOICES

    def refresh_round_trips(self, session_id: str) -> list[ProposalOutcome]:
        """Recompute every pending round-trip exclusion whose consequence is out of date.

        Its export is compared again with the sent-back folder its round trip read, and a fresh
        proposal (its consequence on top of the exclusions accepted since) replaces the pending
        one. Only pending questions are replaced: an exclusion a person already accepted or
        rejected is never asked again here. Where the folder cannot be read again, the
        out-of-date questions stay, marked as such, and are refused on accept.
        """
        inbox = self.store.proposals(session_id)
        stale = [
            p
            for p in inbox.proposals(status="proposed", kind_prefix=EXCLUSION_KIND)
            if p.made_by.kind == "rule" and self.stale_consequence(session_id, p) is not None
        ]
        outcomes: list[ProposalOutcome] = []
        for study_id in sorted({_basis_study(p) for p in stale} - {""}):
            export = self._latest_export(session_id, study_id, sent_back=True)
            if export is None:
                continue
            try:
                report = self._diff(session_id, export, export["sent_back_dir"])
            except (ValueError, OSError, KeyError) as err:  # moved, changed or unreadable
                log.info("round trip of %s not recomputed: %s", study_id, err)
                continue
            subjects = {p.subject for p in stale if _basis_study(p) == study_id}
            for fresh in _round_trip_proposals(report, session_id):
                if fresh.kind == EXCLUSION_KIND and fresh.subject in subjects:
                    outcomes.append(inbox.propose(fresh, "system"))
        return outcomes

    def _latest_export(
        self, session_id: str, study_id: str, *, sent_back: bool = False
    ) -> dict[str, Any] | None:
        """The latest export of ``study_id`` (with a remembered sent-back folder, if asked)."""
        for entry in reversed(self.exports(session_id)):
            if entry.get("study_id") == study_id and (not sent_back or entry.get("sent_back_dir")):
                return entry
        return None


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _since_export(accepted: Sequence[Proposal], export: dict[str, Any]) -> list[Proposal]:
    """The accepted round-trip exclusions an export's analysis does not hold yet.

    An export remembers the exclusions accepted when it was made (they are in its analysis);
    one remembered without them (made before exports recorded it) counts what a person decided
    from the moment of the export on.
    """
    held = export.get("exclusions")
    if isinstance(held, list):
        before = {str(i) for i in held}
        return [p for p in accepted if p.kind == EXCLUSION_KIND and p.id not in before]
    at = str(export.get("at") or "")
    return [p for p in accepted if p.kind == EXCLUSION_KIND and str(p.decided_at or "") >= at]


def _round_trip_proposals(report: dict[str, Any], session_id: str) -> list[Proposal]:
    """The proposals of a ``diff_report``, as proposals of this Studio session."""
    return [
        Proposal.model_validate(raw).model_copy(update={"study_id": session_id})
        for raw in report.get("proposals", [])
    ]


def _basis_study(proposal: Proposal) -> str:
    """The study a round-trip consequence was computed for ("" when it does not say)."""
    basis = (proposal.consequence or {}).get("basis")
    return str(basis.get("study_id") or "") if isinstance(basis, dict) else ""


def _in_stage(proposal: Proposal, stage: str) -> bool:
    if proposal.kind == "stage.confirm":  # only the system's confirm step belongs to a stage
        return proposal.subject == stage and _system_confirm(proposal)
    if stage == "design":
        return proposal.kind.startswith("design.")
    if stage == "curves":
        return proposal.kind.startswith("curve.")
    if stage == "choices":
        return proposal.kind.startswith("choice.")
    if stage == "prism":
        return proposal.kind == "prism.project"
    if stage == "roundtrip":
        return proposal.kind in ("prism.exclusion_reason", "prism.value_edit")
    return False


def _confirmed(
    accepted: list[Proposal], stage: str, assembly: Assembly, studio: Studio, session_id: str
) -> bool:
    """A stage is confirmed by an accepted ``stage.confirm`` that still describes it.

    Only the system's confirm step counts (made by the rule; the proposal store lets no one
    else propose one). The choices stage is described by the option applied on each Decision
    Card, so an agent's pending request, which applies nothing, never re-opens it; any change
    to an applied option does. A confirm from before that payload compares the chain head.
    """
    if assembly.design is None:
        return False
    current = studio.expected_study(session_id, assembly)
    if stage == "prism":  # done when the current analysis has been sent to Prism
        exports = studio._meta(session_id).get("exports", [])
        return any(e.get("study_id") == current for e in exports)
    confirms = [
        p
        for p in accepted
        if p.kind == "stage.confirm" and p.subject == stage and _system_confirm(p)
    ]
    if not confirms:
        return False
    payload = confirms[-1].effective_payload()
    if stage == "design":
        return payload.get("design_hash") == assembly.design_hash
    if stage == "curves":
        return payload.get("design_hash") == assembly.curves_hash
    if stage == "choices":
        if current is None or payload.get("study_id") != current:
            return False
        try:
            if "decisions" in payload:
                return payload["decisions"] == _decisions(studio.store.cards(current))
            return payload.get("chain_head") == studio.store.chain_head(current)
        except StudyNotFound:
            return False
    return False


def _carries(before: StudyDesign | None, after: StudyDesign) -> bool:
    """Two confirmed designs a person's choices carry between.

    They differ at most in the wells left out of the analysis, in the further choices the
    grid tests (``axes``, the efficiency models) and in what one reaction held
    (``reaction_input``, which changes only quantities per µL and per ng): each is decided
    after the curves, and the cards they share ask the same questions.
    """
    if before is None:
        return False
    same = {"excluded_wells": (), "axes": None, "reaction_input": None}
    hashes = {d.model_copy(update=same).design_hash() for d in (before, after)}
    return len(hashes) == 1


def _differ(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Two readings' conclusions differ: a gene's call, or what is reported for a sample.

    A quantification study's readings hold :class:`qpilot.qpcr.quantify_study.Reported`
    values: they differ when a sample's class does, or its number by more than 2-fold.
    """
    from qpilot.qpcr.quantify_study import Reported, changes

    if any(isinstance(v, Reported) for v in (*a.values(), *b.values())):
        names = {k: (k, "") for k in {*a, *b}}
        return bool(changes(a, b, names))
    return a != b


def _system_confirm(proposal: Proposal) -> bool:
    """True for the system's own confirm step (an agent's or a model's never counts)."""
    return proposal.made_by.kind == "rule"


def _decisions(cards: Sequence[DecisionCard]) -> dict[str, str]:
    """The option applied on each decided Decision Card (by a person, the system or an agent).

    A pending request leaves a card's applied option as it was, so it is not in here. Cards
    opened on demand (``ON_DEMAND_KINDS``) are not analysis choices, so they are left out.
    """
    return {
        c.id: c.decision for c in cards if c.decision is not None and c.kind not in ON_DEMAND_KINDS
    }


def _takes(func: Any, name: str) -> bool:
    try:
        return name in inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False


def _judge_status(input_sha256: str, path: Path) -> str:
    """The Curve Judge's status for one input file: ``"validated"`` only where it passed.

    ``curve_judge.validated(rdml_path)`` and ``status(rdml_path)`` answer for the file's
    instrument and chemistry. A Curve Judge whose ``validated`` cannot take the file is
    validated for no file except the very one its recorded transfer test ran on.
    """
    from qpilot.qpcr import curve_judge

    not_validated = str(getattr(curve_judge, "NOT_VALIDATED", "not validated for this instrument"))
    validated = getattr(curve_judge, "validated", None)
    status = getattr(curve_judge, "status", None)
    try:
        if validated is not None and _takes(validated, "rdml_path"):
            if status is not None and _takes(status, "rdml_path"):
                return str(status(rdml_path=path))
            return "validated" if validated(rdml_path=path) else not_validated
        transfer = getattr(curve_judge, "transfer_result", lambda: None)() or {}
        tested = transfer.get("data", {}).get("sha256") if isinstance(transfer, dict) else None
        if validated is not None and tested == input_sha256 and validated():
            return "validated"
    except Exception:  # a gate that cannot answer is a gate that did not pass
        return not_validated
    return not_validated


_CALL_FAILURES = (  # the client's own wording when no reply came back at all
    "endpoint call failed",
    "Anthropic call failed",
    "no model configured",
    "a remote model needs a pseudonymiser",
)


def _model_reason(error: str | None) -> str | None:
    """Why the model was not used, in qPilot's own words (never text from the model's reply)."""
    if not error:
        return None
    if error.startswith(_CALL_FAILURES):
        return error[:200]
    return "its replies did not pass qPilot's checks"


def _why_not(err: BaseException) -> str:
    """Why a model did not answer a one-token request (the HTTP status when there is one)."""
    reason = str(err)[:200] if str(err).startswith(_CALL_FAILURES) else type(err).__name__
    code = getattr(getattr(err.__cause__, "response", None), "status_code", None)
    if isinstance(code, int):
        reason += f" (HTTP {code}" + (": is the model pulled?" if code == 404 else "") + ")"
    return reason


def _with_lab_defaults(design: StudyDesign, summary: InspectSummary) -> StudyDesign:
    """A lab design's experiment (the one holding the compared samples) and headline genes."""
    update: dict[str, Any] = {}
    if design.design_id == BLANK_DESIGN_ID:
        update["design_id"] = "studio"
    if design.experiment_id is None:
        compared = {s for s, d in design.samples.items() if d.group}
        holding = [
            set(s.experiments) for s in summary.samples if s.sample in compared and s.experiments
        ]
        common = set.intersection(*holding) if holding else set()
        if len(common) == 1:
            update["experiment_id"] = common.pop()
    if not design.headline:
        refs = set(design.reference_candidates)
        ignored = {t for t, d in design.targets.items() if d.role == "ignore"}
        targets = sorted(t.target for t in summary.targets if t.target not in refs | ignored)
        if 0 < len(targets) <= 12:
            update["headline"] = tuple(targets)
    return design.model_copy(update=update) if update else design


def _not_decided(
    fields: Sequence[DesignField], makers: Sequence[MadeBy], accepted: Sequence[Proposal]
) -> tuple[list[DesignField], list[MadeBy], int]:
    """The fields a person has not already decided the same way, and how many were dropped.

    Proposing again (after a sample sheet is attached on the Design page, say) must not ask a
    person again what they decided: a field whose value equals the latest accepted decision on
    the same item is left out. A field that differs is proposed, so a new reading is never lost.
    """
    decided: dict[tuple[str, str], str] = {}
    for p in accepted:
        decided[(p.kind, p.subject)] = json.dumps(p.effective_payload(), sort_keys=True)
    kept: list[DesignField] = []
    kept_makers: list[MadeBy] = []
    for f, maker in zip(fields, makers, strict=True):
        if decided.get((f.kind, f.subject)) == json.dumps(f.value, sort_keys=True):
            continue
        kept.append(f)
        kept_makers.append(maker)
    return kept, kept_makers, len(fields) - len(kept)


def _fields_and_makers(
    result: Any, rule_fields: Sequence[DesignField]
) -> tuple[list[DesignField], list[MadeBy]]:
    """The interpreter's fields with who made each one (rule fields stay the rules')."""
    fields = list(getattr(result, "fields", rule_fields))
    makers = list(getattr(result, "makers", []))
    if len(makers) != len(fields):
        rule_set = {(f.kind, f.subject, json.dumps(f.value, sort_keys=True)) for f in rule_fields}
        makers = [
            MadeBy(kind="rule")
            if (f.kind, f.subject, json.dumps(f.value, sort_keys=True)) in rule_set
            else MadeBy(kind="model")
            for f in fields
        ]
    return fields, makers


def leaves_out(proposal: Proposal) -> bool:
    """A ``curve.exclude_well`` proposal leaves its well out (else it puts it back)."""
    return proposal.effective_payload().get("excluded") is True


def gate_card_of(proposal: Proposal) -> str | None:
    """The Run Gate card a ``curve.exclude_well`` proposal came from, if it did."""
    gate = (proposal.consequence or {}).get("gate") if proposal.kind == EXCLUDE_KIND else None
    card = gate.get("card_id") if isinstance(gate, dict) else None
    return card if isinstance(card, str) else None


def _latest_exclusions(view: InboxView) -> dict[str, Proposal]:
    """Per well, the ``curve.exclude_well`` a person accepted last (decision order)."""
    latest: dict[str, Proposal] = {}
    for p in view.accepted:
        if p.kind == EXCLUDE_KIND:
            latest[p.subject] = p
    return latest


def trace_card_of(proposal: Proposal) -> str | None:
    """The Trace place (its card id) a ``curve.exclude_well`` proposal came from, if it did."""
    found = (proposal.consequence or {}).get("trace") if proposal.kind == EXCLUDE_KIND else None
    card = found.get("card_id") if isinstance(found, dict) else None
    return card if isinstance(card, str) else None


def trust_choice(proposal: Proposal) -> str | None:
    """The Import Trust option a ``curve.import_trust`` proposal asks for."""
    option = proposal.effective_payload().get("option")
    return option if isinstance(option, str) and option in trust.OPTIONS else None


def trust_option(accepted: Sequence[Proposal]) -> str | None:
    """The option a person last accepted on the Import Trust card (decision order), or None."""
    found = [trust_choice(p) for p in accepted if p.kind == TRUST_KIND]
    return next((o for o in reversed(found) if o is not None), None)


def trust_decision(accepted: Sequence[Proposal]) -> Proposal | None:
    """The accepted proposal of the option in use on the Import Trust card, or None."""
    found = [p for p in accepted if p.kind == TRUST_KIND and trust_choice(p) is not None]
    return found[-1] if found else None


def trust_requests(view: InboxView) -> list[Proposal]:
    """Agents' requests on the Import Trust card that wait for a person, oldest first."""
    return [
        p
        for p in view.proposals
        if p.kind == TRUST_KIND and p.status == "proposed" and p.made_by.kind == "agent"
    ]


def _gate_plan(assembly: Assembly, view: InboxView, choice: GateChoice) -> _GatePlan:
    """The wells of a gate choice whose state changes, and the proposals that settle it.

    A well is left out when the design excludes it now. "Keep" puts back only the wells a
    person left out with ``curve.exclude_well``; a Prism round trip's exclusion stays. A waiting
    proposal on these wells from this card (or from no card) is used when it asks for what the
    person chose, and turned down when it asks for something else; one from another card is
    left for that card.
    """
    assert assembly.design is not None
    excluded = set(assembly.design.excluded_wells)
    by_person: dict[str, bool] = {}
    for p in view.accepted:  # in decision order: the latest acceptance wins
        if p.kind == EXCLUDE_KIND:
            by_person[p.subject] = leaves_out(p)
    wanted = set(choice.wells)
    changes: list[tuple[str, bool]] = []
    elsewhere: list[str] = []
    for well in choice.universe:
        want = well in wanted
        if want == (well in excluded):
            continue
        if not want and by_person.get(well) is not True:
            elsewhere.append(well)
            continue
        changes.append((well, want))
    mine = {choice.card_id, None}
    waiting = [
        p
        for p in view.proposals
        if p.kind == EXCLUDE_KIND
        and p.status == "proposed"
        and p.subject in choice.universe
        and gate_card_of(p) in mine
    ]
    new: list[tuple[str, bool]] = []
    settle: list[tuple[str, str]] = []
    used: set[str] = set()
    for well, want in changes:
        match = next((p for p in waiting if p.subject == well and leaves_out(p) is want), None)
        if match is None:
            new.append((well, want))
        else:
            settle.append((match.id, "accept"))
            used.add(match.id)
    for p in waiting:
        if p.id not in used:
            agrees = leaves_out(p) is (p.subject in wanted) and p.subject not in elsewhere
            settle.append((p.id, "accept" if agrees else "reject"))
    return _GatePlan(changes, new, settle, elsewhere)


def _report(
    outcomes: Sequence[ProposalOutcome],
    *,
    notes: Sequence[str] = (),
    rejected: Sequence[dict[str, Any]] = (),
    fallback: bool | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "proposed": [o.proposal.id for o in outcomes if o.status == "proposed" and o.proposal],
        "refused": [
            {"reason": o.reason, "subject": o.proposal.subject if o.proposal else None}
            for o in outcomes
            if o.status != "proposed"
        ],
        "notes": list(notes),
    }
    if rejected:
        out["model_fields_rejected"] = list(rejected)
    if fallback is not None:
        out["fallback"] = fallback
    return out


def _headline(result: Any) -> set[str]:
    from qpilot.qpcr.study import HEADLINE_GENES

    facts_headline = {g for g in HEADLINE_GENES if g in result.contrasts}
    return facts_headline or set(list(result.contrasts)[:4])


def _as_payload(draft: Any) -> dict[str, Any]:
    if hasattr(draft, "payload"):
        payload = draft.payload
        return dict(payload() if callable(payload) else payload)
    if hasattr(draft, "model_dump"):
        return draft.model_dump(mode="json")
    return dict(draft)


def _caption_facts(payload: dict[str, Any]) -> list[str]:
    import re

    text = json.dumps(payload)
    return sorted(set(re.findall(r"\{\{(f_[a-z0-9_]+)\}\}", text)))[:50]


_TIME_ZERO = re.compile(  # a time course's start: "0 h", "0h", "day 0", "t0", "time 0", "0 min"
    r"(^|[^a-z0-9.])(0\s*(h|hr|hrs|hours?|min|mins|minutes?|d|days?)|day\s*0|t\s*=?\s*0|time\s*0)"
    r"([^a-z0-9]|$)",
    re.IGNORECASE,
)
MAX_ALL_PAIRS_GROUPS = 5  # 10 comparisons; more groups and a person writes the list


def _vs_control(groups: Sequence[str], control: str) -> dict[str, Any]:
    """Each other group compared with ``control`` (the first, alphabetically, is the primary)."""
    others = [g for g in groups if g != control]
    return {
        "group_a": others[0],
        "group_b": control,
        "comparisons": [{"group_a": g, "group_b": control} for g in others],
        "pattern": "vs_control",
        "control": control,
        "correction": "holm",
    }


def _all_pairs(groups: Sequence[str]) -> dict[str, Any]:
    """Every pair of groups, each later group against each earlier one (sorted names)."""
    pairs = [{"group_a": b, "group_b": a} for i, a in enumerate(groups) for b in groups[i + 1 :]]
    return {
        **pairs[0],
        "comparisons": pairs,
        "pattern": "all_pairs",
        "correction": "holm",
    }


def _accepted_pairing(accepted: Sequence[Proposal]) -> str | None:
    """The pairing's name when a person accepted ``design.pair`` proposals (else ``None``)."""
    found = [p for p in accepted if p.kind == "design.pair" and p.effective_payload().get("pair")]
    if not found:
        return None
    names = {str(p.effective_payload().get("by") or "pair") for p in found}
    return sorted(names)[0] if len(names) == 1 else "pair"


_CONTROL_GROUP = re.compile(
    r"(^|[^a-z])(ctrl|control|vehicle|veh|pbs|wt|wild.?type|untreated|baseline|sham|mock|naive)"
    r"([^a-z]|$)",
    re.IGNORECASE,
)


def _preset_fields(summary: InspectSummary) -> list[DesignField]:
    """The demo file (pinned by sha256) gets its published design as a rule proposal."""
    from qpilot.io.datasets import VERMEULEN_SHA256

    if summary.input_sha256 != VERMEULEN_SHA256:
        return []
    return [
        DesignField(
            kind="design.preset",
            subject="design",
            value={"preset": "vermeulen_expression_defined"},
            cites=[],
            level="High",
            reasons=[
                "this file is the pinned Vermeulen neuroblastoma dataset (same sha256); its "
                "design compares tumours by MYCN expression (an expression-defined split, not a "
                "clinical call), with the five reference genes of the original study"
            ],
        )
    ]


_FEATURES: dict[tuple[str, str | None], Any] = {}


def _curve_features(path: Path, experiment_id: str | None) -> Any:
    """The Curve Judge's per-well curves for a file, read once per process (keyed by sha256)."""
    from qpilot.core.store import sha256_file
    from qpilot.qpcr import curve_judge

    key = (sha256_file(path), experiment_id)
    if key not in _FEATURES:
        if len(_FEATURES) >= 4:  # a few files at most; the demo is about 40 MB in memory
            _FEATURES.pop(next(iter(_FEATURES)))
        _FEATURES[key] = curve_judge.features_from_rdml(path, experiment_id)
    return _FEATURES[key]


_DIGESTS: dict[tuple[str, str, str, tuple[str, ...]], str] = {}
_DIGESTS_LOCK = threading.Lock()
_MISSING = object()  # a digest not computed yet (see Studio.prism_project_cached)


def _digest_key(store: Any, study_id: str, genes: Sequence[str] | None) -> tuple:
    """The cache key of a study's Prism tables digest: store, study, chain head, genes."""
    return (str(store.root), study_id, store.chain_head(study_id), tuple(genes or ()))


_MAC_APPS = (
    "/Applications/Prism 11.app",
    "/Applications/Prism 10.app",
    "/Applications/Prism 9.app",
    "/Applications/Prism.app",
    "/Applications/GraphPad Prism.app",
)


def _mac_prism_app() -> str | None:
    """Where GraphPad Prism is installed on this Mac, if it is."""
    return next((p for p in _MAC_APPS if Path(p).is_dir()), None)


def _mac_prism_installed() -> bool:
    return _mac_prism_app() is not None


def _windows_prism_exe() -> str | None:
    """Where GraphPad Prism is installed on this Windows computer, if it is."""
    roots = [os.environ.get(k) for k in ("ProgramFiles", "ProgramFiles(x86)")]
    for root in filter(None, roots):
        base = Path(root) / "GraphPad"
        if not base.is_dir():
            continue
        for folder in sorted(base.glob("Prism*"), reverse=True):
            exe = folder / "prism.exe"
            if exe.is_file():
                return str(exe)
    return None


def _open_project(project: Path, folder: Path) -> dict[str, Any]:
    """Open a project file in Prism when Prism is installed here (never waits for it)."""
    import sys

    note = (
        "Prism is not installed on this computer: download the bundle and double-click the "
        "project file on the computer that has Prism"
    )
    if sys.platform == "darwin":
        app = _mac_prism_app()
        if app is None:
            return {"launched": False, "note": note, "bundle_dir": str(folder)}
        argv = ["open", "-a", app, str(project)]
    elif sys.platform.startswith("win"):
        exe = _windows_prism_exe()
        if exe is None:
            return {"launched": False, "note": note, "bundle_dir": str(folder)}
        argv = [exe, str(project)]
    else:
        return {"launched": False, "note": note, "bundle_dir": str(folder)}
    try:
        subprocess.Popen(argv, close_fds=True)  # noqa: S603 (no shell; fixed command)
    except OSError as err:
        return {"launched": False, "note": f"Prism could not be started: {err}"}
    return {"launched": True, "done": None, "opened": project.name, "bundle_dir": str(folder)}


__all__ = ["BLIND_STAGES", "STAGES", "Assembly", "StageStatus", "Studio", "StudioError"]

_ = os  # imported for callers that patch the environment in tests
