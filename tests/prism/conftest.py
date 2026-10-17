"""Fixtures for the Prism bridge: a toy study with technical replicates and the demo study."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qpilot.qpcr.export import ExportInputs

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "prism"
TOY_CHAIN = "ab" * 32
TOY_STUDY = "70a0000000c1"

# log2(n0) of each well: unit -> gene -> three technical replicates. Refs average to 11 in every
# unit, so a unit's column value is mean(T) - 11 and its nested values are each well - 11.
TOY_LOG2 = {
    "a1": {"T": [5, 6, 7], "T2": [1, 1, 1], "R1": [10, 10.5, 9.5], "R2": [12, 12, 12]},
    "a2": {"T": [6, 7, 8], "T2": [2, 2, 2], "R1": [10, 10, 10], "R2": [12, 12, 12]},
    "a3": {"T": [7, 8, 9], "T2": [3, 3, 3], "R1": [10, 10, 10], "R2": [11.5, 12, 12.5]},
    "b1": {"T": [3, 3, 3], "T2": [1, 2, 3], "R1": [10, 10, 10], "R2": [12, 12, 12]},
    "b2": {"T": [2, 3, 4], "T2": [2, 2, 2], "R1": [10, 10, 10], "R2": [12, 12, 12]},
    "b3": {"T": [4, 4, 4], "T2": [2, 3, 4], "R1": [10, 10, 10], "R2": [12, 12, 12]},
}
TOY_GROUPS = {"a1": "A", "a2": "A", "a3": "A", "b1": "B", "b2": "B", "b3": "B"}


def toy_curves(log2: dict | None = None, replicates: bool = True) -> pd.DataFrame:
    """A per-well table shaped like ``curves.analyse_study`` output (only the columns used)."""
    rows = []
    well = 0
    for sample, genes in (log2 or TOY_LOG2).items():
        for gene, values in genes.items():
            for value in values if replicates else values[:1]:
                well += 1
                n0 = np.nan if value is None else 2.0**value
                rows.append(("plate1", f"W{well:03d}", sample, "unkn", gene, n0))
    return pd.DataFrame(rows, columns=["run_id", "well", "sample", "sample_type", "target", "n0"])


def toy_inputs(data: pd.DataFrame | None = None, **changes) -> ExportInputs:
    values = {
        "study_id": TOY_STUDY,
        "input_sha256": "c1" * 32,
        "data": toy_curves() if data is None else data,
        "refs": ("R1", "R2"),
        "undetermined": "drop",
        "groups": TOY_GROUPS,
        "group_order": ("A", "B"),
        "genes": ("T", "T2"),
        "headline": ("T", "T2"),
        "chain_head": TOY_CHAIN,
        "design_hash": "d0" * 32,
        "design_note": "toy design",
    }
    values.update(changes)
    return ExportInputs(**values)


@pytest.fixture
def toy() -> ExportInputs:
    return toy_inputs()


@pytest.fixture(scope="session")
def demo_study(tmp_path_factory):
    """(store, study_id) for the demo study in a throwaway studies folder."""
    from qpilot.core.store import StudyStore
    from qpilot.io.datasets import VERMEULEN_FILENAME, default_cache_dir

    path = default_cache_dir() / VERMEULEN_FILENAME
    if not path.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    store = StudyStore(tmp_path_factory.mktemp("prism_studies"))
    return store, store.ensure_study(path)


@pytest.fixture(scope="session")
def demo_inputs(demo_study):
    from qpilot.qpcr.export import demo_inputs as build

    store, study_id = demo_study
    return build(store, study_id)


@pytest.fixture(scope="session")
def demo_export(demo_study, tmp_path_factory):
    """The demo exported once (headline genes, two_groups_log2, macOS paths fixed)."""
    from qpilot.prism import export_study

    store, study_id = demo_study
    out = tmp_path_factory.mktemp("prism_export") / "bundle"
    return export_study(
        store, study_id, out, platform="macos", prism_dir="/Users/lab/qpilot_demo_export"
    )
