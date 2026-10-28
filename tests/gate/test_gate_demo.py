"""Run Gate on the demo study, checked against the scientist's independent re-measurement.

``validation/scientist/gate_acceptance.py`` recomputes G-STD and G-NTC-1 per plate without any
Gate code (``out/gate_plates.csv``) and G-REP's tolerance on ``380_replicates_set``
(``out/grep_ds380.csv``). Column meanings (from that script): ``g_std`` / ``g_ntc`` the verdicts;
``slope``, ``E``, ``E_lo``, ``E_hi``, ``R2`` the OLS fit of Cq on log10(copies) over amplified
standards (copies from the sample name); ``E_perwell_std`` the mean LinRegPCR per-well E of the
same wells; ``ntc_n``, ``ntc_amp``, ``ntc_min_cq`` the plate's NTCs, how many have a Cq and the
earliest; ``tainted`` the unknowns with a Cq less than five cycles before it. The CSV keeps six
significant digits.

One definition differs on purpose: the oracle counts a well with a Cq as amplified, the Gate
uses the engine's primary call (``amplification`` and a Cq, scientist spec §0). The test counts
the wells where the two differ and expects exactly that difference.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qpilot.core.decisions import needs_human
from qpilot.core.rules import summarise
from qpilot.qpcr.gate_rules import (
    GateContext,
    gate_file,
    range_quantile,
    replicate_spread,
    resolve_pack,
)
from tests.gate.wells import check_cited, replicates, table

pytestmark = pytest.mark.demo_data

ORACLE = Path(__file__).resolve().parents[2] / "validation" / "scientist" / "out"
SIG = 2e-5  # six significant digits in the CSV


@pytest.fixture(scope="module")
def demo():
    from qpilot.io.datasets import default_cache_dir
    from qpilot.qpcr.curves import analyse_study

    rdml = default_cache_dir() / "data_vermeulen_raw.rdml"
    if not rdml.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    return gate_file(rdml), analyse_study(rdml)


@pytest.fixture(scope="module")
def oracle() -> pd.DataFrame:
    return pd.read_csv(ORACLE / "gate_plates.csv").set_index("run_id")


def by_plate(report, rule_id):
    return {ev.scope["plate"]: ev for ev in report.evals if ev.rule_id == rule_id}


def test_every_plate_is_gated_and_every_number_is_a_cited_fact(demo):
    report, _ = demo
    assert len(report.units) == 64 and set(report.units.values()) == {"gated"}
    assert report.pack["pack"] == "research-default" and report.pack["hash"] == resolve_pack().hash
    for ev in report.evals:
        check_cited(ev, report.facts)
    na = Counter((ev.rule_id, ev.code) for ev in report.evals if ev.verdict == "not_applicable")
    assert na[("G-NAC", "no_nac_typed")] == 64
    assert na[("G-NRT", "no_nrt_typed")] == 64
    assert na[("G-POS", "no_pos_typed")] == 64


def test_the_standard_curves_equal_the_independent_fit(demo, oracle):
    report, _ = demo
    std = by_plate(report, "G-STD")
    assert set(std) == set(oracle.index)
    assert Counter(ev.verdict for ev in std.values()) == {"pass": 57, "fail": 7}
    for plate, ev in std.items():
        row = oracle.loc[plate]
        assert ev.verdict == row.g_std, plate
        e = ev.evidence
        assert e["slope"] == pytest.approx(row.slope, rel=SIG), plate
        assert e["efficiency"] == pytest.approx(row.E, rel=SIG), plate
        assert e["e_low"] == pytest.approx(row.E_lo, rel=SIG), plate
        assert e["e_high"] == pytest.approx(row.E_hi, rel=SIG), plate
        assert e["r2"] == pytest.approx(row.R2, rel=SIG), plate
        assert e["eff_per_well_mean"] == pytest.approx(row.E_perwell_std, rel=SIG), plate
        assert e["levels"] == row.levels and e["n_wells"] == row.std_wells
    fails = sorted(p.split("_")[0] for p, ev in std.items() if ev.verdict == "fail")
    assert fails == ["ALUsq(Eurogentec)", "CAMTA1", "CDKN3", "MCM2", "NTRK1", "PMP22", "TYMS"]
    alu = next(ev for p, ev in std.items() if p.startswith("ALUsq"))
    assert alu.evidence["r2_low"] and alu.evidence["efficiency_out"]
    gap = np.median(
        [ev.evidence["efficiency"] - ev.evidence["eff_per_well_mean"] for ev in std.values()]
    )
    assert gap == pytest.approx(0.030, abs=0.002)  # the curve's E above the per-curve E


def _no_call_with_cq(curves: pd.DataFrame, plate: str, cq_ntc: float) -> int:
    """Unknown wells with a Cq inside the window that the engine does not call amplified."""
    rows = curves[(curves.run_id == plate) & (curves.sample_type == "unkn")]
    odd = rows[rows.cq.notna() & ~rows.amplification]
    return int(((cq_ntc - odd.cq) < 5).sum())


def test_no_template_controls_equal_the_independent_count(demo, oracle):
    report, curves = demo
    ntc = by_plate(report, "G-NTC-1")
    assert Counter(ev.verdict for ev in ntc.values()) == {"pass": 53, "warn": 4, "fail": 7}
    n_amp = n_ntc = tainted = 0
    for plate, ev in ntc.items():
        row = oracle.loc[plate]
        assert ev.verdict == row.g_ntc, plate
        assert ev.evidence["n_ntc"] == row.ntc_n
        assert ev.evidence["n_ntc_amplified"] == row.ntc_amp, plate
        n_amp += ev.evidence["n_ntc_amplified"]
        n_ntc += ev.evidence["n_ntc"]
        if row.ntc_amp:
            assert ev.evidence["cq_ntc"] == pytest.approx(row.ntc_min_cq, rel=SIG)
            expected = int(row.tainted) - _no_call_with_cq(curves, plate, row.ntc_min_cq)
            assert ev.evidence.get("n_tainted", 0) == expected, plate
            assert len(ev.flagged) == expected
            tainted += expected
    assert (n_amp, n_ntc) == (23, 192)  # scientist spec §2: 23 of 192 NTC wells amplify
    # 21 by the oracle's Cq-only reading; MAP2K4 F24 has a Cq but no amplification call
    assert int(oracle.tainted.sum()) == 21 and tainted == 20
    warn = sorted(p.split("_")[0] for p, ev in ntc.items() if ev.verdict == "warn")
    assert warn == ["CAMTA1", "FYN", "GNB1", "NM23A"]


def test_the_replicate_tolerance_equals_the_independent_one():
    """G-REP's tolerance on groups like ds_380's (E 1.853, Cq ≈ 19, copies unknown)."""
    oracle = pd.read_csv(ORACLE / "grep_ds380.csv")
    rule = resolve_pack().rule("G-REP")
    for row in oracle.itertuples():
        n = int(row.n)
        rows = [{"run_id": "P", "well": "N1", "sample": "NTC", "sample_type": "ntc",
                 "target": "T", "note": "", "eff_indiv": row.E, "eff_target": row.E,
                 "cq": float("nan"), "amplification": False}]  # fmt: skip
        rows += replicates("P", "T", "S", [19.0 + 0.01 * i for i in range(n)], eff=row.E)
        ctx = GateContext(table=table(rows))
        (finding,) = list(replicate_spread(rule, ctx))
        assert finding.evidence["tolerance"] == pytest.approx(row.tol_cycles, rel=SIG)
        assert range_quantile(n) * 0.15 / np.log(row.E) == pytest.approx(row.tol_cycles, rel=SIG)
        assert row.false_flag_rate <= 0.05  # the acceptance the tolerance was chosen for


def test_the_consequence_test_on_the_demo(demo):
    """No control finding changes a call at the planned analysis; three change one elsewhere."""
    report, _ = demo
    # the rules of research-default 1.0.0 give the same verdicts as before G-RT, G-INSTR, G-MELT
    old = [ev for ev in report.evals if ev.rule_id not in ("G-RT", "G-INSTR", "G-MELT")]
    assert summarise(old) == {"pass": 491, "warn": 8, "fail": 14, "not_applicable": 192}
    # the demo annotates no RT replicates, its RDML says nothing about the runs, and the file
    # holds no melt curves
    new = Counter((ev.rule_id, ev.verdict, ev.code) for ev in report.evals if ev not in old)
    assert new == {
        ("G-RT", "not_applicable", "rt_not_annotated"): 1,
        ("G-INSTR", "not_applicable", "nothing_in_file"): 64,
        ("G-MELT", "not_applicable", "no_melt_data"): 1,
    }
    assert report.counts == {"pass": 491, "warn": 8, "fail": 14, "not_applicable": 258}
    assert len(report.consequences) == 10
    assert all(o.n_flipped == 0 for c in report.consequences for o in c.options)
    assert report.triage == {"ignore": 10, "rescue": 0, "human": 0, "defer": 0}
    assert len(report.cards) == 3
    for card in report.cards:
        assert card.kind == "gate.rule" and card.status == "auto_decided"
        assert card.decision == "keep" and needs_human(card)
        assert card.impact["n_genes_flipped_anywhere"] >= 1
    keys = {ev.key for ev in report.evals}  # every consequence names its evaluation
    assert all(c.eval_key in keys for c in report.consequences)
    # standards are not study samples: leaving them out changes nothing, said in words
    rep = [c for c in report.consequences if c.rule_id == "G-REP"]
    assert rep and all(o.reason and o.consequence == "none" for c in rep for o in c.options)
