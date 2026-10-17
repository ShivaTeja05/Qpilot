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
    """Add the propagated interval to baseline rows; ``components`` is keyed by ``tubes``."""
    out = base.copy()
    sd_level = out["tubes"].map(lambda k: components[k]["sd_level_log2"])
    tau = out["tubes"].map(lambda k: components[k]["sd_log2e_run"])
    rep = out["se_rep"] ** 2
    added = out["dcq"] ** 2 * (out["se_log2e"].fillna(0.0) ** 2 + tau**2) + 2 * sd_level**2
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

    def cover(x: pd.DataFrame) -> dict:
        return {
            "cases": int(len(x)),
            "old_welch_ci": _share(x["in_old_ci"]),
            "propagated_ci": _share(x["in_new_ci"]),
            "propagated_ci_with_truth_se": _share(x["in_new_ci_with_truth"]),
            "median_half_width_old": round(float(((x["ci_hi"] - x["ci_lo"]) / 2).median()), 3),
            "median_half_width_new": round(float(((x["new_hi"] - x["new_lo"]) / 2).median()), 3),
        }

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


def first_round_coverage(data: Path, components: dict) -> dict:
    """The propagated interval on round one's 188 AMC comparisons with nominal truth (73.4 %
    Welch coverage), using the run effect estimated without the AMC plates."""
    curves = load(data / "amplicon_primer_mix.rdml")
    base = _baseline(run(curves)).assign(tubes="amc", truth_se=0.0)
    x = propagate(base, {"amc": components})
    return {
        "cases": int(len(x)),
        "old_welch_ci": _share(x["in_old_ci"]),
        "propagated_ci": _share(x["in_new_ci"]),
    }


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
    summary["v2_coverage"]["first_round_cases_nominal_truth"] = first_round_coverage(
        Path(data), summary["v2_coverage"]["components"]["amc"]
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
