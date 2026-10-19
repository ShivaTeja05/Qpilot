"""The efficiency-model axis: which amplification efficiency turns a Cq into a starting quantity.

LinRegPCR reports ``N0 = Nq / E^Cq`` with one fluorescence threshold ``Nq`` per amplicon and run,
so ``log2 Nq = log2 N0 + Cq · log2 E`` is recovered exactly from its own output and any other
efficiency gives ``log2 N0(E) = log2 Nq − Cq · log2 E`` without re-running the curve analysis.
``Nq`` is the median over the run's wells of that amplicon with a quantity (CV 0.07 % on the
demo). Options (ids are stable; the science is in ``agent-bus/contracts/scientist-spec-numbers.md``
§1 and ``methods/efficiency_model.md``):

* ``linregpcr`` (primary): LinRegPCR's mean efficiency of the amplicon on each run, as today.
  The per-well table's ``n0`` is passed through untouched, never rebuilt.
* ``per_well``: each well's own efficiency; a well whose efficiency is not finite or outside
  (1.0, 2.3) is **excluded** (not a non-detect) and counted.
* ``amplicon_mean``: one efficiency per amplicon over all its runs (the runs' LinRegPCR means
  weighted by included wells); not applicable when every amplicon is on one run.
* ``assumed_2``: 2.0 for every well, the 2^−ΔΔCq assumption (common practice, not measured).
* ``standard_curve``: ``10^(−1/slope)`` of Cq against log10 quantity of the run's dilution
  standards (≥ 3 levels with a Cq); amplicons without a curve keep the primary and are listed.

Wells without a quantity under LinRegPCR stay without one under every option: the efficiency
model changes how much was there, never whether something amplified.

Deterministic; no model and no network.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from qpilot.qpcr.axes import AxisError, get_axis
from qpilot.qpcr.quant import EXCLUDED

AXIS = "efficiency"
PRIMARY = "linregpcr"
OPTIONS: tuple[str, ...] = tuple(o.id for o in get_axis(AXIS).catalogue)
E_VALID = (1.0, 2.3)  # LinRegPCR's own validity range for an efficiency (open interval)
STD_MIN_LEVELS = 3  # R² and linearity mean nothing with two levels (same as gate's G-STD)
METHOD_CARD_PATH = "methods/efficiency_model.md"
_STD_NAME = re.compile(r"(?i)^\s*std[\s_-]*(\d+(?:\.\d+)?)\s*$")

METHOD_CARD: dict[str, Any] = {
    "id": "efficiency_model",
    "version": "1",
    "title": "Which efficiency turns Cq into quantity",
    "source": (
        "Ruijter et al., Nucleic Acids Res 2009 (LinRegPCR, N0 = Nq/E^Cq); Livak & Schmittgen, "
        "Methods 2001 (E = 2 assumption); standard curve E = 10^(-1/slope)"
    ),
    "implementation": "qpilot/qpcr/axes/efficiency.py",
    "inputs": ["per-well table: run_id, target, sample_type, cq, n0, eff_target, eff_indiv"],
    "outputs": ["the per-well table with n0 under the chosen efficiency model"],
    "acceptance_tests": [
        "tests/numbers/test_efficiency.py::test_primary_is_passed_through",
        "tests/numbers/test_efficiency.py::test_rebuild_is_exact_on_a_toy_table",
        "tests/numbers/test_efficiency_demo.py::test_demo_flips_match_the_prototype",
    ],
    "licence": "Apache-2.0",
    "card": METHOD_CARD_PATH,
}


@dataclass(frozen=True)
class StdCurve:
    """A dilution-series fit for one amplicon on one run (Cq = intercept + slope · log10 q)."""

    run_id: str
    target: str
    slope: float
    intercept: float
    var_slope: float
    levels: int
    n_wells: int
    r2: float

    @property
    def efficiency(self) -> float:
        """``E = 10^(−1/slope)`` (2.0 = perfect doubling)."""
        return float(10 ** (-1 / self.slope))

    @property
    def var_efficiency(self) -> float:
        """Delta method: ``(E · ln10 / slope²)² · Var(slope)``."""
        return float((self.efficiency * math.log(10) / self.slope**2) ** 2 * self.var_slope)


@dataclass(frozen=True)
class Universe:
    """The per-well table under one efficiency model, and what the model could not do."""

    option: str
    table: pd.DataFrame
    n_excluded: int = 0  # per_well: wells whose own efficiency is outside the valid range
    fallback: tuple[str, ...] = ()  # standard_curve: amplicons that kept LinRegPCR's mean E
    notes: dict[str, str] = field(default_factory=dict)


def std_quantity(sample: str, quantities: Mapping[str, float] | None = None) -> float:
    """A standard's quantity: from the design when given, else from a ``STD_<copies>`` name."""
    if quantities and sample in quantities and quantities[sample]:
        return float(quantities[sample])
    match = _STD_NAME.match(str(sample))
    return float(match.group(1)) if match else float("nan")


def standard_curves(
    table: pd.DataFrame, quantities: Mapping[str, float] | None = None
) -> dict[tuple[str, str], StdCurve]:
    """Per (run, amplicon): an OLS fit of Cq on log10 quantity over the dilution standards.

    Only standards with a Cq and a positive quantity count; a fit needs at least
    :data:`STD_MIN_LEVELS` distinct quantities and a negative slope.
    """
    std = table[(table["sample_type"] == "std") & table["cq"].notna()]
    if EXCLUDED in std.columns:
        std = std[~std[EXCLUDED].astype(bool)]
    if std.empty:
        return {}
    q = std["sample"].map(lambda s: std_quantity(s, quantities)).to_numpy(dtype=float)
    std = std.assign(_lq=np.log10(np.where(q > 0, q, np.nan))).dropna(subset=["_lq"])
    out: dict[tuple[str, str], StdCurve] = {}
    for (run_id, target), rows in std.groupby(["run_id", "target"], sort=True):
        x, y = rows["_lq"].to_numpy(dtype=float), rows["cq"].to_numpy(dtype=float)
        levels = len(np.unique(x))
        if levels < STD_MIN_LEVELS:
            continue
        xm = x.mean()
        sxx = float(((x - xm) ** 2).sum())
        slope = float(((x - xm) * (y - y.mean())).sum() / sxx)
        intercept = float(y.mean() - slope * xm)
        resid = y - (intercept + slope * x)
        dof = len(x) - 2
        var_slope = float((resid**2).sum() / dof / sxx) if dof > 0 else float("nan")
        total = float(((y - y.mean()) ** 2).sum())
        r2 = 1 - float((resid**2).sum()) / total if total > 0 else float("nan")
        if slope < 0:
            out[(str(run_id), str(target))] = StdCurve(
                str(run_id), str(target), slope, intercept, var_slope, levels, len(x), r2
            )
    return out


def log2_nq(table: pd.DataFrame) -> pd.Series:
    """Per well: ``log2 Nq`` of its (run, amplicon), the median of ``log2(n0 · E^Cq)``."""
    ok = table["n0"].gt(0) & table["cq"].notna() & table["eff_target"].gt(0)
    per_well = np.log2(table["n0"].where(ok)) + table["cq"] * np.log2(table["eff_target"].where(ok))
    key = [table["run_id"], table["target"]]
    return per_well.groupby(key).transform("median")


def single_run(table: pd.DataFrame) -> bool:
    """True when every amplicon of the study wells is measured on one run only."""
    unknown = table[table["sample_type"] == "unkn"]
    return bool((unknown.groupby("target")["run_id"].nunique() <= 1).all())


def unavailable(table: pd.DataFrame, curves: Mapping[tuple[str, str], StdCurve]) -> dict[str, str]:
    """Options that do not apply to this study -> the reason, in plain words."""
    out = {}
    if single_run(table):
        out["amplicon_mean"] = (
            "every amplicon is on one run, so one efficiency per amplicon is LinRegPCR's own"
        )
    targets = set(table.loc[table["sample_type"] == "unkn", "target"])
    if not any(target in targets for _, target in curves):
        out["standard_curve"] = (
            f"no amplicon has a dilution series with at least {STD_MIN_LEVELS} levels"
        )
    return out


def _amplicon_mean(table: pd.DataFrame) -> pd.Series:
    """Per well: its amplicon's LinRegPCR mean E averaged over runs, weighted by study wells."""
    used = table[
        (table["sample_type"] == "unkn") & table["n0"].notna() & table["eff_target"].notna()
    ]
    weights = used.groupby(["target", "run_id"]).size()
    means = used.groupby(["target", "run_id"])["eff_target"].first()
    pooled = (means * weights).groupby(level="target").sum() / weights.groupby(level="target").sum()
    return table["target"].map(pooled).astype(float)


def universe(
    table: pd.DataFrame,
    option: str,
    curves: Mapping[tuple[str, str], StdCurve] | None = None,
) -> Universe:
    """The per-well table with ``n0`` under ``option`` (the primary returns ``table`` itself)."""
    if option not in OPTIONS:
        raise AxisError(f"unknown efficiency option {option!r} (known: {', '.join(OPTIONS)})")
    if option == PRIMARY:
        return Universe(option, table)
    eff = table["eff_target"].astype(float)
    n_excluded, fallback = 0, ()
    out = table.copy()
    if option == "per_well":
        own = table["eff_indiv"].astype(float)
        valid = np.isfinite(own) & (own > E_VALID[0]) & (own < E_VALID[1])
        drop = ~valid & table["n0"].notna() & (table["sample_type"] == "unkn")
        n_excluded = int(drop.sum())
        eff = own.where(valid, eff)
        flags = out[EXCLUDED].astype(bool) if EXCLUDED in out.columns else False
        out[EXCLUDED] = flags | drop
    elif option == "amplicon_mean":
        eff = _amplicon_mean(table)
    elif option == "assumed_2":
        eff = pd.Series(2.0, index=table.index)
    elif option == "standard_curve":
        curves = curves or {}
        keys = list(zip(table["run_id"].astype(str), table["target"].astype(str), strict=True))
        e_std = pd.Series(
            [curves[k].efficiency if k in curves else np.nan for k in keys], index=table.index
        )
        targets = set(table.loc[table["sample_type"] == "unkn", "target"].astype(str))
        fallback = tuple(sorted(t for t in targets if not any(k[1] == t for k in curves)))
        eff = e_std.where(e_std.notna(), eff)
    rebuilt = log2_nq(table) - table["cq"] * np.log2(eff)
    out["n0"] = np.exp2(rebuilt).where(table["n0"].notna())
    return Universe(option, out, n_excluded, fallback)


def variance_of_e(
    table: pd.DataFrame,
    option: str,
    curves: Mapping[tuple[str, str], StdCurve] | None = None,
) -> dict[str, float]:
    """Per amplicon: ``Var(E)`` of the efficiency the option uses (spec §2, delta method).

    ``linregpcr``/``amplicon_mean``: (SD of the included wells' own E)² / n included;
    ``standard_curve``: the fit's delta-method variance (mean over runs); ``per_well`` and
    ``assumed_2``: 0 (per-well noise is already in the unit-to-unit spread; an assumption is a
    bias, not a variance).
    """
    unknown = table[(table["sample_type"] == "unkn") & table["n0"].notna()]
    targets = sorted(unknown["target"].astype(str).unique())
    if option in ("per_well", "assumed_2"):
        return {t: 0.0 for t in targets}
    if option == "standard_curve" and curves:
        out = {}
        for t in targets:
            values = [c.var_efficiency for k, c in curves.items() if k[1] == t]
            if values:
                out[t] = float(np.mean(values))
        if out:
            primary = variance_of_e(table, PRIMARY)
            return {t: out.get(t, primary.get(t, 0.0)) for t in targets}
    own = unknown["eff_indiv"].astype(float)
    included = unknown[np.isfinite(own) & (own > E_VALID[0]) & (own < E_VALID[1])]
    grouped = included.groupby(included["target"].astype(str))["eff_indiv"]
    var = (grouped.std(ddof=1) ** 2 / grouped.count()).fillna(0.0)
    return {t: float(var.get(t, 0.0)) for t in targets}
