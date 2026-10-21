"""The legacy demo grid is byte-identical through the registry; fragility by axis on the demo."""

import hashlib

import pytest

from qpilot.core import robustness as rb
from qpilot.core.store import _grid_csv
from qpilot.qpcr.study import run_study

#: sha256 of grid.csv from `qpilot run` on main @ 81484f7 (186 cells x 58 genes).
LEGACY_GRID_SHA256 = "2ef579ff8aa85d4b25da03fdc5491791bcede93be7ff099729731fd2f4e116b1"


@pytest.fixture(scope="module")
def demo(request):
    path = request.getfixturevalue("demo_rdml_path")
    return run_study(path)


@pytest.fixture(scope="module")
def demo_rdml_path():
    from tests.conftest import DEMO_RDML

    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    return DEMO_RDML


@pytest.mark.demo_data
def test_legacy_grid_is_byte_identical(demo):
    result, _, grid = demo
    assert hashlib.sha256(_grid_csv(grid).encode()).hexdigest() == LEGACY_GRID_SHA256
    assert len(grid) == 186 * 58
    assert result.contrasts["ODC1"].fc == pytest.approx(3.59, abs=0.01)


@pytest.mark.demo_data
def test_demo_fragility_by_axis(demo):
    from qpilot.qpcr.curves import analyse_study
    from qpilot.qpcr.study import StudySettings, build_model
    from tests.conftest import DEMO_RDML

    result, _, grid = demo
    space = build_model(analyse_study(DEMO_RDML, "biomarker_set"), StudySettings()).space
    out = rb.fragility_by_axis(grid, space)
    assert out["NM23A"]["rests_on"] == ["refs", "cut"]
    assert out["NM23A"]["holds"] == pytest.approx(0.645, abs=0.001)
    assert out["ODC1"]["rests_on"] == []
    assert sum("refs" in g["rests_on"] for g in out.values()) == 31
    assert sum("cut" in g["rests_on"] for g in out.values()) == 17
    assert sum("undetermined" in g["rests_on"] for g in out.values()) == 0
    for gene, fragile in out.items():
        assert fragile["min_flip_changes"] == result.confidence[gene].min_flip_changes
