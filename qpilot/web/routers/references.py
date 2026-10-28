"""The reference-gene panel's route: geNorm M and NormFinder's stability side by side.

``GET /api/studies/{id}/references`` (:func:`qpilot.web.references_views.reference_stability`):
every candidate reference gene's geNorm M and NormFinder stability value (with the study's
groups), both best pairs and whether they agree, in plain words. Reads only; it never changes
which reference genes are used. A study of a Studio session answers ``403 blind`` until its
design and curves are confirmed, as Results does.
"""

from __future__ import annotations

from fastapi import APIRouter

from qpilot.web.context import Ctx, api_error
from qpilot.web.contract_norm import ReferenceStability

router = APIRouter(tags=["results"])


@router.get("/studies/{study_id}/references", response_model=ReferenceStability)
def get_references(study_id: str, ctx: Ctx) -> ReferenceStability:
    """Both rankings (geNorm, NormFinder) of the study's candidate reference genes."""
    from qpilot.web.references_views import ReferencesUnavailable, reference_stability
    from qpilot.web.routers.results import study

    study(ctx, study_id)
    try:
        return reference_stability(ctx.store, study_id)
    except ReferencesUnavailable as err:
        reason = str(err).rstrip(".")
        raise api_error(
            409,
            "unavailable",
            f"NormFinder cannot be shown next to geNorm: {reason}. It needs the study's input "
            "file, as the Prism export does.",
        ) from err
