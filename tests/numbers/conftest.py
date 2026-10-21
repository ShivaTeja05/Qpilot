"""Shared fixtures for the honest-numbers tests: a small synthetic study and the demo study."""

import numpy as np
import pandas as pd
import pytest

from qpilot.qpcr.design import GroupSpec
from qpilot.qpcr.refgenes import genorm
from qpilot.qpcr.space import QpcrSpace


def toy_matrix(seed: int = 7, n: int = 60) -> pd.DataFrame:
    """Units x genes log2 quantities: three control genes, a marker and two targets."""
    rng = np.random.default_rng(seed)
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
    matrix.loc["s03", "UP"] = np.nan
    matrix.loc["s05", "R2"] = np.nan
    return matrix


@pytest.fixture
def toy():
    matrix = toy_matrix()
    space = QpcrSpace(
        matrix,
        genorm(matrix, ["R1", "R2", "R3"]),
        GroupSpec(marker="M", cut=0.15),
        candidates=("R1", "R2", "R3"),
    )
    return matrix, space
