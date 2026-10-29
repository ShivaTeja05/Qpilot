"""A figure per gene for a paper or a lab meeting: every biological unit, by group, from the engine.

:func:`gene_figure` takes one gene of one comparison from :func:`qpilot.report.tables.study_tables`
and lays it out once, as a list of drawing primitives; :func:`figure_svg` writes them as one
self-contained SVG (text stays text, so it is editable in Illustrator, Inkscape or PowerPoint)
and :func:`figure_png` draws the same primitives with matplotlib at 300 dpi, so the two files
show the same figure. :func:`panel_svg` / :func:`panel_png` put several genes side by side.

What a figure shows, and only that:

* **dots**: the log2 relative quantity of each **biological unit** (the value the test uses),
  never a technical replicate (they are averaged within the unit by the engine first);
* a **bar** at each group's mean with its **95 % confidence interval** (Student's t on the
  units' values, as GraphPad Prism draws it);
* above the groups, the engine's **call** as a shape and a word (▲ up, ▼ down, ○ no call; never
  colour alone), with the fold change and p of the engine's Welch test;
* a study with **several comparisons** (three or more groups): every group the study compares
  is drawn, in one fixed order whichever comparison is chosen, with one bracket per comparison
  (its call, fold change and, when the engine corrects for the several comparisons, the
  corrected p, written p-adj), the narrowest lowest; the chosen comparison's bracket is in
  ink, the others in grey;
* the **caption** (:attr:`GeneFigure.caption`) is built from the engine's facts: n per group,
  the test, no correction across genes (or the engine's correction), the efficiency model, the
  reference genes, the call rule, and which analysis it is (as decided, or recommended). It is
  in the SVG's ``<desc>`` and written beside the figure; it is not drawn into the image.

Colours are the Okabe–Ito palette (safe for colour-blind readers), each group also named under
its column with its n. Sizes are for a journal's single column (85 mm wide); the fonts are
Arial or Helvetica (DejaVu Sans where neither is installed). Deterministic: the same study gives
the same bytes (no dates, no random jitter: the dots are a swarm laid out from the values).
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from html import escape
from typing import Any

from qpilot.report import fmt
from qpilot.report.tables import AS_DECIDED, CALL_WORDS, StudyTables

#: Okabe & Ito (2008), "Color Universal Design": group fills, in a fixed order.
PALETTE = ("#0072B2", "#E69F00", "#009E73", "#CC79A7", "#D55E00", "#56B4E9")
#: The same hues, darker: each dot's outline (contrast against white and between dots).
OUTLINE = ("#004F7C", "#8F6200", "#006A4D", "#8C4C72", "#8F3F00", "#2B7DAD")
INK = "#1A1A1A"
MUTED = "#555555"
GRID = "#E2E2E2"
FONT = "Arial, Helvetica, sans-serif"
FONT_PREFERENCE = ("Arial", "Helvetica", "DejaVu Sans")

W, H = 260.0, 300.0  # one gene, in drawing units
MM_PER_UNIT = 85.0 / W  # a single journal column is 85 mm wide
PT_PER_UNIT = MM_PER_UNIT * 72 / 25.4
ML, MR, MT, MB = 50.0, 12.0, 62.0, 44.0
DPI = 300
MAX_PANEL_COLUMNS = 4


#: A run of text: ``(text, "")``, ``(text, "sup")`` (superscript) or ``(text, "sub")``.
Segment = tuple[str, str]


class FigureError(ValueError):
    """The figure cannot be drawn (the message says why, in words)."""


# ---------------------------------------------------------------------------------------------
# The figure as data
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupDots:
    """One group's units: ``(unit, log2 RQ)`` each, and the mean with its 95 % CI."""

    name: str
    points: tuple[tuple[str, float], ...]
    mean: float | None
    ci_lo: float | None
    ci_hi: float | None
    color: int = 0

    @property
    def n(self) -> int:
        """Biological units with a value."""
        return len(self.points)


@dataclass(frozen=True)
class Bracket:
    """One comparison's call over its two groups (``a`` and ``b`` index ``GeneFigure.groups``)."""

    a: int
    b: int
    name: str
    call: str | None
    fc: float | None
    p: float | None
    adjusted: bool  # ``p`` is the corrected p the call used
    chosen: bool


@dataclass(frozen=True)
class GeneFigure:
    """One gene of one comparison, ready to draw: the dots, the engine's result, the caption.

    ``brackets`` (a study with several comparisons only) holds one bracket per comparison over
    every group of the study; empty otherwise (one bracket over the two groups, as before).
    """

    gene: str
    comparison: str
    groups: tuple[GroupDots, ...]
    call: str | None
    fc: float | None
    ci_lo: float | None
    ci_hi: float | None
    p: float | None
    n_a: int | None
    n_b: int | None
    basis: str
    basis_label: str
    caption: str
    note: str = ""
    brackets: tuple[Bracket, ...] = ()
    p_adjusted: float | None = None

    @property
    def title(self) -> str:
        """``ODC1, MYCN-high vs rest``."""
        return f"{self.gene}, {self.comparison}"


def mean_ci(values: Sequence[float]) -> tuple[float | None, float | None, float | None]:
    """Mean and its 95 % confidence interval (Student's t); no interval below two values."""
    n = len(values)
    if n == 0:
        return None, None, None
    mean = math.fsum(values) / n
    if n < 2:
        return mean, None, None
    from scipy import stats

    sd = math.sqrt(math.fsum((v - mean) ** 2 for v in values) / (n - 1))
    half = float(stats.t.ppf(0.975, n - 1)) * sd / math.sqrt(n)
    return mean, mean - half, mean + half


def gene_figure(
    tables: StudyTables, gene: str, basis: str = AS_DECIDED, comparison: str | None = None
) -> GeneFigure:
    """One gene's figure from the study's tables (the analysis as decided by default).

    Raises:
        FigureError: The gene is not in the comparison, or no unit has a value for it.
        ValueError: Unknown basis.
    """
    analysis = tables.analysis(basis)
    try:
        comp = analysis.comparison(comparison)
    except KeyError as err:
        raise FigureError(f"there is no comparison {comparison!r} in this study") from err
    if gene not in comp.genes:
        raise FigureError(f"{gene!r} is not a gene compared in {comp.name}")
    if not analysis.rebuilt:
        raise FigureError(
            "the figure needs each unit's value, and the study's input file is not known here "
            "(open the study from its file again)"
        )
    if len(analysis.comparisons) > 1:
        return _with_caption(_every_group(analysis, gene, comp), tables, basis)
    values = analysis.unit_values(gene, comp.name)
    order = [
        comp.group_a,
        comp.group_b,
        *(g for g in values if g not in (comp.group_a, comp.group_b)),
    ]
    groups = []
    for i, name in enumerate(order):
        pts = tuple(values.get(name, ()))
        mean, lo, hi = mean_ci([v for _, v in pts])
        groups.append(GroupDots(name, pts, mean, lo, hi, color=i % len(PALETTE)))
    if not any(g.points for g in groups):
        raise FigureError(f"no biological unit has a value for {gene!r}")
    con = comp.contrasts.get(gene)
    note = "" if con is not None else comp.withheld.get(gene, "too few values in a group")
    fig = GeneFigure(
        gene=gene,
        comparison=comp.name,
        groups=tuple(groups),
        call=con.conclusion if con is not None else None,
        fc=_finite(con.fc) if con else None,
        ci_lo=_finite(con.ci[0]) if con else None,
        ci_hi=_finite(con.ci[1]) if con else None,
        p=_finite(con.p) if con else None,
        n_a=con.n_hi if con else None,
        n_b=con.n_lo if con else None,
        basis=analysis.basis,
        basis_label=analysis.label,
        caption="",
        note=note,
    )
    return _with_caption(fig, tables, basis)


def group_order(comps: Sequence[Any]) -> list[str]:
    """Every group of several comparisons, in one order: each comparison's reference first.

    Each group against a control gives the control, then the others; every pair gives the
    first group, then the rest, as the comparisons name them.
    """
    return list(dict.fromkeys(g for c in comps for g in (c.group_b, c.group_a)))


def _every_group(analysis: Any, gene: str, comp: Any) -> GeneFigure:
    """One gene over every group of the study, a bracket per comparison (``comp`` chosen)."""
    comps = list(analysis.comparisons)
    order = group_order(comps)
    values: dict[str, dict[str, float]] = {g: {} for g in order}
    for c in comps:
        if gene not in c.genes:
            continue
        for group, pts in analysis.unit_values(gene, c.name).items():
            values.setdefault(group, {}).update({str(u): v for u, v in pts})
    groups = []
    for i, name in enumerate(order):
        pts = tuple(sorted(values.get(name, {}).items(), key=lambda pair: pair[0]))
        mean, lo, hi = mean_ci([v for _, v in pts])
        groups.append(GroupDots(name, pts, mean, lo, hi, color=i % len(PALETTE)))
    if not any(g.points for g in groups):
        raise FigureError(f"no biological unit has a value for {gene!r}")
    brackets = []
    for c in sorted(comps, key=lambda c: c.name != comp.name):  # the chosen one first (lowest)
        con = c.contrasts.get(gene)
        adjusted = bool(c.correction) and bool(c.p_adjusted) and gene in (c.p_adjusted or {})
        p = (c.p_adjusted or {}).get(gene) if adjusted else (con.p if con else None)
        brackets.append(
            Bracket(
                a=order.index(c.group_a),
                b=order.index(c.group_b),
                name=c.name,
                call=con.conclusion if con is not None else None,
                fc=_finite(con.fc) if con else None,
                p=_finite(p),
                adjusted=adjusted,
                chosen=c.name == comp.name,
            )
        )
    con = comp.contrasts.get(gene)
    note = "" if con is not None else comp.withheld.get(gene, "too few values in a group")
    chosen = brackets[0]
    return GeneFigure(
        gene=gene,
        comparison=comp.name,
        groups=tuple(groups),
        call=con.conclusion if con is not None else None,
        fc=_finite(con.fc) if con else None,
        ci_lo=_finite(con.ci[0]) if con else None,
        ci_hi=_finite(con.ci[1]) if con else None,
        p=_finite(con.p) if con else None,
        n_a=con.n_hi if con else None,
        n_b=con.n_lo if con else None,
        basis=analysis.basis,
        basis_label=analysis.label,
        caption="",
        note=note,
        brackets=tuple(brackets),
        p_adjusted=chosen.p if chosen.adjusted else None,
    )


def _finite(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


# ---- the caption: the engine's facts in words -----------------------------------------------


def p_words(p: float | None, adjusted: bool = False) -> list[Segment]:
    """``p = 0.003``, or ``p = 2.3 × 10⁻⁸`` as text segments (``p_adj`` for a corrected p)."""
    if p is None:
        return [("p not computed", "")]
    name: list[Segment] = [("p", ""), ("adj", "sub")] if adjusted else [("p", "")]
    if p >= 0.001:
        return [*name, (f" = {fmt.p_value(p)}", "")]
    exponent = math.floor(math.log10(p))
    mantissa = p / 10**exponent
    if round(mantissa, 1) >= 10:
        mantissa, exponent = mantissa / 10, exponent + 1
    return [*name, (f" = {mantissa:.1f} × 10", ""), (f"{fmt.MINUS}{-exponent}", "sup")]


def _plain(segments: Sequence[Segment]) -> str:
    sup = str.maketrans("0123456789" + fmt.MINUS, "⁰¹²³⁴⁵⁶⁷⁸⁹⁻")
    sub = str.maketrans("0123456789" + fmt.MINUS, "₀₁₂₃₄₅₆₇₈₉₋")
    table = {"sup": sup, "sub": sub}
    return "".join(t.translate(table[s]) if s in table else t for t, s in segments)


def _call_sentence(fig: GeneFigure) -> str:
    if fig.call is None:
        return f"not compared ({fig.note})" if fig.note else "not compared"
    return {"up": "called up", "down": "called down", "none": "no call"}.get(fig.call, fig.call)


def _every_caption(fig: GeneFigure, tables: StudyTables, basis: str) -> str:
    """The caption of a figure over every group: each group's n, each comparison's result."""
    analysis = tables.analysis(basis)
    comps = {c.name: c for c in analysis.comparisons}
    named = ", ".join(f"{g.name} (n = {g.n})" for g in fig.groups)
    parts = [
        f"{fig.gene} in {named}. Each dot is one biological unit's log2 relative quantity; "
        "technical replicates are averaged within each unit and never counted as n. Bars: group "
        "mean with its 95 % confidence interval (Student's t).",
        f" Quantities are normalised to the mean log2 quantity of the reference genes "
        f"{', '.join(analysis.refs)}; efficiency: {analysis.efficiency}; a curve counts as "
        f"amplified by {_lower(analysis.amp_call)}; wells with no quantity: "
        f"{_lower(analysis.undetermined)}.",
    ]
    first = comps[fig.comparison]
    test = first.test or "Welch's t test"
    parts.append(f" {test[:1].upper()}{test[1:]} on the per-unit log2 values in each comparison:")
    for k, b in enumerate(fig.brackets):
        c = comps[b.name]
        con = c.contrasts.get(fig.gene)
        sep = ";" if k < len(fig.brackets) - 1 else "."
        if con is None:
            parts.append(f" {b.name}, not compared{sep}")
            continue
        name = "corrected p" if b.adjusted else "p"
        p = _plain(p_words(b.p)).removeprefix("p ")
        parts.append(
            f" {b.name}, fold change {fmt.fold(b.fc)} (95 % CI {fmt.fold(_finite(con.ci[0]))} to "
            f"{fmt.fold(_finite(con.ci[1]))}), {name} {p}, {_call_sentence_of(b.call)}{sep}"
        )
    alpha, fold = _rule(tables)
    rule = "corrected p" if any(b.adjusted for b in fig.brackets) else "p"
    parts.append(f" A call needs {rule} < {alpha:g} and at least {fold:g}-fold.")
    if first.correction:
        parts.append(f" {first.correction}.")
    parts.append(
        f" The bracket in black is {fig.comparison}. Analysis: "
        f"{analysis.words.split(':')[0].lower()} ({_basis_tail(analysis)})."
    )
    return "".join(parts)


def _call_sentence_of(call: str | None) -> str:
    return {"up": "called up", "down": "called down", "none": "no call"}.get(call or "", "no call")


def _with_caption(fig: GeneFigure, tables: StudyTables, basis: str) -> GeneFigure:
    from dataclasses import replace

    if fig.brackets:
        return replace(fig, caption=_every_caption(fig, tables, basis))
    analysis = tables.analysis(basis)
    a, b = fig.groups[0], fig.groups[1]
    n_a = fig.n_a if fig.n_a else a.n
    n_b = fig.n_b if fig.n_b else b.n
    comp = analysis.comparison(fig.comparison)
    n_genes = len(comp.contrasts)
    parts = [
        f"{fig.gene}, {a.name} versus {b.name}. Each dot is one biological unit's log2 relative "
        f"quantity ({a.name} n = {n_a}, {b.name} n = {n_b}); technical replicates are averaged "
        "within each unit and never counted as n. Bars: group mean with its 95 % confidence "
        "interval (Student's t).",
        f" Quantities are normalised to the mean log2 quantity of the reference genes "
        f"{', '.join(analysis.refs)}; efficiency: {analysis.efficiency}; a curve counts as "
        f"amplified by {_lower(analysis.amp_call)}; wells with no quantity: "
        f"{_lower(analysis.undetermined)}.",
    ]
    if fig.call is not None:
        test = comp.test or "Welch's t test"
        parts.append(
            f" {test[:1].upper()}{test[1:]} on the per-unit log2 values: fold change "
            f"{fmt.fold(fig.fc)} "
            f"(95 % CI {fmt.fold(fig.ci_lo)} to {fmt.fold(fig.ci_hi)}), {_plain(p_words(fig.p))}; "
            f"{_call_sentence(fig)} under the rule "
            f"p < {_rule(tables)[0]:g} and at least {_rule(tables)[1]:g}-fold."
        )
    else:
        parts.append(f" The engine did not compare this gene: {fig.note}.")
    correction = comp.correction
    if correction:
        parts.append(f" {correction}.")
    elif n_genes == 1:
        parts.append(" One gene was compared, so no correction for multiple testing applies.")
    else:
        parts.append(f" No correction for multiple testing across the {n_genes} genes compared.")
    parts.append(f" Analysis: {analysis.words.split(':')[0].lower()} ({_basis_tail(analysis)}).")
    return replace(fig, caption="".join(parts))


def _lower(text: str) -> str:
    """``Drop empty wells`` -> ``drop empty wells``; names (``LinRegPCR``, ``Cq``) stay."""
    word = text.split(" ", 1)[0]
    if len(word) >= 3 and word[1:].islower() and not word.startswith("Cq"):
        return text[:1].lower() + text[1:]
    return text


def _rule(tables: StudyTables) -> tuple[float, float]:
    for row in tables.settings.rows:
        if row[0] == "Conclusion rule":
            words = str(row[1]).split()
            try:
                alpha = float(words[words.index("<") + 1])
                fold = float(words[words.index("least") + 1].split("-")[0])
                return alpha, fold
            except (ValueError, IndexError):
                break
    return 0.05, 2.0


def _basis_tail(analysis) -> str:
    changed = [c for c in analysis.choices if not c.is_recommended]
    if analysis.basis != AS_DECIDED:
        return "every Decision Card at its recommended option"
    if not changed:
        return "every choice in use is the recommended one"
    return "; ".join(f"{c.title.lower()}: {c.option_label}" for c in changed)


# ---------------------------------------------------------------------------------------------
# Layout: one list of primitives, drawn as SVG and with matplotlib
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Line:
    """A straight line."""

    x1: float
    y1: float
    x2: float
    y2: float
    stroke: str = INK
    width: float = 1.0
    cls: str = ""


@dataclass(frozen=True)
class Dot:
    """A filled circle (one biological unit)."""

    cx: float
    cy: float
    r: float
    fill: str
    stroke: str
    opacity: float = 0.85
    title: str = ""


@dataclass(frozen=True)
class Shape:
    """A filled polygon (the call's triangle) or an open circle (no call)."""

    points: tuple[tuple[float, float], ...] = ()
    circle: tuple[float, float, float] | None = None
    fill: str = INK
    stroke: str = INK


@dataclass(frozen=True)
class Text:
    """A text line made of :data:`Segment` runs; anchored like SVG ``text-anchor``."""

    x: float
    y: float
    segments: tuple[Segment, ...]
    size: float = 9.0
    anchor: str = "start"
    color: str = INK
    bold: bool = False
    rotate: bool = False
    cls: str = ""


@dataclass
class Drawing:
    """Primitives in drawing units, and the canvas size."""

    width: float
    height: float
    items: list = field(default_factory=list)


def _nice_step(span: float, target: int = 5) -> float:
    raw = span / max(target, 1)
    magnitude = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1.0
    for m in (1, 2, 2.5, 5, 10):
        if m * magnitude >= raw:
            return m * magnitude
    return 10 * magnitude


def _range(fig: GeneFigure) -> tuple[float, float]:
    values = [v for g in fig.groups for _, v in g.points]
    values += [x for g in fig.groups for x in (g.ci_lo, g.ci_hi) if x is not None]
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    pad = (hi - lo) * 0.06
    return lo - pad, hi + pad


def swarm(ys: Sequence[float], r: float, half: float) -> list[float]:
    """Horizontal offsets that keep dots of radius ``r`` apart, nearest the centre first.

    ``ys`` are the dots' vertical positions in drawing units, in a fixed order (by value, then
    unit). When the swarm would be wider than ``2 * half`` it is squeezed to fit (dots may then
    touch). Deterministic: no randomness.
    """
    d = 2 * r * 1.02
    placed: list[tuple[float, float]] = []
    out: list[float] = []
    for y in ys:
        near = [(px, py) for px, py in placed if abs(py - y) < d]
        candidates = [0.0]
        for px, py in near:
            w = math.sqrt(max(d * d - (py - y) ** 2, 0.0))
            candidates += [px - w, px + w]
        best = None
        for c in sorted(candidates, key=lambda c: (abs(c), c)):
            if all((c - px) ** 2 + (y - py) ** 2 >= d * d - 1e-9 for px, py in near):
                best = c
                break
        x = 0.0 if best is None else best
        placed.append((x, y))
        out.append(x)
    widest = max((abs(x) for x in out), default=0.0)
    if widest > half > 0:
        out = [x * half / widest for x in out]
    return out


def _call_glyph(call: str | None, x: float, y: float, r: float = 4.2) -> Shape:
    if call == "up":
        return Shape(points=((x, y - r), (x - r, y + r * 0.75), (x + r, y + r * 0.75)))
    if call == "down":
        return Shape(points=((x, y + r), (x - r, y - r * 0.75), (x + r, y - r * 0.75)))
    return Shape(circle=(x, y, r * 0.8), fill="none")


BRACKET_STEP = 15.0  # drawing units between stacked comparison brackets


def layout(fig: GeneFigure, x0: float = 0.0, y0: float = 0.0) -> list:
    """The figure's primitives in a ``W`` × ``H`` box whose top-left corner is ``(x0, y0)``."""
    items: list = []
    left, right = x0 + ML, x0 + W - MR
    extra = BRACKET_STEP * max(len(fig.brackets) - 1, 0)
    top, bottom = y0 + MT + extra, y0 + H - MB
    lo, hi = _range(fig)

    def y(v: float) -> float:
        return bottom - (v - lo) / (hi - lo) * (bottom - top)

    step = _nice_step(hi - lo)
    tick = math.ceil(lo / step) * step
    while tick <= hi + 1e-9:
        yy = y(tick)
        items.append(Line(left, yy, right, yy, GRID, 0.6, "grid"))
        label = f"{tick:g}".replace("-", fmt.MINUS)
        items.append(Text(left - 5, yy + 3, ((label, ""),), 8, "end", MUTED, cls="tick"))
        tick += step
    items.append(Line(left, top, left, bottom, INK, 0.8, "axis"))
    items.append(
        Text(
            x0 + 13,
            (top + bottom) / 2,
            (("log", ""), ("2", "sub"), (" relative quantity", "")),
            8.5,
            "middle",
            INK,
            rotate=True,
            cls="axis-label",
        )
    )
    n = len(fig.groups)
    band = (right - left) / n
    centres = [left + band * (i + 0.5) for i in range(n)]
    many = max((g.n for g in fig.groups), default=0)
    r = 2.6 if many <= 40 else 2.0 if many <= 120 else 1.5
    for g, cx in zip(fig.groups, centres, strict=True):
        # The bar first, the dots over it: every unit stays visible, even on the CI line.
        if g.mean is not None:
            half = band * 0.26
            items.append(Line(cx - half, y(g.mean), cx + half, y(g.mean), INK, 1.8, "mean"))
        if g.ci_lo is not None and g.ci_hi is not None:
            cap = band * 0.09
            items.append(Line(cx, y(g.ci_lo), cx, y(g.ci_hi), INK, 1.1, "ci"))
            for v in (g.ci_lo, g.ci_hi):
                items.append(Line(cx - cap, y(v), cx + cap, y(v), INK, 1.1, "ci"))
        pts = sorted(g.points, key=lambda p: (p[1], str(p[0])))
        offsets = swarm([y(v) for _, v in pts], r, band * 0.36)
        for (unit, v), dx in zip(pts, offsets, strict=True):
            items.append(
                Dot(
                    cx + dx,
                    y(v),
                    r,
                    PALETTE[g.color],
                    OUTLINE[g.color],
                    0.8 if many <= 120 else 0.65,
                    f"{unit}: log2 RQ {v:.3f}",
                )
            )
        items.append(Text(cx, bottom + 15, ((g.name, ""),), 8.5, "middle", INK, cls="group"))
        items.append(Text(cx, bottom + 27, ((f"n = {g.n}", ""),), 7.5, "middle", MUTED))
    items.append(Text(x0 + 6, y0 + 15, ((fig.gene, ""),), 10.5, "start", INK, True, cls="gene"))
    if fig.brackets:  # several comparisons: a bracket each, the narrowest lowest; chosen in ink
        stacked = sorted(fig.brackets, key=lambda b: (abs(b.a - b.b), not b.chosen, b.a, b.b))
        for k, b in enumerate(stacked):
            items += _bracket(b, centres, top - 12 - BRACKET_STEP * k)
        return items
    # The engine's call over the first two groups.
    if n >= 2:
        a, b = centres[0], centres[1]
        by = top - 12
        items.append(Line(a, by, b, by, INK, 0.8, "bracket"))
        for x in (a, b):
            items.append(Line(x, by, x, by + 4, INK, 0.8, "bracket"))
        mid = (a + b) / 2
        if fig.call is None:
            words: tuple[Segment, ...] = (("not compared", ""),)
        else:
            words = (
                (f"{CALL_WORDS.get(fig.call, fig.call)} · {fmt.fold(fig.fc)} · ", ""),
                *p_words(fig.p),
            )
        start = mid - (_text_width(words, 8) + 12) / 2
        items.append(_call_glyph(fig.call, start + 4.5, by - 7.5))
        items.append(Text(start + 12, by - 4.5, words, 8, "start", INK, cls="call"))
    return items


def _bracket(b: Bracket, centres: Sequence[float], by: float) -> list:
    """One comparison's bracket between its groups' columns, with its call, fold and p."""
    ink = INK if b.chosen else MUTED
    a, c = centres[b.a], centres[b.b]
    lo, hi = min(a, c), max(a, c)
    out: list = [Line(lo, by, hi, by, ink, 0.9 if b.chosen else 0.6, "bracket")]
    for x in (lo, hi):
        out.append(Line(x, by, x, by + 3.5, ink, 0.9 if b.chosen else 0.6, "bracket"))
    if b.call is None:
        words: tuple[Segment, ...] = (("not compared", ""),)
    else:
        words = (
            (f"{CALL_WORDS.get(b.call, b.call)} · {fmt.fold(b.fc)} · ", ""),
            *p_words(b.p, b.adjusted),
        )
    size = 7.0
    width = _text_width(words, size) + 10
    start = max((lo + hi) / 2 - width / 2, centres[0] - 20)
    glyph = _call_glyph(b.call, start + 3.8, by - 6.0, 3.4)
    out.append(Shape(glyph.points, glyph.circle, ink if glyph.fill != "none" else "none", ink))
    out.append(Text(start + 10, by - 3.2, words, size, "start", ink, b.chosen, cls="call"))
    return out


def _text_width(segments: Sequence[Segment], size: float) -> float:
    """A text's width in drawing units, estimated (Arial: about half its size per character)."""
    return sum(len(t) * size * (0.38 if s else 0.5) for t, s in segments)


def drawing(fig: GeneFigure) -> Drawing:
    """One gene's figure."""
    return Drawing(W, H, layout(fig))


def panel_drawing(figs: Sequence[GeneFigure], columns: int | None = None) -> Drawing:
    """Several genes side by side (at most four per row)."""
    if not figs:
        raise FigureError("a panel needs at least one gene")
    cols = max(1, min(columns or len(figs), MAX_PANEL_COLUMNS, len(figs)))
    rows = math.ceil(len(figs) / cols)
    out = Drawing(W * cols, H * rows)
    for i, fig in enumerate(figs):
        out.items += layout(fig, W * (i % cols), H * (i // cols))
    return out


# ---------------------------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------------------------


def _e(text: object) -> str:
    return escape(str(text), quote=True)


def _f(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".") if x == x else "0"


def _svg_text(t: Text) -> str:
    weight = ' font-weight="bold"' if t.bold else ""
    rot = f' transform="rotate(-90 {_f(t.x)} {_f(t.y)})"' if t.rotate else ""
    cls = f' class="{t.cls}"' if t.cls else ""
    spans = []
    for text, kind in t.segments:
        if kind in ("sup", "sub"):
            shift = "super" if kind == "sup" else "sub"
            size = _f(t.size * 0.72)
            spans.append(f'<tspan baseline-shift="{shift}" font-size="{size}">{_e(text)}</tspan>')
        else:
            spans.append(_e(text))
    return (
        f'<text{cls} x="{_f(t.x)}" y="{_f(t.y)}" font-size="{_f(t.size)}" '
        f'text-anchor="{t.anchor}" fill="{t.color}"{weight}{rot}>{"".join(spans)}</text>'
    )


def _svg_items(items: Sequence[Any]) -> list[str]:
    out = []
    for it in items:
        if isinstance(it, Line):
            cls = f' class="{it.cls}"' if it.cls else ""
            out.append(
                f'<line{cls} x1="{_f(it.x1)}" y1="{_f(it.y1)}" x2="{_f(it.x2)}" y2="{_f(it.y2)}" '
                f'stroke="{it.stroke}" stroke-width="{_f(it.width)}"/>'
            )
        elif isinstance(it, Dot):
            out.append(
                f'<circle class="unit" cx="{_f(it.cx)}" cy="{_f(it.cy)}" r="{_f(it.r)}" '
                f'fill="{it.fill}" fill-opacity="{_f(it.opacity)}" stroke="{it.stroke}" '
                f'stroke-width="0.5"><title>{_e(it.title)}</title></circle>'
            )
        elif isinstance(it, Shape):
            if it.circle is not None:
                cx, cy, r = it.circle
                out.append(
                    f'<circle class="call-glyph" cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(r)}" '
                    f'fill="none" stroke="{it.stroke}" stroke-width="1.1"/>'
                )
            else:
                pts = " ".join(f"{_f(x)},{_f(y)}" for x, y in it.points)
                out.append(f'<polygon class="call-glyph" points="{pts}" fill="{it.fill}"/>')
        elif isinstance(it, Text):
            out.append(_svg_text(it))
    return out


def svg_document(d: Drawing, title: str, desc: str) -> str:
    """A standalone SVG: physical size in mm, editable text, no scripts, no external links."""
    width_mm, height_mm = d.width * MM_PER_UNIT, d.height * MM_PER_UNIT
    head = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_f(width_mm)}mm" '
        f'height="{_f(height_mm)}mm" viewBox="0 0 {_f(d.width)} {_f(d.height)}" role="img" '
        f'aria-labelledby="fig-title fig-desc" font-family="{FONT}">'
        f'<title id="fig-title">{_e(title)}</title><desc id="fig-desc">{_e(desc)}</desc>'
        f'<rect width="{_f(d.width)}" height="{_f(d.height)}" fill="#FFFFFF"/>'
    )
    return head + "".join(_svg_items(d.items)) + "</svg>\n"


def figure_svg(fig: GeneFigure) -> str:
    """One gene's figure as a standalone SVG (its caption in ``<desc>``)."""
    return svg_document(drawing(fig), fig.title, fig.caption)


def panel_svg(figs: Sequence[GeneFigure], columns: int | None = None) -> str:
    """Several genes in one SVG; every gene's caption in ``<desc>``."""
    d = panel_drawing(figs, columns)
    title = "; ".join(f.gene for f in figs) + f" ({figs[0].comparison})"
    return svg_document(d, title, " ".join(f"({i}) {f.caption}" for i, f in
                                           enumerate(figs, start=1)))  # fmt: skip


# ---------------------------------------------------------------------------------------------
# PNG (matplotlib, the same primitives)
# ---------------------------------------------------------------------------------------------


def _font() -> str:
    from matplotlib import font_manager

    for name in FONT_PREFERENCE:
        try:
            font_manager.findfont(name, fallback_to_default=False)
            return name
        except ValueError:
            continue
    return "DejaVu Sans"


def png_bytes(d: Drawing, dpi: int = DPI) -> bytes:
    """The drawing as a PNG at ``dpi`` (300 by default), white background, no metadata."""
    import matplotlib
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.patches import Circle, Polygon

    inch = MM_PER_UNIT / 25.4
    rc = {"font.family": _font(), "mathtext.default": "regular", "svg.fonttype": "none"}
    with matplotlib.rc_context(rc):
        figure = Figure(figsize=(d.width * inch, d.height * inch), dpi=dpi, facecolor="white")
        FigureCanvasAgg(figure)
        ax = figure.add_axes((0, 0, 1, 1))
        ax.set_xlim(0, d.width)
        ax.set_ylim(d.height, 0)
        ax.set_axis_off()
        for it in d.items:
            if isinstance(it, Line):
                ax.plot(
                    [it.x1, it.x2],
                    [it.y1, it.y2],
                    color=it.stroke,
                    linewidth=it.width * PT_PER_UNIT,
                    solid_capstyle="butt",
                )
            elif isinstance(it, Dot):
                ax.add_patch(
                    Circle(
                        (it.cx, it.cy),
                        it.r,
                        facecolor=_rgba(it.fill, it.opacity),
                        edgecolor=it.stroke,
                        linewidth=0.5 * PT_PER_UNIT,
                    )
                )
            elif isinstance(it, Shape):
                if it.circle is not None:
                    cx, cy, r = it.circle
                    ax.add_patch(
                        Circle(
                            (cx, cy),
                            r,
                            facecolor="none",
                            edgecolor=it.stroke,
                            linewidth=1.1 * PT_PER_UNIT,
                        )  # fmt: skip
                    )
                else:
                    ax.add_patch(Polygon(list(it.points), closed=True, facecolor=it.fill,
                                         edgecolor="none"))  # fmt: skip
            elif isinstance(it, Text):
                ax.text(
                    it.x,
                    it.y,
                    _mathtext(it.segments),
                    fontsize=it.size * PT_PER_UNIT,
                    ha={"start": "left", "middle": "center", "end": "right"}[it.anchor],
                    va="baseline",
                    color=it.color,
                    fontweight="bold" if it.bold else "normal",
                    rotation=90 if it.rotate else 0,
                    rotation_mode="anchor",
                )
        out = io.BytesIO()
        figure.savefig(out, format="png", dpi=dpi, facecolor="white", metadata={"Software": None})
    return out.getvalue()


def _rgba(hex_color: str, alpha: float) -> tuple[float, float, float, float]:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255, alpha)


def _mathtext(segments: Sequence[Segment]) -> str:
    out = []
    for text, kind in segments:
        safe = text.replace("$", r"\$")
        if kind == "sup":
            out.append(f"$^{{{safe}}}$")
        elif kind == "sub":
            out.append(f"$_{{{safe}}}$")
        else:
            out.append(safe)
    return "".join(out)


def figure_png(fig: GeneFigure, dpi: int = DPI) -> bytes:
    """One gene's figure as a PNG (300 dpi by default)."""
    return png_bytes(drawing(fig), dpi)


def panel_png(figs: Sequence[GeneFigure], columns: int | None = None, dpi: int = DPI) -> bytes:
    """Several genes as one PNG."""
    return png_bytes(panel_drawing(figs, columns), dpi)


# ---------------------------------------------------------------------------------------------
# The figure's source data
# ---------------------------------------------------------------------------------------------

SOURCE_COLUMNS = (
    "analysis",
    "comparison",
    "gene",
    "group",
    "biological_unit",
    "log2_rq",
    "group_n",
    "group_mean_log2_rq",
    "group_ci95_low_log2_rq",
    "group_ci95_high_log2_rq",
)


def figure_rows(fig: GeneFigure) -> list[tuple]:
    """One row per dot: the unit's value and its group's summary (as drawn)."""
    rows = []
    for g in fig.groups:
        for unit, value in g.points:
            rows.append(
                (
                    fig.basis,
                    fig.comparison,
                    fig.gene,
                    g.name,
                    unit,
                    value,
                    g.n,
                    g.mean,
                    g.ci_lo,
                    g.ci_hi,
                )  # fmt: skip
            )
    return rows


def csv_value(value: Any) -> str:
    """One CSV cell: floats exact (``repr``), ``TRUE``/``FALSE``, empty for no value.

    Text a spreadsheet would read as a formula (``=``, ``+``, ``-``, ``@`` first) gets a
    leading apostrophe, so a name from a file never runs as a formula when the file is opened.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        return repr(value) if math.isfinite(value) else ""
    if isinstance(value, int):
        return str(value)
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def csv_text(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """UTF-8 CSV text: comma-separated, LF line ends, minimal quoting."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([csv_value(v) for v in row])
    return buf.getvalue()


def figure_csv(fig: GeneFigure) -> str:
    """The figure's source data as CSV (one row per biological unit)."""
    return csv_text(SOURCE_COLUMNS, figure_rows(fig))


def file_stem(gene: str) -> str:
    """A file-name-safe stem for a gene (``SDHA(1)`` stays; ``α-syn`` -> ``syn_<hash>``)."""
    from qpilot.core.names import file_part

    return file_part(gene, "gene")


__all__ = (
    "DPI",
    "PALETTE",
    "FigureError",
    "GeneFigure",
    "GroupDots",
    "csv_text",
    "csv_value",
    "figure_csv",
    "figure_png",
    "figure_rows",
    "figure_svg",
    "file_stem",
    "gene_figure",
    "mean_ci",
    "panel_png",
    "panel_svg",
    "swarm",
)
