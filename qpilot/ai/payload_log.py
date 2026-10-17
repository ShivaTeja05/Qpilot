"""What the model sees: the last payload in memory, and a privacy-safe log line per call.

``last_payload()`` feeds the app's "What the model sees" panel with the exact system prompt and
messages of the most recent call (kept in memory only). ``log_entry()`` builds the line written
to the study's ``ai_calls.jsonl`` through the store: provider, model, payload sha256 and sizes,
whether the output validated and whether a template replaced it. It never contains the API key
and holds the raw payload only when ``QPILOT_LOG_PAYLOAD=1``.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from typing import Any

_lock = threading.Lock()
_last: dict[str, Any] | None = None


def canonical(payload: dict[str, Any]) -> str:
    """The JSON form that is hashed and shown."""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def record_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Remember ``payload`` as the last one sent; return its hash and size."""
    global _last
    text = canonical(payload)
    with _lock:
        _last = json.loads(text)
    return {
        "payload_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "payload_bytes": len(text.encode("utf-8")),
    }


def last_payload() -> dict[str, Any] | None:
    """The exact payload of the last model call in this process, or None."""
    with _lock:
        return None if _last is None else json.loads(canonical(_last))


def clear() -> None:
    """Forget the last payload (tests, or when the model choice changes)."""
    global _last
    with _lock:
        _last = None


def log_entry(
    purpose: str,
    provider: str,
    model: str | None,
    meta: dict[str, Any],
    response: str,
    validated: bool,
    fallback: bool,
) -> dict[str, Any]:
    """One ``ai_calls.jsonl`` line; raw payload only with ``QPILOT_LOG_PAYLOAD=1``."""
    entry = {
        "purpose": purpose,
        "provider": provider,
        "model": model,
        "payload_sha256": meta.get("payload_sha256"),
        "payload_bytes": meta.get("payload_bytes"),
        "response_bytes": len(response.encode("utf-8")),
        "validated": validated,
        "fallback": fallback,
    }
    if os.environ.get("QPILOT_LOG_PAYLOAD") == "1":
        entry["payload"] = last_payload()
    return entry
