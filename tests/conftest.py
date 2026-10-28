"""Shared pytest fixtures: the T0 contract fixtures and the cached demo dataset.

Owned by Dev 1. Both developers' tests use these; do not change their names or return types.
"""

import json
from pathlib import Path

import pytest

from qpilot.io.datasets import VERMEULEN_FILENAME, default_cache_dir
from qpilot.schemas import DecisionCard, Fact, StudyResult

FIXTURES = Path(__file__).parent / "fixtures"
DEMO_RDML = default_cache_dir() / VERMEULEN_FILENAME  # honours $QPILOT_CACHE_DIR


@pytest.fixture
def fixtures_dir() -> Path:
    """Directory holding the contract fixtures and small RDML files."""
    return FIXTURES


@pytest.fixture
def fixture_result() -> StudyResult:
    """The demo study's results as the engine will produce them."""
    return StudyResult.model_validate_json((FIXTURES / "results.json").read_text(encoding="utf-8"))


@pytest.fixture
def fixture_cards() -> list[DecisionCard]:
    """The demo study's three Decision Cards."""
    raw = json.loads((FIXTURES / "cards.json").read_text(encoding="utf-8"))
    return [DecisionCard.model_validate(card) for card in raw]


@pytest.fixture
def fixture_facts() -> dict[str, Fact]:
    """Every number prose may reference, keyed by fact id."""
    raw = json.loads((FIXTURES / "facts.json").read_text(encoding="utf-8"))
    return {fid: Fact.model_validate(value) for fid, value in raw.items()}


@pytest.fixture
def smoke_rdml() -> Path:
    """A small real RDML file that needs no download."""
    return FIXTURES / "test_mca_1_raw_data.rdml"


@pytest.fixture
def demo_rdml_path() -> Path:
    """The cached 64-plate demo dataset; skips the test when it has not been fetched."""
    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    return DEMO_RDML


@pytest.fixture
def tmp_studies_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A throwaway QPILOT_STUDIES_DIR so store tests never touch the real cache."""
    studies = tmp_path / "studies"
    studies.mkdir()
    monkeypatch.setenv("QPILOT_STUDIES_DIR", str(studies))
    return studies


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip ``demo_data`` tests automatically when the dataset is not cached."""
    if DEMO_RDML.exists():
        return
    skip = pytest.mark.skip(reason="demo dataset not cached; run `qpilot fetch-demo`")
    for item in items:
        if "demo_data" in item.keywords:
            item.add_marker(skip)
