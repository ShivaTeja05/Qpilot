"""Red team: the one server's guard (qpilot/web/security.py) under hostile requests.

Each finding is a strict xfail named ``RT-UI-NNN`` until its owner fixes it (then the owner
removes the mark). The tests without a mark are regressions: they pass today and must keep
passing as routes land.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import pytest

from qpilot.web import security
from qpilot.web.security import CSP, Guard

from .conftest import BASE, TOKEN

SAME = {"origin": "http://127.0.0.1:7860"}


# ---- the guard called directly (scopes a browser can send but a test client normalises) ----


async def _inner(scope: Any, receive: Any, send: Any) -> None:
    scope["reached"] = True
    if scope["type"] == "http":
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"inner"})
    else:
        await send({"type": "websocket.accept"})


def _call(scope: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run one request through :class:`Guard` over a stub app; return what was sent."""
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        if scope["type"] == "websocket":
            return {"type": "websocket.connect"}
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(Guard(_inner, TOKEN)(scope, receive, send))
    return sent, scope


def _http(path: str, query: str = "", host: str = "127.0.0.1:7860") -> dict[str, Any]:
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "headers": [(b"host", host.encode())],
    }


def _header(message: dict[str, Any], name: bytes) -> str | None:
    for key, value in message.get("headers", []):
        if key.lower() == name:
            return value.decode("latin-1")
    return None


@pytest.mark.xfail(
    strict=True,
    reason="RT-UI-001 the printed-link redirect copies the request path into Location, so "
    "//evil.example/?token=… (or /\\evil.example/) sends the browser to another site",
)
@pytest.mark.parametrize("path", ["//evil.example/", "/\\evil.example/", "///evil.example"])
def test_the_token_redirect_never_leaves_this_server(path):
    sent, _ = _call(_http(path, f"token={TOKEN}"))
    location = _header(sent[0], b"location") or ""
    assert sent[0]["status"] == 303
    # A path-relative target that a browser could read as another host ("//x", "/\x") is an
    # open redirect; the only safe targets start with exactly one "/" followed by neither.
    assert re.match(r"^/(?![/\\])", location), location


@pytest.mark.xfail(
    strict=True,
    reason="RT-UI-003 Guard passes every non-http scope (websocket) straight to the app: no "
    "Host check, no launch key, no Origin check — a websocket route would be open to any site",
)
def test_websocket_connections_meet_the_same_guard():
    scope = {
        "type": "websocket",
        "path": "/api/anything",
        "raw_path": b"/api/anything",
        "query_string": b"",
        "headers": [(b"host", b"evil.example"), (b"origin", b"http://evil.example")],
    }
    _, seen = _call(scope)
    assert not seen.get("reached"), "a websocket from another site reached the app"


def test_lifespan_still_reaches_the_app():
    async def inner(scope: Any, receive: Any, send: Any) -> None:
        scope["reached"] = True

    scope: dict[str, Any] = {"type": "lifespan"}
    asyncio.run(Guard(inner, TOKEN)(scope, None, None))  # type: ignore[arg-type]
    assert scope["reached"]


# ---- cookie ----------------------------------------------------------------------------------


def test_the_cookie_is_httponly_strict_session_and_host_only(raw_client):
    r = raw_client.get(f"/?token={TOKEN}", follow_redirects=False)
    cookie = r.headers["set-cookie"]
    parts = [p.strip().lower() for p in cookie.split(";")]
    assert "httponly" in parts and "samesite=strict" in parts and "path=/" in parts
    assert not any(p.startswith(("domain=", "expires=", "max-age=")) for p in parts)
    assert r.headers["referrer-policy"] == "no-referrer"  # the key never travels in a Referer
    assert r.headers["cache-control"] == "no-store"


@pytest.mark.xfail(
    strict=True,
    reason="RT-UI-002 the launch-key cookie is named qpilot_token whatever the port: cookies "
    "ignore ports, so a second launch overwrites the first tab's key (401) and every other "
    "web server on 127.0.0.1 the browser visits is sent this launch's key",
)
def test_two_launches_on_two_ports_keep_two_cookies(raw_client):
    first = raw_client.get(
        f"/?token={TOKEN}", headers={"host": "127.0.0.1:7860"}, follow_redirects=False
    )
    second = raw_client.get(
        f"/?token={TOKEN}", headers={"host": "127.0.0.1:7861"}, follow_redirects=False
    )
    name = first.headers["set-cookie"].split("=", 1)[0]
    other = second.headers["set-cookie"].split("=", 1)[0]
    assert name != other, f"both launches set {name!r}; the second overwrites the first"


# ---- the launch key --------------------------------------------------------------------------


def test_the_key_in_an_api_query_string_is_not_a_key(raw_client):
    # A key in an /api URL would end up in history, logs and Referers; only cookie and header.
    assert raw_client.get(f"/api/system?token={TOKEN}").status_code == 401


@pytest.mark.parametrize(
    "cookie",
    [
        "qpilot_token=",
        f"qpilot_token={TOKEN[:-1]}",
        f"qpilot_token={TOKEN}x",
        f"QPILOT_TOKEN={TOKEN}",
        f"x_qpilot_token={TOKEN}",
        f'qpilot_token="{TOKEN[:-1]}"',
        "qpilot_token=\x00",
        "garbage;;;===",
    ],
)
def test_near_miss_cookies_are_refused(raw_client, cookie):
    assert raw_client.get("/api/system", headers={"cookie": cookie}).status_code == 401


@pytest.mark.parametrize(
    "value", [b"", b" ", TOKEN.upper().encode(), b"\xfc" * 10, TOKEN.encode() + b"\xff"]
)
def test_near_miss_headers_are_refused(raw_client, value):
    r = raw_client.get("/api/system", headers={"x-qpilot-token": value})
    assert r.status_code == 401


def test_the_event_stream_needs_the_key(raw_client):
    r = raw_client.get("/api/events")
    assert r.status_code == 401 and r.json()["error"]["code"] == "no_token"


def test_preflight_from_another_site_gets_no_cors_grant(raw_client):
    r = raw_client.options(
        "/api/settings",
        headers={
            "origin": "http://evil.example",
            "access-control-request-method": "PUT",
            "access-control-request-headers": "x-qpilot-token, content-type",
        },
    )
    assert r.status_code >= 400
    assert "access-control-allow-origin" not in r.headers
    assert "access-control-allow-credentials" not in r.headers


# ---- Host (DNS rebinding) --------------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "localhost.",
        "localhost.:7860",
        "127.0.0.1.",
        "127.0.0.1.:7860",
        "[::1]:7860",
        "[::ffff:127.0.0.1]:7860",
        "0.0.0.0:7860",
        "127.1:7860",
        "2130706433:7860",
        "0x7f000001:7860",
        "localhost.evil.example",
        "127.0.0.1.nip.io:7860",
        "localtest.me:7860",
        "evil.example:7860",
        "",
    ],
)
def test_rebinding_names_are_refused(client, host):
    assert client.get("/api/system", headers={"host": host}).status_code == 400
    assert client.get("/", headers={"host": host}).status_code == 400


# ---- Origin / Referer on writes (CSRF) -------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        {"origin": "null"},
        {"origin": ""},
        {"origin": "http://127.0.0.1:7860."},
        {"origin": "http://127.0.0.1:7861"},
        {"origin": "http://localhost:7860"},  # another origin than the one the page uses
        {"origin": "https://127.0.0.1:7860.evil.example"},
        {"origin": "http://127.0.0.1:7860@evil.example"},
        {"origin": "file://"},
        {"origin": "chrome-extension://abcdefghijklmnop"},
        {"referer": "http://evil.example/?u=http://127.0.0.1:7860/"},
        {"referer": "http://127.0.0.1:7861/"},
        {"origin": "null", "referer": "http://127.0.0.1:7860/"},
    ],
)
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_cross_site_writes_are_refused(client, headers, method):
    r = client.request(method, "/api/settings", json={"autonomy": "suggest"}, headers=headers)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "cross_origin"


def test_a_cross_site_form_post_cannot_open_a_file(client, smoke_rdml):
    # multipart/form-data is a "simple" request: no preflight, so the Origin check is the wall.
    r = client.post(
        "/api/workspaces",
        files={"rdml": (smoke_rdml.name, smoke_rdml.read_bytes(), "application/xml")},
        headers={"origin": "http://evil.example"},
    )
    assert r.status_code == 403
    assert client.get("/api/workspaces").json()["workspaces"] == []


@pytest.mark.parametrize("ctype", ["text/plain", "application/x-www-form-urlencoded", None])
def test_json_sent_as_a_simple_content_type_is_not_read_as_json(client, ctype):
    headers = {**SAME, **({"content-type": ctype} if ctype else {})}
    r = client.put("/api/settings", content=b'{"autonomy":"decide_and_tell"}', headers=headers)
    assert r.status_code == 422
    assert client.get("/api/settings").json()["autonomy"] == "suggest"


# ---- upload cap ------------------------------------------------------------------------------


def test_a_declared_oversize_body_is_refused_before_it_is_read(client, monkeypatch):
    monkeypatch.setattr(security, "MAX_UPLOAD_BYTES", 1024)
    r = client.post(
        "/api/workspaces",
        files={"rdml": ("big.rdml", b"x" * 4096, "application/xml")},
        headers=SAME,
    )
    assert r.status_code == 413 and r.json()["error"]["code"] == "too_large"


@pytest.mark.xfail(
    strict=True,
    reason="RT-UI-004 the upload cap reads only Content-Length: a chunked body has none, "
    "passes the guard, and Starlette spools all of it to disk before any route sees it",
)
def test_a_chunked_oversize_body_is_refused_too(client, monkeypatch):
    monkeypatch.setattr(security, "MAX_UPLOAD_BYTES", 1024)
    boundary = "rtboundary"
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="rdml"; filename="big.rdml"\r\n'
        "Content-Type: application/xml\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()

    def body():  # a generator: httpx sends it chunked, without Content-Length
        yield head
        for _ in range(8):
            yield b"x" * 1024
        yield tail

    r = client.post(
        "/api/workspaces",
        content=body(),
        headers={**SAME, "content-type": f"multipart/form-data; boundary={boundary}"},
    )
    assert r.status_code == 413, r.text


# ---- static files and the built page ---------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/assets/..%2f..%2fsecurity.py",
        "/assets/%2e%2e/%2e%2e/security.py",
        "/assets//etc/passwd",
        "/assets/../../../../etc/passwd",
        "/..%2fsecurity.py",
        "/%2e%2e/server.py",
        "/.%2e/server.py",
        "/assets/.vite/manifest.json",
    ],
)
def test_static_paths_never_leave_the_build(client, path):
    r = client.get(path)
    assert r.status_code in (200, 400, 404)
    assert "root:" not in r.text and "import " not in r.text and "def " not in r.text


@pytest.mark.xfail(
    strict=True,
    reason="RT-UI-005 a NUL byte in a static path (/assets/%00.js, /%00) raises ValueError in "
    "_static_file (Path.resolve/lstat): a 500 and a traceback instead of 404",
)
@pytest.mark.parametrize("path", ["/assets/%00.js", "/%00", "/favicon.svg%00.html"])
def test_a_nul_byte_in_a_static_path_is_not_found(web_ctx, path):
    from fastapi.testclient import TestClient

    from qpilot.web.server import create_app

    with TestClient(create_app(web_ctx), base_url=BASE, raise_server_exceptions=False) as c:
        assert c.get(path).status_code == 404


STATIC = Path(security.__file__).parent / "static"
# Strings in the bundle that look like URLs but are never fetched (XML namespaces, React's
# error-decoder link in production error messages).
NOT_FETCHED = re.compile(
    r"https?://(www\.w3\.org/(2000/svg|1999/xlink|1999/xhtml|XML/1998/namespace|1998/Math/MathML)"
    r"|react\.dev/errors/)"
)


def _built() -> list[Path]:
    if not (STATIC / "index.html").is_file():
        pytest.skip("the page is not built in this checkout")
    return [p for p in STATIC.rglob("*") if p.is_file()]


def test_the_built_page_has_no_inline_script_or_handler():
    html = (STATIC / "index.html").read_text(encoding="utf-8") if _built() else ""
    for tag in re.findall(r"<script\b[^>]*>(.*?)</script>", html, flags=re.S | re.I):
        assert not tag.strip(), "inline <script> in index.html (CSP blocks it; it must not exist)"
    assert not re.search(r"\son[a-z]+\s*=", html, flags=re.I), "inline event handler"
    for ref in re.findall(r'(?:src|href)="([^"]+)"', html):
        assert ref.startswith("/") and not ref.startswith("//"), ref


def test_the_built_page_loads_nothing_from_the_internet():
    offenders = []
    for path in _built():
        if path.suffix not in (".html", ".js", ".css", ".svg", ".json", ".webmanifest"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for url in re.findall(r"""(?:https?:)?//[a-z0-9.-]+\.[a-z]{2,}[^\s"'`)<>]*""", text):
            if url.startswith("//") or not NOT_FETCHED.match(url):
                if not url.startswith("//"):
                    offenders.append(f"{path.name}: {url}")
        for url in re.findall(r"""url\(\s*['"]?([^'")]+)""", text):
            # `url(` in JS string checks (motion: startsWith(`url(`)) is code, not a fetch.
            if not url.startswith(("/", "data:", "#", "`", "$")):
                offenders.append(f"{path.name}: url({url})")
    assert not offenders, offenders[:10]


def test_the_csp_holds():
    directives = dict(d.strip().split(" ", 1) for d in CSP.split(";"))
    assert directives["default-src"] == "'self'"
    assert directives["script-src"] == "'self'"  # no 'unsafe-inline', no 'unsafe-eval'
    assert directives["connect-src"] == "'self'"
    assert directives["object-src"] == "'none'" and directives["base-uri"] == "'none'"
    assert directives["frame-ancestors"] == "'none'"
    assert "http" not in CSP and "*" not in CSP


def test_errors_on_unknown_routes_never_echo_the_path_as_html(client):
    r = client.get("/api/<script>alert(1)</script>")
    assert r.headers["content-type"].startswith("application/json")
    assert "<script>" not in r.text
