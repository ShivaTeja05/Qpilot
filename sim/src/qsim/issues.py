"""The investigation queue: every observation and every sensitive decision, with its consequence.

For each observation the simulator runs a remedy scenario: a data perturbation such as
dropping the wells concerned, or a decision change such as leaving a reference gene out. It
then compares the result with the baseline using the explicit rules in :mod:`qsim.compare`. The
queue is sorted by a lexicographic key, never by a weighted score:

1. it invalidates an output (a control amplified within 5 cycles of most samples);
2. it changes a headline call;
3. it changes any call;
4. the largest move in baseline SEs;
5. how many outputs depend on it (lineage).

Everything stays in the queue, including QC findings with no demonstrated effect.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from qsim.attribution import Factorial
from qsim.compare import IMPACT_ORDER, compare
from qsim.decisions import PLAIN
from qsim.engine import Engine
from qsim.troubleshoot import Observation

HEADLINE = ("ODC1", "BIRC5", "NTRK1", "NM23A")
ACTIONS = {
    "ntc": "Check the melt curve of the control and the wells within 5 cycles; repeat the assay if contamination is confirmed.",
    "well_outlier": "Inspect the amplification curve and the sample's other genes before deciding whether any action is justified.",
    "spatial": "Compare with the plate's run log (sealing, pipetting order); re-run the plate if the pattern is technical.",
    "efficiency": "Review the assay's standard curve and flagged wells; consider the per-well efficiency scenario.",
    "reference_group_effect": "Assess whether this reference gene is stable between the groups before using it.",
    "sample_outlier": "Check RNA integrity and the sample label; confirm identity before final interpretation.",
    "decision": "Decide this choice before looking at results and record the reason (Decision Card).",
}
INVALIDATE_SHARE = 0.5


@dataclass
class Issue:
    issue_id: str
    kind: str
    title: str
    loci: dict
    evidence: dict
    consistent_with: list[str]
    remedy: str
    affected_outputs: list[str]
    impact: str
    changed_calls: list[str]
    headline_changed: list[str]
    max_abs_d_in_se: float
    action: str
    status: str = "new"
    detail: list[dict] = field(default_factory=list)

    def sort_key(self) -> tuple:
        return (
            IMPACT_ORDER.index(self.impact),
            -len(self.headline_changed),
            -len(self.changed_calls),
            -self.max_abs_d_in_se,
            -len(self.affected_outputs),
            self.issue_id,
        )


def _affected(engine: Engine, gene: str) -> list[str]:
    s = engine.study
    if gene in s.primary_refs:
        return list(engine.items)
    if gene == s.marker:
        return ["groups (all comparisons)"]
    return [gene] if gene in engine.items else []


def _drop_mask(engine: Engine, obs: Observation) -> np.ndarray:
    s = engine.study
    mask = np.zeros(s.cq.shape, dtype=bool)
    if obs.kind == "sample_outlier":
        for smp in obs.samples:
            mask[s.samples.index(smp), :] = True
        return mask
    if obs.gene not in s.genes:
        return mask
    g = s.genes.index(obs.gene)
    for smp in obs.samples:
        if smp in s.samples:
            mask[s.samples.index(smp), g] = True
    return mask


def _summarise(
    engine: Engine, table: pd.DataFrame, outputs: list[str]
) -> tuple[str, list[str], list[str], float]:
    sub = table[table["gene"].isin(outputs)] if outputs and outputs[0] in engine.items else table
    worst = min((IMPACT_ORDER.index(i) for i in sub["impact"]), default=len(IMPACT_ORDER) - 1)
    changed = list(sub.loc[sub["call"] != sub["base_call"], "gene"])
    head = [g for g in changed if g in HEADLINE]
    move = float(np.nanmax(np.abs(sub["d_in_se"]))) if len(sub) else 0.0
    return IMPACT_ORDER[worst], changed, head, move


def build_queue(
    engine: Engine, observations: list[Observation], factorial: Factorial | None = None
) -> list[Issue]:
    space = engine.space
    base_cell = space.baseline_index()
    base = engine.evaluate(base_cell)
    issues: list[Issue] = []
    for n, obs in enumerate(observations):
        outputs = (
            _affected(engine, obs.gene) if obs.kind != "sample_outlier" else list(engine.items)
        )
        if obs.kind == "reference_group_effect":
            genes = obs.gene.split("/")
            tables = []
            for gene in genes:
                refs = tuple(r for r in engine.study.primary_refs if r != gene)
                ref_id = "+".join(g.split("(")[0] for g in refs)
                scen = engine.evaluate(space.to_index({"refs": ref_id}))
                tables.append(compare(engine, base, scen).assign(remedy=f"leave {gene} out"))
            table = min(tables, key=lambda t: min(IMPACT_ORDER.index(i) for i in t["impact"]))
            remedy = f"leave one gene of {obs.gene} out of the reference set (worst of both shown)"
            outputs = list(engine.items)
        else:
            mask = _drop_mask(engine, obs)
            if not mask.any():
                table = compare(engine, base, base)
                remedy = "no wells to drop"
            else:
                scen = engine.evaluate(base_cell, drop=mask)
                table = compare(engine, base, scen)
                remedy = f"drop {int(mask.sum())} well(s) and re-run the baseline analysis"
        impact, changed, head, move = _summarise(engine, table, outputs)
        if obs.kind == "ntc" and obs.evidence.get("share_within_5_cycles", 0) >= INVALIDATE_SHARE:
            impact = "invalidates"
        title = {
            "ntc": f"No-template control amplified on {obs.gene}",
            "well_outlier": f"Outlying well {obs.wells[0] if obs.wells else ''} on {obs.gene}",
            "spatial": f"{obs.evidence.get('axis', '')} {obs.evidence.get('position', '')} differs on {obs.gene}",
            "efficiency": f"Low efficiency or many flagged wells on {obs.gene}",
            "reference_group_effect": f"Reference pair {obs.gene} differs between groups",
            "sample_outlier": f"Sample {obs.samples[0] if obs.samples else ''} looks unusual",
        }[obs.kind]
        issues.append(
            Issue(
                issue_id=f"I{n:04d}",
                kind=obs.kind,
                title=title,
                loci={
                    "plate": obs.plate,
                    "gene": obs.gene,
                    "wells": obs.wells[:24],
                    "samples": obs.samples[:24],
                },
                evidence=obs.evidence,
                consistent_with=obs.consistent_with,
                remedy=remedy,
                affected_outputs=outputs,
                impact=impact,
                changed_calls=changed,
                headline_changed=head,
                max_abs_d_in_se=round(move, 3),
                action=ACTIONS[obs.kind],
            )
        )
    if factorial is not None:
        single = factorial.single_flips()
        called = [g for g, c in zip(engine.items, base["call"], strict=True) if c != 0]
        for d in space.names:
            flipped = list(single.index[single[d]])
            if not flipped:
                continue
            head = [g for g in flipped if g in HEADLINE]
            position = space.names.index(d)
            moves = []
            for option in range(len(space.decisions[position].options)):
                if option == base_cell[position]:
                    continue
                cell = list(base_cell)
                cell[position] = option
                table = compare(engine, base, engine.evaluate(tuple(cell)))
                moves.append(float(np.nanmax(np.abs(table["d_in_se"]))))
            issues.append(
                Issue(
                    issue_id=f"D-{d}",
                    kind="decision",
                    title=f"{PLAIN[d][0].upper()}{PLAIN[d][1:]}: changing only this changes {len(flipped)} call(s)",
                    loci={"decision": d},
                    evidence={
                        "genes_flipped_alone": flipped,
                        "called_genes_flipped": [g for g in flipped if g in called],
                    },
                    consistent_with=["analysis sensitivity, not an error"],
                    remedy=f"change only {d} from the baseline (ring 1)",
                    affected_outputs=flipped,
                    impact="changes_conclusion",
                    changed_calls=flipped,
                    headline_changed=head,
                    max_abs_d_in_se=round(max(moves), 3),
                    action=ACTIONS["decision"],
                )
            )
    return sorted(issues, key=Issue.sort_key)


def queue_frame(issues: list[Issue]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "rank": i + 1,
                "id": x.issue_id,
                "kind": x.kind,
                "title": x.title,
                "impact": x.impact,
                "headline_changed": ",".join(x.headline_changed),
                "calls_changed": len(x.changed_calls),
                "max_abs_d_in_se": x.max_abs_d_in_se,
                "outputs_affected": len(x.affected_outputs),
                "action": x.action,
                "status": x.status,
            }
            for i, x in enumerate(issues)
        ]
    )
