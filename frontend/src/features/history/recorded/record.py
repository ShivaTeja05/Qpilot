"""Record the History routes' real answers for the History section's tests (never hand-written).

Run from the repository root, with ``$QPILOT_STUDIES_DIR`` holding the Studio walk of the demo
(the session's two analyses: before and after the Prism round trip):

    python frontend/src/features/history/recorded/record.py --study e300000d4f9a

It asks the one server (in-process, over the real routes) for, and writes next to this file:

* ``session-<sid>.json`` -- ``GET /api/sessions/{sid}``, the workspace frame the page opens;
* ``history-<study>.json`` and ``history-<other>.json`` -- ``GET /api/studies/{id}/history``
  for the study and for every other analysis of its file;
* ``diff-<study>-<from>-<to>.json`` -- ``GET …/history/diff`` from step 0 to the head;
* ``compare-<study>-<other>.json`` -- ``GET …/history/compare?other=``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOKEN = "record"


def main() -> None:
    """Write the recordings for one study (and the other analyses of its file)."""
    from fastapi.testclient import TestClient

    from qpilot.core.store import StudyStore
    from qpilot.web.context import make_context
    from qpilot.web.server import create_app

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--study", required=True, help="the study id (12 hex)")
    args = parser.parse_args()

    ctx = make_context(StudyStore(), token=TOKEN, watch=False)
    try:
        with TestClient(create_app(ctx), base_url="http://127.0.0.1:7860") as client:
            client.headers["x-qpilot-token"] = TOKEN

            def save(name: str, path: str, params: dict | None = None) -> dict:
                response = client.get(path, params=params)
                response.raise_for_status()
                body = response.json()
                text = json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False)
                (HERE / name).write_text(text + "\n", encoding="utf-8")
                print(f"wrote {name}")
                return body

            study = args.study
            view = save(f"history-{study}.json", f"/api/studies/{study}/history")
            if view["session"]:
                sid = view["session"]
                save(f"session-{sid}.json", f"/api/sessions/{sid}")
            head = view["steps"][-1]["seq"]
            save(
                f"diff-{study}-0-{head}.json",
                f"/api/studies/{study}/history/diff",
                {"from": 0, "to": head},
            )
            for other in view["related"]:
                oid = other["study_id"]
                save(f"history-{oid}.json", f"/api/studies/{oid}/history")
                save(
                    f"compare-{study}-{oid}.json",
                    f"/api/studies/{study}/history/compare",
                    {"other": oid},
                )
    finally:
        ctx.close()


if __name__ == "__main__":
    main()
