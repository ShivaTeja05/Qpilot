"""Correctness tests on the public Vermeulen benchmark (fetched SHA-256-pinned by qPilot)."""

from __future__ import annotations

import numpy as np
import pytest
from qpilot.qpcr.study import study_from_curves
from scipy import stats

from qsim import explore, inference, influence
from qsim.attribution import Factorial
from qsim.compare import whatif
from qsim.data import load_study
from qsim.decisions import qpcr_space
from qsim.engine import CALL_NAMES, Engine, adjust, mann_whitney


@pytest.fixture(scope="module")
def setup():
    study = load_study()
    space = qpcr_space(study.candidates, study.primary_refs)
    return study, space, Engine(study, space)


def test_study_tiers_follow_rules():
    from qsim.study_space import space_for

    study = load_study()
    space, info = space_for(study)
    tiers = {o.id: o.tier for o in space.decision("refs").options}
    assert all(tiers[o] == "common_practice" for o in ("HMBS", "SDHA", "UBC", "ALUsq"))
    assert not info["stable_genes"] and "HMBS" in info["implicated_genes"]
    assert space.decision("cut").role == "question"


def test_baseline_reproduces_qpilot(setup):
    study, space, engine = setup
    base = engine.evaluate(space.baseline_index())
    result, _, _ = study_from_curves(study.curves, "x")
    for i, gene in enumerate(study.items):
        ref = result.contrasts[gene]
        assert base["log2fc"][i] == pytest.approx(ref.log2fc, abs=1e-12)
        assert base["p"][i] == pytest.approx(ref.p, rel=1e-9, abs=1e-15)
        assert CALL_NAMES[int(base["call"][i])] == ref.conclusion


def test_qpilot_186_grid_is_a_subspace(setup):
    study, space, engine = setup
    _, _, grid = study_from_curves(study.curves, "x")
    table = grid.set_index(["refs__idx", "cut__idx", "undetermined__idx", "item"])
    refs = space.decision("refs").options
    for ri in range(len(refs)):
        for ci, cut in enumerate(["top10", "top15", "top20"]):
            for ui, nd in enumerate(["drop", "cap_min"]):
                res = engine.evaluate(
                    space.to_index({"refs": refs[ri].id, "cut": cut, "nondetect": nd})
                )
                for i, gene in enumerate(study.items):
                    q = table.loc[(ri, ci, ui, gene)]
                    assert res["log2fc"][i] == pytest.approx(q.log2fc, abs=1e-12)
                    assert CALL_NAMES[int(res["call"][i])] == q.conclusion


def test_leave_one_out_is_exact(setup):
    study, space, engine = setup
    base = influence.Baseline(engine)
    loo = influence.leave_one_out(engine, base)
    for smp in loo["sample"].drop_duplicates().iloc[:5]:
        drop = np.zeros(study.cq.shape, dtype=bool)
        drop[study.samples.index(smp), :] = True
        full = engine.evaluate(space.baseline_index(), drop=drop)
        rows = loo[loo["sample"] == smp].set_index("gene")
        for gene, row in rows.iterrows():
            i = engine.items.index(gene)
            assert full["log2fc"][i] - base.diff[i] == pytest.approx(row["d_log2fc"], abs=1e-12)


def test_reference_well_is_exact(setup):
    study, space, engine = setup
    base = influence.Baseline(engine)
    table = influence.reference_wells(engine, base)
    row = table.iloc[7]
    i, j = study.samples.index(row["sample"]), study.genes.index(row["reference"])
    drop = np.zeros(study.cq.shape, dtype=bool)
    drop[i, j] = True
    # dropping the well removes the sample from every gene; recompute the normaliser by hand instead
    values = base.values.copy()
    values[i, j] = np.nan
    ref = values[:, base.ref_cols]
    mean = np.nanmean(ref, axis=1)
    rel = base.rel + (base.values[:, base.ref_cols].mean(axis=1) - mean)[:, None]
    a, b = base.a, base.b
    diffs = [rel[a[:, g], g].mean() - rel[b[:, g], g].mean() for g in range(len(engine.items))]
    se = base.se
    assert np.nanmax(np.abs((np.array(diffs) - base.diff) / se)) == pytest.approx(
        row["max_abs_d_in_se"], abs=1e-9
    )


def test_adjustments():
    p = np.array([0.01, 0.04, 0.03, 0.2])
    assert np.allclose(adjust(p, "bh"), [0.04, 0.16 / 3, 0.16 / 3, 0.2])
    assert np.allclose(adjust(p, "holm"), [0.04, 0.09, 0.09, 0.2])


def test_mann_whitney_matches_scipy():
    rng = np.random.default_rng(0)
    x = np.round(rng.normal(size=(40, 3)), 1)  # rounding creates ties
    a = np.zeros((40, 3), bool)
    a[:15] = True
    b = ~a
    ours = mann_whitney(x, a, b)
    for j in range(3):
        ref = stats.mannwhitneyu(x[a[:, j], j], x[b[:, j], j], method="asymptotic").pvalue
        assert ours[j] == pytest.approx(ref, rel=1e-10)


def test_rings_and_covering(setup):
    _, space, _ = setup
    sizes = explore.ring_sizes(space)
    assert len(explore.rings(space, 2)) == sum(sizes[:3])
    ca = explore.covering_array(space, 2, seed=1)
    assert explore.coverage(space, ca, 2) == 1.0
    assert tuple(ca[0]) == space.baseline_index()


def test_joint_test_uses_the_engines_statistics(setup):
    _, space, engine = setup
    table, meta = inference.joint_test(engine, permutations=19, seed=1)
    base = engine.evaluate(space.baseline_index())
    t_base = np.abs(base["log2fc"] / base["se"])
    assert (table["max_abs_t"].to_numpy() >= t_base - 1e-9).all()
    assert meta["forks"] == len(inference.forks(engine))


def test_whatif_baseline_has_no_effect(setup):
    _, space, engine = setup
    table = whatif(engine, {})
    assert (table["impact"] == "no_demonstrated_effect").all()
    assert (table["d_log2fc"] == 0).all()


def test_factorial_and_determinism(setup):
    _, space, engine = setup
    small = {
        "efficiency": [0],
        "flagged": [0],
        "nondetect": [0, 1],
        "test": [0],
        "multiplicity": [0],
    }
    cells = np.array(
        [
            c
            for c in explore.full(space)
            if all(c[space.names.index(k)] in v for k, v in small.items())
        ]
    )
    g1, g2 = engine.run(cells), Engine(engine.study, space).run(cells[::-1])
    order = np.lexsort(g2.index.T[::-1])
    assert np.array_equal(g1.log2fc, g2.log2fc[order])


def test_factorial_requires_full_grid(setup):
    _, space, engine = setup
    with pytest.raises(ValueError):
        Factorial(engine.run(explore.rings(space, 1)))


def test_standard_curve_efficiency_is_plausible(setup):
    study, _, _ = setup
    e = np.nanmax(study.eff_std, axis=0)
    assert np.isfinite(e).sum() >= 60
    assert 1.8 < float(np.nanmedian(e)) < 2.1


RESULTS = __import__("pathlib").Path(__file__).resolve().parents[1] / "results"


@pytest.mark.skipif(not (RESULTS / "explain.json").exists(), reason="run `qsim run` first")
def test_ask_without_model_uses_checked_templates():
    from qpilot.ai.client import ModelClient
    from qpilot.ai.config import ModelConfig

    from qsim.ask import Asker

    asker = Asker(RESULTS, client=ModelClient(config=ModelConfig()))
    ans = asker.answer("Does NM23A depend on the reference genes?")
    assert ans.tool == "gene" and ans.args["focus"] == "refs" and ans.written_by == "template"
    assert "NM23A" in ans.text and "{{" not in ans.text
    assert asker.parse_changes("What if we used only HMBS and capped the non-detects?") == {
        "refs": "HMBS",
        "nondetect": "cap_min",
    }


@pytest.mark.skipif(not (RESULTS / "explain.json").exists(), reason="run `qsim run` first")
def test_model_answer_with_naked_numbers_is_rejected():
    from qpilot.ai.client import MockBackend, ModelClient

    from qsim.ask import Asker

    replies = iter(
        [
            '{"tool": "gene", "args": {"gene": "ODC1"}}',
            "ODC1 is 3.6 times higher.",  # typed number: must be rejected
            "ODC1 is 3.6 times higher.",
        ]
    )
    asker = Asker(
        RESULTS,
        client=ModelClient(backend=MockBackend(lambda s, m: next(replies))),
        model_writes=True,
    )
    ans = asker.answer("Tell me about ODC1 please")
    assert ans.routed_by == "model" and ans.written_by == "template"
    assert ans.problems  # the validator's reasons are kept
