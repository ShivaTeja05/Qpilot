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
    parser.add_argument(
        "--efficiency",
        default=None,
        metavar="MODELS",
        help="also test efficiency models: 'all', or a comma-separated list of per_well, "
        "amplicon_mean, assumed_2, standard_curve (LinRegPCR's mean efficiency stays the "
        "analysis in use; models that do not apply to the study are named and left out)",
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
    if args.efficiency and args.contrast:
        print("qpilot run: --efficiency tests a choice across the whole study; it cannot be "
              "combined with --contrast", file=sys.stderr)  # fmt: skip
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


def _efficiency_models(text: str) -> tuple[str, ...]:
    """``--efficiency``: the efficiency models to test, LinRegPCR's mean efficiency first."""
    from qpilot.qpcr.axes import efficiency as eff_axis

    if text.strip().lower() == "all":
        return eff_axis.OPTIONS
    named = [t.strip() for t in text.split(",") if t.strip()]
    unknown = [n for n in named if n not in eff_axis.OPTIONS]
    if unknown or not named:
        known = ", ".join(o for o in eff_axis.OPTIONS if o != eff_axis.PRIMARY)
        raise ValueError(f"unknown efficiency model(s) {unknown or [text]}; use 'all' or {known}")
    return (eff_axis.PRIMARY, *dict.fromkeys(n for n in named if n != eff_axis.PRIMARY))


def _with_efficiency(args: argparse.Namespace, settings):
    """The settings with the efficiency models as one more choice of the design.

    The models live in the design (``axes``), so the study id names them: a study that tests
    them is never mistaken for the one that does not. Without ``--design`` the design is the
    demo analysis with this command's experiment, cut-off and control genes.
    """
    from qpilot.qpcr.designs import vermeulen_design
    from qpilot.qpcr.study import StudySettings

    models = _efficiency_models(args.efficiency)
    if len(models) < 2:
        raise ValueError("--efficiency names no model besides LinRegPCR's mean efficiency")
    design = settings.design
    if design is None:
        base = vermeulen_design()
        split = base.marker_split.model_copy(update={"cut": settings.cut})
        design = base.model_copy(
            update={
                "experiment_id": settings.experiment_id,
                "marker_split": split,
                "reference_candidates": settings.candidates,
            }
        )
    axes = {**(design.axes or {}), "efficiency": models}
    return StudySettings.from_design(design.model_copy(update={"axes": axes}))


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
        if args.efficiency:
            settings = _with_efficiency(args, settings)
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


def _print_efficiency(result) -> None:
    """One line on the efficiency models when they were tested (facts only)."""
    facts = result.facts
    status = facts.get("f_axis_efficiency")
    if status is None:
        return
    words = {
        "swept": "tested as one more choice of the grid",
        "screened_out": "tested alone first: none flips a conclusion or moves a fold change "
        "enough to matter, so the grid holds LinRegPCR's mean efficiency",
        "not_applicable": "none of the requested models applies to this study",
    }
    print(f"Efficiency models: {words.get(str(status.value), str(status.value))}")
    prefix = "f_axis_efficiency_unavailable_"
    for fid, fact in sorted(facts.items()):
        if fid.startswith(prefix):
            print(f"  {fid[len(prefix) :]} not applicable: {fact.value}")


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
    rule = settings.rule.describe()
    found = result.comparisons
    if found is not None and len(found.comparisons) > 1 and found.correction != "none":
        rule = rule.replace("only if p <", "only if the corrected p <")
    print(f"Rule: {rule}")
    _print_efficiency(result)
    for gene in settings.headline:
        if gene not in result.contrasts:
            continue
        c, r = result.contrasts[gene], result.robustness[gene]
        level = result.confidence[gene].level if gene in result.confidence else "not graded"
        print(
            f"{gene}: {c.fc:.2f}x [{c.ci[0]:.2f}-{c.ci[1]:.2f}] {c.conclusion}; "
            f"holds in {r.holds * 100:.0f} % of {n_cells} analyses; confidence {level}"
        )
    _print_comparisons(result, settings)
    print("Decision cards, most impact first:")
    for card in cards:
        flipped = card.impact["n_genes_flipped"]
        if card.status == "auto_decided":
            what = f"changes no conclusion; decided automatically ({card.decision})"
        else:
            what = f"changes {flipped} of {n_items} conclusions; needs a human"
        print(f"  {card.rank}. {card.kind}: {what}")


def _print_comparisons(result, settings) -> None:  # noqa: ANN001
    """Every comparison of a study with several (or a paired one): its calls and headline genes."""
    found = result.comparisons
    if found is None:
        return
    from qpilot.qpcr.contrast import CORRECTION_WORDS, TEST_WORDS

    words = TEST_WORDS[found.test]
    if len(found.comparisons) > 1:
        words += f"; {CORRECTION_WORDS[found.correction]}"
    if found.pair_by:
        words += f"; paired by {found.pair_by}"
    print(f"{len(found.comparisons)} comparison(s): {words} (the first is the one the cards use)")
    for outcome in found.comparisons:
        calls = [c.conclusion for c in outcome.contrasts.values()]
        n = (
            f"{outcome.n_pairs} pairs"
            if outcome.n_pairs is not None
            else f"{outcome.n_a} vs {outcome.n_b}"
        )
        print(f"  {outcome.label} ({n}): {calls.count('up')} up, {calls.count('down')} down")
        for gene in settings.headline:
            c = outcome.contrasts.get(gene)
            if c is None:
                continue
            print(
                f"    {gene}: {c.fc:.2f}x [{c.ci[0]:.2f}-{c.ci[1]:.2f}] {c.conclusion}; "
                f"corrected p {outcome.p_adjusted[gene]:.2g}, q {outcome.q_value[gene]:.2g}"
            )


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
            facts = StudyResult.model_validate_json(
                Path(args.results).read_text(encoding="utf-8")
            ).facts
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
        "--no-open", action="store_true", help="print the link but do not open a browser"
    )
    parser.add_argument(
        "--fresh-demo",
        action="store_true",
        help="move the demo study's earlier work aside (kept, never deleted) and start clean",
    )
    parser.add_argument(
        "--audit",
        action="append",
        default=[],
        metavar="DIR",
        help="also show a robustness-audit results folder (`qsim run --out DIR`), read-only "
        "(repeatable)",
    )


def _app(args: argparse.Namespace) -> int:
    from pathlib import Path

    from qpilot.web.server import main as serve_page

    audits = {Path(d).resolve().name: Path(d).resolve() for d in args.audit}
    serve_page(
        port=args.port,
        open_browser=not args.no_open,
        fresh_demo=args.fresh_demo,
        audit_dirs=audits,
    )
    return 0


def _doctor_arguments(parser: argparse.ArgumentParser) -> None:
    pass


def _doctor(args: argparse.Namespace) -> int:
    """Print what qPilot will use and whether anything can leave this machine; never downloads."""
    import platform

    from qpilot import __version__
    from qpilot.ai.config import ModelConfig
    from qpilot.cli.core_cmds import studio_outbound_line
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
    print("app: 127.0.0.1 only, this launch's key required, telemetry off")
    if config.provider == "none":
        print("outbound: none")
    else:
        target = config.endpoint or "https://api.anthropic.com"
        print(f"outbound: {target} (only when you use the model; provider {config.provider})")
    try:
        print(studio_outbound_line())  # Studio's own default: a local model unless one is named
    except ValueError as err:
        print(f"outbound (Studio): INVALID ({err})")
    print(
        "(the model is set in the environment: QPILOT_MODEL_PROVIDER, _ENDPOINT, _NAME; the page "
        "shows its status in Settings; the API key is only sent where it was configured)"
    )
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
        "open qPilot (one page: Studio, results, the audit, Prism, the record) on 127.0.0.1",
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
