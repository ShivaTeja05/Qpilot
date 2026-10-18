"""G-INSTR: the Gate lines for what the run file says about the instrument.

:func:`g_instr` turns a :class:`~qpilot.qpcr.instrument_context.RunContext` into Gate lines, one
per check the file allows:

* run state: ``complete`` is a pass; any other state the file gives is a warning;
* interruptions: a pause, a lid or cover opened, or a drawer opened during the run is a warning
  that names the cycles to look at (the cycle it happened in through the cycle the run resumed
  in, and never less than the next cycle, whose reading is the first after the interruption);
  an abort or a power event in the log is a warning. With an event log and none of these, the
  line is a pass ("no pauses"); without an event log nothing is said about pauses;
* calibrations: calibrations the vendor's own expiry (or the file's "is expired" flag) puts
  past expiry at run time are ``info``, never more: whether an expired optical calibration
  moves Cq is not known, so it is a fact to weigh, not a reason to set the run aside. There is
  one line per age and expiry interval, naming up to :data:`MAX_LABELS` calibrations and
  counting the rest. Calibration dates the file does not carry (StepOne) are ``info`` too;
* temperature: a hold that drifts from its setpoint by more than ``hold_limit_c`` is a warning;
* a file that says nothing about the instrument gives one ``not_applicable`` line.

Every number on a line is a fact (``GateLine.facts``), so the wording
(:mod:`qpilot.explain.instrument_text`) carries no naked numbers. Facts that are local only
(serials, instrument names) never enter a Gate line.

The consequence clause ("Excluding this run changes k of N conclusions") needs the study, so
it is composed later: :func:`needs_consequence` says whether any line calls for the consequence
test, and :func:`add_consequence` appends its result as a line.

Deterministic: no model call and no network.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field

from qpilot.core.facts import slug
from qpilot.qpcr.instrument_context import (
    INTERRUPTIONS,
    NOTE_CAL_NOT_IN_FILE,
    RunContext,
    is_local_only,
)
from qpilot.schemas import Fact

RULE_ID = "G-INSTR"
DEFAULT_HOLD_LIMIT_C = 0.5  # a lab sets its own; the default is a placeholder, not a vendor spec
MAX_LABELS = 3  # calibrations named on one line; the rest are counted
GateStatus = Literal["pass", "info", "warn", "not_applicable"]

#: Every code a G-INSTR line can carry, and its status.
CODES: dict[str, GateStatus] = {
    "run_complete": "pass",
    "run_not_complete": "warn",
    "interrupted": "warn",
    "aborted_in_log": "warn",
    "power_event": "warn",
    "no_interruptions": "pass",
    "calibration_expired": "info",
    "calibrations_in_date": "pass",
    "calibration_date_not_in_file": "info",
    "hold_off_setpoint": "warn",
    "hold_on_setpoint": "pass",
    "nothing_to_check": "not_applicable",
    "nothing_in_file": "not_applicable",
    "consequence": "info",
}


class GateLine(BaseModel):
    """One Gate line: a rule, a status, a code for the wording, its facts and cycles."""

    rule_id: str = RULE_ID
    status: GateStatus
    code: str
    facts: dict[str, Fact] = Field(default_factory=dict)
    cycles: list[int] = Field(default_factory=list)


def _line(code: str, facts: Sequence[Fact] = (), cycles: Sequence[int] = ()) -> GateLine:
    shown = {fact.id: fact for fact in facts if not is_local_only(fact)}
    return GateLine(status=CODES[code], code=code, facts=shown, cycles=list(cycles))


def _get(ctx: RunContext, name: str) -> Fact | None:
    return ctx.facts.get(ctx.fact_id(name))


def _present(*facts: Fact | None) -> list[Fact]:
    return [fact for fact in facts if fact is not None]


def g_instr(ctx: RunContext, *, hold_limit_c: float = DEFAULT_HOLD_LIMIT_C) -> list[GateLine]:
    """The G-INSTR Gate lines for one run context.

    Args:
        ctx: What the run file says (:func:`~qpilot.qpcr.instrument_context.read_run_context`).
        hold_limit_c: The lab's limit, in °C, for a sample temperature off its setpoint during a
            hold.

    Returns:
        Lines in a fixed order: run state, interruptions, calibrations, temperature. A file
        with nothing to check gives a single ``not_applicable`` line.
    """
    lines: list[GateLine] = []
    lines += _run_state(ctx)
    lines += _interruptions(ctx)
    lines += _calibrations(ctx)
    lines += _temperature(ctx, hold_limit_c)
    if lines:
        return lines
    something = (
        any(ctx.identity.values())
        or ctx.run.get("date_source") == "instrument"
        or bool(ctx.well_flags)
    )
    return [_line("nothing_to_check" if something else "nothing_in_file")]


def _run_state(ctx: RunContext) -> list[GateLine]:
    state = ctx.run.get("state")
    if state is None:
        return []
    fact = _get(ctx, "run_state")
    if state == "complete":
        return [_line("run_complete", _present(fact))]
    return [_line("run_not_complete", _present(fact))]


def _interruptions(ctx: RunContext) -> list[GateLine]:
    if "event_log" not in ctx.checked:
        return []
    lines: list[GateLine] = []
    for index, event in enumerate(ctx.events, start=1):
        kind = event["kind"]
        facts = _present(
            _get(ctx, f"event_{index}_kind"),
            _get(ctx, f"event_{index}_first_cycle"),
            _get(ctx, f"event_{index}_last_cycle"),
        )
        if kind in INTERRUPTIONS:
            lines.append(_line("interrupted", facts, event.get("cycles") or []))
        elif kind == "abort":
            cycle = event.get("cycle")
            cycles = [cycle] if cycle is not None else []
            lines.append(
                _line("aborted_in_log", _present(_get(ctx, f"event_{index}_cycle")), cycles)
            )
        elif kind == "power":
            cycle = event.get("cycle")
            cycles = [cycle] if cycle is not None else []
            lines.append(_line("power_event", _present(_get(ctx, f"event_{index}_cycle")), cycles))
    if not lines:
        lines.append(_line("no_interruptions"))
    return lines


def _calibrations(ctx: RunContext) -> list[GateLine]:
    lines: list[GateLine] = []
    if NOTE_CAL_NOT_IN_FILE in ctx.notes:
        lines.append(_line("calibration_date_not_in_file"))
    known = [cal for cal in ctx.calibrations if cal.get("expired_at_run") is not None]
    groups: dict[tuple[int | None, int | None], list[dict]] = {}
    for cal in ctx.calibrations:
        if cal.get("expired_at_run") is True:
            groups.setdefault((cal.get("age_days"), cal.get("interval_days")), []).append(cal)
    for number, cals in enumerate(groups.values(), start=1):
        first = f"cal_{cals[0]['type']}"
        facts = [_get(ctx, f"cal_{cal['type']}_label") for cal in cals[:MAX_LABELS]]
        facts += [_get(ctx, f"{first}_age_days"), _get(ctx, f"{first}_interval_days")]
        if len(cals) > MAX_LABELS:
            facts.append(
                Fact(
                    id=ctx.fact_id(f"expired_group_{number}_n_more"),
                    value=len(cals) - MAX_LABELS,
                    path="G-INSTR: further calibrations with the same age and expiry",
                )
            )
        lines.append(_line("calibration_expired", _present(*facts)))
    if known and not any(cal["expired_at_run"] for cal in known):
        lines.append(_line("calibrations_in_date"))
    return lines


def _temperature(ctx: RunContext, hold_limit_c: float) -> list[GateLine]:
    deviation = (ctx.temperature or {}).get("max_hold_deviation_c")
    if deviation is None:
        return []
    limit = Fact(
        id=ctx.fact_id("hold_limit_c"),
        value=float(hold_limit_c),
        fmt="{:.2f}",
        unit=" °C",
        path="lab setting: G-INSTR hold_limit_c",
    )
    measured = _get(ctx, "max_hold_deviation_c")
    if deviation > hold_limit_c:
        return [_line("hold_off_setpoint", _present(measured, limit))]
    return [_line("hold_on_setpoint", _present(limit))]


def needs_consequence(lines: Sequence[GateLine]) -> bool:
    """True when a line is a warning or an info, so the consequence test should run."""
    return any(line.status in ("warn", "info") for line in lines)


def add_consequence(
    lines: Sequence[GateLine], *, n_changed: int, n_total: int, run_label: str = "run"
) -> list[GateLine]:
    """Append the consequence of excluding this run, computed by the caller.

    Integration computes ``n_changed`` with the lookback or Trace exclusion functions (the
    robustness grid re-run without this run's wells) and calls this; G-INSTR never computes it.

    Args:
        lines: The lines from :func:`g_instr`.
        n_changed: Conclusions that change when the run is excluded.
        n_total: Conclusions in the study.
        run_label: Part of the fact ids (``f_instr_<label>_excl_changed``), for several runs.

    Returns:
        A new list: ``lines`` plus one ``consequence`` line whose facts are the two counts.

    Raises:
        ValueError: The counts are negative or ``n_changed`` exceeds ``n_total``.
    """
    if n_changed < 0 or n_total < 0 or n_changed > n_total:
        raise ValueError("n_changed must be between 0 and n_total")
    part = slug(run_label)
    changed = Fact(
        id=f"f_instr_{part}_excl_changed",
        value=int(n_changed),
        path="consequence test: conclusions that change without this run",
    )
    total = Fact(
        id=f"f_instr_{part}_excl_total",
        value=int(n_total),
        path="consequence test: conclusions in the study",
    )
    return [*lines, _line("consequence", [changed, total])]
