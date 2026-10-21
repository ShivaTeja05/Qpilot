"""Spreadsheet Check routes: recompute a lab's own ΔΔCq sheet and name the first step that differs.

* ``POST /sheets`` (multipart ``sheet``: an ``.xlsx`` or ``.csv`` file, at most 20 MB) keeps the
  file by content next to the study store (as Open keeps an input file) and answers its id.
* ``POST /sheets/{sheet_id}/check`` ``{study_id?, columns?, references?, confirm}`` recomputes
  it (:func:`qpilot.qpcr.sheetcheck.check_sheet`): how many of its fold changes reproduce from
  its own Cq values, the first column and row that differ, the known slip that reproduces it
  (an inverted sign, the exponent applied twice, statistics on fold changes, …), and, against a
  study, the genes whose arithmetic reproduces but whose fold change differs from qPilot's
  (hand-overs: a difference of method). Nothing is saved and the sheet is never edited.

The column mapping is guessed and says so ("mapping guessed, not confirmed") until a person
confirms it (``confirm``), after setting any column the guess got wrong. Sheet labels (sample
and group names) never come back: rows and columns are named by position, groups by order.
A study of a Studio session answers ``403 blind`` until its design and curves are confirmed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, UploadFile

from qpilot.web import results_views as rv
from qpilot.web import views
from qpilot.web.context import AppContext, Ctx, api_error
from qpilot.web.contract_sheets import (
    SheetCheckBody,
    SheetCheckView,
    SheetColumnCheckView,
    SheetColumnView,
    SheetFindingView,
    SheetGeneView,
    SheetHandOverView,
    SheetMappingView,
    SheetRoleView,
    SheetUploaded,
)

router = APIRouter(tags=["sheets"])

MAX_SHEET_BYTES = 20 * 1024 * 1024
SHEET_ID = re.compile(r"^[0-9a-f]{24}\Z")
NEVER_EDITED = "The sheet was read only; it is never edited, and nothing here is saved."
ROLE_WORDS: dict[str, str] = {
    "sample": "sample name",
    "group": "group",
    "bio_unit": "biological unit",
    "gene": "gene",
    "type": "sample type",
    "well": "well",
    "cq": "Cq",
    "mean_cq": "mean Cq",
    "dcq": "ΔCq",
    "ddcq": "ΔΔCq",
    "fc": "fold change",
    "mean_fc": "group mean fold change",
    "sd": "standard deviation",
    "sem": "standard error of the mean",
    "p": "p-value",
    "ignored": "not used",
}


def _kept(ctx: AppContext, sheet_id: str) -> Path:
    """The kept sheet with this id (404 when there is none)."""
    if not SHEET_ID.match(sheet_id or ""):
        raise api_error(404, "not_found", "There is no kept sheet with this id.")
    folder = views.inputs_dir(ctx.store)
    for suffix in views.INPUT_SUFFIXES["sheet"]:
        path = folder / f"{sheet_id}{suffix}"
        if path.is_file():
            return path
    raise api_error(404, "not_found", "There is no kept sheet with this id; drop the file again.")


def _mapping(path: Path, body: SheetCheckBody) -> Any:
    """The mapping to check with: the guess, with a person's columns and confirmation."""
    from qpilot.qpcr.sheetcheck import ColumnGuess, guess_mapping

    if not (body.columns or body.references or body.confirm):
        return None  # check_sheet guesses it and says so
    mapping = guess_mapping(path)
    columns = {c.column: c for c in mapping.columns}
    for item in body.columns or ():
        column = item.column.upper()
        old = columns.get(column)
        gene = (item.gene or "").strip() or (
            old.gene if old is not None and old.role == item.role else None
        )
        columns[column] = ColumnGuess(column=column, role=item.role, gene=gene, basis="user")
    ordered = sorted(columns.values(), key=lambda c: (len(c.column), c.column))
    update: dict[str, Any] = {"columns": ordered, "confirmed": bool(body.confirm)}
    if body.references is not None:
        update["references"] = [r.strip() for r in body.references if r.strip()]
    return mapping.model_copy(update=update)


def _text(result: Any, key: str, fallback: str) -> Any:
    from qpilot.explain.sheetcheck_text import render
    from qpilot.explain.templates import TemplateError

    try:
        rendered = render(result, key, allowed_names=[g.key for g in result.genes])
    except (TemplateError, KeyError):
        return rv.plain_text(fallback)
    return rv.fact_text(rendered.tokens, result.facts)


def _handover(result: Any, gene: str) -> Any:
    from qpilot.explain.sheetcheck_text import HANDOVER_KEY, render
    from qpilot.explain.templates import TemplateError

    try:
        rendered = render(result, HANDOVER_KEY, gene=gene, allowed_names=[gene])
    except (TemplateError, KeyError):
        return rv.plain_text("A difference of method for this gene.")
    return rv.fact_text(rendered.tokens, result.facts)


def sheet_view(sheet_id: str, name: str, study_id: str | None, result: Any) -> SheetCheckView:
    """A check as the page shows it (no sheet label: positions and order only)."""
    from qpilot.explain.sheetcheck_text import FINDINGS_KEY
    from qpilot.qpcr.sheetcheck import STEP_LABELS

    mapping = result.mapping
    summary = result.summary
    return SheetCheckView(
        sheet_id=sheet_id,
        name=name,
        file_sha256=result.file_sha256,
        file_kind=result.file_kind,
        n_rows=result.n_rows,
        study_id=study_id,
        mapping=SheetMappingView(
            status=mapping.status,
            confirmed=mapping.confirmed,
            sheet=mapping.sheet,
            header_row=mapping.header_row,
            layout=mapping.layout,
            columns=[
                SheetColumnView(
                    column=c.column,
                    role=c.role,
                    role_word=ROLE_WORDS.get(c.role, c.role),
                    gene=c.gene,
                    scale=c.scale,
                    basis=c.basis,
                    confidence=c.confidence,
                )
                for c in mapping.columns
            ],
            references=list(mapping.references),
            roles=[SheetRoleView(id=k, word=v) for k, v in ROLE_WORDS.items()],  # type: ignore[arg-type]
        ),
        headline=_text(result, "sheetcheck_v1", "The sheet was checked."),
        findings_text=_text(result, FINDINGS_KEY, "The differences could not be shown in words."),
        findings=[
            SheetFindingView(
                id=f.id,
                column=f.column,
                step_word=STEP_LABELS.get(f.step, f.step),
                gene=f.gene,
                first_row=f.first_row,
                n_rows=len(f.rows),
                status=f.status,
                paths=list(f.paths),
            )
            for f in result.findings
        ],
        columns=[
            SheetColumnCheckView(
                column=c.column,
                step=c.step,
                step_word=STEP_LABELS.get(c.step, c.step),
                gene=c.gene,
                status=c.status,
                n_cells=c.n_cells,
                n_reproduced=c.n_reproduced,
                n_differ=c.n_differ,
            )
            for c in result.columns
        ],
        hand_overs=[
            SheetHandOverView(
                gene=h.gene,
                conclusion_differs=h.conclusion_differs,
                causes=list(h.causes),
                line=_handover(result, h.gene),
            )
            for h in result.hand_overs
        ],
        genes=[
            SheetGeneView(key=g.key, reference=g.reference, flagged=g.flagged, note=g.note)
            for g in result.genes
        ],
        counts={
            "fold_changes": summary.n_fold_changes,
            "reproduced": summary.n_reproduced,
            "differ": summary.n_differ,
            "named": summary.n_named,
            "ambiguous": summary.n_ambiguous,
            "unexplained": summary.n_unexplained,
            "columns_checked": summary.n_columns_checked,
            "columns_reproduced": summary.n_columns_reproduced,
            "findings": summary.n_findings,
            "hand_overs": summary.n_hand_overs,
            "gene_name_flags": summary.n_symbol_flags,
        },
        notes=list(result.notes),
        never_edited=NEVER_EDITED,
    )


@router.post("/sheets", response_model=SheetUploaded)
async def upload_sheet(
    ctx: Ctx,
    sheet: Annotated[UploadFile, File(description="The analysis sheet (.xlsx or .csv).")],
) -> SheetUploaded:
    """Keep a lab's analysis sheet for checking (by content; the same file is kept once)."""
    from qpilot.web.routers.workspaces import _keep

    kept = await _keep(ctx, sheet, "sheet", MAX_SHEET_BYTES)
    name = Path(sheet.filename or kept.name).name[:200]
    return SheetUploaded(sheet_id=kept.stem, name=name, bytes=kept.stat().st_size)


@router.post("/sheets/{sheet_id}/check", response_model=SheetCheckView)
def check_kept_sheet(sheet_id: str, body: SheetCheckBody, ctx: Ctx) -> SheetCheckView:
    """Recompute the sheet from its own Cq values (read-only: nothing is saved or edited)."""
    from qpilot.core.store import StudyNotFound
    from qpilot.qpcr import sheetcheck

    path = _kept(ctx, sheet_id)
    if body.study_id is not None:
        from qpilot.web.routers.results import study

        study(ctx, body.study_id)  # 404 unknown, 403 blind: a comparison reveals results
    name = views.display_name(path) or path.name
    try:
        mapping = _mapping(path, body)
        if body.study_id is None:
            result = sheetcheck.check_sheet(path, mapping)
        else:
            result = sheetcheck.check_sheet_store(ctx.store, body.study_id, path, mapping)
    except sheetcheck.SheetCheckError as err:
        raise api_error(422, "bad_sheet", f"This sheet cannot be checked: {err}") from err
    except StudyNotFound as err:
        raise api_error(404, "not_found", "There is no analysed study with this id.") from err
    except (ValueError, OSError) as err:
        raise api_error(422, "bad_sheet", f"This sheet cannot be checked: {err}") from err
    return sheet_view(sheet_id, name, body.study_id, result)
