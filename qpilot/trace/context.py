"""One study, ready to trace: the analysis in use, every unit's value and every well behind it.

:func:`build_context` takes the engine's model of a stored study (:class:`StudyModel`, rebuilt
from the cached curve analysis) and the analysis in use (a cell of the decision space: control
genes, cut-off, empty-well rule, amplification rule; the planned one by default). It computes,
once per study and analysis:

* each unit's relative value for every gene (log2 target minus the mean of the control genes,
  exactly as :meth:`qpilot.qpcr.space.QpcrSpace.evaluate`, and checked against it);
* the comparison and every unit set aside once (closed form, :mod:`qpilot.trace.welch`);
* the per-well table with each well's unit, role, plate context and flags, all study-relative
  robust z-scores (``(x - median) / (1.4826 MAD)``, flagged beyond 3.5, Iglewicz & Hoaglin's
  modified z-score): a late Cq or an odd efficiency against the same plate and gene, a reference
  well that disagrees with the unit's other control genes (S1), a well within five cycles of an
  amplifying no-template control on its plate (S6, MIQE 2.0), LinRegPCR's own note (S5);
* per unit: every gene late together (S2, input amount) and low efficiency on every plate
  (S4, consistent with an inhibitor).

Read-only: nothing here changes a stored value. Deterministic; no model, no network.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any

import numpy as np
import pandas as pd

from qpilot.qpcr.contrast import ConclusionRule
from qpilot.qpcr.design import GroupSpec, marker_groups
from qpilot.qpcr.quant import EXCLUDED
from qpilot.qpcr.study import StudyModel
from qpilot.trace.welch import CALL_NAMES, Comparison, Effect, Family, WelchArrays, robust_z

THRESHOLDS: dict[str, float] = {
    "robust_z": 3.5,  # Iglewicz & Hoaglin 1993: modified z-score beyond 3.5 = potential outlier
    "ntc_window_cycles": 5.0,  # MIQE 2.0 via gate's G-NTC-1: Cq_ntc - Cq_sample < 5 is tainted
    "moves_number_cap_log2": 0.5,  # "moves the number": |d log2FC| >= min(CI half-width, 0.5)
    "flip_search_limit": 20,  # the greedy search sets aside at most this many units
}
NTC_TYPES = ("ntc", "ntp")
TOLERANCE = 1e-9


class TraceError(ValueError):
    """The entry cannot be traced: unknown name, or not a result (the message says why)."""


@dataclass(frozen=True)
class RefCheck:
    """S1 for every unit and control gene of the analysis (units x control genes arrays).

    ``dev`` is the control gene's value minus what the unit's other control genes predict
    (log2, with each gene's usual offset to the others); ``z`` its robust z over the units with
    every control gene measured; ``flagged`` the wells beyond the threshold (the worst well of a
    unit, then the others re-tested with that well left out of their expectation); ``expected``
    the value a flagged well would have, from the unit's unflagged control genes.
    """

    refs: tuple[str, ...]
    dev: np.ndarray
    z: np.ndarray
    flagged: np.ndarray
    expected: np.ndarray

    @property
    def pull(self) -> np.ndarray:
        """How much each well moves every relative value of its unit (log2; + = up)."""
        k = len(self.refs)
        return -self.dev / k if k else self.dev


@dataclass(frozen=True, eq=False)
class TraceContext:
    """One study and one analysis of it, ready to trace (build with :func:`build_context`)."""

    model: StudyModel
    study_id: str | None
    cell: dict[str, Any]
    planned: bool
    labels: tuple[str, str]
    units: list[str]
    items: list[str]
    refs: tuple[str, ...]
    marker: str | None
    matrix: pd.DataFrame  # units x genes log2(N0) under the analysis' amplification rule
    values: np.ndarray  # units x items after the empty-well rule
    relative: np.ndarray
    valid: np.ndarray
    in_a: np.ndarray
    in_b: np.ndarray
    comparison: Comparison
    loo: Effect
    wells: pd.DataFrame
    ref: RefCheck
    input_shift: np.ndarray
    input_z: np.ndarray
    eff_shift: np.ndarray
    eff_z: np.ndarray
    replicates: bool
    cache: dict[Any, Any] = field(default_factory=dict, repr=False)
    #: A study with several comparisons: the traced one (its id and words) and the correction
    #: its call uses ("none" without one; "holm", "dunnett" or "tukey").
    comparison_id: str | None = None
    comparison_label: str | None = None
    correction: str = "none"

    @cached_property
    def q(self) -> np.ndarray:
        """Each gene's Benjamini-Hochberg q-value over the compared genes (this comparison)."""
        from qpilot.qpcr.contrast import bh

        return bh(np.asarray(self.base.p, dtype=float))

    @property
    def base(self) -> WelchArrays:
        """Every gene's comparison in the analysis in use."""
        return self.comparison.base

    @property
    def rule(self) -> ConclusionRule:
        """The conclusion rule."""
        return self.model.space.rule

    def unit_index(self, unit: str) -> int:
        """Row of ``unit`` in the matrix (``TraceError`` when it is not a unit of the study)."""
        try:
            return self.units.index(unit)
        except ValueError as err:
            raise TraceError(f"There is no sample {unit!r} in this study.") from err

    def gene_index(self, gene: str) -> int:
        """Column of a compared gene (``TraceError`` saying why another name is not one)."""
        if gene in self.items:
            return self.items.index(gene)
        space = self.model.space
        if gene in space.withheld:
            raise TraceError(f"{gene} has no conclusion to trace: {space.withheld[gene]}.")
        if gene in self.refs:
            raise TraceError(
                f"{gene} is a control gene: it feeds every result through the normaliser. "
                "Trace a compared gene; its control-gene section shows what each one does."
            )
        if self.marker is not None and gene == self.marker:
            raise TraceError(f"{gene} is the marker gene: it defines the groups, not a result.")
        if gene in self.matrix.columns:
            raise TraceError(f"{gene} is a candidate control gene, not a result here.")
        raise TraceError(f"There is no compared gene {gene!r} in this study.")

    def group_of(self, i: int) -> str | None:
        """The group label of unit row ``i`` (None when in neither group)."""
        if self.in_a[i]:
            return self.labels[0]
        if self.in_b[i]:
            return self.labels[1]
        return None

    def side_of(self, i: int) -> str | None:
        """``"a"`` (the first group), ``"b"`` or None."""
        return "a" if self.in_a[i] else "b" if self.in_b[i] else None

    @cached_property
    def wells_by_unit(self) -> dict[str, pd.DataFrame]:
        """Each unit's study wells, by plate and well (computed once)."""
        study = self.wells[self.wells["sample_type"] == "unkn"]
        return {
            str(unit): rows.sort_values(["plate", "well"], kind="mergesort")
            for unit, rows in study.groupby("unit", sort=False)
        }

    @cached_property
    def unit_gene(self) -> dict[tuple[str, str], tuple[bool, bool, tuple[str, ...]]]:
        """Per (unit, gene): a study well near an NTC (S6), a curve note, and the plates."""
        study = self.wells[self.wells["sample_type"] == "unkn"]
        notes = study["note"].str.lower()
        noted = (notes.str.len() > 0) & ~notes.str.startswith("no amplification")
        out: dict[tuple[str, str], tuple[bool, bool, tuple[str, ...]]] = {}
        for unit, gene, s6, note, plate in zip(
            study["unit"], study["gene"], study["s6"], noted, study["plate"], strict=True
        ):
            key = (str(unit), str(gene))
            old = out.get(key, (False, False, ()))
            plates = old[2] if plate in old[2] else tuple(sorted((*old[2], str(plate))))
            out[key] = (old[0] or bool(s6), old[1] or bool(note), plates)
        return out

    @cached_property
    def records(self) -> list[dict[str, Any]]:
        """The well table as plain records (row ``n`` of :attr:`wells` is ``records[n]``)."""
        return self.wells.reset_index(drop=True).to_dict("records")

    @cached_property
    def record_index(self) -> dict[tuple[str, str], list[int]]:
        """(unit, gene) -> the records of its study wells, by plate and well."""
        study = self.wells.reset_index(drop=True)
        study = study[study["sample_type"] == "unkn"].sort_values(
            ["plate", "well"], kind="mergesort"
        )
        out: dict[tuple[str, str], list[int]] = {}
        for n, unit, gene in zip(study.index, study["unit"], study["gene"], strict=True):
            out.setdefault((str(unit), str(gene)), []).append(int(n))
        return out

    def unit_records(self, unit: str, genes: Sequence[str]) -> list[dict[str, Any]]:
        """The study-well records of one unit for these genes, gene by gene."""
        return [self.records[n] for g in genes for n in self.record_index.get((unit, g), ())]

    def unit_wells(self, unit: str, gene: str | None = None) -> pd.DataFrame:
        """The study wells of one unit (one gene, or every gene), by plate and well."""
        rows = self.wells_by_unit.get(unit)
        if rows is None:
            return self.wells.iloc[0:0]
        return rows if gene is None else rows[rows["gene"] == gene]


# ---- the analysis in use -------------------------------------------------------------------


def cell_of(model: StudyModel, choice: Mapping[str, str] | None) -> dict[str, Any]:
    """The decision-space cell for a choice given as text (as the robustness grid stores it).

    ``choice`` maps a dimension to the option's grid text (``refs`` as ``"A|B"``); dimensions
    left out keep the planned option. Raises ``TraceError`` for an option the space lacks.
    """
    space = model.space
    cell = dict(space.primary)
    for dim, text in (choice or {}).items():
        if dim not in space.dimensions:
            continue
        options = space.dimensions[dim]
        match = next((o for o in options if _option_text(o) == str(text)), None)
        if match is None:
            raise TraceError(f"The analysis option {text!r} for {dim} is not one qPilot checks.")
        cell[dim] = match
    from qpilot.qpcr.axes.normaliser import NotTraceable, as_refs_cell

    try:  # a best pair is traced as the control genes it is
        return as_refs_cell(cell, model.axis_notes.get("normaliser"))
    except NotTraceable as err:
        raise TraceError(f"Trace cannot follow this analysis: {err}.") from None


def _option_text(option: Any) -> str:
    if isinstance(option, tuple | list):
        return "|".join(option)
    return str(option)


def _rebuilt(model: StudyModel, cell: Mapping[str, Any]) -> bool:
    """True when the cell's quantities are rebuilt (an efficiency model or a plate correction)."""
    efficiency = cell.get("efficiency")
    between = cell.get("interrun")
    return (efficiency is not None and efficiency != model.settings.efficiency[0]) or (
        between is not None and between != model.settings.interrun[0]
    )


def _cell_matrix(model: StudyModel, cell: Mapping[str, Any]) -> pd.DataFrame:
    """Units x genes log2(N0) under the cell's rule, efficiency model and plate correction."""
    primary = model.space.primary.get("amp_call")
    amp = cell.get("amp_call", primary)
    if _rebuilt(model, cell):
        stage = model.cell_stage(cell)
        return stage.values.reindex(index=model.matrix.index, columns=model.matrix.columns)
    if amp is None or amp == primary:
        return model.matrix
    other = model.inputs.alternatives.get(amp)
    if other is None:
        raise TraceError(f"The amplification rule {amp!r} is not one of this study's options.")
    return other.reindex(index=model.matrix.index, columns=model.matrix.columns)


def _cell_table(model: StudyModel, cell: Mapping[str, Any]) -> pd.DataFrame:
    """The per-well table under the cell's amplification rule and efficiency model.

    The rule clears n0 where a well is not called amplified; a model other than the primary
    rebuilds n0 and marks the wells it leaves out as excluded.
    """
    if _rebuilt(model, cell):
        return model.cell_table(cell)
    primary = model.space.primary.get("amp_call")
    amp = cell.get("amp_call", primary)
    if amp is None or amp == primary:
        return model.inputs.primary_table
    from qpilot.qpcr.amp_call import apply_rule

    design = model.settings.design
    calls = dict(design.well_calls) if design is not None else {}
    return apply_rule(model.inputs.table, amp, calls)


def _cell_excluded(model: StudyModel, cell: Mapping[str, Any]) -> pd.DataFrame | None:
    """Units x genes left out entirely in this cell.

    A person's exclusions, and the wells an efficiency model leaves out (each well's own
    efficiency outside the valid range).
    """
    if _rebuilt(model, cell):
        return model.cell_stage(cell).excluded
    return model.inputs.excluded


def relative_values(
    model: StudyModel, cell: Mapping[str, Any], matrix: pd.DataFrame, items: Sequence[str]
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Values, relative values and where they enter, as ``QpcrSpace.evaluate`` has them."""
    values = matrix[list(items)].to_numpy(dtype=float)
    if cell["undetermined"] == "cap":
        with np.errstate(invalid="ignore"), _quiet():
            lowest = np.nanmin(values, axis=0)
        excluded = _cell_excluded(model, cell)
        if excluded is None:
            values = np.where(np.isnan(values), lowest, values)
        else:
            mask = excluded.reindex(index=matrix.index, columns=list(items))
            out = mask.astype("boolean").fillna(False).to_numpy(dtype=bool)
            values = np.where(np.isnan(values) & ~out, lowest, values)
    elif cell["undetermined"] != "drop":
        raise TraceError(f"Unknown empty-well rule {cell['undetermined']!r}.")
    block = matrix[list(cell["refs"])]
    ref_mean = block.mean(axis=1).to_numpy(dtype=float)
    refs_ok = block.notna().all(axis=1).to_numpy()
    relative = values - ref_mean[:, None]
    valid = refs_ok[:, None] & ~np.isnan(relative)
    return values, relative, valid


@contextmanager
def _quiet() -> Iterator[None]:
    """Silence numpy's all-NaN warnings inside a block (an all-empty column has no median)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        yield


PAIRED = (
    "{label} is a paired comparison (by {pair_by}): a sample counts only with its pair, so "
    "Trace, which sets samples aside one at a time, does not follow it. Its numbers are on the "
    "Results and the gene's page."
)


def family_of(model: StudyModel, index: pd.Index, comparison: str | None) -> Family | None:
    """The study's comparisons as groups over the matrix rows, the traced one ``comparison``.

    ``None`` for a study with one comparison (and no plan).

    Raises:
        TraceError: An id the study does not have, or a paired comparison.
    """
    space = model.space
    specs = space.comparisons
    if not specs:
        if comparison:
            raise TraceError("This study has one comparison; there is nothing to choose.")
        return None
    ids = [s.id for s in specs]
    if comparison and comparison not in ids:
        known = ", ".join(ids)
        raise TraceError(f"This study has no comparison {comparison!r} (it has: {known}).")
    chosen = ids.index(comparison) if comparison else 0
    spec = specs[chosen]
    plan = model.settings.design.comparisons if model.settings.design is not None else None
    if spec.paired:
        label = f"{spec.labels[0]} vs {spec.labels[1]}"
        raise TraceError(PAIRED.format(label=label, pair_by=plan.pair_by if plan else "pair"))
    names = list(dict.fromkeys(label for s in specs for label in s.labels))
    units: dict[str, frozenset[str]] = {}
    for s in specs:
        units.setdefault(s.labels[0], s.group_a)
        units.setdefault(s.labels[1], s.group_b)
    groups = np.array([index.isin(units[name]) for name in names], dtype=bool)
    pairs = tuple((names.index(s.labels[0]), names.index(s.labels[1])) for s in specs)
    control = plan.control if plan is not None else None
    return Family(
        groups=groups,
        pairs=pairs,
        chosen=chosen,
        correction=space.correction,
        control=names.index(control) if control in names else None,
    )


def build_context(
    model: StudyModel,
    study_id: str | None = None,
    choice: Mapping[str, str] | None = None,
    labels: tuple[str, str] | None = None,
    comparison: str | None = None,
) -> TraceContext:
    """Everything a trace needs, for the analysis ``choice`` (the planned one by default).

    In a study with several comparisons ``comparison`` names the one traced (the first by
    default); every comparison is recomputed after each change and its call uses the study's
    correction, exactly as the engine calls it.

    Raises:
        TraceError: The choice is not an option of the study, the comparison is not one of it
            or is paired, or the values computed here do not reproduce the engine's own
            comparison (then nothing is traced).
    """
    space = model.space
    cell = cell_of(model, choice)
    matrix = _cell_matrix(model, cell)
    items = list(space.items)
    refs = tuple(cell["refs"])
    units = [str(u) for u in matrix.index]
    marker = space.design.marker if space.design is not None else None
    family = family_of(model, matrix.index, comparison)
    if family is None:
        high, rest = space.groups(cell.get("cut"))
        in_a = matrix.index.isin(high)
        in_b = matrix.index.isin(rest)
        engine = space.evaluate(cell)
    else:
        in_a, in_b = family.masks()
        traced = space.comparisons[family.chosen]
        engine = space.focus(traced.id).evaluate(cell)
        labels = labels or traced.labels
    values, relative, valid = relative_values(model, cell, matrix, items)
    comparison_ = Comparison(relative, valid, in_a, in_b, space.rule, family)
    _check_against_engine(engine, comparison_.base, items)
    names = (
        labels
        or model.labels
        or (
            (space.design.group_var if space.design else "group A"),
            "rest",
        )
    )
    table = _cell_table(model, cell)
    wells = well_table(model, table, refs, marker)
    ref = reference_check(matrix, refs)
    wells = _mark_reference_wells(wells, ref, units)
    input_shift, input_z = _input_shift(matrix)
    eff_shift, eff_z = _eff_shift(wells, units)
    unknown = wells[wells["sample_type"] == "unkn"]
    return TraceContext(
        model=model,
        study_id=study_id,
        cell=cell,
        planned=cell == space.primary,
        labels=(str(names[0]), str(names[1])),
        units=units,
        items=items,
        refs=refs,
        marker=marker,
        matrix=matrix,
        values=values,
        relative=relative,
        valid=valid,
        in_a=in_a,
        in_b=in_b,
        comparison=comparison_,
        loo=comparison_.leave_one_out(),
        wells=wells,
        ref=ref,
        input_shift=input_shift,
        input_z=input_z,
        eff_shift=eff_shift,
        eff_z=eff_z,
        replicates=bool(unknown.duplicated(["unit", "gene"]).any()),
        comparison_id=space.comparisons[family.chosen].id if family is not None else None,
        comparison_label=f"{names[0]} vs {names[1]}" if family is not None else None,
        correction=family.correction if family is not None else "none",
    )


def _check_against_engine(engine: Mapping[str, Any], base: WelchArrays, items: list[str]) -> None:
    """Refuse to trace numbers that are not the engine's own (they must agree to rounding)."""
    for j, gene in enumerate(items):
        result = engine[gene]
        same_fc = math.isclose(result.log2fc, float(base.diff[j]), abs_tol=TOLERANCE)
        p = float(base.p[j])
        same_p = (math.isnan(result.p) and math.isnan(p)) or math.isclose(
            result.p, p, rel_tol=1e-6, abs_tol=1e-300
        )
        same_call = result.conclusion == CALL_NAMES[int(base.call[j])]
        if not (same_fc and same_p and same_call):
            raise TraceError(
                f"Trace could not reproduce the engine's result for {gene}; nothing is traced."
            )


# ---- wells ---------------------------------------------------------------------------------


def well_table(
    model: StudyModel, table: pd.DataFrame, refs: tuple[str, ...], marker: str | None
) -> pd.DataFrame:
    """The per-well table with each well's unit, role, plate context and flags."""
    units = model.inputs.units or {}
    out = pd.DataFrame(
        {
            "plate": table["run_id"].astype(str).to_numpy(),
            "well": table["well"].astype(str).to_numpy(),
            "sample": table["sample"].astype(str).to_numpy(),
            "sample_type": table["sample_type"].astype(str).to_numpy(),
            "gene": table["target"].astype(str).to_numpy(),
            "cq": pd.to_numeric(table["cq"], errors="coerce").to_numpy(dtype=float),
            "n0": pd.to_numeric(table["n0"], errors="coerce").to_numpy(dtype=float),
            "eff": pd.to_numeric(table["eff_indiv"], errors="coerce").to_numpy(dtype=float),
            "note": table["note"].fillna("").astype(str).to_numpy(),
            "excluded": (
                table[EXCLUDED].fillna(False).astype(bool).to_numpy()
                if EXCLUDED in table.columns
                else np.zeros(len(table), dtype=bool)
            ),
        }
    )
    out["unit"] = out["sample"].map(lambda s: units.get(s, s))
    out["key"] = out["plate"] + "/" + out["well"]
    out["amplified"] = out["n0"].notna() & ~out["excluded"]
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
    peers = out[study]
    out["plate_median_cq"] = peers.groupby(key)["cq"].transform("median").reindex(out.index)
    out["cq_z"] = _peer_z(out, study, "cq", key)
    out["eff_z"] = _peer_z(out, study, "eff", key)
    ntc = out[out["sample_type"].isin(NTC_TYPES) & out["cq"].notna()]
    ntc = ntc.sort_values(["cq", "well"], kind="mergesort").groupby(key).head(1)
    ntc = ntc.set_index(key)[["cq", "well"]].rename(columns={"cq": "ntc_cq", "well": "ntc_well"})
    out = out.join(ntc, on=key)
    gap = out["ntc_cq"] - out["cq"]
    out["ntc_gap"] = gap.where(study)
    out["s6"] = study & (gap < THRESHOLDS["ntc_window_cycles"])
    std = out[(out["sample_type"] == "std") & out["cq"].notna()]
    low = std.groupby([*key, "sample"])["cq"].median().reset_index()
    low = low.sort_values([*key, "cq", "sample"], ascending=[True, True, False, True])
    low = low.groupby(key).head(1).set_index(key)  # the latest standard: the fewest copies
    low = low.rename(columns={"cq": "std_low_cq", "sample": "std_low_name"})
    out = out.join(low[["std_low_cq", "std_low_name"]], on=key)
    out["pull"] = np.nan
    out["ref_z"] = np.nan
    out["s1"] = False
    return out


def _peer_z(out: pd.DataFrame, study: pd.Series, column: str, key: list[str]) -> pd.Series:
    """Each study well's robust z against the other study wells of its plate and gene."""
    rows = out[study & out[column].notna()]
    if rows.empty:
        return pd.Series(np.nan, index=out.index)
    grouped = rows.groupby(key)[column]
    median = grouped.transform("median")
    mad = (rows[column] - median).abs().groupby([rows[k] for k in key]).transform("median")
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (rows[column] - median) / (1.4826 * mad)
    z = z.where(mad > 0)
    return z.reindex(out.index)


def flags_of(row: Mapping[str, Any]) -> list[str]:
    """The well's flags, in a fixed order (see :data:`qpilot.trace.schema.WellFlag`)."""
    threshold = THRESHOLDS["robust_z"]
    flags = []
    if row["sample_type"] == "unkn" and not row["amplified"] and not row["excluded"]:
        flags.append("no_amplification")
    if row["excluded"]:
        flags.append("excluded")
    if _gt(row["cq_z"], threshold):
        flags.append("late_cq")
    if _gt(abs(row["eff_z"]) if _finite(row["eff_z"]) else math.nan, threshold):
        flags.append("efficiency_outlier")
    if bool(row["s1"]):
        flags.append("reference_pull")
    if bool(row["s6"]):
        flags.append("ntc_window")
    if row["note"]:
        flags.append("curve_note")
    return flags


def _gt(value: Any, threshold: float) -> bool:
    return _finite(value) and float(value) > threshold


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


# ---- per-unit fingerprints -----------------------------------------------------------------


def _input_shift(matrix: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """S2: per unit, the median over genes of log2(N0) minus the gene's median over units."""
    values = matrix.to_numpy(dtype=float)
    with np.errstate(invalid="ignore"), _quiet():
        centred = values - np.nanmedian(values, axis=0, keepdims=True)
    shift = np.array([np.nanmedian(r) if np.isfinite(r).any() else np.nan for r in centred])
    return shift, robust_z(shift)


def _eff_shift(wells: pd.DataFrame, units: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """S4: per unit, the median of each well's efficiency minus its plate-and-gene median."""
    study = wells[(wells["sample_type"] == "unkn") & wells["eff"].notna()]
    if study.empty:
        nan = np.full(len(units), np.nan)
        return nan, nan
    centred = study["eff"] - study.groupby(["plate", "gene"])["eff"].transform("median")
    per_unit = centred.groupby(study["unit"]).median()
    shift = per_unit.reindex(units).to_numpy(dtype=float)
    return shift, robust_z(shift)


def reference_check(matrix: pd.DataFrame, refs: tuple[str, ...]) -> RefCheck:
    """S1, with a second pass inside flagged units (see :class:`RefCheck`).

    Each control gene's expectation for a unit is the mean of the unit's other control genes
    plus that gene's usual offset to them (the median over units): HMBS always reads lower than
    the others, and a raw mean would flag it everywhere.
    """
    values = matrix[list(refs)].to_numpy(dtype=float)
    n_units, k = values.shape
    nan = np.full((n_units, k), np.nan)
    if k < 3:  # with two control genes one cannot say which of them is off
        return RefCheck(refs, nan, nan, np.zeros((n_units, k), dtype=bool), nan)
    complete = ~np.isnan(values).any(axis=1)
    threshold = THRESHOLDS["robust_z"]
    cache: dict[tuple[int, tuple[int, ...]], tuple[float, float]] = {}

    def offset_scale(j: int, others: tuple[int, ...]) -> tuple[float, float]:
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
    if complete.sum() < 3:
        return RefCheck(refs, dev, z, flagged, expected)
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
                dev[i, j], _, expected[i, j] = deviation(i, int(j), others)
    return RefCheck(refs=refs, dev=dev, z=z, flagged=flagged, expected=expected)


def _mark_reference_wells(wells: pd.DataFrame, ref: RefCheck, units: list[str]) -> pd.DataFrame:
    """Copy S1 (pull, z, flagged) onto the reference wells of the well table."""
    if not ref.refs:
        return wells
    index = {u: i for i, u in enumerate(units)}
    out = wells.copy()
    mask = (out["role"] == "reference") & (out["sample_type"] == "unkn")
    rows = out.index[mask]
    unit_rows = out.loc[rows, "unit"].map(index)
    gene_cols = out.loc[rows, "gene"].map({g: r for r, g in enumerate(ref.refs)})
    ok = unit_rows.notna() & gene_cols.notna()
    rows, ui, gi = rows[ok], unit_rows[ok].astype(int), gene_cols[ok].astype(int)
    pull = ref.pull
    out.loc[rows, "pull"] = pull[ui.to_numpy(), gi.to_numpy()]
    out.loc[rows, "ref_z"] = ref.z[ui.to_numpy(), gi.to_numpy()]
    out.loc[rows, "s1"] = ref.flagged[ui.to_numpy(), gi.to_numpy()] & out.loc[rows, "amplified"]
    return out


# ---- what-ifs on the measured values -------------------------------------------------------


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


def what_if_values(ctx: TraceContext, changes: Mapping[tuple[int, str], float]) -> WhatIf:
    """Every gene re-evaluated with some log2(N0) values replaced (``(unit row, gene) -> value``).

    In marker mode the groups are re-derived from the changed matrix, as a re-analysis would
    (from the planned control genes, as the space always does); ``fixed`` is then the same
    change with the groups held as they are (None when no unit crossed the line).
    """
    matrix = ctx.matrix.copy()
    for (i, gene), value in changes.items():
        matrix.iat[i, matrix.columns.get_loc(gene)] = value
    _, relative, valid = relative_values(ctx.model, ctx.cell, matrix, ctx.items)
    fixed = ctx.comparison.evaluate(relative, valid, ctx.in_a, ctx.in_b)
    space = ctx.model.space
    if space.design is None:
        return WhatIf(fixed, None, (), ())
    spec = GroupSpec(
        space.design.marker, ctx.cell["cut"], space.design.refs_primary, space.design.group_var
    )
    primary = ctx.model.matrix.copy()  # the groups always come from the planned rule's matrix
    for (i, gene), value in changes.items():
        if gene in primary.columns:
            primary.iat[i, primary.columns.get_loc(gene)] = value
    high, rest = marker_groups(primary, spec)
    old_high, _ = space.groups(ctx.cell["cut"])
    in_a, in_b = matrix.index.isin(high), matrix.index.isin(rest)
    if (in_a == ctx.in_a).all() and (in_b == ctx.in_b).all():
        return WhatIf(fixed, None, (), ())
    after = ctx.comparison.evaluate(relative, valid, in_a, in_b)
    return WhatIf(after, fixed, tuple(sorted(old_high - high)), tuple(sorted(high - old_high)))


def set_aside(
    ctx: TraceContext, rows: Sequence[int], genes: Sequence[int] | None = None
) -> WelchArrays:
    """Several units set aside together (from the ``genes`` columns, or from every gene)."""
    valid = ctx.valid.copy()
    cols = slice(None) if genes is None else list(genes)
    for i in rows:
        valid[i, cols] = False
    return ctx.comparison.evaluate(ctx.relative, valid, ctx.in_a, ctx.in_b)
