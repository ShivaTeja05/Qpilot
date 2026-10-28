"""Technical replicates: every choice acts on each well, then a sample's wells become one value.

The planned rule is qPilot's own (``qpilot.qpcr.quant``: the mean ``log2 N0`` of the wells that
have a quantity, undetermined only when every well is), so the simulator's baseline gives
qPilot's numbers on a replicate design. The tables here are small and built by hand, so each
case has a known answer; the real triplicate plate (LightCycler 96, hmuY) checks the
outlier option against the Run Gate's own G-REP finding.
"""

from __future__ import annotations

import dataclasses
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from qpilot.qpcr.contrast import welch
from qpilot.qpcr.gate_rules import GateContext, range_quantile, replicate_spread, resolve_pack
from qpilot.qpcr.quant import EXCLUDED, log2_matrix, relative

from qsim.data import Study, study_arrays
from qsim.decisions import Space
from qsim.engine import Engine, range_tolerance, replicate_outliers
from qsim.study_space import space_for

NQ = 1e10  # one fluorescence threshold: log2 N0 = log2 NQ - Cq * log2 E
E = 1.9
HMUY = (
    Path(__file__).resolve().parents[2]
    / "tests/fixtures/corpus/rdml/lightcycler96-lc96p-hmuy/hmuy_hm_vs_dip_r123.lc96p"
)


def wells(sample: str, target: str, cqs, *, start: int = 1, note: str = "", run: str = "P1"):
    rows = []
    for k, cq in enumerate(cqs):
        rows.append(
            {
                "run_id": run,
                "well": f"{sample}{target}{start + k}",
                "sample": sample,
                "sample_type": "unkn",
                "target": target,
                "cq": np.nan if cq is None else float(cq),
                "n0": np.nan if cq is None else NQ / E ** float(cq),
                "eff_target": E,
                "eff_indiv": E,
                "note": note,
            }
        )
    return rows


REF = {"a1": 15.0, "a2": 15.2, "a3": 14.9, "b1": 15.1, "b2": 14.8, "b3": 15.05}


def ref_wells(sample: str) -> list[float]:
    c = REF[sample]
    return [c, c + 0.05, c - 0.05]


def ref_of(sample: str) -> float:
    """The sample's control-gene value: the mean log2 N0 of its three REF wells."""
    return float(np.mean([log2_n0(c) for c in ref_wells(sample)]))


def triplicates(goi: dict[str, list]) -> pd.DataFrame:
    """A plate: per sample, its GOI wells and three REF wells."""
    rows = []
    for sample, cqs in goi.items():
        rows += wells(sample, "GOI", cqs)
        rows += wells(sample, "REF", ref_wells(sample))
    return pd.DataFrame(rows)


GROUPS = (frozenset({"a1", "a2", "a3"}), frozenset({"b1", "b2", "b3"}))
BASE = {
    "a1": [20.0, 20.1, 20.2],
    "a2": [20.5, 20.4, 20.6],
    "a3": [19.8, 19.9, 20.0],
    "b1": [22.0, 22.2, 22.1],
    "b2": [22.6, 22.4, 22.5],
    "b3": [21.9, 22.0, 22.1],
}


def study_of(table: pd.DataFrame, groups=GROUPS) -> Study:
    matrix = log2_matrix(table)
    arrays, reps = study_arrays(table, matrix)
    genes = list(matrix.columns)
    return Study(
        curves=table,
        input_sha256="test",
        samples=list(matrix.index),
        genes=genes,
        candidates=("REF",),
        primary_refs=("REF",),
        marker="",
        items=[g for g in genes if g != "REF"],
        groups={0.15: groups},
        replicates=reps,
        **arrays,
    )


def engine_of(study: Study) -> Engine:
    space, _ = space_for(study)
    decisions = tuple(  # the design's one comparison (as the qPilot adapter does)
        dataclasses.replace(d, options=tuple(o for o in d.options if o.value == 0.15))
        if d.id == "cut"
        else d
        for d in space.decisions
    )
    return Engine(study, Space(decisions, space.baseline, notes=space.notes))


def log2_n0(cq: float) -> float:
    return math.log2(NQ) - cq * math.log2(E)


def unit_values(engine: Engine, **changes) -> pd.Series:
    """Each sample's GOI value relative to REF (log2) under ``changes``."""
    cell = engine.space.to_index(changes)
    rel, valid = engine.relative(
        engine.matrix_of(engine.values_of(cell)), engine.ids_of(cell)["refs"]
    )
    column = engine.items.index("GOI")
    values = np.where(valid[:, column], rel[:, column], np.nan)
    return pd.Series(values, index=engine.study.samples)


def test_every_well_is_kept_and_the_summary_is_qpilots_matrix():
    table = triplicates({**BASE, "a1": [20.0, None, 20.2]})
    study = study_of(table)
    reps = study.replicates
    assert reps is not None and reps.present.shape == (6, 2, 3) and reps.present.all()
    assert reps.most == 3
    np.testing.assert_array_equal(study.log2_n0, log2_matrix(table).to_numpy())
    # a value's first well names its position; the keys name every well
    assert study.well[0, 0] == "a1GOI1"
    assert list(reps.keys()[0, 0]) == ["P1/a1GOI1", "P1/a1GOI2", "P1/a1GOI3"]


def test_one_well_per_sample_has_no_replicates_and_no_replicate_choice():
    table = pd.DataFrame(
        [r for s, cqs in BASE.items() for t in ("GOI", "REF") for r in wells(s, t, cqs[:1])]
    )
    study = study_of(table)
    assert study.replicates is None
    assert "replicates" not in engine_of(study).space.names


def test_the_planned_rule_is_qpilots_unit_mean():
    table = triplicates({**BASE, "b2": [22.6, None, 22.5]})  # one replicate never amplified
    engine = engine_of(study_of(table))
    assert engine.space.baseline["replicates"] == "mean"
    ours = unit_values(engine)
    theirs = relative(log2_matrix(table), "GOI", ["REF"], "drop")
    pd.testing.assert_series_equal(ours, theirs.reindex(ours.index), check_names=False, atol=1e-12)
    assert ours["b2"] == pytest.approx(np.mean([log2_n0(22.6), log2_n0(22.5)]) - ref_of("b2"))
    base = engine.evaluate(engine.space.baseline_index())
    a, b = ours[sorted(GROUPS[0])], ours[sorted(GROUPS[1])]
    w = welch(a.to_numpy(), b.to_numpy())
    assert base["log2fc"][0] == pytest.approx(w.diff, abs=1e-12)
    assert base["p"][0] == pytest.approx(w.p, rel=1e-9)


def test_a_sample_is_undetermined_only_when_every_well_is():
    table = triplicates({**BASE, "b1": [None, None, None]})
    engine = engine_of(study_of(table))
    dropped = unit_values(engine)
    assert math.isnan(dropped["b1"])
    capped = unit_values(engine, nondetect="cap_min")
    theirs = relative(log2_matrix(table), "GOI", ["REF"], "cap")
    assert capped["b1"] == pytest.approx(theirs["b1"], abs=1e-12)
    lowest = log2_matrix(table)["GOI"].min()  # the lowest amount detected for the gene
    assert capped["b1"] == pytest.approx(lowest - ref_of("b1"), abs=1e-12)
    # the spreadsheet shortcut: Cq 40 in each undetermined well, then the mean
    cq40 = unit_values(engine, nondetect="cq40")
    assert cq40["b1"] == pytest.approx(log2_n0(40.0) - ref_of("b1"), abs=1e-9)
    assert cq40["a1"] == pytest.approx(dropped["a1"], abs=1e-12)


def test_flags_and_late_wells_act_on_single_wells():
    rows = []
    for sample, cqs in BASE.items():
        rows += wells(sample, "REF", ref_wells(sample))
        if sample == "a2":
            rows += wells(sample, "GOI", cqs[:2])
            rows += wells(sample, "GOI", [24.0], start=3, note="PCR efficiency outlier")
        elif sample == "b3":
            rows += wells(sample, "GOI", [21.9, 22.0, 36.0])
        else:
            rows += wells(sample, "GOI", cqs)
    engine = engine_of(study_of(pd.DataFrame(rows)))
    planned = unit_values(engine)
    kept = unit_values(engine, flagged="drop_eff")
    a2, b3 = ref_of("a2"), ref_of("b3")
    assert planned["a2"] == pytest.approx(np.mean([log2_n0(c) for c in (20.5, 20.4, 24.0)]) - a2)
    assert kept["a2"] == pytest.approx(np.mean([log2_n0(c) for c in (20.5, 20.4)]) - a2)
    late = unit_values(engine, late_cq="cq35")
    assert late["b3"] == pytest.approx(np.mean([log2_n0(c) for c in (21.9, 22.0)]) - b3)
    assert planned["b3"] == pytest.approx(np.mean([log2_n0(c) for c in (21.9, 22.0, 36.0)]) - b3)


def test_a_dropped_value_or_well():
    engine = engine_of(study_of(triplicates(BASE)))
    reps = engine.study.replicates
    whole = np.zeros(engine.study.cq.shape, bool)
    whole[engine.study.samples.index("a1"), engine.study.genes.index("GOI")] = True
    cell = engine.space.baseline_index()
    values, _ = engine.matrix_of(engine.values_of(cell), whole)
    assert math.isnan(values[0, engine.study.genes.index("GOI")])
    one = np.zeros(reps.present.shape, bool)
    one[0, engine.study.genes.index("GOI"), 0] = True
    values, _ = engine.matrix_of(engine.values_of(cell), one)
    assert values[0, 0] == pytest.approx(np.mean([log2_n0(20.1), log2_n0(20.2)]))


def test_median_and_outlier_options():
    goi = {**BASE, "a1": [20.0, 20.1, 21.5], "b2": [22.6, 23.9]}  # a1: one far well; b2: two
    engine = engine_of(study_of(triplicates(goi)))
    assert engine.space.decision("replicates").ids == ["mean", "median", "drop_outlier"]
    a1 = ref_of("a1")
    median = unit_values(engine, replicates="median")
    assert median["a1"] == pytest.approx(log2_n0(20.1) - a1)
    outlier = unit_values(engine, replicates="drop_outlier")
    assert outlier["a1"] == pytest.approx(np.mean([log2_n0(20.0), log2_n0(20.1)]) - a1)
    planned = unit_values(engine)
    # within the expected spread (a2), or two wells (b2): nothing is left out
    assert outlier["a2"] == pytest.approx(planned["a2"])
    assert outlier["b2"] == pytest.approx(planned["b2"])


def test_the_tolerance_is_g_reps_without_a_standard_curve():
    n = np.array([2, 3, 4, 3, 3])
    mean_cq = np.array([20.0, 20.0, 20.0, 32.0, 36.0])
    tol = range_tolerance(n, mean_cq, np.full(5, E))
    for i in range(3):
        assert tol[i] == pytest.approx(range_quantile(int(n[i])) * 0.15 / math.log(E))
    assert tol[3] == 2.0  # Cq 30-35: low copy numbers possible, at least two cycles
    use = np.ones((1, 1, 3), bool)
    late = replicate_outliers(np.array([[[36.0, 36.2, 39.0]]]), np.full((1, 1, 3), E), use)
    assert not late.any()  # above Cq 35 the spread is sampling: not judged


def test_the_outlier_option_leaves_out_the_wells_g_rep_flags_on_a_real_plate():
    """LightCycler 96, P. endodontalis hmuY / 16S rRNA in triplicate (Śmiga & Olczak 2025)."""
    from qpilot.qpcr.curves import analyse_study

    curves = analyse_study(HMUY, None, ("sybr_green_i_16s_rrna",))
    ctx = GateContext(table=curves)
    flagged = {
        well
        for finding in replicate_spread(resolve_pack().rule("G-REP"), ctx)
        for well in finding.flagged
    }
    unknown = curves[curves["sample_type"] == "unkn"]
    matrix = log2_matrix(unknown)
    _, reps = study_arrays(unknown, matrix)
    use = reps.present & ~np.isnan(reps.cq) & ~np.isnan(reps.log2_n0)
    ours = set(reps.keys()[replicate_outliers(reps.cq, reps.eff_assay, use)])
    assert ours == flagged and len(ours) == 1


def test_excluded_wells_are_marked_per_well():
    table = triplicates(BASE)
    table[EXCLUDED] = table["well"].eq("a1GOI1")
    study = study_of(table)
    assert int(study.replicates.excluded.sum()) == 1
    # the summary leaves the excluded well out, as qPilot's matrix does
    assert study.log2_n0[0, 0] == pytest.approx(np.mean([log2_n0(20.1), log2_n0(20.2)]))
