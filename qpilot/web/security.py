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
from collections.abc import Awaitable, Callable, MutableMapping
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost"})
TOKEN_COOKIE = "qpilot_token"
TOKEN_HEADER = "x-qpilot-token"
TOKEN_ENV = "QPILOT_APP_TOKEN"
MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # an RDML file; sheets and records are capped lower
CROSS_ORIGIN = "Requests from another site are refused."
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

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


def _cookie_token(headers: dict[str, str]) -> str | None:
    raw = headers.get("cookie")
    if not raw:
        return None
    jar: SimpleCookie = SimpleCookie()
    try:
        jar.load(raw)
    except Exception:  # a malformed cookie header is no token
        return None
    morsel = jar.get(TOKEN_COOKIE)
    return morsel.value if morsel else None


class Guard:
    """ASGI middleware enforcing the rules in the module docstring."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    def _token_ok(self, candidate: str | None) -> bool:
        return bool(candidate) and hmac.compare_digest(candidate.encode(), self.token.encode())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Check one request, then pass it on with the security headers added."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = _headers(scope)
        host = headers.get("host", "")
        path: str = scope.get("path", "")
        method: str = scope.get("method", "GET").upper()

        if host_name(host) not in LOCAL_HOSTS:
            await _plain(send, 400, "This page answers on 127.0.0.1 and localhost only.")
            return

        if method in WRITE_METHODS:
            origin = headers.get("origin")
            referer = headers.get("referer")
            if origin is not None and origin != "null":
                if not same_site(origin, host):
                    await _json(send, 403, "cross_origin", CROSS_ORIGIN)
                    return
            elif origin == "null" or (referer and not same_site(referer, host)):
                await _json(send, 403, "cross_origin", CROSS_ORIGIN)
                return
            length = headers.get("content-length")
            if length and length.isdigit() and int(length) > MAX_UPLOAD_BYTES:
                await _json(send, 413, "too_large", "The upload is larger than 200 MB.")
                return

        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        offered = (query.get("token") or [None])[0]
        if offered is not None and not path.startswith("/api"):
            # Opening the printed link: set the cookie, then drop the token from the address bar.
            if not self._token_ok(offered):
                await _plain(send, 403, "This link is from another launch. Use the newest link.")
                return
            rest = {k: v for k, v in query.items() if k != "token"}
            location = path + ("?" + urlencode(rest, doseq=True) if rest else "")
            cookie = f"{TOKEN_COOKIE}={self.token}; Path=/; HttpOnly; SameSite=Strict"
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
        if is_api and not (
            self._token_ok(_cookie_token(headers)) or self._token_ok(headers.get(TOKEN_HEADER))
        ):
            await _json(
                send,
                401,
                "no_token",
                "Open the link qPilot printed when it started (it carries this launch's key).",
            )
            return

        async def guarded_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                extra = list(SECURITY_HEADERS)
                if is_api:
                    extra.append((b"cache-control", b"no-store"))
                message["headers"] = [*message.get("headers", []), *extra]
            await send(message)

        await self.app(scope, receive, guarded_send)


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
