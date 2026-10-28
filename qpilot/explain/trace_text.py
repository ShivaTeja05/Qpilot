"""Trace in words: the "Where to look" panel, with every number a fact token.

The panel is built from a trace's facts only (``f_trace_<root>_...``, see
:mod:`qpilot.qpcr.trace`), so the same text comes from a fresh :class:`TraceResult` or from facts
stored elsewhere, and it passes :func:`qpilot.core.validator.validate`: sample ids, plates and
wells are string facts (they carry digits), gene names are allowed names. Wording follows the
measured results, not a script: the panel says how many samples would each change the call on
their own, so it can never claim that no single sample decides a call when one does. It names
what the data look like, which bench step that is consistent with and what to check; it never
names a cause.

* :func:`trace_v1` has the template signature ``(facts, card, gene) -> token text``; without a
  gene, or without that gene's trace facts, it returns a sentence with no digits.
* :func:`trace_set_aside_v1` is the rationale of a ``trace_set_aside`` card (no numbers).
* :func:`render_trace` renders any trace result (gene, sample or well) three ways
  (:class:`qpilot.explain.templates.RenderedText`).

``TEMPLATES`` here are for the integrator to register; nothing registers them yet.
Deterministic; no model call.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from qpilot.core.facts import slug
from qpilot.core.validator import TOKEN, render_tokens, validate
from qpilot.explain.templates import RenderedText, TemplateError, to_html
from qpilot.qpcr.trace import CHECKS, TRACE_THRESHOLDS, TraceResult
from qpilot.schemas import DecisionCard, Fact

Facts = Mapping[str, Fact]

NOT_RUN = "Trace has not been run for this result."
NOTHING = "Trace has nothing to show for this result."
CARD_TEXT = (
    "Trace found this place unusual. Keep it, read the well from the sample's other reference "
    "wells, or set it aside; the groups stay as they are. An option that changes a conclusion "
    "is a decision for a person, and it is logged."
)
CONSEQUENCE_WORDS = {
    "changes_call": "changes the call",
    "beyond_ci": "moves the fold change by more than its confidence interval",
    "changes_nothing": "changes nothing here",
}
OPTION_WORDS = {
    "read_from_other_refs": "Read from the sample's other reference wells",
    "set_aside_value": "With this value set aside",
    "set_aside": "With the sample set aside",
}
CHOICE_WORDS = {
    "refs": "the reference genes",
    "cut": "the group cut-off",
    "undetermined": "how empty wells are handled",
    "amp_call": "which curves count as amplified",
}
NOTHING_WORDS = {
    "S1": "reference wells against each other",
    "S2": "whole-sample lateness",
    "S4": "whole-sample efficiency",
    "S5": "curve notes",
    "S7": "samples left out",
}
TARGET_LIMIT_WORDS = {  # a target well's trace: why its value cannot be told apart from biology
    "single_target_well": "It feeds one value; Trace cannot tell from biology without "
    "replicates whether this well is off.",
    "S9": "It feeds one value; its replicate wells are not compared yet, so Trace cannot tell "
    "from biology whether this well is off.",
    None: "It feeds one value; Trace cannot tell from biology without replicates whether this "
    "well is off.",
}
CANNOT_WORDS = (
    "RNA integrity",
    "RT replicates",
    "no-RT controls",
    "batch annotations",
    "a single target well that is off (cannot tell from biology without replicates)",
)


def _t(fid: str) -> str:
    return "{{" + fid + "}}"


class _Panel:
    """Reads one trace's facts by field name and writes token text."""

    def __init__(self, facts: Facts, root_slug: str) -> None:
        self.facts = facts
        self.p = f"f_trace_{root_slug}"

    def id(self, field: str) -> str:
        return f"{self.p}_{field}"

    def has(self, field: str) -> bool:
        return self.id(field) in self.facts

    def tok(self, field: str) -> str:
        return _t(self.id(field))

    def value(self, field: str, default=None):
        fact = self.facts.get(self.id(field))
        return default if fact is None else fact.value

    def ranks(self) -> list[int]:
        out, n = [], 1
        while self.has(f"{n}_sample"):
            out.append(n)
            n += 1
        return out


def _call_line(panel: _Panel, gene: str) -> str:
    call = panel.value("call")
    direction = panel.value("direction", "lower")
    group = f" in {panel.tok('group_hi')}" if panel.has("group_hi") else ""
    head = "No call" if call == "none" else f"Called {call}"
    text = f"{gene}. {head}: {panel.tok('fold')}-fold {direction}{group} (p = {panel.tok('p')})."
    if panel.has("rule_fold") and panel.has("distance_fold"):
        side = "short of" if float(panel.value("distance_to_line_log2", 0.0)) < 0 else "past"
        text += (
            f" The rule needs at least {panel.tok('rule_fold')}-fold and p below "
            f"{panel.tok('rule_alpha')}; this fold change is {panel.tok('distance_fold')} "
            f"{side} that line."
        )
    return text


def _single_sample_line(panel: _Panel) -> str:
    largest = ""
    if panel.has("max_single_effect_fold") and panel.has("max_single_effect_sample"):
        largest = (
            f" (largest effect of one sample: {panel.tok('max_single_effect_fold')}, sample "
            f"{panel.tok('max_single_effect_sample')})"
        )
    if int(panel.value("n_loo_flips", 0)) > 0:
        return (
            f"Setting aside one sample alone changes this call for {panel.tok('n_loo_flips')} "
            f"different samples{largest}."
        )
    return f"No single sample changes this call when set aside{largest}."


def _place_lines(panel: _Panel, n: int, gene: str | None) -> list[str]:
    q = f"{n}_"
    head = f"{panel.tok(q + 'rank')}. Sample {panel.tok(q + 'sample')}"
    if panel.has(q + "well"):
        head += f" · plate {panel.tok(q + 'plate')} · well {panel.tok(q + 'well')}"
    cls = str(panel.value(q + "consequence", "changes_nothing"))
    lines = [f"{head}: {CONSEQUENCE_WORDS.get(cls, cls)}."]
    checks = str(panel.value(q + "checks", "")).split()
    role = panel.value(q + "role")
    if role == "reference_well" and panel.has(q + "cq"):
        text = f"Its {panel.tok(q + 'target')} well read Cq {panel.tok(q + 'cq')}"
        if panel.has(q + "std_cq") and panel.has(q + "std_copies"):
            text += (
                f"; this plate's {panel.tok(q + 'std_copies')}-copy standard reads "
                f"{panel.tok(q + 'std_cq')}"
            )
        lines.append(text + ".")
        normal = panel.value(q + "other_refs_max_z")
        if normal is not None and float(normal) <= TRACE_THRESHOLDS["z"]:
            lines.append(
                f"The sample's other {panel.tok(q + 'n_other_refs')} reference wells agree with "
                "each other."
            )
        if panel.has(q + "fold_off"):
            way = "high" if panel.value(q + "values_read") == "high" else "low"
            lines.append(
                f"So all {panel.tok(q + 'feeds')} values of sample {panel.tok(q + 'sample')} "
                f"read {panel.tok(q + 'fold_off')} too {way}."
            )
    elif role == "sample":
        if "S2" in checks:
            lines.append(
                f"Every gene of this sample comes up late: a median of {panel.tok(q + 'cq_shift')} "
                f"cycles after its plates (robust z {panel.tok(q + 'z')})."
            )
        if "S4" in checks:
            lines.append(
                f"Its amplification efficiency shifts across assays by "
                f"{panel.tok(q + 'eff_shift')}."
            )
    elif role == "target_well" and panel.has(q + "cq"):
        lines.append(f"Its {panel.tok(q + 'target')} well read Cq {panel.tok(q + 'cq')}.")
    if "S6" in checks and panel.has(q + "ntc_well"):
        lines.append(
            f"It comes up within the window of this plate's NTC well {panel.tok(q + 'ntc_well')} "
            f"(Cq {panel.tok(q + 'ntc_cq')})."
        )
    if "S5" in checks:
        lines.append("LinRegPCR noted a curve-quality issue on this well.")
    for check in checks:
        if check in CHECKS:
            info = CHECKS[check]
            lines.append(
                f"Consistent with {info['consistent_with']}; what to check: "
                f"{info['what_to_check']}."
            )
    via = str(panel.value(q + "via", ""))
    if cls != "changes_nothing" and via in OPTION_WORDS:
        lines.append(_option_sentence(panel, q, via, gene))
    return lines


def _option_sentence(panel: _Panel, q: str, via: str, gene: str | None) -> str:
    words = OPTION_WORDS[via]
    if gene is not None:
        new = panel.value(q + "new_call")
        if new is None:
            return f"{words}: {gene} moves by {panel.tok(q + 'effect_fold')}."
        if new == panel.value("call"):
            return f"{words}: {gene} keeps its call but moves by {panel.tok(q + 'effect_fold')}."
        if new == "none":
            return f"{words}: {gene} loses its call."
        return f"{words}: {gene} becomes {panel.tok(q + 'new_call')}."
    return f"{words}: {_calls_changed(panel, q + 'n_changed', q + 'changed_calls')}."


def _calls_changed(panel: _Panel, n_field: str, list_field: str) -> str:
    """Words for the calls an option changes: one gene, several genes, or none."""
    n = int(panel.value(n_field, 0) or 0)
    if n <= 0 or not panel.has(list_field):
        return "no call changes"
    if n == 1:
        return f"the call of {panel.tok(list_field)} changes"
    return f"{panel.tok(n_field)} calls change ({panel.tok(list_field)})"


def _more_line(panel: _Panel) -> str:
    if int(panel.value("n_more", 0)) <= 0:
        return ""
    if int(panel.value("n_more", 0)) == int(panel.value("n_more_changes_nothing", -1)):
        return f"+ {panel.tok('n_more')} more unusual places that change nothing here."
    return f"+ {panel.tok('n_more')} more unusual places."


def _influential_line(panel: _Panel, what: str) -> str:
    parts, n = [], 1
    while panel.has(f"infl_{n}_{what}"):
        part = f"{what} {panel.tok(f'infl_{n}_{what}')} ({panel.tok(f'infl_{n}_fold')}"
        if panel.value(f"infl_{n}_consequence") == "changes_call":
            part += ", setting it aside changes the call"
        parts.append(part + ")")
        n += 1
    if not parts:
        return ""
    tail = "the wells behind these values read as expected"
    return "Influential, nothing unusual: " + ", ".join(parts) + f"; {tail}."


def _nothing_line(panel: _Panel, *, count_plates: bool = False) -> str:
    found = str(panel.value("nothing_found", "")).split()
    checks = ("S1", "S2", "S4", "S5") if count_plates else ("S1", "S2", "S4", "S5", "S7")
    items = [NOTHING_WORDS[c] for c in checks if c in found]
    if count_plates and int(panel.value("n_clean_ntc_plates", 0)) > 0:
        items.insert(0, f"NTCs on {panel.tok('n_clean_ntc_plates')} plates")
    elif not count_plates and panel.has("clean_ntc_plates"):
        items.insert(0, f"NTCs on plates {panel.tok('clean_ntc_plates')}")
    return "Checked, nothing found: " + " · ".join(items) + "." if items else ""


def _answer_line(panel: _Panel) -> str:
    answer = panel.value("answer")
    if answer == "place_to_look":
        return "There is a place to look."
    if answer == "choice_to_look_at":
        dims = [CHOICE_WORDS.get(d, d) for d in str(panel.value("choice_flips", "")).split()]
        which = " or ".join(dims) if dims else "an analysis choice"
        return (
            "The wells show nothing that changes this result; changing "
            f"{which} alone can change it. See that decision card."
        )
    if answer == "absent":
        return "This sample is in no comparison."
    return "Nothing to look at: the result is what the wells say."


def _cannot_line() -> str:
    return "The data cannot show: " + " · ".join(CANNOT_WORDS) + "."


def _gene_panel(facts: Facts, gene: str) -> str:
    panel = _Panel(facts, slug(gene))
    lines = [_call_line(panel, gene), _single_sample_line(panel), _answer_line(panel)]
    ranks = panel.ranks()
    if ranks:
        heading = "Where to look first:"
        if panel.value("answer") != "place_to_look":
            heading = "Unusual places (none changes this result):"
        lines.append(heading)
        for n in ranks:
            lines.extend(_place_lines(panel, n, gene))
        lines.append(_more_line(panel))
    lines.append(_influential_line(panel, "sample"))
    lines.append(_nothing_line(panel))
    if int(panel.value("n_absent_study", 0)) > 0:
        lines.append(
            f"{panel.tok('n_absent_study')} samples are in no comparison; trace a sample to see "
            "which well left it out."
        )
    lines.append(_cannot_line())
    return "\n".join(line for line in lines if line)


def _absent_lines(panel: _Panel) -> list[str]:
    lines = [f"Sample {panel.tok('sample')} is in no comparison."]
    m = 1
    while panel.has(f"absent_1_{m}_reason"):
        q = f"absent_1_{m}_"
        reason = panel.value(q + "reason")
        if panel.has(q + "well"):
            what = "reference" if reason == "empty_reference_well" else "marker"
            text = (
                f"Its {panel.tok(q + 'target')} {what} well {panel.tok(q + 'well')} on plate "
                f"{panel.tok(q + 'plate')} has no value"
            )
            if panel.has(q + "left_out"):
                text += ": a person left it out of the analysis"
            elif panel.value(q + "note") == "no_amplification":
                text += ": LinRegPCR found no amplification"
            lines.append(text + ".")
        elif reason == "not_measured_for_every_gene":
            lines.append(f"It has no well for {panel.tok(q + 'target')}.")
        elif reason == "not_in_a_compared_group":
            lines.append("It is not in either compared group.")
        m += 1
    if panel.has("restore_class"):
        joins = ""
        if panel.has("restore_group"):
            joins = f"it would be in group {panel.tok('restore_group')}, and "
        changed = _calls_changed(panel, "restore_n_changed", "restore_changed_calls")
        lines.append(
            f"With that well read from the sample's other reference wells, {joins}{changed}."
        )
    return lines


def _sample_panel(facts: Facts, root_slug: str) -> str:
    panel = _Panel(facts, root_slug)
    if panel.value("answer") == "absent":
        lines = _absent_lines(panel)
    else:
        lines = [
            f"Sample {panel.tok('sample')} ({panel.tok('group')}) feeds {panel.tok('n_values')} "
            "values.",
            _answer_line(panel),
        ]
        for n in panel.ranks():
            lines.extend(_place_lines(panel, n, None))
        lines.append(_more_line(panel))
        if panel.has("set_aside_n_changed"):
            changed = _calls_changed(panel, "set_aside_n_changed", "set_aside_changed_calls")
            lines.append(f"With the whole sample set aside, {changed}.")
        lines.append(_influential_line(panel, "gene"))
        lines.append(_nothing_line(panel, count_plates=True))
    lines.append(_cannot_line())
    return "\n".join(line for line in lines if line)


def _well_panel(facts: Facts, root_slug: str) -> str:
    panel = _Panel(facts, root_slug)
    if panel.value("answer") == "absent":
        lines = [f"Well {panel.tok('well')} on plate {panel.tok('plate')}."]
        lines += _absent_lines(panel)
        return "\n".join(lines + [_cannot_line()])
    role = panel.value("role")
    head = f"Well {panel.tok('well')} on plate {panel.tok('plate')}"
    if panel.has("target"):
        head += f" ({panel.tok('target')}, sample {panel.tok('sample')})"
    lines = [head + "."]
    if role == "reference_well":
        lines.append(f"It feeds all {panel.tok('feeds')} values of sample {panel.tok('sample')}.")
    elif role == "target_well":
        lines.append(TARGET_LIMIT_WORDS.get(panel.value("limit"), TARGET_LIMIT_WORDS[None]))
    elif role == "ntc":
        if panel.has("n_study_wells_in_window"):
            lines.append(
                f"Study wells of this plate within its window: "
                f"{panel.tok('n_study_wells_in_window')}; in a comparison: "
                f"{panel.tok('n_compared_wells_in_window')}."
            )
    else:
        lines.append("It feeds no compared value.")
    lines.append(_answer_line(panel))
    for n in panel.ranks():
        lines.extend(_place_lines(panel, n, None))
    lines.append(_more_line(panel))
    lines.append(_nothing_line(panel))
    return "\n".join(line for line in lines if line)


def trace_v1(facts: Facts, card: DecisionCard | None, gene: str | None) -> str:
    """The gene panel as token text (template signature); degrades without trace facts.

    With a ``trace_set_aside`` card and no gene it gives the card's rationale.
    """
    if gene is None:
        if card is not None and card.kind == "trace_set_aside":
            return CARD_TEXT
        return NOT_RUN
    if f"f_trace_{slug(gene)}_call" not in facts:
        return NOT_RUN
    return _gene_panel(facts, gene)


def trace_set_aside_v1(facts: Facts, card: DecisionCard | None, gene: str | None) -> str:
    """The rationale of a ``trace_set_aside`` card: no numbers, so it renders from any facts."""
    return CARD_TEXT


TEMPLATES = {"trace_v1": trace_v1, "trace_set_aside_v1": trace_set_aside_v1}


def trace_tokens(result: TraceResult) -> str:
    """The panel of any trace result as token text (no digits outside tokens)."""
    facts = result.facts
    if not facts:
        return NOTHING
    kind, root_id = result.root["kind"], result.root["id"]
    if kind == "gene":
        return _gene_panel(facts, root_id)
    root_slug = f"{kind}_{slug(root_id)}"
    if kind == "sample":
        return _sample_panel(facts, root_slug)
    return _well_panel(facts, root_slug)


def render_trace(result: TraceResult, *, allowed_names: Iterable[str] = ()) -> RenderedText:
    """Render a trace's panel as tokens, plain text and HTML, checked by the validator.

    Allowed names: the root gene (for a gene trace) plus ``allowed_names``. A result without
    facts renders a sentence with no digits.

    Raises:
        TemplateError: The text fails the "no naked numbers" validator.
    """
    tokens = trace_tokens(result)
    names = set(allowed_names)
    if result.root.get("kind") == "gene":
        names.add(result.root["id"])
    check = validate(tokens, result.facts, names)
    if not check.ok:
        raise TemplateError(f"trace_v1: {check.error()}")
    return RenderedText(
        key="trace_v1",
        tokens=tokens,
        plain=render_tokens(tokens, result.facts),
        html=to_html(tokens, result.facts),
        fact_ids=tuple(dict.fromkeys(TOKEN.findall(tokens))),
    )
