"""Task 5 gate: geNorm reproduces the oracle on the demo study."""

import numpy as np
import pandas as pd
import pytest

from qpilot.qpcr.curves import REFERENCE_TARGETS
from qpilot.qpcr.refgenes import CUTOFF_M, CUTOFF_V, genorm, robust_m


@pytest.fixture
def toy_matrix():
    rng = np.random.default_rng(0)
    base = rng.normal(10, 2, size=200)  # sample-to-sample amount differences
    return pd.DataFrame(
        {
            "stable_a": base + rng.normal(0, 0.05, 200),
            "stable_b": base + rng.normal(0, 0.05, 200),
            "wobbly": base + rng.normal(0, 0.8, 200),
            "awful": base + rng.normal(0, 2.0, 200),
        }
    )


def test_most_stable_genes_rank_first(toy_matrix):
    result = genorm(toy_matrix, ["awful", "wobbly", "stable_a", "stable_b"])
    assert set(result.order[:2]) == {"stable_a", "stable_b"}
    assert result.order[-1] == "awful"
    assert result.M_initial["stable_a"] < result.M_initial["awful"]


def test_two_tight_genes_are_enough(toy_matrix):
    result = genorm(toy_matrix, ["stable_a", "stable_b", "wobbly"])
    assert result.V["V2/3"] > CUTOFF_V or result.recommended == ("stable_a", "stable_b")
    tight = genorm(toy_matrix.assign(c=toy_matrix.stable_a + 0.01), ["stable_a", "stable_b", "c"])
    assert len(tight.recommended) == 2 and tight.V["V2/3"] < CUTOFF_V


def test_needs_three_candidates(toy_matrix):
    with pytest.raises(ValueError):
        genorm(toy_matrix, ["stable_a", "stable_b"])


def test_cutoffs_are_reported(toy_matrix):
    result = genorm(toy_matrix, list(toy_matrix.columns))
    assert (result.cutoff_M, result.cutoff_V) == (CUTOFF_M, CUTOFF_V)


@pytest.mark.demo_data
def test_demo_genorm_matches_oracle(demo_matrix):
    result = genorm(demo_matrix, REFERENCE_TARGETS)
    expected_m = {
        "ALUsq(Eurogentec)": 1.682, "HMBS": 1.958, "HPRT1": 1.635, "SDHA(1)": 1.989,
        "UBC(2)": 2.027,
    }  # fmt: skip
    for gene, m in expected_m.items():
        assert result.M_initial[gene] == pytest.approx(m, abs=0.01), gene
    assert result.order == ["ALUsq(Eurogentec)", "HPRT1", "HMBS", "SDHA(1)", "UBC(2)"]
    for key, v in {"V2/3": 0.556, "V3/4": 0.387, "V4/5": 0.327}.items():
        assert result.V[key] == pytest.approx(v, abs=0.01), key
    assert result.recommended == tuple(result.order)  # no V below 0.15 -> all five
    assert all(m > CUTOFF_M for m in result.M_initial.values())


@pytest.mark.demo_data
def test_demo_robust_m_matches_oracle(demo_matrix):
    robust = robust_m(demo_matrix, REFERENCE_TARGETS)
    expected = {
        "ALUsq(Eurogentec)": 1.49, "HMBS": 1.598, "HPRT1": 1.377, "SDHA(1)": 1.699,
        "UBC(2)": 1.822,
    }  # fmt: skip
    for gene, m in expected.items():
        assert robust[gene] == pytest.approx(m, abs=0.02), gene
