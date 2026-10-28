"""Live updates: an in-process event bus, a watcher of the study store, and the SSE stream.

The page never polls the store. Three sources publish here:

* the job runner (``job.updated``: queued, running with a step, done, failed);
* the API itself after a write (``study.changed``, ``proposals.changed``);
* :class:`StoreWatcher`, which notices writes made by **another process** — an agent through
  ``qpilot serve``, a script, another qPilot — by the size and mtime of the hash-chained logs,
  once a second, and publishes the same events. An agent's request therefore reaches the page
  within about a second, without a reload.

Events are small JSON objects ``{"type": ..., "key": ..., ...}``; the page re-reads what it shows
for that workspace. Nothing in an event is trusted for display beyond its ids.

One write is told once: an event published by this process about a workspace makes the watcher
take that workspace's logs as seen (:meth:`StoreWatcher.absorb`), so it does not tell the same
write again a second later. Every event carries ``store_seq`` (a counter of the changes told so
far; job progress does not count) and, when a page's request caused it, that tab's ``origin``
(:data:`ORIGIN`, from the ``x-qpilot-tab`` header), so the tab that wrote — which re-reads by
itself — and the others each re-read once.
"""

from __future__ import annotations

import asyncio
import json
import re
import stat
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any

HEARTBEAT_S = 15.0
MAX_RESULTS_BYTES = 256 * 1024 * 1024
WATCH_INTERVAL_S = 1.0
SETTLE_MAX_S = 3.0  # a change still going on is told at least this often
QUEUE_SIZE = 256
WATCHED = {
    "decisions.jsonl": "study.changed",
    "pending.jsonl": "study.changed",
    "cards.json": "study.changed",
    "proposals.jsonl": "proposals.changed",
    "studio.json": "proposals.changed",
}
#: Events about what is stored (they move ``store_seq``); job progress and model status do not.
STORE_EVENTS = frozenset(
    {"study.changed", "proposals.changed", "settings.changed", "instruments.changed"}
)
#: The page tab whose request is being answered (``x-qpilot-tab``; None outside a request).
ORIGIN: ContextVar[str | None] = ContextVar("qpilot_origin", default=None)
_KEY = re.compile(r"^[0-9a-f]{12,64}\Z")


class EventBus:
    """Fan-out of events to every open stream; safe to publish from any thread."""

    def __init__(self) -> None:
        self._subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[dict[str, Any]]]]
        self._subscribers = set()
        self._lock = threading.Lock()
        self._seq = 0
        self._store_seq = 0
        self.boot = uuid.uuid4().hex[:12]  # a restarted server is another stream
        self._hooks: list[Callable[[dict[str, Any]], None]] = []

    @property
    def store_seq(self) -> int:
        """How many store changes were told so far (answers carry it as ``x-qpilot-store-seq``)."""
        return self._store_seq

    def on_publish(self, hook: Callable[[dict[str, Any]], None]) -> None:
        """Call ``hook(event)`` for every event, before it is sent (the watcher's absorb)."""
        self._hooks.append(hook)

    def publish(self, event: dict[str, Any]) -> None:
        """Send ``event`` to every subscriber (dropped for a subscriber whose queue is full)."""
        origin = ORIGIN.get()
        with self._lock:
            self._seq += 1
            if event.get("type") in STORE_EVENTS:
                self._store_seq += 1
            event = {**event, "seq": self._seq, "store_seq": self._store_seq, "at": time.time()}
            if origin and "origin" not in event:
                event["origin"] = origin
            targets = list(self._subscribers)
        for hook in self._hooks:
            try:
                hook(event)
            except Exception:  # a hook never stops an event
                pass
        for loop, queue in targets:
            try:
                loop.call_soon_threadsafe(_offer, queue, event)
            except RuntimeError:  # that loop has closed; its stream is gone
                self._drop(loop, queue)

    def _drop(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers.discard((loop, queue))

    async def stream(self, is_disconnected: Any) -> AsyncIterator[str]:
        """Server-sent events for one client until it disconnects (heartbeat every 15 s)."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(QUEUE_SIZE)
        with self._lock:
            self._subscribers.add((loop, queue))
        try:
            yield "retry: 2000\n\n"
            yield _sse({"type": "hello", "store_seq": self._store_seq, "boot": self.boot})
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_S)
                except TimeoutError:
                    if await is_disconnected():
                        return
                    yield ": keep-alive\n\n"
                    continue
                yield _sse(event)
        finally:
            self._drop(loop, queue)


def _offer(queue: asyncio.Queue[dict[str, Any]], event: dict[str, Any]) -> None:
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        pass  # a stalled client misses events; it re-reads everything when it reconnects


def _sse(event: dict[str, Any]) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"


class StoreWatcher:
    """Publishes ``study.changed`` / ``proposals.changed`` when a workspace's logs change on disk.

    ``key`` in the event is the 12-hex id the page uses: a study id for a study workspace, the
    session id (``input_sha256[:12]``) for a Studio session.
    """

    def __init__(self, root: Path, bus: EventBus, interval: float = WATCH_INTERVAL_S) -> None:
        self.root = Path(root)
        self.bus = bus
        self.interval = interval
        self._seen: dict[Path, tuple[int, int]] = {}
        self._pending: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        bus.on_publish(self.absorb)

    def start(self) -> None:
        """Start watching on a daemon thread (the first scan only records what is there)."""
        if self._thread is not None:
            return
        self.scan(publish=False)
        self._thread = threading.Thread(target=self._run, name="qpilot-store-watcher", daemon=True)
        self._thread.start()

    def absorb(self, event: dict[str, Any]) -> None:
        """This process told a change of ``event["key"]``: take that workspace's logs as seen.

        The API publishes after it wrote, so what is on disk now is what the event told; the
        next scan then sees no change there and does not tell the same write a second time.
        A write by another process after this moment changes the files again and is told.
        """
        key = event.get("key")
        if (
            event.get("source") == "disk"
            or event.get("type") not in WATCHED.values()
            or not isinstance(key, str)
            or not _KEY.match(key)
        ):
            return
        with self._lock:
            for folder in self._folders_of(key):
                for name in WATCHED:
                    path = folder / name
                    try:
                        st = path.stat()
                    except OSError:
                        self._seen.pop(path, None)
                        continue
                    self._seen[path] = (st.st_mtime_ns, st.st_size)
            for pending in [p for p in self._pending if p[1] == key]:
                del self._pending[pending]

    def _folders_of(self, key: str) -> list[Path]:
        """The workspace folders a key names: a session's (``sessions/<sha>``) or a study's."""
        out: list[Path] = []
        sessions = self.root / "sessions"
        for base in (self.root, sessions):
            try:
                out.extend(
                    d
                    for d in base.glob(f"{key}*")
                    if d.is_dir() and len(d.name) == 64 and d.name != "sessions"
                )
            except OSError:
                continue
        return out

    def stop(self) -> None:
        """Stop the watcher thread."""
        self._stop.set()

    def _run(self) -> None:
        # A long write (a bulk decision appends one line per proposal) is told once it settles:
        # a change is published when the next scan sees no further change, or after
        # SETTLE_MAX_S at the latest, so a page re-reads once, not once a second.
        pending = self._pending
        while not self._stop.wait(self.interval):
            ready: list[dict[str, Any]] = []
            with self._lock:
                try:
                    fresh = self.scan(publish=False)
                except OSError:  # a workspace moved or removed mid-scan: try again next tick
                    continue
                now = time.monotonic()
                seen_now = set()
                for event in fresh:
                    key = (event["type"], event["key"])
                    seen_now.add(key)
                    first = pending.get(key, (now, event))[0]
                    pending[key] = (first, event)
                for key, (first, event) in list(pending.items()):
                    if key not in seen_now or now - first >= SETTLE_MAX_S:
                        ready.append(event)
                        del pending[key]
            for event in ready:
                self.bus.publish(event)

    def scan(self, publish: bool = True) -> list[dict[str, Any]]:
        """Compare the watched files with the last scan; publish (and return) what changed."""
        events: dict[tuple[str, str], dict[str, Any]] = {}
        current: dict[Path, tuple[int, int]] = {}
        with self._lock:
            for folder, key in self._folders():
                for name, kind in WATCHED.items():
                    path = folder / name
                    try:
                        st = path.stat()
                    except OSError:
                        continue
                    sig = (st.st_mtime_ns, st.st_size)
                    current[path] = sig
                    if self._seen.get(path) != sig:
                        events[(kind, key)] = {"type": kind, "key": key, "source": "disk"}
            self._seen = current
        out = list(events.values())
        if publish:
            for event in out:
                self.bus.publish(event)
        return out

    def _folders(self) -> list[tuple[Path, str]]:
        out: list[tuple[Path, str]] = []
        if not self.root.is_dir():
            return out
        for d in self.root.iterdir():
            if d.is_dir() and (d / "results.json").exists():
                key = _study_id(d)
                if key:
                    out.append((d, key))
        sessions = self.root / "sessions"
        if sessions.is_dir():
            for d in sessions.iterdir():
                if d.is_dir() and len(d.name) == 64:
                    out.append((d, d.name[:12]))
        return out


_ID_CACHE: dict[Path, tuple[int, str]] = {}


def _study_id(workspace: Path) -> str | None:
    """A workspace's study id (read once per change of results.json)."""
    path = workspace / "results.json"
    try:
        st = path.stat()
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_RESULTS_BYTES:
            return None  # a pipe or a device is never opened; a huge file is not read
        mtime = st.st_mtime_ns
        cached = _ID_CACHE.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        with path.open("rb") as fh:
            head = fh.read(4096).decode("utf-8", "replace")
        start = head.find('"study_id"')
        if start < 0:
            study_id = json.loads(path.read_text(encoding="utf-8"))["study_id"]
        else:
            study_id = head[start:].split(":", 1)[1].split('"')[1]
        _ID_CACHE[path] = (mtime, study_id)
        return study_id
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return None
