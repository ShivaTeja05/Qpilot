"""Record real JSON for the Run Review's tests from a running `qpilot app` (never typed in).

Start the server on a copy of a store that holds the Studio walk of the demo, then, from the
repository root:

    qpilot app --no-open --port 7896 &
    python frontend/src/features/report/recorded/record.py --port 7896 --session bc1d233e3866

It writes two things to the server, both clearly a test: one sign-off sent with a chain head
that is not in the chain (the server answers ``409 stale`` and writes nothing to the chain; it
logs the attempt beside it), and one real sign-off (``discuss``, a comment that says it is a
test and holds markup, so the page's tests can check that it shows as text). Run it on a copy of
the store, never on a study you keep. It writes, next to this file:

* ``review.json`` -- ``GET /api/studies/{id}/review`` before the sign-off;
* ``review-stale.json`` -- the ``409 stale`` answer to a sign-off read at a head not in the chain
  (``{"status": 409, "body": {...}}``);
* ``review-signed.json`` -- the answer to the sign-off (``SignOffDone``);
* ``review-after.json`` -- ``GET /api/studies/{id}/review`` again, with the sign-off listed;
* ``session.json`` -- ``GET /api/sessions/{sid}`` (the workspace frame), with the file facts and
  inspect summary left out (``null``; the section does not read them);
* ``repeat.json`` -- ``GET /api/studies/{id}/review/repeat`` (what to repeat and why, the repeat
  plate, the Run Gate per plate; read-only, waiting out the first read of the Run Gate and
  Trace), with its items cut to the first 12 (``plan.items``; the counts stay the server's).
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
COMMENT = (
    "Recorded by the qPilot UI tests (not a real review): <b>markup</b> in a comment "
    "must show as text."
)
REVIEWER = "qPilot UI test recorder"
NOT_IN_CHAIN = "0" * 64


def call(port: int, path: str, body: object | None = None) -> tuple[int, object]:
    """GET (or POST ``body``) one API path with the dev launch key: ``(status, JSON)``."""
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
    try:
        with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310 (local)
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as err:  # a refusal is an answer too
        return err.code, json.loads(err.read())


def main() -> None:
    """Record the Run Review, a stale sign-off, one sign-off and the review after it."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=int(os.environ.get("APP_PORT", "7860")))
    parser.add_argument("--session", required=True, help="the session id (12 hex)")
    args = parser.parse_args()
    status, session = call(args.port, f"/api/sessions/{args.session}")
    assert status == 200 and isinstance(session, dict), session
    study = session["study_id"]
    route = f"/api/studies/{study}/review"
    status, review = call(args.port, route)
    assert status == 200 and isinstance(review, dict), review
    assert review["can_sign_off"], review["why_not"]
    sign = {"outcome": "discuss", "comment": COMMENT, "reviewer": REVIEWER}
    stale_status, stale = call(
        args.port, f"{route}/sign-off", {**sign, "expected_head": NOT_IN_CHAIN}
    )
    assert stale_status == 409, stale
    status, signed = call(args.port, f"{route}/sign-off", {**sign, "expected_head": review["head"]})
    assert status == 200, signed
    status, after = call(args.port, route)
    assert status == 200, after
    status, session = call(args.port, f"/api/sessions/{args.session}")
    assert status == 200 and isinstance(session, dict), session
    repeat: object = None
    for _ in range(300):  # the first read waits for the Run Gate and Trace (409 loading)
        status, repeat = call(args.port, f"/api/studies/{study}/review/repeat")
        if status != 409:
            break
        time.sleep(2)
    assert status == 200 and isinstance(repeat, dict), repeat
    repeat["plan"]["items"] = repeat["plan"]["items"][:12]
    session["facts"] = None
    session["summary"] = None
    views = {
        "review.json": review,
        "review-stale.json": {"status": stale_status, "body": stale},
        "review-signed.json": signed,
        "review-after.json": after,
        "session.json": session,
        "repeat.json": repeat,
    }
    for name, view in views.items():
        (HERE / name).write_text(json.dumps(view, indent=1, ensure_ascii=False) + "\n")
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
