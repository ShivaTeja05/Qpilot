"""Check each claim against the study's own record: a verdict from a fixed vocabulary, with why.

The checks, for a claim about one gene (:func:`check_gene`):

1. **The planned analysis** (the study's stored result): the direction against qPilot's call
   (up or down only if p < 0.05 and at least 2-fold), a fold value against the 95 % CI, a
   p-value or a significance word against the p, a robustness word (``robustly``) against the
   share of qPilot's choice grid where the call holds (at least 80 %) and, when the study was
   audited, the audit's verdict.
2. **qPilot's choice grid** (every combination of control genes, group cut-off, empty-well rule
   and amplification-call rule the study was analysed under): the share of analyses where the
   reading holds, and each single choice that makes it hold (or stop holding).
3. **The analysis the text names**: a claim that says which control genes it was normalised to
   is also checked in that cell of the grid.

Verdicts: ``supported`` (holds at the planned analysis), ``choices`` (does not, but holds under
some of the choices qPilot checks; they are named), ``overstated`` (says more than the data),
``contradicted`` (the record says otherwise) and ``unchecked`` (the study cannot answer it).

Every sentence is written with ``{{fact}}`` tokens and passes :func:`qpilot.core.validator.validate`
before it is served: the numbers are the study's facts, facts computed here from the grid
(``origin="grid"``), the audit's (``origin="audit"``) or values quoted from the text itself
(``origin="text"``). Nothing here calls a model.

The grid is read through :mod:`qpilot.web.results_views` (the views that find the planned cell
and the cards' options in it by value), so the page's numbers and these checks agree.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
import pandas as pd

from qpilot.claims.extract import Claim, extract
from qpilot.claims.lexicon import Lexicon
from qpilot.claims.models import (
    VERDICT_LABEL,
    VERDICT_RULE,
    CheckName,
    CheckStatus,
    ClaimCheck,
    ClaimChoice,
    ClaimFact,
    ClaimReading,
    ClaimSegment,
    ClaimSpan,
    ClaimsReport,
    ClaimsSummary,
    ClaimText,
    ClaimView,
    FactOrigin,
    TextRange,
    Verdict,
)
from qpilot.core.facts import slug
from qpilot.core.validator import TOKEN, method_constants, validate
from qpilot.schemas import DecisionCard, Fact, StudyResult

SEVERITY: dict[str, int] = {
    "contradicted": 5,
    "mismatch": 4,
    "overstated": 3,
    "choices": 2,
    "unchecked": 1,
    "supported": 0,
}
WORST: dict[str, int] = {
    "opposite": 4,
    "stronger": 3,
    "weaker": 2,
    "unknown": 1,
    "note": 0,
    "ok": 0,
}
GOOD_AUDIT = ("solid", "holds with caveats")
MAX_CHOICES = 6


# ---- the study's record ----------------------------------------------------------------------


@dataclass
class StudyRecord:
    """Everything a claim is checked against, read once per request."""

    study_id: str
    result: StudyResult
    lexicon: Lexicon
    head: str = ""
    cards: Sequence[DecisionCard] = ()
    grid: Any = None  # qpilot.web.results_views.Grid (None: no grid)
    mapped: Mapping[str, Mapping[int, tuple]] = field(default_factory=dict)
    audit: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    audit_labels: Mapping[str, str] = field(default_factory=dict)
    audit_state: str = "none"  # none / current / older

    @property
    def groups(self) -> tuple[str, str]:
        """The compared group's label and the reference group's."""
        return self.lexicon.group_a, self.lexicon.group_b

    @property
    def phrases(self) -> tuple[str, str]:
        """The groups as a sentence names them (``MYCN-high``, ``the rest``)."""
        a, b = self.groups
        return (f"the {a} group", "the rest") if b == "rest" else (a, b)

    @property
    def alpha(self) -> float:
        """The study's significance level."""
        return float(self.result.conclusion_rule.get("alpha", 0.05))

    @property
    def min_fold(self) -> float:
        """The smallest fold qPilot calls a change."""
        return float(2 ** self.result.conclusion_rule.get("min_log2fc", 1.0))

    def rule_words(self) -> str:
        """The call rule in the words the validator accepts as method, not data."""
        return f"p < {self.alpha:g} and at least {self.min_fold:g}-fold"


def record_of(store: Any, study_id: str) -> StudyRecord:
    """Read a study's record from the store: result, design, cards, grid and audit."""
    from qpilot.web import results_views as rv
    from qpilot.web.views import audit_dir

    result = store.get(study_id)
    try:
        design = store.design(study_id)
    except Exception:  # a study analysed without a confirmed design
        design = None
    head, cards, _ = store.snapshot(study_id)
    grid = rv.load_grid(store, result)
    mapped = rv.card_options(grid, cards) if grid is not None and grid.planned else {}
    audit: dict[str, Any] = {}
    labels: dict[str, str] = {}
    state = "none"
    folder = audit_dir(store, study_id)
    if folder is not None and (folder / "explain.json").exists():
        try:
            audit = json.loads((folder / "explain.json").read_text(encoding="utf-8"))
            manifest = json.loads((folder / "audit_manifest.json").read_text(encoding="utf-8"))
            state = "current" if manifest.get("chain_head") == head else "older"
        except (OSError, ValueError):
            audit, state = {}, "none"
        _, labels = rv._verdicts(store, study_id)
    return StudyRecord(
        study_id=study_id,
        result=result,
        lexicon=Lexicon.from_study(result, design),
        head=head,
        cards=cards,
        grid=grid if grid is not None and grid.planned is not None else None,
        mapped=mapped,
        audit={g: v for g, v in audit.items() if isinstance(v, dict)},
        audit_labels=labels,
        audit_state=state,
    )


# ---- facts and sentences ---------------------------------------------------------------------


class Book:
    """The study's facts plus the ones the checks compute, and sentences made from them."""

    def __init__(self, record: StudyRecord, text: str) -> None:
        from qpilot.qpcr.confidence_checks import HOLDS_MIN

        self.record = record
        self.text = text
        self.facts: dict[str, Fact] = dict(record.result.facts)
        self.origin: dict[str, FactOrigin] = {}
        lex = record.lexicon
        names = {*lex.compared, *lex.references, *lex.withheld, *lex.measured, *record.groups}
        if lex.marker:
            names.add(lex.marker)
        self.names: set[str] = names | method_constants(record.result)
        self.holds_min_value = float(HOLDS_MIN)
        self.holds_min = self.add(
            "f_claims_holds_min",
            HOLDS_MIN,
            "{:.0%}",
            path="qpilot.qpcr.confidence_checks.HOLDS_MIN (the robustness check's threshold)",
            origin="result",
        )

    def t(self, fid: str) -> str:
        """The token of a fact that must exist."""
        if fid not in self.facts:
            raise KeyError(fid)
        return "{{" + fid + "}}"

    def has(self, fid: str) -> bool:
        """True when the fact exists."""
        return fid in self.facts

    def add(
        self,
        fid: str,
        value: float | int | str,
        fmt: str = "{}",
        unit: str = "",
        path: str = "",
        origin: FactOrigin = "grid",
    ) -> str:
        """Register a computed fact (or reuse an equal one) and return its token."""
        fid = fid[:120]
        old = self.facts.get(fid)
        if old is not None and (old.value != value or old.fmt != fmt or old.unit != unit):
            n = 2
            while f"{fid}_{n}" in self.facts:
                n += 1
            fid = f"{fid}_{n}"
        if fid not in self.facts:
            self.facts[fid] = Fact(id=fid, value=value, fmt=fmt, unit=unit, path=path)
            self.origin[fid] = origin
        return "{{" + fid + "}}"

    def quote(self, cid: str, role: str, start: int, end: int) -> str:
        """A value quoted from the text being checked, as a fact (``origin="text"``)."""
        written = self.text[start:end]
        return self.add(
            f"f_text_{cid}_{role}", written, path=f"your text, characters {start}–{end}",
            origin="text",
        )  # fmt: skip

    def say(self, template: str, names: Iterable[str] = ()) -> ClaimText:
        """A sentence from tokens: validated (no naked numbers), split into segments."""
        from qpilot.web.results_views import shown

        allowed = self.names | {n for n in names if n}
        check = validate(template, self.facts, allowed)
        if not check.ok:
            raise ValueError(f"claims sentence failed the validator: {check.error()}: {template!r}")
        segments: list[ClaimSegment] = []
        cited: dict[str, ClaimFact] = {}
        last = 0
        for match in TOKEN.finditer(template):
            if match.start() > last:
                segments.append(ClaimSegment(text=template[last : match.start()]))
            fid = match.group(1)
            fact = self.facts[fid]
            # a value quoted from the checked text reads as a quotation
            words = f"“{shown(fact)}”" if self.origin.get(fid) == "text" else shown(fact)
            segments.append(ClaimSegment(text=words, fact=fid))
            cited.setdefault(
                fid,
                ClaimFact(
                    id=fid,
                    text=shown(fact),
                    value=fact.value,
                    unit=fact.unit,
                    path=fact.path,
                    origin=self.origin.get(fid, "result"),
                ),
            )
            last = match.end()
        if last < len(template):
            segments.append(ClaimSegment(text=template[last:]))
        merged: list[ClaimSegment] = []
        for seg in segments:
            if merged and seg.fact is None and merged[-1].fact is None:
                merged[-1] = ClaimSegment(text=merged[-1].text + seg.text)
            else:
                merged.append(seg)
        return ClaimText(
            plain="".join(s.text for s in merged), segments=merged, facts=list(cited.values())
        )


def _join(items: Sequence[str], last: str = "and") -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {last} " + items[-1]


def _gene_facts(book: Book, gene: str) -> dict[str, str]:
    """Tokens of a compared gene's stored facts (computed here when one is missing)."""
    result = book.record.result
    c = result.contrasts[gene]
    s = slug(gene)
    base = f"contrasts.{gene}"

    def fact(fid: str, value: float, fmt: str, unit: str, path: str) -> str:
        return book.t(fid) if book.has(fid) else book.add(fid, value, fmt, unit, path, "result")

    out = {
        "fc": fact(f"f_fc_{s}_recommended", c.fc, "{:.2g}", "×", f"{base}.fc"),
        "lo": fact(f"f_ci_lo_{s}_recommended", c.ci[0], "{:.2g}", "×", f"{base}.ci[0]"),
        "hi": fact(f"f_ci_hi_{s}_recommended", c.ci[1], "{:.2g}", "×", f"{base}.ci[1]"),
        "p": fact(f"f_p_{s}_recommended", c.p, "{:.2g}", "", f"{base}.p"),
    }
    robust = result.robustness.get(gene)
    if robust is not None:
        out["holds"] = fact(f"f_holds_{s}", robust.holds, "{:.0%}", "", f"robustness.{gene}.holds")
        out["cells"] = book.add(
            "f_claims_n_cells", robust.n_cells, path="robustness (analyses qPilot checks)",
            origin="result",
        )  # fmt: skip
    return out


def _paper_p(book: Book, gene: str) -> str:
    """The p as a paper writes it: ``< 0.001``, else two significant digits."""
    p = book.record.result.contrasts[gene].p
    text = "< 0.001" if p < 0.001 else f"= {float(f'{p:.2g}'):g}"
    return book.add(
        f"f_claims_ptext_{slug(gene)}", text, path=f"contrasts.{gene}.p (as a paper writes it)",
        origin="result",
    )  # fmt: skip


def _call_word(call: str) -> str:
    return {"up": "up", "down": "down"}.get(call, "no change")


# ---- the grid --------------------------------------------------------------------------------


@dataclass
class Reading:
    """A gene claim reduced to what can be compared with numbers."""

    direction: str | None  # up / down / none, for the first group against the second
    hedged: bool
    sign: int  # the direction the fold band points (+1 / -1)
    band: tuple[float, float] | None  # signed log2 band the fold words allow
    comparator: str | None
    p_op: str | None
    p_value: float | None
    p_band: tuple[float, float] | None
    significance: str | None
    # the planned analysis's 95 % CI around its estimate (log2 below, above): the grid holds no
    # intervals, so each analysis is given this width around its own estimate
    ci_width: tuple[float, float] = (0.0, 0.0)
    # "interval": a fold holds where it is within the analysis's interval (is the claim still
    # true there?); "estimate": where the analysis's estimate is the fold written (which
    # analysis gives the number the text reports?)
    mode: str = "interval"


def reading_of(claim: Claim, contrast: Any) -> Reading:
    """The comparable reading of a gene claim (group order and fold sign applied)."""
    d = claim.direction
    if claim.inverted and d in ("up", "down"):
        d = "down" if d == "up" else "up"
    fold = claim.fold
    sign = 0
    if fold is not None and fold.sign is not None:
        sign = fold.sign * (-1 if claim.inverted else 1)
    if not sign:
        sign = 1 if d == "up" else -1 if d == "down" else (1 if contrast.log2fc >= 0 else -1)
    band = None
    if fold is not None:
        lo, hi = fold.lo, fold.hi
        band = (lo, hi) if sign > 0 else (-hi, -lo)
    p_op = p_value = p_band = None
    if claim.p is not None and not claim.p.adjusted:
        p_op, p_value, p_band = claim.p.op, claim.p.value, (claim.p.lo, claim.p.hi)
    return Reading(
        direction=d,
        hedged=claim.hedged,
        sign=sign,
        band=band,
        comparator=fold.comparator if fold else None,
        p_op=p_op,
        p_value=p_value,
        p_band=p_band,
        significance=claim.significance,
        ci_width=(
            max(contrast.log2fc - math.log2(contrast.ci[0]), 0.0),
            max(math.log2(contrast.ci[1]) - contrast.log2fc, 0.0),
        ),
    )


def holds_mask(rows: pd.DataFrame, reading: Reading, alpha: float) -> np.ndarray:
    """Which analyses (grid rows of one gene) the reading holds in."""
    log2fc = rows["log2fc"].to_numpy(dtype=float)
    p = rows["p"].to_numpy(dtype=float)
    call = rows["conclusion"].astype(str).to_numpy()
    mask = np.isfinite(log2fc)
    d = reading.direction
    if d in ("up", "down"):
        if reading.hedged:
            mask &= np.sign(log2fc) == (1 if d == "up" else -1)
        else:
            mask &= call == d
    elif d == "none":
        mask &= call == "none"
    if reading.band is not None:
        lo, hi = reading.band
        if reading.comparator in ("at_least", "at_most") or reading.mode == "estimate":
            mask &= (log2fc >= lo) & (log2fc <= hi)
        else:  # the value is within the analysis's interval
            below, above = reading.ci_width
            mask &= (log2fc + above >= lo) & (log2fc - below <= hi)
    if reading.p_op is not None and reading.p_value is not None:
        with np.errstate(invalid="ignore"):
            if reading.p_op == "<":
                mask &= p < reading.p_value
            elif reading.p_op == "<=":
                mask &= p <= reading.p_value
            elif reading.p_op in (">", ">="):
                mask &= p > reading.p_value if reading.p_op == ">" else p >= reading.p_value
            elif reading.mode == "estimate" and reading.p_band is not None:
                mask &= (p >= reading.p_band[0]) & (p <= reading.p_band[1])
            elif reading.p_value < alpha:  # "p = 0.003" stays true wherever p stays below it
                mask &= p <= reading.p_band[1] if reading.p_band else p < alpha
    with np.errstate(invalid="ignore"):
        if reading.significance == "significant" and not reading.hedged:
            mask &= p < alpha
        elif reading.significance == "not_significant":
            mask &= p >= alpha
    return mask


def _choice_label(book: Book, record: StudyRecord, dim: str, idx: int) -> tuple[str, Any]:
    """A choice's words as a token (labels can hold digits) and its card mapping."""
    from qpilot.web import results_views as rv

    grid = record.grid
    value = grid.options[dim][idx]
    card = record.mapped.get(dim, {}).get(idx)
    label = card[2] if card else rv.option_label(dim, value)
    token = book.add(
        f"f_claims_choice_{slug(dim)}_{idx}", label, path=f"grid.options.{dim}[{idx}] = {value}",
        origin="grid",
    )  # fmt: skip
    return token, card


def one_choice(
    book: Book, record: StudyRecord, gene: str, reading: Reading, planned_holds: bool
) -> list[ClaimChoice]:
    """Single choices (one decision changed, the rest as planned) that flip the reading."""
    from qpilot.web.results_views import DIMENSION_TITLE, IDX

    grid = record.grid
    out: list[ClaimChoice] = []
    for dim in grid.dimensions:
        rows = grid.one_at_a_time(dim)
        rows = rows[rows["item"] == gene]
        if rows.empty:
            continue
        mask = holds_mask(rows, reading, record.alpha)
        for (_, row), ok in zip(rows.iterrows(), mask, strict=True):
            idx = int(row[dim + IDX])
            if idx == grid.planned[dim] or bool(ok) == planned_holds:
                continue
            token, card = _choice_label(book, record, dim, idx)
            out.append(
                ClaimChoice(
                    dimension=dim,
                    title=DIMENSION_TITLE.get(dim, dim),
                    option=grid.options[dim][idx],
                    label=book.say(token),
                    card_id=card[0] if card else None,
                    option_id=card[1] if card else None,
                    holds=bool(ok),
                    call=str(row["conclusion"])
                    if str(row["conclusion"]) in ("up", "down", "none")
                    else None,  # type: ignore[arg-type]
                    fc=float(row["fc"]) if math.isfinite(float(row["fc"])) else None,
                )
            )
    if reading.mode == "estimate" and reading.band is not None:
        centre = sum(x for x in reading.band if math.isfinite(x)) / max(
            1, sum(1 for x in reading.band if math.isfinite(x))
        )
        out.sort(key=lambda c: abs(math.log2(c.fc) - centre) if c.fc else math.inf)
    else:
        out.sort(key=lambda c: (c.card_id is None, c.dimension, c.option))
    return out[:MAX_CHOICES]


def nearest_combination(
    record: StudyRecord, gene: str, reading: Reading
) -> tuple[int, dict[str, int]] | None:
    """The holding analysis that changes the fewest decisions from the planned one."""
    from qpilot.web.results_views import IDX

    grid = record.grid
    rows = grid.item(gene)
    mask = holds_mask(rows, reading, record.alpha)
    if not mask.any():
        return None
    hit = rows[mask]
    cols = [d + IDX for d in grid.dimensions]
    planned = np.array([grid.planned[d] for d in grid.dimensions])
    changes = (hit[cols].to_numpy(dtype=int) != planned).sum(axis=1)
    best = int(np.argmin(changes))
    cell = {d: int(hit.iloc[best][d + IDX]) for d in grid.dimensions}
    return int(changes[best]), cell


def refs_cell(record: StudyRecord, names: Sequence[str]) -> int | None:
    """The grid's control-gene option equal to this set of genes (None if it has none)."""
    grid = record.grid
    if grid is None or "refs" not in grid.dimensions:
        return None
    wanted = set(names)
    for idx, value in enumerate(grid.options["refs"]):
        if set(value.split("|")) == wanted:
            return idx
    return None


# ---- one claim -------------------------------------------------------------------------------


@dataclass
class Outcome:
    """A claim's verdict and the material for its view."""

    verdict: Verdict
    checks: list[ClaimCheck]
    headline: ClaimText
    choices: list[ClaimChoice] = field(default_factory=list)
    grid_holds: int | None = None
    grid_cells: int | None = None
    audit_verdict: str | None = None
    audit_label: str | None = None
    suggestion: ClaimText | None = None
    gene: str | None = None


def _check(name: CheckName, status: CheckStatus, text: ClaimText) -> ClaimCheck:
    return ClaimCheck(check=name, status=status, text=text)


def _unchecked(book: Book, gene: str, status: str | None) -> Outcome:
    lex = book.record.lexicon
    a, b = book.record.phrases
    if status == "absent":
        sentence = f"{gene} is not measured in this study, so its record cannot check this."
    elif status == "reference":
        sentence = (
            f"{gene} is a control gene here: the other genes are normalised to it, so it has "
            "no comparison of its own."
        )
    elif status == "marker":
        sentence = f"{gene} defines the two groups ({a} against {b}), so it is not compared."
    elif status == "withheld":
        fid = f"f_withheld_{slug(gene)}"
        reason = book.t(fid) if book.has(fid) else str(lex.withheld.get(gene, ""))
        sentence = f"{gene} was not compared: {reason}."
    else:
        sentence = f"{gene} is in the file but was not compared between the groups."
    text = book.say(sentence, [gene])
    return Outcome("unchecked", [_check("gene", "unknown", text)], text)


def _groups_words(book: Book, claim: Claim, cid: str) -> tuple[str, list[str]]:
    """What the study compares and what the claim's words compare instead, as a sentence."""
    record = book.record
    lex = record.lexicon
    a, b = record.phrases
    written, what = claim.other_groups[0]
    mark = next(
        (m for m in claim.marks if m.role == "group" and m.written == written), None
    )  # the first such group in the claim's words
    quoted = book.quote(cid, "group", mark.span.start, mark.span.end) if mark else written
    names = [lex.group_a, lex.group_b, what, lex.basis]
    if lex.basis and lex.group_b == "rest":
        short = lex.basis.removesuffix(" expression")
        ours = f"{lex.group_a} against {short}-low expression (the rest)"
        names.append(f"{short}-low")
    else:
        ours = f"{a} against {b}"
    return f"This study compares {ours}, not {what} ({quoted})", names


def _span_of(claim: Claim, written: str) -> tuple[int, int]:
    """Where the claim's words ``written`` are (the first mark that wrote them)."""
    mark = next(m for m in claim.marks if m.written == written)
    return mark.span.start, mark.span.end


def _mismatch(book: Book, claim: Claim, cid: str, gene: str) -> Outcome:
    """A claim about groups the study does not compare: its numbers do not test it."""
    words, names = _groups_words(book, claim, cid)
    text = book.say(f"{words}: its numbers do not test this claim.", [gene, *names])
    return Outcome(
        "mismatch",
        [_check("groups", "opposite", text)],
        text,
        suggestion=suggest_gene(book, gene),
        gene=gene,
    )


def _normaliser_source(book: Book, claim: Claim, cid: str) -> str:
    """Where a claim's normaliser was read, when not in its own sentence (with a quotation)."""
    if claim.normaliser_from is None or claim.normaliser_scope in (None, "own"):
        return ""
    where = book.quote(cid, "normaliser", claim.normaliser_from.start, claim.normaliser_from.end)
    return {
        "text": f"Your text states once, for all the data, how it was normalised ({where}); "
        "read as applying to this claim. ",
        "previous": f"The sentence after this claim says how it was normalised ({where}). ",
        "gene": f"Another sentence says how this gene was normalised ({where}). ",
    }[claim.normaliser_scope]


def check_gene(book: Book, claim: Claim, cid: str) -> Outcome:
    """The verdict on a claim about one gene."""
    record = book.record
    gene = claim.gene or ""
    if claim.gene_status != "compared" or gene not in record.result.contrasts:
        return _unchecked(book, gene, claim.gene_status)
    if claim.relation:
        quoted = book.quote(cid, "relation", *_span_of(claim, claim.relation))
        text = book.say(
            f"Your sentence relates {gene} to another measure ({quoted}); this study compares "
            "two groups and computes no correlation, so it cannot check this.",
            [gene],
        )
        return Outcome("unchecked", [_check("reading", "unknown", text)], text, gene=gene)
    if claim.other_groups and not claim.names_groups:
        return _mismatch(book, claim, cid, gene)
    a, b = record.phrases
    contrast = record.result.contrasts[gene]
    f = _gene_facts(book, gene)
    reading = reading_of(claim, contrast)
    names = [gene, *claim.normaliser]
    checks: list[ClaimCheck] = []
    if claim.other_groups:  # "MYCN-high (MYCN-amplified) tumours": read as the study's groups
        words, extra = _groups_words(book, claim, cid)
        names += extra
        checks.append(
            _check(
                "groups",
                "note",
                book.say(f"{words}; read as the study's own groups.", names),
            )
        )
    estimate = f"fold {f['fc']} (95 % CI {f['lo']}–{f['hi']}), p {f['p']}"
    call = contrast.conclusion
    d = reading.direction

    # 1. direction
    if d in ("up", "down"):
        same_sign = (contrast.log2fc > 0) == (d == "up")
        if reading.hedged:
            status: CheckStatus = "ok" if same_sign else "opposite"
            words = "points the same way" if same_sign else "points the other way"
            text = f"The study's fold for {gene} {words}: {estimate}."
        elif call == d:
            status, text = "ok", f"The study calls {gene} {d} in {a} against {b}: {estimate}."
        elif call in ("up", "down"):
            status, text = "opposite", f"The study calls {gene} {call}, not {d}: {estimate}."
        elif same_sign:
            status = "stronger"
            text = (
                f"The study calls no change for {gene}: {estimate}; qPilot calls a change only "
                f"if {record.rule_words()}."
            )
        else:
            status = "opposite"
            text = (
                f"The study's fold for {gene} points the other way, and no change is "
                f"called: {estimate}."
            )
        checks.append(_check("direction", status, book.say(text, names)))
    elif d == "none":
        if call == "none":
            status, text = "ok", f"The study calls no change for {gene}: {estimate}."
        else:
            status, text = (
                "opposite",
                f"The study calls {gene} {call} in {a} against {b}: {estimate}.",
            )
        checks.append(_check("direction", status, book.say(text, names)))

    # 2. the fold value
    fold = claim.fold
    if fold is not None and reading.band is not None:
        written = book.quote(cid, "fold", fold.mark.span.start, fold.mark.span.end)
        s = reading.sign
        # everything in the direction the fold points: s × log2 (so "larger" means further out)
        ci_near, ci_far = sorted((s * math.log2(contrast.ci[0]), s * math.log2(contrast.ci[1])))
        near_token = f["lo"] if s > 0 else f["hi"]
        point = s * contrast.log2fc
        if fold.comparator == "at_least":
            if point >= fold.lo:
                status = "ok"
                text = f"The study's fold, {f['fc']}, is beyond the {written} you wrote"
                if ci_near < fold.lo:
                    text += f", though its 95 % CI reaches {near_token}"
                text += "."
            else:
                status = "stronger"
                text = (
                    f"The study's fold, {f['fc']} (95 % CI {f['lo']}–{f['hi']}), does not "
                    f"reach the {written} you wrote."
                )
        elif fold.comparator == "at_most":
            if point <= fold.hi:
                status, text = (
                    "ok",
                    f"The study's fold, {f['fc']}, is within the {written} you wrote.",
                )
            else:
                status = "weaker"
                text = (
                    f"The study's fold, {f['fc']} (95 % CI {f['lo']}–{f['hi']}), is "
                    f"larger than the {written} you wrote."
                )
        elif fold.hi >= ci_near and fold.lo <= ci_far:
            status = "ok"
            text = (
                f"The fold you wrote, {written}, is within the study's 95 % CI "
                f"({f['lo']}–{f['hi']}; estimate {f['fc']})."
            )
        elif fold.lo > ci_far:
            status = "stronger"
            text = (
                f"The fold you wrote, {written}, is larger than the study's 95 % CI "
                f"allows ({f['lo']}–{f['hi']}; estimate {f['fc']})."
            )
        else:
            status = "weaker"
            text = (
                f"The fold you wrote, {written}, is smaller than the study's 95 % CI "
                f"allows ({f['lo']}–{f['hi']}; estimate {f['fc']})."
            )
        checks.append(_check("fold", status, book.say(text, names)))

    # 3. the p-value and significance words
    if claim.p is not None:
        written = book.quote(cid, "p", claim.p.mark.span.start, claim.p.mark.span.end)
        p = contrast.p
        if claim.p.adjusted:
            status = "unknown"
            text = (
                f"qPilot computes no adjusted p (q-value, FDR), so {written} cannot be "
                f"checked; the study's unadjusted p for {gene} is {f['p']}."
            )
        elif claim.p.op in ("<", "<="):
            ok = p < claim.p.value if claim.p.op == "<" else p <= claim.p.value
            status = "ok" if ok else "stronger"
            text = (
                f"The study's p for {gene} is {f['p']}, which "
                f"{'satisfies' if ok else 'does not satisfy'} {written}."
            )
        elif claim.p.op in (">", ">="):
            ok = p > claim.p.value if claim.p.op == ">" else p >= claim.p.value
            status = "ok" if ok else "weaker"
            text = (
                f"The study's p for {gene} is {f['p']}, which "
                f"{'satisfies' if ok else 'does not satisfy'} {written}."
            )
        elif claim.p.lo <= p <= claim.p.hi:
            status, text = "ok", f"The study's p for {gene} is {f['p']}, which matches {written}."
        elif p < claim.p.lo:
            status, text = (
                "weaker",
                f"The study's p for {gene} is {f['p']}, smaller than the {written} you wrote.",
            )
        else:
            status, text = (
                "stronger",
                f"The study's p for {gene} is {f['p']}, larger than the {written} you wrote.",
            )
        checks.append(_check("p", status, book.say(text, names)))
    if claim.significance is not None and not (claim.p is not None and not claim.p.adjusted):
        below = contrast.p < record.alpha
        level = f"its significance level {record.alpha:g}"
        if claim.significance == "significant":
            status = "ok" if below else "stronger"
            text = (
                f"The study's p for {gene}, {f['p']}, is "
                f"{'below' if below else 'not below'} {level}."
            )
        else:
            status = "weaker" if below else "ok"
            text = (
                f"The study's p for {gene}, {f['p']}, is "
                f"{'below' if below else 'not below'} {level}."
            )
        checks.append(_check("significance", status, book.say(text, names)))

    # 4. robustness words
    robust = record.result.robustness.get(gene)
    audit = record.audit.get(gene)
    audit_bits = ""
    audit_verdict = audit_label = None
    if audit is not None:
        audit_verdict = str(audit.get("verdict"))
        audit_label = record.audit_labels.get(audit_verdict, audit_verdict)
        label = book.add(
            f"f_claims_audit_verdict_{slug(gene)}", audit_label,
            path=f"simulator_audits/{record.study_id}/explain.json: {gene}.verdict", origin="audit",
        )  # fmt: skip
        n_def = int(audit.get("analyses_defensible") or 0)
        share = float(audit.get("holds_defensible") or 0.0)
        if n_def:
            k = book.add(
                f"f_claims_audit_k_{slug(gene)}", int(round(share * n_def)),
                path=f"explain.json: {gene}.holds_defensible × analyses_defensible", origin="audit",
            )  # fmt: skip
            n = book.add(
                f"f_claims_audit_n_{slug(gene)}", n_def,
                path=f"explain.json: {gene}.analyses_defensible", origin="audit",
            )  # fmt: skip
            audit_bits = f"{label} (same call in {k} of {n} of the audit's reasonable analyses)"
        else:
            audit_bits = label
    if claim.robust and robust is not None:
        rmark = claim.mark("robust")
        written = book.quote(cid, "robust", rmark.span.start, rmark.span.end) if rmark else ""
        holds_ok = robust.holds >= book.holds_min_value
        audit_ok = audit is None or str(audit.get("verdict")) in GOOD_AUDIT
        direction_ok = call == d if d in ("up", "down", "none") else True
        if holds_ok and audit_ok and direction_ok:
            status = "ok"
            text = (
                f"{written} is earned: the call holds in {f['holds']} of the "
                f"{f['cells']} analyses qPilot checks"
            )
        else:
            status = "stronger"
            text = (
                f"{written} says more than the study shows: the call holds in "
                f"{f['holds']} of the {f['cells']} analyses qPilot checks"
            )
            if not holds_ok:
                text += f" (fewer than {book.holds_min})"
        if audit_bits:
            text += f", and the robustness audit's verdict is {audit_bits}"
        checks.append(_check("robust", status, book.say(text + ".", names)))

    # 5. the analysis the text names (its control genes)
    planned_refs = list(record.result.design.refs_primary)
    named_holds: bool | None = None
    named_choice: ClaimChoice | None = None
    if claim.normaliser:
        absent = [g for g in claim.normaliser if record.lexicon.status(g) == "absent"]
        listed = _join(planned_refs)
        source = _normaliser_source(book, claim, cid)
        if absent:
            checks.append(
                _check(
                    "normaliser",
                    "note",
                    book.say(
                        f"{source}Your text normalises to {_join(absent)}, which this study did "
                        f"not measure; checked against qPilot's planned set ({listed}) instead.",
                        names,
                    ),
                )
            )
        elif set(claim.normaliser) == set(planned_refs) and source:
            checks.append(
                _check(
                    "normaliser",
                    "ok",
                    book.say(f"{source}It is qPilot's planned set ({listed}).", names),
                )
            )
        elif set(claim.normaliser) != set(planned_refs) and record.grid is not None:
            idx = refs_cell(record, claim.normaliser)
            if idx is None:
                checks.append(
                    _check(
                        "normaliser",
                        "note",
                        book.say(
                            f"{source}Your text normalises to {_join(claim.normaliser)}, a set "
                            f"qPilot's grid does not hold; checked against the planned set "
                            f"({listed}).",
                            names,
                        ),
                    )
                )
            else:
                named_choice, named_holds = _named_cell(book, record, gene, reading, idx)
                if named_choice is not None:
                    fc = book.add(
                        f"f_claims_fc_{slug(gene)}_refs_{idx}", named_choice.fc or 0.0, "{:.2g}",
                        "×", f"grid.csv: {gene} with refs = {record.grid.options['refs'][idx]}, "
                        "other choices as planned",
                    )  # fmt: skip
                    word = "holds" if named_holds else "does not hold"
                    checks.append(
                        _check(
                            "normaliser",
                            "ok" if named_holds else "note",
                            book.say(
                                f"{source}Your text normalises to {_join(claim.normaliser)}; "
                                f"qPilot's planned set is {listed}. With your set the fold for "
                                f"{gene} is {fc} and the call is "
                                f"{_call_word(named_choice.call or '')}: the claim {word} there.",
                                names,
                            ),
                        )
                    )

    # 6. the grid: where the reading holds
    statuses = [c.status for c in checks if c.check in ("direction", "fold", "p", "significance")]
    planned_ok = all(s in ("ok", "unknown", "note") for s in statuses) and bool(statuses)
    robust_failed = any(c.check == "robust" and c.status == "stronger" for c in checks)
    grid_k = grid_n = None
    choices: list[ClaimChoice] = []
    combination = None
    if record.grid is not None and statuses:
        if not planned_ok:  # which analyses give what the text reports?
            reading = replace(reading, mode="estimate")
        rows = record.grid.item(gene)
        mask = holds_mask(rows, reading, record.alpha)
        grid_k, grid_n = int(mask.sum()), int(len(mask))
        share = book.add(
            f"f_claims_{cid}_grid_share", grid_k / grid_n if grid_n else 0.0, "{:.0%}",
            path=f"grid.csv: {gene}, analyses where this reading holds ({grid_k} of {grid_n})",
        )  # fmt: skip
        cells = book.add("f_claims_n_grid", grid_n, path=f"grid.csv: analyses of {gene}")
        checks.append(
            _check(
                "grid",
                "note",
                book.say(_grid_words(reading, share, cells, grid_k), names),
            )
        )
        choices = one_choice(book, record, gene, reading, planned_ok)
        if not planned_ok and not any(c.holds for c in choices):
            combination = nearest_combination(record, gene, reading)
        if choices:
            tokens = _join([_tokens(c.label) for c in choices[:3]], "or")
            if len(choices) > 3:
                more = book.add(
                    f"f_claims_{cid}_more", len(choices) - 3, path="grid.csv: more single choices"
                )
                tokens += f" (and {more} more)"
            if planned_ok:
                text = f"It stops holding with one choice changed: {tokens}."
            else:
                text = f"Not in the planned analysis, but with one choice changed: {tokens}."
            checks.append(_check("choices", "note", book.say(text, names)))
        elif combination is not None:
            n_changes, cell = combination
            parts = []
            for dim, idx in cell.items():
                if idx != record.grid.planned[dim]:
                    token, _ = _choice_label(book, record, dim, idx)
                    parts.append(token)
            k = book.add(f"f_claims_{cid}_changes", n_changes, path="grid.csv: decisions changed")
            checks.append(
                _check(
                    "choices",
                    "note",
                    book.say(
                        (
                            f"Not in the planned analysis; it holds only when {k} choices "
                            f"change together, for example {_join(parts)}."
                        ),
                        names,
                    ),
                )
            )
    if audit_bits and not claim.robust:
        checks.append(
            _check(
                "audit",
                "note",
                book.say(f"The robustness audit's verdict for {gene}: {audit_bits}.", names),
            )
        )

    # 7. the verdict
    worst = max((WORST[s] for s in statuses), default=0)
    if not statuses and not claim.robust:
        text = book.say(
            f"Nothing in this sentence about {gene} can be compared with the study.", names
        )
        return Outcome("unchecked", [_check("reading", "unknown", text)], text, gene=gene)
    if planned_ok:
        verdict: Verdict = "overstated" if robust_failed else "supported"
    elif named_holds:
        verdict = "choices"
    elif (
        grid_k
        and not (robust_failed and worst < WORST["weaker"])
        and (worst < WORST["opposite"] or any(c.holds for c in choices))
    ):  # the other direction is rescued only by one choice, never by a combination
        verdict = "choices"
    elif worst == WORST["opposite"]:
        verdict = "contradicted"
    elif worst == WORST["stronger"] or robust_failed:
        verdict = "overstated"
    else:
        verdict = "contradicted"
    if (
        named_holds
        and named_choice is not None
        and not any(c.option == named_choice.option for c in choices)
    ):
        choices.insert(0, named_choice)
    headline = _headline(checks, verdict)
    return Outcome(
        verdict=verdict,
        checks=checks,
        headline=headline,
        choices=choices,
        grid_holds=grid_k,
        grid_cells=grid_n,
        audit_verdict=audit_verdict,
        audit_label=audit_label,
        suggestion=None if verdict == "supported" else suggest_gene(book, gene, choices),
        gene=gene,
    )


def _tokens(text: ClaimText) -> str:
    """A ClaimText back to its token form (to embed it in another sentence)."""
    return "".join(s.text if s.fact is None else "{{" + s.fact + "}}" for s in text.segments)


def _grid_words(reading: Reading, share: str, cells: str, k: int) -> str:
    """The grid line, saying what "holds" meant for a fold value."""
    if reading.band is None:
        return f"This reading holds in {share} of the {cells} analyses qPilot checks."
    if reading.mode == "estimate" and k == 0:
        return f"None of the {cells} analyses qPilot checks gives the values you wrote."
    if reading.mode == "estimate":
        return (
            f"The values you wrote match the estimates of {share} of the {cells} analyses "
            "qPilot checks."
        )
    if reading.comparator in ("at_least", "at_most"):
        return (
            f"This reading holds in {share} of the {cells} analyses qPilot checks (by "
            "their estimates)."
        )
    return (
        f"This reading holds in {share} of the {cells} analyses qPilot checks (the fold counts "
        "when it is within an analysis's estimate give or take the planned 95 % CI's width)."
    )


def _named_cell(
    book: Book, record: StudyRecord, gene: str, reading: Reading, idx: int
) -> tuple[ClaimChoice | None, bool | None]:
    from qpilot.web.results_views import DIMENSION_TITLE, IDX

    rows = record.grid.one_at_a_time("refs")
    rows = rows[(rows["item"] == gene) & (rows["refs" + IDX] == idx)]
    if rows.empty:
        return None, None
    ok = bool(holds_mask(rows, reading, record.alpha)[0])
    row = rows.iloc[0]
    token, card = _choice_label(book, record, "refs", idx)
    call = str(row["conclusion"])
    return (
        ClaimChoice(
            dimension="refs",
            title=DIMENSION_TITLE.get("refs", "refs"),
            option=record.grid.options["refs"][idx],
            label=book.say(token),
            card_id=card[0] if card else None,
            option_id=card[1] if card else None,
            planned=idx == record.grid.planned["refs"],
            holds=ok,
            call=call if call in ("up", "down", "none") else None,  # type: ignore[arg-type]
            fc=float(row["fc"]) if math.isfinite(float(row["fc"])) else None,
        ),
        ok,
    )


def _headline(checks: Sequence[ClaimCheck], verdict: Verdict) -> ClaimText:
    """The check that decided the verdict."""
    main = [c for c in checks if c.check not in ("grid", "audit", "choices")]
    if verdict == "supported":
        for name in ("robust", "fold", "direction", "p", "significance"):
            hit = next((c for c in main if c.check == name and c.status == "ok"), None)
            if hit is not None:
                return hit.text
    ranked = sorted(main, key=lambda c: -WORST.get(c.status, 0))
    if verdict == "choices":
        named = next((c for c in main if c.check == "normaliser" and c.status == "ok"), None)
        if named is not None:
            return named.text
        choice = next((c for c in checks if c.check == "choices"), None)
        if choice is not None:
            return choice.text
    return ranked[0].text if ranked else checks[0].text


def suggest_gene(book: Book, gene: str, choices: Sequence[ClaimChoice] = ()) -> ClaimText:
    """A sentence the planned analysis supports for this gene, every number a fact."""
    record = book.record
    contrast = record.result.contrasts[gene]
    f = _gene_facts(book, gene)
    p = _paper_p(book, gene)
    a, b = record.phrases
    numbers = f"fold change {f['fc']}, 95 % CI {f['lo']}–{f['hi']}, p {p}"
    if contrast.conclusion == "up":
        text = f"{gene} was higher in {a} than in {b} ({numbers})"
    elif contrast.conclusion == "down":
        text = f"{gene} was lower in {a} than in {b} ({numbers})"
    else:
        text = (
            f"{gene} did not differ clearly between {a} and {b} ({numbers}; a change is called "
            f"only if {record.rule_words()})"
        )
    robust = record.result.robustness.get(gene)
    if robust is not None and contrast.conclusion != "none":
        text += f"; the call holds in {f['holds']} of the {f['cells']} analyses qPilot checks"
    flips = [c for c in choices if c.call is not None and c.call != contrast.conclusion]
    if flips and contrast.conclusion != "none":
        first = flips[0]
        label = _tokens(first.label)
        text += f", and with {label} it is {_call_word(first.call or '')}"
    return book.say(text + ".", [gene])


# ---- study-level claims ----------------------------------------------------------------------


def check_normaliser(book: Book, claim: Claim, cid: str) -> Outcome:
    """A statement of which control genes the analysis was normalised to."""
    record = book.record
    lex = record.lexicon
    names = list(claim.normaliser)
    planned = list(record.result.design.refs_primary)
    listed = _join(planned)
    absent = [g for g in names if lex.status(g) == "absent"]
    targets = [g for g in names if lex.status(g) in ("compared", "measured", "marker")]
    suggestion = book.say(f"Expression was normalised to the geometric mean of {listed}.", planned)
    if absent:
        text = book.say(
            f"{_join(absent)} {'is' if len(absent) == 1 else 'are'} not measured in this study; "
            f"its analysis normalises to {listed}.",
            names + planned,
        )
        return Outcome(
            "contradicted", [_check("normaliser", "opposite", text)], text, suggestion=suggestion
        )
    if targets:
        text = book.say(
            f"{_join(targets)} {'is a gene' if len(targets) == 1 else 'are genes'} the study "
            f"compares, not a control gene; its analysis normalises to {listed}.",
            names + planned,
        )
        return Outcome(
            "contradicted", [_check("normaliser", "opposite", text)], text, suggestion=suggestion
        )
    if set(names) == set(planned):
        text = book.say(
            f"qPilot's planned analysis normalises to the same genes: {listed}.", planned
        )
        return Outcome("supported", [_check("normaliser", "ok", text)], text)
    idx = refs_cell(record, names)
    if idx is None or record.grid is None:
        text = book.say(
            f"qPilot's planned analysis normalises to {listed}; {_join(names)} is not a set its "
            "grid holds, so the analysis your text names cannot be reproduced.",
            names + planned,
        )
        return Outcome(
            "unchecked", [_check("normaliser", "unknown", text)], text, suggestion=suggestion
        )
    from qpilot.web.results_views import DIMENSION_TITLE, IDX

    grid = record.grid
    rows = grid.one_at_a_time("refs")
    at = rows[rows["refs" + IDX] == idx].set_index("item")
    base = rows[rows["refs" + IDX] == grid.planned["refs"]].set_index("item")
    changed = sorted(
        g for g in record.result.contrasts
        if g in at.index and g in base.index
        and str(at.loc[g, "conclusion"]) != str(base.loc[g, "conclusion"])
    )  # fmt: skip
    token, card = _choice_label(book, record, "refs", idx)
    k = book.add(
        f"f_claims_{cid}_changed", len(changed),
        path=f"grid.csv: genes whose call differs with refs = {grid.options['refs'][idx]}",
    )  # fmt: skip
    shown = ", ".join(changed[:6]) + (" and more" if len(changed) > 6 else "")
    text = (
        f"Your text normalises to {_join(names)}, one of the sets qPilot checks but not "
        f"the planned one ({listed})."
    )
    detail = f"With it, {k} gene calls differ from the planned analysis"
    detail += f": {shown}." if changed else "."
    choice = ClaimChoice(
        dimension="refs",
        title=DIMENSION_TITLE.get("refs", "refs"),
        option=grid.options["refs"][idx],
        label=book.say(token),
        card_id=card[0] if card else None,
        option_id=card[1] if card else None,
        holds=True,
    )
    head = book.say(text, names + planned)
    return Outcome(
        "choices",
        [_check("normaliser", "note", head), _check("choices", "note", book.say(detail, changed))],
        head,
        choices=[choice],
        suggestion=suggestion,
    )


def check_efficiency(book: Book, claim: Claim, cid: str) -> Outcome:
    """A range (or bound) every named assay's amplification efficiency is said to fall in."""
    record = book.record
    eff = record.result.efficiency
    genes = [g for g in (claim.genes or tuple(eff)) if g in eff]
    if not genes:
        text = book.say("The study has no efficiency for the assays this sentence names.")
        return Outcome("unchecked", [_check("efficiency", "unknown", text)], text)
    lo, hi = claim.efficiency or (0.0, math.inf)
    pct = {g: (eff[g] - 1) * 100 for g in genes}
    outside = sorted((g for g in genes if not lo <= pct[g] <= hi), key=lambda g: pct[g])
    mark = claim.marks[-1]
    written = book.quote(cid, "efficiency", mark.span.start, mark.span.end)
    n = book.add(f"f_claims_{cid}_n_assays", len(genes), path="efficiency (assays checked)")

    def pct_token(gene: str) -> str:
        return book.add(
            f"f_claims_effpct_{slug(gene)}", eff[gene] - 1, "{:.0%}", path=f"efficiency.{gene} − 1",
            origin="result",
        )  # fmt: skip

    lowest = min(genes, key=lambda g: pct[g])
    highest = max(genes, key=lambda g: pct[g])
    span = f"from {pct_token(lowest)} ({lowest}) to {pct_token(highest)} ({highest})"
    suggestion = book.say(f"Amplification efficiencies ranged {span}.", [lowest, highest])
    if not outside:
        text = book.say(
            f"All {n} assays are within {written}: efficiencies range {span}.", [lowest, highest]
        )
        return Outcome("supported", [_check("efficiency", "ok", text)], text)
    k = book.add(
        f"f_claims_{cid}_n_outside", len(outside), path="efficiency (assays outside the range)"
    )
    worst = [f"{g} {pct_token(g)}" for g in (outside[:2] if outside[0] == lowest else outside[-2:])]
    text = book.say(
        (
            f"{k} of {n} assays are outside {written}; for example {_join(worst)}. "
            f"Efficiencies range {span}."
        ),
        outside[:2] + outside[-2:] + [lowest, highest],
    )
    return Outcome(
        "contradicted", [_check("efficiency", "opposite", text)], text, suggestion=suggestion
    )


def check_n(book: Book, claim: Claim, cid: str) -> Outcome:
    """Group sizes (``n = 53 vs 294``) against the design (and, if not, any gene's)."""
    record = book.record
    design = record.result.design
    a, b = record.phrases
    values = list(claim.n_values)
    mark = claim.marks[0]
    written = book.quote(cid, "n", mark.span.start, mark.span.end)
    t_hi = book.t("f_n_hi") if book.has("f_n_hi") else book.add("f_n_hi", design.n_hi, path="study")
    t_lo = book.t("f_n_lo") if book.has("f_n_lo") else book.add("f_n_lo", design.n_lo, path="study")
    sizes = f"{t_hi} in {a} and {t_lo} in {b}"
    suggestion = book.say(f"n = {t_hi} ({a}) and {t_lo} ({b}).")
    if sorted(values) == sorted([design.n_hi, design.n_lo]) or (
        len(values) == 1 and values[0] in (design.n_hi + design.n_lo, record.result.n_samples)
    ):
        text = book.say(f"The design compares {sizes}, as {written} says.")
        return Outcome("supported", [_check("n", "ok", text)], text)
    genes = sorted(
        g for g, c in record.result.contrasts.items() if sorted(values) == sorted([c.n_hi, c.n_lo])
    )
    if genes:
        text = book.say(
            f"The design compares {sizes}; {written} are the group sizes for {_join(genes[:6])} "
            "(after empty wells are dropped).",
            genes[:6],
        )
        return Outcome("supported", [_check("n", "ok", text)], text)
    text = book.say(f"The design compares {sizes}, not {written}.")
    return Outcome("contradicted", [_check("n", "opposite", text)], text, suggestion=suggestion)


# ---- the text --------------------------------------------------------------------------------


def _reading(text: str, claim: Claim, lexicon: Lexicon) -> ClaimReading:
    def written(role: str) -> str | None:
        m = claim.mark(role)  # type: ignore[arg-type]
        return text[m.span.start : m.span.end] if m else None

    groups = [text[m.span.start : m.span.end] for m in claim.marks if m.role == "group"]
    words: list[str] = []
    if claim.kind == "gene":
        words.append(claim.gene or "")
        d = claim.direction
        if claim.inverted and d in ("up", "down"):
            d = "down" if d == "up" else "up"
        a, b = lexicon.group_a, lexicon.group_b
        if b == "rest":
            a, b = f"the {a} group", "the rest"
        other = claim.other_groups[0][0] if claim.other_groups and not claim.names_groups else ""
        if other:
            said = {"up": "higher", "down": "lower", "none": "no difference"}.get(d or "", "")
            words.append(f"{said or 'a change'} in {other} (not this study's groups)")
        elif d in ("up", "down"):
            words.append(f"{'higher' if d == 'up' else 'lower'} in {a} than in {b}")
        elif d == "none":
            words.append(f"no difference between {a} and {b}")
        if claim.hedged:
            words.append("hedged (no significance claimed)")
        for role in ("fold", "p", "significance", "robust"):
            w = written(role)
            if w:
                words.append(w)
        if claim.normaliser:
            scope = {
                "text": " (stated once for all the data)",
                "previous": " (from the sentence after it)",
                "gene": " (from another sentence about this gene)",
            }.get(claim.normaliser_scope or "", "")
            words.append("normalised to " + _join(list(claim.normaliser)) + scope)
    elif claim.kind == "normaliser":
        words.append("normalised to " + _join(list(claim.normaliser)))
    elif claim.kind == "efficiency":
        eff_marks = [m for m in claim.marks if m.role == "efficiency"]
        words.append(
            "efficiency "
            + (text[eff_marks[-1].span.start : eff_marks[-1].span.end] if eff_marks else "")
        )
        words.append(_join(list(claim.genes)) if claim.genes else "every assay")
    elif claim.kind == "n":
        words.append(written("n") or "")
    eff = [m for m in claim.marks if m.role == "efficiency"]
    return ClaimReading(
        gene=claim.gene,
        gene_written=written("gene") if claim.kind == "gene" else None,
        gene_via=claim.gene_via,  # type: ignore[arg-type]
        gene_status=claim.gene_status,  # type: ignore[arg-type]
        direction=claim.direction,
        direction_written=written("direction"),
        negated=claim.negated,
        hedged=claim.hedged,
        inverted=claim.inverted,
        fold_written=claim.fold.mark.written if claim.fold else None,
        fold_comparator=claim.fold.comparator if claim.fold else None,
        fold_kind=claim.fold.kind if claim.fold else None,
        p_written=claim.p.mark.written if claim.p else None,
        p_adjusted=bool(claim.p and claim.p.adjusted),
        significance=claim.significance,
        significance_written=written("significance"),
        robust_written=written("robust"),
        normaliser=list(claim.normaliser),
        groups_written=groups,
        other_groups=[w for w, _ in claim.other_groups],
        normaliser_scope=claim.normaliser_scope,
        n_written=written("n"),
        efficiency_written=text[eff[-1].span.start : eff[-1].span.end] if eff else None,
        efficiency_genes=list(claim.genes),
        source=claim.source,
        words=[w for w in words if w],
    )


CHECKERS = {
    "gene": check_gene,
    "normaliser": check_normaliser,
    "efficiency": check_efficiency,
    "n": check_n,
}


def audit_text(
    text: str,
    record: StudyRecord,
    claims: Sequence[Claim] | None = None,
    *,
    reader: str = "rules",
    model_note: str | None = None,
) -> ClaimsReport:
    """Find (or take) the claims in ``text`` and check each against ``record``."""
    from qpilot.qpcr.contrast import ConclusionRule

    claims = list(claims) if claims is not None else extract(text, record.lexicon)
    book = Book(record, text)
    views: list[ClaimView] = []
    for i, claim in enumerate(claims, start=1):
        cid = f"c{i}"
        outcome = CHECKERS[claim.kind](book, claim, cid)
        spans = sorted(
            {(m.span.start, m.span.end, m.role) for m in claim.marks}, key=lambda s: (s[0], s[1])
        )
        views.append(
            ClaimView(
                id=cid,
                kind=claim.kind,
                sentence=TextRange(start=claim.sentence.start, end=claim.sentence.end),
                clause=TextRange(start=claim.clause.start, end=claim.clause.end),
                spans=[
                    ClaimSpan(start=s, end=e, role=r, written=text[s:e])  # type: ignore[arg-type]
                    for s, e, r in spans
                ],
                reading=_reading(text, claim, record.lexicon),
                verdict=outcome.verdict,
                verdict_label=VERDICT_LABEL[outcome.verdict],
                headline=outcome.headline,
                checks=outcome.checks,
                choices=outcome.choices,
                grid_holds=outcome.grid_holds,
                grid_cells=outcome.grid_cells,
                audit_verdict=outcome.audit_verdict,
                audit_label=outcome.audit_label,
                suggestion=outcome.suggestion,
                gene=outcome.gene,
                severity=SEVERITY[outcome.verdict],
            )
        )
    counts = {v: sum(1 for c in views if c.verdict == v) for v in VERDICT_LABEL}
    supported = counts["supported"]
    n = len(views)
    if n == 0:
        sentence = (
            "No checkable claim was found: name a gene of this study with a direction, a "
            "fold or a p-value."
        )
    else:
        sentence = f"{supported} of {n} claim{'s' * (n != 1)} supported by this study's record."
    notes = []
    if record.grid is None:
        notes.append(
            "This study has no choice grid, so no claim can be checked under other choices."
        )
    if record.audit_state == "older":
        notes.append(
            "The robustness audit was run before the latest decisions; its verdicts "
            "may be out of date."
        )
    return ClaimsReport(
        study_id=record.study_id,
        length=len(text),
        text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        claims=views,
        summary=ClaimsSummary(n=n, supported=supported, counts=counts, sentence=sentence),
        reader="rules+model" if reader == "rules+model" else "rules",
        model_note=model_note,
        head=record.head,
        audit=record.audit_state,  # type: ignore[arg-type]
        groups=list(record.groups),
        rule=ConclusionRule(**record.result.conclusion_rule).describe(),
        verdicts=dict(VERDICT_LABEL),
        verdict_rules=dict(VERDICT_RULE),
        notes=notes,
    )
