"""Offline by test: the whole headless path runs with every network socket blocked.

This is what backs the claim "nothing leaves the machine" with provider ``none``: open the
study, read the cards, explain one, ask a question, decide, write and verify the record.
"""

import importlib.util

import pytest
from pytest_socket import SocketBlockedError, disable_socket, enable_socket

from qpilot.ai.ask import ask
from qpilot.ai.client import ModelClient, ModelUnavailable, OpenAICompatibleBackend
from qpilot.ai.config import ModelConfig
from qpilot.ai.explain import explain_card
from qpilot.core.decisions import apply_decision
from qpilot.core.record import verify, write_record


@pytest.fixture
def offline():
    disable_socket(allow_unix_socket=True)
    try:
        yield
    finally:
        enable_socket()


def _headless_path(store, study_id, tmp_path):
    cards = store.cards(study_id)
    facts = store.get(study_id).facts
    explanation = explain_card(cards[0], facts, client=ModelClient())
    assert explanation.fallback and explanation.validated
    answer = ask("What is the fold change of ODC1?", store, study_id, client=ModelClient())
    assert answer.validated
    out = apply_decision(store, study_id, cards[0].id, cards[0].recommended, "keep", "human")
    assert out.status == "applied"
    info = write_record(store, study_id, tmp_path / "record")
    assert verify(info.record_dir).ok


@pytest.mark.filterwarnings("ignore:A test tried to use socket")
def test_sockets_really_are_blocked(offline):
    import socket

    with pytest.raises(SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    backend = OpenAICompatibleBackend(
        ModelConfig(provider="openai_compatible", endpoint="http://127.0.0.1:11434", model="m")
    )
    with pytest.raises(ModelUnavailable):
        backend.complete("s", [{"role": "user", "content": "x"}], 5, 0)


def test_fixture_study_offline(offline, store, study, tmp_path):
    _headless_path(store, study, tmp_path)


@pytest.mark.demo_data
def test_demo_study_offline(offline, store, demo_rdml_path, tmp_path):
    if importlib.util.find_spec("qpilot.qpcr.study") is None:
        pytest.skip("qpcr.study (Dev 1) is not on this branch yet")
    study_id = store.ensure_study(demo_rdml_path)
    _headless_path(store, study_id, tmp_path)
