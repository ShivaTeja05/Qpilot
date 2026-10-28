"""Task 7 gate: the decision space equals the scalar contrast and reproduces the oracle grid."""

import itertools

import numpy as np
import pandas as pd
import pytest

from qpilot.qpcr.contrast import welch_contrast
from qpilot.qpcr.curves import REFERENCE_TARGETS
from qpilot.qpcr.design import GroupSpec
from qpilot.qpcr.refgenes import genorm
from qpilot.qpcr.space import QpcrSpace, ref_subsets
from tests.timing import work_time


def _assert_same(vectorised, scalar):
    assert vectorised.target == scalar.target
    for field in ("log2fc", "fc", "p", "t"):
        assert getattr(vectorised, field) == pytest.approx(getattr(scalar, field), rel=1e-9)
    assert vectorised.ci == pytest.approx(scalar.ci, rel=1e-9)
    assert (vectorised.n_hi, vectorised.n_lo) == (scalar.n_hi, scalar.n_lo)
    assert vectorised.conclusion == scalar.conclusion


# ---------- small synthetic study (runs in CI) ----------


@pytest.fixture
def toy():
    rng = np.random.default_rng(7)
    n = 60
    base = rng.normal(10, 1.5, n)
    marker = rng.normal(0, 1, n)
    matrix = pd.DataFrame(
        {
            "R1": base + rng.normal(0, 0.3, n),
            "R2": base + rng.normal(0, 0.5, n),
            "R3": base + rng.normal(0, 0.9, n),
            "M": base + marker * 2,
            "UP": base + marker * 1.5 + rng.normal(0, 0.5, n),
            "FLAT": base + rng.normal(0, 0.5, n),
        },
        index=[f"s{i:02d}" for i in range(n)],
    )
    matrix.loc["s03", "UP"] = np.nan  # one undetermined well
    matrix.loc["s05", "R2"] = np.nan  # one sample missing a control gene
    gn = genorm(matrix, ["R1", "R2", "R3"])
    space = QpcrSpace(matrix, gn, GroupSpec(marker="M", cut=0.15), candidates=("R1", "R2", "R3"))
    return matrix, space


def test_ref_subsets_are_every_non_empty_subset():
    subsets = ref_subsets(("a", "b", "c"))
    assert subsets == [("a",), ("b",), ("c",), ("a", "b"), ("a", "c"), ("b", "c"), ("a", "b", "c")]
    assert len(ref_subsets(REFERENCE_TARGETS)) == 31


def test_dimensions_items_and_primary(toy):
    _, space = toy
    assert len(space.dimensions["refs"]) == 7
    assert space.dimensions["cut"] == [0.10, 0.15, 0.20]
    assert space.dimensions["undetermined"] == ["drop", "cap"]
    assert space.items == ["UP", "FLAT"]  # control genes and the marker are not items
    assert space.primary["cut"] == 0.15 and space.primary["undetermined"] == "drop"
    assert space.primary["refs"] in space.dimensions["refs"]


def test_every_cell_equals_the_scalar_contrast(toy):
    matrix, space = toy
    for refs, cut, undetermined in itertools.product(*space.dimensions.values()):
        cell = {"refs": refs, "cut": cut, "undetermined": undetermined}
        high, rest = space.groups(cut)
        results = space.evaluate(cell)
        for gene in space.items:
            scalar = welch_contrast(matrix, gene, refs, undetermined, high, rest)
            _assert_same(results[gene], scalar)


def test_groups_come_from_primary_refs_not_the_cell(toy):
    _, space = toy
    a = space.evaluate({"refs": ("R1",), "cut": 0.15, "undetermined": "drop"})["FLAT"]
    b = space.evaluate({"refs": ("R3",), "cut": 0.15, "undetermined": "drop"})["FLAT"]
    # Neither R1 nor R3 is missing anywhere and FLAT has no empty wells, so with groups fixed
    # from the primary refs both cells compare exactly the same samples.
    assert (a.n_hi, a.n_lo) == (b.n_hi, b.n_lo)
    assert a.log2fc != b.log2fc  # only the normaliser changed


def test_conclude_matches_result(toy):
    _, space = toy
    for result in space.evaluate(space.primary).values():
        assert space.conclude(result) == result.conclusion


def test_bad_inputs_are_refused(toy):
    matrix, space = toy
    with pytest.raises(ValueError, match="not in the matrix"):
        QpcrSpace(matrix, genorm(matrix, ["R1", "R2", "R3"]), candidates=("R1", "R2", "NOPE"))
    with pytest.raises(ValueError, match="undetermined"):
        space.evaluate({"refs": ("R1",), "cut": 0.15, "undetermined": "zero"})


# ---------- the demo study ----------


@pytest.fixture(scope="module")
def demo_space(demo_matrix):
    return QpcrSpace(demo_matrix, genorm(demo_matrix, REFERENCE_TARGETS))


@pytest.mark.demo_data
def test_demo_space_shape(demo_space):
    assert len(demo_space.dimensions["refs"]) == 31
    assert len(demo_space.items) == 58
    assert "MYCN(4)" not in demo_space.items
    assert not set(REFERENCE_TARGETS) & set(demo_space.items)
    assert demo_space.primary["refs"] == REFERENCE_TARGETS
    assert len(demo_space.groups(0.15)[0]) == 53


@pytest.mark.demo_data
def test_demo_primary_and_single_ref_cells(demo_space):
    primary = demo_space.evaluate(demo_space.primary)
    assert primary["ODC1"].fc == pytest.approx(3.59, abs=0.1)
    assert primary["NM23A"].conclusion == "up"
    hmbs = demo_space.evaluate({**demo_space.primary, "refs": ("HMBS",)})
    assert hmbs["ODC1"].fc == pytest.approx(2.66, abs=0.1)
    assert hmbs["NM23A"].conclusion == "none"


@pytest.mark.demo_data
def test_demo_cells_equal_scalar_contrast(demo_space, demo_matrix):
    for cell in (
        demo_space.primary,
        {"refs": ("UBC(2)",), "cut": 0.10, "undetermined": "cap"},
        {"refs": ("ALUsq(Eurogentec)", "HPRT1"), "cut": 0.20, "undetermined": "drop"},
    ):
        high, rest = demo_space.groups(cell["cut"])
        results = demo_space.evaluate(cell)
        for gene in ("ODC1", "NTRK1", "NM23A", "PLAT", "BIRC5"):
            scalar = welch_contrast(
                demo_matrix, gene, cell["refs"], cell["undetermined"], high, rest
            )
            _assert_same(results[gene], scalar)


@pytest.mark.demo_data
def test_demo_full_sweep_reproduces_oracle_grid(demo_space):
    """186 cells; holds and per-dimension flips as in the locked plan (the core will own this)."""
    cells = [
        dict(zip(demo_space.dimensions, combo, strict=True))
        for combo in itertools.product(*demo_space.dimensions.values())
    ]
    with work_time() as spent:
        grid = [(cell, demo_space.evaluate(cell)) for cell in cells]
    assert len(grid) == 186
    assert spent.seconds < 5, f"full sweep took {spent}"

    primary = demo_space.evaluate(demo_space.primary)

    def holds(gene):
        base = primary[gene].conclusion
        return sum(results[gene].conclusion == base for _, results in grid) / len(grid)

    assert holds("ODC1") == 1.0 and holds("BIRC5") == 1.0 and holds("NTRK1") == 1.0
    assert holds("NM23A") == pytest.approx(0.645, abs=0.02)
    assert holds("PLAT") == pytest.approx(0.973, abs=0.02)
    assert sum(holds(g) < 0.80 for g in demo_space.items) == 17

    def flips(dimension):
        others = [d for d in demo_space.dimensions if d != dimension]
        varied = [
            results
            for cell, results in grid
            if all(cell[d] == demo_space.primary[d] for d in others)
        ]
        return sum(
            any(r[g].conclusion != primary[g].conclusion for r in varied) for g in demo_space.items
        )

    assert (flips("refs"), flips("cut"), flips("undetermined")) == (31, 17, 0)
