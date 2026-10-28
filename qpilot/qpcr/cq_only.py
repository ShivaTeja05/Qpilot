"""A file of Cq values only: how qPilot analyses a study that has no amplification curves.

Many labs keep only the Cq values the instrument software exported (a Cq table typed or saved
in Excel, an RDML file without curves). :mod:`qpilot.qpcr.curves` reads such a file into the
same per-well table as any other (:func:`qpilot.qpcr.curves.cq_only_run`): each well's Cq is
the file's, its quantity ``N0 = E^-Cq``, and nothing a fit gives (baseline, the well's own
efficiency, R², LinRegPCR's note) is there (:func:`qpilot.qpcr.curves.without_curves`). The
rest of the engine is unchanged: the quantities, the control genes, the comparison, the
robustness grid, the Decision Cards, Trace, the exports and the Analysis Record read that table
as they read LinRegPCR's.

**Efficiency, per assay** (:func:`efficiency_plan`, applied by
:func:`qpilot.qpcr.designs.design_curves`): with no curve there is no well's own efficiency
and no LinRegPCR mean, so ``E`` is

* the assay's **dilution series** on the plate, when the design has one there (the standards'
  quantities a person set, else a ``STD_<number>`` name; at least
  :data:`~qpilot.qpcr.axes.efficiency.STD_MIN_LEVELS` levels with a Cq and a falling line,
  exactly the fit of the efficiency axis' ``standard_curve`` option): ``E = 10^(-1/slope)``;
* on a plate without its own series, the mean ``E`` of the assay's series on its other plates
  (one efficiency per assay, Pfaffl's usage);
* otherwise **assumed 2.0** (every cycle doubles the product: the 2^-ΔΔCq assumption). A
  series whose ``E`` is outside LinRegPCR's validity range (1.0, 2.3), which no PCR can have,
  is not used, and the reason is given.

What needs a curve is **not applicable**, said in plain words (:data:`NOT_APPLICABLE`):
LinRegPCR's baseline, efficiency and R² per well, the Curve Judge, the raw-ness check, melt
curves, and the efficiency models built from LinRegPCR's numbers (``per_well``,
``amplicon_mean``). What a Cq table does have is checked as usual: the Cq cut-offs, non-detects
(the empty-well rule), replicate spread (G-REP), controls, standards (G-STD), the reference
genes and the efficiency assumption (the efficiency axis' ``assumed_2`` when a series is used).

**Confidence** (:func:`cap_for`, qPilot policy as for the Import Trust card's Cq only, worded
"qPilot caps…"): capped at **Low** while any assay's efficiency is assumed, at **Moderate** when
every assay's comes from its dilution series (no well's curve could be checked either way).

Pure and deterministic: no model, no network; every sentence is qPilot's own wording.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

from qpilot.core.confidence import Cap
from qpilot.qpcr.axes import efficiency as eff_axis
from qpilot.qpcr.curves import ASSUMED_EFFICIENCY, without_curves
from qpilot.qpcr.quant import EXCLUDED

__all__ = [
    "ASSUMED_EFFICIENCY",
    "CAP_ID",
    "CQ_RULE_LABEL",
    "NOT_APPLICABLE",
    "assay_note",
    "AssayEfficiency",
    "EfficiencyPlan",
    "cap_for",
    "efficiency_plan",
    "efficiency_words",
    "not_measured",
    "with_efficiency",
    "without_curves",
]

CAP_ID = "cq_only"  # the cap's id among a grade's checks
#: The ``linregpcr`` amplification rule's label for a file of Cq values only (same rule, no fit).
CQ_RULE_LABEL = "The file's own Cq (a well counts when the file gives it a Cq)"
Source = Literal["dilution_series", "assumed"]
#: What needs an amplification curve, in plain words, for every place that would show it.
NOT_APPLICABLE: dict[str, str] = {
    "linregpcr": (
        "Not applicable: this file has Cq values only, so there is no curve for LinRegPCR to "
        "fit (no baseline, no efficiency of its own and no fit quality per well)."
    ),
    "curve_judge": (
        "Not applicable: this file has Cq values only, so there is no curve for the Curve "
        "Judge to read."
    ),
    "rawness": (
        "Not applicable: this file has Cq values only, so there are no curves whose processing "
        "before export could be checked."
    ),
    "melt": "Not applicable: this file has Cq values only, so it has no melt curves.",
    "per_well": (
        "Not applicable: this file has Cq values only, so no well's own efficiency was measured."
    ),
    "amplicon_mean": (
        "Not applicable: this file has Cq values only, so LinRegPCR measured no efficiency to "
        "average over plates."
    ),
}
_IN_USE_SERIES = (
    "the analysis in use already takes each assay's efficiency from its dilution series"
)
_IN_USE_ASSUMED = (
    "the analysis in use already assumes an efficiency of 2.0 (no assay has a dilution series "
    "with at least {levels} levels)"
)
_CAP_LOW = (
    "qPilot caps confidence at Low: this file has Cq values only, so no amplification curve "
    "was checked, and the efficiency of an assay without a dilution series is assumed (every "
    "cycle doubles the product), not measured"
)
_CAP_MODERATE = (
    "qPilot caps confidence at Moderate: this file has Cq values only, so no well's "
    "amplification curve could be checked (each assay's efficiency is from its dilution series)"
)


@dataclass(frozen=True)
class AssayEfficiency:
    """The efficiency one assay's quantities use, where it comes from, and in words."""

    target: str
    efficiency: float  # E: 2.0 = every cycle doubles the product
    source: Source
    runs: tuple[str, ...] = ()  # the plates whose dilution series gave it
    levels: int = 0  # the fewest levels of those series
    r2: float | None = None  # the lowest R² of those series
    rejected: tuple[tuple[str, float], ...] = ()  # (plate, E) of series outside (1.0, 2.3)

    def as_dict(self) -> dict[str, Any]:
        """JSON form (for views, facts and the Analysis Record)."""
        return {
            "target": self.target,
            "efficiency": self.efficiency,
            "source": self.source,
            "runs": list(self.runs),
            "levels": self.levels,
            "r2": self.r2,
            "rejected": [{"run": r, "efficiency": e} for r, e in self.rejected],
            "words": efficiency_words(self),
        }


@dataclass(frozen=True)
class EfficiencyPlan:
    """Per plate and assay the efficiency to use, and per assay what it is and why."""

    by_run: Mapping[tuple[str, str], float] = field(default_factory=dict)
    assays: Mapping[str, AssayEfficiency] = field(default_factory=dict)

    @property
    def assumed(self) -> tuple[str, ...]:
        """Assays whose efficiency is assumed (no usable dilution series), sorted."""
        return tuple(sorted(t for t, a in self.assays.items() if a.source == "assumed"))

    @property
    def measured(self) -> tuple[str, ...]:
        """Assays whose efficiency comes from a dilution series, sorted."""
        return tuple(sorted(t for t, a in self.assays.items() if a.source == "dilution_series"))


def _quantities(design: Any) -> dict[str, float]:
    if design is None:
        return {}
    return {s: float(d.quantity) for s, d in design.samples.items() if d.quantity}


def efficiency_plan(table: pd.DataFrame, design: Any = None) -> EfficiencyPlan:
    """Each assay's efficiency in a table of Cq values only (see the module docstring).

    ``table`` is the per-well table with the design's roles and exclusions applied (the
    standards are ``sample_type == "std"``); ``design`` gives the standards' quantities. A
    table with curves gets an empty plan (LinRegPCR measured its efficiencies).
    """
    if not without_curves(table):
        return EfficiencyPlan()
    curves = eff_axis.standard_curves(table, _quantities(design))
    low, high = eff_axis.E_VALID
    valid = {k: c for k, c in curves.items() if low < c.efficiency < high}
    targets = sorted(set(table["target"].astype(str)))
    by_run: dict[tuple[str, str], float] = {}
    assays: dict[str, AssayEfficiency] = {}
    for target in targets:
        own = {run: c for (run, t), c in valid.items() if t == target}
        rejected = tuple(
            (run, round(c.efficiency, 6))
            for (run, t), c in sorted(curves.items())
            if t == target and (run, t) not in valid
        )
        if own:
            mean = float(np.mean([c.efficiency for c in own.values()]))
            assays[target] = AssayEfficiency(
                target=target,
                efficiency=mean,
                source="dilution_series",
                runs=tuple(sorted(own)),
                levels=min(c.levels for c in own.values()),
                r2=min(c.r2 for c in own.values()),
                rejected=rejected,
            )
        else:
            mean = ASSUMED_EFFICIENCY
            assays[target] = AssayEfficiency(target, mean, "assumed", rejected=rejected)
        rows = table[table["target"].astype(str) == target]
        for run in sorted(set(rows["run_id"].astype(str))):
            by_run[(run, target)] = own[run].efficiency if run in own else mean
    return EfficiencyPlan(by_run=by_run, assays=assays)


def with_efficiency(table: pd.DataFrame, plan: EfficiencyPlan) -> pd.DataFrame:
    """The table with each plate and assay's efficiency and ``N0 = E^-Cq`` (a copy).

    Wells whose efficiency stays 2.0 keep the quantity they were read with, bit for bit.
    """
    if not plan.by_run:
        return table
    keys = list(zip(table["run_id"].astype(str), table["target"].astype(str), strict=True))
    eff = pd.Series(
        [plan.by_run.get(k, ASSUMED_EFFICIENCY) for k in keys], index=table.index, dtype=float
    )
    moved = eff.ne(ASSUMED_EFFICIENCY)
    if not moved.any():
        return table
    out = table.copy()
    out.loc[moved, "eff_target"] = eff[moved]
    cq = out.loc[moved, "cq"].astype(float)
    out.loc[moved, "n0"] = np.power(eff[moved], -cq).where(cq.notna())
    return out


def efficiency_words(assay: AssayEfficiency) -> str:
    """One assay's efficiency in a sentence a scientist reads (no fold change, no group)."""
    pct = (assay.efficiency - 1) * 100
    if assay.source == "dilution_series":
        plates = ", ".join(assay.runs)
        r2 = f", R² {assay.r2:.3f}" if assay.r2 is not None and np.isfinite(assay.r2) else ""
        text = (
            f"{assay.target}: efficiency {assay.efficiency:.2f} ({pct:.0f} %) from its dilution "
            f"series ({assay.levels} levels{r2}; plate {plates})"
        )
    else:
        text = (
            f"{assay.target}: efficiency assumed to be 2.0 (100 %), every cycle doubling the "
            "product: no dilution series of this assay"
        )
    if assay.rejected:
        found = "; ".join(f"{e:.2f} on plate {r}" for r, e in assay.rejected)
        text += (
            f" (a dilution series gives {found}, outside the range a PCR can have, so it is not "
            "used)"
        )
    return text + "."


def not_measured(plan: EfficiencyPlan) -> dict[str, str]:
    """Efficiency models that do not apply to a Cq-only study -> why, in plain words.

    ``per_well`` and ``amplicon_mean`` need LinRegPCR's numbers. ``standard_curve`` is the
    analysis in use wherever an assay has a series; ``assumed_2`` is the analysis in use when
    no assay has one. An empty plan (a study with curves) changes nothing.
    """
    if not plan.assays:
        return {}
    out = {"per_well": NOT_APPLICABLE["per_well"], "amplicon_mean": NOT_APPLICABLE["amplicon_mean"]}
    if plan.measured:
        out["standard_curve"] = _IN_USE_SERIES
    else:
        out["assumed_2"] = _IN_USE_ASSUMED.format(levels=eff_axis.STD_MIN_LEVELS)
    return out


def cap_for(plan: EfficiencyPlan, genes: Any = None) -> Cap | None:
    """The cap on every grade of a Cq-only study (``None`` for a study with curves).

    ``genes`` limits the assays whose efficiency counts to the ones analysed (the study's genes
    and its control genes); by default every assay in the plan counts.
    """
    if not plan.assays:
        return None
    wanted = set(genes) if genes is not None else set(plan.assays)
    assumed = [t for t in plan.assumed if t in wanted]
    if assumed:  # which assays: the facts f_eff_assumed_genes (a reason holds no gene name)
        return Cap(level="Low", check_id=CAP_ID, note=_CAP_LOW)
    return Cap(level="Moderate", check_id=CAP_ID, note=_CAP_MODERATE)


def assay_note(plan: EfficiencyPlan, gene: str) -> str:
    """The assay check of a gene's grade in a Cq-only study (no LinRegPCR, no curve)."""
    found = plan.assays.get(gene)
    source = (
        "from its dilution series"
        if found is not None and found.source == "dilution_series"
        else "assumed (every cycle doubles the product)"
    )
    return (
        f"Cq values only (no curves): this assay's efficiency is {source}; undetermined wells "
        "reported; LOD/LOQ not determined."
    )


def detected_counts(table: pd.DataFrame) -> dict[str, int]:
    """Study wells with and without a Cq (wells a person left out are not counted)."""
    study = table[table["sample_type"] == "unkn"]
    if EXCLUDED in study.columns:
        study = study[~study[EXCLUDED].astype(bool)]
    with_cq = int(study["cq"].notna().sum())
    return {"n_wells": len(study), "n_with_cq": with_cq, "n_without_cq": len(study) - with_cq}
