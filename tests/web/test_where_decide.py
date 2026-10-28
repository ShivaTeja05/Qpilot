"""Trace's Decide… applied in a Studio session: the wells a person sets aside leave the analysis.

The mini file with both knock-outs late on ``1-Mar`` (so the gene is called down) and an early
no-template control on that plate: Where to look points at ``KO_1``'s ``1-Mar`` well (it comes up
within the NTC's window), and setting its value (or the sample) aside changes the call. Here a
person decides over HTTP, Run Gate's path:

* a set-aside writes one ``curve.exclude_well`` per well to the session's inbox (made by Trace,
  accepted by the person with the reason, in one write), the study is analysed again without
  them (the ``analyse`` job), and the person's earlier Decision Card choice is carried to it;
* what is set aside is listed (``…/set-aside``), and "Put the wells back" returns the analysis to
  the first one, byte for byte the same study;
* "keep" with nothing to put back records the keep (Trace's exclusions, rejected with the
  reason) and changes nothing;
* choosing another option at the same place puts back only what was set aside there: a well a
  person left out in Curves stays out;
* refusals: no reason, an option the place does not have, a stale view, a decision on an
  analysis that is no longer the session's, a study analysed outside Studio (the view says to
  open it in Studio).
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from qpilot.core.decisions import apply_decision
from qpilot.core.proposals import verify_proposal_chain
from qpilot.qpcr import trace as trace_engine
from qpilot.studio_service import EXCLUDE_KIND, TRACE_MAKER, trace_card_of
from qpilot.web.routers import where as where_router
from tests.web.conftest import BASE, TOKEN, wait_job, walk_mini

GENE = "1-Mar"
REASON = "The NTC on this plate amplified within five cycles of the knock-outs."


@pytest.fixture(scope="module")
def called_walked(tmp_path_factory):
    """The mini file with 1-Mar called down and an early NTC on its plate, walked once."""
    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.core.store import StudyStore
    from qpilot.qpcr import design_checks
    from qpilot.qpcr import inspect as qinspect
    from qpilot.studio_service import Studio
    from tests.fixtures.studio import studio_mini

    base = tmp_path_factory.mktemp("called")
    root = base / "data"
    root.mkdir()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("QPILOT_DATA_ROOTS", str(root))
        mp.setenv("QPILOT_STUDIES_DIR", str(base / "studies"))
        plate = dict(studio_mini.PLATES[GENE])
        plate.update(NTC=[None, None, 30.5], KO_1=[28.0, 28.1, 27.9], KO_2=[28.2, 28.3, 28.1])
        mp.setitem(studio_mini.PLATES, GENE, plate)
        qinspect.clear_cache()
        rdml = studio_mini.write_studio_mini(root / "mini.rdml")
        studio = Studio(StudyStore(base / "studies"), client=ModelClient(backend=NoneBackend()))
        sid, study_id = walk_mini(studio, rdml)
        design_checks._DECLARED.clear()
        design_checks.set_input_resolver(None)
        qinspect.clear_cache()
    return {"base": base, "root": root, "sid": sid, "study": study_id}


@pytest.fixture
def called(called_walked, tmp_path, monkeypatch):
    from qpilot.ai.client import ModelClient, NoneBackend
    from qpilot.core.store import StudyStore
    from qpilot.qpcr import design_checks
    from qpilot.qpcr import inspect as qinspect
    from qpilot.studio_service import Studio
    from qpilot.web.context import make_context
    from qpilot.web.server import create_app

    shutil.copytree(called_walked["base"], tmp_path / "w", symlinks=False)
    monkeypatch.setenv("QPILOT_DATA_ROOTS", str(called_walked["root"]))
    monkeypatch.setenv("QPILOT_STUDIES_DIR", str(tmp_path / "w" / "studies"))
    qinspect.clear_cache()
    where_router.clear()
    store = StudyStore(tmp_path / "w" / "studies")
    studio = Studio(store, client=ModelClient(backend=NoneBackend()))
    ctx = make_context(store, studio, token=TOKEN, watch=False)
    with TestClient(create_app(ctx), base_url=BASE) as c:
        c.headers["x-qpilot-token"] = TOKEN
        c.headers["origin"] = BASE
        yield {"client": c, "store": store, "studio": studio, **called_walked}
    ctx.close()
    where_router.clear()
    design_checks._DECLARED.clear()
    design_checks.set_input_resolver(None)
    qinspect.clear_cache()


def where(c, study: str, **query) -> dict:
    """One Where to look answer, waiting out the first read of the study's wells."""
    for _ in range(200):
        r = c.get(f"/api/studies/{study}/where-to-look", params=query)
        if r.status_code == 409 and r.json()["error"]["code"] == "loading":
            wait_job(c, r.json()["error"]["details"]["job"])
            continue
        assert r.status_code == 200, r.text
        return r.json()
    raise AssertionError("never ready")


def set_aside(c, study: str) -> dict:
    r = c.get(f"/api/studies/{study}/where-to-look/set-aside")
    assert r.status_code == 200, r.text
    return r.json()


def decide(c, study: str, view: dict, option: str, reason: str = REASON, rank: int = 1, **kw):
    body = {
        "kind": view["root"]["kind"],
        "id": view["root"]["id"],
        "rank": rank,
        "option": option,
        "reason": reason,
        "expected_head": view["head"],
        "expected_inbox": view["inbox_head"],
        **kw,
    }
    return c.post(f"/api/studies/{study}/where-to-look/decide", json=body)


def analysed(c, sid: str, answer: dict) -> str:
    """Wait for the analysis a decision started; the session's study id after it."""
    if answer.get("job"):
        job = wait_job(c, answer["job"])
        assert job["status"] == "done", job
    frame = c.get(f"/api/sessions/{sid}").json()
    assert frame["results_visible"]
    return frame["study_id"]


def first_place(view: dict) -> dict:
    place = view["places"][0]
    assert place["sample"] == "KO_1" and place["target"] == GENE and place["can_decide"]
    return place


def test_the_view_says_decide_applies_here(called):
    c, study = called["client"], called["study"]
    view = where(c, study, gene=GENE)
    assert view["can_apply"] is True and view["session"] == called["sid"]
    assert view["inbox_head"] == called["studio"].head(called["sid"])
    assert "leaves the wells out of the analysis" in view["apply_note"]
    assert view["decide_note"] == view["apply_note"] and view["set_aside"] == []
    options = {o["id"]: o for o in first_place(view)["options"]}
    assert options["keep"]["applies"] and options["keep"]["n_wells"] == 0
    assert options["set_aside_value"]["applies"] and options["set_aside_value"]["n_wells"] == 3
    assert options["set_aside"]["applies"] and options["set_aside"]["n_wells"] == 6  # 2 genes


def test_setting_a_value_aside_is_recorded_analysed_again_and_carried(called):
    c, store, studio = called["client"], called["store"], called["studio"]
    sid, study = called["sid"], called["study"]
    # a person's earlier choice on a Decision Card of the analysis
    head = store.chain_head(study)
    apply_decision(store, study, "card_undetermined", "cap", "Caps the empty wells.", "human", head)
    view = where(c, study, gene=GENE)
    assert view["planned"] is False  # traced at the analysis in use (the person's choice)
    place = first_place(view)
    r = decide(c, study, view, "set_aside_value")
    assert r.status_code == 200, r.text
    done = r.json()
    wells = sorted(f"{place['plate']}/{w}" for w in ("A7", "A8", "A9"))
    assert done["status"] == "left_out" and done["left_out"] == wells and done["put_back"] == []
    assert done["card_id"] == place["card_id"] and done["study_id"] == study
    assert done["message"].startswith("Left out 3 wells") and "carried" in done["message"]
    assert done["job"] and done["job"]["kind"] == "analyse"
    new = analysed(c, sid, done)
    assert new != study

    # the record: one proposal per well, made by Trace, accepted by the person with the reason
    inbox = store.proposals(sid)
    mine = inbox.proposals(kind_prefix=EXCLUDE_KIND)
    assert sorted(p.subject for p in mine) == wells
    for p in mine:
        assert p.status == "accepted" and p.decided_by == "human" and p.reason == REASON
        assert p.payload == {"excluded": True} and p.made_by.kind == "rule"
        assert p.made_by.provider == TRACE_MAKER and trace_card_of(p) == place["card_id"]
        assert set(p.consequence) == {"matters", "trace"} and p.consequence["matters"] is True
        # blind-safe like Run Gate's: the place and the option, never a gene's result
        assert set(p.consequence["trace"]) == {"card_id", "option", "study_id", "sample", "well"}
    entries = inbox.entries()
    assert verify_proposal_chain(entries, inbox.root) is None
    clicks = [e for e in entries if e.proposal_id in {p.id for p in mine}]
    assert {e.actor for e in clicks if e.action == "accept"} == {"human"}
    assert len({e.at for e in clicks}) == 1  # one click, one moment
    assert set(store.design(new).excluded_wells) == set(wells)

    # the new analysis: KO_1 has no 1-Mar value, so 1-Mar can no longer be compared
    assert GENE in store.get(study).contrasts and GENE not in store.get(new).contrasts
    # the person's choice on the Decision Card is carried to it
    carried = studio.carried(sid, new)
    assert carried is not None and "card_undetermined" in carried["carried"]
    card = next(x for x in store.cards(new) if x.id == "card_undetermined")
    assert (card.decision, card.decided_by) == ("cap", "human")

    # Trace at the new analysis: the gene has no comparison; the sample says why
    r = c.get(f"/api/studies/{new}/where-to-look", params={"gene": GENE})
    assert r.status_code == 404
    listed = set_aside(c, new)
    assert listed["can_apply"] and listed["session"] == sid
    (entry,) = listed["set_aside"]
    assert entry["card_id"] == place["card_id"] and entry["wells"] == wells
    assert (entry["sample"], entry["plate"], entry["well"]) == ("KO_1", place["plate"], "A7")
    assert entry["target"] == GENE and entry["reason"] == REASON and entry["matters"] is True
    assert entry["option"] == "set_aside_value" and entry["option_label"].startswith("Set this")
    why = where(c, new, sample="KO_1")
    assert why["root"] == {"kind": "sample", "id": "KO_1"}


def test_put_the_wells_back_returns_to_the_first_analysis(called):
    c, store, sid, study = called["client"], called["store"], called["sid"], called["study"]
    view = where(c, study, gene=GENE)
    done = decide(c, study, view, "set_aside").json()
    assert done["status"] == "left_out" and len(done["left_out"]) == 6
    new = analysed(c, sid, done)
    listed = set_aside(c, new)
    (entry,) = listed["set_aside"]
    assert entry["option"] == "set_aside" and len(entry["wells"]) == 6
    body = {"card_id": entry["card_id"], "reason": " ", "expected_inbox": listed["inbox_head"]}
    no_reason = c.post(f"/api/studies/{new}/where-to-look/put-back", json=body)
    assert no_reason.status_code == 422
    body["reason"] = "The repeat plate's NTC stayed flat."
    r = c.post(f"/api/studies/{new}/where-to-look/put-back", json=body)
    assert r.status_code == 200, r.text
    back = r.json()
    assert back["status"] == "put_back" and back["put_back"] == entry["wells"]
    assert back["message"].startswith("Put 6 wells back")
    again = analysed(c, sid, back)
    assert again == study  # the same design: the first analysis, the same study
    assert store.design(again).excluded_wells == ()
    assert set_aside(c, again)["set_aside"] == []
    # nothing left to put back
    gone = c.post(f"/api/studies/{again}/where-to-look/put-back", json=body)
    assert gone.status_code == 404


def test_keep_with_nothing_to_put_back_records_the_keep(called):
    c, store, sid, study = called["client"], called["store"], called["sid"], called["study"]
    view = where(c, study, gene=GENE)
    r = decide(c, study, view, "keep", reason="I looked at the curve and the NTC's melt peak.")
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "kept" and done["job"] is None
    assert done["message"].startswith("Kept the wells")
    mine = store.proposals(sid).proposals(kind_prefix=EXCLUDE_KIND)
    assert len(mine) == 3 and {p.status for p in mine} == {"rejected"}
    assert {p.decided_by for p in mine} == {"human"}
    assert c.get(f"/api/sessions/{sid}").json()["study_id"] == study


def test_another_option_puts_back_only_what_was_set_aside_there(called):
    from qpilot.mcp_server import QpilotTools

    c, store, studio = called["client"], called["store"], called["studio"]
    sid, study = called["sid"], called["study"]
    # a person leaves one of KO_1's GAPDH wells out in Curves first
    tools = QpilotTools(store)
    wells = trace_engine._store_context(store, study).wells
    ko_1 = wells[(wells["unit"] == "KO_1") & (wells["target"] == "GAPDH")]
    gapdh = sorted(ko_1.index)
    assert len(gapdh) == 3
    proposed = tools.qpcr_propose(sid, EXCLUDE_KIND, gapdh[0], {"excluded": True})
    studio.accept(sid, proposed["proposal"]["id"], "human", "A bubble in this well.")
    first = studio.study(sid)  # the Curves inbox analyses on first use
    view = where(c, first, gene=GENE)
    # set the whole sample aside, then only the 1-Mar value: the GAPDH wells set aside from
    # Trace come back, the one left out in Curves stays out
    done = decide(c, first, view, "set_aside").json()
    assert gapdh[0] not in done["left_out"] and len(done["left_out"]) == 5
    second = analysed(c, sid, done)
    listed = set_aside(c, second)["set_aside"]
    assert len(listed) == 1 and gapdh[0] not in listed[0]["wells"]
    body = {
        "card_id": listed[0]["card_id"],
        "reason": "Only the 1-Mar well is in question.",
        "expected_inbox": set_aside(c, second)["inbox_head"],
    }
    back = c.post(f"/api/studies/{second}/where-to-look/put-back", json=body).json()
    assert back["status"] == "put_back" and gapdh[0] not in back["put_back"]
    third = analysed(c, sid, back)
    assert set(store.design(third).excluded_wells) == {gapdh[0]}


def test_the_value_after_the_sample_puts_back_only_what_trace_set_aside(called):
    """Options are states of a place's wells: from the sample to its value, the rest is back."""
    from dataclasses import replace

    from qpilot.mcp_server import QpilotTools

    store, studio, sid, study = called["store"], called["studio"], called["sid"], called["study"]
    built = trace_engine._store_context(store, study)
    place = trace_engine.trace_gene(built, GENE).places[0]
    wells = built.wells
    gapdh = sorted(wells[(wells["unit"] == "KO_1") & (wells["target"] == "GAPDH")].index)
    marked = sorted(wells[(wells["unit"] == "KO_1") & (wells["target"] == GENE)].index)
    proposed = QpilotTools(store).qpcr_propose(sid, EXCLUDE_KIND, gapdh[0], {"excluded": True})
    studio.accept(sid, proposed["proposal"]["id"], "human", "A bubble in this well.")
    first = studio.study(sid)
    sample = replace(where_router._trace_choice(study, built, place, "set_aside"), study_id=first)
    done = studio.decide_trace(sid, sample, "human", "The whole tube is suspect.")
    assert done.status == "left_out" and done.left_out == sorted([*gapdh[1:], *marked])
    second = studio.study(sid)
    value = where_router._trace_choice(study, built, place, "set_aside_value")
    done = studio.decide_trace(sid, replace(value, study_id=second), "human", "Only 1-Mar.")
    assert done.status == "put_back" and done.put_back == gapdh[1:] and done.left_out == []
    third = studio.study(sid)
    assert set(store.design(third).excluded_wells) == {gapdh[0], *marked}  # Curves' stays out
    # an agent never decides; a stale analysis is refused without writing
    with pytest.raises(Exception, match="only a person"):
        studio.decide_trace(sid, replace(value, study_id=third), "agent", "no")
    stale = studio.decide_trace(sid, replace(value, study_id=first), "human", "late")
    assert stale.status == "stale"


def test_refusals(called, tmp_studies_dir, monkeypatch):
    c, study, sid = called["client"], called["study"], called["sid"]
    view = where(c, study, gene=GENE)
    assert decide(c, study, view, "set_aside", reason="  ").status_code == 422
    unknown = decide(c, study, view, "read_from_other_refs")  # a target well has no such option
    assert unknown.status_code == 422
    assert "no such option" in unknown.json()["error"]["message"]
    stale = decide(c, study, {**view, "head": "0" * 64}, "set_aside")
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale"
    stale = decide(c, study, {**view, "inbox_head": "0" * 64}, "set_aside")
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale"
    assert called["store"].proposals(sid).proposals(kind_prefix=EXCLUDE_KIND) == []
    # the analysis moves on: a decision on the old one is refused
    new = analysed(c, sid, decide(c, study, view, "set_aside_value").json())
    old = decide(c, study, where(c, study, gene=GENE), "set_aside")
    assert old.status_code == 409 and old.json()["error"]["code"] == "studio"
    assert set_aside(c, study)["can_apply"] is False
    assert new != study


def test_a_study_analysed_outside_studio_says_to_open_it_in_studio(tmp_studies_dir, monkeypatch):
    from qpilot.web.context import make_context
    from qpilot.web.server import create_app
    from tests.app.trace_toys import toy_store

    store, study_id, built, _ = toy_store(tmp_studies_dir)
    monkeypatch.setattr(where_router, "_context", lambda ctx, sid: built)
    ctx = make_context(store, token=TOKEN, watch=False)
    with TestClient(create_app(ctx), base_url=BASE) as c:
        c.headers["x-qpilot-token"] = TOKEN
        c.headers["origin"] = BASE
        view = c.get(f"/api/studies/{study_id}/where-to-look", params={"gene": "DOWN"}).json()
        assert view["can_apply"] is False and view["inbox_head"] is None
        assert "open the study's file in Studio" in view["apply_note"]
        assert "numbers stay as analysed" in view["decide_note"]
        body = {
            "kind": "gene",
            "id": "DOWN",
            "rank": 1,
            "option": "set_aside",
            "reason": "A bad tube.",
            "expected_head": view["head"],
        }
        r = c.post(f"/api/studies/{study_id}/where-to-look/decide", json=body)
        assert r.status_code == 409 and r.json()["error"]["code"] == "studio"
        assert "open the study's file in Studio" in r.json()["error"]["message"]
        listed = c.get(f"/api/studies/{study_id}/where-to-look/set-aside").json()
        assert listed["can_apply"] is False and listed["set_aside"] == []
    ctx.close()
