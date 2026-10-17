"""qPilot's door for AI agents: six tools over MCP (stdio), backed by the on-disk study store.

Run with ``python -m qpilot.mcp_server`` (or ``qpilot serve``); add it to Claude Code with
``claude mcp add qpilot -- python -m qpilot.mcp_server``. The server is a separate process from
the app, so both read and write the same workspace through ``qpilot.core.store``.

Rules enforced here, in code:

- **Path policy.** ``qpcr_study`` only opens files whose resolved real path lies inside one of
  ``QPILOT_DATA_ROOTS`` (``os.pathsep``-separated; default: the qPilot cache and the current
  directory). Symlinks are resolved first; there is no string-prefix comparison.
- **An MCP caller is an agent.** ``qpcr_decide`` records every request as ``actor="agent"``.
  A choice that can flip a conclusion comes back ``pending_human``; only a person in the app can
  make it.
- **Agents propose; only a person accepts.** ``qpcr_propose`` adds a proposal to the Studio
  inbox as ``actor="agent"`` with ``made_by.kind="agent"``; the engine's own check replaces
  anything the agent could claim, and no tool can accept, edit or reject a proposal
  (``core/proposals.py`` refuses every actor but ``human``).
- **JSON only.** Tools return engine numbers, never prose written by a model.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from qpilot.core.decisions import DecisionError, apply_decision, check_request, needs_human
from qpilot.core.proposals import STATUSES, ProposalError
from qpilot.core.store import SUGGEST_REASON, StudyNotFound, StudyStore
from qpilot.qpcr.plan import plan
from qpilot.schemas import DecisionCard
from qpilot.schemas_studio import PROPOSAL_KINDS, MadeBy, Proposal

SERVER_NAME = "qpilot"
INSTRUCTIONS = (
    "qPilot analyses qPCR studies from RDML files with a deterministic engine (LinRegPCR, "
    "geNorm, Welch contrasts, a grid of every reasonable analysis). Call qpcr_study first, "
    "then qpcr_robustness for a gene. qpcr_decide records your request as an agent: a choice "
    "that can change any conclusion returns pending_human and waits for a person. "
    "You may propose; only a person in qPilot Studio accepts. Report only "
    "numbers these tools return. Research use only; not for clinical or diagnostic use."
)
UNKNOWN_STUDY = "unknown study_id; call qpcr_study first"
RDML_SUFFIXES = {".rdml", ".xml"}
KIND_TO_DIMENSION = {
    "reference_set": "refs",
    "group_cutoff": "cut",
    "undetermined": "undetermined",
    "amp_call": "amp_call",
}


def data_roots() -> list[Path]:
    """Directories an agent may read input files from."""
    env = os.environ.get("QPILOT_DATA_ROOTS")
    if env:
        roots = [Path(p).expanduser() for p in env.split(os.pathsep) if p.strip()]
    else:
        roots = [Path.home() / ".cache" / "qpilot", Path.cwd()]
    return [r.resolve() for r in roots if r.exists()]


def check_path(rdml_path: str) -> Path:
    """Resolve ``rdml_path`` and require it to be an RDML file inside a data root."""
    try:
        path = Path(rdml_path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as err:
        raise PermissionError("file not found") from err
    if not any(path.is_relative_to(root) for root in data_roots()):
        raise PermissionError("path outside QPILOT_DATA_ROOTS")
    if not path.is_file() or path.suffix.lower() not in RDML_SUFFIXES:
        raise PermissionError("not an .rdml file")
    return path


def _card_view(card: DecisionCard) -> dict[str, Any]:
    return {
        "card_id": card.id,
        "kind": card.kind,
        "rank": card.rank,
        "status": card.status,
        "needs_human": needs_human(card),
        "recommended": card.recommended,
        "decision": card.decision,
        "decided_by": card.decided_by,
        "impact": card.impact,
        "options": [
            {
                "id": o.id,
                "label": o.label,
                "per_gene": {
                    g: {"fc": r.fc, "ci": list(r.ci), "p": r.p, "conclusion": r.conclusion}
                    for g, r in o.per_gene.items()
                },
            }
            for o in card.options
        ],
    }


class QpilotTools:
    """The tools as plain methods (easy to test), registered on the MCP server below.

    ``agent_policy=True`` (the MCP server) applies the study's autonomy setting: in ``suggest``
    (the default) every agent decision becomes a request for a person. The in-app model passes
    ``False`` because the app applies its own Autonomy toggle.
    """

    def __init__(self, store: StudyStore | None = None, agent_policy: bool = True) -> None:
        self._store = store
        self.agent_policy = agent_policy

    @property
    def store(self) -> StudyStore:
        """The study store (created on first use, from ``QPILOT_STUDIES_DIR``)."""
        if self._store is None:
            self._store = StudyStore()
        return self._store

    def qpcr_study(self, rdml_path: str, design: dict | None = None) -> dict[str, Any]:
        """Analyse (or reopen) the qPCR study in an RDML file.

        Returns the study id, the root hash of its decision record, plate and sample counts,
        reference-gene stability, every gene's fold change and conclusion, and the Decision
        Cards. ``design`` is reserved; the demo design (MYCN-high, top 15 %) is used.
        """
        if design:
            return {"error": "custom designs are not supported yet; omit 'design'"}
        try:
            path = check_path(rdml_path)
        except PermissionError as err:
            return {"error": str(err)}
        try:
            study_id = self.store.ensure_study(path)
        except ImportError:
            return {"error": "the qPCR engine is not installed in this build"}
        except Exception as err:  # loader or engine refused the file: answer, never raise
            from qpilot.io.rdml_io import RdmlLoadError

            if isinstance(err, RdmlLoadError):
                return {"error": f"could not read this RDML file: {err}"}
            return {
                "error": "could not analyse this file: it does not fit the demo study design "
                f"({type(err).__name__})"
            }
        result = self.store.get(study_id)
        cards = self.store.cards(study_id)
        fact_ids = sorted({f for c in cards for f in c.facts})
        return {
            "study_id": study_id,
            "record_root_hash": result.input_sha256,
            "chain_head": self.store.chain_head(study_id),
            "agent_autonomy": self.store.autonomy(study_id),
            "n_plates": result.n_plates,
            "n_reactions": result.n_reactions,
            "n_samples": result.n_samples,
            "design": result.design.model_dump(mode="json"),
            "genorm": result.genorm.model_dump(mode="json"),
            "conclusion_rule": result.conclusion_rule,
            # under the recommended choices; decisions made on cards do not change these numbers
            "contrasts_are_for": "the recommended choices",
            "contrasts": {
                g: {
                    "fc": c.fc,
                    "ci": list(c.ci),
                    "p": c.p,
                    "conclusion": c.conclusion,
                    "holds": result.robustness[g].holds if g in result.robustness else None,
                }
                for g, c in result.contrasts.items()
            },
            "open_cards": [_card_view(c) for c in cards if c.status in ("open", "pending_human")],
            "decided_cards": [
                _card_view(c) for c in cards if c.status in ("decided", "auto_decided")
            ],
            "facts": {
                f: result.facts[f].model_dump(mode="json") for f in fact_ids if f in result.facts
            },
        }

    def qpcr_robustness(self, study_id: str, gene: str) -> dict[str, Any]:
        """How robust one gene's conclusion is across every reasonable analysis.

        Returns the conclusion and fold change under the recommended choices, the share of the
        grid that agrees (``holds_fraction``), which single choices could flip it, its
        confidence level with named reasons, and the open cards that can change it.
        """
        try:
            result = self.store.get(study_id)
        except StudyNotFound:
            return {"error": "unknown study_id; call qpcr_study first"}
        name = next((g for g in result.contrasts if g.lower() == gene.strip().lower()), None)
        if name is None:
            return {"error": "gene not in this study", "n_genes": len(result.contrasts)}
        contrast = result.contrasts[name]
        robust = result.robustness.get(name)
        grade = result.confidence.get(name)
        cards = self.store.cards(study_id)
        flipping = []
        if robust is not None:
            for card in cards:
                dim = KIND_TO_DIMENSION.get(card.kind)
                if dim in robust.impact and robust.impact[dim]["flips"]:
                    flipping.append(card.id)
        return {
            "study_id": study_id,
            "gene": name,
            "conclusion": contrast.conclusion,
            "fc": contrast.fc,
            "ci": list(contrast.ci),
            "p": contrast.p,
            "holds_fraction": robust.holds if robust else None,
            "n_cells": robust.n_cells if robust else None,
            "impact_by_dimension": robust.impact if robust else {},
            "confidence": grade.model_dump(mode="json", exclude={"checks"}) if grade else None,
            "cards_that_can_flip_it": flipping,
            "open_cards": [c.id for c in cards if c.status in ("open", "pending_human")],
        }

    def qpcr_decide(
        self,
        study_id: str,
        card_id: str,
        option: str,
        reason: str,
        actor: str = "agent",
        expected_head: str | None = None,
    ) -> dict[str, Any]:
        """Ask to decide a Decision Card, as an agent, with a reason.

        Returns ``applied`` for a choice that cannot change any conclusion, ``pending_human``
        for one that can (a person decides it in the qPilot app), or ``stale`` when
        ``expected_head`` (the ``chain_head`` you last read) is out of date. ``actor`` must be
        ``agent``: an MCP caller is always recorded as an agent.
        """
        if actor != "agent":
            return {
                "error": "over MCP the actor is always 'agent'; people decide in the qPilot app"
            }
        try:
            if self.agent_policy and self.store.autonomy(study_id) != "decide_and_tell":
                card = self.store.card(study_id, card_id)
                cleaned = check_request(card, option, reason)
                outcome = self.store.request_human(
                    study_id, card_id, option, cleaned, "agent", expected_head
                )
                if outcome.status == "pending_human" and not needs_human(card):
                    outcome = outcome.model_copy(update={"reason": SUGGEST_REASON})
            else:
                outcome = apply_decision(
                    self.store, study_id, card_id, option, reason, "agent", expected_head
                )
        except StudyNotFound:
            return {"error": "unknown study_id; call qpcr_study first"}
        except (DecisionError, KeyError) as err:
            # KeyError's str() adds quotes; take its argument so the id reads back exactly
            text = err.args[0] if isinstance(err, KeyError) and err.args else str(err)
            return {"error": str(text)}
        return {
            "status": outcome.status,
            "chain_head": outcome.chain_head,
            "reason": outcome.reason,
            "card": _card_view(outcome.card) if outcome.card else None,
        }

    def qpcr_plan(
        self,
        fc: float = 2.0,
        sd_log2: float | None = None,
        n_per_group: int | None = None,
        alpha: float = 0.05,
        power: float = 0.80,
        n_plates: int | None = None,
        calibrator_on_every_plate: bool | None = None,
        n_candidate_refs: int | None = None,
    ) -> dict[str, Any]:
        """Before the first plate: samples per group needed and what a design cannot detect.

        ``sd_log2`` is the SD of log2 normalised expression between biological replicates (not
        technical Cq SD). Without it you get a message instead of a sample size.
        """
        try:
            out = plan(
                fc=fc,
                sd_log2=sd_log2,
                n_per_group=n_per_group,
                alpha=alpha,
                power=power,
                n_plates=n_plates,
                calibrator_on_every_plate=calibrator_on_every_plate,
                n_candidate_refs=n_candidate_refs,
            )
        except (ValueError, TypeError, ArithmeticError) as err:
            return {"error": str(err)}
        result = out.model_dump(mode="json")
        if out.n_needed is not None:
            # qPilot's own rule (p < 0.05 and at least 2-fold), simulated: what a design calls.
            from qpilot.qpcr.plan import simulate_calls

            sims = {"needed": simulate_calls(fc, sd_log2, out.n_needed, alpha)}
            if n_per_group:
                sims["planned"] = simulate_calls(fc, sd_log2, n_per_group, alpha)
            result["simulated"] = {
                f"{k}_{what}": round(v, 4)
                for k, (sig, called) in sims.items()
                for what, v in (("significant", sig), ("called", called))
            }
        return result

    def qpcr_propose(
        self,
        study_id: str,
        kind: str,
        subject: str,
        payload: dict[str, Any],
        evidence: list[dict[str, Any]] | None = None,
        alternatives: list[dict[str, Any]] | None = None,
        level: str = "Low",
        reasons: list[str] | None = None,
    ) -> dict[str, Any]:
        """Propose one item for a person to accept or reject in qPilot Studio; nothing applies.

        ``kind`` is a Studio proposal kind (``design.well_role``, ``design.group``,
        ``curve.call_rule``, ...); ``subject`` and ``payload`` follow that kind's shape.
        ``evidence`` items are ``{"kind", "ref", "note"}``. The proposal is recorded as made by
        an agent, the engine's refute-only check is attached, and the answer is ``proposed``
        (with the check) or ``refused`` (with the reason). Only a person accepts; no tool can.
        """
        if kind not in PROPOSAL_KINDS:
            return {"error": f"unknown kind; use one of {', '.join(PROPOSAL_KINDS)}"}
        try:
            inbox = self.store.proposals(study_id)
        except StudyNotFound:
            return {"error": UNKNOWN_STUDY}
        try:
            proposal = Proposal.model_validate(
                {
                    "study_id": inbox.study_id,
                    "kind": kind,
                    "subject": subject,
                    "payload": payload,
                    "evidence": evidence or [],
                    "alternatives": alternatives or [],
                    "level": level,
                    "reasons": reasons or [],
                    "made_by": MadeBy(kind="agent"),
                }
            )
        except ValidationError as err:
            return {"error": _invalid(err)}
        try:
            outcome = inbox.propose(proposal, "agent")
        except ProposalError as err:
            return {"error": str(err)}
        if outcome.status not in ("proposed", "refused"):  # nothing else can happen over MCP
            return {"error": "unexpected outcome"}
        return {
            "status": outcome.status,
            "head": outcome.head,
            "reason": outcome.reason,
            "proposal": _proposal_view(outcome.proposal) if outcome.proposal else None,
        }

    def qpcr_proposals(self, study_id: str, status: str | None = None) -> dict[str, Any]:
        """The Studio inbox: every proposal with its status, the engine's check and evidence.

        ``status`` filters by ``proposed``, ``accepted``, ``edited``, ``rejected`` or
        ``superseded``. Read-only; ``head`` is the inbox's chain head.
        """
        if status is not None and status not in STATUSES:
            return {"error": f"status must be one of {', '.join(STATUSES)}"}
        try:
            inbox = self.store.proposals(study_id)
            head, items = inbox.snapshot()
        except StudyNotFound:
            return {"error": UNKNOWN_STUDY}
        except ProposalError as err:
            return {"error": str(err)}
        return {
            "study_id": inbox.study_id,
            "head": head,
            "proposals": [_proposal_view(p) for p in items if status in (None, p.status)],
        }


def _proposal_view(proposal: Proposal) -> dict[str, Any]:
    return proposal.model_dump(mode="json", exclude_none=True)


def _invalid(err: ValidationError) -> str:
    """A short validation message that names fields, never echoes the submitted values."""
    parts = []
    for item in err.errors()[:3]:
        where = ".".join(str(x) for x in item.get("loc", ())) or "proposal"
        parts.append(f"{where}: {item.get('msg', 'invalid')}")
    return "invalid proposal (" + "; ".join(parts) + ")"


TOOL_NAMES = (
    "qpcr_study",
    "qpcr_robustness",
    "qpcr_decide",
    "qpcr_plan",
    "qpcr_propose",
    "qpcr_proposals",
)


def _server_class() -> Callable[..., Any]:
    try:  # mcp >= 2
        from mcp.server.mcpserver import MCPServer

        return MCPServer
    except ImportError:  # mcp 1.x
        from mcp.server.fastmcp import FastMCP

        return FastMCP


def create_server(store: StudyStore | None = None) -> Any:
    """Build the MCP server with every tool in ``TOOL_NAMES`` registered."""
    tools = QpilotTools(store)
    server = _server_class()(SERVER_NAME, instructions=INSTRUCTIONS)
    for name in TOOL_NAMES:
        server.tool(name=name)(getattr(tools, name))
    return server


def main() -> None:
    """Serve over stdio."""
    create_server().run("stdio")


if __name__ == "__main__":
    main()
