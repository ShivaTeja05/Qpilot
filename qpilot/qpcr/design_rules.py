"""Deterministic design proposers: what plain rules can read from names, types and sheets.

The AI interpreter (``qpilot/ai/interpret.py``) merges these with the model's reply and falls
back to them when no model is available. Every field cites the ``text_id``s (and sheet cells)
it used and carries a level with reasons in qPilot's own words; no file text is copied into a
reason. Nothing here is a decision: each field becomes a proposal that only a person accepts.

Rules, in the order they run:

* **Declared types.** A sample the file declares as anything but ``unkn`` is proposed with that
  role (``High``). Declared controls (``ntc``, ``nrt``, ``nac``) always stay controls: no rule
  here proposes a non-control role for them, and the hard ban in
  :mod:`qpilot.qpcr.design_checks` refuses it from anyone.
* **Vendor task names** in a sheet's type column (QuantStudio ``UNKNOWN``/``NTC``/``STANDARD``,
  CFX ``Unknown``/``Standard``/``NTC``/``NRT``/``Positive Control``/``Negative Control`` and
  ``Unkn-01``-style content, LightCycler ``Target Unknown``/``Target Negative``, core-facility
  ``UNKN``/``STND``/``NTC``) map to RDML roles.
* **Control names** (NTC, water, H2O, blank, no template, NRT, -RT, noRT, NAC, no amp, ...;
  case and separator tolerant, at most four words) on a sample declared ``unkn``.
* **Dilution series** from name patterns (``comp_XX_conc_Y``, ``STD_15``, ``Std 1:10``,
  ``1e5 copies``) or a sheet quantity column (``S1``...``S6``): one ``design.dilution_series``
  per series and experiment, with at least three levels. A concentration, input amount or
  dilution column describes every sample (an RNA concentration is not a standard's quantity),
  so it counts only for samples the file or the sheet's type column marks as standards. A
  quantity column counts for an unmarked sample only when the levels step like a dilution and
  the sheet gives the sample no group or biological unit (then it is a study sample).
* **Sheet columns**: ``design.group`` from a group column; ``design.bio_unit`` only from an
  explicit unit column (animal, mouse, patient, donor, subject, biological replicate). A name
  pattern alone (``WT1a``/``WT1b``, ``M3_cDNA1``/``M3_cDNA2``) gives a ``Low`` proposal that
  says so; biological units are never inferred from name similarity with any confidence.
* **Targets**: a declared ``ref`` target gives ``design.target_role``; the HGNC gate
  (:mod:`qpilot.io.symbols`) gives ``design.gene_symbol`` (ambiguous and date-mangled names
  list every candidate).
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from qpilot.io.sheets import SheetRead, SheetTable, sheet_table, squash
from qpilot.io.symbols import check_symbol
from qpilot.qpcr.curves import safe_name
from qpilot.schemas_studio import (
    CONTROL_ROLES,
    DesignField,
    InspectSample,
    InspectSummary,
    QuarantineEntry,
)

if TYPE_CHECKING:
    from qpilot.qpcr.inspect import FileFacts

MIN_SERIES_LEVELS = 3
MAX_CONTROL_WORDS = 4

# ---------------------------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------------------------

#: Squashed vendor task / sample-type text -> RDML role.
VENDOR_TASKS: dict[str, str] = {
    # unknowns
    "unknown": "unkn",
    "unkn": "unkn",
    "unk": "unkn",
    "targetunknown": "unkn",
    "refunknown": "unkn",
    "sample": "unkn",
    # standards
    "standard": "std",
    "std": "std",
    "stnd": "std",
    "stds": "std",
    "targetstandard": "std",
    "refstandard": "std",
    "standardcurve": "std",
    # no-template controls
    "ntc": "ntc",
    "notemplatecontrol": "ntc",
    "notemplate": "ntc",
    "targetnegative": "ntc",
    "refnegative": "ntc",
    "negativentc": "ntc",
    "water": "ntc",
    "h2o": "ntc",
    "blank": "ntc",
    # no-RT controls
    "nrt": "nrt",
    "nort": "nrt",
    "minusrt": "nrt",
    "rtminus": "nrt",
    "noreversetranscriptase": "nrt",
    "noreversetranscription": "nrt",
    "rtnegative": "nrt",
    "rtneg": "nrt",
    # no-amplification controls
    "nac": "nac",
    "noamp": "nac",
    "noamplification": "nac",
    "noamplificationcontrol": "nac",
    # positive controls
    "pos": "pos",
    "positive": "pos",
    "positivecontrol": "pos",
    "posctrl": "pos",
    "poscontrol": "pos",
    "targetpositive": "pos",
    "refpositive": "pos",
    # no-target-present (a negative biological sample), and optical calibrators
    "negativecontrol": "ntp",
    "negctrl": "ntp",
    "negcontrol": "ntp",
    "ntp": "ntp",
    "notargetpresent": "ntp",
    "opt": "opt",
}
#: Squashed vendor wording that fits two roles -> the other plausible role (an alternative).
AMBIGUOUS_TASKS: dict[str, str] = {"negativecontrol": "ntc", "negctrl": "ntc", "negcontrol": "ntc"}

#: Control phrases in sample names (as lists of lowercase words) -> role.
CONTROL_PHRASES: dict[tuple[str, ...], str] = {
    ("ntc",): "ntc",
    ("water",): "ntc",
    ("h2o",): "ntc",
    ("blank",): "ntc",
    ("no", "template"): "ntc",
    ("no", "template", "control"): "ntc",
    ("notemplate",): "ntc",
    ("nrt",): "nrt",
    ("nort",): "nrt",
    ("minusrt",): "nrt",
    ("no", "rt"): "nrt",
    ("minus", "rt"): "nrt",
    ("rt", "neg"): "nrt",
    ("rt", "negative"): "nrt",
    ("no", "reverse", "transcriptase"): "nrt",
    ("nac",): "nac",
    ("no", "amp"): "nac",
    ("noamp",): "nac",
    ("no", "amplification"): "nac",
    ("no", "amplification", "control"): "nac",
}
_MINUS_RT = (
    re.compile(r"(?<![a-z0-9])[-−–]\s*rt(?![a-z0-9])"),
    re.compile(r"(?<![a-z0-9])rt\s*[-−–](?![a-z0-9])"),
)

_NUM = r"(?:\d+(?:[.,]\d+)?\s*[x×*]\s*10\^\s*-?\d+|10\^\s*-?\d+|\d+(?:\.\d+)?(?:e[+-]?\d+)?)"
SERIES_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "named_quantity",  # comp_00_conc_0.0625, mix-A dil 4 (a dilution factor)
        re.compile(
            r"^(?P<series>.*?[a-z0-9].*?)[\s_\-.]+(?P<word>conc|concentration|dil|dilution|qty|"
            r"quantity|copies|cp)[\s_\-.]*(?P<q>" + _NUM + r")$",
            re.IGNORECASE,
        ),
    ),
    (
        "ratio",  # Std 1:10, dil 1/1000
        re.compile(
            r"^(?P<series>.*?)[\s_\-.]*1\s*[:/]\s*(?P<q>" + _NUM + r")$",
            re.IGNORECASE,
        ),
    ),
    (
        "copies",  # 1e5 copies, std 10^4 cp
        re.compile(
            r"^(?P<series>.*?)[\s_\-.]*(?P<q>" + _NUM + r")\s*(?:copies|copy|cps|cp)$",
            re.IGNORECASE,
        ),
    ),
    (
        "standard",  # STD_15, STDA15000, Standard 3
        re.compile(
            r"^(?P<series>std[a-z]?|stnd|standard|stds)[\s_\-.]*(?P<q>" + _NUM + r")$",
            re.IGNORECASE,
        ),
    ),
)
_INDEX_NAME = re.compile(r"^(?P<series>[a-z]{1,8})[\s_\-.]*(?P<q>\d{1,3})$", re.IGNORECASE)
_TECH_MARKER = re.compile(
    r"^(?P<base>.+?)[\s_\-.]*(?:cdna|tr|techrep|tech|rtrep)[\s_\-.]*\d+$", re.IGNORECASE
)
_LETTER_SUFFIX = re.compile(r"^(?P<base>.*\d)(?P<letter>[a-d])$", re.IGNORECASE)


def parse_number(text: str) -> float | None:
    """``"0.0625"``, ``"1e5"``, ``"1x10^5"``, ``"10^4"`` or ``"1,5"`` -> a float (else ``None``)."""
    value = text.strip().lower().replace(" ", "").replace("×", "x").replace("*", "x")
    try:
        if "^" in value:
            mantissa, _, exponent = value.partition("x10^") if "x10^" in value else ("1", "", "")
            if not exponent:
                exponent = value.split("^", 1)[1]
            return float(mantissa.replace(",", ".")) * 10 ** float(exponent)
        return float(value.replace(",", "."))
    except (ValueError, OverflowError):  # OverflowError: a power of ten too large for a float
        return None


def _dilution(text: str) -> float | None:
    """A dilution as the fraction of the stock it holds: ``10`` and ``1:10`` are a tenth.

    A plain number above one is a dilution factor; one of at most one is already a fraction.
    """
    ratio = re.fullmatch(r"\s*1\s*[:/]\s*(.+)", text)
    value = parse_number(ratio.group(1) if ratio else text)
    if value is None or not math.isfinite(value) or value <= 0:
        return None
    return 1.0 / value if ratio or value > 1 else value


def vendor_task_role(text: str) -> str | None:
    """The RDML role a vendor task or sample-type text names, or ``None``.

    Tolerates case, separators and CFX replicate numbering (``Unkn-01``, ``Std-02``).
    """
    key = squash(re.sub(r"[\s_\-]*\d+$", "", text.strip()))
    return VENDOR_TASKS.get(key)


def control_role_from_name(name: str) -> str | None:
    """The control role a sample name reads as, or ``None``.

    A name counts only when it has at most four words and the control phrase is at its start
    or end (``NTC``, ``water 2``, ``MYCN NTC``, ``comp_50_NTC``, ``-RT``, ``no RT``); a sentence
    that merely contains "NTC" is a name like any other.
    """
    text = name.strip().lower()
    for pattern in _MINUS_RT:
        text = pattern.sub(" minusrt ", text)
    words = [w for w in re.split(r"[^a-z0-9]+", text) if w]
    if not words or len(words) > MAX_CONTROL_WORDS:
        return None
    for phrase, role in sorted(CONTROL_PHRASES.items(), key=lambda kv: -len(kv[0])):
        n = len(phrase)
        if tuple(words[:n]) == phrase or tuple(words[-n:]) == phrase:
            rest = words[n:] if tuple(words[:n]) == phrase else words[:-n]
            if all(len(w) <= 8 for w in rest):
                return role
    return None


# ---------------------------------------------------------------------------------------------
# Dilution series
# ---------------------------------------------------------------------------------------------


@dataclass
class Series:
    """One dilution series found in the file or sheet.

    Attributes:
        subject: The series name used as the proposal subject (a safe identifier).
        experiment_id: The experiment its wells are in.
        samples: Safe sample id -> quantity.
        family: Series made by the same naming scheme in one experiment share a family
            (``comp_00`` ... ``comp_50``); the design checks pool amplification by level
            across a family.
        source: ``file`` (declared standards with quantities), ``name`` or ``sheet``.
        cites: ``text_id``s and sheet cells used.
        name_quantities: Quantities read from the names when the file's own differ.
    """

    subject: str
    experiment_id: str
    samples: dict[str, float]
    family: str
    source: str
    cites: list[str] = field(default_factory=list)
    name_quantities: dict[str, float] = field(default_factory=dict)


def _series_name_match(name: str) -> tuple[str, str, float] | None:
    """(series key, family key, quantity) from a sample name, or ``None``."""
    for kind, pattern in SERIES_PATTERNS:
        match = pattern.match(name.strip())
        if not match:
            continue
        value = parse_number(match.group("q"))
        if value is None:
            continue
        series = match.group("series").strip(" _-.")
        word = match.groupdict().get("word") or kind
        if kind == "ratio" or word.lower() in ("dil", "dilution"):
            if value <= 0:
                continue
            value = 1.0 / value  # "1:10" and "dil 10" are dilution factors: one tenth
        family = f"{kind}:{re.sub(r'[0-9]+', '#', series.lower())}:{word.lower()}"
        return series or kind, family, value
    return None


def _geometric(values: Iterable[float]) -> bool:
    """True when the distinct values step by one constant factor of at least 1.5.

    Missing levels are allowed (2-fold steps of 1, 2, 8 pass); tube numbers 1, 2, 3 do not.
    """
    levels = sorted(set(values))
    if len(levels) < MIN_SERIES_LEVELS or levels[0] <= 0:
        return False
    ratios = [b / a for a, b in zip(levels, levels[1:], strict=False)]
    step = min(ratios)
    if step < 1.5:
        return False
    for ratio in ratios:
        power = round(math.log(ratio) / math.log(step))
        if power < 1 or abs(math.log(ratio) - power * math.log(step)) > math.log(1.1):
            return False
    return True


def find_dilution_series(
    summary: InspectSummary,
    quarantine: Iterable[QuarantineEntry],
    *,
    facts: FileFacts | None = None,
) -> list[Series]:
    """Every dilution series the names, the sheet or the file's declared quantities describe.

    A series needs at least three distinct positive quantities in one experiment. Quantities
    come from, in order of preference: the file's declared quantities for declared standards
    (when ``facts`` is given), the sheet's quantity column, the sample names. Names that only
    number the samples (``Std 1``...``Std 6``, ``S1``...``S6``) need a sheet quantity column.

    A sheet quantity counts as a standard's only with evidence that the sample is one: the
    file declares it a standard, the sheet types it so, or its name reads as a dilution
    (:meth:`_SheetLookup.quantity`). Without such a mark a sample the sheet puts in a group or
    a biological unit is a study sample and joins no series, and the others form a series only
    when their levels step like a dilution (:func:`_geometric`), as names alone must: an
    ordinary per-sample amount (``RNA quantity`` 98.2, 110.7, 120.5) is no dilution series.
    """
    values = {entry.text_id: entry.value for entry in quarantine}
    sheet = _sheet_lookup(summary, values)
    declared_qty = _declared_quantities(facts) if facts is not None else {}
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for sample in summary.samples:
        if _declared_roles(sample) & CONTROL_ROLES:
            continue
        name = values.get(sample.text_id, sample.sample)
        match = _series_name_match(name)
        sheet_qty, sheet_ref, marked = sheet.quantity(sample, "std" in _declared_roles(sample))
        marked = marked or match is not None  # a name such as "Std 1:10" marks it too
        index = _INDEX_NAME.match(name.strip()) if match is None else None
        if match is not None:
            key, family, name_qty = match
        elif sheet_qty is not None and (marked or not sheet.study_sample(sample)):
            key = index.group("series") if index else "sheet_series"
            family, name_qty = f"sheet:{key.lower()}", None
        elif sample.sample in declared_qty and "std" in _declared_roles(sample):
            key, family, name_qty = "declared_standards", "declared", None
        else:
            continue
        for experiment in sample.experiments or [""]:
            slot = found.setdefault(
                (experiment, key),
                {
                    "family": family,
                    "members": {},
                    "cites": [],
                    "sources": set(),
                    "names": {},
                    "unmarked": False,
                },
            )
            quantity, source = name_qty, "name"
            if sample.sample in declared_qty:
                quantity, source = declared_qty[sample.sample], "file"
            elif sheet_qty is not None:
                quantity, source = sheet_qty, "sheet"
                slot["cites"].append(sheet_ref)
            if quantity is None or not math.isfinite(quantity) or quantity <= 0:
                continue
            slot["members"][sample.sample] = quantity
            slot["cites"].append(sample.text_id)
            slot["sources"].add(source)
            slot["unmarked"] |= source == "sheet" and not marked
            if name_qty is not None and name_qty != quantity:
                slot["names"][sample.sample] = name_qty
    out: list[Series] = []
    subjects: Counter[str] = Counter(key for _, key in found)
    for (experiment, key), slot in sorted(found.items()):
        members: dict[str, float] = slot["members"]
        if len(set(members.values())) < MIN_SERIES_LEVELS:
            continue
        sources = slot["sources"]
        loose = sources == {"name"} or slot["unmarked"]
        if loose and not _geometric(members.values()):
            continue  # "Std 1".."Std 6" number the tubes; ordinary amounts are no dilution
        subject = safe_name(key, "series")
        if subjects[key] > 1 and experiment:
            subject = safe_name(f"{key}@{experiment}", "series")
        out.append(
            Series(
                subject=subject,
                experiment_id=experiment,
                samples=dict(sorted(members.items(), key=lambda kv: kv[1])),
                family=f"{experiment}|{slot['family']}",
                source="file" if "file" in sources else ("sheet" if "sheet" in sources else "name"),
                cites=list(dict.fromkeys(slot["cites"])),
                name_quantities=slot["names"],
            )
        )
    return out


def _declared_quantities(facts: FileFacts) -> dict[str, float]:
    """Safe sample id -> the one quantity the file declares for it (any target)."""
    out = {}
    for sample, quantities in facts.sample_quantities.items():
        values = {value for value, _unit, _target in quantities}
        if len(values) == 1:
            out[sample] = values.pop()
    return out


# ---------------------------------------------------------------------------------------------
# Sheets
# ---------------------------------------------------------------------------------------------


class _SheetLookup:
    """The sample sheet's table, matched to the file's samples."""

    def __init__(self, table: SheetTable | None, rows_by_sample: dict[str, list[int]]) -> None:
        self.table = table
        self.rows_by_sample = rows_by_sample

    def rows(self, sample: InspectSample) -> list[tuple[dict[str, str], dict[str, str]]]:
        if self.table is None:
            return []
        return [
            (self.table.rows[i], self.table.refs[i])
            for i in self.rows_by_sample.get(sample.sample, [])
        ]

    def values(self, sample: InspectSample, column: str) -> list[tuple[str, str]]:
        """(value, cell ref) of one column over the sample's rows, non-empty only."""
        return [
            (row[column], refs[column]) for row, refs in self.rows(sample) if row.get(column, "")
        ]

    def quantity(
        self, sample: InspectSample, declared_std: bool = False
    ) -> tuple[float | None, str | None, bool]:
        """The sample's quantity as a standard, the cell it was read from, and whether it is marked.

        A sample is *marked* a standard when the file declares it one (``declared_std``) or the
        sheet's type column types it so; then a quantity (``Quantity``, ``Copies``, ``SQ``...),
        concentration, input amount or dilution column gives its quantity. An unmarked sample
        (no type in the sheet) gives only a quantity column, and :func:`find_dilution_series`
        takes it only when the levels step like a dilution and the sheet does not put the
        sample in a group or a biological unit (:meth:`study_sample`). A sample the sheet types
        as anything else gives none: an instrument's export also lists the quantity it computed
        for each unknown. A column that gives the sample more than one value gives none.
        """
        roles = {vendor_task_role(text) for text, _ in self.values(sample, "type")} - {None}
        standard = declared_std or roles == {"std"}
        columns = ["quantity"] if standard or not roles else []
        if standard:
            columns += ["concentration", "dilution"]
        for column in columns:
            read = _dilution if column == "dilution" else parse_number
            found = {read(v): ref for v, ref in self.values(sample, column)}
            found.pop(None, None)
            if found:
                value, ref = next(iter(found.items())) if len(found) == 1 else (None, None)
                return value, ref, standard
        return None, None, standard

    def study_sample(self, sample: InspectSample) -> bool:
        """Whether the sheet puts the sample in a group or a biological unit (a study sample).

        A cell that only names a sample type (``Standard``, ``NTC``) does not count.
        """
        return any(
            vendor_task_role(text) is None
            for column in ("group", "bio_unit", "bio_rep")
            for text, _ in self.values(sample, column)
        )


def _sheet_lookup(summary: InspectSummary, values: Mapping[str, str]) -> _SheetLookup:
    if not summary.sheet:
        return _SheetLookup(None, {})
    read = SheetRead(file_name="", sha256=summary.sheet_sha256 or "")
    for cell in summary.sheet:
        title = cell.cell.rsplit("!", 1)[0]
        if title not in read.sheets:
            read.sheets.append(title)
        read.cells.append(cell)
        read.values[cell.cell] = values.get(cell.text_id, "")
    table = sheet_table(read)
    if table is None:
        return _SheetLookup(None, {})
    exact: dict[str, str] = {}
    loose: dict[str, set[str]] = defaultdict(set)
    for sample in summary.samples:
        original = values.get(sample.text_id, sample.sample)
        exact.setdefault(original.strip(), sample.sample)
        exact.setdefault(sample.sample, sample.sample)
        loose[squash(original)].add(sample.sample)
    rows_by_sample: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(table.rows):
        text = row["sample"]
        match = exact.get(text)
        if match is None and len(loose.get(squash(text), ())) == 1:
            match = next(iter(loose[squash(text)]))
        if match is not None:
            rows_by_sample[match].append(index)
    return _SheetLookup(table, dict(rows_by_sample))


# ---------------------------------------------------------------------------------------------
# The proposer
# ---------------------------------------------------------------------------------------------


def _declared_roles(sample: InspectSample) -> set[str]:
    """Roles declared for every target (``pos@MYCN`` style per-target types are left out)."""
    return {label for label in sample.declared_type.split(",") if "@" not in label}


def is_declared_control(sample: InspectSample) -> bool:
    """True when every type the file declares for the sample is a control role."""
    labels = [label.split("@", 1)[0] for label in sample.declared_type.split(",") if label]
    return bool(labels) and all(label in CONTROL_ROLES for label in labels)


def propose_from_names(
    summary: InspectSummary,
    quarantine: Iterable[QuarantineEntry],
    *,
    facts: FileFacts | None = None,
) -> list[DesignField]:
    """Everything the deterministic rules can propose for a file (and its sample sheet).

    Args:
        summary: From :func:`qpilot.qpcr.inspect.inspect`.
        quarantine: The quarantine entries returned with it (names and sheet cells are read
            from here; nothing is copied into a reason).
        facts: Optional :class:`~qpilot.qpcr.inspect.FileFacts` for the same file; adds the
            file's declared standard quantities to dilution series.

    Returns:
        One :class:`~qpilot.schemas_studio.DesignField` per proposal, in a fixed order: well
        roles, dilution series, groups, biological units, target roles, gene symbols.
    """
    entries = list(quarantine)
    values = {entry.text_id: entry.value for entry in entries}
    sheet = _sheet_lookup(summary, values)
    fields: list[DesignField] = []
    controls: set[str] = set()

    # ---- well roles ----------------------------------------------------------------------
    series = find_dilution_series(summary, entries, facts=facts)
    in_series = {s for each in series for s in each.samples}
    for sample in summary.samples:
        role_field = _role_field(sample, values, sheet, sample.sample in in_series)
        if role_field is None:
            continue
        fields.append(role_field)
        if role_field.value["role"] in CONTROL_ROLES:
            controls.add(sample.sample)
    for sample in summary.samples:
        if is_declared_control(sample):
            controls.add(sample.sample)

    # ---- dilution series -----------------------------------------------------------------
    for each in series:
        level, reasons = _series_level(each)
        alternatives = []
        if each.name_quantities:
            alternatives.append(
                {
                    "experiment_id": each.experiment_id,
                    "samples": {**each.samples, **each.name_quantities},
                }
            )
            reasons.append("the names suggest other quantities; they are listed as an alternative")
        fields.append(
            DesignField(
                kind="design.dilution_series",
                subject=each.subject,
                value={"experiment_id": each.experiment_id, "samples": each.samples},
                cites=each.cites,
                alternatives=alternatives,
                level=level,
                reasons=reasons,
            )
        )

    # ---- groups and biological units -----------------------------------------------------
    explicit_units: set[str] = set()
    for sample in summary.samples:
        if sample.sample in controls or sample.sample in in_series:
            continue
        group = _column_field(sample, sheet, "group", "design.group", "group")
        if group is not None:
            fields.append(group)
        unit = _unit_field(sample, sheet)
        if unit is not None:
            fields.append(unit)
            explicit_units.add(sample.sample)
    fields.extend(_pattern_units(summary, values, controls | in_series | explicit_units))

    # ---- targets -------------------------------------------------------------------------
    for target in summary.targets:
        if target.declared_type == "ref":
            fields.append(
                DesignField(
                    kind="design.target_role",
                    subject=target.target,
                    value={"role": "ref"},
                    cites=[target.text_id],
                    level="High",
                    reasons=["the file declares this target as a reference gene"],
                )
            )
    for target in summary.targets:
        symbol = _symbol_field(target.target, target.text_id, values)
        if symbol is not None:
            fields.append(symbol)
    return fields


def _role_field(
    sample: InspectSample,
    values: Mapping[str, str],
    sheet: _SheetLookup,
    in_series: bool,
) -> DesignField | None:
    """The role proposal for one sample, or ``None`` when the declared ``unkn`` stands."""
    declared = _declared_roles(sample)
    name = values.get(sample.text_id, sample.sample)
    sheet_roles: dict[str, list[str]] = defaultdict(list)
    ambiguous_alt: str | None = None
    for text, ref in sheet.values(sample, "type"):
        role = vendor_task_role(text)
        if role is not None:
            sheet_roles[role].append(ref)
            ambiguous_alt = ambiguous_alt or AMBIGUOUS_TASKS.get(squash(text))
    cites = [sample.text_id]
    if is_declared_control(sample) or (declared and declared != {"unkn"}):
        role = sorted(declared)[0] if len(declared) == 1 else None
        if role is None:
            return None
        reasons = ["the file declares this sample type"]
        if sheet_roles and set(sheet_roles) != {role}:
            reasons.append("the sheet names another type; the file's type is kept")
            cites += [ref for refs in sheet_roles.values() for ref in refs]
        return DesignField(
            kind="design.well_role",
            subject=sample.sample,
            value={"role": role},
            cites=cites,
            level="High",
            reasons=reasons,
        )
    name_role = control_role_from_name(name)
    if len(sheet_roles) == 1:
        role, refs = next(iter(sheet_roles.items()))
        if role == "unkn" and name_role is None and not in_series:
            return None
        if role == "unkn" and name_role is not None:
            return DesignField(
                kind="design.well_role",
                subject=sample.sample,
                value={"role": name_role},
                cites=[*cites, *refs],
                alternatives=[{"role": "unkn"}],
                level="Low",
                reasons=[
                    "the name reads as a control, but the sheet and the file say unknown",
                    "please type your controls",
                ],
            )
        level = "High" if role == name_role else "Moderate"
        reasons = ["the sheet's type column names this role"]
        if name_role == role:
            reasons.append("the name agrees")
        alternatives = [{"role": ambiguous_alt}] if ambiguous_alt else []
        if ambiguous_alt:
            level = "Low"
            reasons.append("the sheet's wording fits more than one control type")
        return DesignField(
            kind="design.well_role",
            subject=sample.sample,
            value={"role": role},
            cites=[*cites, *refs],
            alternatives=alternatives,
            level=level,
            reasons=reasons,
        )
    if len(sheet_roles) > 1:
        ordered = sorted(sheet_roles, key=lambda r: (-len(sheet_roles[r]), r))
        return DesignField(
            kind="design.well_role",
            subject=sample.sample,
            value={"role": ordered[0]},
            cites=[*cites, *(ref for refs in sheet_roles.values() for ref in refs)],
            alternatives=[{"role": r} for r in ordered[1:]],
            level="Low",
            reasons=["the sheet gives this sample more than one type"],
        )
    if name_role is not None:
        return DesignField(
            kind="design.well_role",
            subject=sample.sample,
            value={"role": name_role},
            cites=cites,
            alternatives=[{"role": "unkn"}],
            level="Moderate",
            reasons=[
                "the name reads as a control; the file declares it unknown",
                "please type your controls",
            ],
        )
    if in_series:
        return DesignField(
            kind="design.well_role",
            subject=sample.sample,
            value={"role": "std"},
            cites=cites,
            alternatives=[{"role": "unkn"}],
            level="Low",
            reasons=[
                "the sample belongs to a dilution series named in the file",
                "it is a standard only if the series is meant as a standard curve",
            ],
        )
    return None


def _series_level(each: Series) -> tuple[str, list[str]]:
    if each.source == "file":
        return "High", ["declared standards with quantities in the file"]
    if each.source == "sheet":
        return "Moderate", ["quantities from the sheet's quantity column"]
    return "Moderate", ["the sample names encode a dilution series and its quantities"]


def _column_field(
    sample: InspectSample, sheet: _SheetLookup, column: str, kind: str, key: str
) -> DesignField | None:
    found = sheet.values(sample, column)
    if not found:
        return None
    counts = Counter(value for value, _ in found)
    ordered = sorted(counts, key=lambda v: (-counts[v], v))
    value = safe_name(ordered[0], column)
    reasons = [f"from the sheet column recognised as {column}"]
    level = "Moderate"
    alternatives = []
    if len(ordered) > 1:
        level = "Low"
        reasons.append("the sheet gives this sample more than one value")
        alternatives = [{key: safe_name(v, column)} for v in ordered[1:]]
    return DesignField(
        kind=kind,  # type: ignore[arg-type]
        subject=sample.sample,
        value={key: value},
        cites=[sample.text_id, *dict.fromkeys(ref for _, ref in found)],
        alternatives=alternatives,
        level=level,
        reasons=reasons,
    )


def _unit_field(sample: InspectSample, sheet: _SheetLookup) -> DesignField | None:
    """A biological unit from an explicit sheet column (identity or replicate number)."""
    identity = sheet.values(sample, "bio_unit")
    if identity:
        unit = _column_field(sample, sheet, "bio_unit", "design.bio_unit", "biological_unit")
        if unit is not None and unit.level == "Moderate":
            unit.level = "High"
            unit.reasons = ["from the sheet column that names the biological unit"]
        return unit
    numbers = sheet.values(sample, "bio_rep")
    if not numbers:
        return None
    rep = Counter(v for v, _ in numbers).most_common(1)[0][0]
    groups = sheet.values(sample, "group")
    group = Counter(v for v, _ in groups).most_common(1)[0][0] if groups else ""
    label = f"{group}_rep{rep}" if group else f"rep{rep}"
    cites = [sample.text_id, *(ref for _, ref in numbers), *(ref for _, ref in groups)]
    reasons = ["from the sheet's biological replicate column"]
    if group:
        reasons.append("replicate numbers restart in each group, so the group is part of the unit")
    return DesignField(
        kind="design.bio_unit",
        subject=sample.sample,
        value={"biological_unit": safe_name(label, "unit")},
        cites=list(dict.fromkeys(cites)),
        level="Moderate",
        reasons=reasons,
    )


def sheet_units(summary: InspectSummary, quarantine: Iterable[QuarantineEntry]) -> dict[str, str]:
    """Sample -> biological unit, from the sheet's explicit unit column only.

    These are units a person wrote down; the hard ban in :mod:`qpilot.qpcr.design_checks`
    treats them like confirmed units. Samples with more than one value are left out.
    """
    values = {entry.text_id: entry.value for entry in quarantine}
    sheet = _sheet_lookup(summary, values)
    out = {}
    for sample in summary.samples:
        unit = _unit_field(sample, sheet)
        if unit is not None and not unit.alternatives:
            out[sample.sample] = unit.value["biological_unit"]
    return out


def _pattern_units(
    summary: InspectSummary, values: Mapping[str, str], skip: set[str]
) -> list[DesignField]:
    """``Low`` unit proposals where only a technical-replicate naming pattern suggests them."""
    bases: dict[str, list[InspectSample]] = defaultdict(list)
    for sample in summary.samples:
        if sample.sample in skip:
            continue
        name = values.get(sample.text_id, sample.sample).strip()
        match = _TECH_MARKER.match(name) or _LETTER_SUFFIX.match(name)
        if match:
            bases[match.group("base").strip(" _-.")].append(sample)
    out = []
    for base, members in sorted(bases.items()):
        if len(members) < 2 or not base:
            continue
        unit = safe_name(base, "unit")
        for sample in members:
            out.append(
                DesignField(
                    kind="design.bio_unit",
                    subject=sample.sample,
                    value={"biological_unit": unit},
                    cites=[s.text_id for s in members],
                    alternatives=[{"biological_unit": sample.sample}],
                    level="Low",
                    reasons=[
                        "only the names suggest these samples come from one biological unit",
                        "nothing in the file or sheet says so; please confirm the units",
                    ],
                )
            )
    return out


def _symbol_field(target: str, text_id: str, values: Mapping[str, str]) -> DesignField | None:
    finding = check_symbol(values.get(text_id, target))
    if not finding.candidates:
        return None
    first, *others = finding.candidates
    alternatives = [{"symbol": other} for other in others]
    if finding.status == "approved" and not finding.case_changed:
        level, reasons = "High", ["an approved HGNC symbol"]
    elif finding.status == "approved":
        level, reasons = (
            "Low",
            ["matches an approved human symbol only when letter case is ignored"],
        )
    elif finding.status in ("previous", "alias"):
        level = "Moderate"
        reasons = [f"a {finding.status} symbol; the current approved HGNC symbol is proposed"]
    else:  # date_mangled
        level = "Low"
        reasons = [
            "the name looks like a date Excel made from a gene name",
            "confirm which gene the assay measures",
        ]
    if finding.query != finding.name and finding.status != "date_mangled":
        reasons.append("date tokens or assay suffixes were removed before the lookup")
    if others:
        level = "Low"
        reasons.append("the name could mean more than one gene; every candidate is listed")
    return DesignField(
        kind="design.gene_symbol",
        subject=target,
        value={"symbol": first},
        cites=[text_id],
        alternatives=alternatives,
        level=level,  # type: ignore[arg-type]
        reasons=reasons,
    )


__all__ = [
    "CONTROL_PHRASES",
    "SERIES_PATTERNS",
    "VENDOR_TASKS",
    "Series",
    "control_role_from_name",
    "find_dilution_series",
    "is_declared_control",
    "parse_number",
    "propose_from_names",
    "sheet_units",
    "vendor_task_role",
]
