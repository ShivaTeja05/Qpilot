"""qPilot's robustness grid and the simulator agree on every analysis both can run.

qPilot's Studio grid varies the control genes, the cut-off, the empty-well rule and the
amplification-call rule (744 analyses on the demo). The simulator varies eight decisions; with
its other five at their prespecified options, the same analyses are a slice of its grid. Each
gene's fold change and conclusion must be the same in both, before and after a person's
exclusion in Prism. ``cq_le_40`` has no simulator counterpart and is left out.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qpilot.integration import simulator as sim

pytestmark = pytest.mark.demo_data

LATE = {"linregpcr": "none", "cq_le_35": "cq35", "cq_le_38": "cq38"}
NONDETECT = {"drop": "drop", "cap": "cap_min"}


def _refs(value: str) -> frozenset[str]:
    """``grid.csv`` writes a control-gene set as its genes joined by ``|``."""
    return frozenset(str(value).split("|"))


def _compare(store, study_id: str) -> tuple[int, int]:
    from qsim.engine import CALL_NAMES

    prepared = sim.prepare(sim.load_analysis(store, study_id))
    engine, space = prepared.engine, prepared.space
    grid = pd.read_csv(store.workspace(study_id) / "grid.csv")
    refs = {frozenset(o.value): o.id for o in space.decision("refs").options}
    cuts = {o.value: o.id for o in space.decision("cut").options}
    items = list(engine.items)
    compared = cells = 0
    keys = ["refs", "cut", "undetermined"] + (["amp_call"] if "amp_call" in grid else [])
    for key, rows in grid.groupby(keys):
        values = dict(zip(keys, key, strict=True))
        amp = values.get("amp_call", "linregpcr")
        if amp not in LATE:
            continue
        changes = {
            "refs": refs[_refs(values["refs"])],
            "cut": cuts[float(values["cut"])],
            "nondetect": NONDETECT[values["undetermined"]],
            "late_cq": LATE[amp],
        }
        out = engine.evaluate(space.to_index(changes))
        rows = rows.set_index("item")
        for i, gene in enumerate(items):
            row = rows.loc[gene]
            assert np.isclose(out["log2fc"][i], row["log2fc"], atol=1e-8, equal_nan=True), (
                gene,
                changes,
            )
            assert CALL_NAMES[int(out["call"][i])] == row["conclusion"], (gene, changes)
            compared += 1
        cells += 1
    return cells, compared


def test_the_studio_grid_is_a_slice_of_the_simulator(workflow):
    cells, compared = _compare(workflow["store"], workflow["report"].study_id)
    assert cells == 31 * 3 * 2 * 3  # refs x cut x empty wells x (LinRegPCR, Cq<=35, Cq<=38)
    assert compared == cells * 58


def test_they_still_agree_after_the_persons_exclusion(workflow):
    cells, _ = _compare(workflow["store"], workflow["report"].final_study_id)
    assert cells == 31 * 3 * 2 * 3
