"""Response models of the Spreadsheet Check routes (``routers/sheets.py``).

The engine is :mod:`qpilot.qpcr.sheetcheck` (origin/main's ``qpilot check sheet`` and MCP's
``qpcr_check_sheet``): a lab's own ΔΔCq sheet recomputed from its own Cq values, the first step
that differs and the known slip that reproduces it. The sheet is read, never edited; its column
mapping is a guess until a person confirms it on the page. Sheet labels (sample and group names)
never come back: rows and columns are named by position, groups by order.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from qpilot.web.contract import FactText

SheetRole = Literal[
    "sample",
    "group",
    "bio_unit",
    "gene",
    "type",
    "well",
    "cq",
    "mean_cq",
    "dcq",
    "ddcq",
    "fc",
    "mean_fc",
    "sd",
    "sem",
    "p",
    "ignored",
]


class SheetUploaded(BaseModel):
    """``POST /sheets``: the sheet is kept (by content) for checking; nothing is checked yet."""

    sheet_id: str = Field(description="The kept file's content id (24 hex characters).")
    name: str = Field(description="The file's name on your computer (shown, never opened).")
    bytes: int


class SheetColumnView(BaseModel):
    """One column and what it is taken to hold."""

    column: str = Field(description="The column letter (A, B, …).")
    role: SheetRole
    role_word: str
    gene: str | None = None
    scale: str | None = None
    basis: Literal["header", "content", "user"] = Field(
        description="Where the guess came from; 'user' when a person set it."
    )
    confidence: float


class SheetRoleView(BaseModel):
    """A role a person can give a column."""

    id: SheetRole
    word: str


class SheetMappingView(BaseModel):
    """How the sheet is read: a guess until a person confirms it."""

    status: str = Field(description="'mapping guessed, not confirmed' or 'mapping confirmed'.")
    confirmed: bool
    sheet: int
    header_row: int
    layout: Literal["wide", "long"]
    columns: list[SheetColumnView]
    references: list[str]
    roles: list[SheetRoleView]


class SheetColumnCheckView(BaseModel):
    """One recomputed output column for one gene."""

    column: str
    step: str
    step_word: str
    gene: str | None
    status: Literal["reproduced", "follows", "differs", "not_checked"]
    n_cells: int
    n_reproduced: int
    n_differ: int


class SheetFindingView(BaseModel):
    """One output that differs on its own, and what reproduces it."""

    id: str
    column: str
    step_word: str
    gene: str | None
    first_row: int
    n_rows: int
    status: Literal["explained", "ambiguous", "unexplained"]
    paths: list[str] = Field(description="The known slips or methods that reproduce it.")


class SheetHandOverView(BaseModel):
    """A gene whose sheet arithmetic reproduces but whose fold change differs from the study's."""

    gene: str
    conclusion_differs: bool
    causes: list[str]
    line: FactText


class SheetGeneView(BaseModel):
    """A gene of the sheet; ``flagged`` when its name looks like a date Excel made from it."""

    key: str
    reference: bool
    flagged: bool
    note: str


class SheetCheckBody(BaseModel):
    """What to check against, and the mapping a person set (all optional)."""

    study_id: str | None = Field(
        None, max_length=64, description="Compare the sheet's fold changes with this study's."
    )
    columns: list[SheetColumnSet] | None = Field(
        None, max_length=200, description="Columns a person set (others keep the guess)."
    )
    references: list[str] | None = Field(None, max_length=20)
    confirm: bool = Field(
        False, description="A person confirms the mapping as shown (with any columns set)."
    )


class SheetColumnSet(BaseModel):
    """One column a person sets."""

    column: str = Field(pattern=r"^[A-Za-z]{1,3}$")
    role: SheetRole
    gene: str | None = Field(None, max_length=100)


class SheetCheckView(BaseModel):
    """``POST /sheets/{id}/check``: the sheet recomputed (read-only; nothing is saved)."""

    sheet_id: str
    name: str
    file_sha256: str
    file_kind: Literal["xlsx", "csv"]
    n_rows: int
    study_id: str | None
    mapping: SheetMappingView
    headline: FactText
    findings_text: FactText
    findings: list[SheetFindingView]
    columns: list[SheetColumnCheckView]
    hand_overs: list[SheetHandOverView]
    genes: list[SheetGeneView]
    counts: dict[str, int]
    notes: list[str]
    never_edited: str
    method_card: str = "methods/sheetcheck.md"


SheetCheckBody.model_rebuild()

__all__ = [
    "SheetCheckBody",
    "SheetCheckView",
    "SheetColumnCheckView",
    "SheetColumnSet",
    "SheetColumnView",
    "SheetFindingView",
    "SheetGeneView",
    "SheetHandOverView",
    "SheetMappingView",
    "SheetRole",
    "SheetRoleView",
    "SheetUploaded",
]
