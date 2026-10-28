"""Response models of the melt route: each well's melt curve, its peaks, and its assay's product.

Owned by the ``melt`` router (:mod:`qpilot.web.routers.melt`). The maths is
:mod:`qpilot.qpcr.melt` (method card ``methods/melt_curve.md``); the thresholds are the Run
Gate pack's rule G-MELT. Every number here is the engine's; the page formats it. Like
:mod:`qpilot.web.contract`, every string is text, never HTML. Keep changes additive and
regenerate the frontend's types (``npm run gen:api``) with them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MeltStatus = Literal[
    "one_product",
    "extra_peak",
    "tm_off",
    "no_peak",
    "not_amplified",
    "no_product",
    "product",
    "dimer",
    "other_product",
    "unclassified",
    "not_judged",
    "unreadable",
    "no_melt",
]


class MeltParamsView(BaseModel):
    """The thresholds the calls were made with (the pack's G-MELT parameters)."""

    tm_tolerance_c: float = Field(description="How far (°C) a product may melt from the expected.")
    extra_peak_share: float = Field(
        description="An extra peak counts when it carries at least this share of the peaks."
    )
    noise_share: float = Field(
        description="A peak lower than this share of the assay's typical product peak is noise."
    )
    min_wells: int = Field(description="Study wells needed to take the expected Tm from them.")


class MeltPeakView(BaseModel):
    """One counted peak of a well's −dF/dT."""

    tm: float = Field(description="Its melting temperature (°C): the top of the peak.")
    height: float = Field(description="−dF/dT at the top (fluorescence per °C).")
    share: float = Field(description="Its share of the well's counted peaks (0 to 1).")
    width_c: float | None = Field(default=None, description="Width at half height (°C).")
    role: Literal["product", "extra", "minor"] = Field(
        description="`product`: the well's main peak (its product when it is at the expected "
        "Tm); `extra`: a peak carrying at least the extra-peak share; `minor`: counted, smaller."
    )


class MeltCallView(BaseModel):
    """One well's melt call (no curve): what the plate list and the gate's wells show."""

    key: str = Field(description="`plate/well`.")
    run_id: str
    well: str
    sample: str
    target: str
    sample_type: str
    status: MeltStatus
    status_text: str = Field(description="The call in plain words.")
    flagged: bool = Field(description="G-MELT points at this well.")
    main_tm: float | None = Field(default=None, description="The main peak's Tm (°C).")
    offset_c: float | None = Field(
        default=None, description="The main peak's Tm minus the expected Tm (°C)."
    )
    n_peaks: int = 0


class MeltWellView(MeltCallView):
    """One well's melt curve: the readings, −dF/dT on an even grid, and its counted peaks."""

    amplified: bool
    cq: float | None = None
    peaks: list[MeltPeakView] = Field(default_factory=list)
    readings_temperature: list[float] = Field(
        default_factory=list, description="The file's melt readings: temperatures (°C)."
    )
    readings_fluorescence: list[float | None] = Field(
        default_factory=list, description="The file's melt readings: fluorescence."
    )
    temperature: list[float] = Field(
        default_factory=list, description="The even grid −dF/dT is computed on (°C)."
    )
    derivative: list[float] = Field(
        default_factory=list, description="−dF/dT on the grid (fluorescence per °C)."
    )
    step_c: float | None = Field(default=None, description="Median step between readings (°C).")
    problem: str = Field(
        default="", description="`too_few_points` or `coarse` when the curve cannot be judged."
    )


class MeltAssayView(BaseModel):
    """One target on one plate: where its product melts and how its wells were called."""

    run_id: str
    target: str
    expected_tm: float | None = Field(
        default=None, description="Where the product is expected to melt (°C)."
    )
    expected_source: Literal["file", "median"] | None = Field(
        default=None,
        description="`file`: the target's melting temperature the file declares; `median`: the "
        "median main-peak Tm of the plate's amplified study wells; none: not known.",
    )
    n_reference: int = Field(description="Study wells the median and the noise floor come from.")
    median_tm: float | None = None
    min_tm: float | None = None
    max_tm: float | None = None
    spread_c: float | None = Field(default=None, description="Highest minus lowest of those Tm.")
    noise_floor: float | None = Field(
        default=None, description="Peaks lower than this (−dF/dT) are not counted."
    )
    step_c: float | None = None
    n_wells: int = Field(description="Wells of this target on the plate with a melt curve.")
    counts: dict[str, int] = Field(description="Wells per call.")
    flagged: list[str] = Field(description="The wells G-MELT points at (`plate/well`).")
    summary: str = Field(description="The assay in one plain sentence.")


class MeltTargetView(BaseModel):
    """One target over every plate: its product's median Tm and range."""

    target: str
    n_plates: int
    n_wells: int
    median_tm: float | None = None
    min_tm: float | None = None
    max_tm: float | None = None


class MeltView(BaseModel):
    """The melt curves of a study or a session: one plate's assays and calls, some wells' curves.

    ``has_melt`` false: the file holds no melt curve (``message`` says what to export).
    ``calls`` are every well of the plate ``run`` with a melt curve; ``wells`` the curves of the
    wells asked for (at most twelve).
    """

    key: str = Field(description="The session id or the study id asked about.")
    study_id: str | None = None
    has_melt: bool
    message: str = Field(default="", description="What to do when there is nothing to show.")
    run: str | None = Field(default=None, description="The plate shown.")
    plates: list[str] = Field(description="The plates with melt curves.")
    params: MeltParamsView
    pack: str = Field(description="The rule pack the thresholds come from (name and version).")
    method: str = Field(description="The method card, a path in the repository.")
    caveat: str = Field(description="What a melt peak cannot tell (MIQE 2.0).")
    assays: list[MeltAssayView] = Field(default_factory=list)
    targets: list[MeltTargetView] = Field(default_factory=list)
    calls: list[MeltCallView] = Field(default_factory=list)
    wells: list[MeltWellView] = Field(default_factory=list)
