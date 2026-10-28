"""Record real JSON for the planner's tests from a running `qpilot app` (never typed in).

Start the server on a store that holds the Studio walk of the demo, then, from the repository root:

    qpilot app --no-open --port 7895 &
    python frontend/src/features/planner/recorded/record.py --port 7895 --session bc1d233e3866

It writes, next to this file, exactly what the page reads:

* ``session.json`` -- ``GET /api/sessions/{sid}`` (the workspace frame), with the file facts and
  inspect summary left out (``null``; the section does not read them);
* ``planner.json`` -- ``GET /api/studies/{id}/planner`` (the study's noise, groups, plates);
* ``plan.json`` -- ``POST /api/studies/{id}/planner`` with the planner's defaults (a 2.5-fold
  change, above the 2-fold call line, 80 % power, the headline genes, the study's plate size);
* ``plan-fold3.json`` -- the same at a 3-fold change;
* ``layout.json`` -- ``POST /api/studies/{id}/planner/layout`` for 6 per group of the headline genes
  on 96-well plates, seed 1 (small enough to keep).
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def call(port: int, path: str, body: object | None = None) -> object:
    """GET (or POST ``body``) one API path with the dev launch key."""
    origin = f"http://127.0.0.1:{port}"
    request = urllib.request.Request(
        origin + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={
            "x-qpilot-token": os.environ.get("QPILOT_APP_TOKEN", "qpilot-dev"),
            "content-type": "application/json",
            "origin": origin,
        },
        method="GET" if body is None else "POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310 (local server)
        return json.loads(response.read())


def main() -> None:
    """Record every view the planner reads."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=int(os.environ.get("APP_PORT", "7860")))
    parser.add_argument("--session", required=True, help="the session id (12 hex)")
    args = parser.parse_args()
    session = call(args.port, f"/api/sessions/{args.session}")
    assert isinstance(session, dict)
    session["facts"] = None
    session["summary"] = None
    study = session["study_id"]
    planner = call(args.port, f"/api/studies/{study}/planner")
    assert isinstance(planner, dict)
    defaults = planner["defaults"]
    views = {
        "session.json": session,
        "planner.json": planner,
        "plan.json": call(args.port, f"/api/studies/{study}/planner", defaults),
        "plan-fold3.json": call(
            args.port, f"/api/studies/{study}/planner", {**defaults, "fold": 3}
        ),
        "layout.json": call(
            args.port,
            f"/api/studies/{study}/planner/layout",
            {"n_per_group": 6, "genes": planner["headline"], "wells_per_plate": 96, "seed": 1},
        ),
    }
    for name, view in views.items():
        (HERE / name).write_text(json.dumps(view, indent=1, ensure_ascii=False) + "\n")
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
