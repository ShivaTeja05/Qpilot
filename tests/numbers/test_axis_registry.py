"""The axis registry and the stage-cached decision space (add_plan 0.5, gap G5)."""

import pytest

from qpilot.qpcr.axes import (
    AXES,
    DIMENSION_ORDER,
    AxisError,
    AxisOption,
    get_axis,
    ordered,
    stage_index,
    state,
)
from qpilot.qpcr.design import GroupSpec
from qpilot.qpcr.refgenes import genorm
from qpilot.qpcr.space import QpcrSpace
from tests.numbers.conftest import toy_matrix


def test_registry_fixes_the_dimension_order():
    assert DIMENSION_ORDER[:4] == ("refs", "cut", "undetermined", "amp_call")
    assert "efficiency" in DIMENSION_ORDER
    assert [AXES[n].legacy for n in ("refs", "cut", "undetermined")] == [True, True, True]
    assert not AXES["amp_call"].legacy and not AXES["efficiency"].legacy
    assert get_axis("efficiency").card_kind == "numbers.efficiency_model"
    assert ordered(["efficiency", "refs", "amp_call"]) == ["refs", "amp_call", "efficiency"]
    assert stage_index("efficiency") < stage_index("undetermined") < stage_index("refs")


def test_unknown_axis_and_option_are_refused():
    with pytest.raises(AxisError, match="unknown axis"):
        get_axis("plate_model")
    with pytest.raises(AxisError, match="unknown option"):
        get_axis("efficiency").option("guess")
    with pytest.raises(AxisError, match="primary option"):
        state("efficiency", [AxisOption("a", "a", "A")], "b", "swept")


def test_legacy_space_reports_every_axis(toy):
    _, space = toy
    assert list(space.dimensions) == ["refs", "cut", "undetermined"]
    assert list(space.axes) == list(DIMENSION_ORDER)
    status = {name: axis.status for name, axis in space.axes.items()}
    assert status == {
        "refs": "swept",
        "cut": "swept",
        "undetermined": "swept",
        "amp_call": "single_option",
        "efficiency": "single_option",
    }
    assert space.axes["undetermined"].primary.id == "drop"
    assert [o.id for o in space.axes["undetermined"].options] == ["drop", "cap"]
    assert space.axes["cut"].primary.id == "cut_15"
    refs = space.axes["refs"]
    assert refs.primary.value == space.primary["refs"]
    assert refs.options[0].tier == "common_practice"  # a single control gene
    assert space.axes["efficiency"].as_dict()["primary"] == "linregpcr"


def test_groups_design_has_no_cut_axis():
    matrix = toy_matrix()
    a, b = list(matrix.index[:30]), list(matrix.index[30:])
    space = QpcrSpace(
        matrix, genorm(matrix, ["R1", "R2", "R3"]), candidates=("R1", "R2", "R3"), groups=(a, b)
    )
    assert "cut" not in space.dimensions
    assert space.axes["cut"].status == "not_applicable"
    assert "confirmed design" in space.axes["cut"].reason


def test_unsupported_nondetect_option_is_refused():
    matrix = toy_matrix()
    with pytest.raises(AxisError, match="undetermined"):
        QpcrSpace(
            matrix,
            genorm(matrix, ["R1", "R2", "R3"]),
            GroupSpec(marker="M"),
            candidates=("R1", "R2", "R3"),
            undetermined=("drop", "zero"),
        )


def _efficiency_space(calls: list):
    matrix = toy_matrix()
    shifted = matrix.copy()
    shifted["UP"] = shifted["UP"] * 1.1  # a different efficiency model rescales log2 N0

    def source(options):
        calls.append(dict(options))
        return shifted if options["efficiency"] == "per_well" else matrix

    space = QpcrSpace(
        matrix,
        genorm(matrix, ["R1", "R2", "R3"]),
        GroupSpec(marker="M"),
        candidates=("R1", "R2", "R3"),
        matrix_axes={"efficiency": ("linregpcr", "per_well")},
        matrix_source=source,
    )
    return matrix, shifted, space


def test_matrix_axis_comes_after_the_legacy_dimensions_and_is_cached():
    calls: list = []
    matrix, shifted, space = _efficiency_space(calls)
    assert list(space.dimensions) == ["refs", "cut", "undetermined", "efficiency"]
    assert space.primary["efficiency"] == "linregpcr"
    assert space.axes["efficiency"].status == "swept"
    plain = QpcrSpace(
        shifted,
        genorm(matrix, ["R1", "R2", "R3"]),
        GroupSpec(marker="M"),
        candidates=("R1", "R2", "R3"),
    )
    for refs in space.dimensions["refs"]:
        for rule in ("drop", "cap"):
            cell = {"refs": refs, "cut": 0.15, "undetermined": rule}
            mine = space.evaluate({**cell, "efficiency": "per_well"})
            assert mine == plain.evaluate(cell)
    assert calls == [{"amp_call": "linregpcr", "efficiency": "per_well"}]  # built once
    omitted = space.evaluate({"refs": space.primary["refs"], "cut": 0.15, "undetermined": "drop"})
    assert omitted == space.evaluate(space.primary)


def test_matrix_axis_needs_a_source_and_known_options():
    matrix = toy_matrix()
    args = (matrix, genorm(matrix, ["R1", "R2", "R3"]), GroupSpec(marker="M"))
    with pytest.raises(AxisError, match="matrix_source"):
        QpcrSpace(*args, candidates=("R1", "R2", "R3"), matrix_axes={"efficiency": ("a", "b")})
    with pytest.raises(AxisError, match="matrix-stage"):
        QpcrSpace(*args, candidates=("R1", "R2", "R3"), matrix_axes={"refs": ("a",)})
    _, _, space = _efficiency_space([])
    with pytest.raises(AxisError, match="unknown efficiency option"):
        space.evaluate({**space.primary, "efficiency": "assumed_2"})


def test_hold_takes_an_opt_in_axis_out_but_not_a_legacy_one():
    _, _, space = _efficiency_space([])
    space.hold("efficiency", "screened_out", "no option changes anything")
    assert "efficiency" not in space.dimensions and "efficiency" not in space.primary
    assert space.axes["efficiency"].status == "screened_out"
    with pytest.raises(AxisError, match="legacy"):
        space.hold("undetermined", "screened_out", "")
