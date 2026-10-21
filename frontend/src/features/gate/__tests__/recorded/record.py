"""Record the Run Gate route's own answers for the Controls section's tests (no hand-typed numbers).

Run from the repository root (the demo must be cached: ``qpilot fetch-demo``):

    python frontend/src/features/gate/__tests__/recorded/record.py

It asks the real route (an in-process server over a throwaway store) and writes,
next to this file, exactly what it answers:

* ``gate-demo.json`` -- ``GET /api/studies/{id}/gate`` for the demo study analysed outside
  Studio (Vermeulen 2013: 64 plates; three auto-decided cards, no call changes at the analysis);
* ``gate-mini.json`` -- the same route for the Studio tests' mini file walked through Studio,
  with a no-template control that amplifies early on ``1-Mar`` (one open card: leaving the
  tainted wells out leaves the gene without a call; a person decides it here);
* ``gate-mini-request.json`` -- the same, after an agent asked through MCP to leave the wells
  out (``qpcr_decide``: the request waits on the card for a person);
* ``gate-mini-left-out.json`` -- the gate of the new analysis after a person left the wells out
  (``POST .../gate/cards/{card}/decide``): no card any more, the wells listed as left out, with
  who decided and why;
* ``gate-rt-linked.json`` -- a two-plate file whose design marks reverse-transcription
  replicates (``tests/web/test_gate_runs.py``: unit ``KO2``'s second RT is late on ``1-Mar``,
  so G-RT warns) analysed outside Studio, after a person linked a paused run's ``.eds``
  (``tests/engine/instrument_files.py``) to ``1-Mar_plate`` (``POST .../gate/run-files``): G-INSTR
  warns there and leaving the run's study wells out changes the gene's call.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
TOKEN = "record"
BASE = "http://127.0.0.1:7860"


def get(client, url: str) -> dict:
    """GET ``url``, asking again while the ``gate.run`` job works (409 loading)."""
    for _ in range(1200):
        r = client.get(url)
        if r.status_code != 409 or r.json()["error"]["code"] != "loading":
            r.raise_for_status()
            return r.json()
        time.sleep(0.1)
    raise RuntimeError(f"{url} kept loading")


def write(name: str, body: dict) -> None:
    """Write ``body`` next to this file as compact, key-sorted JSON."""
    text = json.dumps(body, sort_keys=True, separators=(",", ":"))
    (HERE / name).write_text(text + "\n")
    print(f"wrote {name} ({len(text):,} bytes)")


def record(store, studio, study: str, name: str, then=None, before=None) -> None:
    """Record ``/gate`` of one study of ``store`` (an in-process server).

    ``before(client)``, when given, acts first (as a person would); ``then(client, body)``
    acts after the recording (as a person or an agent would) and returns more
    ``(study, name)`` pairs to record.
    """
    from fastapi.testclient import TestClient

    from qpilot.web.context import make_context
    from qpilot.web.server import create_app

    ctx = make_context(store, studio, token=TOKEN, watch=False)
    try:
        with TestClient(create_app(ctx), base_url=BASE) as client:
            client.headers["x-qpilot-token"] = TOKEN
            client.headers["origin"] = BASE
            if before is not None:
                before(client)
            body = get(client, f"/api/studies/{study}/gate")
            write(name, body)
            for more_study, more_name in then(client, body) if then else []:
                write(more_name, get(client, f"/api/studies/{more_study}/gate"))
    finally:
        ctx.close()


def mini_steps(store, sid: str, study: str):
    """An agent asks to leave the tainted wells out; then a person does (a new analysis)."""
    from qpilot.mcp_server import QpilotTools

    def then(client, body):
        card = body["cards"][0]["card"]["id"]
        out = QpilotTools(store).qpcr_decide(
            study, card, "exclude_flagged", "the no-template control amplified"
        )
        assert out["status"] == "pending_human", out
        yield study, "gate-mini-request.json"
        r = client.post(
            f"/api/studies/{study}/gate/cards/{card}/decide",
            json={"option": "exclude_flagged", "reason": "the NTC amplified on this plate"},
        )
        r.raise_for_status()
        job = r.json()["job"]
        for _ in range(3000):
            if client.get(f"/api/jobs/{job['id']}").json()["status"] in ("done", "failed"):
                break
            time.sleep(0.1)
        new = client.get(f"/api/sessions/{sid}").json()["study_id"]
        assert new and new != study, new
        yield new, "gate-mini-left-out.json"

    return then


def main() -> None:
    """Write the recordings."""
    sys.path.insert(0, str(ROOT))
    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.core.store import StudyStore
    from qpilot.io.datasets import default_cache_dir
    from qpilot.studio_service import Studio
    from tests.fixtures.studio import studio_mini
    from tests.web.conftest import walk_mini

    base = Path(tempfile.mkdtemp(prefix="gate-record-"))
    rdml = default_cache_dir() / "data_vermeulen_raw.rdml"
    store = StudyStore(base / "demo")
    record(store, None, store.ensure_study(rdml), "gate-demo.json")

    data = base / "data"
    data.mkdir()
    os.environ["QPILOT_DATA_ROOTS"] = str(data)
    studio_mini.PLATES["1-Mar"]["NTC"] = [None, None, 30.5]  # as tests/web/test_gate_routes.py
    mini = studio_mini.write_studio_mini(data / "mini.rdml")
    store = StudyStore(base / "mini")
    studio = Studio(store, client=ModelClient(backend=NoneBackend()))
    sid, study = walk_mini(studio, mini)
    record(store, studio, study, "gate-mini.json", mini_steps(store, sid, study))

    import pytest

    from tests.engine import instrument_files as F
    from tests.web.test_gate_runs import rt_file

    with pytest.MonkeyPatch.context() as mp:
        rdml, design = rt_file(data / "rt.rdml", mp)
    store = StudyStore(base / "rt" / "studies")
    study = store.ensure_study(rdml, design)
    eds = F.qs_v1_expired(base / "QS5_run.eds", pause_at=23)

    def link(client):
        with eds.open("rb") as handle:
            r = client.post(
                f"/api/studies/{study}/gate/run-files",
                data={"plate": "1-Mar_plate"},
                files={"run": ("QS5_run.eds", handle, "application/octet-stream")},
            )
        r.raise_for_status()

    record(store, None, study, "gate-rt-linked.json", before=link)


if __name__ == "__main__":
    main()
