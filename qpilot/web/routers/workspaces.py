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
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, UploadFile

from qpilot.core.store import StudyNotFound
from qpilot.studio_service import StudioError
from qpilot.web import studio_views, views
from qpilot.web.context import AppContext, Ctx, api_error, check_key, is_session
from qpilot.web.contract import (
    DemoFetched,
    JobStarted,
    JobView,
    OpenDone,
    ProposalList,
    WarmAllDone,
    WarmDone,
    WorkspaceList,
    WorkspaceView,
)
from qpilot.web.jobs import JobError, Progress
from qpilot.web.routers.system import demo_info

router = APIRouter(tags=["workspaces"])
JOB_RESULTS = {
    "open": OpenDone,
    "demo.fetch": DemoFetched,
    "warm": WarmDone,
    "warm.all": WarmAllDone,
}

MAX_SHEET_BYTES = 20 * 1024 * 1024
MAX_RDML_BYTES = 200 * 1024 * 1024
CHUNK = 1024 * 1024
OPEN_TYPICAL_S = 4.5  # the demo's intake, measured (workflow.json, 19 Oct)


def _jobs(ctx: AppContext, key: str) -> list[JobView]:
    return [JobView(**j.view()) for j in ctx.jobs.active(key)]


@router.get("/workspaces", response_model=WorkspaceList)
def list_workspaces(ctx: Ctx) -> WorkspaceList:
    """Every Studio session and every study analysed outside one, newest first."""
    from qpilot.web.warm import warm_session

    return WorkspaceList(
        workspaces=views.workspaces(ctx.studio, warm=lambda sid: warm_session(ctx, sid))
    )


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
        views.remember_name(kept, name)
        return kept
    finally:
        tmp.unlink(missing_ok=True)


def _declares_entities(path: Path) -> bool:
    """True when a plain XML file declares entities (the hardened parser refuses those)."""
    try:
        with path.open("rb") as fh:
            head = fh.read(64 * 1024)
    except OSError:
        return False
    return b"<!ENTITY" in head


def _unreadable(name: str, why: str, path: Path | None = None) -> str:
    """Why a dropped file cannot be read, in the person's words (the loader's reason kept)."""
    if path is not None and "not a valid RDML or XML" in why and _declares_entities(path):
        return (
            f"{name} could not be read: it declares XML entities, which qPilot refuses (they "
            "can make a file pull in other files). Export RDML again from your instrument's "
            "software."
        )
    if "too large" in why:
        detail = why.split("input too large", 1)[1].strip(" ()") if "input too large" in why else ""
        if "compression ratio" in detail:
            return (
                f"{name} could not be read: it is too large when unpacked (its {detail}); qPilot "
                "refuses it before unpacking. Export the RDML file again."
            )
        return f"{name} could not be read: it is too large ({detail or 'over the limit'})."
    if "no rdml_data.xml" in why or "fails the RDML schema" in why or "unsupported RDML" in why:
        reason = why.split(": ", 1)[1] if ": " in why else why
        return (
            f"{name} could not be read: {reason}. Export RDML again from your instrument's "
            "software."
        )
    return (
        f"{name} could not be read: it is not a valid RDML file. Export RDML again from your "
        "instrument's software, then open that file."
    )


def _open_job(ctx: AppContext, rdml: Path, sheet: Path | None, sentence: str) -> JobView:
    """Open as a job, named by the file the person dropped; one job per file (and sheet)."""
    name = views.display_name(rdml) or rdml.name

    def work(progress: Progress) -> dict[str, Any]:
        progress(f"Reading {name} and quarantining every name")
        from qpilot.io.rdml_io import RdmlLoadError

        try:
            sid = ctx.studio.open(rdml, sheet, actor="human")
        except RdmlLoadError as err:
            raise JobError("cannot_open", _unreadable(name, str(err), rdml)) from err
        except Exception as err:  # any reader failure is a sentence about the person's file
            text = str(err).replace(str(rdml), name).replace(rdml.name, name).strip()
            raise JobError(
                "cannot_open", f"{name} could not be opened: {text or type(err).__name__}"
            ) from err
        if sentence:
            with ctx.lock:
                ctx.settings.setdefault("sentences", {})[sid] = sentence[: views.MAX_SENTENCE]
        ctx.bus.publish({"type": "proposals.changed", "key": sid, "source": "page"})
        return {"key": sid}

    job = ctx.jobs.submit(
        "open",
        work,
        title=f"Opening {name}",
        key=None,
        typical_s=OPEN_TYPICAL_S,
        tag=f"{rdml}|{sheet or ''}",
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
    from qpilot.web.warm import ready

    warm = ready(ctx, sid)  # a cold file is read in the background; the frame never waits long
    if warm:
        ensure_analysis(ctx, sid)  # confirmed but not analysed yet (e.g. after a restart)
    return views.session_view(ctx.studio, sid, _jobs(ctx, sid), ready=warm)


@router.get("/studies/{study_id}", response_model=WorkspaceView)
def get_study(study_id: str, ctx: Ctx) -> WorkspaceView:
    """A study's frame (a study analysed outside a Studio session, or a session's study)."""
    from qpilot.web.routers.results import study

    study(ctx, study_id)  # 404, or 403 blind for a session's study while it is blind
    return views.study_view(ctx.store, study_id, _jobs(ctx, study_id))


@router.get("/sessions/{sid}/proposals", response_model=ProposalList)
def list_proposals(
    sid: str,
    ctx: Ctx,
    stage: str | None = None,
    status: Literal["proposed", "accepted", "edited", "rejected", "superseded"] | None = None,
) -> ProposalList:
    """A stage's inbox (or every stage's): contradicted first, then cannot-check, then rest."""
    check_key(sid)
    if stage is not None and stage not in ("design", "curves", "prism", "roundtrip", "stage"):
        raise api_error(400, "bad_stage", f"There is no stage {stage!r}.")
    if not is_session(ctx.store, sid):
        raise api_error(404, "not_found", "There is no Studio session with this id.")
    from qpilot.web.routers.studio import file_or_409
    from qpilot.web.warm import require

    file_or_409(ctx, sid)
    require(ctx, sid)
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
