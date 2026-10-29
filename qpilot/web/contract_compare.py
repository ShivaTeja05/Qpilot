"""API contract: a study's comparisons side by side (several comparisons, multiplicity, pairing).

``GET /api/studies/{id}/comparisons`` returns :class:`ComparisonsView`: every comparison of the
study (one for a study without a comparison plan), and per gene each comparison's call, fold
change, 95 % interval, uncorrected and corrected p-value, q-value and how often the call holds.
Every number is the engine's (``StudyResult.comparisons``, or the study's own contrasts for a
study with one comparison, whose q-values are the engine's Benjamini-Hochberg over its genes).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from qpilot.schemas import Conclusion

__all__ = [
    "CardComparison",
    "ComparisonCell",
    "ComparisonGeneRow",
    "ComparisonInfo",
    "ComparisonNote",
    "ComparisonsView",
]


class ComparisonInfo(BaseModel):
    """One comparison of the study: its groups, sizes and how many genes it calls."""

    id: str
    label: str
    group_a: str
    group_b: str
    primary: bool = Field(
        description="The first comparison: listed first everywhere, and the one the audit audits."
    )
    n_a: int = Field(description="Biological units in group A (pairs, when paired).")
    n_b: int = Field(description="Biological units in group B (pairs, when paired).")
    n_pairs: int | None = Field(default=None, description="Complete pairs (paired designs only).")
    n_up: int
    n_down: int
    n_tested: int
    not_tested: dict[str, str] = Field(
        default={}, description="Genes this comparison cannot test, and why."
    )


class ComparisonCell(BaseModel):
    """One gene in one comparison (the engine's numbers at the planned analysis)."""

    conclusion: Conclusion
    fc: float
    log2fc: float
    ci: tuple[float, float]
    p: float = Field(description="Uncorrected p-value of this comparison's test.")
    p_adjusted: float = Field(
        description="The p-value the call uses: Holm-corrected across the gene's comparisons "
        "(equal to p without a correction)."
    )
    q: float = Field(description="Benjamini-Hochberg q-value across the genes of this comparison.")
    n_a: int
    n_b: int
    holds: float | None = Field(default=None, description="Share of the grid with the same call.")
    level: str | None = None
    at_your_choices: Conclusion | None = Field(
        default=None,
        description="The call at the options a person chose on the cards, when they differ "
        "from the planned ones.",
    )


class ComparisonGeneRow(BaseModel):
    """One gene across every comparison (``cells`` in the order of ``comparisons``)."""

    gene: str
    headline: bool
    cells: list[ComparisonCell | None] = Field(
        description="None where that comparison cannot test the gene."
    )
    n_called: int = Field(description="Comparisons in which the gene is called up or down.")
    omnibus_p: float | None = Field(
        default=None,
        description="Welch's one-way ANOVA p across omnibus_groups (orientation, never a call).",
    )
    omnibus_groups_used: int | None = Field(
        default=None,
        description="How many of omnibus_groups the ANOVA used for this gene (a group with "
        "fewer than two values is left out).",
    )
    omnibus_words: str = Field(
        default="", description="When a group was left out: how many, in words; else empty."
    )


class ComparisonNote(BaseModel):
    """A plain-words note on what follows the comparisons, and what shows only the first."""

    kind: Literal["correction", "paired", "primary_only", "not_measured", "q_value", "omnibus"]
    text: str


class ComparisonsView(BaseModel):
    """Every comparison of a study, side by side."""

    study_id: str
    several: bool = Field(description="The study has a comparison plan (several, or paired).")
    test: Literal["welch", "paired_t", "pooled_t"]
    test_words: str
    correction: Literal["holm", "none", "dunnett", "tukey"]
    correction_words: str
    pattern: str
    control: str | None = None
    pair_by: str | None = None
    rule_text: str = Field(description="When a gene is called up or down, in words.")
    comparisons: list[ComparisonInfo]
    genes: list[ComparisonGeneRow]
    notes: list[ComparisonNote] = []
    not_measured: dict[str, str] = Field(
        default={}, description="Gene -> the units it was not measured in (left out of it only)."
    )
    omnibus_groups: list[str] = Field(
        default=[],
        description="The groups of the per-gene Welch ANOVA (three or more, unpaired designs).",
    )


class CardComparison(BaseModel):
    """What one Decision Card's choice does in one comparison of a study with several."""

    id: str
    label: str
    primary: bool
    flips: bool = Field(description="A call of this comparison changes with this choice alone.")
    n_flipped: int = Field(description="How many of its calls change with this choice alone.")
    genes: list[str] = Field(description="The genes whose call changes (this choice alone).")
    flips_elsewhere: bool = Field(
        description="It changes no call here at the planned settings, but does at other ones."
    )
