"""Typed refusals: one stable code for every answer that does not do what an agent asked.

Every tool reply that is not the thing asked for carries ``code`` (one of :class:`Code`) and
``fix`` (what the agent, or a person, does next). Two kinds:

- **Refusals** (``error``, ``code`` and ``fix`` in the reply; MCP ``isError: true``): nothing
  was decided, proposed or opened, because the request itself cannot be served (an unknown
  study, a path outside the data roots, a choice only a person makes, a stale head, a proposal
  the engine's rules refuse, ...). ``error`` is one plain sentence. A stale ``qpcr_decide`` and a
  refused ``qpcr_propose`` also keep their ``status`` (``stale``, ``refused``) and ``reason``; a
  stale attempt is noted outside the decision chain, so it never moves the head.
- **Waiting for a person** (``status: "pending_human"``; not an error): the request *was*
  recorded and waits in the scientist's queue; ``code`` says why it waits.

Codes are part of the public contract: they are never renamed or reused for another meaning,
and new ones are only added. ``fix`` texts carry no digits (they are prose an agent may repeat);
a limit a refusal quotes is in the ``error`` text from the engine or in a structured field.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Code(StrEnum):
    """The refusal codes, stable across releases."""

    NEEDS_HUMAN_DECISION = "needs_human_decision"
    AUTONOMY_FORBIDS = "autonomy_forbids"
    STALE_HEAD = "stale_head"
    PROPOSAL_REFUSED = "proposal_refused"
    HUMAN_ONLY = "human_only"
    RESULTS_HIDDEN = "results_hidden"
    PATH_NOT_ALLOWED = "path_not_allowed"
    UNSUPPORTED_INPUT = "unsupported_input"
    INPUT_UNREADABLE = "input_unreadable"
    UNKNOWN_STUDY = "unknown_study"
    UNKNOWN_ITEM = "unknown_item"
    INVALID_ARGUMENT = "invalid_argument"
    IDEMPOTENCY_KEY_REUSED = "idempotency_key_reused"
    INTEGRITY_FAILED = "integrity_failed"
    NOT_INSTALLED = "not_installed"
    NOT_READY = "not_ready"
    NOT_APPLICABLE = "not_applicable"
    ENGINE_REFUSED = "engine_refused"


@dataclass(frozen=True)
class RefusalSpec:
    """What a code means, what to do about it, and whether the same call can succeed later."""

    meaning: str
    fix: str
    retry_later: bool = False  # the same arguments may succeed once something else happens


REFUSALS: dict[Code, RefusalSpec] = {
    Code.NEEDS_HUMAN_DECISION: RefusalSpec(
        "This choice can change a conclusion, so only a person may make it, at every autonomy "
        "level. Your request is recorded and waits for the scientist.",
        "Tell the person which card and option you asked for and why; they decide it on the "
        "Decision Cards in qPilot. Read the outcome later with qpcr_study. Do not ask again.",
        retry_later=True,
    ),
    Code.AUTONOMY_FORBIDS: RefusalSpec(
        "The scientist keeps this study in Suggest mode: agents may ask but not apply choices, "
        "even ones that change no conclusion. Your request is recorded and waits.",
        "Ask the person to decide it in qPilot, or to switch the study to decide-and-tell if "
        "they want agents to apply choices that change no conclusion.",
        retry_later=True,
    ),
    Code.STALE_HEAD: RefusalSpec(
        "The study changed since you read it (expected_head is not the current head), so "
        "nothing was recorded.",
        "Read the study again (qpcr_study gives chain_head, qpcr_proposals gives head), check "
        "your request still makes sense, and retry with the new head.",
    ),
    Code.PROPOSAL_REFUSED: RefusalSpec(
        "The engine's rules refused this proposal (a hard ban, a size cap or an inbox limit); "
        "nothing was added to the inbox.",
        "Read the reason. Change the proposal if it was malformed; if it breaks a rule (for "
        "example demoting a declared control) leave it to the person.",
    ),
    Code.HUMAN_ONLY: RefusalSpec(
        "Only a person can do this (decide as a human, accept or reject proposals, confirm a "
        "stage, rebind a session's files).",
        "Tell the person what you suggest; they do it in qPilot Studio or the app.",
    ),
    Code.RESULTS_HIDDEN: RefusalSpec(
        "Results stay hidden until a person confirms the design and the curves in qPilot Studio.",
        "Propose the design (qpcr_propose) and check it (qpcr_check_design); ask the person to "
        "confirm the stages in qPilot Studio, then call again.",
        retry_later=True,
    ),
    Code.PATH_NOT_ALLOWED: RefusalSpec(
        "The path does not exist or lies outside the folders this server shares "
        "(QPILOT_DATA_ROOTS).",
        "Use a file inside a shared folder, or ask the person to add its folder to "
        "QPILOT_DATA_ROOTS and restart the server.",
    ),
    Code.UNSUPPORTED_INPUT: RefusalSpec(
        "The path is not the kind of file this argument takes.",
        "Pass an RDML file (.rdml or .xml) as rdml_path, an .xlsx or .csv file as sheet_path, "
        "or a folder where a folder is asked for.",
    ),
    Code.INPUT_UNREADABLE: RefusalSpec(
        "qPilot could not read or analyse this file.",
        "Check that it is the instrument's export of raw curves; ask the person to open it in "
        "qPilot Studio, which shows what the file declares.",
    ),
    Code.UNKNOWN_STUDY: RefusalSpec(
        "No study or Studio session has this id in this server's study store.",
        "Call qpcr_study (an analysed study) or qpcr_inspect (a lab's own file) first and use "
        "the id it returns.",
    ),
    Code.UNKNOWN_ITEM: RefusalSpec(
        "The study has no item with this name (gene, card, option, proposal, table or fact).",
        "Use a name exactly as the study lists it (qpcr_study lists genes and cards with their "
        "options).",
    ),
    Code.INVALID_ARGUMENT: RefusalSpec(
        "An argument is missing, of the wrong type or outside its allowed values.",
        "Read the error, which names the field, and correct that argument.",
    ),
    Code.IDEMPOTENCY_KEY_REUSED: RefusalSpec(
        "This idempotency_key was already used for a different request.",
        "Use a new key (a fresh UUID) for each distinct request; reuse a key only to retry "
        "the very same request.",
    ),
    Code.INTEGRITY_FAILED: RefusalSpec(
        "A record qPilot would read does not verify (a hash chain, an audit or a reproduction "
        "check failed), so qPilot will not use it.",
        "Tell the person; they can run qpilot verify. Do not work around it.",
    ),
    Code.NOT_INSTALLED: RefusalSpec(
        "A part of qPilot this tool needs is not installed in this build.",
        "Tell the person which part is missing; they install it.",
    ),
    Code.NOT_READY: RefusalSpec(
        "What this tool reads does not exist yet for this study.",
        "Ask the person to run the step that writes it, then call again.",
        retry_later=True,
    ),
    Code.NOT_APPLICABLE: RefusalSpec(
        "This analysis does not apply to this study's design.",
        "Use the tools that fit the design; do not substitute your own calculation.",
    ),
    Code.ENGINE_REFUSED: RefusalSpec(
        "The engine could not compute this for this input.",
        "Report the study id and the error to the person; do not compute it yourself.",
    ),
}

#: ``status`` values of a reply that did nothing as asked (MCP ``isError: true``).
ERROR_STATUSES = ("stale", "refused")


def refuse(code: Code, error: str, **details: Any) -> dict[str, Any]:
    """A refusal reply: the one-line ``error`` (kept for older callers), ``code`` and ``fix``."""
    return {"error": str(error), "code": code.value, "fix": REFUSALS[code].fix, **details}


def mark(out: dict[str, Any], code: Code) -> dict[str, Any]:
    """``out`` with ``code`` and ``fix`` added; an outcome that did nothing also gets ``error``.

    ``error`` is the outcome's own ``reason`` (or the code's meaning), so every reply MCP marks
    ``isError`` carries the same three fields as :func:`refuse`.
    """
    marked = {**out, "code": code.value, "fix": REFUSALS[code].fix}
    if out.get("status") in ERROR_STATUSES and "error" not in out:
        marked["error"] = str(out.get("reason") or REFUSALS[code].meaning)
    return marked


def is_error(out: Any) -> bool:
    """Whether a reply is a refusal: it has ``error``, or a status that did nothing as asked."""
    return isinstance(out, dict) and ("error" in out or out.get("status") in ERROR_STATUSES)


def table() -> list[dict[str, Any]]:
    """Every code with its meaning, fix and retry hint (docs, SKILL.md and tests read this)."""
    return [
        {"code": c.value, "meaning": s.meaning, "fix": s.fix, "retry_later": s.retry_later}
        for c, s in REFUSALS.items()
    ]


__all__ = [
    "ERROR_STATUSES",
    "REFUSALS",
    "Code",
    "RefusalSpec",
    "is_error",
    "mark",
    "refuse",
    "table",
]
