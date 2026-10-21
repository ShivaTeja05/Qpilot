"""A Trace set-aside card built by hand, shaped as the trace engine builds it, for store tests.

The card follows BUILD-DESIGN §2.2: kind ``trace_set_aside``, options keep /
read_from_other_refs / set_aside, and every option carries a ``ContrastResult`` for each of the
study's genes (58 on the fixture study). Setting the tumour aside moves CAMTA2 and IGSF4 past
the 2-fold line (no call -> down), as the plan's CAMTA2 example does; reading the well from the
other references moves CAMTA2 alone.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from qpilot.schemas import CardOption, ContrastResult, DecisionCard, StudyResult

ALPHA = 0.05
MIN_LOG2FC = 1.0


def shifted(result: ContrastResult, delta: float, drop_lo: int = 0) -> ContrastResult:
    """One gene's result with its log2 fold change moved by ``delta`` (CI moved with it)."""
    log2fc = result.log2fc + delta
    low, high = result.ci
    if result.p < ALPHA and abs(log2fc) >= MIN_LOG2FC:
        conclusion = "up" if log2fc > 0 else "down"
    else:
        conclusion = "none"
    return result.model_copy(
        update={
            "log2fc": log2fc,
            "fc": 2.0**log2fc,
            "ci": (low * 2.0**delta, high * 2.0**delta),
            "n_lo": result.n_lo - drop_lo,
            "conclusion": conclusion,
        }
    )


def trace_card(
    result: StudyResult,
    card_id: str = "card_trace_camta2_1",
    *,
    flips: bool = True,
    sample: str = "2016",
) -> DecisionCard:
    """A set-aside card for one place to look; ``flips=False`` gives one that changes nothing."""
    keep = dict(result.contrasts)
    move = {"CAMTA2": -0.05, "IGSF4": -0.05} if flips else {}
    set_aside = {g: shifted(c, move.get(g, 0.0001), drop_lo=1) for g, c in keep.items()}
    refs = {g: shifted(c, -0.03 if flips and g == "CAMTA2" else 0.0) for g, c in keep.items()}
    changed = sorted(g for g in keep if set_aside[g].conclusion != keep[g].conclusion)
    deltas = [abs(set_aside[g].log2fc - keep[g].log2fc) for g in keep]
    impact = {
        "flips": bool(changed),
        "n_genes_flipped": len(changed),
        "max_delta_log2fc": max(deltas),
        "flips_anywhere": bool(changed),
        "n_genes_flipped_anywhere": len(changed),
    }
    return DecisionCard(
        id=card_id,
        kind="trace_set_aside",
        rank=1,
        impact=impact,
        evidence={
            "root": {"kind": "gene", "id": "CAMTA2"},
            "sample": sample,
            "plate": "HMBS_20080318",
            "well": "K22",
            "checks": ["S1"],
            "feeds": len(keep),
            "pull_log2": 2.47,
            "consequence": "changes_call" if changed else "changes_nothing",
            "changed_calls": changed,
        },
        options=[
            CardOption(id="keep", label="Keep the well", per_gene=keep),
            CardOption(
                id="read_from_other_refs",
                label="Read this well from the other references",
                per_gene=refs,
            ),
            CardOption(id="set_aside", label="Set the tumour aside", per_gene=set_aside),
        ],
        recommended="keep",
        rationale_template="trace_v1",
        facts=[],
    )


def sha(path: Path) -> str:
    """sha256 of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()
