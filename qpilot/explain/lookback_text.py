"""Plain-text answers for a lookback and a position history, rendered from facts only.

Every number and label is a ``{{fact_id}}`` token from the result's own facts
(``LookbackResult.facts``, ``PositionReport.facts``), checked with
:func:`qpilot.core.validator.validate` before rendering, so no number is ever typed. The words
are the logbook's: "changes k of N conclusions", "follows the instrument", "moves with the
samples", "not enough runs yet". Without a result the text is one digit-free sentence.

These functions are not registered as templates; the integration wires them in.
"""

from __future__ import annotations

from collections.abc import Mapping

from qpilot.core.facts import slug
from qpilot.core.validator import render_tokens, validate
from qpilot.qpcr.lookback import REASONS, LookbackResult
from qpilot.qpcr.position_history import PositionReport
from qpilot.schemas import Fact

NO_LOOKBACK = "No lookback has been run for this instrument."
NO_POSITIONS = "Position history has not been checked for this instrument."


def _t(fid: str) -> str:
    return "{{" + fid + "}}"


def _checked(text: str, facts: Mapping[str, Fact]) -> str:
    check = validate(text, facts)
    if not check.ok:
        raise ValueError(f"lookback text does not validate: {check.error()}")
    return text


def lookback_tokens(result: LookbackResult | None) -> str:
    """The lookback answer as token text (one line per study)."""
    if result is None or "f_lookback_instrument" not in result.facts:
        return NO_LOOKBACK
    facts = result.facts
    lines = [
        f"Lookback for instrument {_t('f_lookback_instrument')} from {_t('f_lookback_start')} "
        f"to {_t('f_lookback_end')}: runs in the window {_t('f_lookback_n_runs')}, wells "
        f"{_t('f_lookback_n_wells')}, studies {_t('f_lookback_n_studies')}."
    ]
    for study in result.studies:
        p = f"f_lookback_{slug(study.study_id)}"
        head = f"Study {_t(p + '_study')}: "
        if study.status == "no_runs_in_window":
            continue  # counted in one line below
        if study.status == "cannot_evaluate":
            line = head + REASONS.get(study.reason or "", "cannot evaluate")
            if f"{p}_marker" in facts:
                line += f" ({_t(p + '_marker')})"
            lines.append(line + ".")
            continue
        line = (
            head + f"leaving out its runs in the window ({_t(p + '_n_runs')}) changes "
            f"{_t(p + '_n_changed')} of {_t(p + '_n_conclusions')} conclusions"
        )
        if f"{p}_changed_genes" in facts:
            line += f" ({_t(p + '_changed_genes')})"
        line += "."
        if f"{p}_gone_genes" in facts:
            line += (
                f" No longer concluded, because their plates are in the window (not counted as "
                f"changes): {_t(p + '_gone_genes')}."
            )
        if f"{p}_refs_out" in facts:
            line += (
                f" Control-gene candidates measured in the window ({_t(p + '_refs_out')}) were "
                f"left out: the study was analysed again with {_t(p + '_refs_after')}."
            )
            if study.marker is not None:
                moved = "changed" if study.groups.get("changed") else "did not change"
                line += f" The marker groups are derived again from these candidates; they {moved}."
        lines.append(line)
    if any(s.status == "no_runs_in_window" for s in result.studies):
        lines.append(
            f"Studies with no runs from this instrument in the window: "
            f"{_t('f_lookback_n_untouched')}."
        )
    return _checked("\n".join(lines), facts)


def lookback_text(result: LookbackResult | None) -> str:
    """The lookback answer as plain text (numbers rendered from the result's facts)."""
    text = lookback_tokens(result)
    return render_tokens(text, result.facts) if result is not None else text


def position_tokens(report: PositionReport | None) -> str:
    """The position-history answer as token text (one line per instrument)."""
    if report is None or "f_position_base_rate" not in report.facts:
        return NO_POSITIONS
    facts = report.facts
    base = _t("f_position_base_rate")
    lines = [
        f"Base rate: {base} of wells sit more than {_t('f_position_off_cycles')} from the "
        f"median of their replicates ({_t('f_position_n_residuals')} wells with replicates)."
    ]
    for inst in report.instruments:
        p = f"f_position_{slug(inst.instrument_id)}"
        head = f"{_t(p + '_instrument')}: "
        if inst.answer == "follows_instrument":
            lines.append(
                head + f"positions {_t(p + '_flagged')} follow the instrument: they are off "
                f"their replicates more often than the base rate allows, in runs by more than "
                "one person or plate layout."
            )
        elif inst.answer == "moves_with_samples":
            lines.append(
                head + "nothing follows the instrument. The odd wells move between runs, so "
                "look at pipetting or the sample."
            )
        elif inst.reason == "one_person_one_layout":
            lines.append(
                head + f"positions {_t(p + '_beats_chance')} are off more often than chance, "
                "but always with the same samples in the same wells and no second person on "
                "record, so this cannot yet tell the instrument from the samples; a run with "
                "another layout or by another person would."
            )
        elif f"{p}_runs_needed" in facts:
            lines.append(
                head + f"not enough runs yet (need ≈ {_t(p + '_runs_needed')} runs at this "
                f"lab's noise; it has {_t(p + '_n_runs')})."
            )
        else:
            lines.append(head + "not enough runs yet.")
    return _checked("\n".join(lines), facts)


def position_text(report: PositionReport | None) -> str:
    """The position-history answer as plain text."""
    text = position_tokens(report)
    return render_tokens(text, report.facts) if report is not None else text


__all__ = ["lookback_text", "lookback_tokens", "position_text", "position_tokens"]
