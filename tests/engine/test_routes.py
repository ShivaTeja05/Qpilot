"""Step 2.7 gate: the usual route from the instrument to Prism, as engine facts."""

import math

import pandas as pd
import pytest
from scipy import stats

from qpilot.qpcr.routes import ROUTES, compare_routes, cq_matrix, gene_routes


def test_gene_routes_by_hand():
    # dCq per unit; group a is about two cycles lower (four-fold up with E = 2)
    delta = pd.Series({"a1": 1.0, "a2": 1.2, "a3": 0.7, "b1": 3.0, "b2": 3.3, "b3": 2.8, "b4": 2.9})
    high, rest = {"a1", "a2", "a3"}, {"b1", "b2", "b3", "b4"}
    a, b = delta[list(sorted(high))], delta[list(sorted(rest))]
    log2 = stats.ttest_ind(-a, -b, equal_var=False)
    assert log2.pvalue < 0.05 and (-a).mean() - (-b).mean() > 1
    rq_a, rq_b = 2.0 ** -(a - b.mean()), 2.0 ** -(b - b.mean())
    assert math.log2(rq_a.mean() / rq_b.mean()) > 1
    assert stats.ttest_ind(rq_a, rq_b, equal_var=False).pvalue < 0.05
    assert gene_routes(delta, high, rest) == dict.fromkeys(ROUTES, "up")
    assert gene_routes(delta, {"a1"}, rest) == dict.fromkeys(ROUTES, "none")


def test_linear_routes_can_disagree_with_the_log_scale():
    # one unit far higher: p 0.028 on log2 (Welch); on the linear scale 2^[3, 3.2, 5] vs about
    # 1 has a huge spread, p 0.19 (Welch) and 0.12 (Student), although the fold is about 15
    delta = pd.Series({"a1": -3.0, "a2": -3.2, "a3": -5.0, "b1": 0.0, "b2": -0.2, "b3": -0.1})
    out = gene_routes(delta, {"a1", "a2", "a3"}, {"b1", "b2", "b3"})
    assert out == {"ddcq": "up", "linear_welch": "none", "linear_student": "none"}


def test_cq_matrix_averages_replicates_and_skips_excluded_or_called_off_wells():
    table = pd.DataFrame(
        {
            "run_id": ["p"] * 5,
            "well": ["A1", "A2", "A3", "A4", "A5"],
            "sample": ["s1", "s1", "s2", "s2", "s3"],
            "sample_type": ["unkn"] * 5,
            "target": ["G"] * 5,
            "cq": [20.0, 22.0, 25.0, float("nan"), 30.0],
            "design_excluded": [False, False, False, False, True],
        }
    )
    cq = cq_matrix(table, units=None, well_calls={"p/A2": False})
    assert cq.loc["s1", "G"] == 20.0 and cq.loc["s2", "G"] == 25.0
    assert "s3" not in cq.index


def test_routes_use_the_wells_of_the_engines_primary_rule():
    """Review s0: with a Cq cut-off as the primary rule, a late well is out of the routes too.

    In the toy E is exactly 2, so on the same wells ΔΔCq is the engine's analysis itself; the
    one well over cycle 35 is the only thing that could make the route differ.
    """
    from tests.engine.test_groups_study import run, toy_design, toy_wells

    curves = toy_wells(overrides={("sA1", "T1", 0): {"cq": 36.0}})
    result = run(curves, toy_design(amp_calls=("cq_le_35", "linregpcr")))[0]
    assert result.contrasts["T1"].conclusion == "up"
    assert result.facts["f_n_differ_route_ddcq"].value == 0
    late = cq_matrix(curves, None, amp_call="cq_le_35")
    assert late.loc["sA1", "T1"] == pytest.approx(26.5)  # Cq 27 and 26; 36 is left out
    assert cq_matrix(curves, None).loc["sA1", "T1"] == pytest.approx((36 + 27 + 26) / 3)


def test_compare_routes_counts_differences():
    rows = []
    for unit, dcq in {"a1": 1.0, "a2": 1.2, "a3": 0.7, "b1": 3.0, "b2": 3.3, "b3": 2.8}.items():
        for target, cq in (("R", 20.0), ("G", 20.0 + dcq)):
            rows.append({"run_id": "p", "well": f"{unit}{target}", "sample": unit,
                         "sample_type": "unkn", "target": target, "cq": cq})  # fmt: skip
    table = pd.DataFrame(rows)
    units = ["a1", "a2", "a3", "b1", "b2", "b3"]
    high, rest = {"a1", "a2", "a3"}, {"b1", "b2", "b3"}
    found = compare_routes(table, None, units, high, rest, ["R"], {"G": "none"})
    assert {r: found[r].differ for r in ROUTES} == dict.fromkeys(ROUTES, ("G",))
    agree = compare_routes(table, None, units, high, rest, ["R"], {"G": "up"})
    assert [agree[r].n_differ for r in ROUTES] == [0, 0, 0]


# ---------- the demo study (oracles from docs/studio-measured.md) ----------


@pytest.fixture(scope="module")
def studio_demo(demo_curves):
    from qpilot.io.datasets import VERMEULEN_SHA256
    from qpilot.qpcr.designs import vermeulen_design
    from qpilot.qpcr.study import StudySettings, study_from_curves

    # any design but the legacy default asks for the Studio facts; here: no axis, no other change
    design = vermeulen_design().model_copy(update={"note": "routes oracle"})
    return study_from_curves(demo_curves, VERMEULEN_SHA256, StudySettings.from_design(design))


@pytest.mark.demo_data
def test_demo_routes_oracle(studio_demo):
    """Measured on the demo: 4 (CAMTA2, IGSF4, PAICS, PRKACB_bis), 14 and 21 of 58."""
    facts = studio_demo[0].facts
    assert facts["f_n_genes"].value == 58
    assert facts["f_n_differ_route_ddcq"].value == 4
    assert facts["f_genes_differ_route_ddcq"].value == "CAMTA2, IGSF4, PAICS, PRKACB_bis"
    assert facts["f_n_differ_route_linear_welch"].value == 14
    assert facts["f_n_differ_route_linear_student"].value == 21
    welch = set(facts["f_genes_differ_route_linear_welch"].value.split(", "))
    student = set(facts["f_genes_differ_route_linear_student"].value.split(", "))
    assert len(welch) == 14 and len(student) == 21
    assert "f_n_flipped_amp_call" not in facts and facts["f_n_cells"].value == 186


@pytest.mark.demo_data
def test_demo_routes_with_a_cq_cutoff_as_the_primary_rule(demo_curves):
    """Review s0: under cq_le_35 the routes drop the same wells (8 ΔΔCq differences were 2)."""
    from qpilot.io.datasets import VERMEULEN_SHA256
    from qpilot.qpcr.amp_call import STUDIO_AMP_CALLS
    from qpilot.qpcr.designs import vermeulen_design
    from qpilot.qpcr.study import StudySettings, study_from_curves

    rules = ("cq_le_35", *(r for r in STUDIO_AMP_CALLS if r != "cq_le_35"))
    design = vermeulen_design().model_copy(update={"amp_calls": rules})
    settings = StudySettings.from_design(design)
    facts = study_from_curves(demo_curves, VERMEULEN_SHA256, settings)[0].facts
    assert facts["f_n_differ_route_ddcq"].value == 2
    assert facts["f_genes_differ_route_ddcq"].value == "PRDM2, SNAPC1"
    assert facts["f_n_differ_route_linear_welch"].value == 14
    assert facts["f_n_differ_route_linear_student"].value == 14


@pytest.mark.demo_data
def test_demo_studio_preset_keeps_every_legacy_number(studio_demo, demo_curves):
    from qpilot.io.datasets import VERMEULEN_SHA256
    from qpilot.qpcr.study import study_from_curves

    legacy = study_from_curves(demo_curves, VERMEULEN_SHA256)
    studio, cards, grid = studio_demo
    assert studio.contrasts == legacy[0].contrasts and studio.robustness == legacy[0].robustness
    assert studio.study_id != legacy[0].study_id  # a different design is a different study
    assert all(legacy[0].facts[f] == studio.facts[f] for f in legacy[0].facts)
    pd.testing.assert_frame_equal(grid, legacy[2])
