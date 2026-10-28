"""Planner routes: plan the next experiment from the noise this study measured.

* ``GET /api/studies/{id}/planner``: each compared gene's SD between biological units of one group
  (pooled over the groups, from the engine's per-unit values at the study's current choices:
  :func:`qpilot.qpcr.export.study_inputs`, the values the Prism bridge exports), the group sizes,
  the genes' efficiencies and how the study laid out its plates.
* ``POST /api/studies/{id}/planner``: for a change worth finding and a power, per gene the
  samples needed (:func:`qpilot.qpcr.plan.n_needed`), the samples for qPilot's rule to call it
  (:func:`qpilot.qpcr.plan.n_for_call`), what the plan's size detects (``mde_fold``) and the
  simulated chance of the right call (``simulate_calls``), power curves, the design rules
  (:func:`qpilot.qpcr.plan.plan`) and what the plan cannot detect.
* ``POST /api/studies/{id}/planner/layout`` and ``GET …/layout.csv``: every plate of the next
  experiment (:func:`qpilot.qpcr.layout.make_layout`), and the same plates as CSV.

Everything here reads; nothing is written to the study. A study of a Studio session answers
``403 blind`` until its design and curves are confirmed, as Results does.
"""

from __future__ import annotations

import math
import statistics
import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Query
from fastapi.responses import Response

from qpilot.explain.words import plural
from qpilot.qpcr import layout as lay
from qpilot.qpcr import plan as qplan
from qpilot.web.context import AppContext, Ctx, api_error
from qpilot.web.contract_planner import (
    PlanBudget,
    PlanControls,
    PlanCurvePoint,
    PlanEfficiency,
    PlanGene,
    PlanLayoutBalance,
    PlanLayoutBody,
    PlanLayoutEstimate,
    PlanLayoutPlate,
    PlanLayoutView,
    PlanLayoutWell,
    PlannerBody,
    PlannerGene,
    PlannerGroup,
    PlannerView,
    PlanPowerCurve,
    PlanSpread,
    PlanStudyPlates,
    PlanView,
)

router = APIRouter(tags=["planner"])

CURVE_REPS = 4_000  # simulated studies per curve point (the table uses plan.SIM_REPS)
CURVE_POINTS = 26
MAX_CURVES = 8
MAX_CACHED = 8
SIGMA_SOURCE = (
    "SD of log2 relative quantity between biological units of the same group, pooled over the "
    "two groups, from this study's own per-unit values (the engine's normalisation by the "
    "control genes, at the choices currently in force). It is the spread a new experiment of "
    "the same kind should expect; the interval shows how well this study pins it down."
)
NO_INPUT = (
    "qPilot cannot measure this study's noise: {reason}. The planner needs the study's input "
    "file, as the Prism export does."
)


# ---- the study's own noise (cached per study, results file and chain head) -------------------


@dataclass(frozen=True)
class Measured:
    """What the study measured, as the planner needs it."""

    groups: tuple[tuple[str, int], ...]
    sigma: dict[str, tuple[float, int, tuple[int, ...]]]  # gene -> (sd, df, n per group)
    refs: tuple[str, ...]
    plates: PlanStudyPlates | None


_lock = threading.Lock()
_building: dict[tuple, threading.Lock] = {}
_measured: OrderedDict[tuple, Measured] = OrderedDict()


def _key(ctx: AppContext, study_id: str) -> tuple:
    path = ctx.store.workspace(study_id) / "results.json"
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        stamp = 0
    return (str(ctx.store.root), study_id, stamp, ctx.store.chain_head(study_id))


def measured(ctx: AppContext, study_id: str) -> Measured:
    """The study's per-gene noise and plates, rebuilt once per results file and chain head."""
    key = _key(ctx, study_id)
    with _lock:
        if key in _measured:
            _measured.move_to_end(key)
            return _measured[key]
        gate = _building.setdefault(key, threading.Lock())
    with gate:  # one rebuild per key, however many requests arrive together
        with _lock:
            if key in _measured:
                return _measured[key]
        try:
            value = _measure(ctx, study_id)
        finally:
            with _lock:
                _building.pop(key, None)
        with _lock:
            _measured[key] = value
            while len(_measured) > MAX_CACHED:
                _measured.popitem(last=False)
    return value


def _measure(ctx: AppContext, study_id: str) -> Measured:
    from qpilot.qpcr.export import ExportError, study_inputs

    try:
        inputs = study_inputs(ctx.store, study_id, read_only=True)
        table = inputs.table("column")
    except ExportError as err:
        raise api_error(409, "unavailable", NO_INPUT.format(reason=str(err))) from err
    order = tuple(inputs.group_order)
    sizes = tuple(
        (g, int(table.loc[table["group"] == g, "biological_unit"].nunique())) for g in order
    )
    sigma: dict[str, tuple[float, int, tuple[int, ...]]] = {}
    for gene, block in table.groupby("gene", sort=False):
        values = [block.loc[block["group"] == g, "log2_rq"].dropna().tolist() for g in order]
        try:
            sd, df = qplan.pooled_sd(values)
        except ValueError:
            continue  # no group with two values: no noise to plan with
        if sd > 0:
            sigma[str(gene)] = (sd, df, tuple(len(v) for v in values))
    return Measured(
        groups=sizes, sigma=sigma, refs=tuple(inputs.refs), plates=_study_plates(inputs.data)
    )


def _study_plates(data) -> PlanStudyPlates | None:  # noqa: ANN001 (a pandas frame)
    """How the study laid out its plates, from its per-well table."""
    if data is None or not {"run_id", "sample_type", "target", "sample"} <= set(data.columns):
        return None
    runs = data.groupby("run_id")
    if not len(runs):
        return None
    unknown = data[data["sample_type"] == "unkn"]
    targets = unknown.groupby("run_id")["target"].nunique()
    samples = unknown.groupby("run_id")["sample"].nunique()
    all_samples = unknown["sample"].nunique()
    controls: dict[str, float] = {}
    for kind in sorted(set(data["sample_type"]) - {"unkn"}):
        per = data[data["sample_type"] == kind].groupby("run_id").size()
        per = per.reindex(list(runs.groups), fill_value=0)
        controls[str(kind)] = float(statistics.median(per.tolist()))
    n_plates = int(data["run_id"].nunique())
    wells = int(runs.size().max())
    maxim = (
        bool(len(targets))
        and bool((targets == 1).all())
        and (float(samples.min()) >= 0.9 * all_samples)
    )
    t_med = float(statistics.median(targets.tolist())) if len(targets) else 0.0
    s_med = float(statistics.median(samples.tolist())) if len(samples) else 0.0
    parts = [f"{n_plates} plate{'s' * (n_plates != 1)} of up to {wells} wells"]
    if maxim:
        parts.append(
            f"each held one gene for (nearly) all {all_samples} samples: sample maximisation, "
            "so each gene's comparison was made within one run"
        )
    else:
        parts.append(f"a median {t_med:g} gene(s) and {s_med:g} samples per plate")
    if controls:
        words = {"std": "standard", "ntc": "NTC", "nrt": "NRT", "pos": "positive control"}
        parts.append(
            "per plate "
            + ", ".join(
                f"{v:g} {words.get(k, k)} well{'s' * (v != 1)}" for k, v in controls.items()
            )
        )
    return PlanStudyPlates(
        n_plates=n_plates,
        wells_per_plate=wells,
        targets_per_plate=t_med,
        samples_per_plate=s_med,
        controls_per_plate=controls,
        sample_maximisation=maxim,
        text="This study: " + "; ".join(parts) + ".",
    )


# ---- helpers ------------------------------------------------------------------------------------


def _study(ctx: AppContext, study_id: str) -> None:
    """The id, the study and the blind rule, exactly as Results checks them."""
    from qpilot.web.routers.results import study

    study(ctx, study_id)


def _spread(values: Sequence[float]) -> PlanSpread | None:
    v = sorted(float(x) for x in values if math.isfinite(float(x)))
    if not v:
        return None
    q = statistics.quantiles(v, n=4, method="inclusive") if len(v) > 1 else [v[0]] * 3
    return PlanSpread(n=len(v), min=v[0], q1=q[0], median=q[1], q3=q[2], max=v[-1])


def _efficiency(result) -> PlanEfficiency:  # noqa: ANN001 (a StudyResult)
    from qpilot.qpcr.design_checks import EFFICIENCY_RANGE

    eff = {g: float(e) for g, e in (result.efficiency or {}).items() if e is not None}
    lo, hi = EFFICIENCY_RANGE
    outside = sorted(g for g, e in eff.items() if not lo <= e - 1 <= hi)
    spread = _spread(list(eff.values()))
    if spread is None:
        text = "This study has no efficiency per gene."
    else:
        text = (
            f"Efficiency per gene (LinRegPCR, the median over its plates): median "
            f"{spread.median:.2f}, from {spread.min:.2f} to {spread.max:.2f} (2.00 is a perfect "
            f"doubling). {len(outside)} of {spread.n} fall outside "
            f"{lo * 100:.0f}–{hi * 100:.0f} %: check those assays with a standard curve before "
            "the next experiment (a warning only, as in the engine's design checks)."
        )
    return PlanEfficiency(spread=spread, range=(lo, hi), outside=outside, text=text)


def _rule(ctx: AppContext, study_id: str):  # noqa: ANN202 (ConclusionRule)
    from qpilot.qpcr.contrast import ConclusionRule

    return ConclusionRule(**ctx.store.get(study_id).conclusion_rule)


def _headline(ctx: AppContext, study_id: str) -> list[str]:
    from qpilot.web.results_views import headline_genes

    result = ctx.store.get(study_id)
    return headline_genes(result, ctx.store.cards(study_id), ctx.store)


def _slug(label: str) -> str:
    """A group label as the layout may write it (the label itself when it is already safe)."""
    import re

    text = re.sub(r"[^\w()\-. ]", "_", str(label)).strip().lstrip("-")[:64]
    return text or "group"


@lru_cache(maxsize=50_000)
def _sim(
    fc: float, sd: float, n: int, alpha: float, min_log2fc: float, reps: int, n_other: int | None
) -> tuple[float, float]:
    return qplan.simulate_calls(fc, sd, n, alpha, min_log2fc, reps, n_other)


@lru_cache(maxsize=4_096)
def _n_call(fc: float, sd: float, power: float, alpha: float, min_log2fc: float) -> int | None:
    return qplan.n_for_call(fc, sd, power, alpha, min_log2fc, n_max=lay.MAX_SAMPLES_PER_GROUP)


def _pct(x: float) -> str:
    return f"{round(100 * x):d} %"


def _fold(x: float) -> str:
    return f"{x:.2f}×" if x < 10 else f"{x:.1f}×"


# ---- GET: what the study measured ----------------------------------------------------------------


@router.get("/studies/{study_id}/planner", response_model=PlannerView)
def get_planner(study_id: str, ctx: Ctx) -> PlannerView:
    """The study's noise per gene, its group sizes and efficiencies, and the planner's defaults."""
    _study(ctx, study_id)
    m = measured(ctx, study_id)
    result = ctx.store.get(study_id)
    rule = _rule(ctx, study_id)
    headline = _headline(ctx, study_id)
    eff = _efficiency(result)
    genes = []
    for gene, (sd, df, n) in m.sigma.items():
        contrast = result.contrasts.get(gene)
        if contrast is None:
            continue
        e = (result.efficiency or {}).get(gene)
        genes.append(
            PlannerGene(
                gene=gene,
                sigma=sd,
                sigma_ci=qplan.sigma_interval(sd, df),
                df=df,
                n=list(n),
                fc=contrast.fc,
                conclusion=contrast.conclusion,
                efficiency=e,
                efficiency_outside=gene in eff.outside,
                headline=gene in headline,
            )
        )
    sizes = [n for _, n in m.groups]
    spread = _spread([g.sigma for g in genes])
    if spread is None:
        raise api_error(
            409,
            "unavailable",
            "No compared gene has two biological units in a group, so there is no noise to "
            "plan with.",
        )
    focus = [g for g in headline if g in m.sigma] or [genes[0].gene]
    return PlannerView(
        study_id=study_id,
        head=ctx.store.chain_head(study_id),
        groups=[PlannerGroup(label=g, n=n) for g, n in m.groups],
        n_equivalent=qplan.balanced_equivalent(*sizes[:2]) if len(sizes) >= 2 else float(sizes[0]),
        alpha=rule.alpha,
        min_fold=2.0**rule.min_log2fc,
        rule_text=rule.describe(),
        sigma_source=SIGMA_SOURCE,
        genes=genes,
        sigma=spread,
        refs=list(m.refs),
        candidates=list(result.genorm.M_initial),
        headline=headline,
        efficiency=eff,
        plates=m.plates,
        fold_note=qplan.fold_words(rule.min_log2fc, rule.alpha),
        defaults=PlannerBody(
            fold=qplan.default_fold(rule.min_log2fc),
            alpha=rule.alpha,
            genes=focus,
            refs=list(m.refs),
            wells_per_plate=384 if m.plates and m.plates.wells_per_plate > 96 else 96,
        ),
    )


# ---- POST: the plan ---------------------------------------------------------------------------


def _focus(body_genes: list[str] | None, m: Measured, headline: list[str]) -> list[str]:
    if body_genes is None:
        chosen = [g for g in headline if g in m.sigma] or list(m.sigma)[:1]
    else:
        chosen = list(dict.fromkeys(str(g) for g in body_genes))
        unknown = [g for g in chosen if g not in m.sigma]
        if unknown:
            raise api_error(
                422,
                "bad_request",
                f"{', '.join(unknown[:5])}: not a compared gene of this study with a measured "
                "noise. Choose genes from the table.",
            )
    return chosen


def _refs(body_refs: list[str] | None, m: Measured, ctx: AppContext, study_id: str) -> list[str]:
    if body_refs is None:
        return list(m.refs)
    allowed = set(m.refs) | set(ctx.store.get(study_id).genorm.M_initial) | set(m.sigma)
    refs = list(dict.fromkeys(str(r) for r in body_refs))
    unknown = [r for r in refs if r not in allowed]
    if unknown:
        raise api_error(
            422,
            "bad_request",
            f"{', '.join(unknown[:5])}: not a gene of this study. Reference genes come from the "
            "study's panel.",
        )
    return refs


def _spec(
    m: Measured,
    n: int,
    genes: Sequence[str],
    refs: Sequence[str],
    replicates: int,
    wells: int,
    controls: PlanControls,
    seed: int = 1,
) -> lay.LayoutSpec:
    return lay.LayoutSpec(
        groups=tuple((_slug(g), n) for g, _ in m.groups),
        genes=tuple(genes),
        refs=tuple(refs),
        replicates=replicates,
        plate_size=wells,
        ntc=controls.ntc,
        nrt=controls.nrt,
        standards=controls.standards,
        calibrator=controls.calibrator,
        seed=seed,
    )


def _grid(top: int, marks: Sequence[int]) -> list[int]:
    """Group sizes from 2 to ``top`` on a log scale, with the marked sizes included."""
    top = max(top, 4)
    ratio = (top / 2) ** (1 / (CURVE_POINTS - 1))
    sizes = {round(2 * ratio**i) for i in range(CURVE_POINTS)}
    sizes |= {int(x) for x in marks if 2 <= x <= top}
    return sorted(s for s in sizes if 2 <= s <= top)


@router.post("/studies/{study_id}/planner", response_model=PlanView)
def post_planner(study_id: str, body: PlannerBody, ctx: Ctx) -> PlanView:
    """The plan: samples needed, what a size detects, the right call's chance, curves, rules."""
    _study(ctx, study_id)
    m = measured(ctx, study_id)
    rule = _rule(ctx, study_id)
    alpha = body.alpha if body.alpha is not None else rule.alpha
    k = rule.min_log2fc
    fold = float(body.fold) if body.fold is not None else qplan.default_fold(k)
    power = float(body.power)
    try:
        qplan.plan(fold, 1.0, None, alpha, power)  # the same input checks as `qpilot plan`
    except ValueError as err:
        raise api_error(422, "bad_request", f"{str(err)[:1].upper()}{str(err)[1:]}.") from err
    headline = _headline(ctx, study_id)
    focus = _focus(body.genes, m, headline)
    refs = _refs(body.refs, m, ctx, study_id)
    target = max(fold, 1 / fold)
    min_fold = 2.0**k
    sizes = [n for _, n in m.groups]

    need = {g: qplan.n_needed(fold, sd, alpha, power) for g, (sd, _, _) in m.sigma.items()}
    for_call = {g: _n_call(fold, m.sigma[g][0], power, alpha, k) for g in focus}
    if body.n_per_group is not None:
        n_plan = int(body.n_per_group)
        reason = "the size you chose"
    else:
        wanted = [for_call[g] or need[g] for g in focus]
        n_plan = max(2, min(max(wanted), lay.MAX_SAMPLES_PER_GROUP))
        reached = [g for g in focus if for_call[g] is not None]
        if reached:
            reason = (
                f"the size at which qPilot's rule calls a {_fold(target)} change with "
                f"{_pct(power)} power in every chosen gene"
            )
        else:
            reason = (
                f"the size at which a {_fold(target)} change reaches p < {alpha:g} with "
                f"{_pct(power)} power in every chosen gene"
            )
        if max(wanted) > lay.MAX_SAMPLES_PER_GROUP:
            reason += f" (capped at {lay.MAX_SAMPLES_PER_GROUP})"

    rows = []
    for gene, (sd, _, n_gene) in m.sigma.items():
        sig, called = _sim(fold, sd, n_plan, alpha, k, qplan.SIM_REPS, None)
        if len(n_gene) >= 2 and min(n_gene[:2]) >= 2:
            cur_mde = qplan.mde_fold_groups(n_gene[0], n_gene[1], sd, alpha, power)
            cur_called = _sim(fold, sd, n_gene[0], alpha, k, qplan.SIM_REPS, n_gene[1])[1]
        else:
            cur_mde, cur_called = float("inf"), 0.0
        mde = qplan.mde_fold(n_plan, sd, alpha, power)
        is_focus = gene in focus
        cannot: list[str] = []
        if is_focus:
            cannot = qplan.plan(fold, sd, n_plan, alpha, power, min_log2fc=k).cannot_detect
        rows.append(
            PlanGene(
                gene=gene,
                sigma=sd,
                focus=is_focus,
                n_needed=need[gene],
                n_for_call=for_call.get(gene),
                call_reachable=(for_call[gene] is not None) if is_focus else None,
                mde_fold=mde,
                p_significant=sig,
                p_called=called,
                current_mde_fold=cur_mde if math.isfinite(cur_mde) else 0.0,
                current_p_called=cur_called,
                detectable=mde <= target,
                cannot_detect=cannot,
            )
        )

    n_eq = qplan.balanced_equivalent(*sizes[:2]) if len(sizes) >= 2 else float(sizes[0])
    marks = [n_plan, math.ceil(n_eq)] + [need[g] for g in focus]
    marks += [v for v in for_call.values() if v is not None]
    top = min(lay.MAX_SAMPLES_PER_GROUP, max(20, 2 * max(marks), math.ceil(1.25 * n_eq)))
    grid = _grid(top, marks)
    curves = [
        PlanPowerCurve(
            gene=g,
            sigma=m.sigma[g][0],
            points=[
                PlanCurvePoint(n=n, p_significant=s, p_called=c)
                for n in grid
                for s, c in [_sim(fold, m.sigma[g][0], n, alpha, k, CURVE_REPS, None)]
            ],
            n_needed=need[g],
            n_for_call=for_call[g],
        )
        for g in focus[:MAX_CURVES]
    ]

    ok = [r for r in rows if r.focus and r.detectable]
    words = f"{len(ok)} of {len(focus)} chosen gene{'s' * (len(focus) != 1)}"
    called_best = max((r.p_called for r in rows if r.focus), default=0.0)
    headline_text = (
        f"At {n_plan} per group, a {_fold(target)} change reaches p < {alpha:g} with "
        f"{_pct(power)} power in {words}; qPilot's rule (p < {alpha:g} and at least "
        f"{min_fold:g}-fold) calls it up to {_pct(called_best)} of the time."
    )
    ceiling = None
    if target <= min_fold * (1 + 1e-9):
        ceiling = (
            f"A true {_fold(target)} change is at or below qPilot's {min_fold:g}-fold threshold: "
            f"the rule calls it only when noise makes it look {min_fold:g}-fold or more (about "
            "half the time for exactly that change, rarely for less), however many samples you "
            "run. Plan for the smallest change you need called, above the threshold, or change "
            "the conclusion rule before the experiment."
        )

    estimate, layout_error, rules = None, None, []
    try:
        shape = lay.plan_shape(
            _spec(m, n_plan, focus, refs, body.replicates, body.wells_per_plate, body.controls)
        )
        estimate = PlanLayoutEstimate(
            plates=shape.n_plates,
            panels=len(shape.panels),
            batches=shape.batches,
            samples_per_plate=shape.samples_per_plate,
            calibrated=shape.calibrated,
            wells=shape.n_plates * body.wells_per_plate,
        )
        rules = qplan.plan(
            fold,
            m.sigma[focus[0]][0],
            n_plan,
            alpha,
            power,
            n_plates=shape.n_plates,
            calibrator_on_every_plate=shape.batches == 1 or shape.calibrated,
            n_candidate_refs=len(refs),
            min_log2fc=k,
        ).rules
    except lay.LayoutError as err:
        layout_error = f"{str(err)[:1].upper()}{str(err)[1:]}."
        rules = qplan.plan(fold, 1.0, None, alpha, power, n_candidate_refs=len(refs)).rules

    budget = None
    if body.plates is not None:
        budget = _budget(m, body, focus, refs)

    cannot = [line for r in rows if r.focus for line in r.cannot_detect]
    return PlanView(
        study_id=study_id,
        head=ctx.store.chain_head(study_id),
        fold=fold,
        target=target,
        power=power,
        alpha=alpha,
        min_fold=min_fold,
        n_plan=n_plan,
        n_plan_reason=reason,
        genes=rows,
        focus=focus,
        refs=refs,
        curves=curves,
        curve_reps=CURVE_REPS,
        table_reps=qplan.SIM_REPS,
        n_current=sizes,
        n_equivalent=n_eq,
        headline=headline_text,
        ceiling=ceiling,
        cannot_detect=cannot,
        rules=rules,
        layout=estimate,
        layout_error=layout_error,
        budget=budget,
    )


def _budget(m: Measured, body: PlannerBody, focus: list[str], refs: list[str]) -> PlanBudget:
    """The most samples per group whose layout fits in the plates available."""
    plates = int(body.plates or 0)

    def fits(n: int) -> bool:
        spec = _spec(m, n, focus, refs, body.replicates, body.wells_per_plate, body.controls)
        try:
            return lay.plates_needed(spec) <= plates
        except lay.LayoutError:
            return False

    n_fit = None
    lo, hi = 1, lay.MAX_SAMPLES_PER_GROUP + 1
    if fits(2):
        lo = 2
        while hi - lo > 1:  # plates needed grows with the samples
            mid = (lo + hi) // 2
            if fits(mid):
                lo = mid
            else:
                hi = mid
        n_fit = lo
    where = f"{plates} plate{'s' * (plates != 1)} of {body.wells_per_plate} wells"
    if n_fit is None:
        text = (
            f"{where} cannot hold two samples per group of these "
            f"{plural(len(focus), 'gene')}, {plural(len(refs), 'reference gene')} and controls."
        )
    else:
        text = (
            f"{where} hold up to {n_fit} samples per group of these {plural(len(focus), 'gene')} "
            f"with {plural(len(refs), 'reference gene')}, "
            f"{plural(body.replicates, 'replicate')} and the controls."
        )
    return PlanBudget(plates=plates, n_fit=n_fit, text=text)


# ---- the plates -------------------------------------------------------------------------------


def _layout(ctx: AppContext, study_id: str, body: PlanLayoutBody) -> tuple[Measured, lay.Layout]:
    _study(ctx, study_id)
    m = measured(ctx, study_id)
    allowed = set(m.sigma) | set(m.refs) | set(ctx.store.get(study_id).genorm.M_initial)
    unknown = [g for g in [*body.genes, *(body.refs or [])] if g not in allowed]
    if unknown:
        raise api_error(
            422,
            "bad_request",
            f"{', '.join(unknown[:5])}: not a gene of this study. Choose genes from its panel.",
        )
    refs = list(body.refs) if body.refs is not None else list(m.refs)
    controls = PlanControls(
        ntc=body.ntc, nrt=body.nrt, standards=body.standards, calibrator=body.calibrator
    )
    spec = _spec(
        m, body.n_per_group, body.genes, refs, body.replicates, body.wells_per_plate, controls,
        body.seed,
    )  # fmt: skip
    try:
        return m, lay.make_layout(spec)
    except lay.LayoutError as err:
        raise api_error(422, "bad_request", f"{str(err)[:1].upper()}{str(err)[1:]}.") from err


def _csv_name(study_id: str, seed: int) -> str:
    return f"qpilot-plate-layout-{study_id}-seed{seed}.csv"


@router.post("/studies/{study_id}/planner/layout", response_model=PlanLayoutView)
def post_layout(study_id: str, body: PlanLayoutBody, ctx: Ctx) -> PlanLayoutView:
    """Every plate of the next experiment: balanced, randomised (seeded), controls on each."""
    m, layout = _layout(ctx, study_id, body)
    spec, shape, b = layout.spec, layout.shape, layout.balance
    by_number = {p.number: p for p in b.plates}
    plates = []
    for plate in layout.plates:
        pb = by_number[plate.number]
        plates.append(
            PlanLayoutPlate(
                number=plate.number,
                name=plate.name,
                panel=plate.panel,
                batch=plate.batch,
                genes=list(plate.genes),
                refs=list(plate.refs),
                wells=[
                    PlanLayoutWell(
                        well=w.well,
                        sample=w.sample,
                        group=w.group or None,
                        target=w.target,
                        type=w.type,  # type: ignore[arg-type]
                        replicate=w.replicate,
                    )
                    for w in plate.wells
                ],
                wells_used=pb.wells_used,
                wells_free=pb.wells_free,
                samples=pb.samples,
                groups_present=pb.groups_present,
                refs_present=pb.refs_present,
                controls=pb.controls,
                edge_share=pb.edge_share,
            )
        )
    rules = qplan.plan(
        2.0,
        1.0,
        None,
        n_plates=shape.n_plates,
        calibrator_on_every_plate=shape.batches == 1 or shape.calibrated,
        n_candidate_refs=len(spec.refs),
    ).rules
    params = body.model_dump(mode="json", exclude_none=True)
    params = {k: (str(v).lower() if isinstance(v, bool) else v) for k, v in params.items()}
    query = urlencode(params, doseq=True)
    return PlanLayoutView(
        study_id=study_id,
        seed=spec.seed,
        groups=[PlannerGroup(label=g, n=n) for g, n in spec.groups],
        genes=list(spec.genes),
        refs=list(spec.refs),
        replicates=spec.replicates,
        wells_per_plate=spec.plate_size,
        panels=[list(p) for p in shape.panels],
        batches=shape.batches,
        samples_per_plate=shape.samples_per_plate,
        calibrated=shape.calibrated,
        plates=plates,
        balance=PlanLayoutBalance(
            every_plate_every_group=b.every_plate_every_group,
            plates_with_one_group=list(b.plates_with_one_group),
            refs_on_every_plate=b.refs_on_every_plate,
            controls_on_every_plate=b.controls_on_every_plate,
            each_reaction_once=b.each_reaction_once,
            group_plate_association=b.group_plate_association,
            max_share_gap=b.max_share_gap,
            wells_total=b.wells_total,
            wells_samples=b.wells_samples,
            wells_controls=b.wells_controls,
            wells_free=b.wells_free,
        ),
        notes=list(layout.notes),
        warnings=list(layout.warnings),
        rules=rules,
        csv_url=f"/api/studies/{study_id}/planner/layout.csv?{query}",
        csv_name=_csv_name(study_id, spec.seed),
    )


@router.get(
    "/studies/{study_id}/planner/layout.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "The layout as CSV."}},
)
def get_layout_csv(study_id: str, params: Annotated[PlanLayoutBody, Query()], ctx: Ctx) -> Response:
    """The same plates as CSV (plate, well, sample, group, target, type) to import."""
    _, layout = _layout(ctx, study_id, params)
    return Response(
        content=lay.layout_csv(layout),
        media_type="text/csv; charset=utf-8",
        headers={
            "content-disposition": f'attachment; filename="{_csv_name(study_id, layout.spec.seed)}"'
        },
    )
