"""Melt route: each well's melt curve (−dF/dT), its peaks, and where its assay's product melts.

``GET /studies/{id}/melt`` and ``GET /sessions/{sid}/melt`` answer, for one plate (``run``, by
default the first plate with melt curves), every assay (target) on it with its expected melting
temperature, the spread of its study wells' Tm and each well's call, and, for the wells asked
for (``wells=A1,B2``, at most twelve), the curves: the file's readings and −dF/dT with its
counted peaks. The maths is :mod:`qpilot.qpcr.melt` (``methods/melt_curve.md``) and the
thresholds are the shipped pack's rule G-MELT, so these calls are the ones the Run Gate weighs.

A study (analysed outside Studio, or a session's analysis) follows the results' blind rule (403
``blind`` until the design and the curves are confirmed); a session's own melt curves are judged
against its design, so they wait for the design to be confirmed (409 ``studio``). A melt curve
shows a product's identity, never a group: nothing here names a group. A file without melt
curves answers ``has_melt: false`` with what to export. GETs never write.
"""

from __future__ import annotations

import re
import threading
from collections import OrderedDict
from typing import Any

from fastapi import APIRouter, Query

from qpilot.qpcr import melt as M
from qpilot.web.context import AppContext, Ctx, api_error
from qpilot.web.contract_melt import (
    MeltAssayView,
    MeltCallView,
    MeltParamsView,
    MeltPeakView,
    MeltTargetView,
    MeltView,
    MeltWellView,
)

router = APIRouter(tags=["melt"])

MAX_WELLS = 12
KEEP = 16
WELL = re.compile(r"^[A-Z]{1,3}[1-9][0-9]{0,2}\Z")
NO_MELT = (
    "This file has no melt curves. For SYBR Green or another DNA-binding dye, export the melt "
    "curves with the amplification (CFX: Melt Curve RFU Results; QuantStudio: Melt Curve Raw "
    "Data; or an RDML file with its melt data) and open them together."
)
NO_MELT_PLATE = "This plate has no melt curves."
NOT_CONFIRMED = (
    "Melt curves are judged against the design (which wells are study samples and which are "
    "controls): confirm the design first."
)
NO_SOURCE = "The study's input file is missing or has changed, so its melt curves cannot be read."
CAVEAT = (
    "A single peak at the expected temperature does not guarantee that it is the intended "
    "amplicon (MIQE 2.0)."
)
STATUS_TEXT: dict[str, str] = {
    "one_product": "One product at the expected temperature",
    "extra_peak": "An extra peak beside the product",
    "tm_off": "No product at the expected temperature",
    "no_peak": "Amplified, but no melt peak",
    "not_amplified": "Did not amplify: not judged",
    "no_product": "No-template control: nothing melted",
    "product": "No-template control: a peak at the product's temperature (contamination candidate)",
    "dimer": "No-template control: a primer-dimer candidate",
    "other_product": "No-template control: another product",
    "unclassified": "A peak, but the product's temperature is not known on this plate",
    "not_judged": "This kind of control is not judged by its melt",
    "unreadable": "Too few readings, or readings too far apart, to judge",
    "no_melt": "No melt curve",
}

_lock = threading.Lock()
_kept: OrderedDict[tuple[Any, ...], tuple[M.MeltData, list[M.AssayMelt]]] = OrderedDict()


def _pack() -> tuple[M.MeltParams, str]:
    """The shipped pack's G-MELT thresholds and the pack's name and version."""
    from qpilot.qpcr.gate_rules import melt_params, resolve_pack

    pack = resolve_pack()
    return melt_params(pack), f"{pack.pack} {pack.version}"


def _judged(key: tuple[Any, ...], work) -> tuple[M.MeltData, list[M.AssayMelt]]:
    with _lock:
        if key in _kept:
            _kept.move_to_end(key)
            return _kept[key]
    done = work()
    with _lock:
        _kept[key] = done
        while len(_kept) > KEEP:
            _kept.popitem(last=False)
    return done


def clear() -> None:
    """Forget every kept answer (tests)."""
    with _lock:
        _kept.clear()
    M.clear()


def _wells(wells: str | None) -> list[str]:
    names = [w.strip() for w in (wells or "").split(",") if w.strip()]
    for name in names:
        if not WELL.match(name):
            raise api_error(422, "bad_request", f"{name[:12]!r} is not a well name such as A1.")
    return list(dict.fromkeys(names))[:MAX_WELLS]


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(float(value), digits)


def _call_view(w: M.WellCall) -> MeltCallView:
    main = w.main
    return MeltCallView(
        key=w.key,
        run_id=w.run_id,
        well=w.well,
        sample=w.sample,
        target=w.target,
        sample_type=w.sample_type,
        status=w.status,
        status_text=STATUS_TEXT[w.status],
        flagged=w.flagged,
        main_tm=_round(main.tm) if main is not None else None,
        offset_c=_round(w.offset),
        n_peaks=len(w.peaks),
    )


def _well_view(w: M.WellCall) -> MeltWellView:
    melt = w.melt
    extra = set(w.extra)
    peaks = [
        MeltPeakView(
            tm=round(p.tm, 4),
            height=round(p.height, 6),
            share=round(s, 6),
            width_c=p.width_c,
            role="main" if i == 0 else "extra" if p in extra else "minor",
        )
        for i, (p, s) in enumerate(zip(w.peaks, w.shares, strict=True))
    ]
    return MeltWellView(
        **_call_view(w).model_dump(),
        amplified=w.amplified,
        cq=_round(w.cq),
        peaks=peaks,
        readings_temperature=list(melt.curve.temperature) if melt else [],
        readings_fluorescence=[
            v if v == v else None for v in (melt.curve.fluorescence if melt else ())
        ],
        temperature=list(melt.temperature) if melt else [],
        derivative=list(melt.derivative) if melt else [],
        step_c=melt.step_c if melt else None,
        problem=melt.problem if melt else "",
    )


def _assay_summary(a: M.AssayMelt, counts: dict[str, int]) -> str:
    flagged = sum(counts.get(s, 0) for s in (*M.STUDY_FLAGS, *M.NTC_FLAGS))
    if a.coarse:
        return "The melt readings are too far apart to place a melting temperature."
    if a.expected_tm is None and not any(w.sample_type in M.JUDGED for w in a.with_melt):
        return (
            "Only no-template controls of this target here: a peak in them is measured against "
            "the plate's other products."
        )
    if a.expected_tm is None:
        return (
            "Too few study wells melted here to say where the product melts, and the file "
            "declares no temperature: only extra peaks are judged."
        )
    if not flagged:
        return "Every amplified study well melts as one product at the expected temperature."
    if flagged == 1:
        return "One well is flagged: open it to see its melt curve."
    return "Some wells are flagged: open them to see their melt curves."


def _assay_view(a: M.AssayMelt) -> MeltAssayView:
    counts: dict[str, int] = {}
    for w in a.wells:
        if w.melt is not None:
            counts[w.status] = counts.get(w.status, 0) + 1
    return MeltAssayView(
        run_id=a.run_id,
        target=a.target,
        expected_tm=_round(a.expected_tm),
        expected_source=a.expected_source,  # type: ignore[arg-type]
        n_reference=len(a.reference),
        median_tm=_round(a.median_tm),
        min_tm=_round(a.min_tm),
        max_tm=_round(a.max_tm),
        spread_c=_round(a.spread_c),
        noise_floor=_round(a.noise_floor, 6),
        step_c=_round(a.step_c),
        n_wells=len(a.with_melt),
        counts=counts,
        flagged=sorted(w.key for w in a.wells if w.flagged),
        summary=_assay_summary(a, counts),
    )


def _view(
    key: str,
    study_id: str | None,
    data: M.MeltData,
    assays: list[M.AssayMelt],
    params: M.MeltParams,
    pack: str,
    run: str | None,
    wells: list[str],
) -> MeltView:
    base = {
        "key": key,
        "study_id": study_id,
        "params": MeltParamsView(**params.__dict__),
        "pack": pack,
        "method": M.METHOD_CARD,
        "caveat": CAVEAT,
    }
    if not data.has_melt:
        return MeltView(
            **base,
            has_melt=False,
            message=NO_MELT,
            plates=[],
            assays=[],
            targets=[],
            calls=[],
            wells=[],
        )
    plates = list(dict.fromkeys(a.run_id for a in assays))
    shown = run if run is not None else (plates[0] if plates else None)
    mine = [a for a in assays if a.run_id == shown]
    calls = [w for a in mine for w in a.wells if w.melt is not None]
    asked = set(wells)
    return MeltView(
        **base,
        has_melt=True,
        message="" if mine else NO_MELT_PLATE,
        run=shown,
        plates=plates,
        assays=[_assay_view(a) for a in mine],
        targets=[MeltTargetView(**t.__dict__) for t in M.target_summaries(assays)],
        calls=[_call_view(w) for w in calls],
        wells=[_well_view(w) for w in calls if w.well in asked],
    )


# ---- a study ---------------------------------------------------------------------------------


def study_melt(ctx: AppContext, study_id: str) -> tuple[M.MeltData, list[M.AssayMelt]]:
    """A stored study's melt curves, judged on its design's per-well table (kept per file)."""
    from qpilot.qpcr.study import StudySettings

    source = ctx.store.source(study_id)
    if source is None:
        raise api_error(409, "no_source", NO_SOURCE)
    design = ctx.store.design(study_id)
    settings = StudySettings.from_design(design) if design is not None else StudySettings()
    params, _ = _pack()
    st = source.stat()
    key = ("study", str(source), st.st_mtime_ns, st.st_size, study_id, params)
    return _judged(key, lambda: _study_work(source, settings, params))


def _study_work(source: Any, settings: Any, params: M.MeltParams):
    from qpilot.io.rdml_io import RdmlLoadError
    from qpilot.qpcr.curves import CurveAnalysisError

    try:
        return M.study_melt(source, settings, params)
    except (M.MeltError, RdmlLoadError, CurveAnalysisError, OSError) as err:
        raise api_error(409, "melt", f"The melt curves could not be read: {err}") from err


@router.get("/studies/{study_id}/melt", response_model=MeltView)
def get_study_melt(
    study_id: str,
    ctx: Ctx,
    run: str | None = Query(default=None, max_length=128, description="The plate to show."),
    wells: str | None = Query(
        default=None, max_length=800, description="Wells of that plate, e.g. `A1,B2`."
    ),
) -> MeltView:
    """A study's melt curves: one plate's assays and calls, and the curves of the wells asked."""
    from qpilot.web.routers.results import study

    study(ctx, study_id)
    names = _wells(wells)
    data, assays = study_melt(ctx, study_id)
    params, pack = _pack()
    return _view(study_id, study_id, data, assays, params, pack, run, names)


# ---- a session -------------------------------------------------------------------------------


@router.get("/sessions/{sid}/melt", response_model=MeltView)
def get_session_melt(
    sid: str,
    ctx: Ctx,
    run: str | None = Query(default=None, max_length=128, description="The plate to show."),
    wells: str | None = Query(
        default=None, max_length=800, description="Wells of that plate, e.g. `A1,B2`."
    ),
) -> MeltView:
    """A session's melt curves, judged on its confirmed design (409 until it is confirmed)."""
    from qpilot.web import studio_views as sv
    from qpilot.web.routers.studio import call, session

    session(ctx, sid)
    names = _wells(wells)
    _, assembly, stages = call(sv.read_session, ctx.studio, sid)
    design = assembly.design
    curves = stages.get("curves")
    if design is None or curves is None or not curves.open:
        raise api_error(409, "studio", NOT_CONFIRMED)
    source = ctx.studio.source(sid)
    params, pack = _pack()
    st = source.stat()
    key = ("session", str(source), st.st_mtime_ns, st.st_size, design.design_hash(), params)

    def work():
        try:
            data = M.read_melt(source, design.experiment_id)
        except M.MeltError as err:
            raise api_error(409, "melt", f"The melt curves could not be read: {err}") from err
        if not data.has_melt:
            return data, []
        table = sv._designed_table(ctx.studio, sid, design)
        if table is None:
            raise api_error(409, "studio", "The design's wells could not be read from the file.")
        return data, M.judge(table, data, params)

    data, assays = _judged(key, work)
    return _view(sid, None, data, assays, params, pack, run, names)
