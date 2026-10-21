"""Independent re-measurement of Run Gate acceptance numbers.

Author: scientist. Spec: agent-bus/contracts/scientist-spec-gate.md. Reads the pinned Vermeulen
RDML through qPilot's own LinRegPCR wrapper (``qpilot.qpcr.curves.analyse_study``) and recomputes,
without any Gate code, what the Gate must reproduce:

* G-STD per biomarker plate: OLS of Cq on log10(copies) over amplified ``std`` wells (copies from
  the sample name ``STD_<copies>``), E = 10^(-1/slope) with a t-interval; fail if E is outside
  1.90-2.10 or R^2 < 0.980.
* G-NTC-1 per plate: earliest amplifying NTC Cq; unknown wells with Cq_ntc - Cq < 5 are tainted
  (MIQE 2.0); no melt data -> "unclassified" -> fail if any tainted, warn if none tainted.
* G-REP false-flag rate on ``380_replicates_set`` (one sample in 380 wells):
  tol = q95_range(n) * 0.15 / ln(E).

Run from a qPilot checkout:  python validation/scientist/gate_acceptance.py  [--out DIR]
Deterministic (fixed seed). Research use only.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import studentized_range

from qpilot.io.datasets import fetch_vermeulen
from qpilot.qpcr.curves import analyse_study


def g_std(plate: pd.DataFrame) -> dict:
    """G-STD fit and verdict for one plate."""
    s = plate[(plate.sample_type == "std") & plate.cq.notna()].copy()
    s["copies"] = s["sample"].str.extract(r"(\d+)")[0].astype(float)
    x, y = np.log10(s.copies.to_numpy()), s.cq.to_numpy()
    fit = stats.linregress(x, y)
    tq = stats.t.ppf(0.975, len(x) - 2)
    e = 10 ** (-1 / fit.slope)
    e_lo, e_hi = sorted(10 ** (-1 / (fit.slope + d * tq * fit.stderr)) for d in (-1, 1))
    levels = s.groupby("copies").size()
    r2 = fit.rvalue**2
    if len(levels) < 3:
        verdict = "not_applicable"
    elif e < 1.9 or e > 2.1 or r2 < 0.98:
        verdict = "fail"
    elif (levels < 3).any():
        verdict = "warn"
    else:
        verdict = "pass"
    return {
        "std_wells": len(x),
        "levels": len(levels),
        "slope": fit.slope,
        "E": e,
        "E_lo": e_lo,
        "E_hi": e_hi,
        "R2": r2,
        "E_perwell_std": s.eff_indiv.mean(),
        "g_std": verdict,
    }


def g_ntc(plate: pd.DataFrame, k: float = 5.0) -> dict:
    """G-NTC-1 evidence and verdict for one plate."""
    empty = {"ntc_min_cq": np.nan, "tainted": 0}
    ntc = plate[plate.sample_type == "ntc"]
    amp = ntc[ntc.cq.notna()]
    unk = plate[(plate.sample_type == "unkn") & plate.cq.notna()]
    if ntc.empty:
        return {"ntc_n": 0, "ntc_amp": 0, **empty, "g_ntc": "not_applicable"}
    if amp.empty:
        return {"ntc_n": len(ntc), "ntc_amp": 0, **empty, "g_ntc": "pass"}
    cmin = amp.cq.min()
    tainted = int(((cmin - unk.cq) < k).sum())
    return {
        "ntc_n": len(ntc),
        "ntc_amp": len(amp),
        "ntc_min_cq": cmin,
        "tainted": tainted,
        "g_ntc": "fail" if tainted else "warn",
    }


def g_rep_ds380(curves: pd.DataFrame, c: float = 0.15, draws: int = 10_000) -> pd.DataFrame:
    """False-flag rate of the G-REP tolerance on random replicate groups of ds_380."""
    keep = (curves.run_id == "380_replicates_set") & (curves.sample_type == "unkn")
    t = curves[keep & curves.cq.notna()]
    e = float(t.eff_target.iloc[0])
    cq = t.cq.to_numpy()
    rng = np.random.default_rng(380)
    rows = []
    for n in (2, 3, 4):
        tol = studentized_range.ppf(0.95, n, np.inf) * c / np.log(e)
        ranges = np.array([np.ptp(rng.choice(cq, n, replace=False)) for _ in range(draws)])
        rows.append(
            {
                "n": n,
                "wells": len(cq),
                "cq_sd": cq.std(ddof=1),
                "E": e,
                "tol_cycles": tol,
                "false_flag_rate": float(np.mean(ranges > tol)),
                "fixed_0.5_rule_rate": float(np.mean(ranges > 0.5)),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    """Run all three measurements and print the summary."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).parent / "out"))
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    rdml = fetch_vermeulen()
    bio = analyse_study(rdml)
    plates = pd.DataFrame(
        [{"run_id": run, **g_std(p), **g_ntc(p)} for run, p in bio.groupby("run_id", sort=True)]
    )
    plates.to_csv(out / "gate_plates.csv", index=False, float_format="%.6g")
    tech = analyse_study(rdml, experiment_id="technical_datasets")
    rep = g_rep_ds380(tech)
    rep.to_csv(out / "grep_ds380.csv", index=False, float_format="%.6g")
    print("G-STD:", plates.g_std.value_counts().to_dict())
    cols = ["run_id", "slope", "E", "E_lo", "E_hi", "R2"]
    print(plates[plates.g_std != "pass"][cols].round(3).to_string(index=False))
    gap = (plates.E - plates.E_perwell_std).median()
    print(
        f"E_std median {plates.E.median():.3f}; per-well E of std wells median "
        f"{plates.E_perwell_std.median():.3f}; gap median {gap:.3f}"
    )
    n_amp, n_ntc = int(plates.ntc_amp.sum()), int(plates.ntc_n.sum())
    p_amp, p_taint = int((plates.ntc_amp > 0).sum()), int((plates.tainted > 0).sum())
    print(
        "G-NTC-1:",
        plates.g_ntc.value_counts().to_dict(),
        f"| NTC amplified {n_amp}/{n_ntc} on {p_amp} plates",
        f"| tainted unknown wells {int(plates.tainted.sum())} on {p_taint} plates",
    )
    print(rep.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
