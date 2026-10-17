"""No-difference test (V4) on Ruijter et al. 2013 ``ds_380``: 380 replicates of one template.

Data: ``ds_380`` from the R package ``ruijter`` 0.1.3 (Ramiro Magno, CC BY 4.0), exported as CSV
from r-universe into ``data/ruijter/ds_380.csv``: raw SYBR fluorescence, 45 cycles, 380 wells of
150,000 copies of a MYCN amplicon plus 4 no-template controls on one Bio-Rad CFX384 plate. The
package manual corrects the published 15,000 copies to 150,000 (author email).

**Conversion.** :func:`to_rdml` writes the CSV into an RDML file with rdmlpython's own table
import (well, sample, sample type, target, dye, then one column per cycle), so qPilot's LinRegPCR
analyses it exactly as it would an instrument export. ``data/ruijter/ds_380.rdml`` is that file.

**The test.** Every well holds the same template, so any difference between two groups of wells
is false. Random 3 vs 3 and 6 vs 6 splits of the 380 wells are drawn, and each split is analysed
under every combination of the choices that can act on this plate:

* efficiency: LinRegPCR assay mean (baseline), each well's own, assume 100 %;
* flagged wells: keep (baseline), drop efficiency outliers, also drop wells below 10 copies;
* test: Welch (baseline), Student, Mann-Whitney (removed at 3 vs 3, where its smallest possible
  p is 0.1, by the same rule as :mod:`qsim.study_space`).

Choices that cannot act here are left out and listed in the output: the standard curve (one
concentration), late-Cq cut-offs (every Cq is near 19), non-detects (none among the 380),
reference genes (one target, so the test covers quantification and the statistics, not
normalisation) and multiple testing (one comparison). A call is the engine's rule: p < 0.05 and
at least two-fold. The robust filter is :mod:`qsim.designs`': the baseline call holds in at
least 95 % of the defensible analyses.

**Pass (ruling, V4):** at most 1 % of analysis cells make a call, no call passes the robust
filter, and the baseline's median |log2 fold change| is at most 0.15. A second draw puts the two
groups in different halves of the plate, to see whether position effects create calls; it is
reported but not part of the pass rule.
"""

from __future__ import annotations

import itertools
import json
import tempfile
from math import comb
from pathlib import Path

import numpy as np
import pandas as pd
from qpilot.qpcr.contrast import DEFAULT_RULE
from qpilot.qpcr.curves import analyse_study
from qpilot.vendor.rdmlpython import rdml
from scipy import stats

from qsim.data import EFFICIENCY_NOTES, LOW_COPY_NOTE, well_position

DATA = Path(__file__).resolve().parents[2] / "data" / "ruijter"
EXPERIMENT, RUN = "ds_380", "CFX384"
EFFICIENCY = {
    "assay_mean": "prespecified",
    "per_well": "common_practice",
    "assume_100": "common_practice",
}
FLAGGED = {"keep": "prespecified", "drop_eff": "defensible", "drop_eff_low": "common_practice"}
TESTS = {"welch": "prespecified", "student": "defensible", "mann_whitney": "defensible"}
NOT_APPLICABLE = {
    "std_curve": "one concentration, so no standard curve",
    "late_cq": "every Cq is between 16.7 and 19.6, below every cut-off",
    "nondetect": "no non-detects among the 380 template wells",
    "refs": "one target: the test covers quantification and statistics, not normalisation",
    "multiplicity": "one comparison per split",
}
ROBUST = 0.95
MAX_CALL_SHARE = 0.01
MAX_MEDIAN_LOG2 = 0.15


def to_rdml(csv: str | Path = DATA / "ds_380.csv", out: str | Path = DATA / "ds_380.rdml") -> Path:
    """Write the long-format CSV (well, sample_type, cycle, fluor, ...) as an RDML file."""
    t = pd.read_csv(csv)
    wide = t.pivot_table(index=["well", "sample_type"], columns="cycle", values="fluor")
    cycles = list(wide.columns)
    doc = rdml.Rdml()
    doc.new_experiment(EXPERIMENT)
    experiment = doc.get_experiment(byid=EXPERIMENT)
    experiment.new_run(RUN)
    plate = experiment.get_run(byid=RUN)
    plate["pcrFormat_rows"], plate["pcrFormat_columns"] = "16", "24"
    plate["pcrFormat_rowLabel"], plate["pcrFormat_columnLabel"] = "ABC", "123"
    lines = [
        "Well\tSample\tSample Type\tTarget\tTarget Type\tDye\tCq\t" + "\t".join(map(str, cycles))
    ]
    for (well, kind), row in wide.iterrows():
        sample, stype = ("MYCN 150000 copies", "unkn") if kind == "std" else ("NTC", "ntc")
        fluor = "\t".join(repr(float(v)) for v in row.to_numpy())
        lines.append(f"{well}\t{sample}\t{stype}\tMYCN\ttoi\tSYBR\t\t{fluor}")
    with tempfile.TemporaryDirectory() as tmp:
        table = Path(tmp) / "ds_380.tsv"
        table.write_text("\n".join(lines) + "\n")
        plate.import_table(doc, str(table), "amp")
    doc.save(str(out))
    return Path(out)


def load(path: str | Path = DATA / "ds_380.rdml") -> pd.DataFrame:
    curves = analyse_study(Path(path), EXPERIMENT, reference_targets=())
    wells = curves[(curves["sample_type"] == "unkn") & curves["cq"].notna()].copy()
    wells["log2_nq"] = np.log2(wells["n0"]) + wells["cq"] * np.log2(wells["eff_target"])
    notes = wells["note"].fillna("")
    wells["flag_eff"] = notes.map(lambda s: any(k in s for k in EFFICIENCY_NOTES))
    wells["flag_low"] = notes.str.contains(LOW_COPY_NOTE, regex=False)
    wells["column"] = wells["well"].map(lambda w: well_position(w)[1] + 1)
    return wells.reset_index(drop=True)


def _values(wells: pd.DataFrame) -> dict[str, np.ndarray]:
    nq, cq = wells["log2_nq"].to_numpy(), wells["cq"].to_numpy()
    return {
        "assay_mean": np.log2(wells["n0"].to_numpy()),
        "per_well": nq - cq * np.log2(wells["eff_indiv"].to_numpy()),
        "assume_100": nq - cq,
    }


def _keep(wells: pd.DataFrame) -> dict[str, np.ndarray]:
    eff, low = wells["flag_eff"].to_numpy(), wells["flag_low"].to_numpy()
    return {"keep": np.ones(len(wells), bool), "drop_eff": ~eff, "drop_eff_low": ~(eff | low)}


def _test(a: np.ndarray, b: np.ndarray, test: str) -> tuple[float, float]:
    diff = float(a.mean() - b.mean())
    if len(a) < 2 or len(b) < 2:
        return diff, float("nan")
    if test == "mann_whitney":
        p = stats.mannwhitneyu(a, b, alternative="two-sided", method="asymptotic").pvalue
    else:
        p = stats.ttest_ind(a, b, equal_var=test == "student").pvalue
    return diff, float(p)


def cells_for(n: int) -> list[tuple[str, str, str]]:
    """Every combination of the options at n vs n (Mann-Whitney only where it can reach alpha)."""
    tests = [t for t in TESTS if t != "mann_whitney" or 2 / comb(2 * n, n) <= DEFAULT_RULE.alpha]
    return list(itertools.product(EFFICIENCY, FLAGGED, tests))


def _defensible(cell: tuple[str, str, str]) -> bool:
    e, f, t = cell
    return "common_practice" not in (EFFICIENCY[e], FLAGGED[f], TESTS[t])


def splits(wells: pd.DataFrame, n: int, draws: int, rng: np.random.Generator, halves: bool):
    if not halves:
        for _ in range(draws):
            pick = rng.choice(len(wells), 2 * n, replace=False)
            yield pick[:n], pick[n:]
        return
    left = np.where(wells["column"].to_numpy() <= 12)[0]
    right = np.where(wells["column"].to_numpy() > 12)[0]
    for _ in range(draws):
        yield rng.choice(left, n, replace=False), rng.choice(right, n, replace=False)


def run(wells: pd.DataFrame, n: int, draws: int, seed: int, halves: bool = False) -> dict:
    rng = np.random.default_rng(np.random.SeedSequence([seed, n, int(halves)]))
    values, keep = _values(wells), _keep(wells)
    cells = cells_for(n)
    defensible = np.array([_defensible(c) for c in cells])
    base = cells.index(("assay_mean", "keep", "welch"))
    diff = np.full((draws, len(cells)), np.nan)
    p = np.full((draws, len(cells)), np.nan)
    for i, (a, b) in enumerate(splits(wells, n, draws, rng, halves)):
        for j, (e, f, t) in enumerate(cells):
            xa, xb = values[e][a][keep[f][a]], values[e][b][keep[f][b]]
            diff[i, j], p[i, j] = _test(xa, xb, t)
    sig = p < DEFAULT_RULE.alpha
    call = np.where(sig & (diff >= DEFAULT_RULE.min_log2fc), 1, 0)
    call = np.where(sig & (diff <= -DEFAULT_RULE.min_log2fc), -1, call)
    holds = (call[:, defensible] == call[:, [base]]).mean(axis=1)
    base_called = call[:, base] != 0
    by_eff = {}
    for e in EFFICIENCY:
        cols = [j for j, c in enumerate(cells) if c[0] == e]
        by_eff[e] = {
            "share_cells_calling": round(float((call[:, cols] != 0).mean()), 4),
            "share_cells_significant": round(float(sig[:, cols].mean()), 4),
            "median_abs_log2fc": round(float(np.nanmedian(np.abs(diff[:, cols]))), 3),
            "p95_abs_log2fc": round(float(np.nanpercentile(np.abs(diff[:, cols]), 95)), 3),
        }
    return {
        "draws": draws,
        "cells": len(cells),
        "defensible_cells": int(defensible.sum()),
        "share_cells_calling": round(float((call != 0).mean()), 4),
        "share_defensible_cells_calling": round(float((call[:, defensible] != 0).mean()), 4),
        "share_cells_significant": round(float(sig.mean()), 4),
        "share_defensible_cells_significant": round(float(sig[:, defensible].mean()), 4),
        "share_splits_any_defensible_call": round(
            float((call[:, defensible] != 0).any(axis=1).mean()), 4
        ),
        "baseline_calls": int(base_called.sum()),
        "calls_passing_robust_filter": int((base_called & (holds >= ROBUST)).sum()),
        "baseline_median_abs_log2fc": round(float(np.nanmedian(np.abs(diff[:, base]))), 3),
        "baseline_p95_abs_log2fc": round(float(np.nanpercentile(np.abs(diff[:, base]), 95)), 3),
        "by_efficiency": by_eff,
    }


def plate_effects(wells: pd.DataFrame) -> dict:
    """How much Cq moves with position on this one-template plate."""
    rows = wells["well"].map(lambda w: well_position(w)[0])
    edge = (rows == 0) | (rows == 15) | (wells["column"] == 1) | (wells["column"] == 24)
    cq = wells["cq"]
    return {
        "cq_median": round(float(cq.median()), 3),
        "cq_sd": round(float(cq.std()), 3),
        "sd_of_column_medians": round(float(cq.groupby(wells["column"]).median().std()), 3),
        "sd_of_row_medians": round(float(cq.groupby(rows).median().std()), 3),
        "edge_minus_interior_median_cq": round(float(cq[edge].median() - cq[~edge].median()), 3),
        "left_minus_right_half_median_cq": round(
            float(cq[wells["column"] <= 12].median() - cq[wells["column"] > 12].median()), 3
        ),
        "kruskal_p_by_column": float(
            stats.kruskal(*[g for _, g in cq.groupby(wells["column"])]).pvalue
        ),
    }


def validate(
    path: str | Path = DATA / "ds_380.rdml",
    out: str | Path = "results",
    draws: int = 1000,
    seed: int = 2026,
) -> dict:
    wells = load(path)
    result: dict = {
        "dataset": "Ruijter et al. 2013 ds_380 (R package ruijter 0.1.3, CC BY 4.0): 380 replicates of 150,000 copies, CFX384",
        "wells": int(len(wells)),
        "flagged_efficiency": int(wells["flag_eff"].sum()),
        "flagged_low_copy": int(wells["flag_low"].sum()),
        "rule": f"call = p < {DEFAULT_RULE.alpha} and |log2 FC| >= {DEFAULT_RULE.min_log2fc}",
        "not_applicable": NOT_APPLICABLE,
        "plate_effects": plate_effects(wells),
        "random_splits": {},
        "plate_half_splits": {},
    }
    for n in (3, 6):
        result["random_splits"][f"{n}v{n}"] = run(wells, n, draws, seed)
        result["plate_half_splits"][f"{n}v{n}"] = run(wells, n, draws, seed, halves=True)
    rs = result["random_splits"]
    result["pass"] = {
        "rule": f"<= {MAX_CALL_SHARE:.0%} of analysis cells call, no call passes the robust filter, baseline median |log2 FC| <= {MAX_MEDIAN_LOG2}",
        "all_cells": all(r["share_cells_calling"] <= MAX_CALL_SHARE for r in rs.values()),
        "defensible_cells": all(
            r["share_defensible_cells_calling"] <= MAX_CALL_SHARE for r in rs.values()
        ),
        "robust_filter": all(r["calls_passing_robust_filter"] == 0 for r in rs.values()),
        "median_abs_log2fc": all(
            r["baseline_median_abs_log2fc"] <= MAX_MEDIAN_LOG2 for r in rs.values()
        ),
    }
    result["pass"]["overall"] = bool(
        result["pass"]["all_cells"]
        and result["pass"]["robust_filter"]
        and result["pass"]["median_abs_log2fc"]
    )
    (Path(out) / "validation_nodiff.json").write_text(json.dumps(result, indent=1))
    return result
