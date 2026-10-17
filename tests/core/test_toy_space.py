from qpilot.schemas import DecisionSpace
from tests.core.toy_space import ToySpace


def test_toy_space_matches_protocol():
    space: DecisionSpace = ToySpace()
    assert set(space.primary) == set(space.dimensions)
    out = space.evaluate(space.primary)
    assert set(out) == set(space.items)
    assert [space.conclude(out[g]) for g in space.items] == ["up", "up", "down"]


def test_toy_space_flips():
    space = ToySpace()
    assert space.evaluate({"a": 1, "b": "x"})["g2"].conclusion == "none"
    assert space.evaluate({"a": 0, "b": "y"})["g3"].conclusion == "none"
    assert space.evaluate({"a": 2, "b": "y"})["g1"].conclusion == "up"
