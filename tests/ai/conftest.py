import pytest

from qpilot.ai import payload_log
from qpilot.core.store import StudyStore


@pytest.fixture(autouse=True)
def _no_model_env(monkeypatch):
    for var in ("QPILOT_MODEL_PROVIDER", "QPILOT_MODEL_ENDPOINT", "QPILOT_MODEL_NAME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("QPILOT_API_KEY", raising=False)
    monkeypatch.delenv("QPILOT_LOG_PAYLOAD", raising=False)
    payload_log.clear()


@pytest.fixture
def store(tmp_studies_dir) -> StudyStore:
    return StudyStore(tmp_studies_dir)


@pytest.fixture
def study(store, fixture_result, fixture_cards) -> str:
    store.put(fixture_result, fixture_cards)
    return fixture_result.study_id
