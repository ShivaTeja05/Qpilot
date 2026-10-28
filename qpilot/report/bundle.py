"""The zipped exports: the tables as CSV, the figures, and the journal supplement.

* :func:`csv_zip`: one tidy CSV per table (:func:`qpilot.report.tables.all_tables`) and a
  README, as decided (and the recommended analysis when it differs);
* :func:`figures_zip`: for each gene, its figure as SVG and 300-dpi PNG, the figure's source
  data (CSV) and its caption; a panel of the genes side by side (:mod:`qpilot.report.figures`);
* :func:`write_supplement`: what a journal asks for, in one zip: the workbook, every table as
  CSV (one per gene too), the MIQE 2.0 checklist, the figures, the study's RDML file with
  qPilot's Cq, N0 and exclusions written back (:mod:`qpilot.report.rdml_out`; the original file
  and the per-well CSV when that is not possible, and the README says which), and the Analysis
  Record (:func:`qpilot.core.record.write_record`) with its id on every About table.

Zips are deterministic apart from the Analysis Record inside the supplement (whose
``record.json`` carries the time it was written): members in sorted order, fixed dates.
"""

from __future__ import annotations

import io
import math
import shutil
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qpilot.report.figures import (
    SOURCE_COLUMNS,
    FigureError,
    GeneFigure,
    csv_text,
    figure_csv,
    figure_png,
    figure_rows,
    figure_svg,
    file_stem,
    gene_figure,
    panel_png,
    panel_svg,
)
from qpilot.report.tables import AS_DECIDED, StudyTables, Table, all_tables

ZIP_DATE = (1980, 1, 1, 0, 0, 0)
MAX_FIGURES = 12  # genes drawn by default when the study names no headline genes
RESEARCH_USE = "For research use only. Not for clinical or diagnostic use."


class BundleError(ValueError):
    """The zip cannot be written (the message says why)."""


def zip_bytes(members: Mapping[str, bytes]) -> bytes:
    """A deterministic zip: members sorted, fixed dates, deflated."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, members[name])
    return out.getvalue()


def table_csv(table: Table) -> bytes:
    """One table as tidy UTF-8 CSV (exact floats, ``TRUE``/``FALSE``, empty for no value)."""
    return csv_text(table.keys(), table.rows).encode("utf-8")


def csv_members(tables: StudyTables, record_id: str | None = None, folder: str = "") -> dict:
    """``{path: bytes}``: every table as one CSV file."""
    return {f"{folder}{t.name}.csv": table_csv(t) for t in all_tables(tables, record_id)}


def _readme_tables(tables: StudyTables) -> list[str]:
    lines = [
        "results.csv          one row per comparison and gene: call, fold change, 95 % CI low",
        "                     and high (x), log2 fold change, p (Welch), n per group (units)",
        "per_unit.csv         one row per comparison, gene and biological unit: wells used, mean",
        "                     Cq of the gene and of the reference genes, delta Cq, log2 RQ (the",
        "                     value tested) and RQ",
        "per_well.csv         one row per well: plate, well, sample, unit, group, role, target,",
        "                     Cq, N0, efficiency, amplification call, left out (and why)",
    ]
    if tables.recommended is not None:
        lines += [
            "results_recommended.csv, per_unit_recommended.csv",
            "                     the same at the recommended options (the cards' recommendations)",
        ]
    lines += [
        "decisions.csv        every decision: who, what, why, when, with its hash",
        "settings.csv         every analysis choice in use, the test and the conclusion rule",
        "methods.csv          the Methods paragraphs of the report",
        "miqe.csv             the MIQE 2.0 checklist: what the data show for each item",
        "about.csv            the study, the analysis, the input's and design's SHA-256, the",
        "                     decision chain head the Analysis Record carries",
    ]
    return lines


def _readme_head(tables: StudyTables, title: str, record_id: str | None = None) -> list[str]:
    lines = [
        title,
        "=" * len(title),
        "",
        f"Study: {tables.study_id}",
        f"Input file: {tables.source_name or 'unknown'} (SHA-256 {tables.input_sha256})",
        f"Decision chain head: {tables.chain_head}",
    ]
    if record_id:
        lines.append(f"Analysis Record id: {record_id}")
    lines += ["", f"Analysis: {tables.decided.words}."]
    if tables.recommended is not None:
        lines.append(
            "The recommended analysis (every card at its recommended option) is included too, in "
            "the files marked 'recommended'."
        )
    lines += [
        "",
        "Every number comes from qPilot's deterministic engine. CSV files are UTF-8, comma-",
        "separated; numbers are exact (as many digits as the engine has), TRUE/FALSE are",
        "logical values, and an empty cell is no value. Text that a spreadsheet would read as a",
        "formula starts with an apostrophe.",
        "",
    ]
    return lines


def csv_zip(tables: StudyTables, record_id: str | None = None) -> bytes:
    """Every table as one CSV file, and a README."""
    members = csv_members(tables, record_id)
    readme = _readme_head(tables, "qPilot tables (CSV)", record_id) + _readme_tables(tables)
    readme += ["", RESEARCH_USE, ""]
    members["README.txt"] = "\n".join(readme).encode("utf-8")
    return zip_bytes(members)


# ---- figures ---------------------------------------------------------------------------------


def default_genes(tables: StudyTables, basis: str = AS_DECIDED) -> list[str]:
    """The genes drawn when none are named: the headline genes, else the called genes by p."""
    comp = tables.analysis(basis).comparison()
    lead = [g for g in tables.headline if g in comp.contrasts]
    if lead:
        return lead
    called = [g for g, c in comp.contrasts.items() if c.conclusion in ("up", "down")]
    called.sort(key=lambda g: comp.contrasts[g].p if math.isfinite(comp.contrasts[g].p) else 1)
    return (called or list(comp.contrasts))[:MAX_FIGURES]


@dataclass(frozen=True)
class FigureSet:
    """The figure files of some genes, and the genes that could not be drawn (with why)."""

    members: dict[str, bytes]
    genes: tuple[str, ...]
    skipped: tuple[tuple[str, str], ...]


def figure_members(
    tables: StudyTables,
    genes: Sequence[str] | None = None,
    basis: str = AS_DECIDED,
    folder: str = "",
    comparison: str | None = None,
) -> FigureSet:
    """``{path: bytes}`` for each gene (SVG, PNG, source CSV, caption) and a panel of them.

    Raises:
        BundleError: No gene could be drawn.
    """
    wanted = list(genes) if genes else default_genes(tables, basis)
    members: dict[str, bytes] = {}
    figs: list[GeneFigure] = []
    skipped: list[tuple[str, str]] = []
    for gene in dict.fromkeys(wanted):
        try:
            fig = gene_figure(tables, gene, basis, comparison)
        except FigureError as err:
            skipped.append((gene, str(err)))
            continue
        stem = f"{folder}{file_stem(gene)}"
        members[f"{stem}.svg"] = figure_svg(fig).encode("utf-8")
        members[f"{stem}.png"] = figure_png(fig)
        members[f"{stem}_source.csv"] = figure_csv(fig).encode("utf-8")
        members[f"{stem}_caption.txt"] = (fig.caption + "\n").encode("utf-8")
        figs.append(fig)
    if not figs:
        why = "; ".join(f"{g}: {w}" for g, w in skipped) or "no gene was named"
        raise BundleError(f"no figure could be drawn ({why})")
    if len(figs) > 1:
        members[f"{folder}panel.svg"] = panel_svg(figs).encode("utf-8")
        members[f"{folder}panel.png"] = panel_png(figs)
        rows = [r for f in figs for r in figure_rows(f)]
        members[f"{folder}panel_source.csv"] = csv_text(SOURCE_COLUMNS, rows).encode("utf-8")
        captions = "\n\n".join(f"({chr(97 + i)}) {f.caption}" for i, f in enumerate(figs[:26]))
        members[f"{folder}panel_caption.txt"] = (captions + "\n").encode("utf-8")
    return FigureSet(members, tuple(f.gene for f in figs), tuple(skipped))


def _readme_figures(figures: FigureSet) -> list[str]:
    lines = [
        "For each gene: <gene>.svg (editable text), <gene>.png (300 dpi), <gene>_source.csv (one",
        "row per biological unit: the dots, and each group's mean and 95 % CI as drawn) and",
        "<gene>_caption.txt (the caption, from the engine's facts). panel.* shows them side by",
        "side. Dots are biological units, never technical replicates; colours are the Okabe-Ito",
        "palette (safe for colour-blind readers) and every group is named under its column.",
        f"Genes: {', '.join(figures.genes)}.",
    ]
    for gene, why in figures.skipped:
        lines.append(f"Not drawn: {gene} ({why}).")
    return lines


def figures_zip(
    tables: StudyTables,
    genes: Sequence[str] | None = None,
    basis: str = AS_DECIDED,
    comparison: str | None = None,
) -> tuple[bytes, FigureSet]:
    """The figures of ``genes`` (default: :func:`default_genes`) and a README, zipped."""
    figures = figure_members(tables, genes, basis, comparison=comparison)
    analysis = tables.analysis(basis)
    readme = _readme_head(tables, "qPilot figures")
    readme[readme.index(f"Analysis: {tables.decided.words}.")] = f"Analysis: {analysis.words}."
    readme += _readme_figures(figures) + ["", RESEARCH_USE, ""]
    members = dict(figures.members)
    members["README.txt"] = "\n".join(readme).encode("utf-8")
    return zip_bytes(members), figures


# ---- the journal supplement ------------------------------------------------------------------


@dataclass(frozen=True)
class SupplementInfo:
    """What the supplement holds."""

    path: Path
    record_id: str
    chain_head: str
    n_files: int
    rdml: str
    rdml_written_back: bool
    genes: tuple[str, ...]
    bases: tuple[str, ...]
    input_included: bool
    notes: tuple[str, ...] = ()
    n_record_files: int = 0
    record_name: str = ""


def _rdml(store: Any, study_id: str, tables: StudyTables) -> tuple[dict[str, bytes], str, bool]:
    """The RDML with results written back, else the original (and why), as zip members."""
    from qpilot.core.store import sha256_file
    from qpilot.report.rdml_out import RdmlOutError, wells_from_table, write_back

    source = store.source(study_id)
    if source is None or not Path(source).is_file():
        return {}, "The study's input file is not known here: no RDML file is included.", False
    if sha256_file(source) != tables.input_sha256:
        return {}, "The study's input file has changed since: no RDML file is included.", False
    design = store.design(study_id)
    trust = getattr(design, "import_trust", None) if design is not None else None
    quantities = getattr(trust, "analysis", None) != "cq_only"
    stem = Path(source).stem
    if tables.decided.rebuilt:
        try:
            wb = write_back(
                source,
                wells_from_table(tables.decided.per_well.records()),
                experiment_id=design.experiment_id if design is not None else None,
                quantities=quantities,
            )
        except RdmlOutError as err:
            note = f"qPilot could not write its results into the RDML file ({err})"
        else:
            name = f"data/{stem}-qpilot.rdml"
            words = f"{name}: the input file with qPilot's results. {wb.describe()}"
            return {name: wb.data}, words, True
    else:
        note = "the per-well results could not be rebuilt"
    name = f"data/{Path(source).name}"
    return (
        {name: Path(source).read_bytes()},
        f"{name}: the original input file, unchanged; {note}, so the per-well values are in "
        "tables/per_well.csv.",
        False,
    )


def write_supplement(
    store: Any,
    study_id: str,
    out_path: str | Path,
    *,
    session: str | None = None,
    genes: Sequence[str] | None = None,
    tables: StudyTables | None = None,
    progress: Any = None,
    record_out: str | Path | None = None,
) -> SupplementInfo:
    """Write the journal supplement zip (a new file ending in ``.zip``).

    ``record_out`` (a folder) also keeps a copy of the Analysis Record zip there, beside it.

    Raises:
        BundleError: The path is not a new ``.zip`` in an existing folder.
        qpilot.core.record.RecordError: The Analysis Record cannot be written.
        qpilot.core.store.StudyNotFound: Unknown study.
    """
    from qpilot.core.record import write_record, zip_record
    from qpilot.report.excel import ExcelError, excel_bytes, new_file, write_atomic
    from qpilot.report.tables import study_tables

    def step(text: str, fraction: float) -> None:
        if progress is not None:
            progress(text, fraction)

    try:
        out = new_file(out_path, ".zip", "supplement")
    except ExcelError as err:
        raise BundleError(str(err)) from err
    tables = tables if tables is not None else study_tables(store, study_id, session)
    members: dict[str, bytes] = {}
    notes: list[str] = []
    step("Writing the Analysis Record", 0.1)
    with tempfile.TemporaryDirectory(prefix="qpilot-supplement-") as tmp:
        info = write_record(store, study_id, Path(tmp) / "record", include_input=True)
        archive = zip_record(info.record_dir, Path(tmp) / f"qpilot-record-{study_id}.zip")
        members[f"record/{archive.name}"] = archive.read_bytes()
        if record_out is not None:
            shutil.copyfile(archive, Path(record_out) / archive.name)
        shutil.rmtree(info.record_dir, ignore_errors=True)
    record_id = info.record_id
    if info.chain_head != tables.chain_head:  # decided in between: read the study again
        tables = study_tables(store, study_id, session)
        notes.append("Something was decided while the supplement was written; it shows it.")
    step("Writing the workbook and the tables", 0.3)
    xlsx, _ = excel_bytes(store, study_id, tables=tables, record_id=record_id)
    members[f"qpilot-results-{study_id}.xlsx"] = xlsx
    members.update(csv_members(tables, record_id, "tables/"))
    per_unit = tables.decided.per_unit
    gene_at = per_unit.keys().index("gene")
    for gene in dict.fromkeys(r[gene_at] for r in per_unit.rows):
        rows = tuple(r for r in per_unit.rows if r[gene_at] == gene)
        one = Table(per_unit.name, per_unit.title, per_unit.columns, rows)
        members[f"tables/per_gene/{file_stem(gene)}.csv"] = table_csv(one)
    step("Drawing the figures", 0.55)
    try:
        figures = figure_members(tables, genes, AS_DECIDED, "figures/")
        members.update(figures.members)
        drawn = figures.genes
    except BundleError as err:
        figures, drawn = None, ()
        notes.append(f"No figure: {err}.")
    step("Writing the results into the RDML file", 0.7)
    rdml_members, rdml_note, written_back = _rdml(store, study_id, tables)
    members.update(rdml_members)
    readme = _readme_head(tables, "qPilot journal supplement", record_id)
    readme += [
        "Contents",
        "--------",
        f"qpilot-results-{study_id}.xlsx",
        "                     the same tables as one workbook (numbers as numbers)",
        "tables/              one CSV per table:",
        *(f"  {line}" for line in _readme_tables(tables)),
        "tables/per_gene/     per_unit.csv split by gene, one file each",
        "figures/             " + ("the figures:" if figures else "(none)"),
        *(f"  {line}" for line in (_readme_figures(figures) if figures else [])),
        "data/                " + rdml_note,
        f"record/              the Analysis Record (id {record_id}): the input file, every",
        "                     decision with its reason, the results and their checksums. Check",
        f"                     it with `qpilot verify {archive.name}`; re-run it with",
        "                     `qpilot rerun <unzipped folder>`.",
        "",
        "The MIQE 2.0 checklist (tables/miqe.csv) lists what the data show for each item and",
        "which items only a person can answer; it is not a compliance score.",
        *notes,
        "",
        RESEARCH_USE,
        "",
    ]
    members["README.txt"] = "\n".join(readme).encode("utf-8")
    step("Zipping", 0.9)
    data = zip_bytes(members)

    write_atomic(out, data)
    return SupplementInfo(
        path=out,
        record_id=record_id,
        chain_head=tables.chain_head,
        n_files=len(members),
        rdml=rdml_note,
        rdml_written_back=written_back,
        genes=tuple(drawn),
        bases=tables.bases,
        input_included=info.input_included,
        notes=tuple(notes),
        n_record_files=info.n_files,
        record_name=archive.name,
    )


__all__ = (
    "BundleError",
    "FigureSet",
    "SupplementInfo",
    "csv_members",
    "csv_zip",
    "default_genes",
    "figure_members",
    "figures_zip",
    "table_csv",
    "write_supplement",
    "zip_bytes",
)
