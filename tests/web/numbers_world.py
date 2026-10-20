"""The real demo the number tests read, built once per test process.

:func:`demo_world` walks the demo study through Studio exactly as ``qpilot studio demo
--check`` does (the rules propose alone, a scripted person decides, the Prism round trip
excludes one value), runs the robustness audit on the session's current study when the
Decision Simulator is installed, and adds the demo analysed outside a session (``qpilot run``'s
legacy study). Every number then comes from that real store; the tests compare what the API
serves with what the engine, the store, the CLI or the simulator compute on their own.

Set ``QPILOT_NUMBERS_SEED`` to a store made the same way (``qpilot studio demo --check
--studies DIR``, then ``python -m qpilot.integration audit --study ID``) to skip the build
(about two minutes) while developing; the seed is copied, never written.
"""

from __future__ import annotations

import functools
import json
import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from qpilot.core.store import StudyStore

TOKEN = "numbers-token"
BASE = "http://127.0.0.1:7860"


@dataclass
class World:
    """The demo store and the ids the tests need."""

    store: StudyStore
    rdml: Path
    sid: str
    study: str
    before_roundtrip: str | None
    legacy: str
    audited: bool
    log: list[str] = field(default_factory=list)


def session_meta(store: StudyStore, sid: str) -> dict[str, Any]:
    """A session's ``studio.json``."""
    return json.loads((store.find_session(sid) / "studio.json").read_text(encoding="utf-8"))


@functools.cache
def demo_world(root: Path, rdml: Path) -> World:
    """Build (or copy) the demo store under ``root`` once per process; see the module doc."""
    from qpilot.integration import simulator as sim

    studies = root / "studies"
    log: list[str] = []
    seed = os.environ.get("QPILOT_NUMBERS_SEED")
    if seed:
        shutil.copytree(seed, studies)
        log.append(f"copied the seed store {seed}")
    else:
        from qpilot.cli.studio_cmds import demo_check

        code = demo_check(studies, out=log.append)
        if code != 0:
            raise AssertionError("the Studio demo walk failed:\n" + "\n".join(log))
    store = StudyStore(studies)
    sessions = [p.name for p in (studies / "sessions").iterdir() if p.is_dir()]
    if len(sessions) != 1:
        raise AssertionError(f"expected one Studio session, found {sessions}")
    sid = sessions[0][:12]
    meta = session_meta(store, sid)
    study = meta["current_study"]
    others = [s for s in meta.get("studies", {}) if s != study]
    audited = (store.root / "simulator_audits" / study / "audit_manifest.json").exists()
    if not audited and sim.available():
        sim.audit(store, study, store.root / "simulator_audits" / study)
        audited = True
        log.append(f"audited {study}")
    legacy = store.ensure_study(rdml)
    return World(
        store=store,
        rdml=rdml,
        sid=sid,
        study=study,
        before_roundtrip=others[0] if others else None,
        legacy=legacy,
        audited=audited,
        log=log,
    )


@contextmanager
def api_client(store: StudyStore) -> Iterator[TestClient]:
    """The one server over ``store``, with the launch key, as the page uses it."""
    from qpilot.web.context import make_context
    from qpilot.web.server import create_app

    ctx = make_context(store, token=TOKEN, watch=False)
    try:
        with TestClient(create_app(ctx), base_url=BASE) as client:
            client.headers["x-qpilot-token"] = TOKEN
            yield client
    finally:
        ctx.close()


def get_json(client: TestClient, url: str) -> Any:
    """GET a route and return its JSON, failing with the server's words when it is not 200."""
    response = client.get(url)
    assert response.status_code == 200, f"{url}: {response.status_code} {response.text[:400]}"
    return response.json()


@functools.cache
def engine_run(rdml: Path, design_json: str | None) -> tuple[Any, list[Any], Any]:
    """The engine run from scratch (``run_study``), outside the store: the independent numbers.

    ``design_json`` is the confirmed design as JSON (``None`` for ``qpilot run``'s analysis),
    so the cache key is the design's content, not the store's copy of it.
    """
    from qpilot.qpcr.study import StudySettings, run_study
    from qpilot.schemas_studio import StudyDesign

    if design_json is None:
        return run_study(rdml)
    design = StudyDesign.model_validate_json(design_json)
    return run_study(rdml, StudySettings.from_design(design))


def engine_for(world: World, study_id: str) -> tuple[Any, list[Any], Any]:
    """``run_study`` on the study's confirmed design (or none for the legacy study)."""
    design = world.store.design(study_id)
    return engine_run(world.rdml, None if design is None else design.model_dump_json())


def call_ready(client: TestClient, url: str, body: Any = None, timeout: float = 600.0) -> Any:
    """GET (or POST ``body``) a route that may answer 409 ``loading``: wait for its job, retry.

    The audit's live views load in a job the first time (``details.job``); this follows that
    job and asks again, so a test reads the view, not the wait.
    """
    import time

    deadline = time.monotonic() + timeout
    while True:
        response = client.get(url) if body is None else client.post(url, json=body)
        if response.status_code != 409 or response.json()["error"]["code"] != "loading":
            assert response.status_code == 200, f"{url}: {response.status_code} {response.text}"
            return response.json()
        job = (response.json()["error"].get("details") or {}).get("job") or {}
        while job.get("id"):
            view = client.get(f"/api/jobs/{job['id']}").json()
            if view["status"] in ("done", "failed"):
                break
            assert time.monotonic() < deadline, view
            time.sleep(0.2)
        assert time.monotonic() < deadline, f"{url}: still loading"
