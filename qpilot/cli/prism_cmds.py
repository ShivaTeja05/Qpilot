"""CLI commands for exports and the GraphPad Prism bridge: ``export prism | excel``, ``prism``.

``qpilot export prism --study ID [--template two_groups_log2] [--genes ODC1,NTRK1] [--share]
--out DIR`` writes the CSV tables, ``run.pzc``, ``send_back.pzc``, ``qpilot_provenance.json``,
``qpilot_bundle.json`` and a short ``README.txt`` into a new folder. Nothing is written into the
study's workspace.

``qpilot export excel --out FILE.xlsx [--study ID]`` writes one workbook: the results table with
a ``Trace`` column (each gene's top place to look) and a "Where to look" sheet
(:mod:`qpilot.report.excel`). The Prism options do not apply to it and are refused.

``qpilot prism diff --study ID --bundle DIR --sent-back DIR`` prints, as JSON, what changed in
the tables Prism sent back, and the proposals that follow (never accepted here).
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
#: Options of ``export prism`` that ``export excel`` refuses.
PRISM_ONLY = ("template", "genes", "share", "rdml", "platform", "prism_dir", "graphs")


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
        choices=["prism", "excel"],
        help="what to export: prism (a Prism bundle folder) or excel (one .xlsx workbook)",
    )
    parser.add_argument("--study", default=None, help="study id (default: the only study)")
    parser.add_argument(
        "--template",
        default=None,
        choices=sorted(TEMPLATES),
        help=f"prism: the template the tables are made for (default: {DEFAULT_TEMPLATE})",
    )
    parser.add_argument(
        "--genes", default=None, help="comma-separated genes (default: the headline genes)"
    )
    parser.add_argument(
        "--share", action="store_true", help="pseudonymise sample names in the row titles"
    )
    parser.add_argument(
        "--out", required=True, help="prism: a new or empty folder; excel: a new .xlsx file"
    )
    parser.add_argument(
        "--rdml", default=None, help="the study's input file, when qPilot no longer knows it"
    )
    parser.add_argument(
        "--platform",
        choices=["windows", "macos"],
        default=None,
        help="the computer that runs Prism (default: this one)",
    )
    parser.add_argument(
        "--prism-dir",
        default=None,
        help="the bundle folder as the Prism computer sees it (default: --out)",
    )
    parser.add_argument(
        "--graphs",
        default=None,
        help=f"prism: graph exports, pdf, png, pdf,png or none (default {DEFAULT_GRAPHS})",
    )


def _export(args: argparse.Namespace) -> int:
    if args.what == "excel":
        return _export_excel(args)
    from qpilot.core.store import StudyNotFound
    from qpilot.prism import export_study
    from qpilot.qpcr.export import ExportError

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
        )
    except (ExportError, StudyNotFound, OSError) as err:
        print(f"qpilot export prism: {err}", file=sys.stderr)
        return 2
    bundle = result.bundle
    print(f"Wrote {len(result.files)} files to {result.out_dir} (bundle {bundle.bundle_sha256})")
    for name in sorted(result.files):
        print(f"  {name}")
    print(f"Template {bundle.template_id}: {bundle.test}")
    for note in result.notes:
        print(f"Note: {note}")
    print(f"Run in Prism: {result.launch.command_line}")
    print("Not yet checked on a real Prism seat (plan step 0.1); see docs/prism.md.")
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
        print(f"qpilot export excel: {names} only apply to export prism", file=sys.stderr)
        return 2
    store, study_id = _store_and_study(args)
    try:
        info = export_excel(store, study_id, args.out)
    except (ExcelError, StudyNotFound, OSError) as err:
        print(f"qpilot export excel: {err}", file=sys.stderr)
        return 2
    print(
        f"Wrote {info.path}: {info.n_results} results and {info.n_places} places to look "
        "(sheets Results, Where to look, About)"
    )
    if not info.traced:
        print(f"Note: Trace did not run ({info.note or 'no result could be traced'}).")
    return 0


def _prism_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("action", choices=["diff", "verify"])
    parser.add_argument("--study", default=None, help="study id (diff; default: the only study)")
    parser.add_argument("--bundle", required=True, help="the folder `qpilot export prism` wrote")
    parser.add_argument(
        "--sent-back", default=None, help="the folder send_back.pzc exported the tables to"
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
    if not args.sent_back:
        print("qpilot prism diff: give --sent-back <folder>", file=sys.stderr)
        return 2
    store, study_id = _store_and_study(args)
    try:
        report = diff_report(
            store,
            study_id,
            args.bundle,
            args.sent_back,
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
        "export a study: `export prism` writes tables and a Prism script; `export excel` a "
        "workbook with Trace's places to look",
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
