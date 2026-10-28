"""Record the Quantities view's API answers from a running ``qpilot app`` (no hand-written numbers).

Walks the QuantStudio 3 wastewater export through the page's own routes
(``tests/web/quant_walk.py``: a person sets the reference gene, the ten-fold standard series from
100,000 copies, the DNI/DSI groups and the comparison on the Design page, then both blind stages
are confirmed), then saves ``GET …/quantities``, ``GET …/quantities/Cov2`` and
``GET /api/tools/copies`` (1 ng of a 3,000 bp plasmid, a ten-fold series of four levels).

    python frontend/src/features/results/quantities/__tests__/recorded/record_quantities.py 7949
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT))

from tests.web.quant_walk import walk  # noqa: E402


def main(port: str) -> None:
    """Walk the export on the server at ``port`` and write the answers beside this file."""
    base = f"http://127.0.0.1:{port}"
    headers = {"x-qpilot-token": "qpilot-dev", "origin": base}
    out = Path(__file__).parent
    with httpx.Client(base_url=base, headers=headers, timeout=600) as c:
        study = walk(c)["study"]
        answers = {
            "quantities.json": c.get(f"/api/studies/{study}/quantities").json(),
            "quantities-cov2.json": c.get(f"/api/studies/{study}/quantities/Cov2").json(),
            "copies.json": c.get(
                "/api/tools/copies", params={"ng": 1, "length": 3000, "step": 10, "levels": 4}
            ).json(),
        }
    for name, data in answers.items():
        text = json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n"
        (out / name).write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main(sys.argv[1])
