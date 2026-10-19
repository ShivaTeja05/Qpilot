"""Summary, per-gene table, decision log, integrity and the optional sections.

Each builder reads the record through :class:`~qpilot.report.context.Ctx` and returns report
data (:mod:`qpilot.report.model`); none of them computes a new statistic. A gene's "rests on"
is read from ``results.json`` (the dimensions whose change alone flips its conclusion); its
confidence reasons are the engine's checks, re-worded with fact tokens.
"""

from __future__ import annotations

from collections import Counter

from qpilot.report.context import Ctx, dim_label
from qpilot.report.model import (
    Decision,
    Decisions,
    GeneRow,
    Integrity,
    Optional_,
    Reason,
)
from qpilot.report.text import ProseError, Text, safe_slug, tok

NOT_IN_RECORD = "not available in this record"
#: Optional record members another part of qPilot writes, and what the section is called.
OPTIONAL_MEMBERS = {
    "gate": (("gate.json", "rule_evals.json"), "Run Gate: what the controls on each plate mean"),
    "trust": (("trust.json",), "Import Trust Card: are the curves raw?"),
    "labels": (("labels.json",), "Honest-number labels: n, prediction interval, claim floor"),
    "trace": (("trace.json",), "Wells to look at"),
}


# ---------- summary ----------


def summary(ctx: Ctx) -> tuple[Text, list[tuple[str, str]]]:
    """The study in two sentences, and the key numbers as (label, fact id)."""
    f = ctx.facts
    parts = []
    if ctx.has("f_n_plates", "f_n_samples", "f_n_reactions"):
        parts.append(
            f"{tok('f_n_plates')} plates, {tok('f_n_samples')} samples, "
            f"{tok('f_n_reactions')} reactions."
        )
    if ctx.has("f_n_hi", "f_n_lo"):
        parts.append(
            f"Compared: {tok(ctx.group_a)} ({tok('f_n_hi')} biological units) with "
            f"{tok(ctx.group_b)} ({tok('f_n_lo')})."
        )
    if ctx.has("f_n_cells", "f_n_genes", "f_n_hold_lt_80"):
        parts.append(
            f"Every conclusion was recomputed under {tok('f_n_cells')} reasonable analyses; "
            f"{tok('f_n_hold_lt_80')} of {tok('f_n_genes')} genes keep their conclusion in "
            "fewer than four out of five of them."
        )
    calls = Counter(c.conclusion for c in ctx.result.contrasts.values())
    if calls:
        path = "results.json:contrasts.*.conclusion"
        parts.append(
            f"At the primary analysis {ctx.count('n_up', calls['up'], path)} genes are up, "
            f"{ctx.count('n_down', calls['down'], path)} down and "
            f"{ctx.count('n_none', calls['none'], path)} have no call."
        )
    text = ctx.t(" ".join(parts) or "This record holds no study counts.")
    keys = [
        ("plates", "f_n_plates"),
        ("samples", "f_n_samples"),
        ("reactions", "f_n_reactions"),
        ("genes", "f_n_genes"),
        ("analyses per gene", "f_n_cells"),
    ]
    found = [(label, fid) for label, fid in keys if fid in f]
    for _, fid in found:
        f.cited.add(fid)
    return text, found


# ---------- genes ----------


def _reason(ctx: Ctx, gene: str, check: dict) -> Reason:
    """One engine check in fact-bound words (the engine's own note when it has no digits)."""
    s = safe_slug(gene)
    cid, passed = str(check.get("id", "")), bool(check.get("passed"))
    lo, hi = f"f_ci_lo_{s}_recommended", f"f_ci_hi_{s}_recommended"
    words = None
    if cid == "precision" and ctx.has(lo, hi):
        verb = "clears" if passed else "crosses"
        words = f"The 95 % confidence interval {tok(lo)} to {tok(hi)} {verb} the 2-fold line."
    elif cid == "robustness" and ctx.has(f"f_holds_{s}", "f_n_cells"):
        words = f"The conclusion holds in {tok(f'f_holds_{s}')} of {tok('f_n_cells')} analyses"
        words += "." if passed else ", fewer than four out of five."
    elif cid == "fragility" and ctx.has(f"f_min_flip_{s}"):
        flips = int(ctx.facts.value(f"f_min_flip_{s}", 0) or 0)
        if flips == 0:
            words = "No combination of the reasonable choices flips it."
        elif flips == 1:
            words = "Changing a single choice can flip it."
        else:
            words = f"Changing {tok(f'f_min_flip_{s}')} choices at once can flip it."
    elif cid == "normalisation":
        cutoff = ctx.facts.derive(
            "genorm_cutoff_m",
            float(ctx.result.genorm.cutoff_M),
            "{:g}",
            path="results.json:genorm.cutoff_M",
        )
        if passed:
            words = f"A control gene reaches geNorm's usual stability cut-off (M {tok(cutoff)})."
        else:
            words = f"No control gene reaches geNorm's usual stability cut-off (M {tok(cutoff)})."
    elif cid == "assay" and ctx.has(f"f_eff_{s}"):
        words = f"Efficiency measured per well by LinRegPCR (assay mean {tok(f'f_eff_{s}')})"
        if ctx.has("f_pct_undetermined"):
            words += f"; {tok('f_pct_undetermined')} of study wells without a quantity"
        words += "; limits of detection not determined."
    elif cid == "design_sensitivity" and ctx.has(f"f_mde_fold_{s}"):
        words = f"The smallest change this design detects reliably is {tok(f'f_mde_fold_{s}')}."
    if words is None:
        note = str(check.get("note", ""))
        try:
            return Reason(check=cid, passed=passed, text=ctx.t(note))
        except ProseError:
            state = "passed" if passed else "not passed"
            words = f"Check {cid.replace('_', ' ')}: {state} (details in the record)."
    return Reason(check=cid, passed=passed, text=ctx.t(words))


def _rests_on(ctx: Ctx, gene: str) -> tuple[list[str], Text | None]:
    robust = ctx.result.robustness.get(gene)
    if robust is None:
        return [], None
    flips = sorted(d for d, v in robust.impact.items() if isinstance(v, dict) and v.get("flips"))
    s = safe_slug(gene)
    if flips:
        words = "Changing " + " or ".join(dim_label(d) for d in flips) + " alone flips it."
    elif ctx.has(f"f_min_flip_{s}") and int(ctx.facts.value(f"f_min_flip_{s}", 0) or 0) > 1:
        words = f"No single choice flips it; changing {tok(f'f_min_flip_{s}')} choices at once can."
    elif robust.holds >= 1.0:
        words = "No reasonable choice changes it."
    else:
        words = "No single choice flips it."
    return flips, ctx.t(words)


def genes(ctx: Ctx) -> list[GeneRow]:
    """One row per gene, headline genes first, then by name."""
    withheld = {
        fid[len("f_withheld_") :]: fid for fid in ctx.facts if fid.startswith("f_withheld_")
    }
    headline = ctx.headline
    order = headline + sorted(g for g in ctx.result.contrasts if g not in headline)
    rows = []
    for gene in order:
        contrast = ctx.result.contrasts[gene]
        s = safe_slug(gene)

        def fid(name: str) -> str | None:
            return name if name in ctx.facts else None

        n_a, n_b = ctx.gene_n(gene)
        rests, rests_text = _rests_on(ctx, gene)
        grade = ctx.result.confidence.get(gene)
        reasons = [_reason(ctx, gene, c.model_dump()) for c in grade.checks] if grade else []
        rows.append(
            GeneRow(
                gene=gene,
                headline=gene in headline,
                conclusion=contrast.conclusion,
                n_a=n_a,
                n_b=n_b,
                fc=fid(f"f_fc_{s}_recommended"),
                ci_lo=fid(f"f_ci_lo_{s}_recommended"),
                ci_hi=fid(f"f_ci_hi_{s}_recommended"),
                p=fid(f"f_p_{s}_recommended"),
                holds=fid(f"f_holds_{s}"),
                level=fid(f"f_level_{s}"),
                rests_on=rests,
                rests_on_text=rests_text,
                reasons=reasons,
                withheld=withheld.get(s),
            )
        )
    return rows


# ---------- decisions ----------


def decisions(ctx: Ctx) -> Decisions:
    """The decision chain as rows, who decided how many, and the Studio proposals by outcome."""
    view = ctx.view
    entries = [
        Decision(
            seq=str(e.get("seq", "")),
            card=str(e.get("card_id", "")),
            option=str(e.get("option", "")),
            actor=str(e.get("actor", "")),
            status=str(e.get("status", "")),
            at=str(e.get("at", "")),
            reason=str(e.get("reason", "")),
        )
        for e in view.decisions
    ]
    if not entries and not view.has("decisions.jsonl"):
        return Decisions(status="not_available", reason=f"the decision log is {NOT_IN_RECORD}")
    actors = Counter(e.actor for e in entries)
    path = "decisions.jsonl:actor"
    by_actor = ctx.t(
        f"{ctx.count('n_decisions', len(entries), 'decisions.jsonl')} decisions in the "
        f"hash-chained log: {ctx.count('n_dec_human', actors['human'], path)} by a person, "
        f"{ctx.count('n_dec_system', actors['system'], path)} automatically because no "
        "conclusion changes at the primary analysis, "
        f"{ctx.count('n_dec_agent', actors['agent'], path)} by an agent."
    )
    proposals = None
    if view.proposals:
        acts = Counter((str(p.get("action", "")), str(p.get("actor", ""))) for p in view.proposals)
        human_accept = sum(n for (a, who), n in acts.items() if a == "accept" and who == "human")
        human_reject = sum(n for (a, who), n in acts.items() if a == "reject" and who == "human")
        proposed = sum(n for (a, _), n in acts.items() if a == "propose")
        path = "proposals.jsonl:action"
        proposals = ctx.t(
            f"Studio proposal chain: {ctx.count('n_proposed', proposed, path)} proposals; a "
            f"person accepted {ctx.count('n_accepted', human_accept, path)} and rejected "
            f"{ctx.count('n_rejected', human_reject, path)}."
        )
    excluded = view.study_design.get("excluded_wells")
    exclusions = [str(w) for w in excluded] if isinstance(excluded, list) else []
    return Decisions(entries=entries, by_actor=by_actor, proposals=proposals, exclusions=exclusions)


# ---------- integrity ----------


def integrity(ctx: Ctx) -> Integrity:
    """``qpilot verify`` as found, and the identifiers binding the report to the record."""
    view = ctx.view
    report = view.verification
    meta = view.meta
    problems = report.summary().splitlines() if not report.ok else []
    return Integrity(
        ok=report.ok,
        summary=report.summary() if report.ok else "the record does NOT verify",
        problems=problems,
        record_id=view.record_id,
        chain_head=str(meta.get("chain_head")) if meta.get("chain_head") else None,
        input_sha256=ctx.result.input_sha256,
        input_included=view.has("input.rdml"),
        checksums=view.checksums,
        unreadable=sorted(set(view.problems)),
    )


# ---------- optional sections ----------


def optional(ctx: Ctx) -> dict[str, Optional_]:
    """Run Gate, Trust Card, labels and Trace: shown when their member is in the record."""
    out = {}
    for key, (members, title) in OPTIONAL_MEMBERS.items():
        present = [m for m in members if ctx.view.has(m)]
        if not present:
            out[key] = Optional_(
                status="not_available",
                title=title,
                reason=f"{NOT_IN_RECORD} (no {' or '.join(members)})",
            )
            continue
        out[key] = Optional_(
            title=title,
            reason="present in the record; a detailed view arrives with this section's contract",
            data={m: ctx.view.json(m) is not None for m in present},
        )
    return out
