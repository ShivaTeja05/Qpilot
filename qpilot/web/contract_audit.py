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

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from qpilot.web.contract import JobView

ShortText = Annotated[str, StringConstraints(max_length=200)]
"""A choice id, an option id or a gene name in a request (never longer)."""
Changes = Annotated[dict[ShortText, ShortText], Field(max_length=16)]
"""Choices to change: decision id → option id (at most one per decision)."""

CallKey = Literal["up", "down", "none"]
"""A call, as a key: ``up`` / ``down`` (higher / lower in the first group) or ``none``."""

AuditState = Literal[
    "none", "running", "ready", "refused", "not_applicable", "unavailable", "failed"
]


# ---- status and the run --------------------------------------------------------------------


class AuditReproduction(BaseModel):
    """The audit's contract: its planned analysis reproduces qPilot's stored result."""

    ok: bool
    genes: int
    genes_only_in_qpilot: list[str] = []
    genes_only_in_simulator: list[str] = []
    mismatched: list[str] = []
    max_abs_diff_log2fc: float
    max_abs_diff_p: float
    tolerance: float


class AuditReplicates(BaseModel):
    """How a design's technical replicates were audited (several wells per unit and gene)."""

    most_wells_per_value: int = Field(description="The most wells behind one unit's value.")
    values_with_several_wells: int = Field(description="Unit-and-gene values with 2+ wells.")
    values: int = Field(description="Unit-and-gene values in the audit.")
    wells: int = Field(description="Study wells behind them.")
    rule: Literal["mean"] = Field(description="The planned rule: qPilot's mean of log2 N0.")
    varied: bool = Field(
        description="The audit also varied how the wells are combined (three or more wells)."
    )
    words: str = Field(description="What was done, in plain words.")


class AuditComparisons(BaseModel):
    """A study with several comparisons: the one the audit audits, and that it is only that one."""

    audited: str = Field(description="The comparison audited (its id): the study's first.")
    audited_label: str
    n_comparisons: int
    correction: str
    note: str = Field(description="What the audit audits, in plain words.")


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
    technical_replicates: AuditReplicates | None = Field(
        default=None,
        description="Set when the design has technical replicates (absent with one well per "
        "unit and gene, as on the demo).",
    )
    comparisons: AuditComparisons | None = Field(
        default=None,
        description="Set for a study with several comparisons: the audit audits the first.",
    )


class AuditYourChoices(BaseModel):
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
    reproduces_qpilot: AuditReproduction
    lock_sha256: str | None
    grid_hash: str | None
    analyses: int | None = Field(description="Analyses run (every combination of choices).")
    verdict_counts: dict[str, int] = Field(description="Genes per verdict (verdict words).")
    your_choices: AuditYourChoices
    versions: dict[str, str]
    checksums_sha256: str = Field(description="SHA-256 of the audit's AUDIT.sha256 file.")
    created_at: float | None = Field(
        default=None, description="Unix time the audit was sealed (its AUDIT.sha256 written)."
    )
    seconds: float | None = Field(
        description="The simulator's own measured run time (summary.json timings); rebuilding "
        "the study first adds a few seconds."
    )


class AuditCheck(BaseModel):
    """Whether the audit applies to a study, found before it runs (its first step, alone)."""

    applicable: bool
    code: Literal["not_applicable", "refused"] | None = None
    reason: str | None = Field(default=None, description="Why not, in plain words.")
    scope: AuditScope | None = Field(
        default=None, description="What a run would cover (analyses, choices) for THIS study."
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
    check: AuditCheck | None = Field(
        default=None,
        description="Not run yet: whether it applies and what it would cover, once checked.",
    )
    checking: JobView | None = Field(
        default=None, description="Not run yet: the job checking it applies (~9 s on the demo)."
    )
    typical_s: float = Field(description="How long an audit usually takes on the demo, measured.")


class AuditRunResult(BaseModel):
    """The audit job's result (job kind ``audit``)."""

    study_id: str
    analyses: int | None
    verdict_counts: dict[str, int]
    reproduces_qpilot: bool
    seconds: float = Field(description="How long this run took, rebuilding included.")


class AuditLoadResult(BaseModel):
    """The result of loading the audit's live views (job kind ``audit.load``)."""

    study_id: str


class AuditRunRequest(BaseModel):
    """Start the audit; ``again`` replaces an existing one (the earlier one is kept beside it)."""

    again: bool = False


class AuditVerifyRequest(BaseModel):
    """Verify the audit; ``bind_to_record`` also checks it belongs to the study's record now."""

    bind_to_record: bool = True


class AuditFile(BaseModel):
    """One file of the audit, for download."""

    name: str
    bytes: int
    sha256: str | None = Field(description="As listed in AUDIT.sha256 (null for that file).")


class AuditFiles(BaseModel):
    """The audit's files (those its AUDIT.sha256 lists, and that list itself)."""

    files: list[AuditFile]


class AuditVerifyView(BaseModel):
    """The audit's checksums and manifest, and (when asked) its binding to the record."""

    ok: bool
    summary: str
    problems: list[str]
    files_checked: int
    files: list[AuditFile] = []
    checksums_sha256: str | None
    lock_sha256: str | None
    bound_to_record: bool = Field(description="Whether the record binding was checked.")
    audit_chain_head: str | None = None
    record_chain_head: str | None = None
    decisions_since: int | None = Field(
        default=None, description="Decisions in the record after the audited head."
    )
    head_in_chain: bool | None = Field(
        default=None, description="The audited head is in the study's decision chain."
    )
    is_current: bool | None = Field(
        default=None, description="No decision was made after the audit."
    )


# ---- the audit's views (qsim Screen dicts, typed) ----------------------------------------


class AuditStudyFacts(BaseModel):
    """The audited study in counts and the group words."""

    samples: int
    genes: int
    plates: int
    group: str = Field(description="The first group (calls are higher / lower in it).")
    group_def: str
    rest: str = Field(description="The second group, as a sentence says it ('the rest').")
    analyses: int
    reasonable: int
    references: list[str] = Field(
        default_factory=list,
        description="The planned reference genes, as named in the overview (origin/main, 18 Oct).",
    )


class AuditVerdictCount(BaseModel):
    """One verdict, its rule in words and how many genes got it."""

    key: str = Field(description="The verdict, as words ('holds with caveats').")
    label: str
    count: int
    rule: str


class AuditOverviewGene(BaseModel):
    """One gene's line in the overview."""

    gene: str
    fold: str
    call: CallKey
    call_key: CallKey
    verdict: str
    label: str
    headline: bool


class AuditOption(BaseModel):
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
    options: list[AuditOption]


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

    study: AuditStudyFacts
    verdicts: list[AuditVerdictCount]
    genes: list[AuditOverviewGene]
    headline: list[str]
    source: AuditSource
    decisions: list[AuditDecision]
    issues: list[AuditIssue]
    n_issues: int
    provenance: AuditProvenance


class AuditMapPoint(BaseModel):
    """One gene on the robustness map."""

    gene: str
    log2: float | None
    fold: str
    holds: int = Field(
        description="Percent (0–100) of the audit's reasonable analyses with the same call."
    )
    verdict: str
    headline: bool


class AuditChoiceSpread(BaseModel):
    """How much one choice matters across genes."""

    id: str
    name: str
    alone: int = Field(description="Genes whose call this choice changes on its own.")
    spread: int = Field(description="Share of the spread it explains, of 100.")
    question: bool


class AuditReference(BaseModel):
    """One control gene's geNorm M (as worded) and whether it differs between the groups."""

    gene: str
    m: str
    m_value: float | None = None
    differs: bool


class AuditInfluence(BaseModel):
    """Single samples and reference wells that change calls."""

    one_sample_genes: int | None
    ref_removals: str
    ref_removals_flip: int | None


class AuditStudyView(BaseModel):
    """The Study tab: map, choices, reference stability, fix-these-first, influence."""

    map: list[AuditMapPoint]
    choices: list[AuditChoiceSpread]
    references: list[AuditReference]
    stable_below: str
    reference_note: str
    lock_headline: list[str]
    lock_called: list[str]
    influence: AuditInfluence
    line_log2: float
    line: str


class AuditHowOption(BaseModel):
    """An option as the how-it-works page lists it."""

    label: str
    tier: str = Field(description="prespecified / defensible / common_practice")


class AuditHowDecision(BaseModel):
    """One choice at one stage of the pipeline."""

    name: str
    question: str
    planned: str
    n_options: int
    n_reasonable: int
    n_shortcut: int
    alone: int | None
    changes_question: bool
    options: list[AuditHowOption]
    more: int


class AuditHowStage(BaseModel):
    """One stage of the pipeline, in lab order."""

    title: str
    text: str
    decisions: list[AuditHowDecision]


class AuditPlantedFaults(BaseModel):
    """The planted-fault check, when the run made it."""

    trials: int
    changed: int
    caught: int


class AuditSmallDesign(BaseModel):
    """False-call rates in small experiments drawn from the data (percent, worded)."""

    size: str
    single: str
    filtered: str


class AuditKnownEfficiency(BaseModel):
    """One efficiency option's error on a dilution series with a known answer."""

    label: str
    error: float
    error_text: str
    planned: bool


class AuditSpreadWarns(BaseModel):
    """Error when the spread is in the top quarter vs otherwise (percent, worded)."""

    top: str
    other: str


class AuditKnownAnswers(BaseModel):
    """The known-answer test, when the run made it."""

    dataset: str
    cases: int
    efficiency: list[AuditKnownEfficiency]
    spread_warns: AuditSpreadWarns
    inside_range: int
    inside_ci: int


class AuditHow(BaseModel):
    """How it works: stages, the call rule, verdict rules, checks made and not made."""

    stages: list[AuditHowStage]
    call_rule: str
    total: str
    reasonable: int
    seconds: str
    rules: dict[str, str] = Field(description="Each verdict's rule, keyed by the verdict words.")
    faults: AuditPlantedFaults | None = None
    small: list[AuditSmallDesign] = []
    not_run: list[str] = []
    known: AuditKnownAnswers | None = None


class AuditTile(BaseModel):
    """One number tile of the gene card (worded)."""

    label: str
    value: str
    sub: str


class AuditGeneResult(BaseModel):
    """The result in sentences and the verdict's reason."""

    headline: str
    lines: list[str]
    verdict_sentence: str


class AuditHolds(BaseModel):
    """How often the same answer comes out."""

    n: int = Field(
        description="Percent (0–100) of the audit's reasonable analyses with the same call."
    )
    same: int = Field(description="How many of the audit's reasonable analyses have the same call.")
    of: int = Field(description="How many reasonable analyses the audit ran (144 on the demo).")
    lines: list[str]


class AuditChange(BaseModel):
    """A choice (or two together) that changes the call."""

    choice: str
    fold: str
    call: str
    call_key: CallKey
    same_call: bool


class AuditSingleSample(BaseModel):
    """A single sample whose removal changes the call."""

    sample: str
    plate: str
    well: str
    call: str
    call_key: CallKey


class AuditGeneCard(BaseModel):
    """One gene: result, verdict, what changes it, what it leans on, what to do."""

    tiles: list[AuditTile]
    gene: str
    call_key: CallKey
    verdict: str
    label: str
    headline_gene: bool
    result: AuditGeneResult
    holds: AuditHolds
    changes: list[AuditChange]
    no_changes: str | None
    shortcut: str | None
    leans: list[str]
    singles: list[AuditSingleSample]
    todo: list[str]


class AuditAnalysisRow(BaseModel):
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
    rows: list[AuditAnalysisRow]
    n: int
    n_same: int
    n_other: int
    base_call: str
    base_call_key: CallKey
    line_log2: float
    line: str


class AuditEffectOption(BaseModel):
    """One option with every other choice as planned."""

    label: str
    tier: str = Field(description="prespecified / defensible / common_practice")
    log2: float | None
    fold: str
    call: str
    call_key: CallKey
    changes_call: bool
    planned: bool


class AuditEffectDecision(BaseModel):
    """One choice, each option at a time."""

    id: str
    name: str
    options: list[AuditEffectOption]
    n_change: int


class AuditEffects(BaseModel):
    """One choice at a time for one gene."""

    gene: str
    planned_log2: float | None
    planned: str
    decisions: list[AuditEffectDecision]
    line_log2: float
    line: str


class AuditLabRow(BaseModel):
    """One lab parameter, worded."""

    label: str
    value: str


class AuditLabNumbers(BaseModel):
    """The lab parameters as numbers (``null`` when the data has none)."""

    n_high: int
    n_rest: int
    n_high_value: int = Field(description="Samples of the first group with a value (the p's n).")
    n_rest_value: int = Field(description="Samples of the second group with a value.")
    n_plates: int
    cq_median: float | None
    cq_min: float | None
    cq_max: float | None
    n_cq_above: dict[str, int] = Field(description="Wells with Cq above each late-Cq line.")
    n_nondetect: int
    eff_assay: float | None
    eff_std_curve: float | None
    n_flag_eff: int
    n_flag_low: int
    p: float | None


class AuditLab(BaseModel):
    """The assay's lab parameters and the planned control genes' stability."""

    gene: str
    rows: list[AuditLabRow]
    numbers: AuditLabNumbers
    references: list[AuditReference]
    refs_label: str
    stable_below: str


class AuditWhatIfRequest(BaseModel):
    """Choices to change (decision id → option id) and genes to mark as picked."""

    changes: Changes = Field(default_factory=dict)
    genes: list[ShortText] = Field(default_factory=list, max_length=2000)


class AuditWhatIfRow(BaseModel):
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
    rows: list[AuditWhatIfRow]
    n_changed: int
    n_genes: int
    changed_genes: list[str]
    line_log2: float
    line: str


class AuditSamplesRequest(BaseModel):
    """One gene's samples under a set of choices (decision id → option id)."""

    gene: ShortText
    changes: Changes = Field(default_factory=dict)


class AuditSamplePoint(BaseModel):
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


class AuditGroupStats(BaseModel):
    """One group's label, count, missing count and mean (log2, relative to the second)."""

    label: str
    n: int
    missing: int
    mean: float | None


class AuditSampleGroups(BaseModel):
    """The two groups (``high`` is the first group, ``rest`` the second)."""

    high: AuditGroupStats
    rest: AuditGroupStats


class AuditSamples(BaseModel):
    """One gene's samples (the beeswarm)."""

    gene: str
    points: list[AuditSamplePoint]
    groups: AuditSampleGroups
    fold: str
    fold_log2: float | None
    late_cut: str
    changes: list[str]
    line_log2: float
    line: str


class AuditIssues(BaseModel):
    """The whole investigation queue, in its order."""

    issues: list[AuditIssue]
    n_issues: int


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
    views_ready: bool = Field(default=False, description="Its live views are loaded.")
    loading: JobView | None = Field(
        default=None, description="The job loading its live views (started by opening it)."
    )


class AttachedAuditList(BaseModel):
    """Every attached results folder."""

    audits: list[AttachedAudit]
