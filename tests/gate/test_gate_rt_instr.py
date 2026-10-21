"""G-RT and G-INSTR as rules of the Run Gate's pack (research-default 1.1.0).

origin/main's gate lines (``qpcr/gate_rt.py``: the RT-replicate Cq range per biological unit and
target; ``qpcr/gate_instr.py``: what a run file says about the run) are evaluated by the pack
like any rule: a verdict per unit x target and per plate, every number a cited ``f_gate_*``
fact, the pack's thresholds (``limit_cycles``, ``hold_limit_c``) and severity, and the
consequence test where they point at wells. Synthetic studies (``tests/engine/evidence_toys``)
and synthetic run files (``tests/engine/instrument_files``); no download.
"""

from __future__ import annotations

import pandas as pd
import pytest

from qpilot.core import gate as core_gate
from qpilot.core.rules import NOT_APPLICABLE, Rule, override
from qpilot.qpcr.gate_rt import rt_replicate_range
from qpilot.qpcr.gate_rules import (
    CHECKS,
    INSTR_OUTCOMES,
    GateContext,
    RunFile,
    evaluate,
    file_runs,
    instrument_run,
    resolve_pack,
    rt_replicate_spread,
    run_gate,
    stored_runs,
    with_linked,
)
from qpilot.qpcr.instrument_context import read_run_context, run_contexts_from_rdml
from qpilot.qpcr.quant import EXCLUDED
from qpilot.qpcr.study import StudySettings
from tests.engine import instrument_files as F
from tests.engine.evidence_toys import UNITS, sample_name, toy_design, toy_table
from tests.gate.wells import check_cited

PACK = resolve_pack()
G_RT = PACK.rule("G-RT")
G_INSTR = PACK.rule("G-INSTR")


def evals_of(rule: Rule, ctx: GateContext):
    """The rule's evaluations on ``ctx`` through the pack (severity applied), facts checked."""
    out = [ev for ev in evaluate(PACK, ctx) if ev.rule_id == rule.id]
    for ev in out:
        check_cited(ev, ctx.facts.as_dict())
    return out


def shifted(table: pd.DataFrame, target: str, unit: str, cycles: float) -> pd.DataFrame:
    """``table`` with RT replicate ``b`` of ``unit`` later by ``cycles`` for ``target``.

    In the toys RT replicate ``b`` amplifies ``rt_shift`` cycles before ``a``; ``cycles`` later
    on top of that gives a range of ``cycles - rt_shift`` (give or take the toys' noise).
    """
    out = table.copy()
    rows = (out["target"] == target) & (out["sample"] == sample_name(unit, "b"))
    out.loc[rows, "cq"] = out.loc[rows, "cq"] + cycles
    return out


# ---------- G-RT ----------


def test_the_pack_carries_both_rules_with_sources_and_thresholds():
    assert G_RT.check == "rt_replicate_spread" and G_RT.params == {"limit_cycles": 1.0}
    assert G_RT.sources == ["bustin_2015"]
    assert "to be checked against the paper" in PACK.sources["bustin_2015"].note
    assert G_INSTR.check == "instrument_run" and G_INSTR.params == {"hold_limit_c": 0.5}
    assert G_INSTR.sources == ["vendor_run_file", "lab_default"]
    assert set(G_INSTR.severity) == set(INSTR_OUTCOMES)
    assert G_RT.consequence_scope == ["exclude_unit_target", "drop_rt_replicate"]
    assert G_INSTR.consequence_scope == ["exclude_run"]
    for rule in (G_RT, G_INSTR):
        assert set(rule.consequence_scope) <= set(CHECKS[rule.check].options)


def test_rt_ranges_below_the_limit_pass_per_unit_and_target():
    table, design = toy_table(rt_shift=0.3), toy_design()
    evals = evals_of(G_RT, GateContext(table=table, design=design))
    assert len(evals) == len(UNITS) * table["target"].nunique()
    assert {ev.verdict for ev in evals} == {"pass"}
    assert all(set(ev.scope) == {"unit", "target"} and not ev.options for ev in evals)
    # the same ranges as the Evidence Ledger's G-RT line (nothing is left out here)
    ledger = rt_replicate_range(table, design).set_index(["unit", "target"])["range"]
    for ev in evals:
        key = (ev.scope["unit"], ev.scope["target"])
        assert ev.evidence["range"] == pytest.approx(ledger[key])


def test_a_range_at_the_limit_warns_and_points_at_the_units_wells():
    table = shifted(toy_table(rt_shift=0.3), "T1", "u2", 1.6)  # about 1.3 cycles apart
    ctx = GateContext(table=table, design=toy_design())
    (ev,) = (e for e in evals_of(G_RT, ctx) if e.verdict != "pass")
    assert ev.verdict == "warn" and ev.outcome == "rt_over_limit"
    assert ev.scope == {"unit": "u2", "target": "T1"}
    rows = ctx.table[(ctx.table["target"] == "T1") & ctx.table["sample"].str.startswith("u2")]
    assert ev.flagged == sorted(rows["key"])
    assert ev.options == {"exclude_unit_target": ev.flagged}  # two RT replicates: no outlier
    assert "At or above the limit" in ev.reason and ev.evidence["n_measured"] == 2


def test_with_three_rt_replicates_the_farthest_one_can_be_left_out(tmp_path):
    table = toy_table(rt_shift=0.2)
    extra = table[table["sample"] == sample_name("u1", "b")].copy()
    extra["sample"] = sample_name("u1", "c")
    extra["well"] = extra["well"] + "c"
    extra.loc[extra["target"] == "T2", "cq"] += 2.0
    design = toy_design()
    samples = dict(design.samples)
    samples["u1c"] = samples["u1b"].model_copy(update={"sample": "u1c", "rt_replicate": "c"})
    design = design.model_copy(update={"samples": samples})
    ctx = GateContext(table=pd.concat([table, extra], ignore_index=True), design=design)
    (ev,) = (e for e in evals_of(G_RT, ctx) if e.verdict == "warn")
    assert ev.scope == {"unit": "u1", "target": "T2"} and ev.evidence["farthest_rt"] == "c"
    far = ctx.table[(ctx.table["target"] == "T2") & (ctx.table["sample"] == "u1c")]
    assert ev.options["drop_rt_replicate"] == sorted(far["key"])
    assert len(ev.options["exclude_unit_target"]) == 3 * len(far)


@pytest.mark.parametrize(
    ("design", "code"),
    [
        (None, "rt_not_annotated"),
        (toy_design(rt_labels=False), "rt_not_annotated"),
    ],
)
def test_without_rt_labels_the_rule_is_not_applicable_once(design, code):
    (ev,) = evals_of(G_RT, GateContext(table=toy_table(), design=design))
    assert (ev.verdict, ev.code, ev.scope) == (NOT_APPLICABLE, code, {})
    assert "rt_replicate column" in ev.reason


def test_labels_with_one_rt_per_unit_are_not_measurable():
    design = toy_design()
    samples = {
        name: (d.model_copy(update={"biological_unit": name}) if d.rt_replicate else d)
        for name, d in design.samples.items()
    }
    ctx = GateContext(table=toy_table(), design=design.model_copy(update={"samples": samples}))
    (ev,) = evals_of(G_RT, ctx)
    assert (ev.verdict, ev.code) == (NOT_APPLICABLE, "rt_not_measurable")


def test_wells_a_person_left_out_still_count_so_the_option_says_so():
    """The gate labels every well; leaving them out does not hide the check (unlike the ledger)."""
    table = shifted(toy_table(rt_shift=0.3), "T1", "u2", 1.6)
    ctx = GateContext(table=table, design=toy_design())
    (before,) = (e for e in evals_of(G_RT, ctx) if e.verdict == "warn")
    left = table.copy()
    left[EXCLUDED] = (left["run_id"] + "/" + left["well"]).isin(before.flagged)
    (after,) = (
        e
        for e in evals_of(G_RT, GateContext(table=left, design=toy_design()))
        if e.verdict == "warn"
    )
    assert after.flagged == before.flagged
    # the Evidence Ledger's ranges leave those wells out: that unit x target is gone there
    ledger = rt_replicate_range(left, toy_design())
    assert not ((ledger["unit"] == "u2") & (ledger["target"] == "T1")).any()


def test_the_limit_is_the_packs_and_a_lab_can_change_it():
    table = toy_table(rt_shift=0.3)
    strict = override(PACK, "1.1.0-lab.1", params={"G-RT": {"limit_cycles": 0.1}}).rule("G-RT")
    ctx = GateContext(table=table, design=toy_design())
    findings = list(rt_replicate_spread(strict, ctx))
    assert {f.outcome for f in findings} == {"rt_over_limit"}
    assert all(ctx.facts.as_dict()[f.facts[2]].value == 0.1 for f in findings)
    with pytest.raises(ValueError, match="limit_cycles"):
        bad = override(PACK, "1.1.0-lab.2", params={"G-RT": {"limit_cycles": 0}}).rule("G-RT")
        list(rt_replicate_spread(bad, ctx))


def test_leaving_a_units_wells_out_is_priced_by_the_consequence_test():
    table = shifted(toy_table(rt_shift=0.3), "T1", "u2", 1.6)
    settings = StudySettings.from_design(toy_design())
    report = run_gate(table, settings)
    (c,) = (c for c in report.consequences if c.rule_id == "G-RT")
    assert c.scope == {"unit": "u2", "target": "T1"}
    (option,) = c.options
    assert option.option == "exclude_unit_target" and option.consequence in core_gate._RANK
    assert option.excluded == sorted(
        f"{r}/{w}"
        for r, w, s, t in table[["run_id", "well", "sample", "target"]].itertuples(index=False)
        if t == "T1" and s.startswith("u2")
    )


# ---------- G-INSTR ----------


def plate_table(plates=("P1", "P2")) -> pd.DataFrame:
    """Two plates of study wells and one control each (the G-INSTR rule reads plates only)."""
    rows = []
    for plate in plates:
        for i, kind in enumerate(("unkn", "unkn", "ntc")):
            rows.append({"run_id": plate, "well": f"A{i + 1}", "sample": f"s{i}",
                         "sample_type": kind, "target": "T", "cq": 25.0 if kind == "unkn" else None,
                         "amplification": kind == "unkn"})  # fmt: skip
    return pd.DataFrame(rows)


def linked(path) -> RunFile:
    return RunFile(context=read_run_context(path), linked=True)


def test_a_paused_run_with_an_expired_calibration_warns_and_points_at_the_runs_wells(tmp_path):
    run = linked(F.qs_v1_expired(tmp_path / "qs.eds", pause_at=23))
    ctx = GateContext(table=plate_table(), runs={"P1": run})
    p1, p2 = evals_of(G_INSTR, ctx)
    assert p1.scope == {"plate": "P1"} and p1.verdict == "warn"
    assert p1.outcome == "interrupted"  # the first line with the worst verdict
    assert core_gate_plain(p1, ctx) == (
        "From the run file a person linked to this plate: Run completed. The run was paused "
        "during cycles 23–24. Background calibration done 412 days before this run, past the "
        "vendor's 180-day expiry. Hold temperatures stayed within 0.50 °C of the setpoint."
    )
    assert p1.flagged == ["P1/A1", "P1/A2"] and p1.options == {"exclude_run": p1.flagged}
    assert p1.evidence["cycles"] == "23,24" and p1.evidence["source"] == "linked run file"
    # no run context for P2: not applicable, with what to do
    assert (p2.verdict, p2.code) == (NOT_APPLICABLE, "no_run_file")
    assert "link the run file" in p2.reason


def core_gate_plain(ev, ctx) -> str:
    """The reason with every cited fact shown as the page shows it."""
    from qpilot.core.validator import render_tokens

    return render_tokens(ev.reason, ctx.facts.as_dict())


def test_serial_numbers_and_names_never_reach_the_rule(tmp_path):
    run = linked(F.qs_v1_expired(tmp_path / "qs.eds", block_serial="BLK-9876"))
    ctx = GateContext(table=plate_table(("P1",)), runs={"P1": run})
    (ev,) = evals_of(G_INSTR, ctx)
    text = core_gate_plain(ev, ctx) + repr(ev.evidence)
    values = " ".join(str(f.value) for f in ctx.facts.as_dict().values())
    for secret in ("BLK-9876", "278880001", "HC-2001", F.OPERATOR):
        assert secret not in text and secret not in values


def test_the_severity_map_is_the_packs(tmp_path):
    run = linked(F.qs_v1_expired(tmp_path / "qs.eds", pause_at=None))  # only the calibration
    ctx = GateContext(table=plate_table(("P1",)), runs={"P1": run})
    (ev,) = evals_of(G_INSTR, ctx)
    assert (ev.verdict, ev.outcome) == ("warn", "calibration_expired")
    lab = override(PACK, "1.1.0-lab.1", severity={"G-INSTR": {"calibration_expired": "pass"}})
    (calm,) = (e for e in evaluate(lab, GateContext(table=plate_table(("P1",)), runs={"P1": run}))
               if e.rule_id == "G-INSTR")  # fmt: skip
    assert calm.verdict == "pass" and calm.flagged == [] and calm.options == {}
    assert "past the vendor's" in calm.reason  # the fact is still said


def test_an_aborted_run_warns(tmp_path):
    ctx = GateContext(
        table=plate_table(("P1",)), runs={"P1": linked(F.aborted(tmp_path / "a.eds"))}
    )
    (ev,) = evals_of(G_INSTR, ctx)
    assert ev.verdict == "warn" and ev.outcome == "run_not_complete"
    assert "did not complete" in ev.reason


def test_a_clean_run_passes_and_points_at_nothing(tmp_path):
    ctx = GateContext(
        table=plate_table(("P1",)), runs={"P1": linked(F.eds2_json(tmp_path / "e.eds"))}
    )
    (ev,) = evals_of(G_INSTR, ctx)
    assert ev.verdict == "pass" and ev.flagged == [] and ev.options == {}


def test_the_studys_rdml_names_little_and_says_how_to_check_more(tmp_path):
    rdml = F.write_rdml(
        tmp_path / "runs.rdml",
        [
            {"id": "P1", "instrument": F.BIORAD_INSTRUMENT, "runDate": "2014-02-24T13:39:29"},
            {"id": "P2", "instrument": None},
        ],
    )
    runs = file_runs(rdml)
    assert set(runs) == {"P1", "P2"} and not any(r.linked for r in runs.values())
    p1, p2 = evals_of(G_INSTR, GateContext(table=plate_table(), runs=runs))
    assert (p1.verdict, p1.code) == (NOT_APPLICABLE, "nothing_to_check")
    assert (p2.verdict, p2.code) == (NOT_APPLICABLE, "nothing_in_file")
    assert p2.reason.startswith("The study's file says nothing about the instrument")
    assert all("RDML has no field" in ev.reason for ev in (p1, p2))
    assert "CC000123" not in p1.reason + p2.reason  # the cycler's serial stays local


def test_stored_run_contexts_read_back_and_a_linked_file_takes_a_plates_place(tmp_path):
    rdml = F.write_rdml(tmp_path / "runs.rdml", [{"id": "P1", "runDate": "2019-05-11T08:00:00"}])
    data = {"runs": [c.model_view() for c in run_contexts_from_rdml(rdml)]}
    own = stored_runs(data)
    assert set(own) == {"P1"} and own["P1"].context.run["date"] == "2019-05-11"
    assert stored_runs({"runs": [{"source_file": 3}]}) is None and stored_runs({}) is None
    eds = read_run_context(F.qs_v1_expired(tmp_path / "qs.eds"))
    runs = with_linked(own, {"P1": eds})
    assert runs["P1"].linked and runs["P1"].study_date == "2019-05-11"
    ctx = GateContext(table=plate_table(("P1",)), runs=runs)
    (ev,) = evals_of(G_INSTR, ctx)
    shown = core_gate_plain(ev, ctx)
    assert "The linked file's run date (2019-05-10) is not this plate's date in the study's " \
        "file (2019-05-11)" in shown  # fmt: skip


def test_the_hold_limit_is_the_packs(tmp_path):
    """The fixture's holds drift by up to 0.1 °C: within the shipped 0.5, beyond a lab's 0.05."""
    run = linked(F.qs_v1_expired(tmp_path / "qs.eds", pause_at=None))
    assert run.context.temperature["max_hold_deviation_c"] == pytest.approx(0.1)
    tight = override(PACK, "1.1.0-lab.1", params={"G-INSTR": {"hold_limit_c": 0.05}})
    ctx = GateContext(table=plate_table(("P1",)), runs={"P1": run})
    (finding,) = instrument_run(tight.rule("G-INSTR"), ctx)
    shown = core_gate_plain(finding, ctx)
    assert "Sample temperature was up to 0.10 °C off its setpoint during a hold, beyond the " \
        "lab's limit of 0.05 °C." in shown  # fmt: skip
    assert finding.outcome == "calibration_expired"  # both warn; the first worst line names it


def test_without_run_contexts_every_plate_is_not_applicable():
    evals = evals_of(G_INSTR, GateContext(table=plate_table()))
    assert [(e.scope["plate"], e.code) for e in evals] == [
        ("P1", "no_run_file"),
        ("P2", "no_run_file"),
    ]


def test_leaving_a_paused_run_out_is_priced_by_the_consequence_test(tmp_path):
    table = toy_table()
    settings = StudySettings.from_design(toy_design())
    t1 = str(table.loc[table["target"] == "T1", "run_id"].iloc[0])
    run = linked(F.qs_v1_expired(tmp_path / "qs.eds", pause_at=23))
    report = run_gate(table, settings, runs={t1: run})
    (c,) = (c for c in report.consequences if c.rule_id == "G-INSTR")
    assert c.scope == {"plate": t1} and c.verdict == "warn"
    (option,) = c.options
    study = table[(table["run_id"] == t1) & (table["sample_type"] == "unkn")]
    assert option.excluded == sorted(study["run_id"] + "/" + study["well"])
    # the plate holds the only T1 wells: without it T1 cannot be called, so the call changes
    assert option.consequence == "flip" and "T1" in option.flipped
    assert c.triage == "human" and c.card_id is not None
    card = next(card for card in report.cards if card.id == c.card_id)
    assert card.status == "open" and card.evidence["rule_id"] == "G-INSTR"
