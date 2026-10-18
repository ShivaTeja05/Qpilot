"""Tests on new public data, as fixed in ``docs/review/32-external-data-tests.md`` before scoring.

* **X1, held-out dPCR plates.** Three Untergasser plates that measured the same genomic tubes as
  the dPCR truth, two on a QuantStudio. They are scored with interval components fixed from the
  existing results; nothing is estimated on these plates.
* **X2, baseline shift.** A constant added to every fluorescence value must not change anything.
* **X3, missing cycles.** Which wells still get a result (descriptive).
* **X4, Ruijter ds_94_4.** 94 replicates at 15-15,000 copies on a CFX384: known-answer coverage
  of triplicate experiments, and the V4 no-difference test at 15 and 150 copies.
* **X5, Ruijter competimer.** Efficiency lowered on purpose by a competitor (0-50 %): bias of each
  efficiency option, and whether the existing detectors notice.

Data and provenance: ``data/untergasser``, ``data/technical``, ``data/ruijter`` (README files).
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from qpilot.qpcr.curves import analyse_study
from qpilot.vendor.rdmlpython import rdml
from scipy import stats

from qsim import known_answers as ka
from qsim import nodiff
from qsim import truth as dpcr_truth
from qsim.data import EFFICIENCY_NOTES, LOW_COPY_NOTE, well_position
from qsim.validate import BASELINE, _assay_mean_se, load, run

DATA = Path(__file__).resolve().parents[2] / "data"
SEED = 2026

#: interval components fixed before scoring (docs/review/32), from results/validation_dpcr.json
RUN_EFFECT = {"sd_level_log2": 0.0768, "sd_log2e_run": 0.0408}  # robust, all three groups
P1_TERM = 0.1479  # plate x pair SD pooled from both existing series
P1_TERM_AMC = 0.1693  # the term the AMC and DKFZ plates were scored with
NOMINAL_SD = 0.0238  # nominal-truth error bar per dilution step (round 2)

#: (file, experiment, run, label): plates of the December 2024 genomic dilution series
HELD_OUT = (
    ("eva_green_b.rdml", "Eva Green B", "Run 1", "QuantStudio, Eva Green B (17.09.2025)"),
    (
        "quantification_methods.rdml",
        "Quantification Methods",
        "Run 1",
        "QuantStudio, Quantification Methods (22.10.2025)",
    ),
    (
        "probes.rdml",
        "Probes - AMC",
        "P4 - Probe Mixes - DNA Dilution",
        "LightCycler 480 AMC, probe mixes (10.12.2024)",
    ),
)
EMBL_PLATE = ("unused_qpcr_dpcr_comparison.rdml", "Primer and DNA Dilutions", "Run 1")


def _quiet() -> None:
    logging.getLogger("qpilot.qpcr.curves").setLevel(logging.ERROR)


# --- conversion of long-format CSV curves (r-universe) into RDML --------------------------------


def table_to_rdml(curves: pd.DataFrame, experiment: str, run_id: str, out: Path) -> Path:
    """Write curves (columns well, sample, sample_type, target, cycle, fluor) as one RDML plate
    with rdmlpython's own table import, as :func:`qsim.nodiff.to_rdml` does for ds_380."""
    wide = curves.pivot_table(
        index=["well", "sample", "sample_type", "target"], columns="cycle", values="fluor"
    )
    doc = rdml.Rdml()
    doc.new_experiment(experiment)
    exp = doc.get_experiment(byid=experiment)
    exp.new_run(run_id)
    plate = exp.get_run(byid=run_id)
    plate["pcrFormat_rows"], plate["pcrFormat_columns"] = "16", "24"
    plate["pcrFormat_rowLabel"], plate["pcrFormat_columnLabel"] = "ABC", "123"
    lines = [
        "Well\tSample\tSample Type\tTarget\tTarget Type\tDye\tCq\t"
        + "\t".join(map(str, wide.columns))
    ]
    for (well, sample, stype, target), row in wide.iterrows():
        fluor = "\t".join(repr(float(v)) for v in row.to_numpy())
        lines.append(f"{well}\t{sample}\t{stype}\t{target}\ttoi\tSYBR\t\t{fluor}")
    with tempfile.TemporaryDirectory() as tmp:
        table = Path(tmp) / "plate.tsv"
        table.write_text("\n".join(lines) + "\n")
        plate.import_table(doc, str(table), "amp")
    doc.save(str(out))
    return out


def _well_ids(n: int) -> list[str]:
    return [f"{'ABCDEFGHIJKLMNOP'[i // 24]}{i % 24 + 1}" for i in range(n)]


def ds94_rdml(csv: Path = DATA / "ruijter" / "ds_94_4.csv", out: Path | None = None) -> Path:
    t = pd.read_csv(csv)
    t["sample"] = np.where(t["copies"] > 0, "MYCN " + t["copies"].astype(str) + " copies", "NTC")
    t["sample_type"] = np.where(t["copies"] > 0, "unkn", "ntc")
    return table_to_rdml(t, "ds_94_4", "CFX384", out or DATA / "ruijter" / "ds_94_4.rdml")


def competimer_rdml(
    csv: Path = DATA / "ruijter" / "ds_competimer.csv", out: Path | None = None
) -> Path:
    """The CSV has no well IDs: curves are numbered in file order."""
    t = pd.read_csv(csv)
    key = ["replicate", "pct", "conc", "sample_type"]
    order = t.drop_duplicates(key)[key].reset_index(drop=True)
    order["well"] = _well_ids(len(order))
    t = t.drop(columns="well").merge(order, on=key)
    t["sample"] = np.where(
        t["conc"] > 0,
        t["conc"].map("{:g} ng per ul".format) + " " + t["pct"].astype(str) + " pct",
        "NTC",
    )
    t["sample_type"] = np.where(t["conc"] > 0, "unkn", "ntc")
    return table_to_rdml(t, "competimer", "LC480", out or DATA / "ruijter" / "ds_competimer.rdml")


# --- X1: held-out dPCR plates -------------------------------------------------------------------


def _intervals(base: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """The pre-registered intervals, all components fixed (``tubes`` is set to one group)."""
    x = base["poisson_x"] if "poisson_x" in base else ka.poisson_x(base)
    b = base.assign(tubes="new", poisson_x=x)
    comps = {
        "round_2": RUN_EFFECT,
        "p1_primary": RUN_EFFECT | {"sd_plate_pair_log2": P1_TERM},
        "p1_amc_term": RUN_EFFECT | {"sd_plate_pair_log2": P1_TERM_AMC},
        "p5_poisson": RUN_EFFECT | {"poisson_b": ka.POISSON_B},
    }
    return {k: ka.propagate(b, {"new": c}) for k, c in comps.items()}


def held_out_plates(data: Path = DATA / "untergasser") -> tuple[dict, pd.DataFrame]:
    _quiet()
    dpcr = dpcr_truth.load_dpcr(data)
    sd_well = dpcr_truth.dpcr_well_sd(dpcr)
    name = dpcr_truth.qpcr_name
    levels = {name(s): v[2] for s, v in ka.GDNA.items()}
    series = {name(s): v[0] for s, v in ka.GDNA.items()}
    labels = {name(s): v[1] for s, v in ka.GDNA.items()}
    pairs = [(name(hi), name(lo)) for hi, lo in ka.GDNA_PAIRS]

    def truth(run_id: str, target: str, hi: str, lo: str):
        t = dpcr_truth.pair_truth(dpcr, hi, lo, sd_well)
        return None if t is None else (t.log2, t.se, t.source)

    parts = []
    for file, experiment, run_id, label in HELD_OUT:
        curves = load(data / file, experiment, levels, series)
        curves = curves[
            (curves["run_id"] == run_id) & ~curves["target"].str.startswith("No Primer")
        ]
        present = set(curves["sample"])
        here = [(hi, lo) for hi, lo in pairs if hi in present and lo in present]
        t = run(curves, here, truth, labels, "ng")
        t.insert(0, "plate", label)
        t.insert(1, "machine", label.split(",")[0])
        t.insert(2, "truth_kind", "dPCR")
        parts.append(t)
    t = pd.concat(parts, ignore_index=True)
    base = ka._baseline(t)
    resolved = base[np.isfinite(base["truth_log2"])]
    out: dict = {
        "plates": [label for *_, label in HELD_OUT],
        "fixed_components": {
            "run_effect": RUN_EFFECT,
            "p1_term": P1_TERM,
            "p1_amc_term": P1_TERM_AMC,
        },
        "cases": int(len(resolved)),
        "cases_with_efficiency_se_missing_filled_0": int(resolved["se_log2e"].isna().sum()),
        "assays_by_plate": {k: int(g["assay"].nunique()) for k, g in resolved.groupby("plate")},
    }
    scored = {}
    for k, x in _intervals(resolved).items():
        scored[k] = x
        out[k] = ka.gap_report(x)
    others = t[(t["replicates"] == BASELINE[1]) & (t["flagged"] == BASELINE[2])]
    others = others[np.isfinite(others["truth_log2"])]
    out["bias_by_plate_and_efficiency"] = {
        p: {e: ka._bias(x["error_log2"]) for e, x in g.groupby("efficiency")}
        for p, g in others.groupby("plate")
    }
    unres = base[~np.isfinite(base["truth_log2"])]
    out["unresolved_pairs"] = {
        p: {
            "cases": int(len(g)),
            "baseline_median_log2": round(float(g["estimate_log2"].median()), 3),
            "nominal_log2": ka._nominal_log2(p),
        }
        for p, g in unres.groupby("pair")
    }
    out["embl_pair"] = _embl_pair(data, dpcr, sd_well)
    out["pass"] = out["p1_primary"]["pass"]
    return out, scored["p1_primary"]


def _embl_pair(data: Path, dpcr: pd.DataFrame, sd_well: float) -> dict:
    """Reported separately: 'genomic DNA 20ng - EMBL' may not be the tube dPCR measured."""
    file, experiment, run_id = EMBL_PLATE
    embl, gdna = "genomic DNA 20ng - EMBL", "genomic DNA 20ng"
    curves = load(data / file, experiment, {embl: 20.0, gdna: 20.0}, {embl: "EMBL", gdna: "gDNA"})
    curves = curves[curves["run_id"] == run_id]
    t = dpcr_truth.pair_truth(dpcr, dpcr_truth.qpcr_name("EMBL DNA 20ng"), gdna, sd_well)
    rows = run(
        curves, [(embl, gdna)], lambda *a: (t.log2, t.se, t.source), {embl: "EMBL 20", gdna: "20"}
    )
    b = ka._baseline(rows).assign(
        poisson_x=2 / (20 * ka.COPIES_PER_NG),
        plate="QuantStudio, unused comparison (30.05.2025)",
        machine="QuantStudio",
        truth_kind="dPCR",
    )
    x = _intervals(b)["p1_primary"]
    return {"truth_log2": round(t.log2, 3), **ka.cover(x), **ka._bias(x["error_log2"])}


# --- X2 and X3: technical files -----------------------------------------------------------------


def shifted_baseline(path: Path = DATA / "technical" / "shifted_baseline.rdml") -> dict:
    """Pair each well of target 'T X' with its unshifted twin in 'T' (same sample, same order)."""
    _quiet()
    c = analyse_study(path, "DNA Dilution - AMC", reference_targets=())
    c = c[c["cq"].notna()].copy()
    c["base_target"] = c["target"].str.removesuffix(" X")
    c["shifted"] = c["target"].str.endswith(" X")
    c["order"] = c.groupby(["target", "sample"]).cumcount()
    key = ["base_target", "sample", "order"]
    m = c[~c["shifted"]].merge(c[c["shifted"]], on=key, suffixes=("", "_x"))
    d_n0 = (np.log2(m["n0_x"]) - np.log2(m["n0"])).abs()
    d_eff = (m["eff_indiv_x"] - m["eff_indiv"]).abs()
    # the round-2 baseline estimate of every genomic pair, per target, shifted vs not
    levels = {s: v[2] for s, v in ka.GDNA.items() if s in set(c["sample"])}
    curves = load(path, "DNA Dilution - AMC", levels, dict.fromkeys(levels, "gDNA"))
    pairs = [(hi, lo) for hi, lo in ka.GDNA_PAIRS if hi in levels and lo in levels]
    b = ka._baseline(run(curves, pairs))
    b["base_target"] = b["assay"].str.removesuffix(" X")
    est = b.pivot_table(
        index=["base_target", "pair"], columns=b["assay"].str.endswith(" X"), values="estimate_log2"
    )
    d_est = (est[True] - est[False]).abs()
    return {
        "well_pairs": int(len(m)),
        "max_abs_dlog2_n0": round(float(d_n0.max()), 5),
        "median_abs_dlog2_n0": round(float(d_n0.median()), 5),
        "max_abs_d_eff_indiv": round(float(d_eff.max()), 5),
        "cq_changed_max": round(float((m["cq_x"] - m["cq"]).abs().max()), 5),
        "pair_estimates": int(d_est.notna().sum()),
        "max_abs_d_estimate_log2": round(float(d_est.max()), 5),
        "pass": bool(d_n0.max() <= 0.01 and d_eff.max() <= 0.001 and d_est.max() <= 0.01),
    }


MATRIX_GAPS = {
    "K3": "cycle 2",
    "K5": "cycle 2",
    "K7": "cycles 2-4",
    "K9": "cycles 2-3",
    "K11": "cycles 2-5",
    "L2": "cycle 2",
    "L5": "cycle 45",
    "L7": "cycle 45",
    "L9": "cycles 44-45",
    "L11": "cycles 42-45",
    "M3": "cycle 8",
    "M5": "cycle 30",
    "M7": "cycles 14-15",
    "M9": "cycles 20-21",
    "N3": "cycles 17-20",
    "N5": "cycles 42-44",
    "N7": "cycles 5-9",
    "N9": "cycles 5-9, 31-35",
    "N11": "cycles 1-10, 43-45",
    "O1": "cycles 1-7, 20-22, 44-45",  # upstream lists 1-8, but the file has cycle 8
    "O3": "only cycle 20 present",
    "O7": "no data",
}  # from data/technical/UPSTREAM_README.md, checked against the file; cycle 1 is missing everywhere


def matrix_gaps(path: Path = DATA / "technical" / "matrix_gaps.rdml") -> dict:
    """Descriptive: does every damaged well get a result, and how far is it from the intact wells of
    the same sample in the same plate row (each sample spans two rows about 3.5 cycles apart; the
    row-matched reference was adopted after review)."""
    _quiet()
    try:
        c = analyse_study(path, "Experiment 1", reference_targets=())
    except Exception as err:  # noqa: BLE001 (report any failure instead of crashing the run)
        return {"runs": False, "error": f"{type(err).__name__}: {err}"}
    c = c.copy()
    c["well_id"] = c["well"].map(
        lambda w: "ABCDEFGHIJKLMNOP"[well_position(w)[0]] + str(well_position(w)[1] + 1)
    )
    c["row"] = c["well_id"].str[0]
    intact = c[~c["well_id"].isin(MATRIX_GAPS)]
    ref = intact.groupby(["sample", "row"]).agg(cq=("cq", "median"), eff=("eff_indiv", "median"))
    rows = {}
    for well, gap in MATRIX_GAPS.items():
        w = c[c["well_id"] == well]
        if w.empty:
            rows[well] = {"gap": gap, "present": False}
            continue
        r = w.iloc[0]
        key = (r["sample"], r["row"])
        s = ref.loc[key] if key in ref.index else None
        rows[well] = {
            "gap": gap,
            "present": True,
            "cq": None if pd.isna(r["cq"]) else round(float(r["cq"]), 2),
            "eff_indiv": None if pd.isna(r["eff_indiv"]) else round(float(r["eff_indiv"]), 3),
            "d_cq_vs_intact_same_row": None
            if s is None or pd.isna(r["cq"])
            else round(float(r["cq"] - s["cq"]), 2),
            "d_eff_vs_intact_same_row": None
            if s is None or pd.isna(r["eff_indiv"])
            else round(float(r["eff_indiv"] - s["eff"]), 3),
            "note": str(r["note"] or ""),
        }
    return {"runs": True, "wells": int(len(c)), "damaged_wells": rows}


# --- X4: Ruijter ds_94_4 ------------------------------------------------------------------------

DS94_LEVELS = (15000, 1500, 150, 15)
DS94_PAIRS = ((15000, 1500), (1500, 150), (150, 15), (15000, 15))


def _ds94_wells(path: Path) -> pd.DataFrame:
    _quiet()
    c = analyse_study(path, "ds_94_4", reference_targets=())
    w = c[(c["sample_type"] == "unkn") & c["cq"].notna() & c["n0"].notna()].copy()
    w["copies"] = w["sample"].str.extract(r"MYCN (\d+) copies")[0].astype(int)
    w["log2_n0"] = np.log2(w["n0"])
    w["log2_nq"] = w["log2_n0"] + w["cq"] * np.log2(w["eff_target"])
    notes = w["note"].fillna("")
    w["flagged"] = notes.str.len() > 0
    w["flag_eff"] = notes.map(lambda s: any(k in s for k in EFFICIENCY_NOTES))
    w["flag_low"] = notes.str.contains(LOW_COPY_NOTE, regex=False)
    w["column"] = w["well"].map(lambda x: well_position(x)[1] + 1)
    return w.reset_index(drop=True)


def ds94_known_answer(wells: pd.DataFrame, draws: int = 500, seed: int = SEED) -> dict:
    rng = np.random.default_rng(np.random.SeedSequence([seed, 94]))
    se_log2e = _assay_mean_se(wells)
    rows = []
    for hi, lo in DS94_PAIRS:
        a_all, b_all = wells[wells["copies"] == hi], wells[wells["copies"] == lo]
        k = round(np.log10(hi / lo))
        for d in range(draws):
            a = a_all.iloc[rng.choice(len(a_all), 3, replace=False)]
            b = b_all.iloc[rng.choice(len(b_all), 3, replace=False)]
            va, vb = a["log2_n0"].to_numpy(), b["log2_n0"].to_numpy()
            est = float(va.mean() - vb.mean())
            sa, sb = va.var(ddof=1) / 3, vb.var(ddof=1) / 3
            se = float(np.sqrt(sa + sb))
            df = (sa + sb) ** 2 / (sa**2 / 2 + sb**2 / 2)
            half = stats.t.ppf(0.975, df) * se
            truth = float(np.log2(hi / lo))
            rows.append(
                {
                    "pair": f"{hi} vs {lo} copies",
                    "draw": d,
                    "hi": f"{hi}",
                    "lo": f"{lo}",
                    "estimate_log2": est,
                    "truth_log2": truth,
                    "truth_se": NOMINAL_SD * np.sqrt(k),
                    "error_log2": est - truth,
                    "se_rep": se,
                    "df": df,
                    "ci_lo": est - half,
                    "ci_hi": est + half,
                    "dcq": float(a["cq"].mean() - b["cq"].mean()),
                    "se_log2e": se_log2e,
                    "poisson_x": 1 / hi + 1 / lo,
                }
            )
    x = pd.DataFrame(rows).assign(tubes="new")
    out = {"draws_per_pair": draws, "seed": seed, "triplicates": True}
    comps = {
        "round_2": RUN_EFFECT,
        "p1_primary": RUN_EFFECT | {"sd_plate_pair_log2": P1_TERM},
        "p5_poisson": RUN_EFFECT | {"poisson_b": ka.POISSON_B},
    }
    for name, comp in comps.items():
        y = ka.propagate(x, {"new": comp})
        per = {p: ka.cover(g) for p, g in y.groupby("pair", sort=False)}
        overall = float(np.mean([v["propagated_ci_with_truth_se"] for v in per.values()]))
        out[name] = {
            "coverage_equal_weight_over_pairs": round(overall, 3),
            "by_pair": per,
            "pass": overall >= ka.COVERAGE_TARGET,
        }
    full = {}
    for hi, lo in DS94_PAIRS:
        a, b = wells[wells["copies"] == hi], wells[wells["copies"] == lo]
        full[f"{hi} vs {lo} copies"] = {
            "wells": [int(len(a)), int(len(b))],
            "estimate_log2": round(float(a["log2_n0"].mean() - b["log2_n0"].mean()), 3),
            "truth_log2": round(float(np.log2(hi / lo)), 3),
            "error_log2": round(
                float(a["log2_n0"].mean() - b["log2_n0"].mean() - np.log2(hi / lo)), 3
            ),
        }
    out["full_plate_estimates"] = full
    out["replicate_sd_vs_poisson"] = {
        f"{c} copies": {
            "wells": int(len(g)),
            "sd_log2_n0": round(float(g["log2_n0"].std()), 3),
            "poisson_sd_log2": round(float(1 / (np.log(2) * np.sqrt(c))), 3),
        }
        for c, g in wells.groupby("copies")
    }
    out["assay_efficiency"] = round(float(wells["eff_target"].iloc[0]), 4)
    return out


def ds94_no_difference(wells: pd.DataFrame, draws: int = 1000, seed: int = SEED) -> dict:
    out = {}
    for copies in (15, 150):
        level = wells[wells["copies"] == copies].reset_index(drop=True)
        rs = {f"{n}v{n}": nodiff.run(level, n, draws, seed) for n in (3, 6)}
        out[f"{copies} copies"] = {
            "wells": int(len(level)),
            "share_cq_above_35": round(float((level["cq"] > 35).mean()), 3),
            "random_splits": rs,
            "pass": _null_pass(rs),
        }
    return out


def _null_pass(rs: dict) -> dict:
    p = {
        "all_cells": all(r["share_cells_calling"] <= nodiff.MAX_CALL_SHARE for r in rs.values()),
        "robust_filter": all(r["calls_passing_robust_filter"] == 0 for r in rs.values()),
        "median_abs_log2fc": all(
            r["baseline_median_abs_log2fc"] <= nodiff.MAX_MEDIAN_LOG2 for r in rs.values()
        ),
        "defensible_cells": all(
            r["share_defensible_cells_calling"] <= nodiff.MAX_CALL_SHARE for r in rs.values()
        ),
    }
    p["overall"] = bool(p["all_cells"] and p["robust_filter"] and p["median_abs_log2fc"])
    return p


# --- X5: Ruijter competimer ---------------------------------------------------------------------

CONCS = (64.0, 16.0, 4.0, 1.0, 0.25, 0.0625)
PCTS = (0, 5, 10, 20, 30, 40, 50)
EFF_THRESHOLD = 1.8  # qsim.troubleshoot.detect_efficiency's existing assay threshold


def _sample(conc: float, pct: int) -> str:
    return f"{conc:g} ng per ul {pct} pct"  # plain characters, so qPilot keeps the name


FAILED_ANALYSIS = ("no amplification", "only 3 values in log phase")


def competimer(path: Path, exclude_failed: bool = False) -> dict:
    """X5. ``exclude_failed`` (added after scoring, not counted) leaves out wells whose curve
    analysis failed by LinRegPCR's own notes; at 64 and 16 ng/µl the curves rise before cycle 7."""
    _quiet()
    levels = {_sample(c, p): c for c in CONCS for p in PCTS}
    series = {_sample(c, p): f"pct{p}" for c in CONCS for p in PCTS}
    curves = load(path, "competimer", levels, series)
    if exclude_failed:
        failed = curves["note"].fillna("").map(lambda s: any(k in s for k in FAILED_ANALYSIS))
        curves = curves[~failed]
    curves["pct"] = curves["sample"].str.extract(r"(\d+) pct$")[0].astype(int)
    adjacent = list(zip(CONCS[:-1], CONCS[1:], strict=True)) + [(CONCS[0], CONCS[-1])]
    dil_pairs = [(_sample(h, p), _sample(lo, p)) for p in PCTS for h, lo in adjacent]
    fault_pairs = [(_sample(c, p), _sample(c, 0)) for p in PCTS[1:] for c in CONCS]
    present = set(curves["sample"])
    pairs = [(hi, lo) for hi, lo in dil_pairs + fault_pairs if hi in present and lo in present]
    t = run(curves, pairs)
    t = t[(t["replicates"] == BASELINE[1]) & (t["flagged"] == BASELINE[2])].copy()
    t["pct"] = t["hi"].str.extract(r"(\d+) pct$")[0].astype(int)
    t["kind"] = np.where(t["truth_log2"] == 0, "fault", "dilution")

    def table(kind: str) -> dict:
        g = t[t["kind"] == kind]
        return {
            f"{p}%": {e: ka._bias(x["error_log2"]) for e, x in q.groupby("efficiency")}
            for p, q in g.groupby("pct")
        }

    flag = curves["note"].fillna("").map(lambda s: any(k in s for k in EFFICIENCY_NOTES))
    curves["flag_eff"] = flag
    trip = curves.groupby("sample").agg(pct=("pct", "first"), eff=("eff_indiv", "mean"))
    detect = {}
    for p, g in curves.groupby("pct"):
        tr = trip[trip["pct"] == p]
        if g.empty:
            continue
        detect[f"{p}%"] = {
            "wells": int(len(g)),
            "share_wells_flagged_by_linregpcr": round(float(g["flag_eff"].mean()), 3),
            "triplicates": int(len(tr)),
            "share_triplicates_mean_eff_below_1.8": round(
                float((tr["eff"] < EFF_THRESHOLD).mean()), 3
            ),
            "median_eff_indiv": round(float(g["eff_indiv"].median()), 3),
        }
    zero = detect["0%"]
    return {
        "assay_efficiency_plate_mean": round(float(curves["eff_target"].iloc[0]), 4),
        "dilution_within_level": table("dilution"),
        "fault_same_dna_vs_0pct": table("fault"),
        "detectors": detect,
        "false_alarm": {
            "linregpcr_flag": zero["share_wells_flagged_by_linregpcr"],
            "efficiency_below_1.8": zero["share_triplicates_mean_eff_below_1.8"],
            "rule": "false alarm (0 % competitor) <= 2 %",
            "pass": bool(
                zero["share_wells_flagged_by_linregpcr"] <= 0.02
                and zero["share_triplicates_mean_eff_below_1.8"] <= 0.02
            ),
        },
    }


# --- everything ---------------------------------------------------------------------------------


def validate(data: Path = DATA, out: str | Path = "results") -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        ds94 = _ds94_wells(ds94_rdml(data / "ruijter" / "ds_94_4.csv", Path(tmp) / "ds_94_4.rdml"))
        comp_path = competimer_rdml(
            data / "ruijter" / "ds_competimer.csv", Path(tmp) / "competimer.rdml"
        )
        comp = competimer(comp_path)
        comp["post_hoc_without_failed_curve_analyses"] = competimer(comp_path, exclude_failed=True)
    x1, _ = held_out_plates(data / "untergasser")
    result = {
        "plan": "docs/review/32-external-data-tests.md (commit d0cfd27, fixed before scoring)",
        "x1_held_out_dpcr_plates": x1,
        "x2_shifted_baseline": shifted_baseline(data / "technical" / "shifted_baseline.rdml"),
        "x3_matrix_gaps": matrix_gaps(data / "technical" / "matrix_gaps.rdml"),
        "x4_ds94": {
            "wells": int(len(ds94)),
            "known_answer": ds94_known_answer(ds94),
            "no_difference": ds94_no_difference(ds94),
        },
        "x5_competimer": comp,
    }
    Path(out, "validation_external.json").write_text(json.dumps(result, indent=1, default=float))
    return result


def summary_lines(r: dict) -> list[str]:
    word = {True: "PASS", False: "FAIL"}
    x1 = r["x1_held_out_dpcr_plates"]
    lines = [
        f"X1 held-out dPCR plates ({x1['cases']} cases on {len(x1['plates'])} plates, nothing refitted):"
    ]
    for k in ("round_2", "p1_primary", "p1_amc_term", "p5_poisson"):
        a = x1[k]["all"]
        lo, hi = a["coverage_90%_cluster_bootstrap"]
        lines.append(
            f"   {k:12s} {100 * a['propagated_ci_with_truth_se']:.1f} % (CI over truths {100 * lo:.1f}-{100 * hi:.1f} %), "
            f"half-width {a['median_half_width_new']:.3f}  {word[x1[k]['pass']]}"
        )
    for p, v in x1["p1_primary"]["by_plate"].items():
        lines.append(
            f"   {p:52s} {v['cases']:3d} cases  P1 {100 * v['propagated_ci_with_truth_se']:.1f} %"
        )
    x2 = r["x2_shifted_baseline"]
    lines.append(
        f"X2 shifted baseline {word[x2['pass']]}: max |d log2 N0| {x2['max_abs_dlog2_n0']}, "
        f"max |d estimate| {x2['max_abs_d_estimate_log2']} over {x2['pair_estimates']} pair estimates"
    )
    x3 = r["x3_matrix_gaps"]
    if x3["runs"]:
        got = sum(1 for v in x3["damaged_wells"].values() if v.get("cq") is not None)
        lines.append(
            f"X3 missing cycles: analysis runs; {got} of {len(x3['damaged_wells'])} damaged wells get a Cq"
        )
    else:
        lines.append(f"X3 missing cycles: analysis FAILED ({x3['error']})")
    ka4 = r["x4_ds94"]["known_answer"]
    lines.append(
        "X4a ds_94_4 triplicates: "
        + ", ".join(
            f"{k} {100 * ka4[k]['coverage_equal_weight_over_pairs']:.1f} % {word[ka4[k]['pass']]}"
            for k in ("round_2", "p1_primary", "p5_poisson")
        )
    )
    for lvl, v in r["x4_ds94"]["no_difference"].items():
        rs = v["random_splits"]
        lines.append(
            f"X4b no difference at {lvl}: {word[v['pass']['overall']]}; cells calling "
            + ", ".join(f"{n} {100 * s['share_cells_calling']:.2f} %" for n, s in rs.items())
            + "; baseline median |log2| "
            + ", ".join(f"{s['baseline_median_abs_log2fc']}" for s in rs.values())
        )
    c = r["x5_competimer"]
    worst = c["fault_same_dna_vs_0pct"]["50%"]
    lines.append(
        "X5 competimer, 50 % vs 0 % same DNA, median error log2: "
        + ", ".join(f"{e} {v['median_bias_log2']:+.2f}" for e, v in worst.items())
    )
    d50 = c["detectors"]["50%"]
    lines.append(
        f"   detectors at 50 %: LinRegPCR flags {100 * d50['share_wells_flagged_by_linregpcr']:.0f} % of wells, "
        f"eff < 1.8 in {100 * d50['share_triplicates_mean_eff_below_1.8']:.0f} % of triplicates; "
        f"false alarm at 0 % {word[c['false_alarm']['pass']]}"
    )
    return lines
