"""Task 5 gate: geNorm reproduces the oracle on the demo study.

Task 8b gate: the group-effect check flags a control-gene ratio that moves between the groups.
"""

import json

import numpy as np
import pandas as pd
import pytest

from qpilot.qpcr.curves import REFERENCE_TARGETS
from qpilot.qpcr.design import GroupSpec
from qpilot.qpcr.refgenes import (
    CUTOFF_M,
    CUTOFF_V,
    GROUP_FLAG_LOG2,
    genorm,
    group_effect,
    robust_m,
)
from qpilot.qpcr.space import QpcrSpace


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


def _grouped(shifts: dict[str, float], amount_shift: float = 0.0, amount_sd: float = 1.5):
    """Four control genes, 30 high + 60 rest samples; ``shifts`` move genes in the high group."""
    rng = np.random.default_rng(3)
    n_hi, n_lo = 30, 60
    samples = [f"s{i:02d}" for i in range(n_hi + n_lo)]
    in_high = np.arange(n_hi + n_lo) < n_hi
    amount = rng.normal(10, amount_sd, n_hi + n_lo) + amount_shift * in_high  # cDNA put in
    matrix = pd.DataFrame(
        {
            gene: amount + rng.normal(0, 0.1, n_hi + n_lo) + shifts.get(gene, 0.0) * in_high
            for gene in ("A", "B", "C", "D")
        },
        index=samples,
    )
    return matrix, frozenset(samples[:n_hi]), frozenset(samples[n_hi:])


def test_group_effect_flags_a_ratio_shifted_by_one_log2():
    matrix, high, rest = _grouped({"B": 1.0})
    effect = group_effect(matrix, ["A", "B", "C", "D"], high, rest)
    assert effect.flag_log2 == GROUP_FLAG_LOG2 == 0.5
    pairs = {shift.label: shift for shift in effect.pairs}
    assert set(list(pairs)[:3]) == {"A:B", "B:C", "B:D"}  # the shifted ratios, largest first
    assert pairs["A:B"].diff == pytest.approx(-1.0, abs=0.1)  # A:B falls when B rises
    assert pairs["B:C"].diff == pytest.approx(1.0, abs=0.1)
    assert pairs["B:C"].fold == pytest.approx(2.0, abs=0.15) and pairs["B:C"].p < 1e-6
    assert {shift.label for shift in effect.flagged} == {"A:B", "B:C", "B:D"}
    for label in ("A:C", "A:D", "C:D"):  # ratios that do not involve B stay put
        assert abs(pairs[label].diff) < 0.1 and pairs[label] not in effect.flagged
    assert (pairs["A:B"].n_hi, pairs["A:B"].n_lo) == (30, 60)
    assert effect.note == "6 pairs, no multiple-testing correction"


def test_group_effect_flags_only_the_one_pair_whose_ratio_moves():
    matrix, high, rest = _grouped({"A": 0.5, "B": -0.5})  # A:B moves +1; A:C, B:C move ±0.5
    effect = group_effect(matrix, ["A", "B", "C"], high, rest, flag_log2=0.75)
    assert [shift.label for shift in effect.flagged] == ["A:B"]
    assert effect.top.label == "A:B" and effect.top.diff == pytest.approx(1.0, abs=0.1)
    assert effect.as_dict()["flagged"] == ["A:B"]


def test_group_effect_ratios_cancel_the_input_amount():
    matrix, high, rest = _grouped({}, amount_shift=0.8, amount_sd=0.2)  # more cDNA in high
    effect = group_effect(matrix, ["A", "B", "C", "D"], high, rest)
    assert all(shift.diff == pytest.approx(0.8, abs=0.15) for shift in effect.raw)
    assert [shift.label for shift in effect.raw] == ["A", "B", "C", "D"]
    assert not effect.flagged
    assert all(abs(shift.diff) < 0.1 for shift in effect.pairs)


def test_group_effect_drops_missing_values_and_serialises():
    matrix, high, rest = _grouped({"B": 1.0})
    matrix.loc["s00", "A"] = np.nan  # one high sample without A
    effect = group_effect(matrix, ["A", "B", "C"], high, rest)
    pairs = {shift.label: shift for shift in effect.pairs}
    assert (pairs["A:B"].n_hi, pairs["B:C"].n_hi) == (29, 30)
    data = json.loads(json.dumps(effect.as_dict()))
    assert data == effect.as_dict()
    assert set(data) == {"raw", "pairs", "flagged", "flag_log2", "flag_fold", "note"}
    assert data["raw"]["A"]["n_hi"] == 29 and data["flag_fold"] == pytest.approx(2**0.5)
    assert [p["label"] for p in data["pairs"]] == [s.label for s in effect.pairs]


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


@pytest.fixture(scope="module")
def demo_space(demo_matrix):
    return QpcrSpace(demo_matrix, genorm(demo_matrix, REFERENCE_TARGETS), GroupSpec())


@pytest.fixture(scope="module")
def demo_effect(demo_matrix, demo_space):
    return group_effect(demo_matrix, REFERENCE_TARGETS, *demo_space.groups(0.15))


@pytest.mark.demo_data
def test_demo_group_effect_pairs(demo_effect):
    pairs = {shift.label: shift for shift in demo_effect.pairs}
    assert len(pairs) == 10 and demo_effect.note == "10 pairs, no multiple-testing correction"
    top = demo_effect.top
    assert top.label == "HMBS:UBC(2)" and top is demo_effect.pairs[0]
    assert top.diff == pytest.approx(0.81, abs=0.03)
    assert top.fold == pytest.approx(1.76, abs=0.05)
    assert top.p == pytest.approx(0.058, abs=0.01)
    assert (top.n_hi, top.n_lo) == (53, 294)
    assert pairs["HMBS:HPRT1"].diff == pytest.approx(0.71, abs=0.03)
    assert pairs["HMBS:HPRT1"].p == pytest.approx(0.045, abs=0.01)
    assert pairs["SDHA(1):UBC(2)"].diff == pytest.approx(0.54, abs=0.03)
    flagged = [shift.label for shift in demo_effect.flagged]
    assert flagged == ["HMBS:UBC(2)", "HMBS:HPRT1", "SDHA(1):UBC(2)"]


@pytest.mark.demo_data
def test_demo_group_effect_raw_levels(demo_effect):
    raw = {shift.label: shift for shift in demo_effect.raw}
    assert list(raw) == list(REFERENCE_TARGETS)
    assert raw["UBC(2)"].diff == pytest.approx(-0.81, abs=0.03)
    assert raw["UBC(2)"].p == pytest.approx(0.00097, abs=0.0003)
    assert raw["HPRT1"].diff == pytest.approx(-0.70, abs=0.03)
    assert raw["HMBS"].diff == pytest.approx(0.00, abs=0.03)


@pytest.mark.demo_data
def test_demo_ratio_shift_is_the_gap_between_single_control_genes(demo_space, demo_effect):
    """Normalising ODC1 to UBC(2) instead of HMBS moves it by exactly the HMBS:UBC(2) shift."""

    def odc1(ref: str) -> float:
        return demo_space.evaluate({**demo_space.primary, "refs": (ref,)})["ODC1"].log2fc

    assert odc1("UBC(2)") - odc1("HMBS") == pytest.approx(demo_effect.top.diff, abs=0.02)
