"""The wording of G-INSTR Gate lines, rendered from facts only (``instrument_gate_v1``).

Each :class:`~qpilot.qpcr.gate_instr.GateLine` becomes one sentence whose numbers are
``{{fact_id}}`` tokens from the line's own facts, so the paragraph passes
:func:`qpilot.core.validator.validate`. A line whose facts are absent degrades to a sentence
with no digits ("The run was paused during the run; the file does not say in which cycle.").
For example, a run with an old background calibration and a pause reads::

    Run completed. The run was paused during cycles 23–24. Background calibration done
    412 days before this run, past the vendor's 180-day expiry.

The consequence clause ("Excluding this run changes 0 of 58 conclusions.") is the line that
:func:`qpilot.qpcr.gate_instr.add_consequence` appends. This module is not registered in
``explain.templates.TEMPLATES``; integration does that.

Deterministic: no model call and no network.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence

from qpilot.core.validator import TOKEN, render_tokens, validate
from qpilot.explain.templates import RenderedText, TemplateError, to_html
from qpilot.qpcr.gate_instr import GateLine
from qpilot.schemas import Fact

TEMPLATE_KEY = "instrument_gate_v1"

_INTERRUPTION_OPENING = {
    "pause": "The run was paused",
    "lid_open": "The lid was opened",
    "drawer": "The drawer was opened",
}


def _t(fid: str) -> str:
    return "{{" + fid + "}}"


def _ending(facts: Mapping[str, Fact], suffix: str) -> str | None:
    """The id of the line's fact whose id ends with ``suffix`` (a line holds one of each)."""
    return next((fid for fid in sorted(facts) if fid.endswith(suffix)), None)


def _cycle_phrase(facts: Mapping[str, Fact], *, during: bool) -> str:
    first = _ending(facts, "_first_cycle")
    last = _ending(facts, "_last_cycle")
    if first and last and facts[first].value != facts[last].value:
        return f" during cycles {_t(first)}–{_t(last)}"
    if first:
        return f" during cycle {_t(first)}"
    single = _ending(facts, "_cycle")
    if single:
        return f" at cycle {_t(single)}"
    return "; the file does not say in which cycle" if during else ""


def _run_complete(line: GateLine) -> str:
    return "Run completed."


def _run_not_complete(line: GateLine) -> str:
    state = _ending(line.facts, "_run_state")
    if state:
        return f"The file says the run did not complete (state: {_t(state)})."
    return "The file says the run did not complete."


def _interrupted(line: GateLine) -> str:
    kind = _ending(line.facts, "_kind")
    opening = _INTERRUPTION_OPENING.get(
        str(line.facts[kind].value) if kind else "", "The run was interrupted"
    )
    phrase = _cycle_phrase(line.facts, during=True)
    if phrase.startswith(";"):
        return f"{opening} during the run{phrase}."
    return f"{opening}{phrase}."


def _aborted(line: GateLine) -> str:
    return f"The log records an abort{_cycle_phrase(line.facts, during=False)}."


def _power(line: GateLine) -> str:
    return f"The log records a power event{_cycle_phrase(line.facts, during=False)}."


def _no_interruptions(line: GateLine) -> str:
    return "No pauses or lid openings."


def _calibration_expired(line: GateLine) -> str:
    labels = [_t(fid) for fid in sorted(line.facts) if fid.endswith("_label")]
    more = _ending(line.facts, "_n_more")
    age = _ending(line.facts, "_age_days")
    interval = _ending(line.facts, "_interval_days")
    if more:
        what = f"{', '.join(labels)} and {_t(more)} more calibrations"
    elif len(labels) > 1:
        what = f"{', '.join(labels[:-1])} and {labels[-1]} calibrations"
    elif labels:
        what = f"{labels[0]} calibration"
    else:
        what = "a calibration"
    plural = more or len(labels) > 1
    expiry = f"the vendor's {_t(interval)}-day expiry" if interval else "the vendor's expiry"
    if age:
        return f"{what[0].upper()}{what[1:]} done {_t(age)} days before this run, past {expiry}."
    verb = "were" if plural else "was"
    subject = f"the {what}" if labels else what
    return f"The file says {subject} {verb} past {expiry} at this run."


def _calibrations_in_date(line: GateLine) -> str:
    return "No calibration was past the vendor's expiry."


def _calibration_date_not_in_file(line: GateLine) -> str:
    return "Calibration dates are not in the file."


def _hold_off(line: GateLine) -> str:
    deviation = _ending(line.facts, "_max_hold_deviation_c")
    limit = _ending(line.facts, "_hold_limit_c")
    if deviation and limit:
        return (
            f"Sample temperature was up to {_t(deviation)} off its setpoint during a hold, "
            f"beyond the lab's limit of {_t(limit)}."
        )
    return "Sample temperature drifted from its setpoint during a hold, beyond the lab's limit."


def _hold_on(line: GateLine) -> str:
    limit = _ending(line.facts, "_hold_limit_c")
    if limit:
        return f"Hold temperatures stayed within {_t(limit)} of the setpoint."
    return "Hold temperatures stayed within the lab's limit."


def _nothing_to_check(line: GateLine) -> str:
    return "The file names the instrument but records no run state, calibration or event to check."


def _nothing_in_file(line: GateLine) -> str:
    return "The file says nothing about the instrument for this run."


def _consequence(line: GateLine) -> str:
    changed = _ending(line.facts, "_excl_changed")
    total = _ending(line.facts, "_excl_total")
    if changed and total:
        return f"Excluding this run changes {_t(changed)} of {_t(total)} conclusions."
    return "The consequence of excluding this run was not computed."


SENTENCES: dict[str, Callable[[GateLine], str]] = {
    "run_complete": _run_complete,
    "run_not_complete": _run_not_complete,
    "interrupted": _interrupted,
    "aborted_in_log": _aborted,
    "power_event": _power,
    "no_interruptions": _no_interruptions,
    "calibration_expired": _calibration_expired,
    "calibrations_in_date": _calibrations_in_date,
    "calibration_date_not_in_file": _calibration_date_not_in_file,
    "hold_off_setpoint": _hold_off,
    "hold_on_setpoint": _hold_on,
    "nothing_to_check": _nothing_to_check,
    "nothing_in_file": _nothing_in_file,
    "consequence": _consequence,
}


def line_tokens(line: GateLine) -> str:
    """One Gate line as token text.

    Raises:
        KeyError: The line's code has no wording.
    """
    return SENTENCES[line.code](line)


def render_gate(lines: Sequence[GateLine], *, allowed_names: Iterable[str] = ()) -> RenderedText:
    """Render G-INSTR lines as one paragraph: token text, plain text and HTML.

    Args:
        lines: Lines from :func:`qpilot.qpcr.gate_instr.g_instr`, optionally with the line from
            :func:`qpilot.qpcr.gate_instr.add_consequence`.
        allowed_names: Names that may appear verbatim (none are needed by the wording).

    Returns:
        The paragraph, checked by the "no naked numbers" validator.

    Raises:
        TemplateError: The text fails the validator (a fact missing or a digit outside a token).
    """
    facts: dict[str, Fact] = {}
    for line in lines:
        facts.update(line.facts)
    tokens = " ".join(line_tokens(line) for line in lines)
    check = validate(tokens, facts, allowed_names)
    if not check.ok:
        raise TemplateError(f"{TEMPLATE_KEY}: {check.error()}")
    return RenderedText(
        key=TEMPLATE_KEY,
        tokens=tokens,
        plain=render_tokens(tokens, facts),
        html=to_html(tokens, facts),
        fact_ids=tuple(dict.fromkeys(TOKEN.findall(tokens))),
    )
