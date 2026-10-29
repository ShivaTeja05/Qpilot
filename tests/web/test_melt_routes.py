"""The melt route: a session's and a study's melt curves, peaks and calls, from a real SYBR file.

The LightCycler 96 experiment file of the corpus (``rdml/lightcycler96-lc96p-hmuy``: P.
endodontalis hmuY and 16S rRNA, six samples in triplicate, SYBR Green I, melt in 0.2 °C steps)
is dropped on the page with a sample sheet, as a person would, and walked through Studio. The
sheet's groups are the depositors' own (their Cq table ``hmuy_cq_values.xlsx``, sheet "Hm vs
DIP": each of the file's samples is named as in that table (its RDML description)). The
mini file (no melt curves) says so in words. Every number is compared with the engine's own.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qpilot.core.store import StudyStore
from qpilot.qpcr import melt as M
from qpilot.web.context import make_context
from qpilot.web.routers import melt as melt_router
from qpilot.web.server import create_app
from tests.web.conftest import BASE, TOKEN, get_settled, wait_job
from tests.web.test_workspaces_capture import drop

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"
LC96P = CORPUS / "rdml" / "lightcycler96-lc96p-hmuy" / "hmuy_hm_vs_dip_r123.lc96p"
#: The file's samples (named from their RDML description) -> the depositors' condition.
GROUPS = {
    "Hm_1": "Hm",  # 16S 11.73, hmuY 23.46
    "Hm_2": "Hm",  # 11.52, 24.13
    "Hm_3": "Hm",  # 8.70, 22.63
    "DIP_1": "DIP",  # 8.42, 17.78
    "DIP_2": "DIP",  # 13.28, 24.72
    "DIP_3": "DIP",  # 13.11, 23.96
}
SHEET = "Sample,Group\n" + "".join(f"{k},{v}\n" for k, v in GROUPS.items())
HMUY, S16, EMPTY = ("HmuYPe", "16S rRNA", "no target (SYBR Green I)")
PLATE = "99caca4d-c437-48dc-ad56-7c6954ead2e8"


def walk(client, studio) -> dict:
    """Drop the file and the sheet; decide the design (16S the reference) and the curves."""
    from qpilot.mcp_server import QpilotTools

    r = drop(client, [LC96P], extra=[("samples.csv", SHEET.encode(), "text/csv")])
    assert r.status_code == 202, r.text
    job = wait_job(client, r.json()["job"])
    assert job["status"] == "done", job
    sid = job["result"]["key"]
    out: dict = {"sid": sid, "blind": client.get(f"/api/sessions/{sid}/melt")}
    studio.propose_design(sid)
    for p in studio.inbox(sid, "design", "proposed"):
        studio.accept(sid, p.id, "human", "as the sample sheet says")
    tools = QpilotTools(studio.store)
    for target in (HMUY, EMPTY):  # the rules propose every target as a reference
        tools.qpcr_propose(sid, "design.target_role", target, {"role": "toi"})
    for p in studio.inbox(sid, "design", "proposed"):
        studio.accept(sid, p.id, "human", "16S rRNA is the reference; hmuY is studied")
    comparison = studio.propose_comparison(sid)
    studio.accept(sid, comparison.proposal.id, "human", "Hm is the reference condition")
    confirm = studio.propose_confirm(sid, "design")
    studio.accept(sid, confirm.proposal.id, "human")
    out["design_only"] = client.get(f"/api/sessions/{sid}/melt").json()
    studio.propose_curves(sid)
    for p in studio.inbox(sid, "curves", "proposed"):
        studio.accept(sid, p.id, "human", "checked")
    confirm = studio.propose_confirm(sid, "curves")
    studio.accept(sid, confirm.proposal.id, "human")
    out["study"] = studio.study(sid)
    return out


@pytest.fixture(scope="module")
def lc96(tmp_path_factory):
    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.studio_service import Studio

    base = tmp_path_factory.mktemp("lc96")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("QPILOT_MODEL_PROVIDER", "none")
        mp.setenv("QPILOT_STUDIES_DIR", str(base / "studies"))
        store = StudyStore(base / "studies")
        studio = Studio(store, client=ModelClient(backend=NoneBackend()))
        ctx = make_context(store, studio, token=TOKEN, watch=False)
        melt_router.clear()
        with TestClient(create_app(ctx), base_url=BASE) as c:
            c.headers["x-qpilot-token"] = TOKEN
            c.headers["origin"] = BASE
            yield {"client": c, "store": store, "studio": studio, **walk(c, studio)}
        ctx.close()
        melt_router.clear()


def get(client, url: str) -> dict:
    r = client.get(url)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_sessions_melt_curves_wait_for_its_design(lc96):
    r = lc96["blind"]
    assert r.status_code == 409 and r.json()["error"]["code"] == "studio"
    assert "confirm the design first" in r.json()["error"]["message"]
    # once the design is confirmed they show, before the curves are (no group is named)
    view = lc96["design_only"]
    assert view["has_melt"] and view["run"] == PLATE and view["study_id"] is None
    # no group is named: no group field anywhere, and no value is a group's label (the file's
    # own sample and target names, Hm_1 or HmuYPe, are not groups)
    assert not _names_a_group(view, set(GROUPS.values()))


def _names_a_group(value, groups: set[str]) -> bool:
    if isinstance(value, dict):
        return any(
            key in ("group", "groups") or key in groups or _names_a_group(item, groups)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_names_a_group(item, groups) for item in value)
    return isinstance(value, str) and value in groups


def test_the_plates_assays_and_every_wells_call(lc96):
    view = get(lc96["client"], f"/api/sessions/{lc96['sid']}/melt")
    assert view["plates"] == [PLATE] and view["pack"] == "research-default 1.4.0"
    assert view["params"] == {
        "tm_tolerance_c": 1.0,
        "extra_peak_share": 0.05,
        "noise_share": 0.05,
        "min_wells": 3,
        "dimer_min_below_c": 3.0,
    }
    assert view["method"] == "methods/melt_curve.md" and "MIQE 2.0" in view["caveat"]
    assays = {a["target"]: a for a in view["assays"]}
    assert set(assays) == {HMUY, S16, EMPTY}
    assert assays[HMUY]["counts"] == {"one_product": 18} and assays[HMUY]["flagged"] == []
    assert assays[S16]["counts"] == {"one_product": 18}
    assert assays[EMPTY]["counts"] == {"no_product": 60} and assays[EMPTY]["expected_tm"] is None
    assert round(assays[HMUY]["expected_tm"], 1) == 82.0
    assert round(assays[S16]["expected_tm"], 1) == 87.1
    assert assays[HMUY]["expected_source"] == "median" and assays[HMUY]["n_reference"] == 18
    assert assays[HMUY]["summary"] == (
        "Every amplified study well melts as one product at the expected temperature."
    )
    assert len(view["calls"]) == 96 and view["wells"] == []
    assert {c["status_text"] for c in view["calls"] if c["target"] == EMPTY} == {
        "No-template control: nothing melted"
    }
    # the numbers are the engine's
    data = M.read_melt(lc96["studio"].source(lc96["sid"]))
    for call in view["calls"]:
        w = data.wells[(PLATE, call["well"], call["target"])]
        if call["main_tm"] is not None:
            assert any(p.tm == call["main_tm"] for p in w.peaks)


def test_a_wells_curve_its_peaks_and_readings(lc96):
    c = lc96["client"]
    view = get(c, f"/api/sessions/{lc96['sid']}/melt")
    hmuy = sorted(x["well"] for x in view["calls"] if x["target"] == HMUY)[:2]
    one = get(c, f"/api/sessions/{lc96['sid']}/melt?run={PLATE}&wells={','.join(hmuy)}")
    assert [w["well"] for w in one["wells"]] == sorted(hmuy, key=lambda w: (w[0], int(w[1:])))
    for w in one["wells"]:
        assert w["status"] == "one_product" and w["amplified"] and w["cq"] is not None
        assert len(w["temperature"]) == len(w["derivative"]) > 100
        assert len(w["readings_temperature"]) == len(w["readings_fluorescence"])
        assert w["step_c"] == pytest.approx(0.2, abs=0.01)
        (product,) = (p for p in w["peaks"] if p["role"] == "main")
        assert product["tm"] == w["main_tm"] and product["share"] > 0.9
        assert abs(w["offset_c"]) < 1.0
        top = max(range(len(w["derivative"])), key=w["derivative"].__getitem__)
        assert abs(w["temperature"][top] - product["tm"]) <= w["step_c"]


def test_bad_wells_and_a_plate_without_melt(lc96):
    c = lc96["client"]
    r = c.get(f"/api/sessions/{lc96['sid']}/melt?wells=A1,../x")
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_request"
    view = get(c, f"/api/sessions/{lc96['sid']}/melt?run=elsewhere")
    assert (
        view["has_melt"]
        and view["assays"] == []
        and view["message"] == ("This plate has no melt curves.")
    )


def test_the_study_says_what_the_session_says_and_the_gate_weighs_it(lc96):
    c, study = lc96["client"], lc96["study"]
    session = get(c, f"/api/sessions/{lc96['sid']}/melt")
    view = get(c, f"/api/studies/{study}/melt")
    assert view["study_id"] == study and view["key"] == study
    assert view["calls"] == session["calls"] and view["assays"] == session["assays"]
    r = get_settled(c, f"/api/studies/{study}/gate")
    assert r.status_code == 200, r.text
    body = r.json()
    melt = [e for e in body["evaluations"] if e["rule_id"] == "G-MELT"]
    assert {(e["verdict"], e["outcome"]) for e in melt} == {
        ("pass", "one_product"),
        ("pass", "ntc_clean"),
    }
    assert len([e for e in melt if e["outcome"] == "one_product"]) == 12  # 6 samples x 2 targets
    assert body["pack"]["version"] == "1.4.0"
    assert "G-MELT" in [r["rule_id"] for r in body["pack"]["rules"]]


def test_a_study_without_melt_curves_says_what_to_export(walked):
    c = walked["client"]
    view = get(c, f"/api/studies/{walked['study']}/melt")
    assert view["has_melt"] is False and view["calls"] == [] and view["plates"] == []
    assert "Melt Curve RFU Results" in view["message"]
    session = get(c, f"/api/sessions/{walked['sid']}/melt")
    assert session["has_melt"] is False
    r = c.get("/api/studies/nosuchstudy/melt")
    assert r.status_code == 404


def test_the_miqe_item_on_specificity_reads_the_melt_curves(lc96):
    c, study = lc96["client"], lc96["study"]
    miqe = get(c, f"/api/studies/{study}/report")["miqe"]
    (item,) = (i for i in miqe["items"] if i["id"] == "5.19")
    assert item["status"] == "met" and "methods/melt_curve.md" in item["sources"]
    plain = item["evidence"]["plain"]
    assert plain.startswith(
        "qPilot analysed the melt curves of 96 wells (3 assays on their plates)"
    )
    assert "The products melt between 82.0 °C and 87.1 °C." in plain
    assert "G-MELT points at 0 wells" in plain and "(MIQE 2.0)" in plain


def test_without_melt_curves_the_miqe_item_says_so(walked):
    miqe = get(walked["client"], f"/api/studies/{walked['study']}/report")["miqe"]
    (item,) = (i for i in miqe["items"] if i["id"] == "5.19")
    assert item["status"] == "cannot_tell"
    assert item["evidence"]["plain"].startswith("The study's file has no melt curves")
