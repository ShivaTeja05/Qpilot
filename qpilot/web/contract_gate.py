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

from qpilot.web.contract import CardView, FactText

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
    """One verdict of one rule on one plate, plate x target or sample."""

    id: str = Field(description="A stable id of the evaluation (12 hex).")
    rule_id: str
    title: str
    level: Literal["plate", "target", "sample", "study"]
    plate: str | None = None
    target: str | None = None
    sample: str | None = None
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


class GateConsequence(BaseModel):
    """The consequence test of one warn/fail evaluation: every option, the class, the triage."""

    id: str = Field(description="The evaluation's id.")
    rule_id: str
    title: str
    plate: str | None = None
    target: str | None = None
    sample: str | None = None
    verdict: Verdict
    consequence: ConsequenceClass = Field(description="The worst class over the options.")
    triage: Triage
    triage_text: str = Field(description="What happens to the finding, in words.")
    rescue_option: str | None = None
    options: list[GateOption]
    card_id: str | None = Field(default=None, description="Its `gate.rule` Decision Card.")


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
        description="The `gate.rule` cards: options with their per-gene calls. Read-only here."
    )


class GateLoaded(BaseModel):
    """The result of the ``gate.run`` job: the gate is ready to read."""

    study_id: str
    head: str
    n_evaluations: int
    n_consequences: int
    n_cards: int
    seconds: float
