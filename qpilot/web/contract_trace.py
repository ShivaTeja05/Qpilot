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

from qpilot.trace.schema import TraceGene, TracePlate, TraceStudy, TraceWithout
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


class TracePlateView(BaseModel):
    """``GET /studies/{id}/trace/plate?run=``: one plate's wells with Trace's flags."""

    study_id: str
    plate: TracePlate


class TraceLoaded(BaseModel):
    """The result of the ``trace.load`` job: the study is ready to trace."""

    study_id: str
    head: str
    n_genes: int
    seconds: float


# ---- Where to look (the place-to-look engine, qpilot.qpcr.trace) ------------------------------


class WhereCheck(BaseModel):
    """One fingerprint check a place fails (S1-S7), in words."""

    code: str
    looks_like: str
    consistent_with: str
    what_to_check: str


class WhereOption(BaseModel):
    """One thing a person could do at a place, and what it would do to the calls."""

    id: str
    label: str
    consequence: str = Field(description="changes_call, beyond_ci or changes_nothing.")
    consequence_word: str
    changed_calls: list[str] = Field(description="Genes whose call this option changes.")


class WherePlace(BaseModel):
    """A place to look: a well (or the sample's tube) where something is unusual."""

    rank: int
    sample: str
    plate: str | None = None
    well: str | None = None
    target: str | None = None
    role: str
    checks: list[WhereCheck]
    consequence: str
    consequence_word: str
    options: list[WhereOption]
    card_id: str = Field(description="The Decision Card this place opens as (Decide…).")
    card_status: str | None = Field(
        None, description="The card's status when it is already open (open, decided, …)."
    )
    can_decide: bool = Field(
        description="Decide… is offered: an option here changes a call (a person's decision)."
    )


class WhereAbsent(BaseModel):
    """A sample in no comparison."""

    sample: str
    why: str


class WhereView(BaseModel):
    """``GET /studies/{id}/where-to-look``: from a gene, a sample or a well to the places to look.

    Read-only: nothing is opened or written. ``text`` is the "Where to look" panel, one
    sentence per line, every number a cited fact.
    """

    study_id: str
    session: str | None
    head: str = Field(description="The chain head it was read at; send it to open a card.")
    root: dict[str, str] = Field(description="{kind: gene | sample | well, id}.")
    answer: str = Field(
        description="place_to_look, choice_to_look_at, nothing_to_look_at or absent."
    )
    planned: bool = Field(
        description="True when the analysis traced is the planned one (no card decided "
        "otherwise); either way it is the analysis in use."
    )
    text: list[FactText]
    places: list[WherePlace]
    n_more: int = Field(description="Further places found, not shown.")
    checked_nothing_found: list[str]
    cannot_show: list[str]
    absent: list[WhereAbsent]
    n_absent: int
    decide_note: str
    method_card: str = "methods/trace.md"


class OpenPlaceBody(BaseModel):
    """Open the place at ``rank`` of a trace as a Decision Card (a person's click)."""

    kind: str = Field(pattern="^(gene|sample|well)$")
    id: str = Field(min_length=1, max_length=200)
    rank: int = Field(ge=1, le=50)
    expected_head: str = Field(
        min_length=1,
        max_length=128,
        description="The chain head the trace was read at (409 stale when it moved).",
    )


class PlaceOpened(BaseModel):
    """The card a place opened as: decide it on Results like any other card."""

    card_id: str
    opened: bool = Field(description="False when the card was already open.")
    message: str
    head: str
