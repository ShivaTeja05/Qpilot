"""Synthetic plates with known truth, and writers for the vendor formats the connectors read.

Curves follow ``F = base + drift * c + Fmax * N / (N + K)`` with ``N = N0 * E**c`` plus
deterministic noise, so the efficiency, starting quantity and baseline are known. The writers
produce format-faithful exports (header names, header blocks, well naming) of the vendor files
described in the connector docstrings; they are not copies of real files.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass
class Well:
    well: str
    sample: str
    target: str
    task: str  # vendor task / content text
    fluor: list[float] = field(default_factory=list)
    cq: float | None = None
    quantity: float | None = None
    dye: str = "SYBR"


def curve(
    n0: float,
    eff: float = 1.9,
    *,
    cycles: int = 40,
    base: float = 500.0,
    drift: float = 0.5,
    fmax: float = 8000.0,
    k: float = 1e11,
    noise: float = 4.0,
    seed: int = 0,
) -> list[float]:
    """One raw amplification curve (cycles 1..``cycles``)."""
    rng = np.random.default_rng(seed)
    c = np.arange(1, cycles + 1, dtype=float)
    n = n0 * eff**c
    f = base + drift * c + fmax * n / (n + k) + rng.normal(0, noise, cycles)
    return [round(float(v), 3) for v in f]


def subtract_baseline(fluor: list[float], first: int = 3, last: int = 15) -> list[float]:
    """Per-well linear baseline subtraction over cycles ``first..last`` (what CFX does)."""
    y = np.asarray(fluor)
    x = np.arange(1, len(y) + 1)
    sel = (x >= first) & (x <= last)
    slope, intercept = np.polyfit(x[sel], y[sel], 1)
    return [round(float(v), 3) for v in y - (intercept + slope * x)]


def plate(
    rows: int = 4,
    columns: int = 6,
    targets: tuple[str, ...] = ("GAPDH", "MYC"),
    *,
    seed: int = 1,
    subtract: bool = False,
) -> list[Well]:
    """A small plate: unknowns, one NTC per target and two standards, raw or subtracted."""
    wells = []
    index = 0
    for r in range(rows):
        for c in range(columns):
            label = f"{chr(65 + r)}{c + 1}"
            target = targets[index % len(targets)]
            if c == columns - 1 and r == 0:
                task, sample, n0, quantity = "NTC", "", 0.0, None
            elif c == columns - 1 and r in (1, 2):
                task, sample, n0, quantity = "Std", f"Std{r}", 10.0 ** (4 + r), 10.0 ** (4 + r)
            else:
                task, sample, n0, quantity = (
                    "Unkn",
                    f"S{index % 8 + 1}",
                    10.0 ** (2 + index % 3),
                    None,
                )
            fluor = curve(max(n0, 1e-9), seed=seed * 1000 + index)
            if subtract:
                fluor = subtract_baseline(fluor)
            cq = None if n0 == 0 else round(float(np.log(1e9 / n0) / np.log(1.9)), 2)
            wells.append(Well(label, sample, target, task, fluor, cq, quantity))
            index += 1
    return wells


def _csv(rows: list[list[object]], delimiter: str = ",") -> str:
    buffer = io.StringIO()
    csv.writer(buffer, delimiter=delimiter, lineterminator="\r\n").writerows(rows)
    return buffer.getvalue()


def _cfx_well(label: str) -> str:
    return f"{label[0]}{int(label[1:]):02d}"


def write_cfx(
    folder: Path, wells: list[Well], run: str = "run1", *, fluor: str = "SYBR"
) -> list[Path]:
    """CFX 'Export All Data Sheets' CSVs: amplification (per fluor), Cq results, run info."""
    folder.mkdir(parents=True, exist_ok=True)
    n = len(wells[0].fluor)
    amp = [["", "Cycle", *[w.well for w in wells]]]
    for i in range(n):
        amp.append(["", i + 1, *[w.fluor[i] for w in wells]])
    cq = [["", "Well", "Fluor", "Target", "Content", "Sample", "Biological Set Name", "Cq",
           "Cq Mean", "Cq Std. Dev", "Starting Quantity (SQ)", "Log Starting Quantity",
           "SQ Mean", "SQ Std. Dev", "Set Point", "Well Note"]]  # fmt: skip
    for w in wells:
        content = {"Unkn": "Unkn-01", "Std": "Std-01", "NTC": "NTC"}[w.task]
        cq.append(["", _cfx_well(w.well), fluor, w.target, content, w.sample, "",
                   "NaN" if w.cq is None else w.cq, "", "", w.quantity or "", "", "", "",
                   "60", ""])  # fmt: skip
    info = [["File Name", "admin_2019-03-05.pcrd"], ["Created By User", "admin"],
            ["Notes", ""], ["Run Started", "03/05/2019 14:22:11 UTC"],
            ["Run Ended", "03/05/2019 15:40:02 UTC"], ["Base Serial Number", "CT012345"],
            ["Optical Head Serial Number", "785BR0123"],
            ["CFX Manager Version", "3.1.1517.0823"]]  # fmt: skip
    paths = [
        folder / f"{run} -  Quantification Amplification Results_{fluor}.csv",
        folder / f"{run} -  Quantification Cq Results.csv",
        folder / f"{run} -  Run Information.csv",
    ]
    for path, rows in zip(paths, (amp, cq, info), strict=True):
        path.write_text(_csv(rows), encoding="utf-8-sig", newline="")
    return paths


QS_HEADER = [
    "* Block Type = 96-Well Block (0.2mL)",
    "* Calibration Background is expired  = No",
    "* Calibration Background performed on = 2019-03-13",
    "* Calibration Pure Dye SYBR is expired = Yes",
    "* Chemistry = SYBR_GREEN",
    "* Experiment File Name = C:\\Users\\lab\\run1.eds",
    "* Experiment Name = run1",
    "* Experiment Type = Comparative Cт (ΔΔCт)",
    "* Instrument Name = QS5-lab",
    "* Instrument Serial Number = 272310579",
    "* Instrument Type = QuantStudio™ 5 System",
    "* Passive Reference = ROX",
    "* Quantification Cycle Method = Ct",
]


def write_quantstudio(
    path: Path, wells: list[Well], *, rn: bool = True, encoding: str = "utf-8"
) -> Path:
    """A QuantStudio Real-Time PCR Software TXT export with every section in one file."""
    lines = list(QS_HEADER) + ["", "[Sample Setup]"]
    lines.append("\t".join(["Well", "Well Position", "Sample Name", "Sample Color",
                            "Biogroup Name", "Target Name", "Target Color", "Task",
                            "Reporter", "Quencher", "Quantity", "Comments"]))  # fmt: skip
    task = {"Unkn": "UNKNOWN", "Std": "STANDARD", "NTC": "NTC"}
    index = {w.well: (ord(w.well[0]) - 65) * 12 + int(w.well[1:]) for w in wells}
    for w in wells:
        lines.append("\t".join(str(v) for v in [index[w.well], w.well, w.sample, "", "",
                                                 w.target, "", task[w.task], "SYBR", "None",
                                                 w.quantity or "", ""]))  # fmt: skip
    lines += ["", "[Amplification Data]"]
    lines.append("\t".join(["Well", "Well Position", "Cycle", "Target Name"]
                           + (["Rn", "Delta Rn"] if rn else ["Delta Rn"])))  # fmt: skip
    for w in wells:
        base = float(np.median(w.fluor[2:15]))
        for i, f in enumerate(w.fluor):
            rn_value = f / 1000.0
            values = (
                [f"{rn_value:.5f}", f"{rn_value - base / 1000.0:.5f}"]
                if rn
                else [f"{rn_value - base / 1000.0:.5f}"]
            )
            lines.append("\t".join([str(index[w.well]), w.well, str(i + 1), w.target, *values]))
    lines += ["", "[Results]"]
    lines.append("\t".join(["Well", "Well Position", "Omit", "Sample Name", "Target Name",
                            "Task", "Reporter", "Quencher", "CT", "Ct Mean", "Ct SD",
                            "Quantity", "Automatic Ct Threshold", "Ct Threshold",
                            "Automatic Baseline", "Baseline Start", "Baseline End",
                            "Comments"]))  # fmt: skip
    for w in wells:
        ct = "Undetermined" if w.cq is None else f"{w.cq:.3f}"
        lines.append("\t".join(str(v) for v in [index[w.well], w.well, "false", w.sample,
                                                 w.target, task[w.task], "SYBR", "None", ct,
                                                 "", "", w.quantity or "", "true", "0.2",
                                                 "true", "3", "15", ""]))  # fmt: skip
    path.write_text("\r\n".join(lines) + "\r\n", encoding=encoding, newline="")
    return path


def write_tidy(
    path: Path, wells: list[Well], *, delimiter: str = ",", decimal_comma: bool = False
) -> Path:
    """The generic long table (well, sample, target, sample type, cycle, fluorescence)."""
    rows: list[list[object]] = [
        ["well", "sample", "target", "sample type", "cycle", "fluorescence"]
    ]
    for w in wells:
        for i, f in enumerate(w.fluor):
            value = f"{f}".replace(".", ",") if decimal_comma else f
            rows.append([w.well, w.sample, w.target, w.task, i + 1, value])
    path.write_text(_csv(rows, delimiter), encoding="utf-8", newline="")
    return path


def write_rdes(path: Path, wells: list[Well]) -> Path:
    """An RDES amplification table (seven fixed columns, then one column per cycle)."""
    n = len(wells[0].fluor)
    rows: list[list[object]] = [["Well", "Sample", "Sample Type", "Target", "Target Type",
                                 "Dye", "Cq", *range(1, n + 1)]]  # fmt: skip
    kind = {"Unkn": "unkn", "Std": "std", "NTC": "ntc"}
    for w in wells:
        rows.append([w.well, w.sample or w.well, kind[w.task], w.target, "toi", w.dye,
                     -1 if w.cq is None else w.cq, *w.fluor])  # fmt: skip
    path.write_text(_csv(rows, "\t"), encoding="utf-8", newline="")
    return path


def write_lc480(path: Path, wells: list[Well]) -> Path:
    """A LightCycler 480 text export (one amplification program, selected filter 465-510)."""
    lines = [
        "Experiment: run1  Selected Filter: SYBR Green I / HRM Dye (465-510)",
        "\t".join(["SamplePos", "SampleName", "Prog", "Seg", "Cycle", "Time", "Temp", "465-510"]),
    ]
    for w in wells:
        for i, f in enumerate(w.fluor):
            lines.append("\t".join([w.well, w.sample, "2", "3", str(i + 1), str(60 * i),
                                    "72.00", f"{f / 100:.4f}"]))  # fmt: skip
    path.write_text("\r\n".join(lines) + "\r\n", encoding="cp1252", newline="")
    return path
