"""The Curves stage of a file of Cq values only: the Cq table to confirm (``docs/cq-tables.md``).

A file with no amplification curves has no curve for LinRegPCR to fit or for the Curve Judge to
read, so its curves stage confirms what the file does hold: each sample's Cq per well and plate,
the wells without a Cq, the replicate sets whose Cq spread is wider than expected (the Run
Gate's rule G-REP, evaluated on the same wells with the same numbers, without its consequence
test, which needs the results) and each assay's efficiency (from its dilution series, else
assumed to be 2.0). Blind like the rest of the curves stage: the design's groups are never
read here, so nothing pairs a group with a number; the Cq values themselves wait for the design
to be confirmed, as the plate map's do.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from qpilot.studio_service import Studio
from qpilot.web.contract_cqonly import (
    CqCounts,
    CqEfficiencyView,
    CqSetView,
    CqTableView,
    CqWellView,
)

LATE_CQ = 35.0  # the latest of the Cq cut-offs the grid tests (amp_call cq_le_35)
NEGATIVE = ("ntc", "nac", "ntp", "nrt")
WORDS: dict[str, str] = {
    "with_curves": (
        "This file holds amplification curves: the curves stage checks them (LinRegPCR and the "
        "Curve Judge), so there is no Cq table to confirm."
    ),
    "hidden": (
        "This file has Cq values only. Its Cq table is shown here once the design is confirmed: "
        "which wells are study samples, standards and controls."
    ),
    "shown": (
        "This file has Cq values only, so there is no curve to judge: confirm the Cq table "
        "instead. Each sample's wells are listed with the Cq the file gives them; look at the "
        "wells without a Cq and the replicates whose spread is wider than expected, then "
        "confirm the curves stage."
    ),
    "not_evaluated": "Not evaluated: {why}",
}


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _spread(table: pd.DataFrame, source: Any) -> tuple[dict[tuple[str, str, str], Any], str]:
    """G-REP's findings by (plate, target, sample), and its statement (the shipped pack's)."""
    from qpilot.core.validator import TOKEN
    from qpilot.qpcr.gate_rules import (
        GateContext,
        replicate_spread,
        resolve_pack,
        study_quantities,
    )

    pack = resolve_pack(None)
    rule = pack.rule("G-REP")
    quantities = study_quantities(source) if (table["sample_type"] == "std").any() else {}
    ctx = GateContext(table=table, quantities=quantities)
    found: dict[tuple[str, str, str], Any] = {}
    for finding in replicate_spread(rule, ctx):
        scope = finding.scope
        if "sample" not in scope:
            continue
        text = TOKEN.sub(lambda m: ctx.facts.render(m.group(1)), finding.reason)
        found[(scope["plate"], scope["target"], scope["sample"])] = (finding, text)
    return found, " ".join(str(rule.statement).split())


def _set_flags(role: str, cqs: list[float | None], late: int) -> list[str]:
    n = len(cqs)
    missing = sum(c is None for c in cqs)
    flags = []
    if role in NEGATIVE:
        if missing < n:
            flags.append(
                f"a negative control with a Cq in {n - missing} of {n} well"
                f"{'s' * (n != 1)}: the Run Gate weighs it once the results are shown"
            )
        return flags
    if missing == n:
        flags.append("no Cq in any well: not detected")
    elif missing:
        flags.append(f"{missing} of {n} wells without a Cq (not detected there)")
    if late:
        flags.append(
            f"{late} well{'s' * (late != 1)} with a Cq above {LATE_CQ:g}: the Cq ≤ {LATE_CQ:g} "
            "cut-off would count them as not detected"
        )
    return flags


def cq_table_view(studio: Studio, sid: str) -> CqTableView:
    """The Cq table of a session whose file has Cq values only (see the module docstring)."""
    from qpilot.qpcr import cq_only
    from qpilot.web.studio_views import _designed_table, read_session

    if not studio.cq_only(sid):
        return CqTableView(key=sid, cq_only=False, shown=False, message=WORDS["with_curves"])
    not_applicable = [cq_only.NOT_APPLICABLE[k] for k in ("linregpcr", "curve_judge", "rawness")]
    not_applicable.append(cq_only.NOT_APPLICABLE["melt"])
    _, assembly, stages = read_session(studio, sid)
    design = assembly.design
    shown = bool(stages.get("curves") and stages["curves"].open) and design is not None
    if not shown or design is None:
        return CqTableView(
            key=sid,
            cq_only=True,
            shown=False,
            message=WORDS["hidden"],
            not_applicable=not_applicable,
        )
    table = _designed_table(studio, sid, design)
    if table is None:  # the design does not run on this file: the design page says why
        return CqTableView(
            key=sid,
            cq_only=True,
            shown=False,
            message=WORDS["hidden"],
            not_applicable=not_applicable,
        )
    facts = studio.facts(sid)
    plan = cq_only.efficiency_plan(table, design)
    efficiencies = [
        CqEfficiencyView(
            target=a.target,
            efficiency=a.efficiency,
            source=a.source,
            words=cq_only.efficiency_words(a),
        )
        for a in plan.assays.values()
    ]
    spread, statement = _spread(table, studio.source(sid))
    left_out = set(design.excluded_wells)
    sets: list[CqSetView] = []
    for (run_id, target, sample), rows in table.groupby(["run_id", "target", "sample"], sort=False):
        wells = []
        for _, row in rows.iterrows():
            key = f"{run_id}/{row['well']}"
            cq = _finite(row["cq"])
            out = key in left_out or bool(row.get("design_excluded", False))
            wells.append(
                CqWellView(
                    key=key,
                    well=str(row["well"]),
                    cq=cq,
                    used=cq is not None and not out,
                    left_out=out,
                    file_excluded=str(row.get("excluded") or ""),
                    late=cq is not None and cq > LATE_CQ,
                )
            )
        cqs = [w.cq for w in wells if not w.left_out]
        found = [c for c in cqs if c is not None]
        role = str(rows["sample_type"].iloc[0])
        hit = spread.get((str(run_id), str(target), str(sample)))
        if hit is not None and hit[0].outcome in ("within", "outside"):
            verdict, words = hit[0].outcome, hit[1]
            tolerance = _finite(hit[0].evidence.get("tolerance"))
        else:
            why = hit[1] if hit is not None else _no_spread(role, len(found))
            verdict, words, tolerance = (
                "not_evaluated",
                WORDS["not_evaluated"].format(why=why),
                None,
            )
        flags = _set_flags(role, cqs, sum(w.late for w in wells if not w.left_out))
        if verdict == "outside":
            flags.insert(0, "replicate spread wider than expected (G-REP)")
        sets.append(
            CqSetView(
                run_id=str(run_id),
                sample=str(sample),
                sample_text_id=facts.sample_text_ids.get(str(sample)),
                target=str(target),
                target_text_id=facts.target_text_ids.get(str(target)),
                role=role,
                wells=wells,
                n_wells=len(wells),
                n_with_cq=len(found),
                mean_cq=sum(found) / len(found) if found else None,
                range_cq=max(found) - min(found) if len(found) >= 2 else None,
                tolerance=tolerance,
                spread=verdict,
                spread_words=words,
                flags=flags,
            )
        )
    return CqTableView(
        key=sid,
        cq_only=True,
        shown=True,
        message=WORDS["shown"],
        not_applicable=not_applicable,
        efficiencies=efficiencies,
        counts=_counts(sets),
        sets=sets,
        rule=statement,
    )


def _no_spread(role: str, n_found: int) -> str:
    if role in NEGATIVE:
        return "a negative control has no replicate spread to check."
    if n_found < 2:
        return "fewer than two of its wells have a Cq."
    return "this sample type's replicates are not checked by G-REP."


def _counts(sets: list[CqSetView]) -> CqCounts:
    wells = [w for s in sets for w in s.wells]
    with_cq = sum(w.cq is not None for w in wells)
    study = [w for s in sets if s.role == "unkn" for w in s.wells if not w.left_out]
    controls = [w for s in sets if s.role in NEGATIVE for w in s.wells]
    return CqCounts(
        n_wells=len(wells),
        n_with_cq=with_cq,
        n_without_cq=len(wells) - with_cq,
        n_study_without_cq=sum(w.cq is None for w in study),
        n_sets=len(sets),
        n_outside=sum(s.spread == "outside" for s in sets),
        n_late=sum(w.late for w in wells if not w.left_out),
        n_controls_with_cq=sum(w.cq is not None for w in controls),
    )
