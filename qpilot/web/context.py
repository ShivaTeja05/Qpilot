"""What every request handler shares: the store, Studio, jobs, events, and the private folders.

One :class:`AppContext` per server. The store is the same on-disk store the MCP server
(``qpilot serve``) writes, so the page and an agent always see one study.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request

from qpilot.core.store import StudyNotFound, StudyStore
from qpilot.studio_service import Studio
from qpilot.web.events import EventBus, StoreWatcher
from qpilot.web.jobs import JobRunner

KEY = re.compile(r"^[0-9a-f]{12}\Z")


@dataclass
class AppContext:
    """Shared state of one server process."""

    store: StudyStore
    studio: Studio
    bus: EventBus
    jobs: JobRunner
    token: str
    private: Path  # uploads/ and exports/ live here; removed when the server stops
    audit_dirs: dict[str, Path] = field(default_factory=dict)  # attached read-only (qsim app)
    settings: dict[str, Any] = field(default_factory=lambda: {"autonomy": "suggest"})
    watcher: StoreWatcher | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    downloads: dict[str, Path] = field(default_factory=dict)  # opaque id -> file in exports/

    @property
    def uploads(self) -> Path:
        """Where uploaded files are kept for this launch (Studio binds sessions to them)."""
        path = self.private / "uploads"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def exports(self) -> Path:
        """The only folder files are downloaded from."""
        path = self.private / "exports"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def close(self) -> None:
        """Stop the watcher and the pool; remove the private folder."""
        if self.watcher is not None:
            self.watcher.stop()
        self.jobs.shutdown()
        shutil.rmtree(self.private, ignore_errors=True)


def make_context(
    store: StudyStore | None = None,
    studio: Studio | None = None,
    *,
    token: str,
    watch: bool = True,
    audit_dirs: dict[str, Path] | None = None,
) -> AppContext:
    """Build the shared state (and start the store watcher unless ``watch`` is False)."""
    store = store or (studio.store if studio is not None else StudyStore())
    studio = studio or Studio(store)
    bus = EventBus()
    ctx = AppContext(
        store=store,
        studio=studio,
        bus=bus,
        jobs=JobRunner(bus),
        token=token,
        private=Path(tempfile.mkdtemp(prefix="qpilot-app-")),
        audit_dirs=dict(audit_dirs or {}),
    )
    if watch:
        ctx.watcher = StoreWatcher(store.root, bus)
        ctx.watcher.start()
    return ctx


def ctx_of(request: Request) -> AppContext:
    """FastAPI dependency: the server's :class:`AppContext`."""
    return request.app.state.ctx


Ctx = Annotated[AppContext, Depends(ctx_of)]
"""A route parameter typed ``Ctx`` receives the server's :class:`AppContext`."""


def check_key(key: str) -> str:
    """A workspace key is 12 lowercase hex (a session id or a study id); anything else is 404."""
    if not isinstance(key, str) or not KEY.match(key):
        raise api_error(404, "not_found", "There is no workspace with this id.")
    return key


def is_session(store: StudyStore, key: str) -> bool:
    """True when ``key`` names a Studio session."""
    try:
        store.find_session(key)
    except StudyNotFound:
        return False
    return True


def is_study(store: StudyStore, key: str) -> bool:
    """True when ``key`` names an analysed study."""
    try:
        store.workspace(key)
    except StudyNotFound:
        return False
    return True


def api_error(status: int, code: str, message: str, **details: Any) -> HTTPException:
    """An ``HTTPException`` whose body is ``{"error": {code, message, details}}``."""
    return HTTPException(
        status_code=status, detail={"code": code, "message": message, "details": details}
    )
