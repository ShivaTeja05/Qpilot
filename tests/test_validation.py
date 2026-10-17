"""Known-answer round 2: dPCR mapping, truth rules, propagated intervals, the no-difference plate."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from qsim import known_answers, nodiff, truth
from qsim.validate import run


@pytest.fixture(scope="module")
def dpcr():
    return truth.load_dpcr()


def test_dpcr_wells_map_to_layout_and_qpcr_samples(dpcr):
    assert len(dpcr) == 31  # 24 probe wells + 7 EvaGreen wells (D1 is missing upstream)
    w = dpcr.set_index("well")
    assert (w.loc["A04", "assay"], w.loc["A04", "qpcr_sample"]) == (
        "FSTL_1_F_109",
        "genomic DNA 20ng",
    )
    assert w.loc["A04", "copies"] == pytest.approx(12065.46)
    assert w.loc["B08", "assay"] == "FSTL_1_K_219"
    # C5-C8 switch to K_219 although both files number them on (F_113, K_231, ...)
    assert w.loc["C05", "assay"] == "FSTL_1_K_219"
    # the EvaGreen plate's A05 is layout D5: L_412 on the 10^5 standard
    assert (w.loc["D05", "assay"], w.loc["D05", "qpcr_sample"]) == (
        "FSTL_1_L_412",
        "dil_1_10_10e5",
    )
    assert "D01" not in w.index


def test_dpcr_pair_rules(dpcr):
    sd = truth.dpcr_well_sd(dpcr)
    assert 0 < sd < 0.2
    t = truth.pair_truth(dpcr, "genomic DNA 20ng", "genomic DNA 7ng", sd)
    f, k = t.per_assay["FSTL_1_F_109"], t.per_assay["FSTL_1_K_219"]
    assert t.log2 == pytest.approx((f + k) / 2) and t.source == "dPCR mean of 2"
    # the two assays disagree 2.5-fold on the 0.2 ng tube: no single truth
    low = truth.pair_truth(dpcr, "genomic DNA 0.7ng", "genomic DNA 0.2ng", sd)
    assert low.source == "unresolved" and np.isnan(low.log2)
    # probe wells of the 10^5 standard are above the linear range; one assay is not enough
    top = truth.pair_truth(dpcr, "dil_1_10_10e5", "dil_1_10_10e4", sd)
    assert top.source == "unresolved" and top.assays == ("FSTL_1_L_412",)
    amp = truth.pair_truth(dpcr, "dil_1_10_10e4", "dil_1_10_10e3", sd)
    assert len(amp.assays) == 4 and 3.0 < amp.log2 < 3.4


def _curves(efficiency: float = 1.9) -> pd.DataFrame:
    """An ideal plate: N0 = amount, E fixed, triplicates with tiny Cq noise."""
    rng = np.random.default_rng(1)
    rows = []
    for target in ("a", "b"):
        for sample, amount in (("hi", 8.0), ("mid", 4.0), ("lo", 1.0)):
            for i in range(3):
                cq = 30 - np.log(amount) / np.log(efficiency) + rng.normal(0, 0.02)
                n0 = efficiency ** (30 - cq)  # threshold of 1 unit at Cq 30 for one copy
                rows.append(
                    {
                        "run_id": "r",
                        "target": target,
                        "sample": sample,
                        "well": f"{sample}{i}",
                        "ng": amount,
                        "series": "dilution",
                        "cq": cq,
                        "n0": n0,
                        "eff_target": efficiency,
                        "eff_target_sd": 0.02,
                        "eff_indiv": efficiency,
                        "flagged": False,
                    }
                )
    c = pd.DataFrame(rows)
    c["log2_nq"] = np.log2(c["n0"]) + c["cq"] * np.log2(c["eff_target"])
    return c


def test_run_scores_against_a_supplied_truth():
    c = _curves()
    t = run(c, [("hi", "lo")], lambda r, a, hi, lo: (3.0, 0.01, "test") if a == "a" else None)
    assert set(t["assay"]) == {"a"}  # None skips the case
    base = known_answers._baseline(t).iloc[0]
    assert base["truth_log2"] == 3.0 and abs(base["error_log2"]) < 0.05
    assert base["dcq"] == pytest.approx(-3 / np.log2(1.9), abs=0.05)
    assert base["se_log2e"] > 0  # the delta-method term is filled for the assay mean
    nominal = run(c, [("hi", "mid")])
    assert nominal["truth_log2"].iloc[0] == pytest.approx(1.0)


def test_propagated_interval_reduces_to_welch_and_widens():
    c = _curves()
    base = known_answers._baseline(run(c, [("hi", "lo")])).assign(tubes="g", truth_se=0.0)
    zero = {"g": {"sd_level_log2": 0.0, "sd_log2e_run": 0.0}}
    x = known_answers.propagate(base.assign(se_log2e=0.0), zero)
    assert np.allclose(x["new_lo"], x["ci_lo"]) and np.allclose(x["new_hi"], x["ci_hi"])
    wide = known_answers.propagate(base, {"g": {"sd_level_log2": 0.1, "sd_log2e_run": 0.05}})
    assert (wide["new_hi"] - wide["new_lo"] > x["new_hi"] - x["new_lo"]).all()


def test_run_effect_recovers_a_level_sd():
    rng = np.random.default_rng(7)
    rows = []
    for pair in range(30):
        for _ in range(12):  # 12 runs measure each pair of tubes
            rows.append(
                {
                    "tubes": "g",
                    "pair": str(pair),
                    "estimate_log2": 2.0 + rng.normal(0, 0.1 * np.sqrt(2)),
                    "se_rep": 0.0,
                    "se_log2e": 0.0,
                    "dcq": -1.0 - pair / 10,
                }
            )
    est = known_answers.run_effect(pd.DataFrame(rows))
    assert est["sd_level_log2"] == pytest.approx(0.1, abs=0.03)
    assert est["sd_log2e_run"] < 0.03


def test_ds380_conversion_and_null_cells():
    wells = nodiff.load()
    assert len(wells) == 380 and wells["cq"].between(15, 21).all()
    # Mann-Whitney cannot reach p < 0.05 at 3 vs 3 (smallest p 0.1), so it is not a cell there
    assert not any(c[2] == "mann_whitney" for c in nodiff.cells_for(3))
    assert any(c[2] == "mann_whitney" for c in nodiff.cells_for(6))
    r = nodiff.run(wells, 3, draws=40, seed=1)
    assert r["share_defensible_cells_calling"] == 0 and r["calls_passing_robust_filter"] == 0
    assert r["baseline_median_abs_log2fc"] < 0.15


def test_known_answer_round_end_to_end(tmp_path):
    result = known_answers.validate(out=tmp_path)
    assert result["cases_with_truth"] == 197
    assert set(result["plates"]) == {p.key for p in known_answers.PLATES}
    comp = result["v2_coverage"]["components"]
    assert all(np.isfinite(v["sd_level_log2"]) for v in comp.values())
    # coverage of the propagated interval never falls below the replicate-only interval
    cov = result["v2_coverage"]["all"]
    assert cov["propagated_ci"] >= cov["old_welch_ci"]
    assert (tmp_path / "validation_dpcr.json").exists()
