"""Response models of the Cq table route: the Curves stage of a file of Cq values only.

Owned by the ``cqonly`` router (:mod:`qpilot.web.routers.cqonly`). A file with no amplification
curves (a Cq table, a Cq-only RDML: :mod:`qpilot.qpcr.cq_only`, ``docs/cq-tables.md``) has no
curve to judge, so its curves stage confirms the Cq table instead: each sample's Cq per well,
the wells without a Cq, the replicate sets whose spread is wider than expected (the Run Gate's
rule G-REP, the same numbers) and each assay's efficiency. It is blind like the rest of the
curves stage: no group, fold change or p-value is ever in it. Every number is the engine's; every
string is text, never HTML. Keep changes additive and regenerate the frontend's types
(``npm run gen:api``) with them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Spread = Literal["within", "outside", "not_evaluated"]


class CqWellView(BaseModel):
    """One well of a replicate set: its Cq as the file gives it, and whether it is used."""

    key: str = Field(description="`plate/well`.")
    well: str
    cq: float | None = Field(default=None, description="The file's Cq (a cycle); none: no Cq.")
    used: bool = Field(description="It has a Cq and no one left it out.")
    left_out: bool = Field(default=False, description="A person left it out of the analysis.")
    file_excluded: str = Field(default="", description="The file's own exclusion note, if any.")
    late: bool = Field(default=False, description="Its Cq is above the latest Cq cut-off (35).")


class CqSetView(BaseModel):
    """The wells of one sample and target on one plate (its technical replicates)."""

    run_id: str
    sample: str
    sample_text_id: str | None = None
    target: str
    target_text_id: str | None = None
    role: str = Field(description="Its sample type in the design (unkn, std, ntc, …).")
    wells: list[CqWellView]
    n_wells: int
    n_with_cq: int
    mean_cq: float | None = None
    range_cq: float | None = Field(
        default=None, description="Highest minus lowest Cq of its wells with a Cq."
    )
    tolerance: float | None = Field(
        default=None, description="G-REP's expected range for this copy number (cycles)."
    )
    spread: Spread = Field(description="G-REP's verdict on the replicate spread.")
    spread_words: str = Field(description="G-REP's sentence, or why it was not evaluated.")
    flags: list[str] = Field(default=[], description="What to look at, in plain words.")


class CqEfficiencyView(BaseModel):
    """One assay's efficiency: from its dilution series, or assumed to be 2.0."""

    target: str
    efficiency: float = Field(description="E (2.0: every cycle doubles the product).")
    source: Literal["dilution_series", "assumed"]
    words: str


class CqCounts(BaseModel):
    """How many wells and replicate sets the table holds, and how many to look at."""

    n_wells: int = Field(description="Wells of the analysed plates (left-out targets excluded).")
    n_with_cq: int
    n_without_cq: int
    n_study_without_cq: int = Field(description="Study-sample wells without a Cq (non-detects).")
    n_sets: int
    n_outside: int = Field(description="Replicate sets wider than G-REP expects.")
    n_late: int = Field(description="Wells with a Cq above 35.")
    n_controls_with_cq: int = Field(description="Negative-control wells (NTC, no-RT…) with a Cq.")


class CqTableView(BaseModel):
    """The Curves stage of a file of Cq values only (``cq_only: false`` for a file with curves)."""

    key: str
    cq_only: bool
    shown: bool = Field(description="The Cq values are shown (the design is confirmed).")
    message: str = Field(description="What this stage is, in one or two sentences.")
    not_applicable: list[str] = Field(
        default=[], description="The curve-based checks that do not apply, in plain words."
    )
    efficiencies: list[CqEfficiencyView] = []
    counts: CqCounts | None = None
    sets: list[CqSetView] = []
    rule: str = Field(default="", description="G-REP's statement (the rule pack's words).")
