"""G-IPC and the Run Gate in multiplex wells (research-default 1.3.0).

On the QuantStudio 7 Pro eDNA plate (brook trout BRK2 + an internal positive control in every
well) the IPC of sample M22 comes up about 3.5 to 4.2 cycles later than in the no-template
wells: the reaction may have been inhibited, so its late BRK2 may be an underestimate. The rule
says so per plate and control, never judges the IPC as no-template contamination (it is meant to
amplify there), and a card follows only through the consequence test.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from qpilot.qpcr.curves import analyse_study
from qpilot.qpcr.gate_rules import (
    MULTIPLEX_OPTION_NOTE,
    GateContext,
    evaluate,
    ipc_inhibition,
    resolve_pack,
)

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"
QS7 = CORPUS / "rdml" / "quantstudio7pro-rdml-1.2-edna"
QS7_PLATE = QS7 / "SupplementaryMaterials2_qPCR_Plate1.rdml"
QS7_STD = QS7 / "SupplementaryMaterials2_qPCR_ConcentrationStandardCurve.rdml"
LC96 = CORPUS / "rdml" / "lightcycler96-rdml-1.1" / "lc96_bACTXY.rdml"


def rule(rule_id: str = "G-IPC"):
    return next(r for r in resolve_pack().rules if r.id == rule_id)


def evals(path: Path, experiment: str) -> tuple[list, GateContext]:
    ctx = GateContext(table=analyse_study(path, experiment, ()))
    return evaluate(resolve_pack(), ctx), ctx


def text(ev, ctx: GateContext) -> str:
    facts = ctx.facts.as_dict()
    out = ev.reason
    for fid in ev.facts:
        fact = facts[fid]
        out = out.replace("{{" + fid + "}}", fact.fmt.format(fact.value))
    return out


def test_the_qs7_edna_plate_flags_the_sample_whose_ipc_is_late():
    found, ctx = evals(QS7_PLATE, "Experiment 1")
    (ipc,) = [ev for ev in found if ev.rule_id == "G-IPC"]
    assert ipc.scope == {"plate": "Run 1", "target": "IPC"}
    assert ipc.outcome == "ipc_delayed" and ipc.verdict == "warn"
    assert ipc.flagged == ["Run 1/E9", "Run 1/F9", "Run 1/G9", "Run 1/H9"]
    assert ipc.options == {"exclude_inhibited": ipc.flagged}
    assert ipc.evidence["samples"] == "M22" and ipc.evidence["basis"] == "no_template"
    assert ipc.evidence["expected_cq"] == pytest.approx(27.7257, abs=1e-4)
    assert ipc.evidence["max_delay"] == pytest.approx(4.1601, abs=1e-4)
    assert ipc.evidence["n_study_wells"] == 88 and ipc.evidence["n_failed"] == 0
    words = text(ipc, ctx)
    assert "its median over the 5 no-template wells where it amplified" in words
    assert "In 4 of the 88 study wells it came up 3 or more cycles later" in words
    assert "(inhibition)" in words and MULTIPLEX_OPTION_NOTE in words
    # the IPC amplifies in the no-template wells on purpose: G-NTC-1 does not judge it
    ntc = {ev.scope["target"]: ev for ev in found if ev.rule_id == "G-NTC-1"}
    assert ntc["IPC"].verdict == "not_applicable" and ntc["IPC"].code == "internal_control"
    assert ntc["BRK2"].outcome == "clean"


def test_without_no_template_wells_the_plates_own_ipc_median_is_the_reference():
    found, ctx = evals(LC96, "ca1eb225-ecea-4793-9804-87bfbb45f81d")
    (ipc,) = [ev for ev in found if ev.rule_id == "G-IPC"]
    assert ipc.outcome == "ipc_ok" and ipc.verdict == "pass"
    assert ipc.evidence["basis"] == "study" and ipc.evidence["n_study_wells"] == 6
    assert "too few no-template wells had it" in text(ipc, ctx)


def test_a_plate_of_standards_has_no_study_wells_to_check():
    found, _ = evals(QS7_STD, "Experiment 1")
    (ipc,) = [ev for ev in found if ev.rule_id == "G-IPC"]
    assert ipc.verdict == "not_applicable" and ipc.code == "no_unknowns"


# ---------- small tables: the outcomes one by one ----------


def well(well: str, target: str, cq: float | None, sample: str = "S", kind: str = "unkn") -> dict:
    return {
        "run_id": "P",
        "well": well,
        "sample": sample,
        "sample_type": kind,
        "target": target,
        "target_raw": target,
        "cq": cq,
        "amplification": cq is not None,
        "eff_target": 1.95,
        "note": "",
    }


def plate(*extra: dict) -> pd.DataFrame:
    rows = [well(f"H{i}", "IPC", 28.0 + 0.1 * i, "NTC", "ntc") for i in (1, 2, 3)]
    for i in range(1, 6):
        rows += [well(f"A{i}", "GOI", 25.0, f"S{i}"), well(f"A{i}", "IPC", 28.2, f"S{i}")]
    return pd.DataFrame([*rows, *extra])


def outcome(table: pd.DataFrame):
    (finding,) = list(ipc_inhibition(rule(), GateContext(table=table)))
    return finding


def test_every_ipc_on_time_passes():
    found = outcome(plate())
    assert found.outcome == "ipc_ok" and not found.flagged
    assert found.evidence["expected_cq"] == pytest.approx(28.2)


def test_a_late_ipc_is_flagged_and_its_whole_well_is_the_option():
    found = outcome(plate(well("B1", "GOI", 33.0, "T"), well("B1", "IPC", 31.5, "T")))
    assert found.outcome == "ipc_delayed"
    assert found.flagged == ["P/B1"] and found.options == {"exclude_inhibited": ["P/B1"]}
    assert found.evidence["max_delay"] == pytest.approx(3.3)


def test_an_ipc_that_failed_beside_a_negative_target_is_flagged():
    found = outcome(plate(well("B1", "GOI", None, "T"), well("B1", "IPC", None, "T")))
    assert found.outcome == "ipc_failed" and found.flagged == ["P/B1"]
    assert found.evidence["n_failed"] == 1


def test_an_ipc_outcompeted_by_a_strong_target_is_not_inhibition():
    found = outcome(plate(well("B1", "GOI", 18.0, "T"), well("B1", "IPC", None, "T")))
    assert found.outcome == "ipc_ok" and not found.flagged
    assert found.evidence["n_outcompeted"] == 1


def test_an_ipc_in_wells_of_its_own_is_not_an_internal_control():
    table = plate()
    table.loc[table["target"] == "GOI", "well"] = [f"C{i}" for i in range(1, 6)]
    (finding,) = list(ipc_inhibition(rule(), GateContext(table=table)))
    assert finding.outcome == "not_applicable" and finding.code == "no_internal_control"


def test_a_replicate_option_in_a_multiplex_well_says_every_curve_goes_with_it():
    rows = []
    for i, cq in enumerate((20.0, 20.1, 23.0), start=1):
        rows += [well(f"A{i}", "GOI", cq), well(f"A{i}", "REF", 18.0)]
    rows += [well("H1", "GOI", None, "NTC", "ntc"), well("H1", "REF", None, "NTC", "ntc")]
    ctx = GateContext(table=pd.DataFrame(rows))
    found = evaluate(resolve_pack(), ctx)
    rep_of = {
        ev.scope["target"]: ev for ev in found if ev.rule_id == "G-REP" and "sample" in ev.scope
    }
    rep = rep_of["GOI"]
    assert rep.outcome == "outside" and rep.options["drop_outlier_well"] == ["P/A3"]
    assert rep.reason.endswith(MULTIPLEX_OPTION_NOTE)
    assert MULTIPLEX_OPTION_NOTE not in rep_of["REF"].reason  # no option, no note
