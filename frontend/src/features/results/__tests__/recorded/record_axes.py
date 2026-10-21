"""Record the further-choices fixtures from a running ``qpilot app`` (see README.md here).

    python record_axes.py http://127.0.0.1:7896 bc1d233e3866 <this folder>

Walks "Also test efficiency models" through the page's own routes on the seeded demo session:
the results' ``axes`` before, the choices inbox with the rule's proposal, a person's acceptance
(``actor="human"``, set by the server), the analysis job, then the results' ``axes`` after.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

WAIT = ("warming", "loading")  # the server is reading the file or the study: ask again


def main(api: str, sid: str, out: Path) -> None:
    """Record the four fixtures into ``out``."""
    headers = {"x-qpilot-token": "qpilot-dev", "origin": api, "content-type": "application/json"}

    def call(method: str, path: str, body: Any = None) -> Any:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(api + path, data, headers, method=method)
        for _ in range(120):
            try:
                with urllib.request.urlopen(request) as answer:  # noqa: S310 (a local server)
                    return json.loads(answer.read())
            except urllib.error.HTTPError as err:
                error = json.loads(err.read())["error"]
                if err.code in (409, 503) and error["code"] in WAIT:
                    time.sleep(2)
                    continue
                raise RuntimeError(f"{method} {path}: {err.code} {error}") from err
        raise RuntimeError(f"{method} {path}: never ready")

    def write(name: str, data: Any) -> None:
        (out / name).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
        print("wrote", name)

    before = call("GET", f"/api/sessions/{sid}")["study_id"]
    axes = call("GET", f"/api/studies/{before}/results")["axes"]
    write("axes-off.json", {"study_id": before, "session": sid, "axes": axes})
    done = call("POST", f"/api/sessions/{sid}/propose/axis", {"axis": "efficiency", "on": True})
    inbox = call("GET", f"/api/sessions/{sid}/proposals?stage=choices")
    write("proposals-choices-pending.json", inbox)
    pid = done["outcome"]["proposal"]["id"]
    reason = "test the efficiency models before deciding the cards"
    accepted = call(
        "POST",
        f"/api/sessions/{sid}/proposals/{pid}/accept",
        {"reason": reason, "expected_head": inbox["head"]},
    )
    if accepted.get("job"):
        while (job := call("GET", f"/api/jobs/{accepted['job']['id']}"))["status"] not in (
            "done",
            "failed",
        ):
            time.sleep(1)
        assert job["status"] == "done", job
    after = call("GET", f"/api/sessions/{sid}")["study_id"]
    assert after and after != before, (before, after)
    axes = call("GET", f"/api/studies/{after}/results")["axes"]
    write("axes-swept.json", {"study_id": after, "session": sid, "axes": axes})
    write(
        "proposals-choices-decided.json",
        call("GET", f"/api/sessions/{sid}/proposals?stage=choices"),
    )


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], Path(sys.argv[3]))
