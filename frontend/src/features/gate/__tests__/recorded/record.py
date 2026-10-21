"""Record the Run Gate route's own answers for the Controls section's tests (no hand-typed numbers).

Run from the repository root (the demo must be cached: ``qpilot fetch-demo``):

    python frontend/src/features/gate/__tests__/recorded/record.py

It asks the real route (an in-process server over a throwaway store, read-only) and writes,
next to this file, exactly what it answers:

* ``gate-demo.json`` -- ``GET /api/studies/{id}/gate`` for the demo study analysed outside
  Studio (Vermeulen 2013: 64 plates; three auto-decided cards, no call changes at the analysis);
* ``gate-mini.json`` -- the same route for the Studio tests' mini file walked through Studio,
  with a no-template control that amplifies early on ``1-Mar`` (one open card: leaving the
  tainted wells out leaves the gene without a call).
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


def record(store, studio, study: str, name: str) -> None:
    """Record ``/gate`` of one study of ``store`` (an in-process server, read-only)."""
    from fastapi.testclient import TestClient

    from qpilot.web.context import make_context
    from qpilot.web.server import create_app

    ctx = make_context(store, studio, token=TOKEN, watch=False)
    try:
        with TestClient(create_app(ctx), base_url=BASE) as client:
            client.headers["x-qpilot-token"] = TOKEN
            client.headers["origin"] = BASE
            write(name, get(client, f"/api/studies/{study}/gate"))
    finally:
        ctx.close()


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
    _, study = walk_mini(studio, mini)
    record(store, studio, study, "gate-mini.json")


if __name__ == "__main__":
    main()
