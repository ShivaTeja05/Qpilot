"""``qpilot melt``: what each well's melt curve says, from an instrument export or an RDML file.

Reads only. The files are read as the page reads them (:func:`qpilot.io.connectors.materialise`:
CFX Melt Curve RFU Results, QuantStudio Melt Curve Raw Data, StepOne Melt Region files, RDML
with melt data, ...), each well's −dF/dT and peaks are computed (:mod:`qpilot.qpcr.melt`) and
judged with the shipped pack's G-MELT thresholds against the sample types the file declares (a
Studio session's design can re-type wells; the page shows that). Per plate and target: where
the product melts, how many wells were called what, and the wells G-MELT would point at.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from qpilot.cli._types import Command

WORDS = {
    "one_product": "one product",
    "extra_peak": "an extra peak",
    "tm_off": "no product at the expected Tm",
    "no_peak": "amplified, no melt peak",
    "not_amplified": "not amplified",
    "no_product": "control: nothing melted",
    "product": "control: a peak at the product's Tm (contamination candidate)",
    "dimer": "control: a primer-dimer candidate",
    "other_product": "control: another product",
    "unclassified": "a peak, product Tm not known",
    "not_judged": "not judged",
    "unreadable": "cannot be read",
    "no_melt": "no melt curve",
}


def _arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("files", nargs="+", help="an RDML file, or an instrument export's files")
    parser.add_argument("--json", action="store_true", help="print JSON")


def _table(path: Path, melt: Any) -> tuple[Any, str]:
    """The file's per-well table (declared sample types); a melt-only file: its melt wells."""
    import pandas as pd

    from qpilot.io.rdml_io import RdmlLoadError, load
    from qpilot.qpcr.curves import CurveAnalysisError, analyse_study

    try:
        experiments = [e["id"] for e in load(path, validate=False).experiments()]
        frames = [analyse_study(path, e, ()) for e in experiments]
        return pd.concat(frames, ignore_index=True), ""
    except (RdmlLoadError, CurveAnalysisError, ValueError):
        rows = [
            {"run_id": r, "well": w, "target": t, "sample": m.curve.sample}
            for (r, w, t), m in melt.wells.items()
        ]
        table = pd.DataFrame(rows).assign(sample_type="unkn", amplification=True, cq=1.0)
        note = "the file's curves could not be analysed: every well is judged as a study well"
        return table, note


def _assay_out(a: Any) -> dict[str, Any]:
    counts = Counter(w.status for w in a.wells if w.melt is not None)
    return {
        "plate": a.run_id,
        "target": a.target,
        "expected_tm": a.expected_tm,
        "expected_source": a.expected_source,
        "n_reference": len(a.reference),
        "min_tm": a.min_tm,
        "max_tm": a.max_tm,
        "counts": dict(sorted(counts.items())),
        "flagged": [
            {"well": w.well, "sample": w.sample, "call": w.status, "main_tm": w.main.tm}
            if w.main is not None
            else {"well": w.well, "sample": w.sample, "call": w.status, "main_tm": None}
            for w in a.wells
            if w.flagged
        ],
    }


def _line(item: dict[str, Any]) -> str:
    head = f"plate {item['plate']} · {item['target']}: "
    if item["expected_tm"] is None:
        head += "the product's Tm is not known here (too few study wells melted)"
    elif item["expected_source"] == "file":
        head += f"product declared at {item['expected_tm']:.1f} °C"
    else:
        head += (
            f"product at {item['expected_tm']:.1f} °C (median of {item['n_reference']} study "
            f"wells, {item['min_tm']:.1f} to {item['max_tm']:.1f} °C)"
        )
    counts = ", ".join(f"{n} {WORDS[k]}" for k, n in item["counts"].items())
    lines = [f"{head}; {counts}"]
    for f in item["flagged"]:
        tm = f" at {f['main_tm']:.1f} °C" if f["main_tm"] is not None else ""
        lines.append(f"  G-MELT points at {f['well']} ({f['sample']}): {WORDS[f['call']]}{tm}")
    return "\n".join(lines)


def _melt(args: argparse.Namespace) -> int:
    from qpilot.io.connectors import CaptureError, materialise
    from qpilot.qpcr import melt
    from qpilot.qpcr.gate_rules import melt_params, resolve_pack

    paths = [Path(f) for f in args.files]
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        print(f"qpilot melt: no such file: {', '.join(missing)}", file=sys.stderr)
        return 2
    try:
        rdml = materialise(paths if len(paths) > 1 else paths[0]).rdml_path
        data = melt.read_melt(rdml)
    except (CaptureError, melt.MeltError, OSError) as err:
        print(f"qpilot melt: {err}", file=sys.stderr)
        return 2
    pack = resolve_pack()
    out: dict[str, Any] = {"pack": f"{pack.pack} {pack.version}", "has_melt": data.has_melt}
    if not data.has_melt:
        out["message"] = "These files hold no melt curves."
        assays = []
    else:
        table, note = _table(Path(rdml), data)
        assays = [_assay_out(a) for a in melt.judge(table, data, melt_params(pack))]
        out.update(note=note, assays=assays)
    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    if not data.has_melt:
        print(out["message"])
        return 0
    if out["note"]:
        print(f"Note: {out['note']}.")
    for item in assays:
        print(_line(item))
    print(
        "A single peak at the expected temperature does not guarantee that it is the intended "
        f"amplicon (MIQE 2.0). Thresholds: pack {out['pack']}, rule G-MELT."
    )
    return 0


COMMANDS: list[Command] = [
    (
        "melt",
        "what each well's melt curve says: the product's Tm, extra peaks, controls (reads only)",
        _arguments,
        _melt,
    ),
]
