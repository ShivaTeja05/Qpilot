"""History routes: the decision chain replayed on the study's own grid, diffed and compared.

On the real demo study (Vermeulen 2009, 64 plates; analysed once per module, copied per test):
replaying to the head gives exactly the numbers the Results section shows; deciding a card and
diffing the step before and after lists exactly the genes the flip matrix says that option
flips; a changed chain entry is caught. Two analyses of the demo file (the planned design and
the same design with one well left out, as a Prism round trip makes) are compared against the
engine's own stored results. The blind rule and the Studio log are checked on the walked mini
session (tests/web/conftest.py).
"""

from __future__ import annotations

import json
import math
import shutil

import pytest
from fastapi.testclient import TestClient

from qpilot.core.store import StudyStore
from qpilot.web.context import make_context
from qpilot.web.server import create_app
from tests.web.conftest import BASE, TOKEN
from tests.web.test_studio_flow import no_html

EXCLUDED = "ODC1_20080226/A3"  # sample 1496's ODC1 well: the demo walk's Prism round trip


@pytest.fixture(scope="module")
def demo_studies(tmp_path_factory):
    """The demo file analysed as planned, and again with one ODC1 well left out."""
    from qpilot.io.datasets import default_cache_dir
    from qpilot.qpcr.designs import vermeulen_design

    rdml = default_cache_dir() / "data_vermeulen_raw.rdml"
    if not rdml.exists():
        pytest.skip("demo dataset not cached; run `qpilot fetch-demo`")
    base = tmp_path_factory.mktemp("history") / "studies"
    store = StudyStore(base)
    planned = store.ensure_study(rdml)
    design = vermeulen_design().model_copy(update={"excluded_wells": (EXCLUDED,)})
    excluded = store.ensure_study(rdml, design=design)
    return base, planned, excluded


@pytest.fixture
def demo(demo_studies, tmp_path):
    base, planned, excluded = demo_studies
    shutil.copytree(base, tmp_path / "studies")
    store = StudyStore(tmp_path / "studies")
    ctx = make_context(store, token=TOKEN, watch=False)
    with TestClient(create_app(ctx), base_url=BASE) as c:
        c.headers["x-qpilot-token"] = TOKEN
        c.headers["origin"] = BASE
        yield c, store, planned, excluded
    ctx.close()


def history(c, study):
    r = c.get(f"/api/studies/{study}/history")
    assert r.status_code == 200, r.text
    return r.json()


def decide(c, store, study, card, option, reason="a test decision"):
    r = c.post(
        f"/api/studies/{study}/cards/{card}/decide",
        json={"option": option, "reason": reason, "expected_head": store.chain_head(study)},
    )
    assert r.status_code == 200, r.text
    return r.json()


def same(a, b):
    return a is b if a is None or b is None else a == b


def assert_head_is_results(c, study, view):
    """The head's analysis is exactly what the Results section shows for every gene."""
    results = c.get(f"/api/studies/{study}/results").json()
    head = view["analyses"][view["steps"][-1]["analysis"]]
    by_gene = dict(zip(view["genes"], head["genes"], strict=True))
    assert [g["gene"] for g in results["genes"]] == view["genes"]
    for row in results["genes"]:
        mine = by_gene[row["gene"]]
        yours = row["at_your_choices"]
        if yours is None:
            assert head["planned"]
            assert mine["conclusion"] == row["conclusion"]
            assert mine["log2fc"] == row["log2fc"] and mine["fc"] == row["fc"]
            assert same(mine["p"], row["p"]) and mine["holds"] == row["holds"]
        else:
            assert not head["planned"]
            assert mine["conclusion"] == yours["conclusion"]
            assert mine["log2fc"] == yours["log2fc"] and mine["fc"] == yours["fc"]
            assert same(mine["p"], yours["p"])
    assert head["counts"] == {
        k: sum(1 for g in by_gene.values() if g["conclusion"] == k) for k in ("up", "down", "none")
    }


@pytest.mark.demo_data
def test_replaying_to_the_head_reproduces_the_results(demo):
    c, store, study, _ = demo
    view = history(c, study)
    no_html(view)
    assert view["replayable"] and view["chain_intact"] and view["note"] is None
    assert view["root"] == store.get(study).input_sha256
    assert view["head"] == store.chain_head(study)
    entries = store.entries(study)
    assert [s["seq"] for s in view["steps"]] == list(range(len(entries) + 1))
    assert view["steps"][0]["kind"] == "start" and view["steps"][0]["hash"] == view["root"]
    for step, entry in zip(view["steps"][1:], entries, strict=True):
        assert step["hash"] == entry.hash and step["prev_hash"] == entry.prev_hash
        assert step["actor"] == entry.actor and step["status"] == entry.status
    assert_head_is_results(c, study, view)
    # step 0 is the analysis as planned: the stored contrasts and robustness, exactly
    planned = view["analyses"][view["steps"][0]["analysis"]]
    result = store.get(study)
    assert planned["planned"]
    for gene in planned["genes"]:
        assert gene["log2fc"] == result.contrasts[gene["gene"]].log2fc
        assert gene["holds"] == result.robustness[gene["gene"]].holds

    # a person picks another cut-off: the head moves to that grid cell, still equal to Results
    decide(c, store, study, "card_cutoff", "cut_20")
    view = history(c, study)
    assert len(view["analyses"]) == 2
    assert_head_is_results(c, study, view)
    head = view["analyses"][view["steps"][-1]["analysis"]]
    cut = next(ch for ch in head["choices"] if ch["dimension"] == "cut")
    assert cut["value"] == "0.2" and not cut["planned"]
    # holds under that analysis = the core's definition, on the stored grid
    from qpilot.core.robustness import holds_fraction
    from qpilot.web.results_views import load_grid

    grid = load_grid(store, store.get(study)).frame
    for gene in head["genes"][:10]:
        assert math.isclose(
            gene["holds"], holds_fraction(grid, gene["gene"], gene["conclusion"]), abs_tol=1e-12
        )
    in_force = {ch["card_id"]: ch for ch in view["steps"][-1]["choices"]}
    assert in_force["card_cutoff"]["option"] == "cut_20" and in_force["card_cutoff"]["decided"]
    assert in_force["card_cutoff"]["decided_by"] == "human"


@pytest.mark.demo_data
def test_a_diff_after_a_decision_lists_exactly_the_genes_that_option_flips(demo):
    c, store, study, _ = demo
    flips = c.get(f"/api/studies/{study}/flips").json()
    row = next(r for r in flips["rows"] if r["card_id"] == "card_cutoff")
    option = next(o for o in row["options"] if o["card_option"] == "cut_20")
    expected = {g for g, flipped in zip(flips["genes"], option["flips"], strict=True) if flipped}
    assert expected  # the demo's 20 % cut-off changes calls

    decide(c, store, study, "card_cutoff", "cut_15", "the planned cut-off")
    decide(c, store, study, "card_cutoff", "cut_20", "the lab's own cut-off")
    view = history(c, study)
    last = view["steps"][-1]
    assert last["card_id"] == "card_cutoff" and last["option"] == "cut_20"
    assert last["reason"] == "the lab's own cut-off"
    assert set(last["conclusions"]["changed"]) == expected
    assert last["conclusions"]["n_changed"] == len(expected)

    seq = last["seq"]
    r = c.get(f"/api/studies/{study}/history/diff", params={"from": seq - 1, "to": seq})
    assert r.status_code == 200, r.text
    diff = r.json()
    no_html(diff)
    assert {g["gene"] for g in diff["calls_changed"]} == expected
    assert not diff["same_analysis"]
    assert [(ch["card_id"], ch["from_option"], ch["to_option"]) for ch in diff["choices"]] == [
        ("card_cutoff", "cut_15", "cut_20")
    ]
    for change in diff["calls_changed"]:
        i = flips["genes"].index(change["gene"])
        assert change["to_conclusion"] == option["conclusion"][i]
        assert math.isclose(change["to_log2fc"], option["log2fc"][i], abs_tol=1e-12)
    # the card's own consequence for the headline genes says the same
    card = c.get(f"/api/studies/{study}/cards/card_cutoff").json()
    effects = next(o for o in card["options"] if o["id"] == "cut_20")["effects"]
    for effect in effects:
        assert effect["changes_call"] == (effect["gene"] in expected)
    assert diff["to_counts"] == view["analyses"][last["analysis"]]["counts"]
    assert len(diff["fold_moves"]) <= 12
    moves = [abs(g["delta_log2fc"]) for g in diff["fold_moves"]]
    assert moves == sorted(moves, reverse=True)

    # Undo restores the planned analysis: the diff from step 0 to the head is empty
    r = c.post(
        f"/api/studies/{study}/cards/card_cutoff/undo",
        json={"reason": "back to the planned cut-off", "expected_head": store.chain_head(study)},
    )
    assert r.status_code == 200, r.text
    view = history(c, study)
    assert view["steps"][-1]["undo"] and view["steps"][-1]["analysis"] == 0
    assert set(view["steps"][-1]["conclusions"]["changed"]) == expected
    head = view["steps"][-1]["seq"]
    diff = c.get(f"/api/studies/{study}/history/diff", params={"from": 0, "to": head}).json()
    assert diff["same_analysis"] and diff["calls_changed"] == [] and diff["n_moved"] == 0


@pytest.mark.demo_data
def test_a_changed_entry_breaks_the_chain(demo):
    c, store, study, _ = demo
    decide(c, store, study, "card_refset", "recommended", "geNorm's pick")
    log = store.workspace(study) / "decisions.jsonl"
    lines = log.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["reason"] = first["reason"] + " (edited later)"
    lines[0] = json.dumps(first, sort_keys=True, separators=(",", ":"))
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    view = history(c, study)
    assert not view["chain_intact"] and view["broken_at"] == 1
    assert view["steps"][0]["link_ok"]
    assert not view["steps"][1]["link_ok"] and not view["steps"][-1]["chain_intact"]


@pytest.mark.demo_data
def test_two_analyses_of_the_demo_file_are_compared(demo):
    c, store, planned, excluded = demo
    r = c.get(f"/api/studies/{excluded}/history/compare", params={"other": planned})
    assert r.status_code == 200, r.text
    body = r.json()
    no_html(body)
    a, b = store.get(planned), store.get(excluded)
    assert body["before"]["study_id"] == planned and body["after"]["study_id"] == excluded
    assert [d["field"] for d in body["design"]] == ["excluded_wells"]
    assert body["design"][0]["added"] == [EXCLUDED] and body["design"][0]["removed"] == []
    assert body["choices"] == []
    differs = {g for g in a.contrasts if a.contrasts[g].conclusion != b.contrasts[g].conclusion}
    assert {g["gene"] for g in body["calls_changed"]} == differs
    moved = {g for g in a.contrasts if abs(a.contrasts[g].log2fc - b.contrasts[g].log2fc) > 1e-9}
    assert body["n_moved"] == len(moved) and "ODC1" in moved
    odc1 = next(g for g in body["fold_moves"] if g["gene"] == "ODC1")
    assert odc1["from_log2fc"] == a.contrasts["ODC1"].log2fc
    assert odc1["to_log2fc"] == b.contrasts["ODC1"].log2fc
    assert odc1["from_holds"] == a.robustness["ODC1"].holds
    assert odc1["to_holds"] == b.robustness["ODC1"].holds
    # same choices on both sides: everything that changed, the design did
    assert body["decomposed"] and body["by_choices"] == 0 and body["by_design"] == len(differs)
    assert all(g["cause"] == "design" for g in body["calls_changed"])
    # the same question asked from the other side gives the same order
    other = c.get(f"/api/studies/{planned}/history/compare", params={"other": excluded}).json()
    assert other["before"]["study_id"] == planned and other["n_moved"] == body["n_moved"]
    # each history lists the other analysis of the file
    related = history(c, excluded)["related"]
    assert [x["study_id"] for x in related] == [planned]


@pytest.mark.demo_data
def test_choices_and_design_are_told_apart(demo):
    c, store, planned, excluded = demo
    decide(c, store, excluded, "card_cutoff", "cut_20", "the lab's own cut-off")
    body = c.get(f"/api/studies/{excluded}/history/compare", params={"other": planned}).json()
    assert [(x["card_id"], x["to_option"]) for x in body["choices"]] == [("card_cutoff", "cut_20")]
    assert body["decomposed"] and body["by_choices"] > 0
    causes = {g["cause"] for g in body["calls_changed"]}
    assert "choices" in causes and causes <= {"design", "choices", "both"}


@pytest.mark.demo_data
def test_requests_that_cannot_be_answered(demo):
    c, store, planned, excluded = demo
    n = len(store.entries(planned))
    for params in ({"from": 0, "to": n + 1}, {"from": -1, "to": 0}, {"from": "a", "to": 0}):
        r = c.get(f"/api/studies/{planned}/history/diff", params=params)
        assert r.status_code == 422, r.text
    r = c.get(f"/api/studies/{planned}/history/compare", params={"other": planned})
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_request"
    r = c.get(f"/api/studies/{planned}/history/compare", params={"other": "0123456789ab"})
    assert r.status_code == 404
    r = c.get(f"/api/studies/{planned}/history/compare", params={"other": "../../etc"})
    assert r.status_code in (404, 422)
    assert c.get("/api/studies/0123456789ab/history").status_code == 404


# ---- a Studio session: the blind rule and the Studio log ----------------------------------------


def test_the_studio_log_is_shown_by_stage_and_ties_the_study_to_its_confirmation(walked):
    c, study, store = walked["client"], walked["study"], walked["store"]
    view = history(c, study)
    no_html(view)
    assert view["session"] == walked["sid"] and view["studio_intact"]
    stages = [m["stage"] for m in view["studio"]]
    assert stages[:2] == ["design", "curves"]
    design, curves = view["studio"][0], view["studio"][1]
    assert design["confirmed"] and curves["confirmed"] and design["before"] and curves["before"]
    assert curves["led_to"] == study
    entries = store.proposals(walked["sid"]).entries()
    assert view["studio"][-1]["last_seq"] == len(entries)
    assert view["studio"][-1]["head"] == entries[-1].hash
    total = sum(m["n_proposed"] for m in view["studio"])
    assert total == sum(1 for e in entries if e.action == "propose")


def test_a_changed_studio_entry_is_caught(walked):
    c, study, store = walked["client"], walked["study"], walked["store"]
    log = store.find_session(walked["sid"]) / "proposals.jsonl"
    lines = log.read_text(encoding="utf-8").splitlines()
    second = json.loads(lines[1])
    second["at"] = "2001-01-01T00:00:00Z"
    lines[1] = json.dumps(second, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    view = c.get(f"/api/studies/{study}/history")
    # Studio refuses a damaged inbox, so the session shows nothing from it: said in words
    assert view.status_code == 409, view.text
    assert view.json()["error"]["code"] == "studio"
    assert "does not verify" in view.json()["error"]["message"]
    # the engine still reads the log, and marks where it breaks
    from qpilot.history.studio import milestones

    runs, _, intact = milestones(store.find_session(walked["sid"]))
    assert not intact and not runs[0].chain_intact


def test_history_is_blind_until_the_session_is_confirmed_again(walked):
    from qpilot.mcp_server import QpilotTools

    c, study, store, studio, sid = (
        walked["client"],
        walked["study"],
        walked["store"],
        walked["studio"],
        walked["sid"],
    )
    assert c.get(f"/api/studies/{study}/history").status_code == 200
    QpilotTools(store).qpcr_propose(sid, "design.group", "WT_1", {"group": "KO"})
    change = next(p for p in studio.inbox(sid, "design", "proposed") if p.kind == "design.group")
    studio.accept(sid, change.id, "human", "the lab book says KO")
    for path, params in (
        (f"/api/studies/{study}/history", None),
        (f"/api/studies/{study}/history/diff", {"from": 0, "to": 0}),
        (f"/api/studies/{study}/history/compare", {"other": study}),
    ):
        r = c.get(path, params=params)
        assert r.status_code == 403, r.text
        assert r.json()["error"]["code"] == "blind"
