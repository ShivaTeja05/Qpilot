"""CLI commands for exports and the GraphPad Prism bridge: ``export ...``, ``prism``.

``qpilot export prism --study ID [--genes ODC1,NTRK1] [--share] --out DIR`` writes a Prism
project (``qpilot_<study>.pzfx``: the Info sheet with qPilot's provenance, one Column table per
gene, a Grouped table of all genes; Nested tables in ``qpilot_<study>_replicates.pzfx`` when
units have technical replicates), the same tables as CSV, ``qpilot_provenance.json``,
``qpilot_bundle.json`` and a ``README.txt`` with plain steps for Windows and macOS into a new
folder. It opens in Prism as it is: no template, no script. ``--scripts`` adds the optional
Prism scripts (``run.pzc``, ``send_back.pzc``) for a hand-made ``--template``;
``--scripts-only`` writes the older bundle without a project. Nothing is written into the
study's workspace.

``qpilot export xlsx --out FILE.xlsx [--study ID]`` (or ``export excel``) writes one workbook of
the study's numbers as numbers: results per gene (with a ``Trace`` column naming each gene's
top place to look), per biological unit, per well, Trace's "Where to look", the decisions, the
settings, the Methods and an About sheet (:mod:`qpilot.report.excel`). ``export csv --out
FILE.zip`` writes the same tables as CSV files; ``export figures --out FILE.zip [--genes A,B]
[--basis recommended]`` a figure per gene (SVG, 300-dpi PNG, source CSV, caption) and a panel;
``export supplement --out FILE.zip [--genes A,B]`` the journal supplement (workbook, tables,
MIQE checklist, figures, the RDML with qPilot's results, the Analysis Record). Every table holds
the analysis as decided on the Decision Cards, and the recommended one too when it differs.
``--format`` names the same thing as the first argument. The Prism options do not apply to
these and are refused.

``qpilot prism diff --study ID --bundle DIR [--returned FILE_OR_DIR]`` prints, as JSON, what
changed in Prism (the project Prism saved: a ``.pzfx`` file or the folder holding it, by default
the bundle folder; or ``send_back.pzc``'s ``--sent-back`` folder), and the proposals that follow
(never accepted here).
``qpilot prism verify --bundle DIR`` checks a bundle folder's provenance and checksums.

Works with GraphPad Prism. Not affiliated with or endorsed by GraphPad Software or Dotmatics.
"""

from __future__ import annotations

import argparse
import json
import sys

from qpilot.cli._types import Command

DEFAULT_TEMPLATE = "two_groups_log2"
DEFAULT_GRAPHS = "pdf"
#: Options of ``export prism`` that the table exports refuse (``--genes`` is also for figures).
PRISM_ONLY = (
    "template",
    "genes",
    "share",
    "rdml",
    "platform",
    "prism_dir",
    "graphs",
    "scripts",
    "scripts_only",
)
TABLE_EXPORTS = ("excel", "xlsx", "csv", "figures", "supplement")
WITH_GENES = ("figures", "supplement")


def _store_and_study(args: argparse.Namespace):
    """The store and the study: ``--study``, or the only study in the store."""
    from qpilot.core.store import StudyStore

    store = StudyStore()
    if args.study:
        return store, args.study
    studies = store.list_studies()
    if len(studies) != 1:
        raise SystemExit("qpilot: give --study <id> (see `qpilot run` or the app for the id)")
    return store, studies[0]


def _export_arguments(parser: argparse.ArgumentParser) -> None:
    from qpilot.prism.tables import TEMPLATES

    parser.add_argument(
        "what",
        nargs="?",
        choices=["prism", *TABLE_EXPORTS],
        help="what to export: prism (a Prism bundle folder), xlsx (or excel: one workbook), "
        "csv (the tables, zipped), figures (a figure per gene, zipped) or supplement (a "
        "journal supplement zip)",
    )
    parser.add_argument(
        "--format",
        dest="format",
        default=None,
        choices=["prism", *TABLE_EXPORTS],
        help="the same as the first argument",
    )
    parser.add_argument(
        "--basis",
        default=None,
        choices=["as_decided", "recommended"],
        help="figures: the analysis as decided on the Decision Cards (default) or recommended",
    )
    parser.add_argument("--study", default=None, help="study id (default: the only study)")
    parser.add_argument(
        "--template",
        default=None,
        choices=sorted(TEMPLATES),
        help=f"prism: the template the optional scripts use (default: {DEFAULT_TEMPLATE})",
    )
    parser.add_argument(
        "--scripts",
        action="store_true",
        help="prism: also write the optional Prism scripts (run.pzc, send_back.pzc) for a "
        "hand-made template",
    )
    parser.add_argument(
        "--scripts-only",
        action="store_true",
        help="prism: the older bundle (CSV tables and Prism scripts for a template), no project",
    )
    parser.add_argument(
        "--genes", default=None, help="comma-separated genes (default: the headline genes)"
    )
    parser.add_argument(
        "--share", action="store_true", help="pseudonymise sample names in the row titles"
    )
    parser.add_argument(
        "--out",
        required=True,
        help="prism: a new or empty folder; xlsx: a new .xlsx file; csv, figures, supplement: "
        "a new .zip file",
    )
    parser.add_argument(
        "--rdml", default=None, help="the study's input file, when qPilot no longer knows it"
    )
    parser.add_argument(
        "--platform",
        choices=["windows", "macos"],
        default=None,
        help="the computer that runs Prism (default: this one): the README's steps start there",
    )
    parser.add_argument(
        "--prism-dir",
        default=None,
        help="scripts: the bundle folder as the Prism computer sees it (default: --out)",
    )
    parser.add_argument(
        "--graphs",
        default=None,
        help=f"scripts: graph exports, pdf, png, pdf,png or none (default {DEFAULT_GRAPHS})",
    )


def _export(args: argparse.Namespace) -> int:
    if args.what and args.format and args.what != args.format:
        print(f"qpilot export: {args.what} or {args.format}? Give one.", file=sys.stderr)
        return 2
    args.what = args.what or args.format
    if args.what is None:
        print("qpilot export: say what to export: " + ", ".join(["prism", *TABLE_EXPORTS]),
              file=sys.stderr)  # fmt: skip
        return 2
    if args.basis and args.what != "figures":
        print("qpilot export: --basis only applies to export figures", file=sys.stderr)
        return 2
    if args.what in ("excel", "xlsx"):
        return _export_excel(args)
    if args.what in TABLE_EXPORTS:
        return _export_tables(args)
    from qpilot.core.store import StudyNotFound
    from qpilot.prism import export_study
    from qpilot.qpcr.export import ExportError

    scripted = args.scripts or args.scripts_only
    if not scripted:
        given = [f for f, v in (("--graphs", args.graphs), ("--prism-dir", args.prism_dir)) if v]
        if given:
            print(
                f"qpilot export prism: {', '.join(given)} only apply to the Prism scripts "
                "(add --scripts)",
                file=sys.stderr,
            )
            return 2
    if args.scripts and args.scripts_only:
        print("qpilot export prism: give --scripts or --scripts-only, not both", file=sys.stderr)
        return 2
    store, study_id = _store_and_study(args)
    genes = [g.strip() for g in args.genes.split(",") if g.strip()] if args.genes else None
    chosen = args.graphs or DEFAULT_GRAPHS
    graphs = [] if chosen == "none" else [g.strip() for g in chosen.split(",")]
    try:
        result = export_study(
            store,
            study_id,
            args.out,
            genes=genes,
            template_id=args.template or DEFAULT_TEMPLATE,
            share=args.share,
            platform=args.platform,
            prism_dir=args.prism_dir,
            graphs=graphs,
            rdml_path=args.rdml,
            project=not args.scripts_only,
            scripts=True if args.scripts else None,
        )
    except (ExportError, StudyNotFound, OSError) as err:
        print(f"qpilot export prism: {err}", file=sys.stderr)
        return 2
    bundle = result.bundle
    print(f"Wrote {len(result.files)} files to {result.out_dir} (bundle {bundle.bundle_sha256})")
    for name in sorted(result.files):
        print(f"  {name}")
    print(f"Test: {bundle.test}")
    for note in result.notes:
        print(f"Note: {note}")
    if result.project is not None:
        print(f"Open in Prism: double-click {result.project.name} (or File > Open in Prism).")
        print("README.txt says how to add the t test and the graph, and how to bring changes back.")
    else:
        print(f"Template {bundle.template_id}. Run in Prism: {result.launch.command_line}")
    print("Not yet opened in a real Prism by the qPilot team; see docs/prism.md.")
    return 0


def _export_excel(args: argparse.Namespace) -> int:
    """``export excel``: one workbook; the Prism-only options are refused, not ignored."""
    from qpilot.core.store import StudyNotFound
    from qpilot.report.excel import ExcelError, export_excel

    given = [
        "--" + name.replace("_", "-")
        for name in PRISM_ONLY
        if getattr(args, name, None) not in (None, False)
    ]
    if given:
        names = ", ".join(given)
        print(f"qpilot export {args.what}: {names} only apply to export prism", file=sys.stderr)
        return 2
    store, study_id = _store_and_study(args)
    try:
        info = export_excel(store, study_id, args.out)
    except (ExcelError, StudyNotFound, OSError) as err:
        print(f"qpilot export {args.what}: {err}", file=sys.stderr)
        return 2
    print(
        f"Wrote {info.path}: {info.n_results} results and {info.n_places} places to look "
        f"(sheets {', '.join(info.sheets)})"
    )
    if not info.traced:
        print(f"Note: Trace did not run ({info.note or 'no result could be traced'}).")
    return 0


def _export_tables(args: argparse.Namespace) -> int:
    """``export csv | figures | supplement``: one zip; the Prism-only options are refused."""
    from qpilot.core.record import RecordError
    from qpilot.core.store import StudyNotFound
    from qpilot.report.bundle import BundleError, csv_zip, figures_zip, write_supplement
    from qpilot.report.excel import ExcelError, new_file, write_atomic
    from qpilot.report.tables import study_tables

    what = args.what
    refused = [n for n in PRISM_ONLY if not (n == "genes" and what in WITH_GENES)]
    given = [
        "--" + n.replace("_", "-") for n in refused if getattr(args, n, None) not in (None, False)
    ]
    if given:
        print(f"qpilot export {what}: {', '.join(given)} only apply to export prism",
              file=sys.stderr)  # fmt: skip
        return 2
    genes = [g.strip() for g in args.genes.split(",") if g.strip()] if args.genes else None
    store, study_id = _store_and_study(args)
    try:
        if what == "supplement":
            info = write_supplement(store, study_id, args.out, genes=genes)
            print(f"Wrote {info.path}: {info.n_files} files (journal supplement)")
            print(
                f"Analysis Record {info.record_id}; check it with `qpilot verify` after unzipping"
            )
            print(info.rdml)
            print(f"Figures: {', '.join(info.genes) or 'none'}")
            for note in info.notes:
                print(f"Note: {note}")
            return 0
        out = new_file(args.out, ".zip", f"{what} file")
        tables = study_tables(store, study_id)
        if what == "csv":
            write_atomic(out, csv_zip(tables))
            print(f"Wrote {out}: the tables as CSV ({', '.join(tables.bases)})")
        else:
            data, figures = figures_zip(tables, genes, args.basis or "as_decided")
            write_atomic(out, data)
            print(f"Wrote {out}: figures of {', '.join(figures.genes)} (SVG, PNG, source CSV)")
            for gene, why in figures.skipped:
                print(f"Not drawn: {gene} ({why})")
    except (BundleError, ExcelError, RecordError, StudyNotFound, OSError, ValueError) as err:
        print(f"qpilot export {what}: {err}", file=sys.stderr)
        return 2
    return 0


def _prism_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("action", choices=["diff", "verify"])
    parser.add_argument("--study", default=None, help="study id (diff; default: the only study)")
    parser.add_argument("--bundle", required=True, help="the folder `qpilot export prism` wrote")
    parser.add_argument(
        "--returned",
        default=None,
        help="diff: the project Prism saved (.pzfx) or the folder holding it (default: --bundle)",
    )
    parser.add_argument(
        "--sent-back", default=None, help="diff: the folder send_back.pzc exported the tables to"
    )
    parser.add_argument(
        "--rdml", default=None, help="the study's input file, when qPilot no longer knows it"
    )
    parser.add_argument("--items-only", action="store_true", help="diff items only, no proposals")


def _prism(args: argparse.Namespace) -> int:
    from qpilot.core.store import StudyNotFound
    from qpilot.prism import diff_report, verify_provenance
    from qpilot.prism.roundtrip import RoundTripError
    from qpilot.qpcr.export import ExportError

    if args.action == "verify":
        problems = verify_provenance(args.bundle)
        print("\n".join(problems) if problems else "OK: provenance and checksums verify")
        return 1 if problems else 0
    if args.returned and args.sent_back:
        print("qpilot prism diff: give --returned or --sent-back, not both", file=sys.stderr)
        return 2
    returned = args.returned or args.sent_back or args.bundle
    store, study_id = _store_and_study(args)
    try:
        report = diff_report(
            store,
            study_id,
            args.bundle,
            returned,
            proposals=not args.items_only,
            rdml_path=args.rdml,
        )
    except (ExportError, RoundTripError, StudyNotFound, OSError) as err:
        print(f"qpilot prism diff: {err}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


COMMANDS: list[Command] = [
    (
        "export",
        "export a study: `export prism` writes a Prism project (.pzfx) that opens as it is; "
        "`export xlsx` (or excel), `csv`, `figures` or `supplement` the study's numbers, its "
        "figures or a journal supplement",
        _export_arguments,
        _export,
    ),
    (
        "prism",
        "after Prism: `prism diff` shows what changed; `prism verify` checks a bundle",
        _prism_arguments,
        _prism,
    ),
]
