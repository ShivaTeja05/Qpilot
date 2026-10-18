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


def _curves(efficiency: float = 1.9, estimated: float | None = None) -> pd.DataFrame:
    """An ideal plate: N0 = amount, E fixed, triplicates with tiny Cq noise. ``estimated`` is the
    efficiency LinRegPCR reports, and computes N0 with, when it is not the true one."""
    est = efficiency if estimated is None else estimated
    rng = np.random.default_rng(1)
    rows = []
    for target in ("a", "b"):
        for sample, amount in (("hi", 8.0), ("mid", 4.0), ("lo", 1.0)):
            for i in range(3):
                cq = 30 - np.log(amount) / np.log(efficiency) + rng.normal(0, 0.02)
                n0 = efficiency**30 / est**cq  # one copy reaches the threshold at Cq 30
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
                        "eff_target": est,
                        "eff_target_sd": 0.02,
                        "eff_indiv": est,
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


def test_efficiency_offset_corrects_a_low_efficiency():
    c = _curves(1.9, estimated=1.85)  # LinRegPCR reads the efficiency 2.6 % low
    pairs = [("hi", "mid"), ("mid", "lo"), ("hi", "lo")]
    base = known_answers._baseline(run(c, pairs)).assign(
        plate="p", tubes="g", truth_kind="dPCR", truth_se=0.0
    )
    assert (base["error_log2"] < -0.03).all()  # every estimate reads low, more at wide steps
    offsets = known_answers.series_offsets(base)
    assert len(offsets) == 2  # one series per assay
    assert offsets["delta_log2e"].to_numpy() == pytest.approx(np.log2(1.9 / 1.85), abs=0.005)
    pooled = known_answers.efficiency_offset(offsets)
    fixed = known_answers.calibrate(base, {"g": pooled})
    assert fixed["error_log2"].abs().max() < 0.02
    assert (fixed["se_log2e"] >= base["se_log2e"]).all()  # the offset's SE is propagated
    # no training series: no correction
    none = known_answers.efficiency_offset(known_answers.series_offsets(base.iloc[:0]))
    assert none == {"delta_log2e": 0.0, "se_delta_log2e": 0.0, "series": 0}


def test_calibration_training_holds_out_the_scored_group_and_its_truth():
    rows = [
        ("amc", "dPCR", "g20", "g7", "20 vs 7 ng"),
        ("dkfz", "dPCR", "g20", "g7", "20 vs 7 ng"),
        ("dkfz", "dPCR", "embl", "g20", "EMBL 20 vs 20 ng"),
        ("dkfz", "dPCR", "a4", "a3", "1e4 vs 1e3 copies"),
        ("volume", "nominal", "v4", "v2", "4 vs 2 ng/µl"),
    ]
    base = pd.DataFrame(rows, columns=["tubes", "truth_kind", "hi", "lo", "pair"]).assign(
        truth_log2=1.0
    )

    def picked(**how) -> list[tuple[str, str]]:
        t = known_answers.calibration_training(base, "amc", **how)
        return list(zip(t["tubes"], t["hi"], strict=True))

    assert picked() == [("dkfz", "g20"), ("dkfz", "embl"), ("dkfz", "a4")]
    # the DKFZ genomic pairs use the tubes AMC is scored against, so they share its truth
    assert picked(disjoint=True) == [("dkfz", "a4")]
    assert picked(kinds=("dPCR", "nominal"), templates=("genomic",)) == [
        ("dkfz", "g20"),
        ("dkfz", "embl"),
        ("volume", "v4"),
    ]
    assert ("amc", "g20") in picked(held_out=False)


def test_plate_pair_term_recovers_a_between_plate_sd():
    rng = np.random.default_rng(3)
    rows = []
    for pair in range(40):
        for plate in ("p", "q"):  # two plates measure the same pair of tubes, one run each
            rows.append(
                {
                    "tubes": "amc" if plate == "p" else "dkfz",  # one physical series
                    "plate": plate,
                    "hi": f"h{pair}",
                    "lo": f"l{pair}",
                    "pair": str(pair),
                    "estimate_log2": 2.0 + rng.normal(0, 0.1),
                    "se_rep": 0.0,
                    "se_log2e": 0.0,
                    "dcq": -2.0,
                }
            )
    base = pd.DataFrame(rows)
    term = known_answers.plate_pair_term(base)
    assert term["pairs"] == 40
    assert term["sd_plate_pair_log2"] == pytest.approx(0.1, abs=0.03)
    # a pair measured on one plate only says nothing about plates
    assert known_answers.plate_pair_term(base[base["plate"] == "p"])["pairs"] == 0
    # within-plate noise is subtracted, so noise alone gives no term
    noisy = base.assign(estimate_log2=2.0, se_rep=0.1)
    assert known_answers.plate_pair_term(noisy)["sd_plate_pair_log2"] == 0.0


def test_poisson_term_scale_and_slope():
    c = known_answers.copies_per_reaction()
    assert c["genomic DNA 20ng"] == pytest.approx(20 * 303)  # ng per reaction x 303 copies/ng
    assert c[truth.qpcr_name("gDNA 0.2ng/ul")] == pytest.approx(0.2 * 10 * 303)  # 10 µl reactions
    rows = pd.DataFrame({"hi": ["genomic DNA 2ng"], "lo": ["genomic DNA 0.7ng"]})
    x = known_answers.poisson_x(rows).iloc[0]
    assert x == pytest.approx(1 / (2 * 303) + 1 / (0.7 * 303))
    assert known_answers.POISSON_B == pytest.approx(2.0814, abs=1e-4)
    # the slope through the origin recovers an excess variance proportional to the Poisson scale
    pairs = [("genomic DNA 20ng", "genomic DNA 7ng"), ("genomic DNA 2ng", "genomic DNA 0.7ng")]
    rows = []
    for hi, lo in pairs:
        xs = 1 / c[hi] + 1 / c[lo]
        for plate, sign in (("p", 1), ("q", -1)):  # two plates, difference 2 sqrt(b x / 2)
            rows.append(
                {
                    "tubes": "amc" if plate == "p" else "dkfz",
                    "plate": plate,
                    "hi": hi,
                    "lo": lo,
                    "pair": f"{hi} vs {lo}",
                    "estimate_log2": 1.5 + sign * np.sqrt(3.0 * xs / 2),
                    "se_rep": 0.0,
                    "se_log2e": 0.0,
                    "dcq": -1.5,
                }
            )
    assert known_answers.poisson_slope(pd.DataFrame(rows)) == pytest.approx(3.0)


def test_propagate_adds_the_poisson_term():
    c = _curves()
    base = known_answers._baseline(run(c, [("hi", "lo")])).assign(tubes="g", truth_se=0.0)
    zero = {"g": {"sd_level_log2": 0.0, "sd_log2e_run": 0.0}}
    plain = known_answers.propagate(base, zero)
    more = known_answers.propagate(
        base.assign(poisson_x=0.01), {"g": zero["g"] | {"poisson_b": 2.0}}
    )
    assert np.allclose(more["se_new"] ** 2, plain["se_new"] ** 2 + 0.02)


def test_coverage_ci_resamples_whole_truths():
    x = pd.DataFrame(
        {
            "truth_kind": "dPCR",
            "hi": ["a"] * 40 + ["b"] * 10,
            "lo": "z",
            "in_new_ci_with_truth": [True] * 40 + [False] * 10,
        }
    )
    ci = known_answers.coverage_ci(x)
    assert ci["truths"] == 2
    lo, hi = ci["coverage_90%_cluster_bootstrap"]
    assert lo == 0.0 and hi == 1.0  # with two truths a draw can hold only the failing one
    assert ci == known_answers.coverage_ci(x)  # seeded


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
    # the calibration is scored only on groups it was not fitted on; round 2 is kept as it was
    cal = result["efficiency_calibration"]
    assert cal["uncalibrated"] == cov
    assert set(cal["offsets"]) == set(comp)
    assert cal["offsets"]["amc"]["series"] == 8  # the DKFZ plate's dPCR-measured series only
    inside = cal["variants"]["in_sample"]["offsets"]
    assert len({v["delta_log2e"] for v in inside.values()}) == 1
    # tests P1-P3 report the same things, and P1's term uses no plate of the scored series
    gap = result["coverage_gap_tests"]
    assert (
        gap["reference_round_2"]["all"]["propagated_ci_with_truth_se"]
        == cov["propagated_ci_with_truth_se"]
    )
    terms = gap["p1_plate_pair_term"]["terms"]
    assert all(k.startswith("gDNA Feb 2024") for k in terms["amc"]["excess_variance_by_pair"])
    assert all(k.startswith("gDNA Dec 2024") for k in terms["volume"]["excess_variance_by_pair"])
    p5 = gap["p5_poisson_plate_pair_term"]
    assert p5["poisson_b"] == pytest.approx(1 / np.log(2) ** 2, abs=1e-4)  # nothing fitted
    for key in (
        "p1_plate_pair_term",
        "p2_std_curve",
        "p3_std_curve_plus_plate_pair_term",
        "p5_poisson_plate_pair_term",
    ):
        assert gap[key]["all"]["truths"] == 13
    assert set(result["v2_coverage"]["other_estimators"]) == {
        "robust_in_sample",
        "plain_leave_one_group_out",
        "plain_in_sample",
    }
    assert (tmp_path / "validation_dpcr.json").exists()
