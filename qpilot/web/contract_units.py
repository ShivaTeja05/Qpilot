"""Each biological unit's value of one gene, from the engine (the Gene section's "Your samples").

``GET /api/studies/{id}/genes/{gene}/units``: per biological unit, the gene's relative amount
(``log2`` of the gene over the mean of the control genes, the engine's own normalisation,
efficiency-corrected from the curves) at the study's planned analysis, with every well behind it
(its technical replicates); per group the mean and its 95 % confidence interval; and the fold
change between the groups, which is the study's stored result for the gene.

Positions (``x``, ``mean``, ``ci``) are log2 and relative to the second group's mean, as on the
audit's sample chart, so the second group's mean is 0. A number the engine cannot compute is
``null``. Names come from the study's file and are shown as text.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

GroupKey = Literal["high", "rest"]
"""``high`` is the first group of the comparison, ``rest`` the second (the audit's keys)."""

WellState = Literal["used", "no_value", "excluded"]


class UnitWell(BaseModel):
    """One well behind a unit's value (one technical replicate)."""

    plate: str = Field(description="The well's run (plate) id in the file.")
    well: str
    sample: str = Field(description="The sample the well belongs to (a unit may have several).")
    cq: str | None = Field(description="The well's Cq, to one decimal; null when it has none.")
    cq_value: float | None = Field(description="The well's Cq, unrounded.")
    x: float | None = Field(
        description="The well's relative amount (log2, the unit's control-gene mean removed), "
        "relative to the second group's mean; null when the well has no value."
    )
    value: str | None = Field(description='``x`` in words ("1.9× higher").')
    state: WellState = Field(
        description="``used`` in the unit's value; ``no_value``: the well never gave a usable "
        "curve (undetermined); ``excluded``: a person left it out."
    )
    late: bool = Field(description="Cq above the late line (``late_cut``).")
    flagged: bool = Field(description="LinRegPCR flagged the well (efficiency or very low copy).")


class UnitPoint(BaseModel):
    """One biological unit: its value of the gene and the wells behind it."""

    unit: str
    group: GroupKey
    samples: list[str] = Field(
        description="The samples of this unit (one, or several preparations)."
    )
    x: float = Field(
        description="The unit's relative amount (log2), relative to the second "
        "group's mean: the mean of its used wells."
    )
    value: str = Field(description="``x`` in words.")
    capped: bool = Field(
        description="Every well was undetermined and the planned analysis sets the value to the "
        "lowest amount detected for the gene."
    )
    n_wells: int = Field(description="Wells used in the value.")
    cq_range: float | None = Field(
        description="Highest minus lowest Cq of the used wells (cycles); null with one well."
    )
    wells: list[UnitWell]


class UnitGroup(BaseModel):
    """One group: its label, its units with a value, those without, and its mean with CI."""

    label: str
    n: int = Field(description="Biological units with a value (the n of the comparison).")
    missing: int = Field(description="Units of the group without a value for this gene.")
    mean: float | None
    ci: tuple[float, float] | None = Field(
        description="95 % confidence interval of the mean (t, n - 1 degrees of freedom); null "
        "with fewer than two units."
    )
    mean_text: str | None = None
    ci_text: str | None = None


class UnitGroups(BaseModel):
    """The two groups (``high`` is the first group, ``rest`` the second)."""

    high: UnitGroup
    rest: UnitGroup


class UnitValues(BaseModel):
    """One gene's biological units, as the engine computed them."""

    study_id: str
    gene: str
    points: list[UnitPoint]
    groups: UnitGroups
    fold: str = Field(description="The fold change between the group means, in words.")
    fold_log2: float | None
    fold_ci: tuple[float, float] | None = Field(
        description="The stored result's 95 % CI of the fold change (log2)."
    )
    fold_ci_text: str | None = None
    p: float | None
    refs: list[str] = Field(description="The control genes each unit is divided by.")
    undetermined: Literal["drop", "cap"] = Field(
        description="The planned rule for a unit whose wells are all undetermined."
    )
    replicates: bool = Field(description="Some unit has more than one well for this gene.")
    most_wells: int = Field(description="The most wells behind one unit's value.")
    late_cut: str
    at_plan: bool = Field(
        description="The Decision Cards are at the planned options (else the Prism export, "
        "which follows the cards, differs from these values)."
    )
    how: list[str] = Field(description="How the values were computed, in plain sentences.")
    line_log2: float = Field(description="The fold change a call needs (log2).")
    line: str
