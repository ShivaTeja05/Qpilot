"""The K. phaffii study (corpus ``rdml/linregpcr-rdml-1.3-lc480-kphaffii``) as designs for tests.

Büchner, Ludwig, Kerpes & Becker 2025 (Microbial Cell Factories; CC BY 4.0): eight cultivation
conditions in three biological replicates each (``20_1`` … ``P25A_3``), four UPR genes and two
reference genes (ACT1, TFC1), one gene per plate, every sample in triplicate wells.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from qpilot.schemas_studio import Comparison, ComparisonPlan, SampleDesign, StudyDesign

FILE = (
    Path(__file__).resolve().parents[1]
    / "fixtures/corpus/rdml/linregpcr-rdml-1.3-lc480-kphaffii/12934_2025_2809_MOESM5_ESM.rdml"
)
EXPERIMENT = "202502_K_phaffii"
REFS = ("ACT1", "TFC1")
CONDITIONS = ("20", "28", "D20", "D28", "S1", "S3", "S4", "P25A")
SAMPLES = tuple(f"{c}_{i}" for c in CONDITIONS for i in (1, 2, 3))


def condition(sample: str) -> str:
    """``D20_2`` -> ``D20``."""
    return sample.rsplit("_", 1)[0]


def groups(names: Sequence[str]) -> dict[str, list[str]]:
    """Group label -> its samples."""
    return {g: [s for s in SAMPLES if condition(s) == g] for g in names}


def two_groups(a: str, b: str) -> StudyDesign:
    """``a`` against ``b``, no plan."""
    samples = {
        s: SampleDesign(sample=s, group=condition(s)) for s in SAMPLES if condition(s) in (a, b)
    }
    return StudyDesign(
        experiment_id=EXPERIMENT,
        mode="groups",
        comparison=Comparison(group_a=a, group_b=b),
        samples=samples,
        reference_candidates=REFS,
        headline=("HAC1i",),
    )


def plan_design(
    names: Sequence[str],
    pattern: str,
    control: str | None = None,
    correction: str = "holm",
    paired: bool = False,
) -> StudyDesign:
    """A plan over ``names``: each against ``control`` (``vs_control``) or every pair.

    ``paired`` pairs the samples by their replicate number (``_1``, ``_2``, ``_3``): an
    arithmetic check of the paired test, not a claim about how the cultures were run.
    """
    samples = {
        s: SampleDesign(sample=s, group=condition(s), pair=s.rsplit("_", 1)[1] if paired else None)
        for s in SAMPLES
        if condition(s) in names
    }
    if pattern == "vs_control":
        comps = tuple(Comparison(group_a=g, group_b=control) for g in names if g != control)
    else:
        comps = tuple(
            Comparison(group_a=a, group_b=b) for i, a in enumerate(names) for b in names[i + 1 :]
        )
    plan = ComparisonPlan(
        pattern=pattern,  # type: ignore[arg-type]
        control=control,
        comparisons=comps,
        correction=correction,  # type: ignore[arg-type]
        pair_by="replicate" if paired else None,
    )
    return StudyDesign(
        experiment_id=EXPERIMENT,
        mode="groups",
        comparison=comps[0],
        samples=samples,
        reference_candidates=REFS,
        headline=("HAC1i",),
        comparisons=plan,
    )
