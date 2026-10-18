"""The GraphPad Prism bridge (Mode S): tables Prism cannot misread, with provenance.

Scientists move qPCR results into Prism for statistics and figures. The usual route (ΔΔCq in a
spreadsheet, 2^-ΔΔCq pasted into Prism, a t test on the linear scale) changes conclusions that
the engine's own analysis makes (``docs/studio-measured.md``). This package hands Prism log2
relative quantities per biological unit, never technical replicates as n, with the record ref
in every table title and ``qpilot_provenance.json`` beside the project, and later detects what
a scientist changed in Prism.

Mode S only: qPilot writes plain CSV tables and Prism scripts (``.pzc``); the scientist's own
Prism does all reading and writing of Prism files. qPilot never writes or parses ``.prism`` or
``.pzfx``. Mode X (filling a ``.pzfx`` data portion directly) is not built: GraphPad's terms
restrict letting third parties parse those files, and the licence review (plan step 0.5) has
not answered yet (``docs/prism.md``).

* :mod:`qpilot.prism.tables`: one CSV per gene, column or nested layout (step 2.1);
* :mod:`qpilot.prism.script`: ``run.pzc`` and ``send_back.pzc`` (step 2.2);
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

from qpilot.prism.provenance import (
    BUNDLE_FILE,
    PROVENANCE_FILE,
    caption,
    finalize,
    load_bundle,
    verify_provenance,
    write_provenance,
)
from qpilot.prism.roundtrip import diff, read_sent_back, round_trip_proposals
from qpilot.prism.script import (
    GRAPH_FORMATS,
    RUN_SCRIPT,
    SEND_BACK_SCRIPT,
    SENT_BACK_DIR,
    LaunchCommand,
    Platform,
    host_platform,
    join,
    launch_command,
    prism_dir_for,
    prism_runs_here,
    readme_text,
    write_scripts,
)
from qpilot.prism.tables import (
    NOT_AFFILIATED,
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
    """What :func:`export_study` wrote."""

    bundle: PrismBundle
    out_dir: Path
    files: dict[str, Path]
    template_present: bool
    launch: LaunchCommand
    send_back: LaunchCommand
    notes: list[str] = field(default_factory=list)


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
) -> ExportResult:
    """Write the bundle for a study: CSVs, ``run.pzc``, ``send_back.pzc``, README, provenance.

    Writes only into ``out_dir``, which must be new or empty; the bundle sha256 is stored there
    (in ``qpilot_bundle.json``, which also holds the sha256 of ``qpilot_provenance.json``), not
    in the study's workspace.
    When the template file has not been made in Prism yet, everything else is still written and
    the notes (and ``README.txt``) say what to build.

    Raises:
        PrismExportError: The folder is not empty, or the export cannot be built as asked.
        qpilot.qpcr.export.ExportError: The study cannot be rebuilt for export.
    """
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
            f"template {spec.file} has not been made in Prism yet: build it as described in "
            "qpilot/prism/templates/README.md and put it into the bundle folder"
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
    )


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
    tables' checksums but no ``bundle_sha256`` (the scripts depend on where they are written).
    """
    from qpilot.qpcr.export import demo_inputs

    spec = template_spec(template_id)
    inputs = demo_inputs(store, study_id, read_only=True)
    chosen = list(genes) if genes else list(inputs.headline)
    rendered = render_tables(
        inputs,
        chosen,
        template_id,
        record_ref=study_id,
        chain_head=inputs.chain_head,
        share=share,
        pseudonym=pseudonym,
    )
    bundle = PrismBundle(
        study_id=study_id,
        record_ref=study_id,
        chain_head=inputs.chain_head,
        design_hash=inputs.design_hash,
        template_id=template_id,
        test=spec.test,
        tables=[table for table, _ in rendered],
        info={**bundle_info(inputs, spec, share), **caption(inputs, chosen)},
        files={table.csv: table.csv_sha256 for table, _ in rendered},
    )
    return {
        "writes_nothing": True,
        "bundle": bundle.model_dump(mode="json"),
        "would_write": [
            *(t.csv for t, _ in rendered),
            RUN_SCRIPT,
            SEND_BACK_SCRIPT,
            README_FILE,
            PROVENANCE_FILE,
            BUNDLE_FILE,
            f"{SENT_BACK_DIR}/",
        ],
        "template": {
            "id": spec.id,
            "file": spec.file,
            "available": spec.path.is_file(),
            "layout": spec.layout,
            "test": spec.test,
            "graph": spec.graph,
        },
        "tables": {
            table.gene: {
                "columns": table.columns,
                "n_rows": table.n_rows,
                "head": text.splitlines()[: rows + 1],
            }
            for table, text in rendered
        },
        "choices": [choice.as_dict() for choice in inputs.choices],
        "not_affiliated": NOT_AFFILIATED,
    }


def diff_report(
    store: StudyStore,
    study_id: str,
    bundle_dir: str | Path,
    sent_back_dir: str | Path,
    *,
    proposals: bool = True,
    pseudonym: Callable[[str], str] | None = None,
    rdml_path: str | Path | None = None,
    exclusion_suffix: str | None = None,
    accepted: Sequence[Proposal] = (),
    declined: Sequence[Proposal] = (),
) -> dict[str, Any]:
    """What changed in Prism since export, as diff items and proposals. Writes nothing.

    The bundle folder must verify (:func:`verify_provenance`) and belong to ``study_id``.
    Proposals are made only when the study's decision chain has not moved since the export
    (otherwise the consequence would be computed at other choices). Each exclusion's
    consequence is computed together with the exclusions already accepted (the study's own and
    ``accepted``, the ``prism.exclusion_reason`` proposals a person accepted since the export),
    and ``combined_consequence`` is what all the proposed exclusions do together. Values a
    person already decided to keep (``declined``: rejected questions and accepted restores)
    are not asked about again and do not count in it.

    Raises:
        PrismExportError: The bundle does not verify or belongs to another study.
        qpilot.prism.roundtrip.RoundTripError: The sent-back folder cannot be read safely.
    """
    problems = verify_provenance(bundle_dir)
    if problems:
        raise PrismExportError("the bundle does not verify: " + "; ".join(problems))
    bundle = load_bundle(bundle_dir)
    if bundle.study_id != study_id:
        raise PrismExportError(f"this bundle belongs to study {bundle.study_id}, not {study_id}")
    sent = read_sent_back(sent_back_dir, exclusion_suffix=exclusion_suffix)
    items = diff(bundle, sent, bundle_dir=bundle_dir)
    report: dict[str, Any] = {
        "study_id": study_id,
        "record_ref": bundle.record_ref,
        "bundle_sha256": bundle.bundle_sha256,
        "items": [item.model_dump(mode="json") for item in items],
        "notes": [],
    }
    if proposals:
        from qpilot.qpcr.export import demo_inputs

        inputs = demo_inputs(store, study_id, rdml_path=rdml_path, read_only=True)
        if inputs.chain_head != bundle.chain_head:
            report["proposals"] = []
            report["combined_consequence"] = None
            report["notes"].append(
                "the study's decisions changed since this export, so no consequences were "
                "computed; export again and send the tables back from the new projects"
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
    "NOT_AFFILIATED",
    "README_FILE",
    "ExportResult",
    "PrismExportError",
    "diff_report",
    "export_study",
    "preview",
    "verify_provenance",
]
