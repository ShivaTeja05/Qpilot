"""The instrument-context reader: what a run file says about the instrument (plan 2.15, L1).

Most inputs are synthetic and built in ``tmp_path`` (``tests/engine/instrument_files.py``); the
layouts follow the measured oracle. The text exports of the fixtures corpus are read as they are
(Design & Analysis 2.x, QuantStudio TXT, CFX Run Information); their serials and personal fields
are read from the files by the tests, never written here. The demo RDML test is marked
``demo_data``.
"""

import io
import json
import random
import re
import zipfile
from pathlib import Path

import pytest

from qpilot.io.rdml_io import load
from qpilot.qpcr import instrument_context as ic
from qpilot.qpcr.instrument_context import (
    LOCAL_ONLY,
    METHOD_CARD,
    InstrumentFileError,
    RunContext,
    is_local_only,
    model_facts,
    parse_instrument_string,
    read_run_context,
    run_contexts_from_rdml,
)
from tests.engine import instrument_files as F
from tests.timing import work_time

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CORPUS = FIXTURES / "corpus"
DA_QS3 = CORPUS / "thermofisher" / "securebio-qs3-design-analysis-2.7"
DA_7500 = CORPUS / "thermofisher" / "opentrons-7500-design-analysis-csv"
DA_SYNTH = CORPUS / "synthetic" / "quantstudio-design-analysis-rn-drn"
DA_REAL = sorted([*DA_QS3.glob("*.csv"), *DA_7500.glob("*.csv")])
CFX_REAL = sorted(CORPUS.glob("biorad/*/*Run Information.csv"))
# CFX Manager's default run name: "<user>_<date time>_<serial>", then the export's own part
CFX_MANAGER_NAME = r"[^_]+_\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}_[^_]+_Run Information\.csv"
QS_TXT_REAL = sorted((CORPUS / "thermofisher" / "allotropy-quantstudio-rtpcr-txt").glob("*.txt"))
SUMMARY_KEYS = {
    "source_kind",
    "run_id",
    "run_start",
    "run_end",
    "run_state",
    "date_source",
    "model",
    "serial",
    "block_serial",
    "cover_serial",
    "optical_head_serial",
    "firmware",
    "software",
    "calibrations",
    "events",
    "aliases",
}


def _dump(ctx: RunContext) -> str:
    return ctx.model_dump_json() + json.dumps(ctx.summary(), ensure_ascii=False)


def _cal(ctx: RunContext, kind: str) -> dict:
    return next(c for c in ctx.calibrations if c["type"] == kind)


def _hash_header(path: Path) -> dict[str, str]:
    """A Design & Analysis export's ``# Key: Value`` lines (key in lower case), read plainly."""
    header: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.startswith("#"):
            break
        key, _, value = line[1:].partition(":")
        header[key.strip().lower()] = value.strip()
    return header


# ---------------------------------------------------------------------------------------------
# .eds archives
# ---------------------------------------------------------------------------------------------


def test_qs_eds_calibrations_events_and_serials(tmp_path):
    ctx = read_run_context(F.qs_v1_expired(tmp_path / "qs.eds"))
    assert ctx.source_kind == "eds" and ctx.source_file == "qs.eds" and ctx.run_id is None
    assert ctx.run == {
        "start": "2019-05-10T09:00:00Z",
        "end": "2019-05-10T10:40:00Z",
        "state": "complete",
        "date_source": "instrument",
        "date": "2019-05-10",
    }
    assert ctx.identity["model"] == "QuantStudio 1/3/5 class"
    assert ctx.identity["instrument_type"] == "appletini"
    assert ctx.identity["serial"] == "278880001"  # from experiment.xml RunInfo (tag U1)
    assert ctx.identity["block_serial"] == "BLK-1001"  # from the run-start log line (U4)
    assert ctx.identity["cover_serial"] == "HC-2001"
    background = _cal(ctx, "background")
    assert background == {
        "type": "background",
        "label": "Background",
        "performed_on": "2018-03-24",
        "expires_on": "2018-09-20",
        "expired_at_run": True,
        "age_days": 412,
        "interval_days": 180,
        "source": "calibrations/background.ini:[head].timestamp",
    }
    assert _cal(ctx, "roi")["expired_at_run"] is False
    assert _cal(ctx, "roi")["interval_days"] == 730
    assert _cal(ctx, "pure_dye")["age_days"] == 128
    assert [c["type"] for c in ctx.calibrations] == ["background", "pure_dye", "roi", "uniformity"]
    pause, resume = ctx.events
    assert pause["kind"] == "pause" and pause["cycle"] == 23 and pause["cycles"] == [23, 24]
    assert pause["source"].startswith("messages.log:line ")
    assert resume["kind"] == "resume"
    assert ctx.checked == ["identity", "run_state", "calibrations", "event_log", "temperature"]
    assert ctx.temperature is not None and ctx.temperature["max_hold_deviation_c"] <= 0.1
    facts = ctx.facts
    assert facts["f_instr_run_state"].path == "experiment.xml:RunState"
    assert facts["f_instr_run_start"].path == "experiment.xml:RunStartTime"
    assert facts["f_instr_cal_background_age_days"].value == 412
    assert facts["f_instr_cal_background_expires_on"].path == (
        "calibrations/background.ini:[head].expirytime"
    )
    assert facts["f_instr_event_1_first_cycle"].value == 23
    assert facts["f_instr_event_1_last_cycle"].value == 24
    assert (
        facts["f_instr_serial"].path == LOCAL_ONLY + "experiment.xml:RunInfo/InstrumentSerialNumber"
    )


def test_summary_has_the_logbook_keys(tmp_path):
    summary = read_run_context(F.qs_v1_expired(tmp_path / "qs.eds")).summary()
    assert set(summary) == SUMMARY_KEYS
    assert summary["calibrations"]["background"] == {
        "performed_on": "2018-03-24",
        "expires_on": "2018-09-20",
        "expired_at_run": True,
    }
    assert summary["events"] == [{"kind": "pause", "cycle": 23}, {"kind": "resume", "cycle": 23}]
    assert summary["aliases"] == ["278880001", "BLK-1001", "HC-2001"]
    assert summary["run_start"] == "2019-05-10T09:00:00Z" and summary["run_state"] == "complete"
    json.dumps(summary)  # plain JSON


def test_block_swap_pair_gives_distinct_block_serials(tmp_path):
    a = read_run_context(F.qs_v1_expired(tmp_path / "a.eds", block_serial="BLK-1001")).summary()
    b = read_run_context(F.qs_v1_expired(tmp_path / "b.eds", block_serial="BLK-1999")).summary()
    assert a["serial"] == b["serial"] == "278880001"
    assert (a["block_serial"], b["block_serial"]) == ("BLK-1001", "BLK-1999")
    assert a["cover_serial"] == b["cover_serial"]


def test_serials_are_local_only_and_out_of_the_model_view(tmp_path):
    ctx = read_run_context(F.qs_v1_expired(tmp_path / "qs.eds"))
    serials = {"278880001", "BLK-1001", "HC-2001"}
    for fact in ctx.facts.values():
        if fact.value in serials:
            assert is_local_only(fact), fact.id
    view = json.dumps(ctx.model_view(), ensure_ascii=False)
    assert not any(serial in view for serial in serials)
    assert ctx.model_view()["serials_present"] == ["block_serial", "cover_serial", "serial"]
    assert all(not is_local_only(f) for f in model_facts(ctx).values())
    assert "f_instr_serial" not in model_facts(ctx)


def test_personal_data_is_never_copied(tmp_path):
    files = [
        F.qs_v1_expired(tmp_path / "qs.eds"),
        F.eds2_json(tmp_path / "eds2.eds"),
        F.quantstudio_csv(tmp_path / "qs5.csv"),
        F.quantstudio_txt(tmp_path / "qs.txt"),
        F.cfx_run_information(tmp_path / "cfx.csv"),
    ]
    for path in files:
        ctx = read_run_context(path)
        dump = _dump(ctx)
        assert F.OPERATOR not in dump, path.name
        assert "AlexandraQuill" not in dump and "Administrator" not in dump, path.name
    csv_ctx = read_run_context(tmp_path / "qs5.csv")
    assert ic.NOTE_OPERATOR_PATH in csv_ctx.notes and ic.NOTE_USER_NAME in csv_ctx.notes
    assert ic.NOTE_PERSONAL_FIELD in read_run_context(tmp_path / "qs.eds").notes


def test_7500_layout_from_the_real_file(tmp_path):
    path = F.like_7500(tmp_path / "7500.eds")
    with zipfile.ZipFile(path) as archive:
        assert "APLDBIO\\SDS\\CALIBRATIONS/background.ini" in archive.namelist()
    ctx = read_run_context(path)
    assert ctx.run["start"] == "2007-11-10T01:46:54Z" and ctx.run["end"] == "2007-11-10T03:10:59Z"
    assert ctx.identity["model"] == "7500 Fast" and ctx.identity["software"] == "7500 Software v2.3"
    assert ctx.identity["serial"] is None and ctx.aliases == []  # no serial in a 7500 file
    assert [c["type"] for c in ctx.calibrations] == ["background", "pure_dye", "uniformity"]
    background = _cal(ctx, "background")
    # 2007-10-10T19:20:39Z to a run on 2007-11-10: 31 calendar days (30.27 days elapsed)
    assert (background["performed_on"], background["age_days"]) == ("2007-10-10", 31)
    assert background["expires_on"] is None and background["expired_at_run"] is None
    assert ic.NOTE_CAL_NOT_IN_FILE not in ctx.notes
    assert "event_log" not in ctx.checked and ctx.events == [] and ctx.temperature is None


def test_stepone_calibration_date_not_in_file(tmp_path):
    ctx = read_run_context(F.stepone(tmp_path / "stepone.eds"))
    assert ctx.identity["model"] == "StepOnePlus"
    assert ic.NOTE_CAL_NOT_IN_FILE in ctx.notes
    for cal in ctx.calibrations:
        assert cal["performed_on"] is None and cal["age_days"] is None
        assert cal["expired_at_run"] is None
    assert not any(fid.endswith("_age_days") for fid in ctx.facts)


def test_a_calibration_stamped_inside_the_run_has_no_date(tmp_path):
    start, end = F.epoch_ms("2022-02-01T10:00:00"), F.epoch_ms("2022-02-01T11:30:00")
    members = {
        "experiment.xml": F.experiment_xml(start_ms=start, end_ms=end, type_id="paragon"),
        "calibrations/background.ini": F.calibration_ini("background", timestamp_ms=start + 60_000),
        "calibrations/roi.ini": F.calibration_ini("roi", timestamp_ms=start - 3 * F.DAY_MS),
    }
    ctx = read_run_context(F.write_eds(tmp_path / "x.eds", members))
    assert _cal(ctx, "background")["performed_on"] is None
    assert _cal(ctx, "roi")["age_days"] == 3
    assert ic.NOTE_CAL_NOT_IN_FILE in ctx.notes


def test_expiry_keys_and_values(tmp_path):
    ts = F.epoch_ms("2020-01-01T00:00:00")
    start = F.epoch_ms("2020-09-01T08:00:00")
    members = {
        "experiment.xml": F.experiment_xml(start_ms=start, end_ms=start + 3_600_000),
        # the 7500 spelling in [head]: still an expiry
        "calibrations/background.ini": F.calibration_ini(
            "background", timestamp_ms=ts, expiry_ms=ts + 180 * F.DAY_MS,
            expiry_key="expiration-time",
        ),
        # a value before the calibration: not understood, so no expiry
        "calibrations/roi.ini": F.calibration_ini("roi", timestamp_ms=ts, expiry_ms=180),
        # 0 means unset
        "calibrations/uniformity.ini": F.calibration_ini(
            "uniformity", timestamp_ms=ts, expiry_ms=0
        ),
    }  # fmt: skip
    ctx = read_run_context(F.write_eds(tmp_path / "x.eds", members))
    assert _cal(ctx, "background")["expired_at_run"] is True
    assert _cal(ctx, "background")["interval_days"] == 180
    assert _cal(ctx, "roi")["expires_on"] is None and _cal(ctx, "roi")["expired_at_run"] is None
    assert _cal(ctx, "uniformity")["expires_on"] is None
    assert ic.NOTE_EXPIRY_NOT_UNDERSTOOD in ctx.notes


def test_per_dye_sections_with_their_own_times(tmp_path):
    ts = F.epoch_ms("2021-03-01T00:00:00")
    start = F.epoch_ms("2021-06-01T08:00:00")
    fam = (F.epoch_ms("2021-05-01T00:00:00"), F.epoch_ms("2021-05-01T00:00:00") + 30 * F.DAY_MS)
    members = {
        "experiment.xml": F.experiment_xml(start_ms=start, end_ms=start + 3_600_000),
        "calibrations/puredye.ini": F.puredye_ini(timestamp_ms=ts, per_dye={"FAM": fam}),
    }
    ctx = read_run_context(F.write_eds(tmp_path / "x.eds", members))
    assert [c["type"] for c in ctx.calibrations] == ["pure_dye", "pure_dye_fam"]
    fam_cal = _cal(ctx, "pure_dye_fam")
    assert fam_cal["label"] == "Pure Dye FAM" and fam_cal["age_days"] == 31
    assert fam_cal["expired_at_run"] is True  # a 30-day expiry, 31 days before the run
    assert fam_cal["source"] == "calibrations/puredye.ini:[FAM].calibration-time"


def test_ini_data_blocks_and_comments_are_skipped():
    text = "\r\n".join(
        [
            "# timestamp=1 in a comment",
            "[head]",
            "timestamp=1192044039119",
            "[background]",
            "1=<<eof",
            "timestamp=5",
            "eof",
            "after=yes",
        ]
    )
    sections = ic._parse_ini(text)
    assert sections["head"]["timestamp"][0] == "1192044039119"
    assert "timestamp" not in sections["background"] and sections["background"]["after"][0] == "yes"


def test_eds2_json_summary_keys(tmp_path):
    ctx = read_run_context(F.eds2_json(tmp_path / "eds2.eds"))
    assert ctx.run["state"] == "complete"
    assert ctx.run["start"] == "2024-06-03T08:00:00Z" and ctx.run["end"] == "2024-06-03T09:35:00Z"
    ident = ctx.identity
    assert (ident["serial"], ident["block_serial"], ident["cover_serial"]) == (
        "278990004",
        "BLK-7007",
        "HC-7008",
    )
    assert ident["model"] == "QuantStudio 7 Pro" and ident["firmware"] == "1.2.0"
    assert "QS7 Room 4" in ctx.aliases  # the instrument name: local alias only
    assert ctx.facts["f_instr_instrument_name"].path.startswith(LOCAL_ONLY)
    assert ctx.facts["f_instr_run_state"].path == "run/run_summary.json:runState"
    assert "run/run_summary.json:plateBarcode" in ctx.unmapped_keys
    assert ic.NOTE_UNMAPPED in ctx.notes and ic.NOTE_PERSONAL_FIELD in ctx.notes
    assert "unmapped_keys" not in ctx.model_view()


def test_summary_json_that_is_not_json_is_a_note(tmp_path):
    members = {"experiment.xml": F.experiment_xml(), "summary.json": "{not json"}
    ctx = read_run_context(F.write_eds(tmp_path / "x.eds", members))
    assert "summary.json: not readable JSON" in ctx.notes


def test_aborted_state_and_event(tmp_path):
    ctx = read_run_context(F.aborted(tmp_path / "aborted.eds"))
    assert ctx.run["state"] == "aborted"
    assert [e["kind"] for e in ctx.events] == ["abort"] and ctx.events[0]["cycle"] == 12


def test_init_state_with_a_completed_log(tmp_path):
    start = F.epoch_ms("2023-04-04T09:00:00")
    members = {
        "experiment.xml": F.experiment_xml(state="INIT", start_ms=start, end_ms=start + 5_000_000),
        "messages.log": F.messages_log(start="2023-04-04 09:00:00"),
    }
    ctx = read_run_context(F.write_eds(tmp_path / "x.eds", members))
    assert ctx.run["state"] == "complete"
    assert ic.NOTE_STATE_DISAGREES in ctx.notes
    assert ctx.facts["f_instr_run_state_in_file"].value == "init"
    assert ctx.facts["f_instr_run_state"].path.startswith("messages.log:line ")


# ---------------------------------------------------------------------------------------------
# messages.log vocabulary (line syntax unverified, U4)
# ---------------------------------------------------------------------------------------------


def test_log_vocabulary_counts_only_events_during_the_run():
    text = F.messages_log(lid_open_at=7, power_at=30, drawer_before_start=True)
    text += "2019-05-10 11:00:00 INFO Drawer opened\n"  # after "run completed": not counted
    log = ic._parse_log(text, "messages.log")
    kinds = [(e["kind"], e["cycle"]) for e in log.events]
    assert kinds == [("lid_open", 7), ("power", 30)]
    assert log.events[0]["cycles"] == [7, 8] and "cycles" not in log.events[1]
    assert log.completed and not log.aborted


def test_configuration_queries_are_not_events():
    text = "\n".join(
        [
            "2019-05-10 09:00:00 INFO Run started.",
            "2019-05-10 09:00:01 DEBUG ERRor -113: PAUSE? not supported",
            "2019-05-10 09:00:02 DEBUG ERRor -113: LID OPENED? not supported",
            "2019-05-10 09:00:03 INFO Stage 2 Cycle 1 of 40",
            "2019-05-10 09:00:04 INFO Run completed.",
        ]
    )
    assert ic._parse_log(text, "messages.log").events == []


def test_log_without_a_start_line_uses_the_cycles():
    text = "\n".join(
        [
            "INFO Drawer opened",  # before any cycle: loading the plate
            "INFO Stage 2 Cycle 5",
            "INFO Run paused",
            "INFO Stage 2 Cycle 6",
            "INFO Run resumed",
        ]
    )
    events = ic._parse_log(text, "messages.log").events
    assert [(e["kind"], e["cycle"]) for e in events] == [("pause", 5), ("resume", 6)]
    assert events[0]["cycles"] == [5, 6] and events[0]["at"] is None


def test_serial_line_in_either_order():
    value_first = ic._log_serials("900000001 [Instrument] 2733 [Block] 4444 [Heated Cover]", "p")
    label_first = ic._log_serials("[Block] 2733, [Heated Cover] 4444", "p")
    plain = ic._log_serials("900000001", "p")
    assert value_first == [
        ("serial", "900000001", "p"),
        ("block_serial", "2733", "p"),
        ("cover_serial", "4444", "p"),
    ]
    assert label_first == [("block_serial", "2733", "p"), ("cover_serial", "4444", "p")]
    assert plain == [("serial", "900000001", "p")]


def test_events_are_capped(monkeypatch):
    monkeypatch.setattr(ic, "MAX_EVENTS", 3)
    text = "INFO Run started.\n" + "INFO Stage 2 Cycle 4\nINFO Run paused\n" * 10
    log = ic._parse_log(text, "messages.log")
    assert len(log.events) == 3 and log.capped


def test_six_megabyte_log_parses_quickly(tmp_path):
    text = F.messages_log(cycles=40, noise_per_cycle=2_400, pause_at=23)
    assert len(text.encode()) >= 6_000_000
    with work_time() as parse:
        log = ic._parse_log(text, "messages.log")
    assert parse.seconds < 2.0, parse
    assert [e["kind"] for e in log.events] == ["pause", "resume"]
    members = {"experiment.xml": F.experiment_xml(), "messages.log": text}
    eds = F.write_eds(tmp_path / "big.eds", members)
    with work_time() as read:
        ctx = read_run_context(eds)
    assert read.seconds < 2.0, read
    assert ctx.events[0]["cycles"] == [23, 24]


# ---------------------------------------------------------------------------------------------
# temperature log (layout unverified, U4)
# ---------------------------------------------------------------------------------------------


def test_temperature_summary_clean_drift_and_lid():
    clean = ic._temperature_summary(F.temperature_log())
    assert clean is not None
    assert clean["max_hold_deviation_c"] <= 0.1
    assert 0.15 <= clean["zone_spread_p95_c"] <= 0.25
    assert clean["min_lid_c_cycling"] >= 104.9
    drift = ic._temperature_summary(F.temperature_log(drift_at_cycle=30, drift_c=0.9))
    assert 0.85 <= drift["max_hold_deviation_c"] <= 0.95
    dip = ic._temperature_summary(F.temperature_log(lid_dip_c=4.0))
    assert dip["min_lid_c_cycling"] < 101.5


def test_temperature_log_without_a_header_is_a_note(tmp_path):
    members = {"experiment.xml": F.experiment_xml(), "logs/temperature.log": "1 2 3\n4 5 6\n"}
    ctx = read_run_context(F.write_eds(tmp_path / "x.eds", members))
    assert ctx.temperature is None and ic.NOTE_TEMPERATURE_FORMAT in ctx.notes


# ---------------------------------------------------------------------------------------------
# Caps, zip bombs and hostile input
# ---------------------------------------------------------------------------------------------


def test_oversize_log_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(ic, "MAX_LOG_BYTES", 1_000)
    path = F.write_eds(tmp_path / "x.eds", {"messages.log": F.messages_log()})
    with pytest.raises(InstrumentFileError, match="member too large"):
        read_run_context(path)


def test_high_ratio_member_is_refused(tmp_path):
    path = tmp_path / "bomb.eds"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("apldbio/sds/messages.log", " " * 2_000_000)
        # incompressible padding keeps the archive's overall ratio low
        info = zipfile.ZipInfo("apldbio/sds/images/noise.bin")
        archive.writestr(
            info, random.Random(0).randbytes(1_000_000), compress_type=zipfile.ZIP_STORED
        )
    with pytest.raises(InstrumentFileError, match=r"messages\.log: compression ratio"):
        read_run_context(path)


def test_archive_bomb_is_refused_before_any_read(tmp_path):
    path = tmp_path / "bomb.eds"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index in range(20):
            archive.writestr(f"apldbio/sds/images/{index}.tiff", "\0" * 500_000)
    with pytest.raises(InstrumentFileError, match="compression ratio"):
        read_run_context(path)


def test_member_count_and_archive_size_caps(tmp_path, monkeypatch):
    path = F.qs_v1_expired(tmp_path / "qs.eds")
    monkeypatch.setattr(ic, "MAX_MEMBERS", 3)
    with pytest.raises(InstrumentFileError, match="too many members"):
        read_run_context(path)
    monkeypatch.setattr(ic, "MAX_MEMBERS", 50_000)
    monkeypatch.setattr(ic, "MAX_ARCHIVE_BYTES", 1_000)
    with pytest.raises(InstrumentFileError, match="archive too large"):
        read_run_context(path)


def test_export_size_cap(tmp_path, monkeypatch):
    path = F.quantstudio_csv(tmp_path / "qs5.csv")
    monkeypatch.setattr(ic, "MAX_EXPORT_BYTES", 100)
    with pytest.raises(InstrumentFileError, match="export too large"):
        read_run_context(path)


def test_xml_entities_are_never_resolved(tmp_path):
    canary = tmp_path / "canary.txt"
    canary.write_text("CANARY-7f3a", encoding="utf-8")
    xml = (
        '<?xml version="1.0"?>\n'
        f'<!DOCTYPE Experiment [<!ENTITY x SYSTEM "file://{canary}">]>\n'
        "<Experiment><RunState>&x;</RunState><InstrumentTypeId>paragon</InstrumentTypeId>"
        "</Experiment>"
    )
    ctx = read_run_context(F.write_eds(tmp_path / "xxe.eds", {"experiment.xml": xml}))
    assert "CANARY" not in _dump(ctx)
    assert ctx.identity["instrument_type"] == "paragon"


def test_files_qpilot_does_not_read_are_refused(tmp_path):
    with pytest.raises(InstrumentFileError, match="not a file"):
        read_run_context(tmp_path / "missing.eds")
    other_zip = tmp_path / "other.zip"
    with zipfile.ZipFile(other_zip, "w") as archive:
        archive.writestr("readme.txt", "hello")
    with pytest.raises(InstrumentFileError, match="neither"):
        read_run_context(other_zip)
    text = tmp_path / "notes.csv"
    text.write_text("Sample,Group\nA,1\n", encoding="utf-8")
    with pytest.raises(InstrumentFileError, match="not a recognised instrument export"):
        read_run_context(text)
    damaged = tmp_path / "damaged.eds"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("apldbio/sds/experiment.xml", F.experiment_xml() * 20)
    raw = bytearray(buffer.getvalue())
    raw[60:200] = b"\x00" * 140  # corrupt the compressed bytes, keep the directory
    damaged.write_bytes(bytes(raw))
    with pytest.raises(InstrumentFileError):
        read_run_context(damaged)


def test_reading_is_deterministic(tmp_path):
    path = F.qs_v1_expired(tmp_path / "qs.eds")
    assert read_run_context(path).model_dump_json() == read_run_context(path).model_dump_json()


# ---------------------------------------------------------------------------------------------
# QuantStudio results exports
# ---------------------------------------------------------------------------------------------


def test_quantstudio_csv_qs5_and_qs3_headers(tmp_path):
    qs5 = read_run_context(
        F.quantstudio_csv(tmp_path / "qs5.csv", flags={"B1": ["BADROX"], "B3": ["PRFDROP"]})
    )
    assert qs5.source_kind == "quantstudio_export"
    assert qs5.identity["model"] == "QuantStudio™ 5 System"
    assert qs5.identity["serial"] == "278880001"
    assert qs5.identity["block_type"] == "384-Well Block"
    assert qs5.run["end"] == "2019-09-11T18:04:11Z"  # 11:04:11 AM PDT
    assert qs5.run["date"] == "2019-09-11" and qs5.run["start"] is None
    assert len(qs5.calibrations) == 13  # background, ten dyes, ROI, uniformity
    background = _cal(qs5, "background")
    # every date is 11-12-2018: no day above twelve, so the order is ambiguous and no age
    assert background["performed_on"] is None and background["age_days"] is None
    assert background["performed_on_raw"] == "11-12-2018"
    assert background["expired_at_run"] is False  # the file's own "is expired No"
    assert ic.NOTE_DATE_AMBIGUOUS in qs5.notes
    assert qs5.facts["f_instr_cal_background_expired"].path == "export.csv:line 2"
    assert _cal(qs5, "pure_dye_mustang_purple")["label"] == "Pure Dye MUSTANG PURPLE"
    assert qs5.well_flags == {"B1": ["BADROX"], "B3": ["PRFDROP"]}
    assert qs5.facts["f_instr_flag_badrox_wells"].value == 1
    assert qs5.facts["f_instr_n_flagged_wells"].value == 2
    assert qs5.facts["f_instr_well_b1_flags"].value == "BADROX"
    assert qs5.facts["f_instr_well_b1_flags"].path == "export.csv:line 51"  # the B1 row

    qs3 = read_run_context(
        F.quantstudio_csv(
            tmp_path / "qs3.csv",
            variant="qs3",
            model="QuantStudio™ 3 System",
            serial="278880002",
            block="96-Well 0.2-mL Block",
            background_on="10-12-2017",
            others_on="08-24-2017",
            run_end="2019-04-25 10:26:48 AM PDT",
            name_padding="      ",
        )
    )
    # 08-24-2017 settles month-first for the whole file
    assert _cal(qs3, "background")["performed_on"] == "2017-10-12"
    assert _cal(qs3, "background")["age_days"] == 560
    assert _cal(qs3, "roi")["age_days"] == 609
    assert {"cm_meltdoctor", "pure_dye_meltdoctor"} <= {c["type"] for c in qs3.calibrations}
    assert "pure_dye_cy5" not in {c["type"] for c in qs3.calibrations}
    assert qs3.facts["f_instr_instrument_name"].value == "278880002"  # padding stripped
    assert qs3.well_flags == {} and "well_flags" in qs3.checked  # flag columns, none set


def test_the_caller_can_settle_the_date_order(tmp_path):
    path = F.quantstudio_csv(tmp_path / "qs5.csv")
    ctx = read_run_context(path, date_order="DMY")
    assert _cal(ctx, "background")["performed_on"] == "2018-12-11"
    assert _cal(ctx, "background")["age_days"] == 274
    assert ic.NOTE_DATE_AMBIGUOUS not in ctx.notes
    month_first = read_run_context(path, date_order="MDY")
    assert _cal(month_first, "background")["performed_on"] == "2018-11-12"


def test_a_day_above_twelve_settles_day_first(tmp_path):
    ctx = read_run_context(
        F.quantstudio_csv(tmp_path / "x.csv", background_on="13-12-2018", others_on="11-12-2018")
    )
    assert _cal(ctx, "background")["performed_on"] == "2018-12-13"
    assert _cal(ctx, "roi")["performed_on"] == "2018-12-11"


def test_iso_dates_need_no_order(tmp_path):
    ctx = read_run_context(
        F.quantstudio_csv(
            tmp_path / "x.csv", background_on="2018-12-11", run_end="2019-11-11 11:26:03 AM PDT"
        )
    )
    assert _cal(ctx, "background")["age_days"] == 335


def test_an_unconverted_time_zone_is_kept_as_text(tmp_path):
    ctx = read_run_context(
        F.quantstudio_csv(tmp_path / "x.csv", run_end="2019-09-11 11:04:11 AM CEST")
    )
    assert ctx.run["end"] == "2019-09-11T11:04:11" and ctx.run["time_zone"] == "CEST"
    assert ctx.facts["f_instr_run_time_zone"].value == "CEST"
    assert ic.NOTE_TZ_NOT_CONVERTED in ctx.notes


def test_an_expired_flag_from_the_file(tmp_path):
    ctx = read_run_context(
        F.quantstudio_csv(tmp_path / "x.csv", background_on="2018-12-11", expired={"ROI": "Yes"})
    )
    assert _cal(ctx, "roi")["expired_at_run"] is True
    assert _cal(ctx, "background")["expired_at_run"] is False


@pytest.mark.parametrize(
    ("text", "iso", "note"),
    [
        ("2019-09-11 14:18:36 PM PDT", "2019-09-11T21:18:36Z", None),  # 24-hour hour + PM
        ("2019-09-11 11:04:11 AM PDT", "2019-09-11T18:04:11Z", None),
        ("2019-09-11 02:30:00 PM PST", "2019-09-11T22:30:00Z", None),
        ("2019-09-11 12:05:00 AM UTC", "2019-09-11T00:05:00Z", None),
        ("2019-09-11 12:05:00 PM GMT", "2019-09-11T12:05:00Z", None),
        ("2019-07-01 09:00:00 AM BST", "2019-07-01T08:00:00Z", None),
        ("2023-11-14 04:20:56 PM EST", "2023-11-14T21:20:56Z", None),  # Design & Analysis
        ("2024-04-22 03:55:26 PM EDT", "2024-04-22T19:55:26Z", None),
        ("2019-09-11 11:04:11 CEST", "2019-09-11T11:04:11", ic.NOTE_TZ_NOT_CONVERTED),
        ("2019-09-11 11:04:11", "2019-09-11T11:04:11", ic.NOTE_TZ_NOT_IN_FILE),
    ],
)
def test_export_times(text, iso, note):
    parsed = ic._parse_vendor_time(text, None)
    assert ic._iso(parsed.moment) == iso and parsed.note == note
    assert parsed.zone == ("CEST" if note == ic.NOTE_TZ_NOT_CONVERTED else None)


def test_quantstudio_txt_dialect(tmp_path):
    ctx = read_run_context(F.quantstudio_txt(tmp_path / "qs.txt"))
    assert ctx.source_kind == "quantstudio_export"
    assert ctx.identity["model"] == "QuantStudio™ 6 Flex System"
    assert ctx.run["end"] == "2018-06-01T15:20:00Z"  # 16:20 BST
    assert _cal(ctx, "background")["expired_at_run"] is True
    assert _cal(ctx, "background")["age_days"] == 456
    assert ctx.well_flags == {"A1": ["NOISE"]}
    assert ctx.facts["f_instr_cal_background_performed_on"].path == "export.txt:line 3"
    assert "QS6 Room 1" in ctx.aliases


def test_real_quantstudio_txt_exports_from_the_corpus():
    assert len(QS_TXT_REAL) == 6
    for path in QS_TXT_REAL:
        ctx = read_run_context(path)
        assert ctx.source_kind == "quantstudio_export", path.name
        assert "identity" in ctx.checked and ctx.identity["model"], path.name
        assert ctx.run["end"].endswith("Z") and ctx.run["date_source"] == "instrument", path.name
        assert ic.NOTE_TZ_NOT_CONVERTED not in ctx.notes, path.name  # EDT and EST
        view = json.dumps(ctx.model_view(), ensure_ascii=False)
        assert not any(v and v in view for k, v in ctx.identity.items() if k in ic.LOCAL_IDENTITY)
    with_cals = [p.name for p in QS_TXT_REAL if "calibrations" in read_run_context(p).checked]
    assert len(with_cals) == 5  # the results-only export has no calibration rows


# ---------------------------------------------------------------------------------------------
# Design & Analysis 2.x exports: the ``# Key: Value`` header (real files of the corpus)
# ---------------------------------------------------------------------------------------------


def test_design_and_analysis_exports_from_the_corpus():
    # QuantStudio 3, Design & Analysis 2.7: both files of both runs carry the run's header
    qs3 = sorted(DA_QS3.glob("*.csv"))
    assert len(qs3) == 4
    for path in qs3:
        ctx = read_run_context(path)
        assert ctx.source_kind == "quantstudio_export", path.name
        # instrument type, block type, serials, run times, software; no calibration, run state,
        # log or flag column is in the file, so the identity is all there is to check
        assert ctx.checked == ["identity"], path.name
        assert ctx.identity["model"] == "QuantStudio™ 3 System"
        assert ctx.identity["block_type"] == "96-Well 0.1-mL Block"
        assert ctx.identity["software"] == "Design & Analysis Software v2.7.0"
        assert ctx.calibrations == [] and ctx.well_flags == {} and ctx.run["state"] is None
        assert ctx.model_view()["serials_present"] == ["block_serial", "serial"]  # cover empty
    cov2 = read_run_context(DA_QS3 / "2023-11-14_Cov2_Copy_Results_20240422_155540.csv")
    assert cov2.run["start"] == "2023-11-14T21:20:56Z"  # 04:20:56 PM EST
    assert cov2.run["end"] == "2023-11-14T22:19:47Z"  # "Run End Data/Time", as the file spells it
    assert (cov2.run["date"], cov2.run["date_source"]) == ("2023-11-14", "instrument")
    assert "time_zone" not in cov2.run and ic.NOTE_TZ_NOT_CONVERTED not in cov2.notes
    assert cov2.facts["f_instr_run_start"].path == "export.csv:line 11"
    assert cov2.facts["f_instr_serial"].path == LOCAL_ONLY + "export.csv:line 8"
    assert cov2.facts["f_instr_block_serial"].path == LOCAL_ONLY + "export.csv:line 10"
    assert cov2.facts["f_instr_instrument_name"].path.startswith(LOCAL_ONLY)
    assert ic.NOTE_USER_NAME in cov2.notes  # "Operator: DEFAULT"
    assert ic.NOTE_PERSONAL_FIELD in cov2.notes  # "File Name: <run>.eds"

    # a 7500 run in the same dialect: other run-time keys, its serial written "null"
    m7500 = read_run_context(DA_7500 / "Zymo_LOD_1x_2020-04-18_Copy_Results.csv")
    assert m7500.source_kind == "quantstudio_export" and m7500.checked == ["identity"]
    assert m7500.identity["model"] == "7500 System" and m7500.identity["serial"] is None
    assert m7500.run["start"] == "2020-04-19T02:08:17Z"  # "Plate Run Start", 07:08:17 PM PDT
    assert m7500.run["end"] == "2020-04-19T04:00:39Z"
    assert m7500.run["date"] == "2020-04-18"  # the run's own calendar day
    assert ic.NOTE_OPERATOR_PATH in m7500.notes  # "Plate File Name" is a path

    # the corpus's synthetic export of the QuantStudio layout: no run times
    synth = read_run_context(DA_SYNTH / "qpilot-synthetic_Results.csv")
    assert synth.source_kind == "quantstudio_export" and synth.checked == ["identity"]
    assert synth.identity["model"] == "QuantStudio™ 5 System"
    assert synth.run["date"] is None and synth.run["date_source"] is None


@pytest.mark.parametrize("path", DA_REAL, ids=lambda p: p.name)
def test_design_and_analysis_serials_and_personal_fields_stay_local(path):
    header = _hash_header(path)
    ctx = read_run_context(path)
    serials = [v for k, v in header.items() if "serial" in k and v and v != "null"]
    assert serials or path.parent == DA_7500
    view = json.dumps(ctx.model_view(), ensure_ascii=False)
    for serial in serials:
        assert serial in ctx.aliases and serial not in view  # the logbook keeps it, locally
    for fact in ctx.facts.values():
        if fact.value in serials or fact.value in ctx.aliases:
            assert is_local_only(fact), fact.id
    assert not any(alias in view for alias in ctx.aliases)
    dump = _dump(ctx)  # the operator, user and free-text fields leave a fixed note only
    for key in ("file name", "plate file name", "operator", "user name", "comment", "description"):
        if header.get(key):
            assert header[key] not in dump, key


# ---------------------------------------------------------------------------------------------
# CFX Run Information
# ---------------------------------------------------------------------------------------------


def test_cfx_run_information(tmp_path):
    ctx = read_run_context(F.cfx_run_information(tmp_path / "Run Information.csv"))
    assert ctx.source_kind == "cfx_run_information"
    assert ctx.run["start"] == "2020-02-27T10:36:22Z" and ctx.run["end"] == "2020-02-27T12:05:59Z"
    assert ctx.identity["serial"] == "CC000123"
    assert ctx.identity["optical_head_serial"] == "785BR0001"
    assert ctx.identity["software"] == "CFX Maestro 4.1.2433.1219"
    assert ctx.identity["model"] == "Bio-Rad CFX"
    assert (
        ctx.facts["f_instr_optical_head_serial"].path == LOCAL_ONLY + "run_information.csv:line 12"
    )
    assert ic.NOTE_USER_NAME in ctx.notes and ic.NOTE_PERSONAL_FIELD in ctx.notes


def test_cfx_day_first_dates(tmp_path):
    ctx = read_run_context(
        F.cfx_run_information(tmp_path / "ri.csv", started="27/02/2020 10:36:22 UTC")
    )
    assert ctx.run["start"] == "2020-02-27T10:36:22Z"


def test_real_cfx_run_information_from_the_corpus():
    assert len(CFX_REAL) == 4  # CFX Manager 3.1 (3 runs) and CFX Maestro 4.0
    for path in CFX_REAL:
        ctx = read_run_context(path)
        assert ctx.source_kind == "cfx_run_information", path.name
        assert ctx.checked == ["identity"], path.name  # no run status key in a real file
        assert ctx.model_view()["serials_present"] == ["optical_head_serial", "serial"]
        view = json.dumps(ctx.model_view(), ensure_ascii=False)
        assert not any(v and v in view for k, v in ctx.identity.items() if k in ic.LOCAL_IDENTITY)
        assert ic.NOTE_USER_NAME in ctx.notes, path.name
    maestro = read_run_context(next(p for p in CFX_REAL if "covmatic" in str(p)))
    assert maestro.run["start"] == "2020-10-21T20:33:35Z"  # 10/21/2020: month first
    manager = read_run_context(next(p for p in CFX_REAL if "gapdh" in p.name))
    # 09/05/2016 on its own does not settle the day-month order
    assert manager.run["start"] is None and ic.NOTE_DATE_AMBIGUOUS in manager.notes


def test_a_cfx_manager_run_name_leaves_neither_its_user_nor_its_serial_in_the_model_view():
    # CFX Manager names a run "<user>_<date time>_<serial>"; the user and the serial are read
    # from the real file's name here, never written into the test
    (named,) = (c for c in map(read_run_context, CFX_REAL) if c.identity["serial"] in c.source_file)
    assert re.fullmatch(CFX_MANAGER_NAME, named.source_file)
    user, serial = named.source_file.split("_", 1)[0], named.identity["serial"]
    assert len(user) >= 3 and len(serial) >= 4  # long enough to be found if it were copied
    view = named.model_view()
    assert view["source_file"] == "….csv" and view["source_kind"] == "cfx_run_information"
    dumped = json.dumps(view, ensure_ascii=False)
    assert user not in dumped and serial not in dumped
    # the shape a study keeps in run_context.json and reads back for the Run Gate
    assert RunContext.model_validate(view).source_file == "….csv"


def test_a_model_file_name_keeps_a_run_file_suffix_only():
    assert ic.model_file_name("run_2016-09-04 16-12-03_SERIAL_Run Information.csv") == "….csv"
    assert ic.model_file_name("Plate 1.EDS") == "….eds"
    assert ic.model_file_name("rdml") == "…"  # an RDML document read without a file
    assert ic.model_file_name("run.backup") == "…"  # not a suffix qPilot reads run files from


# ---------------------------------------------------------------------------------------------
# RDML
# ---------------------------------------------------------------------------------------------


def test_biorad_instrument_string():
    parsed = parse_instrument_string(F.BIORAD_INSTRUMENT)
    assert parsed["model"] == "Bio-Rad CFX" and parsed["instrument_type"] == "96FX"
    assert parsed["serial"] == "CC000123"
    assert parsed["shuttle_serial"] == "SG0001"
    assert parsed["optical_head_serial"] == "785BR0001"  # no space before "Optical Head SN"
    assert parsed["firmware"].split("; ")[0] == "PXA270 Processor Firmware: 3.2.128.129"
    assert "8051 Motorized Lid: 54" in parsed["firmware"]


def test_other_instrument_strings():
    assert parse_instrument_string("LC96SN90001")["serial"] == "90001"
    assert parse_instrument_string("LC96SN90001")["model"] == "LightCycler 96"
    assert parse_instrument_string("QuantStudio Dx")["model"] == "QuantStudio Dx"
    assert parse_instrument_string("the machine in room 4")["model"] is None
    assert parse_instrument_string(None)["model"] is None


def test_biorad_rdml_zip_whose_member_is_named_after_the_file(tmp_path):
    software = "BioRadCFXManager.exe|3.0.1224.1015. (OS-Microsoft Windows NT 5.1)"
    runs = [
        {"id": "Amp Step 3_FAM", "instrument": F.BIORAD_INSTRUMENT, "software": software},
        {"id": "Amp Step 3_Cy5", "instrument": F.BIORAD_INSTRUMENT, "software": software},
    ]
    path = F.write_rdml(tmp_path / "BioRad_qPCR_melt.rdml", runs, member="BioRad_qPCR_melt.xml")
    contexts = run_contexts_from_rdml(path)
    assert [c.run_id for c in contexts] == ["Amp Step 3_FAM", "Amp Step 3_Cy5"]
    first = contexts[0]
    assert first.identity["serial"] == "CC000123" and first.identity["shuttle_serial"] == "SG0001"
    assert first.identity["software"] == "BioRadCFXManager 3.0.1224.1015"
    assert first.facts["f_instr_amp_step_3_fam_serial"].path == (
        LOCAL_ONLY + "BioRad_qPCR_melt.xml:experiment[exp1]/run[Amp Step 3_FAM]/instrument"
    )
    assert F.BIORAD_INSTRUMENT in first.aliases
    assert first.run["date_source"] is None
    combined = read_run_context(path)
    assert combined.run_id is None and combined.identity["serial"] == "CC000123"
    assert combined.facts["f_instr_n_runs"].value == 2
    assert combined.facts["f_instr_n_runs_instrument"].value == 2
    assert "CC000123" not in json.dumps(combined.model_view())


def test_rdml_run_dates_and_the_u7_flag(tmp_path):
    runs = [
        {"id": "a", "instrument": "QuantStudio Dx", "runDate": "2010-01-01T03:12:59.214"},
        {"id": "b", "instrument": "LC96SN90001", "runDate": "2014-08-19T11:30:20"},
        {"id": "c", "runDate": "2024-12-10T14:00:00Z"},
        {"id": "d", "runDate": "1970-01-01T00:00:00"},
    ]
    a, b, c, d = run_contexts_from_rdml(F.write_rdml(tmp_path / "x.rdml", runs))
    assert a.run["start"] is None and ic.NOTE_RUN_DATE_DOUBTFUL in a.notes
    assert a.facts["f_instr_a_recorded_run_date"].value == "2010-01-01T03:12:59"
    assert b.run["start"] == "2014-08-19T11:30:20" and ic.NOTE_TZ_NOT_IN_FILE in b.notes
    assert b.run["date_source"] == "instrument" and b.identity["serial"] == "90001"
    assert c.run["start"] == "2024-12-10T14:00:00Z"
    assert d.run["start"] is None  # before any real-time instrument: not a run date


def test_run_name_date_rule(tmp_path):
    runs = [
        {"id": "PRKACB_20080311_bis"},
        {"id": "HMBS_20080318"},
        {"id": "competimer_set"},
        {"id": "X_20081340"},  # month 13: no date
        {"id": "Y_2008031"},  # seven digits: no date
    ]
    contexts = run_contexts_from_rdml(F.write_rdml(tmp_path / "x.rdml", runs))
    dates = [(c.run["start"], c.run["date_source"]) for c in contexts]
    assert dates == [
        ("2008-03-11", "run name"),
        ("2008-03-18", "run name"),
        (None, None),
        (None, None),
        (None, None),
    ]
    first = contexts[0]
    assert first.facts["f_instr_prkacb_20080311_bis_run_start"].path.endswith("/@id (run name)")
    assert first.summary()["date_source"] == "run name"
    assert first.identity == dict.fromkeys(ic.IDENTITY_KEYS)  # never an instrument fact


def test_plain_xml_rdml(tmp_path):
    path = tmp_path / "plain.rdml"
    path.write_bytes(F.rdml_xml([{"id": "r1", "instrument": "LightCycler480"}]))
    ctx = read_run_context(path)
    assert ctx.run_id == "r1" and ctx.identity["model"] == "LightCycler480"
    other = tmp_path / "other.xml"
    other.write_text("<plate><well/></plate>", encoding="utf-8")
    with pytest.raises(InstrumentFileError, match="not RDML"):
        read_run_context(other)


def test_ci_fixture_run_name_dates():
    path = FIXTURES / "vermeulen_std_150000.rdml"
    contexts = run_contexts_from_rdml(path)
    assert len(contexts) == 64
    assert all(c.run["date_source"] == "run name" for c in contexts)
    days = sorted({c.run["date"] for c in contexts})
    assert (len(days), days[0], days[-1]) == (15, "2008-02-20", "2008-03-18")
    assert not any(any(c.identity.values()) for c in contexts)
    from_doc = run_contexts_from_rdml(load(path), source_file=path.name)
    assert [c.summary() for c in from_doc] == [c.summary() for c in contexts]


@pytest.mark.demo_data
def test_demo_rdml_has_no_instrument_fields(demo_rdml_path):
    with work_time() as spent:
        contexts = run_contexts_from_rdml(demo_rdml_path)
    assert spent.seconds < 10, spent
    assert len(contexts) == 67
    assert sum(1 for c in contexts if any(c.identity.values())) == 0  # 0 of 67 name it
    named = [c for c in contexts if c.run["date_source"] == "run name"]
    assert len(named) == 64
    assert {c.run_id for c in contexts if c.run["date_source"] is None} == {
        "94_replicates_4_dilutions_set",
        "380_replicates_set",
        "competimer_set",
    }
    days = sorted({c.run["date"] for c in named})
    assert (len(days), days[0], days[-1]) == (15, "2008-02-20", "2008-03-18")
    whole = read_run_context(demo_rdml_path)
    values = {fid: fact.value for fid, fact in whole.facts.items()}
    assert values == {
        "f_instr_n_runs": 67,
        "f_instr_n_runs_instrument": 0,
        "f_instr_n_runs_dated": 64,
        "f_instr_n_runs_dated_by_name": 64,
        "f_instr_n_run_dates": 15,
        "f_instr_first_run_date": "2008-02-20",
        "f_instr_last_run_date": "2008-03-18",
    }


def test_method_card_lists_real_tests():
    assert {"id", "version", "inputs", "outputs", "acceptance_tests", "licence"} <= set(METHOD_CARD)
    root = Path(__file__).resolve().parents[2]
    assert (root / METHOD_CARD["card"]).is_file()
    for test in METHOD_CARD["acceptance_tests"]:
        file, _, name = test.partition("::")
        assert f"def {name}(" in (root / file).read_text(encoding="utf-8"), test


def test_rdml_run_contexts_are_parsed_once_per_xml_and_handed_out_as_copies(tmp_path):
    """perf: the analysis, the gate and the evidence read the same file's runs; parse once."""
    runs = [{"id": "a", "instrument": "LC96SN90001", "runDate": "2014-08-19T11:30:20"}]
    path = F.write_rdml(tmp_path / "x.rdml", runs)
    ic._CONTEXTS.clear()
    calls = []
    real = ic._parse_rdml_contexts
    try:
        ic._parse_rdml_contexts = lambda *a, **k: calls.append(1) or real(*a, **k)
        first = run_contexts_from_rdml(path)
        again = run_contexts_from_rdml(path)
        other = run_contexts_from_rdml(path, source_file="y.rdml")
    finally:
        ic._parse_rdml_contexts = real
    assert len(calls) == 2  # x.rdml once, y.rdml once
    assert again == first and again[0] is not first[0]
    again[0].notes.append("changed by a caller")
    assert run_contexts_from_rdml(path) == first  # a caller's change never reaches the next
    assert len(other) == len(first) and other != first  # the file's name is part of each
