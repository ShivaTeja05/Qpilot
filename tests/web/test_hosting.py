"""Hosted mode (QPILOT_HOSTED=1): a public sandbox; local mode stays exactly as it was."""

from fastapi.testclient import TestClient

from qpilot.web.context import make_context
from qpilot.web.security import Hosting, upload_cap
from qpilot.web.server import create_app

SPACE = "jeevithg-qpilot.hf.space"
ENV = {
    "QPILOT_HOSTED": "1",
    "QPILOT_ALLOWED_HOSTS": SPACE,
    "QPILOT_ALLOWED_ORIGINS": "https://qpilot-demo.vercel.app",
    "QPILOT_FRAME_ANCESTORS": "https://huggingface.co",
}


def test_local_by_default():
    h = Hosting.from_env({})
    assert not h.hosted and h.hosts == {"127.0.0.1", "localhost"} and not h.origins
    assert dict(h.headers())[b"x-frame-options"] == b"DENY"


def hosted_client(monkeypatch, web_store):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    ctx = make_context(web_store, token="unused", watch=False)
    return ctx, TestClient(create_app(ctx), base_url=f"https://{SPACE}")


def test_hosted_needs_no_key_and_says_so(monkeypatch, web_store):
    ctx, c = hosted_client(monkeypatch, web_store)
    with c:
        r = c.get("/api/system")
        assert r.status_code == 200 and r.json()["hosted"] is True
    ctx.close()


def test_hosted_still_refuses_other_hosts_and_sites(monkeypatch, web_store):
    ctx, c = hosted_client(monkeypatch, web_store)
    with c:
        assert c.get("/api/system", headers={"host": "evil.example"}).status_code == 400
        bad = c.put("/api/settings", json={}, headers={"origin": "https://evil.example"})
        assert bad.status_code == 403
        ok = c.put(
            "/api/settings",
            json={"autonomy": "suggest"},
            headers={"origin": "https://qpilot-demo.vercel.app"},
        )
        assert ok.status_code != 403
    ctx.close()


def test_hosted_may_be_framed_by_hugging_face_only(monkeypatch, web_store):
    ctx, c = hosted_client(monkeypatch, web_store)
    with c:
        r = c.get("/")
        assert "frame-ancestors https://huggingface.co" in r.headers["content-security-policy"]
        assert "x-frame-options" not in r.headers
    ctx.close()


def test_upload_cap_can_only_shrink(monkeypatch):
    monkeypatch.setenv("QPILOT_MAX_UPLOAD_MB", "25")
    assert upload_cap() == 25 * 1024 * 1024
    monkeypatch.setenv("QPILOT_MAX_UPLOAD_MB", "5000")
    assert upload_cap() == 200 * 1024 * 1024
