"""Load one qPCR study into the per-well arrays the simulator works on.

The curve analysis itself is qPilot's validated engine (LinRegPCR via the vendored rdmlpython,
one setting for every plate). This module only reshapes its per-well table into
samples x genes arrays, one array per quantity, so that every analysis choice can be applied
as a vectorised operation. Nothing here changes a number qPilot produced.

Efficiency models are exact rearrangements of LinRegPCR's own output: LinRegPCR reports
``N0 = Nq / E_assay^Cq`` with one fluorescence threshold ``Nq`` per plate, so
``log2 Nq = log2 N0 + Cq * log2 E_assay`` is recovered per well and any other efficiency E gives
``log2 N0(E) = log2 Nq - Cq * log2 E``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from qpilot.io.datasets import default_cache_dir, fetch_vermeulen
from qpilot.qpcr.curves import DEMO_EXPERIMENT, REFERENCE_TARGETS, analyse_study
from qpilot.qpcr.design import DEMO_MARKER, GroupSpec, groups_by_cut
from qpilot.qpcr.quant import log2_matrix
from qpilot.qpcr.refgenes import genorm

EFFICIENCY_NOTES = ("PCR efficiency outlier", "indiv PCR eff is")
LOW_COPY_NOTE = "Ncopy < 10"
STD_E_RANGE = (
    1.6,
    2.2,
)  # outside this a standard curve is not usable (slope from noise or one point)
ROWS = "ABCDEFGHIJKLMNOP"
BENCHMARK_NAME = "Neuroblastoma benchmark"  # how the screen names the default study


@dataclass(frozen=True)
class Study:
    """One study as aligned samples x genes arrays (one well per sample and gene)."""

    curves: pd.DataFrame
    input_sha256: str
    samples: list[str]
    genes: list[str]
    candidates: tuple[str, ...]
    primary_refs: tuple[str, ...]
    marker: str
    items: list[str]
    cq: np.ndarray
    log2_n0: np.ndarray
    log2_nq: np.ndarray
    eff_well: np.ndarray
    eff_assay: np.ndarray
    eff_std: np.ndarray
    flag_eff: np.ndarray
    flag_low: np.ndarray
    run: np.ndarray
    well: np.ndarray
    groups: dict[float, tuple[frozenset[str], frozenset[str]]]

    def gene_index(self, gene: str) -> int:
        return self.genes.index(gene)

    def item_columns(self) -> np.ndarray:
        return np.array([self.genes.index(g) for g in self.items])

    def group_masks(self, cut: float) -> tuple[np.ndarray, np.ndarray]:
        high, rest = self.groups[cut]
        names = np.array(self.samples)
        return np.isin(names, list(high)), np.isin(names, list(rest))


def demo_rdml() -> Path:
    """The public Vermeulen neuroblastoma RDML, fetched SHA-256-pinned by qPilot when missing."""
    path = default_cache_dir() / "data_vermeulen_raw.rdml"
    return path if path.exists() else fetch_vermeulen()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def load_study(
    rdml_path: str | Path | None = None,
    *,
    experiment: str = DEMO_EXPERIMENT,
    candidates: tuple[str, ...] = REFERENCE_TARGETS,
    marker: str = DEMO_MARKER,
    cuts: tuple[float, ...] = (0.10, 0.15, 0.20),
    curves: pd.DataFrame | None = None,
) -> Study:
    """Analyse (or reuse) the curves of one RDML file and align them into arrays.

    ``curves`` may be passed directly (the fault-injection benchmark does this with a modified
    copy); otherwise qPilot's cached curve analysis is used.
    """
    if curves is None:
        path = Path(rdml_path) if rdml_path else demo_rdml()
        curves = analyse_study(path, experiment, candidates)
        digest = sha256(path)
    else:
        digest = hashlib.sha256(pd.util.hash_pandas_object(curves).values.tobytes()).hexdigest()
    return study_from_curves(curves, digest, candidates=candidates, marker=marker, cuts=cuts)


def study_from_curves(
    curves: pd.DataFrame,
    input_sha256: str,
    *,
    candidates: tuple[str, ...] = REFERENCE_TARGETS,
    marker: str = DEMO_MARKER,
    cuts: tuple[float, ...] = (0.10, 0.15, 0.20),
) -> Study:
    """Build the aligned arrays; groups and primary references follow qPilot exactly."""
    matrix = log2_matrix(curves)  # raises on technical replicates, like qPilot
    samples, genes = list(matrix.index), list(matrix.columns)
    unknown = curves[curves["sample_type"] == "unkn"]
    unknown = unknown[unknown["sample"].isin(samples)]

    def grid(column: str, fill: object = np.nan, dtype: object = float) -> np.ndarray:
        table = unknown.pivot(index="sample", columns="target", values=column)
        return table.reindex(index=samples, columns=genes).fillna(fill).to_numpy(dtype=dtype)

    cq = grid("cq")
    n0 = grid("n0")
    eff_assay = grid("eff_target")
    eff_well = grid("eff_indiv")
    notes = grid("note", "", object)
    log2_n0 = np.log2(n0)
    log2_nq = log2_n0 + cq * np.log2(eff_assay)
    flag_eff = np.vectorize(lambda s: any(k in str(s) for k in EFFICIENCY_NOTES))(notes)
    flag_low = np.vectorize(lambda s: LOW_COPY_NOTE in str(s))(notes)
    eff_std = standard_curve_efficiency(curves)
    run_grid = grid("run_id", "", object)
    eff_std_grid = np.vectorize(lambda r: eff_std.get(r, np.nan))(run_grid).astype(float)
    stability = genorm(matrix, candidates)
    primary = tuple(g for g in candidates if g in set(stability.recommended))
    groups = groups_by_cut(matrix, GroupSpec(marker, 0.15, primary), cuts)
    items = [g for g in genes if g not in set(candidates) | {marker}]
    return Study(
        curves=curves,
        input_sha256=input_sha256,
        samples=samples,
        genes=genes,
        candidates=tuple(candidates),
        primary_refs=primary,
        marker=marker,
        items=items,
        cq=cq,
        log2_n0=log2_n0,
        log2_nq=log2_nq,
        eff_well=eff_well,
        eff_assay=eff_assay,
        eff_std=eff_std_grid,
        flag_eff=flag_eff.astype(bool),
        flag_low=flag_low.astype(bool),
        run=run_grid,
        well=grid("well", "", object),
        groups=groups,
    )


def standard_curve_efficiency(curves: pd.DataFrame) -> dict[str, float]:
    """Per plate: E = 10^(-1/slope) of Cq against log10 copies of the dilution standards.

    Standards are recognised by RDML sample type ``std`` and a copy number in the sample name
    (``STD_150000``). Plates without at least two standard levels get no value.
    """
    std = curves[(curves["sample_type"] == "std") & curves["cq"].notna()].copy()
    std["copies"] = pd.to_numeric(
        std["sample"].str.extract(r"(\d+(?:\.\d+)?)\s*$")[0], errors="coerce"
    )
    out = {}
    for run, plate in std.dropna(subset=["copies"]).groupby("run_id"):
        if plate["copies"].nunique() >= 2:
            slope = np.polyfit(np.log10(plate["copies"]), plate["cq"], 1)[0]
            e = float(10 ** (-1 / slope))
            if STD_E_RANGE[0] <= e <= STD_E_RANGE[1]:  # a broken curve gives no value
                out[str(run)] = e
    return out


def well_position(well: str) -> tuple[int, int]:
    """``"K17"`` -> (row index 10, column index 16)."""
    return ROWS.index(well[0]), int(well[1:]) - 1
