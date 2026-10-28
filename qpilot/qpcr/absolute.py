"""Absolute quantification: standard curves, LOD and LOQ, and the quantity of every unknown.

Relative quantification (the rest of the engine) compares a gene between groups; this module
answers "how much was there": copies (or whatever unit the standards were declared in) per
reaction, from a dilution series of known quantity measured on the same plate.

**Standard curves.** Per assay (target) and plate: ordinary least squares of the engine's Cq on
``log10`` quantity over the standard wells that were detected (below), giving slope, intercept,
R², the residual SD, the amplification efficiency ``10^(-1/slope) - 1`` with a 95 % confidence
interval from the slope's t interval, every point's residual and each standard's own
back-calculated quantity. A fit needs :data:`MIN_LEVELS` distinct quantities (as the Run Gate's
G-STD and the efficiency axis) and a falling line. When the same series (the same set of
quantities) is on several plates of one assay, a curve **pooled** over those plates is fitted
too and named as such; an unknown on a plate with its own curve is always read from its own
plate's curve, and only a plate without standards for its assay reads from the pooled curve
(or from the one other plate that has a curve), which its flags say.

**Which wells.** The engine's Cq and its exclusions: a well a person excluded is left out of
everything; a well counts as **detected** when it has a Cq and LinRegPCR called it amplified (or
gave it a quantity), under the study's primary amplification rule (a Cq cut-off applies) and a
person's well calls. Nothing is dropped by this module: a standard level that should not be on
the curve is left out by a person (``curve.exclude_well``), never by qPilot.

**Quantities of the standards.** A person's (``design.dilution_series``, the Design page) over
the file's declared quantity (RDML ``<quantity>``) over a ``STD_<number>`` sample name; the
source is reported.

**LOD** (limit of detection): the lowest standard level detected in at least
:data:`LOD_RATE` (95 %) of its wells, every higher level included (Forootan et al. 2017;
MIQE, Bustin et al. 2009). With three or more levels and at least one partly detected level, a
logistic fit of detection on ``log10`` quantity gives a modelled 95 % LOD as well (Forootan et
al. 2017); it is shown, the empirical one is the one flags use. When every level was detected
the LOD is at or below the lowest standard, and said so.

**LOQ** (limit of quantification): the lowest standard level, at or above the LOD, whose
back-calculated quantities have a coefficient of variation of at most :data:`LOQ_CV` (35 %),
every higher level included. The CV is the log-normal one, ``sqrt(exp(SD_ln^2) - 1)`` with
``SD_ln`` the SD of the natural log of the back-calculated quantities (equivalently of Cq times
``ln(1 + E)``), as Forootan et al. 2017 recommend for qPCR, where quantities are log-normal.
35 % is a lab-editable default, not a law.

**Unknowns.** Inverse prediction from the mean Cq of the ``k`` detected wells of a biological
unit (technical replicates, and the samples of one unit, are averaged as the engine averages
``log2 N0``), with the classical 95 % prediction interval of calibration (Miller & Miller,
*Statistics and Chemometrics for Analytical Chemistry*, eq. 5.9; Draper & Smith, *Applied
Regression Analysis*, inverse prediction)::

    x0 = (y0 - b) / m
    s_x0 = (s_yx / |m|) * sqrt(1/k + 1/n + (y0 - y_mean)^2 / (m^2 * Sxx))
    x0 +- t(0.975, n - 2) * s_x0           (on log10 quantity)

A unit whose wells were read from several curves gets the mean of the per-curve ``log10``
estimates and ``sqrt(sum s_i^2) / N`` (independent curves; t with the smallest degrees of
freedom). Flags in plain words: above the top standard or below the lowest (extrapolated),
below the LOQ, below the LOD, not detected, some wells not detected, read from another plate's
curve. With the reaction's template volume and input amount (``StudyDesign.reaction_input``,
absent by default) each quantity is also given per µL of template and per ng of input.

**ng to copies** (:func:`copies_from_mass`), for preparing standards: copies = mass (g) ×
Avogadro / molar mass, with the molar mass of dsDNA ``bp × 617.96 + 36.04``, ssDNA
``nt × 308.97 + 18.02`` and ssRNA ``nt × 320.5 + 159.0`` g/mol (Thermo Fisher's "DNA and RNA
molecular weights and conversions").

Deterministic: no model, no network; every number comes from the per-well table.
"""

from __future__ import annotations

import math
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cached_property, lru_cache
from typing import Any, Literal

import numpy as np
import pandas as pd
from scipy import stats

from qpilot.qpcr.amp_call import amplified
from qpilot.qpcr.quant import EXCLUDED, unit_map

MIN_LEVELS = 3  # as G-STD and the efficiency axis: R² and linearity mean nothing with two
LOD_RATE = 0.95  # Forootan et al. 2017; MIQE (Bustin et al. 2009)
LOQ_CV = 0.35  # Forootan et al. 2017 use 35 %; lab-editable default
PI_LEVEL = 0.95
BAND_POINTS = 41
FLAT_SLOPE = -1.0  # a slope above this (E > 900 %): the Cq does not follow the quantity
EFFICIENCY_RANGE = (0.90, 1.10)  # MIQE (Bustin et al. 2009); as the Run Gate's G-STD
R2_MIN = 0.98  # as G-STD
AVOGADRO = 6.02214076e23  # mol^-1, exact (SI 2019)
METHOD_CARD_PATH = "methods/absolute_quantification.md"
POOLED = "pooled"

Kind = Literal["dsDNA", "ssDNA", "RNA"]
#: Molar mass per base (pair) and the ends' addition, g/mol (Thermo Fisher conversions).
MOLAR_MASS: dict[str, tuple[float, float]] = {
    "dsDNA": (617.96, 36.04),
    "ssDNA": (308.97, 18.02),
    "RNA": (320.5, 159.0),
}
KIND_WORDS = {
    "dsDNA": "double-stranded DNA (a plasmid, PCR product or gBlock)",
    "ssDNA": "single-stranded DNA (an oligo)",
    "RNA": "single-stranded RNA (an in vitro transcript)",
}
#: RDML quantity units in words (RDML 1.3 ``quantityUnit``).
UNIT_WORDS = {
    "cop": "copies",
    "fold": "fold (relative)",
    "dil": "dilution (relative)",
    "ng": "ng",
    "nmol": "nmol",
    "nMol": "nmol",
    "other": "",
}
_STD_NAME = re.compile(r"(?i)^\s*std[\s_-]*(\d+(?:\.\d+)?(?:e[+-]?\d+)?)\s*$")

REFERENCES = (
    "Forootan A, Sjöback R, Björkman J, Sjögreen B, Linz L, Kubista M. Methods to determine "
    "limit of detection and limit of quantification in quantitative real-time PCR (qPCR). "
    "Biomol Detect Quantif. 2017;12:1-6. doi:10.1016/j.bdq.2017.04.001",
    "Bustin SA, Benes V, Garson JA, et al. The MIQE guidelines: minimum information for "
    "publication of quantitative real-time PCR experiments. Clin Chem. 2009;55(4):611-622. "
    "doi:10.1373/clinchem.2008.112797",
    "Miller JN, Miller JC. Statistics and Chemometrics for Analytical Chemistry, 6th ed. "
    "Pearson; 2010. Section 5.6 (inverse prediction from a calibration line)",
    "Thermo Fisher Scientific. DNA and RNA molecular weights and conversions (reference "
    "information).",
)

FLAG_WORDS: dict[str, str] = {
    "above_top": "above the top standard: extrapolated beyond the curve",
    "below_lowest": "below the lowest standard: extrapolated beyond the curve",
    "below_loq": "below the limit of quantification: detected, but the number is not precise",
    "below_lod": "below the limit of detection",
    "not_detected": "not detected in any well",
    "some_not_detected": "some wells were not detected; the quantity is from the detected ones",
    "other_plate": "read from another plate's curve: this plate has no standards for this assay",
    "several_curves": "wells on several plates: the mean of each plate's estimate",
}


class AbsoluteError(ValueError):
    """A quantity cannot be computed (the message says why, in plain words)."""


# ---------------------------------------------------------------------------------------------
# ng -> copies
# ---------------------------------------------------------------------------------------------


def molar_mass(length: float, kind: str = "dsDNA") -> float:
    """g/mol of one molecule of ``length`` bases (dsDNA: base pairs)."""
    if kind not in MOLAR_MASS:
        raise AbsoluteError(f"kind must be one of {', '.join(MOLAR_MASS)}, not {kind!r}")
    if not (length > 0 and math.isfinite(length)):
        raise AbsoluteError("the length must be a positive number of bases (or base pairs)")
    per_base, ends = MOLAR_MASS[kind]
    return float(length) * per_base + ends


def copies_from_mass(ng: float, length: float, kind: str = "dsDNA") -> float:
    """Copies in ``ng`` nanograms of a molecule ``length`` bases long (dsDNA: base pairs)."""
    if not (ng > 0 and math.isfinite(ng)):
        raise AbsoluteError("the mass must be a positive number of ng")
    return float(ng) * 1e-9 * AVOGADRO / molar_mass(length, kind)


def mass_from_copies(copies: float, length: float, kind: str = "dsDNA") -> float:
    """Ng that hold ``copies`` molecules ``length`` bases long."""
    if not (copies > 0 and math.isfinite(copies)):
        raise AbsoluteError("the number of copies must be positive")
    return float(copies) * molar_mass(length, kind) / AVOGADRO * 1e9


def dilution_levels(top: float, step: float, levels: int) -> list[float]:
    """The quantities of a serial dilution: ``top``, ``top/step``, ... (``levels`` values)."""
    if not (top > 0 and math.isfinite(top)):
        raise AbsoluteError("the top quantity must be positive")
    if not (step > 1 and math.isfinite(step)):
        raise AbsoluteError("the dilution step must be more than 1 (10 for a ten-fold series)")
    if not 1 <= levels <= 24:
        raise AbsoluteError("a series has between 1 and 24 levels")
    return [float(top) / float(step) ** i for i in range(int(levels))]


# ---------------------------------------------------------------------------------------------
# The line and its inverse prediction
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Fit:
    """Cq = intercept + slope · log10(quantity), by ordinary least squares."""

    n: int
    slope: float
    intercept: float
    r2: float
    s_yx: float  # residual SD (n - 2 degrees of freedom)
    x_mean: float
    y_mean: float
    sxx: float
    x_min: float
    x_max: float

    @property
    def df(self) -> int:
        """Residual degrees of freedom."""
        return self.n - 2

    @property
    def t_crit(self) -> float:
        """t(0.975, n - 2)."""
        return _t_crit(self.df) if self.df > 0 else math.nan

    @property
    def se_slope(self) -> float:
        """Standard error of the slope."""
        return self.s_yx / math.sqrt(self.sxx) if self.sxx > 0 else math.nan

    @property
    def se_intercept(self) -> float:
        """Standard error of the intercept."""
        return self.s_yx * math.sqrt(1 / self.n + self.x_mean**2 / self.sxx)

    @property
    def efficiency(self) -> float:
        """``10^(-1/slope) - 1``: 1.0 is a perfect doubling (100 %)."""
        return 10 ** (-1 / self.slope) - 1

    @property
    def efficiency_ci(self) -> tuple[float, float]:
        """95 % interval of the efficiency, from the slope's t interval (NaN if it crosses 0)."""
        half = self.t_crit * self.se_slope
        bounds = []
        for s in (self.slope - half, self.slope + half):
            bounds.append(10 ** (-1 / s) - 1 if s < 0 else math.nan)
        low, high = sorted(bounds) if all(math.isfinite(b) for b in bounds) else bounds
        return float(low), float(high)

    def cq_at(self, x: float | np.ndarray) -> float | np.ndarray:
        """The line's Cq at ``log10`` quantity ``x``."""
        return self.intercept + self.slope * x

    def back(self, cq: float | np.ndarray) -> float | np.ndarray:
        """``log10`` quantity read back from a Cq."""
        return (cq - self.intercept) / self.slope

    def inverse(self, y0: float, k: int) -> tuple[float, float]:
        """``(x0, s_x0)``: ``log10`` quantity of a mean Cq of ``k`` wells and its SD."""
        x0 = (y0 - self.intercept) / self.slope
        inner = 1 / k + 1 / self.n + (y0 - self.y_mean) ** 2 / (self.slope**2 * self.sxx)
        return float(x0), float(self.s_yx / abs(self.slope) * math.sqrt(inner))

    def band(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """``(cq, low, high)``: the line and the 95 % prediction band of one new well's Cq."""
        y = self.cq_at(x)
        half = self.t_crit * self.s_yx * np.sqrt(1 + 1 / self.n + (x - self.x_mean) ** 2 / self.sxx)
        return y, y - half, y + half


def fit_line(x: Sequence[float], y: Sequence[float]) -> Fit | None:
    """OLS of ``y`` on ``x``; ``None`` with fewer than three points or no spread in ``x``."""
    xs, ys = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    n = len(xs)
    if n < 3:
        return None
    xm, ym = float(xs.mean()), float(ys.mean())
    sxx = float(((xs - xm) ** 2).sum())
    if sxx <= 0:
        return None
    slope = float(((xs - xm) * (ys - ym)).sum() / sxx)
    intercept = ym - slope * xm
    resid = ys - (intercept + slope * xs)
    sse = float((resid**2).sum())
    syy = float(((ys - ym) ** 2).sum())
    return Fit(
        n=n,
        slope=slope,
        intercept=intercept,
        r2=1 - sse / syy if syy > 0 else math.nan,
        s_yx=math.sqrt(sse / (n - 2)),
        x_mean=xm,
        y_mean=ym,
        sxx=sxx,
        x_min=float(xs.min()),
        x_max=float(xs.max()),
    )


def lognormal_cv(log10_values: Sequence[float]) -> float:
    """CV of log-normal values from their ``log10``: ``sqrt(exp(SD_ln^2) - 1)``; NaN below 2."""
    values = np.asarray(log10_values, dtype=float)
    if len(values) < 2:
        return math.nan
    sd_ln = float(np.std(values, ddof=1)) * math.log(10)
    return math.sqrt(math.expm1(sd_ln**2))


def logistic_fit(x: Sequence[float], detected: Sequence[bool]) -> tuple[float, float] | None:
    """Maximum-likelihood logistic regression ``P(detect) = 1/(1+exp(-(a + b x)))``.

    Newton-Raphson (IRLS) from zero; ``None`` when it does not converge or the data separate
    (detection jumps from none to all between two levels: no slope can be estimated).
    """
    xs = np.asarray(x, dtype=float)
    ys = np.asarray(detected, dtype=float)
    design = np.column_stack([np.ones_like(xs), xs])
    beta = np.zeros(2)
    for _ in range(100):
        eta = design @ beta
        p = 1 / (1 + np.exp(-eta))
        w = p * (1 - p)
        if w.min() < 1e-12:
            return None
        hessian = design.T @ (design * w[:, None])
        try:
            step = np.linalg.solve(hessian, design.T @ (ys - p))
        except np.linalg.LinAlgError:
            return None
        beta = beta + step
        if np.abs(beta).max() > 60:
            return None
        if np.abs(step).max() < 1e-10:
            return float(beta[0]), float(beta[1])
    return None


# ---------------------------------------------------------------------------------------------
# What the module returns
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AbsoluteSettings:
    """The thresholds, shown wherever they are used."""

    lod_rate: float = LOD_RATE
    loq_cv: float = LOQ_CV
    min_levels: int = MIN_LEVELS


@dataclass(frozen=True)
class ReactionInputs:
    """What one reaction held (``StudyDesign.reaction_input``): per µL and per ng factors."""

    template_ul: float | None = None
    input_ng: float | None = None
    unit: str | None = None


@dataclass(frozen=True)
class StandardPoint:
    """One standard well on a curve (detected or not)."""

    run_id: str
    well: str
    sample: str
    quantity: float
    cq: float | None
    detected: bool
    residual: float | None = None  # Cq minus the line, detected wells only
    back_quantity: float | None = None  # read back from the curve


@dataclass(frozen=True)
class Level:
    """One standard level: detection rate and how well its quantity is read back."""

    quantity: float
    n_wells: int
    n_detected: int
    mean_cq: float | None
    sd_cq: float | None
    back_quantity: float | None  # 10^(mean log10 back-calculated)
    cv: float | None  # log-normal CV of the back-calculated quantities

    @property
    def rate(self) -> float:
        """Share of the level's wells detected."""
        return self.n_detected / self.n_wells if self.n_wells else math.nan


@dataclass(frozen=True)
class Limit:
    """An LOD or LOQ: the quantity (``None`` if not determined), how, and in words."""

    quantity: float | None
    method: str  # "empirical", "logistic", "lowest_standard", "not_determined"
    words: str
    at_most: bool = False  # every level passed: the true limit is at or below the lowest


@dataclass(frozen=True)
class StandardCurve:
    """One assay's standard curve on one plate (or pooled over plates with the same series)."""

    id: str
    target: str
    scope: Literal["plate", "pooled"]
    runs: tuple[str, ...]
    fit: Fit | None
    points: tuple[StandardPoint, ...]
    levels: tuple[Level, ...]
    lod: Limit
    lod_model: Limit | None
    loq: Limit
    quantity_source: str  # "design", "file", "name" or a mix joined with "+"
    unit: str
    problem: str = ""  # why there is no fit, in words
    warnings: tuple[str, ...] = ()  # what MIQE would question about the fit, in words

    @cached_property
    def top(self) -> float | None:
        """The highest standard quantity on the curve (detected)."""
        used = [p.quantity for p in self.points if p.detected]
        return max(used) if used else None

    @cached_property
    def lowest(self) -> float | None:
        """The lowest standard quantity on the curve (detected)."""
        used = [p.quantity for p in self.points if p.detected]
        return min(used) if used else None

    def band(self, points: int = BAND_POINTS) -> list[tuple[float, float, float, float]]:
        """``(log10 q, cq, low, high)`` along the curve (a little beyond the standards)."""
        if self.fit is None:
            return []
        span = self.fit.x_max - self.fit.x_min
        xs = np.linspace(self.fit.x_min - 0.1 * span, self.fit.x_max + 0.1 * span, points)
        y, low, high = self.fit.band(xs)
        return [
            (float(a), float(b), float(c), float(d))
            for a, b, c, d in zip(xs, y, low, high, strict=True)
        ]


@dataclass(frozen=True)
class UnknownWell:
    """One study well of an unknown: its Cq and whether it was detected."""

    run_id: str
    well: str
    sample: str
    cq: float | None
    detected: bool
    curve: str | None
    quantity: float | None  # this well alone, read from its curve


@dataclass(frozen=True)
class UnknownEstimate:
    """One biological unit's quantity of one assay, with its 95 % prediction interval."""

    unit: str
    target: str
    samples: tuple[str, ...]
    wells: tuple[UnknownWell, ...]
    curves: tuple[str, ...]
    n_wells: int
    n_detected: int
    mean_cq: float | None
    log10_quantity: float | None
    log10_low: float | None
    log10_high: float | None
    flags: tuple[str, ...]
    per_ul: float | None = None
    per_ng: float | None = None

    @property
    def quantity(self) -> float | None:
        """Per reaction, in the standards' unit."""
        return None if self.log10_quantity is None else 10**self.log10_quantity

    @property
    def low(self) -> float | None:
        """Lower end of the 95 % prediction interval."""
        return None if self.log10_low is None else 10**self.log10_low

    @property
    def high(self) -> float | None:
        """Upper end of the 95 % prediction interval."""
        return None if self.log10_high is None else 10**self.log10_high


@dataclass(frozen=True)
class Absolute:
    """Every standard curve and every unknown's quantity of one study (or file)."""

    curves: tuple[StandardCurve, ...]
    unknowns: tuple[UnknownEstimate, ...]
    unit: str
    settings: AbsoluteSettings
    reaction: ReactionInputs | None = None
    not_quantified: dict[str, str] = field(default_factory=dict)  # target -> why

    @property
    def targets(self) -> list[str]:
        """Assays with a standard curve or a reason why not, in name order."""
        return sorted({c.target for c in self.curves} | set(self.not_quantified))

    def curve(self, curve_id: str) -> StandardCurve:
        """One curve by id.

        Raises:
            KeyError: No such curve.
        """
        for c in self.curves:
            if c.id == curve_id:
                return c
        raise KeyError(curve_id)

    def for_target(self, target: str) -> tuple[list[StandardCurve], list[UnknownEstimate]]:
        """One assay's curves and unknowns."""
        return (
            [c for c in self.curves if c.target == target],
            [u for u in self.unknowns if u.target == target],
        )


# ---------------------------------------------------------------------------------------------
# Inputs: which wells are detected, what each standard's quantity is
# ---------------------------------------------------------------------------------------------


def detected_wells(
    table: pd.DataFrame, rule_id: str = "linregpcr", calls: Mapping[str, bool] | None = None
) -> pd.Series:
    """Whether each well counts as detected: a Cq, LinRegPCR's call, the rule, a person's call.

    LinRegPCR's own amplification call or a quantity from it marks a signal; the study's primary
    amplification rule (a Cq cut-off, the Curve Judge) and a person's well calls then apply as
    they do to relative quantities (:func:`qpilot.qpcr.amp_call.amplified`).
    """
    has_cq = table["cq"].notna()
    called = table["amplification"].eq(True) if "amplification" in table.columns else False
    signal = has_cq & (table["n0"].notna() | called)
    probe = table.assign(n0=np.where(signal, 1.0, np.nan))
    return amplified(probe, rule_id, calls) & has_cq


def name_quantity(sample: str) -> float | None:
    """A standard's quantity from a ``STD_<number>`` name, else ``None``."""
    match = _STD_NAME.match(str(sample))
    return float(match.group(1)) if match else None


def standard_quantities(
    table: pd.DataFrame,
    quantities: Mapping[str, float] | None = None,
    declared: Mapping[tuple[str, str], tuple[float, str]] | None = None,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Per standard well: ``(quantity, source, unit)`` (NaN / "" where none is known).

    The design's quantity (a person) over the file's declared quantity for the sample and
    target (or for the sample) over a ``STD_<number>`` name.
    """
    quantities = quantities or {}
    declared = declared or {}
    values, sources, units = [], [], []
    for sample, target in zip(
        table["sample"].astype(str), table["target"].astype(str), strict=True
    ):
        q, source, unit = math.nan, "", ""
        given = quantities.get(sample)
        filed = declared.get((sample, target)) or declared.get((sample, ""))
        if given is not None and given > 0:
            q, source = float(given), "design"
            unit = filed[1] if filed else ""
        elif filed is not None and filed[0] > 0:
            q, source, unit = float(filed[0]), "file", str(filed[1] or "")
        else:
            named = name_quantity(sample)
            if named is not None and named > 0:
                q, source = named, "name"
        values.append(q)
        sources.append(source)
        units.append(unit)
    index = table.index
    return (
        pd.Series(values, index=index, dtype=float),
        pd.Series(sources, index=index, dtype=object),
        pd.Series(units, index=index, dtype=object),
    )


# ---------------------------------------------------------------------------------------------
# One curve
# ---------------------------------------------------------------------------------------------


def _levels(points: Sequence[StandardPoint], fit: Fit | None) -> tuple[Level, ...]:
    by_q: dict[float, list[StandardPoint]] = {}
    for p in points:
        by_q.setdefault(p.quantity, []).append(p)
    out = []
    for q in sorted(by_q, reverse=True):
        wells = by_q[q]
        cqs = [p.cq for p in wells if p.detected and p.cq is not None]
        back = [float(fit.back(c)) for c in cqs] if fit is not None else []
        out.append(
            Level(
                quantity=q,
                n_wells=len(wells),
                n_detected=len(cqs),
                mean_cq=float(np.mean(cqs)) if cqs else None,
                sd_cq=float(np.std(cqs, ddof=1)) if len(cqs) >= 2 else None,
                back_quantity=float(10 ** np.mean(back)) if back else None,
                cv=lognormal_cv(back) if len(back) >= 2 else None,
            )
        )
    return tuple(out)


def _lod(levels: Sequence[Level], settings: AbsoluteSettings) -> Limit:
    """The lowest level detected in >= 95 % of its wells, every higher level included."""
    if not levels:
        return Limit(None, "not_determined", "no standard levels")
    passed = None
    for level in levels:  # highest quantity first
        if level.n_wells and level.rate >= settings.lod_rate:
            passed = level
        else:
            break
    rate = pct(settings.lod_rate)
    if passed is None:
        return Limit(
            None,
            "not_determined",
            f"the top standard was detected in fewer than {rate} of its wells, so the limit of "
            "detection is above every standard",
        )
    if passed is levels[-1]:
        return Limit(
            passed.quantity,
            "lowest_standard",
            f"every standard level was detected in at least {rate} of its wells: the limit of "
            "detection is at or below the lowest standard",
            at_most=True,
        )
    return Limit(
        passed.quantity,
        "empirical",
        f"the lowest standard detected in at least {rate} of its wells (every higher level too)",
    )


def _lod_model(points: Sequence[StandardPoint], settings: AbsoluteSettings) -> Limit | None:
    """The logistic 95 % LOD, when three or more levels and one partly detected allow it."""
    levels = sorted({p.quantity for p in points})
    if len(levels) < MIN_LEVELS:
        return None
    rates = {}
    for q in levels:
        wells = [p for p in points if p.quantity == q]
        rates[q] = sum(p.detected for p in wells) / len(wells)
    if not any(0 < r < 1 for r in rates.values()):
        return None
    fitted = logistic_fit([math.log10(p.quantity) for p in points], [p.detected for p in points])
    rate = pct(settings.lod_rate)
    if fitted is None or fitted[1] <= 0:
        return Limit(
            None,
            "not_determined",
            "a logistic fit of detection on quantity did not converge (detection jumps from "
            "none to all between two levels); use the empirical limit",
        )
    a, b = fitted
    x95 = (math.log(settings.lod_rate / (1 - settings.lod_rate)) - a) / b
    words = f"modelled: the quantity detected with {rate} probability (logistic fit on log10 "
    words += "quantity over every standard well)"
    if x95 < math.log10(levels[0]):
        words += "; below the lowest standard, so extrapolated"
    return Limit(float(10**x95), "logistic", words)


def _loq(levels: Sequence[Level], lod: Limit, settings: AbsoluteSettings) -> Limit:
    """The lowest level at or above the LOD whose back-calculated CV is <= 35 %."""
    cv = pct(settings.loq_cv)
    if lod.quantity is None:
        return Limit(None, "not_determined", "no limit of detection, so no limit of quantification")
    passed = None
    for level in levels:  # highest first
        if level.quantity < lod.quantity:
            break
        if level.cv is not None and level.cv <= settings.loq_cv:
            passed = level
        else:
            break
    if passed is None:
        return Limit(
            None,
            "not_determined",
            f"the top standard's back-calculated quantities vary by more than {cv} (CV), or it "
            "has fewer than two detected wells",
        )
    return Limit(
        passed.quantity,
        "empirical",
        f"the lowest standard (at or above the limit of detection) whose back-calculated "
        f"quantities have a CV of at most {cv} (every higher level too)",
    )


def _curve(
    curve_id: str,
    target: str,
    scope: Literal["plate", "pooled"],
    runs: Sequence[str],
    rows: pd.DataFrame,
    settings: AbsoluteSettings,
) -> StandardCurve:
    """One curve from its standard wells (columns ``abs_q``, ``abs_det``, ``abs_source``...)."""
    det = rows["abs_det"].to_numpy(dtype=bool)
    x = np.log10(rows["abs_q"].to_numpy(dtype=float))
    y = rows["cq"].to_numpy(dtype=float)
    levels_used = len(np.unique(x[det]))
    fit, problem = None, ""
    if levels_used < settings.min_levels:
        problem = (
            f"{levels_used} standard level(s) detected; a curve needs at least "
            f"{settings.min_levels}"
        )
    else:
        fit = fit_line(x[det], y[det])
        if fit is None or not fit.slope < 0:
            problem = "the standards' Cq does not fall as the quantity rises, so there is no curve"
            fit = None
        elif fit.slope > FLAT_SLOPE:
            problem = (
                f"the standards' Cq barely changes with the quantity (slope {fit.slope:.2f} "
                "cycles per ten-fold): this assay does not measure the standards' template "
                "(an internal or spike-in control?), so there is no curve"
            )
            fit = None
    points = []
    for i, row in enumerate(rows.itertuples(index=False)):
        cq = None if pd.isna(row.cq) else float(row.cq)
        residual = back = None
        if fit is not None and det[i] and cq is not None:
            residual = cq - float(fit.cq_at(x[i]))
            back = float(10 ** fit.back(cq))
        points.append(
            StandardPoint(
                run_id=str(row.run_id),
                well=str(row.well),
                sample=str(row.sample),
                quantity=float(row.abs_q),
                cq=cq,
                detected=bool(det[i]),
                residual=residual,
                back_quantity=back,
            )
        )
    levels = _levels(points, fit)
    lod = _lod(levels, settings)
    sources = "+".join(sorted(set(rows["abs_source"]) - {""})) or "name"
    units = sorted(set(rows["abs_unit"]) - {""})
    warnings = []
    if fit is not None:
        low, high = EFFICIENCY_RANGE
        if not low <= fit.efficiency <= high:
            warnings.append(
                f"efficiency {pct(fit.efficiency, 1)} is outside {pct(low)} to {pct(high)} (MIQE)"
            )
        if not fit.r2 >= R2_MIN:
            warnings.append(f"R² {fit.r2:.3f} is below {R2_MIN:g} (MIQE)")
    return StandardCurve(
        id=curve_id,
        target=target,
        scope=scope,
        runs=tuple(runs),
        fit=fit,
        points=tuple(points),
        levels=levels,
        lod=lod,
        lod_model=_lod_model(points, settings),
        loq=_loq(levels, lod, settings),
        quantity_source=sources,
        unit=UNIT_WORDS.get(units[0], units[0]) if len(units) == 1 else "",
        problem=problem,
        warnings=tuple(warnings),
    )


def _level_labels(std: pd.DataFrame) -> dict[str, str]:
    """Assays whose standards' only quantities are names numbering the levels (``Std 1``...).

    ``STD_150000`` names a quantity; ``Std 1`` to ``Std 5`` number the levels of a series. When
    every quantity of an assay's standards comes from the name and they are exactly 1 to n,
    they are level numbers, never quantities.
    """
    out = {}
    for target, rows in std.groupby(std["target"].astype(str)):
        if rows.empty or set(rows["abs_source"]) != {"name"}:
            continue
        values = sorted(set(rows["abs_q"].dropna()))
        if len(values) >= 2 and values == [float(i) for i in range(1, len(values) + 1)]:
            names = sorted(set(rows["sample"].astype(str)), key=lambda n: (len(n), n))
            out[str(target)] = f"{names[0]} to {names[-1]}"
    return out


def curve_id(target: str, run_id: str) -> str:
    """``<target> @ <run>``, or ``<target> @ pooled``."""
    return f"{target} @ {run_id}"


# ---------------------------------------------------------------------------------------------
# The whole study
# ---------------------------------------------------------------------------------------------


def quantify(
    table: pd.DataFrame,
    *,
    quantities: Mapping[str, float] | None = None,
    declared: Mapping[tuple[str, str], tuple[float, str]] | None = None,
    units: Mapping[str, str] | None = None,
    rule_id: str = "linregpcr",
    calls: Mapping[str, bool] | None = None,
    reaction: ReactionInputs | None = None,
    settings: AbsoluteSettings | None = None,
    targets: Collection[str] | None = None,
) -> Absolute:
    """Every standard curve of the table and every unknown unit's quantity.

    Args:
        table: The per-well table with the design applied
            (:func:`qpilot.qpcr.designs.design_curves`): ``run_id``, ``well``, ``sample``,
            ``sample_type``, ``target``, ``cq``, ``n0``, ``amplification`` and optionally
            ``design_excluded``.
        quantities: The design's standard quantities (sample -> quantity).
        declared: The file's declared quantities: ``(sample, target) -> (value, unit)`` (target
            ``""`` for every target).
        units: Sample -> biological unit (samples not listed are their own unit).
        rule_id: The study's primary amplification rule.
        calls: A person's well calls (``run_id/well`` -> amplified).
        reaction: The reaction's template volume and input amount (per µL / per ng).
        settings: LOD rate, LOQ CV, minimum levels.
        targets: Only these assays (default: every assay with a standard quantity).
    """
    settings = settings or AbsoluteSettings()
    work = table
    if EXCLUDED in work.columns:
        work = work[~work[EXCLUDED].astype(bool)]
    work = work.assign(abs_det=detected_wells(work, rule_id, calls).to_numpy())
    std = work[work["sample_type"] == "std"]
    q, source, unit = standard_quantities(std, quantities, declared)
    std = std.assign(abs_q=q, abs_source=source, abs_unit=unit)
    labelled = _level_labels(std)
    if labelled:
        std = std.assign(abs_q=std["abs_q"].where(~std["target"].astype(str).isin(labelled)))
    known = std[std["abs_q"].notna() & (std["abs_q"] > 0)]
    wanted = sorted(set(known["target"].astype(str)))
    if targets is not None:
        wanted = [t for t in wanted if t in set(targets)]
    curves: list[StandardCurve] = []
    not_quantified: dict[str, str] = {}
    unlabelled = sorted(set(std["target"].astype(str)) - set(known["target"].astype(str)))
    for t in unlabelled:
        if targets is None or t in set(targets):
            not_quantified[t] = (
                "standards without a quantity: set each standard's quantity on the Design page "
                "(a top quantity and a dilution step)"
            )
            if t in labelled:
                not_quantified[t] = (
                    f"the standards are named {labelled[t]}: those number the levels, they are "
                    "not quantities; set each standard's quantity on the Design page (a top "
                    "quantity and a dilution step)"
                )
    for target in wanted:
        rows = known[known["target"].astype(str) == target]
        plates = []
        for run_id, plate in rows.groupby("run_id", sort=False):
            cid = curve_id(target, str(run_id))
            plates.append(_curve(cid, target, "plate", [str(run_id)], plate, settings))
        curves.extend(plates)
        fitted = [c for c in plates if c.fit is not None]
        series = {c.runs[0]: frozenset(p.quantity for p in c.points) for c in plates}
        if len(fitted) >= 2 and len(set(series.values())) == 1:
            pooled_runs = [c.runs[0] for c in plates]
            curves.append(
                _curve(curve_id(target, POOLED), target, "pooled", pooled_runs, rows, settings)
            )
        if not fitted:
            reasons = "; ".join(sorted({c.problem for c in plates if c.problem}))
            not_quantified[target] = reasons or "no standard curve"
    unknowns = _unknowns(work, curves, units, reaction)
    units_found = sorted({c.unit for c in curves if c.unit})
    unit_words = (reaction.unit if reaction and reaction.unit else None) or (
        units_found[0] if len(units_found) == 1 else ""
    )
    return Absolute(
        curves=tuple(curves),
        unknowns=tuple(unknowns),
        unit=unit_words,
        settings=settings,
        reaction=reaction,
        not_quantified=not_quantified,
    )


def _reader(curves: Sequence[StandardCurve]) -> dict[tuple[str, str], tuple[StandardCurve, bool]]:
    """``(target, run) -> (curve, from another plate)`` for every plate an assay is on."""
    out: dict[tuple[str, str], tuple[StandardCurve, bool]] = {}
    by_target: dict[str, list[StandardCurve]] = {}
    for c in curves:
        if c.fit is not None:
            by_target.setdefault(c.target, []).append(c)
    for target, found in by_target.items():
        for c in found:
            if c.scope == "plate":
                out[(target, c.runs[0])] = (c, False)
    return out


def _fallback(curves: Sequence[StandardCurve], target: str) -> StandardCurve | None:
    """The curve a plate without standards reads from: the pooled one, else the only one."""
    found = [c for c in curves if c.target == target and c.fit is not None]
    pooled = [c for c in found if c.scope == "pooled"]
    if pooled:
        return pooled[0]
    return found[0] if len(found) == 1 else None


def _unknowns(
    work: pd.DataFrame,
    curves: Sequence[StandardCurve],
    units: Mapping[str, str] | None,
    reaction: ReactionInputs | None,
) -> list[UnknownEstimate]:
    targets = {c.target for c in curves if c.fit is not None}
    unknown = work[(work["sample_type"] == "unkn") & work["target"].astype(str).isin(targets)]
    if unknown.empty:
        return []
    own = _reader(curves)
    by_id = {c.id: c for c in curves}
    fallback = {t: _fallback(curves, t) for t in targets}
    run = unknown["run_id"].astype(str).to_numpy()
    target_of = unknown["target"].astype(str).to_numpy()
    well_of = unknown["well"].astype(str).to_numpy()
    sample_of = unknown["sample"].astype(str).to_numpy()
    cq_of = unknown["cq"].to_numpy(dtype=float)
    det_of = unknown["abs_det"].to_numpy(dtype=bool) & np.isfinite(cq_of)
    chosen: list[StandardCurve | None] = []
    other_of = np.zeros(len(run), dtype=bool)
    for i, (t, r) in enumerate(zip(target_of, run, strict=True)):
        hit = own.get((t, r))
        if hit is None:
            chosen.append(fallback[t])
            other_of[i] = fallback[t] is not None
        else:
            chosen.append(hit[0])
    slope = np.array([c.fit.slope if c and c.fit else np.nan for c in chosen])
    intercept = np.array([c.fit.intercept if c and c.fit else np.nan for c in chosen])
    with np.errstate(invalid="ignore"):
        single = np.where(det_of, 10 ** ((cq_of - intercept) / slope), np.nan)
    unit_of = unit_map(list(sample_of), units).to_numpy()
    keys = pd.DataFrame({"unit": unit_of, "target": target_of})
    out = []
    for (unit, target), idx in sorted(keys.groupby(["unit", "target"], sort=False).indices.items()):
        wells = []
        per_curve: dict[str, list[float]] = {}
        flags: list[str] = []
        for i in idx:
            curve = chosen[i]
            detected = bool(det_of[i])
            if curve is not None and detected:
                per_curve.setdefault(curve.id, []).append(float(cq_of[i]))
                if other_of[i] and "other_plate" not in flags:
                    flags.append("other_plate")
            cq = float(cq_of[i]) if np.isfinite(cq_of[i]) else None
            wells.append(
                UnknownWell(
                    run_id=str(run[i]),
                    well=str(well_of[i]),
                    sample=str(sample_of[i]),
                    cq=cq,
                    detected=detected,
                    curve=curve.id if curve is not None else None,
                    quantity=float(single[i]) if np.isfinite(single[i]) else None,
                )
            )
        n_detected = int(det_of[idx].sum())
        if n_detected == 0:
            flags.append("not_detected")
        elif n_detected < len(wells):
            flags.append("some_not_detected")
        if len(per_curve) > 1:
            flags.append("several_curves")
        estimate = _estimate(per_curve, by_id)
        log10_q, low, high = estimate if estimate else (None, None, None)
        if log10_q is not None:
            flags.extend(_range_flags(log10_q, [by_id[c] for c in per_curve]))
        elif n_detected == 0:
            used = {w.curve for w in wells if w.curve}
            flags.extend(_nd_flags([by_id[c] for c in sorted(used)]))
        cqs = [c for values in per_curve.values() for c in values]
        out.append(
            UnknownEstimate(
                unit=str(unit),
                target=str(target),
                samples=tuple(sorted({w.sample for w in wells})),
                wells=tuple(wells),
                curves=tuple(sorted(per_curve)),
                n_wells=len(wells),
                n_detected=n_detected,
                mean_cq=sum(cqs) / len(cqs) if cqs else None,
                log10_quantity=log10_q,
                log10_low=low if low is None or math.isfinite(low) else None,
                log10_high=high if high is None or math.isfinite(high) else None,
                flags=tuple(flags),
                per_ul=_per(log10_q, reaction.template_ul if reaction else None),
                per_ng=_per(log10_q, reaction.input_ng if reaction else None),
            )
        )
    return out


def _per(log10_q: float | None, amount: float | None) -> float | None:
    if log10_q is None or amount is None or not amount > 0:
        return None
    return float(10**log10_q / amount)


def _estimate(
    per_curve: Mapping[str, list[float]], curves: Mapping[str, StandardCurve]
) -> tuple[float, float, float] | None:
    """``(log10 q, low, high)`` of a unit from its detected wells' Cq on each curve."""
    if not per_curve:
        return None
    xs, variances, dfs = [], [], []
    for cid, cqs in sorted(per_curve.items()):
        fit = curves[cid].fit
        assert fit is not None
        x0, s = fit.inverse(sum(cqs) / len(cqs), len(cqs))
        xs.append(x0)
        variances.append(s**2)
        dfs.append(fit.df)
    n = len(xs)
    x = sum(xs) / n
    s = math.sqrt(sum(variances)) / n
    df = min(dfs)
    if df <= 0:
        return x, math.nan, math.nan
    half = _t_crit(df) * s
    return x, x - half, x + half


@lru_cache(maxsize=256)
def _t_crit(df: int) -> float:
    """t(0.975, df), cached (one per curve size)."""
    return float(stats.t.ppf(0.5 + PI_LEVEL / 2, df))


def _range_flags(log10_q: float, curves: Sequence[StandardCurve]) -> list[str]:
    """Extrapolation and the limits, against the curve(s) the value was read from."""
    flags = []
    tops = [c.top for c in curves if c.top]
    lows = [c.lowest for c in curves if c.lowest]
    q = 10**log10_q
    if tops and q > max(tops) * (1 + 1e-9):
        flags.append("above_top")
    if lows and q < min(lows) * (1 - 1e-9):
        flags.append("below_lowest")
    lods = [c.lod.quantity for c in curves if c.lod.quantity is not None and not c.lod.at_most]
    loqs = [c.loq.quantity for c in curves if c.loq.quantity is not None]
    if lods and q < max(lods):
        flags.append("below_lod")
    if loqs and q < max(loqs) and "below_lod" not in flags:
        flags.append("below_loq")
    return flags


def _nd_flags(curves: Sequence[StandardCurve]) -> list[str]:
    """A unit with no detected well: below the LOD when the curve has one (said in words)."""
    if any(c.lod.quantity is not None for c in curves):
        return ["below_lod"]
    return []


def pct(fraction: float, decimals: int = 0) -> str:
    """A fraction as the page writes a percentage: ``0.946`` -> ``94.6 %`` (``decimals=1``)."""
    return f"{fraction * 100:.{decimals}f} %"


def flag_words(flags: Sequence[str]) -> list[str]:
    """Each flag in plain words."""
    return [FLAG_WORDS.get(f, f) for f in flags]


def summary_words(curve: StandardCurve) -> str:
    """One line: slope, efficiency with its CI, R², levels."""
    fit = curve.fit
    if fit is None:
        return curve.problem or "no curve"
    low, high = fit.efficiency_ci
    ci = f" (95 % CI {pct(low, 1)} to {pct(high, 1)})" if math.isfinite(low) else ""
    return (
        f"slope {fit.slope:.3f}, efficiency {pct(fit.efficiency, 1)}{ci}, R² {fit.r2:.4f}, "
        f"{len({p.quantity for p in curve.points if p.detected})} levels, {fit.n} wells"
    )


def as_record(value: Any) -> Any:
    """Plain data (for JSON): dataclasses to dicts, NaN to ``None``."""
    if hasattr(value, "__dataclass_fields__"):
        return {k: as_record(getattr(value, k)) for k in value.__dataclass_fields__}
    if isinstance(value, dict):
        return {str(k): as_record(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [as_record(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value
