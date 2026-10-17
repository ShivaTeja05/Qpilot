"""The seven qPCR checks behind a gene's confidence grade (owned by Dev 2).

Pure functions over ``qpilot.schemas`` (plus the standard library); they import nothing else from
``qpilot.qpcr`` or ``qpilot.core``. Only ``precision``, ``robustness`` and ``normalisation`` can
downgrade (see ``qpilot.core.confidence``); the others are reported so the reader sees them.

1. precision: fails when the 95 % CI does not lie wholly beyond a 2-fold line.
2. robustness: fails when the conclusion holds in fewer than 80 % of the grid's analyses.
3. fragility: the fewest choices that flip the conclusion (reported, not double-counted).
4. normalisation: passes only if at least two reference genes are below the commonly used geNorm
   cut-off (M 1.5; later geNorm/qbase+ guidance, not the 2002 paper's 0.7) and some V(n/n+1)
   is below 0.15.
5. assay: per-target efficiency, undetermined wells, LOD/LOQ not determined (reported).
6. design sensitivity: the minimum detectable effect at 80 % power from the observed standard
   error, never post-hoc power; groups derived from the data are noted (reported).
7. reporting: MIQE 2.0 items that the Analysis Record can answer (a list, never a "score").
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from statistics import NormalDist

from qpilot.schemas import Check, ContrastResult, Level, StudyResult

START_LEVEL: Level = "High"
HOLDS_MIN = 0.80
TWO_FOLD = 2.0

MIQE_ITEMS_FROM_RECORD = (
    "Raw fluorescence data provided (RDML)",
    "Cq / quantification method and software version",
    "PCR efficiency per assay (from the amplification curves)",
    "Reference genes used and how many",
    "Reference gene stability (geNorm M and V)",
    "Normalisation method",
    "Handling of undetermined (no-amplification) wells",
    "Number of samples per group",
    "Statistical method and conclusion rule",
    "Analysis choices and who made them (decision log)",
)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _z_sum(alpha: float = 0.05, power: float = 0.80) -> float:
    nd = NormalDist()
    return nd.inv_cdf(1 - alpha / 2) + nd.inv_cdf(power)


def standard_error(contrast: ContrastResult) -> float:
    """SE of the log2 fold change, from the t statistic (or the CI when t is zero)."""
    if contrast.t:
        return abs(contrast.log2fc / contrast.t)
    lo, hi = contrast.ci
    return (math.log2(hi) - math.log2(lo)) / (2 * NormalDist().inv_cdf(0.975))


def mde_fold(contrast: ContrastResult, alpha: float = 0.05, power: float = 0.80) -> float:
    """Smallest fold change this design detects with the given power: 2^((z+z)·SE)."""
    return 2.0 ** (_z_sum(alpha, power) * standard_error(contrast))


def precision_passes(contrast: ContrastResult) -> bool:
    """True when the whole 95 % CI lies beyond the 2-fold line (above 2 or below 1/2)."""
    lo, hi = contrast.ci
    return lo >= TWO_FOLD or hi <= 1 / TWO_FOLD


def normalisation_passes(result: StudyResult) -> bool:
    """At least two references below the M cut-off and some V(n/n+1) below the V cut-off."""
    g = result.genorm
    stable = [r for r, m in g.M_initial.items() if m < g.cutoff_M]
    return len(stable) >= 2 and any(v < g.cutoff_V for v in g.V.values())


def checks_for(
    gene: str, result: StudyResult, grid: Mapping[str, int] | None = None
) -> list[Check]:
    """The seven checks for one gene.

    Args:
        gene: the item, e.g. ``"ODC1"``.
        result: the study (contrasts, robustness, geNorm, efficiency).
        grid: fragility per gene, i.e. ``core.robustness.fragility(grid_df, space)``; when
            omitted, fragility is reported as unknown.
    """
    contrast = result.contrasts[gene]
    robust = result.robustness[gene]
    s = _slug(gene)
    flips = None if grid is None else int(grid[gene])
    refs_ok = normalisation_passes(result)
    precise = precision_passes(contrast)
    holds_ok = robust.holds >= HOLDS_MIN
    if flips is None:
        fragility_note = "Fragility not computed."
    elif flips == 0:
        fragility_note = "No combination of the reasonable choices flips this conclusion."
    else:
        word = "choice" if flips == 1 else "choices"
        fragility_note = f"Changing {flips} {word} at once can flip this conclusion."
    return [
        Check(
            id="precision",
            passed=precise,
            note="The 95 % confidence interval clears the 2-fold line."
            if precise
            else "The 95 % confidence interval crosses the 2-fold line.",
            fact_ids=[f"f_ci_lo_{s}_recommended", f"f_ci_hi_{s}_recommended"],
        ),
        Check(
            id="robustness",
            passed=holds_ok,
            note="The conclusion holds in at least 80 % of the reasonable analyses."
            if holds_ok
            else "The conclusion holds in fewer than 80 % of the reasonable analyses.",
            fact_ids=[f"f_holds_{s}"],
        ),
        Check(
            id="fragility",
            passed=flips == 0,
            note=fragility_note,
            fact_ids=[f"f_min_flip_{s}"],
        ),
        Check(
            id="normalisation",
            passed=refs_ok,
            note="At least two control genes are stable by geNorm."
            if refs_ok
            else "No control gene on this panel is below the commonly used geNorm "
            "stability cut-off (M 1.5).",
            fact_ids=[f"f_m_{_slug(r)}" for r in sorted(result.genorm.M_initial)],
        ),
        Check(
            id="assay",
            passed=True,
            note="Per-well efficiency from LinRegPCR; undetermined wells reported; "
            "LOD/LOQ not determined.",
            fact_ids=[f"f_eff_{s}", "f_pct_undetermined"],
        ),
        Check(
            id="design_sensitivity",
            passed=True,
            note=f"Groups are derived from the data ({result.design.group_var}); "
            "minimum detectable effect reported.",
            fact_ids=[f"f_mde_fold_{s}", "f_n_hi", "f_n_lo"],
        ),
        Check(
            id="reporting",
            passed=True,
            note="MIQE 2.0 items answerable from the record are listed with the record.",
            fact_ids=[],
        ),
    ]


def upgrade_rule(contrast: ContrastResult, holds: float):
    """The one upgrade: fold change at least 4, holds everywhere, CI clear of 2-fold."""

    def rule(checks: list[Check]) -> bool:
        by_id = {c.id: c for c in checks}
        big = contrast.fc >= 4 or contrast.fc <= 0.25
        return big and holds == 1.0 and by_id["precision"].passed and by_id["normalisation"].passed

    return rule
