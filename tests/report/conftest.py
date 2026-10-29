"""Fixtures for the exports: the Studio tests' walked mini study (technical triplicates, KO vs WT).

``excluded`` is the same study with one well left out by a person (a ``curve.exclude_well``
proposal accepted with a reason), so the per-well table and the RDML have an exclusion to show.
"""

from __future__ import annotations

import pytest

from tests.web.conftest import mini_walked, walked  # noqa: F401 - fixtures used by the tests

LEFT_OUT = "GAPDH_plate/A1"
REASON = "bubble in the well"


@pytest.fixture
def excluded(walked):  # noqa: F811 - the fixture imported above
    """``walked`` after a person left one GAPDH well out; ``study`` is the new analysis."""
    from qpilot.mcp_server import QpilotTools

    store, studio, sid = walked["store"], walked["studio"], walked["sid"]
    QpilotTools(store).qpcr_propose(sid, "curve.exclude_well", LEFT_OUT, {"excluded": True})
    for p in studio.inbox(sid, "curves", "proposed"):
        studio.accept(sid, p.id, "human", REASON)
    return {**walked, "study": studio.study(sid)}
