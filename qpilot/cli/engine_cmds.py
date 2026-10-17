"""CLI commands owned by Dev 1: fetch-demo, run, app, doctor, explain, validate."""

import argparse
import sys

from qpilot.cli._types import Command
from qpilot.io.datasets import (
    BENCHMARK_TABLES,
    VERMEULEN_BYTES,
    VERMEULEN_COMMIT,
    DatasetIntegrityError,
    default_cache_dir,
    demo_dataset_info,
    fetch_benchmark_tables,
    fetch_vermeulen,
)


def _fetch_demo_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--cache-dir",
        default=None,
        help=f"where to store the dataset (default: {default_cache_dir()})",
    )
    parser.add_argument(
        "--force", action="store_true", help="download again even if a verified copy exists"
    )


def _fetch_demo(args: argparse.Namespace) -> int:
    info = demo_dataset_info()
    try:
        path = fetch_vermeulen(args.cache_dir, force=args.force)
        tables = fetch_benchmark_tables(args.cache_dir, force=args.force)
    except (DatasetIntegrityError, OSError) as err:
        print(f"qpilot fetch-demo: {err}", file=sys.stderr)
        return 1
    print(f"{path}  ({VERMEULEN_BYTES:,} bytes, sha256 OK)")
    print(f"{info['name']}: {info['contents']}")
    print(f"Licence {info['licence']}. Cite: {info['citation']}.")
    print(f"Note: {info['groups']}.")
    print(f"Published benchmark tables for `qpilot validate`: {len(tables)} files, sha256 OK")
    return 0


def _run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "rdml", nargs="?", default=None, help="RDML file (default: the cached demo study)"
    )
    parser.add_argument("--experiment", default="biomarker_set", help="experiment id")
    parser.add_argument(
        "--contrast",
        action="append",
        metavar="GENE",
        help="print one gene's MYCN-high vs rest comparison (repeatable)",
    )
    parser.add_argument(
        "--refs", default=None, help="comma-separated control genes (default: all five)"
    )
    parser.add_argument("--cut", type=float, default=0.15, help="top fraction by MYCN expression")
    parser.add_argument(
        "--undetermined", choices=["drop", "cap"], default="drop", help="empty-well handling"
    )


def _run(args: argparse.Namespace) -> int:
    from qpilot.io.rdml_io import RdmlLoadError
    from qpilot.qpcr.contrast import DEFAULT_RULE, welch_contrast
    from qpilot.qpcr.curves import REFERENCE_TARGETS, CurveAnalysisError, analyse_study
    from qpilot.qpcr.design import GroupSpec, marker_groups
    from qpilot.qpcr.quant import log2_matrix

    if not args.contrast:
        print(
            "qpilot run: the full study output (--out) arrives with study.py; use --contrast GENE",
            file=sys.stderr,
        )
        return 2
    path = args.rdml or str(default_cache_dir() / "data_vermeulen_raw.rdml")
    refs = tuple(r.strip() for r in args.refs.split(",")) if args.refs else REFERENCE_TARGETS
    try:
        matrix = log2_matrix(analyse_study(path, args.experiment))
    except (RdmlLoadError, CurveAnalysisError, OSError) as err:
        print(f"qpilot run: {err}", file=sys.stderr)
        return 1
    high, rest = marker_groups(matrix, GroupSpec(cut=args.cut))  # groups from the primary refs
    print(f"MYCN-high {len(high)} vs rest {len(rest)} (by expression)")
    print(f"Rule: {DEFAULT_RULE.describe()}")
    for gene in args.contrast:
        if gene not in matrix.columns:
            print(f"qpilot run: unknown gene {gene!r}", file=sys.stderr)
            return 1
        c = welch_contrast(matrix, gene, refs, args.undetermined, high, rest)
        print(
            f"{gene}: {c.fc:.2f}x [{c.ci[0]:.2f}-{c.ci[1]:.2f}] p={c.p:.2g} {c.conclusion}"
            f"  (refs: {', '.join(refs)}; n {c.n_hi}/{c.n_lo})"
        )
    return 0


def _validate_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--out",
        default="validation",
        help="directory for validation_table.md and validation.json (default: ./validation)",
    )
    parser.add_argument(
        "--cache-dir",
        default=None,
        help=f"cache for the demo study and published tables (default: {default_cache_dir()})",
    )


def _validate(args: argparse.Namespace) -> int:
    from qpilot.io.rdml_io import RdmlLoadError
    from qpilot.qpcr.curves import CurveAnalysisError, analyse_study
    from qpilot.qpcr.validation import validate, write_report

    try:
        rdml_path = fetch_vermeulen(args.cache_dir)  # verified; downloads only if missing
        tables = fetch_benchmark_tables(args.cache_dir)
        report = validate(analyse_study(rdml_path), tables)
    except (DatasetIntegrityError, RdmlLoadError, CurveAnalysisError, OSError) as err:
        print(f"qpilot validate: {err}", file=sys.stderr)
        return 1
    markdown, data = write_report(report, args.out)
    print(
        f"Benchmark: {len(BENCHMARK_TABLES)} published tables, rdmlpython @ {VERMEULEN_COMMIT[:7]}"
    )
    for line in report.lines():
        print(f"- {line}")
    print(f"Wrote {markdown} and {data}")
    return 0


COMMANDS: list[Command] = [
    (
        "fetch-demo",
        "download the public 64-plate demo study (pinned, SHA-256 verified)",
        _fetch_demo_arguments,
        _fetch_demo,
    ),
    (
        "run",
        "analyse a study (for now: --contrast GENE prints one comparison)",
        _run_arguments,
        _run,
    ),
    (
        "validate",
        "reproduce the RDML consortium's published benchmark on the demo study",
        _validate_arguments,
        _validate,
    ),
]
