"""``python -m qpilot.integration``: the whole qPCR workflow, the audit, its check, the agents.

Commands::

    demo    [--out DIR] [--permutations N] [--no-simulator] [--no-roundtrip]
            The cached demo through every stage (no model; a scripted person with the reasons
            of `qpilot studio demo --check`); exits 1 when a checked number differs.
    audit   --study ID [--out DIR] [--permutations N]
            Audit a study a person analysed in Studio (in $QPILOT_STUDIES_DIR) with the
            Decision Simulator; default folder <studies>/simulator_audits/<ID>.
    verify  AUDIT_DIR [--record RECORD_DIR_OR_ZIP]
            Check an audit's checksums and lock; with --record, that it is that record's.
    serve   qPilot's MCP server plus the simulator's read-only tools, over stdio.
    status  What is installed and cached.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


def _demo(args: argparse.Namespace) -> int:
    from qpilot.core.store import StudyStore
    from qpilot.integration.workflow import (
        Options,
        demo_expected,
        exclude_demo_sample,
        run_workflow,
    )
    from qpilot.io.datasets import VERMEULEN_FILENAME, default_cache_dir

    rdml = default_cache_dir() / VERMEULEN_FILENAME
    if not rdml.exists():
        print("the demo dataset is not cached; run `qpilot fetch-demo`", file=sys.stderr)
        return 2
    out = Path(args.out)
    if out.exists() and any(out.iterdir()):
        print(f"--out must be a new or empty folder: {out}", file=sys.stderr)
        return 2
    store = StudyStore(out / "studies")  # never the user's own store
    options = Options(
        simulator=not args.no_simulator,
        permutations=args.permutations,
        roundtrip_edit=None if args.no_roundtrip else exclude_demo_sample,
        expected=demo_expected(),
    )
    work = out / "run"
    report = run_workflow(rdml, work, store, options=options)
    return 0 if report.ok else 1


def _audit(args: argparse.Namespace) -> int:
    from qpilot.core.store import StudyStore
    from qpilot.integration import simulator as sim
    from qpilot.integration.mcp_tools import default_audit_dir

    store = StudyStore()
    out = Path(args.out) if args.out else default_audit_dir(store, args.study)
    try:
        result = sim.audit(store, args.study, out, permutations=args.permutations)
    except (sim.NotApplicable, sim.AuditRefused, sim.SimulatorUnavailable) as err:
        print(f"audit refused: {err}", file=sys.stderr)
        return 1
    m = result.manifest
    print(f"audited {m['analyses']:,} analyses of study {args.study} in {result.seconds:.0f} s")
    print(f"verdicts: {m['verdict_counts']}")
    print(f"your choices against the prespecified analysis: {m['your_choices']}")
    print(f"written to {out} (lock {m['lock_sha256'][:12]})")
    return 0


def _verify(args: argparse.Namespace) -> int:
    from qpilot.integration.simulator import verify_audit

    record = args.record
    scratch = None
    if record and str(record).endswith(".zip"):
        from qpilot.core.record import unzip_record

        scratch = tempfile.TemporaryDirectory(prefix="qpilot-verify-")
        record = unzip_record(record, scratch.name)
    check = verify_audit(args.audit, record)
    print(check.summary())
    if scratch is not None:
        scratch.cleanup()
    return 0 if check.ok else 1


def _serve(args: argparse.Namespace) -> int:
    from qpilot.integration.mcp_tools import main

    main()
    return 0


def _status(args: argparse.Namespace) -> int:
    import qpilot
    from qpilot.core.store import default_studies_dir
    from qpilot.integration import simulator as sim
    from qpilot.io.datasets import VERMEULEN_FILENAME, default_cache_dir

    info = {
        "qpilot": qpilot.__version__,
        "simulator_installed": sim.available(),
        "demo_cached": (default_cache_dir() / VERMEULEN_FILENAME).exists(),
        "cache_dir": str(default_cache_dir()),
        "studies_dir": str(default_studies_dir()),
    }
    if info["simulator_installed"]:
        import qsim

        info["qsim"] = qsim.__version__
    print(json.dumps(info, indent=1))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """The parser of ``python -m qpilot.integration``."""
    parser = argparse.ArgumentParser(
        prog="python -m qpilot.integration",
        description="qPilot's qPCR workflow end to end, with the Decision Simulator. "
        "Research use only.",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    demo = sub.add_parser("demo", help="the cached demo through every stage, checked")
    demo.add_argument("--out", default="qpilot-workflow-demo", help="a new or empty folder")
    demo.add_argument("--permutations", type=int, default=999)
    demo.add_argument("--no-simulator", action="store_true")
    demo.add_argument("--no-roundtrip", action="store_true")
    demo.set_defaults(_run=_demo)
    audit = sub.add_parser("audit", help="audit a study analysed in Studio")
    audit.add_argument("--study", required=True)
    audit.add_argument("--out", default=None)
    audit.add_argument("--permutations", type=int, default=999)
    audit.set_defaults(_run=_audit)
    verify = sub.add_parser("verify", help="check an audit (and that it is a record's)")
    verify.add_argument("audit")
    verify.add_argument("--record", default=None)
    verify.set_defaults(_run=_verify)
    serve = sub.add_parser("serve", help="the MCP server with the simulator's tools (stdio)")
    serve.set_defaults(_run=_serve)
    status = sub.add_parser("status", help="what is installed and cached")
    status.set_defaults(_run=_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one command and return its exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    run = getattr(args, "_run", None)
    if run is None:
        parser.print_help()
        return 0
    return int(run(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
