"""Record the API's own answers for the Gene section's tests (never hand-written numbers).

Run from the repository root, with the store holding the Studio walk of the demo study:

    python frontend/src/features/gene/__tests__/recorded/record.py --study e300000d4f9a

It writes, next to this file, what ``GET /api/studies/{id}/results`` and
``GET /api/studies/{id}/genes/{gene}`` answer (the routes return these service results as JSON):

* ``results-view.json`` -- :func:`qpilot.web.results_views.results_view`;
* ``gene-<GENE>.json`` -- :func:`qpilot.web.results_views.gene_view` for each gene named.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    """Write the recordings."""
    from qpilot.core.store import StudyStore
    from qpilot.web.results_views import gene_view, results_view

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True)
    parser.add_argument("--studies", default=os.environ.get("QPILOT_STUDIES_DIR"))
    parser.add_argument("--genes", nargs="+", default=["NM23A", "ODC1"])
    args = parser.parse_args()
    store = StudyStore(args.studies)
    study_id = args.study

    def write(name: str, model) -> None:
        text = json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        (HERE / name).write_text(text + "\n")
        print(f"wrote {name} ({len(text):,} bytes)")

    write("results-view.json", results_view(store, study_id))
    for gene in args.genes:
        write(f"gene-{gene}.json", gene_view(store, study_id, gene))


if __name__ == "__main__":
    main()
