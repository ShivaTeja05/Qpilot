"""The analysis decisions the simulator varies, their options, and how defensible each option is.

Each decision has a stage (where in the pipeline it acts), a type, and options that carry a tier.

The type follows Del Giudice & Gangestad (2021):

* ``E``: the options are equivalent in principle and may be pooled.
* ``N``: one option is better in principle; the alternatives are reported separately.
* ``U``: it is uncertain which option is better, so the options are explored.

The tier says how defensible an option is:

* ``prespecified``: the baseline analysis.
* ``defensible``: an option a careful analyst could choose.
* ``common_practice``: widely used but known to be weaker (a single reference gene,
  efficiency assumed to be 100 %, Cq = 40 substituted for non-detects). It is shown as a
  reference point and kept out of the "defensible" summaries.

The baseline is qPilot's prespecified analysis, so the simulator reproduces qPilot's numbers
exactly at the baseline cell (tested).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Literal

Tier = Literal["prespecified", "defensible", "common_practice"]
PLAIN = {
    "efficiency": "the efficiency model",
    "flagged": "how flagged wells are handled",
    "late_cq": "the late-Cq cut-off",
    "nondetect": "how non-detects are handled",
    "replicates": "how replicate wells are combined",
    "refs": "the reference genes",
    "cut": "the group cut-off",
    "test": "the statistical test",
    "multiplicity": "the multiple-testing correction",
}
Kind = Literal["E", "N", "U"]


@dataclass(frozen=True)
class Option:
    id: str
    value: Any
    tier: Tier
    label: str


@dataclass(frozen=True)
class Decision:
    id: str
    stage: str
    kind: Kind
    question: str
    options: tuple[Option, ...]
    sources: tuple[str, ...] = ()
    role: Literal["analysis", "question"] = "analysis"

    @property
    def ids(self) -> list[str]:
        return [o.id for o in self.options]

    def index(self, option_id: str) -> int:
        try:
            return self.ids.index(option_id)
        except ValueError:
            raise KeyError(
                f"{self.id}: unknown option {option_id!r}; choose from {self.ids}"
            ) from None


@dataclass(frozen=True)
class Space:
    """An ordered list of decisions plus the baseline option of each."""

    decisions: tuple[Decision, ...]
    baseline: dict[str, str] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def names(self) -> list[str]:
        return [d.id for d in self.decisions]

    @property
    def levels(self) -> list[int]:
        return [len(d.options) for d in self.decisions]

    def decision(self, name: str) -> Decision:
        for d in self.decisions:
            if d.id == name:
                return d
        raise KeyError(f"unknown decision {name!r}; choose from {self.names}")

    def baseline_index(self) -> tuple[int, ...]:
        return tuple(d.index(self.baseline[d.id]) for d in self.decisions)

    def to_index(self, assignment: dict[str, str]) -> tuple[int, ...]:
        unknown = set(assignment) - set(self.names)
        if unknown:
            raise KeyError(f"unknown decisions {sorted(unknown)}; choose from {self.names}")
        full = {**self.baseline, **assignment}
        return tuple(d.index(full[d.id]) for d in self.decisions)

    def to_assignment(self, index: tuple[int, ...]) -> dict[str, str]:
        return {d.id: d.options[i].id for d, i in zip(self.decisions, index, strict=True)}

    def option(self, index: tuple[int, ...], name: str) -> Option:
        position = self.names.index(name)
        return self.decisions[position].options[index[position]]

    def tier(self, index: tuple[int, ...]) -> Tier:
        """The weakest tier among a cell's options."""
        tiers = {o.tier for d, i in zip(self.decisions, index, strict=True) for o in [d.options[i]]}
        if "common_practice" in tiers:
            return "common_practice"
        if "defensible" in tiers:
            return "defensible"
        return "prespecified"


#: Only in a study with technical replicates (several wells per sample and gene); it joins the
#: matrix stage after the non-detect rule. The mean is qPilot's rule (``qpcr/quant.py``).
REPLICATES = Decision(
    "replicates",
    "matrix",
    "U",
    "How are a sample's replicate wells combined into one value?",
    (
        Option("mean", "mean", "prespecified", "the mean of the replicate wells"),
        Option("median", "median", "defensible", "the middle replicate well (the median)"),
        Option(
            "drop_outlier",
            "outlier",
            "defensible",
            "leave out a well outside the expected replicate spread, then the mean",
        ),
    ),
    ("Ruiz-Villalba et al. 2021 Life (replicate Cq spread; qPilot's G-REP rule)",),
)


def with_replicates(space: Space) -> Space:
    """``space`` with the :data:`REPLICATES` decision after the other matrix-stage decisions."""
    if "replicates" in space.names:
        return space
    decisions = list(space.decisions)
    at = next(i for i, d in enumerate(decisions) if d.stage != "matrix")
    decisions.insert(at, REPLICATES)
    return Space(tuple(decisions), {**space.baseline, "replicates": "mean"}, notes=space.notes)


def ref_label(subset: tuple[str, ...]) -> str:
    return "+".join(g.split("(")[0] for g in subset)


def qpcr_space(candidates: tuple[str, ...], primary_refs: tuple[str, ...]) -> Space:
    """The qPCR decisions the simulator varies for a two-group relative-expression study."""
    subsets = [s for k in range(1, len(candidates) + 1) for s in combinations(candidates, k)]
    ref_options = tuple(
        Option(
            id=ref_label(s),
            value=s,
            tier=(
                "prespecified"
                if s == primary_refs
                else "common_practice"
                if len(s) == 1
                else "defensible"
            ),
            label=f"normalise to {len(s)} reference gene{'s' if len(s) > 1 else ''}: {ref_label(s)}",
        )
        for s in subsets
    )
    decisions = (
        Decision(
            "efficiency",
            "matrix",
            "N",
            "Which amplification efficiency turns Cq into quantity?",
            (
                Option(
                    "assay_mean", "assay", "prespecified", "LinRegPCR mean efficiency per assay"
                ),
                Option(
                    "std_curve",
                    "std",
                    "defensible",
                    "standard-curve slope of the plate's dilution series",
                ),
                # demoted on evidence: 89 % median error against known dilution ratios (qsim validate)
                Option("per_well", "well", "common_practice", "each well's own efficiency"),
                Option(
                    "assume_100", "fixed2", "common_practice", "assume 100 % (the ddCq shortcut)"
                ),
            ),
            ("Ruijter et al. 2009 NAR", "Bustin & Wittwer, Clin Chem"),
        ),
        Decision(
            "flagged",
            "matrix",
            "U",
            "What happens to wells LinRegPCR flagged?",
            (
                Option("keep", "keep", "prespecified", "keep every quantified well"),
                Option("drop_eff", "eff", "defensible", "drop efficiency-outlier wells"),
                Option(
                    "drop_eff_low", "eff_low", "common_practice", "also drop wells below 10 copies"
                ),
            ),
            ("Ruijter et al. 2009 NAR (LinRegPCR exclusion rules)",),
        ),
        Decision(
            "late_cq",
            "matrix",
            "U",
            "Are very late Cq values treated as not detected?",
            (
                Option("none", None, "prespecified", "keep every Cq"),
                Option("cq35", 35.0, "defensible", "Cq above 35 counts as not detected"),
                Option("cq38", 38.0, "defensible", "Cq above 38 counts as not detected"),
            ),
            ("de Ronde et al. 2017 RNA (critical Cq of 35)",),
        ),
        Decision(
            "nondetect",
            "matrix",
            "N",
            "What happens to wells that never amplified?",
            (
                Option("drop", "drop", "prespecified", "leave them out"),
                Option("cap_min", "cap", "defensible", "set to the lowest amount detected"),
                Option("cq40", "cq40", "common_practice", "substitute Cq = 40"),
            ),
            ("McCall et al. 2014 Bioinformatics (non-detects are not missing at random)",),
        ),
        Decision(
            "refs",
            "normalise",
            "U",
            "Which reference genes is each sample divided by?",
            ref_options,
            ("Vandesompele et al. 2002 Genome Biology (geNorm)",),
        ),
        Decision(
            "cut",
            "groups",
            "U",
            "Where is the MYCN-high group cut?",
            (
                Option("top10", 0.10, "defensible", "top 10 % by MYCN expression"),
                Option("top15", 0.15, "prespecified", "top 15 % by MYCN expression"),
                Option("top20", 0.20, "defensible", "top 20 % by MYCN expression"),
            ),
            role="question",
        ),
        Decision(
            "test",
            "test",
            "U",
            "Which two-group test gives the p-value?",
            (
                Option("welch", "welch", "prespecified", "Welch t-test"),
                Option("student", "student", "defensible", "Student t-test (equal variances)"),
                Option("mann_whitney", "mwu", "defensible", "Mann-Whitney U (rank test)"),
            ),
        ),
        Decision(
            "multiplicity",
            "conclude",
            "N",
            "Is the p-value corrected for testing many genes?",
            (
                Option("none", "none", "prespecified", "no correction"),
                Option("bh", "bh", "defensible", "Benjamini-Hochberg false discovery rate"),
                Option("holm", "holm", "defensible", "Holm family-wise error rate"),
            ),
            role="question",  # a claim rule (which error rate to control), reported separately
        ),
    )
    baseline = {
        "efficiency": "assay_mean",
        "flagged": "keep",
        "late_cq": "none",
        "nondetect": "drop",
        "refs": ref_label(primary_refs),
        "cut": "top15",
        "test": "welch",
        "multiplicity": "none",
    }
    return Space(decisions, baseline)
