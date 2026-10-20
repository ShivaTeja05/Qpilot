"""Charts for the exported files, drawn on the server as inline SVG from the report's numbers.

No scripts and no external references: hover text is SVG ``<title>``, colours are CSS classes the
document's own stylesheet defines (so dark mode and print work), every string is escaped. Meaning
is never colour alone: calls have a shape (▲ up, ▼ down, ○ no call), verdicts a glyph and a word.
"""

from __future__ import annotations

import math
from html import escape

from qpilot.report import fmt
from qpilot.report.model import ReportAudit, ReportGene

W = 720


def _e(text: object) -> str:
    return escape(str(text), quote=True)


def _tri(x: float, y: float, r: float, up: bool) -> str:
    h = r * 1.15
    if up:
        pts = [(x, y - h), (x - r, y + h * 0.6), (x + r, y + h * 0.6)]
    else:
        pts = [(x, y + h), (x - r, y - h * 0.6), (x + r, y - h * 0.6)]
    return " ".join(f"{a:.1f},{b:.1f}" for a, b in pts)


def robustness_map(genes: list[ReportGene], holds_min: float = 0.8) -> str:
    """Every gene: fold change (log2 axis, labelled in ×) against how often its call holds."""
    pts = [g for g in genes if g.holds is not None and g.fc > 0]
    if not pts:
        return ""
    h, ml, mr, mt, mb = 380, 52, 18, 18, 46
    pw, ph = W - ml - mr, h - mt - mb
    span = max(3, min(7, math.ceil(max(abs(math.log2(g.fc)) for g in pts))))

    def x(fc: float) -> float:
        v = max(-span, min(span, math.log2(fc)))
        return ml + (v + span) / (2 * span) * pw

    def y(share: float) -> float:
        return mt + (1 - share) * ph

    out = [
        f'<svg class="chart" viewBox="0 0 {W} {h}" role="img" aria-labelledby="rm-t rm-d">',
        '<title id="rm-t">Robustness map</title>',
        f'<desc id="rm-d">{len(pts)} genes: fold change on a log2 axis against the share of '
        "qPilot's choice grid that gives the same call.</desc>",
    ]
    for k in range(-span, span + 1):
        xv = x(2.0**k)
        out.append(f'<line class="grid" x1="{xv:.1f}" x2="{xv:.1f}" y1="{mt}" y2="{mt + ph}"/>')
        out.append(
            f'<text class="tick" x="{xv:.1f}" y="{mt + ph + 16}" text-anchor="middle">'
            f"{_e(_tick(2.0**k))}</text>"
        )
    for share in (0, 0.25, 0.5, 0.75, 1):
        yv = y(share)
        out.append(f'<line class="grid" x1="{ml}" x2="{ml + pw}" y1="{yv:.1f}" y2="{yv:.1f}"/>')
        out.append(
            f'<text class="tick" x="{ml - 6}" y="{yv + 4:.1f}" text-anchor="end">'
            f"{_e(fmt.percent(share))}</text>"
        )
    for k in (-1, 1):
        xv = x(2.0**k)
        out.append(f'<line class="rule" x1="{xv:.1f}" x2="{xv:.1f}" y1="{mt}" y2="{mt + ph}"/>')
    yv = y(holds_min)
    out.append(f'<line class="rule dotted" x1="{ml}" x2="{ml + pw}" y1="{yv:.1f}" y2="{yv:.1f}"/>')
    out.append(
        f'<text class="axis" x="{ml + pw / 2:.1f}" y="{h - 6}" text-anchor="middle">'
        "fold change (log2 axis; dashed: the 2-fold lines)</text>"
    )
    out.append(
        f'<text class="axis" transform="translate(14 {mt + ph / 2:.1f}) rotate(-90)" '
        'text-anchor="middle">same call in qPilot\'s choice grid</text>'
    )
    placed: list[tuple[float, float, float, float]] = []
    for g in sorted(pts, key=lambda g: (g.headline, g.fc)):
        xv, yv = x(g.fc), y(g.holds or 0)
        tip = (
            f"{g.gene}: {g.conclusion}, {fmt.fold(g.fc)} {fmt.ci(g.ci_lo, g.ci_hi)}, "
            f"same call in {fmt.percent(g.holds)}"
        )
        if g.verdict_label:
            tip += f"; audit: {g.verdict_label}"
        r = 6 if g.headline else 4.5
        if g.conclusion == "none":
            mark = f'<circle class="pt none" cx="{xv:.1f}" cy="{yv:.1f}" r="{r - 0.5}"/>'
        else:
            pts_ = _tri(xv, yv, r, g.conclusion == "up")
            mark = f'<polygon class="pt {g.conclusion}" points="{pts_}"/>'
        out.append(f"<g><title>{_e(tip)}</title>{mark}</g>")
        if g.headline:
            out.append(_label(g.gene, xv, yv, placed, ml + pw))
    out.append("</svg>")
    return "".join(out)


def _tick(v: float) -> str:
    """An axis tick of the fold axis: ``0.25×``, ``1×``, ``32×``."""
    return f"{v:.3g}×"


def _overlaps(box: tuple[float, ...], placed: list[tuple[float, float, float, float]]) -> bool:
    return any(box[0] < b[2] and b[0] < box[2] and box[1] < b[3] and b[1] < box[3] for b in placed)


def _label(text: str, x: float, y: float, placed: list, right: float) -> str:
    """A point's label beside it, moved where it does not overlap a label already placed."""
    w, h = 7.2 * len(text), 13
    spots = ((x + 8, y - 7, "start"), (x + 8, y + 17, "start"), (x - 8, y - 7, "end"))
    spots += ((x - 8, y + 17, "end"), (x + 8, y - 21, "start"), (x + 8, y + 31, "start"))
    for lx, ly, anchor in spots:
        x0 = lx if anchor == "start" else lx - w
        if x0 + w > right + 12:
            continue
        box = (x0, ly - h + 2, x0 + w, ly + 2)
        if not _overlaps(box, placed):
            placed.append(box)
            return (
                f'<text class="label" x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}">'
                f"{_e(text)}</text>"
            )
    return ""


VERDICT_ORDER = (
    "solid",
    "holds with caveats",
    "depends on your choices",
    "fragile",
    "check data first",
    "no call",
)
VERDICT_GLYPH = {
    "solid": "●",
    "holds with caveats": "◐",
    "depends on your choices": "◆",
    "fragile": "▲",
    "check data first": "■",
    "no call": "○",
}


def verdict_bar(audit: ReportAudit) -> str:
    """The audit's verdicts as one stacked bar (the document adds the legend: glyph + word)."""
    counts = [(v, audit.verdict_counts.get(v, 0)) for v in VERDICT_ORDER]
    counts += [(v, n) for v, n in audit.verdict_counts.items() if v not in VERDICT_ORDER]
    total = sum(n for _, n in counts)
    if not total:
        return ""
    h = 26
    out = [
        f'<svg class="chart" viewBox="0 0 {W} {h}" role="img" aria-labelledby="vb-t">',
        '<title id="vb-t">Audit verdicts: '
        + _e("; ".join(f"{n} {audit.verdict_labels.get(v, v)}" for v, n in counts if n))
        + "</title>",
    ]
    x = 0.0
    for v, n in counts:
        if not n:
            continue
        w = n / total * W
        cls = "v-" + v.replace(" ", "-")
        out.append(
            f"<g><title>{_e(audit.verdict_labels.get(v, v))}: {n}</title>"
            f'<rect class="seg {cls}" x="{x:.1f}" y="0" width="{max(w - 1, 1):.1f}" height="26"/>'
        )
        if w > 22:
            out.append(
                f'<text class="seg-n" x="{x + w / 2:.1f}" y="18" text-anchor="middle">{n}</text>'
            )
        out.append("</g>")
        x += w
    out.append("</svg>")
    return "".join(out)


STATUS_ORDER = ("met", "not_met", "not_applicable", "cannot_tell")


def miqe_ring(counts: dict[str, int], size: int = 120) -> str:
    """The MIQE items by status as a ring (a count, never a score)."""
    total = sum(counts.get(s, 0) for s in STATUS_ORDER)
    if not total:
        return ""
    r, cx, cy, sw = 44, size / 2, size / 2, 14
    circ = 2 * math.pi * r
    out = [
        f'<svg class="ring" viewBox="0 0 {size} {size}" width="{size}" height="{size}" role="img" '
        'aria-labelledby="mr-t">',
        '<title id="mr-t">MIQE items by status: '
        + _e(", ".join(f"{counts.get(s, 0)} {s.replace('_', ' ')}" for s in STATUS_ORDER))
        + "</title>",
        f'<circle class="ring-bg" cx="{cx}" cy="{cy}" r="{r}" stroke-width="{sw}" fill="none"/>',
    ]
    offset = 0.0
    for s in STATUS_ORDER:
        n = counts.get(s, 0)
        if not n:
            continue
        length = n / total * circ
        out.append(
            f'<circle class="ring-{s}" cx="{cx}" cy="{cy}" r="{r}" fill="none" '
            f'stroke-width="{sw}" stroke-dasharray="{length:.2f} {circ - length:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 {cx} {cy})"/>'
        )
        offset += length
    out.append(
        f'<text class="ring-n" x="{cx}" y="{cy + 2}" text-anchor="middle">'
        f"{counts.get('met', 0)}/{total}</text>"
        f'<text class="ring-l" x="{cx}" y="{cy + 18}" text-anchor="middle">met</text></svg>'
    )
    return "".join(out)
