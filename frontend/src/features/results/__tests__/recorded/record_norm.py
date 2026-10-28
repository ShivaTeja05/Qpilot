"""Record the normaliser fixtures from a running ``qpilot app`` (see README.md here).

    python record_norm.py http://127.0.0.1:7896 bc1d233e3866 <this folder>

Walks "Also test other normalisers" through the page's own routes on the seeded demo session:
the reference panel (geNorm and NormFinder side by side), the results' ``axes`` before, the
choices inbox with the rule's proposal, a person's acceptance (``actor="human"``, set by the
server), the analysis job, then the results' ``axes`` and the normaliser card after.
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
    """Record the fixtures into ``out``."""
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
        text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
        (out / name).write_text(text, encoding="utf-8", newline="\n")
        print("wrote", name)

    for _ in range(120):  # a fresh store analyses the session's study first
        before = call("GET", f"/api/sessions/{sid}")["study_id"]
        if before:
            break
        time.sleep(2)
    write("references.json", call("GET", f"/api/studies/{before}/references"))
    axes = call("GET", f"/api/studies/{before}/results")["axes"]
    write("normaliser-off.json", {"study_id": before, "session": sid, "axes": axes})
    done = call("POST", f"/api/sessions/{sid}/propose/axis", {"axis": "normaliser", "on": True})
    inbox = call("GET", f"/api/sessions/{sid}/proposals?stage=choices")
    write("proposals-normaliser-pending.json", inbox)
    pid = done["outcome"]["proposal"]["id"]
    reason = "test NormFinder's pair and the global mean before deciding the cards"
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
    write("normaliser-swept.json", {"study_id": after, "session": sid, "axes": axes})
    cards = call("GET", f"/api/studies/{after}/cards")
    card = next(c for c in cards["cards"] if c["card"]["kind"] == "numbers.normaliser")
    for option in card["card"].get("options", []):
        option["per_gene"] = {}  # large and not read by the panel
    write("card-normaliser.json", card)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], Path(sys.argv[3]))
