"""Studio's model default: a local model unless the scientist names a provider."""

import pytest

from qpilot.ai.client import ModelClient, ModelUnavailable
from qpilot.ai.config import (
    STUDIO_DEFAULT_MODEL,
    STUDIO_LOCAL_ENDPOINT,
    ModelConfig,
    is_remote,
    studio_config,
)


def test_the_default_is_the_local_endpoint_and_qwen():
    config = studio_config({})
    assert config.provider == "openai_compatible"
    assert config.endpoint == STUDIO_LOCAL_ENDPOINT == "http://127.0.0.1:11434/v1"
    assert config.model == STUDIO_DEFAULT_MODEL == "qwen2.5:7b"
    assert config.api_key is None and not is_remote(config)


def test_the_studio_model_and_a_local_endpoint_can_be_changed():
    config = studio_config(
        {"QPILOT_STUDIO_MODEL": "llama3.2:3b", "QPILOT_MODEL_ENDPOINT": "http://localhost:8080"}
    )
    assert config.model == "llama3.2:3b" and config.endpoint == "http://localhost:8080"
    assert not is_remote(config)


def test_a_key_is_not_sent_on_the_default_path():
    assert studio_config({"QPILOT_API_KEY": "sk-secret"}).api_key is None


@pytest.mark.parametrize(
    ("env", "provider", "remote"),
    [
        ({"QPILOT_MODEL_PROVIDER": "none"}, "none", False),
        ({"QPILOT_MODEL_PROVIDER": "anthropic", "QPILOT_MODEL_NAME": "m"}, "anthropic", True),
        (
            {
                "QPILOT_MODEL_PROVIDER": "openai_compatible",
                "QPILOT_MODEL_ENDPOINT": "https://llm.example.com/v1",
                "QPILOT_MODEL_NAME": "m",
            },
            "openai_compatible",
            True,
        ),
    ],
)
def test_an_explicit_provider_is_honoured_exactly(env, provider, remote):
    config = studio_config(env)
    assert config == ModelConfig.from_env(env)
    assert config.provider == provider and is_remote(config) is remote


def test_a_remote_endpoint_needs_the_provider_named():
    with pytest.raises(ValueError, match="remote model only when"):
        studio_config({"QPILOT_MODEL_ENDPOINT": "https://llm.example.com/v1"})


def test_an_unknown_provider_is_an_error():
    with pytest.raises(ValueError):
        studio_config({"QPILOT_MODEL_PROVIDER": "somewhere"})


def test_reads_os_environ_by_default(monkeypatch):
    monkeypatch.setenv("QPILOT_STUDIO_MODEL", "qwen2.5:14b")
    assert studio_config().model == "qwen2.5:14b"
    monkeypatch.setenv("QPILOT_MODEL_PROVIDER", "none")
    assert studio_config().provider == "none"


@pytest.mark.filterwarnings("ignore:A test tried to use socket")
def test_offline_the_default_client_fails_fast_and_raises_unavailable():
    from pytest_socket import disable_socket, enable_socket

    disable_socket(allow_unix_socket=True)
    try:
        client = ModelClient(config=studio_config({}))
        assert client.available
        with pytest.raises(ModelUnavailable):
            client.complete("s", [{"role": "user", "content": "x"}], max_tokens=1)
        assert client.ping() is False
    finally:
        enable_socket()
