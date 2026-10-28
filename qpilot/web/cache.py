"""Answer each read once, and re-send nothing that did not change.

Two pieces, both below the routes (no route changes for them):

* :class:`ApiCache`, ASGI middleware on ``/api``. Every JSON ``GET`` answer gets a weak ``ETag``
  (a hash of its bytes); a request whose ``If-None-Match`` names it is answered ``304`` with no
  body, so the page's re-read after a decision costs a few bytes for every view the decision did
  not change. Every answer carries ``x-qpilot-store-seq`` (the event bus's count of store changes
  when the request began), and the ``x-qpilot-tab`` header of a request becomes the ``origin`` of
  the events it causes (:data:`qpilot.web.events.ORIGIN`). A view still being prepared
  (``409 loading`` or ``503 warming``) is answered ``202`` with the same body when the request
  says ``Prefer: respond-async`` (the page always does): the browser then logs no failed load
  for what is a normal wait; ``x-qpilot-status`` keeps the original status.
* :func:`memo`, a small bounded cache for views that are a pure function of content-addressed
  ids (a study id is the hash of its inputs, a session id the hash of its file) plus the store
  state they read, so a repeated read of the same thing is not computed again.

Nothing here changes what an answer says: the bytes of a ``200`` are the route's own.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any, TypeVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from qpilot.web.events import ORIGIN, EventBus

T = TypeVar("T")
TAB = re.compile(r"^[A-Za-z0-9_-]{1,40}\Z")
#: Bodies above this are passed through without an ETag (none of the JSON views is near it).
MAX_TAGGED = 64 * 1024 * 1024
SOFT_WAIT = {(409, "loading"), (503, "warming")}


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers") or []:
        if key == name:
            return value.decode("latin-1")
    return None


def etag_of(body: bytes) -> str:
    """The weak entity tag of a body (the same bytes always give the same tag)."""
    return 'W/"' + hashlib.blake2b(body, digest_size=16).hexdigest() + '"'


def _matches(if_none_match: str | None, tag: str) -> bool:
    if not if_none_match:
        return False
    offered = {t.strip() for t in if_none_match.split(",")}
    return tag in offered or tag.removeprefix("W/") in offered or "*" in offered


class ApiCache:
    """ETags and 304s on ``GET /api``; store sequence, tab origin and soft waits on every answer."""

    def __init__(self, app: ASGIApp, bus: EventBus) -> None:
        self.app = app
        self.bus = bus

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass one request on; buffer a JSON ``GET`` answer to tag (and maybe 304) it."""
        path: str = scope.get("path", "") if scope["type"] == "http" else ""
        if not path.startswith("/api") or path == "/api/events":
            await self.app(scope, receive, send)
            return
        tab = _header(scope, b"x-qpilot-tab")
        token = ORIGIN.set(tab if tab and TAB.match(tab) else None)
        seq = str(self.bus.store_seq).encode()
        soft = "respond-async" in (_header(scope, b"prefer") or "").lower()
        method = scope.get("method", "GET").upper()
        try:
            if method != "GET":
                await self.app(scope, receive, _stamped(send, seq, soft))
                return
            await self._get(scope, receive, send, seq, soft)
        finally:
            ORIGIN.reset(token)

    async def _get(
        self, scope: Scope, receive: Receive, send: Send, seq: bytes, soft: bool
    ) -> None:
        start: Message | None = None
        chunks: list[bytes] = []
        size = 0
        passing = False
        stamped = _stamped(send, seq, soft)

        async def buffered(message: Message) -> None:
            nonlocal start, size, passing
            if passing:
                await stamped(message)
                return
            if message["type"] == "http.response.start":
                kind = dict(message.get("headers") or []).get(b"content-type", b"")
                if message["status"] in (200, 409, 503) and kind.startswith(b"application/json"):
                    start = message
                    return
                passing = True
                await stamped(message)
                return
            if message["type"] != "http.response.body" or start is None:
                await stamped(message)
                return
            chunks.append(message.get("body", b""))
            size += len(chunks[-1])
            if message.get("more_body") and size <= MAX_TAGGED:
                return
            if message.get("more_body"):  # too large to tag: send what is held, then pass
                passing = True
                await stamped(start)
                await stamped(
                    {"type": "http.response.body", "body": b"".join(chunks), "more_body": True}
                )
                return
            body = b"".join(chunks)
            await self._finish(scope, stamped, start, body)

        await self.app(scope, receive, buffered)

    async def _finish(self, scope: Scope, stamped: Send, start: Message, body: bytes) -> None:
        if start["status"] != 200:
            await stamped(start)
            await stamped({"type": "http.response.body", "body": body})
            return
        tag = etag_of(body)
        headers = [(k, v) for k, v in start.get("headers") or [] if k != b"etag"]
        headers.append((b"etag", tag.encode()))
        if _matches(_header(scope, b"if-none-match"), tag):
            kept = [(k, v) for k, v in headers if k not in (b"content-length", b"content-type")]
            await stamped({"type": "http.response.start", "status": 304, "headers": kept})
            await stamped({"type": "http.response.body", "body": b""})
            return
        await stamped({**start, "headers": headers})
        await stamped({"type": "http.response.body", "body": body})


def _stamped(send: Send, seq: bytes, soft: bool) -> Send:
    """``send`` with the store sequence added (and a soft wait answered 202)."""
    held: list[Message] = []

    async def out(message: Message) -> None:
        if message["type"] == "http.response.start":
            headers = [*(message.get("headers") or []), (b"x-qpilot-store-seq", seq)]
            status = message["status"]
            if soft and status in (409, 503):
                # Hold the start: whether to soften it depends on the body's code.
                held.append({**message, "headers": headers})
                return
            await send({**message, "headers": headers})
            return
        if held and message["type"] == "http.response.body":
            start = held.pop()
            body = message.get("body", b"")
            code = _error_code(body) if not message.get("more_body") else None
            if code is not None and (start["status"], code) in SOFT_WAIT:
                start = {
                    **start,
                    "status": 202,
                    "headers": [
                        *start["headers"],
                        (b"x-qpilot-status", str(start["status"]).encode()),
                        (b"preference-applied", b"respond-async"),
                    ],
                }
            await send(start)
        await send(message)

    return out


def _error_code(body: bytes) -> str | None:
    import json

    try:
        data = json.loads(body)
    except ValueError:
        return None
    error = data.get("error") if isinstance(data, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) else None


# ---- computed views --------------------------------------------------------------------------


class Memo:
    """A bounded, thread-safe map from a hashable key to a computed value (least recent out)."""

    def __init__(self, size: int = 64) -> None:
        self.size = size
        self._items: OrderedDict[Hashable, Any] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: Hashable, compute: Callable[[], T]) -> T:
        """The value kept for ``key``, else ``compute()`` (kept unless it raised)."""
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                self.hits += 1
                return self._items[key]
            self.misses += 1
        value = compute()
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self.size:
                self._items.popitem(last=False)
        return value

    def clear(self) -> None:
        """Forget everything (tests; a fresh demo)."""
        with self._lock:
            self._items.clear()


_MEMOS: dict[str, Memo] = {}


def memo(name: str, size: int = 64) -> Memo:
    """The named :class:`Memo` (one per view)."""
    found = _MEMOS.get(name)
    if found is None:
        found = _MEMOS.setdefault(name, Memo(size))
    return found


def clear_all() -> None:
    """Forget every kept view (tests; a fresh demo)."""
    for m in list(_MEMOS.values()):
        m.clear()
