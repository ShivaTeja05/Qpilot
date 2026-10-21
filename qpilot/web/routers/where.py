"""Where to look: from a gene's result, a sample or a well to the places a person should look.

* ``GET /studies/{id}/where-to-look?gene=|sample=|well=PLATE:WELL`` → :class:`WhereView`: the
  places to look, ranked by what each option there does to the calls (it changes a call > it
  moves a fold change by more than its confidence interval > it changes nothing), each with the
  fingerprint checks it fails (S1-S7) and what to check. Read-only.
* ``POST /studies/{id}/where-to-look/open`` ``{kind, id, rank, expected_head}`` → a person's
  **Decide…**: the place becomes a ``trace_set_aside`` Decision Card
  (:meth:`~qpilot.core.store.StudyStore.open_card`), decided on Results like any other card: a
  choice that can change a conclusion is a person's, at every autonomy level. Opening writes no
  chain entry, and deciding the card changes no number of the study.

The engine is :mod:`qpilot.qpcr.trace` (the Gradio app's "Trace: where to look" accordion, the
CLI's ``qpilot trace`` and MCP's ``qpcr_trace``), here built for the **analysis in use** (each
Decision Card's applied option, the planned one elsewhere: what Results shows) from the model
the Trace section keeps (:mod:`qpilot.web.routers.trace`). Its numbers at that analysis must
equal the Trace section's, or nothing is shown. Blind like every result: a Studio session's
study answers ``403 blind`` until its design and curves are confirmed.
"""

from __future__ import annotations

import math
import threading
from collections import OrderedDict
from typing import Any

from fastapi import APIRouter, Query

from qpilot.core.store import CardError, StudyNotFound
from qpilot.qpcr import trace as places_engine
from qpilot.web import results_views as rv
from qpilot.web.context import AppContext, Ctx, api_error
from qpilot.web.contract_trace import (
    OpenPlaceBody,
    PlaceOpened,
    WhereAbsent,
    WhereCheck,
    WhereOption,
    WherePlace,
    WhereView,
)
from qpilot.web.routers import trace as tr

router = APIRouter(tags=["trace"])

TOP = 3
MAX_TOP = 20
MAX_ABSENT = 20
KEEP = 4
TOLERANCE = 1e-8
DECIDE_NOTE = (
    "Decide… opens that place as a Decision Card on Results. A choice that can change a "
    "conclusion is a person's, and it is kept in the decision chain with its reason; the "
    "study's numbers stay as analysed."
)
OPTION_LABELS = {
    "keep": "Keep (no change)",
    "read_from_other_refs": "Read this well from the sample's other reference wells",
    "set_aside_value": "Set this well's value aside",
    "set_aside": "Set the sample aside (every comparison)",
}
STALE = (
    "Something was decided since this trace was shown (another tab or an agent), so the places "
    "may have changed. Here is the trace again."
)
NOT_CURRENT = (
    "This analysis is no longer the session's current one (an accepted change re-ran it): "
    "trace the current results."
)

_lock = threading.Lock()
_build = threading.Lock()
_contexts: OrderedDict[tuple[Any, ...], places_engine.TraceContext] = OrderedDict()


# ---- the context at the analysis in use -----------------------------------------------------


def _context(ctx: AppContext, study_id: str) -> places_engine.TraceContext:
    """The place-to-look context for the analysis in use (the kept model loaded first)."""
    from qpilot.trace.context import cell_of

    page = tr._ready(ctx, study_id)  # the Trace section's context: 409 loading the first time
    choice, _ = tr._choice(ctx, study_id)
    key = (study_id, tr._version(ctx, study_id), tuple(sorted((choice or {}).items())))
    with _lock:
        if key in _contexts:
            _contexts.move_to_end(key)
            return _contexts[key]
    with _build:
        with _lock:
            if key in _contexts:
                return _contexts[key]
        model = tr._model(ctx, study_id)
        result = ctx.store.get(study_id)
        try:
            cell = cell_of(model, choice)
            built = places_engine.build_context(
                model.inputs.primary_table, model, robustness=result.robustness, cell=cell
            )
        except (places_engine.TraceError, ValueError, KeyError) as err:
            raise api_error(409, "not_traceable", f"Nothing is traced: {err}") from err
        _same_numbers(built, page)
        with _lock:
            _contexts[key] = built
            while len(_contexts) > KEEP:
                _contexts.popitem(last=False)
    return built


def _same_numbers(built: places_engine.TraceContext, page: Any) -> None:
    """Both Trace engines must give the same fold changes at the analysis in use."""
    for j, gene in enumerate(built.items):
        try:
            k = page.gene_index(gene)
        except Exception:  # a gene the Trace section does not compare is not cross-checked
            continue
        ours, theirs = float(built.base.log2fc[j]), float(page.base.diff[k])
        if math.isnan(ours) and math.isnan(theirs):
            continue
        if not math.isclose(ours, theirs, abs_tol=TOLERANCE):
            raise api_error(
                409,
                "not_traceable",
                f"Where to look could not reproduce {gene}'s result at the options in use; "
                "nothing is traced.",
            )


def clear() -> None:
    """Forget every kept context (tests; a fresh demo)."""
    with _lock:
        _contexts.clear()


# ---- one trace ------------------------------------------------------------------------------


def _root(gene: str | None, sample: str | None, well: str | None) -> dict[str, str]:
    given = [(k, v.strip()) for k, v in (("gene", gene), ("sample", sample), ("well", well)) if v]
    given = [(k, v) for k, v in given if v]
    if len(given) != 1:
        raise api_error(
            422,
            "bad_request",
            "Name exactly one thing to trace: a gene, a sample, or a well as PLATE:WELL "
            "(for example HMBS_20080318:K22).",
        )
    kind, value = given[0]
    if len(value) > 200:
        raise api_error(422, "bad_request", "That name is too long to be one this study uses.")
    return {"kind": kind, "id": value}


def _traced(
    ctx: AppContext, study_id: str, root: dict[str, str], top: int
) -> tuple[places_engine.TraceResult, places_engine.TraceContext]:
    built = _context(ctx, study_id)
    run = {
        "gene": places_engine.trace_gene,
        "sample": places_engine.trace_sample,
        "well": places_engine.trace_well,
    }[root["kind"]]
    try:
        return run(built, root["id"], top=top), built
    except places_engine.TraceError as err:
        raise api_error(404, "not_found", _sentence(str(err))) from err


def _sentence(text: str) -> str:
    text = str(text).strip().rstrip(".")
    return (text[:1].upper() + text[1:] + ".") if text else "Nothing is traced."


def _place(place: places_engine.PlaceToLook, opened: dict[str, str]) -> WherePlace:
    from qpilot.explain.trace_text import CONSEQUENCE_WORDS

    words = places_engine.CHECKS
    card_id = places_engine._card_id(place)
    options = [
        WhereOption(
            id=oid,
            label=OPTION_LABELS.get(oid, oid.replace("_", " ")),
            consequence=str(info.get("class") or "changes_nothing"),
            consequence_word=CONSEQUENCE_WORDS.get(str(info.get("class")), "changes nothing"),
            changed_calls=[str(g) for g in info.get("changed_calls") or ()],
        )
        for oid, info in place.options.items()
    ]
    return WherePlace(
        rank=place.rank,
        sample=place.sample,
        plate=place.plate,
        well=place.well,
        target=place.target,
        role=place.role,
        checks=[
            WhereCheck(
                code=c,
                **{k: words[c][k] for k in ("looks_like", "consistent_with", "what_to_check")},
            )  # fmt: skip
            for c in place.checks
            if c in words
        ],
        consequence=place.consequence,
        consequence_word=CONSEQUENCE_WORDS.get(place.consequence, place.consequence),
        options=options,
        card_id=card_id,
        card_status=opened.get(card_id),
        can_decide=place.consequence == "changes_call",
    )


ABSENT_WORDS = {
    "empty_reference_well": "its {target} reference well is empty",
    "empty_marker_well": "its {target} marker well is empty",
    "not_measured_for_every_gene": "it was not measured for {target}",
}


def _absent_why(entry: dict[str, Any]) -> str:
    """Why a sample is in no comparison, in words (the wells named, never a number typed)."""
    parts = []
    for reason in entry.get("reasons") or ():
        words = ABSENT_WORDS.get(str(reason.get("reason")), "{target}")
        text = words.format(target=reason.get("target") or "a gene")
        if reason.get("plate") and reason.get("well"):
            text += f" (plate {reason['plate']}, well {reason['well']})"
        parts.append(text)
    return "; ".join(parts) or "it has no value in the comparison"


def where_view(
    ctx: AppContext, study_id: str, sid: str | None, root: dict[str, str], top: int
) -> WhereView:
    """One trace as the page shows it."""
    from qpilot.core.validator import names_from_result
    from qpilot.explain.templates import TemplateError
    from qpilot.explain.trace_text import render_trace

    head = ctx.store.chain_head(study_id)
    result, built = _traced(ctx, study_id, root, top)
    facts = dict(result.facts)
    try:
        rendered = render_trace(result, allowed_names=names_from_result(ctx.store.get(study_id)))
        text = [rv.fact_text(line, facts) for line in rendered.tokens.split("\n") if line]
    except TemplateError:
        text = [rv.plain_text("The trace could not be shown in words.")]
    opened = {c.id: c.status for c in ctx.store.cards(study_id) if c.kind == "trace_set_aside"}
    absent = [
        WhereAbsent(sample=str(a.get("sample", "")), why=_absent_why(a))
        for a in result.absent[:MAX_ABSENT]
    ]
    return WhereView(
        study_id=study_id,
        session=sid,
        head=head,
        root=dict(result.root),
        answer=result.answer,
        planned=built.planned,
        text=text,
        places=[_place(p, opened) for p in result.places],
        n_more=int(result.summary.get("n_more") or 0),
        checked_nothing_found=list(result.checked_nothing_found),
        cannot_show=list(result.cannot_show),
        absent=absent,
        n_absent=len(result.absent),
        decide_note=DECIDE_NOTE,
    )


# ---- routes ---------------------------------------------------------------------------------


@router.get("/studies/{study_id}/where-to-look", response_model=WhereView)
def get_where(
    study_id: str,
    ctx: Ctx,
    gene: str | None = Query(default=None, max_length=200),
    sample: str | None = Query(default=None, max_length=200),
    well: str | None = Query(default=None, max_length=200, description="PLATE:WELL"),
    top: int = Query(default=TOP, ge=1, le=MAX_TOP),
) -> WhereView:
    """From a gene's result, a sample or a well to the places to look (read-only)."""
    sid = tr._visible(ctx, study_id)
    return where_view(ctx, study_id, sid, _root(gene, sample, well), top)


@router.post("/studies/{study_id}/where-to-look/open", response_model=PlaceOpened)
def post_open_place(study_id: str, body: OpenPlaceBody, ctx: Ctx) -> PlaceOpened:
    """A person's Decide…: the place at ``rank`` becomes a Decision Card on Results."""
    from qpilot.web.routers.results import changed
    from qpilot.web.views import analysed_study

    sid = tr._visible(ctx, study_id)
    if sid is not None and analysed_study(ctx.studio, sid) != study_id:
        raise api_error(409, "studio", NOT_CURRENT, session=sid)
    head = ctx.store.chain_head(study_id)
    if body.expected_head != head:
        raise api_error(409, "stale", STALE, head=head)
    root = _root(*(body.id if body.kind == k else None for k in ("gene", "sample", "well")))
    result, _ = _traced(ctx, study_id, root, max(body.rank, TOP))
    if body.rank > len(result.places):
        raise api_error(404, "not_found", "This trace has no place at that rank any more.")
    place = result.places[body.rank - 1]
    if place.consequence != "changes_call":
        raise api_error(
            422,
            "bad_request",
            "No option at this place changes a call, so there is nothing to decide here.",
        )
    card = result.card(body.rank)
    existing = {c.id: c for c in ctx.store.cards(study_id)}
    if card.id in existing:
        return PlaceOpened(
            card_id=card.id,
            opened=False,
            message="This place is already open as a Decision Card on Results.",
            head=head,
        )
    try:
        ctx.store.open_card(study_id, card)
    except CardError as err:
        raise api_error(409, "studio", _sentence(str(err))) from err
    except StudyNotFound as err:
        raise api_error(404, "not_found", "There is no analysed study with this id.") from err
    changed(ctx, study_id, sid)
    return PlaceOpened(
        card_id=card.id,
        opened=True,
        message=(
            "Opened as a Decision Card on Results: decide it there with a reason. A choice that "
            "can change a conclusion is a person's; the study's numbers stay as analysed."
        ),
        head=head,
    )
