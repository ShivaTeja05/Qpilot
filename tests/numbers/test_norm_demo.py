"""The normaliser and inter-run axes on the demo study (64 plates, one gene per plate)."""

import numpy as np
import pytest

from qpilot.explain.templates import render_template
from qpilot.qpcr import interrun as irc
from qpilot.qpcr.curves import analyse_study
from qpilot.qpcr.study import StudySettings, build_model, study_from_curves
from tests.conftest import DEMO_RDML

NORM = ("planned", "normfinder_pair", "genorm_pair", "global_mean")
pytestmark = pytest.mark.demo_data


@pytest.fixture(scope="module")
def curves():
    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    return analyse_study(DEMO_RDML, "biomarker_set")


@pytest.fixture(scope="module")
def study(curves):
    return study_from_curves(curves, "0" * 64, StudySettings(normaliser=NORM))


def test_normaliser_axis_on_the_demo(curves):
    model = build_model(curves, StudySettings(normaliser=NORM))
    space = model.space
    assert list(space.dimensions) == ["refs", "cut", "undetermined", "normaliser"]
    assert space.dimensions["normaliser"] == ["planned", "normfinder_pair", "global_mean"]
    notes = model.axis_notes["normaliser"]
    assert notes["normfinder"]["best_pair"] == ["ALUsq(Eurogentec)", "HPRT1"]
    assert notes["genorm_pair"] == ["ALUsq(Eurogentec)", "HPRT1"]
    assert notes["agreement"].startswith("geNorm and NormFinder agree")
    assert "NormFinder's best pair too" in space.axes["normaliser"].unavailable[0][1]
    assert notes["global_mean"]["n_genes"] == 64
    shift = notes["global_mean"]["group_shift"]  # the panel was chosen for this comparison
    assert shift["fold"] == pytest.approx(0.7067, abs=1e-3) and shift["p"] < 1e-4
    screen = model.screens["normaliser"]
    assert len(screen.flipped["normfinder_pair"]) == 3
    assert len(screen.flipped["global_mean"]) == 19


def test_normaliser_card_on_the_demo(study):
    result, cards, grid = study
    card = next(c for c in cards if c.id == "card_normaliser")
    assert card.kind == "numbers.normaliser" and card.recommended == "planned"
    assert [o.id for o in card.options] == ["planned", "normfinder_pair", "global_mean"]
    assert card.evidence["n_flipped_by_option"] == {
        "planned": 0,
        "normfinder_pair": 3,
        "global_mean": 19,
    }
    assert result.facts["f_n_flipped_normaliser"].value == 19
    text = render_template(card.rationale_template, result.facts, card=card).plain
    assert "geNorm and NormFinder agree" in text and "19 of 58" in text
    # 186 legacy cells + 2 other normalisers x 3 cut-offs x 2 rules: no repeated analysis
    assert result.facts["f_n_cells"].value == 186 + 12
    assert len(grid) == 198 * 58


def test_inter_run_correction_cannot_apply_to_the_demo(curves):
    model = build_model(curves, StudySettings(interrun=irc.OPTIONS))
    axis = model.space.axes["interrun"]
    assert "interrun" not in model.space.dimensions and axis.status == "not_applicable"
    assert "cancels in every fold change" in dict(axis.unavailable)["factor"]
    assert model.axis_notes["interrun"]["n_split_targets"] == 0
    assert model.axis_notes["interrun"]["n_plate_pairs_sharing"] == 0


def test_any_plate_factor_leaves_every_demo_fold_change_as_it_is(curves):
    """The measurement for the report: one gene per plate, so a plate factor always cancels."""
    base = build_model(curves, StudySettings()).space
    rng = np.random.default_rng(0)
    runs = sorted(curves["run_id"].unique())
    factors = dict(zip(runs, rng.normal(0, 1, len(runs)), strict=True))  # up to ~2.5 log2
    moved = build_model(irc.apply_factors(curves, factors), StudySettings()).space
    a, b = base.evaluate(base.primary), moved.evaluate(moved.primary)
    delta = max(abs(a[g].log2fc - b[g].log2fc) for g in a)
    assert delta < 1e-9
    assert all(a[g].conclusion == b[g].conclusion for g in a)
