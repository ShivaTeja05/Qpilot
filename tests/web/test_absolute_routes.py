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
    assert c.post(url, json={"template_ul": 2, "input_ng": 10}).status_code == 422  # no reason
    assert c.post(url, json={"template_ul": -1, "reason": "x"}).status_code == 422
    head = studio.head(sid)
    r = c.post(url, json={"template_ul": 2, "input_ng": 10, "reason": "2 µL of cDNA from 10 ng"})
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
        json={"template_ul": 2, "input_ng": 10, "reason": "same"},
    )
    assert again.status_code == 200 and again.json()["status"] == "unchanged"


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
