"""What Trace returns: one gene's result followed down to its samples, wells and plates.

Produced by :func:`qpilot.trace.gene.trace_gene` and :func:`qpilot.trace.study.trace_study`;
served by ``GET /api/studies/{id}/trace/{gene}`` and ``GET /api/studies/{id}/trace`` (the page's
contract wraps these models, :mod:`qpilot.web.contract_trace`).

Every number is the engine's: each model carries the raw values, and each sentence a person
reads is a ``{{fact_id}}`` token text in :attr:`Traced.texts` with its facts in
:attr:`Traced.facts`, so the page shows every number in a sentence as a cited fact and
:func:`qpilot.core.validator.validate` passes with no naked number. Log2 values are on the
analysis' scale (relative quantity: log2 target minus the mean log2 of the control genes); a
fold change is ``2 ** log2``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

from qpilot.schemas import Fact

T = TypeVar("T", bound=BaseModel)

Call = Literal["up", "down", "none"]
Consequence = Literal["changes_call", "moves_number", "changes_nothing"]
WellRole = Literal[
    "target", "reference", "marker", "candidate_reference", "ntc", "standard", "other"
]
WellFlag = Literal[
    "no_amplification",
    "excluded",
    "late_cq",
    "efficiency_outlier",
    "reference_pull",
    "ntc_window",
    "curve_note",
]
SampleFlag = Literal[
    "reference_pull", "input_shift", "low_efficiency", "far_from_group", "ntc_window", "curve_note"
]
PlaceKind = Literal["reference_well", "target_well", "sample", "plate_control"]
OptionId = Literal["set_aside", "read_from_other_references", "set_aside_wells"]
MissingReason = Literal[
    "empty_target", "excluded", "empty_reference", "empty_marker", "not_in_groups"
]


class TraceCell(BaseModel):
    """The analysis traced: the options in use on each decision (the planned ones or a person's)."""

    refs: list[str] = Field(description="The control genes the values are normalised to.")
    cut: float | None = Field(default=None, description="The marker cut-off (marker split only).")
    undetermined: str = Field(description="What empty wells do: drop or cap.")
    amp_call: str | None = Field(default=None, description="Which curves count as amplified.")
    efficiency: str | None = Field(
        default=None,
        description="Which efficiency turns Cq into quantity (when a person asked to test it).",
    )
    planned: bool = Field(description="True when every option is the planned one.")


class TraceWell(BaseModel):
    """One well at a physical address, with what is unusual about it."""

    key: str = Field(description="`plate/well`, as the curve and plate routes take it.")
    plate: str
    well: str
    sample: str
    unit: str = Field(description="The biological sample (unit) the well belongs to.")
    gene: str
    role: WellRole
    sample_type: str
    cq: float | None = None
    efficiency: float | None = Field(
        default=None, description="The well's own efficiency (2.0 = 100 %)."
    )
    amplified: bool = Field(description="Counts as amplified under the analysis' rule.")
    excluded: bool = Field(description="A person excluded the well.")
    note: str = Field(default="", description="LinRegPCR's note on the well.")
    plate_median_cq: float | None = Field(
        default=None, description="Median Cq of the plate's study wells of this gene."
    )
    cq_z: float | None = Field(
        default=None, description="Robust z of the Cq against the plate's study wells of this gene."
    )
    efficiency_z: float | None = Field(
        default=None, description="Robust z of the efficiency against the same wells."
    )
    pull_log2: float | None = Field(
        default=None,
        description="Reference wells: how far this well moves every value of its sample (log2; + "
        "up), against what the sample's other control genes predict.",
    )
    reference_z: float | None = Field(
        default=None, description="Robust z of that disagreement over the study."
    )
    ntc_well: str | None = Field(
        default=None, description="The plate's earliest amplifying no-template control."
    )
    ntc_cq: float | None = None
    lowest_standard: str | None = Field(
        default=None, description="The plate's standard with the fewest copies."
    )
    lowest_standard_cq: float | None = None
    flags: list[WellFlag] = []


class TraceCall(BaseModel):
    """The traced result: one gene's comparison in the analysis in use."""

    conclusion: Call
    log2fc: float
    fc: float
    ci: tuple[float | None, float | None] = Field(description="95 % CI of the fold change.")
    p: float | None
    n_a: int
    n_b: int
    mean_a: float = Field(description="Mean relative value (log2) of the first group.")
    mean_b: float
    se: float = Field(description="Standard error of the log2 fold change.")
    line_log2: float = Field(description="The rule's line: at least this many log2 units.")
    margin_log2: float = Field(description="|log2 fold change| minus the line (negative: inside).")


class TraceCallChange(BaseModel):
    """A conclusion that a what-if changes."""

    gene: str
    call_before: Call
    call_after: Call
    log2fc_before: float
    log2fc_after: float
    p_before: float | None = None
    p_after: float | None = None


class TraceSample(BaseModel):
    """One biological sample's pull on the traced result (set aside alone, exact)."""

    unit: str
    group: str
    side: Literal["a", "b"]
    rank: int = Field(description="1 = moves the result most when set aside.")
    value_log2: float = Field(description="The sample's relative value for this gene (log2).")
    z_in_group: float | None = Field(
        default=None, description="Robust z of that value within its group."
    )
    d_log2fc: float = Field(description="Change of the log2 fold change when it is set aside.")
    log2fc_without: float
    p_without: float | None
    call_without: Call
    flips: bool = Field(description="Setting it aside alone changes the call.")
    flags: list[SampleFlag] = []
    plates: list[str] = Field(default=[], description="Plates of its wells behind this result.")
    wells: list[TraceWell] = Field(
        default=[], description="Its target and control-gene wells (detailed samples only)."
    )


class TraceFlipSet(BaseModel):
    """The fewest samples found whose removal together changes the call."""

    k: int | None = Field(description="How many (None: no set of up to `searched` samples).")
    exact: bool = Field(
        description="True when no smaller set exists (one and two are checked exhaustively)."
    )
    searched: int
    units: list[str]
    call_after: Call | None = None
    log2fc_after: float | None = None
    p_after: float | None = None


class TraceReference(BaseModel):
    """What one control gene does to this result."""

    gene: str
    share_log2: float = Field(
        description="Its exact additive part of the log2 fold change: minus its group difference "
        "divided by the number of control genes (the target's own difference is the rest)."
    )
    group_diff_log2: float = Field(description="Its own difference between the groups (log2).")
    without: TraceCallChange | None = Field(
        default=None, description="The result normalised to the other control genes only."
    )
    log2fc_without: float | None = None
    call_without: Call | None = None
    flagged: list[TraceWell] = Field(
        default=[], description="Its wells that disagree with their sample's other control genes."
    )


class TraceOption(BaseModel):
    """A what-if for one place; nothing is applied (applying one is a person's decision)."""

    id: OptionId
    label: str
    call_after: Call
    log2fc_after: float
    p_after: float | None
    d_log2fc: float
    changes: list[TraceCallChange] = Field(default=[], description="Every gene whose call changes.")
    regrouped: str | None = Field(default=None, description="How the groups change (marker split).")
    fixed_groups_changes: list[TraceCallChange] | None = None


class TracePlace(BaseModel):
    """A place to look: a well (or a whole sample), what is unusual there and what it does."""

    rank: int
    kind: PlaceKind
    unit: str
    group: str | None
    checks: list[str] = Field(description="Fingerprints found (S1 … S6).")
    consequence: Consequence
    d_log2fc: float
    wells: list[TraceWell]
    options: list[TraceOption]
    text: str = Field(description="Key of its sentence in `texts`.")


class TraceLookFirst(BaseModel):
    """The one well to look at first, and why (``kind`` none: nothing behind the result)."""

    kind: Literal["place", "influential", "none"]
    unit: str | None = None
    well: TraceWell | None = None
    place: int | None = Field(default=None, description="Rank of the place, when kind is place.")
    text: str = "look_first"


class TraceMissing(BaseModel):
    """A sample in the comparison groups with no value here, and the well(s) behind it."""

    unit: str
    reason: MissingReason
    group: str | None = None
    wells: list[TraceWell] = []


class TraceGene(BaseModel):
    """One gene's call followed down to its samples, wells and plates."""

    gene: str
    cell: TraceCell
    labels: tuple[str, str]
    rule: str
    call: TraceCall
    n_used: int
    n_flip_single: int = Field(
        description="Samples that each change the call when set aside alone."
    )
    flip: TraceFlipSet
    samples: list[TraceSample] = Field(
        description="Every sample in the comparison, most influential first."
    )
    references: list[TraceReference]
    places: list[TracePlace]
    look_first: TraceLookFirst
    influential_normal: list[str] = Field(
        description="Influential samples with nothing unusual (keep them for that)."
    )
    missing: list[TraceMissing]
    n_no_comparison: int = Field(description="Samples of the study in no comparison at all.")
    checked: list[str]
    cannot_show: list[str]
    replicates: bool
    thresholds: dict[str, float]


class TraceGeneRow(BaseModel):
    """One gene in the study-wide list, by how little it takes to change its call."""

    gene: str
    rank: int
    conclusion: Call
    log2fc: float
    fc: float
    p: float | None
    margin_log2: float
    n_flip_single: int
    flip_k: int | None
    flip_exact: bool
    flip_units: list[str]
    top_unit: str | None = Field(description="The sample that moves it most when set aside.")
    top_d_log2fc: float | None


class TraceSuspect(BaseModel):
    """A sample that moves many results, or whose wells show something unusual."""

    unit: str
    group: str | None
    rank: int
    n_genes_flipped: int = Field(description="Calls that change when it alone is set aside.")
    genes_flipped: list[str]
    n_genes_moved: int = Field(
        description="Calls whose fold change it moves by at least its yardstick."
    )
    max_abs_d_log2fc: float
    max_gene: str | None
    flags: list[SampleFlag]
    input_shift_log2: float | None = Field(
        default=None, description="S2: every gene's typical offset (log2)."
    )
    wells: list[TraceWell] = Field(default=[], description="Its unusual wells (with their plates).")
    plates: list[str]
    read_as_expected: list[TraceCallChange] | None = Field(
        default=None,
        description="Calls that change if its unusual control-gene well read as its other "
        "control genes predict.",
    )
    read_regrouped: str | None = Field(
        default=None,
        description="Marker split: how the groups change when that well is read as expected.",
    )
    read_groups_held: list[TraceCallChange] | None = Field(
        default=None,
        description="The calls that change when that well is read as expected and every sample "
        "keeps its group (given only when the groups would change).",
    )


class TraceStudy(BaseModel):
    """The study-wide view: genes by fragility, the samples behind the most results."""

    cell: TraceCell
    labels: tuple[str, str]
    rule: str
    n_units: int
    n_compared: int
    n_genes: int
    n_fragile: int = Field(description="Genes that one sample set aside changes.")
    genes: list[TraceGeneRow]
    suspects: list[TraceSuspect]
    left_out: list[TraceMissing] = Field(
        description="Samples in no comparison, and the well behind each."
    )
    checked: list[str]
    cannot_show: list[str]
    thresholds: dict[str, float]


class TracePlate(BaseModel):
    """Every well of one plate, as Trace reads it (for the plate map next to a trace)."""

    run: str
    genes: list[str]
    wells: list[TraceWell]


class TraceWithout(BaseModel):
    """One gene recomputed with some samples set aside together (exact), and what else changes."""

    gene: str
    units: list[str]
    before: TraceCall
    after: TraceCall
    changes_call: bool
    other_changes: list[TraceCallChange] = Field(description="Other genes whose call changes too.")


@dataclass(frozen=True)
class Traced(Generic[T]):
    """A trace and its sentences: ``texts`` (text id -> token text) cite ``facts``."""

    data: T
    texts: dict[str, str]
    facts: dict[str, Fact]

    def plain(self, text_id: str) -> str:
        """One sentence with its facts written out."""
        from qpilot.core.validator import render_tokens

        return render_tokens(self.texts[text_id], self.facts)
