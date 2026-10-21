"""Where to look on the real demo study (origin/main's ``test_demo_trace_camta2_and_decide_k22``).

Tumour 2016's HMBS well on plate HMBS_20080318 (K22) is CAMTA2's first place to look, at the
analysis in use; Decide… opens its card, a person decides it, and the record still verifies.
Both Trace engines agree on the analysis they trace (the route refuses otherwise).
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from qpilot.core.record import verify, write_record
from qpilot.core.store import StudyStore
from qpilot.web.context import make_context
from qpilot.web.routers import trace as trace_router
from qpilot.web.routers import where as where_router
from qpilot.web.server import create_app
from tests.web.conftest import BASE, TOKEN, wait_job

pytestmark = pytest.mark.demo_data


@pytest.fixture(scope="module")
def demo_store(tmp_path_factory):
    from qpilot.io.datasets import default_cache_dir

    rdml = default_cache_dir() / "data_vermeulen_raw.rdml"
    if not rdml.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    base = tmp_path_factory.mktemp("where-demo") / "studies"
    store = StudyStore(base)
    return base, store.ensure_study(rdml)


def _get(c, url, **params):
    r = c.get(url, params=params)
    if r.status_code == 409 and r.json()["error"]["code"] == "loading":
        assert wait_job(c, r.json()["error"]["details"]["job"])["status"] == "done"
        r = c.get(url, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_camta2_points_at_k22_and_decide_opens_its_card(demo_store, tmp_path):
    base, study = demo_store
    shutil.copytree(base, tmp_path / "studies")
    store = StudyStore(tmp_path / "studies")
    context = make_context(store, token=TOKEN, watch=False)
    trace_router.clear()
    where_router.clear()
    try:
        with TestClient(create_app(context), base_url=BASE) as c:
            c.headers["x-qpilot-token"] = TOKEN
            c.headers["origin"] = BASE
            view = _get(c, f"/api/studies/{study}/where-to-look", gene="CAMTA2")
            first = view["places"][0]
            assert (first["sample"], first["plate"], first["well"]) == (
                "2016",
                "HMBS_20080318",
                "K22",
            )
            assert first["can_decide"] and first["card_id"] == "card_trace_2016_hmbs_20080318_k22"
            assert view["planned"] is True
            # the Trace section traces the same call
            section = _get(c, f"/api/studies/{study}/trace/CAMTA2")
            assert section["trace"]["call"]["conclusion"] == "none"
            body = {"kind": "gene", "id": "CAMTA2", "rank": 1, "expected_head": view["head"]}
            opened = c.post(f"/api/studies/{study}/where-to-look/open", json=body).json()
            assert opened["card_id"] == first["card_id"] and opened["opened"] is True
            card = next(
                x
                for x in c.get(f"/api/studies/{study}/cards").json()["cards"]
                if x["card"]["id"] == opened["card_id"]
            )
            assert card["place"]["well"] == "K22" and "CAMTA2" in card["genes"]
            r = c.post(
                f"/api/studies/{study}/cards/{opened['card_id']}/decide",
                json={
                    "option": "read_from_other_refs",
                    "reason": "K22 reads far later than the plate's standards.",
                    "expected_head": store.chain_head(study),
                },
            )
            assert r.status_code == 200, r.text
            assert store.card(study, opened["card_id"]).decided_by == "human"
        info = write_record(store, study, tmp_path / "rec")
        assert verify(info.record_dir).ok
    finally:
        context.close()
        trace_router.clear()
        where_router.clear()
