"""Synthetic melt curves with known products, and real melt files of the corpus, for the tests.

A product that melts at ``tm`` is a smooth step down in fluorescence (half of it melted at
``tm``: an error-function step of width ``sigma``), so its −dF/dT is a Gaussian peak centred
exactly on ``tm``, of height proportional to ``amount / sigma``. The dye's own fluorescence falls
slowly with temperature (a linear background), which adds a constant to −dF/dT.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from functools import cache
from pathlib import Path

import numpy as np

from qpilot.qpcr.melt import MeltCurve, MeltData, MeltSettings, analyse_curve

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"
HSIEH = CORPUS / "biorad" / "hsieh2016-cfx-manager-3.1-sybr"
RPA = CORPUS / "rdml" / "cfx-manager-3.0-rdml-1.2-rpa" / "rpa.rdml"
LC96P = CORPUS / "rdml" / "lightcycler96-lc96p-hmuy" / "hmuy_hm_vs_dip_r123.lc96p"
MCA = Path(__file__).resolve().parents[1] / "fixtures" / "test_mca_1_raw_data.rdml"
GAPDH = "2016-09-04 gapdh"
INHIBITION = "admin_2016-09-04 16-12-03_CC011664"


def readings(
    products: Iterable[tuple[float, float]] = ((84.0, 1.0),),
    *,
    lo: float = 65.0,
    hi: float = 95.0,
    step: float = 0.5,
    sigma: float = 0.8,
    base: float = 10_000.0,
    slope: float = 0.004,
    noise: float = 0.0,
    seed: int = 0,
) -> tuple[list[float], list[float]]:
    """Temperatures and fluorescence of a melt with ``(tm, amount)`` products."""
    t = np.arange(lo, hi + step / 2, step)
    f = base * (1.0 - slope * (t - lo))
    for tm, amount in products:
        step_down = [math.erfc((x - tm) / (sigma * math.sqrt(2))) for x in t]
        f = f + amount * base * 0.5 * np.array(step_down)
    if noise:
        f = f + np.random.default_rng(seed).normal(0.0, noise * base, len(t))
    return [float(x) for x in t], [float(y) for y in f]


def curve(
    well: str,
    products: Iterable[tuple[float, float]] = ((84.0, 1.0),),
    *,
    plate: str = "P",
    target: str = "T",
    sample: str = "S",
    **kw,
) -> MeltCurve:
    t, f = readings(products, **kw)
    return MeltCurve(plate, well, target, sample, tuple(t), tuple(f))


def melt_data(
    curves: Iterable[MeltCurve],
    declared_tm: Mapping[str, float] | None = None,
    chemistry: Mapping[str, str] | None = None,
    settings: MeltSettings | None = None,
) -> MeltData:
    settings = settings or MeltSettings()
    wells = {(c.run_id, c.well, c.target): analyse_curve(c, settings) for c in curves}
    return MeltData(
        wells=wells,
        plates=tuple(dict.fromkeys(c.run_id for c in curves)),
        declared_tm=dict(declared_tm or {}),
        chemistry=dict(chemistry or {}),
        settings=settings,
    )


@cache
def hsieh_rdml(folder: str) -> Path:
    """The hsieh2016 CFX export (every file) as qPilot's RDML, written once per test session."""
    from qpilot.io.connectors import capture, write_rdml

    files = sorted(p for p in HSIEH.iterdir() if p.is_file() and p.name != "MANIFEST.yaml")
    return write_rdml(capture(files), Path(folder) / "hsieh2016.rdml")
