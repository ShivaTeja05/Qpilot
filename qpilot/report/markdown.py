"""The report as Markdown (for a lab notebook, a repository or a manuscript draft).

Every string is escaped for Markdown and for the HTML a Markdown viewer may render: a gene or
sample name from the file can never become a link, an image, emphasis or a tag.
"""

from __future__ import annotations

import re

from qpilot.report import fmt
from qpilot.report.html import LEVEL_BARS, SEVERITY_WORD, STATUS_WORD
from qpilot.report.model import ReportText, ReportView
from qpilot.report.text import with_cites

# Inline constructs only: our own prefixes start every line, so data never starts a block.
_SPECIAL = re.compile(r"([\\`*_\[\]|~])")


def md(text: object) -> str:
    """Text safe in Markdown: specials backslash-escaped, ``<``/``>``/``&`` as entities."""
    s = "" if text is None else str(text)
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = _SPECIAL.sub(r"\\\1", s)
    return " ".join(s.split())


def code(text: object) -> str:
    """An id or hash as inline code (backticks removed: ids never contain them)."""
    return "`" + str(text).replace("`", "") + "`"


def para(text: ReportText | None, cites: bool = False) -> str:
    """A fact-bound text as one escaped line."""
    if text is None:
        return ""
    return md(with_cites(text) if cites else text.plain)


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def document(view: ReportView) -> str:
    """The report as Markdown."""
    h = view.header
    lines = [
        f"# Study report — {md(h.title)}",
        "",
        f"_{md(h.research_use)}_",
        "",
        f"- Study: {code(h.study_id)}",
    ]
    if h.source_name:
        lines.append(f"- Input file: {md(h.source_name)}")
    lines += [
        f"- Input SHA-256: {code(h.input_sha256)}",
        f"- Decision log head: {code(h.chain_head)}",
        f"- Written: {md(h.generated_at)}",
        "- Software: " + md(", ".join(f"{k} {v}" for k, v in h.versions.items() if v != "unknown")),
        "",
        "## Summary",
        "",
        para(view.summary),
        "",
        _row(["Key number", "Value"]),
        _row(["---", "---:"]),
    ]
    for k in view.key_numbers:
        fact = view.facts.get(k.fact)
        if fact is not None:
            lines.append(_row([md(k.label), md(fact.text)]))
    r = view.review
    lines += ["", "## Reviewer's report", "", para(r.lead), ""]
    for f in r.findings:
        glyph, word = SEVERITY_WORD[f.severity]
        lines.append(f"- **{glyph} {word} · {md(f.title)}.** {para(f.text)}")
    if r.passed:
        lines += ["", "### What checks out", ""]
        lines += [f"- **{md(p.title)}.** {para(p.text)}" for p in r.passed]
    lines += ["", "## Methods", ""]
    for p in view.methods.paragraphs:
        lines += [f"### {md(p.title)}", "", para(p.text, cites=True), ""]
    if view.methods.citations:
        lines += ["### References", ""]
        lines += [f"{c.n}\\. {md(c.text)}" for c in view.methods.citations]
        lines.append("")
    m = view.miqe
    lines += ["## MIQE 2.0 checklist", "", para(m.headline), ""]
    section = None
    for item in m.items:
        if item.section != section:
            section = item.section
            lines += [
                "",
                f"### {md(section)}",
                "",
                _row(["Item", "What MIQE asks", "Status", "Evidence"]),
            ]
            lines.append(_row(["---", "---", "---", "---"]))
        glyph, word = STATUS_WORD[item.status]
        lines.append(_row([md(item.id), md(item.label), f"{glyph} {word}", para(item.evidence)]))
    lines += ["", f"_Item list: {md(m.pack.citation)}_", "", "## Limitations", ""]
    lines += [f"- {para(x.text)}" for x in view.limitations]
    lines += [
        "",
        "## Every gene",
        "",
        _row(["Gene", "Call", "Fold [95 % CI]", "p", "n", "Holds", "Confidence", "Audit"]),
        _row(["---", "---", "---:", "---:", "---:", "---:", "---", "---"]),
    ]
    for g in view.genes:
        name = f"**{md(g.gene)}**" if g.headline else md(g.gene)
        level = f"{'▮' * LEVEL_BARS.get(g.level or '', 0)} {md(g.level)}" if g.level else "—"
        lines.append(
            _row(
                [
                    name,
                    md(fmt.CALL_WORD[g.conclusion]),
                    md(f"{fmt.fold(g.fc)} {fmt.ci(g.ci_lo, g.ci_hi)}"),
                    md(fmt.p_value(g.p)),
                    md(f"{fmt.count(g.n_hi)} / {fmt.count(g.n_lo)}"),
                    md(fmt.percent(g.holds)),
                    level,
                    md(g.verdict_label or "—"),
                ]
            )
        )
    lines += [
        "",
        "## Facts cited",
        "",
        _row(["Fact", "Value", "From"]),
        _row(["---", "---:", "---"]),
    ]
    lines += [_row([code(f.id), md(f.text), code(f.path)]) for f in view.facts.values()]
    lines += [
        "",
        "---",
        "",
        f"_Written by qPilot from the study's own numbers on {md(h.generated_at)}. "
        "Tamper-evident, not tamper-proof._",
        "",
    ]
    return "\n".join(lines)
