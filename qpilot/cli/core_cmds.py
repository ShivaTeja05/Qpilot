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


COMMANDS: list[Command] = [
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
