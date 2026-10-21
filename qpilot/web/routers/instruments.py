"""Instruments routes: the registry, each instrument's logbook, incidents, run files, lookback.

The engine is origin/main's instrument registry and hash-chained logbook
(:mod:`qpilot.core.instruments`; ``$QPILOT_STUDIES_DIR/instruments/``), its run-file reader and
G-INSTR lines, and the lookback. On the command line and over MCP an agent may only *propose* an
incident ("a person confirms it in qPilot"); this is where a person does:

* ``GET /instruments`` and ``GET /instruments/{id}``: the instruments, the age of their latest
  calibrations, open incidents, and the logbook with whether its chain verifies (read-only).
* ``POST /instruments`` registers one; ``POST /instruments/{id}/events`` logs a calibration, a
  part change, a service visit, a move or a note; ``POST /instruments/{id}/incidents`` logs an
  incident a person saw; ``…/incidents/{seq}/confirm`` / ``…/reject`` decide an agent's
  proposal; ``…/incidents/{seq}/fix`` notes what fixed one. Every write is ``actor="human"``
  (the server sets it); the logbook refuses anything else for these.
* ``POST /instruments/runs`` (a run file: ``.eds``, a QuantStudio or CFX export, RDML) reads
  what it says about the instrument (no serial number comes back) and which registered
  instrument it names, or asks "Which instrument is this?"; ``POST /instruments/runs/{id}/link``
  answers it (the registry remembers the file's identity, locally) and logs what the file
  itself states (an aborted run, a pause).
* ``POST /studies/{id}/lookback`` (a job): which of the study's conclusions used that
  instrument between two dates, and what leaving those runs out changes. Writes nothing; blind
  like every result.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, UploadFile

from qpilot.core.instruments import (
    INSTRUMENT_ID,
    TYPED_KINDS,
    InstrumentError,
    Registry,
    UnknownInstrument,
    confirm_incident,
    event_view,
    log_fix,
    log_incident,
    log_typed,
    reject_incident,
    suggest_id,
)
from qpilot.web import results_views as rv
from qpilot.web import views
from qpilot.web.context import AppContext, Ctx, api_error
from qpilot.web.contract import JobStarted, JobView
from qpilot.web.contract_instruments import (
    CalibrationAge,
    EventBody,
    EventView,
    FixBody,
    FixView,
    GateLineView,
    IncidentBody,
    IncidentView,
    InstrumentSummary,
    InstrumentsView,
    InstrumentView,
    KindView,
    LinkBody,
    Linked,
    Logged,
    LookbackBody,
    LookbackChange,
    LookbackView,
    RegisterBody,
    RunFileView,
    RunQuestion,
)
from qpilot.web.jobs import JobError, Progress

router = APIRouter(tags=["instruments"])
JOB_RESULTS = {"lookback.run": LookbackView}

HUMAN = "human"
MAX_RUN_BYTES = 200 * 1024 * 1024
RUN_SUFFIXES = (".eds", ".csv", ".txt", ".rdml", ".xml")
RUN_ID = re.compile(r"^[0-9a-f]{24}\Z")
LOOKBACK_S = 6.0  # one re-analysis of the study without the window's runs (demo, loaded laptop)
KIND_WORDS = {
    "calibration": "Calibration",
    "component_change": "Part changed",
    "firmware_change": "Firmware changed",
    "software_change": "Software changed",
    "run_event": "Run event",
    "service": "Service visit",
    "move": "Moved",
    "incident": "Incident",
    "fix": "Fix",
    "note": "Note",
    "lookback": "Lookback",
}
NOTE = (
    "A working memory for the lab, not a regulated record: what the run files say, what people "
    "logged, and incidents a person confirmed. Serial numbers stay in this computer's registry "
    "and are never shown or sent."
)


# ---- helpers --------------------------------------------------------------------------------


def registry(ctx: AppContext) -> Registry:
    """The registry next to this store's studies."""
    from qpilot.core.instruments import INSTRUMENTS_DIR

    return Registry(ctx.store.root / INSTRUMENTS_DIR)


def _refused(err: Exception) -> Exception:
    """The logbook's refusals as the API's errors (plain sentences)."""
    text = str(err).strip().rstrip(".")
    text = (text[:1].upper() + text[1:] + ".") if text else "That was refused."
    if isinstance(err, UnknownInstrument):
        return api_error(404, "not_found", text)
    return api_error(422, "bad_request", text)


def _id_ok(instrument_id: str) -> str:
    if not INSTRUMENT_ID.match(instrument_id or ""):
        raise api_error(404, "not_found", "There is no registered instrument with this id.")
    return instrument_id


def _day(value: str | None, what: str) -> str | None:
    if value is None or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10]).isoformat()
    except ValueError:
        raise api_error(422, "bad_request", f"{what} is a date such as 2008-03-18.") from None


def summary_of(reg: Registry, instrument: Any) -> InstrumentSummary:
    """One instrument's state now: calibration ages, open incidents, the chain's check."""
    book = reg.logbook(instrument.instrument_id)
    problems = book.verify()
    events, incidents = ([], []) if problems else (book.events(), book.incidents())
    today = datetime.now(UTC).date()
    latest: dict[str, CalibrationAge] = {}
    for event in events:
        if event.kind != "calibration":
            continue
        payload = event.payload or {}
        ctype = str(payload.get("type") or "calibration")
        when = str(payload.get("performed_on") or event.at or event.recorded_at)
        try:
            day = date.fromisoformat(when[:10])
        except ValueError:
            continue
        if ctype not in latest or day.isoformat() >= latest[ctype].performed_on:
            latest[ctype] = CalibrationAge(
                type=ctype,
                performed_on=day.isoformat(),
                age_days=(today - day).days,
                source=event.source,
            )
    open_ = [i for i in incidents if i.status != "rejected" and not i.fixes]
    public = instrument.public()
    return InstrumentSummary(
        instrument_id=public["instrument_id"],
        display_name=public["display_name"],
        make_model=public["make_model"],
        location=public["location"],
        shared=public["shared"],
        n_events=len(events),
        n_open_incidents=len(open_),
        n_proposed=sum(i.status == "proposed" for i in open_),
        calibrations=sorted(latest.values(), key=lambda c: c.type),
        chain_ok=not problems,
        problems=list(problems),
    )


def _event(event: Any) -> EventView:
    data = event_view(event, include_text=True)  # the person's own page: their text is shown
    payload = dict(data.get("payload") or {})
    note = str(payload.pop("note", "") or "")
    return EventView(
        seq=event.seq,
        kind=event.kind,
        kind_word=KIND_WORDS.get(event.kind, event.kind),
        source=event.source,
        actor=event.actor,
        at=event.at,
        recorded_at=event.recorded_at,
        run_hash=event.run_hash,
        wells=list(event.wells or ()),
        details={**payload, **({"signature": data["signature"]} if data.get("signature") else {})},
        note=note,
        hash=event.hash,
    )


def _incident(incident: Any) -> IncidentView:
    signature = incident.signature
    fixes = [
        FixView(
            seq=f.get("seq") if isinstance(f.get("seq"), int) else None,
            note=str(f.get("note") or ""),
            at=f.get("at"),
        )
        for f in incident.fixes
    ]
    return IncidentView(
        seq=incident.seq,
        status=incident.status,
        at=incident.at or incident.recorded_at,
        actor=incident.actor,
        run_hash=incident.run_hash,
        wells=list(incident.wells),
        metric=getattr(signature, "metric", None),
        direction=getattr(signature, "direction", None),
        error_code=getattr(signature, "error_code", None),
        note=incident.note,
        fixes=fixes,
        can_confirm=incident.status == "proposed",
        can_fix=incident.status == "confirmed" and not incident.fixes,
    )


def instrument_view(reg: Registry, instrument_id: str) -> InstrumentView:
    """One instrument with its logbook and incidents (a broken chain shows nothing replayed)."""
    instrument = reg.get(instrument_id)
    book = reg.logbook(instrument_id)
    summary = summary_of(reg, instrument)
    if summary.problems:  # a chain that does not verify is shown as broken, never replayed
        return InstrumentView(instrument=summary, events=[], incidents=[], head=book.head())
    return InstrumentView(
        instrument=summary,
        events=[_event(e) for e in book.events()],
        incidents=[_incident(i) for i in book.incidents()],
        head=book.head(),
    )


def _logged(ctx: AppContext, instrument_id: str, event: Any, message: str) -> Logged:
    ctx.bus.publish({"type": "instruments.changed", "key": instrument_id, "source": "page"})
    return Logged(
        message=message,
        seq=event.seq,
        instrument=instrument_view(registry(ctx), instrument_id),
    )


# ---- the registry and logbooks ----------------------------------------------------------------


@router.get("/instruments", response_model=InstrumentsView)
def list_instruments(ctx: Ctx) -> InstrumentsView:
    """Every registered instrument and its state now (read-only)."""
    reg = registry(ctx)
    try:
        instruments = [summary_of(reg, i) for i in reg.instruments()]
    except InstrumentError as err:
        raise api_error(409, "registry", f"The instrument registry cannot be read: {err}") from err
    return InstrumentsView(
        instruments=instruments,
        kinds=[KindView(id=k, word=KIND_WORDS[k]) for k in TYPED_KINDS],  # type: ignore[arg-type]
        as_of=datetime.now(UTC).date().isoformat(),
        note=NOTE,
    )


@router.post("/instruments", response_model=InstrumentView)
def register_instrument(body: RegisterBody, ctx: Ctx) -> InstrumentView:
    """Register an instrument: a name people use, its model and where it stands."""
    reg = registry(ctx)
    instrument_id = (body.instrument_id or "").strip()
    try:
        if not instrument_id:
            instrument_id = suggest_id(body.display_name)
        reg.register(
            instrument_id,
            body.display_name,
            make_model=body.make_model,
            location=body.location,
            shared=body.shared,
        )
    except InstrumentError as err:
        raise _refused(err) from err
    ctx.bus.publish({"type": "instruments.changed", "key": instrument_id, "source": "page"})
    return instrument_view(reg, instrument_id)


@router.get("/instruments/{instrument_id}", response_model=InstrumentView)
def get_instrument(instrument_id: str, ctx: Ctx) -> InstrumentView:
    """One instrument: its state, its logbook in chain order and its incidents (read-only)."""
    try:
        return instrument_view(registry(ctx), _id_ok(instrument_id))
    except InstrumentError as err:
        raise _refused(err) from err


@router.post("/instruments/{instrument_id}/events", response_model=Logged)
def log_event(instrument_id: str, body: EventBody, ctx: Ctx) -> Logged:
    """A person logs a calibration, a part change, a service visit, a move or a note."""
    reg = registry(ctx)
    at = _day(body.at, "The date")
    payload: dict[str, Any] = {}
    if body.kind == "calibration":
        payload["type"] = (body.calibration_type or "calibration").strip()[:60] or "calibration"
        payload["performed_on"] = at or datetime.now(UTC).date().isoformat()
    if body.kind == "component_change":
        if not (body.component or "").strip():
            raise api_error(422, "bad_request", "Say which part was changed.")
        payload["component"] = body.component.strip()[:60]
    if body.kind == "note" and not body.note.strip():
        raise api_error(422, "bad_request", "Write the note.")
    try:
        book = reg.logbook(_id_ok(instrument_id))
        reg.get(instrument_id)
        event = log_typed(book, body.kind, actor=HUMAN, note=body.note, at=at, payload=payload)
    except InstrumentError as err:
        raise _refused(err) from err
    return _logged(ctx, instrument_id, event, f"{KIND_WORDS[body.kind]} logged.")


@router.post("/instruments/{instrument_id}/incidents", response_model=Logged)
def log_incident_route(instrument_id: str, body: IncidentBody, ctx: Ctx) -> Logged:
    """A person logs an incident they saw (confirmed, since a person logs it)."""
    reg = registry(ctx)
    try:
        book = reg.logbook(_id_ok(instrument_id))
        reg.get(instrument_id)
        event = log_incident(
            book,
            actor=HUMAN,
            wells=[w.strip().upper() for w in body.wells],
            signature={"metric": body.metric, "direction": body.direction},
            run_hash=body.run_hash,
            note=body.note,
        )
    except InstrumentError as err:
        raise _refused(err) from err
    return _logged(ctx, instrument_id, event, "Incident logged, confirmed by you.")


@router.post("/instruments/{instrument_id}/incidents/{seq}/confirm", response_model=Logged)
def confirm_incident_route(instrument_id: str, seq: int, ctx: Ctx) -> Logged:
    """A person confirms an incident an agent proposed (only a person can)."""
    reg = registry(ctx)
    try:
        event = confirm_incident(reg.logbook(_id_ok(instrument_id)), seq, actor=HUMAN)
    except InstrumentError as err:
        raise _refused(err) from err
    return _logged(ctx, instrument_id, event, "Incident confirmed: it now counts as seen before.")


@router.post("/instruments/{instrument_id}/incidents/{seq}/reject", response_model=Logged)
def reject_incident_route(instrument_id: str, seq: int, ctx: Ctx) -> Logged:
    """A person turns down an incident an agent proposed (only a person can)."""
    reg = registry(ctx)
    try:
        event = reject_incident(reg.logbook(_id_ok(instrument_id)), seq, actor=HUMAN)
    except InstrumentError as err:
        raise _refused(err) from err
    return _logged(ctx, instrument_id, event, "Incident turned down: it matches nothing.")


@router.post("/instruments/{instrument_id}/incidents/{seq}/fix", response_model=Logged)
def fix_incident_route(instrument_id: str, seq: int, body: FixBody, ctx: Ctx) -> Logged:
    """A person notes what fixed an incident."""
    reg = registry(ctx)
    try:
        event = log_fix(
            reg.logbook(_id_ok(instrument_id)),
            seq,
            note=body.note,
            actor=HUMAN,
            at=_day(body.at, "The date"),
        )
    except InstrumentError as err:
        raise _refused(err) from err
    return _logged(ctx, instrument_id, event, "Fix noted.")


# ---- run files --------------------------------------------------------------------------------


async def _keep_run(ctx: AppContext, upload: UploadFile) -> Path:
    """Stream a run file to the kept-inputs folder, named by content (size-capped)."""
    import hashlib
    import shutil

    from qpilot.web.routers.workspaces import CHUNK

    name = Path(upload.filename or "").name
    suffix = Path(name).suffix.lower()
    if suffix not in RUN_SUFFIXES:
        raise api_error(
            400, "bad_file", f"{name or 'This file'}: expected an .eds, .csv, .txt or .rdml file."
        )
    folder = views.inputs_dir(ctx.store)
    digest = hashlib.sha256()
    tmp = folder / f".run-{id(upload)}{suffix}"
    size = 0
    try:
        with tmp.open("wb") as out:
            while chunk := await upload.read(CHUNK):
                size += len(chunk)
                if size > MAX_RUN_BYTES:
                    raise api_error(413, "too_large", f"{name} is larger than 200 MB.")
                digest.update(chunk)
                out.write(chunk)
        if size == 0:
            raise api_error(400, "empty_file", f"{name} is empty.")
        kept = folder / f"{digest.hexdigest()[:24]}{suffix}"
        if not kept.exists():
            shutil.move(str(tmp), kept)
        views.remember_name(kept, name)
        return kept
    finally:
        tmp.unlink(missing_ok=True)


def _run_path(ctx: AppContext, run_id: str) -> Path:
    if not RUN_ID.match(run_id or ""):
        raise api_error(404, "not_found", "There is no kept run file with this id.")
    folder = views.inputs_dir(ctx.store)
    for suffix in RUN_SUFFIXES:
        path = folder / f"{run_id}{suffix}"
        if path.is_file():
            return path
    raise api_error(404, "not_found", "There is no kept run file with this id; drop it again.")


def _read_run(path: Path) -> Any:
    from qpilot.qpcr.instrument_context import InstrumentFileError, read_run_context

    try:
        return read_run_context(path)
    except InstrumentFileError as err:
        raise api_error(422, "bad_file", f"This run file cannot be read: {err}") from err
    except (ValueError, OSError) as err:
        raise api_error(422, "bad_file", f"This run file cannot be read: {err}") from err


def run_view(ctx: AppContext, path: Path) -> RunFileView:
    """What a kept run file says, its G-INSTR lines and the instrument it names (no serial)."""
    from qpilot.explain.instrument_text import line_tokens
    from qpilot.qpcr.gate_instr import g_instr

    run = _read_run(path)
    lines = []
    for line in g_instr(run):
        try:
            tokens = line_tokens(line)
            text = rv.fact_text(tokens, line.facts)
            if any(ch.isdigit() for s in text.segments if s.fact is None for ch in s.text):
                text = rv.plain_text(f"{line.rule_id}: {line.status}.")
        except KeyError:
            text = rv.plain_text(f"{line.rule_id}: {line.status}.")
        lines.append(
            GateLineView(rule_id=line.rule_id, status=line.status, code=line.code, text=text)
        )
    reg = registry(ctx)
    summary = run.summary()
    try:
        instrument_id = reg.resolve(summary)
        question = reg.ask(summary)
    except InstrumentError:  # an unreadable registry never hides what the file says
        instrument_id, question = None, None
    return RunFileView(
        run_id=path.stem,
        name=views.display_name(path) or path.name,
        context=run.model_view(),
        gate=lines,
        instrument_id=instrument_id,
        question=RunQuestion(**question) if question else None,
    )


@router.post("/instruments/runs", response_model=RunFileView)
async def read_run(
    ctx: Ctx,
    run: Annotated[UploadFile, File(description="An .eds, a QuantStudio or CFX export, or RDML.")],
) -> RunFileView:
    """What a run file says about its instrument, and which registered instrument it names."""
    return run_view(ctx, await _keep_run(ctx, run))


@router.post("/instruments/runs/{run_id}/link", response_model=Linked)
def link_run(run_id: str, body: LinkBody, ctx: Ctx) -> Linked:
    """A person says which instrument the file is from; what the file states is logged once."""
    from qpilot.core.instruments import infer_events
    from qpilot.core.store import sha256_file

    path = _run_path(ctx, run_id)
    run = _read_run(path)
    reg = registry(ctx)
    summary = run.summary()
    instrument_id = _id_ok(body.instrument_id)
    run_hash = sha256_file(path)
    try:
        reg.remember(summary, instrument_id)
        book = reg.logbook(instrument_id)
        seen = {e.run_hash for e in book.events() if e.run_hash}
        events = [] if run_hash in seen else infer_events(None, summary)
        if events:
            book.append_many([{**e, "run_hash": run_hash} for e in events])
    except InstrumentError as err:
        raise _refused(err) from err
    ctx.bus.publish({"type": "instruments.changed", "key": instrument_id, "source": "page"})
    told = f"{len(events)} event(s) the file states were logged" if events else "nothing new"
    return Linked(
        instrument_id=instrument_id,
        n_logged=len(events),
        message=f"Linked: the next file from this instrument is recognised by itself ({told}).",
    )


# ---- the lookback -----------------------------------------------------------------------------


@router.post("/studies/{study_id}/lookback", response_model=JobStarted, status_code=202)
def run_lookback(study_id: str, body: LookbackBody, ctx: Ctx) -> JobStarted:
    """Which of the study's conclusions used the instrument in the window, and what changes."""
    from qpilot.explain.lookback_text import lookback_tokens
    from qpilot.mcp_server import run_map
    from qpilot.qpcr.lookback import LookbackError, lookback
    from qpilot.web.routers.results import study

    study(ctx, study_id)  # 404 unknown, 403 blind
    instrument_id = _id_ok(body.instrument_id)
    start, end = _day(body.start, "The first day"), _day(body.end, "The last day")
    try:
        registry(ctx).get(instrument_id)
    except InstrumentError as err:
        raise _refused(err) from err

    def work(progress: Progress) -> dict[str, Any]:
        progress("Leaving out the runs in the window and analysing the study again", 0.2)
        try:
            mapping, assumed = run_map(ctx.store, [study_id], instrument_id)
            result = lookback(ctx.store, mapping, instrument_id, start, end, studies=[study_id])
        except LookbackError as err:
            raise JobError("bad_request", str(err)) from err
        found = next((s for s in result.studies if s.study_id == study_id), None)
        try:
            text = rv.fact_text(lookback_tokens(result), result.facts)
        except Exception:  # the numbers are still shown in the fields
            text = rv.plain_text("The lookback could not be shown in words.")
        return LookbackView(
            study_id=study_id,
            instrument_id=instrument_id,
            start=str(start),
            end=str(end),
            status=found.status if found else "no_runs_in_window",
            n_conclusions=found.n_conclusions if found else 0,
            n_changed=found.n_changed if found else 0,
            changed=[
                LookbackChange(gene=g.gene, before=g.before, after=g.after)
                for g in (found.changed if found else [])
            ],
            runs_in_window=list(found.runs_in_window) if found else [],
            n_wells_in_window=found.n_wells_in_window if found else 0,
            assumed_all_runs=study_id in assumed,
            text=text,
        ).model_dump(mode="json")

    job = ctx.jobs.submit(
        "lookback.run",
        work,
        title="Looking back over an instrument's period",
        key=study_id,
        typical_s=LOOKBACK_S,
    )
    return JobStarted(job=JobView(**job.view()))
