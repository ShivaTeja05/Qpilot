"""G-MELT, and G-NTC-1's class of a control's product, in the pack (research-default 1.2.0 on).

G-MELT reads each well's melt curve (``qpcr/melt.py``): per study sample x target x plate, one
product at the assay's melting temperature passes, an extra peak warns, no product at the
expected temperature fails (the flagged wells go to the consequence test); per no-template
sample, what melted in it. G-NTC-1 grades a tainted plate with that class: a primer-dimer is a
warning (``tainted_dimer``), anything else a failure, as before. Synthetic melt curves
(``tests/qpcr/melt_curves.py``) on hand-built tables (``tests/gate/wells.py``) and on the toy
study (``tests/engine/evidence_toys.py``); one real CFX export.
"""

from __future__ import annotations

import re

import pytest

from qpilot.core.rules import NOT_APPLICABLE, Rule, override
from qpilot.qpcr import melt as M
from qpilot.qpcr.gate_rules import (
    CHECKS,
    MELT_OUTCOMES,
    GateContext,
    evaluate,
    melt_params,
    melt_products,
    ntc_gap,
    resolve_pack,
    run_gate,
)
from qpilot.qpcr.study import StudySettings
from tests.engine.evidence_toys import toy_design, toy_table
from tests.gate.wells import check_cited, rendered, table, well
from tests.qpcr.melt_curves import INHIBITION, curve, hsieh_rdml, melt_data

PACK = resolve_pack()
G_MELT = PACK.rule("G-MELT")
G_NTC = PACK.rule("G-NTC-1")
BANNED = re.compile(r"\b(specific|confirmed|identified|valid|invalid)\b", re.I)


def evals_of(rule: Rule, ctx: GateContext, pack=PACK):
    """The rule's evaluations on ``ctx`` through the pack (severity applied), facts checked."""
    out = [ev for ev in evaluate(pack, ctx) if ev.rule_id == rule.id]
    facts = ctx.facts.as_dict()
    for ev in out:
        check_cited(ev, facts)
        assert not BANNED.search(rendered(ev.reason, facts)), ev.reason
    return out


def plate():
    """Three replicate pairs (one pair off and with a primer-dimer), a flat one, controls."""
    rows = [
        well("P", "A1", "T", "S1", cq=20.0),
        well("P", "A2", "T", "S1", cq=20.1),
        well("P", "A3", "T", "S2", cq=22.0),
        well("P", "A4", "T", "S2", cq=22.2),
        well("P", "A5", "T", "S3", cq=24.0),
        well("P", "A6", "T", "S3", cq=24.3),
        well("P", "A7", "T", "S4", cq=33.0),
        well("P", "A8", "T", "S5", cq=None),
        well("P", "H1", "T", "NTC1", "ntc", cq=None),
        well("P", "H2", "T", "NTC2", "ntc", cq=36.0),
        well("P", "H3", "T", "NTC3", "ntc", cq=34.0),
        well("P", "H4", "T", "NTC4", "ntc", cq=35.0),
    ]
    curves = [
        curve("A1", ((84.0, 1.0),)),
        curve("A2", ((84.2, 1.0),)),
        curve("A3", ((83.9, 1.0),)),
        curve("A4", ((84.1, 1.0),)),
        curve("A5", ((85.6, 1.0),)),
        curve("A6", ((76.0, 0.2), (84.0, 1.0))),
        curve("A7", ()),
        curve("A8", ()),
        curve("H1", ()),
        curve("H2", ((76.0, 0.3),)),
        curve("H3", ((84.0, 0.2),)),
        curve("H4", ((90.0, 0.2),)),
    ]
    return rows, curves


def ctx_of(rows, curves, **kw) -> GateContext:
    return GateContext(table=table(rows), melt=melt_data(curves, **kw))


# ---------- the rule ----------


def test_the_pack_carries_g_melt_with_its_sources_and_thresholds():
    assert G_MELT.check == "melt_products"
    assert G_MELT.params == {
        "tm_tolerance_c": 1.0,
        "extra_peak_share": 0.05,
        "noise_share": 0.05,
        "min_wells": 3,
        "dimer_min_below_c": 3.0,
    }
    assert G_MELT.sources == ["rdmlpython_melt", "ririe_1997", "miqe2", "lab_default"]
    assert set(G_MELT.severity) == set(MELT_OUTCOMES)
    assert G_MELT.consequence_scope == ["exclude_flagged"]
    assert set(G_MELT.consequence_scope) <= set(CHECKS["melt_products"].options)
    assert melt_params(PACK) == M.MeltParams()
    # G-NTC-1 already mapped the primer-dimer class it now reports
    assert G_NTC.severity["tainted_dimer"] == "warn"


def test_without_melt_curves_the_rule_is_not_applicable_once():
    rows, _ = plate()
    for melt in (None, M.EMPTY):
        ctx = GateContext(table=table(rows), melt=melt)
        (ev,) = evals_of(G_MELT, ctx)
        assert (ev.scope, ev.verdict, ev.code) == ({}, NOT_APPLICABLE, "no_melt_data")
        assert "no melt curves" in ev.reason and "Melt Curve RFU Results" in ev.reason


def test_each_samples_wells_and_each_control_on_a_plate():
    ctx = ctx_of(*plate())
    out = {ev.scope.get("sample", ""): ev for ev in evals_of(G_MELT, ctx)}
    verdicts = {k: (ev.outcome, ev.verdict) for k, ev in out.items()}
    assert verdicts == {
        "S1": ("one_product", "pass"),
        "S2": ("one_product", "pass"),
        "S3": ("tm_off", "fail"),
        "S4": ("no_peak", "fail"),
        "": (NOT_APPLICABLE, NOT_APPLICABLE),  # S5 did not amplify
        "NTC1": ("ntc_clean", "pass"),
        "NTC2": ("ntc_dimer", "pass"),
        "NTC3": ("ntc_product", "warn"),
        "NTC4": ("ntc_other_product", "warn"),
    }
    s3 = out["S3"]
    assert s3.flagged == ["P/A5", "P/A6"] and s3.options == {"exclude_flagged": ["P/A5", "P/A6"]}
    assert s3.evidence["calls"] == "A5:tm_off,A6:extra_peak"
    facts = ctx.facts.as_dict()
    text = rendered(s3.reason, facts)
    assert "Well A5's main peak is at 85.6 °C" in text
    assert "Well A6 shows a second peak beside its product at 84.0 °C: at 76.0 °C (17%" in text
    assert "primer-dimer" in text
    assert "the median of 6 study wells; the rule allows ±1.0 °C" in text
    one = rendered(out["S1"].reason, facts)
    assert one.startswith("Its 2 amplified wells each melt as one product, at 84.0 °C to 84.2 °C")
    assert "does not guarantee that it is the intended amplicon (MIQE 2.0)" in one
    assert out["S1"].flagged == [] and out["S1"].options == {}
    assert out[""].code == "not_amplified" and out[""].scope == {"plate": "P", "target": "T"}
    # controls point at the wells a product is in, but are not study samples: no options
    assert out["NTC3"].flagged == ["P/H3"] and out["NTC3"].options == {}
    assert "a contamination candidate (it amplified at Cq 34.0)" in rendered(
        out["NTC3"].reason, facts
    )
    assert "the no-template control rule grades" in out["NTC2"].reason


def test_the_declared_temperature_and_a_labs_thresholds_are_the_ones_used():
    rows, curves = plate()
    declared = {ev.scope.get("sample"): ev.outcome for ev in evals_of(
        G_MELT, ctx_of(rows, curves, declared_tm={"T": 85.6}))}  # fmt: skip
    # NTC3's peak at 84.0 °C is 1.6 °C below the declared 85.6 °C: closer than a primer-dimer
    # melts (science review J5, pack 1.4.0), so another product, not a primer-dimer
    assert declared["S1"] == "tm_off" and declared["NTC3"] == "ntc_other_product"
    lab = override(
        PACK,
        "1.2.0-lab.1",
        params={"G-MELT": {"tm_tolerance_c": 2.0}},
        severity={"G-MELT": {"extra_peak": "pass"}},
    )
    ctx = ctx_of(rows, curves)
    (s3,) = (ev for ev in evals_of(lab.rule("G-MELT"), ctx, lab) if ev.scope.get("sample") == "S3")
    # A5 is within two degrees now; A6's primer-dimer is the lab's pass
    assert (s3.outcome, s3.verdict, s3.options) == ("extra_peak", "pass", {})
    assert s3.flagged == ["P/A6"]


def test_probe_chemistry_plates_without_melt_and_coarse_readings_say_why():
    rows, curves = plate()
    rows += [well("Q", "A1", "T", "S1", cq=20.0), well("R", "A1", "U", "S1", cq=20.0)]
    rows += [well("P", "B1", "V", "S1", cq=20.0)]
    curves += [curve("A1", target="U", plate="R", lo=60, hi=95, step=2.5)]
    curves += [curve("B1", target="V")]
    ctx = ctx_of(rows, curves, chemistry={"V": "hydrolysis probe"})
    na = {
        tuple(sorted(ev.scope.items())): ev.code
        for ev in evals_of(G_MELT, ctx)
        if ev.verdict == NOT_APPLICABLE and "sample" not in ev.scope
    }
    assert na == {
        (("plate", "P"), ("target", "T")): "not_amplified",
        (("plate", "P"), ("target", "V")): "probe_chemistry",
        (("plate", "Q"),): "no_melt_data",
        (("plate", "R"), ("target", "U")): "coarse_melt",
    }


def test_too_few_study_wells_leave_a_controls_peak_unclassified():
    rows = [well("P", "A1", "T", "S1", cq=20.0), well("P", "H1", "T", "NTC", "ntc", cq=35.0)]
    curves = [curve("A1"), curve("H1", ((76.0, 0.3),))]
    out = {ev.scope.get("sample"): ev for ev in evals_of(G_MELT, ctx_of(rows, curves))}
    assert (out["NTC"].verdict, out["NTC"].code) == (NOT_APPLICABLE, "no_expected_tm")
    assert "only extra peaks are checked" in out["S1"].reason


# ---------- G-NTC-1 with the class of the control's product ----------


def tainted_plate(name: str, ntc_products):
    """Study wells at Cq 30-31 and an NTC at Cq 33: less than five cycles apart (tainted)."""
    rows = [well(name, f"A{i}", "T", f"S{i}", cq=30.0 + 0.2 * i) for i in range(1, 5)]
    rows.append(well(name, "H1", "T", "NTC", "ntc", cq=33.0))
    curves = [curve(f"A{i}", plate=name) for i in range(1, 5)]
    if ntc_products is not None:
        curves.append(curve("H1", ntc_products, plate=name))
    return rows, curves


def test_a_primer_dimer_in_the_control_makes_a_tainted_plate_a_warning():
    rows, curves = tainted_plate("D", ((76.0, 0.3),))
    (ev,) = evals_of(G_NTC, ctx_of(rows, curves))
    assert (ev.outcome, ev.verdict) == ("tainted_dimer", "warn")
    assert ev.evidence["chemistry_class"] == "dimer_candidate"
    assert "primer-dimers are more likely than template, so this is a warning" in ev.reason
    assert ev.flagged and ev.options == {"exclude_flagged": ev.flagged}


@pytest.mark.parametrize(
    ("products", "cls", "words"),
    [
        (((84.0, 0.3),), "contamination_candidate", "treated as contamination"),
        (((90.0, 0.3),), "other_product", "another product, treated as possible contamination"),
        ((), "unclassified", "do not classify every no-template well"),
        (None, "unclassified", "do not classify every no-template well"),
    ],
)
def test_any_other_product_in_the_control_keeps_the_failure(products, cls, words):
    rows, curves = tainted_plate("C", products)
    (ev,) = evals_of(G_NTC, ctx_of(rows, curves))
    assert (ev.outcome, ev.verdict, ev.evidence["chemistry_class"]) == ("tainted", "fail", cls)
    assert words in ev.reason


def test_without_melt_curves_g_ntc_1_says_what_it_said_before():
    rows, _ = tainted_plate("N", None)
    before = list(ntc_gap(G_NTC, GateContext(table=table(rows))))
    other_plate = [curve("A1", plate="elsewhere")]
    for melt in (M.EMPTY, melt_data(other_plate)):
        after = list(ntc_gap(G_NTC, GateContext(table=table(rows), melt=melt)))
        assert [f.model_dump() for f in after] == [f.model_dump() for f in before]
    (f,) = before
    assert f.outcome == "tainted" and f.evidence["chemistry_class"] == "unclassified"
    assert f.reason.endswith("Without melt data the control's product is unclassified "
                             "(contamination or primer-dimer) and is treated as possible "
                             "contamination.")  # fmt: skip


def test_a_late_control_with_a_primer_dimer_says_so_and_flags_nothing():
    rows = [well("L", f"A{i}", "T", f"S{i}", cq=20.0) for i in range(1, 5)]
    rows.append(well("L", "H1", "T", "NTC", "ntc", cq=36.0))
    curves = [curve(f"A{i}", plate="L") for i in range(1, 5)]
    curves.append(curve("H1", ((76.0, 0.3),), plate="L"))
    (ev,) = evals_of(G_NTC, ctx_of(rows, curves))
    assert (ev.outcome, ev.verdict, ev.flagged) == ("amplified_clear", "warn", [])
    assert ev.reason.endswith("primer-dimers are more likely than template.")


# ---------- the consequence test and a real export ----------


def test_leaving_the_flagged_wells_out_is_priced_by_the_consequence_test():
    curves_table = toy_table()
    settings = StudySettings.from_design(toy_design())
    t1 = curves_table[curves_table["target"] == "T1"]
    plate_id = str(t1["run_id"].iloc[0])
    melts = []
    for w, sample, kind in t1[["well", "sample", "sample_type"]].itertuples(index=False):
        products = ((84.0, 1.0),) if not sample.startswith("u2") else ((87.0, 1.0),)
        if kind == "ntc":
            products = ()
        melts.append(curve(w, products, plate=plate_id, target="T1", sample=sample))
    report = run_gate(curves_table, settings, melt=melt_data(melts))
    tested = [c for c in report.consequences if c.rule_id == "G-MELT"]
    assert {c.scope["sample"] for c in tested} == {"u2a", "u2b"}
    for c in tested:
        (option,) = c.options
        assert option.option == "exclude_flagged" and len(option.excluded) == 1
    evals = [ev for ev in report.evals if ev.rule_id == "G-MELT"]
    assert {ev.verdict for ev in evals if ev.scope.get("sample", "").startswith("u2")} == {"fail"}
    assert report.pack["version"] == "1.4.0"


def test_the_cfx_exports_late_no_template_controls(tmp_path):
    """hsieh2016's inhibition plate: two NTCs amplified late (G-NTC-1 warns, 15 cycles clear);
    both melt at the product's temperature: G-MELT says contamination candidate, and G-NTC-1
    says so too."""
    from qpilot.qpcr.curves import analyse_study

    path = hsieh_rdml(str(tmp_path))
    curves = analyse_study(path, "qpilot_import", (), use_cache=False)
    ctx = GateContext(table=curves, melt=M.read_melt(path))
    ntc = [ev for ev in evals_of(G_NTC, ctx) if ev.scope.get("plate") == INHIBITION]
    assert [(ev.outcome, ev.evidence["chemistry_class"]) for ev in ntc] == [
        ("amplified_clear", "contamination_candidate")
    ]
    ctx = GateContext(table=curves, melt=M.read_melt(path))
    melt = [ev for ev in evals_of(G_MELT, ctx) if ev.scope.get("plate") == INHIBITION]
    by = {}
    for ev in melt:
        by[ev.outcome] = by.get(ev.outcome, 0) + 1
    assert by == {"one_product": 14, "ntc_product": 2, "ntc_clean": 1}
    assert sorted(k for ev in melt for k in ev.flagged) == [
        f"{INHIBITION}/A1",
        f"{INHIBITION}/A2",
    ]


def test_every_g_melt_evaluation_is_deterministic():
    rows, curves = plate()
    first = [ev.model_dump() for ev in evals_of(G_MELT, ctx_of(rows, curves))]
    again = [ev.model_dump() for ev in evals_of(G_MELT, ctx_of(rows, curves))]
    assert first == again
    assert list(melt_products(G_MELT, GateContext(table=table(rows))))[0].code == "no_melt_data"


def test_a_peak_just_below_the_product_is_another_product_not_a_primer_dimer():
    """Science review J5: a no-template peak counts as a primer-dimer only 3 °C or more below
    the product (lab-editable); 1.1 °C below, it may be a shorter product or a variant."""
    rows, curves = plate()
    curves = [c for c in curves if c.well not in ("H2", "H3")]
    curves += [curve("H2", ((80.9, 0.3),)), curve("H3", ((82.9, 0.3),))]  # product 84.05 °C
    ctx = ctx_of(rows, curves)
    out = {ev.scope.get("sample"): ev for ev in evals_of(G_MELT, ctx)}
    assert (out["NTC2"].outcome, out["NTC2"].verdict) == ("ntc_dimer", "pass")  # 3.15 °C below
    assert (out["NTC3"].outcome, out["NTC3"].verdict) == ("ntc_other_product", "warn")  # 1.15
    text = rendered(out["NTC3"].reason, ctx.facts.as_dict())
    assert "1.1 °C below this assay's product" in text
    assert "closer than the 3.0 °C a primer-dimer is expected to melt below it" in text
    assert "a shorter product or a variant amplicon" in text
    lab = override(PACK, "1.4.0-lab.1", params={"G-MELT": {"dimer_min_below_c": 1.0}})
    ctx = ctx_of(rows, curves)
    out = {ev.scope.get("sample"): ev for ev in evals_of(lab.rule("G-MELT"), ctx, lab)}
    assert out["NTC3"].outcome == "ntc_dimer"  # a lab's own line
