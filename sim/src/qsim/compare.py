"""Compare a scenario with the baseline, gene by gene, with explicit and configurable rules.

Impact classes (thresholds are defaults, not universal truths):

* ``changes_conclusion``: the call (up / down / none) is different.
* ``biases``: same call, but the estimate moved by at least ``bias_se`` baseline SEs.
* ``widens_uncertainty``: same call, smaller move, but the CI is ``widen`` times as wide.
* ``no_demonstrated_effect``: below every threshold; still reported.

Nothing here sorts scenarios by p-value or effect size.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from qsim.engine import CALL_NAMES, Engine

IMPACT_ORDER = (
    "invalidates",
    "changes_conclusion",
    "biases",
    "widens_uncertainty",
    "no_demonstrated_effect",
)


@dataclass(frozen=True)
class Thresholds:
    bias_se: float = 1.0
    widen: float = 1.25


DEFAULT_THRESHOLDS = Thresholds()


def compare(
    engine: Engine, base: dict, scen: dict, thresholds: Thresholds = DEFAULT_THRESHOLDS
) -> pd.DataFrame:
    rule = engine.rule
    d = scen["log2fc"] - base["log2fc"]
    d_se = d / base["se"]
    width = (scen["hi"] - scen["lo"]) / (base["hi"] - base["lo"])
    changed = scen["call"] != base["call"]
    impact = np.where(
        changed,
        "changes_conclusion",
        np.where(
            np.abs(d_se) >= thresholds.bias_se,
            "biases",
            np.where(width >= thresholds.widen, "widens_uncertainty", "no_demonstrated_effect"),
        ),
    )
    with np.errstate(divide="ignore"):
        sig_margin = np.log10(rule.alpha) - np.log10(np.maximum(scen["p_adj"], 1e-300))
    return pd.DataFrame(
        {
            "gene": engine.items,
            "base_call": [CALL_NAMES[int(c)] for c in base["call"]],
            "call": [CALL_NAMES[int(c)] for c in scen["call"]],
            "base_fold": 2 ** base["log2fc"],
            "fold": 2 ** scen["log2fc"],
            "d_log2fc": d,
            "d_in_se": d_se,
            "ci_width_ratio": width,
            "fold_margin_log2": np.abs(scen["log2fc"]) - rule.min_log2fc,
            "p_margin_decades": sig_margin,
            "impact": impact,
        }
    )


def whatif(
    engine: Engine, changes: dict[str, str], thresholds: Thresholds = DEFAULT_THRESHOLDS
) -> pd.DataFrame:
    """Any combination of choices against the baseline, for every gene."""
    space = engine.space
    base = engine.evaluate(space.baseline_index())
    scen = engine.evaluate(space.to_index(changes))
    return compare(engine, base, scen, thresholds)
