"""The normaliser axis: NormFinder's / geNorm's best pair and the global mean, opt-in."""

import numpy as np
import pandas as pd
import pytest

from qpilot.core import robustness as rb
from qpilot.qpcr.axes import AxisError
from qpilot.qpcr.axes import normaliser as norm_axis
from qpilot.qpcr.contrast import welch
from qpilot.qpcr.design import GroupSpec
from qpilot.qpcr.refgenes import genorm
from qpilot.qpcr.space import QpcrSpace
from tests.numbers.conftest import toy_matrix

REFS = ("R1", "R2", "R3")


def test_global_mean_is_the_plain_mean_when_nothing_is_missing():
    matrix = toy_matrix().dropna()
    genes = norm_axis.global_mean_genes(matrix)
    assert genes == tuple(matrix.columns)
    got = norm_axis.global_mean(matrix, genes)
    plain = matrix.mean(axis=1)
    assert (got - plain).std() == pytest.approx(0.0, abs=1e-12)  # a constant that cancels


def test_global_mean_weighs_each_gene_equally_with_missing_values():
    matrix = pd.DataFrame(
        {"A": [0.0, 2.0, np.nan], "B": [10.0, 10.0, 16.0]}, index=["u1", "u2", "u3"]
    )
    got = norm_axis.global_mean(matrix, ["A", "B"])
    # centred: A -1, 1, NaN; B -2, -2, 4 -> means -1.5, -0.5, 4 (u3 keeps B alone)
    assert got.tolist() == pytest.approx([-1.5, -0.5, 4.0])
    nothing = matrix.assign(A=np.nan, B=np.nan)
    assert norm_axis.global_mean(nothing, ["A", "B"]).isna().all()


def _plan(matrix, primary=REFS, offered=norm_axis.OPTIONS):
    stability = genorm(matrix, list(REFS))
    groups = {u: ("hi" if i % 2 else "lo") for i, u in enumerate(matrix.index)}
    return norm_axis.plan(matrix, REFS, stability, primary, groups, offered)


def test_plan_says_why_an_option_does_not_apply():
    matrix = toy_matrix()
    plan = _plan(matrix)
    assert plan.options[0] == "planned"
    assert "global_mean" not in plan.options
    assert plan.unavailable["global_mean"].startswith("only 6 genes are measured")
    assert str(norm_axis.GLOBAL_MEAN_MIN_GENES) in plan.unavailable["global_mean"]
    assert "own default" in plan.evidence["global_mean"]["threshold_note"]
    nf = plan.normfinder.best_pair
    assert plan.refs["normfinder_pair"] == tuple(g for g in REFS if g in nf)
    if set(plan.genorm_pair) == set(nf):
        assert "NormFinder's best pair too" in plan.unavailable["genorm_pair"]
    # a best pair that is the set in use is not offered again
    same = _plan(matrix, primary=nf)
    assert "already uses" in same.unavailable["normfinder_pair"]


def test_fewer_than_three_candidates_offer_no_pair():
    matrix = toy_matrix()[["R1", "R2", "M", "UP"]]
    stability = genorm(toy_matrix(), list(REFS))  # any result; the candidates decide
    plan = norm_axis.plan(matrix, ("R1", "R2"), stability, ("R1", "R2"), None)
    assert "at least 3" in plan.unavailable["normfinder_pair"]
    assert "at least three" in plan.unavailable["genorm_pair"]
    assert plan.options == ("planned",)


def _space(matrix, options=("planned", "pair", "global"), **kwargs):
    genes = tuple(matrix.columns)

    def source(option, block):
        if option == "pair":
            return block[["R1", "R2"]].to_numpy(dtype=float)
        return norm_axis.global_mean(block, genes).to_numpy(dtype=float)[:, None]

    return QpcrSpace(
        matrix,
        genorm(matrix, list(REFS)),
        GroupSpec(marker="M", cut=0.15),
        candidates=REFS,
        normaliser=list(options),
        normaliser_source=source,
        **kwargs,
    )


def test_options_must_start_with_planned_and_need_a_source():
    matrix = toy_matrix()
    with pytest.raises(AxisError, match="start with 'planned'"):
        _space(matrix, ("pair", "planned"))
    with pytest.raises(AxisError, match="normaliser_source"):
        QpcrSpace(
            matrix,
            genorm(matrix, list(REFS)),
            GroupSpec(marker="M"),
            candidates=REFS,
            normaliser=["planned", "pair"],
        )


def test_the_grid_leaves_out_cells_that_repeat_an_analysis():
    matrix = toy_matrix()
    space = _space(matrix)
    assert list(space.dimensions) == ["refs", "cut", "undetermined", "normaliser"]
    # 7 control-gene sets x 3 cut-offs x 2 rules, plus 2 other normalisers x 3 x 2
    assert rb.n_cells(space) == 7 * 3 * 2 + 2 * 3 * 2
    grid = rb.run_grid(space)
    assert len(grid) == rb.n_cells(space) * len(space.items)
    other = grid[grid["normaliser"] != "planned"]
    assert set(other["refs"].map(tuple)) == {tuple(space.primary["refs"])}
    summary = rb.summary(grid, space)
    assert {s.n_cells for s in summary.values()} == {rb.n_cells(space)}
    sampled = rb.run_grid(space, max_cells=20)
    refs = sampled[sampled["normaliser"] != "planned"]["refs"].map(tuple)
    assert set(refs) == {tuple(space.primary["refs"])}


def test_a_global_mean_cell_divides_by_the_global_mean():
    matrix = toy_matrix()
    space = _space(matrix)
    cell = {**space.primary, "normaliser": "global"}
    got = space.evaluate(cell)["UP"]
    normaliser = norm_axis.global_mean(matrix, tuple(matrix.columns))
    relative = (matrix["UP"] - normaliser).dropna()
    high, rest = space.groups(0.15)
    w = welch(relative[relative.index.isin(high)], relative[relative.index.isin(rest)])
    assert got.log2fc == pytest.approx(w.diff, rel=1e-12)
    assert got.p == pytest.approx(w.p, rel=1e-9)
    values, refs = space.cell_arrays(cell)
    assert refs.shape == (len(matrix), 1)  # one column: the global mean itself
    assert space.evaluate_with(cell)["UP"] == got
    assert space.normaliser_label(cell) == "global"  # not a catalogue id: its own text
    assert space.normaliser_label(space.primary) == ", ".join(space.primary["refs"])


def test_planned_is_exactly_the_space_without_the_axis():
    matrix = toy_matrix()
    plain = QpcrSpace(
        matrix, genorm(matrix, list(REFS)), GroupSpec(marker="M", cut=0.15), candidates=REFS
    )
    space = _space(matrix)
    for cell in rb.cells(plain):
        assert space.evaluate({**cell, "normaliser": "planned"}) == plain.evaluate(cell)
    held = _space(matrix, ("planned",))
    assert "normaliser" not in held.dimensions
    assert held.axes["normaliser"].status == "single_option"
