"""Plain-language verdicts for every gene, from explicit rules a scientist can read.

For a called gene (up or down at the baseline):

* **check data first**: a data finding (not a choice) changes this call when remedied;
* **solid**: same call in at least 95 % of the defensible analyses, no 5 or fewer samples
  overturn it, and the effect is significant in at least 95 % of analyses (joint test);
* **fragile**: same call in under 80 % of the defensible analyses, or 2 or fewer samples
  overturn it, or it sits within 0.1 log2 (about 7 %) of the fold-change line;
* **holds with caveats**: same call in at least 95 % of analyses, but 5 or fewer samples
  overturn it or significance is not robust;
* **depends on your choices**: everything in between (same call in 80-95 % of analyses).

A gene without a call is reported as "no call" with the share of analyses that would call it.
The thresholds are defaults in :data:`RULES`, shown with every verdict, never hidden.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from qsim.attribution import Factorial
from qsim.engine import CALL_NAMES, Engine

RULES = {
    "solid_holds": 0.95,
    "solid_significant": 0.95,
    "fragile_holds": 0.80,
    "fragile_drop_k": 2,
    "fragile_margin_log2": 0.1,
    "drop_k_searched": 5,
}
ORDER = (
    "check data first",
    "fragile",
    "depends on your choices",
    "holds with caveats",
    "solid",
    "no call",
)


def verdicts(genes: pd.DataFrame, issues: list[dict]) -> pd.Series:
    data_hits: set[str] = set()
    for issue in issues:
        if issue["kind"] != "decision" and issue["impact"] in ("invalidates", "changes_conclusion"):
            data_hits |= set(issue["changed_calls"])

    def one(gene: str, r: pd.Series) -> str:
        if r["all_baseline_call"] == "none":
            return "no call"
        if gene in data_hits:
            return "check data first"
        dk = r["drop_k_to_flip"]
        if (
            r["defensible_holds"] < RULES["fragile_holds"]
            or (not pd.isna(dk) and dk <= RULES["fragile_drop_k"])
            or r["fold_margin_log2"] < RULES["fragile_margin_log2"]
        ):
            return "fragile"
        if (
            r["defensible_holds"] >= RULES["solid_holds"]
            and pd.isna(dk)
            and r["share_forks_significant_same_direction"] >= RULES["solid_significant"]
        ):
            return "solid"
        if r["defensible_holds"] >= RULES["solid_holds"]:
            return "holds with caveats"
        return "depends on your choices"

    return pd.Series({g: one(g, r) for g, r in genes.iterrows()}, name="verdict")


def fold_words(log2fc: float) -> str:
    f = 2**log2fc
    return f"{f:.2f}× higher" if f >= 1 else f"{1 / f:.2f}× lower"


def explain(engine: Engine, defensible: Factorial, genes: pd.DataFrame, verdict: pd.Series) -> dict:
    """Per gene: verdict, baseline, and concrete choices that flip it (with the new result)."""
    space = engine.space
    base = engine.evaluate(space.baseline_index())
    out = {}
    for i, gene in enumerate(engine.items):
        sets = defensible.minimal_flip_sets(gene)
        flips = []
        for decisions in sets[:4]:
            cell = _flip_cell(defensible, gene, decisions)
            if cell is None:
                continue
            res = engine.evaluate(cell)
            flips.append(
                {
                    "decisions": list(decisions),
                    "choices": [space.option(cell, d).label for d in decisions],
                    "option_ids": {d: space.option(cell, d).id for d in decisions},
                    "fold": float(2 ** res["log2fc"][i]),
                    "call": CALL_NAMES[int(res["call"][i])],
                }
            )
        r = genes.loc[gene]
        out[gene] = {
            "verdict": verdict[gene],
            "call": CALL_NAMES[int(base["call"][i])],
            "log2fc": float(base["log2fc"][i]),
            "fold": float(2 ** base["log2fc"][i]),
            "fold_words": fold_words(float(base["log2fc"][i])),
            "ci": [float(2 ** base["lo"][i]), float(2 ** base["hi"][i])],
            "p": float(base["p"][i]),
            "holds_defensible": float(r["defensible_holds"]),
            "analyses_defensible": int(defensible.n_cells),
            "drop_k": None if pd.isna(r["drop_k_to_flip"]) else int(r["drop_k_to_flip"]),
            "fold_margin_log2": float(r["fold_margin_log2"]),
            "share_significant": float(r["share_forks_significant_same_direction"]),
            "flips": flips,
            "moves": _moves(r),
        }
    return out


def _moves(r: pd.Series) -> dict | None:
    """The distance to a different conclusion, when the run computed it."""
    if "moves_to_flip" not in r.index:
        return None
    found = not pd.isna(r["moves_to_flip"])
    return {
        "distance": int(r["moves_to_flip"]) if found else None,
        "exact": bool(r["moves_exact"]) if found else False,
        "path": str(r["moves_path"]).split("; ")
        if found and isinstance(r["moves_path"], str)
        else [],
        "call": r["moves_flips_to"] if found else None,
        "searched_up_to": int(r["moves_searched_exhaustively_below"]) if not found else None,
    }


def _flip_cell(f: Factorial, gene: str, decisions: tuple[str, ...]) -> tuple[int, ...] | None:
    """One defensible cell that changes exactly ``decisions`` and flips ``gene``."""
    g = f.grid.items.index(gene)
    pos = [f.names.index(d) for d in decisions]
    hits = np.argwhere(f.flipped[..., g])
    for local in hits:
        changed = [k for k, (v, b) in enumerate(zip(local, f.base_pos, strict=True)) if v != b]
        if changed == sorted(pos):
            return tuple(int(f.allowed[k][v]) for k, v in enumerate(local))
    return None
