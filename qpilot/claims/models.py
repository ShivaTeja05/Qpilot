"""The Claim Auditor's answers, as typed models (the API serves them as they are).

A :class:`ClaimsReport` holds one :class:`ClaimView` per claim found in the text: where it is
(character offsets into the text that was sent), how it was read (:class:`ClaimReading`), the
verdict from a fixed vocabulary, the checks behind it (each a :class:`ClaimText` whose numbers
are facts), the choices under which it would hold, and a corrected sentence built from facts.

Every number in a :class:`ClaimText` is a :class:`ClaimFact` with an id and an ``origin``:
``result`` (the study's stored facts), ``grid`` (qPilot's choice grid, computed here),
``audit`` (the robustness audit) or ``text`` (a value quoted from the text being checked).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Verdict = Literal["supported", "choices", "overstated", "contradicted", "unchecked"]
VERDICTS: tuple[Verdict, ...] = ("supported", "choices", "overstated", "contradicted", "unchecked")
VERDICT_LABEL: dict[str, str] = {
    "supported": "Supported",
    "choices": "Holds only under some choices",
    "overstated": "Overstated",
    "contradicted": "Contradicted",
    "unchecked": "Cannot check",
}
VERDICT_RULE: dict[str, str] = {
    "supported": "Direction, size and significance agree with the study's planned analysis.",
    "choices": (
        "Not what the planned analysis shows, but what some of the choices qPilot checks give."
    ),
    "overstated": "Says more than the data do: a larger change, a stronger p or a robustness "
    "word the study does not earn.",
    "contradicted": "The study says otherwise: the other direction, no change where there is "
    "one, or a number its data exclude.",
    "unchecked": "The study cannot answer it: a gene it did not compare, or words too vague "
    "to check.",
}
CheckStatus = Literal["ok", "stronger", "weaker", "opposite", "unknown", "note"]
CheckName = Literal[
    "gene",
    "direction",
    "fold",
    "p",
    "significance",
    "robust",
    "normaliser",
    "efficiency",
    "n",
    "grid",
    "audit",
    "choices",
    "reading",
]
FactOrigin = Literal["result", "grid", "audit", "text"]
SpanRole = Literal[
    "gene",
    "direction",
    "negation",
    "hedge",
    "fold",
    "p",
    "significance",
    "robust",
    "normaliser",
    "group",
    "n",
    "efficiency",
]
ClaimKind = Literal["gene", "normaliser", "efficiency", "n"]
Conclusion = Literal["up", "down", "none"]


class ClaimFact(BaseModel):
    """A number (or a label with digits) a sentence cites, and where it comes from."""

    id: str
    text: str = Field(description="The value as written (format and unit applied).")
    value: float | int | str
    unit: str = ""
    path: str = Field(default="", description="Where it comes from (a result path, a grid "
                      "cell, an audit file, or characters of the text).")  # fmt: skip
    origin: FactOrigin = "result"


class ClaimSegment(BaseModel):
    """A run of plain text, or one cited value (``fact`` names it)."""

    text: str
    fact: str | None = None


class ClaimText(BaseModel):
    """A sentence whose numbers are facts: plain text, its segments, the facts it cites."""

    plain: str
    segments: list[ClaimSegment]
    facts: list[ClaimFact]


class TextRange(BaseModel):
    """Characters ``start`` (inclusive) to ``end`` (exclusive) of the text that was checked."""

    start: int
    end: int


class ClaimSpan(BaseModel):
    """One piece of the text the reading rests on (underlined on the page)."""

    start: int
    end: int
    role: SpanRole
    written: str


class ClaimReading(BaseModel):
    """How the rules (or a model's proposal, checked) read one claim. Values are as written."""

    gene: str | None = Field(default=None, description="The study's name for the gene.")
    gene_written: str | None = None
    gene_via: Literal["name", "assay", "alias"] | None = Field(
        default=None, description="Found by its name, its name without assay suffix, or an "
        "HGNC alias or previous symbol.")  # fmt: skip
    gene_status: (
        Literal["compared", "reference", "marker", "withheld", "measured", "absent"] | None
    ) = None
    direction: Conclusion | None = Field(
        default=None, description="The direction the words state, read for the first group "
        "against the second (a sentence about the second group is turned around).")  # fmt: skip
    direction_written: str | None = None
    negated: bool = False
    hedged: bool = False
    inverted: bool = Field(default=False, description="The words compare the second group "
                           "with the first.")  # fmt: skip
    fold_written: str | None = None
    fold_comparator: Literal["about", "exact", "at_least", "at_most", "range"] | None = None
    fold_kind: Literal["fold", "percent", "log2"] | None = None
    p_written: str | None = None
    p_adjusted: bool = False
    significance: Literal["significant", "not_significant"] | None = None
    significance_written: str | None = None
    robust_written: str | None = None
    normaliser: list[str] = Field(description="Control genes named.")
    groups_written: list[str]
    n_written: str | None = None
    efficiency_written: str | None = None
    efficiency_genes: list[str]
    source: Literal["rules", "model"] = "rules"
    words: list[str] = Field(
        description="The reading in short pieces for the page (each from the text or a name).",
    )


class ClaimCheck(BaseModel):
    """One check behind a verdict: what was compared, and how it came out."""

    check: CheckName
    status: CheckStatus
    text: ClaimText


class ClaimChoice(BaseModel):
    """One choice qPilot checks under which the claim would hold (or that changes it)."""

    dimension: str
    title: str = Field(description="The decision in words.")
    option: str = Field(description="The option's value in qPilot's grid.")
    label: ClaimText
    card_id: str | None = None
    option_id: str | None = None
    planned: bool = False
    holds: bool
    call: Conclusion | None = None
    fc: float | None = None


class ClaimView(BaseModel):
    """One claim: where it is, how it was read, the verdict and why."""

    id: str
    kind: ClaimKind
    sentence: TextRange
    clause: TextRange
    spans: list[ClaimSpan]
    reading: ClaimReading
    verdict: Verdict
    verdict_label: str
    headline: ClaimText = Field(description="One sentence: the verdict's main reason.")
    checks: list[ClaimCheck]
    choices: list[ClaimChoice]
    grid_holds: int | None = Field(default=None, description="Analyses in qPilot's grid "
                                   "where this reading holds.")  # fmt: skip
    grid_cells: int | None = None
    audit_verdict: str | None = None
    audit_label: str | None = None
    suggestion: ClaimText | None = Field(
        default=None, description="A sentence the record supports, built from facts."
    )
    gene: str | None = Field(default=None, description="The compared gene to open, if any.")
    severity: int = Field(description="Sort key: contradicted 4 … supported 0.")


class ClaimsSummary(BaseModel):
    """How many claims came out which way."""

    n: int
    supported: int
    counts: dict[str, int]
    sentence: str


class ClaimsReport(BaseModel):
    """Every claim in a text, checked against one study."""

    study_id: str
    length: int = Field(description="The length of the text that was checked (characters).")
    text_sha256: str
    claims: list[ClaimView]
    summary: ClaimsSummary
    reader: Literal["rules", "rules+model"] = "rules"
    model_note: str | None = None
    head: str = Field(description="The decision chain's head the claims were checked at.")
    audit: Literal["none", "current", "older"] = "none"
    groups: list[str] = Field(description="The compared group, then the reference group.")
    rule: str = Field(description="qPilot's call rule in words.")
    verdicts: dict[str, str] = Field(description="Each verdict's label.")
    verdict_rules: dict[str, str] = Field(description="What each verdict means.")
    notes: list[str]


class ClaimExample(BaseModel):
    """One example sentence the server wrote from the study's facts, and what it shows."""

    text: str
    intent: Verdict
    what: str = Field(description="What the sentence was written to show, in words.")


class ClaimExamples(BaseModel):
    """Example sentences about this study, written from its facts (none is hand-written)."""

    study_id: str
    paragraph: str
    examples: list[ClaimExample]
    note: str


class ClaimsAssistResult(BaseModel):
    """What the ``claims.read`` job answers: the report, with the model's part said."""

    report: ClaimsReport
    proposed: int = Field(description="Readings the model proposed.")
    accepted: int = Field(description="Proposals whose every value is in the sentence it cites.")
    rejected: list[str] = Field(description="Why proposals were dropped.")
