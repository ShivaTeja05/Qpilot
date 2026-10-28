"""The contract of the Prism, Record and download routes (``routers/files.py``).

Engine and Studio models (:class:`~qpilot.schemas_studio.PrismBundle`,
:class:`~qpilot.schemas_studio.PrismDiffItem`, :class:`~qpilot.core.record.VerifyReport`) are
returned as they are; the models here add only what the page needs around them. Every string is
text: no model carries HTML.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from qpilot.core.record import VerifyReport
from qpilot.schemas_studio import PrismBundle, PrismDiffItem

# ---- downloads -----------------------------------------------------------------------------------


class DownloadLink(BaseModel):
    """A file qPilot wrote into its export folder (beside the store), offered for download."""

    id: str = Field(description="Opaque; registered by this server (listings re-register).")
    url: str = Field(description="`/api/downloads/<id>` (served as an attachment).")
    name: str = Field(description="The file name the browser saves it under.")
    bytes: int
    path: str = Field(description="Where the file is kept on this computer.")


# ---- Prism: the section's frame ------------------------------------------------------------------

ProjectStatus = Literal["accepted", "waiting", "none"]


class PrismProject(BaseModel):
    """The Prism project of the session's current analysis, and what can be done next."""

    status: ProjectStatus = Field(
        description="accepted: a person accepted a project for this analysis; waiting: a "
        "drafted project waits in the Prism inbox; none: nothing drafted yet."
    )
    proposal_id: str | None = None
    template_id: str | None = None
    genes: list[str] = []
    made_by: str | None = Field(default=None, description="rule, model or agent")
    still_current: bool = Field(
        default=False,
        description="Accepted for an earlier analysis whose exported tables hold exactly the "
        "same numbers (equal tables digest): it holds for this one, no new draft is needed.",
    )
    drafted_for: str | None = Field(
        default=None, description="The analysis it was accepted for, when still current."
    )
    checking: bool = Field(
        default=False,
        description="A project accepted for an earlier analysis may still hold: its tables are "
        "being compared with this analysis's (the page hears when it is done).",
    )


class PrismStatus(BaseModel):
    """``GET /api/sessions/{sid}/prism``: where Prism stands for this session."""

    session_id: str
    study_id: str
    choices_confirmed: bool
    project: PrismProject
    can_draft: bool
    can_send: bool
    next: str = Field(description="What to do next, in words.")
    bundles: int = Field(description="Bundles in qPilot's export folder for this session.")


# ---- Prism: what would be written ----------------------------------------------------------------


class PrismTemplate(BaseModel):
    """The test and graph the project is drafted for (a template is only for the scripts)."""

    id: str
    file: str
    available: bool = Field(
        description="A hand-made template is here (only the optional Prism scripts use one; "
        "the project file needs none)."
    )
    layout: str
    test: str
    graph: str


class PrismTableView(BaseModel):
    """One table of the Prism project (``.pzfx``)."""

    name: str
    gene: str = Field(description="Empty for the grouped table of all genes.")
    kind: Literal["column", "nested", "grouped"]
    title: str = Field(description="The table's title in Prism (record ref and chain head).")
    n_rows: int


class PreviewTable(BaseModel):
    """The first rows of one table Prism will import (cells as text, as in the CSV)."""

    gene: str
    columns: list[str]
    n_rows: int
    rows: list[list[str]]


class PrismChoice(BaseModel):
    """One analysis choice the bundle is exported at, and who decided it."""

    card_id: str
    dimension: str
    option: str
    recommended: str
    value: Any = None
    actor: str | None = None
    status: str
    title: str = Field(description="The card's question, e.g. which control genes to use.")
    option_label: str = Field(description="The exported option in words (never a raw id).")
    decided_by: str = Field(description="Who decided, in words.")


class UnitValue(BaseModel):
    """One biological unit's value in a Prism table (log2 relative quantity)."""

    unit: str
    value: float


class GroupPoints(BaseModel):
    """Every biological unit of one group, and the group mean with its 95 % CI (Student t)."""

    name: str
    n: int
    mean: float | None = Field(default=None, description="None for fewer than two units.")
    ci_lo: float | None = None
    ci_hi: float | None = None
    points: list[UnitValue]


class PrismFigure(BaseModel):
    """An approximation of the template's graph for one gene (Prism draws the real one)."""

    gene: str
    scale: str
    groups: list[GroupPoints]
    note: str


class PrismPreview(BaseModel):
    """``GET …/prism/preview``: what Send to Prism would write. Nothing is written."""

    session_id: str
    study_id: str
    writes_nothing: bool = True
    bundle: PrismBundle
    would_write: list[str]
    template: PrismTemplate
    genes: list[str]
    tables: list[PreviewTable]
    choices: list[PrismChoice]
    caption: str | None = None
    figures: dict[str, PrismFigure] = Field(
        default={},
        description="Per gene, from the full table (column layout only; empty otherwise).",
    )
    project: PrismProject
    choices_confirmed: bool
    not_affiliated: str
    project_file: str | None = Field(
        default=None, description="The Prism project Send writes (opens in Prism as it is)."
    )
    project_tables: list[PrismTableView] = []
    replicates_file: str | None = Field(
        default=None, description="The project of Nested tables, when units have replicates."
    )
    replicates_tables: list[PrismTableView] = []
    needs_template: bool = False


# ---- Prism: how the usual routes would change the conclusions ------------------------------------


class PrismRoute(BaseModel):
    """How many of this study's conclusions one usual Excel→Prism route would change."""

    route: str
    label: str = Field(description="The route in the page's words.")
    method: str = Field(description="The route's method, briefly (qpilot.qpcr.routes).")
    n_differ: int
    n_genes: int
    genes: list[str]
    fact: str = Field(description="The fact id of `n_differ`.")
    genes_fact: str | None = None


class PrismRoutes(BaseModel):
    """``GET …/prism/routes``: why the bridge matters, on this study's own plates."""

    session_id: str
    study_id: str
    n_genes: int | None
    rule: str = Field(description="The conclusion rule, in words.")
    engine: dict[str, str] = Field(
        description="The engine's conclusion (up / down / none) for every gene a route changes."
    )
    routes: list[PrismRoute]
    note: str


# ---- Prism: bundles, send, draft, round trip -----------------------------------------------------


class PrismBundleView(BaseModel):
    """One bundle sent to Prism from this session."""

    id: str | None = Field(
        description="Opaque id of a bundle Send to Prism wrote into qPilot's export folder (round "
        "trip, download); None for one written elsewhere or no longer there."
    )
    study_id: str
    bundle_sha256: str
    at: str
    folder: str
    exists: bool
    current: bool = Field(description="Its analysis is the session's current one.")
    sent_back_folder: str | None = Field(
        default=None, description="The folder a round trip read, or where send_back.pzc writes."
    )
    round_trip: bool = Field(description="A round trip can be started from this page.")
    download: DownloadLink | None = None
    project: str | None = Field(
        default=None,
        description="The project file in the bundle folder (where Prism saves it back), for a "
        "bundle with a project; None for a scripts-only bundle.",
    )


class PrismBundles(BaseModel):
    """``GET …/prism/bundles``: every bundle sent from this session, newest first."""

    session_id: str
    bundles: list[PrismBundleView]


Platform = Literal["windows", "macos"]


class OpenSteps(BaseModel):
    """How to open the project on one operating system, in plain words (no command line)."""

    platform: Platform
    label: str = Field(description="Windows or macOS.")
    steps: list[str]


class PrismSent(BaseModel):
    """The result of a Send to Prism job."""

    bundle: PrismBundleView
    n_files: int
    files: list[str] = Field(description="Every file of the bundle, relative to its folder.")
    notes: list[str]
    launched: bool
    done: bool | None = Field(
        default=None, description="Prism finished run.pzc (scripts-only bundles, when launched)."
    )
    launch_note: str | None = None
    project: str | None = Field(default=None, description="The project file (opens in Prism).")
    replicates_project: str | None = None
    this_platform: Platform = Field(description="The operating system of this computer.")
    open_steps: list[OpenSteps] = Field(
        default=[], description="How to open the project, this computer's system first."
    )
    analyse_steps: list[str] = Field(
        default=[], description="The clicks that add the t test and the graph in Prism."
    )
    round_trip_steps: list[str] = Field(
        default=[], description="How to bring changes made in Prism back to qPilot."
    )
    scripts: bool = Field(default=False, description="The optional Prism scripts were written.")
    command_line: str = Field(
        default="",
        description="Only for the optional scripts: what runs run.pzc. Empty for a project.",
    )
    send_back_command: str = ""
    download: DownloadLink


class PrismChecked(BaseModel):
    """The result of the background check whether an earlier project still holds."""

    still_current: bool


class PrismDrafted(BaseModel):
    """The result of a Draft the Prism project job."""

    status: str
    proposal_id: str | None = None
    reason: str | None = None
    message: str


class RoundTripRequest(BaseModel):
    """Which bundle came back, and where: the project Prism saved, or the sent-back folder."""

    bundle: str = Field(description="A bundle id from `…/prism/bundles`.")
    folder: str = Field(
        max_length=4096,
        description="The full path of the project Prism saved (a .pzfx file), of the folder "
        "holding it (the bundle folder, by default), or of send_back.pzc's sent_back folder.",
    )


class RoundTripRefused(BaseModel):
    """A change the round trip did not turn into a question, and why."""

    reason: str | None = None
    subject: str | None = None


class PrismRoundTrip(BaseModel):
    """The result of a round trip: what changed in Prism, as proposals with consequences."""

    bundle_id: str
    study_id: str
    items: list[PrismDiffItem]
    proposed: list[str] = Field(description="Ids of the proposals added to the Round trip inbox.")
    refused: list[RoundTripRefused]
    notes: list[str]
    combined: dict[str, Any] | None = Field(
        default=None, description="What all the proposed exclusions do together."
    )
    message: str
    source: Literal["project", "sent_back"] = Field(
        default="sent_back",
        description="project: read from the project Prism saved; sent_back: from send_back.pzc.",
    )


# ---- the Analysis Record -------------------------------------------------------------------------


class RecordRequest(BaseModel):
    """Export options."""

    include_input: bool = Field(
        default=True, description="False leaves the raw input out (verifiable, not re-runnable)."
    )
    expected_head: str | None = Field(
        default=None, description="The chain head the page showed (a warning if it moved)."
    )


class RecordCommands(BaseModel):
    """Commands that check a record on any computer with qPilot."""

    verify: str
    rerun: str


class RecordExported(BaseModel):
    """The result of an Export the Analysis Record job."""

    study_id: str
    record_id: str
    chain_head: str
    n_files: int
    input_included: bool
    written_at: str | None = None
    download: DownloadLink
    open_flips: list[str] = Field(
        description="Cards that can change a conclusion and are still open (the record says so)."
    )
    head_moved: bool = Field(description="Something was decided after the page's view.")
    warnings: list[str]
    commands: RecordCommands


class RecordList(BaseModel):
    """``GET /api/studies/{id}/records``: the records in qPilot's export folder, newest first."""

    study_id: str
    records: list[RecordExported]


class RecordFacts(BaseModel):
    """What a record says about itself (``record.json``), as read from the uploaded zip."""

    study_id: str | None = None
    input_sha256: str | None = None
    chain_head: str | None = None
    written_at: str | None = None
    input_included: bool | None = None
    shared: bool = False
    record_id: str | None = Field(default=None, description="sha256 of CHECKSUMS.sha256.")


class AuditBinding(BaseModel):
    """Whether a robustness audit verifies and belongs to this record."""

    source: Literal["zip", "store"] = Field(
        description="zip: the audit came in the uploaded zip; store: this qPilot's audit of "
        "the record's study."
    )
    ok: bool
    problems: list[str]
    study_id: str | None = None


class RecordVerified(BaseModel):
    """``POST /api/records/verify``: checksums, both chains, and the audit binding."""

    ok: bool = Field(description="The record verifies (and its audit, when one is bound).")
    file_name: str
    summary: list[str] = Field(description="One line per problem, or one OK line.")
    report: VerifyReport
    record: RecordFacts
    audit: AuditBinding | None = None
    audit_note: str = Field(description="Which audit was checked, or why none was.")
    known_study: bool = Field(description="The record's study is in this qPilot's store.")
    note: str
