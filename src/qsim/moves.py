"""Distance to a different conclusion: the fewest defensible moves that change a call.

A **move** is one of:

* changing one analysis decision to another defensible option (question choices, the group
  cut-off and the multiple-testing rule, stay at their prespecified values);
* leaving out one sample. Both groups must keep at least two samples, so that a test is still
  possible; making the test impossible is not counted as a different conclusion.

The **distance** of a gene is the fewest moves after which its call (up, down or none) differs
from the call of the planned analysis. For a called gene it is how hard the finding is to
overturn. For a gene without a call it is how many moves manufacture one: a p-hacking budget.
One shortest path is reported in plain words, with the number of shortest paths found.

**The search** goes breadth first over the total number of moves d = choices + samples, up to
:data:`MAX_MOVES`, all genes at once:

* choices only: exact, read from the grid of defensible analyses;
* choices plus left-out samples: in every analysis at the right distance, every sample is
  tried, and every set of samples while there are at most :data:`PAIR_LIMIT` such sets (with
  366 tumours: every pair in the planned analysis). Removal uses exact closed-form updates of
  the Welch, Student and Mann-Whitney statistics (tie-corrected, as
  :func:`qsim.engine.mann_whitney`). Beyond that the search is greedy, as
  :func:`qsim.influence.drop_k`: each step leaves out the sample that brings the gene closest to
  its decision boundary.

A distance is **exact** when every combination with fewer moves was searched exhaustively. Every
reported path is re-run through :meth:`qsim.engine.Engine.evaluate` with the samples masked.
The closed form holds the "lowest detected value" used by the cap non-detect rule fixed, so the
re-run is the final word (``verified``).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from math import comb

import numpy as np
import pandas as pd
from scipy import stats

from qsim.engine import CALL_NAMES, DOWN, NONE, UP, Engine
from qsim.explore import distance

MAX_MOVES = 4
PAIR_LIMIT = 100_000  # sets of left-out samples tried exhaustively per gene and analysis
MIN_GROUP = 2


def _calls(diff: np.ndarray, p: np.ndarray, alpha: float, min_log2fc: float) -> np.ndarray:
    sig = p < alpha
    return np.where(
        sig & (diff >= min_log2fc), UP, np.where(sig & (diff <= -min_log2fc), DOWN, NONE)
    )


def _mwu_remove_each(v: np.ndarray, in_a: np.ndarray) -> np.ndarray:
    """Two-sided Mann-Whitney p after leaving out each value in turn (normal approximation with
    tie and continuity correction, exactly as :func:`qsim.engine.mann_whitney`)."""
    xa, xb = np.sort(v[in_a]), np.sort(v[~in_a])
    n1, n2 = len(xa), len(xb)
    lb = np.searchsorted(xb, v, "left")
    eb = np.searchsorted(xb, v, "right") - lb
    ra = np.searchsorted(xa, v, "right")
    ea = ra - np.searchsorted(xa, v, "left")
    u1 = (lb + 0.5 * eb)[in_a].sum()
    u1r = u1 - np.where(in_a, lb + 0.5 * eb, (n1 - ra) + 0.5 * ea)
    n1r, n2r = n1 - in_a, n2 - ~in_a
    nr = n1 + n2 - 1
    _, counts = np.unique(v, return_counts=True)
    ties = float((counts**3 - counts).sum())
    t = ea + eb  # how many values equal this one, itself included
    ties_r = ties - (t**3 - t) + ((t - 1) ** 3 - (t - 1))
    with np.errstate(divide="ignore", invalid="ignore"):
        sigma = np.sqrt(n1r * n2r / 12 * ((nr + 1) - ties_r / (nr * (nr - 1))))
        z = (np.abs(u1r - n1r * n2r / 2) - 0.5) / sigma
    return np.minimum(1.0, 2 * stats.norm.sf(z))


def remove_each(v: np.ndarray, in_a: np.ndarray, test: str) -> tuple[np.ndarray, np.ndarray]:
    """Mean difference (A - B) and p after leaving out each value in turn; p is NaN when a
    group would keep fewer than :data:`MIN_GROUP` values."""
    a_sum, b_sum = v[in_a].sum(), v[~in_a].sum()
    a_sq, b_sq = (v[in_a] ** 2).sum(), (v[~in_a] ** 2).sum()
    na = in_a.sum() - in_a
    nb = (~in_a).sum() - ~in_a
    sa = a_sum - np.where(in_a, v, 0.0)
    sb = b_sum - np.where(in_a, 0.0, v)
    qa = a_sq - np.where(in_a, v**2, 0.0)
    qb = b_sq - np.where(in_a, 0.0, v**2)
    with np.errstate(divide="ignore", invalid="ignore"):
        ma, mb = sa / na, sb / nb
        va = (qa - na * ma**2) / (na - 1)
        vb = (qb - nb * mb**2) / (nb - 1)
        diff = ma - mb
        if test == "student":
            pooled = ((na - 1) * va + (nb - 1) * vb) / (na + nb - 2)
            se = np.sqrt(pooled * (1 / na + 1 / nb))
            df = na + nb - 2.0
        else:
            se = np.sqrt(va / na + vb / nb)
            df = (va / na + vb / nb) ** 2 / ((va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1))
        p = _mwu_remove_each(v, in_a) if test == "mwu" else 2 * stats.t.sf(np.abs(diff / se), df)
    return diff, np.where((na < MIN_GROUP) | (nb < MIN_GROUP), np.nan, p)


class Cell:
    """One analysis: the samples x genes values and group masks the engine compares."""

    def __init__(self, engine: Engine, cell: tuple[int, ...]) -> None:
        v, ids = engine.values_of(cell), engine.ids_of(cell)
        if v["multiplicity"] != "none":
            raise ValueError("moves are searched with the multiple-testing rule at 'none'")
        matrix = engine.matrix(v["efficiency"], v["flagged"], v["nondetect"], late=v.get("late_cq"))
        rel, valid = engine.relative(matrix, ids["refs"])
        hi, lo = engine._masks[v["cut"]]
        self.rel, self.a, self.b = rel, valid & hi[:, None], valid & lo[:, None]
        self.test, self.cell = v["test"], cell

    def gene(
        self, g: int, left_out: tuple[int, ...] = ()
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(sample rows, values, in-group-A) of one gene's comparison without ``left_out``."""
        use = self.a[:, g] | self.b[:, g]
        if left_out:
            use = use.copy()
            use[list(left_out)] = False
        rows = np.where(use)[0]
        return rows, self.rel[rows, g], self.a[rows, g]


@dataclass
class Result:
    gene: str
    base_call: str
    distance: int | None = None
    choices: int | None = None
    samples: tuple[str, ...] = ()
    cell: tuple[int, ...] | None = None
    flips_to: str | None = None
    paths_found: int = 0
    exact: bool = False
    verified: bool | None = None
    # the fewest moves at which a greedy (not exhaustive) search was needed; every combination
    # with fewer moves was tried, so the true distance is at least this
    exhaustive_below: int = MAX_MOVES + 1
    path: list[str] = field(default_factory=list)


def fewest_moves(
    engine: Engine,
    cells: np.ndarray,
    calls: np.ndarray,
    max_moves: int = MAX_MOVES,
    genes: list[str] | None = None,
) -> pd.DataFrame:
    """Distance to a different conclusion for each gene.

    ``cells`` are the defensible analyses (full option indices, one row each) and ``calls`` their
    calls (cells x genes), e.g. from :meth:`Engine.run`; the baseline must be one of them.
    """
    space, rule = engine.space, engine.rule
    base = np.array(space.baseline_index())
    cells = np.asarray(cells)
    base_row = int(np.where((cells == base).all(axis=1))[0][0])
    dist = distance(cells, tuple(base))
    names = engine.items
    todo = list(range(len(names))) if genes is None else [names.index(g) for g in genes]
    base_call = calls[base_row]
    out = {g: Result(names[g], CALL_NAMES[int(base_call[g])]) for g in todo}
    states: dict[int, Cell] = {}

    def state(row: int) -> Cell:
        if row not in states:
            states[row] = Cell(engine, tuple(int(x) for x in cells[row]))
        return states[row]

    def found(g: int, d: int, row: int, left: tuple[int, ...], new: int, n: int = 1) -> None:
        r = out[g]
        if r.distance is None:
            r.distance, r.choices, r.cell = d, int(dist[row]), tuple(int(x) for x in cells[row])
            r.samples = tuple(engine.study.samples[i] for i in left)
            r.flips_to = CALL_NAMES[int(new)]
        r.paths_found += n

    for d in range(1, max_moves + 1):
        open_genes = [g for g in todo if out[g].distance is None]
        if not open_genes:
            break
        for s in range(0, d + 1):
            rows = np.where(dist == d - s)[0]
            for row in rows:
                if s == 0:
                    for g in open_genes:
                        if calls[row, g] != base_call[g]:
                            found(g, d, row, (), calls[row, g])
                    continue
                cell = state(row)
                for g in open_genes:
                    if out[g].distance is not None and out[g].distance < d:
                        continue
                    _search(cell, g, s, base_call[g], rule, d, row, found, out[g])
    for r in out.values():
        r.exact = r.distance is not None and r.distance <= r.exhaustive_below
        if r.distance is not None:
            g = names.index(r.gene)
            r.path = _words(engine, r)
            r.verified = _verify(engine, r, g, base_call[g])
    return pd.DataFrame(
        [
            {
                "gene": r.gene,
                "moves_to_flip": r.distance,
                "moves_exact": r.exact,
                "moves_choices": r.choices,
                "moves_samples": len(r.samples) if r.distance is not None else None,
                "moves_flips_to": r.flips_to,
                "moves_paths_found": r.paths_found,
                "moves_path": "; ".join(r.path),
                "moves_verified": r.verified,
                "moves_searched_exhaustively_below": r.exhaustive_below,
            }
            for r in out.values()
        ]
    ).set_index("gene")


def _frontier(n: int) -> int:
    """Fewest left-out samples whose combinations are too many to try (more than
    :data:`PAIR_LIMIT`): from that many moves on, a distance can no longer be shown exact."""
    s = 2
    while s <= n and comb(n, s) <= PAIR_LIMIT:
        s += 1
    return s


def _search(cell: Cell, g: int, s: int, base: int, rule, d: int, row: int, found, r: Result):
    """Leave out ``s`` samples in ``cell`` for gene ``g``. Exhaustive while that can still make
    the distance exact (fewer than :func:`_frontier` moves in total); greedy after that."""
    alpha, line = rule.alpha, rule.min_log2fc
    rows, v, in_a = cell.gene(g)
    n = len(rows)
    if s == 1 or d < _frontier(n):
        hits, first_hit = 0, None
        for first in itertools.combinations(range(n), s - 1):
            kept = np.delete(np.arange(n), first)
            diff, p = remove_each(v[kept], in_a[kept], cell.test)
            new = _calls(diff, np.nan_to_num(p, nan=1.0), alpha, line)
            ok = ~np.isnan(p) & (new != base)
            if first:
                ok &= kept > first[-1]  # each set of samples once
            if ok.any():
                hits += int(ok.sum())
                if first_hit is None:
                    k = int(np.where(ok)[0][0])
                    first_hit = (tuple(int(rows[i]) for i in (*first, kept[k])), new[k])
        if first_hit is not None:
            found(g, d, row, first_hit[0], first_hit[1], hits)
        return
    r.exhaustive_below = min(r.exhaustive_below, d)
    left: list[int] = []
    for step in range(s):
        rows_now, v_now, a_now = cell.gene(g, tuple(left))
        diff, p = remove_each(v_now, a_now, cell.test)
        new = _calls(diff, np.nan_to_num(p, nan=1.0), alpha, line)
        ok = ~np.isnan(p) & (new != base)
        if ok.any():
            if step == s - 1:
                j = int(np.where(ok)[0][0])
                found(g, d, row, tuple(left) + (int(rows_now[j]),), new[j])
            return
        score = np.minimum(
            np.abs(np.abs(diff) - line),
            np.abs(np.log10(np.maximum(np.nan_to_num(p, nan=1.0), 1e-300)) - np.log10(alpha)),
        )
        score[np.isnan(p)] = np.inf
        if not np.isfinite(score).any():
            return
        left.append(int(rows_now[int(np.argmin(score))]))


def _words(engine: Engine, r: Result) -> list[str]:
    space = engine.space
    base = space.baseline_index()
    parts = [
        f"{space.option(r.cell, d.id).label}"
        for k, d in enumerate(space.decisions)
        if r.cell[k] != base[k]
    ]
    parts += [f"leave out sample {s}" for s in r.samples]
    return parts


def _verify(engine: Engine, r: Result, g: int, base: int) -> bool:
    drop = None
    if r.samples:
        drop = np.zeros(engine.study.cq.shape, bool)
        for s in r.samples:
            drop[engine.study.samples.index(s), :] = True
    res = engine.evaluate(r.cell, drop=drop)
    return bool(CALL_NAMES[int(res["call"][g])] == r.flips_to and res["call"][g] != base)


def describe(row: pd.Series) -> str:
    """One line for a report: ``2 moves (exact): A; B -> none``."""
    if pd.isna(row["moves_to_flip"]):
        return f"not changed within {MAX_MOVES} moves"
    d = int(row["moves_to_flip"])
    exact = "" if row["moves_exact"] else ", at most"
    return f"{d} move{'s' if d > 1 else ''}{exact}: {row['moves_path']} → {row['moves_flips_to']}"


def defensible_grid(engine: Engine, allowed: list[list[int]], call_tensor: np.ndarray):
    """Cells and calls of a sub-factorial, in the order :class:`qsim.attribution.Factorial`
    stores them."""
    cells = np.array(list(itertools.product(*allowed)), dtype=np.int16)
    return cells, call_tensor.reshape(len(cells), -1)


# ---- does the distance predict a wrong call? ------------------------------------------


def _auroc(score: np.ndarray, positive: np.ndarray) -> float | None:
    """Probability that a positive scores above a negative (ties count half)."""
    pos, neg = int(positive.sum()), int((~positive).sum())
    if not pos or not neg:
        return None
    ranks = stats.rankdata(score)
    return float((ranks[positive].sum() - pos * (pos + 1) / 2) / (pos * neg))


def _logit_cv(x: np.ndarray, y: np.ndarray, groups: np.ndarray, folds: int = 5) -> float | None:
    """Out-of-fold AUROC of a ridge logistic model, folds split by draw."""
    from scipy.optimize import minimize

    if y.all() or not y.any():
        return None
    fold_of = {g: i % folds for i, g in enumerate(np.unique(groups))}
    f = np.array([fold_of[g] for g in groups])
    pred = np.empty(len(y))
    for k in range(folds):
        tr, te = f != k, f == k
        if not te.any() or y[tr].all() or not y[tr].any():
            pred[te] = y[tr].mean()
            continue
        mu, sd = x[tr].mean(0), x[tr].std(0) + 1e-12
        xt = np.column_stack([np.ones(tr.sum()), (x[tr] - mu) / sd])

        def loss(w, xt=xt, yt=y[tr]):
            z = xt @ w
            return np.sum(np.logaddexp(0, z) - yt * z) + 0.5 * w[1:] @ w[1:]

        w = minimize(loss, np.zeros(xt.shape[1]), method="BFGS").x
        pred[te] = np.column_stack([np.ones(te.sum()), (x[te] - mu) / sd]) @ w
    return _auroc(pred, y.astype(bool))


def _draw(study, space, cells, hi, lo, reference, draw: int) -> list[dict]:
    import dataclasses

    groups = {c: (frozenset(hi), frozenset(lo)) for c in study.groups}
    engine = Engine(dataclasses.replace(study, groups=groups), space)
    grid = engine.run(cells)
    base = grid.call[grid.row_of(space.baseline_index())]
    called = [engine.items[g] for g in np.where(base != 0)[0]]
    if not called:
        return []
    holds = (grid.call == base[None, :]).mean(axis=0)
    res = engine.evaluate(space.baseline_index())
    mv = fewest_moves(engine, cells, grid.call, genes=called)
    rows = []
    for gene in called:
        g = engine.items.index(gene)
        d = mv.loc[gene, "moves_to_flip"]
        rows.append(
            {
                "draw": draw,
                "gene": gene,
                "holds": float(holds[g]),
                "moves": MAX_MOVES + 1 if pd.isna(d) else int(d),
                "p": float(res["p"][g]),
                "margin": float(abs(res["log2fc"][g]) - engine.rule.min_log2fc),
                "wrong": True if reference is None else bool(base[g] != reference[g]),
            }
        )
    return rows


def predictive_value(
    study, space, sizes: tuple[int, ...] = (3, 6), draws: int = 100, seed: int = 2026
) -> dict:
    """On the small-experiment draws of :mod:`qsim.designs` (same seed, same order): does the
    distance tell a wrong call from a right one better than the agreement share does?

    * **Real difference** (n MYCN-high vs n other tumours): a call is wrong when it differs from
      the call on all 366 tumours (a reference, not the truth). AUROC of each signal alone, and
      out-of-fold AUROC of p + fold margin with and without each signal (folds split by draw).
    * **No difference** (both groups random): every call is false. The share of false calls a
      filter removes: distance of at least 2 or 3 moves, or the 95 % agreement filter.
    """
    from qsim.designs import ROBUST, defensible_cells

    rng = np.random.default_rng(np.random.SeedSequence(seed))
    cells = defensible_cells(space)
    reference = Engine(study, space).evaluate(space.baseline_index())["call"]
    hi_all, lo_all = (sorted(x) for x in study.groups[0.15])
    everyone = sorted(set(hi_all) | set(lo_all))
    tests = draws * len(study.items)
    out: dict = {"draws": draws, "max_moves": MAX_MOVES, "robust_rule": ROBUST, "sizes": {}}
    for n in sizes:
        null, real = [], []
        for k in range(draws):
            pick = rng.choice(everyone, 2 * n, replace=False)
            null += _draw(study, space, cells, list(pick[:n]), list(pick[n:]), None, k)
            hi = list(rng.choice(hi_all, n, replace=False))
            lo = list(rng.choice(lo_all, n, replace=False))
            real += _draw(study, space, cells, hi, lo, reference, k)
        r, z = pd.DataFrame(real), pd.DataFrame(null)
        entry: dict = {
            "no_difference": {
                "gene_tests": tests,
                "false_calls": int(len(z)),
                "false_call_rate": round(len(z) / tests, 4),
                "after_robust_filter": round(float((z["holds"] >= ROBUST).sum()) / tests, 4)
                if len(z)
                else 0.0,
                **{
                    f"after_distance_ge_{m}": round(float((z["moves"] >= m).sum()) / tests, 4)
                    if len(z)
                    else 0.0
                    for m in (2, 3)
                },
                "moves_of_false_calls": z["moves"].value_counts().sort_index().to_dict()
                if len(z)
                else {},
            }
        }
        if len(r):
            y = r["wrong"].to_numpy()
            base_x = np.column_stack([np.log10(np.maximum(r["p"], 1e-300)), r["margin"]])
            entry["real_difference"] = {
                "calls": int(len(r)),
                "share_wrong": round(float(y.mean()), 3),
                "auroc_alone": {
                    "agreement_share": _round(_auroc(-r["holds"].to_numpy(), y)),
                    "distance": _round(_auroc(-r["moves"].to_numpy(), y)),
                    "p_value": _round(_auroc(r["p"].to_numpy(), y)),
                    "fold_margin": _round(_auroc(-r["margin"].to_numpy(), y)),
                },
                "auroc_out_of_fold": {
                    "p_and_margin": _round(_logit_cv(base_x, y, r["draw"].to_numpy())),
                    "plus_agreement_share": _round(
                        _logit_cv(np.column_stack([base_x, r["holds"]]), y, r["draw"].to_numpy())
                    ),
                    "plus_distance": _round(
                        _logit_cv(np.column_stack([base_x, r["moves"]]), y, r["draw"].to_numpy())
                    ),
                },
                "share_wrong_by_distance": {
                    str(m): {
                        "calls": int(len(g)),
                        "share_wrong": round(float(g["wrong"].mean()), 3),
                    }
                    for m, g in r.groupby("moves")
                },
            }
        out["sizes"][str(n)] = entry
    return out


def _round(x: float | None) -> float | None:
    return None if x is None else round(x, 3)
