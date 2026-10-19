"""The tables Prism receives: one CSV per gene, log2 relative quantities per biological unit.

Step 2.1 of the Studio plan, independent of how the tables reach Prism. Prism receives numbers
it cannot misread:

* **log2 relative quantities** (``log2(target) - mean(log2(refs))``, the engine's own
  :func:`qpilot.qpcr.quant.relative`), so a t test in Prism runs on the log2 scale, never on
  2^-ΔΔCq fold changes;
* **one value per biological unit** in the column layout (``two_groups_log2``): first column
  ``Sample`` (row titles), then one column per group in the design's order; each unit's value
  sits in its group's column and the other cells are empty. Technical replicates are averaged
  per unit by the engine and never written as n;
* with technical replicates, the **nested layout** (``nested_superplot``): one subcolumn per
  biological unit inside its group, its replicates stacked as rows. A Prism nested table has one
  subcolumn count for the whole table [R], so every group is padded to the largest group with
  empty subcolumns (``<group>/empty_<k>``). GraphPad: "It is not possible to import subcolumn
  titles" [V] (https://graphpad.com/guides/prism/latest/user-guide/importing_data.htm), so the
  unit names travel in the CSV header and in the bundle, not as Prism subcolumn titles.

Files are UTF-8, comma-separated, LF line ends, fixed column order. Every value is written
with ``repr(float)``, which reads back bit for bit (``float.hex`` equality). A table may hold at
most 1,023 data sets (``.pzfx`` tables must have fewer than 1024 [V]); the nested layout counts
every subcolumn as a data set, the stricter reading, until step 0.1 checks it on a real seat.

Row titles are pseudonymised when the export is marked for sharing (``share=True``): pass the
core's HMAC pseudonym function as ``pseudonym``; without one, units are numbered ``U001``, ...
in sorted order (stable for one study, meaningless outside it).
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from qpilot.core.store import canonical_json
from qpilot.qpcr.export import ExportError, ExportInputs, check_label
from qpilot.schemas_studio import PrismBundle, PrismLayout, PrismTable

MAX_DATA_SETS = 1023  # ".pzfx" tables must have fewer than 1024 data sets [V]
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
ROW_TITLE_COLUMN = "Sample"
REPLICATE_COLUMN = "Replicate"
PAD_PREFIX = "empty_"
INFO_NOTE = (
    "Values computed by qPilot from raw curves (record id in the table titles); edits are "
    "detected when the tables are sent back."
)
NOT_AFFILIATED = (
    "Works with GraphPad Prism. Not affiliated with or endorsed by GraphPad Software or Dotmatics."
)
RECORD_REF = re.compile(r"^[A-Za-z0-9_.-]{1,40}\Z")
CHAIN_HEAD = re.compile(r"^[0-9a-f]{64}\Z")
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10)
}


class PrismExportError(ExportError):
    """The bundle cannot be built as asked (the message says why and what to do)."""


@dataclass(frozen=True)
class TemplateSpec:
    """One hand-made Prism template: its file, the table layout it takes, test and graph."""

    id: str
    file: str
    layout: PrismLayout | None
    test: str
    graph: str
    note: str = ""

    @property
    def path(self) -> Path:
        """Where the template file lives in the package (absent until made in Prism)."""
        return TEMPLATE_DIR / self.file


TEMPLATES: dict[str, TemplateSpec] = {
    "two_groups_log2": TemplateSpec(
        id="two_groups_log2",
        file="two_groups_log2.pzt",
        layout="column",
        test=(
            "Welch's unpaired t test (two-sided) on log2 relative quantities, one value per "
            "biological unit"
        ),
        graph="scatter of every unit with mean and 95 % confidence interval",
    ),
    "nested_superplot": TemplateSpec(
        id="nested_superplot",
        file="nested_superplot.pzt",
        layout="nested",
        test=(
            "nested t test on log2 relative quantities: biological units as subcolumns, "
            "technical replicates within them"
        ),
        graph="SuperPlot: every replicate, markers by biological unit",
    ),
    "many_genes_log2": TemplateSpec(
        id="many_genes_log2",
        file="many_genes_log2.pzt",
        layout=None,
        test="multiple unpaired t tests with false-discovery-rate control",
        graph="volcano or one row per gene",
        note=(
            "many_genes_log2 needs one grouped table with genes as rows, which the frozen "
            "PrismLayout ('column' | 'nested') cannot describe; the README says how to build "
            "the template, and the export needs a contract change first"
        ),
    ),
}


def template_spec(template_id: str) -> TemplateSpec:
    """The template's spec; ``PrismExportError`` for an unknown id."""
    if template_id not in TEMPLATES:
        known = ", ".join(sorted(TEMPLATES))
        raise PrismExportError(f"unknown template {template_id!r}; known: {known}")
    return TEMPLATES[template_id]


# ---------------------------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------------------------


def file_stem(gene: str) -> str:
    """A file-safe stem for a gene: letters, digits, ``_ - . ( )``; spaces become ``_``."""
    stem = re.sub(r"[^\w().-]", "_", gene)
    if not stem or stem.startswith(".") or not stem.isascii():
        raise PrismExportError(f"gene name {gene!r} cannot be a file name")
    if stem.split(".")[0].upper() in _WINDOWS_RESERVED:
        stem = f"{stem}_gene"
    return stem


def sequential_pseudonyms(units: Sequence[str]) -> dict[str, str]:
    """``U001``, ``U002``, ... over the sorted units (the fallback when no HMAC is given)."""
    width = max(3, len(str(len(units))))
    return {unit: f"U{i:0{width}d}" for i, unit in enumerate(sorted(units), start=1)}


def row_titles(
    inputs: ExportInputs, share: bool, pseudonym: Callable[[str], str] | None
) -> dict[str, str]:
    """Biological unit -> the title Prism shows (the unit itself unless shared)."""
    units = inputs.all_units()
    if not share:
        return {unit: unit for unit in units}
    titles = (
        {unit: pseudonym(unit) for unit in units}
        if pseudonym is not None
        else sequential_pseudonyms(units)
    )
    for title in titles.values():
        try:
            check_label(title, "pseudonym")
        except ExportError as err:
            raise PrismExportError(str(err)) from err
    if len(set(titles.values())) != len(titles):
        raise PrismExportError("the pseudonym function gave two units the same name")
    return titles


def table_title(gene: str, record_ref: str, chain_head: str) -> str:
    """The data table's title: the gene, the scale, the record ref and the short chain head."""
    return f"{gene} log2 RQ - qPilot {record_ref} - chain {chain_head[:12]}"


# ---------------------------------------------------------------------------------------------
# Rendering (pure: nothing is written)
# ---------------------------------------------------------------------------------------------


def render_tables(
    inputs: ExportInputs,
    genes: Sequence[str],
    template_id: str,
    *,
    record_ref: str,
    chain_head: str,
    share: bool = False,
    pseudonym: Callable[[str], str] | None = None,
) -> list[tuple[PrismTable, str]]:
    """Every table as ``(PrismTable, csv_text)``, without writing anything.

    Raises:
        PrismExportError: Unknown or unsupported template, unknown genes, not two groups, a
            nested template without technical replicates, or more than 1,023 data sets.
    """
    spec = template_spec(template_id)
    if spec.layout is None:
        raise PrismExportError(spec.note)
    if not RECORD_REF.match(record_ref):
        raise PrismExportError(f"record ref {record_ref!r}: use letters, digits, _ - . only")
    if not CHAIN_HEAD.match(chain_head):
        raise PrismExportError("chain head must be a sha256 hex digest")
    if len(inputs.group_order) != 2:
        raise PrismExportError(f"{template_id} compares exactly two groups")
    genes = list(dict.fromkeys(genes))
    if not genes:
        raise PrismExportError("no genes to export")
    allowed = set(inputs.genes) if inputs.genes else None
    if allowed is not None:
        outside = [g for g in genes if g not in allowed]
        if outside:
            raise PrismExportError(
                f"not analysed genes of this study (reference genes and the marker are not "
                f"exported): {outside}"
            )
    stems = {gene: file_stem(gene) for gene in genes}
    if len({s.lower() for s in stems.values()}) != len(stems):
        raise PrismExportError("two genes would share a file name")
    titles = row_titles(inputs, share, pseudonym)
    table = inputs.table(spec.layout, genes)
    if (
        spec.layout == "nested"
        and not (table.groupby(["gene", "biological_unit"]).size() > 1).any()
    ):
        raise PrismExportError(
            "nested_superplot needs technical replicates (more than one well per biological "
            "unit); this study has one per unit, so use two_groups_log2"
        )
    out = []
    for gene in genes:
        block = table[table["gene"] == gene]
        if block.empty:
            raise PrismExportError(f"{gene}: no unit has a value at these choices")
        render = _render_column if spec.layout == "column" else _render_nested
        columns, rows = render(block, inputs.group_order, titles)
        n_data_sets = len(columns) - 1
        if n_data_sets > MAX_DATA_SETS:
            raise PrismExportError(
                f"{gene}: {n_data_sets} data sets; a Prism table holds at most {MAX_DATA_SETS}"
            )
        text = csv_text([columns, *rows])
        name = stems[gene]
        out.append(
            (
                PrismTable(
                    name=name,
                    gene=gene,
                    layout=spec.layout,
                    title=table_title(gene, record_ref, chain_head),
                    columns=columns,
                    n_rows=len(rows),
                    csv=f"{name}.csv",
                    csv_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                ),
                text,
            )
        )
    return out


def _render_column(
    block: pd.DataFrame, order: Sequence[str], titles: Mapping[str, str]
) -> tuple[list[str], list[list[str]]]:
    columns = [ROW_TITLE_COLUMN, *order]
    rows = []
    for unit, group, value in zip(
        block["biological_unit"], block["group"], block["log2_rq"], strict=True
    ):
        cells = [""] * len(order)
        cells[list(order).index(group)] = format_value(value)
        rows.append([titles[unit], *cells])
    return columns, rows


def _render_nested(
    block: pd.DataFrame, order: Sequence[str], titles: Mapping[str, str]
) -> tuple[list[str], list[list[str]]]:
    per_group = {
        group: sorted(set(block.loc[block["group"] == group, "biological_unit"])) for group in order
    }
    width = max(len(units) for units in per_group.values())
    columns = [REPLICATE_COLUMN]
    series: list[list[float]] = []
    for group in order:
        units = per_group[group]
        for unit in units:
            reps = block[(block["group"] == group) & (block["biological_unit"] == unit)]
            columns.append(f"{group}/{titles[unit]}")
            series.append(reps.sort_values("well_rep")["log2_rq"].tolist())
        for k in range(1, width - len(units) + 1):
            name = f"{group}/{PAD_PREFIX}{k}"
            if name in columns:
                raise PrismExportError(f"a unit is named like a padding column: {name}")
            columns.append(name)
            series.append([])
    depth = max(len(s) for s in series)
    rows = [
        [f"rep {i + 1}", *(format_value(s[i]) if i < len(s) else "" for s in series)]
        for i in range(depth)
    ]
    return columns, rows


def format_value(value: float) -> str:
    """``repr(float)``: the shortest text that reads back to the same float, bit for bit."""
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise PrismExportError("a value is not finite")
    return repr(number)


def csv_text(rows: Sequence[Sequence[str]]) -> str:
    """CSV text for UTF-8 files: commas, minimal quoting, LF line ends."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerows(rows)
    return buffer.getvalue()


# ---------------------------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------------------------


def write_bytes(path: Path, data: bytes) -> None:
    """Write bytes via a temp file and an atomic rename (no newline translation anywhere)."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def bundle_digest(bundle: PrismBundle) -> str:
    """sha256 of the canonical JSON of the bundle without ``bundle_sha256``."""
    payload = canonical_json(bundle.model_dump(mode="json", exclude={"bundle_sha256"}))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def bundle_info(inputs: ExportInputs, spec: TemplateSpec, share: bool) -> dict[str, str]:
    """What the bundle says about itself (strings only; no numbers from the data)."""
    replicates = (
        "averaged per biological unit by qPilot; never written as n"
        if spec.layout == "column"
        else "stacked as rows inside each unit's subcolumn"
    )
    return {
        "note": INFO_NOTE,
        "scale": (
            "log2 relative quantity: log2 of the target minus the mean log2 of the reference "
            "genes, per biological unit"
        ),
        "layout": str(spec.layout),
        "template_file": spec.file,
        "graph": spec.graph,
        "groups": " vs ".join(inputs.group_order),
        "contrast": f"{inputs.group_order[0]} minus {inputs.group_order[1]} (log2)",
        "refs": ", ".join(inputs.refs),
        "undetermined": inputs.undetermined,
        "technical_replicates": replicates,
        "row_titles": "pseudonymised" if share else "biological unit ids",
        "design_note": inputs.design_note,
        "mode": "S: plain CSV tables and a Prism script; Prism reads and writes Prism files",
        "not_affiliated": NOT_AFFILIATED,
    }


def build_bundle(
    inputs: ExportInputs,
    genes: Sequence[str],
    template_id: str,
    out_dir: str | Path,
    *,
    record_ref: str,
    chain_head: str,
    design_hash: str,
    share: bool = False,
    pseudonym: Callable[[str], str] | None = None,
) -> PrismBundle:
    """Write one CSV per gene into ``out_dir`` and return the bundle that describes them.

    ``bundle.files`` lists the CSVs written here; :func:`qpilot.prism.provenance.finalize`
    adds the scripts and README and recomputes ``bundle_sha256`` once everything is written.

    Raises:
        PrismExportError: See :func:`render_tables`.
    """
    spec = template_spec(template_id)
    rendered = render_tables(
        inputs,
        genes,
        template_id,
        record_ref=record_ref,
        chain_head=chain_head,
        share=share,
        pseudonym=pseudonym,
    )
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)
    for table, text in rendered:
        write_bytes(directory / table.csv, text.encode("utf-8"))
    bundle = PrismBundle(
        study_id=inputs.study_id,
        record_ref=record_ref,
        chain_head=chain_head,
        design_hash=design_hash,
        template_id=template_id,
        test=spec.test,
        tables=[table for table, _ in rendered],
        info=bundle_info(inputs, spec, share),
        files={table.csv: table.csv_sha256 for table, _ in rendered},
        mode="script",
    )
    return bundle.model_copy(update={"bundle_sha256": bundle_digest(bundle)})


__all__ = [
    "INFO_NOTE",
    "MAX_DATA_SETS",
    "NOT_AFFILIATED",
    "TEMPLATES",
    "PrismExportError",
    "TemplateSpec",
    "build_bundle",
    "bundle_digest",
    "csv_text",
    "file_stem",
    "format_value",
    "render_tables",
    "row_titles",
    "sequential_pseudonyms",
    "table_title",
    "template_spec",
    "write_bytes",
]
