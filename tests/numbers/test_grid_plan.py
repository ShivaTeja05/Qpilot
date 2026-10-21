"""Core: cell cap with seeded sampling, axis screening, fragility by axis (add_plan 1.6)."""

import pytest

from qpilot.core import robustness as rb
from tests.core.toy_space import ToySpace


class WideSpace(ToySpace):
    """ToySpace with a third, inert dimension ``c`` (5 options): 30 cells."""

    def __init__(self) -> None:
        super().__init__()
        self.dimensions["c"] = [0, 1, 2, 3, 4]
        self.primary["c"] = 0


def test_no_cap_is_the_full_product():
    space = WideSpace()
    assert rb.run_grid(space).equals(rb.run_grid(space, max_cells=30))
    plan = rb.grid_plan(space, max_cells=30)
    assert plan == {
        "dimensions": ["a", "b", "c"],
        "full_product": 30,
        "n_cells": 30,
        "sampled": False,
        "max_cells": 30,
        "seed": None,
    }


def test_cap_keeps_primary_and_one_at_a_time_cells():
    space = WideSpace()
    full = rb.run_grid(space)
    capped = rb.run_grid(space, max_cells=12, seed=3)
    n = len(capped) // len(space.items)
    assert n == 12 == rb.grid_plan(space, max_cells=12, seed=3)["n_cells"]
    # 1 primary + 2 (a) + 1 (b) + 4 (c) = 8 mandatory cells, then 4 sampled
    for item in space.items:
        assert rb.impact_per_dimension(capped, space, item) == rb.impact_per_dimension(
            full, space, item
        )
        assert (
            rb.primary_row(capped, space, item)["conclusion"]
            == (rb.primary_row(full, space, item)["conclusion"])
        )
    idx = capped[[f"{d}__idx" for d in space.dimensions]].drop_duplicates()
    assert idx.equals(idx.sort_values(list(idx.columns)))  # still in product order
    assert rb.run_grid(space, max_cells=12, seed=3).equals(capped)  # seeded: deterministic
    assert not rb.run_grid(space, max_cells=12, seed=4).equals(capped)


def test_cap_below_the_mandatory_cells_still_keeps_them():
    space = WideSpace()
    capped = rb.run_grid(space, max_cells=2)
    assert len(capped) // len(space.items) == 8


def test_screen_axis():
    space = WideSpace()
    inert = rb.screen_axis(space, "c")
    assert not inert.admitted and inert.max_delta_log2fc == 0.0
    assert inert.flipped == {"1": (), "2": (), "3": (), "4": ()}
    a = rb.screen_axis(space, "a")
    assert a.admitted and a.flipped["1"] == ("g2",)
    assert a.as_dict()["flipped"]["2"] == ["g2"]
    small = rb.screen_axis(space, "a", options=[0], min_log2fc=0.5)
    assert not small.admitted and small.flipped == {}


def test_fragility_by_axis():
    space = ToySpace()
    grid = rb.run_grid(space)
    out = rb.fragility_by_axis(grid, space)
    assert list(out) == space.items
    assert out["g1"]["rests_on"] == [] and out["g1"]["holds"] == 1.0
    assert out["g2"]["rests_on"] == ["a"]
    assert out["g2"]["by_axis"]["a"]["flipping_options"] == ["1", "2"]
    assert out["g3"]["rests_on"] == ["b"] and out["g3"]["min_flip_changes"] == 1
    assert out["g3"]["by_axis"]["b"]["max_delta_log2fc"] == pytest.approx(1.1)
    assert out["g3"]["by_axis"]["a"] == {
        "flips": False,
        "flips_anywhere": False,
        "max_delta_log2fc": 0.0,
        "flipping_options": [],
    }
    summary = rb.summary(grid, space)
    for item, fragile in out.items():
        assert fragile["holds"] == summary[item].holds
        for name in space.dimensions:
            assert fragile["by_axis"][name]["flips"] == summary[item].impact[name]["flips"]
