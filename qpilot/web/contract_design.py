"""Response models of the Design page's own editing (``routers/design.py``).

A person sets design items the rules and the model did not propose (a target's role, a sample's
type, group and biological unit, the comparison): each is checked by the engine first
(``POST …/design/check``, which writes nothing), then recorded as the person's own proposal,
accepted in the same act with one reason (``POST …/design/set``). See ``qpilot/studio_design.py``.

Blind-safe: nothing here carries a Cq or any number computed from one; the editor's view has
names, declared types, wells, counts and the design so far.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from qpilot.schemas_studio import ProposalCheck, ProposalOutcome
from qpilot.web.contract import JobView, StageView

DesignKind = Literal[
    "design.target_role",
    "design.well_role",
    "design.group",
    "design.bio_unit",
    "design.dilution_series",
    "design.comparison",
    "design.purpose",
]
PlanAction = Literal["new", "accept", "keep", "unchanged", "refused"]
NeedWhere = Literal["targets", "samples", "comparison", "inbox", "engine"]


class DesignEditItem(BaseModel):
    """One design item a person sets: the proposal kind, its subject and its payload.

    Payloads: ``design.target_role`` ``{"role": "ref"|"toi"|"ignore"}`` (subject: a target);
    ``design.well_role`` ``{"role": "unkn"|"ntc"|"nrt"|"nac"|"pos"|"ntp"|"opt"}`` (a sample);
    ``design.group`` ``{"group": str | null}`` (a sample; null takes it out of every group);
    ``design.bio_unit`` ``{"biological_unit": str | null}`` (a sample; null: its own unit);
    ``design.dilution_series`` ``{"experiment_id": str, "samples": {sample: quantity}}``
    (subject: the series' name; its samples become standards with these quantities);
    ``design.comparison`` ``{"group_a": str, "group_b": str}`` (subject ``comparison``;
    fold change = group_a relative to group_b, the reference group); several comparisons add
    ``comparisons`` (``[{group_a, group_b}, ...]``, the first is ``group_a``/``group_b``),
    ``pattern`` (``vs_control``, ``all_pairs`` or ``chosen``), ``control``, ``correction``
    (``holm``, ``dunnett``, ``tukey`` or ``none``) and ``pair_by`` (the accepted pairing's name);
    ``design.purpose`` ``{"purpose": "compare"|"quantify"}`` (subject ``purpose``): what the study
    is for (compare groups, the default; or quantify samples from a standard curve: no
    comparison and no reference gene needed).
    """

    kind: DesignKind
    subject: str = Field(min_length=1, max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)


class DesignCheckRequest(BaseModel):
    """``POST …/design/check``: what recording these items would do (nothing is written)."""

    items: list[DesignEditItem] = Field(min_length=1, max_length=2000)


class DesignSetRequest(BaseModel):
    """``POST …/design/set``: record these items as the person's decisions, with one reason."""

    items: list[DesignEditItem] = Field(min_length=1, max_length=2000)
    reason: str = Field(
        default="",
        max_length=2000,
        description="Why (kept with every item in the record); required.",
    )
    expected_head: str | None = Field(
        default=None, description="The inbox head the page showed (409 stale when it moved)."
    )
    accept_contradicted: bool = Field(
        default=False,
        description="Record items the engine's check contradicts (the person read why).",
    )


class PlannedItemView(BaseModel):
    """What recording one item does, with the engine's check, before anything is written."""

    kind: DesignKind
    subject: str
    payload: dict[str, Any]
    action: PlanAction = Field(
        description="new: your own proposal, accepted · accept: a waiting proposal that says "
        "the same is accepted · keep: the design already says so (waiting proposals that say "
        "otherwise are rejected) · unchanged: nothing to record · refused: see refusal."
    )
    words: str = Field(description="The item in plain words.")
    check: ProposalCheck | None = None
    refusal: str | None = None
    accept_id: str | None = None
    rejects: list[str] = []
    also_accept: list[str] = []


class DesignPlanView(BaseModel):
    """The plan of one act on the inbox at ``head`` (``POST …/design/check``)."""

    head: str
    items: list[PlannedItemView]
    counts: dict[str, int] = Field(description="Items per action.")
    n_contradicted: int
    n_rejects: int = Field(description="Waiting proposals the act rejects (they say otherwise).")
    message: str


class DesignSetView(BaseModel):
    """What one act recorded (``POST …/design/set``)."""

    message: str
    head: str
    recorded: int = Field(description="Proposals accepted (yours, and waiting ones that agree).")
    rejected: int = Field(description="Waiting proposals rejected because you set otherwise.")
    unchanged: int
    outcomes: list[ProposalOutcome] = []
    stages: list[StageView]
    results_visible: bool
    job: JobView | None = None


class EditorOption(BaseModel):
    """One choice of a control, in a scientist's words."""

    value: str
    label: str
    hint: str


class EditorSample(BaseModel):
    """One sample as the editor shows it: names, wells and the design so far; no number."""

    sample: str
    text_id: str | None = None
    declared_type: str
    n_wells: int
    wells: list[str] = Field(description="`run_id/well` of every well of the sample.")
    targets: list[str]
    experiments: list[str]
    role: str = Field(description="Its type in the design so far (the file's when undecided).")
    quantity: float | None = Field(
        default=None, description="A standard's known quantity, as a person or a sheet set it."
    )
    series: str | None = None
    locked: str | None = Field(
        default=None, description="Why its type cannot change (a declared control)."
    )
    waiting: list[str] = Field(description="Kinds of the proposals about it that wait.")


class EditorMembership(BaseModel):
    """A sample's group and biological unit in the design so far.

    Kept apart from :class:`EditorSample` (which carries counts and a standard's quantity), so
    no object of this API ever holds a group next to a number, even a count.
    """

    sample: str
    group: str | None = None
    unit: str | None = None


class EditorTarget(BaseModel):
    """One target as the editor shows it."""

    target: str
    text_id: str | None = None
    declared_type: str
    n_wells: int
    runs: list[str]
    role: str | None = Field(default=None, description="What a person decided (null: not yet).")
    waiting: list[str]


class DesignNeed(BaseModel):
    """One thing the design still needs, and which control on the page gives it."""

    code: str
    words: str
    where: NeedWhere


class DesignEditorView(BaseModel):
    """``GET …/design/editor``: the editor's whole view at one head of the inbox."""

    head: str
    samples: list[EditorSample]
    membership: list[EditorMembership] = Field(
        description="Each sample's group and unit (one entry per sample, in the same order)."
    )
    targets: list[EditorTarget]
    groups: dict[str, int] = Field(description="Group -> study samples in it.")
    units: dict[str, int] = Field(description="Biological unit -> samples in it.")
    comparison: dict[str, str] | None = None
    comparison_plan: dict[str, Any] | None = Field(
        default=None,
        description="Several comparisons a person set: comparisons, pattern, control, correction "
        "and pair_by of the accepted comparison (None: one comparison).",
    )
    pair_by: str | None = Field(
        default=None, description="The pairing a person accepted (donor, animal...), if any."
    )
    n_paired: int = Field(default=0, description="Study samples with a pairing.")
    preset: str | None = Field(
        default=None, description="A built-in design a person accepted (the demo's)."
    )
    experiments: list[str]
    needs: list[DesignNeed]
    waiting: int
    confirmed: bool = Field(description="The design stage is confirmed (a change re-opens it).")
    sample_types: list[EditorOption]
    target_roles: list[EditorOption]
    has_sheet: bool = Field(description="A sample sheet is attached to this session.")
    sheet_name: str | None = None
    template_url: str = Field(description="The pre-filled sample-sheet template (CSV).")
    purpose: Literal["compare", "quantify"] = Field(
        default="compare",
        description="What the study is for: compare groups (the default) or quantify samples "
        "from a standard curve (no comparison, no reference gene).",
    )
    purposes: list[EditorOption] = Field(
        default=[], description="What a study can be for, in words (compare, quantify)."
    )
    n_standards: int = Field(default=0, description="Standard samples on the plate.")
    n_standards_with_quantity: int = Field(
        default=0, description="Standard samples with a quantity (the file's or a person's)."
    )


class SheetAttached(BaseModel):
    """``POST …/sheet``: the sheet is bound to this session; the rules propose again (a job)."""

    message: str
    sheet_name: str
    job: JobView


__all__ = [
    "DesignCheckRequest",
    "DesignEditItem",
    "DesignEditorView",
    "DesignNeed",
    "DesignPlanView",
    "DesignSetRequest",
    "DesignSetView",
    "EditorMembership",
    "EditorOption",
    "EditorSample",
    "EditorTarget",
    "PlannedItemView",
    "SheetAttached",
]
