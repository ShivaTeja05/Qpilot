"""Report routes: the study's report (Methods, MIQE 2.0, reviewer's report), and its exports.

* ``GET /api/studies/{id}/report`` → :class:`ReportView`. A study of a Studio session answers
  ``403 blind`` until its design and curves are confirmed (the results routes' rule).
* ``POST /api/studies/{id}/report/export`` ``{format: md | html | passport}`` → a
  ``report.export`` job; its result (:class:`ReportExported`) carries the download. The passport
  also writes a fresh Analysis Record into the same folder and is bound to its record id.
* ``GET /api/studies/{id}/report/exports`` → the files written since qPilot started.

Files are written into the study's own export folder in a ``record-report-*`` folder, so the
one download route (``GET /api/downloads/{id}``) serves them under the study's blind rule.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from qpilot.core.record import RecordError, write_record, zip_record
from qpilot.core.store import StudyNotFound
from qpilot.report import html as report_html
from qpilot.report import markdown as report_md
from qpilot.report.build import report as build_report
from qpilot.report.model import ReportView
from qpilot.report.text import ProseError
from qpilot.web import folders
from qpilot.web.context import AppContext, Ctx, api_error
from qpilot.web.contract import JobStarted, JobView
from qpilot.web.contract_files import DownloadLink
from qpilot.web.contract_report import (
    ReportExportBody,
    ReportExported,
    ReportExports,
    ReportFormat,
    ReportRecordRef,
)
from qpilot.web.jobs import JobError, Progress

router = APIRouter(tags=["report"])
JOB_RESULTS = {"report.export": ReportExported}

#: Inside the study's export folder; the ``record-`` prefix puts it under the study's blind rule.
PREFIX = "record-report-"
EXPORT_FILE = "report_export.json"
# Measured on the demo on 20 Oct (a shared, loaded laptop): the report is cached after its first
# build (~3 s); the passport also writes and zips the Analysis Record (7.8 MB with the input).
# The workbook traces every compared gene (``qpilot.report.excel``, origin/main's Excel export).
TYPICAL_S: dict[str, float] = {"md": 3.0, "html": 3.0, "passport": 6.0, "xlsx": 12.0}
TITLES: dict[str, str] = {
    "md": "The report as Markdown",
    "html": "The report as a printable page",
    "passport": "The study passport (one offline HTML file)",
    "xlsx": "The results as an Excel workbook, with Trace's places to look",
}
EXTENSIONS: dict[str, str] = {"md": "md", "html": "html", "passport": "html", "xlsx": "xlsx"}
AT_RECOMMENDED = (
    "The workbook shows the results at the recommended choices, as the Analysis Record does; "
    "the decisions you made are in the record and on the Decision Cards."
)


def _study(ctx: AppContext, study_id: str) -> str | None:
    """404 unknown, 403 ``blind`` while its session is; the study's session (if any)."""
    from qpilot.web.routers.results import study

    return study(ctx, study_id)


def _view(ctx: AppContext, study_id: str, sid: str | None) -> ReportView:
    try:
        return build_report(ctx.store, study_id, sid)
    except StudyNotFound as err:
        raise api_error(404, "not_found", "There is no analysed study with this id.") from err
    except ProseError as err:  # a sentence would show a number that is not a fact: never shown
        raise api_error(
            500,
            "report",
            "The report could not be written: one of its sentences would show a number that is "
            "not a fact of the study. Nothing was shown; please report this.",
        ) from err


def _exports(ctx: AppContext) -> Path:
    return folders.exports_root(ctx.store.root)


def _link(ctx: AppContext, path: Path) -> DownloadLink:
    """The download link of a file in the export folder (the same id when offered again)."""
    target = path.resolve()
    with ctx.lock:  # jobs register downloads from their own threads
        token = next((t for t, p in ctx.downloads.items() if p == target), None)
        if token is None:
            token = folders.register_download(ctx.downloads, _exports(ctx), target)
    return DownloadLink(
        id=token,
        url=f"/api/downloads/{token}",
        name=target.name,
        bytes=target.stat().st_size,
        path=str(target),
    )


@router.get("/studies/{study_id}/report", response_model=ReportView)
def get_report(study_id: str, ctx: Ctx) -> ReportView:
    """The study's report: summary, Methods, MIQE 2.0 checklist, reviewer's report, limitations."""
    sid = _study(ctx, study_id)
    return _view(ctx, study_id, sid)


def _write_record(ctx: AppContext, study_id: str, folder: Path) -> tuple[ReportRecordRef, Any]:
    info = write_record(ctx.store, study_id, folder / "record", include_input=True)
    archive = zip_record(info.record_dir, folder / f"qpilot-record-{study_id}.zip")
    shutil.rmtree(info.record_dir, ignore_errors=True)  # keep only the zip
    ref = ReportRecordRef(
        record_id=info.record_id,
        chain_head=info.chain_head,
        n_files=info.n_files,
        input_included=info.input_included,
        download=_link(ctx, archive),
        verify=f"qpilot verify {archive.name}",
        rerun=f"qpilot rerun {archive.name}",
    )
    return ref, info


@router.post("/studies/{study_id}/report/export", response_model=JobStarted, status_code=202)
def export_report(study_id: str, body: ReportExportBody, ctx: Ctx) -> JobStarted:
    """Write the report as Markdown, a printable page or the study passport (a job)."""
    sid = _study(ctx, study_id)
    fmt: ReportFormat = body.format

    def work(progress: Progress) -> dict[str, Any]:
        if fmt == "xlsx":  # the results table and Trace: no report prose to check
            folder = folders.private_dir(
                folders.workspace_exports(ctx.store.root, study_id), PREFIX
            )
            return _write_excel(ctx, study_id, folder, body, progress)
        progress("Reading the study and checking that every number is a fact", 0.1)
        view = _view_job(ctx, study_id, sid)
        folder = folders.private_dir(folders.workspace_exports(ctx.store.root, study_id), PREFIX)
        try:
            record = None
            if fmt == "passport":
                progress("Writing the Analysis Record the passport is bound to", 0.35)
                record, info = _write_record(ctx, study_id, folder)
                if info.chain_head != view.header.chain_head:  # decided in between: re-read
                    view = _view_job(ctx, study_id, sid)
            progress("Writing the file", 0.8)
            if fmt == "md":
                text = report_md.document(view)
            else:
                text = report_html.document(view, passport=fmt == "passport", record=record)
            stem = "qpilot-passport" if fmt == "passport" else "qpilot-report"
            path = folder / f"{stem}-{study_id}.{EXTENSIONS[fmt]}"
            path.write_text(text, encoding="utf-8")
        except (RecordError, StudyNotFound, OSError, ValueError) as err:
            shutil.rmtree(folder, ignore_errors=True)
            raise JobError("cannot_export", f"The file could not be written: {err}") from err
        moved = bool(body.expected_head) and view.header.chain_head != body.expected_head
        warnings = []
        if moved:
            warnings.append(
                "Something was decided after this page last refreshed; the file shows the study "
                "as it is now."
            )
        open_flips = [f for f in view.review.findings if f.id == "open_choices"]
        if open_flips:
            warnings.append(
                "Choices that can change a conclusion are still open; the file says so."
            )
        if record is not None and not record.input_included:
            warnings.append(
                "The input file was not found, so the record can be verified but not re-run."
            )
        exported = ReportExported(
            study_id=study_id,
            format=fmt,
            title=TITLES[fmt],
            download=_link(ctx, path),
            chain_head=view.header.chain_head,
            written_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            n_facts=len(view.facts),
            record=record,
            head_moved=moved,
            warnings=warnings,
        )
        (folder / EXPORT_FILE).write_text(exported.model_dump_json(), encoding="utf-8")
        return exported.model_dump(mode="json")

    job = ctx.jobs.submit(
        "report.export",
        work,
        title=TITLES[fmt],
        key=study_id,
        typical_s=TYPICAL_S[fmt],
        tag=fmt,  # one job per format: a Markdown export never answers for the passport
    )
    return JobStarted(job=JobView(**job.view()))


def _write_excel(
    ctx: AppContext,
    study_id: str,
    folder: Path,
    body: ReportExportBody,
    progress: Progress,
) -> dict[str, Any]:
    """The ``xlsx`` export: the results and Trace's places to look (``qpilot.report.excel``)."""
    from qpilot.report.excel import ExcelError, export_excel

    progress("Tracing each gene for the 'Where to look' sheet", 0.3)
    path = folder / f"qpilot-results-{study_id}.xlsx"
    try:
        info = export_excel(ctx.store, study_id, path, top=3)
    except (ExcelError, StudyNotFound, OSError) as err:
        shutil.rmtree(folder, ignore_errors=True)
        raise JobError("cannot_export", f"The workbook could not be written: {err}") from err
    warnings = []
    if not info.traced:
        why = (info.note or "no result could be traced").rstrip(".")
        warnings.append(f"Trace did not run ({why}); the results are written without it.")
    cards = ctx.store.cards(study_id)
    if any(c.decision is not None and c.decision != c.recommended for c in cards):
        warnings.append(AT_RECOMMENDED)
    head = ctx.store.chain_head(study_id)
    moved = bool(body.expected_head) and head != body.expected_head
    if moved:
        warnings.append(
            "Something was decided after this page last refreshed; the file shows the study as "
            "it is now."
        )
    exported = ReportExported(
        study_id=study_id,
        format="xlsx",
        title=TITLES["xlsx"],
        download=_link(ctx, path),
        chain_head=head,
        written_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        n_facts=0,
        head_moved=moved,
        warnings=warnings,
    )
    (folder / EXPORT_FILE).write_text(exported.model_dump_json(), encoding="utf-8")
    return exported.model_dump(mode="json")


def _view_job(ctx: AppContext, study_id: str, sid: str | None) -> ReportView:
    try:
        return build_report(ctx.store, study_id, sid)
    except ProseError as err:
        raise JobError(
            "report",
            "The report could not be written: one of its sentences would show a number that is "
            "not a fact of the study. Nothing was written; please report this.",
        ) from err
    except StudyNotFound as err:
        raise JobError("not_found", "There is no analysed study with this id.") from err


@router.get("/studies/{study_id}/report/exports", response_model=ReportExports)
def list_exports(study_id: str, ctx: Ctx) -> ReportExports:
    """The report files written for this study since qPilot started, newest first."""
    _study(ctx, study_id)
    found = []
    folder = folders.workspace_exports(ctx.store.root, study_id)
    for path in folder.glob(f"{PREFIX}*/{EXPORT_FILE}"):
        try:
            exported = ReportExported.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        target = path.parent / exported.download.name
        if exported.study_id != study_id or not target.is_file():
            continue
        update: dict[str, Any] = {"download": _link(ctx, target)}
        if exported.record is not None:
            archive = path.parent / exported.record.download.name
            if archive.is_file():
                update["record"] = exported.record.model_copy(
                    update={"download": _link(ctx, archive)}
                )
            else:
                update["record"] = None
        found.append((path.stat().st_mtime, exported.model_copy(update=update)))
    found.sort(key=lambda pair: pair[0], reverse=True)
    return ReportExports(study_id=study_id, exports=[e for _, e in found])
