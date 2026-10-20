"""Record real JSON for the chart and screen tests from a study store (never hand-written numbers).

Run from the repository root, with the store holding the Studio walk of the demo and its audit:

    python frontend/src/test/recorded/record.py --study e300000d4f9a

It writes, next to this file:

* ``results.json`` -- the stored :class:`~qpilot.schemas.StudyResult` (``StudyStore.get``);
* ``cards.json`` -- the study's Decision Cards (``StudyStore.cards``);
* ``audit-*.json`` -- the robustness audit's views, from qsim's ``Screen`` built over the
  integration's prepared engine for the stored audit (``overview``, ``study_view``,
  ``how_view``, ``gene_card``, ``gene_analyses``, ``gene_effects``, ``gene_samples``,
  ``lab_parameters``, ``run_whatif``).

The page's API returns these same service results; the tests read them as the page would.
"""

from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent


def _screen(store, study_id: str, audit_dir: Path):
    """Qsim's results screen over a qPilot audit (the prepared engine, not the benchmark's)."""
    from qsim.app import Screen
    from qsim.data import BENCHMARK_NAME

    from qpilot.integration.simulator import load_analysis, prepare

    prepared = prepare(load_analysis(store, study_id))
    s = Screen.__new__(Screen)
    s.dir = audit_dir
    s.explain = json.loads((audit_dir / "explain.json").read_text())
    s.genes = pd.read_csv(audit_dir / "genes.csv").set_index("gene")
    s.issues = json.loads((audit_dir / "issues.json").read_text())
    s.summary = json.loads((audit_dir / "summary.json").read_text())
    flips = audit_dir / "one_sample_flips.csv"
    s.sample_flips = pd.read_csv(flips, dtype={"sample": str}) if flips.exists() else None
    s.source = (s.summary.get("source") or {}).get("name") or BENCHMARK_NAME
    s.engine = prepared.engine
    s.space = prepared.space
    s.rules = s.summary["verdicts"]["rules"]
    s.line = 2**s.engine.rule.min_log2fc
    s.alpha = s.engine.rule.alpha
    study = prepared.study
    marker = study.marker.split("(")[0]
    cut = s.space.decision("cut")
    s.group = f"{marker}-high"
    s.group_def = cut.options[cut.index(s.space.baseline["cut"])].label
    s.n_samples = s.summary["study"]["samples"]
    s._asker = None
    s._rdml = None
    s._engine_lock = threading.Lock()
    s._ask_lock = threading.Lock()
    s._asker_lock = threading.Lock()
    return s


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
