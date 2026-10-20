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
"""

from __future__ import annotations

import asyncio
import json
import stat
import threading
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

HEARTBEAT_S = 15.0
MAX_RESULTS_BYTES = 256 * 1024 * 1024
WATCH_INTERVAL_S = 1.0
QUEUE_SIZE = 256
WATCHED = {
    "decisions.jsonl": "study.changed",
    "pending.jsonl": "study.changed",
    "cards.json": "study.changed",
    "proposals.jsonl": "proposals.changed",
    "studio.json": "proposals.changed",
}


class EventBus:
    """Fan-out of events to every open stream; safe to publish from any thread."""

    def __init__(self) -> None:
        self._subscribers: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[dict[str, Any]]]]
        self._subscribers = set()
        self._lock = threading.Lock()
        self._seq = 0

    def publish(self, event: dict[str, Any]) -> None:
        """Send ``event`` to every subscriber (dropped for a subscriber whose queue is full)."""
        with self._lock:
            self._seq += 1
            event = {**event, "seq": self._seq, "at": time.time()}
            targets = list(self._subscribers)
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
            yield _sse({"type": "hello"})
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
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start watching on a daemon thread (the first scan only records what is there)."""
        if self._thread is not None:
            return
        self.scan(publish=False)
        self._thread = threading.Thread(target=self._run, name="qpilot-store-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the watcher thread."""
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.scan()
            except OSError:  # a workspace moved or removed mid-scan: try again next tick
                continue

    def scan(self, publish: bool = True) -> list[dict[str, Any]]:
        """Compare the watched files with the last scan; publish (and return) what changed."""
        events: dict[tuple[str, str], dict[str, Any]] = {}
        current: dict[Path, tuple[int, int]] = {}
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
