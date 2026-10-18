"""A call to a model on this machine goes straight to it: never through an HTTP proxy.

Every call is bounded in total, however slowly the server sends its reply.
"""

import contextlib
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from qpilot.ai import client as client_module
from qpilot.ai.client import MockBackend, ModelClient, ModelUnavailable, OpenAICompatibleBackend
from qpilot.ai.config import ModelConfig


class _Listener:
    """A TCP socket standing in for a site proxy; it records every connection it gets."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.received: list[bytes] = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                continue
            with conn:
                conn.settimeout(1)
                try:
                    self.received.append(conn.recv(65536))
                except OSError:
                    self.received.append(b"")

    def close(self):
        self.stop.set()
        self.thread.join(2)
        self.sock.close()


def _closed_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def proxy(monkeypatch):
    listener = _Listener()
    url = f"http://127.0.0.1:{listener.port}"
    for var in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(var, raising=False)
    for var in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(var, url)
    yield listener
    listener.close()


def _backend(endpoint, timeout=2):
    config = ModelConfig(provider="openai_compatible", endpoint=endpoint, model="m")
    return OpenAICompatibleBackend(config, timeout=timeout)


class _Response:
    """What ``httpx.stream`` yields: a status check and the body in chunks."""

    def __init__(self, body: bytes, size: int):
        self.body = body
        self.size = size

    def raise_for_status(self):
        return None

    def iter_bytes(self):
        for start in range(0, len(self.body), self.size):
            yield self.body[start : start + self.size]


def _stream(seen, reply=None, error=None, size=1 << 16):
    """A stand-in for ``httpx.stream`` that records its arguments; no network."""

    @contextlib.contextmanager
    def stream(method, url, **kwargs):
        seen.update(kwargs, method=method, url=url)
        if error is not None:
            raise error
        yield _Response(json.dumps(reply).encode("utf-8"), size)

    return stream


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_a_local_endpoint_never_goes_through_an_environment_proxy(proxy, host):
    backend = _backend(f"http://{host}:{_closed_port()}/v1")
    with pytest.raises(ModelUnavailable):
        backend.complete("s", [{"role": "user", "content": "Patient07_LPS"}], 5, 0)
    assert proxy.received == []  # the request never reached the proxy


def test_a_remote_endpoint_still_honours_the_proxy_settings(monkeypatch):
    import httpx

    seen = {}
    monkeypatch.setattr(httpx, "stream", _stream(seen, error=OSError("offline")))
    for endpoint, trust in (("https://llm.example.com/v1", True), ("http://127.0.0.1:1/v1", False)):
        with pytest.raises(ModelUnavailable):
            _backend(endpoint).complete("s", [{"role": "user", "content": "x"}], 5, 0)
        assert seen["trust_env"] is trust and seen["method"] == "POST"


@pytest.mark.parametrize(
    ("content", "text"),
    [
        ([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}], "ab"),
        (None, ""),
        (42, ""),
        ({"text": "x"}, ""),
    ],
)
def test_a_reply_that_is_not_text_comes_back_as_text(monkeypatch, content, text):
    import httpx

    reply = {"choices": [{"message": {"content": content}}]}
    monkeypatch.setattr(httpx, "stream", _stream({}, reply, size=7))  # a body in many chunks
    backend = _backend("http://127.0.0.1:1/v1")
    assert backend.complete("s", [{"role": "user", "content": "x"}], 5, 0) == text


class _Trickle(BaseHTTPRequestHandler):
    """A server (not a model) that sends a valid reply four bytes at a time."""

    body = json.dumps({"choices": [{"message": {"content": '{"fields": []}'}}]}).encode()

    def log_message(self, *args):
        return None

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        try:
            for start in range(0, len(self.body), 4):
                self.wfile.write(self.body[start : start + 4])
                self.wfile.flush()
                time.sleep(0.2)
        except OSError:
            return  # the client gave up


def test_a_server_that_trickles_its_reply_cannot_hold_a_call_open():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Trickle)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        backend = _backend(f"http://127.0.0.1:{server.server_address[1]}/v1", timeout=0.5)
        start = time.monotonic()
        with pytest.raises(ModelUnavailable, match="ReadTimeout$"):
            backend.complete("s", [{"role": "user", "content": "x"}], 5, 0)
        # every read comes well within the timeout, but the whole reply would take about 3 s
        assert time.monotonic() - start < 2 * 0.5 + 0.5
    finally:
        server.shutdown()
        server.server_close()


def test_a_reply_larger_than_the_cap_is_refused(monkeypatch):
    import httpx

    reply = {"choices": [{"message": {"content": "x" * 200}}]}
    monkeypatch.setattr(httpx, "stream", _stream({}, reply, size=16))
    monkeypatch.setattr(client_module, "MAX_REPLY_BYTES", 100)
    with pytest.raises(ModelUnavailable, match="ValueError$"):
        _backend("http://127.0.0.1:1/v1").complete("s", [{"role": "user", "content": "x"}], 5, 0)


def test_the_client_always_returns_readable_text():
    client = ModelClient(MockBackend([["not", "text"], "lone \ud800 surrogate"]))
    assert client.complete("s", [{"role": "user", "content": "x"}]) == ""
    reply = client.complete("s", [{"role": "user", "content": "x"}])
    assert reply == "lone ? surrogate"
    reply.encode("utf-8")
