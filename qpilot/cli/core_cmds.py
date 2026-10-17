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


def _pick_study(args: argparse.Namespace):
    """The store and study a harness command works on: --study, --rdml, or the only study."""
    from qpilot.core.store import StudyStore

    store = StudyStore()
    if getattr(args, "rdml", None):
        return store, store.ensure_study(args.rdml)
    if getattr(args, "study", None):
        return store, args.study
    studies = store.list_studies()
    if len(studies) != 1:
        raise SystemExit("qpilot harness: give --study <id> or --rdml <file>")
    return store, studies[0]


def _harness_client(profile: str):
    import os

    from qpilot.ai.client import ModelClient, NoneBackend, make_backend
    from qpilot.ai.config import ModelConfig

    if profile == "none":
        return ModelClient(NoneBackend())
    env = ModelConfig.from_env()
    if profile == "anthropic":
        config = ModelConfig(provider="anthropic", model=env.model, api_key=env.api_key)
    else:
        endpoint = os.environ.get("QPILOT_MODEL_ENDPOINT", "http://127.0.0.1:11434")
        config = ModelConfig(
            provider="openai_compatible", endpoint=endpoint, model=env.model, api_key=env.api_key
        )
    return ModelClient(make_backend(config))


def _harness_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("action", choices=["make", "run", "show"])
    parser.add_argument("--study", default=None, help="study id (default: the only study)")
    parser.add_argument("--rdml", default=None, help="analyse this RDML file first")
    parser.add_argument(
        "--profile",
        choices=["none", "anthropic", "local"],
        default="none",
        help="none = templates; anthropic or local use QPILOT_MODEL_NAME / _ENDPOINT / API_KEY",
    )
    parser.add_argument("--n", type=int, default=10, help="items per kind")
    parser.add_argument("--out", default=None, help="also write the scorecard files here")


def _harness(args: argparse.Namespace) -> int:
    import json

    from qpilot.ai.client import ModelUnavailable
    from qpilot.harness.make_evalset import build_items
    from qpilot.harness.report import Report, markdown, write
    from qpilot.harness.run import run

    store, study_id = _pick_study(args)
    if args.action == "show":
        cards = store.scorecard(study_id)
        if not cards:
            print("no scorecard yet; run `qpilot harness run`")
            return 1
        print(markdown([Report.model_validate(r) for r in cards.values()]), end="")
        return 0
    result = store.get(study_id)
    items = build_items(result, store.cards(study_id), result.facts, n_per_type=args.n)
    if args.action == "make":
        print(json.dumps([i.model_dump() for i in items], indent=2))
        return 0
    try:
        client = _harness_client(args.profile)
    except ModelUnavailable as err:
        print(f"qpilot harness: {err}", file=sys.stderr)
        return 2
    report = run(items, client, store, study_id, profile_name=args.profile)
    saved = store.scorecard(study_id)
    saved[args.profile] = report.model_dump()
    store.put_scorecard(study_id, saved)
    if args.out:
        write(report, args.out)
    print(markdown([report]), end="")
    return 0


def _serve_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--transport", choices=["stdio"], default="stdio", help="MCP transport (stdio only)"
    )


def _serve(args: argparse.Namespace) -> int:
    from qpilot.mcp_server import main as serve_main

    serve_main()
    return 0


COMMANDS: list[Command] = [
    (
        "serve",
        "run the MCP server for AI agents over stdio (claude mcp add qpilot -- qpilot serve)",
        _serve_arguments,
        _serve,
    ),
    (
        "harness",
        "score a model on this study before trusting it (make | run | show)",
        _harness_arguments,
        _harness,
    ),
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
