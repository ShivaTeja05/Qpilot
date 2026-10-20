"""Never make a page wait on a cold file: read each session's file once, in the background.

A Studio session's stages, plate and results gate all start from the file's facts
(:meth:`Studio.facts`, every name quarantined, every curve fitted once). On a 64-plate file that
first read takes seconds when the machine is idle and close to a minute when it is busy; after
it, the facts are kept in memory. So:

* at start the server warms every session it can open (newest first) as one ``warm.all`` job;
* a request about a session whose facts are still cold starts (or joins) that session's ``warm``
  job and waits a moment (:attr:`AppContext.facts_wait`); if the facts are still not there, the
  frame answers what is cheap (``warming``) and anything else answers ``503 warming`` with the
  job, and the page fills in by itself when the job's ``done`` event arrives.

A bound file that is not a regular file (a pipe, a device) is never read: the session is shown
as having no file.
"""

from __future__ import annotations

import os
import stat
import threading
import time
from pathlib import Path
from typing import Any

from qpilot.core.store import StudyNotFound, StudyStore, sha256_file
from qpilot.web.context import AppContext, api_error
from qpilot.web.contract import JobView

WARM_S = 6.0  # one 64-plate file, idle machine (19 Oct: 3.7 s facts + imports)
IMPORTS = (
    "qpilot.qpcr.curves",
    "qpilot.qpcr.study",
    "qpilot.explain.templates",
    "qpilot.app_state",
    "qpilot.studio_state",
    "qsim.app",
)
COLD_MESSAGE = (
    "qPilot is reading this file for the first time since it started (on a large file this can "
    "take a minute on a busy computer). This view fills in by itself when it is done."
)

_hash_lock = threading.Lock()
_hashes: dict[tuple[str, int, int], str] = {}


def regular_file(path: str | Path | None) -> bool:
    """True for an existing regular file (never a pipe, a device or a folder)."""
    if not path:
        return False
    try:
        return stat.S_ISREG(os.stat(path).st_mode)
    except (OSError, ValueError):
        return False


def file_sha256(path: Path) -> str | None:
    """A regular file's sha256, remembered by path, size and modification time."""
    if not regular_file(path):
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (str(path), st.st_mtime_ns, st.st_size)
    with _hash_lock:
        known = _hashes.get(key)
    if known is not None:
        return known
    digest = sha256_file(path)
    with _hash_lock:
        _hashes[key] = digest
    return digest


def session_file_present(store: StudyStore, sid: str) -> bool:
    """The session's bound input is a regular file whose sha256 is the session's."""
    import json

    try:
        folder = store.find_session(sid)
    except StudyNotFound:
        return False
    meta = folder / "source.json"
    if not regular_file(meta):
        return False
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
        path = Path(data["path"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return data.get("sha256") == folder.name and file_sha256(path) == folder.name


def facts_warm(store: StudyStore, sid: str) -> bool:
    """True when this session's file facts are in memory (nothing to read)."""
    import sys

    inspect = sys.modules.get("qpilot.qpcr.inspect")
    # Not imported yet (nothing was read in this process, and importing it is slow), or being
    # imported right now by another thread: either way nothing is in memory yet.
    cached_facts = getattr(inspect, "cached_facts", None)
    if cached_facts is None:
        return False

    try:
        folder = store.find_session(sid)
    except StudyNotFound:
        return False
    return cached_facts(folder.name) is not None


def _prepare_results(ctx: AppContext, sid: str) -> None:
    """Rebuild what the results view keeps in memory for the session's current study."""
    from qpilot.web.results_views import not_compared
    from qpilot.web.views import session_meta

    study_id = session_meta(ctx.store, sid).get("current_study")
    if not study_id:
        return
    try:
        not_compared(ctx.store, ctx.store.get(study_id))
    except Exception:  # the view says only the counts then
        return


def _publish_warm(ctx: AppContext, sid: str) -> None:
    from qpilot.web.views import session_meta

    ctx.bus.publish({"type": "proposals.changed", "key": sid, "source": "warm"})
    ctx.bus.publish({"type": "study.changed", "key": sid, "source": "warm"})
    for study_id in session_meta(ctx.store, sid).get("studies") or {}:
        ctx.bus.publish({"type": "study.changed", "key": study_id, "source": "warm"})


def warm_session(ctx: AppContext, sid: str) -> Any:
    """Start (or join) the job that reads this session's file; None when there is nothing to do."""
    if facts_warm(ctx.store, sid) or not session_file_present(ctx.store, sid):
        return None
    from qpilot.web.views import display_name, session_source_record

    name = display_name(session_source_record(ctx.store, sid).get("path")) or "the file"

    def work(progress: Any) -> dict[str, Any]:
        progress(f"Reading {name}: every name quarantined, every curve fitted once")
        ctx.studio.facts(sid)
        _publish_warm(ctx, sid)
        _prepare_results(ctx, sid)
        return {"key": sid}

    return ctx.jobs.submit("warm", work, title=f"Reading {name}", key=sid, typical_s=WARM_S)


def ready(ctx: AppContext, sid: str, wait: float | None = None) -> bool:
    """True when the session's facts are warm, after starting the read and waiting a moment.

    ``wait`` defaults to :attr:`AppContext.facts_wait` (None: wait as long as the read takes).
    A session without its file is "ready": its routes answer that the file is missing.
    """
    job = warm_session(ctx, sid)
    if job is None:
        return True
    limit = ctx.facts_wait if wait is None else wait
    deadline = None if limit is None else time.monotonic() + limit
    while job.status in ("queued", "running"):
        if deadline is not None and time.monotonic() >= deadline:
            return False
        time.sleep(0.02)
    return facts_warm(ctx.store, sid) or job.status == "failed"


def require(ctx: AppContext, sid: str) -> None:
    """Raise ``503 warming`` (with the job) while this session's file is still being read."""
    if ready(ctx, sid):
        return
    job = warm_session(ctx, sid)
    details = {"job": JobView(**job.view()).model_dump(mode="json")} if job else {}
    raise api_error(503, "warming", COLD_MESSAGE, **details)


def warm_all(ctx: AppContext) -> Any:
    """At start: import the analysis modules, then read every session's file, newest first."""
    import importlib

    sessions = ctx.store.root / "sessions"

    def work(progress: Any) -> dict[str, Any]:
        progress("Loading the analysis code")
        for name in IMPORTS:
            try:
                importlib.import_module(name)
            except Exception:  # an optional part (the simulator) may be missing
                continue
        folders = []
        if sessions.is_dir():
            folders = sorted(
                (d for d in sessions.iterdir() if d.is_dir() and len(d.name) == 64),
                key=lambda d: d.stat().st_mtime,
                reverse=True,
            )
        done = 0
        for i, folder in enumerate(folders):
            sid = folder.name[:12]
            progress(
                f"Reading the files of recent studies ({i + 1} of {len(folders)})",
                i / max(1, len(folders)),
            )
            if facts_warm(ctx.store, sid) or not session_file_present(ctx.store, sid):
                continue
            try:
                ctx.studio.facts(sid)
            except Exception:  # a file that cannot be read says so when it is opened
                continue
            done += 1
            _publish_warm(ctx, sid)
            _prepare_results(ctx, sid)
        return {"sessions": done}

    return ctx.jobs.submit("warm.all", work, title="Getting ready", typical_s=WARM_S * 2)
