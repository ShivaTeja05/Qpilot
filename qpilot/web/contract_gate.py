"""Response models of the Run Gate route: what each plate's controls say, and whether it matters.

Owned by the ``gate`` router (:mod:`qpilot.web.routers.gate`). The numbers are the engine's
(:mod:`qpilot.qpcr.gate_rules` evaluates the rule pack, :mod:`qpilot.core.gate` runs the
consequence test); this module shapes them for the page: every rule evaluation with its reason
as a :class:`~qpilot.web.contract.FactText` (every number a cited fact), every consequence with
what each option would change, and the ``gate.rule`` Decision Cards in the shape of the Results
cards (:class:`~qpilot.web.contract.CardView`). Rules label; nothing here is applied. Like
:mod:`qpilot.web.contract`, every string is text, never HTML. Keep changes additive and
regenerate the frontend's types (``npm run gen:api``) with them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from qpilot.web.contract import CardView, FactText, JobView

Verdict = Literal["pass", "warn", "fail", "not_applicable"]
ConsequenceClass = Literal["none", "magnitude", "flip", "unknown"]
Triage = Literal["ignore", "rescue", "human", "defer"]


class GateSource(BaseModel):
    """Where a rule's threshold comes from."""

    key: str
    citation: str
    url: str | None = None


class GateRuleInfo(BaseModel):
    """One rule of the pack, as a scientist reads it."""

    rule_id: str
    title: str
    statement: str = Field(description="What the rule checks, in words (from the pack).")
    sources: list[GateSource]
    informational: bool = Field(
        description="The rule offers nothing to leave out: its findings are logged, not tested."
    )


class GatePack(BaseModel):
    """The rule pack the gate used (a record names it by its hash)."""

    name: str
    version: str
    hash: str
    label: str = Field(description="The pack's banner: research use, not clinical rules.")
    rules: list[GateRuleInfo]


class GatePlate(BaseModel):
    """One plate: gated (its controls could be checked) or ungated, and its verdicts."""

    plate: str
    status: Literal["gated", "ungated"]
    counts: dict[str, int] = Field(description="Rule evaluations on this plate, per verdict.")
    worst: Verdict = Field(description="fail > warn > pass > not_applicable.")


class GateEvaluation(BaseModel):
    """One verdict of one rule on one plate, plate x target, sample or biological unit."""

    id: str = Field(description="A stable id of the evaluation (12 hex).")
    rule_id: str
    title: str
    level: Literal["plate", "target", "sample", "unit", "study"]
    plate: str | None = None
    target: str | None = None
    sample: str | None = None
    unit: str | None = Field(
        default=None, description="The biological unit (G-RT: its reverse-transcription replicates)"
    )
    verdict: Verdict
    outcome: str = Field(description="The evaluator's outcome before the pack's severity.")
    code: str = Field(description="Why a rule is not applicable (machine reason), else empty.")
    reason: FactText
    flagged: list[str] = Field(description="The wells the rule points at (`plate/well`).")
    consequence: str | None = Field(
        default=None, description="The id of its consequence test, when it has one."
    )


class GateOption(BaseModel):
    """What one option (leaving some wells out) would change."""

    id: str
    label: str
    excluded: list[str] = Field(description="The wells this option leaves out (`plate/well`).")
    consequence: ConsequenceClass
    n_flipped: int = Field(description="Calls that change at the analysis in use.")
    flipped: list[str]
    n_flipped_elsewhere: int = Field(
        description="Calls that change only at other settings of the analysis grid."
    )
    flipped_elsewhere: list[str]
    max_delta_log2fc: float = Field(description="The largest fold-change move (log2).")
    text: FactText = Field(description="What leaving the wells out changes, in words.")
    code: Literal["", "already_left_out", "not_study_samples", "cannot_rerun"] = Field(
        default="",
        description="Why the option was answered without a re-run: its wells are already left "
        "out of the analysis, are not study samples, or the analysis cannot run without them.",
    )
    left_out: list[str] = Field(
        default=[], description="Its wells that the analysis already leaves out (a decision)."
    )


class GateDecisionView(BaseModel):
    """What a person last chose on a Run Gate card (the session's record) and what is in use.

    ``option`` is the option the wells are in now (from the analysed design), ``None`` when
    they match no option (some left out another way). ``action`` is what the latest decision
    did; ``reason``, ``decided_at`` and ``decided_by`` are from the record.
    """

    option: str | None
    label: str
    action: Literal["left_out", "put_back", "kept"]
    left_out: list[str] = Field(description="The card's wells the analysis leaves out now.")
    reason: str
    decided_at: str
    decided_by: Literal["human"] = "human"


class GateRequestView(BaseModel):
    """An agent's request on a Run Gate card, waiting for a person (curve exclusions)."""

    option: str
    option_label: str
    wells: list[str] = Field(description="The wells it asks to leave out or put back.")
    left_out: bool = Field(description="True: it asks to leave them out; False: to put back.")
    reason: str
    agent: str | None = None
    at: str


class GateConsequence(BaseModel):
    """The consequence test of one warn/fail evaluation: every option, the class, the triage."""

    id: str = Field(description="The evaluation's id.")
    rule_id: str
    title: str
    plate: str | None = None
    target: str | None = None
    sample: str | None = None
    unit: str | None = None
    verdict: Verdict
    consequence: ConsequenceClass = Field(description="The worst class over the options.")
    triage: Triage
    triage_text: str = Field(description="What happens to the finding, in words.")
    rescue_option: str | None = None
    options: list[GateOption]
    card_id: str | None = Field(default=None, description="Its `gate.rule` Decision Card.")
    decision_id: str = Field(
        default="",
        description="The id to decide it by (`card_gate_<id>`), whether or not it is a card now.",
    )
    can_decide: bool = Field(
        default=False,
        description="A person can choose an option here: a Studio session's card, or wells a "
        "person left out through it (to put back).",
    )
    decision: GateDecisionView | None = None
    requests: list[GateRequestView] = []


class GateRunFile(BaseModel):
    """Which run file G-INSTR read for one plate: one a person linked, or the study's own file.

    The study's own file (RDML) names the instrument and the run date at most; the run file the
    instrument wrote (an ``.eds``, a QuantStudio results export, CFX run information) says
    whether the run completed, its pauses and its calibrations. No serial number is ever here.
    """

    plate: str
    source: Literal["linked", "study_file", "none"] = Field(
        description="linked: a run file a person linked; study_file: the study's own file; "
        "none: qPilot has no run context for this plate."
    )
    kind: str | None = Field(
        default=None,
        description="What the file read is: eds, quantstudio_export, cfx_run_information, rdml.",
    )
    name: str | None = Field(
        default=None, description="A linked file's name as the person gave it, serials blanked."
    )
    linked_at: str | None = Field(default=None, description="When a person linked it.")
    problem: Literal["", "missing", "changed", "unreadable"] = Field(
        default="", description="Why a linked file was not read (it is gone, changed or refused)."
    )
    verdict: Verdict = Field(description="G-INSTR's verdict for this plate.")
    evaluation: str | None = Field(
        default=None, description="The id of the plate's G-INSTR evaluation."
    )


class GateView(BaseModel):
    """``GET /studies/{id}/gate``: the controls on every plate, and whether they matter."""

    study_id: str
    session: str | None = Field(description="The Studio session the study came from, if any.")
    head: str = Field(description="The decision chain head the gate was read at.")
    pack: GatePack
    headline: FactText = Field(description="One line in plain words.")
    analysis: Literal["planned", "your_choices"] = Field(
        description="The analysis the consequences were measured at: the planned one, or the "
        "options a person chose on the Decision Cards."
    )
    exclude_in: Literal["curves", "none"] = Field(
        description="Where wells are left out: the Curves section of the Studio session, or "
        "nowhere on this page (a study analysed outside Studio)."
    )
    how_to_apply: str = Field(description="What to do about a finding, in words.")
    plates: list[GatePlate]
    n_gated: int
    n_ungated: int
    counts: dict[str, int] = Field(description="Rule evaluations per verdict (all four keys).")
    triage: dict[str, int] = Field(description="Consequence tests per triage (all four keys).")
    evaluations: list[GateEvaluation]
    consequences: list[GateConsequence]
    cards: list[CardView] = Field(
        description="The `gate.rule` cards: options with their per-gene calls, and what a "
        "person chose (a Studio session decides them here; a study analysed outside Studio "
        "cannot)."
    )
    can_decide: bool = Field(
        default=False,
        description="A person decides the cards here (a Studio session whose results show).",
    )
    inbox_head: str | None = Field(
        default=None,
        description="The session's proposal chain head the view was read at (send it back as "
        "`expected_inbox`).",
    )
    decide_note: str = Field(default="", description="What deciding a card here does, in words.")
    runs: list[GateRunFile] = Field(
        default=[], description="Per plate, the run file G-INSTR read (empty without G-INSTR)."
    )
    run_note: str = Field(default="", description="What linking a run file does, in words.")


class GateDecide(BaseModel):
    """``POST /studies/{id}/gate/cards/{card_id}/decide``: a person's choice on a gate card."""

    option: str = Field(max_length=64)
    reason: str = Field(default="", max_length=2000)
    expected_head: str | None = Field(
        default=None, max_length=64, description="The study's chain head the view showed."
    )
    expected_inbox: str | None = Field(
        default=None, max_length=64, description="The session's inbox head the view showed."
    )


class GateDecided(BaseModel):
    """What the choice did: wells left out or put back (the study is analysed again) or kept."""

    status: Literal["left_out", "put_back", "kept"]
    message: str
    study_id: str = Field(description="The analysis the choice was made at.")
    left_out: list[str]
    put_back: list[str]
    inbox_head: str
    job: JobView | None = Field(
        default=None, description="The analysis of the changed design, when it changed."
    )


class GateRunUnlink(BaseModel):
    """``POST /studies/{id}/gate/run-files/unlink``: a person removes a plate's linked run file."""

    plate: str = Field(min_length=1, max_length=200)


class GateRunLinked(BaseModel):
    """What linking (or unlinking) a run file did; the gate is read again with it."""

    plate: str
    linked: bool = Field(description="True: the plate now has this run file; False: unlinked.")
    name: str | None = None
    kind: str | None = None
    message: str


class GateLoaded(BaseModel):
    """The result of the ``gate.run`` job: the gate is ready to read."""

    study_id: str
    head: str
    n_evaluations: int
    n_consequences: int
    n_cards: int
    seconds: float
