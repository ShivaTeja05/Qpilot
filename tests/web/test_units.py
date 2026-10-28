"""Each biological unit's value with its replicate wells, and the audit of a replicate design.

On a real plate with triplicate wells (LightCycler 96, hmuY / 16S rRNA, three biological
replicates per group): ``GET /api/studies/{id}/genes/{gene}/units`` gives the engine's per-unit
values with every well behind them, and the robustness audit runs through the page and says how
the replicates were combined. No demo data is needed.
"""

from __future__ import annotations

import math
import time

import pytest
from scipy import stats

from qpilot.integration import simulator as sim
from qpilot.web import units_views
from tests.integration.hmuy import GENE, HMUY, NAMES, REFERENCE, RUN, hmuy_design
from tests.web.conftest import BASE

WRITE = {"origin": BASE}


@pytest.fixture
def hmuy(web_store):
    units_views.clear_cache()
    return web_store.ensure_study(HMUY, design=hmuy_design())


def _units(client, study_id: str, gene: str = GENE):
    return client.get(f"/api/studies/{study_id}/genes/{gene}/units")


def test_each_unit_is_the_mean_of_its_replicate_wells(client, web_store, hmuy):
    r = _units(client, hmuy)
    assert r.status_code == 200, r.text
    view = r.json()
    stored = web_store.get(hmuy).contrasts[GENE]
    assert view["fold_log2"] == pytest.approx(stored.log2fc, abs=1e-12)
    assert view["p"] == pytest.approx(stored.p, rel=1e-12)
    assert view["replicates"] is True and view["most_wells"] == 3 and view["at_plan"] is True
    assert view["refs"] == [REFERENCE] and view["undetermined"] == "drop"
    points = view["points"]
    assert sorted(p["unit"] for p in points) == sorted(NAMES)  # six units: n is never 18 wells
    for p in points:
        assert p["n_wells"] == 3 and [w["state"] for w in p["wells"]] == ["used"] * 3
        assert {w["plate"] for w in p["wells"]} == {RUN}
        mean_of_wells = sum(w["x"] for w in p["wells"]) / 3
        assert mean_of_wells == pytest.approx(p["x"], abs=1e-12)  # replicates average to the unit
    groups = view["groups"]
    assert (groups["high"]["label"], groups["rest"]["label"]) == ("DIP", "Hm")
    assert (groups["high"]["n"], groups["rest"]["n"]) == (3, 3)
    assert groups["rest"]["mean"] == pytest.approx(0.0, abs=1e-12)
    assert groups["high"]["mean"] == pytest.approx(stored.log2fc, abs=1e-12)
    high = [p["x"] for p in points if p["group"] == "high"]
    half = stats.t.ppf(0.975, 2) * stats.tstd(high) / math.sqrt(3)
    lo, hi = groups["high"]["ci"]
    assert (lo, hi) == pytest.approx((groups["high"]["mean"] - half, groups["high"]["mean"] + half))
    assert view["fold_ci"] == pytest.approx([math.log2(c) for c in stored.ci])
    assert any("replicate wells" in line for line in view["how"])


def test_dip_3s_wide_triplicate_is_visible_well_by_well(client, hmuy):
    view = _units(client, hmuy).json()
    (dip3,) = (p for p in view["points"] if p["unit"] == "be08945d-29c6-47a0-8c49-cc85f693c1a5")
    assert [w["well"] for w in dip3["wells"]] == ["F1", "F2", "F3"]
    cqs = [w["cq_value"] for w in dip3["wells"]]
    assert dip3["cq_range"] == round(max(cqs) - min(cqs), 2)
    assert dip3["cq_range"] > 1.0  # wider than G-REP's expected range for three wells (0.82)


def test_an_excluded_well_is_listed_but_not_used(client, web_store):
    units_views.clear_cache()
    study_id = web_store.ensure_study(HMUY, design=hmuy_design((f"{RUN}/F2",)))
    view = _units(client, study_id).json()
    (dip3,) = (p for p in view["points"] if p["unit"] == "be08945d-29c6-47a0-8c49-cc85f693c1a5")
    assert [w["state"] for w in dip3["wells"]] == ["used", "excluded", "used"]
    assert dip3["n_wells"] == 2 and dip3["wells"][1]["x"] is None
    stored = web_store.get(study_id).contrasts[GENE]
    assert view["fold_log2"] == pytest.approx(stored.log2fc, abs=1e-12)


def test_a_control_gene_or_an_unknown_gene_is_not_found(client, hmuy):
    for gene in (REFERENCE, "NOPE"):
        r = _units(client, hmuy, gene)
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert client.get("/api/studies/000000000000/genes/X/units").status_code == 404


def test_a_study_without_its_file_says_why(client, web_store, hmuy, monkeypatch):
    monkeypatch.setattr(web_store, "source", lambda _sid: None)
    units_views.clear_cache()
    r = _units(client, hmuy)
    assert r.status_code == 409 and r.json()["error"]["code"] == "unavailable"
    assert "input file" in r.json()["error"]["message"]


def _wait(client, job: dict, timeout: float = 300.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        view = client.get(f"/api/jobs/{job['id']}").json()
        if view["status"] in ("done", "failed"):
            return view
        time.sleep(0.05)
    raise AssertionError(f"job {job['id']} did not finish")


@pytest.mark.skipif(not sim.available(), reason="the Decision Simulator is not installed")
def test_the_audit_of_a_replicate_design_through_the_page(client, hmuy):
    status = client.get(f"/api/studies/{hmuy}/audit").json()
    if status.get("checking"):
        assert _wait(client, status["checking"])["status"] == "done"
        status = client.get(f"/api/studies/{hmuy}/audit").json()
    assert status["check"]["applicable"] is True
    words = status["check"]["scope"]["technical_replicates"]["words"]
    assert "never counted as samples" in words and "G-REP" in words
    r = client.post(f"/api/studies/{hmuy}/audit", json={}, headers=WRITE)
    assert r.status_code == 202, r.text
    assert _wait(client, r.json()["job"])["status"] == "done"
    body = client.get(f"/api/studies/{hmuy}/audit").json()
    assert body["status"] == "ready" and body["manifest"]["reproduces_qpilot"]["ok"]
    reps = body["manifest"]["scope"]["technical_replicates"]
    assert reps["most_wells_per_value"] == 3 and reps["varied"] is True
    assert body["manifest"]["scope"]["decisions"]["replicates"] == [
        "mean",
        "median",
        "drop_outlier",
    ]
    # the audit's own sample chart: one point per unit, at the same values as the engine's route
    for _ in range(600):
        r = client.post(f"/api/studies/{hmuy}/audit/samples", json={"gene": GENE, "changes": {}})
        if r.status_code != 409:
            break
        job = r.json()["error"]["details"].get("job")
        if job:
            _wait(client, job)
    assert r.status_code == 200, r.text
    audit_points = {p["sample"]: p["x"] for p in r.json()["points"]}
    engine_points = {p["unit"]: p["x"] for p in _units(client, hmuy).json()["points"]}
    assert audit_points.keys() == engine_points.keys()
    for unit, x in engine_points.items():
        assert audit_points[unit] == pytest.approx(x, abs=1e-9)
    # the audit's lab view counts wells, not units: its Cq range is the wells' own
    lab = client.get(f"/api/studies/{hmuy}/audit/lab/{GENE}").json()["numbers"]
    cqs = [w["cq_value"] for p in _units(client, hmuy).json()["points"] for w in p["wells"]]
    assert (lab["cq_min"], lab["cq_max"]) == (pytest.approx(min(cqs)), pytest.approx(max(cqs)))
    assert lab["n_nondetect"] == 0 and lab["n_plates"] == 1


def test_the_values_stay_at_the_plan_after_a_card_is_decided(client, web_store, hmuy):
    head = web_store.chain_head(hmuy)
    outcome = web_store.append_decision(
        hmuy, "card_undetermined", "cap", "lab rule, for comparison", "human", head
    )
    assert outcome.status == "applied"
    units_views.clear_cache()
    view = _units(client, hmuy).json()
    assert view["at_plan"] is False and view["undetermined"] == "drop"
    assert view["fold_log2"] == pytest.approx(web_store.get(hmuy).contrasts[GENE].log2fc)
    assert any("Prism export follows your choices" in line for line in view["how"])


@pytest.mark.demo_data
def test_the_demo_has_one_well_per_unit(client, web_store):
    from tests.conftest import DEMO_RDML

    if not DEMO_RDML.exists():
        pytest.skip("demo dataset not cached")
    units_views.clear_cache()
    study_id = web_store.ensure_study(DEMO_RDML)
    stored = web_store.get(study_id).contrasts["ODC1"]
    view = _units(client, study_id, "ODC1").json()
    assert view["replicates"] is False and view["most_wells"] == 1
    assert len(view["points"]) == stored.n_hi + stored.n_lo
    assert (view["groups"]["high"]["n"], view["groups"]["rest"]["n"]) == (stored.n_hi, stored.n_lo)
    assert view["fold_log2"] == pytest.approx(stored.log2fc, abs=1e-12)
    assert all(len(p["wells"]) == 1 for p in view["points"])
