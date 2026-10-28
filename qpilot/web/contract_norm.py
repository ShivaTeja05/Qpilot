"""API models of the reference-gene panel: geNorm and NormFinder side by side.

``GET /api/studies/{id}/references`` (:mod:`qpilot.web.routers.references`). Raw numbers from the
engine (:mod:`qpilot.qpcr.refgenes`, :mod:`qpilot.qpcr.normfinder`); the page formats them. The
words say what the two methods agree on; they never say which reference genes to use, which
stays a person's choice on the reference-gene card.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ReferenceGeneRow(BaseModel):
    """One candidate reference gene under both methods (lower is steadier in each)."""

    gene: str
    used: bool = Field(description="The analysis in use divides by it.")
    genorm_m: float | None = Field(
        default=None, description="geNorm M: the mean SD of its log2 ratio to each other candidate."
    )
    genorm_rank: int | None = Field(default=None, description="1 = steadiest by geNorm.")
    normfinder: float | None = Field(
        default=None,
        description="NormFinder's stability value: the error it would bring in (log2), from its "
        "variation within each group and its shift between the groups.",
    )
    normfinder_rank: int | None = Field(default=None, description="1 = steadiest by NormFinder.")
    within_sd: float | None = Field(
        default=None, description="NormFinder's within-group SD (log2), mean over the groups."
    )
    shift: dict[str, float] = Field(
        default_factory=dict,
        description="NormFinder's shift of the gene in each group (log2), before shrinkage.",
    )


class ReferencePair(BaseModel):
    """A best pair by one method, with its value where the method gives one."""

    genes: list[str]
    value: float | None = None


class ReferenceStability(BaseModel):
    """geNorm M and NormFinder's stability side by side, and whether they agree."""

    study_id: str
    candidates: list[str]
    used: list[str] = Field(description="The reference genes the analysis in use divides by.")
    rows: list[ReferenceGeneRow] = Field(description="Every candidate, in candidate order.")
    genorm_pair: ReferencePair | None = Field(
        default=None, description="geNorm's best pair (its last two genes; it cannot order them)."
    )
    normfinder_pair: ReferencePair | None = None
    verdict: Literal["agree", "share_one", "disagree", "not_available"]
    words: str = Field(description="What the two agree or disagree on, in plain words.")
    choice_note: str = Field(description="Which reference genes are used stays a person's choice.")
    grouped: bool = Field(description="NormFinder used the study's groups.")
    groups: dict[str, int] = Field(default_factory=dict, description="Group -> units used.")
    n_units: int = 0
    n_left_out: int = Field(default=0, description="Units NormFinder could not use, and why below.")
    left_out_reasons: dict[str, int] = Field(
        default_factory=dict, description="Why units were left out -> how many."
    )
    warnings: list[str] = Field(default_factory=list, description="The paper's own requirements.")
    unavailable: str | None = Field(
        default=None, description="Why NormFinder could not run (then no NormFinder numbers)."
    )
    sources: list[str]
