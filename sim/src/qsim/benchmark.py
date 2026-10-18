"""Fault-injection benchmark: plant known problems in real data and see what the simulator finds.

Each trial copies the real per-well table, injects one fault at a random site (seeded), rebuilds
the study and runs the detectors. Faults act on the quantities LinRegPCR reports: a shift of
d cycles divides N0 by E^d.

* ``well_outlier``: one well is 3 cycles late (a pipetting error);
* ``row_offset``: every sample well in one row is 1 cycle late (a multichannel error);
* ``edge_ring``: every sample well on the plate edge is 0.7 cycles late (evaporation);
* ``sample_swap``: two samples' wells are swapped on one plate;
* ``ntc_contamination``: a no-template control amplifies 2 cycles after the median sample;
* ``reference_shift``: one reference gene is 0.6 cycles earlier in the MYCN-high group only (a
  regulated reference gene).

Scores per fault: how often the injected site is detected, how many new findings appear
elsewhere (false alarms against the clean run), and how often the fault changed any call.
Mutation testing is the template (Jia & Harman 2011).
"""

from __future__ import annotations

from collections import Counter

import numpy as np
import pandas as pd

from qsim.data import ROWS, Study, study_from_curves, well_position
from qsim.engine import Engine
from qsim.study_space import space_for
from qsim.troubleshoot import run_detectors

FAULTS = (
    "well_outlier",
    "row_offset",
    "edge_ring",
    "sample_swap",
    "ntc_contamination",
    "reference_shift",
)


def _shift(curves: pd.DataFrame, rows: pd.Index, cycles: float) -> None:
    curves.loc[rows, "cq"] = curves.loc[rows, "cq"] + cycles
    curves.loc[rows, "n0"] = curves.loc[rows, "n0"] / curves.loc[rows, "eff_target"] ** cycles


DEFAULT_SIZES = {
    "well_outlier": [3.0, 5.0, 8.0],
    "row_offset": [1.0, 2.0],
    "edge_ring": [0.7, 1.5],
    "sample_swap": [0.0],
    "ntc_contamination": [2.0],
    "reference_shift": [0.3, 0.6],
}


def inject(
    study: Study, fault: str, rng: np.random.Generator, size: float | None = None
) -> tuple[pd.DataFrame, dict]:
    """Return a faulty copy of the per-well table and where the fault was put.

    ``size`` is in cycles (for the NTC: cycles after the median sample)."""
    c = study.curves.copy()
    unk = (c["sample_type"] == "unkn") & c["cq"].notna() & c["sample"].isin(study.samples)
    item_genes = [g for g in study.items]
    if fault in ("well_outlier", "row_offset", "edge_ring", "sample_swap"):
        gene = str(rng.choice(item_genes))
        on = unk & (c["target"] == gene)
        if fault == "well_outlier":
            row = rng.choice(c.index[on])
            _shift(c, pd.Index([row]), 3.0 if size is None else size)
            return c, {"gene": gene, "samples": [c.at[row, "sample"]], "well": c.at[row, "well"]}
        if fault == "row_offset":
            r = str(rng.choice(list(ROWS[:-2])))  # rows O-P hold standards and controls
            rows = c.index[
                on & c["well"].str.startswith(r) & ~c["well"].str[1:].str.contains(r"\D")
            ]
            _shift(c, rows, 1.0 if size is None else size)
            return c, {"gene": gene, "row": r}
        if fault == "edge_ring":
            pos = c.loc[on, "well"].map(well_position)
            edge = pos.map(lambda p: p[0] in (0, len(ROWS) - 1) or p[1] in (0, 23))
            _shift(c, edge.index[edge], 0.7 if size is None else size)
            return c, {"gene": gene}
        if fault == "sample_swap":
            a, b = rng.choice(c.index[on], size=2, replace=False)
            for col in ("cq", "n0"):
                c.loc[a, col], c.loc[b, col] = c.loc[b, col], c.loc[a, col]
            return c, {"gene": gene, "samples": [c.at[a, "sample"], c.at[b, "sample"]]}
    if fault == "ntc_contamination":
        clean = [
            run
            for run, p in c.groupby("run_id")
            if p.loc[p["sample_type"] == "ntc", "cq"].isna().all()
        ]
        run = str(rng.choice(clean))
        plate = c[c["run_id"] == run]
        ntc_row = plate.index[plate["sample_type"] == "ntc"][0]
        c.loc[ntc_row, "cq"] = float(plate.loc[plate["sample_type"] == "unkn", "cq"].median()) + (
            2.0 if size is None else size
        )
        c.loc[ntc_row, "amplification"] = True
        return c, {"plate": run, "gene": str(plate["target"].iloc[0])}
    if fault == "reference_shift":
        gene = str(rng.choice(list(study.primary_refs)))
        high, _ = study.groups[0.15]
        rows = c.index[unk & (c["target"] == gene) & c["sample"].isin(list(high))]
        _shift(c, rows, -(0.6 if size is None else size))
        return c, {"gene": gene}
    raise ValueError(f"unknown fault {fault!r}")


def detected(fault: str, truth: dict, keys: set) -> bool:
    if fault in ("well_outlier", "sample_swap"):
        return any(("well_outlier", truth["gene"], smp) in keys for smp in truth["samples"])
    if fault == "row_offset":
        return ("spatial", truth["gene"], "row", truth["row"]) in keys
    if fault == "edge_ring":
        return any(k[0] == "spatial" and k[1] == truth["gene"] for k in keys)
    if fault == "ntc_contamination":
        return ("ntc", truth["plate"]) in keys
    if fault == "reference_shift":
        return any(k[0] == "reference_group_effect" and truth["gene"] in k[1] for k in keys)
    raise ValueError(fault)


def run_benchmark(
    study: Study, trials: int = 25, seed: int = 2026, sizes: dict[str, list[float]] | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(np.random.SeedSequence(seed))
    clean_obs, _ = run_detectors(study)
    clean_keys = {o.key for o in clean_obs}
    space = space_for(study)[0]
    base_call = Engine(study, space).evaluate(space.baseline_index())["call"]
    rows = []
    sizes = sizes or DEFAULT_SIZES
    for fault in FAULTS:
        for size in sizes[fault]:
            for trial in range(trials):
                curves, truth = inject(study, fault, rng, size)
                faulty = study_from_curves(
                    curves, "fault", candidates=study.candidates, marker=study.marker
                )
                obs, _ = run_detectors(faulty)
                keys = {o.key for o in obs}
                new = keys - clean_keys
                hit = detected(fault, truth, keys)
                gene = truth.get("gene")
                own = {
                    k
                    for k in new
                    if len(k) > 1 and (k[1] == gene or (isinstance(k[1], tuple) and gene in k[1]))
                } | ({("ntc", truth["plate"])} if "plate" in truth else set())
                call = Engine(faulty, space_for(faulty)[0]).evaluate(space.baseline_index())["call"]
                rows.append(
                    {
                        "fault": fault,
                        "size_cycles": size,
                        "trial": trial,
                        "detected": hit,
                        "new_findings_elsewhere": len(new - own),
                        "calls_changed": int((call != base_call).sum()),
                        "truth": truth,
                    }
                )
    detail = pd.DataFrame(rows)
    summary = detail.groupby(["fault", "size_cycles"], sort=False).agg(
        trials=("trial", "size"),
        detection_rate=("detected", "mean"),
        mean_new_findings_elsewhere=("new_findings_elsewhere", "mean"),
        share_trials_changing_a_call=("calls_changed", lambda x: float((x > 0).mean())),
    )
    changing = detail[detail["calls_changed"] > 0]
    summary["detection_rate_when_a_call_changed"] = changing.groupby(["fault", "size_cycles"])[
        "detected"
    ].mean()
    return summary, detail


def clean_counts(study: Study) -> dict:
    obs, _ = run_detectors(study)
    return dict(Counter(o.kind for o in obs))
