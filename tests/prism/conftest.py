"""Fixtures for the Prism bridge: a toy study with technical replicates and the demo study."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qpilot.qpcr.designs import design_from_proposals
from qpilot.qpcr.export import ExportInputs
from qpilot.qpcr.study import StudySettings, build_model
from qpilot.schemas import ContrastResult
from qpilot.schemas_studio import (
    Comparison,
    MadeBy,
    Proposal,
    SampleDesign,
    StudyDesign,
)

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


def toy_design(groups=TOY_GROUPS, units=None, order=("A", "B")) -> StudyDesign:
    """The toy as a confirmed design: groups from the samples, R1 and R2 as control genes."""
    return StudyDesign(
        design_id="toy",
        mode="groups",
        comparison=Comparison(group_a=order[0], group_b=order[1]),
        samples={
            s: SampleDesign(sample=s, group=g, biological_unit=(units or {}).get(s))
            for s, g in groups.items()
        },
        reference_candidates=("R1", "R2"),
        headline=("T", "T2"),
    )


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
    order = values["group_order"]
    if "design" not in changes and set(order) <= set(values["groups"].values()):
        values["design"] = toy_design(values["groups"], values.get("units"), order)
    values.setdefault("curves", values["data"])  # the toy's wells are the curve analysis
    return ExportInputs(**values)


def engine_inputs(curves: pd.DataFrame, design: StudyDesign, undetermined="drop") -> ExportInputs:
    """Inputs built the way ``study_inputs`` builds them, from a per-well table and a design."""
    model = build_model(curves, StudySettings.from_design(design))
    data, units = model.inputs.primary_table, model.inputs.units or {}
    samples = sorted(set(data.loc[data["sample_type"] == "unkn", "sample"]))
    order = tuple(model.labels)
    groups = {
        **{s: order[0] for s in samples if units.get(s, s) in model.high},
        **{s: order[1] for s in samples if units.get(s, s) in model.rest},
    }
    return ExportInputs(
        study_id=TOY_STUDY,
        input_sha256="cd" * 32,
        data=data,
        refs=tuple(model.space.primary["refs"]),
        undetermined=undetermined,
        groups=groups,
        group_order=order,
        units=model.inputs.units,
        genes=tuple(model.space.items),
        chain_head=TOY_CHAIN,
        design=design,
        curves=curves,
    )


def accepted_exclusion(
    gene: str, unit: str, well_rep: int = 0, well: str | None = None
) -> Proposal:
    """A ``prism.exclusion_reason`` as a person accepted it (a replicate names its exact well)."""
    payload = {"gene": gene, "sample": unit, "action": "exclude", "well_rep": well_rep}
    if well is not None:
        payload["well"] = well
    return Proposal(
        id=f"accepted-{gene}-{unit}-{well_rep}",
        study_id="session",
        kind="prism.exclusion_reason",
        subject=f"{gene}/{unit}",
        payload=payload,
        made_by=MadeBy(kind="rule"),
        status="accepted",
        decided_by="human",
        reason="failed extraction",
    )


def after_acceptance(design, curves, exclusions, cell) -> dict[str, ContrastResult]:
    """The engine's results once a person accepted these exclusions (as Studio applies them)."""
    accepted = [accepted_exclusion(*exclusion) for exclusion in exclusions]
    design = design_from_proposals(design, accepted, curves)
    return build_model(curves, StudySettings.from_design(design)).space.evaluate(cell)


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
