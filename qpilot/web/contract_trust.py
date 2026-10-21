"""Response models of the Import Trust route: can the imported curves be trusted as they are?

Owned by the ``trust`` router (:mod:`qpilot.web.routers.trust`). The card's policy (which imports
get it, each option's analysis and confidence cap, the vendor's re-export recipe) is
:mod:`qpilot.io.trust`; the analysis is the engine's. Like :mod:`qpilot.web.contract`, every
string is text, never HTML. Keep changes additive and regenerate the frontend's types
(``npm run gen:api``) with them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from qpilot.web.contract import JobView

TrustOption = Literal["reexport_raw", "analyse_as_is", "cq_only"]
CapLevel = Literal["High", "Moderate", "Low", "Very low"]


class TrustOptionView(BaseModel):
    """One option of the Import Trust card: what it does to the analysis and its cap."""

    id: TrustOption
    label: str
    effect: str = Field(description="What choosing it does to the analysis, in words.")
    cap: CapLevel = Field(description="The highest confidence any gene has under it.")
    cap_reason: str = Field(description="The cap's reason, as the genes' reasons say it.")
    recommended: bool
    in_use: bool = Field(description="The option the analysis in use follows.")
    new_analysis: bool = Field(
        description="Choosing it analyses the study again (its Decision Cards start over)."
    )
    available: bool
    why_not: str = Field(default="", description="Why it cannot be chosen, when it cannot.")


class TrustPlateView(BaseModel):
    """One plate of the import and its raw-ness verdict."""

    run_id: str
    verdict: str


class TrustDecisionView(BaseModel):
    """What a person last chose on the card (the session's record)."""

    option: TrustOption
    label: str
    reason: str
    decided_at: str
    decided_by: Literal["human"] = "human"


class TrustRequestView(BaseModel):
    """An agent's request on the card, waiting for a person (asked over MCP)."""

    proposal_id: str
    option: TrustOption
    option_label: str
    reason: str
    agent: str | None = None
    at: str


class ImportTrustView(BaseModel):
    """``GET /studies/{id}/import-trust``: the Import Trust card of a study, when it has one.

    ``applies`` is false for every study whose curves call for no card (raw, normalised to a
    passive reference, an RDML file, a study analysed outside Studio); ``why`` says so and the
    other fields are empty. ``in_use`` is the option the analysis follows (the curves as
    imported until a person decides), ``cap`` and ``cap_reason`` the cap on every gene's grade
    at this analysis.
    """

    study_id: str
    applies: bool
    why: str = ""
    card_id: str = ""
    kind: str = ""
    question: str = ""
    verdict: str | None = None
    verdict_title: str = ""
    verdict_meaning: str = ""
    connector_label: str = ""
    recipe: str = Field(default="", description="How to export the raw curves from this software.")
    plates: list[TrustPlateView] = []
    n_instrument_cq: int = Field(default=0, description="Wells with a Cq from the instrument.")
    n_wells: int = 0
    options: list[TrustOptionView] = []
    status: Literal["open", "decided", "pending_human", "none"] = "none"
    in_use: TrustOption | None = None
    cap: CapLevel | None = None
    cap_reason: str = ""
    decision: TrustDecisionView | None = None
    requests: list[TrustRequestView] = []
    can_decide: bool = Field(
        default=False, description="A person can decide it here (the session's analysis in use)."
    )
    decide_note: str = ""
    inbox_head: str | None = Field(
        default=None, description="The session's inbox head (send it back as expected_inbox)."
    )


class TrustDecide(BaseModel):
    """``POST /studies/{id}/import-trust/decide``: a person's choice on the card, with a reason."""

    option: str = Field(max_length=64)
    reason: str = Field(default="", max_length=2000)
    expected_inbox: str | None = Field(
        default=None, max_length=64, description="The session's inbox head the view showed."
    )


class TrustDecided(BaseModel):
    """What the choice did: recorded, and (for a new analysis) the study analysed again."""

    status: Literal["decided"]
    option: TrustOption
    message: str
    study_id: str = Field(description="The analysis the choice was made at.")
    changed: bool = Field(description="The analysis changed: the study is analysed again.")
    inbox_head: str
    job: JobView | None = Field(
        default=None, description="The analysis of the changed design, when it changed."
    )


__all__ = [
    "ImportTrustView",
    "TrustDecide",
    "TrustDecided",
    "TrustDecisionView",
    "TrustOptionView",
    "TrustPlateView",
    "TrustRequestView",
]
