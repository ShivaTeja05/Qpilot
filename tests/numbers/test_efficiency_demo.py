"""The efficiency axis on the demo study, opt-in, end to end (acceptance: prototype s4)."""

import pytest

from qpilot.core import robustness as rb
from qpilot.core.decisions import needs_human
from qpilot.core.store import _grid_csv
from qpilot.explain.templates import render_template
from qpilot.qpcr.curves import analyse_study
from qpilot.qpcr.designs import DesignError
from qpilot.qpcr.study import StudySettings, build_model, study_from_curves
from tests.conftest import DEMO_RDML

ALL = ("linregpcr", "per_well", "amplicon_mean", "assumed_2", "standard_curve")
pytestmark = pytest.mark.demo_data


@pytest.fixture(scope="module")
def curves():
    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    return analyse_study(DEMO_RDML, "biomarker_set")


@pytest.fixture(scope="module")
def study(curves):
    return study_from_curves(curves, "0" * 64, StudySettings(efficiency=ALL))


def test_demo_flips_match_the_prototype(curves):
    model = build_model(curves, StudySettings(efficiency=ALL))
    space = model.space
    assert list(space.dimensions) == ["refs", "cut", "undetermined", "efficiency"]
    assert space.dimensions["efficiency"] == [
        "linregpcr",
        "per_well",
        "assumed_2",
        "standard_curve",
    ]
    assert space.axes["efficiency"].status == "swept"
    assert "amplicon_mean" in dict(space.axes["efficiency"].unavailable)  # one gene per plate
    screen = model.screens["efficiency"]
    assert screen.flipped["per_well"] == ("CAMTA2", "DPYSL3", "PAICS", "PRKACB_bis", "SLC25A5")
    assert screen.flipped["assumed_2"] == ("CAMTA2", "IGSF4", "PAICS", "PRKACB_bis")
    assert screen.flipped["standard_curve"] == ("DPYSL3", "PAICS", "SLC25A5")
    base = space.evaluate(space.primary)
    well = space.evaluate({**space.primary, "efficiency": "per_well"})
    two = space.evaluate({**space.primary, "efficiency": "assumed_2"})
    assert well["NTRK1"].fc / base["NTRK1"].fc == pytest.approx(0.39, abs=0.005)
    assert two["NTRK1"].fc / base["NTRK1"].fc == pytest.approx(0.47, abs=0.005)
    for gene in screen.flipped["per_well"] + screen.flipped["assumed_2"]:
        assert 0.49 <= base[gene].fc <= 2.1 or 0.49 <= well[gene].fc <= 2.1
    assert model.axis_notes["efficiency"]["n_excluded_per_well"] == 9


def test_demo_card_facts_and_escalation(study):
    result, cards, grid = study
    assert len(grid) == 31 * 3 * 2 * 4 * 58
    card = next(c for c in cards if c.id == "card_efficiency")
    assert card.kind == "numbers.efficiency_model" and card.status == "open"
    assert needs_human(card) and card.impact["n_genes_flipped"] == 6
    assert card.evidence["n_flipped_by_option"] == {
        "linregpcr": 0,
        "per_well": 5,
        "assumed_2": 4,
        "standard_curve": 3,
    }
    assert result.facts["f_n_flipped_efficiency"].value == 6
    assert result.facts["f_n_eff_excluded_per_well"].value == 9
    assert result.facts["f_axis_efficiency"].value == "swept"
    text = render_template("efficiency_v1", result.facts, card=card).plain
    assert "5 of 58 genes" in text and "a person makes it" in text
    # the primary analysis is untouched: same headline numbers as the legacy run
    assert result.contrasts["ODC1"].fc == pytest.approx(3.5899, abs=1e-4)


def test_demo_fragility_names_the_efficiency_axis(curves, study):
    space = build_model(curves, StudySettings(efficiency=ALL)).space
    fragile = rb.fragility_by_axis(study[2], space)
    resting = sorted(g for g, f in fragile.items() if "efficiency" in f["rests_on"])
    assert resting == ["CAMTA2", "DPYSL3", "IGSF4", "PAICS", "PRKACB_bis", "SLC25A5"]
    assert fragile["PAICS"]["by_axis"]["efficiency"]["flipping_options"] == [
        "per_well",
        "assumed_2",
        "standard_curve",
    ]


def test_opt_in_is_deterministic(curves, study):
    again = study_from_curves(curves, "0" * 64, StudySettings(efficiency=ALL))
    assert _grid_csv(again[2]) == _grid_csv(study[2])
    assert again[0].model_dump_json() == study[0].model_dump_json()


def test_only_unavailable_options_means_no_axis(curves):
    model = build_model(curves, StudySettings(efficiency=("linregpcr", "amplicon_mean")))
    assert "efficiency" not in model.space.dimensions
    assert model.space.axes["efficiency"].status == "not_applicable"


def test_bad_options_are_refused(curves):
    with pytest.raises(DesignError, match="start with"):
        build_model(curves, StudySettings(efficiency=("per_well", "linregpcr")))
    with pytest.raises(DesignError, match="unknown efficiency option"):
        build_model(curves, StudySettings(efficiency=("linregpcr", "guess")))
