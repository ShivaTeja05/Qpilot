"""CLI commands owned by Dev 2: serve (MCP), plan, verify, rerun, harness."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from qpilot.cli._types import Command


def _record_dir(path: str, scratch: Path) -> Path:
    """A record folder, unpacking a zip record (any name or case) safely first."""
    import zipfile

    from qpilot.core.record import RecordError, unzip_record

    p = Path(path)
    if p.is_dir():
        return p
    if p.suffix.lower() == ".zip" or (p.is_file() and zipfile.is_zipfile(p)):
        return unzip_record(p, scratch / p.stem)
    if p.exists():
        raise RecordError(f"not an Analysis Record folder or zip: {p}")
    raise RecordError(f"no such record: {p}")


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


def studio_outbound_line(config=None) -> str:
    """The ``outbound (Studio):`` line of ``qpilot doctor``: where Studio's model calls go.

    Names the configured provider and whether it is local (provider ``none``, or an
    ``openai_compatible`` endpoint on localhost or a loopback address) or remote, using the
    same rule as the AI layer (``core.pseudonym.endpoint_is_local``). Sample names are
    pseudonymised before any remote call; a local endpoint can still forward elsewhere.
    ``config`` defaults to Studio's own choice (``ai.config.studio_config``: the environment
    when ``QPILOT_MODEL_PROVIDER`` is set, else the local OpenAI-compatible endpoint).
    """
    from qpilot.ai.client import public_endpoint
    from qpilot.ai.config import studio_config
    from qpilot.core.pseudonym import endpoint_is_local

    config = config if config is not None else studio_config()
    if config.provider == "none":
        return "outbound (Studio): none (provider none; no model is called)"
    try:
        target = public_endpoint(config.endpoint)
    except ValueError:
        target = "an unparsable endpoint"
    if not target:
        target = "https://api.anthropic.com" if config.provider == "anthropic" else "no endpoint"
    if endpoint_is_local(config.provider, config.endpoint):
        return (
            f"outbound (Studio): local, {target} (provider {config.provider}); "
            "sample names stay on this machine unless that endpoint forwards them"
        )
    return (
        f"outbound (Studio): REMOTE, {target} (provider {config.provider}); "
        "sample names are pseudonymised (keyed tokens) before any remote call"
    )


def _rerun_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("record", help="an Analysis Record folder or .zip")
    parser.add_argument("--out", default=None, help="where to write the regenerated results")


def _rerun(args: argparse.Namespace) -> int:
    import tempfile

    from qpilot.core.record import RecordError, rerun_compare

    with tempfile.TemporaryDirectory() as tmp:
        try:
            record = _record_dir(args.record, Path(tmp))
            report = rerun_compare(record, args.out or Path(tmp) / "rerun")
        except (RecordError, OSError, ValueError) as err:
            print(f"qpilot rerun: {err}", file=sys.stderr)
            return 2
    where = report.out_dir if args.out else "(temporary folder)"
    for name in report.compared:
        verdict = "DIFFERS from the record" if name in report.differs else "byte-identical"
        print(f"{name}: {verdict}")
    for name in report.not_in_record:
        print(f"{name}: not in this record, so not compared")
    if report.build_note:
        print(f"note: {report.build_note}")
    print(f"regenerated files: {where}")
    return 0 if report.same else 1


def _plan_arguments(parser: argparse.ArgumentParser) -> None:
    from qpilot.qpcr.plan import SD_RT_HELP, SD_WELL_HELP, SIGMA_HELP

    parser.add_argument("--fc", type=float, default=2.0, help="fold change to detect (default 2)")
    parser.add_argument("--sd", type=float, default=None, help=SIGMA_HELP)
    parser.add_argument("--n", type=int, default=None, help="planned samples (subjects) per group")
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--power", type=float, default=0.80)
    parser.add_argument("--plates", type=int, default=None, help="number of plates")
    parser.add_argument(
        "--no-calibrator",
        action="store_true",
        help="no inter-run calibrator on every plate",
    )
    parser.add_argument("--refs", type=int, default=None, help="candidate reference genes")
    budget = parser.add_argument_group(
        "replicate budget",
        "with any of these, --sd is the SD between subjects alone and --n counts subjects",
    )
    budget.add_argument("--sd-rt", type=float, default=None, help=SD_RT_HELP)
    budget.add_argument("--sd-well", type=float, default=None, help=SD_WELL_HELP)
    budget.add_argument("--n-rt", type=int, default=1, help="RT reactions per subject (default 1)")
    budget.add_argument("--n-tech", type=int, default=1, help="wells per RT reaction (default 1)")
    budget.add_argument("--cost-subject", type=float, default=None, help="cost of one subject")
    budget.add_argument("--cost-rt", type=float, default=None, help="cost of one RT reaction")
    budget.add_argument("--cost-well", type=float, default=None, help="cost of one qPCR well")
    budget.add_argument(
        "--cq",
        type=float,
        default=None,
        help="expected Cq of the target (accepted; the claim-floor check is not built yet)",
    )
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
            sd_rt=args.sd_rt,
            sd_well=args.sd_well,
            n_rt=args.n_rt,
            n_tech=args.n_tech,
            cost_subject=args.cost_subject,
            cost_rt=args.cost_rt,
            cost_well=args.cost_well,
            expected_cq=args.cq,
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
    for line in (out.budget or {}).get("sentences", []):
        print(f"Budget: {line}")
    for line in (out.budget or {}).get("notes", []):
        print(f"Note: {line}")
    return 0


DESIGN_NOTE = (
    "qPilot currently analyses the demo study design (experiment 'biomarker_set', MYCN-high vs "
    "rest, five control genes); other designs are not configurable yet."
)


def _fail(message: str) -> None:
    """Print a plain error and exit with code 2 (the CLI's code for a refused request)."""
    print(message, file=sys.stderr)
    raise SystemExit(2)


def _open_study(store, path: str) -> str:
    """``ensure_study`` with plain-language errors instead of tracebacks (exits with code 2)."""
    from qpilot.io.rdml_io import RdmlLoadError

    p = Path(path)
    if not p.exists():
        _fail(f"qpilot: no such RDML file: {path}")
    if not p.is_file():
        _fail(f"qpilot: not a file: {path}")
    try:
        return store.ensure_study(p)
    except RdmlLoadError as err:
        design = "no experiment" in str(err)
        _fail(f"qpilot: {err}" + (f"\n{DESIGN_NOTE}" if design else ""))
    except OSError as err:
        _fail(f"qpilot: cannot read {path}: {err.strerror or err}")
    except (KeyError, ValueError) as err:
        _fail(f"qpilot: this file does not fit the demo design ({err}).\n{DESIGN_NOTE}")
    raise AssertionError("unreachable")


def _pick_study(args: argparse.Namespace):
    """The store and study a command works on: --study, --rdml, or the only study."""
    from qpilot.core.store import StudyStore

    store = StudyStore()
    if getattr(args, "rdml", None):
        return store, _open_study(store, args.rdml)
    if getattr(args, "study", None):
        return store, args.study
    studies = store.list_studies()
    if len(studies) != 1:
        raise SystemExit("qpilot: give --study <id> or --rdml <file>")
    return store, studies[0]


def _harness_client(profile: str):
    import os

    from qpilot.ai.client import ModelClient, NoneBackend, make_backend
    from qpilot.ai.config import ModelConfig

    if profile == "none":
        return ModelClient(NoneBackend())
    env = ModelConfig.from_env()
    if profile == "anthropic":
        config = ModelConfig(
            provider="anthropic", endpoint=env.endpoint, model=env.model, api_key=env.api_key
        )
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
    parser.add_argument(
        "--studio",
        action="store_true",
        help="also the Studio items (typing, injection, proposal safety, Prism round trip, "
        "amplification calls); about an hour with a small local model",
    )
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
        latest = [Report.model_validate(r) for k, r in cards.items() if k != "history"]
        print(markdown(latest), end="")
        for r in latest:
            print(f"{r.profile}: run {r.run_at or 'unknown'}, endpoint {r.endpoint or '-'}")
        if cards.get("history"):
            print(f"({len(cards['history'])} earlier runs kept in the study's scorecard)")
        return 0
    result = store.get(study_id)
    items = build_items(
        result, store.cards(study_id), result.facts, n_per_type=args.n, studio=args.studio
    )
    if args.action == "make":
        print(json.dumps([i.model_dump() for i in items], indent=2))
        return 0
    try:
        client = _harness_client(args.profile)
    except ModelUnavailable as err:
        print(f"qpilot harness: {err}", file=sys.stderr)
        return 2
    from datetime import UTC, datetime

    run_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = run(items, client, store, study_id, profile_name=args.profile, run_at=run_at)
    saved = store.scorecard(study_id)
    if args.profile in saved:  # keep earlier runs instead of overwriting them
        history = saved.setdefault("history", [])
        history.append(saved[args.profile])
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
        "check an Analysis Record's checksums, decision chain and proposal chain",
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
