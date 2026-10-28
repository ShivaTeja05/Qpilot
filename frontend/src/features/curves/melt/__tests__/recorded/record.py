"""Record the melt route's own answers for the melt panel's tests (no hand-typed numbers).

Run from the repository root:

    python frontend/src/features/curves/melt/__tests__/recorded/record.py

It asks the real route (an in-process server over a throwaway store) and writes, next to this
file, exactly what it answers:

* ``melt-lc96-plate.json`` / ``melt-lc96-wells.json`` -- ``GET /api/sessions/{sid}/melt`` for
  the corpus's LightCycler 96 file (``rdml/lightcycler96-lc96p-hmuy``) opened with the
  depositors' groups and its design confirmed: the plate's three assays, and wells A1-A3 (hmuY,
  one product each);
* ``melt-rpa-wells.json`` -- the same for the corpus's CFX RDML with ten SYBR assays on one
  plate (``rdml/cfx-manager-3.0-rdml-1.2-rpa``), its design confirmed with two groups (the file
  has three samples; a design needs a comparison to be confirmed, and no melt call reads it):
  wells A4 (HoxB1P1, an extra peak), F4 and F6 (HoxB9P4, no product at the expected
  temperature);
* ``melt-none.json`` -- ``GET /api/studies/{id}/melt`` for the Studio tests' mini file, which
  has no melt curves;
* ``gate-lc96.json`` -- ``GET /api/studies/{id}/gate`` for the LightCycler 96 study (its design
  and curves confirmed): G-MELT's checks with the rest of the pack.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[6]
TOKEN = "record"
BASE = "http://127.0.0.1:7860"
RPA = ROOT / "tests/fixtures/corpus/rdml/cfx-manager-3.0-rdml-1.2-rpa/rpa.rdml"
RPA_SHEET = "Sample,Group\nR-HCtrl13,Control\nR-MoH9,Mutant\nR-dsH18,Mutant\n"


def write(name: str, body: dict) -> None:
    """Write ``body`` next to this file as compact, key-sorted JSON."""
    text = json.dumps(body, sort_keys=True, separators=(",", ":"))
    (HERE / name).write_text(text + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {name} ({len(text):,} bytes)")


def get(client, url: str) -> dict:
    """GET ``url``, asking again while a job works (409 loading)."""
    for _ in range(1200):
        r = client.get(url)
        if r.status_code != 409 or r.json()["error"]["code"] != "loading":
            r.raise_for_status()
            return r.json()
        time.sleep(0.1)
    raise RuntimeError(f"{url} kept loading")


def confirm_design(studio, sid: str, roles: dict[str, str] | None = None) -> None:
    """Accept the sheet's design, set the targets' ``roles``, compare two groups, confirm."""
    from qpilot.mcp_server import QpilotTools

    studio.propose_design(sid)
    for p in studio.inbox(sid, "design", "proposed"):
        studio.accept(sid, p.id, "human", "as the sample sheet says")
    for target, role in (roles or {}).items():
        QpilotTools(studio.store).qpcr_propose(sid, "design.target_role", target, {"role": role})
    for p in studio.inbox(sid, "design", "proposed"):
        studio.accept(sid, p.id, "human", "the reference and the genes studied")
    comparison = studio.propose_comparison(sid)
    if comparison is not None:  # three samples in three groups have nothing to compare
        studio.accept(sid, comparison.proposal.id, "human", "the first group is the reference")
    confirm = studio.propose_confirm(sid, "design")
    studio.accept(sid, confirm.proposal.id, "human")


def main() -> None:
    """Open the files as a person would and record each answer."""
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient

    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.core.store import StudyStore
    from qpilot.studio_service import Studio
    from qpilot.web.context import make_context
    from qpilot.web.server import create_app
    from tests.web.conftest import wait_job, walk_mini
    from tests.web.test_melt_routes import EMPTY, HMUY, LC96P, SHEET
    from tests.web.test_workspaces_capture import drop

    base = Path(tempfile.mkdtemp())
    store = StudyStore(base / "studies")
    studio = Studio(store, client=ModelClient(backend=NoneBackend()))
    ctx = make_context(store, studio, token=TOKEN, watch=False)
    with TestClient(create_app(ctx), base_url=BASE) as c:
        c.headers["x-qpilot-token"] = TOKEN
        c.headers["origin"] = BASE

        def opened(path: Path, sheet: str) -> str:
            r = drop(c, [path], extra=[("samples.csv", sheet.encode(), "text/csv")])
            r.raise_for_status()
            return wait_job(c, r.json()["job"])["result"]["key"]

        sid = opened(LC96P, SHEET)
        confirm_design(studio, sid, {HMUY: "toi", EMPTY: "toi"})
        write("melt-lc96-plate.json", get(c, f"/api/sessions/{sid}/melt"))
        write("melt-lc96-wells.json", get(c, f"/api/sessions/{sid}/melt?wells=A1,A2,A3"))
        studio.propose_curves(sid)
        for p in studio.inbox(sid, "curves", "proposed"):
            studio.accept(sid, p.id, "human", "checked")
        confirm = studio.propose_confirm(sid, "curves")
        studio.accept(sid, confirm.proposal.id, "human")
        write("gate-lc96.json", get(c, f"/api/studies/{studio.study(sid)}/gate"))

        rpa = opened(RPA, RPA_SHEET)
        confirm_design(studio, rpa, {"GusBP1": "ref", "ActBP1": "ref"})
        write("melt-rpa-wells.json", get(c, f"/api/sessions/{rpa}/melt?wells=A4,F4,F6"))

        root = base / "data"
        root.mkdir()
        from tests.fixtures.studio.studio_mini import write_studio_mini

        _, mini = walk_mini(studio, write_studio_mini(root / "mini.rdml"))
        write("melt-none.json", get(c, f"/api/studies/{mini}/melt"))
    ctx.close()


if __name__ == "__main__":
    main()
