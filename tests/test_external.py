"""Tests on new public data (docs/review/32): converters, fixed components, end to end."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from qpilot.qpcr.curves import analyse_study

from qsim import external, known_answers

RESULTS = Path(__file__).resolve().parents[1] / "results"


def _sigmoid(n0: float, cycles: int = 40, eff: float = 1.9) -> np.ndarray:
    c = np.arange(1, cycles + 1)
    signal = n0 * eff**c
    return 1.0 + 20.0 * signal / (signal + 1e9)


def test_table_to_rdml_round_trip(tmp_path):
    rows = []
    for i, (sample, n0) in enumerate([("high", 1e4), ("high", 1e4), ("low", 1e2), ("low", 1e2)]):
        for cycle, f in enumerate(_sigmoid(n0), start=1):
            rows.append(
                {
                    "well": f"A{i + 1}",
                    "sample": sample,
                    "sample_type": "unkn",
                    "target": "T",
                    "cycle": cycle,
                    "fluor": f,
                }
            )
    path = external.table_to_rdml(pd.DataFrame(rows), "exp", "run", tmp_path / "p.rdml")
    logging.getLogger("qpilot.qpcr.curves").setLevel(logging.ERROR)
    c = analyse_study(path, "exp", reference_targets=(), use_cache=False)
    assert sorted(c["sample"]) == ["high", "high", "low", "low"]
    cq = c.groupby("sample")["cq"].mean()
    assert cq["low"] - cq["high"] == pytest.approx(np.log(100) / np.log(1.9), abs=0.3)


def test_ruijter_conversions_keep_every_curve(tmp_path):
    ds94 = external._ds94_wells(external.ds94_rdml(out=tmp_path / "a.rdml"))
    assert ds94.groupby("copies").size().to_dict() == {15: 94, 150: 94, 1500: 94, 15000: 94}
    logging.getLogger("qpilot.qpcr.curves").setLevel(logging.ERROR)
    comp = analyse_study(
        external.competimer_rdml(out=tmp_path / "c.rdml"),
        "competimer",
        reference_targets=(),
        use_cache=False,
    )
    assert len(comp) == 147 and comp["well"].nunique() == 147
    # plain sample names survive qPilot's identifier check unchanged
    assert external._sample(0.0625, 50) in set(comp["sample"])


def test_fixed_components_match_the_existing_results():
    j = json.loads((RESULTS / "validation_dpcr.json").read_text())
    rob = j["v2_coverage"]["other_estimators"]["robust_in_sample"]["components"]["amc"]
    assert external.RUN_EFFECT == {
        "sd_level_log2": rob["sd_level_log2"],
        "sd_log2e_run": rob["sd_log2e_run"],
    }
    gap = j["coverage_gap_tests"]["p1_plate_pair_term"]
    both = gap["variant_one_term_from_both_series"]["term"]["sd_plate_pair_log2"]
    assert external.P1_TERM == pytest.approx(both, abs=1e-4)
    assert external.P1_TERM_AMC == pytest.approx(
        gap["terms"]["amc"]["sd_plate_pair_log2"], abs=1e-4
    )
    assert external.NOMINAL_SD == pytest.approx(j["truth_model"]["nominal_truth_sd_log2"], abs=1e-4)


def test_null_pass_needs_all_three_conditions():
    ok = {
        "share_cells_calling": 0.005,
        "share_defensible_cells_calling": 0.0,
        "calls_passing_robust_filter": 0,
        "baseline_median_abs_log2fc": 0.1,
    }
    assert external._null_pass({"3v3": ok})["overall"]
    assert not external._null_pass({"3v3": ok | {"baseline_median_abs_log2fc": 0.2}})["overall"]
    assert not external._null_pass({"3v3": ok | {"calls_passing_robust_filter": 1}})["overall"]


def test_propagate_ignores_a_missing_poisson_scale_without_a_slope():
    base = pd.DataFrame(
        {
            "tubes": "g",
            "se_rep": [0.1],
            "df": [4.0],
            "dcq": [-2.0],
            "se_log2e": [0.0],
            "estimate_log2": [1.0],
            "error_log2": [0.0],
            "truth_log2": [1.0],
            "truth_se": [0.0],
            "ci_lo": [0.7],
            "ci_hi": [1.3],
            "poisson_x": [np.nan],
        }
    )
    x = known_answers.propagate(base, {"g": {"sd_level_log2": 0.0, "sd_log2e_run": 0.0}})
    assert np.isfinite(x["se_new"]).all()


def test_external_end_to_end(tmp_path):
    r = external.validate(out=tmp_path)
    x1 = r["x1_held_out_dpcr_plates"]
    assert x1["cases"] == 120 and len(x1["plates"]) == 3
    assert r["x2_shifted_baseline"]["pass"]  # a constant offset changes nothing
    assert r["x3_matrix_gaps"]["runs"]
    assert set(r["x4_ds94"]["no_difference"]) == {"15 copies", "150 copies"}
    assert "post_hoc_without_failed_curve_analyses" in r["x5_competimer"]
    assert (tmp_path / "validation_external.json").exists()
