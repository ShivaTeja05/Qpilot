"""CLI commands owned by Dev 1: fetch-demo, run, app, doctor, explain, validate."""

import argparse
import sys
from pathlib import Path

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
        "--out",
        default=None,
        help="write results.json, cards.json, facts.json and grid.csv to this directory",
    )
    parser.add_argument(
        "--contrast",
        action="append",
        metavar="GENE",
        help="only print this gene's MYCN-high vs rest comparison (repeatable)",
    )
    parser.add_argument(
        "--refs",
        default=None,
        help="comma-separated control genes: the normaliser with --contrast, else the candidates",
    )
    parser.add_argument("--cut", type=float, default=0.15, help="top fraction by MYCN expression")
    parser.add_argument(
        "--undetermined",
        choices=["drop", "cap"],
        default="drop",
        help="empty-well handling (with --contrast)",
    )
    parser.add_argument(
        "--design",
        default=None,
        metavar="STUDY_YAML",
        help="run a confirmed study design (groups, control genes, replicates) from a study.yaml",
    )
    parser.add_argument(
        "--samples",
        default=None,
        metavar="SHEET_CSV",
        help="sample sheet for --design (CSV: sample, group[, biological_unit, role, quantity])",
    )


def _design_conflicts(args: argparse.Namespace) -> list[str]:
    """Options that the design file sets, given on the command line as well."""
    given = {
        "--contrast": bool(args.contrast),
        "--refs": bool(args.refs),
        "--experiment": args.experiment != "biomarker_set",
        "--cut": args.cut != 0.15,
    }
    return [option for option, used in given.items() if used]


def _run(args: argparse.Namespace) -> int:
    from qpilot.io.rdml_io import RdmlLoadError
    from qpilot.qpcr.contrast import DEFAULT_RULE, welch_contrast
    from qpilot.qpcr.curves import REFERENCE_TARGETS, CurveAnalysisError, analyse_study
    from qpilot.qpcr.design import GroupSpec, marker_groups
    from qpilot.qpcr.quant import log2_matrix

    if args.samples and not args.design:
        print("qpilot run: --samples needs --design", file=sys.stderr)
        return 1
    if args.design and _design_conflicts(args):
        options = ", ".join(_design_conflicts(args))
        print(f"qpilot run: with --design, set {options} in the design file", file=sys.stderr)
        return 1
    if not args.contrast:
        return _run_study(args)
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


def _run_study(args: argparse.Namespace) -> int:
    from qpilot.core.decisions import DecisionError
    from qpilot.io.rdml_io import RdmlLoadError
    from qpilot.qpcr.curves import CurveAnalysisError
    from qpilot.qpcr.quant import QuantError
    from qpilot.qpcr.study import StudySettings, run_study, write_outputs

    settings = StudySettings(experiment_id=args.experiment, cut=args.cut)
    if args.refs:
        candidates = tuple(r.strip() for r in args.refs.split(","))
        settings = StudySettings(experiment_id=args.experiment, cut=args.cut, candidates=candidates)
    path = args.rdml or str(default_cache_dir() / "data_vermeulen_raw.rdml")
    try:
        if args.design:
            from qpilot.qpcr.designs import load_design

            settings = StudySettings.from_design(load_design(args.design, args.samples))
        result, cards, grid = run_study(path, settings)
    except (
        RdmlLoadError,
        CurveAnalysisError,
        QuantError,
        DecisionError,
        ValueError,
        OSError,
    ) as err:
        print(f"qpilot run: {err}", file=sys.stderr)
        return 1
    _print_study(result, cards, settings)
    if args.out:
        paths = write_outputs(result, cards, grid, args.out)
        print(f"Wrote {', '.join(paths)} to {args.out}")
    return 0


def _print_study(result, cards, settings) -> None:
    n_items = len(result.contrasts)
    n_cells = next(iter(result.robustness.values())).n_cells if result.robustness else 0
    print(
        f"{result.n_plates} plates, {result.n_reactions:,} reactions, {result.n_samples} samples "
        f"(study {result.study_id})"
    )
    if settings.groups_mode:  # groups from the design: units per group, no cut-off
        print(f"{result.design.group_var}: {result.design.n_hi} vs {result.design.n_lo} "
              f"biological units ({result.design.note})")  # fmt: skip
    else:
        print(f"{settings.marker_label}-high {result.design.n_hi} vs rest {result.design.n_lo} "
              "(by expression)")  # fmt: skip
    stable = [g for g, m in result.genorm.M_initial.items() if m < result.genorm.cutoff_M]
    print(
        f"Control genes, most stable first: {', '.join(result.genorm.order)}; "
        f"recommended: {', '.join(result.genorm.recommended)}; "
        f"below geNorm M {result.genorm.cutoff_M:g}: {', '.join(stable) or 'none'}"
    )
    print(f"Rule: {settings.rule.describe()}")
    for gene in settings.headline:
        if gene not in result.contrasts:
            continue
        c, r = result.contrasts[gene], result.robustness[gene]
        level = result.confidence[gene].level if gene in result.confidence else "not graded"
        print(
            f"{gene}: {c.fc:.2f}x [{c.ci[0]:.2f}-{c.ci[1]:.2f}] {c.conclusion}; "
            f"holds in {r.holds * 100:.0f} % of {n_cells} analyses; confidence {level}"
        )
    print("Decision cards, most impact first:")
    for card in cards:
        flipped = card.impact["n_genes_flipped"]
        if card.status == "auto_decided":
            what = f"changes no conclusion; decided automatically ({card.decision})"
        else:
            what = f"changes {flipped} of {n_items} conclusions; needs a human"
        print(f"  {card.rank}. {card.kind}: {what}")


def _explain_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("template", nargs="?", help="template key, e.g. refset_v1 (omit to list)")
    parser.add_argument("--gene", default=None, help="gene, for confidence_v1")
    parser.add_argument(
        "--results",
        default=None,
        help="a results.json to read facts from (default: analyse the cached demo study)",
    )
    parser.add_argument(
        "--tokens", action="store_true", help="print the {{fact_id}} token text instead"
    )


def _explain(args: argparse.Namespace) -> int:
    from qpilot.explain.templates import TEMPLATES, TemplateError, render_template
    from qpilot.schemas import StudyResult

    if not args.template:
        print("\n".join(sorted(TEMPLATES)))
        return 0
    try:
        if args.results:
            facts = StudyResult.model_validate_json(Path(args.results).read_text()).facts
        else:
            from qpilot.qpcr.study import run_study

            facts = run_study(default_cache_dir() / "data_vermeulen_raw.rdml")[0].facts
        rendered = render_template(args.template, facts, gene=args.gene)
    except (KeyError, TemplateError, ValueError, OSError) as err:
        print(f"qpilot explain: {err}", file=sys.stderr)
        return 1
    print(rendered.tokens if args.tokens else rendered.plain)
    return 0


def _app_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--port", type=int, default=None, help="port (default: first free from 7860)"
    )
    parser.add_argument(
        "--fresh-demo",
        action="store_true",
        help="move the demo study's earlier decisions aside (kept, never deleted) and start clean",
    )


def _app(args: argparse.Namespace) -> int:
    from qpilot.app import main as app_main  # imports Gradio only here, telemetry already off

    app_main(port=args.port, fresh_demo=args.fresh_demo)
    return 0


def _doctor_arguments(parser: argparse.ArgumentParser) -> None:
    pass


def _doctor(args: argparse.Namespace) -> int:
    """Print what qPilot will use and whether anything can leave this machine; never downloads."""
    import platform

    from qpilot import __version__
    from qpilot.ai.config import ModelConfig
    from qpilot.core.store import default_studies_dir
    from qpilot.io.datasets import (
        VERMEULEN_FILENAME,
        VERMEULEN_SHA256,
        cached_benchmark_tables,
        verify_file,
    )

    print(f"qpilot {__version__} · Python {platform.python_version()} · {platform.system()}")
    print(f"LinRegPCR: rdmlpython vendored @ {VERMEULEN_COMMIT[:7]}")
    demo = default_cache_dir() / VERMEULEN_FILENAME
    try:
        verify_file(demo, VERMEULEN_SHA256, VERMEULEN_BYTES)
        cached = True
        print(f"demo dataset: {demo} (sha256 OK)")
    except (OSError, DatasetIntegrityError) as err:
        cached = False
        print(f"demo dataset: not ready ({err}); run `qpilot fetch-demo`")
    tables = "cached" if cached_benchmark_tables() else "not cached (run `qpilot fetch-demo`)"
    print(f"benchmark tables: {tables}")
    print(f"studies: {default_studies_dir()}")
    try:
        config = ModelConfig.from_env()
    except ValueError as err:
        print(f"provider: INVALID ({err})")
        print("outbound: unknown until QPILOT_MODEL_PROVIDER is fixed")
        return 1
    described = config.describe()
    print(f"provider: {described['provider']}")
    print(f"QPILOT_API_KEY: {described['api_key']}")
    print("app: 127.0.0.1 only, never shared, Gradio telemetry forced off")
    if config.provider == "none":
        print("outbound: none")
    else:
        target = config.endpoint or "https://api.anthropic.com"
        print(f"outbound: {target} (only when you use the model; provider {config.provider})")
    print("(in the app you can pick a model; the API key is only sent where it was configured)")
    if not cached:
        print("(`qpilot fetch-demo` downloads the pinned demo study once; nothing else does)")
    print("OK")
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
        "analyse a study: results, robustness, confidence and Decision Cards",
        _run_arguments,
        _run,
    ),
    (
        "app",
        "open the one-page app on 127.0.0.1 (telemetry off, never shared)",
        _app_arguments,
        _app,
    ),
    (
        "doctor",
        "show versions, the dataset, the model provider and what can leave this machine",
        _doctor_arguments,
        _doctor,
    ),
    (
        "explain",
        "print one explanation template rendered from a study's facts",
        _explain_arguments,
        _explain,
    ),
    (
        "validate",
        "reproduce the RDML consortium's published benchmark on the demo study",
        _validate_arguments,
        _validate,
    ),
]
