"""Science review J2 and J6: standards that look wrong, the exact interval, LOD words.

Real data: the QuantStudio 7 Pro eDNA standard curve (corpus), with the three flat wells a6b05fe
took off it put back by a person's well calls (A7, A8, D9: LinRegPCR says no amplification), and
StepOne's RNase P curve (a good curve). The exact interval is checked against the independent
oracle (``validation/excellence/absolute_oracle.py``).
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from qpilot.qpcr import absolute as ab
from validation.excellence import absolute_oracle as ao

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus" / "rdml"
EDNA = (
    CORPUS
    / "quantstudio7pro-rdml-1.2-edna"
    / "SupplementaryMaterials2_qPCR_ConcentrationStandardCurve.rdml"
)  # noqa: E501
STEPONE = CORPUS / "stepone-2.3-rdml-1.0" / "stepone_std.rdml"
FLAT = ("A7", "A8", "D9")


def _edna(put_back: bool):
    from qpilot.qpcr.absolute_study import declared_quantities
    from qpilot.qpcr.curves import analyse_study

    table = analyse_study(EDNA, None, ())
    std = table[table["sample_type"] == "std"]
    calls = {f"{r}/{w}": True for r, w in zip(std["run_id"], std["well"], strict=True) if w in FLAT}
    result = ab.quantify(
        table, calls=calls if put_back else None, declared=declared_quantities(EDNA)
    )
    (curve,) = [c for c in result.curves if c.fit is not None]
    return curve


def test_the_flat_standards_are_pointed_at_with_what_leaving_them_out_does():
    curve = _edna(put_back=True)
    assert curve.fit.efficiency == pytest.approx(1.536, abs=0.001) and curve.fit.r2 < 0.42
    found = {s.well: s for s in curve.suspects}
    assert set(found) == set(FLAT)  # only the three flat wells, none of the good ones
    a8 = found["A8"]
    assert a8.why == ("order", "residual") and a8.residual_z == pytest.approx(-7.30, abs=0.01)
    assert "its Cq 9.9 at 2.41 is earlier than 20 of the 20 standard wells holding" in a8.words
    assert a8.efficiency == pytest.approx(1.140, abs=0.001) and a8.r2 == pytest.approx(0.743, 1e-3)
    assert all(s.why == ("order",) for w, s in found.items() if w != "A8")
    clean = _edna(put_back=False)  # LinRegPCR's call respected (a6b05fe): nothing to point at
    assert clean.suspects == () and clean.fit.efficiency == pytest.approx(0.871, abs=0.001)


def test_g_and_the_exact_interval_on_a_poor_curve():
    """g 0.21: at the mean Cq with three wells the classical interval is [-0.20, 5.80] log10,
    the exact (Fieller) one [-0.56, 6.17]; qPilot now reports the exact one."""
    curve = _edna(put_back=True)
    fit = curve.fit
    assert fit.g == pytest.approx(0.206, abs=0.001) and curve.exact_interval
    x0, s = fit.inverse(fit.y_mean, 3)
    assert (x0 - fit.t_crit * s, x0 + fit.t_crit * s) == pytest.approx((-0.20, 5.80), abs=0.01)
    exact = fit.inverse_exact(fit.y_mean, 3)
    assert exact == pytest.approx((-0.56, 6.17), abs=0.01)
    det = [p for p in curve.points if p.detected and p.cq is not None]
    o = ao.fit([math.log10(p.quantity) for p in det], [p.cq for p in det])
    for y0 in (fit.y_mean, 20.0, 35.0):
        for k in (1, 3):
            assert fit.inverse_exact(y0, k) == pytest.approx(ao.inverse_exact(o, y0, k), abs=1e-9)
    estimate = ab._estimate({curve.id: [fit.y_mean] * 3}, {curve.id: curve})
    assert estimate[1:] == pytest.approx(exact, abs=1e-12)


def test_a_good_curve_keeps_the_classical_interval():
    from qpilot.qpcr.absolute_study import quantify_file

    result = quantify_file(STEPONE)
    (curve,) = [c for c in result.curves if c.fit is not None]
    assert curve.g < ab.G_EXACT and not curve.exact_interval and curve.suspects == ()
    fit = curve.fit
    estimate = ab._estimate({curve.id: [fit.y_mean] * 3}, {curve.id: curve})
    x0, s = fit.inverse(fit.y_mean, 3)
    assert estimate == pytest.approx((x0, x0 - fit.t_crit * s, x0 + fit.t_crit * s), abs=1e-12)


def test_an_unbounded_slope_gives_no_interval():
    fit = ab.fit_line([0, 1, 2, 3], [30.0, 25.0, 31.0, 26.0])
    assert fit is not None and fit.g >= 1
    assert all(math.isnan(v) for v in fit.inverse_exact(28.0, 1))


def test_the_curve_limits_cite_taylor_2010():
    assert ab.CURVE_LIMITS_SOURCE == "Taylor et al. 2010"
    curve = _edna(put_back=True)
    assert any("(Taylor et al. 2010)" in w for w in curve.warnings)
    assert not any("MIQE" in w for w in curve.warnings)


def test_the_lod_says_how_many_wells_per_level_stand_behind_it():
    """Science review J6: below 20 wells a level, 95 % means every well; say so, and recommend
    ten replicates around the limit (Forootan 2017; Klymus 2020)."""
    from qpilot.qpcr.absolute_study import quantify_file

    (curve,) = [c for c in quantify_file(STEPONE).curves if c.fit is not None]
    assert {lv.n_wells for lv in curve.levels} == {3}
    assert "with 3 wells per level, 95 % of a level's wells means all of them" in curve.lod.words
    assert "at least 10 replicates" in curve.lod.words and "Klymus" in curve.lod.words
    edna = _edna(put_back=False)
    assert "with 4 wells per level" in edna.lod.words
    many = [ab.Level(q, 20, 20, 25.0, 0.2, q, 0.1) for q in (1e4, 1e3, 1e2)]
    assert ab.few_wells_words(many, ab.AbsoluteSettings()) == ""
    assert "Klymus KE" in " ".join(ab.REFERENCES) and "Taylor S" in " ".join(ab.REFERENCES)
