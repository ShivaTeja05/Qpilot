"""Position history: does an odd well follow the instrument, or move with the samples?

On demand only ("check this instrument"), never a default card. For every well with a Cq, its
**residual** is its Cq minus the median Cq of its replicate group (same sample, same target,
same run; groups of fewer than ``min_replicates`` wells with a Cq say nothing and are skipped).
A well is **off** when ``|residual| > off_cycles`` (0.5 cycles by default).

* **Base rate**: the lab's own share of off wells over every residual given (all instruments);
  this is the null, so the test asks "more often than this lab's pipetting and replicate noise".
* **Per instrument and position**: across that instrument's runs, ``n`` residuals at the
  position, ``x`` of them off; one-sided binomial test ``P(X >= x | n, base rate)``,
  Bonferroni-adjusted over the positions tested on that instrument.
* **Flagged** only when the adjusted p < ``alpha`` (0.05) **and** the off runs at that position
  span at least ``min_people_or_layouts`` people or plate layouts (a layout is which sample sat
  in which well; given, or fingerprinted from the run itself), so a sample that always sits in
  the same well is never taken for the instrument.
* **Runs needed**: the smallest ``k`` for which a position off in ``k`` of ``k`` runs would beat
  chance after the correction (``positions x base_rate**k < alpha``). A position with fewer runs
  than that cannot be flagged at all.

One answer per instrument: ``follows_instrument`` (some position is flagged),
``not_enough_runs`` (no position has the runs needed, or a position beats chance only with one
layout and at most one person on record, so the samples that always sit there cannot be told
from the instrument), or ``moves_with_samples`` (positions had the runs needed and none beats
chance: the odd wells move between runs, so look at pipetting or the sample).

Operators are counted, never reported: names stay on this machine. Deterministic, no model.
Research use only.
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, field_validator
from scipy import stats

from qpilot.core.facts import FactRegistry, slug
from qpilot.core.instruments import WELL, well_order
from qpilot.core.store import canonical_json
from qpilot.schemas import Fact

if TYPE_CHECKING:
    from qpilot.core.store import StudyStore

OFF_CYCLES = 0.5
ALPHA = 0.05
MIN_REPLICATES = 2
MAX_RUNS_NEEDED = 1_000
STUDY_TYPES = ("unkn", "std")  # replicate groups of samples and standards; never NTC wells

Answer = Literal["follows_instrument", "moves_with_samples", "not_enough_runs"]
WORDS = {
    "follows_instrument": "follows the instrument",
    "moves_with_samples": "moves with the samples",
    "not_enough_runs": "not enough runs yet",
}


class WellReading(BaseModel):
    """One well of one run: position, sample, target and Cq (None: no Cq)."""

    well: str
    sample: str
    target: str
    cq: float | None = None

    @field_validator("well")
    @classmethod
    def _well(cls, value: str) -> str:
        if not WELL.match(value):
            raise ValueError("a well is a position such as A1 or P24")
        return value


class RunWells(BaseModel):
    """One run's wells on one instrument, with who ran it and the plate layout.

    ``operator`` is local only: it is counted (how many people), never reported. ``layout``
    names the plate layout; when None it is a fingerprint of which sample sat in which well
    (the target is ignored: the same samples in the same wells for another gene is the same
    layout), so two runs share a layout only when every sample sat in the same well.
    """

    run_id: str
    instrument_id: str
    operator: str | None = None
    layout: str | None = None
    wells: list[WellReading]

    def layout_key(self) -> str:
        """The layout name, or the fingerprint of the run's sample-to-well map."""
        if self.layout:
            return self.layout
        cells = sorted({(w.well, w.sample) for w in self.wells})
        return hashlib.sha256(canonical_json(cells).encode("utf-8")).hexdigest()[:12]


class PositionStat(BaseModel):
    """One well position on one instrument across its runs."""

    position: str
    n_runs: int
    n_off: int
    median_residual: float
    side: Literal["below", "above", "both", "none"]
    p: float
    p_adjusted: float
    n_people_off: int
    n_layouts_off: int
    testable: bool
    flagged: bool


class InstrumentPositions(BaseModel):
    """The answer for one instrument, with the positions behind it."""

    instrument_id: str
    answer: Answer
    words: str
    reason: Literal["flagged", "too_few_runs", "one_person_one_layout", "none_beats_chance"]
    n_runs: int
    n_people: int
    n_layouts: int
    n_positions_tested: int
    n_positions_testable: int
    runs_needed: int | None
    flagged: list[str]
    beats_chance: list[str]
    positions: list[PositionStat]


class PositionReport(BaseModel):
    """Position history of every instrument given (JSON-stable; floats rounded)."""

    n_residuals: int
    n_off: int
    base_rate: float | None
    off_cycles: float
    alpha: float
    min_people_or_layouts: int
    min_replicates: int
    instruments: list[InstrumentPositions]
    facts: dict[str, Fact] = Field(default_factory=dict)


def _r(value: float) -> float:
    return round(float(value), 10)


def adjusted_p(n_off: int, n_runs: int, base_rate: float, n_positions: int) -> float:
    """Bonferroni-adjusted one-sided binomial p of ``n_off`` off in ``n_runs`` at a position."""
    if n_off <= 0:
        return 1.0
    p = float(stats.binom.sf(n_off - 1, n_runs, base_rate))
    return min(1.0, p * n_positions)


def runs_needed(base_rate: float, n_positions: int, alpha: float = ALPHA) -> int | None:
    """Smallest k for which k of k runs off beats chance after the correction (None: never)."""
    if n_positions <= 0 or base_rate >= 1:
        return None
    if base_rate <= 0:
        return 1
    for k in range(1, MAX_RUNS_NEEDED + 1):
        if n_positions * base_rate**k < alpha:
            return k
    return None


def residuals(runs: Sequence[RunWells], *, min_replicates: int = MIN_REPLICATES) -> pd.DataFrame:
    """One row per well with a Cq in a replicate group: residual against the group median.

    Columns: ``instrument_id, run_id, position, sample, target, residual, operator, layout``.
    """
    rows: list[dict[str, Any]] = []
    for run in runs:
        groups: dict[tuple[str, str], list[WellReading]] = defaultdict(list)
        for well in run.wells:
            if well.cq is not None and math.isfinite(well.cq):
                groups[(well.sample, well.target)].append(well)
        layout = run.layout_key()
        for (_, _), wells in sorted(groups.items()):
            if len(wells) < min_replicates:
                continue
            median = float(np.median([w.cq for w in wells]))
            for w in sorted(wells, key=lambda x: well_order(x.well)):
                rows.append(
                    {
                        "instrument_id": run.instrument_id,
                        "run_id": run.run_id,
                        "position": w.well,
                        "sample": w.sample,
                        "target": w.target,
                        "residual": float(w.cq) - median,
                        "operator": run.operator,
                        "layout": layout,
                    }
                )
    columns = ["instrument_id", "run_id", "position", "sample", "target", "residual"]
    return pd.DataFrame(rows, columns=[*columns, "operator", "layout"])


def _side(values: Sequence[float]) -> str:
    if not len(values):
        return "none"
    below, above = any(v < 0 for v in values), any(v > 0 for v in values)
    return "both" if below and above else "below" if below else "above"


def _instrument(
    instrument_id: str,
    table: pd.DataFrame,
    runs: Sequence[RunWells],
    base_rate: float,
    *,
    off_cycles: float,
    alpha: float,
    min_people_or_layouts: int,
) -> InstrumentPositions:
    mine = [r for r in runs if r.instrument_id == instrument_id]
    people = {r.operator for r in mine if r.operator}
    layouts = {r.layout_key() for r in mine}
    positions = sorted(set(table["position"]), key=well_order)
    m = len(positions)
    need = runs_needed(base_rate, m, alpha)
    stats_out: list[PositionStat] = []
    for position in positions:
        rows = table[table["position"] == position]
        off = rows[rows["residual"].abs() > off_cycles]
        n, x = len(rows), len(off)
        p_raw = float(stats.binom.sf(x - 1, n, base_rate)) if x else 1.0
        p_adj = adjusted_p(x, n, base_rate, m)
        n_people = len({o for o in off["operator"] if isinstance(o, str) and o})
        n_layouts = len(set(off["layout"]))
        spread = max(n_people, n_layouts) >= min_people_or_layouts
        stats_out.append(
            PositionStat(
                position=position,
                n_runs=n,
                n_off=x,
                median_residual=_r(np.median(rows["residual"])),
                side=_side(list(off["residual"])),  # type: ignore[arg-type]
                p=_r(p_raw),
                p_adjusted=_r(p_adj),
                n_people_off=n_people,
                n_layouts_off=n_layouts,
                testable=need is not None and n >= need,
                flagged=p_adj < alpha and spread,
            )
        )
    flagged = [s.position for s in stats_out if s.flagged]
    beats = [s.position for s in stats_out if s.p_adjusted < alpha]
    testable = sum(s.testable for s in stats_out)
    if flagged:
        answer, reason = "follows_instrument", "flagged"
    elif beats:
        answer, reason = "not_enough_runs", "one_person_one_layout"
    elif not testable:
        answer, reason = "not_enough_runs", "too_few_runs"
    else:
        answer, reason = "moves_with_samples", "none_beats_chance"
    return InstrumentPositions(
        instrument_id=instrument_id,
        answer=answer,  # type: ignore[arg-type]
        words=WORDS[answer],
        reason=reason,  # type: ignore[arg-type]
        n_runs=len(mine),
        n_people=len(people),
        n_layouts=len(layouts),
        n_positions_tested=m,
        n_positions_testable=testable,
        runs_needed=need,
        flagged=flagged,
        beats_chance=beats,
        positions=stats_out,
    )


def position_history(
    runs: Sequence[RunWells],
    *,
    min_people_or_layouts: int = 2,
    off_cycles: float = OFF_CYCLES,
    alpha: float = ALPHA,
    min_replicates: int = MIN_REPLICATES,
) -> PositionReport:
    """Whether odd wells follow each instrument or move with the samples (on demand).

    Args:
        runs: The runs to pool, each tagged with its instrument (the base rate is pooled over
            all of them: the lab's own replicate noise).
        min_people_or_layouts: How many people or plate layouts a flagged position's off runs
            must span.
        off_cycles: A well is off when its residual is larger than this, in cycles.
        alpha: Family-wise level per instrument (Bonferroni over its positions).
        min_replicates: Smallest replicate group (wells with a Cq) that gives residuals.

    Returns:
        A :class:`PositionReport` with one answer per instrument, sorted by instrument id.
    """
    if min_people_or_layouts < 1 or min_replicates < 2:
        raise ValueError("min_people_or_layouts must be at least 1 and min_replicates at least 2")
    table = residuals(runs, min_replicates=min_replicates)
    n = len(table)
    n_off = int((table["residual"].abs() > off_cycles).sum()) if n else 0
    base_rate = n_off / n if n else None
    instruments = []
    for instrument_id in sorted({r.instrument_id for r in runs}):
        rows = table[table["instrument_id"] == instrument_id]
        if base_rate is None or not len(rows):
            instruments.append(_empty(instrument_id, runs))
            continue
        instruments.append(
            _instrument(
                instrument_id,
                rows,
                runs,
                base_rate,
                off_cycles=off_cycles,
                alpha=alpha,
                min_people_or_layouts=min_people_or_layouts,
            )
        )
    report = PositionReport(
        n_residuals=n,
        n_off=n_off,
        base_rate=_r(base_rate) if base_rate is not None else None,
        off_cycles=off_cycles,
        alpha=alpha,
        min_people_or_layouts=min_people_or_layouts,
        min_replicates=min_replicates,
        instruments=instruments,
    )
    return report.model_copy(update={"facts": position_facts(report)})


def _empty(instrument_id: str, runs: Sequence[RunWells]) -> InstrumentPositions:
    mine = [r for r in runs if r.instrument_id == instrument_id]
    return InstrumentPositions(
        instrument_id=instrument_id,
        answer="not_enough_runs",
        words=WORDS["not_enough_runs"],
        reason="too_few_runs",
        n_runs=len(mine),
        n_people=len({r.operator for r in mine if r.operator}),
        n_layouts=len({r.layout_key() for r in mine}),
        n_positions_tested=0,
        n_positions_testable=0,
        runs_needed=None,
        flagged=[],
        beats_chance=[],
        positions=[],
    )


def runs_from_curves(
    curves: pd.DataFrame,
    instruments: Mapping[str, str],
    *,
    operators: Mapping[str, str] | None = None,
) -> list[RunWells]:
    """Runs of a per-well table, tagged with their instrument (runs not in the map are left out).

    Sample and standard wells only (never NTC wells); ``cq`` is the engine Cq.
    """
    out = []
    table = curves[curves["sample_type"].isin(STUDY_TYPES)]
    for run_id, rows in table.groupby(table["run_id"].astype(str), sort=True):
        if run_id not in instruments:
            continue
        wells = [
            WellReading(
                well=str(w),
                sample=str(s),
                target=str(t),
                cq=None if pd.isna(c) else float(c),
            )
            for w, s, t, c in zip(
                rows["well"], rows["sample"], rows["target"], rows["cq"], strict=True
            )
        ]
        out.append(
            RunWells(
                run_id=run_id,
                instrument_id=instruments[run_id],
                operator=(operators or {}).get(run_id),
                wells=wells,
            )
        )
    return out


def position_history_store(
    store: StudyStore,
    runs: Mapping[str, str],
    *,
    studies: Sequence[str] | None = None,
    operators: Mapping[str, str] | None = None,
    min_people_or_layouts: int = 2,
) -> PositionReport:
    """Position history over the runs of stored studies (read-only), on demand.

    ``runs`` maps run ids to instrument ids, as for a lookback; runs not in it are left out.
    A study whose input file another study already used (the same file under another design)
    is skipped, so no run counts twice. Studies whose input file is missing are skipped.
    """
    from qpilot.core.store import StudyNotFound
    from qpilot.qpcr.lookback import load_study

    seen: set[str] = set()
    pooled: list[RunWells] = []
    for study_id in sorted(set(store.list_studies() if studies is None else studies)):
        try:
            digest = store.get(study_id).input_sha256
            if digest in seen:
                continue
            curves, _, _ = load_study(store, study_id)
        except (StudyNotFound, FileNotFoundError):
            continue
        seen.add(digest)
        pooled += runs_from_curves(curves, runs, operators=operators)
    return position_history(pooled, min_people_or_layouts=min_people_or_layouts)


def position_facts(report: PositionReport) -> dict[str, Fact]:
    """Every number and label position-history prose may show (``f_position_*``)."""
    reg = FactRegistry()

    def add(fid: str, value: Any, path: str, fmt: str = "{}") -> None:
        reg.add(Fact(id=fid, value=value, fmt=fmt, path=path))

    if report.base_rate is not None:
        add("f_position_base_rate", report.base_rate, "position.base_rate", "{:.1%}")
    add("f_position_n_residuals", report.n_residuals, "position.n_residuals", "{:,}")
    reg.add(
        Fact(
            id="f_position_off_cycles",
            value=report.off_cycles,
            fmt="{:g}",
            unit=" cycles",
            path="position.off_cycles",
        )
    )
    for i, inst in enumerate(report.instruments):
        p, at = f"f_position_{slug(inst.instrument_id)}", f"position.instruments[{i}]"
        add(f"{p}_instrument", inst.instrument_id, f"{at}.instrument_id")
        add(f"{p}_n_runs", inst.n_runs, f"{at}.n_runs")
        add(f"{p}_n_positions", inst.n_positions_tested, f"{at}.n_positions_tested")
        add(f"{p}_n_testable", inst.n_positions_testable, f"{at}.n_positions_testable")
        if inst.runs_needed is not None:
            add(f"{p}_runs_needed", inst.runs_needed, f"{at}.runs_needed")
        if inst.flagged:
            add(f"{p}_flagged", ", ".join(inst.flagged), f"{at}.flagged")
        if inst.beats_chance:
            add(f"{p}_beats_chance", ", ".join(inst.beats_chance), f"{at}.beats_chance")
    return reg.as_dict()


__all__ = [
    "WORDS",
    "InstrumentPositions",
    "PositionReport",
    "PositionStat",
    "RunWells",
    "WellReading",
    "adjusted_p",
    "position_facts",
    "position_history",
    "position_history_store",
    "residuals",
    "runs_from_curves",
    "runs_needed",
]
