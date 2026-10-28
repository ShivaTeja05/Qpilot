"""Record real JSON for the exports' tests from a running `qpilot app` (never typed in).

Start the server on a copy of a store that holds the Studio walk of the demo, with one Decision
Card decided away from its recommended option (so both analyses exist), then, from the
repository root:

    qpilot app --no-open --port 7946 &
    python frontend/src/features/report/recorded/record_exports.py --port 7946 \
        --study e300000d4f9a --gene ODC1

It writes, next to this file:

* ``figure-info.json`` -- ``GET /api/studies/{id}/report/figure/info?gene=…`` (as decided);
* ``figure-info-recommended.json`` -- the same with ``basis=recommended``;
* ``export-csv.json`` -- the finished ``report.export`` job's result for ``{"format": "csv"}``
  (it writes one CSV zip into the store's export folder; run it on a copy of the store). The
  download's folder path is replaced by the file's name (it names this computer's folders).
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _call(base: str, token: str, method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method)
    request.add_header("x-qpilot-token", token)
    request.add_header("origin", base)
    if data is not None:
        request.add_header("content-type", "application/json")
    with urllib.request.urlopen(request, timeout=300) as answer:
        return json.loads(answer.read())


def _write(name: str, data: dict) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    (HERE / name).write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {name}")


def main() -> None:
    """Record the answers."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--study", required=True)
    parser.add_argument("--gene", required=True)
    args = parser.parse_args()
    base = f"http://127.0.0.1:{args.port}"
    token = os.environ.get("QPILOT_APP_TOKEN", "qpilot-dev")
    info = f"/api/studies/{args.study}/report/figure/info?"
    for name, basis in (("figure-info.json", "as_decided"),
                        ("figure-info-recommended.json", "recommended")):  # fmt: skip
        query = urllib.parse.urlencode({"gene": args.gene, "basis": basis})
        _write(name, _call(base, token, "GET", info + query))
    started = _call(base, token, "POST", f"/api/studies/{args.study}/report/export",
                    {"format": "csv"})  # fmt: skip
    job = started["job"]
    while job["status"] not in ("done", "failed"):
        time.sleep(1)
        job = _call(base, token, "GET", f"/api/jobs/{job['id']}")
    result = job["result"]
    result["download"]["path"] = result["download"]["name"]  # not this computer's folders
    _write("export-csv.json", result)


if __name__ == "__main__":
    main()
