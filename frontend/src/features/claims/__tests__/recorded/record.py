"""Record the Claims section's test JSON from a real study store (never hand-written numbers).

Run from the repository root, with the store holding the Studio walk of the demo and its audit:

    python frontend/src/features/claims/__tests__/recorded/record.py --study e300000d4f9a

It asks the real server (in process) for:

* ``examples.json`` -- ``GET /api/studies/{id}/claims/examples`` (sentences written from the
  study's own facts);
* ``report.json`` -- ``POST /api/studies/{id}/claims`` on that example paragraph followed by
  the sentences in ``EXTRA`` (claims about a normaliser the study checks but did not plan,
  group sizes, a list read "respectively", and a claim about groups the study does not compare),
  so every verdict and span kind appears.

The sentences in ``EXTRA`` name the study's genes and groups only; every number in the answers
is the server's.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from qpilot.core.store import StudyStore
from qpilot.web.context import make_context
from qpilot.web.server import create_app

HERE = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:7860"
EXTRA = (
    "Expression was normalised to UBC. ODC1 and BIRC5 were up-regulated (4.1- and 6-fold, "
    "respectively). n = 53 vs 294 tumours. GAPDH was unchanged. Survivin was 4-fold higher in "
    "MYCN-amplified tumours (p < 0.001)."
)


def main() -> None:
    """Write the recorded answers next to this file."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--study", required=True)
    parser.add_argument("--studies", default=os.environ.get("QPILOT_STUDIES_DIR"))
    args = parser.parse_args()
    ctx = make_context(StudyStore(args.studies), token="record", watch=False)
    try:
        with TestClient(create_app(ctx), base_url=BASE) as c:
            c.headers.update({"x-qpilot-token": "record", "origin": BASE})
            examples = c.get(f"/api/studies/{args.study}/claims/examples").json()
            text = examples["paragraph"] + " " + EXTRA
            report = c.post(f"/api/studies/{args.study}/claims", json={"text": text}).json()
            report["text"] = text  # the page holds the text it sent; kept here for the tests
            for name, body in (("examples", examples), ("report", report)):
                path = HERE / f"{name}.json"
                path.write_text(json.dumps(body, indent=1, ensure_ascii=False) + "\n")
                print("wrote", path)
    finally:
        ctx.close()


if __name__ == "__main__":
    main()
