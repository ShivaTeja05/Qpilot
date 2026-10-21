"""Record the Import Trust route's own answers for the card's tests (no hand-typed values).

Run from the repository root (nothing to download):

    python frontend/src/features/results/__tests__/recorded/record_trust.py

It walks the Studio tests' mini file through Studio as if it had been opened from a CFX export
whose curves were baseline-subtracted (``tests/fixtures/studio/trust.py``), asks the real route
(an in-process server over a throwaway store) and writes, next to this file, what it answers:

* ``trust-open.json`` -- ``GET /api/studies/{id}/import-trust`` before anyone decides (the
  curves as imported, every gene capped at Moderate; a person decides here);
* ``trust-request.json`` -- the same, after an agent asked through MCP for Cq only
  (``qpcr_decide``: the request waits on the card for a person);
* ``trust-cq-only.json`` -- the card of the new analysis after a person chose Cq only
  (``POST .../import-trust/decide``): decided, capped at Low, who decided and why.
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


def write(name: str, body: dict) -> None:
    """Write ``body`` next to this file as compact, key-sorted JSON."""
    text = json.dumps(body, sort_keys=True, separators=(",", ":"))
    (HERE / name).write_text(text + "\n")
    print(f"wrote {name} ({len(text):,} bytes)")


def main() -> None:
    """Write the recordings."""
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient

    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.core.store import StudyStore
    from qpilot.mcp_server import QpilotTools
    from qpilot.studio_service import Studio
    from qpilot.web.context import make_context
    from qpilot.web.server import create_app
    from tests.fixtures.studio import trust

    base = Path(tempfile.mkdtemp(prefix="trust-record-"))
    data = base / "data"
    data.mkdir()
    os.environ["QPILOT_DATA_ROOTS"] = str(data)
    os.environ["QPILOT_STUDIES_DIR"] = str(base / "studies")
    store = StudyStore(base / "studies")
    studio = Studio(store, client=ModelClient(backend=NoneBackend()))
    sid, study = trust.walk_trusted(studio, trust.write_trusted_mini(data))
    ctx = make_context(store, studio, token=TOKEN, watch=False)
    try:
        with TestClient(create_app(ctx), base_url=BASE) as client:
            client.headers["x-qpilot-token"] = TOKEN
            client.headers["origin"] = BASE
            url = f"/api/studies/{study}/import-trust"
            write("trust-open.json", client.get(url).raise_for_status().json())
            out = QpilotTools(store).qpcr_decide(
                study, "card_import_trust", "cq_only", "the export holds baseline-subtracted RFU"
            )
            assert out["status"] == "pending_human", out
            write("trust-request.json", client.get(url).raise_for_status().json())
            r = client.post(
                f"{url}/decide",
                json={"option": "cq_only", "reason": "baseline-subtracted export; report Cq only"},
            )
            r.raise_for_status()
            job = r.json()["job"]
            for _ in range(3000):
                if client.get(f"/api/jobs/{job['id']}").json()["status"] in ("done", "failed"):
                    break
                time.sleep(0.1)
            new = client.get(f"/api/sessions/{sid}").json()["study_id"]
            assert new and new != study, new
            got = client.get(f"/api/studies/{new}/import-trust").raise_for_status().json()
            write("trust-cq-only.json", got)
    finally:
        ctx.close()


if __name__ == "__main__":
    main()
