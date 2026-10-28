"""Record the views of every section on a study with several comparisons (the real engine).

Run from the repository root:

    python frontend/src/test/recorded/record_compare2.py

It analyses ``tests/fixtures/studio/compare_mini.py``'s file with ACTB lowered by Drug B
(``ref_shift``: which control genes normalise then changes TP53's call in Drug B vs Control
only) under its design (each drug vs Control, Holm) in a throwaway store and writes, next to
this file, the page's own views exactly as the API serves them:

* ``api-cards-compare.json``: ``GET /api/studies/{id}/cards`` (a card that flips a call in the
  second comparison only).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
SHIFT = {("ACTB", "Drug B"): 2.5}


def _write(name: str, data) -> None:
    path = HERE / name
    text = json.dumps(data, indent=1, ensure_ascii=False, default=str) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {path.relative_to(REPO)} ({path.stat().st_size:,} bytes)")


def main() -> None:
    """Record the views."""
    sys.path.insert(0, str(REPO))
    from qpilot.core.store import StudyStore
    from qpilot.web import results_views as rv
    from tests.fixtures.studio.compare_mini import design, write_compare_mini

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["QPILOT_CACHE_DIR"] = str(Path(tmp) / "cache")
        source = write_compare_mini(Path(tmp) / "shift.rdml", ref_shift=SHIFT)
        store = StudyStore(Path(tmp) / "studies")
        study = store.ensure_study(source, design())
        _write("api-cards-compare.json", rv.cards_view(store, study).model_dump(mode="json"))


if __name__ == "__main__":
    main()
