"""``qsim``: run the Decision Simulator, ask a what-if question, or list the decisions."""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from qsim.compare import whatif
from qsim.data import load_study
from qsim.engine import Engine
from qsim.issues import HEADLINE
from qsim.study_space import space_for


def _engine(rdml: str | None) -> Engine:
    study = load_study(rdml)
    return Engine(study, space_for(study)[0])


def cmd_run(args: argparse.Namespace) -> int:
    from qsim.report import run_all

    summary = run_all(
        args.rdml, args.out, args.permutations, args.bench_trials, args.seed, args.design_draws
    )
    print(
        f"wrote {args.out}/REPORT.md and summary.json ({summary['ledger']['total_cells']:,} analyses)"
    )
    return 0


def cmd_whatif(args: argparse.Namespace) -> int:
    engine = _engine(args.rdml)
    changes = dict(item.split("=", 1) for item in args.set)
    table = whatif(engine, changes)
    genes = args.genes or list(HEADLINE)
    if args.all:
        genes = list(table["gene"])
    view = table[table["gene"].isin(genes)]
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print(f"baseline: {engine.space.baseline}")
        print(f"changed:  {changes}\n")
        print(view.round(3).to_string(index=False))
        flipped = table[table["call"] != table["base_call"]]
        print(
            f"\n{len(flipped)} of {len(table)} calls change: {', '.join(flipped['gene']) or 'none'}"
        )
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    from qpilot.ai.client import ModelClient
    from qpilot.ai.config import ModelConfig

    from qsim.ask import Asker

    client = ModelClient(config=ModelConfig()) if args.no_model else None
    asker = Asker(args.results, client=client, rdml=args.rdml, model_writes=args.model_writes)
    ans = asker.answer(" ".join(args.question))
    print(ans.text)
    print(
        f"\n[{ans.tool} {ans.args} · routed by {ans.routed_by} · written by {ans.written_by}"
        f"{' (' + ans.model + ')' if ans.model and ans.written_by == 'model' else ''} · every number from the engine]"
    )
    if args.verbose and ans.problems:
        print("validator:", ans.problems)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    import json

    from qsim.validate import validate

    result = validate(args.data, args.out)
    print(json.dumps(result, indent=1))
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from qsim.demo import run_demo

    run_demo(args.rdml, gene=args.gene, well=args.well)
    return 0


def cmd_app(args: argparse.Namespace) -> int:
    from pathlib import Path

    from qsim.app import serve
    from qsim.plates import PlateProblem, prepare

    results = args.results
    if args.rdml:  # reuse the run for this file, or make a quick one under results/plates/
        try:
            results = prepare(
                args.rdml, args.results, progress=lambda s: print(s, "...", flush=True)
            )
        except PlateProblem as err:
            print(f"\nqsim cannot open {Path(args.rdml).name}.\n\n{err.full()}", file=sys.stderr)
            if err.detail:
                print(f"\n(details: {err.detail})", file=sys.stderr)
            return 2
    serve(
        results,
        args.rdml,
        args.port,
        no_model=args.no_model,
        open_browser=args.open,
        root=args.results,
    )
    return 0


def cmd_options(args: argparse.Namespace) -> int:
    engine = _engine(args.rdml)
    for d in engine.space.decisions:
        print(f"{d.id} [{d.kind}] {d.question}")
        for o in d.options:
            mark = "*" if engine.space.baseline[d.id] == o.id else " "
            print(f"  {mark} {o.id:24s} {o.tier:16s} {o.label}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="qsim", description="qPilot Decision Simulator. Research use only."
    )
    parser.add_argument("--rdml", help="RDML file (default: the public Vermeulen benchmark)")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser(
        "run", help="run every analysis, influence, inference, troubleshooting and the benchmark"
    )
    run.add_argument("--out", default="results")
    run.add_argument("--permutations", type=int, default=999)
    run.add_argument("--bench-trials", type=int, default=20)
    run.add_argument("--seed", type=int, default=2026)
    run.add_argument("--design-draws", type=int, default=100)
    run.set_defaults(func=cmd_run)
    w = sub.add_parser("whatif", help="compare any combination of choices with the baseline")
    w.add_argument("--set", action="append", default=[], metavar="DECISION=OPTION")
    w.add_argument("--genes", nargs="*")
    w.add_argument("--all", action="store_true", help="show every gene")
    w.set_defaults(func=cmd_whatif)
    a = sub.add_parser("ask", help="ask a question in plain words (local model, checked numbers)")
    a.add_argument("question", nargs="+")
    a.add_argument("--results", default="results")
    a.add_argument("--no-model", action="store_true", help="no model at all (keyword routing)")
    a.add_argument(
        "--model-writes",
        action="store_true",
        help="let the model word the answer (numbers still checked)",
    )
    a.add_argument("-v", "--verbose", action="store_true")
    a.set_defaults(func=cmd_ask)
    v = sub.add_parser(
        "validate", help="score every analysis against known answers (dilution series)"
    )
    v.add_argument("--data", default="data/untergasser/amplicon_primer_mix.rdml")
    v.add_argument("--out", default="results")
    v.set_defaults(func=cmd_validate)
    dm = sub.add_parser("demo", help="narrated walk from one raw curve to a verdict on one gene")
    dm.add_argument("--gene", default="NM23A")
    dm.add_argument("--well", default="A1")
    dm.set_defaults(func=cmd_demo)
    ap = sub.add_parser(
        "app", help="results screen in plain lab language, served on 127.0.0.1 (offline)"
    )
    ap.add_argument("--results", default="results")
    ap.add_argument(
        "--rdml",
        default=argparse.SUPPRESS,
        help="your own RDML file: a quick run goes to <results>/plates/ the first time",
    )
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-model", action="store_true", help="Ask without a model (keyword routing)")
    ap.add_argument("--open", action="store_true", help="open the page in the default browser")
    ap.set_defaults(func=cmd_app)
    o = sub.add_parser("options", help="list decisions and options (* = baseline)")
    o.set_defaults(func=cmd_options)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
