"""Science review J10: several samples of one unit, G-REP's ties, the audit's tolerance."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from qsim.engine import _combine, range_tolerance, replicate_outliers

from qpilot.qpcr.gate_rules import range_quantile
from qpilot.qpcr.quant import log2_matrix


def _wells(rows):
    return pd.DataFrame(
        [
            {"run_id": "p1", "well": f"A{i}", "sample": s, "sample_type": "unkn", "target": "G",
             "cq": 20.0, "n0": n0}
            for i, (s, n0) in enumerate(rows, start=1)
        ]
    )  # fmt: skip


def test_a_unit_of_several_samples_is_the_mean_of_its_samples_means():
    """Two RNA preparations of one animal: one in three wells (log2 1), one in one (log2 4).
    The unit is 2.5, not the flat 1.75 that weighed the first preparation three times."""
    table = _wells([("prep1", 2.0), ("prep1", 2.0), ("prep1", 2.0), ("prep2", 16.0)])
    units = {"prep1": "mouse1", "prep2": "mouse1"}
    assert log2_matrix(table, units).loc["mouse1", "G"] == pytest.approx(2.5)
    # one sample per unit: the plain mean of its wells, bit for bit
    one = _wells([("s1", 2.0), ("s1", 8.0), ("s1", 16.0), ("s2", 4.0)])
    flat = one.assign(log2=np.log2(one["n0"])).groupby("sample")["log2"].mean()
    got = log2_matrix(one, {"s1": "u1", "s2": "u2"})["G"]
    assert got.loc["u1"] == flat.loc["s1"] and got.loc["u2"] == flat.loc["s2"]


def test_the_audit_combines_a_units_samples_the_same_way():
    values = np.array([[[1.0, 1.0, 1.0, 4.0]]])
    use = np.ones_like(values, dtype=bool)
    sub = np.array([[[0, 0, 0, 1]]])
    assert _combine(values, use, "mean", sub)[0, 0] == pytest.approx(2.5)
    assert _combine(values, use, "mean")[0, 0] == pytest.approx(1.75)
    one = np.array([[[0, 0, 0, 0]]])  # one sample: the flat mean, exactly
    assert _combine(values, use, "mean", one)[0, 0] == _combine(values, use, "mean")[0, 0]


def test_the_audits_tolerance_is_g_reps_with_the_poisson_term():
    """With a standard curve on the plate G-REP adds 1/N copies to the pipetting variance; the
    audit used the pipetting term only, so it could leave out a well G-REP accepts."""
    n, cq, e = np.array([3]), np.array([27.4]), np.array([2.0])
    pipetting = range_quantile(3) * 0.15 / math.log(2)
    assert range_tolerance(n, cq, e)[0] == pytest.approx(pipetting)
    with_copies = range_tolerance(n, cq, e, np.array([10.0]))[0]
    assert with_copies == pytest.approx(range_quantile(3) * math.sqrt(0.15**2 + 0.1) / math.log(2))
    cqs = np.array([[[27.0, 27.2, 28.0]]])  # range 1.0: outside pipetting (0.72), inside 1.67
    use = np.ones_like(cqs, dtype=bool)
    eff = np.full(cqs.shape, 2.0)
    assert replicate_outliers(cqs, eff, use).sum() == 1  # copies unknown: C3 is left out
    slope = np.full(cqs.shape, -3.32)
    intercept = np.full(cqs.shape, 27.4 + 3.32)  # 10 copies at the wells' mean Cq
    assert replicate_outliers(cqs, eff, use, slope, intercept).sum() == 0  # as G-REP


def test_the_audit_proposes_no_outlier_on_a_tie():
    cqs = np.array([[[20.0, 20.5, 21.0]]])  # spread 1.0, the two outer wells equally far
    use = np.ones_like(cqs, dtype=bool)
    eff = np.full(cqs.shape, 2.0)
    assert replicate_outliers(cqs, eff, use).sum() == 0
    skewed = np.array([[[20.0, 20.1, 21.0]]])
    assert replicate_outliers(skewed, eff, use)[0, 0].tolist() == [False, False, True]
