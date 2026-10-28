"""The one server's guard: this machine only, this page only, this launch only.

Every request passes :class:`Guard` (a plain ASGI middleware, so the event stream is never
buffered):

* **Host allow-list.** A request whose ``Host`` is not ``127.0.0.1`` or ``localhost`` is refused
  (400), so a web page that rebinds its own name to this machine cannot reach the API.
* **Launch token.** Every ``/api`` request needs the token of this launch, from the HttpOnly,
  ``SameSite=Strict`` cookie that opening the printed link (``/?token=…``) sets, or from the
  ``X-Qpilot-Token`` header (tests, scripts). Another user of this computer, or a page in another
  browser profile, has neither. ``QPILOT_APP_TOKEN`` fixes the token (launch.json, tests).
* **Same origin for writes.** A ``POST``/``PUT``/``PATCH``/``DELETE`` whose ``Origin`` (or, with no
  ``Origin``, whose ``Referer``) is another site is refused (403), cookie or not.
* **Headers.** A strict Content-Security-Policy (scripts, styles, fonts, images and connections
  from this server only: the page makes no outbound request), ``nosniff``, no referrer, no
  framing, and ``no-store`` on every API answer.

Uploads are capped here (:data:`MAX_UPLOAD_BYTES`) before a body is read into memory.
"""

from __future__ import annotations

import hmac
import os
import secrets
import shutil
import traceback
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from dataclasses import dataclass
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost"})
TOKEN_COOKIE = "qpilot_token"
TOKEN_HEADER = "x-qpilot-token"
TOKEN_ENV = "QPILOT_APP_TOKEN"
MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # an RDML file; sheets and records are capped lower
MAX_BODY_BYTES = 1024 * 1024  # any other write (JSON) is small
CROSS_ORIGIN = "Requests from another site are refused."
INTERNAL = (
    "Something went wrong inside qPilot (nothing was changed by it). The terminal where qPilot "
    "runs shows the details; please report them."
)
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
#: A hosted sandbox turns read-only while its disk has less than this free (QPILOT_MIN_FREE_MB).
HOSTED_MIN_FREE_MB = 1024
SANDBOX_FULL = (
    "The public sandbox's disk is full, so it only shows what is there until it restarts "
    "(which empties it). To analyse your own files, install qPilot and run qpilot app."
)

CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        # Components set inline style attributes (positions, colours); no inline <script> ever.
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)
SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"content-security-policy", CSP.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), interest-cohort=()"),
)


@dataclass(frozen=True)
class Hosting:
    """Where this server is reachable from (environment; local by default).

    Local (the default): ``127.0.0.1`` / ``localhost`` only, a launch key, no framing.
    Hosted (``QPILOT_HOSTED=1``, a public sandbox such as a Hugging Face Space): the extra host
    names in ``QPILOT_ALLOWED_HOSTS``, writes also from the sites in ``QPILOT_ALLOWED_ORIGINS``
    (e.g. a frontend that proxies ``/api``), framing by ``QPILOT_FRAME_ANCESTORS``, and no launch
    key (nothing private lives there: the page says so). Comma-separated lists. Every visitor
    may write, so a hosted server refuses writes (507) while the disk holding its store
    (``QPILOT_STUDIES_DIR``) has less than ``QPILOT_MIN_FREE_MB`` free (1024 by default): one
    visitor's uploads and exports cannot fill the disk the store needs (RT-EX-007).
    """

    hosted: bool = False
    hosts: frozenset[str] = LOCAL_HOSTS
    origins: frozenset[str] = frozenset()
    frame_ancestors: tuple[str, ...] = ()
    data_dir: str | None = None
    min_free_mb: int = 0

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Hosting:
        """Read the hosting settings (local unless ``QPILOT_HOSTED=1``)."""
        env = os.environ if env is None else env
        if (env.get("QPILOT_HOSTED") or "").strip() != "1":
            return cls()

        def items(name: str) -> list[str]:
            return [x.strip() for x in (env.get(name) or "").split(",") if x.strip()]

        try:
            min_free = int(env.get("QPILOT_MIN_FREE_MB") or HOSTED_MIN_FREE_MB)
        except ValueError:
            min_free = HOSTED_MIN_FREE_MB
        return cls(
            hosted=True,
            hosts=LOCAL_HOSTS | {host_name(h) for h in items("QPILOT_ALLOWED_HOSTS")},
            origins=frozenset(o.rstrip("/").lower() for o in items("QPILOT_ALLOWED_ORIGINS")),
            frame_ancestors=tuple(items("QPILOT_FRAME_ANCESTORS")),
            data_dir=(env.get("QPILOT_STUDIES_DIR") or "").strip() or None,
            min_free_mb=max(min_free, 0),
        )

    def disk_full(self) -> bool:
        """True when a hosted server's store has less free disk than ``min_free_mb``."""
        if not self.hosted or self.min_free_mb <= 0:
            return False
        folder = self.data_dir or os.path.expanduser("~")
        while folder and not os.path.isdir(folder):  # the store may not exist yet
            parent = os.path.dirname(folder)
            folder = parent if parent != folder else ""
        try:
            free = shutil.disk_usage(folder or "/").free
        except OSError:
            return False
        return free < self.min_free_mb * 1024 * 1024

    def headers(self) -> tuple[tuple[bytes, bytes], ...]:
        """The security headers; framing allowed only to the configured ancestors."""
        if not self.frame_ancestors:
            return SECURITY_HEADERS
        csp = CSP.replace(
            "frame-ancestors 'none'", "frame-ancestors " + " ".join(self.frame_ancestors)
        )
        out = [(k, v) for k, v in SECURITY_HEADERS if k != b"x-frame-options"]
        return tuple(
            (k, csp.encode()) if k == b"content-security-policy" else (k, v) for k, v in out
        )


Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def launch_token() -> str:
    """This launch's token: ``QPILOT_APP_TOKEN`` when set, else 32 random URL-safe bytes."""
    fixed = (os.environ.get(TOKEN_ENV) or "").strip()
    return fixed if fixed else secrets.token_urlsafe(32)


def _headers(scope: Scope) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in scope.get("headers") or []:
        out.setdefault(key.decode("latin-1").lower(), value.decode("latin-1"))
    return out


def host_name(host: str) -> str:
    """The name part of a ``Host`` header (``[::1]:7860`` → ``::1``; ``a:1`` → ``a``)."""
    host = host.strip().lower()
    if host.startswith("["):
        return host[1 : host.find("]")] if "]" in host else host
    return host.rsplit(":", 1)[0] if ":" in host else host


def same_site(url: str, host: str) -> bool:
    """True when ``url`` (an Origin or Referer) is this server as the browser addressed it."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and parts.netloc.lower() == host.strip().lower()


def cookie_name(host: str) -> str:
    """The launch-key cookie's name for this server's port (cookies ignore ports).

    Two launches on two ports keep two cookies, and another server on 127.0.0.1 is never sent
    this launch's key under a name it would read.
    """
    host = host.strip().lower()
    port = ""
    if host.startswith("["):
        rest = host[host.find("]") + 1 :] if "]" in host else ""
        port = rest[1:] if rest.startswith(":") else ""
    elif ":" in host:
        port = host.rsplit(":", 1)[1]
    return f"{TOKEN_COOKIE}_{port if port.isdigit() else '80'}"


def _cookie_token(headers: dict[str, str], name: str = TOKEN_COOKIE) -> str | None:
    raw = headers.get("cookie")
    if not raw:
        return None
    jar: SimpleCookie = SimpleCookie()
    try:
        jar.load(raw)
    except Exception:  # a malformed cookie header is no token
        return None
    morsel = jar.get(name)
    return morsel.value if morsel else None


class Guard:
    """ASGI middleware enforcing the rules in the module docstring."""

    def __init__(self, app: ASGIApp, token: str, hosting: Hosting | None = None) -> None:
        self.app = app
        self.token = token
        self.hosting = hosting if hosting is not None else Hosting.from_env()
        self.headers = self.hosting.headers()

    def _token_ok(self, candidate: str | None) -> bool:
        return bool(candidate) and hmac.compare_digest(candidate.encode(), self.token.encode())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Check one request, then pass it on with the security headers added."""
        if scope["type"] == "websocket":  # the page uses none: refuse, never pass unchecked
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":  # lifespan
            await self.app(scope, receive, send)
            return
        headers = _headers(scope)
        host = headers.get("host", "")
        path: str = scope.get("path", "")
        method: str = scope.get("method", "GET").upper()

        if host_name(host) not in self.hosting.hosts:
            await _plain(send, 400, "This page answers on 127.0.0.1 and localhost only.")
            return

        if method in WRITE_METHODS:
            origin = headers.get("origin")
            referer = headers.get("referer")
            if origin is not None and origin != "null":
                allowed = origin.rstrip("/").lower() in self.hosting.origins
                if not (same_site(origin, host) or allowed):
                    await _json(send, 403, "cross_origin", CROSS_ORIGIN)
                    return
            elif origin == "null" or (referer and not same_site(referer, host)):
                await _json(send, 403, "cross_origin", CROSS_ORIGIN)
                return
            length = headers.get("content-length")
            if length and length.isdigit() and int(length) > _body_cap(headers):
                await _json(send, 413, "too_large", _too_large(headers))
                return
            if self.hosting.disk_full():
                await _json(send, 507, "sandbox_full", SANDBOX_FULL)
                return

        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        offered = (query.get("token") or [None])[0]
        if offered is not None and not path.startswith("/api"):
            # Opening the printed link: set the cookie, then drop the token from the address bar.
            if not self._token_ok(offered):
                await _plain(send, 403, "This link is from another launch. Use the newest link.")
                return
            rest = {k: v for k, v in query.items() if k != "token"}
            # One leading "/" only: "//x" or "/\\x" would send the browser to another site.
            target = "/" + path.lstrip("/\\")
            location = target + ("?" + urlencode(rest, doseq=True) if rest else "")
            cookie = f"{cookie_name(host)}={self.token}; Path=/; HttpOnly; SameSite=Strict"
            await send(
                {
                    "type": "http.response.start",
                    "status": 303,
                    "headers": [
                        (b"location", location.encode()),
                        (b"set-cookie", cookie.encode()),
                        (b"cache-control", b"no-store"),
                        *SECURITY_HEADERS,
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return

        is_api = path.startswith("/api")
        if (
            is_api
            and not self.hosting.hosted
            and not (
                self._token_ok(_cookie_token(headers, cookie_name(host)))
                or self._token_ok(headers.get(TOKEN_HEADER))
            )
        ):
            await _json(
                send,
                401,
                "no_token",
                "Open the link qPilot printed when it started (it carries this launch's key).",
            )
            return

        started = False

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                extra = list(self.headers)
                if is_api:
                    extra.append((b"cache-control", b"no-store"))
                message["headers"] = [*message.get("headers", []), *extra]
            await send(message)

        received = 0

        async def counted_receive() -> Message:
            # A body sent without Content-Length (chunked) is counted as it arrives, so it is
            # capped before the multipart parser spools it to disk.
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body") or b"")
                if received > _body_cap(headers):
                    raise _TooLarge
            return message

        try:
            await self.app(scope, counted_receive if method in WRITE_METHODS else receive,
                           guarded_send)  # fmt: skip
        except _TooLarge:
            if not started:
                await _json(send, 413, "too_large", _too_large(headers))
        except Exception:  # a bug: the person reads a sentence, the terminal the traceback
            traceback.print_exc()
            if not started:
                await _json(send, 500, "internal", INTERNAL)


def _body_cap(headers: dict[str, str]) -> int:
    """Uploads (multipart) may be large; every other body (JSON) is small."""
    kind = headers.get("content-type", "").split(";", 1)[0].strip().lower()
    return upload_cap() if kind == "multipart/form-data" else MAX_BODY_BYTES


def upload_cap() -> int:
    """The largest upload: ``QPILOT_MAX_UPLOAD_MB`` when set (a hosted sandbox), else 200 MB."""
    try:
        mb = int(os.environ.get("QPILOT_MAX_UPLOAD_MB", "") or 0)
    except ValueError:
        mb = 0
    return mb * 1024 * 1024 if 0 < mb * 1024 * 1024 < MAX_UPLOAD_BYTES else MAX_UPLOAD_BYTES


def _too_large(headers: dict[str, str]) -> str:
    cap = _body_cap(headers)
    if cap != MAX_BODY_BYTES:
        return f"The upload is larger than {cap // (1024 * 1024)} MB."
    return "This request is larger than qPilot accepts."


class _TooLarge(BaseException):  # noqa: N818
    """A request body passed the upload cap (a BaseException: no handler turns it into a 400)."""


async def _plain(send: Send, status: int, text: str) -> None:
    body = text.encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"text/plain; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"),
                *SECURITY_HEADERS,
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _json(send: Send, status: int, code: str, message: str) -> None:
    import json

    body = json.dumps({"error": {"code": code, "message": message}}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"),
                *SECURITY_HEADERS,
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
