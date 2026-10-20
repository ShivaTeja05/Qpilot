"""Launch hardening of the old pages, checked on the one server (tests/web/PARITY.md §1).

The old Gradio pages (``qpilot app``, ``qpilot studio``) and ``qsim app`` each hardened their own
launch: this machine only, no telemetry, uploads capped, no tracebacks, the store never served,
the API key never shown. These tests check the same properties on ``qpilot.web``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest_socket import disable_socket, enable_socket

from qpilot.ai.profile import Profile
from qpilot.ai.suggest_only import load_profile_or_default
from qpilot.core.store import StudyStore
from qpilot.studio_service import Studio
from qpilot.web import security
from qpilot.web.context import make_context
from qpilot.web.routers import workspaces
from qpilot.web.server import create_app
from tests.web.conftest import BASE, TOKEN, wait_job

MB = 1024 * 1024
WEB = Path(security.__file__).parent


def keyed(app, **kwargs) -> TestClient:
    client = TestClient(app, base_url=BASE, **kwargs)
    client.headers["x-qpilot-token"] = TOKEN
    client.headers["origin"] = BASE
    return client


# ---- this machine only (P16) -----------------------------------------------------------------


def test_main_serves_this_machine_only(monkeypatch, tmp_studies_dir, capsys):
    import uvicorn

    from qpilot.web import server

    seen: dict = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **config: seen.update(app=app, config=config))
    monkeypatch.setattr(server.webbrowser, "open", lambda url: seen.update(opened=url))
    server.main(port=7999, open_browser=False, store=StudyStore(tmp_studies_dir))
    try:
        config = seen["config"]
        assert config["host"] == "127.0.0.1" and config["port"] == 7999
        assert config["access_log"] is False and config["server_header"] is False
        assert "opened" not in seen
        out = capsys.readouterr().out
        assert "http://127.0.0.1:7999/?token=" in out
        assert "research use only" in out
    finally:
        seen["app"].state.ctx.close()
    source = "\n".join(p.read_text(encoding="utf-8") for p in WEB.rglob("*.py"))
    assert "0.0.0.0" not in source, "nothing binds every interface"


# ---- no network needed (P18) -----------------------------------------------------------------


def test_open_and_propose_with_the_network_switched_off(sclient, mini_rdml):
    disable_socket()
    try:
        with mini_rdml.open("rb") as fh:
            r = sclient.post("/api/workspaces", files={"rdml": ("mini.rdml", fh, "text/xml")})
        assert r.status_code == 202, r.text
        opened = wait_job(sclient, r.json()["job"])
        assert opened["status"] == "done", opened
        sid = opened["result"]["key"]
        r = sclient.post(f"/api/sessions/{sid}/propose/design")
        assert r.status_code == 202, r.text
        proposed = wait_job(sclient, r.json()["job"])
        assert proposed["status"] == "done", proposed
        assert proposed["result"]["proposed"], "the rules propose alone, offline"
    finally:
        enable_socket()


# ---- the store is never served (P19) ---------------------------------------------------------


def test_store_files_are_never_served(sclient, web_store, opened):
    target = web_store.find_session(opened) / "quarantine.json"  # the file's own names
    secret = target.read_text(encoding="utf-8")[:200]
    rel = target.relative_to(web_store.root).as_posix()
    absolute = target.resolve().as_posix()
    paths = [
        f"/{rel}",
        f"/assets/../{rel}",
        f"/assets/%2e%2e/%2e%2e/{rel}",
        f"/{absolute}",
        f"/assets/{absolute}",
        f"/file={absolute}",
        f"/gradio_api/file={absolute}",
        f"/api/files/{rel}",
        f"/api/downloads/{rel}",
        f"/%2e%2e/%2e%2e{absolute}",
    ]
    for path in paths:
        r = sclient.get(path)
        assert secret not in r.text, path


# ---- uploads are capped while they stream (P20) ----------------------------------------------


def _upload(app, headers: dict[str, str], chunks: list[bytes]) -> tuple[int, int]:
    """Drive one POST /api/workspaces through the ASGI app; (status, body bytes it pulled)."""
    pulled = 0
    sent: list[dict] = []
    pending = iter(chunks)

    async def receive() -> dict:
        nonlocal pulled
        chunk = next(pending, None)
        if chunk is None:
            return {"type": "http.request", "body": b"", "more_body": False}
        pulled += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": True}

    async def send(message: dict) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/workspaces",
        "raw_path": b"/api/workspaces",
        "query_string": b"",
        "root_path": "",
        "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 7860),
    }
    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    return start["status"], pulled


def _multipart(total: int, chunk: int = 256 * 1024) -> tuple[dict[str, str], list[bytes]]:
    head = (
        b'--qpb\r\nContent-Disposition: form-data; name="rdml"; filename="big.rdml"\r\n'
        b"Content-Type: text/xml\r\n\r\n"
    )
    body = [head] + [b"x" * chunk for _ in range(total // chunk)] + [b"\r\n--qpb--\r\n"]
    headers = {
        "host": "127.0.0.1:7860",
        "origin": BASE,
        "x-qpilot-token": TOKEN,
        "content-type": "multipart/form-data; boundary=qpb",
    }
    return headers, body


@pytest.fixture
def small_caps(monkeypatch):
    monkeypatch.setattr(security, "MAX_UPLOAD_BYTES", 1 * MB)
    monkeypatch.setattr(workspaces, "MAX_RDML_BYTES", 1 * MB)


def test_an_upload_over_the_cap_is_refused(web_ctx, small_caps):
    headers, body = _multipart(8 * MB)
    headers["content-length"] = str(sum(map(len, body)))
    status, pulled = _upload(create_app(web_ctx), headers, body)
    assert status == 413 and pulled == 0, "refused before reading the body"


@pytest.mark.xfail(
    strict=True,
    reason="PARITY-1 (api): the Guard caps by Content-Length only; a chunked body is read to "
    "the end before the 413 (old Gradio and qsim refused while it streamed)",
)
def test_a_chunked_upload_over_the_cap_is_refused_while_it_streams(web_ctx, small_caps):
    headers, body = _multipart(8 * MB)  # no Content-Length: Transfer-Encoding chunked
    status, pulled = _upload(create_app(web_ctx), headers, body)
    assert status == 413
    assert pulled <= 2 * MB, f"read {pulled // MB} MB of an 8 MB body over a 1 MB cap"


# ---- errors are sentences, never a traceback (P21) -------------------------------------------


@pytest.fixture
def broken_route(monkeypatch):
    from qpilot.web import views

    def boom(*_args, **_kwargs):
        raise RuntimeError("Traceback: /Users/someone/secret/studies broke")

    monkeypatch.setattr(views, "workspaces", boom)


def test_an_unexpected_error_leaks_no_traceback(web_ctx, broken_route):
    with keyed(create_app(web_ctx), raise_server_exceptions=False) as client:
        r = client.get("/api/workspaces")
    assert r.status_code == 500
    assert "secret" not in r.text and "Traceback" not in r.text


@pytest.mark.xfail(
    strict=True,
    reason="PARITY-2 (api): an unexpected error is Starlette's plain-text 500, outside the "
    "error shape and without the security headers",
)
def test_an_unexpected_error_is_a_sentence_with_the_security_headers(web_ctx, broken_route):
    with keyed(create_app(web_ctx), raise_server_exceptions=False) as client:
        r = client.get("/api/workspaces")
    assert r.status_code == 500 and r.json()["error"]["message"]
    assert r.headers["content-security-policy"] == security.CSP
    assert r.headers["cache-control"] == "no-store"


# ---- the model: chosen by the environment only, the key never shown (P22) --------------------


def _request_body_fields(openapi: dict) -> set[str]:
    schemas = openapi.get("components", {}).get("schemas", {})

    def fields(schema: dict, seen: set[str]) -> set[str]:
        if "$ref" in schema:
            name = schema["$ref"].rsplit("/", 1)[-1]
            if name in seen:
                return set()
            return fields(schemas[name], seen | {name})
        found = set(schema.get("properties", {}))
        for value in schema.get("properties", {}).values():
            found |= fields(value, seen)
        for key in ("items", "additionalProperties"):
            if isinstance(schema.get(key), dict):
                found |= fields(schema[key], seen)
        for key in ("anyOf", "oneOf", "allOf"):
            for part in schema.get(key, []):
                found |= fields(part, seen)
        return found

    names: set[str] = set()
    for operations in openapi["paths"].values():
        for operation in operations.values():
            for media in operation.get("requestBody", {}).get("content", {}).values():
                names |= fields(media.get("schema", {}), set())
    return names


def test_the_page_cannot_choose_a_model_endpoint(client):
    before = client.get("/api/model").json()
    r = client.put(
        "/api/settings",
        json={
            "autonomy": "suggest",
            "provider": "openai_compatible",
            "endpoint": "http://evil.example/v1",
            "model": "evil",
            "api_key": "stolen",
        },
        headers={"origin": BASE},
    )
    assert r.status_code == 200 and r.json() == {"autonomy": "suggest"}
    after = client.get("/api/model").json()
    assert (after["provider"], after["model"]) == (before["provider"], before["model"])
    fields = _request_body_fields(client.get("/api/openapi.json").json())
    assert not fields & {"endpoint", "provider", "api_key", "key", "model_endpoint"}, fields


@pytest.fixture
def anthropic_env(monkeypatch):
    """Anthropic configured from the environment; no call can leave the machine."""
    from qpilot.ai.client import AnthropicBackend, ModelUnavailable

    def offline(*_args, **_kwargs):
        raise ModelUnavailable("no network in this test")

    monkeypatch.setattr(AnthropicBackend, "complete", offline)
    monkeypatch.setenv("QPILOT_MODEL_PROVIDER", "anthropic")
    monkeypatch.setenv("QPILOT_MODEL_NAME", "claude-test")
    monkeypatch.delenv("QPILOT_MODEL_ENDPOINT", raising=False)
    return monkeypatch


def _served(tmp_studies_dir) -> tuple:
    store = StudyStore(tmp_studies_dir)
    ctx = make_context(store, Studio(store), token=TOKEN, watch=False)
    return ctx, keyed(create_app(ctx))


def test_the_api_key_is_never_shown(anthropic_env, tmp_studies_dir):
    secret = "sk-ant-test-0123456789-SECRET"
    anthropic_env.setenv("QPILOT_API_KEY", secret)
    ctx, client = _served(tmp_studies_dir)
    try:
        with client:
            disable_socket()  # after the client's event loop exists: no new socket from here
            try:
                paths = ("/api/system", "/api/model", "/api/settings", "/api/openapi.json")
                bodies = [client.get(p).text for p in paths]
            finally:
                enable_socket()
    finally:
        ctx.close()
    assert all(secret not in body for body in bodies)
    assert all(secret[:16] not in body for body in bodies), "not even a prefix"


def test_a_missing_key_is_reported_by_name(anthropic_env, tmp_studies_dir):
    anthropic_env.delenv("QPILOT_API_KEY", raising=False)
    ctx, client = _served(tmp_studies_dir)
    try:
        with client:
            model = client.get("/api/model").json()
    finally:
        ctx.close()
    assert not model["available"] and "QPILOT_API_KEY" in model["reason"]


# ---- a broken profile does not stop the server (P23) -----------------------------------------


def test_a_broken_profile_does_not_stop_the_server(monkeypatch, tmp_path, tmp_studies_dir):
    broken = tmp_path / "qpilot_profile.yaml"
    broken.write_text("tone: [unclosed\n  - : :\n", encoding="utf-8")
    monkeypatch.setenv("QPILOT_PROFILE", str(broken))
    assert load_profile_or_default() == Profile()
    ctx, client = _served(tmp_studies_dir)
    try:
        with client:
            assert client.get("/api/system").status_code == 200
            assert client.get("/api/workspaces").status_code == 200
    finally:
        ctx.close()
