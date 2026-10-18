"""Lookback: which conclusions used an instrument's runs in a time window, and does it matter.

Given which instrument each run came from (``runs``: run id -> instrument id) and a window
(an incident, a service visit, an expired calibration), :func:`lookback` lists every study, run
and well from that instrument in the window and, for each study, analyses it again with those
runs left out. The answer per study is "changes k of N conclusions", with the genes.

**What is compared.** Before: the study's primary analysis (the engine's recommended choice
in every dimension) on all its runs. After: the robustness grid run again on the runs outside
the window (:func:`qpilot.core.robustness.run_grid` and ``summary``), whose conclusion per
gene is its primary cell. ``k`` counts the genes concluded both times whose call (up, down,
none) differs; ``N`` is the number of conclusions before. Decided cards are not applied: the
comparison is between primary analyses, and says so (``basis``).

**What a whole run carries.** On a plate that holds one gene (the demo: 64 plates, one gene
each) leaving a run out leaves its gene out, so three cases are handled on their own and never
dropped silently:

* a gene measured only in the window is **no longer concluded**: listed separately, not
  counted in ``k`` (it did not change; it is gone);
* a control-gene candidate measured only in the window: the study is analysed again with the
  other candidates (the engine needs every candidate in the matrix), which also derives the
  marker groups again; the result says so (``candidates_in_window``, ``groups``);
* the grouping marker measured only in the window: the samples cannot be grouped, so the study
  reads "cannot evaluate: the grouping marker was measured in the window".

**Run dates.** In this order: dates the caller gives (``run_dates``), the start date (UTC) of a
stored run context (``run_context.json`` in the workspace), else the date in the run name
(``_20YYMMDD``, the only date the demo file has). Each run says which (``date_source``); a run
mapped to the instrument with no date is listed as undated and is not in any window.

Read-only: nothing is written to the store or to any logbook (the curve cache is read when it
exists and never filled). :func:`write_lookback` appends the result to an instrument's logbook
as a hash-chained ``lookback`` event when a caller asks for it. Deterministic: the same inputs
give the same bytes. Research use only.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
from collections.abc import Collection, Iterable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

from qpilot.core import robustness
from qpilot.core.facts import FactRegistry, slug
from qpilot.core.store import StudyNotFound, canonical_json
from qpilot.schemas import Conclusion, Fact

if TYPE_CHECKING:
    from qpilot.core.instruments import Logbook, LogEvent
    from qpilot.core.store import StudyStore
    from qpilot.qpcr.study import StudyModel, StudySettings

RUN_NAME_DATE = re.compile(r"_(?P<y>20\d{2})(?P<m>\d{2})(?P<d>\d{2})(?=_|$)")
RUN_CONTEXT_FILE = "run_context.json"
MAX_CONTEXT_BYTES = 4 << 20
BASIS = "primary analysis before and after; decided cards are not applied"

DateSource = Literal["given", "run context", "run name"]
Status = Literal["evaluated", "cannot_evaluate", "no_runs_in_window"]

#: Why a study cannot be evaluated: a fixed, digit-free sentence per reason code.
REASONS = {
    "marker_in_window": "cannot evaluate: the grouping marker was measured in the window",
    "no_control_gene_left": (
        "cannot evaluate: every control-gene candidate was measured in the window"
    ),
    "all_runs_in_window": "cannot evaluate: every run of this study is in the window",
    "input_missing": "cannot evaluate: the study's input file is not known or has changed",
    "unknown_study": "cannot evaluate: there is no such study in this store",
    "engine_refused": ("cannot evaluate: the engine cannot analyse this study without these runs"),
}


class LookbackError(ValueError):
    """The window or the run mapping cannot be used."""


# ---- results --------------------------------------------------------------------------------


class LookbackRun(BaseModel):
    """One run from the instrument in the window: its date, where the date came from, wells."""

    study_id: str
    run_id: str
    date: str
    date_source: DateSource
    targets: list[str]
    n_wells: int
    wells: list[str]


class GeneChange(BaseModel):
    """One gene whose call differs once the window's runs are left out."""

    gene: str
    before: Conclusion
    after: Conclusion
    log2fc_before: float | None
    log2fc_after: float | None
    p_before: float | None
    p_after: float | None
    holds_before: float | None
    holds_after: float | None


class StudyLookback(BaseModel):
    """What leaving one study's in-window runs out does to its conclusions."""

    study_id: str
    status: Status
    reason: str | None = None  # a key of REASONS when the status is cannot_evaluate
    detail: str | None = None  # the engine's refusal, for engine_refused
    n_runs: int = 0
    runs_in_window: list[str] = Field(default_factory=list)
    n_wells_in_window: int = 0
    undated_runs: list[str] = Field(default_factory=list)
    n_conclusions: int = 0
    n_changed: int = 0
    changed: list[GeneChange] = Field(default_factory=list)
    no_longer_concluded: list[str] = Field(default_factory=list)
    newly_concluded: list[str] = Field(default_factory=list)
    candidates_before: list[str] = Field(default_factory=list)
    candidates_after: list[str] = Field(default_factory=list)
    candidates_in_window: list[str] = Field(default_factory=list)
    marker: str | None = None
    groups: dict[str, Any] = Field(default_factory=dict)
    grid_cells: dict[str, int] = Field(default_factory=dict)
    baseline_matches_stored: bool | None = None
    basis: str = BASIS

    @property
    def changed_genes(self) -> list[str]:
        """The genes counted in ``n_changed``, sorted."""
        return [c.gene for c in self.changed]


class LookbackResult(BaseModel):
    """Every study, run and well from one instrument in a window, and what leaving them out does.

    JSON-stable: floats are rounded to ten places and NaN becomes null, so the same inputs give
    the same bytes (:meth:`canonical`).
    """

    instrument_id: str
    start: str
    end: str
    runs: list[LookbackRun]
    studies: list[StudyLookback]
    n_studies_in_window: int
    n_runs_in_window: int
    n_wells_in_window: int
    n_changed: int
    facts: dict[str, Fact]

    def canonical(self) -> str:
        """The one JSON form of the result (sorted keys, no spaces); what a lookback hashes."""
        return canonical_json(self.model_dump(mode="json"))

    def sha256(self) -> str:
        """sha256 of :meth:`canonical`."""
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()


# ---- dates and the window -------------------------------------------------------------------


def run_name_date(run_id: str) -> date | None:
    """The date in a run name (``HMBS_20080318`` -> 18 Mar 2008), or None.

    Day precision, time zone unknown: a date someone typed into a name, never an instrument
    fact.
    """
    match = RUN_NAME_DATE.search(run_id)
    if not match:
        return None
    try:
        return date(int(match["y"]), int(match["m"]), int(match["d"]))
    except ValueError:
        return None


def _day(value: Any, what: str) -> date:
    """An ISO date or date-time as a calendar date (a date-time's date in UTC)."""
    if not isinstance(value, str) or not value.strip():
        raise LookbackError(f"{what} must be an ISO date such as 2008-03-18")
    text = value.strip()
    try:
        if len(text) == 10:
            return date.fromisoformat(text)
        moment = datetime.fromisoformat(text)
    except ValueError:
        raise LookbackError(f"{what} {text[:40]!r} is not an ISO date") from None
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC)
    return moment.date()


def _context_dates(data: Any) -> dict[str, tuple[date, DateSource]]:
    """Run start dates from a stored ``run_context.json`` (summaries or full run contexts)."""
    if isinstance(data, Mapping) and isinstance(data.get("runs"), list):
        data = data["runs"]
    if isinstance(data, Mapping):
        items = [{"run_id": k, **v} for k, v in data.items() if isinstance(v, Mapping)]
    elif isinstance(data, list):
        items = [x for x in data if isinstance(x, Mapping)]
    else:
        return {}
    out: dict[str, tuple[date, DateSource]] = {}
    for item in items:
        run_id = item.get("run_id")
        run = item.get("run") if isinstance(item.get("run"), Mapping) else {}
        start = item.get("run_start") or run.get("start")
        if not isinstance(run_id, str) or not isinstance(start, str):
            continue
        try:
            day = _day(start, "run start")
        except LookbackError:
            continue
        named = run.get("date_source") == "run name" or item.get("date_source") == "run name"
        out[run_id] = (day, "run name" if named else "run context")
    return out


def _stored_contexts(store: StudyStore, study_id: str) -> dict[str, tuple[date, DateSource]]:
    getter = getattr(store, "get_artifact", None)
    data: Any = None
    if callable(getter):
        try:
            data = getter(study_id, RUN_CONTEXT_FILE)
        except (KeyError, ValueError, OSError):
            data = None
    if data is None:
        path = store.workspace(study_id) / RUN_CONTEXT_FILE
        if not path.exists() or path.stat().st_size > MAX_CONTEXT_BYTES:
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return _context_dates(data)


def dated_runs(
    run_ids: Iterable[str],
    *,
    given: Mapping[str, str] | None = None,
    contexts: Mapping[str, tuple[date, DateSource]] | None = None,
) -> dict[str, tuple[date, DateSource] | None]:
    """Each run's date and its source (given, run context, run name), or None."""
    out: dict[str, tuple[date, DateSource] | None] = {}
    for run_id in sorted(run_ids):
        if given and run_id in given:
            out[run_id] = (_day(given[run_id], f"the date of run {run_id}"), "given")
        elif contexts and run_id in contexts:
            out[run_id] = contexts[run_id]
        else:
            named = run_name_date(run_id)
            out[run_id] = (named, "run name") if named is not None else None
    return out


# ---- one study ----------------------------------------------------------------------------------


def _num(value: Any) -> float | None:
    if value is None:
        return None
    value = float(value)
    return None if math.isnan(value) else round(value, 10)


def _model(curves: pd.DataFrame, settings: StudySettings) -> tuple[StudyModel, dict, int]:
    """The study's model, its grid summary and the number of grid cells."""
    from qpilot.qpcr.study import build_model

    model = build_model(curves, settings)
    grid = robustness.run_grid(model.space)
    return model, robustness.summary(grid, model.space), robustness.n_cells(model.space)


def _without_runs(settings: StudySettings, runs_out: set[str], candidates: tuple[str, ...]):
    """The settings with fewer candidates and a design that names no well of ``runs_out``."""
    design = settings.design
    if design is not None:

        def keep(key: str) -> bool:
            return key.split("/", 1)[0] not in runs_out

        design = design.model_copy(
            update={
                "well_roles": {k: v for k, v in design.well_roles.items() if keep(k)},
                "well_calls": {k: v for k, v in design.well_calls.items() if keep(k)},
                "excluded_wells": tuple(k for k in design.excluded_wells if keep(k)),
                "reference_candidates": tuple(
                    c for c in design.reference_candidates if c in candidates
                ),
            }
        )
    return dataclasses.replace(settings, candidates=candidates, design=design)


def _groups(model: StudyModel) -> dict[str, int]:
    return {"n_high": len(model.high), "n_rest": len(model.rest)}


def lookback_study(
    curves: pd.DataFrame,
    settings: StudySettings,
    runs_out: Collection[str],
    *,
    study_id: str = "",
    stored: Mapping[str, Any] | None = None,
) -> StudyLookback:
    """What leaving ``runs_out`` out of one study does to its conclusions (no store, no dates).

    Args:
        curves: The study's per-well table (:func:`qpilot.qpcr.curves.analyse_study`).
        settings: The study's settings (``StudySettings.from_design`` or the demo default).
        runs_out: Run ids to leave out.
        study_id: Carried into the result.
        stored: The stored primary contrasts (gene -> ContrastResult), to report whether a
            fresh analysis reproduces them (``baseline_matches_stored``).

    Returns:
        A :class:`StudyLookback` with status ``evaluated`` or ``cannot_evaluate``.
    """
    from qpilot.qpcr.designs import DesignError
    from qpilot.qpcr.study import NGuardError

    out = set(runs_out)
    all_runs = set(curves["run_id"].astype(str))
    inside = curves["run_id"].astype(str).isin(out)
    base = StudyLookback(
        study_id=study_id,
        status="evaluated",
        n_runs=len(all_runs),
        runs_in_window=sorted(out & all_runs),
        n_wells_in_window=int(inside.sum()),
        candidates_before=list(settings.candidates),
        marker=None if settings.groups_mode else settings.marker,
    )
    remaining = curves.loc[~inside]
    gone = set(curves.loc[inside, "target"].astype(str)) - set(remaining["target"].astype(str))
    candidates = tuple(c for c in settings.candidates if c not in gone)
    in_window = [c for c in settings.candidates if c in gone]
    base = base.model_copy(
        update={"candidates_after": list(candidates), "candidates_in_window": in_window}
    )

    def refused(reason: str, detail: str | None = None) -> StudyLookback:
        return base.model_copy(
            update={"status": "cannot_evaluate", "reason": reason, "detail": detail}
        )

    if not len(remaining):
        return refused("all_runs_in_window")
    if not settings.groups_mode and settings.marker in gone:
        return refused("marker_in_window")
    if not candidates:
        return refused("no_control_gene_left")
    before_model, before, cells_before = _model(curves, settings)
    before_calls = before_model.space.evaluate(before_model.space.primary)
    try:
        after_settings = _without_runs(settings, out, candidates)
        after_model, after, cells_after = _model(remaining, after_settings)
    except (DesignError, NGuardError, ValueError, KeyError) as err:
        return refused("engine_refused", f"{type(err).__name__}: {err}"[:300])
    after_calls = after_model.space.evaluate(after_model.space.primary)
    both = sorted(set(before) & set(after))
    changed = [
        GeneChange(
            gene=g,
            before=before[g].conclusion,
            after=after[g].conclusion,
            log2fc_before=_num(before_calls[g].log2fc),
            log2fc_after=_num(after_calls[g].log2fc),
            p_before=_num(before_calls[g].p),
            p_after=_num(after_calls[g].p),
            holds_before=_num(before[g].holds),
            holds_after=_num(after[g].holds),
        )
        for g in both
        if before[g].conclusion != after[g].conclusion
    ]
    matches = None
    if stored is not None:
        matches = set(stored) == set(before_calls) and all(
            (stored[g].fc, stored[g].p) == (before_calls[g].fc, before_calls[g].p)
            for g in before_calls
        )
    return base.model_copy(
        update={
            "n_conclusions": len(before),
            "n_changed": len(changed),
            "changed": changed,
            "no_longer_concluded": sorted(set(before) - set(after)),
            "newly_concluded": sorted(set(after) - set(before)),
            "groups": {
                "before": _groups(before_model),
                "after": _groups(after_model),
                "changed": (before_model.high, before_model.rest)
                != (after_model.high, after_model.rest),
            },
            "grid_cells": {"before": cells_before, "after": cells_after},
            "baseline_matches_stored": matches,
        }
    )


# ---- the store-level entry ----------------------------------------------------------------------


def _check_runs(runs: Any) -> dict[str, str]:
    if not isinstance(runs, Mapping):
        raise LookbackError("runs maps each run id to the id of the instrument it ran on")
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in runs.items()):
        raise LookbackError("runs maps run ids (text) to instrument ids (text)")
    return dict(runs)


def load_study(store: StudyStore, study_id: str) -> tuple[pd.DataFrame, StudySettings, Any]:
    """A stored study's per-well table, settings and stored contrasts, read-only.

    The curve cache is read when it exists and never filled; the workspace is not touched.

    Raises:
        StudyNotFound: No such study.
        FileNotFoundError: The study's input file is not known or has changed.
    """
    from qpilot.io.datasets import default_cache_dir
    from qpilot.qpcr.curves import analyse_study, cache_path
    from qpilot.qpcr.study import StudySettings

    result = store.get(study_id)
    path = store.source(study_id)
    if path is None:
        raise FileNotFoundError(study_id)
    design = store.design(study_id)
    settings = StudySettings.from_design(design) if design is not None else StudySettings()
    cached = cache_path(
        result.input_sha256,
        settings.experiment_id,
        settings.candidates,
        settings.curves,
        default_cache_dir(),
    ).exists()
    curves = analyse_study(
        Path(path), settings.experiment_id, settings.candidates, settings.curves, use_cache=cached
    )
    return curves, settings, result.contrasts


def lookback(
    store: StudyStore,
    runs: Mapping[str, str],
    instrument_id: str,
    start: str,
    end: str,
    *,
    studies: Iterable[str] | None = None,
    run_dates: Mapping[str, str] | None = None,
) -> LookbackResult:
    """Which studies used ``instrument_id`` between ``start`` and ``end``, and what changes.

    Args:
        store: The study store (read only).
        runs: Run id -> instrument id, for the runs whose instrument is known (the same run id
            in two studies is taken to be the same run).
        instrument_id: The instrument whose window this is.
        start: First day of the window (ISO date; a date-time counts by its UTC date).
        end: Last day of the window, inclusive.
        studies: Study ids to check (default: every study in the store).
        run_dates: Run id -> ISO date, overriding the dates qPilot finds itself.

    Returns:
        A :class:`LookbackResult`: every run and well in the window, and per study the
        consequence of leaving them out (or why it cannot be evaluated).

    Raises:
        LookbackError: The window or the run mapping cannot be used.
    """
    mapping = _check_runs(runs)
    first, last = _day(start, "start"), _day(end, "end")
    if first > last:
        raise LookbackError("the window starts after it ends")
    if isinstance(studies, str):
        studies = [studies]
    ids = sorted(set(store.list_studies() if studies is None else studies))
    listed: list[LookbackRun] = []
    results: list[StudyLookback] = []
    for study_id in ids:
        try:
            curves, settings, stored = load_study(store, study_id)
        except StudyNotFound:
            results.append(_unusable(study_id, "unknown_study"))
            continue
        except FileNotFoundError:
            results.append(_unusable(study_id, "input_missing"))
            continue
        except (OSError, ValueError) as err:  # one unreadable study never stops the others
            results.append(_unusable(study_id, "engine_refused", f"{type(err).__name__}: {err}"))
            continue
        ours = sorted(
            r for r in set(curves["run_id"].astype(str)) if mapping.get(r) == instrument_id
        )
        dates = run_dates_for(store, study_id, ours, run_dates)
        undated = [r for r in ours if dates[r] is None]
        window = [r for r in ours if dates[r] is not None and first <= dates[r][0] <= last]
        listed += _listing(study_id, curves, window, dates)
        if not window:
            results.append(
                StudyLookback(
                    study_id=study_id,
                    status="no_runs_in_window",
                    n_runs=int(curves["run_id"].nunique()),
                    undated_runs=undated,
                )
            )
            continue
        one = lookback_study(curves, settings, window, study_id=study_id, stored=stored)
        results.append(one.model_copy(update={"undated_runs": undated}))
    evaluated = [s for s in results if s.runs_in_window]
    result = LookbackResult(
        instrument_id=instrument_id,
        start=first.isoformat(),
        end=last.isoformat(),
        runs=listed,
        studies=results,
        n_studies_in_window=len(evaluated),
        n_runs_in_window=len(listed),
        n_wells_in_window=sum(r.n_wells for r in listed),
        n_changed=sum(s.n_changed for s in results),
        facts={},
    )
    return result.model_copy(update={"facts": lookback_facts(result)})


def run_dates_for(
    store: StudyStore,
    study_id: str,
    run_ids: Iterable[str],
    given: Mapping[str, str] | None = None,
) -> dict[str, tuple[date, DateSource] | None]:
    """The dates of a stored study's runs (given, then run context, then run name)."""
    return dated_runs(run_ids, given=given, contexts=_stored_contexts(store, study_id))


def _unusable(study_id: str, reason: str, detail: str | None = None) -> StudyLookback:
    return StudyLookback(
        study_id=study_id,
        status="cannot_evaluate",
        reason=reason,
        detail=detail[:300] if detail else None,
    )


def _listing(
    study_id: str,
    curves: pd.DataFrame,
    window: list[str],
    dates: Mapping[str, tuple[date, DateSource] | None],
) -> list[LookbackRun]:
    from qpilot.core.instruments import well_order

    out = []
    rows = curves[curves["run_id"].astype(str).isin(window)]
    for run_id, table in rows.groupby(rows["run_id"].astype(str), sort=True):
        day, source = dates[str(run_id)]  # type: ignore[misc]
        wells = sorted(set(table["well"].astype(str)), key=well_order)
        out.append(
            LookbackRun(
                study_id=study_id,
                run_id=str(run_id),
                date=day.isoformat(),
                date_source=source,
                targets=sorted(set(table["target"].astype(str))),
                n_wells=len(table),
                wells=wells,
            )
        )
    return out


# ---- facts and the logbook entry ----------------------------------------------------------------


def lookback_facts(result: LookbackResult) -> dict[str, Fact]:
    """Every number and label lookback prose may show, as facts (``f_lookback_*``)."""
    reg = FactRegistry()

    def add(fid: str, value: Any, path: str, fmt: str = "{}") -> None:
        reg.add(Fact(id=fid, value=value, fmt=fmt, path=path))

    add("f_lookback_instrument", result.instrument_id, "lookback.instrument_id")
    add("f_lookback_start", result.start, "lookback.start")
    add("f_lookback_end", result.end, "lookback.end")
    add("f_lookback_n_studies", result.n_studies_in_window, "lookback.n_studies_in_window")
    add("f_lookback_n_runs", result.n_runs_in_window, "lookback.n_runs_in_window", "{:,}")
    add("f_lookback_n_wells", result.n_wells_in_window, "lookback.n_wells_in_window", "{:,}")
    untouched = sum(s.status == "no_runs_in_window" for s in result.studies)
    add("f_lookback_n_untouched", untouched, "lookback.studies[status=no_runs_in_window]")
    for i, study in enumerate(result.studies):
        p, at = f"f_lookback_{slug(study.study_id)}", f"lookback.studies[{i}]"
        add(f"{p}_study", study.study_id, f"{at}.study_id")
        add(f"{p}_n_runs", len(study.runs_in_window), f"{at}.runs_in_window")
        if study.status != "evaluated":
            if study.marker and study.reason == "marker_in_window":
                add(f"{p}_marker", study.marker, f"{at}.marker")
            continue
        add(f"{p}_n_changed", study.n_changed, f"{at}.n_changed")
        add(f"{p}_n_conclusions", study.n_conclusions, f"{at}.n_conclusions")
        if study.changed:
            add(f"{p}_changed_genes", ", ".join(study.changed_genes), f"{at}.changed")
        if study.no_longer_concluded:
            gone = study.no_longer_concluded
            add(f"{p}_n_gone", len(gone), f"{at}.no_longer_concluded")
            add(f"{p}_gone_genes", ", ".join(gone), f"{at}.no_longer_concluded")
        if study.candidates_in_window:
            add(f"{p}_refs_out", ", ".join(study.candidates_in_window), f"{at}.candidates")
            add(f"{p}_refs_after", ", ".join(study.candidates_after), f"{at}.candidates_after")
    return reg.as_dict()


def write_lookback(logbook: Logbook, result: LookbackResult, actor: str) -> LogEvent:
    """Append a lookback result to its instrument's logbook (a hash-chained ``lookback`` event).

    The entry holds the window, the result's sha256 and, per study, k, N and the genes: enough
    to see later what was concluded about the window, without the well listing.
    """
    if result.instrument_id != logbook.instrument_id:
        raise LookbackError("this lookback is about another instrument")
    studies = [
        {
            "study_id": s.study_id,
            "status": s.status,
            **({"reason": s.reason} if s.reason else {}),
            "n_runs_in_window": len(s.runs_in_window),
            "n_conclusions": s.n_conclusions,
            "n_changed": s.n_changed,
            "changed_genes": s.changed_genes,
            "no_longer_concluded": s.no_longer_concluded,
            "candidates_in_window": s.candidates_in_window,
        }
        for s in result.studies
    ]
    payload = {
        "window": {"start": result.start, "end": result.end},
        "result_sha256": result.sha256(),
        "n_runs_in_window": result.n_runs_in_window,
        "studies": studies,
    }
    return logbook.append(
        {"kind": "lookback", "source": "inferred", "actor": actor, "payload": payload}
    )


__all__ = [
    "REASONS",
    "GeneChange",
    "LookbackError",
    "LookbackResult",
    "LookbackRun",
    "StudyLookback",
    "lookback",
    "lookback_facts",
    "lookback_study",
    "dated_runs",
    "load_study",
    "run_dates_for",
    "run_name_date",
    "write_lookback",
]
