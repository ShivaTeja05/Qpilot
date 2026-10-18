"""qpcr/export.py: the per-unit table the bridge hands to Prism, from the engine's arithmetic."""

import json
import math

import numpy as np
import pandas as pd
import pytest

from qpilot.qpcr.contrast import welch_contrast
from qpilot.qpcr.export import (
    TABLE_COLUMNS,
    ExportError,
    exclusion_consequence,
    sample_table,
    unit_contrasts,
)
from qpilot.qpcr.quant import log2_matrix, relative
from tests.engine.test_groups_study import toy_design as groups_design
from tests.engine.test_groups_study import toy_wells
from tests.prism.conftest import (
    TOY_CHAIN,
    TOY_GROUPS,
    TOY_LOG2,
    TOY_STUDY,
    after_acceptance,
    engine_inputs,
    toy_curves,
    toy_inputs,
)

NAN = {"n0": float("nan"), "cq": float("nan")}
CELL = {"refs": ("R1", "R2"), "undetermined": "drop"}
CAP = {"refs": ("REF",), "undetermined": "cap"}

COLUMN_T = {"a1": -5.0, "a2": -4.0, "a3": -3.0, "b1": -8.0, "b2": -8.0, "b3": -7.0}
NESTED_T = {
    "a1": [-6.0, -5.0, -4.0],
    "a2": [-5.0, -4.0, -3.0],
    "a3": [-4.0, -3.0, -2.0],
    "b1": [-8.0, -8.0, -8.0],
    "b2": [-9.0, -8.0, -7.0],
    "b3": [-7.0, -7.0, -7.0],
}


def _table(inputs, layout="column", genes=("T",)):
    return inputs.table(layout, list(genes))


def test_column_layout_is_one_hand_computed_value_per_unit(toy):
    table = _table(toy)
    assert list(table.columns) == list(TABLE_COLUMNS)
    assert len(table) == 6  # six units, never 18 wells: technical replicates are not n
    assert dict(zip(table["biological_unit"], table["log2_rq"], strict=True)) == COLUMN_T
    assert set(table["well_rep"]) == {0}
    assert list(table["group"]) == ["A", "A", "A", "B", "B", "B"]


def test_nested_layout_stacks_three_replicates_per_unit(toy):
    table = _table(toy, "nested")
    assert len(table) == 18
    for unit, values in NESTED_T.items():
        rows = table[table["biological_unit"] == unit]
        assert rows["log2_rq"].tolist() == values
        assert rows["well_rep"].tolist() == [1, 2, 3]


def test_nested_replicates_average_to_the_column_value(toy):
    nested = _table(toy, "nested", ("T", "T2"))
    column = _table(toy, "column", ("T", "T2"))
    means = nested.groupby(["gene", "biological_unit"])["log2_rq"].mean()
    for gene, unit, value in zip(
        column["gene"], column["biological_unit"], column["log2_rq"], strict=True
    ):
        assert math.isclose(means[(gene, unit)], value, abs_tol=1e-12)


def test_one_well_per_unit_is_relative_itself_bit_for_bit():
    curves = toy_curves(replicates=False)
    inputs = toy_inputs(curves)
    table = _table(inputs, genes=("T", "T2"))
    matrix = log2_matrix(curves)
    for gene in ("T", "T2"):
        engine = relative(matrix, gene, ("R1", "R2"), "drop")
        mine = table[table["gene"] == gene].set_index("biological_unit")["log2_rq"]
        assert {u: v.hex() for u, v in mine.items()} == {
            u: float(v).hex() for u, v in engine.items()
        }


def test_matrix_input_gives_the_same_table_as_curves():
    curves = toy_curves(replicates=False)
    kwargs = {
        "refs": ("R1", "R2"),
        "undetermined": "drop",
        "groups": TOY_GROUPS,
        "group_order": ("A", "B"),
    }
    from_curves = sample_table(curves, **kwargs)
    from_matrix = sample_table(log2_matrix(curves), **kwargs)
    pd.testing.assert_frame_equal(from_curves, from_matrix)


def test_undetermined_replicate_drop_and_cap():
    log2 = {k: {g: list(v) for g, v in genes.items()} for k, genes in TOY_LOG2.items()}
    log2["b3"]["T"] = [4, None, 4]
    inputs = toy_inputs(toy_curves(log2))
    dropped = _table(inputs).set_index("biological_unit")["log2_rq"]
    assert dropped["b3"] == -7.0  # the undetermined well is left out of the mean
    capped = _table(toy_inputs(toy_curves(log2), undetermined="cap"))
    capped = capped.set_index("biological_unit")["log2_rq"]
    # The engine's rule: a unit is undetermined only when every replicate is, so under cap b3
    # is still the mean of its two detected wells; the export must equal the engine's value.
    assert capped["b3"] == -7.0
    units = log2_matrix(toy_curves(log2), {})
    assert capped["b3"] == relative(units, "T", ("R1", "R2"), "cap")["b3"]
    nested = _table(inputs, "nested")
    assert nested[nested["biological_unit"] == "b3"]["log2_rq"].tolist() == [-7.0, -7.0]


def test_a_unit_with_every_replicate_undetermined_is_capped_like_the_engine():
    log2 = {k: {g: list(v) for g, v in genes.items()} for k, genes in TOY_LOG2.items()}
    log2["b3"]["T"] = [None, None, None]
    curves = toy_curves(log2)
    capped = _table(toy_inputs(curves, undetermined="cap")).set_index("biological_unit")
    engine = relative(log2_matrix(curves, {}), "T", ("R1", "R2"), "cap")
    assert capped.loc["b3", "log2_rq"] == engine["b3"]
    dropped = _table(toy_inputs(curves)).set_index("biological_unit")
    assert "b3" not in dropped.index
    nested = _table(toy_inputs(curves, undetermined="cap"), "nested")
    assert nested[nested["biological_unit"] == "b3"]["log2_rq"].tolist() == [engine["b3"]]


def test_several_samples_in_one_unit_are_averaged_never_counted():
    log2 = {**TOY_LOG2, "a1x": {"T": [7], "T2": [1], "R1": [10], "R2": [12]}}
    groups = {**TOY_GROUPS, "a1x": "A"}
    curves = toy_curves(log2, replicates=False)
    inputs = toy_inputs(curves, groups=groups, units={"a1x": "a1"})
    table = _table(inputs)
    assert len(table) == 6
    row = table[table["biological_unit"] == "a1"].iloc[0]
    assert row["sample"] == "a1+a1x"
    assert row["log2_rq"] == ((5 + 7) / 2) - 11  # samples a1 (T 5) and a1x (T 7), refs 11


def test_a_unit_in_two_groups_is_refused():
    inputs = toy_inputs(units={"a1": "u", "b1": "u"})
    with pytest.raises(ExportError, match="two groups"):
        _table(inputs)


@pytest.mark.parametrize(
    "change, message",
    [
        ({"groups": {**TOY_GROUPS, "a1": "C"}}, "not in group_order"),
        ({"group_order": ("A", 'B"; x')}, "unsafe group"),
        ({"units": {"a1": "bad\nname"}}, "unsafe biological unit"),
        ({"refs": ("R9",)}, "reference genes not in the data"),
    ],
)
def test_bad_inputs_are_refused(change, message):
    with pytest.raises(ExportError, match=message):
        _table(toy_inputs(**change))


def test_unknown_gene_is_refused(toy):
    with pytest.raises(ExportError, match="genes not in the data"):
        _table(toy, genes=("NOPE",))


def test_unit_contrasts_equal_the_engine_welch_contrast():
    curves = toy_curves(replicates=False)
    inputs = toy_inputs(curves)
    mine = unit_contrasts(_table(inputs, genes=("T", "T2")), ("A", "B"))
    matrix = log2_matrix(curves)
    high = {s for s, g in TOY_GROUPS.items() if g == "A"}
    rest = set(TOY_GROUPS) - high
    for gene in ("T", "T2"):
        engine = welch_contrast(matrix, gene, ("R1", "R2"), "drop", high, rest)
        assert mine[gene] == engine


def test_exclusion_consequence_on_the_toy(toy):
    out = exclusion_consequence(toy, "T", "a3")
    assert out["n_units_before"] == [3, 3] and out["n_units_after"] == [2, 3]
    assert math.isclose(out["log2fc_before"], -4 - (-23 / 3), abs_tol=1e-12)
    assert math.isclose(out["log2fc_after"], -4.5 - (-23 / 3), abs_tol=1e-12)
    assert out["n_genes"] == 2
    assert out["withheld_after"] is None
    assert out["basis"] == {"study_id": TOY_STUDY, "chain_head": TOY_CHAIN, "accepted": []}
    # One replicate cleared in a nested table: the consequence is what accepting it does.
    one_well = exclusion_consequence(toy, "T", "a3", 3)
    engine = after_acceptance(toy.design, toy.curves, [("T", "a3", 3)], CELL)["T"]
    assert one_well["n_units_after"] == [engine.n_hi, engine.n_lo]
    assert one_well["log2fc_after"] == engine.log2fc


def test_a_consequence_needs_the_design_and_the_curves():
    with pytest.raises(ExportError, match="design and per-well table"):
        exclusion_consequence(toy_inputs(design=None), "T", "a3")


# ---------- the consequence is what the engine reports after acceptance ----------


def test_under_cap_the_floor_moves_as_it_does_after_acceptance():
    """mA2's T1 never amplified; mB3 holds T1's lowest value, so excluding it moves the cap."""
    curves = toy_wells(overrides={("sA2", "T1", r): NAN for r in range(3)})
    inputs = engine_inputs(curves, groups_design(), "cap")
    table = inputs.table("column", ["T1"]).set_index("biological_unit")["log2_rq"]
    assert table["mA2"] == -0.5  # capped at the lowest T1 value, mB3's
    out = exclusion_consequence(inputs, "T1", "mB3")
    engine = after_acceptance(groups_design(), curves, [("T1", "mB3", 0)], CAP)["T1"]
    assert out["log2fc_after"] == engine.log2fc
    assert math.isclose(out["log2fc_after"], 0.5833333333333333, abs_tol=1e-12)
    assert out["p_after"] == engine.p and out["conclusion_after"] == engine.conclusion
    # The same row deleted from the exported table keeps mA2 at the old floor (0.4167).
    simulated = unit_contrasts(inputs.table("column"), inputs.group_order)
    left = unit_contrasts(inputs.table("column"), inputs.group_order, exclude=[("T1", "mB3", 0)])
    assert out["log2fc_before"] == pytest.approx(simulated["T1"].log2fc, abs=1e-12)
    assert left["T1"].log2fc != pytest.approx(out["log2fc_after"], abs=1e-6)


def test_a_gene_the_exclusion_withholds_is_reported_withheld_not_held():
    """mB2's T1 never amplified: excluding mB3 leaves control one unit, so T1 is withheld."""
    curves = toy_wells(overrides={("sB2", "T1", r): NAN for r in range(3)})
    inputs = engine_inputs(curves, groups_design(), "cap")
    out = exclusion_consequence(inputs, "T1", "mB3")
    assert out["conclusion_before"] == "up"
    assert out["conclusion_after"] == "withheld"
    assert out["fc_after"] is None and out["p_after"] is None and out["n_units_after"] is None
    assert "fewer than two biological units" in out["withheld_after"]
    assert out["changed_genes"] == ["T1"] and out["n_conclusions_changed"] == 1
    assert "T1" not in after_acceptance(groups_design(), curves, [("T1", "mB3", 0)], CAP)
    json.dumps(out, allow_nan=False)  # plain JSON: the proposal store refuses NaN


# ---------- the demo study ----------


@pytest.mark.demo_data
def test_demo_table_equals_relative_bit_for_bit(demo_inputs):
    matrix = log2_matrix(demo_inputs.data)
    table = demo_inputs.table("column", ["ODC1", "BIRC5", "NTRK1", "NM23A"])
    for gene in ("ODC1", "BIRC5", "NTRK1", "NM23A"):
        engine = relative(matrix, gene, demo_inputs.refs, demo_inputs.undetermined)
        engine = engine[engine.index.isin(list(demo_inputs.groups))]
        mine = table[table["gene"] == gene].set_index("biological_unit")["log2_rq"]
        assert {u: v.hex() for u, v in mine.items()} == {
            u: float(v).hex() for u, v in engine.items()
        }


@pytest.mark.demo_data
def test_demo_inputs_are_the_studys_groups_and_choices(demo_inputs):
    groups = pd.Series(demo_inputs.groups).value_counts()
    assert groups.to_dict() == {"rest": 294, "MYCN-high": 53}
    assert demo_inputs.group_order == ("MYCN-high", "rest")
    assert len(demo_inputs.genes) == 58
    assert demo_inputs.at_primary
    choices = {c.card_id: c for c in demo_inputs.choices}
    assert choices["card_undetermined"].actor == "system"
    assert choices["card_undetermined"].value == "drop"
    assert choices["card_refset"].actor is None  # open: the recommended option, undecided
    assert choices["card_refset"].value == demo_inputs.refs
    assert choices["card_cutoff"].value == 0.15
    assert len(demo_inputs.design_hash) == 64


@pytest.mark.demo_data
def test_demo_contrasts_equal_the_stored_primary_results(demo_inputs):
    table = demo_inputs.table("column", list(demo_inputs.headline))
    mine = unit_contrasts(table, demo_inputs.group_order)
    for gene, result in mine.items():
        stored = demo_inputs.result.contrasts[gene]
        assert result.conclusion == stored.conclusion
        assert math.isclose(result.fc, stored.fc, rel_tol=1e-12)
        assert math.isclose(result.p, stored.p, rel_tol=1e-9)
        assert (result.n_hi, result.n_lo) == (stored.n_hi, stored.n_lo)


@pytest.mark.demo_data
def test_demo_inputs_follow_a_human_decision(demo_study, tmp_path):
    from qpilot.core.store import StudyStore
    from qpilot.qpcr.export import demo_inputs as build

    store, study_id = demo_study
    copy = StudyStore(tmp_path / "studies")
    result, cards = store.get(study_id), store.cards(study_id)
    copy.put(result, cards)
    copy.set_source(study_id, store.source(study_id))
    copy.append_decision(study_id, "card_cutoff", "cut_10", "testing", "human", None)
    inputs = build(copy, study_id)
    choice = {c.card_id: c for c in inputs.choices}["card_cutoff"]
    assert (choice.option, choice.value, choice.actor) == ("cut_10", 0.10, "human")
    assert not inputs.at_primary
    assert pd.Series(inputs.groups).value_counts()["MYCN-high"] < 53
    assert np.isfinite(inputs.table("column", ["ODC1"])["log2_rq"]).all()
