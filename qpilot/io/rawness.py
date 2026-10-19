"""Raw-ness detector: were these amplification curves processed before qPilot saw them?

LinRegPCR estimates each well's baseline itself and assumes unprocessed fluorescence; a vendor's
baseline subtraction or smoothing is baked into exported numbers and cannot be undone, and
baseline errors are the main source of efficiency bias (Ruijter et al. 2009). This module says,
per well, per plate and per study, what processing the curves most likely had, with the
evidence, **before** per-well efficiencies are trusted. Spec: ``scientist-spec-capture.md`` §3.

Per well, on one target's amplification curve:

* ground phase = cycles 3..G, ``G = clip(floor(Cq) - 4, 8, 40)`` when the vendor gave a Cq, else
  3..min(15, last cycle) (the window gate's DRIFT rule uses); fewer than 5 ground cycles ->
  ``unknown`` (``short_ground``);
* ``m`` = median ground value; ``sigma`` = 1.4826 x MAD of the ground's first differences / sqrt 2
  (noise per point); ``neg`` = ground values below 0;
* tests: ``ground_offset`` (m / sigma), ``negative_values`` (neg > 0: raw fluorescence cannot be
  negative), ``zero_centred`` (|m| <= 3 sigma / sqrt n and 20-80 % of ground values negative),
  ``flat_fit_footprint`` (the ground's least-squares line has |slope| x n <= sigma and
  |level at its centre| <= sigma), ``smoothing`` (SD of first differences / (sqrt 2 x SD of
  residuals about the ground line): 1.00 for white noise, 0.58 after a 3-point centred mean);
* well verdict: ``baseline_subtracted`` if negatives, or zero-centred with a flat-fit footprint;
  ``raw`` if m / sigma >= 10 without negatives; else ``unknown``.

Per plate: a column name the vendor declared wins (``Delta Rn`` -> ``baseline_subtracted``,
``Rn`` -> ``normalized``); otherwise the well verdict held by at least 80 % of evaluable wells,
``unknown`` when at least 10 % are raw and at least 10 % subtracted (mixed processing), and
``scaled`` when amplified wells span exactly 0..1 (min-max scaling). A plate whose median
smoothing ratio is below 0.7 was smoothed: a raw verdict becomes ``unknown``. A plate without
curves is ``cq_only``. The study verdict is the worst plate's.

**Every cut-off (10, 3, 20-80 %, 80 %, 10 %, 0.7, 1 %) is an unsourced starting value**, to be
measured (false-alarm rate on raw public curves, detection rate on synthetic processing) in
``validation/rawness.md``. Deterministic: numpy only, floats rounded to 4 significant digits
in the JSON.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from qpilot.io.connectors.base import PlateData

METHOD_ID = "qpilot.rawness/1"
METHOD_CARD = {
    "id": METHOD_ID,
    "name": "Raw-ness detector (processing footprint of exported amplification curves)",
    "version": "1",
    "paper": "Ruijter JM et al. Nucleic Acids Res 2009;37(6):e45 (why baselines matter); "
    "tests and cut-offs: qPilot (scientist-spec-capture.md section 3), unsourced starting values",
    "inputs": "per-well fluorescence per cycle; vendor Cq (optional); declared signal column",
    "outputs": "well / plate / study verdict raw | normalized | baseline_subtracted | scaled | "
    "cq_only | unknown, with evidence; linregpcr_ok",
    "acceptance": "tests/capture/test_rawness.py; validation/rawness.md (false-alarm and "
    "detection rates)",
    "licence": "Apache-2.0 (qPilot)",
}

VERDICTS = ("raw", "normalized", "baseline_subtracted", "scaled", "cq_only", "unknown")
_BADNESS = {"raw": 0, "normalized": 1, "scaled": 2, "unknown": 3, "baseline_subtracted": 4,
            "cq_only": 5}  # fmt: skip

# Unsourced starting values (scientist-spec-capture.md section 3); measured in validation/.
MIN_GROUND = 5
RAW_OFFSET = 10.0
ZERO_SIGMAS = 3.0
NEG_SHARE = (0.2, 0.8)
PLATE_SHARE = 0.8
MIXED_SHARE = 0.1
SMOOTHED_RATIO = 0.7
SCALED_TOLERANCE = 0.01
AMPLIFIED_SIGMAS = 10.0


def _sig(value: float | None) -> float | None:
    """Round to 4 significant digits (deterministic JSON); ``None`` for non-finite."""
    if value is None or not math.isfinite(value):
        return None
    if value == 0:
        return 0.0
    return float(f"{value:.4g}")


@dataclass
class WellResult:
    """One well's tests and verdict."""

    verdict: str
    reason: str = ""
    ground_n: int = 0
    level: float = math.nan  # m
    noise: float = math.nan  # sigma
    offset: float = math.nan  # m / sigma
    negatives: int = 0
    zero_centred: bool = False
    flat_fit: bool = False
    smoothing: float = math.nan
    amplitude: float = math.nan
    amplified: bool = False
    y_min: float = math.nan
    y_max: float = math.nan


def ground_window(cycles: np.ndarray, cq: float | None) -> np.ndarray:
    """Boolean mask of the ground-phase cycles (3..G), as gate's DRIFT rule chooses them."""
    if cq is not None and math.isfinite(cq):
        last = int(min(max(math.floor(cq) - 4, 8), 40))
    else:
        last = int(min(15, cycles.max() if cycles.size else 0))
    return (cycles >= 3) & (cycles <= last)


def assess_well(
    cycles: Sequence[float], fluor: Sequence[float], cq: float | None = None
) -> WellResult:
    """The raw-ness tests and verdict for one amplification curve."""
    x = np.asarray(cycles, dtype=float)
    y = np.asarray(fluor, dtype=float)
    if x.size == 0:
        return WellResult("unknown", "no_curve")
    mask = ground_window(x, cq)
    gx, gy = x[mask], y[mask]
    n = int(gy.size)
    if n < MIN_GROUND:
        return WellResult("unknown", "short_ground", ground_n=n)
    level = float(np.median(gy))
    diffs = np.diff(gy)
    mad = float(np.median(np.abs(diffs - np.median(diffs))))
    noise = 1.4826 * mad / math.sqrt(2)
    if noise <= 0:  # quantised, perfectly flat ground: use the resolution of the values
        steps = np.abs(diffs[diffs != 0])
        noise = float(steps.min()) / 2 if steps.size else max(abs(level) * 1e-6, 1e-12)
    offset = level / noise
    negatives = int((gy < 0).sum())
    share_negative = negatives / n
    zero_centred = abs(level) <= ZERO_SIGMAS * noise / math.sqrt(n) and (
        NEG_SHARE[0] <= share_negative <= NEG_SHARE[1]
    )
    centre = float(gx.mean())
    slope, intercept = np.polyfit(gx - centre, gy, 1)
    flat_fit = abs(slope) * n <= noise and abs(intercept) <= noise
    residuals = gy - (intercept + slope * (gx - centre))
    resid_sd = float(np.std(residuals, ddof=1)) if n > 2 else math.nan
    smoothing = (
        float(np.std(diffs, ddof=1)) / (math.sqrt(2) * resid_sd) if resid_sd > 0 else math.nan
    )
    amplitude = float(y.max() - level)
    if negatives > 0 or (zero_centred and flat_fit):
        verdict, reason = "baseline_subtracted", "negative_values" if negatives else "zero_flat"
    elif offset >= RAW_OFFSET:
        verdict, reason = "raw", "ground_offset"
    else:
        verdict, reason = "unknown", "small_offset"
    return WellResult(
        verdict=verdict,
        reason=reason,
        ground_n=n,
        level=level,
        noise=noise,
        offset=offset,
        negatives=negatives,
        zero_centred=zero_centred,
        flat_fit=flat_fit,
        smoothing=smoothing,
        amplitude=amplitude,
        amplified=amplitude > AMPLIFIED_SIGMAS * noise,
        y_min=float(y.min()),
        y_max=float(y.max()),
    )


@dataclass
class PlateResult:
    """One plate's verdict, the well counts behind it, and its evidence."""

    run_id: str
    verdict: str
    wells: dict[str, int] = field(default_factory=dict)
    evidence: list[dict] = field(default_factory=list)
    declared: str = ""
    linregpcr_ok: bool = False
    note_keys: list[str] = field(default_factory=list)


def _median(values: list[float]) -> float | None:
    finite = [v for v in values if math.isfinite(v)]
    return float(np.median(finite)) if finite else None


def assess_plate(plate: PlateData) -> PlateResult:
    """The plate's verdict from its wells (and the signal column its reader declared)."""
    results = [assess_well(r.amp.x, r.amp.y, r.cq) for r in plate.reactions if r.amp is not None]
    out = PlateResult(run_id=plate.run_id, verdict="unknown")
    if not results:
        out.verdict = "cq_only"
        out.evidence.append({"run_id": plate.run_id, "test": "amplification_layer",
                             "passed": False, "note_key": "no_curves"})  # fmt: skip
        return out
    counts = Counter(r.verdict for r in results)
    out.wells = dict(sorted(counts.items()))
    evaluable = [r for r in results if r.reason not in ("short_ground", "no_curve")]
    n_eval = len(evaluable)
    run = plate.run_id
    neg_wells = sum(1 for r in evaluable if r.negatives > 0)
    out.evidence += [
        {"run_id": run, "test": "negative_values", "n_wells": neg_wells, "of": n_eval,
         "passed": neg_wells == 0},
        {"run_id": run, "test": "ground_level", "value": _sig(_median([r.level for r in evaluable])),
         "unit": plate.value_kind},
        {"run_id": run, "test": "ground_offset",
         "value": _sig(_median([r.offset for r in evaluable])), "threshold": RAW_OFFSET},
        {"run_id": run, "test": "zero_centred",
         "n_wells": sum(1 for r in evaluable if r.zero_centred), "of": n_eval},
        {"run_id": run, "test": "flat_fit_footprint",
         "n_wells": sum(1 for r in evaluable if r.flat_fit), "of": n_eval},
    ]  # fmt: skip
    smoothing = _median([r.smoothing for r in evaluable])
    smoothed = smoothing is not None and smoothing < SMOOTHED_RATIO
    out.evidence.append({"run_id": run, "test": "smoothing", "value": _sig(smoothing),
                         "threshold": SMOOTHED_RATIO, "passed": not smoothed})  # fmt: skip
    short = len(results) - n_eval
    if short:
        out.evidence.append({"run_id": run, "test": "short_ground", "n_wells": short,
                             "of": len(results)})  # fmt: skip
    amplified = [r for r in evaluable if r.amplified]
    scaled = bool(amplified) and (
        abs(max(r.y_max for r in amplified) - 1.0) <= SCALED_TOLERANCE
        and abs(min(r.y_min for r in amplified)) <= SCALED_TOLERANCE
    )
    out.evidence.append({"run_id": run, "test": "scaled_0_1", "passed": not scaled})

    declared = {"dRn": "baseline_subtracted", "Rn": "normalized"}.get(plate.value_kind, "")
    if declared:
        out.declared = plate.value_kind
        out.verdict = declared
        out.evidence.append({"run_id": run, "test": "declared_signal", "value": plate.value_kind})
        out.note_keys.append("declared_" + plate.value_kind.lower())
    elif n_eval == 0:
        out.verdict = "unknown"
        out.note_keys.append("short_ground")
    else:
        raw = sum(1 for r in evaluable if r.verdict == "raw") / n_eval
        subtracted = sum(1 for r in evaluable if r.verdict == "baseline_subtracted") / n_eval
        if raw >= MIXED_SHARE and subtracted >= MIXED_SHARE:
            out.verdict = "unknown"
            out.note_keys.append("mixed")
        elif scaled:
            out.verdict = "scaled"
        else:
            top, top_n = Counter(r.verdict for r in evaluable).most_common(1)[0]
            out.verdict = top if top_n / n_eval >= PLATE_SHARE else "unknown"
            if out.verdict == "unknown":
                out.note_keys.append("no_majority")
        if out.verdict == "raw" and smoothed:
            out.verdict = "unknown"
            out.note_keys.append("smoothed")
    clean = neg_wells == 0 and not any(r.flat_fit and r.zero_centred for r in evaluable)
    out.linregpcr_ok = out.verdict in ("raw", "normalized") or (out.verdict == "scaled" and clean)
    return out


@dataclass
class RawnessReport:
    """Verdicts for every plate and the study, with evidence (see the module docstring)."""

    plates: list[PlateResult]

    @property
    def study_verdict(self) -> str:
        """The worst plate's verdict (``unknown`` with no plates)."""
        if not self.plates:
            return "unknown"
        return max((p.verdict for p in self.plates), key=lambda v: _BADNESS[v])

    @property
    def linregpcr_ok(self) -> bool:
        """Whether every plate's curves suit LinRegPCR's per-well baseline and efficiency."""
        return bool(self.plates) and all(p.linregpcr_ok for p in self.plates)

    def to_json(self) -> dict:
        """The ``rawness`` block of ``CaptureMeta`` (deterministic)."""
        return {
            "method": METHOD_ID,
            "study_verdict": self.study_verdict,
            "linregpcr_ok": self.linregpcr_ok,
            "plate_verdicts": {p.run_id: p.verdict for p in self.plates},
            "plate_linregpcr_ok": {p.run_id: p.linregpcr_ok for p in self.plates},
            "declared": {p.run_id: p.declared for p in self.plates if p.declared},
            "notes": {p.run_id: p.note_keys for p in self.plates if p.note_keys},
            "wells": {p.run_id: p.wells for p in self.plates},
            "evidence": [e for p in self.plates for e in p.evidence],
        }


def assess(plates: Sequence[PlateData]) -> RawnessReport:
    """Verdicts for every plate of an import."""
    return RawnessReport([assess_plate(p) for p in plates])


_WARNINGS = {
    "baseline_subtracted": (
        "CURVES_NOT_RAW",
        "The amplification curves were most likely baseline-subtracted before export, so qPilot "
        "cannot estimate each well's baseline and efficiency itself. Re-export the raw "
        "fluorescence to restore per-well efficiency.",
    ),
    "unknown": (
        "RAWNESS_UNKNOWN",
        "qPilot could not tell whether these curves were processed (signal too small or mixed); "
        "treat per-well efficiencies with caution.",
    ),
    "scaled": (
        "CURVES_SCALED",
        "The curves were rescaled to run from 0 to 1 before export; qPilot cannot see whether a "
        "baseline was subtracted first.",
    ),
    "cq_only": (
        "CQ_ONLY",
        "Only Cq values were provided. Efficiency is assumed, not measured, so confidence is "
        "capped at Low.",
    ),
    "normalized": (
        "PASSIVE_REFERENCE",
        "The curves are passive-reference normalised (Rn); the ground phase is kept, so qPilot "
        "can still estimate each well's baseline.",
    ),
}


def warnings_for(rawness: dict | None) -> list[tuple[str, str]]:
    """Plain-English warnings (code, message) for a ``rawness`` block; none for ``raw``."""
    if not rawness:
        return []
    verdicts = set(rawness.get("plate_verdicts", {}).values())
    return [_WARNINGS[v] for v in VERDICTS if v in verdicts and v in _WARNINGS]


__all__ = [
    "METHOD_CARD",
    "METHOD_ID",
    "VERDICTS",
    "PlateResult",
    "RawnessReport",
    "WellResult",
    "assess",
    "assess_plate",
    "assess_well",
    "ground_window",
    "warnings_for",
]
