"""Record the Evidence Ledger and a card opened from Trace from a running ``qpilot app``.

Start the server on a store that holds the Studio walk of the demo, open one place with
``frontend/src/features/trace/__tests__/recorded/record_where.py --open`` (a person's Decide…),
then, from the repository root:

    python frontend/src/features/results/__tests__/recorded/record_ledger.py \
        --port 7896 --study e300000d4f9a

It writes, next to this file, exactly what the page reads:

* ``evidence.json`` -- ``GET /api/studies/{id}/evidence`` (the Evidence Ledger);
* ``cards-trace.json`` -- ``GET /api/studies/{id}/cards`` with the card opened from Trace (its
  ``place`` set); each stored card's per-gene numbers under ``card.options[].per_gene`` are left
  out (``{}``: the page reads each option's ``effects`` instead).
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
WAIT = ("warming", "loading")


def call(port: int, path: str) -> Any:
    """GET one API path with the dev launch key, waiting out a first read of the study."""
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        headers={"x-qpilot-token": os.environ.get("QPILOT_APP_TOKEN", "qpilot-dev")},
    )
    for _ in range(150):
        try:
            with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310 (local)
                return json.loads(response.read())
        except urllib.error.HTTPError as err:
            error = json.loads(err.read()).get("error", {})
            if err.code in (409, 503) and error.get("code") in WAIT:
                time.sleep(2)
                continue
            raise RuntimeError(f"{path}: {err.code} {error}") from err
    raise RuntimeError(f"{path}: never ready")


def write(name: str, view: object) -> None:
    """Write one answer next to this file, as the server sent it."""
    (HERE / name).write_text(json.dumps(view, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {name}")


def main() -> None:
    """Record the ledger and the cards."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=int(os.environ.get("APP_PORT", "7860")))
    parser.add_argument("--study", required=True, help="the study id (12 hex)")
    args = parser.parse_args()
    evidence = call(args.port, f"/api/studies/{args.study}/evidence")
    assert evidence["available"], evidence.get("note")
    write("evidence.json", evidence)
    cards = call(args.port, f"/api/studies/{args.study}/cards")
    if not any(c.get("place") for c in cards["cards"]):
        raise SystemExit("No card opened from Trace yet: run record_where.py --open first.")
    for view in cards["cards"]:
        for option in view["card"].get("options") or ():
            option["per_gene"] = {}
    write("cards-trace.json", cards)


if __name__ == "__main__":
    main()
