"""CLI commands owned by Dev 2: plan, rerun, verify, serve, harness, records, mcp."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from qpilot.cli._types import Command


def _record_dir(path: str, scratch: Path) -> Path:
    """A record folder, unpacking a ``.zip`` record safely first."""
    from qpilot.core.record import unzip_record

    p = Path(path)
    if p.suffix == ".zip":
        return unzip_record(p, scratch / p.stem)
    return p


def _verify_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("record", help="an Analysis Record folder or .zip")


def _verify(args: argparse.Namespace) -> int:
    import tempfile

    from qpilot.core.record import RecordError, verify

    with tempfile.TemporaryDirectory() as tmp:
        try:
            report = verify(_record_dir(args.record, Path(tmp)))
        except RecordError as err:
            print(f"qpilot verify: {err}", file=sys.stderr)
            return 2
    print(report.summary())
    print("(tamper-evident, not tamper-proof)")
    return 0 if report.ok else 1


def _rerun_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("record", help="an Analysis Record folder")
    parser.add_argument("--out", default=None, help="where to write the regenerated results")


def _rerun(args: argparse.Namespace) -> int:
    from qpilot.core.record import RecordError, rerun

    record = Path(args.record)
    try:
        path = rerun(record, args.out)
    except RecordError as err:
        print(f"qpilot rerun: {err}", file=sys.stderr)
        return 2
    same = path.read_bytes() == (record / "results.json").read_bytes()
    print(f"{path}: {'byte-identical to the record' if same else 'DIFFERS from the record'}")
    return 0 if same else 1


def _plan_arguments(parser: argparse.ArgumentParser) -> None:
    from qpilot.qpcr.plan import SIGMA_HELP

    parser.add_argument("--fc", type=float, default=2.0, help="fold change to detect (default 2)")
    parser.add_argument("--sd", type=float, default=None, help=SIGMA_HELP)
    parser.add_argument("--n", type=int, default=None, help="planned samples per group")
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--power", type=float, default=0.80)
    parser.add_argument("--plates", type=int, default=None, help="number of plates")
    parser.add_argument(
        "--no-calibrator",
        action="store_true",
        help="no inter-run calibrator on every plate",
    )
    parser.add_argument("--refs", type=int, default=None, help="candidate reference genes")
    parser.add_argument("--json", action="store_true", help="print JSON")


def _plan(args: argparse.Namespace) -> int:
    from qpilot.qpcr.plan import plan

    try:
        out = plan(
            fc=args.fc,
            sd_log2=args.sd,
            n_per_group=args.n,
            alpha=args.alpha,
            power=args.power,
            n_plates=args.plates,
            calibrator_on_every_plate=None if args.plates is None else not args.no_calibrator,
            n_candidate_refs=args.refs,
        )
    except ValueError as err:
        print(f"qpilot plan: {err}", file=sys.stderr)
        return 2
    if args.json:
        print(out.model_dump_json(indent=2))
        return 0
    print(out.message)
    for line in out.cannot_detect:
        print(f"Cannot detect: {line}")
    for line in out.rules:
        print(f"Rule: {line}")
    return 0


COMMANDS: list[Command] = [
    (
        "plan",
        "before the first plate: samples needed and what a design cannot detect",
        _plan_arguments,
        _plan,
    ),
    (
        "verify",
        "check an Analysis Record's checksums and decision chain",
        _verify_arguments,
        _verify,
    ),
    (
        "rerun",
        "re-run an Analysis Record and compare results byte for byte",
        _rerun_arguments,
        _rerun,
    ),
]
