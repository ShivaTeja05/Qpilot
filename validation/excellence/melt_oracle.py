"""A product's melting temperature found two other ways, from the instrument's own files.

* From the instrument's derivative: CFX Manager writes its own −dF/dT ("Melt Curve Derivative
  Results"); the top of the parabola through its three highest readings is the instrument's Tm
  between readings.
* From the raw readings (CFX "Melt Curve RFU Results") by a different smoother than qPilot's
  Savitzky-Golay: a cubic smoothing spline (``scipy.interpolate.make_smoothing_spline``, its
  smoothing chosen by generalised cross-validation), differentiated analytically; the Tm is the
  derivative's maximum on a 0.01 °C grid (Ririe, Rasmussen & Wittwer, Anal Biochem 1997).

Both read the CSV files with the ``csv`` module, not with qPilot's connectors.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
from scipy.interpolate import make_smoothing_spline


def _table(path: Path) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    header = rows[0]
    col = header.index("Temperature")
    temps = np.array([float(r[col]) for r in rows[1:]])
    wells = {}
    for j, name in enumerate(header):
        if j <= col or not name:
            continue
        label = f"{name[0]}{int(name[1:])}"
        wells[label] = np.array([float(r[j]) for r in rows[1:]])
    return temps, wells


def vertex_tm(t: np.ndarray, d: np.ndarray) -> float:
    """The top of the parabola through the highest reading of ``d`` and its two neighbours."""
    p = int(np.argmax(d[1:-1])) + 1
    a, b, c = d[p - 1], d[p], d[p + 1]
    den = a - 2 * b + c
    step = float(t[p + 1] - t[p])
    return float(t[p] + (0.5 * (a - c) / den) * step) if den < 0 else float(t[p])


def instrument_tm(derivative_csv: str | Path) -> dict[str, float]:
    """Well -> Tm from the instrument's own −dF/dT file."""
    t, wells = _table(Path(derivative_csv))
    return {w: vertex_tm(t, d) for w, d in wells.items()}


def spline_tm(rfu_csv: str | Path) -> dict[str, float]:
    """Well -> Tm from a smoothing spline of the raw readings."""
    t, wells = _table(Path(rfu_csv))
    fine = np.arange(t[0] + 1.0, t[-1] - 1.0, 0.01)  # away from the ends, as any smoother
    out = {}
    for w, f in wells.items():
        spline = make_smoothing_spline(t, f)
        d = -spline.derivative()(fine)
        out[w] = float(fine[int(np.argmax(d))])
    return out
