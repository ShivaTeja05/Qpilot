"""Record the views of every section on a study with several comparisons (the real engine).

Run from the repository root:

    python frontend/src/test/recorded/record_compare2.py

It analyses ``tests/fixtures/studio/compare_mini.py``'s file with ACTB lowered by Drug B
(``ref_shift``: which control genes normalise then changes TP53's call in Drug B vs Control
only) under its design (each drug vs Control, Holm) in a throwaway store, asks the real routes
(an in-process server over that store) and writes, next to this file, exactly what they answer:

* ``api-cards-compare.json``: ``GET /api/studies/{id}/cards`` (a card that flips a call in the
  second comparison only);
* ``api-trace-compare-b.json``: ``GET /api/studies/{id}/trace/MYC?comparison=drug_b_vs_control``
  (the call with its corrected p, q and the p before correction);
* ``api-results-compare2.json``: ``GET /api/studies/{id}/results`` (the comparison tabs);
* ``api-units-compare-b.json``: ``GET /api/studies/{id}/genes/MYC/units?comparison=…``;
* ``api-history-compare-b.json``: ``GET /api/studies/{id}/history?comparison=…`` after a
  person's decision on the reference-set card;
* ``api-review-compare.json``: ``GET /api/studies/{id}/review`` (the comparisons named).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
SHIFT = {("ACTB", "Drug B"): 2.5}
B = "drug_b_vs_control"


def _write(name: str, data) -> None:
    path = HERE / name
    text = json.dumps(data, indent=1, ensure_ascii=False, default=str) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {path.relative_to(REPO)} ({path.stat().st_size:,} bytes)")


def main() -> None:
    """Record the views."""
    sys.path.insert(0, str(REPO))
    from fastapi.testclient import TestClient

    from qpilot.core.store import StudyStore
    from qpilot.web.context import make_context
    from qpilot.web.server import create_app
    from tests.fixtures.studio.compare_mini import design, write_compare_mini

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["QPILOT_CACHE_DIR"] = str(Path(tmp) / "cache")
        source = write_compare_mini(Path(tmp) / "shift.rdml", ref_shift=SHIFT)
        store = StudyStore(Path(tmp) / "studies")
        study = store.ensure_study(source, design())
        ctx = make_context(store, token="record", watch=False)
        base = "http://127.0.0.1:7860"
        try:
            with TestClient(create_app(ctx), base_url=base) as client:
                client.headers["x-qpilot-token"] = "record"
                client.headers["origin"] = base

                def get(url: str, **params) -> dict:
                    for _ in range(600):
                        r = client.get(url, params=params)
                        if r.status_code != 409 or r.json()["error"]["code"] != "loading":
                            r.raise_for_status()
                            return r.json()
                        time.sleep(0.1)
                    raise RuntimeError(f"{url} kept loading")

                api = f"/api/studies/{study}"
                _write("api-cards-compare.json", get(f"{api}/cards"))
                _write("api-results-compare2.json", get(f"{api}/results"))
                _write("api-trace-compare-b.json", get(f"{api}/trace/MYC", comparison=B))
                _write("api-units-compare-b.json", get(f"{api}/genes/MYC/units", comparison=B))
                _write("api-review-compare.json", get(f"{api}/review"))
                head = store.chain_head(study)
                r = client.post(
                    f"{api}/cards/card_refset/decide",
                    json={
                        "option": "actb_alone",
                        "reason": "our lab's reference",
                        "expected_head": head,
                    },
                )
                r.raise_for_status()
                _write("api-history-compare-b.json", get(f"{api}/history", comparison=B))
        finally:
            ctx.close()


if __name__ == "__main__":
    main()
