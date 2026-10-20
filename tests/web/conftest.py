"""Fixtures for the one server: an app over a throwaway store, and a client with the key."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from qpilot.core.store import StudyStore
from qpilot.web.context import make_context
from qpilot.web.server import create_app

TOKEN = "test-token"
BASE = "http://127.0.0.1:7860"


@pytest.fixture
def web_store(tmp_studies_dir) -> StudyStore:
    return StudyStore(tmp_studies_dir)


@pytest.fixture
def web_ctx(web_store):
    ctx = make_context(web_store, token=TOKEN, watch=False)
    yield ctx
    ctx.close()


@pytest.fixture
def raw_client(web_ctx) -> Iterator[TestClient]:
    """A client without the launch key (for the guard's refusals)."""
    with TestClient(create_app(web_ctx), base_url=BASE) as client:
        yield client


@pytest.fixture
def client(web_ctx) -> Iterator[TestClient]:
    """A client that carries the launch key, as the page does after opening the printed link."""
    with TestClient(create_app(web_ctx), base_url=BASE) as c:
        c.headers["x-qpilot-token"] = TOKEN
        yield c


# ---- Studio over HTTP on a small synthetic file (no download, no model) ----------------------

ORIGIN = {"origin": BASE}


def wait_job(client: TestClient, job: dict, timeout: float = 300.0) -> dict:
    """Follow a job until it is done or failed; return its last view."""
    import time

    deadline = time.monotonic() + timeout
    while True:
        view = client.get(f"/api/jobs/{job['id']}").json()
        if view["status"] in ("done", "failed"):
            return view
        if time.monotonic() > deadline:
            raise AssertionError(f"job {job['kind']} did not finish: {view}")
        time.sleep(0.05)


@pytest.fixture
def mini_rdml(tmp_path, monkeypatch):
    """The Studio tests' synthetic two-plate file, in a data root agents may read."""
    from qpilot.qpcr import design_checks
    from qpilot.qpcr import inspect as qinspect
    from tests.fixtures.studio.studio_mini import write_studio_mini

    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("QPILOT_DATA_ROOTS", str(root))
    qinspect.clear_cache()
    yield write_studio_mini(root / "mini.rdml")
    design_checks._DECLARED.clear()
    design_checks.set_input_resolver(None)
    qinspect.clear_cache()


@pytest.fixture
def studio_ctx(web_store, mini_rdml):
    """A server context whose Studio uses no model (the rules alone propose)."""
    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.studio_service import Studio

    studio = Studio(web_store, client=ModelClient(backend=NoneBackend()))
    ctx = make_context(web_store, studio, token=TOKEN, watch=False)
    yield ctx
    ctx.close()


@pytest.fixture
def sclient(studio_ctx) -> Iterator[TestClient]:
    """A keyed client over the model-free Studio context."""
    with TestClient(create_app(studio_ctx), base_url=BASE) as c:
        c.headers["x-qpilot-token"] = TOKEN
        c.headers["origin"] = BASE
        yield c


@pytest.fixture
def opened(sclient, mini_rdml) -> str:
    """The mini file opened over HTTP (upload); returns the session id."""
    with mini_rdml.open("rb") as fh:
        r = sclient.post("/api/workspaces", files={"rdml": ("mini.rdml", fh, "application/xml")})
    assert r.status_code == 202, r.text
    job = wait_job(sclient, r.json()["job"])
    assert job["status"] == "done", job
    return job["result"]["key"]
