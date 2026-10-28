"""Design routes: a person finishes the design on the page, with no model, for any plate.

``GET …/design/editor`` is the editor's view (names, declared types, wells, the design so far,
what is still missing; never a number). ``POST …/design/check`` shows what recording some items
would do and the engine's check of each, writing nothing. ``POST …/design/set`` records them as
the person's own proposals, accepted in the same act with the person's reason (``actor`` is
``human``, set here, never by the request). ``GET …/design/template.csv`` is a sample sheet
pre-filled with the plate's names; ``POST …/sheet`` attaches a filled sheet to this session and
asks the rules to propose again.

Refusals: ``studio`` (409, in words: an item the hard bans refuse, or one the engine contradicts
while ``accept_contradicted`` is not set), ``stale`` (409, ``details.head``), ``bad_request``
(422), ``bad_file`` (400).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import Response

from qpilot import studio_design as sd
from qpilot.studio_service import StudioError
from qpilot.web import studio_views as sv
from qpilot.web import views
from qpilot.web.context import AppContext, Ctx, api_error
from qpilot.web.contract import JobView
from qpilot.web.contract_design import (
    DesignCheckRequest,
    DesignEditItem,
    DesignEditorView,
    DesignNeed,
    DesignPlanView,
    DesignSetRequest,
    DesignSetView,
    EditorMembership,
    EditorOption,
    EditorSample,
    EditorTarget,
    PlannedItemView,
    SheetAttached,
)
from qpilot.web.jobs import JobError, Progress
from qpilot.web.routers.studio import (
    HUMAN,
    PROPOSE_DESIGN_S,
    call,
    changed,
    ensure_analysis,
    session,
)
from qpilot.web.routers.studio import _report as propose_report

router = APIRouter(tags=["design"])


def _items(raw: list[DesignEditItem]) -> list[sd.DesignItem]:
    return [sd.DesignItem(i.kind, i.subject, dict(i.payload)) for i in raw]


def _run(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """A Studio operation whose design-edit refusals are 409 ``studio``, in words."""
    try:
        return call(fn, *args, **kwargs)
    except sd.DesignEditError as err:
        raise api_error(409, "studio", sv.sentence(err)) from err


def _sheet_name(ctx: AppContext, sid: str) -> tuple[bool, str | None]:
    try:
        path = ctx.studio.sheet(sid)
    except StudioError:
        return True, None
    if path is None:
        return False, None
    return True, views.display_name(path) or path.name


def _confirmed(ctx: AppContext, sid: str) -> bool:
    return any(s.stage == "design" and s.confirmed for s in sv.stage_views(ctx.studio, sid))


@router.get("/sessions/{sid}/design/editor", response_model=DesignEditorView)
def get_editor(sid: str, ctx: Ctx) -> DesignEditorView:
    """The design editor: every sample and target, the design so far, what it still needs."""
    session(ctx, sid)
    state = _run(sd.state, ctx.studio, sid)
    has_sheet, sheet_name = _sheet_name(ctx, sid)
    return DesignEditorView(
        head=state.head,
        samples=[
            EditorSample(**{k: v for k, v in vars(s).items() if k not in ("group", "unit")})
            for s in state.samples
        ],
        membership=[
            EditorMembership(sample=s.sample, group=s.group, unit=s.unit) for s in state.samples
        ],
        targets=[EditorTarget(**vars(t)) for t in state.targets],
        groups=state.groups,
        units=state.units,
        comparison=state.comparison,
        comparison_plan=state.plan,
        pair_by=state.pair_by,
        n_paired=state.n_paired,
        preset=state.preset,
        experiments=state.experiments,
        needs=[DesignNeed(**vars(n)) for n in state.needs],
        waiting=state.waiting,
        confirmed=_confirmed(ctx, sid),
        sample_types=[EditorOption(value=v, label=a, hint=b) for v, a, b in sd.SAMPLE_TYPE_WORDS],
        target_roles=[EditorOption(value=v, label=a, hint=b) for v, a, b in sd.TARGET_ROLE_WORDS],
        has_sheet=has_sheet,
        sheet_name=sheet_name,
        template_url=f"/api/sessions/{sid}/design/template.csv",
    )


def _plan_view(plan: sd.DesignPlan) -> DesignPlanView:
    counts: dict[str, int] = {}
    for p in plan.items:
        counts[p.action] = counts.get(p.action, 0) + 1
    rejects = sum(len(p.rejects) for p in plan.items)
    parts = []
    recorded = counts.get("new", 0) + counts.get("accept", 0)
    if recorded:
        parts.append(f"{recorded} change{'s' * (recorded != 1)} to record")
    if rejects:
        parts.append(
            f"{rejects} waiting proposal{'s' * (rejects != 1)} that say{'s' * (rejects == 1)} "
            "otherwise will be rejected"
        )
    if counts.get("unchanged"):
        parts.append(f"{counts['unchanged']} already so")
    if counts.get("refused"):
        parts.append(f"{counts['refused']} refused")
    if plan.contradicted:
        parts.append(f"{len(plan.contradicted)} contradicted by the engine's check")
    return DesignPlanView(
        head=plan.head,
        items=[
            PlannedItemView(
                kind=p.item.kind,  # type: ignore[arg-type]
                subject=p.item.subject,
                payload=dict(p.item.payload),
                action=p.action,
                words=p.words,
                check=p.check,
                refusal=p.refusal,
                accept_id=p.accept_id,
                rejects=list(p.rejects),
                also_accept=list(p.also_accept),
            )
            for p in plan.items
        ],
        counts=counts,
        n_contradicted=len(plan.contradicted),
        n_rejects=rejects,
        message=sv.sentence("; ".join(parts) or "nothing to record"),
    )


@router.post("/sessions/{sid}/design/check", response_model=DesignPlanView)
def check_design(sid: str, body: DesignCheckRequest, ctx: Ctx) -> DesignPlanView:
    """What recording these items would do, with the engine's check of each (writes nothing)."""
    session(ctx, sid)
    plan = _run(sd.plan, ctx.studio, sid, _items(body.items))
    return _plan_view(plan)


@router.post("/sessions/{sid}/design/set", response_model=DesignSetView)
def set_design(sid: str, body: DesignSetRequest, ctx: Ctx) -> DesignSetView:
    """Record design items as the person's own decisions (each checked; one reason for all)."""
    session(ctx, sid)
    reason = body.reason.strip()
    if not reason:
        raise api_error(
            422, "bad_request", "Say why (the reason is kept in the record with every change)."
        )
    result = _run(
        sd.set_design,
        ctx.studio,
        sid,
        _items(body.items),
        HUMAN,
        reason,
        expected_head=body.expected_head,
        accept_contradicted=body.accept_contradicted,
    )
    last = result.outcomes[-1] if result.outcomes else None
    if last is not None and last.status == "stale":
        raise api_error(409, "stale", sv.WORDS["stale"], head=last.head)
    if last is not None and last.status == "refused":
        raise api_error(
            403, "refused", sv.sentence(f"Nothing was recorded: {last.reason}"), head=last.head
        )
    if result.outcomes:
        changed(ctx, sid)
    parts = []
    if result.recorded:
        parts.append(f"Recorded {result.recorded} change{'s' * (result.recorded != 1)}")
    if result.rejected:
        parts.append(
            f"rejected {result.rejected} waiting proposal{'s' * (result.rejected != 1)} that "
            f"said otherwise"
        )
    if result.unchanged and not parts:
        parts.append("Nothing to record: the design already says so")
    job = ensure_analysis(ctx, sid)
    return DesignSetView(
        message=sv.sentence(", ".join(parts) or "Nothing to record"),
        head=result.head,
        recorded=result.recorded,
        rejected=result.rejected,
        unchanged=result.unchanged,
        outcomes=result.outcomes,
        stages=call(sv.stage_views, ctx.studio, sid),
        results_visible=ctx.studio.results_visible(sid),
        job=job,
    )


@router.get(
    "/sessions/{sid}/design/template.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "The sample-sheet template."}},
)
def get_template(sid: str, ctx: Ctx) -> Response:
    """A sample sheet pre-filled with this plate's samples and targets (CSV, opens in Excel)."""
    session(ctx, sid)
    text = _run(sd.template_csv, ctx.studio, sid)
    name = _template_name(ctx, sid)
    return Response(
        content=("﻿" + text).encode("utf-8"),  # a BOM, so Excel reads it as UTF-8
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


def _template_name(ctx: AppContext, sid: str) -> str:
    import re
    from pathlib import Path

    try:
        source = ctx.studio.source(sid)
        shown = views.display_name(source) or source.name
    except Exception:  # a missing file still gets a template name
        shown = sid
    stem = re.sub(r"[^A-Za-z0-9_\-. ()]+", "_", Path(shown).stem)[:80].strip(" ._") or sid
    return f"{stem} sample sheet.csv"


@router.post("/sessions/{sid}/sheet", response_model=SheetAttached, status_code=202)
async def attach_sheet(
    sid: str,
    ctx: Ctx,
    sheet: Annotated[
        UploadFile, File(description="The sample sheet (.csv, .tsv, .xlsx or .xlsm).")
    ],
) -> SheetAttached:
    """Attach a sample sheet to this session (no need to open the files again).

    The rules then propose again from it (a job). Nothing is decided.
    """
    from qpilot.io.sheets import SheetError, read_sheet, sheet_table, target_roles
    from qpilot.web.routers.workspaces import MAX_SHEET_BYTES, _keep

    session(ctx, sid)
    if not sheet.filename:
        raise api_error(400, "no_file", "Choose the sample sheet to attach.")
    kept = await _keep(ctx, sheet, "sheet", MAX_SHEET_BYTES)
    name = views.display_name(kept) or kept.name
    try:
        read = read_sheet(kept)
        usable = sheet_table(read) is not None or bool(target_roles(read))
    except SheetError as err:
        raise api_error(400, "bad_file", sv.sentence(f"{name} could not be read: {err}")) from err
    if not usable:
        raise api_error(
            400,
            "bad_file",
            f"{name} has no column qPilot recognises: a sample sheet needs a Sample column "
            "(and Group, Biological unit, Sample type, Quantity…), or a Target column with a "
            "Target role (Gene type) column. Download the template from this page to see them.",
        )
    _run(sd.attach_sheet, ctx.studio, sid, kept, HUMAN)
    changed(ctx, sid)
    studio = ctx.studio
    remembered = (ctx.settings.get("sentences") or {}).get(sid, "")

    def work(progress: Progress) -> dict[str, Any]:
        progress(f"Reading {name} and proposing the design again (rules, then the model)")
        try:
            report = studio.propose_design(sid, remembered)
        except (StudioError, ValueError, OSError) as err:
            raise JobError("not_proposed", sv.sentence(f"No design proposed: {err}")) from err
        changed(ctx, sid)
        return propose_report(report, "design")

    job = ctx.jobs.submit(
        "propose.design", work, title="Proposing the design", key=sid, typical_s=PROPOSE_DESIGN_S
    )
    return SheetAttached(
        message=f"{name} is attached to this session; the rules propose from it again.",
        sheet_name=name,
        job=JobView(**job.view()),
    )
