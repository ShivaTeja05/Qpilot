"""The study-wide trace: which calls hang on few samples, and which samples sit behind most calls.

:func:`trace_study` ranks the compared genes by how little it takes to change their call (the
fewest samples whose removal changes it; then how many single samples do; then how close the
fold change is to the rule's line), and lists the "suspect" samples: those whose removal alone
changes the most calls, or whose wells show a fingerprint (a control-gene well that disagrees
with the sample's other control genes, every gene late together, low efficiency everywhere, a
well within five cycles of an amplifying no-template control), each with the plates and wells
to look at. It also names the samples in no comparison and the empty well behind each.

:func:`without_samples` recomputes one gene with any set of samples set aside together (exact)
and says which other calls change too: the page's "what if I drop this sample?".

Deterministic; no model. Every number is the engine's (see :mod:`qpilot.trace.gene`).
"""

from __future__ import annotations

import math

import numpy as np

from qpilot.qpcr.contrast import describe_rule
from qpilot.trace.context import THRESHOLDS, TraceContext, TraceError, set_aside
from qpilot.trace.gene import (
    call_model,
    cannot_show,
    cell_model,
    changes,
    finite,
    flip_set,
    read_as_expected,
    sample_plates,
    well_model,
)
from qpilot.trace.schema import (
    Traced,
    TraceGeneRow,
    TraceMissing,
    TracePlate,
    TraceStudy,
    TraceSuspect,
    TraceWithout,
)
from qpilot.trace.words import Facts

MAX_SUSPECTS = 40


def trace_study(ctx: TraceContext) -> Traced[TraceStudy]:
    """Genes by fragility and the samples behind the most calls (see the module)."""
    facts = Facts("study", float(2**ctx.rule.min_log2fc))
    genes = _genes(ctx)
    suspects = _suspects(ctx)
    left_out = _left_out(ctx)
    n_fragile = sum(1 for g in genes if g.n_flip_single)
    _summary(ctx, facts, genes, suspects, left_out)
    checked = [
        "Every compared gene: every sample set aside alone, and every pair of samples where no "
        "single one changes the call.",
        "Every sample's control-gene wells against what its other control genes predict.",
        "Every sample's input amount and efficiency across all its plates.",
        "Every study well against its plate's amplifying no-template controls.",
    ]
    if len(ctx.refs) < 3:
        checked[1] = (
            "With fewer than three control genes, control-gene wells cannot be checked against "
            "each other."
        )
    data = TraceStudy(
        cell=cell_model(ctx),
        labels=ctx.labels,
        rule=describe_rule(ctx.rule, ctx.correction),
        comparison=ctx.comparison_id,
        comparison_label=ctx.comparison_label,
        n_units=len(ctx.units),
        n_compared=int(ctx.comparison.used.any(axis=1).sum()),
        n_genes=len(ctx.items),
        n_fragile=n_fragile,
        genes=genes,
        suspects=suspects,
        left_out=left_out,
        checked=checked,
        cannot_show=cannot_show(ctx),
        thresholds=dict(THRESHOLDS),
    )
    return Traced(data, facts.texts, facts.facts)


def _genes(ctx: TraceContext) -> list[TraceGeneRow]:
    loo = ctx.loo
    base = ctx.base
    rows = []
    for j, gene in enumerate(ctx.items):
        used = ctx.comparison.used[:, j]
        flip = flip_set(ctx, j)
        d = np.where(used, np.abs(loo.d_log2fc[:, j]), -1.0)
        top = int(np.argmax(d)) if used.any() else None
        p = float(base.p[j])
        p_adj = finite(base.p_adj[j]) if base.p_adj is not None else None
        rows.append(
            TraceGeneRow(
                gene=gene,
                rank=0,
                conclusion={1: "up", -1: "down", 0: "none"}[int(base.call[j])],
                log2fc=float(base.diff[j]),
                fc=float(2 ** base.diff[j]),
                p=p if math.isfinite(p) else None,
                p_adjusted=p_adj,
                margin_log2=abs(float(base.diff[j])) - float(ctx.rule.min_log2fc),
                n_flip_single=int((loo.changed[:, j] & used).sum()),
                flip_k=flip.k,
                flip_exact=flip.exact,
                flip_units=flip.units,
                top_unit=ctx.units[top] if top is not None else None,
                top_d_log2fc=float(loo.d_log2fc[top, j]) if top is not None else None,
            )
        )
    rows.sort(
        key=lambda g: (
            g.flip_k if g.flip_k is not None else math.inf,
            -g.n_flip_single,
            abs(g.margin_log2),
            g.gene,
        )
    )
    return [g.model_copy(update={"rank": n}) for n, g in enumerate(rows, start=1)]


def _suspects(ctx: TraceContext) -> list[TraceSuspect]:
    loo = ctx.loo
    half = ctx.base.half_width()
    cap = THRESHOLDS["moves_number_cap_log2"]
    yard = np.where(np.isfinite(half), np.minimum(half, cap), cap)
    threshold = THRESHOLDS["robust_z"]
    d = np.abs(loo.d_log2fc)
    every = [*ctx.items, *ctx.refs]
    out = []
    for i, unit in enumerate(ctx.units):
        used = ctx.comparison.used[i]
        if not used.any():
            continue
        flipped = [ctx.items[j] for j in np.flatnonzero(loo.changed[i] & used)]
        moved = int(((d[i] >= yard) & used & ~loo.changed[i]).sum())
        flags = []
        if ctx.ref.flagged[i].any():
            flags.append("reference_pull")
        if math.isfinite(ctx.input_z[i]) and abs(ctx.input_z[i]) > threshold:
            flags.append("input_shift")
        if math.isfinite(ctx.eff_z[i]) and ctx.eff_z[i] < -threshold:
            flags.append("low_efficiency")
        records = ctx.unit_records(unit, every)
        unusual = [r for r in records if r["s1"] or r["s6"]]
        if unusual and any(r["s6"] for r in unusual):
            flags.append("ntc_window")
        if not (flipped or moved or flags):
            continue
        j_max = int(np.argmax(np.where(used, d[i], -1.0)))
        read = regrouped = held = None
        if "reference_pull" in flags:
            what = read_as_expected(ctx, i)
            read = changes(ctx, what.after)
            if what.regrouped:
                regrouped = _regrouped_words(ctx, what.left, what.joined)
                held = changes(ctx, what.fixed) if what.fixed is not None else None
        out.append(
            TraceSuspect(
                unit=unit,
                group=ctx.group_of(i),
                rank=0,
                n_genes_flipped=len(flipped),
                genes_flipped=flipped,
                n_genes_moved=moved,
                max_abs_d_log2fc=float(d[i, j_max]),
                max_gene=ctx.items[j_max],
                flags=flags,
                input_shift_log2=float(ctx.input_shift[i])
                if math.isfinite(ctx.input_shift[i])
                else None,
                wells=[well_model(r) for r in unusual],
                plates=sample_plates(ctx, unit, [r["gene"] for r in unusual]) if unusual else [],
                read_as_expected=read,
                read_regrouped=regrouped,
                read_groups_held=held,
            )
        )
    out.sort(
        key=lambda s: (
            -s.n_genes_flipped,
            -len(s.read_as_expected or []),
            -("reference_pull" in s.flags),
            -s.n_genes_moved,
            -s.max_abs_d_log2fc,
            s.unit,
        )
    )
    return [s.model_copy(update={"rank": n}) for n, s in enumerate(out[:MAX_SUSPECTS], start=1)]


def _regrouped_words(ctx: TraceContext, left: tuple[str, ...], joined: tuple[str, ...]) -> str:
    """'2016 leaves MYCN-high; 1907 joins MYCN-high'."""
    parts = []
    if left:
        parts.append(f"{', '.join(left)} {'leaves' if len(left) == 1 else 'leave'} {ctx.labels[0]}")
    if joined:
        parts.append(
            f"{', '.join(joined)} {'joins' if len(joined) == 1 else 'join'} {ctx.labels[0]}"
        )
    return "; ".join(parts)


def _left_out(ctx: TraceContext) -> list[TraceMissing]:
    """Every sample of the matrix in no comparison, why, and the empty well(s) behind it."""
    used_any = ctx.comparison.used.any(axis=1)
    matrix = ctx.matrix
    out = []
    for i in np.flatnonzero(~used_any):
        unit = ctx.units[i]
        empty_refs = [r for r in ctx.refs if math.isnan(matrix.iat[i, matrix.columns.get_loc(r)])]
        marker_empty = (
            ctx.marker is not None
            and ctx.marker in matrix.columns
            and math.isnan(matrix.iat[i, matrix.columns.get_loc(ctx.marker)])
        )
        genes = empty_refs + ([ctx.marker] if marker_empty and ctx.marker else [])
        records = ctx.unit_records(unit, genes)
        if empty_refs:
            reason = (
                "excluded" if records and all(r["excluded"] for r in records) else "empty_reference"
            )
        elif marker_empty:
            reason = "empty_marker"
        else:
            reason = "not_in_groups"
        out.append(
            TraceMissing(
                unit=unit, reason=reason, group=None, wells=[well_model(r) for r in records]
            )
        )
    return out


def _summary(
    ctx: TraceContext,
    facts: Facts,
    genes: list[TraceGeneRow],
    suspects: list[TraceSuspect],
    left_out: list[TraceMissing],
) -> None:
    t = facts
    one = [g for g in genes if g.flip_k == 1]
    two = [g for g in genes if g.flip_k == 2]
    text = (
        f"Of {t.count('n_genes', len(genes))} compared genes, {t.count('n_one', len(one))} "
        "change their "
        f"call when a single sample is set aside"
    )
    if two:
        text += f", and {t.count('n_two', len(two))} more when two are"
    text += "."
    if one:
        text += f" The most fragile: {t.name('fragile', ', '.join(g.gene for g in one[:6]))}."
    flagged = [s for s in suspects if "reference_pull" in s.flags]
    if flagged:
        noun = (
            "sample has a control-gene well"
            if len(flagged) == 1
            else "samples have a control-gene well"
        )
        text += (
            f" {t.count('n_flagged', len(flagged))} {noun} far from what their other control genes "
            "predict; each makes every value of its sample too high or too low."
        )
    if left_out:
        text += (
            f" {t.count('n_left_out', len(left_out))} of {t.count('n_units', len(ctx.units))} "
            "samples "
            "are in no comparison (see why)."
        )
    facts.say("summary", text)


def plate_wells(ctx: TraceContext, run: str) -> TracePlate:
    """Every well of one plate, with Trace's flags (``TraceError`` for an unknown plate)."""
    rows = [r for r in ctx.records if r["plate"] == run]
    if not rows:
        raise TraceError(f"There is no plate {run!r} in this study.")
    return TracePlate(
        run=run,
        genes=sorted({str(r["gene"]) for r in rows}),
        wells=[well_model(r) for r in rows],
    )


def without_samples(ctx: TraceContext, gene: str, units: list[str]) -> TraceWithout:
    """Gene ``gene`` with ``units`` set aside together (every gene re-evaluated in full).

    Raises:
        TraceError: Unknown gene or sample, or a sample that is not in this gene's comparison.
    """
    j = ctx.gene_index(gene)
    names = list(dict.fromkeys(units))
    if not names:
        raise TraceError("Name at least one sample to set aside.")
    rows = [ctx.unit_index(u) for u in names]
    used = ctx.comparison.used[:, j]
    outside = [u for u, i in zip(names, rows, strict=True) if not used[i]]
    if outside:
        raise TraceError(f"Not in {gene}'s comparison: {', '.join(outside)}.")
    after = set_aside(ctx, rows)
    valid = ctx.valid.copy()
    valid[rows, :] = False
    listed = changes(ctx, after)
    return TraceWithout(
        gene=gene,
        units=names,
        before=call_model(ctx, ctx.base, j),
        after=call_model(ctx, after, j, valid & (ctx.in_a | ctx.in_b)[:, None]),
        changes_call=bool(after.call[j] != ctx.base.call[j]),
        other_changes=[c for c in listed if c.gene != gene],
    )
