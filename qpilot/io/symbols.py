"""The gene-symbol gate: is a target name an approved human gene symbol, and if not, what is it?

Between a fifth and a third of published Excel gene lists contain names Excel converted into
dates or numbers (``MARCH1`` -> ``1-Mar``, ``SEPT2`` -> ``2-Sep``). qPCR target names add
their own noise: assay numbers and repeat-assay tags (``MYCN(4)``, ``PRKACB_bis``,
``UBC(2)``), date tokens from the instrument (``WSB1_20080310``) and non-gene assays such as
the Alu repeat (``ALUsq(Eurogentec)``).

:func:`check_symbols` sorts every name into one of:

=====================  ========================================================================
status                 meaning
=====================  ========================================================================
``approved``           an approved HGNC symbol (after removing assay suffixes)
``previous``           a previous HGNC symbol; ``candidates`` are the approved symbols now used
``alias``              an alias symbol; ``candidates`` are the approved symbols it may mean
``date_mangled``       looks like a date Excel made from a name; ``candidates`` lists every
                       approved symbol whose current or former name Excel turns into that date
``number_mangled``     looks like a number Excel made from a name (``2.31E+19``); not reversible
``non_gene``           a repeat or spike-in assay (Alu, LINE-1, ERCC), or a word qPCR files use
                       as a label (``REF``, ``NTC``, ``STD``, ``CTRL``, ``GOI``, ``Target 2``, a
                       single letter): deliberately no symbol
``unknown``            none of the above (a non-human gene, a custom assay, or a typo)
=====================  ========================================================================

When a name could mean more than one gene, every candidate is listed (``ambiguous``); nothing
is chosen silently. A label is never looked up: ``REF`` is an HGNC alias of ``ALYREF`` and
``STD`` a previous symbol of two genes, but in a qPCR file they mean "reference" and
"standard". Only :attr:`SymbolFinding.identifies` evidence names one gene; an alias, a match
that ignores letter case or several candidates only suggest one, so a rename from them must be
confirmed by a person (it is never "consistent" on its own).

The data is the HGNC complete set (CC0), reduced to approved, previous and alias symbols in
``qpilot/data/hgnc/`` (see its README for source, date and licence). HGNC is
human only: mouse or rat symbols match only by ignoring case (``case_changed``).
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Literal

SymbolStatus = Literal[
    "approved", "previous", "alias", "date_mangled", "number_mangled", "non_gene", "unknown"
]
DATA_FILE = "data/hgnc/hgnc_symbols.tsv"

MONTHS: dict[str, int] = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
#: Month -> the name prefixes that Excel reads as that month when followed by a number.
#: ``MARC`` is included because HGNC renamed ``MARC1``/``MARC2`` (now ``MTARC1``/``MTARC2``)
#: for exactly this reason, together with ``MARCH``->``MARCHF`` and ``SEPT``->``SEPTIN``.
MONTH_PREFIXES: dict[int, tuple[str, ...]] = {
    1: ("JAN", "JANUARY"),
    2: ("FEB", "FEBRUARY"),
    3: ("MAR", "MARCH", "MARC"),
    4: ("APR", "APRIL"),
    5: ("MAY",),
    6: ("JUN", "JUNE"),
    7: ("JUL", "JULY"),
    8: ("AUG", "AUGUST"),
    9: ("SEP", "SEPT", "SEPTEMBER"),
    10: ("OCT", "OCTOBER"),
    11: ("NOV", "NOVEMBER"),
    12: ("DEC", "DECEMBER"),
}

_DATE_TOKEN = re.compile(r"_20\d{6}(?=_|$)")
_PAREN_SUFFIX = re.compile(r"\s*\([^()]*\)\s*$")
_ASSAY_SUFFIX = re.compile(r"(?i)[\s_]+(?:bis|ter|new|old|v\d+|\d+|assay\d*)$")
_MONTH_WORD = r"([A-Za-z]{3,9})"
_DAY_MONTH = re.compile(r"^(\d{1,2})[-\s/.]" + _MONTH_WORD + r"$")
_MONTH_NUMBER = re.compile(r"^" + _MONTH_WORD + r"[-\s/.](\d{1,4})$")
_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ]00:00(?::00(?:\.0+)?)?)?$")
_SLASH_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$")
_E_NUMBER = re.compile(r"^\d+[.,]\d+E[+-]?\d+$", re.IGNORECASE)
_EXCEL_PRONE = re.compile(
    r"^(?:"
    + "|".join(sorted({p for ps in MONTH_PREFIXES.values() for p in ps}, key=len)[::-1])
    + r")\d{1,2}$"
)
#: Words qPCR files use as labels, never genes: these also numbered (``REF2``, ``Target_1``) ...
LABELS: tuple[str, ...] = (
    "REF", "REFERENCE", "GOI", "TOI", "TARGET", "GENE", "NTC", "NRT", "NTP", "STD", "STANDARD",
    "CTRL", "CONTROL", "POS", "NEG", "IPC", "BLANK", "CALIBRATOR",
)  # fmt: skip
#: ... and these only as written (``HK1`` is hexokinase 1, ``CTL1`` a choline transporter).
LABELS_AS_WRITTEN: tuple[str, ...] = (
    "HK", "HKG", "HOUSEKEEPING", "REFGENE", "NAC", "NOTEMPLATE", "CAL", "CTL", "SPIKE", "EMPTY",
    "WATER", "H2O", "WT", "KO", "MOCK",
)  # fmt: skip
_LABEL = re.compile(
    r"^(?:(?:" + "|".join(LABELS) + r")(?:[\s_-]?\d{1,2})?|" + "|".join(LABELS_AS_WRITTEN) + r")$",
    re.IGNORECASE,
)
_NON_GENE = (
    (_LABEL, "a word qPCR files use for a reference, a control or a standard, not a gene name"),
    (re.compile(r"^\w$"), "a single character, not a gene name"),
    (re.compile(r"^ALU", re.IGNORECASE), "an Alu repeat assay, not a gene"),
    (re.compile(r"^(?:LINE[-_ ]?1|L1HS|L1PA\d*)$", re.IGNORECASE), "a LINE-1 repeat assay"),
    (re.compile(r"^ERCC[-_ ]?\d+$", re.IGNORECASE), "an ERCC spike-in control, not a gene"),
)


@dataclass(frozen=True)
class SymbolFinding:
    """What the gate found for one name.

    Attributes:
        name: The input as text.
        query: The name looked up after removing date tokens and assay suffixes.
        status: See the module docstring.
        candidates: Approved HGNC symbols the name may stand for, sorted (empty for
            ``unknown``, ``non_gene`` and ``number_mangled``).
        matched: The HGNC symbols that matched (``MARCH1`` and ``MARC1`` for ``1-Mar``).
        case_changed: True when the match needed letter case to be ignored.
        note: qPilot's own short explanation (never contains file text).
    """

    name: str
    query: str
    status: SymbolStatus
    candidates: tuple[str, ...] = ()
    matched: tuple[str, ...] = ()
    case_changed: bool = False
    note: str = ""

    @property
    def ambiguous(self) -> bool:
        """True when the name could mean more than one approved symbol."""
        return len(self.candidates) > 1

    @property
    def identifies(self) -> bool:
        """True when the name itself identifies one approved symbol.

        It does when it is that symbol as written, a previous symbol of one gene, or a date
        Excel made from one gene's name. An alias (a name other genes or words may share), a
        match that ignores letter case, or several candidates only suggest a gene: a rename
        from them is for a person to confirm.
        """
        if len(self.candidates) != 1 or self.case_changed:
            return False
        return self.status in ("approved", "previous", "date_mangled")

    @property
    def resolved(self) -> str | None:
        """The one approved symbol the name stands for (``None`` unless exactly one)."""
        if self.status in ("approved", "previous", "alias", "date_mangled"):
            return self.candidates[0] if len(self.candidates) == 1 else None
        return None


@dataclass(frozen=True)
class SymbolTable:
    """Approved, previous and alias symbols, indexed for exact and case-blind lookup."""

    approved: frozenset[str]
    previous: dict[str, frozenset[str]]  # previous symbol -> approved symbols
    alias: dict[str, frozenset[str]]  # alias symbol -> approved symbols
    upper: dict[str, tuple[tuple[str, str, str], ...]]  # UPPER -> (symbol, relation, approved)

    def lookup(self, symbol: str, *, ignore_case: bool = False) -> list[tuple[str, str, str]]:
        """Every ``(matched symbol, relation, approved symbol)`` for ``symbol``.

        ``relation`` is ``approved``, ``previous`` or ``alias``. Exact (case-sensitive) matches
        only, unless ``ignore_case``.
        """
        if ignore_case:
            return list(self.upper.get(symbol.upper(), ()))
        hits: list[tuple[str, str, str]] = []
        if symbol in self.approved:
            hits.append((symbol, "approved", symbol))
        for approved in sorted(self.previous.get(symbol, ())):
            hits.append((symbol, "previous", approved))
        for approved in sorted(self.alias.get(symbol, ())):
            hits.append((symbol, "alias", approved))
        return hits


@lru_cache(maxsize=1)
def load_table() -> SymbolTable:
    """Load the shipped HGNC table once per process."""
    text = resources.files("qpilot").joinpath(DATA_FILE).read_text(encoding="utf-8")
    approved: set[str] = set()
    previous: dict[str, set[str]] = {}
    alias: dict[str, set[str]] = {}
    upper: dict[str, list[tuple[str, str, str]]] = {}
    for line in text.split("\n"):
        if not line or line.startswith("#"):
            continue
        symbol, prev, aliases = (line.split("\t") + ["", ""])[:3]
        approved.add(symbol)
        upper.setdefault(symbol.upper(), []).append((symbol, "approved", symbol))
        for relation, values, index in (("previous", prev, previous), ("alias", aliases, alias)):
            for value in filter(None, values.split("|")):
                index.setdefault(value, set()).add(symbol)
                upper.setdefault(value.upper(), []).append((value, relation, symbol))
    return SymbolTable(
        approved=frozenset(approved),
        previous={k: frozenset(v) for k, v in previous.items()},
        alias={k: frozenset(v) for k, v in alias.items()},
        upper={k: tuple(v) for k, v in upper.items()},
    )


def normalise_assay_name(name: str) -> str:
    """Remove instrument date tokens and assay suffixes from a target name.

    ``MYCN(4)`` -> ``MYCN``; ``PRKACB_20080311_bis`` -> ``PRKACB``; ``ALUsq(Eurogentec)`` ->
    ``ALUsq``; ``UBC(2)`` -> ``UBC``. Hyphens are kept (``NKX2-1`` is a symbol).
    """
    text = _DATE_TOKEN.sub("", name.strip())
    while True:
        stripped = _ASSAY_SUFFIX.sub("", _PAREN_SUFFIX.sub("", text)).strip()
        if stripped == text or not stripped:
            return text
        text = stripped


def excel_date_parts(value: object) -> list[tuple[int, int]]:
    """The ``(month, number)`` pairs a date (or date-looking text) could have come from.

    ``1-Mar`` and ``Mar-01`` give ``[(3, 1)]``; ``3/1/2024`` gives ``[(3, 1), (1, 3)]`` (month
    and day order is unknown); a date on the first of a month also offers its two-digit year,
    since Excel reads ``MARCH40`` as March 1940. Anything else gives ``[]``.
    """
    pairs: list[tuple[int, int]] = []
    if isinstance(value, dt.datetime | dt.date):
        pairs.append((value.month, value.day))
        if value.day == 1 and value.year % 100:
            pairs.append((value.month, value.year % 100))
        return pairs
    if not isinstance(value, str):
        return pairs
    text = value.strip()
    if match := _DAY_MONTH.match(text):
        month = MONTHS.get(match.group(2).lower())
        if month:
            pairs.append((month, int(match.group(1))))
    elif match := _MONTH_NUMBER.match(text):
        month = MONTHS.get(match.group(1).lower())
        number = int(match.group(2))
        if month and number:
            pairs.append((month, number % 100 if number > 99 else number))
    elif match := _ISO_DATE.match(text):
        year, month, day = (int(g) for g in match.groups())
        if 1 <= month <= 12 and 1 <= day <= 31:
            pairs.append((month, day))
            if day == 1 and year % 100:
                pairs.append((month, year % 100))
    elif match := _SLASH_DATE.match(text):
        first, second = int(match.group(1)), int(match.group(2))
        for month, day in ((first, second), (second, first)):
            if 1 <= month <= 12 and 1 <= day <= 31 and (month, day) not in pairs:
                pairs.append((month, day))
    return [(m, n) for m, n in pairs if 1 <= n <= 99]


def check_symbol(name: object, *, table: SymbolTable | None = None) -> SymbolFinding:
    """Run the gate on one name (a string, or a date a spreadsheet returned). See the module."""
    table = table or load_table()
    if isinstance(name, dt.datetime | dt.date):
        text = name.isoformat()
        return _date_finding(text, excel_date_parts(name), table)
    text = str(name).strip()
    if not text:
        return SymbolFinding(name=text, query=text, status="unknown", note="empty name")
    label = _label(text)
    if label is not None:
        return label
    exact = table.lookup(text)
    query = text if exact else normalise_assay_name(text)
    hits = exact or table.lookup(query)
    if hits:
        return _finding(text, query, hits, case_changed=False)
    pairs = excel_date_parts(text)
    if pairs:
        return _date_finding(text, pairs, table)
    if _E_NUMBER.match(text):
        return SymbolFinding(
            name=text,
            query=text,
            status="number_mangled",
            note="looks like a number Excel made from a name; the original cannot be recovered",
        )
    for pattern, note in _NON_GENE:
        if pattern.match(query):
            return SymbolFinding(name=text, query=query, status="non_gene", note=note)
    hits = table.lookup(query, ignore_case=True)
    if hits:
        return _finding(text, query, hits, case_changed=True)
    return SymbolFinding(
        name=text,
        query=query,
        status="unknown",
        note="not an HGNC symbol (it may be a non-human gene, a custom assay or a typo)",
    )


def _label(text: str) -> SymbolFinding | None:
    """A label or a single character (see :data:`LABELS`), before any lookup; else ``None``."""
    query = normalise_assay_name(text)
    for pattern, note in _NON_GENE[:2]:
        if pattern.match(text) or pattern.match(query):
            return SymbolFinding(name=text, query=query, status="non_gene", note=note)
    return None


def check_symbols(
    names: Iterable[object], *, table: SymbolTable | None = None
) -> list[SymbolFinding]:
    """Run the gate on every name, in order. See the module docstring for the statuses."""
    table = table or load_table()
    return [check_symbol(name, table=table) for name in names]


def _finding(
    text: str, query: str, hits: list[tuple[str, str, str]], *, case_changed: bool
) -> SymbolFinding:
    relations = {relation for _, relation, _ in hits}
    if "approved" in relations:
        approved = sorted({a for _, r, a in hits if r == "approved"})
        status: SymbolStatus = "approved"
        note = "an approved HGNC symbol"
    else:
        approved = sorted({a for _, _, a in hits})
        status = "previous" if "previous" in relations else "alias"
        note = (
            "a previous HGNC symbol; the gene now has another symbol"
            if status == "previous"
            else "an alias, not the approved HGNC symbol; other genes or words may share an "
            "alias, so confirm the gene before renaming"
        )
    if case_changed:
        note += " (matched only when letter case is ignored)"
    if query != text:
        note += "; date tokens or assay suffixes were removed before the lookup"
    if _EXCEL_PRONE.match(query.upper()):
        note += "; Excel turns this name into a date unless the column is set to text"
    if len(approved) > 1:
        note += "; it could mean more than one gene"
    return SymbolFinding(
        name=text,
        query=query,
        status=status,
        candidates=tuple(approved),
        matched=tuple(sorted({m for m, _, _ in hits})),
        case_changed=case_changed,
        note=note,
    )


def _date_finding(text: str, pairs: list[tuple[int, int]], table: SymbolTable) -> SymbolFinding:
    matched: set[str] = set()
    approved: set[str] = set()
    for month, number in pairs:
        for prefix in MONTH_PREFIXES[month]:
            for symbol, _, target in table.lookup(f"{prefix}{number}", ignore_case=True):
                matched.add(symbol)
                approved.add(target)
    note = "looks like a date Excel made from a gene name"
    note += (
        "; every gene whose name Excel turns into this date is listed"
        if approved
        else "; no HGNC symbol turns into this date"
    )
    return SymbolFinding(
        name=text,
        query=text,
        status="date_mangled",
        candidates=tuple(sorted(approved)),
        matched=tuple(sorted(matched)),
        note=note,
    )


__all__ = [
    "LABELS",
    "LABELS_AS_WRITTEN",
    "MONTH_PREFIXES",
    "SymbolFinding",
    "SymbolStatus",
    "SymbolTable",
    "check_symbol",
    "check_symbols",
    "excel_date_parts",
    "load_table",
    "normalise_assay_name",
]
