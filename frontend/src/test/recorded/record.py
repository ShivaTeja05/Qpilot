"""Record real JSON for the chart and screen tests from a study store (never hand-written numbers).

Run from the repository root, with the store holding the Studio walk of the demo and its audit:

    python frontend/src/test/recorded/record.py --study e300000d4f9a

It writes, next to this file:

* ``results.json`` -- the stored :class:`~qpilot.schemas.StudyResult` (``StudyStore.get``);
* ``cards.json`` -- the study's Decision Cards (``StudyStore.cards``);
* ``api-results.json``, ``api-flips.json``, ``api-cards.json`` -- the page's own views of them,
  exactly as ``GET /api/studies/{id}/results|flips|cards`` serve them
  (``qpilot.web.results_views``);
* ``audit-*.json`` -- the robustness audit's views, from qsim's ``Screen`` built over the
  integration's prepared engine for the stored audit (``overview``, ``study_view``,
  ``how_view``, ``gene_card``, ``gene_analyses``, ``gene_effects``, ``gene_samples``,
  ``lab_parameters``, ``run_whatif``).

The page's API returns these same service results; the tests read them as the page would.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _screen(store, study_id: str, audit_dir: Path):
    """Qsim's results screen over a qPilot audit (the prepared engine, as the API builds it)."""
    from qsim.app import Screen

    from qpilot.integration.simulator import load_analysis, prepare

    return Screen.from_prepared(audit_dir, prepare(load_analysis(store, study_id)))


def _write(name: str, data) -> None:
    path = HERE / name
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str) + "\n")
    print(f"wrote {path.relative_to(HERE.parents[3])} ({path.stat().st_size:,} bytes)")


def main() -> None:
    """Record the views."""
    from qpilot.core.store import StudyStore

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--study", required=True)
    ap.add_argument("--genes", nargs="*", default=["ODC1", "NM23A"])
    ap.add_argument("--whatif", default="late_cq=cq35", help="decision=option[,decision=option]")
    args = ap.parse_args()

    store = StudyStore()
    result = store.get(args.study)
    _write("results.json", result.model_dump(mode="json"))
    _write("cards.json", [c.model_dump(mode="json") for c in store.cards(args.study)])
    from qpilot.web import results_views as rv

    session = rv.session_of_study(store, args.study)
    _write("api-results.json", rv.results_view(store, args.study, session).model_dump(mode="json"))
    _write("api-flips.json", rv.flips_view(store, args.study).model_dump(mode="json"))
    _write("api-cards.json", rv.cards_view(store, args.study).model_dump(mode="json"))

    audit_dir = store.root / "simulator_audits" / args.study
    if not (audit_dir / "explain.json").exists():
        hint = f"python -m qpilot.integration audit --study {args.study}"
        print(f"no audit at {audit_dir}: run `{hint}`")
        return
    s = _screen(store, args.study, audit_dir)
    _write("audit-overview.json", s.overview())
    _write("audit-study.json", s.study_view())
    _write("audit-how.json", s.how_view())
    for g in args.genes:
        _write(f"audit-gene-{g}.json", s.gene_card(g))
        _write(f"audit-analyses-{g}.json", s.gene_analyses(g))
        _write(f"audit-effects-{g}.json", s.gene_effects(g))
        _write(f"audit-samples-{g}.json", s.gene_samples(g))
        _write(f"audit-lab-{g}.json", s.lab_parameters(g))
    changes = dict(kv.split("=", 1) for kv in args.whatif.split(",") if kv)
    _write("audit-whatif.json", s.run_whatif(changes, list(args.genes)))


if __name__ == "__main__":
    main()
