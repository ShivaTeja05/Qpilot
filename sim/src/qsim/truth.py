"""Digital-PCR truth for the Untergasser dilution series, and which dPCR well measured what.

Source: "Quantify Standard by dPCR" (27.08.2025) in the RDML consortium's Untergasser folder. A
qPCR plate (LightCycler 480 at DKFZ, experiment "dPCR - DKFZ" in ``large_DNA_dilutions.rdml``)
and a QX200 droplet dPCR plate were prepared from the same DNA tubes. The genomic DNA tubes are
the one dilution series made in AMC in December 2024 and used for every later experiment, so the
same truth also applies to "DNA Dilution - AMC" (measured eight months earlier; see the caveat in
``docs/review/30-validation-round-2.md``).

**The mapping.** The dPCR plate layout (``large_DNA_dilutions_pipett_dpcr.tsv``) says which assay
and sample each dPCR well holds:

=====  ============  ==============================================================
row    mix           wells 1-8
=====  ============  ==============================================================
A      probe         FSTL_1_F_109: test, 0, EMBL 20, 20, 7, 2, 0.7, 0.2 (ng)
B      probe         FSTL_1_K_219: the same eight samples
C      probe         amplicon standard 10^5, 10^4, 10^3, 10^2 with F_109 (C1-C4), then K_219
D      EvaGreen      the same standards with H_201 (D1-D4), then L_412 (D5-D8)
=====  ============  ==============================================================

Assay names in both the layout and the result files were numbered on by spreadsheet fill
(FSTL_1_F_109, F_110, ... F_116 along row A), so the assay is identified by its letter (F, K, H,
L), which is unique among the four primer pairs (:data:`ASSAYS`). The EvaGreen wells ran on their
own dPCR plate, whose row A is layout row D. Layout labels, the result files' sample names and
the qPCR sample names correspond as in :data:`SAMPLES`; :func:`load_dpcr` raises if a result
file's sample name or assay letter disagrees with the layout. The amplicon labels are copies in the 2 µl added (200000 = the 10^5 copies/µl tube).
The qPCR plate has the amplicon standards twice: the freshly made 1:10 series ("Dil 1:10") and
aliquots frozen and thawed ten times ("Freeze"). The dPCR measured the fresh series; the frozen
aliquots are scored as a secondary comparison under the same truth. EvaGreen well D1 (H_201 at
10^5) is missing from the result file, and the "test" sample is not on the qPCR plate.

**The truth of a pair of tubes** is the dPCR log2 ratio. Every assay targets the single-copy gene
FSTL1 and both tubes of a pair hold the same molecules for every assay, so the ratio is a
property of the tubes. It is the mean over the dPCR assays that measured both tubes, after a
quality check that uses the dPCR table alone (never the qPCR):

* a well above :data:`UPPER_COPIES` copies per 20 µl is left out: that is beyond the QX200's
  linear range, and both probe wells of the 10^5 standard have 99.9 % of droplets positive;
* with three or more assays, an assay more than :data:`DISCORDANT_LOG2` from the median is left
  out;
* a pair needs two or more remaining assays that agree within :data:`DISCORDANT_LOG2`. Otherwise
  it is **unresolved**: dPCR gives no single truth, and the pair is reported separately under
  each assay's value and the nominal ratio. This happens for the 0.2 ng tube (F_109 and K_219
  differ 2.5-fold) and the 10^5 standard (only the EvaGreen L_412 well is in range).

The truth's standard error combines each well's Poisson interval (from the result file) and a
dPCR well-to-well term (pipetting into the dPCR mix), estimated from how F_109 and K_219 differ
on the same genomic tubes beyond their Poisson error.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from qpilot.qpcr.curves import safe_name

DATA = Path(__file__).resolve().parents[2] / "data" / "untergasser"
LAYOUT = "large_DNA_dilutions_pipett_dpcr.tsv"
#: result file -> layout row of its wells' row A (the EvaGreen wells ran on their own plate)
RESULTS = {
    "large_DNA_dilutions_res_dpcr_probe.tsv": {},
    "large_DNA_dilutions_res_dpcr_evagreen.tsv": {"A": "D"},
}
#: the assay letter in FSTL_1_<letter>_<number> -> the qPCR assay (each letter is one primer pair)
ASSAYS = {"F": "FSTL_1_F_109", "K": "FSTL_1_K_219", "H": "FSTL_1_H_201", "L": "FSTL_1_L_412"}
DISCORDANT_LOG2 = 0.5  # a 1.41-fold disagreement between dPCR assays on the same tubes
UPPER_COPIES = 1e5  # per 20 µl: the QX200's stated upper limit of linear quantification
Z95 = 1.959963984540054

#: dPCR layout label -> (name in the dPCR result files, qPCR sample, series, nominal amount)
SAMPLES: dict[str, tuple[str, str, str, float]] = {
    "20": ("20", "genomic DNA 20ng", "gDNA", 20.0),
    "7": ("7", "genomic DNA 7ng", "gDNA", 7.0),
    "2": ("2", "genomic DNA 2ng", "gDNA", 2.0),
    "0.7": ("0.7", "genomic DNA 0.7ng", "gDNA", 0.7),
    "0.2": ("0.2", "genomic DNA 0.2ng", "gDNA", 0.2),
    "EMBL 20": ("EMBL20", "EMBL DNA 20ng", "EMBL", 20.0),
    "0": ("NTC", "genomic DNA 0ng", "gDNA", 0.0),
    "200000": ("a20000", "Dil 1:10 - 10e5", "amplicon", 1e5),
    "20000": ("a2000", "Dil 1:10 - 10e4", "amplicon", 1e4),
    "2000": ("a200", "Dil 1:10 - 10e3", "amplicon", 1e3),
    "200": ("a20", "Dil 1:10 - 10e2", "amplicon", 1e2),
    "test": ("FF", "", "unused", float("nan")),
}


def qpcr_name(name: str) -> str:
    """A sample name as qPilot's curve table holds it (``Dil 1:10 - 10e5`` -> ``dil_1_10_10e5``)."""
    log = logging.getLogger("qpilot.qpcr.curves")
    level, log.level = log.level, logging.ERROR
    try:
        return safe_name(name, "sample")
    finally:
        log.setLevel(level)


def _layout(path: Path) -> dict[str, tuple[str, str, str]]:
    """Well (``A01``) -> (layout sample label, assay, mix) from the dPCR pipetting scheme."""
    rows = list(csv.reader(path.open(encoding="utf-8"), delimiter="\t"))
    blocks = [i for i, r in enumerate(rows) if r[1:4] == ["1", "2", "3"]]
    if len(blocks) < 2:
        raise ValueError(f"{path.name}: expected two 8-column blocks (samples, assays)")

    def block(start: int) -> dict[str, list[str]]:
        out = {}
        for r in rows[start + 1 : start + 5]:
            out[r[0]] = [c.strip() for c in r[1:9]] + [r[10].strip() if len(r) > 10 else ""]
        return out

    samples, assays = block(blocks[0]), block(blocks[1])
    layout = {}
    for row in "ABCD":
        for col in range(8):
            layout[f"{row}{col + 1:02d}"] = (samples[row][col], assays[row][col], samples[row][8])
    return layout


def load_dpcr(data: Path = DATA) -> pd.DataFrame:
    """One row per dPCR well: assay, qPCR sample, copies and log2 Poisson standard error."""
    layout = _layout(data / LAYOUT)
    rows = []
    for name, rows_to_layout in RESULTS.items():
        table = pd.read_csv(data / name, sep="\t", dtype=str, keep_default_na=False)
        for _, r in table.iterrows():
            well = r["Well"].strip()
            if not well:
                continue
            well = rows_to_layout.get(well[0], well[0]) + well[1:]
            label, layout_assay, mix = layout[well]
            assay = ASSAYS[layout_assay.split("_")[2]]
            result_name, qpcr, series, nominal = SAMPLES[label]
            if r["Sample"].strip() != result_name or ASSAYS[r["Target"].split("_")[2]] != assay:
                raise ValueError(
                    f"{name} {r['Well']}: {r['Sample']!r}/{r['Target']!r}, layout {well} says "
                    f"{label!r} ({result_name}) with {assay}"
                )
            copies = pd.to_numeric(r["Copies/20µLWell"], errors="coerce")
            lo = pd.to_numeric(r["PoissonConfMin"], errors="coerce")
            hi = pd.to_numeric(r["PoissonConfMax"], errors="coerce")
            se = (np.log2(hi) - np.log2(lo)) / (2 * Z95) if lo > 0 and hi > 0 else np.nan
            rows.append(
                {
                    "well": well,
                    "assay": assay,
                    "mix": mix,
                    "label": label,
                    "qpcr_sample": qpcr_name(qpcr) if qpcr else "",
                    "series": series,
                    "nominal": nominal,
                    "copies": copies,
                    "log2_copies": np.log2(copies) if copies > 0 else np.nan,
                    "se_poisson": se,
                    "droplets": int(r["Accepted Droplets"] or 0),
                    "positives": int(r["Positives"] or 0),
                    "status": r["Status"],
                }
            )
    return pd.DataFrame(rows)


def dpcr_well_sd(dpcr: pd.DataFrame) -> float:
    """dPCR well-to-well SD (log2) beyond Poisson, from F_109 vs K_219 on the same genomic tubes.

    Var(log2 F/K across tubes) = 2 sd^2 + mean(Poisson variances). Uses the dilution-series tubes
    whose F/K difference is within :data:`DISCORDANT_LOG2` of the median difference.
    """
    g = dpcr[(dpcr["series"] == "gDNA") & (dpcr["nominal"] > 0)]
    wide = g.pivot_table(index="label", columns="assay", values=["log2_copies", "se_poisson"])
    d = wide["log2_copies"]["FSTL_1_F_109"] - wide["log2_copies"]["FSTL_1_K_219"]
    ok = (d - d.median()).abs() <= DISCORDANT_LOG2
    pois = (wide["se_poisson"]["FSTL_1_F_109"] ** 2 + wide["se_poisson"]["FSTL_1_K_219"] ** 2)[ok]
    excess = float(d[ok].var(ddof=1) - pois.mean())
    return float(np.sqrt(max(excess, 0.0) / 2))


@dataclass(frozen=True)
class PairTruth:
    log2: float  # NaN when unresolved
    se: float
    source: str  # "dPCR mean of k assays", "unresolved", ...
    assays: tuple[str, ...]
    per_assay: dict[str, float]


def pair_truth(dpcr: pd.DataFrame, hi: str, lo: str, sd_well: float) -> PairTruth | None:
    """Truth of the log2 ratio between two qPCR samples (``safe_name`` form), or None."""
    a = dpcr[dpcr["qpcr_sample"] == hi].set_index("assay")
    b = dpcr[dpcr["qpcr_sample"] == lo].set_index("assay")
    both = sorted(set(a.index) & set(b.index))
    ratio = {k: float(a.loc[k, "log2_copies"] - b.loc[k, "log2_copies"]) for k in both}
    ratio = {k: v for k, v in ratio.items() if np.isfinite(v)}
    if not ratio:
        return None
    var = {
        k: float(a.loc[k, "se_poisson"] ** 2 + b.loc[k, "se_poisson"] ** 2 + 2 * sd_well**2)
        for k in ratio
    }
    keep = [k for k in ratio if max(a.loc[k, "copies"], b.loc[k, "copies"]) <= UPPER_COPIES]
    if len(keep) >= 3:
        med = float(np.median([ratio[k] for k in keep]))
        keep = [k for k in keep if abs(ratio[k] - med) <= DISCORDANT_LOG2]
    if len(keep) < 2 or np.ptp([ratio[k] for k in keep]) > DISCORDANT_LOG2:
        return PairTruth(np.nan, np.nan, "unresolved", tuple(keep), ratio)
    est = float(np.mean([ratio[k] for k in keep]))
    se = float(np.sqrt(sum(var[k] for k in keep)) / len(keep))
    return PairTruth(est, se, f"dPCR mean of {len(keep)}", tuple(keep), ratio)


def nominal_sd(dpcr: pd.DataFrame, sd_well: float, pairs: list[tuple[str, str, float]]) -> float:
    """How far nominal ratios sit from dPCR on resolved genomic pairs: an error bar for the
    nominal truth used where no dPCR exists (RMS of dPCR minus nominal, less dPCR's own error)."""
    gaps, own = [], []
    for hi, lo, nominal in pairs:
        t = pair_truth(dpcr, hi, lo, sd_well)
        if t is None or not np.isfinite(t.log2):
            continue
        gaps.append(t.log2 - nominal)
        own.append(t.se**2)
    if not gaps:
        return float("nan")
    return float(np.sqrt(max(np.mean(np.square(gaps)) - np.mean(own), 0.0)))
