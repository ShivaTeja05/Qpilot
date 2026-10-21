"""Response models of the Evidence Ledger and Run Review routes (``routers/evidence.py``).

Ported from the Gradio app's Evidence panel and Run Review accordion (origin/main, 18 Oct): the
same engine (:mod:`qpilot.qpcr.evidence`, :mod:`qpilot.report.run_review`), every sentence
token text validated by :mod:`qpilot.explain.evidence_text` and sent as :class:`FactText`, so
every number on the page is one of the ledger's or the study's facts.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from qpilot.web.contract import FactText

EvidenceStatus = Literal["present", "absent", "not_applicable", "unknown"]
ReviewOutcome = Literal["accept", "repeat", "discuss"]


class EvidenceItemView(BaseModel):
    """One item of the Evidence Ledger: what the study has or lacks, and what that means."""

    id: str
    title: str
    status: EvidenceStatus
    status_word: str = Field(description="present, absent, not applicable or unknown.")
    value: str | None = Field(None, description="e.g. the efficiency source.")
    line: FactText = Field(description="Title, status and what it means, numbers as facts.")
    cannot_tell: bool = Field(
        description="Absent or unknown: the item says what this study cannot tell you."
    )
    miqe: list[str] = Field(description="The MIQE 2.0 items it answers.")


class EvidenceView(BaseModel):
    """``GET /studies/{id}/evidence``: the Evidence Ledger, or why there is none."""

    study_id: str
    available: bool
    source: Literal["kept", "rebuilt", "none"] = Field(
        description="kept: saved when the study was analysed; rebuilt: re-read from the input "
        "file for this page (nothing saved); none: not available (note says why)."
    )
    note: str = ""
    summary: FactText | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    items: list[EvidenceItemView] = Field(default_factory=list)
    rule: str = Field(description="Absent items never change a conclusion or a confidence grade.")
    method_card: str = "methods/evidence.md"


class ReviewHeadlineView(BaseModel):
    """One headline gene on the Run Review."""

    gene: str
    conclusion: Literal["up", "down", "none"]
    line: FactText


class SignOffView(BaseModel):
    """A recorded sign-off: one ``review`` entry in the decision chain (always a person's)."""

    seq: int
    outcome: ReviewOutcome
    outcome_word: str
    reviewer: str
    comment: str
    at: str
    hash: str
    line: FactText


class ReviewOutcomeView(BaseModel):
    """One outcome a person can sign off with."""

    id: ReviewOutcome
    label: str
    meaning: str


class NotBuiltView(BaseModel):
    """A part of the full Run Review that is not built yet (said, never faked)."""

    id: str
    title: str
    reason: str
    section: str | None = Field(None, description="The page section that shows it instead.")


class RunReviewView(BaseModel):
    """``GET /studies/{id}/review``: one page for the person who reviews someone else's work."""

    study_id: str
    session: str | None = None
    head: str = Field(description="The chain head now; send it back as expected_head.")
    title: FactText
    purpose: str
    headline: list[ReviewHeadlineView]
    evidence: EvidenceView
    sign_offs: list[SignOffView]
    outcomes: list[ReviewOutcomeView]
    not_built: list[NotBuiltView]
    can_sign_off: bool = Field(
        description="False for an analysis a Studio session has moved on from (sign off the "
        "current one); why_not says so."
    )
    why_not: str = ""
    max_comment: int
    max_reviewer: int


class SignOffBody(BaseModel):
    """A person's sign-off (the server records it as ``human``; the page cannot choose)."""

    outcome: ReviewOutcome
    comment: str = Field(max_length=2000, description="Why (required; kept in the chain).")
    reviewer: str = Field(max_length=400, description="Who signs off (kept in the chain).")
    expected_head: str = Field(
        min_length=1,
        max_length=128,
        description="The chain head the review was read at (409 stale when a decision moved "
        "it since).",
    )


class SignOffDone(BaseModel):
    """The answer to a sign-off: the entry as written, the new head and the page again."""

    message: str
    head: str
    sign_off: SignOffView
    review: RunReviewView


__all__ = [
    "EvidenceItemView",
    "EvidenceStatus",
    "EvidenceView",
    "NotBuiltView",
    "ReviewHeadlineView",
    "ReviewOutcome",
    "ReviewOutcomeView",
    "RunReviewView",
    "SignOffBody",
    "SignOffDone",
    "SignOffView",
]
