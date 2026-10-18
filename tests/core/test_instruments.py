"""The instrument registry, inferred events, the hash-chained logbook and incident memory."""

import hashlib
import json
import multiprocessing as mp

import pytest

from qpilot.core import instruments as inst
from qpilot.core.instruments import (
    QUESTION,
    SEEN_BEFORE,
    InstrumentError,
    Logbook,
    LogbookError,
    Registry,
    UnknownInstrument,
    canonical_line,
    chain_root,
    confirm_incident,
    event_hash,
    event_view,
    infer_events,
    instruments_root,
    log_fix,
    log_incident,
    log_typed,
    match_incidents,
    proposed_window,
    reject_incident,
    suggest_id,
)
from qpilot.core.store import StudyNotFound, StudyStore

SERIAL = "272530975"
RUN_A = "a" * 64
RUN_B = "b" * 64
BANNED = (
    "diagnosis",
    "diagnose",
    "root cause",
    "invalid run",
    "valid run",
    "faulty instrument",
    "error found",
    "compliant",
)


def _summary(**changes):
    base = {
        "source_kind": "quantstudio_export",
        "run_id": "run1",
        "run_start": "2026-03-01T09:00:00Z",
        "run_end": "2026-03-01T11:00:00Z",
        "run_state": "complete",
        "model": "QuantStudio 5 System",
        "serial": SERIAL,
        "block_serial": "BLK-0001",
        "cover_serial": "CVR-0001",
        "optical_head_serial": None,
        "firmware": "1.3.0",
        "software": "QuantStudio Design & Analysis 2.6",
        "calibrations": {
            "background": {
                "performed_on": "2025-12-11",
                "expires_on": None,
                "expired_at_run": False,
            },
            "roi": {"performed_on": "2025-12-11", "expires_on": None, "expired_at_run": False},
        },
        "events": [],
        "aliases": ["QuantStudio 5 System"],
    }
    base.update(changes)
    return base


@pytest.fixture
def root(tmp_path):
    return tmp_path / "instruments"


@pytest.fixture
def registry(root):
    reg = Registry(root)
    reg.register(
        "qs5-room-2110",
        "QS5 – Room 2.110",
        make_model="QuantStudio 5",
        location="Room 2.110",
        shared=True,
        serials=[SERIAL],
    )
    return reg


@pytest.fixture
def book(registry):
    return registry.logbook("qs5-room-2110")


# ---- the registry -------------------------------------------------------------------------------


def test_root_sits_next_to_study_workspaces_and_is_never_a_study(tmp_studies_dir):
    root = instruments_root()
    assert root == tmp_studies_dir / "instruments"
    reg = Registry()
    reg.register("abcdef", "A hex-looking id")  # a hex instrument id still lives under instruments/
    reg.logbook("abcdef").append({"kind": "note", "source": "typed", "actor": "human"})
    store = StudyStore(tmp_studies_dir)
    assert store.list_studies() == []
    with pytest.raises(StudyNotFound):
        store.workspace("abcdef")


def test_register_round_trips_through_strict_yaml(registry, root):
    text = (root / "instruments.yaml").read_text()
    assert "'272530975'" in text  # serials are written quoted, so YAML keeps them as text
    again = Registry(root).get("qs5-room-2110")
    assert again == registry.get("qs5-room-2110")
    assert again.display_name == "QS5 – Room 2.110" and again.shared is True
    assert [i.instrument_id for i in Registry(root).instruments()] == ["qs5-room-2110"]


@pytest.mark.parametrize(
    ("yaml_text", "message"),
    [
        ("instruments:\n  a: &x {display_name: A}\n  b: *x\n", "aliases are not allowed"),
        ("instruments:\n  a: {display_name: A}\n  a: {display_name: B}\n", "appears twice"),
        ("instruments:\n  a: {display_name: A, colour: red}\n", "colour"),
        ("version: 1\nowner: me\n", "unknown field"),
        ("version: 2\n", "version"),
        ("instruments:\n  a: {display_name: A, serials: [272530975]}\n", "serials"),
        ("instruments:\n  Bad/Id: {display_name: A}\n", "instrument id"),
        (
            "instruments:\n  a: {display_name: A, serials: ['1']}\n"
            "  b: {display_name: B, serials: ['1']}\n",
            "two instruments",
        ),
        ("instruments:\n  a: {instrument_id: b, display_name: A}\n", "different id"),
        ("- just\n- a list\n", "mapping"),
        ("instruments: [a, b]\n", "mapping"),
        ("instruments:\n  ? [a, b]\n  : {display_name: A}\n", "plain text"),
    ],
)
def test_strict_loader_refuses_bad_registries(root, yaml_text, message):
    root.mkdir(parents=True)
    (root / "instruments.yaml").write_text(yaml_text)
    with pytest.raises(InstrumentError, match=message):
        Registry(root).instruments()


def test_oversize_registry_is_refused(root):
    root.mkdir(parents=True)
    (root / "instruments.yaml").write_text("#" * (inst.MAX_REGISTRY_BYTES + 1))
    with pytest.raises(InstrumentError, match="limit"):
        Registry(root).load()


def test_register_refuses_taken_ids_and_serials(registry):
    with pytest.raises(InstrumentError, match="already registered"):
        registry.register("qs5-room-2110", "Again")
    with pytest.raises(InstrumentError, match="serial"):
        registry.register("other", "Other", serials=[f" {SERIAL} "])
    with pytest.raises(InstrumentError, match="instrument_id"):
        registry.register("Has Spaces", "Bad id")
    with pytest.raises(UnknownInstrument):
        registry.get("nope")


def test_update_keeps_serials(registry):
    out = registry.update("qs5-room-2110", location="Room 3.001", shared=False)
    assert out.location == "Room 3.001" and out.shared is False
    assert out.serials == (SERIAL,)


def test_serials_and_aliases_never_leave_through_export(registry):
    registry.remember_alias("Cycler SN: CC009466", "qs5-room-2110")
    exported = json.dumps(registry.export())
    assert SERIAL not in exported and "CC009466" not in exported
    assert registry.export()[0]["display_name"] == "QS5 – Room 2.110"
    assert "serials" not in registry.get("qs5-room-2110").public()
    asked = json.dumps(registry.ask(_summary(serial="999")))
    assert SERIAL not in asked and "999" not in asked


def test_suggest_id_makes_a_slug():
    assert suggest_id("QS5 – Room 2.110") == "qs5-room-2-110"
    with pytest.raises(InstrumentError):
        suggest_id("––")


# ---- linking runs: resolve, ask once, remember ----------------------------------------------


def test_resolve_by_serial_first(registry):
    assert registry.resolve(_summary()) == "qs5-room-2110"
    assert registry.resolve(_summary(serial=f"  {SERIAL} ")) == "qs5-room-2110"
    # An unknown serial is a new instrument, even with the same model string as an alias.
    registry.remember_alias("QuantStudio 5 System", "qs5-room-2110")
    assert registry.resolve(_summary(serial="111111111")) is None


def test_a_file_without_a_serial_asks_once_and_is_remembered_by_alias(registry):
    stepone = {"serial": None, "aliases": ["Applied Biosystems StepOne™ Instrument"]}
    assert registry.resolve(stepone) is None
    question = registry.ask(stepone)
    assert question["question"] == QUESTION and question["reason"] == "no_serial"
    assert question["choices"] == [
        {"instrument_id": "qs5-room-2110", "display_name": "QS5 – Room 2.110"}
    ]
    registry.register("stepone-lab4", "StepOne – Lab 4")
    registry.remember(stepone, "stepone-lab4")
    assert registry.resolve(stepone) == "stepone-lab4"
    assert registry.ask(stepone) is None  # asked once only
    assert Registry(registry.root).resolve({"aliases": ["applied biosystems  STEPONE™ instrument"]})
    assert registry.ask({"serial": "123"})["reason"] == "unknown_serial"


def test_remember_records_the_serial_when_there_is_one(registry):
    registry.register("qs3", "QS3")
    registry.remember({"serial": "272321808", "aliases": ["QuantStudio 3 System"]}, "qs3")
    got = registry.get("qs3")
    assert got.serials == ("272321808",) and got.aliases == ()
    assert registry.resolve({"serial": "272321808"}) == "qs3"
    with pytest.raises(InstrumentError, match="neither"):
        registry.remember({"serial": None, "aliases": []}, "qs3")


def test_an_alias_names_one_instrument(registry):
    registry.register("other", "Other")
    registry.remember_alias("LC96SN11301", "other")
    registry.remember_alias("lc96sn11301", "other")  # idempotent, case-folded
    assert registry.get("other").aliases == ("LC96SN11301",)
    with pytest.raises(InstrumentError, match="already names"):
        registry.remember_alias("LC96SN11301", "qs5-room-2110")
    with pytest.raises(InstrumentError):
        registry.remember_alias("   ", "other")
    with pytest.raises(UnknownInstrument):
        registry.remember_alias("x", "missing")


def test_malformed_summaries_are_refused(registry):
    with pytest.raises(InstrumentError):
        registry.resolve(["not", "a", "mapping"])
    with pytest.raises(InstrumentError):
        registry.resolve({"serial": 272530975})
    with pytest.raises(InstrumentError):
        registry.resolve({"aliases": "one string"})


# ---- inferred events ----------------------------------------------------------------------------


def test_a_block_swap_yields_exactly_one_inferred_component_change():
    first = _summary()
    second = _summary(run_id="run2", run_start="2026-03-14T09:00:00Z", block_serial="BLK-0002")
    events = infer_events(first, second)
    assert [(e["kind"], e["source"]) for e in events] == [("component_change", "inferred")]
    assert events[0]["payload"] == {"component": "block"}
    assert events[0]["at"] == "2026-03-14T09:00:00Z"
    assert "BLK-000" not in json.dumps(events)  # which part changed, never its serial


def test_calibration_firmware_software_and_run_events():
    first = _summary()
    second = _summary(
        run_start="2026-04-02T08:00:00Z",
        calibrations={"background": {"performed_on": "2026-03-30"}, "roi": {"performed_on": None}},
        firmware="1.4.0",
        software="QuantStudio Design & Analysis 2.7",
        optical_head_serial="OH-1",
        run_state="aborted",
        events=[{"kind": "pause", "cycle": 23}, {"kind": "resume", "cycle": 24}],
    )
    events = infer_events(first, second)
    kinds = [(e["kind"], e["source"]) for e in events]
    assert kinds == [
        ("calibration", "inferred"),
        ("firmware_change", "inferred"),
        ("software_change", "inferred"),
        ("run_event", "file"),
        ("run_event", "file"),
    ]
    assert events[0]["payload"] == {"type": "background", "performed_on": "2026-03-30"}
    assert events[0]["at"] == "2026-03-30"  # dated by the calibration, not by the run
    assert events[1]["payload"] == {"from": "1.3.0", "to": "1.4.0"}
    assert events[3]["payload"] == {"what": "run_state", "state": "aborted"}
    assert events[4]["payload"] == {"what": "pause", "cycle": 23}
    assert all(e["actor"] == "system" for e in events)


def test_first_run_and_missing_values_infer_no_change():
    assert infer_events(None, _summary()) == []
    assert infer_events(_summary(block_serial=None), _summary(block_serial="BLK-9")) == []
    aborted = infer_events(None, _summary(run_state="aborted", events=[{"kind": "abort"}]))
    assert [e["payload"]["what"] for e in aborted] == ["abort"]  # one entry, not two


def test_two_instruments_cannot_be_compared():
    with pytest.raises(InstrumentError, match="different instruments"):
        infer_events(_summary(), _summary(serial="111111111"))


def test_inferred_events_append_with_their_run(book):
    events = infer_events(_summary(), _summary(block_serial="BLK-0002"))
    written = book.append_many([{**e, "run_hash": RUN_B} for e in events])
    assert [(e.seq, e.kind, e.source, e.run_hash) for e in written] == [
        (1, "component_change", "inferred", RUN_B)
    ]
    assert book.verify() == []


# ---- the hash chain -----------------------------------------------------------------------------


def _fill(book):
    book.append({"kind": "calibration", "source": "file", "actor": "system", "at": "2026-01-02"})
    log_typed(book, "service", note="Engineer visit; lamp replaced", at="2026-02-01")
    book.append(
        {
            "kind": "run_event",
            "source": "file",
            "actor": "system",
            "at": "2026-02-03T10:00:00Z",
            "run_hash": RUN_A,
            "payload": {"what": "pause", "cycle": 23},
        }
    )


def test_chain_links_from_the_sha256_of_the_instrument_id(book):
    _fill(book)
    events = book.events()
    assert events[0].prev_hash == chain_root("qs5-room-2110")
    assert chain_root("qs5-room-2110") == hashlib.sha256(b"qs5-room-2110").hexdigest()
    assert [e.seq for e in events] == [1, 2, 3]
    for prev, event in zip(events, events[1:], strict=False):
        assert event.prev_hash == prev.hash
    for event in events:
        assert event.hash == event_hash(event)
        data = event.model_dump(mode="json", exclude={"hash"}, exclude_none=True)
        body = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        assert event.hash == hashlib.sha256(body.encode()).hexdigest()
    lines = book.path.read_text().splitlines()
    assert lines == [canonical_line(e) for e in events]
    assert book.head() == events[-1].hash
    assert book.verify() == []


def test_tampering_is_detected_and_stops_reads_and_appends(book):
    _fill(book)
    lines = book.path.read_text().splitlines()
    lines[1] = lines[1].replace("lamp replaced", "nothing done")
    book.path.write_text("\n".join(lines) + "\n")
    problems = book.verify()
    assert problems and "entry 2" in problems[0]
    with pytest.raises(LogbookError):
        book.events()
    with pytest.raises(LogbookError):
        book.append({"kind": "note", "source": "typed", "actor": "human"})


def test_an_extra_key_or_a_dropped_line_is_detected(book):
    _fill(book)
    lines = book.path.read_text().splitlines()
    data = json.loads(lines[0])
    data["extra"] = 1
    book.path.write_text("\n".join([json.dumps(data), *lines[1:]]) + "\n")
    assert book.verify()
    book.path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    assert "entry 2" in book.verify()[0]
    book.path.write_text("not json\n")
    assert book.verify() == ["entry 1 cannot be read"]


def test_a_rule_breaking_entry_with_valid_hashes_is_still_reported(book):
    """Hashes alone do not make an entry legitimate: replay checks who confirmed."""
    inc = log_incident(book, actor="agent", wells=["B3"], signature={"metric": "plateau"})
    forged = inst.LogEvent(
        seq=2,
        prev_hash=inc.hash,
        instrument_id=book.instrument_id,
        kind="incident",
        source="typed",
        actor="agent",
        recorded_at="2026-03-15T00:00:00Z",
        payload={"action": "confirm", "incident": inc.seq},
    )
    forged = forged.model_copy(update={"hash": event_hash(forged)})
    with open(book.path, "a") as fh:
        fh.write(canonical_line(forged) + "\n")
    assert any(inst.HUMAN_ONLY in p for p in book.verify())
    with pytest.raises(LogbookError):
        book.incidents()


def test_size_caps(book, monkeypatch):
    with pytest.raises(InstrumentError, match="longer"):
        log_typed(book, "note", note="x" * (inst.MAX_TEXT + 1))
    with pytest.raises(LogbookError, match="larger"):
        book.append(
            {
                "kind": "note",
                "source": "typed",
                "actor": "human",
                "payload": {"blob": "y" * inst.MAX_EVENT_BYTES},
            }
        )
    _fill(book)
    monkeypatch.setattr(inst, "MAX_LOGBOOK_BYTES", 100)
    assert "limit" in book.verify()[0]
    with pytest.raises(LogbookError):
        book.events()


def test_malformed_events_are_refused(book):
    good = {"kind": "note", "source": "typed", "actor": "human"}
    for bad in (
        {**good, "kind": "repair"},
        {**good, "source": "guess"},
        {**good, "actor": "robot"},
        {**good, "at": "yesterday"},
        {**good, "wells": ["B3", "row 2"]},
        {**good, "wells": "B3"},
        {**good, "run_hash": "not-a-hash"},
        {**good, "payload": {"value": float("nan")}},
        {**good, "colour": "red"},
        {**good, "signature": {"metric": "Plateau Height"}},
    ):
        with pytest.raises(InstrumentError):
            book.append(bad)
    assert not book.path.exists()  # nothing was written for any refusal


def test_events_filter_by_kind_and_date(book):
    _fill(book)
    assert [e.kind for e in book.events(kinds=["service"])] == ["service"]
    assert [e.seq for e in book.events(since="2026-02-02")] == [3]
    assert [e.seq for e in book.events(since="2026-02-01T00:00:00+00:00")] == [2, 3]
    with pytest.raises(InstrumentError):
        book.events(kinds=["repair"])


def _append_many(root, n, barrier):
    book = Logbook("qs5-room-2110", root)
    barrier.wait()
    for i in range(n):
        book.append({"kind": "note", "source": "typed", "actor": "human", "payload": {"i": i}})


def test_concurrent_appends_keep_one_valid_chain(root):
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(3)
    procs = [ctx.Process(target=_append_many, args=(str(root), 5, barrier)) for _ in range(3)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0
    book = Logbook("qs5-room-2110", root)
    assert book.verify() == []
    assert [e.seq for e in book.events()] == list(range(1, 16))


# ---- incidents ----------------------------------------------------------------------------------

LOW_PLATEAU = {"metric": "plateau", "direction": "low", "numbers": {"plateau_ratio": 0.42}}


def test_an_agent_proposes_and_only_a_person_confirms(book):
    inc = log_incident(
        book,
        actor="agent",
        wells=["B4", "B3"],
        signature=LOW_PLATEAU,
        run_hash=RUN_A,
        note="B3/B4 plateau low",
        at="2026-03-14",
    )
    assert inc.wells == ("B3", "B4") and inc.payload["status"] == "proposed"
    assert book.incidents()[0].status == "proposed"
    head = book.head()

    class Sneaky(str):
        def __eq__(self, other):
            return True

        __hash__ = str.__hash__

    for actor in ("agent", "system", Sneaky("agent"), None, "Human"):
        with pytest.raises(InstrumentError, match="only a person"):
            confirm_incident(book, inc.seq, actor=actor)
        with pytest.raises(InstrumentError, match="only a person"):
            reject_incident(book, inc.seq, actor=actor)
        with pytest.raises(InstrumentError, match="only a person"):
            log_fix(book, inc.seq, note="re-seated the block", actor=actor)
    assert book.head() == head  # no refusal wrote anything
    with pytest.raises(LogbookError, match="only a person"):
        book.append(
            {
                "kind": "incident",
                "source": "typed",
                "actor": "agent",
                "payload": {"action": "confirm", "incident": inc.seq},
            }
        )
    confirm_incident(book, inc.seq, actor="human")
    assert book.incidents()[0].status == "confirmed"
    with pytest.raises(InstrumentError, match="already confirmed"):
        confirm_incident(book, inc.seq, actor="human")
    with pytest.raises(InstrumentError, match="no incident"):
        confirm_incident(book, 99, actor="human")
    assert book.verify() == []


def test_a_person_logging_an_incident_confirms_it(book):
    inc = log_incident(book, actor="human", wells=["C7"], signature={"error_code": "PRFDROP"})
    assert book.incidents()[0].status == "confirmed" and inc.payload["status"] == "confirmed"
    with pytest.raises(LogbookError, match="must be confirmed"):
        book.append(
            {
                "kind": "incident",
                "source": "typed",
                "actor": "human",
                "payload": {"action": "log", "status": "proposed"},
            }
        )


def test_rejected_incidents_are_never_matched_or_fixed(book):
    inc = log_incident(book, actor="agent", wells=["B3"], signature=LOW_PLATEAU)
    reject_incident(book, inc.seq, actor="human")
    assert book.incidents()[0].status == "rejected"
    assert match_incidents(book, {"wells": ["B3"], **LOW_PLATEAU}) == []
    with pytest.raises(InstrumentError, match="no open incident"):
        log_fix(book, inc.seq, note="n/a", actor="human")


def test_fix_notes_link_to_their_incident(book):
    inc = log_incident(book, actor="human", wells=["B3", "B4"], signature=LOW_PLATEAU)
    fix = log_fix(
        book, inc.seq, note="Service visit: head position", actor="human", at="2026-03-21"
    )
    assert fix.kind == "fix" and fix.payload == {
        "incident": inc.seq,
        "note": "Service visit: head position",
    }
    assert book.incidents()[0].fixes == [
        {"seq": fix.seq, "at": "2026-03-21", "note": "Service visit: head position"}
    ]
    with pytest.raises(InstrumentError, match="what fixed"):
        log_fix(book, inc.seq, note="  ", actor="human")


def test_typed_text_is_stored_as_typed(book):
    note = "Lid felt warm;  B3 looked dry — evaporation?\nCheck seal."
    event = log_typed(book, "note", note=note)
    assert book.events()[0].payload["note"] == note == event.payload["note"]
    assert book.verify() == []
    view = event_view(book.events()[0])
    assert "note" not in view["payload"] and view["payload"]["note_chars"] == len(note)
    assert event_view(book.events()[0], include_text=True)["payload"]["note"] == note


def test_seen_before_on_the_same_instrument_and_wells(registry, book):
    """3b.2: a B3/B4 low-plateau incident; a later run with B3 low matches, elsewhere nothing."""
    inc = log_incident(
        book,
        actor="agent",
        wells=["B3", "B4"],
        signature=LOW_PLATEAU,
        run_hash=RUN_A,
        note="Low plateau, evaporation suspected",
        at="2026-03-14",
    )
    later = {"wells": ["B3"], "metric": "plateau", "direction": "low"}
    assert match_incidents(book, later) == []  # proposed only: not yet a memory
    confirm_incident(book, inc.seq, actor="human")
    log_fix(book, inc.seq, note="service visit", actor="human", at="2026-03-21")
    matches = match_incidents(book, later)
    assert len(matches) == 1
    hit = matches[0]
    assert hit["words"] == SEEN_BEFORE
    assert hit["incident"] == inc.seq and hit["at"] == "2026-03-14"
    assert hit["wells"] == ["B3"] and hit["incident_wells"] == ["B3", "B4"]
    assert hit["matched_on"] == ["wells_metric_direction"]
    assert hit["fixed"] is True and hit["fixes"][0]["at"] == "2026-03-21"
    assert "note" not in hit and "service" not in json.dumps(hit)  # text only on request
    shown = match_incidents(book, later, include_text=True)[0]
    assert shown["note"] == "Low plateau, evaporation suspected"
    assert shown["fixes"][0]["note"] == "service visit"
    # Another instrument: its own logbook has nothing, and a signature naming it matches nothing.
    registry.register("qs7-room-3", "QS7 – Room 3")
    assert match_incidents(registry.logbook("qs7-room-3"), later) == []
    assert match_incidents(book, {**later, "instrument_id": "qs7-room-3"}) == []
    # Same wells but another metric or direction: not the same thing.
    assert match_incidents(book, {**later, "direction": "high"}) == []
    assert match_incidents(book, {**later, "metric": "cq_residual"}) == []
    assert match_incidents(book, {**later, "wells": ["H12"]}) == []
    assert book.verify() == []


def test_seen_before_by_error_code(book):
    log_incident(
        book, actor="human", wells=["A1"], signature={"error_code": "PRFDROP"}, at="2026-01-05"
    )
    log_incident(
        book, actor="human", wells=["P24"], signature={"error_code": "prfdrop"}, at="2026-02-05"
    )
    matches = match_incidents(book, {"error_code": "PRFDROP", "wells": ["K22"]})
    assert [m["at"] for m in matches] == ["2026-02-05", "2026-01-05"]  # most recent first
    assert all(m["matched_on"] == ["error_code"] for m in matches)


def test_proposed_window_runs_from_last_clean_evidence_to_the_fix(book):
    log_typed(book, "calibration", at="2026-01-10", payload={"type": "background"})
    log_typed(book, "service", at="2026-02-20")
    inc = log_incident(book, actor="human", wells=["B3"], signature=LOW_PLATEAU, at="2026-03-14")
    assert proposed_window(book, inc.seq) == ("2026-02-20", "2026-03-14")
    log_fix(book, inc.seq, note="new block", actor="human", at="2026-03-21")
    assert proposed_window(book, inc.seq) == ("2026-02-20", "2026-03-21")


def test_typed_events_are_limited_to_typed_kinds(book):
    with pytest.raises(InstrumentError):
        log_typed(book, "incident")
    with pytest.raises(InstrumentError):
        log_typed(book, "note", actor="robot")


def test_module_words(book):
    """The words rule: status words only, in the module and in what it returns."""
    text = inst.__doc__ + json.dumps([inst.HUMAN_ONLY, SEEN_BEFORE, QUESTION])
    assert not [w for w in BANNED if w in text.lower()]
