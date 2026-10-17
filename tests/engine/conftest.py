"""Engine test fixtures: the analysed 64-plate demo study, computed once per test session."""

import pytest

from qpilot.io.datasets import VERMEULEN_FILENAME, default_cache_dir


@pytest.fixture(scope="session")
def demo_curves():
    """Per-well table for the demo study (uses the curve cache after the first run)."""
    from qpilot.qpcr.curves import analyse_study

    path = default_cache_dir() / VERMEULEN_FILENAME
    if not path.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    return analyse_study(path)


@pytest.fixture(scope="session")
def demo_matrix(demo_curves):
    """Samples x genes log2(n0) matrix for the demo study."""
    from qpilot.qpcr.quant import log2_matrix

    return log2_matrix(demo_curves)
