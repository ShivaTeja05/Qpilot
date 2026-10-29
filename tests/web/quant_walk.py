"""A real lab's absolute-quantification plate walked through the page's own routes.

The QuantStudio 3 (Design & Analysis 2.7) export of an airplane-wastewater run (corpus
``thermofisher/securebio-qs3-design-analysis-2.7``): SARS-CoV-2 (Cov2, FAM) and the faecal
normaliser PMMoV (VIC) in triplicate, five standards named ``Std 1`` … ``Std 5`` with no
quantity in the export, NTCs. A person, on the Design page (``POST …/design/set``, no model):
PMMoV is the reference gene and Cov2 the gene of interest; the standards are a ten-fold series
from 100,000 copies (the person's input: the export does not carry it); the airplane samples of
two sites over five days are the groups (DNI vs DSI); the comparison DNI vs DSI. Then the curves
are confirmed and the study is analysed: Results show Cov2/PMMoV and the Quantities view the
copies of every sample. ``walk(client)`` works on a TestClient or on ``requests`` against
``qpilot app`` (``record_quantities.py``).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"
QS3 = CORPUS / "thermofisher" / "securebio-qs3-design-analysis-2.7"
TOP, STEP = 100_000.0, 10.0  # the person's series: Std 1 = 1e5 copies, ten-fold
REASON = "plate map and standard series from the lab notebook"


def _ok(r: Any, code: int = 200) -> Any:
    assert r.status_code == code, (r.status_code, r.text[:500])
    return r.json()


def _job(client: Any, job: dict, timeout: float = 600.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        view = client.get(f"/api/jobs/{job['id']}").json()
        if view["status"] in ("done", "failed"):
            assert view["status"] == "done", view
            return view
        assert time.monotonic() < deadline, view
        time.sleep(0.1)


def files() -> list[Path]:
    return sorted(QS3.glob("*.csv"))


def walk(client: Any) -> dict[str, str]:
    """Open, design, confirm and analyse; returns ``{"sid", "study"}``."""
    parts = [("files", (p.name, p.read_bytes(), "text/csv")) for p in files()]
    sid = _job(client, _ok(client.post("/api/workspaces", files=parts), 202)["job"])["result"][
        "key"
    ]
    _job(client, _ok(client.post(f"/api/sessions/{sid}/propose/design", json={}), 202)["job"])
    view = _ok(client.get(f"/api/sessions/{sid}/design/editor"))
    names = {s["sample"] for s in view["samples"]}
    standards = sorted(n for n in names if n.startswith("Std "))
    series = {s: TOP / STEP**i for i, s in enumerate(standards)}
    groups = {
        n: site
        for n in names
        for site in ("DNI", "DSI")
        if n.startswith("PR-") and f"-{site}-" in n
    }
    items = [
        {"kind": "design.target_role", "subject": "PMMoV", "payload": {"role": "ref"}},
        {"kind": "design.target_role", "subject": "Cov2", "payload": {"role": "toi"}},
        {
            "kind": "design.dilution_series",
            "subject": "STD",
            "payload": {"experiment_id": view["experiments"][0], "samples": series},
        },
        *[
            {"kind": "design.group", "subject": n, "payload": {"group": g}}
            for n, g in sorted(groups.items())
        ],
        {"kind": "design.comparison", "subject": "comparison",
         "payload": {"group_a": "DNI", "group_b": "DSI"}},
    ]  # fmt: skip
    body = {"items": items, "reason": REASON, "expected_head": view["head"],
            "accept_contradicted": False}  # fmt: skip
    _ok(client.post(f"/api/sessions/{sid}/design/set", json=body))
    _settle(client, sid, "design")
    _confirm(client, sid, "design")
    _job(client, _ok(client.post(f"/api/sessions/{sid}/propose/curves", json={}), 202)["job"])
    _settle(client, sid, "curves")
    _confirm(client, sid, "curves")
    study = _study(client, sid)
    return {"sid": sid, "study": study}


def _settle(client: Any, sid: str, stage: str) -> None:
    """Accept what the rules proposed for the stage (a person reading each, as on the page)."""
    for _ in range(5):
        listed = _ok(client.get(f"/api/sessions/{sid}/proposals", params={"stage": stage}))
        waiting = [p for p in listed["proposals"] if p["status"] == "proposed"]
        if not waiting:
            return
        p = waiting[0]
        head = listed.get("head")
        r = client.post(
            f"/api/sessions/{sid}/proposals/{p['id']}/accept",
            json={"reason": "checked against the plate map", "expected_head": head},
        )
        if r.status_code != 200:  # a contradicted proposal: reject it with the reason
            client.post(
                f"/api/sessions/{sid}/proposals/{p['id']}/reject",
                json={"reason": "not what the plate map says", "expected_head": head},
            )


def _confirm(client: Any, sid: str, stage: str) -> None:
    shown = _ok(client.post(f"/api/sessions/{sid}/confirm/{stage}"))
    assert shown["ready"], shown
    _ok(client.post(
        f"/api/sessions/{sid}/confirm/{stage}/accept",
        json={"proposal_id": shown["proposal"]["id"], "expected_head": shown["head"]},
    ))  # fmt: skip


def _study(client: Any, sid: str, timeout: float = 600.0) -> str:
    deadline = time.monotonic() + timeout
    while True:
        spaces = _ok(client.get("/api/workspaces"))
        rows = spaces if isinstance(spaces, list) else spaces.get("workspaces", [])
        mine = next((w for w in rows if w.get("key") == sid), None)
        if mine and mine.get("study_id") and mine.get("results_visible"):
            r = client.get(f"/api/studies/{mine['study_id']}/results")
            if r.status_code == 200:
                return str(mine["study_id"])
        assert time.monotonic() < deadline, mine
        time.sleep(0.5)
