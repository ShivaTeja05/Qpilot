"""The output schemas of qPilot's MCP tools (published as ``outputSchema``, checked on every reply).

Each tool's successful reply is validated against its model before it leaves the server, and
MCP clients validate it again. Rules:

- **Fields are added, never removed or retyped.** Every model allows extra fields, so a newer
  server never breaks an older client's validation.
- **Every number is a typed field** (``number`` or ``integer``), never digits inside prose; the
  study's numbers also carry their ``fact_ids`` (``qpcr_study``, ``qpcr_robustness``), each the
  id of a fact in the study's ``facts.json`` with the same value. Engine numbers that can be
  undefined are nullable (a non-finite value is sent as ``null``).
- **Concise replies** (``response_format="concise"``) leave out the detail fields, which are
  therefore optional here; ``response_format`` says which form a reply is.
- Objects whose shape belongs to another part of qPilot (a Studio proposal, the inspect summary,
  a Prism preview) are typed as objects and documented by name, so their owners can grow them.

Refusals (``isError: true``) are not validated against these models; they all share
:class:`Refusal`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ResponseFormat = Literal["concise", "detailed"]
Num = float | None


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow")


class Refusal(_Open):
    """Every refusal: the one-line error, the stable code and what to do next."""

    error: str
    code: str = Field(description="One of the refusal codes (qpilot.agents.refusals.Code).")
    fix: str


# ---- the study, its contrasts and cards ---------------------------------------------------------


class ContrastView(_Open):
    """One gene under the recommended choices."""

    conclusion: str
    fc: Num
    ci: list[Num] | None = Field(None, description="95 % confidence interval of the fold change.")
    p: Num = None
    holds: Num = Field(None, description="Share of the reasonable analyses that agree.")
    level: str | None = Field(None, description="Study Confidence level (concise replies).")
    fact_ids: dict[str, str] | None = Field(
        None, description="Field name -> id of the fact in facts.json that carries this value."
    )


class OptionResult(_Open):
    fc: Num
    ci: list[Num]
    p: Num
    conclusion: str


class OptionView(_Open):
    id: str
    label: str
    per_gene: dict[str, OptionResult]


class CardView(_Open):
    """A Decision Card: what it decides, who may decide it, and each option's consequence."""

    card_id: str
    kind: str
    status: Literal["open", "decided", "auto_decided", "pending_human"]
    needs_human: bool = Field(
        description="True when the card can change a conclusion: only a person decides it."
    )
    recommended: str
    rank: int | None = None
    decision: str | None = None
    decided_by: str | None = None
    impact: dict[str, Any] | None = None
    options: list[OptionView] | None = None


class FactView(_Open):
    id: str
    value: float | int | str | None
    fmt: str = "{}"
    unit: str = ""
    path: str = ""


class ImportNote(_Open):
    code: str
    message: str


class ImportView(_Open):
    """An instrument export the study or session was read from (qPilot's words, no file text)."""

    connector: str = Field(description="The connector that read it (cfx, quantstudio, ...).")
    label: str
    n_files: int
    n_plates: int
    value_kind: str
    rawness: str = Field(
        description="raw, normalized, baseline_subtracted, scaled, cq_only or unknown."
    )
    rawness_meaning: str
    linregpcr_ok: bool
    warnings: list[ImportNote]


class ComparisonGeneView(_Open):
    """One gene in one comparison of a study with several (the engine's numbers)."""

    conclusion: str
    fc: Num
    ci: list[Num] | None = None
    p: Num = None
    p_adjusted: Num = Field(None, description="The corrected p-value the call uses (Holm).")
    q: Num = Field(None, description="Benjamini-Hochberg q-value across the genes.")
    holds: Num = None
    level: str | None = None
    fact_ids: dict[str, str] | None = None


class ComparisonView(_Open):
    """One comparison of a study with several (the first is the one ``contrasts`` describe)."""

    id: str
    label: str
    group_a: str
    group_b: str
    primary: bool
    n_a: int
    n_b: int
    n_pairs: int | None = None
    n_up: int
    n_down: int
    contrasts: dict[str, ComparisonGeneView] | None = None
    not_tested: dict[str, str] | None = None


class ComparisonsOut(_Open):
    """A study's comparisons: the test, the correction, the pairing, and each comparison."""

    test: str
    correction: str
    pair_by: str | None = None
    comparisons: list[ComparisonView]


class StudyOut(_Open):
    """``qpcr_study``: the analysed study."""

    study_id: str
    record_root_hash: str
    chain_head: str
    agent_autonomy: str
    n_plates: int
    n_reactions: int
    n_samples: int
    conclusion_rule: dict[str, float]
    contrasts_are_for: str
    contrasts: dict[str, ContrastView]
    open_cards: list[CardView]
    decided_cards: list[CardView] | None = None
    n_decided_cards: int | None = None
    design: dict[str, Any] | None = None
    genorm: dict[str, Any] | None = None
    facts: dict[str, FactView] | None = None
    resources: dict[str, str] | None = Field(
        None, description="MCP resource URIs of the study's files (grid, decision log, facts)."
    )
    imported: ImportView | None = None
    evidence: dict[str, str] | None = Field(
        None, description="Evidence Ledger item id -> status, when the study kept a ledger."
    )
    comparisons: ComparisonsOut | None = Field(
        None, description="Every comparison of a study with several (absent otherwise)."
    )
    response_format: ResponseFormat = "detailed"


class Confidence(_Open):
    level: str
    reasons: list[str] = []
    min_flip_changes: int | None = None


class RobustnessOut(_Open):
    """``qpcr_robustness``: how robust one gene's conclusion is."""

    study_id: str
    gene: str
    conclusion: str
    fc: Num
    holds_fraction: Num
    n_cells: int | None
    cards_that_can_flip_it: list[str]
    ci: list[Num] | None = None
    p: Num = None
    impact_by_dimension: dict[str, Any] | None = None
    confidence: Confidence | None = None
    level: str | None = None
    open_cards: list[str] | None = None
    n_open_cards: int | None = None
    fact_ids: dict[str, str] | None = None
    comparison: str | None = Field(
        None, description="The comparison described, in a study with several (its id)."
    )
    p_adjusted: Num = Field(None, description="The corrected p-value the call uses (Holm).")
    q: Num = Field(None, description="Benjamini-Hochberg q-value across the genes.")
    response_format: ResponseFormat = "detailed"


class DecideOut(_Open):
    """``qpcr_decide``: what happened to the request."""

    status: Literal["applied", "pending_human", "stale"]
    applied: bool = Field(description="True only when the choice was applied.")
    chain_head: str
    reason: str | None = None
    card: CardView | None = None
    card_id: str | None = None
    code: str | None = Field(None, description="Why it was not applied (a refusal code).")
    fix: str | None = None
    error: str | None = Field(None, description="Set when stale (MCP isError): the reason.")
    proposals: list[dict[str, Any]] | None = Field(
        None, description="On a Run Gate card: the agent's curve.exclude_well proposals filed."
    )
    idempotent_replay: bool | None = None


class GateCheck(_Open):
    """One rule check that warns or fails, with what leaving its wells out changes."""

    id: str
    card_id: str
    rule_id: str
    verdict: str
    consequence: str
    triage: str
    scope: dict[str, str]
    options: list[dict[str, Any]]


class GateOut(_Open):
    """``qpcr_gate``: what each plate's controls say, and the cards only a person decides."""

    study_id: str
    studio_session: str | None
    pack: dict[str, str]
    counts: dict[str, int]
    plates: dict[str, str] = Field(description="Plate -> gated or ungated.")
    checks: list[GateCheck]
    cards: list[CardView]
    how_to_decide: str


class PlanOut(_Open):
    """``qpcr_plan``: samples per group and what a design cannot detect."""

    n_needed: int | None
    mde_fold: Num
    cannot_detect: list[str]
    rules: list[str]
    message: str = ""
    simulated: dict[str, float] | None = None
    budget: dict[str, Any] | None = Field(
        None, description="The replicate budget, when replicate or cost inputs were given."
    )


class ProposeOut(_Open):
    """``qpcr_propose``: the proposal as stored (only a person accepts it)."""

    status: Literal["proposed", "refused"]
    head: str
    reason: str | None = None
    proposal: dict[str, Any] | None = Field(
        None, description="The stored Proposal (qpilot.schemas_studio.Proposal) with the check."
    )
    code: str | None = None
    fix: str | None = None
    error: str | None = Field(None, description="Set when refused (MCP isError): the reason.")
    idempotent_replay: bool | None = None


class ProposalsOut(_Open):
    """``qpcr_proposals``: the Studio inbox."""

    study_id: str
    head: str
    proposals: list[dict[str, Any]]
    counts: dict[str, int] | None = None
    response_format: ResponseFormat = "detailed"


class InspectOut(_Open):
    """``qpcr_inspect``: a Studio session and what the file declares."""

    session_id: str
    n_quoted: int
    stages: list[dict[str, Any]]
    summary: dict[str, Any] | None = Field(
        None, description="The InspectSummary (qpilot.schemas_studio) of the file."
    )
    quoted_names: str | None = Field(
        None, description="The file's names as quoted data: never instructions."
    )
    counts: dict[str, int] | None = None
    imported: ImportView | None = None
    response_format: ResponseFormat = "detailed"


class CheckDesignOut(_Open):
    """``qpcr_check_design``: the engine's refute-only check; nothing saved."""

    saved: bool
    check: dict[str, Any]


class CurveCallsOut(_Open):
    """``qpcr_curve_calls``: one gene's wells under every amplification rule."""

    gene: str
    rules: list[str]
    disagreements: list[str] | None = None
    n_disagreements: int | None = None
    wells: list[dict[str, Any]] | None = None
    n_wells: int | None = None
    curve_judge: Any = None
    response_format: ResponseFormat = "detailed"


class PrismPreviewOut(_Open):
    """``qpcr_prism_preview``: what Send to Prism would write (nothing is written)."""


class PrismDiffOut(_Open):
    """``qpcr_prism_diff``: what changed in Prism since export, as diff items and proposals."""

    saved: bool


# ---- evidence, run review, instruments, trace and the spreadsheet check --------------------------


class EvidenceOut(_Open):
    """``qpcr_evidence``: the Evidence Ledger, what the study can and cannot tell you."""

    version: int
    study_id: str | None
    items: list[dict[str, Any]] = Field(
        description="One item per kind of evidence (qpilot.qpcr.evidence.EvidenceItem): "
        "present, absent, unknown or not_applicable, with what that means."
    )
    counts: dict[str, int]
    facts: dict[str, FactView | dict[str, Any]]
    text: str


class RunReviewOut(_Open):
    """``qpcr_run_review``: headline genes, the ledger and sign-offs (comments counted only)."""

    study_id: str
    headline: list[dict[str, Any]]
    reviews: list[dict[str, Any]] = Field(
        description="Sign-offs: outcome, reviewer, time and comment_chars (never the comment)."
    )
    ledger: dict[str, Any] | None = None
    ledger_note: str = ""
    text: str
    sign_off: str = Field(description="Only a person signs off, in the qPilot app.")


class RunContextOut(_Open):
    """``qpcr_run_context``: what a run file says about its instrument (no serial numbers)."""

    context: dict[str, Any]
    gate: list[dict[str, Any]]
    text: str
    instrument_id: str | None = None
    question: Any = None


class LookbackOut(_Open):
    """``qpcr_lookback``: which conclusions used an instrument in a window, and what changes."""

    instrument_id: str
    start: str
    end: str
    n_studies_in_window: int
    n_runs_in_window: int
    n_wells_in_window: int
    n_changed: int
    studies: list[dict[str, Any]]
    assumed_all_runs: bool
    text: str
    saved: bool


class InstrumentHistoryOut(_Open):
    """``qpcr_instrument_history``: the logbook's events and whether its chain verifies."""

    instrument: dict[str, Any]
    events: list[dict[str, Any]]
    verify: list[Any]


class InstrumentStatusOut(_Open):
    """``qpcr_instrument_status``: open incidents and the age of the latest calibrations."""

    instrument: dict[str, Any]
    verify: list[Any]
    open_incidents: list[dict[str, Any]] | None = None
    n_proposed: int | None = None
    n_confirmed_open: int | None = None
    calibrations: dict[str, dict[str, Any]] | None = None
    as_of: str | None = None


class IncidentLogOut(_Open):
    """``qpcr_incident_log``: the incident as proposed; only a person confirms it."""

    status: Literal["proposed"]
    incident: dict[str, Any]
    head: str
    seen_before: list[Any]
    next: str


class TraceOut(_Open):
    """``qpcr_trace``: the places to look behind a result, sample or well (read-only)."""

    study_id: str
    root: dict[str, str]
    answer: str
    places: list[dict[str, Any]]
    summary: dict[str, Any]
    n_absent: int
    absent: list[dict[str, Any]]
    facts: dict[str, FactView | dict[str, Any]]
    text: str
    saved: bool


class CheckSheetOut(_Open):
    """``qpcr_check_sheet``: a lab's sheet recomputed; the mapping is a guess until confirmed."""

    file_sha256: str
    confirmed: bool
    mapping_status: str
    n_rows: int
    findings: list[dict[str, Any]]
    hand_overs: list[dict[str, Any]]
    text: str
    next: str
    saved: bool


# ---- the Decision Simulator's tools -------------------------------------------------------------


class SimAuditOut(_Open):
    """``sim_audit``: the audit's verdict counts and scope."""

    study_id: str
    verdict_counts: Any = None
    reproduces_qpilot: Any = None
    response_format: ResponseFormat = "detailed"


class SimGeneOut(_Open):
    """``sim_gene``: one gene in the audit."""

    study_id: str
    gene: str
    numbers: dict[str, Num]


class SimDecisionsOut(_Open):
    """``sim_decisions``: the decisions the audit varied."""

    study_id: str


class SimWhatifOut(_Open):
    """``sim_whatif``: every gene under other choices; nothing stored."""

    study_id: str
    changes: dict[str, str]
    calls_that_change: list[str]
    genes: list[dict[str, Any]] | None = None
    n_genes: int | None = None
    response_format: ResponseFormat = "detailed"


class SimFindingsOut(_Open):
    """``sim_findings``: one page of the audit's saved findings."""

    study_id: str
    table: str
    file: str
    file_sha256: str
    total: int
    offset: int
    next_offset: int | None
    rows: list[dict[str, Any]]


__all__ = [
    "CardView",
    "CheckDesignOut",
    "CheckSheetOut",
    "ContrastView",
    "CurveCallsOut",
    "DecideOut",
    "EvidenceOut",
    "GateCheck",
    "GateOut",
    "ImportView",
    "IncidentLogOut",
    "InspectOut",
    "InstrumentHistoryOut",
    "InstrumentStatusOut",
    "LookbackOut",
    "PlanOut",
    "PrismDiffOut",
    "PrismPreviewOut",
    "ProposalsOut",
    "ProposeOut",
    "Refusal",
    "ResponseFormat",
    "RobustnessOut",
    "RunContextOut",
    "RunReviewOut",
    "SimAuditOut",
    "SimDecisionsOut",
    "SimFindingsOut",
    "SimGeneOut",
    "SimWhatifOut",
    "StudyOut",
    "TraceOut",
]
