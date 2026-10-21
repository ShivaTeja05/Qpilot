"""The efficiency-model axis on hand-built tables (spec: scientist-spec-numbers.md §1, §2)."""

import math

import numpy as np
import pandas as pd
import pytest

from qpilot.qpcr.axes import AxisError
from qpilot.qpcr.axes import efficiency as eff
from qpilot.qpcr.quant import EXCLUDED

LOG2_NQ = {("p1", "G"): 30.0, ("p2", "G"): 31.0, ("p1", "R"): 29.0}
E_RUN = {("p1", "G"): 1.9, ("p2", "G"): 1.8, ("p1", "R"): 1.95}


def toy_table() -> pd.DataFrame:
    """Wells whose n0 is exactly Nq / E_run^Cq; a dilution series of 4 levels on p1/G."""
    rows = []
    for (run, target), log2_nq in LOG2_NQ.items():
        e_run = E_RUN[(run, target)]
        for i, (cq, own) in enumerate([(20.0, 1.92), (22.5, 1.88), (25.0, 0.9), (np.nan, np.nan)]):
            n0 = 2 ** (log2_nq - cq * math.log2(e_run)) if np.isfinite(cq) else np.nan
            rows.append(
                dict(
                    run_id=run,
                    well=f"A{i}",
                    sample=f"s{i}",
                    sample_type="unkn",
                    target=target,
                    cq=cq,
                    n0=n0,
                    eff_target=e_run,
                    eff_indiv=own,
                )
            )
    for j, copies in enumerate((1e5, 1e4, 1e3, 1e2)):
        cq = 15.0 + j * math.log(10) / math.log(1.9)  # E = 1.9 exactly
        rows.append(
            dict(
                run_id="p1",
                well=f"S{j}",
                sample=f"STD_{copies:g}",
                sample_type="std",
                target="G",
                cq=cq,
                n0=2 ** (30 - cq * math.log2(1.9)),
                eff_target=1.9,
                eff_indiv=1.9,
            )
        )
    return pd.DataFrame(rows)


def test_primary_is_passed_through():
    table = toy_table()
    assert eff.universe(table, "linregpcr").table is table
    with pytest.raises(AxisError, match="unknown efficiency option"):
        eff.universe(table, "guess")


def test_log2_nq_is_recovered_per_run_and_target():
    table = toy_table()
    nq = eff.log2_nq(table)
    for (run, target), value in LOG2_NQ.items():
        rows = (table["run_id"] == run) & (table["target"] == target)
        assert nq[rows].to_numpy() == pytest.approx(value)


def test_rebuild_is_exact_on_a_toy_table():
    table = toy_table()
    detected = table["n0"].notna()
    two = eff.universe(table, "assumed_2").table
    expect = table["run_id"].combine(table["target"], lambda r, t: LOG2_NQ[(r, t)]) - table["cq"]
    assert np.log2(two.loc[detected, "n0"]).to_numpy() == pytest.approx(expect[detected])
    assert two["n0"].isna().equals(table["n0"].isna())  # never turns a non-detect into a value
    mean = eff.universe(table, "amplicon_mean").table
    g = (table["target"] == "G") & detected & (table["sample_type"] == "unkn")
    pooled = (1.9 * 3 + 1.8 * 3) / 6  # study wells with a quantity: 3 on each run
    log2_nq = table["run_id"].map({"p1": 30.0, "p2": 31.0})
    want = log2_nq[g] - table.loc[g, "cq"] * math.log2(pooled)
    assert np.log2(mean.loc[g, "n0"]).to_numpy() == pytest.approx(want.to_numpy())


def test_per_well_excludes_wells_outside_the_valid_range():
    table = toy_table()
    u = eff.universe(table, "per_well")
    bad = (table["eff_indiv"] <= 1.0) & table["n0"].notna() & (table["sample_type"] == "unkn")
    assert u.n_excluded == int(bad.sum()) == 3
    assert u.table.loc[bad, EXCLUDED].all() and not u.table.loc[~bad, EXCLUDED].any()
    ok = table["eff_indiv"].eq(1.92)
    want = 30.0 - 20.0 * math.log2(1.92)
    first = ok & (table["run_id"] == "p1") & (table["target"] == "G")
    assert np.log2(u.table.loc[first, "n0"]).iloc[0] == pytest.approx(want)


def test_standard_curve_needs_three_levels_and_falls_back_per_amplicon():
    table = toy_table()
    curves = eff.standard_curves(table)
    assert list(curves) == [("p1", "G")]
    curve = curves[("p1", "G")]
    assert curve.efficiency == pytest.approx(1.9) and curve.levels == 4 and curve.r2 == 1.0
    two_levels = table[~table["sample"].isin(["STD_100", "STD_1000"])]
    assert eff.standard_curves(two_levels) == {}
    u = eff.universe(table, "standard_curve", curves)
    assert u.fallback == ("R",)  # R has no series; p2/G keeps LinRegPCR's mean (no curve there)
    quantities = {"STD_100000": 1.0, "STD_10000": 0.1, "STD_1000": 0.01, "STD_100": 0.001}
    same = eff.standard_curves(table, quantities)[("p1", "G")]
    assert same.efficiency == pytest.approx(1.9)  # only the scale of the quantities changed


def test_unavailable_options_are_named():
    table = toy_table()
    assert eff.unavailable(table, eff.standard_curves(table)) == {}
    one_run = table[table["run_id"] == "p1"]
    reasons = eff.unavailable(one_run, {})
    assert set(reasons) == {"amplicon_mean", "standard_curve"}
    assert "one run" in reasons["amplicon_mean"]


def test_variance_of_e_per_option():
    table = toy_table()
    assert eff.variance_of_e(table, "per_well") == {"G": 0.0, "R": 0.0}
    assert eff.variance_of_e(table, "assumed_2") == {"G": 0.0, "R": 0.0}
    primary = eff.variance_of_e(table, "linregpcr")
    assert primary["G"] == pytest.approx(np.var([1.92, 1.88, 1.92, 1.88], ddof=1) / 4)
    curves = eff.standard_curves(table)
    assert eff.variance_of_e(table, "standard_curve", curves)["G"] == pytest.approx(0.0, abs=1e-12)
    assert eff.variance_of_e(table, "standard_curve", curves)["R"] == primary["R"]
