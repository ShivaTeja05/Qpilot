"""Evidence Ledger and Run Review routes: what a study cannot tell you, and a person's sign-off.

* ``GET /studies/{id}/evidence`` → :class:`EvidenceView`: the eleven items of the Evidence
  Ledger (:mod:`qpilot.qpcr.evidence`), each present, absent, unknown or not applicable, with
  what that means for the conclusions. The ledger the study kept when it was analysed
  (``evidence.json``) when there is one, else one rebuilt read-only from the input file and
  kept in memory (never written: every GET writes nothing).
* ``GET /studies/{id}/review`` → :class:`RunReviewView`: the Run Review
  (:mod:`qpilot.report.run_review`): headline genes, the ledger and every recorded sign-off.
* ``GET /studies/{id}/review/repeat`` → :class:`RepeatView`: what to repeat and why (per sample
  x gene, every reason in words, whether it changes a call, ranked by consequence), the Run
  Gate's lines per plate, and the repeat plate (:mod:`qpilot.qpcr.repeat`), read at the
  analysis in use; ``…/review/repeat.csv`` downloads the plate in the planner's
  instrument-agnostic CSV. It reads the Run Gate and Trace, so a first read answers
  ``409 loading`` with their job (as Controls and Trace do). Read-only.
* ``POST /studies/{id}/review/sign-off`` → a person signs off (accept, repeat or discuss, a
  comment and a name): one ``review`` entry in the decision chain
  (:meth:`~qpilot.core.store.StudyStore.append_review`), always ``actor="human"`` (the server
  sets it). A decision made since the review was read answers ``409 stale``; a sign-off never
  makes a decision stale.

A study of a Studio session answers ``403 blind`` until its design and curves are confirmed
(the results routes' rule). Ported from the Gradio app's Evidence panel and Run Review
accordion; every sentence is validated token text, so every number is a fact.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import Response

from qpilot.core.decisions import DecisionError
from qpilot.core.store import MAX_REVIEWER, StaleReview, StudyNotFound
from qpilot.explain.evidence_text import (
    PURPOSE,
    STATUS_WORDS,
    comparison_lines,
    headline_lines,
    item_line,
    ledger_summary,
    render_facts,
    signoff_lines,
    study_line,
)
from qpilot.explain.templates import TemplateError
from qpilot.qpcr.evidence import LEDGER_VERSION, EvidenceError, EvidenceLedger, evidence_store
from qpilot.web import results_views as rv
from qpilot.web.context import AppContext, Ctx, api_error
from qpilot.web.contract import FactText
from qpilot.web.contract_evidence import (
    EvidenceItemView,
    EvidenceView,
    NotBuiltView,
    RepeatView,
    ReviewHeadlineView,
    ReviewOutcomeView,
    RunReviewView,
    SignOffBody,
    SignOffDone,
    SignOffView,
)

router = APIRouter(tags=["evidence"])

EVIDENCE_FILE = "evidence.json"
KEEP = 8
CANNOT = ("absent", "unknown")
RULE = (
    "Absent items never change a conclusion or a confidence grade; they say what this study "
    "cannot show."
)
NOT_SHOWN = "This line could not be shown."
OUTCOMES = (
    ReviewOutcomeView(
        id="accept",
        label="Accept",
        meaning="The run can be used as it is, with what the ledger says it cannot show.",
    ),
    ReviewOutcomeView(
        id="repeat",
        label="Repeat",
        meaning="Something here needs the run (or part of it) done again; say what.",
    ),
    ReviewOutcomeView(
        id="discuss",
        label="Discuss",
        meaning="Talk it through before the run is used; say what to talk about.",
    ),
)
OUTCOME_WORDS = {o.id: o.label.lower() for o in OUTCOMES}
STALE = (
    "Something was decided since the Run Review was shown (another tab or an agent), so it is "
    "shown again. Read it, then sign off again."
)
NOT_CURRENT = (
    "This analysis is no longer the session's current one (an accepted change re-ran it): sign "
    "off the current results."
)

#: Parts of the full Run Review not on this page yet that another section already shows.
ELSEWHERE: dict[str, tuple[str, str]] = {
    "next_run": (
        "planner",
        "Not on this page yet: Plan next sizes the next run from this study's own noise.",
    ),
}

REPEAT_NOTE = (
    "What the checks point at, per sample and gene, most consequential first: the Run Gate's "
    "warnings and failures, the wells a person left out, samples in no comparison, wells with "
    "no amplification where the gene amplified in nearly every other sample, and Trace's places "
    "to look. Re-running is your call: the plan changes nothing in the analysis."
)

_lock = threading.Lock()
_rebuilt: OrderedDict[tuple[str, str, int], tuple[EvidenceLedger | None, str]] = OrderedDict()
_plans: OrderedDict[tuple[Any, ...], Any] = OrderedDict()


# ---- the ledger -----------------------------------------------------------------------------


def _version(ctx: AppContext, study_id: str) -> tuple[str, str, int]:
    """Which store, which study, and when its results last changed (a re-analysis rebuilds)."""
    path = ctx.store.workspace(study_id) / "results.json"
    try:
        return str(ctx.store.root), study_id, path.stat().st_mtime_ns
    except OSError:
        return str(ctx.store.root), study_id, 0


def _kept(ctx: AppContext, study_id: str) -> EvidenceLedger | None:
    """The ledger the study kept when it was analysed, when it is this study's and current."""
    try:
        data = ctx.store.get_artifact(study_id, EVIDENCE_FILE)
        ledger = EvidenceLedger.model_validate(data) if isinstance(data, dict) else None
    except (ValueError, OSError):  # an unreadable kept ledger is rebuilt, never shown
        return None
    if ledger is None or ledger.version != LEDGER_VERSION:
        return None
    if ledger.study_id not in (None, ctx.store.get(study_id).study_id):
        return None
    return ledger


def import_rawness(ctx: AppContext, study_id: str) -> dict[str, Any] | None:
    """The raw-ness verdict Open's import check kept for the study's session, if any."""
    from qpilot.web import intake

    sid = rv.session_of_study(ctx.store, study_id)
    if sid is None:
        return None
    try:
        found = intake.load(ctx.store, sid)
    except Exception:  # an unreadable import record only means no verdict
        return None
    rawness = found[0].rawness if found is not None else None
    return dict(rawness) if rawness else None


def ledger_of(ctx: AppContext, study_id: str) -> tuple[EvidenceLedger | None, str, str]:
    """``(ledger, note, source)``: the kept ledger, else one rebuilt read-only (kept in memory).

    A study opened from an instrument export gets the import's raw-ness verdict in its ledger
    (rebuilt when the kept one was built without it).
    """
    rawness = import_rawness(ctx, study_id)
    kept = _kept(ctx, study_id)
    judged = kept is not None and kept.item("rawness").consequence.code.startswith("rawness_import")
    if kept is not None and (rawness is None or judged):
        return kept, "", "kept"
    key = _version(ctx, study_id)
    with _lock:
        if key in _rebuilt:
            _rebuilt.move_to_end(key)
            ledger, note = _rebuilt[key]
            return ledger, note, "rebuilt" if ledger is not None else "none"
    try:
        ledger, note = evidence_store(ctx.store, study_id, rawness=rawness), ""
    except StudyNotFound:
        raise
    except EvidenceError as err:
        ledger, note = None, str(err)
    except Exception as err:  # the panel says so; the page stays up
        ledger, note = None, f"it could not be built ({type(err).__name__})"
    with _lock:
        _rebuilt[key] = (ledger, note)
        while len(_rebuilt) > KEEP:
            _rebuilt.popitem(last=False)
    return ledger, note, "rebuilt" if ledger is not None else "none"


def clear() -> None:
    """Forget every rebuilt ledger and repeat plan (tests; a fresh demo)."""
    with _lock:
        _rebuilt.clear()
        _plans.clear()


def checked(key: str, tokens: str, facts: dict[str, Any], fallback: str) -> FactText:
    """Token text validated (numbers only through facts) as :class:`FactText`, else ``fallback``."""
    try:
        rendered = render_facts(key, tokens, facts)
    except (TemplateError, KeyError, ValueError):
        return rv.plain_text(fallback)
    return rv.fact_text(rendered.tokens, facts)


def _sentence(note: str) -> str:
    note = note.strip().rstrip(".")
    return note[:1].upper() + note[1:] + "." if note else ""


def evidence_view(
    study_id: str, ledger: EvidenceLedger | None, note: str, source: str
) -> EvidenceView:
    """The ledger as the page shows it (or why there is none)."""
    if ledger is None:
        why = _sentence(note) or "It could not be built for this study."
        return EvidenceView(
            study_id=study_id,
            available=False,
            source="none",
            note=f"The Evidence Ledger is not available for this study. {why}",
            rule=RULE,
        )
    facts = dict(ledger.facts)
    summary_tokens = ledger_summary(facts)
    summary = (
        checked("evidence_v1", summary_tokens, facts, "Evidence Ledger.")
        if summary_tokens
        else None
    )
    items = []
    for item in ledger.items:
        status = item.status if item.status in STATUS_WORDS else "unknown"
        try:
            tokens = item_line(facts, item.id)
        except (TemplateError, KeyError):
            tokens = None
        fallback = f"{item.title}: {STATUS_WORDS[status]}. {NOT_SHOWN}"
        line = (
            checked("evidence_v1", tokens, facts, fallback) if tokens else rv.plain_text(fallback)
        )
        items.append(
            EvidenceItemView(
                id=item.id,
                title=item.title,
                status=status,
                status_word=STATUS_WORDS[status],
                value=item.value,
                line=line,
                cannot_tell=status in CANNOT,
                miqe=list(item.miqe),
            )
        )
    return EvidenceView(
        study_id=study_id,
        available=True,
        source="kept" if source == "kept" else "rebuilt",
        summary=summary,
        counts=ledger.counts(),
        items=items,
        rule=RULE,
    )


# ---- the Run Review -------------------------------------------------------------------------


def _study(ctx: AppContext, study_id: str) -> str | None:
    """404 unknown, 403 ``blind`` while its session is; the study's session (if any)."""
    from qpilot.web.routers.results import study

    return study(ctx, study_id)


def _current(ctx: AppContext, study_id: str, sid: str | None) -> bool:
    from qpilot.web.views import analysed_study

    return sid is None or analysed_study(ctx.studio, sid) == study_id


def review_view(ctx: AppContext, study_id: str, sid: str | None) -> RunReviewView:
    """The Run Review of the study, with every sign-off the decision chain holds."""
    from qpilot.core.decisions import MAX_REASON
    from qpilot.report.run_review import HEADLINE_GENES, RunReviewError, build_review

    store = ctx.store
    head = store.chain_head(study_id)  # read first: a write in between makes a sign-off stale
    result = store.get(study_id)
    design = store.design(study_id)
    headline = tuple(design.headline) if design is not None else HEADLINE_GENES
    ledger, note, source = ledger_of(ctx, study_id)
    try:
        review = build_review(
            result,
            headline=headline,
            ledger=ledger,
            ledger_note=note,
            reviews=store.reviews(study_id),
        )
    except RunReviewError as err:
        raise api_error(
            500, "review", f"The Run Review could not be built: {_sentence(str(err))}"
        ) from err
    facts = dict(review.facts)
    lines = headline_lines(facts)
    shown = [
        ReviewHeadlineView(
            gene=gene.gene,
            conclusion=gene.conclusion,
            line=checked("runreview_v1", tokens, facts, gene.gene),
        )
        for gene, tokens in zip(review.headline, lines, strict=False)
    ]
    signs = signoff_lines(facts)
    sign_offs = [
        SignOffView(
            seq=s.seq,
            outcome=s.outcome,
            outcome_word=OUTCOME_WORDS[s.outcome],
            reviewer=s.reviewer,
            comment=s.comment,
            at=s.at,
            hash=s.hash,
            line=checked("runreview_v1", tokens, facts, "A sign-off is recorded."),
        )
        for s, tokens in zip(review.reviews, signs, strict=False)
    ]
    current = _current(ctx, study_id, sid)
    return RunReviewView(
        study_id=study_id,
        session=sid,
        head=head,
        title=checked("runreview_v1", study_line(facts), facts, "Run Review."),
        purpose=PURPOSE,
        headline=shown,
        comparisons=[
            checked("runreview_v1", tokens, facts, "A comparison of the study.")
            for tokens in comparison_lines(facts)
        ],
        evidence=evidence_view(study_id, ledger, note, source),
        sign_offs=sign_offs,
        outcomes=list(OUTCOMES),
        not_built=[
            NotBuiltView(
                id=n.id,
                title=n.title,
                reason=ELSEWHERE.get(n.id, ("", _sentence(n.reason)))[1],
                section=ELSEWHERE.get(n.id, (None, ""))[0] or None,
            )
            for n in review.not_available
        ],
        can_sign_off=current,
        why_not="" if current else NOT_CURRENT,
        max_comment=MAX_REASON,
        max_reviewer=MAX_REVIEWER,
    )


# ---- routes ---------------------------------------------------------------------------------


@router.get("/studies/{study_id}/evidence", response_model=EvidenceView)
def get_evidence(study_id: str, ctx: Ctx) -> EvidenceView:
    """The Evidence Ledger: what this study can and cannot tell you (read-only)."""
    _study(ctx, study_id)
    ledger, note, source = ledger_of(ctx, study_id)
    return evidence_view(study_id, ledger, note, source)


@router.get("/studies/{study_id}/review", response_model=RunReviewView)
def get_review(study_id: str, ctx: Ctx) -> RunReviewView:
    """The Run Review: headline genes, the Evidence Ledger and the recorded sign-offs."""
    sid = _study(ctx, study_id)
    return review_view(ctx, study_id, sid)


@router.post("/studies/{study_id}/review/sign-off", response_model=SignOffDone)
def post_sign_off(study_id: str, body: SignOffBody, ctx: Ctx) -> SignOffDone:
    """A person signs off the run: one ``review`` entry in the decision chain, as ``human``."""
    from qpilot.web.routers.results import changed, rv_sentence

    sid = _study(ctx, study_id)
    if not _current(ctx, study_id, sid):
        raise api_error(409, "studio", NOT_CURRENT, session=sid)
    try:
        entry = ctx.store.append_review(
            study_id,
            body.outcome,
            body.comment,
            body.reviewer,
            actor="human",  # the page is a person; it cannot choose another actor
            expected_head=body.expected_head,
        )
    except StaleReview as err:
        raise api_error(409, "stale", STALE, head=ctx.store.chain_head(study_id)) from err
    except DecisionError as err:
        raise api_error(422, "bad_request", rv_sentence(str(err))) from err
    changed(ctx, study_id, sid)
    review = review_view(ctx, study_id, sid)
    sign_off = next(s for s in review.sign_offs if s.seq == entry.seq)
    word = OUTCOME_WORDS[sign_off.outcome]
    return SignOffDone(
        message=(
            f"Signed off ({word}). The decision log keeps it with your name and comment; it "
            "changes no result and no Decision Card."
        ),
        head=entry.hash,
        sign_off=sign_off,
        review=review,
    )


# ---- what to repeat and why ------------------------------------------------------------------


def repeat_plan(ctx: AppContext, study_id: str, sid: str | None, include: str) -> Any:
    """The study's repeat plan at the analysis in use (kept per state; 409 while it loads)."""
    from qpilot.qpcr.gate_rules import resolve_pack
    from qpilot.qpcr.repeat import RepeatError, build_plan, left_out_from_inbox
    from qpilot.web.routers import gate as gate_router
    from qpilot.web.routers import where as where_router

    inbox = ctx.studio.head(sid) if sid else None
    key = (
        *_version(ctx, study_id),
        ctx.store.chain_head(study_id),
        inbox,
        gate_router.links_version(ctx.store, study_id),
        include,
    )
    with _lock:
        if key in _plans:
            _plans.move_to_end(key)
            return _plans[key]
    built = where_router._context(ctx, study_id)  # 409 loading: Trace reads the wells first
    report = gate_router._report(ctx, study_id, gate_router._choice(ctx, study_id))
    left = left_out_from_inbox(ctx.store.proposals(sid).accepted(), built) if sid else {}
    try:
        plan = build_plan(
            study_id,
            built,
            gate=report,
            pack=resolve_pack(),
            left_out=left,
            include="all" if include == "all" else "consequential",
        )
    except RepeatError as err:
        raise api_error(
            409, "repeat", f"The repeat plate cannot be laid out: {_sentence(str(err))}"
        ) from err
    with _lock:
        _plans[key] = plan
        while len(_plans) > KEEP:
            _plans.popitem(last=False)
    return plan


def _csv_name(study_id: str) -> str:
    return f"qpilot-repeat-{study_id}.csv"


@router.get("/studies/{study_id}/review/repeat", response_model=RepeatView)
def get_repeat(
    study_id: str,
    ctx: Ctx,
    include: str = Query(default="consequential", pattern="^(consequential|all)$"),
) -> RepeatView:
    """What to repeat and why, ranked by consequence, and the repeat plate (read-only)."""
    sid = _study(ctx, study_id)
    plan = repeat_plan(ctx, study_id, sid, include)
    return RepeatView(
        study_id=study_id,
        session=sid,
        include="all" if include == "all" else "consequential",
        plan=plan,
        csv_url=f"/api/studies/{study_id}/review/repeat.csv?include={include}",
        csv_name=_csv_name(study_id),
        note=REPEAT_NOTE,
    )


@router.get(
    "/studies/{study_id}/review/repeat.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "The repeat plate as CSV."}},
)
def get_repeat_csv(
    study_id: str,
    ctx: Ctx,
    include: str = Query(default="consequential", pattern="^(consequential|all)$"),
) -> Response:
    """The repeat plate as the planner's CSV (plate, well, sample, group, target, type)."""
    sid = _study(ctx, study_id)
    plan = repeat_plan(ctx, study_id, sid, include)
    if not plan.wells:
        raise api_error(404, "not_found", "Nothing points at a reaction to re-run.")
    return Response(
        content=plan.csv(),
        media_type="text/csv; charset=utf-8",
        headers={"content-disposition": f'attachment; filename="{_csv_name(study_id)}"'},
    )
