"""The Prism export rebuilds any confirmed design with the engine's own space (demo data)."""

import math

import pytest

from qpilot.core.store import StudyStore
from qpilot.qpcr.amp_call import STUDIO_AMP_CALLS
from qpilot.qpcr.designs import vermeulen_design
from qpilot.qpcr.export import study_inputs
from qpilot.schemas_studio import Comparison, SampleDesign, StudyDesign

pytestmark = pytest.mark.demo_data


@pytest.fixture(scope="module")
def store(tmp_path_factory, demo_rdml_path_module):
    return StudyStore(tmp_path_factory.mktemp("studies"))


@pytest.fixture(scope="module")
def demo_rdml_path_module():
    from tests.conftest import DEMO_RDML

    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached")
    return DEMO_RDML


def _values(inputs, gene="ODC1"):
    table = inputs.table("column", [gene])
    return dict(zip(table["sample"], table["log2_rq"], strict=True))


def test_groups_design_with_the_demo_split_reproduces_the_demo(store, demo_rdml_path_module):
    legacy_id = store.ensure_study(demo_rdml_path_module)
    legacy = study_inputs(store, legacy_id)
    samples = {
        s: SampleDesign(sample=s, group="high" if g.endswith("-high") else "rest")
        for s, g in legacy.groups.items()
    }
    design = StudyDesign(
        design_id="demo_as_groups",
        experiment_id="biomarker_set",
        mode="groups",
        comparison=Comparison(group_a="high", group_b="rest"),
        samples=samples,
        reference_candidates=vermeulen_design().reference_candidates,
        headline=vermeulen_design().headline,
    )
    study_id = store.ensure_study(demo_rdml_path_module, design=design)
    assert study_id != legacy_id
    ours, theirs = store.get(study_id), store.get(legacy_id)
    for gene in ("ODC1", "BIRC5", "NTRK1", "NM23A"):
        assert ours.contrasts[gene].fc == theirs.contrasts[gene].fc
        assert ours.contrasts[gene].p == theirs.contrasts[gene].p
    assert math.isclose(ours.contrasts["ODC1"].fc, 3.5899, rel_tol=1e-4)
    designed = study_inputs(store, study_id)
    assert designed.group_order == ("high", "rest")
    assert _values(designed) == _values(legacy)


def test_a_persons_cq_cutoff_choice_reaches_the_exported_values(store, demo_rdml_path_module):
    design = vermeulen_design().model_copy(
        update={"design_id": "studio_demo", "amp_calls": STUDIO_AMP_CALLS}
    )
    study_id = store.ensure_study(demo_rdml_path_module, design=design)
    recommended = study_inputs(store, study_id)
    assert {c.card_id: c.value for c in recommended.choices}["card_amp_call"] == "linregpcr"
    head = store.chain_head(study_id)
    outcome = store.append_decision(
        study_id, "card_amp_call", "cq_le_35", "lab rule, for comparison", "human", head
    )
    assert outcome.status == "applied"
    chosen = study_inputs(store, study_id)
    assert {c.card_id: c.value for c in chosen.choices}["card_amp_call"] == "cq_le_35"
    before, after = _values(recommended, "NTRK1"), _values(chosen, "NTRK1")
    # Wells above Cq 35 stop being quantities, so those tumours leave NTRK1's table; every
    # other value is unchanged (the reference genes' wells of the kept tumours are all <= 35).
    assert set(after) < set(before)
    assert all(after[s] == before[s] for s in after)
