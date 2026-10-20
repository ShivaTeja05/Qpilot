"""The page's API contract: every response model the one server returns.

The frontend's TypeScript types are generated from the OpenAPI schema these models produce
(``npm run gen:api`` in ``frontend/``), so a change here is a change of the contract: keep it
additive, and regenerate the types in the same commit.

Engine and Studio models (:class:`~qpilot.schemas.DecisionCard`,
:class:`~qpilot.schemas_studio.Proposal`, …) are returned as they are, never re-shaped; this
module adds only what the page needs around them. No model here carries HTML: every string is
text, and the page renders text as text.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from qpilot.schemas_studio import InspectSummary, Proposal

# ---- errors and jobs -----------------------------------------------------------------------


class ErrorBody(BaseModel):
    """A refusal or failure in plain words; ``code`` is stable, ``message`` is for people."""

    code: str
    message: str
    details: dict[str, Any] = {}


class ErrorResponse(BaseModel):
    """Every non-2xx answer: ``{"error": {...}}``."""

    error: ErrorBody


JobStatus = Literal["queued", "running", "done", "failed"]


class JobView(BaseModel):
    """One piece of slow work; ``result`` is set once it is done (shape depends on ``kind``)."""

    id: str
    kind: str
    title: str
    key: str | None = None
    status: JobStatus
    step: str = ""
    fraction: float | None = None
    typical_s: float | None = None
    elapsed_s: float = 0.0
    result: Any = None
    error: dict[str, str] | None = None


class JobStarted(BaseModel):
    """What a slow request answers at once."""

    job: JobView


# ---- the system ------------------------------------------------------------------------------


class ModelStatus(BaseModel):
    """Which model the AI layer uses, whether it answers, and what leaves this machine."""

    provider: str
    model: str | None = None
    available: bool
    configured: bool
    answers: bool | None = None
    checking: bool = False
    misconfigured: bool = False
    reason: str | None = None
    local: bool
    sample_names: str
    outbound: str = Field(description="The `outbound` line of `qpilot doctor`, as words.")


class DemoInfo(BaseModel):
    """The public demo study (Vermeulen 2009 / Ruijter 2013), SHA-256 pinned."""

    cached: bool
    path: str | None = None
    bytes: int
    sha256: str
    source: str
    citation: str
    licence: str


class SystemView(BaseModel):
    """What this install is and what it will use."""

    version: str
    python: str
    platform: str
    method: str = Field(description="The vendored curve method and its commit.")
    studies_dir: str
    simulator: bool = Field(description="Whether the Decision Simulator (audit) is installed.")
    model: ModelStatus
    autonomy: Literal["suggest", "decide_and_tell"]
    demo: DemoInfo
    policy: list[str] = Field(description="What qPilot does and never does, one line each.")
    never: list[str] = Field(description="The never-does footer lines.")


class Settings(BaseModel):
    """Settings a person can change from the page (this launch only)."""

    autonomy: Literal["suggest", "decide_and_tell"] = "suggest"


# ---- workspaces ------------------------------------------------------------------------------

StageName = Literal["design", "curves", "choices", "prism", "roundtrip"]


class StageView(BaseModel):
    """Where one Studio stage stands."""

    stage: StageName
    open: bool
    confirmed: bool
    pending: int
    blockers: list[str] = []


class NextStep(BaseModel):
    """The one thing to do next, in the page's own words, and where to do it."""

    title: str
    detail: str = ""
    section: str = Field(description="The page section to go to (home, design, curves, …).")
    action: str | None = Field(default=None, description="A button label on that section.")


WorkspaceKind = Literal["session", "study"]


class WorkspaceSummary(BaseModel):
    """One line of the workspace list (a Studio session, or a study analysed without one)."""

    key: str = Field(description="12 hex: the session id, or the study id of a study-only one.")
    kind: WorkspaceKind
    title: str
    input_sha256: str
    file_name: str | None = None
    file_present: bool
    study_id: str | None = None
    results_visible: bool
    stages: list[StageView] = []
    n_plates: int | None = None
    n_samples: int | None = None
    n_genes: int | None = None
    decisions: int = 0
    pending_requests: int = 0
    has_audit: bool = False
    is_demo: bool = False
    updated_at: float = Field(description="Unix time of the last write to this workspace.")


class WorkspaceList(BaseModel):
    """Every workspace in the store, most recently changed first."""

    workspaces: list[WorkspaceSummary]


class FileFacts(BaseModel):
    """What the opened file declares (counts only; names are in ``summary``)."""

    file_name: str | None
    input_sha256: str
    sheet_name: str | None = None
    n_plates: int
    n_wells: int
    n_samples: int
    n_targets: int
    declared_types: dict[str, int]


class WorkspaceView(BaseModel):
    """One workspace: its file, its stages, whether results may be shown, and the next step."""

    key: str
    kind: WorkspaceKind
    title: str
    facts: FileFacts | None = None
    summary: InspectSummary | None = None
    stages: list[StageView] = []
    results_visible: bool
    study_id: str | None = None
    proposals_head: str | None = None
    decisions_head: str | None = None
    next_step: NextStep
    active_jobs: list[JobView] = []
    has_audit: bool = False
    is_demo: bool = False


class Opened(BaseModel):
    """The answer to opening a file: the workspace to go to."""

    key: str
    workspace: WorkspaceView


# ---- Studio proposals ------------------------------------------------------------------------


class ProposalList(BaseModel):
    """A stage's inbox, in the order the page shows it (contradicted first, then the rest)."""

    stage: str | None
    head: str
    proposals: list[Proposal]
    counts: dict[str, int] = Field(description="proposed / consistent / contradicted / … counts")


class ProposalAction(BaseModel):
    """Accept, edit or reject one proposal (always as a person)."""

    reason: str = ""
    edits: dict[str, Any] | None = None
    expected_head: str | None = None
