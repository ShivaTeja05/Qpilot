"""Record the API's answers for a quantification run, as the page reads them.

Walks the QuantStudio 3 wastewater export through the page's own routes, in a fresh study store,
as a person would on the Design page with no model (purpose: quantify samples; the standards a
ten-fold series from 100,000 copies), confirms both blind stages, and saves what Results and the
Design editor read. The app is the one ``qpilot app`` serves, driven in-process::

    python frontend/src/features/results/quantities/__tests__/recorded/record_quantify.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[7]
sys.path.insert(0, str(ROOT))

HERE = Path(__file__).resolve().parent
EDITOR = ROOT / "frontend" / "src" / "features" / "design" / "recorded"
TOKEN = "record-token"


def save(path: Path, data: object) -> None:
    """Write one answer as the page receives it (JSON, LF)."""
    text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    """Walk the export and save each answer."""
    os.environ["QPILOT_MODEL_PROVIDER"] = "none"
    from fastapi.testclient import TestClient

    from qpilot.core.store import StudyStore
    from qpilot.web.context import make_context
    from qpilot.web.server import create_app
    from tests.web import quantify_walk as qw

    with tempfile.TemporaryDirectory() as tmp:
        ctx = make_context(StudyStore(Path(tmp) / "studies"), token=TOKEN, watch=False)
        with TestClient(create_app(ctx), base_url="http://127.0.0.1:7860") as c:
            c.headers["x-qpilot-token"] = TOKEN
            sid = qw.open_qs3(c)
            qw._set(c, sid, qw.qs3_items(c, sid), "standards from the lab notebook")
            save(
                EDITOR / "editor-quantify.json", c.get(f"/api/sessions/{sid}/design/editor").json()
            )
            study = qw.finish(c, sid)["study"]
            save(
                HERE / "quantify-quantities.json", c.get(f"/api/studies/{study}/quantities").json()
            )
            save(HERE / "quantify-cov2.json", c.get(f"/api/studies/{study}/quantities/Cov2").json())
            save(HERE / "quantify-cards.json", c.get(f"/api/studies/{study}/cards").json())
            frame = c.get(f"/api/sessions/{sid}").json()
            frame.pop("summary", None)
            save(HERE / "quantify-frame.json", frame)
        ctx.close()


if __name__ == "__main__":
    main()
