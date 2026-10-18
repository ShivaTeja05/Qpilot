"""Known-answer validation, round 2: digital-PCR truth, four instruments, intervals that cover.

The first round (:mod:`qsim.validate`) scored every analysis of the AMC dilution series against
the nominal ng ratio. The review ruled that nominal truth cannot separate the efficiency options
and asked for three changes (``docs/review/00-judge-ruling.md`` sections 8-9). This module makes
them:

**V1, bias for each choice, against dPCR.** Truth is the QX200 dPCR ratio of the same tubes
(:mod:`qsim.truth`), reported for each input level. Five plates on four machines:

======================  ===================================  =========================  ========
plate                   experiment                           instrument                 truth
======================  ===================================  =========================  ========
``dkfz``                dPCR - DKFZ (Aug 2025), 4 assays     LightCycler 480 II, DKFZ   dPCR
``amc``                 DNA Dilution - AMC (Dec 2024), 38    LightCycler 480 II, AMC    dPCR
                        assay x mix runs
``volume_lc480``        Volumes and Machines (Feb 2024)      LightCycler 480 II, AMC    nominal
``volume_qs6``          Volumes and Machines (Mar 2024)      QuantStudio 6 Flex, EMBL   nominal
``volume_stepone``      Volumes and Machines (Mar 2024)      StepOne, EMBL              nominal
======================  ===================================  =========================  ========

The instrument comparison (``volume_machine.rdml``) used an earlier DNA dilution series that
dPCR never measured, so its truth is the pipetted ratio, with an error bar taken from how far
nominal ratios sat from dPCR on the measured series. The two EMBL plates were pipetted from the
same reaction tubes, so they differ only by instrument.

**Pass rules, fixed before scoring:** the preferred efficiency option (LinRegPCR assay mean,
the baseline) has median |error| <= 0.15 log2 on at least two machines; the Spearman
correlation between the spread across defensible analyses and the baseline's |error| is >= 0.3
within each input level (else "spread is a warning" is dropped).

**V2, intervals that cover the truth.** The replicate (Welch) interval ignores two errors every
well of an assay shares: the estimated efficiency, which multiplies the Cq difference, and the
premix each level's replicates were pipetted from. The propagated interval adds, by the delta
method (Bilgrau et al. 2016):

    var = se_replicates^2 + dCq^2 * (se_log2E^2 + tau^2) + 2 * sd_level^2

``se_log2E`` is the within-run SE of log2 of the efficiency (LinRegPCR's SD of well efficiencies
over sqrt(n), or the standard-curve slope's SE). ``tau`` (a per-run efficiency error) and
``sd_level`` (a per-level premix error) are the run effect. They are estimated without any
truth, from how estimates of the same pair of tubes scatter across assays, mixes and machines
beyond their own SE, and each plate group is scored with components estimated from the *other*
groups (leave-one-group-out), so no plate's interval is tuned on its own truth. The scatter is
measured robustly (MAD). That choice was made after the first run: with the plain variance, five
AMC assays with no usable dilution response (standard-curve efficiency 2.2 to 1.9e5) set every
interval's width. Both estimators, in and out of sample, are reported. Degrees of
freedom are Satterthwaite's, with the added components treated as known. The coverage test
compares the error with the interval widened by the truth's own SE (dPCR Poisson and well
error, or the nominal error bar). Pass: at least 90 % of baseline intervals contain the truth.

**V2 addendum, efficiency calibration.** :func:`calibrate` corrects the assay-mean efficiency by
one per-cycle offset, log2 E + delta. The offset is fitted on the dPCR-measured dilution series
(:func:`series_offsets`, :func:`efficiency_offset`) of the *other* plate groups
(:func:`calibration_training`) and scored under the same pass rule. The method and four variants
were fixed before any calibrated number was computed (recorded in the session notes, not in a
separate plan commit); the SE-free diagnostic variant was added after the primary result. It is
a validation variant, not an analysis option, so no tier changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize, stats

from qsim import truth as dpcr_truth
from qsim.data import STD_E_RANGE
from qsim.validate import BASELINE, _std_curve, load, run

DATA = Path(__file__).resolve().parents[2] / "data" / "untergasser"
BIAS_LIMIT = 0.15  # log2: the preferred efficiency option's median |error|
SPEARMAN_LIMIT = 0.3
COVERAGE_TARGET = 0.90
MIN_CASES = 8  # cases needed for a within-level correlation

GDNA = {
    "genomic DNA 20ng": ("gDNA", "20", 20.0),
    "genomic DNA 7ng": ("gDNA", "7", 7.0),
    "genomic DNA 2ng": ("gDNA", "2", 2.0),
    "genomic DNA 0.7ng": ("gDNA", "0.7", 0.7),
    "genomic DNA 0.2ng": ("gDNA", "0.2", 0.2),
}
GDNA_PAIRS = [
    ("genomic DNA 20ng", "genomic DNA 7ng"),
    ("genomic DNA 7ng", "genomic DNA 2ng"),
    ("genomic DNA 2ng", "genomic DNA 0.7ng"),
    ("genomic DNA 0.7ng", "genomic DNA 0.2ng"),
    ("genomic DNA 20ng", "genomic DNA 0.7ng"),
    ("genomic DNA 20ng", "genomic DNA 0.2ng"),
]
EMBL = {"EMBL DNA 20ng": ("EMBL", "EMBL 20", 20.0)}
AMPLICON = {
    f"Dil 1:10 - 10e{k}": ("amplicon", f"1e{k}", 10.0**k) for k in (5, 4, 3, 2)
}  # the freshly made 1:10 standard; the "Freeze" aliquots are not used
AMPLICON_PAIRS = [
    ("Dil 1:10 - 10e5", "Dil 1:10 - 10e4"),
    ("Dil 1:10 - 10e4", "Dil 1:10 - 10e3"),
    ("Dil 1:10 - 10e3", "Dil 1:10 - 10e2"),
    ("Dil 1:10 - 10e4", "Dil 1:10 - 10e2"),
]
VOLUME = {
    "gDNA 0.2ng/ul": ("gDNA", "0.2", 0.2),
    "gDNA 1ng/ul": ("gDNA", "1", 1.0),
    "gDNA 2ng/ul": ("gDNA", "2", 2.0),
    "gDNA 4ng/ul": ("gDNA", "4", 4.0),
    "gDNA 8ng/ul": ("gDNA", "8", 8.0),
}  # the 0.5 ng/µl wells come from a separate one-mix tube and are left out
VOLUME_PAIRS = [
    ("gDNA 1ng/ul", "gDNA 0.2ng/ul"),
    ("gDNA 2ng/ul", "gDNA 1ng/ul"),
    ("gDNA 4ng/ul", "gDNA 2ng/ul"),
    ("gDNA 8ng/ul", "gDNA 4ng/ul"),
    ("gDNA 4ng/ul", "gDNA 0.2ng/ul"),
]


@dataclass(frozen=True)
class Group:
    """Samples measured on one plate under one kind of truth, and the pairs compared."""

    levels: dict[str, tuple[str, str, float]]  # sample -> (series, label, nominal amount)
    pairs: list[tuple[str, str]]
    unit: str


@dataclass(frozen=True)
class Plate:
    key: str
    file: str
    experiment: str
    machine: str
    tubes: str  # plates sharing DNA tubes; the run effect is estimated across them
    truth: str  # "dPCR" or "nominal"
    groups: tuple[Group, ...]
    targets: tuple[str, ...] = field(default=())  # empty = every target


PLATES = (
    Plate(
        "dkfz",
        "large_DNA_dilutions.rdml",
        "dPCR - DKFZ",
        "LightCycler 480 II, DKFZ",
        "dkfz",
        "dPCR",
        (
            Group({**GDNA, **EMBL}, [*GDNA_PAIRS, ("EMBL DNA 20ng", "genomic DNA 20ng")], "ng"),
            Group(AMPLICON, AMPLICON_PAIRS, "copies"),
        ),
    ),
    Plate(
        "amc",
        "amplicon_primer_mix.rdml",
        "DNA Dilution - AMC",
        "LightCycler 480 II, AMC",
        "amc",
        "dPCR",
        (Group(GDNA, GDNA_PAIRS, "ng"),),
    ),
    Plate(
        "volume_lc480",
        "volume_machine.rdml",
        "AMC Amsterdam NL - 384 Wells",
        "LightCycler 480 II, AMC",
        "volume",
        "nominal",
        (Group(VOLUME, VOLUME_PAIRS, "ng/µl"),),
        ("FSTL1",),
    ),
    Plate(
        "volume_qs6",
        "volume_machine.rdml",
        "EMBL Heidelberg DE - 384 Wells",
        "QuantStudio 6 Flex, EMBL",
        "volume",
        "nominal",
        (Group(VOLUME, VOLUME_PAIRS, "ng/µl"),),
        ("FSTL1",),
    ),
    Plate(
        "volume_stepone",
        "volume_machine.rdml",
        "EMBL Heidelberg DE - 96 Wells",
        "StepOne, EMBL",
        "volume",
        "nominal",
        (Group(VOLUME, VOLUME_PAIRS, "ng/µl"),),
        ("FSTL1",),
    ),
)


def _truth_fn(plate: Plate, group: Group, dpcr: pd.DataFrame, sd_well: float, sd_nominal: float):
    name = dpcr_truth.qpcr_name
    nominal = {name(s): v[2] for s, v in group.levels.items()}
    cache: dict[tuple[str, str], tuple[float, float, str] | None] = {}

    def truth(run_id: str, target: str, hi: str, lo: str):
        if (hi, lo) not in cache:
            if plate.truth == "nominal":
                cache[hi, lo] = (float(np.log2(nominal[hi] / nominal[lo])), sd_nominal, "nominal")
            else:
                t = dpcr_truth.pair_truth(dpcr, hi, lo, sd_well)
                cache[hi, lo] = None if t is None else (t.log2, t.se, t.source)
        return cache[hi, lo]

    return truth


def table(data: Path = DATA) -> tuple[pd.DataFrame, dict]:
    """Every analysis of every case on every plate, with its truth; plus the truth model."""
    dpcr = dpcr_truth.load_dpcr(data)
    sd_well = dpcr_truth.dpcr_well_sd(dpcr)
    name = dpcr_truth.qpcr_name
    adjacent = [
        (name(hi), name(lo), float(np.log2(GDNA[hi][2] / GDNA[lo][2]))) for hi, lo in GDNA_PAIRS[:4]
    ]
    sd_nominal = dpcr_truth.nominal_sd(dpcr, sd_well, adjacent)
    parts = []
    for plate in PLATES:
        for group in plate.groups:
            levels = {name(s): v[2] for s, v in group.levels.items()}
            series = {name(s): v[0] for s, v in group.levels.items()}
            labels = {name(s): v[1] for s, v in group.levels.items()}
            curves = load(data / plate.file, plate.experiment, levels, series)
            if plate.targets:
                curves = curves[curves["target"].isin(plate.targets)]
            pairs = [(name(hi), name(lo)) for hi, lo in group.pairs]
            t = run(
                curves,
                pairs,
                _truth_fn(plate, group, dpcr, sd_well, sd_nominal),
                labels,
                group.unit,
            )
            e_full = std_curve_qc(curves, series[pairs[0][1]])
            t["std_e_all_levels"] = [
                e_full.get(k, np.nan) for k in zip(t["run"], t["assay"], strict=True)
            ]
            t["dilution_qc"] = t["std_e_all_levels"].between(*STD_E_RANGE)
            t.insert(0, "plate", plate.key)
            t.insert(1, "machine", plate.machine)
            t.insert(2, "tubes", plate.tubes)
            t.insert(3, "truth_kind", plate.truth)
            parts.append(t)
    unresolved = {}
    for hi, lo in [*GDNA_PAIRS, *AMPLICON_PAIRS]:
        tr = dpcr_truth.pair_truth(dpcr, name(hi), name(lo), sd_well)
        if tr is not None and not np.isfinite(tr.log2):
            unresolved[f"{name(hi)}|{name(lo)}"] = {k: round(v, 4) for k, v in tr.per_assay.items()}
    model = {
        "dpcr_well_sd_log2": round(sd_well, 4),
        "nominal_truth_sd_log2": round(sd_nominal, 4),
        "dpcr_upper_copies_per_20ul": dpcr_truth.UPPER_COPIES,
        "dpcr_discordant_log2": dpcr_truth.DISCORDANT_LOG2,
        "unresolved_pairs_dpcr_by_assay": unresolved,
        "dpcr_wells": dpcr.drop(columns=["status"]).round(4).to_dict("records"),
    }
    return pd.concat(parts, ignore_index=True), model


def _baseline(t: pd.DataFrame) -> pd.DataFrame:
    return t[
        (t["efficiency"] == BASELINE[0])
        & (t["replicates"] == BASELINE[1])
        & (t["flagged"] == BASELINE[2])
    ]


def run_effect(base: pd.DataFrame, robust: bool = True) -> dict:
    """Per-level premix SD and per-run efficiency SD (log2 per cycle), estimated without truth.

    Each set of estimates of one pair of tubes (same ``tubes`` and pair, three or more runs or
    assays) gives one point: the spread of the estimates beyond what their own replicate and
    within-run efficiency SEs explain. The points are regressed on [2, dCq^2] with non-negative
    coefficients, weighted by set size. ``robust`` uses (1.4826 MAD)^2 about the median, so a
    few failed assays (no dilution response at all) do not set every interval's width; the plain
    version uses the variance about the mean.
    """
    y, x, w = [], [], []
    for _, g in base.dropna(subset=["se_rep", "se_log2e", "estimate_log2"]).groupby(
        ["tubes", "pair"]
    ):
        n = len(g)
        if n < 3:
            continue
        est = g["estimate_log2"]
        own = g["se_rep"] ** 2 + (g["dcq"] * g["se_log2e"]) ** 2
        if robust:
            spread = (1.4826 * (est - est.median()).abs().median()) ** 2
            own_v = own.median()
        else:
            spread = est.var(ddof=1)
            own_v = own.mean()
        y.append(spread - own_v)
        x.append([2.0, float(g["dcq"].abs().median()) ** 2])
        w.append(np.sqrt(n))
    if len(y) < 2:
        return {"sd_level_log2": 0.0, "sd_log2e_run": 0.0, "sets": len(y)}
    wv = np.array(w)
    coef, _ = optimize.nnls(np.array(x) * wv[:, None], np.array(y) * wv)
    return {
        "sd_level_log2": float(np.sqrt(coef[0])),
        "sd_log2e_run": float(np.sqrt(coef[1])),
        "sets": len(y),
    }


def std_curve_qc(curves: pd.DataFrame, series: str) -> dict[tuple[str, str], float]:
    """Standard-curve efficiency of each (run, assay) over every level of ``series``; qsim's
    existing plausibility rule (:data:`qsim.data.STD_E_RANGE`) says outside 1.6-2.2 a dilution
    response is not usable."""
    return {
        key: _std_curve(assay, ("", ""), series)[0]
        for key, assay in curves.groupby(["run_id", "target"])
    }


def propagate(base: pd.DataFrame, components: dict[str, dict]) -> pd.DataFrame:
    """Add the propagated interval to baseline rows; ``components`` is keyed by ``tubes``. An
    optional ``sd_plate_pair_log2`` adds the plate x pair term of :func:`plate_pair_term`, and an
    optional ``poisson_b`` adds b times the rows' ``poisson_x`` (:func:`poisson_x`)."""
    out = base.copy()
    sd_level = out["tubes"].map(lambda k: components[k]["sd_level_log2"])
    tau = out["tubes"].map(lambda k: components[k]["sd_log2e_run"])
    sd_pp = out["tubes"].map(lambda k: components[k].get("sd_plate_pair_log2", 0.0))
    poisson = out["tubes"].map(lambda k: components[k].get("poisson_b", 0.0))
    if "poisson_x" in out:  # only rows given a Poisson slope use their scale (it may be NaN)
        poisson = (poisson * out["poisson_x"]).where(poisson > 0, 0.0)
    else:
        poisson = 0.0
    rep = out["se_rep"] ** 2
    added = (
        out["dcq"] ** 2 * (out["se_log2e"].fillna(0.0) ** 2 + tau**2)
        + 2 * sd_level**2
        + sd_pp**2
        + poisson
    )
    var = rep + added
    df = var**2 / (rep**2 / out["df"])
    out["se_new"] = np.sqrt(var)
    out["df_new"] = df
    half = stats.t.ppf(0.975, df) * out["se_new"]
    out["new_lo"], out["new_hi"] = out["estimate_log2"] - half, out["estimate_log2"] + half
    var_t = var + out["truth_se"].fillna(0.0) ** 2
    df_t = var_t**2 / (rep**2 / out["df"])
    out["half_with_truth"] = stats.t.ppf(0.975, df_t) * np.sqrt(var_t)
    err = out["error_log2"].abs()
    out["in_old_ci"] = (out["ci_lo"] <= out["truth_log2"]) & (out["truth_log2"] <= out["ci_hi"])
    out["in_new_ci"] = err <= half
    out["in_new_ci_with_truth"] = err <= out["half_with_truth"]
    return out


def _template(pair: pd.Series) -> np.ndarray:
    """Which template a pair label measures: the amplicon standard or genomic DNA (the EMBL
    pair belongs to the genomic group; its Cq difference is near zero, so it carries no weight)."""
    return np.where(pair.str.endswith(" copies"), "amplicon", "genomic")


def series_offsets(base: pd.DataFrame) -> pd.DataFrame:
    """Per-cycle efficiency offset of each dilution series, fitted on its truth.

    A series is one (plate, run, assay, template). Its offset ``delta`` (log2 per cycle) is the
    correction of the assay-mean efficiency, log2 E + delta, that best moves the baseline onto the
    truth. The calibrated estimate is ``estimate - dcq * delta``, so delta is the least-squares
    slope through the origin of error on dcq over the series' resolved pairs.
    """
    keys = ["plate", "tubes", "truth_kind", "run", "assay", "template"]
    b = base[np.isfinite(base["truth_log2"]) & np.isfinite(base["dcq"])]
    b = b.assign(template=_template(b["pair"]))
    rows = []
    for key, g in b.groupby(keys):
        sxx = float((g["dcq"] ** 2).sum())
        if sxx > 0:
            delta = float((g["dcq"] * g["error_log2"]).sum() / sxx)
            rows.append([*key, len(g), delta])
    return pd.DataFrame(rows, columns=[*keys, "pairs", "delta_log2e"])


def efficiency_offset(offsets: pd.DataFrame) -> dict:
    """The pooled offset: the median over series, with the median's SE (1.2533 x 1.4826 MAD over
    sqrt n). No series gives no correction."""
    d = offsets["delta_log2e"]
    if d.empty:
        return {"delta_log2e": 0.0, "se_delta_log2e": 0.0, "series": 0}
    mad = 1.4826 * float((d - d.median()).abs().median())
    return {
        "delta_log2e": float(d.median()),
        "se_delta_log2e": 1.2533 * mad / float(np.sqrt(len(d))),
        "series": int(len(d)),
    }


def calibration_training(
    base: pd.DataFrame,
    scored: str,
    kinds: tuple[str, ...] = ("dPCR",),
    templates: tuple[str, ...] | None = None,
    disjoint: bool = False,
    held_out: bool = True,
) -> pd.DataFrame:
    """Baseline rows a calibration for the ``scored`` tube group may be fitted on.

    ``held_out`` leaves the scored group out, so no plate is calibrated on its own truth.
    ``disjoint`` also drops every dPCR pair that uses a tube whose dPCR truth the scored group is
    scored against: the AMC and DKFZ plates share the genomic tubes and hence the same truth, and
    a calibration fitted on one would carry that truth's own error into the other.
    """
    train = base[base["tubes"] != scored] if held_out else base
    train = train[train["truth_kind"].isin(kinds)]
    if templates is not None:
        train = train[np.isin(_template(train["pair"]), templates)]
    if disjoint:
        own = base[
            (base["tubes"] == scored)
            & (base["truth_kind"] == "dPCR")
            & np.isfinite(base["truth_log2"])
        ]
        tubes = set(own["hi"]) | set(own["lo"])
        shared = (train["truth_kind"] == "dPCR") & (
            train["hi"].isin(tubes) | train["lo"].isin(tubes)
        )
        train = train[~shared]
    return train


def calibrate(base: pd.DataFrame, offsets: dict[str, dict]) -> pd.DataFrame:
    """Baseline rows with the assay-mean efficiency corrected by a per-cycle log2 offset; the
    offset's SE joins the within-run SE of log2 E. ``offsets`` is keyed by ``tubes``."""
    out = base.copy()
    delta = out["tubes"].map(lambda k: offsets[k]["delta_log2e"])
    se = out["tubes"].map(lambda k: offsets[k]["se_delta_log2e"])
    shift = -out["dcq"] * delta
    for col in ("estimate_log2", "error_log2", "ci_lo", "ci_hi"):
        out[col] = out[col] + shift
    out["se_log2e"] = np.sqrt(out["se_log2e"].fillna(0.0) ** 2 + se**2)
    out["calibration_log2e"] = delta
    return out


#: the dilution series each tube group measured. AMC and DKFZ used the same December 2024 tubes.
#: The Feb 2024 instrument comparison is one series but not one set of tubes: only QuantStudio and
#: StepOne share reaction tubes; the LC480 plate (AMC) used its own premixes, with its 0.2 and
#: 0.5 ng/µl levels from a separate 1:100 dilution. Its plate x pair excess therefore mixes
#: dilution error with instrument disagreement.
PHYSICAL_SERIES = {"amc": "gDNA Dec 2024", "dkfz": "gDNA Dec 2024", "volume": "gDNA Feb 2024"}


def _pair_excess(base: pd.DataFrame) -> pd.DataFrame:
    """Per tube pair measured on two or more plates: the excess variance across plates.

    For each pair and plate: m is the median baseline estimate over runs, and s^2 the median over
    runs of (se_rep^2 + dCq^2 se_log2E^2) divided by the number of runs. The excess is the sample
    variance of m across plates minus the mean s^2. Pairs dPCR could not resolve count too: no
    truth is used.
    """
    b = base.dropna(subset=["estimate_log2"])
    b = b.assign(
        own=b["se_rep"] ** 2 + (b["dcq"] * b["se_log2e"].fillna(0.0)) ** 2,
        series=b["tubes"].map(PHYSICAL_SERIES),
    )
    rows = []
    for (series, hi, lo), pair in b.groupby(["series", "hi", "lo"]):
        plates = pair.groupby("plate").agg(
            m=("estimate_log2", "median"), s2=("own", "median"), n=("own", "size")
        )
        if len(plates) >= 2:
            excess = float(plates["m"].var(ddof=1) - (plates["s2"] / plates["n"]).mean())
            rows.append([series, hi, lo, pair["pair"].iloc[0], excess])
    return pd.DataFrame(rows, columns=["series", "hi", "lo", "pair", "excess"])


def plate_pair_term(base: pd.DataFrame) -> dict:
    """Plate x pair SD (log2), estimated without truth: sqrt(max(0, mean excess variance over the
    pairs measured on two or more plates)), see :func:`_pair_excess`."""
    e = _pair_excess(base)
    sd = float(np.sqrt(max(0.0, e["excess"].mean()))) if len(e) else 0.0
    return {
        "sd_plate_pair_log2": sd,
        "pairs": len(e),
        "excess_variance_by_pair": {
            f"{r.series}: {r.pair}": round(r.excess, 4) for r in e.itertuples()
        },
    }


COPIES_PER_NG = 303  # haploid human genome copies per ng (3.3 pg each)
REACTION_UL = 10  # reaction volume of the instrument comparison, whose levels are ng/µl
POISSON_B = 1 / np.log(2) ** 2  # variance of log2 of a Poisson count of c copies is 1 / (c ln^2 2)


def copies_per_reaction() -> dict[str, float]:
    """Nominal template copies per reaction of every sample, from the design only (never dPCR);
    amplicon labels are read as copies per reaction."""
    scale = {"ng": COPIES_PER_NG, "ng/µl": COPIES_PER_NG * REACTION_UL, "copies": 1.0}
    out = {}
    for plate in PLATES:
        for group in plate.groups:
            for sample, (_, _, amount) in group.levels.items():
                out[dpcr_truth.qpcr_name(sample)] = amount * scale[group.unit]
    return out


def poisson_x(rows: pd.DataFrame) -> pd.Series:
    """The Poisson scale of each row's pair: 1/c_hi + 1/c_lo, c in copies per reaction."""
    c = copies_per_reaction()
    return 1 / rows["hi"].map(c) + 1 / rows["lo"].map(c)


def poisson_slope(base: pd.DataFrame) -> float:
    """Least-squares slope through the origin of the pairs' excess variance on their Poisson scale."""
    e = _pair_excess(base)
    if e.empty:
        return 0.0
    x = poisson_x(e).to_numpy()
    return float(x @ e["excess"].to_numpy() / (x @ x))


def coverage_ci(x: pd.DataFrame, draws: int = 2000, seed: int = 2026, level: float = 0.90) -> dict:
    """Coverage with truth SE and its cluster-bootstrap interval: the distinct truths (a pair of
    tubes under one kind of truth) are resampled with replacement, with all their cases."""
    key = x["truth_kind"] + "|" + x["hi"] + "|" + x["lo"]
    hit = x.groupby(key)["in_new_ci_with_truth"].agg(["sum", "size"])
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(hit), size=(draws, len(hit)))
    share = hit["sum"].to_numpy()[pick].sum(1) / hit["size"].to_numpy()[pick].sum(1)
    lo, hi = np.quantile(share, [(1 - level) / 2, (1 + level) / 2])
    return {
        "truths": int(len(hit)),
        "draws": draws,
        "seed": seed,
        f"coverage_{level:.0%}_cluster_bootstrap": [round(float(lo), 3), round(float(hi), 3)],
    }


def cover(x: pd.DataFrame) -> dict:
    return {
        "cases": int(len(x)),
        "old_welch_ci": _share(x["in_old_ci"]),
        "propagated_ci": _share(x["in_new_ci"]),
        "propagated_ci_with_truth_se": _share(x["in_new_ci_with_truth"]),
        "median_half_width_old": round(float(((x["ci_hi"] - x["ci_lo"]) / 2).median()), 3),
        "median_half_width_new": round(float(((x["new_hi"] - x["new_lo"]) / 2).median()), 3),
    }


def gap_report(x: pd.DataFrame) -> dict:
    """What every test of ``31-research-closing-the-coverage-gap.md`` reports."""
    return {
        "all": cover(x) | coverage_ci(x),
        "by_group": {k: cover(g) for k, g in x.groupby("tubes", sort=False)},
        "by_plate": {k: cover(g) for k, g in x.groupby("plate", sort=False)},
        "by_truth": {k: cover(g) for k, g in x.groupby("pair", sort=False)},
        "bias_by_machine": {k: _bias(g["error_log2"]) for k, g in x.groupby("machine", sort=False)},
        "pass": (_share(x["in_new_ci_with_truth"]) or 0) >= COVERAGE_TARGET,
    }


def _share(s: pd.Series) -> float | None:
    s = s.dropna()
    return round(float(s.mean()), 3) if len(s) else None


def _bias(errors: pd.Series) -> dict:
    e = errors.dropna()
    if e.empty:
        return {"cases": 0}
    return {
        "cases": int(len(e)),
        "median_abs_error_log2": round(float(e.abs().median()), 3),
        "median_bias_log2": round(float(e.median()), 3),
        "share_within_0.15": round(float((e.abs() <= BIAS_LIMIT).mean()), 3),
    }


def score(t: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    resolved = t[np.isfinite(t["truth_log2"])]
    dpcr = resolved[resolved["truth_kind"] == "dPCR"]
    base = _baseline(t)
    out: dict = {}

    # V1: every choice against dPCR truth, by input level
    by_choice: dict = {}
    for col in ("efficiency", "replicates", "flagged"):
        by_choice[col] = {
            opt: {"all_levels": _bias(g["error_log2"])}
            | {pair: _bias(p["error_log2"]) for pair, p in g.groupby("pair", sort=False)}
            for opt, g in dpcr.groupby(col)
        }
    out["by_choice_dpcr"] = by_choice

    # V1: each efficiency option on each plate, other choices at the baseline
    others = resolved[
        (resolved["replicates"] == BASELINE[1]) & (resolved["flagged"] == BASELINE[2])
    ]
    plates = {}
    for key, g in others.groupby("plate", sort=False):
        first = g.iloc[0]
        b = g[g["efficiency"] == BASELINE[0]]
        plates[key] = {
            "machine": first["machine"],
            "truth": first["truth_kind"],
            "efficiency": {e: _bias(x["error_log2"]) for e, x in g.groupby("efficiency")},
            "baseline_by_level": {
                p: _bias(x["error_log2"]) for p, x in b.groupby("pair", sort=False)
            },
        }
        plates[key]["passes"] = bool(
            plates[key]["efficiency"][BASELINE[0]].get("median_abs_error_log2", 9) <= BIAS_LIMIT
        )
    out["plates"] = plates
    machines: dict[str, list[str]] = {}
    for key, p in plates.items():
        if p["passes"]:
            machines.setdefault(p["machine"], []).append(f"{key} ({p['truth']} truth)")
    dpcr_machines = sorted(
        {p["machine"] for p in plates.values() if p["passes"] and p["truth"] == "dPCR"}
    )
    out["v1_bias"] = {
        "rule": f"LinRegPCR assay-mean efficiency, median |error| <= {BIAS_LIMIT} log2 on >= 2 machines",
        "machines_passing": machines,
        "machines_passing_with_dpcr_truth": dpcr_machines,
        "models_passing": sorted({m.split(",")[0] for m in machines}),
        "pass": len(machines) >= 2,
    }

    # V1: does spread across defensible analyses warn of a wrong baseline, within each level?
    cases = []
    for key, case in dpcr.groupby(["plate", "run", "assay", "pair"], sort=False):
        b = _baseline(case)
        d = case[case["defensible"]]
        if b.empty or d.empty:
            continue
        cases.append(
            {
                "pair": key[3],
                "dilution_qc": bool(case["dilution_qc"].iloc[0]),
                "spread_log2": float(d["estimate_log2"].max() - d["estimate_log2"].min()),
                "baseline_abs_error": abs(float(b["error_log2"].iloc[0])),
                "truth_in_range": bool(
                    d["estimate_log2"].min() <= b["truth_log2"].iloc[0] <= d["estimate_log2"].max()
                ),
            }
        )
    c = pd.DataFrame(cases)

    def by_level(c: pd.DataFrame) -> dict:
        levels = {}
        for pair, sub in c.groupby("pair", sort=False):
            entry: dict = {"cases": int(len(sub))}
            if len(sub) >= MIN_CASES:
                r, p = stats.spearmanr(sub["spread_log2"], sub["baseline_abs_error"])
                entry |= {"spearman": round(float(r), 3), "p": float(p)}
            levels[pair] = entry
        return levels

    levels = by_level(c)
    tested = [v["spearman"] for v in levels.values() if "spearman" in v]
    rho, p = stats.spearmanr(c["spread_log2"], c["baseline_abs_error"])
    qc = c[c["dilution_qc"]]
    rho_qc, p_qc = stats.spearmanr(qc["spread_log2"], qc["baseline_abs_error"])
    out["v1_warning"] = {
        "rule": f"Spearman(spread, baseline |error|) >= {SPEARMAN_LIMIT} within each level with >= {MIN_CASES} cases",
        "pooled": {"spearman": round(float(rho), 3), "p": float(p), "cases": int(len(c))},
        "by_level": levels,
        "pass": bool(tested) and min(tested) >= SPEARMAN_LIMIT,
        "robustness_check_passing_dilution_qc": {
            "pooled": {"spearman": round(float(rho_qc), 3), "p": float(p_qc), "cases": len(qc)},
            "by_level": by_level(qc),
        },
        "truth_inside_range_of_defensible_analyses": _share(c["truth_in_range"]),
    }

    # V2: run effect (truth-free), leave-one-group-out, and coverage
    groups = sorted(base["tubes"].unique())

    def scored_with(robust: bool, lodo: bool) -> tuple[pd.DataFrame, dict]:
        if lodo:
            comp = {g: run_effect(base[base["tubes"] != g], robust) for g in groups}
        else:
            comp = dict.fromkeys(groups, run_effect(base, robust))
        parts = [propagate(base[base["tubes"] == g], {g: comp[g]}) for g in groups]
        x = pd.concat(parts, ignore_index=True)
        return x[np.isfinite(x["truth_log2"])], comp

    def rounded(comp: dict) -> dict:
        return {
            g: {k: round(v, 4) if isinstance(v, float) else v for k, v in r.items()}
            for g, r in comp.items()
        }

    ok, comp = scored_with(robust=True, lodo=True)
    variants = {}
    for name, robust, lodo in (
        ("robust_in_sample", True, False),
        ("plain_leave_one_group_out", False, True),
        ("plain_in_sample", False, False),
    ):
        x, c = scored_with(robust, lodo)
        variants[name] = {"components": rounded(c), "all": cover(x)}
    out["v2_coverage"] = {
        "rule": f"baseline 95 % interval with truth uncertainty contains the truth in >= {COVERAGE_TARGET:.0%} of cases",
        "method": "robust (MAD) run effect, each plate group scored with components from the other groups",
        "components": rounded(comp),
        "all": cover(ok),
        "passing_dilution_qc": cover(ok[ok["dilution_qc"]]),
        "failing_dilution_qc": cover(ok[~ok["dilution_qc"]]),
        "by_plate": {k: cover(g) for k, g in ok.groupby("plate", sort=False)},
        "by_level": {k: cover(g) for k, g in ok.groupby("pair", sort=False)},
        "other_estimators": variants,
        "pass": (_share(ok["in_new_ci_with_truth"]) or 0) >= COVERAGE_TARGET,
    }
    scored = ok

    # V2 addendum: calibrate the assay-mean efficiency on held-out dPCR-measured dilutions
    def calibrated_with(se: bool = True, **how) -> tuple[pd.DataFrame, dict]:
        cal = {
            g: efficiency_offset(series_offsets(calibration_training(base, g, **how)))
            for g in groups
        }
        if not se:
            cal = {g: c | {"se_delta_log2e": 0.0} for g, c in cal.items()}
        parts = [
            propagate(calibrate(base[base["tubes"] == g], {g: cal[g]}), {g: comp[g]})
            for g in groups
        ]
        x = pd.concat(parts, ignore_index=True)
        return x[np.isfinite(x["truth_log2"])], cal

    def bias_by(col: str, x: pd.DataFrame) -> dict:
        return {
            k: {
                "uncalibrated": _bias(ok.loc[g.index, "error_log2"]),
                "calibrated": _bias(g["error_log2"]),
            }
            for k, g in x.groupby(col, sort=False)
        }

    cal_ok, cal = calibrated_with()
    cal_ok.index = ok.index  # same groups in the same order, so rows line up with ``ok``
    cal_variants = {}
    for name, how in (
        ("truth_disjoint", {"disjoint": True}),
        ("with_nominal_truth_plates", {"kinds": ("dPCR", "nominal")}),
        ("genomic_only", {"templates": ("genomic",)}),
        ("in_sample", {"held_out": False}),
        ("diagnostic_offset_without_its_se", {"se": False}),
    ):
        x, c = calibrated_with(**how)
        x.index = ok.index
        cal_variants[name] = {
            "offsets": rounded(c),
            "all": cover(x),
            "by_plate": {k: cover(g) for k, g in x.groupby("plate", sort=False)},
            "bias_by_machine": bias_by("machine", x),
        }
    cal_variants["diagnostic_offset_without_its_se"]["why"] = (
        "added after the primary result, to explain it; not pre-registered; not counted"
    )
    every = series_offsets(base)
    machine_bias = bias_by("machine", cal_ok)
    out["efficiency_calibration"] = {
        "rule": out["v2_coverage"]["rule"],
        "method": (
            "log2 E_cal = log2 E_LinRegPCR + delta, one per-cycle offset for every run of a plate "
            "group: the median over the other groups' dPCR-measured dilution series of each "
            "series' least-squares offset; its SE joins the efficiency term; run effect as above"
        ),
        "preregistered": (
            "method and the truth_disjoint, with_nominal_truth_plates, genomic_only and in_sample "
            "variants fixed before any calibrated number was computed; written in the session "
            "notes, not committed separately (method, code and results share commit 56b4c8f); "
            "diagnostic_offset_without_its_se was added after the primary result"
        ),
        "offsets": rounded(cal),
        "series_offsets_descriptive": {
            f"{plate} {template}": {
                "series": int(len(g)),
                "median_delta_log2e": round(float(g["delta_log2e"].median()), 4),
                "mad_delta_log2e": round(
                    float(1.4826 * (g["delta_log2e"] - g["delta_log2e"].median()).abs().median()), 4
                ),
            }
            for (plate, template), g in every.groupby(["plate", "template"], sort=False)
        },
        "uncalibrated": cover(ok),
        "all": cover(cal_ok),
        "passing_dilution_qc": cover(cal_ok[cal_ok["dilution_qc"]]),
        "failing_dilution_qc": cover(cal_ok[~cal_ok["dilution_qc"]]),
        "by_plate": {k: cover(g) for k, g in cal_ok.groupby("plate", sort=False)},
        "by_level": {k: cover(g) for k, g in cal_ok.groupby("pair", sort=False)},
        "bias_by_machine": machine_bias,
        "bias_by_plate": bias_by("plate", cal_ok),
        "machines_within_bias_limit": {
            k: sorted(
                m
                for m, v in machine_bias.items()
                if v[k].get("median_abs_error_log2", 9) <= BIAS_LIMIT
            )
            for k in ("uncalibrated", "calibrated")
        },
        "variants": cal_variants,
        "pass": (_share(cal_ok["in_new_ci_with_truth"]) or 0) >= COVERAGE_TARGET,
    }
    scored = ok.assign(
        calibration_log2e=cal_ok["calibration_log2e"],
        estimate_log2_calibrated=cal_ok["estimate_log2"],
        error_log2_calibrated=cal_ok["error_log2"],
        half_with_truth_calibrated=cal_ok["half_with_truth"],
        in_calibrated_ci_with_truth=cal_ok["in_new_ci_with_truth"],
    )

    # Tests P1-P3 of 31-research-closing-the-coverage-gap.md, estimators fixed before scoring
    def held_out_term(g: str) -> dict:
        return plate_pair_term(base[base["tubes"].map(PHYSICAL_SERIES) != PHYSICAL_SERIES[g]])

    def score_rows(rows: pd.DataFrame, comp: dict) -> pd.DataFrame:
        x = pd.concat(
            [propagate(rows[rows["tubes"] == g], {g: comp[g]}) for g in groups], ignore_index=True
        )
        return x[np.isfinite(x["truth_log2"])]

    pp = {g: held_out_term(g) for g in groups}
    pp_all = plate_pair_term(base)
    std = t[
        (t["efficiency"] == "std_curve")
        & (t["replicates"] == BASELINE[1])
        & (t["flagged"] == BASELINE[2])
    ]
    std_comp = {g: run_effect(std[std["tubes"] != g], robust=True) for g in groups}

    def term(c: dict) -> dict:
        return {"sd_plate_pair_log2": c["sd_plate_pair_log2"]}

    lowest = {dpcr_truth.qpcr_name(n) for n in ("genomic DNA 0.2ng", "gDNA 0.2ng/ul")}
    no_low = base[~base["hi"].isin(lowest) & ~base["lo"].isin(lowest)]
    pp_no_low = {
        g: plate_pair_term(no_low[no_low["tubes"].map(PHYSICAL_SERIES) != PHYSICAL_SERIES[g]])
        for g in groups
    }
    p1 = score_rows(base, {g: comp[g] | term(pp[g]) for g in groups})
    p1_no_low = score_rows(base, {g: comp[g] | term(pp_no_low[g]) for g in groups})
    p1_in = score_rows(base, {g: comp[g] | term(pp_all) for g in groups})
    p2 = score_rows(std, std_comp)
    p3 = score_rows(std, {g: std_comp[g] | term(pp[g]) for g in groups})
    base_x = base.assign(poisson_x=poisson_x(base))
    b_held = {
        g: poisson_slope(base[base["tubes"].map(PHYSICAL_SERIES) != PHYSICAL_SERIES[g]])
        for g in groups
    }
    b_both = poisson_slope(base)
    p5 = score_rows(base_x, {g: comp[g] | {"poisson_b": POISSON_B} for g in groups})
    p5a = score_rows(base_x, {g: comp[g] | {"poisson_b": b_held[g]} for g in groups})
    p5b = score_rows(base_x, {g: comp[g] | {"poisson_b": b_both} for g in groups})
    out["coverage_gap_tests"] = {
        "plan": "docs/review/31-research-closing-the-coverage-gap.md (fixed before scoring)",
        "rule": out["v2_coverage"]["rule"],
        "reference_round_2": gap_report(ok),
        "p1_plate_pair_term": {
            "method": (
                "round-2 interval plus a plate x pair variance, estimated without truth from tube "
                "pairs measured on two or more plates; AMC and DKFZ use the volume series' term, "
                "the volume plates use the AMC/DKFZ series' term"
            ),
            "terms": {
                g: c | {"sd_plate_pair_log2": round(c["sd_plate_pair_log2"], 4)}
                for g, c in pp.items()
            },
            **gap_report(p1),
            "variant_one_term_from_both_series": {
                "term": pp_all | {"sd_plate_pair_log2": round(pp_all["sd_plate_pair_log2"], 4)},
                **gap_report(p1_in),
            },
            "post_hoc_sensitivity_term_without_lowest_tubes": {
                "why": (
                    "added after scoring: one pair with the lowest tube carries 71 % of the "
                    "instrument-comparison excess, and the two 0.2 ng pairs 62 % of the genomic "
                    "excess; not counted for the pass"
                ),
                "terms": {g: round(c["sd_plate_pair_log2"], 4) for g, c in pp_no_low.items()},
                **gap_report(p1_no_low),
            },
        },
        "p2_std_curve": {
            "method": (
                "standard-curve efficiency from the run's other nominal dilution levels "
                "(leave-pair-out, no dPCR); slope SE as the efficiency SE; robust run effect "
                "re-estimated on standard-curve rows, leave-one-group-out"
            ),
            "components": rounded(std_comp),
            "cases_without_slope_se": int(p2["se_log2e"].isna().sum()),
            **gap_report(p2),
        },
        "p3_std_curve_plus_plate_pair_term": gap_report(p3),
        "p5_poisson_plate_pair_term": {
            "method": (
                "round-2 interval plus (1/c_hi + 1/c_lo)/ln^2 2, one Poisson draw of each tube per "
                "plate; c = nominal copies per reaction from the design; nothing fitted"
            ),
            "plan": "pre-registered in docs/review/31 (commit 4b25cc5) before scoring",
            "poisson_b": round(POISSON_B, 4),
            "copies_per_reaction": {k: round(v, 1) for k, v in copies_per_reaction().items()},
            **gap_report(p5),
            "variant_p5a_b_fitted_on_other_series": {
                "poisson_b": {g: round(v, 3) for g, v in b_held.items()},
                **gap_report(p5a),
            },
            "variant_p5b_b_fitted_on_both_series": {
                "poisson_b": round(b_both, 3),
                **gap_report(p5b),
            },
        },
    }

    # dPCR could not settle these pairs: show the baseline against each candidate truth
    unresolved = {}
    ub = base[base["truth_source"] == "unresolved"]
    for pair, g in ub.groupby("pair", sort=False):
        first = g.iloc[0]
        nominal = _nominal_log2(first["pair"])
        unresolved[pair] = {
            "cases": int(len(g)),
            "baseline_median_log2": round(float(g["estimate_log2"].median()), 3),
            "nominal_log2": nominal,
        }
    out["unresolved"] = unresolved
    return out, scored


def _nominal_log2(pair: str) -> float | None:
    """log2 of the nominal ratio from a pair label like ``0.7 vs 0.2 ng`` or ``1e5 vs 1e4 copies``."""
    try:
        hi, rest = pair.split(" vs ")
        lo = rest.split(" ")[0]
        return round(float(np.log2(float(hi) / float(lo))), 3)
    except ValueError:
        return None


def first_round_coverage(data: Path, components: dict, offset: dict | None = None) -> dict:
    """The propagated interval on round one's 188 AMC comparisons with nominal truth (73.4 %
    Welch coverage), using the run effect estimated without the AMC plates; ``offset`` also
    calibrates the efficiency with the offset fitted without them."""
    curves = load(data / "amplicon_primer_mix.rdml")
    base = _baseline(run(curves)).assign(tubes="amc", truth_se=0.0)
    if offset is not None:
        base = calibrate(base, {"amc": offset})
    x = propagate(base, {"amc": components})
    return {
        "cases": int(len(x)),
        "old_welch_ci": _share(x["in_old_ci"]),
        "propagated_ci": _share(x["in_new_ci"]),
    }


def amplicon_standard_check(
    data: Path, base: pd.DataFrame, components: dict, round_2: dict | None = None
) -> dict:
    """Descriptive check for test P2: DKFZ genomic pairs quantified with the efficiency of the same
    run's amplicon standard curve (all four levels), as a lab with a separate standard would.
    ``round_2`` (added after review) also scores the assay-mean comparator with the round-2
    interval it was validated with."""
    plate = next(p for p in PLATES if p.key == "dkfz")
    group = next(g for g in plate.groups if g.unit == "copies")
    name = dpcr_truth.qpcr_name
    levels = {name(s): v[2] for s, v in group.levels.items()}
    series = {name(s): v[0] for s, v in group.levels.items()}
    curves = load(data / plate.file, plate.experiment, levels, series)
    std = {k: _std_curve(a, ("", ""), "amplicon") for k, a in curves.groupby(["run_id", "target"])}
    g = base[
        (base["plate"] == "dkfz")
        & (_template(base["pair"]) == "genomic")
        & np.isfinite(base["truth_log2"])
    ].copy()
    e_amp = np.array([std[k][0] for k in zip(g["run"], g["assay"], strict=True)])
    shift = -g["dcq"] * (np.log2(e_amp) - np.log2(g["e_used"]))
    for col in ("estimate_log2", "error_log2", "ci_lo", "ci_hi"):
        g[col] = g[col] + shift
    g["se_log2e"] = [std[k][1] for k in zip(g["run"], g["assay"], strict=True)]
    x = propagate(g, {"dkfz": components})
    return {
        "amplicon_efficiency_by_assay": {
            k[1]: round(v[0], 4) for k, v in std.items() if (base["assay"] == k[1]).any()
        },
        "with_amplicon_standard": cover(x) | _bias(x["error_log2"]),
        "with_genomic_assay_mean": cover(base.loc[g.index].pipe(propagate, {"dkfz": components}))
        | _bias(base.loc[g.index, "error_log2"]),
        "with_genomic_assay_mean_note": "scored with P2's standard-curve run effect, as above",
    } | (
        {}
        if round_2 is None
        else {
            "with_genomic_assay_mean_round_2_interval": cover(
                base.loc[g.index].pipe(propagate, {"dkfz": round_2})
            )
        }
    )


def validate(data: str | Path = DATA, out: str | Path = "results") -> dict:
    t, model = table(Path(data))
    result, scored = score(t)
    for pair, entry in result["unresolved"].items():
        hi_lo = t.loc[t["pair"] == pair, ["hi", "lo"]].iloc[0]
        entry["dpcr_log2_by_assay"] = model["unresolved_pairs_dpcr_by_assay"].get(
            f"{hi_lo['hi']}|{hi_lo['lo']}", {}
        )
    summary = {
        "dataset": "Untergasser et al., RDML consortium: dPCR - DKFZ, DNA Dilution - AMC, Volumes and Machines",
        "plates": {p.key: f"{p.experiment} ({p.machine}; {p.truth} truth)" for p in PLATES},
        "analyses": int(len(t)),
        "cases": int(t.groupby(["plate", "run", "assay", "pair"]).ngroups),
        "cases_with_truth": int(
            t[np.isfinite(t["truth_log2"])].groupby(["plate", "run", "assay", "pair"]).ngroups
        ),
        "truth_model": model,
        **result,
    }
    amc = summary["v2_coverage"]["components"]["amc"]
    summary["v2_coverage"]["first_round_cases_nominal_truth"] = first_round_coverage(
        Path(data), amc
    )
    summary["efficiency_calibration"]["first_round_cases_nominal_truth"] = first_round_coverage(
        Path(data), amc, summary["efficiency_calibration"]["offsets"]["amc"]
    )
    p2 = summary["coverage_gap_tests"]["p2_std_curve"]
    p2["dkfz_genomic_with_amplicon_standard"] = amplicon_standard_check(
        Path(data), scored, p2["components"]["dkfz"], summary["v2_coverage"]["components"]["dkfz"]
    )
    out = Path(out)
    t.round(6).to_csv(out / "validation_dpcr.csv", index=False)
    scored.round(6).to_csv(out / "validation_dpcr_baseline.csv", index=False)
    (out / "validation_dpcr.json").write_text(json.dumps(summary, indent=1))
    return summary


def _pct(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None else f"{100 * x:.{digits}f} %"


def summary_lines(first: dict, second: dict, null: dict) -> list[str]:
    """The pass/fail lines ``qsim validate`` prints; every number is from the result files."""
    word = {True: "PASS", False: "FAIL"}
    b, w, c = second["v1_bias"], second["v1_warning"], second["v2_coverage"]
    lines = [
        f"Round 1, nominal ng truth (AMC LightCycler 480): {first['coverage']['cases']} comparisons, "
        f"baseline 95 % CI covers {_pct(first['coverage']['truth_inside_baseline_95ci'])}.",
        f"Round 2, dPCR truth: {second['cases_with_truth']} comparisons with a truth on 5 plates, 4 machines.",
        f"  V1 bias  {word[b['pass']]}  {b['rule']}",
    ]
    for key, p in second["plates"].items():
        e = p["efficiency"]["assay_mean"]
        lines.append(
            f"           {key:15s} {p['machine']:27s} {p['truth']:7s} truth: median |error| "
            f"{e['median_abs_error_log2']:.3f} log2 over {e['cases']} cases"
        )
    lines.append(
        f"           machines passing: {', '.join(b['machines_passing']) or 'none'}; "
        f"with dPCR truth: {', '.join(b['machines_passing_with_dpcr_truth']) or 'none'}"
    )
    levels = ", ".join(
        f"{k} {v['spearman']:.2f}" for k, v in w["by_level"].items() if "spearman" in v
    )
    qc = w["robustness_check_passing_dilution_qc"]["by_level"]
    qc_levels = ", ".join(f"{k} {v['spearman']:.2f}" for k, v in qc.items() if "spearman" in v)
    lines += [
        f"  V1 warn  {word[w['pass']]}  {w['rule']}: {levels}",
        f"           assays passing the dilution QC only: {qc_levels}",
        f"  V2 cover {word[c['pass']]}  {c['rule']}: {_pct(c['all']['propagated_ci_with_truth_se'])} "
        f"(Welch {_pct(c['all']['old_welch_ci'])}; assays passing the dilution QC "
        f"{_pct(c['passing_dilution_qc']['propagated_ci_with_truth_se'])}; round-1 cases "
        f"{_pct(c['first_round_cases_nominal_truth']['propagated_ci'])})",
    ]
    cal = second["efficiency_calibration"]
    before, after = cal["uncalibrated"], cal["all"]
    lines += [
        f"  V2 calib {word[cal['pass']]}  same rule, assay-mean efficiency calibrated on held-out "
        f"dPCR plates: {_pct(after['propagated_ci_with_truth_se'])} (uncalibrated "
        f"{_pct(before['propagated_ci_with_truth_se'])}); median half-width "
        f"{before['median_half_width_new']:.3f} -> {after['median_half_width_new']:.3f} log2",
        "           offsets, log2 per cycle: "
        + ", ".join(f"{g} {v['delta_log2e']:+.4f}" for g, v in cal["offsets"].items()),
    ]
    for machine, v in cal["bias_by_machine"].items():
        lines.append(
            f"           {machine:27s} median |error| {v['uncalibrated']['median_abs_error_log2']:.3f} "
            f"-> {v['calibrated']['median_abs_error_log2']:.3f} log2 over {v['calibrated']['cases']} cases"
        )
    gap = second["coverage_gap_tests"]

    def test_line(label: str, r: dict) -> str:
        a = r["all"]
        lo, hi = a["coverage_90%_cluster_bootstrap"]
        return (
            f"           {label:44s} {_pct(a['propagated_ci_with_truth_se'])} "
            f"(90 % CI over truths {_pct(lo)}-{_pct(hi)}), half-width "
            f"{a['median_half_width_new']:.3f}  {word[r['pass']]}"
        )

    p1 = gap["p1_plate_pair_term"]
    lines += [
        "  V2 gap   tests fixed in docs/review/31 before scoring (same rule):",
        test_line("round 2, for reference", gap["reference_round_2"]),
        test_line("P1 plate x pair term (primary)", p1),
        test_line("P1 one term from both series", p1["variant_one_term_from_both_series"]),
        test_line(
            "P1 without lowest tubes (post hoc)",
            p1["post_hoc_sensitivity_term_without_lowest_tubes"],
        ),
        test_line("P2 run's own standard curve", gap["p2_std_curve"]),
        test_line(
            "P3 standard curve + plate x pair term", gap["p3_std_curve_plus_plate_pair_term"]
        ),
        test_line("P5 Poisson term, nothing fitted", gap["p5_poisson_plate_pair_term"]),
        test_line(
            "P5a Poisson slope from the other series",
            gap["p5_poisson_plate_pair_term"]["variant_p5a_b_fitted_on_other_series"],
        ),
        test_line(
            "P5b Poisson slope from both series",
            gap["p5_poisson_plate_pair_term"]["variant_p5b_b_fitted_on_both_series"],
        ),
    ]
    rs = null["random_splits"]
    lines.append(
        f"  V4 null  {word[null['pass']['overall']]}  {null['pass']['rule']}: cells calling "
        + ", ".join(
            f"{k} {_pct(v['share_cells_calling'], 2)} (defensible {_pct(v['share_defensible_cells_calling'], 2)})"
            for k, v in rs.items()
        )
        + f"; robust calls {sum(v['calls_passing_robust_filter'] for v in rs.values())}"
    )
    return lines
