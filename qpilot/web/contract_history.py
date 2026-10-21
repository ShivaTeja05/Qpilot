"""Response models of the History routes: the decision chain replayed, step by step.

Owned by the ``history`` router (:mod:`qpilot.web.routers.history`); built by
:mod:`qpilot.history`. Every conclusion here is read from the study's own robustness grid
(``grid.csv``) or its stored results, under the choices in force at that point of the chain —
never estimated. Like :mod:`qpilot.web.contract`, every string is text (never HTML). Keep changes
additive and regenerate the frontend's types (``npm run gen:api``) with them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from qpilot.web.contract import CarriedFrom

Conclusion = Literal["up", "down", "none"]
Actor = Literal["human", "agent", "system"]
EntryStatus = Literal["applied", "auto", "pending_human", "rejected", "stale"]
Stage = Literal["design", "curves", "choices", "prism", "other"]


# ---- one analysis: every gene under one set of choices ----------------------------------------


class HistoryGene(BaseModel):
    """One gene under one analysis (one cell of the study's grid)."""

    gene: str
    log2fc: float | None = Field(description="null where the engine computed none.")
    fc: float | None
    p: float | None = Field(description="null where the engine computed none.")
    conclusion: Conclusion | None
    holds: float | None = Field(
        description="Share (0–1) of the grid's analyses that give this same call."
    )


class HistoryChoice(BaseModel):
    """One analysis choice (a grid dimension) and the option an analysis uses."""

    dimension: str
    title: str = Field(description="The choice in words.")
    value: str = Field(description="The option as the grid writes it.")
    label: str = Field(description="The option in words (the card's label when a card has it).")
    planned: bool = Field(description="The option of the analysis as planned.")


class HistoryAnalysis(BaseModel):
    """One distinct analysis that some step of the chain had in force."""

    index: int
    planned: bool = Field(description="The analysis as planned (every choice as recommended).")
    choices: list[HistoryChoice]
    genes: list[HistoryGene] = Field(description="Aligned with HistoryView.genes.")
    counts: dict[str, int] = Field(description="Genes called up / down / none.")


# ---- the chain, step by step -------------------------------------------------------------------


class ChoiceInForce(BaseModel):
    """A Decision Card's state at one step of the chain."""

    card_id: str
    title: str
    dimension: str | None
    option: str = Field(description="The option in force (the planned one while undecided).")
    option_label: str
    planned: bool = Field(description="The option in force is the planned (recommended) one.")
    decided: bool = Field(description="Someone had decided this card by this step.")
    decided_by: Actor | None = None
    status: str = Field(description="open, decided, auto_decided or pending_human.")


class StepConclusions(BaseModel):
    """The calls at one step, and what changed from the step before."""

    up: int
    down: int
    none: int
    n_changed: int = Field(description="Genes whose call differs from the step before.")
    changed: list[str] = Field(description="Those genes, by name.")
    n_moved: int = Field(
        description="Genes whose fold change moved (by more than 1e-9 in log2) from the step "
        "before, whether or not their call changed."
    )


class HistoryStep(BaseModel):
    """One point of the chain: 0 is the study as analysed, then one per decision entry."""

    seq: int = Field(description="0: as analysed (the chain's root); then the entry's seq.")
    kind: Literal["start", "decision"]
    at: str | None = None
    actor: Actor | None = None
    card_id: str | None = None
    card_title: str | None = None
    option: str | None = None
    option_label: str | None = None
    reason: str | None = Field(default=None, description="Quoted text from whoever decided.")
    status: EntryStatus | None = None
    undo: bool = Field(default=False, description="Written by Undo.")
    carried: CarriedFrom | None = Field(
        default=None,
        description="A person's decision carried from an earlier analysis (reason: their words).",
    )
    hash: str = Field(description="The entry's hash (step 0: the input file's sha256).")
    prev_hash: str | None = None
    link_ok: bool = Field(description="This entry's link and hash re-computed on the server.")
    chain_intact: bool = Field(description="Every entry up to this one verifies.")
    analysis: int | None = Field(
        default=None, description="Index into HistoryView.analyses; null when not replayable."
    )
    choices: list[ChoiceInForce]
    conclusions: StepConclusions | None = None
    effect: str = Field(description="What this step changed, in plain words.")
    audited: bool = Field(default=False, description="The robustness audit was run at this step.")


# ---- the Studio log around the chain -----------------------------------------------------------


class MilestoneItem(BaseModel):
    """One kind of action within a Studio milestone (e.g. 53 sample roles accepted)."""

    kind: str = Field(description="The proposal kind (design.well_role, stage.confirm, …).")
    title: str = Field(description="The kind in words.")
    action: Literal["propose", "accept", "edit", "reject", "supersede"]
    n: int
    actors: dict[str, int] = Field(description="Who acted: human / agent / system → count.")
    reasons: list[str] = Field(description="Distinct reasons given (up to three), quoted text.")
    subjects: list[str] = Field(description="What it was about (up to three), quoted text.")


class StudioMilestone(BaseModel):
    """A run of the Studio session's proposal log on one stage (design, curves, …)."""

    stage: Stage
    title: str
    first_seq: int
    last_seq: int
    at_first: str
    at_last: str
    n_proposed: int
    n_accepted: int
    n_rejected: int
    n_edited: int
    n_superseded: int
    confirmed: bool = Field(description="The stage was confirmed by a person in this run.")
    head: str = Field(description="The proposal chain's hash after this run.")
    chain_intact: bool = Field(description="The proposal chain verifies up to this run.")
    before: bool = Field(description="Happened before this analysis was made.")
    after_seq: int | None = Field(
        default=None,
        description="When not before: placed after this step of the decision chain.",
    )
    led_to: str | None = Field(
        default=None, description="The study this run's last acceptance produced, if any."
    )
    items: list[MilestoneItem]


class RelatedStudy(BaseModel):
    """Another analysis of the same input file (another design of it)."""

    study_id: str
    created_at: str | None
    design_hash: str | None = None
    current: bool = Field(description="The session's analysis of the design confirmed now.")
    after: str | None = Field(
        default=None, description="What it was made after, in words (the Studio step)."
    )
    n_entries: int


class CarryCard(BaseModel):
    """One card a person had decided in the earlier analysis, and what became of it here."""

    card_id: str
    card_title: str
    option: str | None = Field(default=None, description="What the person had chosen there.")
    option_label: str | None = None
    why: str | None = Field(default=None, description="Why it is asked again, in words.")


class CarryNote(BaseModel):
    """What a person had decided in the analysis before this one, carried here or asked again.

    The choices stage is never carried: a person confirms the new analysis's choices again.
    """

    from_study: str = Field(description="The session's analysis before this one.")
    carried: list[CarryCard] = Field(description="Carried as new entries (see the steps).")
    asked_again: list[CarryCard] = Field(description="Not carried: the choice matters more here.")
    gone: list[CarryCard] = Field(description="The card or the option is not in this analysis.")


class AuditMark(BaseModel):
    """Where the robustness audit sits on the chain."""

    chain_head: str
    step: int | None = Field(description="The step whose hash the audit was run at.")
    current: bool = Field(description="The audit is of the chain head of now.")


class HistoryView(BaseModel):
    """A study's decision chain replayed: every step, the analysis in force and its calls."""

    study_id: str
    session: str | None = None
    input_sha256: str
    head: str
    root: str = Field(description="The chain's genesis: the input file's sha256.")
    chain_intact: bool
    broken_at: int | None = Field(default=None, description="The first entry that fails.")
    created_at: str | None = Field(default=None, description="When this analysis was made.")
    replayable: bool = Field(
        description="The study's grid holds the planned analysis, so each step can be replayed."
    )
    note: str | None = Field(default=None, description="Why a step cannot be replayed, if so.")
    n_cells: int | None = Field(default=None, description="Analyses in the study's grid.")
    min_log2fc: float = Field(description="The call rule's minimum |log2 fold|.")
    alpha: float
    groups: list[str] = Field(description="The compared group, then the reference group.")
    genes: list[str]
    headline: list[str]
    analyses: list[HistoryAnalysis]
    steps: list[HistoryStep]
    studio: list[StudioMilestone] = Field(description="The session's Studio log, by stage run.")
    studio_intact: bool = True
    related: list[RelatedStudy] = Field(description="Other analyses of the same input file.")
    carry: CarryNote | None = Field(
        default=None,
        description="A person's decisions from the session's analysis before this one.",
    )
    audit: AuditMark | None = None


# ---- diff two steps ----------------------------------------------------------------------------


class GeneChange(BaseModel):
    """One gene at two points: its call, fold, p and share of analyses with the same call."""

    gene: str
    headline: bool = False
    from_conclusion: Conclusion | None
    to_conclusion: Conclusion | None
    from_log2fc: float | None
    to_log2fc: float | None
    from_p: float | None
    to_p: float | None
    from_holds: float | None
    to_holds: float | None
    delta_log2fc: float | None = Field(description="to − from, log2.")
    call_changed: bool
    verdict: str | None = Field(default=None, description="The audit's verdict, when audited.")
    verdict_label: str | None = None
    cause: Literal["design", "choices", "both", "unknown"] | None = Field(
        default=None,
        description="(compare only) whether the design, the choices, or both moved this gene.",
    )


class ChoiceChange(BaseModel):
    """A Decision Card whose option in force differs between two points."""

    card_id: str
    title: str
    from_option: str
    from_label: str
    to_option: str
    to_label: str


class HistoryDiff(BaseModel):
    """What changed between two steps of the chain (or two analyses of the same file)."""

    study_id: str
    from_seq: int
    to_seq: int
    same_analysis: bool = Field(description="Both steps had the same analysis in force.")
    choices: list[ChoiceChange]
    from_counts: dict[str, int]
    to_counts: dict[str, int]
    calls_changed: list[GeneChange] = Field(description="Every gene whose call changed.")
    fold_moves: list[GeneChange] = Field(
        description="The genes whose fold change moved most (up to 12), largest first."
    )
    holds_moves: list[GeneChange] = Field(
        description="The genes whose share of same-call analyses moved most (up to 12)."
    )
    n_moved: int = Field(description="Genes whose fold change moved at all.")
    summary: str = Field(description="The change in one sentence.")
    audit_note: str | None = Field(
        default=None, description="Which step the audit's verdicts are of, when audited."
    )


# ---- compare two analyses of the same input ----------------------------------------------------


class DesignChange(BaseModel):
    """One field of the confirmed design that differs between two analyses."""

    field: str
    title: str = Field(description="The field in words.")
    added: list[str] = Field(default=[], description="List items only in the later analysis.")
    removed: list[str] = Field(default=[], description="List items only in the earlier one.")
    before: str | None = Field(default=None, description="A scalar value before, as text.")
    after: str | None = None


class CompareSide(BaseModel):
    """One of the two analyses compared, at its chain head."""

    study_id: str
    created_at: str | None
    head: str
    n_entries: int
    design_hash: str | None
    counts: dict[str, int]
    choices: list[ChoiceInForce]
    current: bool = Field(description="The session's analysis of the design confirmed now.")


class HistoryCompare(BaseModel):
    """Two analyses of the same input file: which conclusions differ, and why."""

    input_sha256: str
    before: CompareSide = Field(description="The earlier analysis.")
    after: CompareSide = Field(description="The later analysis.")
    design: list[DesignChange]
    choices: list[ChoiceChange] = Field(description="Cards whose option in force differs.")
    calls_changed: list[GeneChange]
    fold_moves: list[GeneChange]
    holds_moves: list[GeneChange]
    n_moved: int
    genes_only_before: list[str]
    genes_only_after: list[str]
    decomposed: bool = Field(
        description="The later analysis' grid has the earlier one's choices, so each change is "
        "split into what the design did and what the choices did."
    )
    by_design: int = Field(description="Calls changed by the design alone (same choices).")
    by_choices: int = Field(description="Calls changed by the choices alone (same design).")
    summary: str
