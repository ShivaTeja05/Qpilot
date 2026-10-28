"""Which options are defensible for THIS study: tiers set by explicit rules and the study's data.

The tier of an option should not be a matter of taste. Three rules use the study itself:

* **Reference sets.** A single gene is common practice (MIQE asks for several validated
  references). A set that contains a gene the group-difference check implicates (the gene is in
  two or more flagged reference pairs) is common practice. If two or more candidates pass a
  geNorm stability cut-off (M below 1.0, the heterogeneous-tissue value), only sets of those
  stable genes are defensible. If none do, as in the neuroblastoma panel, sets of three or more
  unimplicated genes are defensible, and the report says that no candidate is stable.
* **Rank test.** Mann-Whitney is removed when its smallest achievable two-sided p-value at the
  study's group sizes is above alpha (at 3 vs 3 it is 0.1). Keeping it would build "no call" in.
* **The cut-off** defines the question, not the analysis. It is reported separately and held
  at the prespecified value in the defensible view.

A study with technical replicates (:attr:`qsim.data.Study.replicates`) also varies how a
sample's replicate wells are combined (:data:`qsim.decisions.REPLICATES`); a study with one well
per sample and gene does not, so its space is unchanged.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from math import comb

import numpy as np

from qpilot.qpcr.contrast import DEFAULT_RULE
from qpilot.qpcr.quant import log2_matrix
from qpilot.qpcr.refgenes import genorm, group_effect

from qsim.data import Study
from qsim.decisions import Decision, Option, Space, qpcr_space, ref_label, with_replicates

M_STABLE = 1.0


def stability_m(matrix, candidates) -> dict[str, float]:
    """Each control-gene candidate's stability M, as qPilot computes it for this many genes.

    geNorm's M for three or more candidates; with two, the SD of their log2 ratio (the same for
    both); with one, none (qPilot's ``qpcr.study._stability``).
    """
    candidates = list(candidates)
    if len(candidates) >= 3:
        return dict(genorm(matrix, candidates).M_initial)
    if len(candidates) == 2:
        a, b = candidates
        sd = float((matrix[a] - matrix[b]).dropna().std(ddof=1))
        return {a: sd, b: sd}
    return {}


def reference_tiers(study: Study, cut: float = 0.15) -> tuple[dict[str, tuple[str, str]], dict]:
    matrix = log2_matrix(study.curves)
    m_values = stability_m(matrix, study.candidates)
    stable = [g for g in study.candidates if m_values.get(g, 99) < M_STABLE]
    high, rest = study.groups[cut]
    flagged = group_effect(matrix, list(study.candidates), high, rest).flagged
    counts = Counter(g for shift in flagged for g in shift.genes)
    implicated = {g for g, n in counts.items() if n >= 2}
    tiers: dict[str, tuple[str, str]] = {}
    for option in qpcr_space(study.candidates, study.primary_refs).decision("refs").options:
        subset = option.value
        if subset == study.primary_refs:
            tiers[option.id] = ("prespecified", "the prespecified set")
        elif len(subset) == 1:
            tiers[option.id] = ("common_practice", "a single reference gene")
        elif implicated & set(subset):
            genes = ", ".join(sorted(implicated & set(subset)))
            tiers[option.id] = (
                "common_practice",
                f"contains {genes}, which differs between the groups",
            )
        elif len(stable) >= 2:
            ok = set(subset) <= set(stable)
            tiers[option.id] = (
                "defensible" if ok else "common_practice",
                "only geNorm-stable genes" if ok else "includes a gene above geNorm M 1.0",
            )
        else:
            ok = len(subset) >= 3
            tiers[option.id] = (
                "defensible" if ok else "common_practice",
                "three or more genes, none stable" if ok else "two genes, none stable",
            )
    info = {
        "geNorm_M": {g: round(float(v), 3) for g, v in m_values.items()},
        "stable_below_M": M_STABLE,
        "stable_genes": stable,
        "implicated_genes": sorted(implicated),
        "flagged_pairs": ["/".join(s.genes) for s in flagged],
    }
    return tiers, info


def space_for(study: Study) -> tuple[Space, dict]:
    """The decision space with study-specific tiers and validity rules applied."""
    base = qpcr_space(study.candidates, study.primary_refs)
    tiers, info = reference_tiers(study)
    notes: list[str] = []
    if not info["stable_genes"]:
        notes.append(
            "no reference candidate is below geNorm M 1.0; reference choice is a known weakness of this study"
        )
    decisions = []
    for d in base.decisions:
        if d.id == "refs":
            d = replace(d, options=tuple(replace(o, tier=tiers[o.id][0]) for o in d.options))
        if d.id == "test":
            sizes = [study.group_masks(c) for c in study.groups]
            n1 = min(int(h.sum()) for h, _ in sizes)
            n2 = min(int(r.sum()) for _, r in sizes)
            min_p = 2 / comb(n1 + n2, n1)
            if min_p > DEFAULT_RULE.alpha:
                d = replace(d, options=tuple(o for o in d.options if o.id != "mann_whitney"))
                notes.append(
                    f"Mann-Whitney removed: its smallest possible p at {n1} vs {n2} is {min_p:.3g}, above alpha"
                )
        if d.id == "efficiency" and not np.isfinite(study.eff_well).any():
            # a file of Cq values only (qpilot.qpcr.cq_only): no curve, so no well's own efficiency
            d = replace(d, options=tuple(o for o in d.options if o.id != "per_well"))
            notes.append(
                "each well's own efficiency removed: the file has Cq values only (no curves)"
            )
        decisions.append(d)
    space = Space(tuple(decisions), base.baseline, notes=tuple(notes))
    if study.replicates is not None and study.replicates.most >= 3:
        space = with_replicates(space)
    return space, {"reference_tiers": {k: v[1] for k, v in tiers.items()}, **info, "notes": notes}


__all__ = ["Decision", "Option", "ref_label", "reference_tiers", "space_for", "stability_m"]
