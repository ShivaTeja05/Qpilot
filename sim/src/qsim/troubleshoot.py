"""Detectors: observations with evidence, never confirmed causes.

Each detector reports what it saw, where, by which rule, and the causes the observation is
consistent with. It never says a cause is confirmed; that needs new evidence (a re-run, a melt
curve, a gel).

The plate-level detectors work on residuals of a robust two-way model of log2 N0
(samples x genes, Tukey median polish). A sample's overall amount (input, RNA quality) and a
gene's overall level are removed, so what is left is gene-specific biology plus plate-specific
artefacts:

* ``ntc``: a no-template control amplified on a plate. Under MIQE 2.0 a sample counts as
  positive only if its Cq is at least 5 cycles earlier than the control, so wells within
  5 cycles are reported.
* ``well_outlier``: a residual more than ``z`` robust standard deviations from its plate's
  median. Consistent with pipetting, a bubble, a swap on that plate, or real biology.
* ``spatial``: one row, column or the edge ring of a plate differs from the rest
  (Mann-Whitney at alpha 0.01, Bonferroni within the plate; Dragiev et al. 2011,
  Mazoure et al. 2017).
* ``efficiency``: an assay's mean efficiency is below 1.8, or many of its wells were flagged.
* ``reference_group_effect``: a pair of reference genes changes ratio between the groups
  (qPilot's ``group_effect``). Normalising to them would add or remove signal.
* ``sample_outlier``: a sample's overall amount is far below the others (low input or
  degraded RNA), or its profile is unusually noisy (possible mislabel, or biology).

``identifiability`` states what this plate layout can and cannot separate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from qpilot.qpcr.quant import log2_matrix
from qpilot.qpcr.refgenes import group_effect
from scipy import stats

from qsim.data import ROWS, Study, well_position

MIQE_NTC_GAP = 5.0


@dataclass
class Observation:
    kind: str
    plate: str
    gene: str
    wells: list[str]
    samples: list[str]
    evidence: dict
    rule: str
    consistent_with: list[str]
    key: tuple = field(default=())

    def as_dict(self) -> dict:
        out = dict(self.__dict__)
        out["key"] = list(self.key)
        return out


def median_polish(x: np.ndarray, iterations: int = 10) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    e = x.copy()
    rows, cols = np.zeros(x.shape[0]), np.zeros(x.shape[1])
    for _ in range(iterations):
        r = np.nanmedian(e, axis=1)
        rows += r
        e -= r[:, None]
        c = np.nanmedian(e, axis=0)
        cols += c
        e -= c[None, :]
    return rows, cols, e


def _robust_z(v: np.ndarray) -> np.ndarray:
    med = np.nanmedian(v)
    mad = 1.4826 * np.nanmedian(np.abs(v - med))
    return (v - med) / mad if mad > 0 else np.zeros_like(v)


def detect_ntc(study: Study) -> list[Observation]:
    c = study.curves
    out = []
    for run, plate in c.groupby("run_id"):
        ntc = plate[(plate["sample_type"] == "ntc") & plate["cq"].notna()]
        if ntc.empty:
            continue
        unk = plate[(plate["sample_type"] == "unkn") & plate["cq"].notna()]
        ntc_cq = float(ntc["cq"].min())
        close = unk[unk["cq"] > ntc_cq - MIQE_NTC_GAP]
        gene = str(plate["target"].iloc[0])
        out.append(
            Observation(
                kind="ntc",
                plate=str(run),
                gene=gene,
                wells=list(close["well"]),
                samples=list(close["sample"]),
                evidence={
                    "ntc_wells_amplified": int(len(ntc)),
                    "earliest_ntc_cq": round(ntc_cq, 2),
                    "median_sample_cq": round(float(unk["cq"].median()), 2),
                    "samples_within_5_cycles": int(len(close)),
                    "share_within_5_cycles": round(len(close) / max(len(unk), 1), 3),
                },
                rule="no-template control amplified; samples within 5 cycles are not distinguishable (MIQE 2.0)",
                consistent_with=[
                    "reagent or template contamination",
                    "primer-dimer (check melt curve)",
                ],
                key=("ntc", str(run)),
            )
        )
    return out


def residuals(study: Study, rank: int = 8) -> np.ndarray:
    """Two-way median-polish residuals with a rank-``rank`` co-expression fit removed.

    The low-rank part (iterative SVD with imputation of missing wells) captures programmes of
    genes that move together across tumours, so a well is judged against what its sample's
    other genes predict, not only against the plate. Rank 8 lowers the median robust SD of the
    demo residuals from 1.20 to 0.91 log2 units without absorbing single-plate patterns.
    """
    _, _, e = median_polish(study.log2_n0)
    # on a small panel a fit of rank near the number of genes reproduces the residuals (with
    # two genes a median-polished row is (a, -a), rank 1); what is left is rounding noise, which
    # a robust z turns into "outliers". At most n_genes - 2 programmes; the demo keeps 8.
    rank = min(rank, e.shape[1] - 2)
    if rank <= 0:
        return e
    x = e.copy()
    missing = np.isnan(x)
    x[missing] = np.take(np.nanmedian(x, axis=0), np.where(missing)[1])
    for _ in range(5):
        centre = x.mean(axis=0)
        u, sv, vt = np.linalg.svd(x - centre, full_matrices=False)
        fit = (u[:, :rank] * sv[:rank]) @ vt[:rank] + centre
        x[missing] = fit[missing]
    out = e - fit
    out[missing] = np.nan
    return out


def detect_well_outliers(study: Study, e: np.ndarray, z: float = 5.0) -> list[Observation]:
    out = []
    for g, gene in enumerate(study.genes):
        zz = _robust_z(e[:, g])
        for i in np.where(np.abs(zz) > z)[0]:
            out.append(
                Observation(
                    kind="well_outlier",
                    plate=str(study.run[i, g]),
                    gene=gene,
                    wells=[str(study.well[i, g])],
                    samples=[study.samples[i]],
                    evidence={
                        "robust_z": round(float(zz[i]), 2),
                        "cq": round(float(study.cq[i, g]), 2),
                    },
                    rule=f"plate residual beyond {z:g} robust SD",
                    consistent_with=[
                        "pipetting error or bubble",
                        "sample swap on this plate",
                        "real biology of this sample",
                    ],
                    key=("well_outlier", gene, study.samples[i]),
                )
            )
    return out


def detect_spatial(
    study: Study, e: np.ndarray, alpha: float = 0.01, cut: float = 0.15
) -> list[Observation]:
    """Row, column and edge tests on residuals with each comparison group's median removed,
    so that biology which differs between the groups does not read as a plate pattern when the
    groups are not spread evenly over the plate."""
    out = []
    n_tests = len(ROWS) + 24 + 1
    hi, lo = study.group_masks(cut)
    strata = [hi, lo, ~(hi | lo)]
    for g, gene in enumerate(study.genes):
        wells = study.well[:, g]
        ok = ~np.isnan(e[:, g]) & (wells != "")
        if ok.sum() < 30:
            continue
        adjusted = e[:, g].copy()
        for stratum in strata:
            sel = stratum & ok
            if sel.any():
                adjusted[sel] -= np.nanmedian(adjusted[sel])
        pos = np.array([well_position(w) for w in wells[ok]])
        vals = adjusted[ok]
        groups = [("row", ROWS[r], pos[:, 0] == r) for r in range(len(ROWS))]
        groups += [("column", str(c + 1), pos[:, 1] == c) for c in range(24)]
        edge = (
            (pos[:, 0] == 0) | (pos[:, 0] == len(ROWS) - 1) | (pos[:, 1] == 0) | (pos[:, 1] == 23)
        )
        groups.append(("edge", "ring", edge))
        for axis, label, mask in groups:
            if mask.sum() < 3 or (~mask).sum() < 3:
                continue
            p = stats.mannwhitneyu(vals[mask], vals[~mask], method="asymptotic").pvalue
            if p < alpha / n_tests:
                shift = float(np.median(vals[mask]) - np.median(vals[~mask]))
                out.append(
                    Observation(
                        kind="spatial",
                        plate=str(study.run[ok, g][0]),
                        gene=gene,
                        wells=list(wells[ok][mask]),
                        samples=list(np.array(study.samples)[ok][mask]),
                        evidence={
                            "axis": axis,
                            "position": label,
                            "p": float(p),
                            "median_shift_log2": round(shift, 3),
                            "wells": int(mask.sum()),
                        },
                        rule=f"Mann-Whitney {axis} vs rest, alpha {alpha:g} / {n_tests} tests",
                        consistent_with=[
                            "evaporation or thermal gradient",
                            "multichannel pipetting error",
                            "placement of similar samples together",
                        ],
                        key=("spatial", gene, axis, label),
                    )
                )
    return out


def detect_efficiency(
    study: Study, low: float = 1.8, flagged_share: float = 0.05
) -> list[Observation]:
    out = []
    for g, gene in enumerate(study.genes):
        eff = float(np.nanmedian(study.eff_assay[:, g]))
        share = float(study.flag_eff[:, g].mean())
        if eff < low or share > flagged_share:
            out.append(
                Observation(
                    kind="efficiency",
                    plate=str(study.run[0, g]),
                    gene=gene,
                    wells=list(study.well[study.flag_eff[:, g], g]),
                    samples=list(np.array(study.samples)[study.flag_eff[:, g]]),
                    evidence={
                        "assay_efficiency": round(eff, 3),
                        "share_wells_flagged": round(share, 3),
                    },
                    rule=f"assay efficiency below {low} or more than {flagged_share:.0%} of wells flagged by LinRegPCR",
                    consistent_with=["inhibition", "poor primer design", "baseline problems"],
                    key=("efficiency", gene),
                )
            )
    return out


def detect_reference_group_effect(study: Study, cut: float = 0.15) -> list[Observation]:
    matrix = log2_matrix(study.curves)
    high, rest = study.groups[cut]
    result = group_effect(matrix, list(study.candidates), high, rest)
    out = []
    for shift in result.flagged:
        out.append(
            Observation(
                kind="reference_group_effect",
                plate="",
                gene="/".join(shift.genes),
                wells=[],
                samples=[],
                evidence={"log2_ratio_shift": round(float(shift.diff), 3), "p": float(shift.p)},
                rule="reference-gene ratio differs between groups by at least 2^0.5 (qPilot group_effect)",
                consistent_with=[
                    "a reference gene regulated by the condition",
                    "assay drift between groups",
                ],
                key=("reference_group_effect", tuple(sorted(shift.genes))),
            )
        )
    return out


def detect_sample_outliers(study: Study, e: np.ndarray, z: float = 3.5) -> list[Observation]:
    rows, _, _ = median_polish(study.log2_n0)
    out = []
    za = _robust_z(rows)
    spread = np.nanmedian(np.abs(e), axis=1)
    zs = _robust_z(spread)
    for i, smp in enumerate(study.samples):
        if za[i] < -z:
            out.append(
                Observation(
                    "sample_outlier",
                    "",
                    "all",
                    [],
                    [smp],
                    {"amount_robust_z": round(float(za[i]), 2)},
                    f"overall amount below {z:g} robust SD",
                    ["low input", "degraded RNA", "pipetting into the cDNA plate"],
                    key=("sample_amount", smp),
                )
            )
        if zs[i] > z:
            out.append(
                Observation(
                    "sample_outlier",
                    "",
                    "all",
                    [],
                    [smp],
                    {"profile_noise_robust_z": round(float(zs[i]), 2)},
                    f"profile noise above {z:g} robust SD",
                    ["sample mislabel or mix-up", "unusual biology"],
                    key=("sample_profile", smp),
                )
            )
    return out


def identifiability(study: Study, cut: float = 0.15) -> dict:
    """What this layout can separate: is position fixed per sample, are groups clustered?"""
    positions = study.well[:, : len(study.genes)]
    fixed = bool(all(len(set(row) - {""}) == 1 for row in positions))
    high, _ = study.groups[cut]
    wells = study.well[:, 0]
    pos = np.array([well_position(w) for w in wells])
    is_high = np.isin(np.array(study.samples), list(high))
    out = {"position_fixed_per_sample": fixed}
    for axis, name in ((0, "row"), (1, "column")):
        table = pd.crosstab(pos[:, axis], is_high)
        chi2, p, _, _ = stats.chi2_contingency(table)
        out[f"group_clustered_by_{name}_p"] = float(p)
    out["notes"] = []
    if fixed:
        out["notes"].append(
            "every sample sits in the same well on every plate: a position effect shared by all "
            "plates cannot be told apart from the sample, and largely cancels in reference "
            "normalisation; only plate-specific patterns are detectable"
        )
    if min(out["group_clustered_by_row_p"], out["group_clustered_by_column_p"]) < 0.01:
        out["notes"].append(
            "group membership is clustered on the plate; spatial artefacts could mimic group differences"
        )
    return out


def run_detectors(study: Study) -> tuple[list[Observation], dict]:
    e = residuals(study)
    obs = (
        detect_ntc(study)
        + detect_well_outliers(study, e)
        + detect_spatial(study, e)
        + detect_efficiency(study)
        + detect_reference_group_effect(study)
        + detect_sample_outliers(study, e)
    )
    return obs, identifiability(study)
