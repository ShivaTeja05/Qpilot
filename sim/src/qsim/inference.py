"""Joint inference across analyses: is a gene's association robust, with error control?

"Holds in 64 % of analyses" describes the multiverse; it is not a test. This module follows the
idea of PIMA (Girardi et al., Psychometrika 2024) with a permutation max-T procedure:

1. the forks are every defensible analysis with the Welch statistic (each reference subset of
   two or more genes, cut-off, efficiency model, flagged-well and non-detect rule);
2. the group labels are permuted B times. The groups are defined from MYCN expression, so the
   permutation shuffles which samples are "high", keeping the group sizes and the nesting of
   the 10 / 15 / 20 % cuts;
3. under each permutation every fork's Welch t is recomputed, and the maximum |t| across forks
   is kept per gene;
4. per gene, the global p-value is the share of permutations whose maximum reaches the
   observed maximum. A fork is significant with family-wise error control across forks when
   its |t| exceeds the 95th percentile of the permutation maxima;
5. Benjamini-Hochberg is applied across genes to the global p-values.

All Welch statistics come from three matrix products per batch of permutations over
precomputed (sample x fork-gene) arrays.
"""

from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

from qsim.engine import Engine, adjust


def forks(engine: Engine) -> list[tuple[int, ...]]:
    space = engine.space
    out = []
    for cell in itertools.product(*[range(n) for n in space.levels]):
        base = space.baseline_index()
        tier_ok = all(
            space.decisions[d].options[i].tier != "common_practice"
            and (space.decisions[d].role == "analysis" or i == base[d])
            for d, i in enumerate(cell)
        )
        a = space.to_assignment(cell)
        if tier_ok and a["test"] == "welch" and a["multiplicity"] == "none":
            out.append(cell)
    return out


def joint_test(
    engine: Engine, permutations: int = 999, seed: int = 2026, batch: int = 100
) -> tuple[pd.DataFrame, dict]:
    space = engine.space
    cells = forks(engine)
    cut_pos = space.names.index("cut")
    cut_values = [o.value for o in space.decision("cut").options]
    # distinct (matrix, refs) normalised arrays, shared by the three cuts
    keys = sorted({c[:cut_pos] for c in cells})
    rels, valids = [], []
    for key in keys:
        cell = (
            tuple(key) + (space.baseline_index()[cut_pos],) + space.baseline_index()[cut_pos + 1 :]
        )
        v, ids = engine.values_of(cell), engine.ids_of(cell)
        m = engine.matrix_of(v)
        rel, valid = engine.relative(m, ids["refs"])
        rels.append(np.where(valid, rel, 0.0))
        valids.append(valid.astype(float))
    n_items = len(engine.items)
    X = np.stack(rels, axis=1).reshape(len(engine.study.samples), -1)  # samples x (key, gene)
    X2 = X**2
    V = np.stack(valids, axis=1).reshape(len(engine.study.samples), -1)
    pool_hi, pool_lo = engine._masks[0.15]
    pool = np.where(pool_hi | pool_lo)[0]
    sizes = [int(engine._masks[c][0].sum()) for c in cut_values]

    def t_stats(masks_hi: np.ndarray, masks_lo: np.ndarray) -> np.ndarray:
        """masks: (m, samples) -> Welch t of shape (m, keys, genes)."""
        out = []
        for M in (masks_hi, masks_lo):
            n = M @ V
            s1 = M @ X
            s2 = M @ X2
            mean = s1 / n
            var = (s2 - n * mean**2) / (n - 1)
            out.append((n, mean, var))
        (na, ma, va), (nb, mb, vb) = out
        t = (ma - mb) / np.sqrt(va / na + vb / nb)
        return t.reshape(len(masks_hi), len(keys), n_items)

    def masks_for(order: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        hi = np.zeros((len(cut_values), len(engine.study.samples)))
        lo = np.zeros_like(hi)
        for c, size in enumerate(sizes):
            hi[c, pool[order[:size]]] = 1
            lo[c, pool[order[size:]]] = 1
        return hi, lo

    # observed: the real groups for each cut
    obs_hi = np.stack([engine._masks[c][0] for c in cut_values]).astype(float)
    obs_lo = np.stack([engine._masks[c][1] for c in cut_values]).astype(float)
    t_obs = t_stats(obs_hi, obs_lo)  # (cuts, keys, genes)
    used = np.zeros((len(cut_values), len(keys)), dtype=bool)
    for c in cells:
        used[c[cut_pos], keys.index(c[:cut_pos])] = True
    t_obs = np.where(used[..., None], t_obs, np.nan)
    obs_max = np.nanmax(np.abs(t_obs), axis=(0, 1))
    rng = np.random.default_rng(np.random.SeedSequence(seed))
    maxima = []
    for start in range(0, permutations, batch):
        b = min(batch, permutations - start)
        his, los = [], []
        for _ in range(b):
            h, lo_ = masks_for(rng.permutation(len(pool)))
            his.append(h)
            los.append(lo_)
        t = t_stats(np.concatenate(his), np.concatenate(los)).reshape(
            b, len(cut_values), len(keys), n_items
        )
        t = np.where(used[None, ..., None], np.abs(t), np.nan)
        maxima.append(np.nanmax(t, axis=(1, 2)))
    maxima = np.concatenate(maxima)  # (B, genes)
    p_global = (1 + (maxima >= obs_max[None, :]).sum(axis=0)) / (permutations + 1)
    crit = np.quantile(maxima, 0.95, axis=0)
    base = engine.evaluate(space.baseline_index())
    sign = np.sign(base["log2fc"])
    flat = t_obs.reshape(-1, n_items)
    ok = ~np.isnan(flat)
    sig = (np.abs(flat) > crit[None, :]) & ok
    same_dir = np.sign(flat) == sign[None, :]
    table = pd.DataFrame(
        {
            "gene": engine.items,
            "max_abs_t": obs_max,
            "p_global": p_global,
            "q_global_bh": adjust(p_global, "bh"),
            "fwer_crit_t": crit,
            "share_forks_significant": sig.sum(0) / ok.sum(0),
            "share_forks_significant_same_direction": (sig & same_dir).sum(0) / ok.sum(0),
        }
    )
    meta = {
        "forks": len(cells),
        "permutations": permutations,
        "seed": seed,
        "pooled_samples": int(len(pool)),
    }
    return table, meta
