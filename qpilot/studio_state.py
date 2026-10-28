"""Studio's wording and views: proposals in plain words, stages and the Prism preview.

The one page uses the plain-words descriptions (:func:`describe`, through
:mod:`qpilot.web.studio_views`); the escaped-HTML views remain for the Studio service's tests and
the record (``tests/studio``). Three rules hold for everything returned here:

* every string that came from the input file, the sample sheet, a model or an agent (sample and
  target names, quarantined text, reasons, evidence notes, model and agent names, check notes,
  payload values) is HTML-escaped with :func:`qpilot.app_state.esc` before it reaches markup;
  text drawn by Plotly is escaped too;
* during the blind stages a card's consequence says at most "this matters for at least one
  conclusion" (the service's boolean); fold changes, p-values and conclusions are rendered only
  for the round trip, and only while the results are visible; "What the model saw" shows only
  the Design Interpreter's payload then, since any other model call may have been sent results;
* every number is the engine's (a check's details, a consequence, a fact) or a plain count;
  nothing is typed by hand.

Each proposal card has the six fixed parts of the plan (``qPilot-STUDIO-PRISM-PLAN.md`` §3):
Proposal, Why, Engine check, Consequence, Level and Actions, then a footer naming who made it.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

import plotly.graph_objects as go

from qpilot.ai.payload_log import canonical
from qpilot.ai.prompts import SYSTEM_INTERPRET
from qpilot.app_state import conclusion_word, esc
from qpilot.core.facts import slug
from qpilot.explain.templates import to_html
from qpilot.schemas import Fact
from qpilot.schemas_studio import TEXT_ID, InspectSummary, MadeBy, Proposal, QuarantineEntry
from qpilot.studio_service import BLIND_STAGES, STAGES

STAGE_LABELS = {
    "design": "Design (blind)",
    "curves": "Curves (blind)",
    "choices": "Choices",
    "prism": "Prism draft",
    "roundtrip": "Round trip",
}
CHECK_WORDS = {
    "consistent": "consistent",
    "contradicted": "contradicted",
    "cannot_check": "cannot check",
}
CHECK_MEANING = {
    "consistent": "the engine found nothing that refutes it (a check can refute, never prove)",
    "contradicted": "the engine's check refutes it; accepting it anyway needs a reason",
    "cannot_check": "no engine check applies; decide it on the evidence",
}
STATUS_WORDS = {
    "proposed": "waiting for a person",
    "accepted": "accepted",
    "edited": "edited and accepted",
    "rejected": "rejected",
    "superseded": "replaced by a newer proposal",
}
ROLE_WORDS = {
    "unkn": "a study sample",
    "std": "a standard of known quantity",
    "ntc": "a no-template control",
    "nrt": "a no-reverse-transcription control",
    "nac": "a no-amplification control",
    "pos": "a positive control",
    "opt": "an optical calibrator",
    "ntp": "a no-target-present control",
}
PRESET_WORDS = {
    "vermeulen_expression_defined": (
        "the published design of the Vermeulen neuroblastoma dataset: tumours compared by MYCN "
        "expression (an expression-defined split, not a clinical call), normalised to the "
        "original study's five reference genes"
    ),
}
MATTERS_TEXT = "This matters for at least one conclusion; decide on the evidence."
NOT_MATTERS_TEXT = "Neither reading changes any conclusion."
BLIND_TEXT = (
    "Hidden in the blind stages: no gene, direction or number is shown before the design and "
    "the curves are confirmed."
)
SEEN_HIDDEN_TEXT = (
    "Hidden: the design or the curves are not confirmed (again) yet, and the last model call did "
    "not come from the Design Interpreter, so what it was sent may include results."
)
CURVE_JUDGE = "qpilot-curve-judge"
MAX_EVIDENCE_SHOWN = 30
MAX_JSON_CHARS = 20_000
CHECK_ORDER = {"contradicted": 0, "cannot_check": 1, "consistent": 2}
GROUP_COLORS = ("#2a78d6", "#eb6834")  # categorical slots 1-2, validated as a pair
INK = "#52514e"


# ---------- describing a proposal in plain words ----------


def _num(value: Any) -> str:
    return (
        f"{value:g}"
        if isinstance(value, int | float) and not isinstance(value, bool)
        else str(value)
    )


def _short_json(data: Any, limit: int = 300) -> str:
    text = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


def rule_words(rule: Any) -> str:
    """An amplification-call rule id in words."""
    rule = str(rule)
    if rule == "linregpcr":
        return "LinRegPCR's call (it found an exponential phase and a quantity)"
    if rule == "learned":
        return "the Curve Judge's call (a model that reads the curve's shape)"
    match = re.fullmatch(r"cq_le_(\d+(?:\.\d+)?)", rule)
    if match:
        return f"a Cq cut-off: a Cq above {match.group(1)} counts as not amplified"
    return f"the rule {rule!r}"


def _d_preset(subject: str, d: Mapping[str, Any]) -> str:
    preset = str(d["preset"])
    known = PRESET_WORDS.get(preset)
    return f"Use the built-in design “{preset}”" + (f": {known}" if known else "")


def _d_role(subject: str, d: Mapping[str, Any]) -> str:
    role = str(d["role"])
    return f"Treat sample {subject} as {ROLE_WORDS.get(role, f'role {role!r}')}"


def _d_group(subject: str, d: Mapping[str, Any]) -> str:
    if d["group"] is None:
        return f"Take sample {subject} out of every group (it is not compared)"
    return f"Put sample {subject} in group “{d['group']}”"


def _d_unit(subject: str, d: Mapping[str, Any]) -> str:
    if d["biological_unit"] is None:
        return f"Sample {subject} is its own biological unit (its wells are technical replicates)"
    return (
        f"Sample {subject} belongs to biological unit “{d['biological_unit']}”: its wells are "
        "technical replicates of that unit and are never counted as separate n"
    )


def _d_target_role(subject: str, d: Mapping[str, Any]) -> str:
    role = str(d["role"])
    if role == "ref":
        return f"Use target {subject} as a reference gene (other genes are normalised to it)"
    if role == "toi":
        return f"Treat target {subject} as a gene of interest"
    if role == "ignore":
        return f"Leave target {subject} out of the study (none of its wells is used)"
    return f"Give target {subject} the role {role!r}"


def _d_symbol(subject: str, d: Mapping[str, Any]) -> str:
    return f"Target {subject} is the gene with the HGNC symbol {d['symbol']}"


def _d_comparison(subject: str, d: Mapping[str, Any]) -> str:
    a, b = d["group_a"], d["group_b"]
    text = f"Compare group “{a}” with group “{b}” (fold change = {a} relative to {b})"
    listed = [c for c in d.get("comparisons") or [] if isinstance(c, Mapping)]
    others = [c for c in listed if (c.get("group_a"), c.get("group_b")) != (a, b)]
    if others:
        pattern = d.get("pattern")
        if pattern == "vs_control" and d.get("control"):
            head = f"Compare each group with the control “{d['control']}”"
        elif pattern == "all_pairs":
            head = "Compare every pair of groups"
        else:
            head = "Compare these groups"
        pairs = "; ".join(
            f"{c.get('group_a')} vs {c.get('group_b')}"
            for c in [{"group_a": a, "group_b": b}, *others]
        )
        text = f"{head} ({len(others) + 1} comparisons: {pairs}; the first is {a} vs {b})"
        correction = d.get("correction") or "holm"
        text += (
            ", with Holm's correction across each gene's comparisons"
            if correction == "holm"
            else ", with no correction for several comparisons"
        )
    if d.get("pair_by"):
        text += f", paired by {d['pair_by']} (a paired test within each {d['pair_by']})"
    return text


def _d_pair(subject: str, d: Mapping[str, Any]) -> str:
    pair, by = d.get("pair"), d.get("by") or "pair"
    if not pair:
        return f"Sample {subject} is not paired with samples of the other groups"
    return (
        f"Sample {subject} belongs to {by} “{pair}”: it is paired with that {by}'s samples in "
        "the other groups"
    )


def _d_series(subject: str, d: Mapping[str, Any]) -> str:
    samples = dict(d["samples"])
    names = list(samples)
    quantities = sorted(float(q) for q in samples.values())
    span = f"{names[0]} … {names[-1]}" if len(names) > 1 else ", ".join(names)
    return (
        f"Samples {span} ({len(names)} in all, experiment {d.get('experiment_id', '?')}) form a "
        f"dilution series {subject}, quantities {quantities[0]:g} to {quantities[-1]:g}"
    )


def _d_rule(subject: str, d: Mapping[str, Any]) -> str:
    return f"Count a well as amplified by {rule_words(d['rule'])}"


def _d_well(subject: str, d: Mapping[str, Any]) -> str:
    amplified = d["amplified"]
    if not isinstance(amplified, bool):
        raise TypeError("amplified must be true or false")
    words = "amplified" if amplified else "not amplified (no usable curve)"
    return f"Count well {subject} as {words}"


def _d_exclude(subject: str, d: Mapping[str, Any]) -> str:
    excluded = d["excluded"]
    if not isinstance(excluded, bool):
        raise TypeError("excluded must be true or false")
    if excluded:
        return f"Leave well {subject} out of the analysis"
    return f"Put well {subject} back into the analysis"


def _d_trust(subject: str, d: Mapping[str, Any]) -> str:
    from qpilot.io.trust import LABELS

    option = d["option"]
    if option not in LABELS:
        raise TypeError("not an option of the Import Trust card")
    label = LABELS[option]
    return f"Import Trust: {label[0].lower()}{label[1:]}"


def _d_axis(subject: str, d: Mapping[str, Any]) -> str:
    from qpilot.qpcr.axes import get_axis

    axis = get_axis(subject)
    if not isinstance(d["options"], list | tuple) or not d["options"]:
        raise TypeError("options must be a non-empty list")
    options = [str(o) for o in d["options"]]
    labels = {o.id: _lower_first(o.label) for o in axis.catalogue}
    question = _lower_first(axis.title)
    if len(options) < 2:
        return f"Stop testing {question}; keep {labels.get(options[0], options[0])} only"
    others = "; ".join(labels.get(o, o) for o in options[1:])
    return (
        f"Also test {question}: {others} (besides {labels.get(options[0], options[0])}, "
        "the analysis in use)"
    )


def _lower_first(text: str) -> str:
    """``Each well's own`` -> ``each well's own``; a name like ``LinRegPCR's`` keeps its case."""
    first = text.split(" ", 1)[0]
    return text[:1].lower() + text[1:] if first[1:].islower() else text


def _d_project(subject: str, d: Mapping[str, Any]) -> str:
    genes = ", ".join(str(g) for g in d.get("genes") or []) or "the headline genes"
    template = d.get("template_id") or "two_groups_log2"
    text = f"Prism project from template {template}: one table each for {genes}"
    extras = [f"{k}: {d[k]}" for k in ("test", "graph") if isinstance(d.get(k), str)]
    return text + (f" ({'; '.join(extras)})" if extras else "")


def _d_exclusion(subject: str, d: Mapping[str, Any]) -> str:
    gene, sample = d.get("gene", "?"), d.get("sample") or "an unknown sample"
    if d.get("action") == "restore":
        return f"Keep sample {sample} in {gene} (restore it in the analysis)"
    return f"Exclude sample {sample} from {gene}, as it is excluded in Prism"


def _d_value_edit(subject: str, d: Mapping[str, Any]) -> str:
    gene, sample = d.get("gene", "?"), d.get("sample") or "an unknown sample"
    what = (
        "keep the edited value as a manual edit"
        if d.get("action") == "keep"
        else "restore qPilot's value"
    )
    return f"The value of sample {sample} for {gene} was changed in Prism: {what}"


def _d_confirm(subject: str, d: Mapping[str, Any]) -> str:
    covers = d.get("covers") or []
    label = STAGE_LABELS.get(subject, subject)
    if subject == "choices":
        return f"Confirm the {label} stage: the Decision Cards of this analysis"
    n = len(covers)
    return f"Confirm the {label} stage: it covers {n} accepted proposal{'s' * (n != 1)}"


_DESCRIBERS: dict[str, Callable[[str, Mapping[str, Any]], str]] = {
    "design.preset": _d_preset,
    "design.well_role": _d_role,
    "design.group": _d_group,
    "design.bio_unit": _d_unit,
    "design.target_role": _d_target_role,
    "design.gene_symbol": _d_symbol,
    "design.comparison": _d_comparison,
    "design.pair": _d_pair,
    "design.dilution_series": _d_series,
    "curve.call_rule": _d_rule,
    "curve.well_call": _d_well,
    "curve.exclude_well": _d_exclude,
    "curve.import_trust": _d_trust,
    "choice.axis": _d_axis,
    "prism.project": _d_project,
    "prism.exclusion_reason": _d_exclusion,
    "prism.value_edit": _d_value_edit,
    "stage.confirm": _d_confirm,
}


def describe(proposal: Proposal, payload: Mapping[str, Any] | None = None) -> str:
    """The proposal in plain words (plain text: the caller escapes it).

    ``payload`` describes another reading of the same proposal (an alternative or an edit).
    A payload that does not have its kind's shape (an agent's, say) is shown as JSON.
    """
    data = proposal.payload if payload is None else payload
    describer = _DESCRIBERS.get(proposal.kind)
    if describer is not None:
        try:
            return describer(proposal.subject, data)
        except (KeyError, TypeError, ValueError, IndexError, AttributeError):
            pass
    return f"{proposal.kind} for {proposal.subject}: {_short_json(dict(data))}"


def is_blind_kind(proposal: Proposal) -> bool:
    """A proposal of the design or curves stage (its consequence is never shown in full)."""
    if proposal.kind == "stage.confirm":
        return proposal.subject in BLIND_STAGES
    return proposal.kind.startswith(("design.", "curve."))


def ordered_pending(proposals: Sequence[Proposal]) -> list[Proposal]:
    """Pending proposals: what the engine contradicts first, then cannot-check, then the rest."""
    indexed = list(enumerate(proposals))
    indexed.sort(key=lambda item: (CHECK_ORDER.get(item[1].check.status, 3), item[0]))
    return [p for _, p in indexed]


# ---------- the six parts of a card ----------


def _part(number: int, label: str, body: str) -> str:
    return (
        f'<div class="qs-part qs-part-{number}"><span class="qs-label">{number}. {label}</span>'
        f"{body}</div>"
    )


def _value_text(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return str(value).lower()
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def kv_table(rows: Iterable[tuple[str, str]], css: str = "qs-kv") -> str:
    """A two-column table of already-escaped cells."""
    body = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows)
    return f'<table class="{css}">{body}</table>' if body else ""


def details_rows(details: Mapping[str, Any]) -> list[tuple[str, str]]:
    """A check's (or consequence's) details as escaped table rows; nested parts fold away."""
    rows = []
    for key, value in details.items():
        label = esc(str(key).replace("_", " "))
        if key == "checks" and isinstance(value, Mapping):
            for rule, sub in value.items():
                if isinstance(sub, Mapping):
                    word = CHECK_WORDS.get(str(sub.get("status")), str(sub.get("status")))
                    text = f"{esc(word)}: {esc(sub.get('note', ''))}"
                    if sub.get("details"):
                        text += _folded(sub["details"], "details")
                    rows.append((esc(rule), text))
            continue
        if isinstance(value, Mapping | list | tuple) and not _scalars(value):
            rows.append((label, _folded(value, f"{len(value)} item(s)")))
        elif isinstance(value, list | tuple):
            shown = ", ".join(_value_text(v) for v in value[:12])
            more = f" … ({len(value)} in all)" if len(value) > 12 else ""
            rows.append((label, esc(shown + more)))
        else:
            rows.append((label, esc(_value_text(value))))
    return rows


def _scalars(value: Any) -> bool:
    return isinstance(value, list | tuple) and all(
        not isinstance(v, Mapping | list | tuple) for v in value
    )


def _folded(value: Any, summary: str) -> str:
    text = json.dumps(value, indent=1, ensure_ascii=False, sort_keys=True, default=str)
    if len(text) > MAX_JSON_CHARS:
        text = text[:MAX_JSON_CHARS] + "\n… (cut here)"
    return (
        f'<details><summary>{esc(summary)}</summary><pre class="qs-pre">{esc(text)}</pre></details>'
    )


def _evidence_item(
    kind: str,
    ref: str,
    note: str,
    quarantine: Mapping[str, QuarantineEntry],
    sheet_cells: Mapping[str, str],
) -> str:
    note_html = f" <span class='qs-note'>({esc(note)})</span>" if note else ""
    if kind == "text" or TEXT_ID.match(ref):
        entry = quarantine.get(ref)
        title = f"text {esc(ref)}"
        body = _quoted(entry) if entry else "<p>This text is not in the session's quarantine.</p>"
    elif kind == "cell":
        text_id = sheet_cells.get(ref) or next(
            (tid for cell, tid in sheet_cells.items() if ref.endswith(cell)), None
        )
        title = f"cell {esc(ref)}"
        if text_id and text_id in quarantine:
            body = _quoted(quarantine[text_id])
        elif ref.startswith("sent_back/"):
            body = "<p>A cell of the table Prism sent back.</p>"
        else:
            body = "<p>This cell is not in the session's sample sheet.</p>"
    elif kind in ("well", "curve"):
        title = f"{'curve of well' if kind == 'curve' else 'well'} {esc(ref)}"
        body = (
            f"<p>To see this well's curve, choose <code>{esc(ref)}</code> under "
            "“Curve of a cited well” below the inbox.</p>"
        )
    else:
        title = f"{esc(kind)} {esc(ref)}"
        body = f"<p>{esc(kind)}: <code>{esc(ref)}</code></p>"
    return f"<li><details><summary>{title}{note_html}</summary>{body}</details></li>"


def _quoted(entry: QuarantineEntry) -> str:
    flag = ""
    if "instruction_like" in entry.flags:
        flag = (
            '<p class="qs-flag">This text reads like an instruction. It is shown as data and '
            "is never obeyed.</p>"
        )
    others = [f for f in entry.flags if f != "instruction_like"]
    extra = f" · flags: {esc(', '.join(others))}" if others else ""
    return (
        f'<blockquote class="qs-quote">{esc(entry.value)}</blockquote>'
        f'<p class="qs-origin">Original text from {esc(entry.origin)}{extra}</p>{flag}'
    )


def why_html(
    proposal: Proposal,
    quarantine: Mapping[str, QuarantineEntry],
    sheet_cells: Mapping[str, str],
) -> str:
    """Part 2: each source behind the proposal, expandable to the original it cites."""
    items = [
        _evidence_item(e.kind, e.ref, e.note, quarantine, sheet_cells)
        for e in proposal.evidence[:MAX_EVIDENCE_SHOWN]
    ]
    more = len(proposal.evidence) - MAX_EVIDENCE_SHOWN
    if more > 0:
        items.append(f"<li>… and {more} more source(s)</li>")
    if not items:
        return "<p>No source is cited.</p>"
    return f'<ul class="qs-evidence">{"".join(items)}</ul>'


def check_html(proposal: Proposal, *, details: bool = True) -> str:
    """Part 3: consistent / contradicted / cannot check, its rule ids and its details.

    ``details=False`` leaves the check's numbers out (a round-trip consequence that is out of
    date carries them too).
    """
    check = proposal.check
    status = check.status
    badge = f'<span class="qs-check {esc(status)}">{esc(CHECK_WORDS.get(status, status))}</span>'
    parts = [f"<p>{badge} {esc(CHECK_MEANING.get(status, ''))}</p>"]
    if check.note:
        parts.append(f'<p class="qs-check-note">{esc(check.note)}</p>')
    if check.rule_ids:
        rules = ", ".join(f"<code>{esc(r)}</code>" for r in check.rule_ids)
        parts.append(f"<p>Rules: {rules}</p>")
    if check.details and details:
        parts.append(kv_table(details_rows(check.details)))
    return "".join(parts)


def matters_of(proposal: Proposal, asked: bool | None = None) -> bool | None:
    """The blind consequence: the proposal's own ``{"matters": true}``, else what was asked."""
    if proposal.consequence == {"matters": True}:
        return True
    return asked


def consequence_html(
    proposal: Proposal,
    *,
    results_visible: bool,
    matters: bool | None = None,
    stale: str | None = None,
) -> str:
    """Part 4: during the blind stages only the boolean; the full consequence in the round trip.

    ``stale`` (from :meth:`qpilot.studio_service.Studio.stale_consequence`) says why a
    round-trip consequence no longer holds: then no number of it is shown, only that.
    """
    if is_blind_kind(proposal):
        matters = matters_of(proposal, matters)
        if matters is True:
            return f'<p class="qs-matters">{esc(MATTERS_TEXT)}</p>'
        if matters is False:
            return f"<p>{esc(NOT_MATTERS_TEXT)}</p>"
        hint = ""
        if proposal.alternatives and proposal.kind.startswith("design."):
            hint = " Press “Does this matter?” to ask the engine (it answers yes or no only)."
        return f"<p>{esc(BLIND_TEXT)}{esc(hint)}</p>"
    if proposal.consequence is None:
        return "<p>No consequence is computed for this kind of proposal.</p>"
    if not results_visible:
        return (
            "<p>Hidden: the design or the curves are not confirmed (again) yet, so no result is "
            "shown.</p>"
        )
    c = proposal.consequence
    if proposal.kind == "prism.exclusion_reason" and "fc_before" in c:
        if stale:
            return (
                f'<p class="qs-stale"><b>Out of date</b>: {esc(stale)}. Its numbers are not '
                "shown, and accepting it is refused until they are computed again.</p>"
            )
        return _exclusion_consequence(c)
    if proposal.kind == "prism.value_edit":
        rows = [
            ("value qPilot exported", esc(_value_text(c.get("exported")))),
            ("value Prism sent back", esc(_value_text(c.get("returned")))),
        ]
        return "<p>The value no longer matches the record.</p>" + kv_table(rows)
    return kv_table(details_rows(c))


def _fold(value: Any) -> str:
    return f"{value:.3f}×" if isinstance(value, int | float) else esc(value)


def _p(value: Any) -> str:
    return f"{value:.2g}" if isinstance(value, int | float) else esc(value)


def _changed(c: Mapping[str, Any]) -> int:
    try:
        return int(c.get("n_conclusions_changed", 0))
    except (TypeError, ValueError):
        return 0


def _exclusion_consequence(c: Mapping[str, Any]) -> str:
    """One exclusion's consequence and, with several, what all of them do together."""
    gene = esc(c.get("gene", ""))
    changed = _changed(c)
    n_genes = c.get("n_genes", "?")
    before = esc(conclusion_word(str(c.get("conclusion_before"))))
    after = esc(conclusion_word(str(c.get("conclusion_after"))))
    rows = [
        (f"fold change of {gene}", f"{_fold(c.get('fc_before'))} → {_fold(c.get('fc_after'))}"),
        ("p-value", f"{_p(c.get('p_before'))} → {_p(c.get('p_after'))}"),
        (f"conclusion for {gene}", f"{before} → {after}"),
        (
            "biological units (per group)",
            f"{esc(c.get('n_units_before'))} → {esc(c.get('n_units_after'))}",
        ),
        ("conclusions that change", f"{changed} of {esc(n_genes)}"),
    ]
    genes = c.get("changed_genes") or []
    if genes:
        rows.append(("genes whose conclusion changes", esc(", ".join(map(str, genes)))))
    head = (
        f"<p class='qs-matters'>Excluding it changes {changed} of {esc(n_genes)} conclusions.</p>"
        if changed
        else f"<p>Excluding it changes no conclusion ({changed} of {esc(n_genes)}).</p>"
    )
    together = c.get("with_all_pending")
    if isinstance(together, Mapping):
        head += _together(gene, n_genes, changed, together)
    return head + kv_table(rows)


def _together(gene: str, n_genes: Any, alone: int, w: Mapping[str, Any]) -> str:
    """What every exclusion found in the round trip does together (``with_all_pending``)."""
    raw_n, of = str(w.get("n_exclusions", "?")), str(n_genes)
    changed = _changed(w)
    if changed and not alone:
        words = (
            "On its own it changes no conclusion, but together with the other exclusions found "
            f"in this round trip ({raw_n} in all) {changed} of {of} conclusions change."
        )
    elif changed:
        words = (
            f"Together with the other exclusions found in this round trip ({raw_n} in all), "
            f"{changed} of {of} conclusions change."
        )
    else:
        words = (
            f"Together with the other exclusions found in this round trip ({raw_n} in all), no "
            f"conclusion changes (0 of {of})."
        )
    n = esc(raw_n)
    before = esc(conclusion_word(str(w.get("conclusion_before"))))
    after = esc(conclusion_word(str(w.get("conclusion_after"))))
    rows = [
        (
            f"fold change of {gene}, all {n} together",
            f"{_fold(w.get('fc_before'))} → {_fold(w.get('fc_after'))}",
        ),
        (f"conclusion for {gene}, all {n} together", f"{before} → {after}"),
        (f"conclusions that change, all {n} together", f"{changed} of {esc(n_genes)}"),
    ]
    genes = w.get("changed_genes") or []
    if genes:
        rows.append(
            (f"genes whose conclusion changes, all {n} together", esc(", ".join(map(str, genes))))
        )
    css = " class='qs-matters'" if changed else ""
    return f"<p{css}>{esc(words)}</p>" + kv_table(rows, "qs-kv qs-together")


def level_html(proposal: Proposal) -> str:
    """Part 5: the ordinal level (never a percentage) and the reasons named."""
    level = proposal.level
    badge = f'<span class="qp-badge level-{esc(slug(level))}">{esc(level)}</span>'
    reasons = "".join(f"<li>{esc(r)}</li>" for r in proposal.reasons)
    return f"<p>{badge}</p>" + (f'<ul class="qs-reasons">{reasons}</ul>' if reasons else "")


def actions_html(proposal: Proposal) -> str:
    """Part 6: what the buttons under the card do for this proposal."""
    if proposal.status != "proposed":
        who = "a person" if proposal.decided_by == "human" else "nobody"
        reason = f" Reason: {esc(proposal.reason)}" if proposal.reason else ""
        return f"<p>{esc(STATUS_WORDS.get(proposal.status, proposal.status))} by {who}.{reason}</p>"
    lines = [
        "Accept, Edit (change the fields, then accept), or Reject with a reason: the buttons below."
    ]
    if proposal.check.status == "contradicted":
        lines.append("The engine's check contradicts this proposal: accepting it needs a reason.")
    if proposal.kind == "prism.exclusion_reason":
        lines.append(
            "Accepting records the exclusion with your reason and re-runs the analysis without "
            "this value; the choices are then decided again."
        )
    lines.append("Nothing changes until you press one of them.")
    return "".join(f"<p>{esc(line)}</p>" for line in lines)


def maker_text(made_by: MadeBy) -> str:
    """Who made a proposal, in words (plain text)."""
    if made_by.kind == "rule":
        return "Made by a fixed rule in qPilot (no model)."
    if made_by.kind == "agent":
        return f"Proposed by an agent over MCP ({made_by.agent or 'unnamed'})."
    if made_by.kind == "person":
        return "Set by a person on the Design page (and accepted in the same act)."
    if made_by.provider == CURVE_JUDGE:
        return (
            f"Made by the Curve Judge, a local curve classifier (model {made_by.model}); it reads "
            "only the curve's fluorescence values."
        )
    text = f"Made by the model {made_by.provider or '?'} · {made_by.model or '?'}"
    if made_by.prompt_sha256:
        text += f" · prompt sha256 {made_by.prompt_sha256[:12]}"
    return text + "."


def payload_sha256(payload: Mapping[str, Any]) -> str:
    """sha256 of a payload as the model layer hashes it (``payload_log.canonical``)."""
    return hashlib.sha256(canonical(dict(payload)).encode("utf-8")).hexdigest()


def interpreter_payload(payload: Mapping[str, Any]) -> bool:
    """True for a payload sent with the Design Interpreter's system prompt (it holds no result).

    The Design Interpreter is the only model call of the blind stages; every other call (the
    Prism caption, an explanation) may be sent fold changes, intervals and p-values.
    """
    return payload.get("system") == SYSTEM_INTERPRET


def _seen_hidden(payload: Mapping[str, Any], results_visible: bool) -> bool:
    return not results_visible and not interpreter_payload(payload)


def seen_html(last_payload: Mapping[str, Any] | None, *, results_visible: bool = False) -> str:
    """The intake panel "What the model saw": the last model call's payload, blind-gated.

    While the blind stages are open only the Design Interpreter's payload is shown; any other
    is withheld (:data:`SEEN_HIDDEN_TEXT`), so no result reaches the page through it.
    """
    if last_payload is None:
        body = "<p>No model call yet in this qPilot process.</p>"
    elif _seen_hidden(last_payload, results_visible):
        body = f"<p>{esc(SEEN_HIDDEN_TEXT)}</p>"
    else:
        text = json.dumps(last_payload, indent=2, ensure_ascii=False, default=str)
        body = f'<pre class="qs-pre">{esc(text)}</pre>'
    return f"<h4>What the model saw (the last call)</h4>{body}"


def model_saw_html(
    made_by: MadeBy, last_payload: Mapping[str, Any] | None, *, results_visible: bool = False
) -> str:
    """The card footer's "What the model saw" toggle (language-model proposals only).

    Blind-gated like :func:`seen_html`: while the results are hidden, only the Design
    Interpreter's payload is shown.
    """
    if made_by.kind != "model" or made_by.provider == CURVE_JUDGE:
        return ""
    if last_payload is None:
        body = "<p>No model call in this qPilot process yet (payloads are kept in memory only).</p>"
    elif _seen_hidden(last_payload, results_visible):
        body = f"<p>{esc(SEEN_HIDDEN_TEXT)}</p>"
    else:
        same = made_by.prompt_sha256 and made_by.prompt_sha256 == payload_sha256(last_payload)
        label = (
            "The payload behind this card."
            if same
            else "The last model call in this qPilot process; it may not be the one behind "
            "this card."
        )
        text = json.dumps(last_payload, indent=2, ensure_ascii=False, default=str)[:MAX_JSON_CHARS]
        body = f'<p>{esc(label)}</p><pre class="qs-pre">{esc(text)}</pre>'
    return f'<details class="qs-saw"><summary>What the model saw</summary>{body}</details>'


def card_html(
    proposal: Proposal,
    *,
    quarantine: Mapping[str, QuarantineEntry] | None = None,
    sheet_cells: Mapping[str, str] | None = None,
    results_visible: bool = False,
    matters: bool | None = None,
    last_payload: Mapping[str, Any] | None = None,
    stale: str | None = None,
) -> str:
    """One proposal card with the six fixed parts and its footer (escaped HTML).

    ``stale`` says why a round-trip consequence no longer holds; the card then shows none of
    its numbers (neither in the consequence nor in the check's details).
    """
    p = proposal
    what = [f'<p class="qs-what">{esc(describe(p))}</p>']
    question = p.payload.get("question")
    if p.kind.startswith("prism.") and isinstance(question, str):
        what.append(f'<p class="qs-question">{esc(question)}</p>')
    if p.edits:
        what.append(f"<p>As edited by a person: {esc(describe(p, p.effective_payload()))}</p>")
    if p.alternatives:
        alts = "; ".join(esc(describe(p, alt)) for alt in p.alternatives[:6])
        what.append(f'<p class="qs-alt">Other reading(s): {alts}</p>')
    what.append(
        f'<p class="qs-meta"><code>{esc(p.kind)}</code> · '
        f"{esc(STATUS_WORDS.get(p.status, p.status))} · <span class='qs-id'>{esc(p.id)}</span></p>"
    )
    saw = model_saw_html(p.made_by, last_payload, results_visible=results_visible)
    footer = f'<div class="qs-footer">{esc(maker_text(p.made_by))}{saw}</div>'
    return (
        f'<div class="qs-card check-{esc(p.check.status)}" data-proposal="{esc(p.id)}">'
        + _part(1, "Proposal", "".join(what))
        + _part(2, "Why", why_html(p, quarantine or {}, sheet_cells or {}))
        + _part(3, "Engine check", check_html(p, details=not stale))
        + _part(
            4,
            "Consequence",
            consequence_html(p, results_visible=results_visible, matters=matters, stale=stale),
        )
        + _part(5, "Level", level_html(p))
        + _part(6, "Actions", actions_html(p))
        + footer
        + "</div>"
    )


# ---------- lists, the stage strip and the inbox header ----------


def proposal_list_html(proposals: Sequence[Proposal], title: str) -> str:
    """A numbered list of proposals with their checks (what a bulk action would cover)."""
    items = "".join(
        f"<li>{esc(describe(p))} "
        f'<span class="qs-check {esc(p.check.status)}">'
        f"{esc(CHECK_WORDS.get(p.check.status, p.check.status))}</span> "
        f'<span class="qs-id">{esc(p.id)}</span>'
        + ("" if p.status == "proposed" else f" <b>(already {esc(p.status)}; will be refused)</b>")
        + "</li>"
        for p in proposals
    )
    return f'<div class="qs-list"><p>{esc(title)}</p><ol>{items}</ol></div>'


def decided_html(proposals: Sequence[Proposal]) -> str:
    """What was already decided in the stage (folded): status, proposal and reason."""
    if not proposals:
        return ""
    items = []
    for p in proposals:
        reason = f" — reason: {esc(p.reason)}" if p.reason else ""
        items.append(
            f"<li><b>{esc(STATUS_WORDS.get(p.status, p.status))}</b>: "
            f"{esc(describe(p))}{reason}</li>"
        )
    return (
        f'<details class="qs-decided"><summary>Decided in this stage ({len(proposals)})</summary>'
        f'<ol class="qs-list">{"".join(items)}</ol></details>'
    )


def _as_dict(stage: Any) -> dict[str, Any]:
    return stage.as_dict() if hasattr(stage, "as_dict") else dict(stage)


def current_stage(stages: Sequence[Any]) -> str:
    """The first open stage not yet confirmed (the round trip once everything else is)."""
    for stage in map(_as_dict, stages):
        if stage["open"] and not stage["confirmed"]:
            return str(stage["stage"])
    return STAGES[-1]


def stage_strip_html(stages: Sequence[Any], shown: str | None = None) -> str:
    """Design (blind) → Curves (blind) → Choices → Prism draft → Round trip, with their state."""
    items = []
    for stage in map(_as_dict, stages):
        name = str(stage["stage"])
        if stage["confirmed"]:
            css, mark = "confirmed", "✔"
            state = "sent to Prism" if name == "prism" else "confirmed"
        elif stage["open"]:
            css, mark = "open", "●"
            state = "open"
        else:
            css, mark = "closed", "○"
            state = "not open yet"
        if stage["pending"]:
            state += f" · {int(stage['pending'])} waiting"
        if name == shown:
            css += " current"
        blockers = "".join(f"<li>{esc(b)}</li>" for b in stage.get("blockers") or [])
        blocker_html = f'<ul class="qs-blockers">{blockers}</ul>' if blockers else ""
        items.append(
            f'<li class="qs-stage {css}"><span class="qs-mark">{mark}</span> '
            f"<b>{esc(STAGE_LABELS.get(name, name))}</b>"
            f'<span class="qs-state">{esc(state)}</span>{blocker_html}</li>'
        )
    return f'<ol class="qs-strip">{"".join(items)}</ol>'


def confirm_html(confirm: Proposal, covered: Sequence[Proposal]) -> str:
    """What a pending ``stage.confirm`` covers, shown before the person's confirm click."""
    payload = confirm.payload
    stage = confirm.subject
    lines = [
        f"<p><b>{esc(describe(confirm))}.</b> Confirming records that you checked what is "
        "listed below. Nothing is confirmed until you press the button.</p>"
    ]
    if payload.get("design_hash"):
        lines.append(f"<p>Design hash <code>{esc(str(payload['design_hash'])[:16])}…</code></p>")
    if stage == "choices":
        lines.append(
            f"<p>Analysis <code>{esc(payload.get('study_id', ''))}</code>, decision chain at "
            f"<code>{esc(str(payload.get('chain_head', ''))[:12])}</code>.</p>"
        )
    if covered:
        lines.append(
            proposal_list_html(covered, f"It covers these {len(covered)} accepted proposals:")
        )
    elif stage != "choices":
        lines.append("<p>It covers no accepted proposal of this stage.</p>")
    if stage in BLIND_STAGES:
        lines.append(f"<p>{esc(BLIND_TEXT)}</p>")
    return f'<div class="qs-confirm">{"".join(lines)}</div>'


def model_line_html(status: Mapping[str, Any]) -> str:
    """The model status line: which model, whether it answers, and whether anything leaves.

    A configured model that does not answer is shown as exactly that, with the reason: each
    Propose still tries it (and waits for it) before the rules answer alone, so "no model" would
    be wrong. A misconfigured one says what is wrong; while the first answer is not known yet,
    the line says it is checking.
    """
    provider = str(status.get("provider", "none"))
    model = status.get("model")
    reason = str(status.get("reason") or "")
    configured = bool(status.get("configured", status.get("available", False)))
    if provider == "mock" or not configured:
        if status.get("misconfigured") and reason:
            return (
                '<p class="qs-model"><span class="qp-dot off"></span>Model: none — the configured '
                f"model cannot be used: {esc(reason)}. The rules propose alone; no model is "
                "called.</p>"
            )
        return (
            '<p class="qs-model"><span class="qp-dot"></span>Model: none — the rules propose '
            "alone; no model is called.</p>"
        )
    who = esc(provider + (f" · {model}" if model else ""))
    if status.get("local", True):
        where = "local — sample names go only to this local endpoint, as quoted data"
    else:
        where = (
            "<b>REMOTE — names pseudonymised</b>: sample names are replaced by pseudonyms before "
            "anything leaves this computer"
        )
    if status.get("available", False):
        dot = "on" if status.get("local", True) else "off"
        return f'<p class="qs-model">Model: {who} · <span class="qp-dot {dot}"></span>{where}</p>'
    if status.get("answers") is None:
        state = '<span class="qp-dot"></span>checking whether it answers'
    else:
        state = (
            '<span class="qp-dot off"></span><b>configured but not answering: '
            f"{esc(reason or 'no reason given')}</b> (each Propose still tries it, then the rules "
            "propose alone)"
        )
    return f'<p class="qs-model">Model: {who} · {state} · {where}</p>'


def file_html(name: str, summary: InspectSummary, sheet: bool) -> str:
    """What was opened: counts as the file declares them (no analysis, no result)."""
    types = ", ".join(f"{n} {esc(t)}" for t, n in sorted(summary.declared_types.items()))
    experiments = ", ".join(f"{esc(e)} ({n} plates)" for e, n in summary.experiments.items())
    sheet_line = f" · sample sheet: {len(summary.sheet)} cells" if sheet else ""
    return (
        f"<p><b>{esc(name)}</b>: {summary.n_samples} samples ({types}); "
        f"{len(summary.targets)} targets; experiments {experiments}{sheet_line}. "
        "Opened only: nothing is analysed and nothing is proposed until you press a button.</p>"
    )


def notice_html(text: str) -> str:
    """A notice line (escaped)."""
    return f'<p class="qp-notice">{esc(text)}</p>' if text else ""


# ---------- results-side views (only rendered once the results are visible) ----------

ROUTES = (
    (
        "linear_welch",
        "The usual Excel→Prism route (2^-ΔΔCq per sample, Welch's t test on the linear scale) "
        "changes",
    ),
    (
        "linear_student",
        "The same route with Student's t test (Prism's default before version 10) changes",
    ),
    ("ddcq", "ΔΔCq with the efficiency assumed to be 2.0 (Welch on log2) changes"),
)


def routes_html(facts: Mapping[str, Fact]) -> str:
    """The route comparison, as facts: how many conclusions the usual routes would change."""
    if "f_n_genes" not in facts:
        return ""
    lines = []
    for route, words in ROUTES:
        fid = f"f_n_differ_route_{route}"
        if fid not in facts:
            continue
        line = to_html(
            f"{words} {{{{{fid}}}}} of {{{{f_n_genes}}}} conclusions on this study.", facts
        )
        genes = f"f_genes_differ_route_{route}"
        if genes in facts and facts[fid].value:
            line += (
                f" <details><summary>which</summary>{to_html('{{' + genes + '}}', facts)}</details>"
            )
        lines.append(f"<li>{line}</li>")
    if not lines:
        return ""
    return (
        '<div class="qs-routes"><h4>Why the bridge matters</h4><ul>'
        + "".join(lines)
        + "</ul><p class='qs-hint'>Computed by the engine on this study's own plates "
        "(methods/routes.md); the engine's analysis is what is sent to Prism.</p></div>"
    )


def prism_preview_html(preview: Mapping[str, Any]) -> str:
    """What Send to Prism would write: test, graph, tables, choices, caption (escaped)."""
    bundle = preview.get("bundle") or {}
    template = preview.get("template") or {}
    info = bundle.get("info") or {}
    available = template.get("available")
    template_line = esc(template.get("file", bundle.get("template_id", "")))
    if available is False:
        template_line += (
            " — not made in Prism yet: the bundle is still written, and its README says how to "
            "build the template"
        )
    rows = [
        ("test", esc(bundle.get("test", template.get("test", "")))),
        ("graph", esc(template.get("graph", info.get("graph", "")))),
        ("layout", esc(template.get("layout", info.get("layout", "")))),
        ("template", template_line),
        ("scale", esc(info.get("scale", ""))),
        ("groups", esc(info.get("groups", ""))),
        ("reference genes", esc(info.get("refs", ""))),
        ("technical replicates", esc(info.get("technical_replicates", ""))),
    ]
    tables = "".join(
        f"<tr><td>{esc(t.get('gene'))}</td><td>{esc(', '.join(map(str, t.get('columns', []))))}"
        f"</td><td>{esc(t.get('n_rows'))}</td></tr>"
        for t in bundle.get("tables", [])
    )
    choices = "".join(
        f"<tr><td>{esc(c.get('card_id'))}</td><td>{esc(c.get('option'))}</td>"
        f"<td>{esc(_who(c))}</td></tr>"
        for c in preview.get("choices", [])
    )
    caption = info.get("caption")
    would = ", ".join(esc(f) for f in preview.get("would_write", []))
    return (
        '<div class="qs-preview"><h4>Prism preview</h4>'
        "<p>Nothing is written until you press Send to Prism.</p>"
        + kv_table([(esc(k), v) for k, v in rows if v])
        + (
            '<table class="qp-options"><thead><tr><th>Table</th><th>Columns</th><th>Rows</th>'
            f"</tr></thead><tbody>{tables}</tbody></table>"
            if tables
            else ""
        )
        + (
            '<table class="qp-options"><thead><tr><th>Choice</th><th>Option exported</th>'
            f"<th>Decided by</th></tr></thead><tbody>{choices}</tbody></table>"
            if choices
            else ""
        )
        + (f'<p class="qs-caption"><b>Caption:</b> {esc(caption)}</p>' if caption else "")
        + (f"<p>Would write: {would}</p>" if would else "")
        + f'<p class="qs-hint">{esc(preview.get("not_affiliated", ""))}</p></div>'
    )


def _who(choice: Mapping[str, Any]) -> str:
    actor = choice.get("actor")
    if actor == "human":
        return "a person"
    if actor == "system":
        return "the system (it changes no conclusion)"
    if actor is None:
        return "not decided yet: exported at the recommended option"
    return str(actor)


def preview_tables(preview: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Each previewed table as ``{"columns": [...], "rows": [[...]]}`` (parsed with ``csv``)."""
    out = {}
    for gene, table in (preview.get("tables") or {}).items():
        lines = list(table.get("head") or [])
        parsed = list(csv.reader(io.StringIO("\n".join(lines))))
        columns = parsed[0] if parsed else list(table.get("columns", []))
        out[str(gene)] = {"columns": columns, "rows": parsed[1:], "n_rows": table.get("n_rows")}
    return out


def table_html(gene: str, table: Mapping[str, Any]) -> str:
    """A previewed table as HTML (the fallback when no graph can be drawn)."""
    head = "".join(f"<th>{esc(c)}</th>" for c in table.get("columns", []))
    body = "".join(
        "<tr>" + "".join(f"<td>{esc(cell)}</td>" for cell in row) + "</tr>"
        for row in table.get("rows", [])
    )
    shown = len(table.get("rows", []))
    total = table.get("n_rows")
    note = f"<p class='qs-hint'>First {shown} of {esc(total)} rows.</p>" if total else ""
    return (
        f"<h4>{esc(gene)}</h4><div class='qs-scroll'><table class='qp-options'>"
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>{note}"
    )


def group_points(
    columns: Sequence[str], rows: Sequence[Sequence[str]]
) -> dict[str, list[tuple[str, float]]]:
    """A column-layout table as ``{group: [(unit, log2 value), ...]}`` (empty cells skipped)."""
    groups: dict[str, list[tuple[str, float]]] = {str(c): [] for c in columns[1:]}
    for row in rows:
        if not row:
            continue
        unit = row[0]
        for column, cell in zip(columns[1:], row[1:], strict=False):
            try:
                value = float(cell)
            except ValueError:
                continue
            if math.isfinite(value):
                groups[str(column)].append((unit, value))
    return groups


def mean_ci(values: Sequence[float]) -> tuple[float, float, float] | None:
    """Mean and its 95 % confidence interval (Student's t); None for fewer than two values."""
    from scipy import stats

    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))
    half = float(stats.t.ppf(0.975, n - 1)) * sd / math.sqrt(n)
    return mean, mean - half, mean + half


def prism_figure(gene: str, groups: Mapping[str, Sequence[tuple[str, float]]]) -> go.Figure:
    """Every unit per group with mean ± 95 % CI: an approximation of the template's graph."""
    figure = go.Figure()
    for index, (group, points) in enumerate(groups.items()):
        color = GROUP_COLORS[index % len(GROUP_COLORS)]
        xs = [index + (((i * 0.618034) % 1.0) - 0.5) * 0.5 for i in range(len(points))]
        figure.add_trace(
            go.Scatter(
                x=xs,
                y=[v for _, v in points],
                mode="markers",
                name=esc(group),
                marker={"color": color, "size": 7, "opacity": 0.6},
                text=[esc(unit) for unit, _ in points],
                hovertemplate="%{text}: %{y:.3f}<extra>" + esc(group) + "</extra>",
            )
        )
        summary = mean_ci([v for _, v in points])
        if summary is not None:
            mean, lo, hi = summary
            figure.add_trace(
                go.Scatter(
                    x=[index],
                    y=[mean],
                    mode="markers",
                    name=f"{esc(group)} mean ± 95 % CI",
                    marker={
                        "color": INK,
                        "size": 14,
                        "symbol": "line-ew-open",
                        "line": {"width": 3},
                    },
                    error_y={
                        "type": "data",
                        "symmetric": False,
                        "array": [hi - mean],
                        "arrayminus": [mean - lo],
                        "color": INK,
                        "thickness": 2,
                        "width": 10,
                    },
                    hovertemplate=f"mean %{{y:.3f}} (95 % CI {lo:.3f} to {hi:.3f})<extra></extra>",
                    showlegend=False,
                )
            )
    names = [esc(g) for g in groups]
    figure.update_layout(
        title=f"{esc(gene)}: log2 relative quantity per biological unit",
        height=360,
        margin={"l": 50, "r": 10, "t": 50, "b": 40},
        yaxis_title="log2 RQ",
        xaxis={"tickmode": "array", "tickvals": list(range(len(names))), "ticktext": names},
        legend={"orientation": "h", "y": -0.15},
    )
    return figure


def curve_points(curve: Mapping[str, Sequence[Any]]) -> list[tuple[int, float]]:
    """A well's curve as ``(cycle, value)`` pairs, cycles without a finite value dropped."""
    out = []
    for cycle, value in zip(curve.get("cycle", []), curve.get("fluorescence", []), strict=False):
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            out.append((int(cycle), number))
    return out


def curve_figure(well_key: str, points: Sequence[tuple[int, float]]) -> go.Figure:
    """One well's curve, as the Curve Judge reads it (each curve divided by its minimum)."""
    figure = go.Figure(
        go.Scatter(
            x=[c for c, _ in points],
            y=[v for _, v in points],
            mode="lines+markers",
            line={"color": GROUP_COLORS[0], "width": 2},
            marker={"size": 5},
            hovertemplate="cycle %{x}: %{y:.3f}<extra></extra>",
        )
    )
    figure.update_layout(
        title=f"Well {esc(well_key)}",
        height=300,
        margin={"l": 50, "r": 10, "t": 50, "b": 40},
        xaxis_title="cycle",
        yaxis_title="fluorescence ÷ the curve's minimum",
    )
    return figure


def headline(result: Any) -> list[str]:
    """The genes shown first (the design's headline genes, else the first four)."""
    from qpilot.qpcr.study import HEADLINE_GENES

    return [g for g in HEADLINE_GENES if g in result.contrasts] or list(result.contrasts)[:4]


__all__ = [
    "BLIND_TEXT",
    "MATTERS_TEXT",
    "STAGE_LABELS",
    "card_html",
    "confirm_html",
    "consequence_html",
    "current_stage",
    "curve_figure",
    "curve_points",
    "describe",
    "file_html",
    "group_points",
    "is_blind_kind",
    "mean_ci",
    "model_line_html",
    "ordered_pending",
    "preview_tables",
    "prism_figure",
    "prism_preview_html",
    "proposal_list_html",
    "routes_html",
    "stage_strip_html",
    "table_html",
]
