"""The report as HTML: a printable page, and the **study passport** (one offline file).

Both are one HTML file with inline CSS, no scripts, no fonts, images or links to fetch, and a
Content-Security-Policy that forbids anything else (``default-src 'none'``). Every string from
the study (gene, sample and option names, reasons, file names) is escaped. The passport adds
the charts (inline SVG drawn here from the report's numbers), the gene table, the decision log,
the audit's verdicts, every cited fact with where it comes from, and the Analysis Record it is
bound to with the commands that check it.
"""

from __future__ import annotations

from html import escape

from qpilot.report import fmt, svg
from qpilot.report.model import MiqeItem, ReportText, ReportView
from qpilot.report.text import cite_groups

CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; "
    "form-action 'none'"
)
STATUS_WORD = {
    "met": ("✓", "Met"),
    "not_met": ("✕", "Not met"),
    "not_applicable": ("–", "Not applicable"),
    "cannot_tell": ("?", "Cannot tell from the data"),
}
SEVERITY_WORD = {"major": ("▲", "Major"), "minor": ("●", "Minor"), "note": ("○", "Note")}
LEVEL_BARS = {"High": 4, "Moderate": 3, "Low": 2, "Very low": 1}


def e(text: object) -> str:
    """Escaped text (quotes too)."""
    return escape("" if text is None else str(text), quote=True)


def text_html(text: ReportText | None, view: ReportView) -> str:
    """Fact-bound text: each fact a span naming where it comes from; quoted data as text."""
    if text is None:
        return ""
    out = []
    for seg, group in cite_groups(text):
        if group is not None:
            out.append(f'<sup class="cite">[{e(", ".join(map(str, group)))}]</sup>')
        elif seg.fact:
            fact = view.facts.get(seg.fact)
            where = f"{seg.fact} — {fact.path}" if fact else seg.fact
            out.append(f'<span class="fact" title="{e(where)}">{e(seg.text)}</span>')
        elif seg.quote:
            out.append(f'<span class="q">{e(seg.text)}</span>')
        else:
            out.append(e(seg.text))
    return "".join(out)


STYLE = """
:root{--bg:#fbfbfa;--surface:#fff;--sunken:#f3f4f2;--line:#e2e4e0;--fg:#1c1f1d;--muted:#5d625f;
--faint:#868b88;--accent:#0f766e;--accent-soft:#e6f4f1;--up:#b4441c;--down:#1d5fa8;--none:#6b6f6c;
--ok:#1f7a3f;--warn:#9a6200;--danger:#b42318;--info:#2f5fa7;--v-solid:#1f7a3f;--v-caveats:#5b8a1c;
--v-depends:#9a6200;--v-fragile:#b42318;--v-check:#7a3fb4;--v-nocall:#8a8f8c}
@media (prefers-color-scheme:dark){:root{--bg:#121413;--surface:#1a1d1b;--sunken:#151816;
--line:#2c302e;--fg:#e8eae8;--muted:#a3a8a5;--faint:#7c817e;--accent:#4fb3a6;--accent-soft:#163430;
--up:#f08a5d;--down:#6aa8f0;--none:#9a9f9c;--ok:#5cc282;--warn:#e0a54a;--danger:#f0786b;
--info:#7aa7ec;--v-solid:#5cc282;--v-caveats:#a6cf5e;--v-depends:#e0a54a;--v-fragile:#f0786b;
--v-check:#c49af0;--v-nocall:#8f9491}}
*{box-sizing:border-box}html{background:var(--bg);color:var(--fg)}
body{margin:0 auto;max-width:920px;padding:32px 20px 64px;font:14px/1.55 system-ui,-apple-system,
"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif}
h1{font-size:26px;line-height:1.25;margin:0 0 6px}h2{font-size:19px;margin:36px 0 10px;
padding-top:10px;border-top:1px solid var(--line)}h3{font-size:15px;margin:20px 0 6px}
p{margin:6px 0 10px}.muted{color:var(--muted)}.small{font-size:12.5px}
.mono,code{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:12.5px}
code{background:var(--sunken);border:1px solid var(--line);border-radius:6px;padding:1px 5px;
word-break:break-all}
.ids{display:grid;grid-template-columns:max-content 1fr;gap:2px 14px;margin:12px 0;font-size:13px}
.ids dt{color:var(--muted)}.ids dd{margin:0;word-break:break-all}
.banner{border:1px solid var(--line);background:var(--surface);border-radius:12px;padding:12px 16px;
margin:14px 0}.banner.accent{background:var(--accent-soft);border-color:transparent}
.keys{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0}.key{background:var(--surface);
border:1px solid var(--line);border-radius:10px;padding:8px 12px;min-width:120px}
.key b{display:block;font-size:20px;font-variant-numeric:tabular-nums}.key span{color:var(--muted);
font-size:12px}.fact{font-variant-numeric:tabular-nums;font-weight:600;
text-decoration:underline dotted var(--faint);text-underline-offset:3px}
.q{font-style:normal}.cite{color:var(--accent);font-size:10.5px}
table{border-collapse:collapse;width:100%;font-size:12.5px;margin:8px 0 16px}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:600;background:var(--sunken)}td.num,th.num{text-align:right;
font-variant-numeric:tabular-nums;white-space:nowrap}tr.hl td{background:var(--accent-soft)}
.st-met{color:var(--ok)}.st-not_met{color:var(--danger)}.st-not_applicable{color:var(--muted)}
.st-cannot_tell{color:var(--warn)}.sev-major{color:var(--danger)}.sev-minor{color:var(--warn)}
.sev-note{color:var(--info)}.call-up{color:var(--up)}.call-down{color:var(--down)}
.call-none{color:var(--none)}.finding{border:1px solid var(--line);border-radius:10px;
padding:10px 14px;margin:8px 0;background:var(--surface)}.finding h4{margin:0 0 4px;font-size:14px}
.chart{width:100%;height:auto;display:block;margin:8px 0}.chart .grid{stroke:var(--line);
stroke-width:1}.chart .rule{stroke:var(--faint);stroke-width:1;stroke-dasharray:5 4}
.chart .dotted{stroke-dasharray:2 3}.chart text{fill:var(--muted);font-size:11px}
.chart .label{fill:var(--fg);font-size:11.5px;font-weight:600}.chart .axis{font-size:11.5px}
.pt.up{fill:var(--up)}.pt.down{fill:var(--down)}.pt.none{fill:none;stroke:var(--none);
stroke-width:1.5}.seg.v-solid{fill:var(--v-solid)}.seg.v-holds-with-caveats{fill:var(--v-caveats)}
.seg.v-depends-on-your-choices{fill:var(--v-depends)}.seg.v-fragile{fill:var(--v-fragile)}
.seg.v-check-data-first{fill:var(--v-check)}.seg.v-no-call{fill:var(--v-nocall)}
.chart .seg-n{fill:#fff;font-weight:700;font-size:12px}.chart .legend{font-size:12px;fill:var(--fg)}
.ring-bg{stroke:var(--sunken)}.ring-met{stroke:var(--ok)}.ring-not_met{stroke:var(--danger)}
.ring-not_applicable{stroke:var(--faint)}.ring-cannot_tell{stroke:var(--warn)}
.ring-n{fill:var(--fg);font-size:20px;font-weight:700}.ring-l{fill:var(--muted);font-size:11px}
.miqe-head{display:flex;gap:18px;align-items:center}details{margin:8px 0}
summary{cursor:pointer;color:var(--accent);font-weight:600}
.verify ol{margin:6px 0 0 18px;padding:0}.verify li{margin:4px 0}
ul.legend{list-style:none;display:flex;flex-wrap:wrap;gap:4px 16px;padding:0;margin:4px 0 12px;
font-size:12.5px}.sw.v-solid{color:var(--v-solid)}.sw.v-holds-with-caveats{color:var(--v-caveats)}
.sw.v-depends-on-your-choices{color:var(--v-depends)}.sw.v-fragile{color:var(--v-fragile)}
.sw.v-check-data-first{color:var(--v-check)}.sw.v-no-call{color:var(--v-nocall)}
footer{margin-top:40px;color:var(--faint);font-size:12px}
@media print{html,body{background:#fff;color:#000}body{max-width:none;padding:0}
h2{break-after:avoid}table,.finding,.chart{break-inside:avoid}details{display:block}
details>summary{display:none}.banner{border-color:#ccc}}
@media (max-width:640px){body{padding:20px 14px 40px}h1{font-size:22px}
.ids{grid-template-columns:1fr}.ids dt{margin-top:6px}table{display:block;overflow-x:auto}}
"""


def _head(title: str) -> str:
    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        # CSP is our own constant (no double quote): written as is, its single quotes intact
        f'<meta http-equiv="Content-Security-Policy" content="{CSP}">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="referrer" content="no-referrer">'
        f"<title>{e(title)}</title><style>{STYLE}</style></head><body>"
    )


def _ids(view: ReportView, record: object | None = None) -> str:
    h = view.header
    rows = [("Study", f'<span class="mono">{e(h.study_id)}</span>')]
    if h.source_name:
        rows.append(("Input file", e(h.source_name)))
    rows.append(("Input SHA-256", f'<span class="mono">{e(h.input_sha256)}</span>'))
    rows.append(("Decision log head", f'<span class="mono">{e(h.chain_head)}</span>'))
    rec = getattr(record, "record_id", None)
    if rec:
        rows.append(("Analysis Record", f'<span class="mono">{e(rec)}</span>'))
    rows.append(("Written", e(h.generated_at)))
    versions = ", ".join(f"{k} {v}" for k, v in h.versions.items() if v and v != "unknown")
    rows.append(("Software", e(versions)))
    return '<dl class="ids">' + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>"


def _keys(view: ReportView) -> str:
    out = []
    for k in view.key_numbers:
        fact = view.facts.get(k.fact)
        if fact is None:
            continue
        out.append(
            f'<div class="key" title="{e(fact.id + " — " + fact.path)}"><b>{e(fact.text)}</b>'
            f"<span>{e(k.label)}</span></div>"
        )
    return '<div class="keys">' + "".join(out) + "</div>"


def _methods(view: ReportView) -> str:
    m = view.methods
    out = ['<h2 id="methods">Methods</h2>']
    for p in m.paragraphs:
        out.append(f"<h3>{e(p.title)}</h3><p>{text_html(p.text, view)}</p>")
    if m.citations:
        out.append('<h3>References</h3><ol class="small">')
        out += [f"<li>{e(c.text)}</li>" for c in m.citations]
        out.append("</ol>")
    return "".join(out)


def _verdict_legend(view: ReportView) -> str:
    a = view.audit
    items = []
    for v in (*svg.VERDICT_ORDER, *(k for k in a.verdict_counts if k not in svg.VERDICT_ORDER)):
        n = a.verdict_counts.get(v)
        if n:
            cls = "v-" + v.replace(" ", "-")
            items.append(
                f'<li><span class="sw {cls}">{svg.VERDICT_GLYPH.get(v, "•")}</span> '
                f"{e(a.verdict_labels.get(v, v))} <b>{e(n)}</b></li>"
            )
    return '<ul class="legend">' + "".join(items) + "</ul>"


def _review(view: ReportView) -> str:
    r = view.review
    out = [f'<h2 id="review">Reviewer\'s report</h2><p>{text_html(r.lead, view)}</p>']
    for f in r.findings:
        glyph, word = SEVERITY_WORD[f.severity]
        shown = [g for g in f.genes if g not in f.title]
        genes = f' <span class="muted small">({e(", ".join(shown))})</span>' if shown else ""
        out.append(
            f'<div class="finding"><h4><span class="sev-{f.severity}">{glyph} {word}</span> · '
            f"{e(f.title)}{genes}</h4><p>{text_html(f.text, view)}</p></div>"
        )
    if r.passed:
        out.append("<h3>What checks out</h3><ul>")
        out += [f"<li><b>{e(p.title)}.</b> {text_html(p.text, view)}</li>" for p in r.passed]
        out.append("</ul>")
    return "".join(out)


def _miqe_row(item: MiqeItem, view: ReportView) -> str:
    glyph, word = STATUS_WORD[item.status]
    return (
        f'<tr><td class="mono">{e(item.id)}</td><td>{e(item.label)}</td>'
        f'<td class="st-{item.status}" style="white-space:nowrap">{glyph} {word}</td>'
        f"<td>{text_html(item.evidence, view)}</td></tr>"
    )


def _miqe(view: ReportView, ring: bool) -> str:
    m = view.miqe
    head = f"<p>{text_html(m.headline, view)}</p>"
    if ring:
        head = f'<div class="miqe-head">{svg.miqe_ring(m.counts)}<div>{head}</div></div>'
    out = [f'<h2 id="miqe">MIQE 2.0 checklist</h2>{head}']
    section = None
    rows = []
    for item in m.items:
        if item.section != section:
            if rows:
                out.append(_table(rows))
                rows = []
            section = item.section
            out.append(f"<h3>{e(section)}</h3>")
        rows.append(_miqe_row(item, view))
    if rows:
        out.append(_table(rows))
    out.append(
        f'<p class="small muted">Item list: {e(m.pack.citation)} (map {e(m.pack.name)} '
        f'{e(m.pack.version)}, SHA-256 <span class="mono">{e(m.pack.sha256)}</span>).</p>'
    )
    return "".join(out)


def _table(rows: list[str]) -> str:
    return (
        "<table><thead><tr><th>Item</th><th>What MIQE asks</th><th>Status</th><th>Evidence</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _limitations(view: ReportView) -> str:
    items = "".join(f"<li>{text_html(x.text, view)}</li>" for x in view.limitations)
    return f'<h2 id="limitations">Limitations</h2><ul>{items}</ul>'


def _genes(view: ReportView) -> str:
    rows = []
    for g in view.genes:
        level = f"{'▮' * LEVEL_BARS.get(g.level or '', 0)} {g.level}" if g.level else "—"
        rows.append(
            f'<tr class="{"hl" if g.headline else ""}"><td><b>{e(g.gene)}</b></td>'
            f'<td class="call-{g.conclusion}">{e(fmt.CALL_WORD[g.conclusion])}</td>'
            f'<td class="num">{e(fmt.fold(g.fc))} {e(fmt.ci(g.ci_lo, g.ci_hi))}</td>'
            f'<td class="num">{e(fmt.p_value(g.p))}</td>'
            f'<td class="num">{e(fmt.count(g.n_hi))} / {e(fmt.count(g.n_lo))}</td>'
            f'<td class="num">{e(fmt.percent(g.holds))}</td><td>{e(level)}</td>'
            f"<td>{e(g.verdict_label or '—')}</td></tr>"
        )
    n_cells = next((g.n_cells for g in view.genes if g.n_cells), 0)
    return (
        '<h2 id="genes">Every gene</h2><p class="muted small">Headline genes first (shaded). '
        f"{e(view.rule)} “Holds”: the share of the {e(fmt.count(n_cells))} analyses qPilot checks "
        "that give the same call; “Audit”: the verdict in the audit's reasonable set.</p>"
        '<table><thead><tr><th>Gene</th><th>Call</th><th class="num">Fold [95 % CI]</th>'
        '<th class="num">p</th><th class="num">n</th><th class="num">Holds</th><th>Confidence'
        "</th><th>Audit</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _decisions(view: ReportView) -> str:
    rows = []
    for d in view.decisions:
        by = {"human": "a person", "agent": "an agent", "system": "automatically"}.get(
            d.actor or "", d.actor or "—"
        )
        rows.append(
            f'<tr><td class="num">{e(d.seq if d.seq is not None else "—")}</td>'
            f"<td>{e(d.card_title)}</td><td>{e(d.option_label or d.option or '—')}</td>"
            f"<td>{e(by)}</td><td>{e(d.status)}{' · can change a call' if d.can_flip else ''}"
            f"</td><td>{e(d.reason or '')}</td>"
            f'<td class="mono">{e((d.hash or "")[:12])}</td></tr>'
        )
    return (
        '<h2 id="decisions">Decisions</h2><p class="muted small">The hash-chained decision log, '
        "then the choices still open (their recommended option is used).</p><table><thead><tr>"
        '<th class="num">#</th><th>Choice</th><th>Option</th><th>By</th><th>Status</th>'
        "<th>Reason</th><th>Hash</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _facts(view: ReportView) -> str:
    rows = "".join(
        f'<tr><td class="mono">{e(f.id)}</td><td class="num">{e(f.text)}</td>'
        f'<td class="mono small">{e(f.path)}</td></tr>'
        for f in view.facts.values()
    )
    return (
        f'<h2 id="facts">Every number, and where it comes from</h2><details><summary>'
        f'{e(fmt.count(len(view.facts)))} facts cited in this file</summary><p class="small '
        "muted\">f_… ids are the engine's own facts; f_rpt_… ids are values this report read "
        "from the study (the path says where).</p><table><thead><tr><th>Fact</th>"
        '<th class="num">Value</th><th>From</th></tr></thead><tbody>'
        + rows
        + "</tbody></table></details>"
    )


def _verify(view: ReportView, record: object | None) -> str:
    rec_id = getattr(record, "record_id", None)
    name = getattr(getattr(record, "download", None), "name", None)
    if not rec_id or not name:
        return (
            '<div class="banner"><b>How to check this report.</b> Every number in it is a fact '
            "of the study, listed with where it comes from at the end. Export the Analysis "
            "Record from qPilot to verify and re-run the analysis.</div>"
        )
    return (
        '<div class="banner accent verify"><b>How to verify this passport</b><ol>'
        f"<li>Get the Analysis Record <code>{e(name)}</code> that was written with it.</li>"
        f"<li>Run <code>qpilot verify {e(name)}</code>: it checks every file's checksum and both "
        "hash chains.</li>"
        f'<li>Its record id must be <code class="mono">{e(rec_id)}</code> (the SHA-256 of the '
        "record's CHECKSUMS.sha256) and its decision log head "
        f'<code class="mono">{e(view.header.chain_head)}</code>.</li>'
        f"<li>Run <code>qpilot rerun {e(name)}</code> to recompute every number from the input "
        "file.</li></ol></div>"
    )


def document(view: ReportView, *, passport: bool = False, record: object | None = None) -> str:
    """The report as one HTML file (``passport=True``: charts, tables, facts and the record)."""
    h = view.header
    kind = "Study passport" if passport else "Study report"
    title = f"{kind} — {h.title}"
    out = [
        _head(title),
        f'<header><p class="muted small">qPilot · {e(kind)}</p><h1>{e(h.title)}</h1>'
        f'<p class="muted">{e(h.research_use)}</p>{_ids(view, record)}</header>',
    ]
    if passport:
        out.append(_verify(view, record))
    out.append(f'<h2 id="summary">Summary</h2><p>{text_html(view.summary, view)}</p>{_keys(view)}')
    if passport:
        out.append(
            '<h3>Robustness map</h3><p class="muted small">Each gene: its fold change and how '
            "often its call holds across qPilot's choice grid (▲ up, ▼ down, ○ no call; headline "
            "genes labelled; dotted: the line a robust call should stay above).</p>"
            + svg.robustness_map(view.genes)
        )
        if view.audit.status == "ready":
            out.append(
                "<h3>The audit's verdicts</h3>"
                + (
                    f'<p class="muted small">In the audit\'s reasonable set of '
                    f"{e(fmt.count(view.audit.reasonable))} analyses"
                    if view.audit.reasonable
                    else '<p class="muted small">'
                )
                + (" (run at the current decision log)." if view.audit.current else
                   " (run at an earlier decision log).")
                + "</p>"
                + svg.verdict_bar(view.audit)
                + _verdict_legend(view)
            )  # fmt: skip
    out.append(_review(view))
    if passport:
        out.append(_genes(view))
        out.append(_decisions(view))
    out.append(_methods(view))
    out.append(_miqe(view, ring=passport))
    out.append(_limitations(view))
    if passport:
        out.append(_facts(view))
    out.append(
        f"<footer>Written by qPilot from the study's own numbers on {e(h.generated_at)}. "
        "Tamper-evident, not tamper-proof. Research use only.</footer></body></html>"
    )
    return "".join(out)
