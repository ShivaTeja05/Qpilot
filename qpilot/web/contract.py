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

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from qpilot.schemas import (
    ContrastResult,
    DecisionCard,
    DecisionEntry,
    DecisionOutcome,
    GeneRobustness,
    Grade,
)
from qpilot.schemas_studio import (
    InspectSummary,
    Proposal,
    ProposalOutcome,
    QuarantineEntry,
    WellCall,
)

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
Reason = Annotated[str, Field(max_length=2000, description="Kept in the record (≤ 500 chars).")]


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
    descriptions: dict[str, str] = Field(
        default={}, description="Proposal id -> the proposal in plain words (as made, or edited)."
    )


class ProposalAction(BaseModel):
    """Accept, edit or reject one proposal (always as a person)."""

    reason: Reason = ""
    edits: dict[str, Any] | None = None
    expected_head: str | None = None


class ProposeDesign(BaseModel):
    """Ask for design proposals; the sentence given at Open is used when none is sent."""

    sentence: str | None = Field(default=None, max_length=500)


class RefusedProposal(BaseModel):
    """A proposal the inbox refused to take (with why)."""

    subject: str | None = None
    reason: str | None = None


class ProposeReport(BaseModel):
    """What one round of proposing added to the inbox (the result of a propose job)."""

    stage: str
    proposed: list[str] = Field(description="Ids of the proposals added.")
    refused: list[RefusedProposal] = []
    notes: list[str] = []
    fallback: bool | None = Field(
        default=None, description="True when the model was not used at all (rules alone)."
    )
    fields_by_model: int | None = Field(default=None, description="Fields the model made.")
    model_error: str | None = None
    disagreements: int | None = Field(
        default=None, description="Curves: study wells where the Curve Judge disagrees."
    )
    targets_that_matter: int | None = None
    message: str = Field(description="What happened, in one or two sentences.")


class ProposeOne(BaseModel):
    """The answer to proposing a single thing (the comparison): what was added, or why not."""

    outcome: ProposalOutcome | None = None
    message: str


class EvidenceView(BaseModel):
    """One evidence item with the file's text it points at (quoted, never obeyed)."""

    kind: str
    ref: str
    note: str = ""
    text: str | None = Field(default=None, description="The quoted text behind a text id / cell.")
    origin: str | None = None
    flags: list[str] = []
    well: str | None = Field(default=None, description="`run_id/well` when it points at a well.")


class ProposalView(BaseModel):
    """One proposal with everything its card shows, in words."""

    proposal: Proposal
    description: str
    alternatives: list[str] = Field(description="Each alternative in plain words.")
    evidence: list[EvidenceView]
    blind: bool = Field(description="A design/curves proposal: its consequence is only 'matters'.")
    stale_consequence: str | None = Field(
        default=None, description="Why a round-trip consequence no longer holds (then refused)."
    )
    model_made: bool = Field(description="Made by a language model (its payload can be shown).")
    head: str


class ProposalDecided(BaseModel):
    """The answer to accept / edit / reject: the outcome and the session's stages after it."""

    outcome: ProposalOutcome
    message: str
    head: str
    stages: list[StageView] = []
    results_visible: bool
    job: JobView | None = Field(
        default=None, description="The analysis this decision started (results became visible)."
    )


class MattersAnswer(BaseModel):
    """Does this proposal (or its first alternative) change a conclusion? Only yes / no."""

    proposal_id: str
    matters: bool | None = Field(description="None: the rest of the design does not run yet.")
    head: str = Field(description="The proposal chain head this answer holds for.")
    message: str


BulkAction = Literal["accept", "reject"]


class BulkList(BaseModel):
    """Exactly what a bulk action would cover, shown before anything is written."""

    stage: str
    action: BulkAction
    ids: list[str]
    proposals: list[Proposal]
    descriptions: dict[str, str] = {}
    head: str
    message: str


class BulkRequest(BaseModel):
    """Act on exactly the listed proposals (the list the person was shown)."""

    stage: str
    ids: list[str] = Field(max_length=2000)
    reason: Reason = ""
    expected_head: str | None = None


class BulkDone(BaseModel):
    """What a bulk action did, one chain entry per proposal."""

    action: BulkAction
    done: int
    outcomes: list[ProposalOutcome]
    message: str
    head: str
    stages: list[StageView] = []
    results_visible: bool = False


ConfirmStage = Literal["design", "curves", "choices"]


class ConfirmView(BaseModel):
    """A stage's pending confirm step and exactly what it covers (nothing written yet)."""

    stage: ConfirmStage
    proposal: Proposal | None = None
    covers: list[Proposal] = []
    descriptions: dict[str, str] = {}
    warnings: list[str] = []
    ready: bool = Field(description="True when a confirm step waits for 'Yes, confirm'.")
    message: str
    head: str


class ConfirmRequest(BaseModel):
    """Yes, confirm: accept this confirm step."""

    proposal_id: str
    expected_head: str | None = None


# ---- Studio: the plate, curves and quarantined text ------------------------------------------


class PlateRun(BaseModel):
    """One plate (run) of the file."""

    experiment_id: str
    run_id: str
    n_wells: int
    targets: list[str]
    in_design: bool = Field(description="On the experiment the design analyses.")


class PlateWell(BaseModel):
    """One well (and target) of a plate; curve numbers once the design is confirmed."""

    key: str = Field(description="`run_id/well`: what the curve routes take.")
    well: str
    row: int | None = Field(default=None, description="1-based row (A = 1).")
    col: int | None = Field(default=None, description="1-based column.")
    sample: str
    sample_text_id: str | None = None
    target: str
    target_text_id: str | None = None
    declared_type: str = Field(description="What the file declares (unkn, std, ntc, nrt, …).")
    role: str | None = Field(default=None, description="Its role in the design assembled so far.")
    excluded_by_person: bool = False
    excluded_note: str = Field(default="", description="The file's or LinRegPCR's exclusion note.")
    amplified: bool | None = Field(
        default=None,
        description="Counts as amplified under the analysis rule: LinRegPCR found a starting "
        "quantity (or a person's call for this well).",
    )
    cq: float | None = Field(default=None, description="LinRegPCR's Cq (a cycle).")
    efficiency: float | None = Field(
        default=None,
        description="The well's own amplification factor per cycle (2.0 = 100 %); the starting "
        "quantity uses the target's mean (efficiency_target).",
    )
    efficiency_target: float | None = Field(
        default=None, description="The target's mean amplification factor, used for N0."
    )
    r2: float | None = None
    baseline: float | None = Field(default=None, description="LinRegPCR's baseline (raw units).")
    linregpcr_note: str = Field(default="", description="LinRegPCR's own note on this well.")
    judge: bool | None = Field(default=None, description="The Curve Judge's call, when it ran.")
    disagrees: bool = False
    person_call: bool | None = Field(default=None, description="A call a person accepted.")
    proposal_id: str | None = Field(default=None, description="A pending well-call proposal.")
    group: str | None = Field(default=None, description="Only once results are visible.")


class PlateView(BaseModel):
    """One plate's wells, for the plate map (blind: no group next to a number)."""

    key: str
    run: PlateRun
    runs: list[PlateRun]
    n_rows: int
    n_cols: int
    targets: list[str]
    curves_shown: bool = Field(description="Cq, efficiency, R² and calls are included.")
    curves_note: str
    curve_judge: str = Field(description="The Curve Judge's status in words.")
    results_visible: bool
    wells: list[PlateWell]


class CurveSeries(BaseModel):
    """One well's raw curve."""

    key: str
    well: str
    sample: str
    target: str
    cycle: list[int]
    fluorescence: list[float | None]


class CurveView(BaseModel):
    """One well's raw amplification curve, with LinRegPCR's numbers once they may be shown."""

    key: str
    run_id: str
    well: str
    sample: str
    target: str
    declared_type: str
    cycle: list[int]
    fluorescence: list[float | None] = Field(description="Raw fluorescence as in the file.")
    numbers_shown: bool
    cq: float | None = Field(default=None, description="LinRegPCR's Cq (a cycle).")
    baseline: float | None = Field(
        default=None, description="LinRegPCR's baseline, in the fluorescence's units."
    )
    efficiency: float | None = Field(
        default=None,
        description="The well's own amplification factor per cycle (2.0 = 100 %).",
    )
    efficiency_target: float | None = Field(
        default=None, description="The target's mean amplification factor, used for N0."
    )
    r2: float | None = None
    amplified: bool | None = Field(
        default=None, description="Counts as amplified under the analysis rule (see PlateWell)."
    )
    judge: bool | None = None
    linregpcr_note: str = ""
    replicates: list[CurveSeries] = Field(
        description="Other wells of the same sample and target on the same plate."
    )
    note: str


class CurveCallsView(BaseModel):
    """Each well of one target called under every rule (facts about curves, no conclusion)."""

    gene: str
    rules: list[str]
    rule_labels: dict[str, str]
    curve_judge: str
    wells: list[WellCall]
    disagreements: list[str]


class QuarantineView(BaseModel):
    """The session's quarantined texts: what the file (or sheet, or sentence) says, quoted."""

    entries: list[QuarantineEntry]
    sheet_cells: dict[str, str] = Field(description="Sheet cell (`Sheet1!B2`) -> text id.")
    n_flagged: int


class ModelSeen(BaseModel):
    """What the model was sent in its last call — withheld while blind unless it held no result."""

    state: Literal["none", "hidden", "shown"]
    message: str
    payload_text: str | None = Field(default=None, description="The payload as indented JSON.")
    sha256: str | None = None
    interpreter: bool = Field(description="Sent by the Design Interpreter (holds no result).")
    same_as_proposal: bool | None = Field(
        default=None, description="With ?proposal=: the payload is the one behind that card."
    )


# ---- results ---------------------------------------------------------------------------------

Conclusion = Literal["up", "down", "none"]


class FactRef(BaseModel):
    """A number the engine computed, as cited in a text (its id says where it comes from)."""

    id: str
    text: str = Field(description="The value as written (format and unit applied).")
    value: float | int | str
    unit: str = ""
    path: str = Field(default="", description="Where in the result it comes from.")


class TextSegment(BaseModel):
    """A run of plain text, or one cited number (``fact`` names it)."""

    text: str
    fact: str | None = None


class FactText(BaseModel):
    """A sentence whose numbers are facts: plain text, segments, and the facts it cites."""

    plain: str
    segments: list[TextSegment]
    facts: list[FactRef]
    source: Literal["template", "model"] = "template"


class GroupCount(BaseModel):
    """One comparison group and how many biological units it holds."""

    label: str
    n: int


class ResultsSummary(BaseModel):
    """The study in counts, its groups and how they were made."""

    n_plates: int
    n_reactions: int
    n_samples: int
    n_genes: int
    mode: Literal["marker_split", "groups"]
    group_var: str
    groups: list[GroupCount] = Field(description="The compared group first, the reference second.")
    cut: float | None = Field(default=None, description="Marker split: the top fraction.")
    design_line: str
    text: FactText | None = Field(default=None, description="The summary sentence, cited.")


class RuleView(BaseModel):
    """The rule every conclusion is drawn with."""

    alpha: float
    min_log2fc: float
    min_fold: float
    text: str


class GenormView(BaseModel):
    """Reference genes: which were used, and geNorm's stability (M) and pairwise V."""

    used: list[str]
    candidates: list[str]
    m: dict[str, float] = Field(description="geNorm M per candidate (lower is more stable).")
    order: list[str]
    v: dict[str, float]
    recommended: list[str]
    cutoff_m: float
    cutoff_v: float
    stable: list[str] = Field(description="Candidates below the M cut-off.")


class AtChoices(BaseModel):
    """A gene's result at the options a person chose on the Decision Cards (from the grid)."""

    fc: float
    log2fc: float
    p: float
    conclusion: Conclusion
    differs: bool = Field(description="The call differs from the planned analysis.")


class GeneRow(BaseModel):
    """One compared gene: the contrast, how robust it is, and how confident."""

    gene: str
    headline: bool
    conclusion: Conclusion
    fc: float
    log2fc: float
    ci: tuple[float, float]
    p: float
    n_hi: int
    n_lo: int
    holds: float | None = Field(
        default=None, description="Share of reasonable analyses with the same call (0–1)."
    )
    n_cells: int
    level: str | None = None
    reasons: list[str] = []
    min_flip_changes: int | None = None
    flips_by: list[str] = Field(description="Decisions that alone can change this call.")
    efficiency: float | None = None
    at_your_choices: AtChoices | None = None
    verdict: str | None = Field(default=None, description="The robustness audit's verdict.")
    verdict_label: str | None = None


class AuditBadge(BaseModel):
    """Whether the robustness audit ran on this study (details: the Audit section)."""

    status: Literal["none", "ready"]
    verdict_counts: dict[str, int] = {}
    chain_head: str | None = None
    current: bool = Field(default=False, description="Audited at the decision chain head of now.")


class ResultsView(BaseModel):
    """Everything the Results section shows about a study (raw numbers; the page formats)."""

    study_id: str
    session: str | None = Field(default=None, description="The Studio session it belongs to.")
    input_sha256: str
    summary: ResultsSummary
    rule: RuleView
    references: GenormView
    genes: list[GeneRow]
    headline: list[str]
    counts: dict[str, int] = Field(description="Genes per conclusion (up / down / none).")
    levels: dict[str, int] = Field(description="Genes per confidence level.")
    choices: dict[str, str] = Field(description="Card id -> the option applied now.")
    cards_waiting: int
    pending_requests: int
    head: str
    audit: AuditBadge


class OptionEffect(BaseModel):
    """One option's consequence for one gene (the other choices as planned)."""

    gene: str
    fc: float
    log2fc: float
    ci: tuple[float, float]
    p: float
    conclusion: Conclusion
    changes_call: bool = Field(description="A different call than the recommended option's.")


class CardOptionView(BaseModel):
    """One option of a Decision Card."""

    id: str
    label: str
    recommended: bool
    chosen: bool
    requested: bool = Field(description="An agent asked for this option; it waits for a person.")
    not_recommended: bool = Field(description="E.g. a single control gene (MIQE).")
    effects: list[OptionEffect]


class PendingRequest(BaseModel):
    """An agent's request on a card, waiting for a person."""

    seq: int
    option: str
    option_label: str
    reason: str
    actor: str
    at: str


class CardView(BaseModel):
    """One Decision Card with its words, options and what each option changes."""

    card: DecisionCard
    title: str
    status_line: str
    impact: FactText
    explanation: FactText
    needs_human: bool = Field(description="Can change a conclusion: only a person decides it.")
    genes: list[str] = Field(description="The genes whose consequences each option shows.")
    options: list[CardOptionView]
    pending: list[PendingRequest]
    undo_option: str | None = Field(default=None, description="What Undo would restore.")
    undo_label: str | None = None


class CardsView(BaseModel):
    """The study's Decision Cards, most impact first."""

    study_id: str
    head: str
    cards: list[CardView]
    next_card: str | None
    counter: str
    pending_requests: int


class DecideBody(BaseModel):
    """Decide a card (always as a person; the reason is kept in the record)."""

    option: str = Field(max_length=200)
    reason: Reason
    expected_head: str | None = None


class UndoBody(BaseModel):
    """Undo the last change on a card (a new entry restoring the option before it)."""

    reason: Reason
    expected_head: str | None = None


class TurnDownBody(BaseModel):
    """Turn down an agent's request on a card (one option, or every request on it)."""

    reason: Reason
    option: str | None = Field(default=None, max_length=200)
    expected_head: str | None = None


class DecisionDone(BaseModel):
    """The answer to decide / undo / turn down."""

    outcome: DecisionOutcome
    message: str
    head: str
    card: CardView | None = None
    next_card: str | None = None


class Explanation(BaseModel):
    """A card explained by the model (or why the template's words stand)."""

    card_id: str
    text: FactText
    validated: bool
    fallback: bool
    provider: str
    note: str = ""


class DecisionEntryView(BaseModel):
    """One entry of the decision chain, with its card and option in words."""

    entry: DecisionEntry
    card_title: str
    option_label: str
    undo: bool = Field(description="Written by Undo.")


class StaleAttempt(BaseModel):
    """A write refused as stale (kept outside the chain, so it never moved the head)."""

    at: str
    attempted: str = Field(description="applied, pending_human or rejected")
    card_id: str
    card_title: str
    option: str
    option_label: str
    reason: str = ""
    actor: str
    expected_head: str | None = None
    head: str | None = None


class DecisionsView(BaseModel):
    """The study's hash-chained decision log, requests waiting, and its head."""

    study_id: str
    head: str
    root: str = Field(default="", description="The chain's genesis: the input file's sha256.")
    chain_intact: bool = Field(
        default=True, description="Every entry's link and hash re-computed on the server."
    )
    broken_at: int | None = Field(default=None, description="The first entry that fails.")
    entries: list[DecisionEntryView]
    pending: list[DecisionEntryView]
    n_pending: int = 0
    attempts: list[StaleAttempt] = []


class FlipOption(BaseModel):
    """One option of a decision, the other choices as planned: each gene's call under it."""

    value: str
    label: str
    card_option: str | None = Field(default=None, description="The card's option id, if any.")
    planned: bool
    chosen: bool = False
    conclusion: list[Conclusion] = Field(description="Aligned with FlipsView.genes.")
    log2fc: list[float]
    flips: list[bool]


class FlipRow(BaseModel):
    """One decision: which genes changing it alone can flip, and by how much it moves them."""

    dimension: str
    title: str
    card_id: str | None = None
    status: str | None = None
    flips: list[bool] = Field(description="Aligned with FlipsView.genes.")
    max_delta_log2fc: list[float]
    n_flipped: int
    options: list[FlipOption]


class FlipsView(BaseModel):
    """Decisions (rows) × genes (columns): where one decision alone flips a gene's call."""

    study_id: str
    genes: list[str]
    planned: list[Conclusion]
    rows: list[FlipRow]


class GeneGrid(BaseModel):
    """Every analysis in the grid for one gene (the 'what holds' strip), compactly."""

    dimensions: list[str]
    options: dict[str, list[str]]
    planned: list[int] = Field(description="The planned option's index per dimension.")
    cells: list[list[int]] = Field(description="Option index per dimension, one per analysis.")
    log2fc: list[float]
    p: list[float]
    conclusion: list[Conclusion]


class GeneView(BaseModel):
    """Everything about one gene."""

    study_id: str
    gene: str
    row: GeneRow
    contrast: ContrastResult
    robustness: GeneRobustness
    confidence: Grade | None = None
    confidence_text: FactText | None = None
    grid: GeneGrid | None = None
    effects: list[FlipRow] = Field(description="One decision at a time (this gene only).")
    cards: list[CardView] = Field(description="Decision Cards that can change this gene.")
    is_reference: bool
    reference_m: float | None = None
    prev_gene: str | None = None
    next_gene: str | None = None
    audit_verdict: str | None = None
    audit_verdict_label: str | None = None
