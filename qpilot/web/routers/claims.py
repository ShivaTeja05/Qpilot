"""The Claim Auditor: check the claims in a paragraph against the study's own record.

* ``POST /api/studies/{id}/claims`` ``{text}`` (at most 5 000 characters): every claim the rules
  read in the text (gene, direction, fold, p, robustness words, normaliser, n, efficiency), each
  with its spans, a verdict from a fixed vocabulary (supported / holds only under some choices /
  overstated / contradicted / cannot check), the checks behind it (every number a cited fact)
  and a corrected sentence built from facts. Read-only and synchronous (a few hundred ms on the
  demo); the text is not stored.
* ``POST /api/studies/{id}/claims/read`` ``{text}``: the same, with the page's model proposing
  readings of the sentences the rules could not read (a job, ``claims.read``). The rules check
  every proposal (each value must be in the sentence it cites); the model never gives a verdict
  or a number, and a remote model is never sent the text.
* ``GET /api/studies/{id}/claims/examples``: example sentences written from this study's facts,
  each verified to come out as described, so the auditor can be tried without typing.

A study of a Studio session whose design or curves are not confirmed answers 403 ``blind``:
claims about group differences are checked only once results are visible.
"""

from __future__ import annotations

from fastapi import APIRouter

from qpilot.web.context import AppContext, Ctx, api_error
from qpilot.web.contract import JobStarted, JobView
from qpilot.web.contract_claims import (
    MAX_CLAIMS_TEXT,
    ClaimExamples,
    ClaimsAssistResult,
    ClaimsBody,
    ClaimsReport,
)
from qpilot.web.jobs import Progress

router = APIRouter(tags=["claims"])
JOB_RESULTS = {"claims.read": ClaimsAssistResult}
READ_TYPICAL_S = 20.0

TOO_LONG = (
    "Paste at most {limit} characters at a time (this text has {n}); check a long manuscript "
    "a section at a time."
)
EMPTY = "Paste a sentence or a paragraph about this study's results to check."


def _record(ctx: AppContext, study_id: str):  # noqa: ANN202 (qpilot.claims.StudyRecord)
    """The study's record, after the results routes' checks (404, 403 ``blind``, warming)."""
    from qpilot.claims import record_of
    from qpilot.web.routers.results import study

    study(ctx, study_id)
    return record_of(ctx.store, study_id)


def _count(n: int) -> str:
    """A count as the page writes it: thin spaces between thousands (``5 000``)."""
    return f"{n:,}".replace(",", "\u202f")


def _text(body: ClaimsBody) -> str:
    text = body.text
    if len(text) > MAX_CLAIMS_TEXT:
        raise api_error(
            413, "too_large", TOO_LONG.format(limit=_count(MAX_CLAIMS_TEXT), n=_count(len(text)))
        )
    if not text.strip():
        raise api_error(422, "bad_request", EMPTY)
    return text


@router.post("/studies/{study_id}/claims", response_model=ClaimsReport)
def check_claims(study_id: str, body: ClaimsBody, ctx: Ctx) -> ClaimsReport:
    """Every claim in the text, read by rules and checked against the study's record."""
    from qpilot.claims import audit_text

    record = _record(ctx, study_id)  # the study's gates (404, 403 blind) answer first
    return audit_text(_text(body), record)


@router.post("/studies/{study_id}/claims/read", response_model=JobStarted, status_code=202)
def read_claims(study_id: str, body: ClaimsBody, ctx: Ctx) -> JobStarted:
    """The same check, with the page's model proposing readings the rules missed (a job)."""
    from qpilot.claims.assist import read_with_model

    record = _record(ctx, study_id)
    text = _text(body)
    client = ctx.studio.client

    def work(progress: Progress) -> dict:
        progress("Reading the sentences the rules could not read")
        return read_with_model(text, record, client).model_dump(mode="json")

    job = ctx.jobs.submit(
        "claims.read",
        work,
        title="Reading the claims with the model",
        key=study_id,
        typical_s=READ_TYPICAL_S if client.available else None,
        dedupe=False,
    )
    return JobStarted(job=JobView(**job.view()))


@router.get("/studies/{study_id}/claims/examples", response_model=ClaimExamples)
def claim_examples(study_id: str, ctx: Ctx) -> ClaimExamples:
    """Example sentences about this study, written from its facts and verified."""
    from qpilot.claims.examples import write_examples
    from qpilot.web.results_views import headline_genes

    record = _record(ctx, study_id)
    headline = headline_genes(record.result, record.cards, ctx.store)
    return write_examples(record, headline)
