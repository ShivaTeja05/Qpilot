"""Trace routes: follow a result down to the samples, wells and plates that drive it.

``GET /studies/{id}/trace`` (the study: genes by fragility, the samples behind the most calls),
``GET /studies/{id}/trace/{gene}`` (one gene's call followed down to its wells) and
``POST /studies/{id}/trace/{gene}/without`` (the call recomputed with samples set aside: a
what-if, nothing is applied). Every number is the engine's (:mod:`qpilot.trace`), for the
analysis in use: each Decision Card's applied option, the planned one elsewhere, exactly the
call the Results section shows.

A study analysed from a Studio session answers ``403 blind`` until its design and curves are
confirmed (the results routes' rule). The first trace of a study rebuilds its model from the
input file (about a second on the demo, more under load): it runs as a ``trace.load`` job, and a
request that finds it still running answers ``409 loading`` with the job to follow. After that,
traces are closed-form arithmetic on the kept model (tens of milliseconds a gene); a decision
that changes the analysis in use is traced again from the same model.
"""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict
from typing import Annotated, Any

from fastapi import APIRouter, Query

from qpilot.trace import TraceContext, TraceError, build_context, model_for_study
from qpilot.trace.gene import trace_gene
from qpilot.trace.study import plate_wells, trace_study, without_samples
from qpilot.web import results_views as rv
from qpilot.web.context import AppContext, Ctx, api_error
from qpilot.web.contract import JobView
from qpilot.web.contract_trace import (
    TraceGeneView,
    TraceLoaded,
    TracePlateView,
    TraceStudyView,
    TraceWithoutBody,
    TraceWithoutView,
)
from qpilot.web.jobs import JobError, Progress

router = APIRouter(tags=["trace"])
JOB_RESULTS = {"trace.load": TraceLoaded}

LOAD_S = 3.0  # measured: ~1 s on the demo when the laptop is idle; jobs share it under load
WAIT_S = 1.5  # a request waits this long for a load before answering 409 loading
FAILED_S = 10.0  # a load that just failed is reported, not retried, for this long
KEEP = 4
GRID_TOLERANCE = 1e-8  # grid.csv keeps ten significant digits

_lock = threading.Lock()
_build = threading.Lock()
_models: OrderedDict[tuple[str, tuple[str, int]], Any] = OrderedDict()
_contexts: OrderedDict[tuple[Any, ...], TraceContext] = OrderedDict()
_choices: OrderedDict[tuple[Any, ...], tuple[dict[str, str] | None, Any]] = OrderedDict()


# ---- the kept model and context ------------------------------------------------------------


def _visible(ctx: AppContext, study_id: str) -> str | None:
    """The results routes' checks (id, study, blind); returns the study's session, if any."""
    from qpilot.web.routers.results import compares_groups, study

    sid = study(ctx, study_id)
    compares_groups(ctx, study_id, "Trace")
    return sid


def _version(ctx: AppContext, study_id: str) -> tuple[str, int]:
    """Which store, and when its results last changed (a re-analysis means a new model)."""
    path = ctx.store.workspace(study_id) / "results.json"
    try:
        return str(ctx.store.root), path.stat().st_mtime_ns
    except OSError:
        return str(ctx.store.root), 0


def _choice(ctx: AppContext, study_id: str) -> tuple[dict[str, str] | None, Any]:
    """The options in use (grid text per dimension), and the grid cell they name.

    Kept per chain head and results version: only a decision or a re-analysis changes them.
    """
    key = (study_id, ctx.store.chain_head(study_id), _version(ctx, study_id))
    with _lock:
        if key in _choices:
            return _choices[key]
    found = _find_choice(ctx, study_id)
    with _lock:
        _choices[key] = found
        while len(_choices) > 4 * KEEP:
            _choices.popitem(last=False)
    return found


def _find_choice(ctx: AppContext, study_id: str) -> tuple[dict[str, str] | None, Any]:
    result = ctx.store.get(study_id)
    grid = rv.load_grid(ctx.store, result)
    if grid is None or grid.planned is None:
        return None, None
    cards = ctx.store.cards(study_id)
    cell = rv.current_cell(grid, cards, rv.card_options(grid, cards))
    if cell == grid.planned:
        return None, None
    return {dim: grid.options[dim][idx] for dim, idx in cell.items()}, (grid, cell)


def _labels(
    ctx: AppContext, study_id: str, comparison: str | None = None
) -> tuple[str, str] | None:
    if comparison:  # another comparison: the context names its own two groups
        return None
    labels = [g.label for g in rv.groups(ctx.store.get(study_id))]
    return (labels[0], labels[1]) if len(labels) == 2 else ("group A", "group B")


def comparison_of(ctx: AppContext, study_id: str, comparison: str | None) -> str | None:
    """A comparison id the study has (404 in words otherwise); None for the first one."""
    from qpilot.web.compare_views import outcome_of
    from qpilot.web.routers.results import comparison_ok, known_comparison

    wanted = comparison_ok(comparison)
    if wanted is None:
        return None
    with known_comparison():
        outcome = outcome_of(ctx.store.get(study_id), wanted)
    return None if outcome is None or outcome.primary else outcome.id


def _model(ctx: AppContext, study_id: str) -> Any:
    key = (study_id, _version(ctx, study_id))
    with _lock:
        if key in _models:
            _models.move_to_end(key)
            return _models[key]
    model = model_for_study(ctx.store, study_id)
    with _lock:
        _models[key] = model
        while len(_models) > KEEP:
            _models.popitem(last=False)
    return model


def _cached_model(ctx: AppContext, study_id: str) -> bool:
    with _lock:
        return (study_id, _version(ctx, study_id)) in _models


def _context(ctx: AppContext, study_id: str, comparison: str | None = None) -> TraceContext:
    """The study's trace context for the analysis in use (the model must be kept already).

    ``comparison``: a study with several comparisons, the one traced (None: the first).
    """
    choice, at = _choice(ctx, study_id)
    key = (study_id, _version(ctx, study_id), tuple(sorted((choice or {}).items())), comparison)
    with _lock:
        if key in _contexts:
            _contexts.move_to_end(key)
            return _contexts[key]
    with _build:
        with _lock:
            if key in _contexts:
                return _contexts[key]
        built = build_context(
            _model(ctx, study_id),
            study_id,
            choice,
            _labels(ctx, study_id, comparison),
            comparison=comparison,
        )
        if at is not None:
            grid, cell = at
            if comparison:
                from qpilot.web.compare_views import comparison_grid

                grid = comparison_grid(ctx.store, study_id, comparison, grid)
            if grid is not None:
                _same_as_grid(built, grid, cell)
        with _lock:
            _contexts[key] = built
            while len(_contexts) > KEEP:
                _contexts.popitem(last=False)
    return built


def _same_as_grid(trace: TraceContext, grid: Any, cell: dict[str, int]) -> None:
    """At a person's options, the traced numbers must be the grid's (what Results shows)."""
    rows = grid.cell(cell)
    for j, gene in enumerate(trace.items):
        if gene not in rows.index:
            continue
        stored = float(rows.at[gene, "log2fc"])
        if not math.isclose(stored, float(trace.base.diff[j]), abs_tol=GRID_TOLERANCE):
            raise TraceError(
                f"Trace could not reproduce {gene}'s result at the options in use; nothing is "
                "traced."
            )


def _ready(ctx: AppContext, study_id: str, comparison: str | None = None) -> TraceContext:
    """The context, loading the model in a ``trace.load`` job the first time (409 loading)."""
    if _cached_model(ctx, study_id):
        return _traceable(lambda: _context(ctx, study_id, comparison))
    if ctx.store.source(study_id) is None:
        raise api_error(
            409,
            "no_source",
            "The study's input file is missing or has changed since it was analysed, so its "
            "wells cannot be traced. Open the file again to trace it.",
        )
    failed = ctx.jobs.latest("trace.load", study_id)
    if failed is not None and failed.status == "failed" and failed.error:
        if time.time() - (failed.finished or 0) < FAILED_S:
            raise api_error(
                409, failed.error.get("code", "failed"), failed.error.get("message", "")
            )

    def work(progress: Progress) -> dict[str, Any]:
        start = time.perf_counter()
        progress("Re-reading the study's wells from its file", 0.1)
        try:
            _model(ctx, study_id)
            progress("Setting every sample aside, one and two at a time", 0.6)
            traced = _context(ctx, study_id)
            trace_study(traced)  # every gene's flip set and every what-if, kept for the page
        except TraceError as err:
            raise JobError("not_traceable", str(err)) from err
        return TraceLoaded(
            study_id=study_id,
            head=ctx.store.chain_head(study_id),
            n_genes=len(traced.items),
            seconds=round(time.perf_counter() - start, 2),
        ).model_dump(mode="json")

    job = ctx.jobs.submit(
        "trace.load",
        work,
        title="Reading the study's wells for Trace",
        key=study_id,
        typical_s=LOAD_S,
    )
    deadline = time.monotonic() + WAIT_S
    while job.status in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(0.05)
    if job.status == "done":
        return _traceable(lambda: _context(ctx, study_id, comparison))
    if job.status == "failed" and job.error:
        raise api_error(409, job.error.get("code", "failed"), job.error.get("message", ""))
    raise api_error(
        409,
        "loading",
        "Trace is reading the study's wells from its file (about a second the first time on the "
        "demo). It answers as soon as the job is done.",
        job=JobView(**job.view()).model_dump(mode="json"),
    )


def clear() -> None:
    """Forget every kept model, context and choice (tests; a fresh demo)."""
    with _lock:
        _models.clear()
        _contexts.clear()
        _choices.clear()


def _traceable(fn: Any) -> Any:
    try:
        return fn()
    except TraceError as err:
        raise api_error(409, "not_traceable", str(err)) from err


def _texts(texts: dict[str, str], facts: dict[str, Any]) -> dict[str, Any]:
    return {tid: rv.fact_text(tokens, facts) for tid, tokens in texts.items()}


def _gene_ok(gene: str) -> str:
    if not gene or len(gene) > 128:
        raise api_error(404, "not_found", "There is no compared gene with this name.")
    return gene


# ---- routes --------------------------------------------------------------------------------


ComparisonQuery = Annotated[
    str | None,
    Query(description="A study with several comparisons: the one to trace (its id; the first)."),
]


@router.get("/studies/{study_id}/trace", response_model=TraceStudyView)
def get_trace_study(study_id: str, ctx: Ctx, comparison: ComparisonQuery = None) -> TraceStudyView:
    """Genes by how little it takes to change their call; the samples behind the most calls."""
    sid = _visible(ctx, study_id)
    traced = _ready(ctx, study_id, comparison_of(ctx, study_id, comparison))
    out = trace_study(traced)
    return TraceStudyView(
        study_id=study_id,
        session=sid,
        head=ctx.store.chain_head(study_id),
        trace=out.data,
        texts=_texts(out.texts, out.facts),
    )


@router.get("/studies/{study_id}/trace/plate", response_model=TracePlateView)
def get_trace_plate(
    study_id: str,
    ctx: Ctx,
    run: str | None = Query(default=None, max_length=128, description="The plate (run id)."),
) -> TracePlateView:
    """Every well of one plate with Trace's flags (the plate map next to a traced well)."""
    _visible(ctx, study_id)
    if not run:
        raise api_error(422, "bad_request", "Name the plate to show (`run`).")
    traced = _ready(ctx, study_id)
    try:
        plate = plate_wells(traced, run)
    except TraceError as err:
        raise api_error(404, "not_found", str(err)) from err
    return TracePlateView(study_id=study_id, plate=plate)


@router.get("/studies/{study_id}/trace/{gene}", response_model=TraceGeneView)
def get_trace_gene(
    study_id: str, gene: str, ctx: Ctx, comparison: ComparisonQuery = None
) -> TraceGeneView:
    """One gene's call followed down to its samples, wells and plates."""
    sid = _visible(ctx, study_id)
    _gene_ok(gene)
    traced = _ready(ctx, study_id, comparison_of(ctx, study_id, comparison))
    try:
        out = trace_gene(traced, gene)
    except TraceError as err:
        raise api_error(404, "not_found", str(err), gene=gene) from err
    return TraceGeneView(
        study_id=study_id,
        session=sid,
        head=ctx.store.chain_head(study_id),
        trace=out.data,
        texts=_texts(out.texts, out.facts),
    )


@router.post("/studies/{study_id}/trace/{gene}/without", response_model=TraceWithoutView)
def post_trace_without(
    study_id: str, gene: str, body: TraceWithoutBody, ctx: Ctx, comparison: ComparisonQuery = None
) -> TraceWithoutView:
    """The call recomputed with these samples set aside together (a what-if; nothing changes)."""
    _visible(ctx, study_id)
    _gene_ok(gene)
    if not body.samples or any(not s or len(s) > 128 for s in body.samples):
        raise api_error(422, "bad_request", "Name each sample to set aside as the trace lists it.")
    traced = _ready(ctx, study_id, comparison_of(ctx, study_id, comparison))
    try:
        traced.gene_index(gene)
    except TraceError as err:
        raise api_error(404, "not_found", str(err), gene=gene) from err
    try:
        result = without_samples(traced, gene, body.samples)
    except TraceError as err:
        raise api_error(422, "bad_request", str(err)) from err
    return TraceWithoutView(study_id=study_id, head=ctx.store.chain_head(study_id), result=result)
