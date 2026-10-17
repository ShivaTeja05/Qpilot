"""The two groups the demo study compares, defined once and then held fixed.

The demo dataset has no treatment groups, so the comparison is defined from the data: tumours
whose MYCN expression (a known neuroblastoma driver) is in the top ``cut`` fraction are
"MYCN-high", the rest are the comparison group. Groups are computed **once**, from the primary
control-gene set, and never re-derived when a different control set is tried; that is what lets
the app say truthfully "same samples, same groups, only the control gene changed".

This is an expression-defined grouping, not a clinical MYCN-amplification call, and every output
says so.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd

from qpilot.qpcr.curves import REFERENCE_TARGETS
from qpilot.qpcr.quant import relative
from qpilot.schemas import DesignSummary

DEMO_MARKER = "MYCN(4)"
DEMO_GROUP_VAR = "MYCN_high"
GROUP_NOTE = "expression-defined (top fraction by MYCN expression), not a clinical call"


@dataclass(frozen=True)
class GroupSpec:
    """How to split samples: the marker gene, the top fraction, the control genes used for it."""

    marker: str = DEMO_MARKER
    cut: float = 0.15
    refs_primary: tuple[str, ...] = REFERENCE_TARGETS
    group_var: str = DEMO_GROUP_VAR

    def __post_init__(self) -> None:
        if not 0 < self.cut < 1:
            raise ValueError(f"cut must be between 0 and 1, not {self.cut}")


def marker_groups(matrix: pd.DataFrame, spec: GroupSpec) -> tuple[frozenset[str], frozenset[str]]:
    """Split samples into (high, rest) by the marker's relative expression.

    The threshold is the value at position ``int((1 - cut) * n)`` of the sorted relative
    expressions, exactly as the validation oracle computes it; samples at or above it are high.
    """
    marker = relative(matrix, spec.marker, spec.refs_primary, "drop")
    if marker.empty:
        raise ValueError(f"no sample has {spec.marker!r} and all control genes measured")
    ordered = marker.sort_values(kind="mergesort").to_numpy()
    threshold = ordered[int((1 - spec.cut) * len(ordered))]
    high = frozenset(marker.index[marker >= threshold])
    return high, frozenset(marker.index) - high


def design_summary(high: frozenset[str], rest: frozenset[str], spec: GroupSpec) -> DesignSummary:
    """Describe the grouping for results, cards and the app header."""
    return DesignSummary(
        group_var=spec.group_var,
        cut=spec.cut,
        n_hi=len(high),
        n_lo=len(rest),
        note=GROUP_NOTE,
        refs_primary=tuple(spec.refs_primary),
    )


def groups_by_cut(
    matrix: pd.DataFrame, spec: GroupSpec, cuts: Sequence[float]
) -> dict[float, tuple[frozenset[str], frozenset[str]]]:
    """Groups for several cut-offs, all from the primary control genes (for the robustness grid)."""
    return {
        cut: marker_groups(
            matrix,
            GroupSpec(spec.marker, cut, spec.refs_primary, spec.group_var),
        )
        for cut in cuts
    }
