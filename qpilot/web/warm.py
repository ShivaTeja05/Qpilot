"""Never make a page wait on a cold file: read each session's file once, in the background.

A Studio session's stages, plate and results gate all start from the file's facts
(:meth:`Studio.facts`, every name quarantined, every curve fitted once). On a 64-plate file that
first read takes seconds when the machine is idle and close to a minute when it is busy; after
it, the facts are kept in memory. So:

* at start the server warms every session it can open (newest first) as one ``warm.all`` job;
* a request about a session whose facts are still cold starts (or joins) that session's ``warm``
  job and waits a moment (:attr:`AppContext.facts_wait`); if the facts are still not there, the
  frame answers what is cheap (``warming``) and anything else answers ``503 warming`` with the
  job, and the page fills in by itself when the job's ``done`` event arrives;
* then the views a person opens next are prepared the same way (:func:`prepare_views`): each
  recent session's current study is read once through the API itself (Results, the controls,
  the report, the Evidence Ledger, Trace, the audit…), so its first visit answers from what the
  routes keep in memory instead of computing for seconds (the controls: ~20 s on the demo). A
  study analysed while the server runs (after a confirm) is prepared as soon as it exists. The
  preparation reads only (``GET``), one view at a time, and waits for quiet moments of the page.

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
from qpilot.web.context import KEY, AppContext, api_error
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


def warm_all(ctx: AppContext, app: Any = None) -> Any:
    """At start: import the analysis modules, then read every session's file, newest first.

    With ``app`` (the server's ASGI app), the views of the recent sessions' studies are prepared
    afterwards (:func:`prepare_views`), and every study analysed later as soon as it exists.
    """
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
        if app is not None:
            studies = [s for s in (_current_study(ctx, f.name[:12]) for f in folders) if s]
            prepare_views(ctx, app, studies[:PREPARE_RECENT])
        return {"sessions": done}

    if app is not None:
        follow_new_studies(ctx, app)
    return ctx.jobs.submit("warm.all", work, title="Getting ready", typical_s=WARM_S * 2)


# ---- preparing the views a person opens next ---------------------------------------------------

#: A study's views in the order a person usually opens them (each a GET under its route).
STUDY_VIEWS: tuple[tuple[str, str], ...] = (
    ("results", "the results"),
    ("cards", "the results"),
    ("flips", "the results"),
    ("gate", "the controls on every plate"),
    ("report", "the report"),
    ("evidence", "the Evidence Ledger"),
    ("review", "the run review"),
    ("trace", "Trace"),
    ("audit", "the audit"),
    ("audit/overview", "the audit"),
    ("planner", "the next-experiment planner"),
    ("claims/examples", "the claim checker"),
)
#: Views about every workspace, prepared once at start.
GLOBAL_VIEWS: tuple[tuple[str, str], ...] = (("/api/agents", "what agents did"),)
PREPARE_RECENT = 2  # sessions whose current study is prepared at start
PREPARE_S = 40.0  # the demo's views, measured (the controls are most of it)
IDLE_S = 0.4  # a step starts once the page has been quiet this long…
IDLE_MAX_S = 8.0  # …or after this long at the latest
VIEW_WAIT_S = 600.0  # the longest a view's own job is followed
_prepared: set[tuple[str, str]] = set()  # (store root, study id) prepared in this process
_prepared_lock = threading.Lock()


def _current_study(ctx: AppContext, sid: str) -> str | None:
    from qpilot.web.views import session_meta

    try:
        study = session_meta(ctx.store, sid).get("current_study")
    except Exception:  # an unreadable session prepares nothing
        return None
    return study if isinstance(study, str) and KEY.match(study) else None


def prepare_views(ctx: AppContext, app: Any, study_ids: list[str]) -> Any:
    """Read each study's views once, in the background (a ``prepare`` job); None if nothing to do.

    Each view is read through the API (``GET``), exactly as the page reads it, so whatever the
    route keeps in memory is kept; a view still being prepared by its own job is followed until
    that job is done. Nothing is written. Studies already prepared in this process are skipped.
    """
    from qpilot.web.cache import ACTIVITY

    root = str(ctx.store.root)
    with _prepared_lock:
        todo = [s for s in dict.fromkeys(study_ids) if (root, s) not in _prepared]
        _prepared.update((root, s) for s in todo)
    first = (root, "") not in _prepared
    if first:
        with _prepared_lock:
            _prepared.add((root, ""))
    if not todo and not first:
        return None
    steps = [
        (study, f"/api/studies/{study}/{view}", words)
        for study in todo
        for view, words in STUDY_VIEWS
    ]
    if first:
        steps += [("", path, words) for path, words in GLOBAL_VIEWS]

    def work(progress: Any) -> dict[str, Any]:
        read = 0
        for i, (study, path, words) in enumerate(steps):
            if study and not _is_study(ctx, study):
                continue
            waited = 0.0
            while ACTIVITY.idle_for() < IDLE_S and waited < IDLE_MAX_S:
                time.sleep(0.1)
                waited += 0.1
            progress(f"Preparing {words}", i / len(steps))
            if _read_view(ctx, app, path):
                read += 1
        progress("Ready", 1.0)
        return {"studies": todo, "views": read}

    return ctx.jobs.submit(
        "prepare",
        work,
        title="Preparing what the page shows next",
        typical_s=PREPARE_S * len(todo),
        dedupe=False,
        background=True,
    )


def prepare_curve_check(ctx: AppContext, sid: str) -> Any:
    """Once a session's design is confirmed, read its curves for the Curve Judge in advance.

    "Check the curves" is the next step then, and its first part reads every curve of the file
    (~15 s on the demo); a background ``prepare`` job reads them now, only for a file the Curve
    Judge is validated for, and only when they are not in memory already. None: nothing to do.
    """
    try:
        from qpilot.qpcr import curve_judge
        from qpilot.qpcr.study import StudySettings

        assembly = ctx.studio.confirmed_assembly(sid, through="design")
        if assembly is None or assembly.design is None:
            return None
        if ctx.studio.confirmed_assembly(sid, through="curves") is not None:
            return None  # the curves are confirmed: the check is behind
        experiment = StudySettings.from_design(assembly.design).experiment_id
        path = ctx.studio.source(sid)
        if curve_judge.features_kept(path, experiment) or not curve_judge.validated(path):
            return None
    except Exception:  # anything unreadable: the check itself says so when it runs
        return None

    def work(progress: Any) -> dict[str, Any]:
        progress("Reading every curve for the curve check")
        curve_judge.features_from_rdml(path, experiment)
        return {"key": sid}

    return ctx.jobs.submit(
        "prepare",
        work,
        title="Preparing the curve check",
        key=None,
        typical_s=CURVES_S,
        tag=f"curves:{sid}",
        background=True,
    )


CURVES_S = 15.0  # the demo's curves read for the Curve Judge, measured


def follow_new_studies(ctx: AppContext, app: Any) -> None:
    """Prepare what a person opens next as soon as an event says it is next.

    A study the moment it is analysed (its ``study.changed`` event), and a session's curve check
    the moment its design is confirmed (the page's ``proposals.changed``).
    """
    from qpilot.web.views import session_meta

    pending: set[str] = set()
    sessions: set[str] = set()
    lock = threading.Lock()
    timer: list[threading.Timer] = []

    def run() -> None:
        with lock:
            keys = list(pending)
            pending.clear()
            asked = list(sessions)
            sessions.clear()
            timer.clear()
        for sid in asked:
            prepare_curve_check(ctx, sid)
        studies: list[str] = []
        for key in keys:
            try:
                if _is_study(ctx, key):
                    studies.append(key)
                elif ctx.store.find_session(key):
                    found = session_meta(ctx.store, key).get("current_study")
                    if isinstance(found, str) and KEY.match(found):
                        studies.append(found)
            except Exception:  # a key that is neither: nothing to prepare
                continue
        if studies:
            prepare_views(ctx, app, studies)

    def later() -> None:
        if not timer:
            t = threading.Timer(2.0, run)
            t.daemon = True
            timer.append(t)
            t.start()

    def hook(event: dict[str, Any]) -> None:
        key = event.get("key")
        if event.get("type") == "proposals.changed" and event.get("source") == "page":
            if isinstance(key, str) and KEY.match(key):
                with lock:
                    sessions.add(key)
                    later()
            return
        if event.get("type") != "study.changed":
            return
        if key is None:  # everything may have changed (a fresh demo): prepare again on change
            forget_prepared(ctx)
            return
        if not isinstance(key, str):
            return
        if event.get("source") in ("warm", "prepare") or not KEY.match(key):
            return
        with lock:
            pending.add(key)
            later()

    ctx.bus.on_publish(hook)


def forget_prepared(ctx: AppContext) -> None:
    """Prepare this store's studies again when they next change (tests; a fresh demo)."""
    root = str(ctx.store.root)
    with _prepared_lock:
        for item in [p for p in _prepared if p[0] == root]:
            _prepared.discard(item)


def _is_study(ctx: AppContext, key: str) -> bool:
    try:
        ctx.store.workspace(key)
    except (StudyNotFound, OSError, ValueError):
        return False
    return True


def _read_view(ctx: AppContext, app: Any, path: str) -> bool:
    """GET ``path`` from the app itself; follow a ``loading`` answer's job, then read again."""
    deadline = time.monotonic() + VIEW_WAIT_S
    for _ in range(4):
        status, body = _asgi_get(app, ctx.token, path)
        if status == 200:
            return True
        job = _waiting_job(status, body)
        if job is None:
            return False
        found = ctx.jobs.get(job)
        while found is not None and found.status in ("queued", "running"):
            if time.monotonic() > deadline:
                return False
            time.sleep(0.2)
    return False


def _waiting_job(status: int, body: bytes) -> str | None:
    import json

    if status not in (409, 503):
        return None
    try:
        error = json.loads(body).get("error") or {}
    except (ValueError, AttributeError):
        return None
    if error.get("code") not in ("loading", "warming"):
        return None
    job = (error.get("details") or {}).get("job") or {}
    return job.get("id") if isinstance(job, dict) and isinstance(job.get("id"), str) else None


def _asgi_get(app: Any, token: str, path: str) -> tuple[int, bytes]:
    """One ``GET`` through the app in-process (no socket), as the page would send it."""
    import asyncio

    from qpilot.web.cache import INTERNAL
    from qpilot.web.security import TOKEN_HEADER

    route, _, query = path.partition("?")

    async def go() -> tuple[int, bytes]:
        status = 0
        chunks: list[bytes] = []
        asked = False

        async def receive() -> dict[str, Any]:
            nonlocal asked
            if not asked:
                asked = True
                return {"type": "http.request", "body": b"", "more_body": False}
            await asyncio.sleep(3600)  # nothing else arrives; a reply never waits on this
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": route,
            "raw_path": route.encode(),
            "query_string": query.encode(),
            "root_path": "",
            "headers": [
                (b"host", b"127.0.0.1"),
                (TOKEN_HEADER.encode(), token.encode()),
                (INTERNAL, b"1"),
            ],
            "client": ("127.0.0.1", 0),
            "server": ("127.0.0.1", 0),
        }
        await app(scope, receive, send)
        return status, b"".join(chunks)

    try:
        return asyncio.run(go())
    except Exception:  # a view that fails says so when the page opens it
        return 0, b""
