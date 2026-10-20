"""Slow work off the request thread: curve fitting, the audit, the round trip, the model test.

A request that would take more than about a second starts a :class:`Job` and returns at once with
its id; the page follows it through ``job.updated`` events (and ``GET /api/jobs/{id}``). A job
says what it is doing (``step``), how long it has run and how long the same work usually takes
on the demo (``typical_s``, measured, never a promise). Starting the same work for the same
workspace while it runs returns the running job instead of starting it twice.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Literal

from qpilot.web.events import EventBus

JobStatus = Literal["queued", "running", "done", "failed"]
MAX_KEPT = 200
WORKERS = 3


class JobError(Exception):
    """A failure the page can show as is: a plain-words message and a stable code."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass
class Job:
    """One piece of slow work and where it stands."""

    id: str
    kind: str
    title: str
    key: str | None
    typical_s: float | None
    status: JobStatus = "queued"
    step: str = ""
    fraction: float | None = None
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    result: Any = None
    error: dict[str, str] | None = None

    def view(self) -> dict[str, Any]:
        """JSON-ready, with ``elapsed_s`` computed now."""
        end = self.finished or time.time()
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "key": self.key,
            "status": self.status,
            "step": self.step,
            "fraction": self.fraction,
            "typical_s": self.typical_s,
            "elapsed_s": round(end - self.started, 2) if self.started else 0.0,
            "result": self.result if self.status == "done" else None,
            "error": self.error,
        }


class Progress:
    """Handed to a job's function: ``step("Fitting curves", 0.4)`` updates the page."""

    def __init__(self, runner: JobRunner, job: Job) -> None:
        self._runner = runner
        self._job = job

    def __call__(self, step: str, fraction: float | None = None) -> None:
        """Say what the job is doing now (and, when known, how far along it is, 0–1)."""
        self._job.step = step
        if fraction is not None:
            self._job.fraction = max(0.0, min(1.0, float(fraction)))
        self._runner._publish(self._job)


class JobRunner:
    """A small thread pool with job records and events."""

    def __init__(self, bus: EventBus, workers: int = WORKERS) -> None:
        self.bus = bus
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="qpilot-job")
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._lock = threading.Lock()

    def submit(
        self,
        kind: str,
        fn: Callable[[Progress], Any],
        *,
        title: str,
        key: str | None = None,
        typical_s: float | None = None,
        dedupe: bool = True,
    ) -> Job:
        """Run ``fn(progress)`` on the pool; its return value (JSON-ready) is the job's result."""
        with self._lock:
            if dedupe:
                for job in self._jobs.values():
                    if job.kind == kind and job.key == key and job.status in ("queued", "running"):
                        return job
            job = Job(
                id=uuid.uuid4().hex[:16], kind=kind, title=title, key=key, typical_s=typical_s
            )
            self._jobs[job.id] = job
            while len(self._jobs) > MAX_KEPT:
                self._jobs.popitem(last=False)
        self._publish(job)
        self._pool.submit(self._run, job, fn)
        return job

    def get(self, job_id: str) -> Job | None:
        """The job with this id, if it is still kept."""
        with self._lock:
            return self._jobs.get(job_id)

    def active(self, key: str | None = None) -> list[Job]:
        """Queued and running jobs (of one workspace, or all)."""
        with self._lock:
            return [
                j
                for j in self._jobs.values()
                if j.status in ("queued", "running") and (key is None or j.key == key)
            ]

    def latest(self, kind: str, key: str | None) -> Job | None:
        """The most recent job of this kind for this workspace."""
        with self._lock:
            for job in reversed(self._jobs.values()):
                if job.kind == kind and job.key == key:
                    return job
        return None

    def _run(self, job: Job, fn: Callable[[Progress], Any]) -> None:
        job.status = "running"
        job.started = time.time()
        self._publish(job)
        try:
            job.result = fn(Progress(self, job))
            job.status = "done"
        except JobError as err:
            job.error = {"code": err.code, "message": err.message}
            job.status = "failed"
        except Exception as err:  # shown to the person; the traceback stays in the terminal
            traceback.print_exc()
            job.error = {"code": "failed", "message": _plain(err)}
            job.status = "failed"
        finally:
            job.finished = time.time()
            self._publish(job)

    def _publish(self, job: Job) -> None:
        view = job.view()
        view.pop("result", None)  # results are read with GET /api/jobs/{id}; events stay small
        self.bus.publish({"type": "job.updated", "key": job.key, "job": view})

    def shutdown(self) -> None:
        """Stop accepting work; running jobs finish on their threads."""
        self._pool.shutdown(wait=False, cancel_futures=True)


def _plain(err: BaseException) -> str:
    text = str(err).strip() or type(err).__name__
    return text[:500]
