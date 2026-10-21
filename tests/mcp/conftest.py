"""Shared fixtures for the agent surface: a data root, the fixture study and the served tools."""

from __future__ import annotations

from typing import Any

import anyio
import pytest

from qpilot.core.store import StudyStore, sha256_file
from qpilot.mcp_server import QpilotTools, create_server


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    """The only folder agents may read (``QPILOT_DATA_ROOTS``)."""
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("QPILOT_DATA_ROOTS", str(root))
    return root


@pytest.fixture
def store(tmp_studies_dir) -> StudyStore:
    return StudyStore(tmp_studies_dir)


@pytest.fixture
def demo(data_root, store, fixture_result, fixture_cards):
    """A stand-in RDML file inside the data root whose workspace holds the fixture study.

    Its cards: ``card_refset`` and ``card_cutoff`` open (both can flip a conclusion),
    ``card_undetermined`` auto-decided.
    """
    rdml = data_root / "demo.rdml"
    rdml.write_bytes(b"<rdml>fixture stand-in</rdml>")
    digest = sha256_file(rdml)
    result = fixture_result.model_copy(update={"input_sha256": digest, "study_id": digest[:12]})
    store.put(result, fixture_cards)
    return rdml, result.study_id


@pytest.fixture
def tools(store) -> QpilotTools:
    return QpilotTools(store)


@pytest.fixture
def served(store):
    """``call(name, args)`` through the MCP server ``qpilot serve`` builds (simulator tools on)."""
    server = create_server(store, simulator=True)

    def call(name: str, args: dict[str, Any]) -> Any:
        return anyio.run(server.call_tool, name, args)

    call.server = server  # type: ignore[attr-defined]
    call.store = store  # type: ignore[attr-defined]
    return call
