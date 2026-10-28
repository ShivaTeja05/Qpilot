"""The audit on a real plate with technical replicates (LightCycler 96, triplicate wells).

The key invariant holds on a replicate design too: with every choice as planned, the simulator
gives qPilot's stored fold change, p-value and call (it combines a unit's wells with qPilot's
own rule), and only then is anything else computed. No demo data is needed.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from qpilot.core.store import StudyStore
from qpilot.integration import simulator as sim
from tests.integration.hmuy import GENE, HMUY, NAMES, RUN, hmuy_design

pytestmark = pytest.mark.skipif(
    not sim.available(), reason="the Decision Simulator is not installed"
)


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    return StudyStore(tmp_path_factory.mktemp("replicates") / "studies")


@pytest.fixture(scope="module")
def study_id(store):
    return store.ensure_study(HMUY, design=hmuy_design())


@pytest.fixture(scope="module")
def prepared(store, study_id):
    return sim.prepare(sim.load_analysis(store, study_id))


def test_the_design_has_triplicates_and_each_unit_is_one_value(prepared):
    reps = prepared.scope["technical_replicates"]
    assert reps["most_wells_per_value"] == 3 and reps["wells"] == 36 and reps["values"] == 12
    assert reps["rule"] == "mean" and reps["varied"]
    assert prepared.scope["n_samples"] == len(NAMES)  # six units, never 18 wells per gene
    assert prepared.scope["n_in_groups"] == [3, 3]
    assert prepared.scope["decisions"]["replicates"] == ["mean", "median", "drop_outlier"]


def test_the_baseline_reproduces_qpilot_on_a_replicate_design(store, study_id, prepared):
    check = sim.reproduction(prepared, store.get(study_id))
    assert check["ok"], check
    assert check["genes"] == 1 and check["max_abs_diff_log2fc"] <= sim.TOLERANCE


def test_the_audit_runs_end_to_end_and_verifies(store, study_id, tmp_path, capsys, monkeypatch):
    result = sim.audit(store, study_id, tmp_path / "audit", permutations=99)
    assert sim.verify_audit(result.out_dir).ok
    manifest = json.loads((result.out_dir / sim.MANIFEST).read_text())
    assert manifest["reproduces_qpilot"]["ok"]
    assert manifest["scope"]["technical_replicates"]["varied"]
    assert manifest["analyses"] == manifest["scope"]["analyses_in_full_grid"]
    lock = json.loads((result.out_dir / "lock.json").read_text())
    assert lock["baseline"]["replicates"] == "mean"
    assert set(lock["tiers"]["replicates"]) == {"mean", "median", "drop_outlier"}
    assert set(result.verdicts) == {GENE}
    # the command line says how replicates were handled
    from qpilot.integration.__main__ import main

    monkeypatch.setenv("QPILOT_STUDIES_DIR", str(store.root))
    assert (
        main(["audit", "--study", study_id, "--out", str(tmp_path / "cli"), "--permutations", "99"])
        == 0
    )
    printed = capsys.readouterr().out
    assert "technical replicates: Each biological unit's value is the mean" in printed


def test_how_replicates_are_combined_is_an_audit_choice(prepared):
    from qsim.compare import whatif

    base = whatif(prepared.engine, {}).set_index("gene")
    median = whatif(prepared.engine, {"replicates": "median"}).set_index("gene")
    outlier = whatif(prepared.engine, {"replicates": "drop_outlier"}).set_index("gene")
    assert median.loc[GENE, "base_fold"] == pytest.approx(base.loc[GENE, "fold"])
    # DIP_3's hmuY wells span 1.2 cycles (G-REP's expected range is 0.82): F2 is left out
    reps = prepared.study.replicates
    keys = reps.keys()
    assert f"{RUN}/F2" in set(keys[reps.present])
    for table in (median, outlier):
        assert table.loc[GENE, "fold"] != pytest.approx(base.loc[GENE, "fold"])
        assert table.loc[GENE, "call"] == base.loc[GENE, "call"]


def test_a_well_a_person_excluded_is_left_out_of_its_unit_only(store):
    excluded = f"{RUN}/F2"
    study_id = store.ensure_study(HMUY, design=hmuy_design((excluded,)))
    prepared = sim.prepare(sim.load_analysis(store, study_id))
    assert prepared.scope["wells_excluded_by_a_person"] == 1
    assert sim.reproduction(prepared, store.get(study_id))["ok"]
    reps = prepared.study.replicates
    mask = prepared.engine.excluded
    assert mask.shape == reps.present.shape and list(reps.keys()[mask]) == [excluded]
    # the unit keeps a value from its two other wells
    cell = prepared.space.baseline_index()
    values, _ = prepared.engine.matrix_of(prepared.engine.values_of(cell))
    unit = prepared.study.samples.index("be08945d-29c6-47a0-8c49-cc85f693c1a5")
    assert not math.isnan(values[unit, prepared.study.genes.index(GENE)])
    assert np.isfinite(values).all()
