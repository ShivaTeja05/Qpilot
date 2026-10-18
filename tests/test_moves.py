"""Distance to a different conclusion: closed-form updates, search and exactness."""

from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

from qsim import influence, moves
from qsim.data import load_study
from qsim.designs import defensible_cells
from qsim.engine import Engine
from qsim.study_space import space_for


@pytest.fixture(scope="module")
def setup():
    study = load_study()
    space, _ = space_for(study)
    engine = Engine(study, space)
    cells = defensible_cells(space)
    grid = engine.run(cells)
    return engine, cells, grid, moves.fewest_moves(engine, cells, grid.call)


def test_leaving_out_one_sample_matches_the_engine(setup):
    engine, cells, _, _ = setup
    space = engine.space
    rng = np.random.default_rng(3)
    for test in ("welch", "student", "mann_whitney"):
        cell = space.to_index({"test": test, "late_cq": "cq35"})
        c = moves.Cell(engine, cell)
        for g in rng.choice(len(engine.items), 4, replace=False):
            rows, v, in_a = c.gene(g)
            diff, p = moves.remove_each(v, in_a, c.test)
            for k in rng.choice(len(rows), 3, replace=False):
                drop = np.zeros(engine.study.cq.shape, bool)
                drop[rows[k], :] = True
                res = engine.evaluate(cell, drop=drop)
                assert diff[k] == pytest.approx(res["log2fc"][g], abs=1e-9)
                assert p[k] == pytest.approx(res["p"][g], rel=1e-7, abs=1e-14)


def test_mann_whitney_update_handles_ties():
    rng = np.random.default_rng(5)
    v = rng.integers(0, 6, 25).astype(float)  # many ties
    in_a = np.arange(25) < 11
    _, p = moves.remove_each(v, in_a, "mwu")
    for k in range(25):
        keep = np.arange(25) != k
        ref = stats.mannwhitneyu(
            v[keep & in_a], v[keep & ~in_a], alternative="two-sided", method="asymptotic"
        ).pvalue
        assert p[k] == pytest.approx(ref, rel=1e-9)


def test_groups_keep_two_samples():
    v = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    _, p = moves.remove_each(v, np.array([True, True, False, False, False]), "welch")
    assert np.isnan(p[:2]).all() and np.isfinite(p[2:]).all()


def test_one_move_agrees_with_choices_and_single_samples(setup):
    engine, cells, grid, mv = setup
    base = grid.call[grid.row_of(engine.space.baseline_index())]
    dist = (cells != np.array(engine.space.baseline_index())).sum(axis=1)
    by_choice = (grid.call[dist == 1] != base).any(axis=0)
    loo = influence.leave_one_out(engine)
    by_sample = np.isin(engine.items, loo.loc[loo["flips"], "gene"].unique())
    expected = set(np.array(engine.items)[by_choice | by_sample])
    assert set(mv.index[mv["moves_to_flip"] == 1]) == expected


def test_paths_are_verified_and_exact_below_the_frontier(setup):
    _, _, _, mv = setup
    found = mv[mv["moves_to_flip"].notna()]
    assert found["moves_verified"].all()
    assert moves._frontier(366) == 3 and moves._frontier(12) > moves.MAX_MOVES
    assert found.loc[found["moves_to_flip"] <= 3, "moves_exact"].all()
    assert not found.loc[found["moves_to_flip"] == 4, "moves_exact"].any()


def test_a_hand_checked_two_sample_path(setup):
    engine, _, grid, mv = setup
    gene = "PDE4DIP"
    g = engine.items.index(gene)
    row = mv.loc[gene]
    assert row["moves_to_flip"] == 2 and row["moves_choices"] == 0
    samples = [p.removeprefix("leave out sample ") for p in row["moves_path"].split("; ")]
    drop = np.zeros(engine.study.cq.shape, bool)
    for s in samples:
        drop[engine.study.samples.index(s), :] = True
    base = engine.evaluate(engine.space.baseline_index())["call"][g]
    assert base != 0
    assert engine.evaluate(engine.space.baseline_index(), drop=drop)["call"][g] == 0


def test_search_is_deterministic(setup):
    engine, cells, grid, mv = setup
    again = moves.fewest_moves(engine, cells, grid.call, genes=["NM23A", "DDC", "MRPL3"])
    for gene in again.index:
        assert again.loc[gene].equals(mv.loc[gene])
