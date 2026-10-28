"""Load one qPCR study into the per-well arrays the simulator works on.

The curve analysis itself is qPilot's validated engine (LinRegPCR via the vendored rdmlpython,
one setting for every plate). This module only reshapes its per-well table into
samples x genes arrays, one array per quantity, so that every analysis choice can be applied
as a vectorised operation. Nothing here changes a number qPilot produced.

Efficiency models are exact rearrangements of LinRegPCR's own output: LinRegPCR reports
``N0 = Nq / E_assay^Cq`` with one fluorescence threshold ``Nq`` per plate, so
``log2 Nq = log2 N0 + Cq * log2 E_assay`` is recovered per well and any other efficiency E gives
``log2 N0(E) = log2 Nq - Cq * log2 E``.

**Technical replicates.** A study may have several wells per sample and gene (triplicates, or
several samples of one biological unit renamed to that unit by the caller). The samples x genes
arrays then summarise each value's wells (the ``log2 N0`` grid is qPilot's own unit-level
matrix, :func:`qpilot.qpcr.quant.log2_matrix`), and :class:`Replicates` keeps every well, so the
engine applies each choice to each well first and then combines a value's wells the way qPilot
does: the mean ``log2 N0`` of the wells that have a quantity (the geometric mean of N0),
undetermined only when every well is. A study with one well per sample and gene has no
:class:`Replicates` and is built exactly as before.
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
from qpilot.qpcr.quant import EXCLUDED, log2_matrix
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
class Replicates:
    """Every well behind each sample-and-gene value: arrays of shape (samples, genes, wells).

    ``present`` marks a real well (a value with fewer wells than the most is padded with NaN);
    a value's wells are ordered by run, then well. ``excluded`` marks wells a person excluded
    (qPilot's ``design_excluded`` column). ``n0_missing`` marks wells without a quantity:
    qPilot's undetermined, which the engine reads from a missing Cq (the caller aligns the two).
    """

    present: np.ndarray
    cq: np.ndarray
    log2_n0: np.ndarray
    log2_nq: np.ndarray
    eff_well: np.ndarray
    eff_assay: np.ndarray
    eff_std: np.ndarray
    flag_eff: np.ndarray
    flag_low: np.ndarray
    excluded: np.ndarray
    run: np.ndarray
    well: np.ndarray

    @property
    def most(self) -> int:
        """The most wells behind any one value."""
        return int(self.present.sum(axis=2).max()) if self.present.size else 0

    def keys(self) -> np.ndarray:
        """``"<run_id>/<well>"`` per well (``""`` for padding)."""
        joined = np.char.add(np.char.add(self.run.astype(str), "/"), self.well.astype(str))
        return np.where(self.present, joined, "")


@dataclass(frozen=True)
class Study:
    """One study as aligned samples x genes arrays (one well per sample and gene, or the
    summary of each value's technical replicates, which :attr:`replicates` then holds)."""

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
    replicates: Replicates | None = None

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
    matrix = log2_matrix(curves)  # technical replicates: the mean log2 N0 per sample, as qPilot
    arrays, replicates = study_arrays(curves, matrix)
    stability = genorm(matrix, candidates)
    primary = tuple(g for g in candidates if g in set(stability.recommended))
    groups = groups_by_cut(matrix, GroupSpec(marker, 0.15, primary), cuts)
    genes = list(matrix.columns)
    items = [g for g in genes if g not in set(candidates) | {marker}]
    return Study(
        curves=curves,
        input_sha256=input_sha256,
        samples=list(matrix.index),
        genes=genes,
        candidates=tuple(candidates),
        primary_refs=primary,
        marker=marker,
        items=items,
        groups=groups,
        replicates=replicates,
        **arrays,
    )


def study_arrays(
    curves: pd.DataFrame, matrix: pd.DataFrame
) -> tuple[dict[str, np.ndarray], Replicates | None]:
    """The samples x genes arrays of :class:`Study` (and its replicates, when there are any).

    ``matrix`` is :func:`qpilot.qpcr.quant.log2_matrix` of ``curves``: its rows and columns are
    the study's samples and genes. With one well per sample and gene each array is that well's
    value; otherwise each is a summary of the value's wells (see :func:`replicate_arrays`).
    """
    samples, genes = list(matrix.index), list(matrix.columns)
    unknown = curves[curves["sample_type"] == "unkn"]
    unknown = unknown[unknown["sample"].isin(samples)]
    if unknown.duplicated(["sample", "target"]).any():
        return replicate_arrays(unknown, matrix, standard_curve_efficiency(curves))

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
    arrays = {
        "cq": cq,
        "log2_n0": log2_n0,
        "log2_nq": log2_nq,
        "eff_well": eff_well,
        "eff_assay": eff_assay,
        "eff_std": eff_std_grid,
        "flag_eff": flag_eff.astype(bool),
        "flag_low": flag_low.astype(bool),
        "run": run_grid,
        "well": grid("well", "", object),
    }
    return arrays, None


def replicate_arrays(
    unknown: pd.DataFrame, matrix: pd.DataFrame, eff_std: dict[str, float]
) -> tuple[dict[str, np.ndarray], Replicates]:
    """Per-well arrays (samples x genes x wells) and the samples x genes summaries of them.

    The summaries are what single-well readers see (plate checks, the lab panels): ``log2_n0``
    is ``matrix`` itself (qPilot's mean over the wells with a quantity, a person's exclusions
    left out); ``cq`` and the efficiencies are the means over the same wells; a value is flagged
    when any of its wells is; ``run`` and ``well`` are its first well's (by run, then well), so a
    position always names a real well. Every number the engine compares comes from the wells.
    """
    samples, genes = list(matrix.index), list(matrix.columns)
    rows = unknown[unknown["target"].isin(genes)].copy()
    rows["_i"] = rows["sample"].map({s: i for i, s in enumerate(samples)})
    rows["_j"] = rows["target"].map({g: j for j, g in enumerate(genes)})
    rows = rows.sort_values(["_i", "_j", "run_id", "well"], kind="mergesort")
    rows["_k"] = rows.groupby(["_i", "_j"]).cumcount()
    i, j, k = (rows[c].to_numpy(dtype=int) for c in ("_i", "_j", "_k"))
    shape = (len(samples), len(genes), int(k.max()) + 1 if len(k) else 1)

    def cube(values: np.ndarray, fill: object = np.nan, dtype: object = float) -> np.ndarray:
        out = np.full(shape, fill, dtype=dtype)
        out[i, j, k] = values
        return out

    present = cube(np.ones(len(rows), dtype=bool), False, bool)
    cq = cube(rows["cq"].to_numpy(dtype=float))
    with np.errstate(divide="ignore", invalid="ignore"):
        log2_n0 = cube(np.log2(rows["n0"].to_numpy(dtype=float)))
    eff_assay = cube(rows["eff_target"].to_numpy(dtype=float))
    eff_well = cube(rows["eff_indiv"].to_numpy(dtype=float))
    notes = rows["note"].fillna("").astype(str)
    flag_eff = cube(
        notes.map(lambda s: any(n in s for n in EFFICIENCY_NOTES)).to_numpy(), False, bool
    )
    flag_low = cube(notes.map(lambda s: LOW_COPY_NOTE in s).to_numpy(), False, bool)
    if EXCLUDED in rows.columns:
        excluded = cube(rows[EXCLUDED].astype(bool).to_numpy(), False, bool)
    else:
        excluded = np.zeros(shape, dtype=bool)
    runs = rows["run_id"].astype(str)
    run = cube(runs.to_numpy(dtype=object), "", object)
    well = cube(rows["well"].astype(str).to_numpy(dtype=object), "", object)
    std = cube(runs.map(lambda r: eff_std.get(r, np.nan)).to_numpy(dtype=float))
    with np.errstate(invalid="ignore"):
        log2_nq = log2_n0 + cq * np.log2(eff_assay)
    reps = Replicates(
        present=present,
        cq=cq,
        log2_n0=log2_n0,
        log2_nq=log2_nq,
        eff_well=eff_well,
        eff_assay=eff_assay,
        eff_std=std,
        flag_eff=flag_eff,
        flag_low=flag_low,
        excluded=excluded,
        run=run,
        well=well,
    )
    used = present & ~np.isnan(log2_n0) & ~excluded

    def mean(values: np.ndarray, where: np.ndarray) -> np.ndarray:
        n = where.sum(axis=2)
        total = np.where(where, values, 0.0).sum(axis=2)
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(n > 0, total / n, np.nan)

    summary_n0 = matrix.to_numpy(dtype=float)
    summary_cq = mean(cq, used)
    summary_eff = mean(eff_assay, present & ~np.isnan(eff_assay))
    with np.errstate(invalid="ignore", divide="ignore"):
        summary_nq = summary_n0 + summary_cq * np.log2(summary_eff)
    arrays = {
        "cq": summary_cq,
        "log2_n0": summary_n0,
        "log2_nq": summary_nq,
        "eff_well": mean(eff_well, used & ~np.isnan(eff_well)),
        "eff_assay": summary_eff,
        "eff_std": std[:, :, 0],
        "flag_eff": (flag_eff & present).any(axis=2),
        "flag_low": (flag_low & present).any(axis=2),
        "run": run[:, :, 0],
        "well": well[:, :, 0],
    }
    return arrays, reps


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
