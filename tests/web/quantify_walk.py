"""Two real labs' quantification runs walked to Results through the page's own routes.

A run that measures **how much** is there compares no groups, so its design says so: the study's
purpose is *quantify samples* (``design.purpose``), set by a person on the Design page (``POST
…/design/set``, no model). No comparison and no reference gene are needed; standards with a
quantity are.

* **StepOne** (corpus ``rdml/stepone-2.3-rdml-1.0``): RNase P, a five-level series whose
  quantities the RDML file declares, two populations as unknowns. The rules propose the purpose
  (a series of known quantity and no groups); the person accepts it.
* **QuantStudio 3** (``thermofisher/securebio-qs3-design-analysis-2.7``): airplane wastewater,
  SARS-CoV-2 (Cov2) and PMMoV, standards ``Std 1`` … ``Std 5`` with no quantity in the export.
  The person sets the purpose and the series (ten-fold from 100,000 copies, from the lab
  notebook) in one act.

Then the curves are confirmed and the study is analysed. ``walk_*(client)`` work on a TestClient
or on ``requests`` against ``qpilot app``.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from tests.web.quant_walk import _confirm, _job, _ok

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"
STEPONE = CORPUS / "rdml" / "stepone-2.3-rdml-1.0" / "stepone_std.rdml"
QS3 = CORPUS / "thermofisher" / "securebio-qs3-design-analysis-2.7"
TOP, STEP = 100_000.0, 10.0
REASON = "a quantification run: copies per reaction from the standard curve, no groups compared"


def _set(client: Any, sid: str, items: list[dict], reason: str = REASON) -> dict:
    view = _ok(client.get(f"/api/sessions/{sid}/design/editor"))
    body = {"items": items, "reason": reason, "expected_head": view["head"],
            "accept_contradicted": False}  # fmt: skip
    return _ok(client.post(f"/api/sessions/{sid}/design/set", json=body))


def _settle(client: Any, sid: str, stage: str) -> None:
    """Decide every waiting proposal of the stage (a person reading each, as on the page)."""
    for _ in range(200):
        listed = _ok(client.get(f"/api/sessions/{sid}/proposals", params={"stage": stage}))
        waiting = [p for p in listed["proposals"] if p["status"] == "proposed"]
        if not waiting:
            return
        p, head = waiting[0], listed.get("head")
        r = client.post(
            f"/api/sessions/{sid}/proposals/{p['id']}/accept",
            json={"reason": "checked against the plate map", "expected_head": head},
        )
        if r.status_code != 200:  # a contradicted proposal: reject it with the reason
            _ok(client.post(
                f"/api/sessions/{sid}/proposals/{p['id']}/reject",
                json={"reason": "not what the plate map says", "expected_head": head},
            ))  # fmt: skip
    raise AssertionError("the inbox did not settle")


def _study(client: Any, sid: str, timeout: float = 600.0) -> str:
    """Wait for the analysed study of the session; its Quantities answer."""
    deadline = time.monotonic() + timeout
    while True:
        view = _ok(client.get(f"/api/sessions/{sid}"))
        if view.get("study_id") and view.get("results_visible"):
            r = client.get(f"/api/studies/{view['study_id']}/quantities")
            if r.status_code == 200:
                return str(view["study_id"])
        assert time.monotonic() < deadline, view
        time.sleep(0.2)


def finish(client: Any, sid: str) -> dict[str, str]:
    """Settle the design inbox, confirm it, check and confirm the curves, wait for the study."""
    _settle(client, sid, "design")
    _confirm(client, sid, "design")
    _job(client, _ok(client.post(f"/api/sessions/{sid}/propose/curves", json={}), 202)["job"])
    _settle(client, sid, "curves")
    _confirm(client, sid, "curves")
    return {"sid": sid, "study": _study(client, sid)}


def open_stepone(client: Any) -> str:
    """Open the StepOne RDML file and ask the rules for the design; returns the session."""
    files = {"rdml": (STEPONE.name, STEPONE.read_bytes(), "application/xml")}
    opened = _ok(client.post("/api/workspaces", files=files), 202)
    sid = _job(client, opened["job"])["result"]["key"]
    _job(client, _ok(client.post(f"/api/sessions/{sid}/propose/design", json={}), 202)["job"])
    return sid


def walk_stepone(client: Any, sid: str | None = None) -> dict[str, str]:
    """StepOne: the rules' purpose proposal accepted by the person, then the curves."""
    sid = sid or open_stepone(client)
    listed = _ok(client.get(f"/api/sessions/{sid}/proposals", params={"stage": "design"}))
    purpose = next(
        p
        for p in listed["proposals"]
        if p["kind"] == "design.purpose" and p["status"] == "proposed"
    )
    _ok(client.post(
        f"/api/sessions/{sid}/proposals/{purpose['id']}/accept",
        json={"reason": REASON, "expected_head": listed["head"]},
    ))  # fmt: skip
    return finish(client, sid)


def open_qs3(client: Any) -> str:
    """Open the QuantStudio 3 export set and ask the rules for the design."""
    parts = [("files", (p.name, p.read_bytes(), "text/csv")) for p in sorted(QS3.glob("*.csv"))]
    opened = _ok(client.post("/api/workspaces", files=parts), 202)
    sid = _job(client, opened["job"])["result"]["key"]
    _job(client, _ok(client.post(f"/api/sessions/{sid}/propose/design", json={}), 202)["job"])
    return sid


def qs3_items(client: Any, sid: str) -> list[dict]:
    """The person's items: quantify samples, and the standards' ten-fold series."""
    view = _ok(client.get(f"/api/sessions/{sid}/design/editor"))
    names = sorted(s["sample"] for s in view["samples"] if s["sample"].startswith("Std "))
    series = {s: TOP / STEP**i for i, s in enumerate(names)}
    return [
        {"kind": "design.purpose", "subject": "purpose", "payload": {"purpose": "quantify"}},
        {
            "kind": "design.dilution_series",
            "subject": "STD",
            "payload": {"experiment_id": view["experiments"][0], "samples": series},
        },
    ]


def walk_qs3(client: Any, sid: str | None = None) -> dict[str, str]:
    """QuantStudio 3: the person sets the purpose and the series in one act."""
    sid = sid or open_qs3(client)
    _set(client, sid, qs3_items(client, sid), "standards from the lab notebook: 1e5 copies, x10")
    return finish(client, sid)
