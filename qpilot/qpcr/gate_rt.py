"""G-RT: the spread between reverse-transcription replicates of one biological unit.

Reverse transcription is one of the largest technical variance sources in RT-qPCR, and it is
almost never measured: it needs the same RNA reverse-transcribed more than once. When a sample
sheet annotates that (``SampleDesign.rt_replicate``: samples of one ``biological_unit`` with
different labels were reverse-transcribed separately), this rule measures it.

For every biological unit × target with at least two annotated RT replicates:

1. the Cq of each RT replicate is the mean Cq of its usable study wells (technical replicates
   are averaged first; undetermined wells and wells a person excluded are left out);
2. the range is the largest minus the smallest RT-replicate Cq, over the RT replicates that
   have a Cq;
3. a range below :data:`RT_RANGE_LIMIT` (one cycle) passes; a range at or above it warns.

The line is ``not_applicable`` when no RT replicates are annotated ("no RT replicates
annotated"; the Evidence Ledger then says "RT variability not measured"), or when no unit ×
target has two RT replicates with a Cq. A warning is a reported check: it never changes a
conclusion or a confidence grade. Pricing it through the Run Gate's consequence test is for
the Gate (add_plan 3.2), which does not exist yet.

**Source of the criterion** (:data:`SOURCE`). The one-cycle line is the RT-replicate ΔCq < 1
criterion of Bustin et al. (Clin Chem, published online in 2014), as quoted in the repository's
research notes. The paper states it as a criterion for choosing a reverse transcriptase; G-RT
applies the same line to each biological unit × target. It is to be checked against the paper
before it is cited anywhere (SOLVABLE-ERRORS-PLAN §7, fact 3).

The Cq is the engine's (LinRegPCR's TD0), as in the per-well table. Deterministic: no model
call and no network.
"""

from __future__ import annotations

import math
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel

from qpilot.qpcr.designs import design_curves
from qpilot.qpcr.quant import EXCLUDED
from qpilot.schemas import Fact
from qpilot.schemas_studio import StudyDesign

RULE_ID = "G-RT"
RT_RANGE_LIMIT = 1.0  # cycles; Bustin et al. 2014 as quoted in the research notes (to verify)
CRITERION = "RT-replicate ΔCq range < 1 cycle"
SOURCE: dict[str, str] = {
    "citation": (
        "Bustin S, Dhillon HS, Kirvell S, et al. Variability of the reverse transcription "
        "step: practical implications. Clin Chem 2015;61(1) (published online 2014). "
        "doi:10.1373/clinchem.2014.230615"
    ),
    "quoted_from": (
        "research_notes/qPilot niche discovery and features/04-preanalytics-qc-gates.md "
        "(the RT-replicate ΔCq < 1 criterion, 'directly checkable from Cq tables when "
        "replicates are annotated')"
    ),
    "status": "to verify against the paper (SOLVABLE-ERRORS-PLAN §7, fact 3)",
    "scope_note": (
        "the paper gives ΔCq < 1 as a criterion for choosing a reverse transcriptase; G-RT "
        "applies the same line to each biological unit x target"
    ),
}
RANGE_COLUMNS = ("unit", "target", "n_rt", "n_measured", "cq_min", "cq_max", "range")
_DECIMALS = 10  # ranges are rounded before the comparison, so float noise cannot flip a line

METHOD_CARD: dict[str, Any] = {
    "id": "g_rt",
    "version": "1",
    "title": "G-RT: RT-replicate Cq range per biological unit and target",
    "source": SOURCE["citation"],
    "implementation": "qpilot/qpcr/gate_rt.py",
    "inputs": [
        "per-well table: run_id, well, sample, sample_type, target, cq",
        "StudyDesign.samples: biological_unit, rt_replicate",
    ],
    "outputs": ["one GateLine (rule G-RT): pass, warn or not_applicable, with its facts"],
    "acceptance_tests": [
        "tests/engine/test_gate_rt.py::test_ranges_within_the_limit_pass",
        "tests/engine/test_gate_rt.py::test_a_range_at_the_limit_warns",
        "tests/engine/test_gate_rt.py::test_no_annotation_is_not_applicable",
        "tests/engine/test_gate_rt.py::test_demo_is_not_applicable",
    ],
    "licence": "Apache-2.0",
    "card": "methods/evidence.md",
}


class GateLine(BaseModel):
    """One rule's verdict on a study, in the Run Gate's line shape (BUILD-DESIGN §2.3).

    The same fields as ``qpilot.qpcr.gate_instr.GateLine`` (built separately), so the two can
    be merged into one class. A line is a reported check: it never changes a conclusion.
    """

    rule_id: str
    status: Literal["pass", "info", "warn", "not_applicable"]
    code: str
    facts: dict[str, Fact]
    cycles: list[int] = []


def rt_labels(design: StudyDesign | None) -> dict[str, tuple[str, str]]:
    """Sample -> (biological unit, RT replicate label), for the samples that carry a label."""
    if design is None:
        return {}
    return {s: (d.unit(), d.rt_replicate) for s, d in design.samples.items() if d.rt_replicate}


def rt_replicate_range(curves: pd.DataFrame, design: StudyDesign | None) -> pd.DataFrame:
    """The RT-replicate Cq range of every biological unit × target with two or more RT labels.

    Args:
        curves: The per-well table (``run_id, well, sample, sample_type, target, cq``); the
            design's well-level choices are applied here (re-typed and excluded wells).
        design: The confirmed design; ``None`` or no ``rt_replicate`` labels give no rows.

    Returns:
        One row per unit × target, sorted by unit then target, with the columns
        :data:`RANGE_COLUMNS`: ``n_rt`` RT replicates with study wells for that target,
        ``n_measured`` of them with a Cq, the smallest and largest RT-replicate Cq, and
        ``range`` (NaN when fewer than two RT replicates have a Cq).

    Raises:
        DesignError: The design names wells that are not in the table.
    """
    labels = rt_labels(design)
    if not labels:
        return pd.DataFrame(columns=list(RANGE_COLUMNS))
    table = design_curves(curves, design)
    wells = table[(table["sample_type"] == "unkn") & table["sample"].isin(labels)]
    if EXCLUDED in wells.columns:
        wells = wells[~wells[EXCLUDED].astype(bool)]
    if wells.empty:
        return pd.DataFrame(columns=list(RANGE_COLUMNS))
    frame = pd.DataFrame(
        {
            "unit": wells["sample"].map(lambda s: labels[s][0]).astype(str),
            "rt": wells["sample"].map(lambda s: labels[s][1]).astype(str),
            "target": wells["target"].astype(str),
            "cq": pd.to_numeric(wells["cq"], errors="coerce").astype(float),
        }
    )
    per_rt = frame.groupby(["unit", "target", "rt"], sort=True)["cq"].mean()
    grouped = per_rt.groupby(level=["unit", "target"], sort=True)
    out = pd.DataFrame(
        {
            "n_rt": grouped.size(),
            "n_measured": grouped.count(),
            "cq_min": grouped.min(),
            "cq_max": grouped.max(),
        }
    ).reset_index()
    out = out[out["n_rt"] >= 2].reset_index(drop=True)
    spread = (out["cq_max"] - out["cq_min"]).round(_DECIMALS)
    out["range"] = spread.where(out["n_measured"] >= 2)
    out[["n_rt", "n_measured"]] = out[["n_rt", "n_measured"]].astype(int)
    return out[list(RANGE_COLUMNS)]


def g_rt(
    curves: pd.DataFrame,
    design: StudyDesign | None,
    *,
    limit_cycles: float = RT_RANGE_LIMIT,
) -> GateLine:
    """Rule G-RT on a study: RT-replicate ΔCq range below ``limit_cycles`` for every unit × target.

    Args:
        curves: The per-well table (see :func:`rt_replicate_range`).
        design: The confirmed design carrying ``rt_replicate`` labels, or ``None``.
        limit_cycles: The criterion; one cycle (:data:`RT_RANGE_LIMIT`).

    Returns:
        A :class:`GateLine` with ``rule_id`` ``"G-RT"``. Codes: ``rt_not_annotated`` and
        ``rt_not_measurable`` (``not_applicable``), ``rt_within_limit`` (``pass``),
        ``rt_over_limit`` (``warn``). Facts ``f_grt_*``: the limit, units with RT replicates,
        unit × target pairs measured and over the limit, the largest range and where it is.

    Raises:
        ValueError: ``limit_cycles`` is not a positive finite number.
        DesignError: The design names wells that are not in the table.
    """
    if not (isinstance(limit_cycles, int | float) and math.isfinite(limit_cycles)):
        raise ValueError("limit_cycles must be a finite number of cycles")
    if limit_cycles <= 0:
        raise ValueError("limit_cycles must be above zero")
    ranges = rt_replicate_range(curves, design)
    facts: dict[str, Fact] = {}

    def add(field: str, value: float | int | str, fmt: str = "{}", unit: str = "") -> None:
        fid = f"f_grt_{field}"
        facts[fid] = Fact(id=fid, value=value, fmt=fmt, unit=unit, path=f"gate.{RULE_ID}.{field}")

    add("limit", float(limit_cycles), "{:g}", " cycle" if limit_cycles == 1 else " cycles")
    n_units = int(ranges["unit"].nunique())
    add("n_units", n_units)
    if n_units == 0:
        return GateLine(rule_id=RULE_ID, status="not_applicable", code="rt_not_annotated",
                        facts=facts)  # fmt: skip
    measured = ranges.dropna(subset=["range"])
    add("n_pairs", len(measured))
    if measured.empty:
        return GateLine(rule_id=RULE_ID, status="not_applicable", code="rt_not_measurable",
                        facts=facts)  # fmt: skip
    over = measured[measured["range"] >= limit_cycles]
    worst = measured.sort_values(["range", "unit", "target"], ascending=[False, True, True])
    top = worst.iloc[0]
    add("n_over", len(over))
    add("max_range", float(top["range"]), "{:.2f}", " cycles")
    add("worst_unit", str(top["unit"]))
    add("worst_target", str(top["target"]))
    if over.empty:
        return GateLine(rule_id=RULE_ID, status="pass", code="rt_within_limit", facts=facts)
    return GateLine(rule_id=RULE_ID, status="warn", code="rt_over_limit", facts=facts)
