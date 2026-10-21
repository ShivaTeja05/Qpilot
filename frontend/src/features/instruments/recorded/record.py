"""Record real JSON for the Instruments section's tests from a running `qpilot app` (not typed).

Start the server on a copy of the seeded demo store whose instrument registry is empty, then, from
the repository root (with the store's folder in ``$QPILOT_STUDIES_DIR``):

    qpilot app --no-open --port 7896 &
    python frontend/src/features/instruments/recorded/record.py --port 7896

It registers two instruments, logs what a person would log (a calibration, a service visit, a
note whose text holds markup), has an *agent* propose two incidents through the logbook's own
Python API (as ``qpilot serve`` would), confirms one as a person, logs and fixes an incident a
person saw, reads two run files (the synthetic QuantStudio ``.eds`` with an expired calibration
and a pause, and a public Bio-Rad CFX "Run Information" export), links the ``.eds``, and runs a
lookback over the demo study. It writes, next to this file, exactly what the page reads:

* ``workspaces.json`` -- ``GET /api/workspaces`` (the lookback's study picker);
* ``instruments.json`` -- ``GET /api/instruments`` at the end;
* ``instrument.json`` -- ``GET /api/instruments/{id}`` of the QuantStudio at the end: one incident
  an agent proposed (waiting), one confirmed and open, one fixed, and the logbook;
* ``register.json`` -- ``POST /api/instruments`` (the CFX, with an id given);
* ``event-logged.json`` / ``confirmed.json`` / ``incident-logged.json`` / ``fixed.json`` -- the
  answers of the logbook writes;
* ``run-unknown.json`` -- ``POST /api/instruments/runs`` of the ``.eds`` before it is linked
  (it names no registered instrument, so the server asks which one it is);
* ``linked.json`` -- ``POST /api/instruments/runs/{run_id}/link``;
* ``run-known.json`` -- the same file read again once linked;
* ``run-cfx.json`` -- the CFX export (a serial the registry does not know);
* ``never.json`` -- the serial numbers the two files carry, read locally from each file's own
  ``summary()`` (the test checks that none of them is ever on the page);
* ``lookback-started.json`` / ``lookback-job.json`` -- ``POST /api/studies/{id}/lookback`` (3 Mar
  2008, the method card's window that changes calls) and its finished job;
* ``broken.json`` / ``broken-one.json`` -- ``GET /api/instruments`` and ``/{id}`` while one line of
  the CFX's logbook is altered on disk (the bytes are put back right after); the one instrument
  answers with a refusal, kept as ``{"status", "body"}``.

Run it on a fresh copy of the store: it registers and logs again on every run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
CFX_RUN = (
    ROOT
    / "tests/fixtures/corpus/biorad/hsieh2016-cfx-manager-3.1-sybr"
    / "2016-09-04 gapdh_Run Information.csv"
)
LOCAL_IDENTITY = ("serial", "block_serial", "cover_serial", "optical_head_serial", "shuttle_serial")


def call(
    port: int,
    path: str,
    body: object | None = None,
    *,
    raw: bytes | None = None,
    content_type: str = "application/json",
    refusal: bool = False,
) -> Any:
    """GET (or POST ``body`` as JSON, or ``raw`` bytes) one API path with the dev launch key.

    With ``refusal``, an error answer is returned as ``{"status", "body"}`` instead of stopping.
    """
    origin = f"http://127.0.0.1:{port}"
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    request = urllib.request.Request(
        origin + path,
        data=data,
        headers={
            "x-qpilot-token": os.environ.get("QPILOT_APP_TOKEN", "qpilot-dev"),
            "content-type": content_type,
            "origin": origin,
        },
        method="GET" if data is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310 (local server)
            return json.loads(response.read())
    except urllib.error.HTTPError as err:
        if refusal:
            return {"status": err.code, "body": json.loads(err.read())}
        raise SystemExit(f"{path}: {err.code} {err.read().decode(errors='replace')}") from None


def upload(port: int, path: Path) -> Any:
    """``POST /api/instruments/runs`` with the file in the multipart field ``run``."""
    boundary = uuid.uuid4().hex
    head = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="run"; filename="{path.name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    return call(
        port,
        "/api/instruments/runs",
        raw=head + path.read_bytes() + tail,
        content_type=f"multipart/form-data; boundary={boundary}",
    )


def wait_job(port: int, job_id: str) -> Any:
    """Poll a job until it is done or failed."""
    for _ in range(600):
        job = call(port, f"/api/jobs/{job_id}")
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.5)
    raise SystemExit(f"job {job_id} did not finish")


def register(port: int, body: dict[str, Any]) -> dict[str, Any]:
    """Register an instrument, or read it when a previous run registered it."""
    have = {
        i["display_name"]: i["instrument_id"] for i in call(port, "/api/instruments")["instruments"]
    }
    if body["display_name"] in have:
        return call(port, f"/api/instruments/{have[body['display_name']]}")
    return call(port, "/api/instruments", body)


def serials_of(path: Path) -> list[str]:
    """The serial numbers a run file carries (read locally; they must never reach the page)."""
    from qpilot.qpcr.instrument_context import read_run_context

    summary = read_run_context(path).summary()
    return sorted({str(summary[k]) for k in LOCAL_IDENTITY if summary.get(k)})


def main() -> None:
    """Write every view and answer the Instruments section reads."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=int(os.environ.get("APP_PORT", "7860")))
    parser.add_argument(
        "--store", default=os.environ.get("QPILOT_STUDIES_DIR"), help="the server's studies folder"
    )
    args = parser.parse_args()
    if not args.store:
        raise SystemExit("--store (or $QPILOT_STUDIES_DIR) is the folder the server reads")
    sys.path.insert(0, str(ROOT))
    from qpilot.core.instruments import Registry, log_incident
    from qpilot.core.store import sha256_file
    from tests.engine.instrument_files import qs_v1_expired

    port = args.port
    out: dict[str, Any] = {}
    workspaces = call(port, "/api/workspaces")
    out["workspaces.json"] = workspaces
    study = next(
        w["study_id"] for w in workspaces["workspaces"] if w["results_visible"] and w["study_id"]
    )

    qs = register(
        port,
        {
            "display_name": "QuantStudio 5, bench 2",
            "make_model": "Applied Biosystems QuantStudio 5",
            "location": "Lab 2.14, by the window",
            "shared": True,
        },
    )["instrument"]["instrument_id"]
    out["register.json"] = cfx_view = register(
        port,
        {
            "display_name": "CFX96 in the core facility",
            "instrument_id": "cfx96-core",
            "make_model": "Bio-Rad CFX96",
            "location": "Core facility, room 0.08",
            "shared": False,
        },
    )
    cfx = cfx_view["instrument"]["instrument_id"]

    base = f"/api/instruments/{qs}"
    call(
        port,
        f"{base}/events",
        {
            "kind": "calibration",
            "calibration_type": "background",
            "at": "2025-08-28",
            "note": "Background and ROI by the engineer.",
        },
    )
    call(
        port,
        f"{base}/events",
        {"kind": "service", "at": "2025-08-28", "note": "Annual service visit; block cleaned."},
    )
    out["event-logged.json"] = call(
        port,
        f"{base}/events",
        {
            "kind": "note",
            "note": 'Plate holder pushed back <b>flush</b> & re-seated; see <a href="#">manual</a>',
        },
    )
    call(
        port,
        f"/api/instruments/{cfx}/events",
        {"kind": "move", "at": "2026-01-12", "note": "Moved from room 1.20 to the core."},
    )

    with tempfile.TemporaryDirectory() as tmp:
        eds = qs_v1_expired(Path(tmp) / "qs5-2019-05-10.eds")
        never = serials_of(eds) + serials_of(CFX_RUN)
        out["run-unknown.json"] = run = upload(port, eds)
        out["linked.json"] = call(
            port, f"/api/instruments/runs/{run['run_id']}/link", {"instrument_id": qs}
        )
        out["run-known.json"] = upload(port, eds)
        run_hash = sha256_file(eds)
    out["run-cfx.json"] = upload(port, CFX_RUN)
    out["never.json"] = {"serials": never}

    # An agent proposes two incidents, as `qpilot serve` would (the page cannot write as an agent).
    book = Registry(Path(args.store) / "instruments").logbook(qs)
    late = log_incident(
        book,
        actor="agent",
        wells=["B3", "B4"],
        signature={"metric": "cq_residual", "direction": "high"},
        run_hash=run_hash,
        note="B3 and B4 ran late on three plates in a row <i>after the pause</i>.",
    )
    low = log_incident(
        book,
        actor="agent",
        wells=["H12"],
        signature={"metric": "plateau", "direction": "low"},
        run_hash=run_hash,
        note="H12's plateau is low next to its replicates.",
    )
    assert late.seq != low.seq
    out["confirmed.json"] = call(port, f"{base}/incidents/{low.seq}/confirm", {})
    out["incident-logged.json"] = seen = call(
        port,
        f"{base}/incidents",
        {
            "wells": ["A1", "A2"],
            "metric": "plateau",
            "direction": "low",
            "note": "Edge wells low after the lid was opened.",
        },
    )
    out["fixed.json"] = call(
        port, f"{base}/incidents/{seen['seq']}/fix", {"note": "Lid gasket replaced."}
    )
    out["instrument.json"] = call(port, base)

    started = call(
        port,
        f"/api/studies/{study}/lookback",
        {"instrument_id": qs, "start": "2008-03-03", "end": "2008-03-03"},
    )
    out["lookback-started.json"] = started
    out["lookback-job.json"] = wait_job(port, started["job"]["id"])

    # A logbook line altered on disk: the chain no longer verifies (the bytes are put back).
    log = Path(args.store) / "instruments" / "logbook" / f"{cfx}.jsonl"
    original = log.read_bytes()
    try:
        log.write_bytes(original.replace(b"room 1.20", b"room 1.21", 1))
        out["broken.json"] = call(port, "/api/instruments")
        out["broken-one.json"] = call(port, f"/api/instruments/{cfx}", refusal=True)
    finally:
        log.write_bytes(original)
    out["instruments.json"] = call(port, "/api/instruments")

    for serial in never:  # the server never sends a serial; a recording that holds one is wrong
        leaked = [n for n, v in out.items() if n != "never.json" and serial in json.dumps(v)]
        assert not leaked, f"a serial number is in {leaked}"
    for name, view in out.items():
        (HERE / name).write_text(json.dumps(view, indent=1, ensure_ascii=False) + "\n")
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
