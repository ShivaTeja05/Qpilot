"""One client for any model: none, Anthropic, or any OpenAI-compatible endpoint (local or not).

``ModelClient.complete(system, messages)`` returns the model's text. Backends:

- ``NoneBackend``: raises :class:`ModelUnavailable`, so callers fall back to templates.
- ``AnthropicBackend``: the Messages API through the ``anthropic`` SDK (``pip install .[ai]``).
- ``OpenAICompatibleBackend``: ``POST <endpoint>/v1/chat/completions`` with ``httpx``; works for
  Ollama, vLLM, LM Studio and hosted OpenAI-compatible endpoints. An endpoint on this machine
  is called directly, never through an HTTP proxy named by the environment or the system
  settings: names are sent to it without pseudonyms because they stay on this machine. One
  call ends within about twice its timeout, even when the server sends its reply a few bytes
  at a time.
- ``MockBackend``: canned replies for tests; no network.

Every call goes through :mod:`qpilot.ai.payload_log` so the app can show what the model saw.
Temperature defaults to 0. :meth:`ModelClient.complete` always returns text: a reply that is
not text comes back empty, and characters UTF-8 cannot carry (unpaired surrogates) as ``?``.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from qpilot.ai import payload_log
from qpilot.ai.config import ModelConfig

Message = dict[str, str]
DEFAULT_TIMEOUT_S = 60.0
MAX_REPLY_BYTES = 4 * 1024 * 1024  # a chat reply is a few kilobytes; a larger body is refused


def public_endpoint(url: str | None) -> str | None:
    """An endpoint as it may be logged: scheme, host, port and path only (no user, key, query)."""
    if not url:
        return None
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{host}{port}{parts.path}" if parts.scheme else None


def _as_text(reply: Any) -> str:
    """A reply as text that can be logged and parsed (anything but a string is empty)."""
    if not isinstance(reply, str):
        return ""
    return reply.encode("utf-8", "replace").decode("utf-8")  # an unpaired surrogate -> "?"


def _content_text(content: Any) -> str:
    """The text of a chat message's ``content``: a string, or the joined text of its parts."""
    if isinstance(content, list):
        return "".join(
            part["text"]
            for part in content
            if isinstance(part, dict)
            and part.get("type") == "text"
            and isinstance(part.get("text"), str)
        )
    return content if isinstance(content, str) else ""


def _accepts(func: Any, name: str) -> bool:
    """True when ``func`` takes a parameter ``name`` (or ``**kwargs``)."""
    import inspect

    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False
    return name in params or any(p.kind is p.VAR_KEYWORD for p in params.values())


class ModelUnavailable(RuntimeError):
    """No model is configured, or the configured one cannot be reached."""


class Backend(Protocol):
    """Anything that can turn a system prompt and messages into text."""

    name: str
    model: str | None

    def complete(
        self, system: str, messages: list[Message], max_tokens: int, temperature: float
    ) -> str:
        """Return the model's reply."""
        ...


class NoneBackend:
    """No model: every call raises so the caller uses its template."""

    name = "none"
    model = None

    def complete(self, system, messages, max_tokens, temperature) -> str:
        """Always unavailable."""
        raise ModelUnavailable("no model configured (provider = none)")


class MockBackend:
    """Replies from a list (cycled) or a function of the messages; records every call."""

    name = "mock"

    def __init__(self, replies: Sequence[str] | Callable[[str, list[Message]], str], model="mock"):
        self.replies = replies
        self.model = model
        self.calls: list[dict[str, Any]] = []

    def complete(self, system, messages, max_tokens, temperature) -> str:
        """Return the next canned reply."""
        self.calls.append({"system": system, "messages": messages})
        if callable(self.replies):
            return self.replies(system, messages)
        return self.replies[(len(self.calls) - 1) % len(self.replies)]


class AnthropicBackend:
    """Claude through the Anthropic Messages API."""

    name = "anthropic"

    def __init__(self, config: ModelConfig, timeout: float = DEFAULT_TIMEOUT_S):
        if not config.model:
            raise ModelUnavailable("set QPILOT_MODEL_NAME to the model to use")
        if not config.api_key:
            raise ModelUnavailable("set QPILOT_API_KEY for the Anthropic provider")
        try:
            import anthropic
        except ImportError as err:  # pragma: no cover - depends on the install
            raise ModelUnavailable("install the AI extra: pip install -e '.[ai]'") from err
        kwargs: dict[str, Any] = {"api_key": config.api_key.get_secret_value(), "timeout": timeout}
        if config.endpoint:
            kwargs["base_url"] = config.endpoint
        self._client = anthropic.Anthropic(**kwargs)
        self.model = config.model
        self.url = str(getattr(self._client, "base_url", config.endpoint or "")) or None

    def complete(self, system, messages, max_tokens, temperature) -> str:
        """Call the Messages API and join the text blocks."""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "system": system,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if _accepts(self._client.messages.create, "temperature"):  # newer SDKs dropped it
            kwargs["temperature"] = temperature
        try:
            reply = self._client.messages.create(**kwargs)
        except Exception as err:  # network, auth, rate limit: all mean "use the template"
            raise ModelUnavailable(f"Anthropic call failed: {type(err).__name__}") from err
        return "".join(getattr(block, "text", "") for block in reply.content)


class OpenAICompatibleBackend:
    """Any ``/v1/chat/completions`` endpoint: Ollama, vLLM, LM Studio, hosted gateways."""

    name = "openai_compatible"

    def __init__(self, config: ModelConfig, timeout: float = DEFAULT_TIMEOUT_S):
        if not config.endpoint:
            raise ModelUnavailable("set QPILOT_MODEL_ENDPOINT, e.g. http://127.0.0.1:11434")
        if not config.model:
            raise ModelUnavailable("set QPILOT_MODEL_NAME to a model the endpoint serves")
        from qpilot.core.pseudonym import endpoint_is_local

        base = config.endpoint.rstrip("/")
        self.url = base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")
        self.model = config.model
        self.timeout = timeout
        # a call to this machine carries real names; a proxy from HTTP_PROXY or the system
        # settings would take them elsewhere, so only a remote endpoint may go through one
        self._trust_env = not endpoint_is_local(self.name, self.url)
        self._headers = {"Content-Type": "application/json"}
        if config.api_key:
            self._headers["Authorization"] = f"Bearer {config.api_key.get_secret_value()}"

    def complete(self, system, messages, max_tokens, temperature) -> str:
        """POST the chat request and return the first choice's content.

        The whole call is bounded, not only each read: ``httpx``'s timeout applies to every
        read on its own, so a server that sends its status line, headers or body a few bytes at
        a time could keep one call open as long as it liked. The call therefore runs in a worker
        thread, and the caller stops waiting ``2 * timeout`` seconds after it started (the body
        is also given up once it is still being read after ``timeout`` seconds). An abandoned
        call is reported as a failure; its worker ends when the server stops or a read times
        out, and holds nothing the caller uses. A body larger than :data:`MAX_REPLY_BYTES` is
        refused.
        """
        try:
            import httpx
        except ImportError as err:  # pragma: no cover - depends on the install
            raise ModelUnavailable("install the AI extra: pip install -e '.[ai]'") from err
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        outcome: dict[str, Any] = {}

        def call() -> None:
            try:
                outcome["reply"] = self._post(httpx, body)
            except Exception as err:  # reported to the caller below
                outcome["error"] = err

        worker = threading.Thread(target=call, name="qpilot-model-call", daemon=True)
        worker.start()
        worker.join(2 * self.timeout)
        if worker.is_alive():
            raise ModelUnavailable(
                "endpoint call failed: no complete reply within twice the timeout (abandoned)"
            )
        try:
            if "error" in outcome:
                raise outcome["error"]
            content = outcome["reply"]["choices"][0]["message"]["content"]
        except Exception as err:
            raise ModelUnavailable(f"endpoint call failed: {type(err).__name__}") from err
        return _content_text(content)

    def _post(self, httpx: Any, body: dict[str, Any]) -> Any:
        """Send ``body`` and read the JSON reply within :attr:`timeout` seconds in all."""
        deadline = time.monotonic() + self.timeout
        chunks: list[bytes] = []
        size = 0
        with httpx.stream(
            "POST",
            self.url,
            json=body,
            headers=self._headers,
            timeout=self.timeout,
            trust_env=self._trust_env,
        ) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_REPLY_BYTES:
                    raise ValueError(f"the reply is larger than {MAX_REPLY_BYTES} bytes")
                chunks.append(chunk)
                if time.monotonic() > deadline:
                    raise httpx.ReadTimeout("the reply took longer than the client's timeout")
        return json.loads(b"".join(chunks))


def make_backend(config: ModelConfig) -> Backend:
    """The backend for a config (``NoneBackend`` for provider ``none``)."""
    if config.provider == "anthropic":
        return AnthropicBackend(config)
    if config.provider == "openai_compatible":
        return OpenAICompatibleBackend(config)
    return NoneBackend()


class ModelClient:
    """The single entry point every model call goes through."""

    def __init__(self, backend: Backend | None = None, config: ModelConfig | None = None):
        if backend is None:
            config = config or ModelConfig.from_env()
            try:
                backend = make_backend(config)
            except ModelUnavailable:
                backend = NoneBackend()
        self.backend = backend
        self.last_meta: dict[str, Any] = {}
        self.metas: list[dict[str, Any]] = []  # one per call, so every call can be logged

    @classmethod
    def from_env(cls) -> ModelClient:
        """A client for the model configured in the environment (or none)."""
        return cls(config=ModelConfig.from_env())

    @property
    def provider(self) -> str:
        """Backend name: none, anthropic, openai_compatible or mock."""
        return self.backend.name

    @property
    def model(self) -> str | None:
        """The model name the backend uses, if any."""
        return self.backend.model

    @property
    def available(self) -> bool:
        """False for the none backend."""
        return not isinstance(self.backend, NoneBackend)

    def complete(
        self,
        system: str,
        messages: list[Message],
        max_tokens: int = 600,
        temperature: float = 0.0,
    ) -> str:
        """Send one request; the payload is recorded for the "What the model sees" panel.

        The reply is always text (see the module docstring).
        """
        payload = {
            "provider": self.provider,
            "model": self.model,
            "system": system,
            "messages": messages,
        }
        self.last_meta = payload_log.record_payload(payload)
        self.metas.append(self.last_meta)
        return _as_text(self.backend.complete(system, messages, max_tokens, temperature))

    def ping(self) -> bool:
        """True when the backend answers a one-token request (the app's "connected" dot)."""
        if not self.available:
            return False
        try:
            self.backend.complete("Reply with OK.", [{"role": "user", "content": "OK?"}], 1, 0.0)
        except ModelUnavailable:
            return False
        return True
