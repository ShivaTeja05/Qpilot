"""Record "Where to look" with an agent's request waiting at a place (never typed).

From the repository root, with the team's env sourced:

    python frontend/src/features/trace/__tests__/recorded/record_request.py

It walks the Studio tests' synthetic mini file (both knock-outs late on ``1-Mar`` and an early
no-template control on that plate, as ``tests/web/test_where_decide.py`` does) in a scratch
store, then, through qPilot's own MCP tool code (``QpilotTools.qpcr_request_set_aside``, an
agent), asks for the first place's value to be set aside, and records what the page reads
(``GET /api/studies/{id}/where-to-look?gene=1-Mar``, in process through the real app):

* ``where-gene-requested.json`` -- the trace with the agent's request waiting at the first place.

Nothing is set aside by the request; a person's Decide… answers it.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
GENE = "1-Mar"
REASON = "The no-template control on this plate amplified within five cycles of the knock-outs."


def main() -> None:
    """Walk the mini file, file the agent's request, write the page's answer."""
    from fastapi.testclient import TestClient

    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.core.store import StudyStore
    from qpilot.mcp_server import QpilotTools
    from qpilot.studio_service import Studio
    from qpilot.web.context import make_context
    from qpilot.web.server import create_app
    from tests.fixtures.studio import studio_mini
    from tests.web.conftest import BASE, TOKEN, wait_job, walk_mini

    base = Path(tempfile.mkdtemp(prefix="qpilot-record-request-"))
    root = base / "data"
    root.mkdir()
    os.environ["QPILOT_DATA_ROOTS"] = str(root)
    os.environ["QPILOT_STUDIES_DIR"] = str(base / "studies")
    os.environ["QPILOT_MODEL_PROVIDER"] = "none"
    plate = dict(studio_mini.PLATES[GENE])
    plate.update(NTC=[None, None, 30.5], KO_1=[28.0, 28.1, 27.9], KO_2=[28.2, 28.3, 28.1])
    studio_mini.PLATES[GENE] = plate
    rdml = studio_mini.write_studio_mini(root / "mini.rdml")
    store = StudyStore(base / "studies")
    studio = Studio(store, client=ModelClient(backend=NoneBackend()))
    _, study = walk_mini(studio, rdml)
    ctx = make_context(store, studio, token=TOKEN, watch=False)
    with TestClient(create_app(ctx), base_url=BASE) as client:
        client.headers.update({"x-qpilot-token": TOKEN, "origin": BASE})

        def where() -> dict:
            for _ in range(200):
                r = client.get(f"/api/studies/{study}/where-to-look", params={"gene": GENE})
                if r.status_code == 409 and r.json()["error"]["code"] == "loading":
                    wait_job(client, r.json()["error"]["details"]["job"])
                    continue
                assert r.status_code == 200, r.text
                return r.json()
            raise RuntimeError("never ready")

        first = where()["places"][0]
        asked = QpilotTools(store).qpcr_request_set_aside(
            study, first["card_id"], "set_aside_value", REASON, gene=GENE
        )
        assert asked["status"] == "pending_human", asked
        view = where()
        assert view["places"][0]["requests"], "the request is not shown"
        (HERE / "where-gene-requested.json").write_text(
            json.dumps(view, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
        print("wrote where-gene-requested.json")
    ctx.close()


if __name__ == "__main__":
    main()
