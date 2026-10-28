"""One write, one re-read: ETags and 304s, soft waits, tab origins, and the watcher's absorb.

The page re-reads a workspace after each decision; these tests pin what makes that cheap and
single: an unchanged view answers 304 with no body, a view still being prepared answers 202 (no
failed load in the browser's console), an event names the tab whose request caused it, and a
write this process told is not told again by the store watcher.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qpilot.web.cache import ApiCache, Memo, etag_of
from qpilot.web.context import api_error
from qpilot.web.events import EventBus, StoreWatcher

SID = "ab" * 32


def _mini(bus: EventBus) -> FastAPI:
    """A tiny app with the same middleware and error shape as the server's."""
    from fastapi import HTTPException, Request
    from fastapi.responses import JSONResponse

    app = FastAPI()
    state = {"value": 1}

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse({"error": {"details": {}, **exc.detail}}, status_code=exc.status_code)

    @app.get("/api/thing")
    def thing():
        return {"value": state["value"], "big": "x" * 10_000}

    @app.post("/api/thing")
    def write():
        state["value"] += 1
        bus.publish({"type": "study.changed", "key": SID[:12], "source": "page"})
        return {"ok": True}

    @app.get("/api/slow")
    def slow():
        raise api_error(409, "loading", "Still loading.", job={"id": "j1"})

    @app.get("/api/stale")
    def stale():
        raise api_error(409, "stale", "Changed since you read it.")

    @app.get("/api/warming")
    def warming():
        raise api_error(503, "warming", "Reading the file.")

    app.add_middleware(ApiCache, bus=bus)
    return app


@pytest.fixture
def mini():
    bus = EventBus()
    seen: list[dict] = []
    bus.on_publish(seen.append)
    with TestClient(_mini(bus)) as c:
        yield c, bus, seen


def test_an_unchanged_view_answers_304_without_a_body(mini):
    c, _, _ = mini
    first = c.get("/api/thing")
    assert first.status_code == 200
    tag = first.headers["etag"]
    assert tag == etag_of(first.content)
    again = c.get("/api/thing", headers={"if-none-match": tag})
    assert again.status_code == 304
    assert again.content == b""
    assert again.headers["etag"] == tag


def test_a_changed_view_answers_its_new_bytes(mini):
    c, _, _ = mini
    tag = c.get("/api/thing").headers["etag"]
    c.post("/api/thing")
    after = c.get("/api/thing", headers={"if-none-match": tag})
    assert after.status_code == 200
    assert after.json()["value"] == 2
    assert after.headers["etag"] != tag


def test_the_bytes_of_an_answer_are_the_routes_own(mini):
    c, _, _ = mini
    body = c.get("/api/thing").content
    assert json.loads(body) == {"value": 1, "big": "x" * 10_000}


def test_a_view_being_prepared_is_a_soft_wait_only_when_asked(mini):
    c, _, _ = mini
    plain = c.get("/api/slow")
    assert plain.status_code == 409 and plain.json()["error"]["code"] == "loading"
    soft = c.get("/api/slow", headers={"prefer": "respond-async"})
    assert soft.status_code == 202
    assert soft.headers["x-qpilot-status"] == "409"
    assert soft.json() == plain.json()
    warm = c.get("/api/warming", headers={"prefer": "respond-async"})
    assert warm.status_code == 202 and warm.headers["x-qpilot-status"] == "503"
    # A real conflict stays a conflict.
    stale = c.get("/api/stale", headers={"prefer": "respond-async"})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale"


def test_events_name_the_tab_whose_request_caused_them(mini):
    c, _, seen = mini
    c.post("/api/thing", headers={"x-qpilot-tab": "tab-1"})
    c.post("/api/thing")
    c.post("/api/thing", headers={"x-qpilot-tab": "not a tab id!"})
    assert [e.get("origin") for e in seen] == ["tab-1", None, None]


def test_answers_carry_the_store_sequence(mini):
    c, bus, _ = mini
    assert c.get("/api/thing").headers["x-qpilot-store-seq"] == "0"
    c.post("/api/thing")
    assert bus.store_seq == 1
    assert c.get("/api/thing").headers["x-qpilot-store-seq"] == "1"
    bus.publish({"type": "job.updated", "key": None})
    assert bus.store_seq == 1  # job progress is not a store change


def _session(root: Path) -> Path:
    folder = root / "sessions" / SID
    folder.mkdir(parents=True)
    (folder / "proposals.jsonl").write_text("{}\n")
    return folder


def test_the_watcher_does_not_tell_a_write_this_process_told(tmp_path):
    root = tmp_path / "studies"
    folder = _session(root)
    bus = EventBus()
    watcher = StoreWatcher(root, bus)
    watcher.scan(publish=False)
    with (folder / "proposals.jsonl").open("a") as fh:
        fh.write('{"a": 1}\n')
    bus.publish({"type": "proposals.changed", "key": SID[:12], "source": "page"})
    assert watcher.scan(publish=False) == []
    # Another process writes after that: told.
    with (folder / "proposals.jsonl").open("a") as fh:
        fh.write('{"b": 2}\n')
    assert [e["type"] for e in watcher.scan(publish=False)] == ["proposals.changed"]


def test_the_watcher_still_tells_a_disk_event_and_other_workspaces(tmp_path):
    root = tmp_path / "studies"
    folder = _session(root)
    other = root / "sessions" / ("cd" * 32)
    other.mkdir(parents=True)
    (other / "decisions.jsonl").write_text("")
    bus = EventBus()
    watcher = StoreWatcher(root, bus)
    watcher.scan(publish=False)
    (folder / "proposals.jsonl").write_text("{}\n{}\n")
    (other / "decisions.jsonl").write_text("{}\n")
    # An event from the watcher itself, or about another key, absorbs nothing here.
    bus.publish({"type": "proposals.changed", "key": SID[:12], "source": "disk"})
    bus.publish({"type": "study.changed", "key": "ef" * 6, "source": "page"})
    keys = sorted(e["key"] for e in watcher.scan(publish=False))
    assert keys == ["abababababab", "cdcdcdcdcdcd"]


def test_hello_carries_the_store_sequence():
    import asyncio

    bus = EventBus()
    bus.publish({"type": "study.changed", "key": "ab" * 6})

    async def first_two() -> list[str]:
        out = []
        stream = bus.stream(lambda: False)
        async for chunk in stream:
            out.append(chunk)
            if len(out) == 2:
                break
        await stream.aclose()
        return out

    chunks = asyncio.run(first_two())
    hello = json.loads(chunks[1].split("data: ", 1)[1])
    assert hello == {"type": "hello", "store_seq": 1, "boot": bus.boot}


def test_memo_computes_once_per_key_and_stays_bounded():
    m = Memo(size=2)
    calls: list[str] = []

    def compute(k: str):
        def run():
            calls.append(k)
            return k.upper()

        return run

    assert m.get("a", compute("a")) == "A"
    assert m.get("a", compute("a")) == "A"
    m.get("b", compute("b"))
    m.get("c", compute("c"))  # "a" is the least recent: forgotten
    m.get("a", compute("a"))
    assert calls == ["a", "b", "c", "a"]


def test_a_failed_compute_is_not_kept():
    m = Memo()

    def boom():
        raise ValueError("no")

    with pytest.raises(ValueError):
        m.get("k", boom)
    assert m.get("k", lambda: 3) == 3


def test_the_server_tags_its_views_and_compresses_large_ones(client):
    first = client.get("/api/workspaces")
    assert first.status_code == 200 and first.headers.get("etag")
    again = client.get("/api/workspaces", headers={"if-none-match": first.headers["etag"]})
    assert again.status_code == 304
    big = client.get("/api/openapi.json", headers={"accept-encoding": "gzip"})
    assert big.status_code == 200 and big.headers.get("content-encoding") == "gzip"
    assert big.json()["openapi"]  # the client reads the same JSON
