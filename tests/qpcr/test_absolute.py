"""Absolute quantification (qpilot/qpcr/absolute.py) against hand computations, scipy and files.

* the line: scipy's ``linregress`` (slope, intercept, r, standard errors);
* inverse prediction: Miller & Miller's worked example 5.6.1 (x0 and s_x0 to two decimals) and
  the formula by hand for k replicates;
* LOD/LOQ: constructed levels (detection rates, log-normal CV) and a logistic fit checked
  against a direct maximisation of the likelihood;
* ng -> copies by hand;
* a real StepOne file (RNase P standard curve) end to end, a two-plate pooled curve, Std 1..5
  level labels, an internal control whose Cq does not follow the standards.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import optimize, stats

from qpilot.qpcr import absolute as ab

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"
STEPONE = CORPUS / "rdml" / "stepone-2.3-rdml-1.0" / "stepone_std.rdml"


# ---- the line and its inverse ---------------------------------------------------------------


def test_fit_matches_scipy_linregress():
    rng = np.random.default_rng(7)
    x = np.repeat(np.log10([1e6, 1e5, 1e4, 1e3, 1e2]), 3)
    y = 38.0 - 3.32 * x + rng.normal(0, 0.15, len(x))
    fit = ab.fit_line(x, y)
    ref = stats.linregress(x, y)
    assert fit.slope == pytest.approx(ref.slope, rel=1e-12)
    assert fit.intercept == pytest.approx(ref.intercept, rel=1e-12)
    assert fit.r2 == pytest.approx(ref.rvalue**2, rel=1e-12)
    assert fit.se_slope == pytest.approx(ref.stderr, rel=1e-10)
    assert fit.se_intercept == pytest.approx(ref.intercept_stderr, rel=1e-10)
    t = stats.t.ppf(0.975, len(x) - 2)
    low, high = fit.efficiency_ci
    e_bounds = sorted(
        10 ** (-1 / s) - 1 for s in (ref.slope - t * ref.stderr, ref.slope + t * ref.stderr)
    )
    assert (low, high) == pytest.approx(tuple(e_bounds), rel=1e-10)
    assert fit.efficiency == pytest.approx(10 ** (-1 / ref.slope) - 1, rel=1e-12)


def test_inverse_prediction_is_miller_and_miller_example_5_6_1():
    # Statistics and Chemometrics for Analytical Chemistry, Example 5.6.1 (fluorescence)
    fit = ab.fit_line([0, 2, 4, 6, 8, 10, 12], [2.1, 5.0, 9.0, 12.6, 17.3, 21.0, 24.7])
    assert (round(fit.slope, 2), round(fit.intercept, 2), round(fit.s_yx, 4)) == (
        1.93,
        1.52,
        0.4328,
    )
    expected = {2.9: (0.72, 0.26), 13.5: (6.21, 0.24), 23.0: (11.13, 0.26)}
    for y0, (x0, s) in expected.items():
        got = fit.inverse(y0, 1)
        assert (round(got[0], 2), round(got[1], 2)) == (x0, s)


def test_inverse_with_k_replicates_by_hand():
    x = [6, 6, 6, 5, 5, 5, 4, 4, 4, 3, 3, 3]
    y = [18.1, 18.0, 18.2, 21.4, 21.5, 21.3, 24.8, 24.6, 24.9, 28.1, 28.3, 28.0]
    fit = ab.fit_line(x, y)
    cqs = [23.0, 23.2, 22.9]
    y0 = float(np.mean(cqs))
    m, b = np.polyfit(x, y, 1)
    resid = np.asarray(y) - (b + m * np.asarray(x))
    s = math.sqrt((resid**2).sum() / (len(x) - 2))
    sxx = ((np.asarray(x) - np.mean(x)) ** 2).sum()
    x0 = (y0 - b) / m
    s_x0 = s / abs(m) * math.sqrt(1 / 3 + 1 / len(x) + (y0 - np.mean(y)) ** 2 / (m**2 * sxx))
    got = fit.inverse(y0, 3)
    assert got[0] == pytest.approx(x0, rel=1e-12) and got[1] == pytest.approx(s_x0, rel=1e-10)


def test_lognormal_cv():
    values = np.log10([100, 120, 90])
    sd_ln = np.std(np.log([100, 120, 90]), ddof=1)
    assert ab.lognormal_cv(values) == pytest.approx(math.sqrt(math.exp(sd_ln**2) - 1))
    assert math.isnan(ab.lognormal_cv([2.0]))


# ---- LOD / LOQ on constructed tables ------------------------------------------------------------


def _plate(levels, run="p1", target="T", cq_of=None, detect=None, extra=()):
    """A per-well table of standards ``{quantity: n wells}``, Cq on a perfect line."""
    cq_of = cq_of or (lambda q, i: 38.0 - 3.32 * math.log10(q) + (i - 1) * 0.05)
    rows = []
    for q, n in levels.items():
        for i in range(n):
            ok = detect(q, i) if detect else True
            rows.append(
                {
                    "run_id": run,
                    "well": f"S{q:g}_{i}",
                    "sample": f"STD_{q:g}",
                    "sample_type": "std",
                    "target": target,
                    "cq": cq_of(q, i) if ok else float("nan"),
                    "n0": 1.0 if ok else float("nan"),
                    "amplification": ok,
                }
            )
    rows.extend(extra)
    return pd.DataFrame(rows)


def _unknown(sample, cq, run="p1", target="T", well=None):
    return {
        "run_id": run,
        "well": well or f"U_{sample}_{cq}",
        "sample": sample,
        "sample_type": "unkn",
        "target": target,
        "cq": cq,
        "n0": 1.0 if cq == cq else float("nan"),
        "amplification": cq == cq,
    }


def test_lod_is_the_lowest_level_detected_in_95_percent_every_higher_too():
    levels = {1e5: 4, 1e4: 4, 1e3: 4, 1e2: 4, 1e1: 4}
    # 10 copies: 1 of 4 detected, 100 copies: 3 of 4, everything above: 4 of 4
    table = _plate(levels, detect=lambda q, i: not ((q == 1e1 and i >= 1) or (q == 1e2 and i == 3)))
    (curve,) = ab.quantify(table).curves
    assert curve.lod.method == "empirical" and curve.lod.quantity == 1e3
    rates = {lv.quantity: lv.rate for lv in curve.levels}
    assert (rates[1e1], rates[1e2], rates[1e3]) == (0.25, 0.75, 1.0)
    # the logistic LOD (two partly detected levels) is between 100 and 1,000 copies
    assert curve.lod_model is not None and curve.lod_model.method == "logistic"
    assert 100 < curve.lod_model.quantity < 1000
    # one partly detected level only: detection jumps, no finite fit
    jump = ab.quantify(_plate(levels, detect=lambda q, i: not (q == 1e1 and i >= 2)))
    assert jump.curves[0].lod.quantity == 1e2
    assert jump.curves[0].lod_model.method == "not_determined"


def test_every_level_detected_means_at_or_below_the_lowest():
    (curve,) = ab.quantify(_plate({1e5: 3, 1e4: 3, 1e3: 3})).curves
    assert curve.lod.quantity == 1e3 and curve.lod.at_most and curve.lod.method == "lowest_standard"
    assert curve.lod_model is None  # nothing partly detected: no model to fit


def test_loq_uses_the_lognormal_cv_of_back_calculated_quantities():
    spread = {1e5: 0.05, 1e4: 0.05, 1e3: 0.2, 1e2: 0.8}  # Cq noise per level

    def cq_of(q, i):
        return 38.0 - 3.32 * math.log10(q) + (i - 1) * spread[q]

    (curve,) = ab.quantify(_plate({q: 3 for q in spread}, cq_of=cq_of)).curves
    cvs = {lv.quantity: lv.cv for lv in curve.levels}
    back = [math.log10(p.back_quantity) for p in curve.points if p.quantity == 1e2]
    assert cvs[1e2] == pytest.approx(ab.lognormal_cv(back))
    assert cvs[1e3] <= 0.35 < cvs[1e2]
    assert curve.loq.quantity == 1e3 and curve.loq.method == "empirical"
    stricter = ab.quantify(
        _plate({q: 3 for q in spread}, cq_of=cq_of), settings=ab.AbsoluteSettings(loq_cv=0.10)
    )
    assert stricter.curves[0].loq.quantity == 1e4


def test_logistic_fit_is_the_maximum_likelihood():
    x = np.repeat([0.0, 0.5, 1.0, 1.5, 2.0], 6)
    detected = np.array(
        [0, 0, 0, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 1, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
    )

    def nll(beta):
        eta = beta[0] + beta[1] * x
        return float(np.sum(np.logaddexp(0, eta) - detected * eta))

    best = optimize.minimize(
        nll,
        [0.0, 1.0],
        method="Nelder-Mead",
        options={"xatol": 1e-10, "fatol": 1e-12, "maxiter": 5000},
    )
    a, b = ab.logistic_fit(x, detected)
    assert (a, b) == pytest.approx(tuple(best.x), abs=1e-4)
    assert ab.logistic_fit([0, 0, 1, 1], [0, 0, 1, 1]) is None  # separated: no slope


# ---- unknowns ---------------------------------------------------------------------------------


def test_unknown_quantity_interval_and_flags():
    levels = {1e5: 3, 1e4: 3, 1e3: 3, 1e2: 3}
    top_cq = 38.0 - 3.32 * 5
    extra = [
        _unknown("mid", 38.0 - 3.32 * 3.5, well="u1"),
        _unknown("mid", 38.0 - 3.32 * 3.5 + 0.1, well="u2"),
        _unknown("high", top_cq - 3.0, well="u3"),
        _unknown("low", 38.0 - 3.32 * 1.2, well="u4"),
        _unknown("none", float("nan"), well="u5"),
        _unknown("half", 38.0 - 3.32 * 3.0, well="u6"),
        _unknown("half", float("nan"), well="u7"),
    ]
    result = ab.quantify(_plate(levels, extra=extra))
    (curve,) = result.curves
    by_unit = {u.unit: u for u in result.unknowns}
    mid = by_unit["mid"]
    x0, s = curve.fit.inverse(np.mean([w.cq for w in mid.wells]), 2)
    t = stats.t.ppf(0.975, curve.fit.n - 2)
    assert mid.log10_quantity == pytest.approx(x0) and mid.log10_low == pytest.approx(x0 - t * s)
    assert mid.quantity == pytest.approx(10**x0) and mid.flags == ()
    assert "above_top" in by_unit["high"].flags
    assert "below_lowest" in by_unit["low"].flags
    assert by_unit["none"].flags == ("not_detected", "below_lod")
    assert by_unit["none"].quantity is None
    assert "some_not_detected" in by_unit["half"].flags and by_unit["half"].n_detected == 1


def test_biological_units_average_their_wells():
    extra = [_unknown("s1", 25.0, well="a"), _unknown("s2", 25.4, well="b")]
    result = ab.quantify(
        _plate({1e5: 3, 1e4: 3, 1e3: 3}, extra=extra), units={"s1": "m1", "s2": "m1"}
    )
    (unit,) = result.unknowns
    assert unit.unit == "m1" and unit.samples == ("s1", "s2") and unit.n_detected == 2
    assert unit.mean_cq == pytest.approx(25.2)


def test_per_ul_and_per_ng():
    extra = [_unknown("s1", 25.0)]
    reaction = ab.ReactionInputs(template_ul=2.0, input_ng=10.0)
    result = ab.quantify(_plate({1e5: 3, 1e4: 3, 1e3: 3}, extra=extra), reaction=reaction)
    (unit,) = result.unknowns
    assert unit.per_ul == pytest.approx(unit.quantity / 2.0)
    assert unit.per_ng == pytest.approx(unit.quantity / 10.0)


def test_pooled_curve_and_a_plate_without_standards():
    levels = {1e5: 2, 1e4: 2, 1e3: 2}
    a = _plate(levels, run="p1")
    b = _plate(levels, run="p2", cq_of=lambda q, i: 38.3 - 3.32 * math.log10(q) + i * 0.05)
    other = pd.DataFrame([_unknown("s9", 27.0, run="p3"), _unknown("s1", 27.0, run="p1")])
    result = ab.quantify(pd.concat([a, b, other], ignore_index=True))
    ids = {c.id: c for c in result.curves}
    assert set(ids) == {"T @ p1", "T @ p2", "T @ pooled"}
    pooled = ids["T @ pooled"]
    assert pooled.scope == "pooled" and pooled.runs == ("p1", "p2") and pooled.fit.n == 12
    units = {u.unit: u for u in result.unknowns}
    assert units["s1"].curves == ("T @ p1",) and "other_plate" not in units["s1"].flags
    assert units["s9"].curves == ("T @ pooled",) and "other_plate" in units["s9"].flags


def test_level_labels_are_not_quantities():
    table = _plate({1e5: 3, 1e4: 3, 1e3: 3})
    table["sample"] = table["sample"].map(
        {"STD_100000": "Std 1", "STD_10000": "Std 2", "STD_1000": "Std 3"}
    )
    result = ab.quantify(table)
    assert not result.curves and "number the levels" in result.not_quantified["T"]
    given = ab.quantify(table, quantities={"Std 1": 1e5, "Std 2": 1e4, "Std 3": 1e3})
    assert given.curves[0].fit is not None and given.curves[0].quantity_source == "design"


def test_an_assay_that_does_not_follow_the_standards_has_no_curve():
    flat = _plate(
        {1e5: 3, 1e4: 3, 1e3: 3}, cq_of=lambda q, i: 27.0 - 0.05 * math.log10(q) + 0.01 * i
    )
    (curve,) = ab.quantify(flat).curves
    assert curve.fit is None and "barely changes" in curve.problem


def test_excluded_wells_are_left_out_and_quantities_order():
    table = _plate({1e5: 3, 1e4: 3, 1e3: 3}, extra=[_unknown("s1", 27.0)])
    table["design_excluded"] = table["well"].eq("S100000_0")
    (curve,) = ab.quantify(table).curves
    assert curve.fit.n == 8 and all(p.well != "S100000_0" for p in curve.points)
    q, source, _ = ab.standard_quantities(
        pd.DataFrame({"sample": ["STD_50", "X", "Y"], "target": ["T", "T", "T"]}),
        quantities={"X": 7.0},
        declared={("Y", ""): (3.0, "cop"), ("STD_50", "T"): (5.0, "cop")},
    )
    assert list(q) == [5.0, 7.0, 3.0] and list(source) == ["file", "design", "file"]


# ---- ng -> copies -------------------------------------------------------------------------------


def test_copies_from_mass_by_hand():
    # 1 ng of a 3,000 bp plasmid: 1e-9 g * 6.02214076e23 / (3000 * 617.96 + 36.04) g/mol
    assert ab.copies_from_mass(1.0, 3000) == pytest.approx(1e-9 * 6.02214076e23 / 1853916.04)
    assert ab.copies_from_mass(1.0, 100, "ssDNA") == pytest.approx(
        1e-9 * 6.02214076e23 / (100 * 308.97 + 18.02)
    )
    assert ab.copies_from_mass(2.0, 1000, "RNA") == pytest.approx(
        2e-9 * 6.02214076e23 / (1000 * 320.5 + 159.0)
    )
    assert ab.mass_from_copies(ab.copies_from_mass(5.0, 500), 500) == pytest.approx(5.0)
    assert ab.dilution_levels(1e6, 10, 3) == [1e6, 1e5, 1e4]
    with pytest.raises(ab.AbsoluteError):
        ab.copies_from_mass(1.0, 0)
    with pytest.raises(ab.AbsoluteError):
        ab.copies_from_mass(1.0, 100, "protein")


# ---- a real file -------------------------------------------------------------------------------


def test_stepone_rnase_p_standard_curve_end_to_end():
    from qpilot.qpcr.absolute_study import quantify_file

    result = quantify_file(STEPONE)
    (curve,) = result.curves
    std = [p for p in curve.points]
    x = np.log10([p.quantity for p in std])
    y = np.array([p.cq for p in std])
    ref = stats.linregress(x, y)
    assert curve.fit.slope == pytest.approx(ref.slope, rel=1e-12)
    assert (len(std), curve.fit.n, len(curve.levels)) == (15, 15, 5)
    assert curve.fit.slope == pytest.approx(-3.458, abs=5e-4)
    assert curve.fit.efficiency == pytest.approx(0.946, abs=5e-4)
    assert curve.fit.r2 > 0.999 and curve.quantity_source == "file"
    assert curve.lod.at_most and curve.lod.quantity == 625.0
    assert curve.loq.quantity == 625.0
    units = {u.unit: u for u in result.unknowns}
    assert set(units) == {"pop1_RNase P", "pop2_RNase P"}
    for unit in units.values():
        cqs = [w.cq for w in unit.wells]
        x0 = (np.mean(cqs) - ref.intercept) / ref.slope
        assert unit.log10_quantity == pytest.approx(x0, rel=1e-10)
        assert unit.low < unit.quantity < unit.high and unit.flags == ()
    # pop1 ~2,600 and pop2 ~4,800 copies: inside the 625-10,000 series
    assert 2500 < units["pop1_RNase P"].quantity < 2700
    assert 4700 < units["pop2_RNase P"].quantity < 4950


# ---- the command line ---------------------------------------------------------------------------


def test_cli_quantify_and_copies(capsys, tmp_path):
    from qpilot.cli import main

    out_csv = tmp_path / "q.csv"
    assert main(["quantify", str(STEPONE), "--csv", str(out_csv)]) == 0
    printed = capsys.readouterr().out
    assert "RNase P @ Run001" in printed and "efficiency 94.6 %" in printed
    assert "pop1_RNase P" in printed
    rows = out_csv.read_text(encoding="utf-8").splitlines()
    assert rows[0].startswith("unit,assay") and len(rows) == 3
    assert main(["copies", "--ng", "1", "--length", "3000", "--step", "10", "--levels", "3"]) == 0
    printed = capsys.readouterr().out
    assert "3.248e+08 copies" in printed and "level 3: 3.248e+06" in printed
    assert main(["copies", "--ng", "1", "--length", "0"]) == 2


def test_cli_quantify_with_person_quantities_for_level_labels(capsys):
    from qpilot.cli import main

    folder = CORPUS / "thermofisher" / "securebio-qs3-design-analysis-2.7"
    files = [str(p) for p in sorted(folder.glob("*.csv"))]
    assert main(["quantify", *files, "--target", "Cov2"]) == 1  # Std 1..5: no quantities
    assert "number the levels" in capsys.readouterr().out
    given = [f"--quantity=Std {i}={10 ** (6 - i):g}" for i in range(1, 6)]
    assert main(["quantify", *files, "--target", "Cov2", *given]) == 0
    printed = capsys.readouterr().out
    assert "Cov2 @" in printed and "quantities from design" in printed
    assert "D-231018-Negative Ctrl\tCov2\t0/3" in printed and "not detected in any well" in printed
