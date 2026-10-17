"""What each conclusion leans on: samples, reference wells and the margin to the boundary.

All at the baseline analysis (Welch test, no correction), with exact closed-form updates of the
group sums, so no approximation is involved:

* ``leave_one_out``: drop one sample (its target well) from one gene's comparison;
* ``reference_wells``: drop one reference-gene well from one sample's normaliser. One reference
  well feeds every gene of that sample, so a single well can move many conclusions;
* ``drop_k``: the fewest samples whose removal flips a call, by greedy search (an upper bound).

These are perturbations of the observed data and are labelled as such; nothing is ever written
back into the measured values.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from qsim.engine import CALL_NAMES, DOWN, NONE, UP, Engine


def _welch_from_sums(n_a, s_a, q_a, n_b, s_b, q_b):
    ma, mb = s_a / n_a, s_b / n_b
    va = (q_a - n_a * ma**2) / (n_a - 1)
    vb = (q_b - n_b * mb**2) / (n_b - 1)
    sa, sb = va / n_a, vb / n_b
    se = np.sqrt(sa + sb)
    diff = ma - mb
    df = (sa + sb) ** 2 / (sa**2 / (n_a - 1) + sb**2 / (n_b - 1))
    p = 2 * stats.t.sf(np.abs(diff / se), df)
    return diff, se, p


def _call(diff, p, rule):
    sig = p < rule.alpha
    return np.where(
        sig & (diff >= rule.min_log2fc), UP, np.where(sig & (diff <= -rule.min_log2fc), DOWN, NONE)
    )


class Baseline:
    """Group sums of the baseline comparison, for exact one-sample updates."""

    def __init__(self, engine: Engine) -> None:
        space = engine.space
        cell = space.baseline_index()
        v = engine.values_of(cell)
        ids = engine.ids_of(cell)
        matrix = engine.matrix(v["efficiency"], v["flagged"], v["nondetect"])
        self.values, _ = matrix
        self.rel, self.valid = engine.relative(matrix, ids["refs"])
        self.ref_cols = engine._ref_cols[ids["refs"]]
        self.hi, self.lo = engine._masks[v["cut"]]
        self.engine, self.rule = engine, engine.rule
        x = np.where(self.valid, self.rel, 0.0)
        self.x = x
        a = self.valid & self.hi[:, None]
        b = self.valid & self.lo[:, None]
        self.a, self.b = a, b
        self.sums = (
            a.sum(0),
            (x * a).sum(0),
            (x**2 * a).sum(0),
            b.sum(0),
            (x * b).sum(0),
            (x**2 * b).sum(0),
        )
        diff, se, p = _welch_from_sums(*self.sums)
        self.diff, self.se, self.p = diff, se, p
        self.call = _call(diff, p, self.rule)


def leave_one_out(engine: Engine, base: Baseline | None = None) -> pd.DataFrame:
    """Every (sample, gene): the change in log2 fold change and the call when it is dropped."""
    base = base or Baseline(engine)
    n_a, s_a, q_a, n_b, s_b, q_b = base.sums
    x, a, b = base.x, base.a, base.b
    na = n_a - a
    sa = s_a - x * a
    qa = q_a - x**2 * a
    nb = n_b - b
    sb = s_b - x * b
    qb = q_b - x**2 * b
    diff, se, p = _welch_from_sums(na, sa, qa, nb, sb, qb)
    call = _call(diff, p, base.rule)
    used = a | b
    s = engine.study
    rows = np.argwhere(used)
    items = np.array(engine.items)
    cols = s.item_columns()
    return pd.DataFrame(
        {
            "sample": np.array(s.samples)[rows[:, 0]],
            "gene": items[rows[:, 1]],
            "plate": s.run[rows[:, 0], cols[rows[:, 1]]],
            "well": s.well[rows[:, 0], cols[rows[:, 1]]],
            "group": np.where(base.hi[rows[:, 0]], "high", "rest"),
            "d_log2fc": (diff - base.diff[None, :])[used],
            "d_in_se": ((diff - base.diff[None, :]) / base.se[None, :])[used],
            "base_call": [CALL_NAMES[int(c)] for c in base.call[rows[:, 1]]],
            "call": [CALL_NAMES[int(c)] for c in call[used]],
        }
    ).assign(flips=lambda f: f["call"] != f["base_call"])


def reference_wells(engine: Engine, base: Baseline | None = None) -> pd.DataFrame:
    """Drop one reference well from one sample's normaliser; effect on every gene at once."""
    base = base or Baseline(engine)
    s = engine.study
    ref = base.values[:, base.ref_cols]
    k = ref.shape[1]
    full_mean = ref.mean(axis=1)
    out = []
    n_a, s_a, q_a, n_b, s_b, q_b = base.sums
    for i in np.where(~np.isnan(full_mean))[0]:
        for j in range(k):
            others = np.delete(ref[i], j)
            delta = full_mean[i] - others.mean()  # rel = target - mean, so rel rises by delta
            row = base.x[i]
            new = row + delta
            in_a, in_b = base.a[i], base.b[i]
            sa = s_a + np.where(in_a, delta, 0)
            qa = q_a + np.where(in_a, new**2 - row**2, 0)
            sb = s_b + np.where(in_b, delta, 0)
            qb = q_b + np.where(in_b, new**2 - row**2, 0)
            diff, se, p = _welch_from_sums(n_a, sa, qa, n_b, sb, qb)
            call = _call(diff, p, base.rule)
            flipped = np.array(engine.items)[call != base.call]
            gene = s.genes[base.ref_cols[j]]
            out.append(
                {
                    "sample": s.samples[i],
                    "reference": gene,
                    "plate": s.run[i, base.ref_cols[j]],
                    "well": s.well[i, base.ref_cols[j]],
                    "max_abs_d_in_se": float(np.nanmax(np.abs((diff - base.diff) / base.se))),
                    "genes_flipped": len(flipped),
                    "flipped": ",".join(flipped),
                }
            )
    return pd.DataFrame(out)


def drop_k(engine: Engine, gene: str, k_max: int = 5, base: Baseline | None = None) -> dict:
    """Greedy: repeatedly drop the sample that moves the gene closest to its decision boundary."""
    base = base or Baseline(engine)
    g = engine.items.index(gene)
    x, a, b = base.x[:, g], base.a[:, g].copy(), base.b[:, g].copy()
    start = int(base.call[g])
    removed = []
    rule = base.rule
    for _ in range(k_max):
        best = None
        for i in np.where(a | b)[0]:
            aa, bb = a.copy(), b.copy()
            aa[i] = bb[i] = False
            diff, _, p = _welch_from_sums(
                aa.sum(),
                (x * aa).sum(),
                (x**2 * aa).sum(),
                bb.sum(),
                (x * bb).sum(),
                (x**2 * bb).sum(),
            )
            c = int(_call(np.array(diff), np.array(p), rule))
            if c != start:
                removed.append(engine.study.samples[i])
                return {
                    "gene": gene,
                    "k": len(removed),
                    "samples": removed,
                    "flips_to": CALL_NAMES[c],
                }
            score = min(
                abs(abs(diff) - rule.min_log2fc),
                abs(np.log10(max(p, 1e-300)) - np.log10(rule.alpha)),
            )
            if best is None or score < best[0]:
                best = (score, i)
        i = best[1]
        a[i] = b[i] = False
        removed.append(engine.study.samples[i])
    return {"gene": gene, "k": None, "samples": [], "flips_to": None}


def margins(engine: Engine, base: Baseline | None = None) -> pd.DataFrame:
    """How far each baseline call is from its two boundaries (fold line, p threshold)."""
    base = base or Baseline(engine)
    rule = base.rule
    return pd.DataFrame(
        {
            "gene": engine.items,
            "call": [CALL_NAMES[int(c)] for c in base.call],
            "fold": 2**base.diff,
            "fold_margin_log2": np.abs(base.diff) - rule.min_log2fc,
            "fold_margin_in_se": (np.abs(base.diff) - rule.min_log2fc) / base.se,
            "p": base.p,
            "p_margin_decades": np.log10(rule.alpha) - np.log10(np.maximum(base.p, 1e-300)),
        }
    )
