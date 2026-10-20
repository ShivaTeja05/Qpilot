"""Ask on an audited study: verdict and what-if questions go to the audit's Ask engine.

The audit is real: a copy of the store ``QPILOT_TEST_AUDIT_STORE`` names (the UI team's seeded
store: a scripted person confirmed the demo's design and curves through the real service, then the
audit ran), otherwise the demo study audited here once per module (demo data, about a minute).
No model is configured: keyword routing and the audit's checked templates answer.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qpilot.core.store import StudyStore
from qpilot.integration import simulator as sim
from qpilot.web.context import make_context
from qpilot.web.routers.ops import _audit_engine
from qpilot.web.server import create_app
from tests.web.conftest import BASE, TOKEN, wait_job

pytestmark = [
    pytest.mark.demo_data,  # the audited study's input file is the demo's
    pytest.mark.skipif(not sim.available(), reason="the Decision Simulator is not installed"),
    pytest.mark.skipif(_audit_engine() is None, reason="the audit routes are not in this build"),
]


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    """One server over a store with one audited study, no model (built once per module)."""
    root = tmp_path_factory.mktemp("ask-audit") / "studies"
    seeded = os.environ.get("QPILOT_TEST_AUDIT_STORE")
    if seeded and any(Path(seeded, "simulator_audits").glob("*/audit_manifest.json")):
        shutil.copytree(seeded, root)
        study_id = sorted(root.glob("simulator_audits/*/audit_manifest.json"))[0].parent.name
    else:
        from tests.conftest import DEMO_RDML

        if not DEMO_RDML.exists():
            pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
        store = StudyStore(root)
        study_id = store.ensure_study(DEMO_RDML)
        sim.audit(store, study_id, root / "simulator_audits" / study_id)
    previous = os.environ.get("QPILOT_MODEL_PROVIDER")
    os.environ["QPILOT_MODEL_PROVIDER"] = "none"  # read when Studio builds its client
    ctx = make_context(StudyStore(root), token=TOKEN, watch=False)
    try:
        assert ctx.studio.client.provider == "none"
        with TestClient(create_app(ctx), base_url=BASE) as client:
            client.headers["x-qpilot-token"] = TOKEN
            yield client, study_id, ctx.store
    finally:
        ctx.close()
        if previous is None:
            os.environ.pop("QPILOT_MODEL_PROVIDER", None)
        else:
            os.environ["QPILOT_MODEL_PROVIDER"] = previous


def ask(client, study_id, question, **extra):
    r = client.post(f"/api/studies/{study_id}/ask", json={"question": question, **extra})
    assert r.status_code == 202, r.text
    done = wait_job(client, r.json()["job"], timeout=900)
    assert done["status"] == "done", done
    return done["result"]


def test_a_verdict_question_is_answered_by_the_audit(served):
    client, study_id, _ = served
    answer = ask(client, study_id, "Is ODC1 solid?")
    assert answer["engine"] == "audit" and answer["tool"] == "gene"
    assert answer["args"]["gene"] == "ODC1"
    assert answer["written_by"] == "template" and answer["routed_by"] in ("rules", "keywords")
    assert answer["facts"], answer
    for fact in answer["facts"]:
        assert fact["meaning"] and fact["value"] in answer["answer"]
    assert "{{" not in answer["answer"]


def test_a_what_if_question_runs_the_audits_engine(served):
    client, study_id, store = served
    head = store.chain_head(study_id)
    answer = ask(client, study_id, "What if we normalise to HMBS alone?")
    assert answer["engine"] == "audit" and answer["tool"] == "whatif"
    assert answer["args"]["changes"] == {"refs": "HMBS"}
    assert answer["head_after"] == head == store.chain_head(study_id)  # what-if decides nothing


def test_a_change_request_still_goes_to_the_study_and_waits_for_a_person(served):
    client, study_id, store = served
    answer = ask(client, study_id, "Apply HMBS alone as the control gene")
    assert answer["engine"] == "study" and answer["tool"] == "qpcr_decide"
    assert answer["status"] == "pending_human"
    assert any(p.card_id == answer["card_id"] for p in store.pending(study_id))


def test_the_study_can_be_asked_instead(served):
    client, study_id, _ = served
    answer = ask(client, study_id, "Is ODC1 solid?", source="study")
    assert answer["engine"] == "study" and answer["tool"] == "qpcr_robustness"
