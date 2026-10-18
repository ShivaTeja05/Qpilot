"""The planted-fault benchmark for Trace (plan T3): does it point at the right well?

"Points at the right place" is a claim; this measures it. Each case copies the per-well table,
plants one fault at a seeded address, rebuilds the study model from the planted table
(:func:`qpilot.qpcr.study.build_model`: groups, reference offsets and every robust threshold are
re-derived, as they would be for a real run) and asks Trace from the entry a scientist would
use. The score is where the planted address lands among Trace's ranked places.

Fault types (:data:`FAULT_SPECS`):

======  =====================  =============================================  =================
fault   name                   what the plant changes                         Trace entry
======  =====================  =============================================  =================
F1      dead reference well    one reference well of a compared sample:       the sample
                               Cq + 8
F2      low input              every well of a compared sample: Cq + 3        the sample
F3      inhibition             every well of a compared sample: Cq + 2 and    the sample
                               its efficiency - 0.10
F4      contaminated NTC       one NTC well of a plate whose NTCs are clean:  the plate's gene
                               Cq 30
F5      empty reference well   one reference well of a compared sample: no    the sample
                               amplification
F6      one late target well   one target well of a compared sample: Cq + 3   the well, the gene
======  =====================  =============================================  =================

**The plant model** keeps every edited well as LinRegPCR would report it:

* LinRegPCR reports ``N0 = Nq / E**Cq`` with ``E`` the gene's mean efficiency on the plate
  (``eff_target``; on the demo ``n0 * eff_target**cq`` is constant within each plate to a few
  parts in 10^4 of a log10 unit). A Cq shift of ``d`` cycles therefore gives
  ``n0' = n0 * E**(-d)``, with ``E`` the well's ``eff_target`` (its own ``eff_indiv`` when the
  plate has none).
* F3 also lowers the well's own efficiency (``eff_indiv``, which S4 reads) by 0.10 on every well
  of the sample that has a Cq. ``eff_target`` is held: one well among a plate's wells moves the
  plate's mean by at most 0.10 divided by their number, LinRegPCR leaves a well more than 0.05
  from the plate's median efficiency out of that mean, and a change of the plate's mean would
  scale every well of the plate nearly alike, which cancels in every comparison. So
  ``n0' = n0 * E**-2`` there too.
* LinRegPCR is not re-run. The notes it would add are not added (for F3, "PCR efficiency
  outlier" on wells more than 0.05 below the plate's median), so the curve-note check S5 is not
  exercised: the benchmark tests Trace's own fingerprints.
* Wells without a Cq stay empty. A planted Cq never passes the latest Cq the table reports (a
  later one could not have come from the run): addresses where it would are not drawn.
* F4: the NTC well gets Cq 30 and ``n0 = Nq / E**30`` with the plate's ``Nq`` (the median of
  ``n0 * E**cq`` over its wells), amplification, and LinRegPCR's exclusion text for an
  amplifying NTC. F5: the well reads as LinRegPCR reports one with no amplification (no Cq, no
  N0, efficiency 1, R2 -1, note "no amplification;no TD0 found").

**Addresses** are drawn uniformly from sorted pools with ``numpy.random.default_rng([case seed,
fault index])``. Samples: the compared samples (every reference present, in a group) that no
study-relative check (S1, S2, S4) flags before planting; those flagged ones are the real faults.
F4 plates: a reference or compared gene's plate (the marker's feeds no compared value) with NTC
wells, none of them amplifying.

**Scoring.** The same trace is run on the unplanted table; a place at the same address that
shows no check it did not show there is a known place and is set aside, from the ranking and
from the false-place count. ``rank`` is the 1-based position of the first remaining place at
the planted address: F1 the planted reference well; F2 and F3 the sample's tube (the
whole-sample place, S2 or S4); F4 a study well of the planted plate within the NTC window (S6);
F5 the planted well among the wells that left the sample out (answer ``absent``). The other new
places are false places. **F6 is scored as a refusal**: the well trace says Trace cannot tell
from biology without replicates (``summary["limit"]``), claims no check on the well that the
unplanted well did not show, and the gene's trace shows no new place on the planted sample.
Two study-wide numbers sit beside the trace: ``new_flags_elsewhere`` (other samples newly
flagged by S1, S2 or S4, or newly in no comparison) and, for F1 to F3, ``study_rank`` (the
planted sample's rank among the newly flagged samples, by ``|z|``; ``study_rank_with_known``
counts the real faults too).

The plan's expected shape (``FaultSpec.expected``): rank 1 in at least 90 % of cases for F1,
F4 and F5; top 3 in at least 90 % for F2 and F3; refusal in every F6 case. The bar is set from
the first measured run (``methods/trace.md``).

Deterministic: the same table, settings and seed give identical cases and summaries; only
:attr:`TraceScorecard.timing` varies between runs. No model call, no network.
"""

from __future__ import annotations

import hashlib
import math
import statistics
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from qpilot.core.store import dump_json
from qpilot.qpcr.study import StudySettings, build_model
from qpilot.qpcr.trace import (
    TraceContext,
    TraceResult,
    build_context,
    trace_gene,
    trace_sample,
    trace_well,
)

if TYPE_CHECKING:
    from qpilot.qpcr.study import StudyModel

FaultId = Literal["F1", "F2", "F3", "F4", "F5", "F6"]
Entry = Literal["sample", "gene", "well"]
Measure = Literal["top1", "top3", "refusal"]

VERSION = "1"
MAX_CASES_PER_FAULT = 1000  # case seeds are seed * 1000 + i
ALL_PLACES = 1_000_000  # ``top`` for the traces the benchmark ranks: every place
NTC_AMPLIFIED = "amplification in negative control"  # LinRegPCR's exclusion text
NO_AMPLIFICATION_NOTE = "no amplification;no TD0 found"  # LinRegPCR's note, as on the demo
REFUSAL_LIMITS = ("single_target_well", "S9")  # trace_well summary["limit"] for a target well
_PLANT_COLUMNS = (
    "run_id",
    "well",
    "sample",
    "sample_type",
    "target",
    "cq",
    "n0",
    "eff_indiv",
    "eff_target",
    "note",
    "amplification",
)
_STUDY_CHECKS = ("S1", "S2", "S4")  # the study-relative checks a plant can tip elsewhere
_RATE_PLACES = 4


@dataclass(frozen=True)
class FaultSpec:
    """One planted fault type: what is changed, where Trace starts and what the plan expects."""

    id: FaultId
    name: str
    plants: str
    entry: Entry
    measure: Measure
    expected: float
    cycles: float = 0.0
    eff_delta: float = 0.0
    ntc_cq: float | None = None


FAULT_SPECS: dict[str, FaultSpec] = {
    "F1": FaultSpec(
        "F1",
        "dead reference well",
        "one reference well of a compared sample reads later",
        "sample",
        "top1",
        0.9,
        cycles=8.0,
    ),
    "F2": FaultSpec(
        "F2",
        "low input",
        "every well of a compared sample reads later",
        "sample",
        "top3",
        0.9,
        cycles=3.0,
    ),
    "F3": FaultSpec(
        "F3",
        "inhibition",
        "every well of a compared sample reads later, with a lower efficiency",
        "sample",
        "top3",
        0.9,
        cycles=2.0,
        eff_delta=-0.10,
    ),
    "F4": FaultSpec(
        "F4",
        "contaminated NTC",
        "one NTC well of a plate whose NTCs are clean amplifies",
        "gene",
        "top1",
        0.9,
        ntc_cq=30.0,
    ),
    "F5": FaultSpec(
        "F5",
        "empty reference well",
        "one reference well of a compared sample does not amplify",
        "sample",
        "top1",
        0.9,
    ),
    "F6": FaultSpec(
        "F6",
        "one late target well",
        "one target well of a compared sample reads later",
        "well",
        "refusal",
        1.0,
        cycles=3.0,
    ),
}
FAULTS: tuple[str, ...] = tuple(FAULT_SPECS)


class BenchError(ValueError):
    """The benchmark cannot run: an unknown fault, a bad seed, or nothing to plant."""


# =============================================================================================
# Result models (JSON-stable)
# =============================================================================================


class BenchCase(BaseModel):
    """One benchmark case: the fault type and the seed that re-derives its address.

    ``id`` is optional for a case built from a harness item (``trace_<fault>_seed_<seed>``).
    """

    id: str = ""
    fault: FaultId
    seed: int = Field(ge=0)


class PlantTruth(BaseModel):
    """Where a fault was planted, re-derivable from ``(fault, seed)`` and the table.

    ``sample`` is the unit planted (``None`` for F4); ``plate`` and ``well`` the planted well
    (``well`` is ``None`` for the whole-sample faults F2 and F3); ``target`` its gene; ``wells``
    every well key the plant changed, sorted. ``entry`` and ``root`` say where Trace starts
    (a sample, a gene, or a well key) and ``gene`` the gene traced besides (F4, F6).
    """

    fault: FaultId
    seed: int
    sample: str | None
    plate: str | None
    well: str | None
    target: str | None
    wells: list[str]
    cycles: float
    eff_delta: float
    ntc_cq: float | None
    entry: Entry
    root: str
    gene: str | None = None


class CaseResult(BaseModel):
    """One case scored: where the planted address ranks among the new places.

    ``rank``, ``top1``, ``top3`` and ``detected`` are ``None`` for F6, ``refusal`` is ``None``
    for F1 to F5. ``hit_checks`` and ``hit_consequence`` are the checks and the consequence
    class of the place at the planted address (F6: the checks claimed on the planted well).
    ``n_new_places`` excludes the ``n_known_places`` the unplanted trace already shows;
    ``false_places`` are new places not at the planted address (for F6, new places in the
    gene's trace), ``false_place_checks`` the checks they show. ``study_rank`` (F1 to F3)
    ranks the planted sample among the samples the plant newly flags study-wide;
    ``study_rank_with_known`` among every flagged sample, the real faults included.
    ``flagged_elsewhere`` names the other samples the plant newly flags (``new_flags_elsewhere``
    counts them). ``refs_changed``: the planted table's model chose other reference genes.
    """

    id: str
    fault: FaultId
    seed: int
    truth: PlantTruth | None = None
    answer: str | None = None
    rank: int | None = None
    top1: bool | None = None
    top3: bool | None = None
    detected: bool | None = None
    refusal: bool | None = None
    hit_checks: list[str] = Field(default_factory=list)
    hit_consequence: str | None = None
    n_new_places: int = 0
    n_known_places: int = 0
    false_places: int = 0
    false_place_checks: list[str] = Field(default_factory=list)
    study_rank: int | None = None
    study_rank_with_known: int | None = None
    new_flags_elsewhere: int = 0
    flagged_elsewhere: list[str] = Field(default_factory=list)
    refs_changed: bool = False
    detail: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class FaultScore(BaseModel):
    """One fault type summarised over its cases (rates are counts over ``n``, four places)."""

    fault: FaultId
    name: str
    entry: Entry
    measure: Measure
    expected: float
    n: int
    n_errors: int
    detected: int | None
    top1: int | None
    top3: int | None
    refusals: int | None
    detected_rate: float | None
    top1_rate: float | None
    top3_rate: float | None
    refusal_rate: float | None
    measured: float | None
    meets_expected: bool
    false_places_mean: float | None
    false_places_max: int | None
    new_flags_elsewhere_mean: float | None
    study_top1: int | None
    study_top1_rate: float | None
    study_top1_with_known: int | None
    n_refs_changed: int


class TraceScorecard(BaseModel):
    """The benchmark's result: per-fault scores, every case, and timing.

    Everything but :attr:`timing` is deterministic for a given table, settings and seed;
    :meth:`results_json` and :meth:`results_sha256` leave the timing out.
    """

    version: str = VERSION
    seed: int
    n_per_fault: int
    faults: list[FaultId]
    parameters: dict[str, dict[str, Any]]
    input: dict[str, Any]
    baseline: dict[str, Any]
    by_fault: dict[str, FaultScore]
    cases: list[CaseResult]
    timing: dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> str:
        """Byte-stable JSON with the timing."""
        return dump_json(self.model_dump(mode="json"))

    def results_json(self) -> str:
        """Byte-stable JSON without the timing (identical for the same seed)."""
        return dump_json(self.model_dump(mode="json", exclude={"timing"}))

    def results_sha256(self) -> str:
        """SHA-256 of :meth:`results_json`."""
        return hashlib.sha256(self.results_json().encode()).hexdigest()

    def markdown(self) -> str:
        """The per-fault table (Markdown), for the method card and the harness report."""
        head = (
            "| Fault | Planted | Trace entry | Cases | Found | Rank 1 | Top 3 | Refusal | "
            "False places per run (mean, max) | New flags elsewhere (mean) | Plan expects | "
            "Holds |"
        )
        rows = [head, "|" + "---|" * 12]
        for fid in self.faults:
            s = self.by_fault[fid]
            spec = FAULT_SPECS[fid]
            measure = {"top1": "rank 1", "top3": "top 3", "refusal": "refusal"}[s.measure]
            false = (
                f"{s.false_places_mean:.2f}, {s.false_places_max}"
                if s.false_places_mean is not None
                else "—"
            )
            flags = (
                f"{s.new_flags_elsewhere_mean:.2f}"
                if s.new_flags_elsewhere_mean is not None
                else "—"
            )
            rows.append(
                "| "
                + " | ".join(
                    [
                        f"{fid} {s.name}",
                        _describe(spec),
                        _entry_words(spec),
                        str(s.n),
                        _count(s.detected, s.n),
                        _count(s.top1, s.n),
                        _count(s.top3, s.n),
                        _count(s.refusals, s.n),
                        false,
                        flags,
                        f"{measure} ≥ {100 * s.expected:.0f} %",
                        "yes" if s.meets_expected else "no",
                    ]
                )
                + " |"
            )
        return "\n".join(rows) + "\n"


def _count(k: int | None, n: int) -> str:
    if k is None:
        return "—"
    return f"{k}/{n} ({100 * k / n:.0f} %)" if n else "0/0"


def _describe(spec: FaultSpec) -> str:
    parts = []
    if spec.cycles:
        parts.append(f"Cq +{spec.cycles:g}")
    if spec.eff_delta:
        parts.append(f"efficiency {spec.eff_delta:+.2f}")
    if spec.ntc_cq is not None:
        parts.append(f"NTC Cq {spec.ntc_cq:g}")
    if spec.id == "F5":
        parts.append("no amplification")
    where = {
        "F1": "one reference well",
        "F2": "every well of a sample",
        "F3": "every well of a sample",
        "F4": "one NTC well of a clean plate",
        "F5": "one reference well",
        "F6": "one target well",
    }[spec.id]
    return f"{where}: {', '.join(parts)}"


def _entry_words(spec: FaultSpec) -> str:
    return {
        "sample": "trace the sample",
        "gene": "trace the plate's gene",
        "well": "trace the well and its gene",
    }[spec.entry]


# =============================================================================================
# The baseline: the unplanted study, the address pools, the known places
# =============================================================================================


@dataclass(eq=False)
class BenchBaseline:
    """The unplanted study a benchmark plants into, built once by :func:`prepare_baseline`.

    Holds the table, settings, model and trace context, the latest Cq the table reports
    (``max_cq``), the real faults set aside from the pools (``real``), the address pool of
    every fault type and a cache of the unplanted traces (the known places).
    """

    curves: pd.DataFrame
    settings: StudySettings
    model: StudyModel
    ctx: TraceContext
    table_sha256: str
    max_cq: float
    row_of: dict[str, Any]
    efficiency: dict[str, float]
    real: tuple[str, ...]
    pools: dict[str, list[tuple]]
    flags: dict[tuple[str, str], float]
    seconds: float
    _traces: dict[tuple[str, str], TraceResult] = field(default_factory=dict)

    def trace(self, entry: str, root: str) -> TraceResult:
        """The unplanted trace for ``entry`` (``sample``, ``gene`` or ``well``) and ``root``."""
        key = (entry, root)
        if key not in self._traces:
            self._traces[key] = _run_entry(self.ctx, entry, root)
        return self._traces[key]


def prepare_baseline(curves: pd.DataFrame, settings: StudySettings | None = None) -> BenchBaseline:
    """Build the unplanted study once: model, trace context, address pools.

    Args:
        curves: The per-well table (:func:`qpilot.qpcr.curves.analyse_study`), unplanted.
        settings: The study's settings; the demo analysis when not given.

    Raises:
        BenchError: The table lacks a column the plant needs, or two rows share a well key.
    """
    t0 = time.perf_counter()
    missing = [c for c in _PLANT_COLUMNS if c not in curves.columns]
    if missing:
        raise BenchError(f"the per-well table lacks the columns the plant needs: {missing}")
    settings = settings or StudySettings()
    keys = (curves["run_id"].astype(str) + "/" + curves["well"].astype(str)).to_numpy()
    if len(set(keys)) != len(keys):
        raise BenchError("two rows of the per-well table share a run_id/well key")
    row_of = dict(zip(keys.tolist(), curves.index.tolist(), strict=True))
    eff_target = curves["eff_target"].to_numpy(dtype=float)
    eff_indiv = curves["eff_indiv"].to_numpy(dtype=float)
    usable = np.isfinite(eff_target) & (eff_target > 1.0)
    eff = np.where(usable, eff_target, eff_indiv)
    efficiency = {k: float(e) for k, e in zip(keys.tolist(), eff.tolist(), strict=True)}
    cq = curves["cq"].to_numpy(dtype=float)
    max_cq = float(np.nanmax(cq)) if np.isfinite(cq).any() else math.nan
    model = build_model(curves, settings)
    ctx = build_context(curves, model)
    flags = _flags(ctx)
    real = tuple(sorted({unit for unit, check in flags if check in _STUDY_CHECKS}))
    pools = _pools(ctx, max_cq, row_of, efficiency, set(real))
    return BenchBaseline(
        curves=curves,
        settings=settings,
        model=model,
        ctx=ctx,
        table_sha256=_table_sha256(curves),
        max_cq=max_cq,
        row_of=row_of,
        efficiency=efficiency,
        real=real,
        pools=pools,
        flags=flags,
        seconds=time.perf_counter() - t0,
    )


def _table_sha256(curves: pd.DataFrame) -> str:
    """SHA-256 of the table as CSV (the identity of the input in the scorecard)."""
    return hashlib.sha256(curves.to_csv(index=False).encode()).hexdigest()


def _flags(ctx: TraceContext) -> dict[tuple[str, str], float]:
    """Study-level flags ``(unit, check) -> |z|``: S1, S2, S4, and S7 (no z: 0)."""
    out: dict[tuple[str, str], float] = {}
    for i, r in ctx.s1_flag.items():
        out[(ctx.units[i], "S1")] = abs(float(ctx.s1_z[i, r]))
    tube = ctx.tube
    for unit, s2, s4, z_late, z_eff in zip(
        tube.index, tube["s2"], tube["s4"], tube["z_late"], tube["z_eff"], strict=True
    ):
        if bool(s2):
            out[(str(unit), "S2")] = abs(float(z_late))
        if bool(s4):
            out[(str(unit), "S4")] = abs(float(z_eff))
    for entry in ctx.absent:
        out[(str(entry["sample"]), "S7")] = 0.0
    return out


def _pools(
    ctx: TraceContext,
    max_cq: float,
    row_of: Mapping[str, Any],
    efficiency: Mapping[str, float],
    real: set[str],
) -> dict[str, list[tuple]]:
    """Every address each fault type may be planted at, in a fixed (sorted) order."""
    w = ctx.wells
    cq = dict(zip(w.index.tolist(), w["cq"].astype(float).tolist(), strict=True))

    def plantable(key: str | None, cycles: float) -> bool:
        if key is None or key not in row_of:
            return False
        value = cq.get(key, math.nan)
        e = efficiency.get(key, math.nan)
        return math.isfinite(value) and math.isfinite(e) and e > 1.0 and value + cycles <= max_cq

    compared = sorted(ctx.units[i] for i in np.flatnonzero(ctx.used) if ctx.units[i] not in real)
    study = w[w["sample_type"] == "unkn"]  # every well of the tube, as a whole-sample plant
    by_unit = {str(u): sorted(g.index.tolist()) for u, g in study.groupby("unit", sort=True)}
    cell = {pair: entry[0] for pair, entry in ctx.cells.items()}
    pools: dict[str, list[tuple]] = {f: [] for f in FAULTS}
    for unit in compared:
        row = ctx.unit_row[unit]
        for ref in ctx.refs:
            key = cell.get((unit, ref))
            if plantable(key, 0.0):
                pools["F5"].append((unit, ref, key))
            if plantable(key, FAULT_SPECS["F1"].cycles):
                pools["F1"].append((unit, ref, key))
        amplified = [k for k in by_unit.get(unit, []) if math.isfinite(cq.get(k, math.nan))]
        for fault in ("F2", "F3"):
            cycles = FAULT_SPECS[fault].cycles
            if amplified and all(plantable(k, cycles) for k in amplified):
                pools[fault].append((unit,))
        for gene in ctx.items:
            key = cell.get((unit, gene))
            if ctx.valid[row, ctx.item_col[gene]] and plantable(key, FAULT_SPECS["F6"].cycles):
                pools["F6"].append((unit, gene, key))
    ntc = w[(w["sample_type"] == "ntc") & ~w["person_excluded"]]
    ntc_wells = {
        (str(r), str(t)): sorted(k for k in g.index.tolist() if k in row_of)
        for (r, t), g in ntc.groupby(["run_id", "target"], sort=True)
    }
    for (run, target), info in sorted(ctx.plates.items()):
        feeds = target in ctx.refs or target in ctx.item_col
        wells = ntc_wells.get((run, target), [])
        if feeds and target != ctx.marker and wells and not info["n_ntc_amplified"]:
            pools["F4"].append((run, target, tuple(wells)))
    return pools


# =============================================================================================
# Planting
# =============================================================================================


def _spec(fault: str) -> FaultSpec:
    if fault not in FAULT_SPECS:
        raise BenchError(f"unknown fault {fault!r}; one of {', '.join(FAULTS)}")
    return FAULT_SPECS[fault]


def _check_seed(seed: int) -> int:
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)) or seed < 0:
        raise BenchError("seed must be a whole number of at least 0")
    return int(seed)


def plant(
    curves: pd.DataFrame,
    fault: str,
    seed: int,
    *,
    baseline: BenchBaseline | None = None,
    settings: StudySettings | None = None,
) -> tuple[pd.DataFrame, PlantTruth]:
    """Plant one fault in a copy of the per-well table, at an address drawn from ``seed``.

    Args:
        curves: The unplanted per-well table (never modified).
        fault: ``"F1"`` to ``"F6"`` (:data:`FAULT_SPECS`).
        seed: A whole number; with the fault it fixes the address.
        baseline: :func:`prepare_baseline` of ``curves`` (built here when not given).
        settings: The study's settings when the baseline is built here.

    Returns:
        The planted copy and where the fault is (:class:`PlantTruth`).

    Raises:
        BenchError: An unknown fault, a bad seed, a baseline of another table, or a study with
            nothing to plant this fault at.
    """
    spec = _spec(fault)
    seed = _check_seed(seed)
    bl = baseline if baseline is not None else prepare_baseline(curves, settings)
    if curves is not bl.curves and not (
        curves.index.equals(bl.curves.index)
        and curves["run_id"].equals(bl.curves["run_id"])
        and curves["well"].equals(bl.curves["well"])
    ):
        raise BenchError("the baseline was prepared from another per-well table")
    pool = bl.pools[spec.id]
    if not pool:
        raise BenchError(f"{spec.id} ({spec.name}): this study has no address to plant it at")
    rng = np.random.default_rng([seed, FAULTS.index(spec.id)])
    pick = pool[int(rng.integers(len(pool)))]
    out = curves.copy()
    ctx = bl.ctx
    gene = None
    if spec.id in ("F1", "F5", "F6"):
        unit, target, key = pick
        if spec.id == "F5":
            _empty(out, bl, key)
        else:
            _shift(out, bl, [key], spec.cycles, 0.0)
        wells = [key]
        root = key if spec.entry == "well" else unit
        gene = target if spec.id == "F6" else None
    elif spec.id in ("F2", "F3"):
        (unit,) = pick
        study = ctx.wells[(ctx.wells["unit"] == unit) & (ctx.wells["sample_type"] == "unkn")]
        wells = sorted(
            k
            for k, c in zip(study.index, study["cq"], strict=True)
            if math.isfinite(float(c)) and k in bl.row_of
        )
        _shift(out, bl, wells, spec.cycles, spec.eff_delta)
        key, target, root = None, None, unit
    else:  # F4
        run, target, ntc_wells = pick
        key = ntc_wells[int(rng.integers(len(ntc_wells)))]
        _contaminate(out, bl, key, run, target, float(spec.ntc_cq))
        unit, wells = None, [key]
        gene = target if target in ctx.item_col else ctx.items[int(rng.integers(len(ctx.items)))]
        root = gene
    row = ctx.wells.loc[key] if key is not None else None
    truth = PlantTruth(
        fault=spec.id,
        seed=seed,
        sample=unit,
        plate=str(row["run_id"]) if row is not None else None,
        well=str(row["well"]) if row is not None else None,
        target=target,
        wells=wells,
        cycles=spec.cycles,
        eff_delta=spec.eff_delta,
        ntc_cq=spec.ntc_cq,
        entry=spec.entry,
        root=root,
        gene=gene,
    )
    return out, truth


def _shift(
    out: pd.DataFrame, bl: BenchBaseline, keys: Sequence[str], cycles: float, eff_delta: float
) -> None:
    """Cq + ``cycles`` and ``n0 * E**-cycles`` (E: the plate's efficiency); ``eff_indiv`` moved."""
    rows = [bl.row_of[k] for k in keys]
    factor = np.array([bl.efficiency[k] ** -cycles for k in keys])
    out.loc[rows, "cq"] = out.loc[rows, "cq"].to_numpy(dtype=float) + cycles
    out.loc[rows, "n0"] = out.loc[rows, "n0"].to_numpy(dtype=float) * factor
    if eff_delta:
        out.loc[rows, "eff_indiv"] = out.loc[rows, "eff_indiv"].to_numpy(dtype=float) + eff_delta


def _empty(out: pd.DataFrame, bl: BenchBaseline, key: str) -> None:
    """The well as LinRegPCR reports one with no amplification."""
    row = bl.row_of[key]
    out.loc[row, ["cq", "n0"]] = [math.nan, math.nan]
    out.loc[row, "eff_indiv"] = 1.0
    out.loc[row, "amplification"] = False
    out.loc[row, "note"] = NO_AMPLIFICATION_NOTE
    if "r2" in out.columns:
        out.loc[row, "r2"] = -1.0


def _contaminate(
    out: pd.DataFrame, bl: BenchBaseline, key: str, run: str, target: str, cq: float
) -> None:
    """The NTC well amplifies at ``cq``, its N0 on the plate's threshold."""
    c = bl.curves
    plate = (c["run_id"].astype(str) == run) & (c["target"].astype(str) == target)
    rows = c[plate & c["cq"].notna() & c["n0"].notna()]
    keys = (rows["run_id"].astype(str) + "/" + rows["well"].astype(str)).tolist()
    e = np.array([bl.efficiency[k] for k in keys])
    nq = float(np.median(rows["n0"].to_numpy(dtype=float) * e ** rows["cq"].to_numpy(dtype=float)))
    efficiency = bl.efficiency[key]
    row = bl.row_of[key]
    out.loc[row, ["cq", "n0"]] = [cq, nq / efficiency**cq]
    out.loc[row, "eff_indiv"] = efficiency
    out.loc[row, "amplification"] = True
    out.loc[row, "note"] = ""
    if "excluded" in out.columns:
        out.loc[row, "excluded"] = NTC_AMPLIFIED
    if "plateau" in out.columns:
        out.loc[row, "plateau"] = True
    if "r2" in out.columns and len(rows):
        out.loc[row, "r2"] = float(rows["r2"].median())


# =============================================================================================
# Cases and scoring
# =============================================================================================


def bench_items(
    n_per_fault: int = 50, seed: int = 0, faults: Iterable[str] = FAULTS
) -> list[BenchCase]:
    """The benchmark's cases: ``n_per_fault`` per fault, case seeds ``seed * 1000 + i``.

    For the harness: each case carries only its fault and seed; :func:`run_case` re-derives
    the address from them.

    Raises:
        BenchError: An unknown fault, a bad seed, or more than 1000 cases per fault.
    """
    seed = _check_seed(seed)
    if isinstance(n_per_fault, bool) or not isinstance(n_per_fault, int) or n_per_fault < 1:
        raise BenchError("n_per_fault must be a whole number of at least 1")
    if n_per_fault > MAX_CASES_PER_FAULT:
        raise BenchError(f"at most {MAX_CASES_PER_FAULT} cases per fault")
    faults = [_spec(f).id for f in faults]
    if not faults or len(set(faults)) != len(faults):
        raise BenchError("give each fault at most once, and at least one")
    width = max(2, len(str(n_per_fault)))
    return [
        BenchCase(
            id=f"trace_{fault.lower()}_{i + 1:0{width}d}",
            fault=fault,
            seed=seed * MAX_CASES_PER_FAULT + i,
        )
        for fault in faults
        for i in range(n_per_fault)
    ]


def _run_entry(ctx: TraceContext, entry: str, root: str) -> TraceResult:
    if entry == "sample":
        return trace_sample(ctx, root, top=ALL_PLACES)
    if entry == "gene":
        return trace_gene(ctx, root, top=ALL_PLACES)
    return trace_well(ctx, root, top=ALL_PLACES)


@dataclass(frozen=True)
class _Addr:
    """One place (or, for an ``absent`` answer, one well that left the sample out)."""

    role: str
    sample: str
    plate: str | None
    well: str | None
    checks: frozenset[str]
    consequence: str | None = None  # the place's class (None for a well that left it out)

    @property
    def key(self) -> tuple[str, str, str | None, str | None]:
        return (self.role, self.sample, self.plate, self.well)


def _addresses(result: TraceResult) -> list[_Addr]:
    """The ranked places of a trace; for ``absent``, the wells that left the sample out."""
    if result.answer == "absent":
        return [
            _Addr("empty_well", str(e["sample"]), r.get("plate"), r.get("well"), frozenset({"S7"}))
            for e in result.absent
            for r in e.get("reasons", [])
        ]
    return [
        _Addr(p.role, p.sample, p.plate, p.well, frozenset(p.checks), p.consequence)
        for p in result.places
    ]


def _new(result: TraceResult, known: TraceResult) -> tuple[list[_Addr], int]:
    """Places not known from the unplanted trace (same address, no check it lacked there)."""
    before: dict[tuple, frozenset[str]] = {}
    for a in _addresses(known):
        before[a.key] = before.get(a.key, frozenset()) | a.checks
    new, n_known = [], 0
    for a in _addresses(result):
        if a.key in before and a.checks <= before[a.key]:
            n_known += 1
        else:
            new.append(a)
    return new, n_known


def _hit(fault: str, truth: PlantTruth, a: _Addr) -> bool:
    if fault == "F1":
        return a.role == "reference_well" and (a.plate, a.well) == (truth.plate, truth.well)
    if fault in ("F2", "F3"):
        return a.role == "sample" and a.sample == truth.sample
    if fault == "F4":
        return a.plate == truth.plate and "S6" in a.checks
    if fault == "F5":
        return (a.plate, a.well) == (truth.plate, truth.well)
    return False


def run_case(case: BenchCase | Mapping[str, Any], baseline: BenchBaseline) -> CaseResult:
    """Plant one case, rebuild the model, run Trace from the fault's entry and score it.

    Args:
        case: A :class:`BenchCase` (or a mapping with ``id``, ``fault`` and ``seed``, as a
            harness item carries it).
        baseline: :func:`prepare_baseline` of the unplanted table.

    Raises:
        BenchError: See :func:`plant`. Errors of the model or the trace are raised as they come.
    """
    case = case if isinstance(case, BenchCase) else BenchCase.model_validate(dict(case))
    if not case.id:
        case = case.model_copy(update={"id": f"trace_{case.fault.lower()}_seed_{case.seed}"})
    spec = FAULT_SPECS[case.fault]
    planted, truth = plant(baseline.curves, case.fault, case.seed, baseline=baseline)
    model = build_model(planted, baseline.settings)
    ctx = build_context(planted, model)
    flags = _flags(ctx)
    new_flags = {k: z for k, z in flags.items() if k not in baseline.flags}
    elsewhere = sorted({unit for unit, _ in new_flags if unit != truth.sample})
    common = {
        "id": case.id,
        "fault": case.fault,
        "seed": case.seed,
        "truth": truth,
        "new_flags_elsewhere": len(elsewhere),
        "flagged_elsewhere": elsewhere,
        "refs_changed": tuple(ctx.refs) != tuple(baseline.ctx.refs),
    }
    if spec.measure == "refusal":
        return _score_refusal(ctx, baseline, truth, common)
    result = _run_entry(ctx, spec.entry, truth.root)
    new, n_known = _new(result, baseline.trace(spec.entry, truth.root))
    hits = [n for n, a in enumerate(new, start=1) if _hit(spec.id, truth, a)]
    rank = hits[0] if hits else None
    return CaseResult(
        **common,
        answer=result.answer,
        rank=rank,
        top1=rank == 1,
        top3=rank is not None and rank <= 3,
        detected=rank is not None,
        hit_checks=sorted(new[rank - 1].checks) if rank is not None else [],
        hit_consequence=new[rank - 1].consequence if rank is not None else None,
        n_new_places=len(new),
        n_known_places=n_known,
        false_places=len(new) - len(hits),
        false_place_checks=_checks_of(a for a in new if not _hit(spec.id, truth, a)),
        study_rank=_study_rank(spec.id, truth, new_flags),
        study_rank_with_known=_study_rank(spec.id, truth, flags),
    )


def _checks_of(places: Iterable[_Addr]) -> list[str]:
    return sorted({c for a in places for c in a.checks})


def _study_rank(fault: str, truth: PlantTruth, flags: Mapping[tuple, float]) -> int | None:
    """F1 to F3: the planted sample's rank among the flagged samples of ``flags``, by ``|z|``.

    Given the new flags only, the known real faults are set aside; given every flag of the
    planted study, they compete with the plant.
    """
    checks = {"F1": ("S1",), "F2": ("S2", "S4"), "F3": ("S2", "S4")}.get(fault)
    if checks is None:
        return None
    best: dict[str, float] = {}
    for (unit, check), z in flags.items():
        if check in checks:
            best[unit] = max(best.get(unit, 0.0), z)
    order = sorted(best, key=lambda u: (-best[u], u))
    return order.index(truth.sample) + 1 if truth.sample in best else None


def _score_refusal(
    ctx: TraceContext, bl: BenchBaseline, truth: PlantTruth, common: dict[str, Any]
) -> CaseResult:
    """F6: the well trace states the limit and claims nothing new; the gene trace agrees."""
    well = trace_well(ctx, truth.root, top=ALL_PLACES)
    before = bl.trace("well", truth.root)
    limit = well.summary.get("limit")
    states = (
        well.summary.get("role") == "target_well"
        and limit in REFUSAL_LIMITS
        and "single_target_well" in well.cannot_show
    )
    checks_now = set(well.places[0].checks) if well.places else set()
    checks_before = set(before.places[0].checks) if before.places else set()
    claimed = sorted(checks_now - checks_before)
    gene = trace_gene(ctx, str(truth.gene), top=ALL_PLACES)
    new, n_known = _new(gene, bl.trace("gene", str(truth.gene)))
    on_sample = [a for a in new if a.sample == truth.sample]
    listed = any(e.get("sample") == truth.sample for e in gene.influential_nothing_unusual)
    return CaseResult(
        **common,
        answer=well.answer,
        refusal=bool(states and not claimed and not on_sample),
        hit_checks=claimed,
        n_new_places=len(new),
        n_known_places=n_known,
        false_places=len(new),
        false_place_checks=_checks_of(new),
        detail={
            "limit": limit,
            "claimed_checks": claimed,
            "new_places_on_sample": len(on_sample),
            "listed_influential_nothing_unusual": listed,
            "gene_answer": gene.answer,
        },
    )


# =============================================================================================
# The benchmark
# =============================================================================================


def run_benchmark(
    curves: pd.DataFrame,
    settings: StudySettings | None = None,
    *,
    n_per_fault: int = 50,
    seed: int = 0,
    faults: Iterable[str] = FAULTS,
) -> TraceScorecard:
    """Run the planted-fault benchmark on one study and score it.

    Args:
        curves: The unplanted per-well table.
        settings: The study's settings; the demo analysis when not given.
        n_per_fault: Cases per fault type (at most 1000).
        seed: The benchmark seed (case seeds ``seed * 1000 + i``).
        faults: The fault types to run, in order.

    Returns:
        The :class:`TraceScorecard`. A case whose plant, model or trace raises is kept with its
        ``error`` and counts as a miss (``FaultScore.n_errors``).

    Raises:
        BenchError: Bad arguments, a table the plant cannot use, or a fault with nothing to
            plant at.
    """
    t0 = time.perf_counter()
    cases = bench_items(n_per_fault, seed, faults)
    order = list(dict.fromkeys(c.fault for c in cases))
    bl = prepare_baseline(curves, settings)
    empty = [f for f in order if not bl.pools[f]]
    if empty:
        raise BenchError(f"this study has no address to plant {', '.join(empty)} at")
    results: list[CaseResult] = []
    seconds: dict[str, list[float]] = {f: [] for f in order}
    for case in cases:
        start = time.perf_counter()
        try:
            results.append(run_case(case, bl))
        except Exception as err:  # noqa: BLE001 - a failed case is a scored miss, not a crash
            results.append(
                CaseResult(
                    id=case.id,
                    fault=case.fault,
                    seed=case.seed,
                    error=f"{type(err).__name__}: {err}",
                )
            )
        seconds[case.fault].append(time.perf_counter() - start)
    by_fault = {f: _summarise(FAULT_SPECS[f], [r for r in results if r.fault == f]) for f in order}
    total = time.perf_counter() - t0
    timing = {
        "baseline_s": round(bl.seconds, 3),
        "total_s": round(total, 3),
        "per_case_mean_s": round(statistics.fmean(sum(seconds.values(), [])), 4),
        "per_fault": {
            f: {"mean_s": round(statistics.fmean(s), 4), "max_s": round(max(s), 4)}
            for f, s in seconds.items()
        },
    }
    return TraceScorecard(
        seed=seed,
        n_per_fault=n_per_fault,
        faults=order,
        parameters={f: _parameters(FAULT_SPECS[f]) for f in order},
        input=_input(bl),
        baseline={
            "n_real_faults_set_aside": len(bl.real),
            "n_s1_flags": len(bl.ctx.s1_flag),
            "n_tube_flags": int((bl.ctx.tube["s2"] | bl.ctx.tube["s4"]).sum()),
            "n_absent": len(bl.ctx.absent),
            "max_cq": round(bl.max_cq, 4),
            "pool_sizes": {f: len(bl.pools[f]) for f in order},
        },
        by_fault=by_fault,
        cases=results,
        timing=timing,
    )


def _parameters(spec: FaultSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "plants": spec.plants,
        "entry": spec.entry,
        "measure": spec.measure,
        "expected": spec.expected,
        "cycles": spec.cycles,
        "eff_delta": spec.eff_delta,
        "ntc_cq": spec.ntc_cq,
    }


def _input(bl: BenchBaseline) -> dict[str, Any]:
    ctx = bl.ctx
    return {
        "n_wells": len(bl.curves),
        "n_plates": len(ctx.plates),
        "n_compared": int(ctx.used.sum()),
        "n_genes": len(ctx.items),
        "refs": list(ctx.refs),
        "table_sha256": bl.table_sha256,
    }


def _rate(k: int | None, n: int) -> float | None:
    return round(k / n, _RATE_PLACES) if k is not None and n else None


def _summarise(spec: FaultSpec, cases: Sequence[CaseResult]) -> FaultScore:
    n = len(cases)
    ok = [c for c in cases if c.error is None]
    refusal = spec.measure == "refusal"

    def count(attr: str, applies: bool) -> int | None:
        return sum(bool(getattr(c, attr)) for c in cases) if applies else None

    detected = count("detected", not refusal)
    top1 = count("top1", not refusal)
    top3 = count("top3", not refusal)
    refusals = count("refusal", refusal)
    measured = {"top1": top1, "top3": top3, "refusal": refusals}[spec.measure]
    false = [c.false_places for c in ok]
    flags = [c.new_flags_elsewhere for c in ok]
    study = spec.id in ("F1", "F2", "F3")
    study_top1 = sum(c.study_rank == 1 for c in cases) if study else None
    with_known = sum(c.study_rank_with_known == 1 for c in cases) if study else None
    return FaultScore(
        fault=spec.id,
        name=spec.name,
        entry=spec.entry,
        measure=spec.measure,
        expected=spec.expected,
        n=n,
        n_errors=n - len(ok),
        detected=detected,
        top1=top1,
        top3=top3,
        refusals=refusals,
        detected_rate=_rate(detected, n),
        top1_rate=_rate(top1, n),
        top3_rate=_rate(top3, n),
        refusal_rate=_rate(refusals, n),
        measured=_rate(measured, n),
        meets_expected=bool(n) and measured is not None and measured / n >= spec.expected,
        false_places_mean=round(statistics.fmean(false), _RATE_PLACES) if false else None,
        false_places_max=max(false) if false else None,
        new_flags_elsewhere_mean=round(statistics.fmean(flags), _RATE_PLACES) if flags else None,
        study_top1=study_top1,
        study_top1_rate=_rate(study_top1, n),
        study_top1_with_known=with_known,
        n_refs_changed=sum(c.refs_changed for c in ok),
    )


__all__: Sequence[str] = (
    "FAULTS",
    "FAULT_SPECS",
    "BenchBaseline",
    "BenchCase",
    "BenchError",
    "CaseResult",
    "FaultScore",
    "FaultSpec",
    "PlantTruth",
    "TraceScorecard",
    "bench_items",
    "plant",
    "prepare_baseline",
    "run_benchmark",
    "run_case",
)
