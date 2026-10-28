"""Record real JSON for the Prism section's tests from a running `qpilot app` (never typed in).

Start the server on a store that holds the Studio walk of the demo, then, from the repository root:

    qpilot app --no-open --port 7886 &
    python frontend/src/features/prism/recorded/record.py --port 7886 --session bc1d233e3866

It writes, next to this file, exactly what the page reads:

* ``session.json`` -- ``GET /api/sessions/{sid}`` (the workspace frame: stages, study id), with
  the file facts and inspect summary left out (``null``; the section does not read them);
* ``proposals-prism.json`` / ``proposals-roundtrip.json`` -- ``GET /api/sessions/{sid}/proposals``;
* ``prism-status.json``, ``prism-routes.json``, ``prism-preview.json``, ``prism-bundles.json``
  -- the Prism routes.

With ``--send`` it also presses Send to Prism once (it writes a bundle into qPilot's export
folder, as the page's button does) and records the job's answer as ``sent.json``.

A route the server does not have (yet) is skipped with a note. The home folder in paths (the bundle
folders) is written as ``~`` so the recordings name no person's account.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def fetch(port: int, path: str) -> object | None:
    """GET one API path with the dev launch key; None when the route does not exist."""
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        headers={"x-qpilot-token": os.environ.get("QPILOT_APP_TOKEN", "qpilot-dev")},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310 (local server)
            return json.loads(response.read())
    except urllib.error.HTTPError as err:
        print(f"skip {path}: HTTP {err.code}")
        return None


def main() -> None:
    """Record every view the Prism section reads."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=int(os.environ.get("APP_PORT", "7860")))
    parser.add_argument("--session", required=True, help="the session id (12 hex)")
    parser.add_argument("--send", action="store_true", help="also record a Send to Prism answer")
    args = parser.parse_args()
    sid = args.session
    views = {
        "session.json": f"/api/sessions/{sid}",
        "proposals-prism.json": f"/api/sessions/{sid}/proposals?stage=prism",
        "proposals-roundtrip.json": f"/api/sessions/{sid}/proposals?stage=roundtrip",
        "prism-status.json": f"/api/sessions/{sid}/prism",
        "prism-routes.json": f"/api/sessions/{sid}/prism/routes",
        "prism-preview.json": f"/api/sessions/{sid}/prism/preview",
        "prism-bundles.json": f"/api/sessions/{sid}/prism/bundles",
    }
    for name, path in views.items():
        data = fetch(args.port, path)
        if name == "session.json" and isinstance(data, dict):
            data = {**data, "facts": None, "summary": None}
        if data is not None:
            text = json.dumps(data, indent=1, ensure_ascii=False).replace(str(Path.home()), "~")
            (HERE / name).write_text(text + "\n")
            print(f"wrote {name}")
    if args.send:
        result = send(args.port, sid)
        text = json.dumps(result, indent=1, ensure_ascii=False).replace(str(Path.home()), "~")
        (HERE / "sent.json").write_text(text + "\n")
        print("wrote sent.json")


def send(port: int, sid: str) -> object:
    """Press Send to Prism once and wait for the job's answer."""
    import time

    headers = {
        "x-qpilot-token": os.environ.get("QPILOT_APP_TOKEN", "qpilot-dev"),
        "origin": f"http://127.0.0.1:{port}",
    }
    base = f"http://127.0.0.1:{port}"
    request = urllib.request.Request(
        f"{base}/api/sessions/{sid}/prism/send", method="POST", headers=headers
    )
    with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310 (local server)
        job = json.loads(response.read())["job"]
    while True:
        view = fetch(port, f"/api/jobs/{job['id']}")
        if isinstance(view, dict) and view.get("status") in ("done", "failed"):
            return view.get("result")
        time.sleep(0.5)


if __name__ == "__main__":
    main()
