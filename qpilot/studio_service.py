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
choices     the Decision Cards (reference set, cut-off, empty wells, amplification call)
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
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from filelock import FileLock

from qpilot.core.store import StudyNotFound, StudyStore, atomic_write, canonical_json, dump_json
from qpilot.schemas import Actor
from qpilot.schemas_studio import (
    TEXT_ID,
    DesignField,
    Evidence,
    InspectSummary,
    MadeBy,
    MarkerSplit,
    Proposal,
    ProposalCheck,
    ProposalOutcome,
    QuarantineEntry,
    StudyDesign,
)

STAGES: tuple[str, ...] = ("design", "curves", "choices", "prism", "roundtrip")
BLIND_STAGES: tuple[str, ...] = ("design", "curves")
STAGE_KINDS = {
    "design": "design.",
    "curves": "curve.",
    "choices": "",  # the Decision Cards, not proposals
    "prism": "prism.project",
    "roundtrip": ("prism.exclusion_reason", "prism.value_edit"),
}
STUDIO_FILE = "studio.json"
AI_CALLS_FILE = "ai_calls.jsonl"
CURVE_JUDGE_FILE = "curve_judge_calls.json"
MAX_WELL_PROPOSALS = 400
PRISM_WAIT_S = 120.0
BLANK_DESIGN_ID = "studio_blank"


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

    # ---- the model ------------------------------------------------------------------------

    @property
    def client(self) -> Any:
        """The model client (Studio's local default, created on first use)."""
        if self._client is None:
            from qpilot.ai.client import ModelClient

            try:
                from qpilot.ai.config import studio_config
            except ImportError:  # an AI layer without the Studio default: environment only
                self._client = ModelClient.from_env()
            else:
                self._client = ModelClient(config=studio_config())
        return self._client

    def model_status(self) -> dict[str, Any]:
        """Which model Studio uses and whether anything leaves this machine."""
        from qpilot.core.pseudonym import endpoint_is_local

        backend = self.client.backend
        endpoint = getattr(backend, "url", None) or getattr(
            getattr(backend, "config", None), "endpoint", None
        )
        provider = self.client.provider
        local = provider in ("none", "mock") or endpoint_is_local(provider, endpoint)
        return {
            "provider": provider,
            "model": self.client.model,
            "available": self.client.available,
            "local": local,
            "sample_names": "sent as quoted data"
            if local
            else "replaced by pseudonyms before anything leaves this machine",
        }

    # ---- the session ------------------------------------------------------------------------

    def open(self, rdml_path: str | Path, sheet_path: str | Path | None = None) -> str:
        """Open the Studio session of an input file (and optional sample sheet); return its id.

        The file is inspected once (every name quarantined); nothing is analysed and nothing is
        proposed yet.
        """
        from qpilot.core.store import sha256_file
        from qpilot.qpcr.inspect import file_facts

        session_id = self.store.open_session(rdml_path)
        facts = file_facts(rdml_path, sheet_path)
        entries = [(e.value, e.origin) for e in facts.quarantine]
        self.store.quarantine(session_id).add_many(entries)
        sheet = None
        if sheet_path is not None:
            sheet = {"path": str(Path(sheet_path).resolve()), "sha256": sha256_file(sheet_path)}
        self._update_meta(session_id, {"sheet": sheet})
        return session_id

    def _folder(self, session_id: str) -> Path:
        return self.store.find_session(session_id)

    def _meta(self, session_id: str) -> dict[str, Any]:
        path = self._folder(session_id) / STUDIO_FILE
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _update_meta(self, session_id: str, update: dict[str, Any]) -> None:
        folder = self._folder(session_id)
        with FileLock(str(folder / ".lock"), timeout=30):
            meta = self._meta(session_id)
            meta.update(update)
            atomic_write(folder / STUDIO_FILE, dump_json(meta))

    def source(self, session_id: str) -> Path:
        """The session's input file; ``StudioError`` when it is missing or has changed."""
        path = self.store.session_source(session_id)
        if path is None:
            raise StudioError("the input file is missing or has changed since it was opened")
        return path

    def sheet(self, session_id: str) -> Path | None:
        """The session's sample sheet, when it has one and it is unchanged."""
        from qpilot.core.store import sha256_file

        sheet = self._meta(session_id).get("sheet")
        if not sheet:
            return None
        path = Path(sheet["path"])
        if not path.exists() or sha256_file(path) != sheet["sha256"]:
            raise StudioError("the sample sheet is missing or has changed since it was opened")
        return path

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
                with open(folder / AI_CALLS_FILE, "a", encoding="utf-8") as fh:
                    fh.write(lines)

    # ---- stage 1: the design ----------------------------------------------------------------

    def propose_design(self, session_id: str, sentence: str = "") -> dict[str, Any]:
        """The Design Interpreter: rules always, the model when one answers; all as proposals.

        ``sentence`` (the scientist's one line about the experiment) is quarantined like any
        file text and reaches the model only as quoted data.
        """
        from qpilot.qpcr.design_rules import propose_from_names

        facts = self.facts(session_id)
        quarantine = self.store.quarantine(session_id)
        if sentence.strip():
            quarantine.add(sentence.strip(), "studio:sentence")
        entries = quarantine.all()
        rule_fields = propose_from_names(facts.summary, entries, facts=facts)
        rule_fields = [*_preset_fields(facts.summary), *rule_fields]
        notes: list[str] = []
        makers: list[MadeBy] = [MadeBy(kind="rule")] * len(rule_fields)
        fields: list[DesignField] = list(rule_fields)
        rejected: list[dict[str, Any]] = []
        fallback = True
        try:
            from qpilot.ai.interpret import interpret
        except ImportError:
            notes.append("the Design Interpreter is not installed; rules only")
        else:
            pseudonymiser = None
            if not self.model_status()["local"]:
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
            notes += list(getattr(result, "notes", []))
            rejected = list(getattr(result, "rejected", []))
            fallback = bool(getattr(result, "fallback", True))
            self._log_calls(session_id, "studio.interpret", getattr(result, "meta", []))
        outcomes = [
            self._propose(session_id, f, maker) for f, maker in zip(fields, makers, strict=True)
        ]
        return _report(outcomes, notes=notes, rejected=rejected, fallback=fallback)

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

    def assemble(self, session_id: str) -> Assembly:
        """The design the session's accepted proposals describe, or what still blocks it.

        Starts from the demo preset when a person accepted it, else from a blank design that
        must gain a comparison; Studio's default amplification rules are the options of the
        ``amp_call`` axis. Only accepted proposals are read.
        """
        from qpilot.qpcr.amp_call import STUDIO_AMP_CALLS
        from qpilot.qpcr.designs import DesignError, design_from_proposals

        accepted = self.store.proposals(session_id).accepted()
        blockers: list[str] = []
        design_part = [p for p in accepted if p.kind.startswith("design.")]
        if not any(p.kind in ("design.preset", "design.comparison") for p in design_part):
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
            if not design.reference_candidates:
                blockers.append("no reference genes yet: accept at least one target as a reference")
            design_hash = design.design_hash()
            curve_part = [p for p in accepted if p.kind.startswith("curve.")]
            full = design_from_proposals(design, curve_part, curves)
            prism_part = [p for p in accepted if p.kind == "prism.exclusion_reason"]
            full = design_from_proposals(full, prism_part, curves)
        except DesignError as err:
            return Assembly(None, [*blockers, str(err)])
        if blockers:
            return Assembly(None, blockers, design_hash)
        curves_hash = full.model_copy(update={"excluded_wells": ()}).design_hash()
        return Assembly(full, [], design_hash, curves_hash)

    def _curves_table(self, session_id: str) -> Any:
        """Every well of every experiment (for mapping gene/sample exclusions to wells)."""
        return self.facts(session_id).wells

    # ---- stage confirmation -------------------------------------------------------------------

    def stages(self, session_id: str) -> list[StageStatus]:
        """Every stage's status, in the fixed order; a stage opens when the one before closes."""
        accepted = self.store.proposals(session_id).accepted()
        pending = self.inbox(session_id, status="proposed")
        assembly = self.assemble(session_id)
        out: list[StageStatus] = []
        previous = True
        for stage in STAGES:
            confirmed = previous and _confirmed(accepted, stage, assembly, self, session_id)
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

    def results_visible(self, session_id: str) -> bool:
        """True once the blind stages (design, curves) are both confirmed by a person."""
        status = {s.stage: s for s in self.stages(session_id)}
        return all(status[stage].confirmed for stage in BLIND_STAGES)

    def propose_confirm(self, session_id: str, stage: str) -> ProposalOutcome:
        """The system proposes closing a stage; a person accepts it (the confirm click).

        Refused while the stage has pending proposals or (design) the design cannot run. The
        payload names the design hash it confirms and every accepted proposal it covers.
        """
        if stage not in ("design", "curves", "choices"):
            raise StudioError(f"no confirm step for stage {stage!r}")
        status = {s.stage: s for s in self.stages(session_id)}[stage]
        if not status.open:
            raise StudioError(f"the {stage} stage is not open yet")
        if status.pending:
            raise StudioError(f"the {stage} stage still has proposals waiting for a decision")
        assembly = self.assemble(session_id)
        if assembly.design is None:
            raise StudioError("the design cannot be confirmed yet: " + "; ".join(assembly.blockers))
        accepted = self.store.proposals(session_id).accepted()
        covers = [p.id for p in accepted if _in_stage(p, stage)]
        payload: dict[str, Any] = {
            "stage": stage,
            "design_hash": assembly.design_hash if stage == "design" else assembly.curves_hash,
            "covers": covers,
        }
        if stage == "choices":
            study_id = self.study(session_id)
            undecided = [
                c.id for c in self.store.cards(study_id) if c.status in ("open", "pending_human")
            ]
            if undecided:
                raise StudioError(
                    "decide every analysis choice first (still open: " + ", ".join(undecided) + ")"
                )
            payload["study_id"] = study_id
            payload["chain_head"] = self.store.chain_head(study_id)
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
        """A person accepts one proposal (a reason is needed when the check contradicts it)."""
        return self.store.proposals(session_id).accept(proposal_id, actor, reason, expected_head)

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
        and a contradicted edit needs a reason like a contradicted proposal.
        """
        _require_human(actor, "edit a proposal")
        inbox = self.store.proposals(session_id)
        original = inbox.get(proposal_id)
        recheck = self.check(session_id, original.model_copy(update={"edits": edits}))
        if recheck.status == "contradicted" and not reason.strip():
            return ProposalOutcome(
                status="refused",
                head=inbox.head(),
                proposal=original,
                reason="the engine check contradicts this edit; give a reason to accept it anyway",
            )
        return inbox.edit_and_accept(proposal_id, actor, edits, reason, expected_head)

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
            if p.check.status == "consistent" and p.kind != "stage.confirm"
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
        groups = sorted(
            {str(p.effective_payload().get("group")) for p in accepted if p.kind == "design.group"}
        )
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
        """
        if not proposal.alternatives or not proposal.kind.startswith("design."):
            return None
        assembly = self.assemble(session_id)
        if assembly.design is None:
            return None
        from qpilot.qpcr.designs import DesignError, design_from_proposals

        curves = self._curves_table(session_id)
        readings = []
        for payload in (proposal.payload, proposal.alternatives[0]):
            reading = proposal.model_copy(update={"payload": payload, "status": "accepted"})
            try:
                readings.append(design_from_proposals(assembly.design, [reading], curves))
            except DesignError:
                return None
        conclusions = [self._primary_conclusions(session_id, d) for d in readings]
        if None in conclusions:
            return None
        return conclusions[0] != conclusions[1]

    def _primary_conclusions(self, session_id: str, design: StudyDesign) -> dict[str, str] | None:
        """Each gene's conclusion at the primary choices (internal only: blind stages)."""
        from qpilot.qpcr.curves import CurveAnalysisError, analyse_study
        from qpilot.qpcr.designs import DesignError
        from qpilot.qpcr.study import StudySettings, build_model

        single = design.model_copy(update={"amp_calls": design.amp_calls[:1]})
        settings = StudySettings.from_design(single)
        try:
            curves = analyse_study(
                self.source(session_id),
                settings.experiment_id,
                settings.candidates,
                settings.curves,
            )
            model = build_model(curves, settings)
        except (DesignError, CurveAnalysisError, ValueError):
            return None
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
        from qpilot.qpcr import curve_judge
        from qpilot.qpcr.amp_call import amplified
        from qpilot.qpcr.curves import analyse_study
        from qpilot.qpcr.designs import design_curves
        from qpilot.qpcr.study import StudySettings

        status = {s.stage: s for s in self.stages(session_id)}
        if not status["design"].confirmed:
            raise StudioError("confirm the design first: the curves stage follows it")
        design = self.assemble(session_id).design
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
        learned: dict[str, bool] = {}
        if curve_judge.validated():
            learned = self._learned_calls(session_id, path, settings.experiment_id)
            disagree = [
                k
                for k, ours in zip(keys, linreg, strict=True)
                if k in learned and learned[k] != bool(ours) and k not in design.well_calls
            ]
        else:
            notes.append("the Curve Judge is " + curve_judge.status() + "; LinRegPCR alone")
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
            matters = baseline is not None and changed is not None and changed != baseline
            if not matters:
                continue
            mattering += 1
            for key in wells[: max(0, MAX_WELL_PROPOSALS - len(outcomes))]:
                outcomes.append(self._propose_well_call(session_id, key, learned[key], target))
        notes.append(
            "Curve Judge disagreements that could change a conclusion are listed one well each; "
            "the others change no conclusion and are not listed"
        )
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

    def _learned_calls(self, session_id: str, path: Path, experiment_id: str | None) -> dict:
        """The Curve Judge's call per ``run_id/well``, cached in the session by model."""
        from qpilot.qpcr import curve_judge

        cache = self._folder(session_id) / CURVE_JUDGE_FILE
        key = f"{curve_judge.MODEL_SHA256}:{experiment_id}"
        if cache.exists():
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("key") == key:
                return {k: bool(v) for k, v in data["calls"].items()}
        calls = curve_judge.predict_calls(path, experiment_id)
        out = {str(k): bool(v) for k, v in calls.items()}
        atomic_write(cache, dump_json({"key": key, "calls": out}))
        return out

    def curve_calls(self, session_id: str, gene: str) -> dict[str, Any]:
        """Each well of one target called under every rule (and the Curve Judge when validated).

        Facts about the curves, never a conclusion, so they are available in the blind curve
        stage. Uses the assembled design's experiment and well roles when there is one.
        """
        from qpilot.qpcr import curve_judge
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
        if curve_judge.validated():
            experiment = design.experiment_id if design is not None else None
            learned = self._learned_calls(session_id, path, experiment)
            calls = [
                c.model_copy(update={"calls": {**c.calls, "learned": learned[k]}})
                if (k := f"{c.run_id}/{c.well}") in learned
                else c
                for c in calls
            ]
        return {
            "gene": gene,
            "rules": [*STUDIO_AMP_CALLS, *(["learned"] if curve_judge.validated() else [])],
            "curve_judge": curve_judge.status(),
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
        """The analysed study of the confirmed design (analysed on first use); blind-gated."""
        if not self.results_visible(session_id):
            raise StudioError("confirm the design and the curves first: results stay hidden")
        design = self.assemble(session_id).design
        assert design is not None
        study_id = self.store.ensure_study(self.source(session_id), design=design)
        studies = dict(self._meta(session_id).get("studies", {}))
        if study_id not in studies:
            studies[study_id] = design.design_hash()
            self._update_meta(session_id, {"studies": studies, "current_study": study_id})
        elif self._meta(session_id).get("current_study") != study_id:
            self._update_meta(session_id, {"current_study": study_id})
        return study_id

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
        project = self._accepted_project(session_id, study_id)
        genes = project.get("genes") if project else None
        template = (project or {}).get("template_id") or "two_groups_log2"
        return preview(self.store, study_id, genes or None, template, rows=rows)

    def _accepted_project(self, session_id: str, study_id: str) -> dict[str, Any] | None:
        accepted = self.store.proposals(session_id).accepted("prism.project")
        for proposal in reversed(accepted):
            payload = proposal.effective_payload()
            if payload.get("study_id") == study_id:
                return payload
        return None

    def exports(self, session_id: str) -> list[dict[str, Any]]:
        """Every bundle sent to Prism from this session: study, folder, bundle sha256, time."""
        return list(self._meta(session_id).get("exports", []))

    def send_to_prism(
        self, session_id: str, out_dir: str | Path, actor: Actor, *, share: bool = False
    ) -> Any:
        """Write the bundle (CSVs, scripts, provenance) for the accepted Prism project.

        Only a person's click writes: ``actor`` must be ``human``, the choices stage must be
        confirmed and a ``prism.project`` for this study accepted.
        """
        from qpilot.prism import export_study

        _require_human(actor, "send a study to Prism")
        status = {s.stage: s for s in self.stages(session_id)}
        if not status["choices"].confirmed:
            raise StudioError("confirm the analysis choices first")
        study_id = self.study(session_id)
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
        exports = list(self._meta(session_id).get("exports", []))
        exports.append(
            {
                "study_id": study_id,
                "bundle_dir": str(Path(out_dir).resolve()),
                "bundle_sha256": result.bundle.bundle_sha256,
                "at": _now(),
            }
        )
        self._update_meta(session_id, {"exports": exports})
        return result

    def launch_prism(self, result: Any, actor: Actor, wait_s: float = PRISM_WAIT_S) -> dict:
        """Run the bundle's ``run.pzc`` in the scientist's Prism and wait for its done file.

        Never runs without a person's click (``actor == "human"``) and never when Prism is not
        installed: then the bundle stays where it is, to run on the Prism machine.
        """
        from qpilot.prism.script import DONE_FILE

        _require_human(actor, "launch Prism")
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
        """
        from qpilot.prism import diff_report

        exports = self._meta(session_id).get("exports", [])
        match = [e for e in exports if Path(e["bundle_dir"]) == Path(bundle_dir).resolve()]
        if not match:
            raise StudioError("this bundle was not sent to Prism from this session")
        study_id = match[-1]["study_id"]
        report = diff_report(
            self.store,
            study_id,
            bundle_dir,
            sent_back_dir,
            pseudonym=self.store.pseudonymiser(session_id).pseudonymise,
        )
        outcomes = []
        for raw in report.get("proposals", []):
            proposal = Proposal.model_validate(raw).model_copy(update={"study_id": session_id})
            outcomes.append(self.store.proposals(session_id).propose(proposal, "system"))
        report["inbox"] = _report(outcomes)
        return report


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _in_stage(proposal: Proposal, stage: str) -> bool:
    if proposal.kind == "stage.confirm":
        return proposal.subject == stage
    if stage == "design":
        return proposal.kind.startswith("design.")
    if stage == "curves":
        return proposal.kind.startswith("curve.")
    if stage == "prism":
        return proposal.kind == "prism.project"
    if stage == "roundtrip":
        return proposal.kind in ("prism.exclusion_reason", "prism.value_edit")
    return False


def _confirmed(
    accepted: list[Proposal], stage: str, assembly: Assembly, studio: Studio, session_id: str
) -> bool:
    """A stage is confirmed by an accepted ``stage.confirm`` that still describes it."""
    if assembly.design is None:
        return False
    current = studio.expected_study(session_id, assembly)
    if stage == "prism":  # done when the current analysis has been sent to Prism
        exports = studio._meta(session_id).get("exports", [])
        return any(e.get("study_id") == current for e in exports)
    confirms = [p for p in accepted if p.kind == "stage.confirm" and p.subject == stage]
    if not confirms:
        return False
    payload = confirms[-1].effective_payload()
    if stage == "design":
        return payload.get("design_hash") == assembly.design_hash
    if stage == "curves":
        return payload.get("design_hash") == assembly.curves_hash
    if stage == "choices":
        if payload.get("study_id") != current:
            return False
        try:
            return payload.get("chain_head") == studio.store.chain_head(current)
        except StudyNotFound:
            return False
    return False


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
        targets = sorted(t.target for t in summary.targets if t.target not in refs)
        if 0 < len(targets) <= 12:
            update["headline"] = tuple(targets)
    return design.model_copy(update=update) if update else design


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


def _mac_prism_installed() -> bool:
    return any(Path(p).exists() for p in ("/Applications/Prism 10.app", "/Applications/Prism.app"))


__all__ = ["BLIND_STAGES", "STAGES", "Assembly", "StageStatus", "Studio", "StudioError"]

_ = os  # imported for callers that patch the environment in tests
