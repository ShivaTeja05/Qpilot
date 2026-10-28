"""The GraphPad Prism bridge: a Prism project that opens as it is, with provenance.

Scientists move qPCR results into Prism for statistics and figures. The usual route (ΔΔCq in a
spreadsheet, 2^-ΔΔCq pasted into Prism, a t test on the linear scale) changes conclusions that
the engine's own analysis makes (``docs/studio-measured.md``). This package hands Prism log2
relative quantities per biological unit, never technical replicates as n, with the record ref
in every table title and ``qpilot_provenance.json`` beside the project, and later detects what
a scientist changed in Prism.

The default bundle (Mode X, ``project=True``) is a ``.pzfx`` project qPilot writes itself in
Prism's documented XML format (:mod:`qpilot.prism.project`, :mod:`qpilot.prism.pzfx`): it needs
only GraphPad Prism on the scientist's computer, no template and no script. qPilot writes and
reads only the documented plain-XML data part of the file (data tables and the Info sheet),
never Prism's binary analyses and graphs. The older route (Mode S: CSV tables plus Prism
scripts, ``.pzc``, for a hand-made template) stays available as an optional extra
(``scripts=True``, or ``project=False`` for exactly the old bundle).

* :mod:`qpilot.prism.tables`: one CSV per gene, column or nested layout (step 2.1);
* :mod:`qpilot.prism.project` and :mod:`qpilot.prism.pzfx`: the Prism project itself;
* :mod:`qpilot.prism.script`: ``run.pzc`` and ``send_back.pzc`` (step 2.2, optional);
* :mod:`qpilot.prism.provenance`: ``qpilot_provenance.json`` and its check (step 2.3);
* :mod:`qpilot.prism.roundtrip`: what changed in Prism, as proposals (steps 6.1 and 6.2).

:func:`export_study`, :func:`preview` and :func:`diff_report` are what the CLI uses and what the
MCP tools (``qpcr_prism_preview``, ``qpcr_prism_diff``) should call. :func:`preview` and
:func:`diff_report` write nothing; only :func:`export_study` writes, and only into its own
output folder (never into the study's workspace).

Works with GraphPad Prism. Not affiliated with or endorsed by GraphPad Software or Dotmatics.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from qpilot.prism.project import (
    GROUPED_NAME,
    INFO_GROUPED_TITLE,
    INFO_PROJECT,
    INFO_REPLICATES,
    OLD_PRISM_SUBCOLUMNS,
    PLATFORMS,
    grouped_fits,
    grouped_title,
    grouped_width,
    open_steps,
    project_file,
    project_names,
    render_project_tables,
    replicates_file,
    tables_digest,
    write_projects,
)
from qpilot.prism.project import readme_text as project_readme
from qpilot.prism.provenance import (
    BUNDLE_FILE,
    PROVENANCE_FILE,
    caption,
    finalize,
    load_bundle,
    verify_provenance,
    write_provenance,
)
from qpilot.prism.pzfx import MAX_SUBCOLUMNS
from qpilot.prism.roundtrip import (
    SOURCE_PROJECT,
    SOURCE_SENT_BACK,
    diff,
    diff_returned,
    is_project_path,
    read_returned,
    read_sent_back,
    round_trip_proposals,
)
from qpilot.prism.script import (
    GRAPH_FORMATS,
    RUN_SCRIPT,
    SEND_BACK_SCRIPT,
    LaunchCommand,
    Platform,
    host_platform,
    join,
    launch_command,
    open_command,
    prism_dir_for,
    prism_runs_here,
    readme_text,
    write_scripts,
)
from qpilot.prism.tables import (
    NOT_AFFILIATED,
    TEMPLATES,
    PrismExportError,
    build_bundle,
    bundle_info,
    render_tables,
    template_spec,
    write_bytes,
)
from qpilot.schemas_studio import PrismBundle, Proposal

if TYPE_CHECKING:
    from qpilot.core.store import StudyStore

README_FILE = "README.txt"
DEFAULT_TEMPLATE = "two_groups_log2"


@dataclass(frozen=True)
class ExportResult:
    """What :func:`export_study` wrote.

    ``project`` is the Prism project file (``None`` for a scripts-only bundle); ``launch``
    opens it (or runs ``run.pzc`` in a scripts-only bundle) and ``send_back`` runs
    ``send_back.pzc`` (``None`` when no script was written). ``open_steps`` says, per
    operating system, how a person opens the project, in plain words.
    """

    bundle: PrismBundle
    out_dir: Path
    files: dict[str, Path]
    template_present: bool
    launch: LaunchCommand
    send_back: LaunchCommand | None
    notes: list[str] = field(default_factory=list)
    project: Path | None = None
    replicates_project: Path | None = None
    scripts: bool = False
    open_steps: dict[str, list[str]] = field(default_factory=dict)


def export_study(
    store: StudyStore,
    study_id: str,
    out_dir: str | Path,
    *,
    genes: Sequence[str] | None = None,
    template_id: str = DEFAULT_TEMPLATE,
    share: bool = False,
    pseudonym: Callable[[str], str] | None = None,
    platform: Platform | None = None,
    prism_dir: str | None = None,
    graphs: Sequence[str] = ("pdf",),
    rdml_path: str | Path | None = None,
    record_ref: str | None = None,
    project: bool = True,
    scripts: bool | None = None,
) -> ExportResult:
    """Write the bundle for a study: the Prism project, CSVs, README and provenance.

    By default (``project=True``) the bundle is a ``.pzfx`` project that opens in Prism as it
    is (:mod:`qpilot.prism.project`), its tables as CSV, a README with plain steps for Windows
    and macOS, ``qpilot_provenance.json`` and ``qpilot_bundle.json``. ``scripts=True`` adds the
    optional Prism scripts (``run.pzc``, ``send_back.pzc``) for a hand-made template.
    ``project=False`` writes the older scripts-only bundle (Mode S) exactly as before.

    Writes only into ``out_dir``, which must be new or empty; the bundle sha256 is stored there
    (in ``qpilot_bundle.json``, which also holds the sha256 of ``qpilot_provenance.json``), not
    in the study's workspace.

    Raises:
        PrismExportError: The folder is not empty, or the export cannot be built as asked.
        qpilot.qpcr.export.ExportError: The study cannot be rebuilt for export.
    """
    if not project:
        return _export_scripts_only(
            store,
            study_id,
            out_dir,
            genes=genes,
            template_id=template_id,
            share=share,
            pseudonym=pseudonym,
            platform=platform,
            prism_dir=prism_dir,
            graphs=graphs,
            rdml_path=rdml_path,
            record_ref=record_ref,
        )
    from qpilot.qpcr.export import demo_inputs

    write_scripts_too = bool(scripts)
    directory = Path(out_dir)
    if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
        raise PrismExportError(f"the output folder must be new or empty: {directory}")
    platform = platform or host_platform()
    spec = template_spec(template_id)
    inputs = demo_inputs(store, study_id, rdml_path=rdml_path)
    chosen = list(genes) if genes else list(inputs.headline)
    ref = record_ref or study_id
    # Everything that can refuse is checked before the first file is written.
    rendered = render_project_tables(
        inputs,
        chosen,
        record_ref=ref,
        chain_head=inputs.chain_head,
        share=share,
        pseudonym=pseudonym,
    )
    if write_scripts_too:
        render_tables(  # the template route's own checks (layout, replicates)
            inputs,
            chosen,
            template_id,
            record_ref=ref,
            chain_head=inputs.chain_head,
            share=share,
            pseudonym=pseudonym,
        )
        unknown = [g for g in graphs if g not in GRAPH_FORMATS]
        if unknown:
            raise PrismExportError(f"graph formats must be among {GRAPH_FORMATS}, not {unknown}")
    texts = caption(inputs, chosen)
    folder = prism_dir_for(directory, platform, prism_dir) if write_scripts_too else None
    directory.mkdir(parents=True, exist_ok=True)
    for table, text in rendered:
        write_bytes(directory / table.csv, text.encode("utf-8"))
    notes: list[str] = []
    info = {
        **bundle_info(inputs, spec, share),
        **texts,
        "mode": "X: a Prism project (.pzfx) written in Prism's documented XML format; it opens "
        "in Prism as it is",
        "layout": "column (and nested by replicate when units have technical replicates)",
        "technical_replicates": "averaged per biological unit by qPilot; never written as n",
        "template_status": "not needed",
        "tables_sha256": tables_digest(rendered),
    }
    width = grouped_width(rendered)
    if grouped_fits(rendered):
        info[INFO_GROUPED_TITLE] = grouped_title(ref, inputs.chain_head)
        if width > OLD_PRISM_SUBCOLUMNS:
            notes.append(
                f"the table of all genes has {width} subcolumns (one per biological unit of the "
                f"largest group): it needs Prism 9 or later (Prism 6 to 8 allow "
                f"{OLD_PRISM_SUBCOLUMNS}); the Column tables open in any version"
            )
    elif width:
        notes.append(
            f"no table of all genes: a group has {width} biological units, more than the "
            f"{MAX_SUBCOLUMNS} subcolumns a Prism grouped table holds"
        )
    bundle = PrismBundle(
        study_id=inputs.study_id,
        record_ref=ref,
        chain_head=inputs.chain_head,
        design_hash=inputs.design_hash,
        template_id=template_id,
        test=TEMPLATES["two_groups_log2"].test,
        tables=[table for table, _ in rendered],
        info=info,
        files={table.csv: table.csv_sha256 for table, _ in rendered},
        mode="xml",
    )
    entries = _decision_entries(store, study_id)
    bundle = bundle.model_copy(
        update={
            "info": {**bundle.info, **write_projects(bundle, inputs, directory, entries=entries)}
        }
    )
    undecided = [c.card_id for c in inputs.choices if c.actor is None]
    if undecided:
        notes.append(
            "not decided yet, so exported at the recommended option (provenance says so): "
            + ", ".join(undecided)
        )
    if not inputs.at_primary:
        notes.append(
            "the export uses choices other than the recommended ones; the caption carries no "
            "numbers because the study's facts describe the recommended analysis"
        )
    written: dict[str, Path] = {}
    send_back: LaunchCommand | None = None
    present = spec.path.is_file()
    if write_scripts_too:
        assert folder is not None
        layout = spec.layout or "column"
        subset = bundle.model_copy(
            update={
                "tables": [t for t in bundle.tables if t.layout == layout and "__" not in t.name]
            }
        )
        written = write_scripts(
            subset, spec.path, directory, platform=platform, prism_dir=folder, graphs=graphs
        )
        if not present:
            notes.append(
                f"the optional scripts need a template made in Prism ({spec.file}); without "
                "one, use the project file"
            )
        send_back = launch_command(join(folder, SEND_BACK_SCRIPT, platform), platform)
    project_path = directory / bundle.info[INFO_PROJECT]
    launch = open_command(str(project_path.resolve()), platform)
    readme = project_readme(bundle, scripts=write_scripts_too, platform=platform, notes=notes)
    write_bytes(directory / README_FILE, readme.encode("utf-8"))
    bundle = finalize(bundle, directory, [*written, README_FILE], inputs)
    provenance = write_provenance(bundle, inputs, directory)
    files = {table.csv: directory / table.csv for table in bundle.tables}
    files |= written | {README_FILE: directory / README_FILE, PROVENANCE_FILE: provenance}
    files[BUNDLE_FILE] = directory / BUNDLE_FILE
    for name in project_names(bundle):
        files[name] = directory / name
    replicates = bundle.info.get(INFO_REPLICATES)
    return ExportResult(
        bundle=bundle,
        out_dir=directory,
        files=files,
        template_present=present,
        launch=launch,
        send_back=send_back,
        notes=notes,
        project=project_path,
        replicates_project=directory / replicates if replicates else None,
        scripts=write_scripts_too,
        open_steps={p: open_steps(project_path.name, p) for p in PLATFORMS},
    )


def _decision_entries(store: StudyStore, study_id: str) -> list[Any]:
    """The study's decision record (for the reasons in the Info sheet); empty when unreadable."""
    try:
        return list(store.entries(study_id))
    except (OSError, ValueError, KeyError):
        return []


def _export_scripts_only(
    store: StudyStore,
    study_id: str,
    out_dir: str | Path,
    *,
    genes: Sequence[str] | None,
    template_id: str,
    share: bool,
    pseudonym: Callable[[str], str] | None,
    platform: Platform | None,
    prism_dir: str | None,
    graphs: Sequence[str],
    rdml_path: str | Path | None,
    record_ref: str | None,
) -> ExportResult:
    """The older bundle (Mode S): CSVs and Prism scripts for a template made by hand."""
    from qpilot.qpcr.export import demo_inputs

    directory = Path(out_dir)
    if directory.exists() and (not directory.is_dir() or any(directory.iterdir())):
        raise PrismExportError(f"the output folder must be new or empty: {directory}")
    platform = platform or host_platform()
    spec = template_spec(template_id)
    inputs = demo_inputs(store, study_id, rdml_path=rdml_path)
    chosen = list(genes) if genes else list(inputs.headline)
    # Everything that can refuse is checked before the first file is written.
    render_tables(
        inputs,
        chosen,
        template_id,
        record_ref=record_ref or study_id,
        chain_head=inputs.chain_head,
        share=share,
        pseudonym=pseudonym,
    )
    texts = caption(inputs, chosen)
    unknown = [g for g in graphs if g not in GRAPH_FORMATS]
    if unknown:
        raise PrismExportError(f"graph formats must be among {GRAPH_FORMATS}, not {unknown}")
    folder = prism_dir_for(directory, platform, prism_dir)
    bundle = build_bundle(
        inputs,
        chosen,
        template_id,
        directory,
        record_ref=record_ref or study_id,
        chain_head=inputs.chain_head,
        design_hash=inputs.design_hash,
        share=share,
        pseudonym=pseudonym,
    )
    present = spec.path.is_file()
    notes = []
    if prism_dir is None and not prism_runs_here():
        notes.append(
            "Prism does not run on this computer, so the scripts name the bundle folder as this "
            "computer sees it: export again with the folder as the Prism computer sees it "
            "(prism_dir / --prism-dir), or copy the bundle there and edit SetPath in the scripts"
        )
    if not present:
        notes.append(
            f"the scripts need a template made in Prism ({spec.file}), which is not here; "
            "without one, export the default bundle (a Prism project that needs no template)"
        )
    undecided = [c.card_id for c in inputs.choices if c.actor is None]
    if undecided:
        notes.append(
            "not decided yet, so exported at the recommended option (provenance says so): "
            + ", ".join(undecided)
        )
    if not inputs.at_primary:
        notes.append(
            "the export uses choices other than the recommended ones; the caption carries no "
            "numbers because the study's facts describe the recommended analysis"
        )
    info = {**bundle.info, **texts, "template_status": "included" if present else "missing"}
    bundle = bundle.model_copy(update={"info": info})
    written = write_scripts(
        bundle, spec.path, directory, platform=platform, prism_dir=folder, graphs=graphs
    )
    launch = launch_command(join(folder, RUN_SCRIPT, platform), platform)
    send_back = launch_command(join(folder, SEND_BACK_SCRIPT, platform), platform)
    readme = readme_text(bundle, template_present=present, launch=launch, send_back=send_back)
    write_bytes(directory / README_FILE, readme.encode("utf-8"))
    bundle = finalize(bundle, directory, [*written, README_FILE], inputs)
    provenance = write_provenance(bundle, inputs, directory)
    files = {table.csv: directory / table.csv for table in bundle.tables}
    files |= written | {README_FILE: directory / README_FILE, PROVENANCE_FILE: provenance}
    files[BUNDLE_FILE] = directory / BUNDLE_FILE
    return ExportResult(
        bundle=bundle,
        out_dir=directory,
        files=files,
        template_present=present,
        launch=launch,
        send_back=send_back,
        notes=notes,
        scripts=True,
    )


def project_digest(store: StudyStore, study_id: str, genes: Sequence[str] | None = None) -> str:
    """The digest of the tables a Prism project of this study would hold (writes nothing).

    Equal digests mean equal numbers in every exported table, whatever the analysis id: a
    draft accepted for one analysis is still current for another with the same digest.
    """
    from qpilot.qpcr.export import demo_inputs

    inputs = demo_inputs(store, study_id, read_only=True)
    chosen = list(genes) if genes else list(inputs.headline)
    rendered = render_project_tables(
        inputs, chosen, record_ref=study_id, chain_head=inputs.chain_head
    )
    return tables_digest(rendered)


def preview(
    store: StudyStore,
    study_id: str,
    genes: Sequence[str] | None = None,
    template_id: str = DEFAULT_TEMPLATE,
    *,
    share: bool = False,
    pseudonym: Callable[[str], str] | None = None,
    rows: int = 5,
) -> dict[str, Any]:
    """What an export *would* write, as JSON-ready data. Writes nothing at all.

    For the MCP tool ``qpcr_prism_preview``: writing needs a person's Send. The bundle has the
    tables' checksums but no ``bundle_sha256``. ``tables`` shows each gene's Column table (the
    one the figure draws); ``project`` lists every table the Prism project would hold.
    """
    from qpilot.qpcr.export import demo_inputs

    spec = template_spec(template_id)
    inputs = demo_inputs(store, study_id, read_only=True)
    chosen = list(genes) if genes else list(inputs.headline)
    rendered = render_project_tables(
        inputs,
        chosen,
        record_ref=study_id,
        chain_head=inputs.chain_head,
        share=share,
        pseudonym=pseudonym,
    )
    info = {
        **bundle_info(inputs, spec, share),
        **caption(inputs, chosen),
        "mode": "X: a Prism project (.pzfx) written in Prism's documented XML format",
        "tables_sha256": tables_digest(rendered),
        INFO_PROJECT: project_file(study_id),
    }
    if grouped_fits(rendered):
        info[INFO_GROUPED_TITLE] = grouped_title(study_id, inputs.chain_head)
    nested = [t for t, _ in rendered if t.layout == "nested"]
    if nested:
        info[INFO_REPLICATES] = replicates_file(study_id)
    bundle = PrismBundle(
        study_id=study_id,
        record_ref=study_id,
        chain_head=inputs.chain_head,
        design_hash=inputs.design_hash,
        template_id=template_id,
        test=TEMPLATES["two_groups_log2"].test,
        tables=[table for table, _ in rendered],
        info=info,
        files={table.csv: table.csv_sha256 for table, _ in rendered},
        mode="xml",
    )
    primary = [(t, text) for t, text in rendered if t.layout == "column" and "__" not in t.name]
    listed = [
        {"name": t.name, "gene": t.gene, "kind": t.layout, "title": t.title, "n_rows": t.n_rows}
        for t, _ in rendered
        if t.layout == "column"
    ]
    if info.get(INFO_GROUPED_TITLE):
        listed.append(
            {
                "name": GROUPED_NAME,
                "gene": "",
                "kind": "grouped",
                "title": info[INFO_GROUPED_TITLE],
                "n_rows": len(primary),
            }
        )
    replicate_tables = [
        {"name": t.name, "gene": t.gene, "kind": "nested", "title": t.title, "n_rows": t.n_rows}
        for t in nested
    ]
    return {
        "writes_nothing": True,
        "bundle": bundle.model_dump(mode="json"),
        "would_write": [
            project_file(study_id),
            *([replicates_file(study_id)] if nested else []),
            *(t.csv for t, _ in rendered),
            README_FILE,
            PROVENANCE_FILE,
            BUNDLE_FILE,
        ],
        "project": {
            "file": project_file(study_id),
            "tables": listed,
            "info_sheet": "qPilot provenance",
            "replicates_file": replicates_file(study_id) if nested else None,
            "replicates_tables": replicate_tables,
            "needs_template": False,
        },
        "template": {
            "id": spec.id,
            "file": spec.file,
            "available": spec.path.is_file(),
            "layout": "column",
            "test": TEMPLATES["two_groups_log2"].test,
            "graph": TEMPLATES["two_groups_log2"].graph,
        },
        "tables": {
            table.gene: {
                "columns": table.columns,
                "n_rows": table.n_rows,
                "head": text.splitlines()[: rows + 1],
            }
            for table, text in primary
        },
        "choices": [choice.as_dict() for choice in inputs.choices],
        "not_affiliated": NOT_AFFILIATED,
    }


def diff_report(
    store: StudyStore,
    study_id: str,
    bundle_dir: str | Path,
    returned: str | Path,
    *,
    proposals: bool = True,
    pseudonym: Callable[[str], str] | None = None,
    rdml_path: str | Path | None = None,
    exclusion_suffix: str | None = None,
    accepted: Sequence[Proposal] = (),
    declined: Sequence[Proposal] = (),
) -> dict[str, Any]:
    """What changed in Prism since export, as diff items and proposals. Writes nothing.

    ``returned`` is what came back from Prism: the project Prism saved (a ``.pzfx`` file, or a
    folder holding it, such as the bundle folder itself) or the folder ``send_back.pzc``
    exported the tables to (CSV). The bundle folder must verify (:func:`verify_provenance`)
    and belong to ``study_id``.
    Proposals are made only when the study's decision chain has not moved since the export
    (otherwise the consequence would be computed at other choices). Each exclusion's
    consequence is computed together with the exclusions already accepted (the study's own and
    ``accepted``, the ``prism.exclusion_reason`` proposals a person accepted since the export),
    and ``combined_consequence`` is what all the proposed exclusions do together. Values a
    person already decided to keep (``declined``: rejected questions and accepted restores)
    are not asked about again and do not count in it.

    Raises:
        PrismExportError: The bundle does not verify or belongs to another study.
        qpilot.prism.roundtrip.RoundTripError: What came back cannot be read safely.
    """
    problems = verify_provenance(bundle_dir)
    if problems:
        raise PrismExportError("the bundle does not verify: " + "; ".join(problems))
    bundle = load_bundle(bundle_dir)
    if bundle.study_id != study_id:
        raise PrismExportError(f"this bundle belongs to study {bundle.study_id}, not {study_id}")
    notes: list[str] = []
    if is_project_path(returned):
        back = read_returned(returned, bundle, bundle_dir)
        items = diff_returned(bundle, back, bundle_dir=bundle_dir)
        notes += back.notes
        source = SOURCE_PROJECT
    else:
        sent = read_sent_back(returned, exclusion_suffix=exclusion_suffix)
        items = diff(bundle, sent, bundle_dir=bundle_dir)
        source = SOURCE_SENT_BACK
    report: dict[str, Any] = {
        "study_id": study_id,
        "record_ref": bundle.record_ref,
        "bundle_sha256": bundle.bundle_sha256,
        "source": source,
        "items": [item.model_dump(mode="json") for item in items],
        "notes": notes,
    }
    if proposals:
        from qpilot.qpcr.export import demo_inputs

        inputs = demo_inputs(store, study_id, rdml_path=rdml_path, read_only=True)
        if inputs.chain_head != bundle.chain_head:
            report["proposals"] = []
            report["combined_consequence"] = None
            report["notes"].append(
                "the study's decisions changed since this export, so no consequences were "
                "computed; send to Prism again and bring back the new project"
            )
        else:
            made, combined = round_trip_proposals(
                items,
                study_id,
                inputs,
                bundle=bundle,
                pseudonym=pseudonym,
                accepted=accepted,
                declined=declined,
            )
            report["proposals"] = [p.model_dump(mode="json") for p in made]
            report["combined_consequence"] = combined
    return report


__all__ = [
    "DEFAULT_TEMPLATE",
    "PLATFORMS",
    "NOT_AFFILIATED",
    "README_FILE",
    "ExportResult",
    "PrismExportError",
    "diff_report",
    "export_study",
    "preview",
    "project_digest",
    "verify_provenance",
]
