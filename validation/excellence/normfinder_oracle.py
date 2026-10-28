"""NormFinder from Andersen, Jensen & Ørntoft (Cancer Res 2004; 64:5245-5250), written again.

The paper's supplementary model, element by element with explicit sums (genes ``i = 1..k``,
groups ``g``, samples ``j = 1..n_g``; ``y`` on a log scale):

* residual ``r_igj = y_igj - ybar_ig. - ybar_.gj + ybar_.g.``;
* ``s2_ig = sum_j r_igj^2 / ((n_g - 1)(1 - 2/k))`` and the unbiased intragroup variance
  ``sigma2_ig = s2_ig - sum_i' s2_i'g / (k (k - 1))``;
* intergroup difference ``d_ig = z_ig - zbar_i. - zbar_.g + zbar_..`` with ``z_ig = ybar_ig.``;
* ``gamma2 = sum_ig d_ig^2 / ((k-1)(G-1)) - sum_ig (sigma2_ig / n_g) / (k G)``, at least 0;
* ``rho_ig = gamma2 |d_ig| / (gamma2 + v_ig) + sqrt(v_ig + gamma2 v_ig / (gamma2 + v_ig))``,
  ``v_ig = sigma2_ig / n_g``; the stability value ``rho_i`` is its mean over the groups;
* the average of two genes: posterior means averaged and the posterior variances summed over
  four, ``rho_pair,g = |m_ig + m_jg| / 2 + sqrt((p_ig + p_jg) / 4)``.

A negative ``sigma2`` is counted as zero (qPilot's documented choice; the paper is silent).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from itertools import combinations


def normfinder(
    values: Mapping[str, Mapping[str, float]], groups: Mapping[str, str]
) -> dict[str, object]:
    """Stability values, gamma2 and every pair's value.

    Args:
        values: Gene -> unit -> log2 value (complete: every gene has every unit).
        groups: Unit -> group (units of groups with fewer than two units must be left out).

    Returns:
        ``{"stability": {gene: rho}, "gamma2": float, "pairs": {(g1, g2): rho}}``.
    """
    genes = list(values)
    k = len(genes)
    names = sorted(set(groups.values()))
    members = {g: sorted(u for u, grp in groups.items() if grp == g) for g in names}
    sigma2: dict[tuple[str, str], float] = {}
    z: dict[tuple[str, str], float] = {}
    n: dict[str, int] = {}
    for g in names:
        units = members[g]
        ng = len(units)
        n[g] = ng
        gene_mean = {i: sum(values[i][u] for u in units) / ng for i in genes}
        unit_mean = {u: sum(values[i][u] for i in genes) / k for u in units}
        grand = sum(gene_mean.values()) / k
        s2 = {}
        for i in genes:
            ss = 0.0
            for u in units:
                r = values[i][u] - gene_mean[i] - unit_mean[u] + grand
                ss += r * r
            s2[i] = ss / ((ng - 1) * (1 - 2 / k))
        total = sum(s2.values())
        for i in genes:
            sigma2[(i, g)] = s2[i] - total / (k * (k - 1))
            z[(i, g)] = gene_mean[i]
    G = len(names)
    v = {(i, g): max(sigma2[(i, g)], 0.0) / n[g] for i in genes for g in names}
    if G >= 2:
        zi = {i: sum(z[(i, g)] for g in names) / G for i in genes}
        zg = {g: sum(z[(i, g)] for i in genes) / k for g in names}
        zz = sum(z.values()) / (k * G)
        d = {(i, g): z[(i, g)] - zi[i] - zg[g] + zz for i in genes for g in names}
        gamma2 = sum(x * x for x in d.values()) / ((k - 1) * (G - 1))
        gamma2 -= sum(v.values()) / (k * G)
        gamma2 = max(gamma2, 0.0)
    else:
        d = {(i, g): 0.0 for i in genes for g in names}
        gamma2 = 0.0
    post_mean, post_var = {}, {}
    for key in d:
        denom = gamma2 + v[key]
        w = gamma2 / denom if denom > 0 else 0.0
        post_mean[key] = w * d[key]
        post_var[key] = v[key] + w * v[key]
    stability = {
        i: sum(abs(post_mean[(i, g)]) + math.sqrt(post_var[(i, g)]) for g in names) / G
        for i in genes
    }
    pairs = {}
    for a, b in combinations(genes, 2):
        pairs[(a, b)] = (
            sum(
                abs(post_mean[(a, g)] + post_mean[(b, g)]) / 2
                + math.sqrt((post_var[(a, g)] + post_var[(b, g)]) / 4)
                for g in names
            )
            / G
        )
    return {"stability": stability, "gamma2": gamma2 if G >= 2 else None, "pairs": pairs}


def from_frame(matrix, candidates: Sequence[str], groups: Mapping[str, str] | None):  # noqa: ANN001, ANN201
    """Run :func:`normfinder` on a units x genes DataFrame (complete units, groups of >= 2)."""
    block = matrix[list(candidates)].dropna(how="any")
    labels = {str(u): (groups or {}).get(u, "all") if groups else "all" for u in block.index}
    labels = {u: g for u, g in labels.items() if g is not None}
    sizes: dict[str, int] = {}
    for g in labels.values():
        sizes[g] = sizes.get(g, 0) + 1
    labels = {u: g for u, g in labels.items() if sizes[g] >= 2}
    values = {gene: {str(u): float(block.at[u, gene]) for u in block.index} for gene in candidates}
    return normfinder({g: {u: values[g][u] for u in labels} for g in values}, labels)
