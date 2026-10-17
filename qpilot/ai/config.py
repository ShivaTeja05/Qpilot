"""Which language model (if any) the scientist chose: provider, endpoint, model name, key.

Read from the environment (``QPILOT_MODEL_PROVIDER``, ``QPILOT_MODEL_ENDPOINT``,
``QPILOT_MODEL_NAME``, ``QPILOT_API_KEY``) or set from the app. The default provider is
``none``: qPilot is fully usable with templates only. Model names are never hard-coded.
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field, SecretStr

Provider = Literal["none", "anthropic", "openai_compatible"]


class ModelConfig(BaseModel):
    """A model choice. ``api_key`` is a secret and never printed or logged."""

    provider: Provider = "none"
    endpoint: str | None = None
    model: str | None = None
    api_key: SecretStr | None = Field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> ModelConfig:
        """Build the config from ``QPILOT_MODEL_*`` and ``QPILOT_API_KEY``."""
        provider = (os.environ.get("QPILOT_MODEL_PROVIDER") or "none").strip().lower()
        if provider not in ("none", "anthropic", "openai_compatible"):
            raise ValueError("QPILOT_MODEL_PROVIDER must be none, anthropic or openai_compatible")
        key = os.environ.get("QPILOT_API_KEY")
        return cls(
            provider=provider,  # type: ignore[arg-type]
            endpoint=os.environ.get("QPILOT_MODEL_ENDPOINT") or None,
            model=os.environ.get("QPILOT_MODEL_NAME") or None,
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
