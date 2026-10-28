"""The science review's independent oracles (``validation/excellence``) against the engine.

Each test runs qPilot on a real lab file from ``tests/fixtures/corpus`` and recomputes the same
numbers from first principles (``docs/science-review-2026-10.md`` says what each checks and why).
The oracles never call qPilot's arithmetic; where they take qPilot's per-well table as their
input, the numbers compared are everything downstream of it.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from qpilot.qpcr.curves import analyse_study
from qpilot.qpcr.normfinder import normfinder
from qpilot.qpcr.study import StudySettings, build_model, run_study
from tests.science import kphaffii as kp
from validation.excellence import absolute_oracle as ao
from validation.excellence import comparisons_oracle as co
from validation.excellence import melt_oracle as mo
from validation.excellence import normfinder_oracle as nfo
from validation.excellence import replicates_oracle as ro
from validation.excellence import stats_oracle as so

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"
TIGHT = 1e-12


@pytest.fixture(scope="module")
def cache(tmp_path_factory):
    return tmp_path_factory.mktemp("science-cache")


@pytest.fixture(scope="module")
def wells(cache):
    return analyse_study(kp.FILE, kp.EXPERIMENT, kp.REFS, cache_dir=cache)


@pytest.fixture(scope="module")
def rel(wells):
    return co.relative(co.unit_values(wells), list(kp.REFS))


def _engine(design, cache):
    return run_study(kp.FILE, StudySettings.from_design(design), cache_dir=cache)[0]


def _max_gaps(result, want):
    gaps = {"log2fc": 0.0, "p": 0.0, "p_adjusted": 0.0, "q": 0.0}
    for outcome, (_, expected) in zip(result.comparisons.comparisons, want.items(), strict=True):
        for gene, r in outcome.contrasts.items():
            w = expected[gene]
            gaps["log2fc"] = max(gaps["log2fc"], abs(r.log2fc - w["diff"]))
            gaps["p"] = max(gaps["p"], abs(r.p - w["p"]))
            gaps["p_adjusted"] = max(
                gaps["p_adjusted"], abs(outcome.p_adjusted[gene] - w["p_adjusted"])
            )
            gaps["q"] = max(gaps["q"], abs(outcome.q_value[gene] - w["q"]))
    return gaps


PLANS = [
    pytest.param(
        ("20", "28", "D20", "D28"), "vs_control", "20", "holm", False, id="vs_control-holm"
    ),
    pytest.param(("20", "28", "D20", "D28"), "all_pairs", None, "holm", False, id="all_pairs-holm"),
    pytest.param(
        ("20", "28", "D20", "D28"), "vs_control", "20", "none", False, id="vs_control-none"
    ),
    pytest.param(("20", "28", "D20", "D28"), "vs_control", "20", "holm", True, id="paired-holm"),
    pytest.param(kp.CONDITIONS, "vs_control", "20", "holm", False, id="eight-conditions"),
]


@pytest.mark.parametrize(("names", "pattern", "control", "correction", "paired"), PLANS)
def test_several_comparisons_equal_the_oracle(
    cache, rel, names, pattern, control, correction, paired
):
    """Welch / paired t, Holm within a gene, BH within a comparison, Welch's ANOVA: to 1e-12."""
    design = kp.plan_design(names, pattern, control, correction, paired)
    result = _engine(design, cache)
    plan = [(c.group_a, c.group_b) for c in design.comparisons.comparisons]
    pairs = {s: s.rsplit("_", 1)[1] for s in kp.SAMPLES} if paired else None
    want = co.compare(rel, kp.groups(names), plan, correction, pairs)
    gaps = _max_gaps(result, want)
    assert max(gaps.values()) < TIGHT, gaps
    if result.comparisons.omnibus:
        found = co.omnibus(rel, kp.groups(names))
        for gene, o in result.comparisons.omnibus.items():
            assert o.f == pytest.approx(found[gene]["f"], rel=1e-12)
            assert o.p == pytest.approx(found[gene]["p"], rel=1e-10, abs=1e-15)
            assert o.df2 == pytest.approx(found[gene]["df2"], rel=1e-12)


def test_the_oracles_own_welch_anova_and_paired_test_equal_scipy(rel):
    data = [rel.loc[kp.groups(["20"])["20"], "HAC1i"], rel.loc[kp.groups(["D20"])["D20"], "HAC1i"]]
    three = [*data, rel.loc[kp.groups(["28"])["28"], "HAC1i"]]
    mine = so.welch_anova([list(x) for x in three])
    want = stats.f_oneway(*three, equal_var=False)
    assert mine["f"] == pytest.approx(want.statistic) and mine["p"] == pytest.approx(want.pvalue)
    w = so.welch(list(data[0]), list(data[1]))
    assert w["p"] == pytest.approx(stats.ttest_ind(*data, equal_var=False).pvalue)
    diffs = list(np.asarray(data[1]) - np.asarray(data[0]))
    assert so.paired(diffs)["p"] == pytest.approx(stats.ttest_rel(data[1], data[0]).pvalue)


def test_the_oracles_dunnett_equals_scipys(rel):
    """The oracle's adaptive quadrature against scipy's quasi-Monte Carlo (error ~1e-4)."""
    g = kp.groups(("20", "28", "D20", "D28"))
    for gene in rel.columns:
        named = {k: list(rel.loc[v, gene]) for k, v in g.items()}
        var, df = so.pooled_variance(named)
        treated = ["28", "D20", "D28"]
        t = [so.pooled_t(named[k], named["20"], var, df)["t"] for k in treated]
        mine = so.dunnett_adjusted(t, [3, 3, 3], 3, df)
        stat, theirs = so.scipy_dunnett([named[k] for k in treated], named["20"])
        np.testing.assert_allclose(stat, t, rtol=1e-10)
        np.testing.assert_allclose(mine, theirs, atol=1e-3)


@pytest.mark.parametrize(
    ("names", "pattern", "control", "correction"),
    [
        (("20", "28", "D20", "D28"), "vs_control", "20", "dunnett"),
        (("20", "28", "D20", "D28"), "all_pairs", None, "tukey"),
        (kp.CONDITIONS, "vs_control", "20", "dunnett"),
    ],
)
def test_dunnett_and_tukey_equal_the_oracle(cache, rel, names, pattern, control, correction):
    """Dunnett and Tukey, when the engine has them (``qpilot.qpcr.multiplicity``)."""
    pytest.importorskip("qpilot.qpcr.multiplicity")
    design = kp.plan_design(names, pattern, control, correction)
    result = _engine(design, cache)
    plan = [(c.group_a, c.group_b) for c in design.comparisons.comparisons]
    want = co.compare(rel, kp.groups(names), plan, correction)
    gaps = _max_gaps(result, want)
    assert gaps["log2fc"] < TIGHT and gaps["p"] < TIGHT and gaps["q"] < TIGHT, gaps
    assert gaps["p_adjusted"] < 1e-9, gaps  # two numerical integrations of one probability
    if correction == "tukey":
        for gene in rel.columns:
            data = [list(rel.loc[kp.groups([x])[x], gene]) for x in names]
            th = stats.tukey_hsd(*data)
            for outcome, (a, b) in zip(result.comparisons.comparisons, plan, strict=True):
                i, j = names.index(a), names.index(b)
                assert outcome.p_adjusted[gene] == pytest.approx(th.pvalue[i, j], abs=1e-9)


def test_end_to_end_from_linregpcrs_own_quantities_the_calls_agree(cache):
    """From the N0 the depositors' LinRegPCR wrote (not qPilot's curve fit): same calls.

    qPilot re-fits the raw curves; the depositors' LinRegPCR used its own settings, so the
    numbers differ (per-well SD of the log2 difference ~0.1, the review measured fold changes up
    to 0.23 log2 apart). The calls, every one "no call" here, agree.
    """
    design = kp.plan_design(("20", "28", "D20", "D28"), "vs_control", "20")
    result = _engine(design, cache)
    theirs = co.linregpcr_wells(kp.FILE)
    rel = co.relative(co.unit_values(theirs), list(kp.REFS))
    plan = [(c.group_a, c.group_b) for c in design.comparisons.comparisons]
    want = co.compare(rel, kp.groups(("20", "28", "D20", "D28")), plan)
    for outcome, (_, expected) in zip(result.comparisons.comparisons, want.items(), strict=True):
        for gene, r in outcome.contrasts.items():
            w = expected[gene]
            assert abs(r.log2fc - w["diff"]) < 0.3
            significant = w["p_adjusted"] < 0.05 and abs(w["diff"]) >= 1
            assert (r.conclusion != "none") == significant


# ---- NormFinder ---------------------------------------------------------------------------------


@pytest.mark.parametrize("grouped", [True, False])
@pytest.mark.parametrize("candidates", [("ACT1", "TFC1", "HRD1"), None])
def test_normfinder_equals_the_papers_equations(wells, grouped, candidates):
    values = co.unit_values(wells)
    cand = list(candidates or values.columns)
    groups = {u: kp.condition(u) for u in values.index} if grouped else None
    mine = nfo.from_frame(values, cand, groups)
    found = normfinder(values, cand, groups)
    for gene in cand:
        assert found.stability[gene] == pytest.approx(mine["stability"][gene], rel=1e-12)
    for pair, value in found.pairs:
        assert value == pytest.approx(mine["pairs"][pair], rel=1e-12)
    if grouped:
        assert found.gamma2 == pytest.approx(mine["gamma2"], abs=1e-15)


# ---- replicates in the robustness audit ---------------------------------------------------------


def _audit_engine(curves, design):
    from qpilot.integration import simulator as sim

    pytest.importorskip("qsim")
    settings = StudySettings.from_design(design)
    model = build_model(curves, settings)
    analysis = sim.Analysis("science", "sha", kp.FILE, settings, model, None, None)
    return sim.prepare(analysis), model


def _replicate_oracle(table, rule, a, b):
    rel = co.relative(ro.combine(table[table["sample_type"] == "unkn"], rule), list(kp.REFS))
    units_a = [u for u in rel.index if kp.condition(u) == a]
    units_b = [u for u in rel.index if kp.condition(u) == b]
    return {g: so.welch(list(rel.loc[units_a, g]), list(rel.loc[units_b, g])) for g in rel.columns}


@pytest.mark.parametrize("outliers", [False, True])
def test_the_audits_replicate_rules_equal_the_oracle(wells, outliers):
    """Mean (qPilot's), median and one outlier left out: n counts units, never wells."""
    curves = wells.copy()
    if outliers:  # one well of six units read 1.5 cycles late, its quantity with it
        pick = curves[
            curves["sample"].str.match(r"^(D20|20)_") & curves["target"].isin(["HAC1i", "ACT1"])
        ]
        hit = pick.groupby(["sample", "target"]).head(1).index[:6]
        curves.loc[hit, "cq"] += 1.5
        curves.loc[hit, "n0"] /= curves.loc[hit, "eff_target"] ** 1.5
    prepared, model = _audit_engine(curves, kp.two_groups("D20", "20"))
    assert prepared.scope["technical_replicates"]["most_wells_per_value"] == 3
    assert prepared.scope["n_in_groups"] == [3, 3]  # units, not 9 wells
    table = model.inputs.primary_table
    calls = {}
    for rule in ("mean", "median", "drop_outlier"):
        out = prepared.engine.evaluate(prepared.space.to_index({"replicates": rule}))
        want = _replicate_oracle(table, rule, "D20", "20")
        for i, gene in enumerate(prepared.engine.items):
            assert out["log2fc"][i] == pytest.approx(want[gene]["diff"], abs=TIGHT)
            assert out["p"][i] == pytest.approx(want[gene]["p"], abs=TIGHT)
        calls[rule] = out["log2fc"].copy()
    moved = not np.allclose(calls["drop_outlier"], calls["mean"])
    assert moved == outliers  # the real file's triplicates are tight: nothing is left out


# ---- absolute quantification --------------------------------------------------------------------


STANDARDS = [
    "rdml/stepone-2.3-rdml-1.0/stepone_std.rdml",
    "rdml/quantstudio7pro-rdml-1.2-edna/SupplementaryMaterials2_qPCR_ConcentrationStandardCurve.rdml",
]


@pytest.mark.parametrize("name", STANDARDS)
def test_standard_curves_lod_and_loq_equal_the_oracle(name):
    from qpilot.qpcr.absolute_study import quantify_file

    result = quantify_file(CORPUS / name)
    fitted = [c for c in result.curves if c.fit is not None]
    assert fitted
    for curve in fitted:
        det = [p for p in curve.points if p.detected and p.cq is not None]
        o = ao.fit([math.log10(p.quantity) for p in det], [p.cq for p in det])
        assert curve.fit.slope == pytest.approx(o["slope"], rel=1e-12)
        assert curve.fit.intercept == pytest.approx(o["intercept"], rel=1e-12)
        assert curve.fit.r2 == pytest.approx(o["r2"], rel=1e-12)
        assert curve.fit.efficiency_ci == pytest.approx(
            (o["efficiency_low"], o["efficiency_high"]), rel=1e-12
        )
        levels: dict[float, tuple[int, int]] = {}
        for p in curve.points:
            n, d = levels.get(p.quantity, (0, 0))
            levels[p.quantity] = (n + 1, d + int(p.detected))
        assert curve.lod.quantity == ao.lod_empirical(levels)
        if curve.lod_model is not None and curve.lod_model.quantity is not None:
            x = [math.log10(p.quantity) for p in curve.points]
            want = ao.lod_logistic(x, [p.detected for p in curve.points])
            assert curve.lod_model.quantity == pytest.approx(want, rel=1e-8)
        for level in curve.levels:
            if level.cv is not None:
                back = [
                    (p.cq - o["intercept"]) / o["slope"]
                    for p in det
                    if p.quantity == level.quantity
                ]
                assert level.cv == pytest.approx(ao.lognormal_cv(back), rel=1e-9)
        for y0 in (min(p.cq for p in det), o["y_mean"], max(p.cq for p in det)):
            x0, s = curve.fit.inverse(y0, 3)
            _, low, high = ao.inverse_classical(o, y0, 3)
            t = curve.fit.t_crit
            assert (x0 - t * s, x0 + t * s) == pytest.approx((low, high), rel=1e-12)


def test_the_classical_inverse_interval_is_the_exact_one_on_a_good_curve():
    """StepOne's RNase P curve (R² 0.9995): Miller & Miller's interval equals Fieller's to 1e-3."""
    from qpilot.qpcr.absolute_study import quantify_file

    (curve,) = [c for c in quantify_file(CORPUS / STANDARDS[0]).curves if c.fit is not None]
    det = [p for p in curve.points if p.detected and p.cq is not None]
    o = ao.fit([math.log10(p.quantity) for p in det], [p.cq for p in det])
    for p in det:
        _, low, high = ao.inverse_classical(o, p.cq, 3)
        exact = ao.inverse_exact(o, p.cq, 3)
        assert exact == pytest.approx((low, high), abs=1e-3)


# ---- melt curves --------------------------------------------------------------------------------


def test_melt_tm_equals_the_instruments_own_derivative_and_a_spline(tmp_path):
    from qpilot.qpcr.melt import read_melt
    from tests.qpcr.melt_curves import HSIEH, hsieh_rdml

    data = read_melt(hsieh_rdml(str(tmp_path)))
    (run,) = [r for r in {k[0] for k in data.wells} if "gapdh" in r]
    inst = mo.instrument_tm(HSIEH / "2016-09-04 gapdh -  Melt Curve Derivative Results_SYBR.csv")
    spline = mo.spline_tm(HSIEH / "2016-09-04 gapdh -  Melt Curve RFU Results_SYBR.csv")
    assert len(inst) == 96
    ours = {w: data.wells[(run, w, "SYBR")].peaks[0].tm for w in inst}
    assert max(abs(ours[w] - inst[w]) for w in inst) < 0.01  # CFX's derivative is the same filter
    gaps = np.array([ours[w] - spline[w] for w in inst])
    assert np.abs(gaps).max() < 0.1 and abs(gaps.mean()) < 0.05


# ---- the global mean ----------------------------------------------------------------------------


def test_global_mean_is_each_gene_centred_then_averaged(wells):
    from qpilot.qpcr.axes.normaliser import global_mean

    values = co.unit_values(wells)
    values.iloc[0, 2] = np.nan  # one missing value: averaged over the genes the unit has
    genes = list(values.columns)
    found = global_mean(values, genes)
    centred = {g: values[g] - values[g].mean() for g in genes}
    for unit in values.index:
        have = [centred[g][unit] for g in genes if not pd.isna(values.at[unit, g])]
        assert found[unit] == pytest.approx(sum(have) / len(have), abs=TIGHT)
