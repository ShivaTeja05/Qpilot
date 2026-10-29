"""Step 4.1 gate: which curves count as amplified, as a screened robustness dimension."""

import numpy as np
import pandas as pd
import pytest

from qpilot.core import robustness
from qpilot.qpcr.amp_call import (
    DEFAULT_AMP_CALLS,
    METHOD_CARD,
    RULES,
    STUDIO_AMP_CALLS,
    AmpCallError,
    amplified,
    apply_rule,
    disagreements,
    register_learned,
    screen_amp_call,
    well_calls,
)
from qpilot.schemas import ContrastResult
from qpilot.schemas_studio import AmpCallRule
from tests.timing import work_time

NAN = float("nan")


def _table():
    return pd.DataFrame(
        {
            "run_id": ["p1"] * 5,
            "well": ["A1", "A2", "A3", "A4", "A5"],
            "sample": ["s1", "s2", "s3", "ref", "s5"],
            "sample_type": ["unkn"] * 5,
            "target": ["G", "G", "G", "R", "G"],
            "cq": [30.0, 36.0, 39.0, 41.0, NAN],
            "n0": [8.0, 4.0, 2.0, 1.0, NAN],
        }
    )


def test_rules_on_a_toy_table():
    table = _table()
    assert list(amplified(table, "linregpcr")) == [True, True, True, True, False]
    assert list(amplified(table, "cq_le_40")) == [True, True, True, False, False]
    assert list(amplified(table, "cq_le_38")) == [True, True, False, False, False]
    assert list(amplified(table, "cq_le_35")) == [True, False, False, False, False]
    out = apply_rule(table, "cq_le_35")
    assert out["n0"].isna().tolist() == [False, True, True, True, True]  # control gene too
    assert len(out) == len(table) and table["n0"].notna().sum() == 4  # a copy; no row removed
    pd.testing.assert_frame_equal(apply_rule(table, "linregpcr"), table)


def test_a_persons_call_overrides_every_rule():
    table, calls = _table(), {"p1/A2": True, "p1/A1": False, "p1/A5": True}
    assert list(amplified(table, "cq_le_35", calls)) == [False, True, False, False, False]
    assert list(amplified(table, "linregpcr", calls))[:2] == [False, True]
    assert not amplified(table, "linregpcr", calls).iloc[4]  # no quantity never counts


def test_well_calls_and_disagreements():
    calls = well_calls(_table(), STUDIO_AMP_CALLS)
    assert [c.well for c in calls] == ["A1", "A2", "A3", "A4", "A5"]
    assert calls[1].calls == {
        "linregpcr": True,
        "cq_le_40": True,
        "cq_le_38": True,
        "cq_le_35": False,
    }
    assert calls[4].cq is None and calls[0].cq == 30.0
    assert [c.well for c in disagreements(calls)] == ["A2", "A3", "A4"]


def test_rules_and_the_learned_hook():
    assert DEFAULT_AMP_CALLS == ("linregpcr",)
    assert STUDIO_AMP_CALLS == ("linregpcr", "cq_le_40", "cq_le_38", "cq_le_35")
    assert [r for r, rule in RULES.items() if rule.recommended] == ["linregpcr"]
    assert "common, not recommended" in RULES["cq_le_35"].label
    assert [RULES[r].cq_max for r in STUDIO_AMP_CALLS[1:]] == [40.0, 38.0, 35.0]
    assert "learned" not in RULES  # nothing registers it until its validation has passed
    with pytest.raises(AmpCallError, match="built in"):
        register_learned(AmpCallRule(id="cq_le_35", label="x", kind="learned"), lambda c: c)
    with pytest.raises(AmpCallError, match="only a 'learned'"):
        register_learned(AmpCallRule(id="judge", label="x", kind="cq_max"), lambda c: c)
    with pytest.raises(AmpCallError, match="unknown"):
        amplified(_table(), "learned")
    with pytest.raises(AmpCallError, match="'cq'"):
        amplified(_table().drop(columns="cq"), "cq_le_35")
    assert {"id", "version", "inputs", "outputs", "acceptance_tests", "licence"} <= set(METHOD_CARD)


def test_a_registered_learned_rule_is_one_more_option(monkeypatch):
    from qpilot.qpcr import amp_call

    monkeypatch.setattr(amp_call, "RULES", dict(amp_call.RULES))
    monkeypatch.setattr(amp_call, "_LEARNED", {})
    rule = AmpCallRule(id="learned", label="Curve Judge", kind="learned")
    register_learned(rule, lambda c: c["cq"] < 31)
    assert list(amplified(_table(), "learned")) == [True, False, False, False, False]


def _result(gene, log2fc, p):
    conclusion = "up" if p < 0.05 and log2fc >= 1 else "none"
    return ContrastResult(
        target=gene, log2fc=log2fc, fc=2**log2fc, ci=(1, 2), p=p, t=1, n_hi=3, n_lo=3,
        conclusion=conclusion,
    )  # fmt: skip


def test_screening_admits_flips_or_big_shifts_only():
    def evaluate(results):
        return lambda cell: results[cell.get("amp_call", "a")]

    base = {"G": _result("G", 2.0, 0.01), "H": _result("H", 0.1, 0.5)}
    quiet = {"a": base, "b": {**base, "H": _result("H", 0.4, 0.5)}}
    screen = screen_amp_call(evaluate(quiet), {"amp_call": "a"}, ["a", "b"], ["G", "H"])
    assert not screen.admitted and screen.rules[0].max_delta_log2fc == pytest.approx(0.3)
    moved = {"a": base, "b": {**base, "H": _result("H", 0.7, 0.5)}}
    assert screen_amp_call(evaluate(moved), {"amp_call": "a"}, ["a", "b"], ["G", "H"]).admitted
    flipped = {"a": base, "b": {**base, "G": _result("G", 2.0, 0.2)}}
    screen = screen_amp_call(evaluate(flipped), {"amp_call": "a"}, ["a", "b"], ["G", "H"])
    assert screen.admitted and screen.rules[0].flipped == ("G",)


# ---------- the demo study (oracles from docs/studio-measured.md) ----------


@pytest.fixture(scope="module")
def studio_demo(demo_curves):
    from qpilot.io.datasets import VERMEULEN_SHA256
    from qpilot.qpcr.designs import vermeulen_design
    from qpilot.qpcr.study import StudySettings, study_from_curves

    design = vermeulen_design().model_copy(update={"amp_calls": STUDIO_AMP_CALLS})
    return study_from_curves(demo_curves, VERMEULEN_SHA256, StudySettings.from_design(design))


ORACLE = {
    "cq_le_35": [
        "CLSTN1", "EPN2", "MRPL3", "NTRK1", "PAICS", "PLAT", "PRKACB_bis", "PTPRF", "PTPRH",
        "SLC25A5",
    ],
    "cq_le_38": ["CLSTN1", "EPN2", "PLAGL1"],
    "cq_le_40": ["CLSTN1"],
}  # fmt: skip


def _flipped(grid, result, rule_id):
    rows = grid[
        (grid["amp_call"] == rule_id)
        & (grid["cut"] == 0.15)
        & (grid["undetermined"] == "drop")
        & (grid["refs"].map(len) == 5)
    ]
    primary = rows["item"].map({g: r.conclusion for g, r in result.robustness.items()})
    return sorted(rows.loc[rows["conclusion"] != primary, "item"])


@pytest.mark.demo_data
def test_demo_amp_call_oracle(studio_demo):
    """Measured: 10 (Cq <= 35), 3 (<= 38), 1 (<= 40); the plan's 7 and 2 did not reproduce."""
    result, cards, grid = studio_demo
    for rule_id, genes in ORACLE.items():
        assert _flipped(grid, result, rule_id) == genes, rule_id
        assert result.facts[f"f_n_flipped_amp_{rule_id}"].value == len(genes)
        assert result.facts[f"f_screen_amp_flips_{rule_id}"].value == len(genes)
    assert result.facts["f_n_flipped_amp_linregpcr"].value == 0
    assert result.facts["f_screen_amp_call"].value == "admitted"
    ntrk1 = grid[(grid["item"] == "NTRK1") & (grid["amp_call"] == "cq_le_35")]
    primary_cell = ntrk1[(ntrk1["cut"] == 0.15) & (ntrk1["undetermined"] == "drop")]
    assert result.contrasts["NTRK1"].conclusion == "down"
    assert primary_cell[primary_cell["refs"].map(len) == 5]["conclusion"].tolist() == ["none"]
    card = next(c for c in cards if c.id == "card_amp_call")
    assert card.kind == "amp_call" and card.recommended == "linregpcr"
    assert card.evidence["title"] == "Which curves count as amplified"
    assert [o.id for o in card.options] == list(STUDIO_AMP_CALLS)
    assert card.evidence["n_flipped_by_rule"] == {
        "linregpcr": 0, "cq_le_40": 1, "cq_le_38": 3, "cq_le_35": 10
    }  # fmt: skip
    assert card.status == "open"  # it flips conclusions, so a person decides
    assert not [f for f in card.facts if f not in result.facts]


@pytest.mark.demo_data
def test_demo_std15_late_wells(demo_curves):
    std15 = demo_curves[demo_curves["sample"] == "STD_15"]
    assert len(std15) == 192 and int((std15["cq"] > 35).sum()) == 90
    calls = disagreements(well_calls(std15, ("linregpcr", "cq_le_35")))
    assert len(calls) == 90  # every one of them had a LinRegPCR quantity


@pytest.mark.demo_data
def test_demo_grid_size_and_sweep_time(studio_demo, demo_curves):
    from qpilot.qpcr.curves import REFERENCE_TARGETS
    from qpilot.qpcr.quant import log2_matrix
    from qpilot.qpcr.refgenes import genorm
    from qpilot.qpcr.space import QpcrSpace

    result, _, grid = studio_demo
    assert result.facts["f_n_cells"].value == 744 and len(grid) == 744 * 58
    matrix = log2_matrix(demo_curves)
    others = {r: log2_matrix(apply_rule(demo_curves, r)) for r in STUDIO_AMP_CALLS[1:]}
    space = QpcrSpace(matrix, genorm(matrix, REFERENCE_TARGETS), amp_alternatives=others)
    with work_time() as spent:
        swept = robustness.run_grid(space)
    assert len(swept) == 744 * 58
    assert spent.seconds < 2, f"744-cell sweep took {spent}"
    # the primary cell is the legacy analysis exactly: a rule never changes the primary choice
    legacy = QpcrSpace(matrix, genorm(matrix, REFERENCE_TARGETS)).evaluate(
        {"refs": REFERENCE_TARGETS, "cut": 0.15, "undetermined": "drop"}
    )
    assert result.contrasts == legacy
    assert np.isfinite([c.p for c in result.contrasts.values()]).all()


@pytest.mark.demo_data
def test_demo_ampcall_template_validates(studio_demo, fixture_result):
    from qpilot.ai.explain import card_names
    from qpilot.core.validator import names_from_result, validate
    from qpilot.explain.templates import render_template

    result, cards, _ = studio_demo
    card = next(c for c in cards if c.id == "card_amp_call")
    rendered = render_template("ampcall_v1", result.facts, card=card)
    assert validate(rendered.tokens, result.facts, card_names(card)).ok
    assert validate(rendered.tokens, result.facts, names_from_result(result)).ok
    assert "{{f_n_flipped_amp_cq_le_35}}" in rendered.tokens
    assert "10 of 58 genes change their conclusion" in rendered.plain
    assert "common, not recommended" in rendered.plain
    legacy = render_template("ampcall_v1", fixture_result.facts)  # no axis: words, no numbers
    assert legacy.fact_ids == () and "LinRegPCR's own call only" in legacy.plain


def test_a_curve_the_learned_rule_cannot_score_keeps_linregpcrs_call(monkeypatch):
    import pandas as pd

    from qpilot.qpcr import amp_call
    from qpilot.schemas_studio import AmpCallRule

    rule = AmpCallRule(id="learned_test", label="learned (test)", kind="learned")
    monkeypatch.setitem(amp_call.RULES, rule.id, rule)
    monkeypatch.setitem(
        amp_call._LEARNED, rule.id, lambda curves: pd.Series([True, False, None], dtype=object)
    )
    curves = pd.DataFrame(
        {"run_id": ["r"] * 3, "well": ["A1", "A2", "A3"], "n0": [5.0, 5.0, 5.0], "cq": [20.0] * 3}
    )
    assert amp_call.amplified(curves, rule.id).tolist() == [True, False, True]


# ---------- science review J1: LinRegPCR's own "no amplification" respected (opt-in) ----------


def test_the_strict_rule_follows_linregpcrs_call():
    from qpilot.qpcr.amp_call import STRICT, no_amplification_with_quantity

    table = _table().assign(
        sample_type=["unkn", "unkn", "std", "unkn", "unkn"],
        amplification=[True, False, False, True, False],
    )
    assert list(amplified(table, STRICT)) == [True, False, False, True, False]
    assert list(amplified(table, "linregpcr")) == [True, True, True, True, False]
    assert list(no_amplification_with_quantity(table)) == [False, True, True, False, False]
    assert list(amplified(table, STRICT, {"p1/A2": True})) == [True, True, False, True, False]
    # a negative control keeps its quantity: it is the contamination signal the gate weighs
    ntc = table.assign(sample_type=["ntc"] * 5)
    assert list(amplified(ntc, STRICT)) == list(amplified(ntc, "linregpcr"))
    # a table without LinRegPCR's call (a file of Cq values only) falls back on the quantity
    assert list(amplified(_table(), STRICT)) == list(amplified(_table(), "linregpcr"))
    assert STRICT in RULES and STRICT not in STUDIO_AMP_CALLS  # offered, not the default
    assert not RULES[STRICT].recommended


def test_strict_rule_on_the_edna_sample_plate():
    """QuantStudio 7 Pro eDNA plate (corpus): 7 unknown wells LinRegPCR calls no amplification
    carry quantities, one at Cq 19.1 with 2.5 x 10^6 copies; its NTCs are left as they are."""
    from pathlib import Path

    from qpilot.qpcr.amp_call import STRICT, no_amplification_with_quantity
    from qpilot.qpcr.curves import analyse_study

    folder = Path(__file__).parents[1] / "fixtures/corpus/rdml/quantstudio7pro-rdml-1.2-edna"
    path = folder / "SupplementaryMaterials2_qPCR_Plate1.rdml"
    table = analyse_study(path, None, ())
    flat = table[no_amplification_with_quantity(table)]
    assert sorted(flat["well"]) == ["A5", "C5", "C9", "D9", "E1", "E6", "F5"]
    assert set(flat["sample_type"]) == {"unkn"}
    c9 = flat[flat["well"] == "C9"].iloc[0]
    assert c9["cq"] == pytest.approx(19.1, abs=0.05) and c9["n0"] == pytest.approx(2.49e6, rel=0.01)
    assert int(amplified(table, "linregpcr").sum()) - int(amplified(table, STRICT).sum()) == 7
    out = apply_rule(table, STRICT)
    assert out.loc[flat.index, "n0"].isna().all()
    ntc = table["sample_type"] == "ntc"
    pd.testing.assert_series_equal(out.loc[ntc, "n0"], table.loc[ntc, "n0"])


@pytest.mark.demo_data
def test_demo_strict_rule_changes_no_call(demo_curves):
    """The review's measurement: 11 of 24 576 wells, no call changes, at most 0.069 log2."""
    from qpilot.io.datasets import VERMEULEN_SHA256
    from qpilot.qpcr.amp_call import STRICT, no_amplification_with_quantity
    from qpilot.qpcr.designs import vermeulen_design
    from qpilot.qpcr.study import StudySettings, study_from_curves

    flat = demo_curves[no_amplification_with_quantity(demo_curves)]
    assert len(demo_curves) == 24_576 and len(flat) == 11
    mtss1 = flat[flat["target"] == "MTSS1"].iloc[0]
    assert mtss1["cq"] == pytest.approx(23.82, abs=0.01)
    design = vermeulen_design().model_copy(update={"amp_calls": ("linregpcr", STRICT)})
    result, _, grid = study_from_curves(
        demo_curves, VERMEULEN_SHA256, StudySettings.from_design(design)
    )
    assert result.facts["f_screen_amp_flips_linregpcr_call"].value == 0
    assert result.facts["f_screen_amp_dlog2fc_linregpcr_call"].value == pytest.approx(
        0.0687, abs=5e-4
    )
    assert result.facts["f_screen_amp_call"].value == "not admitted"  # the grid stays 186 cells
    assert result.facts["f_n_cells"].value == 186 and "amp_call" not in grid.columns
