"""Synthetic instrument run files for the instrument-context and G-INSTR tests.

Every file is built here with the standard library, in a test's ``tmp_path``. None is copied from
a vendor or a public repository: the layouts follow what the measured oracle
(``runtime/understand/ledger-instrument-oracle.md`` Task B) read from real files, and every
value (serials, dates, names) is invented. Where a layout is not known from a real file (the
QuantStudio ``messages.log`` line syntax, ``run_summary.json`` keys, the temperature log, the
TXT export and the CFX Run Information export), the builders write the assumed layout that the
reader documents as unverified.
"""

from __future__ import annotations

import datetime as dt
import math
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

DAY_MS = 86_400_000
OPERATOR = "Alexandra Quill"  # a made-up person: must never appear in any reader output
OPERATOR_PATH = r"D:\Users\Administrator\Experiments\AlexandraQuill\2019-05-10_090000.eds"


def epoch_ms(iso: str) -> int:
    """Milliseconds since 1970 for an ISO time in UTC (``2019-05-10T09:00:00``)."""
    moment = dt.datetime.fromisoformat(iso).replace(tzinfo=dt.UTC)
    return int(moment.timestamp() * 1000)


# ---------------------------------------------------------------------------------------------
# .eds archives
# ---------------------------------------------------------------------------------------------


def experiment_xml(
    *,
    state: str = "COMPLETE",
    start_ms: int | None = None,
    end_ms: int | None = None,
    type_id: str = "appletini",
    serial: str | None = None,
    serial_path: str = "RunInfo/InstrumentSerialNumber",
    instrument_name: str | None = None,
) -> str:
    """``experiment.xml`` with the 7500 file's top-level children, plus an optional serial."""
    run_info = ""
    if serial is not None or instrument_name is not None:
        parts = serial_path.split("/")
        inner = f"<{parts[-1]}>{serial}</{parts[-1]}>" if serial is not None else ""
        if instrument_name is not None:
            inner += f"<InstrumentName>{instrument_name}</InstrumentName>"
        for tag in reversed(parts[:-1]):
            inner = f"<{tag}>{inner}</{tag}>"
        run_info = f"    {inner}\n"
    times = ""
    if start_ms is not None:
        times += f"    <RunStartTime>{start_ms}</RunStartTime>\n"
    if end_ms is not None:
        times += f"    <RunEndTime>{end_ms}</RunEndTime>\n"
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        "<Experiment>\n"
        "    <Name>Synthetic Example</Name>\n"
        "    <Description>Made up for a test</Description>\n"
        f"    <Operator>{OPERATOR}</Operator>\n"
        f"    <RunState>{state}</RunState>\n"
        "    <FinalAnalysisCompleted>true</FinalAnalysisCompleted>\n"
        "    <ModifiedTime>1454933983298</ModifiedTime>\n"
        f"{times}"
        "    <PreReadState>INIT</PreReadState>\n"
        f"    <FileName>{OPERATOR_PATH}</FileName>\n"
        "    <Type><Id>Std</Id><Name>Quantitation - Standard Curve</Name></Type>\n"
        "    <Samples><Name>pop1</Name><Color>-8076815</Color></Samples>\n"
        f"{run_info}"
        f"    <InstrumentTypeId>{type_id}</InstrumentTypeId>\n"
        "</Experiment>\n"
    )


def _data_block(rows: int = 3) -> list[str]:
    return ["1=<<eof", *("-301.0,26.1,-356.5,25.0" for _ in range(rows)), "eof"]


def calibration_ini(
    section: str,
    *,
    timestamp_ms: int,
    expiry_ms: int | None = None,
    expiry_key: str = "expirytime",
    instrument_type: str = "sds7500fast",
    instrument_id: str = "null",
    block_id: str = "",
) -> str:
    """A calibration ``.ini`` in the 7500 layout: CRLF, ``#`` comments, ``<<eof`` data blocks."""
    lines = [
        "# Instrument calibration file. Synthetic copy of the layout for a test.",
        "# The timestamp field in the [head] section is the time elapsed, in milliseconds, "
        "since midnight, January 1, 1970 UTC.",
        "",
        "[head]",
        "name=Calibration",
        "version=1.0.0",
        "operator=null",
        "# timestamp: the time elapsed, in milliseconds, since midnight, January 1, 1970 UTC.",
        f"timestamp={timestamp_ms}",
    ]
    if expiry_ms is not None:
        lines.append(f"{expiry_key}={expiry_ms}")
    lines += [
        "digest=null",
        "",
        "[instrument]",
        f"id={instrument_id}",
        f"type={instrument_type}",
        "",
        "[scanner]",
        "id=*",
        "filters=1,2,3,4,5",
        "",
        "[block]",
        f"id={block_id}",
        "type=96fast",
        "rows=8",
        "columns=12",
        "",
        "[plate]",
        "id=null",
        "",
        "[result]",
        "result=false",
        "",
        f"[{section}]",
        *_data_block(),
        "",
    ]
    return "\r\n".join(lines)


def puredye_ini(
    *,
    timestamp_ms: int,
    dyes: Sequence[str] = ("FAM", "ROX", "SYBR", "TEXAS RED", "VIC"),
    per_dye: Mapping[str, tuple[int, int]] | None = None,
    expiry_ms: int | None = None,
) -> str:
    """``puredye.ini``: a ``[puredyes]`` list then one section per dye (``…-time=0`` = unset)."""
    head = calibration_ini("puredyes", timestamp_ms=timestamp_ms, expiry_ms=expiry_ms)
    head = head.split("[puredyes]")[0]
    lines = [head.rstrip("\r\n"), "", "[puredyes]", "dyes=" + ",".join(dyes), ""]
    for dye in dyes:
        cal, exp = (per_dye or {}).get(dye, (0, 0))
        lines += [
            f"[{dye}]",
            "operator=null",
            f"calibration-time={cal}",
            f"expiration-time={exp}",
            "temperature=0.0",
            "result=false",
            *_data_block(2),
            "",
        ]
    return "\r\n".join(lines)


def messages_log(
    *,
    start: str = "2019-05-10 09:00:00",
    cycles: int = 40,
    serial_line: str | None = (
        "Serial Number: 278880001 [Instrument] BLK-1001 [Block] HC-2001 [Heated Cover]"
    ),
    pause_at: int | None = None,
    lid_open_at: int | None = None,
    abort_at: int | None = None,
    power_at: int | None = None,
    complete: bool = True,
    noise_per_cycle: int = 3,
    drawer_before_start: bool = True,
) -> str:
    """A ``messages.log`` in the assumed line syntax (U4): timestamp, level, message.

    It carries the noise the plan measured (configuration queries answered ``ERRor``) and, when
    asked, a pause and its resume, a lid opening, an abort or a power event at a given cycle.
    """
    clock = dt.datetime.fromisoformat(start)
    out: list[str] = []

    def say(message: str, level: str = "INFO", seconds: int = 20) -> None:
        nonlocal clock
        out.append(f"{clock:%Y-%m-%d %H:%M:%S} {level} {message}")
        clock += dt.timedelta(seconds=seconds)

    if drawer_before_start:
        say("Drawer opened")  # loading the plate: before the run, never an event
        say("Drawer closed")
    say("Run started." + (f" {serial_line}" if serial_line else ""))
    say("Stage 1 Step 1 hold 95.0 C")
    for cycle in range(1, cycles + 1):
        say(f"Stage 2 Cycle {cycle} of {cycles}")
        for _ in range(noise_per_cycle):
            say("ERRor -113: LEDSTATUS? not supported", level="DEBUG", seconds=1)
        if pause_at == cycle:
            say("Run paused by user", seconds=240)
            say("Run resumed")
        if lid_open_at == cycle:
            say("Heated cover opened")
            say("Heated cover closed")
        if power_at == cycle:
            say("Power failure detected", level="WARN")
            say("Power restored", level="WARN")
        if abort_at == cycle:
            say("Run aborted by user", level="WARN")
            return "\n".join(out) + "\n"
    if complete:
        say("Run completed.")
    return "\n".join(out) + "\n"


def temperature_log(
    *,
    cycles: int = 40,
    drift_at_cycle: int | None = None,
    drift_c: float = 0.0,
    lid_dip_c: float = 0.0,
) -> str:
    """A 1-Hz temperature log in the assumed layout (U4): setpoint, sample, three zones, cover.

    The sample follows the setpoint with a lag of a few seconds; ``drift_c`` holds the sample
    that far off the setpoint through the anneal of ``drift_at_cycle``.
    """
    rows = ["Time,Stage,Cycle,Setpoint,Sample,Block1,Block2,Block3,Cover"]
    sample = 25.0
    second = 0

    def hold(stage: int, cycle: int, setpoint: float, seconds: int, drift: float = 0.0) -> None:
        nonlocal sample, second
        for _ in range(seconds):
            sample += (setpoint + drift - sample) * 0.45
            wobble = 0.03 * math.sin(second / 3.0)
            value = sample + wobble
            cover = 105.0 - lid_dip_c * (cycle == cycles // 2) + 0.05 * math.sin(second / 7.0)
            rows.append(
                f"{second},{stage},{cycle},{setpoint:.2f},{value:.3f},{value - 0.1:.3f},"
                f"{value + 0.02:.3f},{value + 0.11:.3f},{cover:.3f}"
            )
            second += 1

    hold(1, 0, 95.0, 120)
    for cycle in range(1, cycles + 1):
        hold(2, cycle, 95.0, 15)
        drift = drift_c if cycle == drift_at_cycle else 0.0
        hold(2, cycle, 60.0, 30, drift)
    return "\n".join(rows) + "\n"


def write_eds(
    path: Path,
    members: Mapping[str, str | bytes],
    *,
    software: str = "QuantStudio Design & Analysis Software v1.4.3",
    upper_backslash: Iterable[str] = (),
) -> Path:
    """Zip ``members`` under ``apldbio/sds/``; names in ``upper_backslash`` the 7500's way."""
    upper = set(upper_backslash)
    manifest = (
        "Manifest-Version: 1.0\nContent-Type: Std\n"
        f"Implementation-Version: {software}\nSpecification-Vendor: Synthetic\n"
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("apldbio/sds/Manifest.mf", manifest)
        for rel, data in members.items():
            if rel in upper:
                folder, _, name = rel.rpartition("/")
                full = "APLDBIO\\SDS\\" + folder.upper().replace("/", "\\") + "/" + name
            else:
                full = "apldbio/sds/" + rel
            archive.writestr(full, data)
        archive.writestr("[Content_Types].xml", "<Types/>")
    return path


RUN_START = "2019-05-10T09:00:00"
RUN_END = "2019-05-10T10:40:00"


def qs_v1_expired(path: Path, *, block_serial: str = "BLK-1001", pause_at: int | None = 23) -> Path:
    """A QuantStudio-class run: background 412 days old with a 180-day expiry, a pause at 23."""
    start, end = epoch_ms(RUN_START), epoch_ms(RUN_END)
    background = start - 412 * DAY_MS
    serial_line = (
        f"Serial Number: 278880001 [Instrument] {block_serial} [Block] HC-2001 [Heated Cover]"
    )
    members = {
        "experiment.xml": experiment_xml(
            start_ms=start, end_ms=end, type_id="appletini", serial="278880001"
        ),
        "calibrations/background.ini": calibration_ini(
            "background", timestamp_ms=background, expiry_ms=background + 180 * DAY_MS,
            instrument_type="appletini",
        ),
        "calibrations/roi.ini": calibration_ini(
            "roi", timestamp_ms=background, expiry_ms=background + 730 * DAY_MS,
            instrument_type="appletini",
        ),
        "calibrations/uniformity.ini": calibration_ini(
            "uniformity", timestamp_ms=background, expiry_ms=background + 730 * DAY_MS,
            instrument_type="appletini",
        ),
        "calibrations/puredye.ini": puredye_ini(
            timestamp_ms=start - 128 * DAY_MS, expiry_ms=start - 128 * DAY_MS + 730 * DAY_MS
        ),
        "messages.log": messages_log(pause_at=pause_at, serial_line=serial_line),
        "logs/temperature.log": temperature_log(),
    }  # fmt: skip
    return write_eds(path, members)


def stepone(path: Path) -> Path:
    """A StepOnePlus run: every calibration file stamped with the run's own start time."""
    start, end = epoch_ms("2025-03-04T10:15:00"), epoch_ms("2025-03-04T12:01:00")
    members = {
        "experiment.xml": experiment_xml(start_ms=start, end_ms=end, type_id="steponeplus"),
        "calibrations/background.ini": calibration_ini("background", timestamp_ms=start),
        "calibrations/uniformity.ini": calibration_ini("uniformity", timestamp_ms=start),
        "calibrations/puredye.ini": puredye_ini(timestamp_ms=start),
    }
    return write_eds(path, members, software="StepOne Software v2.3")


def like_7500(path: Path) -> Path:
    """The real 7500 layout: upper-case backslash calibration names, ``expiration-time=0``."""
    start, end = 1194659214000, 1194664259000  # the oracle's run: 2007-11-10, 84 minutes
    members = {
        "experiment.xml": experiment_xml(start_ms=start, end_ms=end, type_id="sds7500fast"),
        "plate_setup.xml": "<Plate/>",
        "multicomponent_data.txt": "StepOne v2.0 MulticomponentData\n",
        "images/temperatures.txt": "n=60.0," * 40 + "\n",
        "calibrations/background.ini": calibration_ini("background", timestamp_ms=1192044039119),
        "calibrations/uniformity.ini": calibration_ini("uniformity", timestamp_ms=1192044039104),
        "calibrations/puredye.ini": puredye_ini(timestamp_ms=1192044039104),
    }
    upper = {
        "calibrations/background.ini",
        "calibrations/uniformity.ini",
        "calibrations/puredye.ini",
    }
    return write_eds(path, members, software="7500 Software v2.3", upper_backslash=upper)


def eds2_json(path: Path) -> Path:
    """An archive whose run facts are only in ``run/run_summary.json`` and ``summary.json``."""
    import json

    run_summary = {
        "runState": "COMPLETED",
        "runStartTime": epoch_ms("2024-06-03T08:00:00"),
        "runEndTime": epoch_ms("2024-06-03T09:35:00"),
        "instrument": {
            "serialNumber": "278990004",
            "instrumentType": "QuantStudio 7 Pro",
            "firmwareVersion": "1.2.0",
            "block": {"serialNumber": "BLK-7007", "type": "96-Well 0.2-mL Block"},
            "heatedCover": {"serialNumber": "HC-7008"},
        },
        "operator": OPERATOR,
        "plateBarcode": "PLATE-0001",
        "acquisitionCount": 41,
    }
    summary = {"experimentName": "made up", "instrumentName": "QS7 Room 4"}
    members = {
        "run/run_summary.json": json.dumps(run_summary),
        "summary.json": json.dumps(summary),
    }
    return write_eds(path, members)


def aborted(path: Path) -> Path:
    """A run whose experiment.xml says ``ABORTED`` and whose log stops at an abort."""
    start, end = epoch_ms("2021-01-12T14:00:00"), epoch_ms("2021-01-12T14:31:00")
    members = {
        "experiment.xml": experiment_xml(
            state="ABORTED", start_ms=start, end_ms=end, type_id="paragon"
        ),
        "messages.log": messages_log(start="2021-01-12 14:00:00", abort_at=12, complete=False),
    }
    return write_eds(path, members)


# ---------------------------------------------------------------------------------------------
# QuantStudio results exports and CFX Run Information
# ---------------------------------------------------------------------------------------------

QS5_DYES = ("ABY", "CY5", "FAM", "JUN", "MUSTANG PURPLE", "NED", "ROX", "SYBR", "TAMRA", "VIC")
QS3_CALS = ("CM MELTDOCTOR",)
QS3_DYES = ("ABY", "FAM", "JUN", "MELTDOCTOR", "NED", "ROX", "SYBR", "TAMRA", "VIC")
FLAG_COLUMNS = ("CQCONF", "EXPFAIL", "PRFLOW", "HIGHSD", "BADROX", "PRFDROP")


def _pad(row: str, width: int) -> str:
    return row + "," * max(0, width - 1 - row.count(","))


def quantstudio_csv(
    path: Path,
    *,
    model: str = "QuantStudio™ 5 System",
    serial: str = "278880001",
    block: str = "384-Well Block",
    background_on: str = "11-12-2018",
    others_on: str | None = None,
    expired: Mapping[str, str] | None = None,
    run_end: str = "2019-09-11 11:04:11 AM PDT",
    variant: str = "qs5",
    flags: Mapping[str, Sequence[str]] | None = None,
    name_padding: str = "",
    width: int = 36,
) -> Path:
    """A results export: 45 ``key,value`` rows padded to ``width`` fields, a blank row, a table.

    ``variant`` ``qs5`` lists the QS5 dyes; ``qs3`` swaps CY5 and MUSTANG PURPLE for the
    MELTDOCTOR calibrations, as the QS3 files do. ``flags`` maps a well to the flags set on it.
    """
    others_on = others_on or background_on
    expired = expired or {}
    rows = [f"Block Type,{block}"]

    def cal(what: str, day: str) -> None:
        # the real files end these three keys with a space before the comma; the dyes do not
        space = " " if what in ("Background", "ROI", "Uniformity") else ""
        rows.append(f"Calibration {what} is expired{space},{expired.get(what, 'No')}")
        rows.append(f"Calibration {what} performed on,{day}")

    cal("Background", background_on)
    if variant == "qs3":
        for what in QS3_CALS:
            cal(what, background_on)
        for dye in QS3_DYES:
            cal(f"Pure Dye {dye}", others_on)
    else:
        for dye in QS5_DYES:
            cal(f"Pure Dye {dye}", others_on)
    cal("ROI", others_on)
    cal("Uniformity", others_on)
    rows += [
        "Chemistry,TAQMAN",
        "Date Created,2019-09-11 14:18:36 PM PDT",
        "Experiment Barcode",
        "Experiment Comment",
        f"Experiment File Name,{OPERATOR_PATH}",
        "Experiment Name,2019-09-10_120614",
        f"Experiment Run End Time,{run_end}",
        "Experiment Type,Comparative Cт (ΔΔCт) ",
        f"Instrument Name,{name_padding}{serial}",
        f"Instrument Serial Number,{serial}",
        f"Instrument Type,{model}",
        "Passive Reference,ROX",
        "Post-read Stage/Step",
        "Pre-read Stage/Step",
        "Quantification Cycle Method,Ct",
        "Signal Smoothing On,true",
        'Stage/ Cycle where Ct Analysis is performed,"Stage2, Step2"',
        f"User Name,{OPERATOR}",
    ]
    lines = [_pad(row, width) for row in rows]
    lines.append("," * (width - 1))
    columns = ["Well", "Well Position", "Omit", "Sample Name", "Target Name", "Task", "CT"]
    columns += list(FLAG_COLUMNS)
    lines.append(",".join(columns))
    flags = flags or {}
    number = 0
    for row_letter in "AB":
        for col in range(1, 4):
            number += 1
            well = f"{row_letter}{col}"
            marks = ["Y" if flag in flags.get(well, ()) else "N" for flag in FLAG_COLUMNS]
            lines.append(
                ",".join(
                    [str(number), well, "false", f"S{number}", "GAPDH", "UNKNOWN", "21.4", *marks]
                )
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def quantstudio_txt(path: Path) -> Path:
    """The TXT dialect (U5): ``* key = value`` header rows, then tab-separated sections."""
    lines = [
        "* Block Type = 96-Well Block (0.2mL)",
        "* Calibration Background is expired = Yes",
        "* Calibration Background performed on = 2017-03-02",
        "* Calibration ROI is expired = No",
        "* Calibration ROI performed on = 2018-01-15",
        "* Experiment File Name = " + OPERATOR_PATH,
        "* Experiment Run End Time = 2018-06-01 16:20:00 PM BST",
        "* Instrument Name = QS6 Room 1",
        "* Instrument Serial Number = 278770003",
        "* Instrument Type = QuantStudio™ 6 Flex System",
        "* User Name = " + OPERATOR,
        "",
        "[Sample Setup]",
        "Well\tWell Position\tSample Name\tTarget Name",
        "1\tA1\tS1\tGAPDH",
        "",
        "[Results]",
        "Well\tWell Position\tSample Name\tCT\tNOISE\tSPIKE",
        "1\tA1\tS1\t22.1\tY\tN",
        "2\tA2\tS2\t22.4\tN\tN",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def cfx_run_information(path: Path, *, started: str = "02/27/2020 10:36:22 UTC") -> Path:
    """A CFX "Run Information" key/value export in the assumed layout (U6)."""
    lines = [
        "File Name,C:\\Users\\AlexandraQuill\\Documents\\run_2020.pcrd",
        f"Created By User,{OPERATOR}",
        "Notes,",
        "ID,",
        f"Run Started,{started}",
        "Run Ended,02/27/2020 12:05:59 UTC",
        "Sample Vol,20",
        "Lid Temp,105",
        "Protocol File Name,C:\\Users\\AlexandraQuill\\protocol.prcl",
        "Plate Setup File Name,C:\\Users\\AlexandraQuill\\plate.pltd",
        "Base Serial Number,CC000123",
        "Optical Head Serial Number,785BR0001",
        "CFX Maestro Version,4.1.2433.1219",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------------------------
# RDML
# ---------------------------------------------------------------------------------------------

BIORAD_INSTRUMENT = (
    'Block Type "96FX", Cycler SN: CC000123, PXA270 Processor Firmware: 3.2.128.129, '
    "HC12 Thermal Control Firmware: 1.0.165.0, FX2 Controller Firmware: 1.35.0.0, "
    "Dsp Firmware Version: 1.123.0.0, 8051 Motorized Lid: 54, Shuttle SN: SG0001,"
    "Optical Head SN: 785BR0001"
)


def rdml_xml(runs: Sequence[Mapping[str, str | None]], *, version: str = "1.1") -> bytes:
    """An RDML document with one experiment and the given runs (id, instrument, runDate...)."""
    parts = [
        f'<rdml version="{version}" xmlns:rdml="http://www.rdml.org" xmlns="http://www.rdml.org">',
        "<dateMade>2014-02-24T13:39:29</dateMade>",
        '<experiment id="exp1">',
    ]
    for run in runs:
        parts.append(f'<run id="{run["id"]}">')
        parts.append("<description></description>")
        if run.get("instrument") is not None:
            parts.append(f"<instrument>{run['instrument']}</instrument>")
        if run.get("software"):
            name, _, version_text = str(run["software"]).partition("|")
            parts.append(
                f"<dataCollectionSoftware><name>{name}</name><version>{version_text}</version>"
                "</dataCollectionSoftware>"
            )
        parts.append("<pcrFormat><rows>8</rows><columns>12</columns></pcrFormat>")
        if run.get("runDate"):
            parts.append(f"<runDate>{run['runDate']}</runDate>")
        parts.append(
            '<react id="1"><sample id="s1"/><data><tar id="t1"/>'
            "<adp><cyc>1</cyc><tmp>60</tmp><fluor>0.1</fluor></adp></data></react>"
        )
        parts.append("</run>")
    parts += ["</experiment>", "</rdml>"]
    return "".join(parts).encode("utf-8")


def write_rdml(
    path: Path, runs: Sequence[Mapping[str, str | None]], *, member: str = "rdml_data.xml"
) -> Path:
    """A zipped RDML file; Bio-Rad names the member after the file, not ``rdml_data.xml``."""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, rdml_xml(runs))
    return path
