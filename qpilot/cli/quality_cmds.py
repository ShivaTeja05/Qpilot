"""CLI commands for what a study can and cannot tell you: evidence, run review, instruments.

``qpilot evidence``, ``qpilot report run-review``, ``qpilot trace``, ``qpilot check sheet`` and
``qpilot instrument inspect|list|add|history|lookback|position``. Every command reads; the few
that write (adding an instrument, ``lookback --log``) write the instrument registry or logbook,
never a study's results, cards or decisions. A run review is only rendered here: a person signs
it off in the app, and the command line has no way to decide or sign off anything. ``trace``
opens no card, and ``check sheet`` never edits the sheet.

Exit codes: 0 done, 1 the command ran and the answer is negative (a logbook that does not
verify), 2 refused or bad input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from qpilot.cli._types import Command


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False))


def _refuse(command: str, message: Any) -> int:
    print(f"qpilot {command}: {message}", file=sys.stderr)
    return 2


def _study_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "study",
        nargs="?",
        default=None,
        help="study id, or its RDML file (default: the only study)",
    )
    parser.add_argument("--json", action="store_true", help="print JSON")


def _resolve_study(value: str | None):
    """The store and study id: an RDML file is analysed once; plain errors exit with code 2."""
    from qpilot.cli.core_cmds import _fail, _open_study
    from qpilot.core.store import StudyStore

    store = StudyStore()
    if value and Path(value).exists():
        return store, _open_study(store, value)
    if value:
        return store, value
    studies = store.list_studies()
    if len(studies) != 1:
        _fail("qpilot: give a study id or an RDML file")
    return store, studies[0]


# ---- qpilot evidence ---------------------------------------------------------------------------


def _evidence_arguments(parser: argparse.ArgumentParser) -> None:
    _study_arg(parser)


def _evidence(args: argparse.Namespace) -> int:
    from qpilot.core.store import StudyNotFound
    from qpilot.explain.evidence_text import render_evidence
    from qpilot.mcp_server import study_ledger

    store, sid = _resolve_study(args.study)
    try:
        ledger, note = study_ledger(store, sid)
    except StudyNotFound as err:
        return _refuse("evidence", err)
    if ledger is None:
        return _refuse("evidence", f"no Evidence Ledger: {note}")
    if args.json:
        _print_json({**ledger.model_dump(mode="json"), "counts": ledger.counts()})
        return 0
    print(render_evidence(ledger).plain)
    return 0


# ---- qpilot report run-review ------------------------------------------------------------------


def _report_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("what", choices=["run-review"], help="the report to render")
    _study_arg(parser)
    parser.add_argument("--out", default=None, help="also write the page as HTML to this file")


def _report(args: argparse.Namespace) -> int:
    from qpilot.core.store import StudyNotFound
    from qpilot.mcp_server import study_review
    from qpilot.report.run_review import RunReviewError, render_html, render_text

    store, sid = _resolve_study(args.study)
    try:
        review = study_review(store, sid)
        text = render_text(review)
        page = render_html(review) if args.out else None
    except (StudyNotFound, RunReviewError, ValueError) as err:
        return _refuse("report", err)
    if page is not None:
        out = Path(args.out)
        if out.suffix.lower() not in (".html", ".htm"):
            return _refuse("report", "--out names an .html file")
        try:
            out.write_text(page, encoding="utf-8")
        except OSError as err:
            return _refuse("report", f"cannot write {out}: {err.strerror or err}")
    if args.json:
        _print_json(review.model_dump(mode="json"))
    else:
        print(text)
        print("Sign-off: a person signs off this review in the qPilot app.")
    if page is not None:
        print(f"wrote {args.out}", file=sys.stderr)
    return 0


# ---- qpilot trace --------------------------------------------------------------------------------


def _trace_arguments(parser: argparse.ArgumentParser) -> None:
    _study_arg(parser)
    root = parser.add_mutually_exclusive_group(required=True)
    root.add_argument("--gene", default=None, help="trace one gene's result")
    root.add_argument("--sample", default=None, help="trace one sample")
    root.add_argument("--well", default=None, metavar="PLATE:WELL", help="trace one well")
    parser.add_argument("--top", type=int, default=3, help="places to show (default 3)")


def _trace(args: argparse.Namespace) -> int:
    from qpilot.core.store import StudyNotFound
    from qpilot.explain.templates import TemplateError
    from qpilot.explain.trace_text import render_trace
    from qpilot.qpcr.trace import TraceError, trace_store

    store, sid = _resolve_study(args.study)
    try:
        result = trace_store(
            store, sid, gene=args.gene, sample=args.sample, well=args.well, top=args.top
        )
        text = None if args.json else render_trace(result).plain
    except (StudyNotFound, TraceError, TemplateError) as err:
        return _refuse("trace", err)
    if args.json:
        sys.stdout.write(result.to_json())  # byte-stable: sorted keys, trailing newline
        return 0
    print(text)
    return 0


# ---- qpilot check sheet --------------------------------------------------------------------------


def _check_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("what", choices=["sheet"], help="what to check")
    parser.add_argument("file", help="the analysis sheet (.xlsx or .csv); it is never edited")
    parser.add_argument(
        "--study", default=None, help="compare with this study's results (id or its RDML file)"
    )
    parser.add_argument(
        "--map",
        action="append",
        default=None,
        metavar="COL=ROLE",
        help="set what a column holds, e.g. C=cq:GAPDH or F=dcq (repeat); confirms the mapping",
    )
    parser.add_argument(
        "--confirm", action="store_true", help="confirm the guessed column mapping as printed"
    )
    parser.add_argument("--json", action="store_true", help="print JSON")


def _apply_map(mapping: Any, items: list[str]) -> Any:
    """The mapping with each ``COL=ROLE[:GENE]`` of ``items`` set by a person (refuses bad ones)."""
    from typing import get_args

    from qpilot.qpcr.sheetcheck import ColumnGuess, Role

    roles = set(get_args(Role))
    columns = {c.column: c for c in mapping.columns}
    for item in items:
        column, sep, value = item.partition("=")
        role, _, gene = value.partition(":")
        column, role, gene = column.strip().upper(), role.strip(), gene.strip()
        if not sep or not column.isalpha() or role not in roles:
            raise ValueError(
                f"--map takes COL=ROLE[:GENE] with ROLE one of {', '.join(sorted(roles))}, "
                f"not {item!r}"
            )
        old = columns.get(column)
        keep_gene = old.gene if old is not None and role == old.role else None
        columns[column] = ColumnGuess(column=column, role=role, gene=gene or keep_gene)
    ordered = sorted(columns.values(), key=lambda c: (len(c.column), c.column))
    return mapping.model_copy(update={"columns": ordered, "confirmed": True})


def _mapping_lines(mapping: Any) -> list[str]:
    lines = [f"Column mapping ({mapping.status}; {mapping.layout} sheet):"]
    for col in mapping.columns:
        if col.role == "ignored":
            continue
        gene = f" {col.gene}" if col.gene else ""
        scale = f" on {col.scale}" if col.scale else ""
        how = "set by you" if col.basis == "user" else f"from the {col.basis}"
        lines.append(f"  {col.column}: {col.role}{gene}{scale} ({how})")
    if mapping.references:
        lines.append(f"  reference genes: {', '.join(mapping.references)}")
    if not mapping.confirmed:
        lines.append(
            "  Not confirmed: check it, then rerun with --confirm, or set columns with "
            "--map COL=ROLE[:GENE]."
        )
    return lines


def _check(args: argparse.Namespace) -> int:
    from qpilot.core.store import StudyNotFound
    from qpilot.explain.sheetcheck_text import FINDINGS_KEY, render
    from qpilot.explain.templates import TemplateError
    from qpilot.qpcr.sheetcheck import (
        SheetCheckError,
        check_sheet,
        check_sheet_store,
        guess_mapping,
    )

    try:
        mapping = None
        if args.map or args.confirm:
            mapping = guess_mapping(args.file)
            if args.map:
                mapping = _apply_map(mapping, args.map)
            mapping = mapping.model_copy(update={"confirmed": True})
        if args.study:
            store, sid = _resolve_study(args.study)
            result = check_sheet_store(store, sid, args.file, mapping)
        else:
            result = check_sheet(args.file, mapping)
        if args.json:
            sys.stdout.write(result.to_json())  # byte-stable: sorted keys, trailing newline
            return 0
        text = render(result).plain
        findings = render(result, FINDINGS_KEY).plain if result.findings else ""
    except (SheetCheckError, StudyNotFound, TemplateError, ValueError, OSError) as err:
        return _refuse("check sheet", err)
    print("\n".join(_mapping_lines(result.mapping)))
    print(text)
    if findings:
        print(findings)
    print("The sheet was read only; it is never edited.")
    return 0


# ---- qpilot instrument ... -----------------------------------------------------------------------


def _mapping_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--study", action="append", default=None, help="a study id (repeat; default: every study)"
    )
    runs = parser.add_mutually_exclusive_group()
    runs.add_argument(
        "--map",
        action="append",
        default=None,
        metavar="RUN=INSTR",
        help="run id on an instrument (repeat); other runs are left out",
    )
    runs.add_argument(
        "--all-runs", default=None, metavar="INSTR", help="every run of the studies on INSTR"
    )
    parser.add_argument("--json", action="store_true", help="print JSON")


def _instrument_arguments(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="action", metavar="<action>", required=True)
    inspect = sub.add_parser("inspect", help="what a run file says about the instrument")
    inspect.add_argument("file", help="an .eds, QuantStudio or CFX export, or .rdml file")
    inspect.add_argument("--json", action="store_true", help="print JSON")
    inspect.add_argument("--date-order", choices=["DMY", "MDY"], default=None,
                         help="how the file writes dates like 11-12-2018")  # fmt: skip
    inspect.add_argument(
        "--show-serials",
        action="store_true",
        help="also show serial numbers (local only; hidden by default)",
    )
    listing = sub.add_parser("list", help="the registered instruments")
    listing.add_argument("--json", action="store_true", help="print JSON")
    add = sub.add_parser("add", help="register an instrument")
    add.add_argument("instrument_id", help="a short id: lower-case letters, digits, - or _")
    add.add_argument("--name", required=True, help="the name people use for it")
    add.add_argument("--model", default="", help="make and model")
    add.add_argument("--location", default="", help="where it stands")
    add.add_argument("--shared", action="store_true", help="a shared (core facility) instrument")
    add.add_argument("--alias", action="append", default=[], help="an identity string (repeat)")
    add.add_argument("--serial", action="append", default=[], help="a serial number (repeat)")
    history = sub.add_parser("history", help="an instrument's logbook, and whether it verifies")
    history.add_argument("instrument_id")
    history.add_argument("--since", default=None, help="only events on or after this ISO date")
    history.add_argument(
        "--show-notes", action="store_true", help="show the text people typed (local only)"
    )
    history.add_argument("--json", action="store_true", help="print JSON")
    back = sub.add_parser("lookback", help="what changes without an instrument's runs in a window")
    back.add_argument("--instrument", required=True, help="the instrument id")
    back.add_argument("--from", dest="start", required=True, help="first day (ISO date)")
    back.add_argument("--to", dest="end", required=True, help="last day (ISO date), inclusive")
    back.add_argument("--log", action="store_true", help="record the result in the logbook")
    _mapping_arguments(back)
    position = sub.add_parser("position", help="well positions that follow the instrument")
    position.add_argument("--instrument", required=True, help="the instrument id")
    _mapping_arguments(position)


def _instrument(args: argparse.Namespace) -> int:
    from qpilot.core.instruments import InstrumentError

    handlers = {
        "inspect": _inspect,
        "list": _list,
        "add": _add,
        "history": _history,
        "lookback": _lookback,
        "position": _position,
    }
    try:
        return handlers[args.action](args)
    except InstrumentError as err:
        return _refuse("instrument", err)


def _inspect(args: argparse.Namespace) -> int:
    from qpilot.explain.instrument_text import render_gate
    from qpilot.qpcr.gate_instr import g_instr
    from qpilot.qpcr.instrument_context import LOCAL_IDENTITY, InstrumentFileError
    from qpilot.qpcr.instrument_context import read_run_context as read

    try:
        ctx = read(args.file, date_order=args.date_order)
    except InstrumentFileError as err:
        return _refuse("instrument", err)
    lines = g_instr(ctx)
    serials = {k: ctx.identity.get(k) for k in sorted(LOCAL_IDENTITY) if ctx.identity.get(k)}
    if args.json:
        out = {"context": ctx.model_view(), "gate": [x.model_dump(mode="json") for x in lines]}
        if args.show_serials:
            out["serials"] = serials
        _print_json(out)
        return 0
    view = ctx.model_view()
    ident = {k: v for k, v in view["identity"].items() if v}
    print(f"file: {view['source_file']} ({view['source_kind']})")
    for key, value in sorted(ident.items()):
        print(f"{key}: {value}")
    run = {k: v for k, v in view["run"].items() if v}
    for key, value in sorted(run.items()):
        print(f"run {key}: {value}")
    for cal in view["calibrations"]:
        age = f", {cal['age_days']} days before the run" if cal.get("age_days") is not None else ""
        print(f"calibration {cal['type']}: {cal.get('performed_on') or 'date not in file'}{age}")
    if view["serials_present"]:
        if args.show_serials:
            for key, value in serials.items():
                print(f"{key}: {value} (local only)")
        else:
            print(f"serials in file: {', '.join(view['serials_present'])} (--show-serials)")
    for note in view["notes"]:
        print(f"note: {note}")
    print(render_gate(lines).plain)
    return 0


def _registry():
    from qpilot.core.store import StudyStore
    from qpilot.mcp_server import instrument_registry

    return instrument_registry(StudyStore())


def _list(args: argparse.Namespace) -> int:
    instruments = _registry().export()
    if args.json:
        _print_json(instruments)
        return 0
    if not instruments:
        print("no instruments registered; add one with `qpilot instrument add`")
        return 0
    for inst in instruments:
        shared = ", shared" if inst["shared"] else ""
        where = f", {inst['location']}" if inst["location"] else ""
        model = f" ({inst['make_model']})" if inst["make_model"] else ""
        print(f"{inst['instrument_id']}: {inst['display_name']}{model}{where}{shared}")
    return 0


def _add(args: argparse.Namespace) -> int:
    inst = _registry().register(
        args.instrument_id,
        args.name,
        make_model=args.model,
        location=args.location,
        shared=args.shared,
        aliases=args.alias,
        serials=args.serial,
    )
    print(f"registered {inst.instrument_id}: {inst.display_name}")
    return 0


def _history(args: argparse.Namespace) -> int:
    from qpilot.core.instruments import event_view

    registry = _registry()
    registry.get(args.instrument_id)
    book = registry.logbook(args.instrument_id)
    problems = book.verify()
    events = [] if problems else book.events(since=args.since)
    views = [event_view(e, include_text=args.show_notes) for e in events]
    if args.json:
        _print_json({"instrument_id": args.instrument_id, "events": views, "verify": problems})
        return 1 if problems else 0
    for view in views:
        when = view.get("at") or view["recorded_at"]
        payload = view.get("payload") or {}
        detail = ", ".join(f"{k}={v}" for k, v in sorted(payload.items()) if k != "note")
        if args.show_notes and payload.get("note"):
            detail += f" note: {payload['note']}"
        wells = f" wells {','.join(view['wells'])}" if view.get("wells") else ""
        print(f"{view['seq']} {when} {view['kind']} ({view['source']}, {view['actor']}){wells}"
              + (f": {detail}" if detail else ""))  # fmt: skip
    if not views and not problems:
        print(f"no events in the logbook of {args.instrument_id}")
    for problem in problems:
        print(f"does not verify: {problem}")
    if not problems:
        print(f"logbook verifies ({len(views)} events shown)")
    return 1 if problems else 0


def _runs(args: argparse.Namespace, store, instrument_id: str) -> tuple[dict, list[str], list]:
    """The run map and the studies for lookback or position history, from the flags."""
    from qpilot.mcp_server import run_map, study_run_ids

    studies = sorted(set(args.study)) if args.study else store.list_studies()
    if args.map:
        mapping = {}
        for item in args.map:
            run_id, sep, instr = item.rpartition("=")
            if not sep or not run_id or not instr:
                raise ValueError(f"--map takes RUN=INSTR, not {item!r}")
            mapping[run_id] = instr
        return mapping, [], studies
    if args.all_runs:
        mapping = {}
        for sid in studies:
            try:
                mapping.update({r: args.all_runs for r in study_run_ids(store, sid)})
            except Exception:  # the lookback reports a study whose runs it cannot list
                continue
        return mapping, [], studies
    mapping, assumed = run_map(store, studies, instrument_id)
    return mapping, assumed, studies


def _lookback(args: argparse.Namespace) -> int:
    from qpilot.core.store import StudyStore
    from qpilot.explain.lookback_text import lookback_text
    from qpilot.qpcr.lookback import REASONS, LookbackError, lookback, write_lookback

    store = StudyStore()
    try:
        mapping, assumed, studies = _runs(args, store, args.instrument)
        result = lookback(store, mapping, args.instrument, args.start, args.end, studies=studies)
    except (LookbackError, ValueError) as err:
        return _refuse("instrument lookback", err)
    if args.log:
        registry = _registry()
        write_lookback(registry.logbook(args.instrument), result, "human")
    if args.json:
        _print_json({**result.model_dump(mode="json"), "assumed_all_runs": assumed})
        return 0
    print(lookback_text(result))
    for study in result.studies:
        if study.status == "evaluated":
            line = f"Study {study.study_id}: {study.n_changed} of {study.n_conclusions} "
            line += "conclusions change"
            if study.changed:
                line += f" ({', '.join(study.changed_genes)})"
            print(line)
        elif study.status == "no_runs_in_window":
            print(f"Study {study.study_id}: no runs in the window")
        else:
            print(f"Study {study.study_id}: {REASONS.get(study.reason or '', 'cannot evaluate')}")
    for sid in assumed:
        print(f"note: no run map recorded for {sid}; every run counted as on {args.instrument}")
    if args.log:
        print(f"recorded in the logbook of {args.instrument}")
    return 0


def _position(args: argparse.Namespace) -> int:
    from qpilot.core.store import StudyStore
    from qpilot.explain.lookback_text import position_text
    from qpilot.qpcr.position_history import position_history_store

    store = StudyStore()
    try:
        mapping, assumed, studies = _runs(args, store, args.instrument)
        report = position_history_store(store, mapping, studies=studies)
    except ValueError as err:
        return _refuse("instrument position", err)
    if args.json:
        _print_json({**report.model_dump(mode="json"), "assumed_all_runs": assumed})
        return 0
    print(position_text(report))
    for sid in assumed:
        print(f"note: no run map recorded for {sid}; every run counted as on {args.instrument}")
    return 0


COMMANDS: list[Command] = [
    (
        "evidence",
        "what this study can and cannot tell you (Evidence Ledger; reads only)",
        _evidence_arguments,
        _evidence,
    ),
    (
        "report",
        "`report run-review`: one review page per study (renders only; sign-off is in the app)",
        _report_arguments,
        _report,
    ),
    (
        "trace",
        "from a gene's result, a sample or a well (PLATE:WELL) back to the places to look "
        "(reads only)",
        _trace_arguments,
        _trace,
    ),
    (
        "check",
        "`check sheet FILE`: recompute a lab's own ΔΔCq sheet; the file is never edited",
        _check_arguments,
        _check,
    ),
    (
        "instrument",
        "what run files say about instruments: inspect | list | add | history | lookback | "
        "position",
        _instrument_arguments,
        _instrument,
    ),
]
