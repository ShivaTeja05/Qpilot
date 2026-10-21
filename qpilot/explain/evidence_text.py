"""Text for the Evidence Ledger, the G-RT line and the Run Review, rendered only from facts.

Three template functions with the ``(facts, card, gene) -> token text`` signature of
:data:`qpilot.explain.templates.TEMPLATES`, collected in :data:`EVIDENCE_TEMPLATES` for the
integration to register (this module does not touch the shared registry):

* ``evidence_v1`` (:func:`evidence_text`): the ledger's summary line and one line per item,
  "title: status. consequence", the consequence chosen by the item's code fact;
* ``grt_v1`` (:func:`gate_rt_text`): the G-RT line (RT-replicate Cq range);
* ``runreview_v1`` (:func:`runreview_text`): the thin Run Review (headline, ledger, sign-offs).

Every number is a ``{{fact_id}}`` token, and the text passes
:func:`qpilot.core.validator.validate`. Each function degrades to one digit-free sentence when
its facts are absent, so it renders from any study's facts. :func:`render_facts` validates and
renders token text the way :func:`qpilot.explain.templates.render_template` does.

Deterministic; no model call.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

from qpilot.core.facts import slug
from qpilot.core.validator import TOKEN, render_tokens, validate
from qpilot.explain.templates import RenderedText, TemplateError, to_html
from qpilot.qpcr.evidence import CONSEQUENCES, ITEM_TITLES, ITEMS, EvidenceLedger
from qpilot.qpcr.gate_rt import GateLine
from qpilot.schemas import DecisionCard, Fact

Facts = Mapping[str, Fact]

STATUS_WORDS: dict[str, str] = {
    "present": "present",
    "absent": "absent",
    "not_applicable": "not applicable",
    "unknown": "unknown",
}
NOT_BUILT = "The Evidence Ledger has not been built for this study."
GRT_NOT_RUN = "G-RT has not been run for this study."
REVIEW_NOT_BUILT = "No Run Review has been built for this study."
LEDGER_SUMMARY = (
    "Evidence Ledger: {{f_ev_n_present}} of {{f_ev_n_items}} items present, "
    "{{f_ev_n_absent}} absent, {{f_ev_n_unknown}} unknown and {{f_ev_n_not_applicable}} not "
    "applicable. Absent items never change a conclusion or a confidence grade; they say what "
    "this study cannot show."
)
NOT_AVAILABLE: tuple[tuple[str, str, str], ...] = (  # (id, title, reason): the thin version
    ("repeat", "What to repeat and why", "not available yet; the repeat plan is not built."),
    ("gate", "Run Gate lines per plate", "not available yet; the Run Gate is not built."),
    (
        "next_run",
        "What to change next run",
        "not available yet; it needs the replicate planner and the plate-map checks.",
    ),
)
PURPOSE = (
    "qPilot does not pass or fail a run; it shows what the data can and cannot show, and a "
    "person signs off."
)
NO_HEADLINE = "No headline genes are named for this study."
NO_SIGNOFF = "No sign-off is recorded yet."
_SUMMARY_IDS = ("f_ev_n_items", "f_ev_n_present", "f_ev_n_absent", "f_ev_n_unknown",
                "f_ev_n_not_applicable")  # fmt: skip


def _t(fid: str) -> str:
    return "{{" + fid + "}}"


def _need(facts: Facts, ids: Iterable[str], where: str) -> None:
    missing = [fid for fid in ids if fid not in facts]
    if missing:
        raise TemplateError(f"{where}: missing facts: {', '.join(missing)}")


def _value(facts: Facts, fid: str) -> float | int | str | None:
    fact = facts.get(fid)
    return None if fact is None else fact.value


# ---------- the Evidence Ledger ----------


def item_line(facts: Facts, item: str) -> str | None:
    """Token text for one ledger item, ``None`` when the facts do not hold that item.

    Raises:
        TemplateError: The item's code is unknown or a fact its consequence cites is missing.
    """
    status = _value(facts, f"f_ev_{item}_status")
    if status is None:
        return None
    code = str(_value(facts, f"f_ev_{item}_code") or "")
    if code not in CONSEQUENCES or str(status) not in STATUS_WORDS:
        raise TemplateError(f"evidence item {item}: unknown code {code!r} or status {status!r}")
    text = CONSEQUENCES[code]
    _need(facts, TOKEN.findall(text), f"evidence item {item}")
    return f"{ITEM_TITLES[item]}: {STATUS_WORDS[str(status)]}. {text}"


def ledger_summary(facts: Facts) -> str | None:
    """The ledger's one-sentence count of items by status, ``None`` without ledger facts."""
    if not all(fid in facts for fid in _SUMMARY_IDS):
        return None
    return LEDGER_SUMMARY


def evidence_text(facts: Facts, card: DecisionCard | None = None, gene: str | None = None) -> str:
    """Template ``evidence_v1``: the ledger summary and one line per item (token text).

    ``card`` and ``gene`` are ignored (the registry's signature). Without ledger facts the text
    is one digit-free sentence.
    """
    summary = ledger_summary(facts)
    if summary is None:
        return NOT_BUILT
    lines = [summary]
    lines += [line for item in ITEMS if (line := item_line(facts, item)) is not None]
    return "\n".join(lines)


# ---------- G-RT ----------


def gate_rt_text(facts: Facts, card: DecisionCard | None = None, gene: str | None = None) -> str:
    """Template ``grt_v1``: the G-RT verdict from the ``f_grt_*`` facts (token text).

    ``card`` and ``gene`` are ignored. Without G-RT facts the text is one digit-free sentence.
    """
    if "f_grt_limit" not in facts or "f_grt_n_units" not in facts:
        return GRT_NOT_RUN
    if int(_value(facts, "f_grt_n_units") or 0) == 0:
        return "G-RT does not apply: no RT replicates annotated, so RT variability not measured."
    if int(_value(facts, "f_grt_n_pairs") or 0) == 0:
        return (
            "G-RT does not apply: RT replicates are annotated for {{f_grt_n_units}} biological "
            "units, but no unit × target has RT replicates with a Cq to compare."
        )
    ids = ("f_grt_n_over", "f_grt_max_range", "f_grt_worst_unit", "f_grt_worst_target")
    _need(facts, ids, "grt_v1")
    caveat = " The line is quoted from the literature and still to be checked against the paper."
    if int(_value(facts, "f_grt_n_over") or 0) == 0:
        return (
            "G-RT passes: all {{f_grt_n_pairs}} biological unit × target RT-replicate Cq ranges "
            "are below {{f_grt_limit}}; the largest is {{f_grt_max_range}}." + caveat
        )
    return (
        "G-RT warns: {{f_grt_n_over}} of {{f_grt_n_pairs}} biological unit × target "
        "RT-replicate Cq ranges reach {{f_grt_limit}} or more; the largest is "
        "{{f_grt_max_range}}, for {{f_grt_worst_unit}} and {{f_grt_worst_target}}. RT "
        "variability is part of those fold changes." + caveat
    )


# ---------- the Run Review ----------


def _numbered(facts: Facts, prefix: str, suffix: str) -> list[int]:
    """The indices i with a fact ``<prefix><i><suffix>``, ascending."""
    found = []
    for fid in facts:
        if fid.startswith(prefix) and fid.endswith(suffix):
            middle = fid[len(prefix) : len(fid) - len(suffix)]
            if middle.isdigit():
                found.append(int(middle))
    return sorted(found)


def headline_lines(facts: Facts) -> list[str]:
    """One token line per headline gene of a Run Review (``f_rr_headline_<i>_gene`` facts).

    Each line names the call, the fold change, the confidence level and how often the
    conclusion holds, using the study's own facts for that gene where they exist.
    """
    lines = []
    for i in _numbered(facts, "f_rr_headline_", "_gene"):
        p = f"f_rr_headline_{i}"
        g = slug(str(_value(facts, f"{p}_gene")))
        line = f"{_t(p + '_gene')}: {_t(p + '_call')}"
        _need(facts, (f"{p}_call",), "runreview_v1")
        if f"f_fc_{g}_recommended" in facts:
            line += f", {_t(f'f_fc_{g}_recommended')}"
        parts = []
        if f"f_level_{g}" in facts:
            parts.append(f"{_t(f'f_level_{g}')} confidence")
        if f"f_holds_{g}" in facts and "f_n_cells" in facts:
            parts.append(f"holds in {_t(f'f_holds_{g}')} of {_t('f_n_cells')} analyses")
        if parts:
            line += f" ({'; '.join(parts)})"
        lines.append(line + ".")
    return lines


def signoff_lines(facts: Facts) -> list[str]:
    """One token line per recorded sign-off (``f_rr_review_<seq>_*`` facts), oldest first."""
    lines = []
    for seq in _numbered(facts, "f_rr_review_", "_reviewer"):
        p = f"f_rr_review_{seq}"
        _need(facts, (f"{p}_seq", f"{p}_outcome"), "runreview_v1")
        line = f"{_t(p + '_reviewer')} chose {_t(p + '_outcome')}"
        if f"{p}_at" in facts:
            line += f" on {_t(p + '_at')}"
        line += f" (decision-log entry {_t(p + '_seq')})"
        if f"{p}_comment" in facts:
            line += f": “{_t(p + '_comment')}”"
        lines.append(line + ".")
    return lines


def study_line(facts: Facts) -> str:
    """The Run Review's first line: the study id and, when known, its size."""
    line = "Run Review of study {{f_rr_study_id}}"
    if all(fid in facts for fid in ("f_n_plates", "f_n_samples", "f_n_reactions")):
        line += ": {{f_n_plates}} plates, {{f_n_samples}} samples, {{f_n_reactions}} reactions"
    return line + "."


def ledger_missing(facts: Facts) -> str:
    """Why a Run Review shows no ledger (the reason is a fact when one was recorded)."""
    if "f_rr_ledger_note" in facts:
        return "The Evidence Ledger is not available for this study: {{f_rr_ledger_note}}."
    return "The Evidence Ledger is not available for this study."


def runreview_text(facts: Facts, card: DecisionCard | None = None, gene: str | None = None) -> str:
    """Template ``runreview_v1``: the thin Run Review as token text (one line per point).

    ``card`` and ``gene`` are ignored. Without Run Review facts the text is one digit-free
    sentence. The text never judges the run: it states what the data can show and who signed
    off, and lists the parts that are not built yet.
    """
    if "f_rr_study_id" not in facts:
        return REVIEW_NOT_BUILT
    lines = [study_line(facts), PURPOSE]
    lines += headline_lines(facts) or [NO_HEADLINE]
    lines.append(ledger_summary(facts) or ledger_missing(facts))
    lines += signoff_lines(facts) or [NO_SIGNOFF]
    lines += [f"{title}: {reason}" for _, title, reason in NOT_AVAILABLE]
    return "\n".join(lines)


Template = Callable[[Facts, "DecisionCard | None", "str | None"], str]

EVIDENCE_TEMPLATES: dict[str, Template] = {
    "evidence_v1": evidence_text,
    "grt_v1": gate_rt_text,
    "runreview_v1": runreview_text,
}


# ---------- rendering ----------


def render_facts(
    key: str, tokens: str, facts: Facts, *, allowed_names: Iterable[str] = ()
) -> RenderedText:
    """Validate token text and render it three ways, as ``render_template`` does.

    Args:
        key: A name for the text (a template key such as ``evidence_v1``).
        tokens: The token text.
        facts: The facts the tokens cite.
        allowed_names: Names that may appear verbatim (none of these templates needs one).

    Raises:
        TemplateError: An unknown or empty fact token, or a number outside a token.
    """
    check = validate(tokens, facts, allowed_names)
    if not check.ok:
        raise TemplateError(f"{key}: {check.error()}")
    return RenderedText(
        key=key,
        tokens=tokens,
        plain=render_tokens(tokens, facts),
        html=to_html(tokens, facts),
        fact_ids=tuple(dict.fromkeys(TOKEN.findall(tokens))),
    )


def _facts_of(source: EvidenceLedger | GateLine | Facts) -> Facts:
    return source.facts if isinstance(source, EvidenceLedger | GateLine) else source


def render_evidence(source: EvidenceLedger | Facts) -> RenderedText:
    """``evidence_v1`` validated and rendered from a ledger (or its ``facts``)."""
    facts = _facts_of(source)
    return render_facts("evidence_v1", evidence_text(facts), facts)


def render_gate_rt(source: GateLine | Facts) -> RenderedText:
    """``grt_v1`` validated and rendered from a G-RT line (or its ``facts``)."""
    facts = _facts_of(source)
    return render_facts("grt_v1", gate_rt_text(facts), facts)
