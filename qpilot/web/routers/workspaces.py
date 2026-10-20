"""Workspace routes: the list, opening a file (or the demo), and a workspace's frame.

A *session* is a Studio session (named ``input_sha256[:12]``): the AI proposes, the engine
checks, a person decides, and results stay hidden until the design and the curves are
confirmed. A *study* is an analysis made outside a session (``qpilot run``, an agent's
``qpcr_study``); its results are shown straight away.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, UploadFile

from qpilot.core.store import StudyNotFound
from qpilot.studio_service import StudioError
from qpilot.web import studio_views, views
from qpilot.web.context import AppContext, Ctx, api_error, check_key, is_session, is_study
from qpilot.web.contract import (
    JobStarted,
    JobView,
    ProposalList,
    WorkspaceList,
    WorkspaceView,
)
from qpilot.web.jobs import JobError, Progress
from qpilot.web.routers.system import demo_info

router = APIRouter(tags=["workspaces"])

MAX_SHEET_BYTES = 20 * 1024 * 1024
MAX_RDML_BYTES = 200 * 1024 * 1024
CHUNK = 1024 * 1024
OPEN_TYPICAL_S = 4.5  # the demo's intake, measured (workflow.json, 19 Oct)


def _jobs(ctx: AppContext, key: str) -> list[JobView]:
    return [JobView(**j.view()) for j in ctx.jobs.active(key)]


@router.get("/workspaces", response_model=WorkspaceList)
def list_workspaces(ctx: Ctx) -> WorkspaceList:
    """Every Studio session and every study analysed outside one, newest first."""
    return WorkspaceList(workspaces=views.workspaces(ctx.studio))


async def _keep(ctx: AppContext, upload: UploadFile, kind: str, limit: int) -> Path:
    """Stream an upload to the kept-inputs folder, named by its sha256 (size-capped)."""
    name = Path(upload.filename or "").name
    suffix = Path(name).suffix.lower()
    if suffix not in views.INPUT_SUFFIXES[kind]:
        allowed = " or ".join(views.INPUT_SUFFIXES[kind])
        raise api_error(400, "bad_file", f"{name or 'This file'}: expected a {allowed} file.")
    folder = views.inputs_dir(ctx.store)
    digest = hashlib.sha256()
    tmp = folder / f".upload-{id(upload)}{suffix}"
    size = 0
    try:
        with tmp.open("wb") as out:
            while chunk := await upload.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise api_error(
                        413, "too_large", f"{name} is larger than {limit // (1024 * 1024)} MB."
                    )
                digest.update(chunk)
                out.write(chunk)
        if size == 0:
            raise api_error(400, "empty_file", f"{name} is empty.")
        kept = folder / f"{digest.hexdigest()[:24]}{suffix}"
        if not kept.exists():
            shutil.move(str(tmp), kept)
        return kept
    finally:
        tmp.unlink(missing_ok=True)


def _open_job(ctx: AppContext, rdml: Path, sheet: Path | None, sentence: str) -> JobView:
    def work(progress: Progress) -> dict[str, Any]:
        progress("Reading the file and quarantining every name")
        try:
            sid = ctx.studio.open(rdml, sheet, actor="human")
        except (StudioError, ValueError, OSError) as err:
            raise JobError("cannot_open", str(err)) from err
        if sentence:
            with ctx.lock:
                ctx.settings.setdefault("sentences", {})[sid] = sentence[: views.MAX_SENTENCE]
        ctx.bus.publish({"type": "proposals.changed", "key": sid, "source": "page"})
        return {"key": sid}

    job = ctx.jobs.submit(
        "open", work, title=f"Opening {rdml.name}", key=None, typical_s=OPEN_TYPICAL_S
    )
    return JobView(**job.view())


@router.post("/workspaces", response_model=JobStarted, status_code=202)
async def open_file(
    rdml: Annotated[UploadFile, File(description="The instrument's RDML export (.rdml, .xml).")],
    ctx: Ctx,
    sheet: Annotated[UploadFile | None, File(description="Optional sample sheet.")] = None,
    sentence: Annotated[str, Form(max_length=views.MAX_SENTENCE)] = "",
) -> JobStarted:
    """Open a file (and optional sample sheet) as a Studio session; nothing is analysed yet."""
    rdml_path = await _keep(ctx, rdml, "rdml", MAX_RDML_BYTES)
    sheet_path = None
    if sheet is not None and sheet.filename:
        sheet_path = await _keep(ctx, sheet, "sheet", MAX_SHEET_BYTES)
    return JobStarted(job=_open_job(ctx, rdml_path, sheet_path, sentence.strip()))


@router.post("/workspaces/demo", response_model=JobStarted, status_code=202)
def open_demo(ctx: Ctx) -> JobStarted:
    """Open the cached demo study (``qpilot fetch-demo`` or ``POST /api/demo/fetch`` first)."""
    info = demo_info()
    if not info.cached or not info.path:
        raise api_error(
            409,
            "demo_missing",
            "The demo study is not downloaded yet: fetch it first (7 MB, SHA-256 pinned).",
        )
    return JobStarted(job=_open_job(ctx, Path(info.path), None, ""))


@router.post("/demo/fetch", response_model=JobStarted, status_code=202)
def fetch_demo(ctx: Ctx) -> JobStarted:
    """Download the demo study (pinned source, SHA-256 verified); only on a click."""

    def work(progress: Progress) -> dict[str, Any]:
        from qpilot.io.datasets import fetch_vermeulen

        progress("Downloading 7 MB from the RDML consortium's repository (pinned commit)")
        try:
            path = fetch_vermeulen()
        except Exception as err:
            raise JobError("download_failed", f"The download failed: {err}") from err
        return {"path": str(path)}

    job = ctx.jobs.submit("demo.fetch", work, title="Downloading the demo study", typical_s=5.0)
    return JobStarted(job=JobView(**job.view()))


@router.get("/sessions/{sid}", response_model=WorkspaceView)
def get_session(sid: str, ctx: Ctx) -> WorkspaceView:
    """A Studio session's frame: file facts, stages, results visibility, next step."""
    check_key(sid)
    if not is_session(ctx.store, sid):
        raise api_error(404, "not_found", "There is no Studio session with this id.")
    from qpilot.web.routers.studio import ensure_analysis

    ensure_analysis(ctx, sid)  # confirmed but not analysed yet (e.g. after a restart)
    return views.session_view(ctx.studio, sid, _jobs(ctx, sid))


@router.get("/studies/{study_id}", response_model=WorkspaceView)
def get_study(study_id: str, ctx: Ctx) -> WorkspaceView:
    """A study's frame (a study analysed outside a Studio session, or a session's study)."""
    check_key(study_id)
    if not is_study(ctx.store, study_id):
        raise api_error(404, "not_found", "There is no analysed study with this id.")
    return views.study_view(ctx.store, study_id, _jobs(ctx, study_id))


@router.get("/sessions/{sid}/proposals", response_model=ProposalList)
def list_proposals(
    sid: str,
    ctx: Ctx,
    stage: str | None = None,
    status: str | None = None,
) -> ProposalList:
    """A stage's inbox (or every stage's): contradicted first, then cannot-check, then rest."""
    check_key(sid)
    if stage is not None and stage not in ("design", "curves", "prism", "roundtrip", "stage"):
        raise api_error(400, "bad_stage", f"There is no stage {stage!r}.")
    if not is_session(ctx.store, sid):
        raise api_error(404, "not_found", "There is no Studio session with this id.")
    try:
        proposals = ctx.studio.inbox(sid, stage, status)
        head = ctx.studio.head(sid)
        visible = ctx.studio.results_visible(sid)
    except StudyNotFound as err:
        raise api_error(404, "not_found", "There is no Studio session with this id.") from err
    except StudioError as err:
        raise api_error(409, "studio", str(err)) from err
    if stage in ("prism", "roundtrip") and not visible:
        raise api_error(
            403,
            "blind",
            "Results stay hidden until the design and the curves are confirmed.",
        )
    proposals = studio_views.visible_proposals(proposals, visible)
    order = {"contradicted": 0, "cannot_check": 1, "consistent": 2}
    proposals = sorted(
        proposals,
        key=lambda p: (p.status != "proposed", order.get(p.check.status, 3)),
    )
    counts: dict[str, int] = {}
    for p in proposals:
        counts[p.status] = counts.get(p.status, 0) + 1
        if p.status == "proposed":
            counts[p.check.status] = counts.get(p.check.status, 0) + 1
    return ProposalList(
        stage=stage,
        head=head,
        proposals=proposals,
        counts=counts,
        descriptions=studio_views.descriptions(proposals),
    )
