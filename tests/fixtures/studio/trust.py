"""A Studio session of the mini file as if opened from an instrument export (Import Trust tests).

The mini file (:mod:`tests.fixtures.studio.studio_mini`) is written with the instrument's Cq
values (``<cq>``) and a clear knock-out effect on ``1-Mar`` (six cycles later than the
wild type), so its gene is graded Moderate before any cap: the Cq-only cap (Low) then lowers
it. What the import was read as (``capture.json``) is written beside the session the way
``qpilot.web.intake.save`` writes it after an export is opened, with the verdict a test asks for.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from qpilot.io.connectors.base import CaptureMeta, ConnectorInfo, Layers, PlateMeta
from tests.fixtures.studio import studio_mini

#: Knock-out crossings six cycles after the wild type's on 1-Mar (WT 25.0-25.3).
STRONG_KO = {"KO_1": [31.0, 31.1, 30.9], "KO_2": [31.2, 31.3, 31.4]}


#: Wells with an instrument Cq per plate: all but the flat ones (water and NTC; one NTC on 1-Mar).
N_CQ = {"GAPDH": 24, "1-Mar": 25}


def capture_meta(
    verdict: str = "baseline_subtracted", *, instrument_cq: bool = True
) -> CaptureMeta:
    """What a CFX export of the mini file would be read as, with this raw-ness verdict."""
    plates = [
        PlateMeta(
            run_id=f"{target}_plate",
            rows=8,
            columns=12,
            n_wells=30,
            n_reactions=30,
            n_cycles=studio_mini.CYCLES,
            targets=[target],
            dyes=["SYBR"],
            sample_types={"unkn": 27, "ntc": 3},
            n_with_vendor_cq=N_CQ[target] if instrument_cq else 0,
            value_kind="RFU",
        )
        for target in studio_mini.TARGETS
    ]
    return CaptureMeta(
        connector=ConnectorInfo(id="cfx", version="1", label="Bio-Rad CFX Manager / Maestro"),
        dialect="cfx.csv.amplification+cq",
        sources=[],
        experiment_id="mini_set",
        layers=Layers(amplification=True, cq=True, sample_types=True, targets=True),
        value_kind="RFU",
        plates=plates,
        rawness={
            "method": "qpilot.rawness/1",
            "study_verdict": verdict,
            "plate_verdicts": {p.run_id: verdict for p in plates},
            "linregpcr_ok": verdict in ("raw", "normalized"),
        },
    )


def write_trusted_mini(root: Path, *, instrument_cq: bool = True) -> Path:
    """The mini file with the strong knock-out effect (and the instrument's Cq values)."""
    with pytest.MonkeyPatch.context() as mp:
        for sample, crossings in STRONG_KO.items():
            mp.setitem(studio_mini.PLATES["1-Mar"], sample, crossings)
        return studio_mini.write_studio_mini(root / "mini.rdml", instrument_cq=instrument_cq)


def walk_trusted(
    studio: Any, rdml: Path, verdict: str = "baseline_subtracted", *, instrument_cq: bool = True
) -> tuple[str, str]:
    """Walk the file through Studio with ``capture.json`` saying ``verdict``; analyse it."""
    from qpilot.web import intake
    from tests.web.conftest import walk_mini

    sid, _ = walk_mini(studio, rdml)
    intake.save(studio.store, sid, capture_meta(verdict, instrument_cq=instrument_cq), [])
    return sid, studio.study(sid)
