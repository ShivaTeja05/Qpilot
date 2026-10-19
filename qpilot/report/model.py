"""The report as data (schema ``qpilot.report/1``): what every renderer draws from.

Numbers are never stored here as numbers to print: a field that shows a number holds a fact id
(look it up in :attr:`Report.facts`) or a :class:`~qpilot.report.text.Text` whose numbers are
fact tokens. Strings that came from the record (gene names, reasons) are kept as data and
escaped by each renderer.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from qpilot.report.text import Text
from qpilot.schemas import Fact

SCHEMA = "qpilot.report/1"
Status = Literal["ok", "not_available"]
Verdict = Literal["pass", "warn", "fail", "not_applicable"]
MiqeStatus = Literal["filled", "needs_scientist", "not_applicable"]


class Section(BaseModel):
    """A part of the report that may be missing from a record."""

    status: Status = "ok"
    reason: str = ""  # plain words, no digits: why the section is not available


class Reason(BaseModel):
    """One component of a gene's confidence grade, in fact-bound words."""

    check: str
    passed: bool
    text: Text


class GeneRow(BaseModel):
    """One gene: n, fold change, how many analyses agree, what it rests on, confidence."""

    gene: str
    headline: bool = False
    conclusion: str
    n_a: str | None = None
    n_b: str | None = None
    fc: str | None = None
    ci_lo: str | None = None
    ci_hi: str | None = None
    p: str | None = None
    holds: str | None = None
    level: str | None = None
    rests_on: list[str] = []
    rests_on_text: Text | None = None
    reasons: list[Reason] = []
    withheld: str | None = None  # fact id of the reason a gene's comparison is withheld


class ReviewCheck(BaseModel):
    """One of the Reviewer's Report checks."""

    id: str
    title: str
    verdict: Verdict
    text: Text
    source: str = ""


class Review(Section):
    """The one-page Reviewer's Report."""

    pack: dict[str, str] = {}
    lead: Text | None = None
    checks: list[ReviewCheck] = []
    cannot_check: list[str] = []


class MiqeRow(BaseModel):
    """One MIQE 2.0 item and what the record says about it."""

    id: str
    section: str
    label: str
    status: MiqeStatus
    answer: Literal["Yes", "No", ""] = ""
    text: Text | None = None
    sources: list[str] = []


class Miqe(Section):
    """The MIQE 2.0 table and its completeness count (never a score)."""

    pack: dict[str, str] = {}
    headline: Text | None = None
    rows: list[MiqeRow] = []
    n_filled: int = 0
    n_items: int = 0


class Methods(Section):
    """The methods paragraph and its references."""

    paragraphs: list[Text] = []
    references: list[str] = []


class Decision(BaseModel):
    """One entry of the hash-chained decision log (strings from the record, kept as data)."""

    seq: str
    card: str
    option: str
    actor: str
    status: str
    at: str
    reason: str


class Decisions(Section):
    """Who decided what, when and why; plus a count of Studio proposals by outcome."""

    entries: list[Decision] = []
    by_actor: Text | None = None
    proposals: Text | None = None
    exclusions: list[str] = []


class Figure(BaseModel):
    """One figure: inline SVG, a fact-bound caption, the CSV of what is plotted."""

    id: str
    title: str
    svg: str
    caption: Text
    source_csv: str


class Figures(Section):
    """The figures; SuperPlots need the record's input file (see :mod:`qpilot.report.units`)."""

    items: list[Figure] = []
    notes: list[str] = []


class Integrity(BaseModel):
    """What ``qpilot verify`` found, and the identifiers that bind the report to the record."""

    ok: bool
    summary: str
    problems: list[str] = []
    record_id: str | None = None
    chain_head: str | None = None
    input_sha256: str | None = None
    input_included: bool = False
    checksums: dict[str, str] = {}
    unreadable: list[str] = []


class Optional_(Section):
    """A section another part of qPilot fills (Run Gate, Trust Card, labels, Trace)."""

    title: str = ""
    lines: list[Text] = []
    data: dict[str, Any] = {}


class Report(BaseModel):
    """Everything the renderers draw; ``model_dump(mode="json")`` is the ``--json`` output."""

    report_schema: str = SCHEMA
    study_id: str
    record: dict[str, Any] = {}
    integrity: Integrity
    summary: Text
    key_numbers: list[tuple[str, str]] = []  # (label, fact id)
    genes: list[GeneRow] = []
    reviewer: Review
    miqe: Miqe
    methods: Methods
    decisions: Decisions
    figures: Figures
    optional: dict[str, Optional_] = {}
    facts: dict[str, Fact] = {}
