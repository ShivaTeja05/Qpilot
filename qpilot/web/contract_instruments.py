"""Response models of the Instruments routes (``routers/instruments.py``).

The engine is origin/main's instrument registry and hash-chained logbook
(:mod:`qpilot.core.instruments`), the run-file reader (:mod:`qpilot.qpcr.instrument_context`,
G-INSTR lines) and the lookback (:mod:`qpilot.qpcr.lookback`). Serial numbers and identity
strings never leave the registry: nothing here carries one.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from qpilot.web.contract import FactText

TypedKind = Literal["calibration", "component_change", "service", "move", "note"]


class CalibrationAge(BaseModel):
    """The latest calibration of one type, from the logbook."""

    type: str
    performed_on: str
    age_days: int
    source: str


class InstrumentSummary(BaseModel):
    """One registered instrument as the list shows it (no serial number, no alias)."""

    instrument_id: str
    display_name: str
    make_model: str
    location: str
    shared: bool
    n_events: int
    n_open_incidents: int
    n_proposed: int = Field(description="Incidents an agent proposed, waiting for a person.")
    calibrations: list[CalibrationAge]
    chain_ok: bool
    problems: list[str] = Field(description="What is wrong with the logbook's chain, if any.")


class KindView(BaseModel):
    """An event kind a person can log, in words."""

    id: TypedKind
    word: str


class InstrumentsView(BaseModel):
    """``GET /instruments``: the registry, with each instrument's state now."""

    instruments: list[InstrumentSummary]
    kinds: list[KindView]
    as_of: str
    note: str = Field(description="What the registry and logbook are, and what they are not.")


class RegisterBody(BaseModel):
    """Register an instrument (a person; serials are linked from its run files, never typed)."""

    display_name: str = Field(min_length=1, max_length=200)
    instrument_id: str | None = Field(
        None, max_length=64, description="A short id; made from the name when left out."
    )
    make_model: str = Field("", max_length=200)
    location: str = Field("", max_length=200)
    shared: bool = False


class EventView(BaseModel):
    """One logbook entry (what a person typed is shown here, on their own page)."""

    seq: int
    kind: str
    kind_word: str
    source: str = Field(description="file, inferred or typed.")
    actor: str
    at: str | None
    recorded_at: str
    run_hash: str | None
    wells: list[str]
    details: dict[str, Any]
    note: str
    hash: str


class FixView(BaseModel):
    """What a person noted fixed an incident."""

    seq: int | None
    note: str
    at: str | None


class IncidentView(BaseModel):
    """An incident rebuilt from the chain: proposed (by an agent), confirmed or turned down."""

    seq: int
    status: Literal["proposed", "confirmed", "rejected"]
    at: str | None
    actor: str
    run_hash: str | None
    wells: list[str]
    metric: str | None
    direction: str | None
    error_code: str | None
    note: str
    fixes: list[FixView]
    can_confirm: bool
    can_fix: bool


class InstrumentView(BaseModel):
    """``GET /instruments/{id}``: the instrument, its logbook and its incidents."""

    instrument: InstrumentSummary
    events: list[EventView]
    incidents: list[IncidentView]
    head: str


class EventBody(BaseModel):
    """A person logs a service visit, a move, a calibration, a part change or a note."""

    kind: TypedKind
    note: str = Field("", max_length=2000)
    at: str | None = Field(None, max_length=40, description="When (ISO date); today if left out.")
    calibration_type: str | None = Field(None, max_length=60)
    component: str | None = Field(None, max_length=60)


class IncidentBody(BaseModel):
    """A person logs an incident they saw (confirmed, since a person logs it)."""

    wells: list[str] = Field(min_length=1, max_length=96)
    metric: str = Field(min_length=1, max_length=64, pattern="^[a-z0-9_]{1,64}$")
    direction: Literal["low", "high"]
    note: str = Field("", max_length=2000)
    run_hash: str | None = Field(None, max_length=64)


class FixBody(BaseModel):
    """What fixed an incident (a person)."""

    note: str = Field(min_length=1, max_length=2000)
    at: str | None = Field(None, max_length=40)


class Logged(BaseModel):
    """The answer to a logbook write: what was written and the instrument now."""

    message: str
    seq: int
    instrument: InstrumentView


class GateLineView(BaseModel):
    """One G-INSTR line about a run file, in words (numbers as facts)."""

    rule_id: str
    status: str
    code: str
    text: FactText


class RunQuestion(BaseModel):
    """The one question asked for a run file that names no registered instrument."""

    question: str
    reason: str
    choices: list[dict[str, str]]


class RunFileView(BaseModel):
    """``POST /instruments/runs``: what a run file says about its instrument (no serials)."""

    run_id: str = Field(description="The kept file's content id.")
    name: str
    context: dict[str, Any] = Field(
        description="The run context's model view: model, firmware, run state, calibrations "
        "and their age, pauses, temperature, vendor flags; serial fields named, never shown."
    )
    gate: list[GateLineView]
    instrument_id: str | None = Field(None, description="The registered instrument it names.")
    question: RunQuestion | None = None


class LinkBody(BaseModel):
    """Which instrument a run file is from (a person answers the question)."""

    instrument_id: str = Field(min_length=1, max_length=64)


class Linked(BaseModel):
    """The run file is linked: its next files resolve by themselves."""

    instrument_id: str
    n_logged: int = Field(description="Events the file states (an aborted run, a pause …).")
    message: str


class LookbackBody(BaseModel):
    """Which instrument and which days (ISO dates, inclusive)."""

    instrument_id: str = Field(min_length=1, max_length=64)
    start: str = Field(min_length=10, max_length=10)
    end: str = Field(min_length=10, max_length=10)


class LookbackChange(BaseModel):
    """A gene whose call differs once the window's runs are left out."""

    gene: str
    before: str
    after: str


class LookbackView(BaseModel):
    """What leaving a study's runs on that instrument in that window out does to its calls."""

    study_id: str
    instrument_id: str
    start: str
    end: str
    status: str
    n_conclusions: int
    n_changed: int
    changed: list[LookbackChange]
    runs_in_window: list[str]
    n_wells_in_window: int
    assumed_all_runs: bool = Field(
        description="No run-to-instrument map was recorded: every run counts as on it."
    )
    text: FactText
    saved: bool = False


__all__ = [
    "CalibrationAge",
    "EventBody",
    "EventView",
    "FixBody",
    "FixView",
    "GateLineView",
    "IncidentBody",
    "IncidentView",
    "InstrumentSummary",
    "InstrumentView",
    "InstrumentsView",
    "KindView",
    "LinkBody",
    "Linked",
    "Logged",
    "LookbackBody",
    "LookbackChange",
    "LookbackView",
    "RegisterBody",
    "RunFileView",
    "RunQuestion",
    "TypedKind",
]
