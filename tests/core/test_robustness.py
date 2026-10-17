import pytest

from qpilot.core import robustness as rb
from qpilot.schemas import GeneRobustness, StudyResult
from tests.core.toy_space import ToySpace


@pytest.fixture
def space():
    return ToySpace()


@pytest.fixture
def grid(space):
    return rb.run_grid(space)


def test_grid_has_one_row_per_cell_and_item(space, grid):
    assert rb.n_cells(space) == 6
    assert len(list(rb.cells(space))) == 6
    assert len(grid) == 6 * 3
    assert space.calls == 6  # evaluate once per cell, not per item


def test_holds(grid):
    assert rb.holds_fraction(grid, "g1", "up") == 1.0
    assert rb.holds_fraction(grid, "g2", "up") == pytest.approx(2 / 6)
    assert rb.holds_fraction(grid, "g3", "down") == pytest.approx(3 / 6)


def test_impact_per_dimension(space, grid):
    g2 = rb.impact_per_dimension(grid, space, "g2")
    assert g2["a"]["flips"] is True
    assert g2["b"]["flips"] is False
    g3 = rb.impact_per_dimension(grid, space, "g3")
    assert g3["a"]["flips"] is False and g3["b"]["flips"] is True
    assert g3["b"]["max_delta_log2fc"] == pytest.approx(1.1)
    g1 = rb.impact_per_dimension(grid, space, "g1")
    assert not any(d["flips"] for d in g1.values())
    assert g1["a"]["max_delta_log2fc"] == pytest.approx(0.2)


def test_min_flip_changes(space, grid):
    assert rb.min_flip_changes(grid, space, "g1") == 0
    assert rb.min_flip_changes(grid, space, "g2") == 1
    assert rb.min_flip_changes(grid, space, "g3") == 1


def test_min_flip_counts_combined_changes():
    space = ToySpace()
    base = space.evaluate

    def only_when_both_change(cell):
        out = base(cell)
        if cell["a"] != 0 and cell["b"] != "x":
            out["g1"] = out["g1"].model_copy(update={"log2fc": 0.0, "fc": 1.0})
        return out

    space.evaluate = only_when_both_change
    grid = rb.run_grid(space)
    assert rb.min_flip_changes(grid, space, "g1") == 2
    impact = rb.impact_per_dimension(grid, space, "g1")
    assert not impact["a"]["flips"] and not impact["b"]["flips"]


def test_summary(space, grid):
    s = rb.summary(grid, space)
    assert set(s) == {"g1", "g2", "g3"}
    assert all(isinstance(v, GeneRobustness) for v in s.values())
    assert s["g2"].conclusion == "up" and s["g2"].n_cells == 6
    assert rb.flipped_by(s, "a") == ["g2"]
    assert rb.flipped_by(s, "b") == ["g3"]


def test_tuple_options_serialise(space):
    space.dimensions = {"a": [("r1",), ("r1", "r2"), ("r2",)], "b": ["x", "y"]}
    space.primary = {"a": ("r1",), "b": "x"}
    base = space.evaluate
    space.evaluate = lambda cell: base({"a": len(cell["a"]) - 1, "b": cell["b"]})
    grid = rb.run_grid(space)
    s = rb.summary(grid, space)
    assert s["g1"].holds == 1.0
    assert set(rb.to_csv_frame(grid)["a"]) == {"r1", "r1|r2", "r2"}


def test_bad_primary_rejected(space):
    space.primary = {"a": 9, "b": "x"}
    grid = rb.run_grid(space)
    with pytest.raises(ValueError):
        rb.summary(grid, space)


def test_fixture_summary_shape(fixture_result: StudyResult):
    # The fixture robustness block is what summary() must produce for the real space.
    robustness = fixture_result.robustness
    assert robustness["ODC1"].holds == 1.0
    assert robustness["NM23A"].holds == pytest.approx(0.645, abs=0.02)
    assert sum(r.impact["refs"]["flips"] for r in robustness.values()) == 31
    assert sum(r.impact["cut"]["flips"] for r in robustness.values()) == 17
    assert sum(r.impact["undetermined"]["flips"] for r in robustness.values()) == 0
    again = {k: GeneRobustness.model_validate(v.model_dump()) for k, v in robustness.items()}
    assert again == robustness
