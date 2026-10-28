"""Report routes: the study's report (Methods, MIQE 2.0, reviewer's report), and its exports.

* ``GET /api/studies/{id}/report`` → :class:`ReportView`. A study of a Studio session answers
  ``403 blind`` until its design and curves are confirmed (the results routes' rule).
* ``POST /api/studies/{id}/report/export`` ``{format: md | html | passport | xlsx | csv |
  figures | supplement}`` → a ``report.export`` job; its result (:class:`ReportExported`)
  carries the download. The passport also writes a fresh Analysis Record into the same folder
  and is bound to its record id; so is the supplement (the record is inside it, and beside it).
  The workbook, the CSV tables and the supplement hold the analysis as decided on the Decision
  Cards, and the recommended one too when it differs (``bases``); figures draw one of them
  (``basis``) for the ``genes`` asked (default: the headline genes).
* ``GET /api/studies/{id}/report/exports`` → the files written since qPilot started.
* ``GET /api/studies/{id}/report/figure/info?gene=…`` → :class:`FigureInfo` (one gene's figure:
  caption, groups, links); ``GET …/report/figure?gene=…&format=svg|png|csv`` → the file itself
  (``download=true`` to save it). Both under the blind rule; nothing is written.

Files are written into the study's own export folder in a ``record-report-*`` folder, so the
one download route (``GET /api/downloads/{id}``) serves them under the study's blind rule.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Response

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
    Basis,
    FigureFiles,
    FigureFormat,
    FigureGroup,
    FigureInfo,
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
# The tables, figures and supplement measured on the demo (64 plates, 24 576 wells) on 28 Oct:
# the workbook ~25 s (Trace of 58 genes), CSV ~10 s, figures ~12 s, the supplement ~50 s (it
# writes the results into the 60 MB RDML file and checks it against the schema).
TYPICAL_S: dict[str, float] = {
    "md": 3.0,
    "html": 3.0,
    "passport": 6.0,
    "xlsx": 25.0,
    "csv": 10.0,
    "figures": 12.0,
    "supplement": 50.0,
}
TITLES: dict[str, str] = {
    "md": "The report as Markdown",
    "html": "The report as a printable page",
    "passport": "The study passport (one offline HTML file)",
    "xlsx": "The numbers as an Excel workbook, with Trace's places to look",
    "csv": "The numbers as CSV tables (zip)",
    "figures": "A figure per gene: SVG, PNG and source data (zip)",
    "supplement": "The journal supplement (zip)",
}
EXTENSIONS: dict[str, str] = {
    "md": "md",
    "html": "html",
    "passport": "html",
    "xlsx": "xlsx",
    "csv": "zip",
    "figures": "zip",
    "supplement": "zip",
}
STEMS: dict[str, str] = {
    "xlsx": "qpilot-results",
    "csv": "qpilot-tables",
    "figures": "qpilot-figures",
    "supplement": "qpilot-supplement",
}
TABLE_FORMATS = ("xlsx", "csv", "figures", "supplement")
BOTH_BASES = (
    "The options chosen on the Decision Cards are not all the recommended ones: the file holds "
    "the analysis as decided, and the recommended analysis too (marked 'recommended')."
)
FIGURES_ONE_BASIS = (
    "The options chosen on the Decision Cards are not all the recommended ones: these figures "
    "show one analysis (named in each caption); the Gene section's Figure panel shows the other."
)
OPEN_CARDS = (
    "Some Decision Cards are still open: the file counts them at their recommended option and "
    "says so."
)
NO_EXPORT_NAME = (
    "No figure: a group, sample or gene of this study has a name the exports cannot write "
    "(use letters, digits, spaces and _ - . ( ) in names)."
)
FIGURE_MEDIA = {"svg": "image/svg+xml", "png": "image/png", "csv": "text/csv; charset=utf-8"}


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
        if fmt in TABLE_FORMATS:  # the study's numbers: no report prose to check
            folder = folders.private_dir(
                folders.workspace_exports(ctx.store.root, study_id), PREFIX
            )
            return _write_tables(ctx, study_id, sid, folder, body, progress)
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
            path.write_text(text, encoding="utf-8", newline="\n")
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
        (folder / EXPORT_FILE).write_text(
            exported.model_dump_json(), encoding="utf-8", newline="\n"
        )
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


def _tables(ctx: AppContext, study_id: str, sid: str | None) -> Any:
    from qpilot.report.tables import study_tables

    return study_tables(ctx.store, study_id, sid)


def _write_tables(
    ctx: AppContext,
    study_id: str,
    sid: str | None,
    folder: Path,
    body: ReportExportBody,
    progress: Progress,
) -> dict[str, Any]:
    """The study's numbers as a file: workbook, CSV zip, figures zip or supplement."""
    from qpilot.report.bundle import BundleError, csv_zip, figures_zip, write_supplement
    from qpilot.report.excel import ExcelError, export_excel, write_atomic

    fmt = body.format
    path = folder / f"{STEMS[fmt]}-{study_id}.{EXTENSIONS[fmt]}"
    warnings: list[str] = []
    record = None
    genes: list[str] = []
    try:
        progress("Reading the study's numbers (as decided on the Decision Cards)", 0.1)
        tables = _tables(ctx, study_id, sid)
        if fmt == "xlsx":
            progress("Tracing each gene for the 'Where to look' sheet", 0.3)
            info = export_excel(ctx.store, study_id, path, top=3, tables=tables)
            if not info.traced:
                why = (info.note or "no result could be traced").rstrip(".")
                warnings.append(f"Trace did not run ({why}); the numbers are written without it.")
        elif fmt == "csv":
            write_atomic(path, csv_zip(tables))
        elif fmt == "figures":
            progress("Drawing the figures", 0.4)
            data, figures = figures_zip(tables, body.genes, body.basis or "as_decided")
            write_atomic(path, data)
            genes = list(figures.genes)
            warnings += [f"{g} was not drawn: {why}" for g, why in figures.skipped]
        else:
            supplement = write_supplement(
                ctx.store,
                study_id,
                path,
                session=sid,
                genes=body.genes,
                tables=tables,
                progress=progress,
                record_out=folder,
            )
            genes = list(supplement.genes)
            warnings += list(supplement.notes)
            if not supplement.rdml_written_back:
                warnings.append(supplement.rdml.split(": ", 1)[-1])
            archive = folder / supplement.record_name
            record = ReportRecordRef(
                record_id=supplement.record_id,
                chain_head=supplement.chain_head,
                n_files=supplement.n_record_files,
                input_included=supplement.input_included,
                download=_link(ctx, archive),
                verify=f"qpilot verify {archive.name}",
                rerun=f"qpilot rerun {archive.name}",
            )
            if not supplement.input_included:
                warnings.append(
                    "The input file was not found, so the record can be verified but not re-run."
                )
    except (ExcelError, BundleError, RecordError, StudyNotFound, OSError, ValueError) as err:
        shutil.rmtree(folder, ignore_errors=True)
        raise JobError("cannot_export", f"The file could not be written: {err}") from err
    if tables.recommended is not None:
        warnings.append(FIGURES_ONE_BASIS if fmt == "figures" else BOTH_BASES)
    elif tables.n_open:
        warnings.append(OPEN_CARDS)
    head = tables.chain_head if record is None else record.chain_head
    moved = bool(body.expected_head) and head != body.expected_head
    if moved:
        warnings.append(
            "Something was decided after this page last refreshed; the file shows the study as "
            "it is now."
        )
    exported = ReportExported(
        study_id=study_id,
        format=fmt,
        title=TITLES[fmt],
        download=_link(ctx, path),
        chain_head=head,
        written_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        n_facts=0,
        record=record,
        head_moved=moved,
        warnings=warnings,
        bases=[body.basis or "as_decided"] if fmt == "figures" else list(tables.bases),
        genes=genes,
    )
    (folder / EXPORT_FILE).write_text(exported.model_dump_json(), encoding="utf-8", newline="\n")
    return exported.model_dump(mode="json")


# ---- one gene's figure (read only) --------------------------------------------------------------


def _figure(
    ctx: AppContext, study_id: str, gene: str, basis: Basis, comparison: str | None
) -> tuple[Any, Any]:
    from qpilot.qpcr.export import ExportError
    from qpilot.report.figures import FigureError, gene_figure

    sid = _study(ctx, study_id)
    try:
        tables = _tables(ctx, study_id, sid)
        found = ctx.store.get(study_id).comparisons
        for outcome in found.comparisons if found is not None and comparison else ():
            if outcome.id == comparison:  # a comparison's id (the page's picker) names it too
                comparison = outcome.label
        return tables, gene_figure(tables, gene, basis, comparison)
    except StudyNotFound as err:
        raise api_error(404, "not_found", "There is no analysed study with this id.") from err
    except ExportError as err:  # its message quotes the name: said in qPilot's words instead
        raise api_error(409, "no_figure", NO_EXPORT_NAME) from err
    except FigureError as err:
        if "is not a gene" in str(err) or "no comparison" in str(err):
            raise api_error(404, "not_found", f"No figure: {err}.") from err
        raise api_error(409, "no_figure", f"No figure: {err}.") from err


def _figure_url(study_id: str, gene: str, basis: str, fmt: str, comparison: str | None) -> str:
    from urllib.parse import urlencode

    query = {"gene": gene, "format": fmt, "basis": basis}
    if comparison:
        query["comparison"] = comparison
    return f"/api/studies/{study_id}/report/figure?{urlencode(query)}"


@router.get("/studies/{study_id}/report/figure/info", response_model=FigureInfo)
def figure_info(
    study_id: str,
    ctx: Ctx,
    gene: str = Query(min_length=1, max_length=200),
    basis: Basis = "as_decided",
    comparison: str | None = Query(default=None, max_length=300),
) -> FigureInfo:
    """One gene's figure: what it shows, its caption (from the engine's facts), its files."""
    tables, fig = _figure(ctx, study_id, gene, basis, comparison)
    analysis = tables.analysis(basis)
    return FigureInfo(
        study_id=study_id,
        gene=fig.gene,
        comparison=fig.comparison,
        comparisons=[c.name for c in analysis.comparisons],
        basis=basis,
        bases=list(tables.bases),
        basis_label=analysis.label,
        call=fig.call,  # type: ignore[arg-type]
        fold_change=fig.fc,
        ci95_low=fig.ci_lo,
        ci95_high=fig.ci_hi,
        p=fig.p,
        p_adjusted=fig.p_adjusted,
        n_a=fig.n_a,
        n_b=fig.n_b,
        groups=[
            FigureGroup(name=g.name, n=g.n, mean=g.mean, ci_low=g.ci_lo, ci_high=g.ci_hi)
            for g in fig.groups
        ],
        caption=fig.caption,
        note=fig.note,
        files=FigureFiles(
            **{
                f: _figure_url(study_id, fig.gene, basis, f, comparison)
                for f in ("svg", "png", "csv")
            }
        ),
        chain_head=tables.chain_head,
    )


@router.get(
    "/studies/{study_id}/report/figure",
    response_class=Response,
    responses={
        200: {
            "content": {"image/svg+xml": {}, "image/png": {}, "text/csv": {}},
            "description": "The figure as SVG or PNG, or its source data as CSV.",
        }
    },
)
def figure_file(
    study_id: str,
    ctx: Ctx,
    gene: str = Query(min_length=1, max_length=200),
    format: FigureFormat = "svg",  # noqa: A002 - the query parameter's name
    basis: Basis = "as_decided",
    comparison: str | None = Query(default=None, max_length=300),
    download: bool = False,
) -> Response:
    """One gene's figure as SVG (editable text), 300-dpi PNG, or its source data as CSV."""
    from qpilot.report.figures import figure_csv, figure_png, figure_svg, file_stem

    _, fig = _figure(ctx, study_id, gene, basis, comparison)
    if format == "svg":
        data: bytes = figure_svg(fig).encode("utf-8")
    elif format == "png":
        data = figure_png(fig)
    else:
        data = figure_csv(fig).encode("utf-8")
    suffix = "_source.csv" if format == "csv" else f".{format}"
    name = f"{file_stem(fig.gene)}{'' if basis == 'as_decided' else '_recommended'}{suffix}"
    disposition = "attachment" if download else "inline"
    return Response(
        content=data,
        media_type=FIGURE_MEDIA[format],
        headers={"Content-Disposition": f'{disposition}; filename="{name}"'},
    )


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
