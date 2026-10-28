"""The instrument registry and each instrument's logbook: what the run files say, remembered.

Domain-agnostic: this module knows instruments, runs, wells and events, never what a run
measured. The domain plugin reads the run files (a run context's ``summary()``, a plain dict)
and supplies the metrics an incident is described by. Everything lives next to the study
workspaces, in a folder whose name is not hex, so the study store never mistakes it for a
study::

    $QPILOT_STUDIES_DIR/instruments/
        instruments.yaml                 the registry: one entry per instrument
        logbook/<instrument_id>.jsonl    hash-chained, append-only, one LogEvent per line
        .lock  logbook/.<instrument_id>.lock

**The registry** (:class:`Registry`) is read with a strict YAML loader (no aliases, no repeated
keys, unknown fields refused, at most 1 MiB). An imported run is linked to its instrument by
:meth:`Registry.resolve`: by the instrument's serial number when the file has one, else by an
identity string seen in an earlier file (an *alias*). A run that resolves to nothing returns
``None``, so the app asks "Which instrument is this?" once (:meth:`Registry.ask`); the answer is
remembered by serial or by alias (:meth:`Registry.remember`), and the next file from that
instrument resolves by itself.

**The logbook** (:class:`Logbook`) is one chain per instrument. Each line's ``hash`` is the
sha256 of the canonical JSON of the event without ``hash`` and without fields that are None
(the proposal chain's rule, so optional fields added later never change old hashes); the first
event links to the sha256 of the instrument id. Appends are serialised by a file lock and refuse
to extend a chain that does not verify; :meth:`Logbook.verify` lists what is wrong and never
raises. Reads stop at a size cap.

Events come from three sources: ``file`` (the file says it: an aborted run, a pause at a
cycle), ``inferred`` (two successive files differ: a calibration date, a block serial, a
firmware version; see :func:`infer_events`) and ``typed`` (a person or an agent entered it).

**Incidents.** An agent may propose an incident; only a person confirms or turns it down
(:func:`confirm_incident`, :func:`reject_incident`), and only a person notes what fixed it
(:func:`log_fix`). The rule is checked again whenever the chain is replayed, so an entry
written around these functions is refused on append and reported by ``verify``.
:func:`match_incidents` is deterministic (no model): a new run's signature is "seen before" when
a confirmed incident on the same instrument shares a well and has the same metric and direction,
or has the same error code.

**What never leaves the machine.** Serial numbers and aliases (an alias is an identity string
from a file and can contain a serial) stay in ``instruments.yaml``; :meth:`Registry.export` and
:meth:`Instrument.public` leave them out, and no event ever stores one (a component change
records which component, not its serial). Text a person types (an incident note, a fix) is
stored exactly as typed, for that person's own screen; :func:`event_view` and
:func:`match_incidents` only count it unless ``include_text=True``, and nothing here passes it
to a model. Callers that hand events to an agent use those defaults.

Research use only: the logbook is a working memory for a lab, not a regulated record.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from filelock import FileLock
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from qpilot.core.store import (
    LOCK_TIMEOUT_S,
    _lines,
    _now,
    atomic_write,
    canonical_json,
    default_studies_dir,
)
from qpilot.schemas import Actor

INSTRUMENTS_DIR = "instruments"
REGISTRY_FILE = "instruments.yaml"
LOGBOOK_DIR = "logbook"
REGISTRY_VERSION = 1

EventKind = Literal[
    "calibration",
    "component_change",
    "firmware_change",
    "software_change",
    "run_event",
    "service",
    "move",
    "incident",
    "fix",
    "note",
    "lookback",
]
Source = Literal["file", "inferred", "typed"]
EVENT_KINDS: tuple[str, ...] = EventKind.__args__  # type: ignore[attr-defined]
SOURCES: tuple[str, ...] = Source.__args__  # type: ignore[attr-defined]
ACTORS = ("human", "agent", "system")
TYPED_KINDS = ("calibration", "component_change", "service", "move", "note")
INCIDENT_ACTIONS = ("log", "confirm", "reject")
INCIDENT_STATUSES = ("proposed", "confirmed", "rejected")

#: Summary keys of the parts that can be replaced, and the component name an event records.
COMPONENTS = {
    "block_serial": "block",
    "cover_serial": "cover",
    "optical_head_serial": "optical_head",
}
#: Run-log event kinds worth an entry (a resume only ends a pause).
RUN_EVENT_KINDS = ("pause", "lid_open", "drawer", "abort", "power")
#: Payload keys that hold text a person typed: stored as typed, only counted in views.
TEXT_KEYS = ("note",)

MAX_REGISTRY_BYTES = 1 << 20
MAX_INSTRUMENTS = 1_000
MAX_LOGBOOK_BYTES = 16 << 20
MAX_EVENT_BYTES = 64 << 10
MAX_TEXT = 2_000
MAX_NAME = 200
MAX_ALIAS = 500
MAX_WELLS = 1_536
MAX_VERSION = 100

INSTRUMENT_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
WELL = re.compile(r"^(?P<row>[A-Z]{1,2})(?P<col>[0-9]{1,3})$")
METRIC = re.compile(r"^[a-z0-9_]{1,64}$")
ERROR_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
RUN_HASH = re.compile(r"^[0-9a-f]{6,64}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

HUMAN_ONLY = "only a person can confirm or turn down an incident, or note what fixed it"
SEEN_BEFORE = "seen before"
QUESTION = "Which instrument is this?"


class InstrumentError(ValueError):
    """A registry or logbook action that is not allowed, malformed, or meets a damaged file."""


class UnknownInstrument(InstrumentError):
    """No instrument with this id is registered."""


class LogbookError(InstrumentError):
    """A logbook that does not verify, is too large, or an event that cannot be written."""


def instruments_root(studies_dir: str | Path | None = None) -> Path:
    """``<studies dir>/instruments``: ``$QPILOT_STUDIES_DIR/instruments`` by default."""
    base = Path(studies_dir) if studies_dir is not None else default_studies_dir()
    return base / INSTRUMENTS_DIR


def suggest_id(display_name: str) -> str:
    """An instrument id made from a display name: ``QS5 – Room 2.110`` -> ``qs5-room-2-110``."""
    out = re.sub(r"[^a-z0-9]+", "-", str(display_name).lower()).strip("-")[:64].strip("-")
    if not out:
        raise InstrumentError(f"cannot make an instrument id from {display_name!r}")
    return out


def _key(text: str) -> str:
    """The form identity strings are compared in: whitespace collapsed, case folded."""
    return " ".join(str(text).split()).casefold()


def _clean_line(value: Any, what: str, limit: int) -> str:
    if type(value) is not str:
        raise InstrumentError(f"{what} must be text")
    out = " ".join(value.split())
    if len(out) > limit:
        raise InstrumentError(f"{what} is longer than {limit} characters")
    return out


def _instant(value: str) -> datetime:
    """An ISO date or date-time as an aware UTC datetime (a date is its midnight, UTC)."""
    if len(value) == 10:
        day = date.fromisoformat(value)
        return datetime(day.year, day.month, day.day, tzinfo=UTC)
    moment = datetime.fromisoformat(value)
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _iso(value: Any, what: str) -> str:
    if type(value) is not str or not value.strip():
        raise InstrumentError(f"{what} must be an ISO date or date-time")
    text = value.strip()
    try:
        _instant(text)
    except ValueError:
        raise InstrumentError(f"{what} {text[:40]!r} is not an ISO date or date-time") from None
    return text


def _require_human(actor: Any) -> None:
    # type() and not isinstance(): a str subclass could answer == "human" for anyone.
    if type(actor) is not str or actor != "human":
        raise InstrumentError(HUMAN_ONLY)


def _require_actor(actor: Any) -> str:
    if type(actor) is not str or actor not in ACTORS:
        raise InstrumentError(f"actor must be one of {', '.join(ACTORS)}")
    return actor


def well_order(well: str) -> tuple[int, str, int]:
    """Sort key for well positions: ``A2`` before ``A10`` before ``B1``."""
    match = WELL.match(well)
    if not match:
        return (9, well, 0)
    return (len(match["row"]), match["row"], int(match["col"]))


# ---- the registry -------------------------------------------------------------------------------


class Instrument(BaseModel):
    """One registered instrument (the spec's ``Instrument`` entity).

    ``aliases`` are identity strings seen in run files and ``serials`` the instrument's serial
    numbers; both are local only (an alias can contain a serial), so :meth:`public` leaves
    them out.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    instrument_id: str
    display_name: str
    make_model: str = ""
    location: str = ""
    shared: bool = False
    aliases: tuple[str, ...] = ()
    serials: tuple[str, ...] = ()

    @field_validator("instrument_id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not INSTRUMENT_ID.match(value):
            raise ValueError(
                "an instrument id is lower-case letters, digits, '-' or '_' (at most 64), "
                "starting with a letter or digit"
            )
        return value

    @field_validator("display_name", "make_model", "location")
    @classmethod
    def _line(cls, value: str) -> str:
        out = " ".join(value.split())
        if len(out) > MAX_NAME:
            raise ValueError(f"longer than {MAX_NAME} characters")
        return out

    @field_validator("display_name")
    @classmethod
    def _named(cls, value: str) -> str:
        if not value:
            raise ValueError("an instrument needs a display name")
        return value

    @field_validator("aliases", "serials")
    @classmethod
    def _strings(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        out: list[str] = []
        for item in value:
            text = " ".join(item.split())
            if not text or len(text) > MAX_ALIAS:
                raise ValueError(f"entries must be 1 to {MAX_ALIAS} characters")
            if _key(text) not in {_key(o) for o in out}:
                out.append(text)
        return tuple(out)

    def public(self) -> dict[str, Any]:
        """The instrument without serials and aliases: what may leave this machine."""
        return self.model_dump(mode="json", exclude={"serials", "aliases"})


class _StrictLoader(yaml.SafeLoader):
    """``yaml.safe_load`` that also refuses aliases and duplicate keys."""

    def compose_node(self, parent, index):
        """Refuse ``*alias`` references (they can multiply a small file's size)."""
        if self.check_event(yaml.AliasEvent):
            mark = self.peek_event().start_mark
            raise InstrumentError(f"line {mark.line + 1}: YAML aliases are not allowed")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        """Refuse a key that appears twice (plain YAML silently keeps the last one)."""
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                line = key_node.start_mark.line + 1
                raise InstrumentError(f"line {line}: key {key!r} appears twice")
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


_HEADER = (
    "# qPilot instrument registry. Serial numbers and aliases stay on this machine:\n"
    "# they are never exported. Quote serial numbers so YAML keeps them as text.\n"
)


def _parse_registry(text: str, where: str) -> dict[str, Instrument]:
    try:
        data = yaml.load(text, Loader=_StrictLoader)  # noqa: S506 (a SafeLoader subclass)
    except yaml.YAMLError as err:
        raise InstrumentError(f"{where}: not valid YAML ({err})") from None
    except TypeError:  # a mapping key YAML cannot hash (a list used as a key)
        raise InstrumentError(f"{where}: a key is not plain text") from None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise InstrumentError(f"{where}: expected a mapping, not {type(data).__name__}")
    unknown = sorted(str(k) for k in data if k not in ("version", "instruments"))
    if unknown:
        raise InstrumentError(f"{where}: unknown field(s) {unknown}; allowed: version, instruments")
    if data.get("version", REGISTRY_VERSION) != REGISTRY_VERSION:
        raise InstrumentError(f"{where}: registry version {data.get('version')!r} is not known")
    entries = data.get("instruments") or {}
    if not isinstance(entries, dict):
        raise InstrumentError(f"{where}: instruments must be a mapping keyed by instrument id")
    if len(entries) > MAX_INSTRUMENTS:
        raise InstrumentError(f"{where}: more than {MAX_INSTRUMENTS} instruments")
    out: dict[str, Instrument] = {}
    for key, fields in entries.items():
        if not isinstance(fields, dict):
            raise InstrumentError(f"{where}: instrument {key!r} must be a mapping")
        if "instrument_id" in fields and fields["instrument_id"] != key:
            raise InstrumentError(f"{where}: instrument {key!r} names a different id")
        try:
            out[str(key)] = Instrument.model_validate({**fields, "instrument_id": key})
        except ValidationError as err:
            item = err.errors()[0]
            field = ".".join(str(x) for x in item.get("loc", ())) or "instrument"
            raise InstrumentError(
                f"{where}: instrument {key!r}, {field}: {item.get('msg', 'invalid')}"
            ) from None
    _check_unique(out.values())
    return out


def _check_unique(instruments: Iterable[Instrument]) -> None:
    """A serial or alias names one instrument only."""
    owner: dict[tuple[str, str], str] = {}
    for inst in instruments:
        for what, values in (("serial", inst.serials), ("alias", inst.aliases)):
            for value in values:
                slot = (what, _key(value))
                if slot in owner and owner[slot] != inst.instrument_id:
                    raise InstrumentError(
                        f"one {what} is given to two instruments "
                        f"({owner[slot]} and {inst.instrument_id})"
                    )
                owner[slot] = inst.instrument_id


class Registry:
    """The instruments of this machine's lab (``instruments.yaml``).

    ``Registry()`` opens ``$QPILOT_STUDIES_DIR/instruments``; ``Registry(root)`` opens another
    folder. Every write re-reads the file under the lock, so two processes never lose each
    other's entries.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else instruments_root()
        self.path = self.root / REGISTRY_FILE

    # ---- reading --------------------------------------------------------------------------

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.root / ".lock"), timeout=LOCK_TIMEOUT_S):
            yield

    def _read(self) -> dict[str, Instrument]:
        if not self.path.exists():
            return {}
        size = self.path.stat().st_size
        if size > MAX_REGISTRY_BYTES:
            raise InstrumentError(
                f"{REGISTRY_FILE} is {size:,} bytes; the limit is {MAX_REGISTRY_BYTES:,}"
            )
        try:
            text = self.path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as err:
            raise InstrumentError(f"{REGISTRY_FILE} is not UTF-8 text") from err
        return _parse_registry(text, REGISTRY_FILE)

    def load(self) -> dict[str, Instrument]:
        """Every registered instrument by id (strict reading; :class:`InstrumentError` if bad)."""
        return self._read()

    def instruments(self) -> list[Instrument]:
        """Every registered instrument, sorted by id."""
        return [inst for _, inst in sorted(self._read().items())]

    def get(self, instrument_id: str) -> Instrument:
        """One instrument; :class:`UnknownInstrument` if it is not registered."""
        found = self._read().get(instrument_id) if isinstance(instrument_id, str) else None
        if found is None:
            raise UnknownInstrument(f"no instrument {instrument_id!r} is registered")
        return found

    def export(self) -> list[dict[str, Any]]:
        """Every instrument without serials and aliases (safe to share or show a model)."""
        return [inst.public() for inst in self.instruments()]

    # ---- writing --------------------------------------------------------------------------

    def save(self, instruments: Mapping[str, Instrument] | Iterable[Instrument]) -> None:
        """Replace the registry with these instruments (deterministic YAML, atomic write)."""
        values = instruments.values() if isinstance(instruments, Mapping) else instruments
        with self._locked():
            self._write({inst.instrument_id: inst for inst in values})

    def _write(self, instruments: Mapping[str, Instrument]) -> None:
        _check_unique(instruments.values())
        entries = {
            iid: inst.model_dump(mode="json", exclude={"instrument_id"})
            for iid, inst in sorted(instruments.items())
        }
        text = _HEADER + yaml.safe_dump(
            {"version": REGISTRY_VERSION, "instruments": entries},
            sort_keys=True,
            allow_unicode=True,
            default_flow_style=False,
        )
        if _parse_registry(text, REGISTRY_FILE) != dict(instruments):
            raise InstrumentError("the registry would not read back as written")
        atomic_write(self.path, text)

    def _change(self, change: Callable[[dict[str, Instrument]], Instrument]) -> Instrument:
        with self._locked():
            current = self._read()
            out = change(current)
            current[out.instrument_id] = out
            self._write(current)
            return out

    def register(
        self,
        instrument_id: str,
        display_name: str,
        *,
        make_model: str = "",
        location: str = "",
        shared: bool = False,
        aliases: Sequence[str] = (),
        serials: Sequence[str] = (),
    ) -> Instrument:
        """Add an instrument once: a friendly name, model, location and the shared flag.

        Raises:
            InstrumentError: The id is malformed or taken, or a serial or alias already
                names another instrument.
        """
        try:
            new = Instrument(
                instrument_id=instrument_id,
                display_name=display_name,
                make_model=make_model,
                location=location,
                shared=shared,
                aliases=tuple(aliases),
                serials=tuple(serials),
            )
        except ValidationError as err:
            item = err.errors()[0]
            field = ".".join(str(x) for x in item.get("loc", ())) or "instrument"
            raise InstrumentError(f"{field}: {item.get('msg', 'invalid')}") from None

        def change(current: dict[str, Instrument]) -> Instrument:
            if new.instrument_id in current:
                raise InstrumentError(f"instrument {new.instrument_id!r} is already registered")
            _check_unique([*current.values(), new])
            return new

        return self._change(change)

    def update(
        self,
        instrument_id: str,
        *,
        display_name: str | None = None,
        make_model: str | None = None,
        location: str | None = None,
        shared: bool | None = None,
    ) -> Instrument:
        """Change an instrument's name, model, location or shared flag (serials stay)."""
        fields = {
            k: v
            for k, v in (
                ("display_name", display_name),
                ("make_model", make_model),
                ("location", location),
                ("shared", shared),
            )
            if v is not None
        }

        def change(current: dict[str, Instrument]) -> Instrument:
            old = current.get(instrument_id)
            if old is None:
                raise UnknownInstrument(f"no instrument {instrument_id!r} is registered")
            try:
                return Instrument.model_validate({**old.model_dump(), **fields})
            except ValidationError as err:
                raise InstrumentError(err.errors()[0].get("msg", "invalid")) from None

        return self._change(change)

    def _remember(self, what: str, value: Any, instrument_id: str) -> Instrument:
        text = _clean_line(value, what, MAX_ALIAS)
        if not text:
            raise InstrumentError(f"an empty {what} cannot name an instrument")
        field = "serials" if what == "serial" else "aliases"

        def change(current: dict[str, Instrument]) -> Instrument:
            inst = current.get(instrument_id)
            if inst is None:
                raise UnknownInstrument(f"no instrument {instrument_id!r} is registered")
            for other in current.values():
                held = {_key(v) for v in getattr(other, field)}
                if other.instrument_id != instrument_id and _key(text) in held:
                    raise InstrumentError(
                        f"this {what} already names instrument {other.instrument_id!r}"
                    )
            values = getattr(inst, field)
            if _key(text) in {_key(v) for v in values}:
                return inst
            return inst.model_copy(update={field: (*values, text)})

        return self._change(change)

    def remember_alias(self, alias: str, instrument_id: str) -> Instrument:
        """Remember that files carrying this identity string come from this instrument."""
        return self._remember("alias", alias, instrument_id)

    def remember_serial(self, serial: str, instrument_id: str) -> Instrument:
        """Remember a serial number of this instrument (local only)."""
        return self._remember("serial", serial, instrument_id)

    def remember(self, summary: Mapping[str, Any], instrument_id: str) -> Instrument:
        """Record a person's answer to "Which instrument is this?" for a run summary.

        The file's serial is remembered when it has one; otherwise every identity string it
        carries becomes an alias, so the next file like it resolves without asking.
        """
        info = _summary(summary)
        inst = self.get(instrument_id)
        if info["serial"]:
            inst = self.remember_serial(info["serial"], instrument_id)
        else:
            if not info["aliases"]:
                raise InstrumentError(
                    "this file has neither a serial number nor an identity string to remember"
                )
            for alias in info["aliases"]:
                inst = self.remember_alias(alias, instrument_id)
        return inst

    # ---- linking runs ---------------------------------------------------------------------

    def resolve(self, summary: Mapping[str, Any]) -> str | None:
        """The instrument a run summary comes from, or None when qPilot must ask.

        A file with a serial resolves by that serial only (an unknown serial is a new
        instrument, whatever its model string says); a file without one resolves by an alias
        it carries. Never a guess: no match, or aliases of two instruments, gives None.
        """
        info = _summary(summary)
        instruments = self._read().values()
        if info["serial"]:
            wanted = _key(info["serial"])
            hits = {i.instrument_id for i in instruments if wanted in map(_key, i.serials)}
        else:
            seen = {_key(a) for a in info["aliases"]}
            hits = {i.instrument_id for i in instruments if seen & set(map(_key, i.aliases))}
        return hits.pop() if len(hits) == 1 else None

    def ask(self, summary: Mapping[str, Any]) -> dict[str, Any] | None:
        """The one question the app shows for a run that does not resolve, else None.

        Returns ``{"question", "reason", "choices"}``: ``reason`` is ``unknown_serial`` or
        ``no_serial``; ``choices`` are the registered instruments (no serials, no aliases).
        """
        if self.resolve(summary) is not None:
            return None
        info = _summary(summary)
        return {
            "question": QUESTION,
            "reason": "unknown_serial" if info["serial"] else "no_serial",
            "choices": [
                {"instrument_id": i["instrument_id"], "display_name": i["display_name"]}
                for i in self.export()
            ],
        }

    def logbook(self, instrument_id: str) -> Logbook:
        """The logbook of a registered instrument."""
        self.get(instrument_id)
        return Logbook(instrument_id, self.root)


def _summary(summary: Mapping[str, Any] | None) -> dict[str, Any]:
    """The run-summary keys this module reads, checked; missing keys read as None."""
    if summary is None:
        return {}
    if not isinstance(summary, Mapping):
        raise InstrumentError("a run summary is a mapping (the run context's summary())")

    def text(key: str, limit: int = MAX_ALIAS) -> str | None:
        value = summary.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise InstrumentError(f"run summary: {key} must be text")
        value = _CONTROL.sub(" ", value).strip()
        return value[:limit] or None

    out: dict[str, Any] = {k: text(k) for k in ("serial", *COMPONENTS)}
    for key in ("firmware", "software", "run_state", "run_start", "run_end", "model"):
        out[key] = text(key, MAX_VERSION)
    aliases = summary.get("aliases") or []
    if not isinstance(aliases, list | tuple) or not all(isinstance(a, str) for a in aliases):
        raise InstrumentError("run summary: aliases must be a list of text")
    out["aliases"] = [" ".join(a.split()) for a in aliases if a.strip()][:50]
    calibrations = summary.get("calibrations") or {}
    if not isinstance(calibrations, Mapping):
        raise InstrumentError("run summary: calibrations must be a mapping by type")
    out["calibrations"] = {
        str(k)[:MAX_VERSION]: dict(v) if isinstance(v, Mapping) else {}
        for k, v in calibrations.items()
    }
    events = summary.get("events") or []
    if not isinstance(events, list | tuple):
        raise InstrumentError("run summary: events must be a list")
    out["events"] = [dict(e) for e in events if isinstance(e, Mapping)]
    return out


# ---- events and the chain -------------------------------------------------------------------


class Signature(BaseModel):
    """What an incident, or a new run, looks like: metric, direction, error code, numbers.

    ``metric`` is the plugin's name for what was measured (``plateau``, ``cq_residual``),
    ``direction`` whether it was low or high, ``error_code`` a vendor flag or message code
    (``PRFDROP``) and ``numbers`` the values qPilot attached. No free text.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    metric: str | None = None
    direction: Literal["low", "high"] | None = None
    error_code: str | None = None
    numbers: dict[str, float] = Field(default_factory=dict)

    @field_validator("metric")
    @classmethod
    def _metric(cls, value: str | None) -> str | None:
        if value is not None and not METRIC.match(value):
            raise ValueError("a metric is lower-case letters, digits and '_' (at most 64)")
        return value

    @field_validator("error_code")
    @classmethod
    def _code(cls, value: str | None) -> str | None:
        if value is not None and not ERROR_CODE.match(value):
            raise ValueError("an error code is letters, digits and _ . : - (at most 64)")
        return value

    @field_validator("numbers")
    @classmethod
    def _numbers(cls, value: dict[str, float]) -> dict[str, float]:
        if len(value) > 50 or not all(METRIC.match(k) for k in value):
            raise ValueError("at most 50 numbers, keyed like a metric")
        if not all(math.isfinite(v) for v in value.values()):
            raise ValueError("numbers must be finite")
        return value


class LogEvent(BaseModel):
    """One line of ``logbook/<instrument_id>.jsonl`` (the spec's ``Event``), hash-chained.

    ``at`` is when it happened, when known (an inferred change is dated by the run that
    showed it); ``recorded_at`` is when qPilot wrote it. ``run_hash`` names the run file (its
    sha256 or a prefix of it), ``wells`` the positions concerned.
    """

    model_config = ConfigDict(extra="forbid")

    seq: int
    prev_hash: str
    instrument_id: str
    kind: EventKind
    source: Source
    actor: Actor
    at: str | None = None
    recorded_at: str
    run_hash: str | None = None
    wells: tuple[str, ...] | None = None
    signature: Signature | None = None
    payload: dict[str, Any] | None = None
    hash: str = ""

    def when(self) -> datetime:
        """When it happened if known, else when it was recorded (aware, UTC)."""
        return _instant(self.at or self.recorded_at)


def chain_root(instrument_id: str) -> str:
    """The first ``prev_hash`` of an instrument's logbook: sha256 of its id."""
    return hashlib.sha256(instrument_id.encode("utf-8")).hexdigest()


def event_hash(event: LogEvent) -> str:
    """sha256 of the event's canonical JSON without ``hash`` and without None fields."""
    data = event.model_dump(mode="json", exclude={"hash"}, exclude_none=True)
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def canonical_line(event: LogEvent) -> str:
    """The exact line an event is stored as (no trailing newline)."""
    return canonical_json(event.model_dump(mode="json", exclude_none=True))


def verify_chain(events: Sequence[LogEvent], root: str) -> int | None:
    """The ``seq`` of the first event whose link or hash is wrong, or None if intact."""
    prev = root
    for position, event in enumerate(events, start=1):
        if event.seq != position or event.prev_hash != prev or event.hash != event_hash(event):
            return position
        prev = event.hash
    return None


def first_altered_line(lines: Sequence[str], events: Sequence[LogEvent]) -> int | None:
    """The first line whose bytes are not the canonical form of the event it parses to."""
    for position, (line, event) in enumerate(zip(lines, events, strict=False), start=1):
        if line != canonical_line(event):
            return position
    return None


def _plain(value: Any, what: str) -> Any:
    """``value`` as plain JSON (no NaN, no infinities), or :class:`LogbookError`."""
    try:
        return json.loads(json.dumps(value, allow_nan=False, ensure_ascii=False))
    except (TypeError, ValueError):
        raise LogbookError(f"{what} must be plain JSON (text, numbers, lists, mappings)") from None


class Incident(BaseModel):
    """An incident rebuilt from the chain: what was logged, its status and its fixes."""

    seq: int
    at: str | None
    recorded_at: str
    actor: Actor
    run_hash: str | None = None
    wells: tuple[str, ...] = ()
    signature: Signature = Field(default_factory=Signature)
    status: Literal["proposed", "confirmed", "rejected"]
    decided_seq: int | None = None
    note: str = ""
    fixes: list[dict[str, Any]] = Field(default_factory=list)


def _linked(found: Mapping[int, Incident], payload: Mapping[str, Any]) -> Incident | None:
    """The incident an entry links to by number (``True`` is not entry 1)."""
    ref = payload.get("incident")
    return found.get(ref) if type(ref) is int else None


def _replay(events: Sequence[LogEvent]) -> tuple[dict[int, Incident], list[str]]:
    """Incidents by seq and the rule problems of a chain (who confirmed, what was linked)."""
    found: dict[int, Incident] = {}
    problems: list[str] = []
    for event in events:
        payload = event.payload or {}
        where = f"entry {event.seq}"
        if event.kind == "incident":
            action = payload.get("action")
            if action == "log":
                expected = "confirmed" if event.actor == "human" else "proposed"
                if payload.get("status") != expected:
                    problems.append(f"{where}: an incident by {event.actor} must be {expected}")
                    continue
                found[event.seq] = Incident(
                    seq=event.seq,
                    at=event.at,
                    recorded_at=event.recorded_at,
                    actor=event.actor,
                    run_hash=event.run_hash,
                    wells=event.wells or (),
                    signature=event.signature or Signature(),
                    status=expected,
                    decided_seq=event.seq if expected == "confirmed" else None,
                    note=payload.get("note", ""),
                )
            elif action in ("confirm", "reject"):
                target = _linked(found, payload)
                if event.actor != "human":
                    problems.append(f"{where}: {HUMAN_ONLY}")
                elif target is None:
                    problems.append(f"{where}: no incident {payload.get('incident')!r} to decide")
                elif target.status != "proposed":
                    problems.append(f"{where}: incident {target.seq} is already {target.status}")
                else:
                    status = "confirmed" if action == "confirm" else "rejected"
                    found[target.seq] = target.model_copy(
                        update={"status": status, "decided_seq": event.seq}
                    )
            else:
                problems.append(f"{where}: unknown incident action {action!r}")
        elif event.kind == "fix":
            target = _linked(found, payload)
            if event.actor != "human":
                problems.append(f"{where}: {HUMAN_ONLY}")
            elif target is None or target.status == "rejected":
                problems.append(f"{where}: no open incident {payload.get('incident')!r} to fix")
            else:
                fix = {"seq": event.seq, "at": event.at, "note": payload.get("note", "")}
                found[target.seq] = target.model_copy(update={"fixes": [*target.fixes, fix]})
    return found, problems


class Logbook:
    """One instrument's logbook: append-only, hash-chained, size-capped, lock-serialised.

    ``Logbook(instrument_id)`` opens ``$QPILOT_STUDIES_DIR/instruments/logbook/<id>.jsonl``;
    ``Logbook(instrument_id, root)`` opens it under another instruments folder. The logbook
    does not require the instrument to be registered (:meth:`Registry.logbook` does).
    """

    def __init__(self, instrument_id: str, root: str | Path | None = None) -> None:
        if not isinstance(instrument_id, str) or not INSTRUMENT_ID.match(instrument_id):
            raise InstrumentError(f"not an instrument id: {instrument_id!r}")
        self.instrument_id = instrument_id
        self.root = Path(root) if root is not None else instruments_root()
        self.folder = self.root / LOGBOOK_DIR
        self.path = self.folder / f"{instrument_id}.jsonl"
        self.chain_root = chain_root(instrument_id)

    # ---- reading --------------------------------------------------------------------------

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.folder.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.folder / f".{self.instrument_id}.lock"), timeout=LOCK_TIMEOUT_S):
            yield

    def _scan(self) -> tuple[list[LogEvent], list[str]]:
        """Every event and every problem; never raises for a bad file."""
        if not self.path.exists():
            return [], []
        size = self.path.stat().st_size
        if size > MAX_LOGBOOK_BYTES:
            return [], [f"the logbook is {size:,} bytes; the limit is {MAX_LOGBOOK_BYTES:,}"]
        try:
            lines = [line for line in _lines(self.path) if line.strip()]
        except UnicodeDecodeError:
            return [], ["the logbook is not UTF-8 text"]
        events: list[LogEvent] = []
        for position, line in enumerate(lines, start=1):
            if len(line.encode("utf-8")) > MAX_EVENT_BYTES:
                return events, [f"entry {position} is larger than {MAX_EVENT_BYTES:,} bytes"]
            try:
                events.append(LogEvent.model_validate_json(line))
            except (ValueError, RecursionError):
                return events, [f"entry {position} cannot be read"]
        problems = []
        broken = verify_chain(events, self.chain_root)
        if broken is None:
            broken = first_altered_line(lines, events)
        if broken is not None:
            problems.append(f"the chain does not verify at entry {broken}")
        other = [e.seq for e in events if e.instrument_id != self.instrument_id]
        if other:
            problems.append(f"entry {other[0]} belongs to another instrument")
        problems += _replay(events)[1]
        return events, problems

    def _load(self) -> list[LogEvent]:
        events, problems = self._scan()
        if problems:
            raise LogbookError(f"the logbook of {self.instrument_id}: {problems[0]}")
        return events

    def verify(self) -> list[str]:
        """What is wrong with this logbook (an empty list when it verifies); never raises."""
        try:
            if not self.path.exists():
                return []
            with self._locked():
                return self._scan()[1]
        except Exception as err:  # verify reports, never raises
            return [f"the logbook cannot be read ({type(err).__name__})"]

    def events(
        self, kinds: Iterable[str] | None = None, since: str | None = None
    ) -> list[LogEvent]:
        """Events in chain order, optionally of some kinds and on or after ``since``.

        Raises:
            LogbookError: The logbook does not verify or is over the size cap.
        """
        wanted = set(kinds) if kinds is not None else None
        if wanted is not None and wanted - set(EVENT_KINDS):
            raise InstrumentError(f"unknown event kind(s): {sorted(wanted - set(EVENT_KINDS))}")
        start = _instant(_iso(since, "since")) if since is not None else None
        if not self.path.exists():
            return []
        with self._locked():
            events = self._load()
        return [
            e
            for e in events
            if (wanted is None or e.kind in wanted) and (start is None or e.when() >= start)
        ]

    def head(self) -> str:
        """Hash of the latest event, or the chain root when the logbook is empty."""
        events = self.events()
        return events[-1].hash if events else self.chain_root

    def incidents(self) -> list[Incident]:
        """Every incident with its present status and fixes, oldest first."""
        found, _ = _replay(self.events())
        return [found[seq] for seq in sorted(found)]

    # ---- writing --------------------------------------------------------------------------

    def append(self, event: Mapping[str, Any]) -> LogEvent:
        """Append one event and return it as written.

        ``event`` has ``kind``, ``source`` and ``actor``, and optionally ``at``, ``run_hash``,
        ``wells``, ``signature`` and ``payload``.

        Raises:
            LogbookError: The event is malformed or breaks a rule (an agent confirming an
                incident), or the logbook does not verify.
        """
        return self.append_many([event])[0]

    def append_many(self, events: Sequence[Mapping[str, Any]]) -> list[LogEvent]:
        """Append several events in one locked write (all or none)."""
        return self._append(lambda _current: list(events))

    def _append(
        self, build: Callable[[list[LogEvent]], Sequence[Mapping[str, Any]]]
    ) -> list[LogEvent]:
        """Under the lock: read and verify, let ``build`` see the chain, write what it returns."""
        with self._locked():
            current = self._load()
            fresh = list(build(list(current)))
            if not fresh:
                return []
            written: list[LogEvent] = []
            recorded = _now()
            for spec in fresh:
                written.append(self._event(spec, [*current, *written], recorded))
            _, problems = _replay([*current, *written])
            if problems:
                raise LogbookError(f"refusing to write: {problems[0]}")
            text = "".join(canonical_line(e) + "\n" for e in written)
            size = self.path.stat().st_size if self.path.exists() else 0
            if size + len(text.encode("utf-8")) > MAX_LOGBOOK_BYTES:
                raise LogbookError(f"the logbook would pass its {MAX_LOGBOOK_BYTES:,}-byte limit")
            with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            return written

    def _event(self, spec: Mapping[str, Any], chain: list[LogEvent], recorded: str) -> LogEvent:
        if not isinstance(spec, Mapping):
            raise LogbookError("an event is a mapping")
        allowed = {"kind", "source", "actor", "at", "run_hash", "wells", "signature", "payload"}
        unknown = sorted(str(k) for k in spec if k not in allowed)
        if unknown:
            raise LogbookError(f"unknown event field(s) {unknown}")
        _require_actor(spec.get("actor"))
        at = spec.get("at")
        run_hash = spec.get("run_hash")
        if run_hash is not None and (type(run_hash) is not str or not RUN_HASH.match(run_hash)):
            raise LogbookError("run_hash must be a run file's sha256 (lower-case hex)")
        wells = _wells(spec.get("wells"))
        payload = spec.get("payload")
        if payload is not None:
            if not isinstance(payload, Mapping):
                raise LogbookError("payload must be a mapping")
            payload = _plain(dict(payload), "payload")
            for key in TEXT_KEYS:
                if key in payload and (
                    type(payload[key]) is not str or len(payload[key]) > MAX_TEXT
                ):
                    raise LogbookError(f"{key} must be text of at most {MAX_TEXT} characters")
        try:
            event = LogEvent(
                seq=len(chain) + 1,
                prev_hash=chain[-1].hash if chain else self.chain_root,
                instrument_id=self.instrument_id,
                kind=spec.get("kind"),  # type: ignore[arg-type]
                source=spec.get("source"),  # type: ignore[arg-type]
                actor=spec.get("actor"),  # type: ignore[arg-type]
                at=_iso(at, "at") if at is not None else None,
                recorded_at=recorded,
                run_hash=run_hash,
                wells=wells,
                signature=spec.get("signature"),  # type: ignore[arg-type]
                payload=payload or None,
            )
        except ValidationError as err:
            item = err.errors()[0]
            field = ".".join(str(x) for x in item.get("loc", ())) or "event"
            raise LogbookError(f"{field}: {item.get('msg', 'invalid')}") from None
        event = event.model_copy(update={"hash": event_hash(event)})
        line = canonical_line(event)
        if len(line.encode("utf-8")) > MAX_EVENT_BYTES:
            raise LogbookError(f"an event is larger than {MAX_EVENT_BYTES:,} bytes")
        again = LogEvent.model_validate_json(line)
        if canonical_line(again) != line or event_hash(again) != event.hash:
            raise LogbookError("this event would not read back as written")
        return again


def _wells(value: Any) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise LogbookError("wells must be a list of positions such as A1")
    wells = list(value)
    if len(wells) > MAX_WELLS:
        raise LogbookError(f"at most {MAX_WELLS:,} wells")
    if not all(isinstance(w, str) and WELL.match(w) for w in wells):
        raise LogbookError("wells must be positions such as A1 or P24")
    return tuple(sorted(set(wells), key=well_order)) or None


# ---- inferred events ----------------------------------------------------------------------------


def infer_events(previous: Mapping[str, Any] | None, current: Mapping[str, Any]) -> list[dict]:
    """The events two successive run summaries of one instrument show, with no typing.

    ``previous`` is the summary of the instrument's latest earlier run (None for its first
    run); both are run-context ``summary()`` dicts. Inferred (``source="inferred"``):

    * a calibration whose ``performed_on`` date changed -> ``calibration`` (dated by the new
      calibration date);
    * a block, cover or optical-head serial that changed -> ``component_change`` (the payload
      names the component, never a serial);
    * a firmware or software version that changed -> ``firmware_change`` / ``software_change``.

    From the current file alone (``source="file"``): a run state other than complete, and each
    pause, lid or drawer opening, abort or power event -> ``run_event`` (with its cycle).
    A value missing from either file infers nothing. The returned dicts carry ``kind``,
    ``source``, ``actor`` (``system``), ``at`` and ``payload``; add ``run_hash`` and append.

    Raises:
        InstrumentError: The two summaries carry different instrument serials.
    """
    cur = _summary(current)
    prev = _summary(previous) if previous is not None else None
    if prev and prev["serial"] and cur["serial"] and _key(prev["serial"]) != _key(cur["serial"]):
        raise InstrumentError("these two runs are from different instruments (serials differ)")
    at = _date_or_none(cur["run_start"]) or _date_or_none(cur["run_end"])
    out: list[dict] = []

    def add(kind: str, source: str, payload: dict[str, Any], when: str | None = at) -> None:
        out.append(
            {"kind": kind, "source": source, "actor": "system", "at": when, "payload": payload}
        )

    if prev is not None:
        for ctype in sorted(cur["calibrations"]):
            new = _date_or_none(cur["calibrations"][ctype].get("performed_on"))
            old = _date_or_none(prev["calibrations"].get(ctype, {}).get("performed_on"))
            if new and old and new != old:
                add("calibration", "inferred", {"type": ctype, "performed_on": new}, new)
        for key, component in COMPONENTS.items():
            if cur[key] and prev[key] and _key(cur[key]) != _key(prev[key]):
                add("component_change", "inferred", {"component": component})
        for key, kind in (("firmware", "firmware_change"), ("software", "software_change")):
            if cur[key] and prev[key] and cur[key] != prev[key]:
                add(kind, "inferred", {"from": prev[key], "to": cur[key]})
    events = cur["events"]
    state = cur["run_state"]
    if state and state.casefold() != "complete":
        if not (state.casefold() == "aborted" and any(e.get("kind") == "abort" for e in events)):
            add("run_event", "file", {"what": "run_state", "state": state.casefold()})
    for item in events:
        kind = item.get("kind")
        if kind in RUN_EVENT_KINDS:
            cycle = item.get("cycle")
            payload: dict[str, Any] = {"what": kind}
            if isinstance(cycle, int) and not isinstance(cycle, bool):
                payload["cycle"] = cycle
            add("run_event", "file", payload)
    return out


def _date_or_none(value: Any) -> str | None:
    """An ISO date or date-time string as given, or None when absent or unreadable."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        _instant(value.strip())
    except ValueError:
        return None
    return value.strip()


# ---- typed events and incidents -----------------------------------------------------------------


def _note(note: Any) -> str:
    """Text a person or an agent typed: kept exactly as typed, within the size cap."""
    if note is None:
        return ""
    if type(note) is not str:
        raise InstrumentError("a note must be text")
    if len(note) > MAX_TEXT:
        raise InstrumentError(f"a note is longer than {MAX_TEXT} characters")
    return note


def log_typed(
    logbook: Logbook,
    kind: str,
    *,
    actor: str = "human",
    note: str = "",
    at: str | None = None,
    run_hash: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> LogEvent:
    """A one-line typed event: a service visit, a move, a calibration, a lamp change, a note."""
    if kind not in TYPED_KINDS:
        raise InstrumentError(f"a typed event is one of {', '.join(TYPED_KINDS)}")
    _require_actor(actor)
    body = dict(payload or {})
    if note:
        body["note"] = _note(note)
    return logbook.append(
        {
            "kind": kind,
            "source": "typed",
            "actor": actor,
            "at": at,
            "run_hash": run_hash,
            "payload": body or None,
        }
    )


def log_incident(
    logbook: Logbook,
    *,
    actor: str,
    wells: Sequence[str] = (),
    signature: Mapping[str, Any] | Signature | None = None,
    run_hash: str | None = None,
    note: str = "",
    at: str | None = None,
) -> LogEvent:
    """Log an incident on a run's wells: confirmed when a person logs it, proposed otherwise.

    qPilot attaches the instrument, run, wells and signature; ``note`` is what the person (or
    the proposing agent) saw, stored as typed. An agent's incident waits, ``proposed``, until a
    person confirms it; :func:`match_incidents` reads confirmed incidents only.
    """
    _require_actor(actor)
    if isinstance(wells, str):
        raise InstrumentError("wells must be a list of positions such as A1")
    status = "confirmed" if actor == "human" else "proposed"
    if isinstance(signature, Signature):
        signature = signature.model_dump(exclude_none=True)
    payload: dict[str, Any] = {"action": "log", "status": status}
    if note:
        payload["note"] = _note(note)
    return logbook.append(
        {
            "kind": "incident",
            "source": "typed",
            "actor": actor,
            "at": at,
            "run_hash": run_hash,
            "wells": list(wells) or None,
            "signature": dict(signature) if signature else None,
            "payload": payload,
        }
    )


def _decide(logbook: Logbook, incident: int, action: str, actor: Any) -> LogEvent:
    _require_human(actor)
    if type(incident) is not int:
        raise InstrumentError("an incident is named by its entry number")

    def build(current: list[LogEvent]) -> list[dict]:
        found, _ = _replay(current)
        target = found.get(incident)
        if target is None:
            raise InstrumentError(f"no incident at entry {incident}")
        if target.status != "proposed":
            raise InstrumentError(f"incident {incident} is already {target.status}")
        payload = {"action": action, "incident": incident}
        return [{"kind": "incident", "source": "typed", "actor": "human", "payload": payload}]

    return logbook._append(build)[0]


def confirm_incident(logbook: Logbook, incident: int, *, actor: str) -> LogEvent:
    """A person confirms a proposed incident (any other actor is refused before any read)."""
    return _decide(logbook, incident, "confirm", actor)


def reject_incident(logbook: Logbook, incident: int, *, actor: str) -> LogEvent:
    """A person turns down a proposed incident (any other actor is refused)."""
    return _decide(logbook, incident, "reject", actor)


def log_fix(
    logbook: Logbook, incident: int, *, note: str, actor: str, at: str | None = None
) -> LogEvent:
    """A person notes what fixed an incident; the note is stored as typed, linked by entry."""
    _require_human(actor)
    text = _note(note)
    if not text.strip():
        raise InstrumentError("say what fixed it")
    if type(incident) is not int:
        raise InstrumentError("an incident is named by its entry number")

    def build(current: list[LogEvent]) -> list[dict]:
        found, _ = _replay(current)
        if incident not in found or found[incident].status == "rejected":
            raise InstrumentError(f"no open incident at entry {incident}")
        payload = {"incident": incident, "note": text}
        return [{"kind": "fix", "source": "typed", "actor": "human", "at": at, "payload": payload}]

    return logbook._append(build)[0]


def _query(signature: Mapping[str, Any] | Signature) -> tuple[str | None, set[str], Signature]:
    if isinstance(signature, Signature):
        return None, set(), signature
    if not isinstance(signature, Mapping):
        raise InstrumentError("a signature is a mapping")
    data = dict(signature)
    instrument = data.pop("instrument_id", None)
    wells = _wells(data.pop("wells", None)) or ()
    try:
        return instrument, set(wells), Signature.model_validate(data)
    except ValidationError as err:
        raise InstrumentError(err.errors()[0].get("msg", "invalid signature")) from None


def match_incidents(
    logbook: Logbook,
    signature: Mapping[str, Any] | Signature,
    *,
    include_text: bool = False,
) -> list[dict[str, Any]]:
    """Confirmed incidents a new run's signature has "seen before", most recent first.

    ``signature`` has ``wells``, ``metric``, ``direction`` and ``error_code`` (and optionally
    ``instrument_id``: another instrument's run matches nothing here). A match is the same
    instrument and either an overlapping well with the same metric and direction, or the same
    error code. Deterministic, no model. The typed notes (what was seen, what fixed it) are
    included only with ``include_text=True``, for a person's screen; never pass them to a
    model.
    """
    instrument, wells, query = _query(signature)
    if instrument is not None and instrument != logbook.instrument_id:
        return []
    out = []
    for inc in logbook.incidents():
        if inc.status != "confirmed":
            continue
        sig = inc.signature
        overlap = sorted(wells & set(inc.wells), key=well_order)
        matched_on = []
        if overlap and sig.metric and sig.metric == query.metric:
            if sig.direction == query.direction:
                matched_on.append("wells_metric_direction")
        if sig.error_code and query.error_code and _key(sig.error_code) == _key(query.error_code):
            matched_on.append("error_code")
        if not matched_on:
            continue
        record: dict[str, Any] = {
            "words": SEEN_BEFORE,
            "incident": inc.seq,
            "at": inc.at or inc.recorded_at,
            "instrument_id": logbook.instrument_id,
            "wells": overlap,
            "incident_wells": list(inc.wells),
            "metric": sig.metric,
            "direction": sig.direction,
            "error_code": sig.error_code,
            "matched_on": matched_on,
            "fixed": bool(inc.fixes),
            "fixes": [{"seq": f["seq"], "at": f["at"]} for f in inc.fixes],
            "note_chars": len(inc.note),
        }
        if include_text:
            record["note"] = inc.note
            record["fixes"] = [dict(f) for f in inc.fixes]
        out.append(record)
    return sorted(out, key=lambda r: (_instant(r["at"]), r["incident"]), reverse=True)


def event_view(event: LogEvent, *, include_text: bool = False) -> dict[str, Any]:
    """An event as plain data; typed text is replaced by its length unless ``include_text``."""
    data = event.model_dump(mode="json", exclude_none=True)
    payload = data.get("payload")
    if payload and not include_text:
        for key in TEXT_KEYS:
            if key in payload:
                payload[f"{key}_chars"] = len(payload.pop(key))
    return data


def proposed_window(logbook: Logbook, incident: int) -> tuple[str, str]:
    """A lookback window to propose for an incident: last clean evidence -> fix.

    The start is the latest calibration or service entry before the incident (else the
    incident's own date); the end is its first fix (else the incident's date). A proposal for
    a person to edit, never applied on its own.
    """
    events = logbook.events()
    found, _ = _replay(events)
    inc = found.get(incident)
    if inc is None:
        raise InstrumentError(f"no incident at entry {incident}")
    when = _instant(inc.at or inc.recorded_at)
    clean = [
        e
        for e in events
        if e.seq < inc.seq and e.kind in ("calibration", "service") and e.when() <= when
    ]
    start = max(clean, key=lambda e: (e.when(), e.seq)).when() if clean else when
    fixes = [_instant(f["at"]) if f["at"] else None for f in inc.fixes]
    ends = [f for f in fixes if f is not None]
    end = min(ends) if ends else when
    return start.date().isoformat(), max(end, start).date().isoformat()


__all__ = [
    "EVENT_KINDS",
    "INSTRUMENTS_DIR",
    "QUESTION",
    "SEEN_BEFORE",
    "SOURCES",
    "Incident",
    "Instrument",
    "InstrumentError",
    "LogEvent",
    "Logbook",
    "LogbookError",
    "Registry",
    "Signature",
    "UnknownInstrument",
    "canonical_line",
    "chain_root",
    "confirm_incident",
    "event_hash",
    "event_view",
    "first_altered_line",
    "infer_events",
    "instruments_root",
    "log_fix",
    "log_incident",
    "log_typed",
    "match_incidents",
    "proposed_window",
    "reject_incident",
    "suggest_id",
    "verify_chain",
    "well_order",
]
