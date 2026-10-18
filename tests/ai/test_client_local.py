"""A call to a model on this machine goes straight to it: never through an HTTP proxy."""

import socket
import threading

import pytest

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


def _backend(endpoint):
    config = ModelConfig(provider="openai_compatible", endpoint=endpoint, model="m")
    return OpenAICompatibleBackend(config, timeout=2)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_a_local_endpoint_never_goes_through_an_environment_proxy(proxy, host):
    backend = _backend(f"http://{host}:{_closed_port()}/v1")
    with pytest.raises(ModelUnavailable):
        backend.complete("s", [{"role": "user", "content": "Patient07_LPS"}], 5, 0)
    assert proxy.received == []  # the request never reached the proxy


def test_a_remote_endpoint_still_honours_the_proxy_settings(monkeypatch):
    seen = {}

    def post(url, **kwargs):
        seen.update(kwargs)
        raise OSError("offline")

    import httpx

    monkeypatch.setattr(httpx, "post", post)
    for endpoint, trust in (("https://llm.example.com/v1", True), ("http://127.0.0.1:1/v1", False)):
        with pytest.raises(ModelUnavailable):
            _backend(endpoint).complete("s", [{"role": "user", "content": "x"}], 5, 0)
        assert seen["trust_env"] is trust


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

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": content}}]}

    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: Response())
    backend = _backend("http://127.0.0.1:1/v1")
    assert backend.complete("s", [{"role": "user", "content": "x"}], 5, 0) == text


def test_the_client_always_returns_readable_text():
    client = ModelClient(MockBackend([["not", "text"], "lone \ud800 surrogate"]))
    assert client.complete("s", [{"role": "user", "content": "x"}]) == ""
    reply = client.complete("s", [{"role": "user", "content": "x"}])
    assert reply == "lone ? surrogate"
    reply.encode("utf-8")
