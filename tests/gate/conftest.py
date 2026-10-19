import pytest

from qpilot.core.store import StudyStore


@pytest.fixture
def store(tmp_studies_dir) -> StudyStore:
    return StudyStore(tmp_studies_dir)


@pytest.fixture
def study(store, fixture_result, fixture_cards) -> str:
    """The fixture study written into a throwaway workspace; returns its study id."""
    store.put(fixture_result, fixture_cards)
    return fixture_result.study_id
