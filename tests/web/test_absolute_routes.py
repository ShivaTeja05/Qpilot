"""Quantities routes over the walked mini study (a ten-fold STD_100..STD_10000 series per plate).

The standard curves and each unit's quantity come from the study's file and confirmed design;
the numbers equal the engine's (:mod:`qpilot.qpcr.absolute`); the routes are blind like every
result; a person records the reaction input with a reason (the study is analysed again, the
blind stages stay confirmed, quantities per µL and per ng follow); the exports, Methods and
MIQE items carry it; ng to copies is the formula by hand.
"""

from __future__ import annotations

import math

import pytest

from qpilot.mcp_server import QpilotTools
from qpilot.qpcr.absolute_study import for_study


def _quantities(c, study):
    r = c.get(f"/api/studies/{study}/quantities")
    assert r.status_code == 200, r.text
    return r.json()


def test_quantities_of_the_walked_study(walked):
    c, study, store = walked["client"], walked["study"], walked["store"]
    view = _quantities(c, study)
    assert view["available"] and view["groups_shown"] and view["can_set_reaction"]
    assays = {a["target"]: a for a in view["assays"]}
    assert set(assays) == {"GAPDH", "1-Mar"}
    curve = assays["GAPDH"]["curves"][0]
    assert curve["fitted"] and curve["n_levels"] == 3 and curve["quantity_source"] == "design"
    assert -3.7 < curve["slope"] < -3.0 and curve["r2"] > 0.99
    assert curve["efficiency_low"] < curve["efficiency"] < curve["efficiency_high"]
    assert curve["lod"]["at_most"] and curve["lod"]["quantity"] == 100.0
    engine = for_study(
        study, store.get(study).input_sha256, store.source(study), store.design(study)
    ).result
    (fit_curve,) = (x for x in engine.curves if x.id == curve["id"])
    assert curve["slope"] == fit_curve.fit.slope and curve["intercept"] == fit_curve.fit.intercept
    detail = c.get(f"/api/studies/{study}/quantities/GAPDH").json()
    units = {u["unit"]: u for u in detail["units"]}
    assert {"WT_1", "WT_2", "KO_1", "KO_2"} <= set(units)
    assert units["KO_1"]["group"] == "KO" and units["WT_1"]["group"] == "WT"
    ko = units["KO_1"]
    assert ko["low"] < ko["quantity"] < ko["high"] and ko["n_detected"] == 3
    x0, s = fit_curve.fit.inverse(sum(w["cq"] for w in ko["wells"]) / 3, 3)
    assert ko["quantity"] == pytest.approx(10**x0)
    assert len(detail["curves"][0]["band"]) == 41 and detail["curves"][0]["levels"]
    assert {p["sample"] for p in detail["curves"][0]["points"]} == {
        "STD_100",
        "STD_1000",
        "STD_10000",
    }
    assert c.get(f"/api/studies/{study}/quantities/NOPE").status_code == 404


def test_quantities_are_blind_until_the_session_is_confirmed_again(walked):
    c, study, sid, store, studio = (
        walked["client"], walked["study"], walked["sid"], walked["store"], walked["studio"]
    )  # fmt: skip
    assert c.get(f"/api/studies/{study}/quantities").status_code == 200
    QpilotTools(store).qpcr_propose(sid, "design.group", "WT_1", {"group": "KO"})
    change = next(p for p in studio.inbox(sid, "design", "proposed") if p.kind == "design.group")
    studio.accept(sid, change.id, "human", "the lab book says KO")
    assert not studio.results_visible(sid)
    for url in (f"/api/studies/{study}/quantities", f"/api/studies/{study}/quantities/GAPDH"):
        r = c.get(url)
        assert r.status_code == 403 and r.json()["error"]["code"] == "blind", r.text
        assert "quantity" not in r.text


def test_a_person_records_the_reaction_input(walked):
    c, study, sid, studio = walked["client"], walked["study"], walked["sid"], walked["studio"]
    url = f"/api/studies/{study}/quantities/reaction"
    head = c.get(f"/api/studies/{study}/quantities").json()["inbox_head"]
    assert head == studio.head(sid)  # the view carries the inbox head the page sends back
    ask = {"template_ul": 2, "input_ng": 10, "expected_head": head}
    assert c.post(url, json=ask).status_code == 422  # no reason
    assert c.post(url, json={**ask, "template_ul": -1, "reason": "x"}).status_code == 422
    r = c.post(url, json={**ask, "reason": "2 µL of cDNA from 10 ng"})
    assert r.status_code == 200 and r.json()["status"] == "accepted", r.text
    assert r.json()["head"] != head
    assert studio.results_visible(sid)  # the blind stages stay confirmed
    accepted = [
        p for p in studio.store.proposals(sid).accepted() if p.kind == "choice.reaction_input"
    ]
    assert accepted and accepted[-1].made_by.kind == "person"
    new = studio.study(sid)
    assert new != study
    design = studio.store.design(new)
    assert design.reaction_input.template_ul == 2.0 and design.reaction_input.input_ng == 10.0
    detail = c.get(f"/api/studies/{new}/quantities/GAPDH").json()
    ko = next(u for u in detail["units"] if u["unit"] == "KO_1")
    assert ko["per_ul"] == pytest.approx(ko["quantity"] / 2) and ko["per_ng"] == pytest.approx(
        ko["quantity"] / 10
    )
    # the relative results are the same numbers (the reaction input changes no fold change)
    old, now = studio.store.get(study), studio.store.get(new)
    assert {g: r.log2fc for g, r in old.contrasts.items()} == {
        g: r.log2fc for g, r in now.contrasts.items()
    }
    again = c.post(
        f"/api/studies/{new}/quantities/reaction",
        json={
            "template_ul": 2,
            "input_ng": 10,
            "reason": "same",
            "expected_head": r.json()["head"],
        },
    )
    assert again.status_code == 200 and again.json()["status"] == "unchanged"


# RT-EX-012
def test_the_reaction_input_needs_the_head_the_page_showed(walked):
    """Two tabs: the later one no longer wins unseen. Without ``expected_head`` the request is
    refused (422); with a head that moved, 409 ``stale`` in words, and nothing is written."""
    c, study, sid, studio = walked["client"], walked["study"], walked["sid"], walked["studio"]
    url = f"/api/studies/{study}/quantities/reaction"
    shown = c.get(f"/api/studies/{study}/quantities").json()["inbox_head"]
    body = {"template_ul": 2, "input_ng": 10, "reason": "2 µL of cDNA from 10 ng"}
    missing = c.post(url, json=body)
    assert missing.status_code == 422, missing.text
    where = [p["where"] for p in missing.json()["error"]["details"]["problems"]]
    assert any("expected_head" in w for w in where)
    assert c.post(url, json={**body, "expected_head": ""}).status_code == 422
    first = c.post(url, json={**body, "expected_head": shown})  # the first tab
    assert first.status_code == 200, first.text
    head = studio.head(sid)
    second = c.post(  # the second tab, still showing the old head
        f"/api/studies/{studio.study(sid)}/quantities/reaction",
        json={**body, "template_ul": 5, "expected_head": shown},
    )
    assert second.status_code == 409, second.text
    error = second.json()["error"]
    assert error["code"] == "stale" and "read the quantities again" in error["message"]
    assert studio.head(sid) == head  # nothing written
    design = studio.store.design(studio.study(sid))
    assert design.reaction_input.template_ul == 2.0


def test_exports_methods_and_miqe_carry_the_curves(walked):
    from qpilot.report.tables import all_tables, build_tables

    c, study, store = walked["client"], walked["study"], walked["store"]
    tables = build_tables(store, study)
    names = [t.name for t in all_tables(tables)]
    assert names.index("standard_curves") == names.index("per_well") + 1
    curves = {r["assay"]: r for r in tables.quantities[0].records()}
    assert curves["GAPDH"]["levels"] == 3 and curves["GAPDH"]["lod"] == 100.0
    quantities = tables.quantities[1].records()
    ko = next(r for r in quantities if r["assay"] == "GAPDH" and r["biological_unit"] == "KO_1")
    assert ko["group"] == "KO" and ko["low"] < ko["quantity"] < ko["high"]
    report = c.get(f"/api/studies/{study}/report").json()
    paragraphs = {p["id"]: p for p in report["methods"]["paragraphs"]}
    assert "quantities" in paragraphs
    text = paragraphs["quantities"]["text"]["plain"]
    assert "standard curves" in text and "limit of quantification" in text
    assert {x["id"] for x in report["methods"]["citations"]} >= {"forootan2017", "miller2010"}
    status = {i["id"]: i for i in report["miqe"]["items"]}
    assert status["5.14"]["status"] == "met"
    assert status["5.13"]["status"] == "not_met"  # every level detected: bounded, not calculated
    assert "at or below the lowest standard" in status["5.13"]["evidence"]["plain"]


def test_copies_helper_is_the_formula_by_hand(walked):
    c = walked["client"]
    r = c.get("/api/tools/copies", params={"ng": 1, "length": 3000, "step": 10, "levels": 4})
    body = r.json()
    expected = 1e-9 * 6.02214076e23 / (3000 * 617.96 + 36.04)
    assert body["copies"] == pytest.approx(expected) and body["kind"] == "dsDNA"
    assert body["series"] == pytest.approx([expected / 10**i for i in range(4)])
    rna = c.get("/api/tools/copies", params={"ng": 2, "length": 500, "kind": "RNA"}).json()
    assert rna["copies"] == pytest.approx(2e-9 * 6.02214076e23 / (500 * 320.5 + 159.0))
    assert c.get("/api/tools/copies", params={"ng": 0, "length": 100}).status_code == 422
    assert (
        c.get("/api/tools/copies", params={"ng": 1, "length": 100, "kind": "x"}).status_code == 422
    )
    assert math.isfinite(body["copies_per_ng"])


def test_miqe_lod_is_met_when_a_series_reaches_non_detection(walked, monkeypatch):
    from qpilot.qpcr import absolute as ab
    from tests.qpcr.test_absolute import _plate

    levels = {1e5: 4, 1e4: 4, 1e3: 4, 1e2: 4, 1e1: 4}
    table = _plate(levels, detect=lambda q, i: not ((q == 1e1 and i >= 1) or (q == 1e2 and i == 3)))
    result = ab.quantify(table)
    monkeypatch.setattr("qpilot.report.methods.study_quantities", lambda c: result)
    report = walked["client"].get(f"/api/studies/{walked['study']}/report").json()
    item = next(i for i in report["miqe"]["items"] if i["id"] == "5.13")
    assert item["status"] == "met" and "95 %" in item["evidence"]["plain"]
    methods = next(p for p in report["methods"]["paragraphs"] if p["id"] == "quantities")
    assert "35 %" in methods["text"]["plain"] and "95 %" in methods["text"]["plain"]


def test_a_real_quantstudio_export_end_to_end(sclient):
    """QuantStudio 3 wastewater plate: standards set on the Design page, then Results."""
    from tests.web.quant_walk import walk

    done = walk(sclient)
    study = done["study"]
    view = _quantities(sclient, study)
    assays = {a["target"]: a for a in view["assays"]}
    assert set(assays) == {"Cov2", "PMMoV"} and not view["not_quantified"]
    cov2 = assays["Cov2"]["curves"][0]
    assert cov2["quantity_source"] == "design" and cov2["n_levels"] == 5 and cov2["n_wells"] == 15
    assert -3.45 < cov2["slope"] < -3.2 and cov2["r2"] > 0.99 and not cov2["warnings"]
    pmmov = assays["PMMoV"]["curves"][0]
    assert any("outside" in w for w in pmmov["warnings"])  # efficiency far above 110 %
    detail = sclient.get(f"/api/studies/{study}/quantities/Cov2").json()
    units = {u["unit"]: u for u in detail["units"]}
    assert units["PR-231026-DNI-R1"]["group"] == "DNI"
    assert units["PR-231026-DSI-R1"]["group"] == "DSI"
    assert units["PR-231026-DCS-R1"]["group"] is None  # not in the comparison
    neg = units["PR-231026-NEG-R1"]
    assert neg["quantity"] is None and [f["id"] for f in neg["flags"]] == [
        "not_detected",
        "below_lod",
    ]
    quantified = [u for u in detail["units"] if u["quantity"] is not None]
    assert all(u["low"] < u["quantity"] < u["high"] for u in quantified)
    assert all(10 <= u["quantity"] <= 1e5 for u in quantified)  # inside the person's series
    results = sclient.get(f"/api/studies/{study}/results").json()
    assert [g["gene"] for g in results["genes"]] == ["Cov2"]
