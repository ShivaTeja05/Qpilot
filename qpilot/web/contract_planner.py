"""Response and request models of the planner: plan the next experiment from this one.

Owned by the ``planner`` router (:mod:`qpilot.web.routers.planner`). Every number comes from the
open study (its per-unit values, its groups, its efficiencies), from :mod:`qpilot.qpcr.plan` or
from :mod:`qpilot.qpcr.layout`; every string is text (never HTML). Keep changes additive and
regenerate the frontend's types (``npm run gen:api``) with them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from qpilot.qpcr import layout as lay

Conclusion = Literal["up", "down", "none"]

# ---- what the study measured ------------------------------------------------------------------


class PlannerGroup(BaseModel):
    """One group of the study's comparison and how many biological units it holds."""

    label: str
    n: int


class PlannerGene(BaseModel):
    """One compared gene: its noise in this study, and what the study found."""

    gene: str
    sigma: float = Field(
        description="Pooled SD of log2 relative quantity between biological units of one group "
        "(qpilot.qpcr.plan.pooled_sd over the engine's per-unit values)."
    )
    sigma_ci: tuple[float, float] = Field(
        description="95 % chi-square interval of sigma (qpilot.qpcr.plan.sigma_interval)."
    )
    df: int = Field(description="Degrees of freedom of sigma: units with a value minus groups.")
    n: list[int] = Field(description="Units with a value in each group, in the groups' order.")
    fc: float = Field(description="The fold change this study found (group 1 / group 2).")
    conclusion: Conclusion
    efficiency: float | None = Field(
        default=None, description="The gene's PCR efficiency (fold per cycle; 2 is doubling)."
    )
    efficiency_outside: bool = Field(
        description="Efficiency outside the engine's 90–110 % range (a warning only)."
    )
    headline: bool


class PlanSpread(BaseModel):
    """Five numbers that describe a spread (min, quartiles, median, max) over genes."""

    n: int
    min: float
    q1: float
    median: float
    q3: float
    max: float


class PlanEfficiency(BaseModel):
    """The genes' efficiencies and which fall outside the engine's usual range."""

    spread: PlanSpread | None
    range: tuple[float, float] = Field(description="The usual range as E - 1 (0.90–1.10).")
    outside: list[str]
    text: str


class PlanStudyPlates(BaseModel):
    """How this study laid out its plates (from its per-well table)."""

    n_plates: int
    wells_per_plate: int = Field(description="The most wells any plate used.")
    targets_per_plate: float = Field(description="Median number of targets per plate.")
    samples_per_plate: float = Field(description="Median number of study samples per plate.")
    controls_per_plate: dict[str, float] = Field(
        description="Median wells per plate by control type (std, ntc, nrt, …)."
    )
    sample_maximisation: bool = Field(
        description="Every plate held one target for every sample (Hellemans 2007)."
    )
    text: str


class PlanControls(BaseModel):
    """Controls on every plate, per assay."""

    ntc: int = Field(default=1, ge=0, le=lay.MAX_PER_ASSAY, description="NTC wells per assay.")
    nrt: int = Field(default=0, ge=0, le=lay.MAX_PER_ASSAY, description="NRT wells per assay.")
    standards: int = Field(
        default=0,
        ge=0,
        le=lay.MAX_STANDARDS,
        description="Standard dilution points per assay, each in the technical replicates.",
    )
    calibrator: bool = Field(
        default=True,
        description="An inter-run calibrator on every plate when a gene's samples span plates.",
    )


class PlannerBody(BaseModel):
    """What to plan: the change worth finding, the power, and the next experiment's shape."""

    fold: float | None = Field(
        default=None,
        description="The smallest fold change worth detecting (e.g. 2.5, or 0.4); none: a "
        "quarter above the call rule's threshold (2.5 for a 2-fold rule; plan.default_fold).",
    )
    power: float = Field(default=0.80, ge=0.5, le=0.99)
    alpha: float | None = Field(
        default=None, ge=0.001, le=0.2, description="Two-sided; default the study's rule."
    )
    n_per_group: int | None = Field(
        default=None,
        ge=2,
        le=lay.MAX_SAMPLES_PER_GROUP,
        description="Planned samples per group; none: the size the chosen genes need.",
    )
    genes: list[str] | None = Field(
        default=None,
        max_length=lay.MAX_GENES,
        description="The next experiment's genes (default: the study's headline genes).",
    )
    refs: list[str] | None = Field(
        default=None,
        max_length=lay.MAX_REFS,
        description="Reference genes on every plate (default: the study's control genes).",
    )
    plates: int | None = Field(
        default=None, ge=1, le=lay.MAX_PLATES, description="Plates available (a budget)."
    )
    wells_per_plate: Literal[96, 384] = 96
    replicates: int = Field(default=2, ge=1, le=lay.MAX_REPLICATES)
    controls: PlanControls = Field(default_factory=PlanControls)


class PlannerView(BaseModel):
    """What the study measured that a plan needs: noise per gene, group sizes, efficiencies."""

    study_id: str
    head: str
    groups: list[PlannerGroup]
    n_equivalent: float = Field(
        description="The balanced group size as precise as the study's groups (harmonic mean)."
    )
    alpha: float
    min_fold: float = Field(description="The rule's fold threshold for a call (2 = two-fold).")
    rule_text: str
    sigma_source: str = Field(description="How sigma was measured, in words.")
    genes: list[PlannerGene]
    sigma: PlanSpread
    refs: list[str] = Field(description="The control genes this study normalises by.")
    candidates: list[str] = Field(description="The reference candidates the study tested.")
    headline: list[str]
    efficiency: PlanEfficiency
    plates: PlanStudyPlates | None
    defaults: PlannerBody
    fold_note: str = Field(
        default="",
        description="How the change worth finding relates to the call rule, in plain words.",
    )


# ---- the plan ---------------------------------------------------------------------------------


class PlanGene(BaseModel):
    """One gene under the plan: samples needed, what the plan's size detects, the right call."""

    gene: str
    sigma: float
    focus: bool = Field(description="One of the next experiment's genes.")
    n_needed: int = Field(
        description="Per group for p < alpha with the chosen power (qpilot.qpcr.plan.n_needed)."
    )
    n_for_call: int | None = Field(
        default=None,
        description="Per group for qPilot's rule to call the change with the chosen power "
        "(qpilot.qpcr.plan.n_for_call); None: no size reaches it, or not computed (not focus).",
    )
    call_reachable: bool | None = Field(
        default=None, description="Whether any size reaches the power for a call; None: not asked."
    )
    mde_fold: float = Field(description="The smallest change the plan's size detects (mde_fold).")
    p_significant: float = Field(description="Simulated P(p < alpha) at the plan's size.")
    p_called: float = Field(description="Simulated P(qPilot calls it, right way) at that size.")
    current_mde_fold: float = Field(description="mde_fold_groups at the study's own group sizes.")
    current_p_called: float = Field(
        description="Simulated P(called) at the study's own (unbalanced) group sizes."
    )
    detectable: bool = Field(description="mde_fold at the plan's size ≤ the target change.")
    cannot_detect: list[str] = Field(description="qpilot.qpcr.plan.plan's lines, as text.")


class PlanCurvePoint(BaseModel):
    """One group size on a power curve."""

    n: int
    p_significant: float
    p_called: float


class PlanPowerCurve(BaseModel):
    """P(significant) and P(called) against samples per group, at the gene's sigma."""

    gene: str
    sigma: float
    points: list[PlanCurvePoint]
    n_needed: int
    n_for_call: int | None


class PlanLayoutEstimate(BaseModel):
    """How the plan would be laid out (no well assigned yet)."""

    plates: int
    panels: int
    batches: int
    samples_per_plate: int
    calibrated: bool
    wells: int = Field(description="Wells the plates hold in all.")


class PlanBudget(BaseModel):
    """What fits in the plates available."""

    plates: int
    n_fit: int | None = Field(
        description="The most samples per group whose layout fits; None: not even two."
    )
    text: str


class PlanView(BaseModel):
    """The plan: per gene numbers, power curves, the rules, what it cannot detect, plates."""

    study_id: str
    head: str
    fold: float
    target: float = Field(description="The change in either direction, ≥ 1 (max(fold, 1/fold)).")
    power: float
    alpha: float
    min_fold: float
    n_plan: int = Field(description="The samples per group the numbers are at.")
    n_plan_reason: str
    genes: list[PlanGene]
    focus: list[str]
    refs: list[str]
    curves: list[PlanPowerCurve]
    curve_reps: int = Field(description="Simulated studies behind each curve point.")
    table_reps: int = Field(description="Simulated studies behind each table probability.")
    n_current: list[int] = Field(description="The study's own group sizes.")
    n_equivalent: float
    headline: str = Field(description="One sentence: what this plan detects.")
    ceiling: str | None = Field(
        default=None,
        description="When the target is at or below the rule's threshold: why no size calls it.",
    )
    cannot_detect: list[str]
    rules: list[str] = Field(description="qpilot.qpcr.plan's design rules for this plan.")
    layout: PlanLayoutEstimate | None
    layout_error: str | None = None
    budget: PlanBudget | None = None


# ---- the plates -------------------------------------------------------------------------------


class PlanLayoutBody(BaseModel):
    """The next experiment to lay out on plates."""

    n_per_group: int = Field(ge=2, le=lay.MAX_SAMPLES_PER_GROUP)
    genes: list[str] = Field(min_length=1, max_length=lay.MAX_GENES)
    refs: list[str] | None = Field(default=None, max_length=lay.MAX_REFS)
    replicates: int = Field(default=2, ge=1, le=lay.MAX_REPLICATES)
    wells_per_plate: Literal[96, 384] = 96
    ntc: int = Field(default=1, ge=0, le=lay.MAX_PER_ASSAY)
    nrt: int = Field(default=0, ge=0, le=lay.MAX_PER_ASSAY)
    standards: int = Field(default=0, ge=0, le=lay.MAX_STANDARDS)
    calibrator: bool = True
    seed: int = Field(default=1, ge=0, le=2**31 - 1)

    @field_validator("wells_per_plate", mode="before")
    @classmethod
    def _plate_from_text(cls, value: object) -> object:
        """A query string carries ``96`` as text; read it as the number it is."""
        return int(value) if isinstance(value, str) and value.isdigit() else value


class PlanLayoutWell(BaseModel):
    """One well: position, sample (and group), assay, RDML sample type, replicate."""

    well: str
    sample: str
    group: str | None
    target: str
    type: Literal["unkn", "std", "ntc", "nrt", "pos"]
    replicate: int


class PlanLayoutPlate(BaseModel):
    """One plate of the layout with its balance."""

    number: int
    name: str
    panel: int
    batch: int
    genes: list[str]
    refs: list[str]
    wells: list[PlanLayoutWell]
    wells_used: int
    wells_free: int
    samples: dict[str, int] = Field(description="Group → samples on this plate.")
    groups_present: int
    refs_present: bool
    controls: dict[str, int] = Field(description="Control type → wells.")
    edge_share: dict[str, float | None] = Field(
        description="Group → share of its wells on the plate's outer rows and columns."
    )


class PlanLayoutBalance(BaseModel):
    """The checks every layout passes (or says why not)."""

    every_plate_every_group: bool
    plates_with_one_group: list[int]
    refs_on_every_plate: bool
    controls_on_every_plate: bool
    each_reaction_once: bool = Field(
        description="Every planned gene reaction on exactly one plate; a reference gene's once "
        "per gene panel (each plate normalises its own samples)."
    )
    group_plate_association: float = Field(
        description="Cramér's V of plate × group over samples: 0 means plate says nothing of group."
    )
    max_share_gap: float = Field(
        description="Largest gap between a group's share on a plate and its share overall."
    )
    wells_total: int
    wells_samples: int
    wells_controls: int
    wells_free: int


class PlanLayoutView(BaseModel):
    """Every plate of the next experiment, its balance, and the CSV to import."""

    study_id: str
    seed: int
    groups: list[PlannerGroup]
    genes: list[str]
    refs: list[str]
    replicates: int
    wells_per_plate: int
    panels: list[list[str]]
    batches: int
    samples_per_plate: int
    calibrated: bool
    plates: list[PlanLayoutPlate]
    balance: PlanLayoutBalance
    notes: list[str]
    warnings: list[str]
    rules: list[str]
    csv_url: str = Field(description="GET this for the CSV (same inputs, same plates).")
    csv_name: str
