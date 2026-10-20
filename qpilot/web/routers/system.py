"""System routes: what this install is, settings, the model's status, live events and jobs."""

from __future__ import annotations

import platform
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from qpilot import __version__
from qpilot.web.context import AppContext, Ctx, api_error
from qpilot.web.contract import DemoInfo, JobView, ModelStatus, Settings, SystemView

router = APIRouter(tags=["system"])


def model_status(ctx: AppContext, check: bool = False) -> ModelStatus:
    """The model's status plus the ``outbound`` line of ``qpilot doctor``.

    A local model (or none) is asked a one-token question at most once a minute, in the
    background, as Studio does. A remote one is never contacted to render a page: its last known
    answer is shown, and only ``check`` (the person's “Check connection”) sends the request.
    """
    from qpilot.cli.core_cmds import studio_outbound_line

    studio = ctx.studio
    if check:
        _check_now(studio)
    status = studio.model_status(check=check)
    try:
        outbound = studio_outbound_line()
    except Exception:  # a misconfigured model is reported by the status itself
        outbound = "outbound: unknown (the model configuration could not be read)"
    return ModelStatus(**status, outbound=outbound)


def demo_info() -> DemoInfo:
    """The demo dataset: whether it is cached (and verified by size), where, and its source."""
    from qpilot.io.datasets import (
        VERMEULEN_BYTES,
        VERMEULEN_FILENAME,
        VERMEULEN_SHA256,
        default_cache_dir,
        demo_dataset_info,
    )

    path = default_cache_dir() / VERMEULEN_FILENAME
    cached = path.is_file() and path.stat().st_size == VERMEULEN_BYTES
    info = demo_dataset_info()
    return DemoInfo(
        cached=cached,
        path=str(path) if cached else None,
        bytes=VERMEULEN_BYTES,
        sha256=VERMEULEN_SHA256,
        source=info["url"],
        citation=info["citation"],
        licence=info["licence"],
    )


@router.get("/system", response_model=SystemView)
def system(ctx: Ctx) -> SystemView:
    """What this install is, which model it uses and what it never does."""
    from qpilot.ai.profile import autonomy_policy
    from qpilot.app_state import FOOTER
    from qpilot.integration.simulator import available
    from qpilot.io.datasets import VERMEULEN_COMMIT

    return SystemView(
        version=__version__,
        python=platform.python_version(),
        platform=platform.system(),
        method=f"LinRegPCR (rdmlpython) @ {VERMEULEN_COMMIT[:7]}",
        studies_dir=str(ctx.store.root),
        simulator=available(),
        model=model_status(ctx),
        autonomy=ctx.settings["autonomy"],
        demo=demo_info(),
        policy=list(autonomy_policy()),
        never=list(FOOTER),
    )


@router.get("/settings", response_model=Settings)
def get_settings(ctx: Ctx) -> Settings:
    """This launch's settings."""
    return Settings(**ctx.settings)


@router.put("/settings", response_model=Settings)
def put_settings(body: Settings, ctx: Ctx) -> Settings:
    """Change this launch's settings (the autonomy mode)."""
    ctx.settings.update(body.model_dump())
    ctx.bus.publish({"type": "settings.changed"})
    return Settings(**ctx.settings)


def _check_now(studio: Any) -> None:
    """Send the one-token request now (whatever the last answer's age) and wait for it."""
    from qpilot.studio_service import PING_TIMEOUT_S, _Ping

    with studio._ping_lock:
        ping = studio._pings.setdefault(studio._model_key(), _Ping())
        if ping.thread is None or not ping.thread.is_alive():
            ping.at = None  # due now
    studio._answers()
    with studio._ping_lock:
        thread = ping.thread
    if thread is not None:
        thread.join(PING_TIMEOUT_S + 1.0)


@router.post("/model/check", response_model=ModelStatus)
def check_model(ctx: Ctx) -> ModelStatus:
    """“Check connection”: ask the model one short question now (the only remote contact)."""
    return model_status(ctx, check=True)


@router.get("/model", response_model=ModelStatus)
def get_model(ctx: Ctx) -> ModelStatus:
    """The model's status (a one-token question at most once a minute, in the background)."""
    return model_status(ctx)


@router.get("/events")
async def events(request: Request, ctx: Ctx) -> StreamingResponse:
    """Server-sent events: ``job.updated``, ``study.changed``, ``proposals.changed``, …."""
    return StreamingResponse(
        ctx.bus.stream(request.is_disconnected),
        media_type="text/event-stream",
        headers={"x-accel-buffering": "no"},
    )


@router.get("/jobs/{job_id}", response_model=JobView)
def get_job(job_id: str, ctx: Ctx) -> JobView:
    """One job, with its result once it is done."""
    job = ctx.jobs.get(job_id)
    if job is None:
        raise api_error(404, "not_found", "This job is not known (it may be from another launch).")
    return JobView(**job.view())


@router.get("/jobs", response_model=list[JobView])
def list_jobs(ctx: Ctx, key: str | None = None) -> list[JobView]:
    """Jobs still queued or running (of one workspace, or all)."""
    return [JobView(**j.view()) for j in ctx.jobs.active(key)]
