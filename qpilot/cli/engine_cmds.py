"""CLI commands owned by Dev 1: fetch-demo, run, app, doctor, explain, validate."""

import argparse
import sys

from qpilot.cli._types import Command
from qpilot.io.datasets import (
    VERMEULEN_BYTES,
    DatasetIntegrityError,
    default_cache_dir,
    demo_dataset_info,
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
    except (DatasetIntegrityError, OSError) as err:
        print(f"qpilot fetch-demo: {err}", file=sys.stderr)
        return 1
    print(f"{path}  ({VERMEULEN_BYTES:,} bytes, sha256 OK)")
    print(f"{info['name']}: {info['contents']}")
    print(f"Licence {info['licence']}. Cite: {info['citation']}.")
    print(f"Note: {info['groups']}.")
    return 0


COMMANDS: list[Command] = [
    (
        "fetch-demo",
        "download the public 64-plate demo study (pinned, SHA-256 verified)",
        _fetch_demo_arguments,
        _fetch_demo,
    ),
]
