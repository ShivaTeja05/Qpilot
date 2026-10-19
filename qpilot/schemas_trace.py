"""Data contract of Trace: from a result, a sample or a well to the well(s) to look at.

Produced by :mod:`qpilot.qpcr.trace`, consumed by the CLI (``qpilot trace``), the MCP tool
``qpcr_trace``, the app and the report. Contract: ``agent-bus/contracts/trace-api.md``.

Every number a person reads in a text field (``detail``, ``why``, ``summary`` …) is a
``{{fact_id}}`` token whose fact is in :attr:`TraceResult.facts`; the ``*_plain`` fields are the
same text rendered. Structured numeric fields carry the raw values those facts were made from,
and each object's ``facts`` maps a field name to its fact id.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from qpilot.schemas import Conclusion, Fact

TRACE_SCHEMA = "qpilot.trace/1"

Entry = Literal["gene", "sample", "well"]
Consequence = Literal["changes_call", "moves_number", "changes_nothing"]
CheckStatus = Literal["fail", "warn", "pass", "not_applicable"]
WellRole = Literal[
    "target", "reference", "marker", "candidate_reference", "ntc", "standard", "other"
]
PlaceKind = Literal["reference_well", "target_well", "sample", "empty_well", "plate_control"]
OptionId = Literal["set_aside", "read_from_other_references", "bring_back"]
LeftOutReason = Literal[
    "empty_reference",
    "empty_marker",
    "empty_target",
    "excluded",
    "not_in_groups",
    "not_measured_for_every_gene",
    "not_a_study_sample",
]


class TraceWell(BaseModel):
    """One well at a physical address, as the per-well table has it."""

    plate: str
    well: str
    sample: str
    unit: str
    gene: str
    role: WellRole
    sample_type: str
    cq: float | None = None
    n0: float | None = None
    eff: float | None = None
    note: str = ""
    excluded: bool = False
    plate_median_cq: float | None = None
    facts: dict[str, str] = {}


class TraceCheck(BaseModel):
    """One fingerprint check (S1 … S9) and what it found."""

    id: str
    name: str
    status: CheckStatus
    z: float | None = None
    detail: str = ""
    facts: list[str] = []


class CallChange(BaseModel):
    """A conclusion that a what-if changes."""

    gene: str
    call_before: Conclusion
    call_after: Conclusion
    log2fc_before: float
    log2fc_after: float
    p_before: float | None = None
    p_after: float | None = None


class TraceOption(BaseModel):
    """A what-if for one place; nothing is applied (applying one is a person's decision)."""

    id: OptionId
    label: str
    groups: Literal["fixed", "re-derived"] = "fixed"
    group_change: str | None = None
    d_log2fc: float | None = None
    changes: list[CallChange] = []
    fixed_groups_changes: list[CallChange] | None = None


class Place(BaseModel):
    """A place to look: a well (or a whole sample), what is unusual there and what it does."""

    rank: int
    kind: PlaceKind
    unit: str
    group: str | None = None
    path: list[str] = []
    wells: list[TraceWell] = []
    checks: list[TraceCheck] = []
    consequence: Consequence
    unit_shift_log2: float | None = None
    options: list[TraceOption] = []
    why: str = ""
    why_plain: str = ""
    facts: list[str] = []


class Influential(BaseModel):
    """A unit that moves the result and shows nothing unusual (do not exclude it for that)."""

    unit: str
    group: str | None = None
    d_log2fc: float
    changes_call: bool
    call_after: Conclusion
    note: str = ""
    facts: list[str] = []


class LeftOut(BaseModel):
    """A unit that is in no comparison (or not in this gene's), why, and the well behind it."""

    unit: str
    reason: LeftOutReason
    wells: list[TraceWell] = []
    detail: str = ""
    bring_back: TraceOption | None = None


class ConclusionNode(BaseModel):
    """The traced result: one gene's comparison in the primary analysis."""

    gene: str
    call: Conclusion
    log2fc: float
    fc: float
    ci: tuple[float, float]
    p: float
    n_a: int
    n_b: int
    margin_log2: float
    facts: dict[str, str] = {}


class UnitNode(BaseModel):
    """The traced sample: its unit, group, and where it stands."""

    unit: str
    samples: list[str]
    group: str | None = None
    in_comparisons: int
    n_items: int
    checks: list[TraceCheck] = []
    wells: list[TraceWell] = []
    facts: dict[str, str] = {}


class Dependent(BaseModel):
    """A conclusion that a traced well feeds, and what the well's what-ifs do to it."""

    gene: str
    unit: str
    via: Literal["target", "normaliser", "marker"]
    call: Conclusion
    d_log2fc_set_aside: float | None = None
    call_set_aside: Conclusion | None = None
    d_log2fc_expected: float | None = None
    call_expected: Conclusion | None = None


class TraceResult(BaseModel):
    """Everything Trace found for one entry (gene, sample or well)."""

    schema_version: str = TRACE_SCHEMA
    entry: Entry
    root: str
    study_id: str | None = None
    cell: dict[str, Any] = {}
    groups: tuple[str, str]
    rule: str
    thresholds: dict[str, float] = {}
    conclusion: ConclusionNode | None = None
    unit: UnitNode | None = None
    wells: list[TraceWell] = []
    dependents: list[Dependent] = []
    places: list[Place] = []
    influential: list[Influential] = []
    n_set_aside_flips: int = 0
    left_out: list[LeftOut] = []
    checked: list[str] = []
    cannot_show: list[str] = []
    summary: str = ""
    summary_plain: str = ""
    facts: dict[str, Fact] = {}
