"""Which language model (if any) the scientist chose: provider, endpoint, model name, key.

Read from the environment (``QPILOT_MODEL_PROVIDER``, ``QPILOT_MODEL_ENDPOINT``,
``QPILOT_MODEL_NAME``, ``QPILOT_API_KEY``) or set from the app. The default provider is
``none``: qPilot is fully usable with templates only. Model names are never hard-coded.

qPilot Studio has its own default (:func:`studio_config`): a model on this machine. With
``QPILOT_MODEL_PROVIDER`` unset, Studio asks the local OpenAI-compatible endpoint
(``http://127.0.0.1:11434/v1``, Ollama's) for ``QPILOT_STUDIO_MODEL`` or ``qwen2.5:7b``. A
remote provider is used only when the scientist sets ``QPILOT_MODEL_PROVIDER`` to it, and then
sample names are pseudonymised before anything leaves (:func:`is_remote`). An unreachable local
server costs one refused connection: the call raises ``ModelUnavailable`` and the interpreter
falls back to qPilot's rules. A slow one is bounded by the interpreter's time budget
(:func:`interpret_budget_s`, ``QPILOT_INTERPRET_BUDGET_S``): when it runs out, the rules answer
for the parts of the file the model has not read.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, Field, SecretStr

Provider = Literal["none", "anthropic", "openai_compatible"]
STUDIO_LOCAL_ENDPOINT = "http://127.0.0.1:11434/v1"
STUDIO_DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_INTERPRET_BUDGET_S = 180.0


class ModelConfig(BaseModel):
    """A model choice. ``api_key`` is a secret and never printed or logged."""

    provider: Provider = "none"
    endpoint: str | None = None
    model: str | None = None
    api_key: SecretStr | None = Field(default=None, repr=False)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ModelConfig:
        """Build the config from ``QPILOT_MODEL_*`` and ``QPILOT_API_KEY``."""
        env = os.environ if env is None else env
        provider = (env.get("QPILOT_MODEL_PROVIDER") or "none").strip().lower()
        if provider not in ("none", "anthropic", "openai_compatible"):
            raise ValueError("QPILOT_MODEL_PROVIDER must be none, anthropic or openai_compatible")
        key = env.get("QPILOT_API_KEY")
        return cls(
            provider=provider,  # type: ignore[arg-type]
            endpoint=env.get("QPILOT_MODEL_ENDPOINT") or None,
            model=env.get("QPILOT_MODEL_NAME") or None,
            api_key=SecretStr(key) if key else None,
        )

    def describe(self) -> dict[str, str | None]:
        """What may be shown or logged about this config (never the key)."""
        return {
            "provider": self.provider,
            "endpoint": self.endpoint,
            "model": self.model,
            "api_key": "set" if self.api_key else "unset",
        }


def studio_config(env: Mapping[str, str] | None = None) -> ModelConfig:
    """The model qPilot Studio uses: the scientist's explicit choice, else a local one.

    If ``QPILOT_MODEL_PROVIDER`` is set (to anything, ``none`` included) it is honoured exactly,
    as :meth:`ModelConfig.from_env` reads it: a remote provider is only ever used because the
    scientist named it. Otherwise Studio uses the OpenAI-compatible endpoint on this machine,
    ``QPILOT_MODEL_ENDPOINT`` if it is set (it must be local; a remote one needs the provider
    named) or ``http://127.0.0.1:11434/v1``, with the model ``QPILOT_STUDIO_MODEL`` or
    ``qwen2.5:7b``. ``QPILOT_API_KEY`` is not sent on this default path (a key belongs to the
    provider it was configured for).

    Raises:
        ValueError: ``QPILOT_MODEL_PROVIDER`` names an unknown provider, or the provider is
            unset and ``QPILOT_MODEL_ENDPOINT`` is not on this machine.
    """
    env = os.environ if env is None else env
    if (env.get("QPILOT_MODEL_PROVIDER") or "").strip():
        return ModelConfig.from_env(env)
    endpoint = (env.get("QPILOT_MODEL_ENDPOINT") or "").strip() or STUDIO_LOCAL_ENDPOINT
    config = ModelConfig(
        provider="openai_compatible",
        endpoint=endpoint,
        model=(env.get("QPILOT_STUDIO_MODEL") or "").strip() or STUDIO_DEFAULT_MODEL,
    )
    if is_remote(config):
        raise ValueError(
            "QPILOT_MODEL_ENDPOINT is not on this machine; Studio uses a remote model only when "
            "QPILOT_MODEL_PROVIDER names it"
        )
    return config


def is_remote(config: ModelConfig) -> bool:
    """True when a call with ``config`` can leave this machine (then names are pseudonymised).

    The one rule for "this machine" is :func:`qpilot.core.pseudonym.endpoint_is_local`:
    provider ``none``, or an ``openai_compatible`` endpoint on ``localhost`` or a loopback
    address. Everything else, every ``anthropic`` endpoint included, is remote.
    """
    from qpilot.core.pseudonym import endpoint_is_local

    return not endpoint_is_local(config.provider, config.endpoint)


def interpret_budget_s(env: Mapping[str, str] | None = None) -> float:
    """How long the Design Interpreter may keep asking the model about one file, in seconds.

    ``QPILOT_INTERPRET_BUDGET_S`` when it is a positive number, else three minutes. When the
    budget runs out, no further call is started and the rules answer for the rest of the file.
    """
    env = os.environ if env is None else env
    try:
        budget = float((env.get("QPILOT_INTERPRET_BUDGET_S") or "").strip())
    except ValueError:
        return DEFAULT_INTERPRET_BUDGET_S
    return budget if math.isfinite(budget) and budget > 0 else DEFAULT_INTERPRET_BUDGET_S
