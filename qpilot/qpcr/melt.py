"""Melt curves of DNA-binding-dye assays (SYBR Green, EvaGreen): −dF/dT, peaks, the product's Tm.

A melt curve is the fluorescence of a well read while the temperature rises after the last cycle.
A double-stranded product loses its dye when it melts, so the fluorescence drops most steeply at
the product's melting temperature (Tm): the peak of the negative derivative −dF/dT (Ririe,
Rasmussen and Wittwer 1997). A second, lower peak is usually a primer-dimer; a peak elsewhere is
another product. This module computes, deterministically and from the study's own file:

* **per well** (:func:`analyse_curve`): the readings sorted and put on an even temperature grid
  (their median step), −dF/dT by a Savitzky–Golay derivative (a cubic over a window of
  :attr:`MeltSettings.smoothing_c`, at least five readings: it keeps a peak's height and width
  where a straight-line slope would flatten them), and its local maxima: each peak's
  Tm (the top of a parabola through the three highest readings), its height (−dF/dT there), its
  prominence (the height above its local background, as ``scipy.signal.find_peaks`` measures
  it) and its width at half prominence. Maxima within half a window of either end are edge
  effects of the smoothing and are dropped, and so are ripples below
  :attr:`MeltSettings.ripple_share` of the well's tallest peak.
* **per assay** (one target on one plate, :func:`judge`): the expected Tm (the target's melting
  temperature declared in the RDML file, else the median main-peak Tm of the target's amplified
  study wells on the plate, with at least ``min_wells`` of them: unknowns, else unknowns,
  positives and standards together), the spread of those wells' Tm, and a noise floor
  (``noise_share`` of the median main-peak prominence of those wells): a peak lower than that
  is not counted. Then each well's call: a study well that amplified melts as one product at the
  expected Tm (``one_product``), has, beside its product (the most prominent peak within
  ``tm_tolerance_c`` of the expected Tm, as rdmlpython takes the true peak), an extra peak
  carrying at least ``extra_peak_share`` of its summed peak prominences (``extra_peak``), has no
  peak within the tolerance (``tm_off``) or shows no peak at all (``no_peak``); a no-template
  control shows no peak (``no_product``), a peak at the product's Tm (``product``: a
  contamination candidate), only lower peaks (``dimer``: a primer-dimer candidate) or a higher
  one (``other_product``).
* **per target** across plates (:func:`target_summaries`): the median product Tm and its range.

The thresholds are the Run Gate pack's (rule G-MELT, ``packs/research-default.yaml``), passed in
as :class:`MeltParams`; this module has their defaults only. The method card is
``methods/melt_curve.md``. A melt peak is a class, never an identification: a single peak at the
expected Tm does not prove the intended amplicon (MIQE 2.0).

The file is read through the hardened loader (:func:`qpilot.io.rdml_io.load`); a file whose
XML holds no melt reading (``<mdp>``) is recognised by a streaming scan without being parsed, so
a study without melt data costs a fraction of a second. Results are kept in memory per file
(path, size, modification time) and experiment.
"""

from __future__ import annotations

import math
import threading
import zipfile
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd
from scipy.signal import find_peaks, peak_widths, savgol_filter

METHOD_CARD = "methods/melt_curve.md"
#: Sample types whose melt is judged as a product (when they amplified).
JUDGED = ("unkn", "pos", "std")
#: Sample types whose melt is classified as a no-template control's.
NO_TEMPLATE = ("ntc", "ntp")
#: Sample types the expected Tm is taken from first (the scientist spec: amplified unknowns).
REFERENCE = ("unkn",)
#: RDML dye chemistries that bind double-stranded DNA (a melt curve then shows the product).
DYE_CHEMISTRIES = ("non-saturating DNA binding dye", "saturating DNA binding dye")
MAX_DOCS = 8

WellStatus = Literal[
    "one_product",
    "extra_peak",
    "tm_off",
    "no_peak",
    "not_amplified",
    "no_product",
    "product",
    "dimer",
    "other_product",
    "unclassified",
    "not_judged",
    "unreadable",
    "no_melt",
]
#: Statuses of a study well that point at it (the rule flags these wells).
STUDY_FLAGS = ("extra_peak", "tm_off", "no_peak")
#: Statuses of a no-template control that say a product is in it.
NTC_FLAGS = ("product", "other_product")


class MeltError(Exception):
    """The file's melt curves could not be read."""


@dataclass(frozen=True)
class MeltSettings:
    """How a curve is differentiated (the analysis, not the thresholds of a rule).

    ``smoothing_c``: the Savitzky–Golay window in °C; ``poly_order``: its polynomial; a curve
    needs ``min_points`` readings at most ``max_step_c`` apart; local maxima below
    ``ripple_share`` of the well's tallest are not listed, and at most ``max_peaks`` are.
    """

    smoothing_c: float = 2.0
    poly_order: int = 3
    min_points: int = 15
    max_step_c: float = 1.0
    ripple_share: float = 0.01
    max_peaks: int = 8


@dataclass(frozen=True)
class MeltParams:
    """G-MELT's thresholds (the pack's ``params``; these are its defaults)."""

    tm_tolerance_c: float = 1.0
    extra_peak_share: float = 0.05
    noise_share: float = 0.05
    min_wells: int = 3

    @classmethod
    def from_rule(cls, params: Mapping[str, Any]) -> MeltParams:
        """The thresholds a pack rule's ``params`` set (unknown keys ignored, the rest checked)."""
        out = cls()
        for name in ("tm_tolerance_c", "extra_peak_share", "noise_share", "min_wells"):
            if name not in params:
                continue
            value = params[name]
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError(f"G-MELT: parameter {name} must be a number")
            if not math.isfinite(float(value)) or value < 0:
                raise ValueError(f"G-MELT: parameter {name} must be a number of at least zero")
            out = replace(out, **{name: int(value) if name == "min_wells" else float(value)})
        if out.tm_tolerance_c <= 0:
            raise ValueError("G-MELT: tm_tolerance_c must be more than zero degrees")
        if out.extra_peak_share >= 1 or out.noise_share >= 1:
            raise ValueError("G-MELT: the shares must be below one")
        return out


@dataclass(frozen=True)
class MeltCurve:
    """One well's melt readings as the file holds them (one target)."""

    run_id: str
    well: str
    target: str
    sample: str
    temperature: tuple[float, ...]
    fluorescence: tuple[float, ...]

    @property
    def key(self) -> str:
        """The well's ``run_id/well`` key (as every well-level decision names it)."""
        return f"{self.run_id}/{self.well}"


@dataclass(frozen=True)
class Peak:
    """One peak of a well's −dF/dT."""

    tm: float
    height: float
    prominence: float
    width_c: float | None


@dataclass(frozen=True)
class WellMelt:
    """One well's melt curve analysed: the even grid, −dF/dT on it, and its peaks."""

    curve: MeltCurve
    temperature: tuple[float, ...] = ()
    derivative: tuple[float, ...] = ()
    peaks: tuple[Peak, ...] = ()
    step_c: float | None = None
    problem: str = ""

    @property
    def key(self) -> str:
        """The well's ``run_id/well`` key."""
        return self.curve.key


@dataclass(frozen=True)
class MeltData:
    """Every melt curve of one experiment of a file, analysed, and what the file declares.

    ``wells`` is keyed ``(run_id, well, target)`` as the per-well table names them;
    ``plates`` lists every plate read and ``declared_tm`` / ``chemistry`` the targets' melting
    temperature and dye chemistry where the file declares them.
    """

    wells: Mapping[tuple[str, str, str], WellMelt] = field(default_factory=dict)
    plates: tuple[str, ...] = ()
    declared_tm: Mapping[str, float] = field(default_factory=dict)
    chemistry: Mapping[str, str] = field(default_factory=dict)
    settings: MeltSettings = field(default_factory=MeltSettings)

    @property
    def has_melt(self) -> bool:
        """Whether any well has a melt curve."""
        return bool(self.wells)

    def plates_with_melt(self) -> set[str]:
        """The plates at least one of whose wells has a melt curve."""
        return {run_id for run_id, _, _ in self.wells}

    def probe(self, target: str) -> bool:
        """Whether the file declares a probe chemistry (not a DNA-binding dye) for ``target``."""
        chem = self.chemistry.get(target, "")
        return bool(chem) and chem not in DYE_CHEMISTRIES


EMPTY = MeltData()


# ---------- one curve ----------


def _clean(
    temperature: Iterable[Any], fluorescence: Iterable[Any]
) -> tuple[np.ndarray, np.ndarray]:
    """Finite readings sorted by temperature; readings at one temperature averaged."""
    t = np.asarray([_float(v) for v in temperature], dtype=float)
    f = np.asarray([_float(v) for v in fluorescence], dtype=float)
    n = min(len(t), len(f))
    t, f = t[:n], f[:n]
    ok = np.isfinite(t) & np.isfinite(f)
    t, f = t[ok], f[ok]
    if not len(t):
        return t, f
    unique, inverse = np.unique(t, return_inverse=True)
    sums = np.bincount(inverse, weights=f)
    counts = np.bincount(inverse)
    return unique, sums / counts


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _window(step: float, n: int, settings: MeltSettings) -> int:
    """The Savitzky–Golay window in readings: odd, at least five, at most the curve."""
    w = int(round(settings.smoothing_c / step))
    w = max(w + (1 - w % 2), 5)
    if w > n:
        w = n if n % 2 else n - 1
    return w


def analyse_curve(curve: MeltCurve, settings: MeltSettings | None = None) -> WellMelt:
    """One well's −dF/dT and peaks (see the module docstring); never raises on bad data.

    A curve with fewer than ``min_points`` readings is ``too_few_points``; one whose readings
    are more than ``max_step_c`` apart is ``coarse`` (a peak cannot be placed to within a
    degree); a flat or empty one has no peaks.
    """
    settings = settings or MeltSettings()
    t, f = _clean(curve.temperature, curve.fluorescence)
    if len(t) < max(settings.min_points, 5):
        return WellMelt(curve=curve, problem="too_few_points")
    step = float(np.median(np.diff(t)))
    if not step > 0:
        return WellMelt(curve=curve, problem="too_few_points")
    if step > settings.max_step_c:
        return WellMelt(curve=curve, step_c=step, problem="coarse")
    n = int(round((t[-1] - t[0]) / step)) + 1
    grid = t[0] + step * np.arange(n)
    values = np.interp(grid, t, f)
    w = _window(step, n, settings)
    order = min(settings.poly_order, w - 1)
    derivative = -savgol_filter(values, w, order, deriv=1, delta=step, mode="interp")
    # a peak must lose more than a millionth of the curve's fluorescence range per reading:
    # below that it is rounding in a flat stretch, not a product melting
    floor = 1e-6 * float(np.ptp(values)) / step
    peaks = _peaks(grid, derivative, step, w, settings, floor)
    return WellMelt(
        curve=curve,
        temperature=tuple(float(round(x, 6)) for x in grid),
        derivative=tuple(float(round(y, 6)) for y in derivative),
        peaks=peaks,
        step_c=round(step, 6),
    )


def _peaks(
    grid: np.ndarray,
    d: np.ndarray,
    step: float,
    window: int,
    settings: MeltSettings,
    floor: float = 0.0,
) -> tuple[Peak, ...]:
    """The local maxima of ``d``, most prominent first (edge effects and ripples left out)."""
    found, props = find_peaks(d, prominence=0)
    if not len(found):
        return ()
    prominence = props["prominences"]
    edge = window // 2
    keep = [
        i
        for i, p in enumerate(found)
        if edge <= p <= len(d) - 1 - edge and prominence[i] > max(floor, 0.0)
    ]
    if not keep:
        return ()
    top = max(float(prominence[i]) for i in keep)
    keep = [i for i in keep if prominence[i] >= settings.ripple_share * top]
    bases = (prominence[keep], props["left_bases"][keep], props["right_bases"][keep])
    widths = peak_widths(d, found[keep], rel_height=0.5, prominence_data=bases)[0]
    out = []
    for i, steps in zip(keep, widths, strict=True):
        p = int(found[i])
        tm, height = _vertex(grid, d, p, step)
        width = float(steps) * step
        out.append(
            Peak(
                tm=round(tm, 4),
                height=round(height, 6),
                prominence=round(float(prominence[i]), 6),
                width_c=round(width, 4) if math.isfinite(width) else None,
            )
        )
    out.sort(key=lambda pk: (-pk.prominence, pk.tm))
    return tuple(out[: settings.max_peaks])


def _vertex(grid: np.ndarray, d: np.ndarray, p: int, step: float) -> tuple[float, float]:
    """The top of the parabola through the peak's reading and its two neighbours."""
    a, b, c = float(d[p - 1]), float(d[p]), float(d[p + 1])
    den = a - 2 * b + c
    if den >= 0:  # not a strict maximum (a plateau): the reading itself
        return float(grid[p]), b
    offset = 0.5 * (a - c) / den
    offset = max(-0.5, min(0.5, offset))
    return float(grid[p]) + offset * step, b - 0.25 * (a - c) * offset


# ---------- the file ----------

_lock = threading.Lock()
_cache: OrderedDict[tuple[Any, ...], MeltData] = OrderedDict()


def _has_melt_points(path: Path) -> bool | None:
    """Whether the file's XML holds a melt reading (``<mdp``), by a streaming scan.

    ``None`` when the scan cannot tell (a zip without ``rdml_data.xml``): the file is then read.
    """
    from qpilot.io.rdml_io import RDML_MEMBER

    def scan(handle: Any) -> bool:
        tail = b""
        while True:
            chunk = handle.read(1 << 20)
            if not chunk:
                return False
            if b"<mdp" in tail + chunk:
                return True
            tail = chunk[-8:]

    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                if RDML_MEMBER not in archive.namelist():
                    return None
                with archive.open(RDML_MEMBER) as handle:
                    return scan(handle)
        with path.open("rb") as handle:
            return scan(handle)
    except (OSError, zipfile.BadZipFile):
        return None


def read_melt(
    source: str | Path | Any,
    experiment_id: str | None = None,
    settings: MeltSettings | None = None,
) -> MeltData:
    """Every melt curve of one experiment of an RDML file (or loaded document), analysed.

    ``experiment_id`` ``None`` reads every experiment. A path is kept in memory by its path,
    size and modification time. A file with no melt reading is not parsed: it gives an empty
    :class:`MeltData` (no wells and no plates).

    Raises:
        MeltError: The file cannot be read safely.
    """
    from qpilot.io.rdml_io import RdmlLoadError, load
    from qpilot.vendor.rdmlpython import rdml

    settings = settings or MeltSettings()
    if isinstance(source, rdml.Rdml):
        return _read_doc(source, experiment_id, settings)
    path = Path(source)
    try:
        st = path.stat()
    except OSError as err:
        raise MeltError(f"{path.name}: {err.strerror or err}") from err
    key = (str(path.resolve()), st.st_mtime_ns, st.st_size, experiment_id, settings)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    if _has_melt_points(path) is False:
        data = MeltData(settings=settings)
    else:
        try:
            doc = load(path, validate=False)
        except RdmlLoadError as err:
            raise MeltError(str(err)) from err
        data = _read_doc(doc, experiment_id, settings)
    with _lock:
        _cache[key] = data
        while len(_cache) > MAX_DOCS:
            _cache.popitem(last=False)
    return data


def _read_doc(doc: Any, experiment_id: str | None, settings: MeltSettings) -> MeltData:
    from qpilot.io.rdml_io import RdmlLoadError, runs
    from qpilot.qpcr.curves import normalise_target, react_well_label, safe_name

    try:
        found = runs(doc, experiment_id)
    except RdmlLoadError as err:
        raise MeltError(str(err)) from err
    dyes: dict[str, str] = {}
    for dye in doc.dyes():
        chem = dye["dyeChemistry"]
        if dye["id"] and chem:
            dyes[str(dye["id"])] = str(chem)
    declared: dict[str, float] = {}
    chemistry: dict[str, str] = {}
    for target in doc.targets():
        name = normalise_target(safe_name(str(target["id"]), "target"))
        tm = _float(target["meltingTemperature"])
        if math.isfinite(tm) and 20.0 <= tm <= 100.0:
            declared[name] = tm
        dye = target["dyeId"]
        if dye and str(dye) in dyes:
            chemistry[name] = dyes[str(dye)]
    wells: dict[tuple[str, str, str], WellMelt] = {}
    plates: list[str] = []
    for run in found:
        run_id = safe_name(str(run["id"]), "run")
        plates.append(run_id)
        n_columns = int(run["pcrFormat_columns"])
        for react in run.getreactjson(curves=True).get("reacts", []):
            well = react_well_label(react["id"], n_columns)
            sample = safe_name(str(react.get("sample", "")), "sample")
            for data in react.get("datas", []):
                points = data.get("mdps") or []
                if not points:
                    continue
                target = normalise_target(safe_name(str(data.get("tar", "")), "target"))
                curve = MeltCurve(
                    run_id=run_id,
                    well=well,
                    target=target,
                    sample=sample,
                    temperature=tuple(_float(p[0]) for p in points if len(p) > 1),
                    fluorescence=tuple(_float(p[1]) for p in points if len(p) > 1),
                )
                wells[(run_id, well, target)] = analyse_curve(curve, settings)
    return MeltData(
        wells=wells,
        plates=tuple(plates),
        declared_tm=declared,
        chemistry=chemistry,
        settings=settings,
    )


def clear() -> None:
    """Forget every kept file (tests)."""
    with _lock:
        _cache.clear()


# ---------- the calls ----------


@dataclass(frozen=True)
class WellCall:
    """One well's melt call within its assay (see the module docstring for the statuses)."""

    run_id: str
    well: str
    target: str
    sample: str
    sample_type: str
    amplified: bool
    cq: float | None
    status: WellStatus
    melt: WellMelt | None = None
    #: The counted peaks (at or above the assay's noise floor), main peak first.
    peaks: tuple[Peak, ...] = ()
    #: Each counted peak's share of the well's summed prominences, in ``peaks`` order.
    shares: tuple[float, ...] = ()
    #: The counted peaks besides the main one that carry at least ``extra_peak_share``.
    extra: tuple[Peak, ...] = ()
    #: The main peak's Tm minus the expected Tm (None without either).
    offset: float | None = None

    @property
    def key(self) -> str:
        """The well's ``run_id/well`` key."""
        return f"{self.run_id}/{self.well}"

    @property
    def main(self) -> Peak | None:
        """The main (most prominent counted) peak, if any."""
        return self.peaks[0] if self.peaks else None

    @property
    def flagged(self) -> bool:
        """Whether G-MELT points at this well (a study well's problem, a product in a control)."""
        return self.status in STUDY_FLAGS or self.status in NTC_FLAGS


@dataclass(frozen=True)
class AssayMelt:
    """One target on one plate: the expected Tm, its spread, the noise floor, each well's call."""

    run_id: str
    target: str
    params: MeltParams
    expected_tm: float | None
    #: ``file`` (the target's declared Tm), ``median`` (of the reference wells) or ``None``.
    expected_source: str | None
    #: The wells the median Tm (and the noise floor) come from.
    reference: tuple[str, ...]
    median_tm: float | None
    min_tm: float | None
    max_tm: float | None
    reference_height: float | None
    noise_floor: float | None
    step_c: float | None
    wells: tuple[WellCall, ...]
    coarse: bool = False

    @property
    def spread_c(self) -> float | None:
        """Highest minus lowest main-peak Tm of the reference wells."""
        if self.min_tm is None or self.max_tm is None:
            return None
        return round(self.max_tm - self.min_tm, 4)

    @property
    def with_melt(self) -> list[WellCall]:
        """The wells that have a melt curve."""
        return [w for w in self.wells if w.melt is not None]


def _median(values: Iterable[float]) -> float | None:
    vals = [v for v in values if v is not None and math.isfinite(v)]
    return float(np.median(vals)) if vals else None


def _amplified(row: Any) -> bool:
    amp = row.get("amplification")
    cq = row.get("cq")
    return bool(amp is True or amp == 1 or str(amp).lower() == "true") and _finite(cq) is not None


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def judge_assay(
    run_id: str,
    target: str,
    rows: pd.DataFrame,
    melt: MeltData,
    params: MeltParams | None = None,
    plate_height: float | None = None,
) -> AssayMelt:
    """The melt calls of one target on one plate (``rows``: its wells of the per-well table).

    ``rows`` carries ``well``, ``sample``, ``sample_type``, ``amplification`` and ``cq`` (the
    engine's call: a well amplified when LinRegPCR says so and gives it a Cq). Sample types are
    the confirmed design's when the table was re-typed by it. ``plate_height`` is the typical
    product peak of the plate's other assays: the noise floor of an assay none of whose study
    wells amplified (its wells are then measured against a real product, not their own noise).
    """
    params = params or MeltParams()
    entries: list[tuple[dict[str, Any], WellMelt | None]] = []
    for row in rows.to_dict("records"):
        entries.append((row, melt.wells.get((run_id, str(row["well"]), target))))
    readable = [(r, m) for r, m in entries if m is not None and not m.problem and m.peaks]

    def mains(types: tuple[str, ...]) -> list[tuple[str, Peak]]:
        return [
            (f"{run_id}/{r['well']}", m.peaks[0])
            for r, m in readable
            if str(r["sample_type"]) in types and _amplified(r)
        ]

    ref = mains(REFERENCE)
    if len(ref) < params.min_wells:
        ref = mains(JUDGED)
    tms = [p.tm for _, p in ref]
    median_tm = _median(tms) if len(ref) >= params.min_wells else None
    declared = melt.declared_tm.get(target)
    if declared is not None:
        expected, source = float(declared), "file"
    elif median_tm is not None:
        expected, source = median_tm, "median"
    else:
        expected, source = None, None
    reference_height = _median(p.prominence for _, p in ref)
    if reference_height is None:
        reference_height = plate_height
    if reference_height is None:  # no product anywhere on the plate: its tallest peak
        tallest = [m.peaks[0].prominence for _, m in readable]
        reference_height = max(tallest) if tallest else None
    floor = params.noise_share * reference_height if reference_height is not None else None
    steps = [m.step_c for _, m in entries if m is not None and m.step_c is not None]
    coarse = (
        bool(entries)
        and all(m is None or m.problem == "coarse" for _, m in entries)
        and any(m is not None for _, m in entries)
    )
    calls = tuple(_call(run_id, target, row, m, params, expected, floor) for row, m in entries)
    return AssayMelt(
        run_id=run_id,
        target=target,
        params=params,
        expected_tm=round(expected, 4) if expected is not None else None,
        expected_source=source,
        reference=tuple(k for k, _ in ref),
        median_tm=round(median_tm, 4) if median_tm is not None else None,
        min_tm=round(min(tms), 4) if tms and median_tm is not None else None,
        max_tm=round(max(tms), 4) if tms and median_tm is not None else None,
        reference_height=reference_height,
        noise_floor=floor,
        step_c=float(np.median(steps)) if steps else None,
        wells=calls,
        coarse=coarse,
    )


def _call(
    run_id: str,
    target: str,
    row: Mapping[str, Any],
    melt: WellMelt | None,
    params: MeltParams,
    expected: float | None,
    floor: float | None,
) -> WellCall:
    kind = str(row.get("sample_type") or "unkn")
    amplified = _amplified(row)
    base = WellCall(
        run_id=run_id,
        well=str(row["well"]),
        target=target,
        sample=str(row.get("sample") or ""),
        sample_type=kind,
        amplified=amplified,
        cq=_finite(row.get("cq")),
        status="no_melt",
        melt=melt,
    )
    if melt is None:
        return base
    if melt.problem:
        return replace(base, status="unreadable")
    tol = params.tm_tolerance_c
    counted = [p for p in melt.peaks if floor is None or p.prominence >= floor]
    if kind in JUDGED and expected is not None:
        # the product is the most prominent peak within the tolerance (rdmlpython's true peak);
        # without one, the most prominent peak is the well's main peak
        window = [p for p in counted if abs(p.tm - expected) <= tol]
        if window:
            product = window[0]
            counted = [product, *(p for p in counted if p is not product)]
    total = sum(p.prominence for p in counted)
    shares = tuple(round(p.prominence / total, 6) if total > 0 else 0.0 for p in counted)
    extra = tuple(
        p for p, s in zip(counted[1:], shares[1:], strict=True) if s >= params.extra_peak_share
    )
    main = counted[0] if counted else None
    offset = round(main.tm - expected, 4) if main is not None and expected is not None else None
    base = replace(base, peaks=tuple(counted), shares=shares, extra=extra, offset=offset)
    if kind in JUDGED:
        if not amplified:
            return replace(base, status="not_amplified")
        if main is None:
            return replace(base, status="no_peak")
        if offset is not None and abs(offset) > tol:
            return replace(base, status="tm_off")
        if extra:
            return replace(base, status="extra_peak")
        return replace(base, status="one_product")
    if kind in NO_TEMPLATE:
        if main is None:
            return replace(base, status="no_product")
        if expected is None:
            return replace(base, status="unclassified")
        weighty = [main, *extra]
        if any(abs(p.tm - expected) <= tol for p in weighty):
            return replace(base, status="product")
        if main.tm < expected:
            return replace(base, status="dimer")
        return replace(base, status="other_product")
    return replace(base, status="not_judged")


def judge(table: pd.DataFrame, melt: MeltData, params: MeltParams | None = None) -> list[AssayMelt]:
    """:func:`judge_assay` for every plate x target of ``table`` that has a melt curve."""
    params = params or MeltParams()
    if not melt.has_melt or table.empty:
        return []
    with_melt = {(run_id, target) for run_id, _, target in melt.wells}
    groups = [
        (str(run_id), str(target), rows)
        for (run_id, target), rows in table.groupby(["run_id", "target"], sort=False)
        if (str(run_id), str(target)) in with_melt
    ]
    out = [judge_assay(run_id, target, rows, melt, params) for run_id, target, rows in groups]
    heights: dict[str, list[float]] = {}
    for a in out:
        if a.reference and a.reference_height is not None:
            heights.setdefault(a.run_id, []).append(a.reference_height)
    return [
        judge_assay(g[0], g[1], g[2], melt, params, _median(heights.get(a.run_id, ())))
        if not a.reference and a.run_id in heights
        else a
        for g, a in zip(groups, out, strict=True)
    ]


@dataclass(frozen=True)
class TargetMelt:
    """One target across the plates: its product's median Tm and range."""

    target: str
    n_plates: int
    n_wells: int
    median_tm: float | None
    min_tm: float | None
    max_tm: float | None


def target_summaries(assays: Iterable[AssayMelt]) -> list[TargetMelt]:
    """Per target, over every plate: the main-peak Tm of the wells each plate's median used."""
    by_target: dict[str, list[AssayMelt]] = {}
    for assay in assays:
        by_target.setdefault(assay.target, []).append(assay)
    out = []
    for target, items in by_target.items():
        tms = []
        for assay in items:
            keys = set(assay.reference) if assay.median_tm is not None else set()
            tms += [w.melt.peaks[0].tm for w in assay.wells if w.key in keys and w.melt]
        out.append(
            TargetMelt(
                target=target,
                n_plates=len(items),
                n_wells=len(tms),
                median_tm=round(float(np.median(tms)), 4) if tms else None,
                min_tm=round(min(tms), 4) if tms else None,
                max_tm=round(max(tms), 4) if tms else None,
            )
        )
    return out


def study_melt(
    source: str | Path,
    settings: Any = None,
    params: MeltParams | None = None,
) -> tuple[MeltData, list[AssayMelt]]:
    """A study's melt curves and calls: the per-well table re-typed by its design, then judged.

    ``settings`` is the study's :class:`qpilot.qpcr.study.StudySettings` (default: the demo's);
    the per-well table comes from the curve cache, as the Run Gate reads it.
    """
    from qpilot.qpcr.curves import analyse_study
    from qpilot.qpcr.designs import design_curves
    from qpilot.qpcr.study import StudySettings

    settings = settings or StudySettings()
    melt = read_melt(source, settings.experiment_id)
    if not melt.has_melt:
        return melt, []
    curves = analyse_study(source, settings.experiment_id, settings.candidates, settings.curves)
    table = design_curves(curves, settings.design) if settings.design is not None else curves
    return melt, judge(table, melt, params)


__all__ = [
    "DYE_CHEMISTRIES",
    "EMPTY",
    "JUDGED",
    "METHOD_CARD",
    "NO_TEMPLATE",
    "NTC_FLAGS",
    "STUDY_FLAGS",
    "AssayMelt",
    "MeltCurve",
    "MeltData",
    "MeltError",
    "MeltParams",
    "MeltSettings",
    "Peak",
    "TargetMelt",
    "WellCall",
    "WellMelt",
    "analyse_curve",
    "judge",
    "judge_assay",
    "read_melt",
    "study_melt",
    "target_summaries",
]
