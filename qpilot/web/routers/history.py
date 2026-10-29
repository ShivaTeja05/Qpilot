"""History routes: a study's decision chain replayed, two steps diffed, two analyses compared.

Read only. A study analysed from a Studio session answers ``403 blind`` while that session's
design or curves are not confirmed (the same gate as the results), and so does the other study
of a comparison. Every conclusion is read from the study's own grid under the choices in force
at that step (:mod:`qpilot.history`), never estimated.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from qpilot.core.store import StudyNotFound
from qpilot.history import compare_studies, diff_steps, history_view
from qpilot.history.replay import HistoryError
from qpilot.web.context import AppContext, Ctx, api_error, check_key
from qpilot.web.contract_history import HistoryCompare, HistoryDiff, HistoryView
from qpilot.web.routers.results import study

router = APIRouter(tags=["history"])

MAX_STEP = 1_000_000


def visible(ctx: AppContext, study_id: str) -> str | None:
    """The results' gate (id, study, blind rule); a damaged Studio log is refused in words."""
    from qpilot.core.proposals import ProposalError

    try:
        return study(ctx, study_id)
    except ProposalError as err:
        raise api_error(
            409,
            "studio",
            f"This session's Studio log does not verify ({err}), so qPilot shows nothing from it.",
        ) from err


def _refused(err: Exception) -> Exception:
    """The engine's refusals as the API's errors."""
    if isinstance(err, StudyNotFound):
        return api_error(404, "not_found", "There is no analysed study with this id.")
    if isinstance(err, HistoryError):
        return api_error(422, "bad_request", str(err))
    return err


ComparisonQuery = Annotated[
    str | None,
    Query(description="A study with several comparisons: the one replayed (its id; the first)."),
]


@router.get("/studies/{study_id}/history", response_model=HistoryView)
def get_history(study_id: str, ctx: Ctx, comparison: ComparisonQuery = None) -> HistoryView:
    """Every step of the decision chain: the choices in force, the calls, what each changed."""
    from qpilot.web.routers.results import comparison_ok, known_comparison

    sid = visible(ctx, study_id)
    try:
        with known_comparison():
            return history_view(ctx.store, study_id, sid, comparison_ok(comparison))
    except (StudyNotFound, HistoryError) as err:
        raise _refused(err) from err


@router.get("/studies/{study_id}/history/diff", response_model=HistoryDiff)
def get_history_diff(
    study_id: str,
    ctx: Ctx,
    from_seq: Annotated[
        int | None,
        Query(alias="from", ge=0, le=MAX_STEP, description="The earlier step (0: as analysed)."),
    ] = None,
    to_seq: Annotated[
        int | None, Query(alias="to", ge=0, le=MAX_STEP, description="The later step.")
    ] = None,
    comparison: ComparisonQuery = None,
) -> HistoryDiff:
    """What changed between two steps: calls, the largest fold and holds moves, the choices."""
    visible(ctx, study_id)  # the gate answers first: a blind study says only that
    if from_seq is None or to_seq is None:
        raise api_error(422, "bad_request", "Say which two steps to compare (from and to).")
    from qpilot.web.routers.results import comparison_ok, known_comparison

    try:
        with known_comparison():
            return diff_steps(ctx.store, study_id, from_seq, to_seq, comparison_ok(comparison))
    except (StudyNotFound, HistoryError) as err:
        raise _refused(err) from err


@router.get("/studies/{study_id}/history/compare", response_model=HistoryCompare)
def get_history_compare(
    study_id: str,
    ctx: Ctx,
    other: Annotated[
        str | None, Query(max_length=64, description="Another analysis of the same file.")
    ] = None,
) -> HistoryCompare:
    """Two analyses of the same input file: the conclusions that differ, and why."""
    visible(ctx, study_id)  # the gate answers first: a blind study says only that
    if not other:
        raise api_error(422, "bad_request", "Say which other analysis of this file to compare.")
    visible(ctx, check_key(other))
    try:
        return compare_studies(ctx.store, study_id, other)
    except (StudyNotFound, HistoryError) as err:
        raise _refused(err) from err
