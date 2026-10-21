r"""What the run file says about the instrument: identity, run, calibrations and events.

The instrument writes much of its own record into the run file: which instrument and which block
ran the plate, when each optical calibration was done and when it expires, whether the run
finished, and (QuantStudio family) a log of events. Exports usually lose it. This module reads it
back, from four kinds of file, into one :class:`RunContext`:

* ``eds``: a QuantStudio-family run archive (StepOne, 7500, QuantStudio, ViiA). It is a zip whose
  members sit under ``apldbio/sds/``; member names are compared in lower case with ``\``
  turned into ``/``, because the 7500 writes ``APLDBIO\SDS\CALIBRATIONS/background.ini``.
  Read: ``experiment.xml`` (``RunState``, ``RunStartTime``/``RunEndTime`` in epoch milliseconds,
  ``InstrumentTypeId``, a serial wherever it is), ``Manifest.mf`` (software),
  ``calibrations/*.ini`` (``[head] timestamp=``, an expiry key, per-dye sections),
  ``run/run_summary.json`` and ``summary.json`` (keys mapped tolerantly), ``messages.log``
  (a curated event vocabulary, never error counts) and ``logs/temperature.log`` (a summary);
* ``quantstudio_export``: the header rows of a QuantStudio results export (``.csv`` rows
  ``key,value`` padded with commas, the ``.txt`` ``* key = value`` dialect, or the
  ``# Key: Value`` lines a Design & Analysis 2.x export puts above its table) and its per-well
  flag columns (``Y``/``N``);
* ``cfx_run_information``: a Bio-Rad CFX "Run Information" key/value export;
* ``rdml``: ``run.instrument`` (Bio-Rad CFX strings carry the serials; a LightCycler 96 string
  carries one), ``run.runDate`` and, failing that, a date in the run name, which is recorded
  with ``date_source = "run name"`` and is never an instrument fact.

Rules:

* every item is a :class:`~qpilot.schemas.Fact` whose ``path`` points at its source (archive
  member and key, or export line), e.g. ``experiment.xml:RunState`` or ``export.csv:line 3``;
* serials and instrument names stay on this machine: their facts' paths start with
  :data:`LOCAL_ONLY`, :meth:`RunContext.model_view` leaves them out, and only
  :meth:`RunContext.summary` (read by the local instrument logbook) carries them;
* personal data is never copied: an operator's file path, user name, operator or comment field
  only leaves a fixed note ("operator path present, not read"). Log text is matched against a
  fixed vocabulary and never copied; free-text names in RDML are kept only as local aliases;
* files are untrusted: size caps and the zip compression ratio are checked from the zip
  directory before any member is read, every read is bounded, and XML goes through the same
  hardened parser as RDML (no entities, no network);
* whatever cannot be told from the file is ``None`` with a note, never a guess: a calibration
  timestamp that falls in the run, or on the run day of a StepOne, means "calibration date not in
  file"; a day-month order that the file does not settle means "date format ambiguous" and no
  age; a time zone qPilot does not know is kept as text and not converted.

Formats checked on real files and formats inferred are listed in ``methods/instrument_context.md``
(open questions U1 to U9). Whether an expired optical calibration moves Cq is not known; this
module reports the fact and never judges the run.

Deterministic: no model call and no network.
"""

from __future__ import annotations

import csv
import datetime as dt
import html
import io
import json
import re
import zipfile
import zlib
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
from lxml import etree
from pydantic import BaseModel, Field

from qpilot.core.facts import slug
from qpilot.io.rdml_io import MAX_XML_BYTES as MAX_RDML_BYTES
from qpilot.io.rdml_io import RDML_MEMBER, hardened_parser
from qpilot.schemas import Fact

METHOD_CARD_PATH = "methods/instrument_context.md"

SourceKind = Literal["eds", "quantstudio_export", "cfx_run_information", "rdml"]
SOURCE_KINDS: tuple[str, ...] = ("eds", "quantstudio_export", "cfx_run_information", "rdml")
EDS_PREFIX = "apldbio/sds/"
LOCAL_ONLY = "local:"  # Fact.path prefix: the fact never leaves the machine (serials, names)

MAX_FILE_BYTES = 2 << 30  # an .eds or .rdml file on disk
MAX_ARCHIVE_BYTES = 2 << 30  # all members of an .eds, uncompressed
MAX_MEMBERS = 50_000  # a 7500 archive has 223 members (mostly images)
MAX_ZIP_RATIO = 100  # the same limit as rdml_io and io.sheets; a real 7500 .eds inflates 5x
RATIO_CHECK_BYTES = 1 << 20  # smaller members are not ratio-checked (a short ini packs tightly)
MAX_MEMBER_BYTES = 32 << 20  # experiment.xml, json and ini members
MAX_LOG_BYTES = 8 << 20  # messages.log and the temperature log; the largest measured was 5.7 MB
MAX_EXPORT_BYTES = 32 << 20  # a text export; a 384-well results export is well under 1 MB
MAX_EXPORT_LINES = 500_000
HEADER_SCAN_LINES = 400  # key/value header rows are searched only near the top of an export
MAX_JSON_NODES = 20_000
MAX_JSON_DEPTH = 8
MAX_EVENTS = 500
MAX_CYCLES_NAMED = 100
MAX_TEMPERATURE_ROWS = 500_000
MAX_ALIAS_CHARS = 400  # a Bio-Rad CFX instrument string is about 230 characters
MAX_UNMAPPED_KEYS = 50

HOLD_MIN_ROWS = 10  # a hold is a constant setpoint for at least this many log rows
SETTLE_BAND_C = 0.1  # a hold is measured once the sample is this close to (or crosses) setpoint
SETPOINT_STEP_C = 0.05  # setpoint changes smaller than this do not end a hold

IDENTITY_KEYS: tuple[str, ...] = (
    "model",
    "instrument_type",
    "serial",
    "block_serial",
    "cover_serial",
    "optical_head_serial",
    "firmware",
    "software",
)
LOCAL_IDENTITY = frozenset(
    {"serial", "block_serial", "cover_serial", "optical_head_serial", "shuttle_serial"}
)
EVENT_KINDS: tuple[str, ...] = ("pause", "lid_open", "drawer", "abort", "power", "resume")
INTERRUPTIONS = frozenset({"pause", "lid_open", "drawer"})
CHECKS: tuple[str, ...] = (
    "identity",
    "run_state",
    "calibrations",
    "event_log",
    "temperature",
    "well_flags",
)

NOTE_CAL_NOT_IN_FILE = "calibration date not in file"
NOTE_DATE_AMBIGUOUS = "date format ambiguous"
NOTE_TZ_NOT_CONVERTED = "time zone not converted"
NOTE_TZ_NOT_IN_FILE = "time zone not in file"
NOTE_RUN_DATE_DOUBTFUL = "run date may be unset or anonymised"
NOTE_OPERATOR_PATH = "operator path present, not read"
NOTE_USER_NAME = "user name present, not read"
NOTE_PERSONAL_FIELD = "personal field present, not read"
NOTE_STATE_DISAGREES = "experiment.xml and the log disagree on the run state; the log is used"
NOTE_CAL_AFTER_RUN = "calibration dated after the run"
NOTE_EXPIRY_NOT_UNDERSTOOD = "calibration expiry value not understood"
NOTE_SOURCES_DISAGREE = "the file gives two different values for one instrument field"
NOTE_EVENTS_CAPPED = "more log events than the cap; the rest are not listed"
NOTE_TEMPERATURE_FORMAT = "temperature log present but its layout is not understood"
NOTE_UNMAPPED = "some summary keys are not mapped (listed in unmapped_keys)"
NOTE_MANY_RUNS = "the file holds several runs; read them one by one with run_contexts_from_rdml"

_TZ_OFFSETS = {
    "UTC": 0,
    "GMT": 0,
    "Z": 0,
    "PDT": -7,
    "PST": -8,
    "EDT": -4,  # Design & Analysis exports of a US lab write EST and EDT
    "EST": -5,
    "BST": 1,
}

#: ``InstrumentTypeId`` values seen in public files and the instrument class they stand for.
INSTRUMENT_TYPE_IDS: dict[str, str] = {
    "sds7500fast": "7500 Fast",
    "sds7500": "7500",
    "steponeplus": "StepOnePlus",
    "stepone": "StepOne",
    "appletini": "QuantStudio 1/3/5 class",
    "paragon": "ViiA 7 / QuantStudio 7 Flex class",
    "spyder": "QuantStudio 12K Flex class",
}

#: Per-well vendor flag columns known from QuantStudio exports (other upper-case Y/N columns
#: are accepted too).
KNOWN_WELL_FLAGS = frozenset(
    {
        "AMPNC",
        "BADROX",
        "BLFAIL",
        "CQCONF",
        "EXPFAIL",
        "HIGHSD",
        "LOWROX",
        "NOAMP",
        "NOISE",
        "NOSIGNAL",
        "OFFSCALE",
        "OUTLIERRG",
        "PRFDROP",
        "PRFLOW",
        "SPIKE",
        "THOLDFAIL",
    }
)

#: Free text in RDML ``run.instrument`` becomes the model only when it names a known instrument.
_KNOWN_MODEL = re.compile(
    r"QuantStudio|StepOne|ViiA|LightCycler|\bLC ?\d{2,3}\b|\bCFX|\b7[359]00\b|Rotor-?Gene|"
    r"Mx300[05]|AriaMx|qTOWER|\bEco\b|iCycler|MyiQ|Chromo4|Opticon|iQ5",
    re.I,
)
#: ``…_20080220`` (optionally followed by ``_bis``): the Vermeulen run-name date.
RUN_NAME_DATE = re.compile(r"_(?P<y>20\d{2})(?P<m>\d{2})(?P<d>\d{2})(?=_|$)")

METHOD_CARD: dict[str, Any] = {
    "id": "instrument_context",
    "version": "1",
    "title": "What the run file says about the instrument",
    "source": (
        "Vendor file layouts read from public files (QuantStudio CSV results exports, "
        "Design & Analysis 2.x CSV exports, an ABI 7500 .eds, a Bio-Rad CFX RDML export); no "
        "published method"
    ),
    "implementation": "qpilot/qpcr/instrument_context.py",
    "inputs": [
        "a QuantStudio-family .eds archive",
        "a QuantStudio .csv/.txt results export (and a Design & Analysis 2.x .csv export)",
        "a Bio-Rad CFX Run Information export",
        "an RDML file",
    ],
    "outputs": [
        "RunContext: identity, run times and state, calibrations, log events, temperature "
        "summary, per-well vendor flags, notes, facts with source pointers",
        "RunContext.summary(): the stable dict the instrument logbook reads",
    ],
    "acceptance_tests": [
        "tests/engine/test_instrument_context.py::test_qs_eds_calibrations_events_and_serials",
        "tests/engine/test_instrument_context.py::test_7500_layout_from_the_real_file",
        "tests/engine/test_instrument_context.py::test_stepone_calibration_date_not_in_file",
        "tests/engine/test_instrument_context.py::test_quantstudio_csv_qs5_and_qs3_headers",
        "tests/engine/test_instrument_context.py::test_design_and_analysis_exports_from_the_corpus",
        "tests/engine/test_instrument_context.py::test_six_megabyte_log_parses_quickly",
        "tests/engine/test_instrument_context.py::test_demo_rdml_has_no_instrument_fields",
        "tests/engine/test_gate_instr.py::test_pause_at_cycle_23_warns_naming_cycles_23_24",
    ],
    "licence": "Apache-2.0",
    "card": METHOD_CARD_PATH,
}


class InstrumentFileError(ValueError):
    """The file is not a readable run file within the size caps, or not a kind qPilot reads."""


class RunContext(BaseModel):
    """What one run file (or one RDML run) says about the instrument and the run.

    Attributes:
        source_file: The file's name (no directories).
        source_kind: ``eds``, ``quantstudio_export``, ``cfx_run_information`` or ``rdml``.
        run_id: The RDML run id; ``None`` for other files (their experiment names are free text).
        identity: ``model``, ``instrument_type``, ``serial``, ``block_serial``, ``cover_serial``,
            ``optical_head_serial``, ``firmware``, ``software`` (``str`` or ``None``), plus
            ``block_type`` / ``shuttle_serial`` when a file names them. Serials are local only.
        run: ``start`` and ``end`` (ISO 8601; UTC with ``Z`` when the file gives a known time
            zone, else local time without a zone; a date only when it comes from a run name),
            ``state`` (``complete``, ``aborted``, ``stopped``, ``init``, ... or ``None``),
            ``date_source`` (``instrument``, ``run name`` or ``None``) and ``date`` (the
            calendar day calibration ages are counted to); ``time_zone`` holds a zone
            abbreviation the file gives that qPilot does not convert.
        calibrations: One dict per calibration: ``type``, ``label``, ``performed_on`` and
            ``expires_on`` (ISO dates or ``None``), ``expired_at_run`` and ``age_days`` (or
            ``None``), ``interval_days`` (vendor interval, when both dates are known),
            ``source``; ``performed_on_raw`` when the day-month order is ambiguous.
        events: Log events during the run: ``kind`` (one of :data:`EVENT_KINDS`), ``at`` (local
            time from the log or ``None``), ``cycle`` (or ``None``), ``source``; interruptions
            (pause, lid or drawer opened) also carry ``cycles``, the cycles to look at.
        temperature: ``max_hold_deviation_c``, ``zone_spread_p95_c``, ``min_lid_c_cycling``
            (each a float or ``None``), or ``None`` when the file has no temperature log.
        well_flags: Well (``A1``) -> the vendor flags set on it (``PRFDROP``, ``NOISE``, ...).
        notes: Fixed phrases about what the file does not say (see the ``NOTE_*`` constants).
        facts: Every item above as a fact whose ``path`` is its source pointer.
        checked: What the file allowed to check (a subset of :data:`CHECKS`), so "no pauses" is
            said only when an event log was read.
        aliases: Identity strings seen (serials, instrument names, RDML instrument text); local.
        unmapped_keys: Keys of ``run_summary.json``/``summary.json`` not mapped; local.
    """

    source_file: str
    source_kind: SourceKind
    run_id: str | None = None
    identity: dict[str, str | None] = Field(default_factory=lambda: dict.fromkeys(IDENTITY_KEYS))
    run: dict[str, Any] = Field(
        default_factory=lambda: {
            "start": None,
            "end": None,
            "state": None,
            "date_source": None,
            "date": None,
        }
    )
    calibrations: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    temperature: dict[str, float | None] | None = None
    well_flags: dict[str, list[str]] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    facts: dict[str, Fact] = Field(default_factory=dict)
    checked: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    unmapped_keys: list[str] = Field(default_factory=list)

    def fact_id(self, name: str) -> str:
        """The id of this context's fact ``name`` (``f_instr_<name>``, run-prefixed for RDML)."""
        return _fact_id(self.run_id, name)

    def summary(self) -> dict[str, Any]:
        """The stable dict the instrument logbook reads; no free text beyond identity strings.

        ``run_start`` is a date only (``2008-02-20``) when ``date_source`` is ``"run name"``.
        """
        ident = self.identity
        calibrations = {
            cal["type"]: {
                "performed_on": cal.get("performed_on"),
                "expires_on": cal.get("expires_on"),
                "expired_at_run": cal.get("expired_at_run"),
            }
            for cal in sorted(self.calibrations, key=lambda c: c["type"])
        }
        return {
            "source_kind": self.source_kind,
            "run_id": self.run_id,
            "run_start": self.run.get("start"),
            "run_end": self.run.get("end"),
            "run_state": self.run.get("state"),
            "date_source": self.run.get("date_source"),
            "model": ident.get("model"),
            "serial": ident.get("serial"),
            "block_serial": ident.get("block_serial"),
            "cover_serial": ident.get("cover_serial"),
            "optical_head_serial": ident.get("optical_head_serial"),
            "firmware": ident.get("firmware"),
            "software": ident.get("software"),
            "calibrations": calibrations,
            "events": [{"kind": e["kind"], "cycle": e.get("cycle")} for e in self.events],
            "aliases": sorted(set(self.aliases)),
        }

    def model_view(self) -> dict[str, Any]:
        """The context without anything local: no serials, aliases, local facts or raw keys.

        This is the only shape of a :class:`RunContext` that may go to a model or an export.
        ``serials_present`` names the serial fields the file had, without their values.
        """
        data = self.model_dump(mode="json", exclude={"aliases", "unmapped_keys", "facts"})
        data["identity"] = {
            key: (None if key in LOCAL_IDENTITY else value) for key, value in self.identity.items()
        }
        data["serials_present"] = sorted(k for k in LOCAL_IDENTITY if self.identity.get(k))
        data["facts"] = {
            fid: fact.model_dump(mode="json")
            for fid, fact in sorted(self.facts.items())
            if not is_local_only(fact)
        }
        return data


def is_local_only(fact: Fact) -> bool:
    """True for a fact that must never leave the machine (a serial or an instrument name)."""
    return fact.path.startswith(LOCAL_ONLY)


def model_facts(ctx: RunContext) -> dict[str, Fact]:
    """The context's facts a model may see (every fact that is not local only), sorted by id."""
    return {fid: fact for fid, fact in sorted(ctx.facts.items()) if not is_local_only(fact)}


# ---------------------------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------------------------


def read_run_context(
    path: str | Path, *, date_order: Literal["DMY", "MDY"] | None = None
) -> RunContext:
    """Read what a run file says about the instrument.

    Args:
        path: An ``.eds`` archive, a QuantStudio ``.csv``/``.txt`` results export (a Design &
            Analysis 2.x ``.csv`` export too), a CFX "Run Information" ``.csv``/``.txt`` export,
            or an ``.rdml`` file. The kind is sniffed from the content, not the suffix alone.
        date_order: For exports whose dates are written ``11-12-2018``: ``"DMY"`` or ``"MDY"``
            when the caller knows the order (for instance from this instrument's earlier files);
            ``None`` lets the file settle it (any day above twelve) or leaves it ambiguous.

    Returns:
        The run context. An RDML file with several runs gives one file-level context whose
        facts count the runs; use :func:`run_contexts_from_rdml` for the runs themselves.

    Raises:
        InstrumentFileError: Missing file, over a size cap, a zip bomb, damaged, or not a kind
            of file qPilot reads.
    """
    file = Path(path)
    if not file.is_file():
        raise InstrumentFileError(f"not a file: {file.name}")
    size = file.stat().st_size
    if size > MAX_FILE_BYTES:
        raise InstrumentFileError(f"{file.name}: file too large ({size} bytes)")
    if zipfile.is_zipfile(file):
        return _read_zip(file)
    with file.open("rb") as handle:
        head = handle.read(4096)
    if file.suffix.lower() in (".rdml", ".xml") or head.lstrip(b"\xef\xbb\xbf \t\r\n")[:1] == b"<":
        if size > MAX_RDML_BYTES:
            raise InstrumentFileError(f"{file.name}: input too large ({size} bytes of XML)")
        return _combine_rdml(file.name, _rdml_contexts_from_bytes(file.read_bytes(), file.name))
    if size > MAX_EXPORT_BYTES:
        raise InstrumentFileError(f"{file.name}: export too large ({size} bytes; the cap is 32 MB)")
    return _read_text_export(file, date_order)


def run_contexts_from_rdml(doc_or_path: Any, *, source_file: str | None = None) -> list[RunContext]:
    """One :class:`RunContext` per RDML run: instrument string, run date or run-name date.

    Args:
        doc_or_path: An RDML file path, or a document loaded by
            :func:`qpilot.io.rdml_io.load` (anything with ``experiments()``).
        source_file: The file name to record; default the path's name, or ``"rdml"``.

    Returns:
        Contexts in document order (experiments, then their runs).

    Raises:
        InstrumentFileError: The path is not a readable RDML file within the caps.
    """
    if hasattr(doc_or_path, "experiments"):
        name = source_file or "rdml"
        records = []
        for experiment in doc_or_path.experiments():
            for run in experiment.runs():
                records.append(
                    _RdmlRun(
                        experiment_id=str(experiment["id"]),
                        run_id=str(run["id"]),
                        instrument=run["instrument"],
                        run_date=run["runDate"],
                        software_name=run["dataCollectionSoftware_name"],
                        software_version=run["dataCollectionSoftware_version"],
                        member=RDML_MEMBER,
                    )
                )
        return [_rdml_run_context(record, name) for record in records]
    file = Path(doc_or_path)
    if not file.is_file():
        raise InstrumentFileError(f"not a file: {file.name}")
    name = source_file or file.name
    if zipfile.is_zipfile(file):
        with _open_zip(file) as archive:
            infos = archive.infolist()
            _check_archive(file.name, infos)
            info = _rdml_member(file.name, infos)
            data = _read_member(archive, info, MAX_RDML_BYTES, info.filename)
        return _rdml_contexts_from_bytes(data, name, member=info.filename)
    size = file.stat().st_size
    if size > MAX_RDML_BYTES:
        raise InstrumentFileError(f"{file.name}: input too large ({size} bytes of XML)")
    return _rdml_contexts_from_bytes(file.read_bytes(), name)


# ---------------------------------------------------------------------------------------------
# The builder every reader fills
# ---------------------------------------------------------------------------------------------


def _fact_id(run_id: str | None, name: str) -> str:
    """``f_instr_<name>``, or ``f_instr_<run>_<name>`` for one RDML run."""
    if not run_id:
        return f"f_instr_{name}"
    part = re.sub(r"[^a-z0-9]+", "_", run_id.lower()).strip("_") or "run"
    return f"f_instr_{part}_{name}"


@dataclass
class _Cal:
    """A calibration as read, before ages and expiry are settled against the run date."""

    type: str
    label: str
    source: str
    performed: dt.datetime | dt.date | None = None
    expires: dt.datetime | dt.date | None = None
    expires_source: str | None = None
    expired_flag: bool | None = None  # the file's own "is expired" statement
    expired_source: str | None = None
    raw_date: str | None = None  # a performed-on date whose day-month order is ambiguous


@dataclass
class _Builder:
    """Collects one run's items and facts; :meth:`build` settles ages and returns the context."""

    source_file: str
    source_kind: str
    run_id: str | None = None
    identity: dict[str, str | None] = field(default_factory=lambda: dict.fromkeys(IDENTITY_KEYS))
    identity_paths: dict[str, str] = field(default_factory=dict)
    start: dt.datetime | None = None
    end: dt.datetime | None = None
    start_text: str | None = None
    end_text: str | None = None
    local_date: dt.date | None = None  # the run's calendar day in the file's own time frame
    run_zone: str | None = None  # a time-zone abbreviation the file gives and qPilot keeps as text
    state: str | None = None
    date_source: str | None = None
    calibrations: list[_Cal] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    temperature: dict[str, float | None] | None = None
    well_flags: dict[str, list[str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    facts: dict[str, Fact] = field(default_factory=dict)
    checked: set[str] = field(default_factory=set)
    aliases: set[str] = field(default_factory=set)
    unmapped_keys: list[str] = field(default_factory=list)
    well_rows: dict[str, str] = field(default_factory=dict)  # well -> its first flagged row

    def note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)

    def fact(
        self,
        name: str,
        value: float | int | str,
        path: str,
        *,
        fmt: str = "{}",
        unit: str = "",
        local: bool = False,
    ) -> str:
        fid = _fact_id(self.run_id, name)
        self.facts[fid] = Fact(
            id=fid, value=value, fmt=fmt, unit=unit, path=(LOCAL_ONLY + path) if local else path
        )
        return fid

    def set_identity(self, key: str, value: str | None, path: str) -> None:
        """Set an identity field once; a later, different value from another source is a note."""
        if not value:
            return
        current = self.identity.get(key)
        if current is not None:
            if current != value:
                self.note(NOTE_SOURCES_DISAGREE)
            return
        self.identity[key] = value
        self.identity_paths[key] = path
        local = key in LOCAL_IDENTITY
        self.fact(key, value, path, local=local)
        if local:
            self.aliases.add(value)
        self.checked.add("identity")

    def alias(self, value: str | None, name: str, path: str) -> None:
        """Remember an identity string (an instrument name, a free-text RDML instrument)."""
        text = _clean_text(value, MAX_ALIAS_CHARS)
        if text:
            self.aliases.add(text)
            self.fact(name, text, path, local=True)

    def build(self, *, stepone: bool | None = None) -> RunContext:
        if self.state is not None:
            self.checked.add("run_state")
        run = {
            "start": self.start_text or (_iso(self.start) if self.start else None),
            "end": self.end_text or (_iso(self.end) if self.end else None),
            "state": self.state,
            "date_source": self.date_source,
            "date": None,
        }
        if self.run_zone:
            run["time_zone"] = self.run_zone
        run_date = self.local_date
        if run_date is None:
            moment = self.start or self.end
            run_date = moment.astimezone(dt.UTC).date() if moment and moment.tzinfo else None
            if moment is not None and moment.tzinfo is None:
                run_date = moment.date()
        if run_date is not None:
            run["date"] = run_date.isoformat()
            self.fact("run_date", run_date.isoformat(), self.identity_paths.get("_date", ""))
        if stepone is None:
            stepone = _is_stepone(self.identity)
        calibrations = [self._calibration(cal, run_date, stepone) for cal in self.calibrations]
        calibrations.sort(key=lambda c: c["type"])
        if calibrations:
            self.checked.add("calibrations")
        if self.temperature is not None:
            self.checked.add("temperature")
        return RunContext(
            source_file=self.source_file,
            source_kind=self.source_kind,  # type: ignore[arg-type]
            run_id=self.run_id,
            identity=self.identity,
            run=run,
            calibrations=calibrations,
            events=self.events,
            temperature=self.temperature,
            well_flags=dict(sorted(self.well_flags.items(), key=lambda kv: _well_order(kv[0]))),
            notes=self.notes,
            facts=dict(sorted(self.facts.items())),
            checked=[c for c in CHECKS if c in self.checked],
            aliases=sorted(self.aliases),
            unmapped_keys=sorted(self.unmapped_keys),
        )

    def _calibration(self, cal: _Cal, run_date: dt.date | None, stepone: bool) -> dict[str, Any]:
        """Settle one calibration against the run: date in file or not, age, expiry."""
        performed_on = _as_date(cal.performed)
        expires_on = _as_date(cal.expires)
        not_in_file = False
        moments = (cal.performed, self.start, self.end)
        if all(isinstance(m, dt.datetime) for m in moments) and _comparable(*moments):
            not_in_file = self.start <= cal.performed <= self.end  # nothing calibrates mid-run
        if stepone and performed_on is not None and performed_on == run_date:
            not_in_file = True  # StepOne files stamp calibrations with the run date
        if not_in_file:
            self.note(NOTE_CAL_NOT_IN_FILE)
            performed_on = expires_on = None
        age = (run_date - performed_on).days if run_date and performed_on else None
        if age is not None and age < 0:
            self.note(NOTE_CAL_AFTER_RUN)
            age = None
        expired = cal.expired_flag
        if expired is None and expires_on is not None and run_date is not None:
            expired = run_date > expires_on
        interval = (expires_on - performed_on).days if expires_on and performed_on else None
        out: dict[str, Any] = {
            "type": cal.type,
            "label": cal.label,
            "performed_on": performed_on.isoformat() if performed_on else None,
            "expires_on": expires_on.isoformat() if expires_on else None,
            "expired_at_run": expired,
            "age_days": age,
            "interval_days": interval,
            "source": cal.source,
        }
        if cal.raw_date is not None and performed_on is None and not not_in_file:
            out["performed_on_raw"] = cal.raw_date
        base = f"cal_{cal.type}"
        self.fact(f"{base}_label", cal.label, cal.source)
        if performed_on is not None:
            self.fact(f"{base}_performed_on", performed_on.isoformat(), cal.source)
        if expires_on is not None:
            self.fact(f"{base}_expires_on", expires_on.isoformat(), cal.expires_source or "")
        if expired is not None:
            path = cal.expired_source or cal.expires_source or cal.source
            self.fact(f"{base}_expired", "yes" if expired else "no", path)
        if age is not None:
            self.fact(f"{base}_age_days", age, cal.source)
        if interval is not None:
            self.fact(f"{base}_interval_days", interval, cal.expires_source or cal.source)
        return out


def _comparable(*moments: Any) -> bool:
    """True when the times are all aware or all naive (so they can be compared)."""
    return len({m.tzinfo is None for m in moments}) == 1


def _is_stepone(identity: Mapping[str, str | None]) -> bool:
    text = " ".join(identity.get(k) or "" for k in ("model", "instrument_type", "software")).lower()
    return "stepone" in text.replace(" ", "")


# ---------------------------------------------------------------------------------------------
# Small helpers: text, dates, zip caps
# ---------------------------------------------------------------------------------------------

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_ID_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._\-/]{0,63}$")
_NULLISH = frozenset({"", "null", "none", "n/a", "na", "unknown", "*", "0", "-"})


def _clean_text(value: Any, limit: int = 80) -> str | None:
    """Printable text, whitespace collapsed, at most ``limit`` characters; ``None`` if empty."""
    if value is None:
        return None
    text = " ".join(_CONTROL.sub(" ", html.unescape(str(value))).split())
    return text[:limit] or None


def _clean_id(value: Any) -> str | None:
    """A serial-like value (letters, digits, ``._-/``), or ``None`` for placeholders."""
    text = _clean_text(value, 64)
    if text is None or text.lower() in _NULLISH or not _ID_VALUE.match(text):
        return None
    return text


def _iso(moment: dt.datetime) -> str:
    """ISO 8601 to the second: ``…Z`` for an aware time (in UTC), no zone for a naive one."""
    if moment.tzinfo is None:
        return moment.strftime("%Y-%m-%dT%H:%M:%S")
    return moment.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_date(value: dt.datetime | dt.date | None) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.astimezone(dt.UTC).date() if value.tzinfo else value.date()
    return value


def _from_epoch(value: Any) -> dt.datetime | None:
    """Epoch milliseconds (or seconds) as an aware UTC time; ``None`` for 0 or implausible ones."""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    seconds = number / 1000 if number > 10**11 else number
    try:
        moment = dt.datetime.fromtimestamp(seconds, tz=dt.UTC)
    except (OverflowError, OSError, ValueError):
        return None
    return moment if 1990 <= moment.year <= 2100 else None


def _parse_iso(text: Any) -> dt.datetime | None:
    """An ISO 8601 date-time (``Z`` or an offset allowed), or ``None``."""
    raw = _clean_text(text, 40)
    if raw is None:
        return None
    raw = raw.replace("Z", "+00:00").replace("z", "+00:00")
    try:
        moment = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    return moment if 1990 <= moment.year <= 2100 else None


def _time_value(value: Any) -> dt.datetime | None:
    """A JSON time value: epoch milliseconds or seconds, digits as text, or ISO 8601."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return _from_epoch(int(value))
    text = str(value).strip()
    return _from_epoch(text) if text.isdigit() else _parse_iso(text)


_SPLIT_DATE = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$")
_ISO_DATE = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")


def _date_order(values: Iterable[str]) -> Literal["DMY", "MDY"] | None:
    """Settle day-month order from a file's own dates: a first part above twelve means DMY."""
    first = second = False
    for value in values:
        match = _SPLIT_DATE.match(value.strip().split(" ")[0])
        if match:
            first |= int(match.group(1)) > 12
            second |= int(match.group(2)) > 12
    if first and not second:
        return "DMY"
    if second and not first:
        return "MDY"
    return None


def _parse_date(text: str, order: str | None) -> tuple[dt.date | None, bool]:
    """``(date, ambiguous)`` for ``2018-12-11``, ``08-24-2017`` or ``11-12-2018``."""
    token = text.strip().split(" ")[0]
    try:
        if match := _ISO_DATE.match(token):
            return dt.date(int(match[1]), int(match[2]), int(match[3])), False
        if match := _SPLIT_DATE.match(token):
            a, b, year = int(match[1]), int(match[2]), int(match[3])
            if a > 12 and b <= 12:
                return dt.date(year, b, a), False
            if b > 12 and a <= 12:
                return dt.date(year, a, b), False
            if a == b:
                return dt.date(year, a, b), False
            if order == "DMY":
                return dt.date(year, b, a), False
            if order == "MDY":
                return dt.date(year, a, b), False
            return None, True
    except ValueError:
        return None, False
    return None, False


_VENDOR_TIME = re.compile(
    r"^\s*(?P<date>\S+)[ T]+(?P<h>\d{1,2}):(?P<mi>\d{2})(?::(?P<s>\d{2}))?(?:[.,]\d+)?"
    r"\s*(?P<ampm>AM|PM)?\s*(?P<tz>[A-Za-z]{1,5})?\s*$",
    re.I,
)


@dataclass(frozen=True)
class _VendorTime:
    """An export time: the moment, its local calendar day, a note, and an unconverted zone."""

    moment: dt.datetime | None
    day: dt.date | None = None
    note: str | None = None
    zone: str | None = None  # a zone abbreviation qPilot does not convert, kept as text


def _parse_vendor_time(text: str, order: str | None) -> _VendorTime:
    """Read an export time such as ``2019-09-11 14:18:36 PM PDT``.

    The hour may be a 24-hour hour followed by AM/PM; above twelve the suffix is ignored. Known
    zones (UTC, GMT, PDT, PST, BST) give an aware time; any other zone is not converted: the
    time stays naive (local), the abbreviation is kept as text, and a note says so.
    """
    match = _VENDOR_TIME.match(text or "")
    if not match:
        return _VendorTime(None)
    day, ambiguous = _parse_date(match["date"], order)
    if day is None:
        return _VendorTime(None, note=NOTE_DATE_AMBIGUOUS if ambiguous else None)
    hour = int(match["h"])
    ampm = (match["ampm"] or "").upper()
    if ampm and hour <= 12:
        hour = hour % 12 + (12 if ampm == "PM" else 0)
    if hour > 23:
        return _VendorTime(None)
    moment = dt.datetime(day.year, day.month, day.day, hour, int(match["mi"]), int(match["s"] or 0))
    zone = (match["tz"] or "").upper()
    if zone in _TZ_OFFSETS:
        offset = dt.timezone(dt.timedelta(hours=_TZ_OFFSETS[zone]))
        return _VendorTime(moment.replace(tzinfo=offset), day)
    if zone:
        return _VendorTime(moment, day, NOTE_TZ_NOT_CONVERTED, zone)
    return _VendorTime(moment, day, NOTE_TZ_NOT_IN_FILE)


def _decode(raw: bytes) -> str:
    """Text from bytes: UTF-16 by its byte-order mark, else UTF-8, Windows-1252 or Latin-1."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _open_zip(file: Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(file)
    except (zipfile.BadZipFile, OSError) as err:
        raise InstrumentFileError(f"{file.name}: not a readable zip archive ({err})") from err


def _check_archive(name: str, infos: Sequence[zipfile.ZipInfo]) -> None:
    """Refuse an archive with too many members, too much data, or a decompression-bomb ratio."""
    if len(infos) > MAX_MEMBERS:
        raise InstrumentFileError(f"{name}: too many members in the archive ({len(infos)})")
    total = sum(info.file_size for info in infos)
    packed = sum(info.compress_size for info in infos)
    if total > MAX_ARCHIVE_BYTES:
        raise InstrumentFileError(f"{name}: archive too large ({total} bytes uncompressed)")
    if packed and total / packed > MAX_ZIP_RATIO:
        raise InstrumentFileError(
            f"{name}: archive too large (compression ratio above {MAX_ZIP_RATIO}:1)"
        )


def _read_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, cap: int, label: str) -> bytes:
    """One member's bytes, after its declared size and ratio pass; the read itself is bounded."""
    if info.file_size > cap:
        raise InstrumentFileError(
            f"{label}: member too large ({info.file_size} bytes; the cap is {cap >> 20} MB)"
        )
    if (
        info.file_size >= RATIO_CHECK_BYTES
        and info.compress_size
        and info.file_size / info.compress_size > MAX_ZIP_RATIO
    ):
        raise InstrumentFileError(f"{label}: compression ratio above {MAX_ZIP_RATIO}:1")
    try:
        with archive.open(info) as handle:
            data = handle.read(cap + 1)
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError) as err:
        raise InstrumentFileError(f"{label}: damaged or encrypted member ({err})") from err
    if len(data) > cap:
        raise InstrumentFileError(f"{label}: member larger than the {cap >> 20} MB cap")
    return data


def _members(infos: Sequence[zipfile.ZipInfo]) -> tuple[dict[str, zipfile.ZipInfo], bool]:
    """Relative member name (lower case, ``/``, without ``apldbio/sds/``) -> info; has prefix."""
    prefixed: dict[str, zipfile.ZipInfo] = {}
    plain: dict[str, zipfile.ZipInfo] = {}
    for info in infos:
        if info.is_dir():
            continue
        name = info.filename.replace("\\", "/").lower()
        if name.startswith(EDS_PREFIX):
            prefixed.setdefault(name[len(EDS_PREFIX) :], info)
        else:
            plain.setdefault(name, info)
    if prefixed:
        return {**{k: v for k, v in plain.items() if k not in prefixed}, **prefixed}, True
    return plain, False


def _well_order(well: str) -> tuple[int, str, int]:
    match = re.match(r"^([A-Z]+)(\d+)$", well)
    if match:
        return (0, match[1].rjust(2), int(match[2]))
    return (1, well, 0)


# ---------------------------------------------------------------------------------------------
# Zip files: .eds archives and zipped RDML
# ---------------------------------------------------------------------------------------------


def _read_zip(file: Path) -> RunContext:
    with _open_zip(file) as archive:
        infos = archive.infolist()
        _check_archive(file.name, infos)
        members, prefixed = _members(infos)
        is_eds = prefixed or (
            file.suffix.lower() == ".eds"
            and any(
                n in members for n in ("experiment.xml", "summary.json", "run/run_summary.json")
            )
        )
        if is_eds:
            return _read_eds(file.name, archive, members)
        if any(info.filename.lower().endswith(".xml") for info in infos):
            info = _rdml_member(file.name, infos)
            data = _read_member(archive, info, MAX_RDML_BYTES, info.filename)
            contexts = _rdml_contexts_from_bytes(data, file.name, member=info.filename)
            return _combine_rdml(file.name, contexts)
    raise InstrumentFileError(
        f"{file.name}: a zip archive, but neither a QuantStudio-family .eds nor an RDML file"
    )


def _rdml_member(name: str, infos: Sequence[zipfile.ZipInfo]) -> zipfile.ZipInfo:
    """``rdml_data.xml``, or the archive's only XML member (Bio-Rad names it after the file)."""
    xml = [i for i in infos if not i.is_dir() and i.filename.lower().endswith(".xml")]
    for info in xml:
        if info.filename == RDML_MEMBER:
            return info
    if len(xml) == 1:
        return xml[0]
    raise InstrumentFileError(f"{name}: no {RDML_MEMBER} inside the RDML archive")


def _read_eds(
    name: str, archive: zipfile.ZipFile, members: Mapping[str, zipfile.ZipInfo]
) -> RunContext:
    """A QuantStudio-family archive: experiment.xml, calibrations, summaries and logs."""
    b = _Builder(source_file=name, source_kind="eds")

    def read(rel: str, cap: int = MAX_MEMBER_BYTES) -> bytes | None:
        info = members.get(rel)
        return None if info is None else _read_member(archive, info, cap, rel)

    xml_state: str | None = None
    raw = read("experiment.xml")
    if raw is not None:
        xml_state = _eds_experiment(raw, b)
    manifest = read("manifest.mf")
    if manifest is not None:
        _eds_manifest(_decode(manifest), b)
    json_state: str | None = None
    for rel in ("run/run_summary.json", "summary.json"):
        data = read(rel)
        if data is not None:
            state = _eds_summary_json(data, rel, b)
            json_state = json_state or state
    log_rel = next((r for r in ("messages.log", "logs/messages.log") if r in members), None)
    log = _LogRead()
    if log_rel is not None:
        log = _parse_log(_decode(read(log_rel, MAX_LOG_BYTES) or b""), log_rel)
        b.checked.add("event_log")
        for key, value, path in log.serials:
            b.set_identity(key, value, path)
        _add_events(b, log)
    temp_rel = next(
        (
            r
            for r in ("logs/temperature.log", "temperature.log", "logs/temperatures.log")
            if r in members
        ),
        None,
    )
    if temp_rel is not None:
        text = _decode(read(temp_rel, MAX_LOG_BYTES) or b"")
        b.temperature = _temperature_summary(text)
        if b.temperature is None:
            b.note(NOTE_TEMPERATURE_FORMAT)
        else:
            for key, value in b.temperature.items():
                if value is not None:
                    b.fact(key, value, f"{temp_rel}", fmt="{:.2f}", unit=" °C")
    for rel in sorted(r for r in members if re.fullmatch(r"calibrations/[^/]+\.ini", r)):
        _eds_calibration(_decode(read(rel) or b""), rel, b)
    b.state = _settle_state(xml_state or json_state, log, b)
    if b.state is not None:
        b.fact("run_state", b.state, b.identity_paths.get("_state", "experiment.xml:RunState"))
    if b.start is not None:
        b.fact("run_start", _iso(b.start), b.identity_paths.get("_start", ""))
    if b.end is not None:
        b.fact("run_end", _iso(b.end), b.identity_paths.get("_end", ""))
    if b.start or b.end:
        b.date_source = "instrument"
        b.identity_paths["_date"] = b.identity_paths.get("_start") or b.identity_paths.get(
            "_end", ""
        )
    return b.build()


_STATES = {
    "complete": "complete",
    "completed": "complete",
    "finished": "complete",
    "success": "complete",
    "aborted": "aborted",
    "abort": "aborted",
    "stopped": "stopped",
    "terminated": "stopped",
    "cancelled": "stopped",
    "canceled": "stopped",
    "failed": "failed",
    "error": "failed",
    "init": "init",
    "running": "running",
    "paused": "paused",
}


def _state_word(text: Any) -> str | None:
    raw = (_clean_text(text, 30) or "").lower().replace(" ", "_")
    if not raw:
        return None
    if raw in _STATES:
        return _STATES[raw]
    return raw if re.fullmatch(r"[a-z_]{1,20}", raw) else "unknown"


def _settle_state(state: str | None, log: _LogRead, b: _Builder) -> str | None:
    """The run state: the file's, unless the log says it completed when the file did not."""
    if state not in ("complete", "aborted", "stopped", "failed") and log.completed:
        if state is not None:
            b.note(NOTE_STATE_DISAGREES)
            b.fact("run_state_in_file", state, b.identity_paths.get("_state", ""))
        b.identity_paths["_state"] = f"{log.source}:line {log.completed}"
        return "complete"
    if state is None and log.aborted:
        b.identity_paths["_state"] = f"{log.source}:line {log.aborted}"
        return "aborted"
    return state


def _children(element: Any, path: str = "", depth: int = 1) -> Iterator[tuple[Any, str, int]]:
    """Elements to depth three, with their slash path from the root (local names)."""
    for child in element:
        if not isinstance(child.tag, str):
            continue
        local = etree.QName(child).localname
        here = f"{path}/{local}" if path else local
        yield child, here, depth
        if depth < 3:
            yield from _children(child, here, depth + 1)


_XML_IDENTITY: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("block_serial", re.compile(r"^block(serial(number|no)?|sn)$")),
    ("cover_serial", re.compile(r"^(heated)?(cover|lid)(serial(number|no)?|sn)$")),
    ("optical_head_serial", re.compile(r"^optic(al)?(head)?(serial(number|no)?|sn)$")),
    ("serial", re.compile(r"^(instrument)?serial(number|no|num)?$|^instrumentsn$")),
    ("firmware", re.compile(r"^(instrument)?firmware(version)?$")),
    ("software", re.compile(r"^(software|application)(name)?version$")),
)


def _eds_experiment(raw: bytes, b: _Builder) -> str | None:
    """``experiment.xml``: run state and times, instrument type, any serial (tag unverified)."""
    try:
        root = etree.fromstring(raw, hardened_parser())
    except etree.XMLSyntaxError as err:
        raise InstrumentFileError(f"experiment.xml: not readable XML ({err})") from err
    state: str | None = None
    for element, path, depth in _children(root):
        local = path.rsplit("/", 1)[-1].lower()
        text = (element.text or "").strip()
        pointer = f"experiment.xml:{path}"
        if depth == 1 and local == "runstate" and text:
            state = _state_word(text)
            b.identity_paths["_state"] = pointer
        elif depth == 1 and local in ("runstarttime", "runendtime"):
            moment = _from_epoch(text) or _parse_iso(text)
            if moment is not None and local == "runstarttime":
                b.start, b.identity_paths["_start"] = moment, pointer
            elif moment is not None:
                b.end, b.identity_paths["_end"] = moment, pointer
        elif depth == 1 and local == "instrumenttypeid":
            type_id = _clean_id(text)
            if type_id:
                b.set_identity("instrument_type", type_id, pointer)
                b.set_identity("model", INSTRUMENT_TYPE_IDS.get(type_id.lower(), type_id), pointer)
        elif depth == 1 and local in ("operator", "username", "user", "filename") and text:
            b.note(NOTE_PERSONAL_FIELD)
        elif local == "instrumentname" and text:
            b.alias(text, "instrument_name", pointer)
        else:
            parent = path.rsplit("/", 1)[0].lower() if "/" in path else ""
            if depth > 1 and not re.search(r"runinfo|instrument|block|cover|lid|optic", parent):
                continue
            for key, pattern in _XML_IDENTITY:
                if pattern.match(local):
                    if key == "serial" and re.search(r"block", parent):
                        key = "block_serial"
                    elif key == "serial" and re.search(r"cover|lid", parent):
                        key = "cover_serial"
                    value = _clean_id(text) if "serial" in key else _clean_text(text, 64)
                    b.set_identity(key, value, pointer)
                    break
    return state


def _eds_manifest(text: str, b: _Builder) -> None:
    for number, line in enumerate(text.splitlines(), start=1):
        key, sep, value = line.partition(":")
        if sep and key.strip().lower() == "implementation-version":
            b.set_identity("software", _clean_text(value, 64), f"Manifest.mf:line {number}")


def _parse_ini(text: str) -> dict[str, dict[str, tuple[str, int]]]:
    """Section (lower case) -> key (lower case) -> (value, line); data blocks are skipped.

    Calibration files carry numeric blocks written ``1=<<eof`` ... ``eof``; ``#`` lines are
    comments.
    """
    sections: dict[str, dict[str, tuple[str, int]]] = {}
    current: str | None = None
    block_end: str | None = None
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if block_end is not None:
            if line == block_end:
                block_end = None
            continue
        if not line or line[0] in "#;":
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip()
            sections.setdefault(current.lower(), {"": (current, number)})
            current = current.lower()
            continue
        key, sep, value = line.partition("=")
        if not sep or current is None:
            continue
        value = value.strip()
        if value.startswith("<<"):
            block_end = value[2:].strip() or "eof"
            continue
        sections[current].setdefault(key.strip().lower(), (value, number))
    return sections


_CAL_TYPES = {"background": "Background", "roi": "ROI", "uniformity": "Uniformity"}
_CAL_STEMS = {"puredye": "pure_dye", "pure_dye": "pure_dye", "puredyes": "pure_dye"}
_INI_STANDARD = frozenset(
    {"head", "instrument", "scanner", "block", "plate", "result", "puredyes"} | set(_CAL_TYPES)
)
_EXPIRY_KEYS = frozenset({"expirytime", "expirationtime", "expiry", "expiration", "expirydate"})
_SAFE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 +\-]{0,39}$")


def _eds_calibration(text: str, rel: str, b: _Builder) -> None:
    """One ``calibrations/*.ini``: ``[head] timestamp``, expiry, per-dye times, ids."""
    sections = _parse_ini(text)
    stem = rel.rsplit("/", 1)[-1][: -len(".ini")]
    if stem in _CAL_STEMS:
        kind, label = _CAL_STEMS[stem], "Pure Dye"
    elif re.fullmatch(r"[a-z0-9_]{1,30}", stem):
        kind, label = stem, _CAL_TYPES.get(stem, stem)
    else:
        return  # not a vendor calibration name
    head = sections.get("head", {})
    cal = _Cal(type=kind, label=label, source=f"{rel}:[head].timestamp")
    if "timestamp" in head:
        cal.performed = _from_epoch(head["timestamp"][0])
    if cal.performed is None:
        b.note(NOTE_CAL_NOT_IN_FILE)
    expiry_key = next((k for k in head if re.sub(r"[-_]", "", k) in _EXPIRY_KEYS), None)
    if expiry_key is not None:
        cal.expires = _expiry(head[expiry_key][0], cal.performed, b)
        cal.expires_source = f"{rel}:[head].{expiry_key}"
    b.calibrations.append(cal)
    for section_key, target in (("instrument", "serial"), ("block", "block_serial")):
        ident = sections.get(section_key, {}).get("id")
        if ident and _clean_id(ident[0]):
            b.set_identity(target, _clean_id(ident[0]), f"{rel}:[{section_key}].id")
    for name, entries in sections.items():
        if name in _INI_STANDARD or not ({"calibration-time", "expiration-time"} & set(entries)):
            continue
        dye = entries[""][0]
        if len(dye) > 24 or not _SAFE_LABEL.match(dye):
            continue
        performed = _from_epoch(entries.get("calibration-time", ("0", 0))[0])
        expires = None
        if "expiration-time" in entries:
            expires = _expiry(entries["expiration-time"][0], performed, b)
        if performed is None and expires is None:
            continue  # 0 means unset; the [head] timestamp stands for the whole file
        b.calibrations.append(
            _Cal(
                type=f"{kind}_{slug(dye)}",
                label=f"{label} {dye}",
                source=f"{rel}:[{dye}].calibration-time",
                performed=performed,
                expires=expires,
                expires_source=f"{rel}:[{dye}].expiration-time",
            )
        )


def _expiry(value: str, performed: dt.datetime | None, b: _Builder) -> dt.datetime | None:
    """An expiry value: epoch ms after the calibration; 0 means unset; anything else a note."""
    text = value.strip()
    if text in ("", "0", "-1"):
        return None
    moment = _from_epoch(text)
    if moment is not None and (performed is None or moment > performed):
        return moment
    b.note(NOTE_EXPIRY_NOT_UNDERSTOOD)
    return None


# ---- run/run_summary.json and summary.json (key names unverified) ----

_JSON_FIELDS: dict[str, str] = {
    "serialnumber": "serial",
    "instrumentserialnumber": "serial",
    "instrumentserial": "serial",
    "instrumentsn": "serial",
    "serial": "serial",
    "blockserialnumber": "block_serial",
    "blockserial": "block_serial",
    "coverserialnumber": "cover_serial",
    "heatedcoverserialnumber": "cover_serial",
    "lidserialnumber": "cover_serial",
    "opticalheadserialnumber": "optical_head_serial",
    "instrumenttype": "model",
    "instrumentmodel": "model",
    "instrumenttypeid": "instrument_type",
    "model": "model",
    "modelname": "model",
    "firmware": "firmware",
    "firmwareversion": "firmware",
    "instrumentfirmware": "firmware",
    "softwareversion": "software",
    "software": "software",
    "applicationversion": "software",
    "runstate": "state",
    "runstatus": "state",
    "status": "state",
    "state": "state",
    "runstarttime": "start",
    "starttime": "start",
    "runstart": "start",
    "startedat": "start",
    "runendtime": "end",
    "endtime": "end",
    "runend": "end",
    "endedat": "end",
    "completedat": "end",
    "instrumentname": "instrument_name",
}
_JSON_PERSONAL = frozenset(
    {
        "operator",
        "user",
        "username",
        "owner",
        "createdby",
        "experimenter",
        "filename",
        "filepath",
        "path",
        "barcode",
        "comment",
        "comments",
        "notes",
        "description",
        "email",
        "name",
    }
)


def _json_leaves(data: Any) -> Iterator[tuple[str, str, Any]]:
    """``(path, normalised key, value)`` for scalar leaves, bounded in depth and node count."""
    budget = [MAX_JSON_NODES]

    def walk(node: Any, path: str, depth: int) -> Iterator[tuple[str, str, Any]]:
        if budget[0] <= 0 or depth > MAX_JSON_DEPTH:
            return
        budget[0] -= 1
        if isinstance(node, dict):
            for key in sorted(node, key=str):
                child = f"{path}.{key}" if path else str(key)
                value = node[key]
                if isinstance(value, dict | list):
                    yield from walk(value, child, depth + 1)
                else:
                    budget[0] -= 1
                    yield child, re.sub(r"[^a-z0-9]", "", str(key).lower()), value
        elif isinstance(node, list):
            for index, value in enumerate(node[:200]):
                yield from walk(value, f"{path}[{index}]", depth + 1)

    yield from walk(data, "", 0)


def _eds_summary_json(raw: bytes, rel: str, b: _Builder) -> str | None:
    """Map the keys that look like run or identity fields; record the rest as unmapped keys."""
    try:
        data = json.loads(_decode(raw))
    except (json.JSONDecodeError, RecursionError):
        b.note(f"{rel}: not readable JSON")
        return None
    state: str | None = None
    unmapped = 0
    for path, key, value in _json_leaves(data):
        pointer = f"{rel}:{path}"
        parent = path.rsplit(".", 1)[0].lower() if "." in path else ""
        target = _JSON_FIELDS.get(key)
        if target == "serial" and "block" in parent:
            target = "block_serial"
        elif target == "serial" and re.search(r"cover|lid", parent):
            target = "cover_serial"
        elif target == "serial" and "optic" in parent:
            target = "optical_head_serial"
        if target is None and key in _JSON_PERSONAL:
            if value not in (None, ""):
                b.note(NOTE_PERSONAL_FIELD)
            continue
        if target is None or value is None or isinstance(value, bool):
            if target is None:
                unmapped += 1
                safe = re.sub(r"[^A-Za-z0-9_.\[\]-]", "_", path)[:80]
                if len(b.unmapped_keys) < MAX_UNMAPPED_KEYS:
                    b.unmapped_keys.append(f"{rel}:{safe}")
            continue
        if target == "state":
            state = state or _state_word(value)
            b.identity_paths.setdefault("_state", pointer)
        elif target in ("start", "end"):
            moment = _time_value(value)
            if moment is None:
                continue
            if target == "start" and b.start is None:
                b.start, b.identity_paths["_start"] = moment, pointer
            elif target == "end" and b.end is None:
                b.end, b.identity_paths["_end"] = moment, pointer
        elif target == "instrument_name":
            b.alias(str(value), "instrument_name", pointer)
        else:
            clean = _clean_id(value) if "serial" in target else _clean_text(value, 64)
            b.set_identity(target, clean, pointer)
    if unmapped:
        b.note(NOTE_UNMAPPED)
    return state


# ---- messages.log: a curated event vocabulary (line syntax unverified) ----

_LOG_TIME = re.compile(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})")
_LOG_CYCLE = re.compile(r"\bcycle\s*(?:#|no\.?)?\s*[:=]?\s*(\d{1,3})\b", re.I)
_LOG_KEYWORDS = re.compile(
    r"paus|resum|lid|cover|drawer|tray|door|abort|power|run |cycle|serial|stopp|terminat", re.I
)
_LOG_EVENTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("abort", re.compile(r"\babort(ed|ing)?\b|\brun (was )?(stopped|terminated)\b", re.I)),
    (
        "power",
        re.compile(
            r"\bpower (failure|fail|loss|lost|outage|interrupt\w*)\b|" r"\bpowered (off|down)\b",
            re.I,
        ),
    ),
    ("pause", re.compile(r"\b(run )?paused\b|\bpausing\b", re.I)),
    ("resume", re.compile(r"\bresum(ed|ing)\b", re.I)),
    ("lid_open", re.compile(r"\b(lid|cover|heated cover) (was |is )?open(ed)?\b", re.I)),
    ("drawer", re.compile(r"\b(drawer|tray|door) (was |is )?(open(ed)?|eject(ed)?)\b", re.I)),
)
_LOG_CLOSED = re.compile(r"\b(lid|cover|drawer|tray|door) (was |is )?closed\b", re.I)
_LOG_START = re.compile(r"\brun (started|starting|begun|began)\b", re.I)
_LOG_DONE = re.compile(
    r"\brun (completed|complete|finished|ended)\b|\brun has (completed|finished)\b", re.I
)
_LOG_SERIAL = re.compile(r"serial number\s*[:=]\s*(?P<rest>.*)$", re.I)
_SERIAL_TOKEN = r"[A-Za-z0-9][A-Za-z0-9_.\-]{2,39}"
_SERIAL_LABELS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("block_serial", re.compile(r"block", re.I)),
    ("cover_serial", re.compile(r"cover|lid", re.I)),
    ("optical_head_serial", re.compile(r"optic|camera", re.I)),
    ("serial", re.compile(r"instrument|system|base|main", re.I)),
)


@dataclass
class _LogRead:
    """What the message log says: events during the run, start serials, completion."""

    source: str = ""
    events: list[dict[str, Any]] = field(default_factory=list)
    serials: list[tuple[str, str, str]] = field(default_factory=list)
    completed: int = 0  # line number of "run completed", 0 if absent
    aborted: int = 0
    capped: bool = False


def _log_serials(rest: str, pointer: str) -> list[tuple[str, str, str]]:
    """Serials on a run-start line: ``Serial Number: X [Block] Y [Heated Cover]`` (either order)."""
    rest = rest.strip()
    if rest.startswith("["):
        pairs = [
            (label, value)
            for label, value in re.findall(
                rf"\[([^\]]{{1,30}})\]\s*[:=]?\s*({_SERIAL_TOKEN})", rest
            )
        ]
    else:
        pairs = [
            (label, value)
            for value, label in re.findall(rf"({_SERIAL_TOKEN})\s*\[([^\]]{{1,30}})\]", rest)
        ]
    out: list[tuple[str, str, str]] = []
    for label, value in pairs:
        key = next((k for k, pattern in _SERIAL_LABELS if pattern.search(label)), None)
        clean = _clean_id(value)
        if key and clean:
            out.append((key, clean, pointer))
    if not pairs:
        first = re.match(rf"^({_SERIAL_TOKEN})\b", rest)
        if first and _clean_id(first[1]):
            out.append(("serial", _clean_id(first[1]) or "", pointer))
    return out


def _parse_log(text: str, source: str) -> _LogRead:
    """Events during the run from the instrument's message log; the text itself is never kept.

    Only lines matching the fixed vocabulary count (run started/completed, paused, resumed, lid,
    cover, drawer or tray opened/closed, aborted, power). Lines with a ``?`` are configuration
    queries and are skipped, so the thousands of harmless ``ERRor`` query lines never count.
    An event is during the run when it comes after "run started" and before "run completed"
    (or, in a log without a start line, after the first cycle). The cycle is the one on the
    line, else the last one the log named.
    """
    out = _LogRead(source=source)
    current: int | None = None
    seen_start = False
    done = False
    raw_events: list[dict[str, Any]] = []
    closers: list[tuple[int, int | None]] = []  # (line, cycle) of resume / closed lines
    for number, line in enumerate(text.splitlines(), start=1):
        if not _LOG_KEYWORDS.search(line) or "?" in line:
            continue
        if cycle := _LOG_CYCLE.search(line):
            current = int(cycle[1])
        if _LOG_START.search(line):
            if not seen_start:
                seen_start = True
                if serial := _LOG_SERIAL.search(line):
                    out.serials = _log_serials(serial["rest"], f"{source}:line {number}")
            continue
        if _LOG_DONE.search(line):
            if not out.completed:
                out.completed = number
            done = True
            continue
        in_run = not done if seen_start else current is not None
        kind = next((k for k, pattern in _LOG_EVENTS if pattern.search(line)), None)
        if kind is None:
            if _LOG_CLOSED.search(line):
                closers.append((number, current))
            continue
        if kind == "resume":
            closers.append((number, current))
        if not in_run:
            continue
        if kind == "abort" and not out.aborted:
            out.aborted = number
        stamp = _LOG_TIME.search(line[:48])
        at = None
        if stamp:
            try:
                at = dt.datetime(*(int(g) for g in stamp.groups())).strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                at = None
        if len(raw_events) >= MAX_EVENTS:
            out.capped = True
            continue
        raw_events.append(
            {
                "kind": kind,
                "at": at,
                "cycle": current,
                "source": f"{source}:line {number}",
                "_line": number,
            }
        )
    for event in raw_events:
        line = event.pop("_line")
        if event["kind"] in INTERRUPTIONS:
            start = event["cycle"]
            end = next((cyc for ln, cyc in closers if ln > line), None)
            if start is None:
                event["cycles"] = []
            else:
                last = max(start + 1, end if end is not None else start)
                event["cycles"] = list(range(start, min(last, start + MAX_CYCLES_NAMED - 1) + 1))
        out.events.append(event)
    return out


def _add_events(b: _Builder, log: _LogRead) -> None:
    if log.capped:
        b.note(NOTE_EVENTS_CAPPED)
    if any(e["at"] for e in log.events):
        b.note(NOTE_TZ_NOT_IN_FILE)
    b.fact("n_events", len(log.events), log.source)
    for index, event in enumerate(log.events, start=1):
        b.fact(f"event_{index}_kind", event["kind"], event["source"])
        if event["cycle"] is not None:
            b.fact(f"event_{index}_cycle", event["cycle"], event["source"])
        if event.get("cycles"):
            b.fact(f"event_{index}_first_cycle", event["cycles"][0], event["source"])
            b.fact(f"event_{index}_last_cycle", event["cycles"][-1], event["source"])
    b.events = log.events


# ---- logs/temperature.log (layout unverified) ----


def _temperature_role(header: str) -> str | None:
    name = header.strip().lower()
    if "lid" in name or "cover" in name:
        return "lid_setpoint" if "set" in name or "target" in name else "lid"
    if "set" in name or "target" in name:
        return "setpoint"
    if "sample" in name:
        return "sample"
    if re.search(r"(block|zone)\s*[_#-]?\s*\d+", name):
        return "zone"
    if name.startswith("block"):
        return "block"
    if "cycle" in name:
        return "cycle"
    return None


def _temperature_summary(text: str) -> dict[str, float | None] | None:
    """Hold deviation, zone spread and lowest lid temperature from a tabular temperature log.

    A header row (within the first fifty lines) names the columns; rows that are not all
    numeric in the needed columns are skipped. A hold is a setpoint that stays within
    :data:`SETPOINT_STEP_C` for at least :data:`HOLD_MIN_ROWS` rows. The ramp into a hold is
    not part of it: a hold is measured from the first row whose sample temperature is within
    :data:`SETTLE_BAND_C` of the setpoint or has crossed it (so an overshoot counts), or, when
    it never gets there, on its last row only (so a block that cannot reach its setpoint still
    shows). Cycling is the rows with a cycle number of one or more (or, without a cycle column,
    the rows between the first and last setpoint change).

    Returns:
        ``max_hold_deviation_c``, ``zone_spread_p95_c``, ``min_lid_c_cycling`` (rounded to two
        decimals, ``None`` where the log lacks the columns), or ``None`` when no header row
        with a setpoint, a zone or a lid column is found.
    """
    lines = text.splitlines()
    header_at = None
    delimiter: str | None = None
    roles: dict[int, str] = {}
    for index, line in enumerate(lines[:50]):
        for sep in (",", "\t", ";", None):
            cells = line.split(sep) if sep else line.split()
            if len(cells) < 3:
                continue
            found = {i: r for i, c in enumerate(cells) if (r := _temperature_role(c))}
            if sum(1 for c in cells if re.search(r"[A-Za-z]", c)) >= 2 and found:
                header_at, delimiter, roles = index, sep, found
                break
        if header_at is not None:
            break
    if header_at is None:
        return None
    rows: list[list[float]] = []
    wanted = sorted(roles)
    for line in lines[header_at + 1 : header_at + 1 + MAX_TEMPERATURE_ROWS]:
        cells = line.split(delimiter) if delimiter else line.split()
        try:
            rows.append([float(cells[i]) for i in wanted])
        except (IndexError, ValueError):
            continue
    if not rows:
        return None
    table = np.asarray(rows, dtype=float)
    column = {i: table[:, n] for n, i in enumerate(wanted)}
    by_role: dict[str, list[np.ndarray]] = {}
    for i, role in roles.items():
        by_role.setdefault(role, []).append(column[i])
    zones = np.column_stack(by_role["zone"]) if by_role.get("zone") else None
    if by_role.get("sample"):
        sample = by_role["sample"][0]
    elif zones is not None:
        sample = zones.mean(axis=1)
    else:
        sample = by_role["block"][0] if by_role.get("block") else None
    setpoint = by_role["setpoint"][0] if by_role.get("setpoint") else None
    hold = np.zeros(len(table), dtype=bool)
    if setpoint is not None:
        change = np.flatnonzero(np.abs(np.diff(setpoint)) >= SETPOINT_STEP_C) + 1
        bounds = [0, *change.tolist(), len(table)]
        off = np.abs(sample - setpoint) if sample is not None else None
        for lo, hi in zip(bounds[:-1], bounds[1:], strict=True):
            if hi - lo < HOLD_MIN_ROWS:
                continue
            if off is None:
                hold[lo:hi] = True
                continue
            signed = (sample - setpoint)[lo:hi]
            crossed = np.flatnonzero(np.sign(signed) != np.sign(signed[0]))
            settled = np.flatnonzero(off[lo:hi] <= SETTLE_BAND_C)
            first = min(
                crossed[0] if len(crossed) else hi - lo - 1,
                settled[0] if len(settled) else hi - lo - 1,
            )
            hold[lo + first : hi] = True
    out: dict[str, float | None] = {
        "max_hold_deviation_c": None,
        "zone_spread_p95_c": None,
        "min_lid_c_cycling": None,
    }
    if setpoint is not None and sample is not None and hold.any():
        out["max_hold_deviation_c"] = round(float(np.max(np.abs(sample - setpoint)[hold])), 2)
    if zones is not None and zones.shape[1] >= 2:
        rows_used = hold if hold.any() else np.ones(len(table), dtype=bool)
        spread = (zones.max(axis=1) - zones.min(axis=1))[rows_used]
        out["zone_spread_p95_c"] = round(float(np.percentile(spread, 95)), 2)
    if by_role.get("lid"):
        lid = by_role["lid"][0]
        if by_role.get("cycle"):
            cycling = by_role["cycle"][0] >= 1
        elif setpoint is not None:
            changes = np.flatnonzero(np.abs(np.diff(setpoint)) >= SETPOINT_STEP_C)
            cycling = np.zeros(len(table), dtype=bool)
            if len(changes) >= 3:
                cycling[changes[0] + 1 : changes[-1] + 1] = True
        else:
            cycling = np.zeros(len(table), dtype=bool)
        if cycling.any():
            out["min_lid_c_cycling"] = round(float(np.min(lid[cycling])), 2)
    if all(value is None for value in out.values()):
        return None
    return out


# ---------------------------------------------------------------------------------------------
# Text exports: QuantStudio results header and CFX Run Information
# ---------------------------------------------------------------------------------------------

_QS_MARKERS = (
    "block type",
    "instrument type",
    "instrument serial number",
    "experiment run end time",
    "passive reference",
)
_CFX_MARKERS = (
    "run started",
    "run ended",
    "base serial number",
    "optical head serial number",
    "cfx maestro version",
    "cfx manager version",
)


#: A Design & Analysis 2.x header line: the key runs to the first colon (one real file writes
#: ``Heated Cover Serial Number:`` with no space after it); the value may hold commas and colons.
_HASH_KEY_VALUE = re.compile(r"^#\s*([A-Za-z][^:]{0,79}?)\s*:\s*(.*)$")


def _key_value(line: str) -> tuple[str, str] | None:
    """``(key, value)`` from a header row (``k,v,,``, tabbed, ``* k = v`` or ``# Key: Value``)."""
    text = line.strip()
    if not text:
        return None
    if text.startswith("#"):
        match = _HASH_KEY_VALUE.match(text)
        return (match[1].strip(), match[2].strip()) if match else None
    if text.startswith("*"):
        match = re.match(r"^\*\s*(.+?)\s*=\s*(.*)$", text)
        return (match[1].strip(), match[2].strip()) if match else None
    if "\t" in text and "," not in text.split("\t", 1)[0]:
        fields = text.split("\t")
    elif "," in text:
        try:
            fields = next(csv.reader([text]))
        except csv.Error:
            return None
    else:
        match = re.match(r"^([A-Za-z][A-Za-z ]{1,60}?):\s+(.*)$", text)
        return (match[1].strip(), match[2].strip()) if match else (text, "")
    if not fields:
        return None
    return fields[0].strip(), (fields[1].strip() if len(fields) > 1 else "")


def _read_text_export(file: Path, date_order: str | None) -> RunContext:
    raw = file.read_bytes()
    text = _decode(raw)
    if "\x00" in text:
        raise InstrumentFileError(f"{file.name}: not a text export")
    lines = text.splitlines()
    if len(lines) > MAX_EXPORT_LINES:
        raise InstrumentFileError(f"{file.name}: more than {MAX_EXPORT_LINES} lines")
    keys = [kv[0].lower() for line in lines[:HEADER_SCAN_LINES] if (kv := _key_value(line))]
    qs = sum(1 for k in keys if k in _QS_MARKERS or k.startswith("calibration "))
    cfx = sum(1 for k in keys if k in _CFX_MARKERS)
    suffix = file.suffix.lower() if file.suffix.lower() in (".csv", ".txt", ".tsv") else ".txt"
    if qs and qs >= cfx:
        return _read_quantstudio(file.name, lines, f"export{suffix}", date_order)
    if cfx:
        return _read_cfx(file.name, lines, f"run_information{suffix}", date_order)
    raise InstrumentFileError(
        f"{file.name}: not a recognised instrument export (no QuantStudio header and no CFX "
        "Run Information keys)"
    )


_QS_EXPIRED = re.compile(r"^calibration\s+(?P<what>.+?)\s+is\s+expired$", re.I)
_QS_PERFORMED = re.compile(r"^calibration\s+(?P<what>.+?)\s+performed\s+on$", re.I)
_QS_SERIALS = {
    "instrument serial number": "serial",
    "heated cover serial number": "cover_serial",  # Design & Analysis 2.x
    "block serial number": "block_serial",  # Design & Analysis 2.x
}
#: Run start and end keys, spelled as the files spell them: the results export's, then Design &
#: Analysis 2.x's (a QuantStudio's "Run End Data/Time", a 7500's "Plate Run ... Date/Time").
_QS_RUN_TIMES = {
    "experiment run start time": "start",
    "experiment run end time": "end",
    "run start date/time": "start",
    "run end data/time": "end",
    "plate run start date/time": "start",
    "plate run end date/time": "end",
}


def _cal_type(what: str) -> tuple[str, str] | None:
    label = _clean_text(what, 40)
    if not label or not _SAFE_LABEL.match(label):
        return None
    return slug(label), label


def _read_quantstudio(
    name: str, lines: Sequence[str], label: str, date_order: str | None
) -> RunContext:
    """The QuantStudio results export: header rows or ``# Key: Value`` lines, then flag columns."""
    b = _Builder(source_file=name, source_kind="quantstudio_export")
    header: list[tuple[int, str, str]] = []
    table_at: list[int] = []
    for number, line in enumerate(lines, start=1):
        kv = _key_value(line)
        if kv is None:
            continue
        key, value = kv
        if key.lower() in ("well", "well position") or key.startswith("["):
            table_at.append(number)
            continue
        if number <= HEADER_SCAN_LINES and not table_at:
            header.append((number, key, value))
    order = date_order or _date_order(
        v for _, k, v in header if _QS_PERFORMED.match(k) or "time" in k.lower()
    )
    cals: dict[str, _Cal] = {}
    for number, key, value in header:
        pointer = f"{label}:line {number}"
        lower = key.lower()
        if match := _QS_EXPIRED.match(key):
            found = _cal_type(match["what"])
            if found and value.lower() in ("yes", "no", "true", "false", "y", "n"):
                cal = cals.setdefault(found[0], _Cal(type=found[0], label=found[1], source=pointer))
                cal.expired_flag = value.lower() in ("yes", "true", "y")
                cal.expired_source = pointer
        elif match := _QS_PERFORMED.match(key):
            found = _cal_type(match["what"])
            if found and value:
                cal = cals.setdefault(found[0], _Cal(type=found[0], label=found[1], source=pointer))
                cal.source = pointer
                day, ambiguous = _parse_date(value, order)
                cal.performed = day
                if ambiguous:
                    b.note(NOTE_DATE_AMBIGUOUS)
                    cal.raw_date = value.strip().split(" ")[0]
        elif lower == "instrument type":
            b.set_identity("model", _clean_text(value, 80), pointer)
        elif lower in _QS_SERIALS:
            b.set_identity(_QS_SERIALS[lower], _clean_id(value), pointer)
        elif lower == "instrument name":
            b.alias(value, "instrument_name", pointer)
        elif lower == "block type":
            block_type = _clean_text(value, 60)
            if block_type:
                b.identity["block_type"] = block_type
                b.fact("block_type", block_type, pointer)
        elif lower in ("software version", "software name and version"):
            b.set_identity("software", _clean_text(value, 64), pointer)
        elif lower in _QS_RUN_TIMES:
            parsed = _parse_vendor_time(value, order)
            moment, day = parsed.moment, parsed.day
            if parsed.note:
                b.note(parsed.note)
            if moment is None:
                continue
            if parsed.zone:
                b.run_zone = parsed.zone
                b.fact("run_time_zone", parsed.zone, pointer)
            which = _QS_RUN_TIMES[lower]
            if which == "end":
                b.end, b.end_text = moment, _iso(moment)
                b.identity_paths["_end"] = pointer
            else:
                b.start, b.start_text = moment, _iso(moment)
                b.identity_paths["_start"] = pointer
            if day is not None and (b.local_date is None or which == "start"):
                b.local_date = day
                b.identity_paths["_date"] = pointer
        elif lower == "experiment file name" and value:
            b.note(NOTE_OPERATOR_PATH)
        elif lower in ("file name", "plate file name") and value:  # Design & Analysis 2.x
            b.note(NOTE_OPERATOR_PATH if re.search(r"[/\\]", value) else NOTE_PERSONAL_FIELD)
        elif lower in ("comment", "description") and value:  # Design & Analysis 2.x
            b.note(NOTE_PERSONAL_FIELD)
        elif lower in ("user name", "user", "operator") and value:
            b.note(NOTE_USER_NAME)
    b.calibrations = [cals[k] for k in sorted(cals)]
    for kind, fact_name in (("_start", "run_start"), ("_end", "run_end")):
        moment = b.start if kind == "_start" else b.end
        if moment is not None:
            b.fact(fact_name, _iso(moment), b.identity_paths[kind])
    if b.start or b.end:
        b.date_source = "instrument"
    _well_flags(lines, table_at, label, b)
    return b.build()


def _well_flags(lines: Sequence[str], tables: Sequence[int], label: str, b: _Builder) -> None:
    """Per-well vendor flags: upper-case columns whose every value is ``Y`` or ``N``."""
    found_any = False
    for start in tables:
        head = lines[start - 1]
        delimiter = "\t" if "\t" in head else ","
        try:
            header = next(csv.reader([head], delimiter=delimiter))
        except csv.Error:
            continue
        header = [h.strip() for h in header]
        lower = [h.lower() for h in header]
        if "well" not in lower:
            continue
        well_col = lower.index("well position") if "well position" in lower else lower.index("well")
        flag_cols = [i for i, h in enumerate(header) if re.fullmatch(r"[A-Z][A-Z0-9]{2,15}", h)]
        rows: list[list[str]] = []
        for line in lines[start:]:
            if not line.strip() or line.lstrip().startswith("["):
                break
            try:
                rows.append([c.strip() for c in next(csv.reader([line], delimiter=delimiter))])
            except csv.Error:
                break
        flags: list[int] = []
        for i in flag_cols:
            values = {r[i].upper() for r in rows if i < len(r) and r[i]}
            if values and values <= {"Y", "N"}:
                flags.append(i)
        if not flags:
            continue
        found_any = True
        counts: dict[str, int] = {}
        for offset, row in enumerate(rows, start=1):
            if well_col >= len(row) or not re.fullmatch(
                r"[A-Za-z]{1,2}\d{1,3}|\d{1,4}", row[well_col]
            ):
                continue
            well = row[well_col].upper()
            for i in flags:
                if i < len(row) and row[i].upper() == "Y":
                    names = b.well_flags.setdefault(well, [])
                    if header[i] not in names:
                        names.append(header[i])
                        counts[header[i]] = counts.get(header[i], 0) + 1
                    b.well_rows.setdefault(well, f"{label}:line {start + offset}")
        pointer = f"{label}:line {start}"
        for flag in sorted(header[i] for i in flags):
            b.fact(f"flag_{slug(flag)}_wells", counts.get(flag, 0), pointer)
    for well, names in b.well_flags.items():
        names.sort()
        b.fact(f"well_{slug(well)}_flags", ", ".join(names), b.well_rows[well])
    if found_any:
        b.checked.add("well_flags")
        b.fact("n_flagged_wells", len(b.well_flags), f"{label}:flag columns")


_CFX_FIELDS = {
    "base serial number": "serial",
    "optical head serial number": "optical_head_serial",
    "cfx maestro version": "software",
    "cfx manager version": "software",
    "instrument type": "model",
    "instrument model": "model",
    "firmware version": "firmware",
}
_CFX_PERSONAL = frozenset(
    {
        "user",
        "created by user",
        "file name",
        "notes",
        "id",
        "protocol file name",
        "plate setup file name",
        "data file",
        "operator",
    }
)


def _read_cfx(name: str, lines: Sequence[str], label: str, date_order: str | None) -> RunContext:
    """A Bio-Rad CFX "Run Information" export (key/value rows; layout unverified)."""
    b = _Builder(source_file=name, source_kind="cfx_run_information")
    rows = [
        (number, kv[0], kv[1])
        for number, line in enumerate(lines[:HEADER_SCAN_LINES], start=1)
        if (kv := _key_value(line))
    ]
    order = date_order or _date_order(
        v for _, k, v in rows if k.lower() in ("run started", "run ended")
    )
    for number, key, value in rows:
        pointer = f"{label}:line {number}"
        lower = key.lower().rstrip(":")
        if lower in ("run started", "run ended"):
            parsed = _parse_vendor_time(value, order)
            moment, day = parsed.moment, parsed.day
            if parsed.note:
                b.note(parsed.note)
            if moment is None:
                continue
            if parsed.zone:
                b.run_zone = parsed.zone
                b.fact("run_time_zone", parsed.zone, pointer)
            if lower == "run started":
                b.start, b.start_text = moment, _iso(moment)
                b.identity_paths["_start"] = pointer
                b.local_date = day
                b.identity_paths["_date"] = pointer
            else:
                b.end, b.end_text = moment, _iso(moment)
                b.identity_paths["_end"] = pointer
                if b.local_date is None:
                    b.local_date = day
                    b.identity_paths["_date"] = pointer
        elif lower in _CFX_FIELDS:
            target = _CFX_FIELDS[lower]
            clean = _clean_id(value) if "serial" in target else _clean_text(value, 64)
            if target == "software" and clean:
                clean = ("CFX Maestro " if "maestro" in lower else "CFX Manager ") + clean
            b.set_identity(target, clean, pointer)
        elif lower in ("run status", "run state", "status"):
            b.state = _state_word(value)
            if b.state:
                b.fact("run_state", b.state, pointer)
        elif lower in _CFX_PERSONAL and value:
            b.note(
                NOTE_USER_NAME if "user" in lower or lower == "operator" else NOTE_PERSONAL_FIELD
            )
    if b.identity.get("model") is None:
        b.set_identity("model", "Bio-Rad CFX", f"{label}:Run Information keys")
    for kind, fid in (("_start", "run_start"), ("_end", "run_end")):
        moment = b.start if kind == "_start" else b.end
        if moment is not None:
            b.fact(fid, _iso(moment), b.identity_paths[kind])
    if b.start or b.end:
        b.date_source = "instrument"
    return b.build(stepone=False)


# ---------------------------------------------------------------------------------------------
# RDML
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _RdmlRun:
    experiment_id: str
    run_id: str
    instrument: str | None
    run_date: str | None
    software_name: str | None
    software_version: str | None
    member: str


def _rdml_contexts_from_bytes(data: bytes, name: str, *, member: str = "rdml") -> list[RunContext]:
    """Stream the RDML XML and keep only each run's header elements (reactions are dropped)."""
    records: list[_RdmlRun] = []
    experiment = ""
    parser_args = {
        "resolve_entities": False,
        "no_network": True,
        "load_dtd": False,
        "huge_tree": False,
    }
    try:
        stream = etree.iterparse(
            io.BytesIO(data),
            events=("start", "end"),
            tag=("{*}experiment", "{*}run", "{*}react"),
            **parser_args,
        )
        for event, element in stream:
            local = etree.QName(element).localname
            if event == "start":
                if local == "experiment":
                    experiment = element.get("id") or ""
                continue
            if local == "react":
                element.clear(keep_tail=True)
            elif local == "run":
                records.append(_rdml_record(element, experiment, member))
                element.clear(keep_tail=True)
    except etree.XMLSyntaxError as err:
        raise InstrumentFileError(f"{name}: not a valid RDML or XML file ({err})") from err
    if not records and not re.search(rb"<(\w+:)?rdml\b", data[:4096]):
        raise InstrumentFileError(f"{name}: an XML file, but not RDML")
    return [_rdml_run_context(record, name) for record in records]


def _child_text(element: Any, local: str) -> str | None:
    for child in element:
        if isinstance(child.tag, str) and etree.QName(child).localname == local:
            return child.text
    return None


def _rdml_record(run: Any, experiment: str, member: str) -> _RdmlRun:
    software = next(
        (
            c
            for c in run
            if isinstance(c.tag, str) and etree.QName(c).localname == "dataCollectionSoftware"
        ),
        None,
    )
    return _RdmlRun(
        experiment_id=experiment,
        run_id=run.get("id") or "",
        instrument=_child_text(run, "instrument"),
        run_date=_child_text(run, "runDate"),
        software_name=_child_text(software, "name") if software is not None else None,
        software_version=_child_text(software, "version") if software is not None else None,
        member=member,
    )


_BIORAD_KEYS = {
    "cycler sn": "serial",
    "shuttle sn": "shuttle_serial",
    "optical head sn": "optical_head_serial",
}
_LIGHTCYCLER = re.compile(r"^(?P<model>LC\s?\d{2,3})\s?SN\s?(?P<serial>[A-Za-z0-9]{3,20})$", re.I)


def parse_instrument_string(text: str | None) -> dict[str, str | None]:
    """Identity fields from an RDML ``run.instrument`` string.

    A Bio-Rad CFX export writes ``Block Type "96FX", Cycler SN: …, … Firmware: …, Shuttle SN: …,
    Optical Head SN: …`` (split on commas, then on ``": "``). A LightCycler 96 writes
    ``LC96SN<serial>``. Any other text gives a model only when it names a known instrument.

    Returns:
        ``model``, ``instrument_type`` (the block type), ``serial``, ``shuttle_serial``,
        ``optical_head_serial`` and ``firmware`` (``; ``-joined ``name: version`` items), each a
        string or ``None``.
    """
    out: dict[str, str | None] = dict.fromkeys(
        ("model", "instrument_type", "serial", "shuttle_serial", "optical_head_serial", "firmware")
    )
    clean = _clean_text(text, 600)
    if not clean:
        return out
    if re.search(r"\bSN:\s", clean) or clean.lower().startswith("block type"):
        out["model"] = "Bio-Rad CFX"
        firmware: list[str] = []
        for item in (part.strip() for part in clean.split(",")):
            key, sep, value = item.partition(": ")
            if not sep:
                match = re.match(r'^Block Type\s+"?([^"]{1,20})"?$', item, re.I)
                if match:
                    out["instrument_type"] = _clean_text(match[1], 20)
                continue
            lower = key.strip().lower()
            if lower in _BIORAD_KEYS:
                out[_BIORAD_KEYS[lower]] = _clean_id(value)
            elif ("firmware" in lower or "lid" in lower) and _SAFE_LABEL.match(key.strip()):
                version = _clean_text(value, 30)
                if version:
                    firmware.append(f"{key.strip()}: {version}")
        out["firmware"] = "; ".join(firmware) or None
        return out
    if match := _LIGHTCYCLER.match(clean):
        number = re.sub(r"\D", "", match["model"])
        out["model"] = f"LightCycler {number}"
        out["serial"] = _clean_id(match["serial"])
        return out
    if _KNOWN_MODEL.search(clean):
        out["model"] = clean[:80]
    return out


def _rdml_run_context(record: _RdmlRun, name: str) -> RunContext:
    b = _Builder(source_file=name, source_kind="rdml", run_id=record.run_id or None)
    base = f"{record.member}:experiment[{record.experiment_id}]/run[{record.run_id}]"
    if record.instrument and record.instrument.strip():
        parsed = parse_instrument_string(record.instrument)
        pointer = f"{base}/instrument"
        for key in ("model", "instrument_type", "serial", "optical_head_serial", "firmware"):
            b.set_identity(key, parsed[key], pointer)
        if parsed["shuttle_serial"]:
            b.identity["shuttle_serial"] = parsed["shuttle_serial"]
            b.fact("shuttle_serial", parsed["shuttle_serial"], pointer, local=True)
            b.aliases.add(parsed["shuttle_serial"])
        b.alias(record.instrument, "instrument_text", pointer)
    software = " ".join(
        part
        for part in (
            _clean_text(re.sub(r"\.exe$", "", record.software_name or "", flags=re.I), 40),
            _version_token(record.software_version),
        )
        if part
    )
    if software:
        b.set_identity("software", software, f"{base}/dataCollectionSoftware")
    moment = _parse_iso(record.run_date) if record.run_date else None
    if moment is not None and (moment.month, moment.day) != (1, 1) and moment.year >= 1996:
        b.start = moment
        b.start_text = _iso(moment)
        b.date_source = "instrument"
        b.fact("run_start", b.start_text, f"{base}/runDate")
        b.identity_paths["_date"] = f"{base}/runDate"
        if moment.tzinfo is None:
            b.note(NOTE_TZ_NOT_IN_FILE)
    elif moment is not None:
        b.note(NOTE_RUN_DATE_DOUBTFUL)
        b.fact("recorded_run_date", _iso(moment), f"{base}/runDate")
    if b.date_source is None and record.run_id:
        match = RUN_NAME_DATE.search(record.run_id)
        if match:
            try:
                day = dt.date(int(match["y"]), int(match["m"]), int(match["d"]))
            except ValueError:
                day = None
            if day is not None:
                b.local_date = day
                b.start_text = day.isoformat()
                b.date_source = "run name"
                b.fact("run_start", day.isoformat(), f"{base}/@id (run name)")
                b.identity_paths["_date"] = f"{base}/@id (run name)"
    return b.build()


def _version_token(text: str | None) -> str | None:
    """The leading version number of a software version text (``3.0.1224.1015. (OS-…`` -> ``…``)."""
    clean = _clean_text(text, 200)
    if not clean:
        return None
    match = re.search(r"\d+(?:\.\d+)+", clean)
    if match:
        return match[0]
    return clean[:30] if _SAFE_LABEL.match(clean[:30]) else None


def _combine_rdml(name: str, contexts: Sequence[RunContext]) -> RunContext:
    """One run: that run's context. Several: a file-level context that counts the runs."""
    if len(contexts) == 1:
        return contexts[0]
    b = _Builder(source_file=name, source_kind="rdml")
    for key in IDENTITY_KEYS:
        values = {ctx.identity.get(key) for ctx in contexts}
        value = next(iter(values)) if len(values) == 1 else None
        if value is not None:
            fact = contexts[0].facts.get(contexts[0].fact_id(key))
            path = fact.path.removeprefix(LOCAL_ONLY) if fact else "rdml:run/instrument"
            b.set_identity(key, value, path)
    for ctx in contexts:
        b.aliases.update(ctx.aliases)
    dated = [ctx for ctx in contexts if ctx.run.get("date")]
    b.note(NOTE_MANY_RUNS)
    for ctx in contexts:
        for note in ctx.notes:
            b.note(note)
    b.fact("n_runs", len(contexts), "rdml:run")
    with_instrument = sum(1 for c in contexts if c.fact_id("instrument_text") in c.facts)
    by_name = sum(1 for c in dated if c.run.get("date_source") == "run name")
    b.fact("n_runs_instrument", with_instrument, "rdml:run/instrument")
    b.fact("n_runs_dated", len(dated), "rdml:run/runDate or run name")
    b.fact("n_runs_dated_by_name", by_name, "rdml:run/@id (run name)")
    b.fact("n_run_dates", len({c.run["date"] for c in dated}), "rdml:run/runDate or run name")
    if dated:
        days = sorted(c.run["date"] for c in dated)
        b.fact("first_run_date", days[0], "rdml:run/runDate or run name")
        b.fact("last_run_date", days[-1], "rdml:run/runDate or run name")
    return b.build()
