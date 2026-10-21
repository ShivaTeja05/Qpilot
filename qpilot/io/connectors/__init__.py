"""Connectors: get a real lab's instrument exports into qPilot as RDML.

A connector reads one family of files (RDML; Bio-Rad CFX Manager/Maestro spreadsheets;
QuantStudio/ViiA 7/StepOne/7500 exports; LightCycler 480 text; RDES; a tidy table or a Cq
table) into plates, which :mod:`~qpilot.io.connectors.builder` writes as deterministic RDML, so
the engine reads every format the same way. Engine callers use :func:`materialise`::

    m = materialise(path)                 # RDML input: returned as it is
    run_study(m.rdml_path, settings)      # m.meta: what was captured (CaptureMeta JSON)

Contract: ``agent-bus/contracts/capture-connectors.md``.
"""

from qpilot.io.connectors.base import (
    CaptureError,
    CaptureMeta,
    Connector,
    Detection,
    PlateData,
    Reaction,
)
from qpilot.io.connectors.registry import (
    Capture,
    Materialised,
    capture,
    connectors,
    detect,
    expand,
    get_connector,
    is_capturable,
    materialise,
    write_rdml,
)

__all__ = [
    "Capture",
    "CaptureError",
    "CaptureMeta",
    "Connector",
    "Detection",
    "Materialised",
    "PlateData",
    "Reaction",
    "capture",
    "connectors",
    "detect",
    "expand",
    "get_connector",
    "is_capturable",
    "materialise",
    "write_rdml",
]
