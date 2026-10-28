"""Several comparisons, multiplicity and paired designs: the engine's numbers against scipy.

On the synthetic three-group file (``tests/fixtures/studio/compare_mini.py``: Control, Drug A,
Drug B; four donors) every comparison's fold change, p-value, corrected p-value and q-value is
recomputed here from the engine's own per-unit relative quantities with scipy and statsmodels
(Welch: ``ttest_ind(equal_var=False)``; paired: ``ttest_rel``; Holm and Benjamini-Hochberg:
``multipletests``), and the backward-compatibility promises are pinned: no plan, no change.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from qpilot.qpcr.contrast import bh, holm, paired_t, welch
from qpilot.qpcr.designs import DesignError, check_design, comparison_plan, design_from_proposals
from qpilot.qpcr.quant import relative
from qpilot.qpcr.study import (
    COMPARISON_GRID_FILE,
    StudySettings,
    build_model,
    comparison_grid_of,
    comparison_units,
    run_study,
    write_outputs,
)
from qpilot.schemas import StudyResult
from qpilot.schemas_studio import (
    Comparison,
    ComparisonPlan,
    MadeBy,
    Proposal,
    SampleDesign,
    StudyDesign,
)
from tests.fixtures.studio.compare_mini import design as mini_design
from tests.fixtures.studio.compare_mini import samples as mini_samples
from tests.fixtures.studio.compare_mini import write_compare_mini

multitest = pytest.importorskip("statsmodels.stats.multitest")


# ---- the arithmetic ----------------------------------------------------------------------------


def test_holm_and_bh_equal_statsmodels_with_untested_values_left_out():
    rng = np.random.default_rng(3)
    for _ in range(300):
        p = rng.uniform(0, 0.3, int(rng.integers(1, 9)))
        if rng.random() < 0.4:
            p[rng.integers(0, len(p))] = np.nan
        finite = np.isfinite(p)
        adjusted, q = holm(p), bh(p)
        assert np.isnan(adjusted[~finite]).all() and np.isnan(q[~finite]).all()
        if finite.any():
            want_holm = multitest.multipletests(p[finite], method="holm")[1]
            want_bh = multitest.multipletests(p[finite], method="fdr_bh")[1]
            np.testing.assert_allclose(adjusted[finite], want_holm, rtol=1e-12)
            np.testing.assert_allclose(q[finite], want_bh, rtol=1e-12)
    # by hand: 3 tests, 0.01 0.02 0.04 -> 0.03 0.04 0.04 (step-down, monotone)
    np.testing.assert_allclose(holm([0.04, 0.01, 0.02]), [0.04, 0.03, 0.04])
    np.testing.assert_allclose(bh([0.04, 0.01, 0.02]), [0.04, 0.03, 0.03])


def test_holm_runs_along_one_axis_per_gene():
    p = np.array([[0.01, 0.2, np.nan], [0.03, 0.01, 0.5], [0.04, 0.9, 0.01]])
    out = holm(p, axis=0)
    for j in range(3):
        finite = np.isfinite(p[:, j])
        want = multitest.multipletests(p[finite, j], method="holm")[1]
        np.testing.assert_allclose(out[finite, j], want)


def test_paired_t_equals_scipy_ttest_rel():
    a = np.array([2.1, 3.4, 1.9, 2.8, 3.0])
    b = np.array([1.5, 2.9, 1.0, 2.6, 2.1])
    found = paired_t(a - b)
    want = stats.ttest_rel(a, b)
    assert found.t == pytest.approx(want.statistic) and found.p == pytest.approx(want.pvalue)
    assert found.df == 4 and found.diff == pytest.approx(float(np.mean(a - b)))
    with pytest.raises(ValueError):
        paired_t([0.3])


# ---- the engine on the synthetic three-group file -----------------------------------------------


@pytest.fixture(scope="module")
def mini(tmp_path_factory):
    root = tmp_path_factory.mktemp("compare")
    return {
        "path": write_compare_mini(root / "compare_mini.rdml"),
        "missing": write_compare_mini(root / "compare_missing.rdml", missing_well=True),
        "cache": root / "cache",
    }


def _run(mini, design, key="path"):
    return run_study(mini[key], StudySettings.from_design(design), cache_dir=mini["cache"])


def _model(mini, design, key="path"):
    from qpilot.qpcr.curves import analyse_study

    settings = StudySettings.from_design(design)
    curves = analyse_study(
        mini[key], settings.experiment_id, settings.candidates, cache_dir=mini["cache"]
    )
    return build_model(curves, settings)


def _per_unit(model, gene):
    refs = model.space.primary["refs"]
    return relative(model.matrix, gene, refs, "drop", model.inputs.excluded)


@pytest.mark.parametrize("paired", [False, True])
def test_every_comparison_equals_scipy_and_statsmodels(mini, paired):
    design = mini_design(paired=paired)
    result, cards, grid = _run(mini, design)
    model = _model(mini, design)
    found = result.comparisons
    assert found is not None and found.test == ("paired_t" if paired else "welch")
    assert [o.id for o in found.comparisons] == ["drug_a_vs_control", "drug_b_vs_control"]
    units = comparison_units(model)
    raw: dict[str, dict[str, float]] = {}
    for outcome in found.comparisons:
        group_a, group_b, pairs = units[outcome.id]
        assert (pairs is not None) == paired
        raw[outcome.id] = {}
        for gene, contrast in outcome.contrasts.items():
            values = _per_unit(model, gene)
            if paired:
                a = np.array([values[u] for u, _ in pairs])
                b = np.array([values[v] for _, v in pairs])
                want = stats.ttest_rel(a, b)
                diff = float(np.mean(a - b))
                assert contrast.n_hi == contrast.n_lo == len(pairs) == outcome.n_pairs
            else:
                a = values[values.index.isin(group_a)].to_numpy()
                b = values[values.index.isin(group_b)].to_numpy()
                want = stats.ttest_ind(a, b, equal_var=False)
                diff = float(a.mean() - b.mean())
                w = welch(a, b)
                lo, hi = 2 ** (w.diff - w.t_crit * w.se), 2 ** (w.diff + w.t_crit * w.se)
                assert contrast.ci == pytest.approx((lo, hi), rel=1e-9)
            assert contrast.log2fc == pytest.approx(diff, abs=1e-9)
            assert contrast.p == pytest.approx(want.pvalue, rel=1e-9)
            raw[outcome.id][gene] = contrast.p
    genes = sorted(found.comparisons[0].contrasts)
    for gene in genes:  # Holm across the gene's two comparisons
        ps = [raw[o.id][gene] for o in found.comparisons]
        want = multitest.multipletests(ps, method="holm")[1]
        for outcome, value in zip(found.comparisons, want, strict=True):
            assert outcome.p_adjusted[gene] == pytest.approx(value, rel=1e-12)
            rule = result.conclusion_rule
            expect = "none"
            if value < rule["alpha"] and abs(outcome.contrasts[gene].log2fc) >= 1:
                expect = "up" if outcome.contrasts[gene].log2fc > 0 else "down"
            assert outcome.contrasts[gene].conclusion == expect
    for outcome in found.comparisons:  # BH across the comparison's genes
        ps = [raw[outcome.id][g] for g in genes]
        want = multitest.multipletests(ps, method="fdr_bh")[1]
        for gene, value in zip(genes, want, strict=True):
            assert outcome.q_value[gene] == pytest.approx(value, rel=1e-12)
    # the primary comparison is the study's own result, cards and grid
    first = found.comparisons[0]
    assert first.primary and first.contrasts == result.contrasts
    assert first.robustness == result.robustness and first.confidence == result.confidence
    every = comparison_grid_of(grid)
    block = every[every["comparison"] == first.id].reset_index(drop=True)
    pd.testing.assert_series_equal(block["log2fc"], grid["log2fc"], check_names=False)
    assert list(block["conclusion"]) == list(grid["conclusion"])
    # the expected calls of the synthetic data
    calls = {o.id: {g: c.conclusion for g, c in o.contrasts.items()} for o in found.comparisons}
    assert calls["drug_a_vs_control"] == {"IL6": "up", "MYC": "none", "TP53": "none"}
    assert calls["drug_b_vs_control"] == {"IL6": "up", "MYC": "up", "TP53": "none"}


def test_the_omnibus_is_welchs_anova_of_the_engines_values(mini):
    design = mini_design()
    found = _run(mini, design)[0].comparisons
    model = _model(mini, design)
    assert found.omnibus_groups == ["Drug A", "Control", "Drug B"]
    by_group = {
        g: [u for u, s in mini_samples().items() if s[0] == g] for g in found.omnibus_groups
    }
    for gene, result in found.omnibus.items():
        values = _per_unit(model, gene)
        groups = [values[values.index.isin(units)].to_numpy() for units in by_group.values()]
        want = stats.f_oneway(*groups, equal_var=False)
        assert result.f == pytest.approx(want.statistic, rel=1e-9)
        assert result.p == pytest.approx(want.pvalue, rel=1e-9)
    assert _run(mini, mini_design(paired=True))[0].comparisons.omnibus == {}  # not for pairs


def test_pairing_removes_a_donor_effect(mini):
    unpaired = _run(mini, mini_design(paired=False))[0].comparisons
    paired = _run(mini, mini_design(paired=True))[0].comparisons
    for a, b in zip(unpaired.comparisons, paired.comparisons, strict=True):
        assert b.contrasts["MYC"].fc == pytest.approx(a.contrasts["MYC"].fc)  # same means
    myc = [o.contrasts["MYC"].p for o in (unpaired.comparisons[1], paired.comparisons[1])]
    assert myc[1] < myc[0]  # the donors' own biology no longer counts as noise


def test_without_correction_the_call_uses_p(mini):
    result = _run(mini, mini_design(correction="none"))[0]
    for outcome in result.comparisons.comparisons:
        assert outcome.p_adjusted == {g: c.p for g, c in outcome.contrasts.items()}


def test_all_pairs_three_comparisons_and_a_holm_family_of_three(mini):
    result = _run(mini, mini_design(pattern="all_pairs"))[0]
    found = result.comparisons
    assert len(found.comparisons) == 3 and found.pattern == "all_pairs"
    gene = "MYC"
    ps = [o.contrasts[gene].p for o in found.comparisons]
    want = multitest.multipletests(ps, method="holm")[1]
    assert [o.p_adjusted[gene] for o in found.comparisons] == pytest.approx(list(want))
    assert result.facts["f_n_comparisons"].value == 3
    assert result.facts["f_cmp3_label"].value == "Drug B vs Drug A"


def test_a_unit_without_a_gene_is_left_out_of_that_gene_only(mini):
    result = _run(mini, mini_design(), key="missing")[0]
    second = result.comparisons.comparisons[1]
    assert second.contrasts["TP53"].n_hi == 3 and second.contrasts["IL6"].n_hi == 4
    assert result.facts["f_not_measured_tp53"].value == "DrugB_D4"
    assert result.facts["f_n_not_measured"].value == 1
    assert result.n_samples == 12  # the unit still counts: it has every other gene
    paired = _run(mini, mini_design(paired=True), key="missing")[0].comparisons.comparisons[1]
    assert paired.contrasts["TP53"].n_hi == 3 and paired.n_pairs == 4  # D4's pair lacks TP53


def test_outputs_carry_every_comparisons_grid(mini, tmp_path):
    result, cards, grid = _run(mini, mini_design(paired=True))
    paths = write_outputs(result, cards, grid, tmp_path / "out")
    assert COMPARISON_GRID_FILE in paths
    text = paths[COMPARISON_GRID_FILE].read_text()
    assert text.splitlines()[0].startswith("comparison,refs,undetermined,")
    assert "p_adjusted" in text.splitlines()[0]
    saved = json.loads(paths["results.json"].read_text())
    assert saved["comparisons"]["pair_by"] == "donor"
    assert StudyResult.model_validate(saved) == result


# ---- refusals in plain words --------------------------------------------------------------------


def _paired_design(drop_from: str | None = None, double: bool = False) -> StudyDesign:
    base = mini_design(paired=True)
    samples = dict(base.samples)
    if drop_from is not None:  # D4 has no Control sample in the design
        samples.pop(drop_from)
    if double:  # D1 gives two Drug A units
        samples["DrugA_D2"] = samples["DrugA_D2"].model_copy(update={"pair": "D1"})
    return base.model_copy(update={"samples": samples})


def test_a_paired_design_refuses_units_that_do_not_pair():
    with pytest.raises(DesignError, match=r"donor D4 has no unit in Control"):
        check_design(_paired_design(drop_from="Control_D4"))
    with pytest.raises(DesignError, match=r"donor D1 has 2 units in Drug A"):
        check_design(_paired_design(double=True))
    unpaired = mini_design(paired=True)
    no_key = dict(unpaired.samples)
    no_key["DrugA_D1"] = no_key["DrugA_D1"].model_copy(update={"pair": None})
    with pytest.raises(DesignError, match=r"no donor for DrugA_D1"):
        check_design(unpaired.model_copy(update={"samples": no_key}))


def test_a_plan_is_checked():
    with pytest.raises(ValueError, match="one unpaired comparison"):
        ComparisonPlan(comparisons=(Comparison(group_a="A", group_b="B"),))
    with pytest.raises(ValueError, match="compared twice"):
        ComparisonPlan(
            comparisons=(Comparison(group_a="A", group_b="B"), Comparison(group_a="B", group_b="A"))
        )
    with pytest.raises(ValueError, match="not against the control"):
        ComparisonPlan(
            pattern="vs_control",
            control="C",
            comparisons=(
                Comparison(group_a="A", group_b="C"),
                Comparison(group_a="A", group_b="B"),
            ),
        )
    good = mini_design()
    with pytest.raises(ValueError, match="first comparison must be the design's comparison"):
        StudyDesign.model_validate(
            {**good.model_dump(), "comparison": {"group_a": "Drug B", "group_b": "Control"}}
        )


# ---- backward compatibility ---------------------------------------------------------------------


def test_no_plan_no_change_in_hashes_or_json():
    samples = {s: SampleDesign(sample=s, group=g) for s, (g, _) in mini_samples().items()}
    design = StudyDesign(
        mode="groups", comparison=Comparison(group_a="Drug A", group_b="Control"), samples=samples
    )
    canonical = json.loads(design.canonical())
    assert "comparisons" not in canonical
    assert all("pair" not in s for s in canonical["samples"].values())
    # the same design written before these fields existed hashes the same
    old = {k: v for k, v in design.model_dump(mode="json").items() if k != "comparisons"}
    for s in old["samples"].values():
        s.pop("pair")
    assert StudyDesign.model_validate(old).design_hash() == design.design_hash()
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "results.json"
    stored = StudyResult.model_validate_json(fixture.read_text())
    assert "comparisons" not in stored.model_dump_json()
    assert "comparisons" not in stored.model_dump(mode="json")


def test_a_groups_study_without_a_plan_has_no_comparisons(mini):
    plain = mini_design().model_copy(update={"comparisons": None})
    result, _, grid = _run(mini, plain)
    assert result.comparisons is None and comparison_grid_of(grid) is None
    assert not any(f.startswith(("f_cmp", "f_n_comparisons")) for f in result.facts)


# ---- the design from proposals ------------------------------------------------------------------


def _accepted(kind: str, subject: str, payload: dict) -> Proposal:
    return Proposal(
        study_id="s",
        kind=kind,  # type: ignore[arg-type]
        subject=subject,
        payload=payload,
        made_by=MadeBy(kind="rule"),
        status="accepted",
    )


def test_a_plan_and_pairings_from_accepted_proposals():
    base = mini_design().model_copy(update={"comparisons": None})
    proposals = [_accepted("design.pair", s, {"pair": d, "by": "donor"}) for s, (_, d) in
                 mini_samples().items()]  # fmt: skip
    payload = {
        "group_a": "Drug A",
        "group_b": "Control",
        "comparisons": [
            {"group_a": "Drug A", "group_b": "Control"},
            {"group_a": "Drug B", "group_b": "Control"},
        ],
        "pattern": "vs_control",
        "control": "Control",
        "correction": "holm",
        "pair_by": "donor",
    }
    proposals.append(_accepted("design.comparison", "comparison", payload))
    design = design_from_proposals(base, proposals)
    plan = design.comparisons
    assert plan is not None and plan.pair_by == "donor" and plan.control == "Control"
    assert [c.key() for c in plan.comparisons] == ["drug_a_vs_control", "drug_b_vs_control"]
    assert design.samples["DrugB_D3"].pair == "D3"
    # the plain payload is one comparison, as before
    assert comparison_plan({"group_a": "A", "group_b": "B"}) is None
    plain = design_from_proposals(
        design, [_accepted("design.comparison", "comparison", {"group_a": "Drug A",
                                                               "group_b": "Control"})]
    )  # fmt: skip
    assert plain.comparisons is None and plain.samples["DrugB_D3"].pair == "D3"
