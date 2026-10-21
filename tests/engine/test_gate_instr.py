"""G-INSTR: Gate lines from what the run file says, and their wording (plan 2.4 + 3.5, L1)."""

import re

import pytest

from qpilot.core.validator import validate
from qpilot.explain.instrument_text import SENTENCES, line_tokens, render_gate
from qpilot.qpcr.gate_instr import (
    CODES,
    RULE_ID,
    GateLine,
    add_consequence,
    g_instr,
    needs_consequence,
)
from qpilot.qpcr.instrument_context import read_run_context, run_contexts_from_rdml
from tests.engine import instrument_files as F

# add_plan §2 status words: none of these may appear in a Gate line's wording
BANNED = (
    "diagnosis",
    "diagnose",
    "root cause",
    "error found",
    "validated",
    "valid run",
    "invalid",
    "faulty",
    "compliant",
    "IVD",
)


def _codes(lines):
    return [(line.status, line.code) for line in lines]


def _all_fixture_contexts(tmp_path):
    return [
        read_run_context(F.qs_v1_expired(tmp_path / "qs.eds")),
        read_run_context(F.stepone(tmp_path / "stepone.eds")),
        read_run_context(F.like_7500(tmp_path / "7500.eds")),
        read_run_context(F.eds2_json(tmp_path / "eds2.eds")),
        read_run_context(F.aborted(tmp_path / "aborted.eds")),
        read_run_context(F.quantstudio_csv(tmp_path / "qs5.csv")),
        read_run_context(F.quantstudio_txt(tmp_path / "qs.txt")),
        read_run_context(F.cfx_run_information(tmp_path / "cfx.csv")),
    ]


def test_pause_at_cycle_23_warns_naming_cycles_23_24(tmp_path):
    ctx = read_run_context(F.qs_v1_expired(tmp_path / "qs.eds", pause_at=23))
    lines = g_instr(ctx)
    pause = next(line for line in lines if line.code == "interrupted")
    assert pause.rule_id == RULE_ID == "G-INSTR"
    assert pause.status == "warn" and pause.cycles == [23, 24]
    assert needs_consequence(lines)
    text = render_gate(add_consequence(lines, n_changed=0, n_total=58))
    assert "The run was paused during cycles 23–24." in text.plain
    assert text.plain.endswith("Excluding this run changes 0 of 58 conclusions.")
    assert "{{" not in text.plain and "{{" in text.tokens


def test_wording_reads_like_the_plan_example(tmp_path):
    ctx = read_run_context(F.qs_v1_expired(tmp_path / "qs.eds", pause_at=None))
    lines = g_instr(ctx)
    assert _codes(lines) == [
        ("pass", "run_complete"),
        ("pass", "no_interruptions"),
        ("info", "calibration_expired"),
        ("pass", "hold_on_setpoint"),
    ]
    text = render_gate(lines)
    assert text.plain == (
        "Run completed. No pauses or lid openings. Background calibration done 412 days before "
        "this run, past the vendor's 180-day expiry. Hold temperatures stayed within 0.50 °C of "
        "the setpoint."
    )
    assert validate(text.tokens, {k: v for line in lines for k, v in line.facts.items()}).ok
    assert set(text.fact_ids) == {
        "f_instr_cal_background_label",
        "f_instr_cal_background_age_days",
        "f_instr_cal_background_interval_days",
        "f_instr_hold_limit_c",
    }
    assert 'data-fact="f_instr_cal_background_age_days"' in text.html


def test_an_expired_calibration_is_info_never_a_warning(tmp_path):
    ctx = read_run_context(F.qs_v1_expired(tmp_path / "qs.eds", pause_at=None))
    expired = [line for line in g_instr(ctx) if line.code == "calibration_expired"]
    assert [line.status for line in expired] == ["info"]
    assert CODES["calibration_expired"] == "info"


def test_expired_calibrations_with_the_same_age_share_a_line(tmp_path):
    every = {"Background": "Yes", "ROI": "Yes", "Uniformity": "Yes"}
    every |= {f"Pure Dye {dye}": "Yes" for dye in F.QS5_DYES}
    path = F.quantstudio_csv(tmp_path / "x.csv", background_on="2018-12-11", expired=every)
    lines = g_instr(read_run_context(path, date_order="DMY"))
    assert _codes(lines) == [("info", "calibration_expired")]
    assert render_gate(lines).plain == (
        "Background, Pure Dye ABY, Pure Dye CY5 and 10 more calibrations done 274 days before "
        "this run, past the vendor's expiry."
    )
    two = {"Background": "Yes", "ROI": "Yes"}
    path = F.quantstudio_csv(tmp_path / "y.csv", background_on="2018-12-11", expired=two)
    assert render_gate(g_instr(read_run_context(path))).plain == (
        "Background and ROI calibrations done 274 days before this run, past the vendor's expiry."
    )


def test_run_not_complete_warns(tmp_path):
    lines = g_instr(read_run_context(F.aborted(tmp_path / "aborted.eds")))
    assert _codes(lines) == [("warn", "run_not_complete"), ("warn", "aborted_in_log")]
    assert lines[1].cycles == [12]
    assert render_gate(lines).plain == (
        "The file says the run did not complete (state: aborted). "
        "The log records an abort at cycle 12."
    )


def test_lid_and_power_events(tmp_path):
    start = F.epoch_ms("2019-05-10T09:00:00")
    members = {
        "experiment.xml": F.experiment_xml(start_ms=start, end_ms=start + 6_000_000),
        "messages.log": F.messages_log(lid_open_at=31, power_at=35),
    }
    lines = g_instr(read_run_context(F.write_eds(tmp_path / "x.eds", members)))
    assert _codes(lines) == [
        ("pass", "run_complete"),
        ("warn", "interrupted"),
        ("warn", "power_event"),
    ]
    assert lines[1].cycles == [31, 32] and lines[2].cycles == [35]
    assert render_gate(lines).plain == (
        "Run completed. The lid was opened during cycles 31–32. "
        "The log records a power event at cycle 35."
    )


def test_hold_temperature_against_the_lab_limit(tmp_path):
    members = {
        "experiment.xml": F.experiment_xml(),
        "logs/temperature.log": F.temperature_log(drift_at_cycle=30, drift_c=0.9),
    }
    ctx = read_run_context(F.write_eds(tmp_path / "x.eds", members))
    off = g_instr(ctx)
    assert _codes(off)[-1] == ("warn", "hold_off_setpoint")
    assert render_gate(off).plain.endswith(
        "Sample temperature was up to 0.89 °C off its setpoint during a hold, beyond the lab's "
        "limit of 0.50 °C."
    )
    relaxed = g_instr(ctx, hold_limit_c=1.0)
    assert _codes(relaxed)[-1] == ("pass", "hold_on_setpoint")


def test_stepone_and_7500(tmp_path):
    stepone = g_instr(read_run_context(F.stepone(tmp_path / "stepone.eds")))
    assert _codes(stepone) == [("pass", "run_complete"), ("info", "calibration_date_not_in_file")]
    assert render_gate(stepone).plain == "Run completed. Calibration dates are not in the file."
    # the 7500 has calibration ages but no expiry and no log: nothing is said about either
    like_7500 = g_instr(read_run_context(F.like_7500(tmp_path / "7500.eds")))
    assert _codes(like_7500) == [("pass", "run_complete")]
    assert not needs_consequence(like_7500)


def test_exports_say_what_their_header_allows(tmp_path):
    qs5 = g_instr(read_run_context(F.quantstudio_csv(tmp_path / "qs5.csv")))
    assert _codes(qs5) == [("pass", "calibrations_in_date")]
    txt = g_instr(read_run_context(F.quantstudio_txt(tmp_path / "qs.txt")))
    assert _codes(txt) == [("info", "calibration_expired")]
    # the TXT file gives no expiry date, only the vendor's flag
    assert render_gate(txt).plain == (
        "Background calibration done 456 days before this run, past the vendor's expiry."
    )
    cfx = g_instr(read_run_context(F.cfx_run_information(tmp_path / "cfx.csv")))
    assert _codes(cfx) == [("not_applicable", "nothing_to_check")]


def test_nothing_in_file_is_not_applicable(tmp_path):
    runs = [{"id": "HMBS_20080318"}, {"id": "competimer_set"}]
    for ctx in run_contexts_from_rdml(F.write_rdml(tmp_path / "x.rdml", runs)):
        lines = g_instr(ctx)
        assert _codes(lines) == [("not_applicable", "nothing_in_file")]
        assert render_gate(lines).plain == (
            "The file says nothing about the instrument for this run."
        )
        assert not needs_consequence(lines)


def test_gate_lines_never_carry_local_facts_or_serials(tmp_path):
    serials = ("278880001", "BLK-1001", "HC-2001", "278990004", "CC000123", "785BR0001")
    for ctx in _all_fixture_contexts(tmp_path):
        lines = g_instr(ctx)
        for line in lines:
            assert all(not fact.path.startswith("local:") for fact in line.facts.values())
        text = render_gate(lines)
        for serial in serials:
            assert serial not in text.plain and serial not in text.html
        lowered = text.plain.lower()
        assert not [word for word in BANNED if word.lower() in lowered], text.plain


def test_every_code_has_wording_that_degrades_without_facts():
    assert set(SENTENCES) == set(CODES)
    for code, status in CODES.items():
        line = GateLine(status=status, code=code)
        tokens = line_tokens(line)
        assert tokens and not re.search(r"\d", tokens), (code, tokens)
        assert validate(tokens, {}).ok


def test_add_consequence_checks_its_counts(tmp_path):
    lines = g_instr(read_run_context(F.aborted(tmp_path / "aborted.eds")))
    with pytest.raises(ValueError):
        add_consequence(lines, n_changed=3, n_total=2)
    out = add_consequence(lines, n_changed=2, n_total=58, run_label="HMBS_20080318")
    assert out[:-1] == lines and out[-1].code == "consequence" and out[-1].status == "info"
    assert set(out[-1].facts) == {
        "f_instr_hmbs_20080318_excl_changed",
        "f_instr_hmbs_20080318_excl_total",
    }
    assert render_gate(out).plain.endswith("Excluding this run changes 2 of 58 conclusions.")


def test_gate_is_deterministic(tmp_path):
    ctx = read_run_context(F.qs_v1_expired(tmp_path / "qs.eds"))
    first = [line.model_dump_json() for line in g_instr(ctx)]
    assert first == [line.model_dump_json() for line in g_instr(ctx)]


@pytest.mark.demo_data
def test_demo_runs_are_not_applicable(demo_rdml_path):
    contexts = run_contexts_from_rdml(demo_rdml_path)
    assert {tuple(_codes(g_instr(ctx))) for ctx in contexts} == {
        (("not_applicable", "nothing_in_file"),)
    }
    whole = g_instr(read_run_context(demo_rdml_path))
    assert _codes(whole) == [("not_applicable", "nothing_in_file")]
