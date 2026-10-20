"""Record a real Ask answer from a running ``qpilot app`` for the drawer's tests.

Usage (repository root, server running): ``python record_ask.py OUT QUESTION [SOURCE]``. Writes
the finished job (``GET /api/jobs/{id}``) of ``POST /api/studies/e300000d4f9a/ask`` to ``OUT``
next to this file. ``QPILOT_API`` and ``QPILOT_APP_TOKEN`` come from ``agent-bus/ui-env.sh``.
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

API = os.environ["QPILOT_API"]
KEY = os.environ["QPILOT_APP_TOKEN"]
STUDY = "e300000d4f9a"


def call(path: str, body: dict | None = None) -> dict:
    """One JSON request to the page's API with this launch's key."""
    request = urllib.request.Request(
        API + path,
        method="POST" if body else "GET",
        headers={"x-qpilot-token": KEY, "content-type": "application/json"},
        data=json.dumps(body).encode() if body else None,
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def main() -> None:
    """Ask, wait for the job, and save it."""
    out, question = sys.argv[1], sys.argv[2]
    source = sys.argv[3] if len(sys.argv) > 3 else "auto"
    job = call(f"/api/studies/{STUDY}/ask", {"question": question, "source": source})["job"]
    for _ in range(60):
        view = call(f"/api/jobs/{job['id']}")
        if view["status"] in ("done", "failed"):
            break
        time.sleep(0.5)
    path = Path(__file__).resolve().parent / Path(out).name
    path.write_text(json.dumps(view, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(path.name, view["status"], (view.get("result") or {}).get("tool"))


if __name__ == "__main__":
    main()
