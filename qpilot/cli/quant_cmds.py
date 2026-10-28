"""``qpilot quantify`` and ``qpilot copies``: absolute quantification and preparing standards.

``qpilot quantify FILE…`` reads an RDML file or an instrument export as the page does
(:func:`qpilot.io.connectors.materialise`), fits each assay's standard curve per plate and
prints its slope, efficiency with its 95 % CI, R², LOD and LOQ, then every unknown's quantity
with its 95 % prediction interval and flags (:mod:`qpilot.qpcr.absolute`). It needs no study
and no design: the sample types and quantities are the file's (``--quantity NAME=VALUE`` gives a
standard's quantity when the file has none, e.g. QuantStudio's ``Std 1`` … ``Std 5``). Reads only;
``--csv`` writes the unknowns' table.

``qpilot copies --ng 1 --length 3000`` prints how many copies that mass of a molecule holds
(dsDNA by default; ``--kind ssDNA|RNA``) and, with ``--step`` and ``--levels``, the dilution
series from it.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from qpilot.cli._types import Command


def _quantify_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("files", nargs="+", help="an RDML file, or an instrument export's files")
    parser.add_argument("--target", action="append", default=None, help="only this assay")
    parser.add_argument(
        "--quantity",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="a standard's quantity (repeat per standard) when the file declares none",
    )
    parser.add_argument("--loq-cv", type=float, default=None, help="the LOQ's CV (default 0.35)")
    parser.add_argument("--csv", type=Path, default=None, help="write every unknown to this CSV")
    parser.add_argument("--json", action="store_true", help="print JSON")


def _quantities(given: list[str]) -> dict[str, float]:
    out = {}
    for item in given:
        name, sep, value = item.rpartition("=")
        if not sep or not name.strip():
            raise SystemExit(f"--quantity takes NAME=VALUE, not {item!r}")
        try:
            out[name.strip()] = float(value)
        except ValueError:
            raise SystemExit(f"--quantity {item!r}: {value!r} is not a number") from None
    return out


def _fmt(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}g}"


def _run_quantify(args: argparse.Namespace) -> int:
    from qpilot.io.connectors import CaptureError, materialise
    from qpilot.qpcr import absolute as ab
    from qpilot.qpcr.absolute_study import declared_quantities
    from qpilot.qpcr.curves import analyse_study

    files = [Path(f) for f in args.files]
    try:
        made = materialise(files if len(files) > 1 else files[0])
    except (CaptureError, OSError, ValueError) as err:
        print(f"qpilot quantify: {err}", file=sys.stderr)
        return 2
    table = analyse_study(made.rdml_path, None, ())
    settings = ab.AbsoluteSettings(loq_cv=args.loq_cv) if args.loq_cv else None
    result = ab.quantify(
        table,
        quantities=_quantities(args.quantity) or None,
        declared=declared_quantities(made.rdml_path),
        settings=settings,
        targets=args.target,
    )
    if args.csv is not None:
        _write_csv(args.csv, result)
    if args.json:
        print(json.dumps(ab.as_record(result), indent=2, sort_keys=True, default=str))
        return 0 if result.curves else 1
    _print(result)
    return 0 if result.curves else 1


def _print(result: Any) -> None:
    from qpilot.qpcr import absolute as ab

    unit = result.unit or "units of the standards"
    print(f"Absolute quantification (quantities per reaction, in {unit})")
    for target, reason in sorted(result.not_quantified.items()):
        print(f"  {target}: no curve: {reason}")
    for curve in result.curves:
        print(f"\n{curve.id} ({curve.scope}; quantities from {curve.quantity_source})")
        print(f"  {ab.summary_words(curve)}")
        for warning in curve.warnings:
            print(f"  note: {warning}")
        lod = curve.lod
        print(f"  LOD {_fmt(lod.quantity)}: {lod.words}")
        if curve.lod_model is not None:
            print(f"  LOD (logistic) {_fmt(curve.lod_model.quantity)}: {curve.lod_model.words}")
        print(f"  LOQ {_fmt(curve.loq.quantity)}: {curve.loq.words}")
    if result.unknowns:
        print("\nunit\tassay\twells\tmean Cq\tquantity\t95 % PI\tflags")
    for u in result.unknowns:
        interval = f"{_fmt(u.low)} to {_fmt(u.high)}" if u.low is not None else "-"
        flags = "; ".join(ab.flag_words(u.flags)) or ""
        mean = f"{u.mean_cq:.2f}" if u.mean_cq is not None else "-"
        print(
            f"{u.unit}\t{u.target}\t{u.n_detected}/{u.n_wells}\t{mean}\t{_fmt(u.quantity)}\t"
            f"{interval}\t{flags}"
        )


def _write_csv(path: Path, result: Any) -> None:
    from qpilot.qpcr import absolute as ab

    columns = ["unit", "assay", "samples", "wells", "detected", "mean_cq", "quantity", "low"]
    columns += ["high", "unit_of_quantity", "curve", "flags"]
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(columns)
        for u in result.unknowns:
            writer.writerow(
                [
                    u.unit,
                    u.target,
                    " ".join(u.samples),
                    u.n_wells,
                    u.n_detected,
                    "" if u.mean_cq is None else repr(u.mean_cq),
                    "" if u.quantity is None else repr(u.quantity),
                    "" if u.low is None else repr(u.low),
                    "" if u.high is None else repr(u.high),
                    result.unit,
                    " ".join(u.curves),
                    "; ".join(ab.flag_words(u.flags)),
                ]
            )


def _copies_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ng", type=float, required=True, help="ng of the standard (or ng/µL)")
    parser.add_argument("--length", type=float, required=True, help="bases (dsDNA: base pairs)")
    parser.add_argument("--kind", choices=("dsDNA", "ssDNA", "RNA"), default="dsDNA")
    parser.add_argument("--step", type=float, default=None, help="dilution step (10: ten-fold)")
    parser.add_argument("--levels", type=int, default=0, help="levels of the dilution series")
    parser.add_argument("--json", action="store_true", help="print JSON")


def _run_copies(args: argparse.Namespace) -> int:
    from qpilot.qpcr import absolute as ab

    try:
        copies = ab.copies_from_mass(args.ng, args.length, args.kind)
        series = ab.dilution_levels(copies, args.step, args.levels) if args.step else []
    except ab.AbsoluteError as err:
        print(f"qpilot copies: {err}", file=sys.stderr)
        return 2
    mass = ab.molar_mass(args.length, args.kind)
    if args.json:
        print(json.dumps({"copies": copies, "molar_mass": mass, "series": series}, indent=2))
        return 0
    print(f"{args.ng:g} ng of {ab.KIND_WORDS[args.kind]}, {args.length:g} long:")
    print(f"  molar mass {mass:,.2f} g/mol; {copies:.4g} copies ({copies / args.ng:.4g} per ng)")
    for i, level in enumerate(series, start=1):
        print(f"  level {i}: {level:.4g}")
    return 0


COMMANDS: list[Command] = [
    (
        "quantify",
        "Absolute quantification: standard curves, LOD/LOQ, every unknown's copies",
        _quantify_arguments,
        _run_quantify,
    ),
    (
        "copies",
        "ng of a standard to copies (dsDNA, ssDNA, RNA) and its dilution series",
        _copies_arguments,
        _run_copies,
    ),
]
