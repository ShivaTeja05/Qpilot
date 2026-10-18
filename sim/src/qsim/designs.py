"""Typical bench experiments drawn from real data: does "holds across analyses" help?

Two tests, each repeated over many random draws of n tumours per group:

* **No difference.** Both groups are drawn at random from all tumours, ignoring MYCN, so any
  call is a false call. Measured: how often a single (baseline) analysis calls a gene, and how
  often a call survives the robustness filter (same call in at least 95 % of the defensible
  analyses).
* **Real difference, small n.** n MYCN-high and n other tumours. The reference answer is the
  call on all 366 tumours (a reference, not the truth). Measured: how often a small-study call
  disagrees with the reference, for calls that pass the filter versus calls that do not.

The defensible analyses are the study's defensible tiers with the question choice (the cut)
held fixed. Tiers come from the full study and are never tuned on these draws.
"""

from __future__ import annotations

import dataclasses
import itertools

import numpy as np
import pandas as pd

from qsim.data import Study
from qsim.decisions import Space
from qsim.engine import Engine

ROBUST = 0.95


def defensible_cells(space: Space) -> np.ndarray:
    base = space.baseline_index()
    axes = []
    for k, d in enumerate(space.decisions):
        if d.role == "question":
            axes.append([base[k]])
        else:
            axes.append([i for i, o in enumerate(d.options) if o.tier != "common_practice"])
    return np.array(list(itertools.product(*axes)), dtype=np.int16)


def _one(
    study: Study, space: Space, cells: np.ndarray, hi: list[str], lo: list[str]
) -> tuple[np.ndarray, np.ndarray]:
    groups = {c: (frozenset(hi), frozenset(lo)) for c in study.groups}
    engine = Engine(dataclasses.replace(study, groups=groups), space)
    grid = engine.run(cells)
    base = grid.call[grid.row_of(space.baseline_index())]
    holds = (grid.call == base[None, :]).mean(axis=0)
    return base, holds


def run(
    study: Study, space: Space, sizes: tuple[int, ...] = (3, 6), draws: int = 100, seed: int = 2026
) -> dict:
    rng = np.random.default_rng(np.random.SeedSequence(seed))
    cells = defensible_cells(space)
    reference = Engine(study, space).evaluate(space.baseline_index())["call"]
    hi_all, lo_all = (sorted(x) for x in study.groups[0.15])
    everyone = sorted(set(hi_all) | set(lo_all))
    out = {"defensible_cells": int(len(cells)), "draws": draws, "robust_rule": ROBUST, "sizes": {}}
    for n in sizes:
        null_calls = null_robust = 0
        real = []
        for _ in range(draws):
            pick = rng.choice(everyone, 2 * n, replace=False)
            base, holds = _one(study, space, cells, list(pick[:n]), list(pick[n:]))
            called = base != 0
            null_calls += int(called.sum())
            null_robust += int((called & (holds >= ROBUST)).sum())
            hi = list(rng.choice(hi_all, n, replace=False))
            lo = list(rng.choice(lo_all, n, replace=False))
            base, holds = _one(study, space, cells, hi, lo)
            for g in np.where(base != 0)[0]:
                real.append(
                    {"robust": bool(holds[g] >= ROBUST), "agrees": bool(base[g] == reference[g])}
                )
        tests = draws * len(reference)
        r = pd.DataFrame(real)
        rob = r[r["robust"]] if len(r) else r
        frag = r[~r["robust"]] if len(r) else r
        out["sizes"][str(n)] = {
            "no_difference": {
                "gene_tests": tests,
                "false_call_rate_single_analysis": round(null_calls / tests, 4),
                "false_call_rate_after_robust_filter": round(null_robust / tests, 4),
            },
            "real_difference": {
                "calls": int(len(r)),
                "share_robust": round(float(r["robust"].mean()), 3) if len(r) else None,
                "disagree_with_full_study_if_robust": round(float(1 - rob["agrees"].mean()), 3)
                if len(rob)
                else None,
                "disagree_with_full_study_if_not_robust": round(float(1 - frag["agrees"].mean()), 3)
                if len(frag)
                else None,
            },
        }
    return out
