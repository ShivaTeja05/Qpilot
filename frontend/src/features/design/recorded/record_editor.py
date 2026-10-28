"""Record the Design editor's API answers for its tests (nothing is hand-written).

Run from the repository root (nothing to download):

    python frontend/src/features/design/recorded/record_editor.py

The synthetic CFX Manager export of the public corpus
(``tests/fixtures/corpus/synthetic/cfx-manager-raw-vs-baseline-subtracted``, raw RFU) is opened
through ``POST /api/workspaces`` with ``files`` and a two-column group sheet, on a throwaway
store (FastAPI TestClient over the real app, no model), the rules propose, and:

* ``editor-cfx-synthetic.json``: ``GET /api/sessions/{sid}/design/editor``;
* ``plan-cfx-synthetic.json``: ``POST /api/sessions/{sid}/design/check`` for a draft that marks
  REF a reference gene, puts S1 in group A (what the sheet proposed) and S5 in group Z (the
  sheet said B), and puts the NTC in a group (refused: a control joins no group).
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
CFX = (
    ROOT / "tests" / "fixtures" / "corpus" / "synthetic" / "cfx-manager-raw-vs-baseline-subtracted"
)
GROUPS = "Sample,Group\nS1,A\nS2,A\nS3,A\nS4,A\nS5,B\nS6,B\nS7,B\nS8,B\n"
TOKEN = "record"
BASE = "http://127.0.0.1:7860"
DRAFT = [
    {"kind": "design.target_role", "subject": "REF", "payload": {"role": "ref"}},
    {"kind": "design.group", "subject": "S1", "payload": {"group": "A"}},
    {"kind": "design.group", "subject": "S5", "payload": {"group": "Z"}},
    {"kind": "design.group", "subject": "NTC", "payload": {"group": "A"}},
]


def main() -> None:
    """Write the recordings."""
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient

    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.core.store import StudyStore
    from qpilot.studio_service import Studio
    from qpilot.web.context import make_context
    from qpilot.web.server import create_app

    base = Path(tempfile.mkdtemp(prefix="editor-record-"))
    os.environ["QPILOT_STUDIES_DIR"] = str(base / "studies")
    store = StudyStore(base / "studies")
    studio = Studio(store, client=ModelClient(backend=NoneBackend()))
    ctx = make_context(store, studio, token=TOKEN, watch=False)

    def wait(client: TestClient, job: dict) -> dict:
        for _ in range(3000):
            view = client.get(f"/api/jobs/{job['id']}").json()
            if view["status"] in ("done", "failed"):
                return view
            time.sleep(0.1)
        raise AssertionError(job)

    try:
        with TestClient(create_app(ctx), base_url=BASE) as client:
            client.headers["x-qpilot-token"] = TOKEN
            client.headers["origin"] = BASE
            paths = sorted(CFX.glob("qpilot-synthetic-raw *"))
            parts = [("files", (p.name, p.read_bytes(), "text/plain")) for p in paths]
            parts.append(("sheet", ("groups.csv", GROUPS.encode(), "text/csv")))
            r = client.post("/api/workspaces", files=parts)
            assert r.status_code == 202, r.text
            sid = wait(client, r.json()["job"])["result"]["key"]
            r = client.post(f"/api/sessions/{sid}/propose/design", json={})
            assert wait(client, r.json()["job"])["status"] == "done"
            editor = client.get(f"/api/sessions/{sid}/design/editor").json()
            plan = client.post(f"/api/sessions/{sid}/design/check", json={"items": DRAFT}).json()
            for name, data in (
                ("editor-cfx-synthetic.json", editor),
                ("plan-cfx-synthetic.json", plan),
            ):
                (HERE / name).write_text(
                    json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                )
                print(f"wrote {name}")
    finally:
        ctx.close()


if __name__ == "__main__":
    main()
