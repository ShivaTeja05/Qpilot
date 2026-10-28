"""The Quantities view's API models: standard curves, LOD/LOQ and every unknown's quantity.

Every number is :mod:`qpilot.qpcr.absolute`'s (the engine's Cq and well exclusions). Units are
plain numbers in the standards' own unit (``unit``: "copies" when the file or a person says so);
the page formats them. ``null`` is "no value" (a fit that could not be made, an interval with
too few standards, a well with no Cq).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LimitView(BaseModel):
    """A limit of detection or of quantification: the quantity, how it was found, in words."""

    quantity: float | None
    method: Literal["empirical", "logistic", "lowest_standard", "not_determined"]
    words: str
    at_most: bool = Field(
        default=False, description="Every level passed: the true limit is at or below this."
    )


class LevelView(BaseModel):
    """One standard level: how often it was detected and how well its quantity reads back."""

    quantity: float
    n_wells: int
    n_detected: int
    rate: float | None
    mean_cq: float | None
    sd_cq: float | None
    back_quantity: float | None = Field(description="Geometric mean of the read-back quantities.")
    cv: float | None = Field(description="Log-normal CV of the read-back quantities (0.35 = 35 %).")


class StandardPointView(BaseModel):
    """One standard well (detected or not) on its curve."""

    run_id: str
    well: str
    sample: str
    quantity: float
    cq: float | None
    detected: bool
    residual: float | None
    back_quantity: float | None


class BandPoint(BaseModel):
    """The fitted line and its 95 % prediction band for one new well, at one log10 quantity."""

    log10_quantity: float
    cq: float
    low: float
    high: float


class CurveSummary(BaseModel):
    """One standard curve's numbers (per assay and plate, or pooled over plates)."""

    id: str
    target: str
    scope: Literal["plate", "pooled"]
    runs: list[str]
    fitted: bool
    problem: str = ""
    slope: float | None = None
    intercept: float | None = None
    r2: float | None = None
    efficiency: float | None = Field(default=None, description="10^(-1/slope) - 1 (1.0 = 100 %).")
    efficiency_low: float | None = None
    efficiency_high: float | None = None
    s_yx: float | None = Field(default=None, description="Residual SD of Cq about the line.")
    n_wells: int = 0
    n_levels: int = 0
    top: float | None = None
    lowest: float | None = None
    lod: LimitView
    lod_model: LimitView | None = None
    loq: LimitView
    quantity_source: str = Field(description="design, file, name, or a mix joined with '+'.")
    warnings: list[str] = []
    n_unknowns: int = Field(default=0, description="Units read from this curve.")


class CurveDetail(CurveSummary):
    """A curve with every point, level and the prediction band (for the chart)."""

    points: list[StandardPointView]
    levels: list[LevelView]
    band: list[BandPoint]


class FlagView(BaseModel):
    """One flag on an unknown, with its words."""

    id: str
    words: str


class UnknownWellView(BaseModel):
    """One well of an unknown."""

    run_id: str
    well: str
    sample: str
    cq: float | None
    detected: bool
    curve: str | None
    quantity: float | None


class UnitQuantity(BaseModel):
    """One biological unit's quantity of one assay with its 95 % prediction interval."""

    unit: str
    group: str | None = Field(default=None, description="Its group in the confirmed design.")
    samples: list[str]
    curves: list[str]
    n_wells: int
    n_detected: int
    mean_cq: float | None
    quantity: float | None
    low: float | None
    high: float | None
    per_ul: float | None = None
    per_ng: float | None = None
    flags: list[FlagView]
    wells: list[UnknownWellView]


class AssaySummary(BaseModel):
    """One assay: its curves and how many units were quantified or flagged."""

    target: str
    curves: list[CurveSummary]
    n_units: int
    n_quantified: int
    n_flagged: int


class NotQuantified(BaseModel):
    """An assay with standards but no curve, and why."""

    target: str
    reason: str


class ReactionView(BaseModel):
    """What one reaction held (the design's ``reaction_input``)."""

    template_ul: float | None = None
    input_ng: float | None = None
    unit: str | None = None


class QuantitiesSettings(BaseModel):
    """The thresholds in use, shown wherever they apply."""

    lod_rate: float
    loq_cv: float
    min_levels: int
    prediction_level: float


class QuantitiesView(BaseModel):
    """The study's absolute quantification: every assay with standards."""

    study_id: str
    available: bool = Field(description="False: no standard has a quantity (see `why`).")
    why: str = ""
    unit: str = Field(description="What one unit of the quantities is ('' when not declared).")
    settings: QuantitiesSettings
    reaction: ReactionView | None = None
    can_set_reaction: bool = Field(
        default=False, description="A person can record the reaction input (a Studio session)."
    )
    inbox_head: str | None = Field(
        default=None,
        description="The session's inbox head (a Studio session's study only): sent back as "
        "`expected_head` when the reaction input is recorded.",
    )
    assays: list[AssaySummary]
    not_quantified: list[NotQuantified]
    groups_shown: bool = Field(
        default=False, description="Units carry their design group (a groups design)."
    )
    notes: list[str] = []
    method_card: str
    references: list[str]


class AssayQuantities(BaseModel):
    """One assay: every curve in full and every unit's quantity."""

    study_id: str
    target: str
    unit: str
    settings: QuantitiesSettings
    reaction: ReactionView | None = None
    curves: list[CurveDetail]
    units: list[UnitQuantity]


class ReactionRequest(BaseModel):
    """A person records what one reaction held (all empty: per reaction only)."""

    template_ul: float | None = Field(default=None, gt=0, lt=1e9)
    input_ng: float | None = Field(default=None, gt=0, lt=1e9)
    unit: str | None = Field(default=None, max_length=40)
    reason: str = Field(min_length=1, max_length=2000)
    expected_head: str = Field(
        min_length=1,
        max_length=64,
        description="The session's inbox head the quantities view showed (its `inbox_head`); "
        "409 stale when something was decided since.",
    )


class ReactionRecorded(BaseModel):
    """What recording the reaction input did."""

    status: str
    head: str
    message: str


class CopiesAnswer(BaseModel):
    """ng to copies for a standard: the numbers and the formula, in words."""

    kind: Literal["dsDNA", "ssDNA", "RNA"]
    kind_words: str
    length: float
    ng: float
    molar_mass: float = Field(description="g/mol of one molecule.")
    copies: float = Field(description="Copies in that many ng.")
    copies_per_ng: float
    formula: str
    series: list[float] = Field(
        default=[], description="A serial dilution from `copies` (when a step was given)."
    )
    reference: str
