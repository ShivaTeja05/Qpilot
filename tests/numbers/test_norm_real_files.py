"""NormFinder, the normaliser plan and the plate check on a real lab file (not the demo).

The K. phaffii LinRegPCR RDML 1.3 (LightCycler 480 II, CC-BY-4.0, ``tests/fixtures/corpus``): six
genes, one per plate, 24 samples (8 conditions x 3). As a person who names ACT1, TFC1 and DOA10
candidate reference genes and compares the 20 °C cultures with the 28 °C ones would see it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qpilot.qpcr import interrun as irc
from qpilot.qpcr.axes import normaliser as norm_axis
from qpilot.qpcr.curves import analyse_study
from qpilot.qpcr.normfinder import normfinder
from qpilot.qpcr.quant import log2_matrix
from qpilot.qpcr.refgenes import genorm
from tests.numbers.test_normfinder import _paper

FILE = Path(
    "tests/fixtures/corpus/rdml/linregpcr-rdml-1.3-lc480-kphaffii/12934_2025_2809_MOESM5_ESM.rdml"
)
CANDIDATES = ["ACT1", "TFC1", "DOA10"]


@pytest.fixture(scope="module")
def curves():
    return analyse_study(FILE, "202502_K_phaffii", ())


def _groups(units):
    return {u: ("20" if "20" in u else "28" if "28" in u else None) for u in units}


def test_normfinder_on_a_real_file_is_the_papers_arithmetic(curves):
    matrix = log2_matrix(curves)
    groups = _groups(matrix.index)
    result = normfinder(matrix, CANDIDATES, groups)
    assert result.groups == {"20": 6, "28": 6} and result.n_units == 12
    assert sum(1 for why in result.left_out.values() if why == "in no group") == 12
    kept = [u for u in matrix.index if groups[u] is not None]
    expected = _paper(matrix.loc[kept], CANDIDATES, {u: groups[u] for u in kept})
    assert result.stability == pytest.approx(expected["rho"], rel=1e-10)
    assert dict(result.pairs) == pytest.approx(expected["pairs"], rel=1e-10)
    assert any("at least 8 samples per group" in w for w in result.warnings)


def test_the_plan_and_the_plates_say_what_does_not_apply(curves):
    matrix = log2_matrix(curves)
    plan = norm_axis.plan(
        matrix, CANDIDATES, genorm(matrix, CANDIDATES), CANDIDATES, _groups(matrix.index)
    )
    assert plan.unavailable["global_mean"].startswith("only 6 genes are measured")
    assert set(plan.options) <= {"planned", "normfinder_pair", "genorm_pair"}
    why = irc.unavailable(curves)
    assert set(why) == {"calibrator", "factor"}
    assert "cancels in every fold change" in why["factor"]
    assert irc.summary(curves)["n_runs"] == 6
