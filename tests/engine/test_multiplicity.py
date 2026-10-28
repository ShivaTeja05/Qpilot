"""Dunnett's and Tukey's corrections: the quadrature against scipy, then the engine against scipy.

``qpilot.qpcr.multiplicity`` integrates Dunnett's multivariate t and Tukey's studentized range
with fixed Gauss rules (deterministic). Here it is checked against ``scipy.stats.dunnett``
(quasi-Monte Carlo, about 1e-4) and a high-order rule of the same integral (1e-7), and against
``scipy.stats.tukey_hsd`` / ``studentized_range`` (1e-8). Then, on the synthetic three-group
file, every comparison's corrected p-value is recomputed with scipy from the engine's own
per-unit relative quantities, and the plan's refusals are checked in words.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

import qpilot.qpcr.multiplicity as mult
from qpilot.qpcr.multiplicity import dunnett_adjusted, pooled, tukey_adjusted
from qpilot.qpcr.quant import relative
from qpilot.qpcr.study import StudySettings, build_model, comparison_units, run_study
from qpilot.schemas_studio import Comparison, ComparisonPlan
from tests.fixtures.studio.compare_mini import design as mini_design
from tests.fixtures.studio.compare_mini import write_compare_mini


def _stats(samples):
    return [
        (
            np.array([len(x)], dtype=float),
            np.array([np.mean(x)]),
            np.array([np.var(x, ddof=1) if len(x) > 1 else np.nan]),
        )
        for x in samples
    ]


def _dunnett_inputs(samples):
    control, treated = samples[0], samples[1:]
    var, df = pooled(_stats(samples))
    n0 = len(control)
    t = np.array(
        [
            [(np.mean(x) - np.mean(control)) / np.sqrt(var[0] * (1 / len(x) + 1 / n0))]
            for x in treated
        ]
    )
    return t, np.array([[len(x)] for x in treated], dtype=float), np.array([n0], float), df


def test_dunnett_equals_scipy_within_its_monte_carlo_error():
    rng = np.random.default_rng(3)
    for _ in range(25):
        k = int(rng.integers(2, 6))
        sizes = rng.integers(2, 9, size=k + 1)
        samples = [rng.normal(rng.normal(0, 1.2) if i else 0, 1, n) for i, n in enumerate(sizes)]
        t, n, n0, df = _dunnett_inputs(samples)
        want = stats.dunnett(*samples[1:], control=samples[0], random_state=1)
        np.testing.assert_allclose(t[:, 0], want.statistic, rtol=1e-12)
        np.testing.assert_allclose(dunnett_adjusted(t, n, n0, df)[:, 0], want.pvalue, atol=1e-3)


def test_dunnett_quadrature_agrees_with_a_high_order_rule():
    rng = np.random.default_rng(5)
    t = rng.normal(0, 2.5, size=(4, 30))
    n = rng.integers(2, 8, size=(4, 30)).astype(float)
    n0 = rng.integers(2, 8, size=30).astype(float)
    df = rng.integers(2, 60, size=30).astype(float)
    t[1, 3] = np.nan  # a comparison the gene cannot test is not in its family
    found = dunnett_adjusted(t, n, n0, df)
    keep = (mult.Z_NODES, mult.S_NODES_SMALL_DF, mult.S_NODES_LARGE_DF)
    try:
        mult.Z_NODES, mult.S_NODES_SMALL_DF, mult.S_NODES_LARGE_DF = 150, 96, 64
        mult._z_rule.cache_clear()
        mult.s_rule.cache_clear()
        high = dunnett_adjusted(t, n, n0, df)
    finally:
        mult.Z_NODES, mult.S_NODES_SMALL_DF, mult.S_NODES_LARGE_DF = keep
        mult._z_rule.cache_clear()
        mult.s_rule.cache_clear()
    np.testing.assert_allclose(found, high, atol=1e-7, equal_nan=True)
    assert np.isnan(found[1, 3])
    # the family of gene 3 is the other three comparisons: as if the untested one were absent
    alone = dunnett_adjusted(
        np.delete(t[:, 3:4], 1, 0), np.delete(n[:, 3:4], 1, 0), n0[3:4], df[3:4]
    )
    np.testing.assert_allclose(np.delete(found[:, 3], 1), alone[:, 0], atol=1e-12)


def test_one_comparison_under_dunnett_is_the_pooled_t_test():
    t = np.array([[2.3], [np.nan]])
    p = dunnett_adjusted(t, np.array([[4.0], [4.0]]), np.array([5.0]), np.array([11.0]))
    assert p[0, 0] == pytest.approx(2 * stats.t.sf(2.3, 11), abs=1e-9) and np.isnan(p[1, 0])


def test_tukey_equals_scipy_tukey_hsd():
    rng = np.random.default_rng(7)
    for _ in range(25):
        k = int(rng.integers(2, 7))
        samples = [rng.normal(rng.normal(0, 1), 1, n) for n in rng.integers(2, 9, size=k)]
        want = stats.tukey_hsd(*samples)
        var, df = pooled(_stats(samples))
        pairs = [(i, j) for i in range(k) for j in range(i + 1, k)]
        t = np.array(
            [
                [
                    (np.mean(samples[i]) - np.mean(samples[j]))
                    / np.sqrt(var[0] * (1 / len(samples[i]) + 1 / len(samples[j])))
                ]
                for i, j in pairs
            ]
        )
        found = tukey_adjusted(t, np.array([k], float), df)[:, 0]
        np.testing.assert_allclose(found, [want.pvalue[i, j] for i, j in pairs], atol=1e-8)


def test_large_degrees_of_freedom_and_extremes():
    t = np.array([[0.0], [40.0]])
    p = dunnett_adjusted(t, np.array([[50.0], [50.0]]), np.array([50.0]), np.array([5000.0]))
    assert p[0, 0] == pytest.approx(1.0, abs=1e-9) and 0 <= p[1, 0] < 1e-12
    q = tukey_adjusted(np.array([[1.5]]), np.array([3.0]), np.array([4000.0]))
    assert q[0, 0] == pytest.approx(stats.studentized_range.sf(1.5 * np.sqrt(2), 3, 4000), abs=1e-8)
    with pytest.raises(ValueError):
        mult.s_rule(0.0)


# ---- the engine on the synthetic three-group file -----------------------------------------------


@pytest.fixture(scope="module")
def mini(tmp_path_factory):
    root = tmp_path_factory.mktemp("multiplicity")
    return {"path": write_compare_mini(root / "compare_mini.rdml"), "cache": root / "cache"}


def _model(mini, design):
    from qpilot.qpcr.curves import analyse_study

    settings = StudySettings.from_design(design)
    curves = analyse_study(
        mini["path"], settings.experiment_id, settings.candidates, cache_dir=mini["cache"]
    )
    return build_model(curves, settings)


def _groups(model, gene):
    rel = relative(model.matrix, gene, model.space.primary["refs"], "drop", model.inputs.excluded)
    out = {}
    for cid, (a, b, _) in comparison_units(model).items():
        out[cid] = (rel[rel.index.isin(a)].to_numpy(), rel[rel.index.isin(b)].to_numpy())
    return out


def test_a_dunnett_study_equals_scipy_dunnett_on_the_engines_own_values(mini):
    design = mini_design(correction="dunnett")
    result, _cards, _grid = run_study(
        mini["path"], StudySettings.from_design(design), cache_dir=mini["cache"]
    )
    found = result.comparisons
    assert found.test == "pooled_t" and found.correction == "dunnett"
    model = _model(mini, design)
    for gene in ("IL6", "MYC", "TP53"):
        groups = _groups(model, gene)
        control = groups["drug_a_vs_control"][1]
        treated = [groups[o.id][0] for o in found.comparisons]
        want = stats.dunnett(*treated, control=control, random_state=1)
        everything = [control, *treated]
        dof = sum(len(x) for x in everything) - len(everything)
        sp = sum((len(x) - 1) * np.var(x, ddof=1) for x in everything) / dof
        for i, outcome in enumerate(found.comparisons):
            c = outcome.contrasts[gene]
            a = treated[i]
            assert c.log2fc == pytest.approx(np.mean(a) - np.mean(control), abs=1e-12)
            t = (np.mean(a) - np.mean(control)) / np.sqrt(sp * (1 / len(a) + 1 / len(control)))
            assert c.p == pytest.approx(2 * stats.t.sf(abs(t), dof), rel=1e-9)
            assert outcome.p_adjusted[gene] == pytest.approx(want.pvalue[i], abs=1e-3)
            significant = outcome.p_adjusted[gene] < 0.05 and abs(c.log2fc) >= 1
            assert (c.conclusion != "none") == significant
            half = stats.t.ppf(0.975, dof) * np.sqrt(sp * (1 / len(a) + 1 / len(control)))
            assert c.ci[0] == pytest.approx(2 ** (c.log2fc - half), rel=1e-9)
    assert result.contrasts == found.comparisons[0].contrasts  # the primary is the study's own


def test_a_tukey_study_equals_scipy_tukey_hsd(mini):
    design = mini_design(pattern="all_pairs", correction="tukey")
    result, _cards, _grid = run_study(
        mini["path"], StudySettings.from_design(design), cache_dir=mini["cache"]
    )
    found = result.comparisons
    model = _model(mini, design)
    order = ["Control", "Drug A", "Drug B"]
    for gene in ("IL6", "MYC", "TP53"):
        groups = _groups(model, gene)
        by_name = {
            "Control": groups["drug_a_vs_control"][1],
            "Drug A": groups["drug_a_vs_control"][0],
            "Drug B": groups["drug_b_vs_control"][0],
        }
        want = stats.tukey_hsd(*(by_name[g] for g in order))
        for outcome in found.comparisons:
            i, j = order.index(outcome.group_a), order.index(outcome.group_b)
            assert outcome.p_adjusted[gene] == pytest.approx(want.pvalue[i, j], abs=1e-8)


def test_the_grid_and_the_record_are_deterministic(mini, tmp_path):
    from qpilot.qpcr.study import write_outputs

    design = mini_design(correction="dunnett")
    settings = StudySettings.from_design(design)
    texts = []
    for name in ("one", "two"):
        result, cards, grid = run_study(mini["path"], settings, cache_dir=mini["cache"])
        write_outputs(result, cards, grid, tmp_path / name)
        files = ("results.json", "grid_comparisons.csv")
        texts.append({k: (tmp_path / name / k).read_bytes() for k in files})
    assert texts[0] == texts[1]


@pytest.mark.parametrize(
    ("kwargs", "words"),
    [
        ({"pattern": "all_pairs", "correction": "dunnett"}, "each group against one control"),
        ({"pattern": "vs_control", "correction": "tukey"}, "every pair of the groups"),
        ({"pattern": "vs_control", "correction": "dunnett", "pair_by": "donor"}, "pools unpaired"),
    ],
)
def test_the_plan_refuses_a_correction_that_does_not_fit(kwargs, words):
    comparisons = (
        Comparison(group_a="B", group_b="A"),
        Comparison(group_a="C", group_b="A"),
    )
    if kwargs["pattern"] == "all_pairs":
        comparisons = (*comparisons, Comparison(group_a="C", group_b="B"))
    control = "A" if kwargs["pattern"] == "vs_control" else None
    with pytest.raises(ValueError, match=words):
        ComparisonPlan(comparisons=comparisons, control=control, **kwargs)


def test_tukey_needs_every_pair():
    with pytest.raises(ValueError, match="every pair"):
        ComparisonPlan(
            pattern="all_pairs",
            comparisons=(
                Comparison(group_a="B", group_b="A"),
                Comparison(group_a="C", group_b="A"),
            ),
            correction="tukey",
        )
    plan = ComparisonPlan(
        pattern="all_pairs",
        comparisons=(
            Comparison(group_a="B", group_b="A"),
            Comparison(group_a="C", group_b="A"),
            Comparison(group_a="C", group_b="B"),
        ),
        correction="tukey",
    )
    assert plan.correction == "tukey"
