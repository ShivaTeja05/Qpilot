"""Red team: the live event stream (``/api/events``) against a real server.

A test client cannot hold sockets open or drop them like a browser, so this module starts
uvicorn on a free port of 127.0.0.1 for its tests (a few seconds).
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from tests.web.conftest import TOKEN

STREAMS = 60


@pytest.fixture
def live(web_ctx) -> Iterator[dict[str, Any]]:
    """The app served by uvicorn on 127.0.0.1 (stopped after the test)."""
    import uvicorn

    from qpilot.web.server import create_app

    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    server = uvicorn.Server(
        uvicorn.Config(create_app(web_ctx), host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        assert time.monotonic() < deadline, "the server did not start"
        time.sleep(0.05)
    yield {"port": port, "base": f"http://127.0.0.1:{port}", "ctx": web_ctx}
    server.should_exit = True
    thread.join(10)


def _open_stream(port: int, token: str | None = TOKEN, host: str | None = None) -> socket.socket:
    """A raw connection that asks for the stream and then never reads (a stalled tab)."""
    sock = socket.create_connection(("127.0.0.1", port))
    lines = ["GET /api/events HTTP/1.1", f"Host: {host or f'127.0.0.1:{port}'}"]
    if token:
        lines.append(f"x-qpilot-token: {token}")
    sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
    return sock


def _subscribers(ctx) -> int:
    return len(ctx.bus._subscribers)


def test_many_stalled_streams_neither_block_the_api_nor_leak(live):
    ctx, port = live["ctx"], live["port"]
    socks = [_open_stream(port) for _ in range(STREAMS)]
    try:
        deadline = time.monotonic() + 10
        while _subscribers(ctx) < STREAMS and time.monotonic() < deadline:
            time.sleep(0.05)
        assert _subscribers(ctx) == STREAMS
        for _ in range(1500):  # nobody reads: each queue fills (256) and drops the rest
            ctx.bus.publish({"type": "job.updated", "key": None, "pad": "x" * 2000})
        # A stream that blocked the server would make this time out; under a loaded machine an
        # answer can take seconds, so only "answers at all" is asserted.
        r = httpx.get(live["base"] + "/api/settings", headers={"x-qpilot-token": TOKEN}, timeout=20)
        assert r.status_code == 200
    finally:
        for sock in socks:
            sock.close()
    deadline = time.monotonic() + 20
    while _subscribers(ctx) and time.monotonic() < deadline:
        ctx.bus.publish({"type": "ping"})  # a write to a closed socket ends its stream
        time.sleep(0.2)
    assert _subscribers(ctx) == 0, "closed streams are still subscribed"


@pytest.mark.parametrize(
    "token,host",
    [(None, None), ("wrong", None), (TOKEN, "evil.example"), (TOKEN, "localhost.")],
)
def test_the_stream_refuses_strangers_before_subscribing(live, token, host):
    ctx, port = live["ctx"], live["port"]
    sock = _open_stream(port, token, host)
    try:
        sock.settimeout(10)
        head = sock.recv(200).decode("latin-1")
    finally:
        sock.close()
    assert head.split(" ")[1] in ("400", "401")
    assert _subscribers(ctx) == 0


def test_events_carry_no_job_result(live):
    ctx = live["ctx"]
    seen: list[str] = []
    with httpx.stream(
        "GET", live["base"] + "/api/events", headers={"x-qpilot-token": TOKEN}, timeout=20
    ) as r:
        lines = r.iter_lines()
        for line in lines:
            if line.startswith("data:") and '"hello"' in line:
                break
        job = ctx.jobs.submit("t", lambda p: {"secret": "result-body"}, title="t", key=None)
        deadline = time.monotonic() + 10
        for line in lines:
            seen.append(line)
            if '"done"' in line or time.monotonic() > deadline:
                break
    assert any(job.id in line for line in seen)
    assert not any("result-body" in line for line in seen)
