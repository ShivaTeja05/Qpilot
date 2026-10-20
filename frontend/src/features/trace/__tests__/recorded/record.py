"""Record the Trace routes' own answers for the Trace section's tests (never hand-written numbers).

Run from the repository root, with the store holding the Studio walk of the demo study:

    python frontend/src/features/trace/__tests__/recorded/record.py --study e300000d4f9a

It asks the real routes (an in-process server over the store, read-only) and writes, next to
this file, exactly what they answer:

* ``trace-study.json`` -- ``GET /api/studies/{id}/trace``;
* ``trace-<GENE>.json`` -- ``GET /api/studies/{id}/trace/{gene}`` for each gene named;
* ``without-<GENE>.json`` -- ``POST /api/studies/{id}/trace/{gene}/without`` with the gene's
  smallest flip set (the samples whose removal changes its call).
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    """Write the recordings."""
    from fastapi.testclient import TestClient

    from qpilot.core.store import StudyStore
    from qpilot.web.context import make_context
    from qpilot.web.server import create_app

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True)
    parser.add_argument("--studies", default=os.environ.get("QPILOT_STUDIES_DIR"))
    parser.add_argument("--genes", nargs="+", default=["CAMTA2"])
    args = parser.parse_args()
    ctx = make_context(StudyStore(args.studies), token="record", watch=False)
    base = "http://127.0.0.1:7860"
    try:
        with TestClient(create_app(ctx), base_url=base) as client:
            client.headers["x-qpilot-token"] = "record"
            client.headers["origin"] = base

            def get(url: str) -> dict:
                for _ in range(600):
                    r = client.get(url)
                    if r.status_code != 409 or r.json()["error"]["code"] != "loading":
                        r.raise_for_status()
                        return r.json()
                    time.sleep(0.1)
                raise RuntimeError(f"{url} kept loading")

            def write(name: str, body: dict) -> None:
                text = json.dumps(body, sort_keys=True, separators=(",", ":"))
                (HERE / name).write_text(text + "\n")
                print(f"wrote {name} ({len(text):,} bytes)")

            study = f"/api/studies/{args.study}/trace"
            write("trace-study.json", get(study))
            for gene in args.genes:
                body = get(f"{study}/{gene}")
                write(f"trace-{gene}.json", body)
                units = body["trace"]["flip"]["units"]
                if units:
                    r = client.post(f"{study}/{gene}/without", json={"samples": units})
                    r.raise_for_status()
                    write(f"without-{gene}.json", r.json())
    finally:
        ctx.close()


if __name__ == "__main__":
    main()
