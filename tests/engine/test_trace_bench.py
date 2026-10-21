"""The planted-fault benchmark for Trace (plan T3).

Synthetic tests run in CI on the toy per-well table of ``test_trace`` (plus a one-copy standard
on every plate, so a planted Cq has room before the latest Cq the table reports). The
``demo_data`` tests run a small benchmark on the 64-plate demo against bars set just below the
measured 50-case scorecard in ``methods/trace.md``.
"""

import json
import math

import numpy as np
import pandas as pd
import pytest

from qpilot.qpcr import trace_bench as B
from qpilot.qpcr.study import StudySettings
from tests.engine.test_trace import TOY, _cq, toy_table


def bench_toy(table=None):
    """The toy study with a one-copy standard (Cq 40) on every plate."""
    table = toy_table() if table is None else table
    std = table[table["sample"] == "STD_15"].drop_duplicates("run_id").copy()
    std["sample"], std["well"] = "STD_1", "H5"
    std["cq"], std["n0"] = _cq(0.0), 1.0
    return pd.concat([table, std], ignore_index=True)


def planted_rows(before, after):
    """Index labels of the rows a plant changed (NaN equal to NaN)."""
    changed = ~((before == after) | (before.isna() & after.isna())).all(axis=1)
    return list(before.index[changed])


@pytest.fixture(scope="module")
def toy():
    table = bench_toy()
    return table, B.prepare_baseline(table, TOY)


@pytest.fixture(scope="module")
def faulty_toy():
    """The toy with real faults: S1 on s03, S2 on s15, an S5 note on s11, an S6 well on s05,
    and two samples in no comparison (s07, s09)."""
    t = toy_table()
    s03 = (t["sample"] == "s03") & (t["target"] == "R2")
    t.loc[s03, "cq"] += 6.0
    t.loc[s03, "n0"] /= t.loc[s03, "eff_target"] ** 6.0
    s15 = (t["sample"] == "s15") & (t["sample_type"] == "unkn")
    t.loc[s15, "cq"] += 3.0
    t.loc[s15, "n0"] /= t.loc[s15, "eff_target"] ** 3.0
    t.loc[(t["sample"] == "s11") & (t["target"] == "UP"), "note"] = "PCR efficiency outlier"
    late = (t["sample"] == "s05") & (t["target"] == "FLAT")
    t.loc[late, ["cq", "n0"]] = [36.0, 2.0 ** ((40.0 - 36.0) * np.log2(1.9))]
    ntc = (t["run_id"] == "FLAT_20260101") & (t["well"] == "H10")
    t.loc[ntc, ["cq", "n0", "amplification"]] = [39.0, 0.5, True]
    for sample, gene in (("s07", "R2"), ("s09", "M(1)")):  # in no comparison (S7)
        empty = (t["sample"] == sample) & (t["target"] == gene)
        t.loc[empty, ["cq", "n0", "amplification"]] = [np.nan, np.nan, False]
    table = bench_toy(t)
    return table, B.prepare_baseline(table, TOY)


# ---------- the plant model ----------


@pytest.mark.parametrize("fault", ["F1", "F2", "F3", "F6"])
def test_plant_shifts_cq_and_n0_consistently(toy, fault):
    table, bl = toy
    before = table.copy()
    spec = B.FAULT_SPECS[fault]
    out, truth = B.plant(table, fault, 4, baseline=bl)
    assert table.equals(before)  # the input is never modified
    rows = planted_rows(table, out)
    keys = sorted(f"{table.at[r, 'run_id']}/{table.at[r, 'well']}" for r in rows)
    assert keys == truth.wells and keys
    e = table.loc[rows, "eff_target"]
    np.testing.assert_allclose(out.loc[rows, "cq"], table.loc[rows, "cq"] + spec.cycles)
    # N0 = Nq / E**Cq: the threshold Nq of every planted well is unchanged
    nq_before = np.log(table.loc[rows, "n0"]) + table.loc[rows, "cq"] * np.log(e)
    nq_after = np.log(out.loc[rows, "n0"]) + out.loc[rows, "cq"] * np.log(e)
    np.testing.assert_allclose(nq_after, nq_before, rtol=0, atol=1e-9)
    np.testing.assert_allclose(
        out.loc[rows, "eff_indiv"], table.loc[rows, "eff_indiv"] + spec.eff_delta
    )
    assert (out.loc[rows, "eff_target"] == e).all()
    assert out.drop(index=rows).equals(table.drop(index=rows))
    assert (out.loc[rows, "cq"] <= bl.max_cq).all()
    if fault in ("F2", "F3"):
        unknown = table[(table["sample"] == truth.sample) & (table["sample_type"] == "unkn")]
        assert len(rows) == len(unknown) and truth.well is None
        assert truth.root == truth.sample
    else:
        assert len(rows) == 1 and truth.well == table.at[rows[0], "well"]
        assert truth.root == (keys[0] if fault == "F6" else truth.sample)


def test_plant_ntc_and_empty_well(toy):
    table, bl = toy
    out, truth = B.plant(table, "F4", 2, baseline=bl)
    (row,) = planted_rows(table, out)
    ntc = out.loc[row]
    assert ntc["sample_type"] == "ntc" and truth.sample is None
    assert (ntc["cq"], bool(ntc["amplification"]), ntc["excluded"]) == (
        30.0,
        True,
        B.NTC_AMPLIFIED,
    )
    plate = table[(table["run_id"] == truth.plate) & table["cq"].notna()]
    nq = np.median(plate["n0"] * plate["eff_target"] ** plate["cq"])
    assert ntc["n0"] * ntc["eff_target"] ** 30.0 == pytest.approx(nq)
    assert truth.root == truth.gene and truth.gene == truth.target  # toy plates are genes'
    out, truth = B.plant(table, "F5", 2, baseline=bl)
    (row,) = planted_rows(table, out)
    empty = out.loc[row]
    assert truth.target in TOY.candidates and empty["sample"] == truth.sample
    assert math.isnan(empty["cq"]) and math.isnan(empty["n0"]) and not empty["amplification"]
    assert empty["note"] == B.NO_AMPLIFICATION_NOTE


def test_plant_is_seeded(toy):
    table, bl = toy
    for fault in B.FAULTS:
        a, ta = B.plant(table, fault, 11, baseline=bl)
        b, tb = B.plant(table, fault, 11, baseline=bl)
        assert ta == tb and a.equals(b)
        drawn = {tuple(B.plant(table, fault, s, baseline=bl)[1].wells) for s in range(8)}
        assert len(drawn) > 1, fault
    # without a baseline the same address is drawn
    assert B.plant(table, "F1", 11, settings=TOY)[1] == B.plant(table, "F1", 11, baseline=bl)[1]


def test_pools_set_the_real_faults_aside(faulty_toy):
    _, bl = faulty_toy
    assert set(bl.real) == {"s03", "s15"}
    for fault, pool in bl.pools.items():
        samples = {address[0] for address in pool}
        if fault == "F4":
            assert "FLAT" not in {address[1] for address in pool}  # its NTC amplifies
            assert "M(1)" not in {address[1] for address in pool}  # the marker feeds nothing
        else:
            assert pool and not samples & {"s03", "s15"}, fault
            assert not samples & {"s07", "s09"}  # in no comparison


def test_known_places_are_set_aside(faulty_toy):
    table, bl = faulty_toy
    with_place = {"s05", "s11"}  # their own traces show an S6 or an S5 place before planting
    case = next(
        c
        for c in B.bench_items(200, 0, ["F1"])
        if B.plant(table, "F1", c.seed, baseline=bl)[1].sample in with_place
    )
    result = B.run_case(case, bl)
    assert result.n_known_places == 1
    assert (result.rank, result.top1, result.false_places) == (1, True, 0)
    assert result.hit_checks == ["S1"]


# ---------- cases and scoring ----------


def test_bench_items_and_harness_cases(toy):
    items = B.bench_items(3, 2, ["F2", "F6"])
    assert [(c.id, c.fault, c.seed) for c in items] == [
        ("trace_f2_01", "F2", 2000),
        ("trace_f2_02", "F2", 2001),
        ("trace_f2_03", "F2", 2002),
        ("trace_f6_01", "F6", 2000),
        ("trace_f6_02", "F6", 2001),
        ("trace_f6_03", "F6", 2002),
    ]
    assert len(B.bench_items()) == 50 * len(B.FAULTS)
    assert B.bench_items(120, 0, ["F1"])[-1].id == "trace_f1_120"
    _, bl = toy
    by_mapping = B.run_case({"fault": "F6", "seed": 2001, "score": "refusal"}, bl)
    assert by_mapping.id == "trace_f6_seed_2001"
    assert by_mapping.model_dump(exclude={"id"}) == B.run_case(items[4], bl).model_dump(
        exclude={"id"}
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"n_per_fault": 0}, "at least 1"),
        ({"n_per_fault": 1001}, "at most"),
        ({"seed": -1}, "seed"),
        ({"seed": True}, "seed"),
        ({"faults": ["F7"]}, "unknown fault"),
        ({"faults": ["F1", "F1"]}, "at most once"),
        ({"faults": []}, "at least one"),
    ],
)
def test_bench_items_errors(kwargs, message):
    with pytest.raises(B.BenchError, match=message):
        B.bench_items(**kwargs)


def test_plant_errors(toy):
    table, bl = toy
    with pytest.raises(B.BenchError, match="unknown fault"):
        B.plant(table, "F9", 0, baseline=bl)
    with pytest.raises(B.BenchError, match="seed"):
        B.plant(table, "F1", -3, baseline=bl)
    other = table.iloc[::-1].reset_index(drop=True)
    with pytest.raises(B.BenchError, match="another per-well table"):
        B.plant(other, "F1", 0, baseline=bl)
    with pytest.raises(B.BenchError, match="lacks the columns"):
        B.prepare_baseline(table.drop(columns=["eff_target"]), TOY)
    dirty = table.copy()  # every NTC amplifies: no plate to contaminate
    ntc = dirty["sample_type"] == "ntc"
    dirty.loc[ntc, ["cq", "n0", "amplification"]] = [38.0, 1.0, True]
    with pytest.raises(B.BenchError, match="no address"):
        B.plant(dirty, "F4", 0, settings=TOY)
    with pytest.raises(B.BenchError, match="F4"):
        B.run_benchmark(dirty, TOY, n_per_fault=1, faults=["F1", "F4"])


def test_toy_benchmark_meets_the_plan_on_a_clean_study(toy):
    table, _ = toy
    card = B.run_benchmark(table, TOY, n_per_fault=8, seed=0)
    assert card.faults == list(B.FAULTS) and len(card.cases) == 8 * len(B.FAULTS)
    for fid, score in card.by_fault.items():
        assert score.n == 8 and score.n_errors == 0, fid
        assert score.meets_expected, fid
        assert score.measured == 1.0, fid
        assert score.false_places_max == 0, fid
        assert score.n_refs_changed == 0, fid
    for fid in ("F1", "F2", "F3"):
        assert card.by_fault[fid].study_top1 == 8 == card.by_fault[fid].study_top1_with_known
    f2 = [c for c in card.cases if c.fault == "F2"]
    assert all(c.hit_checks == ["S2"] for c in f2)
    f3 = [c for c in card.cases if c.fault == "F3"]
    assert all("S4" in c.hit_checks for c in f3)
    f6 = [c for c in card.cases if c.fault == "F6"]
    assert all(c.detail["limit"] == "single_target_well" for c in f6)
    assert all(c.rank is None and c.top1 is None for c in f6)
    assert all(c.refusal is None for c in card.cases if c.fault != "F6")
    assert all(len(c.flagged_elsewhere) == c.new_flags_elsewhere for c in card.cases)
    assert all(c.false_place_checks == [] for c in card.cases)
    assert card.input["n_compared"] == 80 and card.baseline["n_real_faults_set_aside"] == 0


def test_benchmark_is_deterministic(toy):
    table, _ = toy
    a = B.run_benchmark(table, TOY, n_per_fault=3, seed=5)
    b = B.run_benchmark(table.copy(), TOY, n_per_fault=3, seed=5)
    assert a.results_json() == b.results_json()
    assert a.results_sha256() == b.results_sha256()
    c = B.run_benchmark(table, TOY, n_per_fault=3, seed=6)
    assert [x.truth for x in c.cases] != [x.truth for x in a.cases]
    data = json.loads(a.to_json())
    assert "timing" in data and "timing" not in json.loads(a.results_json())
    assert set(data["timing"]["per_fault"]) == set(B.FAULTS)
    assert "NaN" not in a.to_json() and "Infinity" not in a.to_json()
    assert B.TraceScorecard.model_validate_json(a.to_json()).results_json() == a.results_json()


def test_a_failing_case_is_a_scored_miss(toy, monkeypatch):
    table, _ = toy
    real = B.run_case

    def flaky(case, baseline):
        if case.id == "trace_f1_02":
            raise RuntimeError("boom")
        return real(case, baseline)

    monkeypatch.setattr(B, "run_case", flaky)
    card = B.run_benchmark(table, TOY, n_per_fault=2, seed=0, faults=["F1"])
    score = card.by_fault["F1"]
    assert (score.n, score.n_errors, score.top1) == (2, 1, 1)
    assert not score.meets_expected
    failed = card.cases[1]
    assert failed.error == "RuntimeError: boom" and failed.top1 is None


def test_markdown_table(toy):
    table, _ = toy
    card = B.run_benchmark(table, TOY, n_per_fault=1, seed=0)
    lines = card.markdown().splitlines()
    assert len(lines) == 2 + len(B.FAULTS)
    assert lines[2].startswith("| F1 dead reference well | one reference well: Cq +8 |")
    assert "refusal ≥ 100 %" in lines[-1] and "| yes |" in lines[-1]


# =============================================================================================
# The demo study (bars set just below the measured 50-case scorecard; methods/trace.md)
# =============================================================================================


@pytest.fixture(scope="module")
def demo_bench(demo_curves):
    return B.run_benchmark(demo_curves, n_per_fault=10, seed=0)


@pytest.mark.demo_data
def test_demo_benchmark_bars(demo_bench):
    card = demo_bench
    s = card.by_fault
    assert all(score.n == 10 and score.n_errors == 0 for score in s.values())
    assert s["F1"].top1 >= 8  # UBC(2), the noisiest reference, hides some +8-cycle wells
    assert s["F3"].top3 >= 9 and s["F4"].top1 >= 9 and s["F5"].top1 >= 9
    assert s["F6"].refusals == 10
    # F2 falls short of the plan: S2 needs more than four cycles on this panel
    assert 1 <= s["F2"].top3 <= 5
    for fid in ("F1", "F3", "F4", "F5"):
        assert s[fid].false_places_max <= 1, fid
    assert all(score.new_flags_elsewhere_mean <= 1 for score in s.values())
    assert card.input["n_compared"] == 347 and card.baseline["n_real_faults_set_aside"] == 18
    assert card.timing["per_case_mean_s"] < 2.0


@pytest.mark.demo_data
def test_demo_real_faults_are_set_aside(demo_curves):
    bl = B.prepare_baseline(demo_curves, StudySettings())
    assert {"2016", "1924", "1772", "2714", "2748"} <= set(bl.real)
    for fault, pool in bl.pools.items():
        if fault != "F4":
            assert not {address[0] for address in pool} & set(bl.real), fault
    plates = {address[1] for address in bl.pools["F4"]}
    assert "MYCN(4)" not in plates and "ALUsq(Eurogentec)" not in plates  # marker; dirty NTCs
    assert len(bl.pools["F4"]) == 52  # 64 plates, less the marker's and 11 with amplifying NTCs


@pytest.mark.demo_data
def test_demo_benchmark_is_deterministic(demo_curves, demo_bench):
    again = B.run_benchmark(demo_curves.copy(), n_per_fault=2, seed=0)
    first_two = [c for c in demo_bench.cases if c.id.endswith(("_01", "_02"))]
    assert [c.model_dump() for c in again.cases] == [c.model_dump() for c in first_two]
