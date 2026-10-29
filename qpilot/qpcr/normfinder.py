"""Control-gene stability (NormFinder): how much error does each candidate bring in?

NormFinder (Andersen, Jensen & Ørntoft, Cancer Res 2004; 64:5245) fits an additive model to the
log expression ``y_igj`` of candidate gene ``i`` in sample ``j`` of group ``g``,

    y_igj = alpha_ig + beta_gj + eps_igj,   Var(eps_igj) = sigma2_ig          (Eq. A)

(``beta_gj`` is the amount of mRNA in the sample, so it cancels) and scores each candidate by
the systematic error it would bring into a normalisation: the variation **within** each group
plus the variation of its level **between** the groups. This module is a reimplementation from
the paper's equations; no NormFinder code (R, Excel or GPL ports such as NormqPCR) was used.

* **Intragroup variance** (Eq. B). Per group, the residuals of the additive model
  ``r_igj = y_igj - ybar_ig. - ybar_.gj + ybar_.g.``; ``s2_ig = sum_j r_igj^2 /
  ((n_g - 1)(1 - 2/k))`` and the unbiased ``sigma2_ig = s2_ig - sum_v s2_vg / (k(k - 1))``.
* **Intergroup difference.** ``z_ig`` (the group mean of gene ``i``) gives
  ``d_ig = z_ig - zbar_i. - zbar_.g + zbar_..``: the gene's own shift in group ``g`` once the
  average of the candidates (assumed not to differ between groups) is taken out.
* **Shrinkage** (Eq. D). The spread of the true differences,
  ``gamma2 = sum d_ig^2 / ((k - 1)(G - 1)) - sum sigma2_ig / n_g / (kG)``, 0 if negative.
* **Stability value** (Eq. C), the absolute posterior mean of the difference plus one posterior
  SD: with ``v = sigma2_ig / n_g``,
  ``rho_ig = gamma2 |d_ig| / (gamma2 + v) + sqrt(v + gamma2 v / (gamma2 + v))``, and
  ``rho_i`` is its mean over the groups. Lower is steadier.
* **Best pair** (the paper's "average control gene", supplementary data): the average of two
  genes has the average of their posterior means and a quarter of the sum of their posterior
  variances, ``rho_ij = mean_g (|d~_ig + d~_jg| / 2 + sqrt((p_ig + p_jg) / 4))``, so a pair whose
  group shifts cancel can beat the two individually steadiest genes.

Without groups (or with one), ``d = 0`` and ``gamma2 = 0``: the stability value is the standard
error of the gene's mean, ``sqrt(sigma2_i / n)``, and the best pair is the two steadiest genes.

qPilot's choices where the paper is silent, each reported in the result: a candidate whose
unbiased variance estimate comes out negative (sampling noise with few genes) is counted as 0 in
the stability value (``clamped``); a unit missing any candidate is left out (NormFinder needs
complete data), as is a unit without a group or a group with fewer than two units. The paper's
own guidance is reported as plain warnings: at least eight samples per group, at least three
candidates (five to ten recommended), candidates not expected to differ between the groups.

Input values are on the log2 scale (``log2 N0``; NormFinder's own input is ``-Cq`` for Cq data,
the same scale). Deterministic, numpy only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

import numpy as np
import pandas as pd

MIN_CANDIDATES = 3  # the model needs k > 2 (the factor 1 - 2/k); the paper's own minimum
RECOMMENDED_CANDIDATES = 5  # "5-10 are recommended"
MIN_PER_GROUP = 8  # "The sample set should minimally contain 8 samples/group"
METHOD_CARD_PATH = "methods/normfinder.md"
SOURCE = "Andersen, Jensen & Ørntoft, Cancer Res 2004; 64:5245-5250"

METHOD_CARD: dict[str, Any] = {
    "id": "normfinder",
    "version": "1",
    "title": "NormFinder: how much error each control gene brings in",
    "source": SOURCE,
    "implementation": "qpilot/qpcr/normfinder.py",
    "inputs": ["units x genes log2 N0 of the candidate control genes", "each unit's group"],
    "outputs": ["stability value per candidate", "the best gene", "the best pair"],
    "acceptance_tests": [
        "tests/numbers/test_normfinder.py::test_matches_a_direct_transcription_of_the_paper",
        "tests/numbers/test_normfinder.py::test_hand_computed_three_genes_two_groups",
        "tests/numbers/test_normfinder.py::test_sample_amount_cancels",
    ],
    "licence": "Apache-2.0",
    "card": METHOD_CARD_PATH,
}


class NormFinderError(ValueError):
    """Too few candidates or units for the model (the message says what is missing)."""


@dataclass(frozen=True)
class NormFinderResult:
    """NormFinder's answer for one set of candidates on one study.

    ``stability`` maps each candidate to its stability value (candidate order); ``order`` lists
    the candidates steadiest first; ``best_pair`` is the pair whose average is steadiest, with
    ``pair_stability`` its value and ``pairs`` every pair's value (best first). ``intragroup``
    is each candidate's within-group variance averaged over the groups and ``intergroup`` its
    shift per group (``d_ig``, log2) before shrinkage; ``gamma2`` the estimated spread of the
    true shifts (``None`` without groups). ``groups`` names the groups used with their sizes,
    ``n_units`` counts the units used and ``left_out`` the units left out and why.
    """

    candidates: tuple[str, ...]
    stability: dict[str, float]
    order: tuple[str, ...]
    best: str
    best_pair: tuple[str, str]
    pair_stability: float
    pairs: tuple[tuple[tuple[str, str], float], ...]
    intragroup: dict[str, float]
    intergroup: dict[str, dict[str, float]]
    gamma2: float | None
    groups: dict[str, int]
    n_units: int
    clamped: tuple[str, ...] = ()
    left_out: dict[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @property
    def grouped(self) -> bool:
        """True when two or more groups entered the model (inter- and intragroup variation)."""
        return len(self.groups) >= 2

    def as_dict(self) -> dict[str, Any]:
        """Plain JSON-serialisable values (stable key order)."""
        return {
            "candidates": list(self.candidates),
            "stability": {g: float(v) for g, v in self.stability.items()},
            "order": list(self.order),
            "best": self.best,
            "best_pair": list(self.best_pair),
            "pair_stability": float(self.pair_stability),
            "pairs": [{"genes": list(p), "stability": float(v)} for p, v in self.pairs],
            "intragroup": {g: float(v) for g, v in self.intragroup.items()},
            "intergroup": {g: dict(v) for g, v in self.intergroup.items()},
            "gamma2": None if self.gamma2 is None else float(self.gamma2),
            "groups": dict(self.groups),
            "grouped": self.grouped,
            "n_units": int(self.n_units),
            "clamped": list(self.clamped),
            "left_out": dict(self.left_out),
            "warnings": list(self.warnings),
            "source": SOURCE,
        }


def _intragroup(block: np.ndarray) -> np.ndarray:
    """Eq. B for one group: the unbiased intragroup variance of each gene (rows = genes)."""
    k, n = block.shape
    residual = (
        block - block.mean(axis=1, keepdims=True) - block.mean(axis=0, keepdims=True) + block.mean()
    )
    s2 = (residual**2).sum(axis=1) / ((n - 1) * (1 - 2 / k))
    return s2 - s2.sum() / (k * (k - 1))


def _shrunk(d: np.ndarray, v: np.ndarray, gamma2: float) -> tuple[np.ndarray, np.ndarray]:
    """Posterior mean of the shifts and posterior variance of the group means (Eq. C parts)."""
    total = gamma2 + v
    with np.errstate(divide="ignore", invalid="ignore"):
        weight = np.where(total > 0, gamma2 / total, 0.0)
    return weight * d, v + weight * v


def normfinder(
    matrix: pd.DataFrame,
    candidates: Sequence[str],
    groups: Mapping[str, str | None] | None = None,
) -> NormFinderResult:
    """Rank candidate control genes by NormFinder's stability value and find the best pair.

    Args:
        matrix: Units x genes ``log2 N0`` (:func:`qpilot.qpcr.quant.log2_matrix`).
        candidates: The candidate control genes (three or more).
        groups: Unit -> group name (``None``: no group). Without it every unit is one group.

    Returns:
        A :class:`NormFinderResult`.

    Raises:
        NormFinderError: Fewer than three candidates, or fewer than two complete units.
    """
    candidates = tuple(dict.fromkeys(candidates))
    k = len(candidates)
    if k < MIN_CANDIDATES:
        raise NormFinderError(
            f"NormFinder needs at least {MIN_CANDIDATES} candidate control genes, not {k}"
        )
    missing = [gene for gene in candidates if gene not in matrix.columns]
    if missing:
        raise NormFinderError(f"candidates not in the matrix: {missing}")
    block = matrix[list(candidates)]
    left_out: dict[str, str] = {}
    for unit in block.index[block.isna().any(axis=1)]:
        left_out[str(unit)] = "missing a candidate's value"
    block = block.dropna(how="any")
    if groups is None:
        labels = pd.Series("all", index=block.index, dtype=object)
    else:
        labels = pd.Series([groups.get(u) for u in block.index], index=block.index, dtype=object)
        for unit in labels.index[labels.isna()]:
            left_out[str(unit)] = "in no group"
        labels = labels.dropna()
    sizes = labels.value_counts()
    for name in sorted(sizes.index[sizes < 2].astype(str)):
        for unit in labels.index[labels.astype(str) == name]:
            left_out[str(unit)] = f"in group {name}, which has fewer than two units"
    kept = sorted(str(g) for g in sizes.index[sizes >= 2])
    if not kept:
        raise NormFinderError("NormFinder needs at least two units with every candidate")
    group_names = tuple(kept)
    variances, means, counts = [], [], []
    for name in group_names:
        units = labels.index[labels.astype(str) == name]
        values = block.loc[units].to_numpy(dtype=float).T  # genes x units
        variances.append(_intragroup(values))
        means.append(values.mean(axis=1))
        counts.append(values.shape[1])
    sigma2 = np.column_stack(variances)  # genes x groups
    z = np.column_stack(means)
    n = np.asarray(counts, dtype=float)
    clamped = tuple(candidates[i] for i in range(k) if (sigma2[i] < 0).any())
    sigma2_used = np.clip(sigma2, 0.0, None)
    v = sigma2_used / n  # the variance of a group mean
    n_groups = len(group_names)
    if n_groups >= 2:
        d = z - z.mean(axis=1, keepdims=True) - z.mean(axis=0, keepdims=True) + z.mean()
        gamma2 = float((d**2).sum() / ((k - 1) * (n_groups - 1)) - v.sum() / (k * n_groups))
        gamma2 = max(gamma2, 0.0)
    else:
        d = np.zeros_like(z)
        gamma2 = 0.0
    shift, post = _shrunk(d, v, gamma2)
    rho = (np.abs(shift) + np.sqrt(post)).mean(axis=1)
    stability = {gene: float(rho[i]) for i, gene in enumerate(candidates)}
    order = tuple(sorted(candidates, key=lambda g: (stability[g], candidates.index(g))))
    pairs = []
    for i, j in combinations(range(k), 2):
        value = (np.abs(shift[i] + shift[j]) / 2 + np.sqrt((post[i] + post[j]) / 4)).mean()
        pairs.append(((candidates[i], candidates[j]), float(value)))
    rank = {gene: i for i, gene in enumerate(candidates)}
    pairs.sort(key=lambda item: (item[1], rank[item[0][0]], rank[item[0][1]]))
    best_pair, pair_value = pairs[0]
    warnings = _warnings(
        k, dict(zip(group_names, counts, strict=True)), groups is not None, clamped
    )
    return NormFinderResult(
        candidates=candidates,
        stability=stability,
        order=order,
        best=order[0],
        best_pair=best_pair,
        pair_stability=pair_value,
        pairs=tuple(pairs),
        intragroup={gene: float(sigma2_used[i].mean()) for i, gene in enumerate(candidates)},
        intergroup={
            gene: {name: float(d[i, g]) for g, name in enumerate(group_names)}
            for i, gene in enumerate(candidates)
        }
        if n_groups >= 2
        else {},
        gamma2=gamma2 if n_groups >= 2 else None,
        groups=dict(zip(group_names, counts, strict=True)),
        n_units=int(n.sum()),
        clamped=clamped,
        left_out=dict(sorted(left_out.items())),
        warnings=warnings,
    )


def _warnings(
    k: int, sizes: Mapping[str, int], asked_groups: bool, clamped: Sequence[str] = ()
) -> tuple[str, ...]:
    """The paper's requirements this study does not meet, in plain words.

    ``clamped`` are the candidates whose within-group variance came out negative in some group
    and counts as 0 there (the paper is silent; science review J11): with small groups this
    happens often and makes those genes look steadiest, so they are named.
    """
    out = []
    small = sorted(name for name, size in sizes.items() if size < MIN_PER_GROUP)
    if small and len(sizes) >= 2:
        out.append(
            f"the paper asks for at least {MIN_PER_GROUP} samples per group; "
            f"{', '.join(small)} {'has' if len(small) == 1 else 'have'} fewer, so the "
            "stability values are rough"
        )
    elif small:
        out.append(
            f"the paper asks for at least {MIN_PER_GROUP} samples; this study has fewer, so the "
            "stability values are rough"
        )
    if clamped:
        names = ", ".join(clamped)
        out.append(
            f"the within-group variance of {names} came out below zero in some group (an "
            "unbiased estimate from few samples can) and is counted as zero there, which makes "
            f"{'it' if len(clamped) == 1 else 'them'} look steadier than the data show"
        )
    if k < RECOMMENDED_CANDIDATES:
        out.append(
            f"the paper recommends {RECOMMENDED_CANDIDATES} to 10 candidate control genes; with "
            f"{k} the model's estimates are rough"
        )
    if asked_groups and len(sizes) < 2:
        out.append(
            "only one group has two or more units, so NormFinder could not look at the "
            "difference between groups"
        )
    return tuple(out)


@dataclass(frozen=True)
class Agreement:
    """geNorm and NormFinder side by side: do they pick the same pair and the same best gene?"""

    genorm_pair: tuple[str, str]
    normfinder_pair: tuple[str, str]
    same_pair: bool
    shared: tuple[str, ...]  # genes in both best pairs
    genorm_best: tuple[str, str]  # geNorm cannot order its last two
    normfinder_best: str
    words: str

    def as_dict(self) -> dict[str, Any]:
        """Plain JSON-serialisable values."""
        return {
            "genorm_pair": list(self.genorm_pair),
            "normfinder_pair": list(self.normfinder_pair),
            "same_pair": self.same_pair,
            "shared": list(self.shared),
            "genorm_best": list(self.genorm_best),
            "normfinder_best": self.normfinder_best,
            "words": self.words,
        }


def agreement(genorm_order: Sequence[str], result: NormFinderResult) -> Agreement:
    """Compare geNorm's best pair (its last two genes) with NormFinder's best pair, in words.

    The words say only what the two methods agree or disagree on; they never say which control
    genes to use (that stays a person's choice on the reference-gene card).
    """
    order = list(genorm_order)
    if len(order) < 2:
        raise NormFinderError("geNorm needs two genes to name a best pair")
    g_pair = (order[0], order[1])
    nf_pair = result.best_pair
    same = set(g_pair) == set(nf_pair)
    shared = tuple(g for g in nf_pair if g in g_pair)
    g_words = " and ".join(g_pair)
    nf_words = " and ".join(nf_pair)
    if same:
        words = f"geNorm and NormFinder agree on the best pair: {nf_words}."
    elif shared:
        words = (
            f"geNorm and NormFinder share {shared[0]} in their best pair but disagree on the "
            f"other gene: geNorm picks {g_words}, NormFinder {nf_words}."
        )
    else:
        words = (
            f"geNorm and NormFinder disagree on the best pair: geNorm picks {g_words}, "
            f"NormFinder {nf_words}."
        )
    if result.grouped and not same:
        words += (
            " NormFinder also looks at how each gene differs between the groups, which geNorm "
            "cannot see; geNorm favours genes that move together, even when they move together "
            "between the groups."
        )
    return Agreement(
        genorm_pair=g_pair,
        normfinder_pair=nf_pair,
        same_pair=same,
        shared=shared,
        genorm_best=g_pair,
        normfinder_best=result.best,
        words=words,
    )


__all__ = [
    "MIN_CANDIDATES",
    "MIN_PER_GROUP",
    "SOURCE",
    "Agreement",
    "NormFinderError",
    "NormFinderResult",
    "agreement",
    "normfinder",
]
