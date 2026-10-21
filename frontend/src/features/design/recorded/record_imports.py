"""Record the session frame's ``capture`` for two corpus exports (the Imported from card's tests).

Run from the repository root (nothing to download):

    python frontend/src/features/design/recorded/record_imports.py

Each export of the public corpus (``tests/fixtures/corpus``) is opened through
``POST /api/workspaces`` with ``files`` on a throwaway store (FastAPI TestClient over the real
app, no model), and ``GET /api/sessions/{sid}`` → ``capture`` is written next to this file:

* ``import-cfx-hsieh-gapdh.json``: every ``2016-09-04 gapdh*`` file of
  ``biorad/hsieh2016-cfx-manager-3.1-sybr``;
* ``import-lc480-cp-table.json``: ``roche/sanger-lc480-cp-table/qPCR.txt``.
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
CORPUS = ROOT / "tests" / "fixtures" / "corpus"
TOKEN = "record"
BASE = "http://127.0.0.1:7860"
EXPORTS = {
    "import-cfx-hsieh-gapdh.json": sorted(
        (CORPUS / "biorad" / "hsieh2016-cfx-manager-3.1-sybr").glob("2016-09-04 gapdh*")
    ),
    "import-lc480-cp-table.json": [CORPUS / "roche" / "sanger-lc480-cp-table" / "qPCR.txt"],
}


def main() -> None:
    """Write the recordings."""
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient

    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.core.store import StudyStore
    from qpilot.studio_service import Studio
    from qpilot.web.context import make_context
    from qpilot.web.server import create_app

    base = Path(tempfile.mkdtemp(prefix="imports-record-"))
    os.environ["QPILOT_STUDIES_DIR"] = str(base / "studies")
    store = StudyStore(base / "studies")
    studio = Studio(store, client=ModelClient(backend=NoneBackend()))
    ctx = make_context(store, studio, token=TOKEN, watch=False)
    try:
        with TestClient(create_app(ctx), base_url=BASE) as client:
            client.headers["x-qpilot-token"] = TOKEN
            client.headers["origin"] = BASE
            for name, paths in EXPORTS.items():
                parts = [("files", (p.name, p.read_bytes(), "text/plain")) for p in paths]
                r = client.post("/api/workspaces", files=parts)
                assert r.status_code == 202, r.text
                job = r.json()["job"]
                for _ in range(3000):
                    view = client.get(f"/api/jobs/{job['id']}").json()
                    if view["status"] in ("done", "failed"):
                        break
                    time.sleep(0.1)
                assert view["status"] == "done", view
                frame = client.get(f"/api/sessions/{view['result']['key']}").json()
                text = json.dumps(frame["capture"], indent=2, ensure_ascii=False)
                (HERE / name).write_text(text + "\n")
                print(f"wrote {name}")
    finally:
        ctx.close()


if __name__ == "__main__":
    main()
