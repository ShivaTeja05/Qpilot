"""Known-answer validation on a second, very different dataset: the Untergasser dilution series.

Data: "DNA Dilution - AMC" in ``amplicon_primer_mix.rdml`` (RDML consortium, Untergasser,
van der Hoff, Benes). Human genomic DNA at 20, 7, 2, 0.7 and 0.2 ng plus 0 ng controls, in
technical triplicates, for 16 primer pairs on a LightCycler 480 with three reaction mixes. The
true fold change between two DNA amounts is their ratio, so every analysis can be scored
against the truth, not only against the other analyses.

The same simulator idea is applied: each (assay, pair of amounts) is analysed under every
combination of the choices a lab would make here, and each result is compared with the truth:

* ``efficiency``: LinRegPCR mean per assay / each well's own / assume 100 % / standard-curve
  slope fitted on the other dilution levels (leave-pair-out, so the compared levels are not
  used to fit it);
* ``replicates``: mean of log quantities / median / mean Cq then convert / arithmetic mean of
  quantities (the spreadsheet habit) / drop the replicate farthest from the median when the
  triplicate spans more than 0.5 cycles;
* ``flagged``: keep / drop wells LinRegPCR flagged.

It answers four questions. Which choices are right? Does the simulator's spread warn when the
baseline answer is wrong? Does the range across defensible analyses contain the truth? And with
real technical replicates, are planted single-well errors detected?

This is round 1, with nominal ng as the truth. Round 2 (:mod:`qsim.known_answers`) reuses
:func:`run` with digital-PCR truth on four machines and adds propagated intervals.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
from qpilot.qpcr.curves import analyse_study
from scipy import stats

LEVELS = {
    "genomic DNA 20ng": 20.0,
    "genomic DNA 7ng": 7.0,
    "genomic DNA 2ng": 2.0,
    "genomic DNA 0.7ng": 0.7,
    "genomic DNA 0.2ng": 0.2,
    "genomic DNA 0ng": 0.0,
}
PAIRS = [(20.0, 7.0), (7.0, 2.0), (2.0, 0.7), (0.7, 0.2), (20.0, 0.2)]
EFFICIENCY = {
    "assay_mean": "defensible",
    "per_well": "common_practice",
    "assume_100": "common_practice",
    "std_curve": "defensible",
}
REPLICATES = {
    "mean_log": "defensible",
    "median": "defensible",
    "mean_cq": "defensible",
    "drop_outlier": "defensible",
    "arith_mean": "common_practice",
}
FLAGGED = {"keep": "defensible", "drop_flagged": "defensible"}
BASELINE = ("assay_mean", "mean_log", "keep")
SPREAD_RULE = 0.5  # cycles; the common "replicates within half a cycle" rule


def load(
    path: str | Path,
    experiment: str = "DNA Dilution - AMC",
    levels: dict[str, float] | None = None,
    series: dict[str, str] | None = None,
) -> pd.DataFrame:
    """LinRegPCR wells of the given samples, with nominal amount ``ng`` and ``series`` columns."""
    levels = LEVELS if levels is None else levels
    curves = analyse_study(Path(path), experiment, reference_targets=())
    curves = curves[curves["sample"].isin(levels)].copy()
    curves["ng"] = curves["sample"].map(levels)
    curves["series"] = curves["sample"].map(series or {}).fillna("dilution")
    curves["log2_nq"] = np.log2(curves["n0"]) + curves["cq"] * np.log2(curves["eff_target"])
    curves["flagged"] = curves["note"].fillna("").str.len() > 0
    return curves


def _std_curve(assay: pd.DataFrame, exclude: tuple[str, str], series: str) -> tuple[float, float]:
    """Standard-curve efficiency from the series' other levels, and the SE of its log2."""
    use = assay[
        (assay["ng"] > 0)
        & (assay["series"] == series)
        & ~assay["sample"].isin(exclude)
        & assay["cq"].notna()
    ]
    if use["ng"].nunique() < 2:
        return float("nan"), float("nan")
    x = np.log10(use["ng"].to_numpy())
    slope, intercept = np.polyfit(x, use["cq"], 1)
    se_log2e = float("nan")
    if len(use) > 2:
        resid = use["cq"].to_numpy() - (slope * x + intercept)
        se_slope = np.sqrt(resid @ resid / (len(x) - 2) / ((x - x.mean()) ** 2).sum())
        se_log2e = float(np.log2(10) * se_slope / slope**2)
    return float(10 ** (-1 / slope)), se_log2e


def _level_value(
    wells: pd.DataFrame, efficiency: str, replicates: str, e_std: float
) -> tuple[float, np.ndarray]:
    """log2 quantity of one level under the choices, and the per-well log2 values."""
    if efficiency == "assay_mean":
        e = wells["eff_target"].to_numpy()
    elif efficiency == "per_well":
        e = wells["eff_indiv"].to_numpy()
    elif efficiency == "assume_100":
        e = np.full(len(wells), 2.0)
    else:
        e = np.full(len(wells), e_std)
    cq = wells["cq"].to_numpy()
    nq = wells["log2_nq"].to_numpy()
    per_well = nq - cq * np.log2(e)
    if replicates == "drop_outlier" and len(cq) >= 3 and np.ptp(cq) > SPREAD_RULE:
        keep = np.ones(len(cq), bool)
        keep[np.argmax(np.abs(cq - np.median(cq)))] = False
        per_well = per_well[keep]
        cq, nq, e = cq[keep], nq[keep], e[keep]
    if replicates in ("mean_log", "drop_outlier"):
        return float(per_well.mean()), per_well
    if replicates == "median":
        return float(np.median(per_well)), per_well
    if replicates == "mean_cq":
        return float(nq.mean() - cq.mean() * np.log2(e.mean())), per_well
    if replicates == "arith_mean":
        return float(np.log2(np.mean(2.0**per_well))), per_well
    raise ValueError(replicates)


def _assay_mean_se(assay: pd.DataFrame) -> float:
    """Delta-method SE of log2 of LinRegPCR's mean efficiency: SD of the wells' efficiencies over
    the square root of the unflagged amplified wells, divided by E ln 2."""
    e = float(assay["eff_target"].iloc[0])
    sd = float(assay["eff_target_sd"].iloc[0])
    n = int((~assay["flagged"] & assay["cq"].notna()).sum())
    if not (np.isfinite(sd) and n >= 2 and e > 1):
        return float("nan")
    return sd / (e * np.log(2) * np.sqrt(n))


Truth = Callable[[str, str, str, str], "tuple[float, float, str] | None"]


def run(
    curves: pd.DataFrame,
    pairs: list[tuple[str, str]] | None = None,
    truth: Truth | None = None,
    labels: dict[str, str] | None = None,
    unit: str = "ng",
) -> pd.DataFrame:
    """Every analysis of every (run, assay, pair of samples), scored against ``truth``.

    ``pairs`` are (higher, lower) sample names; by default the nominal-ng :data:`PAIRS`.
    ``truth(run, assay, hi, lo)`` returns (log2 ratio, its SE, source) or None to skip; by
    default the nominal ratio. Each row also keeps what the propagated interval needs: the
    replicate SE and Welch df, the Cq difference and the SE of log2 efficiency.
    """
    nominal = curves.drop_duplicates("sample").set_index("sample")["ng"].to_dict()
    if pairs is None:
        by_ng = {v: k for k, v in nominal.items()}
        pairs = [(by_ng[hi], by_ng[lo]) for hi, lo in PAIRS if hi in by_ng and lo in by_ng]
    labels = labels or {s: f"{v:g}" for s, v in nominal.items()}
    series = curves.drop_duplicates("sample").set_index("sample")["series"].to_dict()
    rows = []
    for (run_id, target), assay in curves.groupby(["run_id", "target"]):
        se_assay = _assay_mean_se(assay)
        for hi, lo in pairs:
            if truth is None:
                t = (float(np.log2(nominal[hi] / nominal[lo])), 0.0, "nominal")
            else:
                t = truth(run_id, target, hi, lo)
            if t is None:
                continue
            truth_log2, truth_se, source = t
            e_std, se_std = _std_curve(assay, (hi, lo), series[lo])
            for eff, rep, flag in itertools.product(EFFICIENCY, REPLICATES, FLAGGED):
                sub = assay[assay["cq"].notna() & assay["n0"].notna()]
                if flag == "drop_flagged":
                    sub = sub[~sub["flagged"]]
                a, b = sub[sub["sample"] == hi], sub[sub["sample"] == lo]
                if len(a) < 2 or len(b) < 2 or (eff == "std_curve" and not np.isfinite(e_std)):
                    continue
                va, wa = _level_value(a, eff, rep, e_std)
                vb, wb = _level_value(b, eff, rep, e_std)
                est = va - vb
                lo_ci = hi_ci = se = df = np.nan
                if len(wa) >= 2 and len(wb) >= 2:
                    w = stats.ttest_ind(wa, wb, equal_var=False)
                    se = abs(est / w.statistic) if w.statistic else np.nan
                    df = (wa.var(ddof=1) / len(wa) + wb.var(ddof=1) / len(wb)) ** 2 / (
                        (wa.var(ddof=1) / len(wa)) ** 2 / (len(wa) - 1)
                        + (wb.var(ddof=1) / len(wb)) ** 2 / (len(wb) - 1)
                    )
                    half = stats.t.ppf(0.975, df) * se
                    lo_ci, hi_ci = est - half, est + half
                se_log2e = {"assay_mean": se_assay, "std_curve": se_std}.get(eff, 0.0)
                rows.append(
                    {
                        "run": run_id,
                        "assay": target,
                        "pair": f"{labels[hi]} vs {labels[lo]} {unit}",
                        "hi": hi,
                        "lo": lo,
                        "truth_log2": truth_log2,
                        "truth_se": truth_se,
                        "truth_source": source,
                        "efficiency": eff,
                        "replicates": rep,
                        "flagged": flag,
                        "defensible": EFFICIENCY[eff] == "defensible"
                        and REPLICATES[rep] == "defensible",
                        "estimate_log2": est,
                        "error_log2": est - truth_log2,
                        "ci_lo": lo_ci,
                        "ci_hi": hi_ci,
                        "se_rep": float(
                            np.sqrt(wa.var(ddof=1) / len(wa) + wb.var(ddof=1) / len(wb))
                        )
                        if len(wa) >= 2 and len(wb) >= 2
                        else np.nan,
                        "df": df,
                        "dcq": float(a["cq"].mean() - b["cq"].mean()),
                        "se_log2e": se_log2e,
                        "e_used": float(np.nanmean(a["eff_target"]))
                        if eff == "assay_mean"
                        else (
                            2.0
                            if eff == "assume_100"
                            else e_std
                            if eff == "std_curve"
                            else float(np.nanmean(a["eff_indiv"]))
                        ),
                    }
                )
    return pd.DataFrame(rows)


def score(table: pd.DataFrame) -> dict:
    out: dict = {
        "analyses": int(len(table)),
        "cases": int(table.groupby(["run", "assay", "pair"]).ngroups),
    }
    by = {}
    for col in ("efficiency", "replicates", "flagged"):
        g = table.groupby(col)["error_log2"]
        by[col] = {
            k: {
                "median_abs_error_pct": round(
                    float((2 ** g.get_group(k).abs() - 1).median() * 100), 1
                ),
                "median_bias_pct": round(float((2 ** g.get_group(k).median() - 1) * 100), 1),
                "share_within_10pct": round(
                    float((g.get_group(k).abs() <= np.log2(1.1)).mean()), 3
                ),
            }
            for k in g.groups
        }
    out["by_choice"] = by
    cases = []
    for key, case in table.groupby(["run", "assay", "pair"]):
        base = case[
            (case["efficiency"] == BASELINE[0])
            & (case["replicates"] == BASELINE[1])
            & (case["flagged"] == BASELINE[2])
        ]
        if base.empty:
            continue
        b = base.iloc[0]
        d = case[case["defensible"]]
        cases.append(
            {
                "pair": key[2],
                "spread_log2": float(d["estimate_log2"].max() - d["estimate_log2"].min()),
                "baseline_abs_error": abs(float(b["error_log2"])),
                "truth_in_range": bool(
                    d["estimate_log2"].min() <= b["truth_log2"] <= d["estimate_log2"].max()
                ),
                "truth_in_baseline_ci": bool(b["ci_lo"] <= b["truth_log2"] <= b["ci_hi"])
                if np.isfinite(b["ci_lo"])
                else None,
                "truth_in_ci_or_range": None,
            }
        )
    c = pd.DataFrame(cases)
    rho, p = stats.spearmanr(c["spread_log2"], c["baseline_abs_error"])
    top = c["spread_log2"] >= c["spread_log2"].quantile(0.75)
    per_level = {}
    for pair, sub in c.groupby("pair"):
        if len(sub) >= 8:
            r, pv = stats.spearmanr(sub["spread_log2"], sub["baseline_abs_error"])
            per_level[pair] = {
                "spearman": round(float(r), 3),
                "p": float(pv),
                "cases": int(len(sub)),
            }
    out["warning_by_pair"] = per_level
    out["warning"] = {
        "spearman_spread_vs_baseline_error": round(float(rho), 3),
        "p": float(p),
        "baseline_median_abs_error_pct_when_spread_in_top_quarter": round(
            float((2 ** c.loc[top, "baseline_abs_error"] - 1).median() * 100), 1
        ),
        "baseline_median_abs_error_pct_otherwise": round(
            float((2 ** c.loc[~top, "baseline_abs_error"] - 1).median() * 100), 1
        ),
    }
    ci_ok = c["truth_in_baseline_ci"].dropna()
    out["coverage"] = {
        "truth_inside_range_of_defensible_analyses": round(float(c["truth_in_range"].mean()), 3),
        "truth_inside_baseline_95ci": round(float(ci_ok.mean()), 3),
        "cases": int(len(c)),
    }
    return out


def replicate_faults(
    curves: pd.DataFrame, trials: int = 300, seed: int = 2026, shift: float = 3.0
) -> dict:
    """Plant a late replicate (+shift cycles) and test the half-cycle triplicate rule; measure the
    damage to the baseline estimate and how much the drop-outlier choice repairs it."""
    rng = np.random.default_rng(np.random.SeedSequence(seed))
    triplicates = [
        g
        for _, g in curves[
            (curves["ng"] > 0) & curves["cq"].notna() & np.isfinite(curves["log2_nq"])
        ].groupby(["run_id", "target", "ng"])
        if len(g) == 3
    ]
    clean_flags = np.mean([np.ptp(g["cq"]) > SPREAD_RULE for g in triplicates])
    hits, dmg_base, dmg_fixed = [], [], []
    for _ in range(trials):
        g = triplicates[int(rng.integers(len(triplicates)))].copy()
        i = int(rng.integers(3))
        g.iloc[i, g.columns.get_loc("cq")] += shift
        hits.append(np.ptp(g["cq"]) > SPREAD_RULE)
        clean = triplicates[0]  # placeholder for shape; damage is measured on the triplicate itself
        del clean
        nq, e = g["log2_nq"].to_numpy(), g["eff_target"].to_numpy()
        vals = nq - g["cq"].to_numpy() * np.log2(e)
        true_vals = vals.copy()
        true_vals[i] += shift * np.log2(e[i])
        dmg_base.append(abs(vals.mean() - true_vals.mean()))
        keep = np.ones(3, bool)
        if np.ptp(g["cq"]) > SPREAD_RULE:
            keep[np.argmax(np.abs(g["cq"].to_numpy() - np.median(g["cq"])))] = False
        dmg_fixed.append(abs(vals[keep].mean() - true_vals.mean()))
    return {
        "trials": trials,
        "shift_cycles": shift,
        "detected": round(float(np.mean(hits)), 3),
        "clean_triplicates_flagged": round(float(clean_flags), 3),
        "median_error_pct_mean_of_three": round(float((2 ** np.median(dmg_base) - 1) * 100), 1),
        "median_error_pct_after_drop_outlier": round(
            float((2 ** np.median(dmg_fixed) - 1) * 100), 1
        ),
    }


def controls(curves: pd.DataFrame) -> dict:
    ntc = curves[curves["ng"] == 0]
    amp = ntc[ntc["cq"].notna()]
    low = (
        curves[(curves["ng"] == 0.2) & curves["cq"].notna()]
        .groupby(["run_id", "target"])["cq"]
        .median()
    )
    gaps = []
    for (run_id, target), g in amp.groupby(["run_id", "target"]):
        if (run_id, target) in low.index:
            gaps.append(float(g["cq"].min() - low[(run_id, target)]))
    return {
        "zero_ng_wells": int(len(ntc)),
        "zero_ng_wells_amplified": int(len(amp)),
        "assays_with_amplified_control": int(amp.groupby(["run_id", "target"]).ngroups),
        "assays_where_control_within_5_cycles_of_0.2ng": int(sum(gp < 5 for gp in gaps)),
    }


def validate(path: str | Path, out: str | Path = "results") -> dict:
    curves = load(path)
    table = run(curves)
    result = {
        "dataset": "Untergasser et al., RDML consortium: DNA Dilution - AMC (LightCycler 480; Roche SYBR, SensiFast, LC Green)",
        "wells": int(len(curves)),
        "assays": int(curves.groupby(["run_id", "target"]).ngroups),
        **score(table),
        "replicate_faults": replicate_faults(curves),
        "controls": controls(curves),
    }
    out = Path(out)
    table.to_csv(out / "validation_untergasser.csv", index=False)
    (out / "validation_untergasser.json").write_text(json.dumps(result, indent=1))
    return result
