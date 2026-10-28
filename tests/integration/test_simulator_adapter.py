"""The adapter: designs it can and cannot audit, the person's choices, refusals (demo data)."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from qpilot.core.store import StudyStore
from qpilot.integration import simulator as sim
from qpilot.qpcr.amp_call import STUDIO_AMP_CALLS
from qpilot.qpcr.designs import vermeulen_design
from qpilot.qpcr.export import study_inputs
from qpilot.schemas_studio import Comparison, SampleDesign, StudyDesign

pytestmark = [
    pytest.mark.demo_data,
    pytest.mark.skipif(not sim.available(), reason="the Decision Simulator is not installed"),
]


@pytest.fixture(scope="module")
def store(tmp_path_factory, demo_rdml_session):
    return StudyStore(tmp_path_factory.mktemp("adapter") / "studies")


@pytest.fixture(scope="module")
def legacy(store, demo_rdml_session):
    return store.ensure_study(demo_rdml_session)


def _groups_design(store, legacy_id, units=None) -> StudyDesign:
    inputs = study_inputs(store, legacy_id)
    samples = {
        s: SampleDesign(
            sample=s,
            group="high" if g.endswith("-high") else "rest",
            biological_unit=(units or {}).get(s),
        )
        for s, g in inputs.groups.items()
    }
    return StudyDesign(
        design_id="demo_as_groups",
        experiment_id="biomarker_set",
        mode="groups",
        comparison=Comparison(group_a="high", group_b="rest"),
        samples=samples,
        reference_candidates=vermeulen_design().reference_candidates,
        headline=vermeulen_design().headline,
    )


def test_a_two_group_design_is_audited_with_its_one_comparison(
    store, legacy, demo_rdml_session, workflow, tmp_path
):
    study_id = store.ensure_study(demo_rdml_session, design=_groups_design(store, legacy))
    prepared = sim.prepare(sim.load_analysis(store, study_id))
    assert prepared.scope["mode"] == "groups"
    assert [o.id for o in prepared.space.decision("cut").options] == [sim.GROUPS_OPTION]
    assert prepared.scope["analyses_in_full_grid"] == 90_396 // 3
    assert sim.reproduction(prepared, store.get(study_id))["ok"]
    result = sim.audit(store, study_id, tmp_path / "audit", permutations=199)
    assert sim.verify_audit(result.out_dir).ok
    # the defensible view holds the cut-off fixed, so it is the same 144 analyses either way
    ours = pd.read_csv(result.out_dir / "genes.csv").set_index("gene")["defensible_holds"]
    split = pd.read_csv(
        f"{workflow['report'].stages['simulator']['audit_dir']}/genes.csv"
    ).set_index("gene")["defensible_holds"]
    assert (ours - split.reindex(ours.index)).abs().max() < 1e-12


def test_samples_of_one_biological_unit_are_audited_as_qpilot_averaged_them(
    store, legacy, demo_rdml_session
):
    inputs = study_inputs(store, legacy)
    high = sorted(s for s, g in inputs.groups.items() if g.endswith("-high"))
    units = {s: f"unit{i // 2}" for i, s in enumerate(high[:6])}  # two preparations per unit
    design = _groups_design(store, legacy, units)
    study_id = store.ensure_study(demo_rdml_session, design=design)
    prepared = sim.prepare(sim.load_analysis(store, study_id))
    assert sim.reproduction(prepared, store.get(study_id))["ok"]
    reps = prepared.scope["technical_replicates"]
    assert reps["most_wells_per_value"] == 2 and reps["values_with_several_wells"] == 3 * 64
    # two wells per value: the median is the mean and no well is an outlier, so it is not varied
    assert not reps["varied"] and "replicates" not in prepared.space.names
    assert prepared.scope["analyses_in_full_grid"] == 90_396 // 3
    n_high = sum(1 for s in high) - 3  # six samples became three units
    assert prepared.scope["n_in_groups"][0] == n_high
    assert {"unit0", "unit1", "unit2"} <= set(prepared.study.samples)


def test_the_persons_card_choice_becomes_the_simulators_option(store, demo_rdml_session):
    design = vermeulen_design().model_copy(
        update={"design_id": "studio_demo", "amp_calls": STUDIO_AMP_CALLS}
    )
    study_id = store.ensure_study(demo_rdml_session, design=design)
    head = store.chain_head(study_id)
    outcome = store.append_decision(
        study_id, "card_amp_call", "cq_le_35", "lab rule, for comparison", "human", head
    )
    assert outcome.status == "applied"
    analysis = sim.load_analysis(store, study_id)
    prepared = sim.prepare(analysis)
    changes, notes = sim.chosen_changes(prepared, analysis.inputs.choices)
    assert changes == {"late_cq": "cq35"} and notes == []
    from qsim.compare import whatif

    table = whatif(prepared.engine, changes).set_index("gene")
    exported = study_inputs(store, study_id)  # the values sent to Prism at the person's choice
    from qpilot.qpcr.export import unit_contrasts

    theirs = unit_contrasts(exported.table("column"), exported.group_order, exported.rule)
    assert set(theirs) == set(table.index)
    for gene, contrast in theirs.items():  # the simulator's what-if is the exported analysis
        assert math.isclose(table.loc[gene, "fold"], contrast.fc, rel_tol=1e-9), gene
        assert table.loc[gene, "call"] == contrast.conclusion, gene


def test_an_audit_that_would_not_reproduce_is_refused(store, legacy, tmp_path, monkeypatch):
    def broken(prepared, result):
        return {
            "ok": False,
            "mismatched": ["ODC1"],
            "genes_only_in_qpilot": [],
            "genes_only_in_simulator": [],
        }

    monkeypatch.setattr(sim, "reproduction", broken)
    with pytest.raises(sim.AuditRefused, match="does not reproduce"):
        sim.audit(store, legacy, tmp_path / "never")
    assert not (tmp_path / "never").exists()
