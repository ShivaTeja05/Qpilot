"""Quantities routes: standard curves, LOD/LOQ and every unknown's absolute quantity.

* ``GET /api/studies/{id}/quantities`` (:func:`qpilot.web.absolute_views.quantities_view`):
  every assay with standards, its curves' numbers and how many units it quantified;
* ``GET /api/studies/{id}/quantities/{target}``: one assay's curves in full (points, levels,
  the 95 % prediction band) and every biological unit's quantity with its interval and flags;
* ``POST /api/studies/{id}/quantities/reaction``: a person records what one reaction held
  (template µL, input ng), for quantities per µL and per ng: a ``choice.reaction_input``
  made and accepted by the person in one act, in the session's hash-chained inbox; the design
  changes, so the study is analysed again (the blind stages stay confirmed);
* ``GET /api/tools/copies``: ng of a standard to copies (dsDNA, ssDNA, RNA) and its dilution
  series, for preparing standards (the Design page's helper; no study needed).

Blind like Results: a Studio session's study answers ``403 blind`` until its design and curves
are confirmed. Every number is the engine's (:mod:`qpilot.qpcr.absolute`).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from qpilot.web.context import Ctx, api_error
from qpilot.web.contract_absolute import (
    AssayQuantities,
    CopiesAnswer,
    QuantitiesView,
    ReactionRecorded,
    ReactionRequest,
)

router = APIRouter(tags=["results"])

NO_ASSAY = "This study has no standard curve for this assay."
UNAVAILABLE = (
    "The quantities cannot be shown: {reason}. They are computed from the study's input file, "
    "as the analysis was."
)
ONLY_SESSION = (
    "What one reaction held is recorded in a Studio session's decision record; this study was "
    "analysed outside one."
)
FORMULA = (
    "copies = ng × 10⁻⁹ g/ng × 6.02214076 × 10²³ /mol ÷ molar mass (g/mol); molar mass: dsDNA "
    "bp × 617.96 + 36.04, ssDNA nt × 308.97 + 18.02, ssRNA nt × 320.5 + 159.0"
)
COPIES_REFERENCE = "Thermo Fisher Scientific, DNA and RNA molecular weights and conversions"


def _unavailable(err: Exception) -> Exception:
    reason = str(err).rstrip(".")
    return api_error(409, "unavailable", UNAVAILABLE.format(reason=reason))


@router.get("/studies/{study_id}/quantities", response_model=QuantitiesView)
def get_quantities(study_id: str, ctx: Ctx) -> QuantitiesView:
    """The study's standard curves and how many units each assay quantified."""
    from qpilot.qpcr.absolute_study import QuantitiesUnavailable
    from qpilot.web.absolute_views import quantities_view
    from qpilot.web.routers.results import study

    sid = study(ctx, study_id)
    try:
        return quantities_view(ctx.store, study_id, can_set_reaction=sid is not None)
    except QuantitiesUnavailable as err:
        raise _unavailable(err) from err


@router.get("/studies/{study_id}/quantities/{target}", response_model=AssayQuantities)
def get_assay_quantities(study_id: str, target: str, ctx: Ctx) -> AssayQuantities:
    """One assay: every curve with its points and prediction band, every unit's quantity."""
    from qpilot.qpcr.absolute_study import QuantitiesUnavailable
    from qpilot.web.absolute_views import assay_view
    from qpilot.web.routers.results import study

    study(ctx, study_id)
    if not target or len(target) > 128:
        raise api_error(404, "not_found", NO_ASSAY)
    try:
        return assay_view(ctx.store, study_id, target)
    except KeyError as err:
        raise api_error(404, "not_found", NO_ASSAY, target=target) from err
    except QuantitiesUnavailable as err:
        raise _unavailable(err) from err


@router.post("/studies/{study_id}/quantities/reaction", response_model=ReactionRecorded)
def post_reaction(study_id: str, body: ReactionRequest, ctx: Ctx) -> ReactionRecorded:
    """A person records the template volume and input amount of one reaction (with a reason)."""
    from qpilot.web.absolute_views import record_reaction
    from qpilot.web.routers.results import changed, writable

    sid = writable(ctx, study_id)
    if sid is None:
        raise api_error(409, "studio", ONLY_SESSION)
    try:
        outcome = record_reaction(
            ctx.studio,
            sid,
            {"template_ul": body.template_ul, "input_ng": body.input_ng, "unit": body.unit},
            body.reason,
            expected_head=body.expected_head,
        )
    except ValueError as err:
        raise api_error(422, "invalid", str(err)) from err
    if outcome.status == "stale":
        raise api_error(
            409,
            "stale",
            "Something was decided since you loaded this (another tab or an agent): read the "
            "quantities again, then record.",
            head=outcome.head,
        )
    if outcome.status == "refused":
        raise api_error(409, "studio", outcome.reason or "the reaction input was refused")
    changed(ctx, study_id, sid)
    return ReactionRecorded(
        status=outcome.status,
        head=outcome.head,
        message="Recorded. The study is analysed again with it; the quantities per µL and per ng "
        "follow.",
    )


@router.get("/tools/copies", response_model=CopiesAnswer)
def get_copies(
    ng: float = Query(gt=0, lt=1e12, description="ng of the standard (or ng per µL)."),
    length: float = Query(gt=0, lt=1e9, description="Bases (dsDNA: base pairs)."),
    kind: Literal["dsDNA", "ssDNA", "RNA"] = "dsDNA",
    step: float | None = Query(default=None, gt=1, lt=1e6, description="Dilution step."),
    levels: int = Query(default=0, ge=0, le=24, description="Levels of the series."),
) -> CopiesAnswer:
    """How many copies ``ng`` of a ``length``-long molecule hold, and its dilution series."""
    from qpilot.qpcr import absolute as ab

    try:
        copies = ab.copies_from_mass(ng, length, kind)
        series = ab.dilution_levels(copies, step, levels) if step and levels else []
    except ab.AbsoluteError as err:
        raise api_error(422, "invalid", str(err)) from err
    mass = ab.molar_mass(length, kind)
    return CopiesAnswer(
        kind=kind,
        kind_words=ab.KIND_WORDS[kind],
        length=length,
        ng=ng,
        molar_mass=mass,
        copies=copies,
        copies_per_ng=copies / ng,
        formula=FORMULA,
        series=series,
        reference=COPIES_REFERENCE,
    )
