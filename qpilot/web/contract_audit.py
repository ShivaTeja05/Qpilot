"""The robustness audit's part of the API contract: status, the run, and the audit's views.

The views are the Decision Simulator's own results-screen dicts (:class:`qsim.app.Screen`),
typed here key for key: same keys, same values, nothing re-shaped. Two keys are left out: the
screen's ``model`` status (the page has its own model chip) and the gene card's ``evidence``
link (there is no separate HTML page). Numbers a sentence needs come pre-worded (``fold``,
``line``, ``value``); the raw numbers charts need sit beside them (``log2``, ``line_log2``,
``call_key``). A number the engine cannot compute is ``null``, never NaN.

Every string is text: names come from the study's file and are shown as text.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from qpilot.web.contract import JobView

CallKey = Literal["up", "down", "none"]
"""A call, as a key: ``up`` / ``down`` (higher / lower in the first group) or ``none``."""

AuditState = Literal[
    "none", "running", "ready", "refused", "not_applicable", "unavailable", "failed"
]


# ---- status and the run --------------------------------------------------------------------


class Reproduction(BaseModel):
    """The audit's contract: its planned analysis reproduces qPilot's stored result."""

    ok: bool
    genes: int
    genes_only_in_qpilot: list[str] = []
    genes_only_in_simulator: list[str] = []
    mismatched: list[str] = []
    max_abs_diff_log2fc: float
    max_abs_diff_p: float
    tolerance: float


class AuditScope(BaseModel):
    """What was audited: the comparison, the samples and the choices varied."""

    mode: Literal["groups", "marker_split"]
    groups: list[str] = Field(description="The two groups compared: [first, second].")
    n_samples: int
    n_genes_compared: int
    n_in_groups: list[int]
    control_gene_candidates: list[str]
    prespecified_control_genes: list[str]
    amplification_rule: str
    wells_excluded_by_a_person: int
    undetermined_aligned: int
    decisions: dict[str, list[str]] = Field(description="Each choice varied and its options.")
    reference_sets: int
    analyses_in_full_grid: int


class YourChoices(BaseModel):
    """The analysis chosen on the Decision Cards against the prespecified one."""

    changes_from_prespecified: dict[str, str] = {}
    no_simulator_counterpart: list[str] = []
    calls_that_differ: list[str] = []


class AuditManifestView(BaseModel):
    """A finished audit: what it audited, how it is bound to the study, and what it found."""

    study_id: str
    input_sha256: str
    chain_head: str | None = Field(description="The decision chain's head when audited.")
    design_hash: str | None
    source_file: str
    scope: AuditScope
    reproduces_qpilot: Reproduction
    lock_sha256: str | None
    grid_hash: str | None
    analyses: int | None = Field(description="Analyses run (every combination of choices).")
    verdict_counts: dict[str, int] = Field(description="Genes per verdict (verdict words).")
    your_choices: YourChoices
    versions: dict[str, str]
    checksums_sha256: str = Field(description="SHA-256 of the audit's AUDIT.sha256 file.")
    seconds: float | None = Field(
        description="The simulator's own measured run time (summary.json timings); rebuilding "
        "the study first adds a few seconds."
    )


class AuditStatus(BaseModel):
    """Whether a study has an audit, one is running, or why it cannot have one."""

    study_id: str
    status: AuditState
    reason: str | None = Field(
        default=None,
        description="Why not, in plain words (refused, not applicable, unavailable, failed).",
    )
    job: JobView | None = Field(default=None, description="The running (or failed) audit job.")
    manifest: AuditManifestView | None = None
    current: bool | None = Field(
        default=None,
        description="Ready: true when no decision was made on the study since it was audited.",
    )
    decisions_since: int = Field(default=0, description="Decisions made after the audit.")
    views_ready: bool = Field(
        default=False,
        description="Ready: the live views are loaded (the first load rebuilds the study, ~15 s "
        "on the demo; the audit views wait for it).",
    )
    loading: JobView | None = Field(default=None, description="The job loading the live views.")
    typical_s: float = Field(description="How long an audit usually takes on the demo, measured.")


class AuditRunRequest(BaseModel):
    """Start the audit; ``again`` replaces an existing one (the earlier one is kept beside it)."""

    again: bool = False


class AuditVerifyRequest(BaseModel):
    """Verify the audit; ``bind_to_record`` also checks it belongs to the study's record now."""

    bind_to_record: bool = True


class AuditVerifyView(BaseModel):
    """The audit's checksums and manifest, and (when asked) its binding to the record."""

    ok: bool
    summary: str
    problems: list[str]
    files_checked: int
    checksums_sha256: str | None
    lock_sha256: str | None
    bound_to_record: bool = Field(description="Whether the record binding was checked.")
    audit_chain_head: str | None = None
    record_chain_head: str | None = None
    decisions_since: int | None = Field(
        default=None, description="Decisions in the record after the audited head."
    )


# ---- the audit's views (qsim Screen dicts, typed) ----------------------------------------


class StudyFacts(BaseModel):
    """The audited study in counts and the group words."""

    samples: int
    genes: int
    plates: int
    group: str = Field(description="The first group (calls are higher / lower in it).")
    group_def: str
    rest: str = Field(description="The second group, as a sentence says it ('the rest').")
    analyses: int
    reasonable: int


class VerdictCount(BaseModel):
    """One verdict, its rule in words and how many genes got it."""

    key: str = Field(description="The verdict, as words ('holds with caveats').")
    label: str
    count: int
    rule: str


class OverviewGene(BaseModel):
    """One gene's line in the overview."""

    gene: str
    fold: str
    call: CallKey
    call_key: CallKey
    verdict: str
    label: str
    headline: bool


class DecisionOption(BaseModel):
    """One option of an analysis choice."""

    id: str
    label: str
    tier: str = Field(description="In words: your planned analysis / reasonable / shortcut.")


class AuditDecision(BaseModel):
    """One analysis choice the audit varies (the what-if lab's selects)."""

    id: str
    name: str
    question: str
    changes_claim: bool
    baseline: str = Field(description="The planned option's id.")
    options: list[DecisionOption]


class AuditIssue(BaseModel):
    """One item of the investigation queue."""

    id: str
    title: str
    about: str
    action: str
    changes: list[str] = Field(description="Genes whose call changes when it is fixed.")
    headline: list[str]
    causes: list[str]
    wells: list[str]
    samples: list[str]
    plate: str


class AuditSource(BaseModel):
    """Which file the audit describes."""

    name: str
    benchmark: bool


class AuditProvenance(BaseModel):
    """Short hashes and the files the run wrote."""

    run: str
    lock: str
    input: str
    qsim: str
    files: list[str]


class AuditOverview(BaseModel):
    """The audit's first screen: the study, verdict counts, genes, choices, top issues."""

    study: StudyFacts
    verdicts: list[VerdictCount]
    genes: list[OverviewGene]
    headline: list[str]
    source: AuditSource
    decisions: list[AuditDecision]
    issues: list[AuditIssue]
    n_issues: int
    provenance: AuditProvenance


class MapPoint(BaseModel):
    """One gene on the robustness map."""

    gene: str
    log2: float | None
    fold: str
    holds: int = Field(description="Reasonable analyses with the same call, of 100.")
    verdict: str
    headline: bool


class ChoiceSpread(BaseModel):
    """How much one choice matters across genes."""

    id: str
    name: str
    alone: int = Field(description="Genes whose call this choice changes on its own.")
    spread: int = Field(description="Share of the spread it explains, of 100.")
    question: bool


class ReferenceStability(BaseModel):
    """One control gene's geNorm M (as worded) and whether it differs between the groups."""

    gene: str
    m: str
    differs: bool


class Influence(BaseModel):
    """Single samples and reference wells that change calls."""

    one_sample_genes: int | None
    ref_removals: str
    ref_removals_flip: int | None


class AuditStudyView(BaseModel):
    """The Study tab: map, choices, reference stability, fix-these-first, influence."""

    map: list[MapPoint]
    choices: list[ChoiceSpread]
    references: list[ReferenceStability]
    stable_below: str
    reference_note: str
    lock_headline: list[str]
    lock_called: list[str]
    influence: Influence
    line_log2: float
    line: str


class HowOption(BaseModel):
    """An option as the how-it-works page lists it."""

    label: str
    tier: str = Field(description="prespecified / defensible / common_practice")


class HowDecision(BaseModel):
    """One choice at one stage of the pipeline."""

    name: str
    question: str
    planned: str
    n_options: int
    n_reasonable: int
    n_shortcut: int
    alone: int | None
    changes_question: bool
    options: list[HowOption]
    more: int


class HowStage(BaseModel):
    """One stage of the pipeline, in lab order."""

    title: str
    text: str
    decisions: list[HowDecision]


class PlantedFaults(BaseModel):
    """The planted-fault check, when the run made it."""

    trials: int
    changed: int
    caught: int


class SmallDesign(BaseModel):
    """False-call rates in small experiments drawn from the data (percent, worded)."""

    size: str
    single: str
    filtered: str


class KnownEfficiency(BaseModel):
    """One efficiency option's error on a dilution series with a known answer."""

    label: str
    error: float
    error_text: str
    planned: bool


class SpreadWarns(BaseModel):
    """Error when the spread is in the top quarter vs otherwise (percent, worded)."""

    top: str
    other: str


class KnownAnswers(BaseModel):
    """The known-answer test, when the run made it."""

    dataset: str
    cases: int
    efficiency: list[KnownEfficiency]
    spread_warns: SpreadWarns
    inside_range: int
    inside_ci: int


class AuditHow(BaseModel):
    """How it works: stages, the call rule, verdict rules, checks made and not made."""

    stages: list[HowStage]
    call_rule: str
    total: str
    reasonable: int
    seconds: str
    rules: dict[str, str] = Field(description="Each verdict's rule, keyed by the verdict words.")
    faults: PlantedFaults | None = None
    small: list[SmallDesign] = []
    not_run: list[str] = []
    known: KnownAnswers | None = None


class Tile(BaseModel):
    """One number tile of the gene card (worded)."""

    label: str
    value: str
    sub: str


class GeneResult(BaseModel):
    """The result in sentences and the verdict's reason."""

    headline: str
    lines: list[str]
    verdict_sentence: str


class HoldsBlock(BaseModel):
    """How often the same answer comes out."""

    n: int = Field(description="Reasonable analyses with the same call, of 100.")
    lines: list[str]


class ChangeRow(BaseModel):
    """A choice (or two together) that changes the call."""

    choice: str
    fold: str
    call: str
    call_key: CallKey
    same_call: bool


class SingleSample(BaseModel):
    """A single sample whose removal changes the call."""

    sample: str
    plate: str
    well: str
    call: str
    call_key: CallKey


class AuditGeneCard(BaseModel):
    """One gene: result, verdict, what changes it, what it leans on, what to do."""

    tiles: list[Tile]
    gene: str
    call_key: CallKey
    verdict: str
    label: str
    headline_gene: bool
    result: GeneResult
    holds: HoldsBlock
    changes: list[ChangeRow]
    no_changes: str | None
    shortcut: str | None
    leans: list[str]
    singles: list[SingleSample]
    todo: list[str]


class AnalysisRow(BaseModel):
    """One reasonable analysis of one gene."""

    log2: float | None
    fold: str
    call: str
    call_key: CallKey
    same: bool
    choices: list[str] = Field(description="What differs from the planned analysis.")
    planned: bool


class AuditAnalyses(BaseModel):
    """Every reasonable analysis of one gene (the analyses strip)."""

    gene: str
    rows: list[AnalysisRow]
    n: int
    n_same: int
    n_other: int
    base_call: str
    base_call_key: CallKey
    line_log2: float
    line: str


class EffectOption(BaseModel):
    """One option with every other choice as planned."""

    label: str
    tier: str = Field(description="prespecified / defensible / common_practice")
    log2: float | None
    fold: str
    call: str
    call_key: CallKey
    changes_call: bool
    planned: bool


class EffectDecision(BaseModel):
    """One choice, each option at a time."""

    id: str
    name: str
    options: list[EffectOption]
    n_change: int


class AuditEffects(BaseModel):
    """One choice at a time for one gene."""

    gene: str
    planned_log2: float | None
    planned: str
    decisions: list[EffectDecision]
    line_log2: float
    line: str


class LabRow(BaseModel):
    """One lab parameter, worded."""

    label: str
    value: str


class AuditLab(BaseModel):
    """The assay's lab parameters and the planned control genes' stability."""

    gene: str
    rows: list[LabRow]
    references: list[ReferenceStability]
    refs_label: str
    stable_below: str


class WhatIfRequest(BaseModel):
    """Choices to change (decision id → option id) and genes to mark as picked."""

    changes: dict[str, str] = Field(default_factory=dict, max_length=16)
    genes: list[str] = Field(default_factory=list, max_length=2000)


class WhatIfRow(BaseModel):
    """One gene, planned → chosen."""

    gene: str
    headline: bool
    picked: bool
    verdict: str
    base: str
    base_call: str
    base_call_key: CallKey
    new: str
    new_call: str
    new_call_key: CallKey
    base_log2: float | None
    new_log2: float | None
    changed: bool


class AuditWhatIf(BaseModel):
    """Every gene under the chosen options, changed calls counted."""

    changes: list[str] = Field(description="The options chosen, as labels.")
    rows: list[WhatIfRow]
    n_changed: int
    n_genes: int
    changed_genes: list[str]
    line_log2: float
    line: str


class SamplesRequest(BaseModel):
    """One gene's samples under a set of choices (decision id → option id)."""

    gene: str = Field(max_length=200)
    changes: dict[str, str] = Field(default_factory=dict, max_length=16)


class SamplePoint(BaseModel):
    """One sample's value relative to the second group's mean."""

    x: float | None
    group: Literal["high", "rest"]
    sample: str
    plate: str
    well: str
    cq: str | None
    late: bool
    nondetect: bool
    flagged: bool
    carries: bool
    value: str


class GroupStats(BaseModel):
    """One group's label, count, missing count and mean (log2, relative to the second)."""

    label: str
    n: int
    missing: int
    mean: float | None


class SampleGroups(BaseModel):
    """The two groups (``high`` is the first group, ``rest`` the second)."""

    high: GroupStats
    rest: GroupStats


class AuditSamples(BaseModel):
    """One gene's samples (the beeswarm)."""

    gene: str
    points: list[SamplePoint]
    groups: SampleGroups
    fold: str
    fold_log2: float | None
    late_cut: str
    changes: list[str]
    line_log2: float
    line: str


# ---- attached audits (``qpilot app --audit DIR``) -----------------------------------------


class AttachedAudit(BaseModel):
    """A results folder attached read-only when the server started."""

    name: str
    source: str = Field(description="The file the run describes.")
    qpilot_audit: bool = Field(description="A qPilot audit (bound to a study), not a plain run.")
    study_id: str | None = None
    available: bool = Field(description="Whether its views can be shown.")
    reason: str | None = Field(default=None, description="Why not, in plain words.")
    analyses: int | None = None
    verdict_counts: dict[str, int] = {}


class AttachedAuditList(BaseModel):
    """Every attached results folder."""

    audits: list[AttachedAudit]
