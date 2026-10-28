"""Command-line entry point. FROZEN at T0.

Each developer registers commands only in their own module: ``engine_cmds.py`` (Dev 1) and
``core_cmds.py`` (Dev 2); ``prism_cmds``, ``studio_cmds`` and ``quality_cmds`` (evidence, run
review, instruments) were added the same way. A command is a tuple
``(name, help, add_arguments, run)`` where ``add_arguments(parser)`` adds options to an
``argparse`` sub-parser and ``run(args)`` returns an exit code.
"""

import argparse
import sys
from collections.abc import Sequence

from qpilot import __version__
from qpilot.cli import core_cmds, engine_cmds, melt_cmds, prism_cmds, quality_cmds, studio_cmds
from qpilot.cli._console import ensure_utf8_output
from qpilot.cli._types import Command

__all__ = ["Command", "build_parser", "main"]


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level parser with one sub-command per registered command."""
    parser = argparse.ArgumentParser(
        prog="qpilot",
        description="qPilot: open qPCR analysis. Research use only.",
    )
    parser.add_argument("--version", action="version", version=f"qpilot {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    seen: set[str] = set()
    commands = [
        *engine_cmds.COMMANDS,
        *core_cmds.COMMANDS,
        *prism_cmds.COMMANDS,
        *studio_cmds.COMMANDS,
        *quality_cmds.COMMANDS,
        *melt_cmds.COMMANDS,
    ]
    for name, help_text, add_arguments, run in commands:
        if name in seen:
            raise RuntimeError(f"command registered twice: {name}")
        seen.add(name)
        command_parser = sub.add_parser(name, help=help_text)
        add_arguments(command_parser)
        command_parser.set_defaults(_run=run)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``qpilot`` command line and return its exit code."""
    ensure_utf8_output()  # ΔΔCq and → must not crash a Windows pipe (cp1252)
    parser = build_parser()
    args = parser.parse_args(argv)
    run = getattr(args, "_run", None)
    if run is None:
        parser.print_help()
        return 0
    return int(run(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
