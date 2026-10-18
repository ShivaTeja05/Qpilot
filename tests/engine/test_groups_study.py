"""Step 3.1 gate: the engine runs from any confirmed design (groups from a sheet, replicates).

A synthetic study built as a per-well table (no download): two groups x three biological units
x three technical replicates, one control gene and two targets. Values are chosen so the fold
change and Welch's p can be computed by hand from the unit means.
"""

import math

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from qpilot.qpcr.designs import study_key
from qpilot.qpcr.study import NGuardError, StudySettings, study_from_curves, write_outputs
from qpilot.schemas_studio import Comparison, SampleDesign, StudyDesign

INPUT = "cd" * 32
REF = {"mA1": 10.0, "mA2": 11.0, "mA3": 9.0, "mB1": 10.5, "mB2": 9.5, "mB3": 10.0}
REL = {  # log2(target) - log2(REF) per biological unit
    "T1": {"mA1": 3.0, "mA2": 3.5, "mA3": 2.5, "mB1": 1.0, "mB2": 1.5, "mB3": 0.5},
    "T2": {"mA1": 0.4, "mA2": -0.2, "mA3": 0.1, "mB1": 0.0, "mB2": 0.3, "mB3": -0.1},
}
SAMPLES = {  # sample -> (biological unit, group); mB3 has two cDNA preparations
    "sA1": ("mA1", "treated"),
    "sA2": ("mA2", "treated"),
    "sA3": ("mA3", "treated"),
    "sB1": ("mB1", "control"),
    "sB2": ("mB2", "control"),
    "sB3a": ("mB3", "control"),
    "sB3b": ("mB3", "control"),
}
OFFSETS = (-1.0, 0.0, 1.0)  # technical replicates, log2 around the unit's value


def toy_wells(rel=REL, overrides=None):
    """One row per well; ``overrides`` maps (sample, target, replicate) -> dict of columns."""
    overrides = overrides or {}
    rows = []
    for plate, target in enumerate(("REF", *rel)):
        well = 0
        for sample, (unit, _) in SAMPLES.items():
            value = REF[unit] + (rel[target][unit] if target != "REF" else 0.0)
            for rep, offset in enumerate(OFFSETS):
                row = {
                    "run_id": f"p{plate}",
                    "well": f"A{well}",
                    "sample": sample,
                    "sample_type": "unkn",
                    "target": target,
                    "n0": 2.0 ** (value + offset),
                    "cq": 40.0 - (value + offset),
                    "eff_target": 1.9,
                }
                row.update(overrides.get((sample, target, rep), {}))
                rows.append(row)
                well += 1
        for name, kind, n0 in (("STD_1", "std", 2.0**20), ("NTC", "ntc", float("nan"))):
            rows.append(
                {
                    "run_id": f"p{plate}",
                    "well": f"Z{kind}",
                    "sample": name,
                    "sample_type": kind,
                    "target": target,
                    "n0": n0,
                    "cq": 20.0 if kind == "std" else float("nan"),
                    "eff_target": 1.9,
                }
            )
    return pd.DataFrame(rows)


def toy_design(samples=SAMPLES, **update) -> StudyDesign:
    design = StudyDesign(
        design_id="toy_groups",
        mode="groups",
        comparison=Comparison(group_a="treated", group_b="control"),
        samples={
            s: SampleDesign(sample=s, group=g, biological_unit=u) for s, (u, g) in samples.items()
        },
        reference_candidates=("REF",),
        headline=("T1", "T2"),
    )
    return design.model_copy(update=update)


def run(curves=None, design=None):
    settings = StudySettings.from_design(design or toy_design())
    return study_from_curves(toy_wells() if curves is None else curves, INPUT, settings)


def hand_welch(a, b):
    """Fold change and Welch p from unit-level relative values, by hand."""
    diff = float(np.mean(a) - np.mean(b))
    return 2**diff, float(stats.ttest_ind(a, b, equal_var=False).pvalue)


@pytest.fixture(scope="module")
def study():
    return run()


def test_groups_come_from_the_design_and_units_are_n(study):
    result, cards, grid = study
    design = result.design
    assert (design.group_var, design.n_hi, design.n_lo) == ("treated vs control", 3, 3)
    assert design.cut == 0.0 and design.note == "groups from the confirmed design"
    assert result.n_samples == 6  # biological units; seven samples, 63 study wells
    assert (result.facts["f_n_hi"].value, result.facts["f_n_lo"].value) == (3, 3)
    assert (result.facts["f_group_a"].value, result.facts["f_group_b"].value) == (
        "treated",
        "control",
    )
    assert "cut" not in grid.columns and "card_cutoff" not in {c.id for c in cards}
    assert result.facts["f_n_cells"].value == 2  # one control gene x drop/cap
    assert {c.id for c in cards} == {"card_refset", "card_undetermined"}


def test_hand_computed_fold_change_and_welch_p(study):
    result, _, _ = study
    t1 = result.contrasts["T1"]
    a = [REL["T1"][u] for u in ("mA1", "mA2", "mA3")]
    b = [REL["T1"][u] for u in ("mB1", "mB2", "mB3")]
    fc, p = hand_welch(a, b)
    assert fc == pytest.approx(4.0) and t1.fc == pytest.approx(fc, rel=1e-9)
    assert t1.p == pytest.approx(p, rel=1e-9)
    assert (t1.n_hi, t1.n_lo, t1.conclusion) == (3, 3, "up")
    assert result.contrasts["T2"].conclusion == "none"


def test_one_undetermined_replicate_is_left_out_of_the_mean():
    curves = toy_wells(overrides={("sA1", "T1", 2): {"n0": float("nan"), "cq": float("nan")}})
    result, _, _ = run(curves)
    # mA1's T1 wells were log2 12, 13, 14; without 14 the unit mean is 12.5, relative 2.5
    a, b = [2.5, 3.5, 2.5], [1.0, 1.5, 0.5]
    fc, p = hand_welch(a, b)
    t1 = result.contrasts["T1"]
    assert t1.fc == pytest.approx(fc, rel=1e-9) and t1.p == pytest.approx(p, rel=1e-9)
    assert (t1.n_hi, t1.n_lo) == (3, 3)
    assert result.facts["f_n_undetermined"].value == 1


def test_a_unit_is_undetermined_only_when_every_replicate_is():
    nan = {"n0": float("nan"), "cq": float("nan")}
    curves = toy_wells(overrides={("sA2", "T2", rep): nan for rep in range(3)})
    result, _, _ = run(curves)
    t2 = result.contrasts["T2"]
    assert (t2.n_hi, t2.n_lo) == (2, 3)
    fc, p = hand_welch([0.4, 0.1], [0.0, 0.3, -0.1])
    assert t2.fc == pytest.approx(fc, rel=1e-9) and t2.p == pytest.approx(p, rel=1e-9)


def test_a_gene_with_one_unit_in_a_group_is_withheld():
    nan = {"n0": float("nan"), "cq": float("nan")}
    overrides = {(s, "T2", rep): nan for s in ("sA1", "sA2") for rep in range(3)}
    result, cards, grid = run(toy_wells(overrides=overrides))
    assert "T2" not in result.contrasts and "T2" not in set(grid["item"])
    assert result.facts["f_n_withheld"].value == 1
    assert result.facts["f_withheld_t2"].value == (
        "fewer than two biological units with a value in treated"
    )
    assert result.contrasts["T1"].conclusion == "up"


def test_n_guard_refuses_a_group_with_one_biological_unit():
    one_animal = {s: ("mA", g) if g == "treated" else (u, g) for s, (u, g) in SAMPLES.items()}
    with pytest.raises(NGuardError, match="fewer than two biological units") as err:
        run(design=toy_design(samples=one_animal))
    assert "the p-value is withheld because a group has fewer than two biological units" in str(
        err.value
    )
    assert "treated has 1" in str(err.value)


def test_a_different_design_of_the_same_input_is_a_different_study(study):
    result, _, _ = study
    other = toy_design(headline=("T1",))
    again = run(design=other)[0]
    assert result.study_id != again.study_id
    assert result.study_id == study_key(INPUT, toy_design())[:12] != INPUT[:12]
    assert len(study_key(INPUT, other)) == 64
    legacy = StudySettings(candidates=("REF",), marker="T1", headline=("T2",))
    assert study_key(INPUT, legacy.design) == INPUT


def test_cards_facts_and_templates_hold_together(study):
    from qpilot.core.validator import names_from_result, validate
    from qpilot.explain.templates import render_template

    result, cards, _ = study
    for card in cards:
        assert not [f for f in card.facts if f not in result.facts], card.id
        rendered = render_template(card.rationale_template, result.facts, card=card)
        assert validate(rendered.tokens, result.facts, names_from_result(result)).ok
    for gene, graded in result.confidence.items():
        for check in graded.checks:
            assert not [f for f in check.fact_ids if f not in result.facts], (gene, check.id)
    refset = next(c for c in cards if c.id == "card_refset")
    assert [o.label for o in refset.options] == ["REF (the only control gene)"]
    assert "f_m_1" not in result.facts and result.facts["f_order_1"].value == "REF"


def test_route_and_withheld_facts_are_studio_facts(study):
    facts = study[0].facts
    assert facts["f_n_withheld"].value == 0
    assert {f"f_n_differ_route_{r}" for r in ("ddcq", "linear_welch", "linear_student")} <= set(
        facts
    )


def test_amp_call_axis_and_nan_p_in_other_cells(tmp_path):
    late = {"cq": 36.0}  # T2 of mA1 and mA2 comes up after cycle 35
    rel = {**REL, "T2": {**REL["T2"], "mA1": 3.0, "mA2": 3.2, "mA3": 3.1}}
    overrides = {(s, "T2", rep): late for s in ("sA1", "sA2") for rep in range(3)}
    design = toy_design(amp_calls=("linregpcr", "cq_le_35"))
    result, cards, grid = run(toy_wells(rel, overrides), design)
    assert result.contrasts["T2"].conclusion == "up"
    assert list(grid.columns[:3]) == ["refs", "undetermined", "amp_call"]
    assert result.facts["f_n_cells"].value == 4
    cell = grid[(grid["amp_call"] == "cq_le_35") & (grid["undetermined"] == "drop")]
    t2 = cell[cell["item"] == "T2"].iloc[0]
    assert t2["conclusion"] == "none" and math.isnan(t2["p"])
    assert result.facts["f_n_flipped_amp_cq_le_35"].value == 1
    assert result.facts["f_screen_amp_call"].value == "admitted"
    assert "card_amp_call" in {c.id for c in cards}
    paths = write_outputs(result, cards, grid, tmp_path)
    lines = paths["grid.csv"].read_text().splitlines()
    header = lines[0].split(",")
    row = next(
        line.split(",")
        for line in lines[1:]
        if ",cq_le_35," in line and ",T2," in line and line.startswith("REF,drop")
    )
    assert row[header.index("p")] == ""  # NaN is written as an empty field


def test_the_same_design_gives_byte_identical_files(study, tmp_path):
    first = write_outputs(*study, tmp_path / "a")
    second = write_outputs(*run(), tmp_path / "b")
    for name in first:
        assert first[name].read_bytes() == second[name].read_bytes(), name


def test_a_sample_retyped_as_a_study_sample_counts_in_its_group(caplog):
    """Review c3: the file calls sB1 a positive control; a person's 'unkn' puts it back in n."""
    from qpilot.qpcr.designs import design_from_proposals
    from qpilot.schemas_studio import MadeBy, Proposal

    pos = {("sB1", t, rep): {"sample_type": "pos"} for t in ("REF", *REL) for rep in range(3)}
    curves = toy_wells(overrides=pos)
    with caplog.at_level("WARNING", logger="qpilot.qpcr.study"):
        left_out = run(curves)[0]
    assert (left_out.contrasts["T1"].n_hi, left_out.contrasts["T1"].n_lo) == (3, 2)
    assert "sB1 (pos)" in caplog.text  # not silently: the sample is named
    retype = Proposal(
        id="p_1",
        study_id="abc123def456",
        kind="design.well_role",
        subject="sB1",
        payload={"role": "pos"},
        made_by=MadeBy(kind="rule"),
        status="edited",
        edits={"role": "unkn"},
    )
    design = design_from_proposals(toy_design(), [retype], curves)
    result = run(curves, design)[0]
    plain = run()[0]
    assert (result.design.n_hi, result.design.n_lo) == (3, 3)
    assert result.contrasts["T1"].fc == pytest.approx(plain.contrasts["T1"].fc, rel=1e-12)
    assert result.contrasts["T1"].p == pytest.approx(plain.contrasts["T1"].p, rel=1e-12)
