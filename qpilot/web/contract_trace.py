"""Response models of the Trace routes: a result followed down to its samples, wells and plates.

Owned by the ``trace`` router (:mod:`qpilot.web.routers.trace`). The engine's own models
(:mod:`qpilot.trace.schema`) are returned as they are; this module adds the study, the chain
head the trace was read at, and the trace's sentences as :class:`~qpilot.web.contract.FactText`
(every number in them a cited fact). Like :mod:`qpilot.web.contract`, every string is text,
never HTML, and every number comes from the engine. Keep changes additive and regenerate the
frontend's types (``npm run gen:api``) with them.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from qpilot.trace.schema import TraceGene, TraceStudy, TraceWithout
from qpilot.web.contract import FactText


class TraceGeneView(BaseModel):
    """``GET /studies/{id}/trace/{gene}``: one gene's call, followed down to its wells."""

    study_id: str
    session: str | None = Field(description="The Studio session the study came from, if any.")
    head: str = Field(description="The decision chain head the trace was read at.")
    trace: TraceGene
    texts: dict[str, FactText] = Field(
        description="The trace's sentences by id: `summary`, `flip`, `look_first`, `place_<rank>`."
    )


class TraceStudyView(BaseModel):
    """``GET /studies/{id}/trace``: genes by fragility, the samples behind the most calls."""

    study_id: str
    session: str | None
    head: str
    trace: TraceStudy
    texts: dict[str, FactText] = Field(description="The overview's sentences by id: `summary`.")


class TraceWithoutBody(BaseModel):
    """The samples to set aside together (nothing is applied: a what-if)."""

    samples: list[str] = Field(
        default=[], max_length=50, description="Sample names as the trace lists them (1 to 50)."
    )


class TraceWithoutView(BaseModel):
    """``POST /studies/{id}/trace/{gene}/without``: the call recomputed without some samples."""

    study_id: str
    head: str
    result: TraceWithout


class TraceLoaded(BaseModel):
    """The result of the ``trace.load`` job: the study is ready to trace."""

    study_id: str
    head: str
    n_genes: int
    seconds: float
