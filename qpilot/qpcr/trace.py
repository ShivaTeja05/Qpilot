"""Trace: from a result, a sample or a well to the well(s) to look at first.

A scientist looks at a result and something seems off: a gene that "should" move shows no call,
a sample sits far from its group, a sample is missing. Trace assumes the maths is right and asks
only *which input made the result this way*. It walks back along the numbers the engine already
computes and stops at a physical address:

    conclusion (one gene, primary analysis)
     └─ the two groups ─ units in no comparison, and the empty well behind each
     └─ one value per biological unit         influence: leave-one-out, exact (closed form)
         ├─ target well(s)                     curve note · NTC window
         └─ normaliser = mean of k reference values
             └─ reference well(s)              expected-from-the-other-references · pull = dev / k
                 └─ plate controls             NTC on the same plate and gene

Three ways in: :func:`trace_gene` (result-first, Excel's "trace precedents"),
:func:`trace_sample` (sample-first) and :func:`trace_well` (well-first, "trace dependents": every
conclusion a well feeds). Each place is scored twice: **unusualness** (study-relative robust z,
``(x - median) / (1.4826 MAD)``, flagged beyond 3.5 as Iglewicz & Hoaglin's modified z-score) and
**consequence** under each what-if (set the unit aside; read the well as the unit's other
references predict). Places are ranked *changes the call* > *moves the number by at least half
its 95 % confidence interval* > *changes nothing*, then by size of effect, then by z. Units that
move the result most but show nothing unusual are listed separately: the "do not exclude this one
for that" answer.

The fingerprints (checks): S1 one reference well disagrees with the unit's other references;
S2 every gene of the unit late together (input amount); S4 whole-unit efficiency low; S5 a
LinRegPCR curve note on the well; S6 a study well within 5 cycles of its plate's earliest
amplifying NTC of the same gene (MIQE 2.0, as gate's G-NTC-1); S7 the unit is in no comparison,
and the well that put it there; S9 technical replicates disagree. A single target well that is
far off, with one well per unit and gene, cannot be told apart from biology, and Trace says so
rather than pointing at it.

What-ifs never change a measured value: they are perturbations, labelled as such. In a study
whose groups come from a marker gene, reading a reference well as expected changes that unit's
marker value too, so the groups are re-derived from the changed data exactly as a re-analysis
would (and the result with the groups held fixed is reported next to it). Setting a unit aside
keeps everyone else's group.

Every number in a text field is a ``{{fact_id}}`` token (``f_trace_<g|s|w>_<root>_<key>``) with
the fact in the result, and sample, plate, well and gene names are string facts, so the text
passes :func:`qpilot.core.validator.validate` with no allowed names. Wording: "look here first
because", "consistent with"; never a diagnosis. Deterministic; no model, no network.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from qpilot.core.facts import slug
from qpilot.core.validator import render_tokens, validate
from qpilot.qpcr.design import marker_groups
from qpilot.qpcr.influence import CALL_NAMES, Comparison, Effect, WelchArrays, robust_z
from qpilot.qpcr.quant import EXCLUDED
from qpilot.qpcr.study import StudyModel
from qpilot.schemas import ContrastResult, Fact
from qpilot.schemas_trace import (
    CallChange,
    ConclusionNode,
    Consequence,
    Influential,
    LeftOut,
    Place,
    TraceCheck,
    TraceOption,
    TraceResult,
    TraceWell,
)

THRESHOLDS: dict[str, float] = {
    "robust_z": 3.5,  # Iglewicz & Hoaglin 1993: modified z-score beyond 3.5 = potential outlier
    "ntc_window_cycles": 5.0,  # MIQE 2.0 via gate's G-NTC-1: Cq_ntc - Cq_unkn < 5 is tainted
    "moves_number_cap_log2": 0.5,  # class 2: |d log2FC| >= min(CI half-width, 0.5 log2)
    "influential_top": 3,  # units listed in "influential, nothing unusual" besides call-changers
}
NTC_TYPES = ("ntc", "ntp")
CONSEQUENCE_ORDER: dict[str, int] = {"changes_call": 0, "moves_number": 1, "changes_nothing": 2}
NO_AMPLIFICATION = re.compile(r"^no amplification", re.I)
TIMES = "×"
FOLD_FMT = "{:.3g}"  # 1.98× must not read as 2× next to a 2-fold line

CHECK_NAMES = {
    "S1": "one reference well disagrees with the unit's other references",
    "S2": "every gene of the unit reads late together",
    "S4": "the whole unit amplifies less efficiently",
    "S5": "curve-quality note on the well",
    "S6": "study well close to an amplifying no-template control",
    "S7": "the unit is in no comparison",
    "S9": "technical replicates disagree",
}


class TraceError(ValueError):
    """The entry cannot be traced: unknown name, or not a result (with the reason in words)."""


# ---------- the context: everything the three entries share, computed once per study ----------


@dataclass(frozen=True)
class RefCheck:
    """S1 for every unit and primary reference (units x references arrays).

    ``dev`` is the reference value minus what the unit's other references predict (log2);
    ``z`` its robust z over the units with every reference measured; ``flagged`` the wells
    beyond the threshold (the worst well of a unit, then the others re-tested with that well
    left out of their expectation); ``expected`` the value a flagged well is read as, from
    the unit's unflagged references.
    """

    refs: tuple[str, ...]
    dev: np.ndarray
    z: np.ndarray
    flagged: np.ndarray
    expected: np.ndarray


@dataclass(frozen=True, eq=False)
class TraceContext:
    """One study, ready to trace (build with :func:`build_context`)."""

    model: StudyModel
    study_id: str | None
    units: list[str]
    items: list[str]
    refs: tuple[str, ...]
    marker: str | None
    labels: tuple[str, str]
    wells: pd.DataFrame
    comparison: Comparison
    base: dict[str, ContrastResult]
    loo: Effect
    ref: RefCheck
    input_shift: np.ndarray
    input_z: np.ndarray
    eff_shift: np.ndarray
    eff_z: np.ndarray
    in_a: np.ndarray
    in_b: np.ndarray
    replicates: bool

    @property
    def matrix(self) -> pd.DataFrame:
        """Units x genes log2(N0) of the primary analysis."""
        return self.model.matrix

    def unit_index(self, unit: str) -> int:
        """Row of ``unit`` in the matrix."""
        return self.units.index(unit)

    def group_of(self, i: int) -> str | None:
        """The group label of unit row ``i`` (None when in neither group)."""
        if self.in_a[i]:
            return self.labels[0]
        if self.in_b[i]:
            return self.labels[1]
        return None


def build_context(model: StudyModel, study_id: str | None = None) -> TraceContext:
    """Everything the three entries need, from a study's decision space (read-only)."""
    space = model.space
    matrix = model.matrix
    refs = tuple(space.primary["refs"])
    items = list(space.items)
    units = [str(u) for u in matrix.index]
    marker = space.design.marker if space.design is not None else None
    labels = model.labels or ((space.design.group_var if space.design else "group A"), "rest")
    in_a = matrix.index.isin(model.high)
    in_b = matrix.index.isin(model.rest)
    relative, valid = _relative(matrix, items, refs)
    comparison = Comparison(relative, valid, in_a, in_b, space.rule)
    base = space.evaluate(space.primary)
    wells = _wells(model, refs, items, marker)
    input_shift, input_z = _input_shift(matrix)
    eff_shift, eff_z = _eff_shift(wells, units)
    unknown = wells[wells["sample_type"] == "unkn"]
    replicates = bool(unknown.duplicated(["unit", "gene"]).any())
    return TraceContext(
        model=model,
        study_id=study_id,
        units=units,
        items=items,
        refs=refs,
        marker=marker,
        labels=(str(labels[0]), str(labels[1])),
        wells=wells,
        comparison=comparison,
        base=base,
        loo=comparison.leave_one_out(),
        ref=_ref_check(matrix, refs),
        input_shift=input_shift,
        input_z=input_z,
        eff_shift=eff_shift,
        eff_z=eff_z,
        in_a=in_a,
        in_b=in_b,
        replicates=replicates,
    )


def context_from_curves(curves: pd.DataFrame, settings: Any = None) -> TraceContext:
    """Build the study model from a per-well table and settings, then the context."""
    from qpilot.qpcr.study import build_model

    return build_context(build_model(curves, settings))


def context_for_study(store: Any, study_id: str) -> TraceContext:
    """Rebuild a stored study read-only (the simulator bridge's route) and its context."""
    from qpilot.integration.simulator import load_analysis

    analysis = load_analysis(store, study_id)
    return build_context(analysis.model, study_id)


def _relative(
    matrix: pd.DataFrame, items: Sequence[str], refs: Sequence[str]
) -> tuple[np.ndarray, np.ndarray]:
    """Relative values of the primary cell and where they enter (as ``QpcrSpace.evaluate``)."""
    values = matrix[list(items)].to_numpy(dtype=float)
    block = matrix[list(refs)]
    ref_mean = block.mean(axis=1).to_numpy(dtype=float)
    refs_ok = block.notna().all(axis=1).to_numpy()
    relative = values - ref_mean[:, None]
    return relative, refs_ok[:, None] & ~np.isnan(relative)


def _wells(
    model: StudyModel, refs: tuple[str, ...], items: list[str], marker: str | None
) -> pd.DataFrame:
    """The per-well table with each well's unit, role, plate context and NTC window."""
    table = model.inputs.primary_table
    units = model.inputs.units or {}
    out = pd.DataFrame(
        {
            "plate": table["run_id"].astype(str).to_numpy(),
            "well": table["well"].astype(str).to_numpy(),
            "sample": table["sample"].astype(str).to_numpy(),
            "sample_type": table["sample_type"].astype(str).to_numpy(),
            "gene": table["target"].astype(str).to_numpy(),
            "cq": table["cq"].to_numpy(dtype=float),
            "n0": table["n0"].to_numpy(dtype=float),
            "eff": table["eff_indiv"].to_numpy(dtype=float),
            "eff_target": table["eff_target"].to_numpy(dtype=float),
            "note": table["note"].fillna("").astype(str).to_numpy(),
            "excluded": (
                table[EXCLUDED].astype(bool).to_numpy()
                if EXCLUDED in table.columns
                else np.zeros(len(table), dtype=bool)
            ),
        }
    )
    out["unit"] = out["sample"].map(lambda s: units.get(s, s))
    candidates = set(model.settings.candidates)

    def role(sample_type: str, gene: str) -> str:
        if sample_type in NTC_TYPES:
            return "ntc"
        if sample_type == "std":
            return "standard"
        if sample_type != "unkn":
            return "other"
        if gene in refs:
            return "reference"
        if marker is not None and gene == marker:
            return "marker"
        if gene in candidates:
            return "candidate_reference"
        return "target"

    out["role"] = [role(t, g) for t, g in zip(out["sample_type"], out["gene"], strict=True)]
    study = out["sample_type"] == "unkn"
    key = ["plate", "gene"]
    median = out[study].groupby(key)["cq"].median().rename("plate_median_cq")
    out = out.join(median, on=key)
    ntc = out[out["sample_type"].isin(NTC_TYPES) & out["cq"].notna()]
    ntc = ntc.sort_values(["cq", "well"], kind="mergesort").groupby(key).head(1)
    ntc = ntc.set_index(key)[["cq", "well"]].rename(columns={"cq": "ntc_cq", "well": "ntc_well"})
    out = out.join(ntc, on=key)
    gap = out["ntc_cq"] - out["cq"]
    out["ntc_gap"] = gap.where(study)
    out["s6"] = study & (gap < THRESHOLDS["ntc_window_cycles"])
    out["contaminant_fraction"] = (out["eff_target"] ** (-gap)).where(out["s6"])
    std = out[(out["sample_type"] == "std") & out["cq"].notna()]
    low = std.groupby([*key, "sample"])["cq"].median().reset_index()
    low = low.sort_values([*key, "cq", "sample"], ascending=[True, True, False, True])
    low = low.groupby(key).head(1).set_index(key)  # the latest standard = the fewest copies
    low = low.rename(columns={"cq": "std_low_cq", "sample": "std_low_name"})
    out = out.join(low[["std_low_cq", "std_low_name"]], on=key)
    return out


def _input_shift(matrix: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """S2: per unit, the median over genes of log2(N0) minus the gene's median over units."""
    values = matrix.to_numpy(dtype=float)
    with np.errstate(invalid="ignore"):
        centred = values - np.nanmedian(values, axis=0, keepdims=True)
    shift = np.array([np.nanmedian(row) if np.isfinite(row).any() else np.nan for row in centred])
    return shift, robust_z(shift)


def _eff_shift(wells: pd.DataFrame, units: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """S4: per unit, the median of each well's efficiency minus its plate-and-gene median."""
    study = wells[(wells["sample_type"] == "unkn") & wells["eff"].notna()]
    centred = study["eff"] - study.groupby(["plate", "gene"])["eff"].transform("median")
    per_unit = centred.groupby(study["unit"]).median()
    shift = per_unit.reindex(units).to_numpy(dtype=float)
    return shift, robust_z(shift)


def _ref_check(matrix: pd.DataFrame, refs: tuple[str, ...]) -> RefCheck:
    """S1 with a second pass inside flagged units (see :class:`RefCheck`)."""
    values = matrix[list(refs)].to_numpy(dtype=float)
    n_units, k = values.shape
    nan = np.full((n_units, k), np.nan)
    if k < 3:  # with two references one cannot say which of them is off
        return RefCheck(refs, nan, nan, np.zeros((n_units, k), dtype=bool), nan)
    complete = ~np.isnan(values).any(axis=1)
    threshold = THRESHOLDS["robust_z"]
    cache: dict[tuple[int, tuple[int, ...]], tuple[float, float]] = {}

    def offset_scale(j: int, others: tuple[int, ...]) -> tuple[float, float]:
        """Median of (ref j - mean of ``others``) over complete units, and the robust SD."""
        if (j, others) not in cache:
            d = values[complete, j] - values[complete][:, list(others)].mean(axis=1)
            centre = float(np.median(d))
            cache[(j, others)] = (centre, float(1.4826 * np.median(np.abs(d - centre))))
        return cache[(j, others)]

    def deviation(i: int, j: int, others: tuple[int, ...]) -> tuple[float, float, float]:
        offset, scale = offset_scale(j, others)
        expected = float(values[i, list(others)].mean()) + offset
        dev = float(values[i, j]) - expected
        return dev, (dev / scale if scale > 0 else math.nan), expected

    dev, z, expected = nan.copy(), nan.copy(), nan.copy()
    flagged = np.zeros((n_units, k), dtype=bool)
    every = tuple(range(k))
    for i in np.flatnonzero(complete):
        for j in every:
            dev[i, j], z[i, j], expected[i, j] = deviation(i, j, every[:j] + every[j + 1 :])
        worst = int(np.nanargmax(np.abs(z[i]))) if np.isfinite(z[i]).any() else -1
        if worst < 0 or not abs(z[i, worst]) > threshold:
            continue
        flagged[i, worst] = True
        if k >= 4:  # re-test the others with the worst well left out of their expectation
            for j in every:
                if j == worst:
                    continue
                others = tuple(o for o in every if o not in (j, worst))
                dev[i, j], z[i, j], expected[i, j] = deviation(i, j, others)
                flagged[i, j] = abs(z[i, j]) > threshold
        for j in np.flatnonzero(flagged[i]):  # read each flagged well from the unflagged ones
            others = tuple(o for o in every if not flagged[i, o])
            if others:
                _, _, expected[i, j] = deviation(i, int(j), others)
    return RefCheck(refs=refs, dev=dev, z=z, flagged=flagged, expected=expected)


# ---------- what-ifs ----------


@dataclass(frozen=True)
class WhatIf:
    """A changed analysis: the comparison after, and how the groups moved (marker mode)."""

    after: WelchArrays
    fixed: WelchArrays | None
    left: tuple[str, ...]
    joined: tuple[str, ...]

    @property
    def regrouped(self) -> bool:
        """True when the groups had to be re-derived because a unit crossed the line."""
        return bool(self.left or self.joined)


def what_if_values(ctx: TraceContext, changes: dict[tuple[int, str], float]) -> WhatIf:
    """Re-evaluate every gene with some log2(N0) values replaced (``(unit row, gene) -> value``).

    In marker mode the groups are re-derived from the changed matrix, as a re-analysis would;
    ``fixed`` is then the same change with the groups held as they are (None when no unit
    crossed the line).
    """
    matrix = ctx.matrix.copy()
    for (i, gene), value in changes.items():
        matrix.iat[i, matrix.columns.get_loc(gene)] = value
    relative, valid = _relative(matrix, ctx.items, ctx.refs)
    fixed = ctx.comparison.evaluate(relative, valid, ctx.in_a, ctx.in_b)
    space = ctx.model.space
    if space.design is None:
        return WhatIf(fixed, None, (), ())
    high, rest = marker_groups(matrix, space.design)
    if high == ctx.model.high and rest == ctx.model.rest:
        return WhatIf(fixed, None, (), ())
    in_a, in_b = matrix.index.isin(high), matrix.index.isin(rest)
    after = ctx.comparison.evaluate(relative, valid, in_a, in_b)
    left = tuple(sorted(ctx.model.high - high))
    joined = tuple(sorted(high - ctx.model.high))
    return WhatIf(after, fixed, left, joined)


def set_aside(ctx: TraceContext, rows: Iterable[int], genes: Iterable[int] | None = None):
    """Several units set aside together (from ``genes`` columns, or from every gene)."""
    relative, valid = _relative(ctx.matrix, ctx.items, ctx.refs)
    cols = slice(None) if genes is None else list(genes)
    for i in rows:
        valid[i, cols] = False
    return ctx.comparison.evaluate(relative, valid, ctx.in_a, ctx.in_b)


def _changes(ctx: TraceContext, after: WelchArrays, cols: Iterable[int] | None = None):
    """Conclusions that differ from the primary analysis, in gene order."""
    base = ctx.comparison.base
    cols = range(len(ctx.items)) if cols is None else cols
    out = []
    for j in cols:
        if after.call[j] == base.call[j]:
            continue
        out.append(
            CallChange(
                gene=ctx.items[j],
                call_before=CALL_NAMES[int(base.call[j])],
                call_after=CALL_NAMES[int(after.call[j])],
                log2fc_before=float(base.diff[j]),
                log2fc_after=float(after.diff[j]),
                p_before=_finite(base.p[j]),
                p_after=_finite(after.p[j]),
            )
        )
    return out


def _finite(value: float) -> float | None:
    value = float(value)
    return value if math.isfinite(value) else None


# ---------- facts and words ----------


class _Facts:
    """Facts of one trace result; :meth:`tok` registers a value and returns its token."""

    def __init__(self, entry: str, root: str) -> None:
        self.prefix = f"f_trace_{entry[0]}_{slug(root)}"
        self.facts: dict[str, Fact] = {}

    def fid(self, key: str) -> str:
        return f"{self.prefix}_{key}"

    def tok(self, key: str, value: Any, fmt: str = "{}", unit: str = "", path: str = "") -> str:
        fid = self.fid(key)
        if isinstance(value, float | np.floating):
            value = float(value)
            if not math.isfinite(value):
                value, fmt, unit = "not available", "{}", ""
        elif isinstance(value, np.integer | bool):
            value = int(value)
        old = self.facts.get(fid)
        if old is not None:  # the same number reached twice keeps its first path
            if (old.value, old.fmt, old.unit) != (value, fmt, unit):
                raise ValueError(f"trace fact {fid} registered twice with different values")
            return "{{" + fid + "}}"
        self.facts[fid] = Fact(id=fid, value=value, fmt=fmt, unit=unit, path=path or f"trace.{key}")
        return "{{" + fid + "}}"

    def ids(self, start: int) -> list[str]:
        """Fact ids registered since ``start`` (in order)."""
        return list(self.facts)[start:]

    def plain(self, text: str) -> str:
        """Validate ``text`` (no naked number) and render it."""
        check = validate(text, self.facts)
        if not check.ok:
            raise ValueError(f"trace text failed the no-naked-numbers check: {check.error()}")
        return render_tokens(text, self.facts)


def _fold(log2: float) -> float:
    return float(2 ** abs(log2))


def _pct(log2: float) -> float:
    """A change in log2 fold change as a percentage change of the fold change (unsigned)."""
    return float(100 * (2 ** abs(log2) - 1))


def _verb(names: Sequence[str], one: str, many: str) -> str:
    return one if len(names) == 1 else many


def _call_word(call: str) -> str:
    return {"up": "up", "down": "down", "none": "no call"}[call]


def _well_model(row: pd.Series, facts: _Facts | None = None, key: str = "") -> TraceWell:
    """A :class:`TraceWell` from a row of the context's well table (facts optional)."""
    cq, n0, eff = (_finite(row[c]) for c in ("cq", "n0", "eff"))
    median = _finite(row["plate_median_cq"])
    ids: dict[str, str] = {}
    if facts is not None:
        for name, value, fmt in (
            ("plate", row["plate"], "{}"),
            ("well", row["well"], "{}"),
            ("sample", row["sample"], "{}"),
            ("gene", row["gene"], "{}"),
            ("cq", cq, "{:.1f}"),
            ("plate_median_cq", median, "{:.1f}"),
        ):
            if value is not None:
                facts.tok(f"{key}_{name}", value, fmt, path=f"trace.{key}.{name}")
                ids[name] = facts.fid(f"{key}_{name}")
        if row["note"]:
            facts.tok(f"{key}_note", row["note"], path=f"trace.{key}.note")
            ids["note"] = facts.fid(f"{key}_note")
    return TraceWell(
        plate=row["plate"],
        well=row["well"],
        sample=row["sample"],
        unit=str(row["unit"]),
        gene=row["gene"],
        role=row["role"],
        sample_type=row["sample_type"],
        cq=cq,
        n0=n0,
        eff=eff,
        note=row["note"],
        excluded=bool(row["excluded"]),
        plate_median_cq=median,
        facts=ids,
    )


def _unit_wells(ctx: TraceContext, unit: str, gene: str) -> pd.DataFrame:
    w = ctx.wells
    rows = w[(w["unit"] == unit) & (w["gene"] == gene) & (w["sample_type"] == "unkn")]
    return rows.sort_values(["plate", "well"], kind="mergesort")


def _consequence(changes_call: bool, d_log2fc: float, half_width: float) -> Consequence:
    """Changes the call > moves the number by min(CI half-width, 0.5 log2) > changes nothing."""
    if changes_call:
        return "changes_call"
    cap = THRESHOLDS["moves_number_cap_log2"]
    yardstick = min(half_width, cap) if math.isfinite(half_width) else cap
    if abs(d_log2fc) >= yardstick:
        return "moves_number"
    return "changes_nothing"


# ---------- result-first: one gene ----------


@dataclass
class _Candidate:
    """A place before ranking: what it is, its checks and its what-ifs for the traced gene."""

    kind: str
    i: int
    wells: pd.DataFrame
    checks: list[tuple[str, str, float | None, dict[str, Any]]]
    options: list[TraceOption]
    d_on_gene: float
    changes_gene: bool
    unit_shift: float | None
    z: float


def trace_gene(ctx: TraceContext, gene: str) -> TraceResult:
    """Result-first: the places to look at behind one gene's conclusion, ranked by consequence.

    Raises:
        TraceError: The gene is not in the study, is withheld, or is a reference/marker gene.
    """
    j = _item_index(ctx, gene)
    facts = _Facts("gene", gene)
    base = ctx.base[gene]
    half = float(ctx.comparison.base.half_width()[j])
    conclusion = _conclusion_node(ctx, gene, base, facts)
    used = ctx.comparison.used[:, j]
    candidates: list[_Candidate] = []
    candidates += _reference_candidates(ctx, j, used)
    candidates += _ntc_candidates(ctx, j, used)
    candidates += _target_candidates(ctx, j, used, half)
    candidates += _sample_candidates(ctx, j, used)
    ranked = sorted(
        candidates,
        key=lambda c: (
            CONSEQUENCE_ORDER[_consequence(c.changes_gene, c.d_on_gene, half)],
            -abs(c.d_on_gene),
            -abs(c.z) if math.isfinite(c.z) else 0.0,
            ctx.units[c.i],
            c.kind,
        ),
    )
    places = [
        _place(ctx, facts, rank, c, gene, base, half) for rank, c in enumerate(ranked, start=1)
    ]
    in_place = {c.i for c in candidates}
    for c in candidates:  # every unit with a well in a place is unusual, not "nothing unusual"
        in_place |= {ctx.unit_index(u) for u in c.wells["unit"] if u in ctx.units}
    influential, n_flips = _influential(ctx, j, used, in_place, facts)
    left_out = _left_out_for_gene(ctx, j, facts)
    checked = _checked_for_gene(ctx, j, used, candidates, facts)
    cannot = _cannot_show(ctx, facts)
    summary = _gene_summary(ctx, gene, base, places, n_flips, influential, left_out, facts)
    return TraceResult(
        entry="gene",
        root=gene,
        study_id=ctx.study_id,
        cell=_cell(ctx),
        groups=ctx.labels,
        rule=ctx.model.space.rule.describe(),
        thresholds=dict(THRESHOLDS),
        conclusion=conclusion,
        places=places,
        influential=influential,
        n_set_aside_flips=n_flips,
        left_out=left_out,
        checked=checked,
        cannot_show=cannot,
        summary=summary,
        summary_plain=facts.plain(summary),
        facts=facts.facts,
    )


def _item_index(ctx: TraceContext, gene: str) -> int:
    if gene in ctx.items:
        return ctx.items.index(gene)
    space = ctx.model.space
    if gene in space.withheld:
        raise TraceError(f"{gene} has no conclusion to trace: {space.withheld[gene]}")
    if gene in ctx.refs:
        raise TraceError(
            f"{gene} is a reference gene: it feeds every conclusion through the normaliser; "
            "trace a sample or one of its wells instead"
        )
    if ctx.marker is not None and gene == ctx.marker:
        raise TraceError(f"{gene} is the marker gene: it defines the groups, it is not a result")
    if gene in ctx.matrix.columns:
        raise TraceError(f"{gene} is a candidate control gene, not a result in this analysis")
    raise TraceError(f"unknown gene {gene!r}")


def _cell(ctx: TraceContext) -> dict[str, Any]:
    cell = dict(ctx.model.space.primary)
    cell["refs"] = list(cell["refs"])
    return cell


def _conclusion_node(
    ctx: TraceContext, gene: str, base: ContrastResult, facts: _Facts
) -> ConclusionNode:
    rule = ctx.model.space.rule
    margin = abs(base.log2fc) - rule.min_log2fc
    ids = {}
    for name, value, fmt, unit in (
        ("gene", gene, "{}", ""),
        ("call", _call_word(base.conclusion), "{}", ""),
        ("fc", base.fc, FOLD_FMT, TIMES),
        ("fold_down", 1 / base.fc if base.fc else math.nan, FOLD_FMT, TIMES),
        ("ci_lo", base.ci[0], FOLD_FMT, TIMES),
        ("ci_hi", base.ci[1], FOLD_FMT, TIMES),
        ("p", base.p, "{:.2g}", ""),
        ("n_a", base.n_hi, "{}", ""),
        ("n_b", base.n_lo, "{}", ""),
        ("group_a", ctx.labels[0], "{}", ""),
        ("group_b", ctx.labels[1], "{}", ""),
        ("rule_fold", 2**rule.min_log2fc, "{:g}", "-fold"),
        ("margin_fold", _fold(margin), "{:.3g}", TIMES),
    ):
        facts.tok(name, value, fmt, unit, path=f"trace.conclusion.{name}")
        ids[name] = facts.fid(name)
    return ConclusionNode(
        gene=gene,
        call=base.conclusion,
        log2fc=base.log2fc,
        fc=base.fc,
        ci=base.ci,
        p=base.p,
        n_a=base.n_hi,
        n_b=base.n_lo,
        margin_log2=margin,
        facts=ids,
    )


def _reference_candidates(ctx: TraceContext, j: int, used: np.ndarray) -> list[_Candidate]:
    """S1-flagged reference wells of units used for gene ``j``."""
    out = []
    k = len(ctx.refs)
    for i in np.flatnonzero(used & ctx.ref.flagged.any(axis=1)):
        for r in np.flatnonzero(ctx.ref.flagged[i]):
            ref = ctx.refs[r]
            expected = float(ctx.ref.expected[i, r])
            shift = (float(ctx.matrix.iat[i, ctx.matrix.columns.get_loc(ref)]) - expected) / k
            repaired = what_if_values(ctx, {(int(i), ref): expected})
            options = [
                _option_read(ctx, repaired, j, i),
                _option_set_aside(ctx, i, j),
            ]
            changes_gene = any(any(c.gene == ctx.items[j] for c in o.changes) for o in options)
            d = max((o.d_log2fc or 0.0 for o in options), key=abs)
            checks = [("S1", "fail", float(ctx.ref.z[i, r]), {"r": int(r), "shift": shift})]
            out.append(
                _Candidate(
                    kind="reference_well",
                    i=int(i),
                    wells=_unit_wells(ctx, ctx.units[i], ref),
                    checks=checks,
                    options=options,
                    d_on_gene=d,
                    changes_gene=changes_gene,
                    unit_shift=shift,
                    z=float(ctx.ref.z[i, r]),
                )
            )
    return out


def _option_read(ctx: TraceContext, what: WhatIf, j: int, i: int) -> TraceOption:
    after = what.after
    label = "read this well as the unit's other references predict"
    change = None
    if what.regrouped:
        parts = []
        if what.left:
            verb = _verb(what.left, "leaves", "leave")
            parts.append(f"{', '.join(what.left)} {verb} {ctx.labels[0]}")
        if what.joined:
            verb = _verb(what.joined, "joins", "join")
            parts.append(f"{', '.join(what.joined)} {verb} {ctx.labels[0]}")
        change = "; ".join(parts)
    return TraceOption(
        id="read_from_other_references",
        label=label,
        groups="re-derived" if what.regrouped else "fixed",
        group_change=change,
        d_log2fc=float(after.diff[j] - ctx.comparison.base.diff[j]),
        changes=_changes(ctx, after),
        fixed_groups_changes=_changes(ctx, what.fixed) if what.fixed is not None else None,
    )


def _option_set_aside(ctx: TraceContext, i: int, j: int) -> TraceOption:
    """The unit set aside from every comparison (exact: one unit, closed form)."""
    after = WelchArrays(
        diff=ctx.loo.after.diff[i],
        se=ctx.loo.after.se[i],
        p=ctx.loo.after.p[i],
        t_crit=ctx.loo.after.t_crit[i],
        call=np.where(ctx.loo.touched[i], ctx.loo.after.call[i], ctx.comparison.base.call),
    )
    return TraceOption(
        id="set_aside",
        label="set the unit aside",
        d_log2fc=float(ctx.loo.d_log2fc[i, j]),
        changes=_changes(ctx, after),
    )


def _ntc_candidates(ctx: TraceContext, j: int, used: np.ndarray) -> list[_Candidate]:
    """Amplifying NTCs on the plates of gene ``j`` and of its references (S6, one per plate)."""
    out = []
    w = ctx.wells
    genes = [ctx.items[j], *ctx.refs]
    tainted = w[w["s6"] & w["gene"].isin(genes) & (w["sample_type"] == "unkn")]
    rows_used = {ctx.units[i] for i in np.flatnonzero(used)}
    tainted = tainted[tainted["unit"].isin(rows_used)]
    for (plate, gene), group in tainted.groupby(["plate", "gene"], sort=True):
        rows = sorted({ctx.unit_index(u) for u in group["unit"]})
        target = gene == ctx.items[j]
        after = set_aside(ctx, rows, [j] if target else None)
        d = float(after.diff[j] - ctx.comparison.base.diff[j])
        option = TraceOption(
            id="set_aside",
            label="set aside the study wells within the NTC window",
            d_log2fc=d,
            changes=_changes(ctx, after, [j] if target else None),
        )
        ntc = w[
            (w["plate"] == plate) & (w["gene"] == gene) & (w["well"] == group["ntc_well"].iloc[0])
        ]
        wells = pd.concat([ntc, group.sort_values(["cq", "well"], ascending=[False, True])])
        gap = float(group["ntc_gap"].min())
        out.append(
            _Candidate(
                kind="plate_control",
                i=rows[0],
                wells=wells,
                checks=[("S6", "fail", None, {"n": len(rows), "gap": gap, "plate": plate})],
                options=[option],
                d_on_gene=d,
                changes_gene=bool(after.call[j] != ctx.comparison.base.call[j]),
                unit_shift=None,
                z=math.nan,
            )
        )
    return out


def _target_candidates(
    ctx: TraceContext, j: int, used: np.ndarray, half: float
) -> list[_Candidate]:
    """Target wells with a curve note that also matter for this result (S5)."""
    out = []
    gene = ctx.items[j]
    w = ctx.wells
    noted = w[(w["gene"] == gene) & (w["sample_type"] == "unkn") & (w["note"] != "") & ~w["s6"]]
    noted = noted[~noted["note"].str.match(NO_AMPLIFICATION)]
    for unit, group in noted.groupby("unit", sort=True):
        i = ctx.unit_index(unit) if unit in ctx.units else None
        if i is None or not used[i]:
            continue
        d = float(ctx.loo.d_log2fc[i, j])
        flips = bool(ctx.loo.changed[i, j])
        if _consequence(flips, d, half) == "changes_nothing":
            continue  # a note alone, on a well that changes nothing here, is not a place
        out.append(
            _Candidate(
                kind="target_well",
                i=i,
                wells=group,
                checks=[("S5", "warn", None, {})],
                options=[_option_set_aside(ctx, i, j)],
                d_on_gene=d,
                changes_gene=flips,
                unit_shift=None,
                z=math.nan,
            )
        )
    return out


def _sample_candidates(ctx: TraceContext, j: int, used: np.ndarray) -> list[_Candidate]:
    """Whole units with every gene late together (S2) or low efficiency everywhere (S4)."""
    out = []
    threshold = THRESHOLDS["robust_z"]
    for i in np.flatnonzero(used):
        checks = []
        if abs(ctx.input_z[i]) > threshold:
            checks.append(("S2", "fail", float(ctx.input_z[i]), {"shift": ctx.input_shift[i]}))
        if ctx.eff_z[i] < -threshold:
            checks.append(("S4", "fail", float(ctx.eff_z[i]), {"shift": ctx.eff_shift[i]}))
        if not checks:
            continue
        option = _option_set_aside(ctx, int(i), j)
        out.append(
            _Candidate(
                kind="sample",
                i=int(i),
                wells=ctx.wells.iloc[0:0],
                checks=checks,
                options=[option],
                d_on_gene=float(ctx.loo.d_log2fc[i, j]),
                changes_gene=bool(ctx.loo.changed[i, j]),
                unit_shift=None,
                z=max((abs(c[2]) for c in checks if c[2] is not None), default=math.nan),
            )
        )
    return out


def _place(
    ctx: TraceContext,
    facts: _Facts,
    rank: int,
    c: _Candidate,
    gene: str,
    base: ContrastResult,
    half: float,
) -> Place:
    start = len(facts.facts)
    key = f"p{rank}"
    unit = ctx.units[c.i]
    u = facts.tok(f"{key}_unit", unit, path=f"trace.places[{rank - 1}].unit")
    wells = [
        _well_model(row, facts, f"{key}_w{n}")
        for n, (_, row) in enumerate(c.wells.iterrows(), start=1)
    ]
    checks = [
        _check(ctx, facts, f"{key}_{cid.lower()}", cid, st, z, d, c) for cid, st, z, d in c.checks
    ]
    consequence = _consequence(c.changes_gene, c.d_on_gene, half)
    words = _why(ctx, facts, key, c, u, wells, checks, gene, consequence)
    path = [f"conclusion:{gene}", f"unit:{unit}"]
    if c.kind == "reference_well":
        path.append("normaliser")
    for well in wells[:1]:
        path += [f"well:{well.plate}:{well.well}", f"plate:{well.plate}"]
    return Place(
        rank=rank,
        kind=c.kind,
        unit=unit,
        group=ctx.group_of(c.i),
        path=path,
        wells=wells,
        checks=checks,
        consequence=consequence,
        unit_shift_log2=c.unit_shift,
        options=c.options,
        why=words,
        why_plain=facts.plain(words),
        facts=facts.ids(start),
    )


def _check(
    ctx: TraceContext,
    facts: _Facts,
    key: str,
    cid: str,
    status: str,
    z: float | None,
    data: dict[str, Any],
    c: _Candidate,
) -> TraceCheck:
    start = len(facts.facts)
    t = facts.tok
    zt = t(key + "_z", z, "{:+.1f}") if z is not None else ""
    if cid == "S1":
        ref = ctx.refs[data["r"]]
        dev = float(ctx.ref.dev[c.i, data["r"]])
        word = "less" if dev < 0 else "more"
        fold = t(key + "_fold", _fold(dev), FOLD_FMT, TIMES)
        detail = (
            f"{t(key + '_gene', ref)} reads {fold} {word} than the unit's other references "
            f"predict (robust z {zt})"
        )
    elif cid == "S2":
        shift = float(data["shift"])
        word = "lower" if shift < 0 else "higher"
        fold = t(key + "_fold", _fold(shift), FOLD_FMT, TIMES)
        detail = (
            f"every gene of the unit reads about {fold} {word} than the study's typical unit "
            f"(robust z {zt}); consistent with the amount of RNA or cDNA put in"
        )
    elif cid == "S4":
        detail = (
            "the unit's wells amplify less efficiently than their plates' other wells "
            f"(median shift {t(key + '_shift', float(data['shift']), '{:+.3f}')}, "
            f"robust z {zt}); consistent with an inhibitor "
            "carried over from extraction"
        )
    elif cid == "S5":
        notes = sorted({n for n in c.wells["note"] if n})
        detail = "LinRegPCR noted: " + "; ".join(
            facts.tok(f"{key}_note{n}", note) for n, note in enumerate(notes, start=1)
        )
    elif cid == "S6":
        n, plate = t(key + "_n", data["n"]), t(key + "_plate", data["plate"])
        gap = t(key + "_gap", data["gap"], "{:.1f}")
        window = t("ntc_window", THRESHOLDS["ntc_window_cycles"], "{:g}")
        detail = (
            f"{n} study wells on plate {plate} come up less than {window} cycles before it "
            f"(closest {gap} cycles); MIQE counts a sample positive only when it precedes an "
            "amplifying negative control by at least that much"
        )
    else:
        detail = ""
    return TraceCheck(
        id=cid,
        name=CHECK_NAMES[cid],
        status=status,
        z=z,
        detail=detail,
        facts=facts.ids(start),
    )


def _why(
    ctx: TraceContext,
    facts: _Facts,
    key: str,
    c: _Candidate,
    u: str,
    wells: list[TraceWell],
    checks: list[TraceCheck],
    gene: str,
    consequence: str,
) -> str:
    """'Look here first because …' in token text."""
    t = facts.tok
    g = t("gene", gene)
    if c.kind == "reference_well":
        well = wells[0] if wells else None
        where = ""
        if well is not None:
            row = c.wells.iloc[0]
            where = (
                f" at plate {facts.tok(key + '_w1_plate', well.plate)} well "
                f"{facts.tok(key + '_w1_well', well.well)}"
            )
            if well.cq is not None:
                where += f" read Cq {facts.tok(key + '_w1_cq', well.cq, '{:.1f}')}"
                if well.plate_median_cq is not None:
                    median = t(key + "_w1_plate_median_cq", well.plate_median_cq, "{:.1f}")
                    where += f" (plate median {median}"
                    if isinstance(row["std_low_name"], str):
                        name = t(key + "_std_name", row["std_low_name"])
                        std_cq = t(key + "_std_cq", float(row["std_low_cq"]), "{:.1f}")
                        where += f"; lowest standard {name} reads {std_cq}"
                    where += ")"
            else:
                where += " gave no Cq"
        shift = c.unit_shift or 0.0
        direction = "too high" if shift < 0 else "too low"
        lead = _lead(consequence)
        text = (
            f"{lead} this reference well{where} makes every value of unit {u} "
            f"{facts.tok(key + '_unit_fold', _fold(shift), FOLD_FMT, TIMES)} {direction}"
        )
        read = c.options[0]
        if read.group_change:
            text += (
                f"; read as the unit's other references predict, the groups change "
                f"({facts.tok(key + '_group_change', read.group_change)})"
            )
        text += _option_effect(facts, key, read, gene, g, "read as expected")
        text += _option_effect(facts, key, c.options[1], gene, g, "set aside")
        return text + "."
    lead = _lead(consequence)
    if c.kind == "plate_control":
        ntc = wells[0]
        return (
            f"{lead} the no-template control at plate {t(key + '_w1_plate', ntc.plate)} "
            f"well {t(key + '_w1_well', ntc.well)} amplified "
            f"(Cq {t(key + '_w1_cq', ntc.cq, '{:.1f}')}): {checks[0].detail}"
            + _option_effect(facts, key, c.options[0], gene, g, "set aside")
            + "."
        )
    if c.kind == "target_well":
        well = wells[0]
        return (
            f"{lead} the {g} well of unit {u} at plate "
            f"{facts.tok(key + '_w1_plate', well.plate)} well "
            f"{facts.tok(key + '_w1_well', well.well)} carries a curve note "
            f"({checks[0].detail})"
            + _option_effect(facts, key, c.options[0], gene, g, "set aside")
            + "."
        )
    return (
        f"{lead} unit {u} as a whole stands out: "
        + "; ".join(check.detail for check in checks)
        + _option_effect(facts, key, c.options[0], gene, g, "set aside")
        + "."
    )


def _lead(consequence: str) -> str:
    if consequence == "changes_nothing":
        return "Unusual, but it changes nothing for this result:"
    return "Look here first because"


def _option_effect(
    facts: _Facts, key: str, option: TraceOption, gene: str, g: str, verb: str
) -> str:
    oid = f"{key}_{option.id}"
    mine = [ch for ch in option.changes if ch.gene == gene]
    if mine:
        ch = mine[0]
        text = (
            f"; {verb}, {g} goes from {facts.tok(oid + '_before', _call_word(ch.call_before))} "
            f"to {facts.tok(oid + '_after', _call_word(ch.call_after))} "
            f"({facts.tok(oid + '_fc_before', 2**ch.log2fc_before, FOLD_FMT, TIMES)} to "
            f"{facts.tok(oid + '_fc_after', 2**ch.log2fc_after, FOLD_FMT, TIMES)})"
        )
    else:
        d = option.d_log2fc or 0.0
        text = (
            f"; {verb}, {g} keeps its call (fold change moves by "
            f"{facts.tok(oid + '_dpct', _pct(d), '{:.1f}', ' %')})"
        )
    others = [ch.gene for ch in option.changes if ch.gene != gene]
    if others:
        text += (
            f" and {facts.tok(oid + '_n_other', len(others))} other calls change "
            f"({facts.tok(oid + '_other', ', '.join(others))})"
        )
    return text


def _influential(
    ctx: TraceContext, j: int, used: np.ndarray, in_place: set[int], facts: _Facts
) -> tuple[list[Influential], int]:
    """Units that move the result most and show nothing unusual, and how many flip the call."""
    d = ctx.loo.d_log2fc[:, j]
    flips = ctx.loo.changed[:, j] & used
    calm = used.copy()
    calm[list(in_place)] = False
    order = sorted(np.flatnonzero(calm), key=lambda i: (-abs(d[i]), ctx.units[i]))
    n = int(used.sum())
    se = float(ctx.comparison.base.se[j])
    cutoff = 2 / math.sqrt(n) if n else math.inf  # size-adjusted DFBETAS (Belsley et al. 1980)
    big = [i for i in order[: int(THRESHOLDS["influential_top"])] if abs(d[i]) / se > cutoff]
    chosen = [i for i in order if flips[i]] + big
    chosen = sorted(set(chosen), key=lambda i: (-abs(d[i]), ctx.units[i]))
    rel = ctx.comparison.x[:, j]
    out = []
    for n, i in enumerate(chosen, start=1):
        start = len(facts.facts)
        group_mask = ctx.comparison.a[:, j] if ctx.in_a[i] else ctx.comparison.b[:, j]
        values = rel[group_mask]
        z = float(robust_z(values)[np.flatnonzero(group_mask).tolist().index(i)])
        key = f"i{n}"
        facts.tok(f"{key}_unit", ctx.units[i])
        facts.tok(f"{key}_dfold", _fold(float(d[i])), "{:.3g}", TIMES)
        note = "nothing unusual in its wells"
        target = _unit_wells(ctx, ctx.units[i], ctx.items[j])
        noted = sorted({x for x in target["note"] if x})
        if noted:
            note = "a curve note on its well (" + "; ".join(noted) + "); nothing else unusual"
        if math.isfinite(z) and abs(z) > THRESHOLDS["robust_z"] and not ctx.replicates:
            note = (
                "its value is far from its group; with one well per unit and gene this "
                "cannot be told apart from biology"
            )
        out.append(
            Influential(
                unit=ctx.units[i],
                group=ctx.group_of(i),
                d_log2fc=float(d[i]),
                changes_call=bool(flips[i]),
                call_after=CALL_NAMES[int(ctx.loo.after.call[i, j])],
                note=note,
                facts=facts.ids(start),
            )
        )
    facts.tok("n_set_aside_flips", int(flips.sum()))
    return out, int(flips.sum())


def _left_out_for_gene(ctx: TraceContext, j: int, facts: _Facts) -> list[LeftOut]:
    """Units in no comparison at all (S7), then units in the groups with no value for the gene."""
    out = _left_out_units(ctx, facts)
    gene = ctx.items[j]
    grouped = ctx.in_a | ctx.in_b
    refs_ok = ctx.matrix[list(ctx.refs)].notna().all(axis=1).to_numpy()
    empty = grouped & refs_ok & np.isnan(ctx.matrix[gene].to_numpy(dtype=float))
    for i in np.flatnonzero(empty):
        unit = ctx.units[i]
        rows = _unit_wells(ctx, unit, gene)
        out.append(
            LeftOut(
                unit=unit,
                reason="excluded" if rows["excluded"].all() and len(rows) else "empty_target",
                wells=[_well_model(r) for _, r in rows.iterrows()],
                detail="",
            )
        )
    facts.tok("n_empty_target", int(empty.sum()))
    return out


def _left_out_units(ctx: TraceContext, facts: _Facts) -> list[LeftOut]:
    """Every unit of the matrix that enters no comparison, why, and the well(s) behind it."""
    out = []
    used_any = ctx.comparison.used.any(axis=1)
    matrix = ctx.matrix
    for i in np.flatnonzero(~used_any):
        unit = ctx.units[i]
        empty_refs = [r for r in ctx.refs if math.isnan(matrix.iat[i, matrix.columns.get_loc(r)])]
        marker_empty = ctx.marker is not None and math.isnan(
            matrix.iat[i, matrix.columns.get_loc(ctx.marker)]
        )
        genes = empty_refs + ([ctx.marker] if marker_empty else [])
        rows = pd.concat([_unit_wells(ctx, unit, g) for g in genes]) if genes else None
        if empty_refs:
            reason = "empty_reference"
            if rows is not None and rows["excluded"].all():
                reason = "excluded"
        elif marker_empty:
            reason = "empty_marker"
        else:
            reason = "not_in_groups"
        bring = None
        if reason == "empty_reference" and len(empty_refs) == 1 and not marker_empty:
            bring = _bring_back(ctx, i, empty_refs[0])
        out.append(
            LeftOut(
                unit=unit,
                reason=reason,
                wells=[_well_model(r) for _, r in rows.iterrows()] if rows is not None else [],
                bring_back=bring,
            )
        )
    facts.tok("n_left_out", len(out))
    facts.tok("n_units", len(ctx.units))
    return out


def _bring_back(ctx: TraceContext, i: int, ref: str) -> TraceOption | None:
    """The unit with its one empty reference read from its other references (what-if)."""
    values = ctx.matrix[list(ctx.refs)].to_numpy(dtype=float)
    complete = ~np.isnan(values).any(axis=1)
    r = ctx.refs.index(ref)
    others = [o for o in range(len(ctx.refs)) if o != r]
    offset = float(np.median(values[complete, r] - values[complete][:, others].mean(axis=1)))
    expected = float(values[i, others].mean()) + offset
    what = what_if_values(ctx, {(i, ref): expected})
    joined = what.joined
    unit = ctx.units[i]
    if ctx.model.space.design is not None:
        group = ctx.labels[0] if unit in joined else ctx.labels[1]
    else:
        group = ctx.group_of(i) or "neither group"
    return TraceOption(
        id="bring_back",
        label=f"read the empty {ref} well from the unit's other references (joins {group})",
        groups="re-derived" if ctx.model.space.design is not None else "fixed",
        group_change=None,
        d_log2fc=None,
        changes=_changes(ctx, what.after),
    )


def _checked_for_gene(
    ctx: TraceContext, j: int, used: np.ndarray, candidates: list[_Candidate], facts: _Facts
) -> list[str]:
    """What was checked and found nothing, in token text."""
    out = []
    kinds = {c.kind for c in candidates}
    found = {cid for c in candidates for cid, *_ in c.checks}
    g = facts.tok("gene", ctx.items[j])
    if "S6" not in found:
        out.append(
            f"No-template controls on the plates of {g} and of its references: "
            "no study well used here sits within the NTC window."
        )
    if "S1" not in found and len(ctx.refs) >= 3:
        out.append("Reference wells of the units used here agree with each other.")
    if "S4" not in found:
        out.append("Whole-unit efficiency: no unit used here amplifies unusually poorly.")
    if "S2" not in found:
        out.append("Input amount: no unit used here reads late on every gene together.")
    if not ctx.replicates:
        out.append("Technical replicates: not applicable, one well per unit and gene.")
    del kinds, used
    return out


def _cannot_show(ctx: TraceContext, facts: _Facts) -> list[str]:
    out = [
        "A single target well that is off cannot be told apart from biology without "
        "technical replicates.",
        "A fault shared by every unit of one group looks like biology (a design question).",
        "A wrong sample in the tube, RNA integrity, RT replicates and no-RT controls leave no "
        "footprint in these data unless they are annotated.",
    ]
    if _position_confounded(ctx):
        out.append(
            "Each sample sits at the same well position on every plate, so a position effect "
            "cannot be told apart from the sample."
        )
    del facts
    return out


def _position_confounded(ctx: TraceContext) -> bool:
    study = ctx.wells[ctx.wells["sample_type"] == "unkn"]
    if study["plate"].nunique() < 2:
        return False
    return bool((study.groupby("sample")["well"].nunique() == 1).all())


def _gene_summary(
    ctx: TraceContext,
    gene: str,
    base: ContrastResult,
    places: list[Place],
    n_flips: int,
    influential: list[Influential],
    left_out: list[LeftOut],
    facts: _Facts,
) -> str:
    t = facts.tok
    g, call = t("gene", gene), t("call", _call_word(base.conclusion))
    rule_fold = t("rule_fold", 2**ctx.model.space.rule.min_log2fc, "{:g}", "-fold")
    if base.log2fc < 0:
        size = f"{t('fold_down', 1 / base.fc, FOLD_FMT, TIMES)} lower"
    else:
        size = f"{t('fc', base.fc, FOLD_FMT, TIMES)} higher"
    text = (
        f"{g}: {call}, {size} in {t('group_a', ctx.labels[0])} than {t('group_b', ctx.labels[1])} "
        f"(p {t('p', base.p, '{:.2g}')}; rule: at least {rule_fold} and significant)."
    )
    if n_flips:
        text += (
            f" {t('n_set_aside_flips', n_flips)} units each change the call when set aside alone: "
            "the result sits close to its line."
        )
    else:
        text += " No single unit changes the call when set aside."
    unusual = [p for p in places if p.consequence != "changes_nothing"]
    if places:
        top = places[0]
        text += f" Look first at unit {t('p1_unit', top.unit)}"
        if top.wells:
            text += (
                f", plate {t('p1_w1_plate', top.wells[0].plate)} well "
                f"{t('p1_w1_well', top.wells[0].well)}"
            )
        text += "."
        rest = len(places) - 1
        if rest:
            text += f" {t('n_more_places', rest)} more places are listed"
            text += (
                f", {t('n_places_matter', len(unusual))} of them matter here." if unusual else "."
            )
    else:
        text += " Nothing to look at: the result is what the wells say."
    calm = [i for i in influential if i.note == "nothing unusual in its wells"]
    if calm:
        n = influential.index(calm[0]) + 1
        text += (
            f" Most influential with nothing unusual: unit {t(f'i{n}_unit', calm[0].unit)}"
            " (keep it; its value is what its wells say)."
        )
    if left_out:
        text += (
            f" {t('n_left_out', len([lo for lo in left_out if lo.reason != 'empty_target']))} of "
            f"{t('n_units', len(ctx.units))} units are in no comparison (see why)."
        )
    return text
