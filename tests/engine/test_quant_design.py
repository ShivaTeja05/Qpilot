"""Task 4 gate: relative quantities and the expression-defined groups."""

import math

import numpy as np
import pandas as pd
import pytest

from qpilot.qpcr.curves import REFERENCE_TARGETS
from qpilot.qpcr.design import GroupSpec, design_summary, groups_by_cut, marker_groups
from qpilot.qpcr.quant import QuantError, log2_matrix, relative, samples_common


def _wells(rows):
    return pd.DataFrame(rows, columns=["sample", "target", "sample_type", "n0"])


@pytest.fixture
def tiny_matrix():
    # s1..s3 x {G, R}; s3 has G undetermined; s4 lacks a G well entirely (dropped as incomplete)
    curves = _wells(
        [
            ("s1", "G", "unkn", 8.0), ("s1", "R", "unkn", 2.0),
            ("s2", "G", "unkn", 4.0), ("s2", "R", "unkn", 4.0),
            ("s3", "G", "unkn", float("nan")), ("s3", "R", "unkn", 1.0),
            ("s4", "R", "unkn", 1.0),
            ("std1", "G", "std", 100.0), ("std1", "R", "std", 100.0),
        ]
    )  # fmt: skip
    return log2_matrix(curves)


def test_matrix_keeps_only_complete_study_samples(tiny_matrix):
    assert samples_common(tiny_matrix) == ["s1", "s2", "s3"]
    assert list(tiny_matrix.columns) == ["G", "R"]
    assert tiny_matrix.loc["s1", "G"] == 3.0 and math.isnan(tiny_matrix.loc["s3", "G"])


def test_relative_is_a_log2_subtraction(tiny_matrix):
    rel = relative(tiny_matrix, "G", ["R"], "drop")
    assert rel.to_dict() == {"s1": 2.0, "s2": 0.0}


def test_cap_uses_lowest_detected_value(tiny_matrix):
    rel = relative(tiny_matrix, "G", ["R"], "cap")
    assert rel["s3"] == pytest.approx(2.0 - 0.0)  # lowest detected log2(G) is 2.0; log2(R)=0


def test_relative_averages_several_control_genes():
    matrix = pd.DataFrame({"G": [5.0], "R1": [1.0], "R2": [3.0]}, index=["s1"])
    assert relative(matrix, "G", ["R1", "R2"]).iloc[0] == 3.0


def test_samples_missing_a_control_gene_are_skipped():
    matrix = pd.DataFrame({"G": [5.0, 5.0], "R": [1.0, np.nan]}, index=["s1", "s2"])
    assert list(relative(matrix, "G", ["R"]).index) == ["s1"]


def test_duplicate_wells_are_averaged_as_technical_replicates():
    # Step 3.1: replicates are no longer refused; log2 n0 is averaged (geometric mean of N0)
    curves = _wells([("s1", "G", "unkn", 1.0), ("s1", "G", "unkn", 4.0)])
    matrix = log2_matrix(curves)
    assert list(matrix.index) == ["s1"] and matrix.loc["s1", "G"] == pytest.approx(1.0)
    assert issubclass(QuantError, Exception)  # still exported for callers that catch it


def test_bad_arguments_are_refused(tiny_matrix):
    with pytest.raises(ValueError):
        relative(tiny_matrix, "G", [], "drop")
    with pytest.raises(ValueError):
        relative(tiny_matrix, "G", ["R"], "zero")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        GroupSpec(cut=1.5)


def test_groups_split_at_the_oracle_threshold():
    matrix = pd.DataFrame(
        {"M": [float(i) for i in range(10)], "R": [0.0] * 10},
        index=[f"s{i}" for i in range(10)],
    )
    high, rest = marker_groups(matrix, GroupSpec(marker="M", cut=0.2, refs_primary=("R",)))
    assert high == {"s8", "s9"} and len(rest) == 8


@pytest.mark.demo_data
def test_demo_samples(demo_matrix):
    assert len(samples_common(demo_matrix)) == 366
    complete_refs = demo_matrix[list(REFERENCE_TARGETS)].notna().all(axis=1)
    assert int(complete_refs.sum()) == 349


@pytest.mark.demo_data
def test_demo_groups_are_53_vs_294(demo_matrix):
    spec = GroupSpec()
    high, rest = marker_groups(demo_matrix, spec)
    summary = design_summary(high, rest, spec)
    assert (summary.n_hi, summary.n_lo) == (53, 294)
    assert summary.group_var == "MYCN_high" and "not a clinical call" in summary.note
    assert summary.refs_primary == REFERENCE_TARGETS


@pytest.mark.demo_data
def test_demo_groups_for_each_cut_use_primary_refs(demo_matrix):
    by_cut = groups_by_cut(demo_matrix, GroupSpec(), [0.10, 0.15, 0.20])
    sizes = {cut: len(high) for cut, (high, _) in by_cut.items()}
    assert sizes[0.15] == 53
    assert sizes[0.10] < 53 < sizes[0.20]
