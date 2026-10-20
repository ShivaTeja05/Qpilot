"""The one server's guard: this machine, this page, this launch (qpilot/web/security.py)."""

import pytest

from qpilot.web.security import CSP


def test_api_needs_the_launch_key(raw_client):
    r = raw_client.get("/api/system")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "no_token"


def test_the_printed_link_sets_the_cookie_and_drops_the_key_from_the_address(raw_client):
    r = raw_client.get("/?token=test-token", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert raw_client.get("/api/system").status_code == 200  # the cookie now carries the key


def test_a_link_from_another_launch_is_refused(raw_client):
    assert raw_client.get("/?token=old", follow_redirects=False).status_code == 403


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1.evil.example", "192.168.1.5"])
def test_other_host_names_are_refused(client, host):
    assert client.get("/api/system", headers={"host": host}).status_code == 400


def test_localhost_is_accepted(client):
    assert client.get("/api/system", headers={"host": "localhost:7860"}).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {"origin": "http://evil.example"},
        {"origin": "null"},
        {"origin": "http://127.0.0.1:9999"},
        {"referer": "http://evil.example/page"},
    ],
)
def test_writes_from_another_site_are_refused(client, headers):
    r = client.put("/api/settings", json={"autonomy": "suggest"}, headers=headers)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "cross_origin"


def test_same_origin_writes_pass(client):
    r = client.put(
        "/api/settings",
        json={"autonomy": "decide_and_tell"},
        headers={"origin": "http://127.0.0.1:7860"},
    )
    assert r.status_code == 200 and r.json()["autonomy"] == "decide_and_tell"


def test_every_answer_carries_the_security_headers(client):
    for path in ("/", "/api/system", "/api/nope"):
        r = client.get(path)
        assert r.headers["content-security-policy"] == CSP
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
    assert client.get("/api/system").headers["cache-control"] == "no-store"


def test_unknown_api_routes_are_json_errors(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("path", ["/../pyproject.toml", "/.env", "/assets/../../security.py"])
def test_static_files_never_leave_the_build(client, path):
    r = client.get(path)
    assert "fastapi" not in r.text and "TOKEN" not in r.text


def test_no_third_party_docs_pages(client):
    assert client.get("/docs").headers["content-type"].startswith("text/html")  # the page itself
    assert "swagger" not in client.get("/docs").text.lower()
    assert client.get("/api/openapi.json").status_code == 200


def test_a_chunked_upload_is_capped_as_it_arrives(client, monkeypatch):
    from qpilot.web import security

    monkeypatch.setattr(security, "MAX_UPLOAD_BYTES", 64 * 1024)

    def body():
        for _ in range(16):
            yield b"x" * 8192

    r = client.post(
        "/api/workspaces",
        content=body(),
        headers={
            "content-type": "multipart/form-data; boundary=b",
            "origin": "http://127.0.0.1:7860",
        },
    )
    assert r.status_code == 413 and r.json()["error"]["code"] == "too_large"
