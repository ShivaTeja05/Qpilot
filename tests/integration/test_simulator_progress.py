"""The audit's full grid is counted as it runs (perf, excellence round): no qsim needed."""

from qpilot.integration.simulator import _count_grid


class Engine:
    def evaluate(self, cell, drop=None):
        return {"cell": cell}


def test_every_hundredth_analysis_is_told_and_nothing_else_changes():
    engine = Engine()
    told: list[tuple[int, int]] = []
    _count_grid(engine, 1000, lambda done, total: told.append((done, total)))
    out = [engine.evaluate((i,)) for i in range(1000)]
    assert out[5] == {"cell": (5,)}  # the engine's answers are passed on unchanged
    assert told[0] == (10, 1000) and told[-1] == (1000, 1000) and len(told) == 100
    # Later stages (dropped wells) and anything past the grid are not counted.
    engine.evaluate((1,), drop=[1])
    engine.evaluate((2,))
    assert told[-1] == (1000, 1000) and len(told) == 100


def test_a_small_grid_is_told_at_every_analysis():
    engine = Engine()
    told: list[int] = []
    _count_grid(engine, 7, lambda done, total: told.append(done))
    for i in range(7):
        engine.evaluate((i,))
    assert told == [1, 2, 3, 4, 5, 6, 7]
