"""Each biological unit's value of one gene, with the wells behind it (the engine's own numbers).

The Gene section's "Your samples" shows these whenever the robustness audit is not there to
draw them, so it is never empty once Results exist. The values are the Prism bridge's
(:func:`qpilot.qpcr.export.study_inputs`, which refuses unless a re-analysis reproduces the
stored result): per unit and gene ``log2(gene) - mean(log2(control genes))`` on the engine's
unit-level matrix (the mean ``log2 N0`` of a unit's wells that have a quantity), and per well
the well's own ``log2 N0`` minus the unit's control-gene mean, so a unit's replicate wells
average to its value. They are taken at the study's planned analysis, the one its stored result
(the fold change, CI and p-value on the Gene page) is computed from; the group means' difference
is checked against that result before anything is shown.
"""

from __future__ import annotations

import dataclasses
import math
import threading
from collections import OrderedDict
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
from scipy import stats

from qpilot.qpcr.export import WELL_COLUMN, ExportError, ExportInputs, study_inputs
from qpilot.qpcr.quant import EXCLUDED
from qpilot.web.contract_units import UnitGroup, UnitGroups, UnitPoint, UnitValues, UnitWell

if TYPE_CHECKING:
    from qpilot.core.store import StudyStore

LATE_CQ = 35.0  # the audit's late line (de Ronde et al. 2017: a critical Cq of 35)
FLAG_NOTES = ("PCR efficiency outlier", "indiv PCR eff is", "Ncopy < 10")  # as the audit flags
TOLERANCE = 1e-9  # the group means' difference against the stored log2 fold change
MAX_CACHED = 8


class UnitsUnavailable(RuntimeError):
    """The study's per-unit values cannot be rebuilt (the message says why, in plain words)."""


@dataclasses.dataclass(frozen=True)
class _Planned:
    inputs: ExportInputs  # at the planned analysis
    at_plan: bool


_cache: OrderedDict[tuple[str, str], _Planned] = OrderedDict()
_lock = threading.Lock()


def _fold_words(log2: float) -> str:
    fold = 2.0**log2
    return f"{fold:.2f}× higher" if fold >= 1 else f"{1 / fold:.2f}× lower"


def _planned(store: StudyStore, study_id: str) -> _Planned:
    """The study's inputs at its planned analysis (cached per study and decision chain head)."""
    key = (study_id, store.chain_head(study_id))
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    try:
        inputs = study_inputs(store, study_id, read_only=True)
    except ExportError as err:
        raise UnitsUnavailable(str(err)) from err
    planned = (
        _Planned(inputs, True) if inputs.at_primary else _Planned(_at_plan(store, inputs), False)
    )
    with _lock:
        _cache[key] = planned
        while len(_cache) > MAX_CACHED:
            _cache.popitem(last=False)
    return planned


def _at_plan(store: StudyStore, inputs: ExportInputs) -> ExportInputs:
    """``inputs`` moved to the planned options (the Decision Cards chose others)."""
    from qpilot.qpcr.study import StudySettings, build_model

    design = store.design(inputs.study_id)
    settings = StudySettings.from_design(design) if design is not None else StudySettings()
    model = build_model(inputs.curves, settings)
    primary = model.space.primary
    data = model.inputs.primary_table
    units = model.inputs.units or {}
    if model.labels is not None:
        order = tuple(model.labels)
    else:
        order = (f"{settings.marker_label}-high", "rest")
    samples = sorted(set(data.loc[data["sample_type"] == "unkn", "sample"]))
    groups = {
        **{s: order[0] for s in samples if units.get(s, s) in model.high},
        **{s: order[1] for s in samples if units.get(s, s) in model.rest},
    }
    return dataclasses.replace(
        inputs,
        data=data,
        refs=tuple(primary["refs"]),
        undetermined=primary["undetermined"],
        groups=groups,
        group_order=order,
        at_primary=True,
    )


def unit_values(store: StudyStore, study_id: str, gene: str) -> UnitValues:
    """One compared gene's biological units at the planned analysis.

    Raises:
        KeyError: The study does not compare ``gene``.
        UnitsUnavailable: The input file is missing or changed, or the values do not reproduce
            the stored result.
    """
    planned = _planned(store, study_id)
    inputs = planned.inputs
    result = inputs.result
    if gene not in inputs.genes or result is None or gene not in result.contrasts:
        raise KeyError(gene)
    contrast = result.contrasts[gene]
    try:
        column = inputs.table("column", [gene])
        nested = inputs.table("nested", [gene], wells=True)
    except ExportError as err:
        raise UnitsUnavailable(str(err)) from err
    first, second = inputs.group_order
    unit_value = column.set_index("biological_unit")["log2_rq"].astype(float)
    group_of = column.set_index("biological_unit")["group"]
    base = float(unit_value[group_of == second].mean()) if (group_of == second).any() else 0.0
    if not math.isfinite(base):
        base = 0.0
    diff = float(unit_value[group_of == first].mean() - unit_value[group_of == second].mean())
    if math.isfinite(contrast.log2fc) and not abs(diff - contrast.log2fc) <= TOLERANCE:
        raise UnitsUnavailable(
            "the per-unit values do not give the stored fold change; nothing is shown rather "
            "than other numbers"
        )
    wells_of = _wells(inputs, gene, nested, base)
    samples_of = _samples_of(inputs)
    points = []
    for unit, value in unit_value.items():
        unit = str(unit)
        wells = wells_of.get(unit, [])
        used = [w for w in wells if w.state == "used"]
        cqs = [w.cq_value for w in used if w.cq_value is not None]
        points.append(
            UnitPoint(
                unit=unit,
                group="high" if group_of[unit] == first else "rest",
                samples=samples_of.get(unit, [unit]),
                x=float(value) - base,
                value=_fold_words(float(value) - base),
                capped=bool(wells) and not used,
                n_wells=len(used),
                cq_range=round(max(cqs) - min(cqs), 2) if len(cqs) > 1 else None,
                wells=wells,
            )
        )
    groups = UnitGroups(
        high=_group(first, unit_value, group_of, base, inputs),
        rest=_group(second, unit_value, group_of, base, inputs),
    )
    most = max((p.n_wells for p in points), default=0)
    ci = None
    if all(math.isfinite(v) and v > 0 for v in contrast.ci):
        ci = (math.log2(contrast.ci[0]), math.log2(contrast.ci[1]))
    rule = inputs.rule
    return UnitValues(
        study_id=study_id,
        gene=gene,
        points=points,
        groups=groups,
        fold=_fold_words(contrast.log2fc) if math.isfinite(contrast.log2fc) else "no fold change",
        fold_log2=contrast.log2fc if math.isfinite(contrast.log2fc) else None,
        fold_ci=ci,
        fold_ci_text=f"{2 ** ci[0]:.2f}× to {2 ** ci[1]:.2f}×" if ci else None,
        p=contrast.p if math.isfinite(contrast.p) else None,
        refs=list(inputs.refs),
        undetermined=inputs.undetermined,
        replicates=most > 1,
        most_wells=most,
        late_cut=f"{LATE_CQ:g}",
        at_plan=planned.at_plan,
        how=_how(gene, inputs, second, points, most, planned.at_plan),
        line_log2=rule.min_log2fc,
        line=f"{2**rule.min_log2fc:g}×",
    )


def _samples_of(inputs: ExportInputs) -> dict[str, list[str]]:
    units = inputs.units or {}
    out: dict[str, list[str]] = {}
    for sample in sorted(inputs.groups):
        out.setdefault(units.get(sample, sample), []).append(sample)
    return out


def _wells(
    inputs: ExportInputs, gene: str, nested: pd.DataFrame, base: float
) -> dict[str, list[UnitWell]]:
    """Every study well of ``gene`` per unit: used (with its value), without one, or excluded."""
    data = inputs.data
    if not {"run_id", "well", "cq", "n0"} <= set(data.columns):
        return {}
    units = inputs.units or {}
    rows = data[(data["sample_type"] == "unkn") & (data["target"] == gene)]
    rows = rows[rows["sample"].isin(list(inputs.groups))]
    value_of: Mapping[str, float] = {
        str(k): float(v) for k, v in zip(nested[WELL_COLUMN], nested["log2_rq"], strict=True) if k
    }
    excluded = (
        rows[EXCLUDED].astype(bool).to_numpy()
        if EXCLUDED in rows.columns
        else np.zeros(len(rows), bool)
    )
    out: dict[str, list[UnitWell]] = {}
    ordered = rows.assign(left_out=excluded).sort_values(
        ["sample", "run_id", "well"], kind="mergesort"
    )
    for row in ordered.itertuples(index=False):
        key = f"{row.run_id}/{row.well}"
        cq = float(row.cq) if pd.notna(row.cq) else None
        x = value_of.get(key)
        state = "excluded" if row.left_out else ("used" if x is not None else "no_value")
        note = str(getattr(row, "note", "") or "")
        out.setdefault(units.get(row.sample, row.sample), []).append(
            UnitWell(
                plate=str(row.run_id),
                well=str(row.well),
                sample=str(row.sample),
                cq=f"{cq:.1f}" if cq is not None else None,
                cq_value=cq,
                x=x - base if x is not None else None,
                value=_fold_words(x - base) if x is not None else None,
                state=state,
                late=cq is not None and cq > LATE_CQ,
                flagged=any(n in note for n in FLAG_NOTES),
            )
        )
    return out


def _group(
    name: str,
    values: pd.Series,
    group_of: pd.Series,
    base: float,
    inputs: ExportInputs,
) -> UnitGroup:
    mine = values[group_of == name].to_numpy(dtype=float) - base
    units = inputs.units or {}
    everyone = {units.get(s, s) for s, g in inputs.groups.items() if g == name}
    n = len(mine)
    mean = float(mine.mean()) if n else None
    ci = None
    if n >= 2:
        half = float(stats.t.ppf(0.975, n - 1) * mine.std(ddof=1) / math.sqrt(n))
        ci = (mean - half, mean + half)
    return UnitGroup(
        label=name,
        n=n,
        missing=max(0, len(everyone) - n),
        mean=mean,
        ci=ci,
        mean_text=_fold_words(mean) if mean is not None else None,
        ci_text=f"{_fold_words(ci[0])} to {_fold_words(ci[1])}" if ci else None,
    )


def _how(
    gene: str,
    inputs: ExportInputs,
    second: str,
    points: list[UnitPoint],
    most: int,
    at_plan: bool,
) -> list[str]:
    refs = ", ".join(inputs.refs)
    out = [
        f"Each large dot is one biological unit: the amount of {gene} divided by the mean of its "
        f"control genes ({refs}), from each well's curve and efficiency, shown relative to the "
        f"mean of {second}.",
    ]
    if most > 1:
        out.append(
            "The small dots on a unit's line are its replicate wells. The unit's value is the mean "
            "of their log2 amounts, so replicate wells are never counted as samples: the groups "
            "compare units."
        )
    else:
        out.append("Each unit has one well for this gene.")
    out.append(
        "The bar is each group's mean and the band its 95 % confidence interval, from the units' "
        "values (not the wells)."
    )
    blank = sum(w.state == "no_value" for p in points for w in p.wells)
    if blank or any(p.capped for p in points):
        rule = (
            "a unit whose wells all lack one is set to the lowest amount detected for the gene"
            if inputs.undetermined == "cap"
            else "a unit whose wells all lack one has no value"
        )
        out.append(f"Wells without a usable curve are listed but not used; {rule}, as planned.")
    if not at_plan:
        out.append(
            "These are the planned analysis's values, which the result above is computed from. "
            "Your Decision Card choices differ from the plan; the Prism export follows your "
            "choices."
        )
    return out


def clear_cache() -> None:
    """Forget every cached study (tests)."""
    with _lock:
        _cache.clear()


__all__: list[Any] = ["UnitsUnavailable", "clear_cache", "unit_values"]
