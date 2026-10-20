"""The report as data: what the page, the Markdown, the printable HTML and the passport draw from.

Text that may hold a number is a :class:`ReportText`: segments of prose, cited facts (``fact``
names one of :attr:`ReportView.facts`), quoted data from the study (``quote``: a gene, sample or
option name, a person's reason: shown as text, never as markup) and citation markers (``cite``).
Numbers outside text (a gene's fold change in the gene table) are copied from the engine's result
as they are; the page formats them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Conclusion = Literal["up", "down", "none"]
MiqeStatus = Literal["met", "not_met", "not_applicable", "cannot_tell"]
Severity = Literal["major", "minor", "note"]
GoTo = Literal["results", "gene", "audit", "record", "design", "curves", "report"]


class ReportFact(BaseModel):
    """One number (or name) a sentence cites, and where it was read."""

    id: str = Field(description="f_… for the engine's own facts; f_rpt_… for one the report read.")
    text: str = Field(description="The value as written (format and unit applied).")
    value: float | int | str
    unit: str = ""
    path: str = Field(
        description=(
            "Where it comes from: the engine's path, or `<source>:<JSON pointer>[@min|max|len|"
            "count=<value>]` for a value the report read (results.json, cards.json, "
            "decisions.jsonl, study_design.json, versions, input.rdml, grid.csv, "
            "audit:<file>, report)."
        )
    )
    derived: bool = Field(description="Read by the report from the store, not one of the engine's.")


class ReportSegment(BaseModel):
    """A run of prose, one cited fact, a quoted string from the study, or a citation marker."""

    text: str
    fact: str | None = None
    quote: bool = Field(default=False, description="Data from the study: never markup.")
    cite: int | None = Field(default=None, description="The number of a citation (methods only).")


class ReportText(BaseModel):
    """A sentence or paragraph whose numbers are facts."""

    plain: str = Field(description="As plain text, without citation markers.")
    segments: list[ReportSegment]
    facts: list[str] = Field(description="Ids of the facts it cites, in order of first use.")


class KeyNumber(BaseModel):
    """One of the study's key numbers (label + the fact that holds it)."""

    label: str
    fact: str


class Citation(BaseModel):
    """A reference the Methods cite (no links: DOIs as text)."""

    n: int
    id: str
    text: str


class MethodsParagraph(BaseModel):
    """One paragraph of the Methods section."""

    id: str
    title: str
    text: ReportText


class MethodsView(BaseModel):
    """The Methods section, ready to paste into a paper."""

    paragraphs: list[MethodsParagraph]
    citations: list[Citation]
    plain: str = Field(description="Every paragraph as plain text, without citation markers.")
    with_citations: str = Field(description="With [n] markers and the numbered reference list.")


class MiqeItem(BaseModel):
    """One MIQE 2.0 item: what the data say about it, with the evidence."""

    id: str
    section: str
    label: str
    status: MiqeStatus
    attest: bool = Field(description="Only a person can answer this item (never answered here).")
    evidence: ReportText | None = None
    sources: list[str] = []


class MiqePack(BaseModel):
    """The item list the checklist uses."""

    name: str
    version: str
    sha256: str
    citation: str


class MiqeView(BaseModel):
    """The MIQE 2.0 checklist: counts by status, never a score."""

    pack: MiqePack
    items: list[MiqeItem]
    counts: dict[MiqeStatus, int]
    n_items: int
    headline: ReportText


class ReviewFinding(BaseModel):
    """Something a careful reviewer would flag, from the study's own numbers."""

    id: str
    severity: Severity
    title: str
    text: ReportText
    genes: list[str] = []
    go_to: GoTo | None = Field(default=None, description="The section that shows it.")
    rule: str | None = Field(default=None, description="The reviewer rule (R1–R8) it answers.")


class ReviewCheck(BaseModel):
    """A question a reviewer asks that the study answers well."""

    id: str
    title: str
    text: ReportText


class ReviewView(BaseModel):
    """The reviewer's report: findings by severity, then what checks out."""

    lead: ReportText
    findings: list[ReviewFinding]
    passed: list[ReviewCheck]
    counts: dict[Severity, int]


class Limitation(BaseModel):
    """One limitation, in plain words."""

    id: str
    text: ReportText


class ReportGene(BaseModel):
    """One compared gene as the passport's gene table shows it (engine values, unformatted)."""

    gene: str
    headline: bool
    conclusion: Conclusion
    fc: float
    ci_lo: float
    ci_hi: float
    p: float | None
    n_hi: int
    n_lo: int
    holds: float | None = Field(description="Share of qPilot's choice grid with the same call.")
    n_cells: int
    level: str | None
    flips_by: list[str] = Field(description="Choices that alone change the call.")
    verdict: str | None = None
    verdict_label: str | None = None


class ReportDecision(BaseModel):
    """One entry of the hash-chained decision log, or a card still open."""

    seq: int | None
    card_id: str
    card_title: str
    option: str | None
    option_label: str | None
    actor: str | None
    status: str
    at: str | None
    reason: str | None
    hash: str | None
    can_flip: bool = Field(description="Some option of this card changes a conclusion.")


class ReportAudit(BaseModel):
    """The robustness audit, when one was run."""

    status: Literal["none", "ready"]
    current: bool = False
    chain_head: str | None = None
    analyses: int | None = None
    reasonable: int | None = Field(default=None, description="The audit's reasonable set.")
    verdict_counts: dict[str, int] = {}
    verdict_labels: dict[str, str] = {}
    reproduces: bool | None = None


class ReportHeader(BaseModel):
    """What the report is about and what binds it to the study."""

    study_id: str
    session: str | None
    title: str
    source_name: str | None = Field(description="The input file's name (from the study).")
    demo: bool
    input_sha256: str
    chain_head: str
    n_decisions: int
    generated_at: str
    versions: dict[str, str]
    research_use: str = "Research use only; not for clinical use."


class ReportView(BaseModel):
    """The whole report of one study."""

    header: ReportHeader
    summary: ReportText
    key_numbers: list[KeyNumber]
    methods: MethodsView
    miqe: MiqeView
    review: ReviewView
    limitations: list[Limitation]
    genes: list[ReportGene]
    decisions: list[ReportDecision]
    audit: ReportAudit
    rule: str = Field(description="The conclusion rule in words.")
    facts: dict[str, ReportFact] = Field(description="Every fact the report cites, by id.")
