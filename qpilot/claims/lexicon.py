"""What a study's prose can name: its genes (with their assay names and HGNC aliases) and groups.

A :class:`Lexicon` is built from one study (:meth:`Lexicon.from_study`) or from plain lists (for
tests). It finds, in a text:

* the study's genes, case-insensitively, by their name in the file (``UBC(2)``), by the name
  without assay suffixes (``UBC``, ``PRKACB`` for ``PRKACB_bis``) and by an HGNC alias or
  previous symbol of that gene (``survivin`` for ``BIRC5``, ``TrkA`` for ``NTRK1``) when the alias
  names exactly one approved gene and is not an English word;
* approved HGNC symbols the study did not measure (``GAPDH``), so a claim about one can be
  answered "not measured in this study" instead of being missed;
* the two compared groups, in the words papers use (``MYCN-high`` / ``MYCN-low``, ``the rest``;
  or the design's own group names such as ``KO`` / ``WT``);
* groupings the study does **not** make (``MYCN-amplified`` where the study compares MYCN
  expression, ``high-risk``, ``stage 4``, ``ALK-mutated``), so a claim about those groups is
  answered "a different comparison" instead of being checked against the study's own groups.

:func:`find_genes` is the one resolver of written gene names (a study's name, its name without
an assay suffix, or an unambiguous HGNC alias or previous symbol such as ``survivin`` for
``BIRC5``); the Claim Auditor and Ask both use it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

from qpilot.io.symbols import load_table, normalise_assay_name

GeneStatus = Literal["compared", "reference", "marker", "withheld", "measured"]
Via = Literal["name", "assay", "alias"]

# Approved HGNC symbols that are also everyday words or abbreviations in methods text; never
# read as a gene the study did not measure (a study gene with such a name is still found).
NOT_GENES = frozenset(
    {
        "ACE", "AGA", "ATM", "CAMP", "CAPS", "CAT", "CLOCK", "DEC", "FAT", "HAS", "IMPACT",
        "KIT", "LOX", "MAX", "MET", "NOV", "OCT", "PAN", "RAN", "REST", "SDS", "SET", "SHE",
        "TAP", "WAS",
    }
)  # fmt: skip
# Aliases that read as words or lab shorthand; an alias is used only when it names one gene.
WORDLIKE_ALIASES = frozenset(
    {"ALL", "BRAVO", "CAP", "CI", "DINE", "KO", "LAR", "MIM", "MTC", "ODC", "SD", "TOP", "TRK"}
)
GENE_SHAPE = re.compile(r"(?<![\w-])[A-Z][A-Z0-9]{1,9}(?:-[A-Z0-9]{1,4})?(?![\w(])")


@dataclass(frozen=True)
class Found:
    """One name found in a text."""

    start: int
    end: int
    written: str
    gene: str  # the study's name (or, for an absent gene, the HGNC symbol)
    via: Via
    status: GeneStatus | Literal["absent"]


@dataclass(frozen=True)
class GroupFound:
    """One mention of a group, compared (``a``, ``b``) or not (``other``).

    For ``other``, ``what`` says what the words group by (``MYCN amplification``).
    """

    start: int
    end: int
    written: str
    which: Literal["a", "b", "other"]
    what: str = ""


# Groupings that are not the study's comparison (pattern, what they group by). "gene status"
# (``ALK-mutated``) counts only when its first word is an HGNC symbol or a study gene.
_STATUS_WORDS = (
    r"(?:non[\s-]?)?amplified|amplifications?|mutant|mutated|mutations?|deleted|deletions?"
    r"|positive|negative|translocated|translocations?|rearranged|rearrangements?|wild[\s-]?type"
)
_ARM = r"(?:\d{1,2}|X|Y)[pq](?:\d{1,2}(?:\.\d{1,2})?)?"  # a chromosome arm or band: 1p, 11q23
OTHER_GROUPS: tuple[tuple[str, str], ...] = (
    (r"(?:high|low|intermediate)[\s-]risk", "risk group"),
    (r"stage[\s-]?(?:[1-4][SsAaBb]?|IV|I{1,3}|4S)(?![\w])", "tumour stage"),
    (
        r"(?:non[\s-]?)?metastatic|relapsed|relapsing|recurrent"
        r"|(?:un)?favou?rable\s+(?:histology|outcome|prognosis)|(?:poor|good)\s+(?:outcome|prognosis)"
        r"|died|deceased|(?:non[\s-]?)?survivors",
        "clinical course",
    ),
    (
        r"(?:older|younger)\s+than\s+\d+(?:\.\d+)?\s*(?:months?|years?|weeks?|days?)"
        r"|aged\s+(?:over|under|above|below)\s+\d+",
        "age",
    ),
    (r"(?:male|female)(?=\s+(?:patients|mice|subjects|donors|animals|individuals))", "sex"),
    (
        rf"{_ARM}[\s-]?(?:deleted|deletions?|loss|gain(?:ed)?|amplified|LOH)"
        rf"|(?:loss|gain|deletion)\s+of\s+(?:chromosome\s+)?{_ARM}",
        "a chromosomal change",
    ),
    (rf"[A-Z][A-Z0-9]{{1,9}}[\s-](?:{_STATUS_WORDS})", "gene status"),
    (r"[A-Z][A-Z0-9]{1,9}[\s-]?(?:high|low)(?:[\s-]expressing)?", "gene status"),
)
# In a marker split (samples grouped by a gene's expression), experimental groups are another
# comparison altogether.
EXPERIMENT_GROUPS: tuple[tuple[str, str], ...] = (
    (
        r"KO|WT|knock[\s-]?(?:out|down)|wild[\s-]?type|transgenic|transfected|treated|untreated"
        r"|vehicle[\s-]treated|si[\s-]?RNA|sh[\s-]?RNA",
        "an experimental treatment or genotype",
    ),
    (
        r"hypoxi[ac]|normoxi[ac]|(?:un)?stimulated|(?:un)?infected|(?:un)?exposed",
        "an experimental condition",
    ),
)


@dataclass
class Lexicon:
    """The study's names and groups, ready to be found in prose.

    Attributes:
        compared: Genes with a comparison (a fold change, a CI, a p-value, a call).
        references: The control genes the analysis normalises to (and the other candidates).
        marker: The gene that defines the groups in a marker split (no comparison of its own).
        withheld: Genes the engine withheld, with the reason in words.
        measured: Every other target in the file (no comparison, but measured).
        group_a: The compared group's label (``MYCN-high``, ``KO``).
        group_b: The reference group's label (``rest``, ``WT``).
        group_a_words: Regular expressions for the compared group.
        group_b_words: Regular expressions for the reference group.
        other_group_words: (pattern, what it groups by) for groupings the study does not make;
            :data:`OTHER_GROUPS` is always added.
        basis: What the two groups are defined by, in words (``MYCN expression``), or empty.
    """

    compared: Sequence[str]
    references: Sequence[str] = ()
    marker: str | None = None
    withheld: Mapping[str, str] = field(default_factory=dict)
    measured: Sequence[str] = ()
    group_a: str = "group A"
    group_b: str = "group B"
    group_a_words: Sequence[str] = ()
    group_b_words: Sequence[str] = ()
    other_group_words: Sequence[tuple[str, str]] = ()
    basis: str = ""

    def __post_init__(self) -> None:
        self._status: dict[str, GeneStatus] = {}
        for status, names in (
            ("measured", self.measured),
            ("withheld", self.withheld),
            ("reference", self.references),
            ("compared", self.compared),
        ):
            for name in names:
                self._status[name] = status  # type: ignore[assignment]
        if self.marker:
            self._status[self.marker] = "marker"
        self._pattern, self._names = _gene_pattern(self._status)
        self._groups = _group_pattern(self.group_a_words, self.group_b_words)
        self._others = [
            (re.compile(rf"(?<![\w-])(?:{p})(?![\w])", re.I if "[A-Z]" not in p else 0), what)
            for p, what in (*self.other_group_words, *OTHER_GROUPS)
        ]

    # ---- building ---------------------------------------------------------------------------

    @classmethod
    def from_study(cls, result, design=None) -> Lexicon:  # noqa: ANN001 (StudyResult, StudyDesign)
        """The lexicon of an analysed study (``design`` is the confirmed design, if any)."""
        facts = result.facts
        refs = list(dict.fromkeys([*result.design.refs_primary, *result.genorm.M_initial]))
        withheld = {
            fact.path[len("withheld.") :]: str(fact.value)
            for fid, fact in facts.items()
            if fid.startswith("f_withheld_") and fact.path.startswith("withheld.")
        }
        marker = None
        split = getattr(design, "marker_split", None) if design is not None else None
        if split is not None and getattr(split, "marker", None):
            marker = str(split.marker)
        measured = [g for g in result.efficiency if g not in result.contrasts and g not in refs]
        others: list[tuple[str, str]] = []
        basis = ""
        if "f_group_a" in facts and "f_group_b" in facts:
            a, b = str(facts["f_group_a"].value), str(facts["f_group_b"].value)
            a_words, b_words = named_groups(a, b)
        else:  # labelled as the Results section labels them (``MYCN-high`` / ``rest``)
            name = result.design.group_var.removesuffix("_high") or (marker or "")
            a, b, a_words, b_words = marker_groups(name)
            others = [*marker_other_groups(name), *EXPERIMENT_GROUPS]
            basis = f"{normalise_assay_name(name) or name} expression"
        return cls(
            compared=list(result.contrasts),
            references=refs,
            marker=marker if marker and marker not in result.contrasts else None,
            withheld=withheld,
            measured=measured,
            group_a=a,
            group_b=b,
            group_a_words=a_words,
            group_b_words=b_words,
            other_group_words=others,
            basis=basis,
        )

    # ---- reading ----------------------------------------------------------------------------

    def status(self, gene: str) -> GeneStatus | Literal["absent"]:
        """What the study holds for ``gene`` (one of its names), or ``absent``."""
        return self._status.get(gene, "absent")

    def genes(self, text: str, start: int = 0, end: int | None = None) -> list[Found]:
        """Every study gene and every absent HGNC gene in ``text[start:end]``, in order."""
        end = len(text) if end is None else end
        found: list[Found] = []
        taken: list[tuple[int, int]] = []
        for match in self._pattern.finditer(text, start, end) if self._pattern else ():
            written = match.group(0)
            gene, via = _resolve(self._names, written)
            if gene is None:
                continue
            found.append(Found(match.start(), match.end(), written, gene, via, self._status[gene]))
            taken.append((match.start(), match.end()))
        table = load_table()
        for match in GENE_SHAPE.finditer(text, start, end):
            s, e = match.span()
            symbol = match.group(0)
            if any(a < e and s < b for a, b in taken) or symbol in NOT_GENES:
                continue
            if symbol in table.approved:
                found.append(Found(s, e, symbol, symbol, "name", "absent"))
        return sorted(found, key=lambda f: f.start)

    def groups(self, text: str, start: int = 0, end: int | None = None) -> list[GroupFound]:
        """Every mention of a group in ``text[start:end]``, in order.

        The two compared groups, and groupings the study does not make (``which="other"``).
        """
        end = len(text) if end is None else end
        out: list[GroupFound] = []
        if self._groups is not None:
            for match in self._groups.finditer(text, start, end):
                which = "a" if match.lastgroup == "a" else "b"
                out.append(GroupFound(match.start(), match.end(), match.group(0), which))  # type: ignore[arg-type]
        labels = {x.casefold() for x in (self.group_a, self.group_b) if x and x != "rest"}
        for pattern, what in self._others:
            for match in pattern.finditer(text, start, end):
                s, e = match.span()
                touching = [g for g in out if g.start < e and s < g.end]
                # "MYCN-high" itself, or a phrase another grouping already holds: nothing new
                if any(g.which == "other" or (g.start <= s and e <= g.end) for g in touching):
                    continue
                words = {w.casefold() for w in re.findall(r"[\w+]+", match.group(0))}
                if words & labels:  # "TP53-mutant" in a study whose groups are "mutant" / "WT"
                    continue
                label = what
                if what == "gene status":
                    symbol = re.split(r"[\s-]", match.group(0))[0]
                    known = symbol in self._status or symbol in load_table().approved
                    if symbol in NOT_GENES or not known:
                        continue
                    label = f"{symbol} status"
                # a longer phrase that names another grouping is that grouping: "high MYCN copy
                # number" is not the group "high MYCN"
                out = [g for g in out if g not in touching]
                out.append(GroupFound(s, e, match.group(0), "other", label))
        return sorted(out, key=lambda g: g.start)


# ---- one resolver of written gene names ------------------------------------------------------


def _resolve(
    names: Mapping[str, list[tuple[str, Via, str]]], written: str
) -> tuple[str | None, Via]:
    """The one study gene ``written`` names (None when it names none or more than one)."""
    key = written.casefold()
    # an alias matches regardless of case only when it has four letters or more
    # (``Survivin``, ``TrkA``); a three-letter one must be written as HGNC writes it
    hits = [h for h in names.get(key, []) if h[1] != "alias" or h[2] == written or len(h[2]) >= 4]
    exact = [h for h in hits if h[1] in ("name", "assay")]
    chosen = exact or hits
    genes = {h[0] for h in chosen}
    if len(genes) != 1:
        return None, "name"
    gene = next(iter(genes))
    via = min((h[1] for h in chosen), key=("name", "assay", "alias").index)
    return gene, via  # type: ignore[return-value]


@lru_cache(maxsize=32)
def _names_of(genes: tuple[str, ...]) -> tuple[re.Pattern[str] | None, dict]:
    return _gene_pattern(dict.fromkeys(genes, "compared"))


def find_genes(text: str, genes: Iterable[str]) -> list[Found]:
    """Each of ``genes`` that ``text`` names, in order, however it is written.

    By the name itself (any case), by the name without its assay suffix (``UBC`` for ``UBC(2)``,
    ``PRKACB`` for ``PRKACB_bis``) or by an HGNC alias or previous symbol that names only that
    gene and is not an English word (``survivin`` for ``BIRC5``, ``TrkA`` for ``NTRK1``). A name
    two of the genes share is used only when written exactly. ``Found.status`` is ``compared``.
    """
    pattern, names = _names_of(tuple(dict.fromkeys(str(g) for g in genes)))
    out = []
    for match in pattern.finditer(text) if pattern else ():
        gene, via = _resolve(names, match.group(0))
        if gene is not None:
            out.append(Found(match.start(), match.end(), match.group(0), gene, via, "compared"))
    return out


# ---- helpers ---------------------------------------------------------------------------------


def named_groups(a: str, b: str) -> tuple[list[str], list[str]]:
    """Patterns for a design's two named groups (``KO`` / ``WT``): the names as whole words."""
    return [_word(a)], [_word(b)]


def marker_groups(marker: str) -> tuple[str, str, list[str], list[str]]:
    """Labels and patterns of a marker split: ``MYCN-high`` against the rest (``MYCN-low``…)."""
    short = normalise_assay_name(marker) or marker
    m = re.escape(short)
    a_words = [rf"{m}[\s-]?high(?:[\s-]expressing)?", rf"high[\s-]{m}"]
    b_words = [
        rf"{m}[\s-]?low(?:[\s-]expressing)?",
        rf"low[\s-]{m}",
        r"(?:the\s+)?rest(?:\s+of\s+the\s+(?:tumou?rs|samples|patients))?",
        r"(?:all\s+)?other\s+(?:tumou?rs|samples|patients|cases)",
        r"(?:the\s+)?remaining\s+(?:tumou?rs|samples|patients|cases)",
    ]
    return f"{short}-high", "rest", a_words, b_words


def marker_other_groups(marker: str) -> list[tuple[str, str]]:
    """Groupings by the marker gene that are not its expression level (``MYCN-amplified``).

    A marker split compares the samples with the highest expression of the marker against the
    rest; amplification, mutation, knock-down or a positive/negative status group samples by
    something else, however often the two agree.
    """
    short = normalise_assay_name(marker) or marker
    m = re.escape(short)
    return [
        (rf"{m}[\s-]?(?:non[\s-]?)?amplif(?:ied|ication)|(?:non[\s-]?)?amplif(?:ied|ication)"
         rf"\s+(?:of\s+)?{m}", f"{short} amplification"),
        (rf"{m}[\s-]?(?:copy[\s-]number|gain|deleted|deletion)", f"{short} copy number"),
        (rf"{m}[\s-]?(?:mutant|mutated|mutations?)|(?:mutant|mutated)\s+{m}", f"{short} mutation"),
        (rf"{m}[\s-]?(?:knock[\s-]?(?:out|down|ed[\s-]down)|silenced|depleted|deficient|null)",
         f"{short} knock-down or knock-out"),
        (rf"{m}[\s-]?wild[\s-]?type|wild[\s-]?type\s+{m}", f"{short} genotype"),
        (rf"{m}[\s-]?(?:positive|negative)", f"{short} status (positive or negative)"),
    ]  # fmt: skip


def _word(label: str) -> str:
    """A group label as a whole-word pattern."""
    return rf"(?<![\w-]){re.escape(label)}(?![\w-])"


@lru_cache(maxsize=1)
def _aliases_by_symbol() -> dict[str, tuple[str, ...]]:
    """Approved symbol -> its aliases and previous symbols that name only that gene."""
    table = load_table()
    out: dict[str, list[str]] = {}
    for index in (table.alias, table.previous):
        for alias, approved in index.items():
            if len(approved) != 1 or alias in table.approved or len(alias) < 3:
                continue
            if alias.upper() in WORDLIKE_ALIASES or not any(c.isalpha() for c in alias):
                continue
            (symbol,) = tuple(approved)
            out.setdefault(symbol, []).append(alias)
    return {k: tuple(sorted(set(v))) for k, v in out.items()}


def _gene_pattern(
    status: Mapping[str, str],
) -> tuple[re.Pattern[str] | None, dict[str, list[tuple[str, Via, str]]]]:
    """One pattern for every name of every study gene, and the casefolded name -> genes map."""
    names: dict[str, list[tuple[str, Via, str]]] = {}

    def add(form: str, gene: str, via: Via) -> None:
        if form and len(form) >= 2:
            names.setdefault(form.casefold(), []).append((gene, via, form))

    aliases = _aliases_by_symbol()
    for gene in status:
        add(gene, gene, "name")
        short = normalise_assay_name(gene)
        if short != gene:
            add(short, gene, "assay")
        for alias in aliases.get(short, ()):
            add(alias, gene, "alias")
    # a short name two genes share (PRKACB and PRKACB_bis) is kept only as an exact name
    for key, hits in list(names.items()):
        if len({h[0] for h in hits}) > 1:
            exact = [h for h in hits if h[1] == "name"]
            if exact:
                names[key] = exact
            else:
                del names[key]
    forms = sorted({h[2] for hits in names.values() for h in hits}, key=len, reverse=True)
    if not forms:
        return None, names
    alternatives = "|".join(re.escape(f) for f in forms)
    pattern = re.compile(rf"(?<![\w.])(?:{alternatives})(?![\w])(?!\()", re.I)
    return pattern, names


def _group_pattern(a: Iterable[str], b: Iterable[str]) -> re.Pattern[str] | None:
    a, b = list(a), list(b)
    if not a and not b:
        return None
    parts = []
    if a:
        parts.append(rf"(?P<a>{'|'.join(a)})")
    if b:
        parts.append(rf"(?P<b>{'|'.join(b)})")
    return re.compile(rf"(?<![\w-])(?:{'|'.join(parts)})(?![\w])", re.I)
