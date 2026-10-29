"""Workspace routes: the list, opening a file (or the demo), and a workspace's frame.

A *session* is a Studio session (named ``input_sha256[:12]``): the AI proposes, the engine
checks, a person decides, and results stay hidden until the design and the curves are
confirmed. A *study* is an analysis made outside a session (``qpilot run``, an agent's
``qpcr_study``); its results are shown straight away.

Opening takes an RDML file (``rdml``, opened as it is) or what an instrument wrote (``files``:
one export or a whole export set, sorted by content in :mod:`qpilot.web.intake`; a vendor export
is read once into deterministic RDML and the session opens that).
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.concurrency import run_in_threadpool

from qpilot.core.store import StudyNotFound
from qpilot.io.connectors import CaptureError
from qpilot.studio_service import StudioError
from qpilot.web import intake, studio_views, views
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


def _unreadable(name: str, err: Exception, path: Path | None = None) -> str:
    """Why a dropped file cannot be read, in the person's words (``intake.unreadable``)."""
    return intake.unreadable(name, err, path)


def _remember_sentence(ctx: AppContext, sid: str, sentence: str) -> None:
    if sentence:
        with ctx.lock:
            ctx.settings.setdefault("sentences", {})[sid] = sentence[: views.MAX_SENTENCE]


def _open_job(
    ctx: AppContext,
    rdml: Path,
    sheet: Path | None,
    sentence: str,
    unused: list[str] | None = None,
) -> JobView:
    """Open as a job, named by the file the person dropped; one job per file (and sheet)."""
    name = views.display_name(rdml) or rdml.name

    def work(progress: Progress) -> dict[str, Any]:
        progress(f"Reading {name} and quarantining every name")
        from qpilot.io.rdml_io import RdmlLoadError

        try:
            sid = ctx.studio.open(rdml, sheet, actor="human")
        except RdmlLoadError as err:
            raise JobError("cannot_open", _unreadable(name, err, rdml)) from err
        except Exception as err:  # any reader failure is a sentence about the person's file
            text = str(err).replace(str(rdml), name).replace(rdml.name, name).strip()
            raise JobError(
                "cannot_open", f"{name} could not be opened: {text or type(err).__name__}"
            ) from err
        _remember_sentence(ctx, sid, sentence)
        ctx.bus.publish({"type": "proposals.changed", "key": sid, "source": "page"})
        return {"key": sid, "unused": list(unused or [])}

    job = ctx.jobs.submit(
        "open",
        work,
        title=f"Opening {name}",
        key=None,
        typical_s=OPEN_TYPICAL_S,
        tag=f"{rdml}|{sheet or ''}",
    )
    return JobView(**job.view())


def _import_job(
    ctx: AppContext,
    found: intake.Sorted,
    sheet: Path | None,
    sentence: str,
) -> JobView:
    """Read an instrument export into RDML once, then open that file as a session (a job)."""
    exports = found.exports
    what = exports[0].name if len(exports) == 1 else f"{len(exports)} files"
    unused = [item.name for item in found.unused]

    def work(progress: Progress) -> dict[str, Any]:
        progress(f"Reading {what} ({found.label}) and quarantining every name")
        try:
            result = intake.read_export(ctx.store, exports)
        except intake.Refused as err:
            raise JobError(err.code, err.message) from err
        except CaptureError as err:
            raise JobError("cannot_open", f"The export could not be read: {err}.") from err
        name = intake.title(result.meta)
        progress(f"Opening {name}")
        try:
            sid = ctx.studio.open(result.rdml_path, sheet, actor="human")
        except Exception as err:  # any reader failure is a sentence about the person's files
            path = result.rdml_path
            text = str(err).replace(str(path), name).replace(path.name, name)
            raise JobError(
                "cannot_open", f"{name} could not be opened: {text.strip() or type(err).__name__}"
            ) from err
        intake.save(ctx.store, sid, result.meta, unused)
        _remember_sentence(ctx, sid, sentence)
        ctx.bus.publish({"type": "proposals.changed", "key": sid, "source": "page"})
        return {"key": sid, "unused": unused}

    job = ctx.jobs.submit(
        "open",
        work,
        title=f"Opening {what}",
        key=None,
        typical_s=OPEN_TYPICAL_S,
        tag="|".join(sorted(str(item.path) for item in exports)) + f"|{sheet or ''}",
    )
    return JobView(**job.view())


async def _open_dropped(
    ctx: AppContext, uploads: list[UploadFile], sheet: UploadFile | None, sentence: str
) -> JobView:
    """Keep every dropped file by content, sort them by content, open the RDML or the export."""
    if len(uploads) > intake.MAX_FILES:
        raise api_error(
            400,
            "too_many_files",
            f"That is {len(uploads)} files; qPilot opens at most {intake.MAX_FILES} at a time.",
        )
    for upload in uploads:  # every name is checked before any byte is kept
        problem = intake.suffix_problem(Path(upload.filename or "").name)
        if problem:
            raise api_error(400, "bad_file", problem)
    kept_files: list[Path] = []
    for upload in uploads:
        kept = await _keep(ctx, upload, "export", MAX_RDML_BYTES)
        if kept not in kept_files:  # the same file dropped twice
            kept_files.append(kept)
    kept_sheet = None
    if sheet is not None and sheet.filename:
        kept_sheet = await _keep(ctx, sheet, "sheet", MAX_SHEET_BYTES)

    def sort_and_open() -> JobView:  # off the event loop: reading by content takes seconds
        dropped: list[intake.Dropped] = []
        for kept in kept_files:
            try:
                dropped.append(intake.classify(kept, views.display_name(kept) or kept.name))
            except intake.Refused as err:
                raise api_error(400, err.code, err.message) from err
        try:
            found = intake.sort_dropped(dropped)
        except intake.Refused as err:
            raise api_error(400, err.code, err.message) from err
        if found.sheets and kept_sheet is not None:
            names = f"{views.display_name(kept_sheet)}, {found.sheets[0].name}"
            raise api_error(400, "mixed_files", f"Add one sample sheet at a time ({names}).")
        sheet_path = intake.sheet_for(ctx.store, found, kept_sheet)  # a Cq table: its columns
        if found.rdml:
            unused = [item.name for item in found.unused]
            return _open_job(ctx, intake.rdml_input(found.rdml[0]), sheet_path, sentence, unused)
        return _import_job(ctx, found, sheet_path, sentence)

    return await run_in_threadpool(sort_and_open)  # RT-EX-010


@router.post("/workspaces", response_model=JobStarted, status_code=202)
async def open_file(
    ctx: Ctx,
    rdml: Annotated[
        UploadFile | None, File(description="An RDML file (.rdml, .xml), opened as it is.")
    ] = None,
    sheet: Annotated[UploadFile | None, File(description="Optional sample sheet.")] = None,
    files: Annotated[
        list[UploadFile] | None,
        File(
            description="What the instrument wrote, instead of `rdml`: one export or a whole "
            "export set (CFX amplification per dye + Cq results + run information; QuantStudio "
            "/ StepOne / 7500; LightCycler 480; RDES or a tidy table), at most 64 files. Sorted "
            "by content: an RDML file, the export, and a sample sheet among them."
        ),
    ] = None,
    sentence: Annotated[str, Form(max_length=views.MAX_SENTENCE)] = "",
) -> JobStarted:
    """Open a file (and optional sample sheet) as a Studio session; nothing is analysed yet.

    Send ``rdml`` (one RDML file) or ``files`` (instrument exports), not both. A vendor export
    is read once into a deterministic RDML file; what was read is shown in the session's
    ``capture``.
    """
    uploads = [f for f in files or [] if f.filename]
    if uploads:
        if rdml is not None and rdml.filename:
            raise api_error(
                400, "mixed_files", "Send an RDML file or instrument export files, not both."
            )
        return JobStarted(job=await _open_dropped(ctx, uploads, sheet, sentence.strip()))
    if rdml is None or not rdml.filename:
        raise api_error(
            400, "no_file", "Choose a file to open: an RDML file or your instrument's export."
        )
    rdml_path = await _keep(ctx, rdml, "rdml", MAX_RDML_BYTES)
    sheet_path = None
    if sheet is not None and sheet.filename:
        kept_sheet = await _keep(ctx, sheet, "sheet", MAX_SHEET_BYTES)
        sheet_path = await run_in_threadpool(  # a Cq table's sample columns, off the loop
            intake.sheet_for, ctx.store, intake.Sorted(), kept_sheet
        )
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
    if stage is not None and stage not in (
        "design",
        "curves",
        "choices",
        "prism",
        "roundtrip",
        "stage",
    ):
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
    if stage in ("choices", "prism", "roundtrip") and not visible:
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
