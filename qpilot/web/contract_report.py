"""The report's API models: the report itself (from :mod:`qpilot.report.model`) and its exports.

``GET /api/studies/{id}/report`` answers :class:`ReportView`; ``POST …/report/export`` starts a
``report.export`` job whose result is :class:`ReportExported`; ``GET …/report/exports`` lists the
exports written since (newest first).
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

ReportFormat = Literal["md", "html", "passport"]


class ReportExportBody(BaseModel):
    """Which file to write."""

    format: ReportFormat = Field(
        description=(
            "md: the report as Markdown; html: a printable page; passport: one self-contained "
            "offline HTML file with charts, bound to a fresh Analysis Record."
        )
    )
    expected_head: str | None = Field(
        default=None, description="The chain head the page showed (warns when it moved since)."
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


class ReportExports(BaseModel):
    """The report files written for a study since qPilot started, newest first."""

    study_id: str
    exports: list[ReportExported]


__all__ = [
    "Citation",
    "DownloadLink",
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
