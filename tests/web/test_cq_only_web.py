"""A lab that only has a Cq table analyses it end to end on the page (``docs/cq-tables.md``).

The depositors' own Excel Cq table of the hmuY study (``hmuy_cq_values.xlsx``: Sample Name,
Gene Name, Condition, Gene Type, Cq; no curves) is dropped alone, the design is set with the
page's design editor, the curves stage confirms the Cq table, and the results, the Evidence
Ledger, the report (Methods, MIQE), the further choices and the Analysis Record follow. The
mini file without curves (``write_studio_mini(curves=False)``) carries a dilution series, so the
efficiency comes from it. Every test runs on a private curve cache: a Cq table must never depend
on (or leave) an entry in the shared one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qpilot.core.record import rerun_compare, verify, write_record
from qpilot.core.store import StudyStore
from qpilot.qpcr.cq_only import NOT_APPLICABLE
from qpilot.web.context import make_context
from qpilot.web.server import create_app
from tests.web.conftest import BASE, TOKEN, wait_job

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"
TABLE = CORPUS / "rdml" / "lightcycler96-lc96p-hmuy" / "hmuy_cq_values.xlsx"
SOYBEAN = CORPUS / "rdml" / "rdml-1.2-cq-only-soybean" / "VPZ_raw_data.rdml"
REASON = "set on the page from the lab's notebook"
#: Every Cq of the table (two decimals, as the depositors typed them).
TABLE_CQ = ("23.4", "23.51", "17.69", "24.61", "11.67", "8.4")


class Page:
    """A keyed client over a private store and a private curve cache."""

    def __init__(self, base: Path) -> None:
        from qpilot.ai.client import ModelClient, NoneBackend
        from qpilot.studio_service import Studio

        self.store = StudyStore(base / "studies")
        self.studio = Studio(self.store, client=ModelClient(backend=NoneBackend()))
        self.ctx = make_context(self.store, self.studio, token=TOKEN, watch=False)
        self.client = TestClient(create_app(self.ctx), base_url=BASE)
        self.client.headers["x-qpilot-token"] = TOKEN
        self.client.headers["origin"] = BASE

    def ok(self, response, code: int = 200):
        assert response.status_code == code, response.text[:600]
        return response.json()

    def get(self, path: str, **params):
        return self.ok(self.client.get(path, params=params or None))

    def job(self, response) -> dict:
        done = wait_job(self.client, self.ok(response, 202)["job"])
        assert done["status"] == "done", done
        return done["result"]

    def head(self, sid: str) -> str:
        return self.get(f"/api/sessions/{sid}/design/editor")["head"]

    def set_design(self, sid: str, items: list[tuple[str, str, dict]]) -> dict:
        body = {
            "items": [{"kind": k, "subject": s, "payload": p} for k, s, p in items],
            "reason": REASON,
            "expected_head": self.head(sid),
        }
        return self.ok(self.client.post(f"/api/sessions/{sid}/design/set", json=body))

    def settle(self, sid: str, stage: str, accept: bool) -> None:
        for p in self.get(f"/api/sessions/{sid}/proposals", stage=stage)["proposals"]:
            if p["status"] != "proposed":
                continue
            verb = "accept" if accept else "reject"
            body = {"reason": "checked against the table", "expected_head": self.head(sid)}
            self.ok(self.client.post(f"/api/sessions/{sid}/proposals/{p['id']}/{verb}", json=body))

    def confirm(self, sid: str, stage: str) -> dict:
        view = self.ok(self.client.post(f"/api/sessions/{sid}/confirm/{stage}"))
        assert view["ready"], view
        body = {"proposal_id": view["proposal"]["id"], "expected_head": view["head"]}
        return self.ok(self.client.post(f"/api/sessions/{sid}/confirm/{stage}/accept", json=body))


@pytest.fixture(scope="module")
def hmuy(tmp_path_factory):
    """The hmuY Cq table walked to the curves check (design confirmed, curves not yet)."""
    base = tmp_path_factory.mktemp("cq-hmuy")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("QPILOT_CACHE_DIR", str(base / "cache"))
        mp.setenv("QPILOT_MODEL_PROVIDER", "none")
        page = Page(base)
        files = [("files", (TABLE.name, TABLE.read_bytes(), "application/octet-stream"))]
        sid = page.job(page.client.post("/api/workspaces", files=files))["key"]
        page.job(page.client.post(f"/api/sessions/{sid}/propose/design", json={}))
        samples = page.get(f"/api/sessions/{sid}/design/editor")["samples"]
        before = {
            "cq_table": page.get(f"/api/sessions/{sid}/cq-table"),
            "results": page.client.get(f"/api/sessions/{sid}/proposals", params={"stage": "prism"}),
            "sheet": page.studio.sheet(sid).read_text(encoding="utf-8"),
        }
        done = page.set_design(
            sid,
            [
                ("design.target_role", "16S rRNA", {"role": "ref"}),
                ("design.target_role", "hmuYPe", {"role": "toi"}),
                *(
                    ("design.group", s["sample"], {"group": s["sample"].split("_")[0]})
                    for s in samples
                ),
                ("design.comparison", "comparison", {"group_a": "DIP", "group_b": "Hm"}),
            ],
        )
        page.settle(sid, "design", accept=False)
        page.confirm(sid, "design")
        report = page.job(page.client.post(f"/api/sessions/{sid}/propose/curves"))
        yield {"page": page, "sid": sid, "base": base, "set": done, "before": before,
               "report": report}  # fmt: skip
        page.ctx.close()


@pytest.fixture(scope="module")
def hmuy_study(hmuy):
    """The same session with the curves stage confirmed and the study analysed."""
    page, sid = hmuy["page"], hmuy["sid"]
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("QPILOT_CACHE_DIR", str(hmuy["base"] / "cache"))
        cq_table = page.get(f"/api/sessions/{sid}/cq-table")
        page.settle(sid, "curves", accept=True)
        confirmed = page.confirm(sid, "curves")
        job = wait_job(page.client, confirmed["job"])
        assert job["status"] == "done", job
        yield {**hmuy, "study": job["result"]["study_id"], "cq_table": cq_table}


# ---- the curves stage: the Cq table, blind --------------------------------------------------


def test_the_table_opens_alone_and_is_set_on_the_page(hmuy):
    view = hmuy["page"].get(f"/api/sessions/{hmuy['sid']}")
    assert any("holds Cq values only" in n for n in view["summary"]["notes"])
    assert not any("LinRegPCR could not analyse" in n for n in view["summary"]["notes"])
    assert hmuy["set"]["recorded"] >= 9  # 2 roles, 6 groups (the sheet's, accepted), comparison


def test_checking_the_curves_proposes_the_rule_and_says_what_does_not_apply(hmuy):
    page, sid, report = hmuy["page"], hmuy["sid"], hmuy["report"]
    assert report["disagreements"] is None  # no Curve Judge sentence: there is nothing to judge
    assert NOT_APPLICABLE["curve_judge"] in report["notes"]
    assert NOT_APPLICABLE["linregpcr"] in report["notes"]
    waiting = [
        p
        for p in page.get(f"/api/sessions/{sid}/proposals", stage="curves")["proposals"]
        if p["status"] == "proposed"
    ]
    assert [(p["kind"], p["payload"]) for p in waiting] == [
        ("curve.call_rule", {"rule": "linregpcr", "basis": "cq"})
    ]
    assert "the file gives it a Cq" in waiting[0]["reasons"][0]
    calls = page.get(f"/api/sessions/{sid}/curve-calls", gene="hmuYPe")
    assert calls["rule_labels"]["linregpcr"].startswith("The file's own Cq")
    assert calls["curve_judge"] == NOT_APPLICABLE["curve_judge"]
    plate = page.get(f"/api/sessions/{sid}/plate")
    assert plate["cq_only"] and plate["curve_judge"] == NOT_APPLICABLE["curve_judge"]
    assert all(w["group"] is None for w in plate["wells"])
    r = page.client.get(f"/api/sessions/{sid}/curve", params={"well": "hmuy Hm vs DIP/A1"})
    assert r.status_code == 404 and "Cq values only" in r.json()["error"]["message"]
    melt = page.get(f"/api/sessions/{sid}/melt")
    assert not melt["has_melt"] and melt["message"] == NOT_APPLICABLE["melt"]


def test_the_cq_table_to_confirm_is_the_files_cq_with_g_rep_and_no_group(hmuy):
    page, sid = hmuy["page"], hmuy["sid"]
    hidden = hmuy["before"]["cq_table"]  # before the design was confirmed: no Cq at all
    assert hidden["cq_only"] and not hidden["shown"] and hidden["sets"] == []
    view = page.get(f"/api/sessions/{sid}/cq-table")
    assert view["cq_only"] and view["shown"]
    assert view["counts"] == {
        "n_wells": 36,
        "n_with_cq": 36,
        "n_without_cq": 0,
        "n_study_without_cq": 0,
        "n_sets": 12,
        "n_outside": 1,
        "n_late": 0,
        "n_controls_with_cq": 0,
    }
    outside = [s for s in view["sets"] if s["spread"] == "outside"]
    assert [(s["sample"], s["target"]) for s in outside] == [("DIP_3", "hmuYPe")]
    assert [w["cq"] for w in outside[0]["wells"]] == [23.79, 24.61, 23.47]
    assert outside[0]["range_cq"] == pytest.approx(1.14)
    assert {e["target"]: e["source"] for e in view["efficiencies"]} == {
        "16S rRNA": "assumed",
        "hmuYPe": "assumed",
    }
    assert set(view["not_applicable"]) >= {NOT_APPLICABLE["curve_judge"], NOT_APPLICABLE["melt"]}
    text = json.dumps(view)
    assert '"group' not in text  # blind: no design group anywhere in the stage's table
    assert "fc" not in {k for s in view["sets"] for k in s}


def test_nothing_pairs_a_group_with_a_number_before_both_stages_are_confirmed(hmuy):
    page, sid = hmuy["page"], hmuy["sid"]
    r = hmuy["before"]["results"]
    assert r.status_code == 403 and r.json()["error"]["code"] == "blind"
    r = page.client.get(f"/api/sessions/{sid}/proposals", params={"stage": "prism"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "blind"
    assert page.get(f"/api/sessions/{sid}")["results_visible"] is False
    # the sample sheet the table made holds the groups, never a Cq
    sheet = hmuy["before"]["sheet"]
    assert "DIP" in sheet and "Hm" in sheet
    assert not any(cq in sheet for cq in TABLE_CQ)


# ---- results, ledger, report, record ----------------------------------------------------


def test_results_come_from_the_given_cq_values(hmuy_study):
    page, study = hmuy_study["page"], hmuy_study["study"]
    results = page.get(f"/api/studies/{study}/results")
    (gene,) = results["genes"]
    assert gene["gene"] == "hmuYPe" and gene["conclusion"] == "none"
    # −ΔΔCq of the depositors' own Cq (means of the triplicates, efficiency 2.0)
    assert gene["fc"] == pytest.approx(4.6231907512, rel=1e-9)
    assert gene["level"] == "Low"
    efficiency = next(a for a in results["axes"] if a["name"] == "efficiency")
    assert efficiency["status"] == "off" and efficiency["can_propose"] is False
    assert "has Cq values only and no assay has a dilution series" in efficiency["text"]["plain"]
    by_id = {o["id"]: o for o in efficiency["options"]}
    assert by_id["per_well"]["unavailable"].startswith("Not applicable: this file has Cq values")
    assert by_id["linregpcr"]["label"].startswith("Each assay's efficiency from its dilution")
    trust = page.get(f"/api/studies/{study}/import-trust")
    assert not trust["applies"] and "Cq values only" in trust["why"]
    trace = page.get(f"/api/studies/{study}/trace/hmuYPe")
    assert "LinRegPCR's note" not in json.dumps(trace)  # no curve note: Trace reads the Cq


def test_the_evidence_ledger_and_the_report_say_no_curves_were_available(hmuy_study):
    page, study = hmuy_study["page"], hmuy_study["study"]
    items = {i["id"]: i for i in page.get(f"/api/studies/{study}/evidence")["items"]}
    assert items["rawness"]["status"] == "not_applicable"
    assert items["rawness"]["line"]["plain"].endswith(NOT_APPLICABLE["rawness"])
    assert items["efficiency"]["status"] == "absent"
    assert "has Cq values only" in items["efficiency"]["line"]["plain"]
    report = page.get(f"/api/studies/{study}/report")
    curves = next(p for p in report["methods"]["paragraphs"] if p["id"] == "curves")
    assert curves["text"]["plain"].startswith("The file holds Cq values only")
    assert "LinRegPCR" not in curves["text"]["plain"]
    miqe = {i["id"]: i for i in report["miqe"]["items"]}
    assert miqe["5.1"]["status"] == "not_met"
    assert miqe["5.1"]["evidence"]["plain"].startswith("Not available: the file holds Cq values")
    assert miqe["5.3"]["status"] == "cannot_tell"
    assert "set by the instrument software" in miqe["5.3"]["evidence"]["plain"]
    assert miqe["5.8"]["status"] == "not_met" and miqe["5.9"]["status"] == "not_met"


def test_a_cq_only_record_verifies_and_re_runs_to_the_same_bytes(hmuy_study, tmp_path):
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("QPILOT_CACHE_DIR", str(hmuy_study["base"] / "cache"))
        info = write_record(hmuy_study["page"].store, hmuy_study["study"], tmp_path / "rec")
        assert verify(info.record_dir).ok
        report = rerun_compare(info.record_dir, tmp_path / "rerun")
    assert report.same, report.differs
    assert {"facts.json", "grid.csv"} <= set(report.compared)


# ---- a dilution series gives the efficiency ---------------------------------------------


def test_the_mini_file_without_curves_takes_its_efficiency_from_the_series(tmp_path, monkeypatch):
    from tests.fixtures.studio.studio_mini import write_studio_mini

    monkeypatch.setenv("QPILOT_CACHE_DIR", str(tmp_path / "cache"))
    root = tmp_path / "data"
    monkeypatch.setenv("QPILOT_DATA_ROOTS", str(root))
    path = write_studio_mini(root / "mini_cq.rdml", curves=False)
    page = Page(tmp_path)
    try:
        files = {"rdml": (path.name, path.read_bytes(), "application/xml")}
        sid = page.job(page.client.post("/api/workspaces", files=files))["key"]
        page.job(page.client.post(f"/api/sessions/{sid}/propose/design", json={}))
        page.set_design(
            sid,
            [
                ("design.target_role", "GAPDH", {"role": "ref"}),
                ("design.target_role", "1-Mar", {"role": "toi"}),
                (
                    "design.dilution_series",
                    "STD",
                    {"samples": {"STD_100": 100, "STD_1000": 1000, "STD_10000": 10000}},
                ),  # fmt: skip
                *(("design.group", s, {"group": s[:2]}) for s in ("WT_1", "WT_2", "KO_1", "KO_2")),
                ("design.well_role", "water", {"role": "ntc"}),
                ("design.comparison", "comparison", {"group_a": "KO", "group_b": "WT"}),
            ],
        )
        page.settle(sid, "design", accept=False)
        page.confirm(sid, "design")
        page.job(page.client.post(f"/api/sessions/{sid}/propose/curves"))
        table = page.get(f"/api/sessions/{sid}/cq-table")
        sources = {
            e["target"]: (e["source"], round(e["efficiency"], 3)) for e in table["efficiencies"]
        }
        assert sources == {"GAPDH": ("dilution_series", 1.968), "1-Mar": ("dilution_series", 1.949)}
        assert table["counts"]["n_controls_with_cq"] == 1  # the late well of the NTC on 1-Mar
        page.settle(sid, "curves", accept=True)
        job = wait_job(page.client, page.confirm(sid, "curves")["job"])
        study = job["result"]["study_id"]
        results = page.get(f"/api/studies/{study}/results")
        efficiency = next(a for a in results["axes"] if a["name"] == "efficiency")
        assert efficiency["can_propose"] and "dilution series" in efficiency["text"]["plain"]
        offer = page.ok(
            page.client.post(f"/api/sessions/{sid}/propose/axis", json={"axis": "efficiency"})
        )
        proposal = offer["outcome"]["proposal"]
        assert proposal["payload"] == {"options": ["linregpcr", "assumed_2"]}
        assert "has Cq values only" in proposal["reasons"][0]
        evidence = {i["id"]: i for i in page.get(f"/api/studies/{study}/evidence")["items"]}
        assert evidence["efficiency"]["status"] == "present"
    finally:
        page.ctx.close()


def test_the_soybean_rdml_of_cq_values_opens_with_one_note_per_experiment(tmp_path, monkeypatch):
    monkeypatch.setenv("QPILOT_CACHE_DIR", str(tmp_path / "cache"))
    page = Page(tmp_path)
    try:
        files = {"rdml": (SOYBEAN.name, SOYBEAN.read_bytes(), "application/xml")}
        sid = page.job(page.client.post("/api/workspaces", files=files))["key"]
        notes = page.get(f"/api/sessions/{sid}")["summary"]["notes"]
        assert sum("holds Cq values only" in n for n in notes) == 3
        assert not any("could not analyse" in n for n in notes)
        assert page.ctx.studio.cq_only(sid)
    finally:
        page.ctx.close()
