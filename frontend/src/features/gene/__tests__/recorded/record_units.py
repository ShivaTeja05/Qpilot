"""Record ``GET /api/studies/{id}/genes/{gene}/units`` for the Gene tests (no typed numbers).

Run from the repository root:

    python frontend/src/features/gene/__tests__/recorded/record_units.py

It analyses, in a throwaway store, the real triplicate plate of the corpus (LightCycler 96,
P. endodontalis hmuY / 16S rRNA, DIP against Hm: ``tests/integration/hmuy.py``) and, when the
demo dataset is cached, the demo study, and writes what the route answers (the service result as
JSON) next to this file:

* ``units-hmuy.json`` -- three units per group, three replicate wells each;
* ``units-ODC1.json`` -- the demo's ODC1: one well per unit, 347 units (a beeswarm).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    """Write the recordings."""
    from qpilot.core.store import StudyStore
    from qpilot.web.units_views import unit_values
    from tests.integration.hmuy import GENE, HMUY, hmuy_design

    def write(name: str, model) -> None:
        text = json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        (HERE / name).write_text(text + "\n")
        print(f"wrote {name} ({len(text):,} bytes)")

    with tempfile.TemporaryDirectory() as tmp:
        store = StudyStore(Path(tmp) / "studies")
        study_id = store.ensure_study(HMUY, design=hmuy_design())
        write("units-hmuy.json", unit_values(store, study_id, GENE))
        from tests.conftest import DEMO_RDML

        if DEMO_RDML.exists():
            demo = store.ensure_study(DEMO_RDML)
            write("units-ODC1.json", unit_values(store, demo, "ODC1"))


if __name__ == "__main__":
    main()
