"""Results routes: a study's results, one gene, the flip matrix, the Decision Cards, the chain.

A study analysed from a Studio session answers ``403 blind`` while that session's design or
curves are not confirmed (again). Every write here is a person's (``actor="human"``, set by the
server) and carries ``expected_head``: a card that changed since the page read it answers
``409 stale`` with the current head. Undo writes a new chain entry; nothing is ever removed.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter

from qpilot.core.store import StudyNotFound
from qpilot.schemas import DecisionOutcome
from qpilot.web import results_views as rv
from qpilot.web.context import AppContext, Ctx, api_error, check_key, is_study
from qpilot.web.contract import (
    CardsView,
    CardView,
    DecideBody,
    DecisionDone,
    DecisionsView,
    Explanation,
    FlipsView,
    GeneView,
    JobStarted,
    JobView,
    ResultsView,
    TurnDownBody,
    UndoBody,
)
from qpilot.web.jobs import JobError, Progress

router = APIRouter(tags=["results"])

CARD_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}\Z")
HUMAN = "human"
EXPLAIN_S = 8.0
STALE = (
    "Something was decided since you loaded this (another tab or an agent). Here is the current "
    "state: please read the card again, then decide."
)
NOT_CURRENT = (
    "This analysis is no longer the session's current one (an accepted change re-ran it): "
    "decide on the current results."
)


# ---- helpers ---------------------------------------------------------------------------------


def study(ctx: AppContext, study_id: str) -> str | None:
    """Check the id, the study and the blind rule; return the study's session (if any)."""
    check_key(study_id)
    if not is_study(ctx.store, study_id):
        raise api_error(404, "not_found", "There is no analysed study with this id.")
    sid = rv.session_of_study(ctx.store, study_id)
    if sid is not None and not ctx.studio.results_visible(sid):
        raise api_error(
            403,
            "blind",
            "Results stay hidden until the design and the curves are confirmed in Studio.",
            session=sid,
        )
    return sid


def writable(ctx: AppContext, study_id: str) -> str | None:
    """:func:`study`, and for a session's study: it is the analysis of the design of now."""
    from qpilot.web.views import analysed_study

    sid = study(ctx, study_id)
    if sid is not None and analysed_study(ctx.studio, sid) != study_id:
        raise api_error(409, "studio", NOT_CURRENT, session=sid)
    return sid


def card_id_ok(card_id: str) -> str:
    """A card id is lowercase letters, digits and underscores; anything else is 404."""
    if not CARD_ID.match(card_id or ""):
        raise api_error(404, "not_found", "There is no Decision Card with this id.")
    return card_id


def changed(ctx: AppContext, study_id: str, sid: str | None) -> None:
    """Tell every open page that this study (and its session) changed."""
    for key in filter(None, (study_id, sid)):
        ctx.bus.publish({"type": "study.changed", "key": key, "source": "page"})


def done(
    ctx: AppContext,
    study_id: str,
    sid: str | None,
    card_id: str,
    outcome: DecisionOutcome,
    message: str,
) -> DecisionDone:
    """The answer to a write (or the refusal it maps to)."""
    from qpilot.app_state import next_card

    if outcome.status == "stale":
        raise api_error(409, "stale", STALE, head=outcome.chain_head)
    changed(ctx, study_id, sid)
    if outcome.status not in ("applied", "rejected"):
        message = rv_sentence(outcome.reason or outcome.status)
    upcoming = next_card(ctx.store.cards(study_id))
    if outcome.status == "applied" and upcoming is None:
        message += " Every choice is decided; export the record when you are ready."
    return DecisionDone(
        outcome=outcome,
        message=message,
        head=outcome.chain_head,
        card=rv.one_card(ctx.store, study_id, card_id),
        next_card=upcoming.id if upcoming else None,
    )


def rv_sentence(text: str) -> str:
    """A refusal as a sentence."""
    text = str(text).strip() or "That was refused."
    text = text[:1].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def decide_errors(err: Exception) -> Exception:
    """Map the core's refusals to the API's errors."""
    from qpilot.core.decisions import DecisionError

    if isinstance(err, StudyNotFound):
        return api_error(404, "not_found", "There is no analysed study with this id.")
    if isinstance(err, KeyError):
        return api_error(404, "not_found", "There is no Decision Card with this id.")
    if isinstance(err, DecisionError):
        return api_error(422, "bad_request", rv_sentence(err))
    return err


# ---- reading ---------------------------------------------------------------------------------


@router.get("/studies/{study_id}/results", response_model=ResultsView)
def get_results(study_id: str, ctx: Ctx) -> ResultsView:
    """The study's results: summary, rule, reference genes, every gene's call and robustness."""
    sid = study(ctx, study_id)
    return rv.results_view(ctx.store, study_id, sid)


@router.get("/studies/{study_id}/genes/{gene}", response_model=GeneView)
def get_gene(study_id: str, gene: str, ctx: Ctx) -> GeneView:
    """Everything about one compared gene, with the cards that can change it."""
    study(ctx, study_id)
    if not gene or len(gene) > 128:
        raise api_error(404, "not_found", "There is no compared gene with this name.")
    try:
        return rv.gene_view(ctx.store, study_id, gene)
    except KeyError as err:
        raise api_error(404, "not_found", "There is no compared gene with this name.") from err


@router.get("/studies/{study_id}/flips", response_model=FlipsView)
def get_flips(study_id: str, ctx: Ctx) -> FlipsView:
    """Decisions × genes: where one decision alone changes a gene's call."""
    study(ctx, study_id)
    return rv.flips_view(ctx.store, study_id)


@router.get("/studies/{study_id}/cards", response_model=CardsView)
def get_cards(study_id: str, ctx: Ctx) -> CardsView:
    """The Decision Cards, most impact first, with the chain head they were read at."""
    study(ctx, study_id)
    return rv.cards_view(ctx.store, study_id)


@router.get("/studies/{study_id}/cards/{card_id}", response_model=CardView)
def get_card(study_id: str, card_id: str, ctx: Ctx) -> CardView:
    """One Decision Card."""
    study(ctx, study_id)
    try:
        return rv.one_card(ctx.store, study_id, card_id_ok(card_id))
    except KeyError as err:
        raise api_error(404, "not_found", "There is no Decision Card with this id.") from err


@router.get("/studies/{study_id}/decisions", response_model=DecisionsView)
def get_decisions(study_id: str, ctx: Ctx) -> DecisionsView:
    """The hash-chained decision log, the requests waiting for a person, and the head."""
    study(ctx, study_id)
    return rv.decisions_view(ctx.store, study_id)


# ---- a person decides (always actor="human") -------------------------------------------------


@router.post("/studies/{study_id}/cards/{card_id}/decide", response_model=DecisionDone)
def decide(study_id: str, card_id: str, body: DecideBody, ctx: Ctx) -> DecisionDone:
    """Decide a card, with a reason (only the Undo button writes an undo)."""
    from qpilot.core.decisions import apply_decision

    sid = writable(ctx, study_id)
    card_id_ok(card_id)
    reason = body.reason.strip()
    if reason.startswith(rv.UNDO_PREFIX):  # only Undo may write an undo
        reason = reason[len(rv.UNDO_PREFIX) :].strip()
    try:
        outcome = apply_decision(
            ctx.store, study_id, card_id, body.option, reason, HUMAN, body.expected_head
        )
    except Exception as err:
        raise decide_errors(err) from err
    labels = {o.id: o.label for o in outcome.card.options} if outcome.card else {}
    return done(
        ctx, study_id, sid, card_id, outcome, f"Decided: {labels.get(body.option, body.option)}."
    )


@router.post("/studies/{study_id}/cards/{card_id}/undo", response_model=DecisionDone)
def undo(study_id: str, card_id: str, body: UndoBody, ctx: Ctx) -> DecisionDone:
    """Undo the last change on a card: a new entry restoring the option before it."""
    from qpilot.core.decisions import MAX_REASON, apply_decision

    sid = writable(ctx, study_id)
    card_id_ok(card_id)
    try:
        ctx.store.card(study_id, card_id)
    except Exception as err:
        raise decide_errors(err) from err
    target = rv.undo_target(ctx.store.entries(study_id), card_id)
    if target is None:
        raise api_error(409, "studio", "Nothing to undo on this card.")
    reason = body.reason.strip()
    if not reason:
        raise api_error(422, "bad_request", "Type a reason for the undo first.")
    text = f"{rv.UNDO_PREFIX} {reason}"[:MAX_REASON]
    try:
        outcome = apply_decision(
            ctx.store, study_id, card_id, target, text, HUMAN, body.expected_head
        )
    except Exception as err:
        raise decide_errors(err) from err
    labels = {o.id: o.label for o in outcome.card.options} if outcome.card else {}
    message = f"Undone: back to {labels.get(target, target)}, written as a new entry."
    return done(ctx, study_id, sid, card_id, outcome, message)


@router.post("/studies/{study_id}/cards/{card_id}/reject-request", response_model=DecisionDone)
def turn_down(study_id: str, card_id: str, body: TurnDownBody, ctx: Ctx) -> DecisionDone:
    """Turn down an agent's request on a card, with a reason (the card stays as it was)."""
    from qpilot.core.decisions import reject_request

    sid = study(ctx, study_id)
    card_id_ok(card_id)
    try:
        ctx.store.card(study_id, card_id)
    except Exception as err:
        raise decide_errors(err) from err
    if not body.reason.strip():
        raise api_error(422, "bad_request", "Give a reason for turning the request down.")
    try:
        outcome = reject_request(
            ctx.store, study_id, card_id, body.reason, body.expected_head, body.option
        )
    except KeyError as err:
        raise api_error(409, "studio", "There is no request waiting on this card.") from err
    except Exception as err:
        raise decide_errors(err) from err
    return done(ctx, study_id, sid, card_id, outcome, "The agent's request was turned down.")


@router.post(
    "/studies/{study_id}/cards/{card_id}/explain", response_model=JobStarted, status_code=202
)
def explain(study_id: str, card_id: str, ctx: Ctx) -> JobStarted:
    """Explain a card with the model (a job); only when a model is configured to answer."""
    study(ctx, study_id)
    card_id_ok(card_id)
    try:
        card = ctx.store.card(study_id, card_id)
    except Exception as err:
        raise decide_errors(err) from err
    client = ctx.studio.client
    if not getattr(client, "available", False):
        raise api_error(
            409,
            "no_model",
            "No model is set up to answer: the explanation on the card is the engine's own "
            "template. Settings says how to connect one.",
        )
    store = ctx.store

    def work(progress: Progress) -> dict[str, Any]:
        from qpilot.ai.explain import explain_card, log_line
        from qpilot.ai.profile import Profile, build_fewshots, load_profile
        from qpilot.core.validator import names_from_result

        progress(f"Asking {client.provider} to explain the card (every number is checked)")
        try:
            profile = load_profile()
        except Exception:  # a broken profile must not stop an explanation; the default is used
            profile = Profile()
        result, cards = store.get(study_id), store.cards(study_id)
        shots = build_fewshots(store.entries(study_id), cards, profile.max_fewshots)
        try:
            explained = explain_card(
                card, result.facts, profile=profile, client=client,
                allowed_names=names_from_result(result), fewshots=shots,
            )  # fmt: skip
        except Exception as err:
            raise JobError("no_answer", rv_sentence(f"No explanation: {err}")) from err
        store.append_ai_call(study_id, log_line(explained, client))
        why = explained.error
        note = f"The model was not used: {why}." if explained.fallback and why else ""
        return Explanation(
            card_id=card_id,
            text=rv.fact_text(
                explained.tokens, result.facts, "template" if explained.fallback else "model"
            ),
            validated=explained.validated,
            fallback=explained.fallback,
            provider=explained.provider,
            note=note,
        ).model_dump(mode="json")

    job = ctx.jobs.submit(
        "card.explain", work, title="Explaining the card", key=study_id, typical_s=EXPLAIN_S
    )
    return JobStarted(job=JobView(**job.view()))
