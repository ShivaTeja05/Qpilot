"""The qPCR evaluators of the shipped pack on small hand-built plates.

Each test writes out the wells, runs the pack's evaluators (``gate_rules.evaluate``, so the
pack's severity map turns outcomes into verdicts) and checks the verdict, the machine reason of
a ``not_applicable``, the flagged wells and options, and that every number shown is a registered
fact cited in the reason (``wells.check_cited``).
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats

from qpilot.core import gate as core_gate
from qpilot.core.rules import RuleEval
from qpilot.qpcr.gate_rules import (
    GateContext,
    evaluate,
    plate_status,
    range_quantile,
    resolve_pack,
)
from tests.gate.wells import check_cited, rendered, replicates, table, well

PACK = resolve_pack()


def run(rows, rule_id: str | None = None, **ctx_args) -> tuple[list[RuleEval], GateContext]:
    """Every evaluation of the shipped pack (or of one rule) on these wells, and the context."""
    ctx = GateContext(table=table(rows), **ctx_args)
    evals = evaluate(PACK, ctx)
    facts = ctx.facts.as_dict()
    for ev in evals:
        check_cited(ev, facts)
    if rule_id is not None:
        evals = [ev for ev in evals if ev.rule_id == rule_id]
    return evals, ctx


def only(evals: list[RuleEval], **scope: str) -> RuleEval:
    hits = [ev for ev in evals if all(ev.scope.get(k) == v for k, v in scope.items())]
    assert len(hits) == 1, [(ev.scope, ev.verdict) for ev in evals]
    return hits[0]


def value(ctx: GateContext, ev: RuleEval, name: str):
    """The value of the evaluation's fact called ``name`` (``f_gate_<name>_…``)."""
    (fid,) = (f for f in ev.facts if f.startswith(f"f_gate_{name}_"))
    return ctx.facts.get(fid).value


def ntc_plate(ntc_cqs, unknown_cqs, target="T", plate="P1", kind="ntc", eff=1.9):
    rows = [
        well(plate, f"N{i + 1}", target, "NTC", kind, cq, eff=eff) for i, cq in enumerate(ntc_cqs)
    ]
    rows += [
        well(plate, f"U{i + 1}", target, f"S{i + 1}", "unkn", cq, eff=eff)
        for i, cq in enumerate(unknown_cqs)
    ]
    return rows


# ---------- G-TYPED ----------


def test_typed_controls_gate_a_plate_and_untyped_plates_are_ungated_loudly():
    rows = ntc_plate([None], [25.0], plate="P1")
    rows += [well("P2", "A1", "T", "S9", "unkn", 24.0), well("P2", "A2", "T", "S9", "unkn", 24.1)]
    rows += [well("P3", "A1", "T", "S8", "unkn", 24.0)]
    evals, ctx = run(rows, confirmed_no_controls={"P3"})
    typed = [ev for ev in evals if ev.rule_id == "G-TYPED"]
    assert [(ev.scope["plate"], ev.verdict) for ev in typed] == [
        ("P1", "pass"),
        ("P2", "fail"),
        ("P3", "warn"),
    ]
    assert value(ctx, typed[0], "ncontrol") == 1
    assert "ungated" in typed[1].reason and "Type the controls" in typed[1].reason
    assert plate_status(evals) == {"P1": "gated", "P2": "ungated", "P3": "ungated"}
    # every control rule on an untyped plate says so (never a pass)
    for rule_id in ("G-NTC-1", "G-NAC", "G-NRT", "G-POS", "G-STD"):
        ev = only([e for e in evals if e.rule_id == rule_id], plate="P2")
        assert (ev.verdict, ev.code) == ("not_applicable", "untyped_plate")
    # replicates of study samples are checked on an untyped plate too
    assert only([e for e in evals if e.rule_id == "G-REP"], plate="P2").verdict == "pass"


# ---------- G-NTC-1 ----------


def test_no_template_control_not_typed_or_nothing_to_compare_is_not_applicable():
    rows = [well("P1", "A1", "T", "S1", "unkn", 25.0), well("P1", "A2", "T", "STD", "std", 20.0)]
    (ev,), _ = run(rows, "G-NTC-1")
    assert (ev.verdict, ev.code) == ("not_applicable", "no_ntc_typed")
    rows = [well("P1", "A1", "T", "NTC", "ntc", None), well("P1", "A2", "T", "STD", "std", 20.0)]
    (ev,), _ = run(rows, "G-NTC-1")
    assert (ev.verdict, ev.code) == ("not_applicable", "no_unknowns")


def test_no_template_wells_that_never_amplified_pass():
    (ev,), ctx = run(ntc_plate([None, None, None], [25.0, 26.0]), "G-NTC-1")
    assert ev.verdict == "pass" and ev.outcome == "clean"
    assert value(ctx, ev, "nntc") == 3 and value(ctx, ev, "nntcamp") == 0
    assert not ev.flagged and not ev.options


def test_the_engine_call_wins_over_a_cq_without_amplification():
    """A control with a Cq but no amplification call (LinRegPCR) did not amplify."""
    rows = ntc_plate([None, None], [25.0])
    rows.append(well("P1", "N9", "T", "NTC", "ntc", 33.0, amplified=False))
    (ev,), _ = run(rows, "G-NTC-1")
    assert ev.verdict == "pass"


def test_worked_check_a_late_control_far_from_the_samples_warns_and_flags_nothing():
    """Scientist spec §3: NTC at 36.4, lowest unknown 27.1 → gap 9.3 ≥ 5 → warn, scope empty."""
    (ev,), ctx = run(ntc_plate([36.4, None], [27.1, 28.0, 29.5]), "G-NTC-1")
    assert (ev.verdict, ev.outcome) == ("warn", "amplified_clear")
    assert value(ctx, ev, "gap") == pytest.approx(9.3)
    assert value(ctx, ev, "cqntc") == pytest.approx(36.4)
    assert value(ctx, ev, "k") == 5
    assert ev.flagged == [] and ev.options == {}
    # nothing to leave out: the consequence test has nothing to re-run, it is logged as it is
    assert core_gate.run_consequences([ev], None, lambda keys: pytest.fail("re-run")) == []


def test_samples_within_k_cycles_of_the_control_are_tainted_and_offered_for_exclusion():
    (ev,), ctx = run(ntc_plate([30.0, 34.0, None], [20.0, 27.0, 26.0], eff=1.9), "G-NTC-1")
    assert (ev.verdict, ev.outcome) == ("fail", "tainted")
    assert ev.flagged == ["P1/U2", "P1/U3"] and ev.options == {"exclude_flagged": ev.flagged}
    assert value(ctx, ev, "ntainted") == 2
    # the share of a tainted sample's signal the control's level could be: E^-(Cq_ntc - Cq)
    assert value(ctx, ev, "contamfrac") == pytest.approx(round(1.9**-3.0, 6))
    assert "could be up to" in rendered(ev.reason, ctx.facts.as_dict())
    assert ev.evidence["chemistry_class"] == "unclassified"


def test_a_sample_no_earlier_than_the_control_could_owe_it_all_its_signal():
    (ev,), ctx = run(ntc_plate([30.0], [31.0, 20.0]), "G-NTC-1")
    assert ev.verdict == "fail" and ev.flagged == ["P1/U1"]
    assert value(ctx, ev, "nlate") == 1
    assert ev.evidence["max_contaminant_fraction"] == 1.0  # a share is never above all of it
    assert "whole signal" in ev.reason and "study well amplified" in ev.reason


def test_a_no_target_control_applies_only_to_its_own_target():
    rows = ntc_plate([22.0], [24.0], target="A", kind="ntp")
    rows += ntc_plate([], [24.0], target="B")
    rows.append(well("P1", "N9", "B", "water", "ntc", None))
    evals, _ = run(rows, "G-NTC-1")
    assert only(evals, target="A").verdict == "fail"
    assert only(evals, target="B").verdict == "pass"


# ---------- G-NAC ----------


def test_amplification_in_a_no_amplification_control_flags_the_targets_study_wells():
    rows = ntc_plate([None], [25.0, 26.0])
    rows.append(well("P1", "X1", "T", "NAC", "nac", 31.0))
    (ev,), ctx = run(rows, "G-NAC")
    assert ev.verdict == "fail" and ev.flagged == ["P1/X1"]
    assert ev.options == {"exclude_target_plate": ["P1/U1", "P1/U2"]}
    assert value(ctx, ev, "nnacamp") == 1
    assert "by analogy" in ev.reason
    rows[-1] = well("P1", "X1", "T", "NAC", "nac", None)
    (ev,), _ = run(rows, "G-NAC")
    assert ev.verdict == "pass"
    (ev,), _ = run(rows[:-1], "G-NAC")
    assert (ev.verdict, ev.code) == ("not_applicable", "no_nac_typed")


# ---------- G-NRT ----------


@pytest.mark.parametrize(
    ("delta", "grade", "verdict"),
    [(8.0, "a", "pass"), (4.0, "b", "warn"), (1.5, "c", "fail"), (0.3, "f", "fail")],
)
def test_genomic_dna_share_from_a_pooled_no_rt_control_is_graded(delta, grade, verdict):
    eff = 2.0
    rows = ntc_plate([None], [])
    rows += replicates("P1", "T", "S1", [24.0, 24.2], start=1, row="B", eff=eff)
    rows.append(well("P1", "R1", "T", "noRT pool", "nrt", 24.1 + delta, eff=eff))
    (ev,), ctx = run(rows, "G-NRT")
    assert (ev.outcome, ev.verdict) == (f"grade_{grade}", verdict)
    assert ev.scope == {"plate": "P1", "target": "T", "sample": "S1"}
    assert value(ctx, ev, "gdna") == pytest.approx(round(eff**-delta, 6), abs=1e-6)
    assert value(ctx, ev, "cqrt") == pytest.approx(24.1)
    assert "pooled no-RT control" in ev.reason and "qPilot adaptation" in ev.reason
    if verdict == "pass":
        assert ev.flagged == [] and ev.options == {}
    else:
        assert ev.flagged == ["P1/B1", "P1/B2"]
        assert ev.options == {"exclude_sample_target": ["P1/B1", "P1/B2"]}


def test_a_no_rt_control_that_did_not_amplify_is_grade_a_and_absence_is_not_a_failure():
    rows = ntc_plate([None], [25.0])
    rows.append(well("P1", "R1", "T", "pool", "nrt", None))
    (ev,), _ = run(rows, "G-NRT")
    assert (ev.outcome, ev.verdict) == ("grade_a", "pass")
    (ev,), _ = run(rows[:-1], "G-NRT")
    assert (ev.verdict, ev.code) == ("not_applicable", "no_nrt_typed")


def test_a_paired_no_rt_control_without_rt_wells_says_so():
    """An ``nrt`` well named like a study sample is paired with it, amplified or not."""
    rows = ntc_plate([None], [])
    rows += [well("P1", "B1", "T", "S1", "unkn", None), well("P1", "B2", "T", "S2", "unkn", 25.0)]
    rows.append(well("P1", "R1", "T", "S1", "nrt", 30.0))
    evals, _ = run(rows, "G-NRT")
    ev = only(evals, sample="S1")
    assert (ev.verdict, ev.code) == ("not_applicable", "no_rt_wells")
    assert len(evals) == 1  # paired: S2 is not compared with S1's control


# ---------- G-POS ----------


def test_a_positive_control_without_a_window_is_not_applicable_and_shows_its_cq():
    rows = ntc_plate([None], [25.0])
    rows.append(well("P1", "Q1", "T", "POS", "pos", 22.5))
    (ev,), ctx = run(rows, "G-POS")
    assert (ev.verdict, ev.code) == ("not_applicable", "pos_unmapped")
    assert value(ctx, ev, "cqpos") == pytest.approx(22.5)
    (ev,), _ = run(rows[:-1], "G-POS")
    assert ev.code == "no_pos_typed"


# ---------- G-STD ----------

LEVELS = (1e1, 1e2, 1e3, 1e4, 1e5)


def std_rows(slope=-3.3219, intercept=38.0, noise=(0.0, 0.0, 0.0), levels=LEVELS, reps=3):
    rows, quantities = [], {}
    for i, q in enumerate(levels):
        name = f"STD_{int(q)}"
        quantities[(name, "T")] = q
        for r in range(reps):
            cq = intercept + slope * math.log10(q) + noise[r % len(noise)] * (1 if i % 2 else -1)
            rows.append(well("P1", f"S{i}{r}", "T", name, "std", cq, eff_indiv=1.9))
    return rows, quantities


def test_a_standard_curve_inside_the_window_passes_with_the_fit_shown():
    rows, quantities = std_rows(noise=(0.05, -0.04, 0.02))
    (ev,), ctx = run(rows, "G-STD", quantities=quantities)
    assert (ev.verdict, ev.outcome) == ("pass", "ok")
    x = np.log10([quantities[(r["sample"], "T")] for r in rows])
    y = np.array([r["cq"] for r in rows])
    fit = stats.linregress(x, y)
    assert ev.evidence["slope"] == pytest.approx(fit.slope, abs=1e-9)
    assert ev.evidence["intercept"] == pytest.approx(fit.intercept, abs=1e-9)
    assert ev.evidence["r2"] == pytest.approx(fit.rvalue**2, abs=1e-12)
    assert ev.evidence["efficiency"] == pytest.approx(10 ** (-1 / fit.slope), abs=1e-12)
    np.testing.assert_allclose(np.polyfit(x, y, 1)[0], ev.evidence["slope"], atol=1e-9)
    assert value(ctx, ev, "estd") == pytest.approx(round(10 ** (-1 / fit.slope) - 1, 6))
    assert value(ctx, ev, "nlevels") == 5
    lo, hi = value(ctx, ev, "estdlo"), value(ctx, ev, "estdhi")
    assert lo < value(ctx, ev, "estd") < hi
    text = rendered(ev.reason, ctx.facts.as_dict())
    assert "efficiency 100.0%" in text and "confidence interval" in text
    assert "evidence, not a failure" in text  # the per-curve efficiency, next to the curve's


@pytest.mark.parametrize(
    ("kwargs", "outcome", "verdict"),
    [
        ({"slope": -3.75}, "efficiency_out", "fail"),
        ({"slope": -3.0}, "efficiency_out", "fail"),
        ({"noise": (0.9, -0.8, 0.6)}, "r2_low", "fail"),
        ({"reps": 2}, "few_replicates", "warn"),
    ],
)
def test_a_standard_curve_outside_the_pack_fails_or_warns(kwargs, outcome, verdict):
    rows, quantities = std_rows(**kwargs)
    (ev,), ctx = run(rows, "G-STD", quantities=quantities)
    assert (ev.outcome, ev.verdict) == (outcome, verdict)
    assert "does not taint study samples" in ev.reason
    if outcome == "few_replicates":
        assert value(ctx, ev, "repmin") == 2 and "three or more" in ev.reason


def test_a_curve_over_too_few_levels_or_without_quantities_is_not_applicable():
    rows, quantities = std_rows(levels=(1e2, 1e3))
    (ev,), _ = run(rows, "G-STD", quantities=quantities)
    assert (ev.verdict, ev.code) == ("not_applicable", "too_few_levels")
    (ev,), _ = run(rows, "G-STD")
    assert (ev.verdict, ev.code) == ("not_applicable", "no_quantity")


def test_a_short_dilution_series_says_how_far_it_spans_and_unamplified_levels_are_left_out():
    rows, quantities = std_rows(levels=(1e2, 1e3, 1e4))
    rows.append(well("P1", "Z1", "T", "STD_10", "std", None))
    quantities[("STD_10", "")] = 10.0  # a quantity declared for every target
    (ev,), ctx = run(rows, "G-STD", quantities=quantities)
    assert ev.verdict == "pass" and value(ctx, ev, "span") == pytest.approx(2.0)
    assert "orders of magnitude" in ev.reason
    assert ev.evidence["n_std_not_amplified"] == 1


def test_a_processed_input_hides_the_per_curve_efficiency():
    rows, quantities = std_rows()
    (ev,), _ = run(rows, "G-STD", quantities=quantities, rawness="processed")
    assert "per curve" not in ev.reason and "eff_gap" not in ev.evidence


# ---------- G-REP ----------


def test_the_range_quantiles_are_the_studentized_range_with_infinite_df():
    for n in range(2, 8):
        assert range_quantile(n) == pytest.approx(
            stats.studentized_range.ppf(0.95, n, np.inf), abs=1e-6
        )


def rep_plate(groups: dict[str, list[float | None]], eff: float = 1.9):
    rows = ntc_plate([None], [], eff=eff)
    for i, (sample, cqs) in enumerate(groups.items()):
        rows += replicates("P1", "T", sample, cqs, row="ABCDEFGH"[i], eff=eff)
    return rows


def test_tight_replicates_pass_against_the_pipetting_tolerance():
    evals, ctx = run(rep_plate({"S1": [24.0, 24.2, 24.1]}), "G-REP")
    ev = only(evals, sample="S1")
    assert ev.verdict == "pass"
    tol = range_quantile(3) * 0.15 / math.log(1.9)  # copies unknown, Cq ≤ 30: pipetting only
    assert value(ctx, ev, "tol") == pytest.approx(round(tol, 6))
    assert value(ctx, ev, "range") == pytest.approx(0.2)
    assert ev.evidence["flags"] == "copies_unknown"


def test_an_outlying_replicate_warns_and_offers_the_well_or_the_sample():
    evals, ctx = run(rep_plate({"S1": [24.0, 24.1, 26.0]}), "G-REP")
    ev = only(evals, sample="S1")
    assert (ev.verdict, ev.flagged) == ("warn", ["P1/A3"])
    assert ev.options == {
        "drop_outlier_well": ["P1/A3"],
        "drop_sample": ["P1/A1", "P1/A2", "P1/A3"],
    }
    assert value(ctx, ev, "nrep") == 3


def test_late_replicates_get_the_two_cycle_floor_and_very_late_ones_are_not_evaluated():
    evals, ctx = run(rep_plate({"S1": [32.0, 33.5], "S2": [36.0, 36.5]}), "G-REP")
    s1 = only(evals, sample="S1")
    assert s1.verdict == "pass" and value(ctx, s1, "tol") == pytest.approx(2.0)
    assert s1.evidence["flags"] == "copies_unknown_low_copy_possible"
    s2 = only(evals, sample="S2")
    assert (s2.verdict, s2.code) == ("not_applicable", "stochastic_range")


def test_a_replicate_that_did_not_amplify_is_counted_not_ranged():
    evals, ctx = run(rep_plate({"S1": [24.0, 24.1, None], "S2": [24.0, None, None]}), "G-REP")
    s1 = only(evals, sample="S1")
    assert s1.verdict == "pass" and value(ctx, s1, "nundet") == 1
    assert "did not amplify" in s1.reason
    s2 = only(evals, sample="S2")
    assert s2.code == "too_few_amplified"


def test_single_wells_have_no_replicates_and_many_outliers_warn_for_the_plate():
    rows = ntc_plate([None], [24.0, 25.0])
    (ev,), _ = run(rows, "G-REP")
    assert (ev.verdict, ev.code) == ("not_applicable", "no_replicates")
    bad = {f"S{i}": [24.0, 24.1, 27.0] for i in range(3)} | {"S9": [24.0, 24.1, 24.05]}
    evals, ctx = run(rep_plate(bad), "G-REP")
    plate = [ev for ev in evals if "sample" not in ev.scope]
    assert [(ev.outcome, ev.verdict) for ev in plate] == [("many_outside", "warn")]
    assert value(ctx, plate[0], "share") == pytest.approx(0.75)
    assert plate[0].options == {}  # a plate-level line: nothing to leave out


def test_copies_from_a_standard_curve_widen_the_tolerance_at_low_copy():
    rows, quantities = std_rows(intercept=36.0)
    rows += replicates("P1", "T", "S1", [33.0, 34.4], row="H")
    evals, ctx = run(rows, "G-REP", quantities=quantities)
    ev = only(evals, sample="S1")
    copies = ev.evidence["copies"]
    assert copies is not None and copies < 10 and "approx_low_copy" in ev.evidence["flags"]
    expected = range_quantile(2) * math.sqrt(0.15**2 + 1 / copies) / math.log(1.9)
    assert value(ctx, ev, "tol") == pytest.approx(round(expected, 6), abs=1e-6)
    assert ev.verdict == "pass"


# ---------- the whole pack ----------


def test_every_evaluation_is_deterministic_and_cites_registered_facts():
    rows, quantities = std_rows()
    rows += ntc_plate([30.0, None], [27.0, 20.0])
    rows += rep_plate({"S7": [24.0, 24.1, 26.0]})[1:]
    first, ctx1 = run(rows, quantities=quantities)
    again, ctx2 = run(rows, quantities=quantities)
    assert [ev.model_dump() for ev in first] == [ev.model_dump() for ev in again]
    assert ctx1.facts.as_dict() == ctx2.facts.as_dict()
    assert {ev.verdict for ev in first} >= {"pass", "warn", "fail", "not_applicable"}
    assert all(ev.code for ev in first if ev.verdict == "not_applicable")
