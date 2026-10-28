"""The report's API models: the report itself (from :mod:`qpilot.report.model`) and its exports.

``GET /api/studies/{id}/report`` answers :class:`ReportView`; ``POST …/report/export`` starts a
``report.export`` job whose result is :class:`ReportExported`; ``GET …/report/exports`` lists the
exports written since (newest first). ``GET …/report/figure/info`` answers :class:`FigureInfo`
(one gene's figure: its caption, its groups and the links to its SVG, PNG and CSV, which
``GET …/report/figure`` serves).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from qpilot.report.model import (
    Citation,
    KeyNumber,
    Limitation,
    MethodsParagraph,
    MethodsView,
    MiqeItem,
    MiqePack,
    MiqeView,
    ReportAudit,
    ReportDecision,
    ReportFact,
    ReportGene,
    ReportHeader,
    ReportSegment,
    ReportText,
    ReportView,
    ReviewCheck,
    ReviewFinding,
    ReviewView,
)
from qpilot.web.contract_files import DownloadLink

ReportFormat = Literal["md", "html", "passport", "xlsx", "csv", "figures", "supplement"]
Basis = Literal["as_decided", "recommended"]
FigureFormat = Literal["svg", "png", "csv"]


class ReportExportBody(BaseModel):
    """Which file to write."""

    format: ReportFormat = Field(
        description=(
            "md: the report as Markdown; html: a printable page; passport: one self-contained "
            "offline HTML file with charts, bound to a fresh Analysis Record; xlsx: the study's "
            "numbers as an Excel workbook (results, per unit, per well, decisions, settings, "
            "Methods; Trace's places to look); csv: the same tables as CSV files in a zip; "
            "figures: a figure per gene (SVG, 300-dpi PNG, source CSV, caption) and a panel, "
            "zipped; supplement: what a journal asks for in one zip (the workbook, the tables, "
            "the MIQE checklist, the figures, the RDML with qPilot's results, the Analysis "
            "Record)."
        )
    )
    expected_head: str | None = Field(
        default=None, description="The chain head the page showed (warns when it moved since)."
    )
    basis: Basis | None = Field(
        default=None,
        description=(
            "figures: draw the analysis as decided on the Decision Cards (default, also when "
            "left out) or the "
            "recommended one. The tables always hold the analysis as decided, and the "
            "recommended one too when it differs."
        ),
    )
    genes: list[str] | None = Field(
        default=None,
        max_length=200,
        description="figures and supplement: the genes to draw (default: the headline genes).",
    )


class ReportRecordRef(BaseModel):
    """The Analysis Record a passport is bound to (written with it, in the same folder)."""

    record_id: str = Field(description="SHA-256 of the record's CHECKSUMS.sha256.")
    chain_head: str
    n_files: int
    input_included: bool
    download: DownloadLink
    verify: str = Field(description="The command that checks the record.")
    rerun: str = Field(description="The command that re-runs it to the same numbers.")


class ReportExported(BaseModel):
    """One written report file, ready to download."""

    study_id: str
    format: ReportFormat
    title: str = Field(description="What the file is, in words.")
    download: DownloadLink
    chain_head: str
    written_at: str
    n_facts: int = Field(description="How many facts the file cites.")
    record: ReportRecordRef | None = None
    head_moved: bool = False
    warnings: list[str] = []
    bases: list[Basis] = Field(
        default=[], description="The analyses the file holds: as decided, and recommended."
    )
    genes: list[str] = Field(default=[], description="The genes drawn (figures, supplement).")


class FigureGroup(BaseModel):
    """One group of a gene's figure: its biological units and the bar drawn for it."""

    name: str
    n: int = Field(description="Biological units with a value (the dots).")
    mean: float | None = Field(description="Mean log2 relative quantity of the units.")
    ci_low: float | None = Field(description="95 % confidence interval of the mean (low).")
    ci_high: float | None


class FigureFiles(BaseModel):
    """Where the figure's files are served (same-origin links)."""

    svg: str
    png: str
    csv: str


class FigureInfo(BaseModel):
    """One gene's figure: what it shows, its caption, and its files."""

    study_id: str
    gene: str
    comparison: str
    comparisons: list[str]
    basis: Basis
    bases: list[Basis] = Field(description="The analyses there is a figure for.")
    basis_label: str
    call: Literal["up", "down", "none"] | None = Field(
        description="The engine's call (None: the engine did not compare this gene)."
    )
    fold_change: float | None
    ci95_low: float | None
    ci95_high: float | None
    p: float | None
    n_a: int | None
    n_b: int | None
    groups: list[FigureGroup]
    caption: str
    note: str = ""
    files: FigureFiles
    chain_head: str


class ReportExports(BaseModel):
    """The report files written for a study since qPilot started, newest first."""

    study_id: str
    exports: list[ReportExported]


__all__ = [
    "Basis",
    "Citation",
    "DownloadLink",
    "FigureFiles",
    "FigureFormat",
    "FigureGroup",
    "FigureInfo",
    "KeyNumber",
    "Limitation",
    "MethodsParagraph",
    "MethodsView",
    "MiqeItem",
    "MiqePack",
    "MiqeView",
    "ReportAudit",
    "ReportDecision",
    "ReportExportBody",
    "ReportExported",
    "ReportExports",
    "ReportFact",
    "ReportFormat",
    "ReportGene",
    "ReportHeader",
    "ReportRecordRef",
    "ReportSegment",
    "ReportText",
    "ReportView",
    "ReviewCheck",
    "ReviewFinding",
    "ReviewView",
]
