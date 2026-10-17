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
    if report.build_note:
        print(f"note: {report.build_note}")
    print(f"regenerated files: {where}")
    return 0 if report.same else 1


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
        raise SystemExit(
            "qpilot: give --study <id> or --rdml <file> (or run `qpilot records open`)"
        )
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
    items = build_items(result, store.cards(study_id), result.facts, n_per_type=args.n)
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


def _records_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "action",
        choices=[
            "open",
            "list",
            "cards",
            "genes",
            "ask",
            "decide",
            "pending",
            "reject",
            "log",
            "export",
        ],
        help="open a study, read its cards, ask, decide (as the scientist), export the record",
    )
    parser.add_argument("rest", nargs="*", help="card id and option (decide) or a question (ask)")
    parser.add_argument("--study", default=None, help="study id (default: the only study)")
    parser.add_argument("--rdml", default=None, help="RDML file (open; default: the demo study)")
    parser.add_argument("--reason", default=None, help="why (decide / reject)")
    parser.add_argument("--expected-head", default=None, help="chain head you last read")
    parser.add_argument("--profile", choices=["none", "anthropic", "local"], default="none")
    parser.add_argument("--out", default=None, help="record folder (export)")
    parser.add_argument("--zip", action="store_true", help="also write a .zip (export)")
    parser.add_argument(
        "--without-input",
        action="store_true",
        help="leave the raw input (sample names, curves) out of the record; it can then be "
        "verified but not re-run (export)",
    )


INTERACTIVE_ONLY = (
    "decide and reject are meant for a person at an interactive terminal (or the app), and no "
    "terminal is attached here. AI agents should ask through MCP instead. (This is a guard "
    "against accidental scripted use, not a security boundary: anything that can run commands "
    "as you can act as you.)"
)


def _require_person() -> None:
    """Refuse decide/reject when no terminal is attached; an accident guard, not a boundary."""
    if sys.stdin is None or not sys.stdin.isatty():
        from qpilot.core.decisions import DecisionError

        raise DecisionError(INTERACTIVE_ONLY)


def _print_cards(store, study_id: str) -> None:
    for card in store.cards(study_id):
        flips = card.impact["n_genes_flipped"]
        who = "a person decides" if card.impact.get("flips") else "decided automatically"
        print(f"[{card.rank}] {card.id}  ({card.kind}; {flips} genes flip; {who})")
        print(
            f"    status: {card.status}; decision: {card.decision or '-'}; "
            f"by: {card.decided_by or '-'}"
        )
        for option in card.options:
            mark = "*" if option.id == card.recommended else " "
            genes = "  ".join(
                f"{g} {r.fc:.2f}x {r.conclusion}" for g, r in list(option.per_gene.items())[:4]
            )
            print(f"   {mark} {option.id:<24} {option.label[:38]:<38} {genes}")


def _records(args: argparse.Namespace) -> int:
    from qpilot.core.decisions import DecisionError, apply_decision, reject_request
    from qpilot.core.store import StudyStore

    if args.action == "open":
        from qpilot.io.datasets import default_cache_dir

        store = StudyStore()
        path = args.rdml or str(default_cache_dir() / "data_vermeulen_raw.rdml")
        try:
            study_id = _open_study(store, path)
        except SystemExit as err:  # message already printed by _open_study
            return int(err.code or 2)
        r = store.get(study_id)
        print(
            f"study {study_id}: {r.n_plates} plates, {r.n_samples} samples, "
            f"{r.n_reactions} reactions"
        )
        print(f"groups: {r.design.group_var} {r.design.n_hi} vs {r.design.n_lo} ({r.design.note})")
        g = r.genorm
        m = ", ".join(f"{ref} {g.M_initial[ref]:.2f}" for ref in g.order)
        v = ", ".join(f"{k} {val:.2f}" for k, val in g.V.items())
        print(f"geNorm M (lower = steadier; cut-off {g.cutoff_M}): {m}")
        print(f"geNorm V (want < {g.cutoff_V}): {v}")
        print(f"chain head: {store.chain_head(study_id)}")
        _print_cards(store, study_id)
        return 0
    if args.action == "list":
        store = StudyStore()
        for study_id in store.list_studies():
            r = store.get(study_id)
            print(
                f"{study_id}  {r.n_plates} plates  {len(r.contrasts)} genes  "
                f"{store.workspace(study_id)}"
            )
        return 0
    store, study_id = _pick_study(args)
    try:
        if args.action == "cards":
            _print_cards(store, study_id)
        elif args.action == "genes":
            r = store.get(study_id)
            print("Under the recommended choices (decisions do not change these numbers yet).")
            changed = [
                f"{c.id} = {c.decision}"
                for c in store.cards(study_id)
                if c.decision and c.decision != c.recommended
            ]
            if changed:
                print(f"Decided differently from the recommendation: {', '.join(changed)}")
            print(f"{'gene':<16} {'fold':>7} {'call':<5} {'holds':>6} {'level':<9} flips alone via")
            rows = sorted(r.robustness.values(), key=lambda x: (x.holds, x.target))
            for rob in rows:
                grade = r.confidence.get(rob.target)
                via = ", ".join(d for d, i in rob.impact.items() if i.get("flips")) or "-"
                print(
                    f"{rob.target:<16} {rob.fc:>6.2f}x {rob.conclusion:<5} {rob.holds:>6.0%} "
                    f"{grade.level if grade else '-':<9} {via}"
                )
        elif args.action == "ask":
            from qpilot.ai.ask import ask

            question = " ".join(args.rest)
            answer = ask(question, store, study_id, client=_harness_client(args.profile))
            print(answer.plain)
            tool = answer.tool_calls[0] if answer.tool_calls else {}
            print(
                f"\n(tool: {tool.get('tool')} {tool.get('args')}; status: {answer.status}; "
                f"model: {answer.provider}; validated: {answer.validated}; "
                f"template used: {answer.fallback}; drafts rejected: {answer.rejected_drafts})"
            )
        elif args.action == "decide":
            if len(args.rest) != 2:
                raise DecisionError("usage: records decide <card_id> <option> --reason '...'")
            _require_person()
            out = apply_decision(
                store,
                study_id,
                args.rest[0],
                args.rest[1],
                args.reason or "",
                "human",
                args.expected_head,
            )
            if out.status == "stale":
                print(f"Not applied: {out.reason}; read the card again (qpilot records cards)")
                print(f"chain head: {out.chain_head}")
                return 2
            print(
                f"{out.status}: {out.card.id if out.card else ''} -> "
                f"{out.card.decision if out.card else ''}"
            )
            if out.reason:
                print(out.reason)
            print(f"chain head: {out.chain_head}")
        elif args.action == "pending":
            for p in store.pending(study_id):
                print(f"{p.card_id}: {p.actor} asks for {p.option!r} because {p.reason!r} ({p.at})")
            if not store.pending(study_id):
                print("no requests waiting")
        elif args.action == "reject":
            if not args.rest or len(args.rest) > 2:
                raise DecisionError("usage: records reject <card_id> [option] --reason '...'")
            _require_person()
            option = args.rest[1] if len(args.rest) == 2 else None
            out = reject_request(
                store, study_id, args.rest[0], args.reason or "", args.expected_head, option
            )
            if out.status == "stale":
                print(f"Not rejected: {out.reason}; read the card again (qpilot records pending)")
                return 2
            print(f"{out.status}: {out.card.id} stays {out.card.decision or 'undecided'}")
        elif args.action == "log":
            for e in store.entries(study_id):
                print(
                    f"{e.seq:>3} {e.status:<13} {e.actor:<6} {e.card_id:<18} {e.option:<22} "
                    f"{e.reason[:50]}"
                )
        elif args.action == "export":
            from qpilot.core.record import verify, write_record, zip_record

            out_dir = args.out or f"qpilot-record-{study_id}"
            cards = store.cards(study_id)
            undecided = [c.id for c in cards if c.impact.get("flips") and c.decided_by != "human"]
            waiting = sorted({p.card_id for p in store.pending(study_id)})
            if undecided:
                print(f"warning: not yet decided by a person: {', '.join(undecided)}")
            if waiting:
                print(f"note: agent requests still waiting on: {', '.join(waiting)}")
            info = write_record(store, study_id, out_dir, include_input=not args.without_input)
            if not info.input_included:
                print("input file left out: this record can be verified but not re-run")
            print(f"record {info.record_id[:16]}… in {info.record_dir} ({info.n_files} files)")
            print(verify(info.record_dir).summary())
            if args.zip:
                print(f"zip: {zip_record(info.record_dir)}")
    except (DecisionError, KeyError, ValueError) as err:
        print(f"qpilot records: {str(err).strip(chr(39))}", file=sys.stderr)
        return 2
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
        "records",
        "open a study, read its cards, ask, decide as the scientist, export the record",
        _records_arguments,
        _records,
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
