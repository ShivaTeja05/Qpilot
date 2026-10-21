"""Plain-language text for a Spreadsheet Check, rendered from its facts only.

Every number is a ``{{fact_id}}`` token from :attr:`qpilot.qpcr.sheetcheck.SheetCheckResult.facts`
(ids ``f_sc_*``), and each text passes :func:`qpilot.core.validator.validate` before it is
returned. Sheet labels never appear: rows and columns are named by position, groups by order,
genes by the name the check made safe to show. When the facts are absent (no sheet checked),
each template returns a sentence without digits, as every registered template must.

Templates, all with the ``(facts, card, gene)`` signature of
:data:`qpilot.explain.templates.TEMPLATES` (they are not registered there; the integration
step adds :data:`TEMPLATES`):

* ``sheetcheck_v1``: the headline (k of n fold changes reproduce; m differ, j with a named
  cause), the first place to look, hand-overs and gene-name flags;
* ``sheetcheck_findings_v1``: one sentence per finding (only that gene's with ``gene=``);
* ``sheetcheck_handover_v1``: one gene's method hand-over (needs ``gene=``).

The check is not a Decision Card, so ``card`` is ignored.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from qpilot.core.validator import TOKEN, render_tokens, validate
from qpilot.explain.templates import RenderedText, TemplateError, to_html
from qpilot.schemas import DecisionCard, Fact

Facts = Mapping[str, Fact]

TEMPLATE_KEY = "sheetcheck_v1"
FINDINGS_KEY = "sheetcheck_findings_v1"
HANDOVER_KEY = "sheetcheck_handover_v1"
NOT_RUN = "No spreadsheet has been checked for this study."
NO_FINDINGS = "Every column the check could recompute reproduces from the sheet's own Cq values."
NO_HANDOVER = "No method hand-over: the engine's answer was not compared with this sheet."


def _t(fid: str) -> str:
    return "{{" + fid + "}}"


def _has(facts: Facts, *ids: str) -> bool:
    return all(fid in facts for fid in ids)


def _count(facts: Facts, fid: str) -> int:
    fact = facts.get(fid)
    return int(fact.value) if fact is not None and not isinstance(fact.value, str) else 0


def _finding_indices(facts: Facts) -> list[int]:
    found = {int(m.group(1)) for fid in facts if (m := re.fullmatch(r"f_sc_(\d+)_step", fid))}
    return sorted(found)


def _what(facts: Facts, k: int, *, start: bool = False) -> str:
    """``column F (ΔCq for MYC)``: which column, which step, which gene and group."""
    p = f"f_sc_{k}"
    inner = _t(p + "_step")
    if f"{p}_gene" in facts:
        inner += f" for {_t(p + '_gene')}"
    if facts.get(f"{p}_group") is not None and facts[f"{p}_group"].value != "every group":
        inner += f", {_t(p + '_group')}"
    return f"{'Column' if start else 'column'} {_t(p + '_column')} ({inner})"


def _rows(facts: Facts, k: int) -> str:
    """``from row 2 onwards (8 rows)``, ``in row 6`` or ``in 3 rows between row 4 and row 9``."""
    p = f"f_sc_{k}"
    n_rows = _count(facts, f"{p}_n_rows")
    if n_rows <= 1:
        return f"in row {_t(p + '_first_row')}"
    if facts.get(f"{p}_onwards") is not None and facts[f"{p}_onwards"].value == "onwards":
        return f"from row {_t(p + '_first_row')} onwards ({_t(p + '_n_rows')} rows)"
    return (
        f"in {_t(p + '_n_rows')} rows between row {_t(p + '_first_row')} and row "
        f"{_t(p + '_last_row')}"
    )


def _cause(facts: Facts, k: int) -> str:
    p = f"f_sc_{k}"
    status = facts[f"{p}_status"].value if f"{p}_status" in facts else "unexplained"
    if status == "explained" and f"{p}_path" in facts:
        return f"It is consistent with {_t(p + '_path')}."
    if status == "ambiguous" and f"{p}_path" in facts:
        return f"It is consistent with {_t(p + '_path')}; the sheet alone cannot tell which."
    if _has(facts, f"{p}_user", f"{p}_expected"):
        text = (
            f"No known path reproduces it: the sheet shows {_t(p + '_user')} where the textbook "
            f"path gives {_t(p + '_expected')}"
        )
        if f"{p}_gap" in facts:
            text += f" (the largest gap is {_t(p + '_gap')})"
        return text + "."
    return "No known path reproduces it."


def sheetcheck_v1(facts: Facts, card: DecisionCard | None = None, gene: str | None = None) -> str:
    """The headline of a check, the first place to look, hand-overs and gene-name flags."""
    if not _has(facts, "f_sc_n_fc", "f_sc_mapping_status"):
        return NOT_RUN
    text = f"Column mapping: {_t('f_sc_mapping_status')}. "
    if _count(facts, "f_sc_n_fc"):
        text += (
            f"{_t('f_sc_n_fc_reproduced')} of {_t('f_sc_n_fc')} fold changes reproduce from the "
            "sheet's own Cq values"
        )
        if _count(facts, "f_sc_n_fc_differ"):
            text += f"; {_t('f_sc_n_fc_differ')} differ, {_t('f_sc_n_fc_named')} with a named cause"
        text += ". "
    else:
        text += "The sheet shows no fold change to recompute. "
    indices = _finding_indices(facts)
    if indices:
        k = indices[0]
        text += f"The first place to look is {_what(facts, k)}, {_rows(facts, k)}. "
        text += _cause(facts, indices[0])
        if _count(facts, "f_sc_n_findings") > 1:
            text += (
                f" Places that differ on their own: {_t('f_sc_n_findings')} in all; later "
                "columns that only carry an earlier difference forward are not counted again."
            )
    elif _count(facts, "f_sc_n_columns_checked"):
        text += NO_FINDINGS
    else:
        text += "No column could be recomputed from the sheet's Cq values."
    if _count(facts, "f_sc_n_hand_overs"):
        text += (
            f" For {_t('f_sc_n_hand_overs')} genes the sheet's arithmetic reproduces but qPilot's "
            "own analysis of the study differs: a difference of method, shown in the "
            "robustness grid, not a slip in the sheet."
        )
    if _count(facts, "f_sc_n_symbol_flags"):
        text += (
            f" {_t('f_sc_n_symbol_flags')} gene names look like a date or number Excel made from "
            "a name; check them before trusting the gene labels."
        )
    return text


def sheetcheck_findings_v1(
    facts: Facts, card: DecisionCard | None = None, gene: str | None = None
) -> str:
    """One sentence per finding (``gene=`` keeps that gene's), in the order they were found."""
    if "f_sc_n_findings" not in facts:
        return NOT_RUN
    indices = _finding_indices(facts)
    if gene is not None:
        indices = [k for k in indices if _gene_is(facts, k, gene)]
    if not indices:
        return NO_FINDINGS
    parts = [
        f"{_what(facts, k, start=True)} differs {_rows(facts, k)}. {_cause(facts, k)}"
        for k in indices
    ]
    return " ".join(parts)


def _gene_is(facts: Facts, k: int, gene: str) -> bool:
    fact = facts.get(f"f_sc_{k}_gene")
    return fact is not None and str(fact.value).casefold() == gene.casefold()


def sheetcheck_handover_v1(
    facts: Facts, card: DecisionCard | None = None, gene: str | None = None
) -> str:
    """One gene's hand-over: the sheet's fold change, the engine's, and what differs."""
    if gene is None:
        return NO_HANDOVER
    from qpilot.core.facts import slug

    p = f"f_sc_ho_{slug(gene)}"
    if not _has(facts, f"{p}_gene", f"{p}_sheet_fc", f"{p}_engine_fc"):
        return NO_HANDOVER
    text = (
        f"{_t(p + '_gene')}: the sheet's arithmetic reproduces and gives {_t(p + '_sheet_fc')}; "
        f"qPilot's own analysis of the same study gives {_t(p + '_engine_fc')}"
    )
    if _has(facts, f"{p}_sheet_call", f"{p}_engine_call"):
        text += f" (call: {_t(p + '_sheet_call')} in the sheet, {_t(p + '_engine_call')} here)"
    text += ". This is a difference of method, not a slip"
    if f"{p}_causes" in facts:
        text += f": it comes from {_t(p + '_causes')}"
    return text + ". The robustness grid shows how much each choice moves it."


TEMPLATES: dict[str, Callable[[Facts, DecisionCard | None, str | None], str]] = {
    TEMPLATE_KEY: sheetcheck_v1,
    FINDINGS_KEY: sheetcheck_findings_v1,
    HANDOVER_KEY: sheetcheck_handover_v1,
}


def render(
    source: Any,
    key: str = TEMPLATE_KEY,
    *,
    gene: str | None = None,
    allowed_names: Iterable[str] = (),
) -> RenderedText:
    """Render one Spreadsheet Check template and validate it.

    Args:
        source: A :class:`~qpilot.qpcr.sheetcheck.SheetCheckResult` or its facts.
        key: One of :data:`TEMPLATES`.
        gene: The gene (``sheetcheck_findings_v1`` filters by it; the hand-over needs it).
        allowed_names: Extra names that may appear verbatim.

    Raises:
        KeyError: Unknown template key.
        TemplateError: The text fails the "no naked numbers" validator.
    """
    facts: Facts = getattr(source, "facts", source)
    if key not in TEMPLATES:
        raise KeyError(f"unknown template {key!r}; known: {', '.join(sorted(TEMPLATES))}")
    tokens = TEMPLATES[key](facts, None, gene)
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


__all__ = [
    "FINDINGS_KEY",
    "HANDOVER_KEY",
    "NOT_RUN",
    "TEMPLATES",
    "TEMPLATE_KEY",
    "render",
    "sheetcheck_findings_v1",
    "sheetcheck_handover_v1",
    "sheetcheck_v1",
]
