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
def web_ctx(web_store, monkeypatch):
    # No model unless a test configures one: the developer's environment never leaks in (CI has
    # no QPILOT_MODEL_PROVIDER, so Studio's default would be the local endpoint).
    monkeypatch.setenv("QPILOT_MODEL_PROVIDER", "none")
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


# ---- views a job prepares (409 loading / 503 warming) ----------------------------------------

#: The answers that mean "a job is preparing this; ask again when it is done" (the page's
#: ``Prefer: respond-async`` turns them into 202, see qpilot/web/cache.py). A route waits a
#: moment for its job (``WAIT_S`` in gate.py and trace.py), then answers one of these; on a
#: loaded machine that is the normal first answer, so a test must never assume it finished.
SOFT_WAIT = {(409, "loading"), (503, "warming")}


def waiting_job(r) -> dict | None:
    """The job a ``409 loading`` / ``503 warming`` answer names; ``{}`` for one that names
    none (ask again shortly); ``None`` for any other answer."""
    if r.status_code not in (409, 503):
        return None
    try:
        error = r.json().get("error") or {}
    except (ValueError, AttributeError):
        return None
    if (r.status_code, error.get("code")) not in SOFT_WAIT:
        return None
    job = (error.get("details") or {}).get("job")
    return job if isinstance(job, dict) and job.get("id") else {}


def settled(client: TestClient, send, *, timeout: float = 300.0, jobs: list | None = None):
    """``send()`` again until the answer is not "being prepared"; return that answer.

    Every job a ``409 loading`` / ``503 warming`` answer names is followed to its end (each one
    is appended to ``jobs`` when given, so a test can check what ran); a job that failed is
    asked about once more and that answer (the route's own refusal) is returned. ``send`` is a
    function so a request with an upload can open its file again for each try.
    """
    import time

    deadline = time.monotonic() + timeout
    while True:
        r = send()
        job = waiting_job(r)
        if job is None:
            return r
        if time.monotonic() > deadline:
            raise AssertionError(f"still being prepared after {timeout:.0f} s: {r.text}")
        if not job:
            time.sleep(0.1)
            continue
        view = wait_job(client, job, max(1.0, deadline - time.monotonic()))
        if jobs is not None:
            jobs.append(view)
        if view["status"] == "failed":
            return send()


def get_settled(client: TestClient, url: str, **kwargs):
    """``GET url`` once its view is prepared (see :func:`settled`)."""
    jobs = kwargs.pop("jobs", None)
    return settled(client, lambda: client.get(url, **kwargs), jobs=jobs)


@pytest.fixture(autouse=True)
def _loaded_machine(monkeypatch):
    """``QPILOT_TEST_NO_JOB_WAIT=1``: the routes answer ``409 loading`` at once, as they do on
    a loaded machine, so a run shows every test that assumes a job finished within ``WAIT_S``
    (``QPILOT_TEST_NO_JOB_WAIT=1 pytest tests/web``). A test that sets ``WAIT_S`` keeps its own."""
    import os

    if os.environ.get("QPILOT_TEST_NO_JOB_WAIT") == "1":
        from qpilot.web.routers import gate, trace

        monkeypatch.setattr(gate, "WAIT_S", 0.0)
        monkeypatch.setattr(trace, "WAIT_S", 0.0)
    yield


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


# ---- an analysed study (the mini file walked through Studio once per module) -----------------

MINI_GROUPS = {"WT_1": "WT", "WT_2": "WT", "KO_1": "KO", "KO_2": "KO"}


def walk_mini(studio, rdml) -> tuple[str, str]:
    """Open, propose, decide and confirm the mini file as a person would; analyse it."""
    from qpilot.mcp_server import QpilotTools

    tools = QpilotTools(studio.store)
    sid = studio.open(rdml)
    studio.propose_design(sid)
    for sample, group in MINI_GROUPS.items():
        tools.qpcr_propose(sid, "design.group", sample, {"group": group})
    for p in studio.inbox(sid, "design", "proposed"):
        studio.accept(sid, p.id, "human", "checked")
    comparison = studio.propose_comparison(sid)
    studio.accept(sid, comparison.proposal.id, "human", "WT is the reference")
    for stage in ("design", "curves"):
        if stage == "curves":
            studio.propose_curves(sid)
            for p in studio.inbox(sid, "curves", "proposed"):
                studio.accept(sid, p.id, "human", "checked")
        confirm = studio.propose_confirm(sid, stage)
        studio.accept(sid, confirm.proposal.id, "human")
    return sid, studio.study(sid)


@pytest.fixture(scope="module")
def mini_walked(tmp_path_factory):
    """A store holding the walked mini session and its analysed study (built once)."""
    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.qpcr import design_checks
    from qpilot.qpcr import inspect as qinspect
    from qpilot.studio_service import Studio
    from tests.fixtures.studio.studio_mini import write_studio_mini

    base = tmp_path_factory.mktemp("walked")
    root = base / "data"
    root.mkdir()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("QPILOT_DATA_ROOTS", str(root))
        mp.setenv("QPILOT_STUDIES_DIR", str(base / "studies"))
        qinspect.clear_cache()
        rdml = write_studio_mini(root / "mini.rdml")
        studio = Studio(StudyStore(base / "studies"), client=ModelClient(backend=NoneBackend()))
        sid, study_id = walk_mini(studio, rdml)
        design_checks._DECLARED.clear()
        design_checks.set_input_resolver(None)
        qinspect.clear_cache()
    return {"base": base, "root": root, "sid": sid, "study": study_id}


@pytest.fixture
def walked(mini_walked, tmp_path, monkeypatch):
    """A private copy of the walked store, its server context and a keyed client."""
    import shutil

    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.qpcr import design_checks
    from qpilot.qpcr import inspect as qinspect
    from qpilot.studio_service import Studio

    shutil.copytree(mini_walked["base"], tmp_path / "w", symlinks=False)
    # the session is bound to the file by path: the copy keeps the original data root
    monkeypatch.setenv("QPILOT_DATA_ROOTS", str(mini_walked["root"]))
    monkeypatch.setenv("QPILOT_STUDIES_DIR", str(tmp_path / "w" / "studies"))
    qinspect.clear_cache()
    store = StudyStore(tmp_path / "w" / "studies")
    studio = Studio(store, client=ModelClient(backend=NoneBackend()))
    ctx = make_context(store, studio, token=TOKEN, watch=False)
    with TestClient(create_app(ctx), base_url=BASE) as c:
        c.headers["x-qpilot-token"] = TOKEN
        c.headers["origin"] = BASE
        yield {"client": c, "store": store, "studio": studio, "ctx": ctx, **mini_walked}
    ctx.close()
    design_checks._DECLARED.clear()
    design_checks.set_input_resolver(None)
    qinspect.clear_cache()
