"""Pseudonymisation, not anonymisation: sample names become keyed tokens before they leave.

Domain-agnostic. A name is replaced by ``s_`` + the first 10 hex of HMAC-SHA-256 under a secret
key that belongs to one workspace (``<workspace>/.keys/hmac.key``, 32 random bytes, created on
first use with mode 0600). The same name always gets the same token within that workspace, so a
model's answer can be mapped back; without the key nobody can compute a token for a guessed name.

What this is not: anonymisation. Whoever holds the key can confirm a guessed name; the token is
stable, so the same sample is recognisable across everything sent from one workspace; and text
next to the name (counts, groups, dates) can still identify a person. The key never leaves the
workspace: the Analysis Record copies a fixed list of files and ``.keys/`` is not on it
(``tests/core/test_pseudonym.py``).

``endpoint_is_local`` is the one rule for what counts as "this machine" when a model is called:
provider ``none``, or an ``openai_compatible`` endpoint whose host is ``localhost`` or a loopback
address. Everything else is remote, and names must be pseudonymised before any call to it.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import re
import secrets
import stat
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlsplit

from filelock import FileLock

from qpilot.core.store import LOCK_TIMEOUT_S
from qpilot.schemas_studio import QuarantineEntry

TOKEN = re.compile(r"^s_[0-9a-f]{10}\Z")
KEY_DIR = ".keys"
KEY_FILE = "hmac.key"
KEY_BYTES = 32


class PseudonymError(ValueError):
    """A key that is unsafe to use, or two names that would share one token."""


#: Windows opens an ``os.open`` descriptor in text mode unless told otherwise, which turns a
#: random 0x0A byte into CR LF on write and stops a read at the first 0x1A: the key must be binary.
_BINARY = getattr(os, "O_BINARY", 0)


def _read_key(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | _BINARY
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise PseudonymError("the pseudonym key is not a regular file")
        if os.name == "posix" and info.st_mode & 0o077:
            raise PseudonymError(f"{path} is readable by other users; expected mode 0600")
        key = os.read(fd, KEY_BYTES + 1)
    finally:
        os.close(fd)
    if len(key) != KEY_BYTES:
        raise PseudonymError("the pseudonym key is damaged")
    return key


def hmac_key(workspace: str | Path) -> bytes:
    """The workspace's secret key, created (mode 0600, under the workspace lock) on first use."""
    workspace = Path(workspace)
    path = workspace / KEY_DIR / KEY_FILE
    if path.exists():
        return _read_key(path)
    workspace.mkdir(parents=True, exist_ok=True)
    with FileLock(str(workspace / ".lock"), timeout=LOCK_TIMEOUT_S):
        if not path.exists():
            path.parent.mkdir(mode=0o700, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | _BINARY
            fd = os.open(path, flags, 0o600)
            try:
                os.write(fd, secrets.token_bytes(KEY_BYTES))
                os.fsync(fd)
            finally:
                os.close(fd)
    return _read_key(path)


def token(text: str, key: bytes) -> str:
    """The pseudonym of ``text`` under ``key``: ``s_`` + 10 hex of HMAC-SHA-256."""
    digest = hmac.new(key, text.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"s_{digest[:10]}"


class Pseudonymiser:
    """Tokens for one workspace's names (the key is read, or created, on first use)."""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace)
        self._key: bytes | None = None

    @property
    def key(self) -> bytes:
        """The workspace's secret key (never print, log or export it)."""
        if self._key is None:
            self._key = hmac_key(self.workspace)
        return self._key

    def __repr__(self) -> str:
        return f"Pseudonymiser({str(self.workspace)!r})"  # never the key

    def pseudonymise(self, text: str) -> str:
        """The token that stands for ``text`` in anything that leaves this machine."""
        return token(text, self.key)

    def pseudonymise_entries(self, entries: Iterable[QuarantineEntry]) -> list[QuarantineEntry]:
        """Quarantine entries with each value replaced by its token (ids and flags kept).

        Raises :class:`PseudonymError` if two different values would share a token (about one
        chance in 10^7 for a thousand names), because a model would then confuse two samples.
        """
        seen: dict[str, str] = {}
        out = []
        for entry in entries:
            pseudonym = self.pseudonymise(entry.value)
            if seen.setdefault(pseudonym, entry.value) != entry.value:
                raise PseudonymError("two names share one pseudonym; rename one of them")
            out.append(entry.model_copy(update={"value": pseudonym}))
        return out


def endpoint_is_local(provider: str, endpoint: str | None) -> bool:
    """True when a model call cannot leave this machine by itself.

    Provider ``none`` makes no call. An ``openai_compatible`` endpoint is local when its host is
    ``localhost`` or a loopback address (``127.0.0.0/8``, ``::1``); anything else, including
    every ``anthropic`` endpoint and a missing or unparsable URL, is remote. A local endpoint
    can still be a proxy that forwards elsewhere; qPilot cannot see past it.
    """
    if provider == "none":
        return True
    if provider != "openai_compatible" or not endpoint:
        return False
    try:
        host = urlsplit(endpoint.strip()).hostname
    except ValueError:
        return False
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


__all__ = [
    "TOKEN",
    "PseudonymError",
    "Pseudonymiser",
    "endpoint_is_local",
    "token",
    "hmac_key",
]
