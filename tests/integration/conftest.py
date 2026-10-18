"""The integrated workflow, run once on the demo for every test in this folder."""

from __future__ import annotations

import pytest

from qpilot.core.store import StudyStore
from qpilot.integration import simulator as sim

needs_qsim = pytest.mark.skipif(
    not sim.available(), reason="the Decision Simulator is not installed"
)


@pytest.fixture(scope="session")
def demo_rdml_session():
    from tests.conftest import DEMO_RDML

    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    return DEMO_RDML


@pytest.fixture(scope="session")
def workflow(tmp_path_factory, demo_rdml_session):
    """The whole workflow on the demo, the scripted person deciding, with the Prism round trip."""
    if not sim.available():
        pytest.skip("the Decision Simulator is not installed")
    from qpilot.integration.workflow import (
        Options,
        demo_expected,
        exclude_demo_sample,
        run_workflow,
    )

    root = tmp_path_factory.mktemp("workflow")
    store = StudyStore(root / "studies")
    printed: list[str] = []
    report = run_workflow(
        demo_rdml_session,
        root / "run",
        store,
        options=Options(roundtrip_edit=exclude_demo_sample, expected=demo_expected()),
        out=printed.append,
    )
    return {"report": report, "store": store, "root": root, "printed": printed}
