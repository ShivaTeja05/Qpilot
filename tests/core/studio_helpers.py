"""Shared helpers for the Studio safety-core tests (proposals, firewall, pseudonyms)."""

import hashlib
import sys
import types

from qpilot.schemas_studio import (
    CONTROL_ROLES,
    Evidence,
    MadeBy,
    Proposal,
    ProposalCheck,
    StudyDesign,
)

SHA = hashlib.sha256(b"a studio test input").hexdigest()
SESSION_ID = SHA[:12]
DECLARED = {"NTC_1": "ntc", "NRT_2": "nrt", "S1": "unkn", "S2": "unkn"}


def proposal(
    study_id: str = SESSION_ID,
    kind: str = "design.group",
    subject: str = "S1",
    payload: dict | None = None,
    check: str = "consistent",
    **update,
) -> Proposal:
    """A proposal as an agent would send it (the store resets anything it must not trust)."""
    base = Proposal(
        study_id=study_id,
        kind=kind,
        subject=subject,
        payload=payload if payload is not None else {"group": "LPS"},
        evidence=[Evidence(kind="sample", ref=subject, note="named like the LPS samples")],
        check=ProposalCheck(status=check),
        made_by=MadeBy(kind="agent"),
    )
    return base.model_copy(update=update)


def toy_guard(candidate: Proposal, current: list[Proposal]) -> str | None:
    """The plan's hard ban, in miniature: a control declared in the file is never demoted."""
    declared = DECLARED.get(candidate.subject)
    if candidate.kind == "design.well_role" and declared in CONTROL_ROLES:
        if candidate.payload.get("role") not in CONTROL_ROLES:
            return f"{candidate.subject} is declared {declared} in the file; never demoted"
    return None


def fake_design_checks(monkeypatch, check_status="consistent", guard=toy_guard, calls=None):
    """Install a stand-in for ``qpilot.qpcr.design_checks`` (another agent builds the real one)."""
    module = types.ModuleType("qpilot.qpcr.design_checks")

    def check_proposal(candidate, store, study_id):
        if calls is not None:
            calls.append((candidate.kind, candidate.subject, study_id))
        return ProposalCheck(status=check_status, rule_ids=["D-TOY"], note="toy engine check")

    module.check_proposal = check_proposal
    module.hard_ban = guard
    monkeypatch.setitem(sys.modules, "qpilot.qpcr.design_checks", module)
    return module


def no_design_checks(monkeypatch):
    """Make the build look like one without ``qpilot.qpcr.design_checks``."""
    monkeypatch.setitem(sys.modules, "qpilot.qpcr.design_checks", None)


def groups_design(note: str = "") -> StudyDesign:
    """A confirmed two-group design (not the legacy default)."""
    from qpilot.schemas_studio import Comparison, SampleDesign

    return StudyDesign(
        design_id="lab_lps",
        mode="groups",
        comparison=Comparison(group_a="LPS", group_b="PBS"),
        samples={
            "S1": SampleDesign(sample="S1", group="LPS"),
            "S2": SampleDesign(sample="S2", group="PBS"),
        },
        note=note,
    )


def fake_designs(monkeypatch):
    """Stand-in for ``qpilot.qpcr.designs.study_key`` (the engine agent builds the real one)."""
    module = types.ModuleType("qpilot.qpcr.designs")

    def study_key(input_sha256, design):
        if design.design_id == "legacy_default":
            return input_sha256
        return hashlib.sha256((input_sha256 + design.design_hash()).encode()).hexdigest()

    module.study_key = study_key
    monkeypatch.setitem(sys.modules, "qpilot.qpcr.designs", module)
    return module
