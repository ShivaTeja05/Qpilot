"""A model server that trickles its reply can never hold a qPilot call open."""

import socket
import threading
import time

import pytest

from qpilot.ai.client import ModelUnavailable, OpenAICompatibleBackend
from qpilot.ai.config import ModelConfig


def _trickling_server(stop: threading.Event) -> int:
    """A server on 127.0.0.1 that sends its status line one byte every 0.3 s, forever."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(5)

    def serve() -> None:
        try:
            conn, _ = server.accept()
        except OSError:
            return
        with conn:
            conn.recv(65536)
            for byte in b"HTTP/1.1 200 OK\r\nX-Slow: " + b"a" * 10_000:
                if stop.is_set():
                    return
                try:
                    conn.sendall(bytes([byte]))
                except OSError:
                    return
                time.sleep(0.3)
        server.close()

    threading.Thread(target=serve, daemon=True).start()
    return server.getsockname()[1]


def test_a_trickling_status_line_ends_within_twice_the_timeout():
    pytest.importorskip("httpx")
    stop = threading.Event()
    port = _trickling_server(stop)
    config = ModelConfig(
        provider="openai_compatible", endpoint=f"http://127.0.0.1:{port}/v1", model="m"
    )
    backend = OpenAICompatibleBackend(config, timeout=1.0)
    start = time.monotonic()
    try:
        with pytest.raises(ModelUnavailable, match="endpoint call failed"):
            backend.complete("s", [{"role": "user", "content": "hi"}], 3, 0.0)
    finally:
        stop.set()
    assert time.monotonic() - start < 3.0
