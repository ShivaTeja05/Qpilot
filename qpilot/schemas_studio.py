"""Studio contracts: proposals, study designs, amplification-call rules and the Prism bundle.

FROZEN for the Studio build (``qPilot-STUDIO-PRISM-PLAN.md`` step 0.3). ``schemas.py`` stays
frozen and untouched; everything qPilot Studio adds is defined here, so the engine, the core,
the AI layer, the Prism bridge and the dashboard build against one file. Change it only through
the contract-change protocol (one PR, both developers approve).

The one rule these types serve, enforced in ``core/proposals.py``:

    AI proposes. The engine checks. The scientist decides.

A :class:`Proposal` has no effect on any number, record entry or Prism file until a person
accepts it. The engine reads only accepted proposals (:func:`qpilot.qpcr.designs.
design_from_proposals`), so pending proposals never change a result.

Payload shapes by ``Proposal.kind`` (``subject`` in brackets):

==========================  =================  ==================================================
kind                        subject            payload
==========================  =================  ==================================================
``design.preset``           ``design``         ``{"preset": "vermeulen_expression_defined"}``
``design.well_role``        sample id          ``{"role": WellRole}``
``design.group``            sample id          ``{"group": str}``
``design.bio_unit``         sample id          ``{"biological_unit": str}``
``design.target_role``      target             ``{"role": "ref" | "toi" | "ignore"}``
``design.gene_symbol``      target             ``{"symbol": str}`` (HGNC)
``design.comparison``       ``comparison``     ``{"group_a": str, "group_b": str}``
``design.dilution_series``  series name        ``{"experiment_id": str, "samples": {id: qty}}``
``curve.call_rule``         ``amp_call``       ``{"rule": AmpCallRule.id}``
``curve.well_call``         ``run_id/well``    ``{"amplified": bool}``
``curve.exclude_well``      ``run_id/well``    ``{"excluded": bool}`` (``false`` puts it back)
``curve.import_trust``      ``import``         ``{"option": str}``: the Import Trust card's option
                                               (``reexport_raw``, ``analyse_as_is``, ``cq_only``)
``choice.axis``             axis name          ``{"options": [option id, ...]}``, primary first
                            (``efficiency``)   (one option: the axis is not tested)
``prism.project``           ``prism``          ``{"template_id": str, "genes": [...], ...}``
``prism.exclusion_reason``  ``gene/sample``    ``{"gene", "sample", "action": "exclude"|"restore"}``
                            (``/rep n``)       + ``"well_rep"`` (0: the unit's value, n: its
                                               replicate n) and, for a replicate, ``"well"``
                                               (``run_id/well``, the exact well excluded)
``prism.value_edit``        ``gene/sample``    ``{"gene", "sample", "action": "restore"|"keep"}``
                            (``/rep n``)       + ``"well_rep"`` and ``"well"`` as above
``stage.confirm``           stage name         ``{"stage", "design_hash", "covers": [ids]}``
==========================  =================  ==================================================
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, model_validator

from qpilot.schemas import Actor, Level

# ---------------------------------------------------------------------------------------------
# Untrusted text (core/firewall.py)
# ---------------------------------------------------------------------------------------------

TEXT_ID = re.compile(r"^t_[0-9a-f]{12}\Z")


def text_id_for(origin: str, value: str) -> str:
    """The one formula for a ``text_id``: ``t_`` + the first 12 hex of sha256(origin NUL value).

    Every module that quarantines text (the firewall, ``qpcr_inspect``, the sheet reader, the
    Prism round trip) uses this, so the same text from the same place always has the same id.
    """
    digest = hashlib.sha256(f"{origin}\x00{value}".encode()).hexdigest()
    return f"t_{digest[:12]}"


class QuarantineEntry(BaseModel):
    """One piece of free text from a file, stored once and cited by ``text_id`` everywhere else.

    ``value`` is the original text. Prompts show it only inside a fenced, labelled quote block
    (``firewall.as_quoted``); the engine never computes with it.
    """

    text_id: str
    origin: str  # e.g. "rdml:sample.id", "sheet:samples.xlsx!Sheet1!B2", "prism:ODC1.csv!A3"
    value: str
    flags: list[str] = []  # "instruction_like", "date_like", "email_like", "long", "control_chars"


# ---------------------------------------------------------------------------------------------
# Proposals (core/proposals.py)
# ---------------------------------------------------------------------------------------------

ProposalKind = Literal[
    "design.preset",
    "design.well_role",
    "design.group",
    "design.bio_unit",
    "design.target_role",
    "design.gene_symbol",
    "design.comparison",
    "design.dilution_series",
    "curve.call_rule",
    "curve.well_call",
    "curve.exclude_well",
    "curve.import_trust",
    "choice.axis",
    "prism.project",
    "prism.exclusion_reason",
    "prism.value_edit",
    "stage.confirm",
]
PROPOSAL_KINDS: tuple[str, ...] = ProposalKind.__args__  # type: ignore[attr-defined]
CheckStatus = Literal["consistent", "contradicted", "cannot_check"]
ProposalStatus = Literal["proposed", "accepted", "edited", "rejected", "superseded"]
EvidenceKind = Literal[
    "text", "cell", "well", "sample", "target", "fact", "curve", "rule", "pattern", "file"
]


class Evidence(BaseModel):
    """One source behind a proposal; every item is clickable in Studio.

    ``ref`` is a ``text_id``, a cell (``samples.xlsx!Sheet1!B2``), a well (``run_id/well``), a
    sample or target id, a fact id, a rule id or a named pattern. ``note`` is qPilot's own short
    wording; text from a file is never copied into it, only cited by ``text_id``.
    """

    kind: EvidenceKind
    ref: str
    note: str = ""


class ProposalCheck(BaseModel):
    """The engine's refute-only check of a proposal.

    Agreement never confirms a proposal: the best a check can say is ``consistent``.
    ``details`` holds the check's own numbers (an R², a count) for display as facts.
    """

    status: CheckStatus
    rule_ids: list[str] = []
    details: dict[str, Any] = {}
    note: str = ""


class MadeBy(BaseModel):
    """Who produced a proposal: a language model, an MCP agent, a deterministic rule or a person.

    ``person``: a person made the proposal on the Design page and accepted it in the same act
    (a design item the rules and the model did not propose). Only ``actor="human"`` may propose
    one (``core/proposals.py``); the engine still checks it like any other proposal.
    """

    kind: Literal["model", "agent", "rule", "person"]
    provider: str | None = None
    model: str | None = None
    prompt_sha256: str | None = None
    agent: str | None = None


class Proposal(BaseModel):
    """Something the AI (or an agent, or a fallback rule) thinks; no effect until accepted.

    ``consequence`` is ``None`` during the blind stages (design, curves); for design ambiguities
    it may only say ``{"matters": true}`` with no gene, direction or number.
    ``edits`` (when a person edited before accepting) are merged over ``payload`` by
    :meth:`effective_payload`; that merged payload is what the engine reads.
    """

    id: str = ""
    study_id: str
    kind: ProposalKind
    subject: str
    payload: dict[str, Any]
    evidence: list[Evidence] = []
    alternatives: list[dict[str, Any]] = []
    check: ProposalCheck = ProposalCheck(status="cannot_check")
    consequence: dict[str, Any] | None = None
    level: Level = "Low"
    reasons: list[str] = []
    made_by: MadeBy
    status: ProposalStatus = "proposed"
    decided_by: Literal["human"] | None = None
    decided_at: str | None = None
    reason: str | None = None
    edits: dict[str, Any] | None = None
    superseded_by: str | None = None
    created_at: str = ""

    def effective_payload(self) -> dict[str, Any]:
        """The payload the engine uses once accepted (``payload`` with any human edits)."""
        return {**self.payload, **(self.edits or {})}

    @property
    def stage(self) -> Literal["design", "curve", "choice", "prism", "stage"]:
        """The Studio stage the proposal belongs to (its kind's prefix).

        ``choice`` proposals belong to the choices stage (after the blind stages): which further
        analysis choices the robustness grid tests, such as the efficiency models.

        ``stage.confirm`` proposals are the confirm click of a whole stage: the system proposes
        one when the stage's items are settled, naming the design hash it confirms, and a
        person accepts it. The blind stages stay closed until those are accepted.
        """
        return self.kind.split(".", 1)[0]  # type: ignore[return-value]


ProposalAction = Literal["propose", "accept", "edit", "reject", "supersede"]


class ProposalEntry(BaseModel):
    """One line of ``proposals.jsonl``; hash-chained like ``decisions.jsonl``.

    The chain's root is the study's input sha256 (the same root as the decision chain).
    ``hash`` is sha256 of the canonical JSON of the entry without ``hash`` and **without
    fields that are None**, so optional fields added later never change old hashes.
    The full proposal is stored on its ``propose`` line only.
    """

    seq: int
    prev_hash: str
    action: ProposalAction
    proposal_id: str
    actor: Actor
    at: str
    reason: str = ""
    edits: dict[str, Any] | None = None
    superseded_by: str | None = None
    proposal: Proposal | None = None
    hash: str = ""


class ProposalOutcome(BaseModel):
    """What happened when someone tried to act on a proposal.

    ``refused`` means the action is not allowed for this actor (only a person accepts, edits or
    rejects) or the proposal is already settled; ``stale`` means ``expected_head`` was out of
    date. Neither writes to the chain.
    """

    status: Literal["proposed", "accepted", "edited", "rejected", "superseded", "stale", "refused"]
    head: str
    proposal: Proposal | None = None
    reason: str | None = None


# ---------------------------------------------------------------------------------------------
# Study design (qpcr/designs.py)
# ---------------------------------------------------------------------------------------------

WellRole = Literal["unkn", "std", "ntc", "nrt", "nac", "pos", "opt", "ntp"]  # RDML sample types
CONTROL_ROLES: frozenset[str] = frozenset({"ntc", "nrt", "nac"})  # never demoted (hard ban)
# ---- added by the Design page's person-made proposals (agent design; see docs/studio.md) ----
#: ``ignore``: a target a person leaves out of the study (a spike-in, an empty channel, an
#: assay not part of this experiment); :func:`qpilot.qpcr.designs.design_curves` drops its
#: wells before anything is computed. Absent unless a person chose it, so no hash changes.
TargetRole = Literal["toi", "ref", "ignore"]
# ---- end of the Design page's additions ------------------------------------------------------


class SampleDesign(BaseModel):
    """What one sample is: its role, its group and the biological unit it belongs to.

    Wells of the same sample and target are technical replicates. Several samples may share
    one ``biological_unit`` (for example three cDNA preparations of one animal); the engine
    averages log2 quantities per unit and gene and never counts technical replicates as n.

    ``rt_replicate`` labels a reverse-transcription replicate: samples of one biological unit
    with different labels were reverse-transcribed separately from the same RNA. Only the
    G-RT rule (:mod:`qpilot.qpcr.gate_rt`) and the Evidence Ledger read it; the analysis
    averages the samples of a unit as before. ``None`` (the default) is left out of
    :meth:`StudyDesign.canonical`, so existing design hashes do not change.
    """

    sample: str
    role: WellRole = "unkn"
    group: str | None = None
    biological_unit: str | None = None
    quantity: float | None = None  # standards: copies or relative dilution
    rt_replicate: str | None = None  # RT replicate label within the biological unit

    def unit(self) -> str:
        """The biological unit (the sample itself when none is set)."""
        return self.biological_unit or self.sample


class TargetDesign(BaseModel):
    """One assay: its name in the file, its confirmed gene symbol and its role."""

    target: str
    symbol: str | None = None
    role: TargetRole = "toi"


class Comparison(BaseModel):
    """The contrast: ``log2fc = mean(group_a) - mean(group_b)`` on the log2 scale."""

    group_a: str
    group_b: str
    label: str = ""


class MarkerSplit(BaseModel):
    """Expression-defined groups (the demo): top ``cut`` fraction by ``marker`` vs the rest."""

    marker: str
    cut: float = 0.15
    cuts: tuple[float, ...] = (0.10, 0.15, 0.20)
    group_var: str = "MYCN_high"


class ImportTrust(BaseModel):
    """How far the curves of an instrument export can be trusted, and what the analysis uses.

    ``verdict`` is the import's raw-ness verdict (``qpilot/io/rawness.py``) when it calls for
    the Import Trust card (``qpilot/io/trust.py``): the curves were baseline-subtracted before
    export, or qPilot could not tell. ``analysis`` is what a person chose on the card:
    ``as_is`` (LinRegPCR on the curves as imported; also the analysis before any choice) or
    ``cq_only`` (the curves are not used: each well's Cq is the instrument's, its quantity
    ``2^-Cq``). Either way the grade is capped (``qpilot/io/trust.py``).
    """

    verdict: Literal["baseline_subtracted", "unknown"]
    analysis: Literal["as_is", "cq_only"] = "as_is"


class StudyDesign(BaseModel):
    """A confirmed study design; the engine runs from this and from nothing else.

    ``mode="marker_split"`` reproduces the demo (groups defined from the data, with a ``cut``
    dimension in the grid). ``mode="groups"`` takes groups from the samples' ``group`` field
    (a sample sheet or accepted proposals) and has no ``cut`` dimension.

    ``well_roles``, ``well_calls`` and ``excluded_wells`` use ``"<run_id>/<well>"`` keys.
    ``well_calls`` is a person's resolution of a curve-call disagreement (``False``: the well
    counts as undetermined under every rule; ``True``: it counts as amplified wherever it has a
    quantity). ``excluded_wells`` are removed from the analysis altogether (a well-exclusion
    decision). ``amp_calls`` are the options of the amplification-call axis, primary first; one
    option means no axis. ``axes`` are the opt-in axes of the decision space a person asked to
    test, each with its options, primary first (``{"efficiency": ("linregpcr", "per_well")}``,
    see ``qpilot/qpcr/axes``). ``import_trust`` is set for a study opened from an instrument
    export whose curves were processed before export (:class:`ImportTrust`). ``None`` (the
    default for both) is left out of :meth:`canonical`, so the design hash and every existing
    study id stay what they were.
    """

    design_id: str = "custom"
    experiment_id: str | None = None
    mode: Literal["marker_split", "groups"]
    marker_split: MarkerSplit | None = None
    comparison: Comparison | None = None
    samples: dict[str, SampleDesign] = {}
    targets: dict[str, TargetDesign] = {}
    reference_candidates: tuple[str, ...] = ()
    headline: tuple[str, ...] = ()
    well_roles: dict[str, WellRole] = {}
    well_calls: dict[str, bool] = {}
    excluded_wells: tuple[str, ...] = ()
    amp_calls: tuple[str, ...] = ("linregpcr",)
    import_trust: ImportTrust | None = None
    axes: dict[str, tuple[str, ...]] | None = None
    note: str = ""

    @model_validator(mode="after")
    def _consistent(self) -> StudyDesign:
        if self.mode == "marker_split" and self.marker_split is None:
            raise ValueError("mode 'marker_split' needs marker_split")
        if self.mode == "groups":
            if self.comparison is None:
                raise ValueError("mode 'groups' needs a comparison")
            groups = {s.group for s in self.samples.values() if s.group}
            missing = {self.comparison.group_a, self.comparison.group_b} - groups
            if missing:
                raise ValueError(f"comparison groups without samples: {sorted(missing)}")
        if not self.amp_calls:
            raise ValueError("amp_calls needs at least one option")
        if self.axes is not None:  # one spelling per analysis: no axis is None, not {}
            if not self.axes:
                raise ValueError("axes lists no axis; leave it out instead")
            single = sorted(name for name, options in self.axes.items() if len(options) < 2)
            if single:
                raise ValueError(f"axes {single} offer one option; an axis not tested is left out")
        return self

    def canonical(self) -> str:
        """The one JSON form that is hashed (sorted keys, no spaces, None fields dropped)."""
        data = self.model_dump(mode="json", exclude_none=True)
        return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def design_hash(self) -> str:
        """sha256 of :meth:`canonical`."""
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------------------------
# Amplification calls (qpcr/amp_call.py) and the Curve Judge
# ---------------------------------------------------------------------------------------------


class AmpCallRule(BaseModel):
    """One rule for which wells count as amplified (an option of the ``amp_call`` axis)."""

    id: str  # "linregpcr", "cq_le_40", "cq_le_38", "cq_le_35", "learned"
    label: str
    kind: Literal["linregpcr", "cq_max", "learned"]
    cq_max: float | None = None
    recommended: bool = False
    note: str = ""
    method_card: str = ""


class WellCall(BaseModel):
    """One well's amplification call under every rule (``qpcr_curve_calls``)."""

    run_id: str
    well: str
    sample: str
    target: str
    sample_type: str
    cq: float | None = None
    calls: dict[str, bool]
    learned_p: float | None = None


# ---------------------------------------------------------------------------------------------
# What qPilot sees in a file before any design exists (qpcr/inspect.py, qpcr_inspect)
# ---------------------------------------------------------------------------------------------


class InspectSample(BaseModel):
    """A sample as declared in the file; ``text_id`` cites its quarantined original name."""

    sample: str
    text_id: str
    declared_type: str
    n_wells: int
    experiments: list[str] = []
    targets: list[str] = []


class InspectTarget(BaseModel):
    """An assay as declared in the file, with a per-well summary from LinRegPCR."""

    target: str
    text_id: str
    declared_type: str
    n_wells: int
    n_with_cq: int
    eff_median: float | None = None


class InspectRun(BaseModel):
    """One plate."""

    experiment_id: str
    run_id: str
    n_wells: int
    targets: list[str] = []


class SheetCell(BaseModel):
    """One non-empty cell of a sample sheet (merged cells already expanded)."""

    cell: str  # "Sheet1!B2"
    text_id: str
    row: int
    column: int


class InspectSummary(BaseModel):
    """Deterministic summary of an input file (and optional sample sheet) for the interpreter."""

    input_sha256: str
    n_samples: int
    declared_types: dict[str, int]
    experiments: dict[str, int]  # experiment id -> number of runs
    runs: list[InspectRun]
    samples: list[InspectSample]
    targets: list[InspectTarget]
    sheet: list[SheetCell] = []
    sheet_sha256: str | None = None
    notes: list[str] = []


class DesignField(BaseModel):
    """One field of the interpreter's reply; becomes one :class:`Proposal`."""

    kind: ProposalKind
    subject: str
    value: dict[str, Any]
    cites: list[str]  # text_ids or sheet cells that exist in the InspectSummary
    alternatives: list[dict[str, Any]] = []
    level: Level = "Low"
    reasons: list[str] = []


class DesignProposal(BaseModel):
    """The interpreter's whole reply (schema-validated before anything is stored)."""

    fields: list[DesignField]


# ---------------------------------------------------------------------------------------------
# The Prism bridge (prism/*)
# ---------------------------------------------------------------------------------------------

PrismLayout = Literal["column", "nested"]


class PrismTable(BaseModel):
    """One data table Prism will import: one gene, log2 relative quantities.

    ``column``: one column per group, one row per biological unit. ``nested``: one subcolumn
    per biological unit with its technical replicates stacked inside (GraphPad's layout).
    """

    name: str  # file stem, e.g. "ODC1"
    gene: str
    layout: PrismLayout
    title: str  # carries the record id and the short chain head
    columns: list[str]
    n_rows: int
    csv: str  # relative path inside the bundle directory
    csv_sha256: str


class PrismBundle(BaseModel):
    """Everything qPilot hands to Prism, and what a later round trip is compared against.

    Mode S (``mode="script"``, the default): CSV tables plus ``run.pzc`` / ``send_back.pzc``;
    Prism does all reading and writing of Prism files. Mode X (``mode="xml"``) is off by default.
    """

    study_id: str
    record_ref: str  # short id shown in file names and titles
    chain_head: str
    design_hash: str
    template_id: str
    scale: Literal["log2_rq"] = "log2_rq"
    test: str
    tables: list[PrismTable]
    info: dict[str, str] = {}
    files: dict[str, str] = {}  # relative path -> sha256, every file written
    mode: Literal["script", "xml"] = "script"
    bundle_sha256: str = ""


class PrismDiffItem(BaseModel):
    """One difference between the exported bundle and what came back from Prism."""

    kind: Literal[
        "excluded",
        "changed",
        "missing",
        "added_row",
        "removed_row",
        "added_column",
        "removed_column",
        "unreadable",
    ]
    table: str
    gene: str
    row: str | None = None
    column: str | None = None
    exported: float | None = None
    returned: float | None = None
    note: str = ""


__all__ = [
    "CONTROL_ROLES",
    "PROPOSAL_KINDS",
    "TEXT_ID",
    "AmpCallRule",
    "CheckStatus",
    "Comparison",
    "DesignField",
    "DesignProposal",
    "Evidence",
    "InspectRun",
    "InspectSample",
    "InspectSummary",
    "InspectTarget",
    "MadeBy",
    "MarkerSplit",
    "PrismBundle",
    "PrismDiffItem",
    "PrismLayout",
    "PrismTable",
    "Proposal",
    "ProposalAction",
    "ProposalCheck",
    "ProposalEntry",
    "ProposalKind",
    "ProposalOutcome",
    "ProposalStatus",
    "QuarantineEntry",
    "SampleDesign",
    "SheetCell",
    "StudyDesign",
    "TargetDesign",
    "WellCall",
    "WellRole",
    "text_id_for",
]

# Actor is re-exported for callers that only import this module.
_ = Actor
