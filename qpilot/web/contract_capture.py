"""Response models of an instrument-export import: what qPilot read and what it means.

Built by :mod:`qpilot.web.intake` from the import's :class:`~qpilot.io.connectors.CaptureMeta`
(``capture.json`` in the session folder). Blind-safe: counts, the person's own file names,
plate shapes, targets, dyes and declared sample types; never a sample name (those stay in the
quarantine), a Cq value or a group.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CaptureSource(BaseModel):
    """One file qPilot read, by the name it had on the person's computer."""

    name: str
    role: str = Field(description="amplification, cq, melt, setup, plate (all in one) or ignored")
    bytes: int


class CapturePlate(BaseModel):
    """What was read for one plate (one RDML run)."""

    run_id: str
    rows: int
    columns: int
    n_wells: int
    n_reactions: int
    n_cycles: int = Field(description="Cycles per amplification curve (0: no curves).")
    targets: list[str]
    dyes: list[str]
    sample_types: dict[str, int] = Field(description="Wells per declared RDML sample type.")
    n_unmapped_types: int = Field(
        description="Wells whose vendor sample type qPilot does not know (treated as unknowns)."
    )
    n_with_vendor_cq: int
    vendor_omitted: list[str] = Field(
        description="Wells the vendor software marked omitted: recorded, never applied."
    )
    value_kind: str
    verdict: str = Field(description="This plate's raw-ness verdict.")


class CaptureRawness(BaseModel):
    """Were the curves processed before export, and what that means for the analysis."""

    verdict: str = Field(
        description="raw | normalized | baseline_subtracted | scaled | cq_only | unknown"
    )
    title: str
    meaning: str
    linregpcr_ok: bool = Field(description="The curves suit LinRegPCR's per-well efficiency.")
    import_trust: bool = Field(
        default=False,
        description="The verdict calls for the Import Trust card: a person decides on Results, "
        "once the blind is lifted, what it means for the analysis.",
    )


class CaptureNote(BaseModel):
    """A warning from the import, in qPilot's words (never file text)."""

    code: str
    message: str


class CaptureSummary(BaseModel):
    """An instrument export as qPilot read it into the session's RDML file."""

    connector: str
    label: str = Field(description="The export family, e.g. 'Bio-Rad CFX Manager / Maestro'.")
    dialect: str
    sources: list[CaptureSource]
    unused: list[str] = Field(
        default=[], description="Files dropped with the export that qPilot did not read."
    )
    value_kind: str
    value_words: str
    layers: dict[str, bool]
    plates: list[CapturePlate]
    rawness: CaptureRawness
    warnings: list[CaptureNote]
    n_quarantined: int = Field(description="Free-text values kept in quarantine.")
