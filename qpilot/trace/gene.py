"""Result-first trace: one gene's call followed down to the samples, wells and plates behind it.

For the analysis in use (:class:`~qpilot.trace.context.TraceContext`), :func:`trace_gene` gives

* every sample's influence: the exact change of the log2 fold change when it alone is set aside,
  and whether that changes the call;
* the fewest samples whose removal together changes the call (one and two checked
  exhaustively; beyond that a greedy search, said so);
* each control gene's exact share of the fold change, and the result without it;
* the places to look, ranked *changes the call* > *moves the number by at least
  min(half its 95 % CI, 0.5 log2)* > *changes nothing*, then by size, then by z, each with the
  wells behind it and what reading or setting it aside would do: a control-gene well that
  disagrees with the sample's other control genes (S1), a whole sample late on every gene (S2)
  or amplifying less efficiently everywhere (S4), a curve note that matters (S5), wells within
  five cycles of an amplifying no-template control (S6);
* the well to look at first, or, when nothing unusual sits behind the result, the most
  influential sample and that its wells look normal (keep it: that is how p-hacking starts).

Setting a sample aside keeps everyone else's group. Reading a control-gene well as the sample's
other control genes predict re-derives a marker split's groups as a re-analysis would (and the
result with the groups held is given too). Nothing is applied: every what-if is a perturbation.

Ported from the WIP engine on ``agents/trace`` (``qpilot/qpcr/trace.py``, 19 Oct 2026): the
reference-well check, the fingerprints, the ranking and the wording; rebuilt around the analysis
in use and the page's contract. Deterministic; no model.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from qpilot.trace.context import (
    THRESHOLDS,
    TraceContext,
    WhatIf,
    flags_of,
    relative_values,
    set_aside,
    what_if_values,
)
from qpilot.trace.schema import (
    Consequence,
    TraceCall,
    TraceCallChange,
    TraceCell,
    Traced,
    TraceFlipSet,
    TraceGene,
    TraceLookFirst,
    TraceMissing,
    TraceOption,
    TracePlace,
    TraceReference,
    TraceSample,
    TraceWell,
)
from qpilot.trace.welch import CALL_NAMES, WelchArrays, robust_z
from qpilot.trace.words import Facts, call_word

CONSEQUENCE_ORDER: dict[str, int] = {"changes_call": 0, "moves_number": 1, "changes_nothing": 2}
NO_AMPLIFICATION = ("no amplification",)
DETAIL = 12  # samples whose wells are listed besides the call-changers and the unusual ones


# ---- shared builders (also used by the study view) -----------------------------------------


def cell_model(ctx: TraceContext) -> TraceCell:
    """The analysis in use."""
    cell = ctx.cell
    return TraceCell(
        refs=list(cell["refs"]),
        cut=cell.get("cut"),
        undetermined=str(cell["undetermined"]),
        amp_call=cell.get("amp_call"),
        planned=ctx.planned,
    )


def finite(value: Any) -> float | None:
    """A float, or None for a missing or non-finite value."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def well_model(row: Mapping[str, Any]) -> TraceWell:
    """A :class:`TraceWell` from a row of the context's well table."""
    s6 = bool(row["s6"])
    standard = row["std_low_name"] if isinstance(row["std_low_name"], str) else None
    return TraceWell(
        key=str(row["key"]),
        plate=str(row["plate"]),
        well=str(row["well"]),
        sample=str(row["sample"]),
        unit=str(row["unit"]),
        gene=str(row["gene"]),
        role=row["role"],
        sample_type=str(row["sample_type"]),
        cq=finite(row["cq"]),
        efficiency=finite(row["eff"]),
        amplified=bool(row["amplified"]),
        excluded=bool(row["excluded"]),
        note=str(row["note"]),
        plate_median_cq=finite(row["plate_median_cq"]),
        cq_z=finite(row["cq_z"]),
        efficiency_z=finite(row["eff_z"]),
        pull_log2=finite(row["pull"]),
        reference_z=finite(row["ref_z"]),
        ntc_well=str(row["ntc_well"]) if s6 and isinstance(row["ntc_well"], str) else None,
        ntc_cq=finite(row["ntc_cq"]) if s6 else None,
        lowest_standard=standard,
        lowest_standard_cq=finite(row["std_low_cq"]) if standard else None,
        flags=flags_of(row),
    )


def call_model(
    ctx: TraceContext, after: WelchArrays, j: int, valid: np.ndarray | None = None
) -> TraceCall:
    """One gene's comparison as the page shows it."""
    rule = ctx.rule
    d, se = float(after.diff[j]), float(after.se[j])
    half = finite(after.t_crit[j] * after.se[j])
    used = (ctx.comparison.used if valid is None else valid)[:, j]
    x = ctx.relative[:, j]
    a, b = used & ctx.in_a, used & ctx.in_b
    return TraceCall(
        conclusion=CALL_NAMES[int(after.call[j])],
        log2fc=d,
        fc=float(2**d),
        ci=(float(2 ** (d - half)), float(2 ** (d + half))) if half is not None else (None, None),
        p=finite(after.p[j]),
        n_a=int(a.sum()),
        n_b=int(b.sum()),
        mean_a=float(x[a].mean()) if a.any() else math.nan,
        mean_b=float(x[b].mean()) if b.any() else math.nan,
        se=se,
        line_log2=float(rule.min_log2fc),
        margin_log2=abs(d) - float(rule.min_log2fc),
    )


def changes(
    ctx: TraceContext, after: WelchArrays, cols: Iterable[int] | None = None
) -> list[TraceCallChange]:
    """Conclusions that differ from the analysis in use, in gene order."""
    base = ctx.base
    out = []
    for j in range(len(ctx.items)) if cols is None else cols:
        if after.call[j] == base.call[j]:
            continue
        out.append(
            TraceCallChange(
                gene=ctx.items[j],
                call_before=CALL_NAMES[int(base.call[j])],
                call_after=CALL_NAMES[int(after.call[j])],
                log2fc_before=float(base.diff[j]),
                log2fc_after=float(after.diff[j]),
                p_before=finite(base.p[j]),
                p_after=finite(after.p[j]),
            )
        )
    return out


def loo_row(ctx: TraceContext, i: int) -> WelchArrays:
    """Every gene with unit ``i`` set aside (closed form; untouched genes keep their result)."""
    after = ctx.loo.after.row(i)
    touched = ctx.loo.touched[i]
    base = ctx.base
    return WelchArrays(
        diff=np.where(touched, after.diff, base.diff),
        se=np.where(touched, after.se, base.se),
        p=np.where(touched, after.p, base.p),
        df=np.where(touched, after.df, base.df),
        t_crit=np.where(touched, after.t_crit, base.t_crit),
        call=np.where(touched, after.call, base.call),
    )


def consequence(changes_call: bool, d_log2fc: float, half_width: float) -> Consequence:
    """Changes the call > moves the number by min(CI half-width, 0.5 log2) > changes nothing."""
    if changes_call:
        return "changes_call"
    cap = THRESHOLDS["moves_number_cap_log2"]
    yardstick = min(half_width, cap) if math.isfinite(half_width) else cap
    return "moves_number" if abs(d_log2fc) >= yardstick else "changes_nothing"


def sample_flags(
    ctx: TraceContext, i: int, genes: Sequence[str], z_in_group: float | None
) -> list[str]:
    """The fingerprints of unit ``i`` behind these genes' values (``genes[0]``: the target)."""
    threshold = THRESHOLDS["robust_z"]
    unit = ctx.units[i]
    table = ctx.unit_gene
    flags = []
    if ctx.ref.flagged[i].any():
        flags.append("reference_pull")
    if math.isfinite(ctx.input_z[i]) and abs(ctx.input_z[i]) > threshold:
        flags.append("input_shift")
    if math.isfinite(ctx.eff_z[i]) and ctx.eff_z[i] < -threshold:
        flags.append("low_efficiency")
    if z_in_group is not None and abs(z_in_group) > threshold:
        flags.append("far_from_group")
    if any(table.get((unit, g), (False,))[0] for g in genes):
        flags.append("ntc_window")
    if table.get((unit, genes[0]), (False, False))[1]:
        flags.append("curve_note")
    return flags


def sample_plates(ctx: TraceContext, unit: str, genes: Sequence[str]) -> list[str]:
    """The plates of the unit's wells behind these genes' values."""
    table = ctx.unit_gene
    plates: set[str] = set()
    for g in genes:
        plates.update(table.get((unit, g), (False, False, ()))[2])
    return sorted(plates)


# ---- the trace -----------------------------------------------------------------------------


@dataclass
class _Candidate:
    """A place before ranking: what it is, its checks and its what-ifs for the traced gene."""

    kind: str
    i: int
    wells: pd.DataFrame
    checks: list[tuple[str, float | None, dict[str, Any]]]
    options: list[TraceOption]
    d: float
    changes_gene: bool
    z: float


def trace_gene(ctx: TraceContext, gene: str, detail: int = DETAIL) -> Traced[TraceGene]:
    """One gene's call, followed down to its samples, wells and plates (see the module).

    Raises:
        TraceError: The gene is not a compared gene of the study (the message says why).
    """
    j = ctx.gene_index(gene)
    facts = Facts(f"g_{gene}", float(2**ctx.rule.min_log2fc))
    base = ctx.base
    used = ctx.comparison.used[:, j]
    half = float(base.half_width()[j])
    call = call_model(ctx, base, j)
    genes = [gene, *ctx.refs]
    samples = _samples(ctx, j, used, genes, detail)
    flip = flip_set(ctx, j)
    references = _references(ctx, j, used)
    candidates = [
        *_reference_candidates(ctx, j, used),
        *_ntc_candidates(ctx, j, used),
        *_target_candidates(ctx, j, used, half),
        *_sample_candidates(ctx, j, used),
    ]
    ranked = sorted(
        candidates,
        key=lambda c: (
            CONSEQUENCE_ORDER[consequence(c.changes_gene, c.d, half)],
            -abs(c.d),
            -abs(c.z) if math.isfinite(c.z) else 0.0,
            ctx.units[c.i],
            c.kind,
        ),
    )
    places = [_place(ctx, facts, rank, c, gene, half) for rank, c in enumerate(ranked, start=1)]
    unusual = {c.i for c in candidates}
    influential = _influential(ctx, j, used, unusual, samples)
    look = _look_first(ctx, facts, gene, places, samples, influential)
    missing, n_none = _missing(ctx, j)
    n_flips = sum(s.flips for s in samples)
    _summary(ctx, facts, gene, call, n_flips, flip, places)
    data = TraceGene(
        gene=gene,
        cell=cell_model(ctx),
        labels=ctx.labels,
        rule=ctx.rule.describe(),
        call=call,
        n_used=int(used.sum()),
        n_flip_single=n_flips,
        flip=flip,
        samples=samples,
        references=references,
        places=places,
        look_first=look,
        influential_normal=influential,
        missing=missing,
        n_no_comparison=n_none,
        checked=_checked(ctx, gene, candidates),
        cannot_show=cannot_show(ctx),
        replicates=ctx.replicates,
        thresholds=dict(THRESHOLDS),
    )
    return Traced(data, facts.texts, facts.facts)


def _samples(
    ctx: TraceContext, j: int, used: np.ndarray, genes: list[str], detail: int
) -> list[TraceSample]:
    """Every sample in the comparison, most influential first, with wells for the detailed."""
    loo = ctx.loo
    d = loo.d_log2fc[:, j]
    rows = np.flatnonzero(used)
    order = sorted(rows, key=lambda i: (-abs(d[i]), ctx.units[i]))
    x = ctx.relative[:, j]
    z = np.full(len(ctx.units), np.nan)
    for mask in (used & ctx.in_a, used & ctx.in_b):
        if mask.sum() >= 3:
            z[mask] = robust_z(x[mask])
    out = []
    for rank, i in enumerate(order, start=1):
        zi = finite(z[i])
        flags = sample_flags(ctx, int(i), genes, zi)
        flips = bool(loo.changed[i, j])
        shown = rank <= detail or flips or bool(set(flags) - {"far_from_group"})
        mine = ctx.unit_records(ctx.units[i], genes) if shown else []
        out.append(
            TraceSample(
                unit=ctx.units[i],
                group=ctx.group_of(int(i)) or "",
                side=ctx.side_of(int(i)) or "a",
                rank=rank,
                value_log2=float(x[i]),
                z_in_group=zi,
                d_log2fc=float(d[i]),
                log2fc_without=float(loo.after.diff[i, j]),
                p_without=finite(loo.after.p[i, j]),
                call_without=CALL_NAMES[int(loo.after.call[i, j])],
                flips=flips,
                flags=flags,
                plates=sample_plates(ctx, ctx.units[i], genes),
                wells=[well_model(r) for r in mine],
            )
        )
    return out


def flip_set(ctx: TraceContext, j: int) -> TraceFlipSet:
    """The fewest samples whose removal changes gene ``j``'s call (kept per study)."""
    key = ("flip", j)
    if key not in ctx.cache:
        ctx.cache[key] = _flip(ctx, j)
    return ctx.cache[key]


def _flip(ctx: TraceContext, j: int) -> TraceFlipSet:
    found = ctx.comparison.smallest_flip(j, ctx.loo, int(THRESHOLDS["flip_search_limit"]))
    after = found.after
    return TraceFlipSet(
        k=len(found.units) or None,
        exact=found.exact,
        searched=found.searched,
        units=[ctx.units[i] for i in found.units],
        call_after=CALL_NAMES[int(after.call)] if after is not None else None,
        log2fc_after=float(after.diff) if after is not None else None,
        p_after=finite(after.p) if after is not None else None,
    )


def _references(ctx: TraceContext, j: int, used: np.ndarray) -> list[TraceReference]:
    """Each control gene's exact share of the fold change, and the result without it."""
    k = len(ctx.refs)
    a, b = used & ctx.in_a, used & ctx.in_b
    out = []
    for r, ref in enumerate(ctx.refs):
        values = ctx.matrix[ref].to_numpy(dtype=float)
        diff = float(values[a].mean() - values[b].mean()) if a.any() and b.any() else math.nan
        without = None
        after_fc = after_call = None
        if k >= 2:
            after = without_reference(ctx, ref)
            after_fc, after_call = float(after.diff[j]), CALL_NAMES[int(after.call[j])]
            listed = changes(ctx, after, [j])
            without = listed[0] if listed else None
        rows = np.flatnonzero(used & ctx.ref.flagged[:, r])
        flagged = []
        for i in rows:
            w = ctx.unit_wells(ctx.units[i], ref)
            flagged += [well_model(row) for _, row in w.iterrows() if bool(row["s1"])]
        out.append(
            TraceReference(
                gene=ref,
                share_log2=-diff / k if math.isfinite(diff) else math.nan,
                group_diff_log2=diff,
                without=without,
                log2fc_without=after_fc,
                call_without=after_call,
                flagged=flagged,
            )
        )
    return out


# ---- places --------------------------------------------------------------------------------


def option_set_aside(
    ctx: TraceContext, i: int, j: int, label: str = "set the sample aside"
) -> TraceOption:
    """Unit ``i`` set aside from every comparison (exact, closed form)."""
    after = loo_row(ctx, i)
    return TraceOption(
        id="set_aside",
        label=label,
        call_after=CALL_NAMES[int(after.call[j])],
        log2fc_after=float(after.diff[j]),
        p_after=finite(after.p[j]),
        d_log2fc=float(after.diff[j] - ctx.base.diff[j]),
        changes=changes(ctx, after),
    )


def option_read(ctx: TraceContext, what: WhatIf, j: int) -> TraceOption:
    """A control-gene well read as the sample's other control genes predict."""
    after = what.after
    regrouped = None
    if what.regrouped:
        parts = []
        if what.left:
            verb = "leaves" if len(what.left) == 1 else "leave"
            parts.append(f"{', '.join(what.left)} {verb} {ctx.labels[0]}")
        if what.joined:
            verb = "joins" if len(what.joined) == 1 else "join"
            parts.append(f"{', '.join(what.joined)} {verb} {ctx.labels[0]}")
        regrouped = "; ".join(parts)
    return TraceOption(
        id="read_from_other_references",
        label="read this well as the sample's other control genes predict",
        call_after=CALL_NAMES[int(after.call[j])],
        log2fc_after=float(after.diff[j]),
        p_after=finite(after.p[j]),
        d_log2fc=float(after.diff[j] - ctx.base.diff[j]),
        changes=changes(ctx, after),
        regrouped=regrouped,
        fixed_groups_changes=changes(ctx, what.fixed) if what.fixed is not None else None,
    )


def read_as_expected(ctx: TraceContext, i: int) -> WhatIf:
    """Unit ``i`` with each flagged control-gene well read from its unflagged control genes."""
    key = ("read", i)
    if key not in ctx.cache:
        flagged = np.flatnonzero(ctx.ref.flagged[i])
        changed = {(i, ctx.refs[r]): float(ctx.ref.expected[i, r]) for r in flagged}
        ctx.cache[key] = what_if_values(ctx, changed)
    return ctx.cache[key]


def without_reference(ctx: TraceContext, ref: str) -> WelchArrays:
    """Every gene normalised to the analysis' other control genes (``ref`` left out)."""
    key = ("without_ref", ref)
    if key not in ctx.cache:
        cell = {**ctx.cell, "refs": tuple(g for g in ctx.refs if g != ref)}
        _, relative, valid = relative_values(ctx.model, cell, ctx.matrix, ctx.items)
        ctx.cache[key] = ctx.comparison.evaluate(relative, valid, ctx.in_a, ctx.in_b)
    return ctx.cache[key]


def _reference_candidates(ctx: TraceContext, j: int, used: np.ndarray) -> list[_Candidate]:
    """S1: control-gene wells of the samples used here that disagree with the others."""
    out = []
    for i in np.flatnonzero(used & ctx.ref.flagged.any(axis=1)):
        i = int(i)
        flagged = [int(r) for r in np.flatnonzero(ctx.ref.flagged[i])]
        options = [option_read(ctx, read_as_expected(ctx, i), j), option_set_aside(ctx, i, j)]
        gene = ctx.items[j]
        changes_gene = any(any(c.gene == gene for c in o.changes) for o in options)
        d = max((o.d_log2fc for o in options), key=abs)
        wells = pd.concat([ctx.unit_wells(ctx.units[i], ctx.refs[r]) for r in flagged])
        checks = [("S1", float(ctx.ref.z[i, r]), {"r": r}) for r in flagged]
        z = max(abs(float(ctx.ref.z[i, r])) for r in flagged)
        out.append(_Candidate("reference_well", i, wells, checks, options, d, changes_gene, z))
    return out


def _ntc_candidates(ctx: TraceContext, j: int, used: np.ndarray) -> list[_Candidate]:
    """S6: study wells used here within five cycles of their plate's amplifying NTC."""
    out = []
    w = ctx.wells
    gene = ctx.items[j]
    tainted = w[w["s6"] & w["gene"].isin([gene, *ctx.refs]) & (w["sample_type"] == "unkn")]
    names = {ctx.units[i] for i in np.flatnonzero(used)}
    tainted = tainted[tainted["unit"].isin(names)]
    for (plate, g), group in tainted.groupby(["plate", "gene"], sort=True):
        rows = sorted({ctx.unit_index(u) for u in group["unit"]})
        target = g == gene
        after = set_aside(ctx, rows, [j] if target else None)
        option = TraceOption(
            id="set_aside_wells",
            label="set aside the study wells within the window",
            call_after=CALL_NAMES[int(after.call[j])],
            log2fc_after=float(after.diff[j]),
            p_after=finite(after.p[j]),
            d_log2fc=float(after.diff[j] - ctx.base.diff[j]),
            changes=changes(ctx, after, [j] if target else None),
        )
        ntc = w[(w["plate"] == plate) & (w["gene"] == g) & (w["well"] == group["ntc_well"].iloc[0])]
        wells = pd.concat([ntc, group.sort_values(["cq", "well"], ascending=[False, True])])
        gap = float(group["ntc_gap"].min())
        out.append(
            _Candidate(
                "plate_control",
                rows[0],
                wells,
                [("S6", None, {"n": len(rows), "gap": gap, "plate": plate})],
                [option],
                option.d_log2fc,
                bool(after.call[j] != ctx.base.call[j]),
                math.nan,
            )
        )
    return out


def _target_candidates(
    ctx: TraceContext, j: int, used: np.ndarray, half: float
) -> list[_Candidate]:
    """S5: target wells with a curve note, where setting the sample aside matters here."""
    out = []
    gene = ctx.items[j]
    w = ctx.wells
    noted = w[(w["gene"] == gene) & (w["sample_type"] == "unkn") & (w["note"] != "") & ~w["s6"]]
    noted = noted[~noted["note"].str.lower().str.startswith(NO_AMPLIFICATION)]
    for unit, group in noted.groupby("unit", sort=True):
        if unit not in ctx.units:
            continue
        i = ctx.unit_index(unit)
        if not used[i]:
            continue
        d = float(ctx.loo.d_log2fc[i, j])
        flips = bool(ctx.loo.changed[i, j])
        if consequence(flips, d, half) == "changes_nothing":
            continue  # a note alone, on a well that changes nothing here, is not a place
        option = option_set_aside(ctx, i, j)
        out.append(
            _Candidate("target_well", i, group, [("S5", None, {})], [option], d, flips, math.nan)
        )
    return out


def _sample_candidates(ctx: TraceContext, j: int, used: np.ndarray) -> list[_Candidate]:
    """S2 / S4: whole samples late on every gene, or amplifying less efficiently everywhere."""
    out = []
    threshold = THRESHOLDS["robust_z"]
    for i in np.flatnonzero(used):
        i = int(i)
        checks: list[tuple[str, float | None, dict[str, Any]]] = []
        if math.isfinite(ctx.input_z[i]) and abs(ctx.input_z[i]) > threshold:
            checks.append(("S2", float(ctx.input_z[i]), {"shift": float(ctx.input_shift[i])}))
        if math.isfinite(ctx.eff_z[i]) and ctx.eff_z[i] < -threshold:
            checks.append(("S4", float(ctx.eff_z[i]), {"shift": float(ctx.eff_shift[i])}))
        if not checks:
            continue
        option = option_set_aside(ctx, i, j)
        z = max(abs(c[1]) for c in checks if c[1] is not None)
        wells = ctx.unit_wells(ctx.units[i], ctx.items[j])
        changes_gene = bool(ctx.loo.changed[i, j])
        out.append(
            _Candidate("sample", i, wells, checks, [option], option.d_log2fc, changes_gene, z)
        )
    return out


def _place(
    ctx: TraceContext, facts: Facts, rank: int, c: _Candidate, gene: str, half: float
) -> TracePlace:
    unit = ctx.units[c.i]
    kind_consequence = consequence(c.changes_gene, c.d, half)
    wells = [well_model(row) for _, row in c.wells.iterrows()]
    text = facts.say(
        f"place_{rank}", _why(ctx, facts, f"p{rank}", c, unit, wells, gene, kind_consequence)
    )
    return TracePlace(
        rank=rank,
        kind=c.kind,
        unit=unit,
        group=ctx.group_of(c.i),
        checks=[cid for cid, *_ in c.checks],
        consequence=kind_consequence,
        d_log2fc=c.d,
        wells=wells,
        options=c.options,
        text=text,
    )


def _lead(kind: str) -> str:
    return (
        "Unusual, but it changes nothing for this result:"
        if kind == "changes_nothing"
        else "Look here first:"
    )


def _why(
    ctx: TraceContext,
    facts: Facts,
    key: str,
    c: _Candidate,
    unit: str,
    wells: list[TraceWell],
    gene: str,
    kind: str,
) -> str:
    """The place in words (token text)."""
    t = facts
    g = t.name("gene", gene)
    u = t.name(f"{key}_unit", unit)
    lead = _lead(kind)
    if c.kind == "reference_well":
        parts = []
        for n, well in enumerate(wells, start=1):
            if "reference_pull" not in well.flags:
                continue
            k = f"{key}_w{n}"
            where = (
                f"the {t.name(k + '_gene', well.gene)} well "
                f"(plate {t.name(k + '_plate', well.plate)}, "
                f"well {t.name(k + '_well', well.well)})"
            )
            if well.cq is None:
                where += " gave no Cq"
            else:
                where += f" read Cq {t.cycles(k + '_cq', well.cq)}"
                notes = []
                if well.plate_median_cq is not None:
                    notes.append(f"plate median {t.cycles(k + '_median', well.plate_median_cq)}")
                if well.lowest_standard is not None and well.lowest_standard_cq is not None:
                    notes.append(
                        f"fewest-copies standard {t.name(k + '_std', well.lowest_standard)} at "
                        f"{t.cycles(k + '_std_cq', well.lowest_standard_cq)}"
                    )
                if notes:
                    where += f" ({'; '.join(notes)})"
            parts.append(where)
        pull = sum(w.pull_log2 or 0.0 for w in wells if "reference_pull" in w.flags)
        direction = "too high" if pull > 0 else "too low"
        text = (
            f"{lead} in sample {u}, {' and '.join(parts)}, far from what the sample's other "
            "control "
            f"genes predict. That makes every value of sample {u} {t.times(key + '_pull', pull)} "
            f"{direction}."
        )
        read = c.options[0]
        if read.regrouped:
            text += (
                " Read as its other control genes predict, the groups change "
                f"({t.name(key + '_regrouped', read.regrouped)})"
            )
            text += _option_effect(facts, key, read, gene, g, "and", first=False)
        else:
            text += _option_effect(
                facts, key, read, gene, g, "Read as its other control genes predict,"
            )
        text += _option_effect(facts, key, c.options[1], gene, g, "Set aside,")
        return text
    if c.kind == "plate_control":
        ntc = wells[0]
        _, _, data = c.checks[0]
        window = t.tok("ntc_window", THRESHOLDS["ntc_window_cycles"], "{:g}")
        n = data["n"]
        noun = "study well used here comes" if n == 1 else "study wells used here come"
        return (
            f"{lead} the no-template control at plate {t.name(key + '_plate', ntc.plate)}, well "
            f"{t.name(key + '_well', ntc.well)} amplified "
            f"(Cq {t.cycles(key + '_cq', ntc.cq)}), and "
            f"{t.count(key + '_n', n)} {noun} up less than {window} cycles before it (closest "
            f"{t.tok(key + '_gap', data['gap'], '{:.1f}')} cycles). MIQE counts a sample "
            "positive only "
            "when it comes up at least that much before an amplifying negative control."
            + _option_effect(facts, key, c.options[0], gene, g, "Set aside,")
        )
    if c.kind == "target_well":
        well = wells[0]
        notes = "; ".join(
            t.name(f"{key}_note{n}", w.note) for n, w in enumerate(wells, start=1) if w.note
        )
        return (
            f"{lead} the {g} well of sample {u} (plate {t.name(key + '_plate', well.plate)}, well "
            f"{t.name(key + '_well', well.well)}) carries LinRegPCR's note: {notes}."
            + _option_effect(facts, key, c.options[0], gene, g, "Set aside,")
        )
    details = []
    for cid, z, data in c.checks:
        zt = t.tok(f"{key}_{cid.lower()}_z", z, "{:+.1f}")
        if cid == "S2":
            shift = float(data["shift"])
            word = "lower" if shift < 0 else "higher"
            details.append(
                f"every gene of the sample reads about {t.times(key + '_s2', shift)} {word} "
                f"than the study's typical sample (robust z {zt}), consistent with the amount "
                "of RNA or cDNA put in"
            )
        else:
            details.append(
                "its wells amplify less efficiently than their plates' other wells (median shift "
                f"{t.tok(key + '_s4', float(data['shift']), '{:+.3f}')}, robust z {zt}), "
                "consistent "
                "with an inhibitor carried over from extraction"
            )
    return (
        f"{lead} sample {u} as a whole stands out: "
        + "; ".join(details)
        + "."
        + _option_effect(facts, key, c.options[0], gene, g, "Set aside,")
    )


def _option_effect(
    facts: Facts, key: str, option: TraceOption, gene: str, g: str, lead: str, first: bool = True
) -> str:
    """What one what-if does to the traced gene (and how many other calls it changes)."""
    t = facts
    oid = f"{key}_{option.id}"
    mine = [ch for ch in option.changes if ch.gene == gene]
    if mine:
        ch = mine[0]
        what = (
            f"{g} goes from {t.name(oid + '_before', call_word(ch.call_before))} to "
            f"{t.name(oid + '_after', call_word(ch.call_after))} "
            f"({t.change(oid + '_fc_before', ch.log2fc_before)} "
            f"becomes {t.change(oid + '_fc_after', ch.log2fc_after)})"
        )
    else:
        what = f"{g} keeps its call (its fold change moves by {t.pct(oid + '_d', option.d_log2fc)})"
    text = f" {lead} {what}" if first else f" {lead} {what}"
    others = [ch.gene for ch in option.changes if ch.gene != gene]
    if others:
        noun = "other call changes" if len(others) == 1 else "other calls change"
        listed = t.name(oid + "_other", ", ".join(others))
        text += f"; {t.count(oid + '_n_other', len(others))} {noun} ({listed})"
    return text + "."


# ---- the rest of the answer ----------------------------------------------------------------


def _influential(
    ctx: TraceContext, j: int, used: np.ndarray, unusual: set[int], samples: list[TraceSample]
) -> list[str]:
    """Influential samples that show nothing unusual (keep them for that).

    Every sample that alone changes the call, and the three that move it most, when their
    influence is large for the group's size (DFBETAS beyond 2/sqrt(n), Belsley et al. 1980).
    """
    n = int(used.sum())
    se = float(ctx.base.se[j])
    cutoff = 2 / math.sqrt(n) if n else math.inf
    calm = [s for s in samples if ctx.unit_index(s.unit) not in unusual]
    big = [s for s in calm[:3] if se > 0 and abs(s.d_log2fc) / se > cutoff]
    chosen = {s.unit for s in calm if s.flips} | {s.unit for s in big}
    return [s.unit for s in samples if s.unit in chosen]


def _look_first(
    ctx: TraceContext,
    facts: Facts,
    gene: str,
    places: list[TracePlace],
    samples: list[TraceSample],
    influential: list[str],
) -> TraceLookFirst:
    t = facts
    g = t.name("gene", gene)
    if places and places[0].consequence != "changes_nothing":
        top = places[0]
        flagged = [
            w for w in top.wells if set(w.flags) & {"reference_pull", "ntc_window", "curve_note"}
        ]
        well = (flagged or top.wells or [None])[0]
        facts.say("look_first", facts.texts[top.text])
        return TraceLookFirst(kind="place", unit=top.unit, well=well, place=top.rank)
    if not samples:
        facts.say("look_first", f"{g} has no samples to trace in this analysis.")
        return TraceLookFirst(kind="none")
    top_sample = samples[0]
    target = [w for w in top_sample.wells if w.gene == gene]
    u = t.name("lf_unit", top_sample.unit)
    unusual = [p for p in places if p.consequence == "changes_nothing"]
    text = "Nothing unusual sits behind this result"
    if unusual:
        noun = "unusual place changes" if len(unusual) == 1 else "unusual places change"
        text += f" ({t.count('lf_n_unusual', len(unusual))} {noun} nothing here)"
    text += (
        f". The sample that moves it most is {u}: set aside, {g}'s fold change moves by "
        f"{t.pct('lf_d', top_sample.d_log2fc)}"
    )
    if top_sample.flips:
        text += f" and the call becomes {t.name('lf_after', call_word(top_sample.call_without))}"
    if "far_from_group" in top_sample.flags and not ctx.replicates:
        text += (
            ". Its value is far from its group; with one well per sample and gene this cannot be "
            "told apart from biology"
        )
    elif top_sample.unit in influential or top_sample.rank == 1:
        text += ". Its wells look normal: keep it, its value is what its wells say"
    facts.say("look_first", text + ".")
    return TraceLookFirst(
        kind="influential", unit=top_sample.unit, well=target[0] if target else None
    )


def _missing(ctx: TraceContext, j: int) -> tuple[list[TraceMissing], int]:
    """Samples in the groups with no value for this gene, and how many are in no comparison."""
    gene = ctx.items[j]
    grouped = ctx.in_a | ctx.in_b
    refs_ok = ctx.matrix[list(ctx.refs)].notna().all(axis=1).to_numpy()
    empty = grouped & refs_ok & np.isnan(ctx.values[:, j])
    out = []
    for i in np.flatnonzero(empty):
        unit = ctx.units[i]
        rows = ctx.unit_wells(unit, gene)
        reason = "excluded" if len(rows) and rows["excluded"].all() else "empty_target"
        out.append(
            TraceMissing(
                unit=unit,
                reason=reason,
                group=ctx.group_of(int(i)),
                wells=[well_model(r) for _, r in rows.iterrows()],
            )
        )
    n_none = int((~ctx.comparison.used.any(axis=1)).sum())
    return out, n_none


def _checked(ctx: TraceContext, gene: str, candidates: list[_Candidate]) -> list[str]:
    """What was checked and found nothing (plain words, no number)."""
    found = {cid for c in candidates for cid, *_ in c.checks}
    out = []
    if "S1" not in found and len(ctx.refs) >= 3:
        out.append("Control-gene wells of the samples used here agree with each other.")
    if "S6" not in found:
        out.append(
            f"No-template controls on the plates of {gene} and its control genes: no study well "
            "used here sits within their window."
        )
    if "S2" not in found:
        out.append("Input amount: no sample used here reads late on every gene together.")
    if "S4" not in found:
        out.append("Whole-sample efficiency: no sample used here amplifies unusually poorly.")
    if len(ctx.refs) < 3:
        out.append(
            "With fewer than three control genes, a control-gene well cannot be checked against "
            "the others."
        )
    if not ctx.replicates:
        out.append("Technical replicates: not applicable, one well per sample and gene.")
    return out


def cannot_show(ctx: TraceContext) -> list[str]:
    """What these data cannot show (plain words)."""
    out = [
        "A single target well that is off cannot be told apart from biology without technical "
        "replicates.",
        "A fault shared by every sample of one group looks like biology (a design question).",
        "A wrong sample in the tube, RNA integrity, RT replicates and no-RT controls leave no "
        "footprint here unless annotated.",
    ]
    study = ctx.wells[ctx.wells["sample_type"] == "unkn"]
    if study["plate"].nunique() > 1 and bool(
        (study.groupby("sample")["well"].nunique() == 1).all()
    ):
        out.append(
            "Each sample sits at the same well position on every plate, so a position effect "
            "cannot be told apart from the sample."
        )
    return out


def _summary(
    ctx: TraceContext,
    facts: Facts,
    gene: str,
    call: TraceCall,
    n_flips: int,
    flip: TraceFlipSet,
    places: list[TracePlace],
) -> None:
    """The headline and the flip sentence."""
    t = facts
    rule = ctx.rule
    g = t.name("gene", gene)
    line = t.tok("rule_fold", float(2**rule.min_log2fc), "{:g}")
    alpha = t.tok("rule_alpha", float(rule.alpha), "{:g}")
    text = (
        f"{g}: {t.name('call', call_word(call.conclusion))}, {t.change('fc', call.log2fc)} in "
        f"{t.name('group_a', ctx.labels[0])} than {t.name('group_b', ctx.labels[1])} "
        f"(p {t.p('p', call.p, rule.alpha)}; the rule: at least {line}-fold and p below {alpha})."
    )
    if n_flips:
        noun = "sample changes" if n_flips == 1 else "samples each change"
        n = t.count("n_flip_single", n_flips)
        text += f" {n} {noun} the call when set aside alone: it sits close to its line."
    facts.say("summary", text)
    if flip.k is None:
        flip_text = (
            f"Setting aside the {t.count('flip_searched', flip.searched)} samples that push {g} "
            "hardest "
            "towards its line, one at a time, does not change its call."
        )
    else:
        who = t.name("flip_units", ", ".join(flip.units))
        after = t.name("flip_after", call_word(flip.call_after or "none"))
        if flip.k == 1:
            flip_text = f"One sample changes the call: set aside {who} and {g} becomes {after}."
        elif flip.exact:
            flip_text = (
                f"No single sample changes the call; {t.count('flip_k', flip.k)} together do "
                f"(every pair checked): set aside {who} and {g} becomes {after}."
            )
        else:
            flip_text = (
                "No single sample or pair changes the call (every pair checked). Setting aside "
                "the sample that pushes it hardest, one at a time, changes it after "
                f"{t.count('flip_k', flip.k)}: "
                f"{who}; {g} then becomes {after}."
            )
    facts.say("flip", flip_text)
    del places
