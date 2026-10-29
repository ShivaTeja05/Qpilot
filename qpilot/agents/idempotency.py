"""Idempotency keys for the write tools: a retried request is answered, never logged twice.

An agent (or the network under it) may send the same ``qpcr_decide`` or ``qpcr_propose`` twice.
With an ``idempotency_key`` (any client-chosen token; a fresh UUID per request is the usual
choice) the first answer that recorded something is kept for :data:`TTL_S` seconds and a retry
with the same key and the same arguments gets that answer back, marked
``"idempotent_replay": true``, without touching the decision log or the inbox. The same key with
different arguments is refused (``idempotency_key_reused``). A refusal records nothing and is not
kept, so the corrected request may reuse the key.

The ledger lives in the study store but outside every workspace and Studio session
(``$QPILOT_STUDIES_DIR/agent_requests/``), so the hash chains, the records and ``qpilot verify``
never see it, and the store remains the only writer of a workspace. One file lock covers the
look-up, the write and the save, across threads and processes.

**Limit:** if the process dies after the log was written and before the answer was saved, one
retry with the same key is written again (the chain stays valid; the person sees two requests).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from filelock import FileLock

from qpilot.agents.refusals import Code, is_error, refuse
from qpilot.core.store import LOCK_TIMEOUT_S, atomic_write, canonical_json, dump_json

LEDGER_DIR = "agent_requests"
TTL_S = 24 * 60 * 60
KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
KEY_RULE = "idempotency_key must be one to a hundred and twenty-eight letters, digits or _.:-"
REPLAY = "idempotent_replay"


def _now() -> float:
    return time.time()


def fingerprint(tool: str, args: dict[str, Any]) -> str:
    """sha256 of the tool name and its arguments in canonical JSON."""
    text = canonical_json({"tool": tool, "args": args})
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class IdempotencyLedger:
    """The keyed answers of one study store (``<root>/agent_requests/``)."""

    def __init__(self, root: str | Path) -> None:
        self.folder = Path(root) / LEDGER_DIR

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.folder / digest[:2] / f"{digest}.json"

    def _saved(self, path: Path) -> dict[str, Any] | None:
        """The saved answer at ``path`` while it is fresh, else None (unreadable counts as none)."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            fresh = _now() - float(data["at"]) < TTL_S
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return data if fresh and isinstance(data.get("response"), dict) else None

    def run(
        self,
        tool: str,
        key: Any,
        args: dict[str, Any],
        call: Callable[[], dict[str, Any]],
        *,
        lock: str = ".lock",
    ) -> dict[str, Any]:
        """Answer ``call()`` once per key; replay a fresh saved answer for the same arguments.

        ``lock`` names the file lock held while ``call()`` runs: a tool whose call takes long (an
        export) passes its own, so it never makes another tool's keyed retry wait for it.
        """
        if key is None:
            return call()
        if not isinstance(key, str) or not KEY.match(key):
            return refuse(Code.INVALID_ARGUMENT, KEY_RULE, field="idempotency_key")
        try:
            wanted = fingerprint(tool, args)
        except (TypeError, ValueError):
            return call()  # arguments that are not JSON are refused by the tool itself
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.folder / lock), timeout=LOCK_TIMEOUT_S):
            saved = self._saved(path)
            if saved is not None:
                if saved.get("fingerprint") != wanted:
                    return refuse(
                        Code.IDEMPOTENCY_KEY_REUSED,
                        "this idempotency_key was already used for a different request",
                        field="idempotency_key",
                    )
                return {**saved["response"], REPLAY: True}
            out = call()
            if not is_error(out):  # only an answer that recorded something is kept
                record = {"at": _now(), "tool": tool, "fingerprint": wanted, "response": out}
                atomic_write(path, dump_json(record))
                self._prune(path.parent)
            return out

    def _prune(self, folder: Path) -> None:
        """Remove expired answers next to a new one (cheap: one shard per write)."""
        for other in folder.glob("*.json"):
            if self._saved(other) is None:
                other.unlink(missing_ok=True)


__all__ = ["KEY", "LEDGER_DIR", "REPLAY", "TTL_S", "IdempotencyLedger", "fingerprint"]
