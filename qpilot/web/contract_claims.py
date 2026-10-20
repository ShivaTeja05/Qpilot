"""The Claim Auditor's part of the API contract: the request and the answers.

Owned by the ``claims`` router (:mod:`qpilot.web.routers.claims`). The answer models are the
engine's own (:mod:`qpilot.claims.models`), served as they are. Every string is text (never
HTML); every number in a sentence is a cited fact (``ClaimText.facts``), and a value quoted from
the checked text is a fact too (``origin="text"``). Keep changes additive and regenerate the
frontend's types (``npm run gen:api``) with them.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from qpilot.claims.models import (
    ClaimCheck,
    ClaimChoice,
    ClaimExample,
    ClaimExamples,
    ClaimFact,
    ClaimReading,
    ClaimsAssistResult,
    ClaimSegment,
    ClaimSpan,
    ClaimsReport,
    ClaimsSummary,
    ClaimText,
    ClaimView,
    TextRange,
)

MAX_CLAIMS_TEXT = 5000
"""The longest text checked at once (characters); a longer one answers 413 ``too_large``."""


class ClaimsBody(BaseModel):
    """The text to check (a results paragraph, a figure legend, an abstract)."""

    text: str = Field(
        default="",
        max_length=50_000,
        description=f"At most {MAX_CLAIMS_TEXT} characters are checked; longer is refused "
        "(413). The text is not stored.",
    )


__all__ = [
    "MAX_CLAIMS_TEXT",
    "ClaimCheck",
    "ClaimChoice",
    "ClaimExample",
    "ClaimExamples",
    "ClaimFact",
    "ClaimReading",
    "ClaimSegment",
    "ClaimSpan",
    "ClaimsAssistResult",
    "ClaimsBody",
    "ClaimsReport",
    "ClaimsSummary",
    "ClaimText",
    "ClaimView",
    "TextRange",
]
