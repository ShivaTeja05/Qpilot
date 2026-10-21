"""Excel export of a stored study: the results table and Trace's "Where to look" sheet.

:func:`export_excel` writes one ``.xlsx`` file with three sheets:

* ``Results``: the app's results table (:func:`qpilot.app_state.results_table`, numbers rendered
  from the study's facts) plus a ``Trace`` column naming each gene's top place to look and what
  it does, e.g. ``HMBS_20080318/K22 (2016): changes the call``, or ``nothing unusual``;
* ``Where to look``: one row per place Trace ranks for each gene (the ``top`` first places);
* ``About``: the study id, the input file's sha256, how Trace ran, and the research-use line.

Trace runs read-only from the study's input file (as :func:`qpilot.qpcr.trace.trace_store`
does); when it cannot (the input file is unknown or changed), the results are still written,
the ``Trace`` column says ``not traced`` and the ``About`` sheet says why. Nothing is written to
the study's workspace, and the export decides nothing.

The file is byte-deterministic: openpyxl's own save stamps the time, so the package is
rewritten with fixed ``docProps/core.xml`` dates, members in sorted order and fixed member dates.
Text that a spreadsheet would read as a formula (``=``, ``+``, ``-``, ``@`` first) is stored as
text. Deterministic: no model call and no network.
"""

from __future__ import annotations

import io
import os
import re
import tempfile
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RESULTS_SHEET = "Results"
WHERE_SHEET = "Where to look"
ABOUT_SHEET = "About"
TRACE_COLUMN = "Trace"
WHERE_COLUMNS = (
    "result",
    "rank",
    "sample",
    "plate",
    "well",
    "checks",
    "consequence",
    "fold_off",
    "changes_call",
    "z",
    "calls_changed",
)
NOT_TRACED = "not traced"
RESEARCH_USE = "For research use only. Not for clinical or diagnostic use."
FIXED_TIME = b"2000-01-01T00:00:00Z"  # docProps/core.xml created and modified
ZIP_DATE = (1980, 1, 1, 0, 0, 0)  # the earliest date a zip member can carry
FORMULA_START = ("=", "+", "-", "@")
DIGITS = 6  # decimals kept for fold_off and z in the "Where to look" sheet
_CORE_DATES = re.compile(rb"<dcterms:(created|modified)([^>]*)>[^<]*<")


class ExcelError(ValueError):
    """The Excel file cannot be written: a bad path, an existing file, or openpyxl missing."""


@dataclass(frozen=True)
class ExcelExport:
    """What was written: the file, its row counts and how Trace ran."""

    path: Path
    n_results: int
    n_places: int
    traced: bool
    note: str = ""


def _openpyxl():
    try:
        import openpyxl
    except ImportError as err:  # an optional extra, like reading .xlsx sheets
        raise ExcelError("writing .xlsx needs openpyxl (pip install 'qpilot[studio]')") from err
    return openpyxl


def _traces(store, study_id: str, genes: Sequence[str], top: int, context) -> tuple[dict, str]:
    """Each gene's trace (``top`` places), or ``{}`` and why Trace could not run."""
    from qpilot.qpcr.trace import TraceError, _store_context, trace_gene

    if context is None:
        try:
            context = _store_context(store, study_id)
        except TraceError as err:
            return {}, str(err)
        except Exception as err:  # the results are still exported; the About sheet says why
            return {}, f"Trace could not run ({type(err).__name__})"
    out = {}
    for gene in genes:
        try:
            out[gene] = trace_gene(context, gene, top=top)
        except TraceError:
            continue  # a gene Trace cannot follow: its cell says "not traced"
    return out, ""


def _num(value: Any) -> float | None:
    if value is None:
        return None
    number = round(float(value), DIGITS)
    return number if number == number else None  # NaN stays empty


def where_rows(traces: Mapping[str, Any]) -> list[tuple]:
    """The "Where to look" rows: every ranked place of every gene, in the order given."""
    from qpilot.explain.trace_text import CONSEQUENCE_WORDS

    rows = []
    for gene, result in traces.items():
        for place in result.places:
            option = place.options.get(place.via, {})
            rows.append(
                (
                    gene,
                    place.rank,
                    place.sample,
                    place.plate,
                    place.well,
                    " ".join(place.checks) or None,
                    CONSEQUENCE_WORDS.get(place.consequence, place.consequence),
                    _num(place.fold_off),
                    place.consequence == "changes_call",
                    _num(place.z),
                    ", ".join(option.get("changed_calls") or ()) or None,
                )
            )
    return rows


def _put_rows(sheet, rows: Iterable[Sequence[Any]]) -> None:
    """Write rows from A1: empty text is an empty cell, and no text becomes a formula."""
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

    for r, row in enumerate(rows, start=1):
        for c, value in enumerate(row, start=1):
            if isinstance(value, str):
                value = ILLEGAL_CHARACTERS_RE.sub("", value) or None
            cell = sheet.cell(row=r, column=c, value=value)
            if isinstance(value, str) and value.startswith(FORMULA_START):
                cell.data_type = "s"  # text from a file is never a formula


def deterministic_xlsx(book) -> bytes:
    """``book`` saved as bytes that depend only on its content (fixed dates, sorted members)."""
    raw, out = io.BytesIO(), io.BytesIO()
    book.save(raw)
    with zipfile.ZipFile(raw) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in sorted(zin.infolist(), key=lambda i: i.filename):
            data = zin.read(info.filename)
            if info.filename == "docProps/core.xml":
                data = _CORE_DATES.sub(rb"<dcterms:\1\2>" + FIXED_TIME + b"<", data)
            member = zipfile.ZipInfo(info.filename, date_time=ZIP_DATE)
            member.compress_type = zipfile.ZIP_DEFLATED
            member.external_attr = 0o600 << 16
            zout.writestr(member, data)
    return out.getvalue()


def excel_bytes(store, study_id: str, *, top: int = 3, context=None) -> tuple[bytes, ExcelExport]:
    """The workbook's bytes and what it holds (``ExcelExport.path`` is empty).

    Args:
        store: The study store.
        study_id: The study.
        top: Places per gene in the "Where to look" sheet (1 to 50).
        context: A :class:`qpilot.qpcr.trace.TraceContext` already built for this study
            (default: built read-only from the study's input file).

    Raises:
        ExcelError: ``top`` out of range, or openpyxl is not installed.
        qpilot.core.store.StudyNotFound: Unknown study.
    """
    from qpilot import __version__
    from qpilot.app_state import results_table, trace_cell

    if isinstance(top, bool) or not isinstance(top, int) or not 1 <= top <= 50:
        raise ExcelError("top must be a whole number from 1 to 50")
    openpyxl = _openpyxl()
    result = store.get(study_id)
    table = results_table(result)
    genes = list(table["Gene"])
    traces, note = _traces(store, study_id, genes, top, context)
    trace_column = [trace_cell(traces[g]) if g in traces else NOT_TRACED for g in genes]
    book = openpyxl.Workbook()
    book.properties.creator = "qPilot"
    results = book.active
    results.title = RESULTS_SHEET
    header = [*table.columns, TRACE_COLUMN]
    body = [(*row, cell) for row, cell in zip(table.itertuples(index=False), trace_column,
                                                strict=True)]  # fmt: skip
    _put_rows(results, [header, *body])
    results.freeze_panes = "A2"
    where = book.create_sheet(WHERE_SHEET)
    places = where_rows(traces)
    _put_rows(where, [WHERE_COLUMNS, *places])
    where.freeze_panes = "A2"
    about = book.create_sheet(ABOUT_SHEET)
    how = (
        f"Trace ran on {len(traces)} of {len(genes)} results, at most {top} places each"
        if traces
        else f"Trace did not run: {note or 'no result could be traced'}"
    )
    _put_rows(
        about,
        [
            ("study_id", result.study_id),
            ("input_sha256", result.input_sha256),
            ("qpilot", __version__),
            ("trace", how),
            ("note", RESEARCH_USE),
        ],
    )
    data = deterministic_xlsx(book)
    info = ExcelExport(Path(), len(genes), len(places), bool(traces), note)
    return data, info


def export_excel(store, study_id: str, out_path: str | Path, *, top: int = 3,
                 context=None) -> ExcelExport:  # fmt: skip
    """Write the study's results and Trace's places to a new ``.xlsx`` file.

    Args:
        store: The study store (read only).
        study_id: The study.
        out_path: A new file ending in ``.xlsx`` in an existing folder.
        top: Places per gene in the "Where to look" sheet.
        context: A Trace context already built for this study (optional).

    Returns:
        What was written.

    Raises:
        ExcelError: The path does not end in ``.xlsx``, the file exists, its folder does not,
            ``top`` is out of range, or openpyxl is not installed.
        qpilot.core.store.StudyNotFound: Unknown study.
    """
    out = Path(out_path).expanduser()
    if out.suffix.lower() != ".xlsx":
        raise ExcelError("the Excel file must end in .xlsx")
    if out.exists():
        raise ExcelError(f"{out} already exists; choose a new file")
    if not out.parent.is_dir():
        raise ExcelError(f"the folder {out.parent} does not exist")
    data, info = excel_bytes(store, study_id, top=top, context=context)
    fd, tmp = tempfile.mkstemp(dir=out.parent, prefix=f".{out.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, out)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return ExcelExport(out, info.n_results, info.n_places, info.traced, info.note)
