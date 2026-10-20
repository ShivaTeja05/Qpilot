"""The planner routes on the walked mini study: every number equals ``qpilot.qpcr.plan``'s.

The study's noise is the pooled within-group SD of the engine's per-unit values (the values the
Prism bridge exports); the plan's numbers are ``n_needed``, ``n_for_call``, ``mde_fold``,
``mde_fold_groups``, ``simulate_calls`` and ``plan`` themselves; the plates are
``qpilot.qpcr.layout.make_layout``'s and the CSV reads back to the same wells. Nothing is written
to the study, and a session's study is blind again as soon as its design changes.
"""

from __future__ import annotations

import pytest

from qpilot.mcp_server import QpilotTools
from qpilot.qpcr import layout as lay
from qpilot.qpcr import plan as qplan
from qpilot.qpcr.export import study_inputs
from qpilot.web.routers import planner as planner_router


def _sigma_from_engine(store, study_id):
    inputs = study_inputs(store, study_id, read_only=True)
    table = inputs.table("column")
    out = {}
    for gene, block in table.groupby("gene", sort=False):
        values = [block.loc[block["group"] == g, "log2_rq"].tolist() for g in inputs.group_order]
        out[gene] = (*qplan.pooled_sd(values), [len(v) for v in values])
    return inputs.group_order, out


def test_the_planner_reads_the_studys_own_noise(walked):
    c, study, store = walked["client"], walked["study"], walked["store"]
    r = c.get(f"/api/studies/{study}/planner")
    assert r.status_code == 200, r.text
    view = r.json()
    order, engine = _sigma_from_engine(store, study)
    assert [g["label"] for g in view["groups"]] == list(order)
    assert view["genes"], "the mini study compares one gene"
    for gene in view["genes"]:
        sd, df, n = engine[gene["gene"]]
        assert gene["sigma"] == pytest.approx(sd, rel=1e-12)
        assert gene["df"] == df and gene["n"] == n
        assert tuple(gene["sigma_ci"]) == pytest.approx(qplan.sigma_interval(sd, df))
        assert gene["sigma_ci"][0] < gene["sigma"] < gene["sigma_ci"][1]
    result = store.get(study)
    assert view["refs"] == list(result.design.refs_primary)
    assert view["min_fold"] == 2.0 and view["alpha"] == result.conclusion_rule["alpha"]
    sizes = [g["n"] for g in view["groups"]]
    assert view["n_equivalent"] == pytest.approx(qplan.balanced_equivalent(*sizes))
    assert view["plates"]["n_plates"] == result.n_plates
    assert view["defaults"]["genes"] == [g for g in view["headline"] if g in engine]


def test_the_plans_numbers_are_the_plan_modules(walked):
    c, study = walked["client"], walked["study"]
    view = c.get(f"/api/studies/{study}/planner").json()
    sigma = {g["gene"]: g for g in view["genes"]}
    body = {"fold": 3.0, "power": 0.9, "n_per_group": 5, "plates": 2, "wells_per_plate": 96}
    r = c.post(f"/api/studies/{study}/planner", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    alpha, k = out["alpha"], 1.0
    assert out["n_plan"] == 5 and out["target"] == 3.0
    for row in out["genes"]:
        sd = sigma[row["gene"]]["sigma"]
        n_a, n_b = sigma[row["gene"]]["n"]
        assert row["n_needed"] == qplan.n_needed(3.0, sd, alpha, 0.9)
        assert row["mde_fold"] == pytest.approx(qplan.mde_fold(5, sd, alpha, 0.9))
        sig, called = qplan.simulate_calls(3.0, sd, 5, alpha, k)
        assert (row["p_significant"], row["p_called"]) == (sig, called)
        assert row["current_mde_fold"] == pytest.approx(
            qplan.mde_fold_groups(n_a, n_b, sd, alpha, 0.9)
        )
        assert (
            row["current_p_called"] == qplan.simulate_calls(3.0, sd, n_a, alpha, k, n_other=n_b)[1]
        )
        assert row["detectable"] == (row["mde_fold"] <= 3.0)
        if row["focus"]:
            assert row["n_for_call"] == qplan.n_for_call(3.0, sd, 0.9, alpha, k, n_max=1000)
            assert row["cannot_detect"] == qplan.plan(3.0, sd, 5, alpha, 0.9).cannot_detect
    for curve in out["curves"]:
        for point in curve["points"]:
            expected = qplan.simulate_calls(
                3.0, curve["sigma"], point["n"], alpha, k, planner_router.CURVE_REPS
            )
            assert (point["p_significant"], point["p_called"]) == expected
        ns = [p["n"] for p in curve["points"]]
        assert ns == sorted(set(ns)) and 5 in ns  # the plan's size is a point of every curve
    estimate = out["layout"]
    assert estimate is not None and out["layout_error"] is None
    assert out["budget"]["plates"] == 2 and out["budget"]["n_fit"] >= 2


def test_without_a_size_the_plan_uses_what_the_chosen_genes_need(walked):
    c, study = walked["client"], walked["study"]
    out = c.post(f"/api/studies/{study}/planner", json={"fold": 4.0}).json()
    focus = [g for g in out["genes"] if g["focus"]]
    wanted = max(g["n_for_call"] or g["n_needed"] for g in focus)
    assert out["n_plan"] == max(2, wanted)
    assert out["ceiling"] is None
    at_two = c.post(f"/api/studies/{study}/planner", json={"fold": 2.0}).json()
    assert at_two["ceiling"] and "threshold" in at_two["ceiling"]
    assert all(g["n_for_call"] is None for g in at_two["genes"] if g["focus"])
    down = c.post(f"/api/studies/{study}/planner", json={"fold": 0.25}).json()
    assert down["target"] == 4.0
    assert [g["n_needed"] for g in down["genes"]] == [g["n_needed"] for g in out["genes"]]


def test_the_rules_are_plans_rules_for_this_layout(walked):
    c, study = walked["client"], walked["study"]
    out = c.post(f"/api/studies/{study}/planner", json={"n_per_group": 40}).json()
    est = out["layout"]
    sd = out["genes"][0]["sigma"]
    rules = qplan.plan(
        2.0,
        sd,
        40,
        out["alpha"],
        0.8,
        n_plates=est["plates"],
        calibrator_on_every_plate=est["batches"] == 1 or est["calibrated"],
        n_candidate_refs=len(out["refs"]),
    ).rules
    assert out["rules"] == rules
    assert any("geNorm" in rule for rule in rules)  # the mini study normalises by one gene


def test_the_budget_is_the_largest_size_that_fits(walked):
    c, study = walked["client"], walked["study"]
    out = c.post(
        f"/api/studies/{study}/planner", json={"plates": 3, "wells_per_plate": 96, "replicates": 3}
    ).json()
    n_fit = out["budget"]["n_fit"]

    def plates(n):
        spec = lay.LayoutSpec(
            groups=tuple((g, n) for g in ("WT", "KO")),
            genes=tuple(out["focus"]),
            refs=tuple(out["refs"]),
            replicates=3,
            plate_size=96,
        )
        return lay.plates_needed(spec)

    assert plates(n_fit) <= 3 < plates(n_fit + 1)


@pytest.mark.parametrize(
    ("body", "where"),
    [
        ({"fold": 1}, "other than 1"),
        ({"fold": 5000}, "between"),
        ({"genes": ["NOT_A_GENE"]}, "not a compared gene"),
        ({"refs": ["NOT_A_GENE"]}, "not a gene of this study"),
        ({"power": 1.5}, "not valid"),
        ({"wells_per_plate": 100}, "not valid"),
        ({"n_per_group": 1}, "not valid"),
    ],
)
def test_bad_plans_are_refused_in_words(walked, body, where):
    c, study = walked["client"], walked["study"]
    r = c.post(f"/api/studies/{study}/planner", json=body)
    assert r.status_code == 422, r.text
    assert where in r.json()["error"]["message"] or where in str(r.json()["error"])


def _layout_body(view, **extra):
    return {"n_per_group": 6, "genes": view["headline"], "wells_per_plate": 96, **extra}


def test_the_layout_is_balanced_reproducible_and_its_csv_reads_back(walked):
    c, study = walked["client"], walked["study"]
    view = c.get(f"/api/studies/{study}/planner").json()
    body = _layout_body(view, seed=7, replicates=3, ntc=2, nrt=1, standards=2)
    r = c.post(f"/api/studies/{study}/planner/layout", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    again = c.post(f"/api/studies/{study}/planner/layout", json=body).json()
    assert again == out
    other = c.post(f"/api/studies/{study}/planner/layout", json={**body, "seed": 8}).json()
    assert [w["sample"] for p in other["plates"] for w in p["wells"]] != [
        w["sample"] for p in out["plates"] for w in p["wells"]
    ]
    b = out["balance"]
    assert b["refs_on_every_plate"] and b["controls_on_every_plate"] and b["each_reaction_once"]
    assert b["every_plate_every_group"] and b["plates_with_one_group"] == []
    for plate in out["plates"]:
        assert set(plate["refs"]) == set(out["refs"])
        assert {w["type"] for w in plate["wells"]} >= {"unkn", "ntc", "nrt", "std"}
    csv = c.get(out["csv_url"])
    assert csv.status_code == 200
    assert csv.headers["content-type"].startswith("text/csv")
    assert out["csv_name"] in csv.headers["content-disposition"]
    rows = lay.read_layout_csv(csv.text)
    wells = [
        (p["number"], w["well"], w["sample"], w["group"] or "", w["target"], w["type"])
        for p in out["plates"]
        for w in p["wells"]
    ]
    assert rows == wells


def test_the_layout_refuses_genes_outside_the_study_and_plates_too_small(walked):
    c, study = walked["client"], walked["study"]
    view = c.get(f"/api/studies/{study}/planner").json()
    r = c.post(f"/api/studies/{study}/planner/layout", json=_layout_body(view, genes=["=cmd|calc"]))
    assert r.status_code == 422 and "not a gene of this study" in r.json()["error"]["message"]
    r = c.post(
        f"/api/studies/{study}/planner/layout",
        json=_layout_body(view, n_per_group=1000, replicates=6),
    )
    assert r.status_code == 422 and "plates" in r.json()["error"]["message"]


def test_the_planner_writes_nothing(walked):
    c, study, store = walked["client"], walked["study"], walked["store"]
    folder = store.workspace(study)
    before = {p.name: p.stat().st_mtime_ns for p in folder.iterdir()}
    head = store.chain_head(study)
    view = c.get(f"/api/studies/{study}/planner").json()
    c.post(f"/api/studies/{study}/planner", json={"fold": 3})
    out = c.post(f"/api/studies/{study}/planner/layout", json=_layout_body(view)).json()
    c.get(out["csv_url"])
    assert store.chain_head(study) == head
    assert {p.name: p.stat().st_mtime_ns for p in folder.iterdir()} == before


def test_the_planner_is_blind_again_when_the_design_changes(walked):
    c, study, store, studio, sid = (
        walked["client"], walked["study"], walked["store"], walked["studio"], walked["sid"],
    )  # fmt: skip
    view = c.get(f"/api/studies/{study}/planner").json()
    QpilotTools(store).qpcr_propose(sid, "design.group", "WT_2", {"group": "KO"})
    pending = [p for p in studio.inbox(sid, "design", "proposed") if p.subject == "WT_2"]
    studio.accept(sid, pending[0].id, "human", "checked")
    for r in (
        c.get(f"/api/studies/{study}/planner"),
        c.post(f"/api/studies/{study}/planner", json={}),
        c.post(f"/api/studies/{study}/planner/layout", json=_layout_body(view)),
        c.get(
            f"/api/studies/{study}/planner/layout.csv",
            params={"n_per_group": 4, "genes": view["headline"]},
        ),
    ):
        assert r.status_code == 403 and r.json()["error"]["code"] == "blind", r.text[:200]


def test_ids_are_checked(walked):
    c = walked["client"]
    for key in ("../etc", "ABCDEF123456", "0" * 12):
        r = c.get(f"/api/studies/{key}/planner")
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
