"""Read the checkable claims out of qPCR results prose, with rules only (no model).

:func:`extract` splits a text into sentences and clauses, finds the study's genes and groups
(:class:`~qpilot.claims.lexicon.Lexicon`), and around each gene the words a claim is made of:

* a direction: up (``up-regulated``, ``increased``, ``higher``, ``induced``…), down
  (``down-regulated``, ``reduced``, ``lower``…) or no change (``unchanged``, ``did not differ``,
  ``no significant difference``…); a negation (``was not increased``) turns a direction into no
  change, and a hedge (``tended to``, ``slightly``) makes it a direction without significance;
* a fold value: ``3.6-fold``, ``3.6×``, ``3.6 times``, ``four-fold``, ``a 72 % decrease``,
  ``log2 fold change of 1.8``, ``FC = 0.28``, with ``about`` / ``more than`` / ``up to`` /
  ranges (``2–3-fold``);
* a p-value (``p < 0.01``, ``P = 2.1 × 10⁻⁸``, ``q < 0.05`` is marked adjusted) or a significance
  word (``significantly``, ``not significant``, ``n.s.``);
* a robustness word (``robustly``, ``consistently``, ``regardless of the reference genes``);
* the normaliser (``normalised to UBC``, ``relative to HMBS and SDHA``, ``using GAPDH as
  reference``), sample sizes (``n = 53 vs 294``) and efficiency ranges (``90–110 %``).

Every part of a reading keeps the exact span of the text it came from, so the page can underline
it and a person can see what was read before believing a verdict. Words that apply to a list of
genes (``ODC1, BIRC5 and NTRK1 were up-regulated``) are shared by the list; values given
``respectively`` are matched in order.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal

from qpilot.claims.lexicon import Found, GroupFound, Lexicon

Direction = Literal["up", "down", "none"]
Comparator = Literal["about", "exact", "at_least", "at_most", "range"]
Role = Literal[
    "gene",
    "direction",
    "negation",
    "hedge",
    "fold",
    "p",
    "significance",
    "robust",
    "normaliser",
    "group",
    "n",
    "efficiency",
]
ClaimKind = Literal["gene", "normaliser", "efficiency", "n"]

MAX_CLAIMS = 200

# ---- the words -------------------------------------------------------------------------------

NUM = r"(?:\d+(?:\.\d+)?|\.\d+)"
_UP = (
    r"up[\s-]?regulat(?:ed|ion|es|e|ing)|over[\s-]?express(?:ed|ion|es)|increas(?:ed|es|e|ing)"
    r"|elevat(?:ed|ion)|higher|greater|enhanced|induc(?:ed|tion|es|e)|enrich(?:ed|ment)"
    r"|raised|rose|augmented|more\s+(?:highly\s+)?(?:expressed|abundant)|gain(?:ed)?"
    r"|accumulat(?:ed|ion)|\bup\b(?![\s-]+to\b)"
)
_DOWN = (
    r"down[\s-]?regulat(?:ed|ion|es|e|ing)|under[\s-]?express(?:ed|ion|es)"
    r"|decreas(?:ed|es|e|ing)|reduc(?:ed|tion|es|e|ing)|lower(?:ed)?|diminish(?:ed|es)?"
    r"|declin(?:ed|e)|dropp(?:ed)|fell|repress(?:ed|ion)|suppress(?:ed|ion)|deplet(?:ed|ion)"
    r"|less\s+(?:highly\s+)?(?:expressed|abundant)|loss|lost|silenc(?:ed|ing)|attenuated"
    r"|\bdown\b"
)
_NONE = (
    r"unchanged|unaltered|unaffected|not\s+(?:significantly\s+|statistically\s+)*"
    r"(?:changed|altered|different|affected)|(?:did|does|do)\s+not\s+(?:significantly\s+)?"
    r"(?:change|differ|vary)|no\s+(?:significant\s+|statistically\s+significant\s+|detectable\s+"
    r"|measurable\s+|clear\s+)?(?:differences?|changes?|effect)|similar|comparable"
    r"|remained\s+(?:unchanged|constant|stable)|equivalent"
)
DIRECTION = re.compile(rf"(?P<up>{_UP})|(?P<down>{_DOWN})|(?P<none>{_NONE})", re.I)
NEGATION = re.compile(
    r"(?:\b(?:not|no|never|neither|nor|without)\b|n't)\s*(?:\w+\s+){0,2}$|\black\s+of\s+$", re.I
)
HEDGE = re.compile(
    r"\btend(?:ed|s)?\s+to\b|\btrend(?:ed|s)?\b|\bslight(?:ly)?\b|\bmarginal(?:ly)?\b"
    r"|\bmodest(?:ly)?\b|\bsomewhat\b|\bweak(?:ly)?\b|\bmild(?:ly)?\b",
    re.I,
)
NOT_SIGNIFICANT = (
    r"(?:not|non|in)[\s-]?(?:statistically\s+)?significant(?:ly)?|n\.\s?s\.|\bns\b"
    r"|(?:did\s+not|failed\s+to)\s+reach\s+(?:statistical\s+)?significance"
)
SIGNIFICANCE = re.compile(
    rf"(?P<not>{NOT_SIGNIFICANT})|(?P<sig>(?:statistically\s+|highly\s+|very\s+)?significant(?:ly)?)",
    re.I,
)
ROBUST = re.compile(
    r"\brobust(?:ly)?\b|\bconsistent(?:ly)?\b(?!\s+with)|\breproducibl[ey]\b|\binvariabl[ey]\b"
    r"|\b(?:regardless|irrespective)\s+of\s+(?:the\s+)?[\w\s-]{1,40}?(?=[,.;)]|$)"
    r"|\bindependent(?:ly)?\s+of\s+(?:the\s+)?(?:normali[sz]ation|reference|control|housekeeping"
    r"|analysis|choice)[\w\s-]{0,30}?(?=[,.;)]|$)"
    r"|\bin\s+(?:all|every)\s+(?:reasonable\s+)?analys[ie]s\b",
    re.I,
)
NORMALISER_CUE = re.compile(
    r"\bnormali[sz](?:ed|ation|ing|e)\s+(?:to|against|by|with|on|using|relative\s+to)\b"
    r"|\brelative\s+to\b|\b(?:reference|housekeeping|control)\s+genes?\b"
    r"|\b(?:endogenous|internal)\s+controls?\b|\bgeometric\s+mean\s+of\b",
    re.I,
)
AS_REFERENCE = re.compile(
    r"\bas\s+(?:the\s+|a\s+|an\s+)?(?:reference|normali[sz]er|housekeeping|endogenous\s+control"
    r"|internal\s+control)(?:\s+genes?)?\b",
    re.I,
)
GLUE = re.compile(
    r"^(?:[\s,&/+()]|\band\b|\bor\b|\bthe\b|\bgeometric\b|\barithmetic\b|\bmean\b|\baverage\b"
    r"|\bof\b|\breference\b|\bcontrol\b|\bhousekeeping\b|\bgenes?\b|\bboth\b|\bplus\b|\busing\b"
    r"|\bwith\b|\btwo\b|\bthree\b|\bfour\b|\bfive\b)*$",
    re.I,
)
LIST_GLUE = re.compile(
    r"^(?:[\s,&/]|\band\b|\bor\b|\bas\s+well\s+as\b|\bboth\b|\btogether\s+with\b"
    r"|\balong\s+with\b|\bthe\b|\bgenes?\b|\bmRNAs?\b|\bexpression\s+of\b|\blevels?\s+of\b"
    r"|\([^()]*\))*$",
    re.I,
)
INHERIT_LEFT = re.compile(
    r"\bas\s+(?:was|were|did|is|are)\b|\bso\s+(?:was|were|did)\b|\blikewise\b|\bsimilarly\b"
    r"|\btoo\b|\balso\b",
    re.I,
)
RESPECTIVELY = re.compile(r"\brespectively\b", re.I)
BASELINE_CUE = re.compile(
    r"(?:\bthan(?:\s+in)?|\bcompared\s+(?:with|to)(?:\s+(?:the|those|that)\s+(?:in|of))?"
    r"|\brelative\s+to|\bversus|\bvs\.?|\bover|\bagainst)\s*(?:the\s+)?(?:in\s+)?$",
    re.I,
)

_NUMBER_WORDS = {
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "hundred": 100,
}
_WORDS = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))
_TIMES = r"(?:[\s-]*(?:fold|×|times)\b|[\s-]*×|(?<=\d)\s?[xX](?![\w]))"
FOLD = re.compile(
    rf"(?P<range>(?P<rlo>{NUM})\s*(?:-|–|—)?\s*(?:to|-|–|—)\s*(?P<rhi>{NUM}){_TIMES})"
    rf"|(?P<log2>log\s?2[\s-]*(?:FC|fold[\s-]?changes?|ratio)\s*(?:of|=|:|was|were|is)?\s*"
    rf"(?P<lval>[-−–]?\s*{NUM}))"
    rf"|(?P<fc>(?:\bFC|fold[\s-]?changes?)\s*(?:of|=|:|was|were|is|≈|~)\s*(?P<fval>{NUM}))"
    rf"|(?P<pct>(?P<pval>{NUM})\s*(?:%|per\s?cent|percent)\s*(?P<pword>increase|rise|gain|higher"
    rf"|more|elevation|up[\s-]?regulation|decrease|reduction|drop|loss|lower|less|decline"
    rf"|down[\s-]?regulation))"
    rf"|(?P<pctby>(?P<bword>increas\w*|decreas\w*|reduc\w*|elevat\w*|rais\w*|lower\w*|drop\w*"
    rf"|declin\w*)\s+by\s+(?:about\s+|approximately\s+|nearly\s+|almost\s+|~\s*)?(?P<bval>{NUM})"
    rf"\s*(?:%|per\s?cent|percent))"
    rf"|(?P<word>\b(?P<wval>{_WORDS})[\s-]?(?:fold|times)\b)"
    rf"|(?P<plain>(?<![\w.])(?P<val>{NUM}){_TIMES})",
    re.I,
)
FOLD_LIST = re.compile(
    rf"(?<![\w.])(?P<items>(?:{NUM}\s*[-–]?\s*(?:,|,?\s*and\b|&)\s*)+{NUM})\s*[-–]?\s*"
    r"(?:fold|×|times)\b",
    re.I,
)
COMPARATOR_BEFORE = (
    (
        "at_least",
        re.compile(
            r"(?:more\s+than|greater\s+than|over|above|exceeding|in\s+excess\s+of|at\s+least"
            r"|>|≥|>=)\s*(?:a\s+|an\s+)?$",
            re.I,
        ),
    ),
    (
        "at_most",
        re.compile(
            r"(?:less\s+than|under|below|at\s+most|up\s+to|no\s+more\s+than|<|≤|<=)\s*(?:a\s+)?$",
            re.I,
        ),
    ),
    (
        "about",
        re.compile(
            r"(?:about|approximately|approx\.?|around|nearly|almost|roughly|some|circa|ca\.|~|≈"
            r"|∼)\s*(?:a\s+|an\s+)?$",
            re.I,
        ),
    ),
)
_SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")
_EXP = r"(?:[-−–⁻]\s*[\d⁰¹²³⁴⁵⁶⁷⁸⁹]+|[⁰¹²³⁴⁵⁶⁷⁸⁹]+)"
P_VALUE = re.compile(
    r"(?<![\w])(?P<label>adjusted\s+[pP](?:[\s-]?values?)?|[pP][\s_-]?adj(?:usted)?|FDR"
    r"|[qQ](?:[\s-]?values?)?|[pP](?:[\s-]?values?)?)"
    r"\s*(?P<op><=|>=|≤|≥|<|>|=|\bof\b|\bwas\b|\bwere\b|\bis\b|\bbelow\b|\bunder\b|\bless\s+than\b)"
    rf"\s*(?:(?P<pow>10\s*(?:\^|\*\*)?\s*(?:\(\s*{_EXP}\s*\)|{_EXP}))"
    rf"|(?P<num>{NUM})(?:\s*(?:[x×*·]|\\times)\s*10\s*(?:\^|\*\*)?\s*"
    rf"(?:\(\s*(?P<expp>{_EXP})\s*\)|(?P<exp>{_EXP}))"
    r"|\s*[eE]\s*(?P<exp2>[-−–]?\d+))?)",
)
N_VALUES = re.compile(
    r"(?<![\w])[nN]\s*=\s*(?P<a>\d+)(?:\s*(?:vs\.?|versus|and|/|,|:|against)\s*(?:[nN]\s*=\s*)?"
    r"(?P<b>\d+))?"
    r"|(?<![\w.])(?P<c>\d+)\s+(?:vs\.?|versus)\s+(?P<d>\d+)\s+(?:tumou?rs|samples|patients|mice"
    r"|animals|subjects|donors|cases|biological\s+replicates)",
)
EFFICIENCY_CUE = re.compile(r"\befficienc(?:y|ies)\b", re.I)
EFFICIENCY_RANGE = re.compile(
    rf"(?:between\s+)?(?P<lo>{NUM})\s*(?P<lu>%)?\s*(?:-|–|—|to|and)\s*(?P<hi>{NUM})\s*(?P<hu>%)?"
    rf"|(?P<op>>|≥|>=|above|over|at\s+least|more\s+than|exceeding|greater\s+than|<|≤|<=|below"
    rf"|under|less\s+than)\s*(?P<v>{NUM})\s*(?P<vu>%)?",
    re.I,
)
_ABBREVIATIONS = {"vs", "e.g", "i.e", "al", "fig", "figs", "approx", "ca", "cf", "no", "ref"}
_ABBREVIATIONS |= {"refs", "eq", "resp", "n.s", "suppl", "tab", "ext", "dr", "mr", "ms", "st"}
SENTENCE_END = re.compile(r"[.!?](?:[\"'”’)\]]*)\s+(?=[\"'“‘(\[]?[A-Z0-9])|\n[ \t]*\n+")
CLAUSE_BREAK = re.compile(
    r";\s*|,?\s+whereas\s+|,?\s+while\s+(?!also\b)|,\s+but\s+|\s+but\s+(?!also\b)"
    r"|,?\s+however,?\s+|,?\s+in\s+contrast,?\s+|,?\s+although\s+|,?\s+though\s+|,\s+yet\s+",
    re.I,
)


# ---- the reading -----------------------------------------------------------------------------


@dataclass(frozen=True)
class Span:
    """A run of the original text: ``text[start:end]``."""

    start: int
    end: int


@dataclass(frozen=True)
class Mark:
    """One piece of the text a reading rests on."""

    role: Role
    span: Span
    written: str


@dataclass(frozen=True)
class FoldValue:
    """A fold value as written, and the change it allows (absolute log2, at least 0).

    ``sign`` is +1 or -1 when the words themselves say which way (``0.28-fold``, ``a 72 %
    decrease``, a signed log2 value), else None (the direction words decide).
    """

    mark: Mark
    comparator: Comparator
    kind: Literal["fold", "percent", "log2"]
    value: float  # as written (3.6, 0.28, 72, -1.8)
    lo: float  # absolute log2 change the words allow, low end
    hi: float  # high end (inf for "more than")
    sign: int | None
    note: str = ""


@dataclass(frozen=True)
class PValue:
    """A p-value statement: ``p < 0.01`` (``op`` "<"), ``p = 0.003`` (``op`` "=" with a band)."""

    mark: Mark
    op: Literal["<", "<=", "=", ">", ">="]
    value: float
    lo: float  # for "=": the band the written digits stand for
    hi: float
    adjusted: bool


@dataclass(frozen=True)
class Claim:
    """One checkable claim and the spans of the text it was read from.

    ``kind`` is ``gene`` (a statement about one gene's change between the groups),
    ``normaliser`` (which control genes the analysis used), ``efficiency`` (a range every named
    assay's efficiency is said to fall in) or ``n`` (group sizes).
    """

    kind: ClaimKind
    sentence: Span
    clause: Span
    marks: tuple[Mark, ...] = ()
    gene: str | None = None
    gene_status: str | None = None  # compared / reference / marker / withheld / measured / absent
    gene_via: str | None = None
    direction: Direction | None = None
    negated: bool = False
    hedged: bool = False
    inverted: bool = False  # the words compare the second group with the first
    fold: FoldValue | None = None
    p: PValue | None = None
    significance: Literal["significant", "not_significant"] | None = None
    robust: bool = False
    normaliser: tuple[str, ...] = ()  # the study's names (and absent HGNC symbols)
    n_values: tuple[int, ...] = ()
    efficiency: tuple[float, float] | None = None  # percent range (lo, hi); inf / 0 if one-sided
    genes: tuple[str, ...] = ()  # for an efficiency claim: the assays it names (empty: all)
    respectively: bool = False
    source: Literal["rules", "model"] = "rules"

    def mark(self, role: Role) -> Mark | None:
        """The first mark with this role."""
        return next((m for m in self.marks if m.role == role), None)


# ---- splitting -------------------------------------------------------------------------------


def sentences(text: str) -> list[Span]:
    """Sentence spans of ``text`` (abbreviations such as ``vs.`` and ``e.g.`` do not end one)."""
    out: list[Span] = []
    start = 0
    for match in SENTENCE_END.finditer(text):
        if match.group(0)[0] in ".!?":
            word = re.search(r"([\w.]+)$", text[start : match.start()])
            if word and word.group(1).lower().rstrip(".") in _ABBREVIATIONS:
                continue
        end = match.start() + (1 if match.group(0)[0] in ".!?" else 0)
        _push(out, text, start, end)
        start = match.end()
    _push(out, text, start, len(text))
    return out


def _push(out: list[Span], text: str, start: int, end: int) -> None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if end > start:
        out.append(Span(start, end))


def clauses(text: str, sentence: Span) -> list[Span]:
    """Clause spans of one sentence, split at ``;`` and contrasts (``whereas``, ``but``…)."""
    out: list[Span] = []
    start = sentence.start
    for match in CLAUSE_BREAK.finditer(text, sentence.start, sentence.end):
        before = text[sentence.start : match.start()]
        if before.count("(") > before.count(")"):
            continue  # never inside parentheses: "(log2 FC = 0.4; q = 0.2)"
        _push(out, text, start, match.start())
        start = match.end()
    _push(out, text, start, sentence.end)
    return out


# ---- numbers ---------------------------------------------------------------------------------


def _float(text: str) -> float:
    return float(text.replace("−", "-").replace("–", "-").replace(" ", ""))


def _decimals(text: str) -> int:
    text = text.strip().lstrip("-−–")
    return len(text.split(".", 1)[1]) if "." in text else 0


def _band(value: float, written: str) -> tuple[float, float]:
    """The range a written number stands for (``3.6`` is 3.55–3.65, ``4`` is 3.5–4.5)."""
    half = 0.5 * 10 ** -_decimals(written)
    return value - half, value + half


def _log2(x: float) -> float:
    return math.log2(x) if x > 0 else -math.inf


def _comparator(text: str, start: int) -> tuple[Comparator, int]:
    """The comparator written just before ``start`` (and where it starts)."""
    before = text[max(0, start - 24) : start]
    for name, pattern in COMPARATOR_BEFORE:
        match = pattern.search(before)
        if match:
            return name, start - (len(before) - match.start())  # type: ignore[return-value]
    return "exact", start


ABOUT = 0.10  # "about 3-fold": the written value's rounding range, widened by 10 % each side


def _fold_value(text: str, match: re.Match[str]) -> FoldValue | None:
    groups = match.groupdict()
    comparator, begin = _comparator(text, match.start())
    end = match.end()
    written = text[begin:end]
    mark = Mark("fold", Span(begin, end), written)
    sign: int | None = None
    kind: Literal["fold", "percent", "log2"] = "fold"
    note = ""
    if groups["range"]:
        a, b = _float(groups["rlo"]), _float(groups["rhi"])
        lo_v, hi_v = min(a, b), max(a, b)
        lo_v, hi_v = _band(lo_v, groups["rlo"])[0], _band(hi_v, groups["rhi"])[1]
        value = (lo_v + hi_v) / 2
        comparator = "range"
        ratio_lo, ratio_hi = lo_v, hi_v
    elif groups["log2"]:
        raw = groups["lval"]
        value = _float(raw)
        kind = "log2"
        lo_b, hi_b = _band(abs(value), raw)
        sign = -1 if value < 0 else (1 if value > 0 else None)
        return _finish(mark, comparator, kind, value, max(lo_b, 0.0), hi_b, sign, note)
    elif groups["pct"] or groups["pctby"]:
        raw = groups["pval"] or groups["bval"]
        word = (groups["pword"] or groups["bword"] or "").lower()
        if re.search(r"(?i)about|approximately|nearly|almost|~", match.group(0)):
            comparator = "about"
        value = _float(raw)
        kind = "percent"
        lo_p, hi_p = _band(value, raw)
        down = word.startswith(("decreas", "reduc", "drop", "loss", "lower", "less", "declin"))
        down = down or word.startswith("down")
        if down:
            if hi_p >= 100:
                return None  # "a 100 % decrease" is not a fold
            sign = -1
            ratio_lo, ratio_hi = 1 - hi_p / 100, 1 - lo_p / 100
            note = "a decrease of this many percent"
        else:
            sign = 1
            ratio_lo, ratio_hi = 1 + lo_p / 100, 1 + hi_p / 100
            note = "an increase of this many percent"
    elif groups["word"]:
        value = float(_NUMBER_WORDS[groups["wval"].lower()])
        ratio_lo, ratio_hi = value - 0.5, value + 0.5
    else:
        raw = groups.get("fval") or groups.get("val") or ""
        if not raw:
            return None
        value = _float(raw)
        ratio_lo, ratio_hi = _band(value, raw)
    if value <= 0 or ratio_hi <= 0:
        return None
    if comparator == "at_least" and kind == "fold":
        ratio_lo = ratio_hi = value  # "more than 3-fold": above 3 itself, not its rounding
    elif comparator == "at_most" and kind == "fold":
        ratio_lo = ratio_hi = value
    if ratio_hi <= 1 or (ratio_lo < 1 < ratio_hi and value < 1):
        sign = -1 if sign is None else sign
        ratio_lo, ratio_hi = 1 / ratio_hi, 1 / max(ratio_lo, 1e-12)
    lo, hi = _log2(max(ratio_lo, 1.0)), _log2(max(ratio_hi, 1.0))
    if comparator == "about":
        lo, hi = _log2(max(2**lo / (1 + ABOUT), 1.0)), _log2(2**hi * (1 + ABOUT))
    return _finish(mark, comparator, kind, value, lo, hi, sign, note)


def _finish(
    mark: Mark,
    comparator: Comparator,
    kind: Literal["fold", "percent", "log2"],
    value: float,
    lo: float,
    hi: float,
    sign: int | None,
    note: str,
) -> FoldValue:
    if comparator == "at_least":
        hi = math.inf
    elif comparator == "at_most":
        lo = 0.0
    elif comparator == "about" and kind == "log2":
        lo, hi = max(lo - math.log2(1 + ABOUT), 0.0), hi + math.log2(1 + ABOUT)
    return FoldValue(mark, comparator, kind, value, lo, hi, sign, note)


def _p_value(text: str, match: re.Match[str]) -> PValue:
    groups = match.groupdict()
    label = groups["label"].lower()
    adjusted = label.startswith(("q", "fdr", "adj")) or "adj" in label
    op_word = groups["op"].strip().lower()
    op = {
        "<=": "<=",
        "≤": "<=",
        ">=": ">=",
        "≥": ">=",
        "<": "<",
        ">": ">",
        "below": "<",
        "under": "<",
        "less than": "<",
    }.get(re.sub(r"\s+", " ", op_word), "=")
    if groups["pow"]:
        exp = re.search(_EXP, groups["pow"]).group(0)  # type: ignore[union-attr]
        value = 10.0 ** _float(exp.translate(_SUP))
        lo, hi = value, value
    else:
        mantissa = groups["num"]
        exp = groups["exp"] or groups["expp"] or groups["exp2"]
        scale = 10.0 ** _float(exp.translate(_SUP)) if exp else 1.0
        value = _float(mantissa) * scale
        lo, hi = (x * scale for x in _band(_float(mantissa), mantissa))
    mark = Mark("p", Span(match.start(), match.end()), match.group(0))
    return PValue(mark, op, value, max(lo, 0.0), hi, adjusted)  # type: ignore[arg-type]


# ---- one clause ------------------------------------------------------------------------------


@dataclass
class _Window:
    gene: Found
    start: int
    end: int
    direction: tuple[Direction, Mark, bool, bool] | None = None  # (dir, mark, negated, hedged)
    folds: list[FoldValue] = field(default_factory=list)
    p: PValue | None = None
    significance: tuple[str, Mark] | None = None
    robust: Mark | None = None
    marks: list[Mark] = field(default_factory=list)

    def empty(self) -> bool:
        return not (self.direction or self.folds or self.p or self.significance or self.robust)


def _inside(spans: Iterable[Span], start: int, end: int) -> bool:
    return any(s.start < end and start < s.end for s in spans)


def _directions(text: str, clause: Span, taken: Sequence[Span]) -> list[tuple]:
    out = []
    for match in DIRECTION.finditer(text, clause.start, clause.end):
        if _inside(taken, match.start(), match.end()):
            continue
        kind = match.lastgroup
        word = match.group(0)
        mark = Mark("direction", Span(match.start(), match.end()), word)
        before = text[clause.start : match.start()]
        negation = NEGATION.search(before[-30:])
        negated = bool(negation) and kind in ("up", "down")
        if kind in ("up", "down") and re.match(r"(?i)loss|lost", word) and negated:
            negated = False
        hedge = HEDGE.search(text, max(clause.start, match.start() - 30), match.start())
        direction: Direction = "none" if negated else kind  # type: ignore[assignment]
        extra = []
        if negated and negation is not None:
            s = match.start() - len(before[-30:]) + negation.start()
            extra.append(Mark("negation", Span(s, s + len(negation.group(0).split()[0])), ""))
        if hedge is not None and not negated:
            extra.append(Mark("hedge", Span(hedge.start(), hedge.end()), hedge.group(0)))
        out.append((match.start(), direction, mark, negated, hedge is not None, extra))
    return out


NOT_NORMALISERS = ("compared", "marker")  # a gene the study compares ends a list of controls


def _glue(between: str) -> bool:
    """Words that join the genes of one list of controls (never across a closing parenthesis)."""
    return GLUE.match(between) is not None and between.count(")") <= between.count("(")


def _normaliser_zone(text: str, clause: Span, genes: list[Found]) -> tuple[list[Found], list[Mark]]:
    """The genes a clause names as its normaliser, and the marks of the cue words."""
    chosen: list[Found] = []
    marks: list[Mark] = []
    for cue in NORMALISER_CUE.finditer(text, clause.start, clause.end):
        if any(m.span.start <= cue.start() < m.span.end for m in marks):
            continue  # "normalised to the geometric mean of …" is one cue
        cursor = cue.end()
        picked = []
        for gene in genes:
            if gene.start < cursor:
                continue
            if not _glue(text[cursor : gene.start]) or gene.status in NOT_NORMALISERS:
                break
            picked.append(gene)
            cursor = gene.end
        if picked:
            chosen += picked
            marks.append(Mark("normaliser", Span(cue.start(), cursor), text[cue.start() : cursor]))
    for cue in AS_REFERENCE.finditer(text, clause.start, clause.end):
        cursor = cue.start()
        picked = []
        for gene in reversed(genes):
            if gene.end > cursor:
                continue
            if not _glue(text[gene.end : cursor]) or gene.status in NOT_NORMALISERS:
                break
            picked.insert(0, gene)
            cursor = gene.start
        if picked:
            chosen += picked
            marks.append(Mark("normaliser", Span(cursor, cue.end()), text[cursor : cue.end()]))
    seen: set[int] = set()
    unique = [g for g in chosen if not (g.start in seen or seen.add(g.start))]
    return unique, marks


def _orientation(text: str, clause: Span, groups: list[GroupFound]) -> tuple[bool, list[Mark]]:
    """True when the clause's words describe the second group relative to the first."""
    marks = [Mark("group", Span(g.start, g.end), g.written) for g in groups]
    focal = None
    for group in groups:
        before = text[clause.start : group.start]
        if BASELINE_CUE.search(before[-40:]):
            if focal is None:
                focal = "b" if group.which == "a" else "a"
            continue
        if focal is None:
            focal = group.which
    return focal == "b", marks


@dataclass
class _ClauseRead:
    """What one clause holds: its gene claims, and what it says without naming a gene."""

    claims: list[Claim]
    normalisers: list[Found]
    marks: list[Mark]  # the normaliser cues and the group words
    orphan: _Window | None = None  # words with no gene ("this did not reach significance")


def _fold_lists(text: str, clause: Span, taken: Sequence[Span]) -> list[FoldValue]:
    """``3.6-, 4.0- and 0.07-fold``: one fold value per number, each written as a fold."""
    out = []
    for match in FOLD_LIST.finditer(text, clause.start, clause.end):
        if _inside(taken, match.start(), match.end()):
            continue
        items = list(re.finditer(NUM, match.group("items")))
        if len(items) < 2:
            continue
        base = match.start("items")
        for i, item in enumerate(items):
            start = base + item.start()
            end = match.end() if i == len(items) - 1 else base + item.end()
            raw = item.group(0)
            value = _float(raw)
            if value <= 0:
                continue
            lo_v, hi_v = _band(value, raw)
            sign = None
            if hi_v <= 1:
                sign, lo_v, hi_v = -1, 1 / hi_v, 1 / max(lo_v, 1e-12)
            mark = Mark("fold", Span(start, end), text[start:end])
            lo, hi = _log2(max(lo_v, 1.0)), _log2(max(hi_v, 1.0))
            out.append(FoldValue(mark, "exact", "fold", value, lo, hi, sign))
    return out


def _clause_claims(text: str, sentence: Span, clause: Span, lexicon: Lexicon) -> _ClauseRead:
    groups = lexicon.groups(text, clause.start, clause.end)
    group_spans = [Span(g.start, g.end) for g in groups]
    genes = [g for g in lexicon.genes(text, clause.start, clause.end)]
    genes = [g for g in genes if not _inside(group_spans, g.start, g.end)]
    norm_genes, norm_marks = _normaliser_zone(text, clause, genes)
    norm_starts = {g.start for g in norm_genes}
    targets = [g for g in genes if g.start not in norm_starts]
    p_values = [_p_value(text, m) for m in P_VALUE.finditer(text, clause.start, clause.end)]
    taken = [p.mark.span for p in p_values] + [Span(g.start, g.end) for g in genes]
    taken += [m.span for m in norm_marks]
    taken += [Span(m.start(), m.end()) for m in N_VALUES.finditer(text, clause.start, clause.end)]
    folds = _fold_lists(text, clause, taken)
    taken += [f.mark.span for f in folds]
    for match in FOLD.finditer(text, clause.start, clause.end):
        if _inside(taken, match.start(), match.end()):
            continue
        value = _fold_value(text, match)
        if value is not None:
            folds.append(value)
    folds.sort(key=lambda f: f.mark.span.start)
    taken += [f.mark.span for f in folds]
    directions = _directions(text, clause, taken + group_spans)
    significance = [
        (("not_significant" if m.lastgroup == "not" else "significant"), m)
        for m in SIGNIFICANCE.finditer(text, clause.start, clause.end)
        if not _inside(taken, m.start(), m.end())
    ]
    robust = [m for m in ROBUST.finditer(text, clause.start, clause.end)]
    inverted, group_marks = _orientation(text, clause, groups)
    if not targets:
        orphan = _Window(
            Found(clause.start, clause.start, "", "", "name", "absent"), *_ends(clause)
        )
        _fill([orphan], directions, folds, p_values, significance, robust)
        return _ClauseRead([], norm_genes, norm_marks + group_marks, orphan)
    windows = []
    for i, gene in enumerate(targets):
        start = clause.start if i == 0 else gene.start
        end = targets[i + 1].start if i + 1 < len(targets) else clause.end
        windows.append(_Window(gene, start, end))
    _fill(windows, directions, folds, p_values, significance, robust)
    respectively = bool(RESPECTIVELY.search(text, clause.start, clause.end))
    all_folds = [f for w in windows for f in w.folds]
    all_ps = [w.p for w in windows if w.p is not None]
    in_one = sum(1 for w in windows if w.folds) == 1
    if len(all_folds) == len(windows) > 1 and (respectively or in_one):
        for w, f in zip(windows, all_folds, strict=True):
            w.folds = [f]
    if respectively and len(all_ps) == len(windows) > 1:
        for w, p in zip(windows, all_ps, strict=True):
            w.p = p
    _share(text, windows)
    # a normaliser named in parentheses belongs to its gene; one in the running text, to all
    local = {id(m): _depth(text, sentence.start, m.span.start) > 0 for m in norm_marks}
    claims = []
    for w in windows:
        if w.empty():
            continue
        mine = [m for m in norm_marks if not local[id(m)] or w.start <= m.span.start < w.end]
        named = [
            g
            for g in norm_genes
            if any(m.span.start <= g.start < m.span.end + 1 for m in mine)
            or any(m.span.start <= g.end <= m.span.end for m in mine)
        ]
        groups_here = [m for m in group_marks if w.start <= m.span.start < w.end] or group_marks
        claims.append(
            _gene_claim(sentence, clause, w, inverted, respectively, mine, named, groups_here)
        )
    return _ClauseRead(claims, norm_genes, norm_marks + group_marks)


def _ends(clause: Span) -> tuple[int, int]:
    return clause.start, clause.end


def _depth(text: str, start: int, pos: int) -> int:
    """How many parentheses are open at ``pos`` (counted from ``start``)."""
    before = text[start:pos]
    return before.count("(") - before.count(")")


def _fill(
    windows: list[_Window],
    directions: list[tuple],
    folds: list[FoldValue],
    p_values: list[PValue],
    significance: list[tuple[str, re.Match[str]]],
    robust: list[re.Match[str]],
) -> None:
    """Give each word of the clause to the gene whose stretch of text it is in."""

    def window_of(pos: int) -> _Window:
        for w in windows:
            if w.start <= pos < w.end:
                return w
        return windows[0] if pos < windows[0].start else windows[-1]

    for pos, direction, mark, negated, hedged, extra in directions:
        w = window_of(pos)
        if w.direction is None or (w.direction[0] == "none" and direction != "none"):
            w.direction = (direction, mark, negated, hedged)
            w.marks += extra
    for fold in folds:
        window_of(fold.mark.span.start).folds.append(fold)
    for p in p_values:
        w = window_of(p.mark.span.start)
        w.p = w.p or p
    for kind, m in significance:
        w = window_of(m.start())
        if w.significance is None or kind == "not_significant":
            w.significance = (kind, Mark("significance", Span(m.start(), m.end()), m.group(0)))
    for m in robust:
        w = window_of(m.start())
        w.robust = w.robust or Mark("robust", Span(m.start(), m.end()), m.group(0))


def _gene_claim(
    sentence: Span,
    clause: Span,
    w: _Window,
    inverted: bool,
    respectively: bool,
    norm_marks: list[Mark],
    norm_genes: list[Found],
    group_marks: list[Mark],
) -> Claim:
    marks = [Mark("gene", Span(w.gene.start, w.gene.end), w.gene.written)]
    direction = w.direction
    fold = w.folds[0] if w.folds else None
    words: Direction | None = direction[0] if direction else None
    if direction is not None:
        marks.append(direction[1])
    elif fold is not None and fold.kind == "percent" and fold.sign is not None:
        words = "up" if fold.sign > 0 else "down"  # "a 72 % decrease" says which way
    marks += w.marks
    for part in (fold.mark if fold else None, w.p.mark if w.p else None, w.robust):
        if part is not None:
            marks.append(part)
    if w.significance is not None:
        marks.append(w.significance[1])
    marks += norm_marks + group_marks
    return Claim(
        kind="gene",
        sentence=sentence,
        clause=clause,
        marks=tuple(sorted(set(marks), key=lambda m: (m.span.start, m.span.end))),
        gene=w.gene.gene,
        gene_status=w.gene.status,
        gene_via=w.gene.via,
        direction=words,
        negated=bool(direction and direction[2]),
        hedged=bool(direction and direction[3]),
        inverted=inverted,
        fold=fold,
        p=w.p,
        significance=w.significance[0] if w.significance else None,  # type: ignore[arg-type]
        robust=w.robust is not None,
        normaliser=tuple(dict.fromkeys(g.gene for g in norm_genes)),
        respectively=respectively,
    )


def _share(text: str, windows: list[_Window]) -> None:
    """Words said once for a list of genes apply to each (``ODC1 and BIRC5 were higher``).

    A gene whose own stretch of text is only list glue (commas, ``and``, a parenthesis) takes
    what it lacks from the next gene to its right that says something; ``…, as was BIRC5``
    takes it from the gene before.
    """

    def listy(w: _Window) -> bool:
        rest = text[w.start : w.end].replace(w.gene.written, " ", 1)
        return LIST_GLUE.match(_strip_marks(rest, w)) is not None

    for i, w in enumerate(windows):
        if w.direction and w.significance and w.robust and w.p:
            continue
        donor = None
        if listy(w):
            for x in windows[i + 1 :]:
                if x.direction or x.significance or x.robust or x.p:
                    donor = x
                    break
                if not listy(x):
                    break
        lead = text[windows[i - 1].gene.end if i else w.start : w.gene.start]
        if donor is None and i and INHERIT_LEFT.search(lead[-30:]):
            donor = next((x for x in reversed(windows[:i]) if not x.empty()), None)
        if donor is None:
            continue
        w.direction = w.direction or donor.direction
        w.significance = w.significance or donor.significance
        w.robust = w.robust or donor.robust
        w.p = w.p or donor.p
        if not w.folds and len(donor.folds) == 1 and listy(w):
            w.folds = list(donor.folds)


def _strip_marks(rest: str, w: _Window) -> str:
    """A window's text without its fold values (``ODC1 (3.6-fold) and``: list glue)."""
    for fold in w.folds:
        rest = rest.replace(fold.mark.written, " ", 1)
    return rest


# ---- study-level claims ----------------------------------------------------------------------


def _efficiency_claim(text: str, sentence: Span, lexicon: Lexicon) -> Claim | None:
    cue = EFFICIENCY_CUE.search(text, sentence.start, sentence.end)
    if cue is None:
        return None
    for match in EFFICIENCY_RANGE.finditer(text, sentence.start, sentence.end):
        g = match.groupdict()
        if g["lo"] is not None:
            lo, hi = _float(g["lo"]), _float(g["hi"])
            if lo > hi:
                continue
            percent = bool(g["lu"] or g["hu"]) or hi > 3
            lo, hi = _band(lo, g["lo"])[0], _band(hi, g["hi"])[1]
        else:
            v = _float(g["v"])
            percent = bool(g["vu"]) or v > 3
            if g["op"].lower().strip() in ("<", "≤", "<=", "below", "under", "less than"):
                lo, hi = 0.0, _band(v, g["v"])[1]
            else:
                lo, hi = _band(v, g["v"])[0], math.inf
        if not percent:  # an amplification factor (1.9–2.1): as a percentage
            lo, hi = (lo - 1) * 100, (hi - 1) * 100 if hi != math.inf else math.inf
        if not (0 <= lo <= 200):
            continue
        named = tuple(
            dict.fromkeys(
                f.gene
                for f in lexicon.genes(text, sentence.start, sentence.end)
                if f.status != "absent"
            )
        )
        span = Span(min(cue.start(), match.start()), max(cue.end(), match.end()))
        marks = (
            Mark("efficiency", Span(cue.start(), cue.end()), cue.group(0)),
            Mark("efficiency", Span(match.start(), match.end()), match.group(0)),
        )
        return Claim(
            kind="efficiency",
            sentence=sentence,
            clause=span,
            marks=marks,
            efficiency=(lo, hi),
            genes=named,
        )
    return None


def _n_claims(text: str, sentence: Span) -> list[Claim]:
    out = []
    for match in N_VALUES.finditer(text, sentence.start, sentence.end):
        g = match.groupdict()
        values = tuple(int(v) for v in (g["a"], g["b"], g["c"], g["d"]) if v is not None)
        mark = Mark("n", Span(match.start(), match.end()), match.group(0))
        out.append(
            Claim(kind="n", sentence=sentence, clause=mark.span, marks=(mark,), n_values=values)
        )
    return out


# ---- the text --------------------------------------------------------------------------------


def extract(text: str, lexicon: Lexicon) -> list[Claim]:
    """Every checkable claim in ``text``, in reading order (at most :data:`MAX_CLAIMS`)."""
    out: list[Claim] = []
    for sentence in sentences(text):
        normalisers: list[Found] = []
        norm_marks: list[Mark] = []
        gene_claims: list[Claim] = []
        previous: list[Claim] = []
        for clause in clauses(text, sentence):
            read = _clause_claims(text, sentence, clause, lexicon)
            if read.orphan is not None and previous:
                previous = [_attach(c, read.orphan) for c in previous]
                gene_claims = gene_claims[: len(gene_claims) - len(previous)] + previous
            if read.claims:
                previous = read.claims
            gene_claims += read.claims
            normalisers += read.normalisers
            norm_marks += [m for m in read.marks if m.role == "normaliser"]
        if normalisers:
            names = tuple(dict.fromkeys(g.gene for g in normalisers))
            running = [m for m in norm_marks if _depth(text, sentence.start, m.span.start) <= 0]
            if running:  # said in the running text: it applies to every gene of the sentence
                gene_claims = [
                    c
                    if c.normaliser
                    else replace(c, normaliser=names, marks=c.marks + tuple(running))
                    for c in gene_claims
                ]
            gene_marks = tuple(Mark("gene", Span(g.start, g.end), g.written) for g in normalisers)
            out.append(
                Claim(
                    kind="normaliser",
                    sentence=sentence,
                    clause=Span(norm_marks[0].span.start, norm_marks[-1].span.end),
                    marks=tuple(sorted(norm_marks + list(gene_marks), key=lambda m: m.span.start)),
                    normaliser=names,
                )
            )
        out += gene_claims
        efficiency = _efficiency_claim(text, sentence, lexicon)
        if efficiency is not None:
            out.append(efficiency)
        out += _n_claims(text, sentence)
    out = _paper_normaliser(out)
    out.sort(key=lambda c: (c.sentence.start, c.clause.start, _first(c)))
    return out[:MAX_CLAIMS]


def _paper_normaliser(claims: list[Claim]) -> list[Claim]:
    """A normaliser stated once for the text applies to every gene claim that names none.

    Only a normaliser in a sentence of its own (no gene claim in it), and only when the text
    states one such set.
    """
    gene_sentences = {c.sentence for c in claims if c.kind == "gene"}
    stated = {
        c.normaliser for c in claims if c.kind == "normaliser" and c.sentence not in gene_sentences
    }
    if len(stated) != 1:
        return claims
    (names,) = stated
    return [
        replace(c, normaliser=names) if c.kind == "gene" and not c.normaliser else c for c in claims
    ]


def _attach(claim: Claim, orphan: _Window) -> Claim:
    """Give the words of a clause that names no gene to the claims of the clause before it.

    ``ODC1 tended to be higher, although this did not reach significance``.
    """
    marks = list(claim.marks)
    changes: dict[str, object] = {}
    if claim.significance is None and orphan.significance is not None:
        changes["significance"] = orphan.significance[0]
        marks.append(orphan.significance[1])
    if claim.p is None and orphan.p is not None:
        changes["p"] = orphan.p
        marks.append(orphan.p.mark)
    if not claim.robust and orphan.robust is not None:
        changes["robust"] = True
        marks.append(orphan.robust)
    if not changes:
        return claim
    return replace(claim, marks=tuple(sorted(set(marks), key=lambda m: m.span.start)), **changes)  # type: ignore[arg-type]


def _first(claim: Claim) -> int:
    return min((m.span.start for m in claim.marks), default=claim.clause.start)
