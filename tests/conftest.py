"""Shared pytest fixtures: the T0 contract fixtures and the cached demo dataset.

Owned by Dev 1. Both developers' tests use these; do not change their names or return types.
"""

import atexit
import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from qpilot.io.datasets import (
    BENCHMARK_TABLES,
    VERMEULEN_FILENAME,
    VERMEULEN_SHA256,
    default_cache_dir,
)
from qpilot.schemas import DecisionCard, Fact, StudyResult

FIXTURES = Path(__file__).parent / "fixtures"


def _private_cache() -> None:
    """Give this test run a cache of its own (``QPILOT_CACHE_DIR``), holding the demo's files.

    The shared cache (``~/.cache/qpilot``) is written by every run on the machine: other
    branches' engines leave curve tables there, keyed by file and settings only, and a test that
    reads one sees another engine's answer (a Cq table read as analysed, a note gone). Here the
    demo dataset, its published tables and the demo's own curve tables are linked in (read, never
    written, by the tests), and every other file's tables are built afresh by this run's engine.
    ``QPILOT_TEST_SHARED_CACHE=1`` keeps the shared cache. Removed when the run ends.
    """
    if os.environ.get("QPILOT_TEST_SHARED_CACHE") == "1":
        return
    shared = default_cache_dir()
    private = Path(tempfile.mkdtemp(prefix="qpilot-test-cache-"))
    atexit.register(shutil.rmtree, private, ignore_errors=True)
    names = {VERMEULEN_FILENAME, *(t.filename for t in BENCHMARK_TABLES.values())}
    if shared.is_dir():
        for path in shared.iterdir():
            demo = path.name in names or path.name.startswith(f"{VERMEULEN_SHA256}.")
            if not (demo and path.is_file()):
                continue
            try:
                os.link(path, private / path.name)
            except OSError:  # another volume: a copy holds the same bytes
                shutil.copy2(path, private / path.name)
    os.environ["QPILOT_CACHE_DIR"] = str(private)


_private_cache()
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
