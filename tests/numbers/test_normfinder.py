"""NormFinder (Andersen, Jensen & Ørntoft 2004): hand computations and the paper's equations."""

import math
from itertools import combinations

import numpy as np
import pandas as pd
import pytest

from qpilot.qpcr.normfinder import NormFinderError, agreement, normfinder


def _matrix(rows: dict[str, list[float]], units: list[str]) -> pd.DataFrame:
    return pd.DataFrame(rows, index=units)


# Hand example (worked out on paper, see the method card): two groups of three samples.
# Group A: G1 0 0 0 · G2 1 1 1 · G3 0 3 0; group B: G1 2 2 2 · G2 1 1 1 · G3 1 4 1.
# Intragroup: s2 = 1, 1, 4 in each group, sigma2 = s2 - 6 / (3 * 2) = 0, 0, 3.
# Intergroup: d_A = -1/2, 1/2, 0 and d_B = 1/2, -1/2, 0; gamma2 = 1/2 - 2/6 = 1/6.
# rho: G1 = G2 = 1/2 (shrinkage weight 1, no variance), G3 = sqrt(1 + 1/7) = sqrt(8/7).
# Best pair G1 + G2: their shifts cancel, rho = 0.
HAND = _matrix(
    {
        "G1": [0, 0, 0, 2, 2, 2],
        "G2": [1, 1, 1, 1, 1, 1],
        "G3": [0, 3, 0, 1, 4, 1],
    },
    ["a1", "a2", "a3", "b1", "b2", "b3"],
)
HAND_GROUPS = {"a1": "A", "a2": "A", "a3": "A", "b1": "B", "b2": "B", "b3": "B"}


def test_hand_computed_three_genes_two_groups():
    result = normfinder(HAND, ["G1", "G2", "G3"], HAND_GROUPS)
    assert result.grouped
    assert result.gamma2 == pytest.approx(1 / 6)
    assert result.intergroup["G1"] == pytest.approx({"A": -0.5, "B": 0.5})
    assert result.intergroup["G3"] == pytest.approx({"A": 0.0, "B": 0.0}, abs=1e-12)
    assert result.intragroup == pytest.approx({"G1": 0.0, "G2": 0.0, "G3": 3.0}, abs=1e-12)
    assert result.stability == pytest.approx({"G1": 0.5, "G2": 0.5, "G3": math.sqrt(8 / 7)})
    assert result.order == ("G1", "G2", "G3")  # a tie keeps the candidate order
    assert result.best_pair == ("G1", "G2")
    assert result.pair_stability == pytest.approx(0.0, abs=1e-7)  # sqrt of rounding error
    g1_g3 = dict(result.pairs)[("G1", "G3")]
    assert g1_g3 == pytest.approx(0.25 + math.sqrt(2 / 7))
    assert result.groups == {"A": 3, "B": 3} and result.n_units == 6


def test_hand_computed_without_groups():
    # Group A alone: sigma2 = 0, 0, 3 and rho = sqrt(sigma2 / n) = 0, 0, 1.
    result = normfinder(HAND.iloc[:3], ["G1", "G2", "G3"])
    assert not result.grouped and result.gamma2 is None
    assert result.stability == pytest.approx({"G1": 0.0, "G2": 0.0, "G3": 1.0}, abs=1e-12)
    assert result.best_pair == ("G1", "G2")
    assert dict(result.pairs)[("G1", "G3")] == pytest.approx(0.5)


def _paper(matrix: pd.DataFrame, genes: list[str], groups: dict[str, str]) -> dict:
    """Eqs. A-D of the paper written out with explicit sums (no vectorisation)."""
    names = sorted(set(groups.values()))
    k, big_g = len(genes), len(names)
    y = {
        (i, g): [matrix.loc[u, i] for u in matrix.index if groups[u] == g]
        for i in genes
        for g in names
    }
    n = {g: len(y[(genes[0], g)]) for g in names}
    sigma2, z = {}, {}
    for g in names:
        s2 = {}
        for i in genes:
            row = sum(y[(i, g)]) / n[g]
            total = 0.0
            for j in range(n[g]):
                col = sum(y[(v, g)][j] for v in genes) / k
                grand = sum(sum(y[(v, g)]) for v in genes) / (k * n[g])
                total += (y[(i, g)][j] - row - col + grand) ** 2
            s2[i] = total / ((n[g] - 1) * (1 - 2 / k))
            z[(i, g)] = row
        for i in genes:
            sigma2[(i, g)] = max(s2[i] - sum(s2.values()) / (k * (k - 1)), 0.0)
    zi = {i: sum(z[(i, g)] for g in names) / big_g for i in genes}
    zg = {g: sum(z[(i, g)] for i in genes) / k for g in names}
    zz = sum(z.values()) / (k * big_g)
    d = {(i, g): z[(i, g)] - zi[i] - zg[g] + zz for i in genes for g in names}
    gamma2 = sum(v * v for v in d.values()) / ((k - 1) * (big_g - 1)) - sum(
        sigma2[(i, g)] / n[g] for i in genes for g in names
    ) / (k * big_g)
    gamma2 = max(gamma2, 0.0)
    rho, shift, post = {}, {}, {}
    for i in genes:
        values = []
        for g in names:
            v = sigma2[(i, g)] / n[g]
            w = gamma2 / (gamma2 + v) if gamma2 + v > 0 else 0.0
            shift[(i, g)] = w * d[(i, g)]
            post[(i, g)] = v + w * v
            values.append(abs(shift[(i, g)]) + math.sqrt(post[(i, g)]))
        rho[i] = sum(values) / big_g
    pairs = {
        (a, b): sum(
            abs(shift[(a, g)] + shift[(b, g)]) / 2 + math.sqrt((post[(a, g)] + post[(b, g)]) / 4)
            for g in names
        )
        / big_g
        for a, b in combinations(genes, 2)
    }
    return {"rho": rho, "gamma2": gamma2, "pairs": pairs}


def _random_study(seed: int, sizes=(9, 12, 7)) -> tuple[pd.DataFrame, dict[str, str]]:
    rng = np.random.default_rng(seed)
    genes = ["A", "B", "C", "D", "E", "F"]
    rows, groups = [], {}
    for g, size in enumerate(sizes):
        for j in range(size):
            amount = rng.normal(0, 1.5)  # the sample's mRNA amount: cancels
            shifts = np.array([0.0, 0.4, -0.3, 0.0, 0.8, -0.2]) * g
            noise = rng.normal(0, [0.2, 0.3, 0.5, 0.25, 0.4, 0.6])
            rows.append(20 + amount + shifts + noise)
            groups[f"g{g}_{j}"] = f"group{g}"
    return pd.DataFrame(rows, columns=genes, index=list(groups)), groups


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_matches_a_direct_transcription_of_the_paper(seed):
    matrix, groups = _random_study(seed)
    genes = list(matrix.columns)
    expected = _paper(matrix, genes, groups)
    result = normfinder(matrix, genes, groups)
    assert result.gamma2 == pytest.approx(expected["gamma2"], rel=1e-10)
    assert result.stability == pytest.approx(expected["rho"], rel=1e-10)
    assert dict(result.pairs) == pytest.approx(expected["pairs"], rel=1e-10)
    best = min(expected["pairs"], key=expected["pairs"].get)
    assert result.best_pair == best


def test_sample_amount_cancels():
    matrix, groups = _random_study(4)
    genes = list(matrix.columns)
    base = normfinder(matrix, genes, groups)
    rng = np.random.default_rng(9)
    shifted = matrix.add(rng.normal(0, 3, len(matrix)), axis=0)  # more cDNA in some samples
    moved = shifted + np.arange(len(genes)) * 1.7  # each gene's own level does not matter
    other = normfinder(moved, genes, groups)
    assert other.stability == pytest.approx(base.stability, rel=1e-9)
    assert other.best_pair == base.best_pair


def test_order_of_samples_and_candidates_does_not_matter():
    matrix, groups = _random_study(5)
    genes = list(matrix.columns)
    base = normfinder(matrix, genes, groups)
    shuffled = matrix.sample(frac=1, random_state=3)[genes[::-1]]
    other = normfinder(shuffled, genes[::-1], groups)
    assert other.stability == pytest.approx(base.stability, rel=1e-12)
    assert set(other.best_pair) == set(base.best_pair)


def test_a_shift_between_groups_is_intergroup_variation_once_groups_are_known():
    matrix, groups = _random_study(6)
    genes = list(matrix.columns)
    with_groups = normfinder(matrix, genes, groups)
    without = normfinder(matrix, genes)
    # E moves by 0.8 log2 per group step: pooled, that is noise; with groups it is a shift
    assert with_groups.intragroup["E"] < without.intragroup["E"] / 2
    assert abs(with_groups.intergroup["E"]["group2"]) > 0.5
    assert with_groups.order[-1] == "E"


def test_units_left_out_and_reported():
    matrix, groups = _random_study(7)
    matrix.iloc[0, 0] = np.nan
    groups = dict(groups)
    groups[matrix.index[1]] = None
    result = normfinder(matrix, list(matrix.columns), groups)
    assert result.left_out == {
        matrix.index[0]: "missing a candidate's value",
        matrix.index[1]: "in no group",
    }
    assert result.n_units == len(matrix) - 2


def test_requirements_are_warned_and_enforced():
    with pytest.raises(NormFinderError, match="at least 3"):
        normfinder(HAND, ["G1", "G2"])
    result = normfinder(HAND, ["G1", "G2", "G3"], HAND_GROUPS)
    words = " ".join(result.warnings)
    assert "at least 8 samples per group" in words and "5 to 10" in words
    single = normfinder(HAND, ["G1", "G2", "G3"], {u: "A" for u in HAND.index})
    assert not single.grouped
    assert any("only one group" in w for w in single.warnings)


def test_negative_variance_estimates_are_counted_as_zero_and_named():
    # Two perfectly parallel genes and a noisy one: the unbiased estimate dips below 0
    units = [f"u{i}" for i in range(6)]
    rng = np.random.default_rng(2)
    base = rng.normal(0, 1, 6)
    matrix = _matrix(
        {"P": base, "Q": base + 0.01 * rng.normal(0, 1, 6), "R": base + rng.normal(0, 1, 6)},
        units,
    )
    result = normfinder(matrix, ["P", "Q", "R"])
    assert result.clamped  # reported, never hidden
    assert all(v >= 0 for v in result.stability.values())


def test_agreement_words():
    result = normfinder(HAND, ["G1", "G2", "G3"], HAND_GROUPS)
    same = agreement(["G2", "G1", "G3"], result)
    assert same.same_pair and same.words.startswith("geNorm and NormFinder agree")
    other = agreement(["G1", "G3", "G2"], result)
    assert not other.same_pair and other.shared == ("G1",)
    assert "share G1" in other.words and "between the groups" in other.words
    apart = agreement(["G3", "X", "G1"], result)
    assert apart.words.startswith("geNorm and NormFinder disagree")
