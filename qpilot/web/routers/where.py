"""Where to look: from a gene's result, a sample or a well to the places a person should look.

* ``GET /studies/{id}/where-to-look?gene=|sample=|well=PLATE:WELL`` → :class:`WhereView`: the
  places to look, ranked by what each option there does to the calls (it changes a call > it
  moves a fold change by more than its confidence interval > it changes nothing), each with the
  fingerprint checks it fails (S1-S7) and what to check. Read-only.
* ``POST /studies/{id}/where-to-look/decide`` ``{kind, id, rank, option, reason, expected_head,
  expected_inbox}`` → a person's **Decide…** in a Studio session (the session's current
  analysis): the option becomes curve exclusions, Run Gate's path
  (:meth:`~qpilot.studio_service.Studio.decide_trace`): a set-aside leaves its wells out (one
  ``curve.exclude_well`` per well, made by Trace and accepted by the person with the reason, one
  write to the session's hash-chained inbox), "keep" puts back what a person left out at the
  place (or records the keep); the study is analysed again (the ``analyse`` job) and the
  person's Decision Card choices are carried to it. Reading a well from the sample's other
  reference wells is a what-if only (the analysis keeps a well or leaves it out).
* ``POST /studies/{id}/where-to-look/put-back`` ``{card_id, reason, expected_inbox}`` → a person
  puts back the wells set aside at a place (they are listed in the view's ``set_aside``).
* ``POST /studies/{id}/where-to-look/open`` ``{kind, id, rank, expected_head}`` → for a study
  analysed outside Studio (no inbox to leave a well out in): the place becomes a
  ``trace_set_aside`` Decision Card (:meth:`~qpilot.core.store.StudyStore.open_card`), decided
  on Results like any other card: a choice that can change a conclusion is a person's, at every
  autonomy level. Opening writes no chain entry, and deciding the card changes no number of
  the study; the view says to open the file in Studio to leave the wells out.

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
    TraceDecideBody,
    TraceDecided,
    TracePutBackBody,
    TraceSetAsideView,
    WhereAbsent,
    WhereCheck,
    WhereOption,
    WherePlace,
    WhereRequest,
    WhereSetAside,
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
APPLY_NOTE = (
    "Decide… leaves the wells out of the analysis (or puts them back), with your reason, in "
    "this session's record, and analyses the study again; your choices on the Decision Cards "
    "are carried to the new analysis. A choice that can change a conclusion is a person's."
)
OUTSIDE_STUDIO = (
    "This study was analysed outside Studio, so its wells cannot be left out here: Decide… "
    "opens the place as a Decision Card on Results, which records your decision with its "
    "reason, and the numbers stay as analysed. To leave the wells out of the analysis, open the "
    "study's file in Studio (Open), confirm the design and the curves, and decide in Trace there."
)
WHAT_IF = (
    "Reading a well from the sample's other reference wells is a what-if only: the analysis "
    "keeps a well or leaves it out. Choose to set the sample aside, or to keep it."
)
DONE_WORDS = {
    "left_out": "Left out {n} {wells}: the study is being analysed again without {them}, and "
    "your choices on the Decision Cards are carried to the new analysis.",
    "put_back": "Put {n} {wells} back: the study is being analysed again with {them}.",
    "kept": "Kept the {wells}: recorded with your reason; the analysis is as it was.",
}

_lock = threading.Lock()
_build = threading.Lock()
_contexts: OrderedDict[tuple[Any, ...], places_engine.TraceContext] = OrderedDict()


# ---- the context at the analysis in use -----------------------------------------------------


def _context(
    ctx: AppContext, study_id: str, comparison: str | None = None
) -> places_engine.TraceContext:
    """The place-to-look context for the analysis in use (the kept model loaded first).

    ``comparison``: a study with several comparisons, the one traced (None: the first).
    """
    from qpilot.trace.context import cell_of

    # the Trace section's context: 409 loading the first time
    page = tr._ready(ctx, study_id, comparison)
    choice, _ = tr._choice(ctx, study_id)
    key = (study_id, tr._version(ctx, study_id), tuple(sorted((choice or {}).items())), comparison)
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
        robust = result.robustness
        if comparison and result.comparisons is not None:
            robust = next(
                (o.robustness for o in result.comparisons.comparisons if o.id == comparison),
                robust,
            )
        try:
            cell = cell_of(model, choice)
            built = places_engine.build_context(
                model.inputs.primary_table,
                model,
                robustness=robust,
                cell=cell,
                comparison=comparison,
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
    ctx: AppContext, study_id: str, root: dict[str, str], top: int, comparison: str | None = None
) -> tuple[places_engine.TraceResult, places_engine.TraceContext]:
    built = _context(ctx, study_id, comparison) if comparison else _context(ctx, study_id)
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


def _where_words(sample: str, well_key: str | None) -> str:
    """Words for a place: sample, plate and well (a tube place: the sample alone)."""
    if not well_key:
        return f"sample {sample}"
    plate, _, well = well_key.rpartition("/")
    return f"sample {sample}, plate {plate}, well {well}"


def _well_key(place: places_engine.PlaceToLook) -> str | None:
    return f"{place.plate}/{place.well}" if place.plate and place.well else None


def _matters(place: places_engine.PlaceToLook, option: str) -> bool:
    """The option (for keep: any option of the place) changes a call at the analysis in use."""
    infos = place.options.values() if option == "keep" else [place.options.get(option) or {}]
    return any(str(i.get("class")) == "changes_call" or bool(i.get("changed_calls")) for i in infos)


def _trace_choice(
    study_id: str, built: places_engine.TraceContext, place: places_engine.PlaceToLook, option: str
) -> Any:
    """The :class:`~qpilot.studio_service.TraceChoice` of one option at one place (server-built)."""
    from qpilot.studio_service import TraceChoice

    wells = places_engine.option_wells(built, place, option) or ()
    key = _well_key(place)
    return TraceChoice(
        study_id=study_id,
        card_id=places_engine._card_id(place),
        option=option,
        label=OPTION_LABELS.get(option, option.replace("_", " ")),
        where=_where_words(place.sample, key),
        sample=place.sample,
        well=key,
        checks=tuple(place.checks),
        wells=tuple(wells),
        universe=places_engine.place_universe(built, place),
        place_wells=places_engine.place_wells(built, place),
        matters=_matters(place, option),
    )


def _can_apply(ctx: AppContext, study_id: str, sid: str | None) -> bool:
    """Decide… changes the analysis: a Studio session whose current analysis this is."""
    from qpilot.web.views import analysed_study

    return sid is not None and analysed_study(ctx.studio, sid) == study_id


def _set_aside(ctx: AppContext, sid: str, built: places_engine.TraceContext) -> list[WhereSetAside]:
    """What a person set aside from Trace in this session that is out of the analysis now."""
    out = []
    wells = built.wells
    for card_id, entry in sorted(ctx.studio.trace_left_out(sid).items()):
        plate = well = target = None
        if entry.well and entry.well in wells.index:
            plate, _, well = entry.well.rpartition("/")
            target = str(wells.loc[entry.well, "target"])
        out.append(
            WhereSetAside(
                card_id=card_id,
                sample=entry.sample,
                plate=plate,
                well=well,
                target=target,
                option=entry.option,
                option_label=OPTION_LABELS.get(entry.option, entry.option.replace("_", " ")),
                wells=list(entry.wells),
                reason=entry.reason,
                decided_at=entry.decided_at,
                matters=entry.matters,
            )
        )
    return out


def _requests(waiting: list[Any]) -> list[WhereRequest]:
    """Agents' waiting requests at one place, one per option asked for (oldest first)."""
    from qpilot.studio_service import leaves_out

    by_option: dict[str, list[Any]] = {}
    for p in waiting:
        option = str(((p.consequence or {}).get("trace") or {}).get("option") or "")
        by_option.setdefault(option, []).append(p)
    return [
        WhereRequest(
            option=option,
            option_label=OPTION_LABELS.get(option, option.replace("_", " ")),
            wells=sorted(p.subject for p in ps if leaves_out(p)),
            put_back=sorted(p.subject for p in ps if not leaves_out(p)),
            reason=(ps[0].reasons or [""])[0],
            agent=ps[0].made_by.agent,
            at=ps[0].created_at,
        )
        for option, ps in by_option.items()
    ]


def _place(
    place: places_engine.PlaceToLook,
    opened: dict[str, str],
    built: places_engine.TraceContext | None = None,
    requests: dict[str, list[Any]] | None = None,
) -> WherePlace:
    from qpilot.explain.trace_text import CONSEQUENCE_WORDS

    words = places_engine.CHECKS
    card_id = places_engine._card_id(place)
    options = []
    for oid, info in place.options.items():
        wells = places_engine.option_wells(built, place, oid) if built is not None else None
        options.append(
            WhereOption(
                id=oid,
                label=OPTION_LABELS.get(oid, oid.replace("_", " ")),
                consequence=str(info.get("class") or "changes_nothing"),
                consequence_word=CONSEQUENCE_WORDS.get(str(info.get("class")), "changes nothing"),
                changed_calls=[str(g) for g in info.get("changed_calls") or ()],
                applies=wells is not None,
                n_wells=len(wells or ()),
            )
        )
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
        requests=_requests((requests or {}).get(card_id, [])),
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
        if reason.get("left_out"):
            text = f"a person left its {reason.get('target') or 'a gene'} wells out of the analysis"
        if reason.get("plate") and reason.get("well"):
            text += f" (plate {reason['plate']}, well {reason['well']})"
        parts.append(text)
    return "; ".join(parts) or "it has no value in the comparison"


COMPARISON_NOTE = (
    "Traced in {label}: each place's consequences are for this comparison. Setting a sample "
    "aside leaves it out of every comparison of the study."
)


def where_view(
    ctx: AppContext,
    study_id: str,
    sid: str | None,
    root: dict[str, str],
    top: int,
    comparison: str | None = None,
) -> WhereView:
    """One trace as the page shows it (``comparison``: the one traced, of several)."""
    from qpilot.core.validator import names_from_result
    from qpilot.explain.templates import TemplateError
    from qpilot.explain.trace_text import render_trace

    head = ctx.store.chain_head(study_id)
    result, built = _traced(ctx, study_id, root, top, comparison)
    traced = built.space.comparisons[0] if built.space.comparisons else None
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
    apply = _can_apply(ctx, study_id, sid)
    note = APPLY_NOTE if apply else OUTSIDE_STUDIO if sid is None else NOT_CURRENT
    asked = ctx.studio.trace_requests(sid) if apply and sid else {}
    return WhereView(
        study_id=study_id,
        session=sid,
        head=head,
        root=dict(result.root),
        answer=result.answer,
        planned=built.planned,
        text=text,
        places=[_place(p, opened, built, asked) for p in result.places],
        comparison=traced.id if traced is not None else None,
        comparison_note=COMPARISON_NOTE.format(label=f"{traced.labels[0]} vs {traced.labels[1]}")
        if traced is not None
        else None,
        n_more=int(result.summary.get("n_more") or 0),
        checked_nothing_found=list(result.checked_nothing_found),
        cannot_show=list(result.cannot_show),
        absent=absent,
        n_absent=len(result.absent),
        decide_note=APPLY_NOTE if apply else DECIDE_NOTE,
        can_apply=apply,
        apply_note=note,
        inbox_head=ctx.studio.head(sid) if sid else None,
        set_aside=_set_aside(ctx, sid, built) if apply and sid else [],
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
    comparison: tr.ComparisonQuery = None,
) -> WhereView:
    """From a gene's result, a sample or a well to the places to look (read-only)."""
    sid = tr._visible(ctx, study_id)
    cid = tr.comparison_of(ctx, study_id, comparison)
    return where_view(ctx, study_id, sid, _root(gene, sample, well), top, cid)


@router.get("/studies/{study_id}/where-to-look/set-aside", response_model=TraceSetAsideView)
def get_set_aside(study_id: str, ctx: Ctx) -> TraceSetAsideView:
    """What a person set aside from Trace in this session that is out of the analysis now."""
    sid = tr._visible(ctx, study_id)
    apply = _can_apply(ctx, study_id, sid)
    note = APPLY_NOTE if apply else OUTSIDE_STUDIO if sid is None else NOT_CURRENT
    found = _set_aside(ctx, sid, _context(ctx, study_id)) if apply and sid else []
    return TraceSetAsideView(
        study_id=study_id,
        session=sid,
        can_apply=apply,
        apply_note=note,
        inbox_head=ctx.studio.head(sid) if sid else None,
        set_aside=found,
    )


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
    cid = tr.comparison_of(ctx, study_id, body.comparison)
    result, _ = _traced(ctx, study_id, root, max(body.rank, TOP), cid)
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


def _decided(ctx: AppContext, study_id: str, sid: str, choice: Any, reason: str, inbox: Any):
    """Run a person's Trace choice through Studio; the analysis of the changed design."""
    from qpilot.web.routers.studio import HUMAN, call, ensure_analysis
    from qpilot.web.routers.studio import changed as inbox_changed

    outcome = call(ctx.studio.decide_trace, sid, choice, HUMAN, reason, expected_head=inbox)
    if outcome.status == "stale":
        raise api_error(409, "stale", STALE, head=outcome.head)
    if outcome.status not in ("left_out", "put_back", "kept"):
        raise api_error(403, "refused", f"Not done: {outcome.reason or 'refused'}.")
    inbox_changed(ctx, sid)
    job = ensure_analysis(ctx, sid)
    ctx.bus.publish({"type": "study.changed", "key": sid, "source": "page"})
    ctx.bus.publish({"type": "study.changed", "key": study_id, "source": "page"})
    n = len(outcome.left_out) or len(outcome.put_back) or len(choice.place_wells)
    message = DONE_WORDS[outcome.status].format(
        n=n, wells="well" if n == 1 else "wells", them="it" if n == 1 else "them"
    )
    if outcome.not_put_back:
        message += (
            f" {len(outcome.not_put_back)} more were left out another way (a Prism round trip) "
            "and stay left out."
        )
    return TraceDecided(
        status=outcome.status,
        message=message,
        study_id=study_id,
        card_id=choice.card_id,
        left_out=outcome.left_out,
        put_back=outcome.put_back,
        inbox_head=outcome.head,
        job=job,
    )


def _session_for_decision(ctx: AppContext, study_id: str, reason: str) -> str:
    """The Studio session whose current analysis this is (409 otherwise); a reason given."""
    sid = tr._visible(ctx, study_id)
    if sid is None:
        raise api_error(409, "studio", OUTSIDE_STUDIO)
    if not _can_apply(ctx, study_id, sid):
        raise api_error(409, "studio", NOT_CURRENT, session=sid)
    if not reason.strip():
        raise api_error(422, "bad_request", "Say why (the reason is kept in the record).")
    return sid


@router.post("/studies/{study_id}/where-to-look/decide", response_model=TraceDecided)
def post_decide_place(study_id: str, body: TraceDecideBody, ctx: Ctx) -> TraceDecided:
    """A person's Decide… in a Studio session: the option leaves wells out or puts them back.

    The place is traced again at the analysis in use and must still be the one shown (``stale``
    when the chain head moved); only an option that changes the analysis (keep or a set-aside)
    is applied. The study is analysed again (the ``analyse`` job) when the design changed.
    """
    sid = _session_for_decision(ctx, study_id, body.reason)
    head = ctx.store.chain_head(study_id)
    if body.expected_head != head:
        raise api_error(409, "stale", STALE, head=head)
    root = _root(*(body.id if body.kind == k else None for k in ("gene", "sample", "well")))
    cid = tr.comparison_of(ctx, study_id, body.comparison)
    result, built = _traced(ctx, study_id, root, max(body.rank, TOP), cid)
    if body.rank > len(result.places):
        raise api_error(404, "not_found", "This trace has no place at that rank any more.")
    place = result.places[body.rank - 1]
    if place.consequence != "changes_call":
        raise api_error(
            422,
            "bad_request",
            "No option at this place changes a call, so there is nothing to decide here.",
        )
    if body.option not in place.options:
        raise api_error(422, "bad_request", "This place has no such option.")
    if places_engine.option_wells(built, place, body.option) is None:
        raise api_error(422, "bad_request", WHAT_IF)
    choice = _trace_choice(study_id, built, place, body.option)
    return _decided(ctx, study_id, sid, choice, body.reason, body.expected_inbox)


@router.post("/studies/{study_id}/where-to-look/put-back", response_model=TraceDecided)
def post_put_back(study_id: str, body: TracePutBackBody, ctx: Ctx) -> TraceDecided:
    """A person puts back the wells they set aside at a place (a Studio session only)."""
    from qpilot.studio_service import GATE_KEEP, TraceChoice

    sid = _session_for_decision(ctx, study_id, body.reason)
    entry = ctx.studio.trace_left_out(sid).get(body.card_id)
    if entry is None:
        raise api_error(
            404, "not_found", "Nothing set aside at this place is out of the analysis now."
        )
    choice = TraceChoice(
        study_id=study_id,
        card_id=body.card_id,
        option=GATE_KEEP,
        label="Put the wells back",
        where=_where_words(entry.sample, entry.well),
        sample=entry.sample,
        well=entry.well,
        checks=(),
        wells=(),
        universe=tuple(entry.wells),
        place_wells=tuple(entry.wells),
        matters=entry.matters,
    )
    return _decided(ctx, study_id, sid, choice, body.reason, body.expected_inbox)
