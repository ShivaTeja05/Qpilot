"""Per-unit values routes: each biological unit's value of one gene, with its wells.

``GET /api/studies/{id}/genes/{gene}/units`` (:func:`qpilot.web.units_views.unit_values`): the
engine's per-unit values at the planned analysis, every well behind them (the technical
replicates), each group's mean with its 95 % CI and the stored fold change. The Gene section's
"Your samples" draws them when the robustness audit is not there to. Reads only; a study of a
Studio session answers ``403 blind`` until its design and curves are confirmed, as Results does.
"""

from __future__ import annotations

from fastapi import APIRouter

from qpilot.web.context import Ctx, api_error
from qpilot.web.contract_units import UnitValues

router = APIRouter(tags=["results"])

NOT_COMPARED = "There is no compared gene with this name (a control gene is not compared)."


@router.get("/studies/{study_id}/genes/{gene}/units", response_model=UnitValues)
def get_gene_units(study_id: str, gene: str, ctx: Ctx) -> UnitValues:
    """One compared gene's biological units, with their wells, at the planned analysis."""
    from qpilot.web.routers.results import study
    from qpilot.web.units_views import UnitsUnavailable, unit_values

    study(ctx, study_id)
    if not gene or len(gene) > 128:
        raise api_error(404, "not_found", NOT_COMPARED)
    try:
        return unit_values(ctx.store, study_id, gene)
    except KeyError as err:
        raise api_error(404, "not_found", NOT_COMPARED, gene=gene) from err
    except UnitsUnavailable as err:
        reason = str(err).rstrip(".")
        raise api_error(
            409,
            "unavailable",
            f"Each unit's value cannot be shown: {reason}. They need the study's input file, as "
            "the Prism export does.",
        ) from err
