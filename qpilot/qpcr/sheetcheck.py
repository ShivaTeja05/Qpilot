"""Spreadsheet Check: recompute a lab's own ΔΔCq sheet and name the first step that differs.

Most qPCR analyses already exist as a spreadsheet: Cq values, then ΔCq, ΔΔCq, fold changes
and a t test, typed or copied by hand. :func:`check_sheet` reads such a sheet, recomputes every
intermediate column from the sheet's own Cq values and reports, for each column that differs,
the rows where the difference starts and the known path that reproduces it. Step by step:

1. **Read.** ``.xlsx``/``.xlsm`` and ``.csv``/``.tsv``/``.txt`` through
   :func:`qpilot.io.sheets.read_sheet`, with its size caps (5 MB file, 20,000 rows, 200 columns).
   The file is never edited and only its sha256 is recorded. Workbooks are opened by openpyxl in
   data-only mode, so a formula cell gives the value the spreadsheet program cached when it last
   saved the file. A workbook written by a tool that does not calculate (openpyxl, pandas, many
   LIMS exports) holds formulas without cached values; it is refused with a message saying so,
   because no formula is ever evaluated here.
2. **Map.** :func:`guess_mapping` guesses each column's role from its header (sample, group,
   biological unit, gene, well Cq or mean Cq, ΔCq, ΔΔCq, fold change / RQ / 2^-ΔΔCq, group mean
   fold change, SD, SEM, p) with a confidence per guess, and whether the sheet is *wide* (one row
   per sample, one Cq column per gene) or *long* (one row per sample or well and gene). Rows whose
   sample cell says "Mean", "SD", "SEM" or "p" are read as summary rows of the group above them.
   A person confirms the mapping (``ColumnMapping.confirmed``) or passes their own; until then
   every result says :data:`MAPPING_GUESSED`.
3. **Recompute.** :data:`PATHS` is a library of known ways to get from Cq to a fold change. Each
   is a pure function of a :class:`Chain` (one target gene's Cq values, reference Cq values,
   biological units and groups): :func:`livak_per_unit` (the textbook path), and the slips
   :func:`sign_inverted`, :func:`exponent_twice`, :func:`no_reference`, :func:`wrong_reference`,
   :func:`arith_mean_fc`, :func:`stats_on_fc` and :func:`wells_as_n`, plus the method
   :func:`pfaffl` when efficiencies are supplied; :func:`row_shift` is a pure function of a
   column's textbook values.
4. **Localise.** For every column, two comparisons: *end to end* (from the sheet's Cq values) and
   *step by step* (from the sheet's own previous column). A column whose values follow from a
   previous column that already differs is marked ``follows``; the first column (ΔCq → ΔΔCq →
   fold change → statistics) that differs on its own is the place to look, with the first row
   where it starts.
5. **Classify.** Each column that differs on its own gets the paths that reproduce every
   differing cell within the larger of the sheet's displayed precision (half a unit in the last
   decimal shown) and 0.5 % relative: one path is ``explained``, two or more ``ambiguous``, none
   ``unexplained`` with the size of the gap. Gene names go through the gene-symbol gate
   (:func:`qpilot.io.symbols.check_symbol`); names Excel turned into dates are flagged.
6. **Hand over.** When the textbook path reproduces the sheet but qPilot's own answer for the
   same study differs (per-well efficiency, normaliser set, samples), that is a method
   difference, not a slip: it is reported as a :class:`HandOver` pointing to the robustness grid.

Conventions that are not slips: ΔCq written as reference minus target and ΔΔCq written as
control minus sample are accepted when the fold change uses the matching sign; Welch's and
Student's t tests both count as the textbook test; an SD in a summary row is checked on the
scale of the column it sits under. For ``.csv`` files the values are what a program printed
(Excel writes the displayed values), so the rounding of every input is carried through each
step; workbook values are the exact numbers the formulas used, so nothing is carried.

Labels in the sheet (sample and group names, header text, the sheet title) are never copied
into the result: rows and columns are named by position, groups by their order and by the text
id of the cell that names them (:func:`qpilot.schemas_studio.text_id_for`), and genes by a name
that passes the gene-symbol gate or a plain assay-name pattern. Findings expose
``kind == "sheet_check"`` so a card list can show them, but they are not Decision Cards: nothing
in the analysis is decided, there are no options, and the study's cards are never touched.

Not claimed: the check reads one table per sheet; it does not evaluate formulas, read number
formats (the precision a person sees in Excel) or follow cell references; a calibrator taken
from one sample, paired or one-tailed tests and other designs are reported as ``unexplained``
with their gap rather than named. Deterministic; no model call and no network.
"""

from __future__ import annotations

import bisect
import datetime as dt
import json
import math
import re
import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field
from scipy import stats

from qpilot.core.facts import FactRegistry, slug
from qpilot.io.sheets import (
    HEADER_SCAN_ROWS,
    SheetError,
    SheetRead,
    cell_text,
    column_letter,
    header_field,
    read_sheet,
    squash,
)
from qpilot.io.symbols import check_symbol, normalise_assay_name
from qpilot.qpcr.contrast import DEFAULT_RULE, ConclusionRule, conclude
from qpilot.schemas import Conclusion, ContrastResult, Fact, StudyResult

SHEETCHECK_VERSION = "1"
METHOD_CARD_PATH = "methods/sheetcheck.md"
TEMPLATE_KEY = "sheetcheck_v1"
CARD_KIND = "sheet_check"
REL_TOL = 0.005  # 0.5 % relative: the floor of every comparison
FLOAT_FLOOR = 1e-9  # arithmetic noise between two programs adding the same numbers
SIGNIFICANT = 12  # significant digits kept in the result (byte-stable JSON)
MAPPING_GUESSED = "mapping guessed, not confirmed"
MAPPING_CONFIRMED = "mapping confirmed"
EFFICIENCY_MIN, EFFICIENCY_MAX = 1.0, 2.5  # amplification factor per cycle (2.0 = 100 %)
CQ_LIKE = (5.0, 50.0)  # a column of numbers in this range is read as Cq values

METHOD_CARD: dict[str, Any] = {
    "id": "sheetcheck",
    "version": SHEETCHECK_VERSION,
    "title": "Spreadsheet Check: recompute a lab's own ΔΔCq sheet",
    "source": (
        "Livak KJ, Schmittgen TD, Methods 25: 402-408 (2001) for the textbook path; Pfaffl MW, "
        "Nucleic Acids Res 29: e45 (2001) for the efficiency-corrected ratio; the slips are "
        "the practitioner errors catalogued in research_notes (W2 practitioner voice)"
    ),
    "implementation": "qpilot/qpcr/sheetcheck.py",
    "inputs": [
        "a .xlsx or .csv analysis sheet (read-only; only its sha256 is recorded)",
        "an optional ColumnMapping (guessed when absent; confirmed by a person)",
        "optional amplification efficiencies per gene (for the Pfaffl path)",
        "optional engine result for the same study (StudyResult or contrasts)",
    ],
    "outputs": [
        "SheetCheckResult: mapping, per-column checks, findings with the first divergent "
        "column and row, the paths that reproduce each, hand-overs and facts",
    ],
    "acceptance_tests": [
        "tests/engine/test_sheetcheck.py::test_clean_livak_sheet_has_no_findings",
        "tests/engine/test_sheetcheck.py::test_each_wrong_path_is_named_at_its_first_column",
        "tests/engine/test_sheetcheck.py::test_item_64_exponent_twice",
        "tests/engine/test_sheetcheck.py::test_method_only_difference_is_a_hand_over",
        "tests/engine/test_sheetcheck.py::test_output_is_byte_deterministic",
        "tests/engine/test_sheetcheck.py::test_demo_clean_sheet_has_no_findings",
        "tests/engine/test_sheetcheck.py::test_demo_each_wrong_path_is_detected",
    ],
    "licence": "Apache-2.0",
    "card": METHOD_CARD_PATH,
}


class SheetCheckError(ValueError):
    """The sheet cannot be checked (unreadable, too large, formulas without values, no table)."""


Role = Literal[
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
Layout = Literal["wide", "long"]
Scale = Literal["dcq", "ddcq", "fc"]
Status = Literal["reproduced", "explained", "ambiguous", "unexplained"]
FindingStatus = Literal["explained", "ambiguous", "unexplained"]
ColumnStatus = Literal["reproduced", "follows", "differs", "not_checked"]
PathKind = Literal["reference", "slip", "method"]

#: Per-row steps in the order a sheet computes them, then the group statistics.
ROW_STEPS: tuple[str, ...] = ("mean_cq", "dcq", "ddcq", "fc")
GROUP_STEPS: tuple[str, ...] = ("mean_dcq", "mean_ddcq", "mean_fc", "sd", "sem", "p")
STEP_ORDER: tuple[str, ...] = ROW_STEPS + GROUP_STEPS
STEP_LABELS: dict[str, str] = {
    "mean_cq": "mean Cq",
    "dcq": "ΔCq",
    "ddcq": "ΔΔCq",
    "fc": "fold change",
    "mean_dcq": "group mean ΔCq",
    "mean_ddcq": "group mean ΔΔCq",
    "mean_fc": "group mean fold change",
    "sd": "standard deviation",
    "sem": "standard error of the mean",
    "p": "p-value",
}
_SIGNED_STEPS = frozenset({"dcq", "ddcq", "mean_dcq", "mean_ddcq"})  # sign is a convention
_ROW_ROLES = frozenset({"mean_cq", "dcq", "ddcq", "fc"})
_GROUP_ROLES = frozenset({"mean_fc", "sd", "sem", "p"})
_STRUCTURAL = frozenset({"sample", "group", "bio_unit", "gene", "type", "well"})
_ANALYSIS = frozenset({"cq", "mean_cq", "dcq", "ddcq", "fc", "mean_fc", "sd", "sem", "p"})


# ---------------------------------------------------------------------------------------------
# The result
# ---------------------------------------------------------------------------------------------


class ColumnGuess(BaseModel):
    """One column of the sheet and what it is taken to hold.

    ``gene`` is the gene key a wide sheet's column belongs to (``None`` in a long sheet, where
    the gene column says it row by row). ``scale`` says what an SD or SEM column is computed on
    when its header names it. ``confidence`` is the guess's confidence (1.0 for a person's
    mapping); ``basis`` says where the guess came from.
    """

    column: str
    role: Role
    gene: str | None = None
    scale: Scale | None = None
    confidence: float = 1.0
    basis: Literal["header", "content", "user"] = "user"


class ColumnMapping(BaseModel):
    """How to read the sheet: which column holds what, and which group is the control.

    ``sheet`` is the 1-based sheet index and ``header_row`` the 1-based row of the header.
    ``references`` are the declared reference genes (gene keys). The control group is named by
    ``control_group`` (the label as written; input only, never echoed) or by
    ``control_text_id`` (the text id of a cell that names it). Outputs say
    :data:`MAPPING_GUESSED` until ``confirmed`` is True.
    """

    sheet: int = 1
    header_row: int = 1
    layout: Layout = "wide"
    columns: list[ColumnGuess] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
    control_group: str | None = None
    control_text_id: str | None = None
    control_confidence: float = 1.0
    confirmed: bool = False

    @property
    def status(self) -> str:
        """:data:`MAPPING_CONFIRMED` or :data:`MAPPING_GUESSED`."""
        return MAPPING_CONFIRMED if self.confirmed else MAPPING_GUESSED

    def by_role(self, *roles: str) -> list[ColumnGuess]:
        """The columns with one of ``roles``, in column order."""
        return [c for c in self.columns if c.role in roles]


class GroupInfo(BaseModel):
    """A group of the sheet, named by its order and the text id of the cell naming it."""

    index: int
    text_id: str
    control: bool
    n_units: int
    n_rows: int
    first_row: int


class GeneInfo(BaseModel):
    """A gene of the sheet and what the gene-symbol gate says about its name."""

    key: str
    reference: bool
    status: str
    candidates: list[str] = Field(default_factory=list)
    flagged: bool = False
    cell: str
    note: str = ""


class ColumnCheck(BaseModel):
    """One checked output column for one gene: how many of its cells reproduce."""

    column: str
    step: str
    gene: str | None
    status: ColumnStatus
    n_cells: int = 0
    n_reproduced: int = 0
    n_follow: int = 0
    n_differ: int = 0
    n_not_comparable: int = 0
    granularity: Literal["row", "unit", "group"] = "row"
    convention: str | None = None
    variant: str | None = None
    finding: str | None = None
    reason: str | None = None


class Finding(BaseModel):
    """One output that differs from the textbook path on its own, and what reproduces it.

    Card-shaped (``kind`` ``"sheet_check"``, ``rationale_template``, ``facts``) so a card list
    can show it, but not a :class:`~qpilot.schemas.DecisionCard`: nothing is decided.
    """

    id: str
    kind: Literal["sheet_check"] = CARD_KIND
    column: str
    step: str
    gene: str | None
    group: int | None = None
    rows: list[int]
    first_row: int
    onwards: bool
    status: FindingStatus
    paths: list[str] = Field(default_factory=list)
    path_details: dict[str, list[str]] = Field(default_factory=dict)
    path_kinds: dict[str, PathKind] = Field(default_factory=dict)
    user_value: float | None = None
    expected_value: float | None = None
    gap: float | None = None
    gap_relative: float | None = None
    gap_pattern: Literal["constant", "varies"] | None = None
    followed_by: list[str] = Field(default_factory=list)
    rationale_template: str = TEMPLATE_KEY
    facts: list[str] = Field(default_factory=list)


class Localisation(BaseModel):
    """Where one gene's chain first differs: the column, the step and the first row."""

    gene: str | None
    column: str
    step: str
    first_row: int
    onwards: bool
    finding: str


class HandOver(BaseModel):
    """The sheet's arithmetic reproduces, but qPilot's own answer for the study differs.

    Not a slip: a method difference that the robustness grid and the Decision Cards show.
    ``causes`` are what visibly differs: ``efficiency`` (the engine uses each well's
    amplification efficiency, the sheet assumes 2.0), ``normaliser`` (another reference set)
    and ``sample_set`` (other group sizes).
    """

    gene: str
    engine_gene: str
    sheet_fc: float | None
    engine_fc: float | None
    ratio: float | None
    sheet_conclusion: Conclusion | None
    engine_conclusion: Conclusion
    conclusion_differs: bool
    causes: list[Literal["efficiency", "normaliser", "sample_set"]]
    see: list[str]
    facts: list[str] = Field(default_factory=list)


class Summary(BaseModel):
    """The headline: k of n fold changes reproduce; m differ, j of them with a named cause."""

    mapping: str
    n_fold_changes: int
    n_reproduced: int
    n_differ: int
    n_named: int
    n_ambiguous: int
    n_unexplained: int
    n_columns_checked: int
    n_columns_reproduced: int
    n_findings: int
    n_hand_overs: int
    n_symbol_flags: int


class SheetCheckResult(BaseModel):
    """Everything the check found; :meth:`to_json` gives byte-stable JSON.

    The same file (same name, same bytes) and the same arguments always give the same bytes.
    Group and control text ids include the file name, as every quarantined cell's id does
    (:func:`qpilot.schemas_studio.text_id_for`), so a renamed copy differs in those ids only.
    """

    version: str = SHEETCHECK_VERSION
    file_sha256: str
    file_kind: Literal["xlsx", "csv"]
    mapping: ColumnMapping
    mapping_status: str
    layout: Layout
    n_rows: int
    groups: list[GroupInfo]
    genes: list[GeneInfo]
    columns: list[ColumnCheck]
    findings: list[Finding]
    localisation: list[Localisation]
    summary: Summary
    hand_overs: list[HandOver]
    notes: list[str]
    facts: dict[str, Fact]

    def to_json(self) -> str:
        """Deterministic JSON (sorted keys, two-space indent, trailing newline)."""
        data = self.model_dump(mode="json")
        return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------------------------------------
# The path library
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PathInfo:
    """One known way from Cq to a fold change: its id, label, kind and the steps it changes."""

    id: str
    label: str
    kind: PathKind
    steps: tuple[str, ...]


PATHS: dict[str, PathInfo] = {
    "livak_per_unit": PathInfo(
        "livak_per_unit",
        "the textbook Livak path (perfect doubling per cycle, per biological unit, geometric mean)",
        "reference",
        STEP_ORDER,
    ),
    "sign_inverted": PathInfo(
        "sign_inverted",
        "the sign of ΔΔCq inverted in the exponent",
        "slip",
        ("fc", "mean_fc"),
    ),
    "exponent_twice": PathInfo(
        "exponent_twice",
        "the exponent applied twice (a fold change used as an exponent again)",
        "slip",
        ("fc", "mean_fc"),
    ),
    "no_reference": PathInfo(
        "no_reference",
        "no reference gene subtracted (the normalisation step skipped)",
        "slip",
        ("dcq", "ddcq", "fc", "mean_dcq", "mean_ddcq", "mean_fc", "p"),
    ),
    "wrong_reference": PathInfo(
        "wrong_reference",
        "a reference other than the one declared",
        "slip",
        ("dcq", "ddcq", "fc", "mean_dcq", "mean_ddcq", "mean_fc", "p"),
    ),
    "arith_mean_fc": PathInfo(
        "arith_mean_fc",
        "the arithmetic mean of fold changes instead of the geometric mean",
        "slip",
        ("mean_fc",),
    ),
    "stats_on_fc": PathInfo(
        "stats_on_fc",
        "the t test run on linear fold changes instead of on ΔCq",
        "slip",
        ("p",),
    ),
    "wells_as_n": PathInfo(
        "wells_as_n",
        "technical wells counted as biological replicates",
        "slip",
        ("ddcq", "fc", "mean_dcq", "mean_ddcq", "mean_fc", "sd", "sem", "p"),
    ),
    "row_shift": PathInfo(
        "row_shift",
        "values taken from a neighbouring row (a copy-paste offset)",
        "slip",
        ROW_STEPS,
    ),
    "pfaffl": PathInfo(
        "pfaffl",
        "the Pfaffl ratio with the efficiencies given",
        "method",
        ("fc", "mean_fc"),
    ),
}


@dataclass(frozen=True)
class Chain:
    """One gene's Cq inputs in sheet-row order: the input of every path function.

    Attributes:
        gene: Gene key.
        rows: Sheet row of each entry (ascending).
        unit: Biological-unit index of each row (``0`` .. ``m - 1``).
        unit_group: Group index of each unit (1-based; ``0`` for no group).
        control: Group index of the control (calibrator) group; ``0`` when unknown.
        target: ``(n, k)`` Cq of the gene's wells per row (``k`` replicate columns; NaN blank).
        target_h: Rounding (half a unit in the last decimal) carried from the Cq values; 0 for
            workbooks.
        refs: The declared reference genes.
        ref_row: Reference gene -> ``(n,)`` its Cq for each row (the row's own wells in a wide
            sheet, the unit's mean in a long sheet).
        ref_unit: Reference gene -> ``(m,)`` its mean Cq per unit.
        ref_h: Reference gene -> rounding carried from its Cq values.
        all_refs: Every reference gene of the sheet (for :func:`wrong_reference`).
        efficiency: Gene -> amplification factor per cycle (for :func:`pfaffl`).
    """

    gene: str
    rows: tuple[int, ...]
    unit: np.ndarray
    unit_group: np.ndarray
    control: int
    target: np.ndarray
    target_h: float = 0.0
    refs: tuple[str, ...] = ()
    ref_row: Mapping[str, np.ndarray] = field(default_factory=dict)
    ref_unit: Mapping[str, np.ndarray] = field(default_factory=dict)
    ref_h: Mapping[str, float] = field(default_factory=dict)
    all_refs: tuple[str, ...] = ()
    efficiency: Mapping[str, float] = field(default_factory=dict)

    @property
    def n_units(self) -> int:
        """Number of biological units."""
        return len(self.unit_group)

    @property
    def has_replicates(self) -> bool:
        """True when some unit has more than one well of this gene."""
        if self.target.shape[1] > 1:
            return True
        return bool(len(self.unit) and np.bincount(self.unit).max() > 1)


@dataclass(frozen=True)
class Anchor:
    """The sheet's own values for one step, aligned to a chain (for step-by-step checks)."""

    row: np.ndarray
    unit: np.ndarray
    h: float = 0.0


@dataclass(frozen=True)
class Anchors:
    """The sheet's own columns a path computes from, and the sheet's ΔΔCq sign convention.

    ``steps`` maps ``mean_cq``/``dcq``/``ddcq``/``fc`` to the sheet's values; ``ref_mean`` maps a
    reference gene to the sheet's mean Cq for it. ``sign`` is +1 when the sheet writes ΔΔCq as
    sample minus control (the fold change is ``2^-ΔΔCq``), -1 for control minus sample.
    """

    steps: Mapping[str, Anchor] = field(default_factory=dict)
    ref_mean: Mapping[str, Anchor] = field(default_factory=dict)
    sign: int = 1


@dataclass(frozen=True)
class PathValues:
    """What a path computes: every step per row and per unit, and the group statistics.

    ``group`` is keyed ``(step, group index, variant)``: the variant is ``""`` for means,
    ``"dcq"`` or ``"fc"`` for the scale of an SD or SEM, ``"welch"`` or ``"student"`` for a p.
    The ``*_h`` mappings carry the rounding of the inputs through each step.
    """

    row: dict[str, np.ndarray]
    unit: dict[str, np.ndarray]
    row_h: dict[str, np.ndarray]
    unit_h: dict[str, np.ndarray]
    group: dict[tuple[str, int, str], float]
    group_h: dict[tuple[str, int, str], float]


# A path can produce values no sheet shows (the exponent applied twice reaches infinity): the
# arithmetic stays quiet and such a value simply never matches a cell.
_QUIET = {"over": "ignore", "invalid": "ignore", "divide": "ignore"}


def _mean(values: np.ndarray) -> float:
    ok = values[~np.isnan(values)]
    with np.errstate(**_QUIET):
        return float(ok.sum() / len(ok)) if len(ok) else math.nan


def _sd(values: np.ndarray) -> float:
    ok = values[np.isfinite(values)]
    if len(ok) < 2 or len(ok) < int((~np.isnan(values)).sum()):
        return math.nan
    with np.errstate(**_QUIET):
        return float(np.std(ok, ddof=1))


def _geo(values: np.ndarray) -> float:
    ok = values[~np.isnan(values)]
    if not len(ok) or (ok <= 0).any():
        return math.nan
    with np.errstate(**_QUIET):
        return float(2.0 ** (np.log2(ok).sum() / len(ok)))


def _row_mean(values: np.ndarray) -> np.ndarray:
    counts = (~np.isnan(values)).sum(axis=1)
    sums = np.where(np.isnan(values), 0.0, values).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = sums / counts
    out[counts == 0] = np.nan
    return out


def _unit_mean(values: np.ndarray, unit: np.ndarray, m: int, *, log: bool = False) -> np.ndarray:
    """Mean over each unit's entries that have a value (``log``: geometric mean)."""
    v = values.reshape(len(unit), -1)
    sums, counts = np.zeros(m), np.zeros(m)
    for j in range(v.shape[1]):
        col = v[:, j]
        ok = ~np.isnan(col)
        if log:
            ok &= col > 0
            np.add.at(sums, unit[ok], np.log2(col[ok]))
        else:
            np.add.at(sums, unit[ok], col[ok])
        np.add.at(counts, unit[ok], 1)
    with np.errstate(**_QUIET):
        out = sums / counts
        out[counts == 0] = np.nan
        return 2.0**out if log else out


def _p(a: np.ndarray, b: np.ndarray, equal_var: bool) -> float:
    """Two-sided t test p (Welch's or Student's); NaN with fewer than two values a side."""
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    if len(a) < 2 or len(b) < 2 or not (np.isfinite(a).all() and np.isfinite(b).all()):
        return math.nan
    with warnings.catch_warnings(), np.errstate(**_QUIET):
        warnings.simplefilter("ignore")
        p = float(stats.ttest_ind(a, b, equal_var=equal_var).pvalue)
    return p if math.isfinite(p) else math.nan


def _p_h(a: np.ndarray, b: np.ndarray, h: float, equal_var: bool, p: float) -> float:
    """How far rounding of the inputs (``h`` each) can move a p-value (worst mean shift)."""
    if h <= 0 or not math.isfinite(p):
        return 0.0
    up, down = _p(a + h, b - h, equal_var), _p(a - h, b + h, equal_var)
    return max(abs(x - p) for x in (up, down) if math.isfinite(x)) if math.isfinite(up) else 0.0


def _fc(rule: str, x: np.ndarray, s: int) -> np.ndarray:
    """A fold change from ΔΔCq under a path's rule (``s``: the sheet's ΔΔCq sign)."""
    with np.errstate(over="ignore", invalid="ignore"):
        if rule == "inverted":
            return np.exp2(s * x)
        if rule == "exp_pos":
            return np.exp2(np.exp2(-s * x))
        if rule == "exp_neg":
            return np.exp2(-np.exp2(-s * x))
        return np.exp2(-s * x)


def _fc_h(rule: str, x: np.ndarray, h: np.ndarray, s: int) -> np.ndarray:
    base = _fc(rule, x, s)
    with np.errstate(over="ignore", invalid="ignore"):
        spread = np.maximum(np.abs(_fc(rule, x + h, s) - base), np.abs(_fc(rule, x - h, s) - base))
    return np.where(np.isfinite(spread), spread, 0.0)


def _apply(computed: np.ndarray, h: np.ndarray, anchor: np.ndarray | None, anchor_h: float):
    """The sheet's values where it has them, the path's own elsewhere (with their rounding)."""
    if anchor is None:
        return computed, h
    has = ~np.isnan(anchor)
    return np.where(has, anchor, computed), np.where(has, anchor_h, h)


def _normaliser(chain: Chain, anchors: Anchors, refs: tuple[str, ...]):
    n, m = len(chain.rows), chain.n_units
    if not refs:
        return np.zeros(n), np.zeros(m), np.zeros(n), np.zeros(m)
    rows, units, rows_h, units_h = [], [], [], []
    for ref in refs:
        if ref not in chain.ref_row:
            return np.full(n, np.nan), np.full(m, np.nan), np.zeros(n), np.zeros(m)
        h = chain.ref_h.get(ref, 0.0)
        anchor = anchors.ref_mean.get(ref)
        r, rh = _apply(
            chain.ref_row[ref],
            np.full(n, h),
            anchor.row if anchor else None,
            anchor.h if anchor else 0.0,
        )
        u, uh = _apply(
            chain.ref_unit[ref],
            np.full(m, h),
            anchor.unit if anchor else None,
            anchor.h if anchor else 0.0,
        )
        rows.append(r), units.append(u), rows_h.append(rh), units_h.append(uh)
    return (
        np.vstack(rows).mean(axis=0),
        np.vstack(units).mean(axis=0),
        np.vstack(rows_h).max(axis=0),
        np.vstack(units_h).max(axis=0),
    )


def _pfaffl_ratio(chain: Chain, anchors: Anchors, refs, c_row, c_unit):
    """Pfaffl's ratio per row and per unit; NaN when the gene's efficiency is not given."""
    n, m = len(chain.rows), chain.n_units
    e_target = chain.efficiency.get(chain.gene)
    ctrl = chain.unit_group == chain.control
    if e_target is None or not ctrl.any():
        return np.full(n, np.nan), np.full(m, np.nan)
    base = _mean(c_unit[ctrl])
    num_row, num_unit = e_target ** (base - c_row), e_target ** (base - c_unit)
    if not refs:
        return num_row, num_unit
    logs_row, logs_unit = [], []
    for ref in refs:
        if ref not in chain.ref_row:
            return np.full(n, np.nan), np.full(m, np.nan)
        e_ref = chain.efficiency.get(ref, 2.0)
        anchor = anchors.ref_mean.get(ref)
        r_row = _apply(chain.ref_row[ref], np.zeros(n), anchor.row if anchor else None, 0.0)[0]
        r_unit = _apply(chain.ref_unit[ref], np.zeros(m), anchor.unit if anchor else None, 0.0)[0]
        q = _mean(r_unit[ctrl])
        logs_row.append((q - r_row) * math.log2(e_ref))
        logs_unit.append((q - r_unit) * math.log2(e_ref))
    return (
        num_row / np.exp2(np.vstack(logs_row).mean(axis=0)),
        num_unit / np.exp2(np.vstack(logs_unit).mean(axis=0)),
    )


def _compose(
    chain: Chain,
    anchors: Anchors | None = None,
    *,
    refs: tuple[str, ...] | None = None,
    fc_rule: str = "livak",
    mean_rule: str = "geometric",
    stats_on: str = "dcq",
    wells: bool = False,
) -> PathValues:
    """Compute every step of one path, anchoring each step on the sheet's previous column.

    With ``anchors`` empty this is the path end to end from the Cq values; with the sheet's
    columns as anchors, each step's output is what this path's step gives from the sheet's own
    previous column (step by step).
    """
    with np.errstate(**_QUIET):
        return _steps(chain, anchors, refs, fc_rule, mean_rule, stats_on, wells)


def _steps(chain, anchors, refs, fc_rule, mean_rule, stats_on, wells) -> PathValues:
    a = anchors if anchors is not None else Anchors()
    s = a.sign
    n, m = len(chain.rows), chain.n_units
    unit, ugroup = chain.unit, chain.unit_group
    row: dict[str, np.ndarray] = {}
    per_unit: dict[str, np.ndarray] = {}
    row_h: dict[str, np.ndarray] = {}
    unit_h: dict[str, np.ndarray] = {}

    def put(step, r, u, rh, uh):
        row[step], per_unit[step], row_h[step], unit_h[step] = r, u, rh, uh

    def anchored(step, r, u, rh, uh):
        anchor = a.steps.get(step)
        if anchor is None:
            return r, u, rh, uh
        r2, rh2 = _apply(r, rh, anchor.row, anchor.h)
        u2, uh2 = _apply(u, uh, anchor.unit, anchor.h)
        return r2, u2, rh2, uh2

    # mean Cq of the gene
    t_unit = _unit_mean(chain.target, unit, m)
    th = chain.target_h
    put("mean_cq", t_unit[unit], t_unit, np.full(n, th), np.full(m, th))
    c_row, c_unit, c_rh, c_uh = anchored(
        "mean_cq", _row_mean(chain.target), t_unit, np.full(n, th), np.full(m, th)
    )
    # ΔCq
    use = chain.refs if refs is None else tuple(refs)
    nf_row, nf_unit, nf_rh, nf_uh = _normaliser(chain, a, use)
    put("dcq", c_row - nf_row, c_unit - nf_unit, c_rh + nf_rh, c_uh + nf_uh)
    d_row, d_unit, d_rh, d_uh = anchored(
        "dcq", c_row - nf_row, c_unit - nf_unit, c_rh + nf_rh, c_uh + nf_uh
    )
    # well-level values, for technical wells counted as n: each replicate Cq column's well
    # when the sheet shows no per-row step of its own, else each row
    w_group = ugroup[unit] if m else np.zeros(0, dtype=int)
    w_d = d_row
    expanded = wells and not any(step in a.steps for step in ROW_STEPS)
    if expanded:
        w_d = (chain.target - nf_row[:, None]).ravel()
        w_group = np.repeat(ugroup[unit], chain.target.shape[1])
    ctrl = ugroup == chain.control
    if wells:
        k = _mean(w_d[w_group == chain.control]) if chain.control else math.nan
    else:
        k = _mean(d_unit[ctrl]) if chain.control else math.nan
    k_h = float(np.max(d_uh[ctrl])) if ctrl.any() else 0.0
    # ΔΔCq
    put("ddcq", d_row - k, d_unit - k, d_rh + k_h, d_uh + k_h)
    dd_row, dd_unit, dd_rh, dd_uh = anchored("ddcq", d_row - k, d_unit - k, d_rh + k_h, d_uh + k_h)
    w_dd = w_d - k if expanded else dd_row
    # fold change
    if fc_rule == "pfaffl":
        f_row, f_unit = _pfaffl_ratio(chain, a, use, c_row, c_unit)
        rel = np.exp2(2 * (c_rh + nf_rh) * math.log2(EFFICIENCY_MAX)) - 1
        f_rh = np.abs(f_row) * rel
        f_uh = np.abs(f_unit) * (np.exp2(2 * (c_uh + nf_uh) * math.log2(EFFICIENCY_MAX)) - 1)
    else:
        f_row, f_unit = _fc(fc_rule, dd_row, s), _fc(fc_rule, dd_unit, s)
        f_rh, f_uh = _fc_h(fc_rule, dd_row, dd_rh, s), _fc_h(fc_rule, dd_unit, dd_uh, s)
    put("fc", f_row, f_unit, f_rh, f_uh)
    fc_anchored = "fc" in a.steps
    F_row, F_unit, F_rh, F_uh = anchored("fc", f_row, f_unit, f_rh, f_uh)
    w_f = _fc(fc_rule, w_dd, s) if expanded and fc_rule != "pfaffl" else F_row
    if expanded and fc_rule == "pfaffl":
        w_f = np.repeat(F_row, chain.target.shape[1])
    # group statistics
    group: dict[tuple[str, int, str], float] = {}
    group_h: dict[tuple[str, int, str], float] = {}
    rel_f = np.where(F_unit > 0, F_uh / np.where(F_unit > 0, F_unit, 1), 0.0)
    groups = sorted({int(g) for g in ugroup if g > 0})
    for g in groups:
        sel = ugroup == g
        if wells:
            wsel = w_group == g
            vd, vdd = w_d[wsel], w_dd[wsel]
            vf = w_f[wsel]
            hd = float(np.max(d_rh)) if len(d_rh) else 0.0
            hdd = float(np.max(dd_rh)) if len(dd_rh) else 0.0
        else:
            vd, vdd, vf = d_unit[sel], dd_unit[sel], F_unit[sel]
            hd = float(np.max(d_uh[sel])) if sel.any() else 0.0
            hdd = float(np.max(dd_uh[sel])) if sel.any() else 0.0
        group[("mean_dcq", g, "")], group_h[("mean_dcq", g, "")] = _mean(vd), hd
        group[("mean_ddcq", g, "")], group_h[("mean_ddcq", g, "")] = _mean(vdd), hdd
        if mean_rule == "arithmetic":
            mean_fc = _mean(vf)
        elif mean_rule in ("exp_pos", "exp_neg") and fc_anchored:
            sign = 1.0 if mean_rule == "exp_pos" else -1.0
            with np.errstate(over="ignore"):
                mean_fc = float(np.exp2(sign * _geo(vf)))
        else:
            mean_fc = _geo(vf)
        rel_max = float(np.nanmax(rel_f[sel])) if sel.any() and np.isfinite(rel_f[sel]).any() else 0
        group[("mean_fc", g, "")] = mean_fc
        group_h[("mean_fc", g, "")] = abs(mean_fc) * rel_max if math.isfinite(mean_fc) else 0.0
        n_vals = int((~np.isnan(vd)).sum())
        # SD and the t test do not move when every value shifts by one number, so they are
        # taken on ΔΔCq: the sheet's own ΔΔCq column when it has one, else ΔCq minus the
        # calibrator.
        for scale, vals, h in (("dcq", vdd, hdd), ("fc", vf, float(np.max(F_uh[sel], initial=0)))):
            sd = _sd(vals)
            group[("sd", g, scale)], group_h[("sd", g, scale)] = sd, math.sqrt(2) * h
            n_s = int((~np.isnan(vals)).sum()) if scale == "fc" else n_vals
            sem = sd / math.sqrt(n_s) if n_s else math.nan
            group[("sem", g, scale)] = sem
            group_h[("sem", g, scale)] = math.sqrt(2) * h / math.sqrt(n_s) if n_s else 0.0
        if chain.control and g != chain.control:
            if wells:
                cs = w_group == chain.control
                ca, cb = (w_dd[wsel], w_dd[cs]) if stats_on == "dcq" else (vf, w_f[cs])
            else:
                ca, cb = (dd_unit[sel], dd_unit[ctrl]) if stats_on == "dcq" else (vf, F_unit[ctrl])
            h_in = hdd if stats_on == "dcq" else 0.0
            for variant, equal in (("welch", False), ("student", True)):
                p = _p(ca, cb, equal)
                group[("p", g, variant)] = p
                group_h[("p", g, variant)] = _p_h(ca, cb, h_in, equal, p)
    return PathValues(row, per_unit, row_h, unit_h, group, group_h)


def livak_per_unit(chain: Chain, anchors: Anchors | None = None) -> PathValues:
    """The textbook path (Livak and Schmittgen 2001), per biological unit.

    Efficiency 2.0. Technical wells are averaged per unit first (mean Cq, the geometric mean of
    the quantities); ΔCq = Cq(gene) - mean Cq of the declared references; the calibrator is
    the mean ΔCq of the control group's units; fold change = 2^-ΔΔCq; a group's fold change is
    the geometric mean of its units' fold changes (the arithmetic mean on the log scale); SD
    and the t test are on ΔCq per unit (Welch's and Student's both count).
    """
    return _compose(chain, anchors)


def sign_inverted(chain: Chain, anchors: Anchors | None = None) -> PathValues:
    """The fold change computed as 2^+ΔΔCq (the sign of the exponent inverted)."""
    return _compose(chain, anchors, fc_rule="inverted")


def exponent_twice(
    chain: Chain, anchors: Anchors | None = None, *, negative: bool = False
) -> PathValues:
    """A fold change raised to a power of two again (2^FC, or 2^-FC with ``negative``).

    The item-64 pattern: a fold change of ten read as "2^10 more mRNA". When the sheet's own
    fold-change column is right, the group mean is 2^(geometric mean of the fold changes).
    """
    rule = "exp_neg" if negative else "exp_pos"
    return _compose(chain, anchors, fc_rule=rule, mean_rule=rule)


def no_reference(chain: Chain, anchors: Anchors | None = None) -> PathValues:
    """No reference subtracted: ΔCq is the gene's own Cq (normalisation skipped)."""
    return _compose(chain, anchors, refs=())


def wrong_reference(
    chain: Chain, anchors: Anchors | None = None, *, refs: Sequence[str]
) -> PathValues:
    """A reference set other than the declared one (``refs``, another reference column)."""
    return _compose(chain, anchors, refs=tuple(refs))


def arith_mean_fc(chain: Chain, anchors: Anchors | None = None) -> PathValues:
    """A group's fold change as the arithmetic mean of its units' fold changes."""
    return _compose(chain, anchors, mean_rule="arithmetic")


def stats_on_fc(chain: Chain, anchors: Anchors | None = None) -> PathValues:
    """The t test run on the units' linear fold changes instead of their ΔCq."""
    return _compose(chain, anchors, stats_on="fc")


def wells_as_n(chain: Chain, anchors: Anchors | None = None) -> PathValues:
    """Every technical well counted as a biological replicate (calibrator, means, SD, t test)."""
    return _compose(chain, anchors, wells=True)


def pfaffl(chain: Chain, anchors: Anchors | None = None) -> PathValues:
    """Pfaffl's efficiency-corrected ratio, with the efficiencies given (missing refs: 2.0)."""
    return _compose(chain, anchors, fc_rule="pfaffl")


def row_shift(values: Mapping[int, float], rows: Sequence[int], shift: int) -> np.ndarray:
    """The value each row would show if a column were pasted ``shift`` rows off.

    Args:
        values: Sheet row -> the textbook value of a column (every chain of that column).
        rows: The rows to read.
        shift: +1 takes the next row's value, -1 the previous row's.

    Returns:
        One value per row of ``rows`` (NaN where the neighbouring row has none).
    """
    return np.array([values.get(r + shift, math.nan) for r in rows], dtype=float)


# ---------------------------------------------------------------------------------------------
# Reading the file
# ---------------------------------------------------------------------------------------------


@dataclass
class _Grid:
    """One sheet's cells (internal; never part of the result)."""

    index: int
    title: str
    cells: dict[tuple[int, int], Any]
    text_ids: dict[tuple[int, int], str]
    by_row: dict[int, dict[int, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for (row, column), value in sorted(self.cells.items()):
            self.by_row.setdefault(row, {})[column] = value


def _grids(read: SheetRead) -> list[_Grid]:
    cells: dict[str, dict[tuple[int, int], Any]] = {title: {} for title in read.sheets}
    ids: dict[str, dict[tuple[int, int], str]] = {title: {} for title in read.sheets}
    for cell in read.cells:
        title = cell.cell.rsplit("!", 1)[0]
        cells[title][(cell.row, cell.column)] = read.values[cell.cell]
        ids[title][(cell.row, cell.column)] = cell.text_id
    return [
        _Grid(index, title, cells[title], ids[title])
        for index, title in enumerate(read.sheets, start=1)
    ]


def _formulas_without_values(path: Path, read: SheetRead) -> dict[str, int]:
    """Sheet title -> number of formula cells that carry no cached value."""
    import openpyxl  # read_sheet already needed it

    missing: dict[str, int] = {}
    book = openpyxl.load_workbook(path, read_only=True, data_only=False, keep_links=False)
    try:
        for sheet in book.worksheets:
            for cells in sheet.iter_rows():
                for cell in cells:
                    if getattr(cell, "data_type", None) != "f":
                        continue
                    ref = f"{sheet.title}!{column_letter(cell.column)}{cell.row}"
                    if read.values.get(ref) is None:
                        missing[sheet.title] = missing.get(sheet.title, 0) + 1
    finally:
        book.close()
    return missing


FORMULA_REFUSAL = (
    "the workbook has formulas without saved values: it was written by a program that does not "
    "calculate (such as openpyxl or pandas), not saved by a spreadsheet program. qPilot never "
    "evaluates formulas. Open it in Excel or LibreOffice and save it, or export it as CSV."
)


def _read(path: str | Path) -> tuple[SheetRead, Literal["xlsx", "csv"], dict[str, int]]:
    try:
        read = read_sheet(path)
    except SheetError as err:
        raise SheetCheckError(str(err)) from err
    file = Path(path)
    kind: Literal["xlsx", "csv"] = "xlsx" if file.suffix.lower() in (".xlsx", ".xlsm") else "csv"
    missing = _formulas_without_values(file, read) if kind == "xlsx" else {}
    return read, kind, missing


# ---------------------------------------------------------------------------------------------
# Cells and headers
# ---------------------------------------------------------------------------------------------

_NUMBER = re.compile(r"^[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?$")
_COMMA_DECIMAL = re.compile(r"^[-+]?\d*,\d+$")
_MISSING = re.compile(
    r"^(?:undetermined|undet\.?|n/?a|nan|nd|n\.d\.|-+|—|–|no\s*c[tq]|not\s+detected|none)$",
    re.I,
)
_STRICT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.()+\-]{0,23}(?: [A-Za-z0-9_.()+\-]{1,15})?$")
REFERENCE_GENES: frozenset[str] = frozenset(
    {
        "ACTB",
        "ALAS1",
        "ALU",
        "ALUSQ",
        "B2M",
        "CYPA",
        "EEF1A1",
        "GAPD",
        "GAPDH",
        "GUSB",
        "HMBS",
        "HPRT",
        "HPRT1",
        "HSP90AB1",
        "PGK1",
        "POLR2A",
        "PPIA",
        "RN18S",
        "RN18S1",
        "RNA18S",
        "RNA18S5",
        "18S",
        "18SRRNA",
        "RPL13A",
        "RPL19",
        "RPL27",
        "RPL32",
        "RPLP0",
        "RPS18",
        "SDHA",
        "TBP",
        "TFRC",
        "TUBB",
        "UBC",
        "YWHAZ",
    }
)
_CONTROL = re.compile(
    r"(?<![a-z0-9])(?:control|controls|ctrl|ctl|untreated|untr|vehicle|veh|mock|sham|wt|"
    r"wild[\s-]?type|naive|baseline|calibrator|normal|healthy|nt|non[\s-]?targeting|scrambled?|"
    r"scr|dmso|pbs|placebo|unstimulated|unstim|rest)(?![a-z0-9])",
    re.I,
)
_EXCLUDED_TYPE = re.compile(
    r"^(?:ntc|nac|nrt|no\s*template.*|negative.*|neg|blank|water|std|standard.*|no\s*rt|"
    r"-\s*rt|minus\s*rt|positive.*|pos|pc|nc)$",
    re.I,
)
_STAT_TAIL = (
    r"(?:\s+(?:of\s+)?(?:fc|fold\s*change|rq|dd?c[tq]|δδc[tq]|δc[tq]|∆∆c[tq]|∆c[tq]|2\^\S*))?"
)
_STAT_ROWS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (stat, re.compile(r"^(?:" + words + r")" + _STAT_TAIL + r"\s*(?:\(.*\)|:)?\s*$", re.I))
    for stat, words in (
        ("sem", r"sem|s\.e\.m\.?|se|std\.?\s*err(?:or)?|standard\s+error"),
        ("sd", r"sd|stdev|st\.?\s*dev\.?|std\.?\s*dev\.?|std|standard\s+deviation"),
        ("p", r"p|p\s*-?\s*val(?:ue)?|pval|t\s*-?\s*test|ttest"),
        ("mean", r"mean|average|avg|ave|geomean|geometric\s+mean|arithmetic\s+mean"),
    )
)


def _parse(value: Any) -> tuple[float, float]:
    """A cell as (number, half a unit in its last decimal); (NaN, NaN) when not a number."""
    if value is None or isinstance(value, bool):
        return math.nan, math.nan
    if isinstance(value, int):
        return float(value), 0.5
    if isinstance(value, float):
        if not math.isfinite(value):
            return math.nan, math.nan
        text = repr(value)
    elif isinstance(value, str):
        text = value.strip().replace("−", "-").replace(" ", "").replace(" ", "")
        if _COMMA_DECIMAL.match(text):
            text = text.replace(",", ".")
        if not _NUMBER.match(text):
            return math.nan, math.nan
    else:
        return math.nan, math.nan
    mantissa, _, exponent = text.lower().partition("e")
    decimals = len(mantissa.split(".", 1)[1]) if "." in mantissa else 0
    return float(text), 0.5 * 10.0 ** ((int(exponent) if exponent else 0) - decimals)


def _letter_index(letter: str) -> int:
    index = 0
    for ch in letter.strip().upper():
        if not "A" <= ch <= "Z":
            raise SheetCheckError(f"not a column letter: {letter!r}")
        index = index * 26 + ord(ch) - 64
    if not index:
        raise SheetCheckError("empty column letter")
    return index


def _stat_label(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    for stat, pattern in _STAT_ROWS:
        if pattern.match(text):
            return stat
    return None


_B, _E = r"(?<![a-z0-9])", r"(?![a-z0-9])"
_D = r"(?:delta|δ|∆)\s*"


def _kw(pattern: str) -> re.Pattern[str]:
    return re.compile(_B + "(?:" + pattern + ")" + _E, re.I)


KEYWORDS: dict[str, re.Pattern[str]] = {
    "fc_formula": re.compile(
        r"(?<![a-z0-9.])2\s*\^?\s*[(\[]?\s*[-−–]?\s*[(\[]?\s*(?:" + _D + _D + r"|dd\s*)c[tqp]",
        re.I,
    ),
    "ddcq": _kw(_D + _D + r"c[tqp]s?|dd\s*c[tqp]s?"),
    "dcq": _kw(_D + r"c[tqp]s?|dc[tqp]s?"),
    "cq": _kw(
        r"c[tqp]s?|c\(t\)|cycle\s+threshold|threshold\s+cycle|quantification\s+cycle|"
        r"crossing\s+point"
    ),
    "mean": _kw(r"mean|average|avg|ave|geomean|geo\s*mean|geometric\s+mean|arithmetic\s+mean"),
    "fc": _kw(
        r"rq|fc|fold(?:\s*-?\s*changes?)?|foldchange|relative\s+(?:expression|quantity|"
        r"quantification|mrna|levels?|abundance)|rel\.?\s*(?:exp|expr|quant)\.?|expression\s+ratio|"
        r"ratio|normali[sz]ed\s+expression|nrq"
    ),
    "sd": _kw(r"sd|stdev|st\.?\s?dev|std\.?\s?dev|standard\s+deviation|std"),
    "sem": _kw(r"sem|se|s\.e\.m\.?|std\.?\s?err(?:or)?|standard\s+error"),
    "p": _kw(r"p|p\s*-?\s*val(?:ue)?s?|pval|t\s*-?\s*test|ttest|welch|student'?s?"),
    "ref": _kw(
        r"refs?|reference(?:\s+genes?)?|housekeeping(?:\s+genes?)?|hkg?|endogenous(?:\s+control)?|"
        r"normali[sz]er|ref\s*genes?"
    ),
    "log2": _kw(r"log\s*2|log\s*base\s*2"),
    "log2fc": _kw(r"log\s*2\s*(?:fc|rq|fold\s*-?\s*changes?|ratio|expression)"),
    "rep": _kw(r"rep(?:licate)?\s*\d*|r\d|tech(?:nical)?\s*rep\w*\s*\d*|well\s*\d*|#\s*\d+"),
    "filler": _kw(
        r"of|the|for|in|vs\.?|versus|to|over|by|norm(?:ali[sz]ed)?|genes?|targets?|values?|"
        r"levels?|and|with|per|cq\s*values?|on"
    ),
}
_SPLIT = re.compile(r"[\s/,;:|&=]+")


@dataclass(frozen=True)
class _HeaderGuess:
    role: str | None
    scale: str | None = None
    confidence: float = 0.0
    labels: tuple[Any, ...] = ()
    ref_hint: bool = False


def _clean_token(token: str) -> str:
    token = token.strip(" _-.:'\"^")
    while token and token[0] in "([{":
        token = token[1:]
    opened = sum(token.count(ch) for ch in "([{")
    while token and token[-1] in ")]}" and opened < sum(token.count(ch) for ch in ")]}"):
        token = token[:-1]
    return token.strip(" _-.:'\"^")


def _labels(text: str, used: Sequence[str]) -> tuple[str, ...]:
    """What is left of a header once its keywords are removed (candidate gene names)."""
    rest = text
    for key in (*used, "mean", "rep", "filler"):
        rest = KEYWORDS[key].sub(" ", rest)
    rest = re.sub(r"[δ∆]", " ", rest, flags=re.I)
    out = []
    for token in _SPLIT.split(rest):
        token = _clean_token(token)
        if token and not token.isdigit() and len(token) <= 40 and token.lower() not in ("x", "-"):
            out.append(token)
    return tuple(out)


def _classify_header(value: Any) -> _HeaderGuess:
    """A header cell's role, scale, confidence and the gene names it carries."""
    if isinstance(value, dt.date | dt.datetime):
        return _HeaderGuess(None, labels=(value,))
    if not isinstance(value, str) or not value.strip():
        return _HeaderGuess(None)
    text = value.strip()
    hit = {key: bool(p.search(text)) for key, p in KEYWORDS.items() if key not in ("filler",)}
    fc_word = hit["fc"] or hit["fc_formula"]
    ref = hit["ref"]
    if hit["sd"] or hit["sem"]:
        role = "sem" if hit["sem"] and not hit["sd"] else "sd"
        if hit["cq"] and not (hit["dcq"] or hit["ddcq"] or fc_word):
            return _HeaderGuess("ignored", confidence=0.8)  # technical SD of replicate Cq
        scale = "fc" if fc_word else "ddcq" if hit["ddcq"] else "dcq" if hit["dcq"] else None
        return _HeaderGuess(
            role, scale, 0.85, _labels(text, [role, "fc", "fc_formula", "ddcq", "dcq"])
        )
    if hit["p"] and not (hit["cq"] or hit["dcq"] or hit["ddcq"]):
        return _HeaderGuess("p", None, 0.85, _labels(text, ["p", "fc", "fc_formula"]))
    if (fc_word and hit["log2"]) or hit["log2fc"]:
        # a log2 fold change is -ΔΔCq: checked as ΔΔCq, its sign a convention
        if hit["mean"]:
            return _HeaderGuess("ignored", confidence=0.6)
        used = ["log2fc", "fc", "fc_formula", "log2"]
        return _HeaderGuess("ddcq", None, 0.8, _labels(text, used))
    if fc_word:
        used = ["fc", "fc_formula", "ddcq"]
        weak = not hit["fc_formula"] and bool(re.fullmatch(r"(?i)\W*(ratio|rel\.?)\W*", text))
        if hit["mean"]:
            return _HeaderGuess("mean_fc", None, 0.85, _labels(text, used))
        return _HeaderGuess("fc", None, 0.6 if weak else 0.9, _labels(text, used))
    if hit["ddcq"]:
        return _HeaderGuess("ddcq", None, 0.9, _labels(text, ["ddcq"]), ref)
    if hit["dcq"]:
        return _HeaderGuess("dcq", None, 0.9, _labels(text, ["dcq", "ref"]), ref)
    if hit["cq"]:
        role = "mean_cq" if hit["mean"] else "cq"
        return _HeaderGuess(role, None, 0.9, _labels(text, ["cq", "ref"]), ref)
    field_name = header_field(text)
    if field_name is not None:
        exact = squash(text) in _exact_headers()
        mapped = {"target": "gene", "replicate": "ignored"}.get(field_name, field_name)
        if mapped not in _STRUCTURAL and mapped != "ignored":
            mapped = "ignored"
        return _HeaderGuess(mapped, None, 0.95 if exact else 0.75)
    return _HeaderGuess(None, labels=(text,), ref_hint=ref)


def _exact_headers() -> frozenset[str]:
    from qpilot.io.sheets import HEADER_SYNONYMS

    return frozenset(s for spellings in HEADER_SYNONYMS.values() for s in spellings)


def _gene_key(raw: Any) -> str | None:
    """A name for a gene that is safe to show: plain assay-name text or the HGNC symbol."""
    if isinstance(raw, dt.date | dt.datetime):
        return cell_text(raw)
    text = cell_text(raw).strip()
    if not text:
        return None
    if _STRICT_NAME.match(text):
        return text
    return check_symbol(text).resolved


def _is_reference(key: str) -> bool:
    base = normalise_assay_name(key).upper().replace("-", "").replace(" ", "")
    return base in REFERENCE_GENES or base.replace("RRNA", "") in REFERENCE_GENES


def _same_gene(a: str, b: str) -> bool:
    if a == b or a.casefold() == b.casefold():
        return True
    return normalise_assay_name(a).casefold() == normalise_assay_name(b).casefold()


# ---------------------------------------------------------------------------------------------
# Guessing the mapping
# ---------------------------------------------------------------------------------------------


@dataclass
class _Rows:
    data: list[int]
    summary: dict[int, str]
    n_excluded: int


def _split_rows(grid: _Grid, header_row: int, sample: int, type_col: int | None) -> _Rows:
    data, summary, excluded = [], {}, 0
    for row in sorted(r for r in grid.by_row if r > header_row):
        cells = grid.by_row[row]
        value = cells.get(sample)
        text = cell_text(value).strip()
        if text:
            stat = _stat_label(value)
            if stat is not None:
                summary[row] = stat
                continue
            if type_col is not None and _EXCLUDED_TYPE.match(cell_text(cells.get(type_col))):
                excluded += 1
                continue
            data.append(row)
            continue
        for _, other in sorted(cells.items()):
            if isinstance(other, str) and other.strip():
                stat = _stat_label(other)
                if stat is not None:
                    summary[row] = stat
                break
    return _Rows(data, summary, excluded)


def _header_choice(grids: Sequence[_Grid], sheet: int | None):
    best = None
    for grid in grids:
        if sheet is not None and grid.index != sheet:
            continue
        for row in sorted(grid.by_row)[:HEADER_SCAN_ROWS]:
            guesses = {c: _classify_header(v) for c, v in sorted(grid.by_row[row].items())}
            roles = [g.role for g in guesses.values()]
            if "sample" not in roles:
                continue
            structural = {r for r in roles if r in _STRUCTURAL}
            analysis = sum(1 for r in roles if r in _ANALYSIS)
            score = (len(structural) + analysis, analysis)
            if best is None or score > best[0]:
                best = (score, grid, row, guesses)
    return best


def _column_numbers(grid: _Grid, rows: Sequence[int], column: int) -> tuple[np.ndarray, float]:
    values, halves = [], []
    for row in rows:
        number, half = _parse(grid.by_row.get(row, {}).get(column))
        values.append(number)
        if math.isfinite(half):
            halves.append(half)
    return np.array(values, dtype=float), (min(halves) if halves else 0.0)


def _cq_like(values: np.ndarray) -> bool:
    ok = values[~np.isnan(values)]
    if len(ok) == 0 or len(ok) < 0.6 * len(values):
        return False
    return bool(CQ_LIKE[0] <= float(np.median(ok)) <= CQ_LIKE[1])


def guess_mapping(path: str | Path | SheetRead, *, sheet: int | None = None) -> ColumnMapping:
    """Guess which column holds what (never confirmed: a person confirms it).

    Args:
        path: The sheet file, or what :func:`qpilot.io.sheets.read_sheet` returned for it.
        sheet: 1-based sheet index; default the sheet whose header names the most columns.

    Returns:
        The guessed mapping, ``confirmed=False``.

    Raises:
        SheetCheckError: Unreadable sheet, formulas without saved values, or no table with a
            sample column.
    """
    if isinstance(path, SheetRead):
        read, missing = path, {}
    else:
        read, _, missing = _read(path)
    return _guess(read, missing, sheet)[0]


def _guess(read: SheetRead, missing: Mapping[str, int], sheet: int | None):
    grids = _grids(read)
    choice = _header_choice(grids, sheet)
    if choice is None:
        if missing:
            raise SheetCheckError(FORMULA_REFUSAL)
        raise SheetCheckError(
            "no table with a sample column was found in the first rows of any sheet; "
            "give the mapping explicitly"
        )
    _, grid, header_row, guesses = choice
    if missing.get(grid.title):
        raise SheetCheckError(FORMULA_REFUSAL)
    guesses = _labels_from_row_above(grid, header_row, guesses)
    sample = next(c for c, g in guesses.items() if g.role == "sample")
    type_col = next((c for c, g in guesses.items() if g.role == "type"), None)
    rows = _split_rows(grid, header_row, sample, type_col)
    gene_col = next((c for c, g in guesses.items() if g.role == "gene"), None)
    taken: set[str] = set()
    columns: list[ColumnGuess] = []
    pending: list[tuple[int, _HeaderGuess, str | None]] = []
    for column, guess in guesses.items():
        role = guess.role
        if role in _STRUCTURAL:
            if role in taken and role != "well":
                role = "ignored"
            taken.add(role)
        if role is None:
            values, _ = _column_numbers(grid, rows.data, column)
            if not _cq_like(values) or not guess.labels:
                continue
            role, guess = "cq", _HeaderGuess("cq", None, 0.6, guess.labels, guess.ref_hint)
            basis = "content"
        else:
            basis = "header"
        pending.append((column, guess, role))
        columns.append(
            ColumnGuess(
                column=column_letter(column),
                role=role,  # type: ignore[arg-type]
                scale=guess.scale,  # type: ignore[arg-type]
                confidence=guess.confidence,
                basis=basis,  # type: ignore[arg-type]
            )
        )
    by_letter = {c.column: c for c in columns}
    cq_unlabelled = [c for c, g, r in pending if r in ("cq", "mean_cq") and not g.labels]
    layout: Layout = "long" if gene_col is not None and cq_unlabelled else "wide"
    references: list[str] = []
    if layout == "wide":
        _assign_wide(pending, by_letter, references)
    else:
        _assign_long(grid, rows, gene_col, pending, by_letter, references)
    mapping = ColumnMapping(
        sheet=grid.index,
        header_row=header_row,
        layout=layout,
        columns=sorted(by_letter.values(), key=lambda c: _letter_index(c.column)),
        references=references,
    )
    control_id, control_conf = _guess_control(grid, rows, mapping)
    mapping.control_text_id = control_id
    mapping.control_confidence = control_conf
    return mapping, grid


def _labels_from_row_above(grid: _Grid, header_row: int, guesses: dict[int, _HeaderGuess]):
    """Two-row headers: gene names in the row above "Ct  ΔCt  ΔΔCt" (often merged across).

    A column whose header names a step but no gene takes the gene from the cell above, when
    the row above names more than one gene (a single title across the table names none).
    """
    above = grid.by_row.get(header_row - 1, {})
    keys = {c: _gene_key(above[c]) for c in guesses if c in above}
    if len({k for k in keys.values() if k}) < 2:
        return guesses
    out = dict(guesses)
    for column, guess in guesses.items():
        if guess.role in _ANALYSIS and not guess.labels and keys.get(column):
            out[column] = replace(guess, labels=(above[column],))
    return out


def _assign_wide(pending, by_letter: dict[str, ColumnGuess], references: list[str]) -> None:
    """Give every Cq and intermediate column of a wide sheet its gene."""
    cq_keys: dict[int, str] = {}
    ref_hint: dict[str, bool] = {}
    for column, guess, role in pending:
        if role not in ("cq", "mean_cq"):
            continue
        labels = [lab for lab in guess.labels if _gene_key(lab)]
        joined = " ".join(str(lab) for lab in labels)
        if len(labels) == 2 and _STRICT_NAME.match(joined):  # "18S rRNA Ct"
            labels = [joined]
        if len(labels) != 1:
            continue
        key = _gene_key(labels[0])
        assert key is not None
        cq_keys[column] = key
        ref_hint[key] = ref_hint.get(key, False) or guess.ref_hint
    # replicate columns written GAPDH_1, GAPDH_2: one gene
    bases: dict[str, list[int]] = {}
    for column, key in cq_keys.items():
        match = re.match(r"^(.+?)[_\-. ](?:rep|r)?\d{1,2}$", key, re.I)
        if match:
            bases.setdefault(match.group(1), []).append(column)
    for base, cols in bases.items():
        if len(cols) >= 2:
            for column in cols:
                cq_keys[column] = base
    genes = list(dict.fromkeys(cq_keys.values()))
    for column, key in cq_keys.items():
        by_letter[column_letter(column)].gene = key
    for key in genes:
        if ref_hint.get(key) or _is_reference(key):
            references.append(key)
    # a gene with only a mean Cq column: that column is its Cq
    wells = {k for c, k in cq_keys.items() if by_letter[column_letter(c)].role == "cq"}
    for column, key in cq_keys.items():
        guess = by_letter[column_letter(column)]
        if guess.role == "mean_cq" and key not in wells:
            guess.role = "cq"
    targets = [g for g in genes if g not in references]
    for column, guess, role in pending:
        if role not in _ROW_ROLES - {"mean_cq"} and role not in _GROUP_ROLES:
            continue
        entry = by_letter[column_letter(column)]
        found = [t for t in targets if any(_label_is(lab, t) for lab in guess.labels)]
        if len(found) == 1:
            entry.gene = found[0]
        elif not found and len(targets) == 1:
            entry.gene = targets[0]
            entry.confidence = round(entry.confidence * 0.9, 2)
    for entry in by_letter.values():  # Cq columns whose gene could not be told
        if entry.role in ("cq", "mean_cq") and entry.gene is None:
            entry.role = "ignored"


def _label_is(label: Any, key: str) -> bool:
    other = _gene_key(label)
    return other is not None and _same_gene(other, key)


def _assign_long(grid, rows, gene_col, pending, by_letter, references: list[str]) -> None:
    """In a long sheet, labelled Cq columns are per-row reference Cq; genes come from rows."""
    seen: list[str] = []
    for row in rows.data:
        key = _gene_key(grid.by_row[row].get(gene_col))
        if key and key not in seen:
            seen.append(key)
    for column, guess, role in pending:
        entry = by_letter[column_letter(column)]
        if role in ("cq", "mean_cq") and guess.labels:
            key = _gene_key(guess.labels[0]) if len(guess.labels) == 1 else None
            if key is None:
                entry.role = "ignored"
                continue
            entry.gene = key
            entry.role = "cq"
            if key not in references:
                references.append(key)
    cq_cols = [e for e in by_letter.values() if e.role == "cq" and e.gene is None]
    mean_cols = [e for e in by_letter.values() if e.role == "mean_cq" and e.gene is None]
    if mean_cols and not cq_cols:
        mean_cols[0].role = "cq"
    for key in seen:
        if _is_reference(key) and key not in references:
            references.append(key)


def _guess_control(grid: _Grid, rows: _Rows, mapping: ColumnMapping) -> tuple[str | None, float]:
    group = mapping.by_role("group")
    if not group:
        return None, 0.0
    column = _letter_index(group[0].column)
    first: dict[str, tuple[int, int]] = {}
    for row in rows.data:
        text = cell_text(grid.by_row[row].get(column)).strip()
        if text and text not in first:
            first[text] = (row, column)
    if not first:
        return None, 0.0
    full = [g for g in first if _CONTROL.fullmatch(g.strip())]
    partial = [g for g in first if _CONTROL.search(g)]
    for found, confidence in ((full, 0.8), (partial, 0.7)):
        if len(found) == 1:
            return grid.text_ids[first[found[0]]], confidence
    pick = _control_from_values(grid, rows, mapping, column, list(first))
    if pick is not None:
        return grid.text_ids[first[pick]], 0.6
    return grid.text_ids[first[next(iter(first))]], 0.3


def _control_from_values(grid, rows, mapping, group_col, labels) -> str | None:
    """The group whose ΔΔCq averages zero (or whose fold changes average one) in the sheet."""
    for role, target in (("ddcq", 0.0), ("fc", 1.0)):
        cols = mapping.by_role(role)
        if not cols:
            continue
        column = _letter_index(cols[0].column)
        means = {}
        for label in labels:
            values = [
                _parse(grid.by_row[r].get(column))[0]
                for r in rows.data
                if cell_text(grid.by_row[r].get(group_col)).strip() == label
            ]
            ok = [v for v in values if math.isfinite(v)]
            if ok:
                means[label] = abs(float(np.mean(ok)) - target)
        if means:
            label = min(means, key=lambda k: (means[k], labels.index(k)))
            if means[label] < 0.1:
                return label
    return None


# ---------------------------------------------------------------------------------------------
# Reading the sheet with a mapping
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _RowOutput:
    """One per-row column of the sheet for one chain (``index``: the chain rows it covers)."""

    step: str
    column: int
    index: np.ndarray
    rows: tuple[int, ...]
    values: np.ndarray
    h: float


@dataclass(frozen=True)
class _GroupOutput:
    """One group statistic the sheet shows (a group-level column cell or a summary-row cell)."""

    step: str
    column: int
    group: int
    scale: str | None
    row: int
    value: float
    h: float


@dataclass
class _Sheet:
    """The mapped sheet: chains, the sheet's outputs per chain, groups and genes."""

    mapping: ColumnMapping
    kind: str
    chains: list[Chain]
    ref_anchors: dict[str, dict[str, Anchor]]
    row_outputs: dict[str, list[_RowOutput]]
    group_outputs: dict[str, list[_GroupOutput]]
    groups: list[GroupInfo]
    group_index: dict[str, int]
    genes: list[GeneInfo]
    skipped: list[ColumnCheck]
    notes: list[str]
    n_rows: int


def _validate_mapping(mapping: ColumnMapping) -> dict[str, list[ColumnGuess]]:
    roles: dict[str, list[ColumnGuess]] = {}
    letters = [_letter_index(entry.column) for entry in mapping.columns]
    if len(set(letters)) != len(letters):
        raise SheetCheckError("the mapping names a column twice")
    for entry in mapping.columns:
        roles.setdefault(entry.role, []).append(entry)
    if len(roles.get("sample", [])) != 1:
        raise SheetCheckError("the mapping needs exactly one sample column")
    if not roles.get("cq"):
        raise SheetCheckError("the mapping names no Cq column")
    if mapping.layout == "long" and len(roles.get("gene", [])) != 1:
        raise SheetCheckError("a long sheet needs exactly one gene column")
    for role in ("group", "bio_unit", "type"):
        if len(roles.get(role, [])) > 1:
            raise SheetCheckError(f"the mapping names more than one {role} column")
    return roles


def _control_label(mapping: ColumnMapping, grid: _Grid) -> str | None:
    if mapping.control_group is not None:
        return mapping.control_group.strip()
    if mapping.control_text_id is None:
        return None
    for key, text_id in sorted(grid.text_ids.items()):
        if text_id == mapping.control_text_id:
            return cell_text(grid.cells[key]).strip()
    return None


def _extract(grid: _Grid, mapping: ColumnMapping, kind: str, efficiencies) -> _Sheet:
    roles = _validate_mapping(mapping)
    col = {role: _letter_index(entries[0].column) for role, entries in roles.items()}
    sample, group_col = col["sample"], col.get("group")
    rows = _split_rows(grid, mapping.header_row, sample, col.get("type"))
    if not rows.data:
        raise SheetCheckError("the table has no data rows under the header")
    carry = kind == "csv"
    notes: list[str] = []
    if rows.n_excluded:
        notes.append("Rows marked as no-template, standard or other controls were left out.")
    group_of: dict[int, str] = {}
    group_index: dict[str, int] = {}
    group_cell: dict[str, tuple[int, int]] = {}
    for row in rows.data:
        label = cell_text(grid.by_row[row].get(group_col)).strip() if group_col else ""
        group_of[row] = label
        if label and label not in group_index:
            group_index[label] = len(group_index) + 1
            group_cell[label] = (row, group_col)  # type: ignore[assignment]
    control_label = _control_label(mapping, grid)
    control = group_index.get(control_label or "", 0)
    if not group_index:
        notes.append("No group column: ΔΔCq, fold changes and group statistics are not checked.")
    elif not control:
        notes.append("The control group is not identified: ΔΔCq and later steps are not checked.")
    unit_col = col.get("bio_unit", sample)

    def unit_key(row: int) -> tuple[str, str]:
        return (cell_text(grid.by_row[row].get(unit_col)).strip(), group_of[row])

    groups = []
    for label, index in group_index.items():
        rows_g = [r for r in rows.data if group_of[r] == label]
        groups.append(
            GroupInfo(
                index=index,
                text_id=grid.text_ids[group_cell[label]],
                control=index == control,
                n_units=len({unit_key(r) for r in rows_g}),
                n_rows=len(rows_g),
                first_row=rows_g[0],
            )
        )
    context = _Context(
        grid,
        mapping,
        rows,
        unit_key,
        group_of,
        group_index,
        control,
        tuple(mapping.references),
        dict(efficiencies or {}),
        carry,
    )
    if mapping.layout == "wide":
        chains, row_outputs, gene_cells, ref_anchors = _wide_chains(context)
    else:
        chains, row_outputs, gene_cells, ref_anchors = _long_chains(context, col["gene"])
    skipped: list[ColumnCheck] = []
    if mapping.layout == "wide":
        for entry in mapping.columns:
            if entry.gene is None and entry.role in _ROW_ROLES | _GROUP_ROLES:
                skipped.append(
                    ColumnCheck(
                        column=entry.column,
                        step=entry.role,
                        gene=None,
                        status="not_checked",
                        reason="the gene this column belongs to is not identified; name it in "
                        "the mapping",
                    )
                )
    group_outputs = _group_outputs(context, chains, row_outputs, skipped, col.get("gene"))
    genes = _gene_infos(grid, gene_cells, context.refs)
    return _Sheet(
        mapping,
        kind,
        chains,
        ref_anchors,
        row_outputs,
        group_outputs,
        groups,
        group_index,
        genes,
        skipped,
        notes,
        len(rows.data),
    )


@dataclass(frozen=True)
class _Context:
    grid: _Grid
    mapping: ColumnMapping
    rows: _Rows
    unit_key: Callable[[int], tuple[str, str]]
    group_of: dict[int, str]
    group_index: dict[str, int]
    control: int
    refs: tuple[str, ...]
    efficiency: dict[str, float]
    carry: bool


def _units(context: _Context, chain_rows: Sequence[int]):
    keys: list[tuple[str, str]] = []
    index: dict[tuple[str, str], int] = {}
    unit = np.zeros(len(chain_rows), dtype=int)
    for i, row in enumerate(chain_rows):
        key = context.unit_key(row)
        if key not in index:
            index[key] = len(keys)
            keys.append(key)
        unit[i] = index[key]
    unit_group = np.array([context.group_index.get(k[1], 0) for k in keys], dtype=int)
    return unit, unit_group, keys


def _wide_chains(context: _Context):
    grid, mapping, refs, carry = context.grid, context.mapping, context.refs, context.carry
    data = context.rows.data
    unit, unit_group, _ = _units(context, data)
    m = len(unit_group)
    cq_cols: dict[str, list[int]] = {}
    mean_cols: dict[str, int] = {}
    gene_cells: dict[str, tuple[int, int]] = {}
    for entry in mapping.columns:
        if entry.role in ("cq", "mean_cq") and entry.gene:
            c = _letter_index(entry.column)
            if entry.role == "cq":
                cq_cols.setdefault(entry.gene, []).append(c)
            else:
                mean_cols.setdefault(entry.gene, c)
            gene_cells.setdefault(entry.gene, (mapping.header_row, c))
    if not refs:
        raise SheetCheckError(
            "no reference gene column was recognised; name the references in the mapping"
        )
    missing = [r for r in refs if r not in cq_cols]
    if missing:
        raise SheetCheckError("a declared reference has no Cq column: " + ", ".join(missing))
    wells: dict[str, np.ndarray] = {}
    halves: dict[str, float] = {}
    for gene, cols in cq_cols.items():
        arrays = [_column_numbers(grid, data, c) for c in cols]
        wells[gene] = np.column_stack([values for values, _ in arrays])
        halves[gene] = max(h for _, h in arrays) if carry else 0.0
    all_refs = tuple(g for g in cq_cols if g in refs or _is_reference(g))
    ref_row = {g: _row_mean(wells[g]) for g in all_refs}
    ref_unit = {g: _unit_mean(wells[g], unit, m) for g in all_refs}
    ref_anchor: dict[str, Anchor] = {}
    for gene in all_refs:
        if gene in mean_cols:
            values, h = _column_numbers(grid, data, mean_cols[gene])
            ref_anchor[gene] = Anchor(values, _unit_mean(values, unit, m), h if carry else 0.0)
    chains: list[Chain] = []
    outputs: dict[str, list[_RowOutput]] = {}
    anchors: dict[str, dict[str, Anchor]] = {}
    for gene in cq_cols:
        reference = gene in refs
        if reference and gene not in mean_cols:
            continue
        chains.append(
            Chain(
                gene=gene,
                rows=tuple(data),
                unit=unit,
                unit_group=unit_group,
                control=context.control,
                target=wells[gene],
                target_h=halves[gene],
                refs=() if reference else refs,
                ref_row={} if reference else ref_row,
                ref_unit={} if reference else ref_unit,
                ref_h={} if reference else {g: halves[g] for g in all_refs},
                all_refs=() if reference else all_refs,
                efficiency=context.efficiency,
            )
        )
        anchors[gene] = {} if reference else ref_anchor
        steps = [("mean_cq", mean_cols[gene])] if gene in mean_cols else []
        if not reference:
            steps += [
                (e.role, _letter_index(e.column))
                for e in mapping.columns
                if e.role in ("dcq", "ddcq", "fc") and e.gene == gene
            ]
        outs = []
        for step, c in steps:
            values, h = _column_numbers(grid, data, c)
            outs.append(_RowOutput(step, c, np.arange(len(data)), tuple(data), values, h))
        outputs[gene] = outs
    return chains, outputs, gene_cells, anchors


def _long_chains(context: _Context, gene_col: int):
    grid, mapping, refs, carry = context.grid, context.mapping, context.refs, context.carry
    data = context.rows.data
    keys: dict[int, str | None] = {}
    unnamed: dict[str, str] = {}
    order: list[str] = []
    gene_cells: dict[str, tuple[int, int]] = {}
    for row in data:
        raw = grid.by_row[row].get(gene_col)
        key = _gene_key(raw)
        if key is None and cell_text(raw).strip():
            key = unnamed.setdefault(cell_text(raw).strip(), f"gene_{len(unnamed) + 1}")
        keys[row] = key
        if key and key not in order:
            order.append(key)
            gene_cells[key] = (row, gene_col)
    cq_main = next(
        (_letter_index(e.column) for e in mapping.columns if e.role == "cq" and not e.gene), None
    )
    if cq_main is None:
        raise SheetCheckError("a long sheet needs one Cq column that is not tied to a gene")
    mean_main = next(
        (_letter_index(e.column) for e in mapping.columns if e.role == "mean_cq" and not e.gene),
        None,
    )
    per_row_ref = {
        e.gene: _letter_index(e.column) for e in mapping.columns if e.role == "cq" and e.gene
    }
    if not refs:
        raise SheetCheckError(
            "no reference gene was recognised; name the references in the mapping"
        )
    missing = [r for r in refs if r not in order and r not in per_row_ref]
    if missing:
        raise SheetCheckError("a declared reference is not in the sheet: " + ", ".join(missing))
    cq_all, cq_h = _column_numbers(grid, data, cq_main)
    mean_all, mean_h = (
        _column_numbers(grid, data, mean_main) if mean_main is not None else (None, 0.0)
    )
    position = {r: i for i, r in enumerate(data)}
    all_refs = tuple(g for g in order if g in refs or _is_reference(g))
    all_refs += tuple(g for g in per_row_ref if g not in all_refs)
    by_unit: dict[str, dict[tuple[str, str], list[float]]] = {}
    mean_by_unit: dict[str, dict[tuple[str, str], list[float]]] = {}
    for row in data:
        gene = keys[row]
        if gene in all_refs:
            unit = context.unit_key(row)
            by_unit.setdefault(gene, {}).setdefault(unit, []).append(cq_all[position[row]])
            if mean_all is not None:
                value = mean_all[position[row]]
                mean_by_unit.setdefault(gene, {}).setdefault(unit, []).append(value)
    out_cols = [
        (e.role, _letter_index(e.column))
        for e in mapping.columns
        if e.role in ("dcq", "ddcq", "fc") and not e.gene
    ]
    h_cq = cq_h if carry else 0.0
    chains: list[Chain] = []
    outputs: dict[str, list[_RowOutput]] = {}
    anchors: dict[str, dict[str, Anchor]] = {}
    for gene in order:
        chain_rows = [r for r in data if keys[r] == gene]
        unit, unit_group, ukeys = _units(context, chain_rows)
        m = len(unit_group)
        idx = [position[r] for r in chain_rows]
        reference = gene in refs
        ref_row: dict[str, np.ndarray] = {}
        ref_unit: dict[str, np.ndarray] = {}
        ref_h: dict[str, float] = {}
        ref_anchor: dict[str, Anchor] = {}
        if not reference:
            for ref in all_refs:
                if ref in per_row_ref:
                    values, h = _column_numbers(grid, chain_rows, per_row_ref[ref])
                    ref_row[ref], ref_unit[ref] = values, _unit_mean(values, unit, m)
                    ref_h[ref] = h if carry else 0.0
                    continue
                cells = by_unit.get(ref, {})
                per = np.array([_mean(np.array(cells.get(k, []), dtype=float)) for k in ukeys])
                ref_unit[ref], ref_row[ref], ref_h[ref] = per, per[unit], h_cq
                if mean_all is not None:
                    cells = mean_by_unit.get(ref, {})
                    per = np.array([_mean(np.array(cells.get(k, []), dtype=float)) for k in ukeys])
                    ref_anchor[ref] = Anchor(per[unit], per, mean_h if carry else 0.0)
        chains.append(
            Chain(
                gene=gene,
                rows=tuple(chain_rows),
                unit=unit,
                unit_group=unit_group,
                control=context.control,
                target=cq_all[idx][:, None],
                target_h=h_cq,
                refs=() if reference else refs,
                ref_row=ref_row,
                ref_unit=ref_unit,
                ref_h=ref_h,
                all_refs=() if reference else all_refs,
                efficiency=context.efficiency,
            )
        )
        anchors[gene] = ref_anchor
        outs = []
        span = np.arange(len(chain_rows))
        if mean_all is not None and mean_main is not None:
            outs.append(
                _RowOutput("mean_cq", mean_main, span, tuple(chain_rows), mean_all[idx], mean_h)
            )
        if not reference:
            for step, c in out_cols:
                values, h = _column_numbers(grid, chain_rows, c)
                outs.append(_RowOutput(step, c, span, tuple(chain_rows), values, h))
        outputs[gene] = outs
    return chains, outputs, gene_cells, anchors


def _group_outputs(context: _Context, chains, row_outputs, skipped, gene_col):
    """Group statistics: cells of group-level columns and of summary rows."""
    grid, mapping, group_index, control = (
        context.grid,
        context.mapping,
        context.group_index,
        context.control,
    )
    out: dict[str, list[_GroupOutput]] = {c.gene: [] for c in chains}
    checked = {c.gene: c for c in chains if c.refs}

    def comparison(g: int) -> int | None:  # the group a p-value compares with the control
        if g != control:
            return g
        if len(group_index) == 2:
            return next(i for i in group_index.values() if i != control)
        return None

    level_columns = [e for e in mapping.columns if e.role in _GROUP_ROLES]
    for entry in level_columns:
        c = _letter_index(entry.column)
        genes = [entry.gene] if entry.gene else list(checked)
        for gene in genes:
            chain = checked.get(gene)
            if chain is None:
                continue
            values, h = _column_numbers(grid, list(chain.rows), c)
            distinct: dict[int, list[tuple[int, float]]] = {}
            for row, value in zip(chain.rows, values, strict=True):
                g = group_index.get(context.group_of[row], 0)
                if math.isfinite(value) and g:
                    seen = distinct.setdefault(g, [])
                    if not any(abs(value - v) <= max(1e-12, 1e-9 * abs(v)) for _, v in seen):
                        seen.append((row, value))
            if any(len(v) > 1 for v in distinct.values()):
                skipped.append(
                    ColumnCheck(
                        column=entry.column,
                        step=entry.role,
                        gene=gene,
                        status="not_checked",
                        granularity="group",
                        reason="its values vary within a group, so it is not a group statistic",
                    )
                )
                continue
            for g, items in sorted(distinct.items()):
                target = comparison(g) if entry.role == "p" else g
                row, value = items[0]
                if target is None or any(
                    (o.step, o.column, o.group, o.value) == (entry.role, c, target, value)
                    for o in out[gene]
                ):
                    continue  # a p-value repeated on both groups' rows is one p-value
                out[gene].append(_GroupOutput(entry.role, c, target, entry.scale, row, value, h))
    data = sorted(context.rows.data)
    group_col = next((_letter_index(e.column) for e in mapping.columns if e.role == "group"), None)
    gene_of_row = {r: ch.gene for ch in chains for r in ch.rows}
    for row, stat in sorted(context.rows.summary.items()):
        at = bisect.bisect_left(data, row)
        if not at:
            continue
        last = data[at - 1]  # the data row just above the summary row
        label = cell_text(grid.by_row[row].get(group_col)).strip() if group_col else ""
        if label not in group_index:
            label = context.group_of[last]
        g = group_index.get(label, 0)
        if not g:
            continue
        gene_here = None
        if mapping.layout == "long":
            raw = grid.by_row[row].get(gene_col)
            gene_here = _gene_key(raw) if cell_text(raw).strip() else gene_of_row[last]
            if gene_here is None:  # a gene name the check does not show: not attributed
                continue
        for gene in checked:
            if gene_here is not None and gene != gene_here:
                continue
            cells = [(o.column, o.step, None) for o in row_outputs.get(gene, [])]
            cells += [
                (_letter_index(e.column), e.role, e.scale)
                for e in level_columns
                if e.gene in (None, gene)
            ]
            for column, column_step, scale in cells:
                number, half = _parse(grid.by_row[row].get(column))
                if not math.isfinite(number) or column_step == "mean_cq":
                    continue
                if column_step in _GROUP_ROLES:
                    step, scale_here = column_step, scale
                else:
                    step, scale_here = _summary_step(stat, column_step)
                target = comparison(g) if step == "p" else g
                if target is None:
                    continue
                item = _GroupOutput(step, column, target, scale_here, row, number, half)
                if item not in out[gene]:
                    out[gene].append(item)
    return out


def _summary_step(stat: str, column_step: str) -> tuple[str, str | None]:
    """What a summary-row cell under a per-row column holds (step, scale)."""
    if stat == "mean":
        return {"dcq": "mean_dcq", "ddcq": "mean_ddcq", "fc": "mean_fc"}[column_step], None
    if stat in ("sd", "sem"):
        return stat, column_step
    return "p", None


def _gene_infos(grid: _Grid, gene_cells: Mapping[str, tuple[int, int]], refs) -> list[GeneInfo]:
    out = []
    for key, (row, column) in gene_cells.items():
        raw = grid.cells.get((row, column))
        finding = check_symbol(raw if isinstance(raw, dt.date | dt.datetime) else key)
        out.append(
            GeneInfo(
                key=key,
                reference=key in refs,
                status=finding.status,
                candidates=list(finding.candidates),
                flagged=finding.status in ("date_mangled", "number_mangled"),
                cell=f"{column_letter(column)}{row}",
                note=finding.note,
            )
        )
    return out


# ---------------------------------------------------------------------------------------------
# Comparing the sheet with the paths
# ---------------------------------------------------------------------------------------------


def _tolerance(expected: np.ndarray, display: float, carried: np.ndarray) -> np.ndarray:
    size = np.abs(np.where(np.isfinite(expected), expected, 0.0))
    return np.maximum.reduce(
        [display + carried, REL_TOL * size, FLOAT_FLOOR * np.maximum(1.0, size)]
    )


def _matches(user, expected, tol, signed: bool) -> tuple[np.ndarray, int]:
    """Cells that match ``expected`` (or its negative, for a sign convention), column-wide."""
    finite = np.isfinite(user) & np.isfinite(expected)
    with np.errstate(invalid="ignore"):
        pos = finite & (np.abs(user - expected) <= tol)
        if not signed:
            return pos, 1
        neg = finite & (np.abs(user + expected) <= tol)
    return (pos, 1) if pos.sum() >= neg.sum() else (neg, -1)


def _granularity(out: _RowOutput, chain: Chain) -> str:
    """``unit`` when every unit's cells carry one value (one value per biological unit)."""
    if out.step == "mean_cq":
        return "unit"
    ok = np.isfinite(out.values)
    units, values = chain.unit[out.index][ok], out.values[ok]
    m = chain.n_units
    high, low = np.full(m, -np.inf), np.full(m, np.inf)
    np.maximum.at(high, units, values)
    np.minimum.at(low, units, values)
    seen = np.isfinite(high)
    size = np.maximum(np.abs(high), np.abs(low))[seen]
    spread = (high - low)[seen]
    return "row" if (spread > 2 * out.h + FLOAT_FLOOR * np.maximum(1.0, size)).any() else "unit"


def _expected(values: PathValues, step: str, chain: Chain, out: _RowOutput, gran: str):
    if gran == "unit":
        u = chain.unit[out.index]
        return values.unit[step][u], values.unit_h[step][u]
    return values.row[step][out.index], values.row_h[step][out.index]


def _group_keys(item: _GroupOutput) -> list[tuple[str, int, str]]:
    g = item.group
    if item.step in ("sd", "sem"):
        scales = {"dcq": ["dcq"], "ddcq": ["dcq"], "fc": ["fc"]}.get(
            item.scale or "", ["dcq", "fc"]
        )
        return [(item.step, g, s) for s in scales]
    if item.step == "p":
        return [("p", g, "welch"), ("p", g, "student")]
    return [(item.step, g, "")]


def _group_match(item: _GroupOutput, values: PathValues) -> tuple[bool, float, str, int]:
    """Whether a group statistic matches (value, matched variant, sign)."""
    signed = item.step in _SIGNED_STEPS
    first = (False, math.nan, "", 1)
    for key in _group_keys(item):
        e = values.group.get(key, math.nan)
        h = values.group_h.get(key, 0.0)
        if not math.isfinite(e):
            continue
        tol = _tolerance(np.array([e]), item.h, np.array([h]))[0]
        for sign in (1, -1) if signed else (1,):
            if abs(item.value - sign * e) <= tol:
                return True, e, key[2], sign
        if not math.isfinite(first[1]):
            first = (False, e, key[2], 1)
    return first


@dataclass
class _Eval:
    chain: Chain
    anchors: Anchors
    e2e: PathValues
    anch: PathValues
    granularity: dict[int, str]


def _anchors(chain: Chain, outs: Sequence[_RowOutput], ref_anchor, carry: bool) -> Anchors:
    steps: dict[str, Anchor] = {}
    m = chain.n_units
    for out in outs:
        if out.step in steps:
            continue
        values = np.full(len(chain.rows), np.nan)
        values[out.index] = out.values
        if out.step == "fc":
            values = np.where(values > 0, values, np.nan)
        unit = _unit_mean(values, chain.unit, m, log=out.step == "fc")
        steps[out.step] = Anchor(values, unit, out.h if carry else 0.0)
    return Anchors(steps=steps, ref_mean=ref_anchor)


def _sign(chain: Chain, outs: Sequence[_RowOutput], base: PathValues) -> int:
    """The sheet's ΔΔCq sign relative to the textbook (from its ΔΔCq column, else ΔCq)."""
    for step in ("ddcq", "dcq"):
        for out in outs:
            if out.step != step:
                continue
            gran = _granularity(out, chain)
            e, h = _expected(base, step, chain, out, gran)
            tol = _tolerance(e, out.h, h)
            ok, sign = _matches(out.values, e, tol, True)
            if ok.any():
                return sign
    return 1


def _evaluate(chain: Chain, sheet: _Sheet) -> _Eval:
    """The textbook path end to end, and step by step from the sheet's own columns.

    End to end, ΔΔCq is the textbook's own, so its fold change takes the textbook sign; the
    sheet's sign convention only applies to a fold change computed from the sheet's ΔΔCq.
    """
    outs = sheet.row_outputs.get(chain.gene, [])
    e2e = livak_per_unit(chain, Anchors())
    user = _anchors(chain, outs, sheet.ref_anchors.get(chain.gene, {}), sheet.kind == "csv")
    user = Anchors(steps=user.steps, ref_mean=user.ref_mean, sign=_sign(chain, outs, e2e))
    anch = livak_per_unit(chain, user)
    gran = {o.column: _granularity(o, chain) for o in outs}
    return _Eval(chain, user, e2e, anch, gran)


def _candidates(chain: Chain) -> list[tuple[str, str, Callable[..., PathValues]]]:
    """Every path (id, detail, function) that could reproduce a difference in this chain."""
    out: list[tuple[str, str, Callable[..., PathValues]]] = [
        ("sign_inverted", "", sign_inverted),
        ("exponent_twice", "positive exponent", exponent_twice),
        (
            "exponent_twice",
            "negative exponent",
            lambda c, a=None: exponent_twice(c, a, negative=True),
        ),
        ("no_reference", "", no_reference),
    ]
    alternatives: list[tuple[str, ...]] = [(r,) for r in chain.all_refs if (r,) != chain.refs]
    if len(chain.all_refs) > 1 and tuple(chain.all_refs) != chain.refs:
        alternatives.append(tuple(chain.all_refs))
    for alt in alternatives:
        out.append(
            (
                "wrong_reference",
                " + ".join(alt),
                lambda c, a=None, r=alt: wrong_reference(c, a, refs=r),
            )
        )
    out += [("arith_mean_fc", "", arith_mean_fc), ("stats_on_fc", "", stats_on_fc)]
    if chain.has_replicates:
        out.append(("wells_as_n", "", wells_as_n))
    if chain.gene in chain.efficiency:
        out.append(("pfaffl", "", pfaffl))
    return out


@dataclass
class _Cell:
    """The comparison of one output: per cell, reproduced / follows / own difference."""

    out: _RowOutput | _GroupOutput
    gene: str
    reproduced: np.ndarray
    follows: np.ndarray
    own: np.ndarray
    comparable: np.ndarray
    expected: np.ndarray
    tol: np.ndarray
    sign: int
    granularity: str
    units: np.ndarray
    variant: str | None = None
    finding: Finding | None = None


def _compare_row(ev: _Eval, out: _RowOutput) -> _Cell:
    chain = ev.chain
    gran = ev.granularity[out.column]
    signed = out.step in _SIGNED_STEPS
    e, eh = _expected(ev.e2e, out.step, chain, out, gran)
    a, ah = _expected(ev.anch, out.step, chain, out, gran)
    tol_e, tol_a = _tolerance(e, out.h, eh), _tolerance(a, out.h, ah)
    ok_e, sign_e = _matches(out.values, e, tol_e, signed)
    ok_a, _ = _matches(out.values, a, tol_a, signed)
    comparable = np.isfinite(out.values) & np.isfinite(e)
    reproduced = comparable & ok_e
    follows = comparable & ~ok_e & ok_a
    own = comparable & ~ok_e & ~ok_a
    return _Cell(
        out,
        chain.gene,
        reproduced,
        follows,
        own,
        comparable,
        sign_e * e,
        tol_e,
        sign_e,
        gran,
        chain.unit[out.index],
    )


def _compare_group(ev: _Eval, item: _GroupOutput) -> _Cell:
    ok_e, e, variant, sign = _group_match(item, ev.e2e)
    ok_a = _group_match(item, ev.anch)[0]
    comparable = math.isfinite(e)
    arr = np.array
    tol = _tolerance(
        arr([e]), item.h, arr([ev.e2e.group_h.get((item.step, item.group, variant), 0.0)])
    )
    return _Cell(
        item,
        ev.chain.gene,
        arr([comparable and ok_e]),
        arr([comparable and not ok_e and ok_a]),
        arr([comparable and not ok_e and not ok_a]),
        arr([comparable]),
        arr([sign * e]),
        tol,
        sign,
        "group",
        arr([0]),
        variant if comparable and ok_e else None,
    )


def _path_reproduces(cell: _Cell, ev: _Eval, values: tuple[PathValues, PathValues]) -> bool:
    """Whether a path's values (end to end or step by step) give every differing cell."""
    out, own = cell.out, cell.own
    if isinstance(out, _GroupOutput):
        return any(_group_match(out, v)[0] for v in values)
    signed = out.step in _SIGNED_STEPS
    user = out.values[own]
    ok = np.zeros(int(own.sum()), dtype=bool)
    for v in values:
        e, eh = _expected(v, out.step, ev.chain, out, cell.granularity)
        e, eh = e[own], eh[own]
        ok |= _matches(user, e, _tolerance(e, out.h, eh), signed)[0]
    return bool(ok.all())


def _shift_reproduces(cell: _Cell, maps: Mapping[int, dict[int, float]], shift: int) -> bool:
    out = cell.out
    assert isinstance(out, _RowOutput)
    rows = [r for r, own in zip(out.rows, cell.own, strict=True) if own]
    user = out.values[cell.own]
    signed = out.step in _SIGNED_STEPS
    ok = np.zeros(len(rows), dtype=bool)
    for values in maps.values():
        e = row_shift(values, rows, shift)
        ok |= _matches(user, e, _tolerance(e, out.h, np.zeros(len(rows))), signed)[0]
    return bool(ok.all())


def _classify(cell: _Cell, ev: _Eval, shift_maps, cache: dict) -> tuple[list[str], dict]:
    """The paths that reproduce every own-differing cell of an output."""
    found: dict[str, list[str]] = {}
    key = ev.chain.gene
    if key not in cache:
        cache[key] = [
            (pid, detail, (fn(ev.chain, Anchors()), fn(ev.chain, ev.anchors)))
            for pid, detail, fn in _candidates(ev.chain)
        ]
    for pid, detail, values in cache[key]:
        if _path_reproduces(cell, ev, values):
            found.setdefault(pid, [])
            if detail and detail not in found[pid]:
                found[pid].append(detail)
    if isinstance(cell.out, _RowOutput):
        maps = shift_maps.get((cell.out.column, cell.out.step), {})
        for shift, detail in ((1, "the next row"), (-1, "the previous row")):
            if maps and _shift_reproduces(cell, maps, shift):
                found.setdefault("row_shift", []).append(detail)
    ordered = [p for p in PATHS if p in found]
    return ordered, {p: found[p] for p in ordered if found[p]}


def _finding(cell: _Cell, index: int, paths: list[str], details: dict) -> Finding:
    out = cell.out
    own = cell.own
    if isinstance(out, _RowOutput):
        rows = [r for r, o in zip(out.rows, own, strict=True) if o]
        comparable_rows = [r for r, c in zip(out.rows, cell.comparable, strict=True) if c]
        user = out.values[own]
        column, step, group = out.column, out.step, None
    else:
        rows, comparable_rows = [out.row], [out.row]
        user = np.array([out.value])
        column, step, group = out.column, out.step, out.group
    expected, tol = cell.expected[own], cell.tol[own]
    gaps = user - expected
    worst = int(np.argmax(np.abs(gaps)))
    pattern = None
    if len(gaps) > 1:
        pattern = "constant" if float(gaps.max() - gaps.min()) <= 2 * float(tol.max()) else "varies"
    rel = None
    if expected[worst] != 0 and math.isfinite(expected[worst]):
        rel = float(user[worst] / expected[worst] - 1)
    status: FindingStatus = (
        "explained" if len(paths) == 1 else "ambiguous" if len(paths) > 1 else "unexplained"
    )
    first = rows[0]
    return Finding(
        id=f"sheet_check_{index}",
        column=column_letter(column),
        step=step,
        gene=cell.gene,
        group=group,
        rows=rows,
        first_row=first,
        onwards=rows == [r for r in comparable_rows if r >= first],
        status=status,
        paths=paths,
        path_details=details,
        path_kinds={p: PATHS[p].kind for p in paths},
        user_value=_r(user[0]),
        expected_value=_r(expected[0]),
        gap=_r(gaps[worst]),
        gap_relative=_r(rel),
        gap_pattern=pattern,
    )


def _r(value: float | None) -> float | None:
    """A float kept to :data:`SIGNIFICANT` digits (byte-stable JSON); ``None`` if not finite."""
    if value is None:
        return None
    value = float(value)
    return float(f"{value:.{SIGNIFICANT}g}") if math.isfinite(value) else None


# ---------------------------------------------------------------------------------------------
# Hand-over to the engine's method
# ---------------------------------------------------------------------------------------------


def _engine_gene(gene: str, contrasts: Mapping[str, ContrastResult]) -> str | None:
    if gene in contrasts:
        return gene
    found = [k for k in sorted(contrasts) if _same_gene(k, gene)]
    return found[0] if len(found) == 1 else None


def _hand_overs(sheet: _Sheet, evals, findings, columns, study, engine_groups, notes):
    if study is None:
        return []
    if isinstance(study, StudyResult):
        contrasts, rule = study.contrasts, ConclusionRule(**study.conclusion_rule)
        engine_refs: tuple[str, ...] | None = tuple(study.design.refs_primary)
    else:
        contrasts, rule, engine_refs = dict(study), DEFAULT_RULE, None
    index = sheet.group_index
    control = next((g.index for g in sheet.groups if g.control), 0)
    if engine_groups is not None:
        first, second = (index.get(label.strip(), 0) for label in engine_groups)
    elif len(index) == 2 and control:
        first, second = next(i for i in index.values() if i != control), control
    else:
        first = second = 0
    if not first or not second:
        notes.append("The engine's groups could not be matched to the sheet's; no hand-over.")
        return []
    differing = {f.gene for f in findings}
    reproduced = {c.gene for c in columns if c.status == "reproduced"}
    out = []
    unmatched = 0
    for ev in evals:
        chain = ev.chain
        if not chain.refs or chain.gene in differing or chain.gene not in reproduced:
            continue
        name = _engine_gene(chain.gene, contrasts)
        if name is None:
            unmatched += 1
            continue
        engine = contrasts[name]
        d = ev.e2e.unit["dcq"]
        a, b = d[chain.unit_group == first], d[chain.unit_group == second]
        log2fc = -(_mean(a) - _mean(b))
        if not math.isfinite(log2fc):
            continue
        if abs(log2fc - engine.log2fc) <= math.log2(1 + REL_TOL):
            continue
        p = _p(-a, -b, False)
        sheet_call = conclude(log2fc, p, rule) if math.isfinite(p) else None
        causes: list[Literal["efficiency", "normaliser", "sample_set"]] = ["efficiency"]
        if engine_refs is not None:
            mine = {normalise_assay_name(r).casefold() for r in chain.refs}
            theirs = {normalise_assay_name(r).casefold() for r in engine_refs}
            if mine != theirs:
                causes.append("normaliser")
        n_a, n_b = int(np.isfinite(a).sum()), int(np.isfinite(b).sum())
        if (n_a, n_b) != (engine.n_hi, engine.n_lo):
            causes.append("sample_set")
        see = ["robustness_grid"] + (["card_refset"] if "normaliser" in causes else [])
        out.append(
            HandOver(
                gene=chain.gene,
                engine_gene=name,
                sheet_fc=_r(2.0**log2fc),
                engine_fc=_r(engine.fc),
                ratio=_r(engine.fc / 2.0**log2fc),
                sheet_conclusion=sheet_call,
                engine_conclusion=engine.conclusion,
                conclusion_differs=sheet_call != engine.conclusion,
                causes=causes,
                see=see,
            )
        )
    if unmatched:
        notes.append("Genes with no counterpart in the engine's result were not compared with it.")
    return out


# ---------------------------------------------------------------------------------------------
# Facts and the result
# ---------------------------------------------------------------------------------------------

CAUSE_LABELS = {
    "efficiency": "each well's own amplification efficiency in the engine",
    "normaliser": "another set of reference genes",
    "sample_set": "other group sizes",
}
CONVENTIONS = {
    "dcq": "ΔCq written as reference minus target",
    "ddcq": "ΔΔCq with the sign opposite to the textbook",
    "mean_dcq": "group ΔCq with the sign opposite to the textbook",
    "mean_ddcq": "group ΔΔCq with the sign opposite to the textbook",
}


def _group_word(group: int | None, groups: Sequence[GroupInfo]) -> str:
    if group is None:
        return "every group"
    info = next((g for g in groups if g.index == group), None)
    return "the control group" if info is not None and info.control else f"group {group}"


def _path_label(paths: Sequence[str], details: Mapping[str, Sequence[str]]) -> str:
    parts = []
    for p in paths:
        label = PATHS[p].label
        if details.get(p):
            detail = ", ".join(details[p])
            label = f"{label[:-1]}; {detail})" if label.endswith(")") else f"{label} ({detail})"
        parts.append(label)
    return " or ".join(parts)


def _build_facts(result: dict[str, Any]) -> dict[str, Fact]:
    reg = FactRegistry()

    def add(fid: str, value: Any, fmt: str = "{}", unit: str = "", path: str = "") -> None:
        if value is None or (isinstance(value, float) and not math.isfinite(value)):
            return
        if isinstance(value, str) and not value:
            return
        reg.add(Fact(id=fid, value=value, fmt=fmt, unit=unit, path=path))

    summary: Summary = result["summary"]
    count = "{:,}"
    add("f_sc_mapping_status", summary.mapping, path="mapping_status")
    add("f_sc_layout", result["layout"], path="layout")
    add("f_sc_n_rows", result["n_rows"], count, path="n_rows")
    add("f_sc_n_groups", len(result["groups"]), count, path="groups")
    add("f_sc_n_genes", len(result["genes"]), count, path="genes")
    add("f_sc_n_references", len(result["mapping"].references), count, path="mapping.references")
    confidences = [c.confidence for c in result["mapping"].columns]
    if confidences:
        add("f_sc_mapping_min_confidence", min(confidences), "{:.2f}", path="mapping.columns")
    for name in (
        "n_fold_changes",
        "n_reproduced",
        "n_differ",
        "n_named",
        "n_ambiguous",
        "n_unexplained",
        "n_columns_checked",
        "n_columns_reproduced",
        "n_findings",
        "n_hand_overs",
        "n_symbol_flags",
    ):
        short = {
            "n_fold_changes": "n_fc",
            "n_reproduced": "n_fc_reproduced",
            "n_differ": "n_fc_differ",
            "n_named": "n_fc_named",
            "n_ambiguous": "n_fc_ambiguous",
            "n_unexplained": "n_fc_unexplained",
        }.get(name, name)
        add(f"f_sc_{short}", getattr(summary, name), count, path=f"summary.{name}")
    groups = result["groups"]
    for k, finding in enumerate(result["findings"], start=1):
        p, at = f"f_sc_{k}", f"findings[{k - 1}]"
        add(f"{p}_step", STEP_LABELS[finding.step], path=f"{at}.step")
        add(f"{p}_column", finding.column, path=f"{at}.column")
        add(f"{p}_gene", finding.gene or "gene not identified", path=f"{at}.gene")
        add(f"{p}_group", _group_word(finding.group, groups), path=f"{at}.group")
        add(f"{p}_first_row", finding.first_row, path=f"{at}.first_row")
        add(f"{p}_last_row", finding.rows[-1], path=f"{at}.rows")
        add(f"{p}_n_rows", len(finding.rows), count, path=f"{at}.rows")
        add(f"{p}_onwards", "onwards" if finding.onwards else "in places", path=f"{at}.onwards")
        add(f"{p}_status", finding.status, path=f"{at}.status")
        if finding.paths:
            add(f"{p}_path", _path_label(finding.paths, finding.path_details), path=f"{at}.paths")
        add(f"{p}_user", finding.user_value, "{:.4g}", path=f"{at}.user_value")
        add(f"{p}_expected", finding.expected_value, "{:.4g}", path=f"{at}.expected_value")
        add(f"{p}_gap", finding.gap, "{:.3g}", path=f"{at}.gap")
        if finding.gap_relative is not None:
            add(
                f"{p}_gap_pct", finding.gap_relative * 100, "{:.1f}", "%", path=f"{at}.gap_relative"
            )
        finding.facts = sorted(fid for fid in reg.ids() if fid.startswith(f"{p}_"))
    used: set[str] = set()
    for k, ho in enumerate(result["hand_overs"]):
        g = slug(ho.gene)
        if g in used:  # two names with one slug ("MYCN(4)", "MYCN_4"): keep both apart
            g = f"{g}_{k + 1}"
        used.add(g)
        p, at = f"f_sc_ho_{g}", f"hand_overs[{k}]"
        add(f"{p}_gene", ho.gene, path=f"{at}.gene")
        add(f"{p}_sheet_fc", ho.sheet_fc, "{:.3g}", "×", path=f"{at}.sheet_fc")
        add(f"{p}_engine_fc", ho.engine_fc, "{:.3g}", "×", path=f"{at}.engine_fc")
        add(f"{p}_ratio", ho.ratio, "{:.3g}", "×", path=f"{at}.ratio")
        add(f"{p}_sheet_call", ho.sheet_conclusion or "no call", path=f"{at}.sheet_conclusion")
        add(f"{p}_engine_call", ho.engine_conclusion, path=f"{at}.engine_conclusion")
        add(f"{p}_causes", " and ".join(CAUSE_LABELS[c] for c in ho.causes), path=f"{at}.causes")
        ho.facts = sorted(fid for fid in reg.ids() if fid.startswith(f"{p}_"))
    flagged = [(i, g) for i, g in enumerate(result["genes"]) if g.flagged]
    for k, (i, gene) in enumerate(flagged, start=1):
        p, at = f"f_sc_sym_{k}", f"genes[{i}]"
        add(f"{p}_cell", gene.cell, path=f"{at}.cell")
        add(f"{p}_status", gene.status.replace("_", " "), path=f"{at}.status")
        add(f"{p}_candidates", ", ".join(gene.candidates) or "none", path=f"{at}.candidates")
    return reg.as_dict()


def _fold_change_counts(cells: Sequence[_Cell]) -> dict[str, int]:
    """Count the sheet's fold changes (one per unit, row or group value) and their causes.

    A fold change that differs is put down to the finding at that cell, or else to the
    earliest finding of the same gene at an earlier step (the difference it inherits).
    """
    counts = dict.fromkeys(("n", "reproduced", "named", "ambiguous", "unexplained"), 0)
    by_gene: dict[str, list[_Cell]] = {}
    for cell in cells:
        by_gene.setdefault(cell.gene, []).append(cell)
    for cell in cells:
        out = cell.out
        if out.step not in ("fc", "mean_fc"):
            continue
        upstream = [
            c.finding
            for c in by_gene[cell.gene]
            if c.finding is not None and STEP_ORDER.index(c.out.step) < STEP_ORDER.index(out.step)
        ]
        upstream.sort(key=lambda f: (STEP_ORDER.index(f.step), _letter_index(f.column)))
        inherited = upstream[0] if upstream else None
        items: list[tuple[bool, bool]] = []  # (reproduced, differs on its own)
        if isinstance(out, _RowOutput):
            seen: set[int] = set()
            for i in range(len(out.rows)):
                if not cell.comparable[i]:
                    continue
                if cell.granularity == "unit":
                    if int(cell.units[i]) in seen:
                        continue
                    seen.add(int(cell.units[i]))
                items.append((bool(cell.reproduced[i]), bool(cell.own[i])))
        elif cell.comparable[0]:
            items.append((bool(cell.reproduced[0]), bool(cell.own[0])))
        for ok, own in items:
            counts["n"] += 1
            cause = cell.finding if own else inherited
            if ok:
                counts["reproduced"] += 1
            elif cause is None or cause.status == "unexplained":
                counts["unexplained"] += 1
            else:
                counts["named"] += 1
                counts["ambiguous"] += cause.status == "ambiguous"
    return counts


def _check_efficiencies(efficiencies: Mapping[str, float] | None) -> dict[str, float]:
    out = {}
    for gene, value in (efficiencies or {}).items():
        e = float(value)
        if not EFFICIENCY_MIN < e <= EFFICIENCY_MAX:
            raise SheetCheckError(
                f"efficiency for {gene!r} must be an amplification factor per cycle between "
                f"{EFFICIENCY_MIN:g} and {EFFICIENCY_MAX:g} (2.0 = 100 %), not {e:g}"
            )
        out[str(gene)] = e
    return out


def check_sheet(
    path: str | Path,
    mapping: ColumnMapping | None = None,
    *,
    efficiencies: Mapping[str, float] | None = None,
    study: StudyResult | Mapping[str, ContrastResult] | None = None,
    engine_groups: tuple[str, str] | None = None,
) -> SheetCheckResult:
    """Recompute a ΔΔCq analysis sheet from its own Cq values and name what differs.

    Args:
        path: The sheet (``.xlsx``, ``.xlsm``, ``.csv``, ``.tsv`` or ``.txt``); never edited.
        mapping: The column mapping; guessed with :func:`guess_mapping` when ``None``. Results
            say :data:`MAPPING_GUESSED` until a mapping with ``confirmed=True`` is passed.
        efficiencies: Gene key -> amplification factor per cycle (2.0 = 100 %), for the Pfaffl
            path; references without one are taken as 2.0.
        study: qPilot's own result for the same study (a :class:`~qpilot.schemas.StudyResult`
            or its contrasts); genes whose sheet arithmetic reproduces but whose engine answer
            differs become hand-overs.
        engine_groups: The sheet's labels of the engine's first group and its comparison group;
            default: the one non-control group against the control group.

    Returns:
        The :class:`SheetCheckResult`.

    Raises:
        SheetCheckError: The sheet is unreadable, over a size cap, holds formulas without saved
            values, has no Cq table, or the mapping does not fit it.
    """
    with np.errstate(**_QUIET):
        return _check(path, mapping, efficiencies, study, engine_groups)


def _check(path, mapping, efficiencies, study, engine_groups) -> SheetCheckResult:
    read, kind, missing = _read(path)
    eff = _check_efficiencies(efficiencies)
    if mapping is None:
        mapping, grid = _guess(read, missing, None)
    else:
        grids = _grids(read)
        if not 1 <= mapping.sheet <= len(grids):
            raise SheetCheckError(f"the workbook has no sheet {mapping.sheet}")
        grid = grids[mapping.sheet - 1]
        if missing.get(grid.title):
            raise SheetCheckError(FORMULA_REFUSAL)
        mapping = mapping.model_copy(deep=True)
    sheet = _extract(grid, mapping, kind, eff)
    evals = [_evaluate(chain, sheet) for chain in sheet.chains]
    cells: list[_Cell] = []
    for ev in evals:
        for out in sheet.row_outputs.get(ev.chain.gene, []):
            cells.append(_compare_row(ev, out))
        if ev.chain.refs:
            for item in sheet.group_outputs.get(ev.chain.gene, []):
                cells.append(_compare_group(ev, item))
    # column-wide textbook values, for copy-paste offsets
    shift_maps: dict[tuple[int, str], dict[int, dict[int, float]]] = {}
    for ev, cell in ((ev, c) for ev in evals for c in cells if c.gene == ev.chain.gene):
        out = cell.out
        if not isinstance(out, _RowOutput):
            continue
        maps = shift_maps.setdefault((out.column, out.step), {0: {}, 1: {}})
        for slot, values in ((0, ev.e2e), (1, ev.anch)):
            e, _ = _expected(values, out.step, ev.chain, out, cell.granularity)
            maps[slot].update(zip(out.rows, (float(x) for x in e), strict=True))
    by_gene = {ev.chain.gene: ev for ev in evals}
    cache: dict[int, Any] = {}
    order = sorted(
        range(len(cells)),
        key=lambda i: (
            STEP_ORDER.index(cells[i].out.step),
            cells[i].out.column,
            [c.gene for c in sheet.chains].index(cells[i].gene),
            getattr(cells[i].out, "group", 0),
            getattr(cells[i].out, "row", 0),
        ),
    )
    findings: list[Finding] = []
    for i in order:
        cell = cells[i]
        if not cell.own.any():
            continue
        paths, details = _classify(cell, by_gene[cell.gene], shift_maps, cache)
        cell.finding = _finding(cell, len(findings) + 1, paths, details)
        findings.append(cell.finding)
    columns = [_column_check(cells[i]) for i in order] + sheet.skipped
    for f in findings:  # downstream columns of the same gene that inherit the difference
        f.followed_by = [
            f"{c.column}:{c.step}"
            for c in columns
            if c.gene == f.gene
            and c.status == "follows"
            and STEP_ORDER.index(c.step) > STEP_ORDER.index(f.step)
        ]
    localisation = []
    for chain in sheet.chains:
        first = next((f for f in findings if f.gene == chain.gene), None)
        if first is not None:
            localisation.append(
                Localisation(
                    gene=first.gene,
                    column=first.column,
                    step=first.step,
                    first_row=first.first_row,
                    onwards=first.onwards,
                    finding=first.id,
                )
            )
    localisation.sort(key=lambda loc: (STEP_ORDER.index(loc.step), _letter_index(loc.column)))
    notes = list(sheet.notes)
    hand_overs = _hand_overs(sheet, evals, findings, columns, study, engine_groups, notes)
    fc = _fold_change_counts([cells[i] for i in order])
    checked = [c for c in columns if c.status != "not_checked"]
    summary = Summary(
        mapping=mapping.status,
        n_fold_changes=fc["n"],
        n_reproduced=fc["reproduced"],
        n_differ=fc["n"] - fc["reproduced"],
        n_named=fc["named"],
        n_ambiguous=fc["ambiguous"],
        n_unexplained=fc["unexplained"],
        n_columns_checked=len(checked),
        n_columns_reproduced=sum(1 for c in checked if c.status == "reproduced"),
        n_findings=len(findings),
        n_hand_overs=len(hand_overs),
        n_symbol_flags=sum(1 for g in sheet.genes if g.flagged),
    )
    view = mapping.model_copy(update={"control_group": None})
    if view.control_text_id is None:
        control = next((g for g in sheet.groups if g.control), None)
        view.control_text_id = control.text_id if control else None
    parts: dict[str, Any] = {
        "summary": summary,
        "layout": mapping.layout,
        "n_rows": sheet.n_rows,
        "groups": sheet.groups,
        "genes": sheet.genes,
        "mapping": view,
        "findings": findings,
        "localisation": localisation,
        "hand_overs": hand_overs,
    }
    facts = _build_facts(parts)
    return SheetCheckResult(
        file_sha256=read.sha256,
        file_kind=kind,  # type: ignore[arg-type]
        mapping=view,
        mapping_status=mapping.status,
        layout=mapping.layout,
        n_rows=sheet.n_rows,
        groups=sheet.groups,
        genes=sheet.genes,
        columns=columns,
        findings=findings,
        localisation=localisation,
        summary=summary,
        hand_overs=hand_overs,
        notes=notes,
        facts=facts,
    )


def _column_check(cell: _Cell) -> ColumnCheck:
    out = cell.out
    n_cells = int(cell.comparable.sum())
    status: ColumnStatus
    if cell.own.any():
        status = "differs"
    elif cell.follows.any():
        status = "follows"
    elif n_cells:
        status = "reproduced"
    else:
        status = "not_checked"
    user = out.values if isinstance(out, _RowOutput) else np.array([out.value])
    convention = CONVENTIONS.get(out.step) if cell.sign < 0 else None
    return ColumnCheck(
        column=column_letter(out.column),
        step=out.step,
        gene=cell.gene,
        status=status,
        n_cells=n_cells,
        n_reproduced=int(cell.reproduced.sum()),
        n_follow=int(cell.follows.sum()),
        n_differ=int(cell.own.sum()),
        n_not_comparable=int((np.isfinite(user) & ~cell.comparable).sum()),
        granularity=cell.granularity,  # type: ignore[arg-type]
        convention=convention,
        variant=cell.variant,
        finding=cell.finding.id if cell.finding else None,
        reason=None if n_cells else "no value here can be recomputed from the sheet's Cq values",
    )


def check_sheet_store(
    store: Any,
    study_id: str,
    path: str | Path,
    mapping: ColumnMapping | None = None,
    *,
    efficiencies: Mapping[str, float] | None = None,
    engine_groups: tuple[str, str] | None = None,
) -> SheetCheckResult:
    """:func:`check_sheet` against a stored study's results (read-only; nothing is written).

    Args:
        store: A :class:`~qpilot.core.store.StudyStore` (anything with ``get(study_id)``).
        study_id: The stored study the sheet analyses.
        path: The sheet.
        mapping: As for :func:`check_sheet`.
        efficiencies: As for :func:`check_sheet`.
        engine_groups: As for :func:`check_sheet`.
    """
    return check_sheet(
        path,
        mapping,
        efficiencies=efficiencies,
        study=store.get(study_id),
        engine_groups=engine_groups,
    )


__all__ = [
    "CARD_KIND",
    "MAPPING_CONFIRMED",
    "MAPPING_GUESSED",
    "METHOD_CARD",
    "PATHS",
    "REL_TOL",
    "Anchor",
    "Anchors",
    "Chain",
    "ColumnCheck",
    "ColumnGuess",
    "ColumnMapping",
    "Finding",
    "GeneInfo",
    "GroupInfo",
    "HandOver",
    "Localisation",
    "PathInfo",
    "PathValues",
    "SheetCheckError",
    "SheetCheckResult",
    "Summary",
    "arith_mean_fc",
    "check_sheet",
    "check_sheet_store",
    "exponent_twice",
    "guess_mapping",
    "livak_per_unit",
    "no_reference",
    "pfaffl",
    "row_shift",
    "sign_inverted",
    "stats_on_fc",
    "wells_as_n",
    "wrong_reference",
]
