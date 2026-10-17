"""``qsim``: run the Decision Simulator, ask a what-if question, or list the decisions."""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from qsim.compare import whatif
from qsim.data import load_study
from qsim.decisions import qpcr_space
from qsim.engine import Engine
from qsim.issues import HEADLINE


def _engine(rdml: str | None) -> Engine:
    study = load_study(rdml)
    return Engine(study, qpcr_space(study.candidates, study.primary_refs))


def cmd_run(args: argparse.Namespace) -> int:
    from qsim.report import run_all

    summary = run_all(args.rdml, args.out, args.permutations, args.bench_trials, args.seed)
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


def cmd_demo(args: argparse.Namespace) -> int:
    from qsim.demo import run_demo

    run_demo(args.rdml, gene=args.gene, well=args.well)
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
    run.set_defaults(func=cmd_run)
    w = sub.add_parser("whatif", help="compare any combination of choices with the baseline")
    w.add_argument("--set", action="append", default=[], metavar="DECISION=OPTION")
    w.add_argument("--genes", nargs="*")
    w.add_argument("--all", action="store_true", help="show every gene")
    w.set_defaults(func=cmd_whatif)
    dm = sub.add_parser("demo", help="narrated walk from one raw curve to a verdict on one gene")
    dm.add_argument("--gene", default="NM23A")
    dm.add_argument("--well", default="A1")
    dm.set_defaults(func=cmd_demo)
    o = sub.add_parser("options", help="list decisions and options (* = baseline)")
    o.set_defaults(func=cmd_options)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
