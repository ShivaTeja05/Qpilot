"""Synthetic, format-faithful qPCR exports with known ground truth (deterministic, stdlib only).

Why: no openly licensed public file has CFX curves exported *without* baseline subtraction, or the
same curves as raw signal, Rn and baseline-subtracted side by side with the truth behind them. These
files let the raw-ness detector, the readers and the Run Gate be tested against known answers.

Model (per well): copies after c cycles ``A(c) = N0 * E**c / (1 + N0 * (E**c - 1) / Nmax)``
(exponential phase with efficiency ``E``, saturating at ``Nmax``); reporter signal
``F(c) = offset + slope * c + scale * A(c) + noise``. Seeded ``random.Random`` and pure Python
floats, so the bytes are identical on every platform and Python version.

Layouts follow the vendors' own exports (compared against the real files in this corpus):
* Bio-Rad CFX Manager: ``<stem> -  Quantification Amplification Results_SYBR.csv`` (wide,
  CRLF, leading empty column, ``Cycle`` then wells ``A1``...) and
  ``<stem> -  Quantification Cq Results.csv`` (``A01`` wells, ``Content`` Unkn/Std/NTC/NRT,
  Cq ``NaN`` when none);
* Thermo Fisher Design & Analysis: ``# key: value`` header, quoted long-format
  ``Amplification Data`` (``Rn`` = reporter / ROX, ``dRn`` = Rn minus a linear baseline) and
  ``Results``.

Every file says SYNTHETIC in a header field or its name. Run ``python -I qpcr_synth.py <out_dir>``.
"""

from __future__ import annotations

import csv
import io
import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path

SEED = 20261019
N_CYCLES = 40
BASELINE_CYCLES = (3, 15)  # inclusive, 1-based: the window a vendor's linear baseline is fitted on
THRESHOLD_RFU = 250.0  # CFX-like single threshold on the baseline-subtracted curve
THRESHOLD_DRN = 0.1  # QuantStudio-like threshold on dRn
GENERATOR_VERSION = "1"


@dataclass(frozen=True)
class Well:
    """Ground truth of one reaction."""

    pos: str  # A1
    target: str
    sample: str
    content: str  # Unkn | Std | NTC | NRT (CFX content names)
    group: str  # A | B | '' (controls)
    n0: float  # starting copies (0 = no template)
    efficiency: float  # amplification factor per cycle (2.0 = 100 %)
    offset: float  # reporter background, RFU
    slope: float  # background drift, RFU per cycle
    scale: float  # RFU per copy
    nmax: float  # copies at saturation
    rox: float  # passive reference signal (QuantStudio files)


def _design(rng: random.Random) -> list[Well]:
    """96-well relative-quantification plate: 2 targets x 8 samples x 3 reps + standards + NTC/NRT.

    Group B samples have 4x the GOI copies of group A (REF unchanged), so the true fold change
    GOI/REF (B vs A) is 4.0. One NTC has a late primer-dimer-like signal, one NRT has genomic DNA.
    """
    wells: list[Well] = []
    base_n0 = {f"S{i}": 10 ** rng.uniform(3.6, 4.4) for i in range(1, 9)}
    eff = {"REF": 1.92, "GOI": 1.86}

    def add(pos, target, sample, content, group, n0):
        wells.append(
            Well(
                pos=pos,
                target=target,
                sample=sample,
                content=content,
                group=group,
                n0=n0,
                efficiency=round(eff[target] + rng.gauss(0, 0.008), 4),
                offset=round(rng.uniform(1100, 1900), 2),
                slope=round(rng.gauss(2.0, 1.5), 3),
                scale=7.5e-9,
                nmax=round(1.1e12 * rng.uniform(0.85, 1.15), -6),
                rox=round(rng.uniform(2600, 3400), 1),
            )
        )

    for row_i, row in enumerate("ABCD"):
        for half in range(2):
            sample = f"S{row_i * 2 + half + 1}"
            group = "A" if sample in ("S1", "S2", "S3", "S4") else "B"
            for rep in range(3):
                col = half * 3 + rep + 1
                ref_n0 = base_n0[sample] * math.exp(rng.gauss(0, 0.05))
                goi_n0 = base_n0[sample] * 0.25 * (4.0 if group == "B" else 1.0)
                goi_n0 *= math.exp(rng.gauss(0, 0.05))
                add(f"{row}{col}", "REF", sample, "Unkn", group, ref_n0)
                add(f"{row}{col + 6}", "GOI", sample, "Unkn", group, goi_n0)
    for row in "EF":
        for i, copies in enumerate((1e5, 1e4, 1e3, 1e2, 1e1)):
            add(f"{row}{i + 1}", "REF", f"Std{i + 1}", "Std", "", copies)
            add(f"{row}{i + 7}", "GOI", f"Std{i + 1}", "Std", "", copies)
    for target, start in (("REF", 1), ("GOI", 7)):
        for k in range(3):
            add(
                f"G{start + k}",
                target,
                "NTC",
                "NTC",
                "",
                2.0 if (target == "GOI" and k == 2) else 0.0,
            )
            add(
                f"G{start + 3 + k}",
                target,
                "NRT",
                "NRT",
                "",
                30.0 if (target == "REF" and k == 0) else 0.0,
            )
    return wells


def _copies(w: Well, cycle: int) -> float:
    if w.n0 <= 0:
        return 0.0
    grow = w.efficiency**cycle
    return w.n0 * grow / (1.0 + w.n0 * (grow - 1.0) / w.nmax)


def _raw_curve(w: Well, rng: random.Random) -> list[float]:
    return [
        w.offset + w.slope * c + w.scale * _copies(w, c) + rng.gauss(0, 6.0)
        for c in range(1, N_CYCLES + 1)
    ]


def _linear_fit(ys: list[float], first: int, last: int) -> tuple[float, float]:
    xs = list(range(first, last + 1))
    sub = ys[first - 1 : last]
    n = len(xs)
    mx, my = sum(xs) / n, sum(sub) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, sub, strict=True)) / sxx
    return my - b * mx, b


def _baseline_subtract(ys: list[float]) -> list[float]:
    a, b = _linear_fit(ys, *BASELINE_CYCLES)
    return [y - (a + b * c) for c, y in enumerate(ys, start=1)]


def _threshold_cycle(ys: list[float], threshold: float) -> float | None:
    """First crossing above ``threshold`` after the baseline window, linearly interpolated."""
    for c in range(BASELINE_CYCLES[1] + 1, len(ys) + 1):
        lo, hi = ys[c - 2], ys[c - 1]
        if lo < threshold <= hi:
            return (c - 1) + (threshold - lo) / (hi - lo)
    return None


def _num(x: float) -> str:
    return repr(float(x))


def _well_order(pos: str) -> tuple[int, int]:
    return ("ABCDEFGH".index(pos[0]), int(pos[1:]))


def _write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def generate(out_dir: str | Path) -> list[Path]:
    """Write every synthetic file into ``out_dir/<set>/`` and return the paths (sorted)."""
    out = Path(out_dir)
    rng = random.Random(SEED)
    wells = sorted(_design(rng), key=lambda w: _well_order(w.pos))
    raw = {w.pos: _raw_curve(w, rng) for w in wells}
    bs = {pos: _baseline_subtract(ys) for pos, ys in raw.items()}
    cq = {pos: _threshold_cycle(ys, THRESHOLD_RFU) for pos, ys in bs.items()}
    written: list[Path] = []

    # ---- Bio-Rad CFX: same curves, raw and baseline-subtracted, two export sets
    cfx = out / "cfx-manager-raw-vs-baseline-subtracted"
    cfx.mkdir(parents=True, exist_ok=True)
    for stem, curves in (("qpilot-synthetic-raw", raw), ("qpilot-synthetic-baselined", bs)):
        lines = [",Cycle," + ",".join(w.pos for w in wells)]
        for c in range(N_CYCLES):
            lines.append(f",{c + 1}," + ",".join(_num(curves[w.pos][c]) for w in wells))
        p = cfx / f"{stem} -  Quantification Amplification Results_SYBR.csv"
        _write(p, "\r\n".join(lines) + "\r\n")
        written.append(p)
        head = (
            ",Well,Fluor,Target,Content,Sample,Biological Set Name,Cq,Cq Mean,Cq Std. Dev,"
            "Starting Quantity (SQ),Log Starting Quantity,SQ Mean,SQ Std. Dev,Set Point,Well Note"
        )
        rows = [head]
        for w in wells:
            well = f"{w.pos[0]}{int(w.pos[1:]):02d}"
            value = cq[w.pos]
            sq = _num(w.n0) if w.content == "Std" else "NaN"
            log_sq = _num(math.log10(w.n0)) if w.content == "Std" else "NaN"
            cq_txt = _num(value) if value is not None else "NaN"
            rows.append(
                f",{well},SYBR,{w.target},{w.content},{w.sample},,{cq_txt},{cq_txt},0,"
                f"{sq},{log_sq},{sq},0,60,"
            )
        p = cfx / f"{stem} -  Quantification Cq Results.csv"
        _write(p, "\r\n".join(rows) + "\r\n")
        written.append(p)

    # ---- Thermo Fisher Design & Analysis CSV: Rn = reporter / ROX, dRn = Rn - linear baseline
    qs = out / "quantstudio-design-analysis-rn-drn"
    qs.mkdir(parents=True, exist_ok=True)
    header = [
        "# File Name: qpilot-synthetic.eds",
        "# Comment: SYNTHETIC qPilot test file (tests/fixtures/corpus/_generators/qpcr_synth.py)",
        "# Operator: SYNTHETIC",
        "# Barcode: ",
        "# Instrument Type: QuantStudio™ 5 System",
        "# Block Type: 96-Well 0.2-mL Block",
        "# Instrument Name: SYNTHETIC",
        "# Instrument Serial Number: 000000000",
        "# Passive Reference: ROX",
        "# PCR Stage/Step Number: Stage 2 Step 2",
        "# Quantification Cycle Method: CT",
        "# Software Name and Version: SYNTHETIC (Design & Analysis Software v2.7.0 layout)",
        f"# Generator: qpcr_synth.py v{GENERATOR_VERSION} seed {SEED}",
    ]
    task = {"Unkn": "UNKNOWN", "Std": "STANDARD", "NTC": "NTC", "NRT": "NTC"}
    rn = {w.pos: [y / w.rox for y in raw[w.pos]] for w in wells}
    drn = {pos: _baseline_subtract(ys) for pos, ys in rn.items()}
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(
        ["Well", "Well Position", "Cycle Number", "Target", "Rn", "dRn", "Sample", "Omit"]
    )
    for w in wells:
        number = _well_order(w.pos)[0] * 12 + _well_order(w.pos)[1]
        for c in range(N_CYCLES):
            writer.writerow(
                [
                    number,
                    w.pos,
                    c + 1,
                    w.target,
                    _num(rn[w.pos][c]),
                    _num(drn[w.pos][c]),
                    w.sample,
                    "FALSE",
                ]
            )
    p = qs / "qpilot-synthetic_Amplification Data.csv"
    _write(p, "\n".join(header) + "\n" + buf.getvalue())
    written.append(p)
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(
        [
            "Well",
            "Well Position",
            "Omit",
            "Sample",
            "Target",
            "Task",
            "Reporter",
            "Quencher",
            "Amp Status",
            "Cq",
            "Threshold",
            "Baseline Start",
            "Baseline End",
            "Quantity",
            "Comments",
        ]
    )
    for w in wells:
        number = _well_order(w.pos)[0] * 12 + _well_order(w.pos)[1]
        value = _threshold_cycle(drn[w.pos], THRESHOLD_DRN)
        writer.writerow(
            [
                number,
                w.pos,
                "FALSE",
                w.sample,
                w.target,
                task[w.content],
                "SYBR",
                "None",
                "AMP" if value is not None else "NO_AMP",
                _num(value) if value is not None else "UNDETERMINED",
                _num(THRESHOLD_DRN),
                BASELINE_CYCLES[0],
                BASELINE_CYCLES[1],
                _num(w.n0) if w.content == "Std" else "",
                "NRT" if w.content == "NRT" else "",
            ]
        )
    p = qs / "qpilot-synthetic_Results.csv"
    _write(p, "\n".join(header) + "\n" + buf.getvalue())
    written.append(p)

    # ---- ground truth, shared by both sets
    for folder in (cfx, qs):
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(
            [
                "well",
                "target",
                "sample",
                "content",
                "group",
                "n0",
                "efficiency",
                "offset_rfu",
                "slope_rfu_per_cycle",
                "rfu_per_copy",
                "nmax",
                "rox_rfu",
                "cq_cfx_threshold_250",
            ]
        )
        for w in wells:
            value = cq[w.pos]
            writer.writerow(
                [
                    w.pos,
                    w.target,
                    w.sample,
                    w.content,
                    w.group,
                    _num(w.n0),
                    _num(w.efficiency),
                    _num(w.offset),
                    _num(w.slope),
                    _num(w.scale),
                    _num(w.nmax),
                    _num(w.rox),
                    _num(value) if value is not None else "",
                ]
            )
        p = folder / "truth.csv"
        _write(p, buf.getvalue())
        written.append(p)
    return sorted(written)


if __name__ == "__main__":
    for path in generate(sys.argv[1] if len(sys.argv) > 1 else "."):
        print(path)
