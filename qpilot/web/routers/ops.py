"""Operations: agents, Ask, the model test, what the model saw, and a fresh demo.

* ``GET /api/agents``: how an agent connects (``claude mcp add qpilot -- qpilot serve``), the tools
  ``qpilot serve`` gives it (each marked read / open / propose / request), the requests waiting
  for a person in every study, and what agents did recently, newest first.
* ``POST /api/studies/{id}/ask``: a question, answered as a job by qPilot's own tools
  (:func:`qpilot.ai.ask.ask`, the MCP tool code), or, for verdict and what-if questions about an
  audited study, by the audit's Ask engine. The answer says which tool answered, who wrote the
  words and every fact it cites. Ask never writes (docs/app.md §1.1: every write from the page
  is a person's): asked to change a choice, it names the Decision Card to decide it on.
* ``POST /api/model/test``: the harness scorecard of the page's model on one study (a job), saved
  with the study's scorecards; ``GET /api/model/seen``: the last payload a model was sent.
* ``POST /api/demo/fresh``: moves the demo's earlier work aside (kept, never deleted).

A study of a Studio session whose design and curves are not both confirmed is blind: Ask and the
model test answer 403 ``blind``, and its agent entries are counted but not listed.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Query

from qpilot.core.decisions import DecisionError
from qpilot.core.store import StudyNotFound, StudyStore
from qpilot.web import views
from qpilot.web.context import KEY, AppContext, Ctx, api_error, check_key, is_session, is_study
from qpilot.web.contract import JobStarted, JobView, ModelSeen
from qpilot.web.contract_ops import (
    AgentActivity,
    AgentRequest,
    AgentsView,
    AgentTool,
    AskAnswer,
    AskBody,
    CitedFact,
    FreshDemo,
    ModelTestBody,
    ModelTestResult,
    ScorecardRow,
    ToolAccess,
)
from qpilot.web.jobs import JobError, Progress

router = APIRouter(tags=["ops"])

#: The model of each job's result, so the page's types carry them (``routers.job_results``).
JOB_RESULTS = {"ask": AskAnswer, "model.test": ModelTestResult}

CONNECT = "claude mcp add qpilot -- qpilot serve"
CONNECT_NOTE = (
    "Run this once in a terminal. Claude Code then starts `qpilot serve` itself; the agent reads "
    "and writes this same study store, and what it does appears here within about a second."
)
ACTIVITY_LIMIT = 60
# How long the work usually takes on the demo with no model (templates answer), measured on
# 20 Oct under load. With a model the time is the model's: no typical time is claimed.
ASK_TYPICAL_S = 0.5  # 0.03-0.4 s
AUDIT_ASK_TYPICAL_S = 1.0
MODEL_TEST_TYPICAL_S = 3.5  # nine questions

#: What each tool of ``qpilot serve`` can change (``tests/web/test_agents.py`` checks that every
#: served tool is here). ``sim_*`` tools all read the study's verified audit and change nothing.
TOOL_ACCESS: dict[str, tuple[ToolAccess, str]] = {
    "qpcr_study": (
        "open",
        "Analyses a file into a study with the default design, or reopens one. It decides no "
        "Decision Card, and a Studio session's design is used only once a person confirmed it.",
    ),
    "qpcr_robustness": ("read", "Nothing."),
    "qpcr_decide": (
        "request",
        "Asks to decide a Decision Card, recorded as the agent's. A choice that can change a "
        "conclusion always waits for a person; any other choice is applied only when the "
        "study lets agents decide and tell, and otherwise waits too.",
    ),
    "qpcr_plan": ("read", "Nothing."),
    "qpcr_propose": (
        "propose",
        "Adds a proposal to a Studio inbox, with the engine's own check. Only a person accepts, "
        "edits or rejects it.",
    ),
    "qpcr_proposals": ("read", "Nothing."),
    "qpcr_inspect": (
        "open",
        "Opens a Studio session for a file: nothing is analysed or proposed, and a session a "
        "person opened keeps its file and sample sheet.",
    ),
    "qpcr_check_design": ("read", "Nothing: the check is not saved."),
    "qpcr_curve_calls": ("read", "Nothing."),
    "qpcr_prism_preview": ("read", "Nothing: it shows what Send to Prism would write."),
    "qpcr_prism_diff": ("read", "Nothing: the differences are not stored."),
}
SIM_EFFECT = "Nothing: it reads the study's verified robustness audit."

#: What an agent can and cannot do (enforced in ``qpilot/mcp_server.py`` and the core).
RULES = (
    "An agent is always recorded as an agent; it can never act as a person.",
    "A choice that can change a conclusion always waits for a person: Approve or Turn down here "
    "or on the Decision Cards.",
    "Agents propose; only a person accepts, edits or rejects a proposal or confirms a stage.",
    "Results stay hidden from agents until a person confirms the design and the curves.",
    "Names from files reach an agent as quoted data, never as instructions.",
    "Agents open only files inside the folders allowed by QPILOT_DATA_ROOTS.",
)

#: Questions the audit answers best: verdicts, what-if, what to check first.
AUDIT_WORDS = re.compile(
    r"\b(verdicts?|solid|fragile|caveats?|depends?\s+on|what[\s-]+if|would\s+(it|the|this|that|"
    r"my|our)|suppose|hypothetically|audit|check\s+(the\s+)?data|look\s+at\s+first|issues?|"
    r"lean[s]?\s+on|survives?)\b",
    re.I,
)
#: Questions only the audit answers: what-if, what to check first, verdicts and the audit itself
#: (the study's own tools would answer them with something else).
AUDIT_ONLY_WORDS = re.compile(
    r"\b(what[\s-]+if|suppose|hypothetically|would\s+(it|the|this|that|my|our)|instead|"
    r"look\s+at\s+first|check\s+(the\s+)?data|issues?|verdicts?|audit(ed|s)?)\b",
    re.I,
)
NEEDS_AUDIT = (
    "This is a question for the robustness audit, which re-runs the study under every "
    "combination of the analysis choices. Run it in Audit, then ask again."
)
NO_AUDIT_ENGINE = "The audit's answers are not available in this build of qPilot."

#: Plain words for the facts qPilot's Ask adds to an answer (``qpilot/ai/ask.py``).
ANSWER_FACTS = {
    "f_ans_fc": "fold change under the recommended choices",
    "f_ans_ci_lo": "lower end of the 95 % confidence interval",
    "f_ans_ci_hi": "upper end of the 95 % confidence interval",
    "f_ans_p": "p-value",
    "f_ans_holds": "share of reasonable analyses with the same call",
    "f_ans_n_cells": "reasonable analyses",
    "f_ans_level": "confidence level",
    "f_ans_min_flip": "choices that flip the call together",
    "f_ans_n_plates": "plates",
    "f_ans_n_samples": "samples",
    "f_ans_n_reactions": "reactions",
    "f_ans_n_genes": "genes in this study",
    "f_ans_n_needed": "samples needed per group",
    "f_ans_mde_fold": "smallest change the planned design detects",
    "f_ans_needed_called": "how often qPilot's rule calls it at the needed size",
    "f_ans_planned_called": "how often qPilot's rule calls it at the planned size",
}
STUDY_TOOL_WORDS = {
    "qpcr_study": "the study summary",
    "qpcr_robustness": "the robustness of one gene across every reasonable analysis",
    "qpcr_decide": "a request to change a choice on a Decision Card",
    "qpcr_plan": "the sample-size planner",
    "explain_number": "where a number comes from",
    "none": "no tool (the question is not about this study)",
}
AUDIT_TOOL_WORDS = {
    "gene": "the audit's gene look-up",
    "whatif": "a live what-if run of the audit's engine",
    "decision": "the audit's choice summary",
    "issues": "the audit's issue queue",
    "overview": "the audit's study overview",
}
ROUTED_WORDS = {
    "model": "the model",
    "keywords": "keyword matching (no model)",
    "rules": "fixed reading rules",
}


# ---- where a study lives, and whether it is blind ----------------------------------------------


@dataclass(frozen=True)
class _Place:
    """The workspace a study belongs to, as the page routes to it."""

    key: str
    kind: Literal["session", "study"]
    visible: bool


class _Places:
    """Studies → their workspace, read once per request (sessions' ``studio.json``)."""

    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.session_of: dict[str, str] = {}
        sessions = ctx.store.root / "sessions"
        if sessions.is_dir():
            for folder in sorted(sessions.iterdir()):
                if folder.is_dir() and len(folder.name) == 64:
                    meta = views.session_meta(ctx.store, folder.name[:12])
                    for study_id in meta.get("studies") or {}:
                        self.session_of[study_id] = folder.name[:12]
        self._visible: dict[str, bool] = {}
        self._titles: dict[str, str] = {}

    def visible(self, sid: str) -> bool:
        """Whether a session's design and curves are both confirmed (fails closed)."""
        if sid not in self._visible:
            try:
                self._visible[sid] = bool(self.ctx.studio.results_visible(sid))
            except Exception:  # an unreadable session is treated as blind, never as open
                self._visible[sid] = False
        return self._visible[sid]

    def title(self, place: _Place) -> str:
        """The workspace's title as the workspace list shows it (its file's name, or the demo's)."""
        if place.key not in self._titles:
            store = self.ctx.store
            try:
                if place.kind == "session":
                    record = views.session_source_record(store, place.key)
                    sha = store.find_session(place.key).name
                else:
                    path = store.workspace(place.key) / "source.json"
                    record = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
                    sha = store.get(place.key).input_sha256
                name = Path(record["path"]).name if record.get("path") else None
                self._titles[place.key] = views._title(name, sha)
            except (StudyNotFound, OSError, ValueError, KeyError):
                self._titles[place.key] = f"Study {place.key}"
        return self._titles[place.key]

    def of_study(self, study_id: str) -> _Place:
        """The workspace of an analysed study."""
        sid = self.session_of.get(study_id)
        if sid is not None:
            return _Place(sid, "session", self.visible(sid))
        return _Place(study_id, "study", True)

    def of_session(self, sid: str) -> _Place:
        """A Studio session as a workspace."""
        return _Place(sid, "session", self.visible(sid))


BLIND_MESSAGE = (
    "Results stay hidden until the design and the curves are confirmed in this study's Studio "
    "session. Confirm them in Design and Curves first."
)


def resolve_study(ctx: AppContext, key: str) -> tuple[str, _Place, _Places]:
    """The analysed study a key names (a study id, or a session's current study), not blind.

    Raises:
        HTTPException: 404 ``not_found``, 403 ``blind``, 409 ``no_results``.
    """
    check_key(key)
    places = _Places(ctx)
    if is_study(ctx.store, key):
        place = places.of_study(key)
        study_id = key
    elif is_session(ctx.store, key):
        place = places.of_session(key)
        study_id = views.session_meta(ctx.store, key).get("current_study")
    else:
        raise api_error(404, "not_found", "There is no study or session with this id.")
    if not place.visible:
        raise api_error(403, "blind", BLIND_MESSAGE, session=place.key)
    if not study_id or not is_study(ctx.store, study_id):
        raise api_error(
            409,
            "no_results",
            "This session has no analysed study yet: confirm the curves to analyse it.",
        )
    return study_id, place, places


# ---- agents -----------------------------------------------------------------------------------

_catalogue: tuple[list[AgentTool], bool] | None = None
_catalogue_lock = threading.Lock()


def _describe(name: str, description: str, read_only: bool | None) -> AgentTool:
    text = inspect.cleandoc(description or "")
    summary = text.split("\n\n", 1)[0].replace("\n", " ").strip()
    simulator = name.startswith("sim_")
    if name in TOOL_ACCESS:
        access, effect = TOOL_ACCESS[name]
    elif simulator or read_only:
        access, effect = "read", SIM_EFFECT if simulator else "Nothing (a read-only tool)."
    else:  # a tool this page does not know yet: assume it may ask for changes
        access, effect = "request", "Not described here yet; read the tool's own description."
    return AgentTool(
        name=name,
        summary=summary,
        description=text,
        access=access,
        effect=effect,
        simulator=simulator,
    )


def tool_catalogue(store: StudyStore) -> tuple[list[AgentTool], bool]:
    """The tools ``qpilot serve`` registers on this install (built once: ~3 s of imports)."""
    global _catalogue
    with _catalogue_lock:
        if _catalogue is None:
            from qpilot.mcp_server import TOOL_NAMES, create_server, served_tool_names

            names = served_tool_names()
            server = create_server(store, simulator=names != TOOL_NAMES)
            listed = asyncio.run(server.list_tools())
            tools = []
            for tool in listed:
                hints = getattr(tool, "annotations", None)
                read_only = getattr(hints, "readOnlyHint", None) if hints else None
                tools.append(_describe(tool.name, tool.description or "", read_only))
            _catalogue = (tools, names != TOOL_NAMES)
        return list(_catalogue[0]), _catalogue[1]


def _connect(store: StudyStore) -> tuple[str, str | None]:
    """The connect command; it names this store unless it is the built-in default.

    Claude Code starts ``qpilot serve`` with its own environment, which need not carry this
    shell's ``QPILOT_STUDIES_DIR``: any other store is named in the command.
    """
    builtin = Path.home() / ".cache" / "qpilot" / "studies"
    if store.root.resolve() == builtin.resolve():
        return CONNECT, None
    root = str(store.root)
    quoted = f'"{root}"' if re.search(r"[\s\"'$`\\]", root) else root
    return (
        f"claude mcp add qpilot -e QPILOT_STUDIES_DIR={quoted} -- qpilot serve",
        "This page uses a study store other than the default one (~/.cache/qpilot/studies), "
        "so the command names it for the agent.",
    )


def _card_words(cards: dict[str, Any], card_id: str, option: str) -> tuple[str, str]:
    from qpilot.ai.explain import KIND_TITLE

    card = cards.get(card_id)
    if card is None:
        return card_id, option
    label = next((o.label for o in card.options if o.id == option), option)
    return KIND_TITLE.get(card.kind, card.kind), label


DECISION_WORDS = {
    "applied": "Set “{title}” to “{label}”",
    "auto": "Set “{title}” to “{label}”",
    "pending_human": "Asked a person to set “{title}” to “{label}”",
    "rejected": "Request turned down: “{title}”, “{label}”",
    "stale": "Not applied (the card changed since the agent read it): “{title}”, “{label}”",
}


def _study_entries(
    places: _Places, study_id: str
) -> tuple[_Place | None, list[AgentRequest], list[AgentActivity]]:
    """One study's pending agent requests and agent entries (decisions and refused attempts).

    The study's workspace (and whether it is blind) is looked up only when there is something
    to show, so a store without agent activity costs a few file reads.
    """
    from qpilot.core.decisions import needs_human

    store = places.ctx.store
    head, card_list, pending = store.snapshot(study_id)
    log = store.entries(study_id)
    rows = [e.model_dump() for e in log if e.actor == "agent"]
    rows += [a for a in store.attempts(study_id) if a.get("actor") == "agent"]
    if not pending and not rows:
        return None, [], []
    place = places.of_study(study_id)
    title = places.title(place)
    cards = {c.id: c for c in card_list}
    requests = []
    for entry in pending:
        card_title, label = _card_words(cards, entry.card_id, entry.option)
        card = cards.get(entry.card_id)
        requests.append(
            AgentRequest(
                key=place.key,
                kind=place.kind,
                study_id=study_id,
                title=title,
                card_id=entry.card_id,
                card_title=card_title,
                option=entry.option,
                option_label=label,
                reason=entry.reason,
                actor=entry.actor,
                at=entry.at,
                seq=entry.seq,
                hash=entry.hash,
                can_change_a_conclusion=bool(card is not None and needs_human(card)),
                expected_head=head,
            )
        )
    waiting = {e.hash for e in pending}
    activity = []
    for row in rows:
        settled = _settled(log, row, waiting) if row["status"] == "pending_human" else {}
        card_title, label = _card_words(cards, row["card_id"], row["option"])
        status = str(row["status"])
        words = DECISION_WORDS.get(status, "{title}: {label}")
        activity.append(
            AgentActivity(
                kind="decision",
                key=place.key,
                workspace_kind=place.kind,
                title=title,
                at=str(row["at"]),
                summary=words.format(title=card_title, label=label),
                status=status,
                reason=row.get("reason"),
                card_id=row["card_id"],
                option=row["option"],
                seq=row.get("seq"),
                hash=row.get("hash") or None,
                **settled,
            )
        )
    return place, requests, activity


def _settled(log: list[Any], request: dict[str, Any], waiting: set[str]) -> dict[str, Any]:
    """What became of an agent's request: still waiting, or the later entry that settled it.

    The same replay as the store's pending list (``core.store.pending_after``): an applied
    decision on the card settles every request on it; a person's rejection settles the
    requests for the option it names.
    """
    if request.get("hash") in waiting:
        return {"request_state": "waiting"}
    later = [e for e in log if e.seq > request["seq"] and e.card_id == request["card_id"]]
    for entry in later:
        if entry.status == "applied":
            state = "approved" if entry.option == request["option"] else "decided_otherwise"
        elif entry.status == "rejected" and entry.actor == "human":
            if entry.option != request["option"]:
                continue
            state = "turned_down"
        else:
            continue
        return {"request_state": state, "settled_by": entry.actor, "settled_at": entry.at}
    return {"request_state": "closed"}


PROPOSAL_WORDS = {
    "proposed": "Proposed",
    "accepted": "Proposed (a person accepted it)",
    "edited": "Proposed (a person edited and accepted it)",
    "rejected": "Proposed (a person rejected it)",
    "superseded": "Proposed (replaced by a later proposal)",
}


def _session_proposals(places: _Places, sid: str) -> list[AgentActivity]:
    """Proposals an agent made in one session's inbox (results-stage ones only once visible)."""
    from qpilot.web.studio_views import blind_kind

    made = [p for p in places.ctx.studio.inbox(sid) if p.made_by.kind == "agent"]
    if any(not blind_kind(p) for p in made) and not places.visible(sid):
        made = [p for p in made if blind_kind(p)]
    if not made:
        return []
    place = _Place(sid, "session", True)
    title = places.title(place)
    return [
        AgentActivity(
            kind="proposal",
            key=sid,
            workspace_kind="session",
            title=title,
            at=p.created_at,
            summary=f"{PROPOSAL_WORDS.get(p.status, 'Proposed')}: {p.kind} for “{p.subject}”",
            agent=p.made_by.agent,
            status=p.status,
            reason=p.reason,
            proposal_id=p.id,
            proposal_kind=p.kind,
            check=p.check.status,
        )
        for p in made
    ]


@router.get("/agents", response_model=AgentsView)
def agents(ctx: Ctx) -> AgentsView:
    """How an agent connects, its tools, requests waiting for a person, recent agent activity."""
    tools, simulator = tool_catalogue(ctx.store)
    connect, store_note = _connect(ctx.store)
    places = _Places(ctx)
    pending: list[AgentRequest] = []
    activity: list[AgentActivity] = []
    hidden = 0
    for study_id in _study_ids(ctx.store):
        try:
            place, requests, entries = _study_entries(places, study_id)
        except (StudyNotFound, OSError, ValueError):
            continue
        if place is not None and not place.visible:
            hidden += len(requests) + len(entries)
            continue
        pending += requests
        activity += entries
    for sid in sorted(_session_ids(ctx.store)):
        try:
            activity += _session_proposals(places, sid)
        except (StudyNotFound, OSError, ValueError):
            continue
    pending.sort(key=lambda r: (r.at, r.seq))
    activity.sort(key=lambda a: a.at, reverse=True)
    return AgentsView(
        connect=connect,
        connect_note=CONNECT_NOTE,
        store_note=store_note,
        tools=tools,
        simulator=simulator,
        rules=list(RULES),
        pending=pending,
        activity=activity[:ACTIVITY_LIMIT],
        activity_total=len(activity),
        hidden_blind=hidden,
    )


def _study_ids(store: StudyStore) -> list[str]:
    """Study ids of every readable workspace; a damaged or half-written one is skipped.

    The store is shared with agents, scripts and other qPilot processes (and may sit in a synced
    folder), so one unreadable ``results.json`` must not hide every other study.
    """
    out = []
    for folder in sorted(store.root.iterdir()):
        path = folder / "results.json"
        if not folder.is_dir() or not path.is_file():  # never open a pipe or a device
            continue
        try:
            study_id = json.loads(path.read_text(encoding="utf-8"))["study_id"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if isinstance(study_id, str) and KEY.match(study_id):
            out.append(study_id)
    return out


def _session_ids(store: StudyStore) -> set[str]:
    sessions = store.root / "sessions"
    if not sessions.is_dir():
        return set()
    return {d.name[:12] for d in sessions.iterdir() if d.is_dir() and len(d.name) == 64}


# ---- Ask -------------------------------------------------------------------------------------


def _audit_engine() -> Any:
    """The audit routes' cached-screen accessor (``audit_screen``), or None in a build without."""
    try:
        from qpilot.web.routers.audit import audit_screen
    except ImportError:
        return None
    return audit_screen


Engine = Literal["study", "audit", "none"]
Autonomy = Literal["suggest", "decide_and_tell"]


def _pick_engine(question: str, source: str, audit: bool, engine: bool) -> Engine:
    """Which engine answers: the audit for verdict and what-if questions, else the study's.

    ``none`` when only the audit could answer and it has not been run (or this build lacks it).
    A request to change a choice always goes to the study's tools (and so to the human gate).
    """
    from qpilot.ai.ask import DECIDE_WORDS, NOT_A_REQUEST

    if source == "study":
        return "study"
    if source == "audit":
        if not audit:
            raise api_error(409, "no_audit", NEEDS_AUDIT)
        if not engine:
            raise api_error(409, "no_audit", NO_AUDIT_ENGINE)
        return "audit"
    if DECIDE_WORDS.search(question) and not NOT_A_REQUEST.search(question):
        return "study"
    if audit and engine and AUDIT_WORDS.search(question):
        return "audit"
    return "none" if AUDIT_ONLY_WORDS.search(question) else "study"


def _no_engine(question: str, audit: bool, autonomy: Autonomy, head: str) -> AskAnswer:
    """The answer to a question only the audit answers, when there is no audit to ask."""
    return AskAnswer(
        question=question,
        answer=NO_AUDIT_ENGINE if audit else NEEDS_AUDIT,
        engine="none",
        tool="none",
        tool_words="no tool: only the robustness audit answers this",
        routed_by="rules",
        routed_words=ROUTED_WORDS["rules"],
        written_by="template",
        writer_words="qPilot's fixed words",
        provider="none",
        facts=[],
        validated=True,
        autonomy=autonomy,
        head_before=head,
        head_after=head,
    )


def _autonomy(ctx: AppContext, study_id: str) -> Literal["suggest", "decide_and_tell"]:
    """What the study lets agents do (``StudyStore.autonomy``; Ask itself never decides)."""
    try:
        level = ctx.store.autonomy(study_id)
    except (StudyNotFound, OSError, ValueError):
        level = "suggest"
    return "decide_and_tell" if level == "decide_and_tell" else "suggest"


class _AskStore(StudyStore):
    """The store as Ask sees it: it reads; it never decides, requests or turns down.

    A change Ask is asked for reaches ``apply_decision`` like an agent's; here it is refused
    before anything is written, and the answer names the card a person decides it on.
    """

    def append_decision(self, *args: Any, **kwargs: Any) -> Any:
        """Refused: Ask never writes to the decision log."""
        raise DecisionError(ASK_NEVER_DECIDES)

    def request_human(self, *args: Any, **kwargs: Any) -> Any:
        """Refused: Ask never files a request."""
        raise DecisionError(ASK_NEVER_DECIDES)

    def reject_pending(self, *args: Any, **kwargs: Any) -> Any:
        """Refused: only a person turns a request down, on the card."""
        raise DecisionError(ASK_NEVER_DECIDES)

    def set_autonomy(self, *args: Any, **kwargs: Any) -> None:
        """Refused: autonomy is a person's setting."""
        raise DecisionError(ASK_NEVER_DECIDES)


ASK_NEVER_DECIDES = "Ask never changes a choice; a person decides it on its Decision Card"


def _client(ctx: AppContext) -> Any:
    """A client over the page's model with its own call log (each job logs only its calls)."""
    from qpilot.ai.client import ModelClient

    return ModelClient(backend=ctx.studio.client.backend)


def _typical(ctx: AppContext, seconds: float) -> float | None:
    """The measured time without a model; none is claimed when a model answers."""
    return None if ctx.studio.client.available else seconds


def _model_note(ctx: AppContext) -> str | None:
    """Why the page's model is not used, when it is not (no model, misconfigured)."""
    status = ctx.studio.model_status()
    if status["configured"]:
        return None
    return f"A template answered: {status['reason'] or 'no model is configured'}."


def _cited(text: str, facts: dict[str, Any]) -> list[CitedFact]:
    from qpilot.ai.ask import _path_words
    from qpilot.core.validator import render_tokens

    out: list[CitedFact] = []
    for fid in dict.fromkeys(re.findall(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}", text)):
        fact = facts.get(fid)
        if fact is None:
            continue
        meaning = ANSWER_FACTS.get(fid) or _path_words(fact.path)
        out.append(
            CitedFact(id=fid, meaning=meaning, value=render_tokens("{{" + fid + "}}", facts))
        )
    return out


def _ask_study(ctx: AppContext, study_id: str, question: str, autonomy: Autonomy) -> AskAnswer:
    """Ask with qPilot's own tools (the MCP tool code), through a store that never writes."""
    from qpilot.ai.ask import ask
    from qpilot.ai.suggest_only import load_profile_or_default

    store = ctx.store
    client = _client(ctx)
    before = store.chain_head(study_id)
    answer = ask(
        question,
        _AskStore(store.root),
        study_id,
        client=client,
        profile=load_profile_or_default(),
    )
    facts = {**store.get(study_id).facts, **answer.facts}
    call = answer.tool_calls[-1] if answer.tool_calls else {"tool": "none", "args": {}}
    tool, args = str(call.get("tool")), dict(call.get("args") or {})
    used = client.available and not answer.fallback
    text, cited, focus, card_id = answer.plain, _cited(answer.answer, facts), None, None
    note = None
    if answer.fallback:
        note = _model_note(ctx) or (
            f"A template answered; the model was not used: {answer.error}."
            if answer.error
            else None
        )
    if tool == "qpcr_decide":
        cards = {c.id: c for c in store.cards(study_id)}
        card_id = str(args.get("card_id") or "")
        if card_id in cards:
            option = str(args.get("option") or "")
            title, label = _card_words(cards, card_id, option)
            asked = option in {o.id for o in cards[card_id].options}
            text = (
                f"Ask never changes a choice. Decide “{title}” on its Decision Card"
                + (f" (you asked for “{label}”)" if asked else "")
                + ", with your reason."
            )
            cited, focus = [], f"card:{card_id}"
            note = "Nothing was written: every choice is a person's, made on its card."
        else:
            card_id = None
    return AskAnswer(
        question=answer.question,
        answer=text,
        engine="study",
        tool=tool,
        args=args,
        tool_words=STUDY_TOOL_WORDS.get(tool, tool),
        routed_by="model" if answer.tool_from_model else "keywords",
        routed_words=ROUTED_WORDS["model" if answer.tool_from_model else "keywords"],
        written_by="model" if used else "template",
        writer_words=f"the model {client.model or client.provider}, every number checked"
        if used
        else "qPilot's checked template",
        provider=answer.provider,
        model=client.model if client.available else None,
        facts=cited,
        validated=answer.validated or focus is not None,  # the card's words are qPilot's own
        note=note,
        card_id=card_id,
        focus=focus,
        autonomy=autonomy,
        head_before=before,
        head_after=store.chain_head(study_id),
    )


def _shown(text: str, facts: list[dict[str, Any]]) -> list[CitedFact]:
    """The audit's facts that its answer shows (its words are rendered; values are matched).

    The audit's Ask returns every fact its tool computed; the answer cites some of them. A fact
    is listed when its value appears in the answer as a whole token.
    """
    out = []
    for fact in facts:
        value = str(fact.get("value", ""))
        if value and re.search(rf"(?<![\w.]){re.escape(value)}(?![\w])", text):
            meaning = str(fact.get("meaning") or fact.get("id") or "")
            out.append(CitedFact(id=fact.get("id"), meaning=meaning, value=value))
    return out


def _ask_audit(ctx: AppContext, study_id: str, question: str, autonomy: Autonomy) -> AskAnswer:
    """The audit's Ask engine (qsim's ``Asker``) over the study's cached audit screen."""
    from fastapi import HTTPException

    audit_screen = _audit_engine()
    try:
        screen = audit_screen(ctx, study_id) if audit_screen is not None else None
    except HTTPException as err:  # the audit routes' own refusals (blind, not found), in words
        detail = err.detail if isinstance(err.detail, dict) else {}
        raise JobError(
            str(detail.get("code", "audit")), str(detail.get("message", err.detail))
        ) from err
    if screen is None:
        raise JobError("no_audit", "This study has no robustness audit yet: run it in Audit first.")
    out = screen.ask(question)
    routed = str(out.get("routed_code") or "keywords")
    written = str(out.get("written_code") or "template")
    model = out.get("model") if written == "model" or routed == "model" else None
    head = ctx.store.chain_head(study_id)
    problems = [str(p) for p in out.get("problems") or []]
    return AskAnswer(
        question=question,
        answer=str(out["text"]),
        engine="audit",
        tool=str(out["tool"]),
        args=dict(out.get("args") or {}),
        tool_words=AUDIT_TOOL_WORDS.get(str(out["tool"]), str(out.get("tool_words", ""))),
        routed_by="model" if routed == "model" else "rules" if routed == "rules" else "keywords",
        routed_words=ROUTED_WORDS.get(routed, routed),
        written_by="model" if written == "model" else "template",
        writer_words=str(out.get("written_by") or "the audit's checked template"),
        provider=ctx.studio.client.provider,
        model=model,
        facts=_shown(str(out["text"]), out.get("facts") or []),
        validated=True,  # the audit's answers are rendered from its facts, or rejected
        note=("A template answered: " + "; ".join(problems) + ".") if problems else None,
        autonomy=autonomy,
        head_before=head,
        head_after=head,
    )


_asking: dict[tuple[int, str, str, str], str] = {}  # (runner, study, engine, question) -> job
_asking_lock = threading.Lock()


@router.post("/studies/{study_id}/ask", response_model=JobStarted, status_code=202)
def ask_question(study_id: str, body: AskBody, ctx: Ctx) -> JobStarted:
    """Answer a question about a study (a job); every number in the answer is a cited fact."""
    question = body.question.strip()
    if not question:
        raise api_error(422, "bad_request", "Type a question first.")
    study_id, place, _ = resolve_study(ctx, study_id)
    autonomy = _autonomy(ctx, study_id)
    audit = views.audit_dir(ctx.store, study_id) is not None
    engine = _pick_engine(question, body.source, audit, _audit_engine() is not None)

    def work(progress: Progress) -> dict[str, Any]:
        if engine == "none":
            answer = _no_engine(question, audit, autonomy, ctx.store.chain_head(study_id))
            return answer.model_dump(mode="json")
        progress("Reading the audit" if engine == "audit" else "Looking it up in the study")
        answer = (_ask_audit if engine == "audit" else _ask_study)(
            ctx, study_id, question, autonomy
        )
        if answer.head_after != answer.head_before:
            for key in dict.fromkeys((study_id, place.key)):
                ctx.bus.publish({"type": "study.changed", "key": key, "source": "page"})
        return answer.model_dump(mode="json")

    # The same question asked again while it runs gets the running job (a model call is not
    # repeated, a request is not filed twice); different questions run side by side.
    asking = (id(ctx.jobs), study_id, engine, " ".join(question.lower().split()))
    with _asking_lock:
        job = ctx.jobs.get(_asking.get(asking, ""))
        if job is None or job.status not in ("queued", "running"):
            job = ctx.jobs.submit(
                "ask",
                work,
                title=f"Answering “{question[:60]}{'…' if len(question) > 60 else ''}”",
                key=place.key,
                typical_s=_typical(
                    ctx, AUDIT_ASK_TYPICAL_S if engine == "audit" else ASK_TYPICAL_S
                ),
                dedupe=False,
            )
            _asking[asking] = job.id
            while len(_asking) > 200:  # the last few hundred questions are enough
                _asking.pop(next(iter(_asking)))
    return JobStarted(job=JobView(**job.view()))


# ---- the model -------------------------------------------------------------------------------


def _default_study(ctx: AppContext) -> str:
    """The demo study when it is analysed and visible, else the most recent visible study."""
    best: str | None = None
    for line in views.workspaces(ctx.studio):  # newest first
        if not line.results_visible or not line.study_id or not is_study(ctx.store, line.study_id):
            continue
        if line.is_demo:
            return line.study_id
        best = best or line.study_id
    if best is None:
        raise api_error(
            409,
            "no_study",
            "Analyse a study first: the model is tested with questions about its results "
            "(open the demo study, confirm its design and curves).",
        )
    return best


def _row(saved: dict[str, Any]) -> ScorecardRow | None:
    """A saved scorecard as a row of the Ask table (None for a Studio-only scorecard)."""
    from qpilot.harness.make_evalset import ASK_KINDS
    from qpilot.harness.report import Report

    report = Report.model_validate(saved)
    ask = [report.correct_by_kind.get(k, [0, 0]) for k in ASK_KINDS]
    right, total = sum(a[0] for a in ask), sum(a[1] for a in ask)
    if not total:
        return None
    caught = report.invented_numbers - sum(
        s.invented_numbers for s in report.items if s.kind not in ASK_KINDS
    )
    return ScorecardRow(
        profile=report.profile,
        provider=report.provider,
        model=report.model,
        endpoint=report.endpoint,
        run_at=report.run_at,
        n_items=total,
        correct=right,
        correct_by_model=report.correct_by_model,
        model_eligible=report.model_eligible,
        invented_numbers_caught=caught,
        numbers_shown=report.numbers_shown,
        safety_held=report.safety[0],
        safety_items=report.safety[1],
        fallbacks=None if report.provider == "none" else report.fallbacks,
        median_latency_s=report.median_latency_s,
        notes=list(report.notes),
    )


FALLBACKS = (
    "Fallbacks count answers where the model was not usable and a template answered instead."
)


def _rows(saved: dict[str, Any]) -> dict[str, ScorecardRow]:
    """Saved scorecards by profile, as rows of the Ask table (Studio-only ones left out)."""
    rows = {}
    for profile, report in saved.items():
        if profile == "history" or not isinstance(report, dict):  # the CLI keeps earlier runs
            continue
        row = _row(report)
        if row is not None:
            rows[profile] = row
    return rows


def _scorecards(
    study_id: str, title: str, rows: dict[str, ScorecardRow], profile: str, note: str
) -> ModelTestResult:
    current = rows.get(profile)
    return ModelTestResult(
        study_id=study_id,
        title=title,
        current=current,
        saved=list(rows.values()),
        n_questions=current.n_items if current else 0,
        note=note,
    )


@router.post("/model/test", response_model=JobStarted, status_code=202)
def test_model(ctx: Ctx, body: ModelTestBody | None = None) -> JobStarted:
    """Score the page's model on questions about one study (a job); saved with the study."""
    key = (body.study if body else None) or _default_study(ctx)
    study_id, place, places = resolve_study(ctx, key)
    title = places.title(place)

    def work(progress: Progress) -> dict[str, Any]:
        from qpilot.ai.suggest_only import run_scorecard

        client = _client(ctx)
        progress(
            "Asking the questions"
            + (f" to {client.model or client.provider}" if client.available else " (templates)")
        )
        profile, saved, n = run_scorecard(ctx.store, study_id, client)
        rows = _rows(saved)
        if profile not in rows:
            raise JobError("failed", "The model test produced no scorecard.")
        note = f"Computed now on {n} questions about {title}. {FALLBACKS}"
        return _scorecards(study_id, title, rows, profile, note).model_dump(mode="json")

    job = ctx.jobs.submit(
        "model.test",
        work,
        title=f"Testing the model on {title}",
        key=place.key,
        typical_s=_typical(ctx, MODEL_TEST_TYPICAL_S),
    )
    return JobStarted(job=JobView(**job.view()))


@router.get("/model/scorecards", response_model=ModelTestResult)
def model_scorecards(
    ctx: Ctx, study: str | None = Query(default=None, max_length=12)
) -> ModelTestResult:
    """A study's saved scorecards (default: the demo study, else the latest visible one)."""
    from qpilot.ai.suggest_only import SCORECARD_KEYS

    study_id, place, places = resolve_study(ctx, study or _default_study(ctx))
    title = places.title(place)
    provider = ctx.studio.client.provider
    profile = SCORECARD_KEYS.get(provider, provider)
    rows = _rows(ctx.store.scorecard(study_id))
    if profile in rows:
        note = f"The last test of this model on {title}. {FALLBACKS}"
    else:
        note = f"This model has not been tested on {title} yet: Test this model scores it."
    return _scorecards(study_id, title, rows, profile, note)


@router.get("/model/seen", response_model=ModelSeen)
def model_seen(ctx: Ctx, study: str | None = Query(default=None, max_length=12)) -> ModelSeen:
    """The last payload a model was sent (memory only), withheld while results are blind.

    With ``study`` (a study or session id) it is gated by that workspace; without it, by every
    session (hidden while any is blind, unless the Design Interpreter sent it).
    """
    from qpilot.web import studio_views as sv

    places = _Places(ctx)
    if study is not None:
        check_key(study)
        if is_study(ctx.store, study):
            sids = [places.session_of[study]] if study in places.session_of else []
        elif is_session(ctx.store, study):
            sids = [study]
        else:
            raise api_error(404, "not_found", "There is no study or session with this id.")
    else:
        sids = sorted(_session_ids(ctx.store))
    blind = next((sid for sid in sids if not places.visible(sid)), None)
    if blind is not None:
        return sv.model_seen(ctx.studio, blind)
    if sids:
        return sv.model_seen(ctx.studio, sids[0])
    return _seen_ungated()


def _seen_ungated() -> ModelSeen:
    """The last payload, shown: no Studio session can be blind in this store."""
    import hashlib

    from qpilot.ai import payload_log
    from qpilot.ai.prompts import SYSTEM_INTERPRET
    from qpilot.web.studio_views import MAX_PAYLOAD_CHARS, WORDS

    last = payload_log.last_payload()
    if last is None:
        return ModelSeen(state="none", message=WORDS["seen_none"], interpreter=False)
    canonical = payload_log.canonical(dict(last)).encode("utf-8")
    return ModelSeen(
        state="shown",
        message=WORDS["seen_shown"],
        payload_text=json.dumps(last, indent=2, ensure_ascii=False, default=str)[
            :MAX_PAYLOAD_CHARS
        ],
        sha256=hashlib.sha256(canonical).hexdigest(),
        interpreter=last.get("system") == SYSTEM_INTERPRET,
    )


# ---- the fresh demo --------------------------------------------------------------------------


@router.post("/demo/fresh", response_model=FreshDemo)
def fresh_demo(ctx: Ctx) -> FreshDemo:
    """Move the demo's session, studies and audits aside (kept, never deleted)."""
    demo_keys = _demo_keys(ctx.store)
    if any(job.key in demo_keys for job in ctx.jobs.active()):
        raise api_error(
            409,
            "busy",
            "Work on the demo study is still running; start a fresh demo once it has finished.",
        )
    with ctx.lock:
        try:
            moved = views.archive_demo(ctx.store)
        except (OSError, ValueError, KeyError, TypeError) as err:  # nothing was moved yet
            raise api_error(
                409,
                "damaged",
                "A study folder in the store could not be read, so nothing was moved: "
                f"{str(err)[:200]}",
            ) from err
    for key in sorted(demo_keys):
        ctx.bus.publish({"type": "study.changed", "key": key, "source": "page"})
    ctx.bus.publish({"type": "study.changed", "key": None, "source": "page"})
    if not moved:
        return FreshDemo(moved=[], message="There was no earlier demo work to move aside.")
    return FreshDemo(
        moved=[str(p) for p in moved],
        archive=str(moved[0].parent),
        message=f"Earlier demo work moved to {moved[0].parent} (kept, never deleted). "
        "Open the demo study to start again.",
    )


def _demo_keys(store: StudyStore) -> set[str]:
    """The demo's session id and its studies' ids."""
    sha = views.demo_sha()
    keys = {sha[:12]}
    for study_id in _study_ids(store):
        try:
            if store.get(study_id).input_sha256 == sha:
                keys.add(study_id)
        except (StudyNotFound, OSError, ValueError):
            continue
    return keys
