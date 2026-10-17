"""Task 6 gate: Welch contrast with CI and the explicit conclusion rule."""

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from qpilot.cli import main
from qpilot.qpcr.contrast import (
    DEFAULT_RULE,
    ConclusionRule,
    conclude,
    standard_error,
    welch,
    welch_contrast,
)
from qpilot.qpcr.curves import REFERENCE_TARGETS
from qpilot.qpcr.design import GroupSpec, marker_groups


def test_welch_p_matches_scipy():
    rng = np.random.default_rng(1)
    a, b = rng.normal(1.0, 1.0, 20), rng.normal(0.0, 2.0, 35)
    w = welch(a, b)
    ref = stats.ttest_ind(a, b, equal_var=False)
    assert w.t == pytest.approx(ref.statistic)
    assert w.p == pytest.approx(ref.pvalue)


def test_welch_needs_two_values_per_group():
    with pytest.raises(ValueError):
        welch([1.0], [1.0, 2.0])


@pytest.mark.parametrize(
    ("log2fc", "p", "expected"),
    [(1.0, 0.01, "up"), (0.99, 0.001, "none"), (-1.0, 0.04, "down"), (2.0, 0.05, "none"),
     (-3.0, 0.2, "none"), (0.0, 1e-9, "none")],
)  # fmt: skip
def test_conclusion_rule_edges(log2fc, p, expected):
    assert conclude(log2fc, p) == expected


def test_rule_is_describable_and_adjustable():
    assert DEFAULT_RULE.describe() == (
        "up or down only if p < 0.05 and the change is at least 2-fold; otherwise no call"
    )
    assert conclude(0.6, 0.01, ConclusionRule(min_log2fc=0.5)) == "up"
    assert DEFAULT_RULE.as_dict() == {"alpha": 0.05, "min_log2fc": 1.0}


def test_contrast_on_a_constructed_matrix():
    samples = [f"s{i}" for i in range(8)]
    matrix = pd.DataFrame(
        {"G": [5.0, 5.2, 4.8, 5.1, 2.0, 2.2, 1.8, 2.1], "R": [0.0] * 8}, index=samples
    )
    result = welch_contrast(matrix, "G", ["R"], "drop", set(samples[:4]), set(samples[4:]))
    assert result.log2fc == pytest.approx(3.0, abs=1e-9)
    assert result.fc == pytest.approx(8.0)
    assert result.ci[0] < 8.0 < result.ci[1]
    assert result.conclusion == "up" and (result.n_hi, result.n_lo) == (4, 4)
    assert standard_error(result) > 0


@pytest.fixture(scope="module")
def demo_groups(demo_matrix):
    return marker_groups(demo_matrix, GroupSpec())


def _fc(demo_matrix, demo_groups, gene, refs, undetermined="drop"):
    high, rest = demo_groups
    return welch_contrast(demo_matrix, gene, refs, undetermined, high, rest)


@pytest.mark.demo_data
@pytest.mark.parametrize(
    ("gene", "fc", "lo", "hi", "conclusion"),
    [("ODC1", 3.59, 2.42, 5.33, "up"), ("BIRC5", 4.01, 2.93, 5.49, "up"),
     ("NTRK1", 0.07, 0.03, 0.14, "down"), ("NM23A", 2.19, None, None, "up"),
     ("PLAT", 0.29, 0.14, 0.63, "down")],
)  # fmt: skip
def test_demo_recommended_set_matches_oracle(
    demo_matrix, demo_groups, gene, fc, lo, hi, conclusion
):
    result = _fc(demo_matrix, demo_groups, gene, REFERENCE_TARGETS)
    assert result.fc == pytest.approx(fc, abs=0.1 if fc > 1 else 0.01)
    if lo is not None:
        assert result.ci[0] == pytest.approx(lo, abs=0.1 if lo > 1 else 0.01)
        assert result.ci[1] == pytest.approx(hi, abs=0.1 if hi > 1 else 0.01)
    assert result.conclusion == conclusion
    # Undetermined wells are dropped, so genes with empty wells compare fewer samples.
    high, rest = demo_groups
    undetermined = demo_matrix[gene].isna()
    expected_hi = sum(1 for s in high if not undetermined[s])
    expected_lo = sum(1 for s in rest if not undetermined[s])
    assert (result.n_hi, result.n_lo) == (expected_hi, expected_lo)
    assert result.n_hi <= 53 and result.n_lo <= 294


@pytest.mark.demo_data
@pytest.mark.parametrize(
    ("gene", "ref", "fc", "conclusion"),
    [("ODC1", "HMBS", 2.66, "up"), ("ODC1", "UBC(2)", 4.66, "up"), ("ODC1", "HPRT1", 4.33, "up"),
     ("NM23A", "HMBS", 1.62, "none")],
)  # fmt: skip
def test_demo_single_control_gene_matches_oracle(
    demo_matrix, demo_groups, gene, ref, fc, conclusion
):
    result = _fc(demo_matrix, demo_groups, gene, [ref])
    assert result.fc == pytest.approx(fc, abs=0.1)
    assert result.conclusion == conclusion


@pytest.mark.demo_data
def test_cli_run_contrast(capsys, demo_matrix):
    assert main(["run", "--contrast", "ODC1", "--contrast", "NM23A", "--refs", "HMBS"]) == 0
    out = capsys.readouterr().out
    assert "MYCN-high 53 vs rest 294" in out
    assert "ODC1: 2.66x" in out and "NM23A: 1.62x" in out and "none" in out
