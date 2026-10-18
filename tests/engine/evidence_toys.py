"""Small synthetic studies for the Evidence Ledger, G-RT and Run Review tests (no download).

Six biological units (three per group), each reverse-transcribed twice (samples ``u1a``,
``u1b``, ...), five targets each on its own plate, with an NTC and a three-level standard
series on every plate. The per-well table has every column of ``curves.COLUMN_ORDER``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from qpilot.qpcr.curves import COLUMN_ORDER
from qpilot.qpcr.study import StudySettings, build_model
from qpilot.schemas_studio import Comparison, SampleDesign, StudyDesign

UNITS = {"u1": "A", "u2": "A", "u3": "A", "u4": "B", "u5": "B", "u6": "B"}
BASE = {"u1": 10.0, "u2": 10.6, "u3": 9.4, "u4": 10.3, "u5": 9.7, "u6": 10.1}
TARGETS = ("R1", "R2", "R3", "T1", "T2")
REFS = ("R1", "R2", "R3")
GENE = {"R1": 0.0, "R2": 1.0, "R3": -1.0, "T1": 2.0, "T2": 0.5}
EFFECT = {"T1": {"A": 2.0, "B": 0.0}, "T2": {"A": 0.0, "B": 0.5}}
STANDARDS = {"STD_1": 1.0, "STD_10": 10.0, "STD_100": 100.0}
INPUT = "cd" * 32


def sample_name(unit: str, rt: str) -> str:
    return f"{unit}{rt}"


def toy_table(
    *,
    rt_shift: float = 0.3,
    ref_noise: float = 0.05,
    ntc: bool = True,
    std: bool = True,
    seed: int = 7,
) -> pd.DataFrame:
    """The per-well table; ``rt_shift`` is the log2 (≈ Cq) offset of RT replicate ``b``."""
    rng = np.random.default_rng(seed)
    rows = []
    for plate, target in enumerate(TARGETS):
        run = f"p{plate}"
        well = 0
        for unit, group in UNITS.items():
            for rt, shift in (("a", 0.0), ("b", rt_shift)):
                noise = float(rng.normal(0, ref_noise if target in REFS else 0.05))
                log2 = BASE[unit] + GENE[target] + EFFECT.get(target, {}).get(group, 0.0)
                log2 += shift + noise
                rows.append(_row(run, f"A{well}", sample_name(unit, rt), "unkn", target, log2))
                well += 1
        if ntc:
            rows.append(_row(run, "P1", "water", "ntc", target, None))
        if std:
            for k, (name, copies) in enumerate(STANDARDS.items()):
                rows.append(_row(run, f"P{k + 2}", name, "std", target, float(np.log2(copies))))
    return pd.DataFrame(rows)[list(COLUMN_ORDER)]


def _row(run: str, well: str, sample: str, kind: str, target: str, log2: float | None) -> dict:
    found = log2 is not None
    return {
        "run_id": run,
        "well": well,
        "sample": sample,
        "sample_type": kind,
        "target": target,
        "target_raw": target,
        "target_type": "ref" if target in REFS else "toi",
        "excluded": "",
        "note": "",
        "baseline": 0.5,
        "eff_indiv": 1.95,
        "r2": 0.999,
        "eff_target": 1.95,
        "eff_target_sd": 0.01,
        "cq": 40.0 - log2 if found else float("nan"),
        "n0": 2.0**log2 if found else float("nan"),
        "amplification": found,
        "plateau": found,
    }


def toy_design(*, rt_labels: bool = True, units: dict[str, str] | None = None) -> StudyDesign:
    """A groups design over the toy samples; ``rt_labels`` adds ``rt_replicate`` a/b."""
    samples = {}
    for unit, group in (units or UNITS).items():
        for rt in ("a", "b"):
            name = sample_name(unit, rt)
            samples[name] = SampleDesign(
                sample=name,
                group=group,
                biological_unit=unit,
                rt_replicate=rt if rt_labels else None,
            )
    return StudyDesign(
        design_id="toy_rt",
        mode="groups",
        comparison=Comparison(group_a="A", group_b="B"),
        samples=samples,
        reference_candidates=REFS,
        headline=("T1", "T2"),
    )


LEGACY = StudySettings(
    candidates=REFS, marker="T1", group_var="T1_high", headline=("T2",), experiment_id=None
)


def toy_model(curves: pd.DataFrame, design: StudyDesign | None = None, *, refs=REFS):
    """The study model: from ``design`` (groups), or the legacy marker split when ``None``."""
    if design is None:
        settings = LEGACY if refs == REFS else StudySettings(**{**LEGACY.__dict__,
                                                                "candidates": refs})  # fmt: skip
        return build_model(curves, settings)
    design = design.model_copy(update={"reference_candidates": tuple(refs)})
    return build_model(curves, StudySettings.from_design(design))
