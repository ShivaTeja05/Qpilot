"""The views a person opens next are prepared in the background (perf, excellence round).

``warm.prepare_views`` reads a study's views through the API itself (GET only), follows a view
whose own job is still preparing it, and never writes. ``follow_new_studies`` prepares a study
as soon as an event says it exists.
"""

from __future__ import annotations

import json
import time

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from qpilot.core.store import StudyStore
from qpilot.web import warm
from qpilot.web.cache import ACTIVITY
from qpilot.web.server import create_app
from tests.web.conftest import wait_job


@pytest.fixture
def study(web_store: StudyStore, fixture_result, fixture_cards) -> str:
    web_store.put(fixture_result, fixture_cards)
    return fixture_result.study_id


def _files(store: StudyStore) -> dict[str, bytes]:
    return {
        str(p.relative_to(store.root)): p.read_bytes()
        for p in sorted(store.root.rglob("*"))
        if p.is_file() and p.name != ".lock"
    }


def test_prepare_reads_every_view_once_and_writes_nothing(web_ctx, web_store, study):
    app = create_app(web_ctx)
    asked: list[str] = []
    real = warm._asgi_get

    def spy(app_, token, path):
        asked.append(path)
        return real(app_, token, path)

    before = _files(web_store)
    warm.forget_prepared(web_ctx)
    try:
        warm._asgi_get = spy
        job = warm.prepare_views(web_ctx, app, [study, study])
        assert job is not None
        view = wait_job_obj(web_ctx, job)
    finally:
        warm._asgi_get = real
    assert view.status == "done", view.error
    views = [p.split(f"/api/studies/{study}/", 1)[1] for p in asked if study in p]
    assert [p for p in asked if study not in p] == [p for p, _ in warm.GLOBAL_VIEWS]
    # Every view once, in the order a person opens them (a view still loading is read again).
    assert list(dict.fromkeys(views)) == [v for v, _ in warm.STUDY_VIEWS]
    assert _files(web_store) == before  # read only
    # Prepared once per process: asking again does nothing.
    assert warm.prepare_views(web_ctx, app, [study]) is None


def wait_job_obj(ctx, job, timeout=120.0):
    deadline = time.monotonic() + timeout
    while job.status in ("queued", "running"):
        assert time.monotonic() < deadline, "prepare did not finish"
        time.sleep(0.05)
    return job


def test_a_view_still_loading_is_followed_until_its_job_is_done(web_ctx):
    """409 loading with a job: wait for the job, then read again (as the page does)."""
    gate = {"n": 0}

    def slow(progress):
        time.sleep(0.2)
        return {}

    job = web_ctx.jobs.submit("gate.run", slow, title="t", key="abcabcabcabc")
    app = FastAPI()

    @app.get("/api/studies/{study}/gate")
    def view(study: str):
        gate["n"] += 1
        if job.status != "done":
            body = {"error": {"code": "loading", "message": "", "details": {"job": job.view()}}}
            return JSONResponse(body, status_code=409)
        return {"ok": True}

    assert warm._read_view(web_ctx, app, "/api/studies/abcabcabcabc/gate")
    assert gate["n"] == 2


def test_internal_reads_do_not_count_as_the_page_being_busy(web_ctx, study):
    app = create_app(web_ctx)
    time.sleep(0.05)
    quiet = ACTIVITY.idle_for()
    status, body = warm._asgi_get(app, web_ctx.token, f"/api/studies/{study}/results")
    assert status == 200 and json.loads(body)["study_id"] == study
    assert ACTIVITY.idle_for() >= quiet  # not reset by the internal read


def test_a_new_study_is_prepared_when_its_event_arrives(web_ctx, study, monkeypatch):
    app = create_app(web_ctx)
    seen: list[list[str]] = []
    monkeypatch.setattr(warm, "prepare_views", lambda ctx, app_, ids: seen.append(ids))
    warm.follow_new_studies(web_ctx, app)
    web_ctx.bus.publish({"type": "study.changed", "key": study, "source": "page"})
    web_ctx.bus.publish({"type": "study.changed", "key": study, "source": "warm"})  # ignored
    deadline = time.monotonic() + 10
    while not seen and time.monotonic() < deadline:
        time.sleep(0.05)
    assert seen == [[study]]


def test_warm_all_with_the_app_prepares_recent_studies(web_ctx, study, monkeypatch, client):
    """A session's current study is prepared after the start-up read (no session: nothing)."""
    asked: list[list[str]] = []
    monkeypatch.setattr(warm, "prepare_views", lambda ctx, app_, ids: asked.append(ids))
    job = warm.warm_all(web_ctx, create_app(web_ctx))
    assert wait_job(client, job.view())["status"] == "done"
    assert asked == [[]]


def test_a_fresh_demo_does_not_wait_for_views_being_prepared(client, web_ctx, study):
    """Only work that writes holds a fresh demo back; preparing a view only reads."""
    import threading

    release = threading.Event()
    web_ctx.jobs.submit("gate.run", lambda progress: release.wait(30), title="t", key=study)
    try:
        r = client.post("/api/demo/fresh")
        assert r.status_code == 200, r.text
        assert web_ctx.store.list_studies() == []
    finally:
        release.set()


def test_background_work_never_takes_a_worker_from_a_persons_jobs(web_ctx):
    """The view preparation runs on its own thread: a person's job starts at once."""
    import threading

    from qpilot.web.jobs import WORKERS

    release = threading.Event()
    held = web_ctx.jobs.submit(
        "prepare", lambda p: release.wait(30), title="t", background=True, dedupe=False
    )
    route_jobs = [
        web_ctx.jobs.submit("gate.run", lambda p: release.wait(30), title="t", key=f"k{i}")
        for i in range(WORKERS - 1)
    ]
    started = threading.Event()
    mine = web_ctx.jobs.submit("open", lambda p: started.set(), title="Opening", key="mine")
    try:
        assert started.wait(10), "a person's job queued behind background work"
        assert held.status == "running" and all(j.status == "running" for j in route_jobs)
    finally:
        release.set()
    assert wait_job_obj(web_ctx, mine).status == "done"
