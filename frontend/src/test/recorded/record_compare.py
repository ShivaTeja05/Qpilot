"""Record the comparison views of a synthetic three-group study (the real engine, no typing).

Run from the repository root:

    python frontend/src/test/recorded/record_compare.py

It analyses ``tests/fixtures/studio/compare_mini.py``'s file (Control, Drug A, Drug B; four
donors; ``DrugB_D4`` not measured for TP53) under its design (each drug vs Control, Holm) in a
throwaway store and writes, next to this file, the page's own views exactly as the API serves
them: ``api-comparisons.json`` (``GET /api/studies/{id}/comparisons``),
``api-results-compare.json`` (``/results``, the first comparison) and
``api-results-compare-b.json`` (``/results?comparison=drug_b_vs_control``).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]


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
    from qpilot.web.compare_views import comparisons_view
    from tests.fixtures.studio.compare_mini import design, write_compare_mini

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["QPILOT_CACHE_DIR"] = str(Path(tmp) / "cache")
        source = write_compare_mini(Path(tmp) / "compare_mini.rdml", missing_well=True)
        store = StudyStore(Path(tmp) / "studies")
        study = store.ensure_study(source, design())
        _write("api-comparisons.json", comparisons_view(store, study).model_dump(mode="json"))
        _write("api-results-compare.json", rv.results_view(store, study).model_dump(mode="json"))
        other = rv.results_view(store, study, comparison="drug_b_vs_control")
        _write("api-results-compare-b.json", other.model_dump(mode="json"))


if __name__ == "__main__":
    main()
