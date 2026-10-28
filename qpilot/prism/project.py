"""The Prism project qPilot hands a scientist: ``.pzfx`` files that open in Prism as they are.

The default bundle needs nothing but GraphPad Prism on the scientist's computer: no template,
no script. :func:`render_project_tables` renders every table the project holds as qPilot's own
CSV text (the same bytes the bundle keeps as ``<table>.csv``, so the round trip compares against
checksummed files), and :func:`write_projects` writes them as Prism's XML (:mod:`.pzfx`):

* ``qpilot_<record>.pzfx``: the Info sheet ("qPilot provenance": the study, the decision
  record's head, the design hash, the analysis settings, who decided each choice and why), one
  **Column table** per gene (and per comparison, when the design has several), and one
  **Grouped table** of all the genes (genes as rows, groups as data sets, units as subcolumns);
* ``qpilot_<record>_replicates.pzfx``, only when biological units have technical replicates:
  the same Info sheet and one **Nested table** per gene. It is a file of its own because the
  attributes Prism uses for a Nested table are inferred, not documented [R]: if a Prism version
  reads them differently, the main project is unaffected.

Neither project file is in the bundle's checked ``files``: the scientist edits and saves them in
Prism, which is the point. Their sha256 as written is kept in the bundle's ``info`` (covered by
``bundle_sha256``), and the round trip compares what Prism saved with the checksummed CSVs.

qPilot cannot write Prism's analyses or graphs (that part of a ``.pzfx`` is Prism's own binary
block), so the README says exactly which clicks add the t test and the graph.

Works with GraphPad Prism. Not affiliated with or endorsed by GraphPad Software or Dotmatics.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import textwrap
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from qpilot.core.store import canonical_json
from qpilot.prism import pzfx
from qpilot.prism.tables import (
    INFO_NOTE,
    NOT_AFFILIATED,
    PrismExportError,
    render_tables,
    write_bytes,
)
from qpilot.qpcr.export import ExportInputs
from qpilot.schemas_studio import PrismBundle, PrismTable

GROUPED_NAME = "all_genes"
REPLICATES_SUFFIX = "_replicates"
INFO_PROJECT = "project"  # bundle.info keys
INFO_PROJECT_SHA = "project_sha256"
INFO_REPLICATES = "replicates_project"
INFO_REPLICATES_SHA = "replicates_project_sha256"
INFO_GROUPED = "grouped_table"
INFO_GROUPED_TITLE = "grouped_title"
CARD_WORDS = {
    "card_refset": "Reference genes",
    "card_cutoff": "Group cut-off",
    "card_amp_call": "Amplification rule",
    "card_efficiency": "Efficiency model",
    "card_undetermined": "Undetermined wells",
    "card_nondetect": "Undetermined wells",
}
ACTOR_WORDS = {
    "human": "decided by a person",
    "system": "set by qPilot: it changes no conclusion",
    None: "not decided yet: the recommended option",
}


def project_file(record_ref: str) -> str:
    """The main project's file name (the record ref is in it)."""
    return f"qpilot_{record_ref}.pzfx"


def replicates_file(record_ref: str) -> str:
    """The Nested tables' project file name."""
    return f"qpilot_{record_ref}{REPLICATES_SUFFIX}.pzfx"


def stamp(record_ref: str, chain_head: str) -> str:
    """The provenance every table title carries: the record ref and the short chain head."""
    return f"qPilot {record_ref} - chain {chain_head[:12]}"


def grouped_title(record_ref: str, chain_head: str) -> str:
    """The Grouped table's title."""
    return f"All genes log2 RQ - {stamp(record_ref, chain_head)}"


# ---------------------------------------------------------------------------------------------
# Comparisons (several, when the design has them; otherwise the study's one)
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ComparisonInputs:
    """One comparison the project has tables for: its key, words and the inputs to render."""

    key: str
    label: str
    inputs: ExportInputs
    primary: bool


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "group"


def comparisons(inputs: ExportInputs) -> list[ComparisonInputs]:
    """The comparisons to export: the study's own, then any further ones its design plans.

    A design with several comparisons (``StudyDesign.comparisons``, groups mode) gets a Column
    table per gene and comparison; the first comparison is the study's primary one and keeps
    the plain table names. Without such a plan this is the one comparison of ``inputs``.
    """
    first, second = inputs.group_order[0], inputs.group_order[1]
    out = [
        ComparisonInputs(
            key=f"{_slug(first)}_vs_{_slug(second)}",
            label=f"{first} vs {second}",
            inputs=inputs,
            primary=True,
        )
    ]
    design = inputs.design
    plan = getattr(design, "comparisons", None) if design is not None else None
    planned = list(getattr(plan, "comparisons", None) or ())
    if len(planned) < 2 or design is None or getattr(design, "mode", "") != "groups":
        return out
    in_data = set(inputs.data.loc[inputs.data["sample_type"] == "unkn", "sample"])
    for comparison in planned[1:]:
        a, b = str(comparison.group_a), str(comparison.group_b)
        groups = {
            s: d.group
            for s, d in design.samples.items()
            if s in in_data and getattr(d, "role", "unkn") == "unkn" and d.group in (a, b)
        }
        key_fn = getattr(comparison, "key", None)
        key = key_fn() if callable(key_fn) else f"{_slug(a)}_vs_{_slug(b)}"
        out.append(
            ComparisonInputs(
                key=str(key),
                label=str(getattr(comparison, "label", "") or f"{a} vs {b}"),
                inputs=replace(inputs, groups=groups, group_order=(a, b)),
                primary=False,
            )
        )
    return out


# ---------------------------------------------------------------------------------------------
# Rendering (pure)
# ---------------------------------------------------------------------------------------------


def has_replicates(inputs: ExportInputs, genes: Sequence[str]) -> bool:
    """True when a biological unit has more than one value for a gene (technical replicates)."""
    table = inputs.table("nested", list(genes))
    return bool((table.groupby(["gene", "biological_unit"]).size() > 1).any())


def render_project_tables(
    inputs: ExportInputs,
    genes: Sequence[str],
    *,
    record_ref: str,
    chain_head: str,
    share: bool = False,
    pseudonym: Callable[[str], str] | None = None,
) -> list[tuple[PrismTable, str]]:
    """Every table of the project as ``(PrismTable, csv_text)``: Column, then Nested ones.

    Column tables are named by the gene's file stem (``ODC1``); for a further comparison the
    stem gets ``__<comparison key>``. Nested tables (only with technical replicates) are
    ``<stem>_replicates``. Nothing is written.

    Raises:
        PrismExportError: As :func:`qpilot.prism.tables.render_tables`.
    """
    out: list[tuple[PrismTable, str]] = []
    plans = comparisons(inputs)
    for plan in plans:
        rendered = render_tables(
            plan.inputs,
            genes,
            "two_groups_log2",
            record_ref=record_ref,
            chain_head=chain_head,
            share=share,
            pseudonym=pseudonym,
        )
        for table, text in rendered:
            if not plan.primary:
                name = f"{table.name}__{plan.key}"
                title = f"{table.gene} log2 RQ {plan.label} - {stamp(record_ref, chain_head)}"
                table = table.model_copy(
                    update={"name": name, "csv": f"{name}.csv", "title": title}
                )
            out.append((table, text))
    if has_replicates(inputs, genes):
        for table, text in render_tables(
            inputs,
            genes,
            "nested_superplot",
            record_ref=record_ref,
            chain_head=chain_head,
            share=share,
            pseudonym=pseudonym,
        ):
            name = f"{table.name}{REPLICATES_SUFFIX}"
            title = f"{table.gene} log2 RQ by replicate - {stamp(record_ref, chain_head)}"
            out.append(
                (
                    table.model_copy(update={"name": name, "csv": f"{name}.csv", "title": title}),
                    text,
                )
            )
    return out


def tables_digest(rendered: Sequence[tuple[PrismTable, str]]) -> str:
    """sha256 of what the exported tables hold: per table its gene, layout and CSV bytes.

    Titles (which carry the record ref and the chain head) are left out on purpose: a new
    analysis whose tables hold exactly the same numbers has the same digest, so a Prism draft
    accepted for the earlier analysis is still current.
    """
    parts = [
        {"gene": t.gene, "layout": t.layout, "name": t.name, "csv_sha256": t.csv_sha256}
        for t, _ in rendered
    ]
    return hashlib.sha256(canonical_json(parts).encode("utf-8")).hexdigest()


def _grid(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text, newline="")))


def project_tables(
    bundle: PrismBundle, texts: dict[str, str]
) -> tuple[list[pzfx.ProjectTable], list[pzfx.ProjectTable]]:
    """The main project's tables (Column per gene, then Grouped) and the Nested ones.

    ``texts`` maps each table's CSV file name to its text (the bundle's own CSVs).
    """
    columns, nested = [], []
    for table in bundle.tables:
        grid = _grid(texts[table.csv])
        if table.layout == "column":
            columns.append(pzfx.column_table(table.name, table.title, grid))
        else:
            nested.append(pzfx.nested_table(table.name, table.title, grid))
    main: list[pzfx.ProjectTable] = list(columns)
    primary = [(t, c) for t, c in zip(bundle.tables, columns, strict=False) if "__" not in t.name]
    title = bundle.info.get(INFO_GROUPED_TITLE)
    if len(primary) > 1 and title:
        groups = [ds.title for ds in primary[0][1].data_sets]
        main.append(
            pzfx.grouped_table(
                GROUPED_NAME,
                title,
                [c for _, c in primary],
                groups,
                [t.gene for t, _ in primary],
            )
        )
    return main, nested


def grouped_width(rendered: Sequence[tuple[PrismTable, str]]) -> int:
    """The subcolumns a Grouped table of these tables needs (0 for fewer than two genes)."""
    primary = [(t, text) for t, text in rendered if t.layout == "column" and "__" not in t.name]
    if len(primary) < 2:
        return 0
    tables = [pzfx.column_table(t.name, t.title, _grid(text)) for t, text in primary]
    groups = [ds.title for ds in tables[0].data_sets]
    return max(len(u) for u in pzfx.grouped_units(tables, groups).values())


def grouped_fits(rendered: Sequence[tuple[PrismTable, str]]) -> bool:
    """True when a Grouped table is worth writing (two genes or more) and fits Prism's limit."""
    width = grouped_width(rendered)
    return 0 < width <= pzfx.MAX_SUBCOLUMNS


OLD_PRISM_SUBCOLUMNS = 256  # Prism 6 to 8 (KB 845)


# ---------------------------------------------------------------------------------------------
# The Info sheet
# ---------------------------------------------------------------------------------------------


def _reasons(entries: Sequence[Any]) -> dict[str, str]:
    """The reason of the last applied decision on each card (from the decision record)."""
    out: dict[str, str] = {}
    for entry in entries:
        card = getattr(entry, "card_id", None)
        if card and getattr(entry, "status", "applied") == "applied":
            out[str(card)] = str(getattr(entry, "reason", "") or "")
    return out


def info_sheet(
    bundle: PrismBundle,
    inputs: ExportInputs,
    entries: Sequence[Any] = (),
    labels: dict[str, dict[str, str]] | None = None,
) -> pzfx.ProjectInfo:
    """The Info sheet: qPilot's provenance as constants (key facts) and notes (sentences).

    ``labels`` gives each card's options in words (card id -> option id -> label), from the
    study's Decision Cards; without it the option ids are shown.
    """
    reasons = _reasons(entries)
    labels = labels or {}
    constants: list[tuple[str, str]] = [
        ("qPilot study", bundle.study_id),
        ("qPilot record", bundle.record_ref),
        ("Decision record head (sha256)", bundle.chain_head),
        ("Design hash (sha256)", bundle.design_hash),
        ("Input file sha256", inputs.input_sha256),
        ("Scale", "log2 relative quantity (log2 of the target minus the mean log2 of the refs)"),
        ("Groups", " vs ".join(inputs.group_order)),
        ("Reference genes", ", ".join(inputs.refs)),
        ("Undetermined wells", str(inputs.undetermined)),
        ("Conclusion rule", inputs.rule.describe()),
        ("Test qPilot used", "Welch's unpaired t test on log2 values, one value per unit"),
    ]
    notes = [
        INFO_NOTE,
        "Each Column table holds one value per biological unit (technical replicates are "
        "averaged by qPilot and never counted as n); the groups are its data sets.",
        "The values are already log2: use the ordinary t test, not a lognormal one, and do not "
        "convert them back to fold changes first.",
    ]
    for choice in inputs.choices:
        title = CARD_WORDS.get(choice.card_id, choice.card_id.removeprefix("card_"))
        who = ACTOR_WORDS.get(choice.actor, f"decided by {choice.actor}")
        words = labels.get(choice.card_id, {})
        option = words.get(choice.option, choice.option)
        constants.append((f"Choice: {title}", f"{option} ({who})"))
        reason = reasons.get(choice.card_id)
        note = f"{title}: {option}, {who}"
        if choice.option != choice.recommended:
            note += f" (qPilot recommended {words.get(choice.recommended, choice.recommended)})"
        notes.append(note + (f". Reason: {reason}" if reason and choice.actor else "."))
    caption = bundle.info.get("caption")
    if caption:
        notes.append(f"Caption (numbers from the recommended analysis): {caption}")
    notes.append(NOT_AFFILIATED)
    constants.append(("qPilot version", _version()))
    return pzfx.ProjectInfo(
        title=pzfx.INFO_TITLE,
        notes=tuple(_clean(n) for n in notes),
        constants=tuple((_clean(k), _clean(v)) for k, v in constants),
    )


def _clean(text: str) -> str:
    """Text safe for XML: control characters become spaces."""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", str(text))


def _version() -> str:
    from qpilot import __version__

    return str(__version__)


# ---------------------------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------------------------


def write_projects(
    bundle: PrismBundle,
    inputs: ExportInputs,
    out_dir: str | Path,
    *,
    entries: Sequence[Any] = (),
    labels: dict[str, dict[str, str]] | None = None,
) -> dict[str, str]:
    """Write the project file(s) into ``out_dir``; return the ``info`` entries that name them.

    The bundle's CSVs must already be written there (they are the tables' text).

    Raises:
        PrismExportError: A table cannot be written as Prism XML.
    """
    directory = Path(out_dir)
    texts = {t.csv: (directory / t.csv).read_text(encoding="utf-8") for t in bundle.tables}
    main, nested = project_tables(bundle, texts)
    info = info_sheet(bundle, inputs, entries, labels)
    written: dict[str, str] = {}
    try:
        data = pzfx.write_project(main, info, version=_version())
        write_bytes(directory / project_file(bundle.record_ref), data)
        written[INFO_PROJECT] = project_file(bundle.record_ref)
        written[INFO_PROJECT_SHA] = hashlib.sha256(data).hexdigest()
        if nested:
            data = pzfx.write_project(nested, info, version=_version())
            write_bytes(directory / replicates_file(bundle.record_ref), data)
            written[INFO_REPLICATES] = replicates_file(bundle.record_ref)
            written[INFO_REPLICATES_SHA] = hashlib.sha256(data).hexdigest()
    except pzfx.PzfxError as err:
        raise PrismExportError(str(err)) from err
    return written


def project_bytes(bundle: PrismBundle, inputs: ExportInputs, texts: dict[str, str]) -> bytes:
    """The main project's bytes without writing anything (the preview and the tests)."""
    main, _ = project_tables(bundle, texts)
    try:
        return pzfx.write_project(main, info_sheet(bundle, inputs), version=_version())
    except pzfx.PzfxError as err:
        raise PrismExportError(str(err)) from err


# ---------------------------------------------------------------------------------------------
# Plain instructions (README and the page): no command line, both operating systems
# ---------------------------------------------------------------------------------------------

PLATFORMS = ("windows", "macos")
PLATFORM_WORDS = {"windows": "Windows", "macos": "macOS"}


def open_steps(project: str, platform: str) -> list[str]:
    """How to open the project on one operating system, in plain words."""
    unzip = (
        "Unzip the bundle: right-click the zip and choose Extract All."
        if platform == "windows"
        else "Unzip the bundle: double-click the zip."
    )
    other = (
        "right-click it and choose Open with > GraphPad Prism"
        if platform == "windows"
        else "Control-click it and choose Open With > GraphPad Prism"
    )
    return [
        unzip + " (Skip this when Prism runs on this computer: the folder is already here.)",
        f"Double-click {project}. GraphPad Prism opens it (or in Prism: File > Open). If "
        f"another program opens it, {other}.",
    ]


ANALYSE_STEPS: tuple[str, ...] = (
    "In Prism, click a gene's table under Data Tables (one table per gene).",
    "The test: click Analyze, choose 't tests (and nonparametric tests)', OK. Choose Unpaired, "
    "Parametric and Welch's correction (do not assume equal SDs), then OK.",
    "The graph: click New Graph, choose the scatter plot of individual values with 'Mean with "
    "95% CI', then OK.",
)
ROUND_TRIP_STEPS: tuple[str, ...] = (
    "Leave a value out in Prism with Edit > Exclude (the value shows in blue italics with an "
    "asterisk), or change it.",
    "Save the project: File > Save. If Prism asks for a format, keep Prism XML (.pzfx).",
    "In qPilot, open Prism > Round trip and choose the saved project file. Each exclusion or "
    "change comes back as a question, with what it does to the conclusions.",
)
NOT_WRITTEN = (
    "qPilot writes the data tables and the Info sheet in Prism's documented XML format. It "
    "cannot write Prism's analyses or graphs (that part of a Prism file only Prism writes), so "
    "you add them with the clicks above; Prism keeps them when you save."
)


WIDTH = 92


def _numbered(steps: Sequence[str]) -> list[str]:
    out: list[str] = []
    for i, step in enumerate(steps, start=1):
        out += textwrap.wrap(f"{i}. {step}", WIDTH, subsequent_indent="   ")
    return out


def readme_text(
    bundle: PrismBundle, *, scripts: bool, platform: str, notes: Sequence[str] = ()
) -> str:
    """The bundle's ``README.txt``: plain steps for Windows and macOS, this computer's first."""
    project = bundle.info.get(INFO_PROJECT, project_file(bundle.record_ref))
    replicates = bundle.info.get(INFO_REPLICATES)
    columns = [t for t in bundle.tables if t.layout == "column"]
    order = [platform, *(p for p in PLATFORMS if p != platform)]
    lines = [
        f"qPilot project for GraphPad Prism: study {bundle.study_id}, record {bundle.record_ref}",
        "",
        "What is here",
        f"- {project}: the Prism project. It opens in GraphPad Prism as it is; no template",
        "  and no script are needed. It holds:",
        "  - an Info sheet 'qPilot provenance': the study, the decision record, the analysis",
        "    settings and who decided each choice;",
        f"  - one Column table per gene ({len(columns)}): log2 relative quantities, one value per",
        "    biological unit, one column per group. Technical replicates are averaged per unit",
        "    by qPilot and never counted as n;",
    ]
    if bundle.info.get(INFO_GROUPED_TITLE):
        lines += [
            "  - a Grouped table of all the genes (genes as rows, units as subcolumns), for",
            "    Analyze > 'Multiple t tests - one per row'.",
        ]
    if replicates:
        lines += [
            f"- {replicates}: the same tables by technical replicate (Nested tables, one",
            "  subcolumn per biological unit), for Prism's nested t test. A file of its own:",
            "  how Prism reads a Nested table written outside Prism is not checked yet.",
        ]
    lines += [
        "- <gene>.csv: the same tables as plain CSV (File > Import in any program).",
        "- qpilot_provenance.json, qpilot_bundle.json: how every value was made, and checksums",
        "  (qpilot prism verify --bundle <this folder>).",
        "",
    ]
    for p in order:
        lines.append(f"Open it ({PLATFORM_WORDS[p]})")
        lines += _numbered(open_steps(project, p))
        lines.append("")
    lines.append("Add the test and the graph (Windows and macOS)")
    lines += _numbered(ANALYSE_STEPS)
    lines += textwrap.wrap(NOT_WRITTEN, WIDTH)
    lines.append("")
    lines.append("Bring your changes back to qPilot")
    lines += _numbered(ROUND_TRIP_STEPS)
    lines.append("")
    if scripts:
        lines += [
            "Optional: the Prism scripts (for a hand-made template)",
            "- run.pzc imports each table into your template; send_back.pzc exports the tables",
            "  to sent_back/ for qpilot prism diff. You do not need them to use the project.",
            "",
        ]
    if notes:
        lines.append("Notes")
        for note in notes:
            lines += textwrap.wrap(f"- {note}", WIDTH, subsequent_indent="  ")
        lines.append("")
    lines += [
        "Not yet opened in a real Prism by the qPilot team: the file follows GraphPad's published",
        "XML schema and files saved by Prism 6 to 10. If Prism refuses it, the CSV files hold the",
        "same tables.",
        "",
        "Works with GraphPad Prism. Not affiliated with or endorsed by GraphPad Software or",
        "Dotmatics.",
    ]
    return "\n".join(lines) + "\n"


def project_names(bundle: PrismBundle) -> list[str]:
    """The project files a bundle wrote (main first)."""
    return [bundle.info[k] for k in (INFO_PROJECT, INFO_REPLICATES) if bundle.info.get(k)]


__all__ = [
    "ANALYSE_STEPS",
    "GROUPED_NAME",
    "ROUND_TRIP_STEPS",
    "ComparisonInputs",
    "comparisons",
    "grouped_fits",
    "grouped_width",
    "grouped_title",
    "has_replicates",
    "info_sheet",
    "open_steps",
    "project_bytes",
    "project_file",
    "project_names",
    "project_tables",
    "readme_text",
    "render_project_tables",
    "replicates_file",
    "tables_digest",
    "write_projects",
]
