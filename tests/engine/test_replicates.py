"""Step 3.1: technical replicates and biological units are averaged before anything else."""

import math

import numpy as np
import pandas as pd
import pytest

from qpilot.qpcr.quant import EXCLUDED, excluded_cells, log2_matrix, replicate_sd


def _wells(rows, excluded=None):
    table = pd.DataFrame(rows, columns=["sample", "target", "sample_type", "n0"])
    if excluded is not None:
        table[EXCLUDED] = excluded
    return table


NAN = float("nan")


def test_one_well_per_sample_keeps_the_original_matrix():
    rows = [
        ("s1", "G", "unkn", 8.0), ("s1", "R", "unkn", 2.0),
        ("s2", "G", "unkn", NAN), ("s2", "R", "unkn", 4.0),
        ("s3", "R", "unkn", 1.0),
    ]  # fmt: skip
    plain = log2_matrix(_wells(rows))
    by_unit = log2_matrix(_wells(rows), units={})  # the aggregating path, identity units
    pd.testing.assert_frame_equal(plain, by_unit)
    assert list(plain.index) == ["s1", "s2"] and plain.loc["s1", "G"] == 3.0


def test_replicates_are_a_geometric_mean_and_never_n():
    rows = [  # s1: G wells 2, 8, 32 (log2 1, 3, 5) -> mean log2 3, not log2(mean n0)
        ("s1", "G", "unkn", 2.0), ("s1", "G", "unkn", 8.0), ("s1", "G", "unkn", 32.0),
        ("s1", "R", "unkn", 4.0), ("s1", "R", "unkn", 4.0),
        ("s2", "G", "unkn", 16.0), ("s2", "R", "unkn", 4.0),
    ]  # fmt: skip
    matrix = log2_matrix(_wells(rows))
    assert matrix.shape == (2, 2)  # three wells of s1 are one row
    assert matrix.loc["s1", "G"] == pytest.approx(3.0)
    assert matrix.loc["s1", "G"] != pytest.approx(math.log2((2 + 8 + 32) / 3))
    sd = replicate_sd(_wells(rows))
    assert sd.loc["s1", "G"] == pytest.approx(2.0)  # SD of 1, 3, 5
    assert sd.loc["s1", "R"] == 0.0 and math.isnan(sd.loc["s2", "G"])


def test_undetermined_only_when_every_replicate_is():
    rows = [
        ("s1", "G", "unkn", NAN), ("s1", "G", "unkn", 4.0), ("s1", "G", "unkn", 16.0),
        ("s2", "G", "unkn", NAN), ("s2", "G", "unkn", NAN),
        ("s1", "R", "unkn", 1.0), ("s2", "R", "unkn", 1.0),
    ]  # fmt: skip
    matrix = log2_matrix(_wells(rows))
    assert matrix.loc["s1", "G"] == pytest.approx(3.0)  # mean of log2 4 and 16
    assert math.isnan(matrix.loc["s2", "G"])
    assert list(matrix.index) == ["s1", "s2"]  # s2 was measured, so it stays


def test_samples_of_one_unit_are_averaged():
    rows = [
        ("prep1", "G", "unkn", 4.0), ("prep2", "G", "unkn", 16.0),
        ("prep1", "R", "unkn", 2.0), ("prep2", "R", "unkn", 2.0),
        ("other", "G", "unkn", 8.0), ("other", "R", "unkn", 2.0),
    ]  # fmt: skip
    matrix = log2_matrix(_wells(rows), units={"prep1": "mouse1", "prep2": "mouse1"})
    assert list(matrix.index) == ["mouse1", "other"]
    assert matrix.loc["mouse1", "G"] == pytest.approx(3.0)


def test_excluded_wells_leave_the_value_but_not_the_sample():
    rows = [
        ("s1", "G", "unkn", 4.0), ("s1", "G", "unkn", 64.0), ("s1", "R", "unkn", 1.0),
        ("s2", "G", "unkn", 8.0), ("s2", "R", "unkn", 1.0),
    ]  # fmt: skip
    table = _wells(rows, excluded=[False, True, False, True, False])
    matrix = log2_matrix(table)
    assert matrix.loc["s1", "G"] == 2.0  # the excluded replicate is not averaged in
    assert math.isnan(matrix.loc["s2", "G"]) and "s2" in matrix.index
    mask = excluded_cells(table)
    assert bool(mask.loc["s2", "G"]) and not bool(mask.loc["s1", "G"])
    assert not mask.to_numpy()[:, 1].any()  # R


def test_studies_and_controls_never_mix():
    rows = [
        ("s1", "G", "unkn", 4.0), ("s1", "R", "unkn", 1.0),
        ("s1", "G", "std", 1e6), ("ntc", "G", "ntc", NAN), ("ntc", "R", "ntc", NAN),
    ]  # fmt: skip
    matrix = log2_matrix(_wells(rows))
    assert list(matrix.index) == ["s1"] and matrix.loc["s1", "G"] == 2.0
    assert np.isfinite(matrix.to_numpy()).all()
