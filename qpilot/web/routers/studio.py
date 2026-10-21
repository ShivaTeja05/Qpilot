"""Studio routes: the blind stages of a session (design, curves) and their proposals.

The AI proposes, the engine checks, a person decides: every accept, edit, reject and confirm
here is written as ``actor="human"`` (set by the server, never by the request), and the blind
rule holds on the server — nothing pairs a group with a number before the design and the curves
are confirmed (:mod:`qpilot.web.studio_views`).

Refusals: ``stale`` (409, ``details.head``) when the inbox changed since the page read it;
``refused`` (403) when the proposal store or Studio will not take this decision; ``studio``
(409) for a Studio refusal in words; ``bad_request`` (422) for a missing reason or a malformed
edit.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Query

from qpilot.core.store import StudyNotFound
from qpilot.schemas_studio import Proposal, ProposalCheck, ProposalOutcome
from qpilot.studio_service import StudioError
from qpilot.web import studio_views as sv
from qpilot.web.context import AppContext, Ctx, api_error, check_key, is_session
from qpilot.web.contract import (
    AnalyseDone,
    BulkAction,
    BulkDone,
    BulkList,
    BulkMakers,
    BulkRequest,
    CheckEdits,
    ConfirmRequest,
    ConfirmStage,
    ConfirmView,
    CurveCallsView,
    CurveView,
    JobStarted,
    JobView,
    MattersAnswer,
    ModelSeen,
    PlateView,
    ProposalAction,
    ProposalDecided,
    ProposalView,
    ProposeAxis,
    ProposeDesign,
    ProposeOne,
    ProposeReport,
    QuarantineView,
    RefusedProposal,
)
from qpilot.web.jobs import JobError, Progress

router = APIRouter(tags=["studio"])
JOB_RESULTS = {
    "propose.design": ProposeReport,
    "propose.curves": ProposeReport,
    "proposal.matters": MattersAnswer,
    "analyse": AnalyseDone,
}

T = TypeVar("T")
HUMAN = "human"  # the only actor the page writes as
STAGES = ("design", "curves", "prism", "roundtrip")
PROPOSE_DESIGN_S = 9.0  # measured on the demo (rules only), 19 Oct
PROPOSE_CURVES_S = 15.0  # Check the curves on the demo (Curve Judge + consequence runs)
MATTERS_S = 6.0
ANALYSE_S = 30.0  # the demo's first analysis after the curves are confirmed (grid included)
MAX_IDS = 200


# ---- helpers ---------------------------------------------------------------------------------


def session(ctx: AppContext, sid: str) -> str:
    """A known session whose file is there and read (404, 409 file missing, 503 warming)."""
    from qpilot.web.warm import require

    check_key(sid)
    if not is_session(ctx.store, sid):
        raise api_error(404, "not_found", "There is no Studio session with this id.")
    file_or_409(ctx, sid)
    require(ctx, sid)
    return sid


def file_or_409(ctx: AppContext, sid: str) -> None:
    """Refuse (in words) a session whose input file is missing or changed since it was opened."""
    from qpilot.web.warm import session_file_present

    if not session_file_present(ctx.store, sid):
        raise api_error(
            409,
            "studio",
            "The input file is missing or has changed since it was opened: open it again "
            "(the session continues where it was left).",
        )


def call(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a Studio operation; its refusals become the API's errors (plain words)."""
    from qpilot.core.proposals import ProposalError
    from qpilot.io.rdml_io import RdmlLoadError
    from qpilot.qpcr.curve_judge import CurveJudgeError
    from qpilot.qpcr.curves import CurveAnalysisError

    try:
        return fn(*args, **kwargs)
    except StudyNotFound as err:
        raise api_error(404, "not_found", "There is no Studio session with this id.") from err
    except (StudioError, ProposalError) as err:
        raise api_error(409, "studio", sv.sentence(err)) from err
    except (RdmlLoadError, CurveJudgeError, CurveAnalysisError, OSError) as err:
        raise api_error(409, "studio", sv.sentence(err)) from err


def proposal_of(ctx: AppContext, sid: str, pid: str) -> Proposal:
    """The session's proposal ``pid`` (404 when unknown, or hidden while blind)."""
    if not sv.PROPOSAL_ID.match(pid or ""):
        raise api_error(404, "not_found", "There is no proposal with this id.")
    try:
        proposal = call(ctx.store.proposals(sid).get, pid)
    except KeyError as err:
        raise api_error(404, "not_found", "There is no proposal with this id.") from err
    if not sv.blind_kind(proposal) and not ctx.studio.results_visible(sid):
        raise api_error(
            403,
            "blind",
            "This proposal is about results, which stay hidden until the design "
            "and the curves are confirmed.",
        )
    return proposal


def not_a_confirm(proposal: Proposal) -> None:
    """A stage's confirm step is accepted only by “Yes, confirm” (as shown), never edited."""
    if proposal.kind == "stage.confirm":
        raise api_error(
            403,
            "refused",
            "A stage is confirmed with “Confirm this stage…” and then “Yes, confirm”, which "
            "show what it covers; a confirm step is never edited.",
        )


def changed(ctx: AppContext, sid: str) -> None:
    """Tell every open page (and tab) that this session's inbox changed."""
    ctx.bus.publish({"type": "proposals.changed", "key": sid, "source": "page"})


def ensure_analysis(ctx: AppContext, sid: str) -> JobView | None:
    """Analyse the confirmed design when results are visible and it is not analysed yet.

    Studio analyses on first use; the page starts it as soon as the curves are confirmed (or a
    person's decision changed the confirmed design), so Results never waits on a click.
    """
    from qpilot.web.views import analysed_study

    studio = ctx.studio
    try:
        if not studio.results_visible(sid) or analysed_study(studio, sid) is not None:
            return None
    except (StudioError, StudyNotFound, OSError, ValueError):
        return None

    def work(progress: Progress) -> dict[str, Any]:
        progress("Analysing the confirmed design: every curve, then qPilot's choice grid")
        try:
            study_id = studio.study(sid)
        except (StudioError, ValueError, OSError) as err:
            raise JobError("cannot_analyse", sv.sentence(err)) from err
        ctx.bus.publish({"type": "study.changed", "key": sid, "source": "page"})
        ctx.bus.publish({"type": "study.changed", "key": study_id, "source": "page"})
        return {"study_id": study_id}

    job = ctx.jobs.submit(
        "analyse", work, title="Analysing the confirmed design", key=sid, typical_s=ANALYSE_S
    )
    return JobView(**job.view())


def decided(ctx: AppContext, sid: str, outcome: ProposalOutcome, done: str) -> ProposalDecided:
    """The answer to a decision (or the refusal it maps to)."""
    if outcome.status == "stale":
        raise api_error(409, "stale", sv.WORDS["stale"], head=outcome.head)
    if outcome.status == "refused":
        raise api_error(
            403,
            "refused",
            sv.sentence(f"Not done: {outcome.reason or 'refused'}"),
            head=outcome.head,
        )
    changed(ctx, sid)
    stages = call(sv.stage_views, ctx.studio, sid)
    visible = ctx.studio.results_visible(sid)
    job = ensure_analysis(ctx, sid)
    if job is not None:
        ctx.bus.publish({"type": "study.changed", "key": sid, "source": "page"})
    return ProposalDecided(
        outcome=outcome,
        message=sv.outcome_message(outcome, done),
        head=outcome.head,
        stages=stages,
        results_visible=visible,
        job=job,
    )


# ---- reading ---------------------------------------------------------------------------------


@router.get("/sessions/{sid}/plate", response_model=PlateView)
def get_plate(sid: str, ctx: Ctx, run: str | None = Query(default=None, max_length=128)):
    """One plate's wells for the plate map (curve numbers once the design is confirmed)."""
    session(ctx, sid)
    try:
        return call(sv.plate_view, ctx.studio, sid, run)
    except KeyError as err:
        raise api_error(404, "not_found", "There is no plate with this name in the file.") from err


@router.get("/sessions/{sid}/curve", response_model=CurveView)
def get_curve(
    sid: str,
    ctx: Ctx,
    well: str = Query(max_length=160, description="`plate/well`, e.g. `AHCY_20080229/A1`."),
    target: str | None = Query(default=None, max_length=128),
):
    """One well's raw curve, its replicates, and LinRegPCR's Cq and baseline once shown."""
    session(ctx, sid)
    try:
        return call(sv.curve_view, ctx.studio, sid, well, target)
    except KeyError as err:
        raise api_error(404, "not_found", "There is no curve for this well in the file.") from err
    except ValueError as err:
        raise api_error(422, "bad_request", sv.sentence(err)) from err


@router.get("/sessions/{sid}/curve-calls", response_model=CurveCallsView)
def get_curve_calls(sid: str, ctx: Ctx, gene: str = Query(min_length=1, max_length=128)):
    """Each well of one target called under every rule (and the Curve Judge where validated)."""
    from qpilot.qpcr.amp_call import get_rule

    session(ctx, sid)
    data = call(ctx.studio.curve_calls, sid, gene)
    labels: dict[str, str] = {}
    for rule in data["rules"]:
        try:
            labels[rule] = get_rule(rule).label
        except Exception:  # a rule this build does not describe keeps its id
            labels[rule] = rule
    return CurveCallsView(**data, rule_labels=labels)


@router.get("/sessions/{sid}/quarantine", response_model=QuarantineView)
def get_quarantine(
    sid: str,
    ctx: Ctx,
    ids: str | None = Query(default=None, max_length=20_000, description="Comma-separated."),
):
    """The session's quarantined texts (quoted file text, its origin and flags)."""
    session(ctx, sid)
    wanted = [i for i in (ids or "").split(",") if i] if ids else None
    return call(sv.quarantine_view, ctx.studio, sid, wanted)


@router.get("/sessions/{sid}/model-seen", response_model=ModelSeen)
def get_model_seen(sid: str, ctx: Ctx, proposal: str | None = Query(default=None, max_length=24)):
    """What the model was sent in its last call (withheld while blind)."""
    session(ctx, sid)
    target = proposal_of(ctx, sid, proposal) if proposal else None
    return sv.model_seen(ctx.studio, sid, target)


@router.get("/sessions/{sid}/proposals/{pid}", response_model=ProposalView)
def get_proposal(sid: str, pid: str, ctx: Ctx):
    """One proposal with its evidence quoted, alternatives in words, and its status."""
    session(ctx, sid)
    proposal = proposal_of(ctx, sid, pid)
    return call(sv.proposal_view, ctx.studio, sid, proposal)


# ---- proposing (the system proposes; nothing is decided) -------------------------------------


@router.post("/sessions/{sid}/propose/design", response_model=JobStarted, status_code=202)
def propose_design(sid: str, ctx: Ctx, body: ProposeDesign | None = None) -> JobStarted:
    """Ask for design proposals: the rules always, the model when one answers (a job)."""
    from qpilot.web.views import MAX_SENTENCE

    session(ctx, sid)
    remembered = (ctx.settings.get("sentences") or {}).get(sid, "")
    text = (body.sentence if body and body.sentence is not None else remembered) or ""
    text = text.strip()[:MAX_SENTENCE]
    studio = ctx.studio

    def work(progress: Progress) -> dict[str, Any]:
        progress("Reading the file's names and asking for a design (rules, then the model)")
        try:
            report = studio.propose_design(sid, text)
        except (StudioError, ValueError, OSError) as err:
            raise JobError("not_proposed", sv.sentence(f"No design proposed: {err}")) from err
        changed(ctx, sid)
        return _report(report, "design")

    job = ctx.jobs.submit(
        "propose.design", work, title="Proposing the design", key=sid, typical_s=PROPOSE_DESIGN_S
    )
    return JobStarted(job=JobView(**job.view()))


@router.post("/sessions/{sid}/propose/curves", response_model=JobStarted, status_code=202)
def propose_curves(sid: str, ctx: Ctx) -> JobStarted:
    """Check the curves: the call rule and the Curve Judge's disagreements that matter (a job)."""
    session(ctx, sid)
    studio = ctx.studio
    if call(studio.confirmed_assembly, sid, "design") is None:
        raise api_error(409, "studio", "Confirm the design first: the curves stage follows it.")

    def work(progress: Progress) -> dict[str, Any]:
        progress("Fitting every curve, asking the Curve Judge, and testing what its calls change")
        try:
            report = studio.propose_curves(sid)
        except Exception as err:  # every failure is a sentence on the page
            raise JobError("not_proposed", sv.sentence(f"No curve calls proposed: {err}")) from err
        changed(ctx, sid)
        return _report(report, "curves")

    job = ctx.jobs.submit(
        "propose.curves", work, title="Checking the curves", key=sid, typical_s=PROPOSE_CURVES_S
    )
    return JobStarted(job=JobView(**job.view()))


def _report(report: dict[str, Any], stage: str) -> dict[str, Any]:
    word = "design" if stage == "design" else "curve"
    return ProposeReport(
        stage=stage,
        proposed=list(report.get("proposed", [])),
        refused=[RefusedProposal(**r) for r in report.get("refused", [])],
        notes=[str(n) for n in report.get("notes", [])],
        fallback=report.get("fallback"),
        fields_by_model=report.get("model_fields"),
        model_error=report.get("model_error"),
        disagreements=report.get("disagreements"),
        targets_that_matter=report.get("targets_that_matter"),
        message=sv.report_message(report, word),
    ).model_dump(mode="json")


@router.post("/sessions/{sid}/propose/comparison", response_model=ProposeOne)
def propose_comparison(sid: str, ctx: Ctx) -> ProposeOne:
    """Once exactly two groups are accepted, the rule proposes which one is the reference."""
    session(ctx, sid)
    outcome = call(ctx.studio.propose_comparison, sid)
    if outcome is None:
        return ProposeOne(
            message="A comparison is proposed once exactly two groups are accepted and no "
            "comparison is."
        )
    if outcome.status == "proposed":
        changed(ctx, sid)
        message = "The comparison is proposed: check which group is the reference, then decide."
    else:
        message = sv.sentence(f"No comparison proposed: {outcome.reason or outcome.status}")
    return ProposeOne(outcome=outcome, message=message)


@router.post("/sessions/{sid}/propose/axis", response_model=ProposeOne)
def propose_axis(sid: str, ctx: Ctx, body: ProposeAxis | None = None) -> ProposeOne:
    """The rule proposes testing a further choice (the efficiency models), or no longer testing it.

    It joins the choices stage's inbox; nothing changes until a person accepts it, and then the
    study is analysed again with the choice as one more dimension of the grid. Results only
    (403 ``blind`` before the design and the curves are confirmed); 409 ``studio`` when there is
    nothing to propose (already tested, or no other option applies to this study).
    """
    body = body or ProposeAxis()
    session(ctx, sid)
    if not ctx.studio.results_visible(sid):
        raise api_error(
            403,
            "blind",
            "Which further choices to test follows the results, which stay hidden until the "
            "design and the curves are confirmed.",
        )
    outcome = call(ctx.studio.propose_axis, sid, body.axis, body.on)
    if outcome.status == "proposed":
        changed(ctx, sid)
        message = (
            "Proposed: test the efficiency models as one more choice. Check the options, then "
            "decide; nothing changes until you accept."
            if body.on
            else "Proposed: stop testing the efficiency models. Nothing changes until you accept."
        )
    else:
        message = sv.sentence(f"Nothing proposed: {outcome.reason or outcome.status}")
    return ProposeOne(outcome=outcome, message=message)


# ---- a person decides (always actor="human") -------------------------------------------------


@router.post("/sessions/{sid}/proposals/{pid}/accept", response_model=ProposalDecided)
def accept(sid: str, pid: str, body: ProposalAction, ctx: Ctx) -> ProposalDecided:
    """Accept a proposal as it is (a reason is needed when the engine's check contradicts it)."""
    session(ctx, sid)
    proposal = proposal_of(ctx, sid, pid)
    not_a_confirm(proposal)
    reason = body.reason.strip()
    if proposal.kind == "prism.exclusion_reason" and not reason:
        raise api_error(422, "bad_request", sv.WORDS["exclusion_reason"])
    outcome = call(
        ctx.studio.accept, sid, pid, HUMAN, reason=reason, expected_head=body.expected_head
    )
    return decided(ctx, sid, outcome, f"Accepted: {sv.descriptions([proposal])[pid]}.")


@router.post("/sessions/{sid}/proposals/{pid}/edit", response_model=ProposalDecided)
def edit(sid: str, pid: str, body: ProposalAction, ctx: Ctx) -> ProposalDecided:
    """Change some payload fields and accept; the edited proposal is checked again first."""
    session(ctx, sid)
    proposal = proposal_of(ctx, sid, pid)
    not_a_confirm(proposal)
    if not isinstance(body.edits, dict):
        raise api_error(422, "bad_request", sv.WORDS["edit_not_object"])
    missing = object()
    edits = {k: v for k, v in body.edits.items() if proposal.payload.get(k, missing) != v}
    if not edits:
        raise api_error(422, "bad_request", sv.WORDS["edit_nothing"])
    reason = body.reason.strip()
    if proposal.kind == "prism.exclusion_reason" and not reason:
        raise api_error(422, "bad_request", "Say why (the reason is kept in the record).")
    outcome = call(
        ctx.studio.edit, sid, pid, HUMAN, edits=edits, reason=reason,
        expected_head=body.expected_head,
    )  # fmt: skip
    words = sv.describe(proposal, {**proposal.payload, **edits})
    return decided(ctx, sid, outcome, f"Edited and accepted: {words}.")


@router.post("/sessions/{sid}/proposals/{pid}/check", response_model=ProposalCheck)
def check_edit(sid: str, pid: str, body: CheckEdits, ctx: Ctx) -> ProposalCheck:
    """The engine's check of an edited reading, before a person accepts it (writes nothing)."""
    session(ctx, sid)
    proposal = proposal_of(ctx, sid, pid)
    not_a_confirm(proposal)
    extra = sorted(set(body.edits) - set(proposal.payload))
    if extra:
        raise api_error(
            422, "bad_request", f"An edit changes the proposal's fields only, not {extra}."
        )
    return call(ctx.studio.check, sid, proposal.model_copy(update={"edits": body.edits}))


@router.post("/sessions/{sid}/proposals/{pid}/reject", response_model=ProposalDecided)
def reject(sid: str, pid: str, body: ProposalAction, ctx: Ctx) -> ProposalDecided:
    """Turn a proposal down, with a reason (also how a confirm step is withdrawn)."""
    session(ctx, sid)
    proposal = proposal_of(ctx, sid, pid)
    reason = body.reason.strip()
    if not reason:
        raise api_error(422, "bad_request", sv.WORDS["reject_reason"])
    outcome = call(
        ctx.studio.reject, sid, pid, HUMAN, reason=reason, expected_head=body.expected_head
    )
    done = (
        "Not confirmed; the stage stays open."
        if proposal.kind == "stage.confirm"
        else f"Rejected: {sv.descriptions([proposal])[pid]}."
    )
    return decided(ctx, sid, outcome, done)


@router.post("/sessions/{sid}/proposals/{pid}/matters", response_model=JobStarted, status_code=202)
def matters(sid: str, pid: str, ctx: Ctx) -> JobStarted:
    """Does this proposal (or its first alternative) change a conclusion? Yes / no (a job)."""
    session(ctx, sid)
    proposal = proposal_of(ctx, sid, pid)
    studio = ctx.studio

    def work(progress: Progress) -> dict[str, Any]:
        progress("Running the design both ways (only 'changes a conclusion or not' is kept)")
        head = studio.head(sid)  # read first: the answer is for this chain
        try:
            answer = studio.matters(sid, proposal)
        except (StudioError, ValueError, OSError) as err:
            raise JobError("cannot_tell", sv.sentence(err)) from err
        if answer is None:
            message = sv.WORDS["matters_unknown"]
        elif answer:
            message = "This matters: the other reading changes at least one conclusion."
        else:
            message = "Either reading leads to the same conclusions."
        return MattersAnswer(
            proposal_id=pid, matters=answer, head=head, message=message
        ).model_dump(mode="json")

    job = ctx.jobs.submit(
        "proposal.matters",
        work,
        title="Does this matter?",
        key=sid,
        typical_s=MATTERS_S,
        tag=pid,
    )
    return JobStarted(job=JobView(**job.view()))


# ---- bulk: shown first, then exactly that list -----------------------------------------------


def _bulk_ids(
    ctx: AppContext, sid: str, action: BulkAction, stage: str, makers: BulkMakers = "ai"
) -> list[Proposal]:
    if stage not in STAGES:
        raise api_error(422, "bad_request", f"There is no stage {stage!r}.")
    if stage not in ("design", "curves") and not ctx.studio.results_visible(sid):
        raise api_error(
            403, "blind", "Results stay hidden until the design and curves are confirmed."
        )
    pending = call(ctx.studio.inbox, sid, stage, "proposed")
    if action == "accept":
        ids = set(call(ctx.studio.consistent_ids, sid, stage))
        return [p for p in pending if p.id in ids]
    return [
        p
        for p in pending
        if p.kind != "stage.confirm"
        and p.check.status == "contradicted"
        and (makers == "all" or p.made_by.kind in sv.AI_MAKERS)
    ]


@router.get("/sessions/{sid}/bulk/{action}", response_model=BulkList)
def bulk_list(
    sid: str,
    action: BulkAction,
    ctx: Ctx,
    stage: str = Query(max_length=16),
    makers: Annotated[
        BulkMakers,
        Query(
            description="Reject: contradicted proposals of a model or an agent (ai), or every "
            "contradicted proposal, the rules' too (all)."
        ),
    ] = "ai",
) -> BulkList:
    """Exactly what “Accept all consistent…” or “Reject contradicted …” would cover."""
    session(ctx, sid)
    listed = _bulk_ids(ctx, sid, action, stage, makers)
    if action == "accept":
        message = sv.WORDS["bulk_show"] if listed else sv.WORDS["bulk_none"]
    else:
        message = sv.WORDS["reject_show"] if listed else sv.WORDS["reject_none"]
    return BulkList(
        stage=stage,
        action=action,
        ids=[p.id for p in listed],
        proposals=listed,
        descriptions=sv.descriptions(listed),
        head=call(ctx.studio.head, sid),
        message=message,
    )


@router.post("/sessions/{sid}/bulk/{action}", response_model=BulkDone)
def bulk_do(sid: str, action: BulkAction, body: BulkRequest, ctx: Ctx) -> BulkDone:
    """Accept (or reject, with one reason) exactly the list the person was shown."""
    session(ctx, sid)
    current = [p.id for p in _bulk_ids(ctx, sid, action, body.stage, body.makers)]
    if not body.ids:
        raise api_error(422, "bad_request", "The list is empty: nothing was done.")
    if len(set(body.ids)) != len(body.ids) or not set(body.ids) <= set(current):
        raise api_error(
            409, "stale", sv.WORDS["list_changed"], head=call(ctx.studio.head, sid), ids=current
        )
    reason = body.reason.strip()
    if action == "accept":
        outcomes = call(
            ctx.studio.accept_all_consistent,
            sid,
            body.stage,
            HUMAN,
            body.ids,
            reason=reason,
            expected_head=body.expected_head,
        )
        done = sum(1 for o in outcomes if o.status == "accepted")
        message = f"Accepted {done} proposal{'s' * (done != 1)}, one record entry each."
    else:
        if not reason:
            raise api_error(422, "bad_request", sv.WORDS["reject_all_reason"])
        if body.expected_head is not None and body.expected_head != call(ctx.studio.head, sid):
            raise api_error(409, "stale", sv.WORDS["stale"], head=call(ctx.studio.head, sid))
        outcomes = call(ctx.studio.reject_many, sid, body.ids, HUMAN, reason)
        done = sum(1 for o in outcomes if o.status == "rejected")
        message = (
            f"Rejected {done} proposal{'s' * (done != 1)}, one record entry each, with your reason."
        )
    others = [o for o in outcomes if o.status not in ("accepted", "rejected")]
    if others:
        message += f" {len(others)} not done: " + "; ".join(
            sorted({str(o.reason or o.status) for o in others})
        )
    if done:
        changed(ctx, sid)
        ensure_analysis(ctx, sid)
    return BulkDone(
        action=action,
        done=done,
        outcomes=outcomes,
        message=message,
        head=call(ctx.studio.head, sid),
        stages=call(sv.stage_views, ctx.studio, sid),
        results_visible=ctx.studio.results_visible(sid),
    )


# ---- confirming a stage: shown first, then “Yes, confirm” ------------------------------------


def _confirm_view(ctx: AppContext, sid: str, stage: str, message: str = "") -> ConfirmView:
    studio = ctx.studio
    proposals = call(studio.inbox, sid, stage)
    pending = [p for p in proposals if p.kind == "stage.confirm" and p.status == "proposed"]
    confirm = pending[-1] if pending else None
    by_id = {p.id: p for p in call(studio.inbox, sid)}
    covered = (confirm.payload.get("covers") or []) if confirm else []
    covers = [by_id[i] for i in covered if i in by_id]
    warnings: list[str] = []
    if confirm is not None and stage == "choices" and studio.results_visible(sid):
        cards = call(studio.store.cards, call(studio.study, sid))
        still = [c for c in cards if c.status in ("open", "pending_human")]
        if still:
            warnings.append(
                f"{len(still)} Decision Card(s) are still open: they would be exported at their "
                "recommended option, and deciding them later re-opens this stage."
            )
    if not message:
        message = (
            f"Here is what confirming the {stage} stage covers. Nothing is confirmed until you "
            "press “Yes, confirm”."
            if confirm
            else f"No confirm step is waiting for the {stage} stage."
        )
    return ConfirmView(
        stage=stage,  # type: ignore[arg-type]
        proposal=confirm,
        covers=covers,
        descriptions=sv.descriptions(covers),
        warnings=warnings,
        ready=confirm is not None,
        message=message,
        head=call(studio.head, sid),
    )


def _confirm_allowed(ctx: AppContext, sid: str, stage: str) -> None:
    if stage == "choices" and not ctx.studio.results_visible(sid):
        raise api_error(403, "blind", "Confirm the design and the curves first.")


@router.get("/sessions/{sid}/confirm/{stage}", response_model=ConfirmView)
def get_confirm(sid: str, stage: ConfirmStage, ctx: Ctx) -> ConfirmView:
    """The stage's pending confirm step and exactly what it covers."""
    session(ctx, sid)
    _confirm_allowed(ctx, sid, stage)
    return _confirm_view(ctx, sid, stage)


@router.post("/sessions/{sid}/confirm/{stage}", response_model=ConfirmView)
def prepare_confirm(sid: str, stage: ConfirmStage, ctx: Ctx) -> ConfirmView:
    """“Confirm this stage…”: the system proposes the confirm step; it shows what it covers."""
    session(ctx, sid)
    _confirm_allowed(ctx, sid, stage)
    try:
        outcome = ctx.studio.propose_confirm(sid, stage)
    except (StudioError, ValueError) as err:
        raise api_error(409, "studio", sv.sentence(f"Not ready to confirm: {err}")) from err
    if outcome.status != "proposed":
        raise api_error(
            409, "studio", sv.sentence(f"Not ready to confirm: {outcome.reason or outcome.status}")
        )
    changed(ctx, sid)
    return _confirm_view(ctx, sid, stage)


@router.post("/sessions/{sid}/confirm/{stage}/accept", response_model=ProposalDecided)
def confirm(sid: str, stage: ConfirmStage, body: ConfirmRequest, ctx: Ctx) -> ProposalDecided:
    """“Yes, confirm”: a person accepts the confirm step that was shown."""
    session(ctx, sid)
    _confirm_allowed(ctx, sid, stage)
    proposal = proposal_of(ctx, sid, body.proposal_id)
    if proposal.kind != "stage.confirm" or proposal.subject != stage:
        raise api_error(
            422, "bad_request", "Press “Confirm this stage…” first: it shows what it covers."
        )
    outcome = call(ctx.studio.accept, sid, proposal.id, HUMAN, expected_head=body.expected_head)
    if outcome.status != "accepted":
        return decided(ctx, sid, outcome, "")
    after = {s.stage: s for s in ctx.studio.stages(sid)}
    if not after[stage].confirmed:
        done = (
            f"The confirm was recorded, but the {stage} stage changed since it was proposed, so "
            "it is not confirmed: confirm it again."
        )
    else:
        done = f"The {stage} stage is confirmed."
        if stage in ("design", "curves") and ctx.studio.results_visible(sid):
            done += " Both blind stages are confirmed: the results are being analysed."
    return decided(ctx, sid, outcome, done)
