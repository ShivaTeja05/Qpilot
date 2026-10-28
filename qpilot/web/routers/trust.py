"""Import Trust route: whether an instrument export's curves can be analysed as they are.

``GET /studies/{id}/import-trust`` answers the ``capture.import_trust`` Decision Card of a study
analysed from a Studio session opened from an instrument export whose curves were most likely
baseline-subtracted before export, or whose processing qPilot could not tell
(:mod:`qpilot.io.trust`): its options with what each does to the analysis and the confidence cap
it puts on every gene, the vendor's re-export recipe, the option in use, a person's decision and
agents' requests. Every other study answers ``applies: false``, with why.

The card has no grid dimension, so it is not decided in the study's decision chain: ``POST
/studies/{id}/import-trust/decide`` records a person's choice as a ``curve.import_trust``
proposal in the session's hash-chained inbox, accepted by the person with the reason in one
write (:meth:`qpilot.studio_service.Studio.decide_import_trust`). ``cq_only`` (and leaving it)
changes the analysis, so the study is analysed again (the ``analyse`` job); the other options
keep it. Only a person decides; an agent's ``qpcr_decide`` over MCP files a request that waits
here (``pending_human``).

Like every result, a study of a Studio session answers ``403 blind`` until its design and
curves are confirmed, a choice included. GETs never write.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from qpilot.io import trust
from qpilot.web.context import AppContext, Ctx, api_error
from qpilot.web.contract_trust import (
    ImportTrustView,
    TrustDecide,
    TrustDecided,
    TrustDecisionView,
    TrustOptionView,
    TrustPlateView,
    TrustRequestView,
)

router = APIRouter(tags=["trust"])

OUTSIDE_STUDIO = (
    "This study was analysed outside Studio, so how far its curves can be trusted is not "
    "decided here. Open its export in Studio (Open, then drop the files): qPilot reads how the "
    "curves were processed, and a person decides what that means for the analysis."
)
NO_CARD = (
    "The curves of this study call for no Import Trust decision: they are raw, normalised to a "
    "passive reference, or the study was opened from an RDML file."
)
NO_CURVES = (
    "This file has Cq values only, so there are no curves whose processing before export could "
    "be checked, and no Import Trust decision: each assay's efficiency is its dilution series' "
    "or an assumed 2.0, and the confidence cap says so."
)
NOT_CURRENT = (
    "This is not the analysis in use for its Studio session any more, so its Import Trust card "
    "is shown as it was; decide it on the analysis in use."
)
DECIDE_NOTE = (
    "Deciding writes one entry to this session's record, with your reason. Choosing to use the "
    "instrument's Cq values only (or going back from it) analyses the study again, and the new "
    "analysis starts with its Decision Cards at the recommended options."
)
STALE = (
    "The analysis changed since you loaded this (another tab, a decision or an agent). Here is "
    "the Import Trust card at the analysis in use now."
)
NO_CQ = (
    "The export has no Cq values from the instrument, so it cannot be analysed without its curves."
)
DONE = {
    "reexport_raw": (
        "Recorded: you will re-export the raw curves. This analysis stays the curves as "
        "imported, with confidence capped at Moderate; open the raw export as a new study."
    ),
    "analyse_as_is": (
        "Recorded: the curves are analysed as they were exported, with confidence capped at "
        "Moderate."
    ),
    "cq_only": (
        "Recorded: the study is being analysed again from the instrument's Cq values, with "
        "confidence capped at Low."
    ),
}
#: The same choices when they leave Cq only: the study is analysed again from the curves.
DONE_BACK = {
    "reexport_raw": (
        "Recorded: you will re-export the raw curves (open the raw export as a new study). The "
        "study is being analysed again from the curves as imported, with confidence capped at "
        "Moderate."
    ),
    "analyse_as_is": (
        "Recorded: the study is being analysed again from the curves as they were exported, "
        "with confidence capped at Moderate."
    ),
}


def _visible(ctx: AppContext, study_id: str) -> str | None:
    """The results routes' checks (id, study, blind); returns the study's session, if any."""
    from qpilot.web.routers.results import study

    return study(ctx, study_id)


def _request(p: Any) -> TrustRequestView | None:
    from qpilot.studio_service import trust_choice

    option = trust_choice(p)
    if option is None:
        return None
    return TrustRequestView(
        proposal_id=p.id,
        option=option,  # type: ignore[arg-type]
        option_label=trust.LABELS[option],
        reason=p.reasons[0] if p.reasons else "",
        agent=p.made_by.agent,
        at=p.created_at or "",
    )


def _cq_only(ctx: AppContext, study_id: str) -> bool:
    """True for a study of a file with Cq values only (its facts say so)."""
    try:
        return "f_cq_only" in ctx.store.get(study_id).facts
    except Exception:  # an unreadable study: say what the curves say
        return False


def build_view(ctx: AppContext, study_id: str, sid: str | None) -> ImportTrustView:
    """The study's Import Trust card as the page shows it (``applies: false`` without one)."""
    from qpilot.studio_service import trust_choice, trust_decision, trust_requests
    from qpilot.web import intake
    from qpilot.web.views import analysed_study

    if sid is None:
        return ImportTrustView(study_id=study_id, applies=False, why=OUTSIDE_STUDIO)
    found = intake.load(ctx.store, sid)
    verdict = ctx.studio.import_verdict(sid)
    design = ctx.store.design(study_id)
    chosen = design.import_trust if design is not None else None
    if found is None or verdict is None or chosen is None:
        cq_values = _cq_only(ctx, study_id)
        return ImportTrustView(
            study_id=study_id, applies=False, why=NO_CURVES if cq_values else NO_CARD
        )
    meta, _ = found
    inbox = ctx.studio.store.proposals(sid).view()
    current = analysed_study(ctx.studio, sid) == study_id
    decided = trust_decision(inbox.accepted) if current else None
    option = trust_choice(decided) if decided is not None else None
    if option is None:
        option = trust.IN_USE if chosen.analysis == "as_is" else "cq_only"
    n_cq = sum(p.n_with_vendor_cq for p in meta.plates)
    caps = trust.caps(chosen.verdict)
    options = []
    for o in trust.OPTIONS:
        available = o != "cq_only" or n_cq > 0
        options.append(
            TrustOptionView(
                id=o,  # type: ignore[arg-type]
                label=trust.LABELS[o],
                effect=trust.EFFECTS[o],
                cap=caps[o].level,
                cap_reason=caps[o].note,
                recommended=o == trust.RECOMMENDED,
                in_use=o == option,
                new_analysis=trust.analysis_for(o) != chosen.analysis,
                available=available,
                why_not="" if available else NO_CQ,
            )
        )
    requests = [r for r in map(_request, trust_requests(inbox)) if r is not None] if current else []
    decision = (
        TrustDecisionView(
            option=option,  # type: ignore[arg-type]
            label=trust.LABELS[option],
            reason=decided.reason or "",
            decided_at=decided.decided_at or "",
        )
        if decided is not None
        else None
    )
    cap = trust.cap_for(chosen)
    assert cap is not None
    words = intake.RAWNESS_WORDS.get(chosen.verdict, intake.RAWNESS_WORDS["unknown"])
    plate_verdicts = (meta.rawness or {}).get("plate_verdicts") or {}
    return ImportTrustView(
        study_id=study_id,
        applies=True,
        why="" if current else NOT_CURRENT,
        card_id=trust.CARD_ID,
        kind=trust.CARD_KIND,
        question=trust.QUESTION,
        verdict=chosen.verdict,
        verdict_title=words[0],
        verdict_meaning=words[1],
        connector_label=meta.connector.label,
        recipe=trust.recipe(meta.connector.id),
        plates=[
            TrustPlateView(run_id=p.run_id, verdict=str(plate_verdicts.get(p.run_id, "unknown")))
            for p in meta.plates
        ],
        n_instrument_cq=n_cq,
        n_wells=sum(p.n_wells for p in meta.plates),
        options=options,
        status="pending_human" if requests else "decided" if decision else "open",
        in_use=option,  # type: ignore[arg-type]
        cap=cap.level,
        cap_reason=cap.note,
        decision=decision,
        requests=requests,
        can_decide=current,
        decide_note=DECIDE_NOTE if current else "",
        inbox_head=inbox.head,
    )


@router.get("/studies/{study_id}/import-trust", response_model=ImportTrustView)
def get_import_trust(study_id: str, ctx: Ctx) -> ImportTrustView:
    """Whether the study's imported curves can be trusted as they are, and who decided it."""
    return build_view(ctx, study_id, _visible(ctx, study_id))


@router.post("/studies/{study_id}/import-trust/decide", response_model=TrustDecided)
def decide_import_trust(study_id: str, body: TrustDecide, ctx: Ctx) -> TrustDecided:
    """A person chooses an option of the Import Trust card, with a reason (a Studio session).

    Recorded in the session's inbox in one write; ``cq_only`` (or leaving it) analyses the
    study again (the ``analyse`` job). Blind like every result; ``studio`` (409) for a study
    analysed outside Studio, one whose curves call for no card, an option already chosen and
    Cq only without instrument Cq values; ``stale`` (409) when the analysis or the inbox
    changed since the view.
    """
    from qpilot.web.routers.studio import HUMAN, call, changed, ensure_analysis
    from qpilot.web.views import analysed_study

    sid = _visible(ctx, study_id)
    if sid is None:
        raise api_error(409, "studio", OUTSIDE_STUDIO)
    reason = body.reason.strip()
    if not reason:
        raise api_error(422, "bad_request", "Say why (the reason is kept in the record).")
    if body.option not in trust.OPTIONS:
        raise api_error(422, "bad_request", "This card has no such option.")
    if analysed_study(ctx.studio, sid) != study_id:
        raise api_error(409, "stale", STALE, head=ctx.studio.head(sid))
    view = build_view(ctx, study_id, sid)
    if not view.applies:
        raise api_error(409, "studio", view.why)
    outcome = call(
        ctx.studio.decide_import_trust,
        sid,
        body.option,
        HUMAN,
        reason,
        expected_head=body.expected_inbox,
        study_id=study_id,
    )
    if outcome.status == "stale":
        raise api_error(409, "stale", STALE, head=outcome.head)
    if outcome.status != "decided":
        raise api_error(403, "refused", f"Not done: {outcome.reason or 'refused'}.")
    changed(ctx, sid)
    job = ensure_analysis(ctx, sid) if outcome.changed else None
    ctx.bus.publish({"type": "study.changed", "key": sid, "source": "page"})
    ctx.bus.publish({"type": "study.changed", "key": study_id, "source": "page"})
    message = (
        DONE_BACK.get(body.option, DONE[body.option]) if outcome.changed else DONE[body.option]
    )
    return TrustDecided(
        status="decided",
        option=body.option,  # type: ignore[arg-type]
        message=message,
        study_id=study_id,
        changed=outcome.changed,
        inbox_head=outcome.head,
        job=job,
    )
