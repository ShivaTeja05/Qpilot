"""The Cq table route: the Curves stage of a file of Cq values only (``docs/cq-tables.md``).

``GET /sessions/{sid}/cq-table`` answers what a file with no amplification curves holds, to
confirm in the curves stage instead of curves: each sample's Cq per well and plate, the wells
without a Cq, the replicate sets wider than the Run Gate's rule G-REP expects, and each assay's
efficiency (its dilution series, else assumed 2.0), with the curve-based checks that do not
apply said in plain words (:mod:`qpilot.web.cq_table_views`). A file with curves answers
``cq_only: false``. Blind: no group, fold change or p-value is ever in it, and the Cq values
wait for the design to be confirmed (``shown: false`` until then). GETs never write.
"""

from __future__ import annotations

from fastapi import APIRouter

from qpilot.web.context import Ctx
from qpilot.web.contract_cqonly import CqTableView
from qpilot.web.routers.studio import call, session

router = APIRouter(tags=["studio"])


@router.get("/sessions/{sid}/cq-table", response_model=CqTableView)
def get_cq_table(sid: str, ctx: Ctx) -> CqTableView:
    """A Cq-only file's Cq table for the curves stage (blind: no group, no comparison)."""
    from qpilot.web.cq_table_views import cq_table_view

    session(ctx, sid)
    return call(cq_table_view, ctx.studio, sid)
