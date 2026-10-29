"""A test's own home folder, the way each system finds it.

``Path.home()`` and ``~`` read ``HOME`` on macOS and Linux but ``USERPROFILE`` on Windows (Python
3.8 and later), so a test that gives qPilot a private home folder sets both.
"""

from __future__ import annotations

from pathlib import Path

import pytest

HOME_VARS = ("HOME", "USERPROFILE")


def set_home(monkeypatch: pytest.MonkeyPatch, folder: Path) -> None:
    """Make ``folder`` this process's home folder for the rest of the test."""
    for name in HOME_VARS:
        monkeypatch.setenv(name, str(folder))


def home_env(folder: Path) -> dict[str, str]:
    """The environment variables that make ``folder`` a child process's home folder."""
    return dict.fromkeys(HOME_VARS, str(folder))
